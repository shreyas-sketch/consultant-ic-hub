"""Serves the built screens and the client-domain check. Mounted last.

- Hashed assets under /assets are cached for a year (immutable); HTML is never cached.
- Paths are resolved and confined to the build folder (no `..` escapes).
- Client pages (/c/<practice>/..., a practice subdomain, or a custom domain) get the small client bundle.
"""
import os
from functools import lru_cache

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.core import settings
from app.core.util import AppError
from app.services.domains import slug_for_host

FRONTEND = os.path.realpath(os.getenv("FRONTEND_DIST") or os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "frontend", "dist"))

router = APIRouter(tags=["frontend"])
NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@router.get("/api/public/domain-check")
async def domain_check(domain: str):
    """For a TLS proxy's on-demand certificates: 200 only for domains we serve."""
    if await slug_for_host(domain):
        return {"ok": True}
    raise AppError("not_found", "Unknown domain.", 404)


def _inside_build(path: str):
    full = os.path.realpath(os.path.join(FRONTEND, path))
    if full != FRONTEND and not full.startswith(FRONTEND + os.sep):
        return None
    return full if os.path.isfile(full) else None


@lru_cache(maxsize=4)
def _html(page: str, mtime: float) -> str:
    with open(os.path.join(FRONTEND, page), encoding="utf-8") as f:
        return f.read()


@router.get("/{path:path}", include_in_schema=False)
async def spa(path: str, request: Request):
    if path.startswith(("api/", "mcp")):
        raise AppError("not_found", "Not found.", 404)
    f = _inside_build(path) if path else None
    if f:
        headers = IMMUTABLE if path.startswith("assets/") else NO_CACHE if path.endswith(".html") else {"Cache-Control": "public, max-age=3600"}
        return FileResponse(f, headers=headers)
    host_slug = await slug_for_host(request.headers.get("host", ""))
    page = "client.html" if path.startswith("c/") or host_slug else "index.html"
    idx = os.path.join(FRONTEND, page)
    if not os.path.isfile(idx):
        return HTMLResponse(f"<h1>{settings.BRAND_NAME}</h1><p>The frontend isn't built yet. Run <code>npm run build</code> in frontend/.</p>",
                            status_code=503)
    html = _html(page, os.path.getmtime(idx))
    if host_slug:
        html = html.replace("<head>", f"<head><script>window.__SLUG__={host_slug!r}</script>", 1)
    return HTMLResponse(html, headers=NO_CACHE)
