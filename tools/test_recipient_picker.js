/* Browser regression for choosing a lead's draft recipient.
 * Run: node tools/test_recipient_picker.js
 * Loads the real static UI from loopback with fixture-only API responses.
 * Writes are explicitly mocked recipient preference POSTs and the focused
 * save/approval guard fixture test. They never leave the loopback browser.
 * No production service, authentication, database, approval, or sending is used.
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
const screenshotDir = process.env.RECIPIENT_SCREENSHOTS && path.resolve(process.env.RECIPIENT_SCREENSHOTS);
if (screenshotDir) fs.mkdirSync(screenshotDir, { recursive: true });
const source = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const initMarker = "(async function init() {";
assert.equal(source.split(initMarker).length, 2, "one known startup function to omit");
const appSource = source.slice(0, source.indexOf(initMarker));
const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8")
  .replace(/<link[^>]+https:\/\/fonts\.[^>]+>/g, "");

const INFO = "10000000-0000-4000-8000-000000000001";
const SAM = "10000000-0000-4000-8000-000000000002";
const NO_EMAIL = "10000000-0000-4000-8000-000000000003";
const RETIRED = "10000000-0000-4000-8000-000000000004";
const UNVERIFIED = "10000000-0000-4000-8000-000000000005";
const EDITED_BODY = "Hi Fixture,\n\nA manually edited opening.\n\nWe can help with your existing production work.\n\nFixture Sender";
const contacts = () => [
  { id: INFO, full_name: "Fixture Company", email: "info@example.test", role_title: "Contact", kind: "shared", usable: true, can_select_recipient: true, drafts_use: true },
  { id: SAM, full_name: "Sam Penfield", email: "sam@example.test", role_title: "Executive Producer", kind: "named", usable: true, can_select_recipient: true, drafts_use: false },
  { id: NO_EMAIL, full_name: "No Published Email", email: null, role_title: "Contact", usable: false, can_select_recipient: false, unusable_reason: "No email on record", drafts_use: false },
  { id: RETIRED, full_name: "Retired Contact", email: "old@example.test", role_title: "Former Producer", usable: false, can_select_recipient: false, unusable_reason: "Previous address", drafts_use: false },
  { id: UNVERIFIED, full_name: "Unverified Contact", email: "unverified@example.test", role_title: "Producer", usable: true, can_select_recipient: false, unusable_reason: "Apollo email is not verified", drafts_use: false },
];
const makeLead = (id, status = "drafted") => ({
  id, name: `Fixture ${id}`, domain: "example.test", source: "apollo", status: "shortlisted",
  fit_score: 82, metadata: {}, created_at: "2026-10-19T00:00:00Z", contacts: contacts(),
  selected_recipient_id: null, recipient_locked_reason: null,
  outreach: status ? { id: `email-${id}`, status, contact_id: INFO } : null,
});
const makeMessage = (id, status = "drafted") => ({
  id: `email-${id}`, entity_id: id, contact_id: INFO, recipient_contact_id: INFO, status, direction: "outbound",
  company: `Fixture ${id}`, domain: "example.test", subject: "A subject to preserve exactly",
  body: EDITED_BODY, contact_name: "Fixture Company", contact_email: "info@example.test",
  attachments: [], created_at: "2026-10-19T00:00:00Z",
  ...(status === "sent" ? { sent_at: "2026-10-19T01:00:00Z" } : {}),
});
const leads = {}, mail = {};
const errors = [], unexpected = [], forbiddenWrites = [], requests = [], writes = [];
const guardedMailWrites = [];
let allowGuardedMailWrites = false;
let writeFailure = null;
const delayed = new Set(), pending = new Map();
function resetFixtures() {
  for (const key of Object.keys(leads)) delete leads[key];
  for (const key of Object.keys(mail)) delete mail[key];
  leads.draft = makeLead("draft"); mail.draft = makeMessage("draft");
  leads.future = makeLead("future", null);
  for (const status of ["approved", "sent"]) {
    leads[status] = makeLead(status, status); mail[status] = makeMessage(status, status);
    leads[status].recipient_locked_reason = status === "approved"
      ? "This email is already approved. Withdraw approval before changing its recipient."
      : "This email was already sent. Its recipient cannot be changed.";
    leads[status].contacts.forEach((c) => { c.can_select_recipient = false; });
  }
  leads.actual = makeLead("actual"); mail.actual = makeMessage("actual");
  leads.actual.selected_recipient_id = INFO;
  leads.actual.outreach.contact_id = SAM;
  leads.actual.contacts.forEach((c) => { c.drafts_use = c.id === SAM; c.selected_recipient = c.id === INFO; });
  mail.actual.contact_id = SAM; mail.actual.recipient_contact_id = SAM; mail.actual.contact_name = "Sam Penfield"; mail.actual.contact_email = "sam@example.test";
  writeFailure = null; writes.length = 0; requests.length = 0;
  guardedMailWrites.length = 0; allowGuardedMailWrites = false;
}

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
  const executablePath = [process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].filter(Boolean).find((p) => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  let passed = 0;
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", async (route) => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin !== base) { unexpected.push(req.url()); return route.abort(); }
      if (!url.pathname.startsWith("/api/")) return route.continue();
      const key = `${req.method()} ${url.pathname}`;
      requests.push(key);
      if (delayed.has(key)) await new Promise((resolve) => pending.set(key, resolve));
      pending.delete(key);
      let data;
      if (req.method() === "POST" && /^\/api\/leads\/[^/]+\/recipient$/.test(url.pathname)) {
        const id = url.pathname.split("/")[3], body = req.postDataJSON();
        writes.push({ key, body });
        if (writeFailure) return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: writeFailure }) });
        const d = leads[id], c = d.contacts.find((c) => c.id === body.contact_id);
        assert(c && c.can_select_recipient && !d.recipient_locked_reason, "only an eligible unlocked contact may be selected");
        assert.deepEqual(Object.keys(body), ["contact_id"], "only the chosen contact ID is submitted");
        d.selected_recipient_id = c.id;
        d.contacts.forEach((p) => { p.selected_recipient = p.id === c.id; p.drafts_use = !!d.outreach && p.id === c.id; });
        if (d.outreach) {
          d.outreach.contact_id = c.id;
          Object.assign(mail[id], { contact_id: c.id, recipient_contact_id: c.id, contact_name: c.full_name, contact_email: c.email,
            body: mail[id].body.replace(/^Hi Fixture,/, "Hi Sam,") });
        }
        data = { ok: true, contact_id: c.id, selected_recipient_id: c.id, draft_updated: !!d.outreach, email: d.outreach };
      } else if (allowGuardedMailWrites && ["PATCH /api/outreach/email-draft", "POST /api/outreach/email-draft/decision"].includes(key)) {
        guardedMailWrites.push({ key, body: req.postDataJSON() });
        data = { ok: true, status: "approved", can_send: false };
      } else if (req.method() !== "GET") {
        forbiddenWrites.push(key);
        return route.fulfill({ status: 405, contentType: "application/json", body: JSON.stringify({ detail: "Fixture write forbidden" }) });
      } else if (/^\/api\/leads\/[^/]+$/.test(url.pathname)) data = leads[url.pathname.split("/").pop()];
      else if (/^\/api\/outreach\/email-[^/]+$/.test(url.pathname)) data = mail[url.pathname.split("email-").pop()];
      else if (url.pathname === "/api/mailboxes") data = { mode: "approver", can_send: true, paused: null, mailboxes: [], people: [] };
      else if (/^\/api\/outreach\/[^/]+\/window$/.test(url.pathname)) data = { enabled: true, window_label: "Fixture next sending window" };
      if (!data) unexpected.push(key);
      return route.fulfill({ status: data ? 200 : 404, contentType: "application/json", body: JSON.stringify(data || { detail: "Unknown fixture" }) });
    });
    await page.goto(base, { waitUntil: "load" });
    const seed = async () => {
      resetFixtures();
      await page.evaluate(() => {
        modal.close(true); document.querySelector("#flags").innerHTML = "";
        history.replaceState(null, "", "#leads"); state.route = "leads";
        state.segment = { id: "fixture-project", ui: {}, outreach_policy: { send_window: { start: "10:00", end: "10:30" } } };
        state.nav = { kind: "lead", ids: ["draft", "future", "approved", "sent"] };
        Object.assign(state.leads, { page: 3, filters: { q: "chosen lead", status: "shortlisted", source: "apollo", contact: "yes" } });
        Object.assign(state.outreach, { folder: "sent", category: "chosen-category", service: "chosen-service", sort: "views", direction: "asc", offset: 400,
          rows: [{ id: "unrelated-email", subject: "Unrelated row", status: "sent" }], counts: { drafts: 1000, sent: 2 }, selected: new Set(["unrelated-email"]) });
        document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.id === "view-leads"));
        window._recipientRefreshes = { view: 0, badge: 0 };
        refreshCurrentView = () => { window._recipientRefreshes.view++; };
        refreshOutreachCount = () => { window._recipientRefreshes.badge++; };
      });
    };
    const snapshot = () => page.evaluate(() => ({
      route: state.route, leads: { page: state.leads.page, filters: state.leads.filters },
      outreach: Object.fromEntries(["folder", "category", "service", "sort", "direction", "offset", "rows", "counts"].map((k) => [k, state.outreach[k]])),
      selected: [...state.outreach.selected],
    }));
    const open = async (id) => {
      await page.evaluate(async (id) => { history.replaceState(null, "", "#lead/" + id); await openLead(id); }, id);
      await page.waitForFunction((id) => modal.current && modal.current.kind === "lead" && modal.current.id === id && !document.querySelector('[aria-label="Opening the lead"]'), id);
    };
    const contactRow = (email) => page.locator("#modalRoot .contact-row").filter({ hasText: email });
    const select = (id) => page.locator(`#modalRoot .contact-recipient[data-recipient="${id}"]`);
    const waitSelected = async (id, contactId) => {
      await page.waitForFunction(({ id, contactId }) => window._recipientRefreshes.view >= 0 && modal.current && modal.current.id === id
        && document.querySelectorAll("#modalRoot .contact-recipient.loading").length === 0
        && [...document.querySelectorAll("#modalRoot .contact-row")].some((r) => r.textContent.includes(contactId === "sam" ? "Sam Penfield" : "Fixture Company")
          && /Draft recipient|Selected recipient/.test(r.textContent)), { id, contactId });
    };
    const test = async (name, fn) => { await seed(); await fn(); assert.deepEqual(errors, [], "no browser exceptions"); passed++; console.log(`PASS ${name}`); };
    const waitPending = async (key) => {
      for (let i = 0; i < 100 && !pending.has(key); i++) await new Promise((resolve) => setTimeout(resolve, 20));
      assert(pending.has(key), `request pending: ${key}`);
    };
    const release = async (key) => {
      const response = page.waitForResponse((r) => `${r.request().method()} ${new URL(r.url()).pathname}` === key);
      delayed.delete(key); pending.get(key)(); await response;
      await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    };

    await test("Named contact can replace an info inbox and Open draft uses the exact updated email", async () => {
      await open("draft");
      assert.match(await contactRow("info@example.test").textContent(), /Draft recipient/);
      assert.match((await select(SAM).textContent()).trim(), /^Use for draft$/);
      const before = await snapshot();
      if (screenshotDir) {
        await page.screenshot({ path: path.join(screenshotDir, "recipient-choice-desktop.png") });
        await page.setViewportSize({ width: 390, height: 844 });
        await page.locator("#modalRoot .contact-recipient").first().scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(screenshotDir, "recipient-choice-narrow.png") });
        await page.setViewportSize({ width: 1440, height: 1000 });
      }
      await select(SAM).click(); await waitSelected("draft", "sam");
      assert.deepEqual(writes, [{ key: "POST /api/leads/draft/recipient", body: { contact_id: SAM } }]);
      assert.match(await contactRow("sam@example.test").textContent(), /Draft recipient/);
      assert.doesNotMatch(await contactRow("info@example.test").textContent(), /Draft recipient/);
      assert.deepEqual(await snapshot(), before, "recipient preference preserves list filters and pagination");
      if (screenshotDir) await page.screenshot({ path: path.join(screenshotDir, "recipient-selected-desktop.png") });
      await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
      assert.equal(await page.evaluate(() => modal.current.id), "email-draft");
      assert.equal(await page.locator("#draftSubject").inputValue(), "A subject to preserve exactly");
      assert.equal(await page.locator("#draftBody").inputValue(), EDITED_BODY.replace("Hi Fixture,", "Hi Sam,"));
      assert.equal(await page.locator('#modalRoot a[href="mailto:sam@example.test"]').count(), 1);
      assert.equal(await page.locator('#modalRoot a[href="mailto:info@example.test"]').count(), 0);
      assert.deepEqual(await snapshot(), before);
    });

    await test("Actual draft recipient badge follows the existing email rather than a stale preference", async () => {
      await open("actual");
      assert.match(await contactRow("sam@example.test").textContent(), /Draft recipient/);
      assert.doesNotMatch(await contactRow("info@example.test").textContent(), /Draft recipient|Selected recipient/);
      assert.equal(writes.length, 0);
    });

    await test("Saving and approving after a recipient change guard the exact reviewed address", async () => {
      allowGuardedMailWrites = true;
      try {
        await open("draft"); await select(SAM).click(); await waitSelected("draft", "sam");
        await page.locator("#leadOpenEmail").click(); await page.locator("#draftBody").waitFor();
        assert.deepEqual(await page.evaluate(() => expectedRecipients([
          { id: "email-draft", recipient_contact_id: "10000000-0000-4000-8000-000000000002", contact_email: "sam@example.test" },
          { id: "unselected-email", recipient_contact_id: "10000000-0000-4000-8000-000000000001", contact_email: "info@example.test" },
        ], ["email-draft"])), { "email-draft": { contact_id: SAM, email: "sam@example.test" } }, "batch guard includes only selected email IDs");
        assert.equal(await page.evaluate(() => expectedRecipients([{ id: "old-row" }], ["old-row"])), null,
          "older cached rows keep the compatibility path");
        await page.locator("#draftSave").click();
        await page.locator("#flags").getByText("Draft saved", { exact: true }).waitFor();
        await page.waitForFunction(() => !state.outreach.busy);
        await page.locator("[data-act=approve]").click();
        await page.waitForFunction(() => !modal.isOpen() && !state.outreach.busy);
        const saved = {
          subject: "A subject to preserve exactly", body: EDITED_BODY.replace("Hi Fixture,", "Hi Sam,"), ai_rewritten: false,
          expected_contact_id: SAM, expected_contact_email: "sam@example.test",
        };
        assert.deepEqual(guardedMailWrites, [
          { key: "PATCH /api/outreach/email-draft", body: saved },
          { key: "PATCH /api/outreach/email-draft", body: saved },
          { key: "POST /api/outreach/email-draft/decision", body: { action: "approve", expected_contact_id: SAM, expected_contact_email: "sam@example.test" } },
        ]);
      } finally { allowGuardedMailWrites = false; }
    });

    await test("Addressless, retired and unverified contacts cannot be chosen", async () => {
      await open("draft");
      for (const id of [NO_EMAIL, RETIRED, UNVERIFIED]) {
        const control = select(id);
        assert(await control.count() === 0 || await control.isDisabled(), `ineligible contact ${id} has no active choice`);
      }
      assert.equal(writes.length, 0);
    });

    await test("Lead without an existing email saves a future draft preference without creating or approving mail", async () => {
      await open("future");
      assert.match((await select(SAM).textContent()).trim(), /^Use for future drafts$/);
      await select(SAM).click(); await waitSelected("future", "sam");
      assert.deepEqual(writes, [{ key: "POST /api/leads/future/recipient", body: { contact_id: SAM } }]);
      assert.match(await contactRow("sam@example.test").textContent(), /Selected recipient/);
      assert.equal(await page.locator("#leadOpenEmail").count(), 0);
      assert.equal(leads.future.outreach, null);
    });

    for (const status of ["approved", "sent"]) await test(`${status} email shows a locked explanation and offers no active recipient change`, async () => {
      await open(status);
      assert((await page.locator("#modalRoot").textContent()).includes(leads[status].recipient_locked_reason));
      const controls = page.locator("#modalRoot .contact-recipient");
      for (let i = 0; i < await controls.count(); i++) assert(await controls.nth(i).isDisabled());
      assert.equal((await page.locator("#leadOpenEmail").textContent()).trim(), "View email");
      assert.equal(writes.length, 0);
      if (screenshotDir && status === "approved") await page.screenshot({ path: path.join(screenshotDir, "recipient-approved-locked.png") });
    });

    await test("Failed recipient save keeps the current recipient and allows retry", async () => {
      writeFailure = "Fixture recipient could not be saved";
      await open("draft"); await select(SAM).click();
      await page.locator("#recipientHelp").getByText(/Fixture recipient could not be saved/).waitFor();
      assert.match(await contactRow("info@example.test").textContent(), /Draft recipient/);
      assert.doesNotMatch(await contactRow("sam@example.test").textContent(), /Draft recipient/);
      assert.equal(await select(SAM).isEnabled(), true);
      assert.equal(leads.draft.outreach.contact_id, INFO);
      writeFailure = null;
      await select(SAM).click(); await waitSelected("draft", "sam");
      assert.equal(writes.length, 2);
    });

    await test("A pending recipient save suppresses repeat clicks and simultaneous contact changes", async () => {
      const key = "POST /api/leads/draft/recipient"; delayed.add(key);
      await open("draft"); await select(SAM).click(); await waitPending(key);
      assert.equal(await select(SAM).isDisabled(), true);
      const otherChoices = page.locator("#modalRoot .contact-recipient");
      for (let i = 0; i < await otherChoices.count(); i++) assert(await otherChoices.nth(i).isDisabled());
      await page.evaluate((id) => {
        const button = document.querySelector(`.contact-recipient[data-recipient="${id}"]`);
        button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }, SAM);
      assert.equal(requests.filter((r) => r === key).length, 1);
      await release(key); await waitSelected("draft", "sam");
      assert.equal(writes.length, 1);
    });

    for (const action of ["close", "replace", "project"]) await test(`Late recipient response does not reopen or overwrite the sheet after ${action}`, async () => {
      const key = "POST /api/leads/draft/recipient"; delayed.add(key);
      await open("draft"); await select(SAM).click(); await waitPending(key);
      if (action === "close") await page.locator("#modalRoot [data-close]").click();
      else if (action === "replace") await open("sent");
      else await page.evaluate(() => { state.segment = { id: "different-project", ui: {} }; modal.close(true); });
      await release(key);
      if (action === "replace") assert.equal(await page.evaluate(() => modal.current && modal.current.id), "sent");
      else assert.equal(await page.locator("#modalRoot .modal").count(), 0);
      assert.equal(requests.filter((r) => r === "GET /api/leads/draft").length, 1, "late write must not refresh the old lead");
    });

    assert.deepEqual(errors, [], "no browser exceptions");
    assert.deepEqual(forbiddenWrites, [], "no unapproved write endpoint used");
    assert.deepEqual(unexpected, [], "all requests used known loopback fixtures");
    console.log(`${passed} recipient browser regressions passed. No production data, external network, approvals, or sends used.`);
  } finally {
    pending.forEach((resolve) => resolve());
    await browser.close(); await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
