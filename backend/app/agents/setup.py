"""Setup agent: a short interview that ends in a ready account.

About 8–10 questions. The answers build: the practice profile, services and
prices, pipeline tweaks, five core templates, the discovery-call session type
and the starter automations (already in place from sign-up).
"""
import copy
import re

from app.integrations import llm
from app.domain.documents.defaults import proposal_file
from app.core import limits
from app.db import get_db
from app.core.util import AppError, new_id, now

QUESTIONS = [
    {"id": "name", "q": "What's your name, and what should we call your practice?", "placeholder": "Priya Mehta — Mehta Growth Advisory"},
    {"id": "who", "q": "Who do you help? Describe your ideal client in one line.", "placeholder": "Founders of ₹5–50 Cr manufacturing businesses"},
    {"id": "problem", "q": "What problem do you solve for them?", "placeholder": "Sales depend on the founder; no repeatable process"},
    {"id": "offers", "q": "What do you sell? List your offers, one per line, with a price.",
     "placeholder": "Business audit — ₹75,000\nAdvisory retainer — ₹50,000 a month\nTeam workshop — ₹60,000"},
    {"id": "rates", "q": "Do you also charge by the hour or the day? What are your rates? (Leave blank if you only charge fixed fees.)",
     "placeholder": "₹6,000 an hour, ₹40,000 a day"},
    {"id": "how", "q": "How do clients usually find you, and how do you sell? (webinar, referrals, LinkedIn, calls…)",
     "placeholder": "Webinars and referrals. A free 30-minute call, then a proposal."},
    {"id": "call", "q": "How long is your first call, and which days and hours suit you?", "placeholder": "30 minutes, Mon–Fri, 10am–1pm and 3pm–6pm"},
    {"id": "payment", "q": "How do you like to be paid? (e.g. 50% advance, rest on delivery)", "placeholder": "50% advance, 50% after 30 days"},
    {"id": "upi", "q": "Your UPI ID, so clients can pay you directly (you can add bank details later).", "placeholder": "priya@okhdfcbank"},
    {"id": "tone", "q": "How should messages sound — warm and casual, or formal?", "placeholder": "Warm, but professional"},
]


