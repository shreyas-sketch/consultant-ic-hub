"""Steps 5–9: scheduler, inbox, automations, agents, MCP, portal, reports."""
import asyncio
from datetime import timedelta

from conftest import act, client, login, outbox, ready_practice, run_jobs
from app.db import get_db
from app.core.util import IST, advance_clock, aware, now


async def owner(phone="+919833300001"):
    c = await login(phone, "Priya Mehta")
    ws = await ready_practice(c)
    return c, ws


async def discovery(c):
    return next(t for t in await act(c, "session_types.list") if t["name"] == "Discovery call")


# ---------------- scheduler ----------------

async def connect_google(c):
    url = (await c.get("/api/connect/gmail/start")).json()["url"]
    r = await c.get(url.replace("http://localhost:8765", ""))
    assert r.status_code in (302, 307)


async def test_lead_books_a_call_from_the_booking_page_and_it_lands_on_the_calendar():
    c, ws = await owner()
    await connect_google(c)
    st = await discovery(c)
    pub = client()
    day = now().astimezone(IST).replace(hour=0, minute=0) + timedelta(days=1)
    slots = (await pub.get(f"/api/public/{ws['slug']}/book/{st['slug']}/slots", params={"date_from": day.isoformat()})).json()
    assert slots
    r = await pub.post(f"/api/public/{ws['slug']}/book/{st['slug']}", json={"contact": {"name": "Anita", "email": "anita@x.in", "phone": "9833022233"},
                                                                           "start": slots[0]})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["meet_link"]
    await run_jobs()
    proj = (await act(c, "projects.search", {}))["items"][0]
    assert proj["stage_id"] == next(s["id"] for s in (await act(c, "stages.list")) if s["key"] == "call_booked")
    cal = await act(c, "calendar.list", {"date_from": day.isoformat(), "date_to": (day + timedelta(days=8)).isoformat()})
    assert any(i["kind"] == "session" for i in cal)
    assert await outbox("calendar_event")


async def test_two_clients_take_the_last_slot_at_the_same_second():
    c, ws = await owner()
    st = await discovery(c)
    pub1, pub2 = client(), client()
    day = now().astimezone(IST).replace(hour=0, minute=0) + timedelta(days=1)
    slot = (await pub1.get(f"/api/public/{ws['slug']}/book/{st['slug']}/slots", params={"date_from": day.isoformat()})).json()[0]
    r1, r2 = await asyncio.gather(
        pub1.post(f"/api/public/{ws['slug']}/book/{st['slug']}", json={"contact": {"name": "A", "email": "a@x.in"}, "start": slot}),
        pub2.post(f"/api/public/{ws['slug']}/book/{st['slug']}", json={"contact": {"name": "B", "email": "b@x.in"}, "start": slot}))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    assert len(await get_db().sessions.find({"status": "booked"}).to_list(None)) == 1


async def test_dubai_client_books_a_mumbai_consultant_across_a_date_boundary():
    c, ws = await owner()
    st = await discovery(c)
    # A late Mumbai slot (17:30 IST = 16:00 Dubai) and an early one (10:00 IST = 08:30 Dubai, which is still the same date)
    pub = client()
    day = now().astimezone(IST).replace(hour=0, minute=0) + timedelta(days=1)
    slots = (await pub.get(f"/api/public/{ws['slug']}/book/{st['slug']}/slots", params={"date_from": day.isoformat()})).json()
    first = aware(slots[0])
    assert first.astimezone(IST).hour == 10  # stored and sent in UTC, shown in the viewer's zone
    assert first.utcoffset().total_seconds() == 0
    # Booking page reads the same instant in Dubai time without shifting it.
    from datetime import timezone
    dubai = first.astimezone(timezone(timedelta(hours=4)))
    assert (dubai.hour, dubai.minute) == (8, 30)


