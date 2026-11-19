import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { Fail, Footer, Header, Loading, Sheet, SlotPicker, cget, cpost, fmtDate, inr, myTz, toDataUrl, useBrand, useLoad } from "@/client/lib/kit";
import { Question } from "@/client/pages/Public";
import { sanitize } from "@/shared/lib/safeHtml";

/** Review -> choose -> sign -> pay -> book, one page at a time, one big button at the bottom. */
export function FileViewer({ preview }) {
  const { token, fileId } = useParams();
  const base = preview ? null : `/api/public/f/${token}`;
  const s = useLoad(() => (preview ? cget(`/api/preview/f/${fileId}`) : cget(`${base}?track=1`)), [token, fileId]);
  const [pi, setPi] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [finished, setFinished] = useState(false);
  const top = useRef(null);
  useBrand(s.data?.brand);
  useEffect(() => { if (s.data && !preview) setPi(Math.min(s.data.progress || 0, s.data.pages.length - 1)); }, [!!s.data]); // eslint-disable-line
  if (s.loading && !s.data) return <Loading />;
  if (s.error) return <Fail error={s.error} retry={s.reload} />;
  const v = s.data;
  const page = v.pages[pi];
  const last = pi === v.pages.length - 1;
  const refresh = async () => { if (!preview) s.set(await cget(`${base}?track=0`)); };
  async function next() {
    setErr(null);
    if (preview) { if (!last) setPi(pi + 1); return; }
    if (!last) {
      const n = pi + 1;
      setPi(n); cpost(`${base}/page`, { index: n }).catch(() => {});
      top.current?.scrollIntoView({ behavior: "smooth" });
      return;
    }
    setBusy(true);
    try {
      await cpost(`${base}/complete`);
      const ty = page.blocks.find((b) => b.type === "thankyou" && b.redirect_url);
      if (ty) { location.href = ty.redirect_url; return; }
      setFinished(true); refresh();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  const missing = page.missing || [];
  const isQuote = page.blocks.some((b) => b.type === "quote");
  const isThanks = page.blocks.length && page.blocks.every((b) => ["thankyou", "text", "company", "divider", "spacer"].includes(b.type)) && last;
  const done = finished || v.status === "completed";
  return (
    <div className="min-h-screen pb-32" ref={top}>
      <Header brand={v.brand} right={<span className="text-[13px] c-muted">Step {pi + 1} of {v.pages.length}</span>} />
      {preview && <div className="mx-auto mt-3 max-w-2xl px-5"><div className="rounded-[10px] bg-[#14151A] px-3 py-2 text-[13px] text-[#F2EEE6]">Preview: this is what your client sees. Buttons don't send anything.</div></div>}
      {v.changes?.length > 0 && pi === 0 && !done && (
        <div className="mx-auto mt-4 max-w-2xl px-5"><div className="c-card p-4"><div className="c-kicker">Updated</div><ul className="mt-1 list-disc pl-5 text-[14px]">{v.changes.map((c, i) => <li key={i}>{c}</li>)}</ul></div></div>
      )}
      <main className="mx-auto max-w-2xl space-y-5 px-5 py-6 rise" key={pi}>
        {page.locked ? (
          <div className="c-card p-5"><b>{page.locked_reason}</b><button className="c-btn2 mt-3" onClick={() => setPi(Math.max(0, pi - 1))}>Go back</button></div>
        ) : page.blocks.map((b) => <Block key={b.id} b={b} base={base} preview={preview} version={v.version} client={v.client} onChange={refresh} />)}
        {done && last && <div className="c-card p-5"><b>All done. Thank you!</b>{v.portal_url && <p className="mt-1 text-[14px] c-muted">See everything in one place anytime: <a className="font-bold underline" href={v.portal_url}>your client portal</a>.</p>}</div>}
      </main>
      {!(isQuote && pi === 0) && <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[#e6e1d6] bg-[var(--c-paper)]/95 px-5 pb-[max(16px,env(safe-area-inset-bottom))] pt-3 backdrop-blur">
        <div className="mx-auto flex max-w-2xl items-center gap-3">
          {pi > 0 && <button className="c-btn2" onClick={() => setPi(pi - 1)} aria-label="Back">←</button>}
          <div className="min-w-0 flex-1">
            {(err || (missing.length > 0 && !page.locked)) && !done && <p className="mb-1 truncate text-[13px] font-bold text-[#B33A2A]">{err ? err.message : missing[0]}</p>}
            {!(done && last) && !(isThanks && done) && !isQuote && <button className="c-btn w-full" disabled={busy || page.locked || (missing.length > 0 && !preview)} onClick={next}>{busy ? "One moment…" : page.button || (last ? "Submit" : "Continue")}</button>}
          </div>
        </div>
      </div>}
      <Footer brand={v.brand} />
    </div>
  );
}

function Block({ b, base, preview, version, client, onChange }) {
  const run = async (path, body) => { if (preview) return; await cpost(`${base}/${path}`, body); await onChange(); };
  switch (b.type) {
    case "text": case "thankyou": return <div className="c-prose" dangerouslySetInnerHTML={{ __html: sanitize(b.html) }} />;
    case "image": return b.url ? <img src={b.url} alt="" className="max-h-[420px] w-full object-cover" style={{ borderRadius: "var(--c-radius)", objectPosition: `${b.focal?.x ?? 50}% ${b.focal?.y ?? 50}%` }} /> : null;
    case "video": return b.url ? <Video url={b.url} /> : null;
    case "divider": return <hr className="border-[#e6e1d6]" />;
    case "spacer": return <div className="h-6" />;
    case "company": return <div><div className="c-kicker">{b.name}</div><div className="text-[13px] c-muted">{[b.contact?.email, b.contact?.phone, b.contact?.website].filter(Boolean).join(" · ")}</div></div>;
    case "timeline": return <div className="c-card p-4">{(b.items || []).map((i, k) => <div key={k} className="flex gap-4 border-t border-[#efebe2] py-2 first:border-0"><b className="w-28 shrink-0" style={{ color: "var(--c-deep)" }}>{i.date}</b><span>{i.title}</span></div>)}</div>;
    case "questions": return <Questions b={b} run={run} />;
    case "services": return <Services b={b} run={run} />;
    case "contract": return <Contract b={b} base={base} preview={preview} client={client} onChange={onChange} />;
    case "invoice": return b.invoice ? <Pay inv={b.invoice} claimUrl={preview ? null : `${base}/claim`} planUrl={preview ? null : `${base}/plan`} promoUrl={preview ? null : `${base}/promo`} version={version} onChange={onChange} /> : null;
    case "scheduler": return <Scheduler b={b} base={base} preview={preview} onChange={onChange} />;
    case "quote": return <Quote b={b} base={base} preview={preview} onChange={onChange} />;
    case "retainer": return <RetainerPlan b={b} />;
    default: return null;
  }
}

function Video({ url }) {
  const yt = url.match(/(?:youtu\.be\/|v=)([\w-]{11})/);
  const vm = url.match(/vimeo\.com\/(\d+)/);
  const lm = url.match(/loom\.com\/share\/(\w+)/);
  const src = yt ? `https://www.youtube.com/embed/${yt[1]}` : vm ? `https://player.vimeo.com/video/${vm[1]}` : lm ? `https://www.loom.com/embed/${lm[1]}` : null;
  return src ? <div className="aspect-video overflow-hidden" style={{ borderRadius: "var(--c-radius)" }}><iframe title="video" src={src} className="h-full w-full" allowFullScreen /></div> : <a href={url} className="font-bold underline">Watch the video</a>;
}

function Questions({ b, run }) {
  const [ans, setAns] = useState(b.answers || {});
  const t = useRef(null);
  function set(qid, val) {
    const a = { ...ans, [qid]: val };
    setAns(a);
    clearTimeout(t.current);
    t.current = setTimeout(() => run("answers", { block_id: b.id, answers: { [qid]: val } }).catch(() => {}), typeof val === "string" && !val.startsWith("data:") ? 600 : 0);
  }
  return <div className="space-y-4">{b.questions.map((q) => <Question key={q.id} q={q} v={ans[q.id]} set={(v) => set(q.id, v)} locked={b.locked} />)}{b.locked && <p className="text-[13px] c-muted">Submitted. Ask us to reopen it if something needs changing.</p>}</div>;
}

function Services({ b, run }) {
  const sel = b.selection || {};
  const [busy, setBusy] = useState(null);
  async function toggle(it) {
    setBusy(it.id);
    let picks = { ...sel };
    if (picks[it.id]) delete picks[it.id];
    else {
      if (b.select !== "multi" && it.kind !== "addon") picks = Object.fromEntries(Object.entries(picks).filter(([k]) => b.items.find((x) => x.id === k)?.kind === "addon"));
      picks[it.id] = 1;
    }
    try { await run("select", { block_id: b.id, picks }); } finally { setBusy(null); }
  }
  return (
    <div className="grid gap-3">
      {b.items.map((it) => {
        const on = !!sel[it.id];
        return (
          <button key={it.id} aria-pressed={!!on} onClick={() => toggle(it)} disabled={busy} className="c-card flex gap-3 p-4 text-left transition" style={on ? { borderColor: "var(--c-primary)", boxShadow: "0 0 0 2px var(--c-primary)" } : {}}>
            <span className="mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full border-2" style={{ borderColor: on ? "var(--c-primary)" : "#cfc8b9", background: on ? "var(--c-primary)" : "transparent" }}>{on && <span className="h-2 w-2 rounded-full bg-white" />}</span>
            <span className="min-w-0 flex-1"><span className="block font-bold">{it.name}{it.kind === "addon" && <span className="ml-2 text-[12px] font-bold c-muted">Add-on</span>}</span>
              {it.desc && <span className="mt-0.5 block text-[14px] c-muted">{it.desc}</span>}</span>
            <span className="c-money">{inr(it.price_paise)}</span>
          </button>
        );
      })}
    </div>
  );
}

function Contract({ b, base, preview, client, onChange }) {
  const [open, setOpen] = useState(false);
  const me = b.signers.find((s) => s.id === b.my_signer_id);
  return (
    <div className="space-y-3">
      <div className="c-card c-prose max-h-[60vh] overflow-y-auto p-5" dangerouslySetInnerHTML={{ __html: sanitize(b.html) }} />
      <div className="grid gap-2 md:grid-cols-2">{b.signers.map((s) => (
        <div key={s.id} className="c-card p-3"><div className="text-[12px] font-bold uppercase tracking-[.14em] c-muted">{s.role === "client" ? "You" : s.role === "consultant" ? "Consultant" : "Signer"}</div>
          {s.signed ? <><div className="text-[20px] italic" style={{ fontFamily: "Georgia, serif" }}>{s.name}</div><div className="text-[12px] c-muted">Signed {s.at}</div></> : <div className="text-[14px] c-muted">Not signed yet</div>}</div>))}</div>
      {me && !me.signed && <button className="c-btn w-full" onClick={() => setOpen(true)} disabled={preview}>Sign</button>}
      <SignSheet open={open} onClose={() => setOpen(false)} b={b} base={base} client={client} onDone={() => { setOpen(false); onChange(); }} />
    </div>
  );
}

function SignSheet({ open, onClose, b, base, client, onDone }) {
  const [name, setName] = useState(client?.name || "");
  const [method, setMethod] = useState("typed");
  const [fields, setFields] = useState({});
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const canvas = useRef(null);
  const drawing = useRef(false);
  function pos(e) { const r = canvas.current.getBoundingClientRect(); const t = e.touches?.[0] || e; return [t.clientX - r.left, t.clientY - r.top]; }
  function down(e) { drawing.current = true; const c = canvas.current.getContext("2d"); c.lineWidth = 2.2; c.lineCap = "round"; c.strokeStyle = "#14151A"; c.beginPath(); c.moveTo(...pos(e)); }
  function move(e) { if (!drawing.current) return; e.preventDefault(); const c = canvas.current.getContext("2d"); c.lineTo(...pos(e)); c.stroke(); }
  async function send() { setErr(null); try { const r = await cpost(`${base}/otp`); setSent(r); } catch (e) { setErr(e); } }
  async function sign() {
    setBusy(true); setErr(null);
    try { await cpost(`${base}/sign`, { block_id: b.id, signer_id: b.my_signer_id, name, method, image: method === "drawn" ? canvas.current.toDataURL("image/png") : null, code, fields }); onDone(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Sign the agreement">
      <div className="space-y-3">
        {b.fields.map((f) => <label key={f.key} className="block"><span className="mb-1 block text-[14px] font-bold">{f.label}{f.permission === "client_must_fill" ? " *" : ""}</span><input className="c-in" value={fields[f.key] ?? f.value ?? ""} onChange={(e) => setFields({ ...fields, [f.key]: e.target.value })} /></label>)}
        <input className="c-in" aria-label="Your full name" placeholder="Your full name" value={name} onChange={(e) => setName(e.target.value)} />
        <div className="flex gap-2">{[["typed", "Type"], ["drawn", "Draw"]].map(([k, l]) => <button key={k} aria-pressed={method === k} onClick={() => setMethod(k)} className="c-btn2 flex-1" style={method === k ? { borderColor: "var(--c-primary)" } : {}}>{l}</button>)}</div>
        {method === "typed" ? <div className="c-card p-4 text-center text-[28px] italic" style={{ fontFamily: "Georgia, serif" }}>{name || "Your name"}</div>
          : <canvas ref={canvas} width={340} height={140} className="c-card w-full touch-none" onMouseDown={down} onMouseMove={move} onMouseUp={() => (drawing.current = false)} onTouchStart={down} onTouchMove={move} onTouchEnd={() => (drawing.current = false)} />}
        {!sent ? <button className="c-btn w-full" disabled={!name.trim()} onClick={send}>Send me a code to confirm</button> : <>
          <p className="text-[14px] c-muted">Enter the code we sent you on {sent.channel === "email" ? "email" : "WhatsApp"}.{sent.qa_code ? ` (Test code: ${sent.qa_code})` : ""}</p>
          <input className="c-in text-center text-[22px] tracking-[.4em]" aria-label="6-digit code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <button className="c-btn w-full" disabled={busy || code.length !== 6} onClick={sign}>{busy ? "Signing…" : "Sign"}</button></>}
        {err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}
        <p className="text-[12px] c-muted">We record your name, a verified code, the time and a fingerprint of this exact text. You'll get a signed copy by email.</p>
      </div>
    </Sheet>
  );
}

function Scheduler({ b, base, preview, onChange }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (!b.session_type) return null;
  if (b.session) return (
    <div className="c-card p-4"><div className="c-kicker">{b.session.status === "held" ? "Held for you" : "Booked"}</div><b className="text-[18px]">{b.session.label}</b>
      {b.session.status === "held" && <p className="text-[14px] c-muted">Your time is held while you finish. It's confirmed once {b.reserve_requires.join(" and ").replace("sign", "you sign").replace("pay", "your payment is confirmed")}.</p>}
      {b.session.meet_link && <a href={b.session.meet_link} className="mt-1 block font-bold underline">Call link</a>}</div>
  );
  return (
    <div><div className="mb-2 font-bold">Pick a time for {b.session_type.name}</div>
      <SlotPicker onPick={async (s) => { if (preview) return; setBusy(true); setErr(null); try { await cpost(`${base}/book`, { block_id: b.id, start: s }); await onChange(); } catch (e) { setErr(e); } finally { setBusy(false); } }}
        loadSlots={(a, z) => preview ? Promise.resolve([]) : cget(`${base}/slots?block_id=${b.id}&date_from=${encodeURIComponent(a)}&date_to=${encodeURIComponent(z)}`)} />
      {busy && <p className="c-muted">Holding your time…</p>}{err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}</div>
  );
}

/** Amount due now, the full schedule, how to pay, and "I've paid". */
export function Pay({ inv, claimUrl, planUrl, promoUrl, version, onChange }) {
  const [method, setMethod] = useState("upi");
  const [open, setOpen] = useState(null);
  const [promo, setPromo] = useState("");
  const [err, setErr] = useState(null);
  const phone = typeof window !== "undefined" && /Android|iPhone|iPad/i.test(navigator.userAgent);
  const tz = myTz();
  const due = inv.schedule.find((s) => !["paid"].includes(s.state));
  const amount = due ? due.left_paise : 0;
  return (
    <div className="space-y-4">
      <div className="c-card p-5">
        <div className="flex items-baseline justify-between"><div className="c-kicker">{inv.doc_title} {inv.number || ""}</div><span className="text-[13px] c-muted">Total {inr(inv.totals.total)}</span></div>
        {due ? <>
          <div className="mt-3 text-[13px] c-muted" style={due.state === "overdue" ? { color: "#B33A2A", fontWeight: 700 } : {}}>{due.state === "processing" ? "Waiting for confirmation" : due.state === "overdue" ? "Overdue" : "Due now"}</div>
          <div className="text-[40px] font-extrabold tracking-[-0.03em]" style={{ color: "var(--c-deep)" }}>{inr(amount)}</div>
          <div className="text-[14px] c-muted">{due.label} · {due.due_label}</div></> : <div className="mt-3 text-[22px] font-extrabold">Paid in full. Thank you!</div>}
        <table className="mt-4 w-full text-[14px]"><tbody>
          {inv.lines.map((l) => <tr key={l.id} className="border-t border-[#efebe2]"><td className="py-2">{l.name}{l.unit === "hour" ? <span className="block text-[13px] c-muted">{l.qty} h × {inr(l.price_paise)}</span> : l.qty !== 1 ? ` × ${l.qty}` : ""}</td>
            <td className="py-2 text-right">{inr(l.amount_paise ?? Math.round(l.qty * l.price_paise))}</td></tr>)}
          {inv.totals.discount > 0 && <tr><td className="py-1 c-muted">Discount</td><td className="py-1 text-right">−{inr(inv.totals.discount)}</td></tr>}
          {inv.totals.promo > 0 && <tr><td className="py-1 c-muted">Promo</td><td className="py-1 text-right">−{inr(inv.totals.promo)}</td></tr>}
          {inv.totals.cgst > 0 && <tr><td className="py-1 c-muted">CGST + SGST</td><td className="py-1 text-right">{inr(inv.totals.cgst + inv.totals.sgst)}</td></tr>}
          {inv.totals.igst > 0 && <tr><td className="py-1 c-muted">IGST</td><td className="py-1 text-right">{inr(inv.totals.igst)}</td></tr>}
        </tbody></table>
        <div className="mt-3 border-t border-[#e6e1d6] pt-3">{inv.schedule.map((s) => (
          <div key={s.id} className="flex items-center justify-between py-1.5 text-[14px]"><span>{s.label} <span className="c-muted">· {s.state === "paid" ? `paid ${s.paid_at ? fmtDate(s.paid_at, tz) : ""}` : s.due_label}</span></span>
            <span className="flex items-center gap-2">{s.state === "paid" ? <a className="text-[13px] underline" href={`/api/public/i/${inv.token}/receipt/${s.id}.pdf`}>Receipt</a> : s.state === "processing" ? <span className="text-[12px] c-muted">Processing</span> : null}<b>{inr(s.amount_paise + (s.late_fee_paise || 0))}</b></span></div>))}</div>
      </div>
      {due && due.state !== "processing" && <>
        {inv.client_choice?.allowed && planUrl && <div className="flex gap-2"><button className="c-btn2 flex-1" onClick={async () => { await cpost(planUrl, { invoice_id: inv.id, plan: "full" }); onChange(); }}>Pay in full</button>
          <button className="c-btn2 flex-1" onClick={async () => { await cpost(planUrl, { invoice_id: inv.id, plan: "split", months: inv.client_choice.months || 3 }); onChange(); }}>Split into {inv.client_choice.months || 3} monthly</button></div>}
        <div className="flex gap-2">{[["upi", "UPI"], ["bank", "Bank transfer"]].map(([k, l]) => <button key={k} aria-pressed={method === k} onClick={() => setMethod(k)} className="c-btn2 flex-1" style={method === k ? { borderColor: "var(--c-primary)", background: "#fff" } : {}}>{l}</button>)}</div>
        {method === "upi" && (due.upi_link ? <div className="c-card p-4 text-center">
          {phone ? <a href={due.upi_link} className="c-btn flex w-full items-center justify-center">Pay {inr(amount)} by UPI</a> : <><img src={due.upi_qr} alt="UPI QR code" className="mx-auto h-48 w-48" /><p className="mt-2 text-[14px] c-muted">Scan with any UPI app</p></>}
          <p className="mt-2 text-[13px] c-muted">To {inv.pay_to.payee} · {inv.pay_to.upi_id}</p></div> : <p className="c-muted">UPI isn't set up for this invoice. Please use bank transfer.</p>)}
        {method === "bank" && inv.pay_to.bank?.account_no && <div className="c-card space-y-1 p-4 text-[14px]">
          {[["Account name", inv.pay_to.bank.account_name], ["Account number", inv.pay_to.bank.account_no], ["IFSC", inv.pay_to.bank.ifsc], ["Bank", inv.pay_to.bank.bank_name]].map(([k, v]) => <div key={k} className="flex justify-between"><span className="c-muted">{k}</span><b className="select-all">{v}</b></div>)}
          <div className="flex justify-between"><span className="c-muted">Amount</span><b>{inr(amount)}</b></div></div>}
        {promoUrl && !inv.promo && <div className="flex gap-2"><input className="c-in" placeholder="Promo code" value={promo} onChange={(e) => setPromo(e.target.value.toUpperCase())} /><button className="c-btn2" onClick={async () => { setErr(null); try { await cpost(promoUrl, { invoice_id: inv.id, code: promo }); onChange(); } catch (e) { setErr(e); } }}>Apply</button></div>}
        {claimUrl && <button className="c-btn w-full" onClick={() => setOpen(due)}>I've paid</button>}
        <p className="text-center text-[12px] c-muted">You pay {inv.pay_to.payee} directly. We never hold your money.</p>
      </>}
      {due?.state === "processing" && <div className="c-card p-4 text-[14px]">Thanks! We'll confirm your payment shortly and send you a receipt.</div>}
      {err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}
      <ClaimSheet item={open} inv={inv} method={method} url={claimUrl} version={version} onClose={() => setOpen(null)} onDone={() => { setOpen(null); onChange(); }} />
    </div>
  );
}

function ClaimSheet({ item, inv, method, url, version, onClose, onDone }) {
  const [ref, setRef] = useState("");
  const [shot, setShot] = useState(null);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!item) return null;
  return (
    <Sheet open onClose={onClose} title="Tell us you've paid">
      <div className="space-y-3">
        <p className="text-[14px] c-muted">{inr(item.left_paise)} by {method === "upi" ? "UPI" : "bank transfer"}. Adding the reference helps us confirm faster.</p>
        <input className="c-in" placeholder="UPI / UTR reference (optional)" value={ref} onChange={(e) => setRef(e.target.value)} />
        <label className="block text-[14px]"><span className="mb-1 block font-bold">Screenshot (optional)</span><input type="file" accept="image/*,application/pdf" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setShot(await toDataUrl(f)); }} /></label>
        {err && <p className="font-bold text-[#B33A2A]">{err.message}</p>}
        <button className="c-btn w-full" disabled={busy} onClick={async () => { setBusy(true); setErr(null); try { await cpost(url, { invoice_id: inv.id, item_id: item.id, method, reference: ref, screenshot: shot, version }); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); } }}>{busy ? "Sending…" : "Confirm I've paid"}</button>
      </div>
    </Sheet>
  );
}

function Quote({ b, base, preview, onChange }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [res, setRes] = useState(null);
  const unit = (i) => (i.qty ? `${i.qty} ${i.unit === "hour" ? "h" : i.unit === "day" ? (i.qty === 1 ? "day" : "days") : i.unit || ""}` : "");
  return (
    <div className="c-card p-4">
      <table className="w-full text-[15px]"><tbody>
        {b.items.map((i, k) => (
          <tr key={k} className="border-t border-[#efebe2] first:border-0"><td className="py-2 pr-2">{i.label}{unit(i) && <span className="block text-[13px] c-muted">{unit(i)}</span>}</td>
            <td className="tnum py-2 text-right">{inr(i.price_paise)}</td></tr>))}
        <tr className="border-t-2 border-[#d9d2c3]"><td className="py-3 font-extrabold">Total</td><td className="tnum py-3 text-right text-[20px] font-extrabold">{inr(b.total_paise)}</td></tr>
      </tbody></table>
      <p className="text-[13px] c-muted">Valid until {b.valid_label}. <a className="underline" href={b.pdf} target="_blank" rel="noreferrer">Download as PDF</a></p>
      {b.accepted || res ? (
        <div className="mt-3 rounded-[10px] bg-[#f3efe4] p-3 text-[15px]"><b>Accepted. Thank you!</b>
          {res?.invoice_link && <p className="mt-1">Your invoice is ready: <a className="font-bold underline" href={res.invoice_link}>view and pay</a>.</p>}</div>
      ) : b.expired ? (
        <p className="mt-3 text-[15px] font-bold text-[#B33A2A]">This quote has expired. Please ask for a new one.</p>
      ) : (
        <>
          {err && <p className="mt-2 text-[14px] font-bold text-[#B33A2A]">{err}</p>}
          <button className="c-btn mt-3 w-full" disabled={busy || preview} onClick={async () => {
            setBusy(true); setErr(null);
            try { setRes(await cpost(`${base}/accept`)); await onChange(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
          }}>{busy ? "One moment…" : "Accept quote"}</button>
        </>
      )}
    </div>
  );
}

function RetainerPlan({ b }) {
  const per = b.period === "quarterly" ? "quarter" : "month";
  return (
    <div className="c-card p-4">
      <div className="c-kicker">Monthly plan</div>
      <div className="mt-1 text-[20px] font-extrabold">{b.name}</div>
      <div className="tnum mt-1 text-[24px] font-extrabold">{b.kind === "payg" ? `Up to ${inr(b.cap_paise)}` : inr(b.fee_paise)}<span className="text-[15px] font-medium c-muted"> a {per}</span></div>
      {b.kind === "hours" && b.included_hours && <p className="mt-1">Includes {b.included_hours} hours each {per}.</p>}
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[14px] c-muted">{(b.terms || []).map((t, i) => <li key={i}>{t}</li>)}
        <li>Invoiced {b.billing === "arrears" ? "at the end" : "at the start"} of each {per}. Pay by UPI or bank transfer.</li></ul>
    </div>
  );
}

function Timesheet({ ts, token }) {
  const [open, setOpen] = useState(ts.mode === "full");
  return (
    <div className="c-card p-4">
      <div className="flex items-center"><b className="flex-1">Timesheet · {ts.total_hours} hours</b>
        {ts.mode === "link" && <button className="text-[14px] font-bold underline" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>}</div>
      {open && <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[420px] text-[14px]"><thead><tr className="text-left text-[12px] uppercase c-muted">{ts.columns.map((c) => <th key={c} className={c === "hours" ? "py-1 text-right" : "py-1"}>{c}</th>)}</tr></thead>
        <tbody>{ts.rows.map((r, i) => <tr key={i} className="border-t border-[#efebe2]">{ts.columns.map((c) => <td key={c} className={c === "hours" ? "tnum py-2 text-right" : "py-2 pr-2"}>{r[c]}</td>)}</tr>)}</tbody></table></div>}
      <span className="hidden">{token}</span>
    </div>
  );
}

export function InvoicePage() {
  const { token } = useParams();
  const s = useLoad(() => cget(`/api/public/i/${token}`), [token]);
  useBrand(s.data?.brand);
  if (s.loading && !s.data) return <Loading />;
  if (s.error) return <Fail error={s.error} />;
  const d = s.data;
  return (
    <div className="min-h-screen"><Header brand={d.brand} />
      <main className="mx-auto max-w-2xl space-y-4 px-5 py-6">
        <div><div className="c-kicker">For {d.client.name}{d.client.company ? `, ${d.client.company}` : ""}</div><h1 className="mt-1 text-[26px] font-extrabold">{d.project}</h1>
          {d.consultant.gstin && <p className="text-[13px] c-muted">GSTIN {d.consultant.gstin} · {d.consultant.address}</p>}</div>
        <Pay inv={{ ...d.invoice, token }} claimUrl={`/api/public/i/${token}/claim`} onChange={async () => s.set(await cget(`/api/public/i/${token}`))} />
        {d.timesheet && <Timesheet ts={d.timesheet} token={token} />}
        {d.invoice.number && <p className="text-[13px]"><a className="underline" href={`/api/public/i/${token}/invoice.pdf`} target="_blank" rel="noreferrer">Download the invoice (PDF)</a></p>}
        {d.invoice.terms && <p className="text-[13px] c-muted">{d.invoice.terms}</p>}
      </main><Footer brand={d.brand} /></div>
  );
}
