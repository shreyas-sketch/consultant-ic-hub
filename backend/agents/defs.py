"""The agents: job, prompt, allowed tools, default autonomy, and a fake-mode plan.

In live mode the model decides which tools to call. In fake mode (QA, tests)
each agent's `plan` produces realistic tool calls from the real account data, so
every screen and approval can be tested with no keys.
"""
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Optional

from core.events import notify
from core.util import IST, aware, fmt_dt, inr, now


@dataclass
class AgentDef:
    name: str
    label: str
    prompt: str
    tools: object
    default_mode: str = "draft"
    model_size: str = "small"
    kind: str = "worker"
    default_instruction: str = ""
    plan: Optional[Callable] = None
    after: Optional[Callable] = None
    why_text: str = ""
    wakes_on: str = ""

    def why(self, trigger):
        t = (trigger or {})
        return self.why_text or t.get("event") or t.get("kind") or self.label


async def _contact(ctx, pr):
    return await ctx.data.contacts.get(pr["contact_ids"][0]) if pr and pr.get("contact_ids") else None


async def _next_slots(ctx, n=3):
    from actions.scheduling import find_slots
    st = await ctx.data.session_types.find_one({"key": "discovery", "active": True}) or await ctx.data.session_types.find_one({"active": True})
    if not st:
        return st, []
    slots = await find_slots(ctx, st, now(), now() + timedelta(days=7))
    return st, slots[:n]


# ---------------- Lead agent ----------------

def score_lead(contact, answers_text, source):
    s, why = 20, []
    if contact and contact.get("company"):
        s += 20
        why.append("has a company")
    if re.search(r"(lakh|lac|crore|cr\b|₹|budget|\d{2,}\s?l\b)", answers_text, re.I):
        s += 25
        why.append("mentions budget or revenue")
    if len(answers_text) > 80:
        s += 15
        why.append("wrote a detailed enquiry")
    if (source or "").lower() in ("client referral", "referral", "webinar"):
        s += 20
        why.append(f"came from {source}")
    return min(100, s), why


async def lead_plan(ctx, pack, trigger, instruction, project_id, chat):
    from actions.merge import build
    pr = await ctx.data.projects.get(project_id) if project_id else None
    if not pr:
        return [], "No project to work on."
    c = await _contact(ctx, pr)
    notes = await ctx.data.notes.find({"project_id": pr["_id"], "kind": "enquiry"})
    text = " ".join(n["text"] for n in notes) + " " + str((trigger.get("payload") or {}).get("message") or "")
    score, why = score_lead(c, text, pr.get("source"))
    st, slots = await _next_slots(ctx)
    vals = await build(ctx, pr, c)
    times = "".join(f"<li>{fmt_dt(s)}</li>" for s in slots)
    body = (f"<p>Hi {vals['client.first_name']},</p><p>Thank you for reaching out"
            f"{' from ' + c['company'] if c and c.get('company') else ''}. I've read your note and I'd be glad to help.</p>"
            + (f"<p>Could we do a short call? Here are a few times that work for me:</p><ul>{times}</ul>"
               f"<p>Or pick any time here: {vals.get('booking.link', '')}</p>" if slots else
               f"<p>You can pick a time for a short call here: {vals.get('booking.link', '')}</p>")
            + f"<p>Speak soon,<br>{vals['consultant.name']}</p>")
    calls = [("notes.add", {"project_id": pr["_id"], "text": f"Lead score {score}/100" + (f" — {', '.join(why)}." if why else ".")})]
    if c and c.get("email"):
        calls.append(("messages.send", {"project_id": pr["_id"], "channel": "email", "subject": f"Re: your enquiry, {vals['client.first_name']}",
                                        "body": body}))
    elif c and c.get("phone"):
        calls.append(("messages.send", {"project_id": pr["_id"], "channel": "whatsapp", "wa_template": "general_update",
                                        "wa_params": [vals["client.first_name"], f"thanks for reaching out! Pick a time for a short call: {vals.get('booking.link', '')}"]}))
    return calls, f"Scored this lead {score}/100 and drafted a reply" + (f" offering {len(slots)} call times." if slots else ".")


async def lead_after(ctx, run, plan):
    note = next((c for c in run["tool_calls"] if c["tool"] == "notes.add"), None)
    m = re.search(r"Lead score (\d+)", (note or {}).get("input", {}).get("text", ""))
    if m and int(m.group(1)) >= 70:
        pr = await ctx.data.projects.get(run["project_id"])
        await notify(ctx, f"Priority lead: {pr['name']} scored {m.group(1)}/100. A reply is ready for your OK.", "priority_lead",
                     link=f"/projects/{pr['_id']}")


# ---------------- Follow-up agent ----------------

