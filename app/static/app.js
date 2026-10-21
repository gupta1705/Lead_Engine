/* TVF Lead Engine -- the review surface.
 *
 * Still no framework and no build step; the reason is deployment, not taste
 * (see the note at the top of app/main.py). The shape is a project sidebar, a
 * board with one column per pipeline state, a list view, a sheet for every lead
 * and every email, reports, and an operations page. The look was redesigned on
 * 2026-09-27 (style.css says how); the Jira idiom of 2026-09-04 went with it.
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
  if (!name && !seed) return `<span class="avatar none ${size || ""}" title="No contact yet">${icon("user", size === "xs" ? 11 : 13)}</span>`;
  const cls = "av-" + (hashCode(seed || name) % 8 + 1);
  return `<span class="avatar ${cls} ${size || ""}" title="${esc(name || seed)}">${esc(initials(name, seed))}</span>`;
}
/* A company's tile: its initials ("The" left out) on one of eight tints, the same tint every time. */
function monoTile(name, seed, size) {
  const n = String(name || "").replace(/^the\s+/i, "");
  return `<span class="mono-tile ${size || ""} t${hashCode(seed || name) % 8 + 1}" aria-hidden="true">${esc(initials(n, seed))}</span>`;
}
/* Rows of shimmering placeholders while a table's first answer is on its way. */
function skeletonRows(cols, n) {
  const w = [62, 38, 24, 30, 46, 20];
  return Array.from({ length: n }, (_, i) => `<tr class="empty-row skeleton-row" aria-hidden="true">${Array.from({ length: cols }, (_, c) =>
    `<td style="padding:16px 14px;text-align:left"><span class="skel" style="height:12px;width:${w[(c + i) % w.length]}%"></span></td>`).join("")}</tr>`).join("");
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
  chevUp: '<path d="m18 15-6-6-6 6"/>',
  chevLeft: '<path d="m15 18-6-6 6-6"/>',
  paperclip: '<path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
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
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  building: '<path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/><path d="M3 21h18M10 7h4M10 11h4M10 15h4"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
function icon(name, size, extra) {
  return `<svg width="${size || 16}" height="${size || 16}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra || ""}>${PATHS[name] || ""}</svg>`;
}
function typeIcon(kind) {
  const glyph = { mail: "mail", user: "user" }[kind] || "building";
  return `<span class="type-icon ${kind}" title="${kind === "mail" ? "Email" : kind === "user" ? "Your account" : "Lead"}">${icon(glyph, 15)}</span>`;
}
/* A project with no rubric (Universal) has no scores: its thresholds are both 0, and the
   board, list and dialog leave the score and priority out rather than show a row of zeros. */
function unscoredProject() { return !REVIEW_THRESHOLD && !PRIORITY_THRESHOLD; }
function ptsClass(score) { score = +score || 0; return score >= PRIORITY_THRESHOLD ? "hi" : score >= REVIEW_THRESHOLD ? "mid" : ""; }
function pts(score) { return `<span class="pts ${ptsClass(score)}" title="Fit score out of 100">${fmtScore(score)}</span>`; }
/* The fit score as a ring: how much of 100 it is, coloured by band (priority, review, below). */
function scoreRing(score, size) {
  size = size || 34;
  const s = Math.max(0, Math.min(100, +score || 0)), sw = size >= 48 ? 4 : 3, h = size / 2, r = (size - sw) / 2;
  const c = 2 * Math.PI * r, label = "Fit score " + fmtScore(score) + " out of 100";
  return `<span class="ring ${ptsClass(s) || "lo"} ${size >= 48 ? "lg" : ""}" style="width:${size}px;height:${size}px" role="img" aria-label="${label}" title="${label}">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true"><circle class="ring-track" cx="${h}" cy="${h}" r="${r}" stroke-width="${sw}"/>${s > 0
      ? `<circle class="ring-fill" cx="${h}" cy="${h}" r="${r}" stroke-width="${sw}" stroke-dasharray="${(c * s / 100).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 ${h} ${h})"/>` : ""}</svg>
    <span class="ring-n" aria-hidden="true">${fmtScore(score)}</span></span>`;
}
/* In a table: the number, and a bar of how much of 100 it is. */
function scoreCell(score) {
  const s = Math.max(0, Math.min(100, +score || 0));
  return `<span class="score-cell">${pts(score)}<span class="meter ${ptsClass(s)}" aria-hidden="true"><i style="width:${s}%"></i></span></span>`;
}

// each state's pill takes the colour its board column and its slice of the donut have
const LEAD_STATUS = {
  discovered: ["To review", "dot"], enriched: ["To review", "dot"], scored: ["To review", "dot"],
  ready_for_review: ["To review", "dot"], shortlisted: ["Shortlisted", "success"],
  contacted: ["Contacted", "inprogress"], in_conversation: ["In conversation", "moved"],
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
// connector slugs as the database knows them -> what a reviewer should read. A source is a
// fact about a lead, not a state, so it is a plain tag: colour is kept for states.
const SOURCES = {
  aicp_directory: "AICP", google_news_rss: "News", wikidata: "Wikidata", youtube_api: "YouTube",
  x_intent: "X", manual_p1: "Manual", manual: "Manual", wikidata_channels: "Wikidata", tvf_pool: "TVF pool",
  apple_podcasts: "Podcast", startup_news: "News", apollo: "Apollo",
};
function sourceLabel(src) { return SOURCES[src] || String(src || "unknown").replace(/_/g, " "); }
function sourceLozenge(src) {
  return `<span class="tag" title="Discovered by the ${esc(src)} connector">${esc(sourceLabel(src))}</span>`;
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
  service: "",        // the lead-service tab (LCX Services), one selection for the Board and Leads both
  board: { filters: { q: "", min_score: REVIEW_THRESHOLD }, cols: {}, token: 0 },
  leads: { filters: { q: "", status: "all", source: "", contact: "" }, selected: new Map(),
           page: 0, perPage: 50, total: 0, rows: [], token: 0 },
  outreach: { folder: "drafts", rows: [], counts: {}, category: "", service: "", sort: "default", direction: "desc", offset: 0, limit: 200, token: 0, busy: false, selected: new Set() },
  ops: { timer: null },
  notif: { counts: null, at: 0 },
};

/* ============================================================== modal */
/* A dialog, or with opts.sheet a sheet from the right (a lead, an email: the list it came from stays
   in view). One dialog replacing another -- the lead arriving in the sheet that said "Opening", the
   lead redrawn after a decision -- swaps in place, without a second entrance. */
const modal = {
  lastFocus: null,
  current: null,      // the lead or email a sheet shows: { kind, id }, for moving to the next one
  guard: null,        // asked before a close that would lose something (an edited draft); false keeps it open
  open(html, opts) {
    opts = opts || {};
    const swap = this.isOpen();
    this.locked = false;
    this.close(true);
    this.current = null; this.guard = null;
    this.locked = !!opts.locked;             // the first sign-in: no way round it but through it
    this.lastFocus = document.activeElement;
    const root = $("#modalRoot");
    root.innerHTML = `<div class="blanket ${opts.sheet ? "sheet" : ""} ${swap ? "instant" : ""}" data-blanket>
      <div class="modal ${opts.narrow ? "narrow" : opts.medium ? "medium" : ""} ${opts.sheet ? "sheet" : ""}" role="dialog" aria-modal="true" tabindex="-1" aria-label="${esc(opts.label || "Dialog")}">${html}</div></div>`;
    document.body.style.overflow = "hidden";
    if (this.locked) $$("[data-close]", root).forEach((b) => b.remove());   // no corner X to walk round it
    const blanket = $("[data-blanket]", root);
    blanket.addEventListener("mousedown", (e) => { if (e.target === blanket && !this.locked) this.close(); });
    $$("[data-close]", root).forEach((b) => b.addEventListener("click", () => this.close()));
    this.onClose = opts.onClose || null;
    // a sheet takes the focus itself, not its primary button: Enter on a card must not shortlist or
    // approve what has not been read yet. A small dialog still focuses its field or its one action.
    const first = opts.sheet ? ($("[autofocus]", root) || $(".modal", root))
                             : $("[autofocus], .modal-foot .btn.primary, [data-close]", root);
    if (first) setTimeout(() => first.focus(), 30);
  },
  close(silent) {
    const root = $("#modalRoot");
    if (!root.innerHTML) return;
    if (!silent && this.guard && !this.guard()) return;
    this.current = null; this.guard = null;
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

/* Moving through a list without leaving the sheet (2026-09-27): the arrows in a sheet's head, or J / K.
   The list is the one the sheet was opened from -- a board column, the Leads page, an Outreach folder --
   as it stood then, so a lead that changes column on a decision keeps its place. Moving never acts on
   anything: approving the next email is still its own click, after reading it. */
function setNav(kind, ids) { state.nav = ids && ids.length > 1 ? { kind, ids: ids.slice() } : null; }
function navButtons(kind, id) {
  const n = state.nav, i = n && n.kind === kind ? n.ids.indexOf(id) : -1;
  if (i < 0) return "";
  return `<span class="sheet-nav"><span class="pos num">${i + 1} of ${n.ids.length}</span>
    <button class="btn icon" data-nav="-1" ${i === 0 ? "disabled" : ""} aria-label="Previous" title="Previous (K)">${icon("chevUp", 18)}</button>
    <button class="btn icon" data-nav="1" ${i === n.ids.length - 1 ? "disabled" : ""} aria-label="Next" title="Next (J)">${icon("chevDown", 18)}</button></span>`;
}
function bindNav(root) {
  $$("[data-nav]", root).forEach((b) => b.addEventListener("click", () => navStep(+b.dataset.nav)));
}
function navStep(step) {
  const cur = modal.current, n = state.nav;
  if (!cur || !n || n.kind !== cur.kind) return;
  const j = n.ids.indexOf(cur.id) + step;
  if (j < 0 || j >= n.ids.length) return;
  if (modal.guard && !modal.guard()) return;             // an edited draft asks before it is left
  const next = n.ids[j];
  if (cur.kind === "lead") { history.replaceState(null, "", "#lead/" + next); openLead(next); }
  else openMessage(next);
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
  if (e.key === "Escape") { closeMenus(); if (modal.isOpen() && !modal.locked) modal.close(); }
  // J / K: the next or previous lead or email, without leaving the sheet (not while typing)
  if ((e.key === "j" || e.key === "k") && modal.current && !e.ctrlKey && !e.metaKey && !e.altKey
      && !(e.target.closest && e.target.closest("input, textarea, select, [contenteditable]"))) {
    e.preventDefault();
    navStep(e.key === "j" ? 1 : -1);
  }
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
  return r.kind ? `<span class="tag" title="Kind of lead">${esc(String(r.kind).replace(/_/g, " "))}</span>` : "";
}
function placeTag(r) {
  const place = r.state || r.city;
  return place ? `<span class="tag" title="${esc((r.city || "") + (r.state ? ", " + r.state : ""))}">${icon("pin", 11)}<span>${esc(place)}</span></span>` : "";
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
  if (format === "list" && Array.isArray(v)) return `<span class="pill-list">${v.slice(0, 8).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</span>`;
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
    // LCX Services (2026-10-13): the services it fits are in the Lead service box, as Also fits, beside the one it
    // is pitched; listing them here too, as "Pitch first", would name a different first service
    if (d.lead_service && f.path === "metadata.services") return "";
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
  state.service = serviceRestore();
  document.title = (TITLES[currentView()] || "") + " - " + ui.project_name;
}

/* ======================================================= lead service */
/* LCX Services (the owner's review of its emails, 2026-10-13, point 12): each lead is pitched ONE service from the
   deck (metadata.lead_service, tools/lcx_judge.py), and the email records which (outreach.service). The Board and
   Leads get one row of tabs, All and a tab per service with its count for what is on screen, then Check service
   (the rules left it to a person) and Not a buyer. A tab with nothing behind it is not shown, and the row is not
   shown at all where it cannot change what is on screen. The tab is one selection for both pages, remembered per
   viewer and per project (this browser only). A project that pitches no single service has none of it: its
   /api/leads answers carry no service_counts. */
const SERVICE_STORE = "tvf_service_v1";
const SERVICE_BUCKET = { hold: "Check service", none: "Not a buyer" };
function serviceLabel(key) { return SERVICE_BUCKET[key] || key || ""; }
function serviceStoreKey() { return SERVICE_STORE + ":" + ((state.segment && state.segment.slug) || ""); }
function serviceRestore() {
  try { return localStorage.getItem(serviceStoreKey()) || ""; } catch (e) { return ""; }
}
function servicePersist() {
  try {
    if (state.service) localStorage.setItem(serviceStoreKey(), state.service);
    else localStorage.removeItem(serviceStoreKey());
  } catch (e) {}
}
/* The Board asks once per column: its tabs count every column's leads together. */
function sumServiceCounts(answers) {
  if (!answers.some((d) => Array.isArray(d.service_counts))) return null;
  const by = new Map(); let all = 0;
  answers.forEach((d) => {
    all += +d.service_all || 0;
    (d.service_counts || []).forEach((c) => by.set(c.key, (by.get(c.key) || 0) + (+c.n || 0)));
  });
  const named = [...by].filter(([k]) => !SERVICE_BUCKET[k]).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return { all, counts: named.concat(Object.keys(SERVICE_BUCKET).filter((k) => by.has(k)).map((k) => [k, by.get(k)]))
    .map(([key, n]) => ({ key, n })) };
}
function renderServiceTabs(el, sc) {
  const cur = state.service;
  if (!sc) { el.hidden = true; el.innerHTML = ""; return; }
  const tabs = sc.counts.filter((c) => c.n > 0 || c.key === cur);
  if (cur && !tabs.some((c) => c.key === cur)) tabs.push({ key: cur, n: 0 });   // on, with nothing in it now
  // a row that cannot change what is on screen is not shown: one tab holding every lead, and no tab on
  const useful = cur || tabs.some((c) => c.n < sc.all);
  el.hidden = !tabs.length || !useful;
  if (el.hidden) { el.innerHTML = ""; return; }
  const tips = { hold: "The rules left its service to a person: pick one in its sheet", none: "Not a buyer: no email is drafted" };
  const tab = (key, label, n) => `<button class="tab ${key === cur ? "active" : ""}" role="tab" aria-selected="${key === cur}"
      data-svc="${esc(key)}"${tips[key] ? ` title="${esc(tips[key])}"` : ""}>${esc(label)}<span class="pts">${(+n || 0).toLocaleString()}</span></button>`;
  el.innerHTML = tab("", "All", sc.all) + tabs.map((c) => tab(c.key, serviceLabel(c.key), c.n)).join("");
  // a row wider than the page scrolls within itself: the tab that is on is kept in view
  const a = $(".tab.active", el);
  if (a) {
    const r = a.getBoundingClientRect(), box = el.getBoundingClientRect();
    if (r.left < box.left || r.right > box.right) el.scrollLeft += r.left - box.left - 24;
  }
}
function bindServiceTabs(el, reload) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-svc]");
    if (!b || b.dataset.svc === state.service) return;
    state.service = b.dataset.svc;
    servicePersist();
    reload();
  });
}
/* "Selling: AI Video for Brands" on a card or a row, when the All tab is on (a service tab already says it). */
function serviceTag(r) {
  if (!r.service || state.service) return "";
  const label = serviceLabel(r.service), held = !!SERVICE_BUCKET[r.service];
  return `<span class="tag" style="max-width:100%" title="${esc(held ? label : "Its email pitches " + label)}"><span>${esc(held ? label : "Selling: " + label)}</span></span>`;
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
  if (state.service) p.set("service", state.service);                      // the lead-service tab (LCX Services)
  p.set("limit", COL_LIMIT); p.set("offset", offset || 0);
  return p.toString();
}

/* A card: the company (its tile, name and website) with its fit score beside it, the facts worth a
   glance (source only where a project has more than one, kind, place), and at the foot the person
   the email goes to and who reached out. */
function renderCard(r, col) {
  const score = +r.fit_score || 0;
  const t = leadTitle(r);
  const tags = serviceTag(r) + (state.sources.length > 1 ? sourceLozenge(r.source) : "") + kindLozenge(r) + placeTag(r);
  const fields = fieldSummary(r);
  const who = r.email
    ? `<span class="card-contact" title="The email goes to ${esc(r.contact_name ? r.contact_name + " <" + r.email + ">" : r.email)}">${avatar(r.contact_name, r.email, "xs")}<span class="truncate">${esc(r.contact_name || r.email)}</span></span>`
    : `<span class="card-contact none">${avatar(null, null, "xs")}<span>No contact yet</span></span>`;
  return `<div class="card ${col.done ? "done" : ""}" role="button" tabindex="0" data-id="${esc(r.id)}"
       aria-label="${esc(t.aria)}${unscoredProject() ? "" : ", score " + fmtScore(score)}">
    <div class="card-top">${monoTile(t.title, r.domain || r.id, "sm")}
      <div class="card-titles"><div class="card-summary">${esc(t.title)}</div>
        ${t.sub ? `<div class="card-sub truncate">${esc(t.sub)}</div>` : ""}</div>
      ${unscoredProject() ? "" : scoreRing(score, 34)}</div>
    ${fields ? `<div class="card-sub">${fields}</div>` : ""}
    ${tags ? `<div class="card-tags">${tags}</div>` : ""}
    <div class="card-foot">${who}
      ${r.reached_by_name ? `<span class="card-by right" title="Reached out by ${esc(r.reached_by || "")}">${icon("send", 12)} ${esc(r.reached_by_name)}</span>` : ""}
    </div></div>`;
}

