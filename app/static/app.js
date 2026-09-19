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
let REVIEW_THRESHOLD = 25, PRIORITY_THRESHOLD = 45, KEY_PREFIX = "TVF";

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
function leadKey(id) { return KEY_PREFIX + "-" + String(id || "").replace(/-/g, "").slice(0, 4).toUpperCase(); }
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
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  sparkle: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
  keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/>',
  pHighest: '<path d="m5 13 7-7 7 7M5 19l7-7 7 7"/>',
  pHigh: '<path d="m5 15 7-7 7 7"/>',
  pMedium: '<path d="M5 9h14M5 15h14"/>',
  pLow: '<path d="m5 9 7 7 7-7"/>',
  pLowest: '<path d="m5 5 7 7 7-7M5 11l7 7 7-7"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4z" fill="currentColor" stroke="none"/>',
  envelope: '<rect x="3" y="6" width="18" height="12" rx="1.5" fill="currentColor" stroke="none"/><path d="m4 8 8 5 8-5" stroke="#fff" stroke-width="2"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="currentColor" stroke="none"/>',
};
function icon(name, size, extra) {
  return `<svg width="${size || 16}" height="${size || 16}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra || ""}>${PATHS[name] || ""}</svg>`;
}
function typeIcon(kind) {
  const glyph = kind === "mail" ? "envelope" : kind === "job" ? "bolt" : "bookmark";
  return `<span class="type-icon ${kind}" title="${kind === "mail" ? "Email" : kind === "job" ? "Pipeline job" : "Lead"}">${icon(glyph, 10)}</span>`;
}
function prioFor(score) {
  score = +score || 0;
  if (score <= 0) return { cls: "low", glyph: "pLowest", label: "Unscored" };
  if (score >= 60) return { cls: "high", glyph: "pHighest", label: "Highest" };
  if (score >= PRIORITY_THRESHOLD) return { cls: "high", glyph: "pHigh", label: "High" };
  if (score >= REVIEW_THRESHOLD) return { cls: "medium", glyph: "pMedium", label: "Medium" };
  if (score > 0) return { cls: "low", glyph: "pLow", label: "Low" };
  return { cls: "low", glyph: "pLowest", label: "Unscored" };
}
function prioIcon(score, withLabel) {
  const p = prioFor(score);
  return `<span class="prio ${p.cls}" title="Priority: ${p.label} (fit score ${fmtScore(score)})">${icon(p.glyph, 16)}${withLabel ? ` <span style="color:var(--text)">${p.label}</span>` : ""}</span>`;
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
  route: null, user: null, rubric: [], sources: [], segment: null, segments: [],
  board: { filters: { q: "", min_score: REVIEW_THRESHOLD, source: "", has_contact: false },
           cols: {}, token: 0 },
  leads: { filters: { q: "", status: "open", min_score: 0, source: "", has_contact: false, sort: "score" },
           page: 0, perPage: 50, total: 0, rows: [], token: 0 },
  outreach: { folder: "drafts", rows: [], counts: {}, token: 0, busy: false, selected: new Set() },
  ops: { timer: null, watching: null, jobs: [] },
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
  if (head === "outreach" && rest) state.outreach.folder = rest;
  if (state.route === head && head !== "outreach") return;   // same view, nothing to do
  if (modal.isOpen()) modal.close(true);
  showView(head);
}
window.addEventListener("hashchange", router);

/* ============================================================ segment */
const UI_FALLBACK = { project_name: "US Production Houses", project_type: "Lead segment", key_prefix: "TVF",
  board_title: "Lead board", list_title: "Leads", entity_label: "company", entity_plural: "companies",
  lead_first: "entity", summary_label: "Summary", card_fields: [], details: [], evidence: [] };
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
    return { title: host, sub: same ? (r.domain || "") : r.name, avatarName: host, aria: same ? host : host + ", " + r.name, same };
  }
  return { title: r.name, sub: r.domain || "", avatarName: r.contact_name, aria: r.name };
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
function uiEvidence(d) {
  return (segUi().evidence || []).map((f) => {
    const v = getPath(d, f.path);
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "";
    return `<li>${icon("info", 16)}<span><strong>${esc(f.label)}:</strong> ${fmtFieldHtml(v, f.format)}</span></li>`;
  }).filter(Boolean);
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
  KEY_PREFIX = ui.key_prefix || "TVF";
  // 0 is a real threshold: a project with no rubric (Universal) scores nothing and hides nothing
  const rv = parseFloat((seg.thresholds || {}).review), pv = parseFloat((seg.thresholds || {}).priority);
  REVIEW_THRESHOLD = Number.isFinite(rv) ? rv : 25;
  PRIORITY_THRESHOLD = Number.isFinite(pv) ? pv : 45;
  $("#projectName").textContent = ui.project_name;
  $("#projectType").textContent = ui.project_type;
  $("#projectSwitch").dataset.prefix = ui.key_prefix || "TVF";          // tints the project icon per segment
  $("#projectSwitch").setAttribute("aria-label", "Project: " + ui.project_name + ". Switch project");
  $("#sidebarFoot").innerHTML = ui.sidebar_note || "";      // our own config, not user input
  $$(".crumb-project").forEach((a) => { a.textContent = ui.project_name; });
  $("#boardTitle").textContent = ui.board_title;
  $("#leadsTitle").textContent = ui.list_title;
  TITLES.board = ui.board_title; TITLES.leads = ui.list_title;
  $("#leadsLastCol").textContent = (ui.card_fields || []).length ? "Evidence" : "Location";
  $("#leadsSummaryCol").textContent = ui.summary_label || "Summary";
  const ent = ui.entity_label || "company";
  $("#outreachEntityCol").textContent = ent.charAt(0).toUpperCase() + ent.slice(1);
  $$("#boardScore, #leadsScore").forEach((sel) => {
    const opts = sel.querySelectorAll("option");
    if (opts[1]) { opts[1].value = String(REVIEW_THRESHOLD); opts[1].textContent = "Reviewable · " + REVIEW_THRESHOLD + "+"; }
    if (opts[2]) { opts[2].value = String(PRIORITY_THRESHOLD); opts[2].textContent = "Priority · " + PRIORITY_THRESHOLD + "+"; }
  });
  state.board.filters.min_score = REVIEW_THRESHOLD;
  const hidden = new Set(ui.hide_routes || []), apolloPage = ui.search_page === "apollo";
  $$(".side-item[data-route]").forEach((b) => { b.hidden = !routeAllowed(b.dataset.route); });
  // Universal generates leads on its search page, so the sidebar has no second way to the same place
  $("#createSide").hidden = apolloPage;
  $("#pipelineHeading").hidden = apolloPage && hidden.has("ops");
  const unscored = unscoredProject();
  $$("#boardScore, #leadsScore").forEach((sel) => { sel.hidden = unscored; });
  $("#leadsTable").classList.toggle("unscored", unscored);
  document.title = (TITLES[currentView()] || "") + " - " + ui.project_name;
}

/* ============================================================== board */
const COLUMNS = [
  { key: "open", title: "To review", status: "open" },
  { key: "shortlisted", title: "Shortlisted", status: "shortlisted" },
  { key: "contacted", title: "Contacted", status: "contacted" },
  { key: "in_conversation", title: "In conversation", status: "in_conversation", done: true },
  { key: "rejected", title: "Rejected", status: "rejected", muted: true },
];
const COL_LIMIT = 60;

function boardQuery(col, offset) {
  const f = state.board.filters, p = new URLSearchParams();
  p.set("status", col.status);
  if (f.q) p.set("q", f.q);
  if (f.source) p.set("source", f.source);
  if (col.key === "open") {      // score and contact filters shape the review band only
    if (f.min_score) p.set("min_score", f.min_score);
    if (f.has_contact) p.set("has_contact", "1");
  }
  p.set("limit", COL_LIMIT); p.set("offset", offset || 0);
  return p.toString();
}

function renderCard(r, col) {
  const score = +r.fit_score || 0;
  const place = r.state || r.city;
  const t = leadTitle(r);
  return `<div class="card ${col.done ? "done" : ""}" role="button" tabindex="0" data-id="${esc(r.id)}"
       aria-label="${esc(t.aria)}, score ${fmtScore(score)}">
    <div class="card-summary">${esc(t.title)}</div>
    ${t.sub ? `<div class="card-sub truncate">${esc(t.sub)}</div>` : ""}
    ${fieldSummary(r) ? `<div class="card-sub">${fieldSummary(r)}</div>` : ""}
    <div class="card-tags">${sourceLozenge(r.source)}${kindLozenge(r)}${place ? `<span class="lozenge" title="${esc((r.city || "") + (r.state ? ", " + r.state : ""))}">${esc(place)}</span>` : ""}</div>
    <div class="card-foot">
      <span class="type-key">${typeIcon("lead")}<span class="key">${leadKey(r.id)}</span></span>
      <span class="right">${unscoredProject() ? "" : prioIcon(score) + pts(score)}${avatar(t.avatarName, r.email, "")}</span>
    </div></div>`;
}

