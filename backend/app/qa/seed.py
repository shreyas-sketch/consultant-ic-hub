"""QA mode sample data: one demo practice built through the real action layer,
so every screen has something real to show."""
from datetime import timedelta

from app.domain.registry import call
from app.core.context import Ctx
from app.db import get_db
from app.core.util import IST, aware, new_id, now

PERSONAS = {
    "owner": "+919000000001", "admin": "+919000000002", "manager": "+919000000003", "member": "+919000000004",
    "collaborator": "+919000000005", "staff": "+919999999999", "new": "+919000000009",
}

SETUP = {"name": "Priya Mehta — Mehta Growth Advisory", "who": "Founders of ₹5–50 Cr family businesses",
         "problem": "Sales depend on the founder and there's no repeatable process",
         "offers": "Business health audit — ₹75,000\nAdvisory retainer — ₹50,000 a month\nTeam sales workshop — ₹60,000",
         "rates": "₹6,000 an hour, ₹40,000 a day",
         "how": "Webinars and referrals. A free 30-minute call, then a proposal the same day.",
         "call": "30 minutes, Mon–Fri, 10am–1pm and 3pm–6pm", "payment": "50% advance, rest in 30 days",
         "upi": "priya.mehta@okhdfcbank", "tone": "Warm, but professional"}


