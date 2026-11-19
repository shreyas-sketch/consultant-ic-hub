"""Services and rate cards (add-on A1).

Rates are set once and used everywhere: time entries, estimates, invoices.
Lookup order for a project: project card -> client card -> default card -> the
service's own default rate. Inside a card: a line for the person, then their
role, then the service.

Every time entry stores the rate and cost rate that applied when it was logged,
so a later change never rewrites old work. Money is whole paise; time whole minutes.
"""
from datetime import date as Date
from typing import Optional

from app.domain import perm
from app.domain.registry import ADMINS, STAFF, P, action
from app.core.events import audit, emit
from app.core.util import IST, AppError, clean, inr, not_found, now

UNITS = {"flat": "Flat fee", "hour": "Per hour", "day": "Per day", "session": "Per session", "week": "Per week",
         "month": "Per month", "item": "Per item"}
DEFAULT_ROLES = ["Partner", "Associate", "Analyst"]


def today_str():
    return now().astimezone(IST).date().isoformat()


def day_hours(ws) -> int:
    return int((ws.get("settings") or {}).get("day_hours") or 8)


def hourly(rate_paise: int, unit: str, ws) -> int:
    """A rate turned into paise per hour. Fixed-price units have no hourly value."""
    if unit == "hour":
        return int(rate_paise)
    if unit == "day":
        return int(rate_paise) // day_hours(ws)
    if unit == "week":
        return int(rate_paise) // (5 * day_hours(ws))
    return 0


# ---------------- lookups ----------------

async def default_card(ctx):
    c = await ctx.data.rate_cards.find_one({"is_default": True})
    if c:
        return c
    return await ctx.data.rate_cards.insert({"name": "Standard rates", "currency": "INR", "is_default": True})


async def rate_on(ctx, line, on: str) -> int:
    """The line's rate on a date: the latest change that has started, else the base rate."""
    ch = await ctx.data.rate_changes.find({"line_id": line["_id"], "status": "scheduled", "effective_from": {"$lte": on}},
                                          sort=[("effective_from", -1)], limit=1)
    return int(ch[0]["rate_paise"]) if ch else int(line["rate_paise"])


async def member_profile(ctx, user_id, on: Optional[str] = None):
    on = on or today_str()
    rows = await ctx.data.member_cost_rates.find({"user_id": user_id, "effective_from": {"$lte": on}}, sort=[("effective_from", -1)], limit=1)
    return rows[0] if rows else {}


async def cards_for(ctx, project):
    out = []
    if project and project.get("rate_card_id"):
        c = await ctx.data.rate_cards.get(project["rate_card_id"])
        if c:
            out.append(("project", c))
    cid = (project or {}).get("contact_ids", [None])[0] if project else None
    if cid:
        contact = await ctx.data.contacts.get(cid)
        if contact and contact.get("rate_card_id"):
            c = await ctx.data.rate_cards.get(contact["rate_card_id"])
            if c:
                out.append(("client", c))
    out.append(("default", await default_card(ctx)))
    return out


async def resolve(ctx, project, on: Optional[str] = None, service_id=None, user_id=None) -> dict:
    """The rate for a service / person on a project and date, and where it came from."""
    ws = await ctx.ws()
    on = (on or today_str())[:10]
    prof = await member_profile(ctx, user_id, on) if user_id else {}
    role = prof.get("billing_role")
    cost = int(prof.get("cost_rate_paise") or 0)
    for scope, card in await cards_for(ctx, project):
        lines = await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"]})
        pick = (next((l for l in lines if l["target"] == "person" and user_id and l.get("user_id") == user_id), None)
                or next((l for l in lines if l["target"] == "role" and role and l.get("role") == role), None)
                or next((l for l in lines if l["target"] == "service" and service_id and l.get("service_id") == service_id), None))
        if pick:
            r = await rate_on(ctx, pick, on)
            return {"rate_paise": r, "unit": pick["unit"], "hourly_paise": hourly(r, pick["unit"], ws), "currency": card.get("currency", "INR"),
                    "source": f"{scope} rate card", "card_id": card["_id"], "line_id": pick["_id"], "cost_rate_paise": cost}
    if service_id:
        s = await ctx.data.services.get(service_id)
        if s:
            return {"rate_paise": int(s["rate_paise"]), "unit": s["unit"], "hourly_paise": hourly(s["rate_paise"], s["unit"], ws),
                    "currency": "INR", "source": "service default", "card_id": None, "line_id": None, "cost_rate_paise": cost}
    # Nothing specific: the default card's hourly line, if there is one.
    card = await default_card(ctx)
    for l in await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"], "unit": "hour", "target": "service"}):
        r = await rate_on(ctx, l, on)
        return {"rate_paise": r, "unit": "hour", "hourly_paise": r, "currency": card.get("currency", "INR"), "source": "default hourly rate",
                "card_id": card["_id"], "line_id": l["_id"], "cost_rate_paise": cost}
    return {"rate_paise": 0, "unit": "hour", "hourly_paise": 0, "currency": "INR", "source": "no rate set", "card_id": None, "line_id": None,
            "cost_rate_paise": cost}


