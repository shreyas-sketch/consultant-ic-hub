"""QA mode helpers: persona login, the fake outbox, moving the clock, running jobs now.

Only mounted when QA_MODE=true. Never available in production.
"""
from fastapi import APIRouter, Response

from app.core.util import AppError, advance_clock, clean, now
from app.db import get_db

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("/login")
async def qa_login(body: dict, response: Response):
    from app.auth import default_workspace, login_phone, start_session
    from app.db.seed import PERSONAS
    phone = PERSONAS.get(body.get("persona", "owner"))
    if not phone:
        raise AppError("invalid", "Unknown persona.", 400)
    user = await login_phone(phone)
    await start_session(response, user, await default_workspace(user))
    return {"ok": True, "persona": body.get("persona", "owner")}


@router.get("/outbox")
async def qa_outbox(limit: int = 30):
    rows = await get_db().vendor_log.find({}).sort("at", -1).to_list(min(limit, 200))
    return clean(rows)


@router.post("/clock")
async def qa_clock(body: dict):
    advance_clock(minutes=int(body.get("minutes", 0)))
    return {"now": now().isoformat()}


@router.post("/run_jobs")
async def qa_jobs():
    from app.workers.jobs import JOBS, run_job
    out = {}
    for _ in range(2):
        for n in JOBS:
            out[n] = await run_job(n, force=True)
    return out
