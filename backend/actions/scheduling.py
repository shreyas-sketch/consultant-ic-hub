"""Scheduler and calendar.

- Times are stored in UTC and shown in the viewer's time zone (default IST).
- Two people can never book the same 1:1 slot: each host+start is a unique lock.
- A slot is held for 10 minutes while a client signs or pays; after "I've paid"
  it stays held until the consultant confirms (24 hours by default).
- Several availability windows per day are allowed.
"""
import math
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from pymongo.errors import DuplicateKeyError

import vendors
from actions import perm
from actions.registry import ADMINS, STAFF, P, action
from core import limits
from core.events import emit, log, notify
from core.util import IST, AppError, aware, clean, fmt_dt, new_id, not_found, now

HOLD_MINUTES = 10


def _hm(s):
    h, m = s.split(":")
    return int(h), int(m)


async def host_connection(ctx, host_id):
    return await ctx.data.connections.find_one({"user_id": host_id, "provider": {"$in": ["gmail", "outlook"]}})


async def busy_for(ctx, host_ids, start, end, exclude_session=None):
    """(start, end) busy blocks for the hosts: sessions (with buffers), holds and connected calendars."""
    out = []
    sess = await ctx.data.sessions.find({"host_ids": {"$in": host_ids}, "status": {"$in": ["booked", "held"]},
                                         "start": {"$lt": end + timedelta(hours=4)}, "end": {"$gt": start - timedelta(hours=4)}})
    for s in sess:
        if s["_id"] == exclude_session:
            continue
        b = timedelta(minutes=s.get("buffer_before", 0))
        a = timedelta(minutes=s.get("buffer_after", 0))
        out.append((aware(s["start"]) - b, aware(s["end"]) + a))
    for h in host_ids:
        try:
            out += await vendors.calendar_busy(await host_connection(ctx, h), start, end)
        except Exception:
            pass
    return out


async def find_slots(ctx, st, date_from, date_to):
    """Bookable starts between two dates (practice time zone), as UTC datetimes."""
    nowt = now()
    earliest = nowt + timedelta(hours=st.get("min_notice_hours", 4))
    latest = nowt + timedelta(days=st.get("max_days_ahead", 30))
    if st.get("date_from"):
        earliest = max(earliest, aware(st["date_from"]))
    if st.get("date_to"):
        latest = min(latest, aware(st["date_to"]) + timedelta(days=1))
    d0 = aware(date_from).astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    d1 = min(aware(date_to).astimezone(IST), latest.astimezone(IST))
    dur = timedelta(minutes=st["duration"])
    inc = timedelta(minutes=st.get("increment") or st["duration"])
    bb, ba = timedelta(minutes=st.get("buffer_before", 0)), timedelta(minutes=st.get("buffer_after", 0))
    busy = await busy_for(ctx, st["host_ids"], d0, d1 + timedelta(days=1))
    group = st.get("max_attendees", 1) > 1
    out = []
    day = d0
    while day <= d1:
        for w in st.get("availability", {}).get(str(day.weekday()), []):
            h1, m1 = _hm(w["start"])
            h2, m2 = _hm(w["end"])
            t = day.replace(hour=h1, minute=m1)
            wend = day.replace(hour=h2, minute=m2)
            while t + dur <= wend:
                tu = t.astimezone(aware(nowt).tzinfo)
                if earliest <= tu <= latest:
                    clash = False
                    if group:
                        g = await ctx.data.sessions.find_one({"type_id": st["_id"], "start": tu, "status": {"$in": ["booked", "held"]}})
                        clash = bool(g and g.get("attendee_count", 1) >= st["max_attendees"])
                        others = [b for b in busy if not (g and b == (aware(g["start"]) - bb, aware(g["end"]) + ba))]
                        clash = clash or any(s < tu + dur + ba and e > tu - bb for s, e in others if not g)
                    else:
                        clash = any(s < tu + dur + ba and e > tu - bb for s, e in busy)
                    if not clash:
                        out.append(tu)
                t += inc
        day += timedelta(days=1)
    return out


def gcal_link(title, start, end, details=""):
    f = lambda d: aware(d).strftime("%Y%m%dT%H%M%SZ")
    return (f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={quote(title)}&dates={f(start)}/{f(end)}"
            f"&details={quote(details)}")


async def get_type(ctx, tid):
    st = await ctx.data.session_types.get(tid)
    if not st:
        st = await ctx.data.session_types.find_one({"slug": tid})
    if not st:
        raise not_found("That session type")
    return st


