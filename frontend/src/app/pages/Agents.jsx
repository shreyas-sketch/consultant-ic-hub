import { useState } from "react";
import { Bot, Sparkles } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { ago, inr, titleCase } from "../../lib/format";
import { useWs } from "../components/AppShell";
import { Button, Card, Chip, Kicker, Loadable, Meter, PageHeader, Segmented, Sheet, Textarea, toast } from "../components/ui";

const MODES = [{ value: "off", label: "Off" }, { value: "suggest", label: "Suggest" }, { value: "draft", label: "Draft for approval" }, { value: "auto", label: "Auto" }];
const FIXED = { daily_brief: "Read only", meeting: "Notes and tasks automatic; sends need your OK", chat: "Follows each tool's level", setup: "Builds your account during setup" };

export default function Agents() {
  const q = useAct("agents.list");
  const ws = useWs();
  const admin = ["owner", "admin"].includes(ws.data?.role);
  const [run, setRun] = useState(null);
  return (
    <div>
      <PageHeader ai kicker="Agents" title="Your AI team," accent="working behind approvals" sub="Each agent has one job. In Draft mode they prepare everything and wait for your OK. Money actions always wait." />
      <Loadable q={q}>
        {(d) => (
          <>
            <Card ai className="mb-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><Kicker ai>AI budget this month</Kicker><span className="tnum text-[14px]"><b className="text-teal">{inr(d.budget.spent_paise)}</b> <span className="text-ivory-70">of {inr(d.budget.cap_paise)}</span></span></div>
              <div className="mt-2"><Meter pct={d.budget.pct} ai /></div>
              <p className="mt-2 text-[13px] text-ivory-70">One budget for your whole team. At 80% you get a notice; at 100% agents pause until next month.</p>
            </Card>
            <div className="grid gap-4 md:grid-cols-2">
              {d.agents.map((a) => <AgentCard key={a.agent} a={a} admin={admin} onChange={() => q.refetch()} onRun={setRun} />)}
            </div>
          </>
        )}
      </Loadable>
      <RunSheet id={run} onClose={() => setRun(null)} />
    </div>
  );
}

function AgentCard({ a, admin, onChange, onRun }) {
  const [instr, setInstr] = useState(a.instructions);
  const [busy, setBusy] = useState(false);
  const fixed = FIXED[a.agent];
  async function set(body) {
    try { await act("agents.update", { agent: a.agent, ...body }); onChange(); toast("Saved", "ai"); } catch (e) { toast(e.message, "error"); }
  }
  return (
    <Card ai>
      <div className="flex items-center gap-2"><Bot size={18} className="text-teal" /><b className="text-[17px]">{a.label}</b>{!a.available && <Chip tone="alert">Unavailable</Chip>}
        <span className="ml-auto tnum text-[13px] text-ivory-70">{a.month_runs} runs · {inr(a.month_cost_paise)}</span></div>
      <p className="mt-1 text-[13px] text-ivory-70">Wakes: {a.wakes_on}</p>
      <div className="mt-3">
        {fixed ? <Chip tone="teal">{fixed}</Chip> : <Segmented ai value={a.enabled ? a.autonomy : "off"} onChange={(v) => admin ? set(v === "off" ? { enabled: false } : { enabled: true, autonomy: v }) : toast("Only an Owner or Admin can change this.", "error")} options={MODES} />}
      </div>
      {a.autonomy === "auto" && !fixed && <p className="mt-2 text-[13px] text-ivory-70">Auto sends messages by itself. Invoices, payment requests and refunds still wait for your OK.</p>}
      {admin && a.agent !== "setup" && (
        <div className="mt-3">
          <Textarea ai rows={2} placeholder="Standing instructions (optional), e.g. always offer a Saturday slot" value={instr} onChange={(e) => setInstr(e.target.value)} />
          {instr !== a.instructions && <Button className="mt-2" size="sm" variant="ai" onClick={() => set({ instructions: instr })}>Save instructions</Button>}
        </div>
      )}
      {["followup", "collections", "daily_brief"].includes(a.agent) && <Button className="mt-3" size="sm" variant="ai" busy={busy} onClick={async () => { setBusy(true); try { const r = await act("agents.run", { agent: a.agent }); toast(r.summary, "ai"); onChange(); } catch (e) { toast(e.message, "error"); } finally { setBusy(false); } }}>Run now</Button>}
      {a.runs.length > 0 && (
        <div className="mt-3 border-t border-hairline pt-2">
          {a.runs.map((r) => (
            <button key={r.id} onClick={() => onRun(r.id)} className="flex w-full items-center gap-2 py-1.5 text-left text-[13px]">
              <Sparkles size={12} className="shrink-0 text-teal" /><span className="min-w-0 flex-1 truncate">{r.summary}</span><span className="shrink-0 text-ivory-35">{ago(r.at)}</span></button>
          ))}
        </div>
      )}
    </Card>
  );
}

function RunSheet({ id, onClose }) {
  const q = useAct("agents.run_get", { id }, { enabled: !!id });
  return (
    <Sheet open={!!id} onClose={onClose} title="Agent run" ai wide>
      {q.data && (
        <div className="space-y-3 font-mono text-[13px]">
          <p>{q.data.summary}</p>
          <p className="text-ivory-35">{titleCase(q.data.agent)} · {q.data.status} · {q.data.tokens_in + q.data.tokens_out} tokens · {inr(q.data.cost_paise)} · mode {q.data.autonomy}</p>
          {q.data.tool_calls.map((c, i) => (
            <div key={i} className="rounded-input border border-teal/30 p-2">
              <div className="text-teal">{c.tool} → {c.verdict === "approve" ? "waiting for your OK" : c.verdict}</div>
              <div className="mt-1 whitespace-pre-wrap break-words text-ivory-70">{JSON.stringify(c.input, null, 1).slice(0, 600)}</div>
            </div>
          ))}
        </div>
      )}
    </Sheet>
  );
}
