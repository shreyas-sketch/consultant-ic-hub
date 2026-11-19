"""Who can see and act on which project."""
from app.core.util import forbidden, not_found

SEE_ALL = {"owner", "admin", "manager", "system"}
ACT_ALL = {"owner", "admin", "system"}


def on_project(ctx, p) -> bool:
    if ctx.role == "collaborator":
        return p["_id"] in (ctx.project_ids or [])
    return p.get("owner_id") == ctx.user_id or ctx.user_id in (p.get("team_ids") or [])


def can_see(ctx, p) -> bool:
    return ctx.role in SEE_ALL or on_project(ctx, p)


def can_act(ctx, p) -> bool:
    """Send files and emails, change the project."""
    return ctx.role in ACT_ALL or on_project(ctx, p)


def visible_filter(ctx) -> dict:
    if ctx.role in SEE_ALL:
        return {}
    if ctx.role == "collaborator":
        return {"_id": {"$in": list(ctx.project_ids or [])}}
    return {"$or": [{"owner_id": ctx.user_id}, {"team_ids": ctx.user_id}]}


async def project(ctx, pid, act=False):
    p = await ctx.data.projects.get(pid)
    if not p or not can_see(ctx, p):
        raise not_found("That project")
    if act and not can_act(ctx, p):
        raise forbidden("You can only do this on projects you are part of.")
    return p


# ---------------- one filter for every door (screens, API, chat, agents, MCP) ----------------

import re as _re

COST_KEY = _re.compile(r"(^|_)(cost|margin)")
FILTER_KEYS = {"sort", "sort_by", "order_by", "group_by", "filter", "filters", "where"}


def hide_money_for(ws, role) -> bool:
    return role == "collaborator" or role in ((ws or {}).get("settings", {}).get("hide_money_roles") or [])


async def see_costs(ctx) -> bool:
    """Cost rates and margins: Owner and Admin; a Manager only if the practice allows it; nobody else."""
    if ctx.role in ("owner", "admin", "system"):
        return not ctx.hide_money
    if ctx.role == "manager" and not ctx.hide_money:
        return bool(((await ctx.ws()).get("settings") or {}).get("managers_see_costs"))
    return False


def _strip_cost(obj):
    if isinstance(obj, list):
        return [_strip_cost(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _strip_cost(v) for k, v in obj.items() if not (isinstance(k, str) and COST_KEY.search(k))}
    return obj


async def redact(ctx, obj):
    """Applied to every action result: money hidden for hide-money roles, costs and margins for anyone not allowed."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if not await see_costs(ctx):
        obj = _strip_cost(obj)
    return strip_money(ctx, obj)


def _mentions(v, rx):
    if isinstance(v, str):
        return bool(rx.search(v.lower()))
    if isinstance(v, dict):
        return any(rx.search(str(k).lower()) or _mentions(x, rx) for k, x in v.items())
    if isinstance(v, list):
        return any(_mentions(x, rx) for x in v)
    return False


async def refuse_hidden_filters(ctx, args):
    """Sorting or filtering by a field you can't see is refused, not answered."""
    if not isinstance(args, dict):
        return
    keys = [k for k in args if k in FILTER_KEYS or str(k).startswith(("min_", "max_"))]
    if not keys:
        return
    from app.core.util import AppError
    if not await see_costs(ctx) and any(COST_KEY.search(str(k)) or _mentions(args[k], COST_KEY) for k in keys):
        raise AppError("forbidden", "You can't sort or filter by cost or margin with your access.", 403)
    money = _re.compile(r"paise|amount|value|rate|price|fee")
    if ctx.hide_money and any(money.search(str(k)) or _mentions(args[k], money) for k in keys):
        raise AppError("forbidden", "Money amounts are hidden for your role, so you can't sort or filter by them.", 403)


def strip_money(ctx, obj):
    """Hide money totals for roles with 'hide money amounts' on."""
    if not ctx.hide_money or obj is None:
        return obj
    if isinstance(obj, list):
        return [strip_money(ctx, o) for o in obj]
    if isinstance(obj, dict):
        return {k: (None if k.endswith("_paise") and k not in ("price_paise",) else strip_money(ctx, v)) for k, v in obj.items()}
    return obj
