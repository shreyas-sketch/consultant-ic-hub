# Architecture

How the system is put together, why, and how it grows. For the business rules (actions, money, automations, agents) see `BACKEND_DESIGN.md`; for deployment see `DEPLOY_RAILWAY.md`.

## The shape

```
                    ┌──────────────────────── Railway project ────────────────────────┐
 consultants ──┐    │                                                                  │
 clients ──────┼──► │  web  (N replicas)            worker (1+ replicas)               │
 AI assistants ┘    │  uvicorn app.main:app         python -m app.workers              │
  (MCP / OAuth)     │  RUN_JOBS=false               RUN_JOBS=true                      │
                    │   • screens (static, cached)   • APScheduler, 17 jobs            │
                    │   • /api/a/<action>            • each job holds a DB lease       │
                    │   • client pages, webhooks     • streams cursors, bounded fan-out│
                    │          │                              │                        │
                    │          └──────────┬───────────────────┘                        │
                    │                     ▼                                            │
                    │            MongoDB (replica set)      S3-compatible bucket       │
                    │            one DB, tenant = workspace  uploads, signed PDFs, ZIPs│
                    └──────────────────────────────────────────────────────────────────┘
```

- **One image, two processes.** Web and worker are the same Docker image with different start commands. They share no memory and no disk, only MongoDB and the bucket. That is what lets each scale on its own.
- **Web is stateless.** Sessions are signed cookies plus a row in `sessions_auth`; rate limits, caches and locks live in MongoDB. Any replica can serve any request, so you can add replicas freely.
- **Workers are safe to duplicate.** Every job takes a lease in `job_locks` (renewed while it runs). A second worker adds headroom and failover, never double sends: those are blocked by unique keys anyway.

## Backend layers

```
backend/app/
  main.py            app factory: middleware, error handlers, routers, lifespan
  api/               HTTP adapters only. No business rules.
    routes/          system, auth, actions, files, connections, public, admin, mcp, oauth, qa, frontend
    deps.py          get_ctx (who, which practice, which role), get_admin, client_ip
    middleware.py    request id, access log, security headers (pure ASGI)
    errors.py        one error shape: {"error": {code, message, extra?, request_id}}
  auth/              OTP, sessions, accounts: the login service
  domain/            THE business logic: every action, grouped by bounded context
    registry.py      @action: name, level, roles, input model. One registry, four doors
    perm.py          project visibility, money/cost redaction on every result
    sales/           crm (contacts, projects, leads), forms
    documents/       client files, merge fields, default texts, uploads
    billing/         money (invoices, payments, ledger), rates, time billing, budgets, retainers, estimates
    engagement/      inbox, scheduling, client tasks, portal
    workspace/       workspace & team, approvals, connected accounts
    automation/      automations, agent actions
    analytics/       reports, insight (forecast, profit, utilisation)
  agents/            agent runtime (tool loop over the registry) and definitions
  automations/       engine: event dispatch, runs, waits, branches
  integrations/      vendors (WhatsApp, SMS, email, calendar, video, notetaker), storage, llm
  services/          pdf (rendered off the event loop), uploads, domains
  core/              settings, context (Ctx), events, limits, logging, security, util
  db/                client (pool), collections, indexes, tenant (ctx.data), locks, migrations
  workers/           jobs registry + scheduler, worker entry point, worker health port
  qa/                demo seed (QA mode only)
```

**Dependency rule:** a layer only imports the layers below it.
`api → auth, domain → agents, automations → integrations, services → db, core`.
`tests/test_platform.py` fails the build if domain, auth, core, db, integrations, services, agents or automations import `app.api`, or if core imports domain.

### One registry, four doors

Every change is an action in `app/domain`. The same function is called by:

| Door | Entry |
|---|---|
| Screens | `POST /api/a/<name>` (`api/routes/actions.py`) |
| Automations | `automations/engine.py` |
| Agents | `agents/runtime.py` (actions as tools) |
| AI connector | `api/routes/mcp.py` (JSON-RPC, OAuth 2.1) |

So roles, read-only access, limits and the money/cost filter are enforced in exactly one place, whoever calls.

### Request lifecycle

1. `RequestContextMiddleware` assigns a request id (or keeps `X-Request-ID`), adds security headers, and logs one JSON line with method, path, status, duration, action and workspace.
2. `get_ctx` reads the session cookie, checks membership of the requested workspace and builds `Ctx` (workspace, user, role, read-only, money visibility).
3. `registry.call` checks role and read-only, validates the input model, runs the action, then `perm.redact` strips cost/margin and hidden money from the result.
4. Errors leave as `{"error": {...}}` with the request id; unexpected ones are logged with the stack trace and the same id.

## Data model and multi-tenancy

- **Tenant = workspace (a practice).** 62 tenant collections carry `workspace_id`; 20 global collections don't (users, sessions, OAuth, limits, job bookkeeping). The list lives in `app/db/collections.py`.
- **Isolation by construction.** Domain code never touches the raw database: `ctx.data.<collection>` adds `workspace_id` to every filter and insert and hides soft-deleted rows. A test fails if a domain module calls `get_db()` on a tenant collection.
- **No transactions needed.** Money and sends are made idempotent with unique keys (`ledger.key`, `approvals.idempotency_key`, `outbound_queue.idempotency_key`, `automation_runs.run_key`, `invoices.number_key`, ...). Races resolve to "one insert wins, the other gets already-done". The same code runs on the in-memory test database and on a real cluster.
- **Money** is integer paise end to end. Invoice numbers have no gaps per Indian financial year.

## Scaling the database

