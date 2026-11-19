"""The app: one FastAPI server for the consultant app, client pages and admin.

Screens call every business action through one route: POST /api/a/<action>.
The same functions are called by automations, agents and the MCP server.
"""
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

import actions.agent_actions  # noqa: F401  (register actions)
import actions.approvals  # noqa: F401
import actions.automations  # noqa: F401
import actions.crm  # noqa: F401
import actions.files  # noqa: F401
import actions.forms  # noqa: F401
import actions.inbox  # noqa: F401
import actions.money  # noqa: F401
import actions.reports  # noqa: F401
import actions.scheduling  # noqa: F401
import actions.workspace  # noqa: F401
import actions.rates  # noqa: F401  (add-ons)
import actions.timebill  # noqa: F401
import actions.budgets  # noqa: F401
import actions.retainers  # noqa: F401
import actions.estimates  # noqa: F401
import actions.insight  # noqa: F401
import actions.client_tasks  # noqa: F401
import vendors
from actions.registry import ACTIONS, P, action, call, registry_table
from admin import router as admin_router
from auth import get_ctx, router as auth_router, start_session
from core import settings
from core.db import ensure_indexes, get_db
from core.util import AppError, clean, new_id, now, token
from mcp import router as mcp_router
from public import hooks as hooks_router, router as public_router

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")


@asynccontextmanager
async def lifespan(app):
    await ensure_indexes()
    from migrations import backfill_time_entries
    await backfill_time_entries(get_db())   # add-on migration: safe to repeat
    if settings.QA_MODE and os.getenv("QA_SEED", "true") == "true":
        from seed import seed
        await seed()
    sched = None
    if settings.RUN_JOBS:
        from jobs import start_scheduler
        sched = start_scheduler()
    yield
    if sched:
        sched.shutdown(wait=False)


if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.05, send_default_pii=False)
    except ImportError:
        print("SENTRY_DSN is set but sentry-sdk isn't installed. Errors will only be logged.")

app = FastAPI(title=settings.BRAND_NAME, lifespan=lifespan, docs_url="/api/docs" if settings.QA_MODE else None, redoc_url=None)


@app.exception_handler(AppError)
async def app_error(request: Request, e: AppError):
    return JSONResponse({"error": {"code": e.code, "message": e.message, **({"extra": e.extra} if e.extra else {})}}, status_code=e.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, e: RequestValidationError):
    return JSONResponse({"error": {"code": "invalid", "message": "Some details are missing or not valid. Please check and try again."}}, status_code=400)


@app.exception_handler(Exception)
async def crash(request: Request, e: Exception):
    traceback.print_exc()
    return JSONResponse({"error": {"code": "server", "message": "Something went wrong on our side. Please try again."}}, status_code=500)


@app.get("/api/health")
async def health():
    return {"ok": True, "brand": settings.BRAND_NAME, "qa": settings.QA_MODE}


