"""0002: every workspace has a numeric storage_bytes counter.

The storage quota is now reserved atomically with a conditional $inc
(app/integrations/vendors.storage_put); giving every workspace the field keeps
that filter simple and index-friendly.
"""
ID = "0002_workspace_storage_counter"


async def up(db):
    r = await db.workspaces.update_many({"storage_bytes": {"$exists": False}}, {"$set": {"storage_bytes": 0}})
    return r.modified_count
