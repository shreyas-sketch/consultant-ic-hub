import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft, Bot, Plus, Trash2 } from "lucide-react";
import { act, useAct } from "@/shared/api";
import { date, hm, inr, titleCase } from "@/shared/lib/format";
import { ProjectSelect } from "@/app/widgets/billing";
import { Button, Card, Chip, Empty, Field, Input, Kicker, Loadable, MoneyInput, PageHeader, Segmented, Select, Sheet, Textarea, cx, toast, useAutosave } from "@/app/ui";

export default function Estimates() {
  const { id } = useParams();
  return id ? <Builder id={id} /> : <List />;
}

function List() {
  const q = useAct("estimates.list", {});
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ project_id: "", text: "" });
  const [busy, setBusy] = useState(false);
  return (
    <div>
      <PageHeader kicker="Estimates" title="Price it properly," accent="then quote" sub="Work out price, cost and margin before anything goes to the client. The client only ever sees the quote."
        right={<Button variant="primary" icon={Plus} onClick={() => setOpen(true)}>New estimate</Button>} />
      <Loadable q={q} empty={<Empty title="No estimates yet" line="Start one from scratch, or describe the work and let the agent draft it." />}>
        {(rows) => (
          <div className="overflow-x-auto rounded-card border border-hairline">
            <table className="w-full min-w-[620px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Estimate</th><th className="p-3">Project</th><th className="p-3">Status</th><th className="p-3 text-right">Time</th><th className="p-3 text-right">Price</th><th className="p-3 text-right">Margin</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id} className="cursor-pointer border-t border-hairline hover:bg-panel" onClick={() => nav(`/estimates/${r.id}`)}>
                  <td className="p-3 font-bold">{r.name} <span className="text-[12px] font-medium text-ivory-35">v{r.version}</span></td><td className="max-w-[200px] truncate p-3">{r.project}</td>
                  <td className="p-3"><Chip tone={r.status === "converted" ? "gold" : "muted"}>{r.status === "converted" ? "Accepted" : titleCase(r.status)}</Chip></td>
                  <td className="tnum p-3 text-right">{hm(r.minutes)}</td><td className="tnum p-3 text-right text-gold">{inr(r.price_paise)}</td>
                  <td className="tnum p-3 text-right">{r.margin_bp === undefined ? "—" : r.has_cost ? `${Math.round(r.margin_bp / 100)}%` : "—"}</td></tr>))}</tbody></table>
          </div>
        )}
      </Loadable>
      <Sheet open={open} onClose={() => setOpen(false)} title="New estimate">
        <div className="space-y-3">
          <ProjectSelect value={f.project_id} onChange={(v) => setF({ ...f, project_id: v })} />
          <Field label="Describe the work (optional)" hint="e.g. a 6-week pricing study, two days a week. The agent drafts phases from your rate card and states its assumptions.">
            <Textarea value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Button disabled={!f.project_id} busy={busy} onClick={async () => { setBusy(true); try { const e = await act("estimates.create", { project_id: f.project_id }); nav(`/estimates/${e.id}`); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); } }}>Blank</Button>
            <Button variant="ai" icon={Bot} disabled={!f.project_id || !f.text.trim()} busy={busy} onClick={async () => { setBusy(true); try { const e = await act("estimates.draft_from_text", f); toast(e.summary, "ai"); nav(`/estimates/${e.id}`); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); } }}>Draft it for me</Button>
          </div>
        </div>
      </Sheet>
    </div>
  );
}

const UNITS = [["hour", "hours"], ["day", "days"], ["week", "weeks"], ["flat", "fixed"], ["session", "sessions"], ["item", "items"]];

