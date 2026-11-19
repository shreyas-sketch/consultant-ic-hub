"""Workspace, team and roles, stages, saved views, notifications, MCP tokens."""
import hashlib
import re
from typing import Optional

from app.domain.documents import defaults
from app.domain.registry import ADMINS, ALL, OWNER, STAFF, P, action
from app.core import limits
from app.core.context import system_ctx
from app.db import get_db
from app.core.events import audit
from app.core.util import AppError, clean, forbidden, new_id, not_found, now, token

ROLES = ["owner", "admin", "manager", "member", "collaborator"]


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "practice").lower()).strip("-")
    return s[:30] or "practice"


async def unique_slug(base):
    db = get_db()
    reserved = {"app", "www", "api", "admin", "mail", "reply", "static", "assets"}
    slug, i = slugify(base), 1
    while slug in reserved or await db.workspaces.find_one({"slug": slug}):
        i += 1
        slug = f"{slugify(base)}-{i}"
    return slug


async def create_workspace(user, name="My practice"):
    """A new practice with its owner, default pipeline, templates, session type,
    starter automations and agent settings."""
    db = get_db()
    ws_id = new_id()
    ws = {"_id": ws_id, "name": name, "slug": await unique_slug(name), "owner_id": user["_id"], "created_at": now(),
          "onboarded": False, "read_only": False,
          "profile": {"practice_name": name, "consultant_name": user.get("name", ""), "phone": user["phone"],
                      "email": user.get("email", ""), "website": "", "address": "", "state": "Maharashtra", "tagline": ""},
          "theme": {"primary": "#C9A84C", "text": "#14151A", "paper": "#FAF8F3", "button_text": "#14151A",
                    "heading_font": "Manrope", "corners": "rounded", "logo_key": None, "logo_shape": "square",
                    "login_bg": "#FAF8F3", "portal_bg": "#FAF8F3", "sidebar": "#FFFFFF", "login_title": ""},
          "invoice": {"upi_id": "", "payee_name": name, "bank": {"account_name": "", "account_no": "", "ifsc": "", "bank_name": ""},
                      "gst_enabled": False, "gstin": "", "state": "Maharashtra", "tax_rate_bp": 1800, "prefix": "INV",
                      "terms": "Payment is made directly to the consultant by UPI or bank transfer.",
                      "late_fee": {"enabled": False, "pct_bp": 200}, "tds_expected": False, "reminders": [-3, 0, 3, 7]},
          "settings": {"lead_sources": defaults.LEAD_SOURCES, "project_types": defaults.PROJECT_TYPES,
                       "lost_reasons": defaults.LOST_REASONS, "custom_fields": [], "quiet_hours": {"start": 21, "end": 8},
                       "hide_money_roles": [], "revenue_goal_paise": 0, "sending_domain": "", "portal_link_default": True,
                       "timezone": "Asia/Kolkata", "notetaker_name": f"{name} notetaker"},
          "domains": [], "connections": {}}
    await db.workspaces.insert_one(ws)
    ctx = system_ctx(ws_id)
    await ctx.data.memberships.insert({"user_id": user["_id"], "role": "owner", "active": True, "project_ids": [],
                                       "phone": user["phone"], "name": user.get("name", "")})
    stage_ids = {}
    for i, (n, g, k) in enumerate(defaults.DEFAULT_STAGES):
        s = await ctx.data.stages.insert({"name": n, "group": g, "key": k, "order": i})
        stage_ids[k] = s["_id"]
    await db.workspaces.update_one({"_id": ws_id}, {"$set": {"settings.stage_rules": [
        dict(r, stage_id=stage_ids[r["stage_key"]]) for r in defaults.DEFAULT_STAGE_RULES]}})
    tpl = {}
    for t in defaults.gallery():
        d = await ctx.data.templates.insert({"kind": t["kind"], "name": t["name"], "body": t["body"], "gallery_key": t["key"]})
        tpl[t["key"]] = d["_id"]
    st = defaults.discovery_session_type()
    st["host_ids"] = [user["_id"]]
    st["slug"] = "discovery-call"
    st_doc = await ctx.data.session_types.insert(st)
    # Link the booking template to the discovery session type.
    bt = await ctx.data.templates.get(tpl["discovery_booking"])
    for pg in bt["body"]["pages"]:
        for b in pg["blocks"]:
            if b["type"] == "scheduler":
                b["session_type_id"] = st_doc["_id"]
    await ctx.data.templates.update({"_id": bt["_id"]}, {"body": bt["body"]})
    for a in defaults.starter_automations(tpl):
        await ctx.data.automations.insert(dict(a, active=True, project_types=[], starter=True))
    for ag in limits.AGENT_KEYS:
        mode = {"daily_brief": "read_only", "meeting": "internal_auto", "chat": "per_level"}.get(ag, "draft")
        await ctx.data.agent_settings.insert({"agent": ag, "autonomy": mode, "instructions": "", "enabled": True})
    return ws


