"""Automation engine (in-house, no outside workflow product).

1. Features write domain events to `events` (the outbox).
2. dispatch() reads new events: applies stage rules, wakes runs waiting for that
   event, and starts runs for matching automations (one per project per event;
   a unique run_key stops doubles). Meeting-agent triggers are handled here too.
3. tick() picks runs whose wake_at has passed (with a lease, so two workers
   never run the same step), runs the next steps through the action layer and
   moves the pointer.
Every send step uses run_id + step_id as its idempotency key, so a retry or a
worker restart never sends twice.
"""
import asyncio
import copy
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from app.domain.registry import call
from app.core.context import system_ctx
from app.db import get_db
from app.core.events import log
from app.core.util import AppError, aware, new_id, now

TRIGGERS = {
    "lead_form.submitted": "Lead form submitted", "session.scheduled": "Session scheduled", "session.starts": "Session starts (with offset)",
    "session.ended": "Session ends", "questionnaire.submitted": "Questionnaire submitted", "file.completed": "Client file completed",
    "file.sent": "Client file sent", "contract.signed": "Contract signed (first signature)",
    "contract.fully_signed": "All signatures collected", "payment.first_paid": "First payment received",
    "invoice.paid_in_full": "Invoice paid in full", "payment.overdue": "Payment overdue", "project.start_date": "Project start date (with offset)",
    "project.end_date": "Project end date (with offset)", "project.stage_changed": "Project moved to a stage", "tag.added": "Tag added",
    "budget.threshold_reached": "Budget reaches X%", "retainer.usage_threshold": "Retainer usage reaches X%",
    "retainer.period_closed": "Retainer period closed", "retainer.renewal_due": "Retainer renewal due",
    "client_task.completed": "Client task completed", "quote.accepted": "Quote accepted",
    "manual": "Run by hand",
}
ACTIONS = ["send_email", "send_file", "send_whatsapp", "create_draft", "create_task", "add_tags", "remove_tags", "move_stage",
           "archive", "run_agent"]
CONDITIONS = ["tag_present", "file_viewed", "file_completed", "contract_signed", "questionnaire_submitted", "session_scheduled",
              "session_no_show", "task_completed", "first_payment", "paid_in_full", "budget_over", "client_task_overdue"]
SEND_ACTIONS = {"send_email", "send_file", "send_whatsapp"}
LEASE_SECONDS = 120


def validate_steps(steps, top=True):
    for i, s in enumerate(steps):
        s.setdefault("id", new_id()[:10])
        t = s.get("type")
        if t == "action":
            if s.get("action") not in ACTIONS:
                raise AppError("invalid", f"Unknown action: {s.get('action')}.", 400)
            if s["action"] == "archive" and not (top and i == len(steps) - 1):
                raise AppError("invalid", "\"Archive project\" ends the automation, so it must be the last step.", 400)
        elif t == "wait":
            w = s.get("wait") or {}
            if w.get("kind") == "time" and not 1 <= int(w.get("minutes", 0)) <= 60 * 24 * 365:
                raise AppError("invalid", "A wait must be between 1 minute and 12 months.", 400)
            if w.get("kind") == "event" and w.get("event") not in TRIGGERS:
                raise AppError("invalid", "Choose which event to wait for.", 400)
        elif t == "condition":
            if (s.get("cond") or {}).get("kind") not in CONDITIONS:
                raise AppError("invalid", "Choose a condition.", 400)
            validate_steps(s.setdefault("yes", []), False)
            validate_steps(s.setdefault("no", []), False)
        else:
            raise AppError("invalid", "Each step must be an action, a wait or a condition.", 400)


def step_at(steps, path):
    cur = steps
    node = None
    i = 0
    while i < len(path):
        node = cur[path[i]]
        if i + 1 < len(path):
            cur = node[path[i + 1]]
            i += 2
        else:
            i += 1
    return node


def advance(steps, path):
    """Next pointer after the step at `path`, or None when the automation ends."""
    path = list(path)
    while path:
        parent = steps
        for j in range(0, len(path) - 1, 2):
            parent = parent[path[j]][path[j + 1]]
        if path[-1] + 1 < len(parent):
            return path[:-1] + [path[-1] + 1]
        path = path[:-2]  # leave the branch, continue after its condition step
    return None


# ---------------- conditions ----------------

