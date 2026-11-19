import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Bot, CalendarDays, CheckCircle2, CheckSquare, FileText, Home, Inbox as InboxIcon, LayoutGrid, LogOut, Menu as MenuIcon, Plus, Receipt, Search, Settings as Cog, Shield, Sparkles, Users, Workflow, BarChart3, ImagePlus, Clock, Repeat, Calculator } from "lucide-react";
import { BRAND } from "@/shared/brand";
import { act, fileToDataUrl, get, post, useAct } from "@/shared/api";
import { ago } from "@/shared/lib/format";
import Chat from "@/app/layout/Chat";
import { Button, Chip, Input, Sheet, cx, toast, useDebounced } from "@/app/ui";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => get("/api/auth/me"), retry: false, staleTime: 60_000 });
export const useWs = () => useAct("workspace.get", {}, { staleTime: 60_000 });

const NAV = [
  ["/", "Home", Home], ["/projects", "Projects", LayoutGrid], ["/contacts", "Contacts", Users], ["/inbox", "Inbox", InboxIcon],
  ["/calendar", "Calendar", CalendarDays], ["/files", "Files & templates", FileText], ["/automations", "Automations", Workflow],
  ["/time", "Time", Clock], ["/retainers", "Retainers", Repeat], ["/estimates", "Estimates", Calculator],
  ["/payments", "Payments", Receipt], ["/reports", "Reports", BarChart3], ["/agents", "Agents", Bot], ["/approvals", "Approvals", CheckCircle2],
  ["/tasks", "Tasks", CheckSquare], ["/settings", "Settings", Cog],
];
const PHONE = [["/", "Home", Home], ["/projects", "Projects", LayoutGrid], ["/inbox", "Inbox", InboxIcon], ["/calendar", "Calendar", CalendarDays]];

export function Wordmark({ small }) {
  return (
    <div className="flex items-center gap-2">
      <svg width={small ? 22 : 26} height={small ? 22 : 26} viewBox="0 0 64 64" aria-hidden><rect width="64" height="64" rx="14" fill="#1E2027" />
        <path d="M18 46V18h16a10 10 0 0 1 0 20H26" fill="none" stroke="#C9A84C" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="44" cy="46" r="4" fill="#2ED3B7" /></svg>
      <span className="text-[13px] font-bold uppercase tracking-wordmark text-gold">{BRAND.name}</span>
    </div>
  );
}

