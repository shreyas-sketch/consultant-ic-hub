"""Our admin panel. Every /api/admin route needs an admin (401 logged out, 403 members)."""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import get_admin, norm_phone, revoke_sessions
from core import limits, settings
from core.db import get_db
from core.util import AppError, aware, clean, fmt_date, month_key, new_id, now

router = APIRouter(prefix="/api/admin", dependencies=[Depends(get_admin)])


async def change(who, what, old, new):
    await get_db().admin_changes.insert_one({"_id": new_id(), "who": who.get("name") or who["phone"], "who_id": who["_id"], "what": what,
                                             "old": old, "new": new, "at": now()})


# ---------------- KPIs ----------------

@router.get("/kpis")
async def kpis():
    db = get_db()
    week = now() - timedelta(days=7)
    return {"invited": await db.invites.count_documents({"via": {"$ne": "team"}}),
            "joined": await db.invites.count_documents({"status": "joined", "via": {"$ne": "team"}}),
            "workspaces": await db.workspaces.count_documents({}),
            "active_week": len(await db.activity.distinct("workspace_id", {"at": {"$gte": week}})),
            "files_sent": await db.client_files.count_documents({"status": {"$ne": "draft"}}),
            "payments_recorded": await db.ledger.count_documents({"type": "payment"}),
            "pending_approvals": await db.approvals.count_documents({"status": "pending"}),
            "ai_cost_month_paise": sum(((u.get("counts") or {}).get("ai_cost_paise", 0)) for u in
                                       await db.usage.find({"month": month_key()}).to_list(None))}


# ---------------- invites ----------------

class InviteIn(BaseModel):
    phones: list           # one or many
    name: str = ""
    note: str = ""


@router.get("/invites")
async def invites(status: str = "", q: str = ""):
    f = {"via": {"$ne": "team"}}
    if status:
        f["status"] = status
    if q:
        f["$or"] = [{"phone": {"$regex": q}}, {"name": {"$regex": q, "$options": "i"}}, {"note": {"$regex": q, "$options": "i"}}]
    return clean(await get_db().invites.find(f).sort("created_at", -1).to_list(1000))


@router.post("/invites")
async def invite_add(body: InviteIn, admin=Depends(get_admin)):
    db = get_db()
    added, existing, bad = 0, 0, []
    for raw in body.phones[:5000]:
        raw = str(raw).strip()
        if not raw:
            continue
        try:
            phone = norm_phone(raw)
        except AppError:
            bad.append(raw)
            continue
        ex = await db.invites.find_one({"phone": phone})
        if ex:
            if ex["status"] == "removed":
                await db.invites.update_one({"_id": ex["_id"]}, {"$set": {"status": "invited"}})
            existing += 1
            continue
        await db.invites.insert_one({"_id": new_id(), "phone": phone, "name": body.name if len(body.phones) == 1 else "", "note": body.note,
                                     "invited_by": admin.get("name") or admin["phone"], "status": "invited", "created_at": now(), "via": "admin"})
        added += 1
    await change(admin, "invites.add", None, {"added": added, "note": body.note})
    return {"added": added, "already": existing, "not_valid": bad}


class RemoveIn(BaseModel):
    restore: bool = False


@router.post("/invites/{iid}/access")
async def invite_access(iid: str, body: RemoveIn, admin=Depends(get_admin)):
    """Remove access: the account goes read-only at once. Client links keep working. Nothing is deleted."""
    db = get_db()
    inv = await db.invites.find_one({"_id": iid})
    if not inv:
        raise AppError("not_found", "That invite was not found.", 404)
    removed = not body.restore
    await db.invites.update_one({"_id": iid}, {"$set": {"status": "removed" if removed else ("joined" if inv.get("user_id") else "invited")}})
    u = await db.users.find_one({"phone": inv["phone"]})
    if u:
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"access_removed": removed}})
        await db.workspaces.update_many({"owner_id": u["_id"]}, {"$set": {"read_only": removed}})
    await change(admin, "invites.access", inv["phone"], "removed" if removed else "restored")
    return {"ok": True}