function Builder({ id }) {
  const q = useAct("estimates.get", { id });
  const nav = useNavigate();
  const [e, setE] = useState(null);
  const [send, setSend] = useState(false);
  useEffect(() => { if (q.data) setE(q.data); }, [q.data]);
  const draft = e?.status === "draft";
  const save = async (x) => {
    if (!x || x.status !== "draft") return;
    try {
      const r = await act("estimates.update", { id, name: x.name, phases: x.phases, contingency_pct: (x.contingency_bp || 0) / 100, discount_paise: x.discount_paise || 0, assumptions: x.assumptions });
      setE((cur) => ({ ...cur, totals: r.totals, phases: r.phases.map((p, i) => ({ ...p, lines: p.lines.map((l, j) => ({ ...(cur.phases[i]?.lines[j] || {}), ...l })) })) }));
    } catch (err) { toast(err.message, "error"); }
  };
  useAutosave(e, save, 900);
  if (!e) return <Loadable q={q}>{() => null}</Loadable>;
  const t = e.totals;
  const upd = (pi, li, k, v) => setE({ ...e, phases: e.phases.map((p, i) => i !== pi ? p : { ...p, lines: p.lines.map((l, j) => j !== li ? l : { ...l, [k]: v }) }) });
  const totals = (
    <Card className="space-y-2">
      <Kicker>Totals</Kicker>
      <Row k="Price to client" v={inr(t.price)} gold />
      {t.contingency > 0 && <Row k="incl. contingency" v={inr(t.contingency)} />}
      {t.discount > 0 && <Row k="incl. discount" v={`-${inr(t.discount)}`} />}
      <Row k="Time" v={`${hm(t.minutes)}`} />
      {t.cost_paise !== undefined && t.has_cost ? <>
        <Row k="Cost to you" v={inr(t.cost_paise)} />
        <Row k="Margin" v={`${inr(t.margin_paise)} · ${Math.round(t.margin_bp / 100)}%`} alert={t.below_target_margin} />
        {t.below_target_margin && <p className="text-[13px] text-alert">Below your target margin of {Math.round(t.target_margin_bp / 100)}%.</p>}
      </> : <>
        <Row k="Effective hourly rate" v={t.effective_hourly_paise ? `${inr(t.effective_hourly_paise)}/h` : "—"} gold />
        {e.standard_hourly_paise ? <p className="text-[13px] text-ivory-70">Your standard rate is {inr(e.standard_hourly_paise)}/h ({e.effective_vs_standard_pct}% of it).</p> : null}
      </>}
    </Card>
  );
  return (
    <div className="pb-24 lg:pb-0">
      <button onClick={() => nav("/estimates")} className="mb-3 inline-flex items-center gap-1 text-[14px] font-bold text-ivory-70 hover:text-gold"><ArrowLeft size={16} /> Estimates</button>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input value={e.name} disabled={!draft} onChange={(ev) => setE({ ...e, name: ev.target.value })} className="max-w-md text-[18px] font-extrabold" aria-label="Estimate name" />
        <Chip tone={e.status === "converted" ? "gold" : "muted"}>v{e.version} · {e.status === "converted" ? "Accepted" : titleCase(e.status)}</Chip>
        <span className="text-[14px] text-ivory-70">{e.project}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          {draft && <Button variant="primary" onClick={async () => { try { await save(e); const r = await act("estimates.finalise", { id }); setE(r); toast("Final. Now make the quote."); } catch (err) { toast(err.message, "error"); } }}>Make final</Button>}
          {e.status === "final" && <Button variant="primary" onClick={() => setSend(true)}>Quote or proposal</Button>}
          {e.status !== "draft" && <Button variant="quiet" onClick={async () => { const n = await act("estimates.new_version", { id }); nav(`/estimates/${n.id}`); }}>New version</Button>}
        </div>
      </div>
      {e.assumptions && <Card ai className="mb-4"><Kicker ai>Assumptions</Kicker><p className="mt-1 whitespace-pre-line text-[14px] text-ivory-70">{e.assumptions}</p></Card>}
      <div className="lg:grid lg:grid-cols-[1fr_320px] lg:gap-6">
        <div className="min-w-0 space-y-3">
          {e.phases.map((ph, pi) => (
            <Card key={ph.id || pi}>
              <div className="mb-2 flex items-center gap-2">
                <div className="min-w-0 flex-1"><Input value={ph.name} disabled={!draft} aria-label="Phase name" onChange={(ev) => setE({ ...e, phases: e.phases.map((p, i) => i === pi ? { ...p, name: ev.target.value } : p) })} className="font-bold" /></div>
                <span className="tnum shrink-0 whitespace-nowrap pl-2 font-bold text-gold">{inr(ph.price_paise)}</span>
                {draft && <button className="shrink-0 p-1" aria-label="Remove phase" onClick={() => setE({ ...e, phases: e.phases.filter((_, i) => i !== pi) })}><Trash2 size={16} className="text-ivory-35" /></button>}
              </div>
              {ph.lines.map((l, li) => (
                <div key={l.id || li} className="grid grid-cols-[60px_96px_1fr] gap-2 border-t border-hairline py-2 md:grid-cols-[1fr_64px_100px_130px_104px_28px]">
                  <Input value={l.label || ""} disabled={!draft} aria-label="Line" onChange={(ev) => upd(pi, li, "label", ev.target.value)} className="col-span-3 md:col-span-1" />
                  <Input value={l.qty} disabled={!draft} inputMode="decimal" aria-label="Quantity" onChange={(ev) => upd(pi, li, "qty", ev.target.value)} />
                  {l.kind === "expense" ? <span className="self-center text-[13px] text-ivory-35">expense</span>
                    : <Select value={l.unit} disabled={!draft} onChange={(ev) => upd(pi, li, "unit", ev.target.value)} options={UNITS.map(([v, lb]) => ({ value: v, label: lb }))} />}
                  {l.kind === "expense"
                    ? <MoneyInput paise={l.cost_paise} disabled={!draft} onChange={(v) => upd(pi, li, "cost_paise", v)} aria-label="Cost" />
                    : <MoneyInput paise={l.rate_paise} disabled={!draft} onChange={(v) => upd(pi, li, "rate_paise", v)} aria-label="Rate" />}
                  <span className="tnum col-span-2 self-center text-[14px] font-bold md:col-span-1 md:text-right">{inr(l.price_paise)}</span>
                  {draft ? <button className="justify-self-end" aria-label="Remove line" onClick={() => setE({ ...e, phases: e.phases.map((p, i) => i !== pi ? p : { ...p, lines: p.lines.filter((_, j) => j !== li) }) })}><Trash2 size={15} className="text-ivory-35" /></button> : <span />}
                </div>
              ))}
              {draft && <div className="mt-2 flex gap-3 text-[14px] font-bold text-gold">
                <button onClick={() => setE({ ...e, phases: e.phases.map((p, i) => i !== pi ? p : { ...p, lines: [...p.lines, { kind: "labour", label: "Consulting", qty: 1, unit: "day", rate_paise: null }] }) })}>+ Work</button>
                <button onClick={() => setE({ ...e, phases: e.phases.map((p, i) => i !== pi ? p : { ...p, lines: [...p.lines, { kind: "expense", label: "Travel", qty: 1, cost_paise: 0, markup_bp: 0 }] }) })}>+ Expense</button></div>}
            </Card>
          ))}
          {draft && <Button icon={Plus} onClick={() => setE({ ...e, phases: [...e.phases, { name: `Phase ${e.phases.length + 1}`, lines: [] }] })}>Add a phase</Button>}
          <Card className="grid gap-3 md:grid-cols-2">
            <Field label="Contingency %"><Input inputMode="decimal" disabled={!draft} value={(e.contingency_bp || 0) / 100} onChange={(ev) => setE({ ...e, contingency_bp: Math.round(Number(ev.target.value || 0) * 100) })} /></Field>
            <Field label="Discount"><MoneyInput paise={e.discount_paise || 0} disabled={!draft} onChange={(v) => setE({ ...e, discount_paise: v })} /></Field>
          </Card>
        </div>
        <aside className="hidden lg:block">{totals}</aside>
      </div>
      <div className="fixed inset-x-0 bottom-[64px] z-20 border-t border-hairline bg-ink/95 py-3 pl-4 pr-24 backdrop-blur lg:hidden">
        <div className="flex items-center justify-between"><span className="text-[13px] text-ivory-70">Price · {hm(t.minutes)}</span><span className="tnum text-[20px] font-extrabold text-gold">{inr(t.price)}</span></div>
        {t.has_cost && t.margin_bp !== undefined && <div className={cx("text-[13px]", t.below_target_margin ? "text-alert" : "text-ivory-70")}>Margin {Math.round(t.margin_bp / 100)}%</div>}
      </div>
      <SendSheet open={send} onClose={() => setSend(false)} e={e} />
    </div>
  );
}

