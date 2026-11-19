import { useEffect, useState } from "react";

export async function call(method, url, body) {
  let r;
  try {
    r = await fetch(url, { method, credentials: "include", headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error("You seem to be offline. Please check your connection.");
  }
  const d = await r.json().catch(() => null);
  if (!r.ok) {
    const e = new Error(d?.error?.message || "Something went wrong. Please try again.");
    e.code = d?.error?.code;
    e.extra = d?.error?.extra;
    throw e;
  }
  return d;
}
export const cget = (u) => call("GET", u);
/** The practice: from /c/<slug>/... or from the practice's own domain. */
export const slugOf = (params) => params.slug || window.__SLUG__;
export const cpost = (u, b = {}) => call("POST", u, b);

export function inr(p) {
  if (p === null || p === undefined) return "";
  return "₹" + Math.round(p / 100).toLocaleString("en-IN");
}
export const myTz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
export const fmtTime = (iso, tz) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz }).toUpperCase();
export const fmtDay = (iso, tz) => new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: tz });
export const fmtDate = (iso, tz) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: tz });

/** Apply the consultant's brand (colours, corners, name in the tab). */
export function useBrand(brand) {
  useEffect(() => {
    if (!brand) return;
    const t = brand.theme || {};
    const r = document.documentElement.style;
    r.setProperty("--c-primary", t.primary || "#C9A84C");
    r.setProperty("--c-btn-text", t.button_text || "#14151A");
    r.setProperty("--c-paper", t.paper || "#FAF8F3");
    r.setProperty("--c-text", t.text || "#14151A");
    r.setProperty("--c-radius", t.corners === "sharp" ? "0px" : "14px");
    r.setProperty("--c-pill", t.corners === "sharp" ? "0px" : "999px");
    document.title = brand.name;
  }, [brand]);
}

export function Header({ brand, right }) {
  return (
    <header className="mx-auto flex max-w-2xl items-center gap-3 px-5 pt-6">
      {brand?.logo_url ? <img src={brand.logo_url} alt={brand.name} className="h-10 max-w-[180px] object-contain" /> : <div className="c-kicker">{brand?.name}</div>}
      <div className="flex-1" />{right}
    </header>
  );
}

export function Footer({ brand }) {
  return brand?.powered_by ? <p className="py-8 text-center text-[12px] c-muted">Powered by {brand.powered_by}</p> : <div className="h-8" />;
}

export function Loading() {
  return <div className="mx-auto max-w-2xl space-y-3 p-5">{[1, 2, 3].map((i) => <div key={i} className="h-20 animate-pulse rounded-[14px] bg-[#efebe2]" />)}</div>;
}
export function Fail({ error, retry }) {
  return <div className="mx-auto max-w-2xl p-5"><div className="c-card p-5"><p className="font-bold">{error?.message || "Something went wrong."}</p>{retry && <button className="c-btn2 mt-3" onClick={retry}>Try again</button>}</div></div>;
}

export function useLoad(fn, deps = []) {
  const [s, setS] = useState({ loading: true });
  const load = () => { setS((x) => ({ ...x, loading: true })); fn().then((data) => setS({ data })).catch((error) => setS({ error })); };
  useEffect(load, deps); // eslint-disable-line
  return { ...s, reload: load, set: (data) => setS({ data }) };
}

export function Sheet({ open, onClose, title, children }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 md:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="rise max-h-[92vh] w-full overflow-y-auto bg-white p-5 md:max-w-md" style={{ borderRadius: "18px 18px 0 0" }}>
        <div className="mb-3 flex items-center justify-between"><h2 className="text-[20px] font-extrabold">{title}</h2><button onClick={onClose} className="h-11 w-11 text-[22px]" aria-label="Close">×</button></div>
        {children}
      </div>
    </div>
  );
}

export function toDataUrl(file) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(file); });
}

/** Day + time picker. Shows times in the client's own time zone, with a switcher. */
export function SlotPicker({ loadSlots, onPick, picked }) {
  const [tz, setTz] = useState(myTz());
  const [days, setDays] = useState([]);
  const [day, setDay] = useState(null);
  const [slots, setSlots] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const from = new Date(); from.setHours(0, 0, 0, 0);
    const to = new Date(from); to.setDate(to.getDate() + 21);
    loadSlots(from.toISOString(), to.toISOString()).then((s) => { setSlots(s); }).catch(setErr);
  }, []); // eslint-disable-line
  useEffect(() => {
    if (!slots) return;
    const ds = [...new Set(slots.map((s) => new Date(s).toLocaleDateString("en-CA", { timeZone: tz })))];
    setDays(ds);
    setDay((d) => (d && ds.includes(d) ? d : ds[0]));
  }, [slots, tz]);
  if (err) return <p className="c-muted">{err.message}</p>;
  if (!slots) return <div className="h-24 animate-pulse rounded-[14px] bg-[#efebe2]" />;
  if (!slots.length) return <p className="c-muted">No times are open in the next three weeks. Please message us instead.</p>;
  const daySlots = slots.filter((s) => new Date(s).toLocaleDateString("en-CA", { timeZone: tz }) === day);
  return (
    <div>
      <div className="flex gap-2 overflow-x-auto pb-2">{days.map((d) => (
        <button key={d} onClick={() => setDay(d)} className="shrink-0 rounded-[12px] border px-3 py-2 text-[14px] font-bold" style={day === d ? { borderColor: "var(--c-primary)", background: "#fff" } : { borderColor: "#e6e1d6" }}>
          {fmtDay(d + "T12:00:00", "UTC")}</button>))}</div>
      <div className="mt-2 grid grid-cols-3 gap-2 md:grid-cols-4">{daySlots.map((s) => (
        <button key={s} onClick={() => onPick(s)} className="h-11 rounded-full border text-[14px] font-bold" style={picked === s ? { background: "var(--c-primary)", color: "var(--c-btn-text)", borderColor: "var(--c-primary)" } : { borderColor: "#ddd6c8", background: "#fff" }}>
          {fmtTime(s, tz)}</button>))}</div>
      <label className="mt-3 flex items-center gap-2 text-[13px] c-muted">Times shown in
        <select className="rounded border border-[#ddd6c8] bg-white px-1 py-0.5" value={tz} onChange={(e) => setTz(e.target.value)}>
          {[...new Set([myTz(), "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York", "America/Los_Angeles", "Australia/Sydney"])].map((z) => <option key={z}>{z}</option>)}
        </select></label>
    </div>
  );
}
