"""Starter content every new practice gets: pipeline stages, consulting templates,
a discovery-call session type and the seven starter automations.

All wording here is our own, written for consultants.
"""
from core.util import new_id

DEFAULT_STAGES = [
    ("Enquiry", "opportunity", "enquiry"),
    ("Call booked", "opportunity", "call_booked"),
    ("Proposal sent", "opportunity", "proposal_sent"),
    ("Contract signed", "booked", "contract_signed"),
    ("Advance paid", "booked", "advance_paid"),
    ("In delivery", "booked", "in_delivery"),
    ("Completed", "booked", "completed"),
]

LEAD_SOURCES = ["Webinar", "Referral", "Client referral", "LinkedIn", "Instagram", "WhatsApp", "Website", "Email", "Event", "Other"]
PROJECT_TYPES = ["Audit", "Retainer", "Workshop", "Advisory", "Discovery call"]
LOST_REASONS = ["Won elsewhere", "No budget", "No reply", "Not a fit"]

# Stage rules: when this event happens, move the project forward to this stage.
# A rule never moves a project backwards. They fire whoever sent the message.
DEFAULT_STAGE_RULES = [
    {"event": "session.scheduled", "stage_key": "call_booked", "enabled": True, "label": "A call is booked"},
    {"event": "file.sent", "stage_key": "proposal_sent", "enabled": True, "label": "A client file or invoice is sent"},
    {"event": "invoice.sent", "stage_key": "proposal_sent", "enabled": True, "label": "An invoice is sent"},
    {"event": "contract.fully_signed", "stage_key": "contract_signed", "enabled": True, "label": "The contract is signed"},
    {"event": "payment.first_paid", "stage_key": "advance_paid", "enabled": True, "label": "The first payment is confirmed"},
]


def _b(t, **kw):
    return {"id": new_id()[:10], "type": t, **kw}


def _page(title, button, *blocks):
    return {"id": new_id()[:10], "title": title, "button": button, "blocks": list(blocks)}


AGREEMENT_TEXT = """<h2>Consulting agreement</h2>
<p>This agreement is between <b>{{practice.name}}</b> ("the Consultant") and <b>{{client.name}}</b>{{client.company_suffix}} ("the Client"), dated {{today}}.</p>
<h3>1. The work</h3>
<p>The Consultant will deliver the services the Client chose in this file:</p>
{{services.recap}}
<p>Work starts on {{field:start_date}} and is planned to finish by {{field:end_date}}.</p>
<h3>2. Fees and payment</h3>
<p>The total fee is {{project.value}}. Payments are due as follows:</p>
{{payments.recap}}
<p>The Client pays the Consultant directly by UPI or bank transfer, using the details on the invoice.</p>
{{late_fee_clause}}
<h3>3. What the Client provides</h3>
<p>Timely access to the people, data and decisions the work needs. Delays on the Client's side may move the timeline.</p>
<h3>4. Confidentiality</h3>
<p>Both sides keep the other's business information private, during this engagement and after it ends.</p>
<h3>5. Ownership</h3>
<p>Once paid in full, the Client owns the final documents made for them. The Consultant keeps their own methods, tools and templates.</p>
<h3>6. Ending early</h3>
<p>Either side can end this agreement with 15 days' written notice. Work done up to that date is paid for.</p>
<h3>7. Limits</h3>
<p>The Consultant gives advice in good faith. Business results depend on many things outside the Consultant's control and are not guaranteed.</p>
<h3>8. Law</h3>
<p>This agreement follows the laws of India. Courts in {{field:city}} have jurisdiction.</p>"""

LATE_FEE_CLAUSE = "<p>If a payment is more than 30 days late, a one-time late fee of {{late_fee.pct}} of that payment may be added. It is never added more than once and never compounds.</p>"

NDA_TEXT = """<h2>Mutual non-disclosure agreement</h2>
<p>Between <b>{{practice.name}}</b> and <b>{{client.name}}</b>{{client.company_suffix}}, dated {{today}}.</p>
<p>1. Each side may share private business information with the other to discuss working together.</p>
<p>2. The other side will use it only for that purpose, keep it private and share it only with people who need it.</p>
<p>3. This does not cover information that is already public, already known, or that the law requires to be shared.</p>
<p>4. This agreement lasts for {{field:years}} years from today.</p>
<p>5. It follows the laws of India.</p>"""


