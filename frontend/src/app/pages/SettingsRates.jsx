// Settings for the add-ons: services and rates, checklists, win chances, connected assistants.
import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { act, useAct, useRefresh } from "../../lib/api";
import { date, dt, inr, todayISO } from "../../lib/format";
import { Button, Card, Chip, Field, Input, Kicker, Loadable, MoneyInput, Select, Sheet, Toggle, cx, toast } from "../components/ui";

const UNITS = [["hour", "Per hour"], ["day", "Per day"], ["flat", "Flat fee"], ["session", "Per session"], ["week", "Per week"], ["month", "Per month"], ["item", "Per item"]];

export function RatesSection({ w }) {
  const admin = ["owner", "admin"].includes(w.role);
  return (
    <>
      <Services admin={admin} />
      <Cards admin={admin} />
      <TeamRates admin={admin} />
      <RateSettings admin={admin} owner={w.role === "owner"} />
    </>
  );
}

function Services({ admin }) {
  const q = useAct("services.list");
  const [f, setF] = useState({ name: "", unit: "hour", rate_paise: 0 });
  return (
    <Card className="space-y-3">
      <Kicker>Service library</Kicker>
      <p className="text-[14px] text-ivory-70">Set rates once. Estimates, time and invoices all use them.</p>
      <Loadable q={q}>{(rows) => rows.map((s) => (
        <div key={s.id} className={cx("flex flex-wrap items-center gap-2 border-t border-hairline pt-2 text-[14px]", s.archived && "opacity-50")}>
          <span className="min-w-0 flex-1 font-bold">{s.name}{s.archived && " (archived)"}</span><span className="text-ivory-70">{s.unit_label}</span>
          <span className="tnum w-28 text-right text-gold">{s.rate_paise === null ? "—" : inr(s.rate_paise)}</span>
          {admin && !s.archived && <button aria-label="Remove" onClick={async () => { const r = await act("services.delete", { id: s.id }); toast(r.message || "Removed"); q.refetch(); }}><Trash2 size={15} className="text-ivory-35" /></button>}
        </div>))}</Loadable>
      {admin && <div className="grid gap-2 md:grid-cols-[1fr_150px_150px_auto] md:items-end">
        <Field label="New service"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Strategy session" /></Field>
        <Field label="Unit"><Select value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} options={UNITS.map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label="Rate"><MoneyInput paise={f.rate_paise} onChange={(v) => setF({ ...f, rate_paise: v || 0 })} /></Field>
        <Button onClick={async () => { try { await act("services.save", f); setF({ name: "", unit: "hour", rate_paise: 0 }); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Add</Button>
      </div>}
    </Card>
  );
}

function Cards({ admin }) {
  const q = useAct("rate_cards.list");
  const services = useAct("services.list");
  const team = useAct("team.list");
  const settings = useAct("rates.settings");
  const [edit, setEdit] = useState(null);
  const [change, setChange] = useState(null);
  return (
    <Card className="space-y-3">
      <div className="flex items-center gap-2"><Kicker>Rate cards</Kicker>
        {admin && <Button size="sm" className="ml-auto" icon={Plus} onClick={() => setEdit({ name: "Client rates", currency: "INR", lines: [] })}>New card</Button>}</div>
      <p className="text-[14px] text-ivory-70">The default card applies to everyone. Give a client or a project its own card for negotiated fees: project beats client beats default.</p>
      <Loadable q={q}>{(cards) => cards.map((c) => (
        <div key={c.id} className="rounded-card border border-hairline p-3">
          <div className="flex flex-wrap items-center gap-2"><b>{c.name}</b>{c.is_default && <Chip tone="gold">Default</Chip>}{c.currency !== "INR" && <Chip>{c.currency}</Chip>}
            {admin && <Button size="sm" variant="quiet" className="ml-auto" onClick={() => setEdit({ ...c, lines: c.lines.map((l) => ({ ...l, rate_paise: l.base_rate_paise })) })}>Edit</Button>}</div>
          {(c.projects.length > 0 || c.clients.length > 0) && <div className="mt-1 text-[13px] text-ivory-70">Used by {[...c.clients.map((x) => x.name), ...c.projects.map((x) => x.name)].join(", ")}</div>}
          <div className="mt-2">{c.lines.map((l) => (
            <div key={l.id} className="flex flex-wrap items-center gap-2 border-t border-hairline py-2 text-[14px] first:border-0">
              <span className="min-w-0 flex-1">{l.label} <span className="text-[12px] text-ivory-35">{l.target === "role" ? "role" : l.target === "person" ? "person" : ""}</span></span>
              <span className="text-ivory-70">{l.unit_label}</span><span className="tnum w-24 text-right font-bold text-gold">{l.rate_paise === null ? "—" : inr(l.rate_paise)}</span>
              {l.upcoming.map((u) => <span key={u.id} className="text-[12px] text-ivory-70">→ {inr(u.rate_paise)} from {date(u.effective_from)}</span>)}
              {admin && <button className="text-[13px] font-bold text-gold" onClick={() => setChange(l)}>Change from a date</button>}
            </div>))}</div>
        </div>))}</Loadable>
      {edit && <CardSheet card={edit} services={services.data || []} team={team.data || []} roles={settings.data?.billing_roles || []} onClose={() => { setEdit(null); q.refetch(); }} />}
      {change && <ChangeSheet line={change} onClose={() => { setChange(null); q.refetch(); }} />}
    </Card>
  );
}

function CardSheet({ card, services, team, roles, onClose }) {
  const [c, setC] = useState(card);
  const set = (i, k, v) => setC({ ...c, lines: c.lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)) });
  return (
    <Sheet open onClose={onClose} title={card.id ? "Edit rate card" : "New rate card"} wide>
      <div className="space-y-3">
        <div className="grid grid-cols-[1fr_110px] gap-2"><Field label="Name"><Input value={c.name} disabled={c.is_default} onChange={(e) => setC({ ...c, name: e.target.value })} /></Field>
          <Field label="Currency"><Input value={c.currency} onChange={(e) => setC({ ...c, currency: e.target.value.toUpperCase() })} /></Field></div>
        {c.lines.map((l, i) => (
          <div key={l.id || i} className="grid gap-2 border-t border-hairline pt-2 md:grid-cols-[110px_1fr_130px_140px_28px]">
            <Select value={l.target} onChange={(e) => set(i, "target", e.target.value)} options={[{ value: "service", label: "Service" }, { value: "role", label: "Role" }, { value: "person", label: "Person" }]} />
            {l.target === "service" ? <Select value={l.service_id || ""} onChange={(e) => set(i, "service_id", e.target.value)} options={[{ value: "", label: "Choose" }, ...services.map((s) => ({ value: s.id, label: s.name }))]} />
              : l.target === "role" ? <Select value={l.role || ""} onChange={(e) => set(i, "role", e.target.value)} options={[{ value: "", label: "Choose" }, ...roles.map((r) => ({ value: r, label: r }))]} />
                : <Select value={l.user_id || ""} onChange={(e) => set(i, "user_id", e.target.value)} options={[{ value: "", label: "Choose" }, ...team.filter((t) => t.user_id && !String(t.user_id).startsWith("pending:")).map((t) => ({ value: t.user_id, label: t.name || t.phone }))]} />}
            <Select value={l.unit} onChange={(e) => set(i, "unit", e.target.value)} options={UNITS.map(([v, lb]) => ({ value: v, label: lb }))} />
            <MoneyInput paise={l.rate_paise} onChange={(v) => set(i, "rate_paise", v || 0)} />
            <button aria-label="Remove line" onClick={() => setC({ ...c, lines: c.lines.filter((_, j) => j !== i) })}><Trash2 size={15} className="text-ivory-35" /></button>
          </div>))}
        <Button size="sm" icon={Plus} onClick={() => setC({ ...c, lines: [...c.lines, { target: "service", unit: "hour", rate_paise: 0 }] })}>Add a rate</Button>
        <Button variant="primary" className="w-full" onClick={async () => { try { await act("rate_cards.save", { id: c.id, name: c.name, currency: c.currency, lines: c.lines }); toast("Rate card saved"); onClose(); } catch (e) { toast(e.message, "error"); } }}>Save</Button>
        {!c.is_default && c.id && <AssignCard card={c} />}
      </div>
    </Sheet>
  );
}

function AssignCard({ card }) {
  const projects = useAct("projects.search", { limit: 300 });
  const contacts = useAct("contacts.search", {});
  const [t, setT] = useState({ kind: "contact", id: "", apply: false });
  const opts = t.kind === "project" ? (projects.data?.items || []).map((p) => ({ value: p.id, label: p.name }))
    : (contacts.data?.items || contacts.data || []).map((c) => ({ value: c.id, label: c.company ? `${c.name} · ${c.company}` : c.name }));
  return (
    <div className="space-y-2 rounded-card border border-hairline p-3">
      <b className="text-[14px]">Use this card for</b>
      <div className="grid grid-cols-[120px_1fr] gap-2"><Select value={t.kind} onChange={(e) => setT({ ...t, kind: e.target.value, id: "" })} options={[{ value: "contact", label: "A client" }, { value: "project", label: "A project" }]} />
        <Select value={t.id} onChange={(e) => setT({ ...t, id: e.target.value })} options={[{ value: "", label: "Choose" }, ...opts]} /></div>
      <Toggle on={t.apply} onChange={(v) => setT({ ...t, apply: v })} label="Re-price their unbilled time too (otherwise only new time)" />
      <Button size="sm" disabled={!t.id} onClick={async () => { try { const r = await act("rate_cards.assign", { rate_card_id: card.id, [t.kind === "project" ? "project_id" : "contact_id"]: t.id, apply_to_unbilled: t.apply }); toast(`Done${r.repriced_entries ? ` · ${r.repriced_entries} entries re-priced` : ""}`); } catch (e) { toast(e.message, "error"); } }}>Apply</Button>
    </div>
  );
}

function ChangeSheet({ line, onClose }) {
  const [f, setF] = useState({ rate_paise: line.rate_paise, effective_from: "" });
  return (
    <Sheet open onClose={onClose} title={`New rate for ${line.label}`}>
      <div className="space-y-3">
        <p className="text-[14px] text-ivory-70">Applies to work from that date. Time already logged keeps its rate.</p>
        <Field label="New rate"><MoneyInput paise={f.rate_paise} onChange={(v) => setF({ ...f, rate_paise: v || 0 })} /></Field>
        <Field label="From"><Input type="date" min={todayISO()} value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} /></Field>
        <Button variant="primary" className="w-full" disabled={!f.effective_from} onClick={async () => { try { const r = await act("rate_changes.schedule", { line_id: line.id, ...f }); toast(r.summary); onClose(); } catch (e) { toast(e.message, "error"); } }}>Schedule</Button>
      </div>
    </Sheet>
  );
}

