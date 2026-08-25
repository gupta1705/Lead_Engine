// Node: Parse AICP Directory  |  Mode: Run Once for All Items
// Runs after the HTTP Request node that fetches the AICP General Member
// Directory page as text.
//
// COMPLIANCE, CHECKED BEFORE A LINE OF THIS WAS WRITTEN.
//   robots.txt   https://www.aicp.com/robots.txt reads "User-agent: * /
//                Disallow:" -- an empty Disallow permits everything.
//   first-party  The directory is AICP's own public page, served as static
//                HTML. Verified live: 1.13MB of server-rendered markup with
//                member names in it, not a JavaScript shell.
//   scope        NAMES ONLY, for internal use. AICP's terms are
//                reference-only: no bulk republishing. Names enter our own
//                enrichment pipeline and go no further. That is why this
//                connector deliberately does not lift addresses, contacts or
//                anything else the page happens to show.
//   politeness   One request per run, and the run is monthly-ish. This is not
//                a crawl.
//
// WHAT IT CAN SET: essentially nothing beyond the name. No domain (the listing
// does not link out), no geography, no size. `has_reachable_presence` is NOT
// set either -- AICP membership is not a first-party presence we have
// verified, and asserting it would be exactly the kind of free-points
// inflation this project has already had to unwind twice.
//
// So an AICP row arrives as a bare name, scores near zero, and stays that way
// until enrichment finds it a domain at P16. That is the intended shape of
// this source, not a defect: it is a NAME LIST of real commercial production
// companies, and the value is in the names being real.

const MARKUP = /<h4[^>]*class="[^"]*font-semiBold[^"]*"[^>]*>([\s\S]*?)<\/h4>\s*<p[^>]*>([\s\S]*?)<\/p>/g;

// Member types that are production companies. AICP also lists associate
// members -- insurers, equipment houses, payroll firms, post facilities --
// which are vendors to the industry, not IP-owning producers, and the review
// checklist explicitly rules them out.
const ADMIT_TYPES = ['production company', 'production companies'];

function clean(s) {
  return (s || '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, d) => String.fromCharCode(parseInt(d, 10)))
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

const resp = $input.first().json;
const html = typeof resp === 'string' ? resp
           : (resp.data || resp.body || resp.text || '');

const segmentId = $('Load Config').first().json.segment_id;

const seen = new Set();
const output = [];
let skippedType = 0;

if (typeof html === 'string' && html.length > 0) {
  let m;
  while ((m = MARKUP.exec(html)) !== null) {
    const name = clean(m[1]);
    const memberType = clean(m[2]).toLowerCase();

    if (!name || name.length < 2) continue;
    if (!ADMIT_TYPES.some(t => memberType.includes(t))) { skippedType++; continue; }

    const key = name.toLowerCase();
    if (seen.has(key)) continue;   // the page repeats members across regions
    seen.add(key);

    output.push({
      json: {
        segment_id: segmentId,
        name: name,
        domain: null,          // filled at enrichment (P16), by design
        source: 'aicp_directory',
        source_url: 'https://www.aicp.com/membership-information/member-directory/general-member-directory',
        raw: {
          member_type: memberType,
          // No scoring inputs. This source knows a name and nothing else, and
          // saying so plainly is worth more than a manufactured signal.
          scoring_inputs: {}
        }
      }
    });
  }
}

if (output.length > 0) {
  output[0].json.raw.parse_stats = {
    admitted: output.length,
    skipped_non_production_member_types: skippedType
  };
}

return output;
