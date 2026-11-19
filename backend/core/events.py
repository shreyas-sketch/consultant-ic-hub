"""Domain events (the outbox), the activity feed, audit log and notifications."""
from core.util import now

EVENT_TYPES = [
    "lead_form.submitted", "project.created", "project.stage_changed", "project.archived",
    "tag.added", "questionnaire.submitted", "file.sent", "file.viewed", "file.completed",
    "contract.signed", "contract.fully_signed", "invoice.sent", "payment.claimed",
    "payment.first_paid", "invoice.paid_in_full", "payment.overdue", "session.scheduled",
    "session.starting", "session.ended", "session.cancelled", "message.received",
    "message.sent_by_hand", "task.completed", "approval.decided",
    # add-ons
    "rate.changed", "time.logged", "time.billed", "budget.threshold_reached", "budget.exceeded",
    "retainer.period_started", "retainer.usage_threshold", "retainer.period_closed", "retainer.renewal_due",
    "estimate.finalised", "quote.accepted", "estimate.converted",
    "client_task.assigned", "client_task.completed", "client_task.overdue",
]


async def emit(ctx, etype: str, payload: dict = None, project_id: str = None):
    """Write a domain event. The dispatcher job picks it up (stage rules,
    automations, agent triggers, event waits)."""
    assert etype in EVENT_TYPES, etype
    if ctx.dry_run:
        return None
    return await ctx.data.events.insert({
        "type": etype, "payload": payload or {}, "project_id": project_id,
        "processed": False, "actor": ctx.actor,
    })


async def log(ctx, project_id, kind, text, ref=None, client_visible=False, meta=None):
    """Activity feed entry on a project. Agent work is labelled by actor."""
    if not project_id or ctx.dry_run:
        return None
    return await ctx.data.activity.insert({
        "project_id": project_id, "kind": kind, "text": text, "ref": ref,
        "actor": ctx.actor, "user_id": ctx.user_id, "client_visible": client_visible,
        "agent_run_id": ctx.agent_run_id, "meta": meta or {}, "at": now(),
    })


async def audit(ctx, action, target=None, detail=None):
    await ctx.data.audit_log.insert({"actor": ctx.actor, "user_id": ctx.user_id, "action": action,
                                     "target": target, "detail": detail or {}})


async def notify(ctx, body, kind="info", link=None, user_ids=None, roles=("owner", "admin")):
    """In-app notification to named users, or to everyone with the given roles."""
    if ctx.dry_run:
        return
    if user_ids is None:
        ms = await ctx.data.memberships.find({"role": {"$in": list(roles)}, "active": True})
        user_ids = [m["user_id"] for m in ms]
    for uid in set(u for u in user_ids if u):
        await ctx.data.notifications.insert({"user_id": uid, "kind": kind, "body": body,
                                             "link": link, "read": False})