async def followup_event(ctx, trigger, project_id):
    """Drafts for add-on events: budget scope check, retainer usage note, renewal, overdue client task."""
    from actions.merge import build
    from actions.retainers import h, period_numbers
    pl = trigger.get("payload") or {}
    ev = trigger["event"]
    pr = await ctx.data.projects.get(project_id) if project_id else None
    if not pr or pr.get("archived"):
        return [], "Nothing to do."
    if ev == "client_task.overdue":
        t = await ctx.data.tasks.get(pl.get("task_id") or "")
        if not t or t["done"]:
            return [], "Nothing to chase."
        return [("client_tasks.remind", {"id": t["_id"]})], f"Drafted a reminder for \"{t['title']}\" — it's overdue."
    c = await _contact(ctx, pr)
    if not c:
        return [], "No contact on this project."
    v = await build(ctx, pr, c)
    first = v["client.first_name"]
    if ev == "budget.threshold_reached":
        b = pr.get("budget") or {}
        left = [t["title"] for t in await ctx.data.tasks.find({"project_id": pr["_id"], "done": False, "audience": {"$ne": "client"}}, limit=5)]
        what = "hours we agreed" if b.get("type") == "time" else "agreed budget"
        text = (f"A quick scope check on {pr['name']}: we've now used about {pl.get('pct')}% of the {what}."
                + (" Still to do: " + "; ".join(left) + "." if left else "")
                + " Shall we keep to the current scope, or add time? Happy to talk it through.")
        subj, why = f"Scope check: {pr['name']}", f"Drafted a scope-check note ({pl.get('pct')}% of the budget used)."
    elif ev == "retainer.usage_threshold":
        r = await ctx.data.retainers.get(pl.get("retainer_id") or "")
        per = await ctx.data.retainer_periods.get(pl.get("period_id") or "")
        if not r or not per:
            return [], "Nothing to do."
        n = await period_numbers(ctx, r, per)
        text = (f"An update on your {r['name']}: {h(n['used'])} of {h(n['available'])} used this period, {h(n['left'])} left. "
                "Anything you'd like me to prioritise with the time left?")
        subj, why = f"{r['name']}: {pl.get('pct')}% used", "Drafted a usage note for the client."
    elif ev == "retainer.renewal_due":
        r = await ctx.data.retainers.get(pl.get("retainer_id") or "")
        if not r:
            return [], "Nothing to do."
        pers = await ctx.data.retainer_periods.find({"retainer_id": r["_id"]})
        total = 0
        for x in pers:
            total += (await period_numbers(ctx, r, x))["used"]
        done = [t["title"] for t in await ctx.data.tasks.find({"project_id": {"$in": r["project_ids"]}, "done": True}, sort=[("done_at", -1)], limit=4)]
        text = (f"Our {r['name']} runs until {pl.get('end_date')}. Over {len(pers)} period{'s' if len(pers) != 1 else ''} we've put in "
                f"{h(total)}" + (", including: " + "; ".join(done) if done else "") + ". Would you like to continue? I can send the renewal.")
        subj, why = f"Renewing your {r['name']}", "Drafted a renewal note with what was delivered."
    else:
        return [], "Nothing to do."
    if c.get("email"):
        args = {"project_id": pr["_id"], "channel": "email", "subject": subj, "body": f"<p>Hi {first},</p><p>{text}</p>"}
    else:
        args = {"project_id": pr["_id"], "channel": "whatsapp", "wa_template": "general_update", "wa_params": [first, text]}
    return [("messages.send", args)], why


async def followup_plan(ctx, pack, trigger, instruction, project_id, chat):
    from actions.merge import build, client_base
    if (trigger or {}).get("event"):
        return await followup_event(ctx, trigger, project_id)
    ws = await ctx.ws()
    opp = [s["_id"] for s in await ctx.data.stages.find({"group": "opportunity"})]
    quiet = await ctx.data.projects.find({"stage_id": {"$in": opp}, "archived": False, "last_activity_at": {"$lt": now() - timedelta(days=3)}},
                                         limit=20)
    targets = {p["_id"]: ("quiet", p) for p in quiet}
    for f in await ctx.data.client_files.find({"status": "sent", "sent_at": {"$lt": now() - timedelta(days=2)}}, limit=20):
        p = await ctx.data.projects.get(f["project_id"])
        if p and not p.get("archived"):
            targets[p["_id"]] = ("unopened", p, f)
    for f in await ctx.data.client_files.find({"status": {"$in": ["viewed"]}, "sent_at": {"$lt": now() - timedelta(days=3)}}, limit=20):
        p = await ctx.data.projects.get(f["project_id"])
        if p and not p.get("archived") and not f.get("signed_blocks"):
            targets[p["_id"]] = ("unsigned", p, f)
    calls = []
    for pid, t in list(targets.items())[:8]:
        if await ctx.data.approvals.find_one({"project_id": pid, "status": "pending", "agent": "followup"}):
            continue
        p = t[1]
        c = await _contact(ctx, p)
        if not c or not c.get("email"):
            continue
        v = await build(ctx, p, c)
        if t[0] == "quiet":
            body = f"<p>Hi {v['client.first_name']},</p><p>Just checking in — is this still something you'd like help with? Happy to find a time: {v.get('booking.link', '')}</p>"
            subj = "Still keen to chat?"
        elif t[0] == "unopened":
            body = f"<p>Hi {v['client.first_name']},</p><p>I sent over \"{t[2]['title']}\" a couple of days ago — here's the link again: {client_base(ws)}/f/{t[2]['token']}</p>"
            subj = f"Re: {t[2]['title']}"
        else:
            body = f"<p>Hi {v['client.first_name']},</p><p>Any questions on \"{t[2]['title']}\"? If it looks good, you can sign and get started here: {client_base(ws)}/f/{t[2]['token']}</p>"
            subj = "Ready to get started?"
        calls.append(("messages.send", {"project_id": pid, "channel": "email", "subject": subj, "body": body}))
    return calls, f"Found {len(calls)} conversation{'s' if len(calls) != 1 else ''} that need a nudge and drafted each one." if calls else "No one needs a nudge today."


