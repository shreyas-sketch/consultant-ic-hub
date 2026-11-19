# Handover

Plain status of what's built, what's tested, and what's left before real consultants use it.

Updated 13 Nov 2026: the add-ons from the Bonsai study are now built (section "Add-ons" below).

Updated 19 Nov 2026: restructured for production on Railway (section "Restructure for production" below). No product behaviour changed; all 225 actions and every screen are as before.

## What's built

All steps of the main playbook, plus all seven add-on phases.

- **Login and accounts.** Invite-only WhatsApp code login with SMS backup. Owner, Admin, Manager, Member, Collaborator. Admin can add team. Removed access goes read-only; client links keep working.
- **Projects and contacts.** Board and table, custom stages, saved views, bulk edit, CSV import, tags, notes, tasks.
- **Lead capture.** Lead forms, booking page, screenshot to lead, leads found in the inbox, referral source.
- **Client files.** Proposal, contract, invoice, questionnaire, booking, quick quote and retainer plan as pages of blocks. Versions with "what changed". OTP signing with a signed PDF and audit page. Reopen a completed file.
- **Money.** Integer paise. Payment schedules, UPI link and QR, "I've paid" claims the consultant confirms, TDS, optional GST, late fee once at 30 days (max 10%), credit notes, no-gap numbering per financial year, recurring invoices, promo codes. Refunds by Owner/Admin only. Invoice PDFs.
- **Scheduling.** Session types, availability, buffers, holds, time zones, Google/Outlook calendar, Meet/Zoom links, meeting notetaker.
- **Inbox.** Email and WhatsApp on one thread per project. Quiet hours for agent sends. WhatsApp 24-hour window.
- **Automations.** Triggers, waits, yes/no branches, approvals on send steps, "Why didn't this run?", test run, 7 starters.
- **Agents.** Lead, follow-up, meeting, proposal, collections, daily brief, automation builder, chat, setup. Draft / ask / auto modes. Money always needs a person.
- **AI cost cap per workspace**, changeable from Admin with no deploy.
- **Client portal.** One login per client, all their projects, what they've been asked for, and their retainer statement.
- **AI connector (MCP).** Proper sign-in (OAuth) or Settings tokens. Read, drafts or full. Sends and money go to approvals.
- **Our Admin screen.** Invites, limits (all accounts or new accounts only, one-click revert), per-account overrides, custom domains, usage, AI cost, agent kill switch, funnel, jobs, health.
- **Reports.** Pipeline, sales, forecast, profit and effective rate, utilisation, money view, tax pack, CSV export.

Counts: 225 actions, 9 agents, 31 limit keys, 21 consultant screens (plus 13 settings sections and 10 Admin pages), 8 client page types.

## Add-ons (Bonsai study)

| Phase | What the consultant gets |
|---|---|
| A1 Rates | Service library; rate cards (default, per client, per project; by service, role or person); rate changes from a date; cost per hour per person; "1 day = N hours". Every time entry keeps the rate it was logged at. |
| A2 Time billing | Weekly grid, list, timer. Billable / unbilled / billed. "Invoice unbilled time" with rounding, grouping and a timesheet. Billable expenses with markup. Period lock. Bulk ZIP download, reminders and CSV of invoices. |
| A3 Budgets | Fee or hours, weekly / monthly / quarterly reset, alerts at 80% and 100% once per cycle, forecast from task estimates, scope-check draft at 80%. |
| A4 Retainers | Hours bank, fixed scope, or pay-as-used with a cap. Rollover and overage rules. Period close once, invoice raised, next period opened with its checklist. Adjustments for late time. Pause, resume, end, renewal note. Client statement in the portal. Checklists and repeating tasks. |
| A5 Estimates | Internal estimate with phases, price, cost, margin (or effective hourly rate). One-page quote or full proposal. Client accepts → budget, tasks and invoice, once. Agent drafts an estimate from call notes and states its assumptions. |
| A6 Insight | Forecast with confirmed and pipeline kept apart. Profit and effective hourly rate by project, client and service. Utilisation by person. |
| A7 Client tasks and MCP sign-in | Ask the client for something by WhatsApp or email; they mark it done, upload or reply (or reply "done" on WhatsApp). MCP sign-in to the current spec. |

**Decisions taken** (section 8 of the add-on playbook — the suggested defaults, all changeable):

- New retainers: unused hours carry up to 25% of the plan for one period; extra time billed at the standard rate.
- Alerts for budgets and retainers at 80% and 100%.
- Clients don't see individual time entries on a retainer statement unless the consultant switches it on.
- Cost and margin: Owner and Admin only. A Manager only if the Owner allows it. Members never. One filter does this for screens, API, chat, agents and MCP.
- Every new limit key is open at launch and shows in the Admin limits editor.

**MCP sign-in, checked against the current spec (revision 2026-07-28, read 13 Nov 2026):**

- The spec now prefers Client ID Metadata Documents and marks Dynamic Client Registration as deprecated. Both are built: CIMD first, DCR kept for older clients.
- PKCE (S256) required. `resource` binds tokens to our MCP endpoint. `iss` returned on every authorisation response. 15-minute access tokens, rotating refresh tokens (reuse signs the chain out).
- The stateless protocol (`server/discover`, version in `_meta`) is supported alongside the older `initialize` handshake.

## Restructure for production (19 Nov 2026)

