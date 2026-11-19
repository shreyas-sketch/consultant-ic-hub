"""MCP server: the same action registry, offered to outside assistants (Claude,
ChatGPT...). JSON-RPC over HTTP POST at /mcp.

Two ways in:
- OAuth sign-in (oauth.py): the assistant opens our login, the consultant picks
  a practice and what to allow (read only / read + drafts / full).
- Connector tokens made in Settings (older clients, still supported).

The person's role is checked on every call, and results go through the same
money and cost filter as the screens. External and money actions land in
Approvals unless the practice allows otherwise. Destructive actions are never
offered. Speaks the stateless 2026-07-28 revision (server/discover, _meta) and
the older initialize handshake.
"""
import hashlib
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.domain.workspace.approvals import create_approval
from app.domain.registry import ACTIONS, by_tool_name, call, tool_schema
from app.agents.runtime import preview_for
from app.core import limits, settings
from app.core.context import Ctx
from app.db import get_db
from app.core.util import AppError, clean, now

router = APIRouter()
MODERN = "2026-07-28"
LEGACY = ["2025-11-25", "2025-06-18"]
LEVELS = {"read": {"read"}, "drafts": {"read", "internal"}, "full": {"read", "internal", "external", "money"}}
NEED = {"read": "read", "internal": "drafts", "external": "full", "money": "full"}


async def token_ctx(request: Request):
    from app.domain.perm import hide_money_for
    from app.api.routes.oauth import access_ctx
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AppError("logged_out", "Sign in to use this connector.", 401)
    raw = auth[7:].strip()
    db = get_db()
    if raw.startswith("pos_at_"):
        t = await access_ctx(raw)
        ws_id, user_id, scope, name = t["workspace_id"], t["user_id"], t["scope"], t.get("client_name") or "assistant"
    else:
        t = await db.mcp_tokens.find_one({"token_hash": hashlib.sha256(raw.encode()).hexdigest(), "deleted_at": None})
        if not t:
            raise AppError("invalid_token", "That connector token isn't valid.", 401)
        ws_id, user_id, scope, name = t["workspace_id"], t["user_id"], t["scope"], t["name"]
        await db.mcp_tokens.update_one({"_id": t["_id"]}, {"$set": {"last_used": now()}})
    if not await limits.value(ws_id, "mcp_connector"):
        raise AppError("locked", "The connector is switched off for this account.", 403)
    m = await db.memberships.find_one({"workspace_id": ws_id, "user_id": user_id, "active": True})
    if not m:
        raise AppError("invalid_token", "The person who connected this is no longer on the team.", 401)
    ws = await db.workspaces.find_one({"_id": ws_id})
    user = await db.users.find_one({"_id": user_id}) or {}
    ctx = Ctx(ws_id=ws_id, user_id=user_id, role=m["role"], actor=f"mcp:{name}", via="mcp", project_ids=m.get("project_ids", []),
              read_only=bool(ws.get("read_only") or user.get("access_removed")), hide_money=hide_money_for(ws, m["role"]))
    return ctx, scope, ws


def offered(scope, role):
    lv = LEVELS[scope]
    return [a for a in ACTIONS.values() if a.agent_ok and a.level in lv and role in a.roles and not a.name.startswith(("approvals.", "mcp."))]


def for_role(role):
    return [a for a in ACTIONS.values() if a.agent_ok and a.level != "destructive" and role in a.roles
            and not a.name.startswith(("approvals.", "mcp."))]


def ok(rid, result, modern=False):
    if modern:
        result = dict(result, resultType="complete", _meta={**(result.get("_meta") or {}), "io.modelcontextprotocol/serverInfo": SERVER_INFO})
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def err(rid, code, msg):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}


SERVER_INFO = {"name": settings.BRAND_NAME, "version": "1.1"}
INSTRUCTIONS = "Tools act on one consulting practice. Sends and money actions wait for the consultant's approval."


