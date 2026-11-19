# Practice OS

An agent-run practice app for Indian consultants. Leads, proposals, contracts, invoices, booking, inbox, automations and AI agents in one place. Plus rates, time billing, budgets, retainers, estimates, forecast and client tasks. Clients pay by UPI or bank transfer; the consultant confirms. Agents draft, the consultant approves.

Invite-only. Login is a WhatsApp code (SMS as backup).

**Stack:** FastAPI + MongoDB (Motor) · React 19 + Vite + TanStack Query + Tailwind · one Docker image, deployed on Railway as a web service and a worker service.

## Try it in 2 minutes (QA mode)

QA mode runs the whole app on sample data. No database, no keys, no internet. Every outside service is faked.

```bash
cd frontend && npm ci && npm run build
```

```bash
cd backend && pip install -r requirements-dev.txt && python ../scripts/qa_server.py   # http://localhost:8765
```

- Log in with any persona from the QA bar at the top, or with `+919000000001` and code `000000`.
- Personas: owner, admin, manager, member, collaborator, new (fresh account, goes through setup), staff (our Admin screen).
- "Run jobs" in the QA bar runs automations, reminders and agents now instead of waiting.
- Client pages: `http://localhost:8765/c/mehta-growth/book/discovery-call`
- Frontend with live reload: `cd frontend && npm run dev` (port 5173, API proxied to 8765).

## Tests

```bash
cd backend && python -m pytest -q          # 128 tests, about 20 seconds
```

```bash
cd frontend && npm run check               # lint + build
```

```bash
CHROME_PATH=/path/to/chrome node scripts/crawl.mjs   # every screen at phone and desktop width (QA server running)
```

## Deploy

On Railway: see **[docs/DEPLOY_RAILWAY.md](docs/DEPLOY_RAILWAY.md)**. In short, one image, two services:

| Service | Start | Notes |
|---|---|---|
| web | `uvicorn app.main:app` (image default) | pre-deploy `python -m app.db.migrate`, healthcheck `/api/health/ready` |
| worker | `python -m app.workers` | no public domain |

plus MongoDB and a Railway Storage Bucket (or any S3-compatible bucket). Service settings are made on the services in Railway (the guide lists every value); Railway no longer reads `railway.json` for new services. Anywhere else with Docker:

```bash
docker build -t practice-os .
```

```bash
docker run --env-file backend/.env practice-os python -m app.db.migrate
```

```bash
docker run --env-file backend/.env -p 8000:8000 practice-os
```

```bash
docker run --env-file backend/.env -e RUN_JOBS=true practice-os python -m app.workers
```

All settings are in `backend/.env.example`. Production refuses to boot with unsafe values.

## Where things are

| Path | What |
|---|---|
| `backend/app/api` | HTTP layer: routers, request context, middleware, error shape |
| `backend/app/domain` | business actions by bounded context: sales, documents, billing, engagement, workspace, automation, analytics |
| `backend/app/auth` | OTP login, sessions, accounts |
| `backend/app/agents`, `backend/app/automations` | agent runtime, automation engine |
| `backend/app/integrations` | WhatsApp, SMS, email, calendar, video, notetaker, file storage, AI |
| `backend/app/db` | Mongo client, collections, indexes, tenant scoping, locks, migrations |
| `backend/app/workers` | scheduled jobs and the worker process |
| `frontend/src/app` | consultant app: `features/`, `ui/`, `widgets/`, `layout/`, route table |
| `frontend/src/client` | client pages bundle (forms, booking, files, invoices, portal) |
| `frontend/src/shared` | API client and hooks, formatting, styles |
| `scripts/` | QA server, crawl, load scenarios, Locust file, doc generator |
| `docs/` | architecture, Railway deploy, handover, backend design, screen map, API and agent specs, QA and load reports |

Start with **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
