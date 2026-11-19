"""Time to invoice (add-on A2) and bulk invoice actions (4.8).

Every entry is non-billable, unbilled or billed. Time on a draft invoice is
still unbilled; it becomes billed (and locked) when the invoice is sent.
Cancelling or fully crediting the invoice gives the time back.

Whole minutes and whole paise only. An invoice line made from time keeps its
minutes, so the line total is exactly minutes x hourly rate / 60, and the
total never depends on how the lines are grouped.
"""
import csv
import io
import math
from collections import defaultdict
from datetime import date as Date
from datetime import timedelta
from typing import Optional

from app.domain import perm
from app.domain.billing import rates
from app.domain.registry import ADMINS, STAFF, P, action
from app.core import limits
from app.core.events import audit, emit, log, notify
from app.core.util import IST, AppError, clean, fmt_date, inr, new_id, not_found, now

STATUSES = ("non_billable", "unbilled", "billed")
REASONS = ("admin", "selling", "learning", "other")


def amount(e) -> int:
    return int(e["minutes"]) * int(e.get("rate_snapshot_paise") or 0) // 60


def hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


async def locked_before(ctx):
    return ((await ctx.ws()).get("settings") or {}).get("time_locked_before")


async def editable(ctx, e, verb="change"):
    """Plain refusals for time that can't be touched."""
    if ctx.role in ("member", "collaborator") and e.get("user_id") != ctx.user_id:
        raise AppError("forbidden", "You can only change your own time.", 403)
    if e.get("retainer_period_id") and (e.get("billing_status") == "billed" or e.get("locked")):
        raise AppError("locked", f"This time is in a closed retainer period, so you can't {verb} it. Log a correction in the current period.", 409)
    if e.get("billing_status") == "billed" or e.get("locked"):
        raise AppError("locked", f"This time is on a sent invoice, so you can't {verb} it. Cancel or credit the invoice first.", 409)
    lb = await locked_before(ctx)
    if lb and e["date"] < lb:
        raise AppError("locked", f"Time before {fmt_date(lb)} is locked, so you can't {verb} it.", 409)


async def find_project(ctx, project_id=None, project_name=None):
    if project_id:
        return await perm.project(ctx, project_id, act=True)
    if project_name:
        rx = {"$regex": project_name.strip()[:60], "$options": "i"}
        rows = await ctx.data.projects.find({"archived": False, "$or": [{"name": rx}], **perm.visible_filter(ctx)}, limit=2)
        if not rows:
            cs = await ctx.data.contacts.find({"$or": [{"name": rx}, {"company": rx}]}, limit=5)
            if cs:
                rows = await ctx.data.projects.find({"archived": False, "contact_ids": {"$in": [c["_id"] for c in cs]},
                                                     **perm.visible_filter(ctx)}, sort=[("last_activity_at", -1)], limit=2)
        if not rows:
            raise not_found("A project with that name")
        return await perm.project(ctx, rows[0]["_id"], act=True)
    raise AppError("invalid", "Which project is this time for?", 400)


def iso_day(s=None):
    if not s:
        return now().astimezone(IST).date().isoformat()
    try:
        return Date.fromisoformat(str(s)[:10]).isoformat()
    except ValueError:
        raise AppError("invalid", "That date doesn't look right.", 400)


# ---------------- logging time ----------------

class TimeLog(P):
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    minutes: Optional[int] = None
    hours: Optional[float] = None
    date: Optional[str] = None
    note: str = ""
    task_id: Optional[str] = None
    service_id: Optional[str] = None
    user_id: Optional[str] = None
    billable: bool = True
    reason: Optional[str] = None      # for non-billable time: admin, selling, learning, other


async def log_entry(ctx, pr, minutes, on, note="", task_id=None, service_id=None, user_id=None, billable=True, reason=None, source="manual"):
    if not 1 <= int(minutes) <= 24 * 60:
        raise AppError("invalid", "Time must be between 1 minute and 24 hours.", 400)
    lb = await locked_before(ctx)
    if lb and on < lb:
        raise AppError("locked", f"Time before {fmt_date(lb)} is locked. Pick a later date.", 409)
    if task_id:
        t = await ctx.data.tasks.get(task_id)
        if not t or t.get("project_id") != pr["_id"]:
            raise not_found("That task")
        service_id = service_id or t.get("service_id")
    uid = user_id or ctx.user_id or (await ctx.ws())["owner_id"]
    snap = await rates.snapshot(ctx, pr, on, service_id, uid)
    e = await ctx.data.time_entries.insert({
        "project_id": pr["_id"], "task_id": task_id, "service_id": service_id, "user_id": uid, "date": on,
        "minutes": int(minutes), "note": (note or "")[:300], "billable": bool(billable),
        "billing_status": "unbilled" if billable else "non_billable", "reason": reason if not billable else None,
        "invoice_id": None, "invoice_line_id": None, "locked": False, "billed_by_hand": False, "source": source, **snap})
    await after_time_change(ctx, pr["_id"], e)
    await emit(ctx, "time.logged", {"entry_id": e["_id"], "minutes": e["minutes"]}, pr["_id"])
    return e


