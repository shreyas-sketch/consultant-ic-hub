import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowDown, ArrowUp, Copy, Plus, Trash2 } from "lucide-react";
import { act, fileToDataUrl, get, post, useAct, useRefresh } from "@/shared/api";
import { dt, titleCase } from "@/shared/lib/format";
import { useWs } from "@/app/layout/AppShell";
import { ChecklistsSection, ConnectedApps, RatesSection, WinChances } from "@/app/features/settings/SettingsRates";
import { Button, Card, Chip, Field, Input, Kicker, Loadable, MoneyInput, PageHeader, Segmented, Select, Sheet, Toggle, cx, toast } from "@/app/ui";

const SECTIONS = [["profile", "Practice"], ["branding", "Client pages"], ["invoice", "Invoices and payment"], ["rates", "Services and rates"], ["pipeline", "Pipeline"],
  ["checklists", "Checklists"], ["lists", "Lists and fields"],
  ["team", "Team"], ["forms", "Lead forms"], ["connections", "Connected accounts"], ["messages", "Messages"], ["connector", "AI connector"], ["audit", "Audit log"]];

export default function Settings() {
  const { section = "profile" } = useParams();
  const nav = useNavigate();
  const ws = useWs();
  return (
    <div>
      <PageHeader kicker="Settings" title="Your practice," accent="your way" />
      <div className="md:grid md:grid-cols-[220px_1fr] md:gap-6">
        <nav className="scroll-x mb-4 flex gap-1 md:flex-col">
          {SECTIONS.map(([k, l]) => <button key={k} onClick={() => nav(`/settings/${k}`)} className={cx("h-11 whitespace-nowrap rounded-input px-3 text-left text-[14px] font-bold", section === k ? "bg-panel-raised text-gold" : "text-ivory-70 hover:bg-panel")}>{l}</button>)}
        </nav>
        <Loadable q={ws}>
          {(w) => (
            <div className="min-w-0 space-y-4">
              {section === "profile" && <Profile w={w} />}
              {section === "branding" && <Branding w={w} />}
              {section === "invoice" && <InvoiceSet w={w} />}
              {section === "pipeline" && <><Pipeline w={w} /><WinChances w={w} /></>}
              {section === "rates" && <RatesSection w={w} />}
              {section === "checklists" && <ChecklistsSection w={w} />}
              {section === "lists" && <Lists w={w} />}
              {section === "team" && <Team w={w} />}
              {section === "forms" && <Forms w={w} />}
              {section === "connections" && <Connections />}
              {section === "messages" && <Messages w={w} />}
              {section === "connector" && <><ConnectedApps /><Connector /></>}
              {section === "audit" && <Audit />}
            </div>
          )}
        </Loadable>
      </div>
    </div>
  );
}

function useSave() {
  const refresh = useRefresh();
  return async (body, msg = "Saved") => {
    try { await act("workspace.update", body); refresh("workspace"); toast(msg); return true; } catch (e) { toast(e.message, "error"); return false; }
  };
}

function Profile({ w }) {
  const save = useSave();
  const [p, setP] = useState(w.profile);
  const [goal, setGoal] = useState(w.settings.revenue_goal_paise);
  return (
    <Card className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {[["practice_name", "Practice name"], ["consultant_name", "Your name"], ["email", "Email"], ["phone", "Phone"], ["website", "Website"], ["address", "Address"]].map(([k, l]) => (
          <Field key={k} label={l}><Input value={p[k] || ""} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></Field>))}
        <Field label="State (for GST place of supply)"><Input value={p.state || ""} onChange={(e) => setP({ ...p, state: e.target.value })} /></Field>
        <Field label="Yearly revenue goal"><MoneyInput paise={goal} onChange={(v) => setGoal(v || 0)} /></Field>
      </div>
      <Button variant="primary" onClick={() => save({ name: p.practice_name, profile: p, settings: { revenue_goal_paise: goal } })}>Save</Button>
    </Card>
  );
}

