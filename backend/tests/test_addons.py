"""Add-on playbook (Bonsai study): every rule in sections 4.1–4.11 that the playbook asks to prove."""
import asyncio
import base64
import hashlib
import io
import json
import zipfile
from datetime import date, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from conftest import act, client, login, outbox, ready_practice, run_jobs
from core.db import get_db
from core.util import IST, advance_clock, now

HOUR = 600000   # ₹6,000 an hour, in paise


def today():
    return now().astimezone(IST).date()


async def practice(phone="+919811120001"):
    c = await login(phone)
    ws = await ready_practice(c)
    return c, ws


async def project(c, name="Acme strategy", email="ravi@acme.in", phone="9820011122"):
    return await act(c, "projects.create", {"name": name, "contact": {"name": "Ravi Shah", "email": email, "phone": phone, "company": "Acme"}})


async def hourly(c, paise=HOUR, name="Consulting hour"):
    return await act(c, "services.save", {"name": name, "unit": "hour", "rate_paise": paise})


async def member_with_hidden_money(c, phone="9811120099"):
    await act(c, "workspace.update", {"settings": {"hide_money_roles": ["member"]}})
    await act(c, "team.add", {"phone": phone, "name": "Kabir", "role": "member"})
    return await login("+91" + phone, invited=False)


def next_month_first():
    t = today()
    return (t.replace(day=1) + timedelta(days=32)).replace(day=1)


# ======================= A1 rates =======================

async def test_rate_change_next_month_never_alters_this_months_entries():
    c, ws = await practice()
    pr = await project(c)
    s = await hourly(c)
    e1 = await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "service_id": s["id"]})
    assert e1["rate_snapshot_paise"] == HOUR
    card = (await act(c, "rate_cards.list"))[0]
    line = next(l for l in card["lines"] if l["service_id"] == s["id"])
    nm = next_month_first().isoformat()
    await act(c, "rate_changes.schedule", {"line_id": line["id"], "rate_paise": 700000, "effective_from": nm})
    await act(c, "rate_changes.schedule", {"line_id": line["id"], "rate_paise": 1, "effective_from": (today() - timedelta(days=1)).isoformat()}, 400)
    e2 = await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "service_id": s["id"]})
    e3 = await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "service_id": s["id"], "date": nm})
    rows = {r["id"]: r for r in await act(c, "time.list", {"project_id": pr["id"]})}
    assert rows[e1["id"]]["rate_snapshot_paise"] == HOUR and rows[e2["id"]]["rate_snapshot_paise"] == HOUR
    assert rows[e3["id"]]["rate_snapshot_paise"] == 700000
    # Upcoming change shows on the card.
    card = (await act(c, "rate_cards.list"))[0]
    assert next(l for l in card["lines"] if l["id"] == line["id"])["upcoming"][0]["effective_from"] == nm


async def test_project_card_beats_client_card_beats_default():
    c, ws = await practice()
    pr = await project(c)
    s = await hourly(c)
    old = await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "service_id": s["id"]})
    contact_id = pr["contact_ids"][0]
    cc = await act(c, "rate_cards.save", {"name": "Acme negotiated", "lines": [{"target": "service", "service_id": s["id"], "unit": "hour", "rate_paise": 500000}]})
    await act(c, "rate_cards.assign", {"rate_card_id": cc["id"], "contact_id": contact_id})
    r = await act(c, "rates.resolve", {"project_id": pr["id"], "service_id": s["id"]})
    assert r["rate_paise"] == 500000 and r["source"] == "client rate card"
    pc = await act(c, "rate_cards.save", {"name": "Acme pilot", "lines": [{"target": "service", "service_id": s["id"], "unit": "hour", "rate_paise": 450000}]})
    await act(c, "rate_cards.assign", {"rate_card_id": pc["id"], "project_id": pr["id"]})
    r = await act(c, "rates.resolve", {"project_id": pr["id"], "service_id": s["id"]})
    assert r["rate_paise"] == 450000 and r["source"] == "project rate card"
    # Without "apply to unbilled", old time keeps its rate; with it, unbilled time is re-priced.
    assert (await act(c, "time.list", {"project_id": pr["id"]}))[0]["rate_snapshot_paise"] == HOUR
    res = await act(c, "rate_cards.assign", {"rate_card_id": pc["id"], "project_id": pr["id"], "apply_to_unbilled": True})
    assert res["repriced_entries"] == 1
    assert next(x for x in await act(c, "time.list", {"project_id": pr["id"]}) if x["id"] == old["id"])["rate_snapshot_paise"] == 450000
    await act(c, "rate_cards.assign", {"rate_card_id": None, "project_id": pr["id"]})
    assert (await act(c, "rates.resolve", {"project_id": pr["id"], "service_id": s["id"]}))["rate_paise"] == 500000
    # Deleting a service that's in use archives it.
    assert (await act(c, "services.delete", {"id": s["id"]}))["archived"] is True


async def test_member_with_hidden_money_cannot_read_rates_through_api_or_chat():
    c, ws = await practice()
    await hourly(c)
    m = await member_with_hidden_money(c)
    r = await act(m, "rates.resolve", {})
    assert r["rate_paise"] is None and r["hourly_paise"] is None
    assert all(s["rate_paise"] is None for s in await act(m, "services.list"))
    assert all(l["rate_paise"] is None for card in await act(m, "rate_cards.list") for l in card["lines"])
    ans = (await act(m, "chat.send", {"message": "What is my hourly rate?"}))["answer"]
    assert "₹" not in ans and "hidden" in ans.lower()
    # Sorting by a money field is refused, not answered.
    await act(m, "projects.search", {"sort": "-value_paise"}, 403)


