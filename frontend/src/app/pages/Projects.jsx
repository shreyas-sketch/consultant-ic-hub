import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { DndContext, PointerSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { Columns3, ImagePlus, List, Plus, Save } from "lucide-react";
import { act, parseCsv, useAct, useRefresh } from "../../lib/api";
import { ago, inr } from "../../lib/format";
import { CreateMenu, NewLead, useWs } from "../components/AppShell";
import { BudgetBar } from "../components/addons";
import { Button, Card, Chip, Empty, Input, Loadable, PageHeader, Segmented, Select, Sheet, cx, toast, useDebounced } from "../components/ui";

const COLS = [["name", "Project"], ["client", "Client"], ["stage", "Stage"], ["value", "Value"], ["budget", "Budget"], ["type", "Type"], ["source", "Source"], ["activity", "Last activity"]];

export default function Projects() {
  const ws = useWs();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const views = useAct("views.list");
  const [mode, setMode] = useState(localStorage.getItem("pv-mode") || "board");
  const [f, setF] = useState({ q: "", type: "", source: "", tag: "", archived: false, waiting_on_client: false });
  const [cols, setCols] = useState(COLS.map((c) => c[0]));
  const [sort, setSort] = useState("-last_activity_at");
  const [sel, setSel] = useState([]);
  const [newOpen, setNewOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const dq = useDebounced(f.q, 250);
  const body = { ...f, q: dq, sort, type: f.type || undefined, source: f.source || undefined, tag: f.tag || undefined, waiting_on_client: f.waiting_on_client || undefined };
  const q = useAct("projects.search", body, { keepPreviousData: true });
  const refresh = useRefresh();
  const stages = ws.data?.stages || [];
  const st = ws.data?.settings || {};
  const pick = sp.get("pick");
  const setM = (m) => { setMode(m); try { localStorage.setItem("pv-mode", m); } catch { /* storage may be off */ } };

  async function saveView() {
    const name = prompt("Name this view");
    if (!name) return;
    try { await act("views.save", { name, filters: f, columns: cols, sort: { key: sort }, mode }); views.refetch(); toast("View saved"); }
    catch (e) { toast(e.message, "error"); }
  }
  function applyView(v) {
    setF({ q: "", type: "", source: "", tag: "", archived: false, ...v.filters });
    if (v.columns?.length) setCols(v.columns);
    if (v.sort?.key) setSort(v.sort.key);
    setM(v.mode || "board");
  }
  async function bulk(op, extra = {}) {
    try { const r = await act("projects.bulk", { ids: sel, op, ...extra }); toast(`${r.changed} changed`); setSel([]); refresh("projects"); }
    catch (e) { toast(e.message, "error"); }
  }

  return (
    <div>
      <PageHeader kicker="Pipeline" title="All your work," accent="in one place" sub={pick ? "Pick a project first, then create the file or invoice from its page." : "Drag a card to move it. Stages move by themselves when files are sent, contracts signed and payments confirmed."}
        right={<>
          <Button variant="quiet" size="sm" onClick={() => setImportOpen(true)}>Import CSV</Button>
          <Button variant="ai" size="sm" icon={ImagePlus} onClick={() => setCreateOpen(true)}>From screenshot</Button>
          <Button variant="primary" size="sm" icon={Plus} onClick={() => setNewOpen(true)}>New lead</Button></>} />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Segmented value={mode} onChange={setM} options={[{ value: "board", label: <span className="flex items-center gap-1"><Columns3 size={14} /> Board</span> }, { value: "table", label: <span className="flex items-center gap-1"><List size={14} /> Table</span> }]} />
        <div className="scroll-x flex gap-1">
          {(views.data || []).map((v) => <button key={v.id} onClick={() => applyView(v)} className="h-9 whitespace-nowrap rounded-full border border-hairline px-3 text-[13px] font-bold text-ivory-70 hover:text-ivory">{v.name}</button>)}
        </div>
        <Button size="sm" variant="quiet" icon={Save} onClick={saveView}>Save view</Button>
      </div>
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Input className="col-span-2 md:col-span-1" placeholder="Search" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <Select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} options={[{ value: "", label: "Any type" }, ...(st.project_types || [])]} />
        <Select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} options={[{ value: "", label: "Any source" }, ...(st.lead_sources || [])]} />
        <Input placeholder="Tag" value={f.tag} onChange={(e) => setF({ ...f, tag: e.target.value })} />
        <Select value={f.archived ? "1" : ""} onChange={(e) => setF({ ...f, archived: !!e.target.value })} options={[{ value: "", label: "Open" }, { value: "1", label: "Archived" }]} />
        <Select value={f.waiting_on_client ? "1" : ""} onChange={(e) => setF({ ...f, waiting_on_client: !!e.target.value })} options={[{ value: "", label: "Anyone" }, { value: "1", label: "Waiting on client" }]} />
      </div>

      <Loadable q={q} rows={5} empty={<Empty title="No projects here yet" line="Add a lead, import a CSV, or share a lead form." action={<Button variant="primary" onClick={() => setNewOpen(true)}>Add a lead</Button>} />}>
        {(d) => mode === "board" && !f.archived ? <Board d={d} stages={stages} onMove={refresh} /> : (
          <Table d={d} stages={stages} cols={cols} setCols={setCols} sort={sort} setSort={setSort} sel={sel} setSel={setSel} onOpen={(id) => nav(`/projects/${id}`)} />
        )}
      </Loadable>

      {sel.length > 0 && (
        <div className="fixed inset-x-3 bottom-[84px] z-30 flex flex-wrap items-center gap-2 rounded-card border border-hairline bg-panel-raised p-3 shadow-float md:inset-x-auto md:bottom-6 md:left-1/2 md:-translate-x-1/2">
          <b className="mr-1">{sel.length} selected</b>
          <select className="h-9 rounded-full border border-hairline bg-panel px-3 text-[14px]" onChange={(e) => e.target.value && bulk("move_stage", { stage_id: e.target.value })} defaultValue="">
            <option value="">Move to…</option>{stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <Button size="sm" variant="quiet" onClick={() => { const t = prompt("Tag"); t && bulk("tag", { tag: t }); }}>Tag</Button>
          <Button size="sm" variant="quiet" onClick={() => { const r = prompt("Why are these lost? (Won elsewhere, No budget, No reply, Not a fit)", "No reply"); r && bulk("archive", { reason: r }); }}>Archive</Button>
          <Button size="sm" variant="link" onClick={() => setSel([])}>Clear</Button>
        </div>
      )}
      <Sheet open={newOpen} onClose={() => setNewOpen(false)} title="New lead"><NewLead onDone={(id) => { setNewOpen(false); nav(`/projects/${id}`); }} /></Sheet>
      <ImportSheet open={importOpen} onClose={() => { setImportOpen(false); refresh("projects", "contacts"); }} />
      <CreateMenu open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

function Board({ d, stages, onMove }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }), useSensor(TouchSensor, { activationConstraint: { delay: 220, tolerance: 6 } }));
  const [local, setLocal] = useState({});
  const items = d.items.map((p) => ({ ...p, stage_id: local[p.id] || p.stage_id }));
  async function end(e) {
    const pid = e.active?.id;
    const sid = e.over?.id;
    if (!pid || !sid) return;
    const p = items.find((x) => x.id === pid);
    if (!p || p.stage_id === sid) return;
    setLocal({ ...local, [pid]: sid });
    try { await act("projects.move_stage", { id: pid, stage_id: sid }); onMove("projects"); }
    catch (x) { setLocal({ ...local, [pid]: p.stage_id }); toast(x.message, "error"); }
  }
  return (
    <DndContext sensors={sensors} onDragEnd={end}>
      <div className="scroll-x -mx-4 flex gap-3 px-4 pb-4 md:mx-0 md:px-0">
        {stages.map((s) => <Column key={s.id} s={s} count={d.stage_counts[s.id] ?? 0} items={items.filter((p) => p.stage_id === s.id)} />)}
      </div>
    </DndContext>
  );
}