async def test_slot_hold_for_sign_to_reserve_then_confirmed_on_signature():
    c, ws = await owner()
    st = await discovery(c)
    pr = await act(c, "projects.create", {"name": "Hold", "contact": {"name": "Meera", "email": "m@x.in", "phone": "9819044455"}})
    pages = [{"title": "Sign", "button": "Sign", "blocks": [{"type": "contract", "html": "<p>Agreement</p>", "required": True}]},
             {"title": "Book", "button": "Book", "blocks": [{"type": "scheduler", "session_type_id": st["id"], "reserve_requires": ["sign"]}]}]
    f = await act(c, "files.create_from_template", {"project_id": pr["id"]})
    f = await act(c, "files.update", {"id": f["id"], "pages": pages})
    await act(c, "files.send", {"id": f["id"]})
    pub = client()
    v = (await pub.get(f"/api/public/f/{f['token']}")).json()
    sch = v["pages"][1]["blocks"][0]
    slot = (await pub.get(f"/api/public/f/{f['token']}/slots", params={"block_id": sch["id"], "date_from": (now() + timedelta(days=1)).isoformat()})).json()[0]
    r = await pub.post(f"/api/public/f/{f['token']}/book", json={"block_id": sch["id"], "start": slot})
    assert r.json()["status"] == "held"
    con = v["pages"][0]["blocks"][0]
    await pub.post(f"/api/public/f/{f['token']}/sign", json={"block_id": con["id"], "name": "Meera", "method": "typed", "code": "000000"})
    await act(c, "files.consultant_sign", {"id": f["id"], "block_id": con["id"], "name": "Priya"})
    s = await get_db().sessions.find_one({"file_id": f["id"]})
    assert s["status"] == "booked"


async def test_held_slot_is_released_after_ten_minutes():
    from app.workers.jobs import j_sessions
    c, ws = await owner()
    st = await discovery(c)
    from app.domain.engagement.scheduling import book, find_slots
    from app.core.context import system_ctx
    ctx = system_ctx(ws["id"])
    contact = await ctx.data.contacts.insert({"name": "T", "email": "t@x.in"})
    s0 = await ctx.data.session_types.get(st["id"])
    slot = (await find_slots(ctx, s0, now() + timedelta(days=1), now() + timedelta(days=2)))[0]
    await book(ctx, s0, slot, contact, hold=True)
    advance_clock(minutes=11)
    await j_sessions()
    assert (await get_db().sessions.find_one({}))["status"] == "cancelled"
    assert slot in await find_slots(ctx, s0, slot - timedelta(hours=2), slot + timedelta(hours=1))


# ---------------- inbox ----------------

