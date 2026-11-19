# Practice OS

An agent-run practice app for Indian consultants. Leads, proposals, contracts, invoices, booking, inbox, automations and AI agents in one place. Plus rates, time billing, budgets, retainers, estimates, forecast and client tasks. Clients pay by UPI or bank transfer; the consultant confirms. Agents draft, the consultant approves.

Invite-only. Login is a WhatsApp code (SMS as backup).

## Try it in 2 minutes (QA mode)

QA mode runs the whole app on sample data. No database, no keys, no internet. Every outside service is faked.

```bash
# 1. Screens
cd frontend && npm install && npx vite build

# 2. Server
cd ../backend && pip install -r requirements.txt
python ../scripts/qa_server.py          # http://localhost:8765
```

- Log in with any persona from the QA bar at the top, or with `+919000000001` and code `000000`.
- Personas: owner, admin, manager, member, collaborator, new (fresh account, goes through setup), staff (our Admin screen).
- "Run jobs" in the QA bar runs automations, reminders and agents now instead of waiting.
- Client pages: `http://localhost:8765/c/mehta-growth/book/discovery-call`

## Tests

```bash
cd backend && python -m pytest -q        # 94 tests, about 6 seconds
cd frontend && node ../scripts/crawl.mjs # opens every screen at phone and desktop width
```

## Run for real

One image, two start commands. See `docs/HANDOVER.md` for the before-launch list.

```bash
docker build -t practice-os .
docker run --env-file backend/.env -p 8000:8000 practice-os                       # web
docker run --env-file backend/.env -e RUN_JOBS=true practice-os python worker.py  # worker
```

All settings are in `backend/.env.example`.

## Where things are

| Folder | What |
|---|---|
| `backend/` | FastAPI server, actions, agents, automations, jobs |
| `frontend/` | React screens: the consultant app and the small client bundle |
| `scripts/` | QA server, crawl, load scenarios, Locust file, doc generator |
| `docs/` | Handover, design, screen map, QA and load reports, API and agent specs |
