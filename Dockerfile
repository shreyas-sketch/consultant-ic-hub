# One image for web and worker.
#   web:    uvicorn server:app --host 0.0.0.0 --port 8000      (RUN_JOBS=false)
#   worker: python worker.py                                    (one or more)

# ---- 1. Build the screens ----
FROM node:22-slim AS screens
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build

# ---- 2. Server ----
FROM python:3.12-slim
# WeasyPrint (contract and receipt PDFs) needs Pango.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=screens /app/frontend/dist /app/frontend/dist
ENV PYTHONUNBUFFERED=1 RUN_JOBS=false PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
