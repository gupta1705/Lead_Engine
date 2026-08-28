-- 04C_RESTORE_UNVERIFIED_PROVENANCE.SQL
--
-- WHY THIS EXISTS. 04b writes an explicit 0 for every scoring input no source
-- assessed, and records which keys it defaulted in metadata.unverified_inputs.
-- That list is what lets a human tell "we looked and it scored nothing" apart
-- from "nobody has looked yet" -- the amendment to Invariant 1 that the owner
-- asked for on 2026-08-21.
--
-- The list went missing. A live check on 2026-08-29 found only 58 of 808 rows
-- carrying one, while roughly 439 rows sit at a zero score. The cause is
-- ordinary drift rather than a bug in 04b: rows promoted after the last 04b
-- run were defaulted by later passes, the promote merge in 05 rebuilds
-- metadata from the incoming payload, and set_scoring_input correctly REMOVES
-- a key from the list when real evidence arrives. Net effect, the provenance
-- eroded while the zeros stayed.
--
-- It surfaced through the new review UI, which draws an unassessed criterion
-- differently from one assessed at zero. Without the list every blank read as
-- a hard zero, which is precisely the wrong impression: it makes the pool look
-- judged and rejected when it is mostly just unlooked-at.
--
-- HOW A ZERO IS CLASSIFIED. Only some criteria can legitimately be assessed AT
-- zero by a real source:
--
--   international_ip_experience   only ever written as 1 (news deal language)
--   genre_fit                     only ever written as 0.5 / 1
--   distribution_relationship     only ever written as 1
--   right_size                    only ever written as 1 (site team page)
--   collaboration_openness        only ever written as 1 (site invitation)
--     -> for all five, a stored 0 can ONLY have come from 04b. Unassessed.
--
--   reachable_decision_maker      B1 writes a REAL 0 when it read the site and
--                                 found no published address. That is a
--                                 genuine assessment, so a 0 here is only
--                                 treated as unassessed when no enrichment
--                                 has actually run on the row.
--
-- Idempotent: re-running changes nothing once the lists are correct. Touches
-- no scores, no statuses, and no rejected rows' decisions.

do $$
declare
  seg uuid;
  touched int;
begin
  select id into seg from segments where slug = 'us-production-houses';
  if seg is null then
    raise exception 'segment us-production-houses not found';
  end if;

  with keys as (
    select unnest(array[
      'international_ip_experience', 'genre_fit', 'distribution_relationship',
      'right_size', 'collaboration_openness'
    ]) as k
  ),
  -- every (row, key) pair whose stored value is 0 and whose only possible
  -- author is 04b
  defaulted as (
    select e.id,
           jsonb_agg(distinct k.k) as missing
    from entities e cross join keys k
    where e.segment_id = seg
      and (e.metadata->'scoring_inputs'->>k.k) = '0'
      and not (coalesce(e.metadata->'unverified_inputs', '[]'::jsonb) ? k.k)
    group by e.id
  ),
  -- reachable_decision_maker, handled separately: a 0 is real evidence when an
  -- enrichment pass actually looked at the site and found nothing published.
  rdm as (
    select e.id
    from entities e
    where e.segment_id = seg
      and (e.metadata->'scoring_inputs'->>'reachable_decision_maker') = '0'
      and coalesce(e.metadata->>'enrichment_result', '') not in
          ('no_contact_found', 'site_scrape', 'aicp_directory_api')
      and not (coalesce(e.metadata->'unverified_inputs', '[]'::jsonb)
               ? 'reachable_decision_maker')
  ),
  merged as (
    select coalesce(d.id, r.id) as id,
           coalesce(d.missing, '[]'::jsonb)
             || case when r.id is not null
                     then '["reachable_decision_maker"]'::jsonb
                     else '[]'::jsonb end as add_keys
    from defaulted d
    full outer join rdm r on r.id = d.id
  )
  update entities e
     set metadata = jsonb_set(
           e.metadata, '{unverified_inputs}',
           (
             select jsonb_agg(distinct x)
             from jsonb_array_elements(
                    coalesce(e.metadata->'unverified_inputs', '[]'::jsonb)
                    || m.add_keys) as t(x)
           )),
         updated_at = now()
    from merged m
   where e.id = m.id
     and jsonb_array_length(m.add_keys) > 0;

  get diagnostics touched = row_count;
  raise notice 'restored unverified_inputs provenance on % row(s)', touched;
end $$;

-- What the pool looks like afterwards. An honest engine should report a LOT of
-- unassessed criteria at this stage -- that is the finding, not a failure.
select
  count(*)                                                    as rows_total,
  count(*) filter (where jsonb_array_length(
      coalesce(metadata->'unverified_inputs','[]'::jsonb)) > 0) as rows_with_gaps,
  round(avg(jsonb_array_length(
      coalesce(metadata->'unverified_inputs','[]'::jsonb))), 2) as avg_gaps_per_row
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status in ('discovered','enriched','scored','ready_for_review');
