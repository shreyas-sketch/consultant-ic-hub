"""Retainers (add-on A4), task templates and recurring tasks (4.10).

A retainer runs itself: hours tracked against the period, the client told at a
usage point, the period closed and invoiced, the next one opened with its
checklist. All the maths is in whole minutes.

Close (once per period, even with two workers): add up billable minutes ->
available = included - borrowed + carried in -> carried hours are used first ->
unused: rollover rule; over: overage rule -> the period record is written and
never changes -> invoice per the billing rule (a draft for approval unless the
consultant chose auto-send) -> the next period opens.

Time dated inside a closed period goes to the current period as an adjustment.
No auto-charge: invoices are paid by UPI or bank transfer like any other.
"""
import calendar
from datetime import date as Date
from datetime import timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from app.domain import perm
from app.domain.billing import rates
from app.domain.registry import ADMINS, STAFF, P, action
from app.core import limits
from app.core.events import audit, emit, log, notify
from app.core.util import IST, AppError, clean, fmt_date, inr, new_id, not_found, now

KINDS = {"hours": "Hours or days bank", "fixed": "Fixed scope", "payg": "Pay as used, with a cap"}
ROLLOVER = ("none", "capped", "all")
OVERAGE = ("bill", "borrow", "absorb", "ask")


def today():
    return now().astimezone(IST).date()


def add_months(d: Date, n: int, day: int = None) -> Date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    day = day or d.day
    return Date(y, m, min(day, calendar.monthrange(y, m)[1]))


def period_end(r, start: str) -> str:
    s = Date.fromisoformat(start)
    anchor = Date.fromisoformat(r["start_date"]).day
    return add_months(s, 3 if r["period"] == "quarterly" else 1, anchor).isoformat()


def h(minutes) -> str:
    v = round(int(minutes) / 60, 1)
    return f"{int(v) if v == int(v) else v} hour{'s' if v != 1 else ''}"


def period_label(per) -> str:
    s = Date.fromisoformat(per["start"])
    e = Date.fromisoformat(per["end"]) - timedelta(days=1)
    return f"{s:%b %Y}" if (s.day == 1 and e.month == s.month) else f"{s.day} {s:%b} – {e.day} {e:%b %Y}"


# ---------------- numbers ----------------

async def entries_of(ctx, r, per):
    base = {"project_id": {"$in": r["project_ids"]}, "billing_status": {"$ne": "non_billable"}}
    in_range = await ctx.data.time_entries.find({**base, "date": {"$gte": per["start"], "$lt": per["end"]},
                                                 "adjustment_period_id": None}, sort=[("date", 1)])
    adj = await ctx.data.time_entries.find({**base, "adjustment_period_id": per["_id"]}, sort=[("date", 1)])
    return in_range, adj


async def period_numbers(ctx, r, per):
    if per.get("status") == "closed":
        return {k: per.get(k, 0) for k in ("included", "carried_in_minutes", "borrowed", "available", "used", "adjustments", "left")} | \
               {"carried_out_minutes": per.get("carried_out_minutes", 0), "overage_minutes": per.get("overage_minutes", 0),
                "lapsed_minutes": per.get("lapsed_minutes", 0)}
    rows, adj = await entries_of(ctx, r, per)
    used = sum(e["minutes"] for e in rows) + sum(e["minutes"] for e in adj)
    included = int(per.get("included_minutes") or 0)
    borrowed = int(per.get("borrowed_minutes") or 0)
    carried = sum(int(c["minutes"]) for c in per.get("carried_in") or [])
    avail = max(0, included - borrowed) + carried if r["kind"] == "hours" else 0
    return {"included": included, "carried_in_minutes": carried, "borrowed": borrowed, "available": avail, "used": used,
            "adjustments": sum(e["minutes"] for e in adj), "left": max(0, avail - used)}


async def overage_rate(ctx, r):
    if r.get("overage_rate_paise"):
        return int(r["overage_rate_paise"])
    pr = await ctx.data.projects.get(r["project_ids"][0])
    rate = (await rates.resolve(ctx, pr))["hourly_paise"]
    if rate:
        return rate
    inc = int(r.get("included_minutes") or 0)
    return int(r.get("fee_paise") or 0) * 60 // inc if inc else 0


# ---------------- invoices ----------------

async def raise_invoice(ctx, r, per, lines, title, due_on: Date, idem):
    """A retainer invoice: a draft for the consultant's OK, or sent straight away if they chose that."""
    from app.domain.workspace.approvals import create_approval
    from app.domain.billing.money import SendInv, invoices_send, new_invoice
    lines = [l for l in lines if l["price_paise"] > 0 or l.get("minutes")]
    if not lines:
        return None
    if await ctx.data.invoices.find_one({"retainer_idem": idem}):
        return None
    pr = await ctx.data.projects.get(r["project_ids"][0])
    inv = await new_invoice(ctx, pr, lines, [{"id": new_id()[:8], "label": title, "pct": 100,
                                             "due": {"type": "date", "date": due_on.isoformat() + "T12:00:00+05:30"}}], title,
                            contact_id=r.get("contact_id"))
    await ctx.data.invoices.update({"_id": inv["_id"]}, {"retainer_id": r["_id"], "retainer_period_id": per["_id"], "retainer_idem": idem})
    if r.get("auto_send"):
        try:
            await invoices_send(ctx, SendInv(id=inv["_id"], channel="both"))
        except AppError as e:
            await notify(ctx, f"Retainer invoice for {r['name']} couldn't be sent: {e.message}", "retainer", link="/payments")
    else:
        await create_approval(ctx, "invoices.send", {"id": inv["_id"], "channel": "both"},
                              {"subject": f"Send {title} ({inr(inv['totals']['total'])})", "summary": f"{r['name']}: {title}"},
                              "Retainer period", project_id=pr["_id"], source="agent", agent="collections", idem=f"retainer-send:{idem}")
    return inv


