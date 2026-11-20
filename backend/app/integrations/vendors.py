"""Every outside service, behind one switch each: live | fake | off.

Fake mode records what would have been sent in `vendor_log`, so QA screens show
real-looking results and tests can check them. Live adapters are written to
each provider's public HTTP API but have NOT been tested against live keys yet
(see docs/HANDOVER.md, before-launch list).
"""
import base64
import hashlib
import json
import logging
import random
from datetime import timedelta
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httpx

from app.core import settings
from app.db import get_db
from app.core.util import AppError, aware, new_id, now

mode = settings.vendor_mode
log = logging.getLogger("app.vendors")


async def _log(kind, ws_id=None, **payload):
    doc = {"_id": new_id(), "kind": kind, "workspace_id": ws_id, "payload": payload, "at": now()}
    await get_db().vendor_log.insert_one(doc)
    return doc


def _off(name):
    raise AppError("vendor_off", f"{name} is switched off right now. Please try again later.", 503)


# ---------------- token encryption for connected accounts ----------------

from app.core.security import decrypt, encrypt  # noqa: E402,F401  (re-exported)


# ---------------- WhatsApp / SMS / OTP ----------------

async def whatsapp_send(ws_id, to, template=None, params=None, text=None):
    m = mode("whatsapp")
    if m == "off":
        _off("WhatsApp")
    if m == "fake":
        d = await _log("whatsapp", ws_id, to=to, template=template, params=params or [], text=text)
        return {"status": "sent", "provider_id": d["_id"]}
    async with httpx.AsyncClient(timeout=15) as c:
        if text is not None:
            # Free-form session message (inside the 24-hour window).
            r = await c.post("https://backend.aisensy.com/direct-apis/t1/messages",
                             headers={"Authorization": f"Bearer {settings.AISENSY_API_KEY}"},
                             json={"to": to, "type": "text", "recipient_type": "individual",
                                   "text": {"body": text}})
        else:
            r = await c.post("https://backend.aisensy.com/campaign/t1/api/v2",
                             json={"apiKey": settings.AISENSY_API_KEY, "campaignName": settings.aisensy_campaign(template),
                                   "destination": to, "userName": "client", "templateParams": params or []})
    if r.status_code >= 300:
        # The provider's reason, for the logs (never the key): wrong campaign name, unapproved template, bad number...
        log.warning("whatsapp send failed", extra={"fields": {
            "status": r.status_code, "campaign": settings.aisensy_campaign(template) if text is None else "(free text)",
            "to_suffix": str(to)[-4:], "reply": r.text[:300]}})
        raise AppError("vendor_failed", "The WhatsApp message could not be sent. Please try again.", 502)
    return {"status": "sent", "provider_id": r.json().get("id") if r.content else None}


async def sms_send(to, text):
    m = mode("sms")
    if m == "off":
        _off("SMS")
    if m == "fake":
        await _log("sms", None, to=to, text=text)
        return {"status": "sent"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://control.msg91.com/api/v5/flow/",
                         headers={"authkey": settings.MSG91_AUTH_KEY},
                         json={"template_id": settings.MSG91_TEMPLATE_ID, "recipients": [{"mobiles": to, "text": text}]})
    return {"status": "sent" if r.status_code < 300 else "failed"}


async def otp_send(phone, code):
    """WhatsApp first, SMS as fallback."""
    try:
        await whatsapp_send(None, phone, template="otp_login", params=[code])
        return "whatsapp"
    except AppError:
        # Fall back to SMS only when SMS really sends. Falling back to a fake SMS would
        # tell the person "sent by SMS" while nothing arrives.
        if mode("sms") != "live" and not settings.QA_MODE:
            raise
        await sms_send(phone, f"Your login code is {code}. It expires in 10 minutes.")
        return "sms"


# ---------------- Email ----------------

def reply_address(thread_id):
    return f"t-{thread_id}@{settings.INBOUND_DOMAIN}"