function Column({ s, items, count }) {
  const { setNodeRef, isOver } = useDroppable({ id: s.id });
  const total = items.reduce((a, p) => a + (p.value_paise || 0), 0);
  return (
    <div ref={setNodeRef} className={cx("w-[272px] shrink-0 rounded-card border p-2 transition", isOver ? "border-gold bg-panel" : "border-hairline bg-panel/50")}>
      <div className="flex items-center justify-between px-2 py-2">
        <div className="font-bold">{s.name} <span className="text-ivory-35">{count}</span></div>
        {total > 0 && <span className="tnum text-[13px] text-gold">{inr(total, { short: true })}</span>}
      </div>
      <div className="min-h-[60px] space-y-2">{items.map((p) => <ProjectCard key={p.id} p={p} />)}</div>
    </div>
  );
}

function ProjectCard({ p }) {
  const nav = useNavigate();
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: p.id });
  const style = transform ? { transform: `translate(${transform.x}px, ${transform.y}px)`, zIndex: 20 } : undefined;
  return (
    <div ref={setNodeRef} style={style} {...listeners} {...attributes} onClick={() => !isDragging && nav(`/projects/${p.id}`)}
      className={cx("cursor-pointer touch-manipulation rounded-input border border-hairline bg-panel p-3 hover:border-gold-deep", isDragging && "shadow-float")}>
      <div className="truncate font-bold">{p.name}</div>
      <div className="mt-0.5 truncate text-[13px] text-ivory-70">{p.contacts?.[0]?.name || "No client yet"}</div>
      <div className="mt-2 flex items-center gap-2">
        {p.value_paise > 0 && <span className="tnum text-[13px] font-bold text-gold">{inr(p.value_paise, { short: true })}</span>}
        {p.booked && <Chip tone="gold">Booked</Chip>}
        {p.source && <span className="truncate text-[12px] text-ivory-35">{p.source}</span>}
        <span className="ml-auto text-[12px] text-ivory-35">{ago(p.last_activity_at)}</span>
      </div>
      {p.waiting_on_client && <div className="mt-2"><Chip>Waiting on client</Chip></div>}
      <BudgetBar b={p.budget} compact />
    </div>
  );
}

