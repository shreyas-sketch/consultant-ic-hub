"""Fuzzers kept as tests. Each found real bugs once; they stay so the bugs stay fixed.

- authz: every action x restricted persona (member, collaborator, manager, another
  practice's owner) x ids of records that persona must not see. Fails on a leak or a write.
- crash: every action as the owner with hostile inputs. Fails on any 5xx.
- routes: every other HTTP route with junk path params and bodies. Fails on any 5xx.
"""
import json  # noqa: F401
import random
import re

import httpx

from app.main import app
from app.db import get_db
from app.domain.registry import ACTIONS
from app.qa.seed import PERSONAS, seed

ID_FIELDS = {"id", "project_id", "invoice_id", "file_id", "contact_id", "task_id", "retainer_id", "estimate_id",
             "session_id", "automation_id", "run_id", "claim_id", "thread_id", "budget_id", "template_id", "item_id",
             "approval_id", "period_id", "rate_card_id", "service_id", "line_id", "form_id", "user_id", "member_id",
             "note_id", "expense_id", "entry_id", "type_id", "view_id", "stage_id", "upload_id", "agent_run_id"}
# collection each id-ish field most likely points at
FIELD_COLL = {"project_id": "projects", "invoice_id": "invoices", "file_id": "client_files", "contact_id": "contacts",
              "task_id": "tasks", "retainer_id": "retainers", "estimate_id": "estimates", "session_id": "sessions",
              "automation_id": "automations", "run_id": "automation_runs", "claim_id": "payment_claims",
              "thread_id": "threads", "budget_id": "budgets", "expense_id": "expenses", "entry_id": "time_entries",
              "note_id": "notes", "approval_id": "approvals", "upload_id": "uploads"}
# for "id", guess from the action's prefix
PREFIX_COLL = {"projects": "projects", "invoices": "invoices", "files": "client_files", "contacts": "contacts", "tasks": "tasks",
               "retainers": "retainers", "estimates": "estimates", "sessions": "sessions", "automations": "automations",
               "approvals": "approvals", "time": "time_entries", "expenses": "expenses", "notes": "notes", "budgets": "budgets",
               "client_tasks": "tasks", "messages": "messages", "quotes": "client_files", "payments": "invoices",
               "templates": "templates", "lead_forms": "lead_forms", "session_types": "session_types", "promo_codes": "promo_codes",
               "recurring": "recurring_invoices", "rate_cards": "rate_cards", "services": "services", "uploads": "uploads",
               "stages": "stages", "views": "views", "task_templates": "task_templates", "mcp": "mcp_tokens"}

SKIP = {"workspace.delete"}  # irreversible for the rest of the run





def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


async def login(persona):
    c = client()
    r = await c.post("/api/qa/login", json={"persona": persona})
    assert r.status_code == 200, r.text
    return c


def project_of(coll, doc):
    if coll == "projects":
        return doc["_id"]
    if doc.get("project_id"):
        return doc["project_id"]
    if doc.get("project_ids"):
        return doc["project_ids"][0]
    return None


async def run_authz_fuzz():
    await seed()
    db = get_db()
    ws = await db.workspaces.find_one({"slug": "mehta-growth"})
    wsid = ws["_id"]
    # A second practice: its owner must never reach practice 1's data.
    from app.auth import login_phone, start_session
    from fastapi import Response
    await db.invites.insert_one({"_id": "x", "phone": "+919700000001", "name": "Other", "status": "invited", "practice_name": "Other Co"})
    other = await login_phone("+919700000001")
    oc = client()
    resp = Response()
    from app.auth import default_workspace
    await start_session(resp, other, await default_workspace(other))
    for k, v in resp.headers.items():
        if k == "set-cookie":
            name, val = v.split(";")[0].split("=", 1)
            oc.cookies.set(name, val)

    personas = {p: await login(p) for p in ("member", "collaborator", "manager")}
    personas["other_practice"] = oc
    users = {p: await db.users.find_one({"phone": PERSONAS[p]}) for p in ("member", "collaborator", "manager")}
    mships = {p: await db.memberships.find_one({"workspace_id": wsid, "user_id": users[p]["_id"]}) for p in users}

    projects = await db.projects.find({"workspace_id": wsid}).to_list(None)

    def visible(persona, pid):
        if persona == "other_practice":
            return False
        if persona == "manager":
            return True
        p = next((x for x in projects if x["_id"] == pid), None)
        if not p:
            return True
        u = users[persona]["_id"]
        if persona == "collaborator":
            return pid in (mships[persona].get("project_ids") or [])
        return p.get("owner_id") == u or u in (p.get("team_ids") or [])

    # candidate ids per collection, each with its project
    cands = {}
    for coll in set(FIELD_COLL.values()) | set(PREFIX_COLL.values()):
        docs = await db[coll].find({"workspace_id": wsid}).to_list(400)
        cands[coll] = [(d["_id"], project_of(coll, d)) for d in docs]

    findings = []
    for name, a in sorted(ACTIONS.items()):
        if name in SKIP or not a.model:
            continue
        fields = set(a.model.model_fields)
        idf = [f for f in fields if f in ID_FIELDS]
        if not idf:
            continue
        for persona, c in personas.items():
            role = "owner" if persona == "other_practice" else persona
            if role not in a.roles:
                continue
            tried = 0
            for f in idf:
                coll = FIELD_COLL.get(f) or (PREFIX_COLL.get(name.split(".")[0]) if f == "id" else None)
                if not coll:
                    continue
                for rid, pid in cands.get(coll, []):
                    if visible(persona, pid) and coll != "projects" and pid is None and persona != "other_practice":
                        continue  # workspace-level record a staff role may legitimately see
                    if visible(persona, pid):
                        continue
                    body = {f: rid}
                    # fill other required fields with plausible values
                    for ff, info in a.model.model_fields.items():
                        if ff in body or not info.is_required():
                            continue
                        ann = str(info.annotation)
                        body[ff] = rid if ff in ID_FIELDS else (1 if "int" in ann else True if "bool" in ann else [] if "list" in ann else {} if "dict" in ann else "x")
                    before = await db[coll].find_one({"_id": rid})
                    r = await c.post(f"/api/a/{name}", json=body)
                    after = await db[coll].find_one({"_id": rid})
                    tried += 1
                    leak = r.status_code == 200 and (pid and pid in r.text or rid in r.text)
                    changed = before != after and a.level != "read"
                    crash = r.status_code >= 500
                    if leak or changed or crash:
                        findings.append({"action": name, "level": a.level, "persona": persona, "field": f, "coll": coll,
                                         "status": r.status_code, "leak": bool(leak), "changed": changed, "crash": crash,
                                         "snippet": r.text[:160]})
                    if tried >= 3:
                        break
                if tried >= 3:
                    break
    return findings