function TeamRates({ admin }) {
  const q = useAct("team.rates", {}, { enabled: admin });
  const s = useAct("rates.settings");
  if (!admin) return null;
  return (
    <Card className="space-y-2">
      <Kicker>Team: roles, cost and hours</Kicker>
      <p className="text-[14px] text-ivory-70">Cost per hour is what an hour of that person costs the practice. Only Owners and Admins see it. Leave it empty if you work alone.</p>
      <Loadable q={q}>{(rows) => rows.map((r) => <TeamRow key={r.user_id} r={r} roles={s.data?.billing_roles || []} onSaved={() => q.refetch()} />)}</Loadable>
    </Card>
  );
}

function TeamRow({ r, roles, onSaved }) {
  const [f, setF] = useState({ billing_role: r.billing_role || "", cost_rate_paise: r.cost_rate_paise || 0, available_hours_week: r.available_hours_week });
  const changed = f.billing_role !== (r.billing_role || "") || f.cost_rate_paise !== (r.cost_rate_paise || 0) || Number(f.available_hours_week) !== r.available_hours_week;
  return (
    <div className="grid items-end gap-2 border-t border-hairline pt-2 md:grid-cols-[1fr_150px_150px_110px_auto]">
      <div><b>{r.name}</b><div className="text-[12px] text-ivory-35">{r.role}</div></div>
      <Field label="Billing role"><Select value={f.billing_role} onChange={(e) => setF({ ...f, billing_role: e.target.value })} options={[{ value: "", label: "None" }, ...roles.map((x) => ({ value: x, label: x }))]} /></Field>
      <Field label="Cost per hour"><MoneyInput paise={f.cost_rate_paise} onChange={(v) => setF({ ...f, cost_rate_paise: v || 0 })} /></Field>
      <Field label="Hours / week"><Input inputMode="decimal" value={f.available_hours_week} onChange={(e) => setF({ ...f, available_hours_week: e.target.value })} /></Field>
      <Button size="sm" disabled={!changed} onClick={async () => { try { await act("team.set_rates", { user_id: r.user_id, ...f, available_hours_week: Number(f.available_hours_week) }); toast("Saved"); onSaved(); } catch (e) { toast(e.message, "error"); } }}>Save</Button>
    </div>
  );
}

