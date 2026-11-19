module.exports = async ({ journey, expect, api, persona, BASE }) => {
  async function freshProposal(me) {
    const t = Date.now();
    const pr = (await api(me, "projects.create", { name: `QA Proposal ${t % 100000}`, contact: { name: "Meera QA", phone: "96" + String(t).slice(-8), email: `meera.${t}@example.in` } })).body;
    const tpl = (await api(me, "templates.list", { kind: "file" })).body.find((x) => x.name === "Proposal — advisory retainer");
    const f = (await api(me, "files.create_from_template", { project_id: pr.id, template_id: tpl.id })).body;
    // Sending is refused until the consultant fills the contract fields.
    const early = await api(me, "files.send", { id: f.id });
    expect(early.status === 400, "send blocked until fields are filled");
    for (const pg of f.pages) for (const b of pg.blocks) if (b.type === "contract") for (const fl of b.fields) fl.value = fl.value || "1 Dec 2026";
    await api(me, "files.update", { id: f.id, pages: f.pages });
    const sent = await api(me, "files.send", { id: f.id, channel: "email" });
    expect(sent.status === 200, "file sent");
    const full = (await api(me, "files.get", { id: f.id })).body;
    return { pr, f: full };
  }

  await journey("Client file on a phone: review, choose package, sign with code, pay, book, done", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const { pr, f } = await freshProposal(me);
    const cl = await mk(390);
    await cl.goto(`${BASE}/c/mehta-growth/f/${f.token}`);
    const log = [];
    for (let step = 0; step < 14; step++) {
      await cl.waitForTimeout(500);
      const sideways = await cl.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      expect(!sideways, `no sideways scroll at step ${step}`);
      const text = await cl.locator("body").innerText();
      if (/all done|you're all set|thank you|completed/i.test(text) && !(await cl.getByRole("button", { name: /next|continue|review/i }).count())) { log.push("done"); break; }
      // Choose a package: tick the first option if nothing is chosen yet.
      const choose = cl.getByRole("button", { name: /^(choose|select|pick)/i });
      if (await choose.count()) { await choose.first().click(); log.push("chose package"); continue; }
      if (/Choose an option/.test(text)) {
        const pkg = cl.getByRole("button", { pressed: false }).filter({ hasText: "₹" });
        await pkg.first().click();
        await cl.getByRole("button", { pressed: true }).filter({ hasText: "₹" }).first().waitFor({ timeout: 5000 });
        log.push("chose package");
        continue;
      }
      const radio = cl.locator("input[type=radio]:visible");
      if (await radio.count() && !(await radio.first().isChecked())) { await radio.first().check(); log.push("picked option"); }
      // Sign: open the sheet, type the name, get a code, enter it.
      const signOpen = cl.getByRole("button", { name: "Sign", exact: true });
      if (await signOpen.count() && !(await cl.locator("[role=dialog]").count())) {
        await signOpen.first().click();
        const sh = cl.getByRole("dialog", { name: "Sign the agreement" });
        await sh.getByLabel("Your full name").fill("Meera QA");
        await sh.getByRole("button", { name: "Send me a code to confirm" }).click();
        await sh.getByLabel("6-digit code").fill("000000");
        await sh.getByRole("button", { name: "Sign", exact: true }).click();
        await sh.waitFor({ state: "detached", timeout: 8000 });
        log.push("signed");
        // The consultant countersigns (the agreement needs both).
        const fs = (await api(me, "files.get", { id: f.id })).body;
        for (const pg of fs.pages) for (const b of pg.blocks) if (b.type === "contract") await api(me, "files.consultant_sign", { id: f.id, block_id: b.id, name: "Priya Mehta" });
        await cl.reload();
        continue;
      }
      // Pay: "I've paid".
      const paid = cl.getByRole("button", { name: "I've paid" });
      if (await paid.count() && await paid.first().isEnabled()) {
        await paid.first().click();
        const sh = cl.locator("[role=dialog]").last();
        await sh.getByPlaceholder(/reference/).fill("UTR-QA-1");
        await sh.getByRole("button", { name: "Confirm I've paid" }).click();
        log.push("claimed payment");
        await cl.waitForTimeout(600);
        continue;
      }
      // Book: pick the first free slot.
      const slot = cl.getByRole("button", { name: /^\d{1,2}:\d{2}\s?(AM|PM)$/i });
      if (await slot.count()) {
        await slot.first().click();
        const book = cl.getByRole("button", { name: /book|confirm/i });
        if (await book.count()) await book.last().click();
        log.push("booked");
        await cl.waitForTimeout(600);
        continue;
      }
      // Otherwise move to the next page.
      const next = cl.getByRole("button", { name: /next|continue|review|finish|done|accept|submit/i });
      if (await next.count() && await next.last().isEnabled()) { await next.last().click(); log.push("next"); continue; }
      log.push("stuck: " + text.replace(/\s+/g, " ").slice(0, 160));
      break;
    }
    console.log("      client steps:", log.join(" → "));
    const st = (await api(me, "files.get", { id: f.id })).body;
    const sigs = st.signatures || [];
    expect(sigs.some((s) => s.otp_verified), "client signature with OTP recorded");
    const inv = (await api(me, "payments.list_due", { project_id: pr.id })).body;
    expect(inv.groups.processing.length >= 1, "client's payment claim is waiting for confirmation");
    expect(!log.some((l) => l.startsWith("stuck")), "client never got stuck: " + log.join(" | "));
  });
};
