"""Client-facing API. No consultant login here.

- Client files, invoices and downloads open by a long random token in the link.
- Signing asks for an OTP. Paying is "I've paid" (the consultant confirms).
- The portal logs a client in by OTP or magic link.
Client text (answers, messages, uploads) is stored as data and never treated as
instructions by any agent.
"""
import base64
import hashlib
import logging
import random
import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import Response as RawResponse

from app.integrations import vendors
from app.domain.documents import files as F
from app.domain.billing import money as M
from app.domain.sales.forms import submit as form_submit
from app.domain.engagement.inbox import receive
from app.domain.documents.merge import build, client_base, fill, session_values
from app.domain.engagement.portal import client_project, client_projects
from app.domain.engagement.scheduling import book, cancel_session, extend_hold_after_claim, find_slots, get_type
from app.api.deps import client_ip
from app.auth import check_otp, issue_otp, norm_phone
from app.services.uploads import data_url_to_key, mime_of  # noqa: F401  (data_url_to_key re-exported)
from app.core import limits, settings
from app.core.context import system_ctx
from app.db import get_db
from app.core.events import emit, log, notify
from app.core.util import AppError, aware, clean, fmt_dt, inr, new_id, not_found, now, token

async def verify_hook(request: Request):
    """Inbound webhooks must carry the shared secret (query ?secret= or X-Hook-Secret header).
    Without it anyone could post fake client replies, e.g. 'done' to close a client's tasks."""
    from app.core.security import secrets_equal
    if not settings.HOOK_SECRET:
        if settings.QA_MODE:
            return
        raise AppError("forbidden", "Webhooks are not configured.", 403)
    got = request.headers.get("x-hook-secret") or request.query_params.get("secret") or ""
    if not secrets_equal(got, settings.HOOK_SECRET):
        raise AppError("forbidden", "Not allowed.", 401)


router = APIRouter(prefix="/api/public")
hooks = APIRouter(prefix="/api/hooks", dependencies=[Depends(verify_hook)])


def cctx(ws_id):
    return system_ctx(ws_id, actor="client", via="public")


ip_of = client_ip


async def ws_by_slug(slug):
    ws = await get_db().workspaces.find_one({"slug": slug})
    if not ws:
        raise not_found("That page")
    return ws


async def brand_of(ws):
    th = ws.get("theme", {})
    lim = await limits.value(ws["_id"], "powered_by_hidden", ws.get("created_at"))
    return {"name": ws.get("profile", {}).get("practice_name") or ws["name"], "slug": ws["slug"], "theme": th,
            "logo_url": f"/api/public/logo/{ws['slug']}" if th.get("logo_key") else None,
            "consultant": ws.get("profile", {}).get("consultant_name"), "powered_by": None if lim else settings.BRAND_NAME,
            "contact": {k: ws.get("profile", {}).get(k) for k in ("email", "phone", "website")}}


@router.get("/brand/{slug}")
async def brand(slug: str):
    return await brand_of(await ws_by_slug(slug))


@router.get("/logo/{slug}")
async def logo(slug: str):
    ws = await ws_by_slug(slug)
    key = ws.get("theme", {}).get("logo_key")
    if not key:
        raise not_found("That logo")
    data = await vendors.storage_get(key)
    return RawResponse(data, media_type=mime_of(key, "image/jpeg"), headers={"Cache-Control": "public, max-age=300"})


# ---------------- lead forms ----------------

async def form_by(ws, slug):
    f = await get_db().lead_forms.find_one({"workspace_id": ws["_id"], "slug": slug, "deleted_at": None})
    if not f or not f.get("live"):
        raise not_found("That form")
    return f


@router.get("/{ws_slug}/form/{slug}")
async def form_get(ws_slug: str, slug: str):
    ws = await ws_by_slug(ws_slug)
    f = await form_by(ws, slug)
    out = {"form": {k: f.get(k) for k in ("_id", "name", "kind", "blocks", "thank_you", "price_paise", "promo_enabled", "otp_required")},
           "brand": await brand_of(ws)}
    out["form"]["id"] = out["form"].pop("_id")
    return out


@router.post("/{ws_slug}/form/{slug}/event")
async def form_event(ws_slug: str, slug: str, body: dict, request: Request):
    ws = await ws_by_slug(ws_slug)
    f = await form_by(ws, slug)
    if body.get("kind") in ("view", "start"):
        await cctx(ws["_id"]).data.form_events.insert({"form_id": f["_id"], "kind": body["kind"], "source": (body.get("source") or "Direct")[:40],
                                                       "ip": ip_of(request), "at": now()})
    return {"ok": True}


@router.post("/{ws_slug}/form/{slug}/submit")
async def form_post(ws_slug: str, slug: str, body: dict, request: Request):
    ws = await ws_by_slug(ws_slug)
    return await form_submit(cctx(ws["_id"]), await form_by(ws, slug), body, ip_of(request))


@router.post("/{ws_slug}/otp")
async def public_otp(ws_slug: str, body: dict, request: Request):
    """OTP for forms that ask for it and for the client portal."""
    await ws_by_slug(ws_slug)
    phone = norm_phone(body.get("phone", ""))
    return await send_code(phone, ip_of(request))


async def send_code(key, ip):
    """Phone or email code for clients. Same rate limits as consultant login."""
    return await issue_otp(key, ip)


# ---------------- booking pages ----------------

@router.get("/{ws_slug}/book/{type_slug}")
async def booking_get(ws_slug: str, type_slug: str):
    ws = await ws_by_slug(ws_slug)
    ctx = cctx(ws["_id"])
    st = await get_type(ctx, type_slug)
    if not st.get("active", True):
        raise not_found("That booking page")
    return {"type": {k: st.get(k) for k in ("name", "duration", "format", "questions", "price_paise", "max_attendees")} | {"id": st["_id"]},
            "brand": await brand_of(ws)}