def parse_offers(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        m = re.search(r"₹?\s?([\d,]+(?:\.\d+)?)\s*(k|l|lakh|lac)?", line, re.I)
        price = 0
        if m:
            v = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            v *= 1000 if unit == "k" else 100000 if unit in ("l", "lakh", "lac") else 1
            price = int(v * 100)
        name = re.split(r"[—\-–:]\s*₹?|\s₹", line)[0].strip() or line
        monthly = bool(re.search(r"month|/mo|retainer", line, re.I))
        out.append({"id": new_id()[:10], "name": name[:80], "desc": "Monthly" if monthly else "", "price_paise": price, "qty": 1,
                    "kind": "package", "monthly": monthly})
    return out


def parse_hours(text):
    """'30 minutes, Mon–Fri, 10am–1pm and 3pm–6pm' -> (30, {weekday: windows})."""
    t = (text or "").lower()
    dur = int((re.search(r"(\d+)\s*(?:min|minute)", t) or [None, 30])[1])
    wins = []
    rx = r"(\d{1,2})(?::\d{2})?\s*(am|pm)?\s*(?:–|-|to)\s*(\d{1,2})(?::\d{2})?\s*(am|pm)?"
    for a, ap, b, bp in re.findall(rx, t):
        h1, h2 = int(a), int(b)
        ap = ap or (bp if h1 <= h2 else "am")
        if ap == "pm" and h1 < 12:
            h1 += 12
        if bp == "pm" and h2 < 12:
            h2 += 12
        if not ap and not bp and h1 < 8:
            h1, h2 = h1 + 12, h2 + 12 if h2 < 12 else h2
        if 0 <= h1 < h2 <= 23:
            wins.append({"start": f"{h1:02d}:00", "end": f"{h2:02d}:00"})
    days = list(range(0, 5))
    if "sat" in t:
        days.append(5)
    if "sun" in t:
        days.append(6)
    wins = wins or [{"start": "10:00", "end": "13:00"}, {"start": "15:00", "end": "18:00"}]
    return (dur if 10 <= dur <= 180 else 30), {str(d): wins for d in days}


def parse_payment(text):
    m = re.search(r"(\d{1,3})\s*%", text or "")
    adv = int(m.group(1)) if m and 0 < int(m.group(1)) < 100 else 50
    days = int((re.search(r"(\d+)\s*days?", text or "") or [None, 30])[1])
    return [{"label": "Advance on signing", "pct": adv, "due": {"type": "on_signing"}},
            {"label": "Balance", "pct": 100 - adv, "due": {"type": "after_previous", "days": days}}]


def preview(answers):
    offers = parse_offers(answers.get("offers"))
    dur, avail = parse_hours(answers.get("call"))
    return {"services": [{"name": o["name"], "price_paise": o["price_paise"], "monthly": o["monthly"]} for o in offers],
            "pipeline": ["Enquiry", "Call booked", "Proposal sent", "Contract signed", "Advance paid", "In delivery", "Completed"],
            "first_proposal": f"Proposal for {(answers.get('who') or 'your client')[:60]}",
            "discovery_call": {"minutes": dur, "days": len(avail)}, "schedule": parse_payment(answers.get("payment"))}


async def build_account(ctx, answers):
    """Apply the interview. Internal actions only: nothing is sent to any client."""
    db = get_db()
    ws = await ctx.ws()
    name_line = answers.get("name") or ""
    person = re.split(r"\s[—\-–]\s|,", name_line)[0].strip() if name_line else ""
    practice = (re.split(r"\s[—\-–]\s|,", name_line) + [""])[1].strip() if name_line else ""
    practice = practice or ws["name"]
    offers = parse_offers(answers.get("offers"))
    who = (answers.get("who") or "business owners").strip().rstrip(".")
    who = who[0].lower() + who[1:] if len(who) > 1 and who[1].islower() else who
    problem = (answers.get("problem") or "").strip().rstrip(".")
    fake = {"intro": f"I work with {who}." + (f" The problem I usually solve: {problem[0].lower() + problem[1:]}." if problem else "")
                     + " Here's how we could work together.",
            "enquiry_reply": "<p>Hi {{client.first_name}},</p><p>Thank you for reaching out. I work with "
                             f"{who}, so I'd love to hear more about your business. "
                             "Could we do a short call? Pick a time here: {{booking.link}}</p><p>Speak soon,<br>{{consultant.name}}</p>"}
    data, res = await llm.complete_json("large", "You set up a consultant's account. Write in their voice: " + (answers.get("tone") or "warm"),
                                        f"<client_data>{answers}</client_data>\nReturn JSON with 'intro' (2 sentences for proposals) and "
                                        "'enquiry_reply' (short HTML email with {{client.first_name}}, {{booking.link}}, {{consultant.name}}).", fake)
    await limits.add_ai_cost(ctx.ws_id, ctx.user_id, res["cost_paise"])
    upi = (answers.get("upi") or "").strip()
    ch = {"name": practice, "onboarded": True, "profile.practice_name": practice, "profile.consultant_name": person or ws["profile"].get("consultant_name"),
          "invoice.payee_name": person or practice,
          "setup": {"ideal_client": answers.get("who"), "problem": answers.get("problem"), "offers": [o["name"] for o in offers],
                    "how_they_sell": answers.get("how"), "tone": answers.get("tone"), "answers": answers, "done_at": now()}}
    if upi and re.match(r"^[\w.\-]{1,256}@[a-zA-Z]{2,64}$", upi):
        ch["invoice.upi_id"] = upi
    await db.workspaces.update_one({"_id": ctx.ws_id}, {"$set": ch})
    ctx._ws = None
    if person:
        await db.users.update_one({"_id": ws["owner_id"], "name": ""}, {"$set": {"name": person}})
    # Service packages as templates, and the first service library and rate card.
    for o in offers:
        await ctx.data.templates.insert({"kind": "package", "name": o["name"], "body": o})
    from app.domain.billing.rates import setup_from_interview
    await setup_from_interview(ctx, offers, answers.get("rates"))
    # 1–3: a proposal per offer type, priced from their offers.
    sched = parse_payment(answers.get("payment"))
    made = []
    base = proposal_file("retainer")
    pages = copy.deepcopy(base["pages"])
    for pg in pages:
        for b in pg["blocks"]:
            if b["type"] == "text" and "<h1>" in b.get("html", ""):
                b["html"] = f"<h1>Proposal</h1><p>Hi {{{{client.first_name}}}}, {data.get('intro') or fake['intro']}</p>"
            if b["type"] == "services" and offers:
                b["items"] = [dict(o, kind="package") for o in offers[:4]]
            if b["type"] == "invoice":
                b["schedule"] = sched
    t = await ctx.data.templates.insert({"kind": "file", "name": "My proposal", "body": {"pages": pages}, "by_setup": True})
    made.append(t["name"])
    # 4: the enquiry reply in their voice.
    er = await ctx.data.templates.find_one({"gallery_key": "enquiry_reply"})
    if er:
        await ctx.data.templates.update({"_id": er["_id"]}, {"body": dict(er["body"], html=data.get("enquiry_reply") or fake["enquiry_reply"])})
        made.append(er["name"])
    # 5: the discovery-call booking file and session type with their hours.
    dur, avail = parse_hours(answers.get("call"))
    st = await ctx.data.session_types.find_one({"key": "discovery"})
    if st:
        await ctx.data.session_types.update({"_id": st["_id"]}, {"duration": dur, "increment": dur, "availability": avail})
    made += ["Discovery-call booking", "Onboarding questionnaire", "Consulting agreement"]
    from app.core.events import audit
    await audit(ctx, "setup.completed", ctx.ws_id, {"templates": made})
    return {"ok": True, "templates": made, "services": len(offers), "upi_set": "invoice.upi_id" in ch, "proposal_template_id": t["_id"]}


_ = AppError