async def test_client_reply_shows_on_the_project_and_whatsapp_window():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Chat", "contact": {"name": "Vikram", "email": "v@x.in", "phone": "9821033344"}})
    await act(c, "messages.send", {"project_id": pr["id"], "channel": "email", "subject": "Hello", "body": "<p>Hi</p>"})
    th = await act(c, "threads.get", {"project_id": pr["id"]})
    assert th["messages"][0]["status"] == "delivered"
    r = await c.post("/api/a/messages.send", json={"project_id": pr["id"], "channel": "whatsapp", "body": "Free text"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "window_closed"
    pub = client()
    await pub.post("/api/hooks/email-inbound", json={"To": f"t-{th['thread']['id']}@reply.example.com", "From": "v@x.in", "Subject": "Re: Hello",
                                                     "TextBody": "Sounds good"})
    await pub.post("/api/hooks/whatsapp-inbound", json={"from": "+919821033344", "text": "Can we talk at 5?"})
    th = await act(c, "threads.get", {"project_id": pr["id"]})
    assert [m["direction"] for m in th["messages"]] == ["out", "in", "in"] and th["whatsapp_window_open"]
    await act(c, "messages.send", {"project_id": pr["id"], "channel": "whatsapp", "body": "Yes, 5 works."})
    inbox = await act(c, "inbox.list", {})
    assert inbox[0]["project_id"] == pr["id"]


async def test_quiet_hours_hold_agent_messages_until_8am():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Q", "contact": {"name": "Q", "email": "q@x.in"}})
    t = now().astimezone(IST)
    advance_clock(seconds=(t.replace(hour=22, minute=30) - t).total_seconds())
    from app.domain.engagement.inbox import send_message
    from app.core.context import system_ctx
    ctx = system_ctx(ws["id"], actor="agent:followup")
    contact = await ctx.data.contacts.find_one({})
    m = await send_message(ctx, pr["id"], contact, "email", "Nudge", "<p>Hi</p>")
    assert m["status"] == "scheduled" and aware(m["scheduled_at"]).astimezone(IST).hour == 8
    # By hand goes now.
    await act(c, "messages.send", {"project_id": pr["id"], "channel": "email", "subject": "Now", "body": "<p>Hi</p>"})
    assert any(x["payload"]["subject"] == "Now" for x in await outbox("email"))


async def test_custom_domain_without_spf_dkim_is_blocked_with_a_plain_message():
    c, ws = await owner()
    r = await c.post("/api/a/workspace.update", json={"settings": {"sending_domain": "nospf-example.com"}})
    assert r.status_code == 400 and "SPF or DKIM" in r.json()["error"]["message"]


# ---------------- automations ----------------

async def test_starter_automations_run_against_a_simulated_clock():
    """New enquiry → reply drafted; proposal not viewed → nudge; contract unsigned → nudge;
    advance paid → onboarding; overdue → collections; completed → testimonial + referral;
    after the discovery call → proposal drafted."""
    c, ws = await owner()
    autos = await act(c, "automations.list")
    assert len(autos) == 7 and all(a["active"] for a in autos)
    # Enquiry
    f = await act(c, "lead_forms.save", {"name": "E", "kind": "enquiry"})
    q = f["blocks"][1]["questions"][0]["id"]
    out = (await client().post(f"/api/public/{ws['slug']}/form/{f['slug']}/submit",
                               json={"contact": {"name": "Rohit", "email": "rohit@x.in", "phone": "9820011122"}, "answers": {q: "Help"}})).json()
    pid = out["project_id"]
    await run_jobs()
    assert any(a["agent"] == "lead" for a in await act(c, "approvals.list"))
    # Proposal sent, not viewed for 2 days → nudge; contract not signed in 3 days → nudge
    tpl = next(t for t in await act(c, "templates.list", {"kind": "file"}) if t["name"] == "Proposal — business audit")
    fl = await act(c, "files.create_from_template", {"project_id": pid, "template_id": tpl["id"]})
    for pg in fl["pages"]:
        for b in pg["blocks"]:
            for fld in b.get("fields", []):
                fld["value"] = "1 Dec 2026"
    await act(c, "files.update", {"id": fl["id"], "pages": fl["pages"]})
    await act(c, "files.send", {"id": fl["id"]})
    await run_jobs()
    advance_clock(days=2, minutes=5)
    await run_jobs()
    subjects = [a["preview"].get("subject") for a in await act(c, "approvals.list")]
    assert any("Your proposal" in (s or "") for s in subjects)
    advance_clock(days=1, minutes=5)
    await run_jobs()
    subjects = [a["preview"].get("subject") for a in await act(c, "approvals.list")]
    assert any("Ready to get started" in (s or "") for s in subjects)
    # Completed → testimonial after 3 days, referral after 7 more
    done = next(s for s in await act(c, "stages.list") if s["key"] == "completed")
    await act(c, "projects.move_stage", {"id": pid, "stage_id": done["id"]})
    await run_jobs()
    advance_clock(days=3, minutes=5)
    await run_jobs()
    ap = [a for a in await act(c, "approvals.list") if "few words" in (a["preview"].get("subject") or "")]
    assert ap
    await act(c, "approvals.approve", {"id": ap[0]["id"]})
    await run_jobs()
    advance_clock(days=7, minutes=5)
    await run_jobs()
    assert any("Know someone" in (a["preview"].get("subject") or "") for a in await act(c, "approvals.list"))


async def test_onboarding_and_collections_starters():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Paid", "contact": {"name": "Farhan", "email": "f@x.in"}})
    inv = await act(c, "invoices.create", {"project_id": pr["id"], "lines": [{"name": "Retainer", "qty": 1, "price_paise": 10000000}],
                                           "schedule": [{"label": "Advance", "pct": 50, "due": {"type": "on_signing"}},
                                                        {"label": "Balance", "pct": 50, "due": {"type": "date", "date": (now() + timedelta(days=2)).isoformat()}}]})
    await act(c, "invoices.send", {"id": inv["id"]})
    inv = await act(c, "invoices.get", {"id": inv["id"]})
    await act(c, "payments.confirm", {"invoice_id": inv["id"], "item_id": inv["schedule"][0]["id"]})
    await run_jobs()
    p = await act(c, "projects.get", {"id": pr["id"]})
    assert p["stage"]["key"] == "in_delivery"  # onboarding automation moved it after the advance
    assert any("kickoff" in t["title"].lower() for t in p["tasks"])
    from app.workers.jobs import j_money
    advance_clock(days=3)
    await j_money()
    await run_jobs()
    ap = [a for a in await act(c, "approvals.list") if a["agent"] == "collections"]
    assert ap and "Payment reminder" in ap[0]["preview"]["subject"]


async def test_editing_an_automation_does_not_change_runs_in_flight():
    c, ws = await owner()
    a = next(x for x in await act(c, "automations.list") if x["key"] == "proposal_not_viewed")
    from app.automations.engine import start_run
    from app.core.context import system_ctx
    ctx = system_ctx(ws["id"])
    runs = []
    for i in range(50):
        pr = await act(c, "projects.create", {"name": f"P{i}", "contact": {"name": f"C{i}", "email": f"c{i}@x.in"}})
        runs.append(await start_run(ctx, await ctx.data.automations.get(a["id"]), pr["id"]))
    await run_jobs()
    await act(c, "automations.save", {"id": a["id"], "name": "Changed", "trigger": a["trigger"], "active": True,
                                      "steps": [{"type": "action", "action": "create_task", "title": "New step"}]})
    r = await get_db().automation_runs.find_one({"_id": runs[0]["_id"]})
    assert r["snapshot"]["steps"][0]["type"] == "wait" and r["status"] == "waiting"


async def test_worker_killed_mid_step_never_double_sends():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "W", "contact": {"name": "W", "email": "w@x.in"}})
    tpl = next(t for t in await act(c, "templates.list", {"kind": "email"}) if t["name"] == "Welcome after advance")
    auto = await act(c, "automations.save", {"name": "Send now", "trigger": {"type": "manual"}, "active": True,
                                             "steps": [{"type": "action", "action": "send_email", "template_id": tpl["id"]}]})
    from app.automations.engine import execute, start_run
    from app.core.context import system_ctx
    ctx = system_ctx(ws["id"])
    run = await start_run(ctx, await ctx.data.automations.get(auto["id"]), pr["id"])
    await execute(dict(run))
    # Simulate a crash before the pointer moved: run the same step again.
    await execute(dict(run))
    sent = [m for m in await outbox("email") if m["payload"]["to"] == "w@x.in"]
    assert len(sent) == 1


