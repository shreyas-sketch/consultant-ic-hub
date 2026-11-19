"""Contacts, projects and pipeline, notes, tags, tasks, time, lead capture."""
import re
from datetime import timedelta
from typing import Optional

from app.domain import perm
from app.domain.registry import ADMINS, STAFF, P, action
from app.core import limits
from app.core.events import audit, emit, log
from app.core.util import AppError, aware, clean, new_id, not_found, now

# ---------------- contacts ----------------


def first_name(name):
    return (name or "").strip().split(" ")[0] if name else ""


def norm_phone_soft(p):
    d = re.sub(r"\D", "", p or "")
    if len(d) == 10:
        d = "91" + d
    return ("+" + d) if len(d) >= 11 else ""


class ContactIn(P):
    name: str
    phone: str = ""
    email: str = ""
    company: str = ""
    role: str = ""
    source: str = ""
    tags: list = []
    notes: str = ""


async def upsert_contact(ctx, c: dict):
    phone = norm_phone_soft(c.get("phone"))
    email = (c.get("email") or "").strip().lower()
    if not (phone or email or (c.get("name") or "").strip()):
        raise AppError("invalid", "Please add at least a name, phone or email.", 400)
    existing = None
    if phone:
        existing = await ctx.data.contacts.find_one({"phone": phone})
    if not existing and email:
        existing = await ctx.data.contacts.find_one({"email": email})
    if existing:
        upd = {k: v for k, v in {"email": email, "phone": phone, "company": c.get("company"), "role": c.get("role")}.items()
               if v and not existing.get(k)}
        if upd:
            await ctx.data.contacts.update({"_id": existing["_id"]}, upd)
            existing.update(upd)
        return existing, False
    doc = {"name": (c.get("name") or email or phone).strip()[:120], "first_name": first_name(c.get("name")), "phone": phone,
           "email": email, "company": (c.get("company") or "").strip(), "role": (c.get("role") or "").strip(),
           "source": c.get("source") or "", "tags": c.get("tags") or [], "notes": c.get("notes") or "", "enrichment": {}}
    return await ctx.data.contacts.insert(doc), True


@action("contacts.create", "internal", ContactIn, roles=STAFF, desc="Add a contact (lead or client).")
async def contacts_create(ctx, p: ContactIn):
    c, created = await upsert_contact(ctx, p.model_dump())
    return clean(c)


class ContactSearch(P):
    q: str = ""
    tag: str = ""
    limit: int = 50
    skip: int = 0


@action("contacts.search", "read", ContactSearch, desc="Search contacts by name, phone, email or company.")
async def contacts_search(ctx, p: ContactSearch):
    f = {}
    if p.q:
        rx = {"$regex": re.escape(p.q.strip()), "$options": "i"}
        f["$or"] = [{"name": rx}, {"phone": rx}, {"email": rx}, {"company": rx}]
    if p.tag:
        f["tags"] = p.tag
    if ctx.role not in perm.SEE_ALL:
        vis = await ctx.data.projects.find(perm.visible_filter(ctx), projection={"contact_ids": 1})
        ids = {cid for pr in vis for cid in pr.get("contact_ids", [])}
        f["_id"] = {"$in": list(ids)}
    rows = await ctx.data.contacts.find(f, sort=[("name", 1)], limit=min(p.limit, 200), skip=p.skip)
    return {"items": clean(rows), "total": await ctx.data.contacts.count(f)}


class IdIn(P):
    id: str


@action("contacts.get", "read", IdIn, desc="One contact with all their projects, payments and total value.")
async def contacts_get(ctx, p: IdIn):
    c = await ctx.data.contacts.get(p.id)
    if not c:
        raise not_found("That contact")
    projects = [pr for pr in await ctx.data.projects.find({"contact_ids": c["_id"]}, sort=[("created_at", -1)]) if perm.can_see(ctx, pr)]
    if ctx.role not in perm.SEE_ALL and not projects:
        raise not_found("That contact")
    pids = [pr["_id"] for pr in projects]
    received = sum(r["amount_paise"] for r in await ctx.data.ledger.find({"project_id": {"$in": pids}, "type": "payment"}))
    refunds = sum(r["amount_paise"] for r in await ctx.data.ledger.find({"project_id": {"$in": pids}, "type": "refund"}))
    msgs = await ctx.data.messages.count({"project_id": {"$in": pids}})
    out = clean(c)
    out.update({"projects": clean(projects), "total_value_paise": sum(pr.get("value_paise", 0) for pr in projects),
                "received_paise": received - refunds, "messages": msgs})
    return perm.strip_money(ctx, out)


