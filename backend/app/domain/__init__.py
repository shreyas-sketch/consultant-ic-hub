"""The domain layer: every business action, grouped by bounded context.

Importing a module registers its actions in `app.domain.registry.ACTIONS`.
`load()` imports them all; the web app, the worker and the scripts call it once.
"""
import importlib

MODULES = [
    "app.domain.sales.crm",
    "app.domain.sales.forms",
    "app.domain.documents.files",
    "app.domain.documents.uploads",
    "app.domain.billing.money",
    "app.domain.billing.rates",
    "app.domain.billing.timebill",
    "app.domain.billing.budgets",
    "app.domain.billing.retainers",
    "app.domain.billing.estimates",
    "app.domain.engagement.inbox",
    "app.domain.engagement.scheduling",
    "app.domain.engagement.client_tasks",
    "app.domain.workspace.workspace",
    "app.domain.workspace.approvals",
    "app.domain.workspace.connections",
    "app.domain.automation.automations",
    "app.domain.automation.agent_actions",
    "app.domain.analytics.reports",
    "app.domain.analytics.insight",
]


def load():
    for m in MODULES:
        importlib.import_module(m)
    from app.domain.registry import ACTIONS
    return ACTIONS