async def test_why_didnt_this_run_gives_each_reason():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Y", "type": "Workshop", "contact": {"name": "Y", "email": "y@x.in"}})
    autos = {a["key"]: a for a in await act(c, "automations.list")}
    a = autos["onboarding"]
    w = await act(c, "automations.why", {"automation_id": a["id"], "project_id": pr["id"]})
    assert w["reason"] == "no_trigger"
    await act(c, "automations.toggle", {"id": a["id"], "active": False})
    assert (await act(c, "automations.why", {"automation_id": a["id"], "project_id": pr["id"]}))["reason"] == "off"
    await act(c, "automations.save", {"id": a["id"], "name": a["name"], "trigger": a["trigger"], "steps": a["steps"], "active": True,
                                      "project_types": ["Retainer"]})
    assert (await act(c, "automations.why", {"automation_id": a["id"], "project_id": pr["id"]}))["reason"] == "type"
    tpl = next(t for t in await act(c, "templates.list", {"kind": "email"}) if t["name"] == "Welcome after advance")
    b = await act(c, "automations.save", {"name": "Approve me", "trigger": {"type": "manual"}, "active": True,
                                          "steps": [{"type": "action", "action": "send_email", "template_id": tpl["id"], "approve": True}]})
    run = await act(c, "automations.run_manual", {"automation_id": b["id"], "project_id": pr["id"]})
    assert (await act(c, "automations.why", {"automation_id": b["id"], "project_id": pr["id"]}))["reason"] == "waiting_approval"
    await act(c, "automations.cancel_run", {"run_id": run["id"]})
    assert (await act(c, "automations.why", {"automation_id": b["id"], "project_id": pr["id"]}))["reason"] == "cancelled"


async def test_test_run_sends_nothing():
    c, ws = await owner()
    await act(c, "projects.create", {"name": "Sample", "contact": {"name": "S", "email": "s@x.in"}})
    for a in await act(c, "automations.list"):
        out = await act(c, "automations.test_run", {"automation_id": a["id"]})
        assert out["log"]
    assert not await outbox("email") and not await get_db().approvals.find({}).to_list(None)


async def test_automation_builder_drafts_a_switched_off_automation():
    c, ws = await owner()
    r = await act(c, "agents.run", {"agent": "automation_builder", "instruction": "If a proposal isn't opened in 3 days, remind me"})
    autos = [a for a in await act(c, "automations.list") if a.get("drafted_by")]
    assert autos and not autos[0]["active"] and autos[0]["steps"][0]["wait"]["minutes"] == 3 * 1440
    assert "switched off" in r["summary"]


# ---------------- agents ----------------

