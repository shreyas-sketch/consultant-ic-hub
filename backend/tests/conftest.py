import os
import sys

os.environ["QA_MODE"] = "true"
os.environ["QA_SEED"] = "false"
os.environ["RUN_JOBS"] = "false"
os.environ.setdefault("UPLOAD_DIR", "/tmp/practice-os-test-uploads")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import main as server  # noqa: E402
from app.core import limits  # noqa: E402
from app.db import ensure_indexes, get_db, reset_db  # noqa: E402
from app.core.util import new_id, now, reset_clock  # noqa: E402


def pin_clock():
    """Tests run on a Wednesday at 11:00 IST, whatever the real time is."""
    from datetime import timedelta
    from app.core.util import IST, advance_clock
    t = now().astimezone(IST)
    target = t.replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=(2 - t.weekday()) % 7)
    advance_clock(seconds=(target - t).total_seconds())


@pytest.fixture(autouse=True)
async def fresh():
    reset_db()
    reset_clock()
    pin_clock()
    limits.bust_cache()
    await ensure_indexes()
    yield
    reset_clock()


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test")


async def invite(phone, name="", note="test"):
    await get_db().invites.insert_one({"_id": new_id(), "phone": phone, "name": name, "note": note, "status": "invited",
                                       "created_at": now(), "via": "admin"})


async def login(phone, name="Test Consultant", invited=True):
    if invited:
        await invite(phone, name)
    c = client()
    r = await c.post("/api/auth/otp/request", json={"phone": phone})
    assert r.status_code == 200, r.text
    r = await c.post("/api/auth/otp/verify", json={"phone": phone, "code": "000000"})
    assert r.status_code == 200, r.text
    return c


async def act(c, name, body=None, status=200):
    r = await c.post(f"/api/a/{name}", json=body or {})
    assert r.status_code == status, f"{name}: {r.status_code} {r.text}"
    return r.json()


async def ready_practice(c, upi="test@okaxis"):
    await act(c, "workspace.update", {"invoice": {"upi_id": upi}, "profile": {"consultant_name": "Priya"}})
    return await act(c, "workspace.get")


async def run_jobs():
    from app.automations.engine import dispatch, tick
    for _ in range(4):
        await dispatch()
        await tick()


async def outbox(kind=None):
    f = {"kind": kind} if kind else {}
    return await get_db().vendor_log.find(f).to_list(None)
