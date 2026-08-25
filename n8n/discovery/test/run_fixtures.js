#!/usr/bin/env node
/**
 * run_fixtures.js -- run the four Code-node scripts outside n8n, against
 * realistic YouTube API fixtures.
 *
 * WHY THIS EXISTS. The connector was logic-validated once, before the repo was
 * cleared, and has never been run against live YouTube. Rule 4 of BUILD_PLAN.md
 * says an artifact re-adopted from history is re-verified at adoption time, not
 * trusted because it passed once. This is that re-verification.
 *
 * It cannot prove the connector works against the real API -- only a live run
 * does that. What it does prove is that the JUDGEMENT layer behaves: which
 * channels are admitted, which are discarded, what gets extracted from a
 * description, and which scoring_inputs keys are set versus deliberately left
 * absent. That layer is where the interesting bugs live, and it is pure
 * function-of-input, so it is fully testable on the desk.
 *
 * HOW: each script is read from disk and wrapped in a function that is handed a
 * fake `$input` and `$()`, mimicking the two n8n globals the scripts use. The
 * scripts are executed byte-for-byte as n8n will run them -- no copy, no
 * re-implementation, so this test cannot drift from what ships.
 *
 * Usage:  node n8n/discovery/test/run_fixtures.js
 */
const fs = require("fs");
const path = require("path");

const CODE_DIR = path.join(__dirname, "..", "code");
const CONFIG = path.join(__dirname, "..", "..", "..", "config",
  "segment.us-production-houses.json");

const SEGMENT_ID = "d9b72912-6401-4716-ae70-409b37eef71b";

// ---------------------------------------------------------------- n8n shim
function wrap(file) {
  const src = fs.readFileSync(path.join(CODE_DIR, file), "utf8");
  // n8n Code nodes run with $input and $ in scope and a bare top-level return.
  return new Function("$input", "$", src);
}
const items = (arr) => arr.map((json) => ({ json }));
const ctxOf = (store) => (name) => ({ all: () => store[name] || [] });
const inputOf = (arr) => ({ all: () => arr, first: () => arr[0] });

// ---------------------------------------------------------------- fixtures
const cfg = JSON.parse(fs.readFileSync(CONFIG, "utf8"));
const configQueries = cfg.youtube_discovery_queries;

function searchHit(channelId) {
  return { id: { kind: "youtube#channel", channelId } };
}
function channelDetail(o) {
  return {
    items: [{
      snippet: {
        title: o.title,
        description: o.description || "",
        ...(o.country ? { country: o.country } : {}),
      },
      statistics: {
        ...(o.subs !== undefined && o.subs !== null
          ? { subscriberCount: String(o.subs) } : {}),
        videoCount: String(o.videos || 42),
      },
    }],
  };
}

// One channel per case, in the order they will flow through the pipeline.
const CASES = [
  {
    label: "studio, website in description, US",
    id: "UC_studio_ok",
    detail: channelDetail({
      title: "Lantern Row Studios",
      description: "Independent comedy studio. More at https://lanternrowmedia.com or reach us at hello@lanternrowmedia.com",
      country: "US", subs: 24000,
    }),
    expect: (r) => r && r.domain === "lanternrowmedia.com"
      && r.raw.extracted_email === "hello@lanternrowmedia.com"
      && r.raw.scoring_inputs.geography_signal === "us"
      && r.raw.scoring_inputs.has_reachable_presence === true,
  },
  {
    label: "known major flagged, not silently dropped",
    id: "UC_major",
    detail: channelDetail({
      title: "Netflix", description: "Netflix original series and films.",
      country: "US", subs: 28000000,
    }),
    expect: (r) => r && r.raw.scoring_inputs.major_or_oversized_signal === true,
  },
  {
    label: "oversized by subscriber count alone",
    id: "UC_oversized",
    detail: channelDetail({
      title: "Giant Media Network", description: "Entertainment for everyone.",
      country: "US", subs: 9000000,
    }),
    expect: (r) => r && r.raw.scoring_inputs.major_or_oversized_signal === true,
  },
  {
    label: "tiny vlogger, no keyword, below floor -> DISCARDED",
    id: "UC_vlogger",
    detail: channelDetail({
      title: "Dave's Daily Vlog", description: "just me and my cat",
      country: "US", subs: 140,
    }),
    expect: (r) => r === undefined,
  },
  {
    label: "below floor BUT keyword present -> admitted",
    id: "UC_small_studio",
    detail: channelDetail({
      title: "Tiny Pictures", description: "A two-person production company.",
      country: "US", subs: 300,
    }),
    expect: (r) => r !== undefined,
  },
  {
    label: "non-US channel gets geography_signal non_us",
    id: "UC_uk",
    detail: channelDetail({
      title: "Thames Productions", description: "British comedy studio.",
      country: "GB", subs: 50000,
    }),
    expect: (r) => r && r.raw.scoring_inputs.geography_signal === "non_us",
  },
  {
    label: "no country field -> geography_signal ABSENT, not defaulted",
    id: "UC_nocountry",
    detail: channelDetail({
      title: "Nomad Studio", description: "We make things.", subs: 8000,
    }),
    expect: (r) => r && !("geography_signal" in r.raw.scoring_inputs),
  },
  {
    label: "obfuscated email is de-obfuscated",
    id: "UC_obfus",
    detail: channelDetail({
      title: "Quiet Media", description: "Contact: hello [at] quietmedia [dot] com",
      country: "US", subs: 5000,
    }),
    expect: (r) => r && r.raw.extracted_email === "hello@quietmedia.com",
  },
  {
    label: "social links only -> domain stays null",
    id: "UC_social",
    detail: channelDetail({
      title: "Social Only Studio",
      description: "https://instagram.com/socialonly and https://linktr.ee/socialonly",
      country: "US", subs: 12000,
    }),
    expect: (r) => r && r.domain === null,
  },
  {
    label: "channels.list returned nothing -> skipped, no crash",
    id: "UC_missing",
    detail: { items: [] },
    expect: (r) => r === undefined,
  },
];

