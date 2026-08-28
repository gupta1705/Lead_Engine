// Node: Extract Companies From Headlines  |  Mode: Run Once for All Items
// Runs after the RSS Read node, which is executed once per query item from
// "Split News Queries" and returns parsed feed items.
//
// THIS IS THE HARD NODE. A headline is prose, not a record. Turning
//   "Netflix Orders Comedy Series From Lantern Row Media"
// into a lead means answering two separate questions, and conflating them is
// how this connector would go wrong:
//
//   1. WHICH company is this about?   -> name extraction
//   2. Is there real evidence of an   -> international_ip_experience
//      IP/format deal?
//
// The second is worth 30 points, the heaviest criterion in the rubric. The
// lesson from P4 applies directly: `genre_fit` awarded a full 15/15 to every
// channel a genre-flavoured QUERY surfaced, which credited companies for the
// search string rather than for anything about them. So:
//
//   **The query is never the evidence. The headline text is.**
//
// A row scores international_ip_experience = 1 only when a deal phrase appears
// in the headline or summary itself. Matching the query alone earns nothing --
// the article is merely how we found them.
//
// PRECISION OVER RECALL, deliberately. Name extraction only accepts a
// capitalised phrase ending in a company suffix (Media / Studios / Pictures /
// Films / Productions / Entertainment / Television). "Lantern Row Media" is
// admitted; a bare "Lantern Row" is not. That throws away real companies, and
// it is the right trade: a wrong name in staging becomes a wrong company in
// the review queue, and eventually a cold email to a stranger. A missed one
// costs nothing but a lead we never knew about.

// Suffixes that mark the end of a company name.
const COMPANY_SUFFIX = [
  'Media', 'Studio', 'Studios', 'Pictures', 'Films', 'Film',
  'Productions', 'Production', 'Entertainment', 'Television', 'TV',
  'Company', 'Group', 'Network', 'Works', 'House', 'Collective'
];

// Buyers, platforms and trade outlets. These appear in almost every deal
// headline and are never the lead -- we want the shop that MADE the thing,
// not the streamer that bought it or the magazine that reported it.
const NOT_A_LEAD = [
  'netflix', 'amazon', 'prime video', 'apple', 'apple tv', 'disney', 'hulu',
  'hbo', 'max', 'warner', 'paramount', 'peacock', 'nbc', 'nbcuniversal', 'abc',
  'cbs', 'fox', 'sony', 'lionsgate', 'mgm', 'a24', 'bbc', 'itv', 'channel 4',
  'sky', 'canal+', 'zdf', 'rai', 'globo', 'roku', 'tubi', 'starz', 'showtime',
  'amc', 'fx', 'discovery', 'universal', 'columbia', 'miramax', 'legendary',
  'variety', 'deadline', 'hollywood reporter', 'thr', 'screen daily',
  'c21media', 'broadcast', 'televisual', 'realscreen', 'worldscreen',
  'yahoo', 'msn', 'google news'
];

// Deal language, split by WHAT IT ACTUALLY PROVES. Lumping these together was
// this connector's first bug: "Netflix Orders Comedy Series From Tandem
// Pictures" earned the 30-point international_ip_experience on the strength of
// "series order". A domestic commission proves a company can get a show made
// and placed. It says nothing about adapting foreign IP -- which is the single
// criterion this whole source exists to supply. Same error as P4's genre_fit,
// one rung later.

// Terms of art for cross-border IP work. These are what the 30 points are for.
// EXTENDED 2026-08-28 with the vocabulary the query probe surfaced: "US remake"
// / "American remake" headlines carried IP language at 78% but several used
// only those exact phrases, which this list did not yet recognise -- so the
// query would have found the article and the extractor would have scored it
// zero. Query vocabulary and evidence vocabulary must move together.
const IP_FORMAT_PHRASES = [
  'format rights', 'format deal', 'formats deal', 'adaptation rights',
  'remake rights', 'english-language remake', 'english language remake',
  'english-language adaptation', 'english-language version',
  'local adaptation', 'local version', 'international co-production',
  'us remake', 'american remake', 'american adaptation', 'acquires format',
  'co-production', 'coproduction', 'co-produce', 'coproduce', 'co-producing'
];

// Evidence a company has a live route to market. Real, and worth the
// 20-point distribution_relationship -- but a different claim entirely.
const DISTRIBUTION_PHRASES = [
  'first-look deal', 'output deal', 'series order', 'straight-to-series',
  'greenlights', 'greenlit', 'commissions', 'commissioned'
];

