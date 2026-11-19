# QA report

## Full QA round — 19 Nov 2026

Scope: the whole hub after the restructure — backend, consultant app, client pages, admin, background jobs — on a **real MongoDB 7 replica set** (not only the in-memory fake), plus fuzzing and browser journeys. Every bug below is fixed and has a test that fails if it comes back.

### How it was tested

| Method | Coverage | Result |
|---|---|---|
| Backend test suite, in-memory | 128 tests | all pass (≈20 s) |
| Same suite on real MongoDB 7 (replica set) | 128 tests | all pass (≈2.5 min) |
| Concurrency tests (same request ×10 at once), real MongoDB | numbering, payments, claims, slots, OTP, slugs, quota, group seats, budget cycles | all pass after fixes |
| Authorization fuzzer | every action × member / collaborator / manager / another practice's owner × ids they must not see | 0 leaks after fixes |
| Crash fuzzer | all 225 actions × hostile inputs | 0 crashes after fixes |
| Route fuzzer | 105 HTTP routes, 2,124 junk requests (anonymous, client, staff) | 0 crashes after fixes |
| Browser journeys (`scripts/e2e`) | 20 real user journeys, consultant on desktop, clients at 390 px | 20/20 pass |
| Screen crawl (`scripts/crawl.mjs`) | every screen at 390 px and 1280 px, 125 screenshots | clean |
| Upgrade check | new index set applied over the original production indexes | 153 → 242 indexes, 0 conflicts, idempotent |
| Static analysis | ruff (bug classes), ESLint | clean |

### Bugs found and fixed

