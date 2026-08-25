-- 10_ENRICH_TEMPLATE.SQL
-- P10 -- hand-enrichment via the Apollo web app.
--
-- This sitting is not just data entry. It IS the human baseline that
-- **Checkpoint 2 (P17)** measures the Apollo API against: contact-find rate,
-- role accuracy, email validity, and the miss rate on 2-10-person shops. Do it
-- carefully, because "the API found 60% of what a human found" is only a
-- meaningful sentence if the human half was done properly.
--
----------------------------------------------------------------------
-- THE HELPER YOU WILL ACTUALLY USE
----------------------------------------------------------------------
-- `set_scoring_input()` does two things that must happen together: it writes
-- the value, AND it removes the key from `unverified_inputs`. That second part
-- is easy to forget and expensive to get wrong -- the promote/merge step at P9
-- treats anything still listed there as overwritable by a later connector. Set
-- a value by hand without clearing the flag and a future News RSS run can
-- quietly overwrite your research with its own guess.
--
-- Run the CREATE FUNCTION block once; then use the function for every input.

create or replace function set_scoring_input(
    p_entity uuid, p_key text, p_value jsonb
) returns void as $$
    update entities
    set metadata = jsonb_set(
            jsonb_set(metadata, array['scoring_inputs', p_key], p_value, true),
            '{unverified_inputs}',
            coalesce(
              (select jsonb_agg(v)
               from jsonb_array_elements_text(
                        coalesce(metadata->'unverified_inputs', '[]'::jsonb)) v
               where v <> p_key),
              '[]'::jsonb)
        )
    where id = p_entity;
$$ language sql;

----------------------------------------------------------------------
-- STEP 1 -- your worklist. The 12 candidates that already carry proven
-- international IP experience are the only rows where enrichment has
-- something to build on, so start there.
----------------------------------------------------------------------
select e.id,
       e.name,
       e.domain,
       e.fit_score,
       e.metadata->'discovery_raw'->'google_news_rss'->>'headline' as why_it_surfaced,
       e.source_url
from entities e
where e.segment_id = (select id from segments where slug = 'us-production-houses')
  and e.status = 'ready_for_review'
  and e.metadata->'scoring_inputs'->>'international_ip_experience' = '1'
order by e.fit_score desc, e.name;

----------------------------------------------------------------------
-- STEP 2 -- for EACH company, in the Apollo web app
----------------------------------------------------------------------
-- a) These rows have NO domain: a headline names a company, it does not link
--    to its website. So find the site first -- search the company name, confirm
--    from the article that it is the same shop -- then record it. Apollo
--    matches organisations far more reliably by domain than by name.
--
-- b) Apollo -> Search -> Companies -> filter by that domain.
-- c) Open the company -> People -> filter by the config's target_contact_roles:
--       Founder, Co-Founder, Head of Development, Development Executive,
--       Executive Producer, Head of Acquisitions, Head of Distribution
-- d) Reveal the email. Note Apollo's own verification status -- that maps to
--    `email_status` below, and it is what P17 compares the API against.
-- e) Read their actual website and fill the scoring inputs you can now judge.

----------------------------------------------------------------------
-- TEMPLATE -- copy per company. Replace the two placeholders at the top.
----------------------------------------------------------------------
do $$
declare
    v_entity uuid;