async def snapshot(ctx, project, on, service_id=None, user_id=None) -> dict:
    """What a time entry stores when it's logged. Never recalculated later (unless the consultant asks)."""
    r = await resolve(ctx, project, on, service_id, user_id)
    prof = await member_profile(ctx, user_id, on) if user_id else {}
    return {"rate_snapshot_paise": r["hourly_paise"], "cost_snapshot_paise": int(prof.get("cost_rate_paise") or 0),
            "currency": r["currency"], "rate_source": r["source"], "role": prof.get("billing_role")}


# ---------------- services ----------------

class ServiceIn(P):
    id: Optional[str] = None
    name: str
    description: str = ""
    unit: str = "hour"
    rate_paise: int = 0


@action("services.list", "read", roles=STAFF, desc="The service library: name, unit and default rate.")
async def services_list(ctx, p):
    ws = await ctx.ws()
    rows = await ctx.data.services.find({}, sort=[("archived", 1), ("name", 1)])
    out = clean(rows)
    for o in out:
        o["unit_label"] = UNITS.get(o["unit"], o["unit"])
        o["hourly_paise"] = hourly(o["rate_paise"], o["unit"], ws)
    return out


@action("services.save", "internal", ServiceIn, roles=ADMINS, desc="Add or edit a service in the library.")
async def services_save(ctx, p: ServiceIn):
    if not p.name.strip():
        raise AppError("invalid", "The service needs a name.", 400)
    if p.unit not in UNITS:
        raise AppError("invalid", "Choose a unit: flat fee, per hour, per day, per session, per week, per month or per item.", 400)
    if p.rate_paise < 0:
        raise AppError("invalid", "The rate can't be below zero.", 400)
    doc = {"name": p.name.strip()[:80], "description": p.description[:300], "unit": p.unit, "rate_paise": int(p.rate_paise)}
    if p.id:
        if not await ctx.data.services.get(p.id):
            raise not_found("That service")
        await ctx.data.services.update({"_id": p.id}, doc)
        s = await ctx.data.services.get(p.id)
    else:
        s = await ctx.data.services.insert(dict(doc, archived=False))
        # Every service gets a line on the default card, so the card is the one place rates live.
        card = await default_card(ctx)
        await ctx.data.rate_card_lines.insert({"rate_card_id": card["_id"], "target": "service", "service_id": s["_id"],
                                               "unit": p.unit, "rate_paise": int(p.rate_paise)})
    return clean(s)


class IdIn(P):
    id: str


@action("services.delete", "destructive", IdIn, roles=ADMINS, agent_ok=False,
        desc="Remove a service. If it's in use (time, estimates, rate cards), it's archived instead.")
async def services_delete(ctx, p: IdIn):
    s = await ctx.data.services.get(p.id)
    if not s:
        raise not_found("That service")
    used = (await ctx.data.time_entries.count({"service_id": p.id}) or await ctx.data.estimates.count({"phases.lines.service_id": p.id})
            or await ctx.data.rate_card_lines.count({"service_id": p.id, "rate_card_id": {"$ne": (await default_card(ctx))["_id"]}}))
    if used:
        await ctx.data.services.update({"_id": p.id}, {"archived": True})
        return {"ok": True, "archived": True, "message": "This service is in use, so it's archived. Old work keeps it."}
    await ctx.data.services.soft_delete({"_id": p.id})
    await ctx.data.rate_card_lines.hard_delete({"service_id": p.id})
    return {"ok": True, "deleted": True}


@action("services.restore", "internal", IdIn, roles=ADMINS, desc="Bring an archived service back.")
async def services_restore(ctx, p: IdIn):
    await ctx.data.services.update({"_id": p.id}, {"archived": False})
    return {"ok": True}


# ---------------- rate cards ----------------

