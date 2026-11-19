// Reports: forecast (confirmed vs pipeline, kept apart), profit and effective rate, utilisation.
import { useState } from "react";
import { useNavigate } from "react-router";
import { act, download, useAct } from "@/shared/api";
import { hm, inr } from "@/shared/lib/format";
import { Button, Card, Disclaimer, Empty, Kicker, Loadable, Segmented, Stat, cx, toast } from "@/app/ui";

export function ForecastTab() {
  const [months, setMonths] = useState(6);
  const q = useAct("forecast.get", { months });
  const nav = useNavigate();
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><Segmented value={months} onChange={setMonths} options={[{ value: 6, label: "6 months" }, { value: 12, label: "12 months" }]} /></div>
      <Loadable q={q}>
        {(f) => {
          const max = Math.max(1, ...f.months.map((m) => Math.max(m.total_paise, m.target_paise || 0)));
          return (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <Stat label="Confirmed" value={inr(f.totals.confirmed_paise, { short: true })} sub="Agreed invoices and retainers" />
                <Stat label="Pipeline (estimate)" value={inr(f.totals.pipeline_paise, { short: true })} gold={false} sub="Weighted by win chance" />
                {f.undated_confirmed_paise > 0 && <Stat label="Agreed, no date yet" value={inr(f.undated_confirmed_paise, { short: true })} gold={false} sub="Milestones and on-signing items" />}
              </div>
              <Card>
                <Kicker>Next {months} months</Kicker>
                <div className="mt-4 flex h-56 items-end gap-2" role="img" aria-label="Confirmed and pipeline by month">
                  {f.months.map((m) => (
                    <div key={m.month} className="relative flex h-full min-w-0 flex-1 flex-col justify-end" title={`${m.label}: ${inr(m.confirmed_paise)} confirmed + ${inr(m.pipeline_paise)} pipeline (estimate)`}>
                      {m.target_paise ? <div className="absolute inset-x-0 border-t border-dashed border-ivory-35" style={{ bottom: `${(m.target_paise / max) * 100}%` }} /> : null}
                      <div className="rounded-t-[6px] border border-dashed border-gold/60 bg-gold/10" style={{ height: `${(m.pipeline_paise / max) * 100}%` }} />
                      <div className="bg-gradient-to-t from-gold-deep to-gold" style={{ height: `${(m.confirmed_paise / max) * 100}%` }} />
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex gap-2">{f.months.map((m) => <div key={m.month} className="min-w-0 flex-1 truncate text-center text-[12px] text-ivory-70">{m.label.split(" ")[0]}</div>)}</div>
                <div className="mt-3 flex flex-wrap gap-4 text-[13px] text-ivory-70">
                  <span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-sm bg-gold" /> Confirmed</span>
                  <span className="inline-flex items-center gap-2"><span className="h-3 w-3 rounded-sm border border-dashed border-gold/60 bg-gold/10" /> Pipeline — estimate</span>
                  {f.months[0].target_paise ? <span className="inline-flex items-center gap-2"><span className="w-4 border-t border-dashed border-ivory-35" /> Monthly target</span> : null}
                </div>
              </Card>
              <div className="overflow-x-auto rounded-card border border-hairline">
                <table className="w-full min-w-[520px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Month</th><th className="p-3 text-right">Confirmed</th><th className="p-3 text-right">Pipeline (estimate)</th><th className="p-3 text-right">Total</th></tr></thead>
                  <tbody>{f.months.map((m) => <tr key={m.month} className="border-t border-hairline"><td className="p-3">{m.label}</td><td className="tnum p-3 text-right text-gold">{inr(m.confirmed_paise)}</td>
                    <td className="tnum p-3 text-right text-ivory-70">{inr(m.pipeline_paise)}</td><td className="tnum p-3 text-right font-bold">{inr(m.total_paise)}</td></tr>)}</tbody></table>
              </div>
              {f.pipeline.length > 0 && <Card><Kicker>Open opportunities</Kicker>
                {f.pipeline.map((p) => (
                  <button key={p.project_id} onClick={() => nav(`/projects/${p.project_id}?tab=details`)} className="flex w-full items-center gap-3 border-t border-hairline py-2 text-left text-[14px] first:border-0">
                    <span className="min-w-0 flex-1 truncate font-bold">{p.project}</span><span className="text-ivory-70">{p.stage} · {p.probability}%</span>
                    <span className="tnum text-ivory-70">{inr(p.value_paise, { short: true })}</span><span className="tnum w-20 text-right text-gold">{inr(p.weighted_paise, { short: true })}</span></button>))}</Card>}
              {f.ongoing_retainers.length > 0 && <p className="text-[13px] text-ivory-70">Ongoing (no end date): {f.ongoing_retainers.join(", ")}.</p>}
              <Disclaimer>Pipeline is an estimate: each opportunity's value × its stage's win chance. Change win chances in Settings → Pipeline.</Disclaimer>
            </>
          );
        }}
      </Loadable>
    </div>
  );
}

export function ProfitTab() {
  const [group, setGroup] = useState("project");
  const q = useAct("reports.profitability", { group });
  return (
    <div className="space-y-4">
      <Segmented value={group} onChange={setGroup} options={[{ value: "project", label: "By project" }, { value: "client", label: "By client" }, { value: "service", label: "By service" }]} />
      <Loadable q={q} empty={<Empty title="Nothing yet" line="Log time and record payments to see what work really earns." />}>
        {(r) => (
          <>
            <Card><p className="text-[15px]">{r.summary}</p>{r.standard_hourly_paise ? <p className="mt-1 text-[13px] text-ivory-70">Your standard rate: {inr(r.standard_hourly_paise)}/hour.</p> : null}</Card>
            {!r.rows.length ? <Empty title="Nothing yet" /> : (
              <div className="overflow-x-auto rounded-card border border-hairline">
                <table className="w-full min-w-[720px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr>
                  <th className="p-3">{group === "service" ? "Service" : group === "client" ? "Client" : "Project"}</th><th className="p-3 text-right">Billed</th><th className="p-3 text-right">Received</th>
                  <th className="p-3 text-right">Hours</th><th className="p-3 text-right">Effective rate</th>{r.rows[0].cost_paise !== undefined && <><th className="p-3 text-right">Cost</th><th className="p-3 text-right">Margin</th></>}</tr></thead>
                  <tbody>{r.rows.map((x) => {
                    const low = r.standard_hourly_paise && x.effective_hourly_paise && x.effective_hourly_paise < r.standard_hourly_paise * 0.6;
                    return (
                      <tr key={x.key} className="border-t border-hairline"><td className="max-w-[220px] truncate p-3 font-bold">{x.name}</td>
                        <td className="tnum p-3 text-right">{inr(x.billed_paise)}</td><td className="tnum p-3 text-right text-gold">{inr(x.received_paise)}</td>
                        <td className="tnum p-3 text-right">{x.hours}</td><td className={cx("tnum p-3 text-right font-bold", low ? "text-alert" : "text-gold")}>{x.effective_hourly_paise ? `${inr(x.effective_hourly_paise)}/h` : "—"}</td>
                        {x.cost_paise !== undefined && <><td className="tnum p-3 text-right">{inr(x.cost_paise)}</td><td className="tnum p-3 text-right">{x.margin_bp === null ? "—" : `${Math.round(x.margin_bp / 100)}%`}</td></>}</tr>
                    );
                  })}</tbody></table>
              </div>
            )}
            <Disclaimer>Effective rate = money received ÷ hours logged. Fixed fees use the fee actually received, so a fee that was too low shows up here.</Disclaimer>
          </>
        )}
      </Loadable>
    </div>
  );
}

export function UtilTab() {
  const [period, setPeriod] = useState("week");
  const q = useAct("reports.utilisation", { period, count: period === "week" ? 8 : 6 });
  return (
    <div className="space-y-4">
      <Segmented value={period} onChange={setPeriod} options={[{ value: "week", label: "By week" }, { value: "month", label: "By month" }]} />
      <Loadable q={q} empty={<Empty title="No time logged" />}>
        {(u) => (
          <>
            <div className="overflow-x-auto rounded-card border border-hairline">
              <table className="w-full min-w-[640px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Person</th>
                {u.buckets.map((b) => <th key={b} className="p-2 text-center">{b}</th>)}<th className="p-3 text-right">Average</th></tr></thead>
                <tbody>{u.people.map((p) => (
                  <tr key={p.user_id} className="border-t border-hairline"><td className="p-3 font-bold">{p.name}</td>
                    {p.cells.map((c) => <td key={c.label} className="p-2 text-center" title={`${hm(c.billable_minutes)} billable of ${hm(c.available_minutes)} available`}>
                      <span className={cx("tnum", c.pct >= 70 ? "text-gold" : "text-ivory-70")}>{c.pct === null ? "—" : `${c.pct}%`}</span></td>)}
                    <td className="tnum p-3 text-right font-bold">{p.avg_pct}%</td></tr>))}</tbody></table>
            </div>
            {u.non_billable_by_reason.length > 0 && <Card><Kicker>Non-billable time by reason</Kicker>
              {u.non_billable_by_reason.map((r) => <div key={r.reason} className="flex justify-between border-t border-hairline py-2 text-[14px] first:border-0"><span>{r.reason === "untagged" ? "Not tagged" : r.reason[0].toUpperCase() + r.reason.slice(1)}</span><span className="tnum">{hm(r.minutes)}</span></div>)}</Card>}
            <Disclaimer>Utilisation = billable hours ÷ available hours. Set each person's available hours in Settings → Services and rates.</Disclaimer>
          </>
        )}
      </Loadable>
    </div>
  );
}

export async function exportInvoicesCsv(filters = {}) {
  try { const r = await act("invoices.export", filters); download(r.filename, r.csv, "text/csv"); } catch (e) { toast(e.message, "error"); }
}

export const _ = Button;