def fee_line(r, per):
    return {"id": new_id()[:8], "name": f"{r['name']} — {period_label(per)}", "desc": KINDS[r["kind"]] if r["kind"] != "hours"
            else f"Includes {h(per.get('included_minutes') or r['included_minutes'])}", "qty": 1, "price_paise": int(per.get("fee_paise") or r["fee_paise"]),
            "kind": "retainer"}


def overage_line(minutes, rate, label):
    return {"id": new_id()[:8], "name": f"Extra time — {label}", "desc": f"{h(minutes)} beyond the plan", "qty": round(minutes / 60, 2),
            "minutes": int(minutes), "unit": "hour", "price_paise": int(rate), "kind": "overage", "adjust_paise": 0}


# ---------------- periods ----------------

async def open_period(ctx, r, start, index, carried_in=None, borrowed=0, pending_overage=None):
    if r.get("pending_plan"):
        await ctx.data.retainers.update({"_id": r["_id"]}, dict(r["pending_plan"], pending_plan=None))
        r = await ctx.data.retainers.get(r["_id"])
    per = {"retainer_id": r["_id"], "index": index, "start": start, "end": period_end(r, start), "period_key": f"{r['_id']}:{start}",
           "status": "open", "included_minutes": int(r.get("included_minutes") or 0) if r["kind"] == "hours" else 0,
           "fee_paise": int(r.get("fee_paise") or 0), "carried_in": carried_in or [], "borrowed_minutes": int(borrowed or 0), "alerts_sent": []}
    try:
        per = await ctx.data.retainer_periods.insert(per)
    except DuplicateKeyError:
        return await ctx.data.retainer_periods.find_one({"period_key": per["period_key"]}), False
    if r.get("task_template_id"):
        tpl = await ctx.data.task_templates.get(r["task_template_id"])
        if tpl:
            await apply_template(ctx, tpl, r["project_ids"][0], start, f"ret:{per['_id']}")
    await emit(ctx, "retainer.period_started", {"retainer_id": r["_id"], "period_id": per["_id"]}, r["project_ids"][0])
    if r["billing"] == "advance" and r["kind"] in ("hours", "fixed"):
        lines = [fee_line(r, per)]
        if pending_overage:
            lines.append(pending_overage)
        await raise_invoice(ctx, r, per, lines, f"{r['name']} — {period_label(per)}", Date.fromisoformat(start) + timedelta(days=7),
                            f"{per['_id']}:advance")
    return per, True


