// Node: Filter, Score, and Shape for Staging  |  Mode: Run Once for All Items
// Runs after the HTTP Request node that calls YouTube channels.list once
// per item from "Flatten Search Results" (one channel_id per call — not
// batched into groups of 50, a deliberate v1 simplification: channels.list
// costs only 1 quota unit/call, so even ~150 individual calls is trivial
// against the 10,000/day budget, and skipping batching removes a whole
// layer of item-grouping logic that would otherwise be unverified until
// a live test run).
//
// THRESHOLDS BELOW ARE A STARTING POINT, NOT FINAL - tune them during
// S3.8's real-query test against actual results.
//
// KNOWN v1 SIMPLIFICATION: this connector does NOT set activity_signal
// (the is_active gate's input). A real "last upload" check needs a
// separate API call this script doesn't make. Leaving the key unset is
// SAFE by design - the gate treats unknown as pass-through - it just
// means the is_active gate won't actively catch anything yet from this
// connector; Layer B enrichment (which visits the real site) is a more
// natural place to add a fuller check later.

const ADMIT_KEYWORDS = ['studio', 'media', 'production', 'productions', 'network', 'films', 'pictures', 'entertainment'];
const SUBSCRIBER_FLOOR = 1000;
const OVERSIZED_SUBSCRIBER_CEILING = 5000000;
const KNOWN_MAJORS_KEYWORDS = [
  'disney', 'warner bros', 'nbcuniversal', 'paramount', 'sony pictures',
  'viacomcbs', 'mgm', 'lionsgate', 'netflix', 'amazon studios', 'hbo',
  'a24', 'universal pictures', '20th century'
];

function extractDomain(text) {
  if (!text) return null;
  const urlRegex = /https?:\/\/(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(?:\/[^\s]*)?/gi;
  const matches = [...text.matchAll(urlRegex)];
  const EXCLUDE = ['youtube.com', 'youtu.be', 'instagram.com', 'twitter.com', 'x.com',
                   'facebook.com', 'tiktok.com', 'linkedin.com', 'linktr.ee', 'bit.ly'];
  for (const m of matches) {
    const host = m[1].toLowerCase();
    if (!EXCLUDE.some(ex => host === ex || host.endsWith('.' + ex))) {
      return host;
    }
  }
  return null;
}

function extractEmail(text) {
  if (!text) return null;
  const emailRegex = /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i;
  const direct = text.match(emailRegex);
  if (direct) return direct[0].toLowerCase();
  const deobfuscated = text
    .replace(/\s*\[?\(?\s*at\s*\)?\]?\s*/gi, '@')
    .replace(/\s*\[?\(?\s*dot\s*\)?\]?\s*/gi, '.');
  const fallback = deobfuscated.match(emailRegex);
  return fallback ? fallback[0].toLowerCase() : null;
}

const channelItems = $('Flatten Search Results').all();
const detailResponses = $input.all();

const output = [];

detailResponses.forEach((resp, idx) => {
  const ctx = channelItems[idx] ? channelItems[idx].json : {};
  const channel = resp.json && resp.json.items && resp.json.items[0];
  if (!channel) return; // channels.list found nothing for this id - skip

  const snippet = channel.snippet || {};
  const stats = channel.statistics || {};
  const title = snippet.title || '';
  const description = snippet.description || '';
  const subscriberCount = stats.subscriberCount ? parseInt(stats.subscriberCount, 10) : null;
  const country = snippet.country || null;

  // --- ADMISSION FILTER: creators-vs-studios judgment ---
  const haystack = (title + ' ' + description).toLowerCase();
  const keywordHit = ADMIT_KEYWORDS.some(k => haystack.includes(k));
  const aboveFloor = subscriberCount !== null && subscriberCount >= SUBSCRIBER_FLOOR;
  if (!keywordHit && !aboveFloor) {
    return; // discarded - neither signal suggests a real studio
  }

  // --- scoring_inputs this connector can set (null-vs-zero rule: only
  // write a key when there's real evidence either way; leave it out
  // entirely if genuinely unassessed) ---
  const scoringInputs = {};

  if (ctx.genre_hint) {
    scoringInputs.genre_fit = 1;
  }

  if (country) {
    scoringInputs.geography_signal = country === 'US' ? 'us' : 'non_us';
  }

  const isKnownMajor = KNOWN_MAJORS_KEYWORDS.some(k => haystack.includes(k));
  const isOversized = subscriberCount !== null && subscriberCount >= OVERSIZED_SUBSCRIBER_CEILING;
  if (isKnownMajor || isOversized) {
    scoringInputs.major_or_oversized_signal = true;
  }

  scoringInputs.has_reachable_presence = true; // a channel is itself a presence - always confirmed true

  const domain = extractDomain(description);
  const email = extractEmail(description);

  output.push({
    json: {
      segment_id: ctx.segment_id,
      name: title,
      domain: domain,
      source: 'youtube_api',
      source_url: `https://www.youtube.com/channel/${ctx.channel_id}`,
      raw: {
        channel_id: ctx.channel_id,
        matched_query: ctx.matched_query,
        subscriber_count: subscriberCount,
        video_count: stats.videoCount ? parseInt(stats.videoCount, 10) : null,
        country: country,
        description: description,
        extracted_email: email,
        scoring_inputs: scoringInputs
      }
    }
  });
});

return output;
