"""Invoices and payments. The client always pays the consultant directly.

Money rules (non-negotiable):
- amounts are whole paise (integers), never floats;
- an invoice item is paid only when the consultant marks it paid, never from
  the client's "I've paid" tap alone;
- marking paid twice (or two people at once) can never create two ledger rows:
  the payment id and the ledger key are unique;
- a paid invoice is never edited; corrections are credit notes;
- every money movement writes one row to the append-only ledger.
"""
import base64
import io
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from pymongo.errors import DuplicateKeyError

from app.domain import perm
from app.domain.registry import ADMINS, STAFF, P, action
from app.core.events import audit, emit, log, notify
from app.core.util import AppError, aware, clean, fmt_date, fy_of, inr, new_id, not_found, now, token

STATE_CODES = {"Maharashtra": "27", "Gujarat": "24", "Karnataka": "29", "Delhi": "07", "Tamil Nadu": "33", "Telangana": "36",
               "West Bengal": "19", "Rajasthan": "08", "Uttar Pradesh": "09", "Haryana": "06", "Kerala": "32", "Punjab": "03",
               "Madhya Pradesh": "23", "Goa": "30", "Andhra Pradesh": "37", "Odisha": "21", "Bihar": "10"}


# ---------------- totals ----------------

def line_total(l):
    if l.get("minutes") is not None:
        # A line made from logged time: exact minutes x hourly rate (plus the paise that keep totals exact).
        base = int(l["minutes"]) * int(l.get("price_paise", 0)) // 60 + int(l.get("adjust_paise") or 0)
        return base + sum(line_total(s) for s in l.get("sub", []))
    base = int(l.get("qty", 1) * 1000) * int(l.get("price_paise", 0)) // 1000
    return base + sum(line_total(s) for s in l.get("sub", []))


def compute(inv: dict, ws: dict) -> dict:
    """Recalculate totals and the payment schedule. Pure function, paise only."""
    lines = inv.get("lines", [])
    subtotal = sum(line_total(l) for l in lines)
    taxable_lines = sum(line_total(l) for l in lines if l.get("taxable", True))
    d = inv.get("discount") or {}
    disc = int(subtotal * d.get("value", 0) / 10000) if d.get("kind") == "pct_bp" else int(d.get("value", 0)) if d.get("kind") == "flat" else 0
    disc = max(0, min(disc, subtotal))
    promo = min(int((inv.get("promo") or {}).get("discount_paise", 0)), max(0, subtotal - disc))
    after = subtotal - disc - promo
    sc = inv.get("service_charge") or {}
    svc = int(after * sc.get("value", 0) / 10000) if sc.get("kind") == "pct_bp" else int(sc.get("value", 0)) if sc.get("kind") == "flat" else 0
    gst = inv.get("gst") or {}
    cgst = sgst = igst = 0
    if gst.get("enabled"):
        frac = (taxable_lines / subtotal) if subtotal else 0
        base = int((after) * frac) + (svc if sc.get("taxable") else 0)
        rate = int(gst.get("rate_bp", 1800))
        if gst.get("mode") == "intra":
            cgst = sgst = base * rate // 20000
        elif gst.get("mode") == "inter":
            igst = base * rate // 10000
    total = after + svc + cgst + sgst + igst
    sched = inv.get("schedule") or [{"id": new_id()[:8], "label": "Full payment", "pct": 100, "due": {"type": "on_signing"}}]
    fixed = sum(int(s.get("amount_paise_fixed") or 0) for s in sched if s.get("amount_paise_fixed"))
    pct_items = [s for s in sched if not s.get("amount_paise_fixed")]
    remaining = total - fixed
    acc = 0
    for i, s in enumerate(sched):
        s.setdefault("id", new_id()[:8])
        s.setdefault("status", "upcoming")
        s.setdefault("paid_paise", 0)
        s.setdefault("tds_paise", 0)
        s.setdefault("late_fee_paise", 0)
        if s.get("amount_paise_fixed"):
            s["amount_paise"] = int(s["amount_paise_fixed"])
        else:
            if s is pct_items[-1]:
                s["amount_paise"] = remaining - acc
            else:
                s["amount_paise"] = remaining * int(s.get("pct", 0)) // 100
                acc += s["amount_paise"]
    inv["schedule"] = sched
    inv["totals"] = {"subtotal": subtotal, "discount": disc, "promo": promo, "service_charge": svc, "cgst": cgst, "sgst": sgst,
                     "igst": igst, "total": total,
                     "paid": sum(s.get("paid_paise", 0) for s in sched),
                     "due": sum(max(0, s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0) - s.get("tds_paise", 0))
                                for s in sched if s["status"] != "paid")}
    inv["doc_title"] = "Tax Invoice" if gst.get("enabled") else "Invoice"
    return inv