def proposal_file(kind):
    packs = {
        "audit": [("Business health audit", "Two weeks. Interviews, numbers review, a written report and a 90-minute walkthrough.", 7500000),
                  ("Audit + 30-day action plan", "Everything in the audit, plus a week-by-week plan and two follow-up calls.", 12000000)],
        "retainer": [("Advisory retainer — 3 months", "Weekly 60-minute calls, WhatsApp access on working days, one review of key decisions each week.", 15000000),
                     ("Advisory retainer — 6 months", "The same, for six months, with a mid-point strategy day.", 27000000)],
        "workshop": [("Half-day team workshop", "Up to 15 people, on site or online, with a workbook and a recording.", 6000000),
                     ("Full-day workshop + follow-up", "A full day, a workbook and a 60-minute follow-up session two weeks later.", 10000000)],
    }[kind]
    title = {"audit": "Business audit proposal", "retainer": "Advisory retainer proposal", "workshop": "Workshop proposal"}[kind]
    items = [{"id": new_id()[:10], "name": n, "desc": d, "price_paise": p, "qty": 1, "kind": "package"} for n, d, p in packs]
    items.append({"id": new_id()[:10], "name": "Extra strategy session", "desc": "One more 90-minute session, any time during the engagement.",
                  "price_paise": 1500000, "qty": 1, "kind": "addon"})
    return {"pages": [
        _page("Welcome", "Review your options",
              _b("company"),
              _b("text", html=f"<h1>{title}</h1><p>Hi {{{{client.first_name}}}}, thank you for the conversation. "
                               "Here is what I suggest, based on what you shared. Pick the option that suits you best.</p>"),
              _b("timeline", items=[{"date": "Week 1", "title": "Kickoff and discovery"},
                                    {"date": "Weeks 2–3", "title": "Work and reviews"},
                                    {"date": "Week 4", "title": "Final walkthrough"}])),
        _page("Choose", "Review the agreement",
              _b("services", select="single", items=items, feeds_invoice=True)),
        _page("Agreement", "Sign and continue",
              _b("contract", html=AGREEMENT_TEXT, required=True,
                 fields=[{"key": "start_date", "label": "Start date", "permission": "consultant", "value": ""},
                         {"key": "end_date", "label": "End date", "permission": "consultant", "value": ""},
                         {"key": "city", "label": "City for jurisdiction", "permission": "consultant", "value": "Mumbai"}],
                 signers=[])),
        _page("Pay", "Submit",
              _b("invoice", invoice_id=None, schedule=[{"label": "Advance on signing", "pct": 50, "due": {"type": "on_signing"}},
                                                       {"label": "Balance", "pct": 50, "due": {"type": "after_previous", "days": 30}}])),
        _page("Thank you", "",
              _b("thankyou", html="<h2>Thank you!</h2><p>I'll confirm your payment and send a kickoff invite within one working day.</p>")),
    ]}


def booking_file():
    return {"pages": [
        _page("Book", "Confirm booking",
              _b("company"),
              _b("text", html="<h1>Book your discovery call</h1><p>A free 30-minute call to understand your business and see if we're a fit. Pick a time that works for you.</p>"),
              _b("questions", questions=[
                  {"id": "q_goal", "label": "What would you like help with?", "kind": "long", "required": True},
                  {"id": "q_rev", "label": "Rough yearly revenue", "kind": "single", "required": False,
                   "options": ["Under ₹25 L", "₹25 L – ₹1 Cr", "₹1 Cr – ₹5 Cr", "Above ₹5 Cr"]}]),
              _b("scheduler", session_type_id=None)),
        _page("Thank you", "", _b("thankyou", html="<h2>You're booked</h2><p>You'll get a confirmation with the call link on WhatsApp and email.</p>")),
    ]}


