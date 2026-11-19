"""Client files: pages of blocks the client reviews, picks, signs, pays and books
in one sitting. Plus templates, versions, tracking and contract signing.

- The consultant edits a working copy. Sending makes a new version; the client
  always sees the latest sent version.
- A signed contract that is edited and re-shared cancels the old signatures and
  the client is asked to sign again. Both versions are kept.
- If a required contract comes before an invoice, the invoice page stays locked
  until the contract is signed.
"""
import copy
import hashlib
from typing import Optional

from app.domain import perm
from app.domain.documents.merge import build, client_base, fill, session_values
from app.domain.billing.money import compute, due_dates, issue, new_invoice, save_invoice, view as invoice_view
from app.domain.registry import ADMINS, STAFF, P, action
from app.core.events import emit, log, notify
from app.core.util import AppError, aware, clean, fmt_dt, inr, new_id, not_found, now, token

BLOCK_TYPES = {"text", "image", "video", "divider", "spacer", "company", "questions", "services", "contract", "invoice",
               "scheduler", "timeline", "thankyou", "quote", "retainer"}


class IdIn(P):
    id: str


class FileListIn(P):
    project_id: Optional[str] = None


class RemindIn(P):
    file_id: str


class KeyIn(P):
    key: str


def blocks_of(pages, typ=None):
    for pg in pages:
        for b in pg.get("blocks", []):
            if typ is None or b["type"] == typ:
                yield pg, b


def validate_pages(pages):
    if not isinstance(pages, list) or not pages:
        raise AppError("invalid", "A client file needs at least one page.", 400)
    seen = set()
    for pg in pages:
        pg.setdefault("id", new_id()[:10])
        pg.setdefault("blocks", [])
        for b in pg["blocks"]:
            if b.get("type") not in BLOCK_TYPES:
                raise AppError("invalid", f"Unknown block type: {b.get('type')}.", 400)
            b.setdefault("id", new_id()[:10])
            if b["id"] in seen:
                b["id"] = new_id()[:10]
            seen.add(b["id"])


def contract_hash(rendered_html):
    return hashlib.sha256(rendered_html.encode("utf-8")).hexdigest()


async def get_file(ctx, fid, act=False):
    f = await ctx.data.client_files.get(fid)
    if not f:
        raise not_found("That client file")
    await perm.project(ctx, f["project_id"], act=act)
    return f


async def prepare_blocks(ctx, f, project):
    """Create linked invoices, default signers; keep invoices in step with the file."""
    ws = await ctx.ws()
    owner_id = ws["owner_id"]
    for pg, b in blocks_of(f["pages"]):
        if b["type"] == "invoice" and not b.get("invoice_id"):
            inv = await new_invoice(ctx, project, b.get("lines") or [], copy.deepcopy(b.get("schedule")), f.get("title", "Invoice"),
                                    file_id=f["_id"])
            b["invoice_id"] = inv["_id"]
        if b["type"] == "contract" and not b.get("signers"):
            cid = (project.get("contact_ids") or [None])[0]
            b["signers"] = [{"id": "client", "role": "client", "contact_id": cid, "required": True},
                            {"id": "consultant", "role": "consultant", "user_id": owner_id, "required": True}]


async def create_file(ctx, project, pages, title, kind="file", template_id=None):
    pages = copy.deepcopy(pages)
    validate_pages(pages)
    f = {"_id": new_id(), "project_id": project["_id"], "title": title[:120], "kind": kind, "pages": pages, "version": 0,
         "status": "draft", "token": token(20), "answers": {}, "selections": {}, "plan_choice": {}, "progress": 0,
         "template_id": template_id, "sent_at": None, "completed_at": None, "viewed_count": 0}
    await prepare_blocks(ctx, f, project)
    await ctx.data.client_files.insert(f)
    await log(ctx, project["_id"], "file", f"Client file created: {title}", ref=f["_id"])
    return f


class CreateIn(P):
    project_id: str
    template_id: Optional[str] = None
    from_file_id: Optional[str] = None
    title: str = ""


@action("files.create_from_template", "internal", CreateIn, roles=STAFF,
        desc="Create a client file on a project from a template, a recent file, or blank.")