export function AppShell({ children }) {
  const me = useMe();
  const ws = useWs();
  const nav = useNavigate();
  const loc = useLocation();
  const [menu, setMenu] = useState(false);
  const [create, setCreate] = useState(false);
  const [chat, setChat] = useState(false);
  const [notes, setNotes] = useState(false);
  const [search, setSearch] = useState(false);
  const appr = useAct("approvals.list", { status: "pending" }, { refetchInterval: 30_000 });
  const notif = useAct("notifications.list", {}, { refetchInterval: 45_000 });
  const unread = (notif.data || []).filter((n) => !n.read).length;
  const qc = useQueryClient();
  useEffect(() => { setMenu(false); }, [loc.pathname]);
  const u = me.data?.user;
  const wss = me.data?.workspaces || [];
  const readOnly = ws.data?.read_only;
  const pending = appr.data?.length || 0;

  async function logout() {
    await post("/api/auth/logout");
    qc.clear();
    nav("/login");
  }

  return (
    <div className="min-h-screen md:flex">
      <aside className="sticky top-0 hidden h-screen w-[240px] shrink-0 flex-col border-r border-hairline bg-panel/60 px-3 py-5 md:flex">
        <div className="px-2"><Wordmark /></div>
        {wss.length > 1 && (
          <select className="mx-2 mt-4 rounded-input border border-hairline bg-panel px-2 py-2 text-[14px]" value={me.data.current || ""}
            onChange={async (e) => { await post("/api/auth/switch", { workspace_id: e.target.value }); qc.clear(); location.href = "/"; }}>
            {wss.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        )}
        <nav className="mt-5 flex-1 space-y-0.5 overflow-y-auto">
          {NAV.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => cx("flex h-11 items-center gap-3 rounded-input px-3 text-[15px] font-bold",
              isActive ? "bg-panel-raised text-gold" : "text-ivory-70 hover:bg-panel-raised hover:text-ivory")}>
              <Icon size={18} className={to === "/agents" ? "text-teal" : ""} /> <span className="flex-1">{label}</span>
              {to === "/approvals" && pending > 0 && <Chip tone="teal">{pending}</Chip>}
            </NavLink>
          ))}
          {u?.is_admin && <NavLink to="/admin" className="flex h-11 items-center gap-3 rounded-input px-3 text-[15px] font-bold text-ivory-70 hover:bg-panel-raised"><Shield size={18} /> Admin</NavLink>}
        </nav>
        <div className="mt-3 flex items-center gap-2 border-t border-hairline px-2 pt-3">
          <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-bold">{u?.name || u?.phone}</div><div className="truncate text-[12px] text-ivory-35">{ws.data?.name}</div></div>
          <button onClick={logout} className="grid h-11 w-11 place-items-center rounded-full hover:bg-panel-raised" aria-label="Log out"><LogOut size={17} /></button>
        </div>
      </aside>

      <div className="min-w-0 flex-1 pb-24 md:pb-10">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-hairline/60 bg-bg/85 px-4 backdrop-blur md:px-8">
          <div className="md:hidden"><Wordmark small /></div>
          <button onClick={() => setSearch(true)} className="ml-auto flex h-11 items-center gap-2 rounded-full border border-hairline px-3 text-ivory-70 md:ml-0 md:w-72 md:px-4">
            <Search size={16} /><span className="hidden text-[14px] md:inline">Search clients and projects</span>
          </button>
          <div className="flex-1" />
          <button onClick={() => setNotes(true)} className="relative grid h-11 w-11 place-items-center rounded-full hover:bg-panel" aria-label="Notifications">
            <Bell size={19} />{unread > 0 && <span className="absolute right-2 top-2 h-2.5 w-2.5 rounded-full bg-gold" />}
          </button>
          <button onClick={() => setCreate(true)} className="grid h-11 w-11 place-items-center rounded-full bg-gold text-ink" aria-label="Create"><Plus size={20} /></button>
          <button onClick={() => setChat(true)} className="ai hidden h-11 items-center gap-2 rounded-full border border-teal/70 px-4 font-bold text-teal md:flex"><Sparkles size={16} /> Ask or tell</button>
        </header>
        {readOnly && <div className="border-b border-hairline bg-panel px-4 py-2 text-[14px] text-ivory-70 md:px-8">Your access is paused, so you can view everything but not change it. Links you've sent to clients still work.</div>}
        {me.data?.qa && <QaBar />}
        <main className="mx-auto w-full max-w-[1200px] px-4 pt-5 md:px-8 md:pt-7">{children}</main>
      </div>

      <button onClick={() => setChat(true)} className="ai fixed bottom-[88px] right-4 z-30 grid h-14 w-14 place-items-center rounded-full border border-teal/70 bg-panel text-teal shadow-teal md:hidden" aria-label="Ask or tell"><Sparkles size={22} /></button>

      <nav className="fixed inset-x-0 bottom-0 z-40 flex h-[72px] items-stretch border-t border-hairline bg-panel pb-[env(safe-area-inset-bottom)] md:hidden">
        {PHONE.map(([to, label, Icon]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => cx("flex flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium", isActive ? "text-gold" : "text-ivory-35")}>
            <Icon size={21} />{label}
          </NavLink>
        ))}
        <button onClick={() => setMenu(true)} className="relative flex flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium text-ivory-35">
          <MenuIcon size={21} />Menu{pending > 0 && <span className="absolute right-[30%] top-3 h-2.5 w-2.5 rounded-full bg-teal" />}
        </button>
      </nav>

      <Sheet open={menu} onClose={() => setMenu(false)} title="Menu">
        <div className="grid grid-cols-2 gap-2">
          {NAV.filter((n) => !PHONE.find((p) => p[0] === n[0])).map(([to, label, Icon]) => (
            <NavLink key={to} to={to} className="flex h-14 items-center gap-3 rounded-input border border-hairline px-3 font-bold"><Icon size={18} />{label}
              {to === "/approvals" && pending > 0 && <Chip tone="teal">{pending}</Chip>}</NavLink>
          ))}
          {u?.is_admin && <NavLink to="/admin" className="flex h-14 items-center gap-3 rounded-input border border-hairline px-3 font-bold"><Shield size={18} />Admin</NavLink>}
        </div>
        <Button className="mt-4 w-full" variant="quiet" icon={LogOut} onClick={logout}>Log out</Button>
      </Sheet>
      <CreateMenu open={create} onClose={() => setCreate(false)} />
      <Chat open={chat} onClose={() => setChat(false)} />
      <SearchSheet open={search} onClose={() => setSearch(false)} />
      <Sheet open={notes} onClose={() => { setNotes(false); act("notifications.read_all").then(() => notif.refetch()); }} title="Notifications">
        {(notif.data || []).length === 0 && <p className="text-ivory-70">Nothing new.</p>}
        <div className="space-y-1">
          {(notif.data || []).map((n) => (
            <button key={n.id} onClick={() => { setNotes(false); n.link && nav(n.link); }} className="flex w-full gap-3 rounded-input px-2 py-3 text-left hover:bg-panel-raised">
              <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.read ? "bg-hairline" : ["approval", "priority_lead", "ai_budget"].includes(n.kind) ? "bg-teal" : "bg-gold")} />
              <span className="min-w-0 flex-1"><span className="block text-[14px]">{n.body}</span><span className="text-[12px] text-ivory-35">{ago(n.created_at)}</span></span>
            </button>
          ))}
        </div>
      </Sheet>
    </div>
  );
}