async def test_cost_and_margin_never_reach_a_member_by_api_chat_or_filter():
    c, ws = await practice()
    me = (await (await c.get("/api/auth/me")).aread())
    owner_id = json.loads(me)["user"]["id"]
    await act(c, "team.set_rates", {"user_id": owner_id, "cost_rate_paise": 200000, "billing_role": "Partner"})
    await act(c, "team.add", {"phone": "9811120098", "name": "Neha", "role": "member"})
    m = await login("+919811120098", invited=False)
    pr = await project(c)
    await act(c, "projects.update", {"id": pr["id"], "team_ids": [json.loads((await (await m.get("/api/auth/me")).aread()))["user"]["id"]]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 60})
    assert "cost_snapshot_paise" in (await act(c, "time.list", {"project_id": pr["id"]}))[0]
    rows = await act(m, "time.list", {"project_id": pr["id"]})
    assert all(not any("cost" in k or "margin" in k for k in r) for r in rows)
    est = await act(c, "estimates.create", {"project_id": pr["id"], "phases": [{"name": "Work", "lines": [
        {"label": "Analysis", "qty": 5, "unit": "day", "rate_paise": 4000000, "user_id": owner_id}]}]})
    assert est["totals"]["margin_paise"] > 0 and est["totals"]["cost_paise"] > 0
    seen = await act(m, "estimates.get", {"id": est["id"]})
    flat = json.dumps(seen)
    assert "margin" not in flat and "cost" not in flat and seen["totals"]["price"] == est["totals"]["price"]
    await act(m, "reports.profitability", {"sort": "margin"}, 403)
    ok = await act(c, "reports.profitability", {"sort": "margin"})
    assert "rows" in ok


# ======================= A2 time to invoice =======================

async def pay_by_upi(inv):
    pub = client()
    item = inv["schedule"][0]["id"]
    r = await pub.post(f"/api/public/i/{inv['token']}/claim", json={"item_id": item, "method": "upi", "reference": "UTR123"})
    assert r.status_code == 200, r.text
    return item


async def test_log_time_invoice_it_client_pays_by_upi_then_cancel_returns_time():
    c, ws = await practice()
    pr = await project(c)
    s = await hourly(c)
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 90, "service_id": s["id"], "note": "Pricing analysis"})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 30, "billable": False, "reason": "admin"})
    inv = await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"], "group_by": "service", "timesheet": "full"})
    assert inv["totals"]["total"] == 90 * HOUR // 60
    rows = await act(c, "time.list", {"project_id": pr["id"], "status": "unbilled"})
    assert len(rows) == 1 and rows[0]["on_draft"] is True   # time on a draft invoice is still unbilled
    inv = await act(c, "invoices.send", {"id": inv["id"]})
    billed = await act(c, "time.list", {"project_id": pr["id"], "status": "billed"})
    assert len(billed) == 1 and billed[0]["locked"]
    r = await c.post("/api/a/time.update", json={"id": billed[0]["id"], "minutes": 10})
    assert r.status_code == 409 and "sent invoice" in r.json()["error"]["message"]
    # The client sees the timesheet and pays by UPI; the consultant confirms.
    pub = client()
    page = (await pub.get(f"/api/public/i/{inv['token']}")).json()
    assert page["timesheet"]["rows"][0]["hours"] == 1.5 and "Pricing analysis" in page["timesheet"]["rows"][0]["note"]
    item = await pay_by_upi(inv)
    await act(c, "payments.confirm", {"invoice_id": inv["id"], "item_id": item, "method": "upi"})
    assert (await act(c, "time.list", {"project_id": pr["id"], "status": "billed"}))[0]["billing_status"] == "billed"
    # A second invoice, cancelled: its time comes back and can be invoiced again, once.
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "service_id": s["id"]})
    inv2 = await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"]})
    await act(c, "invoices.send", {"id": inv2["id"]})
    out = await act(c, "invoices.void", {"id": inv2["id"]})
    assert out["time_released"] == 1
    assert len(await act(c, "time.list", {"project_id": pr["id"], "status": "unbilled"})) == 1
    await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"]})
    await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"]}, 400)


