"""All settings in one place. Every value comes from an environment variable.

QA_MODE=true runs the whole app on sample data, in memory, with every outside
service faked. No keys, no database, no internet.

`validate()` runs at startup (web and worker) and refuses to boot a production
process with unsafe values, e.g. the default SECRET_KEY.
"""
import os


def _b(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _i(name, default):
    return int(os.getenv(name, str(default)).strip())


def _list(name):
    return [p.strip() for p in os.getenv(name, "").split(",") if p.strip()]


QA_MODE = _b("QA_MODE")
# QA mode normally uses an in-memory database. QA_DB=mongo uses MONGO_URL instead
# (fake vendors, real database) for the staging load test. Use a throwaway database.
QA_DB = os.getenv("QA_DB", "memory").strip().lower()
ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("RAILWAY_ENVIRONMENT_NAME", "qa" if QA_MODE else "production")).strip().lower()

# The ONE place the product name lives on the server (frontend: src/brand.js).
BRAND_NAME = os.getenv("BRAND_NAME", "Practice OS")


def _default_app_url():
    # Railway gives every service a public domain; use it when APP_URL isn't set.
    dom = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    return f"https://{dom}" if dom else "http://localhost:8765"


APP_URL = os.getenv("APP_URL", _default_app_url()).rstrip("/")
# Client pages live on <slug>.<CLIENT_DOMAIN>; empty = /c/<slug> on APP_URL.
CLIENT_DOMAIN = os.getenv("CLIENT_DOMAIN", "")

# ---- Database ----
# Railway's MongoDB service exposes MONGO_URL; DATABASE_URL is accepted too.
MONGO_URL = os.getenv("MONGO_URL") or os.getenv("DATABASE_URL") or "mongodb://localhost:27017"
DB_NAME = os.getenv("DB_NAME", "practice_os")
MONGO_MAX_POOL = _i("MONGO_MAX_POOL", 50)          # per process; size for (replicas × uvicorn workers)
MONGO_MIN_POOL = _i("MONGO_MIN_POOL", 2)
MONGO_TIMEOUT_MS = _i("MONGO_TIMEOUT_MS", 5000)    # server selection / connect
MONGO_SOCKET_TIMEOUT_MS = _i("MONGO_SOCKET_TIMEOUT_MS", 30000)
# Read-heavy screens (reports) may read from secondaries on a replica set.
MONGO_READ_PREFERENCE = os.getenv("MONGO_READ_PREFERENCE", "primary")
# Index builds and migrations run once per deploy (Railway pre-deploy command).
# Web/worker still check indexes at boot unless this is false.
ENSURE_INDEXES_ON_START = _b("ENSURE_INDEXES_ON_START", "true")

# ---- Retention (TTL indexes; days) ----
RETAIN_JOB_RUNS_DAYS = _i("RETAIN_JOB_RUNS_DAYS", 30)
RETAIN_VENDOR_LOG_DAYS = _i("RETAIN_VENDOR_LOG_DAYS", 30)
RETAIN_EVENTS_DAYS = _i("RETAIN_EVENTS_DAYS", 90)   # processed outbox events only

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
TOKEN_KEY = os.getenv("TOKEN_KEY", "")  # Fernet key for connected-account tokens

ADMIN_PHONES = _list("ADMIN_PHONES")
STAFF_EMAIL = os.getenv("STAFF_EMAIL", "")
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "")

# Run the job scheduler inside this process. The worker sets this true;
# web processes in production set it false.
RUN_JOBS = _b("RUN_JOBS", "true")
# Per-workspace jobs (budgets, retainers, client tasks) run this many workspaces at once,
# and scheduled agents (daily brief, follow-up, collections) this many; agents call the AI.
JOB_WS_CONCURRENCY = _i("JOB_WS_CONCURRENCY", 8)
JOB_AGENT_CONCURRENCY = _i("JOB_AGENT_CONCURRENCY", 4)

# ---- Logging ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_JSON = _b("LOG_JSON", "false" if QA_MODE else "true")

# ---- AI ----
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_SMALL = os.getenv("MODEL_SMALL", "claude-haiku-5-5")
MODEL_LARGE = os.getenv("MODEL_LARGE", "claude-sonnet-5-5")
LLM_MAX_CONCURRENCY = _i("LLM_MAX_CONCURRENCY", 32)
LLM_WAIT_SECONDS = float(os.getenv("LLM_WAIT_SECONDS", "15"))
# Price per million tokens in paise (input, output). Editable in Admin > Settings.
PRICE_SMALL = (_i("PRICE_SMALL_IN", 8500), _i("PRICE_SMALL_OUT", 42500))
PRICE_LARGE = (_i("PRICE_LARGE_IN", 25500), _i("PRICE_LARGE_OUT", 127500))
USD_TO_INR_NOTE = "Prices above assume about ₹85 per US$. Check the current price list before launch."

