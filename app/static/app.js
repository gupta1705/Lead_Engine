/* TVF Lead Engine -- the review surface, rebuilt in the Jira idiom (2026-09-04).
 *
 * Still no framework and no build step; the reason is deployment, not taste
 * (see the note at the top of app/main.py). What changed is the shape of the
 * product: a project sidebar, a board with one column per pipeline state, a
 * list view, an issue-style modal for every lead and every email, reports,
 * and an operations page -- the layout people already know from Jira, so the
 * superior who inherits this needs no tour.
 *
 * The one opinionated bit of UI logic survives from v1, in renderCriteria():
 * a criterion that was never assessed is drawn differently from one that was
 * assessed and scored zero. That distinction is the whole point of the
 * engine's unverified_inputs design and it would be a waste to flatten it.
 */

/* ============================================================== utils */
const $ = (s, root) => (root || document).querySelector(s);
const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let REVIEW_THRESHOLD = 25, PRIORITY_THRESHOLD = 45;

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit" });
}
function rel(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime(); if (isNaN(t)) return "";
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60); if (m < 60) return m + "m ago";
  const h = Math.round(m / 60); if (h < 36) return h + "h ago";
  const d = Math.round(h / 24); if (d < 30) return d + "d ago";
  return fmtDate(iso).split(",")[0];
}
function fmtScore(n) { n = +n || 0; return Number.isInteger(n) ? String(n) : n.toFixed(1); }
function hashCode(s) { let h = 0; for (const c of String(s || "")) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }
function initials(name, fallback) {
  // letters and digits only: a scraped address like "%20info@x.com" must not
  // produce "%2" in an avatar
  const clean = (v) => String(v || "").replace(/[^a-z0-9]+/gi, " ").trim();
  const src = clean(name) || clean((fallback || "").split("@")[0]);
  if (!src) return "?";
  const parts = src.split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : src.slice(0, 2)).toUpperCase();
}
function avatar(name, seed, size) {
  if (!name && !seed) return `<span class="avatar none ${size || ""}" title="No contact yet">${icon("user", 12)}</span>`;
  const cls = "av-" + (hashCode(seed || name) % 8 + 1);
  return `<span class="avatar ${cls} ${size || ""}" title="${esc(name || seed)}">${esc(initials(name, seed))}</span>`;
}

/* ============================================================== icons */
const PATHS = {
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  warn: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  chevDown: '<path d="m6 9 6 6 6-6"/>',
  chevRight: '<path d="m9 18 6-6-6-6"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  news: '<path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5"/>',
  shield: '<path d="M12 2 4 5v6c0 5 3.5 9.3 8 10.5 4.5-1.2 8-5.5 8-10.5V5z"/><path d="m9 12 2 2 4-4"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  board: '<rect x="3" y="3" width="5" height="18" rx="1"/><rect x="10" y="3" width="5" height="12" rx="1"/><rect x="17" y="3" width="4" height="8" rx="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  chart: '<path d="M18 20V10M12 20V4M6 20v-6"/>',
  play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z" fill="currentColor"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z" fill="currentColor" stroke="none"/>',
  envelope: '<rect x="3" y="6" width="18" height="12" rx="1.5" fill="currentColor" stroke="none"/><path d="m4 8 8 5 8-5" stroke="#fff" stroke-width="2"/>',
};
function icon(name, size, extra) {
  return `<svg width="${size || 16}" height="${size || 16}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra || ""}>${PATHS[name] || ""}</svg>`;
}
function typeIcon(kind) {
  const glyph = kind === "mail" ? "envelope" : "bookmark";
  return `<span class="type-icon ${kind}" title="${kind === "mail" ? "Email" : "Lead"}">${icon(glyph, 10)}</span>`;
}
/* A project with no rubric (Universal) has no scores: its thresholds are both 0, and the
   board, list and dialog leave the score and priority out rather than show a row of zeros. */
function unscoredProject() { return !REVIEW_THRESHOLD && !PRIORITY_THRESHOLD; }
function ptsClass(score) { score = +score || 0; return score >= PRIORITY_THRESHOLD ? "hi" : score >= REVIEW_THRESHOLD ? "mid" : ""; }
function pts(score) { return `<span class="pts ${ptsClass(score)}" title="Fit score out of 100">${fmtScore(score)}</span>`; }

const LEAD_STATUS = {
  discovered: ["To review", ""], enriched: ["To review", ""], scored: ["To review", ""],
  ready_for_review: ["To review", ""], shortlisted: ["Shortlisted", "success"],
  contacted: ["Contacted", "inprogress"], in_conversation: ["In conversation", "success bold"],
  rejected: ["Rejected", "removed"], archived: ["Archived", ""],
};
function leadStatus(status) {
  const [label, cls] = LEAD_STATUS[status] || [String(status || "unknown").replace(/_/g, " "), ""];
  return { label, cls };
}
function statusLozenge(status) {
  const s = leadStatus(status);
  return `<span class="lozenge ${s.cls}">${esc(s.label)}</span>`;
}
// connector slugs as the database knows them -> what a reviewer should read
const SOURCES = {
  aicp_directory: ["AICP", ""], google_news_rss: ["News", "inprogress"], wikidata: ["Wikidata", "new"],
  youtube_api: ["YouTube", ""], x_intent: ["X", "new"], manual_p1: ["Manual", "moved"], manual: ["Manual", "moved"],
  wikidata_channels: ["Wikidata", "new"], tvf_pool: ["TVF pool", "moved"],
  apple_podcasts: ["Podcast", "new"], startup_news: ["News", "inprogress"], apollo: ["Apollo", "new"],
};
function sourceLabel(src) { return (SOURCES[src] || [String(src || "unknown").replace(/_/g, " "), ""])[0]; }
function sourceLozenge(src) {
  const [label, cls] = SOURCES[src] || [String(src || "unknown").replace(/_/g, " "), ""];
  return `<span class="lozenge ${cls}" title="Discovered by the ${esc(src)} connector">${esc(label)}</span>`;
}
function mailStatus(r) {
  const st = r.status, tri = r.triage;
  if (r.direction === "inbound") {
    if (tri === "positive") return ["Positive", "success bold"];
    if (tri === "negative") return ["Negative", "removed"];
    if (tri === "needs_human" || !tri) return ["Needs triage", "moved"];
    return [tri, ""];
  }
  return ({ drafted: ["Draft", ""], approved: ["Approved", "inprogress"],
    sending: ["Sending", "inprogress bold"], sent: ["Sent", "success"],
    send_unknown: ["Unknown", "moved bold"], send_error: ["Failed", "removed bold"],
    failed: ["Failed", "removed bold"], cancelled: ["Cancelled", ""],
    replied: ["Replied", "success"] })[st] || [String(st || "").replace(/_/g, " "), ""];
}
function mailLozenge(r) { const [l, c] = mailStatus(r); return `<span class="lozenge ${c}">${esc(l)}</span>`; }

/* ============================================================== flags */
function flag(title, opts) {
  opts = opts || {};
  const el = document.createElement("div");
  el.className = "flag " + (opts.kind || "");
  el.innerHTML = `${icon(opts.kind === "err" ? "alert" : opts.kind === "info" ? "info" : "checkCircle", 20)}
    <div><div class="t">${esc(title)}</div>${opts.desc ? `<div class="d">${esc(opts.desc)}</div>` : ""}</div>`;
  $("#flags").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 200); }, opts.ms || 3200);
}
const toast = (msg, isErr) => flag(msg, { kind: isErr ? "err" : "" });

/* ================================================================ api */
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
const post = (path, body) => api(path, { method: "POST",
  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

/* ============================================================== state */
const state = {
  route: null, user: null, sources: [], segment: null, segments: [],
  board: { filters: { q: "", min_score: REVIEW_THRESHOLD }, cols: {}, token: 0 },
  leads: { filters: { q: "", status: "all", source: "", contact: "" },
           page: 0, perPage: 50, total: 0, rows: [], token: 0 },
  outreach: { folder: "drafts", rows: [], counts: {}, token: 0, busy: false, selected: new Set() },
  ops: { timer: null },
  notif: { counts: null, at: 0 },
};

/* ============================================================== modal */
const modal = {
  lastFocus: null,
  open(html, opts) {
    opts = opts || {};
    this.close(true);
    this.lastFocus = document.activeElement;
    const root = $("#modalRoot");
    root.innerHTML = `<div class="blanket" data-blanket>
      <div class="modal ${opts.narrow ? "narrow" : ""}" role="dialog" aria-modal="true" aria-label="${esc(opts.label || "Dialog")}">${html}</div></div>`;
    document.body.style.overflow = "hidden";
    const blanket = $("[data-blanket]", root);
    blanket.addEventListener("mousedown", (e) => { if (e.target === blanket) this.close(); });
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", () => this.close()));
    this.onClose = opts.onClose || null;
    const first = $("[autofocus], .modal-foot .btn.primary, [data-close]", root);
    if (first) setTimeout(() => first.focus(), 30);
  },
  close(silent) {
    const root = $("#modalRoot");
    if (!root.innerHTML) return;
    root.innerHTML = "";
    document.body.style.overflow = "";
    const cb = this.onClose; this.onClose = null;
    if (!silent && cb) cb();
    if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus();
  },
  isOpen() { return !!$("#modalRoot").innerHTML; },
};
function modalHead(crumbHtml, actionsHtml) {
  return `<div class="modal-head">
    <span class="crumb">${crumbHtml}</span><span class="grow"></span>${actionsHtml || ""}
    <button class="btn icon" data-close aria-label="Close">${icon("x", 20)}</button></div>`;
}

/* ============================================================== menus */
function closeMenus(except) {
  $$(".menu").forEach((m) => { if (m !== except) m.hidden = true; });
  $$("[aria-expanded]").forEach((b) => {
    const m = b.parentElement && b.parentElement.querySelector(".menu");
    if (m && m !== except) b.setAttribute("aria-expanded", "false");
  });
}
function toggleMenu(btn, menu, render) {
  const open = menu.hidden;
  closeMenus(open ? menu : null);
  if (open) { if (render) render(menu); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); }
  else { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); }
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu-anchor")) closeMenus();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { closeMenus(); if (modal.isOpen()) modal.close(); }
});

/* ============================================================ routing */
const VIEWS = ["universal", "board", "leads", "outreach", "reports", "ops"];
let TITLES = { universal: "Search Apollo", board: "Lead board", leads: "Leads", outreach: "Outreach", reports: "Reports",
  ops: "Operations" };
function go(hash) { location.hash = hash; }
function currentView() { return state.route || defaultRoute(); }
/* A project's config may hide pages it has no use for (Universal has no outreach and no
   pipeline jobs) and name its own first page; the Apollo page exists only where the
   config asks for it. */
function routeAllowed(name) {
  const ui = segUi();
  if (!VIEWS.includes(name) || (ui.hide_routes || []).includes(name)) return false;
  return name !== "universal" || ui.search_page === "apollo";
}
function defaultRoute() { const d = segUi().default_route; return d && routeAllowed(d) ? d : "board"; }
function showView(name) {
  if (!routeAllowed(name)) name = defaultRoute();
  state.route = name;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  $$(".side-item[data-route]").forEach((b) => b.classList.toggle("active", b.dataset.route === name));
  document.title = TITLES[name] + " - TVF Lead Engine";
  $("#frame").classList.remove("drawer-open");
  if (name === "board") loadBoard();
  if (name === "leads") loadLeads();
  if (name === "outreach") loadOutreach();
  if (name === "reports") loadReports();
  if (name === "ops") loadOps();
  if (name === "universal") loadUniversal();
}
function router() {
  const h = (location.hash || "#" + defaultRoute()).slice(1);
  const [head, rest] = h.split("/");
  if (head === "lead" && rest) { if (!state.route) showView(defaultRoute()); openLead(rest); return; }
  if (head === "outreach" && rest) state.outreach.folder = FOLDERS.some(([k]) => k === rest) ? rest : "drafts";
  if (state.route === head && head !== "outreach") return;   // same view, nothing to do
  if (modal.isOpen()) modal.close(true);
  showView(head);
}
window.addEventListener("hashchange", router);

/* ============================================================ segment */
const UI_FALLBACK = { project_name: "US Production Houses", key_prefix: "TVF",
  board_title: "Lead board", list_title: "Leads", entity_label: "company", entity_plural: "companies",
  lead_first: "entity", summary_label: "Summary", card_fields: [], details: [] };
/* People first (2026-09-09): in a segment whose leads are shows, the card and
   the row lead with the person the engine found behind the show, and the show
   sits underneath. The record stays the show; the face is the host. */
