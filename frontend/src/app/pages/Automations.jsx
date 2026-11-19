import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft, Clock, GitBranch, Play, Plus, Sparkles, Trash2, Zap } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { ago, dt, titleCase } from "../../lib/format";
import { useWs } from "../components/AppShell";
import { Button, Card, Chip, Empty, Field, Input, Kicker, Loadable, PageHeader, Select, Sheet, Tabs, Textarea, Toggle, cx, toast } from "../components/ui";

const nid = () => Math.random().toString(36).slice(2, 12);
const ACTION_LABEL = { send_email: "Send email", send_file: "Send client file", send_whatsapp: "Send WhatsApp", create_draft: "Create email draft", create_task: "Create task",
  add_tags: "Add tags", remove_tags: "Remove tags", move_stage: "Move to stage", archive: "Archive project", run_agent: "Run agent" };
const COND_LABEL = { tag_present: "Tag present", file_viewed: "File viewed", file_completed: "File completed", contract_signed: "Contract signed",
  questionnaire_submitted: "Questionnaire submitted", session_scheduled: "Session scheduled", session_no_show: "Client didn't show", task_completed: "Task completed",
  first_payment: "First payment received", paid_in_full: "Paid in full", budget_over: "Budget over X%", client_task_overdue: "Waiting on the client (overdue)" };

export default function Automations() {
  const { id } = useParams();
  return id ? <Flow id={id} /> : <List />;
}

