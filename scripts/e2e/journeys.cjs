// End-to-end journeys through the real UI. node journeys.cjs [filter]
const { chromium } = require("playwright");
const fs = require("fs");
const BASE = process.env.BASE || "http://localhost:8765";
const OUT = process.env.E2E_SHOTS || require("path").join(__dirname, "shots");
fs.mkdirSync(OUT, { recursive: true });

const results = [];
let browser;

async function newPage(width = 1280, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width, height: width < 500 ? 844 : 900 }, ...opts });
  const page = await ctx.newPage();
  page._problems = [];
  page.on("pageerror", (e) => page._problems.push("pageerror: " + e.message.slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) page._problems.push("console: " + m.text().slice(0, 200)); });
  page.on("response", (r) => { if (r.status() >= 500) page._problems.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  return page;
}

async function persona(page, p) {
  await page.goto(BASE + "/login");
  const r = await page.evaluate(async (p) => (await fetch("/api/qa/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona: p }) })).status, p);
  if (r !== 200) throw new Error("persona login failed " + p);
}

async function api(page, name, body = {}) {
  return page.evaluate(async ([n, b]) => {
    const r = await fetch(`/api/a/${n}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, [name, body]);
}

async function get(page, url) {
  return page.evaluate(async (u) => { const r = await fetch(u); return { status: r.status, body: await r.json().catch(() => null) }; }, url);
}

const toast = (page) => page.locator("[role=status], .toast").last();

async function journey(name, fn) {
  if (process.argv[2] && !name.toLowerCase().includes(process.argv[2].toLowerCase())) return;
  const pages = [];
  const mk = async (...a) => { const p = await newPage(...a); pages.push(p); return p; };
  const t0 = Date.now();
  try {
    await fn(mk);
    const problems = pages.flatMap((p) => p._problems);
    results.push({ name, ok: problems.length === 0, problems, ms: Date.now() - t0 });
  } catch (e) {
    const shot = `${OUT}/${name.replace(/\W+/g, "-")}.png`;
    if (pages.length) await pages[pages.length - 1].screenshot({ path: shot, fullPage: false }).catch(() => {});
    results.push({ name, ok: false, error: e.message.split("\n")[0].slice(0, 300), problems: pages.flatMap((p) => p._problems), shot, ms: Date.now() - t0 });
  }
  for (const p of pages) await p.context().close().catch(() => {});
}

function expect(cond, msg) { if (!cond) throw new Error("expected: " + msg); }

module.exports = { journey, expect, api, get, persona, toast, BASE, results, setBrowser: (b) => (browser = b) };

if (require.main === module) {
  (async () => {
    browser = await chromium.launch();
    for (const f of fs.readdirSync(__dirname).filter((f) => /^j\d+.*\.cjs$/.test(f)).sort()) {
      await require("./" + f)(module.exports);
    }
    await browser.close();
    let bad = 0;
    for (const r of results) {
      console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}  (${r.ms} ms)`);
      if (!r.ok) {
        bad++;
        if (r.error) console.log("      error:", r.error);
        for (const p of r.problems.slice(0, 6)) console.log("      ", p);
        if (r.shot) console.log("      shot:", r.shot);
      }
    }
    console.log(`\n${results.length - bad}/${results.length} journeys passed`);
    process.exit(bad ? 1 : 0);
  })();
}
