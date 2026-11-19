"""Accounts: invitations, first login and the user's default practice."""
from app.core import settings
from app.core.util import new_id, now
from app.db import get_db

NOT_INVITED = "This product is by invitation right now."


async def is_invited(phone) -> bool:
    if phone in settings.ADMIN_PHONES:
        return True
    inv = await get_db().invites.find_one({"phone": phone})
    return bool(inv and inv.get("status") in ("invited", "joined"))


async def login_phone(phone):
    """Find or create the user for an invited phone; set up their workspace."""
    db = get_db()
    user = await db.users.find_one({"phone": phone})
    inv = await db.invites.find_one({"phone": phone})
    if not user:
        user = {"_id": new_id(), "phone": phone, "name": (inv or {}).get("name", ""), "email": "",
                "is_admin": phone in settings.ADMIN_PHONES, "created_at": now(), "access_removed": False}
        await db.users.insert_one(user)
    if inv and inv.get("status") != "joined":
        await db.invites.update_one({"_id": inv["_id"]}, {"$set": {"status": "joined", "joined_at": now(), "user_id": user["_id"]}})
    has_ws = await db.memberships.find_one({"user_id": user["_id"], "active": True})
    pending = await db.memberships.find_one({"user_id": "pending:" + phone})
    if pending:
        await db.memberships.update_many({"user_id": "pending:" + phone}, {"$set": {"user_id": user["_id"], "active": True}})
        has_ws = True
    if not has_ws and not (user.get("is_admin") and not inv):
        from app.domain.workspace.workspace import create_workspace
        await create_workspace(user, name=(inv or {}).get("practice_name") or f"{user.get('name') or 'My'} practice".strip())
    return user


async def default_workspace(user):
    m = await get_db().memberships.find_one({"user_id": user["_id"], "active": True}, sort=[("created_at", 1)])
    return m["workspace_id"] if m else None


def public_user(u):
    return {"id": u["_id"], "phone": u["phone"], "name": u.get("name", ""), "email": u.get("email", ""),
            "is_admin": bool(u.get("is_admin"))}
