"""Estimates and quick quotes (add-on A5).

The estimate is internal: phases and lines with rates from the client's rate
card, cost rates, expenses with markup, contingency and discount, and live
price / cost / margin (or effective hourly rate for a solo consultant).

What goes to the client is a quick quote (a one-page client file with an
Accept button) or a full proposal. Cost and margin are never in either. When
the client accepts: the project gets a budget, tasks with estimates and a
payment schedule. That happens once, however many times they tap.
"""
import re
from datetime import timedelta
from typing import Optional

from actions import perm, rates
from actions.registry import ADMINS, STAFF, P, action
from core import limits
from core.events import emit, log
from core.util import IST, AppError, clean, fmt_date, inr, new_id, not_found, now

UNIT_MIN = {"hour": 60, "day": None, "week": None}


def line_minutes(l, ws):
    q = float(l.get("qty") or 0)
    u = l.get("unit", "hour")
    dh = rates.day_hours(ws)
    return int(round(q * (60 if u == "hour" else dh * 60 if u == "day" else 5 * dh * 60 if u == "week" else 0)))


def compute(est, ws):
    """Pure: totals in paise and minutes."""
    subtotal = cost = minutes = 0
    has_cost = False
    for ph in est.get("phases", []):
        ph_price = ph_cost = 0
        for l in ph.get("lines", []):
            q = float(l.get("qty") or 0)
            if l.get("kind") == "expense":
                c = int(round(q * 1000)) * int(l.get("cost_paise") or 0) // 1000
                pr = c + c * int(l.get("markup_bp") or 0) // 10000
                lc = c
                has_cost = has_cost or c > 0
                l["minutes"] = 0
            else:
                pr = int(round(q * 1000)) * int(l.get("rate_paise") or 0) // 1000
                m = line_minutes(l, ws)
                lc = m * int(l.get("cost_rate_paise") or 0) // 60
                has_cost = has_cost or bool(l.get("cost_rate_paise"))
                minutes += m
                l["minutes"] = m
            l["price_paise"], l["cost_paise_total"] = pr, lc
            ph_price += pr
            ph_cost += lc
        ph["price_paise"], ph["cost_paise_total"] = ph_price, ph_cost
        subtotal += ph_price
        cost += ph_cost
    cont = subtotal * int(est.get("contingency_bp") or 0) // 10000
    disc = min(int(est.get("discount_paise") or 0), subtotal + cont)
    price = subtotal + cont - disc
    margin = price - cost
    target = int((ws.get("settings") or {}).get("target_margin_bp", 3000))
    est["totals"] = {"subtotal": subtotal, "contingency": cont, "discount": disc, "price": price, "cost_paise": cost,
                     "margin_paise": margin, "margin_bp": margin * 10000 // price if price else 0, "minutes": minutes,
                     "effective_hourly_paise": price * 60 // minutes if minutes else 0, "has_cost": has_cost,
                     "below_target_margin": has_cost and price > 0 and margin * 10000 // price < target, "target_margin_bp": target}
    return est


async def standard_hourly(ctx):
    return (await rates.resolve(ctx, None))["hourly_paise"]


async def fill_rates(ctx, pr, phases):
    """Lines without a rate get it from the client's rate card (snapshotted into the estimate)."""
    ws = await ctx.ws()
    on = now().astimezone(IST).date().isoformat()
    for ph in phases:
        ph.setdefault("id", new_id()[:8])
        ph["name"] = (ph.get("name") or "Phase").strip()[:80]
        for l in ph.setdefault("lines", []):
            l.setdefault("id", new_id()[:8])
            l["kind"] = l.get("kind") or "labour"
            l["qty"] = float(l.get("qty") or 0)
            if l["qty"] < 0:
                raise AppError("invalid", "Quantities can't be below zero.", 400)
            if l["kind"] == "labour":
                if l.get("rate_paise") is None:
                    r = await rates.resolve(ctx, pr, on, l.get("service_id"), l.get("user_id"))
                    unit = l.get("unit") or r["unit"]
                    rate = r["rate_paise"] if unit == r["unit"] else (r["hourly_paise"] * (rates.day_hours(ws) if unit == "day" else 1))
                    l["unit"], l["rate_paise"] = unit, int(rate)
                if l.get("cost_rate_paise") is None:
                    prof = await rates.member_profile(ctx, l.get("user_id"), on) if l.get("user_id") else {}
                    l["cost_rate_paise"] = int(prof.get("cost_rate_paise") or 0)
                if not l.get("label"):
                    s = await ctx.data.services.get(l.get("service_id") or "")
                    l["label"] = (s or {}).get("name") or l.get("role") or "Consulting"
            else:
                l["unit"] = "item"
                l["label"] = (l.get("label") or "Expense")[:120]
    return phases


async def view(ctx, est):
    ws = await ctx.ws()
    compute(est, ws)
    o = clean(est)
    pr = await ctx.data.projects.get(est["project_id"])
    o["project"] = (pr or {}).get("name", "")
    if not est["totals"]["has_cost"]:
        std = await standard_hourly(ctx)
        o["standard_hourly_paise"] = std
        o["effective_vs_standard_pct"] = round(est["totals"]["effective_hourly_paise"] * 100 / std) if std else None
    o["versions"] = [{"id": v["_id"], "version": v["version"], "status": v["status"]}
                     for v in await ctx.data.estimates.find({"root_id": est.get("root_id") or est["_id"]}, sort=[("version", 1)])]
    return o


async def get_est(ctx, eid, act=False):
    e = await ctx.data.estimates.get(eid)
    if not e:
        raise not_found("That estimate")
    await perm.project(ctx, e["project_id"], act=act)
    return e


class EstIn(P):
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    name: str = "Estimate"
    phases: list = []
    contingency_pct: float = 0
    discount_paise: int = 0
    assumptions: str = ""
    valid_days: int = 14


@action("estimates.create", "internal", EstIn, roles=STAFF,
        desc="Start an internal estimate: phases and lines (service or role, quantity, unit), rates from the client's rate card.")
async def estimates_create(ctx, p: EstIn):
    from actions.timebill import find_project
    await limits.require(ctx, "estimates")
    pr = await find_project(ctx, p.project_id, p.project_name)
    phases = await fill_rates(ctx, pr, p.phases or [{"name": "Work", "lines": []}])
    est = {"project_id": pr["_id"], "name": p.name.strip()[:80] or "Estimate", "version": 1, "status": "draft", "phases": phases,
           "contingency_bp": int(round(p.contingency_pct * 100)), "discount_paise": max(0, int(p.discount_paise)),
           "assumptions": p.assumptions[:2000], "valid_days": max(1, min(int(p.valid_days), 180))}
    compute(est, await ctx.ws())
    e = await ctx.data.estimates.insert(est)
    await ctx.data.estimates.update({"_id": e["_id"]}, {"root_id": e["_id"]})
    e["root_id"] = e["_id"]
    await log(ctx, pr["_id"], "estimate", f"Estimate started: {e['name']}", ref=e["_id"])
    return await view(ctx, e)


class EstUpd(P):
    id: str
    name: Optional[str] = None
    phases: Optional[list] = None
    contingency_pct: Optional[float] = None
    discount_paise: Optional[int] = None
    assumptions: Optional[str] = None
    valid_days: Optional[int] = None


@action("estimates.update", "internal", EstUpd, roles=STAFF, desc="Edit a draft estimate. A final estimate can't change; make a new version.")
async def estimates_update(ctx, p: EstUpd):
    e = await get_est(ctx, p.id, act=True)
    if e["status"] != "draft":
        raise AppError("locked", "This estimate is final. Make a new version to change it.", 409)
    pr = await ctx.data.projects.get(e["project_id"])
    if p.name is not None:
        e["name"] = p.name.strip()[:80] or e["name"]
    if p.phases is not None:
        e["phases"] = await fill_rates(ctx, pr, p.phases)
    if p.contingency_pct is not None:
        if not 0 <= p.contingency_pct <= 100:
            raise AppError("invalid", "Contingency must be between 0% and 100%.", 400)
        e["contingency_bp"] = int(round(p.contingency_pct * 100))
    if p.discount_paise is not None:
        e["discount_paise"] = max(0, int(p.discount_paise))
    if p.assumptions is not None:
        e["assumptions"] = p.assumptions[:2000]
    if p.valid_days is not None:
        e["valid_days"] = max(1, min(int(p.valid_days), 180))
    compute(e, await ctx.ws())
    await ctx.data.estimates.update({"_id": e["_id"]}, {k: e[k] for k in ("name", "phases", "contingency_bp", "discount_paise", "assumptions",
                                                                          "valid_days", "totals")})
    return await view(ctx, e)


class IdIn(P):
    id: str


@action("estimates.finalise", "internal", IdIn, roles=STAFF, desc="Make an estimate final (locked). Then turn it into a quote or proposal.")
async def estimates_finalise(ctx, p: IdIn):
    e = await get_est(ctx, p.id, act=True)
    if e["status"] != "draft":
        raise AppError("invalid", "This estimate is already final.", 400)
    compute(e, await ctx.ws())
    if e["totals"]["price"] <= 0:
        raise AppError("invalid", "The estimate total is zero. Add lines with rates first.", 400)
    await ctx.data.estimates.update({"_id": e["_id"]}, {"status": "final", "finalised_at": now(), "totals": e["totals"], "phases": e["phases"]})
    pr = await ctx.data.projects.get(e["project_id"])
    st = await ctx.data.stages.get(pr["stage_id"])
    if st and st.get("group") == "opportunity":
        await ctx.data.projects.update({"_id": pr["_id"]}, {"value_paise": e["totals"]["price"]})
    await emit(ctx, "estimate.finalised", {"estimate_id": e["_id"], "price": e["totals"]["price"]}, e["project_id"])
    return await view(ctx, await ctx.data.estimates.get(e["_id"]))


@action("estimates.new_version", "internal", IdIn, roles=STAFF, desc="Copy an estimate into a new draft version.")
async def estimates_new_version(ctx, p: IdIn):
    e = await get_est(ctx, p.id, act=True)
    root = e.get("root_id") or e["_id"]
    last = (await ctx.data.estimates.find({"root_id": root}, sort=[("version", -1)], limit=1))[0]
    doc = {k: v for k, v in e.items() if k not in ("_id", "created_at", "updated_at", "quote_file_id", "proposal_file_id", "converted_at",
                                                   "converting", "finalised_at", "status", "version")}
    n = await ctx.data.estimates.insert(dict(doc, version=last["version"] + 1, status="draft", root_id=root))
    if e["status"] == "final":
        await ctx.data.estimates.update({"_id": e["_id"]}, {"status": "superseded"})
    return await view(ctx, n)


@action("estimates.get", "read", IdIn, roles=STAFF, desc="An estimate with live totals: price, cost, margin, hours, effective rate.")
async def estimates_get(ctx, p: IdIn):
    return await view(ctx, await get_est(ctx, p.id))


class ListIn(P):
    project_id: Optional[str] = None


@action("estimates.list", "read", ListIn, roles=STAFF, desc="Estimates, newest first.")
async def estimates_list(ctx, p: ListIn):
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    f = {"project_id": p.project_id if p.project_id in vis else "-"} if p.project_id else {"project_id": {"$in": vis}}
    rows = await ctx.data.estimates.find(f, sort=[("created_at", -1)], limit=300)
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": list({r["project_id"] for r in rows})}})}
    ws = await ctx.ws()
    out = []
    for r in rows:
        compute(r, ws)
        out.append({"id": r["_id"], "name": r["name"], "version": r["version"], "status": r["status"], "project_id": r["project_id"],
                    "project": names.get(r["project_id"], ""), "price_paise": r["totals"]["price"], "margin_bp": r["totals"]["margin_bp"],
                    "has_cost": r["totals"]["has_cost"], "minutes": r["totals"]["minutes"], "created_at": clean(r)["created_at"]})
    return out


# ---------------- to the client ----------------

def client_items(est, detail):
    """What the client may see: never cost, margin or cost rates."""
    t = est["totals"]
    if detail == "total":
        items = [{"label": est["name"], "price_paise": t["price"]}]
    elif detail == "phase":
        items = [{"label": ph["name"], "price_paise": ph["price_paise"]} for ph in est["phases"] if ph["price_paise"]]
    else:
        items = []
        for ph in est["phases"]:
            for l in ph["lines"]:
                if l["price_paise"]:
                    q = l["qty"]
                    items.append({"label": f"{ph['name']}: {l['label']}", "qty": int(q) if q == int(q) else q,
                                  "unit": l.get("unit") if l.get("kind") != "expense" else None, "price_paise": l["price_paise"]})
    if detail != "total":
        if t["contingency"]:
            items.append({"label": "Contingency", "price_paise": t["contingency"]})
        if t["discount"]:
            items.append({"label": "Discount", "price_paise": -t["discount"]})
    return items


class QuoteIn(P):
    id: str
    detail: str = "phase"            # total | phase | line
    valid_days: Optional[int] = None
    message: str = ""


@action("estimates.to_quote", "internal", QuoteIn, roles=STAFF,
        desc="Turn a final estimate into a one-page quick quote (scope, price, valid-until date, Accept). Cost and margin are never shown.")
async def estimates_to_quote(ctx, p: QuoteIn):
    from actions.files import create_file
    e = await get_est(ctx, p.id, act=True)
    if e["status"] != "final":
        raise AppError("invalid", "Make the estimate final first.", 400)
    if p.detail not in ("total", "phase", "line"):
        raise AppError("invalid", "Show one total, totals per phase, or every line.", 400)
    compute(e, await ctx.ws())
    days = p.valid_days or e.get("valid_days") or 14
    valid_until = (now().astimezone(IST) + timedelta(days=days)).date().isoformat()
    pages = [{"id": new_id()[:8], "title": "Your quote", "button": "Accept quote", "blocks": [
        {"id": new_id()[:8], "type": "text", "html": f"<h2>{e['name']}</h2><p>Hi {{{{client.first_name}}}}, "
                                                      f"{p.message or 'here is my quote for the work we discussed.'}</p>"},
        {"id": new_id()[:8], "type": "quote", "estimate_id": e["_id"], "detail": p.detail, "items": client_items(e, p.detail),
         "total_paise": e["totals"]["price"], "valid_until": valid_until}]}]
    pr = await ctx.data.projects.get(e["project_id"])
    f = await create_file(ctx, pr, pages, f"Quote — {e['name']}", kind="quote")
    await ctx.data.client_files.update({"_id": f["_id"]}, {"estimate_id": e["_id"], "valid_until": valid_until})
    await ctx.data.estimates.update({"_id": e["_id"]}, {"quote_file_id": f["_id"], "detail": p.detail})
    from actions.files import get_file
    return clean(await get_file(ctx, f["_id"]))


class PropIn(P):
    id: str
    template_id: Optional[str] = None
    detail: str = "phase"


@action("estimates.to_proposal", "internal", PropIn, roles=STAFF,
        desc="Fill a proposal template's services and invoice from a final estimate.")
async def estimates_to_proposal(ctx, p: PropIn):
    from actions.files import CreateIn, files_create, get_file
    e = await get_est(ctx, p.id, act=True)
    if e["status"] != "final":
        raise AppError("invalid", "Make the estimate final first.", 400)
    compute(e, await ctx.ws())
    tid = p.template_id
    if not tid:
        t = await ctx.data.templates.find_one({"gallery_key": "proposal_audit"}) or await ctx.data.templates.find_one({"kind": "file"})
        tid = t["_id"] if t else None
    f = await files_create(ctx, CreateIn(project_id=e["project_id"], template_id=tid))
    doc = await get_file(ctx, f.get("id") or f.get("_id"))
    items = [{"id": new_id()[:10], "name": i["label"], "desc": "", "price_paise": i["price_paise"], "qty": 1, "kind": "package"}
             for i in client_items(e, p.detail if p.detail != "line" else "phase") if i["price_paise"] > 0]
    done = False
    for pg in doc["pages"]:
        for b in pg["blocks"]:
            if b["type"] == "services" and not done:
                b.update(items=items, mode="fixed", feeds_invoice=True)
                done = True
    await ctx.data.client_files.update({"_id": doc["_id"]}, {"pages": doc["pages"], "estimate_id": e["_id"]})
    await ctx.data.estimates.update({"_id": e["_id"]}, {"proposal_file_id": doc["_id"], "detail": p.detail})
    return clean(await get_file(ctx, doc["_id"]))


async def convert(ctx, e, from_quote=False):
    """Accepted: budget, tasks with estimates, payment schedule. Exactly once."""
    from actions import budgets
    got = await ctx.data.estimates.find_one_and_update({"_id": e["_id"], "status": "final", "converting": {"$ne": True}},
                                                       {"$set": {"converting": True}})
    if not got:
        return None
    e = got
    ws = await ctx.ws()
    compute(e, ws)
    pid = e["project_id"]
    # Budget (the retainer is the budget if there is one).
    if not await budgets.retainer_for(ctx, pid):
        await ctx.data.budgets.update_many({"project_id": pid, "active": True}, {"active": False, "removed_at": now(), "replaced_by": e["_id"]})
        if e["totals"]["price"] > 0:
            await ctx.data.budgets.insert({"project_id": pid, "type": "fee", "amount_paise": e["totals"]["price"], "amount_minutes": None,
                                           "counts": "both", "reset": "none", "thresholds": (ws.get("settings") or {}).get("budget_alerts") or [80, 100],
                                           "start_date": now().astimezone(IST).date().isoformat(), "active": True, "source": "estimate",
                                           "estimate_id": e["_id"]})
    # Tasks from the labour lines, each with its estimate.
    from pymongo.errors import DuplicateKeyError
    pr = await ctx.data.projects.get(pid)
    n = 0
    for ph in e["phases"]:
        for l in ph["lines"]:
            if l.get("kind") == "expense" or not l.get("minutes"):
                continue
            try:
                await ctx.data.tasks.insert({"title": f"{ph['name']}: {l['label']}"[:200], "project_id": pid, "assignee_id": l.get("user_id") or pr.get("owner_id"),
                                             "due_at": None, "done": False, "created_by": ctx.actor, "reminded": False, "audience": "team",
                                             "estimate_minutes": l["minutes"], "service_id": l.get("service_id"),
                                             "occurrence_key": f"est:{e['_id']}:{l['id']}"})
                n += 1
            except DuplicateKeyError:
                pass
    # Payment schedule from a quick quote (a proposal brings its own invoice block).
    inv = None
    if from_quote:
        from actions.money import issue, new_invoice
        sched = None
        try:
            from agents.setup import parse_payment
            ans = ((ws.get("setup") or {}).get("answers") or {}).get("payment")
            sched = parse_payment(ans) if ans else None
        except Exception:
            sched = None
        lines = [{"id": new_id()[:8], "name": i["label"], "qty": 1, "price_paise": i["price_paise"]}
                 for i in client_items(e, e.get("detail") or "phase")]
        inv = await new_invoice(ctx, pr, lines, sched, e["name"])
        await ctx.data.invoices.update({"_id": inv["_id"]}, {"estimate_id": e["_id"]})
        try:
            inv = await issue(ctx, await ctx.data.invoices.get(inv["_id"]))
        except AppError:
            pass
    await ctx.data.estimates.update({"_id": e["_id"]}, {"status": "converted", "converted_at": now(), "invoice_id": (inv or {}).get("_id")})
    await ctx.data.projects.update({"_id": pid}, {"value_paise": e["totals"]["price"]})
    await budgets.check(ctx, pid)
    await emit(ctx, "estimate.converted", {"estimate_id": e["_id"], "tasks": n}, pid)
    await log(ctx, pid, "estimate", f"Estimate accepted: budget {inr(e['totals']['price'])}, {n} task{'s' if n != 1 else ''} added", ref=e["_id"])
    return {"tasks": n, "invoice": inv}


@action("estimates.convert", "internal", IdIn, roles=STAFF,
        desc="Mark an estimate accepted by hand: the project gets its budget, tasks and (from a quote) the payment schedule.")
async def estimates_convert(ctx, p: IdIn):
    e = await get_est(ctx, p.id, act=True)
    if e["status"] == "converted":
        return {"ok": True, "already": True}
    if e["status"] != "final":
        raise AppError("invalid", "Make the estimate final first.", 400)
    r = await convert(ctx, e, from_quote=bool(e.get("quote_file_id")))
    return {"ok": True, "tasks": (r or {}).get("tasks", 0)}


async def accept_quote(ctx, f):
    """The client tapped Accept on a quote (from the public page)."""
    from actions.files import mark_completed
    if f.get("kind") != "quote":
        raise AppError("invalid", "This isn't a quote.", 400)
    if f["status"] == "completed" or f.get("accepted_at"):
        return {"ok": True, "already": True}
    if f.get("valid_until") and f["valid_until"] < now().astimezone(IST).date().isoformat():
        raise AppError("expired", f"This quote expired on {fmt_date(f['valid_until'])}. Please ask for a new one.", 409)
    got = await ctx.data.client_files.find_one_and_update({"_id": f["_id"], "accepted_at": None}, {"$set": {"accepted_at": now()}})
    if not got:
        return {"ok": True, "already": True}
    e = await ctx.data.estimates.get(f.get("estimate_id") or "")
    res = await convert(ctx, e, from_quote=True) if e else None
    await mark_completed(ctx, await ctx.data.client_files.get(f["_id"]))
    await emit(ctx, "quote.accepted", {"file_id": f["_id"], "estimate_id": f.get("estimate_id")}, f["project_id"])
    inv = (res or {}).get("invoice")
    return {"ok": True, "invoice_token": inv.get("token") if inv and inv.get("status") != "draft" else None}


# ---------------- agent help: an estimate from plain words ----------------

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "half": 0.5}