function List() {
  const q = useAct("automations.list");
  const nav = useNavigate();
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState(false);
  async function build() {
    setBusy(true);
    try { const r = await act("agents.run", { agent: "automation_builder", instruction: ask }); toast(r.summary, "ai"); setAsk(""); q.refetch(); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <div>
      <PageHeader kicker="Automations" title="Rules that run" accent="the routine steps" sub="A trigger, then steps: actions, waits and yes/no conditions. Send steps can wait for your OK."
        right={<Button variant="primary" size="sm" icon={Plus} onClick={async () => { const a = await act("automations.save", { name: "New automation", trigger: { type: "lead_form.submitted" }, steps: [], active: false }); nav(`/automations/${a.id}`); }}>New automation</Button>} />
      <Card ai className="mb-5">
        <Kicker ai>Describe it</Kicker>
        <div className="mt-2 flex gap-2"><input className="ai min-w-0 flex-1 rounded-input border border-hairline bg-bg px-3.5 py-3 font-mono text-[14px] focus:border-teal focus:outline-none" value={ask} onChange={(e) => setAsk(e.target.value)}
          placeholder="If a proposal isn't opened in 3 days, remind me" /><Button variant="ai" busy={busy} disabled={!ask.trim()} onClick={build}>Draft it</Button></div>
        <p className="mt-2 text-[13px] text-ivory-70">The Automation builder drafts it switched off, so you can check it first.</p>
      </Card>
      <Loadable q={q} empty={<Empty title="No automations" />}>
        {(rows) => <div className="space-y-2">{rows.map((a) => (
          <Card key={a.id} className="flex flex-wrap items-center gap-3">
            <Zap size={17} className={a.active ? "text-gold" : "text-ivory-35"} />
            <button className="min-w-0 flex-1 text-left" onClick={() => nav(`/automations/${a.id}`)}><b className="block truncate">{a.name}</b>
              <span className="text-[13px] text-ivory-70">{titleCase((a.trigger?.type || "").replace(".", " "))} · {a.runs_active} running · {a.runs_total} runs{a.last_run ? ` · last ${ago(a.last_run)}` : ""}</span></button>
            {a.drafted_by && <Chip tone="teal"><Sparkles size={11} /> Drafted</Chip>}
            <Toggle on={a.active} onChange={async (v) => { try { await act("automations.toggle", { id: a.id, active: v }); q.refetch(); } catch (e) { toast(e.message, "error"); } }} />
          </Card>))}</div>}
      </Loadable>
    </div>
  );
}

function Flow({ id }) {
  const q = useAct("automations.get", { id });
  const meta = useAct("automations.meta");
  return <Loadable q={q}>{(a) => meta.data ? <FlowEditor a={a} meta={meta.data} reload={() => q.refetch()} /> : null}</Loadable>;
}

function FlowEditor({ a, meta, reload }) {
  const nav = useNavigate();
  const ws = useWs();
  const [f, setF] = useState(a);
  const [tab, setTab] = useState("build");
  const [edit, setEdit] = useState(null); // {path}
  const [test, setTest] = useState(null);
  const [dirty, setDirty] = useState(false);
  const runs = useAct("automations.runs", { automation_id: a.id });
  const set = (p) => { setF(p); setDirty(true); };
  async function save() {
    try { await act("automations.save", { id: a.id, name: f.name, trigger: f.trigger, steps: f.steps, project_types: f.project_types, active: f.active }); setDirty(false); toast("Saved. Runs already going keep their old steps."); reload(); }
    catch (e) { toast(e.message, "error"); }
  }
  function getList(path) { let cur = f.steps; for (let i = 0; i < path.length; i += 2) cur = cur[path[i]][path[i + 1]]; return cur; }
  function updateList(path, fn) {
    const steps = structuredClone(f.steps);
    let cur = steps; for (let i = 0; i < path.length; i += 2) cur = cur[path[i]][path[i + 1]];
    const out = fn(cur); cur.splice(0, cur.length, ...out);
    set({ ...f, steps });
  }
  function addStep(path, index, type) {
    const s = type === "wait" ? { id: nid(), type, wait: { kind: "time", minutes: 1440 } } : type === "condition" ? { id: nid(), type, cond: { kind: "file_viewed" }, yes: [], no: [] }
      : { id: nid(), type: "action", action: "create_task", title: "Follow up" };
    updateList(path, (l) => { const c = [...l]; c.splice(index, 0, s); return c; });
  }
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button onClick={() => nav("/automations")} className="grid h-11 w-11 place-items-center rounded-full hover:bg-panel" aria-label="Back"><ArrowLeft size={19} /></button>
        <input className="min-w-0 flex-1 bg-transparent text-[22px] font-extrabold focus:outline-none" value={f.name} onChange={(e) => set({ ...f, name: e.target.value })} />
        <Toggle on={f.active} onChange={(v) => set({ ...f, active: v })} label={f.active ? "On" : "Off"} />
        <Button size="sm" variant="quiet" icon={Play} onClick={async () => { try { setTest(await act("automations.test_run", { spec: { name: f.name, trigger: f.trigger, steps: f.steps } })); } catch (e) { toast(e.message, "error"); } }}>Test run</Button>
        <Button size="sm" variant="primary" disabled={!dirty} onClick={save}>Save</Button>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "build", label: "Steps" }, { value: "runs", label: "Runs", count: runs.data?.length }]} />
      {tab === "build" && (
        <div className="mx-auto max-w-2xl">
          <Card className="border-gold-deep">
            <Kicker>When this happens</Kicker>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <Select value={f.trigger.type} onChange={(e) => set({ ...f, trigger: { type: e.target.value } })} options={Object.entries(meta.triggers).map(([v, l]) => ({ value: v, label: l }))} />
              {["session.starts"].includes(f.trigger.type) && <Input inputMode="numeric" placeholder="Offset in minutes (negative = before)" value={f.trigger.offset_minutes ?? ""} onChange={(e) => set({ ...f, trigger: { ...f.trigger, offset_minutes: Number(e.target.value) || 0 } })} />}
              {["project.start_date", "project.end_date"].includes(f.trigger.type) && <Input inputMode="numeric" placeholder="Days after (negative = before)" value={f.trigger.offset_days ?? ""} onChange={(e) => set({ ...f, trigger: { ...f.trigger, offset_days: Number(e.target.value) || 0 } })} />}
              {f.trigger.type === "project.stage_changed" && <Select value={f.trigger.stage_id || ""} onChange={(e) => set({ ...f, trigger: { ...f.trigger, stage_id: e.target.value } })} options={[{ value: "", label: "Any stage" }, ...(ws.data?.stages || []).map((s) => ({ value: s.id, label: s.name }))]} />}
              {f.trigger.type === "tag.added" && <Input placeholder="Tag" value={f.trigger.tag || ""} onChange={(e) => set({ ...f, trigger: { ...f.trigger, tag: e.target.value } })} />}
              {["budget.threshold_reached", "retainer.usage_threshold"].includes(f.trigger.type) && <Input inputMode="numeric" placeholder="At % (e.g. 80)" value={f.trigger.pct ?? ""} onChange={(e) => set({ ...f, trigger: { ...f.trigger, pct: e.target.value === "" ? null : Number(e.target.value) } })} />}
            </div>
            <div className="mt-2"><Select value={(f.project_types || [])[0] || ""} onChange={(e) => set({ ...f, project_types: e.target.value ? [e.target.value] : [] })}
              options={[{ value: "", label: "For every project type" }, ...(ws.data?.settings?.project_types || []).map((t) => ({ value: t, label: `Only ${t}` }))]} /></div>
          </Card>
          <Steps list={f.steps} path={[]} onAdd={addStep} onEdit={(p) => setEdit(p)} onRemove={(path, i) => updateList(path, (l) => l.filter((_, j) => j !== i))} />
          <p className="mt-3 text-center text-[13px] text-ivory-35">{meta.note}</p>
          {test && (
            <Card className="mt-4"><Kicker>Test run on a sample project (nothing was sent)</Kicker>
              <ol className="mt-2 list-decimal pl-5 text-[14px]">{test.log.map((l, i) => <li key={i}>{l.text}</li>)}</ol></Card>
          )}
        </div>
      )}
      {tab === "runs" && (
        <Loadable q={runs} empty={<Empty title="No runs yet" line="Runs show up here when the trigger happens on a project." />}>
          {(rows) => <div className="space-y-2">{rows.map((r) => (
            <Card key={r.id}>
              <div className="flex flex-wrap items-center gap-2"><button className="font-bold hover:text-gold" onClick={() => nav(`/projects/${r.project_id}`)}>Project run</button><Chip tone={r.status === "failed" ? "alert" : r.status === "done" ? "gold" : "muted"}>{titleCase(r.status)}</Chip>
                <span className="ml-auto text-[12px] text-ivory-35">{dt(r.created_at)}</span>
                {["waiting", "waiting_approval", "running"].includes(r.status) && <>
                  <Button size="sm" variant="quiet" onClick={async () => { try { await act("automations.skip_step", { run_id: r.id }); runs.refetch(); } catch (e) { toast(e.message, "error"); } }}>Skip step</Button>
                  <Button size="sm" variant="quiet" onClick={async () => { await act("automations.cancel_run", { run_id: r.id }); runs.refetch(); }}>Cancel</Button></>}</div>
              <ol className="mt-2 space-y-0.5 text-[13px] text-ivory-70">{(r.log || []).map((l, i) => <li key={i}><span className={l.status === "failed" ? "text-alert" : ""}>{l.text}</span></li>)}</ol>
            </Card>))}</div>}
        </Loadable>
      )}
      {edit && <StepSheet f={f} path={edit} onClose={() => setEdit(null)} getList={getList} updateList={updateList} />}
    </div>
  );
}

