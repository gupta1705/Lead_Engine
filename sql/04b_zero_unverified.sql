-- 04B_ZERO_UNVERIFIED.SQL
-- Owner decision, 2026-08-23: **an unverified rubric or modifier input scores 0.**
--
-- This REVERSES the "null != zero" handling for reviewer-entered data. It does
-- not reverse it for the engine: 06_score.sql still treats an absent key as
-- never-assessed, because that machinery is what lets a partially-enriched
-- entity be scored at all mid-pipeline. What changes is the DATA we hand it --
-- we now hand it explicit zeros instead of blanks.
--
-- WHY THE OWNER IS RIGHT ABOUT THIS
-- Excluding unverified criteria from the denominator inflates every score. It
-- produced a 90.00 for Lowbrow Studios computed from 4 of 6 criteria, sitting
-- in the same column as scores computed from 5 -- numbers that are not
-- comparable, presented as though they were. "We could not verify it" and "it
-- is not there" have the same practical consequence for a lead: no evidence of
-- the thing TVF needs. Scoring it as 0 is the conservative reading.
--
-- WHAT THIS COSTS, STATED PLAINLY
-- After this runs, the data can no longer distinguish "checked, found nothing"
-- from "never checked". That distinction is genuinely useful at P11 when
-- reading why a criterion scored low across a whole batch. So this script
-- preserves it OUT of the score: every key it defaults to 0 is also recorded
-- in `metadata.p1_unverified`. The score is conservative; the provenance
-- survives; P11 can still tell the two apart.
--
-- WHAT IS DELIBERATELY NOT TOUCHED: THE GATES
-- Gate inputs are not 0-or-1 evidence, they are exclusion triggers, and every
-- one fires ONLY on confirmed disqualifying evidence:
--     us_geography              excludes when geography_signal = 'non_us'
--     not_a_major_or_oversized  excludes when major_or_oversized_signal = true
--     usable_first_party_presence excludes when has_reachable_presence = false
--     is_active                 excludes when activity_signal = 'confirmed_dormant'
-- Defaulting an unknown gate input to a falsy value would FIRE two of those
-- four and silently reject real companies for the crime of not being
-- researched. "Unknown scores 0" is right for evidence; it is actively
-- destructive for exclusion triggers. Gates keep passing on unknown.
--
-- Idempotent: re-running changes nothing, because every key already exists.
-- Config-driven: no criterion names appear below, so it works unchanged for
-- Segment 2 and any future rubric revision.

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
      and e.source = 'manual_p1'
),
gaps as (
    -- which keys each row is missing, BEFORE we fill them
    select t.id,
           coalesce(jsonb_agg(k.key order by k.key)
                    filter (where not (t.si ? k.key) or jsonb_typeof(t.si->k.key) = 'null'),
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
                -- win, so anything actually assessed is preserved untouched
                (select d from defaults) || coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)
            ),
            '{p1_unverified}',
            g.unverified
        )
from gaps g
where e.id = g.id;

----------------------------------------------------------------------
-- CONFIRM: every row now carries all 9 rubric+modifier keys, and each
-- records which of them were defaulted rather than evidenced.
----------------------------------------------------------------------
select
    e.name,
    (select count(*) from jsonb_object_keys(e.metadata->'scoring_inputs')) as total_keys,
    jsonb_array_length(e.metadata->'p1_unverified')                        as defaulted_to_zero,
    e.metadata->'p1_unverified'                                            as which
from entities e
where e.segment_id = (select id from segments where slug = 'us-production-houses')
  and e.source = 'manual_p1'
order by e.name;

-- Re-score after this: 06_score.sql. Every entity now has all 6 rubric
-- criteria assessed, so every score is out of the full 110-point pool and the
-- numbers are finally comparable to each other.
