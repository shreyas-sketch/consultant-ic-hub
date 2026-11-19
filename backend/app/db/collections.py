"""Every collection, and whether it belongs to one workspace (tenant) or is global.

Tenant collections carry `workspace_id` on every document and are only reached
through `ctx.data.<name>` (app/db/tenant.py), which adds the workspace filter and
hides soft-deleted rows. This is also the future shard key: see docs/ARCHITECTURE.md.
"""

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
    "workspaces", "users", "otp_codes", "sessions_auth", "invites", "limit_values", "account_overrides",
    "admin_changes", "admin_settings", "job_locks", "job_runs", "vendor_log", "client_sessions",
    "domains", "oauth_clients", "oauth_requests", "oauth_codes", "oauth_tokens", "oauth_states",
    "schema_migrations", "login_failures",
]
