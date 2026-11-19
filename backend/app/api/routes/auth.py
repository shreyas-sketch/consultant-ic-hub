"""Login: invite-only WhatsApp OTP (SMS fallback), sessions, roles, admin access.

- Only invited numbers can log in. Team members added by an Owner or Admin are
  invited automatically. Others see one line: "This product is by invitation
  right now."
- Sessions: a short access cookie (15 min, signed) plus a refresh cookie
  (30 days, stored). Revoked or removed users lose their sessions.
"""
import hashlib
import random
import re
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel

from app.core import settings
from app.core.context import Ctx
from app.db import get_db
from app.core.util import AppError, aware, clean, new_id, now, token

router = APIRouter(prefix="/api/auth")
_ser = URLSafeTimedSerializer(settings.SECRET_KEY, salt="access")
ACCESS_SECONDS = 15 * 60
REFRESH_DAYS = 30
NOT_INVITED = "This product is by invitation right now."


def norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 11 or len(digits) > 15:
        raise AppError("invalid", "Please enter a valid mobile number.", 400)
    return "+" + digits


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


async def is_invited(phone) -> bool:
    if phone in settings.ADMIN_PHONES:
        return True
    inv = await get_db().invites.find_one({"phone": phone})
    return bool(inv and inv.get("status") in ("invited", "joined"))