def onboarding_file():
    return {"pages": [
        _page("Onboarding", "Submit",
              _b("text", html="<h1>Welcome aboard, {{client.first_name}}</h1><p>A few questions so our kickoff call is useful from minute one.</p>"),
              _b("questions", questions=[
                  {"id": "q1", "label": "What does success look like in 90 days?", "kind": "long", "required": True},
                  {"id": "q2", "label": "Who else should join our calls?", "kind": "short", "required": False},
                  {"id": "q3", "label": "Your biggest constraint right now", "kind": "single", "required": True,
                   "options": ["Time", "Team", "Cash flow", "Sales", "Clarity"]},
                  {"id": "q4", "label": "Share any reports or documents that help", "kind": "file", "required": False}])),
        _page("Done", "", _b("thankyou", html="<h2>Thank you</h2><p>See you at the kickoff.</p>")),
    ]}


EMAILS = {
    "enquiry_reply": ("Enquiry reply", "Thanks for reaching out, {{client.first_name}}",
                      "<p>Hi {{client.first_name}},</p><p>Thank you for getting in touch. I'd love to understand your business better.</p>"
                      "<p>You can pick a time for a short call here: {{booking.link}}</p><p>Speak soon,<br>{{consultant.name}}</p>"),
    "call_reminder": ("Discovery call reminder", "Our call on {{session.date}}",
                      "<p>Hi {{client.first_name}}, a quick reminder about our call on {{session.date}} at {{session.time}}.</p><p>Link: {{session.link}}</p>"),
    "no_show": ("No-show follow-up", "Sorry we missed each other",
                "<p>Hi {{client.first_name}}, looks like we missed each other today. No problem — pick another time here: {{booking.link}}</p>"),
    "proposal_nudge": ("Proposal not viewed", "Your proposal from {{practice.name}}",
                       "<p>Hi {{client.first_name}}, just checking you got the proposal I sent. Here is the link again: {{file.link}}</p>"
                       "<p>Happy to walk you through it on a quick call.</p>"),
    "contract_nudge": ("Contract not signed", "Ready to get started?",
                       "<p>Hi {{client.first_name}}, the agreement is ready for your signature whenever you are: {{file.link}}</p>"
                       "<p>If anything needs changing, just reply.</p>"),
    "welcome": ("Welcome after advance", "Welcome aboard, {{client.first_name}}",
                "<p>Hi {{client.first_name}}, thank you — your advance is confirmed. A short onboarding form is on its way so we can start strong.</p>"),
    "payment_reminder": ("Payment reminder", "Payment due: {{invoice.amount_due}}",
                         "<p>Hi {{client.first_name}}, a friendly reminder that {{invoice.amount_due}} is due on {{invoice.due_date}}.</p>"
                         "<p>You can pay by UPI or bank transfer here: {{invoice.link}}</p>"),
    "testimonial": ("Testimonial request", "Could you share a few words?",
                    "<p>Hi {{client.first_name}}, it was a pleasure working with you. Would you write two or three lines about the experience?"
                    " Just reply to this email.</p>"),
    "referral": ("Referral request", "Know someone I could help?",
                 "<p>Hi {{client.first_name}}, if you know another business owner facing similar challenges, I'd be grateful for an introduction.</p>"),
}


def gallery():
    """The starter template gallery (consulting). Returned fresh each time."""
    g = []
    for key, (name, subject, body) in EMAILS.items():
        g.append({"key": key, "kind": "email", "name": name, "body": {"subject": subject, "html": body}})
    g += [
        {"key": "discovery_booking", "kind": "file", "name": "Discovery-call booking", "body": booking_file()},
        {"key": "proposal_audit", "kind": "file", "name": "Proposal — business audit", "body": proposal_file("audit")},
        {"key": "proposal_retainer", "kind": "file", "name": "Proposal — advisory retainer", "body": proposal_file("retainer")},
        {"key": "proposal_workshop", "kind": "file", "name": "Proposal — workshop", "body": proposal_file("workshop")},
        {"key": "onboarding", "kind": "file", "name": "Onboarding questionnaire", "body": onboarding_file()},
        {"key": "agreement", "kind": "contract", "name": "Consulting agreement", "body": {"html": AGREEMENT_TEXT}},
        {"key": "nda", "kind": "contract", "name": "Mutual NDA", "body": {"html": NDA_TEXT}},
        {"key": "retainer_invoice", "kind": "invoice", "name": "Monthly retainer invoice",
         "body": {"lines": [{"name": "Advisory retainer — monthly fee", "qty": 1, "price_paise": 5000000}]}},
    ]
    return g


