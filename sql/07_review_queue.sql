-- 07_REVIEW_QUEUE.SQL
-- P3 -- Review loop closes.
-- A view over scored, not-yet-decided entities, score-ordered, with the
-- review_checklist pulled from config so you can see the 3 human-judgment
-- items (production-company judgment, subtype judgment, independent-ownership
-- judgment) right next to each candidate -- these are never auto-enforced,
-- by design (free sources can't verify them).

-- SECURITY_INVOKER (added 2026-08-23, after this view was found leaking).
-- A Postgres view runs with its OWNERs privileges by default, so a view owned
-- by postgres over RLS-protected tables hands every row to whoever can select
-- from the view -- and Supabase grants anon SELECT on public objects. Verified
-- live: as anon, entities returned 0 rows (RLS working) while review_queue
-- returned all 10. The anon key ships in browser code, so that was a real leak
-- path, not a theoretical one. security_invoker makes the view run as the
-- CALLER, so the underlying RLS applies. Requires PG15+; Supabase is on 17.
create or replace view review_queue with (security_invoker = true) as
select
  e.id,
  e.name,
  e.domain,
  e.source,
  e.source_url,
  e.fit_score,
  e.score_breakdown,
  e.metadata->>'why_fit'          as why_fit,
  e.metadata->>'subtype'          as subtype,
  e.metadata->'scoring_inputs'    as scoring_inputs,
  s.config->'review_checklist'    as review_checklist,
  (
    select jsonb_agg(jsonb_build_object(
      'full_name', c.full_name,
      'role_title', c.role_title,
      'email', c.email,
      'email_status', c.email_status,
      'is_primary', c.is_primary
    ))
    from contacts c
    where c.entity_id = e.id
  ) as contacts,
  e.status_changed_at
from entities e
join segments s on s.id = e.segment_id
where e.status = 'ready_for_review'
order by e.fit_score desc nulls last;

----------------------------------------------------------------------
-- WORK THE QUEUE
----------------------------------------------------------------------
select * from review_queue;

-- For each row: read why_fit, scoring_inputs, contacts, and the 3
-- review_checklist items against the real site/channel, then either:

-- APPROVE (shortlist) -- swap in the entity's id:
-- update entities set status = 'shortlisted' where id = '<uuid>';

-- REJECT -- always with a one-line reason (never a bare rejection):
-- update entities set status = 'rejected', status_reason = '<why>' where id = '<uuid>';

----------------------------------------------------------------------
-- DONE WHEN: queue is empty (everything dispositioned)
----------------------------------------------------------------------
select count(*) as still_in_queue from review_queue;
-- Expect 0 once you've worked through every row above.

----------------------------------------------------------------------
-- APPROVAL RATE #1 -- record this number in BUILD_PLAN.md's Progress section
----------------------------------------------------------------------
select
  count(*) filter (where status = 'shortlisted')                         as shortlisted,
  count(*) filter (where status = 'rejected')                            as rejected,
  round(
    100.0 * count(*) filter (where status = 'shortlisted')
    / nullif(count(*) filter (where status in ('shortlisted', 'rejected')), 0),
    1
  ) as approval_rate_pct
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1';