async def after_time_change(ctx, project_id, entry=None):
    """Retainer period, budget and alerts follow every change in time."""
    from app.domain.billing import budgets
    from app.domain.billing import retainers
    if entry is not None:
        await retainers.on_time_entry(ctx, entry)
    await budgets.check(ctx, project_id)
    await retainers.check_usage(ctx, project_id)


@action("time.log", "internal", TimeLog,
        desc="Log time on a project (by id or name), e.g. '2 hours on Acme strategy today'. Billable unless said otherwise.")
async def time_log(ctx, p: TimeLog):
    pr = await find_project(ctx, p.project_id, p.project_name)
    minutes = p.minutes if p.minutes is not None else int(round((p.hours or 0) * 60))
    if p.user_id and p.user_id != ctx.user_id and ctx.role not in ("owner", "admin", "system"):
        raise AppError("forbidden", "Only the Owner or an Admin can log time for someone else.", 403)
    if p.reason and p.reason not in REASONS:
        raise AppError("invalid", "Reason must be admin, selling, learning or other.", 400)
    e = await log_entry(ctx, pr, minutes, iso_day(p.date), p.note, p.task_id, p.service_id, p.user_id, p.billable, p.reason)
    out = clean(e)
    out["summary"] = f"Logged {hm(e['minutes'])} on {pr['name']}" + ("" if e["billable"] else " (non-billable)") + "."
    return out


class TimeUpdate(P):
    id: str
    minutes: Optional[int] = None
    date: Optional[str] = None
    note: Optional[str] = None
    task_id: Optional[str] = None
    service_id: Optional[str] = None
    billable: Optional[bool] = None
    reason: Optional[str] = None


@action("time.update", "internal", TimeUpdate, desc="Edit a time entry. Billed or locked time can't be edited.")
async def time_update(ctx, p: TimeUpdate):
    e = await ctx.data.time_entries.get(p.id)
    if not e:
        raise not_found("That time entry")
    pr = await perm.project(ctx, e["project_id"], act=True)
    await editable(ctx, e, "edit")
    ch = {}
    if p.minutes is not None:
        if not 1 <= p.minutes <= 24 * 60:
            raise AppError("invalid", "Time must be between 1 minute and 24 hours.", 400)
        ch["minutes"] = int(p.minutes)
    if p.date:
        on = iso_day(p.date)
        lb = await locked_before(ctx)
        if lb and on < lb:
            raise AppError("locked", f"Time before {fmt_date(lb)} is locked. Pick a later date.", 409)
        ch["date"] = on
    if p.note is not None:
        ch["note"] = p.note[:300]
    if p.task_id is not None:
        ch["task_id"] = p.task_id or None
    if p.service_id is not None:
        ch["service_id"] = p.service_id or None
    if p.billable is not None:
        ch["billable"] = p.billable
        ch["billing_status"] = "unbilled" if p.billable else "non_billable"
    if p.reason is not None:
        ch["reason"] = p.reason or None
    if "date" in ch or "service_id" in ch:
        ch.update(await rates.snapshot(ctx, pr, ch.get("date", e["date"]), ch.get("service_id", e.get("service_id")), e.get("user_id")))
    if e.get("invoice_id") and ("minutes" in ch or "billable" in ch):
        raise AppError("locked", "This time is on a draft invoice. Remove it from the invoice first, or edit the invoice line.", 409)
    await ctx.data.time_entries.update({"_id": e["_id"]}, ch)
    e = await ctx.data.time_entries.get(e["_id"])
    await after_time_change(ctx, pr["_id"], e)
    return clean(e)


class IdIn(P):
    id: str


@action("time.delete", "destructive", IdIn, desc="Delete a time entry. Billed or locked time can't be deleted.")
async def time_delete(ctx, p: IdIn):
    e = await ctx.data.time_entries.get(p.id)
    if not e:
        raise not_found("That time entry")
    await perm.project(ctx, e["project_id"], act=True)
    await editable(ctx, e, "delete")
    if e.get("invoice_id"):
        raise AppError("locked", "This time is on a draft invoice. Remove it from the invoice first.", 409)
    await ctx.data.time_entries.soft_delete({"_id": e["_id"]})
    await after_time_change(ctx, e["project_id"])
    return {"ok": True}


class TimeList(P):
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    status: Optional[str] = None   # non_billable | unbilled | billed
    limit: int = 500