What is in place now:

| Concern | How |
|---|---|
| Hot queries | Declarative index specs (`app/db/indexes.py`): every tenant index leads with `workspace_id`, then equality, then sort/range fields. 164 indexes, built idempotently on each deploy |
| Public pages and webhooks | Token lookups (`client_files`, `invoices`, `uploads`, `tasks`) and webhook lookups (`messages.provider_id`, `sessions.notetaker.bot_id`) are indexed; they were full collection scans before |
| Job scans across tenants | Each scan has its own status index (`invoices.status`, `sessions.status+start`, `outbound_queue.status+send_at`, ...) and streams a cursor in batches of 500, so nothing past a cap is ever skipped |
| Growth of short-lived data | TTL indexes expire OTP codes, sessions, OAuth state/codes/tokens, client sessions, job runs (30 d), vendor log (30 d) and processed events (90 d) |
| Connections | One pooled client per process (`MONGO_MAX_POOL`, timeouts, retryable reads/writes) |
| Read scaling | `reporting_db()` sends tolerant reads to secondaries when `MONGO_READ_PREFERENCE=secondaryPreferred` |
| Schema changes | Versioned migrations (`app/db/migrations/mNNNN_*.py`), recorded in `schema_migrations`, run once under a lock by the pre-deploy command |
| Fan-out work | Per-workspace jobs run `JOB_WS_CONCURRENCY` workspaces at a time; agents `JOB_AGENT_CONCURRENCY`; one failing workspace never stops the rest |

**Growth path**, in the order you will need it:

1. **Vertical + replica set** (now → tens of thousands of practices). Railway's MongoDB service for staging; MongoDB Atlas (Mumbai, M10+, replica set, backups) for production. Point `MONGO_URL` at it; nothing else changes.
2. **Read replicas.** Set `MONGO_READ_PREFERENCE=secondaryPreferred` for report-heavy load.
3. **Archive cold data.** Move `activity`, `messages`, `file_events` and `audit_log` older than N months to an archive collection or Atlas Online Archive; the TTL pattern is already used for transient data.
4. **Shard by tenant.** Every tenant document already carries `workspace_id`, and every tenant query includes it (enforced by `ctx.data`), so `{workspace_id: "hashed"}` (or `{workspace_id: 1, _id: 1}`) is the natural shard key and each query targets one shard. Before sharding, the global unique keys listed above must become `{workspace_id, key}` (the keys already embed workspace-scoped ids, so this changes no behaviour) and public token lookups should go through a small global `link_tokens` collection. Both are a migration plus an index change.

## Background work

| Kind | Examples | Pattern |
|---|---|---|
| Queues | outbound messages, scheduled file sends, held slots, invoice ZIPs | drain in batches every 10–60 s; each item claimed by a conditional update |
| Sweeps | money (overdue, late fees, reminders), session reminders, recurring invoices, project-date automations | stream all matching documents; per-item tags (`reminded`, `last_month`) make reruns harmless |
| Per-workspace | budgets, retainers, repeating tasks, client tasks | `for_each_workspace` with bounded concurrency |
| Agents | daily brief, follow-up, collections | per workspace, lower concurrency (AI calls), per-workspace AI budget |
| Events | stage rules, automation triggers, waits | outbox in `events`, dispatched every 10 s with a lease per event |

## Files

`app/integrations/storage.py` is one async interface over local disk (QA, single box) or any S3-compatible bucket (Railway buckets, R2, AWS). Keys are `<workspace_id>/<uuid>-<safe name>`; local keys are confined to `UPLOAD_DIR`. Uploads are size-checked before decoding and type-checked by their bytes. Quota is reserved atomically per workspace.

## Frontend

React 19 + Vite + TanStack Query, two bundles served by the backend from the same origin (no CORS, cookies just work):

- `src/app`: the consultant app, one folder per product area in `features/`, a shared design system in `ui/`, a route table in `router.jsx`, each screen code-split and wrapped in an error boundary.
- `src/client`: the client pages (forms, booking, files, invoices, portal). Small: it shares only the React vendor chunk.
- `src/shared`: the API client and hooks, formatting, file utilities and styles used by both.

Static assets are content-hashed and served with `Cache-Control: immutable` for a year; HTML is `no-cache`, so a deploy is picked up on the next navigation. A tab left open across a deploy reloads once when a lazy chunk 404s.

## Security posture

- Invite-only phone OTP; codes hashed, 5 tries, 10-minute expiry, atomic single use, per-IP rate limit on every OTP door (consultant and client).
- Session cookies `HttpOnly`, `Secure`, `SameSite=Lax`; refresh tokens stored hashed; removed users lose sessions.
- Tenant isolation by construction (`ctx.data`), role checks in the registry, money and cost redaction on every result.
- Client text is data, never instructions, for agents (`<client_data>` wrapping).
- PDFs: client fields HTML-escaped, renderer limited to `data:` URLs (no file or network fetches).
- Security headers and HSTS on every response; SPA paths confined to the build folder.
- Production refuses to boot with unsafe settings (`settings.validate()`).

## Testing

- `backend/tests`: 114 tests on the in-memory database, including the platform guarantees above (layering, indexes, TTLs, migrations, storage confinement, upload sniffing, rate limits, headers, PDF escaping, config refusal, lease behaviour).
- `scripts/crawl.mjs`: opens every screen at 390 px and 1280 px and fails on 5xx, page errors, sideways scroll, `NaN`/`undefined` or raw ISO dates.
- CI (`.github/workflows/ci.yml`): backend tests, frontend lint + build, Docker image build.