def _challenge_headers(e: AppError):
    from app.api.routes.oauth import challenge
    if e.status == 401:
        return {"WWW-Authenticate": challenge("invalid_token" if e.code == "invalid_token" else None, "read")}
    return {}


@router.post("/mcp")
async def mcp(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(err(None, -32700, "Parse error"), status_code=400)
    rid = body.get("id") if isinstance(body, dict) else None
    hm = request.headers.get("mcp-method")
    if hm and isinstance(body, dict) and body.get("method") and hm != body["method"]:
        return JSONResponse(err(rid, -32020, "HeaderMismatch: Mcp-Method doesn't match the body."), status_code=400)
    try:
        ctx, scope, ws = await token_ctx(request)
    except AppError as e:
        return JSONResponse(err(rid, -32001, e.message), status_code=e.status, headers=_challenge_headers(e))
    if isinstance(body, list):
        out = []
        for b in body:
            if "id" in b:
                r = await handle(ctx, scope, ws, b, request)
                out.append(r if not isinstance(r, JSONResponse) else json.loads(r.body))
        return JSONResponse(out)
    if "id" not in body:  # notification
        return Response(status_code=202)
    r = await handle(ctx, scope, ws, body, request)
    return r if isinstance(r, JSONResponse) else JSONResponse(r)


async def handle(ctx, scope, ws, msg, request=None):
    rid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    meta_v = ((params.get("_meta") or {}).get("io.modelcontextprotocol/protocolVersion")
              or (request.headers.get("mcp-protocol-version") if request is not None else None))
    modern = meta_v == MODERN
    if method == "server/discover":
        return ok(rid, {"supportedVersions": [MODERN] + LEGACY, "capabilities": {"tools": {"listChanged": False}},
                        "instructions": INSTRUCTIONS, "ttlMs": 300000, "cacheScope": "user"}, True)
    if method == "initialize":
        want = params.get("protocolVersion")
        return ok(rid, {"protocolVersion": want if want in LEGACY else LEGACY[0], "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok(rid, {}, modern)
    if method == "tools/list":
        tools = []
        for a in offered(scope, ctx.role):
            s = tool_schema(a)
            tools.append({"name": s["name"], "description": s["description"], "inputSchema": s["input_schema"]})
        return ok(rid, {"tools": tools}, modern)
    if method == "tools/call":
        a = by_tool_name(params.get("name", ""))
        if a and a in for_role(ctx.role) and a not in offered(scope, ctx.role):
            # The person may do this, but the assistant was only allowed less: ask it to step up (spec: 403 insufficient_scope).
            from app.api.routes.oauth import challenge
            need = NEED[a.level]
            return JSONResponse(err(rid, -32003, f"This needs the '{need}' permission. Reconnect and allow more."), status_code=403,
                                headers={"WWW-Authenticate": challenge("insufficient_scope", need, "More permission needed for this tool")})
        if not a or a not in offered(scope, ctx.role):
            return ok(rid, {"content": [{"type": "text", "text": "That tool isn't available with this connector."}], "isError": True}, modern)
        args = params.get("arguments") or {}
        try:
            if a.level in ("external", "money") and not (scope == "full" and ws.get("settings", {}).get("mcp_auto_external")):
                ap = await create_approval(ctx, a.name, args, preview_for(a.name, args), "Requested by an outside assistant",
                                           project_id=args.get("project_id"), source="mcp", agent=None)
                out = {"queued_for_approval": ap["_id"], "note": "The consultant will approve this in the app before it goes out."}
            else:
                out = await call(ctx, a.name, args)
            text = json.dumps(clean(out) if isinstance(out, dict) else out, default=str)[:50000]
            return ok(rid, {"content": [{"type": "text", "text": text}], "isError": False}, modern)
        except AppError as e:
            return ok(rid, {"content": [{"type": "text", "text": e.message}], "isError": True}, modern)
    return err(rid, -32601, "Method not found")