async def decorate(ctx, rows):
    pids = list({r["project_id"] for r in rows})
    projects = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": pids}}, projection={"name": 1})}
    tasks = {x["_id"]: x["title"] for x in await ctx.data.tasks.find({"_id": {"$in": [r["task_id"] for r in rows if r.get("task_id")]}})}
    services = {x["_id"]: x["name"] for x in await ctx.data.services.find({})}
    users = {u["_id"]: u.get("name") or u.get("phone") for u in await rates._team(ctx)}
    out = []
    for r in rows:
        o = clean(r)
        o.update(project=projects.get(r["project_id"], ""), task=tasks.get(r.get("task_id")), service=services.get(r.get("service_id")),
                 person=users.get(r.get("user_id"), ""), amount_paise=amount(r), on_draft=bool(r.get("invoice_id")) and r["billing_status"] != "billed")
        out.append(o)
    return out


@action("time.list", "read", TimeList, desc="Time entries, filtered by project, person, dates or billing status.")
async def time_list(ctx, p: TimeList):
    f = {}
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    else:
        vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
        f["project_id"] = {"$in": vis}
    if ctx.role in ("member", "collaborator"):
        f["user_id"] = ctx.user_id
    elif p.user_id:
        f["user_id"] = p.user_id
    if p.date_from or p.date_to:
        f["date"] = {**({"$gte": iso_day(p.date_from)} if p.date_from else {}), **({"$lte": iso_day(p.date_to)} if p.date_to else {})}
    if p.status:
        if p.status not in STATUSES:
            raise AppError("invalid", "Status is non_billable, unbilled or billed.", 400)
        f["billing_status"] = p.status
    rows = await ctx.data.time_entries.find(f, sort=[("date", -1), ("created_at", -1)], limit=min(max(p.limit, 1), 2000))
    return await decorate(ctx, rows)


# ---------------- weekly grid and timer ----------------

class WeekIn(P):
    week_start: Optional[str] = None
    user_id: Optional[str] = None


def monday(d: Date) -> Date:
    return d - timedelta(days=d.weekday())


@action("time.week", "read", WeekIn, desc="One person's week as a grid: projects and tasks down, days across.")
async def time_week(ctx, p: WeekIn):
    start = monday(Date.fromisoformat(iso_day(p.week_start)))
    days = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    uid = p.user_id if (p.user_id and ctx.role in ("owner", "admin", "manager", "system")) else ctx.user_id
    rows = await ctx.data.time_entries.find({"user_id": uid, "date": {"$gte": days[0], "$lte": days[-1]}})
    lb = await locked_before(ctx)
    grid = {}
    for e in rows:
        k = (e["project_id"], e.get("task_id"))
        g = grid.setdefault(k, {"project_id": e["project_id"], "task_id": e.get("task_id"), "cells": {d: 0 for d in days},
                                "fixed": {d: 0 for d in days}})
        g["cells"][e["date"]] += e["minutes"]
        if e["billing_status"] == "billed" or e.get("locked") or e.get("invoice_id") or e.get("source") != "grid" or (lb and e["date"] < lb):
            g["fixed"][e["date"]] += e["minutes"]
    # Projects the person worked on recently get an empty row, so the grid is quick to fill.
    recent = await ctx.data.time_entries.find({"user_id": uid, "date": {"$gte": (start - timedelta(days=14)).isoformat(), "$lt": days[0]}}, limit=200)
    for e in recent:
        grid.setdefault((e["project_id"], e.get("task_id")), {"project_id": e["project_id"], "task_id": e.get("task_id"),
                                                              "cells": {d: 0 for d in days}, "fixed": {d: 0 for d in days}})
    pids = list({k[0] for k in grid})
    projects = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": pids}}, projection={"name": 1})}
    tasks = {x["_id"]: x["title"] for x in await ctx.data.tasks.find({"_id": {"$in": [k[1] for k in grid if k[1]]}})}
    out = sorted(({**g, "project": projects.get(g["project_id"], ""), "task": tasks.get(g["task_id"])} for g in grid.values()),
                 key=lambda g: (g["project"], g["task"] or ""))
    return {"days": days, "rows": out, "locked_before": lb, "user_id": uid,
            "totals": {d: sum(g["cells"][d] for g in out) for d in days}, "week_total": sum(sum(g["cells"].values()) for g in out)}


class CellIn(P):
    project_id: str
    task_id: Optional[str] = None
    date: str
    minutes: int