@router.get("/{ws_slug}/book/{type_slug}/slots")
async def booking_slots(ws_slug: str, type_slug: str, date_from: str, date_to: str = None):
    ws = await ws_by_slug(ws_slug)
    ctx = cctx(ws["_id"])
    st = await get_type(ctx, type_slug)
    a = aware(date_from)
    b = aware(date_to) if date_to else a + timedelta(days=7)
    return [s.isoformat() for s in await find_slots(ctx, st, a, min(b, a + timedelta(days=31)))]


@router.post("/{ws_slug}/book/{type_slug}")
async def booking_post(ws_slug: str, type_slug: str, body: dict, request: Request):
    from app.domain.sales.crm import upsert_contact
    ws = await ws_by_slug(ws_slug)
    ctx = cctx(ws["_id"])
    st = await get_type(ctx, type_slug)
    c = body.get("contact") or {}
    if not (c.get("name") or "").strip() or not (c.get("email") or c.get("phone")):
        raise AppError("invalid", "Please add your name and a mobile number or email.", 400)
    contact, _ = await upsert_contact(ctx, {"name": c["name"], "phone": c.get("phone"), "email": c.get("email"), "source": "Booking page"})
    for q in st.get("questions", []):
        if q.get("required") and not str((body.get("answers") or {}).get(q["id"], "")).strip():
            raise AppError("invalid", f"Please answer: {q['label']}", 400)
    s = await book(ctx, st, body.get("start"), contact, None, body.get("answers"))
    return {"ok": True, "session": {"start": s["start"].isoformat(), "end": s["end"].isoformat(), "meet_link": s.get("meet_link"),
                                    "label": fmt_dt(s["start"])}}


# ---------------- client file viewer ----------------

async def file_by_token(tok):
    f = await get_db().client_files.find_one({"token": tok, "deleted_at": None})
    if not f or f["status"] == "draft" and not f.get("version"):
        raise not_found("That document")
    return f, cctx(f["workspace_id"])


async def live_pages(ctx, f):
    v = await ctx.data.file_versions.find_one({"file_id": f["_id"]}, sort=[("version", -1)])
    if not v:
        raise not_found("That document")
    return v


def client_signer(blk):
    return next((s for s in blk.get("signers", []) if s["role"] == "client"), None)


async def render_file(ctx, f, preview_pages=None):
    """What the client sees, page by page, with gating and what's missing."""
    ws = await ctx.ws()
    pr = await ctx.data.projects.get(f["project_id"])
    contact = await ctx.data.contacts.get((pr.get("contact_ids") or [""])[0]) if pr.get("contact_ids") else {}
    if preview_pages is not None:
        pages, version, changes = preview_pages, f.get("version") or 0, []
    else:
        v = await live_pages(ctx, f)
        pages, version, changes = v["pages"], v["version"], v.get("changes", [])
    vals = await F.contract_values(ctx, f, pr, pages, contact)
    sigs = await ctx.data.signatures.find({"file_id": f["_id"], "status": "active"})
    out_pages, gate_open = [], True
    completed = f["status"] == "completed"
    for i, pg in enumerate(pages):
        blocks, missing = [], []
        has_invoice = any(b["type"] == "invoice" for b in pg["blocks"])
        locked = (not gate_open) and has_invoice
        for b in pg["blocks"]:
            o = {"id": b["id"], "type": b["type"]}
            t = b["type"]
            if t in ("text", "thankyou"):
                o["html"] = fill(b.get("html", ""), vals)
                o["redirect_url"] = b.get("redirect_url")
            elif t in ("image", "video"):
                o.update({k: b.get(k) for k in ("url", "key", "focal", "caption")})
                if b.get("key"):
                    o["url"] = f"/api/public/asset/{f['token']}/{b['id']}"
            elif t == "company":
                o.update({"name": vals["practice.name"], "consultant": vals["consultant.name"], "contact": (await brand_of(ws))["contact"]})
            elif t in ("divider", "spacer", "timeline"):
                o["items"] = b.get("items", [])
            elif t == "questions":
                o["questions"] = b.get("questions", [])
                o["answers"] = {q["id"]: f.get("answers", {}).get(q["id"]) for q in b.get("questions", [])}
                o["locked"] = completed and not f.get("reopened")
                for q in b.get("questions", []):
                    if q.get("required") and not str(f.get("answers", {}).get(q["id"]) or "").strip():
                        missing.append(f"Answer: {q['label']}")
            elif t == "services":
                o.update({"items": b.get("items", []), "select": b.get("select", "single"), "selection": f.get("selections", {}).get(b["id"], {})})
                if b.get("required", True) and not o["selection"]:
                    missing.append("Choose an option")
            elif t == "contract":
                rendered = fill(b.get("html", ""), vals, True, b.get("fields"))
                me = client_signer(b)
                done = {s["signer_id"]: s for s in sigs if s["block_id"] == b["id"]}
                o.update({"html": rendered, "fields": [x for x in b.get("fields", []) if x.get("permission") != "consultant"],
                          "signers": [{"id": s["id"], "role": s["role"], "signed": s["id"] in done,
                                       "name": done[s["id"]]["name"] if s["id"] in done else None,
                                       "at": fmt_dt(done[s["id"]]["signed_at"]) if s["id"] in done else None} for s in b.get("signers", [])],
                          "my_signer_id": me["id"] if me else None, "required": b.get("required", True)})
                if b.get("required", True) and me and me["id"] not in done:
                    missing.append("Sign the agreement")
                    gate_open = False
            elif t == "invoice":
                inv = await ctx.data.invoices.get(b.get("invoice_id")) if b.get("invoice_id") else None
                if inv:
                    o["invoice"] = await M.view(ctx, inv, for_client=True)
                    first = next((s for s in inv["schedule"] if s["status"] != "paid"), None)
                    if b.get("required", True) and inv["status"] not in ("paid",) and first and first["status"] not in ("processing", "paid") \
                            and not any(s["status"] in ("processing", "paid") for s in inv["schedule"]):
                        missing.append("Pay the first amount (or tap \"I've paid\")")
                o["locked"] = locked
            elif t == "scheduler":
                st = await ctx.data.session_types.get(b.get("session_type_id")) if b.get("session_type_id") else None
                s = await ctx.data.sessions.find_one({"file_id": f["_id"], "status": {"$in": ["held", "booked"]}})
                o.update({"session_type": {"id": st["_id"], "name": st["name"], "duration": st["duration"]} if st else None,
                          "session": {"start": aware(s["start"]).isoformat(), "status": s["status"], "label": fmt_dt(s["start"]),
                                      "meet_link": s.get("meet_link")} if s else None,
                          "reserve_requires": b.get("reserve_requires", [])})
                if b.get("required", True) and not s:
                    missing.append("Pick a time")
            elif t == "quote":
                # Only what the client may see: scope lines and prices. Never cost or margin.
                today_s = now().astimezone(__import__("app.core.util", fromlist=["IST"]).IST).date().isoformat()
                o.update({"items": [{k: i.get(k) for k in ("label", "qty", "unit", "price_paise")} for i in b.get("items", [])],
                          "total_paise": b.get("total_paise", 0), "valid_until": b.get("valid_until"),
                          "valid_label": fmt_date_s(b.get("valid_until")), "accepted": bool(f.get("accepted_at")),
                          "expired": bool(b.get("valid_until") and b["valid_until"] < today_s and not f.get("accepted_at")),
                          "pdf": f"/api/public/f/{f['token']}/quote.pdf"})
            elif t == "retainer":
                o.update({k: b.get(k) for k in ("name", "kind", "period", "fee_paise", "included_hours", "billing", "cap_paise")})
                ro, ov = b.get("rollover") or {}, b.get("overage") or {}
                o["terms"] = [x for x in (
                    {"none": "Unused hours lapse at the end of each period.",
                     "capped": f"Up to {ro.get('cap_hours', 'some')} unused hours carry into the next period.",
                     "all": "Unused hours carry forward."}.get(ro.get("mode")),
                    {"bill": "Extra time is billed at the standard hourly rate.", "borrow": "Extra time comes out of the next period.",
                     "absorb": "Extra time isn't billed.", "ask": "Extra time is billed only after we agree it."}.get(ov.get("mode"))) if x]
            blocks.append(o)
        out_pages.append({"id": pg["id"], "title": pg.get("title"), "button": pg.get("button") or "Continue", "blocks": blocks,
                          "missing": missing, "locked": locked,
                          "locked_reason": "Sign the agreement first to open the payment page." if locked else None})
    return {"title": f["title"], "status": f["status"], "version": version, "changes": changes if version > 1 else [],
            "pages": out_pages, "progress": f.get("progress", 0), "brand": await brand_of(ws),
            "client": {"name": (contact or {}).get("name"), "first_name": (contact or {}).get("first_name"),
                       "has_phone": bool((contact or {}).get("phone")), "has_email": bool((contact or {}).get("email"))},
            "portal_url": f"{client_base(ws)}/portal" if pr.get("portal_link_on", True) else None}


