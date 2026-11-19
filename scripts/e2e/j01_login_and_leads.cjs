module.exports = async ({ journey, expect, api, persona, BASE }) => {
  await journey("Login with a WhatsApp code through the real form", async (mk) => {
    const page = await mk(390);
    await page.goto(BASE + "/login");
    await page.getByPlaceholder("Mobile number").fill("9000000001");
    await page.getByRole("button", { name: "Send code on WhatsApp" }).click();
    await page.getByText(/Enter the 6-digit code/).waitFor({ timeout: 5000 });
    await page.locator("input").first().fill("000000");
    // The form submits by itself on the 6th digit; click only if it is still there.
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 3000 }).catch(async () => {
      await page.getByRole("button", { name: "Log in" }).click();
    });
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 8000 });
    await page.getByText(/Good (morning|afternoon|evening)/).waitFor({ timeout: 8000 });
  });

  await journey("Uninvited number sees one plain line", async (mk) => {
    const page = await mk(390);
    await page.goto(BASE + "/login");
    await page.getByPlaceholder("Mobile number").fill("9111111111");
    await page.getByRole("button", { name: "Send code on WhatsApp" }).click();
    await page.getByText("This product is by invitation right now.").waitFor({ timeout: 5000 });
  });

  await journey("Deep link while logged out returns there after login", async (mk) => {
    const page = await mk();
    await page.goto(BASE + "/payments");
    await page.waitForURL(/\/login\?next=/, { timeout: 8000 });
    await page.getByPlaceholder("Mobile number").fill("9000000002");
    await page.getByRole("button", { name: "Send code on WhatsApp" }).click();
    await page.getByText(/Enter the 6-digit code/).waitFor({ timeout: 5000 });
    await page.locator("input").first().fill("000000");
    // The form submits by itself on the 6th digit; click only if it is still there.
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 3000 }).catch(async () => {
      await page.getByRole("button", { name: "Log in" }).click();
    });
    await page.waitForURL(/\/payments/, { timeout: 8000 });
  });

  await journey("New lead from the Projects screen lands in the pipeline", async (mk) => {
    const page = await mk();
    await persona(page, "owner");
    await page.goto(BASE + "/projects");
    await page.getByRole("button", { name: "New lead" }).click();
    const sheet = page.locator("[role=dialog]").last();
    await sheet.waitFor();
    const name = `QA Lead ${Date.now() % 100000}`;
    await sheet.getByLabel("Name").fill(name);
    await sheet.getByLabel("Mobile").fill("97" + String(Date.now()).slice(-8));
    await sheet.getByLabel("Email").fill(`qa.lead.${Date.now()}@example.in`);
    await sheet.getByRole("button", { name: "Add lead" }).click();
    await page.waitForURL(/\/projects\/\w+/, { timeout: 8000 });
    await page.getByRole("heading", { name: new RegExp(name) }).waitFor({ timeout: 8000 });
    const r = await api(page, "projects.search", { q: name });
    expect(r.status === 200 && JSON.stringify(r.body).includes(name), "lead is searchable");
  });

  await journey("Public lead form: a client enquires and it becomes a project", async (mk) => {
    const admin = await mk();
    await persona(admin, "owner");
    const forms = await api(admin, "lead_forms.list");
    const live = (forms.body || []).find((f) => f.live) || (forms.body || [])[0];
    expect(live, "a lead form exists");
    const client = await mk(390);
    await client.goto(`${BASE}/c/mehta-growth/form/${live.slug}`);
    await client.getByRole("button").first().waitFor();
    const nm = `Form Client ${Date.now() % 100000}`;
    const inputs = client.locator("input:visible, textarea:visible");
    const n = await inputs.count();
    for (let i = 0; i < n; i++) {
      const el = inputs.nth(i);
      const t = (await el.getAttribute("type")) || "text";
      const hint = ((await el.getAttribute("placeholder")) || (await el.getAttribute("name")) || "").toLowerCase();
      if (t === "checkbox" || t === "radio" || t === "hidden" || (await el.getAttribute("name")) === "website") continue;
      if (/mail/.test(hint)) await el.fill(`form.client.${Date.now()}@example.in`);
      else if (/phone|mobile/.test(hint)) await el.fill("98" + String(Date.now()).slice(-8));
      else if (i === 0 || /name/.test(hint)) await el.fill(nm);
      else await el.fill("We need help with pricing.");
    }
    // radios / choices: pick the first option of each group if any are required
    const radios = client.locator("input[type=radio]:visible");
    if (await radios.count()) await radios.first().check().catch(() => {});
    await client.getByRole("button", { name: /send|submit|next|continue/i }).last().click();
    for (let k = 0; k < 4; k++) {
      if (await client.getByText(/thank|received|we'll|got it|book a call/i).count()) break;
      const more = client.getByRole("button", { name: /send|submit|next|continue/i });
      if (await more.count()) await more.last().click().catch(() => {});
      await client.waitForTimeout(600);
    }
    await client.getByText(/thank|received|we'll|got it|book/i).first().waitFor({ timeout: 8000 });
    const r = await api(admin, "projects.search", { q: nm });
    expect(JSON.stringify(r.body).includes(nm), "submitted lead appears for the consultant");
  });
};