function renderColumn(col) {
  const c = state.board.cols[col.key] || { rows: [], total: 0 };
  const body = c.rows.length
    ? c.rows.map((r) => renderCard(r, col)).join("")
    : `<div class="column-empty">${col.key === "open" ? "Nothing to review with these filters." : "No leads here yet."}</div>`;
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
  const open = state.board.cols.open.total;
  $("#boardCount").textContent = open.toLocaleString() + " " + (open === 1 ? (segUi().entity_label || "company") : (segUi().entity_plural || "companies")) + " to review";
  bindBoard();
  syncExportLinks();
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
  if (f.min_score) p.set("min_score", f.min_score);
  if (f.has_contact) p.set("has_contact", "1");
  p.set("sort", f.sort);
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
      <td><span class="cell-key">${typeIcon("lead")}<span class="key">${leadKey(r.id)}</span></span></td>
      <td>${(() => { const t = leadTitle(r);
        const parts = [t.sub || (personFirst() ? (r.domain || "") : "no website yet"), r.kind ? String(r.kind).replace(/_/g, " ") : ""].filter(Boolean);
        return `<div class="primary-cell">${esc(t.title)}</div><div class="secondary">${esc(parts.join(" · "))}</div>`; })()}</td>
      <td>${statusLozenge(r.status)}</td>
      <td>${pts(r.fit_score)}</td>
      <td>${prioIcon(r.fit_score, true)}</td>
      <td>${sourceLozenge(r.source)}</td>
      <td>${r.email ? `<span class="cell-person">${avatar(r.contact_name, r.email)}<span><div>${esc(r.contact_name || "Unnamed")}</div><div class="secondary">${esc(r.email)}</div></span></span>` : '<span class="muted">Unassigned</span>'}</td>
      <td class="secondary">${fieldSummary(r) || esc([r.city, r.state].filter(Boolean).join(", ") || "")}</td>
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="8">No ${esc(segUi().entity_plural || "companies")} match these filters.</td></tr>`;
  delegateOpen("#leadsBody", (id) => go("lead/" + id));
  const from = d.total ? state.leads.page * state.leads.perPage + 1 : 0;
  const to = Math.min((state.leads.page + 1) * state.leads.perPage, d.total);
  $("#leadsInfo").textContent = `${from}–${to} of ${d.total.toLocaleString()}`;
  $("#leadsPrev").disabled = state.leads.page === 0;
  $("#leadsNext").disabled = to >= d.total;
  syncExportLinks();
}

function syncExportLinks() {
  const b = state.board.filters, p = new URLSearchParams();
  p.set("status", "open");
  if (b.min_score) p.set("min_score", b.min_score);
  if (b.source) p.set("source", b.source);
  $("#boardExport").href = "/api/export.xlsx?" + p.toString();
  const l = state.leads.filters, q = new URLSearchParams();
  q.set("status", l.status === "all" ? "open" : l.status);
  if (l.min_score) q.set("min_score", l.min_score);
  if (l.source) q.set("source", l.source);
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
  if (!c.check) return "";
  return c.check.job
    ? `<div class="crit-check">${icon("play", 12)}<span>Checked by <strong>${esc(c.check.label)}</strong> in Operations</span></div>`
    : `<div class="crit-check">${icon("user", 12)}<span>By hand: ${esc(c.check.manual)}</span></div>`;
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
      <p class="muted small" style="margin:4px 0 0">${esc(cov.formula || "")}</p>
      ${cov.stale ? `<p class="small warn-text" style="margin:4px 0 0">${esc(cov.stale)}</p>` : ""}
    </div>`;
}
function renderLegend(ex) {
  return `<details class="legend"><summary>What “found”, “checked, nothing found” and “not checked yet” mean</summary><dl>${(ex.legend || []).map((l) =>
    `<dt><span class="lozenge ${STATE_CLS[l.state] || ""}">${esc(l.label)}</span></dt><dd>${esc(l.meaning)}</dd>`).join("")}</dl></details>`;
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
  return `<div class="section-msg ${VERDICT_TONE[v.tone] || ""}" style="margin-bottom:8px">${icon(v.tone === "hold" ? "alert" : v.tone === "strong" ? "checkCircle" : "info", 20)}<div><div class="title">${esc(v.title || "")}</div><div class="text">${esc(v.detail || "")}</div></div></div>
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
function factList(obj, max) {
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return "";
  const items = Object.entries(obj).filter(([k, v]) => v != null && v !== "" &&
    (typeof v !== "object")).slice(0, max || 8);
  if (!items.length) return "";
  return `<dl class="details" style="grid-template-columns:140px 1fr;gap:4px 8px">${items.map(([k, v]) =>
    `<dt class="small">${esc(k.replace(/_/g, " "))}</dt><dd class="small">${esc(String(v)).slice(0, 240)}</dd>`).join("")}</dl>`;
}
function evidenceItems(m) {
  const out = [];
  // a field one pass writes as a list may be a single string from another:
  // site_platform_evidence is a string, and .forEach on it stopped the dialog opening
  const arr = (v) => Array.isArray(v) ? v : (v == null || v === "") ? [] : [v];
  const text = (v) => typeof v === "string" ? v : (v && (v.headline || v.title || v.phrase || v.text || v.snippet || v.summary)) || JSON.stringify(v);
  const link = (v) => v && typeof v === "object" && (v.url || v.link || v.page) ? (v.url || v.link || v.page) : null;
  const push = (glyph, label, v) => {
    const u = link(v), t = text(v);
    out.push(`<li>${icon(glyph, 16)}<span><strong>${esc(label)}</strong> ${esc(t)}${u ? ` <a href="${esc(u)}" target="_blank" rel="noopener">${icon("external", 12)}</a>` : ""}</span></li>`);
  };
  arr(m.news_evidence).forEach((v) => push("news", "News:", v));
  arr(m.site_genre_evidence).forEach((v) => push("film", "Genre signal:", v));
  arr(m.site_platform_evidence).forEach((v) => push("globe", "Platform credit:", v));
  arr(m.format_deals).forEach((v) => push("bookmark", "Format deal:", v));
  arr(m.notable_credits).forEach((v) => push("film", "Credit:", v));
  // evidence withdrawn on review stays visible, so a score that dropped is never a mystery
  arr(m.retracted_evidence).forEach((v) => out.push(`<li class="withdrawn">${icon("x", 16)}<span><strong>Withdrawn:</strong> <s>${esc(v.headline || v.site_platform_evidence || "")}</s> <span class="small">(${esc(v.reason || "withdrawn on review")})</span></span></li>`));
  if (m.web_verification) {
    const w = m.web_verification;
    push("shield", "Web verification:", typeof w === "string" ? w : (w.summary || w.verdict || w.result || "checked" + (w.checked_at ? " " + fmtDate(w.checked_at) : "")));
  }
  if (m.verified_country) push("pin", "Verified country:", m.verified_country);
  if (m.team_size_evidence) {
    const s = m.team_size_evidence;
    push("users", "Team size:", `${s.people_named} people named on ${s.page || "the site"}${s.scored ? "" : " (recorded, not scored: outside the confident 2–20 band)"}`);
  }
  if (m.team_size_estimate) push("users", "Team estimate:", m.team_size_estimate);
  return out;
}

async function openLead(id, opts) {
  // The dialog opens on the click, not when the server answers: on a cold
  // cloud instance the fetch can take seconds, and a click that shows nothing
  // reads as a click that did nothing.
  const quiet = !!(opts && opts.quiet);
  if (!quiet) {
    modal.open(`${modalHead(`${typeIcon("lead")}<span class="key">${leadKey(id)}</span>`)}
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
  const st = leadStatus(d.status), score = +d.fit_score || 0, prio = prioFor(score);
  const decided = d.status === "shortlisted" || d.status === "rejected";
  const contacts = renderContacts(d);
  const evidence = evidenceItems(m).concat(uiEvidence(d));
  const pills = [sourceLozenge(d.source)];
  if (m.subtype) pills.push(`<span class="lozenge new">${esc(String(m.subtype).replace(/_/g, " "))}</span>`);
  if (m.web_verification) pills.push(`<span class="lozenge success">Web-verified</span>`);
  (m.genres || []).slice(0, 4).forEach((g) => pills.push(`<span class="lozenge">${esc(g)}</span>`));
  (m.platform_relationships || []).slice(0, 4).forEach((g) => pills.push(`<span class="lozenge inprogress">${esc(g)}</span>`));

  modal.open(`
    ${modalHead(`${typeIcon("lead")}<span class="key">${leadKey(d.id)}</span><span style="margin:0 4px">·</span>${statusLozenge(d.status)}`,
      d.domain ? `<a class="btn subtle" href="https://${esc(d.domain)}" target="_blank" rel="noopener">${icon("external", 16)} Website</a>` : "")}
    <div class="modal-body">
      <div class="modal-main">
        ${(() => { const t = leadTitle(d); return personFirst() && hostOf(d) && !t.same
          ? `<h2 class="modal-title" style="margin-bottom:4px">${esc(t.title)}</h2><p class="subtle" style="margin:0 0 16px">Host of <strong>${esc(d.name)}</strong></p>`
          : `<h2 class="modal-title">${esc(d.name)}</h2>`; })()}
        <div class="pill-list" style="margin:-8px 0 20px">${pills.join("")}</div>

        ${d.explain ? `<div class="section"><h3>${icon("sparkle", 16)} Analysis</h3><div class="body">${renderAnalysis(d.explain)}</div></div>` : ""}

        ${m.why_fit ? `<div class="section"><h3>${icon("book", 16)} Why this could fit</h3><div class="body"><p>${esc(m.why_fit)}</p></div></div>` : ""}

        <div class="section"><h3>${icon("shield", 16)} Evidence</h3>
          <div class="body">${evidence.length ? `<ul class="evidence-list">${evidence.join("")}</ul>`
            : `<p class="muted">No evidence beyond the discovery record yet. Run the enrichment passes from Operations.</p>`}</div></div>

        ${d.explain && !(d.explain.criteria || []).length ? "" : `<div class="section"><h3>${icon("chart", 16)} Score breakdown <span class="pts ${ptsClass(score)}">${fmtScore(score)} / 100</span></h3>
          <div class="body">${d.explain ? renderCoverage(d.explain) + renderCriteria(d.explain) + renderLegend(d.explain) : ""}</div></div>`}

        ${research.ownership || research.caveats ? `<div class="section"><h3>${icon("book", 16)} Research notes</h3><div class="body">
          ${research.ownership ? `<p><strong>Ownership.</strong> ${esc(research.ownership)}</p>` : ""}
          ${research.caveats ? `<p><strong>Caveats.</strong> ${esc(research.caveats)}</p>` : ""}</div></div>` : ""}

        <div class="section"><h3>${icon("clock", 16)} Activity</h3><div class="body">
          ${d.status_reason ? `<p><strong>Decision note.</strong> ${esc(d.status_reason)}</p>` : ""}
          ${d.status_changed_at ? `<p class="muted small">Status changed ${fmtDate(d.status_changed_at)}</p>` : ""}
          ${m.source_history && m.source_history.length ? `<p class="muted small">Seen by ${m.source_history.length} discovery run${m.source_history.length === 1 ? "" : "s"}.</p>` : ""}
          ${!d.status_reason && !d.status_changed_at ? `<p class="muted">No decisions yet.</p>` : ""}
        </div></div>
      </div>

      <div class="modal-side">
        <div class="menu-anchor" style="margin-bottom:16px">
          <button class="status-btn ${st.cls.split(" ")[0]}" id="statusBtn" aria-haspopup="true" aria-expanded="false">${esc(st.label)} ${icon("chevDown", 14)}</button>
          <div class="menu" id="statusMenu" hidden>
            <div class="menu-heading">Transition to</div>
            ${d.status !== "shortlisted" ? `<button class="menu-item" data-decide="shortlist"><span class="lozenge success">Shortlisted</span> Its email is drafted next</button>` : ""}
            ${d.status !== "rejected" ? `<button class="menu-item" data-decide="reject"><span class="lozenge removed">Rejected</span> Keep out of the pipeline</button>` : ""}
            ${decided ? `<button class="menu-item" data-decide="reset"><span class="lozenge">To review</span> Undo the decision</button>` : ""}
          </div>
        </div>
        <div class="reason-box" id="reasonBox" hidden>
          <label for="rejectReason">Reason for rejecting (kept with the decision)</label>
          <textarea id="rejectReason" rows="3" placeholder="e.g. service vendor, not an IP owner"></textarea>
          <div class="actions"><button class="btn subtle" id="reasonCancel">Cancel</button><button class="btn danger" id="reasonGo">Reject</button></div>
        </div>

        <div class="side-group"><div class="group-head">${icon("users", 16)} Contacts</div><div class="group-body">${contacts}</div></div>
        <div class="side-group"><div class="group-head">Details</div><div class="group-body">
          <dl class="details">
            ${unscoredProject() ? "" : `<dt>Priority</dt><dd>${prioIcon(score, true)}</dd>
            <dt>Fit score</dt><dd>${pts(score)} <span class="muted small">of 100</span></dd>`}
            <dt>Source</dt><dd>${sourceLozenge(d.source)}</dd>
            <dt>Website</dt><dd>${d.domain ? `<a href="https://${esc(d.domain)}" target="_blank" rel="noopener">${esc(d.domain)}</a>` : '<span class="muted">None yet</span>'}</dd>
            ${(m.hq_city || m.hq_state) ? `<dt>Location</dt><dd>${esc([m.hq_city, m.hq_state].filter(Boolean).join(", "))}</dd>` : ""}
            ${uiDetails(d)}
            ${m.aicp_detail ? `<dt>Directory</dt><dd>Listed in AICP${m.aicp_detail.chapter ? ", " + esc(m.aicp_detail.chapter) : ""}</dd>` : ""}
            ${m.domain_resolution ? `<dt>Website via</dt><dd class="small">${esc(m.domain_resolution.method || m.domain_resolution.source || "resolver")}</dd>` : ""}
          </dl>
        </div></div>
        ${m.web_verification && typeof m.web_verification === "object" ? `<div class="side-group"><div class="group-head">${icon("shield", 16)} Verification</div><div class="group-body">${factList(m.web_verification, 8) || '<span class="muted small">verified</span>'}</div></div>` : ""}
        <div class="timestamps">Created ${fmtDate(d.created_at)}<br>Updated ${fmtDate(d.updated_at || d.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      <span class="left">${leadKey(d.id)} · ${esc(d.name)}</span>
      ${decided ? `<button class="btn subtle" data-decide="reset">Undo decision</button>` : ""}
      ${d.status !== "rejected" ? `<button class="btn subtle danger-text" data-decide="reject">Reject</button>` : ""}
      ${d.status !== "shortlisted" ? `<button class="btn primary" data-decide="shortlist">${icon("check", 16)} Shortlist</button>` : ""}
    </div>`, { label: d.name, onClose: () => { if (location.hash.startsWith("#lead/")) history.replaceState(null, "", "#" + currentView()); } });

  const root = $("#modalRoot");
  const sb = $("#statusBtn", root), sm = $("#statusMenu", root);
  sb.addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(sb, sm); });
  const showReason = () => { $("#reasonBox", root).hidden = false; $("#rejectReason", root).focus(); closeMenus(); };
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
      + (r.drafting ? ". Its email is being drafted: it appears in Outreach within minutes, for you to approve." : "") });
    await openLead(id, { quiet: true }); // re-render with the new status; Undo stays reachable
    refreshCurrentView();
    refreshNotifications(true);
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
const FOLDERS = [
  ["drafts", "Drafts"], ["outbox", "Approved"], ["sent", "Sent"], ["inbox", "Replies"],
  ["positive", "Positive"], ["negative", "Negative"], ["attention", "Attention"], ["cancelled", "Cancelled"],
];
function outreachPolicy() { return (state.segment && state.segment.outreach_policy) || {}; }
function batchOn() { return !!outreachPolicy().batch_approval; }
function followUpsOn() { return !!(outreachPolicy().follow_ups || {}).enabled; }
/* A draft whose opening line a model wrote is marked wherever it appears.
   It is approved one at a time unless the segment allows it into a batch, so
   the mark is not decoration: it is the reason the checkbox may be refused. */