async def files_create(ctx, p: CreateIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    if p.template_id:
        t = await ctx.data.templates.get(p.template_id)
        if not t or t["kind"] != "file":
            raise not_found("That file template")
        pages, title = t["body"]["pages"], p.title or t["name"]
    elif p.from_file_id:
        src = await get_file(ctx, p.from_file_id)
        pages, title = src["pages"], p.title or f"{src['title']} (copy)"
        pages = copy.deepcopy(pages)
        for _, b in blocks_of(pages):
            if b["type"] == "invoice":
                b["invoice_id"] = None
            if b["type"] == "contract":
                b["signers"] = []
    else:
        pages, title = [{"id": new_id()[:10], "title": "Page 1", "button": "Continue", "blocks": [{"id": new_id()[:10], "type": "text", "html": ""}]}], p.title or "New client file"
    f = await create_file(ctx, pr, pages, title, template_id=p.template_id)
    return await file_out(ctx, f)


async def file_out(ctx, f):
    o = clean(f)
    o["versions"] = [{"version": v["version"], "sent_at": clean(v)["created_at"], "changes": v.get("changes", [])}
                     for v in await ctx.data.file_versions.find({"file_id": f["_id"]}, sort=[("version", -1)])]
    o["events"] = clean(await ctx.data.file_events.find({"file_id": f["_id"]}, sort=[("at", -1)], limit=100))
    o["signatures"] = clean(await ctx.data.signatures.find({"file_id": f["_id"]}, sort=[("signed_at", 1)]))
    invs = {}
    for _, b in blocks_of(f["pages"], "invoice"):
        if b.get("invoice_id"):
            inv = await ctx.data.invoices.get(b["invoice_id"])
            if inv:
                invs[b["invoice_id"]] = await invoice_view(ctx, inv)
    o["invoices"] = invs
    o["issues"] = await send_issues(ctx, f)
    ws = await ctx.ws()
    o["link"] = f"{client_base(ws)}/f/{f['token']}"
    return o


async def send_issues(ctx, f):
    """Things that block sending, in plain words."""
    out = []
    pr = await ctx.data.projects.get(f["project_id"])
    if not pr.get("contact_ids"):
        out.append("Add a client to this project first.")
    for pg, b in blocks_of(f["pages"], "contract"):
        for fld in b.get("fields", []):
            if fld.get("permission") == "consultant" and not (fld.get("value") or "").strip():
                out.append(f"Fill in \"{fld['label']}\" in the contract on page \"{pg['title']}\".")
    for pg, b in blocks_of(f["pages"], "scheduler"):
        if not b.get("session_type_id"):
            out.append(f"Choose a session type for the scheduler on page \"{pg['title']}\".")
    for pg, b in blocks_of(f["pages"], "invoice"):
        inv = await ctx.data.invoices.get(b.get("invoice_id")) if b.get("invoice_id") else None
        svc = any(x.get("feeds_invoice") for _, x in blocks_of(f["pages"], "services"))
        if inv and not inv["lines"] and not svc:
            out.append(f"Add at least one line to the invoice on page \"{pg['title']}\".")
    return out


@action("files.get", "read", IdIn,
        desc="A client file with versions, tracking events, signatures and invoices.")
async def files_get(ctx, p):
    return await file_out(ctx, await get_file(ctx, p.id))


class UpdateIn(P):
    id: str
    title: Optional[str] = None
    pages: Optional[list] = None


@action("files.update", "internal", UpdateIn, desc="Save the working copy of a client file (autosave).")
async def files_update(ctx, p: UpdateIn):
    f = await get_file(ctx, p.id, act=True)
    ch = {}
    if p.title is not None:
        ch["title"] = p.title.strip()[:120] or f["title"]
    if p.pages is not None:
        validate_pages(p.pages)
        # Invoices with payments keep their lines: block edits to them.
        for _, b in blocks_of(p.pages, "invoice"):
            if b.get("invoice_id"):
                inv = await ctx.data.invoices.get(b["invoice_id"])
                if inv and any(s["status"] == "paid" for s in inv["schedule"]) and b.get("lines") is not None and b.get("lines") != inv["lines"]:
                    raise AppError("locked", "This invoice already has a payment, so its lines are locked.", 409)
        f["pages"] = p.pages
        await prepare_blocks(ctx, f, await ctx.data.projects.get(f["project_id"]))
        ch["pages"] = f["pages"]
        # Keep invoice drafts in step with the invoice block (lines and schedule).
        for _, b in blocks_of(f["pages"], "invoice"):
            inv = await ctx.data.invoices.get(b["invoice_id"])
            if inv and not any(s["status"] == "paid" for s in inv["schedule"]):
                if b.get("lines") is not None:
                    inv["lines"] = b["lines"]
                if b.get("schedule"):
                    old = {s["id"]: s for s in inv["schedule"] if "id" in s}
                    inv["schedule"] = [dict(old.get(s.get("id"), {}), **s) for s in copy.deepcopy(b["schedule"])]
                if b.get("client_choice") is not None:
                    inv["client_choice"] = {"allowed": bool(b["client_choice"]), "months": 3}
                await save_invoice(ctx, inv)
    if ch:
        await ctx.data.client_files.update({"_id": f["_id"]}, ch)
    return await file_out(ctx, await ctx.data.client_files.get(f["_id"]))


class BlockIn(P):
    id: str
    block_id: str
    props: dict


@action("files.update_block", "internal", BlockIn, desc="Change one block in a client file's working copy.")
async def files_update_block(ctx, p: BlockIn):
    f = await get_file(ctx, p.id, act=True)
    found = False
    for _, b in blocks_of(f["pages"]):
        if b["id"] == p.block_id:
            b.update({k: v for k, v in p.props.items() if k not in ("id", "type", "invoice_id")})
            found = True
    if not found:
        raise not_found("That block")
    return await files_update(ctx, UpdateIn(id=f["_id"], pages=f["pages"]))


def diff_pages(old, new):
    """Plain 'what changed' list between two versions."""
    if old is None:
        return ["First version sent."]
    ob = {b["id"]: (pg, b) for pg, b in blocks_of(old)}
    nb = {b["id"]: (pg, b) for pg, b in blocks_of(new)}
    names = {"text": "Text", "services": "Services and prices", "contract": "Contract", "invoice": "Invoice", "questions": "Questions",
             "scheduler": "Booking", "timeline": "Timeline", "image": "Image", "video": "Video", "thankyou": "Thank-you message"}
    out = []
    for bid, (pg, b) in nb.items():
        label = names.get(b["type"], b["type"].title())
        if bid not in ob:
            out.append(f"Added: {label} on \"{pg['title']}\".")
            continue
        _, o = ob[bid]
        strip = lambda x: {k: v for k, v in x.items() if k not in ("signers",)}
        if strip(o) != strip(b):
            if b["type"] == "services":
                op = {i["id"]: i for i in o.get("items", [])}
                for i in b.get("items", []):
                    if i["id"] not in op:
                        out.append(f"Added option: {i['name']} ({inr(i.get('price_paise', 0))}).")
                    elif op[i["id"]].get("price_paise") != i.get("price_paise"):
                        out.append(f"Price of {i['name']}: {inr(op[i['id']].get('price_paise', 0))} → {inr(i.get('price_paise', 0))}.")
                    elif op[i["id"]] != i:
                        out.append(f"Changed option: {i['name']}.")
                for iid, i in op.items():
                    if iid not in {x["id"] for x in b.get("items", [])}:
                        out.append(f"Removed option: {i['name']}.")
            else:
                out.append(f"Changed: {label} on \"{pg['title']}\".")
    for bid, (pg, b) in ob.items():
        if bid not in nb:
            out.append(f"Removed: {names.get(b['type'], b['type'].title())} from \"{pg['title']}\".")
    if [p_.get("title") for p_ in old] != [p_.get("title") for p_ in new]:
        out.append("Pages were renamed or reordered.")
    return out or ["No visible changes."]


async def render_contract(ctx, f, b, pages=None, pr=None, contact=None):
    pr = pr or await ctx.data.projects.get(f["project_id"])
    vals = await contract_values(ctx, f, pr, pages or f["pages"], contact)
    return fill(b.get("html", ""), vals, True, b.get("fields"))


async def contract_values(ctx, f, pr, pages, contact=None):
    ws = await ctx.ws()
    vals = await build(ctx, pr, contact)
    sel = f.get("selections", {})
    chosen = []
    for _, sb in blocks_of(pages, "services"):
        picked = sel.get(sb["id"]) or {}
        for it in sb.get("items", []):
            if it["id"] in picked:
                chosen.append((it, picked[it["id"]]))
    vals["services.recap"] = ("<table><tr><th>Service</th><th>Qty</th><th class='num'>Price</th></tr>" +
                              "".join(f"<tr><td>{it['name']}<br><span class='muted'>{it.get('desc', '')}</span></td><td>{q}</td>"
                                      f"<td class='num'>{inr(it.get('price_paise', 0) * q)}</td></tr>" for it, q in chosen) +
                              "</table>") if chosen else "<p><i>The services you choose in this file.</i></p>"
    total = 0
    rows = ""
    for _, ib in blocks_of(pages, "invoice"):
        inv = await ctx.data.invoices.get(ib.get("invoice_id")) if ib.get("invoice_id") else None
        if inv:
            total = inv["totals"]["total"]
            for s in inv["schedule"]:
                when = {"on_signing": "on signing", "after_previous": f"{s['due'].get('days', 30)} days after the previous payment",
                        "milestone": f"on milestone: {s['due'].get('milestone', s['label'])}",
                        "relative_project": f"{s['due'].get('days', 0)} days from the project start"}.get(
                    (s.get("due") or {}).get("type"), (fmt_dt(s["due_date"]).split(",")[0] if s.get("due_date") else ""))
                rows += f"<tr><td>{s['label']}</td><td>{when}</td><td class='num'>{inr(s['amount_paise'])}</td></tr>"
    vals["payments.recap"] = f"<table><tr><th>Payment</th><th>Due</th><th class='num'>Amount</th></tr>{rows}</table>" if rows else ""
    if total:
        vals["project.value"] = inr(total)
    lf = ws.get("invoice", {}).get("late_fee", {})
    vals["late_fee_clause"] = fill(__import__("app.domain.documents.defaults", fromlist=["x"]).LATE_FEE_CLAUSE, vals) if lf.get("enabled") else ""
    s = await ctx.data.sessions.find_one({"file_id": f["_id"], "status": {"$in": ["booked", "held"]}})
    vals.update(session_values(s))
    vals["file.link"] = f"{client_base(ws)}/f/{f['token']}"
    return vals


class SendIn(P):
    id: str
    channel: str = "email"      # email | whatsapp | both | link
    message: str = ""
    subject: str = ""
    schedule_at: Optional[str] = None
    notify_client: bool = True


async def do_send(ctx, f, p: SendIn):
    issues = await send_issues(ctx, f)
    if issues:
        raise AppError("not_ready", issues[0], 400, {"issues": issues})
    pr = await ctx.data.projects.get(f["project_id"])
    from app.domain.engagement.inbox import contact_for, send_message
    c = await contact_for(ctx, pr)
    if p.channel in ("email",) and not c.get("email"):
        raise AppError("no_address", "This client has no email address. Send by WhatsApp or add an email.", 400)
    ws = await ctx.ws()
    prev = await ctx.data.file_versions.find_one({"file_id": f["_id"]}, sort=[("version", -1)])
    changes = diff_pages(prev["pages"] if prev else None, f["pages"])
    version = (f.get("version") or 0) + 1
    # Contract text fingerprints for this version; edited signed contracts lose their signatures.
    hashes = {}
    asked_again = False
    for _, b in blocks_of(f["pages"], "contract"):
        rendered = await render_contract(ctx, f, b, pr=pr, contact=c)
        hashes[b["id"]] = contract_hash(rendered)
        active = await ctx.data.signatures.find({"file_id": f["_id"], "block_id": b["id"], "status": "active"})
        if active and any(s["doc_hash"] != hashes[b["id"]] for s in active):
            await ctx.data.signatures.update_many({"file_id": f["_id"], "block_id": b["id"], "status": "active"}, {"status": "cancelled"})
            changes.append("The contract changed, so earlier signatures were cancelled. Please sign again.")
            asked_again = True
    await ctx.data.file_versions.insert({"file_id": f["_id"], "version": version, "pages": copy.deepcopy(f["pages"]),
                                         "changes": changes, "contract_hashes": hashes})
    has_contract = any(True for _ in blocks_of(f["pages"], "contract"))
    has_invoice = False
    for _, b in blocks_of(f["pages"], "invoice"):
        inv = await ctx.data.invoices.get(b["invoice_id"])
        if inv and inv["totals"]["total"] > 0:
            await issue(ctx, inv)
            has_invoice = True
    status = "sent" if f["status"] in ("draft", "scheduled") else f["status"]
    if asked_again and status == "completed":
        status = "sent"
    await ctx.data.client_files.update({"_id": f["_id"]}, {"version": version, "status": status, "sent_at": f.get("sent_at") or now(),
                                                           "last_sent_at": now(), "completed_at": None if asked_again else f.get("completed_at")})
    link = f"{client_base(ws)}/f/{f['token']}"
    vals = await build(ctx, pr, c)
    first_send = version == 1
    if p.channel != "link" and (first_send or p.notify_client):
        intro = p.message.strip() or (f"Here is {f['title'].lower() if f['title'] else 'your document'} from {vals['practice.name']}."
                                      if first_send else "I've updated the document. Here's what changed:")
        html = f"<p>Hi {vals['client.first_name']},</p><p>{intro}</p>"
        if not first_send:
            html += "<ul>" + "".join(f"<li>{x}</li>" for x in changes) + "</ul>"
        if p.channel in ("email", "both") and c.get("email"):
            await send_message(ctx, pr["_id"], c, "email", p.subject or f["title"], html, button=("Open", link), kind="file")
        if p.channel in ("whatsapp", "both") and c.get("phone"):
            await send_message(ctx, pr["_id"], c, "whatsapp", wa_template="file_link",
                               wa_params=[vals["client.first_name"], vals["practice.name"], link], kind="file")
    await ctx.data.file_events.insert({"file_id": f["_id"], "type": "sent", "version": version, "at": now()})
    await log(ctx, pr["_id"], "file", f"{'Sent' if first_send else 'Resent'} \"{f['title']}\" (version {version})", ref=f["_id"],
              client_visible=True, meta={"changes": changes})
    await emit(ctx, "file.sent", {"file_id": f["_id"], "version": version, "has_contract": has_contract, "has_invoice": has_invoice,
                                  "resend": not first_send}, pr["_id"])
    return {"ok": True, "version": version, "link": link, "changes": changes}


@action("files.send", "external", SendIn, desc="Send (or resend) a client file by email/WhatsApp. Each send is a new version.")
async def files_send(ctx, p: SendIn):
    f = await get_file(ctx, p.id, act=True)
    if p.schedule_at and aware(p.schedule_at) > now():
        issues = await send_issues(ctx, f)
        if issues:
            raise AppError("not_ready", issues[0], 400, {"issues": issues})
        await ctx.data.client_files.update({"_id": f["_id"]}, {"status": "scheduled" if f["status"] == "draft" else f["status"],
                                                               "scheduled_send": dict(p.model_dump(), schedule_at=aware(p.schedule_at),
                                                                                      user_id=ctx.user_id)})
        await log(ctx, f["project_id"], "file", f"\"{f['title']}\" scheduled to send {fmt_dt(p.schedule_at)}", ref=f["_id"])
        return {"ok": True, "scheduled": True}
    return await do_send(ctx, f, p)


@action("files.status", "read", IdIn,
        desc="Tracking for a client file: sent, viewed, pages reached, completed.")
async def files_status(ctx, p):
    f = await get_file(ctx, p.id)
    ev = await ctx.data.file_events.find({"file_id": f["_id"]}, sort=[("at", 1)])
    sigs = await ctx.data.signatures.find({"file_id": f["_id"], "status": "active"})
    return {"status": f["status"], "version": f.get("version"), "views": sum(1 for e in ev if e["type"] == "viewed"),
            "last_viewed": clean(ev[-1])["at"] if ev else None, "furthest_page": f.get("progress", 0),
            "signed_by": [s["name"] for s in sigs], "completed_at": clean(f).get("completed_at")}


@action("files.list", "read", FileListIn,
        desc="Recent client files.")
async def files_list(ctx, p):
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    f = {"project_id": {"$in": vis}}
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    rows = await ctx.data.client_files.find(f, sort=[("updated_at", -1)], limit=100, projection={"pages": 0})
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": [r["project_id"] for r in rows]}})}
    return [dict(clean(r), project_name=names.get(r["project_id"], "")) for r in rows]


@action("files.mark_complete", "internal", IdIn, desc="Mark a client file complete by hand.")
async def files_mark_complete(ctx, p):
    f = await get_file(ctx, p.id, act=True)
    await mark_completed(ctx, f, by_hand=True)
    return {"ok": True}


@action("files.reopen", "internal", IdIn, desc="Reopen a completed client file so the client can change their answers.")
async def files_reopen(ctx, p):
    f = await get_file(ctx, p.id, act=True)
    if f["status"] != "completed":
        raise AppError("invalid", "This file isn't completed, so there's nothing to reopen.", 400)
    await ctx.data.client_files.update({"_id": f["_id"]}, {"status": "viewed", "reopened": True, "completed_at": None})
    await ctx.data.file_events.insert({"file_id": f["_id"], "type": "reopened", "at": now()})
    await log(ctx, f["project_id"], "file", f"\"{f['title']}\" reopened for changes", ref=f["_id"], client_visible=True)
    return {"ok": True}


async def mark_completed(ctx, f, by_hand=False):
    if f["status"] == "completed":
        return
    await ctx.data.client_files.update({"_id": f["_id"]}, {"status": "completed", "completed_at": now()})
    await ctx.data.file_events.insert({"file_id": f["_id"], "type": "completed", "at": now()})
    await log(ctx, f["project_id"], "file", f"\"{f['title']}\" completed{' (marked by hand)' if by_hand else ''}", ref=f["_id"],
              client_visible=True)
    has_q = any(True for _ in blocks_of(f["pages"], "questions"))
    await emit(ctx, "file.completed", {"file_id": f["_id"]}, f["project_id"])
    if has_q:
        await emit(ctx, "questionnaire.submitted", {"file_id": f["_id"]}, f["project_id"])
    await notify(ctx, f"\"{f['title']}\" was completed by the client.", "file", link=f"/projects/{f['project_id']}")


class SaveTplIn(P):
    id: str
    name: str


@action("files.save_as_template", "internal", SaveTplIn, roles=STAFF, desc="Save a client file as a reusable template.")
async def files_save_tpl(ctx, p: SaveTplIn):
    f = await get_file(ctx, p.id)
    pages = copy.deepcopy(f["pages"])
    for _, b in blocks_of(pages):
        if b["type"] == "invoice":
            inv = await ctx.data.invoices.get(b.get("invoice_id")) if b.get("invoice_id") else None
            b["invoice_id"] = None
            if inv:
                b["lines"], b["schedule"] = inv["lines"], [{k: s[k] for k in ("label", "pct", "due", "amount_paise_fixed") if k in s} for s in inv["schedule"]]
        if b["type"] == "contract":
            b["signers"] = []
    t = await ctx.data.templates.insert({"kind": "file", "name": p.name.strip()[:80] or f["title"], "body": {"pages": pages}})
    return clean(t)


class SignIn(P):
    id: str
    block_id: str
    name: str


@action("files.consultant_sign", "external", SignIn, desc="Sign a contract as the consultant (you can pre-sign before the client).")
async def files_consultant_sign(ctx, p: SignIn):
    f = await get_file(ctx, p.id, act=True)
    blk = next((b for _, b in blocks_of(f["pages"], "contract") if b["id"] == p.block_id), None)
    if not blk:
        raise not_found("That contract")
    signer = next((s for s in blk.get("signers", []) if s["role"] == "consultant"), None)
    if not signer:
        raise AppError("invalid", "There is no consultant signature line on this contract.", 400)
    rendered = await render_contract(ctx, f, blk)
    await record_signature(ctx, f, blk, signer, p.name, "typed", None, ip="", device="", otp_verified=False, rendered=rendered)
    return await file_out(ctx, await ctx.data.client_files.get(f["_id"]))


async def record_signature(ctx, f, blk, signer, name, method, image_key, ip, device, otp_verified, rendered, otp_channel=None):
    if not (name or "").strip():
        raise AppError("invalid", "Please type your full name to sign.", 400)
    existing = await ctx.data.signatures.find_one({"file_id": f["_id"], "block_id": blk["id"], "signer_id": signer["id"], "status": "active"})
    if existing:
        return existing
    contact = await ctx.data.contacts.get(signer.get("contact_id")) if signer.get("contact_id") else {}
    t = now()
    sig = await ctx.data.signatures.insert({
        "file_id": f["_id"], "project_id": f["project_id"], "version": f.get("version"), "block_id": blk["id"], "signer_id": signer["id"],
        "role": signer["role"], "name": name.strip()[:120], "phone": (contact or {}).get("phone"), "email": (contact or {}).get("email"),
        "otp_verified": otp_verified, "otp_channel": otp_channel, "ip": ip, "device": (device or "")[:300], "signed_at": t,
        "signed_at_ist": fmt_dt(t), "doc_hash": contract_hash(rendered), "method": method, "image_key": image_key, "status": "active"})
    await log(ctx, f["project_id"], "signature", f"Contract signed by {sig['name']} ({signer['role']})", ref=sig["_id"], client_visible=True)
    await emit(ctx, "contract.signed", {"file_id": f["_id"], "block_id": blk["id"], "signer": signer["role"]}, f["project_id"])
    await check_fully_signed(ctx, f, blk, rendered)
    return sig


async def check_fully_signed(ctx, f, blk, rendered):
    sigs = await ctx.data.signatures.find({"file_id": f["_id"], "block_id": blk["id"], "status": "active"})
    signed = {s["signer_id"] for s in sigs}
    need = {s["id"] for s in blk.get("signers", []) if s.get("required", True)}
    if not need <= signed:
        return False
    from app.domain.sales.crm import set_booked
    await set_booked(ctx, f["project_id"], "contract signed")
    await ctx.data.client_files.update({"_id": f["_id"]}, {f"signed_blocks.{blk['id']}": now()})
    # Final PDF with the audit page, stored on the project and sent to every signer.
    try:
        from app.integrations import vendors
        from app.services.pdf import contract_pdf
        ws = await ctx.ws()
        imgs = []
        for s in sigs:
            d = dict(s)
            if s.get("image_key"):
                import base64
                try:
                    raw = await vendors.storage_get(s["image_key"])
                    d["image"] = "data:image/png;base64," + base64.b64encode(raw).decode()
                except Exception:
                    d["image"] = None
            d["signed_at"] = aware(s["signed_at"])
            imgs.append(d)
        pdf = await contract_pdf(ws["profile"].get("practice_name") or ws["name"], f["title"], rendered, imgs, contract_hash(rendered))
        key = await vendors.storage_put(ctx.ws_id, "signed-contract.pdf", pdf, "application/pdf")
        up = await ctx.data.uploads.insert({"project_id": f["project_id"], "file_id": f["_id"], "name": f"{f['title']} — signed.pdf",
                                            "key": key, "kind": "signed_contract", "size": len(pdf), "client_visible": True,
                                            "token": token(18)})
        await ctx.data.client_files.update({"_id": f["_id"]}, {f"signed_pdf.{blk['id']}": up["_id"]})
        from app.domain.engagement.inbox import send_message
        c = await ctx.data.contacts.get(next((s.get("contact_id") for s in blk["signers"] if s["role"] == "client"), None) or "")
        link = f"{client_base(ws)}/d/{up['token']}"
        if c and c.get("email"):
            await send_message(ctx, f["project_id"], c, "email", f"Signed copy: {f['title']}",
                               "<p>Thank you for signing. Your signed copy, with the signing record, is ready to download.</p>",
                               button=("Download signed copy", link), kind="signed_copy", idem_key=f"signed:{f['_id']}:{blk['id']}")
        await notify(ctx, f"\"{f['title']}\" is fully signed. The signed PDF is on the project.", "contract", link=f"/projects/{f['project_id']}")
    except Exception as e:  # PDF problems must never block the signature itself
        await log(ctx, f["project_id"], "error", f"Signed PDF could not be made: {e}")
    await emit(ctx, "contract.fully_signed", {"file_id": f["_id"], "block_id": blk["id"]}, f["project_id"])
    from app.domain.engagement.scheduling import confirm_held_for_file
    await confirm_held_for_file(ctx, f["_id"], "sign")
    return True


class ProjectFiles(P):
    project_id: str


@action("contracts.status", "read", ProjectFiles, desc="Contract signing status for a project's files.")
async def contracts_status(ctx, p: ProjectFiles):
    await perm.project(ctx, p.project_id)
    out = []
    for f in await ctx.data.client_files.find({"project_id": p.project_id}):
        for _, b in blocks_of(f["pages"], "contract"):
            sigs = await ctx.data.signatures.find({"file_id": f["_id"], "block_id": b["id"], "status": "active"})
            out.append({"file_id": f["_id"], "file": f["title"], "block_id": b["id"], "status": f["status"],
                        "signed": [{"name": s["name"], "role": s["role"], "at": clean(s)["signed_at"]} for s in sigs],
                        "waiting_for": [s["role"] for s in b.get("signers", []) if s["id"] not in {x["signer_id"] for x in sigs}]})
    return out


@action("contracts.remind", "external", RemindIn,
        desc="Remind the client to sign a contract.")
async def contracts_remind(ctx, p):
    f = await get_file(ctx, p.file_id, act=True)
    if f["status"] == "draft":
        raise AppError("not_sent", "Send the file first.", 400)
    from app.domain.engagement.inbox import contact_for, send_message
    pr = await ctx.data.projects.get(f["project_id"])
    c = await contact_for(ctx, pr)
    ws = await ctx.ws()
    link = f"{client_base(ws)}/f/{f['token']}"
    ch = "email" if c.get("email") else "whatsapp"
    if ch == "email":
        await send_message(ctx, pr["_id"], c, "email", f"Ready to sign: {f['title']}",
                           f"<p>Hi {c.get('first_name') or c['name']}, a quick reminder that \"{f['title']}\" is ready for your signature.</p>",
                           button=("Review and sign", link), kind="contract_reminder")
    else:
        await send_message(ctx, pr["_id"], c, "whatsapp", wa_template="file_link",
                           wa_params=[c.get("first_name") or c["name"], ws["name"], link], kind="contract_reminder")
    return {"ok": True}


# ---------------- templates ----------------

class TplList(P):
    kind: Optional[str] = None


@action("templates.list", "read", TplList, desc="My templates (client files, contracts, emails, questionnaires, invoices).")
async def templates_list(ctx, p: TplList):
    f = {"kind": p.kind} if p.kind else {}
    return [dict(clean(t), body=None if t["kind"] == "file" else t["body"]) for t in await ctx.data.templates.find(f, sort=[("name", 1)])]


@action("templates.get", "read", IdIn, desc="One template with its content.")
async def templates_get(ctx, p):
    t = await ctx.data.templates.get(p.id)
    if not t:
        raise not_found("That template")
    return clean(t)


class TplSave(P):
    id: Optional[str] = None
    kind: str
    name: str
    body: dict


@action("templates.save", "internal", TplSave, roles=STAFF, desc="Create or update a template.")
async def templates_save(ctx, p: TplSave):
    if p.kind not in ("file", "contract", "questionnaire", "invoice", "email", "package", "automation", "whatsapp"):
        raise AppError("invalid", "Unknown template kind.", 400)
    if p.kind == "file":
        validate_pages(p.body.get("pages", []))
    doc = {"kind": p.kind, "name": p.name.strip()[:80] or "Untitled", "body": p.body}
    if p.id:
        await ctx.data.templates.update({"_id": p.id}, doc)
        return clean(await ctx.data.templates.get(p.id))
    return clean(await ctx.data.templates.insert(doc))


@action("templates.delete", "destructive", IdIn, roles=STAFF, agent_ok=False,
        desc="Delete a template.")
async def templates_delete(ctx, p):
    await ctx.data.templates.soft_delete({"_id": p.id})
    return {"ok": True}


@action("templates.gallery", "read", desc="The starter gallery of consulting templates.")
async def templates_gallery(ctx, p):
    from app.domain.documents.defaults import gallery
    return [{"key": g["key"], "kind": g["kind"], "name": g["name"]} for g in gallery()]


@action("templates.install", "internal", KeyIn, roles=STAFF,
        desc="Copy a gallery template into my templates.")
async def templates_install(ctx, p):
    from app.domain.documents.defaults import gallery
    g = next((x for x in gallery() if x["key"] == p.key), None)
    if not g:
        raise not_found("That gallery template")
    return clean(await ctx.data.templates.insert({"kind": g["kind"], "name": g["name"], "body": g["body"], "gallery_key": g["key"]}))


_ = (ADMINS, compute, due_dates)
