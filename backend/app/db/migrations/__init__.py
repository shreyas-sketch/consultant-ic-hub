"""Versioned data migrations.

Each migration is a module `mNNNN_<name>.py` with `ID` and `async def up(db)`.
Applied ids are recorded in `schema_migrations`; a lease in `job_locks` makes
sure only one process migrates at a time (Railway may start several replicas).
Migrations must be safe to re-run: a crash mid-way leaves it unrecorded and the
next deploy runs it again.

Run with:  python -m app.db.migrate        (Railway pre-deploy command)
"""
import importlib
import logging
import pkgutil
import time
from datetime import timedelta

from app.core.util import now

log = logging.getLogger("app.db.migrations")
LOCK = "migrations"


def discover():
    mods = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("m") and info.name[1:5].isdigit():
            mods.append(importlib.import_module(f"{__name__}.{info.name}"))
    return sorted(mods, key=lambda m: m.ID)


async def _lease(db, seconds=900):
    try:
        r = await db.job_locks.find_one_and_update(
            {"_id": LOCK, "$or": [{"until": None}, {"until": {"$lt": now()}}]},
            {"$set": {"until": now() + timedelta(seconds=seconds)}}, upsert=True)
        return r is not None
    except Exception:  # duplicate key: someone else holds it
        return False


async def pending(db):
    done = {r["_id"] for r in await db.schema_migrations.find({}, {"_id": 1}).to_list(None)}
    return [m for m in discover() if m.ID not in done]


async def migrate(db=None, wait_seconds=120):
    """Apply every pending migration once. Returns the ids applied by this process."""
    import asyncio

    from app.db.client import get_db
    db = db or get_db()
    t_end = time.time() + wait_seconds
    while not await _lease(db):
        if time.time() > t_end:
            raise RuntimeError("Another process has held the migration lock for too long.")
        await asyncio.sleep(2)
    applied = []
    try:
        for m in await pending(db):
            t0 = time.perf_counter()
            n = await m.up(db)
            await db.schema_migrations.insert_one({"_id": m.ID, "applied_at": now(), "result": n,
                                                   "seconds": round(time.perf_counter() - t0, 2)})
            log.info("migration applied: %s (%s)", m.ID, n)
            applied.append(m.ID)
    finally:
        await db.job_locks.update_one({"_id": LOCK}, {"$set": {"until": None}})
    return applied
