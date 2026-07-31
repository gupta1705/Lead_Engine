// Node: Summarize For Source Run  |  Mode: Run Once for All Items
// This node is a PARALLEL branch off "Filter, Score, and Shape for
// Staging" - it reads the same admitted-candidate items that also flow
// to the staging_candidates insert, and collapses them into one summary
// row for source_runs. It does not run after that insert; it runs
// alongside it, on the same input.

const items = $input.all();
const segmentId = items.length > 0 ? items[0].json.segment_id : null;

return [{
  json: {
    segment_id: segmentId,
    source: 'youtube_api',
    candidates_found: items.length,
    candidates_new: items.length, // dedupe against EXISTING entities happens later, at Run A's promote step (S4)
    status: 'succeeded'
  }
}];
