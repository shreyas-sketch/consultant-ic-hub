"""Automations: saved rules (trigger -> steps), their runs, test runs and
"Why didn't this run?"."""
import copy
from typing import Optional

from actions import perm
from actions.registry import ADMINS, P, action
from automations.engine import ACTIONS as STEP_ACTIONS, CONDITIONS, TRIGGERS, advance, execute, start_run, step_at, validate_steps
from core import limits
from core.util import AppError, clean, new_id, not_found, now


@action("automations.meta", "read", agent_ok=False, desc="Triggers, actions and conditions the builder offers.")
async def meta(ctx, p):
    return {"triggers": TRIGGERS, "actions": STEP_ACTIONS, "conditions": CONDITIONS,
            "note": "If a later condition is met early, earlier steps still run to their end or time limit."}


@action("automations.list", "read", desc="All automations with their recent runs.")
async def autos_list(ctx, p):
    out = []
    for a in await ctx.data.automations.find({}, sort=[("created_at", 1)]):
        o = clean(a)
        o["runs_total"] = await ctx.data.automation_runs.count({"automation_id": a["_id"]})
        o["runs_active"] = await ctx.data.automation_runs.count({"automation_id": a["_id"], "status": {"$in": ["running", "waiting", "waiting_approval"]}})
        last = await ctx.data.automation_runs.find_one({"automation_id": a["_id"]}, sort=[("created_at", -1)])
        o["last_run"] = clean(last)["created_at"] if last else None
        out.append(o)
    return out


class IdIn(P):
    id: str


@action("automations.get", "read", IdIn, desc="One automation.")
async def autos_get(ctx, p: IdIn):
    a = await ctx.data.automations.get(p.id)
    if not a:
        raise not_found("That automation")
    return clean(a)


class AutoIn(P):
    id: Optional[str] = None
    name: str
    trigger: dict
    steps: list
    project_types: list = []
    active: bool = False


async def save(ctx, d):
    if (d.get("trigger") or {}).get("type") not in TRIGGERS:
        raise AppError("invalid", "Choose a trigger.", 400)
    steps = copy.deepcopy(d["steps"])
    validate_steps(steps)
    doc = {"name": d["name"].strip()[:80] or "Automation", "trigger": d["trigger"], "steps": steps,
           "project_types": d.get("project_types") or [], "active": bool(d.get("active"))}
    if doc["active"]:
        n = await ctx.data.automations.count({"active": True, **({"_id": {"$ne": d["id"]}} if d.get("id") else {})})
        await limits.check_count(ctx, "active_automations", n)
    if d.get("id"):
        await ctx.data.automations.update({"_id": d["id"]}, doc)
        return await ctx.data.automations.get(d["id"])
    return await ctx.data.automations.insert(doc)


@action("automations.save", "internal", AutoIn, roles=ADMINS | {"manager"}, desc="Create or update an automation. Runs already going keep their old steps.")
async def autos_save(ctx, p: AutoIn):
    return clean(await save(ctx, p.model_dump()))


class SpecIn(P):
    spec: dict


@action("automations.create_from_spec", "internal", SpecIn, desc="Save an automation drafted from a plain-language request (switched off).")
async def autos_from_spec(ctx, p: SpecIn):
    d = dict(p.spec, active=False, id=None)
    d.setdefault("name", "Drafted automation")
    a = await save(ctx, d)
    await ctx.data.automations.update({"_id": a["_id"]}, {"drafted_by": ctx.actor})
    return clean(await ctx.data.automations.get(a["_id"]))


class ToggleIn(P):
    id: str
    active: bool


@action("automations.toggle", "internal", ToggleIn, roles=ADMINS | {"manager"}, desc="Switch an automation on or off.")
async def autos_toggle(ctx, p: ToggleIn):
    a = await ctx.data.automations.get(p.id)
    if not a:
        raise not_found("That automation")
    if p.active:
        await limits.check_count(ctx, "active_automations", await ctx.data.automations.count({"active": True, "_id": {"$ne": p.id}}))
    await ctx.data.automations.update({"_id": p.id}, {"active": p.active})
    return {"ok": True}


@action("automations.delete", "destructive", IdIn, roles=ADMINS, agent_ok=False, desc="Delete an automation.")
async def autos_delete(ctx, p: IdIn):
    await ctx.data.automations.soft_delete({"_id": p.id})
    return {"ok": True}


class RunsIn(P):
    automation_id: Optional[str] = None
    project_id: Optional[str] = None
    limit: int = 50


@action("automations.runs", "read", RunsIn, desc="Automation runs with every step's result.")
async def autos_runs(ctx, p: RunsIn):
    f = {}
    if p.automation_id:
        f["automation_id"] = p.automation_id
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    return clean(await ctx.data.automation_runs.find(f, sort=[("created_at", -1)], limit=min(p.limit, 200)))


class ManualIn(P):
    automation_id: str
    project_id: str


@action("automations.run_manual", "internal", ManualIn, desc="Run an automation on a project now, by hand.")
async def autos_run_manual(ctx, p: ManualIn):
    await perm.project(ctx, p.project_id, act=True)
    a = await ctx.data.automations.get(p.automation_id)
    if not a:
        raise not_found("That automation")
    r = await start_run(ctx, a, p.project_id, {"_id": new_id(), "type": "manual", "payload": {}})
    await execute(r)
    return clean(await ctx.data.automation_runs.get(r["_id"]))


