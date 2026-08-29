-- 04D_STRIP_THIRDPARTY_DOMAINS.SQL
--
-- WHY THIS EXISTS. A domain is only useful if it is the company's OWN site.
-- Three rows in the live pool had a domain belonging to somebody else, and two
-- of them had produced a contact to match:
--
--   Platinum Dunes  -> bloody-disgusting.com, johnsquires@bloody-disgusting.com
--   DECKER'S DREAM  -> jotform.com,           support@jotform.com
--   Witthaus Editorial -> vimeo.com
--
-- Bloody Disgusting is a horror news site that wrote ABOUT Platinum Dunes;
-- John Squires is one of its writers. JotForm is a form service whose support
-- address was scraped off an embedded form. Emailing either would be emailing
-- a stranger about a company they do not work for, and a reviewer who spots
-- one stops trusting the whole sheet.
--
-- THE DISTINCTION THAT MATTERS. A BARE platform domain is never a company's
-- site. A SUBDOMAIN of a site builder usually is:
--
--   wix.com                        -> not theirs
--   rossettiproduction.wixsite.com -> genuinely theirs, a small shop on Wix
--
-- So this matches bare hosts and known publishers only, never "<name>.host".
-- Two legitimate wixsite rows in the pool are deliberately left alone.
--
-- WHAT IT DOES. Nulls the domain, deletes any contact at that domain, and
-- clears the reachable_decision_maker those contacts earned -- then records
-- what happened so the row reads as "no site found" rather than silently
-- losing data. The company itself is kept: the name is still a real lead, it
-- just has no verified website yet.
--
-- Idempotent. Re-running changes nothing once clean.

do $$
declare
  seg uuid;
  n_dom int;
  n_con int;
begin
  select id into seg from segments where slug = 'us-production-houses';

  create temp table bad_rows on commit drop as
  select e.id, e.name, e.domain
  from entities e
  where e.segment_id = seg
    and e.domain is not null
    and (
      -- bare platform / builder / social hosts: never a company's own site
      e.domain in (
        'wix.com','squarespace.com','wordpress.com','godaddy.com','shopify.com',
        'jotform.com','linktr.ee','beacons.ai','carrd.co','weebly.com',
        'youtube.com','youtu.be','facebook.com','instagram.com','twitter.com',
        'x.com','vimeo.com','tiktok.com','linkedin.com','patreon.com',
        'substack.com','medium.com','mailchimp.com','eventbrite.com',
        'gmail.com','bit.ly','allmylinks.com','wixsite.com'
      )
      -- trade press, databases and aggregators: they write ABOUT companies
      or e.domain in (
        'bloody-disgusting.com','imdb.com','crunchbase.com','variety.com',
        'deadline.com','hollywoodreporter.com','indiewire.com','wikipedia.org',
        'productionlist.com','zoominfo.com','rocketreach.co','indeed.com',
        'glassdoor.com','dnb.com','bizapedia.com'
      )
    );

  select count(*) into n_dom from bad_rows;

  delete from contacts c
   using bad_rows b
   where c.entity_id = b.id
     and split_part(c.email, '@', 2) = b.domain;
  get diagnostics n_con = row_count;

  -- a contact that came only from the wrong site is no longer evidence
  update entities e
     set metadata = jsonb_set(
           coalesce(e.metadata, '{}'::jsonb),
           '{scoring_inputs,reachable_decision_maker}', '0'::jsonb)
    from bad_rows b
   where e.id = b.id
     and not exists (select 1 from contacts c where c.entity_id = e.id);

  update entities e
     set domain = null,
         metadata = e.metadata || jsonb_build_object(
             'rejected_domain', b.domain,
             'rejected_domain_reason',
               'third-party host: belongs to a platform or publisher, not this company',
             'site_read', null),
         updated_at = now()
    from bad_rows b
   where e.id = b.id;

  raise notice 'stripped % third-party domain(s) and % contact(s) at them',
               n_dom, n_con;
end $$;

select name, domain, metadata->>'rejected_domain' as was
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and metadata ? 'rejected_domain';
