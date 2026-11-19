import { useState } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Undo2 } from "lucide-react";
import { get, post, req } from "@/shared/api";
import { date, dt, inr, titleCase } from "@/shared/lib/format";
import { Wordmark, useMe } from "@/app/layout/AppShell";
import { Button, Card, Chip, ErrorCard, Field, Input, Kicker, Loadable, PageHeader, Segmented, Select, Sheet, SkeletonList, Stat, Textarea, Toggle, cx, toast } from "@/app/ui";

const useA = (path, opts) => useQuery({ queryKey: ["admin", path], queryFn: () => get(`/api/admin/${path}`), ...opts });
const TABS = [["", "Overview"], ["invites", "Invites"], ["limits", "Limits"], ["workspaces", "Accounts"], ["usage", "Usage"], ["ai", "AI cost"], ["funnel", "Funnel"], ["health", "Health"], ["jobs", "Jobs"], ["settings", "Settings"]];

export default function Admin() {
  const me = useMe();
  const nav = useNavigate();
  if (me.isLoading) return <div className="p-6"><SkeletonList /></div>;
  if (me.isError) return <Navigate to="/login" replace />;
  if (!me.data.user.is_admin) return <div className="p-6"><Card>This area is for the product team only.</Card></div>;
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-5 md:px-8">
      <div className="mb-4 flex items-center gap-3"><button onClick={() => nav("/")} className="grid h-10 w-10 place-items-center rounded-full hover:bg-panel" aria-label="Back"><ArrowLeft size={18} /></button><Wordmark /><Chip>Admin</Chip></div>
      <nav className="scroll-x mb-5 flex gap-1 border-b border-hairline">{TABS.map(([p, l]) => (
        <NavLink key={p} end to={`/admin/${p}`} className={({ isActive }) => cx("h-11 whitespace-nowrap px-3 pt-3 text-[14px] font-bold", isActive ? "text-gold" : "text-ivory-70")}>{l}</NavLink>))}</nav>
      <Routes>
        <Route index element={<Overview />} /><Route path="invites" element={<Invites />} /><Route path="limits" element={<Limits />} /><Route path="workspaces" element={<Workspaces />} />
        <Route path="usage" element={<Usage />} /><Route path="ai" element={<Ai />} /><Route path="funnel" element={<Funnel />} /><Route path="health" element={<Health />} />
        <Route path="jobs" element={<Jobs />} /><Route path="settings" element={<AiSettings />} />
      </Routes>
    </div>
  );
}

function Overview() {
  const q = useA("kpis");
  return <Loadable q={q}>{(k) => (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Invited" value={k.invited} gold={false} /><Stat label="Joined" value={k.joined} gold={false} /><Stat label="Practices" value={k.workspaces} gold={false} />
      <Stat label="Active this week" value={k.active_week} gold={false} /><Stat label="Files sent" value={k.files_sent} gold={false} /><Stat label="Payments recorded" value={k.payments_recorded} gold={false} />
      <Stat label="Waiting approvals" value={k.pending_approvals} gold={false} /><Stat label="AI cost this month" value={inr(k.ai_cost_month_paise)} />
    </div>)}</Loadable>;
}

