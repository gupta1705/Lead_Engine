#!/usr/bin/env node
/**
 * run_seed_fixtures.js -- the two seed connectors: Wikidata (P7) and AICP (P8).
 *
 * Both fixtures use payloads shaped exactly like the live responses, captured
 * from real probes of the SPARQL endpoint and the AICP directory page.
 *
 * Usage:  node n8n/discovery/test/run_seed_fixtures.js
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
const ctxOf = (store) => (name) => ({ all: () => store[name] || [],
                                      first: () => (store[name] || [])[0] });
const inputOf = (arr) => ({ all: () => arr, first: () => arr[0] });

const cfg = JSON.parse(fs.readFileSync(CONFIG, "utf8"));
let pass = 0, fail = 0;
const check = (label, ok, detail) => {
  if (ok) { pass++; console.log("  PASS  " + label); }
  else { fail++; console.log("  FAIL  " + label + (detail ? "\n          " + detail : "")); }
};

console.log("seed connectors -- code-node fixtures\n");

// ============ P7 Wikidata ====================================================
const built = wrap("21_build_sparql.js")(
  inputOf(items([{ wikidata: cfg.wikidata_discovery, segment_id: SEGMENT_ID }])), null);

console.log("21_build_sparql");
check("emits one query item PER class -- the combined query timed out live",
  built.length === cfg.wikidata_discovery.entity_classes.length);
check("uses the configured entity class, not a hardcoded one",
  cfg.wikidata_discovery.entity_classes.every(
    (c) => built.some((b) => b.json.sparql.includes("wd:" + c))));
check("queries BOTH class trees -- film and TV are siblings, not parent/child",
  built.some((b) => b.json.sparql.includes("wd:Q1762059"))
  && built.some((b) => b.json.sparql.includes("wd:Q10689397")),
  "the single-class version silently missed 124 US TV production companies");
check("filters to the configured country",
  built.every((b) => b.json.sparql.includes("wdt:P17 wd:" + cfg.wikidata_discovery.country)));
check("requires an official website (P856) -- the reason this source exists",
  built[0].json.sparql.includes("wdt:P856"));
check("asks for dissolution date (P576), which no other connector can supply",
  built[0].json.sparql.includes("wdt:P576"));
check("builds a fetchable query-service URL",
  built[0].json.query_url.startsWith("https://query.wikidata.org/sparql?format=json&query="));
check("walks subclasses so TV production companies are included too",
  built[0].json.sparql.includes("wdt:P31/wdt:P279*"));

// SPARQL JSON exactly as the endpoint returns it
const b = (v) => ({ type: "literal", value: v });
const uri = (v) => ({ type: "uri", value: v });
const sparqlResponse = {
  results: { bindings: [
    { company: uri("http://www.wikidata.org/entity/Q1"), companyLabel: b("Lantern Row Media"),
      website: uri("https://www.lanternrowmedia.com/"), inception: b("2014-01-01T00:00:00Z") },
    // same entity, second inception statement -- Wikidata really does this
    { company: uri("http://www.wikidata.org/entity/Q1"), companyLabel: b("Lantern Row Media"),
      website: uri("https://www.lanternrowmedia.com/"), inception: b("2015-01-01T00:00:00Z") },
    { company: uri("http://www.wikidata.org/entity/Q2"), companyLabel: b("Closed Pictures"),
      website: uri("http://closedpictures.com"), dissolved: b("2011-06-01T00:00:00Z") },
    { company: uri("http://www.wikidata.org/entity/Q3"), companyLabel: b("Warner Independent Pictures"),
      website: uri("http://wip.warnerbros.com/") },
    { company: uri("http://www.wikidata.org/entity/Q4"), companyLabel: b("Subsidiary Films"),
      website: uri("http://subsidiaryfilms.com"), parentLabel: b("Paramount Pictures") },
    { company: uri("http://www.wikidata.org/entity/Q5"), companyLabel: b("Big Staff Studios"),
      website: uri("http://bigstaff.com"), employees: b("400") },
    { company: uri("http://www.wikidata.org/entity/Q6"), companyLabel: b("Q9999999"),
      website: uri("http://nolabel.com") },
    { company: uri("http://www.wikidata.org/entity/Q7"), companyLabel: b("No Website Co") },
    { company: uri("http://www.wikidata.org/entity/Q8"), companyLabel: b("Bad P856 Co"),
      website: uri("https://bloody-disgusting.com/") },
  ]}
};

const wdStore = { "Build SPARQL Query": built };
const wd = wrap("22_shape_wikidata.js")(inputOf(items([sparqlResponse])), ctxOf(wdStore));
const wdBy = {}; wd.forEach((r) => { wdBy[r.json.name] = r.json; });

console.log("\n22_shape_wikidata");
check("collapses duplicate rows for one entity into a single company",
  wd.filter((r) => r.json.name === "Lantern Row Media").length === 1,
  "Wikidata returns one row per value combination");
check("EXTRACTS THE DOMAIN -- the whole reason for this source",
  wdBy["Lantern Row Media"] && wdBy["Lantern Row Media"].domain === "lanternrowmedia.com");
check("strips www. and the scheme from the website",
  wdBy["Closed Pictures"] && wdBy["Closed Pictures"].domain === "closedpictures.com");
check("a dissolution date sets activity_signal = confirmed_dormant",
  wdBy["Closed Pictures"]
  && wdBy["Closed Pictures"].raw.scoring_inputs.activity_signal === "confirmed_dormant",
  "no other connector can supply this gate input");
check("a live company gets NO activity_signal rather than a guessed one",
  wdBy["Lantern Row Media"]
  && !("activity_signal" in wdBy["Lantern Row Media"].raw.scoring_inputs));
check("a major is flagged by its own name",
  wdBy["Warner Independent Pictures"]
  && wdBy["Warner Independent Pictures"].raw.scoring_inputs.major_or_oversized_signal === true);
check("a subsidiary is flagged by its PARENT (P749)",
  wdBy["Subsidiary Films"]
  && wdBy["Subsidiary Films"].raw.scoring_inputs.major_or_oversized_signal === true,
  "Wikidata models ownership, so subsidiaries are detectable here and nowhere else");
check("an employee count over 50 flags oversized",
  wdBy["Big Staff Studios"]
  && wdBy["Big Staff Studios"].raw.scoring_inputs.major_or_oversized_signal === true);
check("geography_signal = us, guaranteed by the P17 filter",
  wd.every((r) => r.json.raw.scoring_inputs.geography_signal === "us"));
check("an unlabelled item (bare Q-number) is dropped", !wdBy["Q9999999"]);
check("a company with no website is dropped", !wdBy["No Website Co"]);
check("a third-party P856 (news site, form service) is dropped, not adopted",
  !wdBy["Bad P856 Co"],
  "live regression: Wikidata lists bloody-disgusting.com as Platinum Dunes' site");
check("never guesses size, genre, collaboration or IP experience",
  wd.every((r) => {
    const si = r.json.raw.scoring_inputs;
    return !("right_size" in si) && !("genre_fit" in si)
        && !("collaboration_openness" in si)
        && !("international_ip_experience" in si);
  }),
  "Wikidata knows a company is notable, not what it makes or how big it is");
check("tagged source=wikidata", wd.every((r) => r.json.source === "wikidata"));
check("no scoring_inputs key the config does not define", (() => {
  const known = new Set([...cfg.rubric, ...cfg.score_modifiers, ...cfg.gates]
    .map((x) => x.input.split(".").pop()));
  return wd.every((r) =>
    Object.keys(r.json.raw.scoring_inputs).every((k) => known.has(k)));
})());

// ============ P8 AICP ========================================================
// Markup copied from the live page: an h4 with the name, then a member-type p.
const aicpHtml = `
<div class="member"><h4 class="font-semiBold">2M Productions</h4>
<p class="text-[16px]">Production Company</p></div>
<div class="member"><h4 class="font-semiBold">Lantern Row Media</h4>
<p class="text-[16px]">Production Company</p></div>
<div class="member"><h4 class="font-semiBold">2M Productions</h4>
<p class="text-[16px]">Production Company</p></div>
<div class="member"><h4 class="font-semiBold">Acme Payroll Services</h4>
<p class="text-[16px]">Associate Member - Payroll</p></div>
<div class="member"><h4 class="font-semiBold">Gotham Post &amp; Finishing</h4>
<p class="text-[16px]">Associate Member - Post Production</p></div>
<div class="member"><h4 class="font-semiBold">O&#39;Brien Films</h4>
<p class="text-[16px]">Production Company</p></div>
<div class="member"
><h4 class="font-semiBold">1Park9 --> response.json()) .then(data => { console.dir(data.data);</h4>
<p class="text-[16px]">Production Company</p></div>
<div class="member"><h4 class="font-semiBold">Belladonna</h4>
<p class="text-[16px]">Editorial Company</p></div>
<div class="member"><h4 class="font-semiBold">HB Collective</h4>
<p class="text-[16px]">Audio Post Production</p></div>
<div class="member"><h4 class="font-semiBold">Furlined</h4>
<p class="text-[16px]">VFX Studio</p></div>
<div class="member"><h4 class="font-semiBold">Alongside Global Inc</h4>
<p class="text-[16px]">Production and Post Production Company</p></div>`;

const aicpStore = { "Load Config": [{ json: { segment_id: SEGMENT_ID } }] };
const aicp = wrap("31_parse_aicp_directory.js")(
  inputOf(items([{ data: aicpHtml }])), ctxOf(aicpStore));
const aicpNames = aicp.map((r) => r.json.name);

console.log("\n31_parse_aicp_directory");
// REGRESSIONS FROM THE FIRST LIVE RUN (2026-08-27). The directory renders one
// Alpine.js handler per member inside an HTML ATTRIBUTE -- not a <script> tag,
// so stripping scripts never touched it -- and the fragment landed inside the
// captured <h4>. All 231 names came back as
//   "1Park9 --> response.json()) .then(data => { console.dir(data.data);"
check("strips the Alpine.js fragment out of a captured name",
  aicpNames.includes("1Park9"),
  "got: " + JSON.stringify(aicpNames.filter((n) => n.indexOf("1Park9") === 0)));
check("no name carries script residue",
  aicpNames.every((n) => !/console\.|=>|-->|response\.json/.test(n)));
// The member type filters better than any keyword match -- but note the trap it
// has to survive: "Post Production Company" CONTAINS "production company", so a
// naive rule rescues exactly the vendors it means to exclude.
check("rejects an editorial-only house", !aicpNames.includes("Belladonna"));
check("rejects an audio post house", !aicpNames.includes("HB Collective"));
check("rejects a VFX-only studio", !aicpNames.includes("Furlined"));
check("KEEPS a hybrid that also produces",
  aicpNames.includes("Alongside Global Inc"),
  '"Production and Post Production Company" makes content too -- excluding it '
  + "would throw away real candidates");
check("extracts member names from the real markup shape",
  aicpNames.includes("2M Productions") && aicpNames.includes("Lantern Row Media"));
check("dedupes a member repeated across regions",
  aicpNames.filter((n) => n === "2M Productions").length === 1);
check("EXCLUDES associate members -- vendors, not IP-owning producers",
  !aicpNames.includes("Acme Payroll Services")
  && !aicpNames.includes("Gotham Post & Finishing"),
  "the review checklist rules out service vendors explicitly");
check("decodes HTML entities in names",
  aicpNames.includes("O'Brien Films"));
check("domain left null -- the listing does not link out",
  aicp.every((r) => r.json.domain === null));
check("sets NO scoring inputs at all",
  aicp.every((r) => Object.keys(r.json.raw.scoring_inputs).length === 0),
  "a name is all this source knows; asserting has_reachable_presence would be "
  + "the free-points inflation this project has already unwound twice");
check("tagged source=aicp_directory",
  aicp.every((r) => r.json.source === "aicp_directory"));
check("carries segment_id", aicp.every((r) => r.json.segment_id === SEGMENT_ID));
// 5 skipped: two Associate Member tiers (payroll, post), plus the editorial,
// audio-post and VFX-only houses added as live-run regressions.
check("reports how many non-production members it skipped",
  aicp[0].json.raw.parse_stats.skipped_non_production_member_types === 5,
  "got " + aicp[0].json.raw.parse_stats.skipped_non_production_member_types);
check("empty response body does not crash", (() => {
  const empty = wrap("31_parse_aicp_directory.js")(
    inputOf(items([{ data: "" }])), ctxOf(aicpStore));
  return Array.isArray(empty) && empty.length === 0;
})());

// ============ shared summarize ==============================================
const s1 = wrap("04_summarize_source_run.js")(inputOf(wd), ctxOf(wdStore));
const s2 = wrap("04_summarize_source_run.js")(inputOf(aicp), ctxOf(aicpStore));
console.log("\n04_summarize_source_run (shared by both)");
check("wikidata run row", s1[0].json.source === "wikidata"
  && s1[0].json.candidates_found === wd.length);
check("aicp run row", s2[0].json.source === "aicp_directory"
  && s2[0].json.candidates_found === aicp.length);

console.log("\n" + (fail === 0
  ? "GREEN -- " + pass + " checks passed."
  : "FAILED -- " + fail + " of " + (pass + fail) + " checks failed."));
console.log("\nwikidata admitted " + wd.length + ":");
wd.forEach((r) => console.log("  - " + r.json.name.padEnd(30) + r.json.domain
  + "   " + JSON.stringify(r.json.raw.scoring_inputs)));
console.log("aicp admitted " + aicp.length + ": " + aicpNames.join(", "));

process.exit(fail === 0 ? 0 : 1);