def due_dates(inv, project, sent_at=None, signed_at=None):
    prev = None
    for s in inv["schedule"]:
        due = s.get("due") or {"type": "on_signing"}
        t = due.get("type")
        dd = s.get("due_date")
        if t == "date" and due.get("date"):
            dd = aware(due["date"])
        elif t == "on_signing":
            dd = aware(signed_at or sent_at) if (signed_at or sent_at) else None
        elif t == "relative_project" and project and project.get("start_date"):
            dd = aware(project["start_date"]) + timedelta(days=int(due.get("days", 0)))
        elif t == "after_previous" and prev is not None:
            base = prev.get("paid_at") or prev.get("due_date")
            dd = aware(base) + timedelta(days=int(due.get("days", 30))) if base else None
        elif t == "milestone":
            dd = aware(s["milestone_reached_at"]) if s.get("milestone_reached_at") else None
        s["due_date"] = dd
        prev = s
    return inv


def upi_link(ws, amount_paise, note):
    inv = ws.get("invoice", {})
    vpa = (inv.get("upi_id") or "").strip()
    if not vpa:
        return None
    rupees = f"{amount_paise / 100:.2f}"
    return (f"upi://pay?pa={quote(vpa)}&pn={quote(inv.get('payee_name') or ws['name'])}&am={rupees}&cu=INR"
            f"&tn={quote(note[:50])}")


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def item_state(s, inv):
    if s["status"] in ("paid", "processing"):
        return s["status"]
    if s.get("due_date") and aware(s["due_date"]) < now():
        return "overdue"
    return "upcoming"


async def view(ctx, inv, for_client=False):
    """Invoice as the screens and the client page need it."""
    ws = await ctx.ws()
    for l in inv.get("lines", []):
        l["amount_paise"] = line_total(l)
    o = clean(inv)
    for s in o["schedule"]:
        s["state"] = item_state(s, inv) if not isinstance(s.get("due_date"), str) else item_state(
            dict(s, due_date=aware(s["due_date"])), inv)
        s["due_label"] = fmt_date(s["due_date"]) if s.get("due_date") else ("On a milestone" if (s.get("due") or {}).get("type") == "milestone" else "On signing")
        left = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0) - s.get("tds_paise", 0)
        s["left_paise"] = max(0, left)
        if s["state"] != "paid" and left > 0:
            note = f"{inv.get('number') or 'Invoice'} {s['label']}"
            link = upi_link(ws, left, note)
            s["upi_link"] = link
            s["upi_qr"] = qr_svg(link) if link else None
    iv = ws.get("invoice", {})
    o["pay_to"] = {"upi_id": iv.get("upi_id"), "payee": iv.get("payee_name") or ws["name"],
                   "bank": iv.get("bank") if (for_client or ctx.role == "owner") else None}
    o["claims"] = clean(await ctx.data.payment_claims.find({"invoice_id": inv["_id"]}, sort=[("created_at", -1)]))
    if not for_client:
        o["ledger"] = clean(await ctx.data.ledger.find({"invoice_id": inv["_id"]}, sort=[("created_at", 1)]))
        o["credit_notes"] = clean(await ctx.data.credit_notes.find({"invoice_id": inv["_id"]}))
    return perm.strip_money(ctx, o) if not for_client else o


async def new_invoice(ctx, project, lines=None, schedule=None, title="", file_id=None, contact_id=None):
    ws = await ctx.ws()
    iv = ws.get("invoice", {})
    contact = None
    cid = contact_id or (project.get("contact_ids") or [None])[0]
    if cid:
        contact = await ctx.data.contacts.get(cid)
    inv = {"project_id": project["_id"], "file_id": file_id, "contact_id": cid, "title": title or "Invoice", "number": None,
           "fy": None, "status": "draft", "currency": "INR",
           "lines": [dict(l, id=l.get("id") or new_id()[:8]) for l in (lines or [])],
           "discount": None, "service_charge": None, "promo": None,
           "gst": {"enabled": bool(iv.get("gst_enabled")), "rate_bp": iv.get("tax_rate_bp", 1800),
                   "mode": "intra", "place_of_supply": iv.get("state")},
           "schedule": schedule or [{"id": new_id()[:8], "label": "Full payment", "pct": 100, "due": {"type": "on_signing"}}],
           "client_choice": {"allowed": False, "months": 3}, "tds_expected": bool(iv.get("tds_expected")),
           "notes": "", "terms": iv.get("terms", ""), "token": token(18), "client_state": (contact or {}).get("state")}
    compute(inv, ws)
    return await ctx.data.invoices.insert(inv)


async def save_invoice(ctx, inv):
    ws = await ctx.ws()
    compute(inv, ws)
    pr = await ctx.data.projects.get(inv["project_id"])
    due_dates(inv, pr, inv.get("sent_at"), inv.get("signed_at"))
    await ctx.data.invoices.update({"_id": inv["_id"]}, {k: v for k, v in inv.items() if k not in ("_id", "workspace_id", "created_at")})
    return inv


async def get_inv(ctx, iid, act=False):
    inv = await ctx.data.invoices.get(iid)
    if not inv:
        raise not_found("That invoice")
    await perm.project(ctx, inv["project_id"], act=act)
    return inv


def has_payments(inv):
    return any(s.get("paid_paise", 0) > 0 or s["status"] == "paid" for s in inv["schedule"])


# ---------------- invoice actions ----------------