def _s(t, **kw):
    return {"id": new_id()[:10], "type": t, **kw}


def starter_automations(tpl):
    """tpl: dict key -> template id in this workspace."""
    return [
        {"key": "new_enquiry", "name": "New enquiry: instant reply", "trigger": {"type": "lead_form.submitted"},
         "steps": [_s("action", action="run_agent", agent="lead", instruction="Reply to this new enquiry and offer call slots.",
                      fallback_template_id=tpl["enquiry_reply"])]},
        {"key": "after_discovery", "name": "After the discovery call", "trigger": {"type": "session.ended", "session_type_key": "discovery"},
         "steps": [_s("wait", wait={"kind": "time", "minutes": 30}),
                   _s("condition", cond={"kind": "session_no_show"},
                      yes=[_s("action", action="send_email", template_id=tpl["no_show"], approve=True)],
                      no=[_s("action", action="run_agent", agent="proposal", instruction="Draft the proposal from the call notes.")])]},
        {"key": "proposal_not_viewed", "name": "Proposal not viewed in 2 days", "trigger": {"type": "file.sent"},
         "steps": [_s("wait", wait={"kind": "time", "minutes": 2 * 1440}),
                   _s("condition", cond={"kind": "file_viewed"}, yes=[],
                      no=[_s("action", action="send_email", template_id=tpl["proposal_nudge"], approve=True)])]},
        {"key": "contract_not_signed", "name": "Contract not signed in 3 days", "trigger": {"type": "file.sent", "has_contract": True},
         "steps": [_s("wait", wait={"kind": "event", "event": "contract.fully_signed", "limit_minutes": 3 * 1440}),
                   _s("condition", cond={"kind": "contract_signed"}, yes=[],
                      no=[_s("action", action="send_email", template_id=tpl["contract_nudge"], approve=True)])]},
        {"key": "onboarding", "name": "Onboarding after advance paid", "trigger": {"type": "payment.first_paid"},
         "steps": [_s("action", action="move_stage", stage_key="in_delivery"),
                   _s("action", action="create_task", title="Schedule the kickoff call", due_minutes=2 * 1440),
                   _s("action", action="send_email", template_id=tpl["welcome"], approve=True),
                   _s("action", action="send_file", file_template_id=tpl["onboarding"], email_template_id=tpl["welcome"], approve=True)]},
        {"key": "overdue", "name": "Payment overdue: collections", "trigger": {"type": "payment.overdue"},
         "steps": [_s("action", action="run_agent", agent="collections", instruction="Draft a reminder for this overdue payment.",
                      fallback_template_id=tpl["payment_reminder"])]},
        {"key": "after_completion", "name": "Testimonial and referral after completion",
         "trigger": {"type": "project.stage_changed", "stage_key": "completed"},
         "steps": [_s("wait", wait={"kind": "time", "minutes": 3 * 1440}),
                   _s("action", action="send_email", template_id=tpl["testimonial"], approve=True),
                   _s("wait", wait={"kind": "time", "minutes": 7 * 1440}),
                   _s("action", action="send_email", template_id=tpl["referral"], approve=True)]},
    ]


def discovery_session_type():
    week = {str(d): [{"start": "10:00", "end": "13:00"}, {"start": "15:00", "end": "18:00"}] for d in range(0, 5)}
    return {"key": "discovery", "name": "Discovery call", "format": "video", "video": "meet", "duration": 30,
            "buffer_before": 0, "buffer_after": 15, "increment": 30, "availability": week, "min_notice_hours": 4,
            "max_days_ahead": 30, "cancel_cutoff_hours": 12, "max_attendees": 1, "host_ids": [], "color": "#C9A84C",
            "questions": [{"id": "q_topic", "label": "What would you like to discuss?", "kind": "long", "required": False}],
            "price_paise": 0, "notetaker": True, "hold_hours": 24, "reminders": [1440, 60], "active": True}
