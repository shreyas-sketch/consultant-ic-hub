"""Approvals: everything an agent or automation prepared that waits for the
consultant's OK. Approve runs the stored action with its idempotency key, so
approving twice (or two people at once) never sends twice."""
from datetime import timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from app.domain import perm
from app.domain.registry import ACTIONS, P, action, call
from app.core.events import log, notify
from app.core.util import AppError, clean, new_id, not_found, now

EXPIRE_DAYS = 7


async def create_approval(ctx, action_name, args, preview, why, project_id=None, source="agent", agent=None,
                          automation_id=None, run_id=None, step_id=None, idem=None, agent_run_id=None):
    key = idem or f"{ctx.agent_run_id or new_id()}:{action_name}:{new_id()[:6]}"
    doc = {"action": action_name, "args": args, "preview": preview, "why": why, "project_id": project_id, "source": source,
           "agent": agent or (ctx.actor.split(":", 1)[1] if ctx.actor.startswith("agent:") else None),
           "actor": ctx.actor, "automation_id": automation_id, "run_id": run_id, "step_id": step_id,
           "agent_run_id": agent_run_id or ctx.agent_run_id, "idempotency_key": key, "status": "pending",
           "level": ACTIONS[action_name].level, "expires_at": now() + timedelta(days=EXPIRE_DAYS)}
    try:
        a = await ctx.data.approvals.insert(doc)
    except DuplicateKeyError:
        return await ctx.data.approvals.find_one({"idempotency_key": key})
    who = doc["agent"].replace("_", " ").title() + " agent" if doc["agent"] else "Automation"
    await log(ctx, project_id, "approval", f"{who} prepared: {preview.get('subject') or preview.get('summary') or action_name} — waiting for your OK",
              ref=a["_id"])
    await notify(ctx, f"Needs your OK: {preview.get('subject') or preview.get('summary') or action_name}", "approval", link="/approvals")
    return a


class ListIn(P):
    status: str = "pending"
    project_id: Optional[str] = None


@action("approvals.list", "read", ListIn, agent_ok=False, desc="Things waiting for your OK.")
async def approvals_list(ctx, p: ListIn):
    f = {"status": p.status}
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    rows = await ctx.data.approvals.find(f, sort=[("created_at", -1)], limit=200)
    out = []
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": [r["project_id"] for r in rows if r.get("project_id")]}})}
    for r in rows:
        if r.get("project_id"):
            pr = await ctx.data.projects.get(r["project_id"])
            if not pr or not perm.can_see(ctx, pr):
                continue
        o = clean(r)
        o["project_name"] = names.get(r.get("project_id"), "")
        out.append(o)
    return out


async def _may_decide(ctx, approval_id):
    """Deciding needs the right to act on the approval's project (checked before anything changes).
    Approvals with no project (practice-wide) are for Owners, Admins and Managers."""
    a = await ctx.data.approvals.get(approval_id)
    if not a:
        raise not_found("That item")
    if a.get("project_id"):
        await perm.project(ctx, a["project_id"], act=True)
    elif ctx.role not in perm.SEE_ALL:
        raise not_found("That item")
    return a


class DecideIn(P):
    id: str
    edits: Optional[dict] = None   # changed args, e.g. {"subject": ..., "body": ...}


@action("approvals.approve", "internal", DecideIn, agent_ok=False, desc="Approve and run a prepared action (optionally after editing it).")
async def approvals_approve(ctx, p: DecideIn):
    await _may_decide(ctx, p.id)
    a = await ctx.data.approvals.find_one_and_update({"_id": p.id, "status": "pending"}, {"$set": {"status": "executing", "decided_by": ctx.user_id}})
    if not a:
        raise AppError("gone", "This item was already handled or has expired.", 409)
    args = dict(a["args"])
    if p.edits:
        args.update({k: v for k, v in p.edits.items() if k in ("subject", "body", "channel", "message", "start", "amount_paise", "wa_params")})
    # Approving is the consultant sending it by hand (so quiet hours don't hold it back).
    actx = ctx.child(actor=a["actor"], idem_key=a["idempotency_key"], agent_run_id=a.get("agent_run_id"), via="approval")
    try:
        result = await call(actx, a["action"], args)
    except AppError as e:
        await ctx.data.approvals.update({"_id": a["_id"]}, {"status": "failed", "error": e.message})
        raise
    await ctx.data.approvals.update({"_id": a["_id"]}, {"status": "approved", "decided_at": now(), "edited": bool(p.edits),
                                                        "result_ref": (result or {}).get("id") if isinstance(result, dict) else None})
    if a.get("run_id"):
        from app.automations.engine import resume_after_approval
        await resume_after_approval(a["run_id"], True, "edited first" if p.edits else "")
    return {"ok": True}


@action("approvals.skip", "internal", DecideIn, agent_ok=False, desc="Skip a prepared action. Nothing is sent.")
async def approvals_skip(ctx, p: DecideIn):
    await _may_decide(ctx, p.id)
    a = await ctx.data.approvals.find_one_and_update({"_id": p.id, "status": "pending"}, {"$set": {"status": "skipped", "decided_by": ctx.user_id,
                                                                                                  "decided_at": now()}})
    if not a:
        raise AppError("gone", "This item was already handled or has expired.", 409)
    await log(ctx, a.get("project_id"), "approval", "Skipped: " + (a["preview"].get("subject") or a["action"]), ref=a["_id"])
    if a.get("run_id"):
        from app.automations.engine import resume_after_approval
        await resume_after_approval(a["run_id"], False)
    if a.get("on_skip"):
        # e.g. retainer overage with "ask first": skipping means "absorb it".
        from app.domain.registry import call
        try:
            await call(ctx.child(via="approval"), a["on_skip"]["action"], a["on_skip"].get("args") or {})
        except AppError:
            pass
    return {"ok": True}