function Steps({ list, path, onAdd, onEdit, onRemove }) {
  return (
    <div className="flex flex-col items-stretch">
      <Plus3 onAdd={(t) => onAdd(path, 0, t)} />
      {list.map((s, i) => (
        <div key={s.id}>
          {s.type === "condition" ? (
            <div>
              <StepCard s={s} onClick={() => onEdit([...path, i])} onRemove={() => onRemove(path, i)} />
              <div className="mt-2 grid grid-cols-2 gap-3 border-l border-r border-dashed border-hairline px-2">
                {["yes", "no"].map((br) => (
                  <div key={br}><div className={cx("text-center text-[12px] font-bold uppercase tracking-[0.16em]", br === "yes" ? "text-gold" : "text-ivory-35")}>{br}</div>
                    <Steps list={s[br] || []} path={[...path, i, br]} onAdd={onAdd} onEdit={onEdit} onRemove={onRemove} /></div>
                ))}
              </div>
            </div>
          ) : <StepCard s={s} onClick={() => onEdit([...path, i])} onRemove={() => onRemove(path, i)} />}
          <Plus3 onAdd={(t) => onAdd(path, i + 1, t)} />
        </div>
      ))}
    </div>
  );
}

function Plus3({ onAdd }) {
  const [o, setO] = useState(false);
  return (
    <div className="flex flex-col items-center py-1">
      <span className="h-3 w-px bg-hairline" />
      {o ? <div className="flex gap-1">{[["action", "Action"], ["wait", "Wait"], ["condition", "Condition"]].map(([t, l]) => <button key={t} onClick={() => { onAdd(t); setO(false); }} className="h-8 rounded-full border border-hairline px-3 text-[12px] font-bold">{l}</button>)}</div>
        : <button onClick={() => setO(true)} className="grid h-7 w-7 place-items-center rounded-full border border-hairline text-ivory-70 hover:border-gold hover:text-gold" aria-label="Add step"><Plus size={14} /></button>}
      <span className="h-3 w-px bg-hairline" />
    </div>
  );
}