async def lock_slot(ctx, st, start, session_id):
    """Unique lock per host and start time (1:1). Group sessions count seats."""
    if st.get("max_attendees", 1) > 1:
        gid = f"grp:{st['_id']}:{start.isoformat()}"
        try:
            await ctx.data.slot_locks.find_one_and_update({"_id": gid, "count": {"$lt": st["max_attendees"]}},
                                                          {"$inc": {"count": 1}, "$set": {"start": start}}, upsert=True)
        except DuplicateKeyError:
            raise AppError("slot_taken", "This session is full. Please pick another time.", 409)
        return [gid]
    keys = []
    try:
        for h in st["host_ids"]:
            k = f"{h}|{start.isoformat()}"
            await ctx.data.slot_locks.insert({"_id": k, "session_id": session_id, "start": start})
            keys.append(k)
    except DuplicateKeyError:
        for k in keys:
            await ctx.data.slot_locks.hard_delete({"_id": k})
        raise AppError("slot_taken", "Someone just took this time. Please pick another.", 409)
    return keys


async def unlock(ctx, s):
    for k in s.get("lock_keys", []):
        if k.startswith("grp:"):
            await ctx.data.slot_locks.update({"_id": k}, {}, raw={"$inc": {"count": -1}})
        else:
            await ctx.data.slot_locks.hard_delete({"_id": k})


async def book(ctx, st, start, contact, project_id=None, answers=None, hold=False, file_id=None, reserve_requires=None):
    start = aware(start)
    day_slots = await find_slots(ctx, st, start - timedelta(hours=start.astimezone(IST).hour + 1), start + timedelta(hours=1))
    if start not in day_slots:
        raise AppError("slot_unavailable", "That time is no longer available. Please pick another.", 409)
    if not project_id:
        from actions.crm import create_project
        pr = await create_project(ctx, {"name": f"{contact['name']} — {st['name']}", "contact_ids": [contact["_id"]],
                                        "type": "Discovery call" if st.get("key") == "discovery" else "", "source": contact.get("source") or "Booking",
                                        "owner_id": st["host_ids"][0] if st["host_ids"] else None})
        project_id = pr["_id"]
    sid = new_id()
    keys = await lock_slot(ctx, st, start, sid)
    end = start + timedelta(minutes=st["duration"])
    s = {"_id": sid, "type_id": st["_id"], "type_key": st.get("key"), "title": st["name"], "host_ids": st["host_ids"],
         "contact_id": contact["_id"], "project_id": project_id, "start": start, "end": end, "status": "held" if hold else "booked",
         "buffer_before": st.get("buffer_before", 0), "buffer_after": st.get("buffer_after", 0), "lock_keys": keys,
         "hold_expires_at": now() + timedelta(minutes=HOLD_MINUTES) if hold else None, "file_id": file_id,
         "reserve_requires": reserve_requires or [], "answers": answers or {}, "reminders_sent": [], "meet_link": None,
         "calendar_event_ids": {}, "notetaker": {"status": "off"}, "format": st.get("format", "video"), "price_paise": st.get("price_paise", 0),
         "attendee_count": 1}
    await ctx.data.sessions.insert(s)
    if hold:
        await log(ctx, project_id, "session", f"{st['name']} held for {fmt_dt(start)} until the client finishes", ref=sid)
        return s
    return await confirm_session(ctx, s, st)


