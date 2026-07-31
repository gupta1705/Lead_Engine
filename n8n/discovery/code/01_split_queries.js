// Node: Split Queries  |  Mode: Run Once for All Items
// Runs right after the Postgres "Load Config" node.
// Input: 1 item —
//   { queries: [ { query, genre_hint }, ... ], segment_id: "<uuid>" }
// Output: one item per discovery query, each carrying segment_id
// forward so every later item can reach it without a lookup.

const row = $input.first().json;
const queries = row.queries || [];
const segmentId = row.segment_id;

return queries.map(q => ({
  json: {
    query: q.query,
    genre_hint: q.genre_hint !== undefined ? q.genre_hint : null,
    segment_id: segmentId
  }
}));
