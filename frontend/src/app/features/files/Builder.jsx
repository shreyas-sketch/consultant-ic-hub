import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { DndContext, PointerSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowDown, ArrowLeft, ArrowUp, CalendarDays, Copy, Eye, GripVertical, History, Image as ImageIcon, LayoutList, ListChecks, Minus, PenLine, Plus, Receipt, Redo2, Save, Send, Signature, Trash2, Type, Undo2, Video, Building2, PartyPopper, Milestone, Package, Repeat } from "lucide-react";
import { act, fileToDataUrl, post, useAct } from "@/shared/api";
import { dt, inr, titleCase } from "@/shared/lib/format";
import { useWs } from "@/app/layout/AppShell";
import RichText from "@/app/ui/RichText";
import { Button, Card, Chip, Field, Input, Kicker, MoneyInput, Segmented, Select, Sheet, SkeletonList, Toggle, cx, toast, useAutosave } from "@/app/ui";
import { sanitize } from "@/shared/lib/safeHtml";

const nid = () => Math.random().toString(36).slice(2, 12);
const BLOCKS = [
  ["text", "Text", Type], ["image", "Image", ImageIcon], ["video", "Video", Video], ["company", "Company info", Building2],
  ["questions", "Questions", ListChecks], ["services", "Services", Package], ["contract", "Contract", Signature], ["invoice", "Invoice & pay", Receipt],
  ["scheduler", "Scheduler", CalendarDays], ["timeline", "Timeline", Milestone], ["divider", "Divider", Minus], ["spacer", "Spacer", LayoutList], ["thankyou", "Thank you", PartyPopper],
  ["retainer", "Retainer plan", Repeat],
];
const fresh = (type) => ({ id: nid(), type, ...({ text: { html: "" }, questions: { questions: [] }, services: { select: "single", items: [], feeds_invoice: true, required: true },
  contract: { html: "<h2>Agreement</h2><p></p>", fields: [], required: true, signers: [] }, invoice: { schedule: [{ id: nid(), label: "Full payment", pct: 100, due: { type: "on_signing" } }] },
  scheduler: { session_type_id: null, reserve_requires: [] }, timeline: { items: [] }, thankyou: { html: "<h2>Thank you!</h2>" },
  retainer: { name: "Advisory retainer", kind: "hours", period: "monthly", fee_paise: 0, included_hours: 20, billing: "advance",
    rollover: { mode: "capped", cap_hours: 5, valid_periods: 1 }, overage: { mode: "bill" } } }[type] || {}) });

export default function Builder() {
  const { id, tid } = useParams();
  const isTpl = !!tid;
  const q = useAct(isTpl ? "templates.get" : "files.get", { id: id || tid });
  if (q.isLoading) return <div className="p-6"><SkeletonList rows={6} /></div>;
  if (q.isError) return <div className="p-6"><Card>{q.error.message}</Card></div>;
  return <Editor initial={q.data} isTpl={isTpl} reload={() => q.refetch()} />;
}