async def test_rounding_moves_line_and_total_together_and_grouping_never_changes_total():
    c, ws = await practice()
    pr = await project(c)
    await hourly(c)
    t1 = await act(c, "tasks.create", {"title": "Interviews", "project_id": pr["id"]})
    t2 = await act(c, "tasks.create", {"title": "Report", "project_id": pr["id"]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 7, "task_id": t1["id"]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 7, "task_id": t2["id"]})
    inv = await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"], "rounding": 15, "group_by": "task"})
    assert [l["minutes"] for l in inv["lines"]] == [15, 15]
    assert inv["totals"]["total"] == 30 * HOUR // 60
    await act(c, "invoices.void", {"id": inv["id"]})
    # An awkward rate: totals stay identical whatever the grouping.
    pr2 = await project(c, "Odd rate", "o@x.in", "9820011133")
    a1 = await act(c, "tasks.create", {"title": "Interviews", "project_id": pr2["id"]})
    a2 = await act(c, "tasks.create", {"title": "Report", "project_id": pr2["id"]})
    for i, (m, d) in enumerate(((7, 0), (11, 1), (13, 2))):
        await act(c, "time.log", {"project_id": pr2["id"], "minutes": m, "date": (today() - timedelta(days=d)).isoformat(),
                                  "task_id": [a1, a2][i]["id"] if i < 2 else None, "note": f"n{i}"})
    await get_db().time_entries.update_many({"project_id": pr2["id"]}, {"$set": {"rate_snapshot_paise": 500000}})
    totals = []
    for g in ("task", "date", "none", "role"):
        inv = await act(c, "invoices.add_unbilled_time", {"project_id": pr2["id"], "group_by": g})
        totals.append(inv["totals"]["total"])
        await act(c, "invoices.void", {"id": inv["id"]})
    assert totals == [31 * 500000 // 60] * 4


async def test_billable_expense_with_markup_goes_on_the_invoice():
    c, ws = await practice()
    pr = await project(c)
    await act(c, "expenses.save", {"amount_paise": 1000000, "date": today().isoformat(), "category": "Travel", "project_id": pr["id"],
                                   "note": "Surat visit", "billable": True, "markup_pct": 10})
    inv = await act(c, "invoices.add_expenses", {"project_id": pr["id"]})
    assert inv["totals"]["total"] == 1100000
    exp = (await act(c, "expenses.list"))[0]
    await act(c, "expenses.save", {"id": exp["id"], "amount_paise": 5, "date": today().isoformat(), "project_id": pr["id"]}, 409)


async def test_period_lock_and_members_only_touch_their_own_time():
    c, ws = await practice()
    pr = await project(c)
    e = await act(c, "time.log", {"project_id": pr["id"], "minutes": 30, "date": (today() - timedelta(days=10)).isoformat()})
    await act(c, "time.lock_period", {"before": (today() - timedelta(days=5)).isoformat()})
    r = await c.post("/api/a/time.update", json={"id": e["id"], "minutes": 45})
    assert r.status_code == 409 and "locked" in r.json()["error"]["message"]
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 30, "date": (today() - timedelta(days=8)).isoformat()}, 409)
    # Weekly grid: type hours straight in.
    await act(c, "time.set_cell", {"project_id": pr["id"], "date": today().isoformat(), "minutes": 120})
    await act(c, "time.set_cell", {"project_id": pr["id"], "date": today().isoformat(), "minutes": 90})
    wk = await act(c, "time.week", {})
    row = next(r for r in wk["rows"] if r["project_id"] == pr["id"])
    assert row["cells"][today().isoformat()] == 90


async def test_bulk_download_remind_and_export_invoices():
    from jobs import j_exports
    c, ws = await practice()
    pr = await project(c)
    for amt in (5000000, 7500000):
        inv = await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": "Advisory", "qty": 1, "price_paise": amt}]})
        await act(c, "invoices.send", {"id": inv["id"]})
    out = await act(c, "invoices.bulk_download", {"status": "sent"})
    assert out["count"] == 2
    assert await j_exports() == 1
    ex = (await act(c, "exports.list"))[0]
    r = await c.get(ex["link"])
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 2 and all(n.endswith(".pdf") for n in names)
    before = len(await outbox("email"))
    ids = [i["id"] for i in await act(c, "invoices.list")]
    rem = await act(c, "invoices.bulk_remind", {"ids": ids})
    assert rem["sent"] == 2 and len(await outbox("email")) > before
    csv = await act(c, "invoices.export", {})
    assert csv["count"] == 2 and csv["csv"].count("\n") == 3


# ======================= A3 budgets =======================

async def budget_events(pct):
    return await get_db().events.count_documents({"type": "budget.threshold_reached", "payload.pct": pct})


async def test_budget_alert_fires_once_at_80_and_not_again():
    c, ws = await practice()
    pr = await project(c)
    await act(c, "budgets.create", {"project_id": pr["id"], "type": "time", "amount_hours": 10})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 474})
    assert await budget_events(80) == 0
    assert (await act(c, "projects.get", {"id": pr["id"]}))["budget"]["pct"] == 79.0
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 6})
    assert await budget_events(80) == 1
    advance_clock(days=1)
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 30})
    assert await budget_events(80) == 1
    risk = await act(c, "budgets.at_risk")
    assert risk["items"][0]["project_id"] == pr["id"]


async def test_monthly_budget_resets_on_the_first_and_keeps_history():
    c, ws = await practice()
    pr = await project(c)
    await hourly(c)
    await act(c, "budgets.create", {"project_id": pr["id"], "type": "fee", "amount_paise": 10000000, "reset": "monthly"})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 120})
    b = await act(c, "budgets.get", {"project_id": pr["id"]})
    assert b["used"] == 2 * HOUR and b["pct"] == 12.0
    first = next_month_first()
    advance_clock(days=(first - today()).days + 1)
    b = await act(c, "budgets.get", {"project_id": pr["id"]})
    assert b["used"] == 0 and b["cycle_start"] == first.isoformat()
    assert b["history"][0]["used"] == 2 * HOUR


