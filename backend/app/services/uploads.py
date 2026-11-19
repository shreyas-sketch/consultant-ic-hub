"""Turning uploaded data URLs into stored files (consultant and client uploads)."""
import base64
import binascii
import re

from app.core.util import AppError

MAX_BYTES = 8 * 1024 * 1024
ALLOWED = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf"}
_EXT_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "svg": "image/svg+xml",
             "pdf": "application/pdf", "zip": "application/zip"}
_DATA_URL = re.compile(r"^data:([\w/+.-]+);base64,(.+)$", re.S)


def mime_of(key: str, default="application/octet-stream") -> str:
    return _EXT_MIME.get((key or "").rsplit(".", 1)[-1].lower(), default)


def _sniff(raw: bytes) -> str | None:
    """Check the bytes, not just the declared type, so a script can't pose as an image."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    return None


async def data_url_to_key(ws_id, data_url, name):
    if not data_url:
        return None
    m = _DATA_URL.match(data_url)
    if not m:
        raise AppError("invalid", "That file couldn't be read.", 400)
    # Base64 is 4/3 the size: refuse obviously huge bodies before decoding them.
    if len(m.group(2)) > MAX_BYTES * 4 // 3 + 16:
        raise AppError("too_big", "Files can be up to 8 MB.", 400)
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError):
        raise AppError("invalid", "That file couldn't be read.", 400)
    if len(raw) > MAX_BYTES:
        raise AppError("too_big", "Files can be up to 8 MB.", 400)
    declared = m.group(1)
    if declared not in ALLOWED or _sniff(raw) != declared:
        raise AppError("invalid", "Please upload an image or a PDF.", 400)
    from app.integrations import vendors
    return await vendors.storage_put(ws_id, f"{name}.{ALLOWED[declared]}", raw, declared)
