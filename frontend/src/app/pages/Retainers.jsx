import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft, Plus } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { date, hm, inr, titleCase } from "../../lib/format";
import { ProjectSelect } from "../components/addons";
import { Button, Card, Chip, Empty, Field, Input, Kicker, Loadable, Meter, MoneyInput, PageHeader, Segmented, Select, Sheet, Stat, Toggle, cx, toast } from "../components/ui";

export default function Retainers() {
  const { id } = useParams();
  return id ? <Detail id={id} /> : <List />;
}

function List() {
  const q = useAct("retainers.list");
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <PageHeader kicker="Retainers" title="Monthly work that" accent="runs itself" sub="Hours tracked against the period, the client told as they go, the period closed and invoiced, the next one opened."
        right={<Button variant="primary" icon={Plus} onClick={() => setOpen(true)}>New retainer</Button>} />
      <Loadable q={q} empty={<Empty title="No retainers yet" line="Set one up for a client you work with every month." action={<Button onClick={() => setOpen(true)}>New retainer</Button>} />}>
        {(rows) => (
          <div className="space-y-2">{rows.map((r) => {
            const c = r.current;
            const p = c && c.available ? (c.used * 100) / c.available : 0;
            return (
              <Card key={r.id} className="cursor-pointer hover:border-gold-deep" onClick={() => nav(`/retainers/${r.id}`)}>
                <div className="flex flex-wrap items-baseline gap-2">
                  <b className="text-[16px]">{r.client || r.projects[0]?.name}</b><span className="text-ivory-70">· {r.name}</span>
                  <Chip tone={r.status === "active" ? "gold" : "muted"}>{titleCase(r.status)}</Chip>
                  <span className="tnum ml-auto font-bold text-gold">{r.kind === "payg" ? `up to ${inr(r.cap_paise)}` : inr(r.fee_paise)}<span className="text-[13px] font-medium text-ivory-35"> / {r.period === "quarterly" ? "quarter" : "month"}</span></span>
                </div>
                <div className="mt-1 text-[13px] text-ivory-70">{r.kind_label}{r.kind === "hours" ? ` · ${hm(r.included_minutes)} included` : ""}{r.end_date ? ` · ends ${date(r.end_date)}` : " · ongoing"}</div>
                {c && r.kind === "hours" && <div className="mt-3"><div className="mb-1 flex justify-between text-[13px]"><span>{c.label}: {hm(c.used)} of {hm(c.available)}</span><span className="text-ivory-70">{hm(c.left)} left</span></div><Meter pct={p} alert={p >= 100} /></div>}
                {c && r.kind !== "hours" && <div className="mt-2 text-[13px] text-ivory-70">{c.label}: {hm(c.used)} logged</div>}
                {!c && <div className="mt-2 text-[13px] text-ivory-35">No open period.</div>}
              </Card>
            );
          })}</div>
        )}
      </Loadable>
      <NewRetainer open={open} onClose={() => setOpen(false)} onDone={(r) => nav(`/retainers/${r.id}`)} />
    </div>
  );
}