def _num(s):
    s = s.lower()
    return float(WORDS.get(s, s)) if s in WORDS or re.match(r"^\d+(\.\d+)?$", s) else None


def parse_scope(text):
    """'6-week pricing study, two days a week' -> days and a name. Assumptions are stated, never hidden."""
    t = (text or "").lower()
    n = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|twelve|half)"
    weeks = re.search(n + r"[\s-]*weeks?", t)
    dpw = re.search(n + r"\s*days?\s*(?:a|per|each)\s*week", t)
    days = re.search(n + r"\s*(?:working\s*)?days?(?!\s*(?:a|per|each)\s*week)", t)
    hours = re.search(n + r"\s*hours?", t)
    assume = []
    if weeks and dpw:
        total_days = _num(weeks.group(1)) * _num(dpw.group(1))
        assume.append(f"{_num(weeks.group(1)):g} weeks × {_num(dpw.group(1)):g} days a week = {total_days:g} days.")
    elif days:
        total_days = _num(days.group(1))
        assume.append(f"{total_days:g} days of work.")
    elif hours:
        total_days = None
        assume.append(f"{_num(hours.group(1)):g} hours of work.")
    else:
        total_days = 10
        assume.append("No duration was given, so I assumed 10 days. Change it if that's wrong.")
    m = re.search(r"(?:\d+[\s-]*week\s+|a\s+|an\s+)([a-z][a-z ]{3,40}?(?:study|audit|review|project|plan|strategy|workshop|programme|program|"
                  r"sprint|assessment|diagnostic))", t)
    name = (m.group(1).strip().capitalize() if m else "Consulting engagement")
    return {"days": total_days, "hours": _num(hours.group(1)) if hours and total_days is None else None, "name": name, "assumptions": assume}