async def email_send(ws_id, to, subject, html, reply_to=None, from_name=None, connection=None):
    """Send through the consultant's connected Gmail/Outlook when there is one,
    otherwise through our transactional provider with a reply-to address that
    routes replies back to the project thread."""
    if connection:
        prov = connection["provider"]
        if mode(prov) == "fake":
            d = await _log("email", ws_id, via=prov, to=to, subject=subject, html=html, reply_to=reply_to)
            return {"status": "sent", "provider_id": d["_id"], "via": prov}
        tok = await access_token(connection)
        if prov == "gmail":
            msg = MIMEText(html, "html")
            msg["To"], msg["Subject"] = to, subject
            if reply_to:
                msg["Reply-To"] = reply_to
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                 headers={"Authorization": f"Bearer {tok}"}, json={"raw": raw})
            ok = r.status_code < 300
            return {"status": "sent" if ok else "failed", "provider_id": r.json().get("id") if ok else None, "via": prov}
        if prov == "outlook":
            body = {"message": {"subject": subject, "body": {"contentType": "HTML", "content": html},
                                "toRecipients": [{"emailAddress": {"address": to}}],
                                "replyTo": [{"emailAddress": {"address": reply_to}}] if reply_to else []}}
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post("https://graph.microsoft.com/v1.0/me/sendMail",
                                 headers={"Authorization": f"Bearer {tok}"}, json=body)
            return {"status": "sent" if r.status_code < 300 else "failed", "via": prov}
    m = mode("email")
    if m == "off":
        _off("Email")
    if m == "fake":
        d = await _log("email", ws_id, via="provider", to=to, subject=subject, html=html, reply_to=reply_to)
        return {"status": "sent", "provider_id": d["_id"], "via": "provider"}
    # Postmark-compatible JSON API (set EMAIL_API_URL to the provider's endpoint).
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(settings.EMAIL_API_URL, headers={"X-Postmark-Server-Token": settings.EMAIL_API_KEY,
                                                           "Accept": "application/json"},
                         json={"From": f"{from_name or settings.BRAND_NAME} <{settings.EMAIL_FROM}>", "To": to,
                               "Subject": subject, "HtmlBody": html, "ReplyTo": reply_to, "TrackOpens": True})
    ok = r.status_code < 300
    return {"status": "sent" if ok else "failed", "provider_id": (r.json().get("MessageID") if ok else None), "via": "provider"}


async def dns_check(domain):
    """SPF and DKIM check for custom sending domains."""
    if mode("dns") == "fake":
        return {"spf": not domain.startswith("nospf"), "dkim": not domain.startswith("nospf")}
    import dns.resolver
    spf = dkim = False
    try:
        for r in dns.resolver.resolve(domain, "TXT"):
            if "v=spf1" in r.to_text():
                spf = True
    except Exception:
        pass
    for sel in ("default", "google", "selector1", "pm"):
        try:
            dns.resolver.resolve(f"{sel}._domainkey.{domain}", "TXT")
            dkim = True
            break
        except Exception:
            continue
    return {"spf": spf, "dkim": dkim}


# ---------------- OAuth for Google / Microsoft / Zoom ----------------

OAUTH = {
    "gmail": dict(auth="https://accounts.google.com/o/oauth2/v2/auth", token="https://oauth2.googleapis.com/token",
                  scope="https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly "
                        "https://www.googleapis.com/auth/calendar email", cid="GOOGLE_CLIENT_ID", sec="GOOGLE_CLIENT_SECRET"),
    "outlook": dict(auth="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                    token="https://login.microsoftonline.com/common/oauth2/v2.0/token",
                    scope="offline_access Mail.Send Mail.Read Calendars.ReadWrite User.Read",
                    cid="MS_CLIENT_ID", sec="MS_CLIENT_SECRET"),
    "zoom": dict(auth="https://zoom.us/oauth/authorize", token="https://zoom.us/oauth/token", scope="meeting:write",
                 cid="ZOOM_CLIENT_ID", sec="ZOOM_CLIENT_SECRET"),
}


def oauth_url(provider, state, redirect_uri):
    o = OAUTH[provider]
    q = {"client_id": getattr(settings, o["cid"]), "response_type": "code", "redirect_uri": redirect_uri,
         "scope": o["scope"], "state": state, "access_type": "offline", "prompt": "consent"}
    return o["auth"] + "?" + urlencode(q)


