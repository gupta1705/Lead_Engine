-- 47_clipping_leads.sql -- better LCX Clipping leads (the owner, 2026-11-12: "Apply all these suggested changes",
-- after the research on Clipping leads). The database side of it:
--
--   * contact_rank(): an address that exists only to fill a podcast feed (feed@, feeds@, rss@, podcast-feed@) is
--     never written to, in any project: of the Clipping replies, one was a feed address answering "NOT READ BY
--     ANYONE". Everything else in the ranking is unchanged (sql/28).
--   * contact_source_bonus(entity, source): where a project's config sets enrichment.prefer_site_contacts (LCX
--     Clipping), an address the show's own website publishes ranks above the one in its podcast feed or channel
--     description: +40 for a site's address, -10 for a feed's or a description's. 0 in every other project, so
--     their order is exactly as before.
--   * refresh_primary_contacts(): orders by contact_rank + contact_source_bonus, as the drafter's choice does
--     (tools/recipient_selection.py) and the automatic shortlist (sql/14), so the three agree.
-- Idempotent: safe to run again.

create or replace function contact_rank(p_name text, p_email text, p_role text, p_status text, p_domain text)
returns integer language sql immutable as $$
  select
      -- nothing to write to
      case when p_email is null or p_status = 'invalid'
                or p_email !~* '^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$' then -1000 else 0 end
      -- a template placeholder, a URL fragment, or an escape glued to an inbox (nmail@ was "\nmail@")
    + case when split_part(lower(coalesce(p_email, '')), '@', 1)
                ~ '^(first\.?name|last\.?name|first|last|name|your\.?name|email|e-?mail|example|test|user|username)$'
             or split_part(lower(coalesce(p_email, '')), '@', 1)
                ~ '^(n|r|t|u00[0-9a-f]{2}|x[0-9a-f]{2})(info|mail|hello|contact|office|press|studio|team|hi|hey|enquiries|inquiries|sales|admin|general|production)$'
             or position('%' in split_part(coalesce(p_email, ''), '@', 1)) > 0 then -500 else 0 end
      -- an address that only fills a podcast feed: nobody reads it (2026-11-12)
    + case when split_part(lower(coalesce(p_email, '')), '@', 1) ~ '^(feeds?|rss|podcast-?feeds?)$' then -1000 else 0 end
      -- a mailbox nobody reads for a partnership
    + case when split_part(lower(coalesce(p_email, '')), '@', 1)
                ~ '^(accounting|accounts|billing|invoices?|payroll|finance|reports?|support|help|helpdesk|careers?|jobs|hr|recruit(ing|ment)?|legal|privacy|abuse|webmaster|no-?reply|donotreply|unsubscribe|newsletter|subscribe|orders?|returns|shipping|feedback|complaints?|editor|press|media|pr|marketing|ads|advertising|sponsorships?)$'
           then -60 else 0 end
      -- a named person
    + case when nullif(btrim(coalesce(p_name, '')), '') is not null then 40 else 0 end
      -- a decision-maker's role
    + case when coalesce(p_role, '') ~* '(founder|owner|ceo|chief executive|president|managing director|executive producer|head of|partner|principal|director)'
           then 20 else 0 end
      -- a person's own mailbox rather than a shared inbox
    + case when split_part(lower(coalesce(p_email, '')), '@', 1)
                !~ '^(info|hello|hi|hey|contact|contactus|office|studio|team|enquiries|inquiries|enquiry|inquiry|general|mail|business|partnerships?|collab|collabs|work|connect|reach|production|productions|producers?|sales|bookings?|admin)$'
           then 15 else 0 end
      -- a shared inbox that is at least meant for this
    + case when split_part(lower(coalesce(p_email, '')), '@', 1)
                ~ '^(partnerships?|business|collab|collabs|hello|contact|info)$' then 5 else 0 end
      -- at the company's own domain
    + case when p_domain is not null and lower(split_part(coalesce(p_email, ''), '@', 2)) in (lower(p_domain), 'www.' || lower(p_domain))
           then 5 else 0 end
      -- a free mailbox when the company has a domain
    + case when lower(split_part(coalesce(p_email, ''), '@', 2))
                in ('gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com', 'rediffmail.com', 'aol.com')
           then -5 else 0 end
$$;

create or replace function contact_source_bonus(p_entity uuid, p_source text)
returns integer language sql stable as $$
  select case
           when not coalesce((select (s.config->'enrichment'->>'prefer_site_contacts')::boolean
                                from entities e join segments s on s.id = e.segment_id where e.id = p_entity), false)
             then 0
           when coalesce(p_source, '') in ('site_scrape', 'pool:site_scrape') then 40
           when coalesce(p_source, '') in ('podcast_rss', 'youtube_description') then -10
           else 0
         end
$$;

create or replace function refresh_primary_contacts(p_segment_slug text default null)
returns integer language plpgsql as $$
declare
  n integer;
begin
  with ranked as (
    select c.id, c.entity_id, contact_allowed(c.entity_id,c.source,c.verifier,c.email_status) as allowed,
           row_number() over (partition by c.entity_id
                              order by contact_allowed(c.entity_id,c.source,c.verifier,c.email_status) desc,
                                       contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain)
                                         + contact_source_bonus(c.entity_id, c.source) desc,
                                       c.created_at, c.id) as pos
    from contacts c
    join entities e on e.id = c.entity_id
    where p_segment_slug is null
       or e.segment_id = (select id from segments where slug = p_segment_slug)
  ),
  changed as (
    update contacts c
       set is_primary = (r.pos = 1 and r.allowed), updated_at = now()
      from ranked r
     where r.id = c.id and c.is_primary is distinct from (r.pos = 1 and r.allowed)
    returning c.entity_id
  )
  select count(distinct entity_id) into n from changed;
  return n;
end $$;

do $$ begin
  raise notice 'PASS 47_clipping_leads: feed-only addresses unusable, site addresses preferred where configured';
end $$;