# ---------------- limits editor ----------------

@router.get("/limits")
async def limits_list():
    rows = {r["_id"]: r for r in await get_db().limit_values.find({}).to_list(None)}
    out = []
    for k, (label, typ, default, unit) in limits.REGISTRY.items():
        r = rows.get(k, {})
        out.append({"key": k, "label": label, "type": typ, "unit": unit, "default": default, "value": r.get("value", default),
                    "legacy_value": r.get("legacy_value"), "legacy_before": clean(r).get("legacy_before") if r else None})
    return {"limits": out, "plans": [], "note": "No plans yet. When plans exist, each becomes a column here."}


class LimitIn(BaseModel):
    value: object
    applies_to: str = "everyone"   # everyone | new_accounts


def coerce(typ, v):
    if typ in ("number", "money"):
        if v in (None, "", "unlimited", "Unlimited"):
            return None
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            raise AppError("invalid", "Please enter a whole number, or leave it empty for unlimited.", 400)
        if n < 0:
            raise AppError("invalid", "Limits can't be negative.", 400)
        return n
    if typ == "bool":
        if isinstance(v, bool):
            return v
        if str(v).lower() in ("true", "on", "yes", "1"):
            return True
        if str(v).lower() in ("false", "off", "no", "0"):
            return False
        raise AppError("invalid", "Choose on or off.", 400)
    if typ.startswith("choice:"):
        opts = typ.split(":", 1)[1].split(",")
        if v not in opts:
            raise AppError("invalid", f"Choose one of: {', '.join(opts)}.", 400)
        return v
    return v


@router.put("/limits/{key}")
async def limit_set(key: str, body: LimitIn, admin=Depends(get_admin)):
    if key not in limits.REGISTRY:
        raise AppError("not_found", "Unknown limit.", 404)
    typ = limits.REGISTRY[key][1]
    val = coerce(typ, body.value)
    db = get_db()
    cur = await db.limit_values.find_one({"_id": key})
    old = cur["value"] if cur else limits.REGISTRY[key][2]
    doc = {"_id": key, "value": val, "updated_at": now()}
    if body.applies_to == "new_accounts":
        doc["legacy_value"] = old
        doc["legacy_before"] = now()
    else:
        doc["legacy_value"] = None
        doc["legacy_before"] = None
    await db.limit_values.replace_one({"_id": key}, doc, upsert=True)
    limits.bust_cache()
    await change(admin, f"limit.{key}", old, {"value": val, "applies_to": body.applies_to})
    return {"ok": True}


@router.get("/changes")
async def changes():
    return clean(await get_db().admin_changes.find({}).sort("at", -1).to_list(300))


@router.post("/changes/{cid}/revert")
async def revert(cid: str, admin=Depends(get_admin)):
    db = get_db()
    c = await db.admin_changes.find_one({"_id": cid})
    if not c or not c["what"].startswith("limit."):
        raise AppError("invalid", "Only limit changes can be reverted here.", 400)
    key = c["what"].split(".", 1)[1]
    cur = await db.limit_values.find_one({"_id": key})
    await db.limit_values.replace_one({"_id": key}, {"_id": key, "value": c["old"], "legacy_value": None, "legacy_before": None,
                                                     "updated_at": now()}, upsert=True)
    limits.bust_cache()
    await change(admin, f"limit.{key}", (cur or {}).get("value"), {"value": c["old"], "reverted": cid})
    return {"ok": True}


# ---------------- overrides ----------------

class OverrideIn(BaseModel):
    workspace_id: str
    key: str
    value: object
    ends_at: Optional[str] = None
    note: str = ""


@router.get("/overrides")
async def overrides(workspace_id: str = ""):
    f = {"workspace_id": workspace_id} if workspace_id else {}
    return clean(await get_db().account_overrides.find(f).to_list(1000))


