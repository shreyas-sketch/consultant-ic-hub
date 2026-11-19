"""Forecast, profit, effective rate and utilisation (add-on A6).

Forecast keeps two things apart and always shows both:
  confirmed  = invoice schedule items already agreed + active retainer fees (+ monthly invoices)
  pipeline   = each open opportunity's value, spread over months, x its stage's win chance (an estimate)

Profit by project / client / service: billed, received, hours, effective hourly
rate (received / hours), cost (hours x cost rate + expenses), margin. Fixed-fee
projects use the fee received, which is the point: it shows when a fee was too low.
"""
from collections import defaultdict
from datetime import date as Date
from datetime import timedelta
from typing import Optional

from app.domain import perm
from app.domain.billing import rates
from app.domain.registry import ADMINS, STAFF, P, action
from app.core import limits
from app.core.util import IST, AppError, aware, clean, inr, not_found, now

DEFAULT_PROB = {"enquiry": 10, "call_booked": 25, "proposal_sent": 50}


def month_add(mk: str, n: int) -> str:
    y, m = int(mk[:4]), int(mk[5:7]) - 1 + n
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def month_of(d) -> str:
    if hasattr(d, "astimezone"):
        d = aware(d).astimezone(IST)
    return str(d)[:7] if isinstance(d, str) else f"{d.year}-{d.month:02d}"


def prob_of(stage) -> int:
    if stage.get("win_probability") is not None:
        return int(stage["win_probability"])
    return DEFAULT_PROB.get(stage.get("key"), 100 if stage.get("group") == "booked" else 20)


class ProbIn(P):
    stage_id: str
    pct: int


@action("stages.set_probability", "internal", ProbIn, roles=ADMINS, desc="Set an opportunity stage's win chance (used by the forecast).")
async def stages_set_probability(ctx, p: ProbIn):
    st = await ctx.data.stages.get(p.stage_id)
    if not st:
        raise not_found("That stage")
    if not 0 <= p.pct <= 100:
        raise AppError("invalid", "Win chance must be between 0% and 100%.", 400)
    await ctx.data.stages.update({"_id": st["_id"]}, {"win_probability": int(p.pct)})
    return {"ok": True}


class SpreadIn(P):
    id: str
    expected_close: Optional[str] = None
    value_paise: Optional[int] = None
    spread: Optional[list] = None   # [{month: 'YYYY-MM', amount_paise}]


@action("projects.set_revenue_spread", "internal", SpreadIn, roles=STAFF,
        desc="Set an opportunity's value, expected close date and how its revenue spreads across months.")
async def projects_set_spread(ctx, p: SpreadIn):
    pr = await perm.project(ctx, p.id, act=True)
    ch = {}
    if p.expected_close is not None:
        try:
            ch["expected_close"] = Date.fromisoformat(p.expected_close[:10]).isoformat() if p.expected_close else None
        except ValueError:
            raise AppError("invalid", "That close date doesn't look right.", 400)
    if p.value_paise is not None:
        if p.value_paise < 0:
            raise AppError("invalid", "Value can't be below zero.", 400)
        ch["value_paise"] = int(p.value_paise)
    if p.spread is not None:
        rows = []
        for s in p.spread[:24]:
            mk = str(s.get("month", ""))[:7]
            if len(mk) != 7 or mk[4] != "-":
                raise AppError("invalid", "Each month looks like 2026-12.", 400)
            amt = int(s.get("amount_paise") or 0)
            if amt < 0:
                raise AppError("invalid", "Amounts can't be below zero.", 400)
            rows.append({"month": mk, "amount_paise": amt})
        ch["revenue_spread"] = rows
    await ctx.data.projects.update({"_id": pr["_id"]}, ch)
    pr = await ctx.data.projects.get(pr["_id"])
    sp = spread_of(pr)
    diff = int(pr.get("value_paise") or 0) - sum(x["amount_paise"] for x in sp)
    return {"ok": True, "spread": sp, "difference_paise": diff,
            "note": None if diff == 0 else f"The months add up to {inr(sum(x['amount_paise'] for x in sp))}, "
                                           f"{inr(abs(diff))} {'less' if diff > 0 else 'more'} than the value."}


def spread_of(pr):
    if pr.get("revenue_spread"):
        return pr["revenue_spread"]
    close = pr.get("expected_close") or (aware(pr["created_at"]) + timedelta(days=30)).astimezone(IST).date().isoformat()
    return [{"month": close[:7], "amount_paise": int(pr.get("value_paise") or 0)}]


async def latest_estimate_value(ctx, pid):
    rows = await ctx.data.estimates.find({"project_id": pid, "status": {"$in": ["final", "draft"]}}, sort=[("version", -1)], limit=1)
    return int(rows[0]["totals"]["price"]) if rows and rows[0].get("totals") else 0


class FcIn(P):
    months: int = 6


