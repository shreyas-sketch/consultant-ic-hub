"""The one route the screens use for business logic: POST /api/a/<action>.

The same registry is used by automations, agents and the MCP connector, so the
role, read-only and money/cost rules are enforced in exactly one place.
"""
from fastapi import APIRouter, Depends, Request

from app.api.deps import get_ctx
from app.core.util import AppError
from app.domain.registry import call, registry_table

router = APIRouter(prefix="/api", tags=["actions"])

MAX_BODY = 12 * 1024 * 1024  # uploads arrive as data URLs (8 MB file ≈ 11 MB base64)


@router.post("/a/{name}")
async def run_action(name: str, request: Request, ctx=Depends(get_ctx)):
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        raise AppError("too_big", "That request is too large.", 413)
    try:
        body = await request.json()
    except Exception:
        body = {}
    request.state.action = name
    return await call(ctx, name, body if isinstance(body, dict) else {})


@router.get("/registry")
async def registry(ctx=Depends(get_ctx)):
    return registry_table()