@router.post("/overrides")
async def override_set(body: OverrideIn, admin=Depends(get_admin)):
    if body.key not in limits.REGISTRY:
        raise AppError("not_found", "Unknown limit.", 404)
    val = coerce(limits.REGISTRY[body.key][1], body.value)
    db = get_db()
    await db.account_overrides.delete_many({"workspace_id": body.workspace_id, "key": body.key})
    await db.account_overrides.insert_one({"_id": new_id(), "workspace_id": body.workspace_id, "key": body.key, "value": val,
                                           "ends_at": aware(body.ends_at) if body.ends_at else None, "note": body.note, "created_at": now()})
    await change(admin, f"override.{body.key}", body.workspace_id, {"value": val, "ends_at": body.ends_at, "note": body.note})
    return {"ok": True}


@router.delete("/overrides/{oid}")
async def override_del(oid: str, admin=Depends(get_admin)):
    await get_db().account_overrides.delete_one({"_id": oid})
    await change(admin, "override.removed", oid, None)
    return {"ok": True}


# ---------------- usage report ----------------

COUNTS = {"live_lead_forms": ("lead_forms", {"live": True}), "session_types": ("session_types", {"active": True}),
          "active_automations": ("automations", {"active": True}), "saved_views": ("views", {}),
          "users_per_workspace": ("memberships", {"active": True})}


@router.get("/usage")
async def usage_report():
    db = get_db()
    wss = await db.workspaces.find({}, {"_id": 1, "created_at": 1}).to_list(None)
    out = []
    for key, (label, typ, default, unit) in limits.REGISTRY.items():
        if typ not in ("number", "money"):
            continue
        b = {"under_half": 0, "half_to_80": 0, "above_80": 0, "at_limit": 0, "unused": 0}
        for w in wss:
            lim = await limits.value(w["_id"], key, w.get("created_at"))
            if key in COUNTS:
                col, f = COUNTS[key]
                used = await db[col].count_documents(dict(f, workspace_id=w["_id"], deleted_at=None))
            else:
                c = (await limits.usage(w["_id"])) or {}
                used = c.get({"ai_cost_cap_paise": "ai_cost_paise"}.get(key, key), 0)
            if not used:
                b["unused"] += 1
            if lim is None or lim == 0:
                b["under_half"] += 1
                continue
            pct = used / lim
            b["at_limit" if pct >= 1 else "above_80" if pct >= .8 else "half_to_80" if pct >= .5 else "under_half"] += 1
        out.append({"key": key, "label": label, **b})
    feats = {}
    for name, col in (("Lead forms", "lead_forms"), ("Client files sent", "client_files"), ("Automations run", "automation_runs"),
                      ("Agent runs", "agent_runs"), ("Sessions booked", "sessions"), ("Expenses", "expenses"), ("MCP tokens", "mcp_tokens")):
        feats[name] = len(await db[col].distinct("workspace_id"))
    return {"limits": out, "features_used_by_accounts": feats, "accounts": len(wss),
            "note": "This is the data to price on later."}


# ---------------- AI cost ----------------

@router.get("/ai-cost")
async def ai_cost():
    db = get_db()
    rows = await db.usage.find({"month": month_key()}).to_list(None)
    wsn = {w["_id"]: w["name"] for w in await db.workspaces.find({}, {"name": 1}).to_list(None)}
    items = sorted([{"workspace_id": r["workspace_id"], "name": wsn.get(r["workspace_id"], ""), "cost_paise": (r.get("counts") or {}).get("ai_cost_paise", 0),
                     "members": (r.get("counts") or {}).get("ai_cost_member", {})} for r in rows], key=lambda x: -x["cost_paise"])
    total = sum(i["cost_paise"] for i in items)
    kill = await db.admin_settings.find_one({"_id": "agents"}) or {"off": []}
    return {"top": items[:20], "average_paise": round(total / len(items)) if items else 0, "total_paise": total,
            "accounts": len(items), "agents_off": kill.get("off", []), "agents": limits.AGENT_KEYS}


class KillIn(BaseModel):
    agent: str
    off: bool