async def close_period(ctx, r, per, end_on=None, force_lapse=False):
    """Close one period exactly once. Returns the closed period, or None if someone else closed it."""
    got = await ctx.data.retainer_periods.find_one_and_update({"_id": per["_id"], "status": "open"}, {"$set": {"status": "closing"}})
    if not got:
        return None
    per = got
    if end_on and end_on < per["end"]:
        per["end"] = end_on
    rows, adj = await entries_of(ctx, r, per)
    used = sum(e["minutes"] for e in rows) + sum(e["minutes"] for e in adj)
    included = max(0, int(per.get("included_minutes") or 0) - int(per.get("borrowed_minutes") or 0))
    carried = sorted(per.get("carried_in") or [], key=lambda c: (c.get("expires_after") is None, c.get("expires_after") or 0))
    rec = {"used": used, "adjustments": sum(e["minutes"] for e in adj), "included": int(per.get("included_minutes") or 0),
           "borrowed": int(per.get("borrowed_minutes") or 0), "carried_in_minutes": sum(int(c["minutes"]) for c in carried),
           "carried_out": [], "carried_out_minutes": 0, "lapsed_minutes": 0, "overage_minutes": 0, "overage_billed_minutes": 0,
           "borrowed_out_minutes": 0, "absorbed_minutes": 0, "overage_pending_minutes": 0, "end": per["end"]}
    next_borrow, pending_overage, ovr_rate = 0, None, 0
    extra_lines = []
    if r["kind"] == "hours":
        avail = included + rec["carried_in_minutes"]
        rec["available"] = avail
        left = used
        # Carried hours are used first (soonest to expire first), then this period's hours.
        for c in carried:
            take = min(int(c["minutes"]), left)
            left -= take
            rest = int(c["minutes"]) - take
            if rest:
                if not force_lapse and (c.get("expires_after") is None or c["expires_after"] > per["index"]):
                    rec["carried_out"].append({"minutes": rest, "expires_after": c.get("expires_after"), "from_index": c.get("from_index")})
                else:
                    rec["lapsed_minutes"] += rest
        take = min(included, left)
        left -= take
        unused = included - take
        ro = r.get("rollover") or {"mode": "none"}
        if unused:
            if force_lapse or ro["mode"] == "none":
                rec["lapsed_minutes"] += unused
            elif ro["mode"] == "capped":
                keep = min(unused, int(ro.get("cap_minutes") or 0))
                if keep:
                    rec["carried_out"].append({"minutes": keep, "expires_after": per["index"] + int(ro.get("valid_periods") or 1),
                                               "from_index": per["index"]})
                rec["lapsed_minutes"] += unused - keep
            else:
                rec["carried_out"].append({"minutes": unused, "expires_after": None, "from_index": per["index"]})
        rec["carried_out_minutes"] = sum(c["minutes"] for c in rec["carried_out"])
        over = left
        rec["overage_minutes"] = over
        if over:
            ov = r.get("overage") or {"mode": "bill"}
            ovr_rate = await overage_rate(ctx, r)
            bill = 0
            if ov["mode"] == "bill":
                bill = over
            elif ov["mode"] == "borrow":
                next_borrow = min(over, int(ov.get("borrow_cap_minutes") or 0))
                rec["borrowed_out_minutes"] = next_borrow
                bill = over - next_borrow
            elif ov["mode"] == "absorb":
                rec["absorbed_minutes"] = over
            else:   # ask first
                rec["overage_pending_minutes"] = over
            rec["overage_billed_minutes"] = bill
            if bill:
                pending_overage = overage_line(bill, ovr_rate, period_label(per))
    else:
        rec["available"] = 0
    rec["left"] = max(0, rec.get("available", 0) - used)
    await ctx.data.retainer_periods.update({"_id": per["_id"]}, dict(rec, status="closed", closed_at=now()))
    # The period's time is covered by the retainer: billed and locked, so it never shows as unbilled.
    ids = [e["_id"] for e in rows + adj if e["billing_status"] == "unbilled" and not e.get("invoice_id")]
    if ids:
        await ctx.data.time_entries.update_many({"_id": {"$in": ids}}, {"billing_status": "billed", "locked": True, "billed_at": now(),
                                                                        "retainer_period_id": per["_id"]})
    per = await ctx.data.retainer_periods.get(per["_id"])
    pr_id = r["project_ids"][0]
    # Invoice for the period that just closed.
    due = today() + timedelta(days=7)
    if r["kind"] == "payg":
        rate = await overage_rate(ctx, r)
        amt = used * rate // 60
        cap = int(r.get("cap_paise") or 0)
        line = overage_line(used, rate, period_label(per))
        line.update(name=f"{r['name']} — {period_label(per)}", desc=f"{h(used)} at {inr(rate)}/hour", kind="retainer")
        if cap and amt > cap:
            line = {"id": new_id()[:8], "name": f"{r['name']} — {period_label(per)}", "desc": f"{h(used)} used; capped at {inr(cap)}",
                    "qty": 1, "price_paise": cap, "kind": "retainer"}
        if used:
            await raise_invoice(ctx, r, per, [line], f"{r['name']} — {period_label(per)}", due, f"{per['_id']}:arrears")
    elif r["billing"] == "arrears":
        lines = [fee_line(r, per)] + ([pending_overage] if pending_overage else [])
        await raise_invoice(ctx, r, per, lines, f"{r['name']} — {period_label(per)}", due, f"{per['_id']}:arrears")
        pending_overage = None
    if rec.get("overage_pending_minutes"):
        from app.domain.workspace.approvals import create_approval
        a = await create_approval(ctx, "retainers.bill_overage", {"period_id": per["_id"]},
                                  {"subject": f"{r['name']}: bill {h(rec['overage_pending_minutes'])} of extra time?",
                                   "summary": f"{h(rec['overage_pending_minutes'])} beyond the plan in {period_label(per)} at {inr(ovr_rate)}/hour. "
                                              "Skip to absorb it (not billed)."},
                                  "Retainer overage — your rule is to ask first", project_id=pr_id, source="agent", agent="collections",
                                  idem=f"overage:{per['_id']}")
        await ctx.data.approvals.update({"_id": a["_id"]}, {"on_skip": {"action": "retainers.absorb_overage", "args": {"period_id": per["_id"]}}})
    await emit(ctx, "retainer.period_closed", {"retainer_id": r["_id"], "period_id": per["_id"], "used": used,
                                               "overage": rec["overage_minutes"]}, pr_id)
    await log(ctx, pr_id, "retainer", f"{r['name']}: {period_label(per)} closed — {h(used)} used"
              + (f", {h(rec['carried_out_minutes'])} carried forward" if rec["carried_out_minutes"] else "")
              + (f", {h(rec['overage_minutes'])} over" if rec["overage_minutes"] else ""), ref=r["_id"], client_visible=True)
    r = await ctx.data.retainers.get(r["_id"])
    if r["status"] == "active" and not force_lapse and (not r.get("end_date") or per["end"] < r["end_date"]):
        nxt, _ = await open_period(ctx, r, per["end"], per["index"] + 1, rec["carried_out"], next_borrow, pending_overage)
        await ctx.data.retainers.update({"_id": r["_id"]}, {"current_period_id": nxt["_id"]})
    else:
        if pending_overage:
            await raise_invoice(ctx, r, per, [pending_overage], f"{r['name']} — extra time {period_label(per)}", due, f"{per['_id']}:overage")
        await ctx.data.retainers.update({"_id": r["_id"]}, {"current_period_id": None})
    return per


async def run_due(ctx, r):
    """Close every period that has ended (catching up after downtime), handle end date and renewal."""
    n = 0
    t = today().isoformat()
    for _ in range(36):
        per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
        if not per:
            break
        end_date = r.get("end_date")
        if end_date and end_date <= t and end_date < per["end"]:
            if await close_period(ctx, r, per, end_on=end_date, force_lapse=True):
                n += 1
            await ctx.data.retainers.update({"_id": r["_id"]}, {"status": "ended", "ended_at": now()})
            break
        if per["end"] > t:
            break
        if await close_period(ctx, r, per):
            n += 1
        r = await ctx.data.retainers.get(r["_id"])
    r = await ctx.data.retainers.get(r["_id"])
    if r.get("end_date") and r["status"] == "active" and r["end_date"] <= t:
        await ctx.data.retainers.update({"_id": r["_id"]}, {"status": "ended", "ended_at": now()})
    if r.get("end_date") and r["status"] == "active":
        warn = (Date.fromisoformat(r["end_date"]) - timedelta(days=int(r.get("renewal_days") or 30))).isoformat()
        if warn <= t:
            got = await ctx.data.retainers.find_one_and_update({"_id": r["_id"], "renewal_notified": {"$ne": True}},
                                                               {"$set": {"renewal_notified": True}})
            if got:
                await emit(ctx, "retainer.renewal_due", {"retainer_id": r["_id"], "end_date": r["end_date"]}, r["project_ids"][0])
                await notify(ctx, f"{r['name']} ends on {fmt_date(r['end_date'])}. The follow-up agent has drafted a renewal note.",
                             "retainer", link=f"/retainers/{r['_id']}")
    return n


