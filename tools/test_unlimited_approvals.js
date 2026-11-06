/* Approval selection across pages and filters. Loopback fixtures only; no real approval or sending. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs"), path = require("node:path"), os = require("node:os"), http = require("node:http");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"));
const dir = path.resolve(__dirname, "../app/static");
const source = fs.readFileSync(path.join(dir, "app.js"), "utf8");
const marker = "(async function init() {";
assert.equal(source.split(marker).length, 2);
const script = source.slice(0, source.indexOf(marker));
const html = fs.readFileSync(path.join(dir, "index.html"), "utf8").replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g, "");
let rows = Array.from({ length: 451 }, (_, i) => ({ id: `draft-${i}`, entity_id: `lead-${i}`, company: `Fixture ${i}`, domain: `company-${i}.example`, contact_name: "Fixture Contact", contact_email: `contact-${i}@company.example`, recipient_contact_id: `contact-${i}`, subject: `Fixture subject ${i}`, body: `Hello Fixture,\n\nFixture email ${i}.`, direction: "outbound", status: "drafted", category: i < 321 ? "science" : "other", created_at: "2026-11-06T00:00:00Z", attachments: [] }));
const errors = [], external = [], writes = [];
async function main() {
  const server = http.createServer((req, res) => {
    const p = new URL(req.url, "http://127.0.0.1").pathname;
    const file = { "/": [html, "text/html"], "/app.js": [script, "application/javascript"], "/style.css": [fs.readFileSync(path.join(dir, "style.css")), "text/css"] }[p];
    res.writeHead(file ? 200 : 404, { "Content-Type": file ? file[1] : "text/plain" }); res.end(file ? file[0] : "Fixture only");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean).find((p) => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1550, height: 1000 } });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(), u = new URL(req.url());
      if (u.origin !== base) { external.push(req.url()); return route.abort(); }
      if (!u.pathname.startsWith("/api/")) return route.continue();
      let d;
      if (req.method() === "GET" && u.pathname === "/api/outreach") {
        const matching = rows.filter((r) => !u.searchParams.get("category") || r.category === u.searchParams.get("category"));
        const start = +(u.searchParams.get("offset") || 0), limit = +(u.searchParams.get("limit") || 200);
        d = { rows: matching.slice(start, start + limit), total: matching.length, counts: { drafts: rows.length }, filtered_counts: { drafts: matching.length }, categories: [{ key: "science", n: 321 }, { key: "other", n: 130 }], services: [] };
      } else if (req.method() === "GET" && u.pathname === "/api/mailboxes") d = { mode: "approver", accounts: [], can_send: false, paused: null, resets_at: "2026-11-07T00:00:00Z" };
      else if (req.method() === "POST" && u.pathname === "/api/outreach/batch/sample") {
        const b = req.postDataJSON(); writes.push({ path: u.pathname, body: b });
        assert.equal(b.ids.length, 321); assert.equal(Object.keys(b.expected_recipients).length, 321);
        assert(b.ids.every((id) => rows.find((r) => r.id === id)?.category === "science"));
        d = { approvable: b.ids, skipped: [], sample: [b.ids[0], b.ids.at(-1)], token: "fixture-token", generated: false };
      } else if (req.method() === "POST" && u.pathname === "/api/outreach/batch/approve") {
        const b = req.postDataJSON(); writes.push({ path: u.pathname, body: b });
        assert.equal(b.ids.length, 321); assert.equal(Object.keys(b.expected_recipients).length, 321);
        rows = rows.filter((r) => !b.ids.includes(r.id)); d = { approved: 321, skipped: [], windows: [], can_send: false, paused: null };
      } else { errors.push(`${req.method()} ${u.pathname}`); d = { detail: "Unexpected fixture endpoint" }; }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(d) });
    });
    await page.goto(base);
    await page.evaluate(async () => {
      state.segment = { slug: "fixture-project", ui: {}, outreach_policy: { drafts: true, batch_approval: { sample_min: 1, sample_fraction: 0.01, max_batch: 50 } } };
      state.route = "outreach";
      document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-outreach"));
      state.outreach.category = "science"; state.outreach.limit = 50;
      bindOps(); await loadOutreach();
    });
    await page.locator("#outreachSelAll").check();
    assert.equal(await page.evaluate(() => state.outreach.selected.size), 50);
    await page.locator('#outreachPager [data-page="next"]').click();
    await page.waitForFunction(() => state.outreach.rows[0]?.id === "draft-50");
    assert.equal(await page.evaluate(() => state.outreach.selected.size), 50, "selection persists across pages");
    await page.locator("#outreachSelAll").check();
    assert.equal(await page.evaluate(() => state.outreach.selected.size), 100, "old 50-item limit is absent");
    await page.locator("#batchSelectAll").click();
    await page.waitForFunction(() => state.outreach.selected.size === 321 && !state.outreach.selectingAll);
    assert.match(await page.locator("#batchGo").innerText(), /321/);
    await page.locator("#batchBar").screenshot({ path: path.resolve(__dirname, "../logs/unlimited-approvals-bar.png") });
    await page.locator("#outreachCategory").selectOption("other");
    await page.waitForFunction(() => state.outreach.rows[0]?.id === "draft-321");
    assert.equal(await page.evaluate(() => state.outreach.selected.size), 0, "filter changes clear selection");
    await page.locator("#outreachCategory").selectOption("science");
    await page.waitForFunction(() => state.outreach.rows[0]?.id === "draft-0");
    await page.locator("#batchSelectAll").click();
    await page.waitForFunction(() => state.outreach.selected.size === 321 && !state.outreach.selectingAll);
    await page.locator("#batchGo").click();
    await page.waitForSelector("#batchApprove");
    assert.match(await page.locator("#modalRoot").innerText(), /Fixture 320/, "off-page sample has its company and full email");
    assert.equal(await page.locator("#batchApprove").isDisabled(), true);
    for (const btn of await page.locator("[data-read]").all()) await btn.click();
    for (const check of await page.locator("[data-ok]").all()) await check.check();
    await page.locator("#batchApprove").click();
    await page.waitForFunction(() => !document.querySelector("#batchApprove") && state.outreach.selected.size === 0);
    assert.equal(writes.length, 2, "only sample and explicit batch approval requests");
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    console.log("Unlimited approval UI passed: 100 selected across 50-row pages, 321 matching drafts selected, filters respected, off-page review and recipient guards retained. No real emails sent.");
  } finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
