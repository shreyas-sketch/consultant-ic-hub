"""Merge fields: {{client.first_name}}, {{project.name}}, {{practice.name}} ...

One function fills them everywhere (emails, client files, contracts, WhatsApp).
Unknown fields are left visible as [field name] so nothing silently disappears.
"""
import html as _html
import re

from app.core import settings
from app.db import get_db
from app.core.util import aware, fmt_date, fmt_dt, inr, now

FIELD_RX = re.compile(r"\{\{\s*([a-zA-Z0-9_.:\-]+)\s*\}\}")

FIELD_LIST = [
    ("client.name", "Client full name"), ("client.first_name", "Client first name"), ("client.company", "Client company"),
    ("client.email", "Client email"), ("client.phone", "Client phone"), ("project.name", "Project name"),
    ("project.value", "Project value"), ("project.start_date", "Project start date"), ("project.end_date", "Project end date"),
    ("project.type", "Project type"), ("practice.name", "Practice name"), ("consultant.name", "Consultant name"),
    ("today", "Today's date"), ("services.recap", "Services the client chose"), ("payments.recap", "Payment schedule"),
    ("session.date", "Session date"), ("session.time", "Session time"), ("session.link", "Session link"),
    ("file.link", "Client file link"), ("booking.link", "Booking page link"), ("portal.link", "Client portal link"),
    ("invoice.amount_due", "Amount due now"), ("invoice.due_date", "Next due date"), ("invoice.link", "Invoice link"),
]


def client_base(ws) -> str:
    """Base URL for client-facing pages: custom domain, else <slug>.<CLIENT_DOMAIN>, else /c/<slug>."""
    if ws.get("domains"):
        return f"https://{ws['domains'][0]}"
    if settings.CLIENT_DOMAIN:
        return f"https://{ws['slug']}.{settings.CLIENT_DOMAIN}"
    return f"{settings.APP_URL}/c/{ws['slug']}"


async def build(ctx, project=None, contact=None, extra=None) -> dict:
    ws = await ctx.ws()
    owner = await get_db().users.find_one({"_id": ws["owner_id"]}) or {}
    if contact is None and project and project.get("contact_ids"):
        contact = await ctx.data.contacts.get(project["contact_ids"][0])
    contact = contact or {}
    base = client_base(ws)
    v = {
        "client.name": contact.get("name", ""), "client.first_name": contact.get("first_name") or (contact.get("name") or "there").split(" ")[0],
        "client.company": contact.get("company", ""), "client.email": contact.get("email", ""), "client.phone": contact.get("phone", ""),
        "client.company_suffix": f" of {contact['company']}" if contact.get("company") else "",
        "practice.name": ws.get("profile", {}).get("practice_name") or ws["name"],
        "consultant.name": ws.get("profile", {}).get("consultant_name") or owner.get("name") or ws["name"],
        "today": fmt_date(now()),
    }
    if project:
        v.update({"project.name": project.get("name", ""), "project.value": inr(project.get("value_paise", 0)),
                  "project.type": project.get("type", ""),
                  "project.start_date": fmt_date(project["start_date"]) if project.get("start_date") else "",
                  "project.end_date": fmt_date(project["end_date"]) if project.get("end_date") else ""})
        if project.get("contact_ids"):
            v["portal.link"] = f"{base}/portal"
    st = await ctx.data.session_types.find_one({"key": "discovery"}) or await ctx.data.session_types.find_one({})
    if st:
        v["booking.link"] = f"{base}/book/{st.get('slug', st['_id'])}"
    lf = ws.get("invoice", {}).get("late_fee", {})
    v["late_fee.pct"] = f"{lf.get('pct_bp', 0) / 100:g}%"
    v.update(extra or {})
    return v


def fill(text: str, values: dict, html_mode=True, fields=None) -> str:
    """Replace merge fields. `fields` are contract fields ({{field:key}})."""
    if not text:
        return ""
    fields = {f["key"]: f for f in (fields or [])}

    def rep(m):
        k = m.group(1)
        if k.startswith("field:"):
            f = fields.get(k[6:])
            val = (f or {}).get("value") or ""
            if not val:
                return f"[{(f or {}).get('label', k[6:])}]"
            return _html.escape(val) if html_mode else val
        if k in values:
            val = values[k]
            return str(val) if (k.endswith(".recap") or k == "late_fee_clause") else (_html.escape(str(val)) if html_mode else str(val))
        return f"[{k}]"
    return FIELD_RX.sub(rep, text)


def session_values(session) -> dict:
    if not session:
        return {}
    s = aware(session["start"])
    return {"session.date": fmt_date(s), "session.time": fmt_dt(s).split(", ")[-1], "session.link": session.get("meet_link") or ""}
