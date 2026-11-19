const { execSync } = require("child_process");
// Talks to the QA server's MongoDB (the server must run with QA_DB=mongo).
const CONTAINER = process.env.E2E_MONGO_CONTAINER || "qa-mongo";
const DB = process.env.E2E_DB || "pos_e2e";
const mongo = (js) => execSync(`docker exec ${CONTAINER} mongosh ${DB} --quiet --eval '${js.replace(/'/g, "'\\''")}'`).toString().trim();

const EVIL = `<p>Hello <b>bold</b> <a href="https://example.com">link</a></p>`
  + `<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script>`
  + `<a href="javascript:window.__pwned=3">click</a><iframe src="https://example.com"></iframe>`;

module.exports = async ({ journey, expect, api, persona, BASE }) => {
  await journey("Security: hostile HTML in an AI draft never runs in the consultant's Approvals screen", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const ws = mongo(`print(db.workspaces.findOne({slug:"mehta-growth"})._id)`);
    const pr = (await api(me, "projects.search", { q: "Farhan" })).body.items[0];
    const id = "qa-evil-" + Date.now();
    mongo(`db.approvals.insertOne({_id:"${id}",workspace_id:"${ws}",project_id:"${pr.id}",status:"pending",action:"messages.send",
      args:{},actor:"agent:lead",idempotency_key:"${id}",preview:{subject:"QA hostile draft",body:${JSON.stringify(EVIL)}},
      created_at:new Date(),updated_at:new Date(),deleted_at:null,expires_at:new Date(Date.now()+864e5)})`);
    await me.goto(`${BASE}/approvals`);
    await me.getByText("QA hostile draft").first().waitFor({ timeout: 8000 });
    await me.waitForTimeout(800);
    expect(!(await me.evaluate(() => window.__pwned)), "no script ran");
    const body = me.locator(".prose-dark").filter({ hasText: "Hello" }).first();
    expect(await body.locator("b").count() === 1, "bold kept");
    expect((await body.locator("a").first().getAttribute("rel")) === "noopener noreferrer", "links made safe");
    expect(await body.locator("script, iframe, img[onerror]").count() === 0, "dangerous tags removed");
    const jsLinks = await body.locator("a").evaluateAll((as) => as.filter((a) => /^javascript:/i.test(a.getAttribute("href") || "")).length);
    expect(jsLinks === 0, "javascript: links removed");
    await api(me, "approvals.skip", { id });
  });

  await journey("Security: hostile HTML in a message never runs in the client portal", async (mk) => {
    const me = await mk();
    await persona(me, "owner");
    const pr = (await api(me, "projects.search", { q: "Neel" })).body.items[0];
    const ws = mongo(`print(db.workspaces.findOne({slug:"mehta-growth"})._id)`);
    const th = mongo(`var t=db.threads.findOne({project_id:"${pr.id}"}); print(t?t._id:"")`);
    mongo(`db.messages.insertOne({_id:"qa-evil-msg-${Date.now()}",workspace_id:"${ws}",thread_id:"${th}",project_id:"${pr.id}",channel:"email",direction:"out",
      subject:"QA hostile message",body_html:${JSON.stringify(EVIL)},body_text:"",status:"sent",created_at:new Date(),updated_at:new Date(),deleted_at:null})`);
    const cl = await mk(390);
    await cl.goto(`${BASE}/c/mehta-growth/portal`);
    await cl.getByPlaceholder("Mobile number or email").fill(pr.contacts[0].phone);
    await cl.getByRole("button", { name: "Send me a code" }).click();
    await cl.getByLabel(/code/i).or(cl.getByPlaceholder(/code/i)).first().fill("000000");
    const go = cl.getByRole("button", { name: /log in|continue|verify|open/i });
    if (await go.count()) await go.last().click();
    await cl.getByText(pr.name).first().click();
    await cl.getByRole("button", { name: "Messages" }).click();
    await cl.getByText("QA hostile message").first().waitFor({ timeout: 8000 });
    await cl.waitForTimeout(800);
    expect(!(await cl.evaluate(() => window.__pwned)), "no script ran in the portal");
  });
};