function Editor({ initial, isTpl, reload }) {
  const nav = useNavigate();
  const ws = useWs();
  const [title, setTitle] = useState(isTpl ? initial.name : initial.title);
  const [pages, setPages] = useState(isTpl ? initial.body.pages : initial.pages);
  const [hist, setHist] = useState({ past: [], future: [] });
  const [pi, setPi] = useState(0);
  const [sel, setSel] = useState(null);
  const [panel, setPanel] = useState(null); // preview | send | versions | add
  const [addAt, setAddAt] = useState(0);
  const [server, setServer] = useState(initial);
  const save = async ({ title, pages }) => {
    if (isTpl) await act("templates.save", { id: initial.id, kind: "file", name: title, body: { pages } });
    else setServer(await act("files.update", { id: initial.id, title, pages }));
  };
  const state = useAutosave({ title, pages }, save);
  useEffect(() => {
    if (isTpl || !server.pages) return;
    // Pick up ids the server added (invoices, signers) without losing typing.
    setPages((cur) => cur.map((pg, i) => ({ ...pg, blocks: pg.blocks.map((b) => {
      const sb = server.pages[i]?.blocks.find((x) => x.id === b.id);
      return sb && (sb.invoice_id || sb.signers?.length) ? { ...b, invoice_id: sb.invoice_id || b.invoice_id, signers: b.signers?.length ? b.signers : sb.signers } : b;
    }) })));
  }, [server]); // eslint-disable-line
  function change(next) { setHist({ past: [...hist.past.slice(-40), pages], future: [] }); setPages(next); }
  const undo = () => { if (!hist.past.length) return; setHist({ past: hist.past.slice(0, -1), future: [pages, ...hist.future] }); setPages(hist.past[hist.past.length - 1]); };
  const redo = () => { if (!hist.future.length) return; setHist({ past: [...hist.past, pages], future: hist.future.slice(1) }); setPages(hist.future[0]); };
  const page = pages[pi] || pages[0];
  const block = page?.blocks.find((b) => b.id === sel);
  const setPage = (p) => change(pages.map((x, i) => (i === pi ? p : x)));
  const setBlock = (b) => setPage({ ...page, blocks: page.blocks.map((x) => (x.id === b.id ? b : x)) });
  function addBlock(type) { const b = fresh(type); const bl = [...page.blocks]; bl.splice(addAt, 0, b); setPage({ ...page, blocks: bl }); setSel(b.id); setPanel(null); }
  function move(i, d) { const bl = [...page.blocks]; const j = i + d; if (j < 0 || j >= bl.length) return; [bl[i], bl[j]] = [bl[j], bl[i]]; setPage({ ...page, blocks: bl }); }
  const allFields = pages.flatMap((p) => p.blocks.filter((b) => b.type === "contract").flatMap((b) => b.fields || []));
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  useEffect(() => {
    const k = (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); } };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  });

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-hairline bg-bg/90 px-3 backdrop-blur md:px-5">
        <button onClick={() => nav(isTpl ? "/files" : `/projects/${initial.project_id}?tab=files`)} className="grid h-11 w-11 place-items-center rounded-full hover:bg-panel" aria-label="Back"><ArrowLeft size={19} /></button>
        <input className="min-w-0 flex-1 bg-transparent text-[17px] font-extrabold focus:outline-none" value={title} onChange={(e) => setTitle(e.target.value)} />
        <span className="hidden text-[12px] text-ivory-35 md:inline">{{ saved: "Saved", saving: "Saving…", unsaved: "Unsaved", error: "Couldn't save" }[state]}</span>
        <button onClick={undo} disabled={!hist.past.length} className="grid h-10 w-10 place-items-center rounded-full disabled:opacity-30" aria-label="Undo"><Undo2 size={17} /></button>
        <button onClick={redo} disabled={!hist.future.length} className="grid h-10 w-10 place-items-center rounded-full disabled:opacity-30" aria-label="Redo"><Redo2 size={17} /></button>
        {!isTpl && <Button size="sm" variant="quiet" icon={Eye} onClick={() => setPanel("preview")} className="hidden md:inline-flex">Preview as client</Button>}
        {!isTpl && <Button size="sm" variant="quiet" icon={History} onClick={() => setPanel("versions")} className="hidden md:inline-flex">Versions</Button>}
        {!isTpl && <Button size="sm" variant="quiet" icon={Save} onClick={async () => { const n = prompt("Template name", title); if (n) { await save({ title, pages }); await act("files.save_as_template", { id: initial.id, name: n }); toast("Saved as a template"); } }} className="hidden lg:inline-flex">Save as template</Button>}
        {!isTpl && <Button size="sm" variant="primary" icon={Send} onClick={async () => { await save({ title, pages }); setPanel("send"); }}>{server.version ? "Resend" : "Send"}</Button>}
      </header>

      <div className="mx-auto grid max-w-[1400px] gap-4 p-3 md:grid-cols-[220px_1fr] md:p-5 xl:grid-cols-[220px_1fr_360px]">
        <aside className="md:sticky md:top-20 md:self-start">
          <Kicker className="mb-2">Pages</Kicker>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={(e) => {
            if (!e.over || e.active.id === e.over.id) return;
            const a = pages.findIndex((p) => p.id === e.active.id), b = pages.findIndex((p) => p.id === e.over.id);
            change(arrayMove(pages, a, b)); setPi(b);
          }}>
            <SortableContext items={pages.map((p) => p.id)} strategy={verticalListSortingStrategy}>
              <div className="scroll-x flex gap-2 md:flex-col">{pages.map((p, i) => <PageItem key={p.id} p={p} i={i} on={i === pi} onClick={() => { setPi(i); setSel(null); }} />)}</div>
            </SortableContext>
          </DndContext>
          <Button size="sm" variant="quiet" icon={Plus} className="mt-2 w-full" onClick={() => { change([...pages, { id: nid(), title: `Page ${pages.length + 1}`, button: "Continue", blocks: [] }]); setPi(pages.length); }}>Add page</Button>
          {server.issues?.length > 0 && <Card className="mt-3 border-alert/40 text-[13px]"><b className="text-alert">Before sending</b><ul className="mt-1 list-disc pl-4 text-ivory-70">{server.issues.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>}
        </aside>

        <main className="min-w-0">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Input className="max-w-xs" value={page.title} onChange={(e) => setPage({ ...page, title: e.target.value })} />
            <Input className="max-w-xs" value={page.button} onChange={(e) => setPage({ ...page, button: e.target.value })} placeholder="Button text" />
            {pages.length > 1 && <button className="text-[13px] font-bold text-alert" onClick={() => { if (confirm("Delete this page?")) { change(pages.filter((_, i) => i !== pi)); setPi(0); } }}>Delete page</button>}
          </div>
          <div className="rounded-frame bg-paper p-4 text-ink shadow-float md:p-8" style={{ fontFamily: "Manrope Variable, Manrope, sans-serif" }}>
            <AddBetween onClick={() => { setAddAt(0); setPanel("add"); }} />
            {page.blocks.map((b, i) => (
              <div key={b.id}>
                <div onClick={() => setSel(b.id)} className={cx("group relative rounded-xl border-2 p-2 transition", sel === b.id ? "border-gold" : "border-transparent hover:border-[#E6E1D6]")}>
                  <BlockPreview b={b} ws={ws.data} invoice={server.invoices?.[b.invoice_id]} pages={pages} />
                  <div className={cx("absolute -top-3 right-2 flex gap-1 rounded-full bg-ink p-1 text-ivory", sel === b.id ? "flex" : "hidden group-hover:flex")}>
                    <button onClick={(e) => { e.stopPropagation(); move(i, -1); }} className="grid h-7 w-7 place-items-center" aria-label="Move up"><ArrowUp size={13} /></button>
                    <button onClick={(e) => { e.stopPropagation(); move(i, 1); }} className="grid h-7 w-7 place-items-center" aria-label="Move down"><ArrowDown size={13} /></button>
                    <button onClick={(e) => { e.stopPropagation(); const bl = [...page.blocks]; bl.splice(i + 1, 0, { ...structuredClone(b), id: nid(), invoice_id: undefined }); setPage({ ...page, blocks: bl }); }} className="grid h-7 w-7 place-items-center" aria-label="Copy"><Copy size={13} /></button>
                    <button onClick={(e) => { e.stopPropagation(); setPage({ ...page, blocks: page.blocks.filter((x) => x.id !== b.id) }); setSel(null); }} className="grid h-7 w-7 place-items-center text-alert" aria-label="Delete"><Trash2 size={13} /></button>
                  </div>
                </div>
                <AddBetween onClick={() => { setAddAt(i + 1); setPanel("add"); }} />
              </div>
            ))}
            <div className="mt-6 flex justify-center"><span className="rounded-full px-8 py-3 font-extrabold" style={{ background: ws.data?.theme?.primary || "#C9A84C", color: ws.data?.theme?.button_text || "#14151A" }}>{page.button || "Continue"}</span></div>
          </div>
        </main>

        <aside className="hidden xl:block xl:sticky xl:top-20 xl:max-h-[calc(100vh-6rem)] xl:self-start xl:overflow-y-auto">
          {block ? <Settings b={block} set={setBlock} fields={allFields} file={server} isTpl={isTpl} reload={reload} /> : <Card className="text-[14px] text-ivory-70">Select a block to edit it. Use + to add blocks. Drag pages to reorder them.</Card>}
        </aside>
      </div>
      <Sheet open={!!block && window.innerWidth < 1280} onClose={() => setSel(null)} title={block ? BLOCKS.find((x) => x[0] === block.type)?.[1] : ""} wide>
        {block && <Settings b={block} set={setBlock} fields={allFields} file={server} isTpl={isTpl} reload={reload} />}
      </Sheet>
      <Sheet open={panel === "add"} onClose={() => setPanel(null)} title="Add a block">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">{BLOCKS.map(([t, l, I]) => (
          <button key={t} onClick={() => addBlock(t)} className="flex h-20 flex-col items-start justify-center gap-1 rounded-input border border-hairline px-3 text-left font-bold hover:border-gold"><I size={18} className="text-gold" />{l}</button>))}</div>
      </Sheet>
      {panel === "preview" && <PreviewSheet file={server} slug={ws.data?.slug} onClose={() => setPanel(null)} />}
      {panel === "send" && <SendSheet file={server} onClose={() => setPanel(null)} onSent={() => { reload(); setPanel(null); }} />}
      {panel === "versions" && <VersionsSheet file={server} onClose={() => setPanel(null)} />}
    </div>
  );
}

