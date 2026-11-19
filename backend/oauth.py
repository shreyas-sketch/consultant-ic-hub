"""MCP sign-in (add-on 4.11): OAuth 2.1 authorisation code + PKCE, built to the
MCP authorization spec revision 2026-07-28 (checked 13 Nov 2026).

- Protected Resource Metadata (RFC 9728) at /.well-known/oauth-protected-resource[/mcp]
- Authorization Server Metadata (RFC 8414) at /.well-known/oauth-authorization-server
- Client registration: Client ID Metadata Documents (the client_id is an https URL
  we fetch and check) — the spec's preferred way — and Dynamic Client Registration
  (RFC 7591), which the spec keeps for older clients but marks deprecated.
- PKCE S256 only. `resource` (RFC 8707) binds every token to our MCP endpoint.
- `iss` in every authorization response (RFC 9207).
- Access tokens last 15 minutes; refresh tokens rotate, and reusing an old one
  revokes the whole chain.
- The token carries the person, the practice and the consent they chose
  (read / read + drafts / full). Their role is read fresh on every call.
The old connector tokens from Settings keep working.
"""
import base64
import hashlib
import ipaddress
import json
import socket
import time
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core import settings
from core.db import get_db
from core.util import AppError, aware, new_id, now, token

router = APIRouter()
SCOPES = ["read", "drafts", "full"]
RANK = {"read": 1, "drafts": 2, "full": 3}
ACCESS_SECONDS = 15 * 60
REFRESH_DAYS = 30
CODE_SECONDS = 300


def issuer():
    return settings.APP_URL.rstrip("/")


def resource_uri():
    return issuer() + "/mcp"


def prm_url():
    return issuer() + "/.well-known/oauth-protected-resource/mcp"


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def same_resource(a, b) -> bool:
    pa, pb = urlparse((a or "").rstrip("/")), urlparse((b or "").rstrip("/"))
    return (pa.scheme.lower(), pa.netloc.lower(), pa.path or "") == (pb.scheme.lower(), pb.netloc.lower(), pb.path or "")


def challenge(error=None, scope="read", desc=None):
    parts = [f'resource_metadata="{prm_url()}"', f'scope="{scope}"']
    if error:
        parts.insert(0, f'error="{error}"')
    if desc:
        parts.append(f'error_description="{desc}"')
    return "Bearer " + ", ".join(parts)


# ---------------- discovery ----------------

def _prm():
    return {"resource": resource_uri(), "authorization_servers": [issuer()], "scopes_supported": SCOPES,
            "bearer_methods_supported": ["header"], "resource_name": settings.BRAND_NAME}


@router.get("/.well-known/oauth-protected-resource")
async def prm_root():
    return _prm()


@router.get("/.well-known/oauth-protected-resource/mcp")
async def prm_mcp():
    return _prm()


