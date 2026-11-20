# Deploying on Railway

One repository, one Docker image, four Railway services in one project and environment (`production`):

| Service | What it runs | Source |
|---|---|---|
| **web** | `uvicorn app.main:app` (the image's default command): screens, API, client pages, webhooks, MCP | this GitHub repo |
| **worker** | `python -m app.workers`: scheduled jobs | this GitHub repo again |
| **MongoDB** | the database | Docker image `mongo:7` with a volume |
| **Bucket** | uploads, signed contracts, invoice PDFs and ZIPs | a Railway Storage Bucket |

> **Service settings live on the services, not in the repo.** Railway no longer accepts config-as-code files (`railway.json` / `railway.toml`) for new services; it now points to Infrastructure as Code (`.railway/railway.ts`, see [Railway's migration notes](https://docs.railway.com/infrastructure-as-code#migrating-from-config-as-code)). This repo doesn't use either: set the values in the tables below in each service's **Settings** tab (or through Railway's API). They are the settings the live deployment runs with.

## 1. Create the services

1. **web**: **New project → Deploy from GitHub repo** → this repository. Railway finds the `Dockerfile` in the repo root and builds with it. The service is named after the repo (e.g. `consultant-ic-hub`); that's fine.
2. **MongoDB**: **+ New → Docker image** → `mongo:7`. Name it `MongoDB`. Then:
   - add a **volume** mounted at `/data/db`;
   - set its **start command** (Settings → Deploy) to
     ```
     sh -c "mkdir -p /data/db/practice-os && exec docker-entrypoint.sh mongod --dbpath /data/db/practice-os --ipv6 --bind_ip ::,0.0.0.0"
     ```
   - set its variables (Variables tab):
     ```
     MONGO_INITDB_ROOT_USERNAME=mongo
     MONGO_INITDB_ROOT_PASSWORD=<long random hex, e.g. python3 -c "import secrets; print(secrets.token_hex(24))">
     MONGO_URL=mongodb://${{MONGO_INITDB_ROOT_USERNAME}}:${{MONGO_INITDB_ROOT_PASSWORD}}@${{RAILWAY_PRIVATE_DOMAIN}}:27017
     ```
   Why the start command looks like that:
   - `docker-entrypoint.sh` must stay in front of `mongod`. It is what creates the admin user and turns on password checks. A plain `mongod …` start command skips it, and the database then runs **with no password**.
   - The entrypoint only creates the user when the data folder is **empty**. Pointing `--dbpath` at a fresh subfolder of the volume guarantees that on the first start (and is how you recover if a first start went wrong: change the folder name, redeploy).
   - `--ipv6 --bind_ip ::,0.0.0.0` makes it reachable over Railway's private network.
   - Railway's own **+ New → Database → MongoDB** template is a fine alternative; it already exposes `MONGO_URL`.
3. **worker**: **+ New → GitHub repo** → the same repository again. Rename it **worker**. Set its start command (table below).
4. **Bucket**: **+ New → Bucket**. Railway gives it a generated name (e.g. `sorted-toybox`); you can rename it. **A new bucket is a staged change: click Deploy / Apply changes on the project canvas** (the "New" badge goes away). Until then it doesn't exist in the environment and its variables resolve to nothing.
5. **Domain**: on web, **Settings → Networking → Generate domain** with target port `8000`, or add your own domain. Railway injects its own `PORT` (often `8080`), so also set `PORT=8000` on web (section 3). If the two differ, the internal healthcheck still passes but the public URL answers 502.

## 2. Service settings

| Setting | web | worker | MongoDB |
|---|---|---|---|
| Dockerfile path | `Dockerfile` | `Dockerfile` | (image) |
| Start command | leave empty (image default) | `python -m app.workers` | see above |
| Pre-deploy command | `python -m app.db.migrate` | none | none |
| Healthcheck path | `/api/health/ready` | none | none |
| Healthcheck timeout | `120` | | |
| Restart policy | On failure, max 5 retries | Always | default |
| Overlap / draining seconds | `30` / `30` | — / `60` | default |
| Watch paths | `backend/app/**`, `backend/requirements.txt`, `frontend/**`, `Dockerfile` | `backend/app/**`, `backend/requirements.txt`, `Dockerfile` | |
| Volume | none | none | `/data/db` |

## 3. Variables

Set these on **both web and worker** (or once as Shared Variables). In the references, `MongoDB` and `sorted-toybox` are the **service names**: use yours.

```
SECRET_KEY=<python3 -c "import secrets; print(secrets.token_urlsafe(48))">
TOKEN_KEY=<python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
HOOK_SECRET=<python3 -c "import secrets; print(secrets.token_urlsafe(32))">
MONGO_URL=${{MongoDB.MONGO_URL}}
DB_NAME=practice_os
APP_URL=https://<your web domain>
LOG_JSON=true
VENDOR_STORAGE=live
S3_BUCKET=${{sorted-toybox.BUCKET}}
S3_ENDPOINT_URL=${{sorted-toybox.ENDPOINT}}
S3_REGION=${{sorted-toybox.REGION}}
S3_ACCESS_KEY_ID=${{sorted-toybox.ACCESS_KEY_ID}}
S3_SECRET_ACCESS_KEY=${{sorted-toybox.SECRET_ACCESS_KEY}}
S3_ADDRESSING_STYLE=virtual
ADMIN_PHONES=+91XXXXXXXXXX
STAFF_EMAIL=you@yourdomain.in
STAFF_PASSWORD=<strong password>
```

Things to check:
- **Same secrets on both services.** `SECRET_KEY`, `TOKEN_KEY` and `HOOK_SECRET` must be identical on web and worker. **Never change `TOKEN_KEY`** later: saved Gmail, Outlook and Zoom connections are encrypted with it.
- **Set `APP_URL` explicitly.** The worker has no public domain of its own, so it can't work it out, and it refuses to start without an `https://` `APP_URL`.
- **Bucket details.** Use the bucket's `BUCKET` variable, **not** `RAILWAY_BUCKET_NAME`. Railway buckets use virtual-host URLs, so `S3_ADDRESSING_STYLE=virtual` (the default) is right.
- **Order matters for storage.** Keep `VENDOR_STORAGE=fake` until the bucket is deployed. With `live` and an unresolved `S3_BUCKET`, the app refuses to start. Without a bucket, uploads go to the container's disk and vanish on redeploy, and the worker can't share files with web.

Per service:

| Variable | web | worker |
|---|---|---|
| `RUN_JOBS` | `false` | `true` |
| `PORT` | `8000` (must match the domain's target port) | not used |
| `WEB_CONCURRENCY` | `2` (uvicorn processes per replica) | not used |
| `ENSURE_INDEXES_ON_START` | `true` | `false` |

Then switch on each outside service as its keys arrive. Set each pair on both web and worker:

| Feature | Variables |
|---|---|
| Login codes by WhatsApp | `VENDOR_WHATSAPP=live`, `AISENSY_API_KEY`; optionally `AISENSY_CAMPAIGN_<NAME>` when an AiSensy API campaign isn't named like the app's (e.g. `AISENSY_CAMPAIGN_OTP_LOGIN=hub_login_code_`) |
| Login codes by SMS | `VENDOR_SMS=live`, `MSG91_AUTH_KEY`, `MSG91_TEMPLATE_ID` |
| AI agents and chat | `VENDOR_AI=live`, `ANTHROPIC_API_KEY` |
| Email | `VENDOR_EMAIL=live`, `EMAIL_API_URL`, `EMAIL_API_KEY`, `EMAIL_FROM`, `INBOUND_DOMAIN` |
| Google (Gmail, Calendar, Meet) | `VENDOR_GMAIL`, `VENDOR_GCAL`, `VENDOR_MEET` = `live`; `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Outlook | `VENDOR_OUTLOOK`, `VENDOR_OUTLOOK_CAL` = `live`; `MS_CLIENT_ID`, `MS_CLIENT_SECRET` |
| Zoom | `VENDOR_ZOOM=live`; `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` |
| Notetaker | `VENDOR_MEETBOT=live`; `MEETBOT_API_URL`, `MEETBOT_API_KEY` |
| Errors | `SENTRY_DSN` |

**Logins need WhatsApp or SMS.** Consultants log in with a code sent by WhatsApp (SMS as backup). While both are `fake`, codes are never delivered and only the staff email sign-in at `/admin/login` (Admin screen) works.

OAuth redirect URIs to register with the providers: `<APP_URL>/api/connect/gmail/callback`, `/api/connect/outlook/callback`, `/api/connect/zoom/callback`.

Webhook URLs to give the providers (each carries the secret): `<APP_URL>/api/hooks/whatsapp-inbound?secret=<HOOK_SECRET>`, and the same for `email-inbound`, `email-events` and `meetbot`.

The full list with comments is in `backend/.env.example`. **The app refuses to start with unsafe values** (default or short `SECRET_KEY`, no `TOKEN_KEY`, `http://` `APP_URL`, localhost Mongo, live messaging without `HOOK_SECRET`). The deploy log names each one.

## 4. What happens on each deploy

1. Railway builds the image from the `Dockerfile` (screens in a Node stage, then the Python server). Only changes under the watch paths trigger a build.
2. **Pre-deploy (web):** `python -m app.db.migrate` builds missing indexes and applies pending migrations under a lock. If it fails, the deploy stops and the old version keeps serving.
3. Railway starts the new web container and waits for `GET /api/health/ready` (which pings the database) before moving traffic. Old containers get 30 s to drain.
4. The worker restarts. SIGTERM lets running jobs finish their step, and job leases stop a new worker from starting a job the old one still holds.

## 5. Domains

- **Web:** a generated `*.up.railway.app` domain, or your own (`app.yourdomain.in`). `APP_URL` must match it.
- **Client pages on subdomains** (`<practice>.yourdomain.in`): add a wildcard custom domain `*.yourdomain.in` to web and set `CLIENT_DOMAIN=yourdomain.in`. Without it, client pages live at `APP_URL/c/<practice>/...`, which works out of the box.
- **Practices' own domains:** add each as a custom domain on web and map it in Admin → Accounts. `GET /api/public/domain-check?domain=...` answers 200 only for mapped domains (for a TLS proxy using on-demand certificates).

## 6. Scaling

| When | Do |
|---|---|
| Web CPU high / slow responses | raise `WEB_CONCURRENCY`, then add web replicas (stateless) |
| Jobs falling behind (Admin → Jobs shows long durations) | raise `JOB_WS_CONCURRENCY` / `JOB_AGENT_CONCURRENCY`, then add a worker replica (leases keep it safe) |
| Database CPU or connections | move to MongoDB Atlas (Mumbai, M10+, replica set) and point `MONGO_URL` at it; keep `replicas × WEB_CONCURRENCY × MONGO_MAX_POOL` under its connection limit |
| Report-heavy load | `MONGO_READ_PREFERENCE=secondaryPreferred` on a replica set |

## 7. A demo deployment (no database, no keys)

Deploy only **web**, with no pre-deploy command, and set:

```
QA_MODE=true
WEB_CONCURRENCY=1
RUN_JOBS=true
```

You get sample data and persona logins. Data resets on restart. Never give it to real users: in QA mode the code `000000` always logs in.

## 8. Checks after deploying

```bash
curl -s https://<your-app>/api/health/ready
```

You want `{"ok":true,"db":"up",...}`. Then:
- sign in at `/admin/login` with `STAFF_EMAIL` / `STAFF_PASSWORD` (also linked from the login page as "Product team? Sign in with email"). After 10 wrong passwords in 15 minutes from one network or for one email, sign-in pauses for 15 minutes;
- open **Admin → Jobs** (every job should show runs within minutes);
- upload a logo in **Settings**, redeploy web, and confirm it's still there (proves the bucket).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Pre-deploy fails with `Refusing to start with unsafe settings` | a required variable is missing; the log lists which |
| Pre-deploy fails with `Authentication failed` (code 18) | MongoDB started without its admin user, i.e. its start command bypassed `docker-entrypoint.sh`, or the data folder wasn't empty on first start. Fix the start command as above, change the `--dbpath` folder name, redeploy MongoDB, then web |
| MongoDB log says "Access control is not enabled" after start-up | the same problem: the database has no password. Fix it before storing anything |
| Public URL answers 502 "Application failed to respond", but the deploy is green | the domain's target port differs from the port the app listens on. Set `PORT=8000` on web (or change the domain's target port to the port in the log line `Uvicorn running on …`) |
| Healthcheck times out | `MONGO_URL` wrong, or MongoDB isn't deployed in this environment. `/api/health` (no database) still answers |
| `S3_*` variables resolve to nothing | the bucket was added but not deployed. Apply the staged change on the canvas |
| Uploads vanish after a redeploy | `VENDOR_STORAGE` is still `fake` |
| Jobs never run | the worker's start command isn't `python -m app.workers`, or `APP_URL` isn't set on the worker |
| Logged out on every request | `APP_URL` is `https://` but you're browsing over plain `http` (cookies are `Secure`) |
| Nobody receives a login code | WhatsApp and SMS are both `fake`; connect AiSensy or MSG91 |