async def card_view(ctx, card):
    ws = await ctx.ws()
    services = {s["_id"]: s for s in await ctx.data.services.find({})}
    users = {u["_id"]: u for u in await _team(ctx)}
    lines = []
    for l in await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"]}, sort=[("created_at", 1)]):
        cur = await rate_on(ctx, l, today_str())
        upcoming = await ctx.data.rate_changes.find({"line_id": l["_id"], "status": "scheduled", "effective_from": {"$gt": today_str()}},
                                                    sort=[("effective_from", 1)])
        label = (services.get(l.get("service_id"), {}).get("name") if l["target"] == "service" else
                 l.get("role") if l["target"] == "role" else users.get(l.get("user_id"), {}).get("name", "Team member"))
        lines.append({"id": l["_id"], "target": l["target"], "service_id": l.get("service_id"), "role": l.get("role"),
                      "user_id": l.get("user_id"), "label": label or "—", "unit": l["unit"], "unit_label": UNITS.get(l["unit"], l["unit"]),
                      "base_rate_paise": l["rate_paise"], "rate_paise": cur, "hourly_paise": hourly(cur, l["unit"], ws),
                      "upcoming": [{"id": c["_id"], "rate_paise": c["rate_paise"], "effective_from": c["effective_from"]} for c in upcoming]})
    projects = [{"id": x["_id"], "name": x["name"]} for x in await ctx.data.projects.find({"rate_card_id": card["_id"]}, projection={"name": 1})]
    clients = [{"id": x["_id"], "name": x["name"]} for x in await ctx.data.contacts.find({"rate_card_id": card["_id"]}, projection={"name": 1})]
    return dict(clean(card), lines=lines, projects=projects, clients=clients)


async def _team(ctx):
    from app.db import get_db
    ms = await ctx.data.memberships.find({"active": True})
    ids = [m["user_id"] for m in ms if not str(m["user_id"]).startswith("pending:")]
    us = await get_db().users.find({"_id": {"$in": ids}}).to_list(None)
    roles = {m["user_id"]: m["role"] for m in ms}
    return [dict(u, role=roles.get(u["_id"])) for u in us]


@action("rate_cards.list", "read", roles=STAFF, desc="Rate cards with their lines, current rates and upcoming changes.")
async def rate_cards_list(ctx, p):
    await default_card(ctx)
    cards = await ctx.data.rate_cards.find({}, sort=[("is_default", -1), ("name", 1)])
    return [await card_view(ctx, c) for c in cards]


class CardIn(P):
    id: Optional[str] = None
    name: str
    currency: str = "INR"
    lines: list = []   # [{id?, target: service|role|person, service_id?, role?, user_id?, unit, rate_paise}]


@action("rate_cards.save", "internal", CardIn, roles=ADMINS, desc="Create or edit a rate card and its lines.")
async def rate_cards_save(ctx, p: CardIn):
    if not p.name.strip():
        raise AppError("invalid", "The rate card needs a name.", 400)
    cur = (p.currency or "INR").upper()[:3]
    for l in p.lines:
        if l.get("target") not in ("service", "role", "person"):
            raise AppError("invalid", "Each line is for a service, a role or a person.", 400)
        if l.get("unit", "hour") not in UNITS:
            raise AppError("invalid", "Choose a unit for every line.", 400)
        if not isinstance(l.get("rate_paise", 0), int) or l.get("rate_paise", 0) < 0:
            raise AppError("invalid", "Rates must be whole paise, zero or more.", 400)
        if l["target"] == "service" and not l.get("service_id") or l["target"] == "role" and not l.get("role") \
                or l["target"] == "person" and not l.get("user_id"):
            raise AppError("invalid", "Every line needs its service, role or person.", 400)
    if p.id:
        card = await ctx.data.rate_cards.get(p.id)
        if not card:
            raise not_found("That rate card")
        await ctx.data.rate_cards.update({"_id": p.id}, {"name": p.name.strip()[:80], "currency": cur})
    else:
        card = await ctx.data.rate_cards.insert({"name": p.name.strip()[:80], "currency": cur, "is_default": False})
    keep = []
    for l in p.lines:
        doc = {"rate_card_id": card["_id"], "target": l["target"], "service_id": l.get("service_id"), "role": l.get("role"),
               "user_id": l.get("user_id"), "unit": l.get("unit", "hour"), "rate_paise": int(l.get("rate_paise", 0))}
        if l.get("id") and await ctx.data.rate_card_lines.find_one({"_id": l["id"], "rate_card_id": card["_id"]}):
            await ctx.data.rate_card_lines.update({"_id": l["id"]}, doc)
            keep.append(l["id"])
        else:
            keep.append((await ctx.data.rate_card_lines.insert(doc))["_id"])
    for gone in await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"], "_id": {"$nin": keep}}):
        await ctx.data.rate_card_lines.hard_delete({"_id": gone["_id"]})
        await ctx.data.rate_changes.update_many({"line_id": gone["_id"], "status": "scheduled"}, {"status": "cancelled"})
    await audit(ctx, "rate_card.save", card["_id"], {"lines": len(keep)})
    return await card_view(ctx, await ctx.data.rate_cards.get(card["_id"]))


