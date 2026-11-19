import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { Archive, Bot, Copy, ExternalLink, FileText, Mail, MessageCircle, Plus, Sparkles, Video } from "lucide-react";
import { act, useAct, useRefresh } from "../../lib/api";
import { ago, date, dt, fromDateInput, hm, inr, istDateInput, plural, titleCase } from "../../lib/format";
import { BudgetBar, ClientTaskSheet, LogTimeSheet, TimeInvoiceSheet } from "../components/addons";
import { useWs } from "../components/AppShell";
import {
  AgentChip, Button, Card, Chip, Empty, ErrorCard, Field, Input, Kicker, MoneyInput, Segmented, Select, Sheet, SkeletonList, Tabs, Textarea, Toggle, cx, toast,
} from "../components/ui";

export default function Project() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "activity";
  const q = useAct("projects.get", { id });
  const ws = useWs();
  const refresh = useRefresh();
  const nav = useNavigate();
  const [archiveOpen, setArchiveOpen] = useState(false);
  if (q.isLoading) return <SkeletonList rows={6} />;
  if (q.isError) return <ErrorCard error={q.error} retry={() => q.refetch()} />;
  const p = q.data;
  const stages = ws.data?.stages || [];
  const c = p.contacts[0];
  const reload = () => refresh("projects", "threads", "invoices", "files", "payments", "tasks");
  async function moveStage(sid) {
    try { await act("projects.move_stage", { id, stage_id: sid }); reload(); } catch (e) { toast(e.message, "error"); }
  }
  const openTasks = p.tasks.filter((t) => !t.done && t.audience !== "client");
  const nextSession = p.sessions.find((s) => s.status === "booked" && new Date(s.start) > new Date());
  const due = p.invoices.filter((i) => ["sent", "partially_paid"].includes(i.status)).reduce((a, i) => a + (i.totals?.due || 0), 0);
  const running = p.runs.filter((r) => ["running", "waiting", "waiting_approval"].includes(r.status));

  return (
    <div>
      <div className="mb-4 rise">
        <div className="kicker">{p.type || "Project"}{p.source ? ` · ${p.source}` : ""}</div>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-[26px] font-extrabold tracking-[-0.02em]">{p.name}</h1>
          {p.booked && <Chip tone="gold">Booked</Chip>}
          {p.archived && <Chip>Archived{p.archived_reason ? `: ${p.archived_reason}` : ""}</Chip>}
          {p.waiting_on_client && <button onClick={() => setSp({ tab: "tasks" })}><Chip>Waiting on client</Chip></button>}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-ivory-70">
          {c && <button onClick={() => nav(`/contacts/${c.id}`)} className="font-bold text-ivory hover:text-gold">{c.name}{c.company ? ` · ${c.company}` : ""}</button>}
          <select value={p.stage_id} onChange={(e) => moveStage(e.target.value)} className="h-9 rounded-full border border-hairline bg-panel px-3 text-[14px] font-bold">
            {stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          {p.value_paise !== null && p.value_paise > 0 && <span className="tnum font-bold text-gold">{inr(p.value_paise)}</span>}
          <div className="ml-auto flex gap-2">
            <Button size="sm" variant="ai" icon={Bot} onClick={async () => { try { const r = await act("agents.run", { agent: "proposal", project_id: id }); toast(r.summary, "ai"); reload(); } catch (e) { toast(e.message, "error"); } }}>Draft proposal</Button>
            {!p.archived ? <Button size="sm" variant="quiet" icon={Archive} onClick={() => setArchiveOpen(true)}>Archive</Button> :
              <Button size="sm" variant="quiet" onClick={async () => { await act("projects.unarchive", { id }); reload(); }}>Unarchive</Button>}
          </div>
        </div>
      </div>

      <div className="lg:grid lg:grid-cols-[1fr_320px] lg:gap-6">
        <div className="min-w-0">
          <Tabs value={tab} onChange={(t) => setSp({ tab: t })} tabs={[
            { value: "activity", label: "Activity" }, { value: "files", label: "Files", count: p.files.length },
            { value: "tasks", label: "Tasks", count: openTasks.length }, { value: "time", label: "Time" }, { value: "budget", label: "Budget" },
            { value: "payments", label: "Payments", count: p.invoices.length },
            { value: "notes", label: "Notes", count: p.notes.length }, { value: "details", label: "Details" }]} />
          {tab === "activity" && (
            <>
              {openTasks.length > 0 && <details className="mb-3 rounded-card border border-hairline bg-panel p-3 lg:hidden"><summary className="font-bold">{plural(openTasks.length, "open task")}</summary>
                <TaskList tasks={openTasks} onChange={reload} /></details>}
              <Composer p={p} onSent={reload} />
              <Activity items={p.activity} />
            </>
          )}
          {tab === "files" && <FilesTab p={p} onChange={reload} />}
          {tab === "tasks" && <TasksTab p={p} onChange={reload} />}
          {tab === "time" && <TimeTab p={p} onChange={reload} />}
          {tab === "budget" && <BudgetTab p={p} onChange={reload} />}
          {tab === "payments" && <PaymentsTab p={p} onChange={reload} />}
          {tab === "notes" && <NotesTab p={p} onChange={reload} />}
          {tab === "details" && <DetailsTab p={p} onChange={reload} />}
        </div>
        <aside className="mt-6 hidden space-y-4 lg:mt-0 lg:block">
          <Card><Kicker>Open tasks</Kicker>{openTasks.length ? <TaskList tasks={openTasks} onChange={reload} /> : <p className="mt-2 text-[14px] text-ivory-70">None.</p>}</Card>
          <Card><Kicker>Next session</Kicker>{nextSession ? <div className="mt-2"><b>{nextSession.title}</b><div className="text-[14px] text-ivory-70">{dt(nextSession.start)}</div>
            {nextSession.meet_link && <a className="mt-1 inline-flex items-center gap-1 text-[14px] font-bold text-gold" href={nextSession.meet_link} target="_blank" rel="noreferrer"><Video size={14} /> Join link</a>}</div>
            : <p className="mt-2 text-[14px] text-ivory-70">Nothing booked.</p>}</Card>
          <Card><Kicker>Payments</Kicker><div className="mt-2 text-[14px] text-ivory-70">Due: <b className="text-gold">{inr(due)}</b></div></Card>
          {p.budget && <Card><Kicker>Budget</Kicker><div className="mt-2"><BudgetBar b={p.budget} /></div>
            <button className="mt-2 text-[13px] font-bold text-gold" onClick={() => setSp({ tab: "budget" })}>Details</button></Card>}
          {p.portal_url && <Card><Kicker>Client portal</Kicker><PortalBox p={p} onChange={reload} /></Card>}
          <Card><Kicker>Automations running</Kicker>{running.length ? running.map((r) => <div key={r.id} className="mt-2 text-[14px]"><b>{r.name}</b> <span className="text-ivory-35">{r.status.replace("_", " ")}</span></div>) : <p className="mt-2 text-[14px] text-ivory-70">None right now.</p>}
            <WhyButton p={p} /></Card>
        </aside>
      </div>
      <ArchiveSheet open={archiveOpen} onClose={() => setArchiveOpen(false)} p={p} reasons={ws.data?.settings?.lost_reasons || []} onDone={reload} />
    </div>
  );
}