function Invites() {
  const [status, setStatus] = useState("");
  const [qs, setQs] = useState("");
  const q = useA(`invites?status=${status}&q=${encodeURIComponent(qs)}`);
  const [txt, setTxt] = useState("");
  const [note, setNote] = useState("");
  async function add() {
    try { const r = await post("/api/admin/invites", { phones: txt.split(/[\n,;]+/), note }); toast(`Added ${r.added}${r.already ? `, ${r.already} already invited` : ""}${r.not_valid.length ? `, ${r.not_valid.length} not valid` : ""}`); setTxt(""); q.refetch(); }
    catch (e) { toast(e.message, "error"); }
  }
  return (
    <div className="space-y-4">
      <Card className="space-y-2"><Kicker>Invite people</Kicker>
        <Textarea rows={3} value={txt} onChange={(e) => setTxt(e.target.value)} placeholder="One mobile number, or paste a list (one per line)" />
        <div className="flex gap-2"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note, e.g. Sept batch" /><Button variant="primary" onClick={add} disabled={!txt.trim()}>Invite</Button></div>
        <input type="file" accept=".csv,.txt" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setTxt(await f.text()); }} className="text-[13px]" />
      </Card>
      <div className="flex flex-wrap gap-2"><Segmented value={status} onChange={setStatus} options={[{ value: "", label: "All" }, { value: "invited", label: "Invited" }, { value: "joined", label: "Joined" }, { value: "removed", label: "Removed" }]} />
        <Input className="max-w-xs" placeholder="Search number, name or note" value={qs} onChange={(e) => setQs(e.target.value)} /></div>
      <Loadable q={q}>{(rows) => (
        <div className="overflow-x-auto rounded-card border border-hairline"><table className="w-full min-w-[640px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Number</th><th className="p-3">Name</th><th className="p-3">Note</th><th className="p-3">Invited</th><th className="p-3">Status</th><th className="p-3" /></tr></thead>
          <tbody>{rows.map((i) => (
            <tr key={i.id} className="border-t border-hairline"><td className="p-3 tnum">{i.phone}</td><td className="p-3">{i.name}</td><td className="p-3 text-ivory-70">{i.note}</td><td className="p-3 text-ivory-70">{date(i.created_at)} · {i.invited_by}</td>
              <td className="p-3"><Chip tone={i.status === "joined" ? "gold" : i.status === "removed" ? "alert" : "muted"}>{titleCase(i.status)}</Chip></td>
              <td className="p-3">{i.status === "removed" ? <Button size="sm" variant="quiet" onClick={async () => { await post(`/api/admin/invites/${i.id}/access`, { restore: true }); q.refetch(); }}>Restore</Button>
                : <Button size="sm" variant="danger" onClick={async () => { if (confirm("Remove access? The account goes read-only. Client links keep working. Nothing is deleted.")) { await post(`/api/admin/invites/${i.id}/access`, {}); q.refetch(); } }}>Remove access</Button>}</td></tr>))}</tbody></table></div>)}</Loadable>
    </div>
  );
}

function Limits() {
  const q = useA("limits");
  const ch = useA("changes");
  const [edit, setEdit] = useState(null);
  return (
    <div className="space-y-4">
      <p className="text-ivory-70">Every limit, from the registry. Changes take effect within a minute, with no deploy. {q.data?.note}</p>
      <Loadable q={q}>{(d) => (
        <div className="overflow-x-auto rounded-card border border-hairline"><table className="w-full min-w-[600px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Limit</th><th className="p-3">Everyone</th><th className="p-3" /></tr></thead>
          <tbody>{d.limits.map((l) => (
            <tr key={l.key} className="border-t border-hairline"><td className="p-3"><b>{l.label}</b><div className="font-mono text-[12px] text-ivory-35">{l.key}</div></td>
              <td className="p-3 tnum">{fmt(l, l.value)}{l.legacy_before && <div className="text-[12px] text-ivory-35">Older accounts keep {fmt(l, l.legacy_value)}</div>}</td>
              <td className="p-3"><Button size="sm" variant="quiet" onClick={() => setEdit(l)}>Change</Button></td></tr>))}</tbody></table></div>)}</Loadable>
      <Kicker>Change log</Kicker>
      <Loadable q={ch}>{(rows) => <Card>{rows.map((c) => (
        <div key={c.id} className="flex flex-wrap items-center gap-2 border-t border-hairline py-2 text-[13px] first:border-0"><span className="w-40 text-ivory-35">{dt(c.at)}</span><span className="flex-1"><b>{c.who}</b> {c.what}: {JSON.stringify(c.old)} → {JSON.stringify(c.new)}</span>
          {c.what.startsWith("limit.") && <Button size="sm" variant="quiet" icon={Undo2} onClick={async () => { await post(`/api/admin/changes/${c.id}/revert`); q.refetch(); ch.refetch(); toast("Reverted"); }}>Revert</Button>}</div>))}</Card>}</Loadable>
      {edit && <LimitSheet l={edit} onClose={() => { setEdit(null); q.refetch(); ch.refetch(); }} />}
    </div>
  );
}
const fmt = (l, v) => (v === null || v === undefined ? "Unlimited" : l.type === "bool" ? (v ? "On" : "Off") : l.type === "money" ? inr(v) : `${v}${l.unit && !["paise"].includes(l.unit) ? ` ${l.unit}` : ""}`);