// ---------------------------------------------------------------- run
let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  if (ok) { pass++; console.log("  PASS  " + label); }
  else { fail++; console.log("  FAIL  " + label + (detail ? "\n          " + detail : "")); }
};

console.log("conn_youtube_api -- code-node fixtures\n");

// --- 01 Split Queries: config -> one item per query
const split = wrap("01_split_queries.js")(
  inputOf(items([{ queries: configQueries, segment_id: SEGMENT_ID }])), null);
console.log("01_split_queries");
check("emits one item per config query (" + configQueries.length + ")",
  split.length === configQueries.length, "got " + split.length);
check("carries segment_id onto every item",
  split.every((i) => i.json.segment_id === SEGMENT_ID));
check("keeps genre_hint, including explicit nulls",
  split.filter((i) => i.json.genre_hint === null).length ===
  configQueries.filter((q) => q.genre_hint === null).length);

// --- 02 Flatten: one search response per query, deduped by channel id
// Give query 1 three hits, query 2 two hits (one a DUPLICATE of query 1).
const searchResponses = configQueries.map((q, i) => {
  if (i === 0) return { items: CASES.slice(0, 3).map((c) => searchHit(c.id)) };
  if (i === 1) return { items: [searchHit(CASES[0].id), ...CASES.slice(3, 6).map((c) => searchHit(c.id))] };
  if (i === 2) return { items: CASES.slice(6, 10).map((c) => searchHit(c.id)) };
  return { items: [] };
});
const store = { "Split Queries": split };
const flat = wrap("02_flatten_search_results.js")(
  inputOf(items(searchResponses)), ctxOf(store));
console.log("\n02_flatten_search_results");
check("dedupes a channel returned by two different queries",
  flat.length === CASES.length, "expected " + CASES.length + ", got " + flat.length);
check("attaches the matching query to each channel",
  flat[0].json.matched_query === configQueries[0].query);
check("channel first seen under query 1 keeps query 1, not query 2",
  flat.find((i) => i.json.channel_id === CASES[0].id).json.matched_query
  === configQueries[0].query);

// --- 03 Filter/Score/Shape
store["Flatten Search Results"] = flat;
const detailResponses = flat.map((i) =>
  CASES.find((c) => c.id === i.json.channel_id).detail);
const shaped = wrap("03_filter_score_shape.js")(
  inputOf(items(detailResponses)), ctxOf(store));
console.log("\n03_filter_score_shape");
const byId = {};
shaped.forEach((i) => { byId[i.json.raw.channel_id] = i.json; });
for (const c of CASES) check(c.label, c.expect(byId[c.id]));
check("every admitted row carries source = youtube_api",
  shaped.every((i) => i.json.source === "youtube_api"));
check("every admitted row carries a source_url",
  shaped.every((i) => /^https:\/\/www\.youtube\.com\/channel\//.test(i.json.source_url)));
check("genre_fit from a query match is 0.5, never full credit",
  shaped.every((i) => !("genre_fit" in i.json.raw.scoring_inputs)
    || i.json.raw.scoring_inputs.genre_fit === 0.5),
  "a search-query match is weak evidence; full marks would inflate every "
  + "YouTube lead against hand-researched rows at Checkpoint 1");
check("no admitted row invents a scoring_inputs key the config does not define",
  (() => {
    const known = new Set([...cfg.rubric, ...cfg.score_modifiers, ...cfg.gates]
      .map((x) => x.input.split(".").pop()));
    return shaped.every((i) =>
      Object.keys(i.json.raw.scoring_inputs).every((k) => known.has(k)));
  })());

// --- 04 Summarize
const summary = wrap("04_summarize_source_run.js")(inputOf(shaped), ctxOf(store));
console.log("\n04_summarize_source_run");
check("emits exactly one source_runs row", summary.length === 1);
check("counts the admitted candidates, not the searched ones",
  summary[0].json.candidates_found === shaped.length,
  "found=" + summary[0].json.candidates_found + " admitted=" + shaped.length);
check("carries segment_id", summary[0].json.segment_id === SEGMENT_ID);
check("status succeeded", summary[0].json.status === "succeeded");

console.log("\n" + (fail === 0
  ? "GREEN -- " + pass + " checks passed."
  : "FAILED -- " + fail + " of " + (pass + fail) + " checks failed."));
console.log("\nAdmitted " + shaped.length + " of " + CASES.length + " fixture channels:");
shaped.forEach((i) => console.log("  - " + i.json.name +
  "  domain=" + (i.json.domain || "(none)") +
  "  inputs=" + JSON.stringify(i.json.raw.scoring_inputs)));

process.exit(fail === 0 ? 0 : 1);