async def check(ctx, run, cond):
    pid = run["project_id"]
    d = ctx.data
    k = cond["kind"]
    fid = (run.get("trigger_payload") or {}).get("file_id")
    latest_file = (await d.client_files.get(fid)) if fid else await d.client_files.find_one({"project_id": pid, "status": {"$ne": "draft"}},
                                                                                             sort=[("sent_at", -1)])
    if k == "tag_present":
        pr = await d.projects.get(pid)
        return cond.get("tag") in (pr or {}).get("tags", [])
    if k == "file_viewed":
        return bool(latest_file and latest_file["status"] in ("viewed", "completed"))
    if k == "file_completed":
        return bool(latest_file and latest_file["status"] == "completed")
    if k == "contract_signed":
        return bool(await d.client_files.find_one({"project_id": pid, "signed_blocks": {"$exists": True, "$ne": {}}}))
    if k == "questionnaire_submitted":
        return bool(await d.events.find_one({"project_id": pid, "type": "questionnaire.submitted"}))
    if k == "session_scheduled":
        return bool(await d.sessions.find_one({"project_id": pid, "status": {"$in": ["booked", "completed"]}}))
    if k == "session_no_show":
        sid = (run.get("trigger_payload") or {}).get("session_id")
        s = await d.sessions.get(sid) if sid else await d.sessions.find_one({"project_id": pid}, sort=[("start", -1)])
        return bool(s and s["status"] == "no_show")
    if k == "task_completed":
        tid = (run.get("vars") or {}).get(f"task:{cond.get('step_ref')}") or next(iter((run.get("vars") or {}).values()), None)
        t = await d.tasks.get(tid) if tid else None
        return bool(t and t.get("done"))
    if k == "first_payment":
        return bool(await d.ledger.find_one({"project_id": pid, "type": "payment"}))
    if k == "paid_in_full":
        invs = await d.invoices.find({"project_id": pid, "status": {"$nin": ["draft", "void"]}})
        return bool(invs) and all(i["status"] == "paid" for i in invs)
    if k == "budget_over":
        pr = await d.projects.get(pid)
        return float(((pr or {}).get("budget") or {}).get("pct") or 0) >= float(cond.get("pct", 100))
    if k == "client_task_overdue":
        return bool(await d.tasks.find_one({"project_id": pid, "audience": "client", "done": False, "due_at": {"$lt": now()}}))
    return False


# ---------------- running a step ----------------

async def run_ctx(run):
    ctx = system_ctx(run["workspace_id"], actor=f"automation:{run['automation_id']}", via="automation")
    ctx.idem_key = None
    return ctx


async def make_approval(ctx, run, step, action_name, args, preview, why):
    from app.domain.workspace.approvals import create_approval
    return await create_approval(ctx, action_name, args, preview, why, project_id=run["project_id"], source="automation",
                                 automation_id=run["automation_id"], run_id=run["_id"], step_id=step["id"],
                                 idem=f"{run['_id']}:{step['id']}")