function LimitSheet({ l, onClose }) {
  const [v, setV] = useState(l.type === "money" ? (l.value ?? "") / 100 : l.value ?? "");
  const [scope, setScope] = useState("everyone");
  async function save() {
    try { await req("PUT", `/api/admin/limits/${l.key}`, { value: l.type === "money" ? (v === "" ? null : Math.round(Number(v) * 100)) : v, applies_to: scope }); toast("Limit changed"); onClose(); }
    catch (e) { toast(e.message, "error"); }
  }
  return (
    <Sheet open onClose={onClose} title={l.label}>
      <div className="space-y-3">
        {l.type === "bool" ? <Toggle on={!!v} onChange={setV} label={v ? "On" : "Off"} /> : l.type.startsWith("choice:") ? <Select value={v} onChange={(e) => setV(e.target.value)} options={l.type.slice(7).split(",")} />
          : <Field label={l.type === "money" ? "₹ per month (empty = unlimited)" : "Value (empty = unlimited)"}><Input inputMode="decimal" value={v ?? ""} onChange={(e) => setV(e.target.value)} /></Field>}
        <Segmented value={scope} onChange={setScope} options={[{ value: "everyone", label: "Everyone" }, { value: "new_accounts", label: "Only accounts created from now" }]} />
        <Button variant="primary" className="w-full" onClick={save}>Save</Button>
      </div>
    </Sheet>
  );
}

function Workspaces() {
  const [qs, setQs] = useState("");
  const q = useA(`workspaces?q=${encodeURIComponent(qs)}`);
  const lim = useA("limits");
  const [ov, setOv] = useState(null);
  const [dom, setDom] = useState(null);
  return (
    <div className="space-y-3">
      <Input className="max-w-xs" placeholder="Search practices" value={qs} onChange={(e) => setQs(e.target.value)} />
      <Loadable q={q}>{(rows) => rows.map((w) => (
        <Card key={w.id}>
          <div className="flex flex-wrap items-center gap-2"><b className="flex-1">{w.name}</b><Chip tone={w.status === "active" ? "gold" : "alert"}>{titleCase(w.status)}</Chip>{!w.onboarded && <Chip>Not set up</Chip>}
            <Button size="sm" variant="quiet" onClick={() => setDom(w)}>Custom domain</Button>
            <Button size="sm" variant="quiet" onClick={() => setOv(w)}>Override a limit</Button></div>
          <div className="mt-1 text-[13px] text-ivory-70">{w.owner} · {w.phone} · created {w.created} · last active {w.last_active || "—"} · team {w.team} · projects {w.projects} · files sent {w.files_sent} · storage {w.storage_mb} MB</div>
          {w.domains.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{w.domains.map((d) => <Chip key={d} tone="gold">{d}
            <button className="ml-1" aria-label={`Remove ${d}`} onClick={async () => { await req("DELETE", `/api/admin/domains/${d}`); q.refetch(); }}>×</button></Chip>)}</div>}
          {w.overrides.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{w.overrides.map((o) => <Chip key={o.id} tone="teal">{o.key} = {JSON.stringify(o.value)}{o.note ? ` (${o.note})` : ""}
            <button className="ml-1" onClick={async () => { await req("DELETE", `/api/admin/overrides/${o.id}`); q.refetch(); }}>×</button></Chip>)}</div>}
        </Card>))}</Loadable>
      {ov && <OverrideSheet w={ov} limits={lim.data?.limits || []} onClose={() => { setOv(null); q.refetch(); }} />}
      {dom && <DomainSheet w={dom} onClose={() => { setDom(null); q.refetch(); }} />}
    </div>
  );
}

function DomainSheet({ w, onClose }) {
  const [host, setHost] = useState("");
  return (
    <Sheet open onClose={onClose} title={`Custom domain for ${w.name}`}>
      <div className="space-y-3">
        <p className="text-[14px] text-ivory-70">Ask them to add a CNAME record pointing their domain (for example book.theirsite.in) to our client domain. Then add it here. The certificate is issued on the first visit.</p>
        <Field label="Domain"><Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="book.theirsite.in" /></Field>
        <Button variant="primary" className="w-full" onClick={async () => {
          try { await post("/api/admin/domains", { workspace_id: w.id, host }); toast("Domain added"); onClose(); }
          catch (e) { toast(e.message, "error"); }
        }}>Add domain</Button>
      </div>
    </Sheet>
  );
}