async def seed():
    db = get_db()
    if await db.users.find_one({"phone": PERSONAS["owner"]}):
        return
    from app.auth import login_phone
    for role, phone in PERSONAS.items():
        await db.invites.insert_one({"_id": new_id(), "phone": phone, "name": {"owner": "Priya Mehta", "new": "Rahul Verma"}.get(role, ""),
                                     "note": "QA persona", "invited_by": "seed", "status": "invited", "created_at": now(), "via": "admin"})
    for i, (n, note) in enumerate([("Deepa Nair", "Sept batch"), ("Amit Kulkarni", "Sept batch"), ("Rekha Bhat", "Oct webinar")]):
        await db.invites.insert_one({"_id": new_id(), "phone": f"+91980000010{i}", "name": n, "note": note, "invited_by": "seed",
                                     "status": "invited", "created_at": now() - timedelta(days=3 + i), "via": "admin"})
    staff = await login_phone(PERSONAS["staff"])
    await db.users.update_one({"_id": staff["_id"]}, {"$set": {"is_admin": True, "name": "Product team"}})
    owner = await login_phone(PERSONAS["owner"])
    await db.users.update_one({"_id": owner["_id"]}, {"$set": {"name": "Priya Mehta", "email": "priya@mehtagrowth.in"}})
    m = await db.memberships.find_one({"user_id": owner["_id"]})
    ws_id = m["workspace_id"]
    ctx = Ctx(ws_id=ws_id, user_id=owner["_id"], role="owner")
    from app.agents.setup import build_account
    await build_account(ctx, SETUP)
    await db.workspaces.update_one({"_id": ws_id}, {"$set": {
        "slug": "mehta-growth", "profile.email": "priya@mehtagrowth.in", "profile.website": "https://mehtagrowth.in",
        "profile.address": "Andheri East, Mumbai 400069", "invoice.bank": {"account_name": "Mehta Growth Advisory", "account_no": "50200012345678",
                                                                          "ifsc": "HDFC0001234", "bank_name": "HDFC Bank"},
        "invoice.late_fee": {"enabled": True, "pct_bp": 200}, "settings.revenue_goal_paise": 30_00_000_00}})
    ctx._ws = None
    team = {}
    for role, nm in (("admin", "Arjun Rao"), ("manager", "Neha Gupta"), ("member", "Kabir Singh"), ("collaborator", "Sana Khan")):
        await call(ctx, "team.add", {"phone": PERSONAS[role], "name": nm, "role": role})
        u = await login_phone(PERSONAS[role])
        await db.users.update_one({"_id": u["_id"]}, {"$set": {"name": nm}})
        team[role] = u["_id"]

    stages = {s["key"]: s for s in await ctx.data.stages.find({})}
    tpl = {t.get("gallery_key"): t for t in await ctx.data.templates.find({})}
    my_prop = await ctx.data.templates.find_one({"by_setup": True})
    st = await ctx.data.session_types.find_one({"key": "discovery"})
    from app.api.routes import public
    from app.domain.documents import files as F
    from app.automations.engine import dispatch, tick

    async def lead(name, company, phone, email, source, msg, days_ago, ptype=""):
        from app.domain.sales.crm import create_lead
        c, pr = await create_lead(ctx, {"name": name, "company": company, "phone": phone, "email": email, "source": source,
                                        "message": msg, "project_type": ptype, "via": "manual"})
        back = now() - timedelta(days=days_ago)
        await db.projects.update_one({"_id": pr["_id"]}, {"$set": {"created_at": back, "last_activity_at": back, "stage_entered_at": back}})
        await db.contacts.update_one({"_id": c["_id"]}, {"$set": {"created_at": back}})
        return c, await ctx.data.projects.get(pr["_id"])

    async def proposal(pr, pick=0, sign=False):
        f = await F.create_file(ctx, pr, my_prop["body"]["pages"], "Advisory proposal", template_id=my_prop["_id"])
        for pg in f["pages"]:
            for b in pg["blocks"]:
                if b["type"] == "contract":
                    for fld in b["fields"]:
                        fld["value"] = fld["value"] or {"start_date": "1 Dec 2026", "end_date": "28 Feb 2027"}.get(fld["key"], "Mumbai")
        await ctx.data.client_files.update({"_id": f["_id"]}, {"pages": f["pages"]})
        f = await ctx.data.client_files.get(f["_id"])
        await F.do_send(ctx, f, F.SendIn(id=f["_id"], channel="email"))
        f = await ctx.data.client_files.get(f["_id"])
        svc = next(b for _, b in F.blocks_of(f["pages"], "services"))
        await public.file_select(f["token"], {"block_id": svc["id"], "picks": {svc["items"][pick]["id"]: 1}})
        if sign:
            blk = next(b for _, b in F.blocks_of(f["pages"], "contract"))
            pr2 = await ctx.data.projects.get(pr["_id"])
            rendered = await F.render_contract(ctx, f, blk, pr=pr2)
            cl = next(s for s in blk["signers"] if s["role"] == "client")
            cctx = ctx.child(actor="client", user_id=None)
            await F.record_signature(cctx, f, blk, cl, (await ctx.data.contacts.get(cl["contact_id"]))["name"], "typed", None,
                                     "103.21.58.12", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5)", True, rendered, "whatsapp")
            await call(ctx, "files.consultant_sign", {"id": f["_id"], "block_id": blk["id"], "name": "Priya Mehta"})
        return await ctx.data.client_files.get(f["_id"])

    async def invoice_of(f):
        b = next(b for _, b in F.blocks_of(f["pages"], "invoice"))
        return await ctx.data.invoices.get(b["invoice_id"])

    # 1. Fresh lead from the website form (the Lead agent drafts a reply for approval)
    form = await call(ctx, "lead_forms.save", {"name": "Discovery call enquiry", "kind": "enquiry", "source": "Website", "project_type": "Advisory"})
    fdoc = await ctx.data.lead_forms.get(form["id"])
    from app.domain.sales.forms import submit
    from app.core.context import system_ctx
    for i in range(14):
        await ctx.data.form_events.insert({"form_id": fdoc["_id"], "kind": "view", "source": ["Webinar", "LinkedIn", "Website"][i % 3], "ip": f"10.0.0.{i}", "at": now() - timedelta(days=i % 6)})
    await submit(system_ctx(ws_id, actor="client", via="public"), fdoc,
                 {"contact": {"name": "Rohit Sharma", "phone": "9820011122", "email": "rohit@sharmaautoparts.in"},
                  "answers": {fdoc["blocks"][1]["questions"][0]["id"]: "We're a ₹18 Cr auto parts distributor. Growth has stalled at 18 Cr for 3 years and I'm in every sales meeting."},
                  "utm": {"utm_source": "webinar", "utm_campaign": "oct-hvc"}}, "10.0.0.99")

    # 2. Call booked tomorrow
    c2, p2 = await lead("Anita Desai", "Desai Foods", "9833022233", "anita@desaifoods.com", "Webinar",
                        "Interested in the audit. We have 3 outlets and want to franchise.", 4, "Audit")
    t = (now() + timedelta(days=1)).astimezone(IST)
    while t.weekday() > 4:
        t += timedelta(days=1)
    from app.domain.engagement.scheduling import book
    await book(ctx, st, t.replace(hour=11, minute=0, second=0, microsecond=0), c2, p2["_id"])

    # 3. Proposal sent 3 days ago, viewed, not signed
    c3, p3 = await lead("Vikram Rao", "Rao Logistics", "9821033344", "vikram@raologistics.in", "Client referral",
                        "Referred by Kavita. Need help building a sales team.", 12, "Retainer")
    f3 = await proposal(p3)
    await db.client_files.update_one({"_id": f3["_id"]}, {"$set": {"status": "viewed", "sent_at": now() - timedelta(days=3), "viewed_count": 2}})
    await ctx.data.file_events.insert({"file_id": f3["_id"], "type": "viewed", "at": now() - timedelta(days=2)})

    # 4. Signed, and the client tapped "I've paid" (waiting for confirmation)
    c4, p4 = await lead("Meera Iyer", "Iyer Interiors", "9819044455", "meera@iyerinteriors.in", "LinkedIn",
                        "We do ₹6 Cr in interior projects; margins are thin.", 20, "Retainer")
    f4 = await proposal(p4, sign=True)
    inv4 = await invoice_of(f4)
    await public.file_claim(f4["token"], {"invoice_id": inv4["_id"], "item_id": inv4["schedule"][0]["id"], "method": "upi", "reference": "UPI 4211 8890 1123"})

    # 5. Advance paid 40 days ago, balance now overdue
    c5, p5 = await lead("Farhan Ali", "Ali Exports", "9867055566", "farhan@aliexports.com", "Webinar", "Export business, ₹22 Cr.", 50, "Retainer")
    f5 = await proposal(p5, pick=0, sign=True)
    inv5 = await invoice_of(f5)
    await call(ctx, "payments.confirm", {"invoice_id": inv5["_id"], "item_id": inv5["schedule"][0]["id"], "method": "upi", "reference": "UTR 2026100145"})
    inv5 = await ctx.data.invoices.get(inv5["_id"])
    inv5["schedule"][0]["paid_at"] = now() - timedelta(days=40)
    from app.domain.billing.money import save_invoice
    await save_invoice(ctx, inv5)
    await db.ledger.update_many({"invoice_id": inv5["_id"]}, {"$set": {"created_at": now() - timedelta(days=40)}})
    await call(ctx, "projects.move_stage", {"id": p5["_id"], "stage_id": stages["in_delivery"]["_id"]})
    t5 = now().astimezone(IST).replace(hour=15, minute=0, second=0, microsecond=0)
    if t5 < now() + timedelta(hours=4):
        t5 = now().astimezone(IST).replace(hour=17, minute=0, second=0, microsecond=0) if now().astimezone(IST).hour < 13 else t5 + timedelta(days=1)

    # 6. Completed and paid in full (two months ago)
    c6, p6 = await lead("Kavita Joshi", "Joshi Clinics", "9820066677", "kavita@joshiclinics.in", "Referral", "Two clinics, want a third.", 95, "Audit")
    f6 = await proposal(p6, pick=0, sign=True)
    inv6 = await invoice_of(f6)
    for s in inv6["schedule"]:
        await call(ctx, "payments.confirm", {"invoice_id": inv6["_id"], "item_id": s["id"], "method": "bank",
                                             "amount_received_paise": s["amount_paise"] - (s["amount_paise"] // 10 if s is inv6["schedule"][1] else 0),
                                             "tds_paise": s["amount_paise"] // 10 if s is inv6["schedule"][1] else 0})
    await db.ledger.update_many({"invoice_id": inv6["_id"]}, {"$set": {"created_at": now() - timedelta(days=62)}})
    await call(ctx, "projects.move_stage", {"id": p6["_id"], "stage_id": stages["completed"]["_id"]})

    # 7. Lost lead
    c7, p7 = await lead("Suresh Patel", "Patel Textiles", "9822077788", "", "Instagram", "Need marketing help.", 30)
    await call(ctx, "projects.archive", {"id": p7["_id"], "reason": "No budget"})

    # 8. Retainer run by the member, with a collaborator on it, monthly invoice
    c8, p8 = await lead("Neel Shah", "Shah Hardware", "9833088899", "neel@shahhardware.in", "Webinar", "Monthly advisory.", 70, "Retainer")
    await ctx.data.projects.update({"_id": p8["_id"]}, {"owner_id": team["member"], "booked": True, "booked_at": now() - timedelta(days=60),
                                                         "stage_id": stages["in_delivery"]["_id"], "value_paise": 30000000})
    await db.memberships.update_one({"workspace_id": ws_id, "user_id": team["collaborator"]}, {"$set": {"project_ids": [p8["_id"]]}})
    await call(ctx, "recurring.create", {"project_id": p8["_id"], "lines": [{"name": "Advisory retainer — monthly", "qty": 1, "price_paise": 5000000}],
                                         "day_of_month": 1})

    # Messages, notes, tasks, expenses, a suggested lead
    from app.domain.engagement.inbox import receive
    await receive(ctx.child(actor="client"), p3["_id"], "whatsapp", c3["phone"], "", "Hi Priya, saw the proposal. Can we reduce the price a bit? Budget is tight this quarter.")
    await call(ctx, "notes.add", {"project_id": p5["_id"], "text": "Farhan wants weekly reviews of the export pipeline. Focus: two new markets in the Gulf.", "shared": True})
    await call(ctx, "tasks.create", {"title": "Prepare the franchise audit checklist", "project_id": p2["_id"], "due_at": now().isoformat()})
    await call(ctx, "tasks.create", {"title": "Send Farhan the Q3 dashboard", "project_id": p5["_id"], "due_at": (now() - timedelta(days=1)).isoformat()})
    await call(ctx, "tasks.create", {"title": "Draft the hiring scorecard for Neel", "project_id": p8["_id"], "assignee_id": team["member"],
                                     "due_at": (now() + timedelta(days=2)).isoformat()})
    for d, amt, cat, pid, note in ((5, 450000, "Software", None, "Zoom and Canva"), (12, 1800000, "Travel", p5["_id"], "Client visit, Surat"),
                                   (35, 2500000, "Marketing", None, "Webinar ads"), (65, 1200000, "Travel", p6["_id"], "Clinic visit, Pune")):
        await call(ctx, "expenses.save", {"amount_paise": amt, "date": (now() - timedelta(days=d)).date().isoformat(), "category": cat,
                                          "project_id": pid, "note": note})
    await ctx.data.suggested_leads.insert({"status": "new", "via": "inbox", "why": "Enquiry: help with sales hiring",
                                           "lead": {"name": "Pooja Malhotra", "email": "pooja@malhotrasteel.in",
                                                    "message": "Hi, we're looking for a consultant to help us hire and train a sales team.", "source": "Email"}})
    await ctx.data.connections.insert({"provider": "gmail", "user_id": owner["_id"], "account": "priya@mehtagrowth.in",
                                       "tokens": __import__("app.integrations.vendors", fromlist=["x"]).encrypt({"access_token": "fake", "refresh_token": "fake",
                                                                                "expires_at": (now() + timedelta(days=365)).isoformat()}),
                                       "lead_finder": True})
    await seed_addons(ctx, owner, team, stages, p2, p3, p4, p5, p8, c5)
    for _ in range(3):
        await dispatch()
        await tick()
    from app.agents.runtime import run_agent
    await run_agent(ws_id, "daily_brief", trigger={"kind": "seed"})
    # Invited but not yet joined (the "new" persona goes through onboarding).
    _ = (aware, tpl, f6, c5, c6, c7, c8, t5)


async def seed_addons(ctx, owner, team, stages, p2, p3, p4, p5, p8, c5):
    """Add-on sample data: rates, time, a budget, a retainer with three closed periods, estimates, client tasks."""
    from datetime import timedelta as td
    from app.core.util import IST
    D = lambda n: (now() - td(days=n)).astimezone(IST).date().isoformat()   # noqa: E731
    svc = {s["name"]: s for s in await ctx.data.services.find({})}
    hour, day = svc.get("Consulting hour"), svc.get("Consulting day")
    # Team: billing roles, cost per hour, available hours.
    for uid, role, cost, hrs in ((owner["_id"], "Partner", 250000, 30), (team["admin"], "Associate", 150000, 40),
                                 (team["manager"], "Associate", 120000, 40), (team["member"], "Analyst", 80000, 40)):
        await call(ctx, "team.set_rates", {"user_id": uid, "billing_role": role, "cost_rate_paise": cost, "available_hours_week": hrs,
                                           "effective_from": D(200)})
    card = (await call(ctx, "rate_cards.list", {}))[0]
    lines = [{"id": l["id"], "target": l["target"], "service_id": l["service_id"], "unit": l["unit"], "rate_paise": l["base_rate_paise"]}
             for l in card["lines"]]
    lines += [{"target": "role", "role": "Partner", "unit": "hour", "rate_paise": 800000},
              {"target": "role", "role": "Associate", "unit": "hour", "rate_paise": 450000},
              {"target": "role", "role": "Analyst", "unit": "hour", "rate_paise": 250000}]
    card = await call(ctx, "rate_cards.save", {"id": card["id"], "name": card["name"], "lines": lines})
    hline = next((l for l in card["lines"] if l["service_id"] == (hour or {}).get("_id")), None)
    if hline:
        nm = (now().astimezone(IST).date().replace(day=1) + td(days=32)).replace(day=1)
        await call(ctx, "rate_changes.schedule", {"line_id": hline["id"], "rate_paise": 650000, "effective_from": nm.isoformat()})
    neg = await call(ctx, "rate_cards.save", {"name": "Ali Exports — agreed rates", "lines": [
        {"target": "service", "service_id": hour["_id"], "unit": "hour", "rate_paise": 500000}] if hour else []})
    await call(ctx, "rate_cards.assign", {"rate_card_id": neg["id"], "contact_id": c5["_id"]})
    # Time on Ali Exports (some unbilled, some non-billable).
    for d, mins, uid, note, task in ((2, 150, owner["_id"], "Gulf market sizing", None), (3, 90, team["member"], "Distributor list", None),
                                     (6, 120, owner["_id"], "Pricing review with Farhan", None), (9, 60, team["member"], "Export docs check", None),
                                     (16, 180, owner["_id"], "Market entry plan draft", None)):
        await call(ctx, "time.log", {"project_id": p5["_id"], "minutes": mins, "date": D(d), "note": note, "user_id": uid,
                                     "service_id": (hour or {}).get("_id")})
    for d, mins, reason, note in ((1, 60, "selling", "Webinar prep"), (4, 45, "admin", "Invoices and GST"), (8, 90, "learning", "Export finance course")):
        await call(ctx, "time.log", {"project_id": p5["_id"], "minutes": mins, "date": D(d), "billable": False, "reason": reason, "note": note})
    # Budget on Iyer Interiors: 40 hours, 34 used (85%, past the 80% alert).
    await call(ctx, "budgets.create", {"project_id": p4["_id"], "type": "time", "amount_hours": 40, "start_date": D(25)})
    six = lambda dd: (now().astimezone(IST) + td(days=dd)).replace(hour=18, minute=0, second=0, microsecond=0).isoformat()   # noqa: E731
    tk = [await call(ctx, "tasks.create", {"title": t_, "project_id": p4["_id"], "due_at": six(dd), "estimate_hours": eh})
          for t_, dd, eh in (("Site survey and measurements", -1, 6), ("Mood boards for three rooms", 4, 8), ("Vendor shortlist", 9, 5))]
    for d, mins, ti in ((20, 300, 0), (15, 360, 0), (12, 420, 1), (7, 480, 1), (3, 480, None)):
        await call(ctx, "time.log", {"project_id": p4["_id"], "minutes": mins, "date": D(d), "task_id": tk[ti]["id"] if ti is not None else None,
                                     "service_id": (hour or {}).get("_id"), "note": "Design work"})
    # Retainer for Shah Hardware with three closed periods (time first, then the retainer closes the past periods).
    start = (now() - td(days=100)).astimezone(IST).date()
    from app.domain.billing.retainers import add_months
    bounds = [add_months(start, i, start.day) for i in range(5)]
    for i, hrs in enumerate((18, 23, 15, 9)):
        a, b = bounds[i], bounds[i + 1]
        span = max(1, (min(b, now().astimezone(IST).date()) - a).days - 1)
        for k in range(3):
            dd = a + td(days=min(span, 3 + k * max(1, span // 3)))
            if dd > now().astimezone(IST).date():
                dd = now().astimezone(IST).date()
            await call(ctx, "time.log", {"project_id": p8["_id"], "minutes": hrs * 20, "date": dd.isoformat(), "user_id": team["member"],
                                         "note": ["Weekly review call", "Sales hiring scorecard", "MIS walkthrough"][k]})
    tpl = await call(ctx, "task_templates.create", {"name": "Monthly retainer checklist", "items": [
        {"title": "Monthly review call", "estimate_hours": 1.5, "due_days": 5}, {"title": "Send the MIS summary", "estimate_hours": 1, "due_days": 7}]})
    rec = await ctx.data.recurring_invoices.find_one({"project_id": p8["_id"]})
    await call(ctx, "retainers.create", {"project_id": p8["_id"], "name": "Advisory retainer", "kind": "hours", "period": "monthly",
                                         "start_date": start.isoformat(), "fee_paise": 5000000, "included_hours": 20, "billing": "advance",
                                         "rollover": {"mode": "capped", "cap_hours": 5, "valid_periods": 1}, "overage": {"mode": "bill"},
                                         "auto_send": True, "task_template_id": tpl["id"], "adopt_recurring_id": (rec or {}).get("_id"),
                                         "end_date": (now() + td(days=25)).astimezone(IST).date().isoformat()})
    for inv in await ctx.data.invoices.find({"project_id": p8["_id"], "status": "sent"}, sort=[("created_at", 1)]):
        if inv.get("retainer_period_id") and (await ctx.data.retainer_periods.get(inv["retainer_period_id"]) or {}).get("status") == "closed":
            await call(ctx, "payments.confirm", {"invoice_id": inv["_id"], "item_id": inv["schedule"][0]["id"], "method": "bank"})
    await call(ctx, "task_templates.create", {"name": "Kickoff checklist", "items": [
        {"title": "Send the welcome pack", "estimate_hours": 1, "due_days": 1}, {"title": "Book the kickoff call", "due_days": 2},
        {"title": "Collect last year's numbers", "estimate_hours": 2, "due_days": 5}]})
    # Estimates: Rao Logistics (final, quoted) and Desai Foods (draft).
    await call(ctx, "notes.add", {"project_id": p3["_id"], "text": "Call: Vikram wants a 6-week pricing study, two days a week."})
    e = await call(ctx, "estimates.draft_from_text", {"project_id": p3["_id"], "text": "a 6-week pricing study, two days a week"})
    await call(ctx, "estimates.update", {"id": e["id"], "contingency_pct": 10})
    await call(ctx, "estimates.finalise", {"id": e["id"]})
    qf = await call(ctx, "estimates.to_quote", {"id": e["id"], "detail": "phase"})
    await call(ctx, "files.send", {"id": qf["id"], "channel": "email"})
    # A sent invoice made from time, with the timesheet under it.
    ti = await call(ctx, "invoices.add_unbilled_time", {"project_id": p5["_id"], "date_to": D(5), "group_by": "task", "timesheet": "full"})
    await call(ctx, "invoices.send", {"id": ti["id"]})
    await call(ctx, "projects.set_revenue_spread", {"id": p3["_id"], "expected_close": (now() + td(days=20)).date().isoformat()})
    await call(ctx, "estimates.create", {"project_id": p2["_id"], "name": "Franchise readiness audit", "phases": [
        {"name": "Discovery", "lines": [{"service_id": (day or {}).get("_id"), "label": "Store visits", "qty": 2, "unit": "day", "user_id": owner["_id"]}]},
        {"name": "Audit", "lines": [{"label": "Analysis", "qty": 4, "unit": "day", "user_id": team["admin"],
                                     "rate_paise": (day or {}).get("rate_paise", 4000000)}]},
        {"name": "Travel", "lines": [{"kind": "expense", "label": "Pune visits", "qty": 2, "cost_paise": 600000, "markup_bp": 1000}]}]})
    # Client tasks: one due soon, one overdue.
    await call(ctx, "client_tasks.assign", {"project_id": p5["_id"], "title": "Share Q3 export figures", "details": "A simple Excel is fine.",
                                            "due_at": six(2), "channel": "email"})
    await call(ctx, "client_tasks.assign", {"project_id": p4["_id"], "title": "Send the floor plans", "due_at": six(-1),
                                            "channel": "email"})