class InvoiceIn(P):
    project_id: str
    title: str = "Invoice"
    lines: list = []
    schedule: Optional[list] = None
    template_id: Optional[str] = None


@action("invoices.create", "internal", InvoiceIn, roles=STAFF, desc="Create a draft invoice on a project.")
async def invoices_create(ctx, p: InvoiceIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    lines = p.lines
    if p.template_id:
        t = await ctx.data.templates.get(p.template_id)
        lines = lines or (t or {}).get("body", {}).get("lines", [])
    inv = await new_invoice(ctx, pr, lines, p.schedule, p.title)
    await log(ctx, pr["_id"], "invoice", f"Draft invoice created ({inr(inv['totals']['total'])})", ref=inv["_id"])
    return await view(ctx, inv)


class IdIn(P):
    id: str


@action("invoices.get", "read", IdIn, desc="An invoice with its schedule, UPI details, claims and ledger.")
async def invoices_get(ctx, p: IdIn):
    return await view(ctx, await get_inv(ctx, p.id))


class InvoiceUpdate(P):
    id: str
    title: Optional[str] = None
    lines: Optional[list] = None
    schedule: Optional[list] = None
    discount: Optional[dict] = None
    service_charge: Optional[dict] = None
    gst: Optional[dict] = None
    client_choice: Optional[dict] = None
    tds_expected: Optional[bool] = None
    notes: Optional[str] = None
    terms: Optional[str] = None


def validate_lines(lines):
    for l in lines:
        if l.get("minutes") is not None and l.get("qty") is not None and abs(float(l["qty"]) * 60 - int(l["minutes"])) >= 1:
            # The hours on a time line were edited by hand: the hours now decide the amount.
            l["minutes"] = int(round(float(l["qty"]) * 60))
            l["adjust_paise"] = 0
        if not (l.get("name") or "").strip():
            raise AppError("invalid", "Every line needs a name.", 400)
        if not isinstance(l.get("price_paise", 0), int):
            raise AppError("invalid", "Prices must be whole paise.", 400)
        q = l.get("qty", 1)
        if q is None or q <= 0 or q > 100000:
            raise AppError("invalid", f"Quantity for \"{l['name']}\" must be more than zero.", 400)
    total = sum(line_total(l) for l in lines)
    if total < 0:
        raise AppError("invalid", "The invoice total can't be below zero.", 400)


@action("invoices.update", "internal", InvoiceUpdate, desc="Edit a draft or unpaid invoice. Paid lines are locked.")
async def invoices_update(ctx, p: InvoiceUpdate):
    inv = await get_inv(ctx, p.id, act=True)
    if inv["status"] in ("paid", "void"):
        raise AppError("locked", "A paid invoice can't be changed. Use a credit note instead.", 409)
    ch = p.model_dump(exclude={"id"}, exclude_none=True)
    if "lines" in ch:
        if has_payments(inv):
            raise AppError("locked", "Line items are locked once a payment is made. Use a credit note or a new invoice.", 409)
        validate_lines(ch["lines"])
        ch["lines"] = [dict(l, id=l.get("id") or new_id()[:8]) for l in ch["lines"]]
        if inv["status"] == "draft":
            from app.domain.billing.timebill import on_lines_changed
            await on_lines_changed(ctx, inv, ch["lines"])
    if "schedule" in ch:
        paid_ids = {s["id"] for s in inv["schedule"] if s["status"] == "paid"}
        new_ids = {s.get("id") for s in ch["schedule"]}
        if not paid_ids <= new_ids:
            raise AppError("locked", "Paid schedule items can't be removed.", 409)
        old = {s["id"]: s for s in inv["schedule"]}
        ch["schedule"] = [dict(old.get(s.get("id"), {}), **s) if s.get("id") in old else s for s in ch["schedule"]]
        pct = sum(int(s.get("pct", 0)) for s in ch["schedule"] if not s.get("amount_paise_fixed"))
        if any(not s.get("amount_paise_fixed") for s in ch["schedule"]) and pct != 100:
            raise AppError("invalid", f"The percentages add up to {pct}%. They need to add up to 100%.", 400)
    if "discount" in ch and ch["discount"].get("kind") == "pct_bp" and not 0 <= ch["discount"].get("value", 0) <= 10000:
        raise AppError("invalid", "A discount must be between 0% and 100%.", 400)
    inv.update(ch)
    ws = await ctx.ws()
    compute(inv, ws)
    fixed = [s for s in inv["schedule"] if s.get("amount_paise_fixed")]
    if fixed and len(fixed) == len(inv["schedule"]) and sum(s["amount_paise"] for s in fixed) != inv["totals"]["total"]:
        raise AppError("invalid", "The payment amounts don't add up to the invoice total.", 400)
    inv.pop("ai_previous", None) if "lines" not in ch else None
    await save_invoice(ctx, inv)
    return await view(ctx, inv)


async def next_seq(ctx, key):
    """Atomic per-workspace counter. Two first-ever increments can race on the upsert
    (one gets a duplicate key on _id); the loser simply increments the row that now exists."""
    for _ in range(3):
        try:
            c = await ctx.data.counters.find_one_and_update({"_id": key}, {"$inc": {"seq": 1}}, upsert=True)
            return c["seq"]
        except DuplicateKeyError:
            continue
    raise AppError("busy", "Busy, please try again.", 503)


async def assign_number(ctx, inv):
    if inv.get("number"):
        return inv
    ws = await ctx.ws()
    fy = fy_of(now())
    seq = await next_seq(ctx, f"inv:{ctx.ws_id}:{fy}")
    inv["number"] = f"{ws['invoice'].get('prefix', 'INV')}/{fy}/{seq:04d}"
    inv["fy"] = fy
    inv["number_key"] = f"{ctx.ws_id}:{fy}:{inv['number']}"
    return inv


async def issue(ctx, inv):
    """Give the invoice its number and mark it sent (used by files and invoices.send)."""
    if inv["totals"]["total"] <= 0:
        raise AppError("invalid", "The invoice total must be more than zero.", 400)
    ws = await ctx.ws()
    if not (ws["invoice"].get("upi_id") or ws["invoice"].get("bank", {}).get("account_no")):
        raise AppError("no_payout", "Add your UPI ID or bank details in Settings so clients can pay you.", 400)
    await assign_number(ctx, inv)
    if inv["status"] == "draft":
        inv["status"] = "sent"
        inv["sent_at"] = now()
    await save_invoice(ctx, inv)
    from app.domain.billing.timebill import on_invoice_issued
    await on_invoice_issued(ctx, inv)
    return inv


class SendInv(P):
    id: str
    channel: str = "email"   # email | whatsapp | both


@action("invoices.send", "money", SendInv, desc="Send an invoice to the client with the pay link.")
async def invoices_send(ctx, p: SendInv):
    from app.domain.engagement.inbox import contact_for, send_message
    from app.domain.documents.merge import build, client_base
    inv = await get_inv(ctx, p.id, act=True)
    pr = await ctx.data.projects.get(inv["project_id"])
    c = await contact_for(ctx, pr, inv.get("contact_id"))
    await issue(ctx, inv)
    ws = await ctx.ws()
    link = f"{client_base(ws)}/i/{inv['token']}"
    vals = await build(ctx, pr, c)
    due = inv["totals"]["due"]
    if p.channel in ("email", "both") and c.get("email"):
        await send_message(ctx, pr["_id"], c, "email", f"{inv['doc_title']} {inv['number']} from {vals['practice.name']}",
                           f"<p>Hi {vals['client.first_name']},</p><p>Here is your invoice {inv['number']} for {inr(inv['totals']['total'])}. "
                           f"Amount due now: <b>{inr(due)}</b>.</p><p>You can pay by UPI or bank transfer.</p>",
                           button=("View and pay", link), kind="invoice")
    if p.channel in ("whatsapp", "both") and c.get("phone"):
        await send_message(ctx, pr["_id"], c, "whatsapp", wa_template="payment_reminder",
                           wa_params=[vals["client.first_name"], inr(due), link], kind="invoice")
    await log(ctx, pr["_id"], "invoice", f"Invoice {inv['number']} sent", ref=inv["_id"], client_visible=True)
    await emit(ctx, "invoice.sent", {"invoice_id": inv["_id"]}, pr["_id"])
    return await view(ctx, inv)


class RemindIn(P):
    id: str
    item_id: Optional[str] = None
    channel: str = "both"


@action("invoices.remind", "external", RemindIn, desc="Send a payment reminder for an invoice.")
async def invoices_remind(ctx, p: RemindIn):
    from app.domain.engagement.inbox import contact_for, send_message
    from app.domain.documents.merge import build, client_base
    inv = await get_inv(ctx, p.id, act=True)
    pr = await ctx.data.projects.get(inv["project_id"])
    c = await contact_for(ctx, pr, inv.get("contact_id"))
    ws = await ctx.ws()
    link = f"{client_base(ws)}/i/{inv['token']}"
    items = [s for s in inv["schedule"] if s["status"] != "paid" and (not p.item_id or s["id"] == p.item_id)]
    if not items:
        raise AppError("nothing_due", "Nothing is due on this invoice.", 400)
    s = items[0]
    left = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0)
    vals = await build(ctx, pr, c)
    when = fmt_date(s["due_date"]) if s.get("due_date") else "now"
    sent = 0
    if p.channel in ("email", "both") and c.get("email"):
        await send_message(ctx, pr["_id"], c, "email", f"Payment reminder: {inr(left)} due {when}",
                           f"<p>Hi {vals['client.first_name']},</p><p>A friendly reminder that <b>{inr(left)}</b> "
                           f"({s['label']}) is due {('on ' + when) if s.get('due_date') else 'now'}.</p>",
                           button=("Pay now", link), kind="reminder")
        sent += 1
    if p.channel in ("whatsapp", "both") and c.get("phone"):
        await send_message(ctx, pr["_id"], c, "whatsapp", wa_template="payment_reminder",
                           wa_params=[vals["client.first_name"], inr(left), link], kind="reminder")
        sent += 1
    return {"ok": True, "sent": sent}


