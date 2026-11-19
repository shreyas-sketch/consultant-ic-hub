import { useState } from "react";
import { Download, Upload } from "lucide-react";
import { act, download, parseCsv, useAct } from "../../lib/api";
import { date, inr, istDateInput } from "../../lib/format";
import { useWs } from "../components/AppShell";
import { ForecastTab, ProfitTab, UtilTab } from "./Insight";
import { Button, Card, Disclaimer, ErrorCard, Field, Input, Kicker, Loadable, Meter, MoneyInput, PageHeader, Segmented, Select, Sheet, SkeletonList, Stat, Tabs, cx, toast } from "../components/ui";

export default function Reports() {
  const ws = useWs();
  const st = ws.data?.settings || {};
  const [f, setF] = useState({ date_from: "", date_to: "", type: "", source: "", tag: "" });
  const [tab, setTab] = useState("overview");
  const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v).map(([k, v]) => [k, k.startsWith("date") ? new Date(v + "T00:00:00+05:30").toISOString() : v]));
  return (
    <div>
      <PageHeader kicker="Reports" title="The numbers," accent="plainly" sub="Every project counts, whatever its source. Filter any report." />
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-5">
        <input type="date" className="rounded-input border border-hairline bg-panel px-3 py-3" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} aria-label="From" />
        <input type="date" className="rounded-input border border-hairline bg-panel px-3 py-3" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} aria-label="To" />
        <Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} options={[{ value: "", label: "Any type" }, ...(st.project_types || [])]} />
        <Select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} options={[{ value: "", label: "Any source" }, ...(st.lead_sources || [])]} />
        <Input placeholder="Tag" value={f.tag} onChange={(e) => setF({ ...f, tag: e.target.value })} />
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "overview", label: "Overview" }, { value: "pipeline", label: "Leads and pipeline" }, { value: "sales", label: "Sales" }, { value: "forecast", label: "Forecast" }, { value: "profit", label: "Profit" }, ...(["owner", "admin", "manager"].includes(ws.data?.role) ? [{ value: "util", label: "Utilisation" }] : []), { value: "money", label: "Money view" }, { value: "tax", label: "For your CA" }]} />
      {tab === "forecast" && <ForecastTab />}
      {tab === "profit" && <ProfitTab />}
      {tab === "util" && <UtilTab />}
      {tab === "overview" && <Overview body={body} />}
      {tab === "pipeline" && <Pipeline body={body} />}
      {tab === "sales" && <Sales body={body} />}
      {tab === "money" && <MoneyView body={body} />}
      {tab === "tax" && <Tax />}
    </div>
  );
}

function Overview({ body }) {
  const q = useAct("reports.summary", body);
  return (
    <Loadable q={q}>
      {(s) => (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Received this month" value={inr(s.received_month_paise, { short: true })} />
            <Stat label="Received this year" value={inr(s.received_fy_paise, { short: true })} sub="Financial year (Apr–Mar)" />
            <Stat label="Outstanding" value={inr(s.outstanding_paise, { short: true })} sub={s.processing_paise ? `${inr(s.processing_paise, { short: true })} waiting for your confirmation` : ""} />
            <Stat label="Overdue" value={inr(s.overdue_paise, { short: true })} alert={s.overdue_paise > 0} />
            <Stat label="Bookings" value={s.bookings} gold={false} sub={`${s.bookings_month} this month`} />
          </div>
          {s.goal_paise > 0 && <Card className="mt-4"><div className="mb-2 flex justify-between"><Kicker>Yearly goal</Kicker><span className="tnum text-[14px]"><b className="text-gold">{inr(s.received_fy_paise, { short: true })}</b> of {inr(s.goal_paise, { short: true })}</span></div><Meter pct={s.goal_pct} /></Card>}
          <Exports body={body} />
        </>
      )}
    </Loadable>
  );
}

function Bars({ rows, value, label, money = true, alertNeg }) {
  const max = Math.max(1, ...rows.map((r) => Math.abs(value(r))));
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[110px_1fr_auto] items-center gap-3 text-[14px]">
          <span className="truncate text-ivory-70">{label(r)}</span>
          <div className="h-3 rounded-full bg-hairline"><div className={cx("h-3 rounded-full", alertNeg && value(r) < 0 ? "bg-alert" : "bg-gradient-to-r from-gold-deep to-gold-light")} style={{ width: `${(Math.abs(value(r)) / max) * 100}%` }} /></div>
          <span className="tnum font-bold text-gold">{money ? inr(value(r), { short: true }) : value(r)}</span>
        </div>
      ))}
      {!rows.length && <p className="text-ivory-70">No data for these filters.</p>}
    </div>
  );
}

