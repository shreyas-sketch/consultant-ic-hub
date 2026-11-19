// node peek.cjs <persona|-> <path> <width> <click text>[ >> <click text> ...]  -> dumps the last dialog (or page) after clicks
const { chromium } = require("playwright");
(async () => {
  const [persona, path, width, ...rest] = process.argv.slice(2);
  const clicks = rest.join(" ").split(">>").map((s) => s.trim()).filter(Boolean);
  const b = await chromium.launch();
  const page = await (await b.newContext({ viewport: { width: +width, height: 900 } })).newPage();
  const errs = []; page.on("pageerror", (e) => errs.push(e.message)); page.on("response", (r) => r.status() >= 500 && errs.push(r.status() + " " + r.url()));
  if (persona !== "-") { await page.goto("http://localhost:8765/login"); await page.evaluate(async (p) => fetch("/api/qa/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona: p }) }), persona); }
  await page.goto("http://localhost:8765" + path, { waitUntil: "networkidle" });
  for (const c of clicks) { await page.getByRole("button", { name: c, exact: false }).first().click(); await page.waitForTimeout(600); }
  const root = (await page.locator("[role=dialog]").count()) ? page.locator("[role=dialog]").last() : page.locator("main, body").first();
  const out = await root.evaluate((el) => {
    const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const t = (e) => (e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 60);
    return { text: t(el).slice(0, 500), buttons: [...el.querySelectorAll("button,[role=tab]")].filter(vis).map((e) => t(e) || e.getAttribute("aria-label")).slice(0, 40),
             inputs: [...el.querySelectorAll("input,textarea,select")].filter(vis).map((e) => `${e.tagName.toLowerCase()}[${e.type}] ph=${e.placeholder || ""} aria=${e.getAttribute("aria-label") || ""} opts=${e.tagName === "SELECT" ? [...e.options].map((o) => o.text).slice(0, 6).join("|") : ""}`) };
  });
  console.log(JSON.stringify(out, null, 1)); if (errs.length) console.log("ERRORS", errs);
  await b.close();
})();