function OverrideSheet({ w, limits, onClose }) {
  const [key, setKey] = useState(limits[0]?.key);
  const [v, setV] = useState("");
  const [ends, setEnds] = useState("");
  const [note, setNote] = useState("");
  const l = limits.find((x) => x.key === key);
  return (
    <Sheet open onClose={onClose} title={`Override for ${w.name}`}>
      <div className="space-y-3">
        <Select value={key} onChange={(e) => setKey(e.target.value)} options={limits.map((x) => ({ value: x.key, label: x.label }))} />
        <Field label={l?.type === "money" ? "Value in ₹" : l?.type === "bool" ? "on / off" : "Value"}><Input value={v} onChange={(e) => setV(e.target.value)} /></Field>
        <Field label="Ends on (optional)"><input type="date" className="w-full rounded-input border border-hairline bg-panel px-3 py-3" value={ends} onChange={(e) => setEnds(e.target.value)} /></Field>
        <Field label="Note"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why" /></Field>
        <Button variant="primary" className="w-full" onClick={async () => {
          try { await post("/api/admin/overrides", { workspace_id: w.id, key, value: l?.type === "money" ? Math.round(Number(v) * 100) : v, ends_at: ends ? new Date(ends + "T23:59:00+05:30").toISOString() : null, note }); toast("Override saved"); onClose(); }
          catch (e) { toast(e.message, "error"); }
        }}>Save</Button>
      </div>
    </Sheet>
  );
}

function Usage() {
  const q = useA("usage");
  return <Loadable q={q}>{(d) => (
    <div className="space-y-4">
      <p className="text-ivory-70">{d.note} {d.accounts} accounts.</p>
      <div className="overflow-x-auto rounded-card border border-hairline"><table className="w-full min-w-[640px] text-[14px]"><thead className="bg-panel text-left text-[12px] uppercase tracking-[0.12em] text-ivory-70"><tr><th className="p-3">Limit</th><th className="p-3">Under half</th><th className="p-3">Half to 80%</th><th className="p-3">Above 80%</th><th className="p-3">At limit</th><th className="p-3">Not used</th></tr></thead>
        <tbody>{d.limits.map((l) => <tr key={l.key} className="border-t border-hairline tnum"><td className="p-3 font-bold">{l.label}</td><td className="p-3">{l.under_half}</td><td className="p-3">{l.half_to_80}</td><td className="p-3">{l.above_80}</td><td className="p-3 text-alert">{l.at_limit}</td><td className="p-3 text-ivory-35">{l.unused}</td></tr>)}</tbody></table></div>
      <Card><Kicker className="mb-2">Accounts using each feature</Kicker>{Object.entries(d.features_used_by_accounts).map(([k, v]) => <div key={k} className="flex justify-between border-t border-hairline py-1.5 text-[14px] first:border-0"><span>{k}</span><b className={v ? "" : "text-ivory-35"}>{v}</b></div>)}</Card>
    </div>)}</Loadable>;
}

function Ai() {
  const q = useA("ai-cost");
  return <Loadable q={q}>{(d) => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3"><Stat label="Total this month" value={inr(d.total_paise)} /><Stat label="Average per practice" value={inr(d.average_paise)} /><Stat label="Practices using AI" value={d.accounts} gold={false} /></div>
      <Card><Kicker className="mb-2">Top 20 practices</Kicker>{d.top.map((t) => <div key={t.workspace_id} className="flex justify-between border-t border-hairline py-1.5 text-[14px] first:border-0"><span>{t.name}</span><b className="tnum text-gold">{inr(t.cost_paise)}</b></div>)}</Card>
      <Card ai><Kicker ai className="mb-2">Agent kill switches (for everyone)</Kicker>
        {d.agents.map((a) => <Toggle key={a} ai on={!d.agents_off.includes(a)} onChange={async (on) => { await post("/api/admin/agents/kill", { agent: a, off: !on }); q.refetch(); }} label={titleCase(a)} />)}</Card>
      <p className="text-[13px] text-ivory-35">The cap is a limit (AI cost cap per workspace per month). Change it for everyone in Limits, or for one practice in Accounts.</p>
    </div>)}</Loadable>;
}

function Funnel() {
  const q = useA("funnel");
  return <Loadable q={q}>{(rows) => {
    const max = Math.max(1, rows[0]?.count || 1);
    return <Card className="space-y-3">{rows.map((r) => (
      <div key={r.step} className="grid grid-cols-[180px_1fr_60px] items-center gap-3 text-[14px]"><span>{r.step}</span><div className="h-3 rounded-full bg-hairline"><div className="h-3 rounded-full bg-gradient-to-r from-gold-deep to-gold-light" style={{ width: `${(100 * r.count) / max}%` }} /></div><b className="tnum text-gold">{r.count}</b></div>))}
      <p className="text-[13px] text-ivory-35">Shows whether the product works for a new consultant.</p></Card>;
  }}</Loadable>;
}