@action("rate_cards.delete", "destructive", IdIn, roles=ADMINS, agent_ok=False, desc="Delete a rate card (not the default one).")
async def rate_cards_delete(ctx, p: IdIn):
    card = await ctx.data.rate_cards.get(p.id)
    if not card:
        raise not_found("That rate card")
    if card.get("is_default"):
        raise AppError("invalid", "The default rate card can't be deleted. Edit its rates instead.", 400)
    for coll in ("projects", "contacts"):
        await getattr(ctx.data, coll).update_many({"rate_card_id": p.id}, {"rate_card_id": None})
    await ctx.data.rate_cards.soft_delete({"_id": p.id})
    return {"ok": True}


class AssignIn(P):
    rate_card_id: Optional[str] = None   # None = back to the next card in line
    project_id: Optional[str] = None
    contact_id: Optional[str] = None
    apply_to_unbilled: bool = False


async def resnapshot_unbilled(ctx, project_ids):
    """Re-price unbilled time (not on any invoice) after a rate card change the consultant asked to apply."""
    n = 0
    for pid in project_ids:
        pr = await ctx.data.projects.get(pid)
        for e in await ctx.data.time_entries.find({"project_id": pid, "billing_status": "unbilled", "invoice_id": None, "locked": {"$ne": True}}):
            snap = await snapshot(ctx, pr, e["date"], e.get("service_id"), e.get("user_id"))
            await ctx.data.time_entries.update({"_id": e["_id"]}, {"rate_snapshot_paise": snap["rate_snapshot_paise"],
                                                                    "rate_source": snap["rate_source"], "currency": snap["currency"]})
            n += 1
    return n


@action("rate_cards.assign", "internal", AssignIn, roles=ADMINS | {"manager"},
        desc="Give a project or a client its own rate card. Choose whether unbilled time is re-priced or only new time.")
async def rate_cards_assign(ctx, p: AssignIn):
    if bool(p.project_id) == bool(p.contact_id):
        raise AppError("invalid", "Choose a project or a client.", 400)
    if p.rate_card_id and not await ctx.data.rate_cards.get(p.rate_card_id):
        raise not_found("That rate card")
    if p.project_id:
        await perm.project(ctx, p.project_id, act=True)
        await ctx.data.projects.update({"_id": p.project_id}, {"rate_card_id": p.rate_card_id})
        pids = [p.project_id]
    else:
        if not await ctx.data.contacts.get(p.contact_id):
            raise not_found("That client")
        await ctx.data.contacts.update({"_id": p.contact_id}, {"rate_card_id": p.rate_card_id})
        pids = [x["_id"] for x in await ctx.data.projects.find({"contact_ids": p.contact_id}, projection={"_id": 1})]
    n = await resnapshot_unbilled(ctx, pids) if p.apply_to_unbilled else 0
    await audit(ctx, "rate_card.assign", p.project_id or p.contact_id, {"card": p.rate_card_id, "repriced": n})
    return {"ok": True, "repriced_entries": n}


# ---------------- scheduled changes ----------------

class ChangeIn(P):
    effective_from: str              # YYYY-MM-DD
    line_id: Optional[str] = None    # one line ...
    rate_paise: Optional[int] = None
    pct: Optional[float] = None      # ... or every line on a card by a percentage
    rate_card_id: Optional[str] = None


@action("rate_changes.schedule", "internal", ChangeIn, roles=ADMINS,
        desc="Set a new rate from a date, e.g. 'day rate ₹40,000 from 1 April', or raise every rate on a card by a percentage. "
             "Applies to work from that date; past entries never change.")