# ---------------- hooks from time tracking ----------------

async def retainer_of(ctx, project_id):
    return await ctx.data.retainers.find_one({"project_ids": project_id, "status": {"$in": ["active", "paused"]}})


async def on_time_entry(ctx, e):
    """Time dated inside a closed period counts in the current period, as an adjustment."""
    if e.get("adjustment_period_id") or e.get("billing_status") == "non_billable":
        return
    r = await retainer_of(ctx, e["project_id"])
    if not r:
        return
    per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "start": {"$lte": e["date"]}, "end": {"$gt": e["date"]}})
    if per and per["status"] != "open":
        cur = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
        if cur:
            await ctx.data.time_entries.update({"_id": e["_id"]}, {"adjustment_period_id": cur["_id"], "adjustment": True})


async def check_usage(ctx, project_id):
    r = await retainer_of(ctx, project_id)
    if not r or r["kind"] != "hours":
        return
    per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
    if not per:
        return
    n = await period_numbers(ctx, r, per)
    if not n["available"]:
        return
    pct = n["used"] * 100 / n["available"]
    for t in sorted({int(r.get("alert_pct") or 80), 100}):
        if pct < t:
            continue
        got = await ctx.data.retainer_periods.find_one_and_update({"_id": per["_id"], "alerts_sent": {"$ne": t}}, {"$addToSet": {"alerts_sent": t}})
        if got:
            await emit(ctx, "retainer.usage_threshold", {"retainer_id": r["_id"], "period_id": per["_id"], "pct": t,
                                                         "client_note": t == int(r.get("alert_pct") or 80)}, project_id)
            await notify(ctx, f"{r['name']}: {t}% of this period's hours used ({h(n['used'])} of {h(n['available'])}).", "retainer",
                         link=f"/retainers/{r['_id']}")


# ---------------- actions ----------------

class RetainerIn(P):
    id: Optional[str] = None
    name: str = "Advisory retainer"
    project_id: Optional[str] = None
    project_ids: Optional[list] = None
    contact_id: Optional[str] = None
    kind: str = "hours"
    period: str = "monthly"
    start_date: Optional[str] = None
    fee_paise: int = 0
    included_hours: Optional[float] = None
    included_days: Optional[float] = None
    cap_paise: Optional[int] = None
    overage_rate_paise: Optional[int] = None
    billing: str = "advance"
    rollover: Optional[dict] = None     # {mode: none|capped|all, cap_hours, valid_periods: 1..3}
    overage: Optional[dict] = None      # {mode: bill|borrow|absorb|ask, borrow_cap_hours}
    alert_pct: Optional[int] = None
    statement_entries_visible: Optional[bool] = None
    auto_send: bool = False
    task_template_id: Optional[str] = None
    end_date: Optional[str] = None
    notice_days: int = 30
    renewal_days: int = 30
    adopt_recurring_id: Optional[str] = None


def _defaults(ws):
    s = (ws.get("settings") or {}).get("retainer_defaults") or {}
    return {"rollover": s.get("rollover") or {"mode": "capped", "cap_pct": 25, "valid_periods": 1},
            "overage": s.get("overage") or {"mode": "bill"}, "alert_pct": s.get("alert_pct") or 80,
            "statement_entries_visible": bool(s.get("statement_entries_visible", False))}


async def _plan(ctx, p: RetainerIn):
    ws = await ctx.ws()
    d = _defaults(ws)
    if p.kind not in KINDS:
        raise AppError("invalid", "Choose hours bank, fixed scope, or pay as used with a cap.", 400)
    if p.period not in ("monthly", "quarterly"):
        raise AppError("invalid", "A retainer period is monthly or quarterly.", 400)
    if p.billing not in ("advance", "arrears"):
        raise AppError("invalid", "Bill in advance or in arrears.", 400)
    inc = int(round((p.included_hours or 0) * 60 + (p.included_days or 0) * rates.day_hours(ws) * 60))
    if p.kind == "hours" and inc <= 0:
        raise AppError("invalid", "How many hours (or days) are included each period?", 400)
    if p.kind in ("hours", "fixed") and p.fee_paise <= 0:
        raise AppError("invalid", "Enter the fee for each period.", 400)
    if p.kind == "payg" and not (p.cap_paise and p.cap_paise > 0):
        raise AppError("invalid", "Pay-as-used needs a monthly cap.", 400)
    ro = dict(p.rollover or d["rollover"])
    if ro.get("mode") not in ROLLOVER:
        raise AppError("invalid", "Rollover is none, up to a cap, or everything.", 400)
    cap_m = int(round(float(ro["cap_hours"]) * 60)) if ro.get("cap_hours") is not None else inc * int(ro.get("cap_pct") or 25) // 100
    vp = int(ro.get("valid_periods") or 1)
    if not 1 <= vp <= 3:
        raise AppError("invalid", "Carried hours can stay valid for 1, 2 or 3 periods.", 400)
    ov = dict(p.overage or d["overage"])
    if ov.get("mode") not in OVERAGE:
        raise AppError("invalid", "Extra time is billed, borrowed from next period, absorbed, or asked about first.", 400)
    return {"name": p.name.strip()[:80] or "Retainer", "kind": p.kind, "period": p.period, "fee_paise": int(p.fee_paise),
            "included_minutes": inc if p.kind == "hours" else 0, "cap_paise": int(p.cap_paise or 0), "billing": p.billing if p.kind != "payg" else "arrears",
            "overage_rate_paise": int(p.overage_rate_paise) if p.overage_rate_paise else None,
            "rollover": {"mode": ro["mode"], "cap_minutes": cap_m, "valid_periods": vp},
            "overage": {"mode": ov["mode"], "borrow_cap_minutes": int(round(float(ov.get("borrow_cap_hours") or 0) * 60)) or inc}}


