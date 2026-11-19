"""Scheduled jobs. One registry, schedules in IST, every run logged, and a
database lease lock so each job runs once even with several workers."""
import time
import traceback
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.context import system_ctx
from app.db import get_db
from app.core.util import IST, aware, month_key, new_id, now


async def lease(name, seconds):
    db = get_db()
    try:
        r = await db.job_locks.find_one_and_update({"_id": name, "$or": [{"until": None}, {"until": {"$lt": now()}}]},
                                                   {"$set": {"until": now() + timedelta(seconds=seconds)}}, upsert=True)
        return r is not None
    except Exception:  # duplicate key: another worker holds it
        return False


async def release(name):
    await get_db().job_locks.update_one({"_id": name}, {"$set": {"until": None}})


async def workspaces():
    return await get_db().workspaces.find({"read_only": {"$ne": True}}, {"_id": 1}).to_list(None)


# ---------------- the jobs ----------------

async def j_dispatch():
    from app.automations.engine import dispatch
    return await dispatch()


async def j_tick():
    from app.automations.engine import tick
    return await tick()


async def j_outbound():
    """Send messages whose scheduled time (quiet hours, schedule send) has come."""
    from app.domain.engagement.inbox import deliver
    db = get_db()
    n = 0
    for q in await db.outbound_queue.find({"status": "pending", "send_at": {"$lte": now()}}).to_list(200):
        r = await db.outbound_queue.find_one_and_update({"_id": q["_id"], "status": "pending"}, {"$set": {"status": "sending"}})
        if not r:
            continue
        m = await db.messages.find_one({"_id": q["message_id"]})
        if m and m["status"] in ("scheduled", "queued"):
            ctx = system_ctx(q["workspace_id"], actor=m.get("actor") or "system")
            await deliver(ctx, m)
            n += 1
        else:
            await db.outbound_queue.update_one({"_id": q["_id"]}, {"$set": {"status": "done"}})
    # Client files scheduled to send.
    from app.domain.documents.files import SendIn, do_send
    for f in await db.client_files.find({"scheduled_send.schedule_at": {"$lte": now()}}).to_list(100):
        ctx = system_ctx(f["workspace_id"], actor="user")
        ctx.user_id = f["scheduled_send"].get("user_id")
        sp = dict(f["scheduled_send"])
        await db.client_files.update_one({"_id": f["_id"]}, {"$set": {"scheduled_send": None}})
        try:
            await do_send(ctx, f, SendIn(**{k: v for k, v in sp.items() if k in SendIn.model_fields and k != "schedule_at"}))
        except Exception:
            pass
        n += 1
    return n


async def j_sessions():
    """Holds, reminders, session.starting and session.ended events, notetaker transcripts."""
    from app.domain.engagement.inbox import send_message
    from app.domain.engagement.scheduling import cancel_session
    from app.core.events import emit
    from app.core.util import fmt_dt
    db = get_db()
    n = 0
    for s in await db.sessions.find({"status": "held", "hold_expires_at": {"$lt": now()}}).to_list(500):
        await cancel_session(system_ctx(s["workspace_id"]), s, by="hold expired", tell_client=False)
        n += 1
    for s in await db.sessions.find({"status": "booked", "start": {"$gt": now() - timedelta(hours=2), "$lt": now() + timedelta(days=2)}}).to_list(2000):
        ctx = system_ctx(s["workspace_id"])
        st = await ctx.data.session_types.get(s["type_id"]) or {}
        start = aware(s["start"])
        for off in st.get("reminders", [1440, 60]):
            if off not in s.get("reminders_sent", []) and now() >= start - timedelta(minutes=off) and now() < start:
                c = await ctx.data.contacts.get(s["contact_id"])
                ws = await ctx.ws()
                if c and c.get("phone"):
                    await send_message(ctx, s["project_id"], c, "whatsapp", wa_template="session_reminder",
                                       wa_params=[c.get("first_name") or c["name"], ws["name"], fmt_dt(start), s.get("meet_link") or "-"],
                                       kind="reminder", idem_key=f"rem:{s['_id']}:{off}")
                if c and c.get("email"):
                    await send_message(ctx, s["project_id"], c, "email", f"Reminder: {s['title']} at {fmt_dt(start).split(', ')[-1]}",
                                       f"<p>Hi {c.get('first_name') or c['name']}, a reminder about {s['title']} on {fmt_dt(start)}.</p>"
                                       + (f"<p>Join: {s['meet_link']}</p>" if s.get("meet_link") else ""), kind="reminder",
                                       idem_key=f"rem:{s['_id']}:{off}")
                await db.sessions.update_one({"_id": s["_id"]}, {"$addToSet": {"reminders_sent": off}})
                n += 1
        if not s.get("starting_emitted") and now() >= start - timedelta(minutes=60):
            await db.sessions.update_one({"_id": s["_id"]}, {"$set": {"starting_emitted": True}})
            await emit(ctx, "session.starting", {"session_id": s["_id"], "type_key": s.get("type_key")}, s["project_id"])
    for s in await db.sessions.find({"status": {"$in": ["booked", "no_show", "completed"]}, "end": {"$lt": now()}, "ended_emitted": {"$ne": True}}).to_list(500):
        ctx = system_ctx(s["workspace_id"])
        await db.sessions.update_one({"_id": s["_id"]}, {"$set": {"ended_emitted": True, "status": "completed" if s["status"] == "booked" else s["status"]}})
        await emit(ctx, "session.ended", {"session_id": s["_id"], "type_key": s.get("type_key"), "type_id": s["type_id"]}, s["project_id"])
        n += 1
    return n


