import { useState } from "react";
import { useParams } from "react-router";
import { Fail, Footer, Header, Loading, SlotPicker, cget, cpost, fmtDate, fmtDay, fmtTime, inr, myTz, toDataUrl, slugOf, useBrand, useLoad } from "../kit";

/** One portal per client, with all their projects. */
export default function Portal() {
  const slug = slugOf(useParams());
  const brandQ = useLoad(() => cget(`/api/public/brand/${slug}`), [slug]);
  const me = useLoad(() => cget(`/api/public/${slug}/portal/me`).catch((e) => (e.code === "logged_out" ? null : Promise.reject(e))), [slug]);
  const [pid, setPid] = useState(null);
  useBrand(brandQ.data);
  if (me.loading || brandQ.loading) return <Loading />;
  if (me.error) return <Fail error={me.error} />;
  if (!me.data) return <Login slug={slug} brand={brandQ.data} onDone={me.reload} />;
  const projects = me.data.projects;
  const current = pid || (projects.length === 1 ? projects[0].id : null);
  return (
    <div className="min-h-screen"><Header brand={brandQ.data} right={<button className="text-[13px] c-muted underline" onClick={async () => { await cpost(`/api/public/${slug}/portal/logout`); me.reload(); }}>Log out</button>} />
      <main className="mx-auto max-w-2xl px-5 py-6">
        {!current ? (
          <>
            <div className="c-kicker">Hello {me.data.name.split(" ")[0]}</div><h1 className="mt-1 text-[26px] font-extrabold">Your projects</h1>
            <div className="mt-4 space-y-2">{projects.map((p) => (
              <button key={p.id} onClick={() => setPid(p.id)} className="c-card flex w-full items-center gap-3 p-4 text-left"><span className="min-w-0 flex-1"><b className="block">{p.name}</b><span className="text-[14px] c-muted">{p.stage}</span></span><span>→</span></button>))}
              {!projects.length && <p className="c-muted">Nothing here yet.</p>}</div>
          </>
        ) : <Project slug={slug} pid={current} back={projects.length > 1 ? () => setPid(null) : null} />}
      </main><Footer brand={brandQ.data} /></div>
  );
}

function Login({ slug, brand, onDone }) {
  const [key, setKey] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(null);
  const [err, setErr] = useState(null);
  return (
    <div className="min-h-screen" style={{ background: brand?.theme?.login_bg || undefined }}><Header brand={brand} />
      <main className="mx-auto max-w-sm px-5 py-12">
        <h1 className="text-[26px] font-extrabold">{brand?.theme?.login_title || `Welcome to ${brand?.name}`}</h1>
        <p className="mt-1 c-muted">Your files, payments, sessions and messages, in one place.</p>
        <div className="mt-6 space-y-3">
          <input className="c-in" placeholder="Mobile number or email" value={key} onChange={(e) => setKey(e.target.value)} disabled={!!sent} />
          {sent && <><input className="c-in text-center text-[22px] tracking-[.4em]" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} placeholder="Code" />
            {sent.qa_code && <p className="text-[13px] c-muted">Test code: {sent.qa_code}</p>}</>}
          {err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}
          <button className="c-btn w-full" onClick={async () => { setErr(null); try { if (!sent) setSent(await cpost(`/api/public/${slug}/portal/code`, { phone: key })); else { await cpost(`/api/public/${slug}/portal/login`, { phone: key, code }); onDone(); } } catch (e) { setErr(e); } }}>{sent ? "Log in" : "Send me a code"}</button>
        </div>
      </main></div>
  );
}