function personFirst() { return segUi().lead_first === "person"; }
function hostOf(r) {
  if (r.host_name) return r.host_name;
  const h = (r.metadata || {}).host;
  return h && h.name && (h.confidence === "high" || h.confidence === "medium") ? h.name : null;
}
function leadTitle(r) {
  const host = hostOf(r);
  if (personFirst() && host) {
    // a show named after its host ("Aswath Damodaran") is not repeated underneath
    const same = host.trim().toLowerCase() === String(r.name || "").trim().toLowerCase();
    return { title: host, sub: same ? (r.domain || "") : r.name, aria: same ? host : host + ", " + r.name, same };
  }
  return { title: r.name, sub: r.domain || "", aria: r.name };
}
function kindLozenge(r) {
  return r.kind ? `<span class="lozenge inprogress" title="Kind of lead">${esc(String(r.kind).replace(/_/g, " "))}</span>` : "";
}
function segUi() { return Object.assign({}, UI_FALLBACK, (state.segment && state.segment.ui) || {}); }
function getPath(obj, path) {
  return String(path || "").split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function fmtField(v, format) {
  if (v == null || v === "") return "";
  const n = typeof v === "number" ? v : (typeof v === "string" && v.trim() !== "" && !isNaN(+v) ? +v : null);
  switch (format) {
    case "number": return n == null ? String(v) : Math.round(n).toLocaleString();
    case "number1": return n == null ? String(v) : (Math.round(n * 10) / 10).toString();
    case "compact": return n == null ? String(v) : n >= 1e6 ? (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M" : n >= 1e3 ? (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k" : String(Math.round(n));
    case "percent": return n == null ? String(v) : Math.round(n * 100) + "%";
    case "date": return fmtDate(v);
    case "list": return Array.isArray(v) ? v.join(", ") : String(v);
    case "link": return String(v).replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
    default: return Array.isArray(v) ? v.join(", ") : String(v);
  }
}
function fmtFieldHtml(v, format) {
  // only an http(s) address becomes a link: anything else in an href is not a web page
  if (format === "link" && v && /^https?:\/\//i.test(String(v))) return `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(fmtField(v, format))}</a>`;
  if (format === "list" && Array.isArray(v)) return `<span class="pill-list">${v.slice(0, 8).map((x) => `<span class="lozenge">${esc(x)}</span>`).join("")}</span>`;
  return esc(fmtField(v, format));
}
function fieldSummary(r) {
  const fields = segUi().card_fields || [];
  if (!fields.length || !Array.isArray(r.fields)) return "";
  return fields.map((f, i) => ({ f, v: r.fields[i] }))
    .filter((x) => x.v != null && x.v !== "")
    .map((x) => esc(fmtField(x.v, x.f.format)) + (x.f.label ? " " + esc(x.f.label) : "")).join(" · ");
}
function uiDetails(d) {
  return (segUi().details || []).map((f) => {
    const v = getPath(d, f.path);
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "";
    return `<dt>${esc(f.label)}</dt><dd>${fmtFieldHtml(v, f.format)}</dd>`;
  }).join("");
}
function applySegment(seg) {
  state.segment = seg;
  const ui = segUi();
  // 0 is a real threshold: a project with no rubric (Universal) scores nothing and hides nothing
  const rv = parseFloat((seg.thresholds || {}).review), pv = parseFloat((seg.thresholds || {}).priority);
  REVIEW_THRESHOLD = Number.isFinite(rv) ? rv : 25;
  PRIORITY_THRESHOLD = Number.isFinite(pv) ? pv : 45;
  $("#projectName").textContent = ui.project_name;
  $("#projectSwitch").dataset.prefix = ui.key_prefix || "TVF";          // tints the project icon per segment
  $("#projectSwitch").setAttribute("aria-label", "Project: " + ui.project_name + ". Switch project");
  $("#boardTitle").textContent = ui.board_title;
  $("#leadsTitle").textContent = ui.list_title;
  TITLES.board = ui.board_title; TITLES.leads = ui.list_title;
  $("#leadsLastCol").textContent = (ui.card_fields || []).length ? "Evidence" : "Location";
  $("#leadsSummaryCol").textContent = ui.summary_label || "Summary";
  const ent = ui.entity_label || "company";
  $("#outreachEntityCol").textContent = ent.charAt(0).toUpperCase() + ent.slice(1);
  /* The board's To review column starts at the review threshold. Where the automatic line sits
     at or below it (LCX: 20 against 25), everything the floor would show is shortlisted already,
     so the column shows every lead a person may still pick by hand. Where the line sits above it
     (production houses: 30 against 25), the band between the two is what a person reviews. */
  const autoLine = seg.auto_shortlist ? (seg.auto_shortlist_min == null ? 0 : seg.auto_shortlist_min) : null;
  state.board.filters.min_score = autoLine !== null && autoLine <= REVIEW_THRESHOLD ? 0 : REVIEW_THRESHOLD;
  $$(".side-item[data-route]").forEach((b) => { b.hidden = !routeAllowed(b.dataset.route); });
  COLUMNS = outreachOn() ? ALL_COLUMNS : ALL_COLUMNS.filter((c) => c.key !== "contacted" && c.key !== "in_conversation");
  $("#leadsTable").classList.toggle("unscored", unscoredProject());
  document.title = (TITLES[currentView()] || "") + " - " + ui.project_name;
}

/* ============================================================== board */
const ALL_COLUMNS = [
  { key: "open", title: "To review", status: "open" },
  { key: "shortlisted", title: "Shortlisted", status: "shortlisted" },
  { key: "contacted", title: "Contacted", status: "contacted" },
  { key: "in_conversation", title: "In conversation", status: "in_conversation", done: true },
];   // rejected leads have left the flow; Leads, Status: Rejected, is where to find one
function outreachOn() { return !(segUi().hide_routes || []).includes("outreach"); }
let COLUMNS = ALL_COLUMNS;
const COL_LIMIT = 60;

function boardQuery(col, offset) {
  const f = state.board.filters, p = new URLSearchParams();
  p.set("status", col.status);
  if (f.q) p.set("q", f.q);
  if (col.key === "open" && f.min_score) p.set("min_score", f.min_score);   // the floor shapes the review band only
  p.set("limit", COL_LIMIT); p.set("offset", offset || 0);
  return p.toString();
}

function renderCard(r, col) {
  const score = +r.fit_score || 0;
  const place = r.state || r.city;
  const t = leadTitle(r);
  // the source says something only where a project has more than one
  const tags = (state.sources.length > 1 ? sourceLozenge(r.source) : "") + kindLozenge(r)
    + (place ? `<span class="lozenge" title="${esc((r.city || "") + (r.state ? ", " + r.state : ""))}">${esc(place)}</span>` : "");
  return `<div class="card ${col.done ? "done" : ""}" role="button" tabindex="0" data-id="${esc(r.id)}"
       aria-label="${esc(t.aria)}, score ${fmtScore(score)}">
    <div class="card-summary">${esc(t.title)}</div>
    ${t.sub ? `<div class="card-sub truncate">${esc(t.sub)}</div>` : ""}
    ${fieldSummary(r) ? `<div class="card-sub">${fieldSummary(r)}</div>` : ""}
    ${tags ? `<div class="card-tags">${tags}</div>` : ""}
    <div class="card-foot">
      <span class="right">${unscoredProject() ? "" : pts(score)}${avatar(r.contact_name, r.email, "")}</span>
    </div></div>`;
}

function renderColumn(col) {
  const c = state.board.cols[col.key] || { rows: [], total: 0 };
  const body = c.rows.length
    ? c.rows.map((r) => renderCard(r, col)).join("")
    : `<div class="column-empty">${state.board.filters.q ? "Nothing matches this search." : col.key === "open" ? "Nothing to review." : "No leads here yet."}</div>`;
  const more = c.rows.length < c.total
    ? `<button class="btn subtle compact column-more" data-more="${col.key}">Show more (${c.total - c.rows.length} left)</button>` : "";
  return `<section class="column" aria-label="${esc(col.title)}">
    <div class="column-head"><span class="${col.done ? "done" : ""}">${esc(col.title)}</span>
      <span class="n">${c.total}</span>${col.done ? icon("checkCircle", 14, 'style="color:var(--text-success)"') : ""}</div>
    <div class="column-body" data-col="${col.key}">${body}${more}</div></section>`;
}

async function loadBoard() {
  const token = ++state.board.token;
  const board = $("#board");
  if (!Object.keys(state.board.cols).length) board.innerHTML = COLUMNS.map(renderColumn).join("");
  try {
    const results = await Promise.all(COLUMNS.map((col) => api("/api/leads?" + boardQuery(col, 0))));
    if (token !== state.board.token) return;
    COLUMNS.forEach((col, i) => { state.board.cols[col.key] = { rows: results[i].rows, total: results[i].total }; });
  } catch (e) { return toast("Could not load the board: " + e.message, true); }
  board.innerHTML = COLUMNS.map(renderColumn).join("");
  bindBoard();
}

/* Opening a lead or a message is a click ANYWHERE on its row or card, not on
   the key. One delegated listener per list does that, and unlike a listener
   per row it survives every re-render, so a row can never end up dead. Real
   controls inside a row (a checkbox, a link, a button) still do their own job. */
function delegateOpen(containerSel, open, skipSel) {
  const el = $(containerSel);
  if (!el || el.dataset.delegated) return;
  el.dataset.delegated = "1";
  const idFrom = (e) => {
    if (skipSel && e.target.closest(skipSel)) return null;
    if (e.target.closest("a, button, input, textarea, select, label")) return null;
    const row = e.target.closest("[data-id]");
    return row && el.contains(row) ? row.dataset.id : null;
  };
  el.addEventListener("click", (e) => { const id = idFrom(e); if (id) open(id); });
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const id = idFrom(e);
    if (id) { e.preventDefault(); open(id); }
  });
}

function bindBoard() {
  const board = $("#board");
  delegateOpen("#board", (id) => go("lead/" + id), "[data-more]");
  $$("[data-more]", board).forEach((b) => b.addEventListener("click", async () => {
    const col = COLUMNS.find((x) => x.key === b.dataset.more), c = state.board.cols[col.key];
    b.classList.add("loading");
    try {
      const d = await api("/api/leads?" + boardQuery(col, c.rows.length));
      c.rows = c.rows.concat(d.rows); c.total = d.total;
      $("#board").innerHTML = COLUMNS.map(renderColumn).join("");
      bindBoard();
    } catch (e) { toast(e.message, true); b.classList.remove("loading"); }
  }));
}

/* ============================================================== leads */
function leadsQuery() {
  const f = state.leads.filters, p = new URLSearchParams();
  p.set("status", f.status);
  if (f.q) p.set("q", f.q);
  if (f.source) p.set("source", f.source);
  if (f.contact) p.set("contact", f.contact);
  p.set("limit", state.leads.perPage);
  p.set("offset", state.leads.page * state.leads.perPage);
  return p.toString();
}

async function loadLeads() {
  const token = ++state.leads.token;
  let d;
  try { d = await api("/api/leads?" + leadsQuery()); }
  catch (e) { return toast("Could not load leads: " + e.message, true); }
  if (token !== state.leads.token) return;
  state.leads.rows = d.rows; state.leads.total = d.total;
  $("#leadsCount").textContent = d.total.toLocaleString() + " " + (d.total === 1 ? (segUi().entity_label || "company") : (segUi().entity_plural || "companies"));
  $("#leadsBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr class="row-link" data-id="${esc(r.id)}" tabindex="0">
      <td>${(() => { const t = leadTitle(r);
        const parts = [t.sub || (personFirst() ? (r.domain || "") : "no website yet"), r.kind ? String(r.kind).replace(/_/g, " ") : ""].filter(Boolean);
        return `<div class="primary-cell">${esc(t.title)}</div><div class="secondary">${esc(parts.join(" · "))}</div>`; })()}</td>
      <td class="col-status">${statusLozenge(r.status)}</td>
      <td class="col-score">${pts(r.fit_score)}</td>
      <td class="col-source">${sourceLozenge(r.source)}</td>
      <td>${r.email ? `<span class="cell-person">${avatar(r.contact_name, r.email)}<span>${r.contact_name ? `<div>${esc(r.contact_name)}</div><div class="secondary">${esc(r.email)}</div>` : `<div>${esc(r.email)}</div>`}</span></span>` : '<span class="muted">No address</span>'}</td>
      <td class="secondary">${fieldSummary(r) || esc([r.city, r.state].filter(Boolean).join(", ") || "")}</td>
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="6">No ${esc(segUi().entity_plural || "companies")} match these filters.</td></tr>`;
  $("#leadsTable").classList.toggle("one-status", state.leads.filters.status !== "all");
  // The filter shows only where it can change what is on screen: a selection that is
  // all addresses, or none, has nothing to narrow.
  const split = $("#leadsContact");
  split.hidden = !(d.with_address && d.without_address) && !state.leads.filters.contact;
  split.options[1].textContent = `Has an address (${(d.with_address || 0).toLocaleString()})`;
  split.options[2].textContent = `No address yet (${(d.without_address || 0).toLocaleString()})`;
  delegateOpen("#leadsBody", (id) => go("lead/" + id));
  const from = d.total ? state.leads.page * state.leads.perPage + 1 : 0;
  const to = Math.min((state.leads.page + 1) * state.leads.perPage, d.total);
  $("#leadsInfo").textContent = `${from}–${to}`;       // the total is in the count above the table
  $("#leadsPrev").disabled = state.leads.page === 0;
  $("#leadsNext").disabled = to >= d.total;
  $("#leadsPager").hidden = d.total <= state.leads.perPage && !state.leads.page;
  $("#leadsExport").hidden = !d.total;                   // an empty view has nothing to download
  syncExportLinks();
}

function syncExportLinks() {
  const l = state.leads.filters, q = new URLSearchParams();
  q.set("status", l.status);
  if (l.q) q.set("q", l.q);
  if (l.source) q.set("source", l.source);
  if (l.contact) q.set("contact", l.contact);
  $("#leadsExport").href = "/api/export.xlsx?" + q.toString();
}

/* ======================================================== lead modal */
/* The score, criterion by criterion (owner's review, 2026-09-17). Every row
 * says which of three states it is in -- found, checked and nothing found, or
 * not checked yet -- why, and where the evidence is. The explanation is built
 * server-side by app/explain.py; this only draws it. */
const STATE_CLS = { found: "success", none: "", unchecked: "moved" };
function srcLinks(sources) {
  if (!sources || !sources.length) return "";
  return `<div class="crit-src">${sources.map((s) => s.url
    ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}${s.date ? " · " + esc(s.date) : ""} ${icon("external", 12)}</a>`
    : `<span>${esc(s.label)}${s.date ? " · " + esc(s.date) : ""}</span>`).join("")}</div>`;
}
function checkHint(c) {
  return c.check && c.check.manual
    ? `<div class="crit-check">${icon("user", 12)}<span>By hand: ${esc(c.check.manual)}</span></div>` : "";
}
function critRow(c, mod) {
  const amount = mod
    ? (c.state === "found" ? `<strong>${c.delta > 0 ? "+" : ""}${fmtScore(c.delta)}</strong>` : "—")
    : (c.state === "unchecked" ? "—" : `<strong>${fmtScore(c.earned)}</strong>`);
  return `<tr class="crit-${esc(c.state)}">
      <td><div class="crit-label">${esc(c.label)}</div><span class="lozenge state-inline ${STATE_CLS[c.state] || ""}">${esc(c.state_label)}</span><div class="why">${esc(c.why)}</div>${srcLinks(c.sources)}${checkHint(c)}</td>
      <td class="r num">${mod ? (c.max > 0 ? "+" : "") + fmtScore(c.max) : fmtScore(c.points)}</td>
      <td class="r num">${amount}</td>
      <td><span class="lozenge ${STATE_CLS[c.state] || ""}">${esc(c.state_label)}</span></td></tr>`;
}
function renderCriteria(ex) {
  const cov = ex.coverage || {};
  return `<table class="tbl crit-table"><thead><tr><th>Criterion</th><th class="r">Points</th><th class="r">Earned</th><th>State</th></tr></thead><tbody>` +
    (ex.criteria || []).map((c) => critRow(c, false)).join("") +
    `<tr class="crit-total"><td>Total</td><td class="r num">${fmtScore(cov.points_total)}</td><td class="r num"><strong>${fmtScore(cov.points_earned)}</strong></td><td></td></tr></tbody></table>` +
    ((ex.modifiers || []).length ? `<table class="tbl crit-table mod-table"><thead><tr><th>Adjustment</th><th class="r">Up to</th><th class="r">Applied</th><th>State</th></tr></thead><tbody>` +
      ex.modifiers.map((c) => critRow(c, true)).join("") + "</tbody></table>" : "");
}
function renderCoverage(ex) {
  const cov = ex.coverage || {}, total = +cov.points_total || 0, checked = +cov.points_checked || 0, earned = +cov.points_earned || 0;
  const pct = (n) => total ? Math.max(0, Math.min(100, n / total * 100)) : 0;
  return `<div class="coverage">
      <div class="coverage-bar" role="img" aria-label="${fmtScore(earned)} points earned, ${fmtScore(checked - earned)} checked with nothing found, ${fmtScore(total - checked)} not checked yet, of ${fmtScore(total)}">
        <span class="earned" style="width:${pct(earned)}%"></span><span class="checked" style="width:${pct(checked - earned)}%"></span></div>
      <div class="coverage-key small">
        <span><i class="k earned"></i>${fmtScore(earned)} earned</span>
        <span><i class="k checked"></i>${fmtScore(checked - earned)} checked, nothing found</span>
        <span><i class="k unchecked"></i>${fmtScore(total - checked)} not checked yet</span>
        <span class="muted">of ${fmtScore(total)} points</span></div>
      ${cov.stale ? `<p class="small warn-text" style="margin:4px 0 0">${esc(cov.stale)}</p>` : ""}
    </div>`;
}
/* The analysis: a verdict, one next step, strengths, gaps and risks. There is no
 * review checklist any more -- the owner, 2026-09-19: it "serves no point"; the
 * flow is leads shown, shortlisted, approved, sent. */
const VERDICT_TONE = { strong: "success", promising: "", weak: "warning", unreliable: "warning", hold: "danger" };
function renderAnalysis(ex) {
  const a = ex.analysis || {}, v = a.verdict || {};
  const list = (items, cls) => items && items.length
    ? `<ul class="plain-list ${cls || ""}">${items.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : `<p class="muted small">None.</p>`;
  const risks = (a.risks || []).length
    ? `<ul class="plain-list risks">${a.risks.map((r) => `<li class="risk ${esc(r.level)}">${icon(r.level === "info" ? "info" : "warn", 14)}<span><strong>${esc(r.title)}.</strong> ${esc(r.detail)}</span></li>`).join("")}</ul>`
    : `<p class="muted small">None found.</p>`;
  return `${v.title ? `<div class="section-msg ${VERDICT_TONE[v.tone] || ""}" style="margin-bottom:8px">${icon(v.tone === "hold" ? "alert" : v.tone === "strong" ? "checkCircle" : "info", 20)}<div><div class="title">${esc(v.title)}</div></div></div>` : ""}
    <div class="next-step">${icon("chevRight", 16)}<div><strong>Next step.</strong> ${esc(a.next_step || "")}</div></div>
    <div class="analysis-grid"><div><h4 class="sub-h">Strengths</h4>${list(a.strengths)}</div><div><h4 class="sub-h">Gaps</h4>${list(a.gaps)}</div></div>
    <h4 class="sub-h">Risks</h4>${risks}`;
}
/* Every way in: addresses best first (the first usable one is where drafts go),
 * junk shown struck through with the reason, then phone, people listed without
 * an address, website, channel and feed, and what was already tried. */
function renderContacts(d) {
  const cr = (d.explain || {}).contact_routes || { routes: [], tried: [] };
  const people = (d.contacts || []).map((c) => `<div class="contact-row ${c.usable ? "" : "retired"}">
      ${avatar(c.full_name, c.email)}
      <div class="contact-main"><div class="who">${esc(c.full_name || "No name published")}${c.drafts_use ? ` <span class="lozenge success" title="Drafts go to this address">Drafts use this</span>` : ""}</div>
        ${c.role_title ? `<div class="role">${esc(c.role_title)}</div>` : ""}
        <div class="mail">${c.usable ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : c.email ? `<s>${esc(c.email)}</s>` : `<span class="muted">No email on record</span>`}${c.kind === "shared" ? " · shared inbox" : c.kind === "low_value" ? ` · <span class="warn-text">rarely read for partnerships</span>` : ""}</div>
        ${!c.usable && c.email ? `<div class="role warn-text">Not used: ${esc(c.unusable_reason)}</div>` : ""}
        ${safeUrl(c.linkedin_url) ? `<div class="role"><a href="${esc(safeUrl(c.linkedin_url))}" target="_blank" rel="noopener">LinkedIn ${icon("external", 12)}</a></div>` : ""}
      </div></div>`).join("");
  const glyphs = { phone: "user", people: "users", website: "globe", channel: "play", podcast: "play", app: "link", social: "link" };
  const routes = (cr.routes || []).map((r) => {
    const body = r.people ? r.people.map((p) => `${esc(p.name)}${p.role ? ` <span class="muted">(${esc(p.role)})</span>` : ""}`).join(", ")
      : r.url ? `<a href="${esc(r.url)}"${String(r.url).startsWith("tel:") ? "" : ` target="_blank" rel="noopener"`}>${esc(r.value)}</a>` : esc(r.value || "");
    return `<li>${icon(glyphs[r.kind] || "link", 14)}<span><span class="muted">${esc(r.label)}:</span> ${body}</span></li>`;
  }).join("");
  return `${people || `<p class="muted small" style="margin:0 0 8px">No email address on record.</p>`}
    ${routes ? `<ul class="evidence-list routes">${routes}</ul>` : ""}
    ${(cr.tried || []).length ? `<p class="tried small muted">${cr.tried.map(esc).join(" ")}</p>` : ""}`;
}
async function openLead(id, opts) {
  // The dialog opens on the click, not when the server answers: on a cold
  // cloud instance the fetch can take seconds, and a click that shows nothing
  // reads as a click that did nothing.
  const quiet = !!(opts && opts.quiet);
  if (!quiet) {
    modal.open(`${modalHead(`${typeIcon("lead")}`)}
      <div class="modal-body single"><div class="modal-main"><div class="empty-state">
        <div class="spin" style="margin: 0 auto 12px"></div><p>Opening the lead</p></div></div></div>`,
      { label: "Opening the lead" });
  }
  let d;
  try { d = await api("/api/leads/" + id); }
  catch (e) {
    if (!quiet) modal.close(true);
    return toast("Could not load company: " + e.message, true);
  }
  const m = d.metadata || {}, research = m.p1_research || {};
  const score = +d.fit_score || 0;
  const decided = d.status === "shortlisted" || d.status === "rejected";
  const contacts = renderContacts(d);
  const pills = [sourceLozenge(d.source)];
  if (m.subtype) pills.push(`<span class="lozenge new">${esc(String(m.subtype).replace(/_/g, " "))}</span>`);
  // Details: only rows no other part of the dialog shows; the box appears only when it has some
  const wv = m.web_verification && typeof m.web_verification === "object" ? m.web_verification : null;
  const credits = Array.isArray(m.notable_credits) ? m.notable_credits.map((c) => typeof c === "string" ? c : (c && (c.title || c.name)) || "").filter(Boolean) : [];
  const det = [
    (m.hq_city || m.hq_state) ? `<dt>Location</dt><dd>${esc([m.hq_city, m.hq_state].filter(Boolean).join(", "))}</dd>` : "",
    uiDetails(d),
    wv && wv.note ? `<dt>Web check</dt><dd>${esc(wv.note)}${wv.date ? ` <span class="muted small">${esc(wv.date)}</span>` : ""}</dd>` : "",
    m.team_size_estimate ? `<dt>Team size (research)</dt><dd>${esc(m.team_size_estimate)}</dd>` : "",
    credits.length ? `<dt>Credits</dt><dd>${esc(credits.join("; "))}</dd>` : "",
  ].join("");
  (m.genres || []).slice(0, 4).forEach((g) => pills.push(`<span class="lozenge">${esc(g)}</span>`));
  (m.platform_relationships || []).slice(0, 4).forEach((g) => pills.push(`<span class="lozenge inprogress">${esc(g)}</span>`));

  modal.open(`
    ${modalHead(`${typeIcon("lead")}${statusLozenge(d.status)}`,
      d.domain ? `<a class="btn subtle" href="https://${esc(d.domain)}" target="_blank" rel="noopener">${icon("external", 16)} ${esc(d.domain)}</a>` : "")}
    <div class="modal-body">
      <div class="modal-main">
        ${(() => { const t = leadTitle(d); return personFirst() && hostOf(d) && !t.same
          ? `<h2 class="modal-title" style="margin-bottom:4px">${esc(t.title)}</h2><p class="subtle" style="margin:0 0 16px">Host of <strong>${esc(d.name)}</strong></p>`
          : `<h2 class="modal-title">${esc(d.name)}</h2>`; })()}
        <div class="pill-list" style="margin:-8px 0 20px">${pills.join("")}</div>

        ${d.explain ? `<div class="section"><h3>${icon("sparkle", 16)} Analysis</h3><div class="body">${renderAnalysis(d.explain)}</div></div>` : ""}

        ${d.explain && !(d.explain.criteria || []).length ? "" : `<div class="section"><h3>${icon("chart", 16)} Score breakdown <span class="pts ${ptsClass(score)}">${fmtScore(score)} / 100</span></h3>
          <div class="body">${d.explain ? renderCoverage(d.explain) + renderCriteria(d.explain) : ""}</div></div>`}

        ${research.ownership || research.caveats ? `<div class="section"><h3>${icon("book", 16)} Research notes</h3><div class="body">
          ${m.why_fit ? `<p><strong>Why it could fit.</strong> ${esc(m.why_fit)}</p>` : ""}
          ${research.ownership ? `<p><strong>Ownership.</strong> ${esc(research.ownership)}</p>` : ""}
          ${research.caveats ? `<p><strong>Caveats.</strong> ${esc(research.caveats)}</p>` : ""}</div></div>` : ""}

        ${d.status_reason ? `<div class="section"><h3>${icon("clock", 16)} Decision note</h3><div class="body">
          <p>${esc(d.status_reason)} <span class="muted small">(${fmtDate(d.status_changed_at)})</span></p></div></div>` : ""}
      </div>

      <div class="modal-side">
        <div class="reason-box" id="reasonBox" hidden>
          <label for="rejectReason">Reason for rejecting (kept with the decision)</label>
          <textarea id="rejectReason" rows="3" placeholder="e.g. service vendor, not an IP owner"></textarea>
          <div class="actions"><button class="btn subtle" id="reasonCancel">Cancel</button><button class="btn danger" id="reasonGo">Reject</button></div>
        </div>

        <div class="side-group"><div class="group-head">${icon("users", 16)} Contacts</div><div class="group-body">${contacts}</div></div>
        ${det ? `<div class="side-group"><div class="group-head">Details</div><div class="group-body"><dl class="details">${det}</dl></div></div>` : ""}
        <div class="timestamps">Created ${fmtDate(d.created_at)}<br>Updated ${fmtDate(d.updated_at || d.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      ${decided ? `<button class="btn subtle" data-decide="reset">Undo decision</button>` : ""}
      ${d.status !== "rejected" ? `<button class="btn subtle danger-text" data-decide="reject">Reject</button>` : ""}
      ${d.status !== "shortlisted" ? `<button class="btn primary" data-decide="shortlist">${icon("check", 16)} Shortlist</button>` : ""}
    </div>`, { label: d.name, onClose: () => { if (location.hash.startsWith("#lead/")) history.replaceState(null, "", "#" + currentView()); } });

  const root = $("#modalRoot");
  const showReason = () => { $("#reasonBox", root).hidden = false; $("#rejectReason", root).focus(); };
  $$("[data-decide]", root).forEach((b) => b.addEventListener("click", () => {
    const what = b.dataset.decide;
    if (what === "reject") return showReason();
    decide(id, what, "");
  }));
  $("#reasonCancel", root).addEventListener("click", () => { $("#reasonBox", root).hidden = true; });
  $("#reasonGo", root).addEventListener("click", () => decide(id, "reject", $("#rejectReason", root).value));
}

async function decide(id, decision, reason) {
  $$("#modalRoot .btn").forEach((b) => b.disabled = true);
  try {
    const r = await post("/api/leads/" + id + "/decision", { decision, reason: reason || "" });
    const s = leadStatus(r.status);
    flag(r.name, { desc: "Moved to " + s.label + (decision === "reset" ? " (decision undone)" : "")
      + (r.drafting ? ". Its email is being drafted: it appears in Outreach within minutes, for you to approve." : "")
      + (r.withdrawn ? ". Its waiting email was withdrawn." : "") });
    await openLead(id, { quiet: true }); // re-render with the new status; Undo stays reachable
    refreshCurrentView();
    refreshOutreachCount(true);
  } catch (e) {
    toast("Could not save: " + e.message, true);
    $$("#modalRoot .btn").forEach((b) => b.disabled = false);
  }
}
function refreshCurrentView() {
  const v = currentView();
  if (v === "board") loadBoard();
  if (v === "leads") loadLeads();
  if (v === "outreach") loadOutreach();
  if (v === "reports") loadReports();
  if (v === "universal") renderUniResults();
}

/* =========================================================== outreach */
/* Every reply sits in Replies with its mark (Positive, Negative, Needs triage); a positive one
   also moves the company to In conversation. Attention shows only when a send's outcome is
   unknown. (Positive, Negative and Cancelled folders went on 2026-09-19.) */
const FOLDERS = [["drafts", "Drafts"], ["outbox", "Approved"], ["sent", "Sent"], ["inbox", "Replies"], ["attention", "Attention"]];
function outreachPolicy() { return (state.segment && state.segment.outreach_policy) || {}; }
function batchOn() { return !!outreachPolicy().batch_approval; }
function followUpsOn() { return !!(outreachPolicy().follow_ups || {}).enabled; }
function stepLozenge(r) {
  const n = +r.sequence_step || 0;
  return n > 0 ? `<span class="lozenge new" title="Follow-up in the same thread">Follow-up ${n}</span> ` : "";
}
async function loadOutreach() {
  const o = state.outreach, token = ++o.token;
  let d;
  try { d = await api("/api/outreach?folder=" + encodeURIComponent(o.folder)); }
  catch (e) { return toast("Could not load outreach: " + e.message, true); }
  // can an approval go out from here? (a connected mailbox) -- it words what "approve" does
  api("/api/mailboxes").then((m) => { o.canSend = !!m.can_send; o.paused = m.paused || null; renderSendCounter(m); })
    .catch(() => { $("#sendCounter").hidden = true; });
  if (token !== o.token) return;
  o.rows = d.rows; o.counts = d.counts || {};
  const present = new Set(d.rows.map((r) => r.id));
  o.selected = new Set([...(o.selected || [])].filter((id) => present.has(id)));
  const batch = batchOn() && o.folder === "drafts" && d.rows.length > 0;
  $("#outreachTable").classList.toggle("batch", batch);
  $("#folderTabs").innerHTML = FOLDERS.filter(([key]) => key !== "attention" || o.counts.attention || o.folder === "attention").map(([key, label]) =>
    `<button class="tab ${key === o.folder ? "active" : ""}" role="tab" aria-selected="${key === o.folder}" data-f="${key}">${label}<span class="pts">${o.counts[key] || 0}</span></button>`).join("");
  $$("#folderTabs .tab").forEach((b) => b.addEventListener("click", () => {
    o.folder = b.dataset.f; o.selected.clear(); history.replaceState(null, "", "#outreach/" + o.folder); loadOutreach();
  }));
  $("#outreachBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr class="row-link" data-id="${esc(r.id)}" tabindex="0">
      <td class="sel-col"><input type="checkbox" data-sel="${esc(r.id)}" ${o.selected.has(r.id) ? "checked" : ""} aria-label="Select this draft"></td>
      <td><div class="primary-cell">${esc(r.company)}</div><div class="secondary">${esc(r.domain || "")}</div></td>
      <td>${r.contact_email ? `<span class="cell-person">${avatar(r.contact_name, r.contact_email)}<span><div>${esc(r.contact_name || "Unnamed")}</div><div class="secondary">${esc(r.contact_email)}</div></span></span>` : '<span class="muted">No address</span>'}</td>
      <td><div class="truncate" style="max-width:420px">${r.direction === "inbound" ? mailLozenge(r) + " " : ""}${stepLozenge(r)}${esc(r.subject || "(no subject)")}</div>${r.send_error ? `<div class="secondary" style="color:var(--text-danger)">${esc(r.send_error)}</div>` : ""}</td>
      <td class="secondary nowrap" title="${esc(fmtDate(r.sent_at || r.created_at))}">${rel(r.sent_at || r.created_at)}</td>
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="5">${o.folder === "drafts"
        ? "No drafts waiting. Shortlist a company on the board and its email is drafted here within minutes."
        : "Nothing in this folder yet."}</td></tr>`;
  delegateOpen("#outreachBody", openMessage, ".sel-col");
  $$("#outreachBody [data-sel]").forEach((c) => c.addEventListener("change", () => {
    if (c.checked) o.selected.add(c.dataset.sel); else o.selected.delete(c.dataset.sel);
    renderBatchBar();
  }));
  renderBatchBar();
  updateOutreachCount(o.counts);
}

function renderBatchBar() {
  const o = state.outreach, bar = $("#batchBar");
  const on = batchOn() && o.folder === "drafts" && o.rows.length > 0;
  bar.hidden = !on;
  if (!on) return;
  const n = o.selected.size, pol = outreachPolicy().batch_approval;
  const k = n ? Math.min(n, Math.max(pol.sample_min, Math.ceil(n * pol.sample_fraction))) : 0;
  bar.innerHTML = `<span>${n ? `<strong>${n}</strong> selected` : "Select drafts to approve them together."}</span>
    ${n ? `<span class="small muted">You'll read a random ${k} of them before they're approved.</span>` : ""}
    <span class="grow"></span>
    <button class="btn primary" id="batchGo" ${n ? "" : "disabled"}>${icon("check", 16)} Approve ${n || ""} selected</button>`;
  const all = $("#outreachSelAll"), cap = Math.min(o.rows.length, pol.max_batch || o.rows.length);
  all.checked = n > 0 && n >= cap;
  all.indeterminate = n > 0 && n < cap;
  all.setAttribute("aria-label", "Select the first " + cap + " drafts"); all.title = "Select the first " + cap + " drafts";
  $("#batchGo").addEventListener("click", startBatch);
}

async function startBatch() {
  const o = state.outreach, ids = [...o.selected];
  const btn = $("#batchGo");
  btn.classList.add("loading");
  let s;
  try { s = await post("/api/outreach/batch/sample", { ids }); }
  catch (e) { btn.classList.remove("loading"); return toast(e.message, true); }
  btn.classList.remove("loading");
  const byId = Object.fromEntries(o.rows.map((r) => [r.id, r]));
  const sample = s.sample.map((id) => byId[id]).filter(Boolean);
  const n = s.approvable.length;
  modal.open(`
    ${modalHead(`${icon("check", 16)}<span>Approve ${n} draft${n === 1 ? "" : "s"}</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <div class="section-msg">${icon("info", 24)}<div><div class="title">Read these ${sample.length} first</div>
        <div class="text">The server picked them at random from your selection. Approval unlocks when every one is ticked. Everything approved is sent exactly as written, and your name is recorded against the batch.${s.generated ? " This batch contains drafts whose opening line a model wrote, so the sample is larger." : ""}</div></div></div>
      ${s.skipped.length ? `<div class="section-msg warning">${icon("warn", 24)}<div><div class="title">${s.skipped.length} will not be approved</div>
        <div class="text">${s.skipped.map((x) => esc((byId[x.id] || {}).company || x.id) + ": " + esc(x.reason)).join("<br>")}</div></div></div>` : ""}
      ${sample.map((r, i) => `<div class="sample-item">
        <div class="sample-head"><span class="cell-person">${avatar(r.contact_name, r.contact_email)}<span>
          <div class="primary-cell">${stepLozenge(r)}${esc(r.subject || "(no subject)")}</div>
          <div class="secondary">${esc(r.company)} · ${esc(r.contact_email || "")}</div></span></span>
          <button class="btn subtle compact" data-read="${i}">Read</button></div>
        <div class="mail-body" data-body="${i}" hidden>${esc(r.body || "")}</div>
        <label class="check" style="margin-top:8px"><input type="checkbox" data-ok="${i}" disabled><span>I read this and it's right to send</span></label>
      </div>`).join("")}
    </div></div>
    <div class="modal-foot"><span class="left" id="batchLeft">0 of ${sample.length} checked</span>
      <button class="btn subtle" data-close>Cancel</button>
      <button class="btn primary" id="batchApprove" disabled>${icon("check", 16)} Approve ${n}</button></div>`,
    { label: "Approve drafts" });
  const root = $("#modalRoot");
  const sync = () => {
    const done = $$("[data-ok]", root).filter((c) => c.checked).length;
    $("#batchLeft", root).textContent = `${done} of ${sample.length} checked`;
    $("#batchApprove", root).disabled = done !== sample.length;
  };
  $$("[data-read]", root).forEach((b) => b.addEventListener("click", () => {
    const i = b.dataset.read, body = $(`[data-body="${i}"]`, root);
    body.hidden = !body.hidden;
    $(`[data-ok="${i}"]`, root).disabled = false;        // a tick is only possible after opening it
    b.textContent = body.hidden ? "Read" : "Hide";
  }));
  $$("[data-ok]", root).forEach((c) => c.addEventListener("change", sync));
  $("#batchApprove", root).addEventListener("click", async (e) => {
    const b = e.currentTarget;
    b.classList.add("loading"); b.disabled = true;
    try {
      const r = await post("/api/outreach/batch/approve", { ids: s.approvable, sample: s.sample, token: s.token });
      modal.close(true);
      o.selected.clear();
      flag("Approved " + r.approved + " draft" + (r.approved === 1 ? "" : "s"), {
        desc: r.skipped.length ? r.skipped.length + " skipped: " + [...new Set(r.skipped.map((x) => x.reason))].join("; ")
                               : r.paused ? "They wait in Approved: sending is paused for this project."
                               : (r.can_send ? "They go out within minutes, inside today's sending limit."
                                             : "They go out as soon as a mailbox is connected."),
        kind: r.skipped.length ? "info" : "" });
      await loadOutreach();
    } catch (err) { toast(err.message, true); b.classList.remove("loading"); b.disabled = false; }
  });
}

/* ---------------------------------------------------------------- footer
   The sign-off, the postal address and the opt-out are the same on every
   email this project sends, so they are one setting rather than four lines
   repeated in each template. The server refuses a footer with no address or
   no way out -- both are required of commercial email, and both are what
   keep a sending domain alive. */
function footerPreview(text, sender) {
  const vals = { sender_name: sender.name, sender_title: sender.title, postal_address: sender.postal_address };
  let out = text || "";
  Object.keys(vals).forEach((k) => { out = out.split("{{" + k + "}}").join(vals[k] || ""); });
  return out;
}

async function openFooter() {
  let d;
  try { d = await api("/api/outreach/footer"); }
  catch (e) { return toast("Could not load the footer: " + e.message, true); }
  const pending = d.drafts_pending || 0;
  modal.open(`
    ${modalHead(`${typeIcon("mail")}<span class="key">Footer</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <h2 class="modal-title" style="font-size:20px;line-height:24px;margin-bottom:4px">The end of every email</h2>
      <p class="sub" style="margin-bottom:20px">Your sign-off, your postal address and the line that lets someone out. It goes on the opener and on every follow-up, so it is set once here rather than inside each template.</p>
      <div class="footer-grid">
        <div class="field"><label for="fName">Your name</label><input id="fName" type="text" value="${esc(d.sender.name)}" autofocus></div>
        <div class="field"><label for="fTitle">Your title</label><input id="fTitle" type="text" value="${esc(d.sender.title)}"></div>
      </div>
      <div class="field" style="margin-top:12px"><label for="fPostal">Postal address</label>
        <input id="fPostal" type="text" value="${esc(d.sender.postal_address)}" placeholder="Street, city, postcode, country">
        <div class="help">Commercial email has to carry a real postal address. A missing one is what gets a sending domain blocked.</div></div>
      <div class="field" style="margin-top:16px"><label for="fText">Footer</label>
        <textarea id="fText" style="min-height:140px">${esc(d.text)}</textarea>
        <div class="help">Fields: ${d.fields.map((f) => `<code>{{${esc(f)}}}</code>`).join(" ")}</div></div>
      <div class="field" style="margin-top:16px"><label>How it will read</label><div class="mail-body" id="fPreview"></div></div>
      <div id="fProblems"></div>
      ${pending ? `<div class="help" style="margin-top:12px">${pending === 1 ? "The draft waiting gets" : "The " + pending + " drafts waiting get"} this footer too. Only the footer is replaced; anything written above it stays.</div>` : ""}
    </div></div>
    <div class="modal-foot">
      <span class="left">Emails already sent are not touched.</span>
      <button class="btn" data-close>Cancel</button>
      <button class="btn primary" id="fSave">${icon("check", 16)} Save footer</button>
    </div>`, { label: "Email footer" });

  const root = $("#modalRoot");
  const sender = () => ({ name: $("#fName", root).value.trim(), title: $("#fTitle", root).value.trim(),
                          postal_address: $("#fPostal", root).value.trim() });
  const paint = () => { $("#fPreview", root).textContent = footerPreview($("#fText", root).value, sender()); };
  ["fName", "fTitle", "fPostal", "fText"].forEach((id) =>
    $("#" + id, root).addEventListener("input", paint));
  paint();
  if (d.problems && d.problems.length) showFooterProblems(root, d.problems);
  $("#fSave", root).addEventListener("click", async (e) => {
    const b = e.currentTarget;
    b.classList.add("loading"); $$("#modalRoot .btn").forEach((x) => x.disabled = true);
    $("#fProblems", root).innerHTML = "";
    try {
      const res = await post("/api/outreach/footer", { text: $("#fText", root).value, sender: sender() });
      const bits = [];
      if (res.rebuilt) bits.push(res.rebuilt + " draft" + (res.rebuilt === 1 ? "" : "s") + " rewritten");
      if (res.left_alone) bits.push(res.left_alone + " left alone (they do not end with the old footer)");
      flag("Footer saved", { desc: bits.join(", ") || "Every email from now on ends with it." });
      modal.close(true);
      if (currentView() === "outreach") await loadOutreach();
    } catch (err) {
      showFooterProblems(root, String(err.message).split("\n").filter(Boolean));
      $$("#modalRoot .btn").forEach((x) => x.disabled = false); b.classList.remove("loading");
    }
  });
}

function showFooterProblems(root, problems) {
  $("#fProblems", root).innerHTML = `<div class="footer-problems">${icon("alert", 16)}<div>${
    problems.map((p) => `<div>${esc(p)}</div>`).join("")}</div></div>`;
}

function openMessage(id) {
  const o = state.outreach, r = o.rows.find((x) => x.id === id);
  if (!r) return;
  const isDraft = r.status === "drafted", isReply = r.direction === "inbound";
  const step = +r.sequence_step || 0;
  // ending a live thread by hand, or dismissing a follow-up draft; an unsent opener has no thread yet
  const canStop = followUpsOn() && !isReply && !r.stopped_reason && (r.status === "sent" || (step > 0 && r.status === "drafted"));
  modal.open(`
    ${modalHead(`${typeIcon("mail")}${stepLozenge(r)}${mailLozenge(r)}`,
      `<button class="btn subtle" id="msgOpenLead">${icon("bookmark", 14)} Open lead</button>`)}
    <div class="modal-body">
      <div class="modal-main">
        ${isDraft
          ? `<div class="field" style="margin-bottom:12px"><label for="draftSubject">Subject</label><input id="draftSubject" type="text" value="${esc(r.subject || "")}" autofocus></div>
             <div class="field"><label for="draftBody">Body</label><textarea id="draftBody" style="min-height:300px">${esc(r.body || "")}</textarea>
             <div class="help">Edits are saved when you approve. Approving sends it: a person read exactly this text and stands behind it.</div></div>`
          : `<h2 class="modal-title" style="font-size:20px;line-height:24px">${esc(r.subject || "(no subject)")}</h2>
             <div class="mail-body">${esc(r.body || "")}</div>
             ${r.triage_reason ? `<div class="section" style="margin-top:20px"><h3>${icon("sparkle", 16)} Triage note</h3><div class="body">${esc(r.triage_reason)}</div></div>` : ""}`}
      </div>
      <div class="modal-side">
        <div class="side-group"><div class="group-head">Details</div><div class="group-body">
          <dl class="details">
            <dt>Company</dt><dd>${esc(r.company)}${r.domain ? `<div class="small muted">${esc(r.domain)}</div>` : ""}</dd>
            <dt>${isReply ? "From" : "To"}</dt><dd>${r.contact_email ? `<div class="person">${avatar(r.contact_name, r.contact_email)}<div><div class="who">${esc(r.contact_name || "Unnamed")}</div><div class="mail"><a href="mailto:${esc(r.contact_email)}">${esc(r.contact_email)}</a></div></div></div>` : '<span class="muted">No address</span>'}</dd>
            ${!isReply && (r.sender_address || r.sender_mailbox) ? `<dt>Sent from</dt><dd>${esc(r.sender_address || "")}<div class="small muted mono">${esc(r.sender_mailbox || "")}</div></dd>` : ""}
            ${r.approved_by ? `<dt>Approved</dt><dd>${esc(r.approved_by)}<div class="small muted">${esc(r.approval_mode === "batch" ? (r.spot_checked ? "in a batch, spot-checked" : "in a batch") : "individually")} · ${esc(fmtDate(r.approved_at))}</div></dd>` : ""}
            ${r.stopped_reason ? `<dt>Stopped</dt><dd>${esc(r.stopped_reason)}</dd>` : ""}
            ${r.send_error ? `<dt>Send error</dt><dd style="color:var(--text-danger)">${esc(r.send_error)}</dd>` : ""}
            ${r.generated_hook ? `<dt>Written by a model</dt><dd class="small muted">Part of this email was written by a model from this lead's own evidence. Every number in it was checked against that evidence.</dd>` : ""}
          </dl></div></div>
        <div class="timestamps">${r.sent_at ? "Sent " + fmtDate(r.sent_at) + "<br>" : ""}Created ${fmtDate(r.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      <span class="left">${r.status === "approved" ? (o.paused ? "Approved. It waits here: sending is paused for this project." : o.canSend === false ? "Approved. It goes out as soon as a mailbox is connected." : "Approved. It goes out within minutes, inside today's sending limit.") : ""}</span>
      ${canStop ? `<button class="btn subtle danger-text" data-act="stop_sequence" title="No further follow-ups for this company">Stop follow-ups</button>` : ""}
      ${isDraft ? `<button class="btn primary" data-act="approve">${icon("send", 16)} Approve and send</button>` : ""}
      ${r.status === "approved" ? `<button class="btn" data-act="cancel">Withdraw approval</button>` : ""}
      ${isReply && r.status !== "cancelled" ? `<button class="btn" data-act="mark_negative">Mark negative</button><button class="btn primary" data-act="mark_positive">${icon("check", 16)} Mark positive</button>` : ""}
    </div>`, { label: r.subject || "Message" });

  const root = $("#modalRoot");
  $("#msgOpenLead", root).addEventListener("click", () => go("lead/" + r.entity_id));
  $$("[data-act]", root).forEach((b) => b.addEventListener("click", async () => {
    if (o.busy) return;                       // double-click guard (review finding)
    o.busy = true;
    $$("#modalRoot .btn").forEach((x) => x.disabled = true);
    b.classList.add("loading");
    try {
      if (b.dataset.act === "approve") {
        await api("/api/outreach/" + id, { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: $("#draftSubject", root).value, body: $("#draftBody", root).value }) });
      }
      const res = await post("/api/outreach/" + id + "/decision", { action: b.dataset.act });
      const msg = { approve: res.can_send ? "Approved: sending" : "Approved", cancel: "Approval withdrawn", mark_positive: "Marked positive",
        mark_negative: "Marked negative", stop_sequence: "Follow-ups stopped" }[b.dataset.act];
      const desc = b.dataset.act === "approve"
        ? r.company + (res.paused ? ": it waits in Approved, because sending is paused for this project."
                       : res.can_send ? ": it goes out within minutes." : ": it goes out as soon as a mailbox is connected.")
        : b.dataset.act === "stop_sequence"
        ? (res.cancelled ? res.cancelled + " pending follow-up" + (res.cancelled === 1 ? "" : "s") + " cancelled." : "No further follow-ups will be drafted.")
        : res.entity_promoted === false ? "Reply recorded; the company was not in a state that could be promoted." : r.company;
      flag(msg, { desc });
      modal.close(true);
      await loadOutreach();
    } catch (e) { toast(e.message, true); $$("#modalRoot .btn").forEach((x) => x.disabled = false); b.classList.remove("loading"); }
    finally { o.busy = false; }
  }));
}

/* =========================================================== reports */
async function loadReports() {
  let s, k;
  try { [s, k] = await Promise.all([api("/api/stats"), api("/api/kpis").catch(() => ({}))]); }
  catch (e) { return toast("Could not load reports: " + e.message, true); }
  const f = k.funnel || {}, o = k.outreach || {};

  // status donut: reserved status colours, a legend with counts (the table view)
  // Colours in ring order, each adjacent chromatic pair validated for CVD and
  // normal-vision separation (dataviz validator, 2026-09-04). The two neutral
  // states are achromatic on purpose; the legend carries their identity.
  const segs = [
    ["To review", f.open_pool ?? s.open_pool, "var(--chart-review)"],
    ["Shortlisted", f.shortlisted ?? s.shortlisted, "var(--chart-success)"],
    ["Contacted", f.contacted ?? 0, "var(--chart-brand)"],
    ["In conversation", f.in_conversation ?? 0, "var(--chart-amber)"],
    ["Rejected", f.rejected ?? s.rejected, "var(--chart-danger)"],
    ["Archived", f.archived_out_of_scope ?? 0, "var(--chart-archived)"],
  ].map(([label, value, color]) => ({ label, value: +value || 0, color }));
  const total = segs.reduce((x, y) => x + y.value, 0);
  const r = 66, c = 84, circ = 2 * Math.PI * r;
  let acc = 0;
  const arcs = segs.filter((x) => x.value > 0).map((x) => {
    const len = x.value / total * circ, start = acc; acc += len;
    const dash = Math.max(len - 2, 0.5);
    return `<circle r="${r}" cx="${c}" cy="${c}" fill="none" style="stroke:${x.color}" stroke-width="18"
      stroke-dasharray="${dash.toFixed(2)} ${(circ - dash).toFixed(2)}" stroke-dashoffset="${(circ / 4 - start).toFixed(2)}"><title>${esc(x.label)}: ${x.value}</title></circle>`;
  });
  $("#donut").innerHTML = `<svg viewBox="0 0 168 168" width="168" height="168" role="img" aria-label="Status overview: ${segs.map((x) => x.label + " " + x.value).join(", ")}">
    ${total ? arcs.join("") : `<circle r="${r}" cx="${c}" cy="${c}" fill="none" style="stroke:var(--chart-muted)" stroke-width="18"/>`}</svg>
    <div class="center"><div class="n">${total}</div><div class="k">${esc(segUi().entity_plural || "companies")}</div></div>`;
  $("#donutLegend").innerHTML = segs.map((x) => `<li><span class="sw" style="background:${x.color}"></span><span>${esc(x.label)}</span><span class="v">${x.value}${total ? ` · ${Math.round(x.value / total * 100)}%` : ""}</span></li>`).join("");

  // outreach results: nothing to measure until the first email goes out
  const pct = (v) => v == null ? "—" : v + "%";
  $("#kpiTiles").innerHTML = +o.openers_sent > 0 ? [
    ["Contacted, 7 days", o.sent_last_7d ?? 0, "companies, not counting follow-ups", true],
    ["Reply rate", pct(o.reply_rate_pct), `${o.replies ?? 0} replies`, true],
    ["Positive rate", pct(o.positive_rate_pct), `${o.positive_replies ?? 0} positive`, true],
    followUpsOn() && ["Follow-ups sent", o.followups_sent ?? 0, "in the same thread", false],
  ].filter(Boolean).map(([kk, n, d, hi]) => `<div class="tile ${hi ? "hi" : ""}" style="padding:12px 16px"><div class="n" style="font-size:20px">${esc(n)}</div><div class="k">${esc(kk)}</div>${d ? `<div class="d">${esc(d)}</div>` : ""}</div>`).join("")
    : `<p class="muted">Nothing sent yet.</p>`;

  // by source: only where a project has more than one to compare
  const src = k.by_source || [];
  $("#sourcePanel").hidden = src.length < 2;
  $("#sourceTable").innerHTML = `<thead><tr><th>Source</th><th class="r">Found</th><th class="r">Contactable</th><th class="r">Shortlisted</th></tr></thead><tbody>` +
    src.map((x) => `<tr><td>${sourceLozenge(x.source)}</td><td class="r num">${x.found}</td><td class="r num">${x.contactable}</td>
      <td class="r num">${x.approved}</td></tr>`).join("") + "</tbody>";
}

/* ================================================================ ops */
/* What runs by itself, and how its last run went. Days use the scheduler's own numbering
   (Python's weekday(): Monday is 0) -- the page used to show every day one early. */
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
async function loadSchedule() {
  let d;
  try { d = await api("/api/schedule"); } catch (e) { return; }
  const last = d.last || {};
  const hm = (s) => `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
  const rows = (d.schedule || []).filter((s) => s.enabled !== false).map((s) => ({
    name: s.name, run: last[s.pipeline],
    when: s.dow === "*" || s.dow == null ? `Daily ${hm(s)}` : `${DOW[s.dow]} ${hm(s)}` }));
  rows.push({ name: "drafting and sending", when: "Every 15 minutes, when there is work", run: last.outreach });
  const result = (r) => !r ? '<span class="muted">Not run yet</span>'
    : r.status === "running" ? '<span class="lozenge inprogress">Running</span>'
    : r.status === "failed" ? `<span class="lozenge removed" title="${esc(r.failed_detail || r.detail || "")}">Failed${r.failed_step ? " at " + esc(r.failed_step) : ""}</span>`
    : r.status === "skipped" ? '<span class="lozenge moved">Skipped</span>' : '<span class="lozenge success">OK</span>';
  $("#runsTable").innerHTML = `<thead><tr><th>What</th><th>When</th><th>Last run</th><th>Result</th></tr></thead><tbody>` +
    rows.map((x) => `<tr><td class="primary-cell">${esc(x.name.charAt(0).toUpperCase() + x.name.slice(1))}</td><td>${esc(x.when)}</td>
      <td class="secondary nowrap" title="${esc(x.run ? fmtDate(x.run.started_at) : "")}">${x.run ? rel(x.run.started_at) + (x.run.trigger === "manual" ? " (by hand)" : "") : "—"}</td>
      <td>${result(x.run)}</td></tr>`).join("") + "</tbody>";
  $("#runsSub").textContent = "What runs by itself, and how its last run went. Times are UTC." + (d.webhook_configured ? ""
    : " Failures show only here: set ALERT_WEBHOOK_URL on the server to get a Slack or Discord ping.");
}

/* The day's sending counter on the Outreach page (owner, 2026-09-21): how many emails left
 * today out of the daily limit, and when the count starts again. The day is the database's,
 * UTC, so it resets at midnight UTC -- shown in the viewer's own clock (05:30 in India). */
function renderSendCounter(m) {
  const el = $("#sendCounter");
  if (!m || m.limit_today == null) { el.hidden = true; return; }
  const resets = m.resets_at ? new Date(m.resets_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  const sent = m.sent_today || 0, limit = m.limit_today || 0;
  let text, tone = "", title = "Emails this project has sent today, out of its daily limit. The count starts again at " + resets + ".";
  if (m.paused) {
    text = "Sending paused"; tone = "paused";
    title = "Approved emails wait in Approved: " + m.paused;
  } else if (sent >= limit) {
    text = `${sent} of ${limit} sent today`; tone = "full";
    title = "Today's limit is reached. Approved emails go out after " + resets + ".";
  } else {
    text = `${sent} of ${limit} sent today`;
    if (!m.can_send) { tone = "idle"; title += " No mailbox is connected on the server yet, so nothing goes out."; }
  }
  el.className = "send-counter" + (tone ? " " + tone : "");
  el.innerHTML = `<b>${esc(text)}</b>${m.paused ? "" : `<span class="muted"> · resets ${esc(resets)}</span>`}`;
  el.title = title;
  el.hidden = false;
}

/* Mailbox rotation and warm-up (LCX). With one mailbox there is nothing to show that
   Outreach does not already say (whether an approval can go out). */
async function loadMailboxes() {
  let d;
  try { d = await api("/api/mailboxes"); } catch (e) { $("#mailboxPanel").hidden = true; return; }
  $("#mailboxPanel").hidden = !d.rotation;
  if (!d.rotation) return;
  const today = d.mailboxes.reduce((a, m) => a + (m.cap_today || 0), 0);
  $("#mailboxSub").textContent = `Openers go to the mailbox with the most room today; follow-ups leave from the mailbox that sent the opener. Up to ${Math.min(today, d.segment_cap)} emails today (ceiling ${d.segment_cap}).`;
  $("#mailboxTable").innerHTML = `<thead><tr><th>Mailbox</th><th>Address</th><th>Warm-up</th><th class="r">Cap today</th><th class="r">Sent today</th><th>Room left</th></tr></thead><tbody>` +
    d.mailboxes.map((m) => {
      const warm = !m.enabled ? `<span class="lozenge">Disabled</span>`
        : !m.warmup ? `<span class="lozenge success">Warm</span>`
        : m.warmup_day ? (m.cap_today >= m.daily_cap ? `<span class="lozenge success">Warm</span>` : `<span class="lozenge inprogress">Day ${m.warmup_day}</span>`)
        : `<span class="lozenge moved">Not started</span>`;
      const pct = m.cap_today ? Math.round(100 * m.remaining / m.cap_today) : 0;
      return `<tr><td class="mono primary-cell">${esc(m.key)}</td>
        <td>${m.connected ? esc(m.last_address || "Connected") : `<span class="muted small">Not connected: set <span class="mono">${esc(m.email_env)}</span>, then <span class="mono">outreach.py auth --mailbox ${esc(m.key)}</span></span>`}</td>
        <td>${warm}${m.warmup ? `<div class="secondary">${m.warmup.start_cap} a day, +${m.warmup.step} every ${m.warmup.every_days} days, up to ${m.daily_cap}</div>` : ""}</td>
        <td class="r num">${m.cap_today}</td><td class="r num">${m.sent_today}</td>
        <td><div class="bar-cell"><div class="track"><div class="fill" style="width:${pct}%"></div></div><span class="num small">${m.remaining}</span></div></td></tr>`;
    }).join("") + "</tbody>";
}

async function loadOps() {
  loadSchedule();
  loadMailboxes();
  let d;
  try { d = await api("/api/ops"); } catch (e) { return; }
  if (d.busy && !state.ops.timer) watchOps(d.busy, d.label);   // a job holds the slot: show its log
}

/* The log of the job holding the single slot. Stop is there for a job that hangs (it would
   block drafting and sending); a send only stops by finishing, or its email stays 'sending'. */
async function watchOps(key, label) {
  $("#logPanel").hidden = false;
  $("#logTitle").textContent = "Log: " + (label || key);
  $("#logStop").dataset.key = key;
  clearInterval(state.ops.timer);
  const tick = async () => {
    try {
      const d = await api("/api/ops/" + key + "/log?tail=150");
      const pre = $("#opsLog");
      pre.textContent = d.lines.join("\n") || "(no output yet)";
      pre.scrollTop = pre.scrollHeight;
      $("#logStop").hidden = d.status !== "running" || key === "send_outreach";
      if (d.status !== "running") {
        clearInterval(state.ops.timer); state.ops.timer = null;
        if (currentView() === "ops") loadOps();              // the next step of a refresh, if one is running
      }
    } catch (e) { clearInterval(state.ops.timer); state.ops.timer = null; }
  };
  await tick();
  state.ops.timer = setInterval(tick, 3000);
}

function bindOps() {
  $("#runRefresh").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.classList.add("loading");
    try {
      await post("/api/schedule/run/weekly_refresh");
      flag("Weekly refresh started", { desc: "Its steps run one at a time; the log streams below." });
      setTimeout(loadOps, 1500);
    } catch (err) { toast(err.message, true); }
    btn.disabled = false; btn.classList.remove("loading");
  });
  $("#logStop").addEventListener("click", async (e) => {
    try { await post("/api/ops/" + e.currentTarget.dataset.key + "/stop"); flag("Stopping " + $("#logTitle").textContent.replace(/^Log: /, "")); }
    catch (err) { toast(err.message, true); }
  });
  $("#logClose").addEventListener("click", () => { $("#logPanel").hidden = true; });
  $("#footerBtn").addEventListener("click", openFooter);
  $("#outreachSelAll").addEventListener("change", (e) => {
    const o = state.outreach, max = (outreachPolicy().batch_approval || {}).max_batch || o.rows.length;
    o.selected = new Set(e.target.checked ? o.rows.slice(0, max).map((r) => r.id) : []);   // a batch is at most max_batch
    $$("#outreachBody [data-sel]").forEach((c) => { c.checked = o.selected.has(c.dataset.sel); });
    renderBatchBar();
  });
}

/* ========================================================== universal */
/* The Universal project's page: Apollo's people and company search (2026-09-19).
 * The filters are drawn from the server's list (tools/apollo.py FILTERS), so the
 * page offers exactly what Apollo's API accepts, under the names Apollo's own app
 * gives them. Searching people costs nothing; saving a person reveals them and
 * costs a credit, so a save that costs credits is always confirmed first. */
const UNI_STORE = "tvf_uni_v1";
state.uni = {
  kind: "people", q: { people: "", companies: "" }, filters: { people: {}, companies: {} },
  page: 1, perPage: 25, perCompany: "", rows: [], total: 0, totalPages: 0, searched: false, resultKind: null,
  lastFilters: {}, selected: new Map(), picked: {}, open: {}, schema: [], status: null,
  maxReveal: 100, token: 0, bound: false,
};
function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : ""; }
function uniPersist() {
  const u = state.uni;
  try { localStorage.setItem(UNI_STORE, JSON.stringify({ kind: u.kind, q: u.q, filters: u.filters, picked: u.picked })); } catch (e) {}
}
function uniRestore() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(UNI_STORE) || "null"); } catch (e) {}
  if (!s || typeof s !== "object") return;
  const u = state.uni;
  if (s.kind === "people" || s.kind === "companies") u.kind = s.kind;
  if (s.q && typeof s.q === "object") u.q = { people: s.q.people || "", companies: s.q.companies || "" };
  if (s.filters && typeof s.filters === "object") u.filters = { people: s.filters.people || {}, companies: s.filters.companies || {} };
  if (s.picked && typeof s.picked === "object") u.picked = s.picked;
}
function uniConnected() { const s = state.uni.status; return !!(s && s.key_set && s.connected); }

async function loadUniversal() {
  const u = state.uni;
  if (!u.bound) { uniRestore(); bindUniversal(); u.bound = true; }
  await uniLoadStatus();
  renderUniTabs(); renderUniFilters(); renderUniResults();
}
async function uniLoadStatus() {
  const u = state.uni;
  try {
    const d = await api("/api/universal/status");
    u.status = d.apollo; u.schema = d.filters || [];
    u.maxReveal = d.max_reveal_per_save || 100; u.endpoints = d.endpoints || [];
  } catch (e) {
    u.status = { key_set: false, connected: false, problems: [e.message] };
  }
  renderUniStatus();
}
function renderUniStatus() {
  const u = state.uni, s = u.status || {};
  const left = s.credits && s.credits.lead_credits_left != null ? (+s.credits.lead_credits_left).toLocaleString() : null;
  // whether Apollo is connected is the setup box's to say; the header keeps the one number that costs money
  $("#uniStatus").innerHTML = uniConnected() && left != null
    ? `<span class="uni-credits" title="Lead credits left this billing cycle">${esc(left)} credits left</span>` : "";
  const probs = (s.problems || []).map((p) => `<li>${esc(p)}</li>`).join("");
  const eps = (u.endpoints || []).map((e) => `<code>${esc(e.replace(/^api\/v1\//, ""))}</code>`).join(", ");
  const setup = $("#uniSetup");
  if (!s.key_set || !s.connected) {
    setup.innerHTML = `<div class="section-msg warning">${icon("warn", 24)}<div>
      <div class="title">${s.key_set ? "Apollo refused the key" : "Connect Apollo to search"}</div>
      <div class="text"><ol class="uni-steps">
        <li>In Apollo, open <strong>Settings → Integrations → API Keys → Create new key</strong>. Tick ${eps || "the search, reveal and usage endpoints"}, or turn on <strong>Set as master key</strong>.</li>
        <li>Put the key in this project's <code>.env</code> as <code>APOLLO_API_KEY=…</code>, and in Render → Environment as <code>APOLLO_API_KEY</code> for the live site. Never paste it into a chat or an email.</li>
        <li>Reload this page.</li></ol>
        ${probs ? `<ul class="uni-problems">${probs}</ul>` : ""}</div></div></div>`;
  } else if (probs) {
    setup.innerHTML = `<div class="section-msg">${icon("info", 24)}<div><div class="title">Connected, with a gap</div><div class="text"><ul class="uni-problems">${probs}</ul></div></div></div>`;
  } else {
    setup.innerHTML = "";
  }
  $("#uniGo").disabled = !uniConnected();
}
function renderUniTabs() {
  const u = state.uni;
  $$("#uniTabs [data-kind]").forEach((b) => { const on = b.dataset.kind === u.kind; b.classList.toggle("active", on); b.setAttribute("aria-selected", String(on)); });
  $("#uniQuery").value = u.q[u.kind] || "";
  $("#uniQuery").placeholder = u.kind === "people" ? "Search people: any words on their Apollo profile" : "Search companies by name";
  $("#uniCost").innerHTML = icon("info", 14) + (u.kind === "people"
    ? `<span>Searching people is free. Saving a person reveals their full name, work email and LinkedIn: <strong>1 Apollo credit each</strong>.</span>`
    : `<span>Each page of company results costs <strong>1 Apollo credit</strong>. Saving companies is free.</span>`);
  $("#uniGo").textContent = u.kind === "people" ? "Search" : "Search · 1 credit";
}

/* ---- the filter panel ---- */
function uniDefs() {
  // "include similar titles" only means something once there is a title to widen
  const u = state.uni, v = u.filters[u.kind] || {};
  return (u.schema || []).filter((f) => f.for.includes(u.kind) && f.group !== "Search"
    && (f.key !== "include_similar_titles" || (v.person_titles || []).length));
}
function uniActive(f, v) {
  if (f.type === "bool") return v === false;               // the default is on; only "off" narrows a search
  if (v == null || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.values(v).some((x) => x != null && x !== "");
  return true;
}
function uniChip(label, key, i) {
  return `<span class="chip">${esc(label)}<button type="button" class="chip-x" data-remove="${esc(key)}" data-i="${i}" aria-label="Remove ${esc(label)}">${icon("x", 12)}</button></span>`;
}
function uniControl(f, v) {
  const id = "uf_" + f.key, help = f.help ? `<div class="help">${esc(f.help)}</div>` : "";
  if (f.type === "text") return `<div class="field"><label for="${id}">${esc(f.label)}</label><input id="${id}" class="compact" type="text" data-f="${esc(f.key)}" value="${esc(v || "")}">${help}</div>`;
  if (f.type === "list") return `<div class="field"><label for="${id}">${esc(f.label)}</label>
    <div class="chip-input">${(v || []).map((x, i) => uniChip(x, f.key, i)).join("")}<input id="${id}" type="text" data-add="${esc(f.key)}" placeholder="${(v || []).length ? "Add another" : "Type, then Enter"}" autocomplete="off"></div>${help}</div>`;
  if (f.type === "ids") return `<div class="field"><span class="label">${esc(f.label)}</span>
    <div class="chip-input static">${(v || []).length ? v.map((x, i) => uniChip(state.uni.picked[x] || x, f.key, i)).join("") : `<span class="muted small">None picked yet</span>`}</div>${help}</div>`;
  if (f.type === "choice") return `<fieldset class="field"><legend>${esc(f.label)}</legend><div class="check-grid">${f.options.map(([val, label]) =>
    `<label class="check"><input type="checkbox" data-choice="${esc(f.key)}" value="${esc(val)}" ${(v || []).includes(val) ? "checked" : ""}><span>${esc(label)}</span></label>`).join("")}</div>${help}</fieldset>`;
  if (f.type === "bool") return `<label class="check uni-bool"><input type="checkbox" data-bool="${esc(f.key)}" ${v === false ? "" : "checked"}><span>${esc(f.label)}</span></label>`;
  if (f.type === "window") return `<div class="field"><label for="${id}">${esc(f.label)}</label><select id="${id}" class="compact" data-f="${esc(f.key)}"><option value="">Choose a time frame</option>${f.options.map(([val, label]) =>
    `<option value="${esc(val)}" ${String(v) === val ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>${help}</div>`;
  if (f.type === "range" || f.type === "daterange") {
    const t = f.type === "range" ? "number" : "date", o = v || {};
    const lo = o.min == null ? "" : o.min, hi = o.max == null ? "" : o.max;
    return `<div class="field"><span class="label">${esc(f.label)}</span><div class="range-row">
      <input class="compact" type="${t}" data-range="${esc(f.key)}" data-end="min" value="${esc(lo)}" placeholder="Min" aria-label="${esc(f.label)}, minimum">
      <span class="muted">to</span>
      <input class="compact" type="${t}" data-range="${esc(f.key)}" data-end="max" value="${esc(hi)}" placeholder="Max" aria-label="${esc(f.label)}, maximum"></div>${help}</div>`;
  }
  return "";
}
function renderUniFilters() {
  const u = state.uni, vals = u.filters[u.kind], defs = uniDefs(), groups = [];
  defs.forEach((f) => { let g = groups.find((x) => x.name === f.group); if (!g) groups.push(g = { name: f.group, items: [] }); g.items.push(f); });
  const n = defs.filter((f) => uniActive(f, vals[f.key])).length;
  $("#uniFilters").innerHTML = `<div class="uni-filters-head"><strong>Filters</strong><span class="pts ${n ? "mid" : ""}" id="uniFilterCount">${n}</span><span class="grow"></span>
      <button class="btn subtle compact" id="uniClear" ${n ? "" : "hidden"}>Clear all</button></div>` +
    groups.map((g) => {
      const k = g.items.filter((f) => uniActive(f, vals[f.key])).length;
      return `<details class="uni-group" data-group="${esc(g.name)}" ${k || u.open[g.name] ? "open" : ""}>
        <summary>${esc(g.name)}<span class="pts mid" data-gcount ${k ? "" : "hidden"}>${k}</span></summary>
        <div class="uni-group-body">${g.items.map((f) => uniControl(f, vals[f.key])).join("")}</div></details>`;
    }).join("");
}
function uniUpdateCounts() {
  const u = state.uni, vals = u.filters[u.kind], defs = uniDefs();
  const n = defs.filter((f) => uniActive(f, vals[f.key])).length;
  const c = $("#uniFilterCount"); if (c) { c.textContent = n; c.classList.toggle("mid", !!n); }
  const clr = $("#uniClear"); if (clr) clr.hidden = !n;
  $$("#uniFilters details[data-group]").forEach((d) => {
    const k = defs.filter((f) => f.group === d.dataset.group && uniActive(f, vals[f.key])).length;
    const b = $("[data-gcount]", d); if (b) { b.textContent = k; b.hidden = !k; }
  });
}
function uniAddChip(key, raw) {
  const u = state.uni, vals = u.filters[u.kind];
  const items = String(raw || "").split(/[,\n;]+/).map((x) => x.trim()).filter(Boolean);
  if (!items.length) return;
  const cur = vals[key] || [];
  items.forEach((x) => { if (!cur.some((y) => y.toLowerCase() === x.toLowerCase())) cur.push(x); });
  vals[key] = cur; uniPersist(); renderUniFilters();
  const again = $(`#uniFilters [data-add="${key}"]`); if (again) again.focus();
}

/* ---- search and results ---- */
function uniCurrentFilters() {
  const u = state.uni, vals = u.filters[u.kind], out = {};
  uniDefs().forEach((f) => {
    const v = vals[f.key];
    if (!uniActive(f, v)) return;
    if (f.type === "range" || f.type === "daterange") {
      const o = {};
      if (v.min != null && v.min !== "") o.min = v.min;
      if (v.max != null && v.max !== "") o.max = v.max;
      out[f.key] = o;
    } else out[f.key] = v;
  });
  const q = (u.q[u.kind] || "").trim();
  if (q) out[u.kind === "people" ? "q_keywords" : "q_organization_name"] = q;
  return out;
}
async function uniSearch(page) {
  const u = state.uni;
  if (!uniConnected()) return toast("Connect Apollo first: the steps are at the top of this page.", true);
  u.q[u.kind] = $("#uniQuery").value.trim();
  const filters = uniCurrentFilters();
  if (!Object.keys(filters).length) return toast("Add a filter, or type something to search for.", true);
  const token = ++u.token, btn = $("#uniGo");
  btn.classList.add("loading");
  try {
    const d = await post("/api/universal/search", { kind: u.kind, filters, page: page || 1 });
    if (token !== u.token) return;
    u.rows = (u.kind === "people" ? d.people : d.companies) || [];
    u.total = d.total || 0; u.page = d.page || 1; u.perPage = d.per_page || 25;
    u.totalPages = Math.min(500, d.total_pages || Math.ceil(u.total / u.perPage) || 1);
    u.searched = true; u.resultKind = u.kind; u.lastFilters = filters; u.selected.clear();
    uniPersist();
    renderUniResults();
    if (u.kind === "companies") uniLoadStatus();             // that page cost a credit: show the new balance
  } catch (e) { toast(e.message, true); }
  finally { btn.classList.remove("loading"); }
}
function renderUniResults() {
  const u = state.uni, head = $("#uniHead"), body = $("#uniBody");
  if (!u.searched || u.resultKind !== u.kind) {
    head.innerHTML = "";
    body.innerHTML = uniConnected() ? `<tr class="empty-row"><td>Choose filters on the left or type in the search bar, then Search.</td></tr>` : "";
    $("#uniPager").hidden = true; renderUniBatch(); return;
  }
  const selectable = u.rows.filter((r) => !r.saved);
  const allSel = selectable.length > 0 && selectable.every((r) => u.selected.has(r.id));
  const selAll = `<th class="sel"><input type="checkbox" id="uniSelAll" aria-label="Select everyone on this page" ${allSel ? "checked" : ""} ${selectable.length ? "" : "disabled"}></th>`;
  if (u.resultKind === "people") {
    head.innerHTML = `<tr>${selAll}<th>Name</th><th>Title</th><th>Company</th><th>Email</th><th>Lead</th></tr>`;
    body.innerHTML = u.rows.length ? u.rows.map((p) => `<tr class="${u.selected.has(p.id) ? "selected" : ""}">
      <td class="sel">${p.saved ? "" : `<input type="checkbox" data-pick="${esc(p.id)}" ${u.selected.has(p.id) ? "checked" : ""} aria-label="Select ${esc(p.first_name)}">`}</td>
      <td><span class="cell-person">${avatar(p.first_name + " " + p.last_name_obfuscated, p.id)}<span><div class="primary-cell">${esc(p.first_name)} ${esc(p.last_name_obfuscated)}</div>
</span></span></td>
      <td>${esc(p.title || "")}</td>
      <td>${esc(p.company || "")}</td>
      <td>${p.has_email ? `<span class="lozenge success">Has email</span>` : `<span class="lozenge">No email</span>`}</td>
      <td>${p.saved ? `<span class="lozenge inprogress">Saved</span>` : ""}</td></tr>`).join("")
      : `<tr class="empty-row"><td colspan="6">Nobody matches. Remove a filter or two.</td></tr>`;
  } else {
    head.innerHTML = `<tr>${selAll}<th>Company</th><th>Website</th><th>LinkedIn</th><th>Founded</th><th>Phone</th><th></th></tr>`;
    body.innerHTML = u.rows.length ? u.rows.map((c) => {
      const li = safeUrl(c.linkedin_url);
      return `<tr class="${u.selected.has(c.id) ? "selected" : ""}">
      <td class="sel">${c.saved ? "" : `<input type="checkbox" data-pick="${esc(c.id)}" ${u.selected.has(c.id) ? "checked" : ""} aria-label="Select ${esc(c.name)}">`}</td>
      <td><div class="primary-cell">${esc(c.name)}</div>${c.in_apollo_account ? `<div class="secondary">Already an account in your Apollo</div>` : ""}</td>
      <td>${c.primary_domain ? `<a href="https://${esc(c.primary_domain)}" target="_blank" rel="noopener">${esc(c.primary_domain)}</a>` : ""}</td>
      <td>${li ? `<a href="${esc(li)}" target="_blank" rel="noopener">LinkedIn ${icon("external", 12)}</a>` : ""}</td>
      <td>${esc(c.founded_year || "")}</td>
      <td class="nowrap">${esc(c.phone || "")}</td>
      <td class="nowrap uni-row-actions">${c.saved ? statusLozenge(c.saved) : ""}
        <button class="btn subtle compact" data-people="${esc(c.id)}" data-name="${esc(c.name)}" title="People search, limited to this company (free)">People here</button>
        <button class="btn subtle compact" data-like="${esc(c.id)}" data-name="${esc(c.name)}" title="Use as a lookalike seed">Lookalikes</button></td></tr>`;
    }).join("") : `<tr class="empty-row"><td colspan="7">No company matches. Remove a filter or two.</td></tr>`;
  }
  const from = u.total ? (u.page - 1) * u.perPage + 1 : 0, to = Math.min(u.page * u.perPage, u.total);
  $("#uniInfo").textContent = u.total ? `${from.toLocaleString()}–${to.toLocaleString()} of ${u.total.toLocaleString()}${u.total > 500 * u.perPage ? " (Apollo shows the first 500 pages)" : ""}` : "";
  $("#uniPrev").disabled = u.page <= 1;
  $("#uniNext").disabled = u.page >= u.totalPages;
  // every page of companies is another credit, so the buttons say so
  const cost = u.resultKind === "companies" ? " · 1 credit" : "";
  $("#uniPrev").textContent = "Previous" + cost;
  $("#uniNext").textContent = "Next" + cost;
  $("#uniPager").hidden = !u.total;
  renderUniBatch();
}
function renderUniBatch() {
  const u = state.uni, n = u.selected.size, bar = $("#uniBatch");
  if (!n) { bar.hidden = true; bar.innerHTML = ""; return; }
  bar.hidden = false;
  if (u.resultKind === "people") {
    bar.innerHTML = `<strong>${n} selected</strong><span class="grow"></span>
      <label class="small" for="uniPerCo">At most</label>
      <select id="uniPerCo" class="filter" aria-label="At most this many people per company">
        <option value="">any number</option><option value="1">1 per company</option><option value="2">2 per company</option><option value="3">3 per company</option></select>
      <button class="btn subtle" id="uniClearSel">Clear</button>
      <button class="btn primary" id="uniSavePeople">${icon("check", 16)} Save ${n} ${n === 1 ? "person" : "people"}</button>`;
    $("#uniPerCo").value = u.perCompany || "";
  } else {
    bar.innerHTML = `<strong>${n} selected</strong><span class="grow"></span>
      <button class="btn subtle" id="uniClearSel">Clear</button>
      <button class="btn" id="uniPeopleAt">Find people at ${n === 1 ? "this company" : "these companies"}</button>
      <button class="btn primary" id="uniSaveCos">${icon("check", 16)} Save ${n} ${n === 1 ? "company" : "companies"}</button>`;
  }
}
function uniTrimPerCompany(rows, max) {
  if (!max) return { keep: rows, dropped: [] };
  const seen = {}, keep = [], dropped = [];
  rows.forEach((r) => { const k = (r.company || "").toLowerCase() || r.id; seen[k] = (seen[k] || 0) + 1; (seen[k] <= max ? keep : dropped).push(r); });
  return { keep, dropped };
}
function uniSavePeople() {
  const u = state.uni;
  const { keep, dropped } = uniTrimPerCompany([...u.selected.values()], +u.perCompany || 0);
  const n = keep.length;
  if (!n) return;
  if (n > u.maxReveal) return toast(`Save up to ${u.maxReveal} people at a time; ${n} are selected.`, true);
  const left = u.status && u.status.credits ? u.status.credits.lead_credits_left : null;
  modal.open(`${modalHead(`<span>Save ${n} ${n === 1 ? "person" : "people"}</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <p style="margin-bottom:16px">Apollo reveals each person's full name, work email, LinkedIn and company. They are saved to this project as leads, one company per lead.</p>
      <div class="section-msg warning">${icon("warn", 24)}<div><div class="title">Costs up to ${n} Apollo credit${n === 1 ? "" : "s"}</div>
        <div class="text">One credit for each person Apollo has details for, and none for anyone it cannot find.${left != null ? ` You have ${(+left).toLocaleString()} left.` : ""} Personal emails and phone numbers are never asked for.</div></div></div>
      ${dropped.length ? `<p class="small muted">${dropped.length} more ${dropped.length === 1 ? "is" : "are"} left out by “${esc(u.perCompany)} per company” and cost nothing.</p>` : ""}
    </div></div>
    <div class="modal-foot"><button class="btn subtle" data-close>Cancel</button>
      <button class="btn primary" id="uniSaveGo">Reveal and save ${n}</button></div>`, { narrow: true, label: "Save people" });
  $("#uniSaveGo").addEventListener("click", async (e) => {
    const b = e.currentTarget; b.classList.add("loading");
    try {
      const r = await post("/api/universal/save", { kind: "people", ids: keep.map((x) => x.id), filters: u.lastFilters || {} });
      modal.close(true);
      uniAfterSave(r, "people");
    } catch (err) { b.classList.remove("loading"); toast(err.message, true); }
  });
}
async function uniSaveCompanies() {
  const u = state.uni, rows = [...u.selected.values()];
  if (!rows.length) return;
  const b = $("#uniSaveCos"); if (b) b.classList.add("loading");
  try {
    const r = await post("/api/universal/save", { kind: "companies", companies: rows, filters: u.lastFilters || {} });
    uniAfterSave(r, "companies");
  } catch (err) { toast(err.message, true); if (b) b.classList.remove("loading"); }
}
function uniAfterSave(r, kind) {
  const u = state.uni, ids = new Set((r.saved_ids || []).map(String));
  u.rows.forEach((row) => { if (ids.has(String(row.id))) row.saved = kind === "people" ? true : "ready_for_review"; });
  u.selected.clear();
  renderUniResults();
  uniLoadStatus();
  const bits = [];
  if (kind === "people") {
    if (r.with_email != null) bits.push(`${r.with_email} with an email`);
    if (r.credits != null) bits.push(`${fmtScore(r.credits)} credit${+r.credits === 1 ? "" : "s"} used`);
    if (r.already_saved) bits.push(`${r.already_saved} already saved (no charge)`);
    if (r.not_found) bits.push(`${r.not_found} not found by Apollo (no charge)`);
  }
  if (r.companies_created) bits.push(`${r.companies_created} new ${r.companies_created === 1 ? "company" : "companies"}`);
  const title = `Saved ${r.saved} ${kind === "people" ? (r.saved === 1 ? "person" : "people") : (r.saved === 1 ? "company" : "companies")}`;
  const problems = (r.skipped || []).map((s) => `<li><strong>${esc(s.name || "Someone")}</strong>: ${esc(s.why)}</li>`).join("");
  if (problems || r.error) {
    modal.open(`${modalHead(`<span>${esc(title)}</span>`)}<div class="modal-body single"><div class="modal-main">
      <p>${esc(bits.join(" · "))}</p>
      ${r.error ? `<div class="section-msg warning">${icon("warn", 24)}<div><div class="title">Apollo stopped part-way</div><div class="text">${esc(r.error)} ${r.unrevealed ? `${r.unrevealed} ${r.unrevealed === 1 ? "person was" : "people were"} not revealed and not charged; select them again later.` : ""}</div></div></div>` : ""}
      ${problems ? `<h4 class="sub-h">Not saved</h4><ul class="plain-list">${problems}</ul>` : ""}
      <p class="small muted">Saved leads are on this project's Board and Leads pages.</p></div></div>
      <div class="modal-foot"><button class="btn primary" data-close>Done</button></div>`, { narrow: true, label: title });
  } else {
    flag(title, { desc: bits.join(" · ") + ". They are on the Board and Leads pages.", ms: 6000 });
  }
}
function uniPeopleAt(pairs) {
  const u = state.uni;
  pairs.forEach(([id, name]) => { u.picked[id] = name; });
  u.filters.people = Object.assign({}, u.filters.people, { organization_ids: pairs.map((p) => p[0]).slice(0, 100) });
  u.kind = "people"; u.selected.clear();
  uniPersist(); renderUniTabs(); renderUniFilters(); uniSearch(1);
}
function uniLookalike(id, name) {
  const u = state.uni, v = (u.filters.companies.lookalike_organization_ids || []).slice();
  if (v.includes(id)) return toast(name + " is already a lookalike seed.");
  if (v.length >= 5) return toast("Apollo takes up to 5 lookalike seeds. Remove one first.", true);
  u.picked[id] = name; v.push(id);
  u.filters.companies.lookalike_organization_ids = v;
  u.open["Company"] = true;
  uniPersist(); renderUniFilters();
  flag(name + " added as a lookalike seed", { desc: "Search again to see companies like it (1 credit a page).", kind: "info" });
}

/* ---- saved searches ---- */
async function renderUniSavedMenu(menu) {
  menu.innerHTML = `<div class="menu-heading">Saved searches</div><div class="menu-note">Loading…</div>`;
  let d;
  try { d = await api("/api/universal/searches"); }
  catch (e) { menu.innerHTML = `<div class="menu-heading">Saved searches</div><div class="menu-note">${esc(e.message)}</div>`; return; }
  const rows = d.searches || [];
  menu.innerHTML = `<div class="menu-heading">Saved searches</div>` + (rows.length ? rows.map((s) =>
    `<div class="menu-item uni-saved" data-load="${esc(s.id)}" role="button" tabindex="0">${icon(s.kind === "people" ? "users" : "globe", 20)}
      <span class="uni-saved-text"><span class="truncate">${esc(s.name)}</span><span class="desc">${esc(s.summary)}</span></span>
      <button class="btn icon" data-del="${esc(s.id)}" aria-label="Delete ${esc(s.name)}" title="Delete">${icon("x", 14)}</button></div>`).join("")
    : `<div class="menu-note">None yet. Set up a search, then “Save search”.</div>`);
  const byId = Object.fromEntries(rows.map((s) => [s.id, s]));
  $$("[data-load]", menu).forEach((el) => {
    const load = (e) => {
      if (e.target.closest("[data-del]")) return;
      closeMenus(); uniApplySaved(byId[el.dataset.load]);
    };
    el.addEventListener("click", load);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") load(e); });
  });
  $$("[data-del]", menu).forEach((b) => b.addEventListener("click", async (e) => {
    e.stopPropagation();
    try { await api("/api/universal/searches/" + b.dataset.del, { method: "DELETE" }); flag("Saved search deleted"); renderUniSavedMenu(menu); }
    catch (err) { toast(err.message, true); }
  }));
}
function uniApplySaved(s) {
  if (!s) return;
  const u = state.uni, f = Object.assign({}, s.filters || {});
  u.kind = s.kind;
  u.q[s.kind] = f.q_keywords || f.q_organization_name || "";
  delete f.q_keywords; delete f.q_organization_name;
  u.filters[s.kind] = f;
  uniPersist(); renderUniTabs(); renderUniFilters();
  if (s.kind === "people") uniSearch(1);                      // free, so it runs straight away
  else { u.searched = false; renderUniResults(); flag("“" + s.name + "” loaded", { desc: "Search to run it (1 credit a page).", kind: "info" }); }
}
function uniSaveSearchDialog() {
  const u = state.uni;
  u.q[u.kind] = $("#uniQuery").value.trim();
  const filters = uniCurrentFilters();
  if (!Object.keys(filters).length) return toast("Set up a search first: a filter or some search words.", true);
  modal.open(`${modalHead(`<span>Save search</span>`)}<div class="modal-body single"><div class="modal-main">
      <div class="field"><label for="ssName">Name</label><input id="ssName" type="text" maxlength="80" autofocus placeholder="e.g. Heads of partnerships at Mumbai studios">
      <div class="help">A ${u.kind === "people" ? "people" : "company"} search. Saving under a name you already used replaces that search.</div></div>
    </div></div>
    <div class="modal-foot"><button class="btn subtle" data-close>Cancel</button><button class="btn primary" id="ssGo">Save</button></div>`,
    { narrow: true, label: "Save search" });
  const go = async () => {
    const name = $("#ssName").value.trim();
    if (!name) return $("#ssName").focus();
    $("#ssGo").classList.add("loading");
    try { await post("/api/universal/searches", { name, kind: u.kind, filters }); modal.close(true); flag("Search saved", { desc: name }); }
    catch (e) { toast(e.message, true); $("#ssGo").classList.remove("loading"); }
  };
  $("#ssGo").addEventListener("click", go);
  $("#ssName").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
}

function bindUniversal() {
  const u = state.uni, fl = $("#uniFilters");
  $("#uniForm").addEventListener("submit", (e) => { e.preventDefault(); uniSearch(1); });
  $("#uniQuery").addEventListener("input", (e) => { u.q[u.kind] = e.target.value; uniPersist(); });
  $$("#uniTabs [data-kind]").forEach((b) => b.addEventListener("click", () => {
    if (u.kind === b.dataset.kind) return;
    u.q[u.kind] = $("#uniQuery").value;
    u.kind = b.dataset.kind; u.selected.clear();
    uniPersist(); renderUniTabs(); renderUniFilters(); renderUniResults();
  }));
  fl.addEventListener("keydown", (e) => {
    const inp = e.target.closest("[data-add]");
    if (!inp) return;
    if (e.key === "Enter" || e.key === ",") { e.preventDefault(); uniAddChip(inp.dataset.add, inp.value); }
    else if (e.key === "Backspace" && !inp.value) {
      const vals = u.filters[u.kind], cur = vals[inp.dataset.add] || [];
      if (cur.length) { cur.pop(); if (!cur.length) delete vals[inp.dataset.add]; uniPersist(); renderUniFilters(); const again = $(`#uniFilters [data-add="${inp.dataset.add}"]`); if (again) again.focus(); }
    }
  });
  fl.addEventListener("focusout", (e) => {
    const inp = e.target.closest("[data-add]");
    if (inp && inp.value.trim()) setTimeout(() => uniAddChip(inp.dataset.add, inp.value), 0);
  });
  fl.addEventListener("click", (e) => {
    const x = e.target.closest("[data-remove]");
    if (x) {
      const vals = u.filters[u.kind], cur = vals[x.dataset.remove] || [];
      cur.splice(+x.dataset.i, 1);
      if (!cur.length) delete vals[x.dataset.remove];
      uniPersist(); renderUniFilters();
      return;
    }
    if (e.target.closest("#uniClear")) { u.filters[u.kind] = {}; uniPersist(); renderUniFilters(); }
  });
  fl.addEventListener("change", (e) => {
    const t = e.target, vals = u.filters[u.kind];
    if (t.dataset.choice) {
      const cur = vals[t.dataset.choice] || [];
      const next = t.checked ? cur.concat(cur.includes(t.value) ? [] : [t.value]) : cur.filter((x) => x !== t.value);
      if (next.length) vals[t.dataset.choice] = next; else delete vals[t.dataset.choice];
    } else if (t.dataset.bool) {
      if (t.checked) delete vals[t.dataset.bool]; else vals[t.dataset.bool] = false;
    } else if (t.dataset.range) {
      const o = Object.assign({}, vals[t.dataset.range] || {});
      if (t.value === "") delete o[t.dataset.end]; else o[t.dataset.end] = t.value;
      if (Object.keys(o).length) vals[t.dataset.range] = o; else delete vals[t.dataset.range];
    } else if (t.dataset.f) {
      if (t.value.trim() === "") delete vals[t.dataset.f]; else vals[t.dataset.f] = t.value.trim();
    } else return;
    uniPersist(); uniUpdateCounts();
  });
  fl.addEventListener("toggle", (e) => {
    const d = e.target.closest && e.target.closest("details[data-group]");
    if (d) u.open[d.dataset.group] = d.open;
  }, true);

  const res = $("#uniTable");
  res.addEventListener("change", (e) => {
    const t = e.target;
    if (t.id === "uniSelAll") {
      u.rows.filter((r) => !r.saved).forEach((r) => { if (t.checked) u.selected.set(r.id, r); else u.selected.delete(r.id); });
      renderUniResults(); return;
    }
    if (t.dataset.pick) {
      const row = u.rows.find((r) => r.id === t.dataset.pick);
      if (t.checked && row) u.selected.set(row.id, row); else u.selected.delete(t.dataset.pick);
      t.closest("tr").classList.toggle("selected", t.checked);
      renderUniBatch();
      const all = $("#uniSelAll"), sel = u.rows.filter((r) => !r.saved);
      if (all) all.checked = sel.length > 0 && sel.every((r) => u.selected.has(r.id));
    }
  });
  res.addEventListener("click", (e) => {
    const p = e.target.closest("[data-people]");
    if (p) return uniPeopleAt([[p.dataset.people, p.dataset.name]]);
    const l = e.target.closest("[data-like]");
    if (l) return uniLookalike(l.dataset.like, l.dataset.name);
  });
  $("#uniBatch").addEventListener("click", (e) => {
    if (e.target.closest("#uniClearSel")) { u.selected.clear(); renderUniResults(); }
    else if (e.target.closest("#uniSavePeople")) uniSavePeople();
    else if (e.target.closest("#uniSaveCos")) uniSaveCompanies();
    else if (e.target.closest("#uniPeopleAt")) uniPeopleAt([...u.selected.values()].map((c) => [c.id, c.name]));
  });
  $("#uniBatch").addEventListener("change", (e) => { if (e.target.id === "uniPerCo") u.perCompany = e.target.value; });
  $("#uniPrev").addEventListener("click", () => uniSearch(state.uni.page - 1));
  $("#uniNext").addEventListener("click", () => uniSearch(state.uni.page + 1));
  $("#uniSaveSearch").addEventListener("click", uniSaveSearchDialog);
  $("#uniSavedBtn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($("#uniSavedBtn"), $("#uniSavedMenu"), renderUniSavedMenu); });
}

/* ===================================================== outreach count */
/* The one signal outside the Outreach page that something waits on a person: drafts to
   approve, replies to read, sends that failed. (The top-bar bell that repeated it went on
   2026-09-19.) */
function updateOutreachCount(counts) {
  const side = $("#outreachCount");
  const waiting = (counts.drafts || 0) + (counts.untriaged || 0) + (counts.attention || 0);
  side.hidden = waiting === 0; side.textContent = String(waiting);
  side.title = "Drafts to approve, replies to read and sends that failed";
  state.notif.counts = counts; state.notif.at = Date.now();
}
async function refreshOutreachCount(force) {
  if (!outreachOn()) return;
  if (!force && Date.now() - state.notif.at < 90000) return;
  try { const d = await api("/api/outreach?folder=attention"); updateOutreachCount(d.counts || {}); } catch (e) {}
}
function renderProjectsMenu(menu) {
  const segs = state.segments.length ? state.segments
    : [{ slug: "us-production-houses", project_name: "US Production Houses", current: true }];
  menu.innerHTML = `<div class="menu-heading">Projects</div>` + segs.map((s) =>
    `<button class="menu-item ${s.current ? "selected" : ""}" data-seg="${esc(s.slug)}">${icon(s.current ? "film" : "bookmark", 20)}
       <span style="flex:1">${esc(s.project_name)}</span>
       ${s.current ? icon("check", 16) : ""}</button>`).join("");
  $$("[data-seg]", menu).forEach((b) => b.addEventListener("click", async () => {
    closeMenus();
    if (state.segment && b.dataset.seg === state.segment.slug) return;
    try { await post("/api/segment/select", { slug: b.dataset.seg }); history.replaceState(null, "", location.pathname); location.reload(); }
    catch (e) { toast(e.message, true); }
  }));
}
function renderUserMenu(menu) {
  const email = state.user || "";
  menu.innerHTML = `<div class="menu-user">${avatar(null, email, "lg")}<div style="min-width:0"><div class="email truncate">${esc(email || "Signed in")}</div></div></div>
    <div class="menu-sep"></div>
    <button class="menu-item" id="logoutBtn">${icon("logout", 20)}<span>Log out</span></button>`;
  $("#logoutBtn", menu).addEventListener("click", async () => {
    try { await post("/api/auth/logout"); } catch (e) {}
    location.href = "/login";
  });
}

function bindShell() {
  const pairs = [["#userBtn", "#userMenu", renderUserMenu],
    ["#projectSwitch", "#projectSwitchMenu", renderProjectsMenu]];   // the project switcher at the top of the sidebar
  pairs.forEach(([b, m, r]) => $(b).addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($(b), $(m), r); }));
  $$("[data-route]").forEach((b) => b.addEventListener("click", () => go(b.dataset.route)));

  // sidebar: collapse on desktop, drawer on small screens
  const frame = $("#frame");
  try { if (localStorage.getItem("tvf_sidebar") === "collapsed") frame.classList.add("collapsed"); } catch (e) {}
  $("#collapseBtn").addEventListener("click", () => {
    frame.classList.toggle("collapsed");
    const c = frame.classList.contains("collapsed");
    $("#collapseBtn").setAttribute("aria-label", c ? "Expand sidebar" : "Collapse sidebar");
    try { localStorage.setItem("tvf_sidebar", c ? "collapsed" : "open"); } catch (e) {}
  });
  $("#drawerBtn").addEventListener("click", () => frame.classList.toggle("drawer-open"));
  $("#sidebarScrim").addEventListener("click", () => frame.classList.remove("drawer-open"));

}

/* ======================================================= filter wiring */
function syncLeadControls() {
  const f = state.leads.filters;
  $("#leadsSearch").value = f.q; $("#leadsStatus").value = f.status; $("#leadsSource").value = f.source;
  $("#leadsContact").value = f.contact;
}
function bindFilters() {
  let t;
  const b = state.board.filters, l = state.leads.filters;
  $("#boardSearch").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { b.q = e.target.value.trim(); loadBoard(); }, 250); });
  $("#leadsSearch").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { l.q = e.target.value.trim(); state.leads.page = 0; loadLeads(); }, 250); });
  $("#leadsStatus").addEventListener("change", (e) => { l.status = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsSource").addEventListener("change", (e) => { l.source = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsContact").addEventListener("change", (e) => { l.contact = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsPrev").addEventListener("click", () => { state.leads.page--; loadLeads(); });
  $("#leadsNext").addEventListener("click", () => { state.leads.page++; loadLeads(); });
}

/* ================================================================ init */
(async function init() {
  bindShell(); bindFilters(); bindOps();
  try {
    const a = await api("/api/auth/state");
    state.user = a.user || null;
    $("#userAvatar").textContent = initials(null, state.user || "?");
    $("#userAvatar").className = "avatar av-" + (hashCode(state.user || "") % 8 + 1);
  } catch (e) {}
  try {
    const s = await api("/api/stats");
    state.sources = s.by_source.map((r) => r.source);
    $("#leadsSource").innerHTML = '<option value="">All sources</option>' + s.by_source.map((r) =>
      `<option value="${esc(r.source)}">${esc(sourceLabel(r.source))}</option>`).join("");
    $("#leadsSource").hidden = state.sources.length < 2;
    $("#leadsTable").classList.toggle("one-source", state.sources.length < 2);
    const n = { open: s.open_pool, shortlisted: s.shortlisted, contacted: s.contacted,
      in_conversation: s.in_conversation, rejected: s.rejected, archived: s.archived };
    $$("#leadsStatus option").forEach((o) => { if (o.value in n) o.hidden = !+n[o.value]; });
    $("#leadsStatus").hidden = !$$("#leadsStatus option").some((o) => o.value !== "all" && !o.hidden);
  } catch (e) {
    flag("Cannot reach the database", { desc: "Is SUPABASE_DB_URL set? " + e.message, kind: "err", ms: 8000 });
  }
  try {
    const [seg, segs] = await Promise.all([api("/api/segment"), api("/api/segments")]);
    state.segments = segs.segments || [];
    applySegment(seg);
  } catch (e) { /* older server: TVF defaults stand */ }
  syncLeadControls();
  router();
  refreshOutreachCount(true);
  setInterval(() => refreshOutreachCount(false), 120000);
})();