function PortalBox({ p, onChange }) {
  return (
    <div className="mt-2 space-y-2 text-[14px]">
      <div className="flex items-center gap-2"><span className="truncate text-ivory-70">{p.portal_url}</span>
        <button onClick={() => { navigator.clipboard?.writeText(p.portal_url); toast("Link copied"); }} aria-label="Copy"><Copy size={14} /></button></div>
      <Toggle on={p.portal_link_on} onChange={async (v) => { await act("projects.update", { id: p.id, portal_link_on: v }); onChange(); }} label="Include the portal link in files and emails" />
    </div>
  );
}

function WhyButton({ p }) {
  const autos = useAct("automations.list");
  const [res, setRes] = useState(null);
  const [aid, setAid] = useState("");
  return (
    <div className="mt-3 border-t border-hairline pt-3">
      <div className="text-[13px] font-bold text-ivory-70">Why didn't this run?</div>
      <div className="mt-1 flex gap-2">
        <select className="min-w-0 flex-1 rounded-input border border-hairline bg-panel px-2 py-2 text-[13px]" value={aid} onChange={(e) => setAid(e.target.value)}>
          <option value="">Pick an automation</option>{(autos.data || []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <Button size="sm" disabled={!aid} onClick={async () => setRes(await act("automations.why", { automation_id: aid, project_id: p.id }))}>Check</Button>
      </div>
      {res && <p className="mt-2 text-[14px]">{res.text}</p>}
    </div>
  );
}

function actorLabel(a) {
  if (!a) return "";
  if (a.startsWith("agent:")) return `${titleCase(a.slice(6))} agent`;
  if (a.startsWith("automation:")) return "Automation";
  if (a === "client") return "Client";
  if (a.startsWith("system")) return "";
  return "";
}

function Activity({ items }) {
  if (!items.length) return <p className="mt-4 text-ivory-70">Nothing yet.</p>;
  return (
    <div className="mt-4 space-y-0">
      {items.map((a) => {
        const who = actorLabel(a.actor);
        const ai = a.actor?.startsWith("agent:");
        return (
          <div key={a.id} className="flex gap-3 border-l border-hairline py-2.5 pl-4">
            <span className={cx("-ml-[21px] mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border-2 border-bg", ai ? "bg-teal" : a.client_visible ? "bg-gold" : "bg-hairline")} />
            <div className="min-w-0 flex-1">
              <div className="text-[14px]">{who && <b className={ai ? "text-teal" : "text-ivory-70"}>{who}: </b>}{a.text}</div>
              {a.meta?.changes?.length > 0 && <ul className="mt-1 list-disc pl-5 text-[13px] text-ivory-70">{a.meta.changes.map((x, i) => <li key={i}>{x}</li>)}</ul>}
              <div className="text-[12px] text-ivory-35">{dt(a.at)}{a.client_visible ? " · client can see this" : ""}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Composer({ p, onSent }) {
  const thread = useAct("threads.get", { project_id: p.id });
  const [ch, setCh] = useState(p.contacts[0]?.email ? "email" : "whatsapp");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [tpl, setTpl] = useState("");
  const [drafted, setDrafted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [dir, setDir] = useState("");
  const [open, setOpen] = useState(false);
  const windowOpen = thread.data?.whatsapp_window_open;
  async function draft() {
    setAiBusy(true);
    try { const r = await act("messages.draft", { project_id: p.id, direction: dir, channel: ch }); setSubject(r.subject); setBody(r.body); setDrafted(true); }
    catch (e) { toast(e.message, "error"); } finally { setAiBusy(false); }
  }
  async function send() {
    setBusy(true);
    try {
      const html = ch === "email" ? (body.includes("<") ? body : body.split("\n\n").map((x) => `<p>${x.replace(/\n/g, "<br>")}</p>`).join("")) : body;
      await act("messages.send", ch === "whatsapp" && !windowOpen ? { project_id: p.id, channel: "whatsapp", wa_template: tpl || "general_update", wa_params: [p.contacts[0]?.first_name || "", body] }
        : { project_id: p.id, channel: ch, subject, body: html });
      setSubject(""); setBody(""); setDrafted(false); setOpen(false); toast("Sent"); onSent(); thread.refetch();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  if (!p.contacts.length) return <Card className="text-ivory-70">Add a client in Details to start messaging.</Card>;
  return (
    <Card>
      {!open ? (
        <button onClick={() => setOpen(true)} className="flex w-full items-center gap-3 text-left text-ivory-70"><Mail size={18} /> Write to {p.contacts[0].name}…</button>
      ) : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={ch} onChange={setCh} options={[{ value: "email", label: <span className="flex items-center gap-1"><Mail size={14} />Email</span> }, { value: "whatsapp", label: <span className="flex items-center gap-1"><MessageCircle size={14} />WhatsApp</span> }]} />
            {drafted && <AgentChip />}
          </div>
          {ch === "whatsapp" && !windowOpen && <p className="text-[13px] text-ivory-70">WhatsApp only allows free text within 24 hours of the client's last message. This goes as the approved "update" template.</p>}
          {ch === "email" && <Input placeholder="Subject" value={subject} onChange={(e) => { setSubject(e.target.value); setDrafted(false); }} />}
          <Textarea placeholder="Message" value={body.replace(/<\/p><p>/g, "\n\n").replace(/<\/?p>/g, "").replace(/<br>/g, "\n")} onChange={(e) => { setBody(e.target.value); setDrafted(false); }} rows={6} />
          <div className="ai flex flex-wrap items-center gap-2 rounded-input border border-teal/30 p-2">
            <input className="min-w-0 flex-1 bg-transparent px-1 font-mono text-[14px] placeholder:text-ivory-35 focus:outline-none" placeholder="One line of direction for the AI draft (optional)" value={dir} onChange={(e) => setDir(e.target.value)} />
            <Button size="sm" variant="ai" busy={aiBusy} onClick={draft}>AI draft</Button>
          </div>
          <div className="flex justify-end gap-2"><Button variant="quiet" size="sm" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" size="sm" busy={busy} disabled={!body.trim()} onClick={send}>Send</Button></div>
          <input type="hidden" value={tpl} onChange={(e) => setTpl(e.target.value)} />
        </div>
      )}
    </Card>
  );
}

function FilesTab({ p, onChange }) {
  const nav = useNavigate();
  const tpls = useAct("templates.list", { kind: "file" });
  const ups = useAct("uploads.list", { project_id: p.id });
  const [open, setOpen] = useState(false);
  async function create(template_id) {
    try { const f = await act("files.create_from_template", { project_id: p.id, template_id }); nav(`/files/${f.id}`); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <div className="space-y-3">
      <div className="flex gap-2"><Button variant="primary" size="sm" icon={Plus} onClick={() => setOpen(true)}>New client file</Button></div>
      {!p.files.length && <Empty title="No client files yet" line="Proposals, contracts, invoices and questionnaires go here." />}
      {p.files.map((f) => (
        <Card key={f.id} className="flex items-center gap-3">
          <FileText size={18} className="text-gold" />
          <button className="min-w-0 flex-1 text-left" onClick={() => nav(`/files/${f.id}`)}><b className="block truncate">{f.title}</b>
            <span className="text-[13px] text-ivory-70">{titleCase(f.status)}{f.version ? ` · version ${f.version}` : ""}{f.sent_at ? ` · sent ${date(f.sent_at)}` : ""}</span></button>
          <StatusChip s={f.status} />
          {f.status === "completed"
            ? <Button size="sm" onClick={async () => { try { await act("files.reopen", { id: f.id }); toast("Reopened. The client can change their answers."); onChange(); } catch (e) { toast(e.message, "error"); } }}>Reopen</Button>
            : f.sent_at && <Button size="sm" variant="ghost" onClick={async () => { try { await act("files.mark_complete", { id: f.id }); toast("Marked complete."); onChange(); } catch (e) { toast(e.message, "error"); } }}>Mark complete</Button>}
        </Card>
      ))}
      {(ups.data || []).length > 0 && <Kicker className="pt-3">Documents</Kicker>}
      {(ups.data || []).map((u) => (
        <a key={u.id} href={`/api/uploads/${u.id}`} target="_blank" rel="noreferrer" className="flex items-center gap-3 rounded-input border border-hairline bg-panel px-4 py-3">
          <FileText size={16} /><span className="min-w-0 flex-1 truncate">{u.name}</span>{u.by_client && <Chip>From client</Chip>}<ExternalLink size={14} />
        </a>
      ))}
      <Sheet open={open} onClose={() => setOpen(false)} title="New client file">
        <div className="space-y-1">
          <button onClick={() => create(null)} className="w-full rounded-input px-3 py-3 text-left font-bold hover:bg-panel-raised">Blank file</button>
          {(tpls.data || []).map((t) => <button key={t.id} onClick={() => create(t.id)} className="w-full rounded-input px-3 py-3 text-left hover:bg-panel-raised">{t.name}</button>)}
        </div>
      </Sheet>
    </div>
  );
}

export function StatusChip({ s }) {
  const tone = { draft: "muted", scheduled: "muted", sent: "ivory", viewed: "ivory", completed: "gold" }[s] || "muted";
  return <Chip tone={tone}>{titleCase(s)}</Chip>;
}

function TaskList({ tasks, onChange }) {
  return (
    <div className="mt-1">
      {tasks.map((t) => (
        <label key={t.id} className="flex min-h-[44px] items-center gap-3 border-t border-hairline py-2 first:border-0">
          <input type="checkbox" checked={t.done} onChange={async () => { await act("tasks.complete", { id: t.id }); onChange(); }} />
          <span className={cx("min-w-0 flex-1 text-[14px]", t.done && "text-ivory-35 line-through")}>{t.title}
            {t.due_at && <span className={cx("block text-[12px]", new Date(t.due_at) < new Date() && !t.done ? "text-alert" : "text-ivory-35")}>{dt(t.due_at)}</span>}</span>
          {t.created_by?.startsWith("agent:") && <Sparkles size={13} className="text-teal" />}
        </label>
      ))}
    </div>
  );
}

function TasksTab({ p, onChange }) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState(istDateInput());
  const [est, setEst] = useState("");
  const [ask, setAsk] = useState(false);
  const tl = useAct("tasks.list", { scope: "all", project_id: p.id });
  const ct = useAct("client_tasks.list", { project_id: p.id, status: "all" });
  const tpls = useAct("task_templates.list");
  const reloadAll = () => { tl.refetch(); ct.refetch(); onChange(); };
  async function add() {
    if (!title.trim()) return;
    try { await act("tasks.create", { title, project_id: p.id, due_at: fromDateInput(due, 18), estimate_hours: est ? Number(est) : null }); setTitle(""); setEst(""); reloadAll(); } catch (e) { toast(e.message, "error"); }
  }
  const team = (tl.data || []).filter((t) => t.audience !== "client");
  return (
    <div className="space-y-5">
      <div>
        <div className="grid grid-cols-[1fr_auto] gap-2 md:grid-cols-[1fr_140px_90px_auto]"><Input placeholder="New task" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} className="col-span-2 md:col-span-1" />
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="rounded-input border border-hairline bg-panel px-2" aria-label="Due" />
          <Input placeholder="Hours" inputMode="decimal" value={est} onChange={(e) => setEst(e.target.value)} aria-label="Estimate in hours" />
          <Button onClick={add}>Add</Button></div>
        <div className="mt-1">
          {team.map((t) => (
            <div key={t.id} className="flex min-h-[44px] flex-wrap items-center gap-3 border-t border-hairline py-2 first:border-0">
              <input type="checkbox" aria-label="Done" checked={t.done} onChange={async () => { await act("tasks.complete", { id: t.id }); reloadAll(); }} />
              <span className={cx("min-w-0 flex-1 text-[14px]", t.done && "text-ivory-35 line-through")}>{t.title}
                <span className="block text-[12px] text-ivory-35">{t.due_at && <span className={cx(new Date(t.due_at) < new Date() && !t.done && "text-alert")}>{dt(t.due_at)}</span>}
                  {t.estimate_minutes ? <span> · est {Math.round(t.estimate_minutes / 6) / 10}h · {Math.round((t.logged_minutes || 0) / 6) / 10}h logged</span> : null}
                  {t.recurrence ? <span> · repeats {t.recurrence.every}</span> : null}</span></span>
              {t.created_by?.startsWith("agent:") && <Sparkles size={13} className="text-teal" />}
              {!t.done && t.due_at && !t.series_id && <select aria-label="Repeat" className="h-8 rounded-input border border-hairline bg-panel px-2 text-[12px]" value="" onChange={async (e) => { try { await act("tasks.set_recurrence", { id: t.id, every: e.target.value }); toast("Repeats " + e.target.value); reloadAll(); } catch (er) { toast(er.message, "error"); } }}>
                <option value="">Repeat…</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="quarterly">Quarterly</option></select>}
            </div>
          ))}
        </div>
        {(tpls.data || []).length > 0 && <div className="mt-2 flex items-center gap-2 text-[14px]"><span className="text-ivory-70">Add a checklist:</span>
          <select aria-label="Checklist" className="h-9 rounded-input border border-hairline bg-panel px-2" value="" onChange={async (e) => { if (!e.target.value) return; const r = await act("task_templates.apply", { template_id: e.target.value, project_id: p.id }); toast(r.summary); reloadAll(); }}>
            <option value="">Choose…</option>{tpls.data.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></div>}
        <p className="mt-2 text-[12px] text-ivory-35">Team tasks. Clients never see these.</p>
      </div>
      <div>
        <div className="flex items-center gap-2"><Kicker>Waiting on the client</Kicker><Button size="sm" className="ml-auto" icon={Plus} onClick={() => setAsk(true)}>Ask the client</Button></div>
        {!(ct.data || []).length ? <p className="mt-2 text-[14px] text-ivory-70">Nothing asked yet. Ask for documents, numbers or approvals; they get a link by WhatsApp or email.</p> : ct.data.map((t) => (
          <div key={t.id} className="flex flex-wrap items-center gap-3 border-t border-hairline py-2 first:border-0">
            <span className={cx("min-w-0 flex-1 text-[14px]", t.done && "text-ivory-35 line-through")}>{t.title}
              <span className={cx("block text-[12px]", t.overdue ? "text-alert" : "text-ivory-35")}>{t.done ? "Done" : t.due_at ? `Due ${date(t.due_at)}` : "No due date"}{(t.replies || []).length ? ` · ${t.replies.length} repl${t.replies.length === 1 ? "y" : "ies"}` : ""}{(t.upload_ids || []).length ? ` · ${t.upload_ids.length} file${t.upload_ids.length === 1 ? "" : "s"}` : ""}</span></span>
            {!t.done && <><Button size="sm" variant="quiet" onClick={async () => { try { await act("client_tasks.remind", { id: t.id }); toast("Reminder sent"); } catch (e) { toast(e.message, "error"); } }}>Remind</Button>
              <Button size="sm" variant="quiet" onClick={async () => { await act("client_tasks.complete", { id: t.id }); reloadAll(); }}>Mark done</Button></>}
          </div>))}
      </div>
      <ClientTaskSheet open={ask} onClose={() => setAsk(false)} projectId={p.id} onDone={reloadAll} />
    </div>
  );
}

function TimeTab({ p, onChange }) {
  const q = useAct("time.list", { project_id: p.id, limit: 300 });
  const un = useAct("time.unbilled", { project_id: p.id });
  const [log, setLog] = useState(false);
  const [inv, setInv] = useState(false);
  const [sp, setSp] = useSearchParams();
  const item = un.data?.items?.[0];
  const reloadAll = () => { q.refetch(); un.refetch(); onChange(); };
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" icon={Plus} onClick={() => setLog(true)}>Log time</Button>
        {item && item.amount_paise > 0 && <Button size="sm" variant="primary" onClick={() => setInv(true)}>Invoice unbilled time ({inr(item.amount_paise)})</Button>}
      </div>
      {!(q.data || []).length ? <Empty title="No time logged" line="Log time here, from the Time page, or with the timer." /> : (
        <div className="overflow-x-auto rounded-card border border-hairline"><table className="w-full min-w-[560px] text-[14px]"><tbody>{q.data.map((r) => (
          <tr key={r.id} className="border-t border-hairline first:border-0"><td className="whitespace-nowrap p-3">{date(r.date)}</td>
            <td className="max-w-[240px] truncate p-3 text-ivory-70">{r.task ? `${r.task} · ` : ""}{r.note}</td><td className="p-3 text-ivory-70">{r.person}</td>
            <td className="tnum p-3 text-right">{hm(r.minutes)}</td><td className="tnum p-3 text-right text-gold">{r.amount_paise === null ? "—" : inr(r.amount_paise)}</td>
            <td className="p-3"><TimeStatus s={r.billing_status} /></td></tr>))}</tbody></table></div>)}
      <LogTimeSheet open={log} onClose={() => setLog(false)} projectId={p.id} onDone={reloadAll} />
      {inv && <TimeInvoiceSheet open onClose={() => setInv(false)} projectId={p.id} onDone={() => { reloadAll(); setSp({ tab: "payments" }); }} />}
    </div>
  );
}

function BudgetTab({ p, onChange }) {
  const q = useAct("budgets.get", { project_id: p.id });
  const fc = useAct("budgets.forecast", { project_id: p.id }, { enabled: !!q.data && !q.data.from_retainer });
  const nav = useNavigate();
  const [f, setF] = useState({ type: "fee", amount_paise: 0, amount_hours: "", counts: "time", reset: "none" });
  const [edit, setEdit] = useState(false);
  if (q.isLoading) return <SkeletonList rows={2} />;
  const b = q.data;
  async function save(update) {
    try { await act(update ? "budgets.update" : "budgets.create", { project_id: p.id, type: f.type, amount_paise: f.type === "fee" ? f.amount_paise : null, amount_hours: f.type === "time" ? Number(f.amount_hours) : null, counts: f.counts, reset: f.reset });
      toast("Budget saved"); setEdit(false); q.refetch(); fc.refetch(); onChange(); } catch (e) { toast(e.message, "error"); }
  }
  const form = (
    <Card className="space-y-3">
      <Field label="Budget is"><Segmented value={f.type} onChange={(v) => setF({ ...f, type: v })} options={[{ value: "fee", label: "A fee" }, { value: "time", label: "Hours" }]} /></Field>
      {f.type === "fee" ? <Field label="Amount"><MoneyInput paise={f.amount_paise} onChange={(v) => setF({ ...f, amount_paise: v || 0 })} /></Field>
        : <Field label="Hours"><Input inputMode="decimal" value={f.amount_hours} onChange={(e) => setF({ ...f, amount_hours: e.target.value })} /></Field>}
      {f.type === "fee" && <Field label="Counts"><Segmented value={f.counts} onChange={(v) => setF({ ...f, counts: v })} options={[{ value: "time", label: "Billable time" }, { value: "expenses", label: "Expenses" }, { value: "both", label: "Both" }]} /></Field>}
      <Field label="Starts fresh" hint="Unused budget never carries over. Use a retainer for that."><Segmented value={f.reset} onChange={(v) => setF({ ...f, reset: v })} options={[{ value: "none", label: "Never" }, { value: "weekly", label: "Weekly" }, { value: "monthly", label: "Monthly" }, { value: "quarterly", label: "Quarterly" }]} /></Field>
      <p className="text-[13px] text-ivory-70">You're told at 80% and 100%, once each per cycle. At 80% the follow-up agent drafts a short scope check for the client.</p>
      <Button variant="primary" onClick={() => save(!!b)}>Save budget</Button>
    </Card>
  );
  if (!b) return <div className="space-y-3"><p className="text-[14px] text-ivory-70">No budget yet. Set a fee or hours to get an early warning before this project stops paying.</p>{form}</div>;
  if (b.from_retainer) return <Card><Kicker>From the retainer</Kicker><div className="mt-2"><BudgetBar b={b} /></div><p className="mt-2 text-[14px] text-ivory-70">This project's budget is its retainer period ({date(b.cycle_start)} – {date(b.cycle_end)}).</p>
    <Button size="sm" className="mt-2" onClick={() => nav(`/retainers/${b.retainer_id}`)}>Open the retainer</Button></Card>;
  const f0 = fc.data;
  const max = Math.max(b.amount, f0?.forecast_total || 0, 1);
  return (
    <div className="space-y-3">
      <Card>
        <div className="flex items-center gap-2"><Kicker>{b.type === "fee" ? "Fee budget" : "Time budget"}{b.reset !== "none" ? ` · resets ${b.reset}` : ""}</Kicker>
          <Button size="sm" variant="quiet" className="ml-auto" onClick={() => { setF({ type: b.type, amount_paise: b.amount_paise || 0, amount_hours: b.amount_minutes ? b.amount_minutes / 60 : "", counts: b.counts, reset: b.reset }); setEdit(!edit); }}>Edit</Button>
          <Button size="sm" variant="quiet" onClick={async () => { await act("budgets.remove", { project_id: p.id }); q.refetch(); onChange(); }}>Remove</Button></div>
        <div className="mt-3"><BudgetBar b={b} /></div>
        <p className="mt-2 text-[13px] text-ivory-70">{b.used_label} used, {b.type === "fee" ? inr(b.left) : hm(b.left)} left · since {date(b.cycle_start)}{b.next_reset ? ` · resets ${date(b.next_reset)}` : ""}</p>
      </Card>
      {edit && form}
      {f0 && <Card>
        <Kicker>Used so far and forecast</Kicker>
        <p className="mt-1 text-[14px]">{f0.summary}</p>
        <svg viewBox="0 0 600 180" className="mt-3 w-full" role="img" aria-label="Budget used and forecast">
          <line x1="0" x2="600" y1={170 - (b.amount / max) * 150} y2={170 - (b.amount / max) * 150} stroke="currentColor" className="text-alert" strokeDasharray="4 4" strokeWidth="1" />
          {(() => {
            const pts = [...f0.series, ...f0.forecast];
            const ds = pts.map((x) => new Date(x.date).getTime());
            const d0 = Math.min(...ds, Date.now()), d1 = Math.max(...ds, Date.now() + 86400e3);
            const X = (d) => ((new Date(d).getTime() - d0) / (d1 - d0)) * 580 + 10, Y = (v) => 170 - (v / max) * 150;
            const used = [...f0.series, ...(f0.forecast[0] ? [f0.forecast[0]] : [])];
            const solid = used.map((s) => `${X(s.date)},${Y(s.value)}`).join(" ");
            const dotted = f0.forecast.map((s) => `${X(s.date)},${Y(s.value)}`).join(" ");
            return <>{solid && <polyline points={solid} fill="none" stroke="#C9A84C" strokeWidth="3" />}
              {f0.forecast.length > 1 && <polyline points={dotted} fill="none" stroke="#C9A84C" strokeWidth="2" strokeDasharray="6 5" opacity="0.8" />}</>;
          })()}
        </svg>
        <div className="mt-1 flex flex-wrap gap-4 text-[12px] text-ivory-70"><span>— Used</span><span>- - Forecast from open task estimates</span><span className="text-alert">- - Budget</span></div>
        {f0.tasks.length > 0 && <div className="mt-3">{f0.tasks.map((t) => <div key={t.task_id} className="flex justify-between border-t border-hairline py-2 text-[13px]"><span>{t.title}{t.overdue && <span className="text-alert"> · overdue</span>}</span><span className="tnum text-ivory-70">{hm(t.remaining_minutes)} left</span></div>)}</div>}
      </Card>}
      {b.history.length > 0 && <Card><Kicker>Past cycles</Kicker>{b.history.map((h) => <div key={h.start} className="flex justify-between border-t border-hairline py-2 text-[14px] first:border-0"><span>{date(h.start)} – {date(h.end)}</span><span className={cx("tnum", h.pct >= 100 ? "text-alert" : "")}>{Math.round(h.pct)}%</span></div>)}</Card>}
    </div>
  );
}

function TimeStatus({ s }) {
  return <Chip tone={s === "billed" ? "gold" : "muted"}>{s === "non_billable" ? "Non-billable" : s === "billed" ? "Billed" : "Unbilled"}</Chip>;
}

function PaymentsTab({ p, onChange }) {
  const [reqOpen, setReqOpen] = useState(false);
  const [recOpen, setRecOpen] = useState(false);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="primary" onClick={() => setReqOpen(true)}>Request a payment</Button><Button size="sm" variant="quiet" onClick={() => setRecOpen(true)}>Monthly invoice</Button></div>
      {!p.invoices.length && <Empty title="No invoices yet" line="Invoices come from the client file the client signs, or from a payment request." />}
      {p.invoices.map((inv) => <InvoiceCard key={inv.id} id={inv.id} onChange={onChange} />)}
      <RequestSheet open={reqOpen} onClose={() => setReqOpen(false)} p={p} onDone={onChange} />
      <RecurringSheet open={recOpen} onClose={() => setRecOpen(false)} p={p} onDone={onChange} />
    </div>
  );
}

export function InvoiceCard({ id, onChange }) {
  const q = useAct("invoices.get", { id });
  const [confirm, setConfirm] = useState(null);
  const [ai, setAi] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  if (!q.data) return <SkeletonList rows={1} />;
  const inv = q.data;
  const run = async (name, body, msg) => { try { await act(name, body); msg && toast(msg); q.refetch(); onChange && onChange(); } catch (e) { toast(e.message, "error"); } };
  const claimFor = (s) => inv.claims.find((c) => c.id === s.claim_id);
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <b>{inv.doc_title} {inv.number || "(draft)"}</b><Chip tone={inv.status === "paid" ? "gold" : "muted"}>{titleCase(inv.status)}</Chip>
        <span className="ml-auto tnum text-[18px] font-extrabold text-gold">{inr(inv.totals.total)}</span>
      </div>
      <div className="mt-1 text-[13px] text-ivory-70">{inv.lines.map((l) => l.name).join(", ") || "Lines come from the client's choice"}</div>
      <div className="mt-3 space-y-2">
        {inv.schedule.map((s) => {
          const cl = claimFor(s);
          return (
            <div key={s.id} className="rounded-input bg-panel-raised p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold">{s.label}</span>
                <span className={cx("text-[13px]", s.state === "overdue" ? "text-alert" : "text-ivory-70")}>{s.state === "paid" ? `Paid ${date(s.paid_at)}` : `${titleCase(s.state)} · due ${s.due_label}`}</span>
                <span className="ml-auto tnum font-bold text-gold">{inr(s.amount_paise + (s.late_fee_paise || 0))}</span>
              </div>
              {s.late_fee_paise > 0 && s.state !== "paid" && <div className="mt-1 text-[13px] text-ivory-70">Includes a late fee of {inr(s.late_fee_paise)} · <button className="font-bold text-gold" onClick={() => run("payments.cancel_late_fee", { invoice_id: inv.id, item_id: s.id }, "Late fee cancelled")}>Cancel it</button></div>}
              {cl && cl.status === "pending" && <div className="mt-2 text-[14px]">Client says they paid by {cl.method.toUpperCase()}{cl.reference ? ` (ref ${cl.reference})` : ""}. Check your account, then confirm.</div>}
              {s.state !== "paid" && inv.status !== "draft" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" variant={s.state === "processing" ? "primary" : "secondary"} onClick={() => setConfirm(s)}>Mark as paid</Button>
                  {cl && cl.status === "pending" && <Button size="sm" variant="quiet" onClick={() => { const r = prompt("Tell the client why", "We couldn't find this payment yet."); r && run("payments.reject_claim", { claim_id: cl.id, reason: r }, "Client told"); }}>Not received</Button>}
                  <Button size="sm" variant="quiet" onClick={() => run("invoices.remind", { id: inv.id, item_id: s.id }, "Reminder sent")}>Remind</Button>
                  {s.due?.type === "milestone" && !s.milestone_reached_at && <Button size="sm" variant="quiet" onClick={() => run("invoices.milestone_reached", { id: inv.id, item_id: s.id })}>Milestone reached</Button>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {inv.status === "draft" && (
        <div className="ai mt-3 flex gap-2 rounded-input border border-teal/30 p-2">
          <input className="min-w-0 flex-1 bg-transparent px-1 font-mono text-[14px] focus:outline-none" placeholder='e.g. "add a 10% discount" or "split into three payments"' value={ai} onChange={(e) => setAi(e.target.value)} />
          <Button size="sm" variant="ai" busy={aiBusy} onClick={async () => { setAiBusy(true); try { const r = await act("invoices.ai_edit", { id: inv.id, instruction: ai }); toast(`Done: ${r.ai_summary}`, "ai"); setAi(""); q.refetch(); } catch (e) { toast(e.message, "error"); } finally { setAiBusy(false); } }}>Edit</Button>
          {inv.ai_previous && <Button size="sm" variant="quiet" onClick={() => run("invoices.undo_ai_edit", { id: inv.id }, "Undone")}>Undo</Button>}
        </div>
      )}
      {inv.status === "draft" && inv.lines.length > 0 && !inv.file_id && <Button className="mt-3" size="sm" variant="primary" onClick={() => run("invoices.send", { id: inv.id, channel: "both" }, "Invoice sent")}>Send invoice</Button>}
      <ConfirmSheet s={confirm} inv={inv} onClose={() => setConfirm(null)} onDone={() => { q.refetch(); onChange && onChange(); }} />
    </Card>
  );
}

function ConfirmSheet({ s, inv, onClose, onDone }) {
  const due = s ? s.amount_paise + (s.late_fee_paise || 0) - (s.paid_paise || 0) : 0;
  const [tds, setTds] = useState(0);
  const [method, setMethod] = useState("upi");
  const [ref, setRef] = useState("");
  const [busy, setBusy] = useState(false);
  if (!s) return null;
  async function go() {
    setBusy(true);
    try { await act("payments.confirm", { invoice_id: inv.id, item_id: s.id, amount_received_paise: due - (tds || 0), tds_paise: tds || 0, method, reference: ref }); toast("Payment confirmed"); onDone(); onClose(); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open onClose={onClose} title="Mark as paid">
      <p className="text-ivory-70">Only mark it paid once the money is in your account. Amount due: <b className="text-gold">{inr(due)}</b></p>
      <div className="mt-3 space-y-3">
        <Segmented value={method} onChange={setMethod} options={[{ value: "upi", label: "UPI" }, { value: "bank", label: "Bank transfer" }, { value: "cash", label: "Other" }]} />
        <Field label="TDS deducted by the client (if any)" hint={tds ? `You received ${inr(due - tds)} + TDS ${inr(tds)} = ${inr(due)}` : "Business clients often deduct TDS before paying."}><MoneyInput paise={tds} onChange={(v) => setTds(v || 0)} /></Field>
        <Field label="Reference (optional)"><Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR or UPI reference" /></Field>
        <Button variant="primary" size="lg" className="w-full" busy={busy} onClick={go}>Confirm {inr(due - (tds || 0))} received</Button>
      </div>
    </Sheet>
  );
}

function RequestSheet({ open, onClose, p, onDone }) {
  const [amt, setAmt] = useState(null);
  const [label, setLabel] = useState("Payment");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Sheet open={open} onClose={onClose} title="Request a payment">
      <div className="space-y-3">
        <Field label="Amount"><MoneyInput paise={amt} onChange={setAmt} /></Field>
        <Field label="What it's for"><Input value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Field label="Due date (optional)"><input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        <Button variant="primary" size="lg" className="w-full" busy={busy} onClick={async () => {
          setBusy(true);
          try { await act("payments.request", { project_id: p.id, amount_paise: amt || 0, label, due_date: fromDateInput(due) }); toast("Payment link sent"); onDone(); onClose(); }
          catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
        }}>Send pay link</Button>
        <p className="text-[13px] text-ivory-35">The client pays you directly by UPI or bank transfer, then taps "I've paid". You confirm it here.</p>
      </div>
    </Sheet>
  );
}

function RecurringSheet({ open, onClose, p, onDone }) {
  const [amt, setAmt] = useState(null);
  const [name, setName] = useState("Advisory retainer — monthly");
  const [day, setDay] = useState(1);
  return (
    <Sheet open={open} onClose={onClose} title="Monthly invoice">
      <div className="space-y-3">
        <Field label="Line"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Amount each month"><MoneyInput paise={amt} onChange={setAmt} /></Field>
        <Field label="Day of the month (1–28)"><Input inputMode="numeric" value={day} onChange={(e) => setDay(Number(e.target.value.replace(/\D/g, "")) || 1)} /></Field>
        <Button variant="primary" className="w-full" onClick={async () => {
          try { await act("recurring.create", { project_id: p.id, lines: [{ name, qty: 1, price_paise: amt || 0 }], day_of_month: day }); toast("Monthly invoice set up"); onDone(); onClose(); }
          catch (e) { toast(e.message, "error"); }
        }}>Set up</Button>
        <p className="text-[13px] text-ivory-35">Only you can pause or stop it. The client can't.</p>
      </div>
    </Sheet>
  );
}

function NotesTab({ p, onChange }) {
  const [text, setText] = useState("");
  const [shared, setShared] = useState(false);
  const [tr, setTr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-4">
      <Card>
        <Textarea placeholder="Add a note" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="mt-2 flex items-center justify-between"><Toggle on={shared} onChange={setShared} label="Share with the client" />
          <Button size="sm" variant="primary" disabled={!text.trim()} onClick={async () => { await act("notes.add", { project_id: p.id, text, shared }); setText(""); onChange(); }}>Add note</Button></div>
      </Card>
      <Card ai>
        <Kicker ai>Call notes for the Meeting agent</Kicker>
        <Textarea ai className="mt-2" placeholder="Paste a transcript or your notes from the call" value={tr} onChange={(e) => setTr(e.target.value)} />
        <Button className="mt-2" size="sm" variant="ai" busy={busy} onClick={async () => { setBusy(true); try { const r = await act("meetings.add_transcript", { project_id: p.id, text: tr }); toast(r.summary, "ai"); setTr(""); onChange(); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); } }}>Write it up</Button>
      </Card>
      {p.notes.map((n) => (
        <Card key={n.id}>
          <div className="mb-1 flex items-center gap-2">{n.actor?.startsWith("agent:") && <AgentChip who={`${titleCase(n.actor.slice(6))} agent`} />}{n.shared && <Chip tone="gold">Shared</Chip>}{n.kind === "enquiry" && <Chip>Enquiry</Chip>}<span className="ml-auto text-[12px] text-ivory-35">{ago(n.created_at)}</span></div>
          <p className={cx("whitespace-pre-wrap text-[14px]", n.kind === "enquiry" && "font-mono")}>{n.text}</p>
        </Card>
      ))}
    </div>
  );
}

function DetailsTab({ p, onChange }) {
  const ws = useWs();
  const st = ws.data?.settings || {};
  const [d, setD] = useState({ name: p.name, type: p.type, source: p.source, value_paise: p.value_paise, start_date: p.start_date || "", end_date: p.end_date || "",
    shared_details: p.shared_details || {}, custom: p.custom || {} });
  const team = useAct("team.list");
  const [contact, setContact] = useState({ name: "", phone: "", email: "" });
  async function save() {
    try { await act("projects.update", { id: p.id, ...d }); toast("Saved"); onChange(); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <div className="space-y-4">
      <Card>
        <Kicker>Client</Kicker>
        {p.contacts.map((c) => <div key={c.id} className="mt-2"><b>{c.name}</b> <span className="text-ivory-70">{[c.phone, c.email, c.company].filter(Boolean).join(" · ")}</span>
          {c.enrichment?.website && <div className="text-[13px] text-teal">Found: {c.enrichment.website}</div>}</div>)}
        {!p.contacts.length && (
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <Input placeholder="Name" value={contact.name} onChange={(e) => setContact({ ...contact, name: e.target.value })} />
            <Input placeholder="Mobile" value={contact.phone} onChange={(e) => setContact({ ...contact, phone: e.target.value })} />
            <Input placeholder="Email" value={contact.email} onChange={(e) => setContact({ ...contact, email: e.target.value })} />
            <Button onClick={async () => { const c = await act("contacts.create", contact); await act("projects.update", { id: p.id, contact_ids: [c.id] }); onChange(); }}>Add client</Button>
          </div>
        )}
      </Card>
      <Card>
        <Kicker>Shared with the client</Kicker>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field label="Project name"><Input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
          <Field label="Start date"><input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={(d.start_date || "").slice(0, 10)} onChange={(e) => setD({ ...d, start_date: e.target.value })} /></Field>
          <Field label="End date"><input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={(d.end_date || "").slice(0, 10)} onChange={(e) => setD({ ...d, end_date: e.target.value })} /></Field>
          <Field label="Location or format"><Input value={d.shared_details.location || ""} onChange={(e) => setD({ ...d, shared_details: { ...d.shared_details, location: e.target.value } })} placeholder="Online / client office" /></Field>
        </div>
        <div className="my-5 flex items-center gap-3 text-[12px] font-bold uppercase tracking-[0.16em] text-ivory-35"><span className="h-px flex-1 bg-gold-deep" /> Private below this line <span className="h-px flex-1 bg-gold-deep" /></div>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Value"><MoneyInput paise={d.value_paise} onChange={(v) => setD({ ...d, value_paise: v || 0 })} /></Field>
          <Field label="Type"><Select value={d.type} onChange={(e) => setD({ ...d, type: e.target.value })} options={[{ value: "", label: "Not set" }, ...(st.project_types || [])]} /></Field>
          <Field label="Lead source"><Select value={d.source} onChange={(e) => setD({ ...d, source: e.target.value })} options={[{ value: "", label: "Not set" }, ...(st.lead_sources || [])]} /></Field>
          <Field label="Owner"><Select value={p.owner_id} onChange={async (e) => { await act("projects.update", { id: p.id, owner_id: e.target.value }); onChange(); }}
            options={(team.data || []).filter((m) => m.joined).map((m) => ({ value: m.user_id, label: m.name || m.phone }))} /></Field>
          {(p.custom_fields || []).map((cf) => (
            <Field key={cf.key} label={cf.label}><Input value={d.custom[cf.key] || ""} onChange={(e) => setD({ ...d, custom: { ...d.custom, [cf.key]: e.target.value } })} /></Field>
          ))}
        </div>
        <Button className="mt-4" variant="primary" onClick={save}>Save details</Button>
        {!p.booked && p.contacts.length > 0 && <Button className="ml-2 mt-4" variant="quiet" onClick={async () => { await act("projects.mark_booked", { id: p.id, booked: true }); onChange(); }}>Mark booked</Button>}
      </Card>
      <TimeCard p={p} />
    </div>
  );
}

function TimeCard({ p }) {
  const q = useAct("time.list", { project_id: p.id });
  const [run, setRun] = useState(null);
  const [mins, setMins] = useState("");
  const total = (q.data || []).reduce((a, t) => a + t.minutes, 0);
  async function log(minutes) { try { await act("time.log", { project_id: p.id, minutes }); q.refetch(); toast("Time logged"); } catch (e) { toast(e.message, "error"); } }
  return (
    <Card>
      <Kicker>Time</Kicker>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="tnum text-[18px] font-extrabold text-gold">{Math.floor(total / 60)}h {total % 60}m</span>
        {run ? <Button size="sm" variant="primary" onClick={() => { log(Math.max(1, Math.round((Date.now() - run) / 60000))); setRun(null); }}>Stop</Button>
          : <Button size="sm" onClick={() => setRun(Date.now())}>Start timer</Button>}
        <Input className="w-28" placeholder="Minutes" inputMode="numeric" value={mins} onChange={(e) => setMins(e.target.value.replace(/\D/g, ""))} />
        <Button size="sm" variant="quiet" disabled={!mins} onClick={() => { log(Number(mins)); setMins(""); }}>Add</Button>
      </div>
    </Card>
  );
}

function ArchiveSheet({ open, onClose, p, reasons, onDone }) {
  const [reason, setReason] = useState("");
  return (
    <Sheet open={open} onClose={onClose} title="Archive this project">
      <p className="text-ivory-70">Archiving stops any automations running on it.{!p.booked ? " Why was this lead lost?" : ""}</p>
      {!p.booked && <div className="mt-3 grid grid-cols-2 gap-2">{reasons.map((r) => <button key={r} onClick={() => setReason(r)} className={cx("h-12 rounded-input border px-3 font-bold", reason === r ? "border-gold text-gold" : "border-hairline")}>{r}</button>)}</div>}
      <Button className="mt-4 w-full" variant="danger" onClick={async () => { try { await act("projects.archive", { id: p.id, reason: reason || null }); onDone(); onClose(); } catch (e) { toast(e.message, "error"); } }}>Archive</Button>
    </Sheet>
  );
}
