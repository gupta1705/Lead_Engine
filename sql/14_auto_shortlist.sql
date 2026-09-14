-- 14_AUTO_SHORTLIST.SQL
--
-- Owner decision, 2026-09-14: "Instead of shortlisting i want you to
-- automatically shortlist anyone with score above 20."
--
-- Runs as the LAST step of the promote chain (tools/run_chain.py), after the
-- gates, for whichever segment the session setting tvf.segment names. It does
-- nothing at all unless that segment's config says auto_shortlist.enabled.
--
-- WHAT IT TOUCHES, and only this: rows that are ready_for_review -- so the
-- gates have already passed them -- with fit_score strictly above
-- auto_shortlist.min_score. Rejected, archived, contacted and in-conversation
-- rows are never touched: a person's decision and the gates' decision stand.
--
-- IT NEVER OVERRULES A PERSON. Every row it shortlists is stamped
-- metadata.auto_shortlisted_at. A stamped row that is back in ready_for_review
-- got there because somebody put it back, so every later run leaves it alone.
-- The same stamp makes the step idempotent.
--
-- SHORTLISTING SENDS NOTHING. It makes a lead eligible for a draft. Every draft
-- still needs a person to approve it before anything leaves.

do $$
declare
  seg_slug text := current_setting('tvf.segment', true);
  seg uuid;
  cfg jsonb;
  min_score numeric;
  n int;
begin
  select s.id, s.config->'auto_shortlist' into seg, cfg
    from segments s where s.slug = seg_slug;
  if seg is null then
    raise notice 'auto shortlist: no segment named %', seg_slug;
    return;
  end if;
  if coalesce((cfg->>'enabled')::boolean, false) is not true then
    raise notice 'auto shortlist: off for % (config auto_shortlist.enabled)', seg_slug;
    return;
  end if;
  min_score := (cfg->>'min_score')::numeric;
  if min_score is null then
    -- turned on but not told where the line is: stop the chain, do not guess
    raise exception 'auto shortlist: auto_shortlist.min_score is missing for %', seg_slug;
  end if;

  update entities e
     set status = 'shortlisted',
         status_reason = format('auto-shortlisted: score %s is above %s',
                                round(e.fit_score::numeric, 1), min_score),
         status_changed_at = now(),
         updated_at = now(),
         metadata = coalesce(e.metadata, '{}'::jsonb)
                    || jsonb_build_object('auto_shortlisted_at', now(),
                                          'auto_shortlist_min_score', min_score)
   where e.segment_id = seg
     and e.status = 'ready_for_review'
     and e.fit_score > min_score
     and not (coalesce(e.metadata, '{}'::jsonb) ? 'auto_shortlisted_at');
  get diagnostics n = row_count;

  raise notice 'auto shortlist: % row(s) shortlisted for % (score above %)', n, seg_slug, min_score;
end $$;
