# One image for both Railway services:
#   web:    uvicorn app.main:app            (RUN_JOBS=false; the default CMD below)
#   worker: python -m app.workers           (RUN_JOBS=true; set as the worker's start command)
# Pre-deploy (web): python -m app.db.migrate  (indexes + migrations, once per deploy)
# Railway settings for each service: docs/DEPLOY_RAILWAY.md

# ---- 1. Build the screens ----
FROM node:22-bookworm-slim AS screens
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Server ----
FROM python:3.12-slim-bookworm
# WeasyPrint (contract, invoice and receipt PDFs) needs Pango.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    RUN_JOBS=false PORT=8000 WEB_CONCURRENCY=2 \
    FRONTEND_DIST=/app/frontend/dist UPLOAD_DIR=/data/uploads
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY --from=screens /app/frontend/dist /app/frontend/dist
RUN useradd --system --uid 10001 --home /app app && mkdir -p /data/uploads && chown -R app /data
USER app
EXPOSE 8000
# Railway sends SIGTERM on redeploy; uvicorn drains in-flight requests.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 20 --no-server-header"]