# ---------------- Meeting agent ----------------

def summarise_transcript(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    said = " ".join(l.split(":", 1)[-1] for l in lines)
    nums = re.findall(r"(\d+(?:\.\d+)?\s?(?:lakh|crore|cr|l)\b)", said, re.I)
    todos = []
    for l in lines:
        if re.search(r"\b(send|I'll|we'll|next step|follow up|share)\b", l, re.I):
            todos.append(l.split(":", 1)[-1].strip().rstrip("."))
    decisions = [l.split(":", 1)[-1].strip() for l in lines if re.search(r"\b(makes sense|agreed|let's|budget)\b", l, re.I)]
    summary = "Call summary: " + (lines[1].split(":", 1)[-1].strip() if len(lines) > 1 else said[:200])
    if nums:
        summary += f" Figures mentioned: {', '.join(dict.fromkeys(nums))}."
    return summary, decisions[:5], todos[:5]


async def meeting_plan(ctx, pack, trigger, instruction, project_id, chat):
    import vendors
    pr = await ctx.data.projects.get(project_id) if project_id else None
    if not pr:
        return [], "No project."
    ev = trigger.get("event")
    sid = (trigger.get("payload") or {}).get("session_id")
    s = await ctx.data.sessions.get(sid) if sid else await ctx.data.sessions.find_one({"project_id": pr["_id"]}, sort=[("start", -1)])
    c = await _contact(ctx, pr)
    if ev == "session.starting":
        notes = await ctx.data.notes.find({"project_id": pr["_id"]}, sort=[("created_at", -1)], limit=3)
        due = sum(x["totals"]["due"] for x in await ctx.data.invoices.find({"project_id": pr["_id"], "status": {"$in": ["sent", "partially_paid"]}}))
        brief = (f"Prep brief for {s['title'] if s else 'your call'} at {fmt_dt(s['start']) if s else ''}\n"
                 f"Who: {c['name'] if c else ''}{(' · ' + c['company']) if c and c.get('company') else ''}\n"
                 f"Where the project is: {pack.get('project', {}).get('stage', '')}\n"
                 + (f"What they told us: {notes[-1]['text'][:400]}\n" if notes else "")
                 + (f"Money due on this project: {inr(due)}\n" if due else "")
                 + "Goal for the call: understand their numbers, agree the next step, and book the proposal walkthrough.")
        return [("notes.add", {"project_id": pr["_id"], "text": brief})], "Prepared a one-page brief for the call."
    transcript = (trigger.get("payload") or {}).get("transcript")
    if not transcript and s and (s.get("notetaker") or {}).get("bot_id"):
        transcript = await vendors.meetbot_transcript(s["notetaker"]["bot_id"])
    if not transcript:
        return [("tasks.create", {"title": f"Add your notes from the call with {c['name'] if c else 'the client'}", "project_id": pr["_id"],
                                  "due_at": (now() + timedelta(hours=4)).isoformat()})], "No recording yet, so I added a task to capture notes."
    summary, decisions, todos = summarise_transcript(transcript)
    text = summary + ("\n\nDecisions:\n- " + "\n- ".join(decisions) if decisions else "") + ("\n\nTo-dos:\n- " + "\n- ".join(todos) if todos else "")
    calls = [("notes.add", {"project_id": pr["_id"], "text": text})]
    ask = re.compile(r"^(?:could|can|would) you (?:please )?(share|send|give|provide)\s+(?:me\s+|us\s+)?(.+?)(?:\?|$)|^(?:the )?client (?:to|will) (.+)$", re.I)
    for t in todos:
        m = ask.match(t.strip())
        if m:
            title = (f"{m.group(1).capitalize()} {m.group(2)}" if m.group(1) else m.group(3).capitalize()).rstrip("?. ")
            calls.append(("client_tasks.assign", {"project_id": pr["_id"], "title": title[:120], "channel": "both",
                                                  "due_at": (now() + timedelta(days=3)).isoformat()}))
        else:
            calls.append(("tasks.create", {"title": t[:120], "project_id": pr["_id"], "due_at": (now() + timedelta(days=1)).isoformat()}))
    return calls, f"Wrote up the call: {len(decisions)} decision{'s' if len(decisions) != 1 else ''} and {len(todos)} to-do{'s' if len(todos) != 1 else ''}."


async def meeting_after(ctx, run, plan):
    if run["trigger"] and run["trigger"].get("event") == "session.ended" or (run.get("trigger") or {}).get("kind") == "upload":
        note = next((c for c in run["tool_calls"] if c["tool"] == "notes.add"), None)
        if note:
            await ctx.data.meeting_notes.insert({"project_id": run["project_id"], "session_id": ((run["trigger"] or {}).get("payload") or {}).get("session_id"),
                                                 "summary": note["input"]["text"], "agent_run_id": run["_id"]})


# ---------------- Proposal agent ----------------

async def proposal_plan(ctx, pack, trigger, instruction, project_id, chat):
    pr = await ctx.data.projects.get(project_id) if project_id else None
    if not pr:
        return [], "No project."
    if re.search(r"\b(estimate|quote|price it|cost it)\b", instruction or "", re.I):
        notes = " ".join(n["text"] for n in await ctx.data.notes.find({"project_id": pr["_id"]}, sort=[("created_at", -1)], limit=5))
        rounds = [[("estimates.draft_from_text", {"project_id": pr["_id"], "text": (instruction or "") + " " + notes})],
                  [lambda res: ("estimates.finalise", {"id": res["estimates.draft_from_text"]["id"]}) if (res.get("estimates.draft_from_text") or {}).get("id") else None],
                  [lambda res: ("estimates.to_quote", {"id": res["estimates.finalise"]["id"], "detail": "phase"}) if (res.get("estimates.finalise") or {}).get("id") else None],
                  [lambda res: ("files.send", {"id": res["estimates.to_quote"]["id"], "channel": "email",
                                               "message": "Thank you for the call. Here is my quote, based on what we discussed."})
                   if (res.get("estimates.to_quote") or {}).get("id") else None]]

        def s(res):
            e = res.get("estimates.draft_from_text") or {}
            return ((e.get("summary") or "Drafted an estimate.") + " The quick quote is waiting for your OK before it goes out.") if e.get("id") else \
                (e.get("error") or "I couldn't draft the estimate.")
        return rounds, s
    notes = " ".join(n["text"] for n in await ctx.data.notes.find({"project_id": pr["_id"]}, limit=10)) + " " + (instruction or "")
    kind = "retainer" if re.search(r"retainer|month|ongoing|weekly", notes, re.I) else "workshop" if re.search(r"workshop|team|training", notes, re.I) else \
        "audit" if re.search(r"audit|review|diagnos", notes, re.I) else "retainer"
    tpl = await ctx.data.templates.find_one({"gallery_key": f"proposal_{kind}"}) or await ctx.data.templates.find_one({"kind": "file", "name": {"$regex": "Proposal"}})
    mn = await ctx.data.meeting_notes.find_one({"project_id": pr["_id"]}, sort=[("created_at", -1)])
    intro = (mn or {}).get("summary", "").split("\n")[0].replace("Call summary: ", "")
    start = (now() + timedelta(days=7)).astimezone(IST)
    end = start + timedelta(days=90 if kind == "retainer" else 21)

    def r2(res):
        f = res.get("files.create_from_template") or {}
        if not f.get("id"):
            return None
        page0 = f["pages"][0]
        txt = next((b for b in page0["blocks"] if b["type"] == "text"), None)
        if not txt:
            return None
        html = txt["html"] + (f"<p><b>What I heard:</b> {intro}</p>" if intro else "")
        return ("files.update_block", {"id": f["id"], "block_id": txt["id"], "props": {"html": html}})

    def r3(res):
        f = res.get("files.create_from_template") or {}
        if not f.get("id"):
            return None
        for pg in f["pages"]:
            for b in pg["blocks"]:
                if b["type"] == "contract":
                    flds = [dict(x, value=x.get("value") or {"start_date": f"{start.day} {start:%b %Y}", "end_date": f"{end.day} {end:%b %Y}"}.get(x["key"], ""))
                            for x in b.get("fields", [])]
                    return ("files.update_block", {"id": f["id"], "block_id": b["id"], "props": {"fields": flds}})
        return None

    def r4(res):
        f = res.get("files.create_from_template") or {}
        return ("files.send", {"id": f["id"], "channel": "email",
                               "message": "Thank you for the call. Here is my proposal, based on what we discussed."}) if f.get("id") else None

    rounds = [[("files.create_from_template", {"project_id": pr["_id"], "template_id": tpl["_id"]})], [r2, r3], [r4]] if tpl else []
    return rounds, f"Drafted a {kind} proposal from the call notes. It's waiting for your OK before it goes out." if tpl else "No proposal template found."


# ---------------- Collections agent ----------------

DISPUTE = re.compile(r"\b(dispute|not happy|unhappy|refund|cancel|wrong amount|didn't agree|did not agree)\b", re.I)


async def collections_plan(ctx, pack, trigger, instruction, project_id, chat):
    from actions.merge import build, client_base
    from actions.money import item_state
    ws = await ctx.ws()
    f = {"status": {"$in": ["sent", "partially_paid"]}}
    if project_id:
        f["project_id"] = project_id
    calls, flagged = [], 0
    for inv in await ctx.data.invoices.find(f, limit=50):
        over = [s for s in inv["schedule"] if item_state(s, inv) == "overdue"]
        if not over:
            continue
        if await ctx.data.approvals.find_one({"project_id": inv["project_id"], "status": "pending", "agent": "collections"}):
            continue
        pr = await ctx.data.projects.get(inv["project_id"])
        last_in = await ctx.data.messages.find({"project_id": pr["_id"], "direction": "in"}, sort=[("created_at", -1)], limit=3)
        if any(DISPUTE.search((m.get("body_text") or "") + (m.get("subject") or "")) for m in last_in):
            flagged += 1
            await notify(ctx, f"{pr['name']}: the client may be disputing the invoice. I didn't send a reminder — please look.", "dispute",
                         link=f"/projects/{pr['_id']}")
            continue
        s = over[0]
        days = (now() - aware(s["due_date"])).days
        amount = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0)
        c = await _contact(ctx, pr)
        if not c:
            continue
        v = await build(ctx, pr, c)
        link = f"{client_base(ws)}/i/{inv['token']}"
        if days <= 7:
            tone, body = "gentle", f"<p>Hi {v['client.first_name']},</p><p>A gentle reminder that {inr(amount)} ({s['label']}) was due on {fmt_dt(s['due_date']).split(',')[0]}. You can pay by UPI here: {link}</p><p>Thank you!</p>"
        elif days <= 21:
            tone, body = "firm", f"<p>Hi {v['client.first_name']},</p><p>{inr(amount)} for {s['label']} is now {days} days overdue. Could you clear it this week? Pay here: {link}</p><p>If there's an issue, just reply and we'll sort it out.</p>"
        else:
            tone, body = "final", f"<p>Hi {v['client.first_name']},</p><p>{inr(amount)} has been outstanding for {days} days. Please pay by this Friday ({link}) or let me know a date that works, so we can keep the work moving.</p>"
        args = {"project_id": pr["_id"], "channel": "email" if c.get("email") else "whatsapp"}
        if c.get("email"):
            args.update(subject=f"Payment reminder: {inr(amount)}", body=body)
        else:
            args.update(wa_template="payment_reminder", wa_params=[v["client.first_name"], inr(amount), link])
        calls.append(("messages.send", args))
    s = f"Drafted {len(calls)} payment reminder{'s' if len(calls) != 1 else ''}" + (f" and flagged {flagged} possible dispute{'s' if flagged != 1 else ''}" if flagged else "") + "."
    # Month end: draft invoices for unbilled time (largest first; retainer time is invoiced by the retainer).
    import calendar
    t = now().astimezone(IST)
    month_end = (trigger or {}).get("kind") == "schedule" and t.day >= calendar.monthrange(t.year, t.month)[1] - 2
    rounds = [calls] if calls else []
    n_inv = 0
    if (month_end or re.search(r"unbilled|month.?end", instruction or "", re.I)) and not project_id:
        from actions.timebill import unbilled_summary
        on_retainer = {x for r in await ctx.data.retainers.find({"status": {"$in": ["active", "paused"]}}) for x in r["project_ids"]}
        by = await unbilled_summary(ctx)
        for pid, v in sorted(((k, v) for k, v in by.items() if k not in on_retainer and v["amount_paise"] > 0), key=lambda kv: -kv[1]["amount_paise"])[:3]:
            if await ctx.data.approvals.find_one({"project_id": pid, "status": "pending", "action": "invoices.send"}):
                continue
            rounds.append([("invoices.add_unbilled_time", {"project_id": pid, "group_by": "task", "timesheet": "link"})])
            rounds.append([lambda res: ("invoices.send", {"id": res["invoices.add_unbilled_time"]["id"], "channel": "both"})
                           if (res.get("invoices.add_unbilled_time") or {}).get("id") else None])
            n_inv += 1
    if n_inv:
        s = s[:-1] + f", and drafted {n_inv} invoice{'s' if n_inv != 1 else ''} for unbilled time."
    return rounds, s


