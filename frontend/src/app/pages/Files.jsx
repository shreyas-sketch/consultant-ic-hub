import { useState } from "react";
import { useNavigate } from "react-router";
import { Download, FileText, Mail, Plus, ScrollText } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { ago, titleCase } from "../../lib/format";
import RichText from "../components/RichText";
import { Button, Card, Chip, Empty, Field, Input, Loadable, PageHeader, Sheet, Tabs, toast } from "../components/ui";
import { StatusChip } from "./Project";

const KINDS = [["file", "Client files"], ["email", "Emails"], ["contract", "Contracts"], ["invoice", "Invoices"], ["package", "Service packages"]];

export default function Files() {
  const [tab, setTab] = useState("recent");
  return (
    <div>
      <PageHeader kicker="Files & templates" title="Never write the same thing" accent="twice" sub="Your templates, the starter gallery for consultants, and recent client files." />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "recent", label: "Recent files" }, ...KINDS.map(([v, l]) => ({ value: v, label: l })), { value: "gallery", label: "Gallery" }]} />
      {tab === "recent" && <Recent />}
      {KINDS.some(([k]) => k === tab) && <Templates kind={tab} />}
      {tab === "gallery" && <Gallery />}
    </div>
  );
}

function Recent() {
  const q = useAct("files.list", {});
  const nav = useNavigate();
  return (
    <Loadable q={q} empty={<Empty title="No client files yet" line="Create one from a project: a proposal, a booking file or a questionnaire." />}>
      {(rows) => <div className="space-y-2">{rows.map((f) => (
        <Card key={f.id} className="flex items-center gap-3"><FileText size={18} className="text-gold" />
          <button className="min-w-0 flex-1 text-left" onClick={() => nav(`/files/${f.id}`)}><b className="block truncate">{f.title}</b><span className="text-[13px] text-ivory-70">{f.project_name} · {ago(f.updated_at)}</span></button>
          <StatusChip s={f.status} /></Card>))}</div>}
    </Loadable>
  );
}

function Templates({ kind }) {
  const q = useAct("templates.list", { kind });
  const nav = useNavigate();
  const [edit, setEdit] = useState(null);
  async function newOne() {
    if (kind === "file") {
      const t = await act("templates.save", { kind: "file", name: "New template", body: { pages: [{ title: "Page 1", button: "Continue", blocks: [{ type: "text", html: "" }] }] } });
      nav(`/templates/${t.id}`);
    } else setEdit({ kind, name: "", body: kind === "email" ? { subject: "", html: "" } : kind === "contract" ? { html: "" } : kind === "invoice" ? { lines: [] } : { name: "", price_paise: 0 } });
  }
  return (
    <>
      <Button size="sm" icon={Plus} className="mb-3" onClick={newOne}>New template</Button>
      <Loadable q={q} empty={<Empty title="No templates of this kind yet" line="Start from the gallery or write your own." />}>
        {(rows) => <div className="grid gap-2 md:grid-cols-2">{rows.map((t) => (
          <Card key={t.id} className="flex items-center gap-3">
            {kind === "email" ? <Mail size={17} className="text-gold" /> : <ScrollText size={17} className="text-gold" />}
            <button className="min-w-0 flex-1 truncate text-left font-bold" onClick={async () => kind === "file" ? nav(`/templates/${t.id}`) : setEdit(await act("templates.get", { id: t.id }))}>{t.name}</button>
            {t.by_setup && <Chip tone="teal">Written by the Setup agent</Chip>}
          </Card>))}</div>}
      </Loadable>
      {edit && <TemplateSheet t={edit} onClose={() => { setEdit(null); q.refetch(); }} />}
    </>
  );
}

function TemplateSheet({ t, onClose }) {
  const [name, setName] = useState(t.name);
  const [body, setBody] = useState(t.body || {});
  async function save() {
    try { await act("templates.save", { id: t.id, kind: t.kind, name, body }); toast("Template saved"); onClose(); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <Sheet open onClose={onClose} title={titleCase(t.kind) + " template"} wide>
      <div className="space-y-3">
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        {t.kind === "email" && <Field label="Subject"><Input value={body.subject || ""} onChange={(e) => setBody({ ...body, subject: e.target.value })} /></Field>}
        {(t.kind === "email" || t.kind === "contract") && <RichText value={body.html} onChange={(html) => setBody({ ...body, html })} />}
        {t.kind === "package" && <><Field label="Description"><Input value={body.desc || ""} onChange={(e) => setBody({ ...body, desc: e.target.value })} /></Field>
          <Field label="Price (₹)"><Input inputMode="decimal" value={(body.price_paise || 0) / 100} onChange={(e) => setBody({ ...body, price_paise: Math.round(Number(e.target.value || 0) * 100) })} /></Field></>}
        {t.kind === "invoice" && (body.lines || []).map((l, i) => (
          <div key={i} className="flex gap-2"><Input value={l.name} onChange={(e) => { const ls = [...body.lines]; ls[i] = { ...l, name: e.target.value }; setBody({ ...body, lines: ls }); }} />
            <Input className="w-36" inputMode="decimal" value={l.price_paise / 100} onChange={(e) => { const ls = [...body.lines]; ls[i] = { ...l, price_paise: Math.round(Number(e.target.value || 0) * 100) }; setBody({ ...body, lines: ls }); }} /></div>
        ))}
        {t.kind === "invoice" && <Button size="sm" onClick={() => setBody({ ...body, lines: [...(body.lines || []), { name: "", qty: 1, price_paise: 0 }] })}>Add line</Button>}
        <Button variant="primary" className="w-full" onClick={save}>Save</Button>
      </div>
    </Sheet>
  );
}

function Gallery() {
  const q = useAct("templates.gallery");
  return (
    <Loadable q={q}>
      {(rows) => <div className="grid gap-2 md:grid-cols-2">{rows.map((g) => (
        <Card key={g.key} className="flex items-center gap-3"><Chip>{titleCase(g.kind)}</Chip><b className="min-w-0 flex-1 truncate">{g.name}</b>
          <Button size="sm" variant="quiet" icon={Download} onClick={async () => { await act("templates.install", { key: g.key }); toast("Copied to your templates"); }}>Use</Button></Card>))}</div>}
    </Loadable>
  );
}