async def do_action(ctx, run, step, dry):
    """Returns (status, text). status: done | waiting_approval."""
    a = step["action"]
    pid = run["project_id"]
    key = f"{run['_id']}:{step['id']}"
    sctx = ctx.child(idem_key=key, dry_run=dry)
    if a == "send_email":
        t = await ctx.data.templates.get(step.get("template_id"))
        if not t:
            raise AppError("missing", "The email template for this step was deleted.", 400)
        args = {"project_id": pid, "channel": "email", "template_id": t["_id"]}
        if dry:
            return "done", f"Would send email \"{t['name']}\"" + (" (after your OK)" if step.get("approve") else "")
        if step.get("approve"):
            from app.domain.documents.merge import build, fill
            pr = await ctx.data.projects.get(pid)
            vals = await build(ctx, pr)
            await make_approval(ctx, run, step, "messages.send", dict(args, subject=fill(t["body"].get("subject", ""), vals, False),
                                                                       body=fill(t["body"].get("html", ""), vals)),
                                {"channel": "email", "subject": fill(t["body"].get("subject", ""), vals, False),
                                 "body": fill(t["body"].get("html", ""), vals)}, f"Automation \"{run['name']}\"")
            return "waiting_approval", f"Email \"{t['name']}\" waiting for your OK"
        await call(sctx, "messages.send", args)
        return "done", f"Sent email \"{t['name']}\""
    if a == "send_whatsapp":
        args = {"project_id": pid, "channel": "whatsapp", "wa_template": step.get("wa_template", "general_update"),
                "wa_params": step.get("wa_params", [])}
        if dry:
            return "done", "Would send a WhatsApp template"
        if step.get("approve"):
            await make_approval(ctx, run, step, "messages.send", args, {"channel": "whatsapp", "body": step.get("wa_template")},
                                f"Automation \"{run['name']}\"")
            return "waiting_approval", "WhatsApp waiting for your OK"
        await call(sctx, "messages.send", args)
        return "done", "Sent WhatsApp"
    if a == "send_file":
        t = await ctx.data.templates.get(step.get("file_template_id"))
        if not t:
            raise AppError("missing", "The file template for this step was deleted.", 400)
        if dry:
            return "done", f"Would send client file \"{t['name']}\""
        existing = (run.get("vars") or {}).get(f"file:{step['id']}")
        if not existing:
            f = await call(ctx.child(idem_key=key), "files.create_from_template", {"project_id": pid, "template_id": t["_id"]})
            existing = f["id"]
            await ctx.data.automation_runs.update({"_id": run["_id"]}, {f"vars.file:{step['id']}": existing})
        args = {"id": existing, "channel": "email"}
        if step.get("approve"):
            await make_approval(ctx, run, step, "files.send", args, {"channel": "email", "subject": t["name"], "file_id": existing},
                                f"Automation \"{run['name']}\"")
            return "waiting_approval", f"Client file \"{t['name']}\" waiting for your OK"
        await call(sctx, "files.send", args)
        return "done", f"Sent client file \"{t['name']}\""
    if a == "create_draft":
        t = await ctx.data.templates.get(step.get("template_id"))
        if dry:
            return "done", "Would create an email draft"
        from app.domain.documents.merge import build, fill
        pr = await ctx.data.projects.get(pid)
        vals = await build(ctx, pr)
        await call(ctx, "messages.save_draft", {"project_id": pid, "subject": fill((t or {}).get("body", {}).get("subject", ""), vals, False),
                                                "body": fill((t or {}).get("body", {}).get("html", ""), vals)})
        return "done", "Email draft created"
    if a == "create_task":
        if dry:
            return "done", f"Would create task \"{step.get('title')}\""
        due = (now() + timedelta(minutes=int(step.get("due_minutes", 1440)))).isoformat()
        t = await call(ctx, "tasks.create", {"title": step.get("title") or "Follow up", "project_id": pid, "due_at": due,
                                             "assignee_id": step.get("assignee_id")})
        await ctx.data.automation_runs.update({"_id": run["_id"]}, {f"vars.task:{step['id']}": t["id"]})
        return "done", f"Task created: {step.get('title')}"
    if a in ("add_tags", "remove_tags"):
        for tg in step.get("tags", []):
            if not dry:
                await call(ctx, "tags.add" if a == "add_tags" else "tags.remove", {"project_id": pid, "tag": tg})
        return "done", f"{'Would add' if dry else 'Added'} tags" if a == "add_tags" else "Tags removed"
    if a == "move_stage":
        st = await ctx.data.stages.get(step.get("stage_id")) if step.get("stage_id") else await ctx.data.stages.find_one({"key": step.get("stage_key")})
        if not st:
            raise AppError("missing", "The stage for this step no longer exists.", 400)
        if not dry:
            await call(ctx, "projects.move_stage", {"id": pid, "stage_id": st["_id"]})
        return "done", f"{'Would move' if dry else 'Moved'} to {st['name']}"
    if a == "archive":
        if not dry:
            from app.domain.sales.crm import archive
            await archive(ctx, await ctx.data.projects.get(pid), step.get("reason") or "Closed by automation")
        return "done", "Project archived"
    if a == "run_agent":
        if dry:
            return "done", f"Would ask the {step.get('agent')} agent: {step.get('instruction')}"
        from app.agents.runtime import AgentOff, run_agent
        try:
            r = await run_agent(run["workspace_id"], step["agent"], trigger={"kind": "automation", "automation": run["name"],
                                                                             "payload": run.get("trigger_payload")},
                                project_id=pid, instruction=step.get("instruction", ""), idem_prefix=key)
            return "done", f"{step['agent'].replace('_', ' ').title()} agent: {r.get('summary', 'done')}"
        except AgentOff as e:
            if step.get("fallback_template_id"):
                t = await ctx.data.templates.get(step["fallback_template_id"])
                if t:
                    fake_step = dict(step, action="send_email", template_id=t["_id"], approve=True)
                    st, txt = await do_action(ctx, run, fake_step, dry)
                    return st, f"{e} Used the fallback email instead. {txt}"
            return "done", str(e)
    raise AppError("invalid", f"Unknown action {a}", 400)