# Vendor modes: live | fake | off. QA_MODE forces fake.
VENDORS = [
    "ai", "whatsapp", "sms", "email", "gmail", "outlook", "gcal", "outlook_cal",
    "meet", "zoom", "meetbot", "enrich", "storage", "dns",
]


def vendor_mode(name: str) -> str:
    if QA_MODE:
        return "fake"
    return os.getenv(f"VENDOR_{name.upper()}", "fake").strip().lower()


# Provider keys (only read in live mode)
AISENSY_API_KEY = os.getenv("AISENSY_API_KEY", "")


def aisensy_campaign(template: str) -> str:
    """AiSensy API campaign name for one of the app's WhatsApp messages.

    Defaults to the app's own name (otp_login, payment_reminder, ...). Override any
    of them with AISENSY_CAMPAIGN_<NAME>, e.g. AISENSY_CAMPAIGN_OTP_LOGIN=hub_login_code_.
    """
    return (os.getenv(f"AISENSY_CAMPAIGN_{template.upper()}") or "").strip() or template
MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = os.getenv("MSG91_TEMPLATE_ID", "")
EMAIL_API_URL = os.getenv("EMAIL_API_URL", "")       # transactional email provider HTTP endpoint
EMAIL_API_KEY = os.getenv("EMAIL_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "notifications@example.com")
INBOUND_DOMAIN = os.getenv("INBOUND_DOMAIN", "reply.example.com")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID", "")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET", "")
MEETBOT_API_URL = os.getenv("MEETBOT_API_URL", "")
MEETBOT_API_KEY = os.getenv("MEETBOT_API_KEY", "")

# ---- File storage ----
# S3-compatible bucket: Railway Storage Buckets, Cloudflare R2, AWS S3, MinIO.
# Railway buckets expose BUCKET / ENDPOINT / ACCESS_KEY_ID / SECRET_ACCESS_KEY / REGION;
# reference them from these names in the service variables.
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_REGION = os.getenv("S3_REGION", os.getenv("AWS_REGION", ""))
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", os.getenv("AWS_ACCESS_KEY_ID", ""))
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
S3_ADDRESSING_STYLE = os.getenv("S3_ADDRESSING_STYLE", "virtual")   # "path" for MinIO
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/practice-os-uploads")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# Shared secret for inbound webhooks (/api/hooks/*). Give providers the URL with
# ?secret=<HOOK_SECRET>, or send it in an X-Hook-Secret header. Required in production
# whenever WhatsApp, email or the notetaker is live.
HOOK_SECRET = os.getenv("HOOK_SECRET", "")

OTP_PER_IP_PER_HOUR = _i("OTP_PER_IP_PER_HOUR", 30 if not QA_MODE else 1000)

# Tests only: Client ID Metadata Documents served without the network (QA mode, *.test hosts).
QA_CIMD = {}

_DEFAULT_SECRET = "dev-secret-change-me"


class ConfigError(RuntimeError):
    pass


def problems() -> list:
    """Unsafe or inconsistent values for a non-QA process. Empty list = fine."""
    if QA_MODE:
        return []
    out = []
    if SECRET_KEY == _DEFAULT_SECRET or len(SECRET_KEY) < 32:
        out.append("SECRET_KEY must be set to a random string of at least 32 characters.")
    if not TOKEN_KEY:
        out.append("TOKEN_KEY must be set (Fernet key for connected-account tokens).")
    if not APP_URL.startswith("https://"):
        out.append("APP_URL must be the public https:// URL of the app.")
    if MONGO_URL.startswith("mongodb://localhost"):
        out.append("MONGO_URL points at localhost; set it to your MongoDB service (e.g. ${{MongoDB.MONGO_URL}} on Railway).")
    if vendor_mode("storage") == "live" and not S3_BUCKET:
        out.append("VENDOR_STORAGE=live needs S3_BUCKET (and S3_ENDPOINT_URL for non-AWS buckets).")
    if vendor_mode("ai") == "live" and not ANTHROPIC_API_KEY:
        out.append("VENDOR_AI=live needs ANTHROPIC_API_KEY.")
    if not HOOK_SECRET and any(vendor_mode(v) == "live" for v in ("whatsapp", "email", "gmail", "outlook", "meetbot")):
        out.append("HOOK_SECRET must be set when WhatsApp, email or the notetaker is live (it protects /api/hooks/*).")
    for v in VENDORS:
        if vendor_mode(v) not in ("live", "fake", "off"):
            out.append(f"VENDOR_{v.upper()} must be live, fake or off.")
    return out


def validate():
    errs = problems()
    if errs and not _b("ALLOW_UNSAFE_CONFIG"):
        raise ConfigError("Refusing to start with unsafe settings:\n  - " + "\n  - ".join(errs)
                          + "\n(Set ALLOW_UNSAFE_CONFIG=true only for a throwaway staging box.)")
    return errs