class ContactUpdate(P):
    id: str
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[list] = None
    notes: Optional[str] = None


@action("contacts.update", "internal", ContactUpdate, roles=STAFF, desc="Update a contact's details.")
async def contacts_update(ctx, p: ContactUpdate):
    c = await ctx.data.contacts.get(p.id)
    if not c:
        raise not_found("That contact")
    ch = {k: v for k, v in p.model_dump(exclude={"id"}).items() if v is not None}
    if "phone" in ch:
        ch["phone"] = norm_phone_soft(ch["phone"])
    if "email" in ch:
        ch["email"] = ch["email"].strip().lower()
    if "name" in ch:
        ch["first_name"] = first_name(ch["name"])
    await ctx.data.contacts.update({"_id": c["_id"]}, ch)
    return clean(await ctx.data.contacts.get(c["_id"]))


class ImportRows(P):
    rows: list
    create_projects: bool = False
    source: str = "Import"


@action("contacts.import_csv", "internal", ImportRows, roles=ADMINS | {"manager"}, agent_ok=False,
        desc="Import contacts from CSV rows (name, phone, email, company).")
async def contacts_import(ctx, p: ImportRows):
    if len(p.rows) > 2000:
        raise AppError("too_many", "Please import at most 2,000 rows at a time.", 400)
    created = matched = skipped = 0
    for r in p.rows:
        r = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in r.items()}
        if not (r.get("name") or r.get("phone") or r.get("email")):
            skipped += 1
            continue
        c, new = await upsert_contact(ctx, {"name": r.get("name"), "phone": r.get("phone") or r.get("mobile"),
                                            "email": r.get("email"), "company": r.get("company"), "source": p.source})
        created += new
        matched += (not new)
        if p.create_projects and new:
            await create_project(ctx, {"name": f"{c['name']} — enquiry", "contact_ids": [c["_id"]], "source": p.source})
    return {"created": created, "matched": matched, "skipped": skipped}


# ---------------- projects ----------------

async def first_stage(ctx):
    return await ctx.data.stages.find_one({}, sort=[("order", 1)])


async def create_project(ctx, d: dict):
    st = None
    if d.get("stage_id"):
        st = await ctx.data.stages.get(d["stage_id"])
    st = st or await first_stage(ctx)
    doc = {"name": (d.get("name") or "New project").strip()[:120], "contact_ids": d.get("contact_ids", []),
           "type": d.get("type") or "", "stage_id": st["_id"], "value_paise": int(d.get("value_paise") or 0),
           "start_date": d.get("start_date"), "end_date": d.get("end_date"), "source": d.get("source") or "",
           "utm": d.get("utm") or {}, "tags": d.get("tags") or [], "owner_id": d.get("owner_id") or ctx.user_id,
           "team_ids": d.get("team_ids") or [], "booked": False, "archived": False, "archived_reason": None,
           "custom": d.get("custom") or {}, "shared_details": {}, "portal_link_on": True, "last_activity_at": now(),
           "stage_entered_at": now()}
    pr = await ctx.data.projects.insert(doc)
    await log(ctx, pr["_id"], "project", f"Project created in {st['name']}")
    await emit(ctx, "project.created", {"source": doc["source"]}, pr["_id"])
    return pr


class ProjectIn(P):
    name: str
    contact_ids: list = []
    contact: Optional[dict] = None  # create a contact inline
    type: str = ""
    stage_id: Optional[str] = None
    value_paise: int = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    source: str = ""
    tags: list = []
    owner_id: Optional[str] = None


@action("projects.create", "internal", ProjectIn, roles=STAFF, desc="Create a project (starts as an opportunity).")
async def projects_create(ctx, p: ProjectIn):
    if p.value_paise < 0:
        raise AppError("invalid", "Project value can't be negative.", 400)
    d = p.model_dump()
    if p.contact:
        c, _ = await upsert_contact(ctx, p.contact)
        d["contact_ids"] = list(dict.fromkeys(d["contact_ids"] + [c["_id"]]))
    return clean(await create_project(ctx, d))