class ListInv(P):
    ids: Optional[list] = None
    contact_id: Optional[str] = None
    project_id: Optional[str] = None
    status: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    fy: Optional[str] = None


@action("invoices.list", "read", ListInv, desc="Invoices, newest first. Filter by client, project, status, dates or financial year.")
async def invoices_list(ctx, p: ListInv):
    from app.domain.billing.timebill import InvFilter, filtered_invoices
    rows = (await filtered_invoices(ctx, InvFilter(**p.model_dump())))[:500]
    names = {pr["_id"]: pr["name"] for pr in await ctx.data.projects.find({"_id": {"$in": [r["project_id"] for r in rows]}})}
    out = []
    for r in rows:
        o = clean(r)
        o["project_name"] = names.get(r["project_id"], "")
        out.append(o)
    return perm.strip_money(ctx, out)


class AiEdit(P):
    id: str
    instruction: str


@action("invoices.ai_edit", "internal", AiEdit, desc="Edit a draft invoice by instruction, e.g. 'add a 10% discount'. Can be undone.")
async def invoices_ai_edit(ctx, p: AiEdit):
    from app.agents.writer import edit_invoice
    inv = await get_inv(ctx, p.id, act=True)
    if has_payments(inv) or inv["status"] in ("paid", "void"):
        raise AppError("locked", "This invoice already has a payment, so it can't be edited.", 409)
    prev = {k: inv.get(k) for k in ("lines", "schedule", "discount", "service_charge")}
    changes, summary = await edit_invoice(ctx, inv, p.instruction)
    inv.update(changes)
    inv["ai_previous"] = prev
    await save_invoice(ctx, inv)
    await log(ctx, inv["project_id"], "invoice", f"Invoice edited by AI: {summary}", ref=inv["_id"])
    out = await view(ctx, inv)
    out["ai_summary"] = summary
    return out


