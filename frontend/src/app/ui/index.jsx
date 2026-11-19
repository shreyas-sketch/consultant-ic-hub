import { createContext, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, Check, ChevronDown, Loader2, Sparkles, X } from "lucide-react";
import { inr, rupeesToPaise } from "@/shared/lib/format";

export const cx = (...a) => a.filter(Boolean).join(" ");

// ---------- layout and text ----------
export function Card({ className = "", ai, children, ...p }) {
  return (
    <div className={cx("rounded-card border bg-panel p-4", ai ? "border-teal/40 shadow-teal" : "border-hairline", className)} {...p}>
      {children}
    </div>
  );
}

export function Kicker({ ai, children, className = "" }) {
  return <div className={cx("kicker", ai && "kicker-ai", className)}>{children}</div>;
}

/** Page header: one kicker, an ExtraBold headline with one gold (or teal) phrase, one plain line. */
export function PageHeader({ kicker, title, accent, sub, ai, right }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 rise">
      <div className="min-w-0">
        {kicker && <Kicker ai={ai}>{kicker}</Kicker>}
        <h1 className="mt-1 text-[26px] font-extrabold leading-tight tracking-[-0.02em] md:text-[30px]">
          {title} {accent && <span className={ai ? "text-teal" : "text-gold"}>{accent}</span>}
        </h1>
        {sub && <p className="mt-1 text-[15px] font-light text-ivory-70">{sub}</p>}
      </div>
      {right && <div className="flex flex-wrap gap-2">{right}</div>}
    </div>
  );
}

export function Section({ title, children, defaultOpen = true, right }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mt-6">
      <div className="mb-2 flex items-center justify-between">
        <button className="flex items-center gap-1 text-[17px] font-bold" onClick={() => setOpen(!open)}>
          {title}
          <ChevronDown size={16} className={cx("transition", !open && "-rotate-90")} />
        </button>
        {right}
      </div>
      {open && children}
    </div>
  );
}

export function Stat({ label, value, sub, gold = true, alert }) {
  return (
    <div className="min-w-0 rounded-card border border-hairline bg-panel p-4">
      <div className="text-[12px] font-medium uppercase tracking-[0.16em] text-ivory-70">{label}</div>
      <div className={cx("tnum mt-1 truncate text-[26px] font-extrabold tracking-[-0.03em]", alert ? "text-alert" : gold ? "text-gold" : "text-ivory")}>
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[13px] text-ivory-70">{sub}</div>}
    </div>
  );
}

export const Money = ({ paise, short, className = "" }) => <span className={cx("tnum font-bold text-gold", className)}>{inr(paise, { short })}</span>;

export function Disclaimer({ children }) {
  return <p className="mt-3 text-[12px] text-ivory-35">{children}</p>;
}

// ---------- actions ----------
const V = {
  primary: "bg-gold text-ink font-extrabold hover:bg-gold-light rounded-full",
  secondary: "border border-gold-deep text-ivory font-bold hover:border-gold rounded-full",
  quiet: "bg-panel-raised text-ivory font-bold hover:bg-[#2e3240] rounded-full",
  ai: "border border-teal/70 text-teal font-bold hover:bg-teal/10 rounded-full",
  danger: "border border-alert/70 text-alert font-bold hover:bg-alert/10 rounded-full",
  link: "text-gold font-bold hover:underline px-0",
};
export function Button({ variant = "secondary", size = "md", busy, icon: Icon, className = "", children, ...p }) {
  const h = size === "sm" ? "h-9 px-4 text-[14px]" : size === "lg" ? "h-[52px] px-7 text-[16px]" : "h-12 px-5 text-[15px]";
  return (
    <button
      className={cx("inline-flex select-none items-center justify-center gap-2 whitespace-nowrap transition duration-150 disabled:opacity-40",
        variant !== "link" && h, V[variant], variant === "ai" && "ai", className)}
      disabled={busy || p.disabled}
      {...p}
    >
      {busy ? <Loader2 size={16} className="animate-spin" /> : Icon ? <Icon size={16} /> : variant === "ai" ? <Sparkles size={15} /> : null}
      {children}
    </button>
  );
}

export function Chip({ tone = "muted", children, className = "" }) {
  const t = {
    muted: "bg-panel-raised text-ivory-70",
    gold: "bg-gold/15 text-gold",
    teal: "bg-teal/15 text-teal",
    alert: "bg-alert/15 text-alert",
    ivory: "bg-ivory/10 text-ivory",
  }[tone];
  return <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-bold", t, className)}>{children}</span>;
}