class OtpReq(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


@router.post("/otp/request")
async def otp_request(body: OtpReq, request: Request):
    phone = norm_phone(body.phone)
    db = get_db()
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    hour_ago = now() - timedelta(hours=1)
    if await db.otp_codes.count_documents({"ip": ip, "created_at": {"$gt": hour_ago}}) >= settings.OTP_PER_IP_PER_HOUR:
        raise AppError("rate_limited", "Too many codes from this network. Please try again in a while.", 429)
    if not await is_invited(phone):
        raise AppError("not_invited", NOT_INVITED, 403)
    last = await db.otp_codes.find_one({"phone": phone}, sort=[("created_at", -1)])
    if last and aware(last["created_at"]) > now() - timedelta(seconds=30):
        raise AppError("cooldown", "Please wait 30 seconds before asking for a new code.", 429)
    code = f"{random.SystemRandom().randint(0, 999999):06d}"
    await db.otp_codes.insert_one({"_id": new_id(), "phone": phone, "code_hash": _h(code), "tries": 0, "ip": ip,
                                   "created_at": now(), "expires_at": now() + timedelta(minutes=10), "used": False})
    channel = await __import__("app.integrations.vendors", fromlist=["x"]).otp_send(phone, code)
    out = {"ok": True, "channel": channel}
    if settings.QA_MODE:
        out["qa_code"] = code  # shown on screen in QA mode only
    return out


async def check_otp(phone, code) -> bool:
    """Shared by consultant login and client signing/portal OTP."""
    db = get_db()
    if settings.QA_MODE and code == "000000":
        return True
    row = await db.otp_codes.find_one({"phone": phone, "used": False}, sort=[("created_at", -1)])
    if not row or aware(row["expires_at"]) < now():
        raise AppError("otp_expired", "That code has expired. Please ask for a new one.", 400)
    if row["tries"] >= 5:
        raise AppError("otp_locked", "Too many wrong tries. Please ask for a new code.", 429)
    if row["code_hash"] != _h(code.strip()):
        await db.otp_codes.update_one({"_id": row["_id"]}, {"$inc": {"tries": 1}})
        raise AppError("otp_wrong", "That code is not right. Please check and try again.", 400)
    await db.otp_codes.update_one({"_id": row["_id"]}, {"$set": {"used": True}})
    return True


def _set_cookies(resp: Response, user_id, sid, refresh=None):
    resp.set_cookie("pos_access", _ser.dumps({"u": user_id, "s": sid}), max_age=ACCESS_SECONDS, httponly=True,
                    samesite="lax", secure=not settings.QA_MODE)
    if refresh:
        resp.set_cookie("pos_refresh", refresh, max_age=REFRESH_DAYS * 86400, httponly=True, samesite="lax",
                        secure=not settings.QA_MODE)


async def start_session(resp: Response, user, ws_id=None, utm=None):
    sid, refresh = new_id(), token(32)
    await get_db().sessions_auth.insert_one({"_id": sid, "user_id": user["_id"], "refresh_hash": _h(refresh),
                                             "ws_id": ws_id, "created_at": now(),
                                             "expires_at": now() + timedelta(days=REFRESH_DAYS)})
    _set_cookies(resp, user["_id"], sid, refresh)
    return sid


@router.post("/otp/verify")
async def otp_verify(body: OtpVerify, response: Response):
    phone = norm_phone(body.phone)
    if not await is_invited(phone):
        raise AppError("not_invited", NOT_INVITED, 403)
    await check_otp(phone, body.code)
    user = await login_phone(phone)
    ws_id = await default_workspace(user)
    await start_session(response, user, ws_id)
    return {"ok": True, "user": public_user(user)}


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


async def current(request: Request, response: Response):
    """(user, session) from cookies, refreshing the access cookie when needed."""
    db = get_db()
    data = None
    tok = request.cookies.get("pos_access")
    if tok:
        try:
            data = _ser.loads(tok, max_age=ACCESS_SECONDS)
        except (BadSignature, SignatureExpired):
            data = None
    sess = None
    if data:
        sess = await db.sessions_auth.find_one({"_id": data["s"]})
    if not sess:
        rf = request.cookies.get("pos_refresh")
        if rf:
            sess = await db.sessions_auth.find_one({"refresh_hash": _h(rf)})
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
    return ctx


async def get_admin(request: Request, response: Response):
    user, sess = await current(request, response)
    if not (user.get("is_admin") or user.get("staff")):
        raise AppError("forbidden", "This area is for the product team only.", 403)
    return user


@router.get("/me")
async def me(request: Request, response: Response):
    user, sess = await current(request, response)
    db = get_db()
    ms = await db.memberships.find({"user_id": user["_id"], "active": True}).to_list(None)
    wss = []
    for m in ms:
        w = await db.workspaces.find_one({"_id": m["workspace_id"]}, {"name": 1, "slug": 1, "onboarded": 1})
        if w:
            wss.append({"id": w["_id"], "name": w["name"], "slug": w["slug"], "role": m["role"], "onboarded": w.get("onboarded", False)})
    return {"user": public_user(user), "workspaces": wss, "current": sess.get("ws_id"), "qa": settings.QA_MODE,
            "brand": settings.BRAND_NAME}


class SwitchReq(BaseModel):
    workspace_id: str


@router.post("/switch")
async def switch(body: SwitchReq, request: Request, response: Response):
    user, sess = await current(request, response)
    m = await get_db().memberships.find_one({"workspace_id": body.workspace_id, "user_id": user["_id"], "active": True})
    if not m:
        raise AppError("forbidden", "You are not part of that practice.", 403)
    await get_db().sessions_auth.update_one({"_id": sess["_id"]}, {"$set": {"ws_id": body.workspace_id}})
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    try:
        user, sess = await current(request, response)
        await get_db().sessions_auth.delete_one({"_id": sess["_id"]})
    except AppError:
        pass
    response.delete_cookie("pos_access")
    response.delete_cookie("pos_refresh")
    return {"ok": True}


class StaffLogin(BaseModel):
    email: str
    password: str


@router.post("/staff")
async def staff_login(body: StaffLogin, response: Response):
    if not settings.STAFF_EMAIL or body.email.strip().lower() != settings.STAFF_EMAIL.lower() or body.password != settings.STAFF_PASSWORD:
        raise AppError("wrong_login", "That email or password is not right.", 401)
    db = get_db()
    user = await db.users.find_one({"phone": "staff"})
    if not user:
        user = {"_id": new_id(), "phone": "staff", "name": "Staff", "staff": True, "is_admin": True, "created_at": now()}
        await db.users.insert_one(user)
    await start_session(response, user)
    return {"ok": True}


async def revoke_sessions(user_id):
    await get_db().sessions_auth.delete_many({"user_id": user_id})


__all__ = ["router", "get_ctx", "get_admin", "check_otp", "norm_phone", "start_session", "clean"]
