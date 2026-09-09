-- 06_SCORE.SQL
-- P2 -- Scoring works.
-- A config-driven scorer with ZERO segment knowledge: it reads config.rubric
-- and config.score_modifiers off the segments row and does the arithmetic.
-- Change the rubric/weights in config -- never in this file -- and every
-- future segment (startups, etc.) reuses this unchanged.
--
-- Rules encoded here (do not weaken these without updating BUILD_PLAN.md's
-- invariants section too):
--   1. NULL != ZERO. A scoring_inputs key that is missing, OR present with
--      JSON null, is "not assessed" -- excluded from both earned points and
--      the denominator. Detected via the ->>/#>> text-extraction operators,
--      which correctly return SQL NULL for both cases (the jsonb #> operator
--      alone would NOT catch an explicit JSON null -- a real Postgres
--      gotcha, handled correctly below).
--   2. Rubric criteria normalize to 0-100 over only the ASSESSED points pool,
--      not the full rubric pool -- so a partially-enriched entity's score
--      means "fit among what we know", not "fit assuming unknowns are bad".
--   3. Modifiers (penalties/bonuses) apply as a delta AFTER normalization,
--      and only if at least one rubric criterion was assessed (a modifier
--      alone can't produce a score out of nothing).
--   4. Gates are NOT handled here. This scorer only touches rubric +
--      score_modifiers. Gate logic (exclude on confirmed disqualifying
--      evidence) lands at P9/P13, in the promote/Run-A path, not scoring.
--   5. Final score is clamped to [0, 100].

----------------------------------------------------------------------
-- score_entity: scores exactly one entity, writes fit_score +
-- score_breakdown, and (if it was still pre-review) advances status to
-- 'ready_for_review'. Returns the numeric score (NULL if nothing was
-- assessable yet).
----------------------------------------------------------------------
create or replace function score_entity(p_entity_id uuid) returns numeric as $$
declare
    v_metadata      jsonb;
    v_config        jsonb;
    v_rubric        jsonb;
    v_modifiers     jsonb;
    v_crit          jsonb;
    v_mod           jsonb;
    v_path          text[];
    v_raw_text      text;
    v_raw_value     numeric;
    v_points        numeric;
    v_earned        numeric := 0;
    v_max_assessed  numeric := 0;
    v_criteria_known int := 0;
    v_criteria_total int := 0;
    v_base_score    numeric;
    v_modifier_delta numeric := 0;
    v_final_score   numeric;
    v_breakdown_criteria  jsonb := '[]'::jsonb;
    v_breakdown_modifiers jsonb := '[]'::jsonb;
begin
    select e.metadata, s.config
      into v_metadata, v_config
      from entities e
      join segments s on s.id = e.segment_id
     where e.id = p_entity_id;

    if v_config is null then
        raise exception 'score_entity: entity % not found or has no segment config', p_entity_id;
    end if;

    v_rubric    := coalesce(v_config->'rubric', '[]'::jsonb);
    v_modifiers := coalesce(v_config->'score_modifiers', '[]'::jsonb);

    ------------------------------------------------------------------
    -- RUBRIC PASS
    ------------------------------------------------------------------
    for v_crit in select * from jsonb_array_elements(v_rubric)
    loop
        v_criteria_total := v_criteria_total + 1;
        v_path   := string_to_array(v_crit->>'input', '.');
        v_path   := v_path[2:array_length(v_path, 1)];   -- drop leading 'metadata'
        v_points := (v_crit->>'points')::numeric;

        v_raw_text := v_metadata #>> v_path;              -- SQL NULL for both
                                                            -- missing key AND
                                                            -- explicit json null
        if v_raw_text is null then
            v_breakdown_criteria := v_breakdown_criteria || jsonb_build_object(
                'key', v_crit->>'key',
                'assessed', false,
                'points_possible', v_points
            );
            continue;
        end if;

        begin
            v_raw_value := v_raw_text::numeric;
        exception when invalid_text_representation then
            raise exception 'score_entity: entity % rubric key % has non-numeric value %',
                p_entity_id, v_crit->>'key', v_raw_text;
        end;

        v_criteria_known := v_criteria_known + 1;
        v_max_assessed    := v_max_assessed + v_points;
        v_earned           := v_earned + (v_raw_value * v_points);

        v_breakdown_criteria := v_breakdown_criteria || jsonb_build_object(
            'key', v_crit->>'key',
            'assessed', true,
            'raw_value', v_raw_value,
            'points_possible', v_points,
            'points_earned', round(v_raw_value * v_points, 4)
        );
    end loop;

    if v_max_assessed = 0 then
        -- Nothing assessed at all -- cannot produce a score yet. Leave
        -- fit_score NULL rather than inventing a number from modifiers alone.
        update entities
           set fit_score = null,
               score_breakdown = jsonb_build_object(
                   'criteria', v_breakdown_criteria,
                   'criteria_known', v_criteria_known,
                   'criteria_total', v_criteria_total,
                   'note', 'no rubric criteria assessed yet -- score withheld'
               )
         where id = p_entity_id;
        return null;
    end if;

    v_base_score := (v_earned / v_max_assessed) * 100;

    ------------------------------------------------------------------
    -- MODIFIERS PASS (soft additive/subtractive deltas on the base)
    ------------------------------------------------------------------
    for v_mod in select * from jsonb_array_elements(v_modifiers)
    loop
        v_path := string_to_array(v_mod->>'input', '.');
        v_path := v_path[2:array_length(v_path, 1)];

        v_raw_text := v_metadata #>> v_path;
        if v_raw_text is null then
            v_breakdown_modifiers := v_breakdown_modifiers || jsonb_build_object(
                'key', v_mod->>'key',
                'assessed', false
            );
            continue;
        end if;

        begin
            v_raw_value := v_raw_text::numeric;
        exception when invalid_text_representation then
            raise exception 'score_entity: entity % modifier key % has non-numeric value %',
                p_entity_id, v_mod->>'key', v_raw_text;
        end;

        -- penalty modifiers carry max_penalty (already negative);
        -- bonus modifiers carry max_bonus (positive).
        if v_mod ? 'max_penalty' then
            v_points := (v_mod->>'max_penalty')::numeric;
        else
            v_points := (v_mod->>'max_bonus')::numeric;
        end if;

        v_modifier_delta := v_modifier_delta + (v_raw_value * v_points);

        v_breakdown_modifiers := v_breakdown_modifiers || jsonb_build_object(
            'key', v_mod->>'key',
            'assessed', true,
            'raw_value', v_raw_value,
            'delta', round(v_raw_value * v_points, 4)
        );
    end loop;

    v_final_score := greatest(0, least(100, v_base_score + v_modifier_delta));

    update entities
       set fit_score = round(v_final_score, 2),
           score_breakdown = jsonb_build_object(
               'criteria', v_breakdown_criteria,
               'modifiers', v_breakdown_modifiers,
               'criteria_known', v_criteria_known,
               'criteria_total', v_criteria_total,
               'points_earned', round(v_earned, 4),
               'points_possible_assessed', v_max_assessed,
               'base_score', round(v_base_score, 2),
               'modifier_delta', round(v_modifier_delta, 4),
               'final_score', round(v_final_score, 2)
           ),
           -- Advance pre-review entities into the queue; never touch an
           -- entity a human has already dispositioned or moved further.
           status = case when status in ('discovered', 'enriched')
                         then 'ready_for_review'
                         else status
                    end
     where id = p_entity_id;

    return round(v_final_score, 2);
end;
$$ language plpgsql;

----------------------------------------------------------------------
-- score_segment: convenience wrapper -- scores every not-yet-decided
-- entity in a segment. Safe to re-run: already-decided entities
-- (shortlisted/rejected/contacted/in_conversation/archived) are skipped,
-- so a re-run never overwrites a human's disposition.
----------------------------------------------------------------------
create or replace function score_segment(p_segment_slug text)
returns table(entity_id uuid, entity_name text, fit_score numeric) as $$
begin
    return query
    select e.id, e.name, score_entity(e.id)
      from entities e
      join segments s on s.id = e.segment_id
     where s.slug = p_segment_slug
       and e.status not in ('shortlisted', 'rejected', 'contacted', 'in_conversation', 'archived');
end;
$$ language plpgsql;

----------------------------------------------------------------------
-- RUN IT
----------------------------------------------------------------------
select * from score_segment(current_setting('tvf.segment', true));

-- Inspect results, highest fit first:
select
    name,
    status,
    fit_score,
    score_breakdown->>'criteria_known' as criteria_known,
    score_breakdown->>'criteria_total' as criteria_total,
    score_breakdown
from entities
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
order by fit_score desc nulls last;

----------------------------------------------------------------------
-- MANUAL CHECK (P2's done-when): pick one entity above, and by hand:
--   1. sum (raw_value * points) for every ASSESSED rubric criterion
--   2. divide by the sum of points for those same assessed criteria
--   3. multiply by 100  -> this should equal score_breakdown->>'base_score'
--   4. add each assessed modifier's (raw_value * max_penalty/max_bonus)
--   5. clamp to [0,100] -> this should equal fit_score exactly
----------------------------------------------------------------------
