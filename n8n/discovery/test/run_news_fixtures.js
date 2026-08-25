#!/usr/bin/env node
/**
 * run_news_fixtures.js -- exercise the Google News RSS connector's code nodes
 * against realistic feed items, before it ever touches the live feed.
 *
 * The interesting failure here is not a crash. It is a PLAUSIBLE WRONG ANSWER:
 * the wrong company pulled out of a headline, or a 30-point
 * international_ip_experience awarded on no real evidence. Neither throws;
 * both quietly poison the review queue and Checkpoint 1. So most of what
 * follows tests judgement, not mechanics.
 *
 * Scripts are read from disk and executed as-is, so this cannot drift from
 * what ships.
 *
 * Usage:  node n8n/discovery/test/run_news_fixtures.js
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
const queries = cfg.news_rss_discovery_queries;

let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  if (ok) { pass++; console.log("  PASS  " + label); }
  else { fail++; console.log("  FAIL  " + label + (detail ? "\n          " + detail : "")); }
};

console.log("conn_google_news_rss -- code-node fixtures\n");

// ---- 11 Split News Queries -------------------------------------------------
const split = wrap("11_split_news_queries.js")(
  inputOf(items([{ queries, segment_id: SEGMENT_ID }])), null);
console.log("11_split_news_queries");
check("one item per config query (" + queries.length + ")", split.length === queries.length);
check("builds a Google News RSS search URL",
  split.every((i) => i.json.feed_url.startsWith("https://news.google.com/rss/search?q=")));
check("URL-encodes quoted phrases rather than breaking the querystring",
  split[0].json.feed_url.includes("%22"));
check("pins the US English edition (hl/gl/ceid)",
  split.every((i) => i.json.feed_url.includes("hl=en-US")
    && i.json.feed_url.includes("gl=US") && i.json.feed_url.includes("ceid=US%3Aen")
    || i.json.feed_url.includes("ceid=US:en")));
check("carries segment_id and deal_kind forward",
  split.every((i) => i.json.segment_id === SEGMENT_ID && "deal_kind" in i.json));

// ---- 12 Parse News Feed ----------------------------------------------------
// Realistic Google News RSS XML: entity-encoded HTML in <description>, a
// "Headline - Publisher" title, CDATA in places.
function feedXml(items) {
  return '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>'
    + items.map((i) => '<item><title>' + i.t + '</title><link>' + i.l + '</link>'
        + '<pubDate>Sat, 23 Aug 2026 09:00:00 GMT</pubDate>'
        + '<description>&lt;a href="x"&gt;' + i.d + '&lt;/a&gt;</description>'
        + '<source url="https://variety.com">Variety</source></item>').join('')
    + '</channel></rss>';
}

const Q0 = [
  { t: "Lantern Row Media Acquires Format Rights to Korean Hit &#39;Office Hours&#39; - Variety",
    l: "https://news.google.com/rss/articles/AAA",
    d: "The Austin-based studio will produce a local adaptation for a US streamer." },
  { t: "Netflix Orders Comedy Series From Tandem Pictures - Deadline",
    l: "https://news.google.com/rss/articles/BBB",
    d: "Netflix has given a series order to the indie shop." },
  { t: "Quiet Harbor Studios Names New Head of Development - Variety",
    l: "https://news.google.com/rss/articles/CCC", d: "Effective September." },
];
const Q1 = [
  { t: "BBC and Thornfield Pictures Set Co-Production Of New Drama - Deadline",
    l: "https://news.google.com/rss/articles/DDD", d: "The co-production shoots in Wales." },
  { t: "Studios Brace For A Slow Autumn - Variety",
    l: "https://news.google.com/rss/articles/EEE", d: "An industry-wide pullback." },
];
// One response per query, in the same order as the 6 config queries.
const responses = [
  { data: feedXml(Q0) }, { data: feedXml(Q1) },
  { data: feedXml([]) }, { data: feedXml([]) }, { data: feedXml([]) },
  { data: "" },   // a query that returned nothing at all -- must not crash
];

const store = { "Split News Queries": split };
const parsed = wrap("12_parse_news_feed.js")(inputOf(items(responses)), ctxOf(store));

console.log("\n12_parse_news_feed");
check("parses every <item> across all feeds",
  parsed.length === Q0.length + Q1.length, "got " + parsed.length);
check("decodes HTML entities in the description",
  parsed[0].json.description.includes("Austin-based"));
check("decodes numeric entities in the title",
  parsed[0].json.title.includes("'Office Hours'"));
check("an empty response body does not crash the node", true);

// THE REGRESSION TEST. The live P5 run died here: the first version recovered
// query context from item.pairedItem, which enumerates OUTPUT items (0..118 on
// the real run), not the 6 query inputs. Everything past index 5 lost its
// segment_id and the insert failed on a NOT NULL constraint.
check("EVERY parsed article carries segment_id -- not just the first few",
  parsed.every((p) => p.json.segment_id === SEGMENT_ID),
  "regression: pairedItem enumerated output items, so rows past index 5 "
  + "resolved to an empty context and inserted null");
check("query context is zipped by RESPONSE index, not item index",
  parsed.slice(0, 3).every((p) => p.json.matched_query === queries[0].query)
  && parsed.slice(3).every((p) => p.json.matched_query === queries[1].query));

// ---- 13 Extract Companies --------------------------------------------------
const rows = wrap("13_extract_companies.js")(inputOf(parsed), ctxOf(store));
const by = {};
rows.forEach((r) => { by[r.json.name] = r.json; });

console.log("\n13_extract_companies");
check("extracts the company from a format-deal headline", !!by["Lantern Row Media"]);
check("awards international_ip_experience on REAL deal language",
  by["Lantern Row Media"]
  && by["Lantern Row Media"].raw.scoring_inputs.international_ip_experience === 1);
check("records WHICH phrase justified the 30 points",
  by["Lantern Row Media"]
  && by["Lantern Row Media"].raw.ip_format_phrases.includes("format rights"));
check("does NOT turn the buyer (Netflix) into a lead", !by["Netflix"]);
check("does extract the seller from a buyer-led headline", !!by["Tandem Pictures"]);
check("a domestic series order does NOT earn international_ip_experience",
  by["Tandem Pictures"]
  && !("international_ip_experience" in by["Tandem Pictures"].raw.scoring_inputs),
  "a Netflix commission proves route-to-market, not foreign-IP adaptation");
check("a domestic series order DOES earn distribution_relationship",
  by["Tandem Pictures"]
  && by["Tandem Pictures"].raw.scoring_inputs.distribution_relationship === 1);
check("no deal language -> international_ip_experience ABSENT, not 0 or 1",
  by["Quiet Harbor Studios"]
  && !("international_ip_experience" in by["Quiet Harbor Studios"].raw.scoring_inputs));
check("broadcaster in a co-pro headline is not a lead", !by["BBC"]);
check("the indie partner in a co-pro headline IS a lead", !!by["Thornfield Pictures"]);
check("co-production counts as IP evidence",
  by["Thornfield Pictures"]
  && by["Thornfield Pictures"].raw.scoring_inputs.international_ip_experience === 1);
check("a bare suffix never becomes a company name",
  !by["Studios"] && !by["Pictures"] && !by["Media"]);
check("EVERY row carries segment_id -- the bug that broke the live run",
  rows.length > 0 && rows.every((r) => r.json.segment_id === SEGMENT_ID));
check("every row is tagged source=google_news_rss",
  rows.every((r) => r.json.source === "google_news_rss"));
check("every row keeps its article URL for the reviewer",
  rows.every((r) => typeof r.json.source_url === "string" && r.json.source_url.length > 0));
check("every row records which query found it",
  rows.every((r) => typeof r.json.raw.matched_query === "string"));
check("domain left null -- filled at enrichment, like AICP rows",
  rows.every((r) => r.json.domain === null));
check("no scoring_inputs key the config does not define", (() => {
  const known = new Set([...cfg.rubric, ...cfg.score_modifiers, ...cfg.gates]
    .map((x) => x.input.split(".").pop()));
  return rows.every((r) =>
    Object.keys(r.json.raw.scoring_inputs).every((k) => known.has(k)));
})());
check("connector never guesses geography, size or genre",
  rows.every((r) => {
    const si = r.json.raw.scoring_inputs;
    return !("geography_signal" in si) && !("right_size" in si) && !("genre_fit" in si);
  }));

// ---- 13 Extract: regressions from the FIRST LIVE RUN -----------------------
// Every headline below is real, taken from the 119 names the first live P5 run
// produced. Each one yielded a "company" that is not a company. Fixture cases
// invented at the desk did not catch these; only running it did.
const REAL = [
  { h: "Tyler Perry to Produce English-Language Remake of Korean Film 'Miss Granny'",
    wrong: "Korean Film", why: "origin word -- describes the SOURCE, not the buyer" },
  { h: "The Mediapro Studio Snags Spanish Adaptation Rights to Belgian Hit TV Series",
    wrong: "Belgian Hit TV", why: "origin word again", right: "Mediapro Studio" },
  { h: "John Wick and Highlander Production Company to Make English-Language Indian Action Film",
    wrong: "Indian Action Film", why: "origin word", right: "Highlander Production Company" },
  { h: "Reese Witherspoon's production company picks up format rights to Country Living",
    wrong: "Reese Witherspoon's production", why: "lowercase suffix + possessive" },
  { h: "John Wick franchise makers to work on English-language remake of Indian film",
    wrong: "Indian film", why: "lowercase suffix and an origin word" },
  { h: "Im Siwan And Sol Kyung Gu's Film 'The Merciless' Confirmed For English Remake",
    wrong: "Sol Kyung Gu's Film", why: "possessive -- a person's film, not a firm" },
  { h: "Signing of the Council of Europe Convention on the Co-production of Audiovisual Works",
    wrong: "Audiovisual Works", why: "every word generic -- a treaty, not a company" },
];

const realRows = wrap("13_extract_companies.js")(inputOf(items(REAL.map((r) => ({
  title: r.h + " - Variety", description: "", matched_query: queries[0].query,
  deal_kind: null, segment_id: SEGMENT_ID, link: "https://example.test/a",
})))), ctxOf(store));
const realNames = new Set(realRows.map((r) => r.json.name));

console.log("\n13_extract_companies -- regressions from the live run");
REAL.forEach((r) => {
  check("rejects \"" + r.wrong + "\" (" + r.why + ")", !realNames.has(r.wrong));
  if (r.right) {
    check("  ...but still finds " + r.right, realNames.has(r.right));
  }
});
check("prefers the longest match over its own prefix",
  !(realNames.has("Highlander Production") && realNames.has("Highlander Production Company")),
  "one headline yielded both on the live run, which would create two entities "
  + "for one company");

// ---- 04 Summarize (shared) -------------------------------------------------
const summary = wrap("04_summarize_source_run.js")(inputOf(rows), ctxOf(store));
console.log("\n04_summarize_source_run (shared node)");
check("one source_runs row", summary.length === 1);
check("reads source from the items rather than hardcoding youtube_api",
  summary[0].json.source === "google_news_rss");
check("counts the rows produced", summary[0].json.candidates_found === rows.length);
check("carries segment_id", summary[0].json.segment_id === SEGMENT_ID);

console.log("\n" + (fail === 0
  ? "GREEN -- " + pass + " checks passed."
  : "FAILED -- " + fail + " of " + (pass + fail) + " checks failed."));
console.log("\nExtracted " + rows.length + " companies from " + parsed.length + " headlines:");
rows.forEach((r) => console.log("  - " + r.json.name.padEnd(24)
  + " ip_experience=" + (r.json.raw.scoring_inputs.international_ip_experience ?? "(absent)")
  + " distribution=" + (r.json.raw.scoring_inputs.distribution_relationship ?? "(absent)")
  + "  via: " + ([].concat(r.json.raw.ip_format_phrases, r.json.raw.distribution_phrases)
                   .join(", ") || "no deal language")));

process.exit(fail === 0 ? 0 : 1);
