// Node: Filter And Extract Intent Signals  |  Mode: Run Once for All Items
// Runs after "Parse News Feed" (shared with the News RSS connector), which has
// already turned each feed response into one item per article/post carrying its
// own query context.
//
// WHAT THIS SOURCE IS FOR. Every other connector can prove at most one or two
// rubric criteria. This one targets `collaboration_openness` (15 points), which
// nothing else sets: a company that publicly says it is open to co-productions
// or looking for partners is telling you the thing the rubric wants to know.
//
// WHY IT NEEDS A RELEVANCE FILTER, AND WHY THAT IS NOT OPTIONAL. "Co-production"
// is a term of art in UK adult social care and public-service design, and that
// usage dominates the feed. A live probe of `site:x.com "co-production"`
// returned, in order: a Swansea co-production network, an adult social care
// conference, a Nigeria-China film partnership, and a co-production week
// newsletter. One of four was about screen. Without an industry gate this
// connector fills staging with local-government engagement work.
//
// The plan predicted this: "Noisy by design -- needs a basic relevance filter
// node before landing in staging."

// At least one of these must appear, or the item is not about screen at all.
const INDUSTRY_WORDS = [
  'film', 'films', 'tv', 'television', 'series', 'drama', 'comedy', 'sitcom',
  'documentary', 'doc', 'feature', 'streamer', 'streaming', 'studio', 'studios',
  'screen', 'broadcaster', 'network', 'showrunner', 'pilot', 'season',
  'production company', 'producer', 'producers', 'cinema', 'animation',
  'format', 'scripted', 'unscripted'
];

// Any of these and the item is discarded outright, however screen-ish it looks.
// Each was written against a real false positive from the live probe.
const OFF_DOMAIN = [
  'social care', 'adult care', 'healthcare', 'health care', 'nhs', 'patient',
  'council', 'local authority', 'public services', 'community engagement',
  'service users', 'lived experience', 'co-production week', 'wellbeing',
  'housing', 'charity', 'school', 'university', 'curriculum', 'energy',
  'apparel', 'biotech', 'pharma', 'oil', 'mining', 'agriculture'
];

// Explicit invitations. These are the actual evidence for the criterion --
// a company saying, in its own words, that it wants partners.
const INVITATION_PHRASES = [
  'open to co-production', 'open to co-productions', 'open for co-production',
  'looking for partners', 'looking for a partner', 'seeking partners',
  'seeking a production partner', 'seeking co-production',
  'accepting submissions', 'open for submissions', 'pitch us',
  'work with us', 'collaborate with us', 'partner with us',
  'looking to collaborate', 'open to collaboration'
];

const COMPANY_SUFFIX = [
  'Media', 'Studio', 'Studios', 'Pictures', 'Films', 'Film',
  'Productions', 'Production', 'Entertainment', 'Television',
  'Company', 'Group', 'Network', 'Works', 'Collective'
];

const NOT_A_LEAD = [
  'netflix', 'amazon', 'prime video', 'apple', 'disney', 'hulu', 'hbo', 'max',
  'warner', 'paramount', 'peacock', 'nbc', 'abc', 'cbs', 'fox', 'sony',
  'lionsgate', 'mgm', 'a24', 'bbc', 'itv', 'channel 4', 'sky', 'starz',
  'showtime', 'amc', 'discovery', 'universal', 'variety', 'deadline',
  'hollywood reporter', 'screen daily', 'c21media', 'broadcast', 'x.com',
  'twitter', 'google news', 'yahoo', 'msn'
];

const STOP_WORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'by',
  'with', 'from', 'its', 'our', 'we', 'us', 'their', 'new', 'first', 'next',
  'is', 'are', 'was', 'were', 'be', 'been', 'this', 'that', 'these', 'those',
  'open', 'looking', 'seeking', 'accepting', 'announces', 'announced', 'joins',
  'series', 'season', 'show', 'drama', 'comedy', 'film', 'movie', 'documentary',
  'partner', 'partners', 'partnership', 'submission', 'submissions', 'pitch',
  'exclusive', 'report', 'week', 'network', 'conference'
]);

const ORIGIN_WORDS = new Set([
  'korean', 'belgian', 'indian', 'spanish', 'israeli', 'german', 'japanese',
  'french', 'turkish', 'italian', 'dutch', 'danish', 'swedish', 'norwegian',
  'polish', 'russian', 'chinese', 'brazilian', 'mexican', 'australian',
  'british', 'irish', 'welsh', 'scottish', 'canadian', 'american', 'nigerian',
  'nordic', 'european', 'african', 'asian', 'original', 'foreign', 'international'
]);