function Branding({ w }) {
  const save = useSave();
  const [t, setT] = useState(w.theme);
  const refresh = useRefresh();
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="space-y-3">
        <Kicker>Client pages</Kicker>
        <p className="text-[14px] text-ivory-70">Proposals, contracts, invoices, booking pages and the portal use these. Your clients never see our name.</p>
        <label className="flex h-20 cursor-pointer items-center justify-center rounded-input border border-dashed border-hairline">{t.logo_key ? "Change logo" : "Upload your logo"}
          <input type="file" accept="image/png,image/jpeg" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; await post("/api/upload", { data: await fileToDataUrl(f), name: "logo.png", kind: "logo" }); refresh("workspace"); toast("Logo saved"); }} /></label>
        {[["primary", "Button colour"], ["button_text", "Button text colour"], ["paper", "Page background"], ["text", "Text colour"], ["sidebar", "Portal sidebar"]].map(([k, l]) => (
          <Field key={k} label={l}><div className="flex gap-2"><input type="color" value={t[k] || "#C9A84C"} onChange={(e) => setT({ ...t, [k]: e.target.value })} className="h-12 w-14 rounded-input border border-hairline bg-panel" /><Input value={t[k] || ""} onChange={(e) => setT({ ...t, [k]: e.target.value })} /></div></Field>))}
        <Segmented value={t.corners || "rounded"} onChange={(v) => setT({ ...t, corners: v })} options={[{ value: "rounded", label: "Rounded corners" }, { value: "sharp", label: "Sharp corners" }]} />
        <Field label="Portal login title"><Input value={t.login_title || ""} onChange={(e) => setT({ ...t, login_title: e.target.value })} placeholder={`Welcome to ${w.name}`} /></Field>
        <Button variant="primary" onClick={() => save({ theme: t })}>Save</Button>
      </Card>
      <div>
        <Kicker className="mb-2">Live preview</Kicker>
        <div className="p-6 shadow-float" style={{ background: t.paper, color: t.text, borderRadius: t.corners === "sharp" ? 0 : 18 }}>
          {t.logo_key ? <img alt="" src={`/api/public/logo/${w.slug}`} className="h-10" /> : <div className="text-[12px] font-bold uppercase tracking-[0.2em]" style={{ color: "#8F7635" }}>{w.profile.practice_name}</div>}
          <div className="mt-2 text-[13px] opacity-70">Step 2 of 4</div>
          <h2 className="mt-3 text-[24px] font-extrabold">Choose your package</h2>
          <div className="mt-3 border p-4" style={{ borderColor: "#E6E1D6", borderRadius: t.corners === "sharp" ? 0 : 14, background: "#fff" }}><b>Advisory retainer — 3 months</b><div className="font-extrabold" style={{ color: "#8F7635" }}>₹1,50,000</div></div>
          <div className="mt-5 py-3 text-center font-extrabold" style={{ background: t.primary, color: t.button_text, borderRadius: t.corners === "sharp" ? 0 : 999 }}>Review the agreement</div>
        </div>
        <Card className="mt-4 text-[14px]"><Kicker>Your client link</Kicker><div className="mt-1 flex items-center gap-2"><span className="truncate text-ivory-70">{location.origin}/c/{w.slug}/portal</span>
          <button onClick={() => { navigator.clipboard?.writeText(`${location.origin}/c/${w.slug}/portal`); toast("Copied"); }}><Copy size={14} /></button></div>
          <p className="mt-2 text-ivory-35">Custom domain: add a CNAME record pointing to our client domain and we issue the certificate. Ask us to switch it on.</p></Card>
      </div>
    </div>
  );
}