function QaBar() {
  const qc = useQueryClient();
  async function as(persona) {
    await post("/api/qa/login", { persona });
    qc.clear();
    location.href = persona === "staff" ? "/admin" : "/";
  }
  return (
    <div className="scroll-x flex items-center gap-2 border-b border-hairline bg-panel/80 px-4 py-1.5 text-[12px] text-ivory-35 md:px-8">
      <span className="shrink-0 whitespace-nowrap font-mono">QA MODE · sample data</span>
      {["owner", "admin", "manager", "member", "collaborator", "new", "staff"].map((p) => (
        <button key={p} onClick={() => as(p)} className="shrink-0 whitespace-nowrap rounded-full border border-hairline px-2 py-0.5 hover:text-ivory">{p}</button>
      ))}
      <button className="shrink-0 whitespace-nowrap rounded-full border border-hairline px-2 py-0.5 hover:text-ivory" onClick={async () => { await post("/api/qa/run_jobs"); qc.invalidateQueries(); toast("Ran all jobs now"); }}>run jobs</button>
    </div>
  );
}

function SearchSheet({ open, onClose }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q, 250);
  const nav = useNavigate();
  const r = useAct("search.all", { q: dq }, { enabled: open && dq.length > 1 });
  return (
    <Sheet open={open} onClose={onClose} title="Search">
      <Input autoFocus placeholder="Name, phone, email or company" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="mt-3 space-y-1">
        {(r.data?.projects || []).map((p) => (
          <button key={p.id} onClick={() => { onClose(); nav(`/projects/${p.id}`); }} className="block w-full rounded-input px-3 py-2.5 text-left hover:bg-panel-raised">
            <b>{p.name}</b> <span className="text-[13px] text-ivory-35">Project</span></button>
        ))}
        {(r.data?.contacts || []).map((c) => (
          <button key={c.id} onClick={() => { onClose(); nav(`/contacts/${c.id}`); }} className="block w-full rounded-input px-3 py-2.5 text-left hover:bg-panel-raised">
            <b>{c.name}</b> <span className="text-[13px] text-ivory-35">{c.company || c.phone || c.email}</span></button>
        ))}
        {dq.length > 1 && r.data && !r.data.projects.length && !r.data.contacts.length && <p className="px-3 text-ivory-70">No matches.</p>}
      </div>
    </Sheet>
  );
}

