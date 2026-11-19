"""Reports, the money view (expenses, cashflow, profit per project) and the tax pack.

Reports cover every project whatever its source, with filters on every report:
date range, project type, tag, source and owner.
"""
import csv
import io
import re
from collections import defaultdict
from datetime import timedelta
from typing import Optional

from actions import perm
from actions.money import item_state
from actions.registry import ADMINS, P, action
from core import limits
from core.util import IST, AppError, aware, clean, fmt_date, inr, month_key, not_found, now

LEVELS = {"basic": 0, "standard": 1, "advanced": 2}


async def need_level(ctx, lvl):
    have = await limits.get(ctx, "report_level")
    if LEVELS.get(have, 2) < LEVELS[lvl]:
        raise AppError("locked", "This report isn't available on your account right now.", 403)
    if ctx.hide_money or ctx.role in ("member", "collaborator"):
        raise AppError("forbidden", "Reports and money totals are hidden for your role.", 403)


class Filters(P):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    type: Optional[str] = None
    tag: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[str] = None


def pfilter(ctx, f: Filters, date_field="created_at"):
    q = dict(perm.visible_filter(ctx))
    for k in ("type", "source", "owner_id"):
        if getattr(f, k):
            q[k] = getattr(f, k)
    if f.tag:
        q["tags"] = f.tag
    if f.date_from or f.date_to:
        r = {}
        if f.date_from:
            r["$gte"] = aware(f.date_from)
        if f.date_to:
            r["$lte"] = aware(f.date_to)
        q[date_field] = r
    return q


async def _payments(ctx, pids, a=None, b=None):
    q = {"project_id": {"$in": pids}, "type": {"$in": ["payment", "refund"]}}
    if a or b:
        q["created_at"] = {k: v for k, v in (("$gte", a), ("$lt", b)) if v}
    return await ctx.data.ledger.find(q)


@action("reports.summary", "read", Filters, desc="Money received this month and year, outstanding, overdue, bookings, revenue goal.")
async def summary(ctx, f: Filters):
    await need_level(ctx, "basic")
    t = now().astimezone(IST)
    m0 = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    fy_start = t.replace(month=4, day=1, hour=0, minute=0, second=0, microsecond=0)
    if t.month < 4:
        fy_start = fy_start.replace(year=t.year - 1)
    projects = await ctx.data.projects.find(pfilter(ctx, f), projection={"_id": 1, "booked": 1, "booked_at": 1})
    pids = [p["_id"] for p in projects]
    rows = await _payments(ctx, pids)
    sign = lambda r: r["amount_paise"] if r["type"] == "payment" else -r["amount_paise"]
    month = sum(sign(r) for r in rows if aware(r["created_at"]) >= m0)
    year = sum(sign(r) for r in rows if aware(r["created_at"]) >= fy_start)
    outstanding = overdue = processing = 0
    for inv in await ctx.data.invoices.find({"project_id": {"$in": pids}, "status": {"$in": ["sent", "partially_paid"]}}):
        for s in inv["schedule"]:
            left = s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0)
            st = item_state(s, inv)
            if st != "paid":
                outstanding += left
            if st == "overdue":
                overdue += left
            if st == "processing":
                processing += left
    ws = await ctx.ws()
    goal = ws.get("settings", {}).get("revenue_goal_paise", 0)
    return {"received_month_paise": month, "received_fy_paise": year, "outstanding_paise": outstanding, "overdue_paise": overdue,
            "processing_paise": processing, "bookings": sum(1 for p in projects if p.get("booked")),
            "bookings_month": sum(1 for p in projects if p.get("booked_at") and aware(p["booked_at"]) >= m0),
            "goal_paise": goal, "goal_pct": round(100 * year / goal) if goal else None}