# ---------------- Daily brief ----------------

async def brief_plan(ctx, pack, trigger, instruction, project_id, chat):
    return [], "Daily brief ready."


async def brief_after(ctx, run, plan):
    from actions.money import item_state
    today = now().astimezone(IST)
    t0 = today.replace(hour=0, minute=0, second=0, microsecond=0)
    y0 = t0 - timedelta(days=1)
    items = []
    n_appr = await ctx.data.approvals.count({"status": "pending"})
    if n_appr:
        items.append({"text": f"{n_appr} thing{'s' if n_appr != 1 else ''} waiting for your OK", "link": "/approvals", "kind": "approval"})
    claims = await ctx.data.payment_claims.count({"status": "pending"})
    if claims:
        items.append({"text": f"Confirm {claims} payment{'s' if claims != 1 else ''} clients say they've made", "link": "/payments", "kind": "money"})
    sess = await ctx.data.sessions.find({"status": "booked", "start": {"$gte": t0, "$lt": t0 + timedelta(days=1)}}, sort=[("start", 1)])
    if sess:
        items.append({"text": f"{len(sess)} session{'s' if len(sess) != 1 else ''} today — first at {fmt_dt(sess[0]['start']).split(', ')[-1]}", "link": "/calendar",
                      "kind": "session"})
    first = await ctx.data.stages.find_one({}, sort=[("order", 1)])
    new_leads = await ctx.data.projects.count({"stage_id": first["_id"] if first else None, "archived": False, "created_at": {"$gte": y0}})
    if new_leads:
        items.append({"text": f"{new_leads} new lead{'s' if new_leads != 1 else ''} since yesterday", "link": "/projects", "kind": "lead"})
    overdue = []
    due_week = 0
    for inv in await ctx.data.invoices.find({"status": {"$in": ["sent", "partially_paid"]}}):
        for s in inv["schedule"]:
            st = item_state(s, inv)
            if st == "overdue":
                overdue.append(s)
            if s.get("due_date") and st != "paid" and aware(s["due_date"]) < now() + timedelta(days=7):
                due_week += s["amount_paise"] - s.get("paid_paise", 0)
    if overdue:
        items.append({"text": f"{len(overdue)} overdue payment{'s' if len(overdue) != 1 else ''}", "link": "/payments", "kind": "overdue"})
    from actions.timebill import unbilled_summary
    by = await unbilled_summary(ctx)
    ub = sum(v["amount_paise"] for v in by.values())
    if ub:
        oldest = min(v["oldest"] for v in by.values())
        days = (today.date() - __import__("datetime").date.fromisoformat(oldest)).days
        items.append({"text": f"{inr(ub)} of unbilled time, oldest from {days // 7} week{'s' if days // 7 != 1 else ''} ago" if days >= 7
                      else f"{inr(ub)} of unbilled time", "link": "/time?tab=unbilled", "kind": "money"})
    risk = await ctx.data.projects.find({"budget.pct": {"$gte": 80}, "archived": False}, sort=[("budget.pct", -1)], limit=5)
    if risk:
        items.append({"text": f"{len(risk)} budget{'s' if len(risk) != 1 else ''} at risk: " + ", ".join(f"{r['name']} {r['budget']['pct']:.0f}%" for r in risk[:3]),
                      "link": f"/projects/{risk[0]['_id']}?tab=budget", "kind": "overdue" if risk[0]["budget"]["pct"] >= 100 else "money"})
    waiting = await ctx.data.tasks.count({"audience": "client", "done": False, "due_at": {"$lt": now()}})
    if waiting:
        items.append({"text": f"Waiting on clients for {waiting} overdue item{'s' if waiting != 1 else ''}", "link": "/tasks?view=client", "kind": "task"})
    insight = []
    try:
        if today.weekday() == 0:
            from actions.insight import FcIn, forecast_get
            insight.append((await forecast_get(ctx, FcIn(months=6)))["summary"])
        if today.day == 1:
            from actions.insight import ProfitIn, reports_profitability
            pr_ = await reports_profitability(ctx, ProfitIn(group="project", date_from=(today - timedelta(days=90)).date().isoformat()))
            if pr_.get("best") and pr_["best"] is not pr_.get("worst"):
                insight.append(pr_["summary"])
    except Exception:
        pass
    changes = []
    for kind, label in (("payment", "payments confirmed"), ("signature", "contracts signed"), ("lead", "new leads")):
        n = await ctx.data.activity.count({"kind": kind, "at": {"$gte": y0}})
        if n:
            changes.append(f"{n} {label}")
    trends = None
    if today.weekday() == 0:
        this_w = await ctx.data.projects.count({"created_at": {"$gte": t0 - timedelta(days=7)}})
        last_w = await ctx.data.projects.count({"created_at": {"$gte": t0 - timedelta(days=14), "$lt": t0 - timedelta(days=7)}})
        trends = f"Leads this week: {this_w} (last week {last_w})."
    await ctx.data.daily_briefs.insert({"date": today.date().isoformat(), "items": items[:3], "all_items": items, "money_due_week_paise": due_week,
                                        "changes": changes, "trends": trends, "insight": insight, "unbilled_paise": ub, "agent_run_id": run["_id"]})


