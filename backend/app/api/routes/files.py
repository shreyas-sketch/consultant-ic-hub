"""Consultant-side file endpoints: upload, download, preview-as-client, export ZIPs."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import get_ctx
from app.core.util import AppError, aware, now, token
from app.db import get_db
from app.domain import perm
from app.integrations import vendors
from app.services.uploads import data_url_to_key, mime_of

router = APIRouter(prefix="/api", tags=["files"])


def _attachment(name: str) -> str:
    safe = "".join(ch for ch in (name or "file") if ch not in '"\\\r\n')[:150]
    return f'attachment; filename="{safe}"'


@router.post("/upload")
async def upload(body: dict, ctx=Depends(get_ctx)):
    if ctx.read_only:
        raise AppError("read_only", "Your access is paused, so you can view but not change anything.", 403)
    if body.get("kind") == "logo" and ctx.role not in ("owner", "admin"):
        raise AppError("forbidden", "Only the Owner or an Admin can change the logo.", 403)
    if body.get("project_id"):
        await perm.project(ctx, body["project_id"], act=True)
    key = await data_url_to_key(ctx.ws_id, body.get("data"), (body.get("name") or "file")[:40])
    doc = {"key": key, "name": (body.get("name") or "File")[:120], "kind": body.get("kind", "file"), "project_id": body.get("project_id"),
           "client_visible": bool(body.get("client_visible")), "token": token(18), "by_client": False}
    up = await ctx.data.uploads.insert(doc)
    if body.get("kind") == "logo":
        await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": {"theme.logo_key": key}})
    return {"id": up["_id"], "key": key}


@router.get("/uploads/{uid}")
async def upload_get(uid: str, ctx=Depends(get_ctx)):
    up = await ctx.data.uploads.get(uid)
    if not up:
        raise AppError("not_found", "That file was not found.", 404)
    if up.get("project_id"):
        await perm.project(ctx, up["project_id"])
    try:
        data = await vendors.storage_get(up["key"])
    except FileNotFoundError:
        raise AppError("not_found", "That file was not found.", 404)
    return Response(data, media_type=mime_of(up["key"]), headers={"Content-Disposition": _attachment(up["name"])})


@router.get("/preview/f/{file_id}")
async def preview_file(file_id: str, ctx=Depends(get_ctx)):
    """"Preview as client": the working copy, exactly as the client page renders it."""
    from app.api.routes.public import render_file
    from app.domain.documents.files import get_file
    f = await get_file(ctx, file_id)
    return await render_file(ctx, f, preview_pages=f["pages"])


@router.get("/exports/{eid}")
async def export_download(eid: str, ctx=Depends(get_ctx)):
    """A ZIP the consultant asked for (bulk invoice download). Only for its own practice, for 7 days."""
    ex = await ctx.data.exports.get(eid)
    if not ex or ex["status"] != "ready":
        raise AppError("not_found", "That download isn't ready or has expired.", 404)
    if ex.get("expires_at") and aware(ex["expires_at"]) < now():
        raise AppError("not_found", "That download has expired. Make it again from Payments.", 404)
    return Response(await vendors.storage_get(ex["key"]), media_type="application/zip",
                    headers={"Content-Disposition": _attachment(ex["key"].split("-", 1)[-1])})
