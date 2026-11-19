module.exports = async ({ journey, expect, api, get, persona, BASE }) => {
  await journey("Money: request a payment, client says paid on a phone, consultant confirms, receipt", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const pr = (await api(me, "projects.create", { name: `QA Money ${Date.now() % 100000}`, contact: { name: "Asha Rao", email: `asha.${Date.now()}@example.in`, phone: "98" + String(Date.now()).slice(-8) } })).body;
    expect(pr && pr.id, "project created");
    await me.goto(`${BASE}/projects/${pr.id}?tab=payments`);
    await me.getByRole("button", { name: "Request a payment" }).click();
    const d = me.locator("[role=dialog]").last();
    await d.getByLabel(/Amount/).fill("12345.50");
    await d.getByLabel(/What it's for/).fill("QA milestone");
    await d.getByRole("button", { name: "Send pay link" }).click();
    await d.waitFor({ state: "detached", timeout: 8000 });
    await me.getByText("QA milestone").first().waitFor({ timeout: 8000 });

    const due = (await api(me, "payments.list_due", { project_id: pr.id })).body;
    const item = [...due.groups.upcoming, ...due.groups.overdue].find((i) => i.label === "QA milestone");
    expect(item && item.amount_paise === 1234550, "₹12,345.50 stored as 1234550 paise, got " + JSON.stringify(item));
    const inv = (await api(me, "invoices.get", { id: item.invoice_id })).body;
    expect(inv.number && /\/\d{4}$/.test(inv.number), "invoice got a number when sent");

    // The client, on a phone, opens the link from WhatsApp.
    const cl = await mk(390);
    await cl.goto(`${BASE}/c/mehta-growth/i/${inv.token}`);
    await cl.getByText("₹12,345.50").first().waitFor({ timeout: 8000 });
    const sideways = await cl.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    expect(!sideways, "no sideways scroll on the invoice page at 390px");
    await cl.getByRole("button", { name: "I've paid" }).click();
    const sh = cl.locator("[role=dialog]").last();
    await sh.getByPlaceholder(/reference/).fill("UTR998877");
    await sh.getByRole("button", { name: "Confirm I've paid" }).click();
    await cl.getByText(/confirm|thank|received|processing|checking/i).first().waitFor({ timeout: 8000 });

    // Not paid until the consultant confirms.
    let st = (await api(me, "invoices.get", { id: inv.id })).body;
    expect(st.status !== "paid" && st.claims.length === 1, "claim recorded, not paid yet");
    await me.goto(`${BASE}/projects/${pr.id}?tab=payments`);
    const confirm = me.getByRole("button", { name: "Mark as paid" }).first();
    await confirm.waitFor({ timeout: 8000 });
    await confirm.click();
    const cd = me.locator("[role=dialog]");
    if (await cd.count()) await cd.last().getByRole("button", { name: /confirm|mark|yes|save/i }).last().click();
    for (let i = 0; i < 20 && st.status !== "paid"; i++) { await me.waitForTimeout(300); st = (await api(me, "invoices.get", { id: inv.id })).body; }
    expect(st.status === "paid", "invoice paid after confirm, is " + st.status);

    // Client sees it paid and can download the receipt PDF.
    await cl.reload();
    await cl.getByText(/paid/i).first().waitFor({ timeout: 8000 });
    const rec = await cl.evaluate(async ([t, it]) => { const r = await fetch(`/api/public/i/${t}/receipt/${it}.pdf`); return [r.status, r.headers.get("content-type"), (await r.arrayBuffer()).byteLength]; }, [inv.token, item.item_id]);
    expect(rec[0] === 200 && rec[1] === "application/pdf" && rec[2] > 1000, "receipt PDF " + rec);
    const pdf = await cl.evaluate(async (t) => { const r = await fetch(`/api/public/i/${t}/invoice.pdf`); return [r.status, (await r.arrayBuffer()).byteLength]; }, inv.token);
    expect(pdf[0] === 200 && pdf[1] > 1000, "invoice PDF " + pdf);
  });

  await journey("Money: invoice numbering, credit note and the paid-invoice lock via the API the screens use", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const pr = (await api(me, "projects.create", { name: "QA Credit", contact: { name: "Kiran", email: `k.${Date.now()}@example.in` } })).body;
    const inv = (await api(me, "invoices.create", { project_id: pr.id, lines: [{ name: "Audit", qty: 1, price_paise: 5000000 }] })).body;
    const sent = (await api(me, "invoices.send", { id: inv.id })).body;
    const full = (await api(me, "invoices.get", { id: inv.id })).body;
    await api(me, "payments.confirm", { invoice_id: inv.id, item_id: full.schedule[0].id });
    const edit = await api(me, "invoices.update", { id: inv.id, lines: [{ name: "Audit", qty: 1, price_paise: 1 }] });
    expect(edit.status >= 400 && edit.status < 500, "paid invoice can't be edited (" + edit.status + ")");
    const cn = await api(me, "invoices.credit_note", { id: inv.id, amount_paise: 100000, reason: "Goodwill" });
    expect(cn.status === 200 && /^CN\//.test(cn.body.number || ""), "credit note numbered " + JSON.stringify(cn.body).slice(0, 120));
    expect(/^INV\/\d{4}-\d{2}\/\d{4}$/.test(sent.number), "invoice number format " + sent.number);
  });
};