async def test_budget_forecast_matches_the_formula():
    c, ws = await practice()
    pr = await project(c)
    await hourly(c)
    start = (today() - timedelta(days=7)).isoformat()
    await act(c, "budgets.create", {"project_id": pr["id"], "type": "time", "amount_hours": 20, "start_date": start})
    d = lambda n: (now() + timedelta(days=n)).isoformat()   # noqa: E731
    t1 = await act(c, "tasks.create", {"title": "T1", "project_id": pr["id"], "due_at": d(3), "estimate_hours": 6})
    t2 = await act(c, "tasks.create", {"title": "T2 overdue", "project_id": pr["id"], "due_at": d(-1), "estimate_hours": 4})
    t3 = await act(c, "tasks.create", {"title": "T3 done", "project_id": pr["id"], "due_at": d(2), "estimate_hours": 5})
    t4 = await act(c, "tasks.create", {"title": "T4 over estimate", "project_id": pr["id"], "due_at": d(2), "estimate_hours": 3})
    await act(c, "tasks.create", {"title": "T5 no estimate", "project_id": pr["id"], "due_at": d(2)})
    await act(c, "tasks.complete", {"id": t3["id"]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 120, "task_id": t1["id"]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 240, "task_id": t4["id"]})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 60})
    f = await act(c, "budgets.forecast", {"project_id": pr["id"]})
    # used 7h; remaining T1 4h + T2 4h (placed on today) -> 15h
    assert f["used"] == 420 and f["forecast_total"] == 900
    assert {t["title"]: t["remaining_minutes"] for t in f["tasks"]} == {"T1": 240, "T2 overdue": 240}
    assert next(t for t in f["tasks"] if t["title"] == "T2 overdue")["date"] == today().isoformat()
    _ = t2


async def test_budget_alert_drafts_a_scope_check_for_approval():
    c, ws = await practice()
    pr = await project(c)
    await act(c, "budgets.create", {"project_id": pr["id"], "type": "time", "amount_hours": 1})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 50})
    await run_jobs()
    ap = await act(c, "approvals.list", {})
    assert any("Scope check" in (a["preview"].get("subject") or "") for a in ap)


# ======================= A4 retainers =======================

async def retainer(c, pid, **kw):
    body = {"project_id": pid, "name": "Advisory retainer", "kind": "hours", "fee_paise": 15000000, "included_hours": 20, "billing": "advance",
            "rollover": {"mode": "none"}, "overage": {"mode": "bill"}, "overage_rate_paise": HOUR}
    body.update(kw)
    return await act(c, "retainers.create", body)


async def close_due(ws_id):
    from actions.retainers import run_all
    return await run_all(ws_id)


async def periods(rid):
    return await get_db().retainer_periods.find({"retainer_id": rid}).sort("index", 1).to_list(None)


async def test_retainer_rollover_up_to_5_for_one_period_then_lapses():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"], rollover={"mode": "capped", "cap_hours": 5, "valid_periods": 1})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 14 * 60})
    advance_clock(days=32)
    await close_due(ws["id"])
    p = await periods(r["id"])
    assert p[0]["carried_out_minutes"] == 300 and p[0]["lapsed_minutes"] == 60
    g = await act(c, "retainers.get", {"id": r["id"]})
    assert g["current"]["available"] == 25 * 60
    advance_clock(days=31)
    await close_due(ws["id"])
    p = await periods(r["id"])
    # The 5 carried hours lapse unused; this period's own unused hours carry (up to 5) again.
    assert p[1]["lapsed_minutes"] == 5 * 60 + 15 * 60
    assert p[2]["carried_in"] == [{"minutes": 300, "expires_after": 3, "from_index": 2}]


async def test_retainer_overage_billed_on_next_invoice_as_its_own_line():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"])
    for _ in range(2):
        await act(c, "time.log", {"project_id": pr["id"], "minutes": 13 * 60})
    advance_clock(days=32)
    await close_due(ws["id"])
    invs = await get_db().invoices.find({"retainer_id": r["id"]}).sort("created_at", 1).to_list(None)
    assert len(invs) == 2
    over = [l for l in invs[1]["lines"] if l.get("kind") == "overage"]
    assert len(over) == 1 and over[0]["minutes"] == 360
    assert invs[1]["totals"]["total"] == 15000000 + 6 * HOUR
    # It waits for the consultant's OK.
    assert any(a["action"] == "invoices.send" for a in await act(c, "approvals.list", {}))


async def test_retainer_borrow_rule_next_period_starts_with_14():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"], overage={"mode": "borrow", "borrow_cap_hours": 10})
    for _ in range(2):
        await act(c, "time.log", {"project_id": pr["id"], "minutes": 13 * 60})
    advance_clock(days=32)
    await close_due(ws["id"])
    g = await act(c, "retainers.get", {"id": r["id"]})
    assert g["current"]["available"] == 14 * 60 and g["current"]["borrowed"] == 360


async def test_retainer_period_closes_exactly_once_with_two_workers():
    from actions.retainers import close_period
    from core.context import system_ctx
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"])
    advance_clock(days=32)
    ctx = system_ctx(ws["id"])
    rr = await ctx.data.retainers.get(r["id"])
    per = await ctx.data.retainer_periods.find_one({"retainer_id": r["id"], "status": "open"})
    a, b = await asyncio.gather(close_period(ctx, rr, per), close_period(ctx, rr, per))
    assert (a is None) != (b is None)
    p = await periods(r["id"])
    assert [x["status"] for x in p] == ["closed", "open"]
    assert await get_db().invoices.count_documents({"retainer_id": r["id"]}) == 2


async def test_time_dated_in_a_closed_period_lands_in_adjustments():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"])
    p0 = (await periods(r["id"]))[0]
    advance_clock(days=32)
    await close_due(ws["id"])
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 60, "date": p0["start"]})
    g = await act(c, "retainers.get", {"id": r["id"]})
    assert g["current"]["adjustments"] == 60 and g["current"]["used"] == 60
    assert (await periods(r["id"]))[0]["used"] == 0   # closed periods never change