@action("reports.pipeline", "read", Filters, desc="Lead sources, conversion by stage, average value, time to book, lost reasons.")
async def pipeline(ctx, f: Filters):
    await need_level(ctx, "standard")
    rows = await ctx.data.projects.find(pfilter(ctx, f))
    stages = await ctx.data.stages.find({}, sort=[("order", 1)])
    order = {s["_id"]: s["order"] for s in stages}
    by_stage = []
    for s in stages:
        reached = sum(1 for p in rows if order.get(p["stage_id"], -1) >= s["order"] or (p.get("booked") and s["group"] == "opportunity"))
        by_stage.append({"stage": s["name"], "reached": reached, "pct": round(100 * reached / len(rows)) if rows else 0})
    src = defaultdict(lambda: {"leads": 0, "booked": 0, "value_paise": 0, "days": []})
    for p in rows:
        d = src[p.get("source") or "Not set"]
        d["leads"] += 1
        if p.get("booked"):
            d["booked"] += 1
            d["value_paise"] += p.get("value_paise", 0)
            if p.get("booked_at"):
                d["days"].append((aware(p["booked_at"]) - aware(p["created_at"])).days)
    sources = []
    for k, d in src.items():
        sources.append({"source": k, "leads": d["leads"], "share_pct": round(100 * d["leads"] / len(rows)) if rows else 0,
                        "booked": d["booked"], "conversion_pct": round(100 * d["booked"] / d["leads"]) if d["leads"] else 0,
                        "value_paise": d["value_paise"], "avg_days_to_book": round(sum(d["days"]) / len(d["days"]), 1) if d["days"] else None})
    booked = [p for p in rows if p.get("booked")]
    lost = defaultdict(int)
    for p in rows:
        if p.get("archived") and p.get("archived_reason"):
            lost[p["archived_reason"]] += 1
    files_sent = await ctx.data.client_files.count({"project_id": {"$in": [p["_id"] for p in rows]}, "status": {"$ne": "draft"}})
    files_booked = await ctx.data.client_files.count({"project_id": {"$in": [p["_id"] for p in booked]}, "status": {"$ne": "draft"}})
    by_month = defaultdict(int)
    for p in booked:
        if p.get("booked_at"):
            by_month[month_key(p["booked_at"])] += 1
    days = [(aware(p["booked_at"]) - aware(p["created_at"])).days for p in booked if p.get("booked_at")]
    return {"total": len(rows), "by_stage": by_stage, "sources": sorted(sources, key=lambda x: -x["leads"]),
            "avg_value_paise": round(sum(p.get("value_paise", 0) for p in booked) / len(booked)) if booked else 0,
            "avg_days_to_book": round(sum(days) / len(days), 1) if days else None,
            "lost_reasons": [{"reason": k, "count": v} for k, v in sorted(lost.items(), key=lambda x: -x[1])],
            "files_sent": files_sent, "files_booked": files_booked,
            "bookings_by_month": [{"month": k, "count": v} for k, v in sorted(by_month.items())]}


@action("reports.payments", "read", Filters, desc="Monthly sales, by project type and team member, and the forecast from payment schedules.")
async def payments(ctx, f: Filters):
    await need_level(ctx, "advanced")
    projects = {p["_id"]: p for p in await ctx.data.projects.find(pfilter(ctx, Filters(type=f.type, tag=f.tag, source=f.source, owner_id=f.owner_id)))}
    rows = await _payments(ctx, list(projects))
    monthly, by_type, by_owner = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        v = r["amount_paise"] if r["type"] == "payment" else -r["amount_paise"]
        monthly[month_key(r["created_at"])] += v
        p = projects.get(r["project_id"], {})
        by_type[p.get("type") or "Not set"] += v
        by_owner[p.get("owner_id") or "—"] += v
    forecast = defaultdict(int)
    for inv in await ctx.data.invoices.find({"project_id": {"$in": list(projects)}, "status": {"$in": ["sent", "partially_paid"]}}):
        for s in inv["schedule"]:
            if s["status"] != "paid":
                key = month_key(s["due_date"]) if s.get("due_date") else "No date yet"
                forecast[key] += s["amount_paise"] - s.get("paid_paise", 0)
    for r in await ctx.data.recurring_invoices.find({"active": True, "project_id": {"$in": list(projects)}}):
        amt = sum(int(l.get("qty", 1) * l.get("price_paise", 0)) for l in r["lines"])
        t = now().astimezone(IST)
        for i in range(1, 4):
            mm = (t.month - 1 + i) % 12 + 1
            yy = t.year + (t.month - 1 + i) // 12
            forecast[f"{yy}-{mm:02d}"] += amt
    from core.db import get_db
    names = {u["_id"]: u.get("name") or u["phone"] for u in await get_db().users.find({"_id": {"$in": list(by_owner)}}).to_list(None)}
    return {"monthly": [{"month": k, "paise": v} for k, v in sorted(monthly.items())],
            "by_type": [{"type": k, "paise": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
            "by_owner": [{"owner": names.get(k, k), "paise": v} for k, v in sorted(by_owner.items(), key=lambda x: -x[1])],
            "forecast": [{"month": k, "paise": v} for k, v in sorted(forecast.items())],
            "forecast_note": "Assumption: every scheduled payment arrives on its due date, and retainers continue."}


def to_csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[1] for c in cols])
    for r in rows:
        w.writerow([r.get(c[0], "") for c in cols])
    return buf.getvalue()