@router.get("/f/{tok}")
async def file_view(tok: str, request: Request, track: int = 1):
    f, ctx = await file_by_token(tok)
    if track:
        await ctx.data.file_events.insert({"file_id": f["_id"], "type": "viewed", "at": now(), "ip": ip_of(request)})
        await ctx.data.client_files.update({"_id": f["_id"]}, {}, raw={"$inc": {"viewed_count": 1}})
        if f["status"] == "sent":
            await ctx.data.client_files.update({"_id": f["_id"]}, {"status": "viewed", "first_viewed_at": now()})
            await log(ctx, f["project_id"], "file", f"Client opened \"{f['title']}\"", ref=f["_id"])
            await emit(ctx, "file.viewed", {"file_id": f["_id"]}, f["project_id"])
            await notify(ctx, f"Your client opened \"{f['title']}\".", "file", link=f"/projects/{f['project_id']}")
            await get_db().messages.update_many({"workspace_id": f["workspace_id"], "project_id": f["project_id"], "kind": "file",
                                                 "status": {"$in": ["sent", "delivered"]}}, {"$set": {"status": "opened"}})
            f["status"] = "viewed"
    return await render_file(ctx, f)


@router.post("/f/{tok}/page")
async def file_page(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    i = int(body.get("index", 0))
    await ctx.data.file_events.insert({"file_id": f["_id"], "type": "page", "page": i, "at": now()})
    if i > f.get("progress", 0):
        await ctx.data.client_files.update({"_id": f["_id"]}, {"progress": i})
    return {"ok": True}


def _block(pages, bid, typ):
    b = next((b for _, b in F.blocks_of(pages, typ) if b["id"] == bid), None)
    if not b:
        raise not_found("That part of the document")
    return b


@router.post("/f/{tok}/answers")
async def file_answers(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    if f["status"] == "completed" and not f.get("reopened"):
        raise AppError("locked", "This form was already submitted. Ask for it to be reopened to make changes.", 409)
    v = await live_pages(ctx, f)
    b = _block(v["pages"], body.get("block_id"), "questions")
    ans = dict(f.get("answers", {}))
    qs = {q["id"]: q for q in b.get("questions", [])}
    for k, val in (body.get("answers") or {}).items():
        if k not in qs:
            continue
        q = qs[k]
        if q["kind"] == "file" and isinstance(val, str) and val.startswith("data:"):
            key = await data_url_to_key(ctx.ws_id, val, "answer")
            up = await ctx.data.uploads.insert({"project_id": f["project_id"], "name": f"{q['label']}", "key": key, "kind": "client_upload",
                                                "client_visible": True, "by_client": True, "token": token(18)})
            val = {"upload_id": up["_id"], "name": q["label"]}
        elif isinstance(val, str):
            val = val[:5000]
        if q["kind"] == "number" and val not in (None, ""):
            try:
                float(val)
            except Exception:
                raise AppError("invalid", f"\"{q['label']}\" needs a number.", 400)
        ans[k] = val
        if q.get("maps_to") and isinstance(val, str):
            obj, _, field = q["maps_to"].partition(".")
            pr = await ctx.data.projects.get(f["project_id"])
            if obj == "contact" and field in ("company", "email", "role") and pr.get("contact_ids"):
                await ctx.data.contacts.update({"_id": pr["contact_ids"][0]}, {field: val})
            elif obj == "project":
                await ctx.data.projects.update({"_id": pr["_id"]}, {f"custom.{field}": val})
    await ctx.data.client_files.update({"_id": f["_id"]}, {"answers": ans})
    return {"ok": True}


@router.post("/f/{tok}/select")
async def file_select(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    v = await live_pages(ctx, f)
    b = _block(v["pages"], body.get("block_id"), "services")
    items = {i["id"]: i for i in b.get("items", [])}
    picks = {k: max(1, min(int(q or 1), 100)) for k, q in (body.get("picks") or {}).items() if k in items}
    if b.get("select", "single") == "single":
        pk = [k for k in picks if items[k].get("kind", "package") == "package"]
        if len(pk) > 1:
            picks = {k: q for k, q in picks.items() if k == pk[-1] or items[k].get("kind") == "addon"}
    sels = dict(f.get("selections", {}))
    sels[b["id"]] = picks
    await ctx.data.client_files.update({"_id": f["_id"]}, {"selections": sels})
    if b.get("feeds_invoice", True):
        for _, ib in F.blocks_of(v["pages"], "invoice"):
            inv = await ctx.data.invoices.get(ib.get("invoice_id"))
            if inv and not M.has_payments(inv) and not any(s["status"] == "processing" for s in inv["schedule"]):
                inv["lines"] = [{"id": k, "name": items[k]["name"], "desc": items[k].get("desc", ""), "qty": q,
                                 "price_paise": items[k].get("price_paise", 0)} for k, q in picks.items()]
                await M.save_invoice(ctx, inv)
                if inv["status"] == "draft" and inv["totals"]["total"] > 0:
                    await M.issue(ctx, inv)  # the invoice becomes real once the client has chosen
    return {"ok": True}


@router.post("/f/{tok}/plan")
async def file_plan(tok: str, body: dict):
    """Client chooses pay in full or split into N monthly payments (when allowed)."""
    f, ctx = await file_by_token(tok)
    inv = await ctx.data.invoices.get(body.get("invoice_id"))
    if not inv or inv.get("file_id") != f["_id"]:
        raise not_found("That invoice")
    if not (inv.get("client_choice") or {}).get("allowed"):
        raise AppError("invalid", "This invoice can't be split.", 400)
    if M.has_payments(inv) or any(s["status"] == "processing" for s in inv["schedule"]):
        raise AppError("locked", "The plan can't change after a payment.", 409)
    n = 1 if body.get("plan") == "full" else max(2, min(int(body.get("months", 3)), int(inv["client_choice"].get("months", 3))))
    base = 100 // n
    inv["schedule"] = [{"id": new_id()[:8], "label": "Full payment" if n == 1 else f"Payment {i + 1} of {n}",
                        "pct": base + (100 - base * n if i == n - 1 else 0),
                        "due": {"type": "on_signing"} if i == 0 else {"type": "after_previous", "days": 30}} for i in range(n)]
    await M.save_invoice(ctx, inv)
    return {"ok": True}


@router.post("/f/{tok}/promo")
async def file_promo(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    inv = await ctx.data.invoices.get(body.get("invoice_id"))
    if not inv or inv.get("file_id") != f["_id"]:
        raise not_found("That invoice")
    await M.apply_promo(ctx, inv, body.get("code", ""))
    return {"ok": True}


@router.post("/f/{tok}/otp")
async def file_otp(tok: str, request: Request):
    f, ctx = await file_by_token(tok)
    pr = await ctx.data.projects.get(f["project_id"])
    c = await ctx.data.contacts.get((pr.get("contact_ids") or [""])[0])
    if not c or not (c.get("phone") or c.get("email")):
        raise AppError("no_contact", "We need your mobile number or email to send a code.", 400)
    return await send_code(c.get("phone") or c["email"], ip_of(request))


@router.post("/f/{tok}/sign")
async def file_sign(tok: str, body: dict, request: Request):
    f, ctx = await file_by_token(tok)
    v = await live_pages(ctx, f)
    b = _block(v["pages"], body.get("block_id"), "contract")
    me = client_signer(b)
    if not me or body.get("signer_id") not in (None, me["id"]):
        raise AppError("forbidden", "This signature line isn't yours.", 403)
    # Client-fill fields must be filled before signing.
    fields = b.get("fields", [])
    given = body.get("fields") or {}
    for fld in fields:
        if fld.get("permission") in ("client_must_fill", "client_edit") and fld["key"] in given:
            fld["value"] = str(given[fld["key"]])[:300]
        if fld.get("permission") == "client_must_fill" and not (fld.get("value") or "").strip():
            raise AppError("invalid", f"Please fill in \"{fld['label']}\" before signing.", 400)
    if given:
        f_full = await ctx.data.client_files.get(f["_id"])
        for _, wb in F.blocks_of(f_full["pages"], "contract"):
            if wb["id"] == b["id"]:
                wb["fields"] = fields
        await ctx.data.client_files.update({"_id": f["_id"]}, {"pages": f_full["pages"]})
        await ctx.data.file_versions.update({"_id": v["_id"]}, {"pages": v["pages"]})
    pr = await ctx.data.projects.get(f["project_id"])
    c = await ctx.data.contacts.get(me.get("contact_id") or (pr.get("contact_ids") or [""])[0])
    key = (c or {}).get("phone") or (c or {}).get("email")
    if not key:
        raise AppError("no_contact", "We need your mobile number or email to verify your signature.", 400)
    await check_otp(key, str(body.get("code", "")))
    img = await data_url_to_key(ctx.ws_id, body.get("image"), "signature") if body.get("method") == "drawn" else None
    rendered = fill(b.get("html", ""), await F.contract_values(ctx, f, pr, v["pages"], c), True, fields)
    await F.record_signature(ctx, f, b, me, body.get("name", ""), body.get("method", "typed"), img, ip_of(request),
                             request.headers.get("user-agent", ""), True, rendered, "whatsapp" if "@" not in key else "email")
    return {"ok": True}


@router.get("/f/{tok}/slots")
async def file_slots(tok: str, block_id: str, date_from: str, date_to: str = None):
    f, ctx = await file_by_token(tok)
    v = await live_pages(ctx, f)
    b = _block(v["pages"], block_id, "scheduler")
    st = await get_type(ctx, b["session_type_id"])
    a = aware(date_from)
    return [s.isoformat() for s in await find_slots(ctx, st, a, aware(date_to) if date_to else a + timedelta(days=7))]


@router.post("/f/{tok}/book")
async def file_book(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    v = await live_pages(ctx, f)
    b = _block(v["pages"], body.get("block_id"), "scheduler")
    st = await get_type(ctx, b["session_type_id"])
    pr = await ctx.data.projects.get(f["project_id"])
    c = await ctx.data.contacts.get(pr["contact_ids"][0])
    old = await ctx.data.sessions.find_one({"file_id": f["_id"], "status": {"$in": ["held", "booked"]}})
    req = list(b.get("reserve_requires") or [])
    done = []
    if "sign" in req and f.get("signed_blocks"):
        done.append("sign")
    if "pay" in req:
        for _, ib in F.blocks_of(v["pages"], "invoice"):
            inv = await ctx.data.invoices.get(ib.get("invoice_id"))
            if inv and any(s["status"] == "paid" for s in inv["schedule"]):
                done.append("pay")
    hold = bool(set(req) - set(done))
    s = await book(ctx, st, body.get("start"), c, pr["_id"], hold=hold, file_id=f["_id"], reserve_requires=req)
    if done:
        await ctx.data.sessions.update({"_id": s["_id"]}, {"reserve_done": done})
    if old:
        await cancel_session(ctx, old, by="client", tell_client=False)
    return {"ok": True, "status": s["status"], "label": fmt_dt(s["start"])}


async def claim_flow(ctx, inv, body):
    if body.get("method") not in ("upi", "bank"):
        raise AppError("invalid", "Choose UPI or bank transfer.", 400)
    if inv["status"] == "draft":
        if inv["totals"]["total"] <= 0:
            raise AppError("invalid", "Choose a package first.", 400)
        await M.issue(ctx, inv)
    shot = await data_url_to_key(ctx.ws_id, body.get("screenshot"), "payment-proof") if body.get("screenshot") else None
    r = await M.client_claim(ctx, inv, body.get("item_id"), body["method"], str(body.get("reference") or ""), shot)
    if inv.get("file_id"):
        await extend_hold_after_claim(ctx, inv["file_id"])
    ws = await ctx.ws()
    owner = await get_db().users.find_one({"_id": ws["owner_id"]})
    if owner and owner.get("phone") and r.get("claim_id"):
        try:
            await vendors.whatsapp_send(ctx.ws_id, owner["phone"], template="consultant_alert",
                                        params=[f"A client says they paid on {inv.get('number')}. Please confirm in {settings.BRAND_NAME}."])
        except AppError:
            pass
    return r


@router.post("/f/{tok}/claim")
async def file_claim(tok: str, body: dict):
    f, ctx = await file_by_token(tok)
    inv = await ctx.data.invoices.get(body.get("invoice_id"))
    if not inv or inv.get("file_id") != f["_id"]:
        raise not_found("That invoice")
    v = await live_pages(ctx, f)
    if body.get("version") and int(body["version"]) != v["version"]:
        raise AppError("changed", "This document was just updated. Please review the latest version before paying.", 409)
    return await claim_flow(ctx, inv, body)


@router.post("/f/{tok}/complete")
async def file_complete(tok: str):
    f, ctx = await file_by_token(tok)
    if f.get("kind") == "quote":
        # A quote is completed only by accepting it (which also converts the estimate, once).
        return await quote_accept(tok)
    view = await render_file(ctx, f)
    missing = [m for pg in view["pages"] for m in pg["missing"]]
    if missing:
        raise AppError("incomplete", missing[0], 400, {"missing": missing})
    await F.mark_completed(ctx, f)
    if f.get("reopened"):
        await ctx.data.client_files.update({"_id": f["_id"]}, {"reopened": False})
    return {"ok": True}


@router.get("/asset/{tok}/{block_id}")
async def file_asset(tok: str, block_id: str):
    f, ctx = await file_by_token(tok)
    v = await live_pages(ctx, f)
    b = next((b for _, b in F.blocks_of(v["pages"]) if b["id"] == block_id and b.get("key")), None)
    if not b:
        raise not_found("That image")
    return RawResponse(await vendors.storage_get(b["key"]), media_type=mime_of(b["key"], "image/png"))


# ---------------- invoice pages and downloads ----------------

async def invoice_by_token(tok):
    inv = await get_db().invoices.find_one({"token": tok, "deleted_at": None})
    if not inv or inv["status"] in ("draft", "void"):
        raise not_found("That invoice")
    return inv, cctx(inv["workspace_id"])


@router.get("/i/{tok}")
async def invoice_page(tok: str):
    from app.domain.billing.timebill import timesheet_rows
    inv, ctx = await invoice_by_token(tok)
    ws = await ctx.ws()
    pr = await ctx.data.projects.get(inv["project_id"])
    c = await ctx.data.contacts.get(inv.get("contact_id") or "") or {}
    return {"invoice": await M.view(ctx, inv, for_client=True), "brand": await brand_of(ws),
            "client": {"name": c.get("name"), "company": c.get("company")}, "project": pr["name"],
            "consultant": {"gstin": ws["invoice"].get("gstin") if inv["gst"].get("enabled") else None,
                           "address": ws["profile"].get("address")},
            "timesheet": await timesheet_rows(ctx, inv)}


@router.post("/i/{tok}/claim")
async def invoice_claim(tok: str, body: dict):
    inv, ctx = await invoice_by_token(tok)
    return await claim_flow(ctx, inv, body)


@router.get("/i/{tok}/timesheet")
async def invoice_timesheet(tok: str):
    from app.domain.billing.timebill import timesheet_rows
    inv, ctx = await invoice_by_token(tok)
    ts = await timesheet_rows(ctx, inv)
    if not ts:
        raise not_found("That timesheet")
    return ts


@router.get("/i/{tok}/invoice.pdf")
async def invoice_pdf_route(tok: str):
    from app.services.pdf import invoice_pdf
    inv, ctx = await invoice_by_token(tok)
    if inv["status"] == "draft":
        raise not_found("That invoice")
    return RawResponse(await invoice_pdf(ctx, inv), media_type="application/pdf",
                       headers={"Content-Disposition": f"inline; filename=invoice-{(inv.get('number') or '').replace('/', '-')}.pdf"})


@router.post("/f/{tok}/accept")
async def quote_accept(tok: str):
    """The client accepts a quick quote. Once only, however many taps."""
    from app.domain.billing.estimates import accept_quote
    f, ctx = await file_by_token(tok)
    res = await accept_quote(ctx, f)
    ws = await ctx.ws()
    from app.domain.documents.merge import client_base
    if res.get("invoice_token"):
        res["invoice_link"] = f"{client_base(ws)}/i/{res['invoice_token']}"
    return res


@router.get("/f/{tok}/quote.pdf")
async def quote_pdf(tok: str):
    from app.services.pdf import render_pdf
    f, ctx = await file_by_token(tok)
    if f.get("kind") != "quote":
        raise not_found("That quote")
    return RawResponse(await render_pdf(await quote_html(ctx, f)), media_type="application/pdf",
                       headers={"Content-Disposition": "inline; filename=quote.pdf"})


async def quote_html(ctx, f):
    """The quote as the client sees it: scope and price only (never cost or margin)."""
    import html as _h
    ws = await ctx.ws()
    b = next((b for pg in f["pages"] for b in pg["blocks"] if b["type"] == "quote"), None) or {}
    rows = "".join(f"<tr><td>{_h.escape(i['label'])}</td><td class='num'>{inr(i['price_paise'])}</td></tr>" for i in b.get("items", []))
    return (f"<div class='kicker'>{_h.escape(ws['profile'].get('practice_name') or ws['name'])}</div><h2>{_h.escape(f['title'])}</h2>"
            f"<table><tr><th>Scope</th><th class='num'>Price</th></tr>{rows}<tr><td><b>Total</b></td><td class='num'><b>{inr(b.get('total_paise', 0))}</b></td></tr></table>"
            f"<p class='muted'>Valid until {_h.escape(fmt_date_s(b.get('valid_until')))}.</p>")


def fmt_date_s(s):
    from app.core.util import fmt_date
    return fmt_date(s) if s else ""


# ---------------- client tasks (the client's link) ----------------

async def task_by_token(tok):
    from app.core.context import system_ctx
    from app.db import get_db
    t = await get_db().tasks.find_one({"token": tok, "audience": "client", "deleted_at": None})
    if not t:
        raise not_found("That request")
    return t, system_ctx(t["workspace_id"], actor="client", via="public")



@router.get("/t/{tok}")
async def ctask_view(tok: str):
    from app.domain.engagement.client_tasks import public_view
    t, ctx = await task_by_token(tok)
    ws = await ctx.ws()
    return {"task": await public_view(ctx, t), "brand": await brand_of(ws)}


@router.post("/t/{tok}/done")
async def ctask_done(tok: str):
    from app.domain.engagement.client_tasks import complete, public_view
    t, ctx = await task_by_token(tok)
    await complete(ctx, t, by="client")
    return {"task": await public_view(ctx, await ctx.data.tasks.get(t["_id"]))}


@router.post("/t/{tok}/reply")
async def ctask_reply(tok: str, body: dict):
    from app.domain.engagement.client_tasks import public_reply, public_view
    t, ctx = await task_by_token(tok)
    await public_reply(ctx, t, body.get("text"))
    return {"task": await public_view(ctx, await ctx.data.tasks.get(t["_id"]))}


@router.post("/t/{tok}/upload")
async def ctask_upload(tok: str, body: dict):
    from app.domain.engagement.client_tasks import public_upload, public_view
    t, ctx = await task_by_token(tok)
    await public_upload(ctx, t, body.get("name"), body.get("data"))
    return {"task": await public_view(ctx, await ctx.data.tasks.get(t["_id"]))}


@router.get("/i/{tok}/receipt/{item_id}.pdf")
async def receipt_pdf(tok: str, item_id: str):
    from app.services.pdf import render_pdf
    inv, ctx = await invoice_by_token(tok)
    s = next((x for x in inv["schedule"] if x["id"] == item_id and x["status"] == "paid"), None)
    if not s:
        raise not_found("That receipt")
    ws = await ctx.ws()
    c = await ctx.data.contacts.get(inv.get("contact_id") or "") or {}
    from html import escape as _x
    html = (f"<div class='kicker'>{_x(ws['profile'].get('practice_name') or ws['name'])}</div><h2>Payment receipt</h2>"
            f"<p>Received from <b>{_x(c.get('name', ''))}</b> on {fmt_dt(s['paid_at'])}.</p>"
            f"<table><tr><th>Invoice</th><th>For</th><th class='num'>Amount</th></tr><tr><td>{_x(str(inv.get('number') or ''))}</td><td>{_x(s['label'])}</td>"
            f"<td class='num'>{inr(s['paid_paise'])}</td></tr>"
            + (f"<tr><td></td><td>TDS deducted by client</td><td class='num'>{inr(s['tds_paise'])}</td></tr>" if s.get("tds_paise") else "")
            + "</table><p class='muted'>Paid directly to the consultant.</p>")
    return RawResponse(await render_pdf(html), media_type="application/pdf",
                       headers={"Content-Disposition": f"inline; filename=receipt-{(inv.get('number') or '').replace('/', '-')}.pdf"})


@router.get("/d/{tok}")
async def download(tok: str):
    u = await get_db().uploads.find_one({"token": tok, "deleted_at": None})
    if not u or not u.get("client_visible"):
        raise not_found("That file")
    data = await vendors.storage_get(u["key"])
    mt = "application/pdf" if u["key"].endswith(".pdf") else "application/octet-stream"
    return RawResponse(data, media_type=mt, headers={"Content-Disposition": f"inline; filename=\"{u['name']}\""})


# ---------------- client portal ----------------

PORTAL_COOKIE = "pos_client"


async def portal_ctx(request, ws_slug):
    ws = await ws_by_slug(ws_slug)
    tok = request.cookies.get(PORTAL_COOKIE) or request.headers.get("x-client-session")
    s = await get_db().client_sessions.find_one({"token_hash": hashlib.sha256((tok or "-").encode()).hexdigest(), "ws_id": ws["_id"]}) if tok else None
    if not s or aware(s["expires_at"]) < now():
        raise AppError("logged_out", "Please log in to see your projects.", 401)
    return cctx(ws["_id"]), s


async def start_client_session(resp, ws, contact_ids):
    raw = token(32)
    await get_db().client_sessions.insert_one({"_id": new_id(), "ws_id": ws["_id"], "contact_ids": contact_ids,
                                               "token_hash": hashlib.sha256(raw.encode()).hexdigest(), "created_at": now(),
                                               "expires_at": now() + timedelta(days=30)})
    resp.set_cookie(PORTAL_COOKIE, raw, max_age=30 * 86400, httponly=True, samesite="lax", secure=not settings.QA_MODE)
    return raw


@router.post("/{ws_slug}/portal/login")
async def portal_login(ws_slug: str, body: dict, response: Response):
    ws = await ws_by_slug(ws_slug)
    ctx = cctx(ws["_id"])
    key = body.get("phone") or ""
    if "@" in key:
        key = key.strip().lower()
        contacts = await ctx.data.contacts.find({"email": key})
    else:
        key = norm_phone(key)
        contacts = await ctx.data.contacts.find({"phone": key})
    if not contacts:
        raise AppError("not_found", "We couldn't find your projects with that number or email.", 404)
    await check_otp(key, str(body.get("code", "")))
    raw = await start_client_session(response, ws, [c["_id"] for c in contacts])
    return {"ok": True, "session": raw}


@router.post("/{ws_slug}/portal/code")
async def portal_code(ws_slug: str, body: dict, request: Request):
    ws = await ws_by_slug(ws_slug)
    ctx = cctx(ws["_id"])
    key = (body.get("phone") or "").strip()
    if "@" in key:
        key = key.lower()
        found = await ctx.data.contacts.find_one({"email": key})
    else:
        key = norm_phone(key)
        found = await ctx.data.contacts.find_one({"phone": key})
    if not found:
        raise AppError("not_found", "We couldn't find your projects with that number or email.", 404)
    return await send_code(key, ip_of(request))


@router.get("/{ws_slug}/portal/me")
async def portal_me(ws_slug: str, request: Request):
    ctx, s = await portal_ctx(request, ws_slug)
    ws = await ctx.ws()
    cs = await ctx.data.contacts.find({"_id": {"$in": s["contact_ids"]}})
    return {"brand": await brand_of(ws), "name": cs[0]["name"] if cs else "", "projects": await client_projects(ctx, s["contact_ids"])}


@router.get("/{ws_slug}/portal/project/{pid}")
async def portal_project(ws_slug: str, pid: str, request: Request):
    ctx, s = await portal_ctx(request, ws_slug)
    return await client_project(ctx, s["contact_ids"], pid)


@router.post("/{ws_slug}/portal/project/{pid}/message")
async def portal_message(ws_slug: str, pid: str, body: dict, request: Request):
    ctx, s = await portal_ctx(request, ws_slug)
    await client_project(ctx, s["contact_ids"], pid)
    text = (body.get("text") or "").strip()[:5000]
    if not text:
        raise AppError("invalid", "The message is empty.", 400)
    c = await ctx.data.contacts.get(s["contact_ids"][0])
    await receive(ctx, pid, "portal", c.get("email") or c.get("phone"), "", text)
    return {"ok": True}


@router.post("/{ws_slug}/portal/project/{pid}/upload")
async def portal_upload(ws_slug: str, pid: str, body: dict, request: Request):
    ctx, s = await portal_ctx(request, ws_slug)
    await client_project(ctx, s["contact_ids"], pid)
    key = await data_url_to_key(ctx.ws_id, body.get("data"), "client-upload")
    up = await ctx.data.uploads.insert({"project_id": pid, "name": (body.get("name") or "Upload")[:120], "key": key, "kind": "client_upload",
                                        "client_visible": True, "by_client": True, "token": token(18)})
    await log(ctx, pid, "upload", f"Client uploaded {up['name']}", ref=up["_id"], client_visible=True)
    await notify(ctx, f"Your client uploaded {up['name']}.", "upload", link=f"/projects/{pid}")
    return {"ok": True}


@router.post("/{ws_slug}/portal/session/{sid}/reschedule")
async def portal_reschedule(ws_slug: str, sid: str, body: dict, request: Request):
    ctx, s = await portal_ctx(request, ws_slug)
    sess = await ctx.data.sessions.get(sid)
    if not sess or sess["contact_id"] not in s["contact_ids"] or sess["status"] != "booked":
        raise not_found("That session")
    st = await ctx.data.session_types.get(sess["type_id"])
    if aware(sess["start"]) - now() < timedelta(hours=st.get("cancel_cutoff_hours", 12)):
        raise AppError("too_late", f"Sessions can be moved up to {st.get('cancel_cutoff_hours', 12)} hours before. Please message instead.", 400)
    c = await ctx.data.contacts.get(sess["contact_id"])
    new = await book(ctx, st, body.get("start"), c, sess["project_id"])
    await cancel_session(ctx, sess, by="client", tell_client=False)
    return {"ok": True, "label": fmt_dt(new["start"])}


@router.post("/{ws_slug}/portal/logout")
async def portal_logout(ws_slug: str, response: Response):
    response.delete_cookie(PORTAL_COOKIE)
    return {"ok": True}


# ---------------- inbound webhooks ----------------

@hooks.post("/email-inbound")
async def email_inbound(body: dict):
    """Provider inbound webhook. Replies to t-<thread>@INBOUND_DOMAIN land on the project."""
    to = (body.get("To") or body.get("to") or "")
    m = re.search(r"t-([a-f0-9]{32})@", to)
    if not m:
        return {"ok": True, "ignored": True}
    th = await get_db().threads.find_one({"_id": m.group(1)})
    if not th:
        return {"ok": True, "ignored": True}
    ctx = cctx(th["workspace_id"])
    text = body.get("StrippedTextReply") or body.get("TextBody") or body.get("text") or ""
    await receive(ctx, th["project_id"], "email", body.get("From") or body.get("from") or "", body.get("Subject") or "", text[:20000])
    return {"ok": True}


async def whatsapp_route(phone):
    """Which practice and project a WhatsApp reply belongs to: (workspace_id, project_id) or None.

    All practices send from one WhatsApp number, so the sender's phone alone can match
    contacts in several practices. A reply goes to exactly one: the practice that last
    sent WhatsApp to this number. With no such message, only an unambiguous match is used;
    a client's words never reach a practice they weren't talking to."""
    db = get_db()
    last = await db.messages.find_one({"to": phone, "channel": "whatsapp", "direction": "out", "deleted_at": None},
                                      sort=[("created_at", -1)])
    if last:
        pr = await db.projects.find_one({"_id": last.get("project_id"), "workspace_id": last["workspace_id"], "deleted_at": None})
        if pr and not pr.get("archived"):
            return last["workspace_id"], pr["_id"]
        ws_ids = [last["workspace_id"]]
    else:
        ws_ids = sorted({c["workspace_id"] for c in await db.contacts.find({"phone": phone, "deleted_at": None}).to_list(None)})
        if len(ws_ids) > 1:
            logging.getLogger("app.hooks").warning("WhatsApp reply matches %d practices and none messaged this number; not delivered",
                                                   len(ws_ids))
            return None
    for ws_id in ws_ids:
        cids = [c["_id"] for c in await db.contacts.find({"workspace_id": ws_id, "phone": phone, "deleted_at": None}).to_list(None)]
        pr = await db.projects.find_one({"workspace_id": ws_id, "contact_ids": {"$in": cids}, "deleted_at": None, "archived": False},
                                        sort=[("last_activity_at", -1)]) if cids else None
        if pr:
            return ws_id, pr["_id"]
    return None


@hooks.post("/whatsapp-inbound")
async def whatsapp_inbound(body: dict):
    phone = norm_phone(body.get("from") or body.get("phone") or "")
    text = (body.get("text") or body.get("message") or "")[:5000]
    route = await whatsapp_route(phone)
    if route:
        await receive(cctx(route[0]), route[1], "whatsapp", phone, "", text)
    return {"ok": True, "matched": 1 if route else 0}


@hooks.post("/email-events")
async def email_events(body: dict):
    """Delivery, open and bounce events from the email provider."""
    pid = body.get("MessageID") or body.get("message_id")
    kind = (body.get("RecordType") or body.get("event") or "").lower()
    status = {"delivery": "delivered", "delivered": "delivered", "open": "opened", "opened": "opened", "bounce": "bounced",
              "bounced": "bounced"}.get(kind)
    if pid and status:
        await get_db().messages.update_many({"provider_id": pid}, {"$set": {"status": status}})
    return {"ok": True}


@hooks.post("/meetbot")
async def meetbot_hook(body: dict):
    """The meeting-bot provider tells us a transcript is ready."""
    bot = body.get("bot_id")
    s = await get_db().sessions.find_one({"notetaker.bot_id": bot})
    if s:
        await get_db().sessions.update_one({"_id": s["_id"]}, {"$set": {"notetaker.transcript_ready": True}})
    return {"ok": True}


_ = (build, session_values, limits, clean)
