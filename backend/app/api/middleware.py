"""HTTP middleware: request id + access log, and security headers.

Written as pure ASGI middleware (not BaseHTTPMiddleware) so streaming responses
and background tasks are not buffered and the event loop isn't blocked.
"""
import logging
import time

from app.core.logging import log_fields, request_id_var
from app.core.util import new_id

log = logging.getLogger("app.http")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class RequestContextMiddleware:
    """Gives every request an id (honours an incoming X-Request-ID), returns it,
    and writes one access-log line with status and duration."""

    def __init__(self, app, https: bool):
        self.app = app
        self.https = https

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode()[:64]
        rid = incoming if incoming and incoming.replace("-", "").isalnum() else new_id()
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
                headers = list(msg.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", rid.encode()))
                for k, v in SECURITY_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if self.https:
                    headers.append(HSTS)
                msg["headers"] = headers
            await send(msg)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if not path.startswith(("/assets/", "/api/health")):
                state = scope.get("state") or {}
                log_fields(log, logging.INFO, "request", method=scope.get("method"), path=path, status=status["code"],
                           ms=round((time.perf_counter() - t0) * 1000, 1), action=state.get("action"),
                           ws=state.get("workspace_id"))
            request_id_var.reset(token)