@router.post("/agents/kill")
async def agent_kill(body: KillIn, admin=Depends(get_admin)):
    if body.agent not in limits.AGENT_KEYS:
        raise AppError("not_found", "Unknown agent.", 404)
    db = get_db()
    cur = (await db.admin_settings.find_one({"_id": "agents"}) or {}).get("off", [])
    new = sorted(set(cur) | {body.agent}) if body.off else [a for a in cur if a != body.agent]
    await db.admin_settings.update_one({"_id": "agents"}, {"$set": {"off": new}}, upsert=True)
    await change(admin, f"agent.kill.{body.agent}", body.agent in cur, body.off)
    return {"ok": True, "off": new}


# ---------------- workspaces, health, funnel ----------------

@router.get("/workspaces")
async def workspaces(q: str = ""):
    db = get_db()
    f = {"name": {"$regex": q, "$options": "i"}} if q else {}
    out = []
    for w in await db.workspaces.find(f).sort("created_at", -1).to_list(500):
        last = await db.activity.find_one({"workspace_id": w["_id"]}, sort=[("at", -1)])
        owner = await db.users.find_one({"_id": w["owner_id"]})
        ovs = await db.account_overrides.find({"workspace_id": w["_id"]}).to_list(None)
        out.append({"id": w["_id"], "name": w["name"], "owner": (owner or {}).get("name") or (owner or {}).get("phone"),
                    "phone": (owner or {}).get("phone"), "status": "read-only" if w.get("read_only") else "active",
                    "onboarded": w.get("onboarded", False), "created": fmt_date(w["created_at"]),
                    "last_active": fmt_date(last["at"]) if last else None,
                    "team": await db.memberships.count_documents({"workspace_id": w["_id"], "active": True}),
                    "projects": await db.projects.count_documents({"workspace_id": w["_id"], "deleted_at": None}),
                    "files_sent": await db.client_files.count_documents({"workspace_id": w["_id"], "status": {"$ne": "draft"}}),
                    "overrides": [{"id": o["_id"], "key": o["key"], "value": o["value"], "note": o.get("note")} for o in ovs],
                    "slug": w.get("slug"), "domains": w.get("domains", []),
                    "storage_mb": round(int(w.get("storage_bytes") or 0) / 1048576, 1)})
    return out


@router.get("/health")
async def health():
    db = get_db()
    day = now() - timedelta(days=1)
    return {"automation_runs": {s: await db.automation_runs.count_documents({"status": s}) for s in
                                ("running", "waiting", "waiting_approval", "failed", "done")},
            "agent_runs_24h": {s: await db.agent_runs.count_documents({"status": s, "created_at": {"$gte": day}}) for s in ("done", "stopped", "failed")},
            "events_backlog": await db.events.count_documents({"processed": False}),
            "outbound_failed_24h": await db.messages.count_documents({"status": "failed", "created_at": {"$gte": day}}),
            "whatsapp_templates": [{"name": k, "status": "approved (fake)" if settings.vendor_mode("whatsapp") == "fake" else "check provider"}
                                   for k in __import__("actions.inbox", fromlist=["x"]).WA_TEMPLATES]}


@router.get("/funnel")
async def funnel():
    db = get_db()
    invited = await db.invites.find({"via": {"$ne": "team"}}).to_list(None)
    users = {u["phone"]: u for u in await db.users.find({"phone": {"$in": [i["phone"] for i in invited]}}).to_list(None)}
    wss = {}
    for u in users.values():
        w = await db.workspaces.find_one({"owner_id": u["_id"]})
        if w:
            wss[u["_id"]] = w
    ids = [w["_id"] for w in wss.values()]
    steps = [("Invited", len(invited)), ("Joined", len(users)), ("Set up", sum(1 for w in wss.values() if w.get("onboarded"))),
             ("First lead", len(await db.projects.distinct("workspace_id", {"workspace_id": {"$in": ids}}))),
             ("First file sent", len(await db.client_files.distinct("workspace_id", {"workspace_id": {"$in": ids}, "status": {"$ne": "draft"}}))),
             ("First payment recorded", len(await db.ledger.distinct("workspace_id", {"workspace_id": {"$in": ids}, "type": "payment"})))]
    return [{"step": s, "count": c} for s, c in steps]


