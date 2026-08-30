/* TVF Lead Engine -- review surface.
 *
 * No framework, no build step. The whole app is a table, a detail panel and
 * two buttons; the reason it stays vanilla is deployment, not taste (see the
 * note at the top of app/main.py).
 *
 * The one opinionated bit of UI logic lives in renderCriteria(): a criterion
 * that was never assessed is drawn differently from one that was assessed and
 * scored zero. That distinction is the whole point of the engine's
 * unverified_inputs design and it would be a waste to flatten it into "0".
 */

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { page: 0, perPage: 50, selected: null, rows: [], total: 0, rubric: [] };

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.className = "toast"; }, 2600);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = "/login"; throw new Error("signed out"); }
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}

/* ------------------------------------------------------------- tabs */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $("#view-" + btn.dataset.view).classList.add("active");
    if (btn.dataset.view === "dashboard") loadDashboard();
    if (btn.dataset.view === "shortlist") loadShortlist();
    if (btn.dataset.view === "outreach") loadOutreach();
    syncExportLink();
  });
});

/* -------------------------------------------------------- dashboard */
async function loadDashboard() {
  let s;
  try { s = await api("/api/stats"); }
  catch (e) { return toast("Could not load stats: " + e.message, true); }
  state.rubric = s.rubric || [];

  $("#statCards").innerHTML = [
    ["Companies found", s.total, false],
    ["With a website", s.with_domain, false],
    ["Contactable", s.with_contact, true],
    ["Named person", s.named_contact, true],
    ["Awaiting review", s.open_pool, false],
    ["Shortlisted", s.shortlisted, true],
  ].map(([k, n, hi]) =>
    `<div class="card ${hi ? "hi" : ""}"><div class="n">${n}</div><div class="k">${k}</div></div>`
  ).join("");

  const max = Math.max(1, ...s.histogram.map((h) => h.n));
  $("#histogram").innerHTML = s.histogram.map((h) =>
    `<div class="row">
       <div class="lbl">${h.band}</div>
       <div class="bar"><div class="fill" style="width:${(h.n / max * 100).toFixed(1)}%"></div></div>
       <div class="val">${h.n}</div>
     </div>`).join("");

  // Coverage is the diagnostic view: points nobody can earn.
  const pool = s.open_pool || 1;
  const byKey = {};
  state.rubric.forEach((r) => { byKey[r.key] = r; });
  $("#coverage").innerHTML = Object.entries(s.coverage).map(([key, n]) => {
    const pct = n / pool * 100;
    const cls = pct < 5 ? "starved" : pct < 40 ? "thin" : "ok";
    const r = byKey[key] || {};
    return `<div class="cov ${cls}">
      <div>
        <div class="top-line">
          <span>${esc(r.label || key)}</span>
          <span class="pts">${r.points != null ? r.points + " pts" : ""}</span>
        </div>
        <div class="track"><div class="fill" style="width:${Math.max(pct, 0.6).toFixed(1)}%"></div></div>
      </div>
      <div class="pct">${n}</div>
    </div>`;
  }).join("");

  $("#sourceTable").innerHTML =
    `<thead><tr><th>Source</th><th>Found</th><th>With site</th>
       <th>Contactable</th><th>Avg score</th><th>Reviewable</th></tr></thead><tbody>` +
    s.by_source.map((r) => `<tr>
        <td class="nm">${esc(r.source)}</td>
        <td>${r.n}</td><td>${r.with_domain}</td><td>${r.with_contact}</td>
        <td>${r.avg_score == null ? "&mdash;" : r.avg_score}</td>
        <td><strong>${r.reviewable}</strong></td>
      </tr>`).join("") + "</tbody>";
}

/* ------------------------------------------------------------ leads */
function filterQuery() {
  const p = new URLSearchParams();
  if ($("#q").value.trim()) p.set("q", $("#q").value.trim());
  if ($("#source").value) p.set("source", $("#source").value);
  if ($("#hasContact").checked) p.set("has_contact", "1");
  if (+$("#minScore").value) p.set("min_score", $("#minScore").value);
  p.set("limit", state.perPage);
  p.set("offset", state.page * state.perPage);
  return p.toString();
}

function scoreClass(n) { return n >= 25 ? "s-hi" : n > 0 ? "s-mid" : "s-lo"; }