async def execute(run, dry=False, max_steps=50):
    """Run steps until a wait, an approval, the end, or a failure."""
    db = get_db()
    ctx = await run_ctx(run)
    steps = run["snapshot"]["steps"]
    path = run.get("path")
    out_log = []
    for _ in range(max_steps):
        if path is None:
            await _set(run, {"status": "done", "path": None, "ended_at": now()}, out_log, dry)
            return run
        step = step_at(steps, path)
        t = step["type"]
        try:
            if t == "wait":
                w = step["wait"]
                if dry:
                    out_log.append(_l(step, "done", f"Wait {'for ' + w.get('event', '') if w['kind'] == 'event' else str(w.get('minutes')) + ' min'} (skipped in test run)"))
                    path = advance(steps, path)
                    continue
                if run.get("waking_from") == step["id"]:
                    run["waking_from"] = None
                    out_log.append(_l(step, "done", "Wait finished"))
                    path = advance(steps, path)
                    continue
                if w["kind"] == "time":
                    wake = now() + timedelta(minutes=int(w["minutes"]))
                    await _set(run, {"status": "waiting", "path": path, "wake_at": wake, "waking_from": step["id"], "waiting_for": None},
                               out_log + [_l(step, "waiting", f"Waiting until {wake.isoformat()}")], dry)
                else:
                    until = now() + timedelta(minutes=int(w.get("limit_minutes", 4320)))
                    await _set(run, {"status": "waiting", "path": path, "wake_at": until, "waking_from": step["id"],
                                     "waiting_for": {"event": w["event"], "until": until}},
                               out_log + [_l(step, "waiting", f"Waiting for {TRIGGERS.get(w['event'], w['event'])}")], dry)
                return run
            if t == "condition":
                ok = await check(ctx, run, step["cond"])
                branch = "yes" if ok else "no"
                out_log.append(_l(step, "done", f"Condition {step['cond']['kind'].replace('_', ' ')}: {branch}"))
                path = path + [branch, 0] if step.get(branch) else advance(steps, path)
                continue
            status, text = await do_action(ctx, run, step, dry)
            out_log.append(_l(step, status, text))
            if status == "waiting_approval":
                await _set(run, {"status": "waiting_approval", "path": path, "wake_at": None}, out_log, dry)
                return run
            if step["action"] == "archive":
                path = None
                continue
            path = advance(steps, path)
        except AppError as e:
            retries = run.get("retries", 0) + 1
            if retries <= 3 and not dry:
                await _set(run, {"status": "waiting", "path": path, "retries": retries,
                                 "wake_at": now() + timedelta(minutes=2 ** retries)}, out_log + [_l(step, "retry", e.message)], dry)
                return run
            out_log.append(_l(step, "failed", e.message))
            if step.get("on_fail") == "continue" and not dry:
                path = advance(steps, path)
                continue
            await _set(run, {"status": "failed", "path": path, "ended_at": now()}, out_log, dry)
            if not dry:
                from app.core.events import notify
                await notify(ctx, f"Automation \"{run['name']}\" stopped: {e.message}", "automation", link=f"/projects/{run['project_id']}")
            return run
    await _set(run, {"status": "running", "path": path, "wake_at": now()}, out_log, dry)
    return run


def _l(step, status, text):
    return {"step_id": step["id"], "status": status, "text": text, "at": now()}


async def _set(run, ch, new_log, dry):
    run.update(ch)
    run.setdefault("log", [])
    run["log"] += new_log
    if dry:
        return
    ctx = system_ctx(run["workspace_id"])
    await ctx.data.automation_runs.update({"_id": run["_id"]}, dict(ch, lease_until=None), raw={"$push": {"log": {"$each": new_log}}} if new_log else None)
    for entry in new_log:
        if entry["status"] in ("done", "failed", "waiting_approval"):
            await log(ctx.child(actor=f"automation:{run['automation_id']}"), run["project_id"], "automation",
                      f"{run['name']}: {entry['text']}", ref=run["_id"])


# ---------------- starting runs ----------------