function InvoiceSet({ w }) {
  const save = useSave();
  const [iv, setIv] = useState(w.invoice);
  const owner = w.role === "owner";
  return (
    <Card className="space-y-3">
      <Kicker>Where clients pay you</Kicker>
      <p className="text-[14px] text-ivory-70">Clients pay you directly. We never hold your money.</p>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="UPI ID" hint={owner ? "Shown as a QR and a Pay by UPI button." : "Only the Owner can change this."}><Input disabled={!owner} value={iv.upi_id || ""} onChange={(e) => setIv({ ...iv, upi_id: e.target.value })} placeholder="name@okhdfcbank" /></Field>
        <Field label="Payee name"><Input value={iv.payee_name || ""} onChange={(e) => setIv({ ...iv, payee_name: e.target.value })} /></Field>
        {owner && ["account_name", "account_no", "ifsc", "bank_name"].map((k) => (
          <Field key={k} label={titleCase(k).replace("No", "number").replace("Ifsc", "IFSC")}><Input value={iv.bank?.[k] || ""} onChange={(e) => setIv({ ...iv, bank: { ...iv.bank, [k]: e.target.value } })} /></Field>))}
      </div>
      <Kicker className="pt-3">Invoices</Kicker>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Number prefix" hint="Numbers run in order per financial year, e.g. INV/2026-27/0001."><Input value={iv.prefix || ""} onChange={(e) => setIv({ ...iv, prefix: e.target.value.toUpperCase().slice(0, 8) })} /></Field>
        <Field label="Payment terms"><Input value={iv.terms || ""} onChange={(e) => setIv({ ...iv, terms: e.target.value })} /></Field>
      </div>
      <Toggle on={iv.gst_enabled} onChange={(v) => setIv({ ...iv, gst_enabled: v })} label="I'm registered for GST" />
      {iv.gst_enabled && <div className="grid gap-3 md:grid-cols-2">
        <Field label="GSTIN"><Input value={iv.gstin || ""} onChange={(e) => setIv({ ...iv, gstin: e.target.value.toUpperCase() })} /></Field>
        <Field label="GST rate (%)"><Input inputMode="decimal" value={(iv.tax_rate_bp || 1800) / 100} onChange={(e) => setIv({ ...iv, tax_rate_bp: Math.round(Number(e.target.value) * 100) })} /></Field></div>}
      <Toggle on={iv.tds_expected} onChange={(v) => setIv({ ...iv, tds_expected: v })} label='Show "TDS expected" on invoices' />
      <Toggle on={iv.late_fee?.enabled} onChange={(v) => setIv({ ...iv, late_fee: { ...iv.late_fee, enabled: v } })} label="Add a late fee once a payment is 30 days late" />
      {iv.late_fee?.enabled && <Field label="Late fee (%, at most 10, added once, never compounding)" hint="Your contract template must have a matching clause (the starter one does)."><Input inputMode="decimal" value={(iv.late_fee.pct_bp || 0) / 100} onChange={(e) => setIv({ ...iv, late_fee: { ...iv.late_fee, pct_bp: Math.round(Number(e.target.value) * 100) } })} /></Field>}
      <Field label="Payment reminders (days from the due date, comma separated)" hint="-3 means three days before."><Input value={(iv.reminders || []).join(", ")} onChange={(e) => setIv({ ...iv, reminders: e.target.value.split(",").map((x) => parseInt(x, 10)).filter((x) => !Number.isNaN(x)) })} /></Field>
      <Button variant="primary" onClick={() => save({ invoice: owner ? iv : Object.fromEntries(Object.entries(iv).filter(([k]) => !["upi_id", "bank"].includes(k))) })}>Save</Button>
      <p className="text-[12px] text-ivory-35">Check GST and TDS treatment with your CA.</p>
    </Card>
  );
}

