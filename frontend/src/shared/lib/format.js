// Money in paise -> Indian format. Dates in IST, like "4 Nov 2026".
export function inr(paise, { short = false, sign = false } = {}) {
  if (paise === null || paise === undefined || Number.isNaN(paise)) return "—";
  const neg = paise < 0;
  const r = Math.abs(paise) / 100;
  let s;
  if (short && r >= 1e7) s = `₹${trim(r / 1e7)} Cr`;
  else if (short && r >= 1e5) s = `₹${trim(r / 1e5)} L`;
  else s = "₹" + r.toLocaleString("en-IN", { minimumFractionDigits: Math.abs(paise) % 100 ? 2 : 0, maximumFractionDigits: 2 });
  return (neg ? "-" : sign && paise > 0 ? "+" : "") + s;
}
const trim = (n) => (Math.round(n * 10) / 10).toString();

export const rupeesToPaise = (v) => {
  const n = Number(String(v ?? "").replace(/[₹,\s]/g, ""));
  return Number.isFinite(n) ? Math.round(n * 100) : NaN;
};

const tz = "Asia/Kolkata";
export function date(iso, opts = {}) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: opts.tz || tz });
}
export function time(iso, opts = {}) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: opts.tz || tz }).replace(" ", " ").toUpperCase();
}
export const dt = (iso, opts) => (iso ? `${date(iso, opts)}, ${time(iso, opts)}` : "");
export function dayLabel(iso, opts = {}) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: opts.tz || tz });
}
export function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return date(iso);
}
export function istNow() {
  return new Date(new Date().toLocaleString("en-US", { timeZone: tz }));
}
export function greeting() {
  const h = istNow().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}
export const todayLabel = () => new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: tz });
export const plural = (n, w, p) => `${n} ${n === 1 ? w : p || w + "s"}`;
export const titleCase = (s) => (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export function istDateInput(iso) {
  const d = iso ? new Date(iso) : new Date();
  return d.toLocaleDateString("en-CA", { timeZone: tz });
}
export const fromDateInput = (v, hour = 10) => (v ? new Date(`${v}T${String(hour).padStart(2, "0")}:00:00+05:30`).toISOString() : null);

// Whole minutes -> "2h 30m" / "45m"; hours with one decimal for tables.
export function hm(min) {
  if (min === null || min === undefined) return "—";
  const m = Math.round(min);
  const h = Math.floor(Math.abs(m) / 60);
  const r = Math.abs(m) % 60;
  return (m < 0 ? "-" : "") + (h ? `${h}h${r ? ` ${String(r).padStart(2, "0")}m` : ""}` : `${r}m`);
}
export const hrs = (min) => (min === null || min === undefined ? "—" : `${Math.round((min / 60) * 10) / 10}h`);
export const todayISO = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
export const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v)}%`);
