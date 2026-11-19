"""The action layer registry: one function per business action, four doors.

The same function is called by the screens (POST /api/a/<name>), the
automation engine, agents (as tools) and the MCP server. Every action has a
level that decides what an agent may do with it.
"""
from dataclasses import dataclass
from typing import Callable, Optional

from pydantic import BaseModel, ValidationError

from core.util import AppError, forbidden, not_found

LEVELS = ["read", "internal", "external", "money", "destructive"]
ALL = frozenset({"owner", "admin", "manager", "member", "collaborator", "system"})
STAFF = frozenset({"owner", "admin", "manager", "member", "system"})  # not collaborators
ADMINS = frozenset({"owner", "admin", "system"})
OWNER = frozenset({"owner", "system"})


@dataclass
class Action:
    name: str
    fn: Callable
    level: str
    roles: frozenset
    model: Optional[type]
    desc: str
    agent_ok: bool = True

    @property
    def tool_name(self):
        return self.name.replace(".", "__")


ACTIONS: dict = {}


def action(name, level, model=None, roles=ALL, desc="", agent_ok=True):
    assert level in LEVELS, level

    def deco(fn):
        ACTIONS[name] = Action(name, fn, level, frozenset(roles), model, desc or (fn.__doc__ or "").strip(), agent_ok)
        return fn
    return deco


def plain_validation(e: ValidationError) -> str:
    msgs = []
    for err in e.errors()[:3]:
        field = " ".join(str(x) for x in err.get("loc", []) if not isinstance(x, int)).replace("_", " ")
        m = err.get("msg", "is not valid").replace("Value error, ", "")
        msgs.append(f"{field.capitalize()}: {m.lower()}." if field else m)
    return " ".join(msgs) or "Some details are missing or not valid."


async def call(ctx, name, args=None):
    a = ACTIONS.get(name)
    if not a:
        raise not_found("That action")
    if ctx.role not in a.roles:
        raise forbidden()
    if ctx.read_only and a.level != "read":
        raise AppError("read_only", "Your access is paused, so you can view but not change anything.", 403)
    from actions import perm
    await perm.refuse_hidden_filters(ctx, args)
    p = None
    if a.model:
        try:
            p = a.model(**(args or {}))
        except ValidationError as e:
            raise AppError("invalid", plain_validation(e), 400)
    return await perm.redact(ctx, await a.fn(ctx, p))


def by_tool_name(tool):
    return ACTIONS.get(tool.replace("__", "."))


def tool_schema(a: Action) -> dict:
    schema = a.model.model_json_schema() if a.model else {"type": "object", "properties": {}}
    schema.pop("title", None)
    return {"name": a.tool_name, "description": f"[{a.level}] {a.desc}"[:1000], "input_schema": schema}


def registry_table():
    rows = []
    for a in sorted(ACTIONS.values(), key=lambda x: x.name):
        props = list((a.model.model_json_schema().get("properties", {}) if a.model else {}).keys())
        rows.append({"name": a.name, "level": a.level, "roles": sorted(a.roles - {"system"}),
                     "inputs": props, "desc": a.desc, "agent_ok": a.agent_ok})
    return rows


class P(BaseModel):
    """Base for action inputs: ignore unknown keys from screens and models."""
    model_config = {"extra": "ignore"}
