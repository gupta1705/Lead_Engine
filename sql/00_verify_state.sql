-- 00_VERIFY_STATE.SQL
-- P0 -- read-only diagnostic. Run this FIRST, in the Supabase SQL editor,
-- before anything else. It tells you which of the other scripts you
-- actually need to run.
--
-- UPDATED 2026-08-23: the database is being rebuilt from scratch on a NEW
-- Supabase account. On a fresh project the order is simply
--     01_schema.sql -> 02_smoke_test.sql -> 03_segment_us_production_houses.sql
-- and then this file, purely to CONFIRM the build landed. Query 2 should match
-- the v3 numbers on the first try, and 03b_sync_segment_config_v3.sql is NOT
-- run -- it only ever existed to patch the old, now-abandoned database.
-- The stale-row branch below is kept for the record; ignore it on a fresh build.
--
-- HOW TO READ THE RESULTS:
--   Query 1 errors with "relation does not exist"
--     -> schema isn't live yet. Run, in order: 01_schema.sql, then
--        02_smoke_test.sql, then 03_segment_us_production_houses.sql.
--        Stop here -- you're done with P0's DB side.
--   Query 1 succeeds but query 2 returns 0 rows
--     -> schema is live but the segment was never inserted. Run
--        03_segment_us_production_houses.sql only.
--   Query 2 returns 1 row: check rubric_criteria/gates/modifiers/checklist
--   against the expected counts below (v3, as of 2026-08-20):
--     rubric_criteria = 6, gates = 4, score_modifiers = 3, review_checklist = 3
--     genre_fit_points = 15, right_size_points = 20, revenue_penalty = -20
--     score_threshold_review = 25, score_threshold_priority = 60  (v4, 2026-08-23)
--   If genre_fit_points/right_size_points/revenue_penalty DON'T match
--     -> the live row has the old v2 numbers. Run 03b_sync_segment_config_v3.sql.
--   If everything matches
--     -> DB is current. Move straight to 04_insert_template.sql (P1).

-- Query 1: does the schema exist at all?
select table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in ('segments', 'entities', 'contacts', 'staging_candidates', 'source_runs')
order by table_name;
-- Expect 5 rows. Fewer (or an error) means the schema isn't fully live.

-- Query 2: the 6/4/3 check -- does the segment row exist, and does its
-- config match the current v3 rubric?
select
  slug,
  jsonb_array_length(config->'rubric')          as rubric_criteria,   -- expect 6
  jsonb_array_length(config->'gates')            as gates,             -- expect 4
  jsonb_array_length(config->'score_modifiers')  as score_modifiers,   -- expect 3
  jsonb_array_length(config->'review_checklist') as review_checklist,  -- expect 3
  config->'rubric'->1->>'points'                 as genre_fit_points,  -- expect 15
  config->'rubric'->3->>'points'                 as right_size_points, -- expect 20
  config->'score_modifiers'->2->>'max_penalty'   as revenue_penalty,   -- expect -20
  config->>'score_threshold_review'              as threshold_review,  -- expect 25
  config->>'score_threshold_priority'            as threshold_priority -- expect 60
from segments
where slug = 'us-production-houses';

-- Query 3: is anything already in entities/staging for this segment?
-- (Informational -- expect 0 rows on a genuinely fresh start.)
select status, count(*)
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
group by status;