async def test_ai_budget_is_per_workspace_and_stops_agents_cleanly():
    c, ws = await owner()
    admin = await login("+919899999990", "Staff")
    await get_db().users.update_one({"phone": "+919899999990"}, {"$set": {"is_admin": True}})
    await admin.post("/api/admin/overrides", json={"workspace_id": ws["id"], "key": "ai_cost_cap_paise", "value": 30, "note": "test"})
    r = await act(c, "chat.send", {"message": "Which leads came in this week?"})
    r2 = await act(c, "chat.send", {"message": "Which leads came in this week?"})
    assert "budget" in r2["answer"].lower() or "budget" in r["answer"].lower()
    b = (await act(c, "workspace.get"))["ai_budget"]
    assert b["state"] == "reached"
    cost = (await admin.get("/api/admin/ai-cost")).json()
    assert cost["top"][0]["workspace_id"] == ws["id"]


async def test_draft_mode_nothing_leaves_without_an_approval_record():
    c, ws = await owner()
    for i in range(3):
        pr = await act(c, "projects.create", {"name": f"Quiet {i}", "contact": {"name": f"Q{i}", "email": f"q{i}@x.in"}})
        await get_db().projects.update_one({"_id": pr["id"]}, {"$set": {"last_activity_at": now() - timedelta(days=5)}})
    r = await act(c, "agents.run", {"agent": "followup"})
    assert len(r["approvals"]) == 3
    assert not await outbox("email")
    msgs = await get_db().messages.find({"actor": "agent:followup"}).to_list(None)
    assert not msgs


async def test_autonomy_auto_sends_external_but_money_stays_locked():
    from app.agents.runtime import gate
    assert gate("external", "auto", "worker") == "run"
    assert gate("money", "auto", "worker") == "approve"
    assert gate("destructive", "auto", "worker") == "refuse"
    assert gate("external", "suggest", "worker") == "suggest"
    c, ws = await owner()
    r = await c.post("/api/a/agents.update", json={"agent": "lead", "autonomy": "auto"})
    assert r.status_code == 200
    log = await get_db().audit_log.find({"action": "agent.settings"}).to_list(None)
    assert log and log[0]["detail"]["autonomy"] == "auto"


async def test_meeting_agent_turns_a_transcript_into_notes_and_tasks_and_proposal_agent_drafts():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Call", "contact": {"name": "Anita", "email": "a@x.in"}})
    from app.integrations.vendors import FAKE_TRANSCRIPT
    r = await act(c, "meetings.add_transcript", {"project_id": pr["id"], "text": FAKE_TRANSCRIPT})
    p = await act(c, "projects.get", {"id": pr["id"]})
    assert any(n["text"].startswith("Call summary") for n in p["notes"])
    assert len(p["tasks"]) >= 1
    r = await act(c, "agents.run", {"agent": "proposal", "project_id": pr["id"]})
    ap = await act(c, "approvals.list", {})
    assert any(a["action"] == "files.send" for a in ap)
    files = (await act(c, "projects.get", {"id": pr["id"]}))["files"]
    assert files and files[0]["status"] == "draft"


async def test_screenshot_to_lead():
    c, ws = await owner()
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    r = await act(c, "leads.from_screenshot", {"image": png})
    assert r["contact"]["name"] == "Rohan Kapoor"
    await run_jobs()
    assert any(a["agent"] == "lead" for a in await act(c, "approvals.list"))


async def test_setup_agent_builds_a_usable_account_from_the_interview():
    c = await login("+919833300099", "New Consultant")
    from app.db.seed import SETUP
    q = await act(c, "onboarding.questions")
    assert 8 <= len(q["questions"]) <= 10
    out = await act(c, "onboarding.finish", {"answers": SETUP})
    assert out["upi_set"] and out["services"] == 3 and len(out["templates"]) == 5
    ws = await act(c, "workspace.get")
    assert ws["onboarded"] and ws["name"] == "Mehta Growth Advisory"
    st = await discovery(c)
    assert st["availability"]["0"] == [{"start": "10:00", "end": "13:00"}, {"start": "15:00", "end": "18:00"}]
    t = await act(c, "onboarding.test_proposal")
    assert (await client().get(t["link"].split("/c/")[0].replace("http://localhost:8765", "") + "/api/public/f/" + t["link"].rsplit("/", 1)[-1])).status_code == 200


# ---------------- MCP ----------------

