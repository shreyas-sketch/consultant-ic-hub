"""Distributed leases on MongoDB (`job_locks`): one holder at a time across all processes.

A lease is a row {_id: name, until: <time>}. Taking it succeeds when the row
is missing, released (until=None) or expired. Two processes racing on a missing
row both try to insert the same _id; the loser gets a duplicate-key error.
"""
from datetime import timedelta

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.util import now
from app.db.client import get_db


async def acquire(name: str, seconds: int) -> bool:
    try:
        r = await get_db().job_locks.find_one_and_update(
            {"_id": name, "$or": [{"until": None}, {"until": {"$lt": now()}}]},
            {"$set": {"until": now() + timedelta(seconds=seconds)}},
            upsert=True, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        return False
    return r is not None


async def renew(name: str, seconds: int):
    await get_db().job_locks.update_one({"_id": name}, {"$set": {"until": now() + timedelta(seconds=seconds)}})


async def release(name: str):
    await get_db().job_locks.update_one({"_id": name}, {"$set": {"until": None}})