@action("invoices.undo_ai_edit", "internal", IdIn, desc="Undo the last AI edit on an invoice.")
async def invoices_undo(ctx, p: IdIn):
    inv = await get_inv(ctx, p.id, act=True)
    prev = inv.get("ai_previous")
    if not prev or has_payments(inv):
        raise AppError("nothing_to_undo", "There is no AI edit to undo.", 400)
    inv.update(prev)
    inv["ai_previous"] = None
    await save_invoice(ctx, inv)
    return await view(ctx, inv)


class MilestoneIn(P):
    id: str
    item_id: str


@action("invoices.milestone_reached", "internal", MilestoneIn, desc="Mark a milestone reached so its payment becomes due.")
async def invoices_milestone(ctx, p: MilestoneIn):
    inv = await get_inv(ctx, p.id, act=True)
    for s in inv["schedule"]:
        if s["id"] == p.item_id:
            s["milestone_reached_at"] = now()
    await save_invoice(ctx, inv)
    return await view(ctx, inv)


class CreditIn(P):
    id: str
    amount_paise: int
    reason: str
    time_to: str = "unbilled"   # a full credit gives its time back: unbilled or non_billable


@action("invoices.credit_note", "money", CreditIn, roles=ADMINS, desc="Issue a credit note against an invoice.")
async def invoices_credit(ctx, p: CreditIn):
    inv = await get_inv(ctx, p.id, act=True)
    if p.amount_paise <= 0 or p.amount_paise > inv["totals"]["total"]:
        raise AppError("invalid", "The credit amount must be more than zero and not more than the invoice total.", 400)
    fy = fy_of(now())
    seq = await next_seq(ctx, f"cn:{ctx.ws_id}:{fy}")
    cn = await ctx.data.credit_notes.insert({"invoice_id": inv["_id"], "project_id": inv["project_id"], "number": f"CN/{fy}/{seq:04d}",
                                             "amount_paise": p.amount_paise, "reason": p.reason[:300]})
    await ledger(ctx, f"cn:{cn['_id']}", "credit_note", p.amount_paise, inv, ref=cn["_id"])
    await audit(ctx, "invoice.credit_note", inv["_id"], {"amount_paise": p.amount_paise})
    out = clean(cn)
    if p.amount_paise == inv["totals"]["total"]:
        from app.domain.billing.timebill import release_invoice_time
        out["time_released"] = await release_invoice_time(ctx, inv, p.time_to)
    return out


class VoidIn(P):
    id: str
    time_to: str = "unbilled"   # what happens to its time: back to unbilled, or non_billable


@action("invoices.void", "destructive", VoidIn, roles=ADMINS, agent_ok=False,
        desc="Cancel an unpaid invoice. Its time goes back to unbilled (or is marked non-billable).")
async def invoices_void(ctx, p: VoidIn):
    inv = await get_inv(ctx, p.id, act=True)
    if has_payments(inv):
        raise AppError("locked", "An invoice with payments can't be voided. Use a credit note.", 409)
    await ctx.data.invoices.update({"_id": inv["_id"]}, {"status": "void"})
    from app.domain.billing.timebill import release_invoice_time
    n = await release_invoice_time(ctx, inv, p.time_to)
    return {"ok": True, "time_released": n}


# ---------------- payments ----------------