class ProjectSearch(P):
    q: str = ""
    stage_id: Optional[str] = None
    type: Optional[str] = None
    tag: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[str] = None
    archived: bool = False
    booked: Optional[bool] = None
    waiting_on_client: Optional[bool] = None
    created_from: Optional[str] = None
    created_to: Optional[str] = None
    sort: str = "-last_activity_at"
    limit: int = 200
    skip: int = 0


async def _project_filter(ctx, p: ProjectSearch, with_stage=True):
    f = dict(perm.visible_filter(ctx))
    f["archived"] = bool(p.archived)
    for k in ("type", "source", "owner_id"):
        if getattr(p, k):
            f[k] = getattr(p, k)
    if p.tag:
        f["tags"] = p.tag
    if p.booked is not None:
        f["booked"] = p.booked
    if p.waiting_on_client:
        f["waiting_on_client"] = True
    if with_stage and p.stage_id:
        f["stage_id"] = p.stage_id
    if p.created_from or p.created_to:
        rng = {}
        if p.created_from:
            rng["$gte"] = aware(p.created_from)
        if p.created_to:
            rng["$lte"] = aware(p.created_to)
        f["created_at"] = rng
    if p.q:
        rx = {"$regex": re.escape(p.q.strip()), "$options": "i"}
        cids = [c["_id"] for c in await ctx.data.contacts.find({"$or": [{"name": rx}, {"email": rx}, {"phone": rx}, {"company": rx}]})]
        ors = [{"name": rx}, {"contact_ids": {"$in": cids}}]
        f = {"$and": [f, {"$or": ors}]} if "$or" in f else dict(f, **{"$or": ors})
    return f


@action("projects.search", "read", ProjectSearch, desc="Search projects with filters. Returns items and stage counts.")
async def projects_search(ctx, p: ProjectSearch):
    f = await _project_filter(ctx, p)
    key = p.sort.lstrip("-")
    rows = await ctx.data.projects.find(f, sort=[(key, -1 if p.sort.startswith("-") else 1)], limit=min(p.limit, 500), skip=p.skip)
    cids = {c for r in rows for c in r.get("contact_ids", [])}
    contacts = {c["_id"]: c for c in await ctx.data.contacts.find({"_id": {"$in": list(cids)}})}
    items = []
    for r in rows:
        o = clean(r)
        o["contacts"] = [{"id": c, "name": contacts[c]["name"], "phone": contacts[c].get("phone"), "email": contacts[c].get("email")}
                         for c in r.get("contact_ids", []) if c in contacts]
        items.append(o)
    base = await _project_filter(ctx, p, with_stage=False)
    counts = {}
    for s in await ctx.data.stages.find({}):
        counts[s["_id"]] = await ctx.data.projects.count(dict(base, stage_id=s["_id"]) if "$and" not in base else {"$and": [base, {"stage_id": s["_id"]}]})
    total = await ctx.data.projects.count(f)
    return perm.strip_money(ctx, {"items": items, "total": total, "stage_counts": counts})


@action("projects.get", "read", IdIn, desc="Everything about one project: details, contacts, activity, files, tasks, payments, sessions.")
async def projects_get(ctx, p: IdIn):
    pr = await perm.project(ctx, p.id)
    out = clean(pr)
    out["contacts"] = clean(await ctx.data.contacts.find({"_id": {"$in": pr.get("contact_ids", [])}}))
    out["stage"] = clean(await ctx.data.stages.get(pr["stage_id"]))
    out["activity"] = clean(await ctx.data.activity.find({"project_id": pr["_id"]}, sort=[("at", -1)], limit=150))
    out["files"] = [{"id": f["id"], "title": f.get("title"), "status": f.get("status"), "version": f.get("version"),
                     "sent_at": f.get("sent_at"), "token": f.get("token"), "kind": f.get("kind", "file")}
                    for f in clean(await ctx.data.client_files.find({"project_id": pr["_id"]}, sort=[("created_at", -1)]))]
    out["tasks"] = clean(await ctx.data.tasks.find({"project_id": pr["_id"]}, sort=[("done", 1), ("due_at", 1)]))
    out["notes"] = clean(await ctx.data.notes.find({"project_id": pr["_id"]}, sort=[("created_at", -1)]))
    out["invoices"] = clean(await ctx.data.invoices.find({"project_id": pr["_id"]}, sort=[("created_at", -1)]))
    out["sessions"] = clean(await ctx.data.sessions.find({"project_id": pr["_id"]}, sort=[("start", 1)]))
    out["runs"] = clean(await ctx.data.automation_runs.find({"project_id": pr["_id"]}, sort=[("created_at", -1)], limit=20))
    out["time_minutes"] = sum(t["minutes"] for t in await ctx.data.time_entries.find({"project_id": pr["_id"]}))
    ws = await ctx.ws()
    from app.domain.engagement.portal import portal_url
    out["portal_url"] = await portal_url(ctx, pr) if pr.get("contact_ids") else None
    out["custom_fields"] = ws.get("settings", {}).get("custom_fields", [])
    return perm.strip_money(ctx, out)