// Genuinely ambiguous: "acquires the rights" could be a Korean format or a
// domestic novel, and a headline rarely says which. Recorded in `raw` so a
// reviewer can look, but it earns NOTHING automatically. Guessing here is how
// a 30-point criterion gets awarded on a coin flip.
const AMBIGUOUS_PHRASES = [
  'options the rights', 'optioned the rights', 'acquires the rights',
  'acquired the rights', 'adapt the', 'adapting the'
];

function stripPublisher(title) {
  // Google News titles read "Headline text - Publisher Name".
  const idx = title.lastIndexOf(' - ');
  if (idx === -1) return { headline: title, publisher: null };
  return {
    headline: title.slice(0, idx).trim(),
    publisher: title.slice(idx + 3).trim()
  };
}

function stripHtml(s) {
  return (s || '').replace(/<[^>]*>/g, ' ').replace(/&[a-z]+;/gi, ' ')
                  .replace(/\s+/g, ' ').trim();
}

function isExcluded(name) {
  const n = name.toLowerCase();
  return NOT_A_LEAD.some(x => n === x || n.startsWith(x + ' ') || n.endsWith(' ' + x));
}

// Headline vocabulary that can never be part of a company name. Without this
// a greedy match reads "Netflix Orders Comedy Series From Tandem Pictures" as
// the company "Series From Tandem Pictures" -- capitalised, suffix-terminated,
// and completely wrong.
const STOP_WORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'by',
  'with', 'from', 'its', 'his', 'her', 'their', 'new', 'first', 'next',
  'orders', 'order', 'sets', 'set', 'acquires', 'acquire', 'acquired',
  'names', 'named', 'adds', 'adding', 'announces', 'announced', 'launches',
  'launched', 'signs', 'signed', 'joins', 'joined', 'taps', 'tapped',
  'hires', 'hired', 'inks', 'inked', 'options', 'optioned', 'boards',
  'lands', 'landed', 'picks', 'picked', 'buys', 'bought', 'plans', 'planned',
  'reveals', 'revealed', 'unveils', 'brings', 'takes', 'gets', 'wins',
  'series', 'season', 'show', 'drama', 'comedy', 'film', 'movie', 'documentary',
  'deal', 'rights', 'format', 'formats', 'adaptation', 'remake', 'co-production',
  'exclusive', 'report', 'acquisition', 'partnership', 'slate', 'project',
]);

// Origin adjectives. Trade headlines describe SOURCE MATERIAL with exactly the
// grammar of a company name -- "Korean Film", "Belgian Hit TV", "Indian Action
// Film". All three came out of the first live run as leads. A nationality word
// anywhere in a candidate name means the phrase is describing what is being
// adapted, not who is adapting it.
const ORIGIN_WORDS = new Set([
  'korean', 'belgian', 'indian', 'farsi', 'spanish', 'israeli', 'german',
  'japanese', 'french', 'turkish', 'italian', 'dutch', 'danish', 'swedish',
  'norwegian', 'finnish', 'polish', 'russian', 'chinese', 'thai', 'brazilian',
  'mexican', 'argentine', 'australian', 'british', 'irish', 'scottish',
  'welsh', 'canadian', 'american', 'nordic', 'latin', 'asian', 'european',
  'african', 'arabic', 'hebrew', 'mandarin', 'cantonese', 'ukrainian',
  'original', 'foreign', 'international', 'domestic'
]);

// Words too generic to identify anyone on their own. A name made ENTIRELY of
// these is a category, not a company: "Audiovisual Works", "Tiny House".
const GENERIC_WORDS = new Set([
  'film', 'films', 'tv', 'television', 'works', 'house', 'company', 'production',
  'productions', 'studio', 'studios', 'media', 'group', 'network', 'entertainment',
  'pictures', 'collective', 'audiovisual', 'content', 'video', 'digital', 'new',
  'hit', 'tiny', 'big', 'little', 'good', 'great', 'best'
]);