/** Anything an agent wrote shows this until a person edits or approves it. */
export const AgentChip = ({ who = "agent" }) => (
  <Chip tone="teal"><Sparkles size={11} /> Drafted by {who}</Chip>
);

// ---------- inputs ----------
// Inputs inside a labelled Field are named by that label; only unlabelled inputs fall back to the placeholder.
const Labelled = createContext(false);

export function Field({ label, hint, error, children, className = "" }) {
  return (
    <Labelled.Provider value={!!label}>
    <label className={cx("block", className)}>
      {label && <span className="mb-1 block text-[13px] font-bold text-ivory-70">{label}</span>}
      {children}
      {hint && !error && <span className="mt-1 block text-[12px] text-ivory-35">{hint}</span>}
      {error && <span className="mt-1 block text-[13px] text-alert">{error}</span>}
    </label>
    </Labelled.Provider>
  );
}
const inputCls = "w-full rounded-input border border-hairline bg-panel px-3.5 py-3 text-ivory placeholder:text-ivory-35 focus:border-gold focus:outline-none";
const useA11yName = (p) => (useContext(Labelled) ? p["aria-label"] : p["aria-label"] ?? p.placeholder);
export const Input = ({ className = "", ai, ...p }) => <input aria-label={useA11yName(p)} className={cx(inputCls, ai && "focus:border-teal", className)} {...p} />;
export const Textarea = ({ className = "", ai, ...p }) => <textarea aria-label={useA11yName(p)} className={cx(inputCls, "min-h-[96px]", ai && "font-mono text-[14px] focus:border-teal", className)} {...p} />;
export function Select({ options, className = "", ...p }) {
  return (
    <select className={cx(inputCls, "appearance-none pr-9", className)} {...p}>
      {options.map((o) => (typeof o === "string" ? <option key={o} value={o}>{o}</option> : <option key={o.value} value={o.value}>{o.label}</option>))}
    </select>
  );
}
/** Money box: type rupees, store paise, our own check and message. */
export function MoneyInput({ paise, onChange, placeholder = "0", ...p }) {
  const [txt, setTxt] = useState(paise ? String(paise / 100) : "");
  useEffect(() => { setTxt(paise ? String(paise / 100) : ""); }, [paise]);
  return (
    <div className="relative">
      <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gold">₹</span>
      <input inputMode="decimal" className={cx(inputCls, "pl-8 tnum")} value={txt} placeholder={placeholder}
        onChange={(e) => { setTxt(e.target.value); const v = rupeesToPaise(e.target.value); onChange(Number.isNaN(v) ? null : v); }} {...p} />
    </div>
  );
}
export function Segmented({ value, onChange, options, ai }) {
  return (
    <div className="scroll-x inline-flex max-w-full rounded-full border border-hairline bg-panel p-1">
      {options.map((o) => {
        const v = typeof o === "string" ? o : o.value;
        const l = typeof o === "string" ? o : o.label;
        const on = v === value;
        return (
          <button key={v} onClick={() => onChange(v)} className={cx("h-9 whitespace-nowrap rounded-full px-4 text-[14px] font-bold transition",
            on ? (ai ? "bg-teal text-teal-ink" : "bg-gold text-ink") : "text-ivory-70 hover:text-ivory")}>{l}</button>
        );
      })}
    </div>
  );
}
export function Toggle({ on, onChange, label, ai }) {
  return (
    <button onClick={() => onChange(!on)} className="flex min-h-[44px] items-center gap-3 text-left">
      <span className={cx("relative h-6 w-11 shrink-0 rounded-full transition", on ? (ai ? "bg-teal" : "bg-gold") : "bg-hairline")}>
        <span className={cx("absolute top-0.5 h-5 w-5 rounded-full bg-ivory transition", on ? "left-[22px]" : "left-0.5")} />
      </span>
      {label && <span className="text-[15px]">{label}</span>}
    </button>
  );
}
export function Meter({ pct, ai, alert }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-hairline">
      <div className={cx("h-full rounded-full transition-all duration-700", alert ? "bg-alert" : ai ? "bg-teal" : "bg-gradient-to-r from-gold-deep to-gold-light")}
        style={{ width: `${Math.min(100, Math.max(0, pct || 0))}%` }} />
    </div>
  );
}
export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="scroll-x mb-4 flex gap-1 border-b border-hairline">
      {tabs.map((t) => (
        <button key={t.value} onClick={() => onChange(t.value)}
          className={cx("relative h-11 shrink-0 whitespace-nowrap px-3 text-[14px] font-bold", value === t.value ? "text-gold" : "text-ivory-70 hover:text-ivory")}>
          {t.label}{t.count ? <span className="ml-1 text-ivory-35">{t.count}</span> : null}
          {value === t.value && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-gold" />}
        </button>
      ))}
    </div>
  );
}