async def rate_changes_schedule(ctx, p: ChangeIn):
    try:
        on = Date.fromisoformat(p.effective_from[:10]).isoformat()
    except ValueError:
        raise AppError("invalid", "Pick a start date for the new rate.", 400)
    if on < today_str():
        raise AppError("invalid", "Pick today or a later date. Work already logged keeps its rate.", 400)
    if p.line_id:
        lines = [await ctx.data.rate_card_lines.get(p.line_id)]
        if not lines[0]:
            raise not_found("That rate")
    else:
        card = await ctx.data.rate_cards.get(p.rate_card_id) if p.rate_card_id else await default_card(ctx)
        if not card:
            raise not_found("That rate card")
        lines = await ctx.data.rate_card_lines.find({"rate_card_id": card["_id"]})
    if p.rate_paise is None and p.pct is None:
        raise AppError("invalid", "Give the new rate or a percentage.", 400)
    if p.pct is not None and not -90 <= p.pct <= 500:
        raise AppError("invalid", "That percentage looks too large.", 400)
    made = []
    for l in lines:
        base = await rate_on(ctx, l, on)
        new = int(p.rate_paise) if p.rate_paise is not None else int(round(base * (100 + p.pct) / 100 / 100)) * 100
        if new < 0:
            raise AppError("invalid", "The rate can't be below zero.", 400)
        c = await ctx.data.rate_changes.insert({"rate_card_id": l["rate_card_id"], "line_id": l["_id"], "rate_paise": new,
                                                "effective_from": on, "status": "scheduled", "previous_paise": base})
        made.append({"id": c["_id"], "line_id": l["_id"], "from_paise": base, "to_paise": new})
    await emit(ctx, "rate.changed", {"effective_from": on, "lines": len(made)})
    await audit(ctx, "rate.schedule", None, {"effective_from": on, "count": len(made)})
    return {"ok": True, "effective_from": on, "changes": made,
            "summary": f"{len(made)} rate{'s' if len(made) != 1 else ''} change from {on}." +
                       (f" {inr(made[0]['from_paise'])} → {inr(made[0]['to_paise'])}." if len(made) == 1 else "")}


@action("rate_changes.cancel", "internal", IdIn, roles=ADMINS, desc="Cancel a scheduled rate change that hasn't started.")
async def rate_changes_cancel(ctx, p: IdIn):
    c = await ctx.data.rate_changes.get(p.id)
    if not c or c["status"] != "scheduled":
        raise not_found("That change")
    if c["effective_from"] <= today_str():
        raise AppError("invalid", "This rate has already started. Schedule a new change instead.", 400)
    await ctx.data.rate_changes.update({"_id": p.id}, {"status": "cancelled"})
    return {"ok": True}


# ---------------- resolve, settings, team rates ----------------

class ResolveIn(P):
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    service_id: Optional[str] = None
    user_id: Optional[str] = None
    date: Optional[str] = None


@action("rates.resolve", "read", ResolveIn, roles=STAFF,
        desc="The rate that applies for a service or person on a project and date, and which card it came from.")
async def rates_resolve(ctx, p: ResolveIn):
    pr = None
    if p.project_id:
        pr = await perm.project(ctx, p.project_id)
    elif p.project_name:
        rows = await ctx.data.projects.find({"name": {"$regex": p.project_name, "$options": "i"}, **perm.visible_filter(ctx)}, limit=1)
        if not rows:
            raise not_found("A project with that name")
        pr = rows[0]
    r = await resolve(ctx, pr, p.date, p.service_id, p.user_id)
    r["project"] = pr["name"] if pr else None
    r["unit_label"] = UNITS.get(r["unit"], r["unit"])
    return r


class RateSettings(P):
    day_hours: Optional[int] = None
    target_margin_pct: Optional[float] = None
    managers_see_costs: Optional[bool] = None
    billing_roles: Optional[list] = None


@action("rates.settings", "read", roles=STAFF, desc="Rate settings: hours in a day, target margin, billing roles.")
async def rates_settings(ctx, p):
    s = (await ctx.ws()).get("settings") or {}
    return {"day_hours": s.get("day_hours") or 8, "target_margin_bp": s.get("target_margin_bp", 3000),
            "managers_see_costs": bool(s.get("managers_see_costs")), "billing_roles": s.get("billing_roles") or DEFAULT_ROLES,
            "time_locked_before": s.get("time_locked_before")}