async def oauth_exchange(provider, code, redirect_uri):
    if mode(provider) == "fake":
        return {"access_token": "fake", "refresh_token": "fake", "expires_at": (now() + timedelta(hours=1)).isoformat(),
                "account": f"demo@{provider}.example"}
    o = OAUTH[provider]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(o["token"], data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                                           "client_id": getattr(settings, o["cid"]),
                                           "client_secret": getattr(settings, o["sec"])})
    if r.status_code >= 300:
        raise AppError("oauth_failed", "We couldn't connect that account. Please try again.", 400)
    j = r.json()
    return {"access_token": j["access_token"], "refresh_token": j.get("refresh_token"),
            "expires_at": (now() + timedelta(seconds=int(j.get("expires_in", 3600)) - 60)).isoformat(),
            "account": j.get("email") or ""}


async def access_token(conn):
    tok = decrypt(conn["tokens"])
    if aware(tok["expires_at"]) > now():
        return tok["access_token"]
    o = OAUTH[conn["provider"]]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(o["token"], data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                           "client_id": getattr(settings, o["cid"]),
                                           "client_secret": getattr(settings, o["sec"])})
    j = r.json()
    tok["access_token"] = j["access_token"]
    tok["expires_at"] = (now() + timedelta(seconds=int(j.get("expires_in", 3600)) - 60)).isoformat()
    await get_db().connections.update_one({"_id": conn["_id"]}, {"$set": {"tokens": encrypt(tok)}})
    return tok["access_token"]


# ---------------- Calendar and video ----------------

async def calendar_busy(conn, start, end):
    """Busy blocks from the consultant's calendar: list of (start, end)."""
    if conn is None:
        return []
    prov = conn["provider"]
    cal_mode = mode("gcal" if prov == "gmail" else "outlook_cal")
    if cal_mode == "fake":
        # One repeatable busy block each weekday 13:00–14:00 IST (lunch).
        out, d = [], aware(start).replace(hour=7, minute=30, second=0, microsecond=0)
        while d < aware(end):
            if d.weekday() < 5:
                out.append((d, d + timedelta(hours=1)))
            d += timedelta(days=1)
        return out
    tok = await access_token(conn)
    async with httpx.AsyncClient(timeout=20) as c:
        if prov == "gmail":
            r = await c.post("https://www.googleapis.com/calendar/v3/freeBusy", headers={"Authorization": f"Bearer {tok}"},
                             json={"timeMin": aware(start).isoformat(), "timeMax": aware(end).isoformat(),
                                   "items": [{"id": "primary"}]})
            busy = r.json().get("calendars", {}).get("primary", {}).get("busy", [])
            return [(aware(b["start"]), aware(b["end"])) for b in busy]
        r = await c.post("https://graph.microsoft.com/v1.0/me/calendar/getSchedule", headers={"Authorization": f"Bearer {tok}"},
                         json={"schedules": [conn.get("account", "")], "startTime": {"dateTime": aware(start).isoformat(), "timeZone": "UTC"},
                               "endTime": {"dateTime": aware(end).isoformat(), "timeZone": "UTC"}})
        items = (r.json().get("value") or [{}])[0].get("scheduleItems", [])
        return [(aware(i["start"]["dateTime"]), aware(i["end"]["dateTime"])) for i in items]


