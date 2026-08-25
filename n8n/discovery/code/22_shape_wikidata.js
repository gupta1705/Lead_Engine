// Node: Shape Wikidata Results  |  Mode: Run Once for All Items
// Runs after the HTTP Request node that calls the Wikidata query service.
// Input: 1 item holding a SPARQL JSON result set.
//
// WHAT THIS CONNECTOR CAN HONESTLY SET, AND WHAT IT CANNOT.
//
//   domain                     -- from P856. THE point of this source. Every
//                                 other connector leaves it null.
//   geography_signal = 'us'    -- the query itself filters on P17 = United
//                                 States, so this is a fact about the result
//                                 set, not a guess.
//   has_reachable_presence     -- it has a published website by construction.
//   activity_signal            -- 'confirmed_dormant' when P576 (dissolution
//                                 date) exists. 38 of the 363 carry one. No
//                                 other connector can supply this gate input,
//                                 and it is the difference between a live shop
//                                 and a company that closed in 2011.
//   major_or_oversized_signal  -- true when the company has a parent
//                                 organisation that is a known major, or its
//                                 own name matches one. Wikidata models
//                                 ownership properly (P749), so subsidiaries
//                                 are detectable here in a way they are not
//                                 from a YouTube channel title.
//
// NOT set: right_size, genre_fit, collaboration_openness,
// international_ip_experience. Wikidata knows a company exists and is notable;
// it does not know whether it makes comedy, wants a partner, or has six people.
// Only 14 of 363 even carry an employee count (P1128), so size is recorded as
// a note when present and left to enrichment otherwise.
//
// THE SIZE PROBLEM, STATED PLAINLY. Wikidata is notable-only, and notable
// skews large: the first page of results is Icon Productions, Relativity
// Media, Warner Independent. The rubric wants 2-20 people. Expect a low hit
// rate and lean on `major_or_oversized_signal` plus the P13 gate to clear the
// obvious misses -- this source earns its place by supplying DOMAINS, not by
// precision.

const KNOWN_MAJORS = [
  'disney', 'warner', 'nbcuniversal', 'universal', 'paramount', 'sony',
  'columbia', 'viacom', 'mgm', 'lionsgate', 'netflix', 'amazon', 'hbo', 'a24',
  '20th century', 'fox', 'dreamworks', 'pixar', 'marvel', 'lucasfilm',
  'miramax', 'legendary', 'blumhouse', 'skydance', 'apple', 'comcast'
];

function hostOf(url) {
  if (!url) return null;
  const m = String(url).match(/^[a-z][a-z0-9+.-]*:\/\/([^/?#]+)/i);
  if (!m) return null;
  return m[1].toLowerCase().replace(/^www\./, '') || null;
}

function isMajorName(s) {
  const t = (s || '').toLowerCase();
  return KNOWN_MAJORS.some(k => t.includes(k));
}

const resp = $input.first().json;
const body = (resp && resp.results && resp.results.bindings) ? resp
           : (resp && resp.data && resp.data.results ? resp.data : null);
const rows = body ? body.results.bindings : [];

// Wikidata returns one row per value combination, so a company with two
// inception statements appears twice. Collapse on the entity URI.
const byEntity = new Map();
for (const r of rows) {
  const uri = r.company && r.company.value;
  if (!uri) continue;
  if (!byEntity.has(uri)) byEntity.set(uri, r);
  else {
    // prefer the row that carries the most information
    const cur = byEntity.get(uri);
    if (Object.keys(r).length > Object.keys(cur).length) byEntity.set(uri, r);
  }
}

const segmentId = $('Build SPARQL Query').first().json.segment_id;
const output = [];

for (const [uri, r] of byEntity) {
  const name = r.companyLabel && r.companyLabel.value;
  // A label that is still a Q-number means the item has no English label --
  // an unusable name, and not worth a row.
  if (!name || /^Q\d+$/.test(name)) continue;

  const website = r.website && r.website.value;
  const domain = hostOf(website);
  if (!domain) continue;   // the whole point of this source

  const scoringInputs = {
    geography_signal: 'us',      // guaranteed by the P17 filter in the query
    has_reachable_presence: true // it has a published website by construction
  };

  const dissolved = r.dissolved && r.dissolved.value;
  if (dissolved) {
    scoringInputs.activity_signal = 'confirmed_dormant';
  }

  const parent = r.parentLabel && r.parentLabel.value;
  if (isMajorName(name) || (parent && isMajorName(parent))) {
    scoringInputs.major_or_oversized_signal = true;
  }

  const employees = r.employees && parseInt(r.employees.value, 10);
  if (Number.isFinite(employees) && employees > 50) {
    scoringInputs.major_or_oversized_signal = true;
  }

  output.push({
    json: {
      segment_id: segmentId,
      name: name,
      domain: domain,
      source: 'wikidata',
      source_url: uri,
      raw: {
        wikidata_uri: uri,
        website: website,
        inception: r.inception ? r.inception.value : null,
        dissolved: dissolved || null,
        parent_organisation: parent || null,
        employees: Number.isFinite(employees) ? employees : null,
        scoring_inputs: scoringInputs
      }
    }
  });
}

return output;