# ---------------- custom domains ----------------

class DomainIn(BaseModel):
    workspace_id: str
    host: str


@router.post("/domains")
async def domain_add(body: DomainIn, admin=Depends(get_admin)):
    """Map a practice's custom domain (they add a CNAME to our client domain; the proxy issues the certificate)."""
    import re
    host = body.host.strip().lower().rstrip(".")
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", host):
        raise AppError("invalid", "That doesn't look like a domain.", 400)
    db = get_db()
    ws = await db.workspaces.find_one({"_id": body.workspace_id})
    if not ws:
        raise AppError("not_found", "Unknown practice.", 404)
    if not await limits.value(ws["_id"], "custom_domain", ws.get("created_at")):
        raise AppError("locked", "Custom domains are switched off for this account.", 403)
    await db.domains.update_one({"host": host}, {"$set": {"host": host, "workspace_id": ws["_id"]}, "$setOnInsert": {"_id": new_id()}}, upsert=True)
    await db.workspaces.update_one({"_id": ws["_id"]}, {"$addToSet": {"domains": host}})
    await change(admin, "domain.add", ws["_id"], host)
    return {"ok": True}


@router.delete("/domains/{host}")
async def domain_del(host: str, admin=Depends(get_admin)):
    db = get_db()
    d = await db.domains.find_one({"host": host})
    if d:
        await db.domains.delete_one({"_id": d["_id"]})
        await db.workspaces.update_one({"_id": d["workspace_id"]}, {"$pull": {"domains": host}})
        await change(admin, "domain.remove", d["workspace_id"], host)
    return {"ok": True}


# ---------------- jobs, vendors, settings ----------------

@router.get("/jobs")
async def jobs():
    from jobs import JOBS
    db = get_db()
    out = []
    for name, (fn, sched, label) in JOBS.items():
        last = await db.job_runs.find_one({"job": name}, sort=[("started_at", -1)])
        out.append({"name": name, "label": label, "schedule": sched, "last": clean(last)})
    return out


@router.post("/jobs/{name}/run")
async def job_run(name: str, admin=Depends(get_admin)):
    from jobs import run_job
    return await run_job(name, force=True)


@router.get("/vendors")
async def vendors_list():
    return [{"name": v, "mode": settings.vendor_mode(v)} for v in settings.VENDORS] + [{"name": "qa_mode", "mode": str(settings.QA_MODE)}]


class AiSettingsIn(BaseModel):
    model_small: Optional[str] = None
    model_large: Optional[str] = None
    price_small: Optional[list] = None
    price_large: Optional[list] = None


@router.get("/settings")
async def settings_get():
    s = await get_db().admin_settings.find_one({"_id": "ai"}) or {}
    return {"model_small": s.get("model_small", settings.MODEL_SMALL), "model_large": s.get("model_large", settings.MODEL_LARGE),
            "price_small": s.get("price_small", list(settings.PRICE_SMALL)), "price_large": s.get("price_large", list(settings.PRICE_LARGE)),
            "note": settings.USD_TO_INR_NOTE}


@router.put("/settings")
async def settings_put(body: AiSettingsIn, admin=Depends(get_admin)):
    ch = {k: v for k, v in body.model_dump().items() if v is not None}
    for k in ("price_small", "price_large"):
        if k in ch and (len(ch[k]) != 2 or any(not isinstance(x, int) or x < 0 for x in ch[k])):
            raise AppError("invalid", "Prices are two whole numbers: paise per million input and output tokens.", 400)
    await get_db().admin_settings.update_one({"_id": "ai"}, {"$set": ch}, upsert=True)
    await change(admin, "settings.ai", None, ch)
    return await settings_get()