@app.post("/api/a/{name}")
async def run_action(name: str, request: Request, ctx=Depends(get_ctx)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await call(ctx, name, body if isinstance(body, dict) else {})


@app.get("/api/registry")
async def registry(ctx=Depends(get_ctx)):
    return registry_table()


# ---------------- uploads (consultant side) ----------------

@app.post("/api/upload")
async def upload(body: dict, ctx=Depends(get_ctx)):
    from public import data_url_to_key
    if ctx.read_only:
        raise AppError("read_only", "Your access is paused, so you can view but not change anything.", 403)
    key = await data_url_to_key(ctx.ws_id, body.get("data"), (body.get("name") or "file")[:40].replace("/", "-"))
    doc = {"key": key, "name": (body.get("name") or "File")[:120], "kind": body.get("kind", "file"), "project_id": body.get("project_id"),
           "client_visible": bool(body.get("client_visible")), "token": token(18), "by_client": False}
    up = await ctx.data.uploads.insert(doc)
    if body.get("kind") == "logo":
        await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": {"theme.logo_key": key}})
    return {"id": up["_id"], "key": key}


@app.get("/api/uploads/{uid}")
async def upload_get(uid: str, ctx=Depends(get_ctx)):
    up = await ctx.data.uploads.get(uid)
    if not up:
        raise AppError("not_found", "That file was not found.", 404)
    if up.get("project_id"):
        from actions import perm
        await perm.project(ctx, up["project_id"])
    return FileResponse(vendors.storage_path(up["key"]), filename=up["name"])


class UploadsIn(P):
    project_id: str


@action("uploads.list", "read", UploadsIn, desc="Files on a project: uploads, signed contracts, client uploads.")
async def uploads_list(ctx, p: UploadsIn):
    from actions import perm
    await perm.project(ctx, p.project_id)
    return clean(await ctx.data.uploads.find({"project_id": p.project_id}, sort=[("created_at", -1)]))


@app.get("/api/preview/f/{file_id}")
async def preview_file(file_id: str, ctx=Depends(get_ctx)):
    """"Preview as client": the working copy, exactly as the client page renders it."""
    from actions.files import get_file
    from public import render_file
    f = await get_file(ctx, file_id)
    return await render_file(ctx, f, preview_pages=f["pages"])


# ---------------- connected accounts (Gmail, Outlook, Zoom) ----------------

@app.get("/api/connect/{provider}/start")
async def connect_start(provider: str, ctx=Depends(get_ctx)):
    if provider not in vendors.OAUTH:
        raise AppError("not_found", "Unknown account type.", 404)
    state = token(16)
    await get_db().otp_codes.insert_one({"_id": new_id(), "phone": f"oauth:{state}", "ws": ctx.ws_id, "user": ctx.user_id, "provider": provider,
                                         "created_at": now(), "expires_at": now(), "used": False, "code_hash": ""})
    redirect = f"{settings.APP_URL}/api/connect/{provider}/callback"
    if vendors.mode(provider) == "fake":
        return {"url": f"{redirect}?code=fake&state={state}"}
    return {"url": vendors.oauth_url(provider, state, redirect)}


@app.get("/api/connect/{provider}/callback")
async def connect_callback(provider: str, code: str, state: str):
    db = get_db()
    st = await db.otp_codes.find_one({"phone": f"oauth:{state}", "used": False})
    if not st:
        return RedirectResponse("/settings?connect=failed")
    await db.otp_codes.update_one({"_id": st["_id"]}, {"$set": {"used": True}})
    tok = await vendors.oauth_exchange(provider, code, f"{settings.APP_URL}/api/connect/{provider}/callback")
    await db.connections.delete_many({"workspace_id": st["ws"], "user_id": st["user"], "provider": provider})
    await db.connections.insert_one({"_id": new_id(), "workspace_id": st["ws"], "user_id": st["user"], "provider": provider,
                                     "account": tok.get("account"), "tokens": vendors.encrypt(tok), "lead_finder": provider != "zoom",
                                     "created_at": now(), "deleted_at": None})
    return RedirectResponse(f"/settings?connected={provider}")


@action("connections.list", "read", agent_ok=False, desc="Connected accounts.")
async def connections_list(ctx, p):
    return [{"id": c["_id"], "provider": c["provider"], "account": c.get("account"), "lead_finder": c.get("lead_finder", False),
             "mine": c["user_id"] == ctx.user_id} for c in await ctx.data.connections.find({})]


class ConnIn(P):
    id: str
    lead_finder: bool = None


@action("connections.update", "internal", ConnIn, agent_ok=False, desc="Turn the inbox lead finder on or off for a connected inbox.")
async def connections_update(ctx, p: ConnIn):
    await ctx.data.connections.update({"_id": p.id, "user_id": ctx.user_id}, {"lead_finder": bool(p.lead_finder)})
    return await connections_list(ctx, None)


@action("connections.disconnect", "destructive", ConnIn, agent_ok=False, desc="Disconnect an account.")
async def connections_disconnect(ctx, p: ConnIn):
    await ctx.data.connections.hard_delete({"_id": p.id, "user_id": ctx.user_id})
    return await connections_list(ctx, None)


# ---------------- QA mode only ----------------

if settings.QA_MODE:
    @app.post("/api/qa/login")
    async def qa_login(body: dict, response: Response):
        from seed import PERSONAS
        phone = PERSONAS.get(body.get("persona", "owner"))
        if not phone:
            raise AppError("invalid", "Unknown persona.", 400)
        from auth import default_workspace, login_phone
        user = await login_phone(phone)
        await start_session(response, user, await default_workspace(user))
        return {"ok": True, "persona": body.get("persona", "owner")}

    @app.get("/api/qa/outbox")
    async def qa_outbox(limit: int = 30):
        rows = await get_db().vendor_log.find({}).sort("at", -1).to_list(limit)
        return clean(rows)

    @app.post("/api/qa/clock")
    async def qa_clock(body: dict):
        from core.util import advance_clock
        advance_clock(minutes=int(body.get("minutes", 0)))
        return {"now": now().isoformat()}

    @app.post("/api/qa/run_jobs")
    async def qa_jobs():
        from jobs import JOBS, run_job
        out = {}
        for _ in range(2):
            for n in JOBS:
                out[n] = await run_job(n, force=True)
        return out


app.include_router(auth_router)
app.include_router(public_router)
app.include_router(hooks_router)
app.include_router(admin_router)
app.include_router(mcp_router)
from oauth import router as oauth_router  # noqa: E402
app.include_router(oauth_router)


@app.get("/api/exports/{eid}")
async def export_download(eid: str, ctx=Depends(get_ctx)):
    """A ZIP the consultant asked for (bulk invoice download). Only for its own practice, for 7 days."""
    from fastapi.responses import Response as RawResponse
    ex = await ctx.data.exports.get(eid)
    if not ex or ex["status"] != "ready":
        raise AppError("not_found", "That download isn't ready or has expired.", 404)
    from core.util import aware
    if ex.get("expires_at") and aware(ex["expires_at"]) < now():
        raise AppError("not_found", "That download has expired. Make it again from Payments.", 404)
    return RawResponse(vendors.storage_get(ex["key"]), media_type="application/zip",
                       headers={"Content-Disposition": f"attachment; filename=\"{ex['key'].split('-', 1)[-1]}\""})


# ---------------- client domains ----------------

RESERVED_SUBDOMAINS = {"app", "www", "api", "admin", "mail", "reply", "static", "assets"}


async def slug_for_host(host: str):
    """<slug>.<CLIENT_DOMAIN> or a custom domain mapped in Admin -> the practice slug."""
    from urllib.parse import urlparse
    host = (host or "").split(":")[0].lower()
    if not host or host == (urlparse(settings.APP_URL).hostname or "").lower():
        return None   # the consultant app itself
    if settings.CLIENT_DOMAIN and host.endswith("." + settings.CLIENT_DOMAIN):
        sub = host[: -len(settings.CLIENT_DOMAIN) - 1]
        if sub in RESERVED_SUBDOMAINS or "." in sub:
            return None
        ws = await get_db().workspaces.find_one({"slug": sub}, {"_id": 1})
        return sub if ws else None
    d = await get_db().domains.find_one({"host": host})
    if d:
        ws = await get_db().workspaces.find_one({"_id": d["workspace_id"]}, {"slug": 1})
        return (ws or {}).get("slug")
    return None


@app.get("/api/public/domain-check")
async def domain_check(domain: str):
    """For the TLS proxy's on-demand certificates: 200 only for domains we serve."""
    if await slug_for_host(domain):
        return {"ok": True}
    raise AppError("not_found", "Unknown domain.", 404)


# ---------------- frontend (served last) ----------------

@app.get("/{path:path}")
async def spa(path: str, request: Request):
    if path.startswith("api/"):
        raise AppError("not_found", "Not found.", 404)
    f = os.path.join(FRONTEND, path)
    if path and os.path.isfile(f):
        return FileResponse(f)
    host_slug = await slug_for_host(request.headers.get("host", ""))
    # Client-facing pages (/c/<practice>/... or a practice domain) use the small client bundle.
    page = "client.html" if path.startswith("c/") or host_slug else "index.html"
    idx = os.path.join(FRONTEND, page)
    if os.path.isfile(idx):
        if host_slug:
            html = open(idx).read().replace("<head>", f"<head><script>window.__SLUG__={host_slug!r}</script>", 1)
            return HTMLResponse(html)
        return FileResponse(idx)
    return HTMLResponse(f"<h1>{settings.BRAND_NAME}</h1><p>The frontend isn't built yet. Run <code>npm run build</code> in frontend/.</p>")


_ = ACTIONS