function writtenLozenge(r) {
  return r.generated ? `<span class="lozenge moved" title="A model wrote the opening line from this lead's own evidence">Written</span> ` : "";
}
function stepLozenge(r) {
  const n = +r.sequence_step || 0;
  return n > 0 ? `<span class="lozenge new" title="Follow-up in the same thread">Follow-up ${n}</span> ` : "";
}
function threadNote() {
  const f = outreachPolicy().follow_ups;
  if (f && f.enabled) {
    const n = (f.steps || []).length;
    return `One thread per company: an opener and up to ${n} follow-up${n === 1 ? "" : "s"}, stopped by any reply.`;
  }
  return "One touch per company, enforced by the database.";
}

async function loadOutreach() {
  const o = state.outreach, token = ++o.token;
  let d;
  try { d = await api("/api/outreach?folder=" + encodeURIComponent(o.folder)); }
  catch (e) { return toast("Could not load outreach: " + e.message, true); }
  // can an approval go out from here? (a connected mailbox) -- it words what "approve" does
  api("/api/mailboxes").then((m) => { o.canSend = !!m.can_send; }).catch(() => {});
  if (token !== o.token) return;
  o.rows = d.rows; o.counts = d.counts || {};
  const present = new Set(d.rows.map((r) => r.id));
  o.selected = new Set([...(o.selected || [])].filter((id) => present.has(id)));
  const batch = batchOn() && o.folder === "drafts" && d.rows.length > 0;
  $("#outreachTable").classList.toggle("batch", batch);
  $("#folderTabs").innerHTML = FOLDERS.map(([key, label]) =>
    `<button class="tab ${key === o.folder ? "active" : ""}" role="tab" aria-selected="${key === o.folder}" data-f="${key}">${label}<span class="pts">${o.counts[key] || 0}</span></button>`).join("");
  $$("#folderTabs .tab").forEach((b) => b.addEventListener("click", () => {
    o.folder = b.dataset.f; o.selected.clear(); history.replaceState(null, "", "#outreach/" + o.folder); loadOutreach();
  }));
  $("#outreachBody").innerHTML = d.rows.length ? d.rows.map((r) => `
    <tr class="row-link" data-id="${esc(r.id)}" tabindex="0">
      <td class="sel-col"><input type="checkbox" data-sel="${esc(r.id)}" ${o.selected.has(r.id) ? "checked" : ""} aria-label="Select this draft"></td>
      <td><span class="cell-key">${typeIcon("mail")}<span class="key">${leadKey(r.entity_id)}</span></span></td>
      <td><div class="primary-cell">${esc(r.company)}</div><div class="secondary">${esc(r.domain || "")}</div></td>
      <td>${r.contact_email ? `<span class="cell-person">${avatar(r.contact_name, r.contact_email)}<span><div>${esc(r.contact_name || "Unnamed")}</div><div class="secondary">${esc(r.contact_email)}</div></span></span>` : '<span class="muted">No address</span>'}</td>
      <td><div class="truncate" style="max-width:360px">${stepLozenge(r)}${writtenLozenge(r)}${esc(r.subject || "(no subject)")}</div>${r.send_error ? `<div class="secondary" style="color:var(--text-danger)">${esc(r.send_error)}</div>` : ""}${r.stopped_reason && r.status === "cancelled" ? `<div class="secondary">${esc(r.stopped_reason)}</div>` : ""}</td>
      <td>${mailLozenge(r)}</td>
      <td class="secondary nowrap" title="${esc(fmtDate(r.sent_at || r.created_at))}">${rel(r.sent_at || r.created_at)}</td>
    </tr>`).join("")
    : `<tr class="empty-row"><td colspan="7">${o.folder === "drafts"
        ? "No drafts waiting. Shortlist a company on the board and its email is drafted here within minutes."
        : "Nothing in this folder yet."}</td></tr>`;
  delegateOpen("#outreachBody", openMessage, ".sel-col");
  $$("#outreachBody [data-sel]").forEach((c) => c.addEventListener("change", () => {
    if (c.checked) o.selected.add(c.dataset.sel); else o.selected.delete(c.dataset.sel);
    renderBatchBar();
  }));
  renderBatchBar();
  updateNotifBadge(o.counts);
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
    <button class="btn subtle" id="batchClear" ${n ? "" : "disabled"}>Clear</button>
    <button class="btn primary" id="batchGo" ${n ? "" : "disabled"}>${icon("check", 16)} Approve ${n || ""} selected</button>`;
  const all = $("#outreachSelAll");
  all.checked = n > 0 && n === o.rows.length;
  all.indeterminate = n > 0 && n < o.rows.length;
  $("#batchClear").addEventListener("click", () => { o.selected.clear(); loadOutreach(); });
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
const FOOTER_SAMPLE = { company: "Example Productions", greeting_name: "there" };

function footerPreview(text, sender) {
  const vals = Object.assign({ sender_name: sender.name, sender_title: sender.title,
    sender_email: sender.email || "", postal_address: sender.postal_address }, FOOTER_SAMPLE);
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
        <div class="help">Fields: ${d.fields.map((f) => `<code>{{${esc(f)}}}</code>`).join(" ")} &nbsp;<a href="#" id="fReset">restore the standard footer</a></div></div>
      <div class="field" style="margin-top:16px"><label>How it will read</label><div class="mail-body" id="fPreview"></div></div>
      <div id="fProblems"></div>
      ${pending ? `<label class="footer-apply"><input type="checkbox" id="fApply" checked> Put this footer on the ${pending} draft${pending === 1 ? "" : "s"} waiting for approval<div class="help">Only the footer is replaced. Anything you wrote above it stays exactly as you wrote it.</div></label>` : ""}
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
  $("#fReset", root).addEventListener("click", (e) => {
    e.preventDefault(); $("#fText", root).value = d.default; paint();
  });
  $("#fSave", root).addEventListener("click", async (e) => {
    const b = e.currentTarget;
    b.classList.add("loading"); $$("#modalRoot .btn").forEach((x) => x.disabled = true);
    $("#fProblems", root).innerHTML = "";
    try {
      const apply = !!($("#fApply", root) || {}).checked;
      const res = await post("/api/outreach/footer",
        { text: $("#fText", root).value, sender: sender(), apply_to_drafts: apply });
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
  const [stLabel, stCls] = mailStatus(r);
  const step = +r.sequence_step || 0;
  const canStop = followUpsOn() && !isReply && ["drafted", "approved", "sent"].includes(r.status);
  modal.open(`
    ${modalHead(`${typeIcon("mail")}<span class="key">${leadKey(r.entity_id)}</span><span style="margin:0 4px">·</span>${stepLozenge(r)}${mailLozenge(r)}`,
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
            <dt>Company</dt><dd><a href="#lead/${esc(r.entity_id)}">${esc(r.company)}</a>${r.domain ? `<div class="small muted">${esc(r.domain)}</div>` : ""}</dd>
            <dt>${isReply ? "From" : "To"}</dt><dd>${r.contact_email ? `<div class="person">${avatar(r.contact_name, r.contact_email)}<div><div class="who">${esc(r.contact_name || "Unnamed")}</div><div class="mail"><a href="mailto:${esc(r.contact_email)}">${esc(r.contact_email)}</a></div></div></div>` : '<span class="muted">No address</span>'}</dd>
            <dt>Status</dt><dd><span class="lozenge ${stCls}">${esc(stLabel)}</span></dd>
            <dt>Direction</dt><dd>${isReply ? "Inbound reply" : step ? "Follow-up " + step + ", same thread" : "Opener"}</dd>
            ${!isReply && (r.sender_address || r.sender_mailbox) ? `<dt>Sent from</dt><dd>${esc(r.sender_address || "")}<div class="small muted mono">${esc(r.sender_mailbox || "")}</div></dd>` : ""}
            ${r.approved_by ? `<dt>Approved</dt><dd>${esc(r.approved_by)}<div class="small muted">${esc(r.approval_mode === "batch" ? (r.spot_checked ? "in a batch, spot-checked" : "in a batch") : "individually")} · ${esc(fmtDate(r.approved_at))}</div></dd>` : ""}
            ${r.stopped_reason ? `<dt>Stopped</dt><dd>${esc(r.stopped_reason)}</dd>` : ""}
            ${r.triage ? `<dt>Triage</dt><dd><span class="lozenge ${r.triage === "positive" ? "success bold" : r.triage === "negative" ? "removed" : "moved"}">${esc(r.triage.replace(/_/g, " "))}</span></dd>` : ""}
            ${r.send_error ? `<dt>Send error</dt><dd style="color:var(--text-danger)">${esc(r.send_error)}</dd>` : ""}
            ${r.template_key ? `<dt>Template</dt><dd class="mono">${esc(r.template_key)}</dd>` : ""}
            ${r.generated_hook ? `<dt>Opening line</dt><dd><span class="lozenge moved">Written by a model</span><div class="small muted" style="margin-top:6px">From this lead's own evidence. Every number in it was checked against that evidence before it was kept.</div></dd>` : ""}
            ${r.gmail_thread_id ? `<dt>Gmail thread</dt><dd class="mono">${esc(r.gmail_thread_id)}</dd>` : ""}
          </dl></div></div>
        <div class="timestamps">${r.sent_at ? "Sent " + fmtDate(r.sent_at) + "<br>" : ""}Created ${fmtDate(r.created_at)}</div>
      </div>
    </div>
    <div class="modal-foot">
      <span class="left">${r.status === "approved" ? (o.canSend === false ? "Approved. It goes out as soon as a mailbox is connected." : "Approved. It goes out within minutes, inside today's sending limit.") : esc(threadNote())}</span>
      ${canStop ? `<button class="btn subtle danger-text" data-act="stop_sequence" title="No further follow-ups for this company">Stop follow-ups</button>` : ""}
      ${isDraft ? `<button class="btn subtle danger-text" data-act="cancel">Cancel draft</button><button class="btn primary" data-act="approve">${icon("send", 16)} Approve and send</button>` : ""}
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
      const msg = { approve: res.can_send ? "Approved: sending" : "Approved", cancel: "Cancelled", mark_positive: "Marked positive",
        mark_negative: "Marked negative", stop_sequence: "Follow-ups stopped" }[b.dataset.act];
      const desc = b.dataset.act === "approve"
        ? r.company + (res.can_send ? ": it goes out within minutes." : ": it goes out as soon as a mailbox is connected.")
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
  state.rubric = s.rubric || [];
  const f = k.funnel || {}, a = k.approval || {}, en = k.enrichment || {}, o = k.outreach || {}, u = k.unattended || {};

  $("#statTiles").innerHTML = [
    ["Companies found", s.total, "all sources, all time", false],
    ["With a website", s.with_domain, "", false],
    ["Contactable", s.with_contact, "have an email", true],
    ["Named person", s.named_contact, "a real name, not info@", true],
    ["To review", s.open_pool, "open pool", false],
    ["Shortlisted", s.shortlisted, "approved for outreach", true],
  ].map(([kk, n, d, hi]) => `<div class="tile ${hi ? "hi" : ""}"><div class="n">${n}</div><div class="k">${esc(kk)}</div>${d ? `<div class="d">${esc(d)}</div>` : ""}</div>`).join("");

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
    <div class="center"><div class="n">${total}</div><div class="k">companies</div></div>`;
  $("#donutLegend").innerHTML = segs.map((x) => `<li><span class="sw" style="background:${x.color}"></span><span>${esc(x.label)}</span><span class="v">${x.value}${total ? ` · ${Math.round(x.value / total * 100)}%` : ""}</span></li>`).join("");

  const pct = (v) => v == null ? "—" : v + "%";
  $("#kpiTiles").innerHTML = [
    ["Contacted, 7d", o.sent_last_7d ?? 0, "target 15–20", true],
    ["Contacted, 28d", o.sent_last_28d ?? 0, "", false],
    ["Approval rate", pct(a.approval_rate_pct), `${a.approved ?? 0} kept / ${a.rejected ?? 0} rejected`, true],
    ["Contact-find rate", pct(en.contact_find_rate_pct), `${en.with_contact ?? 0} of ${en.sites_known ?? 0} sites`, false],
    ["Email validity", pct(en.email_validity_pct), `${en.invalid_emails ?? 0} invalid`, false],
    ["Reply rate", pct(o.reply_rate_pct), `${o.replies ?? 0} replies`, true],
    ["Positive rate", pct(o.positive_rate_pct), `${o.positive_replies ?? 0} positive`, true],
    ["Follow-ups sent", o.followups_sent ?? 0, "in the same thread", false],
    ["Pipeline runs, 28d", u.pipeline_runs_28d ?? 0, `${u.pipeline_failures_28d ?? 0} failed`, false],
  ].map(([kk, n, d, hi]) => `<div class="tile ${hi ? "hi" : ""}" style="padding:12px 16px"><div class="n" style="font-size:20px">${esc(n)}</div><div class="k">${esc(kk)}</div>${d ? `<div class="d">${esc(d)}</div>` : ""}</div>`).join("");

  const max = Math.max(1, ...s.histogram.map((h) => h.n));
  $("#histogram").innerHTML = s.histogram.map((h) => `<div class="row" title="${h.n} companies scoring ${esc(h.band)}">
      <div class="lbl">${esc(h.band)}</div>
      <div class="track"><div class="fill" style="width:${(h.n / max * 100).toFixed(1)}%"></div></div>
      <div class="val">${h.n}</div></div>`).join("");

  const pool = s.open_pool || 1, byKey = {};
  state.rubric.forEach((x) => { byKey[x.key] = x; });
  $("#coverage").innerHTML = Object.entries(s.coverage).map(([key, n]) => {
    const p = n / pool * 100, cls = p < 5 ? "starved" : p < 40 ? "thin" : "ok", rr = byKey[key] || {};
    const state_ = cls === "starved" ? ["Starved", "removed"] : cls === "thin" ? ["Thin", "moved"] : ["Covered", "success"];
    return `<div class="cov ${cls}">
      <div class="top-line"><span>${esc(rr.label || key)}</span><span class="pts-label">${rr.points != null ? rr.points + " pts" : ""}</span></div>
      <div class="track"><div class="fill" style="width:${Math.max(p, 0.6).toFixed(1)}%"></div></div>
      <div class="state"><span class="lozenge ${state_[1]}">${state_[0]}</span><span class="n">${n} · ${p.toFixed(0)}%</span></div></div>`;
  }).join("");

  const bySrc = {};
  (k.by_source || []).forEach((x) => { bySrc[x.source] = x; });
  $("#sourceTable").innerHTML = `<thead><tr><th>Source</th><th class="r">Found</th><th class="r">With site</th>
      <th class="r">Contactable</th><th class="r">Avg score</th><th class="r">Reviewable</th><th>Approval</th></tr></thead><tbody>` +
    s.by_source.map((x) => {
      const ap = bySrc[x.source] || {}, ruled = (ap.approved || 0) + (ap.rejected || 0);
      return `<tr><td>${sourceLozenge(x.source)}</td><td class="r num">${x.n}</td><td class="r num">${x.with_domain}</td>
        <td class="r num">${x.with_contact}</td><td class="r num">${x.avg_score == null ? "—" : x.avg_score}</td>
        <td class="r num"><strong>${x.reviewable}</strong></td>
        <td>${ruled ? `<div class="bar-cell"><div class="track"><div class="fill" style="width:${ap.approval_rate_pct || 0}%"></div></div><span class="num small">${ap.approval_rate_pct}% <span class="muted">(${ap.approved}/${ruled})</span></span></div>` : '<span class="muted small">no decisions yet</span>'}</td></tr>`;
    }).join("") + "</tbody>";
}

/* ================================================================ ops */
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
async function loadSchedule() {
  let d;
  try { d = await api("/api/schedule"); } catch (e) { return; }
  $("#schedTable").innerHTML = `<thead><tr><th>State</th><th>Name</th><th>When</th><th>Pipeline</th></tr></thead><tbody>` +
    ((d.schedule || []).map((s) => {
      const hm = `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`;
      const when = s.dow === "*" || s.dow == null ? `${hm} daily` : `${DOW[s.dow]} ${hm} UTC`;
      return `<tr><td><span class="lozenge ${s.enabled ? "success" : ""}">${s.enabled ? "On" : "Off"}</span></td>
        <td class="primary-cell">${esc(s.name)}</td><td>${esc(when)}</td><td class="mono">${esc(s.pipeline)}</td></tr>`;
    }).join("") || `<tr class="empty-row"><td colspan="4">No schedules configured.</td></tr>`) + "</tbody>";
  $("#webhookMsg").innerHTML = d.webhook_configured
    ? `<div class="section-msg success">${icon("checkCircle", 24)}<div><div class="title">Alerts are armed</div><div class="text">A failed pipeline step pings the alert webhook. Use Test alert to prove it.</div></div></div>`
    : `<div class="section-msg warning">${icon("warn", 24)}<div><div class="title">No alert webhook set</div><div class="text">Failures are logged only. Set ALERT_WEBHOOK_URL in the environment to get a Discord or Slack ping.</div></div></div>`;
  const dur = (r) => (r.started_at && r.finished_at) ? Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000) + "s" : "";
  $("#runsTable").innerHTML = `<thead><tr><th>Pipeline</th><th>Step</th><th>Trigger</th><th>Status</th><th>When</th><th class="r">Took</th></tr></thead><tbody>` +
    (d.runs.length ? d.runs.slice(0, 15).map((r) => `<tr>
        <td class="primary-cell">${esc(r.pipeline)}</td>
        <td>${r.step ? `<span class="mono">${esc(r.step)}</span>` : '<span class="muted">whole pipeline</span>'}</td>
        <td><span class="lozenge ${r.trigger === "manual" ? "inprogress" : ""}">${esc(r.trigger)}</span></td>
        <td><span class="lozenge ${r.status === "ok" ? "success" : r.status === "failed" ? "removed" : "inprogress"}">${esc(r.status)}</span></td>
        <td class="secondary nowrap" title="${esc(fmtDate(r.started_at))}">${rel(r.started_at)}</td>
        <td class="r num secondary">${esc(dur(r))}</td></tr>`).join("")
      : `<tr class="empty-row"><td colspan="6">No runs yet. The first scheduled refresh is Tuesday 02:00 UTC.</td></tr>`) + "</tbody>";
}

async function loadMailboxes() {
  let d;
  try { d = await api("/api/mailboxes"); } catch (e) { $("#mailboxPanel").hidden = true; return; }
  $("#mailboxPanel").hidden = false;
  const today = d.mailboxes.reduce((a, m) => a + (m.cap_today || 0), 0);
  $("#mailboxSub").textContent = d.rotation
    ? `Openers go to the mailbox with the most room left today; follow-ups always leave from the mailbox that sent the opener. New mailboxes warm up slowly. Up to ${Math.min(today, d.segment_cap)} emails today (segment ceiling ${d.segment_cap}). Bounced addresses are never written to again.`
    : `One mailbox, up to ${d.segment_cap} emails a day.`;
  $("#mailboxTable").innerHTML = `<thead><tr><th>Mailbox</th><th>Address</th><th>Warm-up</th><th class="r">Cap today</th><th class="r">Sent today</th><th>Room left</th></tr></thead><tbody>` +
    d.mailboxes.map((m) => {
      const warm = !m.enabled ? `<span class="lozenge">Disabled</span>`
        : !m.warmup ? `<span class="lozenge success">Warm</span>`
        : m.warmup_day ? (m.cap_today >= m.daily_cap ? `<span class="lozenge success">Warm</span>` : `<span class="lozenge inprogress">Day ${m.warmup_day}</span>`)
        : `<span class="lozenge moved">Not started</span>`;
      const pct = m.cap_today ? Math.round(100 * m.remaining / m.cap_today) : 0;
      return `<tr><td class="mono primary-cell">${esc(m.key)}</td>
        <td>${m.last_address ? esc(m.last_address) : `<span class="muted small">set <span class="mono">${esc(m.email_env)}</span> on the laptop</span>`}</td>
        <td>${warm}${m.warmup ? `<div class="secondary">${m.warmup.start_cap} a day, +${m.warmup.step} every ${m.warmup.every_days} days, up to ${m.daily_cap}</div>` : ""}</td>
        <td class="r num">${m.cap_today}</td><td class="r num">${m.sent_today}</td>
        <td><div class="bar-cell"><div class="track"><div class="fill" style="width:${pct}%"></div></div><span class="num small">${m.remaining}</span></div></td></tr>`;
    }).join("") + "</tbody>";
}

async function loadOps() {
  loadSchedule();
  loadMailboxes();
  let d;
  try { d = await api("/api/ops"); }
  catch (e) { return toast("Could not load operations: " + e.message, true); }
  state.ops.jobs = d.jobs;
  const groups = {};
  d.jobs.forEach((j) => (groups[j.group] = groups[j.group] || []).push(j));
  const GROUP_DESC = { Discover: "Find new companies. Runs in the office n8n on schedule.",
    Process: "Staging into the pool: promote, merge, score, apply gates.",
    Enrich: "Websites, contacts, qualification evidence, news.",
    Outreach: "Draft personalised emails for the shortlist." };
  $("#opsGroups").innerHTML = Object.entries(groups).map(([g, jobs]) => `
    <div class="panel"><div class="panel-head"><div><h2>${esc(g)}</h2><p class="sub">${esc(GROUP_DESC[g] || "")}</p></div></div>
      ${jobs.map((j) => `<div class="job-row ${!j.available ? "off" : ""}">
        <div class="info"><div class="name">${esc(j.label)}</div><div class="desc">${esc(j.desc)}</div>
          ${!j.available ? `<div class="why">${esc(j.unavailable_reason)}</div>` : ""}</div>
        <div class="side">
          ${j.running ? `<span class="spin" aria-hidden="true"></span><span class="lozenge inprogress bold">Running</span><button class="btn" data-stop="${j.key}">Stop</button>`
            : `<span class="lozenge ${j.status === "done" ? "success" : j.status === "failed" ? "removed" : ""}">${esc(j.status || "idle")}</span>
               <button class="btn ${j.available && !d.busy ? "primary" : ""}" data-run="${j.key}" ${(!j.available || d.busy) ? "disabled" : ""}>Run</button>`}
          <button class="btn subtle" data-log="${j.key}" ${!j.status ? "disabled" : ""}>Log</button>
        </div></div>`).join("")}
    </div>`).join("");
  $$("#opsGroups [data-run]").forEach((b) => b.addEventListener("click", () => runJob(b.dataset.run)));
  $$("#opsGroups [data-stop]").forEach((b) => b.addEventListener("click", async () => {
    try { await post("/api/ops/" + b.dataset.stop + "/stop"); flag("Stopping " + b.dataset.stop); }
    catch (e) { toast(e.message, true); }
    loadOps();
  }));
  $$("#opsGroups [data-log]").forEach((b) => b.addEventListener("click", () => watchOps(b.dataset.log)));
  if (d.busy && !state.ops.timer) watchOps(d.busy);
}

async function runJob(key, opts) {
  opts = opts || {};
  try {
    await post("/api/ops/" + key + "/run");
    const j = state.ops.jobs.find((x) => x.key === key);
    flag("Started: " + (j ? j.label : key), { desc: "One job runs at a time. The log streams in Operations." });
    if (opts.goToOps) go("ops");
    watchOps(key, opts.onDone);
  } catch (e) { toast(e.message, true); }
  if (currentView() === "ops") loadOps();
}

async function watchOps(key, onDone) {
  state.ops.watching = key;
  const panel = $("#logPanel");
  panel.hidden = false;
  const j = state.ops.jobs.find((x) => x.key === key);
  $("#logTitle").textContent = "Log: " + (j ? j.label : key);
  clearInterval(state.ops.timer);
  const tick = async () => {
    try {
      const d = await api("/api/ops/" + key + "/log?tail=150");
      const pre = $("#opsLog");
      pre.textContent = d.lines.join("\n") || "(no output yet)";
      pre.scrollTop = pre.scrollHeight;
      if (d.status !== "running") {
        clearInterval(state.ops.timer); state.ops.timer = null;
        if (currentView() === "ops") loadOps();
        if (d.status) flag((j ? j.label : key) + ": " + d.status, { kind: d.status === "failed" ? "err" : "" });
        if (onDone) onDone(d.status);
      }
    } catch (e) { clearInterval(state.ops.timer); state.ops.timer = null; }
  };
  await tick();
  state.ops.timer = setInterval(tick, 3000);
}

function bindOps() {
  const runPipe = async (name, btn) => {
    btn.classList.add("loading");
    try { await post("/api/schedule/run/" + name); flag(name + " started", { desc: "Watch it in Recent runs." }); setTimeout(loadSchedule, 1500); }
    catch (e) { toast(e.message, true); }
    btn.classList.remove("loading");
  };
  $("#runRefresh").addEventListener("click", (e) => runPipe("weekly_refresh", e.currentTarget));
  $("#runRescore").addEventListener("click", (e) => runPipe("rescore", e.currentTarget));
  $("#testAlert").addEventListener("click", async (e) => {
    const b = e.currentTarget; b.classList.add("loading");
    try {
      const r = await post("/api/schedule/test-alert");
      flag(r.webhook_configured ? "Alert sent to the webhook" : "No webhook set", { desc: r.webhook_configured ? "Check the channel." : "The alert was logged server-side instead.", kind: r.webhook_configured ? "" : "info" });
    } catch (err) { toast(err.message, true); }
    b.classList.remove("loading");
  });
  $("#logClose").addEventListener("click", () => { $("#logPanel").hidden = true; });
  $("#footerBtn").addEventListener("click", openFooter);
  $("#outreachSelAll").addEventListener("change", (e) => {
    const o = state.outreach;
    if (e.target.checked) o.rows.forEach((r) => o.selected.add(r.id)); else o.selected.clear();
    $$("#outreachBody [data-sel]").forEach((c) => { c.checked = e.target.checked; });
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
  lastFilters: {}, selected: new Map(), picked: {}, open: {}, schema: [], appOnly: [], status: null,
  saved: null, maxReveal: 100, token: 0, bound: false,
};
function safeUrl(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : ""; }
function uniPersist() {
  const u = state.uni;
  try { localStorage.setItem(UNI_STORE, JSON.stringify({ kind: u.kind, q: u.q, filters: u.filters, perPage: u.perPage, picked: u.picked })); } catch (e) {}
}
function uniRestore() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(UNI_STORE) || "null"); } catch (e) {}
  if (!s || typeof s !== "object") return;
  const u = state.uni;
  if (s.kind === "people" || s.kind === "companies") u.kind = s.kind;
  if (s.q && typeof s.q === "object") u.q = { people: s.q.people || "", companies: s.q.companies || "" };
  if (s.filters && typeof s.filters === "object") u.filters = { people: s.filters.people || {}, companies: s.filters.companies || {} };
  if ([10, 25, 50, 100].includes(+s.perPage)) u.perPage = +s.perPage;
  if (s.picked && typeof s.picked === "object") u.picked = s.picked;
}
function uniConnected() { const s = state.uni.status; return !!(s && s.key_set && s.connected); }

async function loadUniversal() {
  const u = state.uni;
  if (!u.bound) { uniRestore(); bindUniversal(); u.bound = true; }
  await uniLoadStatus(false);
  $("#uniPerPage").value = String(u.perPage);
  renderUniTabs(); renderUniFilters(); renderUniResults();
}
async function uniLoadStatus(refresh) {
  const u = state.uni;
  try {
    const d = await api("/api/universal/status" + (refresh ? "?refresh=1" : ""));
    u.status = d.apollo; u.schema = d.filters || []; u.appOnly = d.app_only || []; u.saved = d.saved;
    u.maxReveal = d.max_reveal_per_save || 100; u.endpoints = d.endpoints || [];
  } catch (e) {
    u.status = { key_set: false, connected: false, problems: [e.message] };
  }
  renderUniStatus();
}
function renderUniStatus() {
  const u = state.uni, s = u.status || {};
  const left = s.credits && s.credits.lead_credits_left != null ? (+s.credits.lead_credits_left).toLocaleString() : null;
  $("#uniStatus").innerHTML = !s.key_set ? `<span class="lozenge removed">Apollo not connected</span>`
    : s.connected ? `<span class="lozenge success" title="${esc(s.profile && s.profile.email ? "The key acts as " + s.profile.email : "Connected")}">Apollo connected</span>${left != null ? `<span class="uni-credits" title="Lead credits left this billing cycle">${esc(left)} credits left</span>` : ""}`
    : `<span class="lozenge moved">Apollo refused the key</span>`;
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
function uniDefs() { const u = state.uni; return (u.schema || []).filter((f) => f.for.includes(u.kind) && f.group !== "Search"); }
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
    }).join("") +
    (u.appOnly.length ? `<details class="uni-apponly"><summary>Filters Apollo's app has that its API does not</summary>
      <p>${esc(u.appOnly.join(", "))}. Apollo does not accept them through its API, so they are not offered here.</p></details>` : "");
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
    const d = await post("/api/universal/search", { kind: u.kind, filters, page: page || 1, per_page: u.perPage });
    if (token !== u.token) return;
    u.rows = (u.kind === "people" ? d.people : d.companies) || [];
    u.total = d.total || 0; u.page = d.page || 1;
    u.totalPages = Math.min(500, d.total_pages || Math.ceil(u.total / u.perPage) || 1);
    u.searched = true; u.resultKind = u.kind; u.lastFilters = filters; u.selected.clear();
    uniPersist();
    renderUniResults();
    if (u.kind === "companies") uniLoadStatus(false);        // that page cost a credit: show the new balance
  } catch (e) { toast(e.message, true); }
  finally { btn.classList.remove("loading"); }
}
function renderUniResults() {
  const u = state.uni, head = $("#uniHead"), body = $("#uniBody");
  if (!u.searched || u.resultKind !== u.kind) {
    head.innerHTML = "";
    body.innerHTML = `<tr class="empty-row"><td>${!uniConnected() ? "Connect Apollo to search."
      : u.kind === "people" ? "Choose filters on the left or type in the search bar, then Search. Searching people costs nothing."
      : "Choose filters, then Search. Each page of companies costs 1 Apollo credit."}</td></tr>`;
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
        <div class="secondary">${p.has_location ? "Location on file" : "No location on file"}</div></span></span></td>
      <td>${esc(p.title || "")}</td>
      <td>${esc(p.company || "")}${(p.company_known || []).length ? `<div class="secondary">Apollo knows its ${esc(p.company_known.join(", "))}</div>` : ""}</td>
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
  uniLoadStatus(false);
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
  $("#uniPerPage").addEventListener("change", (e) => {
    u.perPage = +e.target.value; uniPersist();
    if (u.searched && u.resultKind === u.kind && u.kind === "people") uniSearch(1);   // free; a company search waits for Search
  });
  $("#uniSaveSearch").addEventListener("click", uniSaveSearchDialog);
  $("#uniSavedBtn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($("#uniSavedBtn"), $("#uniSavedMenu"), renderUniSavedMenu); });
}

/* ======================================================= create modal */
async function openCreate() {
  let d;
  try { d = await api("/api/ops"); } catch (e) { return toast(e.message, true); }
  state.ops.jobs = d.jobs;
  const groups = {};
  d.jobs.forEach((j) => (groups[j.group] = groups[j.group] || []).push(j));
  const options = Object.entries(groups).map(([g, jobs]) => `<optgroup label="${esc(g)}">${jobs.map((j) =>
    `<option value="${esc(j.key)}" ${!j.available ? "disabled" : ""}>${esc(j.label)}${!j.available ? " (office n8n only)" : ""}</option>`).join("")}</optgroup>`).join("");
  modal.open(`
    ${modalHead(`${typeIcon("job")}<span>Create</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <p class="muted" style="margin-bottom:16px">Generate new leads or run any pipeline step. One job runs at a time; its log streams in Operations.</p>
      <div class="field" style="margin-bottom:16px"><label>Project <span class="req">*</span></label>
        <select disabled><option>US Production Houses</option></select></div>
      <div class="field" style="margin-bottom:16px"><label for="createJob">Job <span class="req">*</span></label>
        <select id="createJob" autofocus>${options}</select>
        <div class="help" id="createDesc"></div></div>
      ${d.busy ? `<div class="section-msg warning">${icon("warn", 24)}<div><div class="title">A job is already running</div><div class="text">${esc(d.busy)} has the slot. Wait for it to finish, or stop it in Operations.</div></div></div>` : ""}
    </div></div>
    <div class="modal-foot"><button class="btn subtle" data-close>Cancel</button>
      <button class="btn primary" id="createGo" ${d.busy ? "disabled" : ""}>Create</button></div>`,
    { narrow: true, label: "Create" });
  const root = $("#modalRoot"), sel = $("#createJob", root);
  const sync = () => { const j = d.jobs.find((x) => x.key === sel.value); $("#createDesc", root).textContent = j ? j.desc : ""; };
  sel.addEventListener("change", sync); sync();
  $("#createGo", root).addEventListener("click", () => { const key = sel.value; modal.close(true); runJob(key, { goToOps: true }); });
}

/* ==================================================== settings modal */
async function openSettings() {
  if (!state.rubric.length) { try { const s = await api("/api/stats"); state.rubric = s.rubric || []; } catch (e) {} }
  const total = state.rubric.reduce((x, r) => x + (+r.points || 0), 0);
  modal.open(`
    ${modalHead(`<span>Project settings</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <h2 class="modal-title" style="font-size:20px;line-height:24px">${esc(segUi().project_name)}</h2>
      <div class="section"><h3>Segment</h3><div class="body">
        <dl class="details"><dt>Slug</dt><dd class="mono">${esc((state.segment || {}).slug || "us-production-houses")}</dd>
        <dt>Config</dt><dd class="mono">${esc((state.segment || {}).config_file || "config/segment.us-production-houses.json")}</dd>
        <dt>Thresholds</dt><dd>Reviewable at ${REVIEW_THRESHOLD} points, priority at ${PRIORITY_THRESHOLD}. Cards show priority arrows from these.</dd></dl></div></div>
      <div class="section"><h3>Scoring rubric <span class="pts">${total} pts</span></h3><div class="body">
        ${state.rubric.length ? `<table class="tbl"><thead><tr><th>Criterion</th><th>Key</th><th class="r">Points</th></tr></thead><tbody>
        ${state.rubric.map((r) => `<tr><td>${esc(r.label || r.key)}${r.guidance ? `<div class="secondary">${esc(r.guidance)}</div>` : ""}</td><td class="mono">${esc(r.key)}</td><td class="r num">${r.points}</td></tr>`).join("")}
        </tbody></table>` : `<p class="muted">No rubric: this project's leads are picked by a person on the Apollo search page, so they carry no fit score.</p>`}</div></div>
      <div class="section"><h3>Changing it</h3><div class="body"><p class="muted">Everything segment-specific lives in the config file, not in code. Edit it, re-sync the row with <span class="mono">python tools/run_sql.py sql/03b_sync_segment_config_v3.sql</span>, then re-score from Operations.</p></div></div>
    </div></div>
    <div class="modal-foot"><button class="btn primary" data-close>Done</button></div>`, { label: "Project settings" });
}

function openAbout() {
  modal.open(`
    ${modalHead(`<span>How the engine works</span>`)}
    <div class="modal-body single"><div class="modal-main">
      <div class="section"><h3>Pipeline</h3><div class="body"><p><strong>Discover</strong> (news, X, YouTube, Wikidata, AICP) →
        <strong>Promote and dedupe</strong> → <strong>Enrich</strong> (website, contacts, evidence) → <strong>Score</strong> against the rubric →
        <strong>Review</strong> (this board) → <strong>Shortlist</strong> (its email is drafted) → <strong>Approve</strong> (it is sent) → <strong>Triage</strong> replies.</p>
        <p>Nothing outbound leaves without a person approving that exact text. One email per company, ever.</p></div></div>
      <div class="section"><h3>Where things run</h3><div class="body"><p>Harvests run in the office n8n on their schedule. Everything after that runs here, including the Tuesday 02:00 UTC weekly refresh. Drafting and sending run by themselves: shortlisting drafts the email, approving sends it, within the day's limit. Pulling replies runs from the terminal.</p></div></div>
      <div class="section"><h3>Keyboard</h3><div class="body">
        <dl class="details"><dt><span class="kbd">/</span></dt><dd>Search the current view</dd>
        <dt><span class="kbd">c</span></dt><dd>Create (run a job)</dd>
        <dt><span class="kbd">Esc</span></dt><dd>Close dialogs and menus</dd>
        <dt><span class="kbd">Enter</span></dt><dd>Open the focused card or row</dd></dl></div></div>
    </div></div>
    <div class="modal-foot"><button class="btn primary" data-close>Got it</button></div>`, { narrow: true, label: "Help" });
}

/* ============================================= notifications + shell */
function updateNotifBadge(counts) {
  const n = (counts.drafts || 0) + (counts.inbox || 0) + (counts.attention || 0);
  const badge = $("#notifBadge");
  badge.hidden = n === 0; badge.textContent = n > 99 ? "99+" : String(n);
  const side = $("#outreachCount");
  const waiting = (counts.drafts || 0) + (counts.outbox || 0);
  side.hidden = waiting === 0; side.textContent = String(waiting);
  state.notif.counts = counts; state.notif.at = Date.now();
}
async function refreshNotifications(force) {
  if (!force && Date.now() - state.notif.at < 90000) return;
  try { const d = await api("/api/outreach?folder=attention"); updateNotifBadge(d.counts || {}); } catch (e) {}
}
function renderNotifMenu(menu) {
  const c = state.notif.counts || {};
  const rows = [
    ["drafts", "Drafts waiting for approval", c.drafts || 0, "edit"],
    ["outbox", "Approved, waiting for the next send", c.outbox || 0, "send"],
    ["inbox", "Replies to triage", c.inbox || 0, "inbox"],
    ["attention", "Need attention", c.attention || 0, "warn"],
  ];
  menu.innerHTML = `<div class="menu-heading">Notifications</div>` + rows.map(([f, label, n, g]) =>
    `<button class="menu-item" data-folder="${f}">${icon(g, 20)}<span style="flex:1">${label}</span><span class="pts ${n ? "mid" : ""}">${n}</span></button>`).join("") +
    (rows.every((r) => !r[2]) ? `<div class="menu-note">All quiet. Nothing is waiting on a person.</div>` : "");
  $$("[data-folder]", menu).forEach((b) => b.addEventListener("click", () => { closeMenus(); state.outreach.folder = b.dataset.folder; go("outreach/" + b.dataset.folder); if (currentView() === "outreach") loadOutreach(); }));
}
function renderProjectsMenu(menu) {
  const segs = state.segments.length ? state.segments
    : [{ slug: "us-production-houses", project_name: "US Production Houses", current: true, counts: {} }];
  menu.innerHTML = `<div class="menu-heading">Projects</div>` + segs.map((s) =>
    `<button class="menu-item ${s.current ? "selected" : ""}" data-seg="${esc(s.slug)}">${icon(s.current ? "film" : "bookmark", 20)}
       <span style="flex:1">${esc(s.project_name)}<span class="desc">${esc(s.slug)}${s.counts && s.counts.reviewable != null ? ` · ${s.counts.reviewable} to review · ${s.counts.shortlisted} shortlisted` : ""}</span></span>
       ${s.current ? icon("check", 16) : ""}</button>`).join("") +
    `<div class="menu-sep"></div><div class="menu-note">A segment is a config row plus connectors. Switching changes every screen.</div>`;
  $$("[data-seg]", menu).forEach((b) => b.addEventListener("click", async () => {
    closeMenus();
    if (state.segment && b.dataset.seg === state.segment.slug) return;
    try { await post("/api/segment/select", { slug: b.dataset.seg }); history.replaceState(null, "", location.pathname); location.reload(); }
    catch (e) { toast(e.message, true); }
  }));
}
function renderHelpMenu(menu) {
  menu.innerHTML = `<div class="menu-heading">Help</div>
    <button class="menu-item" id="helpAbout">${icon("book", 20)}<span>How the engine works<span class="desc">Pipeline, where things run, shortcuts</span></span></button>
    <div class="menu-sep"></div>
    <div class="menu-note">Runbook: docs/runbook.md · Deploy: docs/DEPLOY.md · Plan: BUILD_PLAN.md</div>`;
  $("#helpAbout", menu).addEventListener("click", () => { closeMenus(); openAbout(); });
}
function themeMode() { return document.documentElement.dataset.theme || "auto"; }
function setTheme(mode) {
  if (mode === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = mode;
  try { if (mode === "auto") localStorage.removeItem("tvf_theme"); else localStorage.setItem("tvf_theme", mode); } catch (e) {}
}
function renderUserMenu(menu) {
  const email = state.user || "";
  const cur = themeMode();
  const opt = (mode, label, g) => `<button class="menu-item ${cur === mode ? "selected" : ""}" data-theme="${mode}">${icon(g, 20)}<span style="flex:1">${label}</span>${cur === mode ? icon("check", 16) : ""}</button>`;
  menu.innerHTML = `<div class="menu-user">${avatar(null, email, "lg")}<div style="min-width:0"><div class="email truncate">${esc(email || "Signed in")}</div><div class="small muted">TVF Lead Engine</div></div></div>
    <div class="menu-sep"></div><div class="menu-heading">Theme</div>
    ${opt("light", "Light", "sun")}${opt("dark", "Dark", "moon")}${opt("auto", "Match system", "monitor")}
    <div class="menu-sep"></div>
    <button class="menu-item" id="logoutBtn">${icon("logout", 20)}<span>Log out</span></button>`;
  $$("[data-theme]", menu).forEach((b) => b.addEventListener("click", () => { setTheme(b.dataset.theme); renderUserMenu(menu); }));
  $("#logoutBtn", menu).addEventListener("click", async () => {
    try { await post("/api/auth/logout"); } catch (e) {}
    location.href = "/login";
  });
}

function bindShell() {
  const pairs = [["#notifBtn", "#notifMenu", renderNotifMenu], ["#helpBtn", "#helpMenu", renderHelpMenu],
    ["#userBtn", "#userMenu", renderUserMenu],
    ["#projectSwitch", "#projectSwitchMenu", renderProjectsMenu]];   // the project switcher at the top of the sidebar
  pairs.forEach(([b, m, r]) => $(b).addEventListener("click", (e) => { e.stopPropagation(); toggleMenu($(b), $(m), r); }));
  $$("[data-route]").forEach((b) => b.addEventListener("click", () => go(b.dataset.route)));
  $("#createSide").addEventListener("click", openCreate);          // hidden where the Apollo page generates leads
  $("#settingsSide").addEventListener("click", openSettings);
  $("#notifBtn").addEventListener("click", () => refreshNotifications(true));

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

  // global search: applies to the board or list you are on, otherwise opens the list
  let t;
  $("#globalSearch").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      const v = e.target.value.trim();
      // on the Apollo page the box fills the page's own search bar; Enter runs it (it may cost a credit)
      if (currentView() === "universal") { $("#uniQuery").value = v; state.uni.q[state.uni.kind] = v; return; }
      if (currentView() === "board") { state.board.filters.q = v; $("#boardSearch").value = v; loadBoard(); }
      else { state.leads.filters.q = v; $("#leadsSearch").value = v; state.leads.page = 0; if (currentView() === "leads") loadLeads(); else if (v) go("leads"); }
    }, 300);
  });
  $("#globalSearch").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && currentView() === "universal") { e.preventDefault(); uniSearch(1); }
  });
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || modal.isOpen()) return;
    if (e.key === "/") { e.preventDefault(); ($("#view-board").classList.contains("active") ? $("#boardSearch") : currentView() === "leads" ? $("#leadsSearch") : currentView() === "universal" ? $("#uniQuery") : $("#globalSearch")).focus(); }
    if (e.key === "c") { e.preventDefault(); if (segUi().search_page === "apollo") go("universal"); else openCreate(); }
  });
}

/* ======================================================= filter wiring */
function syncLeadControls() {
  const f = state.leads.filters;
  $("#leadsSearch").value = f.q; $("#leadsStatus").value = f.status; $("#leadsScore").value = String(f.min_score);
  $("#leadsSource").value = f.source; $("#leadsSort").value = f.sort;
  $("#leadsContact").setAttribute("aria-pressed", String(f.has_contact));
  $("#leadsContact").classList.toggle("selected", f.has_contact);
}
function bindFilters() {
  let t;
  const b = state.board.filters, l = state.leads.filters;
  $("#boardSearch").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { b.q = e.target.value.trim(); loadBoard(); }, 250); });
  $("#boardScore").addEventListener("change", (e) => { b.min_score = +e.target.value; loadBoard(); });
  $("#boardSource").addEventListener("change", (e) => { b.source = e.target.value; loadBoard(); });
  $("#boardContact").addEventListener("click", (e) => {
    b.has_contact = !b.has_contact;
    e.currentTarget.setAttribute("aria-pressed", String(b.has_contact)); e.currentTarget.classList.toggle("selected", b.has_contact);
    loadBoard();
  });
  $("#boardRefresh").addEventListener("click", loadBoard);
  $("#reportsRefresh").addEventListener("click", loadReports);
  $("#leadsSearch").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { l.q = e.target.value.trim(); state.leads.page = 0; loadLeads(); }, 250); });
  $("#leadsStatus").addEventListener("change", (e) => { l.status = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsScore").addEventListener("change", (e) => { l.min_score = +e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsSource").addEventListener("change", (e) => { l.source = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsSort").addEventListener("change", (e) => { l.sort = e.target.value; state.leads.page = 0; loadLeads(); });
  $("#leadsContact").addEventListener("click", (e) => {
    l.has_contact = !l.has_contact;
    e.currentTarget.setAttribute("aria-pressed", String(l.has_contact)); e.currentTarget.classList.toggle("selected", l.has_contact);
    state.leads.page = 0; loadLeads();
  });
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
    state.rubric = s.rubric || [];
    state.sources = s.by_source.map((r) => r.source);
    const opts = '<option value="">All sources</option>' + s.by_source.map((r) =>
      `<option value="${esc(r.source)}">${esc(sourceLabel(r.source))} (${r.n})</option>`).join("");
    $("#boardSource").innerHTML = opts; $("#leadsSource").innerHTML = opts;
  } catch (e) {
    flag("Cannot reach the database", { desc: "Is SUPABASE_DB_URL set? " + e.message, kind: "err", ms: 8000 });
  }
  try {
    const [seg, segs] = await Promise.all([api("/api/segment"), api("/api/segments")]);
    state.segments = segs.segments || [];
    applySegment(seg);
    $("#boardScore").value = String(REVIEW_THRESHOLD);
  } catch (e) { /* older server: TVF defaults stand */ }
  syncLeadControls();
  router();
  refreshNotifications(true);
  setInterval(() => refreshNotifications(false), 120000);
})();
