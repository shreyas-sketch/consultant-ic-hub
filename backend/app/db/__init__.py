"""Database connection and indexes.

QA mode and tests use an in-memory MongoDB (mongomock-motor). Production uses
MongoDB Atlas. Code never relies on multi-document transactions: money and
sends are made safe with unique keys instead, so the same code is correct on
both.
"""
from app.core import settings

_client = None
_db = None


def get_db():
    global _client, _db
    if _db is None:
        if settings.QA_MODE and settings.QA_DB != "mongo":
            from mongomock_motor import AsyncMongoMockClient
            _client = AsyncMongoMockClient()
        else:
            from motor.motor_asyncio import AsyncIOMotorClient
            _client = AsyncIOMotorClient(settings.MONGO_URL)
        _db = _client[settings.DB_NAME]
    return _db


def reset_db():
    """Tests only: start from an empty in-memory database."""
    global _client, _db
    _client = None
    _db = None


TENANT_COLLECTIONS = [
    "memberships", "contacts", "projects", "stages", "views", "notes", "tags", "time_entries",
    "activity", "tasks", "lead_forms", "form_submissions", "form_events", "templates",
    "client_files", "file_versions", "file_events", "signatures", "invoices", "payments",
    "payment_claims", "ledger", "credit_notes", "promo_codes", "recurring_invoices",
    "session_types", "sessions", "slot_locks", "threads", "messages", "outbound_queue",
    "automations", "automation_runs", "events", "agent_settings", "agent_runs", "approvals",
    "notifications", "audit_log", "usage", "expenses", "meeting_notes", "daily_briefs",
    "suggested_leads", "connections", "mcp_tokens", "uploads", "counters", "portal_messages",
    # add-ons: rates, time billing, budgets, retainers, estimates, task templates, exports
    "services", "rate_cards", "rate_card_lines", "rate_changes", "member_cost_rates", "timers",
    "budgets", "budget_cycles", "retainers", "retainer_periods", "estimates", "task_templates", "exports",
]

# Collections with no workspace_id (global by design).
GLOBAL_COLLECTIONS = [
    "users", "otp_codes", "sessions_auth", "invites", "limit_values", "account_overrides",
    "admin_changes", "admin_settings", "job_locks", "job_runs", "vendor_log", "client_sessions",
    "domains", "oauth_clients", "oauth_requests", "oauth_codes", "oauth_tokens",
]


async def ensure_indexes(db=None):
    db = db or get_db()
    for c in TENANT_COLLECTIONS:
        await db[c].create_index("workspace_id")
    await db.users.create_index("phone", unique=True)
    await db.invites.create_index("phone", unique=True)
    await db.memberships.create_index([("workspace_id", 1), ("user_id", 1)], unique=True)
    await db.projects.create_index([("workspace_id", 1), ("stage_id", 1)])
    await db.automation_runs.create_index([("status", 1), ("wake_at", 1)])
    await db.automation_runs.create_index("run_key", unique=True)
    await db.events.create_index([("processed", 1), ("created_at", 1)])
    # Invoice numbers: unique per workspace per financial year (set only when issued).
    await db.invoices.create_index("number_key", unique=True, sparse=True)
    await db.approvals.create_index("idempotency_key", unique=True)
    await db.ledger.create_index("key", unique=True)
    await db.outbound_queue.create_index("idempotency_key", unique=True)
    await db.client_files.create_index("token", unique=True)
    await db.contacts.create_index([("workspace_id", 1), ("phone", 1)])
    await db.contacts.create_index([("workspace_id", 1), ("email", 1)])
    await db.domains.create_index("host", unique=True)
    # Add-ons: each of these keys makes a repeated job or a double tap harmless.
    await db.budget_cycles.create_index("cycle_key", unique=True)
    await db.retainer_periods.create_index("period_key", unique=True)
    await db.tasks.create_index("occurrence_key", unique=True, sparse=True)
    await db.time_entries.create_index([("workspace_id", 1), ("project_id", 1), ("date", 1)])
    await db.oauth_clients.create_index("client_id", unique=True)
    await db.oauth_codes.create_index("code_hash", unique=True)
    await db.oauth_tokens.create_index("token_hash", unique=True)
    await db.mcp_tokens.create_index("token_hash", unique=True)