function Pipeline({ body }) {
  const q = useAct("reports.pipeline", body);
  const [view, setView] = useState("share");
  return (
    <Loadable q={q}>
      {(d) => (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Leads" value={d.total} gold={false} />
            <Stat label="Average booked value" value={inr(d.avg_value_paise, { short: true })} />
            <Stat label="Days to book" value={d.avg_days_to_book ?? "—"} gold={false} sub="Average" />
            <Stat label="Files sent → booked" value={`${d.files_sent} → ${d.files_booked}`} gold={false} />
          </div>
          <Card><Kicker className="mb-3">Enquiry to booked, by stage</Kicker><Bars rows={d.by_stage} value={(r) => r.pct} label={(r) => r.stage} money={false} /></Card>
          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><Kicker>Lead sources</Kicker>
              <Segmented value={view} onChange={setView} options={[{ value: "share", label: "Share" }, { value: "value", label: "Value" }, { value: "conv", label: "Conversion" }, { value: "days", label: "Time to book" }]} /></div>
            <Bars rows={d.sources} label={(r) => r.source} money={view === "value"}
              value={(r) => ({ share: r.share_pct, value: r.value_paise, conv: r.conversion_pct, days: r.avg_days_to_book || 0 }[view])} />
            <p className="mt-2 text-[13px] text-ivory-35">{view === "share" || view === "conv" ? "Percent." : view === "days" ? "Days, on average." : ""}</p>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card><Kicker className="mb-3">Why leads were lost</Kicker><Bars rows={d.lost_reasons} label={(r) => r.reason} value={(r) => r.count} money={false} /></Card>
            <Card><Kicker className="mb-3">Bookings by month</Kicker><Bars rows={d.bookings_by_month} label={(r) => r.month} value={(r) => r.count} money={false} /></Card>
          </div>
        </div>
      )}
    </Loadable>
  );
}

function Sales({ body }) {
  const q = useAct("reports.payments", body);
  return (
    <Loadable q={q}>
      {(d) => (
        <div className="space-y-4">
          <Card><Kicker className="mb-3">Money received by month</Kicker><Bars rows={d.monthly} label={(r) => r.month} value={(r) => r.paise} /></Card>
          <Card><Kicker className="mb-3">Forecast from payment schedules</Kicker><Bars rows={d.forecast} label={(r) => r.month} value={(r) => r.paise} /><Disclaimer>{d.forecast_note}</Disclaimer></Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card><Kicker className="mb-3">By project type</Kicker><Bars rows={d.by_type} label={(r) => r.type} value={(r) => r.paise} /></Card>
            <Card><Kicker className="mb-3">By team member</Kicker><Bars rows={d.by_owner} label={(r) => r.owner} value={(r) => r.paise} /></Card>
          </div>
        </div>
      )}
    </Loadable>
  );
}

function MoneyView({ body }) {
  const q = useAct("money.view", body);
  const ex = useAct("expenses.list", {});
  const [add, setAdd] = useState(false);
  const [imp, setImp] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex gap-2"><Button size="sm" variant="primary" onClick={() => setAdd(true)}>Add expense</Button><Button size="sm" variant="quiet" icon={Upload} onClick={() => setImp(true)}>Upload bank statement</Button></div>
      <Loadable q={q}>
        {(d) => (
          <>
            <Card><Kicker className="mb-3">Cashflow (received minus expenses)</Kicker><Bars rows={d.cashflow} label={(r) => r.month} value={(r) => r.net_paise} alertNeg /></Card>
            <Card><Kicker className="mb-3">Profit per project</Kicker>
              {d.projects.map((p) => <div key={p.project_id} className="flex items-center gap-3 border-t border-hairline py-2 text-[14px] first:border-0"><span className="min-w-0 flex-1 truncate">{p.project}</span>
                <span className="text-ivory-70">{inr(p.received_paise, { short: true })} − {inr(p.expenses_paise, { short: true })}</span><b className={cx("tnum", p.profit_paise < 0 ? "text-alert" : "text-gold")}>{inr(p.profit_paise, { short: true })}</b></div>)}
              {!d.projects.length && <p className="text-ivory-70">No payments yet.</p>}</Card>
          </>
        )}
      </Loadable>
      <Card><Kicker className="mb-2">Expenses</Kicker>
        {(ex.data || []).map((e) => <div key={e.id} className="flex gap-3 border-t border-hairline py-2 text-[14px] first:border-0"><span className="w-24 text-ivory-70">{date(e.date)}</span><span className="min-w-0 flex-1 truncate">{e.category} · {e.note}</span><b className="tnum">{inr(e.amount_paise)}</b></div>)}
      </Card>
      <ExpenseSheet open={add} onClose={() => { setAdd(false); q.refetch(); ex.refetch(); }} />
      <StatementSheet open={imp} onClose={() => { setImp(false); q.refetch(); ex.refetch(); }} />
    </div>
  );
}