async def test_pause_mid_period_completes_it_opens_nothing_and_raises_no_invoice():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"])
    assert await get_db().invoices.count_documents({"retainer_id": r["id"]}) == 1   # advance invoice for period 1
    await act(c, "retainers.pause", {"id": r["id"]})
    advance_clock(days=32)
    await close_due(ws["id"])
    assert [x["status"] for x in await periods(r["id"])] == ["closed"]
    assert await get_db().invoices.count_documents({"retainer_id": r["id"]}) == 1


async def test_retainer_ask_first_overage_and_client_statement():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"], overage={"mode": "ask"})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 22 * 60})
    advance_clock(days=32)
    await close_due(ws["id"])
    ap = next(a for a in await act(c, "approvals.list", {}) if a["action"] == "retainers.bill_overage")
    await act(c, "approvals.skip", {"id": ap["id"]})
    assert (await periods(r["id"]))[0]["absorbed_minutes"] == 120
    # The client's statement: numbers, and no entries unless the consultant allows it.
    pub = client()
    contact = (await act(c, "projects.get", {"id": pr["id"]}))["contacts"][0]
    await pub.post("/api/public/" + ws["slug"] + "/portal/code", json={"phone": contact["phone"]})
    r2 = await pub.post("/api/public/" + ws["slug"] + "/portal/login", json={"phone": contact["phone"], "code": "000000"})
    assert r2.status_code == 200, r2.text
    proj = (await pub.get(f"/api/public/{ws['slug']}/portal/project/{pr['id']}")).json()
    st = proj["retainer"]
    assert st["available"] == 20 * 60 and "entries" not in st and st["last_period"]["used"] == 22 * 60


# ======================= A5 estimates =======================

async def test_quote_never_shows_cost_and_accepting_twice_converts_once():
    from public import quote_html
    from core.context import system_ctx
    c, ws = await practice()
    me = json.loads(await (await c.get("/api/auth/me")).aread())["user"]["id"]
    await act(c, "team.set_rates", {"user_id": me, "cost_rate_paise": 200000})
    pr = await project(c)
    est = await act(c, "estimates.create", {"project_id": pr["id"], "name": "Pricing study", "phases": [
        {"name": "Analysis", "lines": [{"label": "Analysis days", "qty": 5, "unit": "day", "rate_paise": 4000000, "user_id": me}]},
        {"name": "Travel", "lines": [{"kind": "expense", "label": "Surat visit", "qty": 1, "cost_paise": 1000000, "markup_bp": 1000}]}]})
    assert est["totals"]["price"] == 5 * 4000000 + 1100000
    assert est["totals"]["cost_paise"] == 5 * 8 * 200000 + 1000000
    await act(c, "estimates.finalise", {"id": est["id"]})
    for detail in ("total", "phase", "line"):
        f = await act(c, "estimates.to_quote", {"id": est["id"], "detail": detail})
        await act(c, "files.send", {"id": f["id"], "channel": "email"})
        page = (await client().get(f"/api/public/f/{f['token']}")).text.lower()
        import re as _re
        hits = [page[max(0, m.start() - 60):m.end() + 30] for m in _re.finditer("cost|margin", page)]
        assert not hits, hits
        html = (await quote_html(system_ctx(ws["id"]), await get_db().client_files.find_one({"_id": f["id"]}))).lower()
        assert "cost" not in html and "margin" not in html
    pub = client()
    a, b = await asyncio.gather(pub.post(f"/api/public/f/{f['token']}/accept"), pub.post(f"/api/public/f/{f['token']}/accept"))
    assert a.status_code == 200 and b.status_code == 200
    assert await get_db().budgets.count_documents({"project_id": pr["id"], "active": True}) == 1
    assert await get_db().tasks.count_documents({"project_id": pr["id"], "occurrence_key": {"$regex": "^est:"}}) == 1
    assert await get_db().invoices.count_documents({"estimate_id": est["id"]}) == 1


async def test_final_estimate_ignores_later_rate_changes_and_expired_quote_is_refused():
    c, ws = await practice()
    pr = await project(c)
    s = await hourly(c)
    est = await act(c, "estimates.create", {"project_id": pr["id"], "phases": [{"name": "Work", "lines": [{"service_id": s["id"], "qty": 10, "unit": "hour"}]}]})
    assert est["totals"]["price"] == 10 * HOUR
    await act(c, "estimates.finalise", {"id": est["id"]})
    await act(c, "services.save", {"id": s["id"], "name": "Consulting hour", "unit": "hour", "rate_paise": 900000})
    card = (await act(c, "rate_cards.list"))[0]
    line = next(l for l in card["lines"] if l["service_id"] == s["id"])
    await act(c, "rate_changes.schedule", {"line_id": line["id"], "rate_paise": 900000, "effective_from": today().isoformat()})
    assert (await act(c, "estimates.get", {"id": est["id"]}))["totals"]["price"] == 10 * HOUR
    await act(c, "estimates.update", {"id": est["id"], "name": "x"}, 409)
    f = await act(c, "estimates.to_quote", {"id": est["id"], "valid_days": 1})
    await act(c, "files.send", {"id": f["id"], "channel": "email"})
    advance_clock(days=3)
    r = await client().post(f"/api/public/f/{f['token']}/accept")
    assert r.status_code == 409 and "expired" in r.json()["error"]["message"]


