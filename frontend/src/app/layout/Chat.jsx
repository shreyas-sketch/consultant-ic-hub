import { useEffect, useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { act, useRefresh } from "@/shared/api";
import { inr } from "@/shared/lib/format";
import { Sheet, ThinkingDots } from "@/app/ui";

/** "Ask or tell": a teal-led panel available on every screen. AI output sits on the background, no bubble. */
export default function Chat({ open, onClose }) {
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);
  const refresh = useRefresh();
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  async function send(t = text) {
    if (!t.trim()) return;
    const history = msgs.map((m) => ({ role: m.role, content: m.text }));
    setMsgs((m) => [...m, { role: "user", text: t }]);
    setText("");
    setBusy(true);
    try {
      const r = await act("chat.send", { message: t, history });
      setMsgs((m) => [...m, { role: "assistant", text: r.answer, cost: r.cost_paise, approvals: r.approvals?.length }]);
      refresh();
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", text: e.message, error: true }]);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet open={open} onClose={onClose} title={<span className="flex items-center gap-2 text-teal"><Sparkles size={18} /> Ask or tell</span>} ai wide>
      <div className="max-h-[52vh] min-h-[200px] space-y-4 overflow-y-auto pr-1">
        {!msgs.length && (
          <div className="space-y-2">
            <p className="text-ivory-70">Ask about your practice, or tell me what to do. Anything that goes to a client waits for your OK.</p>
            {["Which leads came in this week?", "Who owes me money?", "What's on today?", "Add a task to call Vikram tomorrow"].map((s) => (
              <button key={s} onClick={() => send(s)} className="ai mr-2 rounded-full border border-teal/50 px-3 py-1.5 font-mono text-[13px] text-teal">{s}</button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => m.role === "user" ? (
          <div key={i} className="ml-auto max-w-[85%] rounded-[16px_16px_4px_16px] bg-panel-raised px-4 py-2.5 font-mono text-[14px]">{m.text}</div>
        ) : (
          <div key={i} className={`max-w-[95%] border-l-2 pl-3 font-mono text-[14px] leading-relaxed ${m.error ? "border-alert text-ivory-70" : "border-teal"}`}>
            {m.text}
            {(m.approvals > 0 || m.cost > 0) && <div className="mt-1 text-[12px] text-ivory-35">{m.approvals ? `${m.approvals} item(s) waiting for your OK · ` : ""}AI cost {inr(m.cost)}</div>}
          </div>
        ))}
        {busy && <ThinkingDots />}
        <div ref={end} />
      </div>
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input className="ai flex-1 rounded-input border border-hairline bg-bg px-3.5 py-3 font-mono text-[15px] focus:border-teal focus:outline-none" value={text}
          onChange={(e) => setText(e.target.value)} placeholder="Ask or tell…" />
        <button className="grid h-12 w-12 place-items-center rounded-full border border-teal/70 text-teal" aria-label="Send"><Send size={18} /></button>
      </form>
    </Sheet>
  );
}
