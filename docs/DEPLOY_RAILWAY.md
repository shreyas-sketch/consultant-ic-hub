# Deploying on Railway

One repository, one Docker image, three to four Railway services:

| Service | What | Config |
|---|---|---|
| **web** | `uvicorn app.main:app`: screens, API, client pages, webhooks, MCP | `railway.json` (repo root, picked up automatically) |
| **worker** | `python -m app.workers`: scheduled jobs | `railway.worker.json` (set as the service's config file path) |
| **MongoDB** | database | Railway MongoDB template (staging) or MongoDB Atlas (production) |
| **Bucket** | uploads, signed contracts, invoice ZIPs | Railway Storage Bucket, Cloudflare R2 or AWS S3 |

> Field names in `railway.json` follow Railway's config-as-code format (`build.builder`, `build.dockerfilePath`, `deploy.preDeployCommand`, `deploy.healthcheckPath`, `deploy.restartPolicyType`, ...). If Railway's dashboard flags one as unknown, the same setting can be made by hand in the service's Settings tab.

## 1. Create the project

1. Railway → **New project → Deploy from GitHub repo** → pick this repository. This creates the **web** service. Railway finds `railway.json` and builds the `Dockerfile`.
2. **+ New → Database → MongoDB.** Railway names it `MongoDB` and exposes `MONGO_URL` on the private network.
3. **+ New → GitHub repo** → the same repository again. Rename it **worker**. In its **Settings → Config-as-code**, set the config file path to `/railway.worker.json`.
4. Optional but needed for production: **+ New → Bucket** (or create an R2/S3 bucket).

## 2. Variables

Use **Shared Variables** for everything both services need, then reference them. Minimum for production:

```bash
# shared by web and worker
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
TOKEN_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
MONGO_URL=${{MongoDB.MONGO_URL}}
DB_NAME=practice_os
APP_URL=https://<your web domain>
ADMIN_PHONES=+91XXXXXXXXXX
HOOK_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
VENDOR_STORAGE=live
S3_BUCKET=${{Bucket.BUCKET}}                 # check the exact names on the bucket's Variables tab
S3_ENDPOINT_URL=${{Bucket.ENDPOINT}}
S3_ACCESS_KEY_ID=${{Bucket.ACCESS_KEY_ID}}
S3_SECRET_ACCESS_KEY=${{Bucket.SECRET_ACCESS_KEY}}
S3_REGION=${{Bucket.REGION}}
```

Per service:

| Variable | web | worker |
|---|---|---|
| `RUN_JOBS` | `false` | `true` |
| `WEB_CONCURRENCY` | `2` (uvicorn processes per replica; raise with CPU) | not used |
| `ENSURE_INDEXES_ON_START` | `true` | `false` (web's pre-deploy already did it) |

Webhook URLs for providers carry the secret: `https://<app>/api/hooks/whatsapp-inbound?secret=<HOOK_SECRET>` (also `email-inbound`, `email-events`, `meetbot`).

Then switch on each real vendor (`VENDOR_AI=live` + `ANTHROPIC_API_KEY`, `VENDOR_WHATSAPP=live` + `AISENSY_API_KEY`, ...) as its keys arrive. The full list with comments is in `backend/.env.example`.

**The app refuses to start with unsafe values** (default or short `SECRET_KEY`, no `TOKEN_KEY`, `http://` `APP_URL`, `localhost` Mongo). The deploy log shows exactly which ones. `ALLOW_UNSAFE_CONFIG=true` bypasses this for a throwaway staging box only.

## 3. What happens on each deploy

1. Railway builds the image (screens in a Node stage, then the Python server). Only changes under `backend/app`, `frontend` or the `Dockerfile` trigger a build (`watchPatterns`).
2. **Pre-deploy (web):** `python -m app.db.migrate` builds missing indexes and applies pending migrations under a lock. If it fails, the deploy stops and the old version keeps serving.
3. Railway starts the new web container and waits for `GET /api/health/ready` (database ping) to return 200 before moving traffic. Old containers get 30 s to drain.
4. The worker restarts; SIGTERM lets running jobs finish their step, and leases stop a new worker from starting a job the old one is still running.

## 4. Domains

- **Web:** Settings → Networking → Generate domain (or add `app.yourdomain.in`). Set `APP_URL` to it.
- **Client pages on subdomains** (`<practice>.yourdomain.in`): add a wildcard custom domain `*.yourdomain.in` to the web service, set `CLIENT_DOMAIN=yourdomain.in`. Without it, client pages live at `APP_URL/c/<practice>/...`, which works out of the box.
- **Practices' own domains:** add each one as a custom domain on the web service and map it in Admin → Accounts. `GET /api/public/domain-check?domain=...` answers 200 only for mapped domains, for a TLS proxy using on-demand certificates.

## 5. Scaling

| When | Do |
|---|---|
| Web CPU high / slow responses | raise `WEB_CONCURRENCY`, then add web replicas (stateless, no other change) |
| Jobs falling behind (Admin → Jobs shows long `seconds`) | raise `JOB_WS_CONCURRENCY` / `JOB_AGENT_CONCURRENCY`, then add a worker replica (leases keep it safe) |
| Database CPU or connections | move to Atlas M10+ in Mumbai with a replica set; keep `replicas × WEB_CONCURRENCY × MONGO_MAX_POOL` under the cluster's connection limit |
| Report-heavy load | `MONGO_READ_PREFERENCE=secondaryPreferred` on a replica set |

Local file storage only works for a single web replica with **no** separate worker (they would not share a disk). Use a bucket as soon as the worker runs.

## 6. A demo deployment (no database, no keys)

For a clickable demo on sample data, deploy only the web service with:

```bash
QA_MODE=true
WEB_CONCURRENCY=1      # the in-memory database lives in one process
RUN_JOBS=true          # jobs run inside web
```

Remove the pre-deploy command for this service (it is harmless but useless here). Data resets on every restart. Personas are on the login screen. Never point real users at a QA deployment: login codes are shown on screen and `000000` always works.

## 7. Checks after the first production deploy

```bash
curl -s https://<app>/api/health
```

```bash
curl -s https://<app>/api/health/ready
```

Then log in with an `ADMIN_PHONES` number, open **Admin → Health** and **Admin → Jobs** (every job should show runs within a few minutes), and walk through the before-launch list in `HANDOVER.md`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Deploy fails at pre-deploy with `Refusing to start with unsafe settings` | a required variable is missing; the log lists which |
| Healthcheck times out | `MONGO_URL` wrong or the Mongo service is in another environment; `/api/health` (no DB) still answers |
| Uploads work, but downloads 404 after a redeploy | local storage on an ephemeral disk: set `VENDOR_STORAGE=live` and the bucket variables |
| Jobs never run | worker missing `RUN_JOBS=true`, or its config file path isn't set to `/railway.worker.json` |
| Logged out on every request | `APP_URL` is `https://` but you are browsing over plain `http` (cookies are `Secure`) |
