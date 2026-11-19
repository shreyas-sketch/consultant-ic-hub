"""Generate the docs that must match the code exactly:
docs/API_CONTRACT.md, docs/AGENT_SPEC.md (tool registry part), docs/FEATURES_AND_LIMITS.md.

    cd backend && python ../scripts/gen_docs.py
"""
import os
import sys

os.environ.update({"QA_MODE": "true", "QA_SEED": "false", "RUN_JOBS": "false"})
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app import main as server  # noqa: E402,F401
from app.domain.registry import ACTIONS  # noqa: E402
from app.agents.defs import AGENTS  # noqa: E402
from app.agents.runtime import GUARD  # noqa: E402
from app.core.limits import REGISTRY  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
os.makedirs(DOCS, exist_ok=True)


def fields(a):
    if not a.model:
        return "—"
    s = a.model.model_json_schema()
    req = set(s.get("required", []))
    out = []
    for k, v in s.get("properties", {}).items():
        t = v.get("type") or "/".join(x.get("type", "") for x in v.get("anyOf", []) if x.get("type") != "null") or "object"
        out.append(f"`{k}`{'' if k in req else '?'}: {t}")
    return ", ".join(out) or "—"


def roles(a):
    r = sorted(a.roles - {"system"})
    return "everyone" if len(r) == 5 else ", ".join(r)


lines = ["# API contract", "", "Generated from the code by `scripts/gen_docs.py`. Do not edit by hand.", "",
         "## How screens call the API", "",
         "- Every business action: `POST /api/a/<action>` with a JSON body. Login cookie required.",
         "- The same functions are used by automations, agents (as tools) and the MCP server.",
         "- Errors: `{\"error\": {\"code\", \"message\", \"extra\"?}}` with a plain-English message.",
         "- Common codes: 400 `invalid`, 401 `logged_out`, 402 `limit`, 403 `forbidden` / `locked` / `read_only` / `not_invited`, "
         "404 `not_found`, 409 `gone` / `locked` / `slot_taken` / `changed`, 429 `rate_limited` / `cooldown`, 503 `busy`.",
         "- `?` after a field means optional. Money is always integer paise.", "",
         "## Actions", "", "| Action | Level | Who | Inputs | What it does |", "|---|---|---|---|---|"]
for a in sorted(ACTIONS.values(), key=lambda x: x.name):
    lines.append(f"| `{a.name}` | {a.level} | {roles(a)} | {fields(a)} | {a.desc.replace('|', '/')} |")
lines += ["", "## Other routes", "",
          "| Route | What it does |", "|---|---|",
          "| `POST /api/auth/otp/request` `{phone}` | Send a login code (WhatsApp, SMS fallback). Not invited → 403 \"This product is by invitation right now.\" |",
          "| `POST /api/auth/otp/verify` `{phone, code}` | Log in; sets the access + refresh cookies. |",
          "| `GET /api/auth/me` · `POST /api/auth/switch` · `POST /api/auth/logout` · `POST /api/auth/staff` | Session, practice switch, logout, staff login. |",
          "| `POST /api/upload` `{data, name, kind, project_id?}` | Upload (data URL, max 8 MB). `kind: logo` sets the practice logo. |",
          "| `GET /api/preview/f/<file_id>` | The working copy of a client file, rendered exactly as the client sees it. |",
          "| `GET /api/connect/<gmail\\|outlook\\|zoom>/start` · `/callback` | Connect an account (OAuth). |",
          "| `GET /api/public/brand/<slug>` | Practice brand for client pages. |",
          "| `GET/POST /api/public/<slug>/form/<form>` (`/event`, `/submit`) | Lead form. |",
          "| `GET/POST /api/public/<slug>/book/<type>` (`/slots`) | Booking page. |",
          "| `GET /api/public/f/<token>` + `POST .../page, answers, select, plan, promo, otp, sign, book, claim, complete` | Client file viewer. |",
          "| `GET /api/public/i/<token>` · `POST .../claim` · `GET .../receipt/<item>.pdf` | Invoice page, \"I've paid\", receipt. |",
          "| `GET /api/public/d/<token>` | Download (e.g. signed contract PDF). |",
          "| `/api/public/<slug>/portal/...` (`code`, `login`, `me`, `project/<id>`, `message`, `upload`, `session/<id>/reschedule`, `logout`) | Client portal. |",
          "| `POST /api/hooks/email-inbound`, `/whatsapp-inbound`, `/email-events`, `/meetbot` | Provider webhooks. |",
          "| `/api/admin/*` | Admin panel (401 logged out, 403 for non-admins). |",
          "| `POST /mcp` | MCP server (JSON-RPC: initialize, tools/list, tools/call). Bearer connector token. |",
          "| `POST /api/qa/*` | QA mode only: persona login, outbox, clock, run jobs. |"]