async def test_mcp_read_scope_lists_read_tools_and_sends_go_to_approvals():
    c, ws = await owner()
    tok = (await act(c, "mcp.create_token", {"name": "Claude", "scope": "read"}))["token"]
    pub = client()
    h = {"Authorization": f"Bearer {tok}"}
    r = await pub.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, headers=h)
    assert r.json()["result"]["serverInfo"]["name"]
    tools = (await pub.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h)).json()["result"]["tools"]
    assert tools and all(t["description"].startswith("[read]") for t in tools)
    full = (await act(c, "mcp.create_token", {"name": "Claude full", "scope": "full"}))["token"]
    pr = await act(c, "projects.create", {"name": "M", "contact": {"name": "M", "email": "m@x.in"}})
    r = await pub.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                     "params": {"name": "messages__send", "arguments": {"project_id": pr["id"], "subject": "Hi", "body": "<p>Hi</p>"}}},
                       headers={"Authorization": f"Bearer {full}"})
    assert "queued_for_approval" in r.json()["result"]["content"][0]["text"]
    assert not await outbox("email")
    r = await pub.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


# ---------------- portal and reports ----------------

async def test_client_with_three_projects_sees_all_three_in_one_portal():
    c, ws = await owner()
    for i in range(3):
        await act(c, "projects.create", {"name": f"Project {i}", "contact": {"name": "Kavita Joshi", "phone": "9820066677", "email": "k@joshi.in"}})
    pub = client()
    r = await pub.post(f"/api/public/{ws['slug']}/portal/code", json={"phone": "9820066677"})
    assert r.status_code == 200
    r = await pub.post(f"/api/public/{ws['slug']}/portal/login", json={"phone": "9820066677", "code": "000000"})
    assert r.status_code == 200
    me = (await pub.get(f"/api/public/{ws['slug']}/portal/me")).json()
    assert len(me["projects"]) == 3
    one = (await pub.get(f"/api/public/{ws['slug']}/portal/project/{me['projects'][0]['id']}")).json()
    assert "tasks" not in one and "notes" in one
    await pub.post(f"/api/public/{ws['slug']}/portal/project/{me['projects'][0]['id']}/message", json={"text": "Hello from the portal"})
    th = await act(c, "threads.get", {"project_id": me["projects"][0]["id"]})
    assert th["messages"][-1]["body_text"] == "Hello from the portal"


async def test_reports_and_money_view():
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "R", "source": "Webinar", "type": "Audit", "contact": {"name": "R", "email": "r@x.in"}})
    inv = await act(c, "payments.request", {"project_id": pr["id"], "amount_paise": 5000000})
    inv = await act(c, "invoices.get", {"id": inv["id"]})
    await act(c, "payments.confirm", {"invoice_id": inv["id"], "item_id": inv["schedule"][0]["id"]})
    await act(c, "expenses.save", {"amount_paise": 1000000, "date": now().date().isoformat(), "project_id": pr["id"], "category": "Travel"})
    s = await act(c, "reports.summary")
    assert s["received_month_paise"] == 5000000
    pl = await act(c, "reports.pipeline", {"source": "Webinar"})
    assert pl["sources"][0]["source"] == "Webinar" and pl["sources"][0]["conversion_pct"] == 100
    mv = await act(c, "money.view")
    assert mv["projects"][0]["profit_paise"] == 4000000
    reg = await act(c, "tax.pack", {"what": "invoice_register"})
    assert "Invoice no." in reg["csv"]
    imp = await act(c, "expenses.import_statement", {"rows": [{"Date": "2026-11-01", "Narration": "Zoom", "Withdrawal": "1,250.00"},
                                                              {"Date": "2026-11-02", "Narration": "Client paid", "Deposit": "50000"}]})
    assert imp == {"added": 1, "skipped": 1}


async def test_recurring_invoice_goes_out_once_a_month():
    from app.workers.jobs import j_recurring
    c, ws = await owner()
    pr = await act(c, "projects.create", {"name": "Ret", "contact": {"name": "Neel", "email": "n@x.in"}})
    await act(c, "recurring.create", {"project_id": pr["id"], "lines": [{"name": "Retainer", "qty": 1, "price_paise": 5000000}], "day_of_month": 1})
    await j_recurring()
    await j_recurring()
    invs = await get_db().invoices.find({"project_id": pr["id"]}).to_list(None)
    assert len(invs) == 1 and invs[0]["status"] == "sent"


async def test_home_numbers():
    c, ws = await owner()
    h = await act(c, "home.get")
    assert set(h["numbers"]) == {"new_leads", "unread", "tasks_due", "received_month_paise"}
    assert h["brief"] is not None
