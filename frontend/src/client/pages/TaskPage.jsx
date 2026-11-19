// The client's link for one request: mark it done, upload a file, or reply.
import { useState } from "react";
import { useParams } from "react-router";
import { Fail, Footer, Header, Loading, cget, cpost, toDataUrl, useBrand, useLoad } from "../kit";

export default function TaskPage() {
  const { token } = useParams();
  const s = useLoad(() => cget(`/api/public/t/${token}`), [token]);
  useBrand(s.data?.brand);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  if (s.loading && !s.data) return <Loading />;
  if (s.error) return <Fail error={s.error} />;
  const t = s.data.task;
  async function run(path, body) {
    setBusy(true); setErr(null);
    try { const r = await cpost(`/api/public/t/${token}/${path}`, body); s.set({ ...s.data, task: r.task }); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="min-h-screen"><Header brand={s.data.brand} />
      <main className="mx-auto max-w-xl space-y-4 px-5 py-6">
        <div><div className="c-kicker">{t.project}</div><h1 className="mt-1 text-[26px] font-extrabold leading-tight">{t.title}</h1>
          {t.due && <p className={`mt-1 text-[14px] ${t.overdue ? "font-bold text-[#B33A2A]" : "c-muted"}`}>{t.overdue ? "Was due" : "Due"} {t.due}</p>}</div>
        {t.details && <div className="c-card whitespace-pre-wrap p-4">{t.details}</div>}
        {t.done ? <div className="c-card p-4"><b>Done. Thank you!</b></div> : (
          <>
            <label className="c-btn2 flex w-full cursor-pointer items-center justify-center">{busy ? "Uploading…" : "Upload a file"}
              <input type="file" className="hidden" disabled={busy} onChange={async (e) => { const f = e.target.files?.[0]; if (f) await run("upload", { name: f.name, data: await toDataUrl(f) }); }} /></label>
            {t.uploads.length > 0 && <div className="text-[14px] c-muted">Sent: {t.uploads.map((u) => u.name).join(", ")}</div>}
            <div className="flex gap-2"><input className="c-in" placeholder="Reply (optional)" value={msg} onChange={(e) => setMsg(e.target.value)} />
              <button className="c-btn2" disabled={busy || !msg.trim()} onClick={async () => { await run("reply", { text: msg }); setMsg(""); }}>Send</button></div>
            {t.replies.length > 0 && t.replies.map((r, i) => <div key={i} className="c-card p-3 text-[14px]">{r.text}</div>)}
            {err && <p className="text-[14px] font-bold text-[#B33A2A]">{err}</p>}
            <button className="c-btn w-full" disabled={busy} onClick={() => run("done")}>Mark as done</button>
          </>
        )}
      </main><Footer brand={s.data.brand} /></div>
  );
}
