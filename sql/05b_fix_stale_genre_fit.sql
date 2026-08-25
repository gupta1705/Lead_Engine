-- 05B_FIX_STALE_GENRE_FIT.SQL
-- One-time data correction, 2026-08-24. Not a pattern to repeat -- a repair.
--
-- WHAT HAPPENED. The YouTube connector originally awarded `genre_fit = 1`
-- (full marks, 15 points) to any channel a genre-flavoured search query
-- surfaced. That was corrected to 0.5 during P4 authoring, on the reasoning
-- that YouTube relevance-matching a channel to "workplace comedy channel" is
-- real but weak evidence -- the config guidance reserves full points for
-- "core focus" and half for "occasional", and nobody had looked at what these
-- studios actually make.
--
-- The fix went into `code/03_filter_score_shape.js`. It never reached
-- `conn_youtube_api.json`, which carries its own embedded copy of that script,
-- and n8n runs the JSON. So the live harvest was produced by the old code and
-- **74 of 123 YouTube entities carry genre_fit = 1 on evidence nobody has.**
--
-- The fixtures were green throughout, because they test the .js files.
-- `tools/sync_workflow_code.py` now rewrites the JSON from the .js files and
-- `verify_repo.py` fails when the two diverge, so this cannot recur silently.
--
-- WHY CORRECT RATHER THAN RE-HARVEST. A re-run would cost ~750 YouTube quota
-- units and return a slightly different set of channels, which would muddy the
-- per-source comparison Checkpoint 1 depends on. The value is wrong by a known
-- amount, from a known cause, on a known set of rows. Correcting it in place is
-- both cheaper and more precise.
--
-- SCOPE: youtube_api rows only, genre_fit = 1 only, and only rows nobody has
-- dispositioned. A shortlisted or rejected row reflects a human decision made
-- against what they saw; silently changing the numbers underneath it would
-- make the review record dishonest.

update entities
set metadata = jsonb_set(metadata,
                         '{scoring_inputs,genre_fit}',
                         to_jsonb(0.5))
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'youtube_api'
  and status in ('discovered', 'enriched', 'scored', 'ready_for_review')
  and metadata->'scoring_inputs'->>'genre_fit' = '1';

----------------------------------------------------------------------
-- CONFIRM: no un-dispositioned YouTube row should still read 1.
----------------------------------------------------------------------
select metadata->'scoring_inputs'->>'genre_fit' as genre_fit,
       count(*) as rows
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'youtube_api'
group by 1
order by 1;

-- Re-score after this: the affected rows each lose 7.5 raw points.
--   select * from score_segment('us-production-houses');
