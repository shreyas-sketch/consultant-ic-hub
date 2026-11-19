"""Lead forms: public pages (and embed code) that turn strangers into projects."""
from datetime import timedelta
from typing import Optional

from actions.registry import ADMINS, P, action
from core import limits
from core.util import AppError, clean, new_id, not_found, now

CONTACT_BLOCK = {"id": "contact", "type": "contact", "locked": True,
                 "fields": [{"key": "name", "label": "Your name", "required": True},
                            {"key": "phone", "label": "Mobile number", "required": True},
                            {"key": "email", "label": "Email", "required": False}]}

KINDS = ["enquiry", "discovery_call", "paid_consultation", "instant_booking", "speaking_request", "partnership"]


def starter_form(kind):
    q = {"enquiry": [{"id": "q_help", "label": "What would you like help with?", "kind": "long", "required": True}],
         "discovery_call": [{"id": "q_help", "label": "What should we talk about?", "kind": "long", "required": False}],
         "paid_consultation": [{"id": "q_help", "label": "What do you want to solve in this session?", "kind": "long", "required": True}],
         "instant_booking": [],
         "speaking_request": [{"id": "q_event", "label": "Event name and date", "kind": "short", "required": True},
                              {"id": "q_aud", "label": "Audience size", "kind": "number", "required": False}],
         "partnership": [{"id": "q_idea", "label": "What partnership do you have in mind?", "kind": "long", "required": True}]}[kind]
    q.append({"id": "q_ref", "label": "Who referred you? (optional)", "kind": "short", "required": False, "referral": True})
    blocks = [dict(CONTACT_BLOCK), {"id": new_id()[:8], "type": "questions", "questions": q}]
    if kind in ("discovery_call", "paid_consultation", "instant_booking"):
        blocks.append({"id": new_id()[:8], "type": "scheduler", "session_type_id": None})
    return blocks


class FormIn(P):
    id: Optional[str] = None
    name: str
    kind: str = "enquiry"
    live: bool = True
    project_type: str = ""
    source: str = "Website"
    blocks: Optional[list] = None
    thank_you: dict = {"html": "<h2>Thank you!</h2><p>We'll get back to you shortly.</p>", "redirect_url": ""}
    price_paise: int = 0
    promo_enabled: bool = False
    otp_required: bool = False
    automation_ids: list = []


@action("lead_forms.save", "internal", FormIn, roles=ADMINS, desc="Create or update a lead form.")
async def forms_save(ctx, p: FormIn):
    if p.kind not in KINDS:
        raise AppError("invalid", "Unknown form type.", 400)
    blocks = p.blocks or starter_form(p.kind)
    if not any(b.get("type") == "contact" for b in blocks):
        blocks.insert(0, dict(CONTACT_BLOCK))   # the contact block can never be removed
    if any(b.get("type") == "contract" for b in blocks):
        raise AppError("invalid", "Contracts can't go on public forms. Send them in a client file instead.", 400)
    if p.price_paise < 0:
        raise AppError("invalid", "The price can't be negative.", 400)
    doc = p.model_dump(exclude={"id"})
    doc["blocks"] = blocks
    if p.live:
        n = await ctx.data.lead_forms.count({"live": True, **({"_id": {"$ne": p.id}} if p.id else {})})
        await limits.check_count(ctx, "live_lead_forms", n)
    if p.id:
        await ctx.data.lead_forms.update({"_id": p.id}, doc)
        f = await ctx.data.lead_forms.get(p.id)
    else:
        from actions.workspace import slugify
        doc["slug"] = slugify(p.name) + "-" + new_id()[:4]
        f = await ctx.data.lead_forms.insert(doc)
    return await form_out(ctx, f)


async def form_out(ctx, f):
    from actions.merge import client_base
    ws = await ctx.ws()
    o = clean(f)
    o["link"] = f"{client_base(ws)}/form/{f['slug']}"
    o["embed"] = f'<iframe src="{o["link"]}?embed=1" style="width:100%;min-height:640px;border:0" loading="lazy"></iframe>'
    return o


@action("lead_forms.list", "read", desc="Lead forms with their links.")
async def forms_list(ctx, p):
    return [await form_out(ctx, f) for f in await ctx.data.lead_forms.find({}, sort=[("created_at", -1)])]


class IdIn(P):
    id: str


@action("lead_forms.get", "read", IdIn, desc="One lead form.")
async def forms_get(ctx, p: IdIn):
    f = await ctx.data.lead_forms.get(p.id)
    if not f:
        raise not_found("That form")
    return await form_out(ctx, f)


@action("lead_forms.delete", "destructive", IdIn, roles=ADMINS, agent_ok=False, desc="Delete a lead form.")
async def forms_delete(ctx, p: IdIn):
    await ctx.data.lead_forms.soft_delete({"_id": p.id})
    return {"ok": True}


