"""Every index, declared once. `ensure_indexes()` is idempotent and runs on each deploy.

Rules followed here:
- Tenant indexes lead with `workspace_id` (every tenant query has it, via ctx.data),
  then equality fields, then sort/range fields (the ESR rule).
- Unique keys are what make retries and races harmless (see docs/BACKEND_DESIGN.md).
- Worker jobs scan across tenants; each scan has its own index on its status fields.
- Short-lived data expires through TTL indexes instead of cleanup jobs.
- Every index has an explicit name, so changing one is a deliberate migration.
"""
import logging
from dataclasses import dataclass, field

from app.core import settings
from app.db.collections import TENANT_COLLECTIONS

log = logging.getLogger("app.db.indexes")
DAY = 86400


@dataclass
class Ix:
    coll: str
    keys: list
    unique: bool = False
    sparse: bool = False
    ttl: int = None              # expireAfterSeconds
    name: str = None
    opts: dict = field(default_factory=dict)

    def spec(self):
        keys = [(k, 1) if isinstance(k, str) else k for k in self.keys]
        kw = dict(self.opts)
        kw["name"] = self.name or "_".join(f"{k}_{d}" for k, d in keys)
        if self.unique:
            kw["unique"] = True
        if self.sparse:
            kw["sparse"] = True
        if self.ttl is not None:
            kw["expireAfterSeconds"] = int(self.ttl)
        return keys, kw


WS = "workspace_id"
DEL = "deleted_at"


def _tenant():
    # The original single-field index on every tenant collection (kept: cheap, used by counts and admin).
    return [Ix(c, [WS]) for c in TENANT_COLLECTIONS]


