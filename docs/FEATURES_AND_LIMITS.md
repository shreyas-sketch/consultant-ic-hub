# Features and limits

Generated from the limits registry (`backend/app/core/limits.py`). No plans yet: one set of values, "Everyone".
Change any value in Admin › Limits, for everyone or only accounts created from now on, or per practice in Admin › Accounts.

| Limit key | What it limits | Type | Launch value |
|---|---|---|---|
| `users_per_workspace` | Users per workspace | number | 10 users |
| `live_lead_forms` | Live lead forms | number | Unlimited |
| `session_types` | Session types | number | Unlimited |
| `active_automations` | Active automations | number | Unlimited |
| `saved_views` | Saved pipeline views | number | 5 views |
| `ai_cost_cap_paise` | AI cost cap per workspace per month | money | ₹400 |
| `whatsapp_per_month` | WhatsApp messages per month | number | 500 messages |
| `meetbot_hours_per_month` | Meeting-bot hours per month | number | 20 hours |
| `storage_mb` | File storage | number | 10240 MB |
| `report_level` | Report level | choice | advanced |
| `powered_by_hidden` | "Powered by" line hidden on client pages | bool | On |
| `custom_domain` | Custom domain | bool | On |
| `mcp_connector` | MCP connector | bool | On |
| `time_billing` | Time to invoice | bool | On |
| `budgets` | Project budgets | bool | On |
| `retainers` | Retainers | bool | On |
| `active_retainers` | Active retainers | number | Unlimited |
| `estimates` | Estimates and quick quotes | bool | On |
| `forecast_reports` | Forecast, profit and utilisation reports | bool | On |
| `bulk_invoice_actions` | Bulk invoice download, remind and export | bool | On |
| `client_tasks` | Client tasks | bool | On |
| `task_templates` | Task templates and recurring tasks | bool | On |
| `agent_setup` | Agent: setup | bool | On |
| `agent_lead` | Agent: lead | bool | On |
| `agent_followup` | Agent: followup | bool | On |
| `agent_meeting` | Agent: meeting | bool | On |
| `agent_proposal` | Agent: proposal | bool | On |
| `agent_collections` | Agent: collections | bool | On |
| `agent_daily_brief` | Agent: daily brief | bool | On |
| `agent_automation_builder` | Agent: automation builder | bool | On |
| `agent_chat` | Agent: chat | bool | On |

Users, WhatsApp messages, meeting-bot hours and storage are safety limits, not pricing.
Every feature is open to every account at launch. `require()` / `consume()` / `check_count()` are already called in the actions.
