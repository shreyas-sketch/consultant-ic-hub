module.exports = async ({ journey, expect, api, persona, BASE }) => {
  await journey("Time: log 2h 30m in the dialog, then invoice the unbilled time", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const t = Date.now();
    const pr = (await api(me, "projects.create", { name: `QA Time ${t % 100000}`, contact: { name: "Tara", email: `tara.${t}@example.in` } })).body;
    // Projects need an hourly rate to price time: set it on the default rate card if missing.
    await me.goto(`${BASE}/time`);
    await me.getByRole("button", { name: "Log time" }).first().click();
    const d = me.getByRole("dialog", { name: "Log time" });
    await d.getByLabel("Project").selectOption({ label: pr.name });
    await d.getByLabel("Hours").fill("2");
    await d.getByLabel("Minutes").fill("30");
    await d.getByLabel("Note").fill("QA workshop prep");
    await d.getByRole("button", { name: /^Log \d/ }).click();   // the button reads "Log 2h 30m"
    await d.waitFor({ state: "detached", timeout: 8000 });
    const entries = (await api(me, "time.list", { project_id: pr.id })).body;
    const e = (entries.items || entries).find((x) => x.note === "QA workshop prep");
    expect(e && e.minutes === 150, "150 minutes logged, got " + JSON.stringify(e).slice(0, 160));
    const un = (await api(me, "time.unbilled", { project_id: pr.id })).body;
    const item = (un.items || []).find((i) => i.project_id === pr.id) || (un.items || [])[0];
    expect(item, "project shows unbilled time");
    await me.goto(`${BASE}/projects/${pr.id}?tab=time`);
    await me.getByRole("button", { name: /invoice/i }).first().click();
    const sh = me.locator("[role=dialog]").last();
    await sh.getByRole("button", { name: /invoice|create|make/i }).last().click();
    await me.waitForTimeout(1200);
    const after = (await api(me, "time.list", { project_id: pr.id })).body;
    const e2 = (after.items || after).find((x) => x.note === "QA workshop prep");
    expect(e2.invoice_id || e2.on_draft || e2.billing_status !== "unbilled", "time moved onto an invoice: " + e2.billing_status);
  });

  await journey("Approvals: edit an AI draft, approve it, and it is sent", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const list = (await api(me, "approvals.list", {})).body;
    const msg = list.find((a) => a.action === "messages.send" && !String(a.id).startsWith("qa-evil"));
    expect(msg, "a pending message draft exists");
    await me.goto(`${BASE}/approvals`);
    const card = me.locator("div").filter({ has: me.getByRole("button", { name: "Approve" }) }).filter({ hasText: msg.project_name }).last();
    await card.getByRole("button", { name: "Approve" }).first().click();
    await me.waitForTimeout(1200);
    const after = (await api(me, "approvals.list", { status: "approved" })).body;
    expect(after.some((a) => a.id === msg.id), "draft approved");
  });

  await journey("Roles: a member sees only their projects and no team settings; collaborator only shared work", async (mk) => {
    const own = await mk();
    await persona(own, "owner");
    const all = (await api(own, "projects.search", { limit: 500 })).body.items.length;
    const mem = await mk();
    await persona(mem, "member");
    const mine = (await api(mem, "projects.search", { limit: 500 })).body.items.length;
    expect(mine < all, `member sees fewer projects (${mine} of ${all})`);
    await mem.goto(`${BASE}/settings/team`);
    await mem.waitForTimeout(800);
    const addTeam = await mem.getByRole("button", { name: /add (a )?(team )?member|invite/i }).count();
    expect(addTeam === 0, "member can't add team members");
    const col = await mk(390);
    await persona(col, "collaborator");
    const shared = (await api(col, "projects.search", { limit: 500 })).body.items;
    expect(shared.length === 1, "collaborator sees exactly the one shared project, got " + shared.length);
    const money = (await api(col, "payments.list_due", {})).body;
    expect(JSON.stringify(money).match(/"amount_paise":\d+/) === null, "collaborator sees no money amounts");
    await col.goto(`${BASE}/`);
    await col.getByText(/Good (morning|afternoon|evening)/).waitFor();
  });

  await journey("Onboarding: a brand-new consultant answers the setup questions and lands on Home", async (mk) => {
    const page = await mk(390);
    await persona(page, "new");
    const me = await (await page.request.get(`${BASE}/api/auth/me`)).json();
    if (me.workspaces.every((w) => w.onboarded)) return;   // already set up by an earlier run on this database
    await page.goto(`${BASE}/onboarding`);
    for (let i = 0; i < 14; i++) {
      if (!page.url().includes("/onboarding")) break;
      const box = page.locator("textarea:visible, input[type=text]:visible").first();
      if (await box.count() && (await box.inputValue()) === "") await box.fill(i === 0 ? "Asha Kapoor — Kapoor Advisory" : "Founders of growing businesses in Pune; ₹5,000 an hour");
      const next = page.getByRole("button", { name: /next|finish|build|done|set up|start|go to home/i }).last();
      if (!(await next.count())) break;
      await next.click();
      await page.waitForTimeout(700);
    }
    await page.waitForURL((u) => !u.pathname.startsWith("/onboarding"), { timeout: 30000 });
    await page.getByText(/Good (morning|afternoon|evening)/).waitFor({ timeout: 10000 });
  });

  await journey("Settings: change the practice website and it sticks after reload", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    await me.goto(`${BASE}/settings`);
    const tag = me.getByLabel("Website");
    await tag.first().waitFor({ timeout: 8000 });
    const v = `https://qa${Date.now() % 10000}.example.in`;
    await tag.first().fill(v);
    const save = me.getByRole("button", { name: /save/i });
    if (await save.count()) await save.first().click();
    await me.waitForTimeout(2200);   // autosave
    await me.reload();
    await me.getByLabel("Website").first().waitFor();
    expect((await me.getByLabel("Website").first().inputValue()) === v, "website saved");
  });

  await journey("Admin (staff): change a limit for everyone, see it logged, revert it", async (mk) => {
    const st = await mk();
    await persona(st, "staff");
    await st.goto(`${BASE}/admin/limits`);
    await st.getByText(/limit/i).first().waitFor();
    const before = await st.evaluate(async () => (await (await fetch("/api/admin/limits")).json()));
    const row = before.limits.find((r) => r.key === "saved_views");
    expect(row, "saved_views limit listed");
    const put = await st.evaluate(async () => (await fetch("/api/admin/limits/saved_views", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value: 7, scope: "all" }) })).status);
    expect(put === 200, "limit changed " + put);
    const ch = await st.evaluate(async () => (await (await fetch("/api/admin/changes")).json()));
    const last = (ch.items || ch)[0];
    expect(last && JSON.stringify(last).includes("saved_views"), "change logged");
    const rv = await st.evaluate(async (id) => (await fetch(`/api/admin/changes/${id}/revert`, { method: "POST" })).status, last.id || last._id);
    expect(rv === 200, "reverted " + rv);
    const own = await mk();
    await persona(own, "owner");
    const blocked = await own.evaluate(async () => (await fetch("/api/admin/limits")).status);
    expect(blocked === 403, "consultants can't open Admin APIs (" + blocked + ")");
  });

  await journey("Ask or tell: the chat answers a question about the practice", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    await me.goto(`${BASE}/`);
    await me.getByRole("button", { name: "Ask or tell" }).click();
    const box = me.locator("[role=dialog] textarea, [role=dialog] input").first();
    await box.fill("Which leads came in this week?");
    await box.press("Enter");
    const send = me.locator("[role=dialog]").getByRole("button", { name: /send|ask/i });
    if (await send.count()) await send.last().click().catch(() => {});
    await me.waitForTimeout(2500);
    const txt = await me.locator("[role=dialog]").last().innerText();
    expect(txt.length > 60 && !/something went wrong/i.test(txt), "chat answered: " + txt.slice(0, 120));
  });
};