# ---------------- workspace ----------------

@action("workspace.get", "read", desc="Get the practice profile, theme, invoice and settings.")
async def ws_get(ctx, p):
    ws = await ctx.ws()
    out = clean(ws)
    if ctx.role not in ("owner",):
        out.get("invoice", {}).pop("bank", None)
    out["role"] = ctx.role
    out["ai_budget"] = await limits.ai_budget(ctx.ws_id)
    out["limits"] = await limits.all_values_for(ctx.ws_id)
    out["stages"] = clean(await ctx.data.stages.find({}, sort=[("order", 1)]))
    return out


class WsUpdate(P):
    name: Optional[str] = None
    profile: Optional[dict] = None
    theme: Optional[dict] = None
    invoice: Optional[dict] = None
    settings: Optional[dict] = None


@action("workspace.update", "internal", WsUpdate, roles=ADMINS, desc="Update practice profile, theme, invoice details or settings.")
async def ws_update(ctx, p: WsUpdate):
    ws = await ctx.ws()
    changes = {}
    if p.name:
        changes["name"] = p.name.strip()[:80]
    for sec in ("profile", "theme", "invoice", "settings"):
        val = getattr(p, sec)
        if val is None:
            continue
        if sec == "invoice":
            if ctx.role != "owner" and any(k in val for k in ("upi_id", "bank")):
                raise forbidden("Only the Owner can change bank and UPI details.")
            if "upi_id" in val and val["upi_id"] and not re.match(r"^[\w.\-]{1,256}@[a-zA-Z]{2,64}$", val["upi_id"].strip()):
                raise AppError("invalid", "That UPI ID doesn't look right. It should look like name@bank.", 400)
            if val.get("gst_enabled") and not (val.get("gstin") or ws["invoice"].get("gstin")):
                raise AppError("invalid", "Please add your GSTIN before switching GST on.", 400)
            lf = val.get("late_fee")
            if lf and int(lf.get("pct_bp", 0)) > 1000:
                raise AppError("invalid", "The late fee can be at most 10%.", 400)
        if sec == "settings" and "sending_domain" in val and val["sending_domain"]:
            from app.integrations.vendors import dns_check
            chk = await dns_check(val["sending_domain"].strip())
            if not (chk["spf"] and chk["dkim"]):
                raise AppError("dns", "This domain is missing SPF or DKIM records, so emails would land in spam. "
                                      "Add the records shown in Settings, then try again.", 400, chk)
        merged = dict(ws.get(sec) or {})
        merged.update(val)
        changes[sec] = merged
    await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": changes})
    ctx._ws = None
    await audit(ctx, "workspace.update", ctx.ws_id, {"sections": list(changes)})
    return await ws_get(ctx, None)


# ---------------- team ----------------

@action("team.list", "read", desc="List the team members and their roles.")
async def team_list(ctx, p):
    ms = await ctx.data.memberships.find({"active": True})
    out = []
    for m in ms:
        u = await get_db().users.find_one({"_id": m["user_id"]}) if not str(m["user_id"]).startswith("pending:") else None
        out.append({"membership_id": m["_id"], "user_id": m["user_id"], "role": m["role"],
                    "name": (u or {}).get("name") or m.get("name", ""), "phone": (u or {}).get("phone") or m.get("phone"),
                    "joined": bool(u), "project_ids": m.get("project_ids", [])})
    return out


class TeamAdd(P):
    phone: str
    name: str = ""
    role: str = "member"
    project_ids: list = []


@action("team.add", "internal", TeamAdd, roles=ADMINS, desc="Add a team member by mobile number (they count as invited).")
async def team_add(ctx, p: TeamAdd):
    from app.auth import norm_phone
    if p.role not in ROLES or p.role == "owner":
        raise AppError("invalid", "Please choose Admin, Manager, Member or Collaborator.", 400)
    phone = norm_phone(p.phone)
    db = get_db()
    if p.role != "collaborator":
        n = await ctx.data.memberships.count({"active": True, "role": {"$ne": "collaborator"}})
        await limits.check_count(ctx, "users_per_workspace", n)
    u = await db.users.find_one({"phone": phone})
    uid = u["_id"] if u else "pending:" + phone
    if await ctx.data.memberships.find_one({"user_id": uid}):
        raise AppError("exists", "This person is already on the team.", 409)
    await ctx.data.memberships.insert({"user_id": uid, "role": p.role, "active": bool(u), "phone": phone, "name": p.name,
                                       "project_ids": p.project_ids if p.role == "collaborator" else []})
    if not await db.invites.find_one({"phone": phone}):
        await db.invites.insert_one({"_id": new_id(), "phone": phone, "name": p.name, "note": f"Team of {(await ctx.ws())['name']}",
                                     "invited_by": ctx.user_id, "status": "joined" if u else "invited", "created_at": now(),
                                     "via": "team", "workspace_id": ctx.ws_id})
    await audit(ctx, "team.add", phone, {"role": p.role})
    return await team_list(ctx, None)


