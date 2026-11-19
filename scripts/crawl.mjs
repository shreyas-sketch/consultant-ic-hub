// Final crawl: every screen at 390px and 1280px. Fails on 5xx, page errors,
// sideways scroll at 390px, "NaN"/"undefined" on screen, or raw ISO dates.
// Usage: node scripts/crawl.mjs [base] [outdir]
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";
import fs from "fs";

const BASE = process.argv[2] || "http://localhost:8765";
const OUT = process.argv[3] || "qa/shots";
fs.mkdirSync(OUT, { recursive: true });
const problems = [];

async function api(page, name, body = {}) {
  return page.evaluate(async ([n, b]) => (await fetch(`/api/a/${n}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })).json(), [name, body]);
}

async function check(page, label, width) {
  await page.waitForTimeout(700);
  const r = await page.evaluate(() => {
    const text = document.body.innerText;
    return {
      sideways: document.documentElement.scrollWidth > window.innerWidth + 1,
      bad: (text.match(/\bNaN\b|\bundefined\b|\[object Object\]/g) || []).slice(0, 3),
      iso: (text.match(/\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/g) || []).slice(0, 2),
    };
  });
  if (width === 390 && r.sideways) problems.push(`${label} @390: sideways scroll`);
  if (r.bad.length) problems.push(`${label} @${width}: shows ${r.bad.join(", ")}`);
  if (r.iso.length) problems.push(`${label} @${width}: raw date ${r.iso[0]}`);
}

async function visit(ctx, path, label, { shot = true, widths = [390, 1280], action } = {}) {
  for (const w of widths) {
    const page = await ctx.newPage();
    await page.setViewportSize({ width: w, height: w === 390 ? 844 : 900 });
    page.on("pageerror", (e) => problems.push(`${label} @${w}: page error ${e.message.slice(0, 160)}`));
    page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push(`${label} @${w}: console ${m.text().slice(0, 160)}`); });
    page.on("response", (r) => { if (r.status() >= 500) problems.push(`${label} @${w}: ${r.status()} ${r.url()}`); });
    await page.goto(BASE + path, { waitUntil: "networkidle" }).catch((e) => problems.push(`${label}: ${e.message}`));
    if (action) await action(page).catch((e) => problems.push(`${label} action: ${e.message.slice(0, 160)}`));
    await check(page, label, w);
    if (shot) await page.screenshot({ path: `${OUT}/${label}-${w}.png`, fullPage: w === 1280 ? false : false });
    await page.close();
  }
}

async function as(browser, persona) {
  const ctx = await browser.newContext({ deviceScaleFactor: 1 });
  const p = await ctx.newPage();
  await p.goto(BASE + "/login");
  await p.evaluate(async (persona) => fetch("/api/qa/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona }) }), persona);
  return { ctx, p };
}

const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", args: ["--no-sandbox"] });
try {
  const anon = await browser.newContext();
  await visit(anon, "/login", "login");

  const { ctx, p } = await as(browser, "owner");
  const projects = (await api(p, "projects.search", {})).items;
  const vikram = projects.find((x) => x.name.includes("Vikram"));
  const farhan = projects.find((x) => x.name.includes("Farhan"));
  const files = await api(p, "files.list", {});
  const vfile = files.find((f) => f.project_id === vikram.id && f.kind !== "quote");
  const qfile = files.find((f) => f.kind === "quote");
  const iyer = projects.find((x) => x.name.includes("Meera"));
  const rets = await api(p, "retainers.list", {});
  const ests = await api(p, "estimates.list", {});
  const ctasks = await api(p, "client_tasks.list", { status: "open" });
  const autos = await api(p, "automations.list", {});
  const forms = await api(p, "lead_forms.list", {});
  const invs = await api(p, "invoices.list", {});
  const farhanInv = invs.find((i) => i.project_id === farhan.id);
  const contacts = (await api(p, "contacts.search", {})).items;

  for (const [path, label] of [["/", "home"], ["/projects", "projects"], [`/projects/${vikram.id}`, "project"], [`/projects/${farhan.id}?tab=payments`, "project-payments"],
    [`/projects/${vikram.id}?tab=details`, "project-details"], ["/contacts", "contacts"], [`/contacts/${contacts[0].id}`, "contact"], ["/inbox", "inbox"], [`/inbox/${vikram.id}`, "inbox-thread"],
    ["/calendar", "calendar"], ["/files", "files"], [`/files/${vfile.id}`, "builder"], ["/automations", "automations"], [`/automations/${autos[0].id}`, "automation-flow"],
    ["/payments", "payments"], ["/reports", "reports"], ["/agents", "agents"], ["/approvals", "approvals"], ["/tasks", "tasks"], ["/settings", "settings"],
    ["/settings/branding", "settings-branding"], ["/settings/invoice", "settings-invoice"], ["/settings/team", "settings-team"], ["/settings/forms", "settings-forms"],
    ["/settings/connector", "settings-connector"],
    ["/time", "time"], ["/time?tab=list", "time-entries"], ["/time?tab=unbilled", "time-unbilled"], ["/retainers", "retainers"], [`/retainers/${rets[0].id}`, "retainer"],
    ["/estimates", "estimates"], [`/estimates/${ests[0].id}`, "estimate"], [`/estimates/${ests[ests.length - 1].id}`, "estimate-2"], ["/settings/rates", "settings-rates"],
    ["/settings/checklists", "settings-checklists"], ["/settings/pipeline", "settings-pipeline"], [`/projects/${iyer.id}?tab=budget`, "project-budget"],
    [`/projects/${farhan.id}?tab=time`, "project-time"], [`/projects/${iyer.id}?tab=tasks`, "project-tasks"], ["/tasks?view=client", "tasks-client"]]) {
    await visit(ctx, path, label);
  }
  for (const [tab, label] of [["Forecast", "reports-forecast"], ["Profit", "reports-profit"], ["Utilisation", "reports-util"]]) {
    await visit(ctx, "/reports", label, { action: async (pg) => { await pg.getByRole("button", { name: tab, exact: true }).first().click(); await pg.waitForTimeout(700); } });
  }
  const reg = await p.evaluate(async () => (await fetch("/oauth/register", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_name: "Claude", redirect_uris: ["http://localhost:3999/cb"] }) })).json());
  await visit(ctx, `/oauth/authorize?response_type=code&client_id=${reg.client_id}&redirect_uri=${encodeURIComponent("http://localhost:3999/cb")}&code_challenge=abc&code_challenge_method=S256&scope=full&state=s`, "oauth-consent", { widths: [390] });
  await visit(ctx, "/projects", "projects-table", { action: async (pg) => { await pg.getByText("Table").first().click(); await pg.waitForTimeout(400); } });
  await visit(ctx, "/", "chat", { widths: [1280], action: async (pg) => { await pg.getByText("Ask or tell").first().click(); await pg.getByText("Which leads came in this week?").click(); await pg.waitForTimeout(1500); } });

  // Client pages
  const slug = "mehta-growth";
  const cctx = await browser.newContext();
  await visit(cctx, `/c/${slug}/f/${vfile.token}`, "client-file");
  await visit(cctx, `/c/${slug}/f/${vfile.token}`, "client-file-choose", { action: async (pg) => {
    // The file resumes where the client left off, so the second width may already be on step 2.
    const b = pg.getByRole("button", { name: /Review your options/ });
    if (await b.count()) { await b.click(); await pg.waitForTimeout(500); }
  } });
  await visit(cctx, `/c/${slug}/i/${farhanInv.token}`, "client-invoice");
  await visit(cctx, `/c/${slug}/book/discovery-call`, "client-booking");
  await visit(cctx, `/c/${slug}/form/${forms[0].slug}`, "client-form");
  await visit(cctx, `/c/${slug}/portal`, "client-portal-login");
  await visit(cctx, `/c/${slug}/f/${qfile.token}`, "client-quote");
  await visit(cctx, `/c/${slug}/t/${ctasks[0].token}`, "client-task");
  const pctx = await browser.newContext();
  const pp = await pctx.newPage();
  await pp.goto(BASE + `/c/${slug}/portal`);
  await pp.evaluate(async (slug) => { await fetch(`/api/public/${slug}/portal/code`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: "9833088899" }) });
    await fetch(`/api/public/${slug}/portal/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: "9833088899", code: "000000" }) }); }, slug);
  await pp.close();
  await visit(pctx, `/c/${slug}/portal`, "client-portal-plan", { action: async (pg) => {
    const card = pg.getByText("Neel Shah").first(); if (await card.count()) { await card.click(); await pg.waitForTimeout(500); }
    const tab = pg.getByRole("button", { name: "Your plan" }); if (await tab.count()) { await tab.click(); await pg.waitForTimeout(400); } } });
  await visit(ctx, `/c/${slug}/preview/${vfile.id}`, "client-preview", { widths: [390] });

  // Roles
  for (const persona of ["member", "collaborator"]) {
    const r = await as(browser, persona);
    await visit(r.ctx, "/", `home-${persona}`, { widths: [390] });
    await visit(r.ctx, "/projects", `projects-${persona}`, { widths: [1280] });
  }
  const n = await as(browser, "new");
  await visit(n.ctx, "/onboarding", "onboarding");
  const st = await as(browser, "staff");
  for (const [path, label] of [["/admin", "admin"], ["/admin/invites", "admin-invites"], ["/admin/limits", "admin-limits"], ["/admin/workspaces", "admin-accounts"],
    ["/admin/usage", "admin-usage"], ["/admin/ai", "admin-ai"], ["/admin/funnel", "admin-funnel"], ["/admin/jobs", "admin-jobs"]]) {
    await visit(st.ctx, path, label, { widths: [1280] });
  }
} finally {
  await browser.close();
}
fs.writeFileSync(`${OUT}/../crawl-report.txt`, problems.length ? problems.join("\n") : "Clean: no problems found.");
console.log(problems.length ? `${problems.length} problems:\n` + [...new Set(problems)].join("\n") : "Clean: no problems found.");