function columnHead(col, total) {
  return `<div class="column-head"><span class="dot" aria-hidden="true"></span><span class="${col.done ? "done" : ""}">${esc(col.title)}</span>
      ${total == null ? "" : `<span class="n">${total}</span>`}${col.done ? icon("checkCircle", 14, 'style="color:var(--text-success)"') : ""}</div>`;
}
function renderColumn(col) {
  const c = state.board.cols[col.key] || { rows: [], total: 0 };
  const body = c.rows.length
    ? c.rows.map((r) => renderCard(r, col)).join("")
    : `<div class="column-empty">${state.board.filters.q ? "Nothing matches this search."
      : state.service && state.board.sells ? "None here for " + esc(serviceLabel(state.service)) + "."
      : col.key === "open" ? "Nothing to review." : "No leads here yet."}</div>`;
  const more = c.rows.length < c.total
    ? `<button class="btn subtle compact column-more" data-more="${col.key}">Show more (${c.total - c.rows.length} left)</button>` : "";
  return `<section class="column" data-key="${col.key}" aria-label="${esc(col.title)}">
    ${columnHead(col, c.total)}
    <div class="column-body" data-col="${col.key}">${body}${more}</div></section>`;
}
/* Before the first answer: the columns with placeholder cards, not "Nothing to review" (which is not yet known). */
function skeletonColumn(col, i) {
  const card = (w) => `<div class="card skeleton" aria-hidden="true"><div class="card-top"><span class="skel" style="width:30px;height:30px;border-radius:8px"></span>
    <div class="card-titles"><span class="skel" style="width:${w}%;height:12px;margin:4px 0 8px"></span><span class="skel" style="width:${w - 25}%;height:10px"></span></div></div>
    <span class="skel" style="width:38%;height:10px"></span></div>`;
  return `<section class="column" data-key="${col.key}" aria-label="${esc(col.title)}, loading" aria-busy="true">${columnHead(col, null)}
    <div class="column-body">${[78, 64, 70].slice(0, 3 - (i % 2)).map(card).join("")}</div></section>`;
}

async function loadBoard() {
  const token = ++state.board.token;
  const board = $("#board");
  if (!Object.keys(state.board.cols).length) board.innerHTML = COLUMNS.map(skeletonColumn).join("");
  let results;
  try {
    results = await Promise.all(COLUMNS.map((col) => api("/api/leads?" + boardQuery(col, 0))));
    if (token !== state.board.token) return;
    COLUMNS.forEach((col, i) => { state.board.cols[col.key] = { rows: results[i].rows, total: results[i].total }; });
  } catch (e) { return toast("Could not load the board: " + e.message, true); }
  const sc = sumServiceCounts(results);
  state.board.sells = !!sc;
  renderServiceTabs($("#boardServices"), sc);
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
  delegateOpen("#board", (id) => {
    const col = Object.values(state.board.cols).find((c) => c.rows.some((r) => String(r.id) === id));
    setNav("lead", col ? col.rows.map((r) => String(r.id)) : null);    // J / K move down this column
    go("lead/" + id);
  }, "[data-more]");
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
  if (state.service) p.set("service", state.service);                      // the lead-service tab (LCX Services)
  p.set("limit", state.leads.perPage);
  p.set("offset", state.leads.page * state.leads.perPage);
  return p.toString();
}

