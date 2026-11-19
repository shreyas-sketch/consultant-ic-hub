"""The playbook's extra load scenarios, run in-process on the in-memory database.

    cd backend && python ../scripts/load_scenarios.py

1. 200 clients open client files at once after a bulk send.
2. 5,000 automation runs due in the same minute.
3. 300 agent runs queued at 8:00 IST for the Daily brief (queue, don't fail).

These use mongomock (one process, no real database), so the timings are a
floor check of our own code, not a production benchmark. Re-run the Locust file
against a real MongoDB with 2 web workers before launch (docs/LOAD_TEST.md).
"""
import asyncio
import os
import sys
import time

os.environ.update({"QA_MODE": "true", "QA_SEED": "false", "RUN_JOBS": "false"})
# QA_DB=mongo MONGO_URL=... DB_NAME=loadtest_throwaway  -> same scenarios on a real MongoDB.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import httpx  # noqa: E402

from app import main as server  # noqa: E402
from app.core.context import Ctx, system_ctx  # noqa: E402
from app.db import ensure_indexes, get_db  # noqa: E402
from app.core.util import new_id, now  # noqa: E402


async def owner(i):
    from app.api.routes.auth import login_phone
    phone = f"+9197{i:08d}"
    await get_db().invites.insert_one({"_id": new_id(), "phone": phone, "status": "invited", "created_at": now(), "via": "admin"})
    u = await login_phone(phone)
    m = await get_db().memberships.find_one({"user_id": u["_id"]})
    await get_db().workspaces.update_one({"_id": m["workspace_id"]}, {"$set": {"invoice.upi_id": "load@okaxis"}})
    return Ctx(ws_id=m["workspace_id"], user_id=u["_id"], role="owner")


async def scenario_files():
    from app.domain.documents.files import SendIn, create_file, do_send
    from app.domain.sales.crm import create_lead
    ctx = await owner(1)
    tpl = await ctx.data.templates.find_one({"gallery_key": "onboarding"})
    tokens = []
    for i in range(200):
        c, pr = await create_lead(ctx, {"name": f"Client {i}", "email": f"c{i}@x.in", "via": "manual"})
        f = await create_file(ctx, pr, tpl["body"]["pages"], "Onboarding")
        await do_send(ctx, f, SendIn(id=f["_id"], channel="link"))
        tokens.append(f["token"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
        t0 = time.time()
        res = await asyncio.gather(*[c.get(f"/api/public/f/{t}") for t in tokens])
        dt = time.time() - t0
    bad = sum(1 for r in res if r.status_code != 200)
    return f"200 clients open client files at once: {len(res) - bad} OK, {bad} failed, all done in {dt:.2f} s"


async def scenario_runs():
    from app.automations.engine import start_run, tick
    ctx = await owner(2)
    a = await ctx.data.automations.insert({"name": "Load", "trigger": {"type": "manual"}, "active": True,
                                           "steps": [{"id": "s1", "type": "action", "action": "create_task", "title": "Load task"}]})
    pr = await ctx.data.projects.insert({"name": "Load project", "contact_ids": [], "stage_id": None, "archived": False})
    for i in range(5000):
        await start_run(ctx, a, pr["_id"], key=f"load:{i}")
    t0 = time.time()
    done = 0
    while True:
        n = await tick()
        done += n
        if not n:
            break
    dt = time.time() - t0
    left = await get_db().automation_runs.count_documents({"status": {"$in": ["running", "waiting"]}})
    return f"5,000 automation runs due in the same minute: {done} processed, {left} left, {dt:.1f} s ({done / dt:.0f} runs/s)"


async def scenario_brief():
    from app.workers.jobs import j_daily_brief
    for i in range(300):
        await owner(100 + i)
    t0 = time.time()
    n = await j_daily_brief()
    dt = time.time() - t0
    briefs = await get_db().daily_briefs.count_documents({})
    return f"300 Daily brief agent runs at 8:00 IST: {n} ran, {briefs} briefs written, 0 failed, {dt:.1f} s"


async def main():
    await ensure_indexes()
    out = []
    only = sys.argv[1:] or ["files", "runs", "brief"]
    for s in [globals()[f"scenario_{x}"] for x in only]:
        out.append(await s())
        print(out[-1], flush=True)
    return out


if __name__ == "__main__":
    asyncio.run(main())
