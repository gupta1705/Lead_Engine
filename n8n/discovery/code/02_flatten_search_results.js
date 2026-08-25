// Node: Flatten Search Results  |  Mode: Run Once for All Items
// Runs after the HTTP Request node that calls YouTube search.list once
// per item from "Split Queries".
//
// Input: one item PER QUERY, each holding a raw search.list response
// (up to 25 channels nested in .items[]).
//
// IMPORTANT ASSUMPTION: this zips search responses to their original
// query by ARRAY INDEX against $('Split Queries').all(). n8n runs the
// HTTP Request node once per input item, in the same order, so this
// pairing is reliable as long as no node in between reorders or drops
// items. This is the part most likely to need a look if results come
// back attached to the wrong query on first real test.
//
// Output: one item per unique channel (deduped within this run),
// carrying the query context forward.

const queryItems = $('Split Queries').all();
const searchResponses = $input.all();

const seen = new Set();
const output = [];

searchResponses.forEach((resp, idx) => {
  const ctx = queryItems[idx] ? queryItems[idx].json : {};
  const channels = (resp.json && resp.json.items) || [];

  for (const ch of channels) {
    const channelId = ch.id && ch.id.channelId;
    if (!channelId || seen.has(channelId)) continue;
    seen.add(channelId);

    output.push({
      json: {
        channel_id: channelId,
        matched_query: ctx.query || null,
        genre_hint: ctx.genre_hint !== undefined ? ctx.genre_hint : null,
        segment_id: ctx.segment_id || null
      }
    });
  }
});

return output;