begin
    -- ⇩ the id from STEP 1, and the domain you confirmed
    select id into v_entity from entities where name = 'REPLACE COMPANY NAME'
      and segment_id = (select id from segments where slug = 'us-production-houses');

    if v_entity is null then
        raise exception 'no entity by that name -- copy it exactly from STEP 1';
    end if;

    -- 1. the domain the headline could not give us
    update entities set domain = 'REPLACE-domain.com' where id = v_entity;

    -- 2. the contact. `email_status` mirrors Apollo's verification state:
    --      'valid'      Apollo says verified
    --      'catch_all'  domain accepts anything -- deliverable but unproven
    --      'unverified' Apollo has it but has not checked
    --      'unknown'    Apollo has a person but no email
    --    If Apollo returns NOBODY at all, insert no contact row and instead
    --    record that fact -- see the no_contact_found note at the bottom. A
    --    silent gap and a confirmed miss look identical later, and P17 needs
    --    to tell them apart.
    insert into contacts (entity_id, full_name, role_title, email, email_status,
                          email_verified_at, verifier, source, is_primary)
    values (v_entity,
            'REPLACE Full Name',
            'REPLACE Role Title',
            'REPLACE email@domain.com',
            'valid',
            now(),
            'apollo_manual',
            'apollo_manual',
            true)
    on conflict do nothing;

    -- 3. reachable_decision_maker is ENGINE-set, and this is the engine.
    --    1.0 a target-role person with a valid email
    --    0.5 catch-all or role-based address (info@, hello@)
    --    0   nobody reachable
    perform set_scoring_input(v_entity, 'reachable_decision_maker', to_jsonb(1.0));

    -- 4. what you can now judge from their actual website. Set ONLY what you
    --    genuinely assessed -- every one of these is currently a defaulted 0,
    --    and leaving a default in place is more honest than a guess.
    perform set_scoring_input(v_entity, 'right_size',                to_jsonb(1.0));
    perform set_scoring_input(v_entity, 'genre_fit',                 to_jsonb(0.5));
    perform set_scoring_input(v_entity, 'distribution_relationship', to_jsonb(1.0));
    perform set_scoring_input(v_entity, 'collaboration_openness',    to_jsonb(0.5));
    perform set_scoring_input(v_entity, 'client_work_dominance',     to_jsonb(0.0));
    perform set_scoring_input(v_entity, 'revenue_above_cap',         to_jsonb(0.0));

    -- 5. the sentence you will read at review, when the company has faded
    update entities
    set metadata = jsonb_set(metadata, '{why_fit}',
                             to_jsonb('REPLACE one or two sentences on why this is a plausible co-pro partner'::text)),
        status = 'enriched'
    where id = v_entity;

    raise notice 'enriched %', v_entity;
end $$;

----------------------------------------------------------------------
-- WHEN APOLLO FINDS NOBODY -- record it, do not skip it
----------------------------------------------------------------------
-- update entities
-- set metadata = jsonb_set(metadata, '{enrichment_result}', '"no_contact_found"'),
--     status = 'enriched'
-- where id = '<uuid>';
-- select set_scoring_input('<uuid>'::uuid, 'reachable_decision_maker', to_jsonb(0.0));
--
-- A confirmed miss is a finding. P17's whole question is whether Apollo misses
-- 2-10-person shops, and it cannot be answered from rows that were quietly
-- passed over.

----------------------------------------------------------------------
-- STEP 3 -- re-score and see what the enrichment bought
----------------------------------------------------------------------
select * from score_segment('us-production-houses');

select name, fit_score,
       score_breakdown->>'criteria_known' as assessed,
       jsonb_array_length(metadata->'unverified_inputs') as still_defaulted
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'google_news_rss'
order by fit_score desc nulls last
limit 15;

----------------------------------------------------------------------
-- RECORD FOR CHECKPOINT 2 (P17). Write these into BUILD_PLAN.md now, while
-- the sitting is fresh -- they are the baseline the Apollo API is measured
-- against, and reconstructing them later is guesswork.
----------------------------------------------------------------------
select
    count(*)                                                          as attempted,
    count(*) filter (where c.id is not null)                          as contact_found,
    count(*) filter (where c.email_status = 'valid')                  as valid_email,
    round(100.0 * count(*) filter (where c.id is not null)
          / nullif(count(*), 0), 1)                                   as find_rate_pct
from entities e
left join contacts c on c.entity_id = e.id and c.is_primary
where e.segment_id = (select id from segments where slug = 'us-production-houses')
  and e.status = 'enriched';
