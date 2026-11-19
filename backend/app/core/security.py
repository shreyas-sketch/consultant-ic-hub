"""Small security primitives shared across the app."""
import base64
import hashlib
import hmac
import json


def hash_secret(s: str) -> str:
    """SHA-256 of a high-entropy secret (OTP, refresh token, link token). Not for passwords."""
    return hashlib.sha256(s.encode()).hexdigest()


def secrets_equal(a: str, b: str) -> bool:
    """Constant-time comparison for secrets."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def _fernet():
    from cryptography.fernet import Fernet

    from app.core import settings
    key = settings.TOKEN_KEY or base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt(obj) -> str:
    """Encrypt a JSON-able object (connected-account tokens)."""
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt(s: str):
    return json.loads(_fernet().decrypt(s.encode()).decode())