@action("time.set_cell", "internal", CellIn, desc="Type hours straight into the weekly grid.")
async def time_set_cell(ctx, p: CellIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    on = iso_day(p.date)
    if p.minutes < 0 or p.minutes > 24 * 60:
        raise AppError("invalid", "A day can hold up to 24 hours.", 400)
    uid = ctx.user_id
    cell = await ctx.data.time_entries.find({"user_id": uid, "project_id": pr["_id"], "task_id": p.task_id, "date": on})
    grid = next((e for e in cell if e.get("source") == "grid" and e["billing_status"] != "billed" and not e.get("invoice_id")), None)
    others = sum(e["minutes"] for e in cell if e is not grid)
    want = p.minutes - others
    if want < 0:
        raise AppError("invalid", f"{hm(others)} is already logged here in separate entries. Edit those in the list.", 400)
    if grid:
        await editable(ctx, grid)
        if want == 0:
            await ctx.data.time_entries.soft_delete({"_id": grid["_id"]})
            await after_time_change(ctx, pr["_id"])
        else:
            await ctx.data.time_entries.update({"_id": grid["_id"]}, {"minutes": want})
            await after_time_change(ctx, pr["_id"], await ctx.data.time_entries.get(grid["_id"]))
    elif want > 0:
        await log_entry(ctx, pr, want, on, task_id=p.task_id, source="grid")
    return {"ok": True}


class TimerIn(P):
    project_id: str
    task_id: Optional[str] = None
    note: str = ""


@action("time.timer_start", "internal", TimerIn, desc="Start a timer on a project. A running timer is stopped and logged first.")
async def timer_start(ctx, p: TimerIn):
    await perm.project(ctx, p.project_id, act=True)
    stopped = None
    if await ctx.data.timers.find_one({"user_id": ctx.user_id}):
        stopped = await timer_stop(ctx, None)
    t = await ctx.data.timers.insert({"user_id": ctx.user_id, "project_id": p.project_id, "task_id": p.task_id, "note": p.note[:300],
                                      "started_at": now()})
    return {"ok": True, "timer": clean(t), "stopped": stopped}


@action("time.timer_stop", "internal", desc="Stop your running timer and log the time.")
async def timer_stop(ctx, p):
    t = await ctx.data.timers.find_one({"user_id": ctx.user_id})
    if not t:
        raise AppError("invalid", "No timer is running.", 400)
    from app.core.util import aware
    mins = max(1, math.ceil((now() - aware(t["started_at"])).total_seconds() / 60))
    await ctx.data.timers.hard_delete({"_id": t["_id"]})
    pr = await perm.project(ctx, t["project_id"], act=True)
    e = await log_entry(ctx, pr, min(mins, 24 * 60), iso_day(aware(t["started_at"]).astimezone(IST).date().isoformat()),
                        t.get("note", ""), t.get("task_id"), source="timer")
    return {"ok": True, "entry": clean(e), "summary": f"Logged {hm(e['minutes'])} on {pr['name']}."}


@action("time.timer", "read", desc="Your running timer, if any.")
async def timer_get(ctx, p):
    t = await ctx.data.timers.find_one({"user_id": ctx.user_id})
    if not t:
        return None
    pr = await ctx.data.projects.get(t["project_id"])
    return dict(clean(t), project=(pr or {}).get("name", ""))


# ---------------- billing status, lock, unbilled ----------------

class StatusIn(P):
    ids: list
    status: str
    reason: Optional[str] = None


@action("time.set_billing_status", "internal", StatusIn,
        desc="Mark time billed by hand (invoiced outside the app), back to unbilled, or non-billable.")
async def time_set_status(ctx, p: StatusIn):
    if p.status not in STATUSES:
        raise AppError("invalid", "Status is non_billable, unbilled or billed.", 400)
    done = 0
    for e in await ctx.data.time_entries.find({"_id": {"$in": p.ids[:500]}}):
        await perm.project(ctx, e["project_id"], act=True)
        if ctx.role in ("member", "collaborator") and e.get("user_id") != ctx.user_id:
            raise AppError("forbidden", "You can only change your own time.", 403)
        if e.get("invoice_id"):
            raise AppError("locked", "Some of this time is on an invoice. Change it through the invoice.", 409)
        lb = await locked_before(ctx)
        if lb and e["date"] < lb:
            raise AppError("locked", f"Time before {fmt_date(lb)} is locked.", 409)
        if e["billing_status"] == "billed" and not e.get("billed_by_hand"):
            raise AppError("locked", "This time was billed on an invoice. Cancel or credit the invoice to free it.", 409)
        ch = {"billing_status": p.status, "billable": p.status != "non_billable", "billed_by_hand": p.status == "billed",
              "locked": False, "reason": p.reason if p.status == "non_billable" else None}
        if p.status == "billed":
            ch["billed_at"] = now()
        await ctx.data.time_entries.update({"_id": e["_id"]}, ch)
        done += 1
    for pid in {e["project_id"] for e in await ctx.data.time_entries.find({"_id": {"$in": p.ids[:500]}})}:
        await after_time_change(ctx, pid)
    return {"ok": True, "changed": done}


class LockIn(P):
    before: Optional[str] = None   # None removes the lock


@action("time.lock_period", "internal", LockIn, roles=ADMINS, desc="Lock all time before a date so nothing in that period can change.")
async def time_lock(ctx, p: LockIn):
    from app.db import get_db
    on = iso_day(p.before) if p.before else None
    await get_db().workspaces.update_one({"_id": ctx.ws_id}, {"$set": {"settings.time_locked_before": on}})
    ctx._ws = None
    await audit(ctx, "time.lock", None, {"before": on})
    return {"ok": True, "locked_before": on}


class UnbilledIn(P):
    project_id: Optional[str] = None


async def on_retainer(ctx):
    return {x for r in await ctx.data.retainers.find({"status": {"$in": ["active", "paused"]}}, projection={"project_ids": 1}) for x in r["project_ids"]}


async def unbilled_summary(ctx, project_ids=None):
    """Billable time not yet on an invoice. Time on a retainer is billed by the retainer, so it isn't counted."""
    f = {"billing_status": "unbilled", "invoice_id": None}
    skip = await on_retainer(ctx)
    if project_ids is not None:
        f["project_id"] = {"$in": [p for p in project_ids if p not in skip]}
    elif skip:
        f["project_id"] = {"$nin": list(skip)}
    by = defaultdict(lambda: {"minutes": 0, "amount_paise": 0, "oldest": None, "count": 0})
    for e in await ctx.data.time_entries.find(f, projection={"project_id": 1, "minutes": 1, "rate_snapshot_paise": 1, "date": 1}):
        b = by[e["project_id"]]
        b["minutes"] += e["minutes"]
        b["amount_paise"] += amount(e)
        b["count"] += 1
        b["oldest"] = min(b["oldest"] or e["date"], e["date"])
    return by


@action("time.unbilled", "read", UnbilledIn, desc="How much billable time hasn't been invoiced yet, by project, and the oldest entry.")
async def time_unbilled(ctx, p: UnbilledIn):
    if p.project_id:
        await perm.project(ctx, p.project_id)
        pids = [p.project_id]
    else:
        pids = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    by = await unbilled_summary(ctx, pids)
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": list(by)}}, projection={"name": 1})}
    items = sorted(({"project_id": k, "project": names.get(k, ""), **v} for k, v in by.items()), key=lambda x: -x["amount_paise"])
    tot = sum(i["amount_paise"] for i in items)
    mins = sum(i["minutes"] for i in items)
    oldest = min((i["oldest"] for i in items), default=None)
    return {"items": items, "total_paise": tot, "minutes": mins, "oldest": oldest,
            "summary": (f"{inr(tot)} of unbilled time ({hm(mins)}) across {len(items)} project{'s' if len(items) != 1 else ''}"
                        + (f", oldest from {fmt_date(oldest)}." if oldest else ".")) if items else "No unbilled time."}


# ---------------- time onto invoices ----------------

class AddTime(P):
    project_id: str
    invoice_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    rounding: int = 0                 # 0, 6, 15 or 30 minutes, per entry, upwards
    group_by: str = "task"            # task | service | role | date | none
    timesheet: str = "none"           # full | link | none
    columns: list = ["date", "task", "note", "person"]
    entry_ids: Optional[list] = None  # a hand-picked set instead of a date range


def rounded(m, r):
    return int(math.ceil(m / r) * r) if r else int(m)


async def group_label(ctx, e, by, cache):
    if by == "task":
        if not e.get("task_id"):
            return "Professional time"
        if e["task_id"] not in cache:
            t = await ctx.data.tasks.get(e["task_id"])
            cache[e["task_id"]] = (t or {}).get("title") or "No task"
        return cache[e["task_id"]]
    if by == "service":
        if not e.get("service_id"):
            return "Professional time"
        if e["service_id"] not in cache:
            s = await ctx.data.services.get(e["service_id"])
            cache[e["service_id"]] = (s or {}).get("name") or "No service"
        return cache[e["service_id"]]
    if by == "role":
        return e.get("role") or "Professional time"
    if by == "date":
        return fmt_date(e["date"])
    return "Professional time"


def time_lines(groups):
    """groups: {(label, rate): minutes}. Lines whose totals add up exactly, whatever the grouping."""
    lines, by_rate = [], defaultdict(list)
    for (label, rate), mins in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        l = {"id": new_id()[:8], "name": label, "desc": f"{hm(mins)} at {inr(rate)}/hour", "qty": round(mins / 60, 2), "minutes": mins,
             "unit": "hour", "price_paise": rate, "kind": "time", "taxable": True, "adjust_paise": 0}
        lines.append(l)
        by_rate[rate].append(l)
    for rate, ls in by_rate.items():
        exact = sum(l["minutes"] for l in ls) * rate // 60
        floor_sum = sum(l["minutes"] * rate // 60 for l in ls)
        ls[-1]["adjust_paise"] = exact - floor_sum
    return lines


@action("invoices.add_unbilled_time", "internal", AddTime, roles=STAFF,
        desc="Put a project's unbilled time on a draft invoice: all of it or a date range, with rounding, grouping and an optional timesheet.")
async def invoices_add_time(ctx, p: AddTime):
    from app.domain.billing import money as M
    await limits.require(ctx, "time_billing")
    pr = await perm.project(ctx, p.project_id, act=True)
    if pr["_id"] in await on_retainer(ctx):
        raise AppError("invalid", "This project's time is billed through its retainer. Extra time goes on the retainer invoice.", 400)
    if p.rounding not in (0, 6, 15, 30):
        raise AppError("invalid", "Rounding is none, or up to 6, 15 or 30 minutes.", 400)
    if p.group_by not in ("task", "service", "role", "date", "none"):
        raise AppError("invalid", "Group by task, service, role or date.", 400)
    if p.timesheet not in ("full", "link", "none"):
        raise AppError("invalid", "Timesheet is full, link or none.", 400)
    f = {"project_id": pr["_id"], "billing_status": "unbilled", "invoice_id": None}
    if p.entry_ids:
        f["_id"] = {"$in": p.entry_ids}
    if p.date_from or p.date_to:
        f["date"] = {**({"$gte": iso_day(p.date_from)} if p.date_from else {}), **({"$lte": iso_day(p.date_to)} if p.date_to else {})}
    cands = await ctx.data.time_entries.find(f)
    if not cands:
        raise AppError("nothing", "There's no unbilled time on this project for those dates.", 400)
    if any((e.get("currency") or "INR") != "INR" for e in cands):
        raise AppError("invalid", "Some of this time is priced in another currency. Invoices are raised in rupees for now; "
                                  "change the project's rate card or bill this time by hand.", 400)
    if p.invoice_id:
        inv = await M.get_inv(ctx, p.invoice_id, act=True)
        if inv["status"] != "draft" or inv["project_id"] != pr["_id"]:
            raise AppError("invalid", "Time can only go on a draft invoice for the same project.", 400)
    else:
        dates = sorted(e["date"] for e in cands)
        inv = await M.new_invoice(ctx, pr, [], await due_in_days(ctx), f"Professional time — {fmt_date(dates[0])} to {fmt_date(dates[-1])}"
                                  if dates[0] != dates[-1] else f"Professional time — {fmt_date(dates[0])}")
    # Claim the entries for this invoice (two taps or two people can't put the same time on two invoices).
    claim = new_id()
    await ctx.data.time_entries.update_many({**f, "_id": {"$in": [e["_id"] for e in cands]}}, {"invoice_id": inv["_id"], "claim": claim})
    entries = await ctx.data.time_entries.find({"invoice_id": inv["_id"], "claim": claim})
    if not entries:
        raise AppError("nothing", "That time was just put on another invoice.", 409)
    groups, member, cache = defaultdict(int), {}, {}
    for e in entries:
        rm = rounded(e["minutes"], p.rounding)
        label = await group_label(ctx, e, p.group_by, cache)
        key = (label, int(e.get("rate_snapshot_paise") or 0))
        groups[key] += rm
        member[e["_id"]] = (key, rm)
    lines = time_lines(groups)
    line_of = {(l["name"], l["price_paise"]): l["id"] for l in lines}
    for e in entries:
        key, rm = member[e["_id"]]
        await ctx.data.time_entries.update({"_id": e["_id"]}, {"invoice_line_id": line_of[key], "billed_minutes": rm})
    inv["lines"] = list(inv.get("lines") or []) + lines
    inv["timesheet"] = {"mode": p.timesheet, "columns": [c for c in p.columns if c in ("date", "task", "note", "person")]}
    await M.save_invoice(ctx, inv)
    mins = sum(rm for _, rm in member.values())
    await log(ctx, pr["_id"], "invoice", f"{hm(mins)} of time added to a draft invoice", ref=inv["_id"])
    out = await M.view(ctx, inv)
    out["added"] = {"entries": len(entries), "minutes": mins, "lines": len(lines)}
    return out


class AddExp(P):
    project_id: str
    invoice_id: Optional[str] = None
    expense_ids: Optional[list] = None


@action("invoices.add_expenses", "internal", AddExp, roles=STAFF,
        desc="Put a project's billable expenses (with markup and receipts) on a draft invoice.")
async def invoices_add_expenses(ctx, p: AddExp):
    from app.domain.billing import money as M
    pr = await perm.project(ctx, p.project_id, act=True)
    f = {"project_id": pr["_id"], "billable": True, "invoice_id": None}
    if p.expense_ids:
        f["_id"] = {"$in": p.expense_ids}
    exps = await ctx.data.expenses.find(f)
    if not exps:
        raise AppError("nothing", "There are no billable expenses to add on this project.", 400)
    if p.invoice_id:
        inv = await M.get_inv(ctx, p.invoice_id, act=True)
        if inv["status"] != "draft" or inv["project_id"] != pr["_id"]:
            raise AppError("invalid", "Expenses can only go on a draft invoice for the same project.", 400)
    else:
        inv = await M.new_invoice(ctx, pr, [], await due_in_days(ctx), "Expenses")
    claim = new_id()
    await ctx.data.expenses.update_many({**f, "_id": {"$in": [x["_id"] for x in exps]}}, {"invoice_id": inv["_id"], "claim": claim})
    lines = []
    for x in await ctx.data.expenses.find({"invoice_id": inv["_id"], "claim": claim}):
        price = billed_expense(x)
        lid = new_id()[:8]
        lines.append({"id": lid, "name": f"{x.get('category') or 'Expense'}{': ' + x['note'] if x.get('note') else ''}", "desc": fmt_date(x["date"]),
                      "qty": 1, "price_paise": price, "kind": "expense", "expense_id": x["_id"], "receipt_upload_id": x.get("receipt_upload_id"),
                      "taxable": True})
        await ctx.data.expenses.update({"_id": x["_id"]}, {"invoice_line_id": lid})
    inv["lines"] = list(inv.get("lines") or []) + lines
    await M.save_invoice(ctx, inv)
    return await M.view(ctx, inv)


async def due_in_days(ctx):
    """Invoices made from time or expenses are due a few days after they're sent (Settings: invoice.payment_days, default 7)."""
    days = int(((await ctx.ws()).get("invoice") or {}).get("payment_days") or 7)
    return [{"id": new_id()[:8], "label": "Payment", "pct": 100, "due": {"type": "date", "date": (now() + timedelta(days=days)).isoformat()}}]


def billed_expense(x) -> int:
    return int(x["amount_paise"]) + int(x["amount_paise"]) * int(x.get("markup_bp") or 0) // 10000


# ---------------- invoice hooks (called from money.py) ----------------

async def on_invoice_issued(ctx, inv):
    """Sent invoice: its time is billed and locked; its expenses are billed."""
    entries = await ctx.data.time_entries.find({"invoice_id": inv["_id"], "billing_status": "unbilled"})
    if entries:
        await ctx.data.time_entries.update_many({"invoice_id": inv["_id"], "billing_status": "unbilled"},
                                                {"billing_status": "billed", "locked": True, "billed_at": now()})
        await emit(ctx, "time.billed", {"invoice_id": inv["_id"], "entries": len(entries), "minutes": sum(e["minutes"] for e in entries)},
                   inv["project_id"])
        for pid in {e["project_id"] for e in entries}:
            await after_time_change(ctx, pid)
    await ctx.data.expenses.update_many({"invoice_id": inv["_id"]}, {"billed": True})


async def release_invoice_time(ctx, inv, to="unbilled"):
    """Cancelled or fully credited invoice: its time goes back to unbilled (or is marked non-billable)."""
    to = to if to in ("unbilled", "non_billable") else "unbilled"
    n = 0
    for e in await ctx.data.time_entries.find({"invoice_id": inv["_id"]}):
        await ctx.data.time_entries.update({"_id": e["_id"]}, {"invoice_id": None, "invoice_line_id": None, "claim": None, "locked": False,
                                                                "billing_status": to, "billable": to != "non_billable", "billed_at": None})
        n += 1
    await ctx.data.expenses.update_many({"invoice_id": inv["_id"]}, {"invoice_id": None, "invoice_line_id": None, "billed": False, "claim": None})
    if n:
        await after_time_change(ctx, inv["project_id"])
    return n


async def on_lines_changed(ctx, inv, new_lines):
    """A line removed from a draft gives its time and expenses back."""
    keep = {l.get("id") for l in new_lines}
    for e in await ctx.data.time_entries.find({"invoice_id": inv["_id"]}):
        if e.get("invoice_line_id") not in keep:
            await ctx.data.time_entries.update({"_id": e["_id"]}, {"invoice_id": None, "invoice_line_id": None, "claim": None})
    for x in await ctx.data.expenses.find({"invoice_id": inv["_id"]}):
        if x.get("invoice_line_id") not in keep:
            await ctx.data.expenses.update({"_id": x["_id"]}, {"invoice_id": None, "invoice_line_id": None, "claim": None})


async def timesheet_rows(ctx, inv):
    ts = inv.get("timesheet") or {}
    if ts.get("mode") in (None, "none"):
        return None
    cols = ts.get("columns") or ["date", "task", "note", "person"]
    rows = await decorate(ctx, await ctx.data.time_entries.find({"invoice_id": inv["_id"]}, sort=[("date", 1)]))
    out = []
    for r in rows:
        o = {"hours": round((r.get("billed_minutes") or r["minutes"]) / 60, 2)}
        if "date" in cols:
            o["date"] = fmt_date(r["date"])
        if "task" in cols:
            o["task"] = r.get("task") or r.get("service") or ""
        if "note" in cols:
            o["note"] = r.get("note") or ""
        if "person" in cols:
            o["person"] = r.get("person") or ""
        out.append(o)
    return {"mode": ts["mode"], "columns": [c for c in ("date", "task", "note", "person") if c in cols] + ["hours"], "rows": out,
            "total_hours": round(sum(o["hours"] for o in out), 2)}


# ---------------- bulk invoice actions (4.8) ----------------

class InvFilter(P):
    ids: Optional[list] = None
    contact_id: Optional[str] = None
    project_id: Optional[str] = None
    status: Optional[str] = None      # draft | sent | partially_paid | paid | overdue | void
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    fy: Optional[str] = None


async def filtered_invoices(ctx, f: InvFilter):
    from app.domain.billing.money import item_state
    vis = [x["_id"] for x in await ctx.data.projects.find(perm.visible_filter(ctx), projection={"_id": 1})]
    q = {"project_id": {"$in": vis}}
    if f.ids:
        q["_id"] = {"$in": f.ids[:1000]}
    if f.contact_id:
        q["contact_id"] = f.contact_id
    if f.project_id:
        q["project_id"] = f.project_id if f.project_id in vis else "-"
    if f.fy:
        q["fy"] = f.fy
    if f.status and f.status != "overdue":
        q["status"] = f.status
    rows = await ctx.data.invoices.find(q, sort=[("created_at", -1)], limit=2000)
    out = []
    for r in rows:
        d = (r.get("sent_at") or r["created_at"])
        ds = d.astimezone(IST).date().isoformat() if hasattr(d, "astimezone") else str(d)[:10]
        if f.date_from and ds < iso_day(f.date_from) or f.date_to and ds > iso_day(f.date_to):
            continue
        if f.status == "overdue" and not any(item_state(s, r) == "overdue" for s in r["schedule"]):
            continue
        out.append(r)
    return out


@action("invoices.bulk_download", "internal", InvFilter, roles=STAFF,
        desc="Download many invoices as one ZIP of PDFs. It's built in the background and you get a link.")
async def invoices_bulk_download(ctx, p: InvFilter):
    await limits.require(ctx, "bulk_invoice_actions")
    rows = [r for r in await filtered_invoices(ctx, p) if r.get("number")]
    if not rows:
        raise AppError("nothing", "No sent invoices match. Drafts have no number yet, so they aren't included.", 400)
    ex = await ctx.data.exports.insert({"kind": "invoice_pdfs", "invoice_ids": [r["_id"] for r in rows], "status": "queued",
                                        "requested_by": ctx.user_id, "count": len(rows)})
    return {"ok": True, "export_id": ex["_id"], "count": len(rows),
            "summary": f"Building a ZIP of {len(rows)} invoice{'s' if len(rows) != 1 else ''}. You'll get a notification with the link."}


@action("exports.list", "read", roles=STAFF, desc="Your recent downloads (ZIPs of invoices).")
async def exports_list(ctx, p):
    rows = await ctx.data.exports.find({"requested_by": ctx.user_id}, sort=[("created_at", -1)], limit=20)
    return [dict(clean(r), link=f"/api/exports/{r['_id']}" if r["status"] == "ready" else None) for r in rows]


@action("invoices.bulk_remind", "external", InvFilter, roles=STAFF,
        desc="Send payment reminders for many invoices at once. Invoices with nothing due are skipped.")
async def invoices_bulk_remind(ctx, p: InvFilter):
    from app.domain.billing.money import RemindIn, invoices_remind
    await limits.require(ctx, "bulk_invoice_actions")
    sent = skipped = 0
    for r in await filtered_invoices(ctx, p):
        if r["status"] in ("draft", "void", "paid"):
            skipped += 1
            continue
        try:
            await invoices_remind(ctx, RemindIn(id=r["_id"], channel="both"))
            sent += 1
        except AppError:
            skipped += 1
    return {"ok": True, "sent": sent, "skipped": skipped,
            "summary": f"Reminders sent for {sent} invoice{'s' if sent != 1 else ''}" + (f", {skipped} skipped (nothing due)." if skipped else ".")}


@action("invoices.export", "read", InvFilter, roles=STAFF, desc="Invoices as a CSV for your CA.")
async def invoices_export(ctx, p: InvFilter):
    rows = await filtered_invoices(ctx, p)
    names = {x["_id"]: x["name"] for x in await ctx.data.projects.find({"_id": {"$in": list({r["project_id"] for r in rows})}})}
    contacts = {x["_id"]: x for x in await ctx.data.contacts.find({"_id": {"$in": [r.get("contact_id") for r in rows if r.get("contact_id")]}})}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Number", "Date", "Client", "Company", "Project", "Status", "Subtotal (₹)", "Discount (₹)", "CGST (₹)", "SGST (₹)", "IGST (₹)",
                "Total (₹)", "Paid (₹)", "Due (₹)", "Financial year"])
    for r in rows:
        t = r["totals"]
        c = contacts.get(r.get("contact_id"), {})
        d = r.get("sent_at") or r["created_at"]
        w.writerow([r.get("number") or "Draft", fmt_date(d), c.get("name", ""), c.get("company", ""), names.get(r["project_id"], ""),
                    r["status"].replace("_", " "), t["subtotal"] / 100, (t["discount"] + t.get("promo", 0)) / 100, t["cgst"] / 100,
                    t["sgst"] / 100, t["igst"] / 100, t["total"] / 100, t["paid"] / 100, t["due"] / 100, r.get("fy") or ""])
    return {"filename": f"invoices-{now():%Y-%m-%d}.csv", "csv": buf.getvalue(), "count": len(rows)}
