import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { act, useAct } from "../../lib/api";
import { date, inr } from "../../lib/format";
import { Button, Card, Empty, Input, Kicker, Loadable, PageHeader, RowLink, Sheet, Stat, toast, useDebounced } from "../components/ui";
import { StatusChip } from "./Project";

export default function Contacts() {
  const { id } = useParams();
  return id ? <Contact id={id} /> : <List />;
}

function List() {
  const [q, setQ] = useState("");
  const dq = useDebounced(q);
  const r = useAct("contacts.search", { q: dq, limit: 200 });
  const nav = useNavigate();
  return (
    <div>
      <PageHeader kicker="Contacts" title="Find a person," accent="see all their work" sub="Leads and clients. Search by name, phone, email or company." />
      <Input placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" />
      <Loadable q={r} empty={<Empty title="No contacts yet" line="Contacts are added when leads come in, or by import." />}>
        {(d) => <Card className="p-1">{d.items.map((c) => <RowLink key={c.id} title={c.name} sub={[c.company, c.phone, c.email].filter(Boolean).join(" · ")} onClick={() => nav(`/contacts/${c.id}`)} />)}</Card>}
      </Loadable>
    </div>
  );
}

function Contact({ id }) {
  const q = useAct("contacts.get", { id });
  const nav = useNavigate();
  const [edit, setEdit] = useState(false);
  return (
    <Loadable q={q}>
      {(c) => (
        <div>
          <PageHeader kicker={c.company || "Contact"} title={c.name} sub={[c.phone, c.email].filter(Boolean).join(" · ")}
            right={<><Button size="sm" variant="quiet" onClick={() => setEdit(true)}>Edit</Button>
              <Button size="sm" variant="primary" onClick={async () => { const p = await act("projects.create", { name: `${c.name} — new project`, contact_ids: [c.id] }); nav(`/projects/${p.id}`); }}>New project</Button></>} />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <Stat label="Total value" value={inr(c.total_value_paise, { short: true })} />
            <Stat label="Received" value={inr(c.received_paise, { short: true })} />
            <Stat label="Messages" value={c.messages} gold={false} />
          </div>
          <Kicker className="mb-2 mt-6">Projects</Kicker>
          <Card className="p-1">{c.projects.map((p) => <RowLink key={p.id} title={p.name} sub={`Created ${date(p.created_at)}`} right={p.booked ? <StatusChip s="completed" /> : null} onClick={() => nav(`/projects/${p.id}`)} />)}</Card>
          {c.enrichment?.website && <p className="mt-3 text-[14px] text-teal">Lead enrichment found: {c.enrichment.website}</p>}
          <EditSheet open={edit} onClose={() => { setEdit(false); q.refetch(); }} c={c} />
        </div>
      )}
    </Loadable>
  );
}

function EditSheet({ open, onClose, c }) {
  const [f, setF] = useState({ name: c.name, phone: c.phone, email: c.email, company: c.company, role: c.role });
  return (
    <Sheet open={open} onClose={onClose} title="Edit contact">
      <div className="space-y-2">
        {["name", "phone", "email", "company", "role"].map((k) => <Input key={k} placeholder={k} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />)}
        <Button variant="primary" className="w-full" onClick={async () => { try { await act("contacts.update", { id: c.id, ...f }); toast("Saved"); onClose(); } catch (e) { toast(e.message, "error"); } }}>Save</Button>
      </div>
    </Sheet>
  );
}