function NewRetainer({ open, onClose, onDone, projectId, edit }) {
  const [f, setF] = useState(edit ? { project_id: edit.project_ids[0], name: edit.name, kind: edit.kind, period: edit.period, fee_paise: edit.fee_paise,
    included_hours: (edit.included_minutes || 0) / 60, cap_paise: edit.cap_paise || 0, billing: edit.billing, ro: edit.rollover?.mode || "none",
    cap_hours: (edit.rollover?.cap_minutes || 0) / 60, valid: edit.rollover?.valid_periods || 1, ov: edit.overage?.mode || "bill",
    borrow: (edit.overage?.borrow_cap_minutes || 0) / 60, alert_pct: edit.alert_pct || 80, auto_send: !!edit.auto_send, end_date: edit.end_date || "" }
    : { project_id: projectId || "", name: "Advisory retainer", kind: "hours", period: "monthly", fee_paise: 0, included_hours: 20,
      cap_paise: 0, billing: "advance", ro: "capped", cap_hours: 5, valid: 1, ov: "bill", borrow: 10, alert_pct: 80, auto_send: false, end_date: "" });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setF({ ...f, [k]: v });
  async function go() {
    setBusy(true);
    try {
      const r = await act(edit ? "retainers.update" : "retainers.create", { id: edit?.id, project_id: f.project_id, name: f.name, kind: f.kind, period: f.period, fee_paise: f.fee_paise,
        included_hours: Number(f.included_hours), cap_paise: f.cap_paise, billing: f.billing, alert_pct: Number(f.alert_pct), auto_send: f.auto_send,
        rollover: { mode: f.ro, cap_hours: Number(f.cap_hours), valid_periods: Number(f.valid) }, overage: { mode: f.ov, borrow_cap_hours: Number(f.borrow) },
        end_date: f.end_date || null });
      toast(edit ? (r.note || "Saved") : "Retainer set up. The first period is open.");
      onClose();
      onDone && onDone(r);
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title={edit ? "Change the plan" : "New retainer"} wide>
      <div className="grid gap-3 md:grid-cols-2">
        {!projectId && <ProjectSelect value={f.project_id} onChange={set("project_id")} />}
        <Field label="Name"><Input value={f.name} onChange={(e) => set("name")(e.target.value)} /></Field>
        <Field label="Kind" className="md:col-span-2"><Segmented value={f.kind} onChange={set("kind")} options={[{ value: "hours", label: "Hours bank" }, { value: "fixed", label: "Fixed scope" }, { value: "payg", label: "Pay as used, capped" }]} /></Field>
        <Field label="Period"><Segmented value={f.period} onChange={set("period")} options={[{ value: "monthly", label: "Monthly" }, { value: "quarterly", label: "Quarterly" }]} /></Field>
        {f.kind !== "payg" ? <Field label="Fee each period"><MoneyInput paise={f.fee_paise} onChange={set("fee_paise")} /></Field>
          : <Field label="Monthly cap"><MoneyInput paise={f.cap_paise} onChange={set("cap_paise")} /></Field>}
        {f.kind === "hours" && <Field label="Hours included"><Input inputMode="decimal" value={f.included_hours} onChange={(e) => set("included_hours")(e.target.value)} /></Field>}
        {f.kind !== "payg" && <Field label="Invoice"><Segmented value={f.billing} onChange={set("billing")} options={[{ value: "advance", label: "At the start" }, { value: "arrears", label: "At the end" }]} /></Field>}
        {f.kind === "hours" && <>
          <Field label="Unused hours"><Select value={f.ro} onChange={(e) => set("ro")(e.target.value)} options={[{ value: "none", label: "Lapse" }, { value: "capped", label: "Carry up to a cap" }, { value: "all", label: "Carry everything" }]} /></Field>
          {f.ro === "capped" && <div className="grid grid-cols-2 gap-2"><Field label="Up to (hours)"><Input value={f.cap_hours} onChange={(e) => set("cap_hours")(e.target.value)} /></Field>
            <Field label="Valid for"><Select value={f.valid} onChange={(e) => set("valid")(e.target.value)} options={[1, 2, 3].map((n) => ({ value: n, label: `${n} period${n > 1 ? "s" : ""}` }))} /></Field></div>}
          <Field label="Extra time"><Select value={f.ov} onChange={(e) => set("ov")(e.target.value)} options={[{ value: "bill", label: "Bill it on the next invoice" }, { value: "borrow", label: "Borrow from next period" }, { value: "absorb", label: "Absorb (don't bill)" }, { value: "ask", label: "Ask me first" }]} /></Field>
          {f.ov === "borrow" && <Field label="Borrow up to (hours)"><Input value={f.borrow} onChange={(e) => set("borrow")(e.target.value)} /></Field>}
          <Field label="Tell the client at (% used)"><Input inputMode="numeric" value={f.alert_pct} onChange={(e) => set("alert_pct")(e.target.value)} /></Field></>}
        <Field label="End date (optional)"><Input type="date" value={f.end_date} onChange={(e) => set("end_date")(e.target.value)} /></Field>
        <div className="md:col-span-2"><Toggle on={f.auto_send} onChange={set("auto_send")} label="Send retainer invoices by themselves (otherwise they wait for your OK)" /></div>
        {edit && <p className="text-[13px] text-ivory-70 md:col-span-2">Fee, hours, billing and the rollover and extra-time rules change from the next period. Name, alerts, auto-send and end date change now.</p>}
        <Button variant="primary" className="md:col-span-2" busy={busy} disabled={!(f.project_id || projectId)} onClick={go}>{edit ? "Save changes" : "Set up retainer"}</Button>
      </div>
    </Sheet>
  );
}

export { NewRetainer };

function Detail({ id }) {
  const q = useAct("retainers.get", { id });
  const nav = useNavigate();
  const [edit, setEdit] = useState(false);
  return (
    <Loadable q={q}>
      {(r) => {
        const c = r.current;
        const p = c && c.available ? (c.used * 100) / c.available : 0;
        return (
          <div>
            <button onClick={() => nav("/retainers")} className="mb-3 inline-flex items-center gap-1 text-[14px] font-bold text-ivory-70 hover:text-gold"><ArrowLeft size={16} /> Retainers</button>
            <PageHeader kicker={r.client || "Retainer"} title={r.name} sub={`${r.kind_label} · ${r.period} · ${r.billing === "advance" ? "invoiced at the start" : "invoiced at the end"}${r.end_date ? ` · ends ${date(r.end_date)}` : " · ongoing"}`}
              right={<div className="flex gap-2">
                {r.status !== "ended" && <Button size="sm" variant="quiet" onClick={() => setEdit(true)}>Change plan</Button>}
                {r.status === "active" && <Button size="sm" variant="quiet" onClick={async () => { await act("retainers.pause", { id }); toast("Paused from the next period"); q.refetch(); }}>Pause</Button>}
                {r.status === "paused" && <Button size="sm" onClick={async () => { await act("retainers.resume", { id }); q.refetch(); }}>Resume</Button>}
                {r.status !== "ended" && <Button size="sm" variant="quiet" onClick={async () => { try { const x = await act("retainers.close_period", { id }); toast(x.summary); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Close ended periods</Button>}
              </div>} />
            {r.pending_plan && <Card className="mb-3 text-[14px]">Plan change waiting: starts from the next period.</Card>}
            {c ? (
              <Card className="mb-4">
                <Kicker>{c.label} · this period</Kicker>
                {r.kind === "hours" ? <>
                  <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                    <Stat label="Included" value={hm(c.included)} gold={false} sub={c.borrowed ? `${hm(c.borrowed)} borrowed last period` : null} />
                    <Stat label="Carried in" value={hm(c.carried_in_minutes)} gold={false} />
                    <Stat label="Used" value={hm(c.used)} sub={c.adjustments ? `incl. ${hm(c.adjustments)} adjustments` : null} />
                    <Stat label="Left" value={hm(c.left)} alert={c.left === 0 && c.used > c.available} gold={false} />
                  </div>
                  <div className="mt-3"><Meter pct={p} alert={p >= 100} /></div>
                </> : <p className="mt-2">{hm(c.used)} logged this period.</p>}
              </Card>
            ) : <Card className="mb-4 text-ivory-70">No open period{r.status === "paused" ? " (paused)" : ""}.</Card>}
            <div className="grid gap-4 lg:grid-cols-2">
              <Card><Kicker>Period history</Kicker>
                <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[460px] text-[14px]"><thead className="text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="py-2">Period</th><th className="py-2 text-right">Used</th><th className="py-2 text-right">Carried</th><th className="py-2 text-right">Extra</th><th className="py-2 pl-4">Status</th></tr></thead>
                  <tbody>{r.periods.map((x) => (
                    <tr key={x.id} className="border-t border-hairline"><td className="py-2">{x.label}</td><td className="tnum py-2 text-right">{hm(x.used)}</td>
                      <td className="tnum py-2 text-right">{x.carried_out_minutes ? hm(x.carried_out_minutes) : "—"}</td>
                      <td className={cx("tnum py-2 text-right", x.overage_minutes ? "text-alert" : "")}>{x.overage_minutes ? hm(x.overage_minutes) : "—"}</td>
                      <td className="py-2 pl-4"><Chip tone={x.status === "open" ? "gold" : "muted"}>{titleCase(x.status)}</Chip></td></tr>))}</tbody></table></div></Card>
              <Card><Kicker>Invoices</Kicker>
                {!r.invoices.length ? <p className="mt-2 text-ivory-70">None yet.</p> : r.invoices.map((i) => (
                  <div key={i.id} className="flex items-center gap-2 border-t border-hairline py-2 first:border-0"><span className="min-w-0 flex-1 truncate">{i.number || "Draft"} · {i.title}</span>
                    <Chip tone={i.status === "paid" ? "gold" : "muted"}>{titleCase(i.status)}</Chip><span className="tnum font-bold text-gold">{inr(i.total_paise)}</span></div>))}
                <button onClick={() => nav(`/projects/${r.project_ids[0]}?tab=payments`)} className="mt-2 text-[14px] font-bold text-gold">Open the project</button></Card>
            </div>
            <Card className="mt-4"><Kicker>This period's time</Kicker>
              {!(r.entries || []).length ? <p className="mt-2 text-ivory-70">No time logged yet this period.</p> : (r.entries || []).map((e) => (
                <div key={e.id} className="flex gap-3 border-t border-hairline py-2 text-[14px] first:border-0"><span className="w-24 text-ivory-70">{date(e.date)}</span>
                  <span className="min-w-0 flex-1 truncate">{e.note || e.task || "—"}{e.adjustment && <span className="ml-1 text-[12px] text-ivory-35">(adjustment)</span>}</span>
                  <span className="text-ivory-70">{e.person}</span><span className="tnum w-16 text-right">{hm(e.minutes)}</span></div>))}</Card>
            {edit && <NewRetainer open edit={r} onClose={() => { setEdit(false); q.refetch(); }} />}
            <p className="mt-3 text-[13px] text-ivory-35">The client sees this period's statement in their portal{r.statement_entries_visible ? ", with the entries" : " (totals only)"}.</p>
          </div>
        );
      }}
    </Loadable>
  );
}
