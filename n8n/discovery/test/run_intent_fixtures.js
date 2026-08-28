#!/usr/bin/env node
/**
 * run_intent_fixtures.js -- the X-intent connector's judgement layer.
 *
 * This source is noisy in a specific, documented way: "co-production" is a term
 * of art in UK adult social care, and that usage dominates the feed. A live
 * probe of site:x.com "co-production" returned a Swansea co-production network,
 * an adult social care conference, a Nigeria-China film partnership and a
 * co-production week newsletter -- one of four about screen.
 *
 * So the fixtures below are mostly REAL noise, taken from that probe. If the
 * filter lets these through, the connector fills staging with local-government
 * engagement work and someone eventually cold-emails a council.
 *
 * Usage:  node n8n/discovery/test/run_intent_fixtures.js
 */
const fs = require("fs");
const path = require("path");

const CODE_DIR = path.join(__dirname, "..", "code");
const CONFIG = path.join(__dirname, "..", "..", "..", "config",
  "segment.us-production-houses.json");
const SEGMENT_ID = "d9b72912-6401-4716-ae70-409b37eef71b";

function wrap(file) {
  return new Function("$input", "$", fs.readFileSync(path.join(CODE_DIR, file), "utf8"));
}
const items = (arr) => arr.map((json) => ({ json }));
const ctxOf = (store) => (name) => ({ all: () => store[name] || [] });
const inputOf = (arr) => ({ all: () => arr, first: () => arr[0] });

const cfg = JSON.parse(fs.readFileSync(CONFIG, "utf8"));
const queries = cfg.x_intent_discovery_queries;

let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  if (ok) { pass++; console.log("  PASS  " + label); }
  else { fail++; console.log("  FAIL  " + label + (detail ? "\n          " + detail : "")); }
};

console.log("conn_x_intent_signals -- code-node fixtures\n");

// ---- 11 Split (shared with News RSS) ---------------------------------------
const split = wrap("11_split_news_queries.js")(
  inputOf(items([{ queries, segment_id: SEGMENT_ID }])), null);
console.log("11_split_news_queries (shared)");
check("one item per config query (" + queries.length + ")", split.length === queries.length);
check("site: operators survive URL encoding",
  split.some((i) => decodeURIComponent(i.json.feed_url).includes("site:x.com")));

// ---- 14 Filter + Extract ---------------------------------------------------
const POSTS = [
  { label: "REAL NOISE: adult social care conference",
    title: "Celebrating adult social care co-production Join us for a collaborative conference",
    desc: "Service users and lived experience partners welcome.", admit: false },
  { label: "REAL NOISE: a council co-production network",
    title: "Swansea Co-Production Network is a network of people interested in working co-productively",
    desc: "Local authority community engagement.", admit: false },
  { label: "REAL NOISE: co-production week newsletter",
    title: "This Co-production Week we are proud to share the latest edition of Heads-Up",
    desc: "Wellbeing and public services.", admit: false },
  { label: "screen-adjacent but NO invitation",
    title: "Nigeria and China deepen cultural ties through film partnership",
    desc: "Unlocking co-production and technology transfer.", admit: false },
  { label: "invitation + industry + nameable company",
    title: "Thornfield Pictures is open to co-productions and looking for partners on new drama",
    desc: "The indie studio wants scripted series pitches.", admit: true,
    expect: "Thornfield Pictures" },
  { label: "invitation + industry, but nothing nameable",
    title: "We are open to co-productions on our next series", desc: "A studio account.",
    admit: false },
  { label: "a major saying it is open -- never a lead",
    title: "Netflix Studios is looking for partners on unscripted series",
    desc: "Streaming giant opens submissions.", admit: false },
  // CHANGED 2026-08-27. This case used to assert that "accepting submissions"
  // earned admission. The first live run proved that wrong: all four rows it
  // returned were festivals using exactly that phrase. Submissions language
  // belongs to festivals; partnership language belongs to companies. The case
  // is kept, inverted, so the old behaviour cannot quietly return.
  { label: "submissions language alone is NOT a partner signal",
    title: "Lantern Row Media accepting submissions for its comedy series slate",
    desc: "The production company opens its door to writers.", admit: false },
  { label: "the same shop using real partnership language",
    title: "Lantern Row Media is looking for partners on its comedy series slate",
    desc: "The production company wants co-production partners.", admit: true,
    expect: "Lantern Row Media" },
];

const parsed = POSTS.map((p) => ({
  title: p.title, description: p.desc, matched_query: queries[0].query,
  deal_kind: queries[0].intent, segment_id: SEGMENT_ID,
  link: "https://x.com/test/status/1", pubDate: null,
}));

const rows = wrap("14_filter_extract_intent.js")(inputOf(items(parsed)), ctxOf({}));
const names = new Set(rows.map((r) => r.json.name));

