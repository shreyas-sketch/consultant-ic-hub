"""Client tasks (add-on A7): ask the client for something, with a due date and reminders.

Client tasks are the only tasks a client can ever see. They show in the portal
and arrive by WhatsApp or email with a link; the client can mark them done,
upload a file (it lands in the project's Files) or reply. Replying "done" on
WhatsApp completes their one open task.
"""
from datetime import timedelta
from typing import Optional

from app.domain import perm
from app.domain.registry import STAFF, P, action
from app.core import limits
from app.core.events import emit, log, notify
from app.core.util import IST, AppError, aware, clean, fmt_date, not_found, now, token


async def _refresh_flag(ctx, project_id):
    n = await ctx.data.tasks.count({"project_id": project_id, "audience": "client", "done": False})
    await ctx.data.projects.update({"_id": project_id}, {"open_client_tasks": n, "waiting_on_client": n > 0})


def link_of(ws, t):
    from app.domain.documents.merge import client_base
    return f"{client_base(ws)}/t/{t['token']}"


async def _send(ctx, t, pr, reminder=False, idem=None):
    from app.domain.engagement.inbox import contact_for, send_message
    from app.domain.documents.merge import build
    ws = await ctx.ws()
    c = await contact_for(ctx, pr, t.get("client_contact_id"))
    v = await build(ctx, pr, c)
    link = link_of(ws, t)
    due = fmt_date(t["due_at"]) if t.get("due_at") else "when you can"
    who = v.get("consultant.name") or v.get("practice.name")
    sent = 0
    ch = t.get("channel") or "both"
    if ch in ("email", "both") and c.get("email"):
        await send_message(ctx, pr["_id"], c, "email", ("Reminder: " if reminder else "") + t["title"],
                           f"<p>Hi {v['client.first_name']},</p><p>{who} needs something from you: <b>{t['title']}</b>.</p>"
                           + (f"<p>{t['details']}</p>" if t.get("details") else "") + f"<p>Due: {due}.</p>",
                           button=("Open", link), kind="client_task", idem_key=f"{idem}:email" if idem else None)
        sent += 1
    if ch in ("whatsapp", "both") and c.get("phone"):
        await send_message(ctx, pr["_id"], c, "whatsapp", wa_template="client_task",
                           wa_params=[v["client.first_name"], who, t["title"], due, link], kind="client_task",
                           idem_key=f"{idem}:wa" if idem else None)
        sent += 1
    if not sent:
        raise AppError("no_contact", "This client has no email or WhatsApp number.", 400)
    return sent


class AssignIn(P):
    project_id: str
    title: str
    details: str = ""
    due_at: Optional[str] = None
    contact_id: Optional[str] = None
    channel: str = "both"            # whatsapp | email | both
    remind_days_before: int = 1


@action("client_tasks.assign", "external", AssignIn, roles=STAFF,
        desc="Ask the client for something (e.g. 'Share last year's P&L') with a due date. It goes by WhatsApp or email with a link.")
async def client_tasks_assign(ctx, p: AssignIn):
    await limits.require(ctx, "client_tasks")
    pr = await perm.project(ctx, p.project_id, act=True)
    if not p.title.strip():
        raise AppError("invalid", "What do you need from the client?", 400)
    if p.channel not in ("whatsapp", "email", "both"):
        raise AppError("invalid", "Send by WhatsApp, email or both.", 400)
    due = aware(p.due_at) if p.due_at else None
    t = await ctx.data.tasks.insert({"title": p.title.strip()[:200], "details": p.details[:1000], "project_id": pr["_id"], "audience": "client",
                                     "client_contact_id": p.contact_id or (pr.get("contact_ids") or [None])[0], "assignee_id": None,
                                     "due_at": due, "done": False, "created_by": ctx.actor, "token": token(18), "channel": p.channel,
                                     "remind_days_before": max(0, min(int(p.remind_days_before), 14)), "reminded": False,
                                     "overdue_flagged": False, "replies": [], "upload_ids": []})
    await _send(ctx, t, pr, idem=f"ctask:{t['_id']}")
    await _refresh_flag(ctx, pr["_id"])
    await log(ctx, pr["_id"], "task", f"Asked the client: {t['title']}", ref=t["_id"], client_visible=True)
    await emit(ctx, "client_task.assigned", {"task_id": t["_id"]}, pr["_id"])
    return clean(t)


class IdIn(P):
    id: str


async def get_ct(ctx, tid, act=False):
    t = await ctx.data.tasks.get(tid)
    if not t or t.get("audience") != "client":
        raise not_found("That client task")
    pr = await perm.project(ctx, t["project_id"], act=act)
    return t, pr


@action("client_tasks.remind", "external", IdIn, roles=STAFF, desc="Remind the client about something you asked for.")
async def client_tasks_remind(ctx, p: IdIn):
    t, pr = await get_ct(ctx, p.id, act=True)
    if t["done"]:
        raise AppError("invalid", "The client already did this.", 400)
    n = await _send(ctx, t, pr, reminder=True)
    await ctx.data.tasks.update({"_id": t["_id"]}, {"last_reminded_at": now()})
    return {"ok": True, "sent": n}