function Row({ k, v, gold, alert }) {
  return <div className="flex items-baseline justify-between gap-2 text-[14px]"><span className="text-ivory-70">{k}</span><span className={cx("tnum font-bold", alert ? "text-alert" : gold ? "text-gold" : "")}>{v}</span></div>;
}

function SendSheet({ open, onClose, e }) {
  const nav = useNavigate();
  const [detail, setDetail] = useState("phase");
  const [kind, setKind] = useState("quote");
  const [days, setDays] = useState(14);
  const [busy, setBusy] = useState(false);
  return (
    <Sheet open={open} onClose={onClose} title="Send to the client">
      <div className="space-y-4">
        <Field label="As"><Segmented value={kind} onChange={setKind} options={[{ value: "quote", label: "One-page quote" }, { value: "proposal", label: "Full proposal" }]} /></Field>
        <Field label="The client sees" hint="Cost and margin are never shown."><Segmented value={detail} onChange={setDetail} options={[{ value: "total", label: "One total" }, { value: "phase", label: "Per phase" }, { value: "line", label: "Every line" }]} /></Field>
        {kind === "quote" && <Field label="Valid for (days)"><Input inputMode="numeric" value={days} onChange={(ev) => setDays(ev.target.value)} /></Field>}
        <Button variant="primary" className="w-full" busy={busy} onClick={async () => {
          setBusy(true);
          try {
            const f = kind === "quote" ? await act("estimates.to_quote", { id: e.id, detail, valid_days: Number(days) || 14 }) : await act("estimates.to_proposal", { id: e.id, detail });
            toast("Ready. Check it, then send.");
            nav(`/files/${f.id}`);
          } catch (err) { toast(err.message, "error"); } finally { setBusy(false); }
        }}>Make it</Button>
        <p className="text-[13px] text-ivory-35">When the client accepts, the project gets a budget, tasks with estimates{kind === "quote" ? " and the invoice" : ""}.</p>
      </div>
    </Sheet>
  );
}

export const _ = date;
