import { useState } from "react";
import { useNavigate } from "react-router";
import { Mail, MessageCircle, Sparkles } from "lucide-react";
import { act, useAct, useRefresh } from "@/shared/api";
import { ago, inr, titleCase } from "@/shared/lib/format";
import { AgentChip, Button, Card, Chip, Empty, Input, Loadable, PageHeader, Segmented, Textarea, toast } from "@/app/ui";
import { sanitize } from "@/shared/lib/safeHtml";

/** One screen: everything an agent or automation prepared, with Approve / Edit / Skip. */
export default function Approvals() {
  const [status, setStatus] = useState("pending");
  const q = useAct("approvals.list", { status });
  return (
    <div>
      <PageHeader ai kicker="Approvals" title="Needs" accent="your OK" sub="In Draft mode nothing leaves your account until you approve it here." />
      <Segmented ai value={status} onChange={setStatus} options={[{ value: "pending", label: "Waiting" }, { value: "approved", label: "Approved" }, { value: "skipped", label: "Skipped" }, { value: "expired", label: "Expired" }]} />
      <div className="mt-4 space-y-3">
        <Loadable q={q} empty={<Empty title={status === "pending" ? "All caught up" : "Nothing here"} line={status === "pending" ? "When an agent drafts a reply, a nudge or a proposal, it waits here for you." : ""} />}>
          {(rows) => rows.map((a) => <Item key={a.id} a={a} onDone={() => q.refetch()} />)}
        </Loadable>
      </div>
    </div>
  );
}

function Item({ a, onDone }) {
  const [edit, setEdit] = useState(false);
  const [subject, setSubject] = useState(a.args.subject || "");
  const [body, setBody] = useState(a.args.body || a.preview.body || "");
  const [busy, setBusy] = useState("");
  const nav = useNavigate();
  const refresh = useRefresh();
  const who = a.agent ? `${titleCase(a.agent)} agent` : a.source === "mcp" ? "Outside assistant" : "Automation";
  async function decide(kind) {
    setBusy(kind);
    try {
      await act(kind === "skip" ? "approvals.skip" : "approvals.approve", { id: a.id, edits: edit ? { subject, body } : null });
      toast(kind === "skip" ? "Skipped. Nothing was sent." : "Approved and sent", kind === "skip" ? "ok" : "ai");
      onDone(); refresh("approvals", "home", "projects");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  }
  const pending = a.status === "pending";
  return (
    <Card ai={pending}>
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone="teal"><Sparkles size={11} /> {who}</Chip>
        <span className="text-[13px] text-ivory-70">{a.why}</span>
        {a.project_name && <button onClick={() => nav(`/projects/${a.project_id}`)} className="text-[13px] font-bold text-gold">{a.project_name}</button>}
        <span className="ml-auto text-[12px] text-ivory-35">{ago(a.created_at)}</span>
      </div>
      <div className="mt-3 rounded-input border border-hairline bg-bg/60 p-3">
        <div className="mb-1 flex items-center gap-2 text-[12px] uppercase tracking-[0.14em] text-ivory-35">
          {a.preview.channel === "whatsapp" ? <MessageCircle size={13} /> : <Mail size={13} />}{a.action.replace(".", " · ")}
          {a.level === "money" && <Chip tone="gold">Money</Chip>}{!edit && pending && <AgentChip />}
        </div>
        {edit ? (
          <div className="space-y-2">
            {a.preview.channel !== "whatsapp" && <Input value={subject} onChange={(e) => setSubject(e.target.value)} />}
            <Textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
        ) : (
          <>
            <b className="block">{a.preview.subject}</b>
            {a.preview.amount_paise ? <p className="text-gold">{inr(a.preview.amount_paise)}</p> : null}
            {a.preview.body && <div className="prose-dark mt-1 text-[14px]" dangerouslySetInnerHTML={{ __html: sanitize(a.preview.body) }} />}
            {a.preview.file_id && <button onClick={() => nav(`/files/${a.preview.file_id}`)} className="mt-1 text-[14px] font-bold text-gold">Open the client file</button>}
          </>
        )}
      </div>
      {pending && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" size="sm" busy={busy === "ok"} onClick={() => decide("ok")}>{edit ? "Save and approve" : "Approve"}</Button>
          {!edit && (a.action === "messages.send") && <Button size="sm" onClick={() => setEdit(true)}>Edit</Button>}
          <Button size="sm" variant="quiet" busy={busy === "skip"} onClick={() => decide("skip")}>Skip</Button>
        </div>
      )}
      {a.status === "failed" && <p className="mt-2 text-[14px] text-alert">{a.error}</p>}
    </Card>
  );
}
