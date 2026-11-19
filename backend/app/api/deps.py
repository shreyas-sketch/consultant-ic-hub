"""FastAPI dependencies: who is calling, and in which practice.

`get_ctx` builds the request Ctx from the session. The workspace id comes from
the session (or the X-Workspace header, checked against memberships); the client
never gets to pick a workspace it is not a member of.
"""
from fastapi import Request, Response

from app.auth import current
from app.core.context import Ctx
from app.core.util import AppError
from app.db import get_db


def client_ip(request: Request) -> str:
    """Best-effort client IP behind Railway's edge proxy (X-Real-IP), then X-Forwarded-For."""
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


async def get_ctx(request: Request, response: Response) -> Ctx:
    user, sess = await current(request, response)
    db = get_db()
    ws_id = request.headers.get("x-workspace") or sess.get("ws_id")
    m = await db.memberships.find_one({"workspace_id": ws_id, "user_id": user["_id"], "active": True}) if ws_id else None
    if not m:
        raise AppError("no_workspace", "You are not part of a practice yet.", 403)
    ws = await db.workspaces.find_one({"_id": ws_id})
    from app.domain.perm import hide_money_for
    hide = hide_money_for(ws, m["role"])
    removed = bool(user.get("access_removed")) or bool(ws.get("read_only"))
    ctx = Ctx(ws_id=ws_id, user_id=user["_id"], role=m["role"], actor="user", project_ids=m.get("project_ids", []),
              hide_money=hide, read_only=bool(removed))
    ctx._ws = ws
    ctx.user = user
    request.state.workspace_id = ws_id
    request.state.user_id = user["_id"]
    return ctx


async def get_admin(request: Request, response: Response):
    user, _ = await current(request, response)
    if not (user.get("is_admin") or user.get("staff")):
        raise AppError("forbidden", "This area is for the product team only.", 403)
    return user