@action("retainers.create", "money", RetainerIn, roles=ADMINS | {"manager"},
        desc="Set up a retainer: hours bank, fixed scope or pay-as-used with a cap; period; billing; rollover and overage rules.")
async def retainers_create(ctx, p: RetainerIn):
    await limits.require(ctx, "retainers")
    pids = p.project_ids or ([p.project_id] if p.project_id else [])
    if not pids:
        raise AppError("invalid", "Choose the project this retainer is for.", 400)
    prs = [await perm.project(ctx, x, act=True) for x in pids]
    for x in pids:
        if await retainer_of(ctx, x):
            raise AppError("invalid", "That project already has a retainer.", 400)
    await limits.check_count(ctx, "active_retainers", await ctx.data.retainers.count({"status": {"$in": ["active", "paused"]}}))
    plan = await _plan(ctx, p)
    ws = await ctx.ws()
    d = _defaults(ws)
    start = (p.start_date or today().isoformat())[:10]
    r = await ctx.data.retainers.insert(dict(plan, project_ids=pids, contact_id=p.contact_id or (prs[0].get("contact_ids") or [None])[0],
                                             start_date=start, status="active", alert_pct=int(p.alert_pct or d["alert_pct"]),
                                             statement_entries_visible=d["statement_entries_visible"] if p.statement_entries_visible is None
                                             else p.statement_entries_visible, auto_send=p.auto_send, task_template_id=p.task_template_id,
                                             end_date=p.end_date[:10] if p.end_date else None, notice_days=p.notice_days,
                                             renewal_days=p.renewal_days, renewal_notified=False, pending_plan=None,
                                             recurring_invoice_id=p.adopt_recurring_id))
    # One source for the budget: the retainer.
    for x in pids:
        await ctx.data.budgets.update_many({"project_id": x, "active": True}, {"active": False, "removed_at": now(), "replaced_by": r["_id"]})
        await ctx.data.projects.update({"_id": x}, {"budget": None, "retainer_id": r["_id"]})
    if p.adopt_recurring_id:
        rec = await ctx.data.recurring_invoices.get(p.adopt_recurring_id)
        if rec:
            await ctx.data.recurring_invoices.update({"_id": rec["_id"]}, {"active": False, "adopted_by": r["_id"]})
    per, _ = await open_period(ctx, r, start, 1)
    await ctx.data.retainers.update({"_id": r["_id"]}, {"current_period_id": per["_id"]})
    await log(ctx, pids[0], "retainer", f"Retainer set up: {plan['name']}", ref=r["_id"])
    await audit(ctx, "retainer.create", r["_id"], {"kind": plan["kind"]})
    await run_due(ctx, await ctx.data.retainers.get(r["_id"]))
    return await view(ctx, await ctx.data.retainers.get(r["_id"]))


@action("retainers.update", "money", RetainerIn, roles=ADMINS | {"manager"},
        desc="Change a retainer. Plan changes (fee, hours, rules, billing) start from the next period; alerts and settings change now.")
async def retainers_update(ctx, p: RetainerIn):
    r = await get_r(ctx, p.id, act=True)
    plan = await _plan(ctx, p)
    now_fields = {"name": plan.pop("name"), "auto_send": p.auto_send, "task_template_id": p.task_template_id,
                  "end_date": p.end_date[:10] if p.end_date else None, "notice_days": p.notice_days, "renewal_days": p.renewal_days}
    if p.alert_pct:
        now_fields["alert_pct"] = int(p.alert_pct)
    if p.statement_entries_visible is not None:
        now_fields["statement_entries_visible"] = p.statement_entries_visible
    if now_fields["end_date"] != r.get("end_date"):
        now_fields["renewal_notified"] = False
    changed = {k: v for k, v in plan.items() if r.get(k) != v}
    await ctx.data.retainers.update({"_id": r["_id"]}, dict(now_fields, pending_plan=changed or None))
    await audit(ctx, "retainer.update", r["_id"], {"pending": list(changed)})
    out = await view(ctx, await ctx.data.retainers.get(r["_id"]))
    out["note"] = "Plan changes start from the next period." if changed else None
    return out


class IdIn(P):
    id: str


async def get_r(ctx, rid, act=False):
    r = await ctx.data.retainers.get(rid)
    if not r:
        raise not_found("That retainer")
    await perm.project(ctx, r["project_ids"][0], act=act)
    return r


@action("retainers.pause", "money", IdIn, roles=ADMINS | {"manager"},
        desc="Pause a retainer: this period completes, no new period opens and no new invoice is raised.")
async def retainers_pause(ctx, p: IdIn):
    r = await get_r(ctx, p.id, act=True)
    if r["status"] != "active":
        raise AppError("invalid", "Only an active retainer can be paused.", 400)
    await ctx.data.retainers.update({"_id": r["_id"]}, {"status": "paused", "paused_at": now()})
    await log(ctx, r["project_ids"][0], "retainer", f"{r['name']} paused from the next period", ref=r["_id"])
    return {"ok": True}


@action("retainers.resume", "money", IdIn, roles=ADMINS | {"manager"}, desc="Resume a paused retainer. A new period starts today if none is open.")
async def retainers_resume(ctx, p: IdIn):
    r = await get_r(ctx, p.id, act=True)
    if r["status"] != "paused":
        raise AppError("invalid", "This retainer isn't paused.", 400)
    await ctx.data.retainers.update({"_id": r["_id"]}, {"status": "active", "paused_at": None})
    r = await ctx.data.retainers.get(r["_id"])
    if not await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"}):
        last = await ctx.data.retainer_periods.find({"retainer_id": r["_id"]}, sort=[("index", -1)], limit=1)
        last_out = (last[0].get("carried_out") or []) if last else []
        per, _ = await open_period(ctx, dict(r, start_date=today().isoformat()), today().isoformat(), (last[0]["index"] + 1) if last else 1, last_out)
        await ctx.data.retainers.update({"_id": r["_id"]}, {"current_period_id": per["_id"]})
    return {"ok": True}