function Pipeline({ w }) {
  const refresh = useRefresh();
  const [st, setSt] = useState(w.stages.map((s) => ({ id: s.id, name: s.name, group: s.group })));
  const [rules, setRules] = useState(w.settings.stage_rules || []);
  const admin = ["owner", "admin"].includes(w.role);
  const mv = (i, d) => { const a = [...st]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; setSt(a); };
  return (
    <>
      <Card className="space-y-2">
        <Kicker>Stages</Kicker><p className="text-[14px] text-ivory-70">Clients see the stage name in their portal, so keep names client-safe.</p>
        {st.map((s, i) => (
          <div key={s.id || i} className="flex items-center gap-2">
            <Input value={s.name} onChange={(e) => setSt(st.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
            <Select className="w-40" value={s.group} onChange={(e) => setSt(st.map((x, j) => (j === i ? { ...x, group: e.target.value } : x)))} options={[{ value: "opportunity", label: "Opportunity" }, { value: "booked", label: "Booked" }]} />
            <button onClick={() => mv(i, -1)} aria-label="Up"><ArrowUp size={15} /></button><button onClick={() => mv(i, 1)} aria-label="Down"><ArrowDown size={15} /></button>
            <button onClick={() => setSt(st.filter((_, j) => j !== i))} aria-label="Remove"><Trash2 size={15} /></button>
          </div>))}
        <Button size="sm" icon={Plus} onClick={() => setSt([...st, { name: "New stage", group: "booked" }])}>Add stage</Button>
      </Card>
      <Card className="space-y-2">
        <Kicker>Stage rules</Kicker><p className="text-[14px] text-ivory-70">Projects move forward by themselves when these happen, whoever or whatever sent the message. They never move a project back.</p>
        {rules.map((r, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <Toggle on={r.enabled} onChange={(v) => setRules(rules.map((x, j) => (j === i ? { ...x, enabled: v } : x)))} />
            <span className="min-w-0 flex-1 text-[14px]">{r.label} →</span>
            <Select className="w-48" value={r.stage_id} onChange={(e) => setRules(rules.map((x, j) => (j === i ? { ...x, stage_id: e.target.value } : x)))} options={w.stages.map((s) => ({ value: s.id, label: s.name }))} />
          </div>))}
      </Card>
      {admin ? <Button variant="primary" onClick={async () => { try { await act("stages.save", { stages: st, stage_rules: rules }); refresh("workspace", "projects"); toast("Pipeline saved"); } catch (e) { toast(e.message, "error"); } }}>Save pipeline</Button>
        : <p className="text-ivory-70">Only an Owner or Admin can change the pipeline.</p>}
    </>
  );
}

function Lists({ w }) {
  const save = useSave();
  const [s, setS] = useState(w.settings);
  const list = (k, l) => (
    <Field label={l} hint="Comma separated"><Input value={(s[k] || []).join(", ")} onChange={(e) => setS({ ...s, [k]: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
  );
  return (
    <Card className="space-y-3">
      {list("lead_sources", "Lead sources")}{list("project_types", "Project types")}{list("lost_reasons", "Reasons a lead is lost")}
      <Kicker className="pt-2">Custom project fields</Kicker>
      {(s.custom_fields || []).map((f, i) => (
        <div key={i} className="flex gap-2"><Input value={f.label} onChange={(e) => setS({ ...s, custom_fields: s.custom_fields.map((x, j) => (j === i ? { ...x, label: e.target.value, key: x.key || e.target.value.toLowerCase().replace(/\W+/g, "_") } : x)) })} />
          <Select className="w-40" value={f.type || "text"} onChange={(e) => setS({ ...s, custom_fields: s.custom_fields.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)) })} options={["text", "number", "date", "single", "multi"]} />
          <button onClick={() => setS({ ...s, custom_fields: s.custom_fields.filter((_, j) => j !== i) })} aria-label="Remove"><Trash2 size={15} /></button></div>))}
      <Button size="sm" icon={Plus} onClick={() => setS({ ...s, custom_fields: [...(s.custom_fields || []), { key: "", label: "", type: "text" }] })}>Add field</Button>
      <Button variant="primary" onClick={() => save({ settings: { lead_sources: s.lead_sources, project_types: s.project_types, lost_reasons: s.lost_reasons, custom_fields: s.custom_fields } })}>Save</Button>
    </Card>
  );
}

function Team({ w }) {
  const q = useAct("team.list");
  const save = useSave();
  const [f, setF] = useState({ phone: "", name: "", role: "member" });
  const admin = ["owner", "admin"].includes(w.role);
  const [hide, setHide] = useState(w.settings.hide_money_roles || []);
  return (
    <>
      <Card>
        <Kicker>Team</Kicker>
        <Loadable q={q}>{(rows) => rows.map((m) => (
          <div key={m.membership_id} className="flex flex-wrap items-center gap-2 border-t border-hairline py-3 first:border-0">
            <div className="min-w-0 flex-1"><b>{m.name || m.phone}</b> <span className="text-[13px] text-ivory-35">{m.phone}{!m.joined ? " · invited" : ""}</span></div>
            {m.role === "owner" || !admin ? <Chip tone="gold">{titleCase(m.role)}</Chip> : (
              <Select className="w-44" value={m.role} onChange={async (e) => { try { await act("team.update_role", { membership_id: m.membership_id, role: e.target.value }); q.refetch(); } catch (x) { toast(x.message, "error"); } }}
                options={["admin", "manager", "member", "collaborator"].map((r) => ({ value: r, label: titleCase(r) }))} />)}
            {admin && m.role !== "owner" && <button onClick={async () => { if (confirm("Remove this person?")) { await act("team.remove", { membership_id: m.membership_id }); q.refetch(); } }} aria-label="Remove"><Trash2 size={15} /></button>}
          </div>))}</Loadable>
      </Card>
      {admin && <Card className="space-y-2"><Kicker>Add someone</Kicker>
        <div className="grid gap-2 md:grid-cols-4"><Input placeholder="Mobile" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /><Input placeholder="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} options={["admin", "manager", "member", "collaborator"].map((r) => ({ value: r, label: titleCase(r) }))} />
          <Button variant="primary" onClick={async () => { try { await act("team.add", f); setF({ phone: "", name: "", role: "member" }); q.refetch(); toast("Added. They can log in with this number."); } catch (e) { toast(e.message, "error"); } }}>Add</Button></div>
        <p className="text-[13px] text-ivory-35">Admin: everything except bank details and deleting the practice. Manager: sees everything, works on own projects. Member: own projects only. Collaborator: only projects they're added to, no money totals, doesn't count as a seat.</p></Card>}
      {admin && <Card className="space-y-2"><Kicker>Hide money amounts</Kicker><p className="text-[14px] text-ivory-70">Hides reports and Home totals for these roles. Amounts inside files they can open still show.</p>
        {["manager", "member"].map((r) => <Toggle key={r} on={hide.includes(r)} onChange={(v) => setHide(v ? [...hide, r] : hide.filter((x) => x !== r))} label={titleCase(r)} />)}
        <Button size="sm" variant="primary" onClick={() => save({ settings: { hide_money_roles: hide } })}>Save</Button></Card>}
    </>
  );
}

function Forms({ w }) {
  const q = useAct("lead_forms.list");
  const an = useAct("lead_forms.analytics", { days: 30 });
  const [edit, setEdit] = useState(null);
  return (
    <>
      <div className="flex gap-2">{["enquiry", "discovery_call", "paid_consultation", "speaking_request", "partnership"].map((k) => (
        <Button key={k} size="sm" variant="quiet" onClick={async () => { try { await act("lead_forms.save", { name: titleCase(k), kind: k, source: "Website" }); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>+ {titleCase(k)}</Button>))}</div>
      <Loadable q={q} empty={<Card className="text-ivory-70">No forms yet. Pick a starting point above.</Card>}>
        {(rows) => rows.map((f) => {
          const stats = (an.data || []).filter((a) => a.form_id === f.id);
          const v = stats.reduce((a, s) => a + s.views, 0), sub = stats.reduce((a, s) => a + s.submits, 0);
          return (
            <Card key={f.id} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2"><b className="flex-1">{f.name}</b><Chip tone={f.live ? "gold" : "muted"}>{f.live ? "Live" : "Off"}</Chip>
                <span className="text-[13px] text-ivory-70">{v} views · {sub} submits · {v ? Math.round((100 * sub) / v) : 0}%</span><Button size="sm" variant="quiet" onClick={() => setEdit(f)}>Edit</Button></div>
              <div className="flex items-center gap-2 text-[13px]"><span className="truncate text-ivory-70">{f.link}</span><button onClick={() => { navigator.clipboard?.writeText(f.link); toast("Link copied"); }}><Copy size={14} /></button>
                <button className="font-bold text-gold" onClick={() => { navigator.clipboard?.writeText(f.embed); toast("Embed code copied"); }}>Embed code</button></div>
            </Card>);
        })}
      </Loadable>
      {edit && <FormSheet f={edit} w={w} onClose={() => { setEdit(null); q.refetch(); }} />}
    </>
  );
}

function FormSheet({ f, w, onClose }) {
  const [d, setD] = useState(f);
  const types = useAct("session_types.list");
  const autos = useAct("automations.list");
  const qb = d.blocks.find((b) => b.type === "questions") || { questions: [] };
  const sch = d.blocks.find((b) => b.type === "scheduler");
  const setQ = (qs) => setD({ ...d, blocks: d.blocks.map((b) => (b.type === "questions" ? { ...b, questions: qs } : b)) });
  return (
    <Sheet open onClose={onClose} title="Lead form" wide>
      <div className="space-y-3">
        <Field label="Name"><Input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Projects it creates are of type"><Select value={d.project_type || ""} onChange={(e) => setD({ ...d, project_type: e.target.value })} options={[{ value: "", label: "Not set" }, ...w.settings.project_types]} /></Field>
          <Field label="Default source"><Select value={d.source || ""} onChange={(e) => setD({ ...d, source: e.target.value })} options={w.settings.lead_sources} /></Field>
          <Field label="Price (makes it a paid consultation)"><MoneyInput paise={d.price_paise} onChange={(v) => setD({ ...d, price_paise: v || 0 })} /></Field>
          <Field label="Scheduler"><Select value={sch?.session_type_id || ""} onChange={(e) => setD({ ...d, blocks: sch ? d.blocks.map((b) => (b.type === "scheduler" ? { ...b, session_type_id: e.target.value || null } : b)) : [...d.blocks, { id: Math.random().toString(36).slice(2), type: "scheduler", session_type_id: e.target.value }] })}
            options={[{ value: "", label: "No booking on this form" }, ...(types.data || []).map((t) => ({ value: t.id, label: t.name }))]} /></Field>
        </div>
        <Kicker>Questions (name, mobile and email are always asked)</Kicker>
        {qb.questions.map((q, i) => (
          <div key={q.id} className="flex flex-wrap gap-2"><Input className="flex-1" value={q.label} onChange={(e) => setQ(qb.questions.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
            <Select className="w-36" value={q.kind} onChange={(e) => setQ(qb.questions.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))} options={["short", "long", "single", "number", "date"]} />
            <Toggle on={!!q.required} onChange={(v) => setQ(qb.questions.map((x, j) => (j === i ? { ...x, required: v } : x)))} label="Required" />
            <button onClick={() => setQ(qb.questions.filter((_, j) => j !== i))} aria-label="Remove"><Trash2 size={15} /></button></div>))}
        <Button size="sm" icon={Plus} onClick={() => setQ([...qb.questions, { id: Math.random().toString(36).slice(2), label: "", kind: "short", required: false }])}>Add question</Button>
        <Field label="Thank-you message"><Input value={(d.thank_you?.html || "").replace(/<[^>]+>/g, " ").trim()} onChange={(e) => setD({ ...d, thank_you: { ...d.thank_you, html: `<p>${e.target.value}</p>` } })} /></Field>
        <Field label="Or send them to a page after submitting"><Input value={d.thank_you?.redirect_url || ""} onChange={(e) => setD({ ...d, thank_you: { ...d.thank_you, redirect_url: e.target.value } })} placeholder="https://" /></Field>
        <div className="flex flex-wrap gap-4"><Toggle on={d.live} onChange={(v) => setD({ ...d, live: v })} label="Live" /><Toggle on={d.promo_enabled} onChange={(v) => setD({ ...d, promo_enabled: v })} label="Promo code box" /><Toggle on={d.otp_required} onChange={(v) => setD({ ...d, otp_required: v })} label="Verify mobile by OTP" /></div>
        <Field label="Automation it starts"><Select value={(d.automation_ids || [])[0] || ""} onChange={(e) => setD({ ...d, automation_ids: e.target.value ? [e.target.value] : [] })} options={[{ value: "", label: "Any automation triggered by a form" }, ...(autos.data || []).filter((a) => a.trigger?.type === "lead_form.submitted").map((a) => ({ value: a.id, label: a.name }))]} /></Field>
        <div className="flex gap-2"><Button variant="primary" onClick={async () => { try { await act("lead_forms.save", { ...d }); toast("Form saved"); onClose(); } catch (e) { toast(e.message, "error"); } }}>Save</Button>
          <Button variant="danger" onClick={async () => { if (confirm("Delete this form?")) { await act("lead_forms.delete", { id: d.id }); onClose(); } }}>Delete</Button></div>
      </div>
    </Sheet>
  );
}

function Connections() {
  const q = useAct("connections.list");
  async function connect(p) { try { const r = await get(`/api/connect/${p}/start`); location.href = r.url; } catch (e) { toast(e.message, "error"); } }
  const has = (p) => (q.data || []).find((c) => c.provider === p && c.mine);
  return (
    <Card className="space-y-3">
      <Kicker>Connected accounts</Kicker>
      {[["gmail", "Google (Gmail + Calendar + Meet)", "Mail sends from your own address, replies land on projects, calendar busy times block slots."],
        ["outlook", "Microsoft (Outlook mail + calendar)", "The same, for Outlook."], ["zoom", "Zoom", "Zoom links for session types set to Zoom."]].map(([p, l, d]) => {
        const c = has(p);
        return (
          <div key={p} className="flex flex-wrap items-center gap-3 border-t border-hairline pt-3 first:border-0 first:pt-0">
            <div className="min-w-0 flex-1"><b>{l}</b><div className="text-[13px] text-ivory-70">{c ? `Connected: ${c.account}` : d}</div></div>
            {c && p !== "zoom" && <Toggle ai on={c.lead_finder} onChange={async (v) => { await act("connections.update", { id: c.id, lead_finder: v }); q.refetch(); }} label="Lead finder" />}
            {c ? <Button size="sm" variant="quiet" onClick={async () => { await act("connections.disconnect", { id: c.id }); q.refetch(); }}>Disconnect</Button> : <Button size="sm" onClick={() => connect(p)}>Connect</Button>}
          </div>);
      })}
    </Card>
  );
}

function Messages({ w }) {
  const save = useSave();
  const [s, setS] = useState(w.settings);
  return (
    <Card className="space-y-3">
      <Kicker>Quiet hours</Kicker>
      <p className="text-[14px] text-ivory-70">Agents and automations never message clients in these hours; the message waits until the morning. What you send by hand goes straight away.</p>
      <div className="flex items-center gap-2"><Input className="w-24" inputMode="numeric" value={s.quiet_hours.start} onChange={(e) => setS({ ...s, quiet_hours: { ...s.quiet_hours, start: Number(e.target.value) || 21 } })} /> to
        <Input className="w-24" inputMode="numeric" value={s.quiet_hours.end} onChange={(e) => setS({ ...s, quiet_hours: { ...s.quiet_hours, end: Number(e.target.value) || 8 } })} /> (24-hour, client time)</div>
      <Kicker className="pt-2">Sending domain (optional)</Kicker>
      <Field label="Send from your own domain" hint="We check SPF and DKIM first, so emails don't land in spam. Connecting Gmail or Outlook is easier."><Input value={s.sending_domain || ""} onChange={(e) => setS({ ...s, sending_domain: e.target.value })} placeholder="mehtagrowth.in" /></Field>
      <Field label="Notetaker name"><Input value={s.notetaker_name || ""} onChange={(e) => setS({ ...s, notetaker_name: e.target.value })} /></Field>
      <Button variant="primary" onClick={() => save({ settings: { quiet_hours: s.quiet_hours, sending_domain: s.sending_domain, notetaker_name: s.notetaker_name } })}>Save</Button>
    </Card>
  );
}

function Connector() {
  const q = useAct("mcp.list_tokens");
  const [scope, setScope] = useState("drafts");
  const [tok, setTok] = useState(null);
  return (
    <Card ai className="space-y-3">
      <Kicker ai>Connect an outside AI assistant</Kicker>
      <p className="text-[14px] text-ivory-70">Let Claude or another assistant read your account and draft work. Anything it wants to send, or anything to do with money, still waits for your OK in Approvals.</p>
      <p className="font-mono text-[13px] text-teal">Server address: {location.origin}/mcp</p>
      <Segmented ai value={scope} onChange={setScope} options={[{ value: "read", label: "Read only" }, { value: "drafts", label: "Read + drafts" }, { value: "full", label: "Full" }]} />
      <Button variant="ai" onClick={async () => { try { setTok((await act("mcp.create_token", { name: "Assistant", scope })).token); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Create token</Button>
      {tok && <div className="rounded-input border border-teal/50 p-3 font-mono text-[13px] break-all">{tok}<div className="mt-1 text-ivory-35">Copy it now. It won't be shown again.</div></div>}
      {(q.data || []).map((t) => <div key={t.id} className="flex items-center gap-2 border-t border-hairline pt-2 text-[14px]"><span className="flex-1">{t.name} · {t.scope} · last used {t.last_used ? dt(t.last_used) : "never"}</span>
        <Button size="sm" variant="quiet" onClick={async () => { await act("mcp.revoke_token", { id: t.id }); q.refetch(); }}>Revoke</Button></div>)}
    </Card>
  );
}

function Audit() {
  const q = useAct("audit.list");
  return (
    <Loadable q={q}>{(rows) => <Card>{rows.map((r) => <div key={r.id} className="flex gap-3 border-t border-hairline py-2 text-[13px] first:border-0"><span className="w-40 shrink-0 text-ivory-35">{dt(r.created_at)}</span><span className="flex-1">{r.action}</span><span className="text-ivory-70">{r.actor}</span></div>)}</Card>}</Loadable>
  );
}
