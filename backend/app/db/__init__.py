"""Database access: the client, the collection registry, indexes and migrations.

Domain code uses `ctx.data.<collection>` (tenant-scoped). Only infrastructure
(auth, jobs, admin, public routes resolving a token) uses `get_db()` directly.
"""
from app.db.client import close, get_db, ping, reporting_db, reset_db
from app.db.collections import GLOBAL_COLLECTIONS, TENANT_COLLECTIONS
from app.db.indexes import ensure_indexes

__all__ = ["close", "get_db", "ping", "reporting_db", "reset_db", "GLOBAL_COLLECTIONS", "TENANT_COLLECTIONS",
           "ensure_indexes"]
