"""Inbox: one thread per project, email and WhatsApp in one list.

All client-facing sends go through send_message():
- an idempotency key stops double sends (retries, two workers, double clicks);
- quiet hours: automations and agents never message clients 9 pm–8 am, the
  message is queued for 8 am instead (sends by hand are not held);
- WhatsApp free-form text only inside 24 hours of the client's last message;
- every send records its status: queued, scheduled, sent, delivered, opened, bounced, failed.
"""
from datetime import timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

import vendors
from actions import perm
from actions.merge import build, fill
from actions.registry import STAFF, P, action
from core import limits
from core.events import emit, log
from core.util import IST, AppError, aware, clean, new_id, not_found, now

CH = {"whatsapp": "WhatsApp", "email": "Email", "portal": "Portal message"}

WA_TEMPLATES = {
    "file_link": "Hi {{1}}, {{2}} sent you a document: {{3}}",
    "payment_reminder": "Hi {{1}}, a reminder that {{2}} is due. Pay here: {{3}}",
    "session_reminder": "Hi {{1}}, reminder: your session with {{2}} is at {{3}}. Link: {{4}}",
    "booking_confirmed": "Hi {{1}}, your session with {{2}} is booked for {{3}}. Link: {{4}}",
    "consultant_alert": "{{1}}",
    "general_update": "Hi {{1}}, {{2}}",
    "client_task": "Hi {{1}}, {{2}} needs something from you: {{3}}. Due {{4}}. Open: {{5}}",
}


def email_wrap(ws, body_html, button=None):
    th = ws.get("theme", {})
    btn = ""
    if button:
        btn = (f'<p style="margin:28px 0"><a href="{button[1]}" style="background:{th.get("primary", "#C9A84C")};'
               f'color:{th.get("button_text", "#14151A")};padding:14px 26px;border-radius:999px;text-decoration:none;'
               f'font-weight:800;font-family:Manrope,Arial,sans-serif">{button[0]}</a></p>')
    name = ws.get("profile", {}).get("practice_name") or ws["name"]
    return (f'<div style="background:#FAF8F3;padding:32px 16px;font-family:Manrope,Arial,sans-serif;color:#14151A">'
            f'<div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #E6E1D6;border-radius:14px;padding:28px">'
            f'<div style="font-weight:700;letter-spacing:.2em;font-size:12px;color:#8F7635;text-transform:uppercase">{name}</div>'
            f'<div style="font-size:16px;line-height:1.6;margin-top:16px">{body_html}</div>{btn}</div></div>')


def in_quiet_hours(ws, t=None):
    q = ws.get("settings", {}).get("quiet_hours", {"start": 21, "end": 8})
    h = aware(t or now()).astimezone(IST).hour
    return h >= q["start"] or h < q["end"]


def next_morning(ws, t=None):
    q = ws.get("settings", {}).get("quiet_hours", {"start": 21, "end": 8})
    d = aware(t or now()).astimezone(IST)
    m = d.replace(hour=q["end"], minute=0, second=0, microsecond=0)
    if d.hour >= q["end"]:
        m += timedelta(days=1)
    return m


async def thread_for(ctx, project_id):
    th = await ctx.data.threads.find_one({"project_id": project_id})
    if not th:
        th = await ctx.data.threads.insert({"project_id": project_id, "last_message_at": now(), "unread": 0,
                                            "last_client_whatsapp_at": None})
    return th


async def gmail_connection(ctx):
    return await ctx.data.connections.find_one({"provider": {"$in": ["gmail", "outlook"]}, "user_id": ctx.user_id}) or \
        await ctx.data.connections.find_one({"provider": {"$in": ["gmail", "outlook"]}})


