// Node: Split News Queries  |  Mode: Run Once for All Items
// Runs right after the Postgres "Load Config" node.
// Input: 1 item — { queries: [ { query, deal_kind }, ... ], segment_id }
// Output: one item per query, each carrying a ready-built Google News RSS URL
// plus the context every later node needs.
//
// Google News exposes its search as an RSS feed, which is why this source
// costs nothing and needs no API key: no quota, no credential, no signup.
//   https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en
// hl/gl/ceid pin the edition to US English. Unlike YouTube's regionCode -- which
// biases by VIEWER region and let 54 non-US channels through at P4 -- these
// select which Google News edition is searched, so US trade press dominates.
// It is still a bias, not a filter: a non-US company can appear in US trade
// press, and should. The us_geography gate is what actually decides.

const row = $input.first().json;
const queries = row.queries || [];
const segmentId = row.segment_id;

const BASE = 'https://news.google.com/rss/search';

return queries.map(q => ({
  json: {
    query: q.query,
    deal_kind: q.deal_kind !== undefined ? q.deal_kind : null,
    segment_id: segmentId,
    feed_url: `${BASE}?q=${encodeURIComponent(q.query)}&hl=en-US&gl=US&ceid=US:en`
  }
}));
