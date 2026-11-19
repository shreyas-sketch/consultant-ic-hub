import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowLeft, Mail, MessageCircle, Sparkles } from "lucide-react";
import { act, useAct, useRefresh } from "@/shared/api";
import { ago, dt, titleCase } from "@/shared/lib/format";
import { AgentChip, Button, Card, Chip, Empty, Loadable, PageHeader, Segmented, Textarea, cx, toast } from "@/app/ui";
import { sanitize } from "@/shared/lib/safeHtml";

export default function Inbox() {
  const { projectId } = useParams();
  const [f, setF] = useState("all");
  const q = useAct("inbox.list", { filter: f }, { refetchInterval: 30_000 });
  const nav = useNavigate();
  return (
    <div>
      <PageHeader kicker="Inbox" title="Every conversation," accent="unread first" sub="Email and WhatsApp in one list. Replies land on the right project." />
      <div className="md:grid md:grid-cols-[340px_1fr] md:gap-5">
        <div className={cx(projectId && "hidden md:block")}>
          <Segmented value={f} onChange={setF} options={[{ value: "all", label: "All" }, { value: "unread", label: "Unread" }]} />
          <div className="mt-3">
            <Loadable q={q} empty={<Empty title="No conversations yet" line="Messages you send and replies from clients show up here." />}>
              {(rows) => <Card className="p-1">{rows.map((t) => (
                <button key={t.thread_id} onClick={() => nav(`/inbox/${t.project_id}`)} className={cx("flex w-full gap-3 rounded-input px-3 py-3 text-left hover:bg-panel-raised", projectId === t.project_id && "bg-panel-raised")}>
                  {t.channel === "whatsapp" ? <MessageCircle size={17} className="mt-0.5 shrink-0 text-ivory-70" /> : <Mail size={17} className="mt-0.5 shrink-0 text-ivory-70" />}
                  <span className="min-w-0 flex-1"><span className="flex items-center gap-2"><b className="truncate">{t.contact || t.project}</b>{t.unread > 0 && <Chip tone="gold">{t.unread}</Chip>}<span className="ml-auto shrink-0 text-[12px] text-ivory-35">{ago(t.at)}</span></span>
                    <span className="block truncate text-[13px] text-ivory-70">{t.direction === "in" ? "" : "You: "}{t.preview}</span></span>
                </button>))}</Card>}
            </Loadable>
          </div>
        </div>
        <div className={cx(!projectId && "hidden md:block")}>{projectId ? <Thread pid={projectId} /> : <Card className="text-ivory-70">Pick a conversation.</Card>}</div>
      </div>
    </div>
  );
}

function Thread({ pid }) {
  const q = useAct("threads.get", { project_id: pid });
  const p = useAct("projects.get", { id: pid });
  const nav = useNavigate();
  const refresh = useRefresh();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [drafted, setDrafted] = useState(false);
  const c = p.data?.contacts?.[0];
  async function send(ch) {
    setBusy(true);
    try {
      if (ch === "email") await act("messages.send", { project_id: pid, channel: "email", subject: `Re: ${p.data.name}`, body: text.split("\n\n").map((x) => `<p>${x}</p>`).join("") });
      else await act("messages.send", { project_id: pid, channel: "whatsapp", body: text });
      setText(""); setDrafted(false); refresh("threads", "inbox");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function draft() {
    try { const r = await act("messages.draft", { project_id: pid, channel: q.data?.whatsapp_window_open ? "whatsapp" : "email" }); setText(r.body.replace(/<[^>]+>/g, (m) => (m === "</p>" ? "\n\n" : m.startsWith("<br") ? "\n" : "")).trim()); setDrafted(true); }
    catch (e) { toast(e.message, "error"); }
  }
  return (
    <Loadable q={q}>
      {(d) => (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <button onClick={() => nav("/inbox")} className="grid h-10 w-10 place-items-center rounded-full hover:bg-panel md:hidden" aria-label="Back"><ArrowLeft size={18} /></button>
            <button onClick={() => nav(`/projects/${pid}`)} className="text-[18px] font-extrabold hover:text-gold">{p.data?.name}</button>
          </div>
          <div className="space-y-3">
            {d.messages.filter((m) => m.status !== "draft").map((m) => (
              <div key={m.id} className={cx("max-w-[88%] rounded-card border p-3", m.direction === "in" ? "border-hairline bg-panel" : "ml-auto border-hairline bg-panel-raised")}>
                <div className="mb-1 flex flex-wrap items-center gap-2 text-[12px] text-ivory-35">
                  {m.channel === "whatsapp" ? <MessageCircle size={12} /> : <Mail size={12} />}
                  {m.direction === "in" ? "Client" : m.actor?.startsWith("agent:") ? <span className="text-teal">{titleCase(m.actor.slice(6))} agent</span> : "You"}
                  · {dt(m.created_at)}{m.direction === "out" && <span className={m.status === "failed" || m.status === "bounced" ? "text-alert" : ""}>· {m.status}</span>}
                </div>
                {m.subject && <b className="block">{m.subject}</b>}
                {m.body_html ? <div className="prose-dark text-[14px]" dangerouslySetInnerHTML={{ __html: sanitize(m.body_html) }} /> : <p className="whitespace-pre-wrap text-[14px]">{m.body_text || (m.wa_template ? `Template: ${m.wa_template}` : "")}</p>}
              </div>
            ))}
          </div>
          {c && (
            <Card className="mt-4">
              <div className="mb-2 flex items-center gap-2">{drafted && <AgentChip />}<span className="text-[13px] text-ivory-70">{d.whatsapp_window_open ? "WhatsApp is open for free replies (24-hour window)." : "WhatsApp window closed: replies go by email, or as an approved template."}</span></div>
              <Textarea value={text} onChange={(e) => { setText(e.target.value); setDrafted(false); }} placeholder={`Reply to ${c.name}`} />
              <div className="mt-2 flex flex-wrap justify-end gap-2">
                <Button size="sm" variant="ai" icon={Sparkles} onClick={draft}>AI draft</Button>
                {c.email && <Button size="sm" variant="primary" busy={busy} disabled={!text.trim()} onClick={() => send("email")}>Send email</Button>}
                {c.phone && d.whatsapp_window_open && <Button size="sm" busy={busy} disabled={!text.trim()} onClick={() => send("whatsapp")}>Send WhatsApp</Button>}
              </div>
            </Card>
          )}
        </div>
      )}
    </Loadable>
  );
}