function StepCard({ s, onClick, onRemove }) {
  const ai = s.action === "run_agent";
  const label = s.type === "wait" ? (s.wait.kind === "time" ? `Wait ${fmtMin(s.wait.minutes)}` : `Wait until: ${titleCase(s.wait.event?.replace(".", " "))} (up to ${fmtMin(s.wait.limit_minutes || 4320)})`)
    : s.type === "condition" ? `If: ${(COND_LABEL[s.cond.kind] || s.cond.kind).replace("X%", `${s.cond.pct ?? 100}%`)}${s.cond.tag ? ` "${s.cond.tag}"` : ""}` : `${ACTION_LABEL[s.action]}${s.title ? `: ${s.title}` : ""}${s.agent ? `: ${titleCase(s.agent)}` : ""}`;
  const Icon = s.type === "wait" ? Clock : s.type === "condition" ? GitBranch : ai ? Sparkles : Zap;
  return (
    <div className={cx("flex items-center gap-3 rounded-card border bg-panel p-3", ai ? "ai border-teal/50" : "border-hairline")}>
      <Icon size={17} className={ai ? "text-teal" : "text-gold"} />
      <button onClick={onClick} className="min-w-0 flex-1 text-left font-bold">{label}{s.approve && <Chip tone="teal" className="ml-2">Your OK first</Chip>}</button>
      <button onClick={onRemove} className="grid h-9 w-9 place-items-center text-ivory-35 hover:text-alert" aria-label="Remove"><Trash2 size={15} /></button>
    </div>
  );
}
const fmtMin = (m) => (m % 1440 === 0 ? `${m / 1440} day${m === 1440 ? "" : "s"}` : m % 60 === 0 ? `${m / 60} h` : `${m} min`);

