import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ChevronLeft, ChevronRight, Copy, Plus, Trash2, Video } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { dayLabel, inr, istNow, time } from "../../lib/format";
import { useWs } from "../components/AppShell";
import { Button, Card, Chip, Field, Input, Kicker, Loadable, MoneyInput, PageHeader, Segmented, Select, Sheet, Tabs, Toggle, cx, toast } from "../components/ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const KIND = { session: "text-gold", payment_due: "text-ivory-70", task: "text-ivory-70", project_date: "text-ivory-35" };

function startOfWeek(d) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

export default function Calendar() {
  const [sp] = useSearchParams();
  const [tab, setTab] = useState("calendar");
  const [week, setWeek] = useState(startOfWeek(istNow()));
  const [show, setShow] = useState(["sessions", "projects", "payments", "tasks"]);
  const [book, setBook] = useState(sp.get("book") === "1");
  const end = new Date(week); end.setDate(end.getDate() + 7);
  const q = useAct("calendar.list", { date_from: week.toISOString(), date_to: end.toISOString(), show });
  const nav = useNavigate();
  const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(week); d.setDate(d.getDate() + i); return d; });
  return (
    <div>
      <PageHeader kicker="Calendar" title="Sessions, dates" accent="and dues" sub="Times show in IST. Clients see their own time zone on booking pages."
        right={<Button variant="primary" size="sm" icon={Plus} onClick={() => setBook(true)}>Book a session</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "calendar", label: "Calendar" }, { value: "types", label: "Session types" }, { value: "availability", label: "Availability" }]} />
      {tab === "calendar" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button className="grid h-10 w-10 place-items-center rounded-full border border-hairline" onClick={() => { const d = new Date(week); d.setDate(d.getDate() - 7); setWeek(d); }} aria-label="Previous week"><ChevronLeft size={18} /></button>
            <button className="grid h-10 w-10 place-items-center rounded-full border border-hairline" onClick={() => { const d = new Date(week); d.setDate(d.getDate() + 7); setWeek(d); }} aria-label="Next week"><ChevronRight size={18} /></button>
            <b>{dayLabel(week)} – {dayLabel(days[6])}</b>
            <div className="scroll-x ml-auto flex gap-1">{[["sessions", "Sessions"], ["projects", "Project dates"], ["payments", "Payments"], ["tasks", "Tasks"]].map(([k, l]) => (
              <button key={k} onClick={() => setShow(show.includes(k) ? show.filter((x) => x !== k) : [...show, k])} className={cx("h-9 rounded-full border px-3 text-[13px] font-bold", show.includes(k) ? "border-gold text-gold" : "border-hairline text-ivory-35")}>{l}</button>))}</div>
          </div>
          <Loadable q={q}>
            {(items) => (
              <div className="grid gap-3 md:grid-cols-7">
                {days.map((d) => {
                  const key = d.toLocaleDateString("en-CA");
                  const its = items.filter((i) => new Date(i.start).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }) === key || i.start === key);
                  const today = key === istNow().toLocaleDateString("en-CA");
                  return (
                    <div key={key} className={cx("min-h-[90px] rounded-card border p-2", today ? "border-gold-deep bg-panel" : "border-hairline bg-panel/50")}>
                      <div className={cx("mb-1 text-[13px] font-bold", today ? "text-gold" : "text-ivory-70")}>{dayLabel(d)}</div>
                      {its.map((i) => (
                        <button key={i.kind + i.id + i.start} onClick={() => i.project_id && nav(`/projects/${i.project_id}`)} className="mb-1 block w-full rounded-lg bg-panel-raised px-2 py-1.5 text-left text-[13px]">
                          {i.kind === "session" && <span className="tnum font-bold text-gold">{time(i.start)} </span>}
                          <span className={KIND[i.kind]}>{i.title}</span>{i.amount_paise ? <span className="tnum text-gold"> {inr(i.amount_paise, { short: true })}</span> : null}
                          {i.status === "held" && <Chip className="ml-1">Held</Chip>}
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
            )}
          </Loadable>
        </>
      )}
      {tab === "types" && <SessionTypes />}
      {tab === "availability" && <Overview />}
      <BookSheet open={book} onClose={() => setBook(false)} />
    </div>
  );
}

function SessionTypes() {
  const q = useAct("session_types.list");
  const [edit, setEdit] = useState(null);
  return (
    <div className="space-y-3">
      <Button size="sm" icon={Plus} onClick={() => setEdit({ name: "", duration: 30, increment: 30, availability: {}, reminders: [1440, 60], max_attendees: 1, format: "video", video: "meet", min_notice_hours: 4, max_days_ahead: 30, hold_hours: 24, buffer_before: 0, buffer_after: 0, cancel_cutoff_hours: 12, notetaker: false, price_paise: 0, questions: [], active: true })}>New session type</Button>
      <Loadable q={q}>
        {(rows) => rows.map((t) => (
          <Card key={t.id} className="flex flex-wrap items-center gap-3">
            <span className="h-3 w-3 rounded-full" style={{ background: t.color }} />
            <div className="min-w-0 flex-1"><b>{t.name}</b><div className="text-[13px] text-ivory-70">{t.duration} min · {t.format === "video" ? (t.video === "zoom" ? "Zoom" : "Google Meet") : t.format.replace("_", " ")}{t.max_attendees > 1 ? ` · up to ${t.max_attendees}` : ""}{t.notetaker ? " · notetaker on" : ""}{t.price_paise ? ` · ${inr(t.price_paise)}` : ""}</div></div>
            <button onClick={() => { navigator.clipboard?.writeText(t.link); toast("Booking link copied"); }} className="flex items-center gap-1 text-[13px] font-bold text-gold"><Copy size={14} /> Link</button>
            <Button size="sm" variant="quiet" onClick={() => setEdit(t)}>Edit</Button>
          </Card>
        ))}
      </Loadable>
      {edit && <TypeSheet t={edit} onClose={() => { setEdit(null); q.refetch(); }} />}
    </div>
  );
}

function TypeSheet({ t, onClose }) {
  const [f, setF] = useState(t);
  const [busy, setBusy] = useState(false);
  const s = (k, num) => (e) => setF({ ...f, [k]: num ? Number(e.target.value.replace(/\D/g, "")) || 0 : e.target.value });
  function setWin(d, i, k, v) {
    const av = { ...f.availability };
    av[d] = (av[d] || []).map((w, j) => (j === i ? { ...w, [k]: v } : w));
    setF({ ...f, availability: av });
  }
  return (
    <Sheet open onClose={onClose} title={t.id ? "Edit session type" : "New session type"} wide>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name"><Input value={f.name} onChange={s("name")} /></Field>
        <Field label="Format"><Select value={f.format} onChange={s("format")} options={[{ value: "video", label: "Video" }, { value: "phone", label: "Phone" }, { value: "in_person", label: "In person" }]} /></Field>
        {f.format === "video" && <Field label="Video link"><Select value={f.video} onChange={s("video")} options={[{ value: "meet", label: "Google Meet" }, { value: "zoom", label: "Zoom" }]} /></Field>}
        <Field label="Duration (minutes)"><Input inputMode="numeric" value={f.duration} onChange={s("duration", 1)} /></Field>
        <Field label="Start times every (minutes)"><Input inputMode="numeric" value={f.increment} onChange={s("increment", 1)} /></Field>
        <Field label="Buffer before / after (minutes)"><div className="flex gap-2"><Input inputMode="numeric" value={f.buffer_before} onChange={s("buffer_before", 1)} /><Input inputMode="numeric" value={f.buffer_after} onChange={s("buffer_after", 1)} /></div></Field>
        <Field label="Minimum notice (hours)"><Input inputMode="numeric" value={f.min_notice_hours} onChange={s("min_notice_hours", 1)} /></Field>
        <Field label="Book up to (days ahead)"><Input inputMode="numeric" value={f.max_days_ahead} onChange={s("max_days_ahead", 1)} /></Field>
        <Field label="Cancel / reschedule cut-off (hours)"><Input inputMode="numeric" value={f.cancel_cutoff_hours} onChange={s("cancel_cutoff_hours", 1)} /></Field>
        <Field label="Max attendees" hint="More than 1 makes it a group session."><Input inputMode="numeric" value={f.max_attendees} onChange={s("max_attendees", 1)} /></Field>
        <Field label="Price (optional)"><MoneyInput paise={f.price_paise} onChange={(v) => setF({ ...f, price_paise: v || 0 })} /></Field>
        <Field label="Hold after 'I've paid' (hours)"><Input inputMode="numeric" value={f.hold_hours} onChange={s("hold_hours", 1)} /></Field>
      </div>
      <div className="mt-3"><Toggle ai on={f.notetaker} onChange={(v) => setF({ ...f, notetaker: v })} label="Notetaker joins video calls (clients are told the call may be recorded)" /></div>
      <Kicker className="mb-2 mt-5">Availability (IST) · several windows per day are fine</Kicker>
      <div className="space-y-2">
        {DAYS.map((d, di) => (
          <div key={d} className="flex flex-wrap items-center gap-2">
            <span className="w-10 font-bold">{d}</span>
            {(f.availability[String(di)] || []).map((w, i) => (
              <span key={i} className="flex items-center gap-1 rounded-full border border-hairline px-2 py-1">
                <input type="time" value={w.start} onChange={(e) => setWin(String(di), i, "start", e.target.value)} className="bg-transparent" />–
                <input type="time" value={w.end} onChange={(e) => setWin(String(di), i, "end", e.target.value)} className="bg-transparent" />
                <button onClick={() => setF({ ...f, availability: { ...f.availability, [di]: f.availability[String(di)].filter((_, j) => j !== i) } })} aria-label="Remove"><Trash2 size={13} /></button>
              </span>
            ))}
            <button className="text-[13px] font-bold text-gold" onClick={() => setF({ ...f, availability: { ...f.availability, [di]: [...(f.availability[String(di)] || []), { start: "10:00", end: "13:00" }] } })}>+ window</button>
          </div>
        ))}
      </div>
      <Button className="mt-5 w-full" variant="primary" busy={busy} onClick={async () => { setBusy(true); try { await act("session_types.save", f); toast("Saved"); onClose(); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); } }}>Save</Button>
    </Sheet>
  );
}

function Overview() {
  const q = useAct("session_types.overview");
  return (
    <Loadable q={q}>
      {(rows) => (
        <div className="overflow-x-auto rounded-card border border-hairline">
          <table className="w-full min-w-[640px] text-[13px]"><thead><tr className="bg-panel"><th className="p-2 text-left">Session type</th>{DAYS.map((d) => <th key={d} className="p-2 text-left">{d}</th>)}</tr></thead>
            <tbody>{rows.map((t) => (
              <tr key={t.id} className="border-t border-hairline"><td className="p-2 font-bold">{t.name}</td>
                {DAYS.map((_, i) => <td key={i} className="p-2 text-ivory-70">{(t.availability[String(i)] || []).map((w) => `${w.start}–${w.end}`).join(", ") || "—"}</td>)}</tr>))}</tbody></table>
        </div>
      )}
    </Loadable>
  );
}

function BookSheet({ open, onClose }) {
  const types = useAct("session_types.list", {}, { enabled: open });
  const contacts = useAct("contacts.search", { limit: 200 }, { enabled: open });
  const [tid, setTid] = useState("");
  const [cid, setCid] = useState("");
  const [slot, setSlot] = useState("");
  const from = useMemo(() => new Date().toISOString(), [open]);
  const slots = useAct("availability.find_slots", { session_type_id: tid, date_from: from }, { enabled: !!tid });
  return (
    <Sheet open={open} onClose={onClose} title="Book a session">
      <div className="space-y-3">
        <Select value={tid} onChange={(e) => { setTid(e.target.value); setSlot(""); }} options={[{ value: "", label: "Session type" }, ...(types.data || []).map((t) => ({ value: t.id, label: t.name }))]} />
        <Select value={cid} onChange={(e) => setCid(e.target.value)} options={[{ value: "", label: "Who with" }, ...((contacts.data?.items) || []).map((c) => ({ value: c.id, label: c.name }))]} />
        {tid && <div className="flex max-h-56 flex-wrap gap-2 overflow-y-auto">{(slots.data || []).slice(0, 40).map((s) => (
          <button key={s.start} onClick={() => setSlot(s.start)} className={cx("h-10 rounded-full border px-3 text-[13px]", slot === s.start ? "border-gold text-gold" : "border-hairline")}>{s.label}</button>))}</div>}
        <Button variant="primary" size="lg" className="w-full" disabled={!tid || !cid || !slot} onClick={async () => {
          try { await act("sessions.book", { session_type_id: tid, contact_id: cid, start: slot }); toast("Booked. The client gets a confirmation."); onClose(); } catch (e) { toast(e.message, "error"); }
        }}><Video size={16} /> Book</Button>
      </div>
    </Sheet>
  );
}

export { Segmented };
