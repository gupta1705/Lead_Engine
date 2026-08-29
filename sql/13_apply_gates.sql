-- 13_APPLY_GATES.SQL
--
-- The half of the design that was missing. The config has carried four gates
-- since P1, each firing only on CONFIRMED disqualifying evidence, and the
-- scorer has always deliberately ignored them (06_score.sql header, note 4:
-- "gate logic lands at P9/P13"). P13 was never built -- so on 2026-08-29 the
-- TOP-SCORED lead in a US-segment pool was Dharma Productions, Mumbai,
-- because a proven non_us signal changed nothing. A pool whose #1 lead fails
-- the segment definition is the purest lead-quality bug there is.
--
-- WHAT THIS DOES. Rows with confirmed failing gate evidence become
-- `archived`, with a reason naming the gate and the evidence. Archived is the
-- right disposition, not rejected: rejected means a HUMAN said no and is the
-- shield against re-surfacing; archived means the ENGINE ruled it out of
-- scope, is reversible by flipping status back, and equally blocks re-import.
--
-- WHAT IT REFUSES TO TOUCH:
--   * shortlisted / rejected / contacted rows -- human decisions stand, even
--     when the evidence says the human should reconsider. The row is LISTED
--     at the end instead, for a person to act on.
--   * blank/unknown gate inputs -- per config, absence always passes. Gates
--     fire on evidence, never on missing evidence (Invariant 1).
--
-- Idempotent: already-archived rows are skipped; re-running is a no-op.

do $$
declare
  seg uuid;
  n int;
  total int := 0;
begin
  select id into seg from segments where slug = 'us-production-houses';

  -- gate: us_geography (exclude_when 'non_us')
  update entities
     set status = 'archived',
         status_reason = 'Gate us_geography: confirmed non-US ('
                         || coalesce(metadata->>'verified_country', 'source evidence') || ')',
         status_changed_at = now(), updated_at = now()
   where segment_id = seg
     and status in ('discovered','enriched','scored','ready_for_review')
     and metadata->'scoring_inputs'->>'geography_signal' = 'non_us';
  get diagnostics n = row_count; total := total + n;
  raise notice 'us_geography gate archived % row(s)', n;

  -- gate: is_active (exclude_when 'confirmed_dormant')
  update entities
     set status = 'archived',
         status_reason = 'Gate is_active: confirmed dormant/defunct',
         status_changed_at = now(), updated_at = now()
   where segment_id = seg
     and status in ('discovered','enriched','scored','ready_for_review')
     and metadata->'scoring_inputs'->>'activity_signal' = 'confirmed_dormant';
  get diagnostics n = row_count; total := total + n;
  raise notice 'is_active gate archived % row(s)', n;

  -- gate: not_a_major_or_oversized (exclude_when true)
  update entities
     set status = 'archived',
         status_reason = 'Gate not_a_major_or_oversized: major, subsidiary of one, '
                         'or confirmed far beyond the size ceiling',
         status_changed_at = now(), updated_at = now()
   where segment_id = seg
     and status in ('discovered','enriched','scored','ready_for_review')
     and (metadata->'scoring_inputs'->>'major_or_oversized_signal')::boolean is true;
  get diagnostics n = row_count; total := total + n;
  raise notice 'not_a_major_or_oversized gate archived % row(s)', n;

  -- usable_first_party_presence (exclude_when false) fires only on an
  -- explicit false, which no source writes today; included for completeness.
  update entities
     set status = 'archived',
         status_reason = 'Gate usable_first_party_presence: confirmed no reachable presence',
         status_changed_at = now(), updated_at = now()
   where segment_id = seg
     and status in ('discovered','enriched','scored','ready_for_review')
     and metadata->'scoring_inputs'->>'has_reachable_presence' = 'false';
  get diagnostics n = row_count; total := total + n;

  raise notice 'gates archived % row(s) in total', total;
end $$;

-- Human decisions the evidence now argues with: surfaced, never overridden.
select name, status, status_reason as human_decision,
       metadata->'scoring_inputs'->>'geography_signal' as geo,
       metadata->'scoring_inputs'->>'activity_signal' as activity,
       metadata->'scoring_inputs'->>'major_or_oversized_signal' as major
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status in ('shortlisted','contacted','in_conversation')
  and (metadata->'scoring_inputs'->>'geography_signal' = 'non_us'
       or metadata->'scoring_inputs'->>'activity_signal' = 'confirmed_dormant'
       or (metadata->'scoring_inputs'->>'major_or_oversized_signal')::boolean is true);
