// Shared pieces for the add-ons: budget bar, log time, invoice unbilled time, ask the client.
import { useState } from "react";
import { act, useAct } from "../../lib/api";
import { fromDateInput, hm, inr, todayISO } from "../../lib/format";
import { Button, Chip, Field, Input, Meter, Segmented, Select, Sheet, Textarea, Toggle, cx, toast } from "./ui";

export function BudgetBar({ b, compact }) {
  if (!b) return null;
  const over = b.pct >= 100;
  const label = b.type === "fee" ? `${inr(b.used, { short: true })} of ${inr(b.amount, { short: true })}` : `${hm(b.used)} of ${hm(b.amount)}`;
  if (compact) {
    return (
      <div className="mt-2" title={`Budget: ${label}`}>
        <Meter pct={b.pct} alert={over} />
        <div className={cx("mt-1 text-[12px]", over ? "text-alert" : b.pct >= 80 ? "text-gold" : "text-ivory-35")}>Budget {Math.round(b.pct)}%</div>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[13px]">
        <span className="text-ivory-70">{label}</span>
        <span className={cx("tnum font-bold", over ? "text-alert" : "text-gold")}>{Math.round(b.pct)}%</span>
      </div>
      <Meter pct={b.pct} alert={over} />
    </div>
  );
}

export function ProjectSelect({ value, onChange, label = "Project" }) {
  const q = useAct("projects.search", { limit: 300 });
  const items = q.data?.items || [];
  return (
    <Field label={label}>
      <Select value={value || ""} onChange={(e) => onChange(e.target.value)}
        options={[{ value: "", label: q.isLoading ? "Loading…" : "Choose a project" }, ...items.map((p) => ({ value: p.id, label: p.name }))]} />
    </Field>
  );
}

export function LogTimeSheet({ open, onClose, projectId, onDone }) {
  const [f, setF] = useState({ project_id: projectId || "", date: todayISO(), h: "", m: "", note: "", task_id: "", billable: true, reason: "admin" });
  const tasks = useAct("tasks.list", { scope: "open", project_id: f.project_id || projectId }, { enabled: !!(f.project_id || projectId) });
  const [busy, setBusy] = useState(false);
  const minutes = (Number(f.h) || 0) * 60 + (Number(f.m) || 0);
  async function save() {
    setBusy(true);
    try {
      const r = await act("time.log", { project_id: f.project_id || projectId, minutes: Math.round(minutes), date: f.date, note: f.note,
        task_id: f.task_id || null, billable: f.billable, reason: f.billable ? null : f.reason });
      toast(r.summary || "Time logged");
      setF({ ...f, h: "", m: "", note: "" });
      onDone && onDone();
      onClose();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Log time">
      <div className="space-y-3">
        {!projectId && <ProjectSelect value={f.project_id} onChange={(v) => setF({ ...f, project_id: v, task_id: "" })} />}
        <div className="grid grid-cols-3 gap-2">
          <Field label="Date"><Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Hours"><Input inputMode="decimal" value={f.h} onChange={(e) => setF({ ...f, h: e.target.value })} placeholder="2" /></Field>
          <Field label="Minutes"><Input inputMode="numeric" value={f.m} onChange={(e) => setF({ ...f, m: e.target.value })} placeholder="30" /></Field>
        </div>
        {(tasks.data || []).length > 0 && (
          <Field label="Task (optional)"><Select value={f.task_id} onChange={(e) => setF({ ...f, task_id: e.target.value })}
            options={[{ value: "", label: "No task" }, ...tasks.data.map((t) => ({ value: t.id, label: t.title }))]} /></Field>
        )}
        <Field label="Note"><Input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} placeholder="What you worked on" /></Field>
        <Toggle on={f.billable} onChange={(v) => setF({ ...f, billable: v })} label="Billable" />
        {!f.billable && <Segmented value={f.reason} onChange={(v) => setF({ ...f, reason: v })}
          options={[{ value: "admin", label: "Admin" }, { value: "selling", label: "Selling" }, { value: "learning", label: "Learning" }, { value: "other", label: "Other" }]} />}
        <Button variant="primary" className="w-full" busy={busy} disabled={!minutes || !(f.project_id || projectId)} onClick={save}>
          Log {minutes ? hm(minutes) : "time"}</Button>
      </div>
    </Sheet>
  );
}

export function TimeInvoiceSheet({ open, onClose, projectId, onDone }) {
  const [f, setF] = useState({ range: "all", date_from: "", date_to: todayISO(), rounding: 0, group_by: "task", timesheet: "link",
    columns: ["date", "task", "note", "person"] });
  const un = useAct("time.unbilled", { project_id: projectId }, { enabled: open });
  const item = un.data?.items?.[0];
  const [busy, setBusy] = useState(false);
  const col = (c) => setF({ ...f, columns: f.columns.includes(c) ? f.columns.filter((x) => x !== c) : [...f.columns, c] });
  async function go() {
    setBusy(true);
    try {
      const inv = await act("invoices.add_unbilled_time", { project_id: projectId, rounding: f.rounding, group_by: f.group_by, timesheet: f.timesheet,
        columns: f.columns, ...(f.range === "dates" ? { date_from: f.date_from || null, date_to: f.date_to || null } : {}) });
      toast(`Draft invoice ready: ${inv.added.lines} line${inv.added.lines === 1 ? "" : "s"}, ${inr(inv.totals.total)}`);
      onDone && onDone(inv);
      onClose();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Invoice unbilled time">
      <div className="space-y-4">
        {item ? <p className="text-[14px] text-ivory-70"><b className="text-gold">{inr(item.amount_paise)}</b> unbilled ({hm(item.minutes)}), oldest from {item.oldest}.</p>
          : <p className="text-[14px] text-ivory-70">Checking unbilled time…</p>}
        <Field label="Which time"><Segmented value={f.range} onChange={(v) => setF({ ...f, range: v })} options={[{ value: "all", label: "All unbilled" }, { value: "dates", label: "A date range" }]} /></Field>
        {f.range === "dates" && <div className="grid grid-cols-2 gap-2">
          <Field label="From"><Input type="date" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} /></Field>
          <Field label="To"><Input type="date" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} /></Field></div>}
        <Field label="Round each entry up to" hint="Changes the hours and the total together.">
          <Segmented value={f.rounding} onChange={(v) => setF({ ...f, rounding: v })} options={[{ value: 0, label: "None" }, { value: 6, label: "6 min" }, { value: 15, label: "15 min" }, { value: 30, label: "30 min" }]} /></Field>
        <Field label="Invoice lines by" hint="Only changes how lines look, never the total.">
          <Segmented value={f.group_by} onChange={(v) => setF({ ...f, group_by: v })} options={[{ value: "task", label: "Task" }, { value: "service", label: "Service" }, { value: "role", label: "Role" }, { value: "date", label: "Date" }]} /></Field>
        <Field label="The client sees the timesheet">
          <Segmented value={f.timesheet} onChange={(v) => setF({ ...f, timesheet: v })} options={[{ value: "full", label: "Under the invoice" }, { value: "link", label: "As a link" }, { value: "none", label: "No" }]} /></Field>
        {f.timesheet !== "none" && <div className="flex flex-wrap gap-2">{["date", "task", "note", "person"].map((c) => (
          <button key={c} onClick={() => col(c)} className={cx("h-9 rounded-full border px-3 text-[13px] font-bold", f.columns.includes(c) ? "border-gold-deep text-gold" : "border-hairline text-ivory-35")}>{c[0].toUpperCase() + c.slice(1)}</button>))}</div>}
        <Button variant="primary" className="w-full" busy={busy} onClick={go}>Make the draft invoice</Button>
        <p className="text-[13px] text-ivory-35">Time stays unbilled until you send the invoice. Then it's locked.</p>
      </div>
    </Sheet>
  );
}

