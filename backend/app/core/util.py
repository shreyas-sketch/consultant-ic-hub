"""Small shared helpers: ids, errors, time (IST), money."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

_clock_offset = timedelta(0)


def now() -> datetime:
    """Current UTC time. Tests and automation test-runs can move the clock."""
    return datetime.now(UTC) + _clock_offset


def advance_clock(**kw):
    global _clock_offset
    _clock_offset += timedelta(**kw)


def reset_clock():
    global _clock_offset
    _clock_offset = timedelta(0)


def aware(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            raise AppError("invalid", "That date isn't valid. Please pick it again.", 400) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def new_id() -> str:
    return uuid.uuid4().hex


def token(n=24) -> str:
    return secrets.token_urlsafe(n)


def fy_of(dt: datetime) -> str:
    """Indian financial year (April–March) label, e.g. 2026-27."""
    d = aware(dt).astimezone(IST)
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def month_key(dt: datetime = None) -> str:
    return aware(dt or now()).astimezone(IST).strftime("%Y-%m")


def inr(paise: int) -> str:
    """Indian format: ₹1,00,000 (paise dropped when zero)."""
    neg = paise < 0
    paise = abs(int(paise))
    rupees, p = divmod(paise, 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    out = f"₹{s}" + (f".{p:02d}" if p else "")
    return ("-" if neg else "") + out


def fmt_date(dt) -> str:
    d = aware(dt).astimezone(IST)
    return f"{d.day} {d.strftime('%b %Y')}"


def fmt_dt(dt) -> str:
    d = aware(dt).astimezone(IST)
    return f"{d.day} {d.strftime('%b %Y')}, {d.strftime('%I:%M %p').lstrip('0')} IST"


class AppError(Exception):
    """An error with a plain message for the user and a stable code for the screen."""

    def __init__(self, code: str, message: str, status: int = 400, extra=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra or {}


def not_found(what="That item"):
    return AppError("not_found", f"{what} was not found.", 404)


def forbidden(msg="You don't have access to this."):
    return AppError("forbidden", msg, 403)


def clean(doc):
    """Database doc -> API shape (_id -> id, datetimes -> ISO)."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [clean(d) for d in doc]
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["id"] = v
        elif isinstance(v, datetime):
            out[k] = aware(v).isoformat()
        elif isinstance(v, dict):
            out[k] = clean(v)
        elif isinstance(v, list):
            out[k] = [clean(x) if isinstance(x, dict) else (aware(x).isoformat() if isinstance(x, datetime) else x) for x in v]
        else:
            out[k] = v
    return out