// ---------- overlays ----------
/** Bottom sheet on phone, modal on desktop. */
export function Sheet({ open, onClose, title, children, wide, ai }) {
  useEffect(() => {
    if (!open) return;
    const k = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 md:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}
        className={cx("rise max-h-[92vh] w-full overflow-y-auto rounded-t-[18px] border bg-panel p-5 md:rounded-frame", wide ? "md:max-w-3xl" : "md:max-w-lg",
        ai ? "border-teal/50" : "border-hairline")}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-[20px] font-extrabold">{title}</h2>
          <button onClick={onClose} className="grid h-11 w-11 place-items-center rounded-full hover:bg-panel-raised" aria-label="Close"><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

let toastFn = null;
export const toast = (msg, kind = "ok") => toastFn && toastFn({ msg, kind, id: Math.random() });
export function Toaster() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    toastFn = (t) => { setItems((x) => [...x, t]); setTimeout(() => setItems((x) => x.filter((i) => i.id !== t.id)), 3800); };
    return () => { toastFn = null; };
  }, []);
  return createPortal(
    <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6">
      {items.map((t) => (
        <div key={t.id} className="rise pointer-events-auto flex max-w-md items-center gap-2 rounded-input border border-hairline bg-panel-raised px-4 py-3 text-[14px] shadow-float">
          {t.kind === "error" ? <AlertCircle size={16} className="text-alert" /> : <Check size={16} className={t.kind === "ai" ? "text-teal" : "text-gold"} />}
          {t.msg}
        </div>
      ))}
    </div>,
    document.body,
  );
}

// ---------- the five states ----------
export const Skeleton = ({ className = "h-5" }) => <div className={cx("skeleton", className)} />;
export function SkeletonList({ rows = 4 }) {
  return <div className="space-y-3">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>;
}
export function ErrorCard({ error, retry }) {
  return (
    <Card className="flex flex-col items-start gap-3">
      <div className="flex items-center gap-2 font-bold"><AlertCircle size={18} className="text-alert" /> {error?.message || "Something went wrong."}</div>
      {retry && <Button size="sm" onClick={retry}>Retry</Button>}
    </Card>
  );
}
export function Empty({ title, line, action }) {
  return (
    <Card className="flex flex-col items-start gap-3 py-8">
      <div className="text-[17px] font-bold">{title}</div>
      {line && <p className="text-ivory-70">{line}</p>}
      {action}
    </Card>
  );
}
export function LimitReached({ used, limit, what }) {
  return <Card className="border-alert/40"><b>Limit reached.</b> <span className="text-ivory-70">You've used {used} of {limit} {what} this month.</span></Card>;
}
/** Loadable: skeleton while loading, error card with retry, empty state, then content. */
export function Loadable({ q, empty, rows = 4, children }) {
  if (q.isLoading) return <SkeletonList rows={rows} />;
  if (q.isError) return <ErrorCard error={q.error} retry={() => q.refetch()} />;
  const d = q.data;
  if (empty && (!d || (Array.isArray(d) && !d.length) || (d.items && !d.items.length))) return empty;
  return children(d);
}
export const ErrorLine = ({ error }) => (error ? <p className="mt-2 text-[14px] text-alert">{error.message || String(error)}</p> : null);
export const OkLine = ({ children }) => <p className="mt-2 text-[14px] text-gold">{children}</p>;

export function RowLink({ title, sub, right, onClick, ai }) {
  return (
    <button onClick={onClick} className={cx("flex w-full items-center gap-3 rounded-input px-3 py-3 text-left hover:bg-panel-raised", ai && "ai")}>
      <div className="min-w-0 flex-1">
        <div className="truncate font-bold">{title}</div>
        {sub && <div className="truncate text-[13px] text-ivory-70">{sub}</div>}
      </div>
      {right}
    </button>
  );
}

export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export function useAutosave(value, save, ms = 1500) {
  const first = useRef(true);
  const [state, setState] = useState("saved");
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setState("unsaved");
    const t = setTimeout(async () => {
      setState("saving");
      try { await save(value); setState("saved"); } catch (e) { setState("error"); toast(e.message, "error"); }
    }, ms);
    return () => clearTimeout(t);
  }, [JSON.stringify(value)]); // eslint-disable-line
  return state;
}

export const ThinkingDots = () => (
  <span className="inline-flex gap-1">{[0, 1, 2].map((i) => <span key={i} className="pulse-dot h-1.5 w-1.5 rounded-full bg-teal" style={{ animationDelay: `${i * 0.2}s` }} />)}</span>
);