def trigger_matches(auto, ev, project, stage_key=None):
    tr = auto.get("trigger") or {}
    if tr.get("type") != ev["type"]:
        return False
    pl = ev.get("payload") or {}
    if tr.get("form_ids") and pl.get("form_id") not in tr["form_ids"]:
        return False
    if tr.get("session_type_key") and pl.get("type_key") != tr["session_type_key"]:
        return False
    if tr.get("session_type_ids") and pl.get("type_id") not in tr["session_type_ids"]:
        return False
    if tr.get("stage_key") and pl.get("stage_key") != tr["stage_key"]:
        return False
    if tr.get("stage_id") and pl.get("stage_id") != tr["stage_id"]:
        return False
    if tr.get("tag") and pl.get("tag") != tr["tag"]:
        return False
    if tr.get("pct") is not None and ev["type"] in ("budget.threshold_reached", "retainer.usage_threshold") \
            and int(pl.get("pct", -1)) != int(tr["pct"]):
        return False
    if tr.get("has_contract") and not pl.get("has_contract"):
        return False
    if ev["type"] == "file.sent" and pl.get("resend"):
        return False
    if auto.get("project_types") and (project or {}).get("type") not in auto["project_types"]:
        return False
    return True


async def start_run(ctx, auto, project_id, event=None, wake_at=None, key=None):
    run = {"_id": new_id(), "automation_id": auto["_id"], "name": auto["name"], "project_id": project_id,
           "snapshot": copy.deepcopy({"trigger": auto["trigger"], "steps": auto["steps"]}), "path": [0] if auto["steps"] else None,
           "status": "running", "wake_at": wake_at or now(), "log": [], "vars": {},
           "trigger_event_id": (event or {}).get("_id"), "trigger_payload": (event or {}).get("payload", {}),
           "run_key": key or f"{auto['_id']}:{project_id}:{(event or {}).get('_id') or new_id()}"}
    try:
        return await ctx.data.automation_runs.insert(run)
    except DuplicateKeyError:
        return None


async def apply_stage_rules(ctx, ev, project):
    ws = await ctx.ws()
    for r in ws.get("settings", {}).get("stage_rules", []):
        if not r.get("enabled") or r.get("event") != ev["type"]:
            continue
        target = await ctx.data.stages.get(r.get("stage_id")) or await ctx.data.stages.find_one({"key": r.get("stage_key")})
        cur = await ctx.data.stages.get(project["stage_id"])
        if target and cur and target["order"] > cur["order"] and not project.get("archived"):
            from app.domain.sales.crm import move_stage
            await move_stage(ctx.child(actor="system:stage_rule"), project, target, f"stage rule: {r.get('label', ev['type'])}")
            project = await ctx.data.projects.get(project["_id"])
    return project


async def dispatch(limit=300):
    """Process new events across all workspaces. Safe to call from several workers."""
    db = get_db()
    n = 0
    while n < limit:
        ev = await db.events.find_one_and_update({"processed": False, "$or": [{"lease_until": None}, {"lease_until": {"$lt": now()}}]},
                                                 {"$set": {"lease_until": now() + timedelta(seconds=LEASE_SECONDS)}},
                                                 sort=[("created_at", 1)])
        if not ev:
            break
        n += 1
        try:
            await handle_event(ev)
        finally:
            await db.events.update_one({"_id": ev["_id"]}, {"$set": {"processed": True, "processed_at": now()}})
    return n


async def handle_event(ev):
    ctx = system_ctx(ev["workspace_id"])
    pid = ev.get("project_id")
    project = await ctx.data.projects.get(pid) if pid else None
    if project and not project.get("archived"):
        project = await apply_stage_rules(ctx, ev, project)
    # Wake runs waiting for this event.
    if pid:
        for r in await ctx.data.automation_runs.find({"project_id": pid, "status": "waiting", "waiting_for.event": ev["type"]}):
            await ctx.data.automation_runs.update({"_id": r["_id"]}, {"wake_at": now(), "event_arrived": True})
    # Start matching automations.
    if project and not project.get("archived"):
        for auto in await ctx.data.automations.find({"active": True}):
            tr = auto.get("trigger", {})
            if tr.get("type") == "session.starts" and ev["type"] == "session.scheduled":
                s = await ctx.data.sessions.get((ev.get("payload") or {}).get("session_id"))
                if s and (not tr.get("session_type_key") or s.get("type_key") == tr["session_type_key"]):
                    await start_run(ctx, auto, pid, ev, aware(s["start"]) + timedelta(minutes=int(tr.get("offset_minutes", 0))))
                continue
            if trigger_matches(auto, ev, project):
                await start_run(ctx, auto, pid, ev)
    # Add-ons: checklists on stage entry, accepted estimates and retainer plans, agent drafts.
    await addon_hooks(ctx, ev, project)
    # Meeting agent: prep before, notes after.
    if ev["type"] in ("session.starting", "session.ended") and pid:
        from app.agents.runtime import AgentOff, run_agent
        try:
            await run_agent(ev["workspace_id"], "meeting", trigger={"kind": "event", "event": ev["type"], "payload": ev.get("payload")},
                            project_id=pid, idem_prefix=f"ev:{ev['_id']}")
        except AgentOff:
            pass