class ProjectUpdate(P):
    id: str
    name: Optional[str] = None
    type: Optional[str] = None
    value_paise: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    source: Optional[str] = None
    owner_id: Optional[str] = None
    team_ids: Optional[list] = None
    contact_ids: Optional[list] = None
    custom: Optional[dict] = None
    shared_details: Optional[dict] = None
    portal_link_on: Optional[bool] = None


@action("projects.update", "internal", ProjectUpdate, desc="Update a project's details.")
async def projects_update(ctx, p: ProjectUpdate):
    pr = await perm.project(ctx, p.id, act=True)
    ch = {k: v for k, v in p.model_dump(exclude={"id"}).items() if v is not None}
    if "value_paise" in ch and ch["value_paise"] < 0:
        raise AppError("invalid", "Project value can't be negative.", 400)
    if pr.get("booked") and "contact_ids" in ch and not ch["contact_ids"]:
        raise AppError("invalid", "A booked project needs at least one contact.", 400)
    await ctx.data.projects.update({"_id": pr["_id"]}, ch)
    return await projects_get(ctx, IdIn(id=pr["_id"]))


class MoveStage(P):
    id: str
    stage_id: str


async def move_stage(ctx, pr, st, why="by hand"):
    if pr["stage_id"] == st["_id"]:
        return
    await ctx.data.projects.update({"_id": pr["_id"]}, {"stage_id": st["_id"], "stage_entered_at": now(), "last_activity_at": now()})
    await log(ctx, pr["_id"], "stage", f"Moved to {st['name']} ({why})")
    await emit(ctx, "project.stage_changed", {"stage_id": st["_id"], "stage_key": st.get("key"), "from": pr["stage_id"]}, pr["_id"])


@action("projects.move_stage", "internal", MoveStage, desc="Move a project to another pipeline stage.")
async def projects_move(ctx, p: MoveStage):
    pr = await perm.project(ctx, p.id, act=True)
    st = await ctx.data.stages.get(p.stage_id)
    if not st:
        raise not_found("That stage")
    await move_stage(ctx, pr, st)
    return {"ok": True}


class BulkIn(P):
    ids: list
    op: str              # move_stage | tag | assign | archive
    stage_id: Optional[str] = None
    tag: Optional[str] = None
    owner_id: Optional[str] = None
    reason: Optional[str] = None


@action("projects.bulk", "internal", BulkIn, desc="Bulk change: move stage, tag, assign or archive several projects.")
async def projects_bulk(ctx, p: BulkIn):
    done = 0
    for pid in p.ids[:500]:
        try:
            pr = await perm.project(ctx, pid, act=True)
        except AppError:
            continue
        if p.op == "move_stage" and p.stage_id:
            await move_stage(ctx, pr, await ctx.data.stages.get(p.stage_id), "bulk")
        elif p.op == "tag" and p.tag:
            await add_tag(ctx, pr, p.tag)
        elif p.op == "assign" and p.owner_id:
            await ctx.data.projects.update({"_id": pid}, {"owner_id": p.owner_id})
        elif p.op == "archive":
            await archive(ctx, pr, p.reason)
        done += 1
    return {"changed": done}


class ArchiveIn(P):
    id: str
    reason: Optional[str] = None