async def calendar_create_event(ws_id, conn, title, start, end, attendees, want_meet=False):
    if conn is None:
        return {"event_id": None, "meet_link": None}
    prov = conn["provider"]
    if mode("gcal" if prov == "gmail" else "outlook_cal") == "fake":
        d = await _log("calendar_event", ws_id, provider=prov, title=title, start=aware(start).isoformat(), attendees=attendees)
        link = f"https://meet.google.com/{d['_id'][:3]}-{d['_id'][3:7]}-{d['_id'][7:10]}" if want_meet else None
        return {"event_id": d["_id"], "meet_link": link}
    tok = await access_token(conn)
    async with httpx.AsyncClient(timeout=20) as c:
        if prov == "gmail":
            body = {"summary": title, "start": {"dateTime": aware(start).isoformat()}, "end": {"dateTime": aware(end).isoformat()},
                    "attendees": [{"email": a} for a in attendees if a]}
            if want_meet:
                body["conferenceData"] = {"createRequest": {"requestId": new_id()}}
            r = await c.post("https://www.googleapis.com/calendar/v3/calendars/primary/events?conferenceDataVersion=1",
                             headers={"Authorization": f"Bearer {tok}"}, json=body)
            j = r.json()
            return {"event_id": j.get("id"), "meet_link": j.get("hangoutLink")}
        body = {"subject": title, "start": {"dateTime": aware(start).isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": aware(end).isoformat(), "timeZone": "UTC"},
                "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees if a]}
        r = await c.post("https://graph.microsoft.com/v1.0/me/events", headers={"Authorization": f"Bearer {tok}"}, json=body)
        return {"event_id": r.json().get("id"), "meet_link": None}


async def calendar_delete_event(conn, event_id):
    if not conn or not event_id or mode("gcal" if conn["provider"] == "gmail" else "outlook_cal") == "fake":
        return
    tok = await access_token(conn)
    async with httpx.AsyncClient(timeout=20) as c:
        if conn["provider"] == "gmail":
            await c.delete(f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
                           headers={"Authorization": f"Bearer {tok}"})
        else:
            await c.delete(f"https://graph.microsoft.com/v1.0/me/events/{event_id}", headers={"Authorization": f"Bearer {tok}"})


async def zoom_create(ws_id, conn, title, start, minutes):
    if mode("zoom") == "fake" or conn is None:
        d = await _log("zoom_meeting", ws_id, title=title, start=aware(start).isoformat())
        return f"https://zoom.us/j/{random.Random(d['_id']).randint(10**9, 10**10 - 1)}"
    tok = await access_token(conn)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.zoom.us/v2/users/me/meetings", headers={"Authorization": f"Bearer {tok}"},
                         json={"topic": title, "type": 2, "start_time": aware(start).isoformat(), "duration": minutes})
    return r.json().get("join_url")


# ---------------- Meeting bot (notetaker) ----------------

async def meetbot_join(ws_id, meeting_url, bot_name, join_at):
    m = mode("meetbot")
    if m == "off":
        _off("The notetaker")
    if m == "fake":
        if "refuse" in (meeting_url or ""):
            return {"status": "refused", "bot_id": None}
        d = await _log("meetbot", ws_id, url=meeting_url, bot_name=bot_name, join_at=aware(join_at).isoformat())
        return {"status": "scheduled", "bot_id": d["_id"]}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{settings.MEETBOT_API_URL}/bot", headers={"Authorization": f"Token {settings.MEETBOT_API_KEY}"},
                         json={"meeting_url": meeting_url, "bot_name": bot_name, "join_at": aware(join_at).isoformat()})
    if r.status_code >= 300:
        return {"status": "refused", "bot_id": None}
    return {"status": "scheduled", "bot_id": r.json().get("id")}


FAKE_TRANSCRIPT = """Consultant: Thanks for making time. Tell me where the business is today.
Client: We do about 40 lakh a year, mostly from referrals. Sales are lumpy and I'm doing everything myself.
Consultant: What would a good year look like?
Client: One crore, with a small team that can sell without me in every meeting.
Consultant: Then the first 90 days are about a repeatable sales process and one hire.
Client: That makes sense. What would working together look like?
Consultant: A 3-month advisory retainer. Weekly calls, a sales playbook, and help hiring your first salesperson.
Client: Send me the proposal. Budget is around 1.5 lakh for the quarter.
Consultant: I'll send it today. Next step is the proposal, then a kickoff call next week.
Consultant: Could you share last year's P&L and your monthly sales numbers by Friday?"""


async def meetbot_transcript(bot_id):
    if mode("meetbot") == "fake":
        return FAKE_TRANSCRIPT
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{settings.MEETBOT_API_URL}/bot/{bot_id}/transcript",
                        headers={"Authorization": f"Token {settings.MEETBOT_API_KEY}"})
    return r.text if r.status_code < 300 else ""


