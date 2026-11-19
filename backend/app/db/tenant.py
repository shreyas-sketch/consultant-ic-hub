"""The one data-access helper. Every read and write is filtered by workspace_id.

Actions never touch the raw database. They get `ctx.data`, which only knows
one workspace. A test fails if any file in actions/ imports get_db.
"""
from app.db import GLOBAL_COLLECTIONS, TENANT_COLLECTIONS, get_db
from app.core.util import new_id, now


class TenantCollection:
    def __init__(self, coll, ws_id):
        self._c = coll
        self.ws_id = ws_id

    def _f(self, flt=None, include_deleted=False):
        f = dict(flt or {})
        f["workspace_id"] = self.ws_id
        if not include_deleted and "deleted_at" not in f:
            f["deleted_at"] = None
        return f

    async def find(self, flt=None, sort=None, limit=0, skip=0, include_deleted=False, projection=None):
        cur = self._c.find(self._f(flt, include_deleted), projection)
        if sort:
            cur = cur.sort(sort)
        if skip:
            cur = cur.skip(skip)
        if limit:
            cur = cur.limit(limit)
        return await cur.to_list(length=None)

    async def find_one(self, flt=None, include_deleted=False, sort=None):
        if sort:
            rows = await self.find(flt, sort=sort, limit=1, include_deleted=include_deleted)
            return rows[0] if rows else None
        return await self._c.find_one(self._f(flt, include_deleted))

    async def get(self, _id, include_deleted=False):
        return await self.find_one({"_id": _id}, include_deleted=include_deleted)

    async def count(self, flt=None, include_deleted=False):
        return await self._c.count_documents(self._f(flt, include_deleted))

    async def insert(self, doc: dict) -> dict:
        d = dict(doc)
        d.setdefault("_id", new_id())
        d["workspace_id"] = self.ws_id
        t = now()
        d.setdefault("created_at", t)
        d["updated_at"] = t
        d.setdefault("deleted_at", None)
        await self._c.insert_one(d)
        return d

    async def update(self, flt, changes: dict, raw: dict = None, include_deleted=False):
        upd = dict(raw or {})
        s = dict(upd.get("$set", {}))
        s.update(changes or {})
        s["updated_at"] = now()
        upd["$set"] = s
        return await self._c.update_one(self._f(flt, include_deleted), upd)

    async def update_many(self, flt, changes: dict):
        c = dict(changes)
        c["updated_at"] = now()
        return await self._c.update_many(self._f(flt), {"$set": c})

    async def find_one_and_update(self, flt, update, upsert=False, include_deleted=False):
        from pymongo import ReturnDocument
        f = self._f(flt, include_deleted)
        if upsert:
            update = dict(update)
            soi = dict(update.get("$setOnInsert", {}))
            if "_id" not in f:
                soi.setdefault("_id", new_id())
            soi["created_at"] = now()
            update["$setOnInsert"] = soi
        return await self._c.find_one_and_update(f, update, upsert=upsert, return_document=ReturnDocument.AFTER)

    async def soft_delete(self, flt):
        return await self._c.update_many(self._f(flt), {"$set": {"deleted_at": now()}})

    async def hard_delete(self, flt):
        return await self._c.delete_many(self._f(flt, include_deleted=True))


class Data:
    def __init__(self, ws_id: str, db=None):
        if not ws_id:
            raise ValueError("workspace_id is required")
        self.ws_id = ws_id
        self._db = db or get_db()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in GLOBAL_COLLECTIONS:
            raise PermissionError(f"{name} is a global collection; use core.globaldb")
        if name not in TENANT_COLLECTIONS:
            raise AttributeError(f"Unknown collection {name}")
        return TenantCollection(self._db[name], self.ws_id)