async def send_message(ctx, project_id, contact, channel, subject="", html="", text=None, wa_template=None, wa_params=None,
                       schedule_at=None, idem_key=None, kind="message", button=None):
    """The one way a message reaches a client. Returns the message doc."""
    if ctx.dry_run:
        return {"dry_run": True, "channel": channel, "subject": subject}
    ws = await ctx.ws()
    th = await thread_for(ctx, project_id)
    to = contact.get("email") if channel == "email" else contact.get("phone")
    if not to:
        raise AppError("no_address", f"This client has no {'email' if channel == 'email' else 'mobile number'} yet.", 400)
    if channel == "whatsapp" and text is not None and wa_template is None:
        last = th.get("last_client_whatsapp_at")
        if not last or aware(last) < now() - timedelta(hours=24):
            raise AppError("window_closed", "WhatsApp only allows free-form replies within 24 hours of the client's last "
                                            "message. Send an approved template instead.", 400, {"templates": list(WA_TEMPLATES)})
    # Quiet hours apply to agents and automations. Sends by hand and transactional
    # messages (booking confirmations, session reminders, OTPs, signed copies) go now.
    if ctx.actor.startswith(("agent:", "automation:")) and ctx.via != "approval" and in_quiet_hours(ws) and not schedule_at:
        schedule_at = next_morning(ws)
    base = idem_key or ctx.idem_key
    key = f"{base}:{channel}:{kind}" if base else new_id()
    msg = {"_id": new_id(), "thread_id": th["_id"], "project_id": project_id, "contact_id": contact.get("_id"), "channel": channel,
           "direction": "out", "subject": subject, "body_html": html, "body_text": text, "wa_template": wa_template,
           "wa_params": wa_params or [], "to": to, "status": "queued", "actor": ctx.actor, "user_id": ctx.user_id,
           "agent_run_id": ctx.agent_run_id, "kind": kind, "idempotency_key": key, "button": button,
           "scheduled_at": aware(schedule_at) if schedule_at else None}
    try:
        await ctx.data.outbound_queue.insert({"idempotency_key": key, "message_id": msg["_id"], "status": "pending",
                                              "send_at": msg["scheduled_at"] or now()})
    except DuplicateKeyError:
        q = await ctx.data.outbound_queue.find_one({"idempotency_key": key})
        return await ctx.data.messages.get(q["message_id"]) or {"duplicate": True}
    await ctx.data.messages.insert(msg)
    if msg["scheduled_at"] and aware(msg["scheduled_at"]) > now() + timedelta(seconds=30):
        await ctx.data.messages.update({"_id": msg["_id"]}, {"status": "scheduled"})
        await log(ctx, project_id, "message", f"{CH.get(channel, channel)} scheduled for {msg['scheduled_at'].astimezone(IST):%d %b, %I:%M %p}",
                  ref=msg["_id"])
        return await ctx.data.messages.get(msg["_id"])
    return await deliver(ctx, msg)


async def deliver(ctx, msg):
    ws = await ctx.ws()
    try:
        if msg["channel"] == "whatsapp":
            await limits.consume(ctx, "whatsapp_per_month")
            r = await vendors.whatsapp_send(ctx.ws_id, msg["to"], template=msg.get("wa_template"), params=msg.get("wa_params"),
                                            text=msg.get("body_text") if not msg.get("wa_template") else None)
        else:
            conn = await gmail_connection(ctx)
            r = await vendors.email_send(ctx.ws_id, msg["to"], msg["subject"], email_wrap(ws, msg["body_html"], msg.get("button")),
                                         reply_to=vendors.reply_address(msg["thread_id"]),
                                         from_name=ws.get("profile", {}).get("consultant_name") or ws["name"], connection=conn)
        status = "delivered" if r.get("status") == "sent" and vendors.mode("email" if msg["channel"] == "email" else "whatsapp") == "fake" else r.get("status", "sent")
        ch = {"status": status, "provider_id": r.get("provider_id"), "sent_at": now(), "via": r.get("via")}
    except AppError as e:
        ch = {"status": "failed", "error": e.message}
    await ctx.data.messages.update({"_id": msg["_id"]}, ch)
    await ctx.data.outbound_queue.update({"idempotency_key": msg["idempotency_key"]}, {"status": "done"})
    await ctx.data.threads.update({"_id": msg["thread_id"]}, {"last_message_at": now()})
    await ctx.data.projects.update({"_id": msg["project_id"]}, {"last_activity_at": now()})
    who = {"user": "", "client": ""}.get(ctx.actor, f" by {ctx.actor.replace('agent:', '').replace('_', ' ')}"
                                         f"{' agent' if ctx.actor.startswith('agent:') else ''}")
    label = msg.get("subject") or (msg.get("body_text") or msg.get("wa_template") or "")[:60]
    await log(ctx, msg["project_id"], "message", f"{CH.get(msg['channel'], msg['channel'])} {'sent' if ch['status'] != 'failed' else 'failed'}{who}: {label}",
              ref=msg["_id"], client_visible=True)
    if ctx.by_hand() and ch["status"] != "failed":
        await emit(ctx, "message.sent_by_hand", {"message_id": msg["_id"]}, msg["project_id"])
    return await ctx.data.messages.get(msg["_id"])


