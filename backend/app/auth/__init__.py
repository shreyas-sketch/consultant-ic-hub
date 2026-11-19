"""Authentication: invite-only phone login (OTP), sessions and accounts.

This package is the auth *service*. HTTP routes live in app/api/routes/auth.py
and request dependencies in app/api/deps.py. Domain code may import from here;
it must never import from app.api.
"""
from app.auth.accounts import NOT_INVITED, default_workspace, is_invited, login_phone, public_user
from app.auth.otp import check_otp, issue_otp, norm_phone
from app.auth.sessions import (ACCESS_SECONDS, REFRESH_DAYS, clear_cookies, current, current_user,
                               current_user_or_none, end_session, revoke_sessions, start_session)

__all__ = [
    "NOT_INVITED", "default_workspace", "is_invited", "login_phone", "public_user",
    "check_otp", "issue_otp", "norm_phone",
    "ACCESS_SECONDS", "REFRESH_DAYS", "clear_cookies", "current", "current_user", "current_user_or_none",
    "end_session", "revoke_sessions", "start_session",
]
