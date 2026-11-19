"""Project budgets (add-on A3): an early warning before a project stops paying.

A budget is a fee (paise) or time (minutes). It can reset weekly, monthly or
quarterly; unused budget never carries over (that's what retainers are for).
Each alert fires once per cycle, guarded by the cycle document itself.

Forecast (same method Bonsai documents): a task counts if it isn't done, is
due in the current cycle, has an estimate, and the estimate is more than the
time logged on it. Remaining = estimate - logged. Overdue tasks sit on today.
"""
from datetime import date as Date
from datetime import timedelta
from typing import Optional

from pymongo.errors import DuplicateKeyError

from app.domain import perm
from app.domain.billing import rates
from app.domain.registry import ADMINS, STAFF, P, action
from app.core import limits
from app.core.events import emit, notify
from app.core.util import IST, AppError, clean, fmt_date, inr, not_found, now

RESETS = ("none", "weekly", "monthly", "quarterly")
FAR = "9999-12-31"


def today():
    return now().astimezone(IST).date()


def window(b, on: Date):
    """The cycle containing a date: (start, end) as ISO dates, end exclusive."""
    r = b.get("reset", "none")
    if r == "weekly":
        s = on - timedelta(days=on.weekday())
        return s.isoformat(), (s + timedelta(days=7)).isoformat()
    if r == "monthly":
        s = on.replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1)
        return s.isoformat(), e.isoformat()
    if r == "quarterly":
        s = on.replace(month=(on.month - 1) // 3 * 3 + 1, day=1)
        e = s
        for _ in range(3):
            e = (e + timedelta(days=32)).replace(day=1)
        return s.isoformat(), e.isoformat()
    return b.get("start_date") or "2000-01-01", FAR


def amount_of(b) -> int:
    return int(b["amount_paise"] if b["type"] == "fee" else b["amount_minutes"])


async def used_in(ctx, b, start, end):
    from app.domain.billing.timebill import amount, billed_expense
    f = {"project_id": b["project_id"], "billing_status": {"$ne": "non_billable"}, "date": {"$gte": start, "$lt": end}}
    mins = fee = 0
    for e in await ctx.data.time_entries.find(f, projection={"minutes": 1, "rate_snapshot_paise": 1}):
        mins += e["minutes"]
        fee += amount(e)
    if b["type"] == "fee":
        if b.get("counts") == "expenses":
            fee = 0
        if b.get("counts") in ("expenses", "both"):
            for x in await ctx.data.expenses.find({"project_id": b["project_id"], "billable": True, "date": {"$gte": start, "$lt": end}}):
                fee += billed_expense(x)
    used = fee if b["type"] == "fee" else mins
    amt = amount_of(b)
    return {"used": used, "used_minutes": mins, "used_paise": fee, "amount": amt,
            "pct": round(used * 100 / amt, 1) if amt else 0.0, "left": max(0, amt - used)}


async def active_budget(ctx, project_id):
    return await ctx.data.budgets.find_one({"project_id": project_id, "active": True})


async def retainer_for(ctx, project_id):
    return await ctx.data.retainers.find_one({"project_ids": project_id, "status": {"$in": ["active", "paused"]}})


async def cycle_doc(ctx, b, start, end):
    key = f"{b['_id']}:{start}"
    try:
        return await ctx.data.budget_cycles.find_one_and_update(
            {"cycle_key": key}, {"$setOnInsert": {"cycle_key": key, "budget_id": b["_id"], "project_id": b["project_id"], "start": start,
                                                  "end": end, "alerts_sent": []}}, upsert=True)
    except DuplicateKeyError:
        # Another check created this cycle at the same moment: use theirs.
        return await ctx.data.budget_cycles.find_one({"cycle_key": key})


def fmt_amount(b, v):
    return inr(v) if b["type"] == "fee" else f"{round(v / 60, 1)} hours"


async def check(ctx, project_id):
    """Recalculate the current cycle and fire any alert that is due (once each)."""
    b = await active_budget(ctx, project_id)
    if not b:
        return None
    start, end = window(b, today())
    cyc = await cycle_doc(ctx, b, start, end)
    u = await used_in(ctx, b, start, end)
    await ctx.data.budget_cycles.update({"_id": cyc["_id"]}, {"used_minutes": u["used_minutes"], "used_paise": u["used_paise"], "pct": u["pct"]})
    pr = await ctx.data.projects.get(project_id)
    for t in sorted(b.get("thresholds") or [80, 100]):
        if u["pct"] < t:
            continue
        got = await ctx.data.budget_cycles.find_one_and_update({"_id": cyc["_id"], "alerts_sent": {"$ne": t}}, {"$addToSet": {"alerts_sent": t}})
        if not got:
            continue
        who = [x for x in {(pr or {}).get("owner_id"), (await ctx.ws())["owner_id"]} if x]
        await notify(ctx, f"{(pr or {}).get('name', 'A project')}: {t}% of the budget used ({fmt_amount(b, u['used'])} of {fmt_amount(b, u['amount'])}).",
                     "budget", link=f"/projects/{project_id}?tab=budget", user_ids=who)
        await emit(ctx, "budget.threshold_reached", {"budget_id": b["_id"], "pct": t, "used_pct": u["pct"]}, project_id)
        if t >= 100:
            await emit(ctx, "budget.exceeded", {"budget_id": b["_id"], "used_pct": u["pct"]}, project_id)
    summary = {"type": b["type"], "pct": u["pct"], "used": u["used"], "amount": u["amount"], "cycle_start": start,
               "cycle_end": None if end == FAR else end, "reset": b.get("reset", "none")}
    await ctx.data.projects.update({"_id": project_id}, {"budget": summary})
    return summary


# ---------------- actions ----------------

class BudgetIn(P):
    project_id: str
    type: str = "fee"                 # fee | time
    amount_paise: Optional[int] = None
    amount_hours: Optional[float] = None
    amount_days: Optional[float] = None
    counts: str = "time"              # time | expenses | both
    reset: str = "none"               # none | weekly | monthly | quarterly
    thresholds: Optional[list] = None
    start_date: Optional[str] = None


async def _validate(ctx, p: BudgetIn):
    if p.type not in ("fee", "time"):
        raise AppError("invalid", "A budget is a fee or time.", 400)
    if p.counts not in ("time", "expenses", "both"):
        raise AppError("invalid", "Count billable time, billable expenses, or both.", 400)
    if p.reset not in RESETS:
        raise AppError("invalid", "Reset is none, weekly, monthly or quarterly.", 400)
    ws = await ctx.ws()
    doc = {"type": p.type, "counts": p.counts if p.type == "fee" else "time", "reset": p.reset,
           "thresholds": sorted({int(t) for t in (p.thresholds or (ws.get("settings") or {}).get("budget_alerts") or [80, 100]) if 1 <= int(t) <= 200}),
           "start_date": (p.start_date or today().isoformat())[:10]}
    if p.type == "fee":
        if not p.amount_paise or p.amount_paise <= 0:
            raise AppError("invalid", "Enter the budget amount.", 400)
        doc["amount_paise"], doc["amount_minutes"] = int(p.amount_paise), None
    else:
        mins = int(round((p.amount_hours or 0) * 60 + (p.amount_days or 0) * rates.day_hours(ws) * 60))
        if mins <= 0:
            raise AppError("invalid", "Enter the budget in hours or days.", 400)
        doc["amount_minutes"], doc["amount_paise"] = mins, None
    return doc


@action("budgets.create", "internal", BudgetIn, roles=ADMINS | {"manager"},
        desc="Give a project a budget: a fee or hours/days, what counts, optional weekly/monthly/quarterly reset, alert points.")
async def budgets_create(ctx, p: BudgetIn):
    await limits.require(ctx, "budgets")
    await perm.project(ctx, p.project_id, act=True)
    if await retainer_for(ctx, p.project_id):
        raise AppError("invalid", "This project's budget comes from its retainer. Change the retainer instead.", 400)
    if await active_budget(ctx, p.project_id):
        raise AppError("invalid", "This project already has a budget. Edit it instead.", 400)
    doc = await _validate(ctx, p)
    await ctx.data.budgets.insert(dict(doc, project_id=p.project_id, active=True, source="manual"))
    await check(ctx, p.project_id)
    return await budget_view(ctx, p.project_id)


@action("budgets.update", "internal", BudgetIn, roles=ADMINS | {"manager"}, desc="Change a project's budget.")
async def budgets_update(ctx, p: BudgetIn):
    await perm.project(ctx, p.project_id, act=True)
    b = await active_budget(ctx, p.project_id)
    if not b:
        raise not_found("A budget on this project")
    doc = await _validate(ctx, p)
    await ctx.data.budgets.update({"_id": b["_id"]}, doc)
    await check(ctx, p.project_id)
    return await budget_view(ctx, p.project_id)


class ProjIn(P):
    project_id: str


@action("budgets.remove", "internal", ProjIn, roles=ADMINS | {"manager"}, desc="Stop tracking a project's budget. History stays.")
async def budgets_remove(ctx, p: ProjIn):
    await perm.project(ctx, p.project_id, act=True)
    b = await active_budget(ctx, p.project_id)
    if not b:
        raise not_found("A budget on this project")
    await ctx.data.budgets.update({"_id": b["_id"]}, {"active": False, "removed_at": now()})
    await ctx.data.projects.update({"_id": p.project_id}, {"budget": None})
    return {"ok": True}


async def budget_view(ctx, project_id):
    b = await active_budget(ctx, project_id)
    if not b:
        r = await retainer_for(ctx, project_id)
        if r:
            from app.domain.billing.retainers import period_numbers
            per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
            if per:
                n = await period_numbers(ctx, r, per)
                return {"from_retainer": True, "retainer_id": r["_id"], "type": "time", "amount": n["available"], "used": n["used"],
                        "pct": round(n["used"] * 100 / n["available"], 1) if n["available"] else 0, "cycle_start": per["start"],
                        "cycle_end": per["end"], "reset": r["period"]}
        return None
    start, end = window(b, today())
    u = await used_in(ctx, b, start, end)
    hist = []
    for c in await ctx.data.budget_cycles.find({"budget_id": b["_id"], "start": {"$lt": start}}, sort=[("start", -1)], limit=12):
        hu = await used_in(ctx, b, c["start"], c["end"])
        hist.append({"start": c["start"], "end": c["end"], "used": hu["used"], "pct": hu["pct"], "alerts_sent": c.get("alerts_sent", [])})
    return dict(clean(b), **u, cycle_start=start, cycle_end=None if end == FAR else end, history=hist,
                next_reset=None if end == FAR else end, used_label=fmt_amount(b, u["used"]), amount_label=fmt_amount(b, u["amount"]))


@action("budgets.get", "read", ProjIn, desc="A project's budget: used, left, dates, next reset and past cycles.")
async def budgets_get(ctx, p: ProjIn):
    await perm.project(ctx, p.project_id)
    return await budget_view(ctx, p.project_id)


@action("budgets.forecast", "read", ProjIn, desc="Budget used so far (by day) and the forecast from open task estimates.")
async def budgets_forecast(ctx, p: ProjIn):
    from app.domain.billing.timebill import amount
    pr = await perm.project(ctx, p.project_id)
    b = await active_budget(ctx, p.project_id)
    if not b:
        raise not_found("A budget on this project")
    t0 = today()
    start, end = window(b, t0)
    u = await used_in(ctx, b, start, end)
    # Used so far, by day (solid line).
    daily = {}
    for e in await ctx.data.time_entries.find({"project_id": p.project_id, "billing_status": {"$ne": "non_billable"},
                                               "date": {"$gte": start, "$lt": end}}):
        daily[e["date"]] = daily.get(e["date"], 0) + (amount(e) if b["type"] == "fee" else e["minutes"])
    series, acc = [], 0
    for d in sorted(daily):
        acc += daily[d]
        series.append({"date": d, "value": acc})
    used_now = u["used"]
    # Forecast (dotted line).
    end_d = Date.fromisoformat(end) if end != FAR else None
    tasks = []
    for t in await ctx.data.tasks.find({"project_id": p.project_id, "done": False, "audience": {"$ne": "client"},
                                        "estimate_minutes": {"$gt": 0}}):
        due = t["due_at"].astimezone(IST).date() if t.get("due_at") else None
        if not due or due.isoformat() < start or (end_d and due >= end_d):
            continue
        logged = sum(e["minutes"] for e in await ctx.data.time_entries.find({"task_id": t["_id"]}, projection={"minutes": 1}))
        rem = int(t["estimate_minutes"]) - logged
        if rem <= 0:
            continue
        on = max(due, t0)
        rate = (await rates.resolve(ctx, pr, on.isoformat(), t.get("service_id"), t.get("assignee_id")))["hourly_paise"]
        add = rem * rate // 60 if b["type"] == "fee" else rem
        tasks.append({"task_id": t["_id"], "title": t["title"], "date": on.isoformat(), "estimate_minutes": t["estimate_minutes"],
                      "logged_minutes": logged, "remaining_minutes": rem, "rate_paise": rate, "adds": add, "overdue": due < t0})
    tasks.sort(key=lambda x: x["date"])
    fc, acc = [{"date": t0.isoformat(), "value": used_now}], used_now
    for t in tasks:
        acc += t["adds"]
        fc.append({"date": t["date"], "value": acc})
    total = acc
    return {"type": b["type"], "amount": u["amount"], "used": used_now, "forecast_total": total,
            "forecast_pct": round(total * 100 / u["amount"], 1) if u["amount"] else 0, "cycle_start": start,
            "cycle_end": None if end == FAR else end, "series": series, "forecast": fc, "tasks": tasks,
            "summary": f"Used {fmt_amount(b, used_now)} of {fmt_amount(b, u['amount'])}. With open task estimates: {fmt_amount(b, total)}"
                       + (" — over budget." if total > u["amount"] else ".")}


@action("budgets.at_risk", "read", desc="Projects at or over 80% of their budget.")
async def budgets_at_risk(ctx, p):
    rows = await ctx.data.projects.find({"budget.pct": {"$gte": 80}, "archived": False, **perm.visible_filter(ctx)}, sort=[("budget.pct", -1)])
    items = [{"project_id": r["_id"], "project": r["name"], **r["budget"]} for r in rows]
    over = [i for i in items if i["pct"] >= 100]
    return {"items": items, "summary": ("No project is near its budget." if not items else
                                        f"{len(over)} over budget, {len(items) - len(over)} past 80%: "
                                        + "; ".join(f"{i['project']} {i['pct']:.0f}%" for i in items[:6]) + ".")}


class EstIn(P):
    id: str
    minutes: Optional[int] = None
    hours: Optional[float] = None


@action("tasks.set_estimate", "internal", EstIn, roles=STAFF, desc="Set a task's estimate in hours. The task then shows estimate against time logged.")
async def tasks_set_estimate(ctx, p: EstIn):
    t = await ctx.data.tasks.get(p.id)
    if not t:
        raise not_found("That task")
    if t.get("project_id"):
        await perm.project(ctx, t["project_id"], act=True)
    mins = p.minutes if p.minutes is not None else int(round((p.hours or 0) * 60))
    if mins < 0 or mins > 1000 * 60:
        raise AppError("invalid", "The estimate must be between 0 and 1,000 hours.", 400)
    await ctx.data.tasks.update({"_id": t["_id"]}, {"estimate_minutes": mins or None})
    return {"ok": True, "estimate_minutes": mins}


async def check_all(ws_id):
    """Hourly job: resets and alerts for every active budget (time logged elsewhere, a new cycle starting)."""
    from app.core.context import system_ctx
    ctx = system_ctx(ws_id)
    n = 0
    for b in await ctx.data.budgets.find({"active": True}):
        await check(ctx, b["project_id"])
        n += 1
    return n


_ = fmt_date