async def addon_hooks(ctx, ev, project):
    from app.agents.runtime import AgentOff, run_agent
    pid = ev.get("project_id")
    pl = ev.get("payload") or {}
    et = ev["type"]
    try:
        if et == "project.stage_changed" and pid and pl.get("stage_id"):
            from app.domain.billing.retainers import on_stage_entered
            await on_stage_entered(ctx, pid, pl["stage_id"])
            st = await ctx.data.stages.get(pl["stage_id"])
            if st and st.get("key") == "completed" and project and not await ctx.data.retainers.find_one(
                    {"contact_id": {"$in": project.get("contact_ids") or []}, "status": {"$in": ["active", "paused"]}}):
                await run_agent(ev["workspace_id"], "proposal", trigger={"kind": "event", "event": et, "payload": pl}, project_id=pid,
                                instruction="The project is complete. Propose a monthly retainer to continue the work.", idem_prefix=f"ev:{ev['_id']}")
        if et in ("file.completed", "contract.fully_signed") and pl.get("file_id"):
            f = await ctx.data.client_files.get(pl["file_id"])
            if f and f.get("estimate_id") and f.get("kind") != "quote":
                from app.domain.billing.estimates import convert
                e = await ctx.data.estimates.get(f["estimate_id"])
                if e and e["status"] == "final":
                    await convert(ctx, e)
            if f:
                from app.domain.billing.retainers import from_file
                await from_file(ctx, f)
        draft = (et == "budget.threshold_reached" and int(pl.get("pct", 0)) < 100) or (et == "retainer.usage_threshold" and pl.get("client_note")) \
            or et in ("retainer.renewal_due", "client_task.overdue")
        if draft and pid:
            await run_agent(ev["workspace_id"], "followup", trigger={"kind": "event", "event": et, "payload": pl}, project_id=pid,
                            idem_prefix=f"ev:{ev['_id']}")
    except AgentOff:
        pass


TICK_BATCH = 500
TICK_CONCURRENCY = 25


async def tick(limit=5000):
    """Run every due step.

    Claims due runs in batches (one indexed query per batch, then a conditional
    update per run, so two workers never take the same run) and works through
    them concurrently.
    """
    db = get_db()
    done = 0
    sem = asyncio.Semaphore(TICK_CONCURRENCY)

    async def one(r):
        async with sem:
            if r["status"] == "waiting" and r.get("waiting_for") and not r.get("event_arrived") \
                    and aware(r["wake_at"]) < aware(r["waiting_for"]["until"]):
                await db.automation_runs.update_one({"_id": r["_id"]}, {"$set": {"lease_until": None}})
                return
            r["status"] = "running"
            await execute(r)

    while done < limit:
        t = now()
        due = await db.automation_runs.find(
            {"status": {"$in": ["running", "waiting"]}, "wake_at": {"$lte": t},
             "$or": [{"lease_until": None}, {"lease_until": {"$lt": t}}]},
            {"_id": 1}).sort("wake_at", 1).limit(min(TICK_BATCH, limit - done)).to_list(None)
        if not due:
            break
        claimed = []
        for d in due:
            r = await db.automation_runs.find_one_and_update(
                {"_id": d["_id"], "$or": [{"lease_until": None}, {"lease_until": {"$lt": t}}]},
                {"$set": {"lease_until": t + timedelta(seconds=LEASE_SECONDS)}})
            if r:
                claimed.append(r)
        if not claimed:
            break
        await asyncio.gather(*[one(r) for r in claimed])
        done += len(claimed)
    return done


async def resume_after_approval(run_id, approved: bool, note=""):
    db = get_db()
    r = await db.automation_runs.find_one({"_id": run_id})
    if not r or r["status"] != "waiting_approval":
        return
    steps = r["snapshot"]["steps"]
    step = step_at(steps, r["path"])
    nxt = advance(steps, r["path"])
    entry = _l(step, "done", ("Approved and sent" if approved else "Skipped by you") + (f": {note}" if note else ""))
    await db.automation_runs.update_one({"_id": run_id}, {"$set": {"status": "running" if nxt is not None else "done", "path": nxt,
                                                                   "wake_at": now(), "lease_until": None},
                                                          "$push": {"log": entry}})