CRASH_SKIP = {"workspace.delete", "team.remove"}

def junk_for(ann, name):
    a = str(ann)
    opts = ["", "nope", "0" * 40, -1, 0, 10**12, None, [], {}, "2026-13-45", "<script>", {"$gt": ""}, ["x"], True]
    return random.choice(opts)

async def run_crash_fuzz():
    random.seed(7)
    await seed()
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")
    assert (await c.post("/api/qa/login", json={"persona": "owner"})).status_code == 200
    db = get_db()
    some = {k: [d["_id"] for d in await db[k].find({}).to_list(5)] for k in ("projects", "invoices", "client_files", "contacts", "tasks", "retainers", "estimates")}
    crashes = {}
    for name, a in sorted(ACTIONS.items()):
        if name in CRASH_SKIP:
            continue
        fields = a.model.model_fields if a.model else {}
        bodies = [{}, {k: "does-not-exist" for k in fields}]
        for _ in range(6):
            bodies.append({k: junk_for(f.annotation, k) for k, f in fields.items()})
        # realistic ids with junk elsewhere
        if "project_id" in fields:
            bodies.append({k: (some["projects"][0] if k == "project_id" else junk_for(f.annotation, k)) for k, f in fields.items()})
        for b in bodies:
            r = await c.post(f"/api/a/{name}", json=b)
            if r.status_code >= 500:
                crashes.setdefault(name, []).append(b)
                break
    return crashes


BODIES = [None, {}, {"x": 1}, {"phone": "abc", "code": "x", "data": "data:,", "item_id": "x", "block_id": "x", "start": "nope",
          "contact": "x", "answers": "x", "picks": "x", "email": {"$gt": ""}, "id": [], "jsonrpc": "2.0", "method": "tools/call",
          "params": {"name": "nope"}}, ["list"], "string"]

async def run_route_fuzz():
    await seed()
    db = get_db()
    ws = await db.workspaces.find_one({"slug": "mehta-growth"})
    f = await db.client_files.find_one({"workspace_id": ws["_id"]})
    inv = await db.invoices.find_one({"workspace_id": ws["_id"], "token": {"$exists": True}})
    real = {"ws_slug": "mehta-growth", "slug": "mehta-growth", "tok": f["token"], "token": inv["token"]}
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")
    staff = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")
    await staff.post("/api/qa/login", json={"persona": "staff"})
    owner = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")
    await owner.post("/api/qa/login", json={"persona": "owner"})
    crashes = []
    n = 0
    def walk(routes, prefix=""):
        for r in routes:
            orig = getattr(r, "original_router", None)
            if orig is not None:
                yield from walk(orig.routes)
            else:
                yield r, getattr(r, "path", "")
    for r, path in walk(app.routes):
        r_methods = getattr(r, "methods", set()) or set()
        if not path or path.startswith(("/api/a/", "/api/qa")) or path == "/{path:path}":
            continue
        for method in sorted(r_methods - {"HEAD", "OPTIONS"}):
            params = re.findall(r"{(\w+)(?::\w+)?}", path)
            variants = [{p: "junk" for p in params}, {p: real.get(p, "junk") for p in params}]
            for pv in variants:
                url = path
                for p, v in pv.items():
                    url = re.sub(r"{%s(?::\w+)?}" % p, v, url)
                for who in (anon, owner, staff):
                    for b in (BODIES if method != "GET" else [None]):
                        q = "?domain=x&date_from=nope&block_id=x&code=x&state=x&limit=5" if method == "GET" else ""
                        kw = {} if b is None else {"json": b}
                        resp = await who.request(method, url + q, **kw)
                        n += 1
                        if resp.status_code >= 500:
                            crashes.append((method, url, json.dumps(b)[:80], resp.status_code))
                            break
    return crashes


async def test_no_action_leaks_or_changes_records_a_persona_must_not_see():
    findings = await run_authz_fuzz()
    assert not findings, findings[:5]


async def test_no_action_crashes_on_hostile_input():
    crashes = await run_crash_fuzz()
    assert not crashes, list(crashes.items())[:5]


async def test_no_http_route_crashes_on_junk():
    crashes = await run_route_fuzz()
    assert not crashes, crashes[:5]
