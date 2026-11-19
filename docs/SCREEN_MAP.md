# Screen map

Dark consultant app (gold = action, teal = AI, red only for overdue). Light client pages in the practice's own colours. Every screen works at phone width (390 px) and desktop.

Screenshots of each: `qa/shots/`.

## Consultant app

| Screen | Path | What it's for |
|---|---|---|
| Login | `/login` | WhatsApp code login. Not-invited numbers see one plain line. |
| Setup | `/onboarding` | 9-question interview. The setup agent builds services, proposal, booking page and automations. |
| Home | `/` | Needs your OK, today's sessions, daily brief, money this month, leads found in inbox, activity. |
| Projects | `/projects` | Board or table. Stages, saved views, bulk edit, CSV import. |
| Project | `/projects/:id` | Activity, files, tasks (team and client), time, budget, payments, notes, details. Composer for email and WhatsApp. |
| Contacts | `/contacts` | People and companies, with all their projects. |
| Inbox | `/inbox` | One thread per project, email and WhatsApp together. |
| Calendar | `/calendar` | Sessions, session types, availability, booking links. |
| Files & templates | `/files` | Client files sent, templates, gallery. |
| Builder | `/files/:id`, `/templates/:id` | Pages of blocks, preview as client, send, versions. |
| Automations | `/automations` | List, flow editor, runs, "Why didn't this run?", test run. |
| Payments | `/payments` | Due, claims to confirm, paid, refunds, promo codes, recurring. |
| Reports | `/reports` | Pipeline, sales, forecast (confirmed vs pipeline), profit and effective rate, utilisation, money view, tax pack. |
| Agents | `/agents` | Each agent's mode, runs and what it did. |
| Approvals | `/approvals` | Drafts waiting for OK. Edit, approve or skip. |
| Tasks | `/tasks` | Team tasks, and "waiting on clients". |
| Time | `/time` | Week grid, entries, timer, unbilled time by project with "Invoice it". |
| Retainers | `/retainers`, `/retainers/:id` | Each client's plan, this period's meter, period history, invoices, change plan, pause, end. |
| Estimates | `/estimates`, `/estimates/:id` | Phases and lines on the left, live price / cost / margin on the right (a bar on phones). Make final, then a quote or a proposal. |
| Assistant sign-in | `/oauth/consent` | "Allow Claude to work in your practice?" Pick the practice and read / drafts / full. |
| Settings | `/settings/:section` | Practice, client pages, invoices and payment, services and rates, pipeline (with win chances), checklists, lists and fields, team, lead forms, connected accounts, messages, AI connector (signed-in assistants and tokens), audit log. |
| Ask or tell | top bar | Chat with the practice: "which leads came in this week?", "remind Ravi about the invoice". |

## Our Admin screen (staff only)

`/admin`: overview, invites, limits, accounts (overrides, custom domains, storage), usage, AI cost, funnel, health, jobs, AI settings (agent kill switch).

## Client pages

Work at `/c/<practice>/...`, on `<practice>.<client domain>`, or on the practice's own domain.

| Page | Path | What the client does |
|---|---|---|
| Lead form | `/form/:form` | Fills in the enquiry. Can book a call at the end. |
| Booking | `/book/:type` | Picks a slot in their own time zone. Pays first if the session is paid. |
| Client file | `/f/:token` | Steps through proposal → choose package → sign → pay → book. Resumes where they left off. A quick quote is one page with Accept. |
| Preview | `/preview/:fileId` | Consultant's "view as client". |
| Invoice | `/i/:token` | UPI link and QR, bank details, "I've paid", timesheet (if shared), invoice and receipt PDFs. |
| Download | `/d/:token` | Signed contract or shared file. |
| Portal | `/portal` | One login (code to phone) for all their projects, files, invoices, sessions, what they've been asked for, and their retainer statement. |
| Request | `/t/:token` | One thing the consultant asked for: upload a file, reply, mark done. |

## Roles

| | Owner | Admin | Manager | Member | Collaborator |
|---|---|---|---|---|---|
| See projects | all | all | all | their own | only ones shared with them |
| Change and send on projects | all | all | their own | their own | shared ones |
| See money amounts | yes | yes | yes, unless hidden in settings | yes, unless hidden in settings | no |
| Refunds | yes | yes | no | no | no |
| Add team, settings, lead forms | yes | yes | no | no | no |
| Automations | yes | yes | yes | no | no |
| Cost per hour, cost and margin | yes | yes | only if the Owner allows | no | no |
| Audit log | yes | yes | no | no | no |
