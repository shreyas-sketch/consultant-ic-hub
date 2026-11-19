"""One-time codes: shared by consultant login, client signing and the client portal."""
import random
import re
from datetime import timedelta

from app.core import settings
from app.core.security import hash_secret, secrets_equal
from app.core.util import AppError, aware, new_id, now
from app.db import get_db

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=30)
MAX_TRIES = 5


def norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 11 or len(digits) > 15:
        raise AppError("invalid", "Please enter a valid mobile number.", 400)
    return "+" + digits


async def issue_otp(phone: str, ip: str) -> dict:
    """`phone` may be an email address for client codes.

    Rate-limit, store a hashed code and send it (WhatsApp first, SMS fallback).

    Callers check invitation / eligibility first; this only handles the code.
    """
    db = get_db()
    hour_ago = now() - timedelta(hours=1)
    if await db.otp_codes.count_documents({"ip": ip, "created_at": {"$gt": hour_ago}}) >= settings.OTP_PER_IP_PER_HOUR:
        raise AppError("rate_limited", "Too many codes from this network. Please try again in a while.", 429)
    last = await db.otp_codes.find_one({"phone": phone}, sort=[("created_at", -1)])
    if last and aware(last["created_at"]) > now() - RESEND_COOLDOWN:
        raise AppError("cooldown", "Please wait 30 seconds before asking for a new code.", 429)
    code = f"{random.SystemRandom().randint(0, 999999):06d}"
    await db.otp_codes.insert_one({"_id": new_id(), "phone": phone, "code_hash": hash_secret(code), "tries": 0, "ip": ip,
                                   "created_at": now(), "expires_at": now() + CODE_TTL, "used": False})
    from app.integrations import vendors
    if "@" in phone:  # client pages can send the code by email
        await vendors.email_send(None, phone, "Your code", f"<p>Your code is <b>{code}</b>. It expires in 10 minutes.</p>")
        channel = "email"
    else:
        channel = await vendors.otp_send(phone, code)
    out = {"ok": True, "channel": channel}
    if settings.QA_MODE:
        out["qa_code"] = code  # shown on screen in QA mode only
    return out


async def check_otp(phone, code) -> bool:
    db = get_db()
    if settings.QA_MODE and code == "000000":
        return True
    row = await db.otp_codes.find_one({"phone": phone, "used": False}, sort=[("created_at", -1)])
    if not row or aware(row["expires_at"]) < now():
        raise AppError("otp_expired", "That code has expired. Please ask for a new one.", 400)
    if row["tries"] >= MAX_TRIES:
        raise AppError("otp_locked", "Too many wrong tries. Please ask for a new code.", 429)
    if not secrets_equal(row["code_hash"], hash_secret((code or "").strip())):
        await db.otp_codes.update_one({"_id": row["_id"]}, {"$inc": {"tries": 1}})
        raise AppError("otp_wrong", "That code is not right. Please check and try again.", 400)
    # Claim the code atomically so two parallel verifies can't both succeed.
    claimed = await db.otp_codes.update_one({"_id": row["_id"], "used": False}, {"$set": {"used": True}})
    if not claimed.modified_count:
        raise AppError("otp_expired", "That code has already been used. Please ask for a new one.", 400)
    return True