class RunIdIn(P):
    run_id: str


@action("automations.cancel_run", "internal", RunIdIn, desc="Cancel a running automation on a project.")
async def autos_cancel(ctx, p: RunIdIn):
    r = await ctx.data.automation_runs.get(p.run_id)
    if not r:
        raise not_found("That run")
    await perm.project(ctx, r["project_id"], act=True)
    await ctx.data.automation_runs.update({"_id": r["_id"]}, {"status": "cancelled", "ended_reason": "Cancelled by hand"})
    for a in await ctx.data.approvals.find({"run_id": r["_id"], "status": "pending"}):
        await ctx.data.approvals.update({"_id": a["_id"]}, {"status": "skipped"})
    return {"ok": True}


@action("automations.skip_step", "internal", RunIdIn, desc="Skip the step a run is on (not condition steps).")
async def autos_skip(ctx, p: RunIdIn):
    r = await ctx.data.automation_runs.get(p.run_id)
    if not r or r["status"] not in ("waiting", "waiting_approval", "running"):
        raise not_found("That run")
    await perm.project(ctx, r["project_id"], act=True)
    steps = r["snapshot"]["steps"]
    st = step_at(steps, r["path"])
    if st["type"] == "condition":
        raise AppError("invalid", "Condition steps can't be skipped.", 400)
    nxt = advance(steps, r["path"])
    await ctx.data.automation_runs.update({"_id": r["_id"]}, {"path": nxt, "status": "running" if nxt else "done", "wake_at": now(),
                                                              "waking_from": None, "waiting_for": None},
                                          raw={"$push": {"log": {"step_id": st["id"], "status": "skipped", "text": "Skipped by hand", "at": now()}}})
    for a in await ctx.data.approvals.find({"run_id": r["_id"], "step_id": st["id"], "status": "pending"}):
        await ctx.data.approvals.update({"_id": a["_id"]}, {"status": "skipped"})
    return {"ok": True}


class WhyIn(P):
    automation_id: str
    project_id: str


@action("automations.why", "read", WhyIn, desc="\"Why didn't this run?\" for one automation on one project, in plain words.")
async def autos_why(ctx, p: WhyIn):
    pr = await perm.project(ctx, p.project_id)
    a = await ctx.data.automations.get(p.automation_id)
    if not a:
        raise not_found("That automation")
    runs = await ctx.data.automation_runs.find({"automation_id": a["_id"], "project_id": pr["_id"]}, sort=[("created_at", -1)])
    if runs:
        r = runs[0]
        if r["status"] == "cancelled":
            return {"reason": "cancelled", "text": f"It started, but the run was cancelled ({r.get('ended_reason', 'by hand')})."}
        if r["status"] == "waiting_approval":
            return {"reason": "waiting_approval", "text": "It's running. A step is waiting for your OK in Approvals."}
        if r["status"] == "waiting":
            return {"reason": "waiting", "text": "It's running and is on a wait step right now."}
        if r["status"] == "failed":
            return {"reason": "failed", "text": "It ran but a step failed: " + (r["log"][-1]["text"] if r.get("log") else "unknown error") + "."}
        return {"reason": "ran", "text": f"It did run ({r['status']})."}
    if not a.get("active"):
        return {"reason": "off", "text": "The automation is switched off."}
    if a.get("project_types") and pr.get("type") not in a["project_types"]:
        return {"reason": "type", "text": f"This project's type is \"{pr.get('type') or 'not set'}\", but the automation only runs for "
                                          f"{', '.join(a['project_types'])}."}
    t = a["trigger"]["type"]
    ev = await ctx.data.events.find_one({"project_id": pr["_id"], "type": "session.scheduled" if t == "session.starts" else t})
    if not ev:
        return {"reason": "no_trigger", "text": f"The trigger never happened on this project: {TRIGGERS.get(t, t)}."}
    if ev.get("created_at") and a.get("created_at") and ev["created_at"] < a["created_at"]:
        return {"reason": "before", "text": "The trigger happened before this automation was created."}
    return {"reason": "filter", "text": "The trigger happened but didn't match this automation's settings (for example the form or session type)."}


class TestIn(P):
    automation_id: Optional[str] = None
    spec: Optional[dict] = None
    project_id: Optional[str] = None


@action("automations.test_run", "read", TestIn, desc="Run an automation on a sample project with a fast clock. Nothing is sent.")
async def autos_test(ctx, p: TestIn):
    a = await ctx.data.automations.get(p.automation_id) if p.automation_id else dict(p.spec or {}, _id="test")
    if not a or not a.get("steps"):
        raise not_found("That automation")
    steps = copy.deepcopy(a["steps"])
    validate_steps(steps)
    pid = p.project_id
    if not pid:
        pr = await ctx.data.projects.find_one({"archived": False, **perm.visible_filter(ctx)}, sort=[("created_at", -1)])
        if not pr:
            raise AppError("no_sample", "Add one project first so the test has something to run on.", 400)
        pid = pr["_id"]
    run = {"_id": "test-" + new_id()[:8], "workspace_id": ctx.ws_id, "automation_id": a["_id"], "name": a.get("name", "Test"),
           "project_id": pid, "snapshot": {"trigger": a.get("trigger"), "steps": steps}, "path": [0], "log": [], "vars": {},
           "trigger_payload": {}}
    await execute(run, dry=True)
    return {"project_id": pid, "log": clean(run["log"]), "ends": run.get("status")}