async def complete(ctx, t, by="client", note=""):
    got = await ctx.data.tasks.find_one_and_update({"_id": t["_id"], "done": False}, {"$set": {"done": True, "done_at": now(), "done_by": by}})
    if not got:
        return False
    await _refresh_flag(ctx, t["project_id"])
    await log(ctx, t["project_id"], "task", f"{'Client' if by == 'client' else 'Marked'} done: {t['title']}" + (f" — {note[:80]}" if note else ""),
              ref=t["_id"], client_visible=True)
    await emit(ctx, "client_task.completed", {"task_id": t["_id"], "by": by}, t["project_id"])
    if by == "client":
        await notify(ctx, f"Your client finished: {t['title']}", "task", link=f"/projects/{t['project_id']}?tab=tasks")
    return True


@action("client_tasks.complete", "internal", IdIn, roles=STAFF, desc="Mark something you asked the client for as done (e.g. they sent it another way).")
async def client_tasks_complete(ctx, p: IdIn):
    t, _ = await get_ct(ctx, p.id, act=True)
    await complete(ctx, t, by="consultant")
    return {"ok": True}


class ListIn(P):
    project_id: Optional[str] = None
    status: str = "open"   # open | done | overdue | all


@action("client_tasks.list", "read", ListIn, desc="What you're waiting on clients for.")
async def client_tasks_list(ctx, p: ListIn):
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    f = {"audience": "client", "project_id": p.project_id if p.project_id in vis else "-"} if p.project_id else \
        {"audience": "client", "project_id": {"$in": vis}}
    if p.status in ("open", "overdue"):
        f["done"] = False
    elif p.status == "done":
        f["done"] = True
    if p.status == "overdue":
        f["due_at"] = {"$lt": now()}
    rows = await ctx.data.tasks.find(f, sort=[("due_at", 1)], limit=300)
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": list({r["project_id"] for r in rows})}})}
    out = []
    for r in rows:
        o = clean(r)
        o["project"] = names.get(r["project_id"], "")
        o["overdue"] = bool(not r["done"] and r.get("due_at") and aware(r["due_at"]) < now())
        out.append(o)
    return out


async def complete_from_reply(ctx, project_id, text):
    open_ = await ctx.data.tasks.find({"project_id": project_id, "audience": "client", "done": False})
    if len(open_) == 1:
        await complete(ctx, open_[0], by="client", note="replied on WhatsApp")


# ---------------- public (the client's link) ----------------

async def public_view(ctx, t):
    pr = await ctx.data.projects.get(t["project_id"])
    ups = await ctx.data.uploads.find({"_id": {"$in": t.get("upload_ids") or []}})
    return {"title": t["title"], "details": t.get("details") or "", "due": fmt_date(t["due_at"]) if t.get("due_at") else None,
            "overdue": bool(not t["done"] and t.get("due_at") and aware(t["due_at"]) < now()), "done": t["done"],
            "project": (pr or {}).get("name", ""), "replies": [{"text": r["text"], "at": r["at"]} for r in t.get("replies") or []],
            "uploads": [{"name": u["name"]} for u in ups]}


async def public_reply(ctx, t, text):
    from app.domain.engagement.inbox import receive
    text = (text or "").strip()[:2000]
    if not text:
        raise AppError("invalid", "The reply is empty.", 400)
    await ctx.data.tasks.update({"_id": t["_id"]}, {}, raw={"$push": {"replies": {"text": text, "at": now().isoformat()}}})
    c = await ctx.data.contacts.get(t.get("client_contact_id") or "") or {}
    await receive(ctx, t["project_id"], "portal", c.get("email") or c.get("phone") or "client", f"Re: {t['title']}", text)


async def public_upload(ctx, t, name, data):
    from app.services.uploads import data_url_to_key
    key = await data_url_to_key(ctx.ws_id, data, "client-task")
    up = await ctx.data.uploads.insert({"project_id": t["project_id"], "name": (name or "Upload")[:120], "key": key, "kind": "client_upload",
                                        "client_visible": True, "by_client": True, "token": token(18), "client_task_id": t["_id"]})
    await ctx.data.tasks.update({"_id": t["_id"]}, {}, raw={"$push": {"upload_ids": up["_id"]}})
    await log(ctx, t["project_id"], "upload", f"Client uploaded {up['name']} for \"{t['title']}\"", ref=up["_id"], client_visible=True)
    await notify(ctx, f"Your client uploaded {up['name']} for \"{t['title']}\".", "upload", link=f"/projects/{t['project_id']}?tab=files")
    return up


# ---------------- job: reminders and overdue ----------------

async def run_due(ws_id):
    """Send the reminder set when it was assigned (before the due date); flag overdue once (the follow-up agent drafts a nudge)."""
    from app.core.context import system_ctx
    ctx = system_ctx(ws_id)
    n = 0
    for t in await ctx.data.tasks.find({"audience": "client", "done": False, "due_at": {"$ne": None}}):
        due = aware(t["due_at"])
        before = due - timedelta(days=int(t.get("remind_days_before") or 0))
        if t.get("remind_days_before") and not t.get("reminded") and before <= now() < due:
            got = await ctx.data.tasks.find_one_and_update({"_id": t["_id"], "reminded": False}, {"$set": {"reminded": True}})
            if got:
                pr = await ctx.data.projects.get(t["project_id"])
                try:
                    await _send(ctx, t, pr, reminder=True, idem=f"ctask-remind:{t['_id']}")
                    n += 1
                except AppError:
                    pass
        if due < now():
            got = await ctx.data.tasks.find_one_and_update({"_id": t["_id"], "overdue_flagged": False}, {"$set": {"overdue_flagged": True}})
            if got:
                await emit(ctx, "client_task.overdue", {"task_id": t["_id"], "title": t["title"]}, t["project_id"])
                n += 1
    return n


_ = IST
