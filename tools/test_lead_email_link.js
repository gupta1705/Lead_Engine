/* Focused browser regression for lead -> existing email navigation.
 * Run: node tools/test_lead_email_link.js
 * Uses real static HTML/CSS/JS, omitting only automatic startup so fixtures do
 * not require authentication or a database. All API traffic is fixture-only;
 * save/approval responses are mocked only for the explicit action test below.
 * No real email is approved, sent, or modified.
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
const screenshotDir = process.env.LEAD_EMAIL_SCREENSHOTS && path.resolve(process.env.LEAD_EMAIL_SCREENSHOTS);
if (screenshotDir) fs.mkdirSync(screenshotDir, { recursive: true });
const source = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const initMarker = "(async function init() {";
assert.equal(source.split(initMarker).length, 2, "one known startup function to omit");
const appSource = source.slice(0, source.indexOf(initMarker));
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8")
  .replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g, "");
const requests = [], mutations = [], unexpected = [], errors = [];
const fixtureWrites = [];
let allowFixtureWrites = false;
const delayed = new Set(), pending = new Map(), failures = new Map();
const company = (id, status = "drafted") => ({
  id, name: `Fixture ${id}`, domain: "example.test", source: "apollo",
  status: "shortlisted", fit_score: 82, metadata: {}, contacts: [],
  created_at: "2026-10-19T00:00:00Z", outreach: status ? { id: `email-${id}`, status } : null,
});
const message = (id, status = "drafted") => ({
  id: `email-${id}`, entity_id: id, status, direction: "outbound", company: `Fixture ${id}`,
  domain: "example.test", subject: `Exact ${id} subject`, body: `Exact ${id} email body.`,
  contact_name: "Fixture Contact", contact_email: "person@example.test",
  created_at: "2026-10-19T00:00:00Z", attachments: [],
  ...(status === "sent" ? { sent_at: "2026-10-19T01:00:00Z" } : {}),
});
const leads = {
  draft: company("draft"), approved: company("approved", "approved"),
  sent: company("sent", "sent"), none: company("none", null),
};
const mail = { draft: message("draft"), approved: message("approved", "approved"), sent: message("sent", "sent") };

async function main() {
  const server = http.createServer((req, res) => {
    const p = new URL(req.url, "http://127.0.0.1").pathname;
    const files = {
      "/": [html, "text/html"], "/app.js": [appSource, "application/javascript"],
      "/style.css": [fs.readFileSync(path.join(staticDir, "style.css")), "text/css"],
    };
    const item = files[p];
    res.writeHead(item ? 200 : 404, { "Content-Type": item ? item[1] : "text/plain" });
    res.end(item ? item[0] : "Fixture route missing");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const executables = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean);
  const executablePath = executables.find((p) => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  let passed = 0;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== base) { unexpected.push(req.url()); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      requests.push(url.pathname);
      if (req.method() !== "GET") {
        const key = `${req.method()} ${url.pathname}`;
        if (allowFixtureWrites && ["PATCH /api/outreach/email-draft", "POST /api/outreach/email-draft/decision"].includes(key)) {
          fixtureWrites.push({ key, body: req.postDataJSON() });
          return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, status: "approved", can_send: false }) });
        }
        mutations.push(`${req.method()} ${url.pathname}`);
        return route.fulfill({ status: 405, contentType: "application/json", body: JSON.stringify({ detail: "Writes forbidden in fixture test" }) });
      }
      if (delayed.has(url.pathname)) await new Promise((resolve) => pending.set(url.pathname, resolve));
      pending.delete(url.pathname);
      if (failures.has(url.pathname)) return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: failures.get(url.pathname) }) });
      let data;
      if (url.pathname === "/api/mailboxes") data = { mode: "approver", can_send: true, paused: null, mailboxes: [], people: [] };
      else if (/^\/api\/leads\/[^/]+$/.test(url.pathname)) data = leads[url.pathname.split("/").pop()];
      else if (/^\/api\/outreach\/email-[^/]+$/.test(url.pathname)) data = mail[url.pathname.split("email-").pop()];
      else if (/^\/api\/outreach\/[^/]+\/window$/.test(url.pathname)) data = { enabled: true, window_label: "Fixture next sending window" };
      if (!data) unexpected.push(url.pathname);
      return route.fulfill({ status: data ? 200 : 404, contentType: "application/json", body: JSON.stringify(data || { detail: "Unknown fixture" }) });
    });
    await page.goto(base, { waitUntil: "load" });
    const seed = async () => page.evaluate(() => {
      modal.close(true); document.querySelector("#flags").innerHTML = "";
      history.replaceState(null, "", "#leads");
      state.route = "leads";
      state.segment = { id: "fixture-project", ui: {}, outreach_policy: { send_window: { start: "10:00", end: "10:30" } } };
      state.nav = { kind: "lead", ids: ["draft", "approved", "sent"] };
      Object.assign(state.leads, { page: 3, filters: { q: "chosen lead", status: "shortlisted", source: "apollo", contact: "yes" } });
      Object.assign(state.outreach, { folder: "sent", category: "chosen-category", service: "chosen-service", sort: "views", direction: "asc", offset: 400,
        rows: [{ id: "unrelated-email", subject: "Unrelated row", status: "sent" }], counts: { drafts: 1000, sent: 2 }, selected: new Set(["unrelated-email"]) });
      document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === "view-leads"));
    });
    const snapshot = () => page.evaluate(() => ({
      route: state.route, nav: state.nav, leads: { page: state.leads.page, filters: state.leads.filters },
      outreach: Object.fromEntries(["folder", "category", "service", "sort", "direction", "offset", "rows", "counts"].map((k) => [k, state.outreach[k]])),
      selected: [...state.outreach.selected],
    }));
    const open = async (id) => {
      await page.evaluate(async (id) => { history.replaceState(null, "", "#lead/" + id); await openLead(id); }, id);
      await page.waitForFunction((id) => modal.current && modal.current.kind === "lead" && modal.current.id === id && !document.querySelector('[aria-label="Opening the lead"]'), id);
    };
    const test = async (name, fn) => { await seed(); await fn(); assert.deepEqual(errors, [], "no browser exceptions"); passed++; console.log(`PASS ${name}`); };
    const waitPending = async (p) => {
      for (let i = 0; i < 100 && !pending.has(p); i++) await new Promise((resolve) => setTimeout(resolve, 20));
      assert(pending.has(p), `request pending: ${p}`);
    };
    const release = async (p) => {
      const response = page.waitForResponse((r) => new URL(r.url()).pathname === p);
      delayed.delete(p); pending.get(p)(); await response;
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };

    await test("Open draft is beside decisions and opens exact email absent from list without resetting filters or pages", async () => {
      await open("draft");
      const foot = page.locator("#modalRoot .modal-foot");
      assert.deepEqual(await foot.locator("button").allTextContents(), ["Undo decision", "Reject", " Open draft"]);
      if (screenshotDir) {
        await page.screenshot({ path: path.join(screenshotDir, "lead-open-draft-desktop.png") });
        await page.setViewportSize({ width: 390, height: 844 });
        await page.screenshot({ path: path.join(screenshotDir, "lead-open-draft-narrow.png") });
        await page.setViewportSize({ width: 1440, height: 1000 });
      }
      const before = await snapshot();
      await page.locator("#leadOpenEmail").click();
      await page.locator("#draftSubject").waitFor();
      assert.equal(await page.locator("#draftSubject").inputValue(), mail.draft.subject);
      assert.equal(await page.locator("#draftBody").inputValue(), mail.draft.body);
      if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "exact-email-draft-desktop.png") });
      assert.equal(await page.evaluate(() => modal.current.id), mail.draft.id);
      assert.equal(await page.evaluate(() => location.hash), "#leads");
      assert.deepEqual(await snapshot(), before);
      assert(requests.includes("/api/outreach/email-draft"));
      await page.locator("#msgOpenLead").click();
      await page.locator("#leadOpenEmail").waitFor();
      assert.equal(await page.evaluate(() => modal.current.kind), "lead");
      assert.equal(await page.evaluate(() => modal.current.id), "draft");
    });

    for (const status of ["approved", "sent"]) await test(`View email opens ${status} message read-only`, async () => {
      await open(status);
      assert.equal((await page.locator("#leadOpenEmail").textContent()).trim(), "View email");
      await page.locator("#leadOpenEmail").click();
      await page.locator("#msgOpenLead").waitFor();
      assert.equal(await page.locator("#modalRoot .mail-body").textContent(), mail[status].body);
      assert.equal(await page.locator("#draftSubject, #draftBody, #draftSave, [data-act=approve]").count(), 0);
      assert.equal(await page.evaluate(() => modal.current.id), mail[status].id);
    });

    await test("Lead with no email keeps decision controls and has no Open draft button", async () => {
      await open("none");
      assert.equal(await page.locator("#leadOpenEmail").count(), 0);
      assert.equal(await page.locator("[data-decide=reset]").count(), 1);
      assert.equal(await page.locator("[data-decide=reject]").count(), 1);
      if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "lead-without-email-desktop.png") });
    });

    await test("Failed email fetch keeps lead open and restores button for successful retry", async () => {
      failures.set("/api/outreach/email-draft", "Fixture email unavailable");
      await open("draft"); await page.locator("#leadOpenEmail").click();
      await page.locator("#flags").getByText("Could not open email: Fixture email unavailable").waitFor();
      assert.equal(await page.locator("#leadOpenEmail").isEnabled(), true);
      assert.equal(await page.evaluate(() => modal.current.kind), "lead");
      assert.equal(await page.evaluate(() => location.hash), "#lead/draft");
      failures.delete("/api/outreach/email-draft");
      await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
    });

    await test("Mailbox fetch failure does not prevent opening email", async () => {
      failures.set("/api/mailboxes", "Fixture mailbox unavailable");
      await open("draft"); await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
      failures.delete("/api/mailboxes");
    });

    for (const action of ["close", "replace", "project"]) await test(`Late email response ignored after ${action}`, async () => {
      const p = "/api/outreach/email-draft"; delayed.add(p);
      await open("draft"); await page.locator("#leadOpenEmail").click(); await waitPending(p);
      assert.equal(await page.locator("#leadOpenEmail").isDisabled(), true);
      if (action === "close") await page.locator("#modalRoot [data-close]").click();
      else if (action === "replace") await open("sent");
      else await page.evaluate(() => { state.segment = { id: "different-project", ui: {} }; });
      await release(p);
      assert.equal(await page.locator("#draftBody").count(), 0);
      if (action === "close") assert.equal(await page.locator("#modalRoot .modal").count(), 0);
      if (action === "replace") assert.equal(await page.evaluate(() => modal.current.id), "sent");
    });

    await test("Edited draft asks before Open lead and preserves edits when discard is declined", async () => {
      await open("draft"); await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
      await page.locator("#draftBody").fill("Unsaved fixture edits");
      const declined = page.waitForEvent("dialog");
      const click = page.locator("#msgOpenLead").click();
      const dialog = await declined; assert.match(dialog.message(), /Discard your changes/); await dialog.dismiss(); await click;
      assert.equal(await page.locator("#draftBody").inputValue(), "Unsaved fixture edits");
      assert.equal(await page.evaluate(() => modal.current.kind), "mail");
      const accepted = page.waitForEvent("dialog"), secondClick = page.locator("#msgOpenLead").click();
      await (await accepted).accept(); await secondClick; await page.locator("#leadOpenEmail").waitFor();
      assert.equal(await page.evaluate(() => modal.current.id), "draft");
    });

    await test("Mocked save preserves edited copy and approval refreshes Leads plus badge without loading Outreach", async () => {
      allowFixtureWrites = true;
      await page.evaluate(() => {
        window._leadEmailRefreshes = { leads: 0, outreach: 0, badge: [] };
        window._leadEmailOriginals = { loadLeads, loadOutreach, refreshOutreachCount };
        loadLeads = async () => { window._leadEmailRefreshes.leads++; };
        loadOutreach = async () => { window._leadEmailRefreshes.outreach++; };
        refreshOutreachCount = (force) => { window._leadEmailRefreshes.badge.push(force); };
      });
      try {
        await open("draft"); await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
        await page.locator("#draftSubject").fill("Edited fixture subject");
        await page.locator("#draftBody").fill("Edited fixture email body.");
        await page.locator("#draftSave").click();
        await page.locator("#flags").getByText("Draft saved", { exact: true }).waitFor();
        await page.waitForFunction(() => !state.outreach.busy);
        assert.deepEqual(await page.evaluate(() => window._leadEmailRefreshes), { leads: 0, outreach: 0, badge: [] });
        assert.equal(await page.locator("#draftBody").inputValue(), "Edited fixture email body.");
        await page.locator("[data-act=approve]").click();
        await page.waitForFunction(() => !modal.isOpen() && !state.outreach.busy);
        assert.deepEqual(await page.evaluate(() => window._leadEmailRefreshes), { leads: 1, outreach: 0, badge: [true] });
        assert.equal(await page.evaluate(() => state.route), "leads");
        assert.deepEqual(fixtureWrites.map((w) => w.key), ["PATCH /api/outreach/email-draft", "PATCH /api/outreach/email-draft", "POST /api/outreach/email-draft/decision"]);
        assert.deepEqual(fixtureWrites[0].body, { subject: "Edited fixture subject", body: "Edited fixture email body.", ai_rewritten: false });
        assert.deepEqual(fixtureWrites[1].body, fixtureWrites[0].body);
        assert.deepEqual(fixtureWrites[2].body, { action: "approve" });
      } finally {
        allowFixtureWrites = false;
        await page.evaluate(() => {
          ({ loadLeads, loadOutreach, refreshOutreachCount } = window._leadEmailOriginals);
          delete window._leadEmailOriginals; delete window._leadEmailRefreshes;
        });
      }
    });

    assert.deepEqual(mutations, [], "no unexpected API write attempts occurred");
    assert.deepEqual(unexpected, [], "all requests were known loopback fixtures");
    console.log(`${passed} browser regressions passed. No database, authentication, external network, or email sends used.`);
  } finally {
    pending.forEach((resolve) => resolve());
    await browser.close(); await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
