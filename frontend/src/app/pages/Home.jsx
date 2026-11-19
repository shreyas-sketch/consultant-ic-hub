import { useNavigate } from "react-router";
import { CalendarDays, ChevronRight, Sparkles, Video } from "lucide-react";
import { act, useAct, useRefresh } from "../../lib/api";
import { ago, date, greeting, inr, plural, time, todayLabel } from "../../lib/format";
import { useMe } from "../components/AppShell";
import { Button, Card, Chip, ErrorCard, Kicker, Meter, SkeletonList, Stat, cx, toast } from "../components/ui";

const MONEY = [["paid", "Paid", "text-gold"], ["processing", "Processing", "text-ivory-70"], ["upcoming", "Upcoming", "text-ivory-35"], ["overdue", "Overdue", "text-alert"]];

export default function Home() {
  const q = useAct("home.get", {}, { refetchInterval: 60_000 });
  const me = useMe();
  const nav = useNavigate();
  const refresh = useRefresh();
  if (q.isLoading) return <SkeletonList rows={6} />;
  if (q.isError) return <ErrorCard error={q.error} retry={() => q.refetch()} />;
  const h = q.data;
  const name = (me.data?.user?.name || "").split(" ")[0];
  return (
    <div className="space-y-5">
      <div className="rise">
        <Kicker>{todayLabel()}</Kicker>
        <h1 className="mt-1 text-[28px] font-extrabold tracking-[-0.02em]">{greeting()}{name ? "," : ""} <span className="text-gold">{name}</span></h1>
      </div>

      {h.approvals > 0 && (
        <button onClick={() => nav("/approvals")} className="ai flex w-full items-center gap-4 rounded-card border border-teal/50 bg-panel p-4 text-left shadow-teal">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-teal/15 text-teal"><Sparkles size={20} /></span>
          <span className="min-w-0 flex-1"><span className="block text-[17px] font-bold">Needs your OK ({h.approvals})</span>
            <span className="block text-[14px] text-ivory-70">Drafts from your agents and automations. Nothing goes out until you approve.</span></span>
          <ChevronRight className="text-teal" />
        </button>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="New leads" value={h.numbers.new_leads} gold={false} sub="In the first stage" />
        <Stat label="Unread" value={h.numbers.unread} gold={false} sub="Messages" />
        <Stat label="Tasks due" value={h.numbers.tasks_due} gold={false} sub="Today or late" />
        <Stat label="Received" value={h.numbers.received_month_paise === null ? "—" : inr(h.numbers.received_month_paise, { short: true })} sub="This month" />
      </div>

      {(h.unbilled?.amount_paise > 0 || h.waiting_on_client > 0 || h.budgets_at_risk > 0) && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {h.unbilled?.amount_paise > 0 && <button onClick={() => nav("/time?tab=unbilled")} className="text-left"><Stat label="Unbilled time" value={inr(h.unbilled.amount_paise, { short: true })}
            sub={`${Math.round(h.unbilled.minutes / 6) / 10}h across ${plural(h.unbilled.projects, "project")}${h.unbilled.oldest ? `, oldest ${date(h.unbilled.oldest)}` : ""}`} /></button>}
          {h.budgets_at_risk > 0 && <button onClick={() => nav("/projects")} className="text-left"><Stat label="Budgets at risk" value={h.budgets_at_risk} gold={false} sub="Past 80% of the budget" /></button>}
          {h.waiting_on_client > 0 && <button onClick={() => nav("/tasks?view=client")} className="text-left"><Stat label="Waiting on clients" value={h.waiting_on_client} gold={false} sub="Things you've asked for" /></button>}
        </div>
      )}

      {h.stale_claims > 0 && (
        <Card className="flex items-center gap-3"><span className="flex-1">{plural(h.stale_claims, "client says they've paid", "clients say they've paid")} more than 2 days ago. Please confirm or reject.</span>
          <Button size="sm" onClick={() => nav("/payments")}>Review</Button></Card>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-5">
          <Card>
            <div className="mb-2 flex items-center justify-between"><Kicker>Today's sessions</Kicker><button onClick={() => nav("/calendar")} className="text-[13px] font-bold text-gold">Calendar</button></div>
            {!h.sessions.length && <p className="text-ivory-70">No sessions today.</p>}
            {h.sessions.map((s) => (
              <div key={s.id} className="flex items-center gap-3 border-t border-hairline py-3 first:border-0">
                <span className="tnum w-20 shrink-0 font-bold text-gold">{time(s.start)}</span>
                <button onClick={() => nav(`/projects/${s.project_id}`)} className="min-w-0 flex-1 truncate text-left font-bold">{s.title}</button>
                {s.meet_link && <a href={s.meet_link} target="_blank" rel="noreferrer" className="grid h-10 w-10 place-items-center rounded-full border border-hairline"><Video size={16} /></a>}
              </div>
            ))}
          </Card>

          <Card ai>
            <div className="mb-2 flex items-center gap-2"><Kicker ai>Daily brief</Kicker><Chip tone="teal"><Sparkles size={11} /> Agent</Chip></div>
            {!h.brief && <p className="text-ivory-70">Your brief arrives every morning.</p>}
            {h.brief && (
              <>
                {!h.brief.items.length && <p className="text-ivory-70">All clear. Nothing urgent today.</p>}
                <ol className="space-y-2">
                  {h.brief.items.map((it, i) => (
                    <li key={i}><button onClick={() => nav(it.link)} className="flex w-full items-start gap-3 text-left">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-teal/60 text-[13px] font-bold text-teal">{i + 1}</span>
                      <span className="pt-0.5">{it.text}</span></button></li>
                  ))}
                </ol>
                {h.brief.money_due_week_paise > 0 && <p className="mt-3 text-[14px] text-ivory-70">Money due this week: <b className="text-gold">{inr(h.brief.money_due_week_paise)}</b></p>}
                {h.brief.changes?.length > 0 && <p className="mt-1 text-[14px] text-ivory-70">Since yesterday: {h.brief.changes.join(", ")}.</p>}
                {h.brief.trends && <p className="mt-1 text-[14px] text-ivory-70">{h.brief.trends}</p>}
                {(h.brief.insight || []).map((x, i) => <p key={i} className="mt-1 text-[14px] text-ivory-70">{x}</p>)}
              </>
            )}
          </Card>

          {h.suggested_leads > 0 && <SuggestedLeads nav={nav} refresh={refresh} />}
        </div>

        <div className="space-y-5">
          {h.money && (
            <Card>
              <Kicker>Money this month</Kicker>
              <div className="mt-3 grid grid-cols-2 gap-3">
                {MONEY.map(([k, l, c]) => (
                  <button key={k} onClick={() => nav(`/payments?tab=${k}`)} className="rounded-input bg-panel-raised p-3 text-left">
                    <div className="text-[12px] font-medium uppercase tracking-[0.14em] text-ivory-70">{l}</div>
                    <div className={cx("tnum text-[20px] font-extrabold", c)}>{inr(h.money[k], { short: true })}</div>
                  </button>
                ))}
              </div>
              {h.goal && (
                <div className="mt-4"><div className="mb-1 flex justify-between text-[13px] text-ivory-70"><span>Yearly goal {inr(h.goal.goal_paise, { short: true })}</span><span>{h.goal.pct}%</span></div><Meter pct={h.goal.pct} /></div>
              )}
            </Card>
          )}
          {h.budget.state !== "ok" && (
            <Card ai><Kicker ai>AI budget</Kicker><p className="my-2 text-[14px] text-ivory-70">{h.budget.state === "reached" ? "This month's AI budget is used up, so agents are paused." : `You've used ${h.budget.pct}% of this month's AI budget.`}</p>
              <Meter pct={h.budget.pct} ai /></Card>
          )}
          <Card>
            <Kicker>Recent activity</Kicker>
            <div className="mt-2">
              {!h.activity.length && <p className="text-ivory-70">Activity shows up here as you work.</p>}
              {h.activity.map((a) => (
                <button key={a.id} onClick={() => nav(`/projects/${a.project_id}`)} className="flex w-full items-start gap-3 border-t border-hairline py-2.5 text-left first:border-0">
                  <span className={cx("mt-2 h-1.5 w-1.5 shrink-0 rounded-full", a.actor?.startsWith("agent:") ? "bg-teal" : "bg-gold-deep")} />
                  <span className="min-w-0 flex-1 text-[14px]">{a.text}<span className="block text-[12px] text-ivory-35">{ago(a.at)}</span></span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function SuggestedLeads({ nav, refresh }) {
  const s = useAct("leads.suggested");
  async function decide(id, accept) {
    try { const r = await act("leads.decide_suggested", { id, accept }); toast(accept ? "Lead added" : "Dismissed"); refresh(); if (r.project_id) nav(`/projects/${r.project_id}`); }
    catch (e) { toast(e.message, "error"); }
  }
  return (
    <Card ai>
      <Kicker ai>Found in your inbox</Kicker>
      {(s.data || []).map((x) => (
        <div key={x.id} className="mt-3 border-t border-hairline pt-3 first:border-0">
          <div className="font-bold">{x.lead.name} <span className="font-normal text-ivory-35">· {x.lead.email}</span></div>
          <p className="mt-1 font-mono text-[13px] text-ivory-70">{x.lead.message}</p>
          <div className="mt-2 flex gap-2"><Button size="sm" variant="ai" onClick={() => decide(x.id, true)}>Add as lead</Button><Button size="sm" variant="quiet" onClick={() => decide(x.id, false)}>Dismiss</Button></div>
        </div>
      ))}
    </Card>
  );
}
