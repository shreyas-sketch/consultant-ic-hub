import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ChevronLeft, ChevronRight, Clock, Play, Plus, Square } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { date, hm, inr } from "../../lib/format";
import { LogTimeSheet, ProjectSelect, StatusChip, TimeInvoiceSheet } from "../components/addons";
import { Button, Card, Empty, Field, Input, Loadable, PageHeader, Select, Sheet, Stat, Tabs, cx, toast } from "../components/ui";

export default function Time() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "week";
  const [log, setLog] = useState(false);
  return (
    <div>
      <PageHeader kicker="Time" title="Hours in," accent="invoices out" sub="Log time by week, by entry or with a timer. Unbilled time turns into an invoice in a few taps."
        right={<Button variant="primary" icon={Plus} onClick={() => setLog(true)}>Log time</Button>} />
      <Timer />
      <Tabs value={tab} onChange={(t) => setSp({ tab: t })} tabs={[{ value: "week", label: "Week" }, { value: "list", label: "Entries" }, { value: "unbilled", label: "Unbilled" }]} />
      {tab === "week" && <Week />}
      {tab === "list" && <Entries />}
      {tab === "unbilled" && <Unbilled />}
      <LogTimeSheet open={log} onClose={() => setLog(false)} onDone={() => setSp({ tab })} />
    </div>
  );
}