async function loadLeads() {
  let d;
  try { d = await api("/api/leads?" + filterQuery()); }
  catch (e) { return toast("Could not load leads: " + e.message, true); }
  state.rows = d.rows; state.total = d.total;

  $("#resultCount").textContent =
    d.total.toLocaleString() + " compan" + (d.total === 1 ? "y" : "ies");

  $("#leadBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr data-id="${r.id}" class="${state.selected === r.id ? "sel" : ""}">
      <td><span class="score ${scoreClass(+r.fit_score)}">${r.fit_score}</span></td>
      <td><div class="nm">${esc(r.name)}</div>
          <div class="dm">${esc(r.domain || "no website yet")}</div></td>
      <td>${r.email
            ? `<div>${esc(r.contact_name || "")}</div><div class="dm">${esc(r.email)}</div>`
            : '<span class="muted">&mdash;</span>'}</td>
      <td class="src">${esc(r.source)}</td>
    </tr>`).join("")
    : `<tr><td colspan="4" class="muted" style="padding:32px;text-align:center">
         No companies match these filters.</td></tr>`;

  $("#leadBody").querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => selectLead(tr.dataset.id));
  });

  const from = d.total ? state.page * state.perPage + 1 : 0;
  const to = Math.min((state.page + 1) * state.perPage, d.total);
  $("#pageInfo").textContent = `${from}–${to} of ${d.total.toLocaleString()}`;
  $("#prevPage").disabled = state.page === 0;
  $("#nextPage").disabled = to >= d.total;
  syncExportLink();
}

/* ----------------------------------------------------------- detail */
function renderCriteria(criteria) {
  return criteria.map((c) => {
    const cls = !c.assessed ? "unassessed" : c.earned > 0 ? "earned" : "";
    const val = !c.assessed
      ? "not assessed"
      : `${c.earned} / ${c.points}`;
    return `<div class="crit ${cls}">
      <div class="cl">${esc(c.label)}</div>
      <div class="cv">${val}</div>
      ${!c.assessed
        ? `<div class="why">No source has looked at this yet &mdash; it is not
             evidence of a bad fit.</div>` : ""}
    </div>`;
  }).join("");
}

async function selectLead(id) {
  state.selected = id;
  $("#leadBody").querySelectorAll("tr").forEach((tr) =>
    tr.classList.toggle("sel", tr.dataset.id === id));

  let d;
  try { d = await api("/api/leads/" + id); }
  catch (e) { return toast("Could not load company: " + e.message, true); }

  const m = d.metadata || {};
  const research = m.p1_research || {};
  const size = m.team_size_evidence;

  const contacts = (d.contacts || []).length
    ? d.contacts.map((c) => `
        <div class="contact">
          <div class="who">${esc(c.full_name || "No name published")}
            ${c.is_primary ? '<span class="tag">primary</span>' : ""}</div>
          ${c.role_title ? `<div class="role">${esc(c.role_title)}</div>` : ""}
          <div class="mail"><a href="mailto:${esc(c.email)}">${esc(c.email)}</a></div>
        </div>`).join("")
    : '<p class="muted">No contact found yet.</p>';

  $("#detail").innerHTML = `
    <div class="d-head">
      <div class="d-name">${esc(d.name)}</div>
      <div class="d-meta">
        ${d.domain ? `<a href="https://${esc(d.domain)}" target="_blank" rel="noopener">${esc(d.domain)}</a> &middot; ` : ""}
        ${esc(d.source)}
        ${m.hq_city ? " &middot; " + esc(m.hq_city) + (m.hq_state ? ", " + esc(m.hq_state) : "") : ""}
        &middot; <span class="status-pill ${esc(d.status)}">${esc(d.status)}</span>
      </div>
    </div>

    ${m.why_fit ? `<div class="d-sec"><h3>Why this could fit</h3>
       <div class="d-body">${esc(m.why_fit)}</div></div>` : ""}

    <div class="d-sec">
      <h3>Score &mdash; ${d.fit_score == null ? 0 : (+d.fit_score).toFixed(1)} points</h3>
      <div class="d-body">${renderCriteria(d.criteria || [])}</div>
    </div>

    <div class="d-sec"><h3>Contacts</h3><div class="d-body">${contacts}</div></div>

    ${size ? `<div class="d-sec"><h3>Team size evidence</h3><div class="d-body">
        ${size.people_named} people named on <code>${esc(size.page || "")}</code>
        ${size.scored ? "" : ` &mdash; <span class="muted">recorded but not scored:
          outside the confident 2&ndash;20 band</span>`}
      </div></div>` : ""}

    ${research.key_contact ? `<div class="d-sec"><h3>Research notes</h3>
      <div class="d-body">
        ${research.ownership ? `<p><strong>Ownership:</strong> ${esc(research.ownership)}</p>` : ""}
        ${research.caveats ? `<p><strong>Caveats:</strong> ${esc(research.caveats)}</p>` : ""}
      </div></div>` : ""}

    ${d.status_reason ? `<div class="d-sec"><h3>Decision note</h3>
       <div class="d-body muted">${esc(d.status_reason)}</div></div>` : ""}

    <textarea id="rejectReason" rows="2"
      placeholder="Optional note — kept with the decision"></textarea>
    <div class="decide">
      <button class="btn good" id="btnShort">Shortlist</button>
      <button class="btn bad" id="btnReject">Reject</button>
      ${d.status === "shortlisted" || d.status === "rejected"
        ? '<button class="btn" id="btnReset">Undo</button>' : ""}
    </div>`;

  $("#btnShort").addEventListener("click", () => decide(id, "shortlist"));
  $("#btnReject").addEventListener("click", () => decide(id, "reject"));
  const rb = $("#btnReset");
  if (rb) rb.addEventListener("click", () => decide(id, "reset"));
}

async function decide(id, decision) {
  const reason = ($("#rejectReason") || {}).value || "";
  try {
    const r = await api("/api/leads/" + id + "/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision: decision, reason: reason }),
    });
    toast(r.name + " → " + r.status);
    await loadLeads();
    // Keep the decided company on screen even though the default filter has
    // just excluded it. Clearing the panel here looked tidy and was wrong: a
    // misclick became unrecoverable, because Undo lives in this panel and the
    // row is now unreachable from the list. selectLead fetches by id, so it
    // works perfectly well for a row that is no longer in view.
    selectLead(id);
  } catch (e) {
    toast("Could not save: " + e.message, true);
  }
}

/* -------------------------------------------------------- shortlist */
async function loadShortlist() {
  let d;
  try { d = await api("/api/leads?status=shortlisted&limit=500"); }
  catch (e) { return toast(e.message, true); }
  $("#shortTable").innerHTML = d.rows.length
    ? `<thead><tr><th>Score</th><th>Company</th><th>Contact</th><th>Source</th></tr></thead><tbody>`
      + d.rows.map((r) => `<tr>
          <td><span class="score ${scoreClass(+r.fit_score)}">${r.fit_score}</span></td>
          <td><div class="nm">${esc(r.name)}</div><div class="dm">${esc(r.domain || "")}</div></td>
          <td>${r.email ? esc(r.email) : '<span class="muted">&mdash;</span>'}</td>
          <td class="src">${esc(r.source)}</td></tr>`).join("")
      + "</tbody>"
    : `<tbody><tr><td class="muted" style="padding:24px">
         Nothing shortlisted yet. Approve companies in the review queue.</td></tr></tbody>`;
}

/* ---------------------------------------------------------- outreach */
const FOLDERS = [
  ["drafts", "Drafts"], ["outbox", "Approved"], ["sent", "Sent"],
  ["inbox", "Replies"], ["positive", "Positive"], ["negative", "Negative"],
  ["attention", "Attention"], ["cancelled", "Cancelled"],
];
const oState = { folder: "drafts", rows: [], selected: null, reqToken: 0, busy: false };

async function loadOutreach() {
  // request token: folder switches can resolve out of order, and the review
  // found stale responses rendering under the wrong active pill
  const token = ++oState.reqToken;
  let d;
  try { d = await api("/api/outreach?folder=" + oState.folder); }
  catch (e) { return toast("Could not load outreach: " + e.message, true); }
  if (token !== oState.reqToken) return;
  oState.rows = d.rows;

  $("#folderBar").innerHTML = FOLDERS.map(([key, label]) =>
    `<button class="pill ${key === oState.folder ? "active" : ""}" data-f="${key}">
       ${label}<span class="n">${d.counts[key] || 0}</span></button>`).join("");
  $("#folderBar").querySelectorAll(".pill").forEach((b) =>
    b.addEventListener("click", () => { oState.folder = b.dataset.f; oState.selected = null;
      $("#outreachDetail").innerHTML = '<div class="empty"><p>Select a message.</p></div>';
      loadOutreach(); }));

  $("#outreachBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr data-id="${r.id}" class="${oState.selected === r.id ? "sel" : ""}">
      <td><div class="nm">${esc(r.company)}</div>
          <div class="dm">${esc(r.domain || "")}</div></td>
      <td><div>${esc(r.contact_name || "")}</div>
          <div class="dm">${esc(r.contact_email || "")}</div></td>
      <td>${esc(r.subject || "(no subject)")}
          ${r.triage ? ` <span class="triage-tag ${esc(r.triage)}">${esc(r.triage)}</span>` : ""}</td>
    </tr>`).join("")
    : `<tr><td colspan="3" class="muted" style="padding:28px;text-align:center">
         ${oState.folder === "drafts"
           ? "No drafts. Run: python tools/outreach.py draft"
           : "Nothing in this folder yet."}</td></tr>`;
  $("#outreachBody").querySelectorAll("tr[data-id]").forEach((tr) =>
    tr.addEventListener("click", () => selectOutreach(tr.dataset.id)));
}

