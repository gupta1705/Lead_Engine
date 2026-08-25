-- 04B_ZERO_UNVERIFIED.SQL
-- Owner rule, 2026-08-23: **an unverified rubric or modifier input scores 0.**
--
-- Originally written for the ten hand-entered P1 rows. GENERALISED 2026-08-23
-- for P4: it now applies to every pre-review entity in the segment regardless
-- of source, because the moment a connector starts writing rows this has to run
-- over them too. If it stayed scoped to `manual_p1`, YouTube-sourced leads would
-- be scored on partial denominators while hand-entered ones were scored on the
-- full pool -- and Checkpoint 1 (P11) compares approval rate PER SOURCE. The
-- connector would look better than it is, for a reason that has nothing to do
-- with the companies it found.
--
-- WHERE THIS SITS IN THE PIPELINE: after promote (P9), before scoring (P15).
-- Run it on every batch. Idempotent -- a second run changes nothing, because
-- every key already exists.
--
-- SCOPE: only entities not yet dispositioned. A shortlisted or rejected row is
-- a decision already made; this never reaches back and alters one.
--
-- WHAT IT COSTS, STATED PLAINLY: after this runs, the data cannot distinguish
-- "checked, found nothing" from "never checked". That distinction is genuinely
-- useful at P11 when reading why a criterion scored low across a whole batch,
-- so it is preserved OUT of the score: every key defaulted to 0 is recorded in
-- `metadata.unverified_inputs`. Conservative score, provenance intact.
--
-- ⚑ LOAD-BEARING FOR P14 (dedupe/merge). The merge rule there is "existing
-- values kept unless empty" -- and a defaulted 0 is not empty. Without care, a
-- company first found by YouTube (international_ip_experience defaulted to 0)
-- and later found by News RSS with a real format-deal headline would KEEP the
-- 0 and discard the 1. The fix is already available: any key listed in
-- `unverified_inputs` must be treated as overwritable by real evidence. That
-- list is why this script records it rather than just writing zeros.
--
-- WHAT IS DELIBERATELY NOT TOUCHED: THE GATES. Gate inputs are not evidence,
-- they are exclusion triggers, and each fires ONLY on confirmed disqualifying
-- evidence:
--     us_geography                excludes when geography_signal = 'non_us'
--     not_a_major_or_oversized    excludes when major_or_oversized_signal = true
--     usable_first_party_presence excludes when has_reachable_presence = false
--     is_active                   excludes when activity_signal = 'confirmed_dormant'
-- Defaulting an unknown gate input to a falsy value would FIRE two of those four
-- and silently reject real companies for the crime of not being researched.
-- "Unknown scores 0" is right for evidence and destructive for triggers.
--
-- Config-driven: no criterion name appears below, so it works unchanged for a
-- rubric revision or for Segment 2.

----------------------------------------------------------------------
-- MIGRATION (harmless once applied): the metadata key was `p1_unverified`
-- when this only ran over P1 rows. It is source-agnostic now, so the key is
-- `unverified_inputs`. Renames in place; no-op if already done.
----------------------------------------------------------------------
update entities
set metadata = (metadata - 'p1_unverified')
               || jsonb_build_object('unverified_inputs', metadata->'p1_unverified')
where metadata ? 'p1_unverified';

----------------------------------------------------------------------
-- THE RULE
----------------------------------------------------------------------
with keys as (
    -- every rubric + modifier input the config defines (NOT gates)
    select split_part(x.item->>'input', '.', 3) as key
    from segments s
    cross join lateral (
        select jsonb_array_elements(s.config->'rubric')          as item
        union all
        select jsonb_array_elements(s.config->'score_modifiers')
    ) x
    where s.slug = 'us-production-houses'
),
target as (
    select e.id, coalesce(e.metadata->'scoring_inputs', '{}'::jsonb) as si
    from entities e
    where e.segment_id = (select id from segments where slug = 'us-production-houses')
      and e.status in ('discovered', 'enriched', 'scored', 'ready_for_review')
),
gaps as (
    -- which keys each row is missing, BEFORE they are filled
    select t.id,
           coalesce(jsonb_agg(k.key order by k.key)
                    filter (where not (t.si ? k.key)
                               or jsonb_typeof(t.si->k.key) = 'null'),
                    '[]'::jsonb) as unverified
    from target t
    cross join keys k
    group by t.id
),
defaults as (
    select jsonb_object_agg(key, to_jsonb(0)) as d from keys
)
update entities e
set metadata =
        jsonb_set(
            jsonb_set(
                e.metadata,
                '{scoring_inputs}',
                -- defaults first, real values second: `||` lets the RIGHT side
                -- win, so anything actually assessed survives untouched
                (select d from defaults)
                || coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)
            ),
            '{unverified_inputs}',
            g.unverified
        )
from gaps g
where e.id = g.id;

----------------------------------------------------------------------
-- CONFIRM: every pre-review row carries the full rubric+modifier key set,
-- and records which of those were defaulted rather than evidenced.
----------------------------------------------------------------------
select
    e.source,
    count(*)                                                          as rows,
    min((select count(*) from jsonb_object_keys(e.metadata->'scoring_inputs'))) as min_keys,
    round(avg(jsonb_array_length(e.metadata->'unverified_inputs')), 1) as avg_defaulted
from entities e
where e.segment_id = (select id from segments where slug = 'us-production-houses')
  and e.status in ('discovered', 'enriched', 'scored', 'ready_for_review')
group by e.source
order by e.source;

-- Re-score after this: every entity now has all rubric criteria assessed, so
-- every score is out of the full pool and the numbers are comparable across
-- sources -- which is the whole point of Checkpoint 1.
