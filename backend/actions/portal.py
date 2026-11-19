"""Client portal: one place per client, all their projects, under the consultant's brand.

The client logs in by OTP (or a magic link) and sees only what is shared:
their projects and stage names, files, shared notes and details, payments,
sessions and messages. Never internal notes, tasks, automations or the pipeline.
"""
from actions.merge import client_base
from actions.money import view as invoice_view
from core.util import AppError, aware, clean, not_found, now


async def portal_url(ctx, project):
    ws = await ctx.ws()
    return f"{client_base(ws)}/portal"


async def client_projects(ctx, contact_ids):
    rows = await ctx.data.projects.find({"contact_ids": {"$in": contact_ids}, "portal_link_on": {"$ne": False}}, sort=[("created_at", -1)])
    stages = {s["_id"]: s["name"] for s in await ctx.data.stages.find({})}
    return [{"id": r["_id"], "name": r["name"], "stage": stages.get(r["stage_id"], ""), "archived": r.get("archived", False),
             "booked": r.get("booked", False)} for r in rows]


async def client_project(ctx, contact_ids, pid):
    pr = await ctx.data.projects.get(pid)
    if not pr or not set(pr.get("contact_ids", [])) & set(contact_ids):
        raise not_found("That project")
    stages = {s["_id"]: s["name"] for s in await ctx.data.stages.find({})}
    ws = await ctx.ws()
    base = client_base(ws)
    files = [{"id": f["_id"], "title": f["title"], "status": f["status"], "link": f"{base}/f/{f['token']}",
              "sent_at": clean(f).get("sent_at")}
             for f in await ctx.data.client_files.find({"project_id": pid, "status": {"$in": ["sent", "viewed", "completed"]}},
                                                       sort=[("created_at", -1)])]
    invoices = []
    for inv in await ctx.data.invoices.find({"project_id": pid, "status": {"$in": ["sent", "partially_paid", "paid"]}}):
        v = await invoice_view(ctx, inv, for_client=True)
        invoices.append({"id": inv["_id"], "number": inv.get("number"), "title": inv.get("title"), "status": inv["status"],
                         "total_paise": inv["totals"]["total"], "due_paise": inv["totals"]["due"], "link": f"{base}/i/{inv['token']}",
                         "schedule": [{"label": s["label"], "state": s["state"], "amount_paise": s["amount_paise"], "due_label": s["due_label"]}
                                      for s in v["schedule"]]})
    sessions = [{"id": s["_id"], "title": s["title"], "start": aware(s["start"]).isoformat(), "status": s["status"],
                 "meet_link": s.get("meet_link"), "type_id": s["type_id"]}
                for s in await ctx.data.sessions.find({"project_id": pid, "status": {"$in": ["booked", "completed"]}}, sort=[("start", 1)])]
    msgs = [{"direction": m["direction"], "channel": m["channel"], "subject": m.get("subject"),
             "text": m.get("body_text") or "", "html": m.get("body_html") if m["direction"] == "out" else None,
             "at": clean(m)["created_at"]}
            for m in await ctx.data.messages.find({"project_id": pid, "status": {"$nin": ["draft", "scheduled", "queued", "failed"]}},
                                                  sort=[("created_at", 1)], limit=200)]
    activity = clean(await ctx.data.activity.find({"project_id": pid, "client_visible": True}, sort=[("at", -1)], limit=60))
    for a in activity:
        for k in ("actor", "user_id", "agent_run_id", "meta"):
            a.pop(k, None)
    notes = [{"text": n["text"], "at": clean(n)["created_at"]} for n in await ctx.data.notes.find({"project_id": pid, "shared": True})]
    uploads = [{"name": u["name"], "link": f"{base}/d/{u['token']}", "kind": u.get("kind"), "by_client": u.get("by_client", False)}
               for u in await ctx.data.uploads.find({"project_id": pid, "client_visible": True})]
    # Client tasks are the only tasks a client ever sees.
    from core.util import fmt_date
    ctasks = [{"title": x["title"], "details": x.get("details") or "", "due": fmt_date(x["due_at"]) if x.get("due_at") else None,
               "done": x["done"], "overdue": bool(not x["done"] and x.get("due_at") and aware(x["due_at"]) < now()),
               "link": f"{base}/t/{x['token']}"}
              for x in await ctx.data.tasks.find({"project_id": pid, "audience": "client"}, sort=[("done", 1), ("due_at", 1)])]
    retainer = None
    r = await ctx.data.retainers.find_one({"project_ids": pid, "status": {"$in": ["active", "paused"]}})
    if r:
        from actions.retainers import statement
        per = await ctx.data.retainer_periods.find_one({"retainer_id": r["_id"], "status": "open"}) or \
            (await ctx.data.retainer_periods.find({"retainer_id": r["_id"]}, sort=[("index", -1)], limit=1) or [None])[0]
        if per:
            retainer = await statement(ctx, r, per, for_client=True)
            last = await ctx.data.retainer_periods.find({"retainer_id": r["_id"], "status": "closed"}, sort=[("index", -1)], limit=1)
            if last:
                retainer["last_period"] = await statement(ctx, r, last[0], for_client=True)
    return {"id": pid, "name": pr["name"], "stage": stages.get(pr["stage_id"], ""), "details": pr.get("shared_details", {}),
            "files": files, "invoices": invoices, "sessions": sessions, "messages": msgs, "activity": activity,
            "notes": notes, "uploads": uploads, "client_tasks": ctasks, "retainer": retainer}


_ = (AppError, now)