async def j_money():
    """Overdue marking (+ payment.overdue once), late fees at 30 days, invoice reminders."""
    from app.domain.billing.money import save_invoice
    from app.core.events import emit, log
    db = get_db()
    n = 0
    for inv in await db.invoices.find({"status": {"$in": ["sent", "partially_paid"]}, "deleted_at": None}).to_list(5000):
        ctx = system_ctx(inv["workspace_id"])
        ws = await ctx.ws()
        lf = ws["invoice"].get("late_fee", {})
        changed = False
        for s in inv["schedule"]:
            if s["status"] in ("paid", "processing") or not s.get("due_date"):
                continue
            due = aware(s["due_date"])
            if due < now() and not s.get("overdue_emitted"):
                s["overdue_emitted"] = True
                changed = True
                await emit(ctx, "payment.overdue", {"invoice_id": inv["_id"], "item_id": s["id"]}, inv["project_id"])
            if lf.get("enabled") and not s.get("late_fee_added_at") and not s.get("late_fee_cancelled") and now() >= due + timedelta(days=30):
                pct = min(int(lf.get("pct_bp", 0)), 1000)
                s["late_fee_paise"] = (s["amount_paise"] - s.get("paid_paise", 0)) * pct // 10000
                s["late_fee_added_at"] = now()
                changed = True
                await log(ctx, inv["project_id"], "payment", f"Late fee added on {s['label']} (once, not compounding)", ref=inv["_id"])
            for off in ws["invoice"].get("reminders", [-3, 0, 3, 7]):
                tag = f"r{off}"
                if tag not in s.get("reminded", []) and now() >= due + timedelta(days=off) and now() < due + timedelta(days=off + 1):
                    s.setdefault("reminded", []).append(tag)
                    changed = True
                    try:
                        from app.domain.registry import call
                        await call(ctx.child(idem_key=f"invrem:{inv['_id']}:{s['id']}:{off}"), "invoices.remind", {"id": inv["_id"], "item_id": s["id"]})
                    except Exception:
                        pass
        if changed:
            await save_invoice(ctx, inv)
            n += 1
    return n


async def j_recurring():
    from app.domain.billing.money import SendInv, invoices_send, new_invoice
    db = get_db()
    t = now().astimezone(IST)
    mk = month_key()
    n = 0
    for r in await db.recurring_invoices.find({"active": True, "deleted_at": None}).to_list(2000):
        if r.get("last_month") == mk or t.day < r["day_of_month"]:
            continue
        if r.get("start_month") and mk < r["start_month"]:
            continue
        if r.get("end_month") and mk > r["end_month"]:
            await db.recurring_invoices.update_one({"_id": r["_id"]}, {"$set": {"active": False}})
            continue
        ctx = system_ctx(r["workspace_id"])
        pr = await ctx.data.projects.get(r["project_id"])
        if not pr or pr.get("archived"):
            continue
        claim = await db.recurring_invoices.find_one_and_update({"_id": r["_id"], "last_month": r.get("last_month")}, {"$set": {"last_month": mk}})
        if not claim:
            continue
        due = t.replace(hour=12) + timedelta(days=7)
        inv = await new_invoice(ctx, pr, r["lines"], [{"id": new_id()[:8], "label": f"Retainer {t:%B %Y}", "pct": 100,
                                                       "due": {"type": "date", "date": due.isoformat()}}], f"Retainer — {t:%B %Y}")
        await ctx.data.invoices.update({"_id": inv["_id"]}, {"recurring_id": r["_id"]})
        try:
            await invoices_send(ctx, SendInv(id=inv["_id"], channel=r.get("channel", "both")))
        except Exception:
            pass
        n += 1
    return n


