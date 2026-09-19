-- KPI_QUERIES.SQL
-- P26: the numbers Reports shows, as SQL the dashboard and the CLI both run.
--
-- Every query reads the segment slug from the session setting tvf.segment
-- (set via set_config by tools/kpis.py and /api/kpis) so Segment 2 reads the same dashboard. Each returns ONE row of named
-- columns; the app assembles them into /api/kpis, tools/kpis.py prints them.
--
-- Trimmed 2026-09-19 (owner: "get rid of all useless features"): the approval
-- rate measured the auto-shortlist rule, the enrichment block had no decision
-- attached, and the unattended block had no segment filter. What stays is the
-- status funnel, outreach results and which sources yield shortlisted leads.

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

-- ------------------------------------------------------ per-source yield
-- Which harvests find leads worth shortlisting: what each one found, how much
-- of it has a contact, and how much was shortlisted (or went further).
-- name: by_source
select
  source,
  count(*)                                                       as found,
  count(*) filter (where exists (select 1 from contacts c
                                 where c.entity_id = e.id))      as contactable,
  count(*) filter (where status in ('shortlisted','contacted',
                                    'in_conversation'))          as approved
from entities e
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
group by source
order by approved desc, found desc;

-- -------------------------------------------------------------- outreach
-- The v1 clause that matters most: contacted per week, replies, positives.
-- name: outreach
select
  -- every email sent, then companies contacted (openers) and follow-ups
  -- separately: "contacted per week" means companies, not emails (2026-09-10)
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent')            as sent_total,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                     and o.sequence_step = 0)                                     as openers_sent,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                     and o.sequence_step > 0)                                     as followups_sent,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent' and o.sequence_step = 0
                     and o.sent_at >= now() - interval '7 days')                  as sent_last_7d,
  count(*) filter (where o.direction = 'outbound' and o.status = 'sent' and o.sequence_step = 0
                     and o.sent_at >= now() - interval '28 days')                 as sent_last_28d,
  count(*) filter (where o.direction = 'outbound' and o.status = 'drafted')         as drafts_waiting,
  count(*) filter (where o.direction = 'outbound' and o.status = 'approved')        as approved_waiting,
  count(*) filter (where o.direction = 'inbound')                                   as replies,
  count(*) filter (where o.direction = 'inbound' and o.triage = 'positive')         as positive_replies,
  count(*) filter (where o.direction = 'inbound' and o.triage = 'needs_human')      as replies_needing_human,
  -- rates per COMPANY contacted, so follow-ups cannot inflate or deflate them
  round(100.0 * count(distinct o.entity_id) filter (where o.direction = 'inbound')
        / nullif(count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                                    and o.sequence_step = 0), 0), 1)               as reply_rate_pct,
  round(100.0 * count(distinct o.entity_id) filter (where o.direction = 'inbound' and o.triage = 'positive')
        / nullif(count(*) filter (where o.direction = 'outbound' and o.status = 'sent'
                                    and o.sequence_step = 0), 0), 1)               as positive_rate_pct
from outreach o
join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = current_setting('tvf.segment', true));