function RateSettings({ admin, owner }) {
  const q = useAct("rates.settings");
  const refresh = useRefresh();
  const [f, setF] = useState(null);
  useEffect(() => { if (q.data) setF({ day_hours: q.data.day_hours, target_margin_pct: q.data.target_margin_bp / 100, managers_see_costs: q.data.managers_see_costs, roles: q.data.billing_roles.join(", ") }); }, [q.data]);
  if (!f) return null;
  return (
    <Card className="space-y-3">
      <Kicker>Settings</Kicker>
      <div className="grid gap-2 md:grid-cols-3">
        <Field label="Hours in a working day"><Input inputMode="numeric" disabled={!admin} value={f.day_hours} onChange={(e) => setF({ ...f, day_hours: e.target.value })} /></Field>
        <Field label="Target margin %"><Input inputMode="decimal" disabled={!admin} value={f.target_margin_pct} onChange={(e) => setF({ ...f, target_margin_pct: e.target.value })} /></Field>
        <Field label="Billing roles"><Input disabled={!admin} value={f.roles} onChange={(e) => setF({ ...f, roles: e.target.value })} /></Field>
      </div>
      {owner && <Toggle on={f.managers_see_costs} onChange={(v) => setF({ ...f, managers_see_costs: v })} label="Managers can see costs and margins" />}
      {q.data.time_locked_before && <p className="text-[14px] text-ivory-70">Time before {date(q.data.time_locked_before)} is locked.</p>}
      {admin && <div className="flex flex-wrap gap-2">
        <Button onClick={async () => { try { await act("rates.update_settings", { day_hours: Number(f.day_hours), target_margin_pct: Number(f.target_margin_pct), billing_roles: f.roles.split(",").map((x) => x.trim()).filter(Boolean), ...(owner ? { managers_see_costs: f.managers_see_costs } : {}) }); toast("Saved"); q.refetch(); refresh("workspace"); } catch (e) { toast(e.message, "error"); } }}>Save settings</Button>
      </div>}
      {admin && <div className="flex flex-wrap items-end gap-2 border-t border-hairline pt-3">
        <Field label="Lock all time before"><Input type="date" value={f.lock || ""} onChange={(e) => setF({ ...f, lock: e.target.value })} /></Field>
        <Button variant="quiet" disabled={!f.lock} onClick={async () => { try { await act("time.lock_period", { before: f.lock }); toast("Locked. Nothing before that date can change."); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Lock</Button>
      </div>}
    </Card>
  );
}

export function ChecklistsSection({ w }) {
  const q = useAct("task_templates.list");
  const [edit, setEdit] = useState(null);
  const admin = ["owner", "admin", "manager"].includes(w.role);
  const refresh = useRefresh();
  return (
    <>
      <Card className="space-y-3">
        <div className="flex items-center gap-2"><Kicker>Checklists</Kicker>{admin && <Button size="sm" className="ml-auto" icon={Plus} onClick={() => setEdit({ name: "", items: [{ title: "", estimate_hours: "", due_days: 0 }] })}>New checklist</Button>}</div>
        <p className="text-[14px] text-ivory-70">A saved list of tasks. Add it to a project, to a stage (every project entering it gets the tasks), or to each retainer period.</p>
        <Loadable q={q}>{(rows) => rows.map((t) => (
          <div key={t.id} className="flex items-center gap-2 border-t border-hairline pt-2"><b className="flex-1">{t.name}</b><span className="text-[13px] text-ivory-70">{t.items.length} tasks</span>
            {admin && <Button size="sm" variant="quiet" onClick={() => setEdit({ ...t, items: t.items.map((i) => ({ ...i, estimate_hours: i.estimate_minutes ? i.estimate_minutes / 60 : "" })) })}>Edit</Button>}</div>))}</Loadable>
      </Card>
      <Card className="space-y-2">
        <Kicker>Add a checklist when a project enters a stage</Kicker>
        {w.stages.map((s) => (
          <div key={s.id} className="flex items-center gap-2"><span className="min-w-0 flex-1 text-[14px]">{s.name}</span>
            <Select className="w-56" disabled={!["owner", "admin"].includes(w.role)} value={s.task_template_id || ""} onChange={async (e) => { await act("stages.set_task_template", { stage_id: s.id, template_id: e.target.value || null }); refresh("workspace"); toast("Saved"); }}
              options={[{ value: "", label: "None" }, ...(q.data || []).map((t) => ({ value: t.id, label: t.name }))]} /></div>))}
      </Card>
      {edit && (
        <Sheet open onClose={() => setEdit(null)} title={edit.id ? "Edit checklist" : "New checklist"} wide>
          <div className="space-y-3">
            <Field label="Name"><Input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} placeholder="Monthly retainer checklist" /></Field>
            {edit.items.map((it, i) => (
              <div key={i} className="grid gap-2 md:grid-cols-[1fr_110px_110px_150px_28px]">
                <Input value={it.title} placeholder="Task" onChange={(e) => setEdit({ ...edit, items: edit.items.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
                <Input value={it.estimate_hours} placeholder="Hours" inputMode="decimal" onChange={(e) => setEdit({ ...edit, items: edit.items.map((x, j) => (j === i ? { ...x, estimate_hours: e.target.value } : x)) })} />
                <Input value={it.due_days} placeholder="Due in days" inputMode="numeric" onChange={(e) => setEdit({ ...edit, items: edit.items.map((x, j) => (j === i ? { ...x, due_days: e.target.value } : x)) })} />
                <Select value={it.assignee_role || "project_owner"} onChange={(e) => setEdit({ ...edit, items: edit.items.map((x, j) => (j === i ? { ...x, assignee_role: e.target.value } : x)) })}
                  options={[{ value: "project_owner", label: "Project owner" }, { value: "admin", label: "An Admin" }, { value: "manager", label: "A Manager" }, { value: "member", label: "A Member" }]} />
                <button aria-label="Remove" onClick={() => setEdit({ ...edit, items: edit.items.filter((_, j) => j !== i) })}><Trash2 size={15} className="text-ivory-35" /></button>
              </div>))}
            <Button size="sm" icon={Plus} onClick={() => setEdit({ ...edit, items: [...edit.items, { title: "", estimate_hours: "", due_days: 0 }] })}>Add task</Button>
            <Button variant="primary" className="w-full" onClick={async () => { try { await act("task_templates.create", { id: edit.id, name: edit.name, items: edit.items }); setEdit(null); q.refetch(); toast("Saved"); } catch (e) { toast(e.message, "error"); } }}>Save checklist</Button>
          </div>
        </Sheet>
      )}
    </>
  );
}

export function WinChances({ w }) {
  const refresh = useRefresh();
  const admin = ["owner", "admin"].includes(w.role);
  const DEF = { enquiry: 10, call_booked: 25, proposal_sent: 50 };
  return (
    <Card className="space-y-2">
      <Kicker>Win chance by stage</Kicker>
      <p className="text-[14px] text-ivory-70">Used by the forecast: an opportunity counts as its value × this chance. It's an estimate, and always shown apart from confirmed money.</p>
      {w.stages.filter((s) => s.group === "opportunity").map((s) => (
        <div key={s.id} className="flex items-center gap-2"><span className="min-w-0 flex-1 text-[14px]">{s.name}</span>
          <Input className="w-24 text-right" inputMode="numeric" disabled={!admin} defaultValue={s.win_probability ?? DEF[s.key] ?? 20}
            onBlur={async (e) => { try { await act("stages.set_probability", { stage_id: s.id, pct: Number(e.target.value) }); refresh("workspace", "forecast"); } catch (err) { toast(err.message, "error"); } }} /><span className="text-ivory-70">%</span></div>))}
    </Card>
  );
}

export function ConnectedApps() {
  const q = useAct("mcp.connected_apps");
  return (
    <Card ai className="space-y-2">
      <Kicker ai>Assistants signed in</Kicker>
      <p className="text-[14px] text-ivory-70">Assistants that connected with a proper sign-in (OAuth). Add {location.origin}/mcp as a connector in Claude or ChatGPT; it opens this app to sign in and lets you choose what it may do.</p>
      <Loadable q={q}>{(rows) => !rows.length ? <p className="text-[14px] text-ivory-35">None yet.</p> : rows.map((a) => (
        <div key={a.client_id + a.user_id} className="flex flex-wrap items-center gap-2 border-t border-hairline pt-2 text-[14px]">
          <span className="min-w-0 flex-1"><b>{a.name}</b> · {a.user} · {a.scope === "read" ? "read only" : a.scope === "drafts" ? "read + drafts" : "full"}<span className="block text-[12px] text-ivory-35">since {date(a.since)}{a.last_used ? ` · last used ${dt(a.last_used)}` : ""}</span></span>
          <Button size="sm" variant="quiet" onClick={async () => { await act("mcp.disconnect_app", { client_id: a.client_id, user_id: a.user_id }); q.refetch(); toast("Signed out"); }}>Sign out</Button>
        </div>))}</Loadable>
    </Card>
  );
}