class TeamRole(P):
    membership_id: str
    role: str
    project_ids: Optional[list] = None


@action("team.update_role", "internal", TeamRole, roles=ADMINS, desc="Change a team member's role.")
async def team_role(ctx, p: TeamRole):
    m = await ctx.data.memberships.get(p.membership_id)
    if not m:
        raise not_found("That team member")
    if m["role"] == "owner" or p.role == "owner":
        raise AppError("invalid", "There is exactly one Owner per practice. The Owner's role can't be changed here.", 400)
    if p.role not in ROLES:
        raise AppError("invalid", "Please choose a valid role.", 400)
    ch = {"role": p.role}
    if p.project_ids is not None:
        ch["project_ids"] = p.project_ids
    await ctx.data.memberships.update({"_id": m["_id"]}, ch)
    await audit(ctx, "team.role_changed", m["user_id"], {"from": m["role"], "to": p.role})
    return await team_list(ctx, None)


class TeamRemove(P):
    membership_id: str


@action("team.remove", "destructive", TeamRemove, roles=ADMINS, desc="Remove a team member.", agent_ok=False)
async def team_remove(ctx, p: TeamRemove):
    m = await ctx.data.memberships.get(p.membership_id)
    if not m or m["role"] == "owner":
        raise AppError("invalid", "The Owner can't be removed.", 400)
    await ctx.data.memberships.update({"_id": m["_id"]}, {"active": False})
    await audit(ctx, "team.removed", m["user_id"])
    return await team_list(ctx, None)


# ---------------- stages ----------------

@action("stages.list", "read", desc="List pipeline stages in order.")
async def stages_list(ctx, p):
    return clean(await ctx.data.stages.find({}, sort=[("order", 1)]))


class StagesSave(P):
    stages: list  # [{id?, name, group}]
    stage_rules: Optional[list] = None


@action("stages.save", "internal", StagesSave, roles=ADMINS, desc="Rename, add or reorder pipeline stages (up to 20).")
async def stages_save(ctx, p: StagesSave):
    if not 1 <= len(p.stages) <= 20:
        raise AppError("invalid", "A pipeline needs between 1 and 20 stages.", 400)
    keep = []
    for i, s in enumerate(p.stages):
        name = (s.get("name") or "").strip()
        if not name:
            raise AppError("invalid", "Every stage needs a name.", 400)
        grp = s.get("group") if s.get("group") in ("opportunity", "booked") else "opportunity"
        if s.get("id"):
            await ctx.data.stages.update({"_id": s["id"]}, {"name": name, "group": grp, "order": i})
            keep.append(s["id"])
        else:
            d = await ctx.data.stages.insert({"name": name, "group": grp, "order": i, "key": None})
            keep.append(d["_id"])
    for s in await ctx.data.stages.find({"_id": {"$nin": keep}}):
        if await ctx.data.projects.count({"stage_id": s["_id"], "archived": {"$ne": True}}):
            raise AppError("in_use", f"Move the projects out of \"{s['name']}\" before removing it.", 409)
        await ctx.data.stages.soft_delete({"_id": s["_id"]})
    if p.stage_rules is not None:
        await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": {"settings.stage_rules": p.stage_rules}})
        ctx._ws = None
    await audit(ctx, "stages.save", None)
    return await stages_list(ctx, None)


# ---------------- saved views ----------------

@action("views.list", "read", desc="List saved pipeline views.")
async def views_list(ctx, p):
    return clean(await ctx.data.views.find({}, sort=[("created_at", 1)]))


class ViewSave(P):
    id: Optional[str] = None
    name: str
    filters: dict = {}
    columns: list = []
    sort: Optional[dict] = None
    mode: str = "board"


@action("views.save", "internal", ViewSave, desc="Save a pipeline view (filters, columns, order, sort).")
async def views_save(ctx, p: ViewSave):
    doc = {"name": p.name.strip()[:40] or "View", "filters": p.filters, "columns": p.columns, "sort": p.sort, "mode": p.mode}
    if p.id:
        await ctx.data.views.update({"_id": p.id}, doc)
    else:
        await limits.check_count(ctx, "saved_views", await ctx.data.views.count())
        await ctx.data.views.insert(doc)
    return await views_list(ctx, None)


class IdOnly(P):
    id: str


