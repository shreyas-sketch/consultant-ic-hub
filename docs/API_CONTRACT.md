# API contract

Generated from the code by `scripts/gen_docs.py`. Do not edit by hand.

## How screens call the API

- Every business action: `POST /api/a/<action>` with a JSON body. Login cookie required.
- The same functions are used by automations, agents (as tools) and the MCP server.
- Errors: `{"error": {"code", "message", "extra"?}}` with a plain-English message.
- Common codes: 400 `invalid`, 401 `logged_out`, 402 `limit`, 403 `forbidden` / `locked` / `read_only` / `not_invited`, 404 `not_found`, 409 `gone` / `locked` / `slot_taken` / `changed`, 429 `rate_limited` / `cooldown`, 503 `busy`.
- `?` after a field means optional. Money is always integer paise.

## Actions

| Action | Level | Who | Inputs | What it does |
|---|---|---|---|---|
| `agents.list` | read | everyone | — | Each agent: on/off, autonomy, instructions, recent runs, cost this month. |
| `agents.run` | internal | admin, manager, member, owner | `agent`: string, `project_id`?: string, `instruction`?: string | Ask an agent to do its job now. |
| `agents.run_get` | read | everyone | `id`: string | One agent run. |
| `agents.runs` | read | everyone | `agent`?: string, `project_id`?: string, `limit`?: integer | Agent runs with every tool call, cost and result. |
| `agents.update` | internal | admin, owner | `agent`: string, `autonomy`?: string, `enabled`?: boolean, `instructions`?: string | Change an agent's autonomy, on/off or standing instructions. |
| `approvals.approve` | internal | everyone | `id`: string, `edits`?: object | Approve and run a prepared action (optionally after editing it). |
| `approvals.list` | read | everyone | `status`?: string, `project_id`?: string | Things waiting for your OK. |
| `approvals.skip` | internal | everyone | `id`: string, `edits`?: object | Skip a prepared action. Nothing is sent. |
| `audit.list` | read | admin, owner | — | Recent audit log. |
| `automations.cancel_run` | internal | everyone | `run_id`: string | Cancel a running automation on a project. |
| `automations.create_from_spec` | internal | everyone | `spec`: object | Save an automation drafted from a plain-language request (switched off). |
| `automations.delete` | destructive | admin, owner | `id`: string | Delete an automation. |
| `automations.get` | read | everyone | `id`: string | One automation. |
| `automations.list` | read | everyone | — | All automations with their recent runs. |
| `automations.meta` | read | everyone | — | Triggers, actions and conditions the builder offers. |
| `automations.run_manual` | internal | everyone | `automation_id`: string, `project_id`: string | Run an automation on a project now, by hand. |
| `automations.runs` | read | everyone | `automation_id`?: string, `project_id`?: string, `limit`?: integer | Automation runs with every step's result. |
| `automations.save` | internal | admin, manager, owner | `id`?: string, `name`: string, `trigger`: object, `steps`: array, `project_types`?: array, `active`?: boolean | Create or update an automation. Runs already going keep their old steps. |
| `automations.skip_step` | internal | everyone | `run_id`: string | Skip the step a run is on (not condition steps). |
| `automations.test_run` | read | everyone | `automation_id`?: string, `spec`?: object, `project_id`?: string | Run an automation on a sample project with a fast clock. Nothing is sent. |
| `automations.toggle` | internal | admin, manager, owner | `id`: string, `active`: boolean | Switch an automation on or off. |
| `automations.why` | read | everyone | `automation_id`: string, `project_id`: string | "Why didn't this run?" for one automation on one project, in plain words. |
| `availability.find_slots` | read | everyone | `session_type_id`: string, `date_from`: string, `date_to`?: string | Open times for a session type between two dates. |
| `briefs.today` | read | everyone | — | Today's brief: three priorities, money due this week, what changed. |
| `budgets.at_risk` | read | everyone | — | Projects at or over 80% of their budget. |
| `budgets.create` | internal | admin, manager, owner | `project_id`: string, `type`?: string, `amount_paise`?: integer, `amount_hours`?: number, `amount_days`?: number, `counts`?: string, `reset`?: string, `thresholds`?: array, `start_date`?: string | Give a project a budget: a fee or hours/days, what counts, optional weekly/monthly/quarterly reset, alert points. |
| `budgets.forecast` | read | everyone | `project_id`: string | Budget used so far (by day) and the forecast from open task estimates. |
| `budgets.get` | read | everyone | `project_id`: string | A project's budget: used, left, dates, next reset and past cycles. |
| `budgets.remove` | internal | admin, manager, owner | `project_id`: string | Stop tracking a project's budget. History stays. |
| `budgets.update` | internal | admin, manager, owner | `project_id`: string, `type`?: string, `amount_paise`?: integer, `amount_hours`?: number, `amount_days`?: number, `counts`?: string, `reset`?: string, `thresholds`?: array, `start_date`?: string | Change a project's budget. |
| `calendar.list` | read | everyone | `date_from`: string, `date_to`: string, `show`?: array | Calendar items between two dates: sessions, project dates, payment dues, tasks. |
| `chat.send` | internal | everyone | `message`: string, `history`?: array, `project_id`?: string | Ask or tell: answers questions and carries out requests. |
| `client_tasks.assign` | external | admin, manager, member, owner | `project_id`: string, `title`: string, `details`?: string, `due_at`?: string, `contact_id`?: string, `channel`?: string, `remind_days_before`?: integer | Ask the client for something (e.g. 'Share last year's P&L') with a due date. It goes by WhatsApp or email with a link. |
| `client_tasks.complete` | internal | admin, manager, member, owner | `id`: string | Mark something you asked the client for as done (e.g. they sent it another way). |
| `client_tasks.list` | read | everyone | `project_id`?: string, `status`?: string | What you're waiting on clients for. |
| `client_tasks.remind` | external | admin, manager, member, owner | `id`: string | Remind the client about something you asked for. |
| `connections.disconnect` | destructive | everyone | `id`: string, `lead_finder`?: boolean | Disconnect an account. |
| `connections.list` | read | everyone | — | Connected accounts. |
| `connections.update` | internal | everyone | `id`: string, `lead_finder`?: boolean | Turn the inbox lead finder on or off for a connected inbox. |
| `contacts.create` | internal | admin, manager, member, owner | `name`: string, `phone`?: string, `email`?: string, `company`?: string, `role`?: string, `source`?: string, `tags`?: array, `notes`?: string | Add a contact (lead or client). |
| `contacts.get` | read | everyone | `id`: string | One contact with all their projects, payments and total value. |
| `contacts.import_csv` | internal | admin, manager, owner | `rows`: array, `create_projects`?: boolean, `source`?: string | Import contacts from CSV rows (name, phone, email, company). |
| `contacts.search` | read | everyone | `q`?: string, `tag`?: string, `limit`?: integer, `skip`?: integer | Search contacts by name, phone, email or company. |
| `contacts.update` | internal | admin, manager, member, owner | `id`: string, `name`?: string, `phone`?: string, `email`?: string, `company`?: string, `role`?: string, `source`?: string, `tags`?: array, `notes`?: string | Update a contact's details. |
| `contracts.remind` | external | everyone | `file_id`: string | Remind the client to sign a contract. |
| `contracts.status` | read | everyone | `project_id`: string | Contract signing status for a project's files. |
| `estimates.convert` | internal | admin, manager, member, owner | `id`: string | Mark an estimate accepted by hand: the project gets its budget, tasks and (from a quote) the payment schedule. |
| `estimates.create` | internal | admin, manager, member, owner | `project_id`?: string, `project_name`?: string, `name`?: string, `phases`?: array, `contingency_pct`?: number, `discount_paise`?: integer, `assumptions`?: string, `valid_days`?: integer | Start an internal estimate: phases and lines (service or role, quantity, unit), rates from the client's rate card. |
| `estimates.draft_from_text` | internal | admin, manager, member, owner | `project_id`?: string, `project_name`?: string, `text`: string | Draft an estimate from plain words or call notes, e.g. 'a 6-week pricing study, two days a week'. States its assumptions. |
| `estimates.finalise` | internal | admin, manager, member, owner | `id`: string | Make an estimate final (locked). Then turn it into a quote or proposal. |
| `estimates.get` | read | admin, manager, member, owner | `id`: string | An estimate with live totals: price, cost, margin, hours, effective rate. |
| `estimates.list` | read | admin, manager, member, owner | `project_id`?: string | Estimates, newest first. |
| `estimates.new_version` | internal | admin, manager, member, owner | `id`: string | Copy an estimate into a new draft version. |
| `estimates.to_proposal` | internal | admin, manager, member, owner | `id`: string, `template_id`?: string, `detail`?: string | Fill a proposal template's services and invoice from a final estimate. |
| `estimates.to_quote` | internal | admin, manager, member, owner | `id`: string, `detail`?: string, `valid_days`?: integer, `message`?: string | Turn a final estimate into a one-page quick quote (scope, price, valid-until date, Accept). Cost and margin are never shown. |
| `estimates.update` | internal | admin, manager, member, owner | `id`: string, `name`?: string, `phases`?: array, `contingency_pct`?: number, `discount_paise`?: integer, `assumptions`?: string, `valid_days`?: integer | Edit a draft estimate. A final estimate can't change; make a new version. |
| `expenses.delete` | destructive | admin, owner | `id`: string | Delete an expense. |
| `expenses.import_statement` | internal | admin, owner | `rows`: array, `default_category`?: string | Upload a bank statement (CSV/Excel rows); money going out becomes expenses you can tag. |
| `expenses.list` | read | everyone | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string | Expenses. |
| `expenses.save` | internal | admin, manager, owner | `id`?: string, `amount_paise`: integer, `date`: string, `category`?: string, `project_id`?: string, `note`?: string, `billable`?: boolean, `markup_pct`?: number, `receipt_upload_id`?: string | Add or edit an expense (optionally tagged to a project). |
| `exports.list` | read | admin, manager, member, owner | — | Your recent downloads (ZIPs of invoices). |
| `files.consultant_sign` | external | everyone | `id`: string, `block_id`: string, `name`: string | Sign a contract as the consultant (you can pre-sign before the client). |
| `files.create_from_template` | internal | admin, manager, member, owner | `project_id`: string, `template_id`?: string, `from_file_id`?: string, `title`?: string | Create a client file on a project from a template, a recent file, or blank. |
| `files.get` | read | everyone | `id`: string | A client file with versions, tracking events, signatures and invoices. |
| `files.list` | read | everyone | `project_id`?: string | Recent client files. |
| `files.mark_complete` | internal | everyone | `id`: string | Mark a client file complete by hand. |
| `files.reopen` | internal | everyone | `id`: string | Reopen a completed client file so the client can change their answers. |
| `files.save_as_template` | internal | admin, manager, member, owner | `id`: string, `name`: string | Save a client file as a reusable template. |
| `files.send` | external | everyone | `id`: string, `channel`?: string, `message`?: string, `subject`?: string, `schedule_at`?: string, `notify_client`?: boolean | Send (or resend) a client file by email/WhatsApp. Each send is a new version. |
| `files.status` | read | everyone | `id`: string | Tracking for a client file: sent, viewed, pages reached, completed. |
| `files.update` | internal | everyone | `id`: string, `title`?: string, `pages`?: array | Save the working copy of a client file (autosave). |
| `files.update_block` | internal | everyone | `id`: string, `block_id`: string, `props`: object | Change one block in a client file's working copy. |
| `forecast.get` | read | everyone | `months`?: integer | Money expected over the next 6 or 12 months: confirmed (agreed invoices, retainers) and pipeline (weighted estimate), kept apart. |
| `home.get` | read | everyone | — | Everything the Home screen shows. |
| `inbox.list` | read | everyone | `filter`?: string, `channel`?: string | All conversations, unread first. |
| `invoices.add_expenses` | internal | admin, manager, member, owner | `project_id`: string, `invoice_id`?: string, `expense_ids`?: array | Put a project's billable expenses (with markup and receipts) on a draft invoice. |
| `invoices.add_unbilled_time` | internal | admin, manager, member, owner | `project_id`: string, `invoice_id`?: string, `date_from`?: string, `date_to`?: string, `rounding`?: integer, `group_by`?: string, `timesheet`?: string, `columns`?: array, `entry_ids`?: array | Put a project's unbilled time on a draft invoice: all of it or a date range, with rounding, grouping and an optional timesheet. |
| `invoices.ai_edit` | internal | everyone | `id`: string, `instruction`: string | Edit a draft invoice by instruction, e.g. 'add a 10% discount'. Can be undone. |
| `invoices.bulk_download` | internal | admin, manager, member, owner | `ids`?: array, `contact_id`?: string, `project_id`?: string, `status`?: string, `date_from`?: string, `date_to`?: string, `fy`?: string | Download many invoices as one ZIP of PDFs. It's built in the background and you get a link. |
| `invoices.bulk_remind` | external | admin, manager, member, owner | `ids`?: array, `contact_id`?: string, `project_id`?: string, `status`?: string, `date_from`?: string, `date_to`?: string, `fy`?: string | Send payment reminders for many invoices at once. Invoices with nothing due are skipped. |
| `invoices.create` | internal | admin, manager, member, owner | `project_id`: string, `title`?: string, `lines`?: array, `schedule`?: array, `template_id`?: string | Create a draft invoice on a project. |
| `invoices.credit_note` | money | admin, owner | `id`: string, `amount_paise`: integer, `reason`: string, `time_to`?: string | Issue a credit note against an invoice. |
| `invoices.export` | read | admin, manager, member, owner | `ids`?: array, `contact_id`?: string, `project_id`?: string, `status`?: string, `date_from`?: string, `date_to`?: string, `fy`?: string | Invoices as a CSV for your CA. |
| `invoices.get` | read | everyone | `id`: string | An invoice with its schedule, UPI details, claims and ledger. |
| `invoices.list` | read | everyone | `ids`?: array, `contact_id`?: string, `project_id`?: string, `status`?: string, `date_from`?: string, `date_to`?: string, `fy`?: string | Invoices, newest first. Filter by client, project, status, dates or financial year. |
| `invoices.milestone_reached` | internal | everyone | `id`: string, `item_id`: string | Mark a milestone reached so its payment becomes due. |
| `invoices.remind` | external | everyone | `id`: string, `item_id`?: string, `channel`?: string | Send a payment reminder for an invoice. |
| `invoices.send` | money | everyone | `id`: string, `channel`?: string | Send an invoice to the client with the pay link. |
| `invoices.undo_ai_edit` | internal | everyone | `id`: string | Undo the last AI edit on an invoice. |
| `invoices.update` | internal | everyone | `id`: string, `title`?: string, `lines`?: array, `schedule`?: array, `discount`?: object, `service_charge`?: object, `gst`?: object, `client_choice`?: object, `tds_expected`?: boolean, `notes`?: string, `terms`?: string | Edit a draft or unpaid invoice. Paid lines are locked. |
| `invoices.void` | destructive | admin, owner | `id`: string, `time_to`?: string | Cancel an unpaid invoice. Its time goes back to unbilled (or is marked non-billable). |
| `lead_forms.analytics` | read | everyone | `id`?: string, `days`?: integer | Form views, starts, submits and conversion, by source. |
| `lead_forms.delete` | destructive | admin, owner | `id`: string | Delete a lead form. |
| `lead_forms.get` | read | everyone | `id`: string | One lead form. |
| `lead_forms.list` | read | everyone | — | Lead forms with their links. |
| `lead_forms.save` | internal | admin, owner | `id`?: string, `name`: string, `kind`?: string, `live`?: boolean, `project_type`?: string, `source`?: string, `blocks`?: array, `thank_you`?: object, `price_paise`?: integer, `promo_enabled`?: boolean, `otp_required`?: boolean, `automation_ids`?: array | Create or update a lead form. |
| `leads.create` | internal | admin, manager, member, owner | `name`?: string, `phone`?: string, `email`?: string, `company`?: string, `message`?: string, `source`?: string, `project_type`?: string, `project_name`?: string, `utm`?: object, `answers`?: object, `form_id`?: string, `via`?: string | Create a lead: contact plus a new project in the first stage. |
| `leads.decide_suggested` | internal | admin, manager, member, owner | `id`: string, `accept`: boolean | Accept or dismiss a suggested lead. |
| `leads.from_screenshot` | internal | admin, manager, member, owner | `image`: string, `note`?: string | Upload a screenshot of a WhatsApp, LinkedIn or Instagram message; the Lead agent creates the lead. |
| `leads.suggested` | read | everyone | — | Leads the inbox lead finder or screenshot reader found, waiting to be accepted. |
| `mcp.connected_apps` | read | everyone | — | Assistants that signed in to this practice (OAuth), with what they may do. |
| `mcp.create_token` | internal | admin, owner | `name`?: string, `scope`?: string | Create a connector token for an outside AI assistant. |
| `mcp.disconnect_app` | destructive | everyone | `client_id`: string, `user_id`?: string | Sign an assistant out of this practice. |
| `mcp.list_tokens` | read | admin, owner | — | List connector tokens. |
| `mcp.revoke_token` | destructive | admin, owner | `id`: string | Revoke a connector token. |
| `meetings.add_transcript` | internal | everyone | `project_id`: string, `text`?: string, `session_id`?: string | Paste notes or a transcript from a call; the Meeting agent writes it up and creates tasks. |
| `messages.draft` | internal | everyone | `project_id`: string, `direction`?: string, `tone`?: string, `length`?: string, `channel`?: string | Write a message draft with AI (nothing is sent). |
| `messages.save_draft` | internal | everyone | `project_id`: string, `subject`?: string, `body`?: string, `channel`?: string | Save an email draft on the project for later editing. |
| `messages.send` | external | everyone | `project_id`: string, `channel`?: string, `subject`?: string, `body`?: string, `template_id`?: string, `wa_template`?: string, `wa_params`?: array, `contact_id`?: string, `schedule_at`?: string | Send an email or WhatsApp message to the project's client. |
| `money.view` | read | everyone | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string | Cashflow by month (received minus expenses) and profit per project. |
| `notes.add` | internal | everyone | `project_id`: string, `text`: string, `shared`?: boolean | Add a note to a project (shared notes show in the client portal). |
| `notifications.list` | read | everyone | — | List my notifications. |
| `notifications.read_all` | internal | everyone | — | Mark my notifications read. |
| `onboarding.finish` | internal | admin, owner | `answers`: object | Build the account from the interview answers. |
| `onboarding.preview` | read | everyone | `answers`: object | Live preview of what the interview will build. |
| `onboarding.questions` | read | everyone | — | The Setup agent's interview questions. |
| `onboarding.test_proposal` | external | everyone | — | Send yourself a test proposal to see the client side. |
| `payments.cancel_late_fee` | money | everyone | `invoice_id`: string, `item_id`: string | Cancel a late fee on a payment. |
| `payments.confirm` | money | everyone | `invoice_id`: string, `item_id`: string, `amount_received_paise`?: integer, `tds_paise`?: integer, `method`?: string, `reference`?: string | Mark a payment as received (the only way an invoice becomes paid). |
| `payments.list_due` | read | everyone | `project_id`?: string | Every payment item grouped: paid, processing, upcoming, overdue. |
| `payments.refund` | money | admin, owner | `invoice_id`: string, `amount_paise`: integer, `note`?: string | Record a refund you have sent back to the client. |
| `payments.reject_claim` | money | everyone | `claim_id`: string, `reason`?: string | Reject a client's 'I've paid' claim; the payment returns to due and the client is told. |
| `payments.request` | money | everyone | `project_id`: string, `amount_paise`: integer, `label`?: string, `due_date`?: string, `channel`?: string | Send a one-off payment request (a single-line invoice) with a pay link. |
| `projects.archive` | destructive | everyone | `id`: string, `reason`?: string | Archive a project (stops its automations). Lost leads need a reason. |
| `projects.bulk` | internal | everyone | `ids`: array, `op`: string, `stage_id`?: string, `tag`?: string, `owner_id`?: string, `reason`?: string | Bulk change: move stage, tag, assign or archive several projects. |
| `projects.create` | internal | admin, manager, member, owner | `name`: string, `contact_ids`?: array, `contact`?: object, `type`?: string, `stage_id`?: string, `value_paise`?: integer, `start_date`?: string, `end_date`?: string, `source`?: string, `tags`?: array, `owner_id`?: string | Create a project (starts as an opportunity). |
| `projects.delete` | destructive | admin, owner | `id`: string | Delete a project (can be restored for 30 days). |
| `projects.get` | read | everyone | `id`: string | Everything about one project: details, contacts, activity, files, tasks, payments, sessions. |
| `projects.mark_booked` | internal | everyone | `id`: string, `booked`?: boolean | Mark a project booked (or not) by hand. |
| `projects.move_stage` | internal | everyone | `id`: string, `stage_id`: string | Move a project to another pipeline stage. |
| `projects.restore` | internal | admin, owner | `id`: string | Restore a deleted project (within 30 days). |
| `projects.search` | read | everyone | `q`?: string, `stage_id`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string, `archived`?: boolean, `booked`?: boolean, `waiting_on_client`?: boolean, `created_from`?: string, `created_to`?: string, `sort`?: string, `limit`?: integer, `skip`?: integer | Search projects with filters. Returns items and stage counts. |
| `projects.set_revenue_spread` | internal | admin, manager, member, owner | `id`: string, `expected_close`?: string, `value_paise`?: integer, `spread`?: array | Set an opportunity's value, expected close date and how its revenue spreads across months. |
| `projects.unarchive` | internal | everyone | `id`: string | Bring an archived project back. |
| `projects.update` | internal | everyone | `id`: string, `name`?: string, `type`?: string, `value_paise`?: integer, `start_date`?: string, `end_date`?: string, `source`?: string, `owner_id`?: string, `team_ids`?: array, `contact_ids`?: array, `custom`?: object, `shared_details`?: object, `portal_link_on`?: boolean | Update a project's details. |
| `promo.list` | read | everyone | — | Promo codes. |
| `promo.save` | internal | admin, owner | `code`: string, `kind`?: string, `value`: integer, `active`?: boolean | Create or update a promo code. |
| `rate_cards.assign` | internal | admin, manager, owner | `rate_card_id`?: string, `project_id`?: string, `contact_id`?: string, `apply_to_unbilled`?: boolean | Give a project or a client its own rate card. Choose whether unbilled time is re-priced or only new time. |
| `rate_cards.delete` | destructive | admin, owner | `id`: string | Delete a rate card (not the default one). |
| `rate_cards.list` | read | admin, manager, member, owner | — | Rate cards with their lines, current rates and upcoming changes. |
| `rate_cards.save` | internal | admin, owner | `id`?: string, `name`: string, `currency`?: string, `lines`?: array | Create or edit a rate card and its lines. |
| `rate_changes.cancel` | internal | admin, owner | `id`: string | Cancel a scheduled rate change that hasn't started. |
| `rate_changes.schedule` | internal | admin, owner | `effective_from`: string, `line_id`?: string, `rate_paise`?: integer, `pct`?: number, `rate_card_id`?: string | Set a new rate from a date, e.g. 'day rate ₹40,000 from 1 April', or raise every rate on a card by a percentage. Applies to work from that date; past entries never change. |
| `rates.resolve` | read | admin, manager, member, owner | `project_id`?: string, `project_name`?: string, `service_id`?: string, `user_id`?: string, `date`?: string | The rate that applies for a service or person on a project and date, and which card it came from. |
| `rates.settings` | read | admin, manager, member, owner | — | Rate settings: hours in a day, target margin, billing roles. |
| `rates.update_settings` | internal | admin, owner | `day_hours`?: integer, `target_margin_pct`?: number, `managers_see_costs`?: boolean, `billing_roles`?: array | Change hours in a day, target margin or billing roles. |
| `recurring.cancel` | money | everyone | `id`: string | Stop a recurring invoice (only the consultant can). |
| `recurring.create` | money | everyone | `project_id`: string, `lines`: array, `day_of_month`?: integer, `start_month`?: string, `end_month`?: string, `channel`?: string | Set up a monthly invoice for a retainer. |
| `recurring.list` | read | everyone | — | Recurring invoices. |
| `reports.export_csv` | read | admin, manager, owner | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string, `what`?: string | Download a CSV. |
| `reports.payments` | read | everyone | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string | Monthly sales, by project type and team member, and the forecast from payment schedules. |
| `reports.pipeline` | read | everyone | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string | Lead sources, conversion by stage, average value, time to book, lost reasons. |
| `reports.profitability` | read | everyone | `group`?: string, `date_from`?: string, `date_to`?: string | What each project, client or service really earned: billed, received, hours, effective hourly rate, cost and margin. |
| `reports.summary` | read | everyone | `date_from`?: string, `date_to`?: string, `type`?: string, `tag`?: string, `source`?: string, `owner_id`?: string | Money received this month and year, outstanding, overdue, bookings, revenue goal. |
| `reports.utilisation` | read | admin, manager, owner | `period`?: string, `count`?: integer | Billable hours ÷ available hours, per person, by week or month; non-billable time by reason. |
| `retainers.absorb_overage` | internal | admin, manager, owner | `period_id`: string | Don't bill the extra time from a retainer period; it shows as non-billable in reports. |
| `retainers.bill_overage` | money | admin, manager, owner | `period_id`: string | Bill the extra time from a closed retainer period (when the rule is 'ask first'). |
| `retainers.close_period` | money | admin, owner | `id`: string | Close any period that has ended now, instead of waiting for tonight's job. |
| `retainers.create` | money | admin, manager, owner | `id`?: string, `name`?: string, `project_id`?: string, `project_ids`?: array, `contact_id`?: string, `kind`?: string, `period`?: string, `start_date`?: string, `fee_paise`?: integer, `included_hours`?: number, `included_days`?: number, `cap_paise`?: integer, `overage_rate_paise`?: integer, `billing`?: string, `rollover`?: object, `overage`?: object, `alert_pct`?: integer, `statement_entries_visible`?: boolean, `auto_send`?: boolean, `task_template_id`?: string, `end_date`?: string, `notice_days`?: integer, `renewal_days`?: integer, `adopt_recurring_id`?: string | Set up a retainer: hours bank, fixed scope or pay-as-used with a cap; period; billing; rollover and overage rules. |
| `retainers.end` | money | admin, manager, owner | `id`: string, `end_date`?: string | End a retainer on a date. If that's mid-period, the period closes on that date and unused hours lapse. |
| `retainers.get` | read | everyone | `id`: string | A retainer: plan, this period's meter, period history, entries and invoices. |
| `retainers.list` | read | everyone | — | All retainers: client, plan, used this period, next invoice, renewal. |
| `retainers.pause` | money | admin, manager, owner | `id`: string | Pause a retainer: this period completes, no new period opens and no new invoice is raised. |
| `retainers.resume` | money | admin, manager, owner | `id`: string | Resume a paused retainer. A new period starts today if none is open. |
| `retainers.statement` | read | everyone | `id`?: string, `project_name`?: string, `period_id`?: string | This period's statement: included, carried in, used, left (by retainer id or client name). |
| `retainers.update` | money | admin, manager, owner | `id`?: string, `name`?: string, `project_id`?: string, `project_ids`?: array, `contact_id`?: string, `kind`?: string, `period`?: string, `start_date`?: string, `fee_paise`?: integer, `included_hours`?: number, `included_days`?: number, `cap_paise`?: integer, `overage_rate_paise`?: integer, `billing`?: string, `rollover`?: object, `overage`?: object, `alert_pct`?: integer, `statement_entries_visible`?: boolean, `auto_send`?: boolean, `task_template_id`?: string, `end_date`?: string, `notice_days`?: integer, `renewal_days`?: integer, `adopt_recurring_id`?: string | Change a retainer. Plan changes (fee, hours, rules, billing) start from the next period; alerts and settings change now. |
| `search.all` | read | everyone | `q`: string | Search contacts and projects at once. |
| `services.delete` | destructive | admin, owner | `id`: string | Remove a service. If it's in use (time, estimates, rate cards), it's archived instead. |
| `services.list` | read | admin, manager, member, owner | — | The service library: name, unit and default rate. |
| `services.restore` | internal | admin, owner | `id`: string | Bring an archived service back. |
| `services.save` | internal | admin, owner | `id`?: string, `name`: string, `description`?: string, `unit`?: string, `rate_paise`?: integer | Add or edit a service in the library. |
| `session_types.list` | read | everyone | — | Session types clients can book. |
| `session_types.overview` | read | everyone | — | All session types' availability on one weekly grid. |
| `session_types.save` | internal | admin, manager, owner | `id`?: string, `name`: string, `format`?: string, `video`?: string, `duration`?: integer, `buffer_before`?: integer, `buffer_after`?: integer, `increment`?: integer, `availability`?: object, `date_from`?: string, `date_to`?: string, `min_notice_hours`?: integer, `max_days_ahead`?: integer, `cancel_cutoff_hours`?: integer, `max_attendees`?: integer, `host_ids`?: array, `color`?: string, `questions`?: array, `price_paise`?: integer, `notetaker`?: boolean, `hold_hours`?: integer, `reminders`?: array, `active`?: boolean | Create or update a session type. |
| `sessions.book` | external | admin, manager, member, owner | `session_type_id`: string, `start`: string, `contact_id`?: string, `project_id`?: string | Book a session for a client (sends the confirmation). |
| `sessions.cancel` | external | everyone | `id`: string | Cancel a session and tell the client. |
| `sessions.mark` | internal | everyone | `id`: string, `status`: string | Mark a session completed or a no-show. |
| `sessions.reschedule` | external | everyone | `id`: string, `start`: string | Move a session to a new time. |
| `stages.list` | read | everyone | — | List pipeline stages in order. |
| `stages.save` | internal | admin, owner | `stages`: array, `stage_rules`?: array | Rename, add or reorder pipeline stages (up to 20). |
| `stages.set_probability` | internal | admin, owner | `stage_id`: string, `pct`: integer | Set an opportunity stage's win chance (used by the forecast). |
| `stages.set_task_template` | internal | admin, owner | `stage_id`: string, `template_id`?: string | Add a checklist to every project when it enters a stage. |
| `tags.add` | internal | everyone | `project_id`: string, `tag`: string | Add a tag to a project. |
| `tags.remove` | internal | everyone | `project_id`: string, `tag`: string | Remove a tag from a project. |
| `task_templates.apply` | internal | admin, manager, member, owner | `template_id`: string, `project_id`: string, `start_date`?: string | Add a saved checklist to a project. |
| `task_templates.create` | internal | admin, manager, owner | `id`?: string, `name`: string, `items`: array | Save a checklist of tasks (titles, estimates, due days, who). |
| `task_templates.delete` | destructive | admin, manager, owner | `id`: string | Delete a task template. |
| `task_templates.list` | read | admin, manager, member, owner | — | Saved checklists that can be applied to a project, a stage or each retainer period. |
| `tasks.complete` | internal | everyone | `id`: string | Mark a task done. |
| `tasks.create` | internal | everyone | `title`: string, `project_id`?: string, `assignee_id`?: string, `due_at`?: string, `estimate_hours`?: number, `service_id`?: string | Create a task (clients never see tasks). |
| `tasks.list` | read | everyone | `scope`?: string, `project_id`?: string, `mine`?: boolean, `audience`?: string | List tasks: today, upcoming, overdue. |
| `tasks.set_estimate` | internal | admin, manager, member, owner | `id`: string, `minutes`?: integer, `hours`?: number | Set a task's estimate in hours. The task then shows estimate against time logged. |
| `tasks.set_recurrence` | internal | admin, manager, member, owner | `id`: string, `every`?: string, `day`?: integer | Repeat a task weekly, monthly or quarterly on a chosen day. |
| `tax.pack` | read | admin, owner | `what`: string, `fy`?: string | Downloads for your CA: invoice register, TDS by client, GST by month. |
| `team.add` | internal | admin, owner | `phone`: string, `name`?: string, `role`?: string, `project_ids`?: array | Add a team member by mobile number (they count as invited). |
| `team.list` | read | everyone | — | List the team members and their roles. |
| `team.rates` | read | admin, manager, owner | — | Each team member's billing role, cost per hour and available hours. |
| `team.remove` | destructive | admin, owner | `membership_id`: string | Remove a team member. |
| `team.set_rates` | internal | admin, owner | `user_id`: string, `cost_rate_paise`?: integer, `available_hours_week`?: number, `billing_role`?: string, `effective_from`?: string | A team member's billing role, cost per hour (what an hour costs the practice) and available hours a week. |
| `team.update_role` | internal | admin, owner | `membership_id`: string, `role`: string, `project_ids`?: array | Change a team member's role. |
| `templates.delete` | destructive | admin, manager, member, owner | `id`: string | Delete a template. |
| `templates.gallery` | read | everyone | — | The starter gallery of consulting templates. |
| `templates.get` | read | everyone | `id`: string | One template with its content. |
| `templates.install` | internal | admin, manager, member, owner | `key`: string | Copy a gallery template into my templates. |
| `templates.list` | read | everyone | `kind`?: string | My templates (client files, contracts, emails, questionnaires, invoices). |
| `templates.save` | internal | admin, manager, member, owner | `id`?: string, `kind`: string, `name`: string, `body`: object | Create or update a template. |
| `threads.get` | read | everyone | `project_id`: string | All messages on a project, oldest first. |
| `time.delete` | destructive | everyone | `id`: string | Delete a time entry. Billed or locked time can't be deleted. |
| `time.list` | read | everyone | `project_id`?: string, `user_id`?: string, `date_from`?: string, `date_to`?: string, `status`?: string, `limit`?: integer | Time entries, filtered by project, person, dates or billing status. |
| `time.lock_period` | internal | admin, owner | `before`?: string | Lock all time before a date so nothing in that period can change. |
| `time.log` | internal | everyone | `project_id`?: string, `project_name`?: string, `minutes`?: integer, `hours`?: number, `date`?: string, `note`?: string, `task_id`?: string, `service_id`?: string, `user_id`?: string, `billable`?: boolean, `reason`?: string | Log time on a project (by id or name), e.g. '2 hours on Acme strategy today'. Billable unless said otherwise. |
| `time.set_billing_status` | internal | everyone | `ids`: array, `status`: string, `reason`?: string | Mark time billed by hand (invoiced outside the app), back to unbilled, or non-billable. |
| `time.set_cell` | internal | everyone | `project_id`: string, `task_id`?: string, `date`: string, `minutes`: integer | Type hours straight into the weekly grid. |
| `time.timer` | read | everyone | — | Your running timer, if any. |
| `time.timer_start` | internal | everyone | `project_id`: string, `task_id`?: string, `note`?: string | Start a timer on a project. A running timer is stopped and logged first. |
| `time.timer_stop` | internal | everyone | — | Stop your running timer and log the time. |
| `time.unbilled` | read | everyone | `project_id`?: string | How much billable time hasn't been invoiced yet, by project, and the oldest entry. |
| `time.update` | internal | everyone | `id`: string, `minutes`?: integer, `date`?: string, `note`?: string, `task_id`?: string, `service_id`?: string, `billable`?: boolean, `reason`?: string | Edit a time entry. Billed or locked time can't be edited. |
| `time.week` | read | everyone | `week_start`?: string, `user_id`?: string | One person's week as a grid: projects and tasks down, days across. |
| `uploads.list` | read | everyone | `project_id`: string | Files on a project: uploads, signed contracts, client uploads. |
| `views.delete` | internal | everyone | `id`: string | Delete a saved view. |
| `views.list` | read | everyone | — | List saved pipeline views. |
| `views.save` | internal | everyone | `id`?: string, `name`: string, `filters`?: object, `columns`?: array, `sort`?: object, `mode`?: string | Save a pipeline view (filters, columns, order, sort). |
| `workspace.get` | read | everyone | — | Get the practice profile, theme, invoice and settings. |
| `workspace.update` | internal | admin, owner | `name`?: string, `profile`?: object, `theme`?: object, `invoice`?: object, `settings`?: object | Update practice profile, theme, invoice details or settings. |

## Other routes

| Route | What it does |
|---|---|
| `POST /api/auth/otp/request` `{phone}` | Send a login code (WhatsApp, SMS fallback). Not invited → 403 "This product is by invitation right now." |
| `POST /api/auth/otp/verify` `{phone, code}` | Log in; sets the access + refresh cookies. |
| `GET /api/auth/me` · `POST /api/auth/switch` · `POST /api/auth/logout` · `POST /api/auth/staff` | Session, practice switch, logout, staff login. |
| `POST /api/upload` `{data, name, kind, project_id?}` | Upload (data URL, max 8 MB). `kind: logo` sets the practice logo. |
| `GET /api/preview/f/<file_id>` | The working copy of a client file, rendered exactly as the client sees it. |
| `GET /api/connect/<gmail\|outlook\|zoom>/start` · `/callback` | Connect an account (OAuth). |
| `GET /api/public/brand/<slug>` | Practice brand for client pages. |
| `GET/POST /api/public/<slug>/form/<form>` (`/event`, `/submit`) | Lead form. |
| `GET/POST /api/public/<slug>/book/<type>` (`/slots`) | Booking page. |
| `GET /api/public/f/<token>` + `POST .../page, answers, select, plan, promo, otp, sign, book, claim, complete` | Client file viewer. |
| `GET /api/public/i/<token>` · `POST .../claim` · `GET .../receipt/<item>.pdf` | Invoice page, "I've paid", receipt. |
| `GET /api/public/d/<token>` | Download (e.g. signed contract PDF). |
| `/api/public/<slug>/portal/...` (`code`, `login`, `me`, `project/<id>`, `message`, `upload`, `session/<id>/reschedule`, `logout`) | Client portal. |
| `POST /api/hooks/email-inbound`, `/whatsapp-inbound`, `/email-events`, `/meetbot` | Provider webhooks. |
| `/api/admin/*` | Admin panel (401 logged out, 403 for non-admins). |
| `POST /mcp` | MCP server (JSON-RPC: initialize, tools/list, tools/call). Bearer connector token. |
| `POST /api/qa/*` | QA mode only: persona login, outbox, clock, run jobs. |