function selectOutreach(id) {
  oState.selected = id;
  $("#outreachBody").querySelectorAll("tr").forEach((tr) =>
    tr.classList.toggle("sel", tr.dataset.id === id));
  const r = oState.rows.find((x) => x.id === id);
  if (!r) return;

  const isDraft = r.status === "drafted";
  const isReply = r.direction === "inbound";

  $("#outreachDetail").innerHTML = `
    <div class="d-head">
      <div class="d-name">${esc(r.company)}</div>
      <div class="d-meta">${esc(r.contact_name || "")} &middot;
        ${esc(r.contact_email || "")} &middot;
        <span class="status-pill">${esc(r.status)}</span>
        ${r.triage_reason ? `<div class="dm" style="margin-top:4px">${esc(r.triage_reason)}</div>` : ""}
      </div>
    </div>
    ${isDraft
      ? `<input id="draftSubject" value="${esc(r.subject || "")}">
         <textarea id="draftBody">${esc(r.body || "")}</textarea>
         <div class="decide">
           <button class="btn good" id="oApprove">Approve for sending</button>
           <button class="btn bad" id="oCancel">Cancel draft</button>
         </div>
         <p class="sub" style="margin-top:10px">Approving means: a person read
         exactly this text and stands behind it. Edits save on approve.</p>`
      : `<div class="d-sec"><h3>${esc(r.subject || "")}</h3>
           <div class="mail-body">${esc(r.body || "")}</div></div>
         ${isReply && r.status !== "cancelled" ? `<div class="decide">
           <button class="btn good" id="oPos">Mark positive</button>
           <button class="btn bad" id="oNeg">Mark negative</button>
         </div>` : ""}
         ${r.status === "approved" ? `<div class="decide">
           <button class="btn bad" id="oCancel">Withdraw approval</button></div>
           <p class="sub" style="margin-top:10px">Sends happen from the terminal:
           <code>python tools/outreach.py send</code></p>` : ""}`}
  `;

  const call = async (action, extra) => {
    if (oState.busy) return;                 // double-click guard (review finding)
    oState.busy = true;
    document.querySelectorAll("#outreachDetail .btn").forEach((b) => b.disabled = true);
    try {
      if (action === "approve") {
        await api("/api/outreach/" + id, { method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: $("#draftSubject").value,
                                 body: $("#draftBody").value }) });
      }
      await api("/api/outreach/" + id + "/decision", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: extra }) });
      toast("done");
      // the row has changed state: clear the stale panel rather than leave an
      // editor that silently discards further edits (review finding)
      oState.selected = null;
      $("#outreachDetail").innerHTML =
        '<div class="empty"><p>Select a message.</p></div>';
      await loadOutreach();
    } catch (e) { toast(e.message, true); }
    finally { oState.busy = false; }
  };
  const ap = $("#oApprove"); if (ap) ap.addEventListener("click", () => call("approve", "approve"));
  const cn = $("#oCancel");  if (cn) cn.addEventListener("click", () => call("", "cancel"));
  const po = $("#oPos");     if (po) po.addEventListener("click", () => call("", "mark_positive"));
  const ng = $("#oNeg");     if (ng) ng.addEventListener("click", () => call("", "mark_negative"));
}

