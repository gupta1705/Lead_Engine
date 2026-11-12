-- 13_APPLY_GATES.SQL
--
-- Gates, driven by the segment config -- rewritten 2026-09-09 for Segment 3.
--
-- The first version of this file hard-coded the four TVF gates as four update
-- statements. That was fine for one segment and wrong the moment a second one
-- existed: the LCX clipping segment gates on country, activity, category and
-- network ownership, none of which the old file knew. The config has always
-- carried everything a gate needs -- an input path and the value that fires
-- it -- so this file now reads config.gates and applies each one generically.
--
-- SEMANTICS, unchanged from the original: a gate fires ONLY on confirmed
-- disqualifying evidence -- the input equals exclude_when. Blank or unknown
-- always passes (Invariant 1: absence is not evidence). Rows that fire become
-- `archived` with a reason naming the gate. Archived is the engine ruling a
-- row out of scope: reversible, and it blocks re-import exactly as rejected
-- does. Rejected rows, and rows a person shortlisted, are never touched -- a
-- human decision stands; the ones the evidence argues with are listed at the
-- end. Since 2026-11-12 a row the ENGINE shortlisted (auto-shortlist) is
-- re-gated, and its unsent emails cancelled; a contacted row loses only its
-- unsent follow-up.
--
-- The segment comes from the session setting tvf.segment, which
-- tools/run_sql.py sets from SEGMENT_SLUG (default us-production-houses), so
-- the same file serves every segment. Idempotent: archived rows are skipped.

do $$
declare
  seg uuid;
  slug text := current_setting('tvf.segment', true);
  g jsonb;
  key text;
  input_path text[];
  exclude_when text;
  n int;
  total int := 0;
begin
  select id into seg from segments where segments.slug = current_setting('tvf.segment', true);
  if seg is null then
    raise exception 'no segments row for tvf.segment = %', slug;
  end if;

  for g in select jsonb_array_elements(coalesce(config->'gates', '[]'::jsonb))
             from segments where id = seg
  loop
    key := g->>'key';
    -- "metadata.scoring_inputs.geography_signal" -> path inside metadata
    input_path := string_to_array(regexp_replace(g->>'input', '^metadata\.', ''), '.');
    exclude_when := g->>'exclude_when';        -- 'true' / 'false' / 'non_us' ...
    if key is null or input_path is null or exclude_when is null then
      raise notice 'gate % skipped: incomplete definition', coalesce(key, '?');
      continue;
    end if;

    update entities e
       set status = 'archived',
           status_reason = 'Gate ' || key || ': ' || coalesce(g->>'label', 'confirmed failing evidence')
                           || ' (' || coalesce(e.metadata #>> input_path, '?') || ')',
           status_changed_at = now(), updated_at = now()
     where e.segment_id = seg
       and e.status in ('discovered','enriched','scored','ready_for_review')
       and e.metadata #>> input_path is not null
       and lower(e.metadata #>> input_path) = lower(exclude_when);
    get diagnostics n = row_count;
    total := total + n;
    raise notice 'gate % archived % row(s)', key, n;

    -- Evidence that arrives after the engine shortlisted a lead (2026-11-12: a channel's country found by the
    -- enrichment pass AFTER auto-shortlist let emails to Austria and Germany be drafted and approved). A lead the
    -- engine shortlisted itself (metadata.auto_shortlisted_at) is the engine's decision, so the gate overrules it:
    -- archived, and its unsent emails (drafted or approved) cancelled. A lead a person shortlisted by hand stands
    -- and is listed at the end, as before. Contacted leads keep their status and sent history; only an unsent
    -- follow-up to one is cancelled.
    update outreach o
       set status = 'cancelled', updated_at = now(),
           stopped_reason = left('withdrawn: gate ' || key || ' (' || coalesce(e.metadata #>> input_path, '?') || ')', 200)
      from entities e
     where o.entity_id = e.id and e.segment_id = seg
       and o.direction = 'outbound' and o.status in ('drafted', 'approved')
       and (e.status = 'contacted' or (e.status = 'shortlisted' and e.metadata ? 'auto_shortlisted_at'))
       and e.metadata #>> input_path is not null
       and lower(e.metadata #>> input_path) = lower(exclude_when);
    get diagnostics n = row_count;
    if n > 0 then raise notice 'gate % withdrew % unsent email(s)', key, n; end if;
    update entities e
       set status = 'archived',
           status_reason = 'Gate ' || key || ' (after shortlisting): ' || coalesce(g->>'label', 'confirmed failing evidence')
                           || ' (' || coalesce(e.metadata #>> input_path, '?') || ')',
           status_changed_at = now(), updated_at = now()
     where e.segment_id = seg
       and e.status = 'shortlisted' and e.metadata ? 'auto_shortlisted_at'
       and e.metadata #>> input_path is not null
       and lower(e.metadata #>> input_path) = lower(exclude_when);
    get diagnostics n = row_count;
    total := total + n;
    if n > 0 then raise notice 'gate % archived % auto-shortlisted row(s)', key, n; end if;
  end loop;

  raise notice 'gates archived % row(s) in total for %', total, slug;
end $$;

-- Human decisions the evidence now argues with: surfaced, never overridden.
with cfg as (
  select id as seg, jsonb_array_elements(coalesce(config->'gates', '[]'::jsonb)) as g
  from segments where slug = current_setting('tvf.segment', true)
)
select e.name, e.status, e.status_reason as human_decision,
       cfg.g->>'key' as gate,
       e.metadata #>> string_to_array(regexp_replace(cfg.g->>'input', '^metadata\.', ''), '.') as evidence
from entities e
join cfg on cfg.seg = e.segment_id
where e.status in ('shortlisted','contacted','in_conversation')
  and not (e.status = 'shortlisted' and e.metadata ? 'auto_shortlisted_at')
  and lower(e.metadata #>> string_to_array(regexp_replace(cfg.g->>'input', '^metadata\.', ''), '.'))
      = lower(cfg.g->>'exclude_when');
