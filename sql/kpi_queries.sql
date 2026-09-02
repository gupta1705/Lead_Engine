-- KPI_QUERIES.SQL
-- P26: the numbers v1 is judged by, as SQL the dashboard and the CLI both run.
--
-- Every query reads the segment slug from the session setting tvf.segment
-- (set via set_config by tools/kpis.py and /api/kpis) so Segment 2 reads the same dashboard. Each returns ONE row of named
-- columns; the app assembles them into /api/kpis, tools/kpis.py prints them.
--
-- The v1 done-when (BUILD_PLAN P26): 15-20 leads contacted on schedule, sourced
-- from all connectors, replies auto-triaged, human time <= ~3h/week. These are
-- the measurements behind each clause, plus the per-source yield the plan has
-- wanted since P11.

-- ---------------------------------------------------------------- funnel
-- name: funnel
select
  count(*)                                                        as discovered,
  count(*) filter (where domain is not null)                      as with_website,
  count(*) filter (where exists (select 1 from contacts c
                                 where c.entity_id = e.id))       as contactable,
  count(*) filter (where status in ('discovered','enriched','scored',
                                    'ready_for_review'))          as open_pool,
  count(*) filter (where fit_score >= 25 and status in
      ('discovered','enriched','scored','ready_for_review'))      as reviewable,
  count(*) filter (where status = 'shortlisted')                  as shortlisted,
  count(*) filter (where status = 'rejected')                     as rejected,
  count(*) filter (where status = 'contacted')                    as contacted,
  count(*) filter (where status = 'in_conversation')              as in_conversation,
  count(*) filter (where status = 'archived')                     as archived_out_of_scope
from entities e
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true));

-- --------------------------------------------------------- approval rate
-- The Checkpoint 1 number: of everything a human has ruled on, how much was
-- worth keeping. Only human dispositions count (archived = engine, excluded).
-- name: approval
select
  count(*) filter (where status in ('shortlisted','contacted','in_conversation')) as approved,
  count(*) filter (where status = 'rejected')                                     as rejected,
  round(100.0 * count(*) filter (where status in ('shortlisted','contacted','in_conversation'))
        / nullif(count(*), 0), 1)                                                as approval_rate_pct
from entities
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
  and status in ('shortlisted','contacted','in_conversation','rejected');

-- ------------------------------------------------------ per-source yield
-- Which connectors earn their place: what each one found, how much of it
-- survived to be reviewable, and what humans thought of it.
-- name: by_source
select
  source,
  count(*)                                                       as found,
  count(*) filter (where domain is not null)                     as with_website,
  count(*) filter (where exists (select 1 from contacts c
                                 where c.entity_id = e.id))      as contactable,
  count(*) filter (where fit_score >= 25 and status in
      ('discovered','enriched','scored','ready_for_review'))     as reviewable,
  count(*) filter (where status in ('shortlisted','contacted',
                                    'in_conversation'))          as approved,
  count(*) filter (where status = 'rejected')                    as rejected,
  round(100.0 * count(*) filter (where status in ('shortlisted','contacted','in_conversation'))
        / nullif(count(*) filter (where status in ('shortlisted','contacted',
                                                   'in_conversation','rejected')), 0), 1)
                                                                 as approval_rate_pct
from entities e
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
group by source
order by approved desc, reviewable desc, found desc;

-- ----------------------------------------------------------- enrichment
-- Contact-find rate and address quality. email_status comes from the
-- verification path each contact took; 'invalid' is the only hard failure.
-- name: enrichment
select
  count(distinct e.id) filter (where e.domain is not null)               as sites_known,
  count(distinct c.entity_id)                                            as with_contact,
  round(100.0 * count(distinct c.entity_id)
        / nullif(count(distinct e.id) filter (where e.domain is not null), 0), 1)
                                                                         as contact_find_rate_pct,
  count(c.id) filter (where c.full_name is not null)                     as named_contacts,
  count(c.id) filter (where c.email_status = 'invalid')                  as invalid_emails,
  round(100.0 * count(c.id) filter (where c.email_status <> 'invalid')
        / nullif(count(c.id), 0), 1)                                     as email_validity_pct
from entities e
left join contacts c on c.entity_id = e.id
where e.segment_id = (select id from segments where slug = current_setting('tvf.segment', true));

-- -------------------------------------------------------------- outreach
-- The v1 clause that matters most: contacted per week, replies, positives.
-- name: outreach
select
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent')            as sent_total,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                     and o.sent_at >= now() - interval '7 days')                  as sent_last_7d,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                     and o.sent_at >= now() - interval '28 days')                 as sent_last_28d,
  count(*) filter (where o.direction = 'outbound' and o.status = 'drafted')         as drafts_waiting,
  count(*) filter (where o.direction = 'outbound' and o.status = 'approved')        as approved_waiting,
  count(*) filter (where o.direction = 'inbound')                                   as replies,
  count(*) filter (where o.direction = 'inbound' and o.triage = 'positive')         as positive_replies,
  count(*) filter (where o.direction = 'inbound' and o.triage = 'needs_human')      as replies_needing_human,
  round(100.0 * count(*) filter (where o.direction = 'inbound')
        / nullif(count(*) filter (where o.direction = 'outbound' and o.status = 'sent'), 0), 1)
                                                                                    as reply_rate_pct,
  round(100.0 * count(*) filter (where o.direction = 'inbound' and o.triage = 'positive')
        / nullif(count(*) filter (where o.direction = 'outbound' and o.status = 'sent'), 0), 1)
                                                                                    as positive_rate_pct
from outreach o
join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = current_setting('tvf.segment', true));

-- ------------------------------------------------------------ unattended
-- Is the engine actually running itself? Last scheduled runs and failures.
-- name: unattended
select
  (select count(*) from pipeline_runs where step is null
     and started_at >= now() - interval '28 days')                            as pipeline_runs_28d,
  (select count(*) from pipeline_runs where step is null and status = 'failed'
     and started_at >= now() - interval '28 days')                            as pipeline_failures_28d,
  (select max(started_at) from pipeline_runs where step is null)              as last_pipeline_run,
  (select count(*) from source_runs where started_at >= now() - interval '28 days') as harvests_28d,
  (select max(started_at) from source_runs)                                   as last_harvest;