async def _agent_all(agent, **kw):
    from app.agents.runtime import AgentOff, run_agent
    n = 0
    for w in await workspaces():
        try:
            await run_agent(w["_id"], agent, trigger={"kind": "schedule"}, **kw)
            n += 1
        except AgentOff:
            pass
        except Exception:
            traceback.print_exc()
    return n


async def j_daily_brief():
    return await _agent_all("daily_brief")


async def j_followup():
    return await _agent_all("followup")


async def j_collections():
    return await _agent_all("collections")


async def _each_ws(fn):
    n = 0
    for w in await workspaces():
        try:
            n += await fn(w["_id"]) or 0
        except Exception:
            traceback.print_exc()
    return n


async def j_budgets():
    from app.domain.billing.budgets import check_all
    return await _each_ws(check_all)


async def j_retainers():
    from app.domain.billing.retainers import run_all
    return await _each_ws(run_all)


async def j_recurring_tasks():
    from app.domain.billing.retainers import recurring_tasks
    return await _each_ws(recurring_tasks)


async def j_client_tasks():
    from app.domain.engagement.client_tasks import run_due
    return await _each_ws(run_due)


async def build_export(ex):
    """Job: build one queued ZIP (claimed once, so two workers don't both build it)."""
    import zipfile

    from app.integrations import vendors
    from app.core.context import system_ctx
    from app.db import get_db
    from app.services.pdf import invoice_pdf
    from app.domain.billing.timebill import io, notify, now, timedelta
    db = get_db()
    got = await db.exports.find_one_and_update({"_id": ex["_id"], "status": "queued"}, {"$set": {"status": "building", "started_at": now()}})
    if not got:
        return False
    ctx = system_ctx(ex["workspace_id"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for iid in ex["invoice_ids"]:
            inv = await ctx.data.invoices.get(iid)
            if inv:
                z.writestr(f"{(inv.get('number') or iid).replace('/', '-')}.pdf", await invoice_pdf(ctx, inv))
    key = await vendors.storage_put(ex["workspace_id"], f"invoices-{now():%Y%m%d-%H%M}.zip", buf.getvalue(), "application/zip", count=False)
    await db.exports.update_one({"_id": ex["_id"]}, {"$set": {"status": "ready", "key": key, "ready_at": now(),
                                                              "expires_at": now() + timedelta(days=7)}})
    await notify(ctx, f"Your ZIP of {ex['count']} invoice{'s' if ex['count'] != 1 else ''} is ready.", "export",
                 link=f"/api/exports/{ex['_id']}", user_ids=[ex.get("requested_by")] if ex.get("requested_by") else None)
    return True



async def j_exports():
    n = 0
    for ex in await get_db().exports.find({"status": "queued", "deleted_at": None}).to_list(50):
        try:
            n += 1 if await build_export(ex) else 0
        except Exception:
            traceback.print_exc()
            await get_db().exports.update_one({"_id": ex["_id"]}, {"$set": {"status": "failed"}})
    return n


async def j_housekeeping():
    db = get_db()
    # Approvals expire after 7 days (across all workspaces: a housekeeping job, not an action).
    n = (await db.approvals.update_many({"status": "pending", "expires_at": {"$lt": now()}}, {"$set": {"status": "expired"}})).modified_count
    await db.otp_codes.delete_many({"expires_at": {"$lt": now() - timedelta(days=1)}})
    return n


async def j_project_dates():
    """Start runs for project start/end date triggers (with offset)."""
    from app.automations.engine import start_run
    db = get_db()
    today = now().astimezone(IST).date()
    n = 0
    for a in await db.automations.find({"active": True, "deleted_at": None, "trigger.type": {"$in": ["project.start_date", "project.end_date"]}}).to_list(5000):
        ctx = system_ctx(a["workspace_id"])
        field = "start_date" if a["trigger"]["type"] == "project.start_date" else "end_date"
        target = (today - timedelta(days=int(a["trigger"].get("offset_days", 0)))).isoformat()
        for pr in await ctx.data.projects.find({field: {"$regex": f"^{target}"}, "archived": False}):
            if await start_run(ctx, a, pr["_id"], key=f"{a['_id']}:{pr['_id']}:{field}:{target}"):
                n += 1
    return n


async def j_inbox_finder():
    """Watch connected inboxes for new enquiries; suggest them as leads."""
    from app.integrations import vendors
    db = get_db()
    n = 0
    for conn in await db.connections.find({"provider": {"$in": ["gmail", "outlook"]}, "lead_finder": True}).to_list(1000):
        ctx = system_ctx(conn["workspace_id"])
        since = aware(conn.get("last_scan") or now() - timedelta(days=1))
        try:
            msgs = await vendors.inbox_new_messages(conn, since)
        except Exception:
            continue
        await db.connections.update_one({"_id": conn["_id"]}, {"$set": {"last_scan": now()}})
        for m in msgs:
            frm = m.get("from", "")
            email = (frm.split("<")[-1].rstrip(">") if "<" in frm else frm).strip().lower()
            if not email or await ctx.data.contacts.find_one({"email": email}) or await ctx.data.suggested_leads.find_one({"msg_id": m["id"]}):
                continue
            words = (m.get("subject", "") + " " + m.get("snippet", "")).lower()
            if not any(w in words for w in ("enquiry", "inquiry", "consult", "help", "quote", "proposal", "call", "services", "interested")):
                continue
            await ctx.data.suggested_leads.insert({"msg_id": m["id"], "status": "new", "via": "inbox", "why": m.get("subject", ""),
                                                   "lead": {"name": frm.split("<")[0].strip().strip('"') or email, "email": email,
                                                            "message": m.get("snippet", ""), "source": "Email"}})
            n += 1
    return n


JOBS = {
    "dispatch": (j_dispatch, "every 10 s", "Process events (stage rules, automations, agent triggers)"),
    "tick": (j_tick, "every 30 s", "Run due automation steps"),
    "outbound": (j_outbound, "every 30 s", "Send scheduled messages and files"),
    "sessions": (j_sessions, "every 1 min", "Holds, reminders, session start/end"),
    "money": (j_money, "hourly", "Overdue, late fees, invoice reminders"),
    "recurring": (j_recurring, "daily 09:05 IST", "Monthly retainer invoices"),
    "project_dates": (j_project_dates, "daily 07:30 IST", "Project start/end date automations"),
    "daily_brief": (j_daily_brief, "daily 07:45 IST", "Daily brief for every practice"),
    "followup": (j_followup, "daily 08:00 IST", "Follow-up agent"),
    "collections": (j_collections, "daily 10:00 IST", "Collections agent"),
    "inbox_finder": (j_inbox_finder, "every 15 min", "Inbox lead finder"),
    "housekeeping": (j_housekeeping, "hourly", "Expire approvals, clean codes"),
    "budgets": (j_budgets, "hourly", "Budget cycles, resets and alerts"),
    "retainers": (j_retainers, "hourly", "Close retainer periods, invoices, renewals"),
    "recurring_tasks": (j_recurring_tasks, "hourly", "Next occurrence of repeating tasks"),
    "client_tasks": (j_client_tasks, "hourly", "Client task reminders and overdue"),
    "exports": (j_exports, "every 1 min", "Build invoice ZIPs"),
}


async def run_job(name, force=False):
    fn, sched, label = JOBS[name]
    if not await lease(f"job:{name}", 600):
        return {"ok": False, "skipped": "running elsewhere"}
    db = get_db()
    rid = new_id()
    t0 = time.time()
    await db.job_runs.insert_one({"_id": rid, "job": name, "started_at": now(), "status": "running"})
    try:
        n = await fn()
        await db.job_runs.update_one({"_id": rid}, {"$set": {"status": "ok", "items": n, "seconds": round(time.time() - t0, 2)}})
        return {"ok": True, "items": n}
    except Exception as e:
        await db.job_runs.update_one({"_id": rid}, {"$set": {"status": "error", "error": str(e)[:500], "seconds": round(time.time() - t0, 2)}})
        traceback.print_exc()
        return {"ok": False, "error": str(e)}
    finally:
        await release(f"job:{name}")


def start_scheduler():
    s = AsyncIOScheduler(timezone="Asia/Kolkata")
    trig = {"dispatch": IntervalTrigger(seconds=10), "tick": IntervalTrigger(seconds=30), "outbound": IntervalTrigger(seconds=30),
            "sessions": IntervalTrigger(minutes=1), "money": IntervalTrigger(hours=1), "recurring": CronTrigger(hour=9, minute=5),
            "project_dates": CronTrigger(hour=7, minute=30), "daily_brief": CronTrigger(hour=7, minute=45),
            "followup": CronTrigger(hour=8, minute=0), "collections": CronTrigger(hour=10, minute=0),
            "inbox_finder": IntervalTrigger(minutes=15), "housekeeping": IntervalTrigger(hours=1),
            "budgets": IntervalTrigger(hours=1), "retainers": IntervalTrigger(hours=1), "recurring_tasks": IntervalTrigger(hours=1),
            "client_tasks": IntervalTrigger(hours=1), "exports": IntervalTrigger(minutes=1)}
    for name, t in trig.items():
        s.add_job(run_job, t, args=[name], id=name, max_instances=1, coalesce=True)
    s.start()
    return s