async def ledger(ctx, key, typ, amount, inv, ref=None, extra=None):
    """Append-only. The unique key makes a second write of the same movement a no-op."""
    try:
        await ctx.data.ledger.insert({"key": key, "type": typ, "amount_paise": int(amount), "invoice_id": inv["_id"],
                                      "project_id": inv["project_id"], "ref": ref, "actor": ctx.actor, "user_id": ctx.user_id,
                                      **(extra or {})})
        return True
    except DuplicateKeyError:
        return False


async def client_claim(ctx, inv, item_id, method, reference="", screenshot_key=None):
    """The client tapped "I've paid". This never marks anything paid."""
    s = next((x for x in inv["schedule"] if x["id"] == item_id), None)
    if not s:
        raise not_found("That payment")
    if s["status"] == "paid":
        return {"ok": True, "already_paid": True}
    if s["status"] == "processing":
        return {"ok": True, "already_claimed": True}
    # Claim the line atomically: of several taps arriving together, only one moves it to processing.
    got = await ctx.data.invoices.update(
        {"_id": inv["_id"], "schedule": {"$elemMatch": {"id": item_id, "status": {"$nin": ["paid", "processing"]}}}},
        {"schedule.$.status": "processing"})
    if not got.modified_count:
        return {"ok": True, "already_claimed": True}
    claim = await ctx.data.payment_claims.insert({"invoice_id": inv["_id"], "project_id": inv["project_id"], "item_id": item_id,
                                                  "method": method, "reference": reference[:80], "screenshot_key": screenshot_key,
                                                  "amount_paise": s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0),
                                                  "status": "pending", "invoice_version": inv.get("version", 1)})
    s["status"] = "processing"
    s["claim_id"] = claim["_id"]
    await save_invoice(ctx, inv)
    await log(ctx, inv["project_id"], "payment", f"Client says they paid {inr(claim['amount_paise'])} by {method.upper()}"
              f"{(' (ref ' + reference + ')') if reference else ''}. Waiting for your confirmation.", ref=claim["_id"])
    await emit(ctx, "payment.claimed", {"invoice_id": inv["_id"], "item_id": item_id, "claim_id": claim["_id"]}, inv["project_id"])
    await notify(ctx, f"Payment to confirm: {inr(claim['amount_paise'])} on {inv.get('number') or 'an invoice'}", "payment",
                 link=f"/projects/{inv['project_id']}?tab=payments")
    return {"ok": True, "claim_id": claim["_id"]}


class ConfirmIn(P):
    invoice_id: str
    item_id: str
    amount_received_paise: Optional[int] = None
    tds_paise: int = 0
    method: str = "upi"
    reference: str = ""


async def confirm_payment(ctx, inv, item_id, received=None, tds=0, method="upi", reference=""):
    s = next((x for x in inv["schedule"] if x["id"] == item_id), None)
    if not s:
        raise not_found("That payment")
    due = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0)
    received = due - tds if received is None else received
    if received < 0 or tds < 0:
        raise AppError("invalid", "Amounts can't be negative.", 400)
    if received + tds != due:
        raise AppError("invalid", f"Amount received ({inr(received)}) plus TDS ({inr(tds)}) must equal the amount due ({inr(due)}).", 400)
    pay_id = f"{inv['_id']}:{item_id}"
    try:
        await ctx.data.payments.insert({"_id": pay_id, "invoice_id": inv["_id"], "project_id": inv["project_id"], "schedule_item": item_id,
                                        "amount_paise": received, "tds_paise": tds, "method": method, "reference": reference[:80],
                                        "status": "confirmed", "confirmed_by": ctx.user_id})
    except DuplicateKeyError:
        return {"ok": True, "already_paid": True}
    await ledger(ctx, f"pay:{pay_id}", "payment", received, inv, ref=pay_id, extra={"method": method})
    if tds:
        await ledger(ctx, f"tds:{pay_id}", "tds", tds, inv, ref=pay_id)
    fresh = await ctx.data.invoices.get(inv["_id"])
    first_ever = not any(x["status"] == "paid" for x in fresh["schedule"])
    for x in fresh["schedule"]:
        if x["id"] == item_id:
            x.update({"status": "paid", "paid_paise": x.get("paid_paise", 0) + received, "tds_paise": x.get("tds_paise", 0) + tds,
                      "paid_at": now()})
    all_paid = all(x["status"] == "paid" for x in fresh["schedule"])
    fresh["status"] = "paid" if all_paid else "partially_paid"
    await save_invoice(ctx, fresh)
    if s.get("claim_id"):
        await ctx.data.payment_claims.update({"_id": s["claim_id"]}, {"status": "confirmed"})
    await log(ctx, inv["project_id"], "payment", f"Payment confirmed: {inr(received)}" + (f" + TDS {inr(tds)}" if tds else ""),
              ref=pay_id, client_visible=True)
    from app.domain.sales.crm import set_booked
    await set_booked(ctx, inv["project_id"], "payment received")
    project_paid_before = await ctx.data.ledger.count({"project_id": inv["project_id"], "type": "payment"})
    if first_ever and project_paid_before == 1:
        await emit(ctx, "payment.first_paid", {"invoice_id": inv["_id"], "item_id": item_id}, inv["project_id"])
    if all_paid:
        await emit(ctx, "invoice.paid_in_full", {"invoice_id": inv["_id"]}, inv["project_id"])
    from app.domain.engagement.scheduling import confirm_held_for_file
    if inv.get("file_id"):
        await confirm_held_for_file(ctx, inv["file_id"], "pay")
    return {"ok": True, "paid_in_full": all_paid}


