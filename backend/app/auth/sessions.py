"""Sessions: a short signed access cookie (15 min) plus a stored refresh cookie (30 days).

Revoked or removed users lose their sessions on the next request.
"""
from datetime import timedelta

from fastapi import Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core import settings
from app.core.security import hash_secret
from app.core.util import AppError, aware, new_id, now, token
from app.db import get_db

ACCESS_SECONDS = 15 * 60
REFRESH_DAYS = 30
ACCESS_COOKIE = "pos_access"
REFRESH_COOKIE = "pos_refresh"

_ser = URLSafeTimedSerializer(settings.SECRET_KEY, salt="access")


def _secure() -> bool:
    return not settings.QA_MODE or settings.APP_URL.startswith("https://")


def _set_cookies(resp: Response, user_id, sid, refresh=None):
    resp.set_cookie(ACCESS_COOKIE, _ser.dumps({"u": user_id, "s": sid}), max_age=ACCESS_SECONDS, httponly=True,
                    samesite="lax", secure=_secure())
    if refresh:
        resp.set_cookie(REFRESH_COOKIE, refresh, max_age=REFRESH_DAYS * 86400, httponly=True, samesite="lax",
                        secure=_secure())


def clear_cookies(resp: Response):
    resp.delete_cookie(ACCESS_COOKIE)
    resp.delete_cookie(REFRESH_COOKIE)


async def start_session(resp: Response, user, ws_id=None):
    sid, refresh = new_id(), token(32)
    await get_db().sessions_auth.insert_one({"_id": sid, "user_id": user["_id"], "refresh_hash": hash_secret(refresh),
                                             "ws_id": ws_id, "created_at": now(),
                                             "expires_at": now() + timedelta(days=REFRESH_DAYS)})
    _set_cookies(resp, user["_id"], sid, refresh)
    return sid


async def current(request: Request, response: Response):
    """(user, session) from cookies, refreshing the access cookie when needed."""
    db = get_db()
    data = None
    tok = request.cookies.get(ACCESS_COOKIE)
    if tok:
        try:
            data = _ser.loads(tok, max_age=ACCESS_SECONDS)
        except (BadSignature, SignatureExpired):
            data = None
    sess = None
    if data:
        sess = await db.sessions_auth.find_one({"_id": data["s"]})
    if not sess:
        rf = request.cookies.get(REFRESH_COOKIE)
        if rf:
            sess = await db.sessions_auth.find_one({"refresh_hash": hash_secret(rf)})
            if sess and aware(sess["expires_at"]) > now():
                _set_cookies(response, sess["user_id"], sess["_id"])
            else:
                sess = None
    if not sess:
        raise AppError("logged_out", "Please log in again.", 401)
    user = await db.users.find_one({"_id": sess["user_id"]})
    if not user or user.get("revoked"):
        raise AppError("logged_out", "Please log in again.", 401)
    return user, sess


async def current_user(request: Request, response: Response):
    return (await current(request, response))[0]


async def current_user_or_none(request: Request):
    try:
        return (await current(request, Response()))[0]
    except AppError:
        return None


async def end_session(session_id: str):
    await get_db().sessions_auth.delete_one({"_id": session_id})


async def revoke_sessions(user_id):
    await get_db().sessions_auth.delete_many({"user_id": user_id})
