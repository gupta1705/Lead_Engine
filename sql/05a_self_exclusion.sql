-- 05A_SELF_EXCLUSION.SQL
-- Keep TVF and its affiliates out of the lead pool. **Run before every promote.**
--
-- WHY THIS EXISTS, CONCRETELY: the first live YouTube run (2026-08-24) returned
-- The Viral Fever own channel among 125 candidates. It was caught only because
-- 13.1M subscribers tripped `major_or_oversized_signal` -- pure luck. A regional
-- affiliate, a spinoff channel, or a partner shop with 4,000 subscribers would
-- have passed every gate, been scored, reviewed, shortlisted, and eventually
-- put on a send list. The failure mode is TVF cold-emailing itself, or worse, a
-- partner it already works with.
--
-- Config-driven from `config.self_exclusion`, so adding an affiliate is a
-- config edit, never a code change -- and Segment 2 gets the same protection
-- with its own list.
--
-- MATCHING IS DELIBERATELY CONSERVATIVE:
--   domains       exact host or subdomain (`tvfplay.com`, `x.tvfplay.com`)
--   name_patterns whole-word match against a lowercased name
-- There is intentionally no bare `tvf` pattern: it would match TVFoods,
-- TVFirst and similar unrelated companies. A self-exclusion rule that silently
-- deletes real leads is worse than the problem it solves.
--
-- NOT DESTRUCTIVE: nothing is deleted. Staging rows are marked imported with
-- `import_result = 'skipped_self'` so the promote step passes over them, and
-- the evidence of what was caught stays queryable.

----------------------------------------------------------------------
-- One-time: the import_result CHECK predates this rule. Additive only.
-- skipped_shielded_name is what 05_promote_minimal's step 3 writes for a staging row whose name
-- matches a rejected or archived company (the name-level shield). It was missing from this list,
-- so the first harvest that found such a name rolled back the whole promote: LCX Clipping's
-- weekly refresh of 2026-10-07 stopped there ("Maxwell Leadership Podcast").
----------------------------------------------------------------------
alter table staging_candidates drop constraint if exists staging_candidates_import_result_check;
alter table staging_candidates add constraint staging_candidates_import_result_check
    check (import_result in ('inserted', 'merged_duplicate', 'skipped_rejected', 'skipped_self',
                             'skipped_shielded_name'));

----------------------------------------------------------------------
-- STEP 1 -- what would be excluded. Read this before running step 2.
----------------------------------------------------------------------
with cfg as (
    select config->'self_exclusion' as se
    from segments where slug = current_setting('tvf.segment', true)
),
doms as (select jsonb_array_elements_text(se->'domains') as d from cfg),
pats as (select jsonb_array_elements_text(se->'name_patterns') as p from cfg)
select sc.id, sc.name, sc.domain, sc.source,
       case
         when exists (select 1 from doms
                      where lower(sc.domain) = doms.d
                         or lower(sc.domain) like '%.' || doms.d) then 'domain match'
         else 'name match'
       end as why
from staging_candidates sc
where sc.imported = false
  and (
        exists (select 1 from doms
                where lower(sc.domain) = doms.d
                   or lower(sc.domain) like '%.' || doms.d)
     or exists (select 1 from pats
                where lower(sc.name) ~ ('\y' || pats.p || '\y'))
      );

----------------------------------------------------------------------
-- STEP 2 -- mark them. Idempotent: a second run matches nothing new,
-- because the rows it already marked are no longer `imported = false`.
----------------------------------------------------------------------
with cfg as (
    select config->'self_exclusion' as se
    from segments where slug = current_setting('tvf.segment', true)
),
doms as (select jsonb_array_elements_text(se->'domains') as d from cfg),
pats as (select jsonb_array_elements_text(se->'name_patterns') as p from cfg)
update staging_candidates sc
set imported = true,
    import_result = 'skipped_self'
where sc.imported = false
  and (
        exists (select 1 from doms
                where lower(sc.domain) = doms.d
                   or lower(sc.domain) like '%.' || doms.d)
     or exists (select 1 from pats
                where lower(sc.name) ~ ('\y' || pats.p || '\y'))
      );

----------------------------------------------------------------------
-- STEP 3 -- also catch anything that reached `entities` before this rule
-- existed. Archived rather than deleted: an archived row still blocks
-- re-import, which is exactly what we want it to do.
----------------------------------------------------------------------
with cfg as (
    select config->'self_exclusion' as se
    from segments where slug = current_setting('tvf.segment', true)
),
doms as (select jsonb_array_elements_text(se->'domains') as d from cfg),
pats as (select jsonb_array_elements_text(se->'name_patterns') as p from cfg)
update entities e
set status = 'archived',
    status_reason = 'Self-exclusion: TVF or an affiliate. Never a lead.'
where e.segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
  and e.status not in ('archived', 'contacted', 'in_conversation')
  and (
        exists (select 1 from doms
                where lower(e.domain) = doms.d
                   or lower(e.domain) like '%.' || doms.d)
     or exists (select 1 from pats
                where lower(e.name) ~ ('\y' || pats.p || '\y'))
      );

----------------------------------------------------------------------
-- CONFIRM
----------------------------------------------------------------------
select import_result, count(*)
from staging_candidates
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
group by import_result
order by import_result;

select name, domain, status, status_reason
from entities
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
  and status_reason like 'Self-exclusion%';