async function loadLeads() {
  const token = ++state.leads.token;
  if (!$("#leadsBody").children.length) $("#leadsBody").innerHTML = skeletonRows(6, 8);
  let d;
  try { d = await api("/api/leads?" + leadsQuery()); }
  catch (e) { return toast("Could not load leads: " + e.message, true); }
  if (token !== state.leads.token) return;
  state.leads.rows = d.rows; state.leads.total = d.total;
  state.leads.sells = Array.isArray(d.service_counts);
  renderServiceTabs($("#leadsServices"), Array.isArray(d.service_counts) ? { all: +d.service_all || 0, counts: d.service_counts } : null);
  $("#leadsCount").textContent = d.total.toLocaleString() + " " + (d.total === 1 ? (segUi().entity_label || "company") : (segUi().entity_plural || "companies"));
  const picked = state.leads.selected;
  $("#leadsTable").classList.toggle("batch", composeOn());
  $("#leadsBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr class="row-link ${picked.has(String(r.id)) ? "selected" : ""}" data-id="${esc(r.id)}" tabindex="0">
      <td class="sel-col">${canWrite(r) ? `<input type="checkbox" data-pick="${esc(r.id)}" ${picked.has(String(r.id)) ? "checked" : ""} aria-label="Pick ${esc(leadTitle(r).title)}">` : ""}</td>
      <td>${(() => { const t = leadTitle(r);
        const parts = [t.sub || (personFirst() ? (r.domain || "") : "no website yet"), r.kind ? String(r.kind).replace(/_/g, " ") : "",
          // the service its email pitches (LCX Services), when the All tab is on
          r.service && !state.service ? (SERVICE_BUCKET[r.service] || "selling " + r.service) : ""].filter(Boolean);
        return `<div class="cell-company">${monoTile(t.title, r.domain || r.id, "sm")}<span><div class="primary-cell">${esc(t.title)}</div><div class="secondary">${esc(parts.join(" · "))}</div></span></div>`; })()}</td>
      <td class="col-status">${statusLozenge(r.status)}${r.reached_by_name ? `<div class="secondary" title="Reached out by ${esc(r.reached_by || "")}">by ${esc(r.reached_by_name)}</div>` : ""}</td>
      <td class="col-score">${scoreCell(r.fit_score)}</td>
      <td class="col-source">${sourceLozenge(r.source)}</td>
      <td>${r.email ? `<span class="cell-person">${avatar(r.contact_name, r.email)}<span>${r.contact_name ? `<div>${esc(r.contact_name)}</div><div class="secondary">${esc(r.email)}</div>` : `<div>${esc(r.email)}</div>`}</span></span>` : '<span class="muted">No address</span>'}</td>
      <td class="secondary">${fieldSummary(r) || esc([r.city, r.state].filter(Boolean).join(", ") || "")}</td>
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="7">No ${esc(segUi().entity_plural || "companies")} match these filters${state.service && Array.isArray(d.service_counts) ? " for " + esc(serviceLabel(state.service)) : ""}.</td></tr>`;
  renderLeadsBatch();
  $("#leadsTable").classList.toggle("one-status", state.leads.filters.status !== "all");
  // The filter shows only where it can change what is on screen: a selection that is
  // all addresses, or none, has nothing to narrow.
  const split = $("#leadsContact");
  split.hidden = !(d.with_address && d.without_address) && !state.leads.filters.contact;
  split.options[1].textContent = `Has an address (${(d.with_address || 0).toLocaleString()})`;
  split.options[2].textContent = `No address yet (${(d.without_address || 0).toLocaleString()})`;
  delegateOpen("#leadsBody", (id) => { setNav("lead", state.leads.rows.map((r) => String(r.id))); go("lead/" + id); }, ".sel-col");
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
  // the download is not split by lead service (tools/export_leads.py): with a service tab on, the button says so
  const every = !!(state.service && state.leads.sells);
  $("#leadsExportText").textContent = every ? "Export, every service" : "Export this view";
  if (every) $("#leadsExport").title = "The download holds this view's other filters for every service: it is not split by lead service.";
  else $("#leadsExport").removeAttribute("title");
}

/* ======================================================== lead modal */
/* The score, criterion by criterion (owner's review, 2026-09-17). Every row
 * says which of three states it is in -- found, checked and nothing found, or
 * not checked yet -- why, and where the evidence is. The explanation is built
 * server-side by app/explain.py; this only draws it. */
const STATE_CLS = { found: "success", none: "", unchecked: "moved" };
function srcLinks(sources) {
  if (!sources || !sources.length) return "";
  // safeUrl: a source link is http(s) or nothing -- a stored javascript: link would run as the app
  return `<div class="crit-src">${sources.map((s) => safeUrl(s.url)
    ? `<a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.label)}${s.date ? " · " + esc(s.date) : ""} ${icon("external", 12)}</a>`
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
    <div class="next-step">${icon("arrowRight", 16)}<div><strong>Next step.</strong> ${esc(a.next_step || "")}</div></div>
    <div class="analysis-grid"><div><h4 class="sub-h">Strengths</h4>${list(a.strengths)}</div><div><h4 class="sub-h">Gaps</h4>${list(a.gaps)}</div></div>
    <h4 class="sub-h">Risks</h4>${risks}`;
}
/* Contacts include the actual email recipient and the eligible alternatives a reviewer can choose. */
function renderContacts(d) {
  const cr = (d.explain || {}).contact_routes || { routes: [], tried: [] };
  const locked = d.recipient_locked_reason;
  const draft = d.outreach && d.outreach.status === "drafted";
  const people = (d.contacts || []).map((c) => {
    const chosen = d.outreach ? c.drafts_use : String(c.id) === String(d.selected_recipient_id || "");
    const badge = chosen ? (d.outreach ? draft ? "Draft recipient" : "Email recipient" : "Selected recipient") : "";
    return `<div class="contact-row ${c.usable ? "" : "retired"}">
      ${avatar(c.full_name, c.email)}
      <div class="contact-main"><div class="who">${esc(c.full_name || "No name published")}${badge ? ` <span class="lozenge success">${badge}</span>` : ""}</div>
        ${c.role_title ? `<div class="role">${esc(c.role_title)}</div>` : ""}
        <div class="mail">${c.usable ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : c.email ? `<s>${esc(c.email)}</s>` : `<span class="muted">No email on record</span>`}${c.kind === "shared" ? " · shared inbox" : c.kind === "low_value" ? ` · <span class="warn-text">rarely read for partnerships</span>` : ""}</div>
        ${!c.usable && c.email ? `<div class="role warn-text">Not used: ${esc(c.unusable_reason)}</div>` : ""}
        ${safeUrl(c.linkedin_url) ? `<div class="role"><a href="${esc(safeUrl(c.linkedin_url))}" target="_blank" rel="noopener">LinkedIn ${icon("external", 12)}</a></div>` : ""}
        ${!locked && c.can_select_recipient && !chosen ? `<button type="button" class="btn compact contact-recipient" data-recipient="${esc(c.id)}">${draft ? "Use for draft" : "Use for future drafts"}</button>` : ""}
        ${!locked && c.email && c.usable && c.can_select_recipient === false ? `<div class="role">${esc(c.recipient_unavailable_reason || "Not eligible for sending")}</div>` : ""}
      </div></div>`;
  }).join("");
  const glyphs = { phone: "user", people: "users", website: "globe", channel: "play", podcast: "play", app: "link", social: "link" };
  const routes = (cr.routes || []).map((r) => {
    // a route links out only by http(s) or tel: -- anything else is shown as text
    const href = /^tel:[+\d\s().-]+$/i.test(String(r.url || "")) ? String(r.url) : safeUrl(r.url);
    const body = r.people ? r.people.map((p) => `${esc(p.name)}${p.role ? ` <span class="muted">(${esc(p.role)})</span>` : ""}`).join(", ")
      : href ? `<a href="${esc(href)}"${href.startsWith("tel:") ? "" : ` target="_blank" rel="noopener"`}>${esc(r.value)}</a>` : esc(r.value || "");
    return `<li>${icon(glyphs[r.kind] || "link", 14)}<span><span class="muted">${esc(r.label)}:</span> ${body}</span></li>`;
  }).join("");
  return `${people || `<p class="muted small" style="margin:0 0 8px">No email address on record.</p>`}
    ${people ? `<p class="help recipient-help" id="recipientHelp" role="status">${esc(locked || (d.recipient_selection_stale ? "Your selected contact is no longer eligible. Choose another contact before drafting or approving." : "Choose a contact to set who receives this lead's email."))}</p>` : ""}
    ${routes ? `<ul class="evidence-list routes">${routes}</ul>` : ""}
    ${(cr.tried || []).length ? `<p class="tried small muted">${cr.tried.map(esc).join(" ")}</p>` : ""}`;
}

function bindRecipientSelection(root, d, leadId) {
  const choices = $$("[data-recipient]", root), help = $("#recipientHelp", root);
  const openEmail = $("#leadOpenEmail", root);
  let busy = false;
  choices.forEach((button) => button.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    const sheet = modal.current, segment = state.segment, token = state.leadToken;
    const stillHere = () => modal.isOpen() && modal.current === sheet
      && state.segment === segment && state.leadToken === token;
    choices.forEach((b) => b.disabled = true);
    if (openEmail) openEmail.disabled = true;
    button.classList.add("loading");
    if (help) help.textContent = "Saving recipient...";
    try {
      const r = await post("/api/leads/" + encodeURIComponent(leadId) + "/recipient", { contact_id: button.dataset.recipient });
      if (!stillHere()) return;
      const refreshToken = state.leadToken + 1;
      await openLead(leadId, { quiet: true });
      if (!modal.isOpen() || state.segment !== segment || state.leadToken !== refreshToken
          || !modal.current || modal.current.kind !== "lead" || modal.current.id !== leadId) return;
      flag(r.draft_updated ? "Draft recipient changed" : "Recipient selected", { desc: "Your choice is saved for this lead." });
      refreshCurrentView();
      refreshOutreachCount(true);
    } catch (e) {
      if (!stillHere()) return;
      if (help) help.textContent = "Could not change recipient: " + e.message;
      choices.forEach((b) => b.disabled = false);
    } finally {
      busy = false;
      if (button.isConnected) {
        button.classList.remove("loading");
        choices.forEach((b) => b.disabled = false);
        if (openEmail) openEmail.disabled = false;
        if (help && help.textContent === "Saving recipient...")
          help.textContent = "Recipient saved. Reopen this lead to refresh its contacts.";
      }
    }
  }));
}
/* The lead sheet's Lead service box (LCX Services): the one service its email pitches and why, who chose it, the
   other services it fits, and the 18 to pick from. A person's pick stands (the rules never undo it), and picking or
   confirming one lifts the drafter's holds (Check service, Read site first, an audience-only pick). */
function renderLeadService(d) {
  const s = d.lead_service;
  if (!s) return "";
  const m = d.metadata || {}, was = ((m.lead_service || {}).rules_pick || {}).service;
  const head = s.service ? `<strong>${esc(s.service)}</strong>`
    : s.key ? `<span class="lozenge ${s.key === "none" ? "removed" : "moved"}">${esc(s.label || serviceLabel(s.key))}</span>`
    : `<span class="muted">Not picked yet: the next chain run picks one</span>`;
  const why = s.by_person
    ? `Picked by ${esc(s.set_by_name || s.set_by)}${s.decided_at ? ", " + esc(fmtDate(s.decided_at).split(",")[0]) : ""}${was && was !== s.service ? `<div class="small muted">The rules had picked ${esc(was)}</div>` : ""}`
    : s.reason ? `${esc(s.reason)}${s.evidence ? `<div class="small muted">${esc(s.evidence)}</div>` : ""}` : "";
  const fits = (s.also_fits || []).length ? `<dt>Also fits</dt><dd><span class="pill-list">${s.also_fits.map((x) => `<span class="tag" title="${esc(x)}"><span>${esc(x)}</span></span>`).join("")}</span></dd>` : "";
  const choices = s.choices || [];
  const pick = choices.length ? `<div class="field" style="margin-top:12px"><label for="lsPick">${s.service ? "Change service" : "Pick the service"}</label>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <select id="lsPick" class="filter" style="max-width:100%;flex:1 1 180px">${s.service ? "" : `<option value="" selected disabled>Pick a service</option>`}${choices.map((c) => `<option value="${esc(c)}" ${c === s.service ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
        <button type="button" class="btn compact" id="lsSave" disabled>Use this service</button></div>
      <div class="help" id="lsHelp"></div></div>` : "";
  return `<div class="side-group"><div class="group-head">${icon("sparkle", 16)} Lead service</div><div class="group-body">
      <div style="margin-bottom:10px" title="The one service its email pitches">${head}</div>
      ${why || fits ? `<dl class="details">${why ? `<dt>Why</dt><dd>${why}</dd>` : ""}${fits}</dl>` : ""}${pick}</div></div>`;
}
function bindLeadService(root, d, id) {
  const pick = $("#lsPick", root), save = $("#lsSave", root), help = $("#lsHelp", root);
  if (!pick || !save) return;
  const s = d.lead_service, ob = d.outreach;
  const sync = () => {
    const v = pick.value, same = v === (s.service || "");
    // the same service again: a person confirming the rules' pick, which stands from then on; theirs already does
    save.disabled = !v || (same && s.by_person);
    save.textContent = v && same && !s.by_person ? "Confirm" : "Use this service";
    help.textContent = !v ? "" : same ? (s.by_person ? "" : "Confirming keeps it: the rules will not change it later.")
      : ob && ob.status === "drafted" && ob.service === v ? `Its waiting email already pitches ${v}.`
      : ob && ob.status === "drafted" ? `Its waiting email is withdrawn and drafted again, pitching ${v}.`
      : ob && ob.sent_at ? "The email already sent keeps what it pitched."
      : ob ? "The email already approved keeps what it pitched."
      : d.status === "shortlisted" ? `Its email is drafted pitching ${v}, within minutes.` : `Its email will pitch ${v}.`;
  };
  pick.addEventListener("change", sync);
  sync();
  save.addEventListener("click", async () => {
    const v = pick.value;
    save.classList.add("loading"); save.disabled = true;
    try {
      const r = await post("/api/leads/" + id + "/service", { service: v });
      const e = r.email;
      flag("Lead service: " + v, { ms: 6000, desc: r.withdrawn
          ? "Its waiting email pitched something else, so it was withdrawn" + (r.drafting ? "; the new one appears in Outreach within minutes." : ".")
        : r.drafting ? "Its email is being drafted; it appears in Outreach within minutes."
        : e && e.status !== "drafted" ? "Its email " + (e.status === "sent" ? "already sent" : "already approved") + " keeps what it pitched" + (e.service ? " (" + e.service + ")" : "") + "."
        : "Its email pitches it." });
      await openLead(id, { quiet: true });
      refreshCurrentView();
      refreshOutreachCount(true);
    } catch (err) { toast(err.message, true); save.classList.remove("loading"); sync(); }
  });
}
/* A closed lead sheet leaves #lead/<id>, so the same card opens again on the next click. */
function leaveLeadRoute() { if (location.hash.startsWith("#lead/")) history.replaceState(null, "", "#" + currentView()); }
async function openLead(id, opts) {
  // The dialog opens on the click, not when the server answers: on a cold
  // cloud instance the fetch can take seconds, and a click that shows nothing
  // reads as a click that did nothing.
  const quiet = !!(opts && opts.quiet);
  const token = state.leadToken = (state.leadToken || 0) + 1;   // J pressed twice: only the last lead lands
  if (!quiet) {
    modal.open(`${modalHead(`${typeIcon("lead")}<span class="skel" style="width:88px;height:20px;border-radius:999px"></span>`, navButtons("lead", id))}
      <div class="modal-body single"><div class="modal-main" aria-busy="true" aria-label="Opening the lead">
        <div class="lead-hero"><span class="skel" style="width:52px;height:52px;border-radius:14px"></span>
          <div class="lead-hero-text"><span class="skel" style="width:46%;height:22px;margin-bottom:10px"></span><span class="skel" style="width:24%;height:12px"></span></div></div>
        ${[92, 84, 88, 60].map((w) => `<span class="skel" style="width:${w}%;height:12px;margin:14px 0"></span>`).join("")}
        <span class="skel" style="width:100%;height:120px;margin-top:24px;border-radius:12px"></span></div></div>`,
      { label: "Opening the lead", sheet: true, onClose: leaveLeadRoute });
    modal.current = { kind: "lead", id };
    bindNav($("#modalRoot"));
  }
  let d;
  try { d = await api("/api/leads/" + id); }
  catch (e) {
    if (token !== state.leadToken) return;
    if (!quiet) { modal.close(true); leaveLeadRoute(); }
    return toast("Could not load company: " + e.message, true);
  }
  // a newer lead was asked for, or the sheet was closed while this one loaded: it does not pop back
  if (token !== state.leadToken || !modal.isOpen()) return;
  const m = d.metadata || {}, research = m.p1_research || {};
  const score = +d.fit_score || 0;
  const decided = d.status === "shortlisted" || d.status === "rejected";
  const contacts = renderContacts(d);
  const pills = [sourceLozenge(d.source)];
  if (m.subtype) pills.push(`<span class="tag">${esc(String(m.subtype).replace(/_/g, " "))}</span>`);
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
  (m.genres || []).slice(0, 4).forEach((g) => pills.push(`<span class="tag">${esc(g)}</span>`));
  (m.platform_relationships || []).slice(0, 4).forEach((g) => pills.push(`<span class="tag">${esc(g)}</span>`));
  const t = leadTitle(d), hosted = personFirst() && hostOf(d) && !t.same;

  modal.open(`
    ${modalHead(`${typeIcon("lead")}${statusLozenge(d.status)}`,
      (d.domain ? `<a class="btn compact site-btn" href="https://${esc(d.domain)}" target="_blank" rel="noopener" title="${esc(d.domain)}">${icon("external", 14)}<span class="dom">${esc(d.domain)}</span></a>` : "")
      + navButtons("lead", id))}
    <div class="modal-body">
      <div class="modal-main">
        <div class="lead-hero">${monoTile(hosted ? t.title : d.name, d.domain || d.id, "lg")}
          <div class="lead-hero-text"><h2 class="modal-title">${esc(hosted ? t.title : d.name)}</h2>
            ${hosted ? `<p class="lead-hero-sub">Host of <strong>${esc(d.name)}</strong></p>` : ""}</div>
          ${unscoredProject() ? "" : `<div class="lead-hero-score">${scoreRing(score, 56)}<span class="small">fit score</span></div>`}</div>
        <div class="pill-list lead-tags">${pills.join("")}</div>

        ${d.explain ? `<div class="section"><h3>${icon("sparkle", 16)} Analysis</h3><div class="body">${renderAnalysis(d.explain)}</div></div>` : ""}

        ${d.explain && !(d.explain.criteria || []).length ? "" : `<div class="section"><h3>${icon("chart", 16)} Score breakdown</h3>
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

        ${renderLeadService(d)}
        <div class="side-group"><div class="group-head">${icon("users", 16)} Contacts</div><div class="group-body">${contacts}</div></div>
        ${(() => {   // who reached out, from which address, when (owner, 2026-09-26)
          const ob = d.outreach;
          if (!ob || !(ob.sent_at || ["approved", "sending", "send_unknown"].includes(ob.status))) return "";
          return `<div class="side-group"><div class="group-head">${icon("send", 16)} Outreach</div><div class="group-body"><dl class="details">
            <dt>${ob.sent_at ? "Reached out by" : "Approved by"}</dt><dd>${esc(ob.approved_by_name || ob.approved_by || "—")}${ob.sender_address ? `<div class="small muted">from ${esc(ob.sender_address)}</div>` : ""}</dd>
            ${ob.service ? `<dt>${ob.sent_at ? "Pitched" : "Pitches"}</dt><dd>${esc(ob.service)}</dd>` : ""}
            ${!ob.sent_at && ob.schedule && ob.schedule.held ? `<dt>Goes out</dt><dd>Held back, not sent<div class="small muted">${esc(ob.schedule.held_why || "")}</div></dd>`
              : !ob.sent_at && ob.schedule ? `<dt>Goes out</dt><dd>${esc(whenText(ob.schedule))}${ob.schedule.send_tz_reason ? `<div class="small muted">${esc(ob.schedule.send_tz_reason)}</div>` : ""}</dd>`
              : `<dt>${ob.sent_at ? "Sent" : "Status"}</dt><dd>${ob.sent_at ? esc(fmtDate(ob.sent_at)) : "Approved, waiting to go out"}</dd>`}
          </dl></div></div>`; })()}
        ${det ? `<div class="side-group"><div class="group-head">Details</div><div class="group-body"><dl class="details">${det}</dl></div></div>` : ""}
        <div class="timestamps">Created ${fmtDate(d.created_at)}<br>Updated ${fmtDate(d.updated_at || d.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      ${decided ? `<button class="btn subtle" data-decide="reset">Undo decision</button>` : ""}
      ${d.status !== "rejected" ? `<button class="btn subtle danger-text" data-decide="reject">Reject</button>` : ""}
      ${d.outreach && d.outreach.id ? `<button class="btn primary" id="leadOpenEmail">${icon("mail", 16)} ${d.outreach.status === "drafted" ? "Open draft" : "View email"}</button>` : ""}
      ${canWriteLead(d) ? `<button class="btn ${d.status === "shortlisted" ? "primary" : ""}" data-compose>${icon("mail", 16)} Write email</button>` : ""}
      ${d.status !== "shortlisted" ? `<button class="btn primary" data-decide="shortlist">${icon("check", 16)} Shortlist</button>` : ""}
    </div>`, { label: d.name, sheet: true, onClose: leaveLeadRoute });

  const root = $("#modalRoot");
  modal.current = { kind: "lead", id };
  bindNav(root);
  const showReason = () => { $("#reasonBox", root).hidden = false; $("#rejectReason", root).focus(); };
  $$("[data-decide]", root).forEach((b) => b.addEventListener("click", () => {
    const what = b.dataset.decide;
    if (what === "reject") return showReason();
    decide(id, what, "");
  }));
  $("#reasonCancel", root).addEventListener("click", () => { $("#reasonBox", root).hidden = true; });
  $("#reasonGo", root).addEventListener("click", () => decide(id, "reject", $("#rejectReason", root).value));
  const w = $("[data-compose]", root);
  if (w) w.addEventListener("click", () => openCompose([{ id: String(d.id || id), name: d.name }]));
  const email = $("#leadOpenEmail", root);
  if (email) email.addEventListener("click", () => openLeadEmail(id, d.outreach.id, email));
  bindRecipientSelection(root, d, id);
  bindLeadService(root, d, id);
}

async function openLeadEmail(leadId, emailId, button) {
  if (button.disabled) return;
  const sheet = modal.current, segment = state.segment, leadToken = state.leadToken;
  const stillHere = () => modal.isOpen() && modal.current === sheet
    && state.segment === segment && state.leadToken === leadToken
    && sheet && sheet.kind === "lead" && sheet.id === leadId;
  button.disabled = true; button.classList.add("loading");
  try {
    // Fetch the exact email: it may be on another page or hidden by an Outreach filter.
    const [email, mailboxes] = await Promise.all([
      api("/api/outreach/" + encodeURIComponent(emailId)),
      api("/api/mailboxes").catch(() => null),
    ]);
    if (!stillHere()) return;
    if (mailboxes) {
      state.outreach.canSend = !!mailboxes.can_send;
      state.outreach.paused = mailboxes.paused || null;
      state.outreach.mbx = mailboxes;
    }
    leaveLeadRoute();
    openMessage(emailId, email);
  } catch (e) {
    if (stillHere()) toast("Could not open email: " + e.message, true);
  } finally {
    if (button.isConnected) { button.disabled = false; button.classList.remove("loading"); }
  }
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
function draftsOn() {
  // A cached pause or a project with no templates must never hide existing drafts.
  return outreachPolicy().drafts !== false || (state.outreach.counts.drafts || 0) > 0;
}
function followUpsOn() { return !!(outreachPolicy().follow_ups || {}).enabled; }
function stepLozenge(r) {
  const n = +r.sequence_step || 0;
  return n > 0 ? `<span class="lozenge new" title="Follow-up in the same thread">Follow-up ${n}</span> ` : "";
}

/* ------------------------------------------------------------ when it goes
   Each approved email goes out at its own random second, 10:00-10:30 on its recipient's clock (owner,
   2026-10-12: "some must be going at 10:17 some at 10:13"). The server writes the words
   (tools/send_window.py): "Tue 14 Oct, 10:17 New York time (19:47 IST)" -- the recipient's clock, then
   India's. The page adds the viewer's own clock only where it is neither, and keeps every older sentence
   where an email has no time (a project without outreach.send_window). */
function sendWindow() { return outreachPolicy().send_window || null; }
function windowSpan() { const w = sendWindow() || {}; return `${w.start || "10:00"} and ${w.end || "10:30"}`; }
/* Whose clock the window is on (review, 2026-10-12): the recipient's, or -- with timezone_of "sender" -- every
   email at 10:00-10:30 on the sender's, India's. Every sentence below asks these, never says "recipient's" blindly. */
function onSenderClock() { return (sendWindow() || {}).timezone_of === "sender"; }
function senderPlace() { return (sendWindow() || {}).sender_place || "India"; }
function itsClock() { return onSenderClock() ? `${senderPlace()}'s clock` : "its recipient's clock"; }
function itsZone() { return onSenderClock() ? `${senderPlace()}'s time zone` : "its recipient's time zone"; }
function itsWindow() { return onSenderClock() ? `its window on ${senderPlace()}'s clock` : "its recipient's window"; }
function nextWindow() { return onSenderClock() ? `the next window on ${senderPlace()}'s clock` : "the recipient's next window"; }
function clockAt(iso, tz) {
  try {
    return new Date(iso).toLocaleString("en-GB", Object.assign({ weekday: "short", hour: "2-digit", minute: "2-digit",
      hourCycle: "h23" }, tz ? { timeZone: tz } : {}));
  } catch (e) { return ""; }
}
/* "Tue 19:47" on this browser's clock, when that is neither the recipient's nor the sender's (India) */
function yourClock(s) {
  if (!s || !s.send_after) return "";
  const mine = clockAt(s.send_after);
  const sender = (sendWindow() || {}).sender_timezone || "Asia/Kolkata";
  return mine && mine !== clockAt(s.send_after, s.send_tz) && mine !== clockAt(s.send_after, sender) ? mine : "";
}
function whenText(s) { const y = yourClock(s); return s.send_label + (y ? `; ${y} your time` : ""); }
/* An approved email's own moment, for the sheet's foot: when, from whom, and why it moved if it did */
function goesOutNote(r, name) {
  const s = r.schedule;
  if (!s) return null;
  const by = name ? `Approved by ${name}. ` : "Approved. ";
  // held back (a send error, or sending paused): it goes on no day, so no time is promised (review, 2026-10-12)
  if (s.held) return `${by}Held back, not sent: ${s.held_why}.`;
  if (s.reschedules > 0 && s.wait_why) return `${by}Its earlier window passed unsent (${s.wait_why}): now ${whenText(s)}.`;
  return `${by}Goes out ${whenText(s)}${name ? ", from their address" : ""}.`;
}
/* "9 on Tue 14 Oct (6 New York, 3 UK), 3 on Wed 15 Oct (New York)": a batch's times, by the recipients' days */
function windowsText(ws) {
  return (ws || []).map((d) => `${d.count} on ${d.label}` + ((d.places || []).length
    ? ` (${d.places.length > 1 ? d.places.map(([p, n]) => n + " " + p).join(", ") : d.places[0][0]})` : "")).join(", ");
}
/* "3 on Tue 14 Oct, 2 on Wed 15 Oct": approved emails by the day they go out, on India's clock */
function scheduledText(days) { return (days || []).map((d) => `${d.count} on ${d.label}`).join(", "); }
async function loadOutreach() {
  const o = state.outreach, token = ++o.token;
  if (!$("#outreachBody").children.length) $("#outreachBody").innerHTML = skeletonRows(5, 8);
  let d;
  const query = new URLSearchParams({ folder: o.folder, category: o.category, service: o.service,
    sort: o.sort, direction: o.direction, limit: o.limit, offset: o.offset });
  try { d = await api("/api/outreach?" + query); }
  catch (e) { return toast("Could not load outreach: " + e.message, true); }
  // can an approval go out from here? (a connected mailbox) -- it words what "approve" does. Where each
  // person sends from their own Gmail, every person and address is listed with today's count instead.
  api("/api/mailboxes").then((m) => {
    o.canSend = !!m.can_send; o.paused = m.paused || null; o.mbx = m;
    if (m.mode === "approver") { $("#sendCounter").hidden = true; renderMailboxStrip(m); }
    else { $("#mailboxStrip").hidden = true; renderSendCounter(m); }
  }).catch(() => { $("#sendCounter").hidden = true; $("#mailboxStrip").hidden = true; });
  if (token !== o.token) return;
  o.rows = d.rows; o.counts = d.counts || {};
  const total = d.total ?? d.rows.length;
  if (o.offset && o.offset >= total) {
    o.offset = total ? Math.floor((total - 1) / o.limit) * o.limit : 0;
    return loadOutreach();
  }
  renderOutreachFilters(d);
  // Decide only after reading the folder counts. The project's cached policy
  // can say drafting is off while reviewed or externally written drafts exist.
  if (o.folder === "drafts" && !draftsOn()) {
    o.folder = "outbox";
    return loadOutreach();
  }
  const present = new Set(d.rows.filter((r) => !r.approval_blocked).map((r) => r.id));
  o.selected = new Set([...(o.selected || [])].filter((id) => present.has(id)));
  const batch = batchOn() && o.folder === "drafts" && d.rows.length > 0;
  $("#outreachTable").classList.toggle("batch", batch);
  $("#folderTabs").innerHTML = FOLDERS.filter(([key]) => (key !== "attention" || o.counts.attention || o.folder === "attention")
      && (key !== "drafts" || draftsOn())).map(([key, label]) =>
    `<button class="tab ${key === o.folder ? "active" : ""}" role="tab" aria-selected="${key === o.folder}" data-f="${key}">${label}<span class="pts">${(d.filtered_counts || o.counts)[key] || 0}</span></button>`).join("");
  $$("#folderTabs .tab").forEach((b) => b.addEventListener("click", () => {
    o.folder = b.dataset.f; o.offset = 0; o.selected.clear(); history.replaceState(null, "", "#outreach/" + o.folder); loadOutreach();
  }));
  $("#outreachBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr class="row-link" data-id="${esc(r.id)}" tabindex="0">
      <td class="sel-col"><input type="checkbox" data-sel="${esc(r.id)}" ${o.selected.has(r.id) ? "checked" : ""} ${r.approval_blocked ? `disabled title="${esc(r.approval_blocked)}"` : ""} aria-label="Select this draft"></td>
      <td><div class="cell-company">${monoTile(r.company, r.domain || r.entity_id, "sm")}<span><div class="primary-cell">${esc(r.company)}</div><div class="secondary">${esc(r.domain || "")}</div>${outreachMetric(r)}</span></div></td>
      <td>${r.contact_email ? `<span class="cell-person">${avatar(r.contact_name, r.contact_email)}<span><div>${esc(r.contact_name || "Unnamed")}</div><div class="secondary">${esc(r.contact_email)}</div></span></span>` : '<span class="muted">No address</span>'}</td>
      <td><div class="subject-cell">${r.direction === "inbound" ? mailLozenge(r) : ""}${stepLozenge(r)}<span class="subj">${esc(r.subject || "(no subject)")}</span>${files(r).length ? `<span class="clip" title="${esc(files(r).map((f) => f.name).join(", "))}">${icon("paperclip", 14)}</span>` : ""}</div>${r.service ? `<div class="secondary" title="The one service this email ${r.sent_at ? "pitched" : "pitches"}">${r.sent_at ? "Pitched" : "Pitches"} ${esc(r.service)}</div>` : ""}${r.approval_blocked ? `<div class="secondary outreach-hold">${esc(r.approval_blocked)}</div>` : ""}${r.send_error ? `<div class="secondary" style="color:var(--text-danger)">${esc(r.send_error)}</div>` : ""}</td>
      <td class="by-col">${r.approved_by ? `<div>${esc(r.approved_by_name || r.approved_by)}</div>${r.sender_address ? `<div class="secondary">${esc(r.sender_address)}</div>` : ""}` : ""}</td>
      ${(() => {   // when it last moved: sent, approved, or written -- not the draft's age on every tab
        const s = r.schedule;
        if (s && s.held && !r.sent_at && r.status === "approved") {
          // held back: no time, because none will come (review, 2026-10-12); why, on hover and under the subject
          return `<td class="nowrap when-cell" title="${esc("Held back, not sent: " + (s.held_why || ""))}"><div>Held</div><div class="secondary">${r.send_error ? "not sending" : "sending paused"}</div></td>`;
        }
        if (s && !s.held && !r.sent_at && ["approved", "sending"].includes(r.status)) {
          // Approved is the queue: when each one goes, on its recipient's clock (and the viewer's, if neither)
          const y = yourClock(s);
          return `<td class="nowrap when-cell" title="${esc(whenText(s) + (s.send_tz_reason ? " · " + s.send_tz_reason : "")
            + (s.reschedules && s.wait_why ? " · moved: " + s.wait_why : ""))}"><div>${esc(s.send_short)}</div>${y
            ? `<div class="secondary">${esc(y)} your time</div>` : s.reschedules ? `<div class="secondary">moved ${s.reschedules}×</div>` : ""}</td>`;
        }
        const at = r.sent_at || (r.status === "approved" ? r.approved_at : null) || r.created_at;
        const what = r.sent_at ? "Sent" : r.status === "approved" && r.approved_at ? "Approved" : r.direction === "inbound" ? "Received" : "Written";
        return `<td class="secondary nowrap" title="${esc(what + " " + fmtDate(at))}">${rel(at)}</td>`; })()}
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="6">${o.category || o.service ? "No emails match these filters. Clear the filters to see all categories." : o.folder === "drafts"
        ? "No drafts waiting. Shortlist a company on the board and its email is drafted here within minutes."
        : o.folder === "outbox" && composeOn() ? "Nothing waiting to go out. To write to leads, pick them on the Leads page."
        : "Nothing in this folder yet."}</td></tr>`;
  // who reached out: the person who approved it, from which address (owner, 2026-09-26)
  $("#outreachTable").classList.toggle("show-by", ["outbox", "sent", "attention"].includes(o.folder));
  // the Approved folder is a queue with times in it where the project has a sending window
  $("#outreachWhenCol").textContent = o.folder === "outbox" && sendWindow() ? "Goes out" : "When";
  delegateOpen("#outreachBody", (id) => { setNav("mail", state.outreach.rows.map((r) => String(r.id))); openMessage(id); }, ".sel-col");
  $$("#outreachBody [data-sel]").forEach((c) => c.addEventListener("change", () => {
    if (c.checked) o.selected.add(c.dataset.sel); else o.selected.delete(c.dataset.sel);
    renderBatchBar();
  }));
  renderBatchBar();
  const start = total ? o.offset + 1 : 0, end = Math.min(o.offset + o.rows.length, total);
  $("#outreachPager").innerHTML = `<span class="info">${start}–${end} of ${total}</span>
    <button class="btn compact" data-page="prev" ${o.offset ? "" : "disabled"}>Previous</button>
    <button class="btn compact" data-page="next" ${end < total ? "" : "disabled"}>Next</button>`;
  $$("#outreachPager [data-page]").forEach((b) => b.addEventListener("click", () => {
    o.offset = Math.max(0, o.offset + (b.dataset.page === "next" ? o.limit : -o.limit));
    o.selected.clear(); loadOutreach();
  }));
  updateOutreachCount(o.counts);
}

function renderOutreachFilters(d) {
  const o = state.outreach;
  const options = (rows, all, value) => `<option value="">${all}</option>` + (rows || []).map((r) =>
    `<option value="${esc(r.key)}" ${value === r.key ? "selected" : ""}>${esc(r.label || r.key)} (${r.n})</option>`).join("");
  const defaultLabel = o.folder === "drafts" && segUi().prioritize_fresh_leads ? "Priority: fresh + high score" : "Default order";
  const sorts = [["default:desc", defaultLabel], ["subscribers:desc", "Subscriber count: high to low"],
    ["subscribers:asc", "Subscriber count: low to high"], ["views:desc", "Views: high to low"], ["views:asc", "Views: low to high"],
    ["score:desc", "Lead score: high to low"], ["score:asc", "Lead score: low to high"],
    ["date:desc", "Date: newest first"], ["date:asc", "Date: oldest first"]];
  $("#outreachFilters").innerHTML = `<label>Category <select id="outreachCategory">${options(d.categories, "All categories", o.category)}</select></label>
    ${(d.services || []).length ? `<label>Service <select id="outreachService">${options(d.services, "All services", o.service)}</select></label>` : ""}
    <label>Sort by <select id="outreachSort">${sorts.map(([key, label]) => `<option value="${key}" ${key === o.sort + ":" + o.direction ? "selected" : ""}>${label}</option>`).join("")}</select></label>
    ${o.category || o.service || o.sort !== "default" ? '<button class="btn subtle compact" id="outreachReset">Reset</button>' : ""}
    ${["subscribers", "views"].includes(o.sort) ? '<span class="small muted">Unknown metrics appear last.</span>' : ""}
    <div class="pager" id="outreachPager" aria-label="Outreach pages"></div>`;
  const change = () => { o.offset = 0; o.selected.clear(); loadOutreach(); };
  $("#outreachCategory").addEventListener("change", (e) => { o.category = e.target.value; change(); });
  $("#outreachService")?.addEventListener("change", (e) => { o.service = e.target.value; change(); });
  $("#outreachSort").addEventListener("change", (e) => { [o.sort, o.direction] = e.target.value.split(":"); change(); });
  $("#outreachReset")?.addEventListener("click", () => { o.category = o.service = ""; o.sort = "default"; o.direction = "desc"; change(); });
}

function outreachMetric(row) {
  const key = state.outreach.sort;
  const [label, value] = key === "subscribers" ? ["Subscribers", row.subscriber_count]
    : key === "views" ? ["Views", row.view_count] : ["Lead score", row.lead_score];
  if (value == null && !["subscribers", "views", "score"].includes(key)) return "";
  return `<div class="secondary">${label}: ${value == null ? "Unknown" : esc(Number(value).toLocaleString())}</div>`;
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
  const available = o.rows.filter((r) => !r.approval_blocked).length;
  const all = $("#outreachSelAll"), cap = Math.min(available, pol.max_batch || available);
  all.disabled = !cap;
  all.checked = n > 0 && n >= cap;
  all.indeterminate = n > 0 && n < cap;
  all.setAttribute("aria-label", "Select the first " + cap + " drafts"); all.title = "Select the first " + cap + " drafts";
  $("#batchGo").addEventListener("click", startBatch);
}

async function startBatch() {
  const o = state.outreach, ids = [...o.selected];
  const expected = expectedRecipients(o.rows, ids);
  const btn = $("#batchGo");
  btn.classList.add("loading");
  let s;
  try { s = await post("/api/outreach/batch/sample", { ids, ...(expected ? { expected_recipients: expected } : {}) }); }
  catch (e) { btn.classList.remove("loading"); return toast(e.message, true); }
  btn.classList.remove("loading");
  const byId = Object.fromEntries(o.rows.map((r) => [r.id, r]));
  const sample = s.sample.map((id) => byId[id]).filter(Boolean);
  const n = s.approvable.length;
  modal.open(`
    ${modalHead(`${icon("check", 16)}<span>Approve ${n} draft${n === 1 ? "" : "s"}</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <div class="section-msg">${icon("info", 24)}<div><div class="title">Read these ${sample.length} first</div>
        <div class="text">The server picked them at random from your selection. Approval unlocks when every one is ticked. Everything approved is sent exactly as written, and your name is recorded against the batch.${sendWindow() ? ` Each goes out between ${esc(windowSpan())} in ${esc(itsZone())}, at its own minute.` : ""}${s.generated ? " This batch contains drafts whose opening line a model wrote, so the sample is larger." : ""}</div></div></div>
      ${s.skipped.length ? `<div class="section-msg warning">${icon("warn", 24)}<div><div class="title">${s.skipped.length} will not be approved</div>
        <div class="text">${s.skipped.map((x) => esc((byId[x.id] || {}).company || x.id) + ": " + esc(x.reason)).join("<br>")}</div></div></div>` : ""}
      ${sample.map((r, i) => `<div class="sample-item">
        <div class="sample-head"><span class="cell-person">${avatar(r.contact_name, r.contact_email)}<span>
          <div class="primary-cell">${stepLozenge(r)}${esc(r.subject || "(no subject)")}</div>
          <div class="secondary">${esc(r.company)} · ${esc(r.contact_email || "")}${r.service ? " · pitches " + esc(r.service) : ""}</div></span></span>
          <button class="btn subtle compact" data-read="${i}">Read</button></div>
        <div class="mail-body" data-body="${i}" hidden>${esc(r.body || "")}</div>${attachList(r)}
        <label class="check" style="margin-top:8px"><input type="checkbox" data-ok="${i}" disabled><span>I read this and it's right to send</span></label>
      </div>`).join("")}
    </div></div>
    <div class="modal-foot"><span class="left" id="batchLeft">0 of ${sample.length} checked</span>
      <button class="btn subtle" data-close>Cancel</button>
      <button class="btn primary" id="batchApprove" disabled>${icon("check", 16)} Approve ${n}</button></div>`,
    { label: "Approve drafts", medium: true });
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
      const guard = expected ? { expected_recipients: Object.fromEntries(s.approvable.map((id) => [id, expected[id]])) } : {};
      const r = await post("/api/outreach/batch/approve", { ids: s.approvable, sample: s.sample, token: s.token, ...guard });
      modal.close(true);
      o.selected.clear();
      // with a sending window: when they go, by their recipients' own days (owner, 2026-10-12). A paused project's
      // are held, and a held email is never promised a day, skipped drafts or not (second review, 2026-10-12)
      const held = "They wait in Approved: sending is paused for this project.";
      const when = !r.paused && (r.windows || []).length ? "Each at its own minute, " + windowSpan().replace(" and ", "-")
        + " on " + itsClock() + ": " + windowsText(r.windows) + "." : "";
      flag("Approved " + r.approved + " draft" + (r.approved === 1 ? "" : "s"), {
        desc: r.skipped.length ? r.skipped.length + " skipped: " + [...new Set(r.skipped.map((x) => x.reason))].join("; ")
                                 + (r.paused ? ". " + held : when ? ". " + when : "")
                               : r.paused ? held
                               : when ? when + (r.can_send ? "" : " They go once a mailbox is connected.")
                               : (r.can_send ? "They go out within minutes, inside today's sending limit."
                                             : "They go out as soon as a mailbox is connected."),
        kind: r.skipped.length ? "info" : "", ms: when ? 9000 : undefined });
      await loadOutreach();
    } catch (err) { toast(err.message, true); b.classList.remove("loading"); b.disabled = false; }
  });
}

/* ------------------------------------------------------------ writing one
   An email a person writes to the leads they picked (the Universal project; the owner, 2026-09-27: "in the
   universal segment there should be a widget to send mail to them"). The server checks every recipient the
   way an approval does and says who is skipped and why (tools/outreach_compose.py); the page shows the
   email as each of them will read it, footer and all; approving it makes one approved email per company,
   sent from the writer's own Gmail inside that address's daily limit. Nothing is drafted in between. */
const WRITABLE = ["discovered", "enriched", "scored", "ready_for_review", "shortlisted"];
const COMPOSE_FIELDS = ["first_name", "company"];
/* Rewrite is a proposal in the editor. Saving or approving remains a separate action. */
function rewritePanel() {
  return `<details class="email-rewrite"><summary>${icon("sparkle", 16)} Rewrite with AI</summary>
    <div class="field"><label for="rewriteInstructions">How should it change?</label>
      <textarea id="rewriteInstructions" class="rewrite-instructions" maxlength="2000" rows="2"
        placeholder="For example: make this shorter and more conversational."></textarea></div>
    <div class="rewrite-actions"><button type="button" class="btn compact" id="rewriteGo">${icon("sparkle", 16)} Rewrite draft</button>
      <button type="button" class="btn compact subtle" id="rewriteUndo" hidden>Undo rewrite</button></div>
    <div class="help" id="rewriteStatus" role="status">Review the result and edit anything before saving or approving.</div></details>`;
}

function bindRewrite(root, subject, body, endpoint, changed = () => {}) {
  const go = $("#rewriteGo", root), undo = $("#rewriteUndo", root), status = $("#rewriteStatus", root);
  let before = null, busy = false;
  go.addEventListener("click", async () => {
    if (busy) return;
    if (!subject.value.trim() || !body.value.trim()) { status.textContent = "Write a subject and email first."; return; }
    busy = true;
    const snapshot = { subject: subject.value, body: body.value, ai_rewritten: body.dataset.aiRewritten === "true" };
    const controls = $$("button, input, textarea", root).map((el) => [el, el.disabled]);
    const oldGuard = modal.guard, busyGuard = () => false;
    modal.guard = busyGuard;
    controls.forEach(([el]) => { el.disabled = true; });
    go.classList.add("loading"); status.textContent = "Rewriting your draft…";
    try {
      const result = await post(endpoint, { ...snapshot, instructions: $("#rewriteInstructions", root).value });
      if (!body.isConnected) return;
      before = snapshot; subject.value = result.subject; body.value = result.body; body.dataset.aiRewritten = "true";
      undo.hidden = false;
      status.textContent = "Rewritten. Review it before saving or approving.";
    } catch (e) { if (body.isConnected) status.textContent = e.message; }
    finally {
      busy = false;
      if (modal.guard === busyGuard) modal.guard = oldGuard;
      controls.forEach(([el, disabled]) => { if (el.isConnected) el.disabled = disabled; });
      go.classList.remove("loading");
      if (body.isConnected) changed();
    }
  });
  undo.addEventListener("click", () => {
    if (!before || busy) return;
    subject.value = before.subject; body.value = before.body; body.dataset.aiRewritten = String(before.ai_rewritten); before = null; undo.hidden = true;
    status.textContent = "Restored the previous draft."; changed();
  });
}

function composeOn() { return !!outreachPolicy().compose; }
function canWrite(r) { return composeOn() && !!r.email && WRITABLE.includes(r.status); }
function canWriteLead(d) {
  return composeOn() && WRITABLE.includes(d.status) && !d.outreach
    && (d.contacts || []).some((c) => c.usable && c.email);
}
/* the fields filled in as the server fills them (tools/outreach_compose.render): {{company}}'s reads "Angel Studios'" */
function composeFill(text, f) {
  const poss = (n) => n + (/s$/i.test(n) ? "'" : "'s");
  return String(text || "")
    .replace(/{{\s*company\s*}}(['’])s/g, (_, a) => poss(f.company).replace("'", a))
    .replace(/{{\s*first_name\s*}}/g, f.first_name)
    .replace(/{{\s*company\s*}}/g, f.company);
}
function composeUnknown(text) {
  const bad = new Set();
  String(text || "").replace(/{{\s*(\w+)\s*}}/g, (_, k) => { if (!COMPOSE_FIELDS.includes(k)) bad.add(k); return ""; });
  return [...bad];
}

function renderLeadsBatch() {
  const bar = $("#leadsBatch"), sel = state.leads.selected, n = sel.size;
  const all = $("#leadsSelAll"), here = state.leads.rows.filter(canWrite);
  if (all) {
    const on = here.filter((r) => sel.has(String(r.id))).length;
    all.checked = here.length > 0 && on === here.length;
    all.indeterminate = on > 0 && on < here.length;
    all.disabled = !here.length;
  }
  bar.hidden = !(composeOn() && n);
  if (bar.hidden) return;
  bar.innerHTML = `<span><strong>${n}</strong> picked</span>
    <span class="small muted">One email, written once, goes to each of them: you see how it reads for every one before it goes.</span>
    <span class="grow"></span>
    <button class="btn subtle" id="leadsSelClear">Clear</button>
    <button class="btn primary" id="leadsCompose">${icon("mail", 16)} Write email to ${n}</button>`;
}
function bindLeadsCompose() {
  const picked = state.leads.selected;
  $("#leadsBody").addEventListener("change", (e) => {
    const t = e.target.closest("[data-pick]");
    if (!t) return;
    const r = state.leads.rows.find((x) => String(x.id) === t.dataset.pick);
    if (t.checked && r) picked.set(String(r.id), { id: String(r.id), name: leadTitle(r).title });
    else picked.delete(t.dataset.pick);
    t.closest("tr").classList.toggle("selected", t.checked);
    renderLeadsBatch();
  });
  $("#leadsSelAll").addEventListener("change", (e) => {
    state.leads.rows.filter(canWrite).forEach((r) => {
      if (e.target.checked) picked.set(String(r.id), { id: String(r.id), name: leadTitle(r).title });
      else picked.delete(String(r.id));
    });
    $$("#leadsBody [data-pick]").forEach((c) => { c.checked = picked.has(c.dataset.pick); c.closest("tr").classList.toggle("selected", c.checked); });
    renderLeadsBatch();
  });
  $("#leadsBatch").addEventListener("click", (e) => {
    if (e.target.closest("#leadsSelClear")) { picked.clear(); loadLeads(); }
    else if (e.target.closest("#leadsCompose")) openCompose([...picked.values()]);
  });
}

async function openCompose(leads) {
  const ids = leads.map((l) => String(l.id));
  leaveLeadRoute();                    // opened from a lead: that lead's sheet is gone, and must open again later
  modal.open(`${modalHead(`${typeIcon("mail")}<span class="key">New email</span>`)}
    <div class="modal-body single"><div class="modal-main" aria-busy="true" aria-label="Checking who it can go to">
      ${[30, 100, 100].map((w, i) => `<span class="skel" style="width:${w}%;height:${i ? 38 : 14}px;margin:${i ? 14 : 0}px 0"></span>`).join("")}
      <span class="skel" style="width:100%;height:220px;margin-top:14px;border-radius:12px"></span></div></div>`,
    { label: "New email", sheet: true });
  let chk;
  try { chk = await post("/api/outreach/compose/check", { ids }); }
  catch (e) { modal.close(true); return toast(e.message, true); }
  if (!modal.isOpen()) return;
  const c = { ready: chk.ready.slice(), at: 0 };
  // a project may start the box from its own email (outreach.compose_start; LCX Services: every LCX
  // service in one email), sent as it is or changed first; otherwise it starts from the greeting
  const GREETING = "Hi {{first_name}},\n\n", preset = outreachPolicy().compose_start;
  const start = preset ? preset.body : GREETING, startSubject = preset ? preset.subject : "";
  const boxes = (chk.mailboxes || []).filter((b) => b.usable);
  const room = boxes.reduce((a, b) => a + Math.max(0, b.remaining), 0);
  const from = chk.paused
    ? `<p class="small">Sending is paused for this project: what you approve waits in Approved.</p>`
    : boxes.length ? boxes.map((b) => {
        const used = b.daily_cap ? Math.min(100, Math.round(100 * b.out_today / b.daily_cap)) : 0;
        return `<div class="from-box"><div class="truncate"><strong>${esc(b.address)}</strong></div>
          <div class="from-meter"><span class="meter ${b.remaining > 0 ? "hi" : "full"}"><i style="width:${used}%"></i></span>
          <span class="small muted">${b.remaining} of ${b.daily_cap} left today</span></div></div>`; }).join("")
    : `<p class="small">You have no Gmail connected yet. What you approve waits in Approved until you connect one (account menu, Your Gmail).</p>`;

  modal.open(`
    ${modalHead(`${typeIcon("mail")}<span class="key">New email</span>`)}
    <div class="modal-body">
      <div class="modal-main compose-main">
        <div class="compose-to"><span class="label">To</span><span id="cTo"></span></div>
        <div class="field"><label for="cSubject">Subject</label>
          <input id="cSubject" type="text" maxlength="200" autocomplete="off" autofocus value="${esc(startSubject)}"></div>
        <div class="field"><div class="label-row"><label for="cBody">Email</label>
          <span class="insert"><span class="small muted">Insert</span>
            <button type="button" class="btn compact" data-insert="first_name">First name</button>
            <button type="button" class="btn compact" data-insert="company">Company</button></span></div>
          <textarea id="cBody" class="compose-body${preset ? " long" : ""}">${esc(start)}</textarea>
          <div class="help">${preset ? "This project's email is already in: send it as it is, or change anything first."
            : "Write it once."} {{first_name}} and {{company}} become each person's own; your sign-off goes under it.</div>
          <div class="field-error" id="cErr" role="alert" hidden></div></div>
        ${rewritePanel()}
        <div class="compose-preview" id="cPreviewBox">
          <div class="preview-head"><span class="small muted">How it reads for</span> <strong id="cWho"></strong><span class="grow"></span>
            <span class="pos num small muted" id="cPos"></span>
            <button type="button" class="btn icon" id="cPrev" aria-label="Previous person">${icon("chevLeft", 18)}</button>
            <button type="button" class="btn icon" id="cNext" aria-label="Next person">${icon("chevRight", 18)}</button></div>
          <div class="mail-preview"><div class="mp-subject" id="cPrevSubject"></div><div class="mp-body" id="cPreview"></div></div>
        </div>
      </div>
      <div class="modal-side">
        <div class="side-group"><div class="group-head">${icon("send", 16)} Sends from</div><div class="group-body" id="cFrom">${from}</div></div>
        <div class="side-group"><div class="group-head">${icon("users", 16)} Goes to <span class="pts" id="cCount"></span></div>
          <div class="group-body"><ul class="rcpt-list" id="cList"></ul></div></div>
        ${chk.skipped.length ? `<div class="side-group"><div class="group-head">${icon("alert", 16)} Can't be written to <span class="pts">${chk.skipped.length}</span></div>
          <div class="group-body"><ul class="plain-list skip-list">${chk.skipped.map((s) => `<li><strong>${esc(s.company || "A lead")}</strong>: ${esc(s.reason)}</li>`).join("")}</ul></div></div>` : ""}
      </div>
    </div>
    <div class="modal-foot"><span class="left" id="cNote"></span>
      <button class="btn subtle" data-close>Cancel</button>
      <button class="btn primary" id="cGo" disabled>${icon("send", 16)} <span id="cGoText">${sendWindow() ? "Approve" : "Approve and send"}</span></button></div>`,
    { label: "New email", sheet: true });

  const root = $("#modalRoot");
  const subj = $("#cSubject", root), body = $("#cBody", root);
  const paint = () => {
    const n = c.ready.length;
    if (c.at >= n) c.at = Math.max(0, n - 1);
    const r = c.ready[c.at];
    $("#cTo", root).innerHTML = !n ? `<span class="warn-text">Nobody left to write to.</span>`
      : n === 1 ? `${esc(r.contact_name || r.first_name)} <span class="muted">&lt;${esc(r.email)}&gt;</span>`
      : `${n} people at ${n} companies <span class="muted">(listed under Goes to)</span>`;
    $("#cCount", root).textContent = n;
    $("#cList", root).innerHTML = c.ready.map((x, i) => `<li class="${i === c.at ? "on" : ""}" data-at="${i}">
        <span class="rc-main"><span class="rc-name">${esc(x.first_name)}${x.named ? "" : ` <span class="warn-text small">(no first name known)</span>`}</span>
          <span class="small muted truncate">${esc(x.contact_name || "")}${x.contact_name ? " · " : ""}${esc(x.email)}</span>
          <span class="small muted truncate">${esc(x.company_as_written || x.company)}</span>
          ${x.window && x.window.enabled && x.window.window_label ? `<span class="small muted truncate" title="${esc(x.window.send_tz_reason || "")}">${icon("clock", 12)} ${esc(x.window.window_label)}</span>` : ""}</span>
        ${n > 1 ? `<button type="button" class="btn icon" data-drop="${esc(x.id)}" aria-label="Leave ${esc(x.company)} out">${icon("x", 14)}</button>` : ""}</li>`).join("");
    const bad = composeUnknown(subj.value + " " + body.value);
    const err = $("#cErr", root);
    err.hidden = !bad.length;
    err.textContent = bad.length ? bad.map((b) => "{{" + b + "}}").join(", ") + " is not a field an email can use: it can use {{first_name}} and {{company}}." : "";
    $("#cPreviewBox", root).hidden = !r;
    if (r) {
      $("#cWho", root).textContent = (r.contact_name || r.first_name) + " at " + (r.company_as_written || r.company);
      $("#cPos", root).textContent = n > 1 ? `${c.at + 1} of ${n}` : "";
      $("#cPrev", root).hidden = $("#cNext", root).hidden = n < 2;
      $("#cPrev", root).disabled = c.at === 0; $("#cNext", root).disabled = c.at >= n - 1;
      $("#cPrevSubject", root).textContent = composeFill(subj.value.trim(), r) || "(no subject yet)";
      $("#cPreview", root).textContent = composeFill(body.value.trim(), r) + "\n\n" + chk.footer;
    }
    const ok = n > 0 && subj.value.trim() && body.value.trim() && body.value.trim() !== GREETING.trim() && !bad.length;
    $("#cGo", root).disabled = !ok;
    // with a sending window approving is not sending now: each goes at its own minute in its window
    const verb = sendWindow() ? "Approve" : "Approve and send";
    $("#cGoText", root).textContent = n > 1 ? `${verb} ${n} emails` : verb;
    const later = chk.paused || !boxes.length ? 0 : Math.max(0, n - room);
    $("#cNote", root).textContent = !boxes.length || chk.paused ? "They wait in Approved until they can go."
      : sendWindow() ? `Each goes out between ${windowSpan()} in ${itsZone()}, from your address, signed by you.`
      : later ? `${n - later} go today; the other ${later} from tomorrow, within each day's limit.`
      : "Each goes on its own, from your address, signed by you.";
  };
  const dirty = () => subj.value.trim() !== startSubject.trim() || body.value !== start;
  modal.guard = () => !dirty() || confirm("Discard this email?");
  bindRewrite(root, subj, body, "/api/outreach/rewrite", paint);
  subj.addEventListener("input", paint);
  body.addEventListener("input", paint);
  $$("[data-insert]", root).forEach((b) => b.addEventListener("click", () => {
    const s = body.selectionStart ?? body.value.length, e = body.selectionEnd ?? s;
    body.setRangeText("{{" + b.dataset.insert + "}}", s, e, "end");
    body.focus(); paint();
  }));
  $("#cPrev", root).addEventListener("click", () => { c.at = Math.max(0, c.at - 1); paint(); });
  $("#cNext", root).addEventListener("click", () => { c.at = Math.min(c.ready.length - 1, c.at + 1); paint(); });
  $("#cList", root).addEventListener("click", (e) => {
    const drop = e.target.closest("[data-drop]");
    if (drop) { c.ready = c.ready.filter((x) => x.id !== drop.dataset.drop); paint(); return; }
    const li = e.target.closest("[data-at]");
    if (li) { c.at = +li.dataset.at; paint(); }
  });
  $("#cGo", root).addEventListener("click", async (e) => {
    const b = e.currentTarget;
    b.classList.add("loading"); b.disabled = true;
    try {
      const r = await post("/api/outreach/compose", { ids: c.ready.map((x) => x.id), subject: subj.value, body: body.value });
      modal.guard = null; modal.close(true);
      state.leads.selected.clear();
      const n = r.approved, skipped = r.skipped || [];
      // with a sending window, each one's own moment was drawn on approval: say the first, by its words
      const first = (r.ready || []).map((x) => x.schedule).filter((s) => s && !s.held && s.send_after)
        .sort((a, b) => String(a.send_after).localeCompare(String(b.send_after)))[0];
      const fromAddr = (r.sends_from || [])[0] || "your address";
      flag(n ? `Approved ${n} email${n === 1 ? "" : "s"}` : "Nothing was approved", {
        kind: n ? (skipped.length ? "info" : "") : "err", ms: 8000,
        desc: (n ? (r.paused ? "They wait in Approved: sending is paused for this project."
                  : first && !r.can_send ? `${n === 1 ? "It is set for" : "The first is set for"} ${whenText(first)}, but waits in Approved until you connect your Gmail (account menu, Your Gmail).`
                  : first ? (n === 1 ? `It goes out ${whenText(first)}, from ${fromAddr}.`
                                     : `The first goes out ${whenText(first)}, from ${fromAddr}; each of the others at its own minute in ${itsWindow()}.`)
                  : r.can_send ? `They go out from ${fromAddr} within minutes, inside its daily limit.`
                  : "They wait in Approved until you connect your Gmail (account menu, Your Gmail).") : "")
          + (skipped.length ? ` ${skipped.length} skipped: ${[...new Set(skipped.map((s) => s.reason))].join("; ")}.` : "") });
      refreshCurrentView(); refreshOutreachCount(true);
    } catch (err) { toast(err.message, true); b.classList.remove("loading"); paint(); }
  });
  paint();
}

/* ---------------------------------------------------------------- footer
   The sign-off is shared by the project. The postal address is optional and
   omitted by default (owner, 2026-10-09); the opt-out line is gone from every
   footer (owner, 2026-10-13). */
function footerPreview(text, sender) {
  // sender_company (2026-10-13): the project's own company on the title line ("Business Development, LCX")
  const vals = { sender_name: sender.name, sender_title: sender.title, postal_address: sender.postal_address,
                 sender_company: sender.company };
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
      <p class="sub" style="margin-bottom:20px">Your sign-off and the line that lets someone out. It goes on the opener and on every follow-up, so it is set once here rather than inside each template.</p>
      <div class="footer-grid">
        <div class="field"><label for="fName">Your name</label><input id="fName" type="text" value="${esc(d.sender.name)}" autofocus></div>
        <div class="field"><label for="fTitle">Your title</label><input id="fTitle" type="text" value="${esc(d.sender.title)}"></div>
      </div>
      <div class="field" style="margin-top:12px"><label for="fPostal">Postal address (optional)</label>
        <input id="fPostal" type="text" value="${esc(d.sender.postal_address)}" placeholder="Street, city, postcode, country">
        <div class="help">Included only when {{postal_address}} is used in the footer below.</div></div>
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
    </div>`, { label: "Email footer", medium: true });

  const root = $("#modalRoot");
  // the project's company is not edited here (it is the project's, outreach.sender.company): it is only shown
  const sender = () => ({ name: $("#fName", root).value.trim(), title: $("#fTitle", root).value.trim(),
                          postal_address: $("#fPostal", root).value.trim(), company: d.sender.company || "" });
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

/* The files an email carries (outreach.attachments, sql/32; LCX Services: the services deck). Each opens
   from the app, so whoever approves it can read exactly the file that goes with it. */
const files = (r) => (Array.isArray(r && r.attachments) ? r.attachments : []);
function attachList(r) {
  const fs = files(r);
  if (!fs.length) return "";
  return `<div class="attach-list">${fs.map((f) => `<a class="attach" href="/api/outreach/attachment?path=${encodeURIComponent(f.path)}"
      target="_blank" rel="noopener">${icon("paperclip", 16)}<span class="attach-name truncate">${esc(f.name)}</span>
      <span class="small muted num">${f.bytes ? Math.max(1, Math.round(f.bytes / 1024)) + " KB" : ""}</span></a>`).join("")}</div>`;
}

function expectedRecipients(rows, ids) {
  const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
  if (!ids.every((id) => byId[id] && "recipient_contact_id" in byId[id])) return null;
  return Object.fromEntries(ids.map((id) => [id, {
    contact_id: byId[id].recipient_contact_id, email: byId[id].contact_email || null,
  }]));
}

function openMessage(id, message) {
  const o = state.outreach, r = message || o.rows.find((x) => x.id === id);
  if (!r) return;
  const recipientGuard = "recipient_contact_id" in r
    ? { expected_contact_id: r.recipient_contact_id, expected_contact_email: r.contact_email || null } : {};
  const isDraft = r.status === "drafted", isReply = r.direction === "inbound";
  const step = +r.sequence_step || 0;
  // ending a live thread by hand, or dismissing a follow-up draft; an unsent opener has no thread yet
  const canStop = followUpsOn() && !isReply && !r.stopped_reason && (r.status === "sent" || (step > 0 && r.status === "drafted"));
  modal.open(`
    ${modalHead(`${typeIcon("mail")}${stepLozenge(r)}${mailLozenge(r)}`,
      `<button class="btn compact" id="msgOpenLead" title="Open lead">${icon("building", 14)}<span class="btn-text">Open lead</span></button>` + navButtons("mail", id))}
    <div class="modal-body">
      <div class="modal-main">
        ${isDraft
          ? `<div class="field" style="margin-bottom:14px"><label for="draftSubject">Subject</label><input id="draftSubject" type="text" value="${esc(r.subject || "")}"></div>
             ${rewritePanel()}
             <div class="field" style="margin-top:16px"><label for="draftBody">Body</label><textarea id="draftBody" class="draft-body">${esc(r.body || "")}</textarea>
             <div class="help">Save your edits as a draft, or approve when it is ready to send.</div></div>`
          : `<h2 class="modal-title" style="font-size:20px;line-height:24px">${esc(r.subject || "(no subject)")}</h2>
             <div class="mail-body">${esc(r.body || "")}</div>
             ${r.triage_reason ? `<div class="section" style="margin-top:20px"><h3>${icon("sparkle", 16)} Triage note</h3><div class="body">${esc(r.triage_reason)}</div></div>` : ""}`}
      </div>
      <div class="modal-side">
        <div class="side-group"><div class="group-head">Details</div><div class="group-body">
          <dl class="details">
            <dt>Company</dt><dd>${esc(r.company)}${r.domain ? `<div class="small muted">${esc(r.domain)}</div>` : ""}</dd>
            ${r.service ? `<dt>${r.sent_at ? "Pitched" : "Pitches"}</dt><dd>${esc(r.service)}</dd>` : ""}
            ${files(r).length ? `<dt>Attached</dt><dd>${attachList(r)}</dd>` : ""}
            <dt>${isReply ? "From" : "To"}</dt><dd>${r.contact_email ? `<div class="person">${avatar(r.contact_name, r.contact_email)}<div><div class="who">${esc(r.contact_name || "Unnamed")}</div><div class="mail"><a href="mailto:${esc(r.contact_email)}">${esc(r.contact_email)}</a></div></div></div>` : '<span class="muted">No address</span>'}</dd>
            ${!isReply && (r.sender_address || r.sender_mailbox) ? `<dt>Sent from</dt><dd>${esc(r.sender_address || "")}<div class="small muted mono">${esc(r.sender_mailbox || "")}</div></dd>` : ""}
            ${r.approved_by ? `<dt>Approved by</dt><dd>${esc(r.approved_by_name || r.approved_by)}${r.approved_by_name ? `<div class="small muted">${esc(r.approved_by)}</div>` : ""}<div class="small muted">${esc(r.approval_mode === "batch" ? (r.spot_checked ? "in a batch, spot-checked" : "in a batch") : r.approval_mode === "compose" ? "written and approved here" : "individually")} · ${esc(fmtDate(r.approved_at))}</div></dd>` : ""}
            ${r.schedule && r.schedule.held && !r.sent_at && r.status === "approved" ? `<dt>Goes out</dt><dd>Held back, not sent${r.send_error ? "" : `<div class="small muted">${esc(r.schedule.held_why || "")}</div>`}</dd>` : ""}
            ${r.schedule && !r.schedule.held && !r.sent_at && ["approved", "sending"].includes(r.status) ? `<dt>Goes out</dt><dd>${esc(whenText(r.schedule))}${r.schedule.send_tz_reason ? `<div class="small muted">${esc(r.schedule.send_tz_reason)}</div>` : ""}${r.schedule.reschedules && r.schedule.wait_why ? `<div class="small muted">Moved ${r.schedule.reschedules === 1 ? "once" : r.schedule.reschedules + " times"}: ${esc(r.schedule.wait_why)}</div>` : ""}</dd>` : ""}
            ${isDraft && sendWindow() && !r.approval_blocked ? `<dt>Next window</dt><dd id="msgWindow"><span class="skel" style="width:70%;height:12px"></span></dd>` : ""}
            ${r.stopped_reason ? `<dt>Stopped</dt><dd>${esc(r.stopped_reason)}</dd>` : ""}
            ${r.send_error ? `<dt>Send error</dt><dd style="color:var(--text-danger)">${esc(r.send_error)}</dd>` : ""}
            ${r.generated_hook ? `<dt>Written by a model</dt><dd class="small muted">This draft includes text written or rewritten by AI. Review its facts and wording before approving.</dd>` : ""}
          </dl></div></div>
        <div class="timestamps">${r.sent_at ? "Sent " + fmtDate(r.sent_at) + "<br>" : ""}Created ${fmtDate(r.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      <span class="left" id="msgFootNote">${esc(footNote(r, isDraft))}</span>
      ${canStop ? `<button class="btn subtle danger-text" data-act="stop_sequence" title="No further follow-ups for this company">Stop follow-ups</button>` : ""}
      ${isDraft ? `<button class="btn" id="draftSave">Save draft</button>${r.approval_blocked && r.can_link_contact ? '<button class="btn" data-act="link_contact">Use verified contact</button>' : ""}<button class="btn primary" data-act="approve" ${r.approval_blocked ? `disabled title="${esc(r.approval_blocked)}"` : ""}>${icon("send", 16)} ${sendWindow() ? "Approve" : "Approve and send"}</button>` : ""}
      ${r.status === "approved" ? `<button class="btn" data-act="cancel">Withdraw approval</button>` : ""}
      ${isReply && r.status !== "cancelled" ? `<button class="btn" data-act="mark_negative">Mark negative</button><button class="btn primary" data-act="mark_positive">${icon("check", 16)} Mark positive</button>` : ""}
    </div>`, { label: r.subject || "Message", sheet: true });

  const root = $("#modalRoot");
  modal.current = { kind: "mail", id };
  bindNav(root);
  // a draft names the window approving it now aims at, never a minute: the minute is drawn on approval
  if (isDraft && sendWindow() && !r.approval_blocked) {
    api("/api/outreach/" + encodeURIComponent(id) + "/window").then((w) => {
      if (!modal.isOpen() || !modal.current || modal.current.id !== id) return;
      const cell = $("#msgWindow", root), foot = $("#msgFootNote", root);
      if (cell) cell.innerHTML = w && w.enabled && w.window_label
        ? `${esc(w.window_label)}${w.send_tz_reason ? `<div class="small muted">${esc(w.send_tz_reason)}</div>` : ""}`
        : '<span class="muted">—</span>';
      if (foot) foot.textContent = footNote(r, true, w);
    }).catch(() => { const cell = $("#msgWindow", root); if (cell) cell.textContent = "—"; });
  }
  // the list stays in view beside the sheet, so a stray click could close it: an edited draft asks first
  if (isDraft) {
    const was = { s: r.subject || "", b: r.body || "" };
    bindRewrite(root, $("#draftSubject", root), $("#draftBody", root), "/api/outreach/" + id + "/rewrite");
    $("#draftSave", root).addEventListener("click", async (event) => {
      if (o.busy) return;
      o.busy = true;
      const btn = event.currentTarget, subj = $("#draftSubject", root), body = $("#draftBody", root);
      const controls = $$("button, input, textarea", root).map((el) => [el, el.disabled]);
      controls.forEach(([el]) => { el.disabled = true; }); btn.classList.add("loading");
      try {
        await api("/api/outreach/" + id, { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: subj.value, body: body.value, ai_rewritten: body.dataset.aiRewritten === "true", ...recipientGuard }) });
        was.s = r.subject = subj.value; was.b = r.body = body.value;
        flag("Draft saved", { desc: r.approval_blocked || "Ready to review and approve." });
      } catch (e) { toast(e.message, true); }
      finally { o.busy = false; btn.classList.remove("loading"); controls.forEach(([el, disabled]) => { if (el.isConnected) el.disabled = disabled; }); }
    });
    modal.guard = () => {
      const s = $("#draftSubject", root), bd = $("#draftBody", root);
      return !s || !bd || (s.value === was.s && bd.value === was.b) || confirm("Discard your changes to this draft?");
    };
  }
  $("#msgOpenLead", root).addEventListener("click", () => {
    if (modal.guard && !modal.guard()) return;
    modal.guard = null;
    go("lead/" + r.entity_id);
  });
  $$("[data-act]", root).forEach((b) => b.addEventListener("click", async () => {
    if (o.busy) return;                       // double-click guard (review finding)
    o.busy = true;
    const controls = $$("#modalRoot .btn").map((x) => [x, x.disabled]);
    controls.forEach(([x]) => x.disabled = true);
    b.classList.add("loading");
    try {
      if (["approve", "link_contact"].includes(b.dataset.act)) {
        await api("/api/outreach/" + id, { method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: $("#draftSubject", root).value, body: $("#draftBody", root).value, ai_rewritten: $("#draftBody", root).dataset.aiRewritten === "true", ...recipientGuard }) });
      }
      const res = await post("/api/outreach/" + id + "/decision", { action: b.dataset.act, ...(b.dataset.act === "approve" ? recipientGuard : {}) });
      // held back (an old send error on it): no time to promise, and it does not go "within minutes" either
      const heldNow = res.schedule && res.schedule.held ? res.schedule : null;
      if (heldNow) res.schedule = null;
      const msg = { approve: heldNow ? "Approved, held back" : res.can_send && !res.schedule ? "Approved: sending" : "Approved", cancel: "Approval withdrawn", mark_positive: "Marked positive",
        mark_negative: "Marked negative", stop_sequence: "Follow-ups stopped", link_contact: "Verified contact linked" }[b.dataset.act];
      const perPerson = o.mbx && o.mbx.mode === "approver";
      const from = res.sends_from && res.sends_from.length ? res.sends_from[0] : "";
      // with a sending window it goes at the second just drawn for it, on its recipient's clock
      const desc = b.dataset.act === "approve"
        ? r.company + (heldNow ? ": it is not sent while it is held back: " + heldNow.held_why + "."
                       : res.paused ? ": it waits in Approved, because sending is paused for this project."
                       : res.schedule && res.can_send ? ": goes out " + whenText(res.schedule) + (from ? ", from " + from : "") + "."
                       : res.schedule ? ": set for " + whenText(res.schedule) + (perPerson
                           ? ", but it waits in Approved until you connect your Gmail (account menu, Your Gmail)."
                           : ", once a mailbox is connected.")
                       : res.can_send ? (from ? ": it goes out from " + from + " within minutes." : ": it goes out within minutes.")
                       : perPerson ? ": it waits in Approved until you connect your Gmail (account menu, Your Gmail)."
                       : ": it goes out as soon as a mailbox is connected.")
        : b.dataset.act === "stop_sequence"
        ? (res.cancelled ? res.cancelled + " pending follow-up" + (res.cancelled === 1 ? "" : "s") + " cancelled." : "No further follow-ups will be drafted.")
        : res.entity_promoted === false ? "Reply recorded; the company was not in a state that could be promoted." : r.company;
      flag(msg, { desc, ms: res.schedule ? 7000 : undefined });
      modal.close(true);
      if (currentView() === "outreach") await loadOutreach();
      else { refreshCurrentView(); refreshOutreachCount(true); }
    } catch (e) { toast(e.message, true); controls.forEach(([x, disabled]) => { if (x.isConnected) x.disabled = disabled; }); b.classList.remove("loading"); }
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
  ].filter(Boolean).map(([kk, n, d, hi]) => `<div class="tile ${hi ? "hi" : ""}"><div class="n">${esc(n)}</div><div class="k">${esc(kk)}</div>${d ? `<div class="d">${esc(d)}</div>` : ""}</div>`).join("")
    : `<div class="empty-state" style="padding:24px 8px">${icon("send", 22)}<p style="margin:8px auto 0">Nothing sent yet.</p></div>`;

  // by person: who reached out, from their own Gmail, and which companies wrote back (owner, 2026-09-26)
  const byPerson = k.by_account || [];
  $("#accountPanel").hidden = !byPerson.length;
  $("#accountTable").innerHTML = `<thead><tr><th>Person</th><th class="r">Approved</th><th class="r">Sent today</th><th class="r">Sent, 7 days</th><th class="r">Sent, all</th><th class="r">Replied</th><th class="r">Positive</th></tr></thead><tbody>` +
    byPerson.map((x) => `<tr><td><span class="cell-person">${avatar(x.name, x.account)}<span><div>${esc(x.name || x.account)}</div><div class="secondary">${esc(x.account)}</div></span></span></td>
      <td class="r num">${x.approved}</td><td class="r num">${x.sent_today}</td><td class="r num">${x.sent_last_7d}</td>
      <td class="r num">${x.sent}</td><td class="r num">${x.replied}</td><td class="r num">${x.positive}</td></tr>`).join("") + "</tbody>";

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
  rows.push({ name: "drafting and sending", run: last.outreach, when: sendWindow()
    ? "Drafting every 15 minutes; each approved email at its own time, " + windowSpan().replace(" and ", "-")
      + (onSenderClock() ? " on " + senderPlace() + "'s clock" : " in its recipient's zone")
    : "Every 15 minutes, when there is work" });
  // whether the timed sender runs on this server (review, 2026-10-12): off, the windows are kept only at the
  // fifteen-minute ticks and most emails move to the next weekday -- said here, not found out from a missed day.
  // Its runs are their own pipeline, "send" (second review, 2026-10-12): its Last run is theirs, and the tick's
  // row above is the tick's alone, so a timed run a minute later can no longer hide a tick that failed
  const loop = d.send_loop;
  if (sendWindow() && loop) rows.push({ name: "timed sending", run: last.send, loop, when: "Every few seconds, each email at its own moment" });
  // the latest Gmail refusal a send handled, in the last day (second review, 2026-10-12). That run ends OK -- it
  // moved the address's emails and the others carried on -- so without this row a lasting refusal showed green
  if (d.refused) rows.push({ name: "Gmail refused an address", run: { started_at: d.refused.at }, refusal: d.refused.detail,
    when: d.refused.detail });
  const result = (r) => !r ? '<span class="muted">Not run yet</span>'
    : r.status === "running" ? '<span class="lozenge inprogress">Running</span>'
    : r.status === "failed" ? `<span class="lozenge removed" title="${esc(r.failed_detail || r.detail || "")}">Failed${r.failed_step ? " at " + esc(r.failed_step) : ""}</span>`
    : r.status === "skipped" ? '<span class="lozenge moved">Skipped</span>' : '<span class="lozenge success">OK</span>';
  $("#runsTable").innerHTML = `<thead><tr><th>What</th><th>When</th><th>Last run</th><th>Result</th></tr></thead><tbody>` +
    rows.map((x) => `<tr><td class="primary-cell">${esc(x.name.charAt(0).toUpperCase() + x.name.slice(1))}</td><td>${esc(x.when)}</td>
      <td class="secondary nowrap" title="${esc(x.run ? fmtDate(x.run.started_at) : "")}">${x.run ? rel(x.run.started_at) + (x.run.trigger === "manual" ? " (by hand)" : "") : "—"}</td>
      <td class="nowrap">${x.refusal ? `<span class="lozenge moved" title="${esc(x.refusal)}">Emails moved</span>`
        : x.loop ? `<span class="lozenge ${x.loop.on ? "success" : "removed"}" title="${esc(x.loop.why || "")}">${x.loop.on ? "On" : "Off"}</span>`
          + (x.loop.on && x.run ? " " + result(x.run) : "")
        : result(x.run)}</td></tr>`).join("") + "</tbody>";
  $("#runsSub").textContent = "What runs by itself, and how its last run went. Times are UTC." + (d.webhook_configured ? ""
    : " Failures show only here: set ALERT_WEBHOOK_URL on the server to get a Slack or Discord ping.")
    + (sendWindow() && loop && !loop.on ? " Timed sending is off on this server: " + (loop.why || "") + "." : "");
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
  // held: nothing goes out today whatever the count says -- paused, or no mailbox on the server (2026-09-21: an
  // approval sat in Approved and the page gave no visible reason; the tooltip was the only place that said it)
  const held = !!m.paused || !m.can_send;
  if (m.paused) {
    text = "Sending paused"; tone = "paused";
    title = "Approved emails wait in Approved: " + m.paused;
  } else if (!m.can_send) {
    text = "Not sending: no mailbox connected on the server"; tone = "idle";
    title = "Approved emails wait in Approved until the Gmail values are added in Render's Environment settings "
      + "(GMAIL_SENDER_ADDRESS, GMAIL_TOKEN_JSON, GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET).";
  } else if (sent >= limit) {
    text = `${sent} of ${limit} sent today`; tone = "full";
    title = "Today's limit is reached. Approved emails go out after " + resets + ".";
  } else {
    text = `${sent} of ${limit} sent today`;
  }
  // the queue: approved emails past today's room go out from tomorrow on, oldest first, a day's limit at a time
  const waiting = m.approved_waiting || 0, room = Math.max(0, limit - sent);
  const later = held ? waiting : Math.max(0, waiting - room);
  let queue = "";
  if ((m.scheduled || []).length && !held) {
    // with a sending window each approved email already holds its day: say those, not a guess from today's room
    queue = " · approved: " + scheduledText(m.scheduled);
    title += ` Each approved email goes out at its own minute between ${windowSpan()} on ${itsClock()}: `
      + scheduledText(m.scheduled) + " (days on India's clock).";
  } else if (later && limit) {
    const days = held ? 0 : Math.ceil(later / limit);
    queue = held ? ` · ${later} approved waiting` : ` · ${later} more from tomorrow`;
    title += held ? "" : ` ${waiting} approved: ${Math.min(waiting, room)} go out today, the other ${later} ` +
      (days > 1 ? `over the next ${days} days` : "tomorrow") + `, ${limit} a day, oldest first.`;
  }
  el.className = "send-counter" + (tone ? " " + tone : "");
  el.innerHTML = `<b>${esc(text)}</b>${esc(queue)}${held ? "" : `<span class="muted"> · resets ${esc(resets)}</span>`}`;
  el.title = title;
  el.hidden = false;
}

/* Where each person sends from their own Gmail (owner, 2026-09-26): everyone, each of their addresses
 * with today's count against its own limit, yours first; and a button to connect yours if you have none. */
function renderMailboxStrip(m) {
  const el = $("#mailboxStrip");
  const resets = m.resets_at ? new Date(m.resets_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
  const people = (m.accounts || []).map((a) => {
    const boxes = a.mailboxes.length ? a.mailboxes.map((b) => {
      const tone = !b.usable ? "warn" : b.remaining <= 0 ? "full" : "";
      // this project writes as another brand (sql/36): the account's alias on its domain is the From
      const via = b.sends_as && b.sends_as !== b.address ? ` (through ${b.address}, sharing its daily limit)` : "";
      const tip = b.no_alias ? `${b.address} has no address on ${b.no_alias} to send as: add it in that Gmail (Settings, Accounts, Send mail as).`
        : !b.usable ? "Its sign-in stopped working: " + (a.me ? "connect it again (account menu, Your Gmail). " : a.name + " connects it again from Your Gmail. ") + (b.last_error || "")
        : `${b.out_today} of ${b.daily_cap} sent today, ${b.remaining} left${via}. The count starts again at ${resets}.`;
      const used = b.daily_cap ? Math.min(100, Math.round(100 * b.out_today / b.daily_cap)) : 0;
      return `<span class="mbx ${tone}" title="${esc(tip)}"><span class="addr">${esc(b.sends_as || b.address)}</span><span class="meter ${tone || "hi"}" aria-hidden="true"><i style="width:${used}%"></i></span><span class="cnt"><b>${b.out_today}</b><span class="of">/${b.daily_cap}</span></span>${b.usable ? "" : `<span class="warn-text">${b.no_alias ? "no " + esc(b.no_alias) + " address" : "reconnect"}</span>`}</span>`;
    }).join("") : `<span class="mbx none">${a.me ? "your Gmail is not connected (account menu, Your Gmail)" : "no Gmail connected yet"}</span>`;
    // with a sending window: their approvals by the day each goes (India's clock); otherwise how many wait
    const days = (a.scheduled || []).length && !m.paused ? scheduledText(a.scheduled) : "";
    const waiting = days ? `<span class="muted small" title="${esc(`Approved, each going out at its own minute in ${itsWindow()} (days on India's clock)`)}">approved: ${esc(days)}</span>`
      : a.approved_waiting ? `<span class="muted small">${a.approved_waiting} approved waiting</span>` : "";
    return `<div class="mbx-person ${a.me ? "me" : ""}"><span class="who">${avatar(a.name, a.email, "xs")}${esc(a.name)}${a.me ? " (you)" : ""}</span>${boxes}${waiting}</div>`;
  }).join("");
  el.innerHTML = `<div class="mbx-head"><strong>Sending today</strong>
      <span class="muted small">${m.paused ? "Sending is paused for this project."
        : sendWindow() ? `Each person's approvals go out from their own sending address, each at its own minute between ${esc(windowSpan())} on ${esc(itsClock())}, up to the address's daily limit. Counts start again at ${esc(resets)}.`
        : `Each person's approvals go out from their own sending address, up to its daily limit. Counts start again at ${esc(resets)}.`}</span></div>
    <div class="mbx-people">${people}</div>`;
  el.hidden = false;
}

/* What approving (or an approval) does where each person sends from their own Gmail; null elsewhere.
   win: the draft's window (GET /api/outreach/{id}/window), once it has been asked for. */
function approverNote(r, isDraft, win) {
  const m = state.outreach.mbx;
  if (!m || m.mode !== "approver" || m.paused) return null;
  if (isDraft) {
    const me = (m.accounts || []).find((a) => a.me) || { mailboxes: [] };
    const ok = me.mailboxes.filter((b) => b.usable).sort((a, b) => b.remaining - a.remaining);
    const noAlias = me.mailboxes.find((b) => b.no_alias);
    if (!ok.length && noAlias) return `Your Gmail has no address on ${noAlias.no_alias} to send as: approving keeps it in Approved until you add one in Gmail (Settings, Accounts, Send mail as).`;
    if (!ok.length) return "You have no Gmail connected yet: approving keeps it in Approved until you connect one (account menu, Your Gmail).";
    const from = ok[0].alias_unread ? `your ${ok[0].alias_unread} address (looked up in your Gmail at the first send)`
      : ok[0].sends_as || ok[0].address;
    if (win && win.enabled && win.window_label)
      return `Approving sends it from ${from} in ${nextWindow()}, ${win.window_label}, at a random minute, signed by you.`;
    return `Approving sends it from ${from} (${ok[0].remaining} of ${ok[0].daily_cap} left today), signed by you.`;
  }
  if (r.status === "approved") {
    const who = (m.accounts || []).find((a) => a.email.toLowerCase() === String(r.approved_by || "").toLowerCase());
    const name = who ? who.name : (r.approved_by_name || r.approved_by || "its approver");
    if (who && who.mailboxes.some((b) => b.no_alias) && !who.mailboxes.some((b) => b.usable))
      return `Approved by ${name}. It waits here until ${name}'s Gmail can send as an address on ${who.mailboxes.find((b) => b.no_alias).no_alias}.`;
    if (!(who && who.mailboxes.some((b) => b.usable))) return `Approved by ${name}. It waits here until ${name} connects a Gmail.`;
    return goesOutNote(r, name) || `Approved by ${name}. It goes out from their address within minutes, inside its daily limit.`;
  }
  return null;
}

/* The sheet foot's one sentence: what approving this draft does, or what this approval will do. */
function footNote(r, isDraft, win) {
  if (isDraft && r.approval_blocked) return r.approval_blocked;
  const o = state.outreach;
  const per = approverNote(r, isDraft, win);
  if (per != null) return per;
  if (o.paused) return !isDraft && r.status === "approved" ? "Approved. It waits here: sending is paused for this project." : "";
  if (isDraft) return win && win.enabled && win.window_label
    ? `Approving sends it in ${nextWindow()}, ${win.window_label}, at a random minute.` : "";
  if (r.status !== "approved") return "";
  if (r.schedule) return goesOutNote(r) + (o.canSend === false && !r.schedule.held ? " It goes once a mailbox is connected." : "");
  return o.canSend === false ? "Approved. It goes out as soon as a mailbox is connected." : "Approved. It goes out within minutes, inside today's sending limit.";
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
    o.selected = new Set(e.target.checked ? o.rows.filter((r) => !r.approval_blocked).slice(0, max).map((r) => r.id) : []);
    $$("#outreachBody [data-sel]").forEach((c) => { c.checked = o.selected.has(c.dataset.sel); });
    renderBatchBar();
  });
}

/* ========================================================== universal */
/* The Apollo search page (ui.search_page "apollo": Universal since 2026-09-19, LCX Services since
 * 2026-10-06): Apollo's people and company search.
 * The filters are drawn from the server's list (tools/apollo.py FILTERS), so the
 * page offers exactly what Apollo's API accepts, under the names Apollo's own app
 * gives them. Searching people costs nothing; saving a person reveals them and
 * costs a credit, so a save that costs credits is always confirmed first.
 * Every call names the project this page shows, and the server saves only there (app/universal.py). */
const UNI_STORE = "tvf_uni_v1";
const uniSlug = () => (state.segment && state.segment.slug) || "";
const uniStore = () => (!uniSlug() || uniSlug() === "universal" ? UNI_STORE : UNI_STORE + ":" + uniSlug());
const uniPath = (p) => p + "?project=" + encodeURIComponent(uniSlug());
state.uni = {
  kind: "people", q: { people: "", companies: "" }, filters: { people: {}, companies: {} },
  page: 1, perPage: 25, perCompany: "", rows: [], total: 0, totalPages: 0, searched: false, resultKind: null,
  lastFilters: {}, selected: new Map(), picked: {}, open: {}, schema: [], status: null,
  maxReveal: 100, token: 0, bound: false,
};
function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : ""; }
function uniPersist() {
  const u = state.uni;
  try { localStorage.setItem(uniStore(), JSON.stringify({ kind: u.kind, q: u.q, filters: u.filters, picked: u.picked })); } catch (e) {}
}
function uniRestore() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(uniStore()) || "null"); } catch (e) {}
  if (!s || typeof s !== "object") return;
  const u = state.uni;
  if (s.kind === "people" || s.kind === "companies") u.kind = s.kind;
  if (s.q && typeof s.q === "object") u.q = { people: s.q.people || "", companies: s.q.companies || "" };
  if (s.filters && typeof s.filters === "object") u.filters = { people: s.filters.people || {}, companies: s.filters.companies || {} };
  if (s.picked && typeof s.picked === "object") u.picked = s.picked;
}
function uniConnected() { const s = state.uni.status; return !!(s && s.key_set && s.connected); }
/* Can a search be tried? Yes while the status is still loading, and yes when Apollo could not be asked
   (connected: null -- busy, timed out); no only when the key is missing or Apollo refused it. The
   Search button used to stay off until the ~3 s status check answered, and for good when Apollo was
   busy: typing and pressing Search did nothing (owner, 2026-09-21: "universal section is not working"). */
function uniUsable() { const s = state.uni.status; return !s || (!!s.key_set && s.connected !== false); }

async function loadUniversal() {
  const u = state.uni;
  if (!u.bound) { uniRestore(); bindUniversal(); u.bound = true; }
  await uniLoadStatus();
  renderUniTabs(); renderUniFilters(); renderUniResults();
}
async function uniLoadStatus() {
  const u = state.uni;
  try {
    const d = await api(uniPath("/api/universal/status"));
    u.status = d.apollo; u.schema = d.filters || []; u.projectConstraints = !!d.project_constraints;
    u.maxReveal = d.max_reveal_per_save || 100; u.endpoints = d.endpoints || [];
    const target = u.schema.find((f) => f.key === "_project_search");
    if (target) ["people", "companies"].forEach((kind) => {
      if (!u.filters[kind]._project_search) u.filters[kind]._project_search = target.options[0][0];
    });
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
  $("#uniGo").disabled = !uniUsable();
  if (s.key_set && s.connected == null) {
    // Apollo could not be asked just now (busy, slow): not a refused key, so searching stays on
    setup.innerHTML = `<div class="section-msg">${icon("info", 24)}<div><div class="title">Apollo did not answer the check just now</div>
      <div class="text">Searching still works; the credits show once Apollo answers.${probs ? `<ul class="uni-problems">${probs}</ul>` : ""}</div></div></div>`;
  } else if (!s.key_set || !s.connected) {
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
  $("#uniGo").disabled = !uniUsable();
}
function renderUniTabs() {
  const u = state.uni;
  $$("#uniTabs [data-kind]").forEach((b) => { const on = b.dataset.kind === u.kind; b.classList.toggle("active", on); b.setAttribute("aria-selected", String(on)); });
  $("#uniQuery").value = u.q[u.kind] || "";
  // the bar reads what they do and where (owner, 2026-09-21: "US Arcades", a segment, not a company name)
  $("#uniQuery").placeholder = u.kind === "people" ? "Job, company type and place: owners of restaurants in Dubai"
                                                   : "What they do and where: US arcades, animation studios in California";
  $("#uniCost").innerHTML = icon("info", 14) + (u.kind === "people"
    ? `<span>Searching people is free. Saving reveals their full name, work email and LinkedIn: <strong>1 Apollo credit each</strong>.${u.projectConstraints ? " Only Apollo-verified work emails are saved; project qualification and contact rules apply." : ""}</span>`
    : `<span>Each page of company results costs <strong>1 Apollo credit</strong>. Saving companies is free. To find one company by name, use Company name under Filters.</span>`)
    + (u.readAs && u.readAsKind === u.kind ? `<span class="uni-readas">Searched ${esc(u.readAs)}.${
      u.kind === "people" && u.decisionMakers && !u.projectConstraints ? ` <a href="#" data-everyone>Search everyone instead</a>` : ""}</span>` : "");
  $("#uniGo").textContent = u.kind === "people" ? "Search" : "Search · 1 credit";
}

/* ---- the filter panel ---- */
function uniDefs() {
  // "include similar titles" only means something once there is a title to widen
  const u = state.uni, v = u.filters[u.kind] || {};
  return (u.schema || []).filter((f) => f.for.includes(u.kind) && f.group !== "Search"
    && (!u.projectConstraints || f.key !== "contact_email_status")
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
  if (f.type === "window") return `<div class="field"><label for="${id}">${esc(f.label)}</label><select id="${id}" class="compact" data-f="${esc(f.key)}"><option value="">${f.key === "_project_search" ? "Choose a targeting group" : "Choose a time frame"}</option>${f.options.map(([val, label]) =>
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
  const target = defs.find((f) => f.key === "_project_search");
  if (target && !vals._project_search) vals._project_search = target.options[0][0];
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
  if (q) out.q_text = q;                  // read on the server as what they do and where (tools/apollo.py)
  return out;
}
async function uniSearch(page, asTyped) {
  const u = state.uni;
  if (!uniUsable()) return toast("Connect Apollo first: the steps are at the top of this page.", true);
  u.q[u.kind] = $("#uniQuery").value.trim();
  const filters = uniCurrentFilters();
  if (!Object.keys(filters).length) return toast("Add a filter, or type something to search for.", true);
  const token = ++u.token, btn = $("#uniGo");
  btn.classList.add("loading");
  try {
    const d = await post(uniPath("/api/universal/search"), { kind: u.kind, filters, page: page || 1, as_typed: !!asTyped });
    if (token !== u.token) return;
    // a likely typo: a company search is held unsearched (no credit), a people search says so when empty
    u.suggest = d.did_you_mean || null; u.held = !!d.held; u.typed = u.q[u.kind];
    u.decisionMakers = !!d.decision_makers;                  // no job typed: owners, founders, C-suite
    u.rows = (u.kind === "people" ? d.people : d.companies) || [];
    u.total = d.total || 0; u.page = d.page || 1; u.perPage = d.per_page || 25;
    u.totalPages = Math.min(500, d.total_pages || Math.ceil(u.total / u.perPage) || 1);
    u.searched = true; u.resultKind = u.kind; u.lastFilters = filters; u.selected.clear();
    u.readAs = d.read_as || ""; u.readAsKind = u.kind;
    uniPersist(); renderUniTabs();
    renderUniResults();
    if (u.kind === "companies" && !u.held) uniLoadStatus();  // that page cost a credit: show the new balance
  } catch (e) { toast(e.message, true); }
  finally { btn.classList.remove("loading"); }
}
/* An empty result, with a spelling suggestion when the words look mistyped. A held company search was never
   sent to Apollo (it would have cost a credit to find nothing: "UAE Restraunts", 2026-09-21). */
function uniEmptyRow(cols, nobody) {
  const u = state.uni;
  const typo = u.suggest ? `<a href="#" data-suggest>${esc(u.suggest)}</a>` : "";
  if (u.held && typo) {
    return `<tr class="empty-row"><td colspan="${cols}">Not searched yet, so no credit spent. Did you mean ${typo}?
      Or <a href="#" data-as-typed>search “${esc(u.typed || "")}” as typed</a>.</td></tr>`;
  }
  return `<tr class="empty-row"><td colspan="${cols}">${nobody}${typo ? ` Did you mean ${typo}?` : ""} Remove a filter or two.</td></tr>`;
}
function renderUniResults() {
  const u = state.uni, head = $("#uniHead"), body = $("#uniBody");
  if (!u.searched || u.resultKind !== u.kind) {
    head.innerHTML = "";
    body.innerHTML = uniUsable() ? `<tr class="empty-row"><td>Choose filters on the left or type in the search bar, then Search.</td></tr>` : "";
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
      : uniEmptyRow(6, "Nobody matches.");
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
    }).join("") : uniEmptyRow(7, "No company matches.");
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
      const r = await post(uniPath("/api/universal/save"), { kind: "people", ids: keep.map((x) => x.id), receipts: keep.map((x) => x._receipt).filter(Boolean), filters: u.lastFilters || {} });
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
    const r = await post(uniPath("/api/universal/save"), { kind: "companies", companies: rows, receipts: rows.map((x) => x._receipt).filter(Boolean), filters: u.lastFilters || {} });
    uniAfterSave(r, "companies");
    if (u.projectConstraints && u.schema.some((f) => f.key === "_project_search") && r.saved) {
      flag("Companies saved for qualification", { desc: "Project scoring, website checks and contact rules apply before outreach.", kind: "info" });
    }
  } catch (err) { toast(err.message, true); if (b) b.classList.remove("loading"); }
}
function uniAfterSave(r, kind) {
  const u = state.uni, ids = new Set((r.saved_ids || []).map(String));
  u.rows.forEach((row) => { if (ids.has(String(row.id))) row.saved = kind === "people" ? true : (r.saved_status || "ready_for_review"); });
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
  if (u.filters.companies._project_search) u.filters.people._project_search = u.filters.companies._project_search;
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
  try { d = await api(uniPath("/api/universal/searches")); }
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
    try { await api(uniPath("/api/universal/searches/" + encodeURIComponent(b.dataset.del)), { method: "DELETE" }); flag("Saved search deleted"); renderUniSavedMenu(menu); }
    catch (err) { toast(err.message, true); }
  }));
}
function uniApplySaved(s) {
  if (!s) return;
  const u = state.uni, f = Object.assign({}, s.filters || {});
  u.kind = s.kind;
  // the bar's words (q_text since 2026-09-21; q_keywords before). A company search saved with the old
  // name search keeps q_organization_name, which is now the Company name filter, so it means the same
  u.q[s.kind] = f.q_text || f.q_keywords || "";
  delete f.q_text; delete f.q_keywords;
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
    try { await post(uniPath("/api/universal/searches"), { name, kind: u.kind, filters }); modal.close(true); flag("Search saved", { desc: name }); }
    catch (e) { toast(e.message, true); $("#ssGo").classList.remove("loading"); }
  };
  $("#ssGo").addEventListener("click", go);
  $("#ssName").addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
}

function bindUniversal() {
  const u = state.uni, fl = $("#uniFilters");
  $("#uniForm").addEventListener("submit", (e) => { e.preventDefault(); uniSearch(1); });
  // the decision-maker default, widened in one click: "UAE restaurants" -> "everyone at UAE restaurants"
  $("#uniCost").addEventListener("click", (e) => {
    if (!e.target.closest("[data-everyone]")) return;
    e.preventDefault();
    $("#uniQuery").value = "everyone at " + (state.uni.typed || $("#uniQuery").value).trim();
    uniSearch(1);
  });
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
    const sg = e.target.closest("[data-suggest]");
    if (sg) { e.preventDefault(); $("#uniQuery").value = u.suggest || ""; return uniSearch(1); }
    const typed = e.target.closest("[data-as-typed]");
    if (typed) { e.preventDefault(); return uniSearch(1, true); }
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
    `<button class="menu-item ${s.current ? "selected" : ""}" data-seg="${esc(s.slug)}">${icon("folder", 18)}
       <span style="flex:1">${esc(s.project_name)}</span>
       ${s.current ? icon("check", 16) : ""}</button>`).join("");
  $$("[data-seg]", menu).forEach((b) => b.addEventListener("click", async () => {
    closeMenus();
    if (state.segment && b.dataset.seg === state.segment.slug) return;
    try { await post("/api/segment/select", { slug: b.dataset.seg }); history.replaceState(null, "", location.pathname); location.reload(); }
    catch (e) { toast(e.message, true); }
  }));
}
/* The account menu opens up from the sidebar's foot, where the name and address already show;
   it carries the title (what signs each email) and the account's four actions. */
function renderUserMenu(menu) {
  const email = state.user || "", me = state.me || {};
  menu.innerHTML = `${me.title ? `<div class="menu-note">Signs emails as <strong>${esc(me.name || email)}</strong>, ${esc(me.title)}</div><div class="menu-sep"></div>` : ""}
    <button class="menu-item" id="myGmailBtn">${icon("mail", 18)}<span>Your Gmail</span></button>
    <button class="menu-item" id="myProfileBtn">${icon("user", 18)}<span>Your name and title</span></button>
    <button class="menu-item" id="myPasswordBtn">${icon("shield", 18)}<span>Change password</span></button>
    <div class="menu-sep"></div>
    <button class="menu-item" id="logoutBtn">${icon("logout", 18)}<span>Log out</span></button>`;
  $("#myGmailBtn", menu).addEventListener("click", () => { closeMenus(); openSendingAddress(); });
  $("#myProfileBtn", menu).addEventListener("click", () => { closeMenus(); openProfile(); });
  $("#myPasswordBtn", menu).addEventListener("click", () => { closeMenus(); openPassword(); });
  $("#logoutBtn", menu).addEventListener("click", async () => {
    try { await post("/api/auth/logout"); } catch (e) {}
    location.href = "/login";
  });
}

/* ========================================================= your account */
/* One login per person (owner, 2026-09-26). Each person's emails go out from their own Gmail, signed
   with their own name and title; a starting password the owner handed out opens nothing but the screen
   that replaces it (the server refuses everything else until then). */
function syncMe() {
  const me = state.me || {}, email = state.user || "?";
  $("#userAvatar").textContent = initials(me.name || null, email);
  $("#userAvatar").className = "avatar av-" + (hashCode(email) % 8 + 1);
  $("#userBtn").title = (me.name ? me.name + " · " : "") + email;
  $("#userName").textContent = me.name || email.split("@")[0];
  $("#userMail").textContent = email;
}
function fieldErr(root, id, msg) {
  const el = $("#" + id, root);
  el.textContent = msg || ""; el.hidden = !msg;
}
async function savePassword(current, next, again) {
  if (next !== again) throw new Error("The two new passwords are not the same.");
  await post("/api/auth/password", { current, new: next });
  state.me = Object.assign({}, state.me, { must_change: false });
}
async function saveProfile(name, title) {
  const r = await post("/api/auth/profile", { name, title });
  state.me = Object.assign({}, state.me, { name: r.name, title: r.title });
  syncMe();
}
function passwordFields(given) {
  return `<div class="field"><label for="pwCurrent">${given ? "The password you were given" : "Current password"}</label>
      <input id="pwCurrent" type="password" autocomplete="current-password" ${given ? "autofocus" : ""}></div>
    <div class="field" style="margin-top:12px"><label for="pwNew">${given ? "Your own password" : "New password"}</label>
      <input id="pwNew" type="password" autocomplete="new-password" minlength="10"><div class="help">At least 10 characters.</div></div>
    <div class="field" style="margin-top:12px"><label for="pwAgain">Again</label>
      <input id="pwAgain" type="password" autocomplete="new-password"></div>`;
}
function profileFields(me) {
  return `<div class="footer-grid">
      <div class="field"><label for="meName">Your name</label><input id="meName" type="text" maxlength="80" value="${esc(me.name || "")}" placeholder="e.g. Suhas C"></div>
      <div class="field"><label for="meTitle">Your title</label><input id="meTitle" type="text" maxlength="80" value="${esc(me.title || "")}" placeholder="e.g. Business Development"></div>
    </div>
    <div class="help">They sign every email you approve: it goes out from your own Gmail, with your name and title under it.</div>`;
}

/* The first sign-in (a starting password, or no name yet): set a password of your own, then your name
   and title. Resolves once the account is ready to use. */
function openWelcome() {
  return new Promise((resolve) => {
    const me = state.me || {};
    const pw = !!me.must_change;
    modal.open(`
      ${modalHead(`${typeIcon("user")}<span class="key">Welcome</span>`)}
      <div class="modal-body single"><div class="modal-main">
        <h2 class="modal-title" style="margin-bottom:6px">Set up your account</h2>
        <p class="sub" style="margin-bottom:22px">${pw ? "The password you were given works once. Choose your own, and tell us how to sign your emails." : "Tell us how to sign your emails."}</p>
        ${pw ? passwordFields(true) + '<div class="form-sep"></div>' : ""}
        ${profileFields(me)}
        <div class="footer-problems" id="welcomeErr" hidden></div>
      </div></div>
      <div class="modal-foot"><span class="left">Signed in as ${esc(state.user || "")}</span>
        <button class="btn subtle" id="welcomeOut">Log out</button>
        <button class="btn primary" id="welcomeGo">${icon("check", 16)} Save</button></div>`, { label: "Set up your account", locked: true, narrow: true });
    const root = $("#modalRoot");
    if (!pw) setTimeout(() => $("#meName", root).focus(), 40);
    $("#welcomeOut", root).addEventListener("click", async () => { try { await post("/api/auth/logout"); } catch (e) {} location.href = "/login"; });
    $("#welcomeGo", root).addEventListener("click", async (e) => {
      const b = e.currentTarget;
      fieldErr(root, "welcomeErr", "");
      b.classList.add("loading"); b.disabled = true;
      try {
        if (pw) await savePassword($("#pwCurrent", root).value, $("#pwNew", root).value, $("#pwAgain", root).value);
        await saveProfile($("#meName", root).value, $("#meTitle", root).value);
        modal.locked = false; modal.close(true);
        resolve();
        openSendingAddress({ welcome: true });   // then their Gmail, when it can be connected from here
      } catch (err) {
        fieldErr(root, "welcomeErr", err.message);
        b.classList.remove("loading"); b.disabled = false;
      }
    });
  });
}

function openProfile() {
  modal.open(`
    ${modalHead(`${typeIcon("user")}<span class="key">Your name and title</span>`)}
    <div class="modal-body single"><div class="modal-main">${profileFields(state.me || {})}
      <div class="footer-problems" id="profErr" hidden></div></div></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button>
      <button class="btn primary" id="profGo">${icon("check", 16)} Save</button></div>`, { label: "Your name and title", narrow: true });
  const root = $("#modalRoot");
  $("#profGo", root).addEventListener("click", async () => {
    fieldErr(root, "profErr", "");
    try { await saveProfile($("#meName", root).value, $("#meTitle", root).value); modal.close(true); flag("Saved", { desc: "Emails you approve are signed with it." }); }
    catch (err) { fieldErr(root, "profErr", err.message); }
  });
}

function openPassword() {
  modal.open(`
    ${modalHead(`${typeIcon("user")}<span class="key">Change password</span>`)}
    <div class="modal-body single"><div class="modal-main">${passwordFields(false)}
      <div class="footer-problems" id="pwErr" hidden></div></div></div>
    <div class="modal-foot"><span class="left">You stay signed in here; other devices sign in again.</span><button class="btn" data-close>Cancel</button>
      <button class="btn primary" id="pwGo">${icon("check", 16)} Change</button></div>`, { label: "Change password", narrow: true });
  const root = $("#modalRoot");
  $("#pwGo", root).addEventListener("click", async () => {
    fieldErr(root, "pwErr", "");
    try { await savePassword($("#pwCurrent", root).value, $("#pwNew", root).value, $("#pwAgain", root).value); modal.close(true); flag("Password changed"); }
    catch (err) { fieldErr(root, "pwErr", err.message); }
  });
}

function connectGmail() { location.href = "/api/mailboxes/connect"; }

/* Your Gmail: the addresses the emails you approve go out from, today's use of each one's limit, connect one
   (Google's own sign-in, app/mailbox_connect.py) and disconnect one. The owner, 2026-10-14: "a feature which
   allows users to link a gmail account to send emails in their own without my intervention". The owner can
   still link one for you from the laptop (`users.py gmail`); it shows here the same way. */
async function openSendingAddress(opts) {
  opts = opts || {};
  let d;
  try { d = await api("/api/me/mailboxes"); } catch (e) { return toast("Could not load your Gmail: " + e.message, true); }
  const rows = d.mailboxes || [];
  if (opts.welcome && (rows.length || !d.web_connect)) {
    flag("You're all set", { desc: rows.length ? "The emails you approve are signed with your name and go out from " + rows[0].address + "."
                                               : "The emails you approve are signed with your name and title." });
    return;
  }
  const list = rows.length ? `<ul class="mbx-list">${rows.map((b) => `<li>
      <span class="cell-person">${avatar(null, b.address)}<span><div>${esc(b.address)}</div>
        <div class="secondary">${b.usable ? `${b.out_today} of ${b.daily_cap} sent today, ${b.remaining} left`
          : `<span style="color:var(--text-danger)">Its sign-in stopped working: connect it again</span>`}</div>
        ${(b.send_as || []).length ? `<div class="secondary">Also sends as ${esc(b.send_as.map((x) => x.address).join(", "))}</div>` : ""}</span></span>
      <span class="grow"></span>
      ${b.usable || !d.web_connect ? "" : `<button class="btn compact" data-reconnect>Connect again</button>`}
      <button class="btn subtle compact danger-text" data-drop="${esc(b.id)}" data-addr="${esc(b.address)}">Disconnect</button></li>`).join("")}</ul>`
    : `<p class="muted">No Gmail connected yet. Until you connect one, the emails you approve wait in Approved.</p>`;
  const cap = String((rows[0] || {}).daily_cap || 35);
  modal.open(`
    ${modalHead(`${typeIcon("mail")}<span class="key">Your Gmail</span>`)}
    <div class="modal-body single"><div class="modal-main">
      ${opts.welcome ? `<h2 class="modal-title" style="font-size:20px;line-height:24px;margin-bottom:4px">One last step: your Gmail</h2>` : ""}
      <p class="sub" style="margin-bottom:16px">The emails you approve go out from your own Gmail, signed with your name and title, up to ${esc(cap)} a day from each address${rows.length > 1 ? ", the one with the most room first" : ""}. Google shows you what is allowed (sending, and reading replies, for that address only), and you can take it back here or from your Google account at any time.</p>      ${list}
      ${d.web_connect ? "" : `<div class="footer-problems" style="margin-top:12px">${icon("info", 16)}<div>Connecting from the app is not switched on yet: the owner adds a Google "Web application" client to the server first. Until then the owner can link an address for you.</div></div>`}
    </div></div>
    <div class="modal-foot">
      <button class="btn" data-close>${opts.welcome ? "Later" : "Close"}</button>
      <button class="btn primary" id="gmailGo" ${d.web_connect ? "" : "disabled"}>${icon("mail", 16)} ${rows.length ? "Connect another address" : "Connect your Gmail"}</button>
    </div>`, { label: "Your Gmail", narrow: true });
  const root = $("#modalRoot");
  $("#gmailGo", root).addEventListener("click", connectGmail);
  $$("[data-reconnect]", root).forEach((b) => b.addEventListener("click", connectGmail));
  $$("[data-drop]", root).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Disconnect " + b.dataset.addr + "? The emails you approve stop going out from it.")) return;
    try {
      await api("/api/mailboxes/" + encodeURIComponent(b.dataset.drop), { method: "DELETE" });
      flag("Disconnected", { desc: b.dataset.addr });
      openSendingAddress();
    } catch (e) { toast(e.message, true); }
  }));
}

function bindShell() {
  const pairs = [["#userBtn", "#userMenu", renderUserMenu],
    ["#projectSwitch", "#projectSwitchMenu", renderProjectsMenu]];   // the project switcher at the top of the sidebar
  pairs.forEach(([b, m, r]) => $(b).addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($(b), $(m), r); }));
  $$("[data-route]").forEach((b) => b.addEventListener("click", () => go(b.dataset.route)));

  // sidebar: collapse on desktop, drawer on small screens
  const frame = $("#frame");
  const labelCollapse = () => {
    const c = frame.classList.contains("collapsed");
    $("#collapseBtn").setAttribute("aria-label", c ? "Expand sidebar" : "Collapse sidebar");
    $("#collapseBtn").title = c ? "Expand sidebar" : "Collapse sidebar";
  };
  try { if (localStorage.getItem("tvf_sidebar") === "collapsed") frame.classList.add("collapsed"); } catch (e) {}
  labelCollapse();
  $("#collapseBtn").addEventListener("click", () => {
    frame.classList.toggle("collapsed");
    closeMenus();
    labelCollapse();
    try { localStorage.setItem("tvf_sidebar", frame.classList.contains("collapsed") ? "collapsed" : "open"); } catch (e) {}
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
  // the lead-service tabs (LCX Services): one selection, so a tab picked on one page is on for the other
  bindServiceTabs($("#boardServices"), () => loadBoard());
  bindServiceTabs($("#leadsServices"), () => { state.leads.page = 0; loadLeads(); });
}

/* ================================================================ init */
(async function init() {
  bindShell(); bindFilters(); bindOps(); bindLeadsCompose();
  try {
    const a = await api("/api/auth/state");
    state.user = a.user || null;
    state.me = { name: a.name || "", title: a.title || "", must_change: !!a.must_change_password };
    syncMe();
    // a starting password, or no name to sign emails with yet: that first, before anything loads
    if (state.user && (state.me.must_change || !state.me.name || !state.me.title)) await openWelcome();
  } catch (e) {}
  // back from Google's sign-in (app/mailbox_connect.py): say how it went, then drop it from the address bar
  const back = new URLSearchParams(location.search);
  if (back.get("gmail")) {
    const ok = back.get("gmail") === "connected";
    flag(ok ? "Gmail connected" : "Gmail not connected", ok
      ? { desc: (back.get("msg") || "") + " now sends the emails you approve.", ms: 6000 }
      : { desc: back.get("msg") || "", kind: "err", ms: 10000 });
    history.replaceState(null, "", location.pathname + location.hash);
  }
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