def specs():
    out = _tenant()
    out += [
        # ---- identity, auth and sessions (global) ----
        Ix("users", ["phone"], unique=True),
        Ix("invites", ["phone"], unique=True),
        Ix("invites", ["status", "via"]),
        Ix("workspaces", ["slug"], unique=True),
        Ix("workspaces", ["owner_id"]),
        Ix("domains", ["host"], unique=True),
        Ix("sessions_auth", ["refresh_hash"]),
        Ix("sessions_auth", ["user_id"]),
        Ix("sessions_auth", ["expires_at"], ttl=0),
        Ix("otp_codes", ["phone", ("created_at", -1)]),
        Ix("otp_codes", ["ip", "created_at"]),
        Ix("otp_codes", ["expires_at"], ttl=DAY),
        Ix("client_sessions", ["token_hash"]),
        Ix("client_sessions", ["expires_at"], ttl=0),
        Ix("oauth_states", ["expires_at"], ttl=0),
        Ix("oauth_clients", ["client_id"], unique=True),
        Ix("oauth_codes", ["code_hash"], unique=True),
        Ix("oauth_codes", ["expires_at"], ttl=DAY),
        Ix("oauth_requests", ["expires_at"], ttl=DAY),
        Ix("oauth_tokens", ["token_hash"], unique=True),
        Ix("oauth_tokens", ["family", "kind"]),
        Ix("oauth_tokens", [WS, "client_id", "user_id"]),
        # Keep used refresh tokens a week past expiry so reuse can still be detected.
        Ix("oauth_tokens", ["expires_at"], ttl=7 * DAY),
        Ix("mcp_tokens", ["token_hash"], unique=True),
        Ix("account_overrides", [WS, "key"]),
        Ix("job_runs", ["job", ("started_at", -1)]),
        Ix("job_runs", ["started_at"], ttl=settings.RETAIN_JOB_RUNS_DAYS * DAY, name="started_at_ttl"),
        Ix("vendor_log", ["at"], ttl=settings.RETAIN_VENDOR_LOG_DAYS * DAY, name="at_ttl"),

        # ---- money: unique keys stop double payments and number gaps ----
        Ix("invoices", ["number_key"], unique=True, sparse=True),
        Ix("invoices", ["token"]),                                 # public invoice page
        Ix("invoices", [WS, "project_id", "status"]),
        Ix("invoices", [WS, "retainer_id"]),
        Ix("invoices", ["status", DEL]),                           # money job (cross-tenant)
        Ix("ledger", ["key"], unique=True),
        Ix("ledger", [WS, "invoice_id", "type"]),
        Ix("ledger", [WS, "project_id", "type"]),
        Ix("payment_claims", [WS, "status", ("created_at", -1)]),
        Ix("recurring_invoices", ["active", DEL]),
        Ix("time_entries", [WS, "project_id", "date"]),
        Ix("time_entries", [WS, "project_id", "billing_status"]),
        Ix("time_entries", [WS, "user_id", "date"]),
        Ix("time_entries", [WS, "invoice_id"]),
        Ix("expenses", [WS, "project_id", "billable", "date"]),
        Ix("budget_cycles", ["cycle_key"], unique=True),
        Ix("budgets", [WS, "project_id", "active"]),
        Ix("retainer_periods", ["period_key"], unique=True),
        Ix("retainer_periods", [WS, "retainer_id", "status"]),
        Ix("retainers", [WS, "status"]),
        Ix("retainers", [WS, "project_ids"]),
        Ix("estimates", [WS, "project_id", "status"]),
        Ix("rate_card_lines", [WS, "rate_card_id", "unit"]),
        Ix("rate_changes", [WS, "line_id", "status", "effective_from"]),
        Ix("member_cost_rates", [WS, "user_id", "effective_from"]),

        # ---- CRM and delivery ----
        Ix("memberships", [WS, "user_id"], unique=True),
        Ix("memberships", ["user_id", "active"]),
        Ix("projects", [WS, "stage_id", "archived", ("created_at", -1)]),
        Ix("projects", [WS, "contact_ids"]),
        Ix("contacts", [WS, "phone"]),
        Ix("contacts", [WS, "email"]),
        Ix("client_files", ["token"], unique=True),
        Ix("client_files", [WS, "project_id", "status"]),
        Ix("client_files", ["scheduled_send.schedule_at"], sparse=True),   # outbound job
        Ix("file_versions", [WS, "file_id"]),
        Ix("file_events", [WS, "file_id"]),
        Ix("signatures", [WS, "file_id", "block_id", "status"]),
        Ix("activity", [WS, "project_id", ("at", -1)]),
        Ix("notes", [WS, "project_id", "kind"]),
        Ix("tasks", ["occurrence_key"], unique=True, sparse=True),
        Ix("tasks", ["token"], sparse=True),                       # client task link
        Ix("tasks", [WS, "project_id", "audience", "done"]),
        Ix("tasks", [WS, "audience", "done", "due_at"]),
        Ix("uploads", ["token"], sparse=True),                     # public download link
        Ix("uploads", [WS, "project_id"]),
        Ix("lead_forms", [WS, "slug"]),
        Ix("form_events", [WS, "kind", "ip", "at"]),

        # ---- scheduling ----
        Ix("sessions", ["status", "start"]),                       # reminders job
        Ix("sessions", ["status", "hold_expires_at"]),             # holds job
        Ix("sessions", ["status", "end"]),                         # session.ended job
        Ix("sessions", [WS, "project_id", "status"]),
        Ix("sessions", [WS, "type_id", "start", "status"]),
        Ix("sessions", ["notetaker.bot_id"], sparse=True),         # notetaker webhook

        # ---- inbox and outbound ----
        Ix("threads", [WS, "project_id"]),
        Ix("messages", [WS, "project_id", ("created_at", -1)]),
        Ix("messages", ["provider_id"], sparse=True),              # delivery webhooks
        Ix("outbound_queue", ["idempotency_key"], unique=True),
        Ix("outbound_queue", ["status", "send_at"]),
        Ix("notifications", [WS, "user_id", "read"]),

        # ---- automations, events, agents, approvals ----
        Ix("events", ["processed", "created_at"]),
        Ix("events", ["created_at"], ttl=settings.RETAIN_EVENTS_DAYS * DAY, name="processed_events_ttl",
           opts={"partialFilterExpression": {"processed": True}}),
        Ix("automations", ["active", DEL, "trigger.type"]),
        Ix("automation_runs", ["run_key"], unique=True),
        Ix("automation_runs", ["status", "wake_at"]),
        Ix("automation_runs", [WS, "project_id", "status"]),
        Ix("automation_runs", [WS, "automation_id", "status"]),
        Ix("approvals", ["idempotency_key"], unique=True),
        Ix("approvals", ["status", "expires_at"]),
        Ix("approvals", [WS, "project_id", "status"]),
        Ix("agent_runs", [WS, "agent", ("created_at", -1)]),
        Ix("suggested_leads", [WS, "status"]),
        Ix("exports", ["status", DEL]),
        Ix("connections", ["provider", "lead_finder"]),
        Ix("usage", ["month"]),
    ]
    return out


# Mongo error codes for "an index with this name/keys exists with other options".
_CONFLICT = {85, 86}


async def ensure_indexes(db=None):
    """Create any missing index. Conflicts with an existing index are logged, not fatal:
    changing an index's options is done by a migration (drop + create)."""
    from pymongo.errors import OperationFailure

    from app.db.client import get_db
    db = db or get_db()
    made = 0
    for ix in specs():
        keys, kw = ix.spec()
        try:
            await db[ix.coll].create_index(keys, **kw)
            made += 1
        except OperationFailure as e:
            if getattr(e, "code", None) in _CONFLICT or "already exists" in str(e):
                log.warning("index %s.%s conflicts with an existing index; leave for a migration", ix.coll, kw["name"])
                continue
            raise
    return made
