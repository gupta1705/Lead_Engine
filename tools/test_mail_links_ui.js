/* Browser regression for links in an email: Add link, what the draft shows, and read-only views.
 * Run: node tools/test_mail_links_ui.js
 * Uses the real static HTML/CSS/JS with fixture API answers only. No database, no real email, no sends.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const playwrightModule = process.env.PLAYWRIGHT_MODULE || (() => {
  try { return require.resolve("playwright"); }
  catch { return path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"); }
})();
const { chromium } = require(playwrightModule);

const staticDir = path.resolve(__dirname, "../app/static");
const source = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const initMarker = "(async function init() {";
assert.equal(source.split(initMarker).length, 2, "one known startup function to omit");
const appSource = source.slice(0, source.indexOf(initMarker));
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8").replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g, "");
const shots = process.env.MAIL_LINK_SCREENSHOTS && path.resolve(process.env.MAIL_LINK_SCREENSHOTS);
if (shots) fs.mkdirSync(shots, { recursive: true });

const BODY = "Hi Nicole,\n\n[ReelForge](https://reel--forge.vercel.app/#1), from LCX, cuts every episode.\n\nRegards,\nUpagnya";
const message = (id, status, body = BODY) => ({
  id, entity_id: "lead", status, direction: "outbound", company: "Fixture Show", domain: "example.test",
  subject: "Fixture Show | Clipping + Distribution", body, contact_name: "Nicole", contact_email: "nicole@example.test",
  created_at: "2026-11-06T00:00:00Z", attachments: [], ...(status === "sent" ? { sent_at: "2026-11-06T01:00:00Z" } : {}),
});
const mail = {
  draft: message("draft", "drafted"), plain: message("plain", "drafted", "Hi Nicole,\n\nA plain email about every episode."),
  sent: message("sent", "sent"),
  hostile: message("hostile", "sent", '<img src=x onerror="window.pwned=1"> [x](javascript:window.pwned=1) [<b>y</b>](https://a.example/"onclick="window.pwned=1)'),
};

async function main() {
  const server = http.createServer((req, res) => {
    const files = { "/": [html, "text/html"], "/app.js": [appSource, "application/javascript"],
                    "/style.css": [fs.readFileSync(path.join(staticDir, "style.css")), "text/css"] };
    const item = files[new URL(req.url, "http://127.0.0.1").pathname];
    res.writeHead(item ? 200 : 404, { "Content-Type": item ? item[1] : "text/plain" });
    res.end(item ? item[0] : "Fixture route missing");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const executablePath = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean).find((p) => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const saved = [], errors = [];
  let passed = 0;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== base) return route.abort();
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (req.method() === "PATCH") {
        saved.push(req.postDataJSON());
        return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      }
      const hit = url.pathname.match(/^\/api\/outreach\/([a-z]+)$/);
      const data = hit ? mail[hit[1]] : url.pathname.endsWith("/window") ? { enabled: false } : url.pathname === "/api/mailboxes"
        ? { mode: "approver", can_send: true, paused: null, mailboxes: [], people: [] } : {};
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
    });
    await page.goto(base, { waitUntil: "load" });
    const open = async (id, ready) => {
      await page.evaluate(({ id, msg }) => {
        modal.close(true); document.querySelector("#flags").innerHTML = "";
        state.segment = { id: "fixture", ui: {}, outreach_policy: {} };
        state.nav = { kind: "mail", ids: [id] };
        openMessage(id, msg);
      }, { id, msg: mail[id] });
      await page.locator(ready).waitFor();
    };
    const test = async (name, fn) => { await fn(); assert.deepEqual(errors, [], "no browser exceptions"); passed++; console.log(`PASS ${name}`); };
    const selectWords = (words) => page.evaluate((w) => {
      const t = document.querySelector("#draftBody"), at = t.value.indexOf(w);
      t.focus(); t.setSelectionRange(at, at + w.length);
    }, words);
    const answer = (text) => page.once("dialog", (d) => (text === null ? d.dismiss() : d.accept(text)));

    await test("A draft keeps the form to edit and shows the link it will send", async () => {
      await open("draft", "#draftBody");
      assert.equal(await page.locator("#draftBody").inputValue(), BODY);
      assert.match(await page.locator("#draftLinks").textContent(), /Goes out as a link: ReelForge/);
      assert.equal(await page.locator("#draftLinks a").getAttribute("href"), "https://reel--forge.vercel.app/#1");
      if (shots) await page.screenshot({ path: path.join(shots, "draft-with-link.png") });
    });

    await test("Add link wraps the selected words, updates the list and is what gets saved", async () => {
      await open("plain", "#draftBody");
      assert.equal(await page.locator("#draftLinks").isHidden(), true);
      await selectWords("every episode");
      answer("https://example.com/page");
      await page.locator("#draftLink").click();
      const want = "Hi Nicole,\n\nA plain email about [every episode](https://example.com/page).";
      assert.equal(await page.locator("#draftBody").inputValue(), want);
      assert.match(await page.locator("#draftLinks").textContent(), /every episode/);
      await page.locator("#draftSave").click();
      await page.waitForFunction(() => document.querySelector("#flags").textContent.includes("Draft saved"));
      assert.equal(saved.at(-1).body, want);
    });

    await test("A bare address works, and nothing changes without words or an address", async () => {
      await open("plain", "#draftBody");
      const body = mail.plain.body;
      await page.evaluate(() => { const t = document.querySelector("#draftBody"); t.focus(); t.setSelectionRange(0, 0); });
      await page.locator("#draftLink").click();
      await page.waitForFunction(() => document.querySelector("#flags").textContent.includes("Select the words"));
      assert.equal(await page.locator("#draftBody").inputValue(), body);
      await selectWords("plain email");
      answer("javascript:alert(1)");
      await page.locator("#draftLink").click();
      await page.waitForFunction(() => document.querySelector("#flags").textContent.includes("not a web address"));
      assert.equal(await page.locator("#draftBody").inputValue(), body);
      await selectWords("plain email");
      answer(null);
      await page.locator("#draftLink").click();
      assert.equal(await page.locator("#draftBody").inputValue(), body);
      await selectWords("plain email");
      answer("example.com");
      await page.locator("#draftLink").click();
      assert.match(await page.locator("#draftBody").inputValue(), /\[plain email\]\(example\.com\)/);
      assert.equal(await page.locator("#draftLinks a").getAttribute("href"), "https://example.com");
    });

    await test("A sent email reads as it was received: the word, clickable, no brackets", async () => {
      await open("sent", "#modalRoot .mail-body");
      const body = page.locator("#modalRoot .mail-body");
      assert.equal(await body.locator("a").textContent(), "ReelForge");
      assert.equal(await body.locator("a").getAttribute("href"), "https://reel--forge.vercel.app/#1");
      assert.match(await body.textContent(), /^Hi Nicole,\n\nReelForge, from LCX/);
      if (shots) await page.screenshot({ path: path.join(shots, "sent-with-link.png") });
    });

    await test("Text in an email cannot run script or carry a bad link", async () => {
      await open("hostile", "#modalRoot .mail-body");
      const body = page.locator("#modalRoot .mail-body");
      assert.equal(await body.locator("img, b").count(), 0);
      // only the http address is a link, its quote stays inside the address and its words are plain text
      assert.equal(await body.locator("a").count(), 1);
      assert.equal(await body.locator("a").textContent(), "<b>y</b>");
      assert.equal(await body.locator("a").getAttribute("onclick"), null);
      assert.equal(await body.locator('a[href^="javascript"]').count(), 0);
      assert.match(await body.textContent(), /\[x\]\(javascript:window\.pwned=1\)/);
      assert.equal(await page.evaluate(() => window.pwned), undefined);
    });
    console.log(`${passed} link browser regressions passed. No database, authentication, external network, or email sends used.`);
  } finally {
    await browser.close();
    server.close();
  }
}

main().catch((e) => { console.error(e); process.exitCode = 1; });