# ---------------- Automation builder ----------------

def spec_from_text(text):
    t = text.lower()
    days = int((re.search(r"(\d+)\s*day", t) or [None, 2])[1])
    if "proposal" in t or "file" in t:
        return {"name": f"Nudge if the proposal isn't opened in {days} days", "trigger": {"type": "file.sent"},
                "steps": [{"type": "wait", "wait": {"kind": "time", "minutes": days * 1440}},
                          {"type": "condition", "cond": {"kind": "file_viewed"}, "yes": [],
                           "no": [{"type": "action", "action": "create_task", "title": "Follow up on the proposal", "due_minutes": 60}]}]}
    if "pay" in t or "advance" in t:
        return {"name": "After the first payment", "trigger": {"type": "payment.first_paid"},
                "steps": [{"type": "action", "action": "create_task", "title": "Send the kickoff invite", "due_minutes": 1440},
                          {"type": "action", "action": "move_stage", "stage_key": "in_delivery"}]}
    if "call" in t or "session" in t or "meeting" in t:
        return {"name": "After a call", "trigger": {"type": "session.ended"},
                "steps": [{"type": "wait", "wait": {"kind": "time", "minutes": 60}},
                          {"type": "action", "action": "run_agent", "agent": "proposal", "instruction": "Draft the proposal from the call."}]}
    return {"name": "New enquiry follow-up", "trigger": {"type": "lead_form.submitted"},
            "steps": [{"type": "wait", "wait": {"kind": "time", "minutes": days * 1440}},
                      {"type": "condition", "cond": {"kind": "session_scheduled"}, "yes": [],
                       "no": [{"type": "action", "action": "create_task", "title": "Call this lead", "due_minutes": 120}]}]}