/* ------------------------------------------------------------ wiring */
let debounce;
$("#q").addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => { state.page = 0; loadLeads(); }, 250);
});
$("#source").addEventListener("change", () => { state.page = 0; loadLeads(); });
$("#hasContact").addEventListener("change", () => { state.page = 0; loadLeads(); });
$("#minScore").addEventListener("input", (e) => {
  $("#minScoreOut").value = e.target.value;
  clearTimeout(debounce);
  debounce = setTimeout(() => { state.page = 0; loadLeads(); }, 200);
});
/* Keep the Export button pointed at whatever the reviewer is currently
 * looking at. A download that does not match the screen is a bug report
 * waiting to happen. */
function syncExportLink() {
  const p = new URLSearchParams();
  const onShortlist = $('.tab.active').dataset.view === "shortlist";
  p.set("status", onShortlist ? "shortlisted" : "open");
  if (!onShortlist) {
    if (+$("#minScore").value) p.set("min_score", $("#minScore").value);
    if ($("#source").value) p.set("source", $("#source").value);
  }
  const a = $("#exportBtn");
  a.href = "/api/export.xlsx?" + p.toString();
  a.textContent = onShortlist ? "Export shortlist" : "Export this view";
}

$("#prevPage").addEventListener("click", () => { state.page--; loadLeads(); });
$("#nextPage").addEventListener("click", () => { state.page++; loadLeads(); });

(async function init() {
  try {
    const s = await api("/api/stats");
    state.rubric = s.rubric || [];
    $("#source").innerHTML = '<option value="">All sources</option>'
      + s.by_source.map((r) => `<option value="${esc(r.source)}">${esc(r.source)} (${r.n})</option>`).join("");
  } catch (e) {
    toast("Cannot reach the database. Is SUPABASE_DB_URL set?", true);
  }
  loadLeads();
})();