export function ClientTaskSheet({ open, onClose, projectId, onDone }) {
  const [f, setF] = useState({ title: "", details: "", due: "", channel: "both" });
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      await act("client_tasks.assign", { project_id: projectId, title: f.title, details: f.details, due_at: fromDateInput(f.due, 18), channel: f.channel });
      toast("Sent to the client");
      setF({ title: "", details: "", due: "", channel: "both" });
      onDone && onDone();
      onClose();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Ask the client for something">
      <div className="space-y-3">
        <Field label="What do you need?"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Share last year's P&L" /></Field>
        <Field label="Details (optional)"><Textarea value={f.details} onChange={(e) => setF({ ...f, details: e.target.value })} placeholder="A simple Excel is fine." /></Field>
        <Field label="Due"><Input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
        <Field label="Send by"><Segmented value={f.channel} onChange={(v) => setF({ ...f, channel: v })} options={[{ value: "both", label: "WhatsApp + email" }, { value: "whatsapp", label: "WhatsApp" }, { value: "email", label: "Email" }]} /></Field>
        <p className="text-[13px] text-ivory-35">They get a link to mark it done, upload a file or reply. A reminder goes the day before it's due.</p>
        <Button variant="primary" className="w-full" busy={busy} disabled={!f.title.trim()} onClick={go}>Send</Button>
      </div>
    </Sheet>
  );
}

export const StatusChip = ({ s }) => (
  <Chip tone={s === "billed" ? "gold" : s === "unbilled" ? "muted" : "muted"}>{s === "non_billable" ? "Non-billable" : s === "billed" ? "Billed" : "Unbilled"}</Chip>
);
