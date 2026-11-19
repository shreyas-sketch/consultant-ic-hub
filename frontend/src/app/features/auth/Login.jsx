import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/shared/api";
import { Wordmark } from "@/app/layout/AppShell";
import { Button, Input } from "@/app/ui";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState("phone");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [qa, setQa] = useState(null);
  const [cool, setCool] = useState(0);
  const nav = useNavigate();
  const qc = useQueryClient();
  const codeRef = useRef(null);
  useEffect(() => { get("/api/health").then((h) => setQa(h.qa ? {} : null)).catch(() => {}); }, []);
  useEffect(() => { if (cool > 0) { const t = setTimeout(() => setCool(cool - 1), 1000); return () => clearTimeout(t); } }, [cool]);

  async function request() {
    setErr(null); setBusy(true);
    try {
      const r = await post("/api/auth/otp/request", { phone });
      setStep("code"); setCool(30);
      if (r.qa_code) setQa({ code: r.qa_code });
      setTimeout(() => codeRef.current?.focus(), 50);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  }
  async function verify(c = code) {
    setErr(null); setBusy(true);
    try { await post("/api/auth/otp/verify", { phone, code: c }); qc.clear(); nav(nextUrl()); }
    catch (e) { setErr(e); setCode(""); } finally { setBusy(false); }
  }
  async function persona(p) {
    await post("/api/qa/login", { persona: p }); qc.clear(); nav(p === "staff" ? "/admin" : nextUrl());
  }
  const invited = err?.code === "not_invited";
  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <div className="w-full max-w-sm rise">
        <Wordmark />
        <h1 className="mt-8 text-[32px] font-extrabold leading-tight tracking-[-0.02em]">Your practice, <span className="text-gold">in one login.</span></h1>
        <p className="mt-2 font-light text-ivory-70">Enquiries, calls, proposals, contracts, invoices and follow-ups — with AI drafting the routine work for your OK.</p>
        {invited ? (
          <p className="mt-10 text-[17px] font-bold">{err.message}</p>
        ) : step === "phone" ? (
          <form className="mt-8 space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); request(); }}>
            <Input inputMode="tel" autoComplete="tel" placeholder="Mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} />
            {err && <p className="text-[14px] text-alert">{err.message}</p>}
            <Button variant="primary" size="lg" className="w-full" busy={busy}>Send code on WhatsApp</Button>
          </form>
        ) : (
          <form className="mt-8 space-y-3" noValidate onSubmit={(e) => { e.preventDefault(); verify(); }}>
            <p className="text-ivory-70">Enter the 6-digit code we sent to {phone}.</p>
            <Input ref={codeRef} inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="tnum text-center text-[22px] tracking-[0.5em]"
              value={code} onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 6); setCode(v); if (v.length === 6) verify(v); }} />
            {qa?.code && <p className="font-mono text-[13px] text-ivory-35">QA mode: your code is {qa.code} (000000 also works)</p>}
            {err && <p className="text-[14px] text-alert">{err.message}</p>}
            <Button variant="primary" size="lg" className="w-full" busy={busy}>Log in</Button>
            <button type="button" disabled={cool > 0} onClick={request} className="w-full py-2 text-[14px] text-ivory-70 disabled:opacity-40">
              {cool > 0 ? `Resend code in ${cool}s` : "Resend code (SMS if WhatsApp fails)"}</button>
          </form>
        )}
        <Link to="/admin/login" className="mt-8 block text-center text-[13px] text-ivory-35 hover:text-ivory-70">Product team? Sign in with email</Link>
        {qa && (
          <div className="mt-10 border-t border-hairline pt-4">
            <p className="font-mono text-[12px] text-ivory-35">QA MODE · log in as</p>
            <div className="mt-2 flex flex-wrap gap-2">{["owner", "admin", "manager", "member", "collaborator", "new", "staff"].map((p) => (
              <button key={p} onClick={() => persona(p)} className="rounded-full border border-hairline px-3 py-1.5 text-[13px] text-ivory-70 hover:text-ivory">{p}</button>))}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// After login, go back where the person was heading (e.g. an assistant's sign-in page). Same-site paths only.
function nextUrl() {
  const n = new URLSearchParams(location.search).get("next") || "/";
  return n.startsWith("/") && !n.startsWith("//") ? n : "/";
}