class EndIn(P):
    id: str
    end_date: Optional[str] = None


@action("retainers.end", "money", EndIn, roles=ADMINS | {"manager"},
        desc="End a retainer on a date. If that's mid-period, the period closes on that date and unused hours lapse.")
async def retainers_end(ctx, p: EndIn):
    r = await get_r(ctx, p.id, act=True)
    on = (p.end_date or today().isoformat())[:10]
    await ctx.data.retainers.update({"_id": r["_id"]}, {"end_date": on})
    n = await run_due(ctx, await ctx.data.retainers.get(r["_id"]))
    r = await ctx.data.retainers.get(r["_id"])
    return {"ok": True, "status": r["status"], "closed_periods": n}


async def view(ctx, r):
    o = clean(r)
    per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
    o["kind_label"] = KINDS[r["kind"]]
    o["current"] = dict(clean(per), **(await period_numbers(ctx, r, per)), label=period_label(per)) if per else None
    c = await ctx.data.contacts.get(r.get("contact_id") or "") or {}
    o["client"] = c.get("name")
    prs = await ctx.data.projects.find({"_id": {"$in": r["project_ids"]}}, projection={"name": 1})
    o["projects"] = [{"id": x["_id"], "name": x["name"]} for x in prs]
    if per:
        o["next_invoice"] = per["end"] if r["billing"] == "arrears" or r["kind"] == "payg" else per["end"]
    o["renewal_on"] = (Date.fromisoformat(r["end_date"]) - timedelta(days=int(r.get("renewal_days") or 30))).isoformat() if r.get("end_date") else None
    return o


@action("retainers.list", "read", desc="All retainers: client, plan, used this period, next invoice, renewal.")
async def retainers_list(ctx, p):
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    return [await view(ctx, r) for r in await ctx.data.retainers.find({"project_ids": {"$in": vis}}, sort=[("status", 1), ("created_at", -1)])]


@action("retainers.get", "read", IdIn, desc="A retainer: plan, this period's meter, period history, entries and invoices.")
async def retainers_get(ctx, p: IdIn):
    from app.domain.billing.timebill import decorate
    r = await get_r(ctx, p.id)
    o = await view(ctx, r)
    o["periods"] = [dict(clean(x), label=period_label(x), **(await period_numbers(ctx, r, x)))
                    for x in await ctx.data.retainer_periods.find({"retainer_id": r["_id"]}, sort=[("index", -1)])]
    per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
    if per:
        rows, adj = await entries_of(ctx, r, per)
        o["entries"] = await decorate(ctx, rows + adj)
    o["invoices"] = [{"id": i["_id"], "number": i.get("number"), "title": i["title"], "status": i["status"], "total_paise": i["totals"]["total"]}
                     for i in await ctx.data.invoices.find({"retainer_id": r["_id"]}, sort=[("created_at", -1)])]
    return o


class StmtIn(P):
    id: Optional[str] = None
    project_name: Optional[str] = None
    period_id: Optional[str] = None


async def statement(ctx, r, per, for_client=False):
    n = await period_numbers(ctx, r, per)
    out = {"retainer": r["name"], "kind": r["kind"], "kind_label": KINDS[r["kind"]], "period": period_label(per), "start": per["start"],
           "end": per["end"], "status": per["status"], **n,
           "summary": (f"{period_label(per)}: {h(n['used'])} used of {h(n['available'])} ({h(n['left'])} left)"
                       + (f", including {h(n['carried_in_minutes'])} carried in" if n["carried_in_minutes"] else "") + "."
                       if r["kind"] == "hours" else f"{period_label(per)}: {h(n['used'])} of work so far.")}
    if not for_client or r.get("statement_entries_visible"):
        from app.domain.billing.timebill import decorate
        rows, adj = await entries_of(ctx, r, per)
        out["entries"] = [{"date": fmt_date(e["date"]), "hours": round(e["minutes"] / 60, 2), "note": e.get("note") or "",
                           "task": e.get("task") or "", "adjustment": bool(e.get("adjustment"))} for e in await decorate(ctx, rows + adj)]
    return out


@action("retainers.statement", "read", StmtIn, desc="This period's statement: included, carried in, used, left (by retainer id or client name).")
async def retainers_statement(ctx, p: StmtIn):
    if p.id:
        r = await get_r(ctx, p.id)
    else:
        rx = {"$regex": (p.project_name or "").strip()[:60], "$options": "i"}
        cs = [c["_id"] for c in await ctx.data.contacts.find({"$or": [{"name": rx}, {"company": rx}]})]
        prs = [x["_id"] for x in await ctx.data.projects.find({"$or": [{"name": rx}, {"contact_ids": {"$in": cs}}], **perm.visible_filter(ctx)})]
        r = await ctx.data.retainers.find_one({"project_ids": {"$in": prs}, "status": {"$in": ["active", "paused"]}})
        if not r:
            raise not_found("A retainer for that client")
    per = await ctx.data.retainer_periods.get(p.period_id) if p.period_id else \
        await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"}) or \
        (await ctx.data.retainer_periods.find({"retainer_id": r["_id"]}, sort=[("index", -1)], limit=1) or [None])[0]
    if not per:
        raise not_found("A period on this retainer")
    return await statement(ctx, r, per)


@action("retainers.close_period", "money", IdIn, roles=ADMINS,
        desc="Close any period that has ended now, instead of waiting for tonight's job.")
async def retainers_close(ctx, p: IdIn):
    r = await get_r(ctx, p.id, act=True)
    n = await run_due(ctx, r)
    return {"ok": True, "closed": n, "summary": f"Closed {n} period{'s' if n != 1 else ''}." if n else "No period has ended yet."}