@action("payments.confirm", "money", ConfirmIn, desc="Mark a payment as received (the only way an invoice becomes paid).")
async def payments_confirm(ctx, p: ConfirmIn):
    inv = await get_inv(ctx, p.invoice_id, act=True)
    return await confirm_payment(ctx, inv, p.item_id, p.amount_received_paise, p.tds_paise, p.method, p.reference)


class RejectIn(P):
    claim_id: str
    reason: str = "We couldn't find this payment yet."


@action("payments.reject_claim", "money", RejectIn, desc="Reject a client's 'I've paid' claim; the payment returns to due and the client is told.")
async def payments_reject(ctx, p: RejectIn):
    from app.domain.engagement.inbox import contact_for, send_message
    cl = await ctx.data.payment_claims.get(p.claim_id)
    if not cl or cl["status"] != "pending":
        raise not_found("That claim")
    inv = await get_inv(ctx, cl["invoice_id"], act=True)
    for s in inv["schedule"]:
        if s["id"] == cl["item_id"] and s["status"] == "processing":
            s["status"] = "upcoming"
            s.pop("claim_id", None)
    await save_invoice(ctx, inv)
    await ctx.data.payment_claims.update({"_id": cl["_id"]}, {"status": "rejected", "reason": p.reason})
    pr = await ctx.data.projects.get(inv["project_id"])
    c = await contact_for(ctx, pr, inv.get("contact_id"))
    if c.get("email"):
        await send_message(ctx, pr["_id"], c, "email", "About your payment",
                           f"<p>Hi {c.get('first_name') or c['name']},</p><p>{p.reason} Could you check and share the "
                           f"reference number? The payment is still showing as due.</p>", kind="claim_rejected")
    await log(ctx, pr["_id"], "payment", f"Payment claim rejected: {p.reason}", ref=cl["_id"])
    return {"ok": True}


class RefundIn(P):
    invoice_id: str
    amount_paise: int
    note: str = ""


@action("payments.refund", "money", RefundIn, roles=ADMINS, desc="Record a refund you have sent back to the client.")
async def payments_refund(ctx, p: RefundIn):
    inv = await get_inv(ctx, p.invoice_id, act=True)
    paid = sum(r["amount_paise"] for r in await ctx.data.ledger.find({"invoice_id": inv["_id"], "type": "payment"}))
    refunded = sum(r["amount_paise"] for r in await ctx.data.ledger.find({"invoice_id": inv["_id"], "type": "refund"}))
    if p.amount_paise <= 0 or p.amount_paise > paid - refunded:
        raise AppError("invalid", f"You can refund up to {inr(paid - refunded)} on this invoice.", 400)
    key = f"refund:{ctx.idem_key or ctx.request_id}"
    await ledger(ctx, key, "refund", p.amount_paise, inv, extra={"note": p.note[:200]})
    await log(ctx, inv["project_id"], "payment", f"Refund recorded: {inr(p.amount_paise)}", ref=inv["_id"], client_visible=True)
    await audit(ctx, "payment.refund", inv["_id"], {"amount_paise": p.amount_paise})
    return {"ok": True}


class LateFeeIn(P):
    invoice_id: str
    item_id: str


@action("payments.cancel_late_fee", "money", LateFeeIn, desc="Cancel a late fee on a payment.")
async def payments_cancel_late_fee(ctx, p: LateFeeIn):
    inv = await get_inv(ctx, p.invoice_id, act=True)
    for s in inv["schedule"]:
        if s["id"] == p.item_id and s["status"] != "paid":
            s["late_fee_paise"] = 0
            s["late_fee_cancelled"] = True
    await save_invoice(ctx, inv)
    await log(ctx, inv["project_id"], "payment", "Late fee cancelled", ref=inv["_id"])
    return await view(ctx, inv)


class ListDue(P):
    project_id: Optional[str] = None