class ExportIn(Filters):
    what: str = "projects"   # projects | payments | invoices | contacts


@action("reports.export_csv", "read", ExportIn, roles=ADMINS | {"manager"}, agent_ok=False, desc="Download a CSV.")
async def export_csv(ctx, p: ExportIn):
    await need_level(ctx, "advanced")
    from core.events import audit
    await audit(ctx, "export", p.what)
    if p.what == "projects":
        stages = {s["_id"]: s["name"] for s in await ctx.data.stages.find({})}
        rows = [dict(r, stage=stages.get(r["stage_id"], ""), value=r.get("value_paise", 0) / 100, created=fmt_date(r["created_at"]))
                for r in await ctx.data.projects.find(pfilter(ctx, p))]
        return {"filename": "projects.csv", "csv": to_csv(rows, [("name", "Project"), ("stage", "Stage"), ("type", "Type"), ("source", "Source"),
                                                                  ("value", "Value (₹)"), ("booked", "Booked"), ("created", "Created"),
                                                                  ("archived_reason", "Lost reason")])}
    if p.what == "contacts":
        rows = await ctx.data.contacts.find({})
        return {"filename": "contacts.csv", "csv": to_csv(rows, [("name", "Name"), ("phone", "Phone"), ("email", "Email"), ("company", "Company"),
                                                                  ("source", "Source")])}
    if p.what == "payments":
        names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({})}
        rows = [{"date": fmt_date(r["created_at"]), "type": r["type"], "amount": r["amount_paise"] / 100, "project": names.get(r["project_id"], ""),
                 "method": r.get("method", "")} for r in await ctx.data.ledger.find({}, sort=[("created_at", 1)])]
        return {"filename": "payments.csv", "csv": to_csv(rows, [("date", "Date"), ("type", "Type"), ("amount", "Amount (₹)"),
                                                                  ("project", "Project"), ("method", "Method")])}
    raise AppError("invalid", "Choose projects, contacts or payments.", 400)


# ---------------- money view ----------------

class ExpenseIn(P):
    id: Optional[str] = None
    amount_paise: int
    date: str
    category: str = "Other"
    project_id: Optional[str] = None
    note: str = ""
    billable: bool = False            # bill to the client
    markup_pct: float = 0
    receipt_upload_id: Optional[str] = None