async def confirm_session(ctx, s, st=None):
    st = st or await ctx.data.session_types.get(s["type_id"])
    contact = await ctx.data.contacts.get(s["contact_id"])
    host = s["host_ids"][0] if s["host_ids"] else None
    conn = await host_connection(ctx, host) if host else None
    link = None
    ev = {}
    if s["format"] == "video" and st.get("video", "meet") == "zoom":
        zconn = await ctx.data.connections.find_one({"provider": "zoom", "user_id": host})
        link = await vendors.zoom_create(ctx.ws_id, zconn, st["name"], s["start"], st["duration"])
    r = await vendors.calendar_create_event(ctx.ws_id, conn, f"{st['name']} — {contact['name']}", s["start"], s["end"],
                                            [contact.get("email")], want_meet=(s["format"] == "video" and st.get("video", "meet") == "meet"))
    ev[host or "none"] = r.get("event_id")
    if not link and s["format"] == "video":
        link = r.get("meet_link")
        if not link:
            await notify(ctx, "Connect Google Calendar in Settings so video calls get a Meet link automatically. "
                              f"For now, send the link for {st['name']} on {fmt_dt(s['start'])} yourself.", "calendar",
                         link=f"/projects/{s['project_id']}")
    ch = {"status": "booked", "hold_expires_at": None, "meet_link": link, "calendar_event_ids": ev}
    if st.get("notetaker") and link and s["format"] == "video":
        ch["notetaker"] = await schedule_notetaker(ctx, s, st, link)
    await ctx.data.sessions.update({"_id": s["_id"]}, ch)
    s.update(ch)
    from actions.inbox import send_message
    ws = await ctx.ws()
    when = fmt_dt(s["start"])
    add = gcal_link(f"{st['name']} with {ws['profile'].get('consultant_name') or ws['name']}", s["start"], s["end"], link or "")
    rec = " The call may be recorded by our notetaker so nothing gets missed." if ch.get("notetaker", {}).get("status") == "scheduled" else ""
    sys = ctx.child(actor="system")
    if contact.get("email"):
        await send_message(sys, s["project_id"], contact, "email", f"Booked: {st['name']} on {when}",
                           f"<p>Hi {contact.get('first_name') or contact['name']},</p><p>You're booked for <b>{st['name']}</b> on {when}.</p>"
                           f"<p>{('Join link: ' + link) if link else ''}</p><p>{rec}</p><p><a href='{add}'>Add to Google Calendar</a></p>",
                           kind="booking", idem_key=f"book:{s['_id']}")
    if contact.get("phone"):
        await send_message(sys, s["project_id"], contact, "whatsapp", wa_template="booking_confirmed",
                           wa_params=[contact.get("first_name") or contact["name"], ws["name"], when, link or "-"], kind="booking",
                           idem_key=f"book:{s['_id']}")
    await log(ctx, s["project_id"], "session", f"{st['name']} booked for {when}", ref=s["_id"], client_visible=True)
    await emit(ctx, "session.scheduled", {"session_id": s["_id"], "type_key": st.get("key"), "type_id": st["_id"]}, s["project_id"])
    conflict = await ctx.data.projects.find_one({"_id": {"$ne": s["project_id"]}, "start_date": s["start"].date().isoformat()})
    if conflict:
        await notify(ctx, f"Heads up: {st['name']} on {when} overlaps the project date of \"{conflict['name']}\".", "calendar")
    return s


async def schedule_notetaker(ctx, s, st, link):
    hours = max(1, math.ceil(st["duration"] / 60))
    try:
        await limits.consume(ctx, "meetbot_hours_per_month", hours)
    except AppError:
        return {"status": "limit", "note": "Meeting-bot hours for this month are used up."}
    ws = await ctx.ws()
    try:
        r = await vendors.meetbot_join(ctx.ws_id, link, ws["settings"].get("notetaker_name") or "Notetaker", s["start"])
    except AppError:
        r = {"status": "refused"}
    if r["status"] != "scheduled":
        await limits.refund(ctx, "meetbot_hours_per_month", hours)
        await notify(ctx, f"The notetaker couldn't join {st['name']} on {fmt_dt(s['start'])}. You can upload a recording afterwards.",
                     "notetaker", link=f"/projects/{s['project_id']}")
        return {"status": "refused"}
    return {"status": "scheduled", "bot_id": r["bot_id"], "hours": hours}


async def confirm_held_for_file(ctx, file_id, what):
    """A client signed or paid: confirm any session held for that file once all its requirements are done."""
    for s in await ctx.data.sessions.find({"file_id": file_id, "status": "held"}):
        req = set(s.get("reserve_requires") or [])
        done = set(s.get("reserve_done") or []) | {what}
        await ctx.data.sessions.update({"_id": s["_id"]}, {"reserve_done": list(done)})
        if req <= done:
            await confirm_session(ctx, dict(s, reserve_done=list(done)))


async def extend_hold_after_claim(ctx, file_id):
    for s in await ctx.data.sessions.find({"file_id": file_id, "status": "held"}):
        st = await ctx.data.session_types.get(s["type_id"])
        hrs = (st or {}).get("hold_hours", 24)
        await ctx.data.sessions.update({"_id": s["_id"]}, {"hold_expires_at": now() + timedelta(hours=hrs)})
        await notify(ctx, f"A client says they've paid to reserve {fmt_dt(s['start'])}. Please confirm the payment within {hrs} hours.",
                     "payment", link=f"/projects/{s['project_id']}?tab=payments")