class PeriodIn(P):
    period_id: str


@action("retainers.bill_overage", "money", PeriodIn, roles=ADMINS | {"manager"}, agent_ok=False,
        desc="Bill the extra time from a closed retainer period (when the rule is 'ask first').")
async def retainers_bill_overage(ctx, p: PeriodIn):
    per = await ctx.data.retainer_periods.find_one_and_update({"_id": p.period_id, "overage_pending_minutes": {"$gt": 0}},
                                                              {"$set": {"overage_decided": "bill"}})
    if not per or per.get("overage_decided") != "bill" or per.get("overage_billed_minutes"):
        raise AppError("gone", "This extra time was already decided.", 409)
    r = await ctx.data.retainers.get(per["retainer_id"])
    mins = per["overage_pending_minutes"]
    line = overage_line(mins, await overage_rate(ctx, r), period_label(per))
    await ctx.data.retainer_periods.update({"_id": per["_id"]}, {"overage_billed_minutes": mins, "overage_pending_minutes": 0})
    nxt = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
    inv = await ctx.data.invoices.find_one({"retainer_period_id": (nxt or {}).get("_id"), "status": "draft"}) if nxt else None
    if inv:
        from app.domain.billing.money import save_invoice
        inv["lines"].append(line)
        await save_invoice(ctx, inv)
    else:
        await raise_invoice(ctx, r, per, [line], f"{r['name']} — extra time {period_label(per)}", today() + timedelta(days=7), f"{per['_id']}:overage")
    return {"ok": True}


@action("retainers.absorb_overage", "internal", PeriodIn, roles=ADMINS | {"manager"}, agent_ok=False,
        desc="Don't bill the extra time from a retainer period; it shows as non-billable in reports.")
async def retainers_absorb(ctx, p: PeriodIn):
    per = await ctx.data.retainer_periods.get(p.period_id)
    if not per or not per.get("overage_pending_minutes"):
        raise AppError("gone", "This extra time was already decided.", 409)
    await ctx.data.retainer_periods.update({"_id": per["_id"]}, {"absorbed_minutes": per["overage_pending_minutes"],
                                                                  "overage_pending_minutes": 0, "overage_decided": "absorb"})
    return {"ok": True}


async def from_file(ctx, f):
    """A client accepted a retainer plan in a proposal: set it up (once)."""
    from app.domain.documents.files import blocks_of
    blocks = [b for _, b in blocks_of(f.get("pages") or [], "retainer")]
    if not blocks:
        return None
    got = await ctx.data.client_files.find_one_and_update({"_id": f["_id"], "retainer_created": {"$ne": True}}, {"$set": {"retainer_created": True}})
    if not got or await retainer_of(ctx, f["project_id"]):
        return None
    b = blocks[0]
    p = RetainerIn(name=b.get("name") or "Advisory retainer", project_id=f["project_id"], kind=b.get("kind", "hours"),
                   period=b.get("period", "monthly"), fee_paise=int(b.get("fee_paise") or 0), included_hours=b.get("included_hours"),
                   cap_paise=b.get("cap_paise"), billing=b.get("billing", "advance"), rollover=b.get("rollover"), overage=b.get("overage"))
    return await retainers_create(ctx, p)


async def run_all(ws_id):
    from app.core.context import system_ctx
    ctx = system_ctx(ws_id)
    n = 0
    for r in await ctx.data.retainers.find({"status": {"$in": ["active", "paused"]}}):
        n += await run_due(ctx, r)
    return n


# ---------------- task templates and recurring tasks (4.10) ----------------

class TplIn(P):
    id: Optional[str] = None
    name: str
    items: list   # [{title, estimate_hours?, due_days?, assignee_role?}]


@action("task_templates.list", "read", roles=STAFF, desc="Saved checklists that can be applied to a project, a stage or each retainer period.")
async def tpl_list(ctx, p):
    return clean(await ctx.data.task_templates.find({}, sort=[("name", 1)]))


@action("task_templates.create", "internal", TplIn, roles=ADMINS | {"manager"}, desc="Save a checklist of tasks (titles, estimates, due days, who).")
async def tpl_save(ctx, p: TplIn):
    await limits.require(ctx, "task_templates")
    items = []
    for it in p.items[:60]:
        if not (it.get("title") or "").strip():
            continue
        items.append({"title": it["title"].strip()[:200], "estimate_minutes": int(round(float(it.get("estimate_hours") or 0) * 60)) or None,
                      "due_days": int(it.get("due_days") or 0), "assignee_role": it.get("assignee_role") or "project_owner"})
    if not items:
        raise AppError("invalid", "Add at least one task.", 400)
    doc = {"name": p.name.strip()[:80] or "Checklist", "items": items}
    if p.id:
        await ctx.data.task_templates.update({"_id": p.id}, doc)
        return clean(await ctx.data.task_templates.get(p.id))
    return clean(await ctx.data.task_templates.insert(doc))


@action("task_templates.delete", "destructive", IdIn, roles=ADMINS | {"manager"}, agent_ok=False, desc="Delete a task template.")
async def tpl_delete(ctx, p: IdIn):
    await ctx.data.task_templates.soft_delete({"_id": p.id})
    await ctx.data.stages.update_many({"task_template_id": p.id}, {"task_template_id": None})
    return {"ok": True}


async def assignee_for(ctx, role, project):
    if role in (None, "", "project_owner"):
        return project.get("owner_id") or (await ctx.ws())["owner_id"]
    m = await ctx.data.memberships.find_one({"role": role, "active": True})
    return m["user_id"] if m and not str(m["user_id"]).startswith("pending:") else project.get("owner_id")