@action("expenses.save", "internal", ExpenseIn, roles=ADMINS | {"manager"}, desc="Add or edit an expense (optionally tagged to a project).")
async def expenses_save(ctx, p: ExpenseIn):
    if p.amount_paise <= 0:
        raise AppError("invalid", "The amount must be more than zero.", 400)
    if p.project_id:
        await perm.project(ctx, p.project_id)
    if p.billable and not p.project_id:
        raise AppError("invalid", "To bill an expense to a client, choose the project.", 400)
    if not 0 <= p.markup_pct <= 100:
        raise AppError("invalid", "Markup must be between 0% and 100%.", 400)
    doc = {"amount_paise": p.amount_paise, "date": p.date[:10], "category": p.category[:40], "project_id": p.project_id,
           "note": p.note[:200], "source": "manual", "billable": bool(p.billable), "markup_bp": int(round(p.markup_pct * 100)),
           "receipt_upload_id": p.receipt_upload_id}
    if p.id:
        old = await ctx.data.expenses.get(p.id)
        if not old:
            raise AppError("not_found", "That expense wasn't found.", 404)
        if old.get("invoice_id"):
            raise AppError("locked", "This expense is on an invoice. Remove it from the invoice first.", 409)
        await ctx.data.expenses.update({"_id": p.id}, doc)
        out = await ctx.data.expenses.get(p.id)
    else:
        out = await ctx.data.expenses.insert(dict(doc, invoice_id=None))
    if p.project_id:
        from actions import budgets
        await budgets.check(ctx, p.project_id)
    return clean(out)


@action("expenses.list", "read", Filters, desc="Expenses.")
async def expenses_list(ctx, p: Filters):
    await need_level(ctx, "basic")
    q = {}
    if p.date_from:
        q["date"] = {"$gte": p.date_from[:10]}
    return clean(await ctx.data.expenses.find(q, sort=[("date", -1)], limit=500))


@action("expenses.delete", "destructive", type("ExpId", (P,), {"__annotations__": {"id": str}}), roles=ADMINS, agent_ok=False,
        desc="Delete an expense.")
async def expenses_delete(ctx, p):
    await ctx.data.expenses.soft_delete({"_id": p.id})
    return {"ok": True}


class StatementIn(P):
    rows: list   # parsed CSV/Excel rows from the screen
    default_category: str = "Bank"


def _amount(v):
    if v is None:
        return 0
    s = re.sub(r"[^\d.\-]", "", str(v))
    try:
        return int(round(float(s) * 100)) if s not in ("", "-", ".") else 0
    except ValueError:
        return 0


@action("expenses.import_statement", "internal", StatementIn, roles=ADMINS, agent_ok=False,
        desc="Upload a bank statement (CSV/Excel rows); money going out becomes expenses you can tag.")
async def expenses_import(ctx, p: StatementIn):
    if len(p.rows) > 5000:
        raise AppError("too_many", "Please upload at most 5,000 rows at a time.", 400)
    added = skipped = 0
    for r in p.rows:
        r = {str(k).strip().lower(): v for k, v in r.items()}
        out = _amount(r.get("debit") or r.get("withdrawal") or r.get("withdrawal amt.") or r.get("dr"))
        if not out and _amount(r.get("amount")) < 0:
            out = -_amount(r.get("amount"))
        date = str(r.get("date") or r.get("txn date") or r.get("value date") or "")[:10]
        if out <= 0 or not date:
            skipped += 1
            continue
        key = f"{date}|{out}|{str(r.get('narration') or r.get('description') or '')[:60]}"
        if await ctx.data.expenses.find_one({"import_key": key}):
            skipped += 1
            continue
        await ctx.data.expenses.insert({"amount_paise": out, "date": date, "category": p.default_category, "project_id": None,
                                        "note": str(r.get("narration") or r.get("description") or "")[:200], "source": "statement",
                                        "import_key": key})
        added += 1
    return {"added": added, "skipped": skipped}