async def archive(ctx, pr, reason):
    st = await ctx.data.stages.get(pr["stage_id"])
    if (st or {}).get("group") == "opportunity" and not pr.get("booked") and not reason:
        raise AppError("reason_needed", "Please choose why this lead was lost.", 400)
    await ctx.data.projects.update({"_id": pr["_id"]}, {"archived": True, "archived_reason": reason, "archived_at": now()})
    runs = await ctx.data.automation_runs.find({"project_id": pr["_id"], "status": {"$in": ["running", "waiting", "waiting_approval"]}})
    for r in runs:
        await ctx.data.automation_runs.update({"_id": r["_id"]}, {"status": "cancelled", "ended_reason": "Project archived"})
    await log(ctx, pr["_id"], "archived", f"Archived{(': ' + reason) if reason else ''}")
    await emit(ctx, "project.archived", {"reason": reason}, pr["_id"])


@action("projects.archive", "destructive", ArchiveIn, desc="Archive a project (stops its automations). Lost leads need a reason.")
async def projects_archive(ctx, p: ArchiveIn):
    pr = await perm.project(ctx, p.id, act=True)
    await archive(ctx, pr, p.reason)
    return {"ok": True}


@action("projects.unarchive", "internal", IdIn, desc="Bring an archived project back.")
async def projects_unarchive(ctx, p: IdIn):
    pr = await perm.project(ctx, p.id, act=True)
    await ctx.data.projects.update({"_id": pr["_id"]}, {"archived": False, "archived_reason": None})
    return {"ok": True}


@action("projects.delete", "destructive", IdIn, roles=ADMINS, agent_ok=False, desc="Delete a project (can be restored for 30 days).")
async def projects_delete(ctx, p: IdIn):
    pr = await perm.project(ctx, p.id, act=True)
    await ctx.data.projects.soft_delete({"_id": pr["_id"]})
    await audit(ctx, "project.deleted", pr["_id"])
    return {"ok": True}


@action("projects.restore", "internal", IdIn, roles=ADMINS, agent_ok=False, desc="Restore a deleted project (within 30 days).")
async def projects_restore(ctx, p: IdIn):
    pr = await ctx.data.projects.get(p.id, include_deleted=True)
    if not pr or not pr.get("deleted_at") or aware(pr["deleted_at"]) < now() - timedelta(days=30):
        raise not_found("That deleted project")
    await ctx.data.projects.update({"_id": pr["_id"]}, {"deleted_at": None}, include_deleted=True)
    return {"ok": True}


class BookedIn(P):
    id: str
    booked: bool = True


async def set_booked(ctx, pid, why):
    pr = await ctx.data.projects.get(pid)
    if pr and not pr.get("booked"):
        if not pr.get("contact_ids"):
            return
        await ctx.data.projects.update({"_id": pid}, {"booked": True, "booked_at": now()})
        await log(ctx, pid, "booked", f"Project booked ({why})")


@action("projects.mark_booked", "internal", BookedIn, desc="Mark a project booked (or not) by hand.")
async def projects_mark_booked(ctx, p: BookedIn):
    pr = await perm.project(ctx, p.id, act=True)
    if p.booked and not pr.get("contact_ids"):
        raise AppError("invalid", "A booked project needs at least one contact with a phone or email.", 400)
    await ctx.data.projects.update({"_id": pr["_id"]}, {"booked": p.booked, "booked_at": now() if p.booked else None})
    await log(ctx, pr["_id"], "booked", "Marked booked by hand" if p.booked else "Marked not booked")
    return {"ok": True}


# ---------------- notes and tags ----------------

class NoteIn(P):
    project_id: str
    text: str
    shared: bool = False


@action("notes.add", "internal", NoteIn, desc="Add a note to a project (shared notes show in the client portal).")
async def notes_add(ctx, p: NoteIn):
    pr = await perm.project(ctx, p.project_id)
    if not p.text.strip():
        raise AppError("invalid", "The note is empty.", 400)
    n = await ctx.data.notes.insert({"project_id": pr["_id"], "text": p.text.strip()[:20000], "shared": p.shared,
                                     "author_id": ctx.user_id, "actor": ctx.actor})
    await log(ctx, pr["_id"], "note", "Note added" + (" (shared with client)" if p.shared else ""), ref=n["_id"])
    return clean(n)


class TagIn(P):
    project_id: str
    tag: str


async def add_tag(ctx, pr, tag):
    tag = tag.strip()[:40]
    if tag and tag not in pr.get("tags", []):
        await ctx.data.projects.update({"_id": pr["_id"]}, {}, raw={"$addToSet": {"tags": tag}})
        await emit(ctx, "tag.added", {"tag": tag}, pr["_id"])