async def cancel_session(ctx, s, by="consultant", tell_client=True):
    await ctx.data.sessions.update({"_id": s["_id"]}, {"status": "cancelled", "cancelled_by": by, "cancelled_at": now()})
    await unlock(ctx, s)
    host = s["host_ids"][0] if s.get("host_ids") else None
    for _, ev in (s.get("calendar_event_ids") or {}).items():
        try:
            await vendors.calendar_delete_event(await host_connection(ctx, host), ev)
        except Exception:
            pass
    if s["status"] == "booked":
        await log(ctx, s["project_id"], "session", f"{s['title']} on {fmt_dt(s['start'])} cancelled by {by}", ref=s["_id"], client_visible=True)
        await emit(ctx, "session.cancelled", {"session_id": s["_id"], "by": by}, s["project_id"])
        if tell_client:
            from actions.inbox import send_message
            c = await ctx.data.contacts.get(s["contact_id"])
            if c and c.get("email"):
                await send_message(ctx.child(actor="system"), s["project_id"], c, "email", f"Cancelled: {s['title']}",
                                   f"<p>Your session on {fmt_dt(s['start'])} has been cancelled.</p>", kind="booking_cancelled",
                                   idem_key=f"cancel:{s['_id']}")


# ---------------- actions ----------------

class TypeIn(P):
    id: Optional[str] = None
    name: str
    format: str = "video"            # video | phone | in_person
    video: str = "meet"              # meet | zoom
    duration: int = 30
    buffer_before: int = 0
    buffer_after: int = 0
    increment: int = 30
    availability: dict = {}
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    min_notice_hours: int = 4
    max_days_ahead: int = 30
    cancel_cutoff_hours: int = 12
    max_attendees: int = 1
    host_ids: list = []
    color: str = "#C9A84C"
    questions: list = []
    price_paise: int = 0
    notetaker: bool = False
    hold_hours: int = 24
    reminders: list = [1440, 60]
    active: bool = True


@action("session_types.save", "internal", TypeIn, roles=ADMINS | {"manager"}, desc="Create or update a session type.")
async def types_save(ctx, p: TypeIn):
    if not 5 <= p.duration <= 600:
        raise AppError("invalid", "Duration must be between 5 minutes and 10 hours.", 400)
    if p.max_attendees < 1:
        raise AppError("invalid", "A session needs room for at least one person.", 400)
    for d, wins in p.availability.items():
        for w in wins:
            try:
                a, b = _hm(w["start"]), _hm(w["end"])
            except Exception:
                raise AppError("invalid", "Availability times should look like 09:30.", 400)
            if a >= b:
                raise AppError("invalid", "Each availability window must end after it starts.", 400)
    doc = p.model_dump(exclude={"id"})
    doc["host_ids"] = doc["host_ids"] or [ctx.user_id or (await ctx.ws())["owner_id"]]
    if p.id:
        await ctx.data.session_types.update({"_id": p.id}, doc)
        return clean(await ctx.data.session_types.get(p.id))
    await limits.check_count(ctx, "session_types", await ctx.data.session_types.count({"active": True}))
    from actions.workspace import slugify
    doc["slug"] = slugify(p.name) + "-" + new_id()[:4]
    return clean(await ctx.data.session_types.insert(doc))


@action("session_types.list", "read", desc="Session types clients can book.")
async def types_list(ctx, p):
    from actions.merge import client_base
    ws = await ctx.ws()
    return [dict(clean(t), link=f"{client_base(ws)}/book/{t.get('slug', t['_id'])}") for t in await ctx.data.session_types.find({}, sort=[("name", 1)])]


class SlotsIn(P):
    session_type_id: str
    date_from: str
    date_to: Optional[str] = None


@action("availability.find_slots", "read", SlotsIn, desc="Open times for a session type between two dates.")
async def find_slots_action(ctx, p: SlotsIn):
    st = await get_type(ctx, p.session_type_id)
    df = aware(p.date_from)
    dt = aware(p.date_to) if p.date_to else df + timedelta(days=7)
    slots = await find_slots(ctx, st, df, dt)
    return [{"start": s.isoformat(), "label": fmt_dt(s)} for s in slots[:200]]


class BookIn(P):
    session_type_id: str
    start: str
    contact_id: Optional[str] = None
    project_id: Optional[str] = None


@action("sessions.book", "external", BookIn, roles=STAFF, desc="Book a session for a client (sends the confirmation).")
async def sessions_book(ctx, p: BookIn):
    st = await get_type(ctx, p.session_type_id)
    contact = None
    if p.project_id:
        pr = await perm.project(ctx, p.project_id, act=True)
        contact = await ctx.data.contacts.get(p.contact_id or (pr.get("contact_ids") or [None])[0])
    elif p.contact_id:
        contact = await ctx.data.contacts.get(p.contact_id)
    if not contact:
        raise AppError("no_contact", "Choose who the session is with.", 400)
    s = await book(ctx, st, p.start, contact, p.project_id)
    return clean(s)


class SessIn(P):
    id: str