function Project({ slug, pid, back }) {
  const s = useLoad(() => cget(`/api/public/${slug}/portal/project/${pid}`), [pid]);
  const [tab, setTab] = useState("activity");
  const [msg, setMsg] = useState("");
  const [moving, setMoving] = useState(null);
  const tz = myTz();
  if (s.loading && !s.data) return <Loading />;
  if (s.error) return <Fail error={s.error} />;
  const p = s.data;
  const open = (p.client_tasks || []).filter((t) => !t.done);
  const tabs = [["activity", "Activity"], ...((p.client_tasks || []).length ? [["todo", `For you${open.length ? ` (${open.length})` : ""}`]] : []), ...(p.retainer ? [["plan", "Your plan"]] : []),
    ["files", "Files"], ["payments", "Payments"], ["sessions", "Sessions"], ["messages", "Messages"], ["details", "Details"]];
  return (
    <div>
      {back && <button className="mb-2 text-[14px] c-muted" onClick={back}>← All projects</button>}
      <div className="c-kicker">{p.stage}</div><h1 className="mt-1 text-[26px] font-extrabold">{p.name}</h1>
      <div className="mt-4 flex gap-1 overflow-x-auto border-b border-[#e6e1d6]">{tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className="h-11 shrink-0 whitespace-nowrap px-3 text-[14px] font-bold" style={tab === k ? { borderBottom: "2px solid var(--c-primary)" } : { color: "#8a8579" }}>{l}</button>)}</div>
      <div className="mt-4 space-y-2">
        {tab === "todo" && p.client_tasks.map((t, i) => (
          <a key={i} href={t.link} className="c-card flex items-center gap-3 p-4"><span className={`h-5 w-5 shrink-0 rounded-full border-2 ${t.done ? "bg-[var(--c-primary)]" : ""}`} style={{ borderColor: "var(--c-primary)" }} />
            <span className="min-w-0 flex-1"><b className={t.done ? "line-through c-muted" : ""}>{t.title}</b>
              <span className={`block text-[13px] ${t.overdue ? "font-bold text-[#B33A2A]" : "c-muted"}`}>{t.done ? "Done" : t.due ? `Due ${t.due}` : ""}</span></span>
            {!t.done && <span className="text-[13px] font-bold underline">Open</span>}</a>))}
        {tab === "plan" && p.retainer && <RetainerStatement r={p.retainer} />}
        {tab === "activity" && p.activity.map((a) => <div key={a.id} className="border-l-2 border-[#e6e1d6] py-1.5 pl-3 text-[14px]">{a.text}<div className="text-[12px] c-muted">{fmtDate(a.at, tz)}</div></div>)}
        {tab === "files" && <>{p.files.map((f) => <a key={f.id} href={f.link} className="c-card flex justify-between p-4"><b>{f.title}</b><span className="text-[13px] c-muted">{f.status === "completed" ? "Done" : "Open"}</span></a>)}
          {p.uploads.map((u) => <a key={u.link} href={u.link} className="c-card flex justify-between p-4"><span>{u.name}</span><span className="text-[13px] c-muted">Download</span></a>)}
          <label className="c-btn2 inline-flex cursor-pointer items-center">Upload a file<input type="file" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { await cpost(`/api/public/${slug}/portal/project/${pid}/upload`, { name: f.name, data: await toDataUrl(f) }); s.reload(); } }} /></label></>}
        {tab === "payments" && p.invoices.map((i) => <a key={i.id} href={i.link} className="c-card block p-4"><div className="flex justify-between"><b>{i.number}</b><span className="c-money">{inr(i.total_paise)}</span></div>
          <div className="mt-1 text-[14px] c-muted">{i.due_paise > 0 ? `Due: ${inr(i.due_paise)}` : "Paid in full"}</div></a>)}
        {tab === "sessions" && p.sessions.map((x) => (
          <div key={x.id} className="c-card p-4"><b>{x.title}</b><div className="text-[14px] c-muted">{fmtDay(x.start, tz)}, {fmtTime(x.start, tz)} · {x.status}</div>
            {x.meet_link && x.status === "booked" && <a href={x.meet_link} className="mt-1 block font-bold underline">Join</a>}
            {x.status === "booked" && new Date(x.start) > new Date() && (moving === x.id ? <div className="mt-3"><SlotPicker onPick={async (st) => { try { await cpost(`/api/public/${slug}/portal/session/${x.id}/reschedule`, { start: st }); setMoving(null); s.reload(); } catch (e) { alert(e.message); } }}
              loadSlots={(a, b) => cget(`/api/public/${slug}/book/${x.type_id}/slots?date_from=${encodeURIComponent(a)}&date_to=${encodeURIComponent(b)}`)} /></div>
              : <button className="c-btn2 mt-2" onClick={() => setMoving(x.id)}>Reschedule</button>)}</div>))}
        {tab === "messages" && <>{p.messages.map((m, i) => <div key={i} className={`c-card max-w-[88%] p-3 text-[14px] ${m.direction === "in" ? "ml-auto" : ""}`}>{m.subject && <b className="block">{m.subject}</b>}{m.html ? <div className="c-prose" dangerouslySetInnerHTML={{ __html: m.html }} /> : m.text}<div className="text-[12px] c-muted">{fmtDate(m.at, tz)}</div></div>)}
          <div className="flex gap-2"><input className="c-in" placeholder="Write a message" value={msg} onChange={(e) => setMsg(e.target.value)} /><button className="c-btn2" onClick={async () => { if (!msg.trim()) return; await cpost(`/api/public/${slug}/portal/project/${pid}/message`, { text: msg }); setMsg(""); s.reload(); }}>Send</button></div></>}
        {tab === "details" && <>{Object.entries(p.details || {}).map(([k, v]) => <div key={k} className="flex justify-between text-[14px]"><span className="c-muted">{k}</span><b>{String(v)}</b></div>)}
          {p.notes.map((n, i) => <div key={i} className="c-card whitespace-pre-wrap p-4 text-[14px]">{n.text}</div>)}{!p.notes.length && !Object.keys(p.details || {}).length && <p className="c-muted">Nothing shared yet.</p>}</>}
      </div>
    </div>
  );
}

function RetainerStatement({ r }) {
  const h = (m) => `${Math.round((m / 60) * 10) / 10}h`;
  const pct = r.available ? Math.min(100, (r.used * 100) / r.available) : 0;
  return (
    <div className="space-y-3">
      <div className="c-card p-4">
        <div className="c-kicker">{r.retainer} · {r.period}</div>
        {r.kind === "hours" ? <>
          <div className="mt-3 grid grid-cols-2 gap-3 text-[14px] md:grid-cols-4">
            <div><div className="c-muted">Included</div><b className="tnum text-[18px]">{h(r.included - (r.borrowed || 0))}</b></div>
            <div><div className="c-muted">Carried in</div><b className="tnum text-[18px]">{h(r.carried_in_minutes)}</b></div>
            <div><div className="c-muted">Used</div><b className="tnum text-[18px]">{h(r.used)}</b></div>
            <div><div className="c-muted">Left</div><b className="tnum text-[18px]">{h(r.left)}</b></div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#ece7dc]"><div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--c-primary)" }} /></div>
        </> : <p className="mt-2">{h(r.used)} of work so far this period.</p>}
      </div>
      {(r.entries || []).length > 0 && <div className="c-card p-4"><b>This period's work</b>{r.entries.map((e, i) => (
        <div key={i} className="flex gap-3 border-t border-[#efebe2] py-2 text-[14px]"><span className="w-24 c-muted">{e.date}</span><span className="min-w-0 flex-1">{e.note || e.task}</span><span className="tnum">{e.hours}h</span></div>))}</div>}
      {r.last_period && <p className="text-[13px] c-muted">Last period ({r.last_period.period}): {h(r.last_period.used)} used{r.last_period.kind === "hours" ? ` of ${h(r.last_period.available)}` : ""}.</p>}
    </div>
  );
}