@action("rates.update_settings", "internal", RateSettings, roles=ADMINS, desc="Change hours in a day, target margin or billing roles.")
async def rates_update_settings(ctx, p: RateSettings):
    ch = {}
    if p.day_hours is not None:
        if not 1 <= p.day_hours <= 24:
            raise AppError("invalid", "A day must be between 1 and 24 hours.", 400)
        ch["settings.day_hours"] = int(p.day_hours)
    if p.target_margin_pct is not None:
        if not 0 <= p.target_margin_pct <= 95:
            raise AppError("invalid", "Target margin must be between 0% and 95%.", 400)
        ch["settings.target_margin_bp"] = int(round(p.target_margin_pct * 100))
    if p.managers_see_costs is not None:
        if ctx.role not in ("owner", "system"):
            raise AppError("forbidden", "Only the Owner can let Managers see costs.", 403)
        ch["settings.managers_see_costs"] = bool(p.managers_see_costs)
    if p.billing_roles is not None:
        ch["settings.billing_roles"] = [str(r).strip()[:40] for r in p.billing_roles if str(r).strip()][:12]
    if ch:
        from app.db import get_db
        await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": ch})
        ctx._ws = None
        await audit(ctx, "rates.settings", None, {k: v for k, v in ch.items()})
    return await rates_settings(ctx, None)


class TeamRate(P):
    user_id: str
    cost_rate_paise: Optional[int] = None
    available_hours_week: Optional[float] = None
    billing_role: Optional[str] = None
    effective_from: Optional[str] = None


@action("team.set_rates", "internal", TeamRate, roles=ADMINS,
        desc="A team member's billing role, cost per hour (what an hour costs the practice) and available hours a week.")
async def team_set_rates(ctx, p: TeamRate):
    if not await ctx.data.memberships.find_one({"user_id": p.user_id}):
        raise not_found("That team member")
    on = (p.effective_from or today_str())[:10]
    cur = await member_profile(ctx, p.user_id, "9999-12-31")
    doc = {"user_id": p.user_id, "effective_from": on,
           "cost_rate_paise": int(p.cost_rate_paise) if p.cost_rate_paise is not None else int(cur.get("cost_rate_paise") or 0),
           "available_minutes_week": int(round(p.available_hours_week * 60)) if p.available_hours_week is not None
           else int(cur.get("available_minutes_week") or 40 * 60),
           "billing_role": p.billing_role if p.billing_role is not None else cur.get("billing_role")}
    if doc["cost_rate_paise"] < 0 or not 0 <= doc["available_minutes_week"] <= 100 * 60:
        raise AppError("invalid", "Cost must be zero or more, and available hours between 0 and 100 a week.", 400)
    same = await ctx.data.member_cost_rates.find_one({"user_id": p.user_id, "effective_from": on})
    if same:
        await ctx.data.member_cost_rates.update({"_id": same["_id"]}, doc)
    else:
        await ctx.data.member_cost_rates.insert(doc)
    await audit(ctx, "team.set_rates", p.user_id, {"from": on})
    return {"ok": True}


@action("team.rates", "read", roles=ADMINS | {"manager"}, desc="Each team member's billing role, cost per hour and available hours.")
async def team_rates(ctx, p):
    out = []
    for u in await _team(ctx):
        prof = await member_profile(ctx, u["_id"])
        out.append({"user_id": u["_id"], "name": u.get("name") or u.get("phone"), "role": u.get("role"),
                    "billing_role": prof.get("billing_role"), "cost_rate_paise": int(prof.get("cost_rate_paise") or 0),
                    "available_hours_week": round(int(prof.get("available_minutes_week") or 2400) / 60, 1)})
    return out


# ---------------- setup and migration ----------------

async def setup_from_interview(ctx, offers, rates_text):
    """Setup agent: the first service library and default rate card from the interview."""
    import re
    ws = await ctx.ws()
    made = 0
    for o in offers:
        unit = "month" if o.get("monthly") else "flat"
        await services_save(ctx, ServiceIn(name=o["name"], unit=unit, rate_paise=o["price_paise"]))
        made += 1
    t = (rates_text or "").lower()
    for unit, rx in (("hour", r"([\d,]+(?:\.\d+)?)\s*(k|l|lakh)?\s*(?:₹)?\s*(?:/|an|a|per)\s*h(?:ou)?r"),
                     ("day", r"([\d,]+(?:\.\d+)?)\s*(k|l|lakh)?\s*(?:₹)?\s*(?:/|a|per)\s*day")):
        m = re.search(rx, t.replace("₹", ""))
        if m:
            v = float(m.group(1).replace(",", ""))
            v *= 1000 if (m.group(2) or "") == "k" else 100000 if (m.group(2) or "") in ("l", "lakh") else 1
            await services_save(ctx, ServiceIn(name=f"Consulting {'hour' if unit == 'hour' else 'day'}", unit=unit, rate_paise=int(v * 100)))
            made += 1
    _ = ws
    return made


