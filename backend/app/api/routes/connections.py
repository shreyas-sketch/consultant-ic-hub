"""OAuth for the consultant's own accounts (Gmail, Outlook, Zoom).

The state value is single-use, bound to the user and workspace, and expires
after 10 minutes (stored in `oauth_states`, cleaned up by a TTL index).
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from app.api.deps import get_ctx
from app.core import settings
from app.core.util import AppError, new_id, now, token
from app.db import get_db
from app.integrations import vendors

router = APIRouter(prefix="/api/connect", tags=["connections"])
STATE_TTL = timedelta(minutes=10)


def _redirect_uri(provider):
    return f"{settings.APP_URL}/api/connect/{provider}/callback"


@router.get("/{provider}/start")
async def connect_start(provider: str, ctx=Depends(get_ctx)):
    if provider not in vendors.OAUTH:
        raise AppError("not_found", "Unknown account type.", 404)
    state = token(16)
    await get_db().oauth_states.insert_one({"_id": state, "ws": ctx.ws_id, "user": ctx.user_id, "provider": provider,
                                            "created_at": now(), "expires_at": now() + STATE_TTL})
    if vendors.mode(provider) == "fake":
        return {"url": f"{_redirect_uri(provider)}?code=fake&state={state}"}
    return {"url": vendors.oauth_url(provider, state, _redirect_uri(provider))}


@router.get("/{provider}/callback")
async def connect_callback(provider: str, code: str = "", state: str = ""):
    db = get_db()
    # Single use: delete-and-return, so a replayed state finds nothing.
    st = await db.oauth_states.find_one_and_delete({"_id": state, "provider": provider, "expires_at": {"$gt": now()}})
    if not st or not code:
        return RedirectResponse("/settings?connect=failed")
    try:
        tok = await vendors.oauth_exchange(provider, code, _redirect_uri(provider))
    except Exception:
        return RedirectResponse("/settings?connect=failed")
    await db.connections.delete_many({"workspace_id": st["ws"], "user_id": st["user"], "provider": provider})
    await db.connections.insert_one({"_id": new_id(), "workspace_id": st["ws"], "user_id": st["user"], "provider": provider,
                                     "account": tok.get("account"), "tokens": vendors.encrypt(tok), "lead_finder": provider != "zoom",
                                     "created_at": now(), "deleted_at": None})
    return RedirectResponse(f"/settings?connected={provider}")