- **Layout.** Backend is one package, `backend/app`, in layers (api → auth/domain → agents/automations → integrations/services → db/core); a test enforces the direction. Frontend is feature-based with a shared layer and an `@/` alias. See `docs/ARCHITECTURE.md`.
- **Deploy.** Railway: web (`railway.json`, pre-deploy migrations, readiness check) and worker (`railway.worker.json`). See `docs/DEPLOY_RAILWAY.md`.
- **Database.** 164 declared indexes (tenant-first compound, token and webhook lookups, TTL for short-lived data), versioned migrations, pooled client, streamed job scans, bounded per-workspace concurrency, renewed job leases.
- **Fixed on the way:**
  - Jobs only processed the first N matches (`to_list(5000)` and similar); the rest were silently skipped.
  - Each job's first run was skipped and then locked for 10 minutes (the lease read the pre-upsert document).
  - Storage: callers read local paths directly, so S3 mode would have failed; boto3 blocked the event loop.
  - PDFs: client-typed names and the browser's User-Agent went into the contract PDF unescaped, and the renderer would fetch `file://` and network URLs. Now escaped, and only `data:` URLs load. Rendering no longer blocks other requests.
  - The client OTP endpoint had no per-IP limit (SMS-pumping risk).
  - OAuth connect state never expired and was reusable.
  - Public token lookups and webhook lookups had no index (full scans).
  - Workspace slugs had no unique index (a race could duplicate one).
  - Upload type was trusted from the browser; bytes are now checked.
  - The SPA catch-all could be asked for paths outside the build folder.
  - Every client page downloaded the rich-text editor (~94 kB gzip).
- **Not verified here:** the Docker image could not be built in this environment (no outbound access from the build container). CI builds it on every push; build it once before the first Railway deploy.

## How to run

See `README.md`. QA mode needs nothing but Python and Node.

## Before launch

Keys and accounts (fill `backend/.env`, switch each `VENDOR_*` to `live`). Waiting times are rough guesses; check each vendor's current process.

- [ ] MongoDB Atlas cluster (M10 or above, Mumbai region). Backups on.
- [ ] Anthropic API key. Check model prices and the ₹/US$ rate in `.env`.
- [ ] AiSensy (WhatsApp). Get these templates approved: login code, file sent, payment reminder, booking confirmed, session reminder, **client task** (new). About 1–3 days each.
- [ ] MSG91 for SMS login codes. DLT registration of the sender ID and template (India rule). About 1–2 weeks.
- [ ] Transactional email provider, plus SPF/DKIM on our sending domain and the inbound reply domain.
- [ ] Google Cloud app for Gmail + Calendar. Gmail scopes need Google's verification and a CASA security review. Plan 4–8 weeks. Until then, up to 100 test users.
- [ ] Microsoft app (Outlook mail + calendar). Publisher verification.
- [ ] Zoom app review. About 1–2 weeks.
- [ ] Meeting notetaker provider (any "bot joins the call" API). Set `MEETBOT_API_URL` / `KEY`.
- [ ] S3-style storage bucket in Mumbai region.
- [ ] Sentry DSN.
- [ ] Wildcard DNS for `*.CLIENT_DOMAIN`, and a TLS proxy (Caddy works) using `/api/public/domain-check` for on-demand certificates on custom domains.

Checks to do on staging with live keys:

- [ ] Load test on a real MongoDB (see `docs/LOAD_TEST.md`). Not done yet. This is the biggest open item.
- [ ] One real end-to-end: invite → WhatsApp code → setup → send a proposal to your own phone → sign → pay ₹1 by UPI → confirm.
- [ ] Each live adapter once: WhatsApp send and reply, SMS code, email send and reply, Gmail and Outlook connect, calendar event, Meet and Zoom link, notetaker join, file upload.
- [ ] Connect Claude (and ChatGPT) to `/mcp` with the real sign-in, on the public URL. Tested here only with simulated clients.

Legal and CA (outside the code):

- [ ] Terms, privacy policy, and a data processing note (DPDP Act 2023).
- [ ] CA to review the invoice format, TDS handling, GST invoice fields and late-fee wording.
- [ ] CA: GST and TDS on retainer invoices raised in advance (before the work is done).
- [ ] Lawyer to review the default agreement and NDA text in `backend/app/domain/defaults.py`, and add a retainer clause (rollover, extra time, notice).
- [ ] Confirm OTP signing with an audit page is enough for your clients' contracts (it suits most service agreements; some documents need Aadhaar eSign).

## Known gaps

- **Live adapters are untested.** They are written to each vendor's documented API but have only run in fake mode here. Same for fetching a real assistant's Client ID Metadata Document.
- **Foreign-currency invoices.** A rate card can be in another currency, but invoices are raised in rupees. Time priced in another currency is refused at "Invoice unbilled time" with a plain message.
- **Gmail thread sync.** Client replies come back through our reply-to address. Replies sent to the consultant's own Gmail thread are not synced yet.
- **Real-database load test.** Only run on the in-memory database (see `docs/LOAD_TEST.md`).
- **Storage.** The limit is enforced (atomically) on upload. `vendors.storage_delete()` gives space back, but no screen deletes uploads yet.
- **Retainer plan changes** (fee, hours, rules) take effect from the next period, by design. There's no way to change the current period's plan.
- **Seed.** The QA "staff" persona also gets an empty practice of its own. QA only.