const GENERIC_WORDS = new Set([
  'film', 'films', 'tv', 'television', 'works', 'company', 'production',
  'productions', 'studio', 'studios', 'media', 'group', 'network',
  'entertainment', 'pictures', 'collective', 'content', 'video', 'digital',
  'new', 'big', 'little', 'good', 'great', 'best', 'co'
]);

function hasAny(text, list) {
  const t = text.toLowerCase();
  return list.filter(w => t.includes(w));
}

function isExcluded(name) {
  const n = name.toLowerCase();
  return NOT_A_LEAD.some(x => n === x || n.startsWith(x + ' ') || n.endsWith(' ' + x));
}

// Same backwards walk the News RSS extractor uses, and for the same reason:
// a wrong name here becomes a cold email to a stranger. n8n Code nodes cannot
// import shared modules, so this is duplicated deliberately -- the fixtures
// cover both copies.
function extractCompanies(text) {
  if (!text) return [];
  const tokens = text.split(/\s+/).filter(Boolean);
  const suffixSet = new Set(COMPANY_SUFFIX.map(s => s.toLowerCase()));
  const out = [];
  for (let i = 0; i < tokens.length; i++) {
    const bare = tokens[i].replace(/[^A-Za-z0-9'’&.-]+$/, '');
    if (!suffixSet.has(bare.toLowerCase())) continue;
    if (!/^[A-Z]/.test(bare)) continue;
    const parts = [bare];
    for (let j = i - 1; j >= 0 && parts.length < 4; j--) {
      const w = tokens[j].replace(/[^A-Za-z0-9'’&.-]+$/, '');
      if (!w) break;
      if (STOP_WORDS.has(w.toLowerCase())) break;
      if (!/^[A-Z0-9]/.test(w)) break;
      if (/['’]s$/.test(w)) break;
      parts.unshift(w);
    }
    if (parts.length < 2) continue;
    const lower = parts.map(p => p.toLowerCase().replace(/['’]s$/, ''));
    if (lower.some(w => ORIGIN_WORDS.has(w))) continue;
    if (lower.every(w => GENERIC_WORDS.has(w))) continue;
    const name = parts.join(' ');
    if (isExcluded(name)) continue;
    if (!out.includes(name)) out.push(name);
  }
  return out.filter(n => !out.some(o => o !== n && o.startsWith(n + ' ')));
}

const feedItems = $input.all();
const seen = new Set();
const output = [];
let droppedOffDomain = 0, droppedNoIndustry = 0, droppedNoName = 0, droppedNoInvite = 0;

feedItems.forEach((item) => {
  const j = item.json || {};
  const title = j.title || '';
  const body = (title + ' ' + (j.description || '')).trim();
  if (!body) return;

  // 1. hard reject anything from another sector
  const off = hasAny(body, OFF_DOMAIN);
  if (off.length > 0) { droppedOffDomain++; return; }

  // 2. require positive screen-industry evidence
  const industry = hasAny(body, INDUSTRY_WORDS);
  if (industry.length === 0) { droppedNoIndustry++; return; }

  // 3. require an actual invitation. Without one there is no signal here that
  //    the News RSS connector does not already carry better.
  const invitations = hasAny(body, INVITATION_PHRASES);
  if (invitations.length === 0) { droppedNoInvite++; return; }

  const companies = extractCompanies(title);
  if (companies.length === 0) { droppedNoName++; return; }

  companies.forEach((name) => {
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);

    output.push({
      json: {
        segment_id: j.segment_id || null,
        name: name,
        domain: null,
        source: 'x_intent_signals',
        source_url: j.link || null,
        raw: {
          post_text: title,
          summary: (j.description || '').slice(0, 400),
          published_at: j.pubDate || null,
          matched_query: j.matched_query || null,
          intent_kind: j.deal_kind || null,
          invitation_phrases: invitations,
          industry_words: industry.slice(0, 6),
          scoring_inputs: {
            // The criterion this source exists for. Full credit: the config
            // guidance gives full points for "an explicit collaboration or
            // partnership invitation on their own site", and a public post
            // saying it in the company's own words is the same claim.
            collaboration_openness: 1,
            has_reachable_presence: true
          }
        }
      }
    });
  });
});

// Rejection counts travel with the run so the noise level is measurable rather
// than a guess. If droppedOffDomain dwarfs the output, the queries need work --
// which is a config edit, not a code change.
if (output.length > 0) {
  output[0].json.raw.filter_stats = {
    seen: feedItems.length,
    dropped_off_domain: droppedOffDomain,
    dropped_no_industry_words: droppedNoIndustry,
    dropped_no_invitation: droppedNoInvite,
    dropped_no_company_name: droppedNoName,
    admitted: output.length
  };
}

return output;