@action("payments.list_due", "read", ListDue, desc="Every payment item grouped: paid, processing, upcoming, overdue.")
async def payments_list_due(ctx, p: ListDue):
    vis = await ctx.data.projects.find(perm.visible_filter(ctx), projection={"name": 1})
    names = {x["_id"]: x["name"] for x in vis}
    f = {"project_id": {"$in": list(names)}, "status": {"$nin": ["draft", "void"]}}
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    groups = {"paid": [], "processing": [], "upcoming": [], "overdue": []}
    for inv in await ctx.data.invoices.find(f, sort=[("created_at", -1)], limit=1000):
        for s in inv["schedule"]:
            st = item_state(s, inv)
            groups[st].append({"invoice_id": inv["_id"], "number": inv.get("number"), "project_id": inv["project_id"],
                               "project": names.get(inv["project_id"], ""), "item_id": s["id"], "label": s["label"],
                               "amount_paise": s["amount_paise"] + s.get("late_fee_paise", 0), "paid_paise": s.get("paid_paise", 0),
                               "late_fee_paise": s.get("late_fee_paise", 0), "claim_id": s.get("claim_id"),
                               "due_date": aware(s["due_date"]).isoformat() if s.get("due_date") else None,
                               "paid_at": aware(s["paid_at"]).isoformat() if s.get("paid_at") else None})
    totals = {k: sum(i["amount_paise"] - (i["paid_paise"] if k != "paid" else 0) for i in v) for k, v in groups.items()}
    totals["paid"] = sum(i["paid_paise"] for i in groups["paid"])
    stale = await ctx.data.payment_claims.find({"status": "pending", "created_at": {"$lt": now() - timedelta(days=2)}})
    return perm.strip_money(ctx, {"groups": groups, "totals_paise": totals, "stale_claims": clean(stale)})


class RequestIn(P):
    project_id: str
    amount_paise: int
    label: str = "Payment"
    due_date: Optional[str] = None
    channel: str = "both"


@action("payments.request", "money", RequestIn, desc="Send a one-off payment request (a single-line invoice) with a pay link.")
async def payments_request(ctx, p: RequestIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    if p.amount_paise <= 0:
        raise AppError("invalid", "The amount must be more than zero.", 400)
    sched = [{"id": new_id()[:8], "label": p.label, "pct": 100,
              "due": {"type": "date", "date": p.due_date} if p.due_date else {"type": "on_signing"}}]
    inv = await new_invoice(ctx, pr, [{"name": p.label, "qty": 1, "price_paise": p.amount_paise}], sched, p.label)
    return await invoices_send(ctx, SendInv(id=inv["_id"], channel=p.channel))


# ---------------- promo codes ----------------

class PromoIn(P):
    code: str
    kind: str = "pct_bp"     # pct_bp | flat
    value: int
    active: bool = True


@action("promo.save", "internal", PromoIn, roles=ADMINS, desc="Create or update a promo code.")
async def promo_save(ctx, p: PromoIn):
    code = p.code.strip().upper()
    if not code or p.value <= 0 or (p.kind == "pct_bp" and p.value >= 10000):
        raise AppError("invalid", "A promo code needs a name and a discount below 100%.", 400)
    ex = await ctx.data.promo_codes.find_one({"code": code})
    doc = {"code": code, "kind": p.kind, "value": p.value, "active": p.active}
    if ex:
        await ctx.data.promo_codes.update({"_id": ex["_id"]}, doc)
    else:
        await ctx.data.promo_codes.insert(doc)
    return clean(await ctx.data.promo_codes.find({}))


@action("promo.list", "read", desc="Promo codes.")
async def promo_list(ctx, p):
    return clean(await ctx.data.promo_codes.find({}))


async def apply_promo(ctx, inv, code):
    pc = await ctx.data.promo_codes.find_one({"code": code.strip().upper(), "active": True})
    if not pc:
        raise AppError("invalid", "That promo code isn't valid.", 400)
    if has_payments(inv):
        raise AppError("locked", "A promo code can't be added after a payment.", 409)
    sub = inv["totals"]["subtotal"] - inv["totals"]["discount"]
    disc = sub * pc["value"] // 10000 if pc["kind"] == "pct_bp" else pc["value"]
    if disc >= sub:
        raise AppError("invalid", "This code can't be used on this invoice.", 400)
    inv["promo"] = {"code": pc["code"], "discount_paise": disc}
    await save_invoice(ctx, inv)
    return inv


# ---------------- recurring invoices (retainers) ----------------

class RecurringIn(P):
    project_id: str
    lines: list
    day_of_month: int = 1
    start_month: Optional[str] = None   # YYYY-MM
    end_month: Optional[str] = None
    channel: str = "both"


@action("recurring.create", "money", RecurringIn, desc="Set up a monthly invoice for a retainer.")
async def recurring_create(ctx, p: RecurringIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    validate_lines(p.lines)
    if not 1 <= p.day_of_month <= 28:
        raise AppError("invalid", "Pick a day between 1 and 28 so it exists in every month.", 400)
    r = await ctx.data.recurring_invoices.insert({"project_id": pr["_id"], "lines": p.lines, "day_of_month": p.day_of_month,
                                                  "start_month": p.start_month, "end_month": p.end_month, "channel": p.channel,
                                                  "active": True, "last_month": None})
    await log(ctx, pr["_id"], "invoice", f"Monthly invoice set up for day {p.day_of_month}", ref=r["_id"])
    return clean(r)


@action("recurring.list", "read", desc="Recurring invoices.")
async def recurring_list(ctx, p):
    return clean(await ctx.data.recurring_invoices.find({}))


@action("recurring.cancel", "money", IdIn, desc="Stop a recurring invoice (only the consultant can).")
async def recurring_cancel(ctx, p: IdIn):
    await ctx.data.recurring_invoices.update({"_id": p.id}, {"active": False})
    return {"ok": True}
