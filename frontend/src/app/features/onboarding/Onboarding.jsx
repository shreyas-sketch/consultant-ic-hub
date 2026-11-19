import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { act, useAct } from "@/shared/api";
import { inr } from "@/shared/lib/format";
import { Wordmark } from "@/app/layout/AppShell";
import { Button, Card, Kicker, ThinkingDots, toast } from "@/app/ui";

/** The first-run experience is a conversation with the Setup agent, not an empty dashboard. */
export default function Onboarding() {
  const q = useAct("onboarding.questions");
  const [answers, setAnswers] = useState({});
  const [i, setI] = useState(0);
  const [text, setText] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const nav = useNavigate();
  const qc = useQueryClient();
  const end = useRef(null);
  const qs = q.data?.questions || [];
  useEffect(() => { if (q.data?.answers) setAnswers(q.data.answers); }, [q.data]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [i, busy, done]);
  useEffect(() => { act("onboarding.preview", { answers }).then(setPreview).catch(() => {}); }, [answers]);
  async function next() {
    const qn = qs[i];
    const a = { ...answers, [qn.id]: text.trim() };
    setAnswers(a); setText("");
    if (i + 1 < qs.length) { setI(i + 1); return; }
    setBusy(true);
    try { setDone(await act("onboarding.finish", { answers: a })); qc.invalidateQueries(); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function test() {
    setBusy(true);
    try { const r = await act("onboarding.test_proposal"); window.open(r.link, "_blank"); toast("Sent to you. Open it like a client would.", "ai"); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <div className="mx-auto max-w-[1100px] px-4 py-6 md:px-8">
      <Wordmark />
      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0">
          <div className="kicker kicker-ai">Setup · about 10 minutes</div>
          <h1 className="mt-1 text-[28px] font-extrabold tracking-[-0.02em]">Let's set up <span className="text-teal">your practice</span></h1>
          <p className="mt-1 font-light text-ivory-70">Answer {qs.length} short questions. I'll build your services, pipeline, first templates, booking page and follow-ups. Nothing goes to any client.</p>
          <div className="mt-6 space-y-4">
            {qs.slice(0, i + 1).map((qn, k) => (
              <div key={qn.id} className="space-y-2">
                <div className="border-l-2 border-teal pl-3 font-mono text-[15px]">{qn.q}</div>
                {answers[qn.id] && k < i && <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-[16px_16px_4px_16px] bg-panel-raised px-4 py-2.5 font-mono text-[14px]">{answers[qn.id]}</div>}
              </div>
            ))}
            {!done && !busy && qs[i] && (
              <form onSubmit={(e) => { e.preventDefault(); next(); }} className="space-y-2">
                <textarea autoFocus rows={qs[i].id === "offers" ? 4 : 2} className="ai w-full rounded-input border border-hairline bg-panel px-3.5 py-3 font-mono text-[15px] focus:border-teal focus:outline-none"
                  placeholder={qs[i].placeholder} value={text} onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && qs[i].id !== "offers") { e.preventDefault(); next(); } }} />
                <div className="flex justify-between"><span className="text-[13px] text-ivory-35">{i + 1} of {qs.length}</span>
                  <div className="flex gap-2">{i > 0 && <Button type="button" size="sm" variant="quiet" onClick={() => { setI(i - 1); setText(answers[qs[i - 1].id] || ""); }}>Back</Button>}
                    <Button size="sm" variant="ai">{i + 1 === qs.length ? "Build my account" : "Next"}</Button></div></div>
              </form>
            )}
            {busy && !done && <div className="flex items-center gap-2 font-mono text-teal"><ThinkingDots /> Building your account…</div>}
            {done && (
              <Card ai className="space-y-3 rise">
                <div className="flex items-center gap-2 font-bold text-teal"><Sparkles size={18} /> Your account is ready</div>
                <p className="text-[14px] text-ivory-70">I made: {done.templates.join(", ")}. {done.services} service package{done.services === 1 ? "" : "s"}. {done.upi_set ? "Your UPI ID is on every invoice." : "Add your UPI ID in Settings so clients can pay you."}</p>
                <p className="text-[14px]">Last step: send yourself a test proposal, so you see exactly what a client sees before a real one does.</p>
                <div className="flex flex-wrap gap-2"><Button variant="ai" busy={busy} onClick={test}>Send me a test proposal</Button><Button variant="primary" onClick={() => nav("/")}>Go to Home</Button></div>
              </Card>
            )}
            <div ref={end} />
          </div>
        </div>
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <Kicker className="mb-2">Your account, as it fills in</Kicker>
          <Card className="space-y-4">
            <div><div className="text-[13px] font-bold text-ivory-70">Services</div>
              {(preview?.services || []).map((s, k) => <div key={k} className="flex justify-between border-t border-hairline py-1.5 text-[14px] first:border-0"><span>{s.name}</span><b className="tnum text-gold">{s.price_paise ? inr(s.price_paise) : "—"}{s.monthly ? "/mo" : ""}</b></div>)}
              {!preview?.services?.length && <p className="text-[14px] text-ivory-35">Your offers appear here.</p>}</div>
            <div><div className="text-[13px] font-bold text-ivory-70">Pipeline</div><div className="mt-1 flex flex-wrap gap-1">{(preview?.pipeline || []).map((p) => <span key={p} className="rounded-full bg-panel-raised px-2 py-0.5 text-[12px]">{p}</span>)}</div></div>
            <div><div className="text-[13px] font-bold text-ivory-70">First proposal</div><p className="text-[14px]">{preview?.first_proposal}</p></div>
            <div><div className="text-[13px] font-bold text-ivory-70">Discovery call</div><p className="text-[14px]">{preview ? `${preview.discovery_call.minutes} minutes, ${preview.discovery_call.days} days a week` : ""}</p></div>
            <div><div className="text-[13px] font-bold text-ivory-70">How you get paid</div><p className="text-[14px]">{(preview?.schedule || []).map((s) => `${s.pct}% ${s.label.toLowerCase()}`).join(", ")}</p></div>
          </Card>
        </aside>
      </div>
    </div>
  );
}