class DraftIn(P):
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    text: str


@action("estimates.draft_from_text", "internal", DraftIn, roles=STAFF,
        desc="Draft an estimate from plain words or call notes, e.g. 'a 6-week pricing study, two days a week'. States its assumptions.")
async def estimates_draft(ctx, p: DraftIn):
    from actions.timebill import find_project
    pr = await find_project(ctx, p.project_id, p.project_name)
    sc = parse_scope(p.text)
    ws = await ctx.ws()
    day = await rates.resolve(ctx, pr)
    card = await rates.default_card(ctx)
    day_line = next((l for l in await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"], "unit": "day"})), None)
    if day_line:
        day_rate = await rates.rate_on(ctx, day_line, now().astimezone(IST).date().isoformat())
        sid = day_line.get("service_id")
    else:
        day_rate, sid = day["hourly_paise"] * rates.day_hours(ws), None
    assume = list(sc["assumptions"])
    assume.append(f"Day rate {inr(day_rate)} from your rate card." if day_rate else "No day rate is set; add one in Settings → Services and rates.")
    try:
        from actions.insight import effective_rate_for_words
        er = await effective_rate_for_words(ctx, sc["name"])
        if er:
            assume.append(er)
    except Exception:
        pass
    assume.append("No travel or other expenses included.")
    if sc["days"] is None:
        phases = [{"name": "Work", "lines": [{"kind": "labour", "label": "Consulting", "qty": sc["hours"], "unit": "hour",
                                              "rate_paise": day_rate // rates.day_hours(ws) if day_rate else None, "service_id": sid}]}]
    else:
        d = float(sc["days"])
        split = [("Discovery", max(0.5, round(d * 0.15 * 2) / 2)), ("Analysis and recommendations", None), ("Presentation and handover", max(0.5, round(d * 0.15 * 2) / 2))]
        main = max(0.5, d - split[0][1] - split[2][1])
        phases = [{"name": n, "lines": [{"kind": "labour", "label": "Consulting days", "qty": q if q is not None else main, "unit": "day",
                                         "rate_paise": day_rate or None, "service_id": sid}]} for n, q in split]
    out = await estimates_create(ctx, EstIn(project_id=pr["_id"], name=sc["name"], phases=phases, assumptions="\n".join(assume)))
    out["summary"] = f"Drafted \"{sc['name']}\" at {inr(out['totals']['price'])}. Assumptions: " + " ".join(assume)
    return out


_ = (ADMINS, fmt_date)
