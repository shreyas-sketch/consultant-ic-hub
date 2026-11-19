"""Liveness and readiness probes (Railway healthcheck uses /api/health/ready)."""
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import __version__
from app.core import settings
from app.db import ping

router = APIRouter(prefix="/api", tags=["system"])
_started = time.time()


@router.get("/health")
async def health():
    """Liveness: the process is up. Never touches the database."""
    return {"ok": True, "brand": settings.BRAND_NAME, "qa": settings.QA_MODE, "version": __version__,
            "uptime_s": round(time.time() - _started)}


@router.get("/health/ready")
async def ready():
    """Readiness: the database answers. Railway waits for this before routing traffic."""
    try:
        ms = await ping()
    except Exception as e:  # pragma: no cover - depends on the network
        return JSONResponse({"ok": False, "db": "down", "error": type(e).__name__}, status_code=503)
    return {"ok": True, "db": "up", "db_ms": ms, "version": __version__}