@action("views.delete", "internal", IdOnly, desc="Delete a saved view.")
async def views_delete(ctx, p: IdOnly):
    await ctx.data.views.hard_delete({"_id": p.id})
    return await views_list(ctx, None)


# ---------------- notifications ----------------

@action("notifications.list", "read", desc="List my notifications.")
async def notif_list(ctx, p):
    return clean(await ctx.data.notifications.find({"user_id": ctx.user_id}, sort=[("created_at", -1)], limit=50))


@action("notifications.read_all", "internal", agent_ok=False, desc="Mark my notifications read.")
async def notif_read(ctx, p):
    await ctx.data.notifications.update_many({"user_id": ctx.user_id, "read": False}, {"read": True})
    return {"ok": True}


# ---------------- MCP tokens (outside assistants) ----------------

class McpCreate(P):
    name: str = "Claude"
    scope: str = "drafts"  # read | drafts | full


@action("mcp.create_token", "internal", McpCreate, roles=ADMINS, agent_ok=False,
        desc="Create a connector token for an outside AI assistant.")
async def mcp_create(ctx, p: McpCreate):
    await limits.require(ctx, "mcp_connector")
    if p.scope not in ("read", "drafts", "full"):
        raise AppError("invalid", "Choose read only, read + drafts, or full.", 400)
    raw = "pos_" + token(30)
    await ctx.data.mcp_tokens.insert({"name": p.name, "scope": p.scope, "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
                                      "user_id": ctx.user_id, "role": ctx.role, "last_used": None})
    await audit(ctx, "mcp.token_created", None, {"scope": p.scope})
    return {"token": raw, "note": "Copy this now. It won't be shown again."}


@action("mcp.list_tokens", "read", roles=ADMINS, agent_ok=False, desc="List connector tokens.")
async def mcp_list(ctx, p):
    return [{"id": t["_id"], "name": t["name"], "scope": t["scope"], "created_at": t["created_at"].isoformat(),
             "last_used": t.get("last_used").isoformat() if t.get("last_used") else None}
            for t in await ctx.data.mcp_tokens.find({})]


@action("mcp.revoke_token", "destructive", IdOnly, roles=ADMINS, agent_ok=False, desc="Revoke a connector token.")
async def mcp_revoke(ctx, p: IdOnly):
    await ctx.data.mcp_tokens.hard_delete({"_id": p.id})
    return {"ok": True}


@action("mcp.connected_apps", "read", agent_ok=False, desc="Assistants that signed in to this practice (OAuth), with what they may do.")
async def mcp_apps(ctx, p):
    from app.db import get_db
    q = {"workspace_id": ctx.ws_id, "kind": "refresh", "revoked": False}
    if ctx.role not in ("owner", "admin"):
        q["user_id"] = ctx.user_id
    rows = await get_db().oauth_tokens.find(q).to_list(500)
    users = {u["_id"]: u.get("name") or u.get("phone") for u in await get_db().users.find({"_id": {"$in": [r["user_id"] for r in rows]}}).to_list(None)}
    apps = {}
    for r in rows:
        k = (r["client_id"], r["user_id"])
        a = apps.setdefault(k, {"client_id": r["client_id"], "name": r.get("client_name") or "Assistant", "user": users.get(r["user_id"], ""),
                                "user_id": r["user_id"], "scope": r["scope"], "since": r["created_at"].isoformat(), "last_used": None})
        a["since"] = min(a["since"], r["created_at"].isoformat())
    for a in apps.values():
        last = await get_db().oauth_tokens.find({"workspace_id": ctx.ws_id, "client_id": a["client_id"], "user_id": a["user_id"],
                                                 "kind": "access", "last_used": {"$ne": None}}).sort("last_used", -1).limit(1).to_list(1)
        a["last_used"] = last[0]["last_used"].isoformat() if last else None
    return list(apps.values())


class AppRevoke(P):
    client_id: str
    user_id: Optional[str] = None


@action("mcp.disconnect_app", "destructive", AppRevoke, agent_ok=False, desc="Sign an assistant out of this practice.")
async def mcp_disconnect(ctx, p: AppRevoke):
    from app.db import get_db
    uid = p.user_id if (p.user_id and ctx.role in ("owner", "admin")) else ctx.user_id
    r = await get_db().oauth_tokens.update_many({"workspace_id": ctx.ws_id, "client_id": p.client_id, "user_id": uid}, {"$set": {"revoked": True}})
    await audit(ctx, "mcp.app_disconnected", p.client_id, {"user": uid})
    return {"ok": True, "revoked": r.modified_count}


@action("audit.list", "read", roles=OWNER | ADMINS, agent_ok=False, desc="Recent audit log.")
async def audit_list(ctx, p):
    return clean(await ctx.data.audit_log.find({}, sort=[("created_at", -1)], limit=100))


_ = (ALL, STAFF)