function StepSheet({ f, path, onClose, getList, updateList }) {
  const list = getList(path.slice(0, -1));
  const i = path[path.length - 1];
  const [s, setS] = useState(structuredClone(list[i]));
  const emails = useAct("templates.list", { kind: "email" });
  const files = useAct("templates.list", { kind: "file" });
  const ws = useWs();
  function done() { updateList(path.slice(0, -1), (l) => l.map((x, j) => (j === i ? s : x))); onClose(); }
  return (
    <Sheet open onClose={onClose} title={s.type === "wait" ? "Wait" : s.type === "condition" ? "Condition" : "Action"} ai={s.action === "run_agent"}>
      <div className="space-y-3">
        {s.type === "action" && <>
          <Select value={s.action} onChange={(e) => setS({ ...s, action: e.target.value })} options={Object.entries(ACTION_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          {["send_email", "create_draft"].includes(s.action) && <Select value={s.template_id || ""} onChange={(e) => setS({ ...s, template_id: e.target.value })} options={[{ value: "", label: "Email template…" }, ...(emails.data || []).map((t) => ({ value: t.id, label: t.name }))]} />}
          {s.action === "send_file" && <>
            <Select value={s.file_template_id || ""} onChange={(e) => setS({ ...s, file_template_id: e.target.value })} options={[{ value: "", label: "Client file template…" }, ...(files.data || []).map((t) => ({ value: t.id, label: t.name }))]} />
            <Select value={s.email_template_id || ""} onChange={(e) => setS({ ...s, email_template_id: e.target.value })} options={[{ value: "", label: "Email to send with it…" }, ...(emails.data || []).map((t) => ({ value: t.id, label: t.name }))]} /></>}
          {s.action === "send_whatsapp" && <Select value={s.wa_template || "general_update"} onChange={(e) => setS({ ...s, wa_template: e.target.value })} options={["general_update", "file_link", "payment_reminder", "session_reminder"]} />}
          {s.action === "create_task" && <><Field label="Task"><Input value={s.title || ""} onChange={(e) => setS({ ...s, title: e.target.value })} /></Field>
            <Field label="Due after (minutes)"><Input inputMode="numeric" value={s.due_minutes ?? 1440} onChange={(e) => setS({ ...s, due_minutes: Number(e.target.value) || 0 })} /></Field></>}
          {["add_tags", "remove_tags"].includes(s.action) && <Input placeholder="Tags, separated by commas" value={(s.tags || []).join(", ")} onChange={(e) => setS({ ...s, tags: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />}
          {s.action === "move_stage" && <Select value={s.stage_id || ""} onChange={(e) => setS({ ...s, stage_id: e.target.value, stage_key: undefined })} options={[{ value: "", label: s.stage_key ? titleCase(s.stage_key) : "Stage…" }, ...(ws.data?.stages || []).map((x) => ({ value: x.id, label: x.name }))]} />}
          {s.action === "archive" && <p className="text-[13px] text-ivory-70">Ends the automation, so it must be the last step.</p>}
          {s.action === "run_agent" && <>
            <Select value={s.agent || "lead"} onChange={(e) => setS({ ...s, agent: e.target.value })} options={["lead", "followup", "proposal", "collections", "meeting"].map((x) => ({ value: x, label: `${titleCase(x)} agent` }))} />
            <Textarea ai value={s.instruction || ""} onChange={(e) => setS({ ...s, instruction: e.target.value })} placeholder="What should the agent do?" /></>}
          {["send_email", "send_file", "send_whatsapp"].includes(s.action) && <Toggle ai on={!!s.approve} onChange={(v) => setS({ ...s, approve: v })} label="Approve before sending" />}
        </>}
        {s.type === "wait" && <>
          <Select value={s.wait.kind} onChange={(e) => setS({ ...s, wait: { ...s.wait, kind: e.target.value } })} options={[{ value: "time", label: "Wait for a time" }, { value: "event", label: "Wait until something happens" }]} />
          {s.wait.kind === "time" ? <Field label="How long (days)"><Input inputMode="decimal" value={(s.wait.minutes || 0) / 1440} onChange={(e) => setS({ ...s, wait: { ...s.wait, minutes: Math.max(1, Math.round(Number(e.target.value) * 1440)) } })} /></Field> : <>
            <Select value={s.wait.event || ""} onChange={(e) => setS({ ...s, wait: { ...s.wait, event: e.target.value } })} options={[{ value: "", label: "Event…" }, ...["session.scheduled", "file.completed", "questionnaire.submitted", "payment.first_paid", "invoice.paid_in_full", "contract.signed", "contract.fully_signed", "tag.added"].map((x) => ({ value: x, label: titleCase(x.replace(".", " ")) }))]} />
            <Field label="Give up after (days)"><Input inputMode="decimal" value={(s.wait.limit_minutes || 4320) / 1440} onChange={(e) => setS({ ...s, wait: { ...s.wait, limit_minutes: Math.max(1, Math.round(Number(e.target.value) * 1440)) } })} /></Field></>}
        </>}
        {s.type === "condition" && <>
          <Select value={s.cond.kind} onChange={(e) => setS({ ...s, cond: { ...s.cond, kind: e.target.value } })} options={Object.entries(COND_LABEL).map(([v, l]) => ({ value: v, label: l }))} />
          {s.cond.kind === "tag_present" && <Input placeholder="Tag" value={s.cond.tag || ""} onChange={(e) => setS({ ...s, cond: { ...s.cond, tag: e.target.value } })} />}
          {s.cond.kind === "budget_over" && <Input inputMode="numeric" placeholder="%" value={s.cond.pct ?? 100} onChange={(e) => setS({ ...s, cond: { ...s.cond, pct: Number(e.target.value) || 0 } })} />}
        </>}
        <Button variant="primary" className="w-full" onClick={done}>Done</Button>
      </div>
    </Sheet>
  );
}