async def apply_template(ctx, tpl, project_id, base_date: str, key_prefix: str):
    """Create the checklist's tasks. The same key never creates the same task twice."""
    from datetime import datetime
    pr = await ctx.data.projects.get(project_id)
    if not pr:
        return 0
    base = Date.fromisoformat(base_date[:10])
    n = 0
    for i, it in enumerate(tpl["items"]):
        due = datetime.combine(base + timedelta(days=int(it.get("due_days") or 0)), datetime.min.time(), IST).replace(hour=18)
        try:
            await ctx.data.tasks.insert({"title": it["title"], "project_id": project_id, "assignee_id": await assignee_for(ctx, it.get("assignee_role"), pr),
                                         "due_at": due, "done": False, "created_by": ctx.actor, "reminded": False,
                                         "estimate_minutes": it.get("estimate_minutes"), "audience": "team", "template_id": tpl["_id"],
                                         "occurrence_key": f"{key_prefix}:{i}"})
            n += 1
        except DuplicateKeyError:
            pass
    if n:
        await log(ctx, project_id, "task", f"Checklist \"{tpl['name']}\" added ({n} task{'s' if n != 1 else ''})")
    return n


class ApplyIn(P):
    template_id: str
    project_id: str
    start_date: Optional[str] = None


@action("task_templates.apply", "internal", ApplyIn, roles=STAFF, desc="Add a saved checklist to a project.")
async def tpl_apply(ctx, p: ApplyIn):
    await perm.project(ctx, p.project_id, act=True)
    tpl = await ctx.data.task_templates.get(p.template_id)
    if not tpl:
        raise not_found("That checklist")
    base = (p.start_date or today().isoformat())[:10]
    n = await apply_template(ctx, tpl, p.project_id, base, f"tpl:{tpl['_id']}:{p.project_id}:{base}")
    return {"ok": True, "created": n, "summary": f"Added {n} task{'s' if n != 1 else ''}." if n else "Those tasks are already there."}


class StageTpl(P):
    stage_id: str
    template_id: Optional[str] = None


@action("stages.set_task_template", "internal", StageTpl, roles=ADMINS, desc="Add a checklist to every project when it enters a stage.")
async def stage_tpl(ctx, p: StageTpl):
    if not await ctx.data.stages.get(p.stage_id):
        raise not_found("That stage")
    await ctx.data.stages.update({"_id": p.stage_id}, {"task_template_id": p.template_id})
    return {"ok": True}


async def on_stage_entered(ctx, project_id, stage_id):
    st = await ctx.data.stages.get(stage_id)
    if st and st.get("task_template_id"):
        tpl = await ctx.data.task_templates.get(st["task_template_id"])
        if tpl:
            await apply_template(ctx, tpl, project_id, today().isoformat(), f"stage:{stage_id}:{project_id}:{tpl['_id']}")


class RecurIn(P):
    id: str
    every: str = "monthly"   # none | weekly | monthly | quarterly
    day: Optional[int] = None


def next_due(d: Date, every: str, day=None) -> Date:
    if every == "weekly":
        nd = d + timedelta(days=7)
        return nd + timedelta(days=(int(day) - nd.weekday()) % 7) if day is not None else nd
    return add_months(d, 3 if every == "quarterly" else 1, int(day) if day else d.day)


@action("tasks.set_recurrence", "internal", RecurIn, roles=STAFF, desc="Repeat a task weekly, monthly or quarterly on a chosen day.")
async def tasks_set_recurrence(ctx, p: RecurIn):
    t = await ctx.data.tasks.get(p.id)
    if not t:
        raise not_found("That task")
    if t.get("project_id"):
        await perm.project(ctx, t["project_id"], act=True)
    if p.every not in ("none", "weekly", "monthly", "quarterly"):
        raise AppError("invalid", "Repeat weekly, monthly or quarterly.", 400)
    if p.every != "none" and not t.get("due_at"):
        raise AppError("invalid", "Give the task a due date first, so we know when it repeats.", 400)
    if p.day is not None and (p.every == "weekly" and not 0 <= p.day <= 6 or p.every != "weekly" and not 1 <= p.day <= 31):
        raise AppError("invalid", "Pick a weekday (Mon–Sun) or a day of the month.", 400)
    series = t.get("series_id") or t["_id"]
    rec = None if p.every == "none" else {"every": p.every, "day": p.day}
    await ctx.data.tasks.update({"_id": t["_id"]}, {"recurrence": rec, "series_id": series if rec else None})
    return {"ok": True}


async def recurring_tasks(ws_id):
    """Job: create the next occurrence of each repeating task once the current one is due. Never twice."""
    from app.core.context import system_ctx
    from app.core.util import aware
    ctx = system_ctx(ws_id)
    n = 0
    t_now = now()
    for root in await ctx.data.tasks.find({"recurrence": {"$ne": None}, "series_id": {"$ne": None}}):
        if root["series_id"] != root["_id"]:
            continue
        latest = (await ctx.data.tasks.find({"series_id": root["_id"]}, sort=[("due_at", -1)], limit=1) or [root])[0]
        if not latest.get("due_at") or aware(latest["due_at"]) > t_now:
            continue
        rec = root["recurrence"]
        d = aware(latest["due_at"]).astimezone(IST)
        nd = next_due(d.date(), rec["every"], rec.get("day"))
        due = d.replace(year=nd.year, month=nd.month, day=nd.day)
        try:
            await ctx.data.tasks.insert({k: v for k, v in root.items() if k not in ("_id", "created_at", "updated_at", "done", "done_at",
                                                                                    "occurrence_key", "recurrence", "reminded")}
                                        | {"due_at": due, "done": False, "reminded": False, "series_id": root["_id"], "recurrence": None,
                                           "occurrence_key": f"rec:{root['_id']}:{nd.isoformat()}"})
            n += 1
        except DuplicateKeyError:
            pass
    return n
