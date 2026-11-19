// node explore.cjs <persona|-> <path> [width]  -> prints buttons, links, inputs, headings
const { chromium } = require("playwright");
(async () => {
  const [persona, path, width] = process.argv.slice(2);
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: +(width || 1280), height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  page.on("response", (r) => { if (r.status() >= 500) errs.push(r.status() + " " + r.url()); });
  if (persona !== "-") {
    await page.goto("http://localhost:8765/login");
    await page.evaluate(async (p) => fetch("/api/qa/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona: p }) }), persona);
  }
  await page.goto("http://localhost:8765" + path, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  const info = await page.evaluate(() => {
    const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const t = (e) => (e.innerText || e.value || e.placeholder || e.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 50);
    return {
      h: [...document.querySelectorAll("h1,h2,h3")].filter(vis).map(t).slice(0, 15),
      buttons: [...document.querySelectorAll("button,[role=tab]")].filter(vis).map(t).filter(Boolean).slice(0, 60),
      inputs: [...document.querySelectorAll("input,textarea,select")].filter(vis).map((e) => `${e.tagName.toLowerCase()}[${e.type || ""}] ${e.placeholder || e.name || e.getAttribute("aria-label") || ""}`).slice(0, 30),
      links: [...document.querySelectorAll("a")].filter(vis).map((a) => t(a) + " -> " + a.getAttribute("href")).slice(0, 40),
    };
  });
  console.log(JSON.stringify(info, null, 1));
  if (errs.length) console.log("ERRORS", errs);
  await b.close();
})();