async def builder_plan(ctx, pack, trigger, instruction, project_id, chat):
    spec = spec_from_text(instruction or "")
    return [("automations.create_from_spec", {"spec": spec})], f"Drafted \"{spec['name']}\". It's saved switched off so you can check it first."


# ---------------- Chat ----------------

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                       "november", "december"], 1)}


def _for_name(q):
    m = re.search(r"\b(?:for|on|with)\s+([A-Za-z0-9][\w&.' -]{1,40}?)(?:\?|$|,|\.| this| next| today| yesterday| strategy| work| two| \d)", q)
    return m.group(1).strip() if m else None


def chat_addons(q, ql, t0):
    """Rates, time, budgets, retainers, estimates, forecast, client tasks."""
    m = re.match(r"^log\s+(\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?)\s+(?:on|for)\s+(.+?)(?:\s+(today|yesterday))?\.?$", q, re.I)
    if m:
        amt, unit, rest, when = float(m.group(1)), m.group(2).lower(), m.group(3), (m.group(4) or "today").lower()
        mins = int(round(amt * (60 if unit.startswith("h") else 1)))
        name = rest.split()[0]
        day = (t0 - timedelta(days=1 if when == "yesterday" else 0)).date().isoformat()
        return [("time.log", {"project_name": name, "minutes": mins, "date": day, "note": rest})], \
            (lambda res: (res.get("time.log") or {}).get("summary") or (res.get("time.log") or {}).get("error") or "Logged.")
    if "unbilled" in ql:
        return [("time.unbilled", {})], (lambda res: (res.get("time.unbilled") or {}).get("summary") or "No unbilled time.")
    if re.search(r"over budget|budgets? at risk|near (the|their) budget|which .*budget", ql):
        return [("budgets.at_risk", {})], (lambda res: (res.get("budgets.at_risk") or {}).get("summary") or "No budgets at risk.")
    if re.search(r"hours?.*(left|remaining)|(left|remaining).*hours?", ql) and _for_name(q):
        return [("retainers.statement", {"project_name": _for_name(q)})], \
            (lambda res: (res.get("retainers.statement") or {}).get("summary") or (res.get("retainers.statement") or {}).get("error") or "No retainer found.")
    m = re.search(r"raise .*rates?.* by (\d+(?:\.\d+)?)\s*%(?:.*from\s+(\w+))?", ql)
    if m:
        pct = float(m.group(1))
        mon = MONTHS.get((m.group(2) or "").lower())
        if mon:
            y = t0.year + (1 if mon <= t0.month else 0)
            start = f"{y}-{mon:02d}-01"
        else:
            start = (t0 + timedelta(days=1)).date().isoformat()
        return [("rate_changes.schedule", {"pct": pct, "effective_from": start})], \
            (lambda res: (res.get("rate_changes.schedule") or {}).get("summary") or (res.get("rate_changes.schedule") or {}).get("error") or "Done.")
    if re.search(r"\b(day|hourly|daily) rate\b|\bmy rate\b", ql):
        args = {"project_name": _for_name(q)} if _for_name(q) else {}

        def s(res):
            r = res.get("rates.resolve") or {}
            if r.get("error"):
                return r["error"]
            if r.get("rate_paise") is None:
                return "Rates are hidden for your role."
            who = f" for {r['project']}" if r.get("project") else ""
            if "day" in ql and r.get("unit") != "day" and r.get("hourly_paise"):
                return f"Your day rate{who} works out to {inr(r['hourly_paise'] * 8)} ({inr(r['hourly_paise'])}/hour, from the {r['source']})."
            return f"Your rate{who} is {inr(r['rate_paise'])} {r.get('unit_label', '').lower()} (from the {r['source']})."
        return [("rates.resolve", args)], s
    if re.match(r"^(estimate|quote|price)\b", ql):
        return [("estimates.draft_from_text", {"project_name": _for_name(q), "text": q})], \
            (lambda res: (res.get("estimates.draft_from_text") or {}).get("summary") or (res.get("estimates.draft_from_text") or {}).get("error") or "Done.")
    m = re.search(r"what does (\w+) look like|forecast|coming in|expected (income|money)", ql)
    if m:
        mon = MONTHS.get((m.group(1) or "").lower()) if m.group(1) else None

        def s(res):
            r = res.get("forecast.get") or {}
            if r.get("error"):
                return r["error"]
            rows = r.get("months", [])
            row = next((x for x in rows if mon and int(x["month"][5:7]) == mon), None)
            if row:
                return (f"{row['label']}: {inr(row['confirmed_paise'])} confirmed. Pipeline adds an estimated {inr(row['pipeline_paise'])} "
                        f"(weighted by each stage's win chance).")
            return r.get("summary") or "No forecast yet."
        return [("forecast.get", {"months": 12})], s
    if re.search(r"waiting (on|for) (the )?clients?|client tasks?", ql):
        def s(res):
            rows = res.get("client_tasks.list") or []
            if not rows:
                return "You're not waiting on any client right now."
            return f"Waiting on clients for {len(rows)} thing{'s' if len(rows) != 1 else ''}: " + "; ".join(
                f"{r['project']}: {r['title']}" + (" (overdue)" if r.get("overdue") else "") for r in rows[:6]) + "."
        return [("client_tasks.list", {"status": "open"})], s
    return None