function ExpenseSheet({ open, onClose }) {
  const projects = useAct("projects.search", { limit: 200 }, { enabled: open });
  const [f, setF] = useState({ amount_paise: null, date: istDateInput(), category: "Travel", project_id: "", note: "" });
  return (
    <Sheet open={open} onClose={onClose} title="Add expense">
      <div className="space-y-3">
        <Field label="Amount"><MoneyInput paise={f.amount_paise} onChange={(v) => setF({ ...f, amount_paise: v })} /></Field>
        <Field label="Date"><input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
        <Select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} options={["Travel", "Software", "Marketing", "Contractors", "Office", "Other"]} />
        <Select value={f.project_id} onChange={(e) => setF({ ...f, project_id: e.target.value })} options={[{ value: "", label: "Not for a project" }, ...((projects.data?.items) || []).map((p) => ({ value: p.id, label: p.name }))]} />
        <Input placeholder="Note" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
        <Button variant="primary" className="w-full" onClick={async () => { try { await act("expenses.save", { ...f, project_id: f.project_id || null }); toast("Expense added"); onClose(); } catch (e) { toast(e.message, "error"); } }}>Add</Button>
      </div>
    </Sheet>
  );
}

function StatementSheet({ open, onClose }) {
  const [rows, setRows] = useState([]);
  const [res, setRes] = useState(null);
  return (
    <Sheet open={open} onClose={() => { setRows([]); setRes(null); onClose(); }} title="Upload a bank statement">
      <p className="text-ivory-70">A CSV export from your bank. Money going out becomes expenses you can tag to projects. Money coming in is skipped. No bank login needed.</p>
      <input type="file" accept=".csv" className="mt-3" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setRows(parseCsv(await f.text())); }} />
      {rows.length > 0 && !res && <Button className="mt-3 w-full" variant="primary" onClick={async () => { try { setRes(await act("expenses.import_statement", { rows })); } catch (e) { toast(e.message, "error"); } }}>Import {rows.length} rows</Button>}
      {res && <Card className="mt-3">Added {res.added} expenses, skipped {res.skipped} rows.</Card>}
    </Sheet>
  );
}

function Exports({ body }) {
  async function get(what) { try { const r = await act("reports.export_csv", { ...body, what }); download(r.filename, r.csv); } catch (e) { toast(e.message, "error"); } }
  return <div className="mt-4 flex flex-wrap gap-2">{["projects", "contacts", "payments"].map((w) => <Button key={w} size="sm" variant="quiet" icon={Download} onClick={() => get(w)}>{w[0].toUpperCase() + w.slice(1)} CSV</Button>)}</div>;
}

function Tax() {
  const ws = useWs();
  async function get(what) { try { const r = await act("tax.pack", { what }); download(r.filename, r.csv); } catch (e) { toast(e.message, "error"); } }
  return (
    <Card>
      <p className="text-ivory-70">Downloads for your CA. GST figures appear only when GST is switched on in Settings.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" icon={Download} onClick={() => get("invoice_register")}>Invoice register</Button>
        <Button size="sm" icon={Download} onClick={() => get("tds")}>TDS deducted by client</Button>
        {ws.data?.invoice?.gst_enabled && <Button size="sm" icon={Download} onClick={() => get("gst")}>GST by month</Button>}
      </div>
      <Disclaimer>Check GST, SAC codes and TDS treatment with your CA. This is a record of what you invoiced and received, not tax advice.</Disclaimer>
    </Card>
  );
}

export { ErrorCard, SkeletonList };