function Table({ d, stages, cols, setCols, sort, setSort, sel, setSel, onOpen }) {
  const sname = useMemo(() => Object.fromEntries(stages.map((s) => [s.id, s.name])), [stages]);
  const [colsOpen, setColsOpen] = useState(false);
  const [order, setOrder] = useState(cols);
  const shown = order.filter((c) => cols.includes(c));
  const allOnPage = d.items.length && d.items.every((p) => sel.includes(p.id));
  const sortKey = { name: "name", value: "value_paise", activity: "last_activity_at", type: "type", source: "source" };
  const cell = (p, c) => ({ name: <b>{p.name}</b>, client: p.contacts?.[0]?.name || "—", stage: sname[p.stage_id] || "",
    value: <span className="tnum text-gold">{p.value_paise ? inr(p.value_paise) : "—"}</span>, type: p.type || "—", source: p.source || "—",
    budget: p.budget ? <span className={cx("tnum", p.budget.pct >= 100 ? "text-alert" : p.budget.pct >= 80 ? "text-gold" : "text-ivory-70")}>{Math.round(p.budget.pct)}%</span> : "—",
    activity: <span className="text-ivory-70">{ago(p.last_activity_at)}</span> }[c]);
  function drag(e, c) { e.dataTransfer.setData("text", c); }
  function drop(e, c) { const from = e.dataTransfer.getData("text"); const o = order.filter((x) => x !== from); o.splice(o.indexOf(c), 0, from); setOrder(o); }
  return (
    <>
      <div className="mb-2 flex items-center gap-2 text-[13px] text-ivory-70">
        <span>{d.total} projects</span>
        {allOnPage && d.total > d.items.length && <button className="font-bold text-gold" onClick={() => setSel(d.items.map((p) => p.id))}>Select all {d.total}</button>}
        <button className="ml-auto font-bold text-gold" onClick={() => setColsOpen(true)}>Columns</button>
      </div>
      <div className="overflow-x-auto rounded-card border border-hairline">
        <table className="w-full min-w-[640px] text-left text-[14px]">
          <thead className="bg-panel text-[12px] uppercase tracking-[0.12em] text-ivory-70">
            <tr>
              <th className="w-10 p-3"><input type="checkbox" checked={!!allOnPage} onChange={(e) => setSel(e.target.checked ? d.items.map((p) => p.id) : [])} /></th>
              {shown.map((c) => (
                <th key={c} draggable onDragStart={(e) => drag(e, c)} onDragOver={(e) => e.preventDefault()} onDrop={(e) => drop(e, c)} className="cursor-pointer p-3"
                  onClick={() => sortKey[c] && setSort(sort === `-${sortKey[c]}` ? sortKey[c] : `-${sortKey[c]}`)}>
                  {COLS.find((x) => x[0] === c)[1]}{sort.replace("-", "") === sortKey[c] ? (sort.startsWith("-") ? " ↓" : " ↑") : ""}
                </th>))}
            </tr>
          </thead>
          <tbody>
            {d.items.map((p) => (
              <tr key={p.id} className="cursor-pointer border-t border-hairline hover:bg-panel" onClick={() => onOpen(p.id)}>
                <td className="p-3" onClick={(e) => e.stopPropagation()}><input type="checkbox" checked={sel.includes(p.id)} onChange={(e) => setSel(e.target.checked ? [...sel, p.id] : sel.filter((x) => x !== p.id))} /></td>
                {shown.map((c) => <td key={c} className="max-w-[240px] truncate p-3">{cell(p, c)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Sheet open={colsOpen} onClose={() => setColsOpen(false)} title="Columns">
        {COLS.map(([k, l]) => (
          <label key={k} className="flex h-11 items-center gap-3"><input type="checkbox" checked={cols.includes(k)} onChange={(e) => setCols(e.target.checked ? [...cols, k] : cols.filter((x) => x !== k))} />{l}</label>
        ))}
        <p className="mt-2 text-[13px] text-ivory-35">Drag column headers to reorder them.</p>
      </Sheet>
    </>
  );
}

function ImportSheet({ open, onClose }) {
  const [rows, setRows] = useState([]);
  const [proj, setProj] = useState(true);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  async function file(e) { const f = e.target.files?.[0]; if (f) setRows(parseCsv(await f.text())); }
  async function go() {
    setBusy(true);
    try { setRes(await act("contacts.import_csv", { rows, create_projects: proj })); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={() => { setRows([]); setRes(null); onClose(); }} title="Import contacts">
      <p className="text-ivory-70">A CSV with columns <b>name</b>, <b>phone</b>, <b>email</b>, <b>company</b>. People already here are matched by phone or email.</p>
      <input type="file" accept=".csv,text/csv" className="mt-3" onChange={file} />
      {rows.length > 0 && <p className="mt-3">{rows.length} rows ready.</p>}
      <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={proj} onChange={(e) => setProj(e.target.checked)} /> Create a project for each new contact</label>
      {res ? <Card className="mt-3">Added {res.created}, matched {res.matched}, skipped {res.skipped}.</Card> :
        <Button variant="primary" className="mt-4 w-full" disabled={!rows.length} busy={busy} onClick={go}>Import</Button>}
    </Sheet>
  );
}