function PageItem({ p, i, on, onClick }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: p.id });
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={cx("flex shrink-0 items-center gap-1 rounded-input border px-2", on ? "border-gold bg-panel" : "border-hairline")}>
      <span {...listeners} {...attributes} className="cursor-grab text-ivory-35"><GripVertical size={14} /></span>
      <button onClick={onClick} className="h-11 min-w-0 flex-1 truncate px-1 text-left text-[14px] font-bold">{i + 1}. {p.title}</button>
    </div>
  );
}

const AddBetween = ({ onClick }) => (
  <div className="group flex h-6 items-center justify-center"><button onClick={onClick} className="grid h-6 w-6 place-items-center rounded-full bg-ink text-gold opacity-30 transition group-hover:opacity-100" aria-label="Add block"><Plus size={14} /></button></div>
);

/** What the client will see, in the light print palette. */
function BlockPreview({ b, ws, invoice, pages }) {
  const pr = ws?.profile || {};
  const gold = ws?.theme?.primary || "#C9A84C";
  const html = (h) => <div className="prose-light text-[15px] leading-relaxed [&_h1]:text-[26px] [&_h1]:font-extrabold [&_h2]:text-[20px] [&_h2]:font-extrabold [&_p]:my-1.5 [&_ul]:list-disc [&_ul]:pl-5" dangerouslySetInnerHTML={{ __html: sanitize(h) || "<p class='text-[#9a968c]'>Empty text</p>" }} />;
  switch (b.type) {
    case "text": case "thankyou": return html(b.html);
    case "image": return b.url || b.key ? <img alt="" src={b.url || `/api/uploads/${b.upload_id}`} className="max-h-72 w-full rounded-lg object-cover" style={{ objectPosition: `${b.focal?.x ?? 50}% ${b.focal?.y ?? 50}%` }} /> : <div className="grid h-32 place-items-center rounded-lg bg-[#EFEBE2] text-[#8a8579]">Image</div>;
    case "video": return <div className="grid h-40 place-items-center rounded-lg bg-[#EFEBE2] text-[#8a8579]">{b.url || "Video link"}</div>;
    case "divider": return <hr className="border-[#E6E1D6]" />;
    case "spacer": return <div className="h-8" />;
    case "company": return <div><div className="text-[12px] font-bold uppercase tracking-[0.2em]" style={{ color: "#8F7635" }}>{pr.practice_name || ws?.name}</div><div className="text-[13px] text-[#5A5D66]">{[pr.email, pr.phone, pr.website].filter(Boolean).join(" · ")}</div></div>;
    case "questions": return <div className="space-y-2">{(b.questions || []).map((q) => <div key={q.id}><div className="text-[14px] font-bold">{q.label}{q.required ? " *" : ""}</div><div className="mt-1 h-10 rounded-lg border border-[#E6E1D6] bg-white" /></div>)}{!b.questions?.length && <span className="text-[#8a8579]">Add questions</span>}</div>;
    case "services": return <div className="grid gap-2 md:grid-cols-2">{(b.items || []).map((i) => <div key={i.id} className="rounded-xl border border-[#E6E1D6] bg-white p-3"><div className="font-bold">{i.name}</div><div className="text-[13px] text-[#5A5D66]">{i.desc}</div><div className="mt-1 font-extrabold" style={{ color: "#8F7635" }}>{inr(i.price_paise)}{i.kind === "addon" ? " · add-on" : ""}</div></div>)}{!b.items?.length && <span className="text-[#8a8579]">Add packages</span>}</div>;
    case "contract": return <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">{html(b.html)}<div className="mt-3 flex gap-6 text-[13px] text-[#5A5D66]"><span>Client signature ____</span><span>Your signature ____</span></div></div>;
    case "invoice": {
      const feeds = pages.some((p) => p.blocks.some((x) => x.type === "services" && x.feeds_invoice !== false));
      return <div className="rounded-xl border border-[#E6E1D6] bg-white p-4"><div className="flex justify-between font-bold"><span>{invoice?.doc_title || "Invoice"}</span><span style={{ color: "#8F7635" }}>{invoice ? inr(invoice.totals.total) : ""}</span></div>
        <div className="text-[13px] text-[#5A5D66]">{feeds ? "Lines come from the services the client picks." : (b.lines || []).map((l) => l.name).join(", ")}</div>
        <div className="mt-2 text-[13px]">{(b.schedule || []).map((s) => `${s.label}${s.pct ? ` (${s.pct}%)` : ""}`).join(" · ")}</div><div className="mt-2 text-[13px]">Pay by UPI or bank transfer, directly to you.</div></div>;
    }
    case "scheduler": return <div className="rounded-xl border border-[#E6E1D6] bg-white p-4"><b>Pick a time</b><div className="mt-2 flex gap-2">{["10:00", "10:30", "11:00"].map((t) => <span key={t} className="rounded-full border px-3 py-1 text-[13px]" style={{ borderColor: gold }}>{t}</span>)}</div></div>;
    case "timeline": return <div className="space-y-2">{(b.items || []).map((i, k) => <div key={k} className="flex gap-3"><b className="w-24 shrink-0" style={{ color: "#8F7635" }}>{i.date}</b><span>{i.title}</span></div>)}{!b.items?.length && <span className="text-[#8a8579]">Add milestones</span>}</div>;
    case "retainer": return <div className="rounded-xl border border-[#E6E1D6] bg-white p-4"><div className="text-[11px] font-bold uppercase tracking-[0.2em]" style={{ color: "#8F7635" }}>Monthly plan</div>
      <div className="text-[18px] font-extrabold">{b.name}</div><div className="font-extrabold" style={{ color: "#8F7635" }}>{b.kind === "payg" ? `Up to ${inr(b.cap_paise || 0)}` : inr(b.fee_paise || 0)} a {b.period === "quarterly" ? "quarter" : "month"}</div>
      {b.kind === "hours" && <div className="text-[13px] text-[#5A5D66]">Includes {b.included_hours} hours. When the client completes this file, the retainer is set up.</div>}</div>;
    case "quote": return <div className="rounded-xl border border-[#E6E1D6] bg-white p-4">{(b.items || []).map((i, k) => <div key={k} className="flex justify-between border-t border-[#efebe2] py-1 first:border-0"><span>{i.label}</span><span>{inr(i.price_paise)}</span></div>)}
      <div className="mt-2 flex justify-between font-extrabold"><span>Total</span><span style={{ color: "#8F7635" }}>{inr(b.total_paise || 0)}</span></div><div className="mt-1 text-[13px] text-[#5A5D66]">Valid until {b.valid_until}. The client taps Accept.</div></div>;
    default: return null;
  }
}

function Settings({ b, set, fields, file, isTpl, reload }) {
  const types = useAct("session_types.list");
  const ctpl = useAct("templates.list", { kind: "contract" });
  const up = (k, v) => set({ ...b, [k]: v });
  const items = (k) => b[k] || [];
  const setItem = (k, i, patch) => up(k, items(k).map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const rm = (k, i) => up(k, items(k).filter((_, j) => j !== i));
  return (
    <div className="space-y-3">
      <Kicker>{titleCase(b.type)} block</Kicker>
      {["text", "thankyou"].includes(b.type) && <RichText value={b.html} onChange={(v) => up("html", v)} fields={fields} />}
      {b.type === "thankyou" && <Field label="Redirect to a page after the last step (optional)"><Input value={b.redirect_url || ""} onChange={(e) => up("redirect_url", e.target.value)} placeholder="https://" /></Field>}
      {b.type === "image" && <>
        <label className="flex h-24 cursor-pointer items-center justify-center rounded-input border border-dashed border-hairline">Upload an image<input type="file" accept="image/*" className="hidden" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return; const r = await post("/api/upload", { data: await fileToDataUrl(f), name: f.name, kind: "image", client_visible: true }); set({ ...b, key: r.key, upload_id: r.id, url: "" });
        }} /></label>
        <Field label="Or an image link"><Input value={b.url || ""} onChange={(e) => up("url", e.target.value)} /></Field>
        <Field label="Focal point (keeps the subject in view on phones)"><div className="flex gap-2"><input type="range" min="0" max="100" value={b.focal?.x ?? 50} onChange={(e) => up("focal", { ...(b.focal || {}), x: +e.target.value })} className="flex-1" /><input type="range" min="0" max="100" value={b.focal?.y ?? 50} onChange={(e) => up("focal", { ...(b.focal || {}), y: +e.target.value })} className="flex-1" /></div></Field>
      </>}
      {b.type === "video" && <Field label="Video link (YouTube, Vimeo, Loom)"><Input value={b.url || ""} onChange={(e) => up("url", e.target.value)} /></Field>}
      {b.type === "questions" && <>
        {items("questions").map((q, i) => (
          <Card key={q.id} className="space-y-2 p-3">
            <Input value={q.label} onChange={(e) => setItem("questions", i, { label: e.target.value })} placeholder="Question" />
            <div className="flex gap-2"><Select value={q.kind} onChange={(e) => setItem("questions", i, { kind: e.target.value })} options={["short", "long", "single", "multi", "date", "number", "file"].map((k) => ({ value: k, label: titleCase(k) }))} />
              <Select value={q.maps_to || ""} onChange={(e) => setItem("questions", i, { maps_to: e.target.value || null })} options={[{ value: "", label: "Don't save to a field" }, { value: "contact.company", label: "Client company" }, { value: "contact.role", label: "Client role" }, { value: "project.budget", label: "Project: budget" }]} /></div>
            {["single", "multi"].includes(q.kind) && <Input value={(q.options || []).join(", ")} onChange={(e) => setItem("questions", i, { options: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} placeholder="Options, separated by commas" />}
            <div className="flex justify-between"><Toggle on={!!q.required} onChange={(v) => setItem("questions", i, { required: v })} label="Required" /><button className="text-[13px] text-alert" onClick={() => rm("questions", i)}>Remove</button></div>
          </Card>))}
        <Button size="sm" icon={Plus} onClick={() => up("questions", [...items("questions"), { id: nid(), label: "", kind: "short", required: false }])}>Add question</Button>
      </>}
      {b.type === "services" && <>
        <Segmented value={b.select || "single"} onChange={(v) => up("select", v)} options={[{ value: "single", label: "Client picks one" }, { value: "multi", label: "Client picks any" }]} />
        <Toggle on={b.feeds_invoice !== false} onChange={(v) => up("feeds_invoice", v)} label="The client's choice fills the invoice" />
        <Toggle on={b.required !== false} onChange={(v) => up("required", v)} label="A choice is required" />
        {items("items").map((it, i) => (
          <Card key={it.id} className="space-y-2 p-3">
            <Input value={it.name} onChange={(e) => setItem("items", i, { name: e.target.value })} placeholder="Package name" />
            <Input value={it.desc || ""} onChange={(e) => setItem("items", i, { desc: e.target.value })} placeholder="What's included" />
            <div className="flex gap-2"><MoneyInput paise={it.price_paise} onChange={(v) => setItem("items", i, { price_paise: v || 0 })} />
              <Select value={it.kind || "package"} onChange={(e) => setItem("items", i, { kind: e.target.value })} options={[{ value: "package", label: "Package" }, { value: "addon", label: "Add-on" }]} /></div>
            <button className="text-[13px] text-alert" onClick={() => rm("items", i)}>Remove</button>
          </Card>))}
        <Button size="sm" icon={Plus} onClick={() => up("items", [...items("items"), { id: nid(), name: "", desc: "", price_paise: 0, qty: 1, kind: "package" }])}>Add package</Button>
      </>}
      {b.type === "contract" && <>
        <Select value="" onChange={async (e) => { if (!e.target.value) return; const t = await act("templates.get", { id: e.target.value }); up("html", t.body.html); }} options={[{ value: "", label: "Start from a contract template…" }, ...(ctpl.data || []).map((t) => ({ value: t.id, label: t.name }))]} />
        <RichText value={b.html} onChange={(v) => up("html", v)} fields={b.fields || []} />
        <Toggle on={b.required !== false} onChange={(v) => up("required", v)} label="Must be signed before the invoice page opens" />
        <Kicker>Fields</Kicker>
        {items("fields").map((fl, i) => (
          <div key={i} className="grid grid-cols-2 gap-2">
            <Input value={fl.label} onChange={(e) => setItem("fields", i, { label: e.target.value, key: fl.key || e.target.value.toLowerCase().replace(/\W+/g, "_") })} placeholder="Label" />
            <Select value={fl.permission} onChange={(e) => setItem("fields", i, { permission: e.target.value })} options={[{ value: "consultant", label: "I fill it" }, { value: "client_edit", label: "Client can edit" }, { value: "client_must_fill", label: "Client must fill" }]} />
            {fl.permission === "consultant" && <Input className={cx("col-span-2", !fl.value && "border-alert")} value={fl.value || ""} onChange={(e) => setItem("fields", i, { value: e.target.value })} placeholder={`Value for ${fl.label}`} />}
          </div>))}
        <Button size="sm" icon={Plus} onClick={() => up("fields", [...items("fields"), { key: `f${items("fields").length + 1}`, label: "New field", permission: "consultant", value: "" }])}>Add field</Button>
        <p className="text-[12px] text-ivory-35">Insert a field in the text with "Insert field…". Fields you fill show red until filled, and sending waits for them.</p>
        {!isTpl && file.version > 0 && <Button size="sm" icon={PenLine} onClick={async () => { const n = prompt("Type your full name to sign"); if (n) { try { await act("files.consultant_sign", { id: file.id, block_id: b.id, name: n }); toast("Signed"); reload(); } catch (e) { toast(e.message, "error"); } } }}>Sign as consultant</Button>}
      </>}
      {b.type === "invoice" && <InvoiceSettings b={b} up={up} />}
      {b.type === "scheduler" && <>
        <Field label="Session type"><Select value={b.session_type_id || ""} onChange={(e) => up("session_type_id", e.target.value || null)} options={[{ value: "", label: "Choose…" }, ...(types.data || []).map((t) => ({ value: t.id, label: t.name }))]} /></Field>
        <Toggle on={(b.reserve_requires || []).includes("sign")} onChange={(v) => up("reserve_requires", v ? [...(b.reserve_requires || []), "sign"] : (b.reserve_requires || []).filter((x) => x !== "sign"))} label="Confirm the slot only after signing" />
        <Toggle on={(b.reserve_requires || []).includes("pay")} onChange={(v) => up("reserve_requires", v ? [...(b.reserve_requires || []), "pay"] : (b.reserve_requires || []).filter((x) => x !== "pay"))} label="Confirm the slot only after payment" />
      </>}
      {b.type === "timeline" && <>
        {items("items").map((it, i) => <div key={i} className="flex gap-2"><Input className="w-32" value={it.date} onChange={(e) => setItem("items", i, { date: e.target.value })} placeholder="Week 1" /><Input value={it.title} onChange={(e) => setItem("items", i, { title: e.target.value })} /><button onClick={() => rm("items", i)} aria-label="Remove"><Trash2 size={15} /></button></div>)}
        <Button size="sm" icon={Plus} onClick={() => up("items", [...items("items"), { date: "", title: "" }])}>Add milestone</Button>
      </>}
      {b.type === "retainer" && <>
        <Field label="Name"><Input value={b.name || ""} onChange={(e) => up("name", e.target.value)} /></Field>
        <Field label="Kind"><Select value={b.kind} onChange={(e) => up("kind", e.target.value)} options={[{ value: "hours", label: "Hours bank" }, { value: "fixed", label: "Fixed scope" }, { value: "payg", label: "Pay as used, capped" }]} /></Field>
        <Field label="Period"><Select value={b.period} onChange={(e) => up("period", e.target.value)} options={[{ value: "monthly", label: "Monthly" }, { value: "quarterly", label: "Quarterly" }]} /></Field>
        {b.kind !== "payg" ? <Field label="Fee each period"><MoneyInput paise={b.fee_paise} onChange={(v) => up("fee_paise", v || 0)} /></Field>
          : <Field label="Cap each period"><MoneyInput paise={b.cap_paise} onChange={(v) => up("cap_paise", v || 0)} /></Field>}
        {b.kind === "hours" && <Field label="Hours included"><Input inputMode="decimal" value={b.included_hours || ""} onChange={(e) => up("included_hours", Number(e.target.value) || 0)} /></Field>}
        <Field label="Unused hours"><Select value={b.rollover?.mode || "none"} onChange={(e) => up("rollover", { ...(b.rollover || {}), mode: e.target.value })} options={[{ value: "none", label: "Lapse" }, { value: "capped", label: "Carry up to a cap" }, { value: "all", label: "Carry everything" }]} /></Field>
        <Field label="Extra time"><Select value={b.overage?.mode || "bill"} onChange={(e) => up("overage", { ...(b.overage || {}), mode: e.target.value })} options={[{ value: "bill", label: "Bill it" }, { value: "borrow", label: "Borrow from next period" }, { value: "absorb", label: "Absorb" }, { value: "ask", label: "Ask me first" }]} /></Field>
        <p className="text-[12px] text-ivory-35">When the client completes this file (or signs), the retainer is created and its first period opens.</p>
      </>}
      {b.type === "quote" && <p className="text-[14px] text-ivory-70">Made from an estimate. To change it, make a new version of the estimate and a new quote.</p>}
      {["company", "divider", "spacer"].includes(b.type) && <p className="text-[14px] text-ivory-70">{b.type === "company" ? "Shows your logo and contact details from Settings." : "Nothing to set."}</p>}
    </div>
  );
}

function InvoiceSettings({ b, up }) {
  const sched = b.schedule || [];
  const set = (i, patch) => up("schedule", sched.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const total = sched.reduce((a, s) => a + (s.amount_paise_fixed ? 0 : Number(s.pct || 0)), 0);
  return (
    <>
      <Kicker>Payment schedule</Kicker>
      {sched.map((s, i) => (
        <Card key={s.id || i} className="space-y-2 p-3">
          <Input value={s.label} onChange={(e) => set(i, { label: e.target.value })} />
          <div className="flex gap-2">
            <Input inputMode="numeric" className="w-24" value={s.pct ?? ""} onChange={(e) => set(i, { pct: Number(e.target.value.replace(/\D/g, "")) || 0, amount_paise_fixed: null })} placeholder="%" />
            <Select value={s.due?.type || "on_signing"} onChange={(e) => set(i, { due: { ...(s.due || {}), type: e.target.value } })} options={[{ value: "on_signing", label: "Due on signing" }, { value: "date", label: "On a date" },
              { value: "after_previous", label: "Days after the previous payment" }, { value: "relative_project", label: "Days from project start" }, { value: "milestone", label: "On a milestone" }]} />
          </div>
          {s.due?.type === "date" && <input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-2" value={(s.due.date || "").slice(0, 10)} onChange={(e) => set(i, { due: { ...s.due, date: e.target.value } })} />}
          {["after_previous", "relative_project"].includes(s.due?.type) && <Input inputMode="numeric" value={s.due.days ?? 30} onChange={(e) => set(i, { due: { ...s.due, days: Number(e.target.value.replace(/[^\d-]/g, "")) || 0 } })} placeholder="Days" />}
          {s.due?.type === "milestone" && <Input value={s.due.milestone || ""} onChange={(e) => set(i, { due: { ...s.due, milestone: e.target.value } })} placeholder="Milestone name, e.g. Report delivered" />}
          {sched.length > 1 && <button className="text-[13px] text-alert" onClick={() => up("schedule", sched.filter((_, j) => j !== i))}>Remove</button>}
        </Card>
      ))}
      <div className="flex items-center justify-between"><Button size="sm" icon={Plus} onClick={() => up("schedule", [...sched, { id: nid(), label: "Balance", pct: 0, due: { type: "after_previous", days: 30 } }])}>Add payment</Button>
        <span className={cx("text-[13px]", total === 100 ? "text-ivory-70" : "text-alert")}>{total}% of 100%</span></div>
      <Toggle on={!!b.client_choice} onChange={(v) => up("client_choice", v)} label="Let the client choose: pay in full or split monthly" />
      <p className="text-[12px] text-ivory-35">Clients pay you directly by UPI or bank transfer. Amounts are kept in paise, so totals are exact.</p>
    </>
  );
}

function PreviewSheet({ file, slug, onClose }) {
  const [w, setW] = useState(390);
  return (
    <Sheet open onClose={onClose} title="Preview as client" wide>
      <Segmented value={w} onChange={setW} options={[{ value: 390, label: "Phone" }, { value: 1280, label: "Desktop" }]} />
      <div className="mt-3 overflow-auto rounded-frame border border-hairline bg-white" style={{ height: "70vh" }}>
        <iframe title="preview" src={`/c/${slug}/preview/${file.id}`} style={{ width: w, height: "100%", border: 0, display: "block", margin: "0 auto" }} />
      </div>
    </Sheet>
  );
}

function SendSheet({ file, onClose, onSent }) {
  const [ch, setCh] = useState("email");
  const [msg, setMsg] = useState("");
  const [when, setWhen] = useState("");
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const resend = file.version > 0;
  async function go() {
    setBusy(true);
    try {
      const r = await act("files.send", { id: file.id, channel: ch, message: msg, notify_client: notify, schedule_at: when ? new Date(when).toISOString() : null });
      if (r.scheduled) { toast("Scheduled"); onSent(); } else setDone(r);
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  if (done) return (
    <Sheet open onClose={onSent} title="Sent">
      <p>Version {done.version} is live. You'll be told when the client opens it, reaches each page, and completes it.</p>
      <div className="mt-3 flex items-center gap-2 rounded-input bg-panel-raised p-3 text-[14px]"><span className="min-w-0 flex-1 truncate">{done.link}</span><button onClick={() => { navigator.clipboard?.writeText(done.link); toast("Link copied"); }}><Copy size={15} /></button></div>
      {resend && <ul className="mt-3 list-disc pl-5 text-[14px] text-ivory-70">{done.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>}
      <Button className="mt-4 w-full" variant="primary" onClick={onSent}>Done</Button>
    </Sheet>
  );
  return (
    <Sheet open onClose={onClose} title={resend ? "Resend with changes" : "Send to client"}>
      <div className="space-y-3">
        {file.issues?.length > 0 && <Card className="border-alert/40 text-[14px]"><b className="text-alert">Fix these first</b><ul className="mt-1 list-disc pl-5">{file.issues.map((x, i) => <li key={i}>{x}</li>)}</ul></Card>}
        <Segmented value={ch} onChange={setCh} options={[{ value: "email", label: "Email" }, { value: "whatsapp", label: "WhatsApp" }, { value: "both", label: "Both" }, { value: "link", label: "Just the link" }]} />
        <Field label="Message (optional)"><textarea className="w-full rounded-input border border-hairline bg-panel px-3 py-3" rows={3} value={msg} onChange={(e) => setMsg(e.target.value)} /></Field>
        {resend && <Toggle on={notify} onChange={setNotify} label="Tell the client what changed" />}
        <Field label="Send later (optional)"><input type="datetime-local" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <Button variant="primary" size="lg" className="w-full" busy={busy} disabled={file.issues?.length > 0} onClick={go}>{when ? "Schedule" : resend ? "Resend" : "Send"}</Button>
      </div>
    </Sheet>
  );
}

function VersionsSheet({ file, onClose }) {
  return (
    <Sheet open onClose={onClose} title="Versions and tracking" wide>
      {!file.versions?.length && <p className="text-ivory-70">Not sent yet. Each send becomes a version.</p>}
      {file.versions?.map((v) => (
        <Card key={v.version} className="mb-2"><b>Version {v.version}</b> <span className="text-[13px] text-ivory-35">{dt(v.sent_at)}</span>
          <ul className="mt-1 list-disc pl-5 text-[14px] text-ivory-70">{v.changes.map((c, i) => <li key={i}>{c}</li>)}</ul></Card>
      ))}
      <Kicker className="mb-2 mt-4">What the client did</Kicker>
      {(file.events || []).map((e) => <div key={e.id} className="flex gap-2 border-t border-hairline py-2 text-[14px]"><Chip>{titleCase(e.type)}</Chip>{e.page !== undefined && e.type === "page" ? `Reached page ${e.page + 1}` : ""}<span className="ml-auto text-ivory-35">{dt(e.at)}</span></div>)}
      {(file.signatures || []).length > 0 && <Kicker className="mb-2 mt-4">Signatures</Kicker>}
      {(file.signatures || []).map((s) => <div key={s.id} className="text-[14px]"><b>{s.name}</b> ({s.role}) · {s.signed_at_ist} · <span className={s.status === "cancelled" ? "text-alert" : "text-ivory-70"}>{s.status}</span><div className="break-all font-mono text-[11px] text-ivory-35">{s.doc_hash}</div></div>)}
    </Sheet>
  );
}

export { useMemo };