function Health() {
  const q = useA("health");
  return <Loadable q={q}>{(h) => (
    <div className="grid gap-4 md:grid-cols-2">
      <Card><Kicker className="mb-2">Automation runs</Kicker>{Object.entries(h.automation_runs).map(([k, v]) => <div key={k} className="flex justify-between text-[14px]"><span>{titleCase(k)}</span><b className={k === "failed" && v ? "text-alert" : ""}>{v}</b></div>)}</Card>
      <Card><Kicker className="mb-2">Agent runs (24 h)</Kicker>{Object.entries(h.agent_runs_24h).map(([k, v]) => <div key={k} className="flex justify-between text-[14px]"><span>{titleCase(k)}</span><b>{v}</b></div>)}
        <div className="mt-2 flex justify-between text-[14px]"><span>Events waiting</span><b>{h.events_backlog}</b></div><div className="flex justify-between text-[14px]"><span>Failed sends (24 h)</span><b>{h.outbound_failed_24h}</b></div></Card>
      <Card><Kicker className="mb-2">WhatsApp templates</Kicker>{h.whatsapp_templates.map((t) => <div key={t.name} className="flex justify-between text-[14px]"><span className="font-mono">{t.name}</span><span className="text-ivory-70">{t.status}</span></div>)}</Card>
    </div>)}</Loadable>;
}

function Jobs() {
  const q = useA("jobs");
  const v = useA("vendors");
  return (
    <div className="space-y-4">
      <Loadable q={q}>{(rows) => <Card>{rows.map((j) => (
        <div key={j.name} className="flex flex-wrap items-center gap-2 border-t border-hairline py-2.5 text-[14px] first:border-0"><div className="min-w-0 flex-1"><b>{j.label}</b><div className="text-[12px] text-ivory-35">{j.schedule} · last: {j.last ? `${j.last.status} ${dt(j.last.started_at)}${j.last.items !== undefined ? ` · ${j.last.items} items` : ""}` : "never"}</div></div>
          <Button size="sm" variant="quiet" onClick={async () => { const r = await post(`/api/admin/jobs/${j.name}/run`); toast(r.ok ? `Done: ${r.items ?? 0} items` : r.error || r.skipped, r.ok ? "ok" : "error"); q.refetch(); }}>Run now</Button></div>))}</Card>}</Loadable>
      <Loadable q={v}>{(rows) => <Card><Kicker className="mb-2">Outside services</Kicker><div className="grid grid-cols-2 gap-1 md:grid-cols-4">{rows.map((r) => <div key={r.name} className="text-[14px]"><span className="font-mono">{r.name}</span> <Chip tone={r.mode === "live" ? "gold" : "muted"}>{r.mode}</Chip></div>)}</div></Card>}</Loadable>
    </div>
  );
}

function AiSettings() {
  const q = useA("settings");
  const [s, setS] = useState(null);
  if (q.isLoading) return <SkeletonList />;
  if (q.isError) return <ErrorCard error={q.error} />;
  const d = s || q.data;
  return (
    <Card className="space-y-3">
      <Kicker>AI models (names live here, not in code)</Kicker>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Small, fast model (drafts, reminders)"><Input value={d.model_small} onChange={(e) => setS({ ...d, model_small: e.target.value })} /></Field>
        <Field label="Larger model (proposals, setup)"><Input value={d.model_large} onChange={(e) => setS({ ...d, model_large: e.target.value })} /></Field>
        <Field label="Small model price: paise per million tokens (in, out)"><Input value={d.price_small.join(", ")} onChange={(e) => setS({ ...d, price_small: e.target.value.split(",").map((x) => parseInt(x, 10) || 0) })} /></Field>
        <Field label="Larger model price: paise per million tokens (in, out)"><Input value={d.price_large.join(", ")} onChange={(e) => setS({ ...d, price_large: e.target.value.split(",").map((x) => parseInt(x, 10) || 0) })} /></Field>
      </div>
      <p className="text-[13px] text-ivory-35">{d.note}</p>
      <Button variant="primary" disabled={!s} onClick={async () => { try { await req("PUT", "/api/admin/settings", s); toast("Saved"); setS(null); q.refetch(); } catch (e) { toast(e.message, "error"); } }}>Save</Button>
    </Card>
  );
}