class AnalyticsIn(P):
    id: Optional[str] = None
    days: int = 30


@action("lead_forms.analytics", "read", AnalyticsIn, desc="Form views, starts, submits and conversion, by source.")
async def forms_analytics(ctx, p: AnalyticsIn):
    since = now() - timedelta(days=max(1, min(p.days, 365)))
    f = {"at": {"$gte": since}}
    if p.id:
        f["form_id"] = p.id
    rows = await ctx.data.form_events.find(f)
    by = {}
    for r in rows:
        k = (r.get("form_id"), r.get("source") or "Direct")
        d = by.setdefault(k, {"views": 0, "starts": 0, "submits": 0})
        d[r["kind"] + "s"] = d.get(r["kind"] + "s", 0) + 1
    names = {x["_id"]: x["name"] for x in await ctx.data.lead_forms.find({})}
    out = []
    for (fid, src), d in by.items():
        out.append({"form_id": fid, "form": names.get(fid, ""), "source": src, **d,
                    "conversion_pct": round(100 * d["submits"] / d["views"]) if d["views"] else 0})
    return sorted(out, key=lambda x: -x["submits"])


async def submit(ctx, form, body: dict, ip: str):
    """Public submit. Returns what the thank-you step needs."""
    from actions.crm import create_lead
    if body.get("website"):        # honeypot field: bots fill it, people don't see it
        return {"ok": True, "thank_you": form["thank_you"]}
    hour = now() - timedelta(hours=1)
    if await ctx.data.form_events.count({"kind": "submit", "ip": ip, "at": {"$gte": hour}}) >= 20:
        raise AppError("rate_limited", "Too many submissions from this network. Please try again later.", 429)
    contact = body.get("contact") or {}
    if not (contact.get("name") or "").strip():
        raise AppError("invalid", "Please tell us your name.", 400)
    from actions.crm import norm_phone_soft
    if not norm_phone_soft(contact.get("phone")) and not (contact.get("email") or "").strip():
        raise AppError("invalid", "Please add a mobile number or email so we can reply.", 400)
    if form.get("otp_required"):
        from auth import check_otp, norm_phone
        await check_otp(norm_phone(contact.get("phone", "")), body.get("otp", ""))
    answers = body.get("answers") or {}
    labels = {}
    referral = None
    for b in form["blocks"]:
        for q in b.get("questions", []):
            labels[q["id"]] = q["label"]
            if q.get("required") and not str(answers.get(q["id"], "")).strip():
                raise AppError("invalid", f"Please answer: {q['label']}", 400)
            if q.get("referral") and str(answers.get(q["id"], "")).strip():
                referral = answers[q["id"]]
    utm = body.get("utm") or {}
    source = "Client referral" if referral else (utm.get("utm_source") or "").title() or form.get("source") or "Website"
    c, pr = await create_lead(ctx, {"name": contact.get("name"), "phone": contact.get("phone"), "email": contact.get("email"),
                                    "source": source, "project_type": form.get("project_type"), "utm": dict(utm, referrer=body.get("referrer", "")),
                                    "answers": {labels.get(k, k): v for k, v in answers.items()}, "form_id": form["_id"], "via": "form"})
    await ctx.data.form_submissions.insert({"form_id": form["_id"], "answers": answers, "contact_id": c["_id"], "project_id": pr["_id"],
                                            "utm": utm, "ip": ip})
    await ctx.data.form_events.insert({"form_id": form["_id"], "kind": "submit", "source": source, "ip": ip, "at": now()})
    out = {"ok": True, "thank_you": form["thank_you"], "project_id": pr["_id"]}
    sched = next((b for b in form["blocks"] if b.get("type") == "scheduler" and b.get("session_type_id")), None)
    if sched and body.get("slot_start"):
        from actions.scheduling import book, get_type
        st = await get_type(ctx, sched["session_type_id"])
        paid = form.get("price_paise", 0) > 0
        s = await book(ctx, st, body["slot_start"], c, pr["_id"], answers, hold=paid, reserve_requires=["pay"] if paid else [])
        out["session"] = {"id": s["_id"], "status": s["status"], "start": s["start"].isoformat()}
    if form.get("price_paise", 0) > 0:
        from actions.money import apply_promo, issue, new_invoice
        inv = await new_invoice(ctx, pr, [{"name": form["name"], "qty": 1, "price_paise": form["price_paise"]}], None, form["name"])
        if body.get("promo") and form.get("promo_enabled"):
            inv = await apply_promo(ctx, inv, body["promo"])
        await issue(ctx, inv)
        if out.get("session"):
            await ctx.data.sessions.update({"_id": out["session"]["id"]}, {"file_id": f"form:{inv['_id']}"})
            await ctx.data.invoices.update({"_id": inv["_id"]}, {"file_id": f"form:{inv['_id']}"})
        out["invoice_token"] = inv["token"]
    return out