export function CreateMenu({ open, onClose }) {
  const nav = useNavigate();
  const [mode, setMode] = useState(null);
  const close = () => { setMode(null); onClose(); };
  return (
    <Sheet open={open} onClose={close} title={mode === "lead" ? "New lead" : mode === "shot" ? "Lead from a screenshot" : "Create"} ai={mode === "shot"}>
      {!mode && (
        <div className="grid grid-cols-2 gap-2">
          {[["lead", "New lead or project", Plus], ["shot", "Lead from a screenshot", ImagePlus], ["file", "Client file", FileText],
            ["invoice", "Invoice", Receipt], ["session", "Book a session", CalendarDays], ["form", "Lead form", LayoutGrid]].map(([k, l, I]) => (
            <button key={k} onClick={() => {
              if (k === "lead" || k === "shot") setMode(k);
              else { close(); nav(k === "form" ? "/settings/forms" : k === "session" ? "/calendar?book=1" : "/projects?pick=" + k); }
            }} className={cx("flex h-20 flex-col items-start justify-center gap-1 rounded-input border px-3 text-left font-bold", k === "shot" ? "ai border-teal/50 text-teal" : "border-hairline")}>
              <I size={18} />{l}
            </button>
          ))}
        </div>
      )}
      {mode === "lead" && <NewLead onDone={(pid) => { close(); nav(`/projects/${pid}`); }} />}
      {mode === "shot" && <ShotLead onDone={(pid) => { close(); nav(`/projects/${pid}`); }} />}
    </Sheet>
  );
}

export function NewLead({ onDone }) {
  const ws = useWs();
  const [f, setF] = useState({ name: "", phone: "", email: "", company: "", source: "", project_type: "", message: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  async function save() {
    setBusy(true); setErr(null);
    try { const r = await act("leads.create", { ...f, via: "manual" }); toast("Lead added"); onDone(r.project.id); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  const st = ws.data?.settings || {};
  return (
    <div className="space-y-3">
      <Input placeholder="Name" value={f.name} onChange={s("name")} />
      <div className="grid grid-cols-2 gap-2"><Input placeholder="Mobile" inputMode="tel" value={f.phone} onChange={s("phone")} /><Input placeholder="Email" type="email" value={f.email} onChange={s("email")} /></div>
      <Input placeholder="Company" value={f.company} onChange={s("company")} />
      <div className="grid grid-cols-2 gap-2">
        <select className="rounded-input border border-hairline bg-panel px-3 py-3" value={f.source} onChange={s("source")}><option value="">Source</option>{(st.lead_sources || []).map((x) => <option key={x}>{x}</option>)}</select>
        <select className="rounded-input border border-hairline bg-panel px-3 py-3" value={f.project_type} onChange={s("project_type")}><option value="">Project type</option>{(st.project_types || []).map((x) => <option key={x}>{x}</option>)}</select>
      </div>
      <textarea className="w-full rounded-input border border-hairline bg-panel px-3 py-3" placeholder="What did they ask for? (optional)" value={f.message} onChange={s("message")} />
      {err && <p className="text-alert">{err.message}</p>}
      <Button variant="primary" size="lg" className="w-full" busy={busy} onClick={save}>Add lead</Button>
    </div>
  );
}

function ShotLead({ onDone }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function pick(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setErr(null);
    try { const r = await act("leads.from_screenshot", { image: await fileToDataUrl(file) }); toast(`Lead created: ${r.contact.name}`, "ai"); onDone(r.project.id); }
    catch (x) { setErr(x); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-3">
      <p className="text-ivory-70">Upload a screenshot of a WhatsApp, LinkedIn or Instagram message. The Lead agent reads it and creates the contact and project, then drafts a reply for your OK.</p>
      <label className="ai flex h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-frame border border-dashed border-teal/60 text-teal">
        {busy ? "Reading…" : <><ImagePlus size={24} /> Choose a screenshot</>}
        <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={pick} />
      </label>
      {err && <p className="text-alert">{err.message}</p>}
    </div>
  );
}
