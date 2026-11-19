import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { Fail, Footer, Header, Loading, SlotPicker, cget, cpost, fmtDay, fmtTime, inr, myTz, slugOf, useBrand, useLoad } from "@/client/lib/kit";

export function FormPage() {
  const params = useParams(); const slug = slugOf(params); const { form } = params;
  const [sp] = useSearchParams();
  const embed = sp.get("embed") === "1";
  const nav = useNavigate();
  const s = useLoad(() => cget(`/api/public/${slug}/form/${form}`), [slug, form]);
  const [c, setC] = useState({ name: "", phone: "", email: "" });
  const [ans, setAns] = useState({});
  const [slot, setSlot] = useState(null);
  const [promo, setPromo] = useState("");
  const [hp, setHp] = useState("");
  const [otp, setOtp] = useState({ sent: false, code: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [started, setStarted] = useState(false);
  useBrand(s.data?.brand);
  const utm = Object.fromEntries([...sp.entries()].filter(([k]) => k.startsWith("utm_") || ["gclid", "fbclid"].includes(k)));
  useEffect(() => { if (s.data) cpost(`/api/public/${slug}/form/${form}/event`, { kind: "view", source: utm.utm_source || (document.referrer ? "Referral" : "Direct") }).catch(() => {}); }, [s.data]); // eslint-disable-line
  function start() { if (!started) { setStarted(true); cpost(`/api/public/${slug}/form/${form}/event`, { kind: "start", source: utm.utm_source || "Direct" }).catch(() => {}); } }
  if (s.loading) return <Loading />;
  if (s.error) return <Fail error={s.error} />;
  const f = s.data.form;
  const sched = f.blocks.find((b) => b.type === "scheduler" && b.session_type_id);
  async function submit() {
    setErr(null); setBusy(true);
    try {
      if (f.otp_required && !otp.sent) { await cpost(`/api/public/${slug}/otp`, { phone: c.phone }); setOtp({ ...otp, sent: true }); setBusy(false); return; }
      const r = await cpost(`/api/public/${slug}/form/${form}/submit`, { contact: c, answers: ans, utm, referrer: document.referrer, slot_start: slot, promo, website: hp, otp: otp.code });
      if (r.invoice_token) { nav(`/c/${slug}/i/${r.invoice_token}`); return; }
      if (r.thank_you?.redirect_url) { location.href = r.thank_you.redirect_url; return; }
      setDone(r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  if (done) return (
    <div className={embed ? "" : "min-h-screen"}>{!embed && <Header brand={s.data.brand} />}
      <main className="mx-auto max-w-2xl px-5 py-10 rise"><div className="c-prose" dangerouslySetInnerHTML={{ __html: done.thank_you?.html || "<h2>Thank you!</h2>" }} />
        {done.session && <p className="mt-3 font-bold">Your call is booked for {fmtDay(done.session.start, myTz())}, {fmtTime(done.session.start, myTz())}.</p>}</main></div>
  );
  return (
    <div className={embed ? "" : "min-h-screen"}>
      {!embed && <Header brand={s.data.brand} />}
      <main className="mx-auto max-w-2xl space-y-5 px-5 py-8" onFocus={start}>
        <h1 className="text-[28px] font-extrabold tracking-[-0.02em]">{f.name}</h1>
        <div className="space-y-3">
          <input className="c-in" placeholder="Your name" autoComplete="name" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} />
          <div className="grid gap-3 md:grid-cols-2"><input className="c-in" placeholder="Mobile number" inputMode="tel" autoComplete="tel" value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} />
            <input className="c-in" placeholder="Email" type="email" autoComplete="email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} /></div>
          <input className="hidden" tabIndex={-1} autoComplete="off" value={hp} onChange={(e) => setHp(e.target.value)} name="website" aria-hidden />
        </div>
        {f.blocks.filter((b) => b.type === "questions").flatMap((b) => b.questions).map((q) => <Question key={q.id} q={q} v={ans[q.id]} set={(v) => setAns({ ...ans, [q.id]: v })} />)}
        {sched && <div><div className="mb-2 font-bold">Pick a time</div><SlotPicker picked={slot} onPick={setSlot} loadSlots={(a, b) => cget(`/api/public/${slug}/book/${sched.session_type_id}/slots?date_from=${encodeURIComponent(a)}&date_to=${encodeURIComponent(b)}`)} /></div>}
        {f.price_paise > 0 && <div className="c-card p-4"><div className="flex justify-between font-bold"><span>Session fee</span><span className="c-money">{inr(f.price_paise)}</span></div>
          {f.promo_enabled && <input className="c-in mt-3" placeholder="Promo code (optional)" value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} />}
          <p className="mt-2 text-[13px] c-muted">You'll pay by UPI or bank transfer on the next screen. Your time is held until it's confirmed.</p></div>}
        {otp.sent && <input className="c-in" inputMode="numeric" placeholder="6-digit code sent to your mobile" value={otp.code} onChange={(e) => setOtp({ ...otp, code: e.target.value.replace(/\D/g, "").slice(0, 6) })} />}
        {err && <p className="text-[15px] font-bold text-[#B33A2A]">{err.message}</p>}
        <button className="c-btn w-full" disabled={busy || (sched && !slot)} onClick={submit}>{busy ? "Sending…" : f.otp_required && !otp.sent ? "Verify my number" : f.price_paise > 0 ? "Continue to payment" : "Send"}</button>
        <p className="text-[12px] c-muted">By sending this you agree to be contacted about your enquiry.</p>
      </main>
      {!embed && <Footer brand={s.data.brand} />}
    </div>
  );
}

export function Question({ q, v, set, locked }) {
  const opt = (o) => (
    <button key={o} disabled={locked} onClick={() => set(q.kind === "multi" ? ((v || []).includes(o) ? v.filter((x) => x !== o) : [...(v || []), o]) : o)} className="c-btn2 text-[14px]"
      style={(q.kind === "multi" ? (v || []).includes(o) : v === o) ? { borderColor: "var(--c-primary)", background: "var(--c-paper)" } : {}}>{o}</button>
  );
  return (
    <label className="block">
      <span className="mb-1.5 block font-bold">{q.label}{q.required && " *"}</span>
      {q.kind === "long" ? <textarea className="c-in min-h-[110px]" disabled={locked} value={v || ""} onChange={(e) => set(e.target.value)} />
        : ["single", "multi"].includes(q.kind) ? <div className="flex flex-wrap gap-2">{(q.options || []).map(opt)}</div>
        : q.kind === "file" ? (v?.name ? <span className="c-muted">Uploaded: {v.name}</span> : <input type="file" disabled={locked} onChange={async (e) => { const f = e.target.files?.[0]; if (f) { const { toDataUrl } = await import("@/client/lib/kit"); set(await toDataUrl(f)); } }} />)
        : <input className="c-in" disabled={locked} type={q.kind === "date" ? "date" : "text"} inputMode={q.kind === "number" ? "decimal" : undefined} value={v || ""} onChange={(e) => set(e.target.value)} />}
    </label>
  );
}

export function Booking() {
  const params = useParams(); const slug = slugOf(params); const { type } = params;
  const s = useLoad(() => cget(`/api/public/${slug}/book/${type}`), [slug, type]);
  const [slot, setSlot] = useState(null);
  const [c, setC] = useState({ name: "", phone: "", email: "" });
  const [ans, setAns] = useState({});
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  useBrand(s.data?.brand);
  if (s.loading) return <Loading />;
  if (s.error) return <Fail error={s.error} />;
  const t = s.data.type;
  async function book() {
    setBusy(true); setErr(null);
    try { setDone((await cpost(`/api/public/${slug}/book/${type}`, { contact: c, start: slot, answers: ans })).session); } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  if (done) {
    const g = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(`${t.name} with ${s.data.brand.name}`)}&dates=${done.start.replace(/[-:]/g, "").slice(0, 15)}Z/${done.end.replace(/[-:]/g, "").slice(0, 15)}Z&details=${encodeURIComponent(done.meet_link || "")}`;
    return (
      <div className="min-h-screen"><Header brand={s.data.brand} />
        <main className="mx-auto max-w-2xl px-5 py-10 rise"><div className="c-kicker">Booked</div><h1 className="mt-1 text-[28px] font-extrabold">{fmtDay(done.start, myTz())}, {fmtTime(done.start, myTz())}</h1>
          <p className="mt-2 c-muted">A confirmation is on its way by WhatsApp and email{done.meet_link ? ", with the call link" : ""}.</p>
          <a href={g} target="_blank" rel="noreferrer" className="c-btn2 mt-5 inline-flex items-center">Add to Google Calendar</a></main></div>
    );
  }
  return (
    <div className="min-h-screen"><Header brand={s.data.brand} />
      <main className="mx-auto max-w-2xl space-y-5 px-5 py-8">
        <div><div className="c-kicker">{t.duration} minutes{t.format === "video" ? " · video call" : t.format === "phone" ? " · phone" : " · in person"}</div><h1 className="mt-1 text-[28px] font-extrabold tracking-[-0.02em]">{t.name}</h1>{t.price_paise > 0 && <p className="c-money">{inr(t.price_paise)}</p>}</div>
        <SlotPicker picked={slot} onPick={setSlot} loadSlots={(a, b) => cget(`/api/public/${slug}/book/${type}/slots?date_from=${encodeURIComponent(a)}&date_to=${encodeURIComponent(b)}`)} />
        {slot && <div className="space-y-3 rise">
          <input className="c-in" placeholder="Your name" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} />
          <div className="grid gap-3 md:grid-cols-2"><input className="c-in" placeholder="Mobile number" inputMode="tel" value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} /><input className="c-in" placeholder="Email" type="email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} /></div>
          {(t.questions || []).map((q) => <Question key={q.id} q={q} v={ans[q.id]} set={(v) => setAns({ ...ans, [q.id]: v })} />)}
          {err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}
          <button className="c-btn w-full" disabled={busy} onClick={book}>{busy ? "Booking…" : `Book ${fmtDay(slot, myTz())}, ${fmtTime(slot, myTz())}`}</button></div>}
      </main><Footer brand={s.data.brand} /></div>
  );
}