# ---------------- Inbox lead finder (read connected inbox) ----------------

async def inbox_new_messages(conn, since):
    if conn is None:
        return []
    if mode(conn["provider"]) == "fake":
        return []  # QA seeds suggested leads directly; nothing new arrives by itself
    tok = await access_token(conn)
    async with httpx.AsyncClient(timeout=20) as c:
        if conn["provider"] == "gmail":
            q = f"in:inbox after:{int(aware(since).timestamp())}"
            r = await c.get("https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"q": q, "maxResults": 20},
                            headers={"Authorization": f"Bearer {tok}"})
            out = []
            for m in r.json().get("messages", []):
                mr = await c.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}",
                                 params={"format": "metadata"}, headers={"Authorization": f"Bearer {tok}"})
                j = mr.json()
                h = {x["name"].lower(): x["value"] for x in j.get("payload", {}).get("headers", [])}
                out.append({"id": m["id"], "from": h.get("from", ""), "subject": h.get("subject", ""), "snippet": j.get("snippet", "")})
            return out
        r = await c.get("https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
                        params={"$filter": f"receivedDateTime ge {aware(since).isoformat()}", "$top": 20},
                        headers={"Authorization": f"Bearer {tok}"})
        return [{"id": m["id"], "from": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                 "subject": m.get("subject", ""), "snippet": m.get("bodyPreview", "")} for m in r.json().get("value", [])]


# ---------------- Lead enrichment ----------------

async def enrich(email, name):
    if mode("enrich") != "live":
        dom = (email or "").split("@")[-1] if email and "@" in email else ""
        if not dom or dom in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
            return {}
        company = dom.split(".")[0].replace("-", " ").title()
        return {"company": company, "website": f"https://{dom}", "linkedin": f"https://www.linkedin.com/company/{dom.split('.')[0]}"}
    return {}  # plug a live enrichment provider in here


# ---------------- File storage ----------------
# The storage backend (local disk or an S3-compatible bucket) is in storage.py.
# These wrappers add the per-workspace quota on top.

async def storage_put(ws_id, name, data: bytes, content_type="application/octet-stream", count=True):
    """count=False for files we make for the consultant (export ZIPs): they don't use their storage."""
    from app.integrations import storage
    if ws_id and count:
        from app.core import limits
        db = get_db()
        ws = await db.workspaces.find_one({"_id": ws_id}, {"created_at": 1}) or {}
        cap_mb = await limits.value(ws_id, "storage_mb", ws.get("created_at"))
        # Reserve the space atomically, so parallel uploads can't overshoot the cap.
        flt = {"_id": ws_id}
        if cap_mb is not None:
            cap = cap_mb * 1024 * 1024 - len(data)
            if cap < 0:
                cap = -1  # bigger than the whole allowance: nothing can match
            flt["$or"] = [{"storage_bytes": {"$exists": False}}, {"storage_bytes": {"$lte": cap}}]
        res = await db.workspaces.update_one(flt, {"$inc": {"storage_bytes": len(data)}})
        if cap_mb is not None and not res.modified_count:
            raise AppError("limit", f"Your file storage is full ({cap_mb // 1024 if cap_mb >= 1024 else cap_mb} "
                                    f"{'GB' if cap_mb >= 1024 else 'MB'}). Remove old files or ask us for more space.", 402,
                           {"key": "storage_mb"})
    key = f"{ws_id}/{new_id()}-{storage.safe_name(name)}"
    try:
        await storage.backend().put(key, data, content_type)
    except Exception:
        if ws_id and count:
            await get_db().workspaces.update_one({"_id": ws_id}, {"$inc": {"storage_bytes": -len(data)}})
        raise
    return key


async def storage_get(key) -> bytes:
    """Read a stored file from whichever backend is configured."""
    from app.integrations import storage
    return await storage.backend().get(key)


async def storage_delete(ws_id, key, size: int = 0):
    """Delete a stored file and give its space back to the workspace."""
    from app.integrations import storage
    await storage.backend().delete(key)
    if ws_id and size:
        await get_db().workspaces.update_one({"_id": ws_id}, {"$inc": {"storage_bytes": -int(size)}})
