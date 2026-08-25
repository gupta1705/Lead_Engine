// Node: Build SPARQL Query  |  Mode: Run Once for All Items
// Runs right after the Postgres "Load Config" node.
// Input: 1 item -- { wikidata: {entity_class, country, limit, ...}, segment_id }
// Output: 1 item carrying a ready-to-fetch Wikidata query-service URL.
//
// WHY THIS SOURCE IS WORTH A RUNG. Every other connector leaves `domain` null:
// a YouTube description rarely carries a website, and a news headline names a
// company without linking to it. Wikidata has P856 (official website) as a
// first-class property, so this is the one source that arrives WITH the domain
// already attached -- which is exactly what Apollo needs at P16 to match an
// organisation.
//
// A live probe found **363 US film/TV production companies with a website**.
// That is a seed, not a stream: Wikidata is notable-only, so the list changes
// slowly and this workflow is meant to be re-run occasionally, not weekly.
//
// CC0 licensed and free forever -- no key, no quota, no signup. The service
// does require a descriptive User-Agent, which the HTTP node sets.
//
// The entity class and country live in config so Segment 2 is a config row
// rather than a code change: swap Q1762059 (film production company) for
// whatever class that segment hunts.

const row = $input.first().json;
const cfg = row.wikidata || {};
const segmentId = row.segment_id;

const entityClass = cfg.entity_class || 'Q1762059';   // film production company
const country     = cfg.country      || 'Q30';        // United States
const limit       = cfg.limit        || 400;

// P31/P279* walks subclasses, so "film production company" also catches
// "television production company" and similar narrower classes.
// OPTIONALs are genuinely optional: a company missing an inception date should
// still be returned, not filtered out.
const sparql = `
SELECT DISTINCT ?company ?companyLabel ?website ?inception ?dissolved ?parentLabel ?employees WHERE {
  ?company wdt:P31/wdt:P279* wd:${entityClass} .
  ?company wdt:P17 wd:${country} .
  ?company wdt:P856 ?website .
  OPTIONAL { ?company wdt:P571  ?inception }
  OPTIONAL { ?company wdt:P576  ?dissolved }
  OPTIONAL { ?company wdt:P749  ?parent }
  OPTIONAL { ?company wdt:P1128 ?employees }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT ${limit}`.trim();

return [{
  json: {
    segment_id: segmentId,
    entity_class: entityClass,
    country: country,
    sparql: sparql,
    query_url: 'https://query.wikidata.org/sparql?format=json&query='
               + encodeURIComponent(sparql)
  }
}];