function Timer() {
  const q = useAct("time.timer");
  const [pid, setPid] = useState("");
  const [note, setNote] = useState("");
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 30000); return () => clearInterval(t); }, []);
  const t = q.data;
  if (t) {
    const mins = Math.max(0, Math.floor((Date.now() - new Date(t.started_at).getTime()) / 60000));
    return (
      <Card className="mb-4 flex flex-wrap items-center gap-3 border-gold-deep">
        <Clock size={18} className="text-gold" />
        <div className="min-w-0 flex-1"><b>{t.project}</b><div className="text-[13px] text-ivory-70">{t.note || "Timer running"} · {hm(mins)}</div></div>
        <Button icon={Square} onClick={async () => { try { const r = await act("time.timer_stop"); toast(r.summary); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Stop and log</Button>
      </Card>
    );
  }
  return (
    <Card className="mb-4 grid gap-2 md:grid-cols-[1fr_1fr_auto] md:items-end">
      <ProjectSelect value={pid} onChange={setPid} label="Timer" />
      <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What are you working on?" /></Field>
      <Button icon={Play} disabled={!pid} onClick={async () => { try { await act("time.timer_start", { project_id: pid, note }); setNote(""); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Start</Button>
    </Card>
  );
}

function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00+05:30");
  d.setDate(d.getDate() + n);
  return new Date(d.getTime() + 5.5 * 3600e3).toISOString().slice(0, 10);
}

function Week() {
  const [start, setStart] = useState(null);
  const q = useAct("time.week", start ? { week_start: start } : {});
  const projects = useAct("projects.search", { limit: 300 });
  const [add, setAdd] = useState("");
  const [extra, setExtra] = useState([]);
  return (
    <Loadable q={q}>
      {(w0) => {
        const names = Object.fromEntries((projects.data?.items || []).map((p) => [p.id, p.name]));
        const rows = [...w0.rows, ...extra.filter((id) => !w0.rows.some((r) => r.project_id === id && !r.task_id))
          .map((id) => ({ project_id: id, task_id: null, project: names[id] || "Project", cells: {}, fixed: {} }))];
        const w = { ...w0, rows };
        return (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <Button size="sm" variant="quiet" icon={ChevronLeft} aria-label="Previous week" onClick={() => setStart(addDays(w.days[0], -7))} />
            <b className="text-[15px]">{date(w.days[0])} – {date(w.days[6])}</b>
            <Button size="sm" variant="quiet" icon={ChevronRight} aria-label="Next week" onClick={() => setStart(addDays(w.days[0], 7))} />
            <span className="tnum ml-auto font-bold text-gold">{hm(w.week_total)}</span>
          </div>
          {w.locked_before && <p className="mb-2 text-[13px] text-ivory-35">Time before {date(w.locked_before)} is locked.</p>}
          <div className="overflow-x-auto rounded-card border border-hairline">
            <table className="w-full min-w-[720px] text-[14px]">
              <thead className="bg-panel text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3 text-left">Project / task</th>
                {w.days.map((d) => <th key={d} className="p-2 text-center">{new Date(d + "T12:00:00+05:30").toLocaleDateString("en-IN", { weekday: "short", day: "numeric" })}</th>)}
                <th className="p-3 text-right">Total</th></tr></thead>
              <tbody>
                {w.rows.map((r) => (
                  <tr key={r.project_id + (r.task_id || "")} className="border-t border-hairline">
                    <td className="max-w-[220px] p-3"><div className="truncate font-bold">{r.project}</div>{r.task && <div className="truncate text-[12px] text-ivory-35">{r.task}</div>}</td>
                    {w.days.map((d) => <td key={d} className="p-1 text-center"><Cell r={r} d={d} locked={w.locked_before && d < w.locked_before} onSaved={() => q.refetch()} /></td>)}
                    <td className="tnum p-3 text-right font-bold">{(() => { const s = Object.values(r.cells).reduce((a, b) => a + b, 0); return s ? hm(s) : "—"; })()}</td>
                  </tr>
                ))}
                <tr className="border-t border-hairline bg-panel"><td className="p-3 text-[13px] text-ivory-70">Day total</td>
                  {w.days.map((d) => <td key={d} className="tnum p-2 text-center text-[13px] font-bold">{w.totals[d] ? hm(w.totals[d]) : ""}</td>)}<td /></tr>
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <div className="min-w-[240px] flex-1"><ProjectSelect value={add} onChange={setAdd} label="Add a row" /></div>
            <Button disabled={!add} onClick={() => { setExtra([...extra, add]); setAdd(""); }}>Add</Button>
          </div>
          {!w.rows.length && <p className="mt-3 text-[14px] text-ivory-70">Nothing logged this week yet. Add a project row, then type hours like 1.5 or 1:30.</p>}
        </div>
        );
      }}
    </Loadable>
  );
}

function parseHours(v) {
  const s = String(v).trim();
  if (!s) return 0;
  if (s.includes(":")) { const [h, m] = s.split(":"); return (Number(h) || 0) * 60 + (Number(m) || 0); }
  return Math.round((Number(s) || 0) * 60);
}

function Cell({ r, d, locked, onSaved }) {
  const mins = r.cells[d] || 0;
  const [v, setV] = useState(mins ? String(Math.round((mins / 60) * 100) / 100) : "");
  const fixed = (r.fixed || {})[d] || 0;
  return (
    <input aria-label={`Hours on ${d}`} inputMode="decimal" value={v} disabled={locked}
      className={cx("tnum h-10 w-16 rounded-input border bg-ink text-center text-[14px]", fixed ? "border-gold-deep/50" : "border-hairline", locked && "opacity-40")}
      title={fixed ? `${hm(fixed)} is in separate or billed entries` : ""}
      onChange={(e) => setV(e.target.value)}
      onBlur={async () => {
        const m = parseHours(v);
        if (m === mins) return;
        try { await act("time.set_cell", { project_id: r.project_id, task_id: r.task_id, date: d, minutes: m }); onSaved(); }
        catch (e) { toast(e.message, "error"); setV(mins ? String(Math.round((mins / 60) * 100) / 100) : ""); }
      }} />
  );
}

function Entries() {
  const [status, setStatus] = useState("");
  const q = useAct("time.list", status ? { status, limit: 300 } : { limit: 300 });
  const [sel, setSel] = useState([]);
  const toggle = (id) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
  async function mark(s) {
    try { const r = await act("time.set_billing_status", { ids: sel, status: s }); toast(`${r.changed} entr${r.changed === 1 ? "y" : "ies"} updated`); setSel([]); q.refetch(); }
    catch (e) { toast(e.message, "error"); }
  }
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "All entries" }, { value: "unbilled", label: "Unbilled" }, { value: "billed", label: "Billed" }, { value: "non_billable", label: "Non-billable" }]} />
        {sel.length > 0 && <>
          <span className="text-[13px] text-ivory-70">{sel.length} selected</span>
          <Button size="sm" onClick={() => mark("non_billable")}>Mark non-billable</Button>
          <Button size="sm" onClick={() => mark("billed")}>Billed outside the app</Button>
          <Button size="sm" variant="quiet" onClick={() => mark("unbilled")}>Back to unbilled</Button></>}
      </div>
      <Loadable q={q} empty={<Empty title="No time yet" line="Log time from here, a project, or the timer." />}>
        {(rows) => (
          <div className="overflow-x-auto rounded-card border border-hairline">
            <table className="w-full min-w-[680px] text-[14px]">
              <thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="w-10 p-3" /><th className="p-3">Date</th><th className="p-3">Project</th><th className="p-3">Note</th><th className="p-3">Who</th><th className="p-3 text-right">Time</th><th className="p-3 text-right">Value</th><th className="p-3">Status</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id} className="border-t border-hairline">
                  <td className="p-3"><input type="checkbox" aria-label="Select" checked={sel.includes(r.id)} disabled={r.billing_status === "billed" && !r.billed_by_hand} onChange={() => toggle(r.id)} /></td>
                  <td className="whitespace-nowrap p-3">{date(r.date)}</td><td className="max-w-[180px] truncate p-3">{r.project}</td>
                  <td className="max-w-[220px] truncate p-3 text-ivory-70">{r.task ? `${r.task} · ` : ""}{r.note}</td><td className="p-3 text-ivory-70">{r.person}</td>
                  <td className="tnum p-3 text-right">{hm(r.minutes)}</td><td className="tnum p-3 text-right text-gold">{r.amount_paise === null ? "—" : inr(r.amount_paise)}</td>
                  <td className="p-3"><StatusChip s={r.billing_status} />{r.on_draft && <span className="ml-1 text-[12px] text-ivory-35">on a draft</span>}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Loadable>
    </div>
  );
}

function Unbilled() {
  const q = useAct("time.unbilled", {});
  const [pid, setPid] = useState(null);
  const nav = useNavigate();
  return (
    <Loadable q={q}>
      {(d) => (
        <div>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3">
            <Stat label="Unbilled" value={inr(d.total_paise, { short: true })} sub={hm(d.minutes)} />
            <Stat label="Projects" value={d.items.length} gold={false} />
            <Stat label="Oldest entry" value={d.oldest ? date(d.oldest) : "—"} gold={false} />
          </div>
          {!d.items.length ? <Empty title="All billed" line="No billable time is waiting for an invoice." /> : d.items.map((i) => (
            <Card key={i.project_id} className="mb-2 flex flex-wrap items-center gap-3">
              <div className="min-w-0 flex-1"><button className="font-bold hover:text-gold" onClick={() => nav(`/projects/${i.project_id}?tab=time`)}>{i.project}</button>
                <div className="text-[13px] text-ivory-70">{hm(i.minutes)} · {i.count} entr{i.count === 1 ? "y" : "ies"} · oldest {date(i.oldest)}</div></div>
              <span className="tnum text-[18px] font-extrabold text-gold">{inr(i.amount_paise)}</span>
              <Button size="sm" variant="primary" onClick={() => setPid(i.project_id)}>Invoice it</Button>
            </Card>))}
          {pid && <TimeInvoiceSheet open onClose={() => setPid(null)} projectId={pid} onDone={(inv) => { q.refetch(); nav(`/projects/${inv.project_id}?tab=payments`); }} />}
        </div>
      )}
    </Loadable>
  );
}

export const _ = Sheet;