async def contact_for(ctx, project, contact_id=None):
    cid = contact_id or (project.get("contact_ids") or [None])[0]
    c = await ctx.data.contacts.get(cid) if cid else None
    if not c:
        raise AppError("no_contact", "Add a contact to this project first.", 400)
    return c


# ---------------- actions ----------------

class SendIn(P):
    project_id: str
    channel: str = "email"     # email | whatsapp
    subject: str = ""
    body: str = ""             # html for email, text for WhatsApp
    template_id: Optional[str] = None
    wa_template: Optional[str] = None
    wa_params: list = []
    contact_id: Optional[str] = None
    schedule_at: Optional[str] = None


@action("messages.send", "external", SendIn, desc="Send an email or WhatsApp message to the project's client.")
async def messages_send(ctx, p: SendIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    c = await contact_for(ctx, pr, p.contact_id)
    subject, body = p.subject, p.body
    if p.template_id:
        t = await ctx.data.templates.get(p.template_id)
        if not t:
            raise not_found("That template")
        subject, body = subject or t["body"].get("subject", ""), body or t["body"].get("html", "")
    vals = await build(ctx, pr, c)
    if p.channel == "email":
        if not body.strip():
            raise AppError("invalid", "The message is empty.", 400)
        m = await send_message(ctx, pr["_id"], c, "email", fill(subject, vals, False), fill(body, vals), schedule_at=p.schedule_at)
    elif p.wa_template:
        if p.wa_template not in WA_TEMPLATES:
            raise AppError("invalid", "That WhatsApp template is not approved.", 400)
        m = await send_message(ctx, pr["_id"], c, "whatsapp", wa_template=p.wa_template, wa_params=p.wa_params, schedule_at=p.schedule_at)
    else:
        if not body.strip():
            raise AppError("invalid", "The message is empty.", 400)
        m = await send_message(ctx, pr["_id"], c, "whatsapp", text=fill(body, vals, False), schedule_at=p.schedule_at)
    return clean(m)


class DraftIn(P):
    project_id: str
    direction: str = ""
    tone: str = "warm"        # warm | formal | brief
    length: str = "short"     # short | medium
    channel: str = "email"


@action("messages.draft", "internal", DraftIn, desc="Write a message draft with AI (nothing is sent).")
async def messages_draft(ctx, p: DraftIn):
    from agents.writer import draft_message
    pr = await perm.project(ctx, p.project_id)
    return await draft_message(ctx, pr, p.direction, p.tone, p.length, p.channel)


class SaveDraftIn(P):
    project_id: str
    subject: str = ""
    body: str = ""
    channel: str = "email"


@action("messages.save_draft", "internal", SaveDraftIn, desc="Save an email draft on the project for later editing.")
async def messages_save_draft(ctx, p: SaveDraftIn):
    pr = await perm.project(ctx, p.project_id)
    th = await thread_for(ctx, pr["_id"])
    m = await ctx.data.messages.insert({"thread_id": th["_id"], "project_id": pr["_id"], "channel": p.channel, "direction": "out",
                                        "subject": p.subject, "body_html": p.body, "status": "draft", "actor": ctx.actor,
                                        "agent_run_id": ctx.agent_run_id})
    await log(ctx, pr["_id"], "draft", f"Draft saved: {p.subject or p.body[:40]}", ref=m["_id"])
    return clean(m)


class ThreadIn(P):
    project_id: str


@action("threads.get", "read", ThreadIn, desc="All messages on a project, oldest first.")
async def threads_get(ctx, p: ThreadIn):
    pr = await perm.project(ctx, p.project_id)
    th = await thread_for(ctx, pr["_id"])
    if ctx.actor == "user":
        await ctx.data.threads.update({"_id": th["_id"]}, {"unread": 0})
    msgs = await ctx.data.messages.find({"project_id": pr["_id"]}, sort=[("created_at", 1)], limit=500)
    window = th.get("last_client_whatsapp_at")
    return {"thread": clean(th), "messages": clean(msgs),
            "whatsapp_window_open": bool(window and aware(window) > now() - timedelta(hours=24)),
            "wa_templates": WA_TEMPLATES}


class InboxIn(P):
    filter: str = "all"   # all | unread
    channel: str = ""


@action("inbox.list", "read", InboxIn, desc="All conversations, unread first.")
async def inbox_list(ctx, p: InboxIn):
    vis = {pr["_id"]: pr for pr in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"name": 1, "contact_ids": 1})}
    f = {"project_id": {"$in": list(vis)}}
    if p.filter == "unread":
        f["unread"] = {"$gt": 0}
    ths = await ctx.data.threads.find(f, sort=[("unread", -1), ("last_message_at", -1)], limit=200)
    out = []
    for th in ths:
        last = await ctx.data.messages.find_one({"thread_id": th["_id"], "status": {"$ne": "draft"}}, sort=[("created_at", -1)])
        if not last or (p.channel and last["channel"] != p.channel):
            continue
        pr = vis[th["project_id"]]
        c = await ctx.data.contacts.get(pr["contact_ids"][0]) if pr.get("contact_ids") else None
        out.append({"thread_id": th["_id"], "project_id": pr["_id"], "project": pr["name"], "contact": (c or {}).get("name"),
                    "unread": th.get("unread", 0), "channel": last["channel"], "direction": last["direction"],
                    "preview": (last.get("subject") or last.get("body_text") or "")[:90], "at": clean(last)["created_at"]})
    return out