@router.get("/.well-known/oauth-authorization-server")
async def as_metadata():
    i = issuer()
    return {"issuer": i, "authorization_endpoint": f"{i}/oauth/authorize", "token_endpoint": f"{i}/oauth/token",
            "registration_endpoint": f"{i}/oauth/register", "revocation_endpoint": f"{i}/oauth/revoke",
            "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": SCOPES, "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True, "service_documentation": f"{i}/settings/connector"}


# ---------------- clients ----------------

def _public_host(host: str) -> bool:
    """No fetching from our own network (SSRF): the host must resolve only to public addresses."""
    if not host or host in ("localhost",) or host.endswith((".local", ".internal")):
        return False
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


async def fetch_cimd(client_id: str):
    """Client ID Metadata Document: fetch, check it names itself, cache it."""
    db = get_db()
    cached = await db.oauth_clients.find_one({"client_id": client_id, "kind": "cimd"})
    if cached and cached.get("cache_until") and aware(cached["cache_until"]) > now():
        return cached
    u = urlparse(client_id)
    if u.scheme != "https" or not u.path or u.path == "/" or u.fragment or u.username:
        raise AppError("invalid_client", "The client_id must be an https URL with a path.", 400)
    if settings.QA_MODE and u.hostname and u.hostname.endswith(".test"):
        doc = (settings.QA_CIMD or {}).get(client_id)   # tests supply documents; QA never goes to the network
        if doc is None:
            raise AppError("invalid_client", "We couldn't fetch that client's metadata document.", 400)
        max_age = 3600
    else:
        if not _public_host(u.hostname or ""):
            raise AppError("invalid_client", "That client's metadata document isn't on a public address.", 400)
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:
                r = await c.get(client_id, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise AppError("invalid_client", "We couldn't fetch that client's metadata document.", 400)
        if r.status_code != 200 or len(r.content) > 64 * 1024:
            raise AppError("invalid_client", "That client's metadata document couldn't be used.", 400)
        try:
            doc = r.json()
        except ValueError:
            raise AppError("invalid_client", "That client's metadata document isn't valid JSON.", 400)
        cc = r.headers.get("cache-control", "")
        max_age = next((int(x.split("=")[1]) for x in cc.split(",") if x.strip().startswith("max-age=") and x.split("=")[1].isdigit()), 3600)
    if not isinstance(doc, dict) or doc.get("client_id") != client_id:
        raise AppError("invalid_client", "The metadata document's client_id doesn't match its URL.", 400)
    if not doc.get("client_name") or not isinstance(doc.get("redirect_uris"), list) or not doc["redirect_uris"]:
        raise AppError("invalid_client", "The metadata document needs client_name and redirect_uris.", 400)
    if doc.get("token_endpoint_auth_method", "none") != "none":
        raise AppError("invalid_client", "Only public clients (no client secret) are supported.", 400)
    rec = {"client_id": client_id, "kind": "cimd", "client_name": str(doc["client_name"])[:120],
           "redirect_uris": [str(x) for x in doc["redirect_uris"]][:20], "client_uri": doc.get("client_uri"),
           "cache_until": now() + timedelta(seconds=max(60, min(max_age, 86400)))}
    await db.oauth_clients.update_one({"client_id": client_id}, {"$set": rec, "$setOnInsert": {"_id": new_id(), "created_at": now()}}, upsert=True)
    return rec


async def client_for(client_id: str):
    if not client_id:
        raise AppError("invalid_client", "client_id is missing.", 400)
    if client_id.startswith("https://"):
        return await fetch_cimd(client_id)
    c = await get_db().oauth_clients.find_one({"client_id": client_id, "kind": "dcr"})
    if not c:
        raise AppError("invalid_client", "Unknown client.", 400)
    return c


def _redirect_ok(uri, allowed) -> bool:
    if uri not in allowed:
        return False
    p = urlparse(uri)
    return p.scheme == "https" or (p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "[::1]", "::1")) or \
        (p.scheme not in ("http", "https", "javascript", "data", "file") and bool(p.scheme))


@router.post("/oauth/register")
async def register(request: Request):
    """Dynamic Client Registration (RFC 7591). Deprecated in MCP 2026-07-28; kept for older clients."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_client_metadata", "error_description": "Body must be JSON."}, 400)
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
        return JSONResponse({"error": "invalid_redirect_uri", "error_description": "redirect_uris is required."}, 400)
    for u in uris:
        if not _redirect_ok(u, [u]):
            return JSONResponse({"error": "invalid_redirect_uri", "error_description": f"Not allowed: {u}"}, 400)
    if body.get("token_endpoint_auth_method", "none") != "none":
        return JSONResponse({"error": "invalid_client_metadata", "error_description": "Only public clients (no secret) are supported."}, 400)
    cid = "pos_c_" + token(16)
    rec = {"_id": new_id(), "client_id": cid, "kind": "dcr", "client_name": str(body.get("client_name") or "AI assistant")[:120],
           "redirect_uris": uris[:20], "created_at": now()}
    await get_db().oauth_clients.insert_one(rec)
    return JSONResponse({"client_id": cid, "client_id_issued_at": int(time.time()), "client_name": rec["client_name"],
                         "redirect_uris": rec["redirect_uris"], "grant_types": ["authorization_code", "refresh_token"],
                         "response_types": ["code"], "token_endpoint_auth_method": "none"}, 201)


# ---------------- authorize ----------------

def _err_redirect(redirect_uri, error, state, desc=None):
    q = {"error": error, "iss": issuer()}
    if state:
        q["state"] = state
    if desc:
        q["error_description"] = desc
    return RedirectResponse(redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(q), 302)


@router.get("/oauth/authorize")
async def authorize(request: Request):
    from auth import current_user_or_none
    q = request.query_params
    try:
        client = await client_for(q.get("client_id", ""))
    except AppError as e:
        return JSONResponse({"error": "invalid_client", "error_description": e.message}, 400)
    ru = q.get("redirect_uri", "")
    if not _redirect_ok(ru, client["redirect_uris"]):
        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri isn't registered for this client."}, 400)
    state = q.get("state")
    if q.get("response_type") != "code":
        return _err_redirect(ru, "unsupported_response_type", state)
    if not q.get("code_challenge") or q.get("code_challenge_method") != "S256":
        return _err_redirect(ru, "invalid_request", state, "PKCE with S256 is required.")
    if q.get("resource") and not same_resource(q["resource"], resource_uri()):
        return _err_redirect(ru, "invalid_target", state, "Unknown resource.")
    asked = [s for s in (q.get("scope") or "full").split() if s in RANK] or ["full"]
    rid = token(18)
    await get_db().oauth_requests.insert_one({"_id": rid, "client_id": client["client_id"], "client_name": client["client_name"],
                                              "redirect_uri": ru, "state": state, "code_challenge": q["code_challenge"],
                                              "scope": max(asked, key=lambda s: RANK[s]), "resource": resource_uri(),
                                              "expires_at": now() + timedelta(minutes=10), "created_at": now()})
    target = f"/oauth/consent?req={rid}"
    if not await current_user_or_none(request):
        return RedirectResponse("/login?" + urlencode({"next": target}), 302)
    return RedirectResponse(target, 302)


async def _pending(rid):
    r = await get_db().oauth_requests.find_one({"_id": rid})
    if not r or aware(r["expires_at"]) < now():
        raise AppError("expired", "This sign-in request has expired. Start again from your assistant.", 410)
    return r


def _user_dep():
    from auth import current_user
    return current_user


@router.get("/api/oauth/request/{rid}")
async def request_info(rid: str, user=Depends(_user_dep())):
    r = await _pending(rid)
    db = get_db()
    ms = await db.memberships.find({"user_id": user["_id"], "active": True}).to_list(None)
    wss = {w["_id"]: w for w in await db.workspaces.find({"_id": {"$in": [m["workspace_id"] for m in ms]}}).to_list(None)}
    return {"client_name": r["client_name"], "client_id": r["client_id"], "redirect_host": urlparse(r["redirect_uri"]).netloc or r["redirect_uri"],
            "verified_url": r["client_id"] if r["client_id"].startswith("https://") else None, "scope": r["scope"],
            "workspaces": [{"id": m["workspace_id"], "name": wss.get(m["workspace_id"], {}).get("name", ""), "role": m["role"]}
                           for m in ms if m["workspace_id"] in wss]}


@router.post("/api/oauth/consent")
async def consent(body: dict, user=Depends(_user_dep())):
    from core import limits
    r = await _pending(body.get("req", ""))
    db = get_db()
    await db.oauth_requests.delete_one({"_id": r["_id"]})
    if not body.get("approve"):
        q = {"error": "access_denied", "iss": issuer(), **({"state": r["state"]} if r.get("state") else {})}
        return {"redirect": r["redirect_uri"] + ("&" if "?" in r["redirect_uri"] else "?") + urlencode(q)}
    scope = body.get("scope") if body.get("scope") in RANK else r["scope"]
    if RANK[scope] > RANK[r["scope"]]:
        scope = r["scope"]
    m = await db.memberships.find_one({"user_id": user["_id"], "workspace_id": body.get("workspace_id"), "active": True})
    if not m:
        raise AppError("forbidden", "Choose a practice you're part of.", 403)
    if not await limits.value(m["workspace_id"], "mcp_connector"):
        raise AppError("locked", "The AI connector is switched off for this account.", 403)
    code = token(32)
    await db.oauth_codes.insert_one({"_id": new_id(), "code_hash": h(code), "client_id": r["client_id"], "redirect_uri": r["redirect_uri"],
                                     "code_challenge": r["code_challenge"], "resource": r["resource"], "scope": scope, "user_id": user["_id"],
                                     "workspace_id": m["workspace_id"], "client_name": r["client_name"], "used": False,
                                     "expires_at": now() + timedelta(seconds=CODE_SECONDS), "created_at": now()})
    q = {"code": code, "iss": issuer(), **({"state": r["state"]} if r.get("state") else {})}
    return {"redirect": r["redirect_uri"] + ("&" if "?" in r["redirect_uri"] else "?") + urlencode(q)}


# ---------------- tokens ----------------

def _token_error(error, desc, status=400):
    return JSONResponse({"error": error, "error_description": desc}, status, headers={"Cache-Control": "no-store"})


async def _issue(base: dict, family=None):
    db = get_db()
    access, refresh = "pos_at_" + token(32), "pos_rt_" + token(40)
    family = family or new_id()
    common = {k: base[k] for k in ("client_id", "user_id", "workspace_id", "scope", "resource", "client_name")}
    await db.oauth_tokens.insert_one({"_id": new_id(), "token_hash": h(access), "kind": "access", "family": family, "revoked": False,
                                      "expires_at": now() + timedelta(seconds=ACCESS_SECONDS), "created_at": now(), **common})
    await db.oauth_tokens.insert_one({"_id": new_id(), "token_hash": h(refresh), "kind": "refresh", "family": family, "revoked": False,
                                      "used": False, "expires_at": now() + timedelta(days=REFRESH_DAYS), "created_at": now(), **common})
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS, "refresh_token": refresh,
                         "scope": base["scope"]}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


async def revoke_family(family):
    await get_db().oauth_tokens.update_many({"family": family}, {"$set": {"revoked": True}})


@router.post("/oauth/token")
async def token_endpoint(grant_type: str = Form(...), code: str = Form(None), redirect_uri: str = Form(None), client_id: str = Form(None),
                         code_verifier: str = Form(None), refresh_token: str = Form(None), resource: str = Form(None)):
    db = get_db()
    if resource and not same_resource(resource, resource_uri()):
        return _token_error("invalid_target", "Unknown resource.")
    if grant_type == "authorization_code":
        if not (code and code_verifier and client_id and redirect_uri):
            return _token_error("invalid_request", "code, code_verifier, client_id and redirect_uri are required.")
        c = await db.oauth_codes.find_one_and_update({"code_hash": h(code), "used": False}, {"$set": {"used": True, "used_at": now()}})
        if not c:
            old = await db.oauth_codes.find_one({"code_hash": h(code)})
            if old and old.get("family"):
                await revoke_family(old["family"])   # a code used twice: everything it produced is revoked
            return _token_error("invalid_grant", "That code is invalid or was already used.")
        if aware(c["expires_at"]) < now() or c["client_id"] != client_id or c["redirect_uri"] != redirect_uri:
            return _token_error("invalid_grant", "That code doesn't match this request.")
        digest = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
        if digest != c["code_challenge"]:
            return _token_error("invalid_grant", "PKCE check failed.")
        family = new_id()
        await db.oauth_codes.update_one({"_id": c["_id"]}, {"$set": {"family": family}})
        return await _issue(c, family)
    if grant_type == "refresh_token":
        if not refresh_token:
            return _token_error("invalid_request", "refresh_token is required.")
        t = await db.oauth_tokens.find_one({"token_hash": h(refresh_token), "kind": "refresh"})
        if not t or t["revoked"]:
            return _token_error("invalid_grant", "That refresh token isn't valid.")
        if client_id and client_id != t["client_id"]:
            return _token_error("invalid_grant", "That refresh token belongs to another client.")
        got = await db.oauth_tokens.find_one_and_update({"_id": t["_id"], "used": False}, {"$set": {"used": True}})
        if not got:
            await revoke_family(t["family"])   # an old refresh token came back: assume it was stolen
            return _token_error("invalid_grant", "That refresh token was already used. Please sign in again.")
        if aware(t["expires_at"]) < now():
            return _token_error("invalid_grant", "That refresh token has expired. Please sign in again.")
        m = await db.memberships.find_one({"user_id": t["user_id"], "workspace_id": t["workspace_id"], "active": True})
        if not m:
            await revoke_family(t["family"])
            return _token_error("invalid_grant", "You're no longer on this practice's team.")
        await db.oauth_tokens.update_many({"family": t["family"], "kind": "access"}, {"$set": {"revoked": True}})
        return await _issue(t, t["family"])
    return _token_error("unsupported_grant_type", "Use authorization_code or refresh_token.")


@router.post("/oauth/revoke")
async def revoke(token_: str = Form(..., alias="token")):
    t = await get_db().oauth_tokens.find_one({"token_hash": h(token_)})
    if t:
        await revoke_family(t["family"])
    return JSONResponse({}, 200)


async def access_ctx(raw: str):
    """For /mcp: an OAuth access token -> (person, practice, consent). Audience must be our MCP endpoint."""
    t = await get_db().oauth_tokens.find_one({"token_hash": h(raw), "kind": "access"})
    if not t or t["revoked"]:
        raise AppError("invalid_token", "That access token isn't valid.", 401)
    if aware(t["expires_at"]) < now():
        raise AppError("invalid_token", "That access token has expired.", 401)
    if not same_resource(t["resource"], resource_uri()):
        raise AppError("invalid_token", "That token wasn't issued for this server.", 401)
    await get_db().oauth_tokens.update_one({"_id": t["_id"]}, {"$set": {"last_used": now()}})
    return t


_ = json