async def test_call_notes_to_agent_estimate_to_quote_to_accepted_project_with_budget_and_tasks():
    c, ws = await practice()
    pr = await project(c)
    await act(c, "services.save", {"name": "Consulting day", "unit": "day", "rate_paise": 4000000})
    await act(c, "notes.add", {"project_id": pr["id"], "text": "Call notes: they want a 6-week pricing study, two days a week."})
    run = await act(c, "agents.run", {"agent": "proposal", "project_id": pr["id"], "instruction": "Estimate this and send a quote."})
    assert "Assumptions" in run["summary"] and "12 days" in run["summary"]
    ap = next(a for a in await act(c, "approvals.list", {}) if a["action"] == "files.send")
    await act(c, "approvals.approve", {"id": ap["id"]})
    f = await get_db().client_files.find_one({"project_id": pr["id"], "kind": "quote"})
    assert f["status"] in ("sent", "viewed")
    r = await client().post(f"/api/public/f/{f['token']}/accept")
    assert r.status_code == 200 and r.json().get("invoice_link")
    p = await act(c, "projects.get", {"id": pr["id"]})
    assert p["budget"]["amount"] == 12 * 4000000
    assert await get_db().tasks.count_documents({"project_id": pr["id"], "estimate_minutes": {"$gt": 0}}) == 3


# ======================= A6 insight =======================

async def test_forecast_keeps_confirmed_and_pipeline_apart():
    c, ws = await practice()
    pr = await project(c)
    stages = {s["key"]: s for s in await act(c, "stages.list")}
    await act(c, "stages.set_probability", {"stage_id": stages["proposal_sent"]["id"], "pct": 50})
    await act(c, "projects.move_stage", {"id": pr["id"], "stage_id": stages["proposal_sent"]["id"]})
    m0 = today().strftime("%Y-%m")
    m1 = next_month_first().strftime("%Y-%m")
    sp = await act(c, "projects.set_revenue_spread", {"id": pr["id"], "value_paise": 100000000,
                                                       "spread": [{"month": m0, "amount_paise": 50000000}, {"month": m1, "amount_paise": 50000000}]})
    assert sp["difference_paise"] == 0
    f = await act(c, "forecast.get", {"months": 6})
    assert [f["months"][0]["pipeline_paise"], f["months"][1]["pipeline_paise"]] == [25000000, 25000000]
    assert f["months"][0]["confirmed_paise"] == 0
    await act(c, "projects.move_stage", {"id": pr["id"], "stage_id": stages["contract_signed"]["id"]})
    f = await act(c, "forecast.get", {"months": 6})
    assert f["months"][0]["pipeline_paise"] == 0 and f["months"][0]["confirmed_paise"] == 0
    inv = await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": "Study", "qty": 1, "price_paise": 100000000}],
                                           "schedule": [{"label": "Advance", "pct": 50, "due": {"type": "date", "date": (now() + timedelta(days=1)).isoformat()}},
                                                        {"label": "Balance", "pct": 50, "due": {"type": "date", "date": f"{m1}-15T12:00:00+05:30"}}]})
    await act(c, "invoices.send", {"id": inv["id"]})
    f = await act(c, "forecast.get", {"months": 6})
    assert f["months"][1]["confirmed_paise"] == 50000000
    assert f["totals"]["pipeline_paise"] == 0


async def test_fixed_fee_effective_rate_uses_the_fee_received():
    c, ws = await practice()
    pr = await project(c)
    inv = await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": "Audit", "qty": 1, "price_paise": 5000000}]})
    inv = await act(c, "invoices.send", {"id": inv["id"]})
    await act(c, "payments.confirm", {"invoice_id": inv["id"], "item_id": inv["schedule"][0]["id"], "method": "bank"})
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 600})
    r = await act(c, "reports.profitability", {"group": "project"})
    row = next(x for x in r["rows"] if x["key"] == pr["id"])
    assert row["received_paise"] == 5000000 and row["effective_hourly_paise"] == 500000
    u = await act(c, "reports.utilisation", {"period": "week", "count": 2})
    assert u["people"][0]["cells"][-1]["billable_minutes"] == 600


# ======================= A7 client tasks =======================

async def test_client_completes_a_task_from_whatsapp_and_by_link():
    from actions.inbox import receive
    from core.context import system_ctx
    c, ws = await practice()
    pr = await project(c)
    t = await act(c, "client_tasks.assign", {"project_id": pr["id"], "title": "Share last year's P&L",
                                             "due_at": (now() + timedelta(days=2)).isoformat()})
    assert any("P&L" in str(x) for x in await outbox("whatsapp"))
    assert (await act(c, "projects.search", {"waiting_on_client": True}))["total"] == 1
    await receive(system_ctx(ws["id"]), pr["id"], "whatsapp", "+919820011122", "", "Done")
    assert (await get_db().tasks.find_one({"_id": t["id"]}))["done"]
    assert (await act(c, "projects.get", {"id": pr["id"]}))["waiting_on_client"] is False
    # By the link: upload a file (it lands in the project's files), then mark done.
    t2 = await act(c, "client_tasks.assign", {"project_id": pr["id"], "title": "Send the org chart", "channel": "email"})
    pub = client()
    data = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 org chart").decode()
    r = await pub.post(f"/api/public/t/{t2['token']}/upload", json={"name": "org.pdf", "data": data})
    assert r.status_code == 200 and r.json()["task"]["uploads"][0]["name"] == "org.pdf"
    assert await get_db().uploads.count_documents({"project_id": pr["id"], "client_task_id": t2["id"]}) == 1
    r = await pub.post(f"/api/public/t/{t2['token']}/done")
    assert r.json()["task"]["done"] is True
    assert await get_db().events.count_documents({"type": "client_task.completed"}) == 2
    # Clients see only client tasks in the portal.
    await act(c, "tasks.create", {"title": "Internal: prep deck", "project_id": pr["id"]})
    titles = [x["title"] for x in (await act(c, "client_tasks.list", {"status": "all"}))]
    assert "Internal: prep deck" not in titles


