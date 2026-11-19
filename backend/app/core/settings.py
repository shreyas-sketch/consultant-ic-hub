"""All settings in one place. Every value can be set by environment variable.

QA_MODE=true runs the whole app on sample data, in memory, with every outside
service faked. No keys, no database, no internet.
"""
import os


def _b(name, default="false"):
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


QA_MODE = _b("QA_MODE")
# QA mode normally uses an in-memory database. QA_DB=mongo uses MONGO_URL instead
# (fake vendors, real database) for the staging load test. Use a throwaway database.
QA_DB = os.getenv("QA_DB", "memory").strip().lower()

# The ONE place the product name lives on the server (frontend: src/brand.js).
BRAND_NAME = os.getenv("BRAND_NAME", "Practice OS")

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "practice_os")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
APP_URL = os.getenv("APP_URL", "http://localhost:8765")
# Client pages live on <slug>.<CLIENT_DOMAIN>; in QA they live under /c/ on APP_URL.
CLIENT_DOMAIN = os.getenv("CLIENT_DOMAIN", "")

ADMIN_PHONES = [p.strip() for p in os.getenv("ADMIN_PHONES", "").split(",") if p.strip()]
STAFF_EMAIL = os.getenv("STAFF_EMAIL", "")
STAFF_PASSWORD = os.getenv("STAFF_PASSWORD", "")

# Run the job scheduler inside this process. The worker process sets this true;
# web processes in production set it false.
RUN_JOBS = _b("RUN_JOBS", "true")

# AI
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_SMALL = os.getenv("MODEL_SMALL", "claude-haiku-5-5")
MODEL_LARGE = os.getenv("MODEL_LARGE", "claude-sonnet-5-5")
LLM_MAX_CONCURRENCY = int(os.getenv("LLM_MAX_CONCURRENCY", "32"))
LLM_WAIT_SECONDS = float(os.getenv("LLM_WAIT_SECONDS", "15"))
# Price per million tokens in paise (input, output). Editable in Admin > Settings.
PRICE_SMALL = (int(os.getenv("PRICE_SMALL_IN", "8500")), int(os.getenv("PRICE_SMALL_OUT", "42500")))
PRICE_LARGE = (int(os.getenv("PRICE_LARGE_IN", "25500")), int(os.getenv("PRICE_LARGE_OUT", "127500")))
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
S3_BUCKET = os.getenv("S3_BUCKET", "")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/tmp/practice-os-uploads")
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
TOKEN_KEY = os.getenv("TOKEN_KEY", "")  # Fernet key for connected-account tokens

OTP_PER_IP_PER_HOUR = int(os.getenv("OTP_PER_IP_PER_HOUR", "1000"))

# Tests only: Client ID Metadata Documents served without the network (QA mode, *.test hosts).
QA_CIMD = {}