**Security**
1. *Unauthenticated webhooks.* `/api/hooks/whatsapp-inbound` matched senders by phone across every practice with no authentication: anyone could post a fake client reply (e.g. "done", which closes that client's tasks) or feed text to the agents. All hooks now need `HOOK_SECRET`; production refuses to boot without it when messaging is live.
2. *Stored XSS via AI drafts.* Draft HTML rendered raw in the consultant's Approvals screen; a prompt-injected draft ran script in the consultant's session (reproduced in a browser). All seven raw-HTML renders now go through DOMPurify.
3. *Authorization holes* (members/collaborators reaching projects they aren't on): `files.list`, `payments.list_due`, `approvals.list`, `tasks.list` let a `project_id` filter replace the visibility filter; `agents.runs`/`agents.run_get` had no check; `tasks.complete` and `approvals.skip` let anyone act on any project; `approvals.approve` changed the record before refusing.

**Money and data integrity** (found only on real MongoDB)
4. Parallel "I've paid" taps created one claim per tap.
5. First invoice / credit-note numbers of a financial year could fail (500) when sent at the same moment.
6. Same-name practices created together collided on the web address (originally: silent duplicates).
7. Budget cycle creation crashed one of two parallel checks; two clients taking the first seats of a group session could be told "full".

**Money shown to clients**
8. Client pages and the app rounded paise away: ₹12,345.50 showed as ₹12,346.
9. "Due on receipt" payments showed Overdue the moment they were sent, and the money job fired `payment.overdue` immediately (waking overdue automations and the collections agent). Overdue now means the due day has passed (IST).

**Robustness**
10. Any malformed date crashed every date-taking action (500); `stages.save` and `/oauth/register` crashed on junk input; `lead_forms.save` crashed on an unknown id.
11. A failed scheduled file send vanished silently; failed recurring-invoice sends too. The consultant is now notified. Other job failures are logged with stack traces.
12. `db or get_db()` raised on a real Motor database; the migration lock ignored the database it was migrating.

**Accessibility and copy**
13. Sheets had no dialog role; inputs labelled only by placeholder had no accessible name (and the first fix briefly overrode visible labels — corrected); package choices and UPI/Bank, Type/Draw toggles didn't announce their selected state; the one-time-code box had no label.
14. Lead activity read "New lead from manual".

### Journeys covered in the browser

Login by WhatsApp code (and uninvited number, deep link back after login) · new lead · public lead form · request payment → client claims on a phone → consultant confirms → receipt & invoice PDFs · credit note and paid-invoice lock · full client file on a phone (choose package → sign with code → pay → done) · booking from Mumbai and Dubai time zones (saved instant matches the slot picked) · client portal (login, invoices, message reaches the inbox) · log time → invoice it · approve a draft · member / collaborator visibility · onboarding a new account · settings persist · staff admin limit change, log and revert (and consultants refused) · "Ask or tell" chat · hostile HTML in drafts and portal messages never runs.

### Not covered here

- Live vendor adapters (WhatsApp, SMS, email, Google/Microsoft, Zoom, notetaker, S3): still only exercised in fake mode — see `HANDOVER.md`.
- The Docker image build (the sandbox's build container had no network). CI builds it on every push.
- Load testing on a production-size database (`LOAD_TEST.md`).

### Suggestions (not bugs)

- When "New lead" matches an existing contact by phone or email, the new project silently takes the existing contact's name. A one-line "Matched existing contact …" note would avoid surprise.

---

## Earlier report


Updated 13 Nov 2026 (add-ons). All in QA mode (in-memory database, fake vendors, simulated clock).

## Automated tests: 94 passed

`cd backend && python -m pytest -q` (about 6 seconds)

**Login, roles, limits (15)**
- Invited number logs in and gets a practice. Not-invited number sees one plain line, by WhatsApp and by API.
- No practice can read another's data. Actions can't touch tenant data directly.
- Limit change in Admin works with no deploy; "new accounts only" keeps old accounts; one-click revert.
- Admin can add team. Refunds are Owner/Admin only.
- Removed access goes read-only; client links keep working.
- Storage limit blocks uploads when full. Custom domain and practice subdomain serve client pages; the app's own domain doesn't.
- Error messages are plain.

**Core loop (18)**
- Lead form → project → lead agent drafts a reply → approval.
- Repeat submission attaches to the same contact. Honeypot and required answers. Prompt injection in a form answer stays text.
- Full flow on a phone: book → open file → pick package → sign with code → "I've paid" → two confirms race → one ledger row.
- Rejected claim goes back to due and tells the client.
- Contract edited after a claim needs the latest version. Edited and re-shared contract cancels the old signature and keeps both versions.
- No-gap invoice numbers. Paid invoice locked; credit note. Promo can't reach zero. Late fee: none on day 29, once on day 31. GST off by default, on with GSTIN. AI invoice edit and undo.
- Reopen a completed file; client changes answers and submits again.

**Booking, inbox, automations, agents (26)**
- Two clients take the last slot in the same second: one wins.
- Dubai client books a Mumbai consultant across a date boundary.
- Sign-to-reserve hold confirmed on signature; unpaid hold released after 10 minutes.
- Client reply lands on the project. WhatsApp free text only inside 24 hours.
- Agent messages held during quiet hours until 8 am. Approved and transactional messages are not held.
- Custom sending domain without SPF/DKIM is blocked with a plain message.
- All 7 starter automations on a simulated clock.
- Editing an automation doesn't change runs in flight. Worker killed mid-step never double-sends.
- Every "Why didn't this run?" reason. Test run sends nothing.
- Automation builder drafts a switched-off automation.
- AI budget is per practice and stops agents cleanly.
- Draft mode: nothing leaves without an approval. Auto mode sends, money still waits.
- Meeting agent: transcript → notes and tasks. Proposal agent drafts.
- Screenshot to lead. Setup agent builds a usable account from the interview.
- AI connector read scope lists read tools only; sends go to approvals.
- Client with three projects sees all three in one portal.
- Reports, money view, recurring invoice once a month, home numbers.


**Add-ons (35)** — every test the add-on playbook lists, plus a few more
- Rates: a rate change dated next month leaves this month's entries alone; project card beats client card beats default; "apply to unbilled" re-prices only when asked; a service in use is archived, not deleted.
- A Member with money hidden can't read any rate through the API, chat or MCP; sorting by a money field is refused.
- Cost and margin never reach a Member: time list, estimates, chat; sorting by margin is refused for them and allowed for the Owner.
- Time: on a draft invoice it's still unbilled; sending bills and locks it; editing billed time is refused plainly; the client sees the timesheet and pays by UPI; a cancelled invoice gives its time back, and it can be invoiced again once.
- Rounding 7 minutes up to 15 moves the line and the total together. Grouping by task, date, role or none gives the same total, to the paisa, at an awkward rate.
- Billable expense with 10% markup; an expense on an invoice can't be edited. Period lock. Weekly grid.
- Bulk: ZIP of invoice PDFs built by the job and downloaded; reminders for many; CSV export.
- Budgets: 79% no alert, 80% one alert, 85% next day no second alert; monthly reset on the 1st with last month kept; forecast matches the formula on a fixed sample; the 80% alert drafts a scope check for approval.
- Retainers (the six in the playbook): rollover up to 5 valid one period then lapses; 6 hours over billed as its own line on the next invoice; borrow rule leaves 14; a period closes once with two workers at the same time; late time lands in adjustments; pause completes the period, opens nothing, raises no invoice. Also: "ask first" overage skipped means absorbed; client statement shows totals without entries; plan change starts next period; retainer time is billed by the retainer, never counted as unbilled.
- Estimates: the client page and the quote PDF never contain cost or margin at any detail level; two taps on Accept make one budget, one set of tasks, one invoice; a final estimate ignores later rate changes; an expired quote is refused; call notes → agent estimate (with stated assumptions) → quote → accepted → budget and tasks.
- Forecast: ₹10 L at 50% over two months shows ₹2.5 L a month in pipeline; moving to a booked stage takes it out; confirmed changes only when a payment schedule exists. Fixed-fee effective rate uses the fee received. Utilisation counts billable hours.
- Client tasks: completed by a WhatsApp "Done"; by the link with an upload that lands in the project's files; overdue flags once and the follow-up agent drafts a reminder; call notes turn "could you share…" into a client task; clients only ever see client tasks.
- Checklists on stage entry are added once; a repeating task makes its next occurrence once.
- MCP sign-in: discovery documents and the 401 challenge; a Member signs in and gets no money fields; a code works once and reuse revokes; refresh tokens rotate and reuse signs the chain out; access tokens expire in 15 minutes; DCR, PKCE required, wrong redirect refused, `iss` on errors, wrong `resource` refused; read-only consent gets a 403 step-up challenge for a drafts tool; signing out from Settings revokes.

## Screen crawl: clean

`node scripts/crawl.mjs` opens every consultant screen, Admin page and client page as each role, at 390 px and 1280 px. It flags server errors, page errors, console errors, sideways scroll, "NaN", "undefined" and raw ISO dates. Last run (with the add-on screens): no problems. 125 screenshots in `qa/shots/`.

## Bugs found and fixed during QA

| Bug | Fix |
|---|---|
| Invoice number index broke on drafts with no number | Single sparse `number_key` set when issued |
| Approval expiry touched data outside the tenant helper | Moved to the housekeeping job |
| UPI IDs with a 1-letter handle rejected | Pattern widened |
| Approved agent email held overnight by quiet hours | Approvals send straight away |
| Invoice stayed draft after the client chose a package | Issued on selection |
| Project files list crashed on cleaned ids | Fixed key |
| Booking showed a placeholder Meet link with no calendar connected | Removed; consultant is told to connect Google Calendar |
| Onboarding automation waited on an email approval before moving stage | Steps reordered |
| New automation run missing its workspace | Returns the saved run |
| Home screen remounted a card on every render | Component moved out |
| Chat screen crashed ("T is not a function") | Effect fixed |
| QA bar cramped on phones | No wrap |
| Setup proposal intro had broken grammar | Rewritten |
| "Whatsapp" spelling in places | One label map |
| Client invoice didn't say "Overdue" | Added |
| Storage limit existed but wasn't enforced | Checked on every upload |
| Practice subdomain check would have caught the app's own domain | App host and reserved names excluded |
| No way to reopen a completed form | `files.reopen` plus buttons |
| Crawl flagged a missing button on the second width | Not a bug: the file resumes where the client left off. Crawl fixed. |

| Add-ons: a member could have read rates through chat | One money/cost filter on every action result, for every door |
| Add-ons: retainer time showed as "unbilled" on Home | Retainer time is billed when its period closes and left out of unbilled totals |
| Add-ons: a quote page showed two Accept buttons, and the bottom one completed the file without accepting | Quote pages have only the quote's Accept; the server treats "complete" on a quote as accept |
| Add-ons: invoices made from time were "Overdue" straight away | Due in 7 days (setting) |
| Add-ons: client invoice said "No task × 6" | "Professional time", with hours and rate shown |
| Add-ons: tabs and the QA bar squashed together on phones | Tabs no longer shrink; they scroll |
| Add-ons: estimate builder cramped on phones; price bar under the chat button | Line layout and padding fixed |

## Found, not fixed

- Live vendor adapters have never run against the real services.
- Deleting a file doesn't give storage space back.
- Replies to the consultant's own Gmail thread aren't synced (reply-to address works).
- Foreign-currency invoices (rate cards can be in another currency; invoices are in rupees).
- MCP sign-in tested with simulated assistants only.