async def test_overdue_client_task_gets_a_drafted_nudge():
    from actions.client_tasks import run_due
    c, ws = await practice()
    pr = await project(c)
    await act(c, "client_tasks.assign", {"project_id": pr["id"], "title": "Share bank statements", "due_at": (now() + timedelta(hours=1)).isoformat(),
                                         "remind_days_before": 0})
    advance_clock(hours=2)
    assert await run_due(ws["id"]) == 1
    assert await run_due(ws["id"]) == 0
    await run_jobs()
    assert any(a["action"] == "client_tasks.remind" for a in await act(c, "approvals.list", {}))


async def test_meeting_notes_turn_client_promises_into_client_tasks():
    c, ws = await practice()
    pr = await project(c)
    await act(c, "meetings.add_transcript", {"project_id": pr["id"], "text": "Consultant: Could you share last year's P&L by Friday?\n"
                                             "Consultant: I'll send the proposal today."})
    ap = [a for a in await act(c, "approvals.list", {}) if a["action"] == "client_tasks.assign"]
    assert ap and "P&L" in json.dumps(ap[0]["args"])


# ======================= task templates and recurring tasks =======================

async def test_stage_checklist_once_and_recurring_task_never_twice():
    from actions.retainers import recurring_tasks
    c, ws = await practice()
    pr = await project(c)
    tpl = await act(c, "task_templates.create", {"name": "Kickoff", "items": [{"title": "Send welcome pack", "estimate_hours": 1, "due_days": 2},
                                                                             {"title": "Book kickoff call", "due_days": 3}]})
    stages = {s["key"]: s for s in await act(c, "stages.list")}
    await act(c, "stages.set_task_template", {"stage_id": stages["call_booked"]["id"], "template_id": tpl["id"]})
    for key in ("call_booked", "enquiry", "call_booked"):
        await act(c, "projects.move_stage", {"id": pr["id"], "stage_id": stages[key]["id"]})
        await run_jobs()
    assert await get_db().tasks.count_documents({"project_id": pr["id"], "template_id": tpl["id"]}) == 2
    t = await act(c, "tasks.create", {"title": "Monthly MIS review", "project_id": pr["id"], "due_at": now().isoformat()})
    await act(c, "tasks.set_recurrence", {"id": t["id"], "every": "monthly"})
    advance_clock(minutes=5)
    assert await recurring_tasks(ws["id"]) == 1
    assert await recurring_tasks(ws["id"]) == 0
    assert await get_db().tasks.count_documents({"series_id": t["id"]}) == 2


# ======================= A7 MCP sign-in =======================

CIMD = "https://claude.test/oauth/client.json"
REDIRECT = "https://claude.test/callback"


def pkce():
    v = base64.urlsafe_b64encode(hashlib.sha256(b"verifier-seed").digest()).rstrip(b"=").decode() + "x" * 10
    ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, ch


async def oauth_login(user_client, ws_id, scope="full", client_id=CIMD, redirect=REDIRECT):
    from core import settings
    settings.QA_CIMD[CIMD] = {"client_id": CIMD, "client_name": "Claude", "redirect_uris": [REDIRECT]}
    v, ch = pkce()
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": ch, "code_challenge_method": "S256",
         "state": "xyz", "scope": scope, "resource": "http://localhost:8765/mcp"}
    r = await user_client.get("/oauth/authorize?" + urlencode(q), follow_redirects=False)
    assert r.status_code == 302, r.text
    rid = parse_qs(urlparse(r.headers["location"]).query)["req"][0]
    info = (await user_client.get(f"/api/oauth/request/{rid}")).json()
    assert info["client_name"] == "Claude" or client_id != CIMD
    r = await user_client.post("/api/oauth/consent", json={"req": rid, "approve": True, "scope": scope, "workspace_id": ws_id})
    back = urlparse(r.json()["redirect"])
    qs = parse_qs(back.query)
    assert qs["state"] == ["xyz"] and qs["iss"] == ["http://localhost:8765"]
    pub = client()
    r = await pub.post("/oauth/token", data={"grant_type": "authorization_code", "code": qs["code"][0], "redirect_uri": redirect,
                                             "client_id": client_id, "code_verifier": v, "resource": "http://localhost:8765/mcp"})
    assert r.status_code == 200, r.text
    return r.json(), qs["code"][0], v


async def mcp_call(tok, method, params=None, headers=None):
    return await client().post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                               headers={"Authorization": f"Bearer {tok}", **(headers or {})})