@action("money.view", "read", Filters, desc="Cashflow by month (received minus expenses) and profit per project.")
async def money_view(ctx, f: Filters):
    await need_level(ctx, "advanced")
    projects = {p["_id"]: p for p in await ctx.data.projects.find(pfilter(ctx, Filters(type=f.type, tag=f.tag, source=f.source)))}
    led = await _payments(ctx, list(projects))
    exp = await ctx.data.expenses.find({})
    flow = defaultdict(lambda: {"in": 0, "out": 0})
    for r in led:
        flow[month_key(r["created_at"])]["in"] += r["amount_paise"] if r["type"] == "payment" else -r["amount_paise"]
    for e in exp:
        flow[e["date"][:7]]["out"] += e["amount_paise"]
    per = defaultdict(lambda: {"in": 0, "out": 0})
    for r in led:
        per[r["project_id"]]["in"] += r["amount_paise"] if r["type"] == "payment" else -r["amount_paise"]
    for e in exp:
        if e.get("project_id"):
            per[e["project_id"]]["out"] += e["amount_paise"]
    return {"cashflow": [{"month": k, "in_paise": v["in"], "out_paise": v["out"], "net_paise": v["in"] - v["out"]} for k, v in sorted(flow.items())],
            "projects": sorted([{"project_id": k, "project": projects.get(k, {}).get("name", ""), "received_paise": v["in"],
                                 "expenses_paise": v["out"], "profit_paise": v["in"] - v["out"]} for k, v in per.items() if k in projects],
                               key=lambda x: -x["profit_paise"])}


class TaxIn(P):
    what: str            # invoice_register | tds | gst
    fy: Optional[str] = None


@action("tax.pack", "read", TaxIn, roles=ADMINS, agent_ok=False, desc="Downloads for your CA: invoice register, TDS by client, GST by month.")
async def tax_pack(ctx, p: TaxIn):
    await need_level(ctx, "advanced")
    q = {"number": {"$ne": None}}
    if p.fy:
        q["fy"] = p.fy
    invs = await ctx.data.invoices.find(q, sort=[("number", 1)])
    contacts = {c["_id"]: c for c in await ctx.data.contacts.find({})}
    if p.what == "invoice_register":
        rows = [{"number": i["number"], "date": fmt_date(i.get("sent_at") or i["created_at"]), "client": contacts.get(i.get("contact_id"), {}).get("name", ""),
                 "taxable": (i["totals"]["total"] - i["totals"]["cgst"] - i["totals"]["sgst"] - i["totals"]["igst"]) / 100,
                 "cgst": i["totals"]["cgst"] / 100, "sgst": i["totals"]["sgst"] / 100, "igst": i["totals"]["igst"] / 100,
                 "total": i["totals"]["total"] / 100, "status": i["status"]} for i in invs]
        return {"filename": "invoice-register.csv", "csv": to_csv(rows, [("number", "Invoice no."), ("date", "Date"), ("client", "Client"),
                                                                          ("taxable", "Taxable (₹)"), ("cgst", "CGST"), ("sgst", "SGST"),
                                                                          ("igst", "IGST"), ("total", "Total (₹)"), ("status", "Status")])}
    if p.what == "tds":
        by = defaultdict(int)
        for r in await ctx.data.ledger.find({"type": "tds"}):
            inv = next((i for i in invs if i["_id"] == r["invoice_id"]), None)
            by[contacts.get((inv or {}).get("contact_id"), {}).get("name", "Unknown")] += r["amount_paise"]
        rows = [{"client": k, "tds": v / 100} for k, v in sorted(by.items())]
        return {"filename": "tds-by-client.csv", "csv": to_csv(rows, [("client", "Client"), ("tds", "TDS deducted (₹)")])}
    if p.what == "gst":
        ws = await ctx.ws()
        if not ws["invoice"].get("gst_enabled"):
            raise AppError("gst_off", "GST is switched off in Settings, so there is no GST report.", 400)
        by = defaultdict(lambda: [0, 0, 0])
        for i in invs:
            k = month_key(i.get("sent_at") or i["created_at"])
            by[k][0] += i["totals"]["cgst"]
            by[k][1] += i["totals"]["sgst"]
            by[k][2] += i["totals"]["igst"]
        rows = [{"month": k, "cgst": v[0] / 100, "sgst": v[1] / 100, "igst": v[2] / 100} for k, v in sorted(by.items())]
        return {"filename": "gst-by-month.csv", "csv": to_csv(rows, [("month", "Month"), ("cgst", "CGST (₹)"), ("sgst", "SGST (₹)"), ("igst", "IGST (₹)")])}
    raise AppError("invalid", "Choose invoice register, TDS or GST.", 400)