@action("tags.add", "internal", TagIn, desc="Add a tag to a project.")
async def tags_add(ctx, p: TagIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    await add_tag(ctx, pr, p.tag)
    return {"ok": True}


@action("tags.remove", "internal", TagIn, desc="Remove a tag from a project.")
async def tags_remove(ctx, p: TagIn):
    pr = await perm.project(ctx, p.project_id, act=True)
    await ctx.data.projects.update({"_id": pr["_id"]}, {}, raw={"$pull": {"tags": p.tag}})
    return {"ok": True}


# ---------------- tasks ----------------

class TaskIn(P):
    title: str
    project_id: Optional[str] = None
    assignee_id: Optional[str] = None
    due_at: Optional[str] = None
    estimate_hours: Optional[float] = None
    service_id: Optional[str] = None


async def create_task(ctx, title, project_id=None, assignee_id=None, due_at=None, estimate_minutes=None, service_id=None):
    t = await ctx.data.tasks.insert({"title": title.strip()[:200], "project_id": project_id,
                                     "assignee_id": assignee_id or ctx.user_id, "due_at": aware(due_at) if due_at else None,
                                     "done": False, "created_by": ctx.actor, "reminded": False, "audience": "team",
                                     "estimate_minutes": estimate_minutes, "service_id": service_id})
    await log(ctx, project_id, "task", f"Task added: {t['title']}", ref=t["_id"])
    return t


@action("tasks.create", "internal", TaskIn, desc="Create a task (clients never see tasks).")
async def tasks_create(ctx, p: TaskIn):
    if not p.title.strip():
        raise AppError("invalid", "The task needs a title.", 400)
    if p.project_id:
        await perm.project(ctx, p.project_id)
    owner = await ctx.ws()
    if not p.assignee_id and ctx.user_id is None:
        p.assignee_id = owner["owner_id"]
    est = int(round(p.estimate_hours * 60)) if p.estimate_hours else None
    return clean(await create_task(ctx, p.title, p.project_id, p.assignee_id, p.due_at, est, p.service_id))


@action("tasks.complete", "internal", IdIn, desc="Mark a task done.")
async def tasks_complete(ctx, p: IdIn):
    t = await ctx.data.tasks.get(p.id)
    if not t:
        raise not_found("That task")
    if t.get("project_id"):
        await perm.project(ctx, t["project_id"], act=True)
    elif ctx.role not in perm.ACT_ALL and t.get("assignee_id") not in (None, ctx.user_id):
        raise not_found("That task")
    if t.get("audience") == "client":
        from app.domain.engagement.client_tasks import complete
        await complete(ctx, t, by="consultant")
        return {"ok": True, "done": True}
    await ctx.data.tasks.update({"_id": t["_id"]}, {"done": not t["done"], "done_at": now()})
    if not t["done"]:
        await emit(ctx, "task.completed", {"task_id": t["_id"]}, t.get("project_id"))
    return {"ok": True, "done": not t["done"]}


class TaskList(P):
    scope: str = "open"  # open | today | upcoming | overdue | done | all
    project_id: Optional[str] = None
    mine: bool = False
    audience: str = "team"   # team | client | all


@action("tasks.list", "read", TaskList, desc="List tasks: today, upcoming, overdue.")
async def tasks_list(ctx, p: TaskList):
    from app.core.util import IST
    f = {}
    if p.project_id:
        await perm.project(ctx, p.project_id)
        f["project_id"] = p.project_id
    if p.mine or ctx.role in ("member", "collaborator"):
        f["assignee_id"] = ctx.user_id
    t0 = now().astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    t1 = t0 + timedelta(days=1)
    if p.scope != "all":
        f["done"] = p.scope == "done"
    if p.scope == "today":
        f["due_at"] = {"$gte": t0, "$lt": t1}
    elif p.scope == "upcoming":
        f["due_at"] = {"$gte": t1}
    elif p.scope == "overdue":
        f["due_at"] = {"$lt": now()}
    if p.audience != "all":
        f["audience"] = "client" if p.audience == "client" else {"$ne": "client"}
    rows = await ctx.data.tasks.find(f, sort=[("due_at", 1)], limit=300)
    logged = {}
    ids = [r["_id"] for r in rows if r.get("estimate_minutes")]
    if ids:
        for e in await ctx.data.time_entries.find({"task_id": {"$in": ids}}, projection={"task_id": 1, "minutes": 1}):
            logged[e["task_id"]] = logged.get(e["task_id"], 0) + e["minutes"]
    out = clean(rows)
    for o in out:
        if o.get("estimate_minutes"):
            o["logged_minutes"] = logged.get(o["id"], 0)
    return out


# Time tracking lives in actions/timebill.py (add-on A2).


# ---------------- leads ----------------

class LeadIn(P):
    name: str = ""
    phone: str = ""
    email: str = ""
    company: str = ""
    message: str = ""
    source: str = ""
    project_type: str = ""
    project_name: str = ""
    utm: dict = {}
    answers: dict = {}
    form_id: Optional[str] = None
    via: str = "manual"   # form | screenshot | inbox | manual


async def create_lead(ctx, d: dict):
    """Contact (matched by phone/email) + a new project in the first stage."""
    c, _ = await upsert_contact(ctx, {"name": d.get("name"), "phone": d.get("phone"), "email": d.get("email"),
                                      "company": d.get("company"), "source": d.get("source")})
    if d.get("via") != "manual":
        try:
            from app.integrations.vendors import enrich
            e = await enrich(c.get("email"), c.get("name"))
            if e:
                await ctx.data.contacts.update({"_id": c["_id"]}, {"enrichment": e, "company": c.get("company") or e.get("company", "")})
        except Exception:
            pass
    ws = await ctx.ws()
    pr = await create_project(ctx, {"name": d.get("project_name") or f"{c['name']} — {d.get('project_type') or 'enquiry'}",
                                    "contact_ids": [c["_id"]], "type": d.get("project_type") or "",
                                    "source": d.get("source") or "", "utm": d.get("utm") or {},
                                    "owner_id": ws["owner_id"] if ctx.user_id is None else ctx.user_id})
    if d.get("message") or d.get("answers"):
        txt = (d.get("message") or "") + ("\n" if d.get("message") and d.get("answers") else "") + \
              "\n".join(f"{k}: {v}" for k, v in (d.get("answers") or {}).items())
        await ctx.data.notes.insert({"project_id": pr["_id"], "text": txt.strip(), "shared": False, "actor": "client",
                                     "kind": "enquiry"})
    await log(ctx, pr["_id"], "lead", f"New lead from {d.get('source') or d.get('via')}", meta={"via": d.get("via")})
    if d.get("via") in ("form", "screenshot", "inbox"):
        await emit(ctx, "lead_form.submitted", {"form_id": d.get("form_id"), "via": d.get("via"), "contact_id": c["_id"],
                                                "answers": d.get("answers") or {}, "message": d.get("message", "")}, pr["_id"])
    return c, pr


@action("leads.create", "internal", LeadIn, roles=STAFF, desc="Create a lead: contact plus a new project in the first stage.")
async def leads_create(ctx, p: LeadIn):
    c, pr = await create_lead(ctx, p.model_dump())
    return {"contact": clean(c), "project": clean(pr)}


@action("leads.suggested", "read", desc="Leads the inbox lead finder or screenshot reader found, waiting to be accepted.")
async def leads_suggested(ctx, p):
    return clean(await ctx.data.suggested_leads.find({"status": "new"}, sort=[("created_at", -1)]))


class SuggestDecide(P):
    id: str
    accept: bool


@action("leads.decide_suggested", "internal", SuggestDecide, roles=STAFF, desc="Accept or dismiss a suggested lead.")
async def leads_decide(ctx, p: SuggestDecide):
    s = await ctx.data.suggested_leads.get(p.id)
    if not s or s["status"] != "new":
        raise not_found("That suggested lead")
    out = {"ok": True}
    if p.accept:
        c, pr = await create_lead(ctx, dict(s["lead"], via=s.get("via", "inbox")))
        out["project_id"] = pr["_id"]
    await ctx.data.suggested_leads.update({"_id": s["_id"]}, {"status": "accepted" if p.accept else "dismissed"})
    return out


# ---------------- search ----------------

class Q(P):
    q: str


@action("search.all", "read", Q, desc="Search contacts and projects at once.")
async def search_all(ctx, p: Q):
    c = await contacts_search(ctx, ContactSearch(q=p.q, limit=8))
    pr = await projects_search(ctx, ProjectSearch(q=p.q, limit=8))
    return {"contacts": c["items"], "projects": pr["items"]}


_ = new_id
