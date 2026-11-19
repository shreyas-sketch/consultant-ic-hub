// "Allow this assistant?" — the page an outside assistant (Claude, ChatGPT…) opens to sign in.
import { useState } from "react";
import { useSearchParams } from "react-router";
import { ShieldCheck } from "lucide-react";
import { get, post } from "@/shared/api";
import { useQuery } from "@tanstack/react-query";
import { Wordmark } from "@/app/layout/AppShell";
import { Button, Card, ErrorCard, Field, Kicker, Segmented, Select, Skeleton } from "@/app/ui";

const SCOPES = [{ value: "read", label: "Read only" }, { value: "drafts", label: "Read + drafts" }, { value: "full", label: "Full" }];
const RANK = { read: 1, drafts: 2, full: 3 };

export default function OAuthConsent() {
  const [sp] = useSearchParams();
  const rid = sp.get("req");
  const q = useQuery({ queryKey: ["oauth", rid], queryFn: () => get(`/api/oauth/request/${rid}`), retry: false });
  const [scope, setScope] = useState(null);
  const [ws, setWs] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  async function decide(approve) {
    setBusy(true);
    try {
      const r = await post("/api/oauth/consent", { req: rid, approve, scope: scope || q.data.scope, workspace_id: ws || q.data.workspaces[0]?.id });
      location.href = r.redirect;
    } catch (e) { setBusy(false); setErr(e.message); }
  }
  return (
    <div className="mx-auto max-w-md px-4 py-10">
      <div className="mb-6"><Wordmark /></div>
      {q.isLoading ? <Skeleton className="h-64" /> : q.error ? <ErrorCard error={q.error} /> : (
        <Card ai className="space-y-4">
          <div className="flex items-center gap-2"><ShieldCheck size={20} className="text-teal" /><Kicker ai>Connect an assistant</Kicker></div>
          <h1 className="text-[22px] font-extrabold leading-tight">Allow <span className="text-teal">{q.data.client_name}</span> to work in your practice?</h1>
          <p className="text-[14px] text-ivory-70">It will act as you, with your role's limits. Anything it wants to send to a client, or anything to do with money, still waits for your OK in Approvals.</p>
          {q.data.verified_url ? <p className="break-all text-[12px] text-ivory-35">Identified by {q.data.verified_url}</p> : <p className="text-[12px] text-ivory-35">Returns to {q.data.redirect_host}</p>}
          {q.data.workspaces.length > 1 && <Field label="Practice"><Select value={ws || q.data.workspaces[0].id} onChange={(e) => setWs(e.target.value)} options={q.data.workspaces.map((w) => ({ value: w.id, label: `${w.name} (${w.role})` }))} /></Field>}
          <Field label="What may it do?" hint="It can never delete anything.">
            <Segmented ai value={scope || q.data.scope} onChange={setScope} options={SCOPES.filter((s) => RANK[s.value] <= RANK[q.data.scope])} /></Field>
          {err && <p className="text-[14px] text-alert">{err}</p>}
          <div className="grid grid-cols-2 gap-2">
            <Button variant="quiet" busy={busy} onClick={() => decide(false)}>Don't allow</Button>
            <Button variant="ai" busy={busy} onClick={() => decide(true)}>Allow</Button>
          </div>
        </Card>
      )}
    </div>
  );
}