async def chat_plan(ctx, pack, trigger, instruction, project_id, chat):
    q = (instruction or "").strip()
    ql = q.lower()
    t0 = now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    addon = chat_addons(q, ql, t0)
    if addon:
        return addon
    if re.search(r"lead|enquir", ql):
        since = t0 - timedelta(days=7 if "week" in ql else 30 if "month" in ql else 1 if "today" in ql else 7)

        def s(res):
            items = (res.get("projects.search") or {}).get("items", [])
            if not items:
                return "No new leads in that period."
            return f"{len(items)} lead{'s' if len(items) != 1 else ''} came in: " + "; ".join(f"{i['name']} ({i.get('source') or 'no source'})" for i in items[:10]) + "."
        return [("projects.search", {"created_from": since.isoformat(), "limit": 50})], s
    if re.search(r"owe|overdue|outstanding|due|unpaid", ql):
        def s(res):
            r = res.get("payments.list_due") or {}
            g, tt = r.get("groups", {}), r.get("totals_paise", {})
            parts = [f"Overdue: {inr(tt.get('overdue') or 0)} across {len(g.get('overdue', []))} payment(s)"]
            if g.get("processing"):
                parts.append(f"{len(g['processing'])} payment(s) waiting for your confirmation")
            if g.get("overdue"):
                parts.append("Biggest: " + ", ".join(f"{i['project']} {inr(i['amount_paise'] - i['paid_paise'])}" for i in sorted(g['overdue'], key=lambda x: -x['amount_paise'])[:3]))
            return ". ".join(parts) + "."
        return [("payments.list_due", {})], s
    if re.search(r"today|schedule|calendar|session|meeting", ql):
        def s(res):
            items = [i for i in (res.get("calendar.list") or []) if i["kind"] == "session"]
            return "No sessions today." if not items else "Today: " + "; ".join(f"{fmt_dt(i['start']).split(', ')[-1]} {i['title']} ({i.get('project') or ''})" for i in items)
        return [("calendar.list", {"date_from": t0.isoformat(), "date_to": (t0 + timedelta(days=1)).isoformat()})], s
    m = re.match(r"(?:add|create|remind me to|new)\s+(?:a\s+)?(?:task\s*(?:to|:)?\s*)?(.+)", q, re.I)
    if m and ("task" in ql or "remind" in ql):
        title = m.group(1).strip().rstrip(".")
        return [("tasks.create", {"title": title[:120], "due_at": (t0 + timedelta(days=1, hours=10)).isoformat()})], f"Added a task: {title}."
    if q:
        def s(res):
            r = res.get("search.all") or {}
            ps, cs = r.get("projects", []), r.get("contacts", [])
            if not ps and not cs:
                return "I can answer questions about your leads, payments, sessions and tasks, and add tasks. Try: \"Which leads came in this week?\""
            return "I found: " + "; ".join([p["name"] for p in ps[:5]] + [c["name"] for c in cs[:5]]) + "."
        return [("search.all", {"q": q[:60]})], s
    return [], "How can I help?"