@action("forecast.get", "read", FcIn,
        desc="Money expected over the next 6 or 12 months: confirmed (agreed invoices, retainers) and pipeline (weighted estimate), kept apart.")
async def forecast_get(ctx, p: FcIn):
    await limits.require(ctx, "forecast_reports")
    n = 12 if p.months >= 12 else 6
    first = month_of(now())
    months = [month_add(first, i) for i in range(n)]
    confirmed = defaultdict(int)
    detail = defaultdict(list)
    undated = 0
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    covered = set()
    # 1. Agreed invoice schedule items (issued invoices, and drafts on booked projects).
    booked = {x["_id"] for x in await ctx.data.projects.find({"_id": {"$in": vis}, "booked": True}, projection={"_id": 1})}
    for inv in await ctx.data.invoices.find({"project_id": {"$in": vis}, "status": {"$nin": ["void", "paid"]}}):
        if inv["status"] == "draft" and inv["project_id"] not in booked:
            continue
        if inv.get("retainer_period_id"):
            covered.add(inv["retainer_period_id"])
        for s in inv["schedule"]:
            if s["status"] == "paid":
                continue
            left = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0) - s.get("tds_paise", 0)
            if left <= 0:
                continue
            mk = month_of(s["due_date"]) if s.get("due_date") else None
            if mk is None:
                undated += left
                continue
            mk = max(mk, first)   # overdue money is expected this month
            if mk in months:
                confirmed[mk] += left
                detail[mk].append({"kind": "invoice", "label": inv.get("number") or inv["title"], "amount_paise": left})
    # 2. Active retainers: each future period's fee (not already invoiced).
    ongoing = []
    for r in await ctx.data.retainers.find({"status": "active", "project_ids": {"$in": vis}}):
        from app.domain.billing.retainers import add_months
        per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"})
        start = Date.fromisoformat(per["start"]) if per else Date.fromisoformat(r["start_date"])
        step = 3 if r["period"] == "quarterly" else 1
        fee = int(r.get("fee_paise") or 0) if r["kind"] != "payg" else int(r.get("cap_paise") or 0)
        k = 0
        d = start
        while month_of(d.isoformat()) <= months[-1] and k < 40:
            if r.get("end_date") and d.isoformat() >= r["end_date"]:
                break
            mk = month_of((d if r["billing"] == "advance" else add_months(d, step)).isoformat())
            is_current = per and k == 0
            if mk in months and not (is_current and per["_id"] in covered):
                confirmed[mk] += fee
                detail[mk].append({"kind": "retainer", "label": r["name"] + (" (up to)" if r["kind"] == "payg" else ""), "amount_paise": fee})
            d = add_months(d, step, Date.fromisoformat(r["start_date"]).day)
            k += 1
        if not r.get("end_date"):
            ongoing.append(r["name"])
    # 3. Monthly invoices that aren't part of a retainer.
    for rec in await ctx.data.recurring_invoices.find({"active": True, "project_id": {"$in": vis}}):
        amt = sum(int(l.get("qty", 1) * 1000) * int(l.get("price_paise", 0)) // 1000 for l in rec["lines"])
        for mk in months:
            if mk == first and rec.get("last_month") == mk:
                continue
            if rec.get("end_month") and mk > rec["end_month"]:
                continue
            confirmed[mk] += amt
            detail[mk].append({"kind": "monthly", "label": "Monthly invoice", "amount_paise": amt})
    # Pipeline: open opportunities x win chance.
    stages = {s["_id"]: s for s in await ctx.data.stages.find({})}
    pipeline = defaultdict(int)
    pipe_items = []
    for pr in await ctx.data.projects.find({"_id": {"$in": vis}, "archived": False, "booked": {"$ne": True}}):
        st = stages.get(pr["stage_id"])
        if not st or st.get("group") != "opportunity":
            continue
        val = int(pr.get("value_paise") or 0) or await latest_estimate_value(ctx, pr["_id"])
        if not val:
            continue
        prob = prob_of(st)
        sp = spread_of(dict(pr, value_paise=val))
        weighted = 0
        for s in sp:
            mk = max(s["month"], first)
            w = s["amount_paise"] * prob // 100
            if mk in months:
                pipeline[mk] += w
                weighted += w
        pipe_items.append({"project_id": pr["_id"], "project": pr["name"], "stage": st["name"], "probability": prob, "value_paise": val,
                           "weighted_paise": weighted, "expected_close": pr.get("expected_close")})
    goal = int((await ctx.ws()).get("settings", {}).get("revenue_goal_paise") or 0)
    rows = [{"month": mk, "label": Date.fromisoformat(mk + "-01").strftime("%b %Y"), "confirmed_paise": confirmed[mk],
             "pipeline_paise": pipeline[mk], "total_paise": confirmed[mk] + pipeline[mk], "target_paise": goal // 12 if goal else None,
             "confirmed_items": detail[mk]} for mk in months]
    nxt = rows[1] if len(rows) > 1 else rows[0]
    return {"months": rows, "pipeline": sorted(pipe_items, key=lambda x: -x["weighted_paise"]), "undated_confirmed_paise": undated,
            "ongoing_retainers": ongoing, "totals": {"confirmed_paise": sum(r["confirmed_paise"] for r in rows),
                                                     "pipeline_paise": sum(r["pipeline_paise"] for r in rows)},
            "summary": f"Confirmed for {nxt['label']}: {inr(nxt['confirmed_paise'])}. Pipeline adds an estimated {inr(nxt['pipeline_paise'])}."}


# ---------------- profit and utilisation ----------------

class ProfitIn(P):
    group: str = "project"      # project | client | service
    date_from: Optional[str] = None
    date_to: Optional[str] = None


def _in(d, f, t):
    s = aware(d).astimezone(IST).date().isoformat() if hasattr(d, "astimezone") else str(d)[:10]
    return (not f or s >= f[:10]) and (not t or s <= t[:10])


@action("reports.profitability", "read", ProfitIn,
        desc="What each project, client or service really earned: billed, received, hours, effective hourly rate, cost and margin.")
async def reports_profitability(ctx, p: ProfitIn):
    await limits.require(ctx, "forecast_reports")
    if p.group not in ("project", "client", "service"):
        raise AppError("invalid", "Group by project, client or service.", 400)
    vis = await ctx.data.projects.find(perm.visible_filter(ctx))
    pids = [x["_id"] for x in vis]
    pmap = {x["_id"]: x for x in vis}
    billed = defaultdict(int)
    for inv in await ctx.data.invoices.find({"project_id": {"$in": pids}, "status": {"$nin": ["draft", "void"]}}):
        if _in(inv.get("sent_at") or inv["created_at"], p.date_from, p.date_to):
            billed[inv["project_id"]] += inv["totals"]["total"]
    received = defaultdict(int)
    for l in await ctx.data.ledger.find({"project_id": {"$in": pids}}):
        if not _in(l["created_at"], p.date_from, p.date_to):
            continue
        # TDS the client deducted is still the consultant's income (it comes back as tax credit).
        sign = 1 if l["type"] in ("payment", "tds") else -1 if l["type"] in ("refund", "credit_note") else 0
        received[l["project_id"]] += sign * int(l["amount_paise"])
    mins, bill_mins, cost = defaultdict(int), defaultdict(int), defaultdict(int)
    svc_mins = defaultdict(lambda: defaultdict(int))
    for e in await ctx.data.time_entries.find({"project_id": {"$in": pids}}):
        if not _in(e["date"], p.date_from, p.date_to):
            continue
        mins[e["project_id"]] += e["minutes"]
        if e["billing_status"] != "non_billable":
            bill_mins[e["project_id"]] += e["minutes"]
        cost[e["project_id"]] += e["minutes"] * int(e.get("cost_snapshot_paise") or 0) // 60
        svc_mins[e["project_id"]][e.get("service_id") or "-"] += e["minutes"]
    for x in await ctx.data.expenses.find({"project_id": {"$in": pids}}):
        if _in(x["date"], p.date_from, p.date_to):
            cost[x["project_id"]] += int(x["amount_paise"])
    groups = defaultdict(lambda: {"billed_paise": 0, "received_paise": 0, "minutes": 0, "billable_minutes": 0, "cost_paise": 0, "projects": 0})
    names = {}
    contacts = {c["_id"]: c for c in await ctx.data.contacts.find({})}
    services = {s["_id"]: s["name"] for s in await ctx.data.services.find({})}
    for pid in pids:
        if not (billed[pid] or received[pid] or mins[pid] or cost[pid]):
            continue
        if p.group == "service":
            total = sum(svc_mins[pid].values())
            shares = svc_mins[pid].items() if total else [("-", 1)]
            total = total or 1
            for sid, m in shares:
                g = groups[sid]
                names[sid] = services.get(sid, "No service")
                g["billed_paise"] += billed[pid] * m // total
                g["received_paise"] += received[pid] * m // total
                g["minutes"] += mins[pid] * m // total if mins[pid] else 0
                g["billable_minutes"] += bill_mins[pid] * m // total if bill_mins[pid] else 0
                g["cost_paise"] += cost[pid] * m // total
                g["projects"] += 1
            continue
        key = pid if p.group == "project" else ((pmap[pid].get("contact_ids") or ["-"])[0])
        names[key] = pmap[pid]["name"] if p.group == "project" else (contacts.get(key, {}).get("company") or contacts.get(key, {}).get("name") or "No client")
        g = groups[key]
        g["billed_paise"] += billed[pid]
        g["received_paise"] += received[pid]
        g["minutes"] += mins[pid]
        g["billable_minutes"] += bill_mins[pid]
        g["cost_paise"] += cost[pid]
        g["projects"] += 1
    rows = []
    for k, g in groups.items():
        eff = g["received_paise"] * 60 // g["minutes"] if g["minutes"] else None
        rows.append({"key": k, "name": names.get(k, ""), **g, "hours": round(g["minutes"] / 60, 1), "effective_hourly_paise": eff,
                     "margin_paise": g["received_paise"] - g["cost_paise"],
                     "margin_bp": (g["received_paise"] - g["cost_paise"]) * 10000 // g["received_paise"] if g["received_paise"] else None})
    rows.sort(key=lambda r: -(r["effective_hourly_paise"] or 0))
    rated = [r for r in rows if r["effective_hourly_paise"]]
    best, worst = (rated[0], rated[-1]) if rated else (None, None)
    return {"group": p.group, "rows": rows, "best": best, "worst": worst, "standard_hourly_paise": (await rates.resolve(ctx, None))["hourly_paise"],
            "summary": (f"Best effective rate: {inr(best['effective_hourly_paise'])}/hour on {best['name']}. "
                        f"Lowest: {inr(worst['effective_hourly_paise'])}/hour on {worst['name']}.") if best and best is not worst else
                       "Log time on projects to see effective hourly rates."}


class UtilIn(P):
    period: str = "week"   # week | month
    count: int = 8


@action("reports.utilisation", "read", UtilIn, roles=ADMINS | {"manager"},
        desc="Billable hours ÷ available hours, per person, by week or month; non-billable time by reason.")
async def reports_utilisation(ctx, p: UtilIn):
    await limits.require(ctx, "forecast_reports")
    if p.period not in ("week", "month"):
        raise AppError("invalid", "By week or by month.", 400)
    t = now().astimezone(IST).date()
    n = max(1, min(p.count, 26))
    buckets = []
    if p.period == "week":
        s = t - timedelta(days=t.weekday())
        for i in range(n - 1, -1, -1):
            a = s - timedelta(days=7 * i)
            buckets.append((a.isoformat(), (a + timedelta(days=7)).isoformat(), f"{a.day} {a:%b}"))
    else:
        from app.domain.billing.retainers import add_months
        s = t.replace(day=1)
        for i in range(n - 1, -1, -1):
            a = add_months(s, -i, 1)
            buckets.append((a.isoformat(), add_months(a, 1, 1).isoformat(), f"{a:%b %Y}"))
    team = await rates._team(ctx)
    entries = await ctx.data.time_entries.find({"date": {"$gte": buckets[0][0], "$lt": buckets[-1][1]}})
    people = []
    reasons = defaultdict(int)
    for u in team:
        prof = await rates.member_profile(ctx, u["_id"])
        avail_week = int(prof.get("available_minutes_week") or 2400)
        cells = []
        for a, b, label in buckets:
            mine = [e for e in entries if e.get("user_id") == u["_id"] and a <= e["date"] < b]
            billable = sum(e["minutes"] for e in mine if e["billing_status"] != "non_billable")
            nonb = sum(e["minutes"] for e in mine if e["billing_status"] == "non_billable")
            days = (Date.fromisoformat(b) - Date.fromisoformat(a)).days
            avail = avail_week * days // 7
            cells.append({"label": label, "billable_minutes": billable, "non_billable_minutes": nonb, "available_minutes": avail,
                          "pct": round(billable * 100 / avail) if avail else None})
        for e in entries:
            if e.get("user_id") == u["_id"] and e["billing_status"] == "non_billable":
                reasons[e.get("reason") or "untagged"] += e["minutes"]
        if any(c["billable_minutes"] or c["non_billable_minutes"] for c in cells) or u.get("role") in ("owner",):
            people.append({"user_id": u["_id"], "name": u.get("name") or u.get("phone"), "cells": cells,
                           "avg_pct": round(sum(c["pct"] or 0 for c in cells) / len(cells)) if cells else 0})
    return {"period": p.period, "buckets": [b[2] for b in buckets], "people": people,
            "non_billable_by_reason": [{"reason": k, "minutes": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])]}


async def effective_rate_for_words(ctx, words):
    """For the proposal agent: what similar past work really earned per hour."""
    r = await reports_profitability(ctx, ProfitIn(group="project"))
    w = [x for x in (words or "").lower().split() if len(x) > 3]
    rows = [x for x in r["rows"] if x["effective_hourly_paise"] and any(k in x["name"].lower() for k in w)] or \
        [x for x in r["rows"] if x["effective_hourly_paise"]]
    if not rows:
        return None
    avg = sum(x["effective_hourly_paise"] for x in rows) // len(rows)
    return f"Your past projects earned about {inr(avg)}/hour on average (received ÷ hours logged)."


_ = clean
