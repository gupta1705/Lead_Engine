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
--
-- THREE MORE CONDITIONS, EACH ONLY WHERE THE SEGMENT'S CONFIG SETS IT. The
-- owner, 2026-10-07 (LCX Services, scoring v4): shortlist automatically above
-- 70 "only with a usable contact and a read site". A segment without these
-- keys runs exactly the old rule: each clause below is true at once when its
-- key is absent, and the reason it writes is the old one, word for word.
--   * auto_shortlist.require_contact: the lead has a contact the drafter will
--     actually write to -- the very test tools/outreach.py cmd_draft picks its
--     address by (an email, and contact_rank > -500, sql/28), so shortlisted
--     means draftable at any score. Under the old LCX score half the points
--     were for holding an address, so all 216 leads shortlisted on 2026-10-07
--     had one; the new score asks whether a company is a buyer first, and a
--     lead can cross the line with nobody to write to.
--   * auto_shortlist.named_contact_for (audience keys, matched to
--     metadata.kind): for these audiences the contact the drafter will pick --
--     the best-ranked one, as cmd_draft orders them -- must be a named person,
--     not an info@ inbox (the owner that day: "banks and mid-size companies need
--     a named person"). A named person at accounting@ ranks below info@, so a
--     name anywhere on the lead is not enough (review, 2026-10-08).
--     tools/enrich_apollo.py reads the same key, so a bank whose best address
--     is an inbox is one it looks for a named person at.
--   * auto_shortlist.require_assessed (rubric keys): each was assessed in the
--     lead's current score (score_breakdown.criteria[].assessed). The score is
--     out of the points known, so a directory label, the right size and an
--     inbox make 72.75 of 80 known points while nobody has read the site; LCX
--     requires content_activity: its site was read, or a directory lists its
--     video or Instagram accounts.
--   * auto_shortlist.require_site_read: the company's own site was looked at
--     (metadata.lcx_judgement.site_checked, written by tools/lcx_judge.py: its
--     own words read, or its pages read and none of them a bot wall). A
--     directory listing its accounts assesses content_activity but is not a
--     read site (review, 2026-10-08).
-- A lead over the line that fails one stays in To review, unstamped, and is
-- shortlisted on the first chain run after the site pass or an Apollo reveal
-- gives it a contact, or its site is read. A lead a person shortlists by hand
-- without a contact is still never drafted: cmd_draft joins on the same test.
-- A key that is set but not a list, or a require_assessed key the rubric does
-- not have, stops the chain (a typo would otherwise hold every lead back).

do $$
declare
  seg_slug text := current_setting('tvf.segment', true);
  seg uuid;
  cfg jsonb;
  min_score numeric;
  need_contact boolean;
  need_site boolean;
  named_for jsonb;
  must_assess jsonb;
  held int;
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
  -- absent (or JSON null) is off; anything else must say what it means, or the chain stops
  need_contact := coalesce((cfg->>'require_contact')::boolean, false);
  need_site := coalesce((cfg->>'require_site_read')::boolean, false);
  named_for := coalesce(nullif(cfg->'named_contact_for', 'null'::jsonb), '[]'::jsonb);
  must_assess := coalesce(nullif(cfg->'require_assessed', 'null'::jsonb), '[]'::jsonb);
  if jsonb_typeof(named_for) <> 'array' or jsonb_typeof(must_assess) <> 'array' then
    raise exception 'auto shortlist: auto_shortlist.named_contact_for and require_assessed must be lists for %',
      seg_slug;
  end if;
  -- a misspelt rubric key would hold every lead back for ever, silently
  if exists (select 1 from jsonb_array_elements_text(must_assess) k(key)
              where not exists (select 1 from segments s2
                                  cross join jsonb_array_elements(coalesce(s2.config->'rubric', '[]'::jsonb)) r
                                 where s2.id = seg and r->>'key' = k.key)) then
    raise exception 'auto shortlist: auto_shortlist.require_assessed names a key that is not in the rubric for %',
      seg_slug;
  end if;

  update entities e
     set status = 'shortlisted',
         status_reason = format('auto-shortlisted: score %s is above %s',
                                round(e.fit_score::numeric, 1), min_score)
                         || case when need_contact and named_for ? coalesce(e.metadata->>'kind', '')
                                 then ', with a named person to write to'
                                 when need_contact then ', with someone to write to'
                                 else '' end
                         || case when jsonb_array_length(must_assess) > 0
                                 then '; assessed: ' || (select string_agg(k, ', ')
                                                           from jsonb_array_elements_text(must_assess) k)
                                 else '' end
                         || case when need_site then '; its site read' else '' end,
         status_changed_at = now(),
         updated_at = now(),
         metadata = coalesce(e.metadata, '{}'::jsonb)
                    || jsonb_build_object('auto_shortlisted_at', now(),
                                          'auto_shortlist_min_score', min_score)
   where e.segment_id = seg
     and e.status = 'ready_for_review'
     and e.fit_score > min_score
     and not (coalesce(e.metadata, '{}'::jsonb) ? 'auto_shortlisted_at')
     -- require_contact: a contact cmd_draft would write to; named_contact_for: a named one
     and (not need_contact
          or exists (select 1 from (
                       -- the contact cmd_draft will write to: same filter, same order
                       select c.full_name from contacts c
                        where c.entity_id = e.id and c.email is not null
                          and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500
                        order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,
                                 c.created_at, c.id
                        limit 1) top
                      where not (named_for ? coalesce(e.metadata->>'kind', ''))
                         or nullif(btrim(coalesce(top.full_name, '')), '') is not null))
     -- require_site_read: its own site was looked at
     and (not need_site or coalesce((e.metadata->'lcx_judgement'->>'site_checked')::boolean, false))
     -- require_assessed: every listed rubric criterion was assessed in the current score
     and not exists (select 1 from jsonb_array_elements_text(must_assess) k(key)
                      where not exists (select 1 from jsonb_array_elements(
                                                 case when jsonb_typeof(e.score_breakdown->'criteria') = 'array'
                                                      then e.score_breakdown->'criteria' else '[]'::jsonb end) x
                                         where x->>'key' = k.key and (x->>'assessed')::boolean));
  get diagnostics n = row_count;

  raise notice 'auto shortlist: % row(s) shortlisted for % (score above %)', n, seg_slug, min_score;
  if need_contact or need_site or jsonb_array_length(must_assess) > 0 then
    -- over the line but held: they wait in To review for a contact or a read site
    select count(*) into held from entities e
     where e.segment_id = seg and e.status = 'ready_for_review' and e.fit_score > min_score
       and not (coalesce(e.metadata, '{}'::jsonb) ? 'auto_shortlisted_at');
    raise notice 'auto shortlist: % more over the line held in review for % (%)', held, seg_slug,
      concat_ws(', or ', case when need_contact then 'no contact the drafter would write to' end,
                         case when need_site then 'its site not yet read' end,
                         case when jsonb_array_length(must_assess) > 0
                              then 'not yet assessed: ' || (select string_agg(k, ', ')
                                                              from jsonb_array_elements_text(must_assess) k) end);
  end if;
end $$;