// Walk BACKWARDS from each company suffix, collecting capitalised words until
// something that cannot belong to a name. More restrictive than a regex, and
// restrictive is what this needs to be: a wrong name here becomes a wrong
// company in the review queue and eventually a cold email to a stranger.
//
// The rejection rules below are not speculative -- each one was written against
// a specific wrong name the first live run produced from 119 real headlines.
function extractCompanies(text) {
  if (!text) return [];
  const tokens = text.split(/\s+/).filter(Boolean);
  const suffixSet = new Set(COMPANY_SUFFIX.map(s => s.toLowerCase()));
  const out = [];

  for (let i = 0; i < tokens.length; i++) {
    // Exact token match only. "Co-Production" must not read as the suffix
    // "Production", and "Studios," keeps its comma out of the name.
    const bare = tokens[i].replace(/[^A-Za-z0-9'’&.-]+$/, '');
    if (!suffixSet.has(bare.toLowerCase())) continue;

    // The suffix itself must be capitalised. Catches "Reese Witherspoon's
    // production company" and "English-language remake of Indian film", where
    // the word is ordinary prose rather than part of a proper noun.
    if (!/^[A-Z]/.test(bare)) continue;

    const parts = [bare];
    for (let j = i - 1; j >= 0 && parts.length < 4; j--) {
      const w = tokens[j].replace(/[^A-Za-z0-9'’&.-]+$/, '');
      if (!w) break;
      if (STOP_WORDS.has(w.toLowerCase())) break;      // headline verb/preposition
      if (!/^[A-Z0-9]/.test(w)) break;                  // lowercase = sentence prose
      if (/['’]s$/.test(w)) break;                      // "Sol Kyung Gu's Film"
      parts.unshift(w);
    }

    // A bare suffix on its own ("Studios", "Media") is not a company name.
    if (parts.length < 2) continue;

    const lower = parts.map(p => p.toLowerCase().replace(/['’]s$/, ''));
    if (lower.some(w => ORIGIN_WORDS.has(w))) continue;   // describing the source
    if (lower.every(w => GENERIC_WORDS.has(w))) continue; // a category, not a name

    const name = parts.join(' ');
    if (isExcluded(name)) continue;
    if (!out.includes(name)) out.push(name);
  }

  // Prefer the longest match. "Highlander Production" and "Highlander
  // Production Company" both came back from one headline on the live run;
  // keeping the prefix would create two entities for one company.
  return out.filter(n => !out.some(o => o !== n && o.startsWith(n + ' ')));
}

function matchPhrases(text, list) {
  const t = (text || '').toLowerCase();
  return list.filter(p => t.includes(p));
}

const feedItems = $input.all();

const seen = new Set();
const output = [];

feedItems.forEach((item) => {
  const j = item.json || {};

  // Query context arrives ON the item from "Parse News Feed" -- no pairedItem
  // lookup, no index arithmetic. The first version reconstructed it from
  // item.pairedItem and lost every row past index 5 on the live run, because
  // that field enumerates output items rather than query inputs.
  const ctx = j;

  const rawTitle = j.title || '';
  const { headline, publisher } = stripPublisher(rawTitle);
  const summary = stripHtml(j.description || j.contentSnippet || j.content || '');
  const evidenceText = headline + ' ' + summary;

  const companies = extractCompanies(headline);
  if (companies.length === 0) return;          // nothing nameable -- drop

  const ipPhrases = matchPhrases(evidenceText, IP_FORMAT_PHRASES);
  const distPhrases = matchPhrases(evidenceText, DISTRIBUTION_PHRASES);
  const ambiguous = matchPhrases(evidenceText, AMBIGUOUS_PHRASES);

  companies.forEach((name) => {
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);

    const scoringInputs = {};

    // THE 30-POINT DECISION. Only cross-border IP language earns it, and only
    // from the headline/summary text -- never from the query that found it.
    if (ipPhrases.length > 0) {
      scoringInputs.international_ip_experience = 1;
    }

    // A separate, weaker claim: this company gets shows commissioned and
    // placed. Worth 20 points on its own criterion, and not a substitute
    // for the one above.
    if (distPhrases.length > 0) {
      scoringInputs.distribution_relationship = 1;
    }

    // A company named in US trade press has a public presence by definition.
    scoringInputs.has_reachable_presence = true;

    // Everything else this connector genuinely cannot see -- geography,
    // headcount, genre, ownership -- is left ABSENT, not guessed. 04b turns
    // absent into an explicit 0 before scoring, and records it as unverified
    // so a reviewer can tell a default from a finding.

    output.push({
      json: {
        segment_id: ctx.segment_id,
        name: name,
        domain: null,               // filled at enrichment (P16), like AICP rows
        source: 'google_news_rss',
        source_url: j.link || null,
        raw: {
          headline: headline,
          publisher: publisher,
          summary: summary.slice(0, 500),
          published_at: j.pubDate || j.isoDate || null,
          matched_query: ctx.matched_query || null,
          query_deal_kind: ctx.deal_kind || null,
          ip_format_phrases: ipPhrases,
          distribution_phrases: distPhrases,
          ambiguous_phrases: ambiguous,
          all_companies_in_headline: companies,
          scoring_inputs: scoringInputs
        }
      }
    });
  });
});

return output;
