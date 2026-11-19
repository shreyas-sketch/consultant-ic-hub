module.exports = async ({ journey, expect, api, persona, BASE }) => {
  for (const [tz, label] of [["Asia/Kolkata", "Mumbai"], ["Asia/Dubai", "Dubai"]]) {
    await journey(`Booking page: a client in ${label} books a discovery call and it lands on the calendar`, async (mk) => {
      const cl = await mk(390, { timezoneId: tz, locale: "en-IN" });
      await cl.goto(`${BASE}/c/mehta-growth/book/discovery-call`);
      await cl.getByRole("heading", { name: "Discovery call" }).waitFor();
      // Pick the third day (avoid "today" edge cases) and its first slot.
      const days = cl.getByRole("button", { name: /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d+ \w+$/ });
      await days.nth(2).click();
      const slot = cl.getByRole("button", { name: /^\d{1,2}:\d{2} (AM|PM)$/ }).first();
      const slotText = await slot.innerText();
      await slot.click();
      const t = Date.now();
      const name = `Booker ${label} ${t % 10000}`;
      const fill = async (re, v) => { const el = cl.getByPlaceholder(re); if (await el.count()) await el.first().fill(v); };
      await fill(/name/i, name);
      await fill(/mail/i, `booker.${t}@example.in`);
      await fill(/mobile|phone/i, "95" + String(t).slice(-8));
      await cl.getByRole("button", { name: /book|confirm/i }).last().click();
      await cl.getByText(/booked|confirmed|see you|you're in/i).first().waitFor({ timeout: 8000 });
      // The consultant sees it, at the same instant.
      const me = await mk();
      await persona(me, "owner");
      const res = (await api(me, "projects.search", { q: name })).body;
      expect(res.items.length === 1, "booking created a project for " + name);
      const from = new Date(Date.now() - 86400e3).toISOString(), to = new Date(Date.now() + 40 * 86400e3).toISOString();
      const cal = (await api(me, "calendar.list", { date_from: from, date_to: to, show: ["sessions"] })).body;
      const mine = cal.find((s) => s.kind === "session" && s.project_id === res.items[0].id);
      expect(mine, "session on the consultant's calendar");
      const shown = new Date(mine.start).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: tz });
      expect(shown.replace(/\s/g, "").toLowerCase() === slotText.replace(/\s/g, "").toLowerCase(), `slot ${slotText} in ${tz} saved as ${mine.start} (${shown})`);
    });
  }

  await journey("Client portal: log in with a code, see projects and invoices, send a message", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const pr = (await api(me, "projects.search", { q: "Farhan" })).body.items[0];
    const contact = pr.contacts[0];
    const cl = await mk(390);
    await cl.goto(`${BASE}/c/mehta-growth/portal`);
    await cl.getByPlaceholder("Mobile number or email").fill(contact.phone || contact.email);
    await cl.getByRole("button", { name: "Send me a code" }).click();
    const code = cl.getByLabel(/code/i).or(cl.getByPlaceholder(/code/i));
    await code.first().fill("000000");
    const go = cl.getByRole("button", { name: /log in|continue|verify|open/i });
    if (await go.count()) await go.last().click();
    await cl.getByText(pr.name).first().waitFor({ timeout: 8000 });
    await cl.getByText(pr.name).first().click();
    await cl.getByText(/INV\/|invoice/i).first().waitFor({ timeout: 8000 });
    await cl.getByRole("button", { name: "Messages" }).click();
    const msg = cl.getByPlaceholder(/message|write/i);
    await msg.first().waitFor({ timeout: 5000 });
    {
      const m = `Portal hello ${Date.now() % 10000}`;
      await msg.first().fill(m);
      await cl.getByRole("button", { name: /send/i }).last().click();
      await cl.waitForTimeout(800);
      const thread = JSON.stringify((await api(me, "threads.get", { project_id: pr.id })).body || "");
      expect(thread.includes(m), "portal message reached the consultant's inbox");
    }
    const sideways = await cl.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    expect(!sideways, "portal has no sideways scroll at 390px");
  });
};
