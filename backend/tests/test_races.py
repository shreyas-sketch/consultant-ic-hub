"""Concurrency: the same request fired many times at the same instant.

The in-memory database barely interleaves, so these matter most on a real
server:  QA_DB=mongo MONGO_URL=... python -m pytest tests/test_races.py
"""
import asyncio
import base64
from datetime import timedelta

from conftest import act, client, invite, login, ready_practice
from app.core.util import now
from app.db import get_db

N = 10


async def owner(phone):
    c = await login(phone, "Priya Mehta")
    ws = await ready_practice(c)
    return c, ws


async def test_parallel_sends_get_unique_gapless_invoice_numbers():
    c, _ = await owner("+919833300001")
    pr = await act(c, "projects.create", {"name": "X", "contact": {"name": "Ravi", "email": "ravi@x.in"}})
    drafts = [await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": f"L{i}", "qty": 1, "price_paise": 100000}]})
              for i in range(N)]
    rs = await asyncio.gather(*[c.post("/api/a/invoices.send", json={"id": d["id"]}) for d in drafts])
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs if r.status_code != 200]
    nums = sorted(int(r.json()["number"][-4:]) for r in rs)
    assert nums == list(range(1, N + 1)), nums


async def test_parallel_confirms_write_one_ledger_row():
    c, _ = await owner("+919833300002")
    pr = await act(c, "projects.create", {"name": "X", "contact": {"name": "Ravi", "email": "ravi@x.in"}})
    inv = await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": "Audit", "qty": 1, "price_paise": 5000000}]})
    await act(c, "invoices.send", {"id": inv["id"]})
    item = (await act(c, "invoices.get", {"id": inv["id"]}))["schedule"][0]["id"]
    rs = await asyncio.gather(*[c.post("/api/a/payments.confirm", json={"invoice_id": inv["id"], "item_id": item}) for _ in range(N)])
    assert all(r.status_code < 500 for r in rs), [r.text for r in rs if r.status_code >= 500]
    assert await get_db().ledger.count_documents({"invoice_id": inv["id"], "type": "payment"}) == 1
    assert (await act(c, "invoices.get", {"id": inv["id"]}))["status"] == "paid"


async def test_parallel_claims_from_the_client_make_one_claim():
    c, _ = await owner("+919833300003")
    pr = await act(c, "projects.create", {"name": "X", "contact": {"name": "Ravi", "email": "ravi@x.in", "phone": "9820000003"}})
    inv = await act(c, "payments.request", {"project_id": pr["id"], "amount_paise": 2500000, "label": "Session"})
    item = (await act(c, "invoices.get", {"id": inv["id"]}))["schedule"][0]["id"]
    pub = client()
    rs = await asyncio.gather(*[pub.post(f"/api/public/i/{inv['token']}/claim", json={"item_id": item, "method": "upi"}) for _ in range(N)])
    assert all(r.status_code < 500 for r in rs), [r.text for r in rs if r.status_code >= 500]
    assert len((await act(c, "invoices.get", {"id": inv["id"]}))["claims"]) == 1


async def test_many_clients_take_the_same_slot_one_wins():
    c, ws = await owner("+919833300004")
    st = next(s for s in await act(c, "session_types.list") if s["key"] == "discovery")
    pub = client()
    day = (now() + timedelta(days=2)).date()
    slot = (await pub.get(f"/api/public/{ws['slug']}/book/{st['slug']}/slots", params={"date_from": day.isoformat()})).json()[0]
    rs = await asyncio.gather(*[client().post(f"/api/public/{ws['slug']}/book/{st['slug']}",
                                              json={"contact": {"name": f"C{i}", "email": f"c{i}@x.in"}, "start": slot}) for i in range(N)])
    assert all(r.status_code < 500 for r in rs), [r.text for r in rs if r.status_code >= 500]
    assert sum(r.status_code == 200 for r in rs) == 1
    assert await get_db().sessions.count_documents({"status": "booked", "start": {"$exists": True}}) == 1


async def test_one_login_code_signs_in_once():
    phone = "+919833300005"
    await invite(phone, "Asha")
    c = client()
    code = (await c.post("/api/auth/otp/request", json={"phone": phone})).json()["qa_code"]
    rs = await asyncio.gather(*[client().post("/api/auth/otp/verify", json={"phone": phone, "code": code}) for _ in range(N)])
    assert all(r.status_code < 500 for r in rs), [r.text for r in rs if r.status_code >= 500]
    assert sum(r.status_code == 200 for r in rs) == 1


async def test_practices_created_at_the_same_moment_get_different_addresses():
    phones = [f"+9198333001{i:02d}" for i in range(6)]
    for p in phones:
        await get_db().invites.insert_one({"_id": p, "phone": p, "name": "Same", "practice_name": "Same Advisory",
                                           "status": "invited", "created_at": now(), "via": "admin"})
    from app.auth import login_phone
    await asyncio.gather(*[login_phone(p) for p in phones])
    slugs = [w["slug"] for w in await get_db().workspaces.find({"name": "Same Advisory"}).to_list(None)]
    assert len(slugs) == len(phones) and len(set(slugs)) == len(phones), slugs


async def test_parallel_uploads_never_overshoot_the_storage_cap():
    c, ws = await owner("+919833300006")
    await get_db().account_overrides.insert_one({"_id": "o1", "workspace_id": ws["id"], "key": "storage_mb", "value": 1, "ends_at": None})
    blob = "data:application/pdf;base64," + base64.b64encode(b"%PDF-" + b"x" * 300_000).decode()   # ~300 KB each
    rs = await asyncio.gather(*[c.post("/api/upload", json={"data": blob, "name": f"f{i}"}) for i in range(N)])
    assert all(r.status_code in (200, 402) for r in rs), [r.text for r in rs]
    ok = sum(r.status_code == 200 for r in rs)
    assert ok == 3, ok          # 3 × 300 KB fits in 1 MB, a 4th does not
    used = (await get_db().workspaces.find_one({"_id": ws["id"]}))["storage_bytes"]
    assert used <= 1024 * 1024


async def test_first_seats_of_a_group_session_booked_together_are_not_refused():
    from datetime import datetime, timezone
    from app.core.context import system_ctx
    from app.domain.engagement.scheduling import lock_slot
    ctx = system_ctx("ws-race")
    st = {"_id": "st1", "max_attendees": 4, "host_ids": ["h1"]}
    start = datetime(2027, 1, 5, 10, 0, tzinfo=timezone.utc)
    rs = await asyncio.gather(*[lock_slot(ctx, st, start, f"s{i}") for i in range(6)], return_exceptions=True)
    ok = [r for r in rs if not isinstance(r, Exception)]
    full = [r for r in rs if isinstance(r, Exception)]
    assert len(ok) == 4 and all(getattr(e, "code", "") == "slot_taken" for e in full), rs


async def test_budget_cycle_created_once_under_parallel_checks():
    from app.core.context import system_ctx
    from app.domain.billing.budgets import cycle_doc
    ctx = system_ctx("ws-race")
    b = {"_id": "b1", "project_id": "p1"}
    rs = await asyncio.gather(*[cycle_doc(ctx, b, "2027-01-01", "2027-01-31") for _ in range(N)])
    assert len({r["_id"] for r in rs}) == 1
    assert await get_db().budget_cycles.count_documents({"cycle_key": "b1:2027-01-01"}) == 1
