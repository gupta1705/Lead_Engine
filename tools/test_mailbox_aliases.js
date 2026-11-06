/* Real mailbox UI against loopback fixtures only. No Google login or email sends. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const modulePath = process.env.PLAYWRIGHT_MODULE || path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const { chromium } = require(modulePath);
const staticDir = path.resolve(__dirname, "../app/static");
const source = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const marker = "(async function init() {";
assert.equal(source.split(marker).length, 2);
const appSource = source.slice(0, source.indexOf(marker));
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8").replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g, "");
const ID = "10000000-0000-4000-8000-000000000001";
const PARENT = "fixture@tvf.example", ALIAS = "fixture@lcx.example";
const box = { id: ID, address: PARENT, daily_cap: 50, out_today: 4, sent_today: 4, remaining: 46, usable: true, send_as: [], from_address: null };
const calls = [], errors = [], external = [];
let saveFailure = false;
async function main() {
  const server = http.createServer((req, res) => {
    const name = new URL(req.url, "http://127.0.0.1").pathname;
    const files = { "/": [html, "text/html"], "/app.js": [appSource, "application/javascript"], "/style.css": [fs.readFileSync(path.join(staticDir, "style.css")), "text/css"] };
    const file = files[name];
    res.writeHead(file ? 200 : 404, { "Content-Type": file ? file[1] : "text/plain" });
    res.end(file ? file[0] : "Unknown fixture");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const executablePath = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean).find((p) => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== base) { external.push(req.url()); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const key = `${req.method()} ${url.pathname}`; calls.push(key);
      let data, status = 200;
      if (key === "GET /api/me/mailboxes") data = { mailboxes: [box], web_connect: true };
      else if (key === `POST /api/mailboxes/${ID}/refresh-aliases`) {
        box.send_as = [{ address: ALIAS, name: "Fixture Sender" }];
        data = { ok: true, send_as: box.send_as };
      } else if (key === `POST /api/mailboxes/${ID}/sender`) {
        const body = req.postDataJSON();
        assert.deepEqual(Object.keys(body), ["address"]);
        assert([PARENT, ALIAS].includes(body.address));
        if (saveFailure) { status = 502; data = { detail: "Fixture Google outage. Your sender has not changed." }; }
        else { box.from_address = body.address === PARENT ? null : body.address; data = { ok: true, sends_as: body.address }; }
      } else if (key === "GET /api/mailboxes") data = { mode: "approver", can_send: true, paused: null, resets_at: "2026-11-07T00:00:00Z", accounts: [{ name: "Fixture Sender", email: PARENT, me: true, mailboxes: [{ ...box, sends_as: box.from_address || box.address }], scheduled: [], approved_waiting: 0 }] };
      else { status = 404; data = { detail: "Unknown fixture" }; errors.push(key); }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    });
    await page.goto(base);
    await page.evaluate(async () => { state.segment = { slug: "lcx-clipping", ui: {} }; await openSendingAddress(); });
    assert.match(await page.locator("#modalRoot").innerText(), /parent TVF account/);
    assert.match(await page.locator("#modalRoot").innerText(), /alias needs no separate login/);
    assert.equal(await page.locator("[data-sender] option").count(), 1);
    await page.locator("[data-refresh-aliases]").click();
    await page.waitForFunction((a) => !!document.querySelector(`option[value="${a}"]`), ALIAS);
    await page.locator("[data-sender]").selectOption(ALIAS);
    await page.locator("[data-save-sender]").click();
    await page.waitForFunction((a) => document.querySelector("[data-sender]")?.value === a && document.querySelector("#mailboxStrip")?.innerText.includes(a), ALIAS);
    assert.equal(box.address, PARENT, "parent account is retained");
    assert.equal(box.from_address, ALIAS);
    assert.equal(box.daily_cap, 50, "alias does not create another daily allowance");
    assert.match(await page.locator("#modalRoot").innerText(), /46 left/);
    saveFailure = true;
    await page.locator("[data-sender]").selectOption(PARENT);
    await page.locator("[data-save-sender]").click();
    await page.waitForFunction(() => document.body.innerText.includes("Fixture Google outage"));
    assert.equal(box.from_address, ALIAS, "failed save retains the actual selection");
    box.send_as = [];
    await page.evaluate(() => openSendingAddress());
    assert.match(await page.locator("[data-sender] option:checked").innerText(), /unavailable/);
    assert.match(await page.locator("#modalRoot").innerText(), /Emails wait until you refresh/);
    await page.setViewportSize({ width: 580, height: 950 });
    await page.evaluate(() => openSendingAddress());
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, "no horizontal overflow");
    const screen = path.resolve(__dirname, "../logs/mailbox-alias-ui.png");
    await page.screenshot({ path: screen, fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    assert(calls.every((c) => !/outreach.*decision|send$/.test(c)), "no approval or sending endpoint called");
    console.log("Mailbox alias UI passed: parent login guidance, refresh, selection, shared cap, failed save, unavailable alias and narrow layout. No emails sent.");
    console.log(screen);
  } finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