console.log("\n14_filter_extract_intent");
POSTS.forEach((p) => {
  if (p.admit) {
    check("admits: " + p.label, names.has(p.expect),
      "expected to find " + p.expect);
  } else {
    check("rejects: " + p.label,
      !rows.some((r) => r.json.raw.post_text === p.title));
  }
});

check("every admitted row earns collaboration_openness = 1",
  rows.length > 0 && rows.every((r) =>
    r.json.raw.scoring_inputs.collaboration_openness === 1),
  "this criterion is the only reason the source exists");
check("records WHICH invitation phrase justified it",
  rows.every((r) => (r.json.raw.invitation_phrases || []).length > 0));
check("never guesses geography, size, genre or IP experience",
  rows.every((r) => {
    const si = r.json.raw.scoring_inputs;
    return !("geography_signal" in si) && !("right_size" in si)
        && !("genre_fit" in si) && !("international_ip_experience" in si);
  }),
  "a post saying 'we want partners' proves openness and nothing else");
check("tagged source=x_intent_signals",
  rows.every((r) => r.json.source === "x_intent_signals"));
check("carries segment_id", rows.every((r) => r.json.segment_id === SEGMENT_ID));
check("keeps the post URL for the reviewer",
  rows.every((r) => typeof r.json.source_url === "string"));
check("no scoring_inputs key the config does not define", (() => {
  const known = new Set([...cfg.rubric, ...cfg.score_modifiers, ...cfg.gates]
    .map((x) => x.input.split(".").pop()));
  return rows.every((r) =>
    Object.keys(r.json.raw.scoring_inputs).every((k) => known.has(k)));
})());
check("reports its own noise level so tuning is measurable",
  rows.length > 0 && rows[0].json.raw.filter_stats
  && rows[0].json.raw.filter_stats.dropped_off_domain >= 3,
  "if off-domain drops dwarf admissions, the queries need work -- a config edit");

// ---- REGRESSIONS FROM THE FIRST LIVE RUN -----------------------------------
// The first live P6 run returned exactly four rows and ALL FOUR were film
// festivals or competitions. Not a near miss -- 0% precision. "Accepting
// submissions" is festival vocabulary: festivals solicit submissions,
// production companies solicit partners. These are the real post texts.
const LIVE_NOISE = [
  "Dan Bailey's Outdoor Company accepting submissions for 2025 Cold Snap Film competition",
  "18th Annual Hamilton Film Festival Set for July; Accepting Submissions Now",
  "Egypt's El-Gouna Film Festival starts accepting submissions for its 2026 edition",
  "Sundance Institute opens its screenwriting fellowship for submissions",
  "Tribeca Festival announces call for entries across all categories",
];
const noiseRows = wrap("14_filter_extract_intent.js")(inputOf(items(
  LIVE_NOISE.map((t) => ({
    title: t, description: "", matched_query: queries[0].query, deal_kind: null,
    segment_id: SEGMENT_ID, link: "https://x.com/a/1", pubDate: null })))), ctxOf({}));

console.log("\n14_filter_extract_intent -- regressions from the live run");
check("rejects ALL FIVE festival/competition posts", noiseRows.length === 0,
  "the live run admitted 4 of 4 of these; got " + noiseRows.length
  + (noiseRows.length ? " -> " + noiseRows.map((r) => r.json.name).join(", ") : ""));
LIVE_NOISE.slice(0, 3).forEach((t) => {
  check("  rejects: " + t.slice(0, 52),
    !noiseRows.some((r) => r.json.raw.post_text === t));
});

// ---- 04 Summarize (shared) -------------------------------------------------
const summary = wrap("04_summarize_source_run.js")(inputOf(rows), ctxOf({}));
console.log("\n04_summarize_source_run (shared)");
check("reads source from the items", summary[0].json.source === "x_intent_signals");
check("counts admitted rows", summary[0].json.candidates_found === rows.length);

console.log("\n" + (fail === 0
  ? "GREEN -- " + pass + " checks passed."
  : "FAILED -- " + fail + " of " + (pass + fail) + " checks failed."));
const st = rows[0] && rows[0].json.raw.filter_stats;
if (st) {
  console.log("\nfilter, on " + st.seen + " fixture posts:");
  console.log("  off-domain (social care etc) : " + st.dropped_off_domain);
  console.log("  no screen-industry words     : " + st.dropped_no_industry_words);
  console.log("  no invitation phrase         : " + st.dropped_no_invitation);
  console.log("  nothing nameable             : " + st.dropped_no_company_name);
  console.log("  ADMITTED                     : " + st.admitted);
}
rows.forEach((r) => console.log("  - " + r.json.name
  + "   via: " + r.json.raw.invitation_phrases.join(", ")));

process.exit(fail === 0 ? 0 : 1);