AGENTS = {
    "setup": AgentDef("setup", "Setup agent", "You interview a new consultant and build their account.", [], "draft", "large",
                      wakes_on="First login"),
    "lead": AgentDef("lead", "Lead agent",
                     "You are the Lead agent for a consulting practice. For a new enquiry: score the fit (0–100) against the ideal client "
                     "and say why in a note, then write a short, warm first reply that offers 2–3 call times from availability.find_slots "
                     "and the booking link. Send it with messages.send (it will wait for the consultant's OK).",
                     ["projects.get", "contacts.get", "availability.find_slots", "session_types.list", "notes.add", "tags.add",
                      "messages.send", "messages.draft"], plan=lead_plan, after=lead_after, why_text="New enquiry", wakes_on="New lead or inbound email",
                     default_instruction="Reply to this new enquiry and offer call slots."),
    "followup": AgentDef("followup", "Follow-up agent",
                         "You find leads that went quiet, proposals not opened, and contracts not signed, and write one short nudge for each.",
                         ["projects.search", "projects.get", "files.list", "files.status", "messages.send", "client_tasks.remind",
                          "budgets.get", "retainers.statement"], plan=followup_plan,
                         why_text="Morning follow-up check", wakes_on="Every morning, 8:00 IST"),
    "meeting": AgentDef("meeting", "Meeting agent",
                        "Before a session: write a one-page prep brief as a note. After: turn the transcript into a summary, decisions and "
                        "to-dos; add each to-do as a task. Anything the client promised to send becomes a client task.",
                        ["projects.get", "notes.add", "tasks.create", "client_tasks.assign"], "internal_auto", plan=meeting_plan,
                        after=meeting_after, why_text="Session", wakes_on="1 hour before and right after each session"),
    "proposal": AgentDef("proposal", "Proposal agent",
                         "Turn call notes into a client file: pick the right proposal template, write the intro from what the client said, "
                         "set the contract dates, then send it (it will wait for the consultant's OK).",
                         ["projects.get", "templates.list", "files.create_from_template", "files.get", "files.update_block", "files.send",
                          "estimates.draft_from_text", "estimates.finalise", "estimates.to_quote", "estimates.get", "rates.resolve",
                          "reports.profitability"],
                         plan=proposal_plan, model_size="large", why_text="After the discovery call", wakes_on="After a discovery call, or on request"),
    "collections": AgentDef("collections", "Collections agent",
                            "For overdue payments, pick the right tone by how late and how large, draft the reminder, and flag possible "
                            "disputes to the consultant instead of chasing. At month end, draft invoices for unbilled time.",
                            ["payments.list_due", "invoices.get", "messages.send", "time.unbilled", "invoices.add_unbilled_time", "invoices.send"],
                            plan=collections_plan, why_text="Overdue payment", wakes_on="Payment overdue, and daily"),
    "daily_brief": AgentDef("daily_brief", "Daily brief", "Write today's three priorities, money due this week and what changed.",
                            ["approvals.list"], "read_only", plan=brief_plan, after=brief_after, wakes_on="Every morning"),
    "automation_builder": AgentDef("automation_builder", "Automation builder",
                                   "Turn a plain-language request into an automation spec (trigger, steps, waits, conditions) using "
                                   "automations.create_from_spec. It is saved switched off.", ["automations.create_from_spec", "templates.list"],
                                   plan=builder_plan, wakes_on="In the automations screen"),
    "chat": AgentDef("chat", "Ask or tell",
                     "You answer questions about this practice's account and carry out requests with the tools you have. Keep answers short.",
                     "*", "per_level", plan=chat_plan, kind="chat", wakes_on="Any time"),
}