async def test_oauth_discovery_and_401_challenge():
    pub = client()
    prm = (await pub.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert prm["resource"].endswith("/mcp") and prm["authorization_servers"]
    asm = (await pub.get("/.well-known/oauth-authorization-server")).json()
    assert asm["code_challenge_methods_supported"] == ["S256"] and asm["client_id_metadata_document_supported"] is True
    assert asm["authorization_response_iss_parameter_supported"] is True
    r = await pub.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401 and 'resource_metadata="' in r.headers["www-authenticate"]


async def test_oauth_signin_member_with_hidden_money_gets_no_money_fields():
    c, ws = await practice()
    await hourly(c)
    m = await member_with_hidden_money(c)
    tok, code, verifier = await oauth_login(m, ws["id"])
    r = await mcp_call(tok["access_token"], "tools/call", {"name": "rates__resolve", "arguments": {}})
    body = json.loads(r.json()["result"]["content"][0]["text"])
    assert body["rate_paise"] is None and body["hourly_paise"] is None
    tools = (await mcp_call(tok["access_token"], "tools/list")).json()["result"]["tools"]
    assert not any(t["name"].startswith("payments__refund") for t in tools)
    # The new protocol: server/discover and per-request _meta.
    d = (await mcp_call(tok["access_token"], "server/discover", headers={"MCP-Protocol-Version": "2026-07-28"})).json()["result"]
    assert "2026-07-28" in d["supportedVersions"] and d["resultType"] == "complete"
    # A code works once; reuse revokes what it produced.
    pub = client()
    r = await pub.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": CIMD,
                                             "code_verifier": verifier})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert (await mcp_call(tok["access_token"], "tools/list")).status_code == 401


async def test_oauth_refresh_rotates_and_reuse_signs_everyone_out():
    c, ws = await practice()
    tok, _, _ = await oauth_login(c, ws["id"])
    pub = client()
    r = await pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": CIMD})
    new = r.json()
    assert r.status_code == 200 and new["refresh_token"] != tok["refresh_token"]
    assert (await mcp_call(new["access_token"], "tools/list")).status_code == 200
    r = await pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": CIMD})
    assert r.status_code == 400
    assert (await mcp_call(new["access_token"], "tools/list")).status_code == 401
    # Access tokens expire after 15 minutes.
    tok2, _, _ = await oauth_login(c, ws["id"])
    advance_clock(minutes=16)
    assert (await mcp_call(tok2["access_token"], "tools/list")).status_code == 401


async def test_oauth_dcr_pkce_resource_and_scope_step_up():
    c, ws = await practice()
    pub = client()
    r = await pub.post("/oauth/register", json={"client_name": "Old client", "redirect_uris": ["http://localhost:3999/cb"]})
    assert r.status_code == 201
    cid = r.json()["client_id"]
    bad = await c.get("/oauth/authorize?" + urlencode({"response_type": "code", "client_id": cid, "redirect_uri": "https://evil.example/cb",
                                                         "code_challenge": "x", "code_challenge_method": "S256"}), follow_redirects=False)
    assert bad.status_code == 400
    nopkce = await c.get("/oauth/authorize?" + urlencode({"response_type": "code", "client_id": cid, "redirect_uri": "http://localhost:3999/cb"}),
                         follow_redirects=False)
    assert nopkce.status_code == 302 and "error=invalid_request" in nopkce.headers["location"] and "iss=" in nopkce.headers["location"]
    tok, _, _ = await oauth_login(c, ws["id"], scope="read", client_id=cid, redirect="http://localhost:3999/cb")
    pr = await project(c)
    r = await mcp_call(tok["access_token"], "tools/call", {"name": "notes__add", "arguments": {"project_id": pr["id"], "text": "hi"}})
    assert r.status_code == 403 and 'error="insufficient_scope"' in r.headers["www-authenticate"] and 'scope="drafts"' in r.headers["www-authenticate"]
    r = await pub.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "resource": "https://other.example/mcp"})
    assert r.json()["error"] == "invalid_target"
    # Settings: the person sees the connected assistant and can sign it out.
    apps = await act(c, "mcp.connected_apps")
    assert apps and apps[0]["scope"] == "read"
    await act(c, "mcp.disconnect_app", {"client_id": cid})
    assert (await mcp_call(tok["access_token"], "tools/list")).status_code == 401


_ = date


async def test_retainer_time_is_billed_by_the_retainer_not_counted_as_unbilled():
    c, ws = await practice()
    pr = await project(c)
    other = await project(c, "Hourly client", "h@x.in", "9820011144")
    await hourly(c)
    await retainer(c, pr["id"])
    await act(c, "time.log", {"project_id": pr["id"], "minutes": 120})
    await act(c, "time.log", {"project_id": other["id"], "minutes": 60})
    un = await act(c, "time.unbilled", {})
    assert [i["project_id"] for i in un["items"]] == [other["id"]]
    await act(c, "invoices.add_unbilled_time", {"project_id": pr["id"]}, 400)
    advance_clock(days=32)
    await close_due(ws["id"])
    rows = await act(c, "time.list", {"project_id": pr["id"]})
    assert rows[0]["billing_status"] == "billed"
    r = await c.post("/api/a/time.update", json={"id": rows[0]["id"], "minutes": 10})
    assert r.status_code == 409 and "retainer period" in r.json()["error"]["message"]


async def test_retainer_plan_change_starts_next_period():
    c, ws = await practice()
    pr = await project(c)
    r = await retainer(c, pr["id"])
    out = await act(c, "retainers.update", {"id": r["id"], "name": "Advisory retainer", "kind": "hours", "fee_paise": 18000000, "included_hours": 25,
                                            "billing": "advance", "rollover": {"mode": "none"}, "overage": {"mode": "bill"}})
    assert out["note"] and out["current"]["included"] == 20 * 60
    advance_clock(days=32)
    await close_due(ws["id"])
    g = await act(c, "retainers.get", {"id": r["id"]})
    assert g["current"]["included"] == 25 * 60 and g["fee_paise"] == 18000000 and not g.get("pending_plan")
