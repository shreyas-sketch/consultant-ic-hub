import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { act, download, useAct } from "@/shared/api";
import { date, inr, titleCase } from "@/shared/lib/format";
import { useWs } from "@/app/layout/AppShell";
import { Button, Card, Chip, Empty, Field, Input, Loadable, PageHeader, Segmented, Select, Sheet, Tabs, cx, toast } from "@/app/ui";
import { InvoiceCard } from "@/app/features/projects/Project";

const G = [["overdue", "Overdue", "text-alert"], ["processing", "Processing", "text-ivory-70"], ["upcoming", "Upcoming", "text-ivory-35"], ["paid", "Paid", "text-gold"]];

export default function Payments() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "overdue";
  const q = useAct("payments.list_due", {});
  const nav = useNavigate();
  const [inv, setInv] = useState(null);
  return (
    <div>
      <PageHeader kicker="Payments" title="Money owed," accent="money in" sub="Clients pay you directly by UPI or bank transfer. Nothing passes through us. A payment counts only when you confirm it." />
      <Loadable q={q}>
        {(d) => (
          <>
            <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              {G.map(([k, l, c]) => (
                <button key={k} onClick={() => setSp({ tab: k })} className={cx("rounded-card border bg-panel p-4 text-left", tab === k ? "border-gold-deep" : "border-hairline")}>
                  <div className="text-[12px] font-medium uppercase tracking-[0.16em] text-ivory-70">{l}</div>
                  <div className={cx("tnum mt-1 text-[24px] font-extrabold", c)}>{inr(d.totals_paise[k], { short: true })}</div>
                  <div className="text-[13px] text-ivory-35">{d.groups[k].length} item{d.groups[k].length === 1 ? "" : "s"}</div>
                </button>
              ))}
            </div>
            {d.stale_claims.length > 0 && <Card className="mb-3">{d.stale_claims.length} "I've paid" claim(s) waiting more than 2 days. Confirm or reject them below.</Card>}
            {tab === "processing" && <p className="mb-2 text-[14px] text-ivory-70">The client tapped "I've paid". Check your bank or UPI app, then confirm.</p>}
            {!d.groups[tab].length ? <Empty title="Nothing here" /> : (
              <div className="space-y-2">
                {d.groups[tab].map((i) => (
                  <Card key={i.invoice_id + i.item_id} className="flex flex-wrap items-center gap-3">
                    <div className="min-w-0 flex-1"><button onClick={() => nav(`/projects/${i.project_id}?tab=payments`)} className="font-bold hover:text-gold">{i.project}</button>
                      <div className="text-[13px] text-ivory-70">{i.number} · {i.label} · {tab === "paid" ? `paid ${date(i.paid_at)}` : i.due_date ? `due ${date(i.due_date)}` : "due on signing"}{i.late_fee_paise ? ` · includes late fee ${inr(i.late_fee_paise)}` : ""}</div></div>
                    <span className={cx("tnum text-[18px] font-extrabold", tab === "overdue" ? "text-alert" : "text-gold")}>{inr(tab === "paid" ? i.paid_paise : i.amount_paise - i.paid_paise)}</span>
                    {tab !== "paid" && <Button size="sm" onClick={() => setInv(i.invoice_id)}>Open</Button>}
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </Loadable>
      <More />
      <Sheet open={!!inv} onClose={() => { setInv(null); q.refetch(); }} title="Invoice" wide>{inv && <InvoiceCard id={inv} onChange={() => q.refetch()} />}</Sheet>
    </div>
  );
}

function More() {
  const [tab, setTab] = useState("invoices");
  return (
    <div className="mt-8">
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "invoices", label: "All invoices" }, { value: "recurring", label: "Monthly invoices" }, { value: "promo", label: "Promo codes" }]} />
      {tab === "invoices" && <Invoices />}
      {tab === "recurring" && <Recurring />}
      {tab === "promo" && <Promo />}
    </div>
  );
}

function Invoices() {
  const [f, setF] = useState({ status: "", fy: "", date_from: "", date_to: "" });
  const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
  const q = useAct("invoices.list", body);
  const exports = useAct("exports.list");
  const nav = useNavigate();
  const [sel, setSel] = useState([]);
  const rows = q.data || [];
  const target = sel.length ? { ids: sel } : body;
  const fys = [...new Set(rows.map((r) => r.fy).filter(Boolean))];
  async function run(name, ok) {
    try { const r = await act(name, target); ok(r); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <div>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} options={[{ value: "", label: "Any status" }, { value: "draft", label: "Draft" }, { value: "sent", label: "Sent" }, { value: "partially_paid", label: "Part paid" }, { value: "overdue", label: "Overdue" }, { value: "paid", label: "Paid" }, { value: "void", label: "Cancelled" }]} />
        <Select value={f.fy} onChange={(e) => setF({ ...f, fy: e.target.value })} options={[{ value: "", label: "Any financial year" }, ...fys.map((y) => ({ value: y, label: `FY ${y}` }))]} />
        <Input type="date" aria-label="From" value={f.date_from} onChange={(e) => setF({ ...f, date_from: e.target.value })} />
        <Input type="date" aria-label="To" value={f.date_to} onChange={(e) => setF({ ...f, date_to: e.target.value })} />
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[13px] text-ivory-70">{sel.length ? `${sel.length} selected` : `${rows.length} shown`}</span>
        <Button size="sm" onClick={() => run("invoices.bulk_download", (r) => { toast(r.summary); exports.refetch(); })}>Download PDFs (ZIP)</Button>
        <Button size="sm" onClick={() => run("invoices.bulk_remind", (r) => toast(r.summary))}>Send reminders</Button>
        <Button size="sm" variant="quiet" onClick={() => run("invoices.export", (r) => download(r.filename, r.csv, "text/csv"))}>Export CSV</Button>
        {sel.length > 0 && <button className="text-[13px] font-bold text-ivory-70" onClick={() => setSel([])}>Clear</button>}
      </div>
      {(exports.data || []).filter((x) => x.status !== "ready" || x.link).slice(0, 3).map((x) => (
        <Card key={x.id} className="mb-2 flex items-center gap-3 text-[14px]"><span className="flex-1">ZIP of {x.count} invoice{x.count === 1 ? "" : "s"}</span>
          {x.link ? <a className="font-bold text-gold" href={x.link}>Download</a> : <span className="text-ivory-70">{x.status === "failed" ? "Couldn't build it. Try again." : "Building…"}</span>}</Card>))}
      <Loadable q={q} empty={<Empty title="No invoices match" />}>
        {(rs) => (
          <div className="overflow-x-auto rounded-card border border-hairline">
            <table className="w-full min-w-[600px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr>
              <th className="w-10 p-3"><input type="checkbox" aria-label="Select all" checked={rs.length > 0 && rs.every((r) => sel.includes(r.id))} onChange={(e) => setSel(e.target.checked ? rs.map((r) => r.id) : [])} /></th>
              <th className="p-3">Number</th><th className="p-3">Project</th><th className="p-3">Status</th><th className="p-3 text-right">Total</th><th className="p-3 text-right">Due</th></tr></thead>
              <tbody>{rs.map((r) => (
                <tr key={r.id} className="border-t border-hairline hover:bg-panel">
                  <td className="p-3"><input type="checkbox" aria-label={`Select ${r.number || "draft"}`} checked={sel.includes(r.id)} onChange={() => setSel(sel.includes(r.id) ? sel.filter((x) => x !== r.id) : [...sel, r.id])} /></td>
                  <td className="cursor-pointer p-3" onClick={() => nav(`/projects/${r.project_id}?tab=payments`)}>{r.number || "Draft"}</td><td className="max-w-[200px] cursor-pointer truncate p-3" onClick={() => nav(`/projects/${r.project_id}?tab=payments`)}>{r.project_name}</td>
                  <td className="p-3"><Chip tone={r.status === "paid" ? "gold" : "muted"}>{titleCase(r.status === "void" ? "cancelled" : r.status)}</Chip></td>
                  <td className="tnum p-3 text-right text-gold">{inr(r.totals?.total)}</td><td className="tnum p-3 text-right">{inr(r.totals?.due)}</td></tr>))}</tbody></table>
          </div>
        )}
      </Loadable>
    </div>
  );
}

function Recurring() {
  const q = useAct("recurring.list");
  return (
    <Loadable q={q} empty={<Empty title="No monthly invoices" line="Set one up from a project's Payments tab." />}>
      {(rows) => rows.map((r) => (
        <Card key={r.id} className="mb-2 flex items-center gap-3"><div className="min-w-0 flex-1"><b>{r.lines.map((l) => l.name).join(", ")}</b><div className="text-[13px] text-ivory-70">Day {r.day_of_month} of each month · {r.active ? "active" : "stopped"}</div></div>
          <span className="tnum font-bold text-gold">{inr(r.lines.reduce((a, l) => a + l.price_paise * (l.qty || 1), 0))}</span>
          {r.active && <Button size="sm" variant="quiet" onClick={async () => { await act("recurring.cancel", { id: r.id }); q.refetch(); }}>Stop</Button>}</Card>))}
    </Loadable>
  );
}

function Promo() {
  const q = useAct("promo.list");
  const [f, setF] = useState({ code: "", kind: "pct_bp", value: "" });
  return (
    <div>
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Input placeholder="CODE" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} />
        <Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} options={[{ value: "pct_bp", label: "% off" }, { value: "flat", label: "₹ off" }]} />
        <Input inputMode="decimal" placeholder={f.kind === "pct_bp" ? "10" : "5000"} value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} />
        <Button onClick={async () => { try { await act("promo.save", { code: f.code, kind: f.kind, value: Math.round(Number(f.value) * 100) }); setF({ code: "", kind: "pct_bp", value: "" }); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Add code</Button>
      </div>
      <Loadable q={q} empty={<p className="text-ivory-70">No codes yet. A code can never take a total to zero.</p>}>
        {(rows) => rows.map((p) => <Card key={p.id} className="mb-2 flex justify-between"><b>{p.code}</b><span>{p.kind === "pct_bp" ? `${p.value / 100}% off` : `${inr(p.value)} off`}</span></Card>)}
      </Loadable>
    </div>
  );
}

export { Segmented, Field, useWs };