@action("sessions.cancel", "external", SessIn, desc="Cancel a session and tell the client.")
async def sessions_cancel(ctx, p: SessIn):
    s = await ctx.data.sessions.get(p.id)
    if not s or s["status"] not in ("booked", "held"):
        raise not_found("That session")
    await perm.project(ctx, s["project_id"], act=True)
    await cancel_session(ctx, s)
    return {"ok": True}


class ReschedIn(P):
    id: str
    start: str


@action("sessions.reschedule", "external", ReschedIn, desc="Move a session to a new time.")
async def sessions_reschedule(ctx, p: ReschedIn):
    s = await ctx.data.sessions.get(p.id)
    if not s or s["status"] != "booked":
        raise not_found("That session")
    await perm.project(ctx, s["project_id"], act=True)
    st = await ctx.data.session_types.get(s["type_id"])
    c = await ctx.data.contacts.get(s["contact_id"])
    new = await book(ctx, st, p.start, c, s["project_id"], s.get("answers"))
    await cancel_session(ctx, s, tell_client=False)
    return clean(new)


class MarkIn(P):
    id: str
    status: str   # completed | no_show


@action("sessions.mark", "internal", MarkIn, desc="Mark a session completed or a no-show.")
async def sessions_mark(ctx, p: MarkIn):
    s = await ctx.data.sessions.get(p.id)
    if not s or p.status not in ("completed", "no_show"):
        raise not_found("That session")
    await perm.project(ctx, s["project_id"], act=True)
    await ctx.data.sessions.update({"_id": s["_id"]}, {"status": p.status})
    await log(ctx, s["project_id"], "session", f"Session marked {'a no-show' if p.status == 'no_show' else 'completed'}", ref=s["_id"])
    return {"ok": True}


class RangeIn(P):
    date_from: str
    date_to: str
    show: list = ["sessions", "projects", "payments", "tasks"]


@action("calendar.list", "read", RangeIn, desc="Calendar items between two dates: sessions, project dates, payment dues, tasks.")
async def calendar_list(ctx, p: RangeIn):
    a, b = aware(p.date_from), aware(p.date_to)
    vis = await ctx.data.projects.find(perm.visible_filter(ctx), projection={"name": 1, "start_date": 1, "end_date": 1})
    names = {x["_id"]: x["name"] for x in vis}
    items = []
    if "sessions" in p.show:
        for s in await ctx.data.sessions.find({"project_id": {"$in": list(names)}, "start": {"$gte": a, "$lt": b},
                                               "status": {"$in": ["booked", "held", "completed", "no_show"]}}):
            items.append({"kind": "session", "id": s["_id"], "title": s["title"], "project": names.get(s["project_id"]),
                          "project_id": s["project_id"], "start": aware(s["start"]).isoformat(), "end": aware(s["end"]).isoformat(),
                          "status": s["status"], "meet_link": s.get("meet_link")})
    if "projects" in p.show:
        for x in vis:
            for k in ("start_date", "end_date"):
                if x.get(k) and a.date().isoformat() <= str(x[k])[:10] < b.date().isoformat():
                    items.append({"kind": "project_date", "id": x["_id"], "title": f"{x['name']} {'starts' if k == 'start_date' else 'ends'}",
                                  "project_id": x["_id"], "start": str(x[k])[:10]})
    if "payments" in p.show:
        for inv in await ctx.data.invoices.find({"project_id": {"$in": list(names)}, "status": {"$in": ["sent", "partially_paid"]}}):
            for s in inv["schedule"]:
                if s.get("due_date") and a <= aware(s["due_date"]) < b and s["status"] != "paid":
                    items.append({"kind": "payment_due", "id": inv["_id"], "title": f"Payment due: {s['label']}",
                                  "project_id": inv["project_id"], "start": aware(s["due_date"]).isoformat(),
                                  "amount_paise": None if ctx.hide_money else s["amount_paise"]})
    if "tasks" in p.show:
        tf = {"done": False, "due_at": {"$gte": a, "$lt": b}}
        if ctx.role in ("member", "collaborator"):
            tf["assignee_id"] = ctx.user_id
        for t in await ctx.data.tasks.find(tf):
            items.append({"kind": "task", "id": t["_id"], "title": t["title"], "project_id": t.get("project_id"),
                          "start": aware(t["due_at"]).isoformat()})
    return sorted(items, key=lambda i: i["start"])


@action("session_types.overview", "read", desc="All session types' availability on one weekly grid.")
async def types_overview(ctx, p):
    out = []
    for t in await ctx.data.session_types.find({"active": True}):
        out.append({"id": t["_id"], "name": t["name"], "color": t.get("color"), "availability": t.get("availability", {})})
    return out


_ = datetime
