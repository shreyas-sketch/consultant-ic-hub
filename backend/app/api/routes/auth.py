"""Login routes: invite-only WhatsApp OTP (SMS fallback), workspace switch, staff login."""
from datetime import timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.api.deps import client_ip
from app.auth import (NOT_INVITED, check_otp, clear_cookies, current, default_workspace, end_session, is_invited,
                      issue_otp, login_phone, norm_phone, public_user, start_session)
from app.core import settings
from app.core.security import secrets_equal
from app.core.util import AppError, new_id, now
from app.db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class OtpReq(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


@router.post("/otp/request")
async def otp_request(body: OtpReq, request: Request):
    phone = norm_phone(body.phone)
    if not await is_invited(phone):
        raise AppError("not_invited", NOT_INVITED, 403)
    return await issue_otp(phone, client_ip(request))


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


@router.get("/me")
async def me(request: Request, response: Response):
    user, sess = await current(request, response)
    db = get_db()
    ms = await db.memberships.find({"user_id": user["_id"], "active": True}).to_list(None)
    ids = [m["workspace_id"] for m in ms]
    by_id = {w["_id"]: w for w in await db.workspaces.find({"_id": {"$in": ids}}, {"name": 1, "slug": 1, "onboarded": 1}).to_list(None)}
    wss = [{"id": w["_id"], "name": w["name"], "slug": w["slug"], "role": m["role"], "onboarded": w.get("onboarded", False)}
           for m in ms if (w := by_id.get(m["workspace_id"]))]
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
        _, sess = await current(request, response)
        await end_session(sess["_id"])
    except AppError:
        pass
    clear_cookies(response)
    return {"ok": True}


class StaffLogin(BaseModel):
    email: str
    password: str


STAFF_MAX_FAILURES = 10   # per network and per email, in the lock window


@router.post("/staff")
async def staff_login(body: StaffLogin, request: Request, response: Response):
    """Email + password sign-in for our own team (the Admin screen).

    Wrong passwords are counted per network and per email; after STAFF_MAX_FAILURES
    in 15 minutes, sign-in is refused until the window passes (brute-force guard)."""
    from app.db.indexes import STAFF_LOCK_WINDOW_S
    db = get_db()
    email = body.email.strip().lower()
    keys = [f"ip:{client_ip(request)}", f"email:{email}"]
    since = now() - timedelta(seconds=STAFF_LOCK_WINDOW_S)
    for k in keys:
        if await db.login_failures.count_documents({"key": k, "at": {"$gt": since}}) >= STAFF_MAX_FAILURES:
            raise AppError("rate_limited", "Too many wrong tries. Please wait 15 minutes and try again.", 429)
    ok = (settings.STAFF_EMAIL and settings.STAFF_PASSWORD
          and secrets_equal(email, settings.STAFF_EMAIL.lower())
          and secrets_equal(body.password, settings.STAFF_PASSWORD))
    if not ok:
        await db.login_failures.insert_many([{"_id": new_id(), "key": k, "at": now()} for k in keys])
        raise AppError("wrong_login", "That email or password is not right.", 401)
    await db.login_failures.delete_many({"key": {"$in": keys}})
    user = await db.users.find_one({"phone": "staff"})
    if not user:
        user = {"_id": new_id(), "phone": "staff", "name": "Staff", "staff": True, "is_admin": True, "created_at": now()}
        await db.users.insert_one(user)
    await start_session(response, user)
    return {"ok": True}
