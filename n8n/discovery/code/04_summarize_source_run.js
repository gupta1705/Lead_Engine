// Node: Summarize For Source Run  |  Mode: Run Once for All Items
// This node is a PARALLEL branch off "Filter, Score, and Shape for
// Staging" - it reads the same admitted-candidate items that also flow
// to the staging_candidates insert, and collapses them into one summary
// row for source_runs. It does not run after that insert; it runs
// alongside it, on the same input.

// SHARED BY EVERY CONNECTOR (2026-08-24). `source` is read off the incoming
// items rather than hardcoded, so the same node serves YouTube, News RSS,
// X-intent, Wikidata and AICP without five near-identical copies drifting
// apart. Each connector's shaping node already stamps `source` on every row.
const items = $input.all();
const first = items.length > 0 ? items[0].json : {};
const segmentId = first.segment_id || null;
const source = first.source || 'unknown';

return [{
  json: {
    segment_id: segmentId,
    source: source,
    candidates_found: items.length,
    candidates_new: items.length, // dedupe against EXISTING entities happens later, at the promote step (P9)
    status: 'succeeded'
  }
}];
