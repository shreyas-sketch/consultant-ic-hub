"""Limits engine (the playbook's plans.py, with no plans yet).

Limits are data, not code. The registry below lists every key with its label,
type and default. Values live in `limit_values` and can be changed in Admin with
no deploy (read through a ~60 second cache). Per-workspace overrides live in
`account_overrides`.

require() and consume() are called from day one even though everything is open,
so switching a limit on later needs no code change.
"""
import time

from app.db import get_db
from app.core.util import AppError, aware, month_key, now

AGENT_KEYS = ["setup", "lead", "followup", "meeting", "proposal", "collections",
              "daily_brief", "automation_builder", "chat"]

# key: (label, type, default, unit)
REGISTRY = {
    "users_per_workspace": ("Users per workspace", "number", 10, "users"),
    "live_lead_forms": ("Live lead forms", "number", None, "forms"),
    "session_types": ("Session types", "number", None, "session types"),
    "active_automations": ("Active automations", "number", None, "automations"),
    "saved_views": ("Saved pipeline views", "number", 5, "views"),
    "ai_cost_cap_paise": ("AI cost cap per workspace per month", "money", 40000, "paise"),
    "whatsapp_per_month": ("WhatsApp messages per month", "number", 500, "messages"),
    "meetbot_hours_per_month": ("Meeting-bot hours per month", "number", 20, "hours"),
    "storage_mb": ("File storage", "number", 10240, "MB"),
    "report_level": ("Report level", "choice:basic,standard,advanced", "advanced", ""),
    "powered_by_hidden": ("\"Powered by\" line hidden on client pages", "bool", True, ""),
    "custom_domain": ("Custom domain", "bool", True, ""),
    "mcp_connector": ("MCP connector", "bool", True, ""),
    "time_billing": ("Time to invoice", "bool", True, ""),
    "budgets": ("Project budgets", "bool", True, ""),
    "retainers": ("Retainers", "bool", True, ""),
    "active_retainers": ("Active retainers", "number", None, "retainers"),
    "estimates": ("Estimates and quick quotes", "bool", True, ""),
    "forecast_reports": ("Forecast, profit and utilisation reports", "bool", True, ""),
    "bulk_invoice_actions": ("Bulk invoice download, remind and export", "bool", True, ""),
    "client_tasks": ("Client tasks", "bool", True, ""),
    "task_templates": ("Task templates and recurring tasks", "bool", True, ""),
    **{f"agent_{a}": (f"Agent: {a.replace('_', ' ')}", "bool", True, "") for a in AGENT_KEYS},
}

_cache = {"at": 0.0, "values": {}}
CACHE_SECONDS = 60


def bust_cache():
    _cache["at"] = 0.0


async def _values():
    if time.time() - _cache["at"] > CACHE_SECONDS:
        rows = await get_db().limit_values.find({}).to_list(None)
        _cache["values"] = {r["_id"]: r for r in rows}
        _cache["at"] = time.time()
    return _cache["values"]


async def value(ws_id: str, key: str, ws_created_at=None):
    if key not in REGISTRY:
        raise KeyError(key)
    ov = await get_db().account_overrides.find_one({"workspace_id": ws_id, "key": key})
    if ov and (ov.get("ends_at") is None or aware(ov["ends_at"]) > now()):
        return ov["value"]
    row = (await _values()).get(key)
    if row is None:
        return REGISTRY[key][2]
    if row.get("legacy_before") and ws_created_at is not None:
        if aware(ws_created_at) < aware(row["legacy_before"]):
            return row.get("legacy_value", REGISTRY[key][2])
    return row["value"]


async def _ws_created(ws_id):
    ws = await get_db().workspaces.find_one({"_id": ws_id}, {"created_at": 1})
    return ws.get("created_at") if ws else None


async def get(ctx, key):
    return await value(ctx.ws_id, key, await _ws_created(ctx.ws_id))


async def require(ctx, key):
    """Yes/no features. Off -> 403 'locked'."""
    v = await get(ctx, key)
    if v is False:
        raise AppError("locked", "This feature is switched off for your account right now.", 403, {"key": key})
    return v


async def check_count(ctx, key, current: int, adding: int = 1):
    """Count limits (forms, session types, users...). None means unlimited."""
    lim = await get(ctx, key)
    if lim is not None and current + adding > lim:
        label = REGISTRY[key][0]
        raise AppError("limit", f"You've reached the limit for {label.lower()} ({lim}).", 402,
                       {"key": key, "limit": lim, "used": current})


def _usage_id(ws_id, mk=None):
    return f"{ws_id}:{mk or month_key()}"


async def usage(ws_id, mk=None) -> dict:
    doc = await get_db().usage.find_one({"_id": _usage_id(ws_id, mk)})
    return (doc or {}).get("counts", {})


async def consume(ctx, key, amount=1):
    """Monthly meters (WhatsApp messages, bot hours). Over the limit -> 402 'limit'."""
    lim = await get(ctx, key)
    used = (await usage(ctx.ws_id)).get(key, 0)
    if lim is not None and used + amount > lim:
        raise AppError("limit", f"You've used {used} of {lim} {REGISTRY[key][3]} this month.", 402,
                       {"key": key, "limit": lim, "used": used})
    await _inc(ctx.ws_id, {key: amount})


async def refund(ctx, key, amount=1):
    await _inc(ctx.ws_id, {key: -amount})


async def _inc(ws_id, incs: dict, extra_set=None):
    upd = {"$inc": {f"counts.{k}": v for k, v in incs.items()},
           "$setOnInsert": {"workspace_id": ws_id, "month": month_key()}}
    await get_db().usage.update_one({"_id": _usage_id(ws_id)}, upd, upsert=True)


# ---- AI budget (one budget per workspace, shared by the team) ----

async def ai_budget(ws_id) -> dict:
    cap = await value(ws_id, "ai_cost_cap_paise", await _ws_created(ws_id))
    spent = (await usage(ws_id)).get("ai_cost_paise", 0)
    pct = 0 if not cap else round(100 * spent / cap)
    return {"cap_paise": cap, "spent_paise": spent, "pct": pct,
            "state": "ok" if pct < 80 else ("warning" if pct < 100 else "reached")}


async def add_ai_cost(ws_id, user_id, cost_paise: int):
    incs = {"ai_cost_paise": cost_paise}
    if user_id:
        incs[f"ai_cost_member.{user_id}"] = cost_paise
    await _inc(ws_id, incs)


async def all_values_for(ws_id) -> dict:
    created = await _ws_created(ws_id)
    return {k: await value(ws_id, k, created) for k in REGISTRY}
