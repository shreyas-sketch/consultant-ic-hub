import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Sparkles } from "lucide-react";
import { act, useAct } from "../../lib/api";
import { dt } from "../../lib/format";
import { Card, Empty, Loadable, PageHeader, Segmented, cx } from "../components/ui";

export default function Tasks() {
  const [sp] = useSearchParams();
  const [view, setView] = useState(sp.get("view") === "client" ? "client" : "team");
  const [scope, setScope] = useState("today");
  const q = useAct("tasks.list", { scope: view === "client" ? "open" : scope, audience: view });
  const nav = useNavigate();
  return (
    <div>
      <PageHeader kicker="Tasks" title="What needs doing," accent="today" sub="Tasks from you, your automations and your agents. Clients never see them." />
      <div className="mb-3"><Segmented value={view} onChange={setView} options={[{ value: "team", label: "Team tasks" }, { value: "client", label: "Waiting on clients" }]} /></div>
      {view === "team" && <Segmented value={scope} onChange={setScope} options={[{ value: "today", label: "Today" }, { value: "overdue", label: "Overdue" }, { value: "upcoming", label: "Upcoming" }, { value: "open", label: "All open" }, { value: "done", label: "Done" }]} />}
      <div className="mt-4">
        <Loadable q={q} empty={<Empty title="Nothing here" line="Enjoy the quiet." />}>
          {(rows) => <Card className="p-2">{rows.map((t) => (
            <label key={t.id} className="flex min-h-[52px] items-center gap-3 border-t border-hairline px-2 py-2 first:border-0">
              <input type="checkbox" checked={t.done} onChange={async () => { await act("tasks.complete", { id: t.id }); q.refetch(); }} />
              <span className="min-w-0 flex-1"><span className={cx("block", t.done && "text-ivory-35 line-through")}>{t.title}</span>
                <span className={cx("text-[12px]", t.due_at && new Date(t.due_at) < new Date() && !t.done ? "text-alert" : "text-ivory-35")}>{dt(t.due_at)}</span></span>
              {t.created_by?.startsWith("agent:") && <Sparkles size={14} className="text-teal" />}
              {t.project_id && <button onClick={(e) => { e.preventDefault(); nav(`/projects/${t.project_id}`); }} className="text-[13px] font-bold text-gold">Open</button>}
            </label>))}</Card>}
        </Loadable>
      </div>
    </div>
  );
}