open(os.path.join(DOCS, "API_CONTRACT.md"), "w").write("\n".join(lines) + "\n")

ag = ["# Agent spec", "", "Generated from the code by `scripts/gen_docs.py`.", "",
      "## Rules every agent follows", "", "```", GUARD.strip(), "```", "",
      "- Tool levels: read and internal run straight away; external and money become Approvals unless autonomy allows; destructive never.",
      "- Autonomy (per agent, per practice): Off · Suggest · Draft for approval (default) · Auto. In Auto, money actions still wait.",
      "- Context pack: practice profile and setup answers; the project (stage, type, value, source); client data inside `<client_data>`.",
      "- Limits per run: 8 model turns, ₹25. Per practice: the monthly AI budget (limit key `ai_cost_cap_paise`). At 100% agents stop cleanly.",
      "- Every run is saved with every tool call, its verdict, tokens and cost in paise; agent work shows on the project Activity feed.",
      "- Fake mode: each agent's `plan` produces realistic tool calls from the real account data, so every screen works with no keys.", ""]
for k, d in AGENTS.items():
    tools = "every tool the user's role allows" if d.tools == "*" else ", ".join(f"`{t}`" for t in d.tools) or "— (builds the account directly)"
    ag += [f"## {d.label} (`{k}`)", "", f"- Wakes on: {d.wakes_on}", f"- Default mode: {d.default_mode}", f"- Model size: {d.model_size}",
           f"- Tools: {tools}", f"- Prompt: {d.prompt}", ""]
ag += ["## Tool registry", "", "| Tool name | Level | Agents may use | Inputs |", "|---|---|---|---|"]
for a in sorted(ACTIONS.values(), key=lambda x: x.name):
    ag.append(f"| `{a.tool_name}` | {a.level} | {'yes' if a.agent_ok else 'no'} | {fields(a)} |")
open(os.path.join(DOCS, "AGENT_SPEC.md"), "w").write("\n".join(ag) + "\n")

fl = ["# Features and limits", "", "Generated from the limits registry (`backend/core/limits.py`). No plans yet: one set of values, \"Everyone\".",
      "Change any value in Admin › Limits, for everyone or only accounts created from now on, or per practice in Admin › Accounts.", "",
      "| Limit key | What it limits | Type | Launch value |", "|---|---|---|---|"]
for k, (label, typ, default, unit) in REGISTRY.items():
    v = "Unlimited" if default is None else ("On" if default is True else "Off" if default is False else
                                             f"₹{default // 100}" if typ == "money" else f"{default} {unit}".strip())
    fl.append(f"| `{k}` | {label} | {typ.split(':')[0]} | {v} |")
fl += ["", "Users, WhatsApp messages, meeting-bot hours and storage are safety limits, not pricing.",
       "Every feature is open to every account at launch. `require()` / `consume()` / `check_count()` are already called in the actions."]
open(os.path.join(DOCS, "FEATURES_AND_LIMITS.md"), "w").write("\n".join(fl) + "\n")
print(f"{len(ACTIONS)} actions, {len(AGENTS)} agents, {len(REGISTRY)} limit keys documented.")