async def receive(ctx, project_id, channel, frm, subject="", text="", html=""):
    """A client's reply lands on the project thread."""
    th = await thread_for(ctx, project_id)
    m = await ctx.data.messages.insert({"thread_id": th["_id"], "project_id": project_id, "channel": channel, "direction": "in",
                                        "from": frm, "subject": subject, "body_text": text, "body_html": html, "status": "received",
                                        "actor": "client"})
    ch = {"last_message_at": now()}
    if channel == "whatsapp":
        ch["last_client_whatsapp_at"] = now()
    await ctx.data.threads.update({"_id": th["_id"]}, ch, raw={"$inc": {"unread": 1}})
    await ctx.data.projects.update({"_id": project_id}, {"last_activity_at": now()})
    await log(ctx.child(actor="client"), project_id, "message_in", f"{CH.get(channel, channel)} from client: {(subject or text)[:60]}",
              ref=m["_id"], client_visible=True)
    await emit(ctx.child(actor="client"), "message.received", {"message_id": m["_id"], "channel": channel}, project_id)
    # "Done" on WhatsApp completes the client's one open task on this project.
    if channel == "whatsapp" and (text or "").strip().lower().rstrip(".!") in ("done", "✅", "done ✅", "completed", "sent", "shared"):
        from actions.client_tasks import complete_from_reply
        await complete_from_reply(ctx, project_id, text)
    return m


STAFF_ = STAFF