@action("home.get", "read", agent_ok=False, desc="Everything the Home screen shows.")
async def home(ctx, p):
    from actions.agent_actions import briefs_today
    t0 = now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    vis = perm.visible_filter(ctx)
    first = await ctx.data.stages.find_one({}, sort=[("order", 1)])
    pids = [x["_id"] for x in await ctx.data.projects.find(dict(vis, archived=False), projection={"_id": 1})]
    unanswered = await ctx.data.projects.count(dict(vis, archived=False, stage_id=(first or {}).get("_id")))
    unread = sum(t.get("unread", 0) for t in await ctx.data.threads.find({"project_id": {"$in": pids}, "unread": {"$gt": 0}}))
    tq = {"done": False, "due_at": {"$lt": t0 + timedelta(days=1)}, "audience": {"$ne": "client"}}
    if ctx.role in ("member", "collaborator"):
        tq["assignee_id"] = ctx.user_id
    tasks_due = await ctx.data.tasks.count(tq)
    groups = {"paid": 0, "processing": 0, "upcoming": 0, "overdue": 0}
    m0 = t0.replace(day=1)
    for inv in await ctx.data.invoices.find({"project_id": {"$in": pids}, "status": {"$in": ["sent", "partially_paid", "paid"]}}):
        for s in inv["schedule"]:
            st = item_state(s, inv)
            if st == "paid":
                if s.get("paid_at") and aware(s["paid_at"]) >= m0:
                    groups["paid"] += s.get("paid_paise", 0)
            else:
                groups[st] += s["amount_paise"] + s.get("late_fee_paise", 0) - s.get("paid_paise", 0)
    sessions = [dict(clean(s), project=None) for s in await ctx.data.sessions.find(
        {"project_id": {"$in": pids}, "status": "booked", "start": {"$gte": t0, "$lt": t0 + timedelta(days=1)}}, sort=[("start", 1)])]
    approvals = await ctx.data.approvals.count({"status": "pending"})
    activity = clean(await ctx.data.activity.find({"project_id": {"$in": pids}}, sort=[("at", -1)], limit=12))
    stale = await ctx.data.payment_claims.count({"status": "pending", "created_at": {"$lt": now() - timedelta(days=2)}})
    ws = await ctx.ws()
    suggested = await ctx.data.suggested_leads.count({"status": "new"})
    out = {"greeting_name": (getattr(ctx, "user", {}) or {}).get("name", ""), "approvals": approvals,
           "numbers": {"new_leads": unanswered, "unread": unread, "tasks_due": tasks_due,
                       "received_month_paise": None if ctx.hide_money else groups["paid"]},
           "money": None if ctx.hide_money else groups, "sessions": sessions, "activity": activity, "stale_claims": stale,
           "brief": await briefs_today(ctx, None), "onboarded": ws.get("onboarded", False), "suggested_leads": suggested,
           "budget": await limits.ai_budget(ctx.ws_id), "goal": None}
    from actions.timebill import unbilled_summary
    ub = await unbilled_summary(ctx, pids)
    out["unbilled"] = None if ctx.hide_money else {"amount_paise": sum(v["amount_paise"] for v in ub.values()),
                                                   "minutes": sum(v["minutes"] for v in ub.values()),
                                                   "oldest": min((v["oldest"] for v in ub.values()), default=None), "projects": len(ub)}
    out["waiting_on_client"] = await ctx.data.tasks.count({"project_id": {"$in": pids}, "audience": "client", "done": False})
    out["budgets_at_risk"] = await ctx.data.projects.count(dict(vis, archived=False, **{"budget.pct": {"$gte": 80}}))
    if not ctx.hide_money and ws.get("settings", {}).get("revenue_goal_paise") and ctx.role in ("owner", "admin", "manager"):
        s = await summary(ctx, Filters())
        out["goal"] = {"goal_paise": s["goal_paise"], "pct": s["goal_pct"], "received_paise": s["received_fy_paise"]}
    return out


_ = (not_found, inr)
