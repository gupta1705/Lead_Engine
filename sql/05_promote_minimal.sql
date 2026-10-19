-- 05_PROMOTE_MINIMAL.SQL
-- P9 -- move candidates out of the staging inbox into `entities`.
--
-- RUN ORDER. This is a three-step sequence and the order is load-bearing:
--     1. sql/05a_self_exclusion.sql   (never promote TVF or an affiliate)
--     2. sql/05_promote_minimal.sql   (this file)
--     3. sql/04b_zero_unverified.sql  (unverified inputs become explicit zeros)
--   then score. Running 04b before promote would leave the newly promoted rows
--   scored on partial denominators, which is the exact per-source distortion
--   Checkpoint 1 exists to detect.
--
----------------------------------------------------------------------
-- DEVIATION FROM THE PLAN, AND WHY
----------------------------------------------------------------------
-- BUILD_PLAN specifies "domain branch only, no gates yet" for this rung, with
-- the domainless branch deferred to P14. Against the real harvest that would
-- promote **8 of 213 rows**: YouTube extracted a website for 8 channels, and
-- News RSS extracts none by design (a headline does not carry a URL for the
-- company it names -- the domain arrives at Apollo enrichment, P16).
--
-- A promote step that moves 4% of the pool leaves Checkpoint 1 with nothing to
-- measure. So both branches are implemented here. This is not the hard part of
-- P14: the schema already enforces both uniqueness rules --
--   uq_entities_segment_domain          (segment_id, domain) where domain is not null
--   uq_entities_segment_name_nodomain   (segment_id, lower(name)) where domain is null
-- so the domainless branch is a second matching key, not new machinery. What
-- P14 still owns is the cross-case pre-check and the harder merge edges.
--
----------------------------------------------------------------------
-- INVARIANTS THIS FILE ENFORCES
----------------------------------------------------------------------
-- 4. `rejected` entities are permanently shielded from re-import. A staging row
--    matching a rejected entity is marked `skipped_rejected` and never touches
--    it. Without this, every connector re-run would resurrect companies a human
--    already refused, and the rejection reasons -- the data P11 tunes the rubric
--    from -- would be silently re-litigated.
--
-- 7. Same company, different source, one row. With two connectors live and
--    three more coming, the same company legitimately appears more than once.
--    Matching is by normalized domain first, then by lowercased name.
--
----------------------------------------------------------------------
-- THE MERGE RULE THAT MATTERS
----------------------------------------------------------------------
-- "Existing values kept unless empty" is WRONG once 04b runs, because a
-- defaulted 0 is not empty. Concretely: YouTube finds a company and
-- `international_ip_experience` is defaulted to 0. News RSS then finds the same
-- company with a trade headline proving a format deal -- a real 1, worth 30
-- points. A naive merge keeps the 0 and throws away the evidence.
--
-- So the rule is: **a key listed in the existing row's `unverified_inputs` is
-- overwritable by real evidence; anything else is kept.** That list exists
-- precisely to make this decidable, and this is the step it was written for.
--
-- Re-run = no-op: a second run finds every staging row already `imported`.

----------------------------------------------------------------------
-- STEP 0 -- domain normalization. Same company, three spellings
-- (HTTP://WWW.Foo.com/about, foo.com, www.foo.com) must become one key.
----------------------------------------------------------------------
create or replace function normalize_domain(p text) returns text as $$
  select nullif(
    regexp_replace(
      regexp_replace(
        regexp_replace(lower(btrim(coalesce(p, ''))),
          '^[a-z][a-z0-9+.-]*://', ''),    -- strip scheme
        '^www\.', ''),                      -- strip leading www.
      '[/:?#].*$', ''),                     -- strip path, port, query, fragment
    '');
$$ language sql immutable;

----------------------------------------------------------------------
-- STEP 1 -- what is about to happen. Read this before running step 2.
----------------------------------------------------------------------
with pending as (
    select s.*, normalize_domain(s.domain) as nd
    from staging_candidates s
    where s.imported = false
      and not exists (select 1 from segments policy where policy.id = s.segment_id
          and policy.config->'sourcing'->>'provider' = 'apollo'
          and not (coalesce(policy.config->'sourcing'->'allowed_sources', '[]'::jsonb) ? s.source))
      and s.segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
),
matched as (
    select p.id,
           p.source,
           e.id as entity_id,
           e.status as entity_status
    from pending p
    left join entities e
      on e.segment_id = p.segment_id
     and (
           (p.nd is not null and normalize_domain(e.domain) = p.nd)
        or (p.nd is null and e.domain is null and lower(e.name) = lower(p.name))
         )
)
select
    source,
    count(*) filter (where entity_id is null)                                as will_insert,
    count(*) filter (where entity_id is not null
                       and entity_status = 'rejected')                       as will_skip_rejected,
    count(*) filter (where entity_id is not null
                       and entity_status <> 'rejected')                      as will_merge
from matched
group by source
order by source;

----------------------------------------------------------------------
-- STEP 1b -- SNAPSHOT which entities existed BEFORE this run.
--
-- Not optional bookkeeping. The first version labelled staging rows in a final
-- step that re-checked `entities` -- by which point step 2a had already created
-- them, so all 213 genuine inserts were recorded as `merged_duplicate`. The
-- counts were right and the audit trail was a lie, which is the worse of the
-- two failures: `import_result` is how anyone later reconstructs what a
-- connector actually contributed.
--
-- Dropped automatically at commit.
----------------------------------------------------------------------
create temporary table promote_preexisting on commit drop as
select
    coalesce(normalize_domain(e.domain), lower(e.name)) as match_key,
    e.id   as entity_id,
    e.status
from entities e
where e.segment_id = (select id from segments where slug = current_setting('tvf.segment', true));

----------------------------------------------------------------------
-- STEP 2a -- INSERT the genuinely new ones.
-- `on conflict do nothing` is the idempotency guarantee: a second run, or two
-- staging rows for the same company in one batch, both land as no-ops rather
-- than errors.
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
select distinct on (coalesce(normalize_domain(s.domain), lower(s.name)))
    s.segment_id,
    s.name,
    normalize_domain(s.domain),
    s.source,
    s.source_url,
    'discovered',
    jsonb_build_object(
        'scoring_inputs', coalesce(s.raw->'scoring_inputs', '{}'::jsonb),
        'source_history', jsonb_build_array(
            jsonb_build_object(
                'source', s.source,
                'source_url', s.source_url,
                'seen_at', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SSZ')
            )),
        'discovery_raw', jsonb_build_object(s.source, s.raw - 'scoring_inputs')
    )
from staging_candidates s
where s.imported = false
      and not exists (select 1 from segments policy where policy.id = s.segment_id
          and policy.config->'sourcing'->>'provider' = 'apollo'
          and not (coalesce(policy.config->'sourcing'->'allowed_sources', '[]'::jsonb) ? s.source))
  and s.segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
  and not exists (
        select 1 from entities e
        where e.segment_id = s.segment_id
          and (
                (normalize_domain(s.domain) is not null
                   and normalize_domain(e.domain) = normalize_domain(s.domain))
             or (normalize_domain(s.domain) is null and e.domain is null
                   and lower(e.name) = lower(s.name))
              )
      )
  -- THE NAME-LEVEL SHIELD (added 2026-08-30 after a live leak). The matching
  -- above pairs a staging row with an entity by domain, or by name AMONG
  -- DOMAINLESS rows -- which leaves two ways back in for a company already
  -- ruled out. Both happened on the first post-gate harvest:
  --   * archived Nordisk Film HAS a domain, so a fresh DOMAINLESS "Nordisk
  --     Film" staging row matched nothing and inserted as a second entity;
  --   * archived Platinum Dunes had its bogus domain stripped, so a fresh row
  --     carrying that same bogus domain matched nothing and re-imported it.
  -- An archived or rejected company is out of the segment BY NAME, whatever
  -- domain a connector attaches to it this week. One company, one verdict.
  and not exists (
        select 1 from entities shield
        where shield.segment_id = s.segment_id
          and shield.status in ('rejected', 'archived')
          and lower(shield.name) = lower(s.name)
      )
order by coalesce(normalize_domain(s.domain), lower(s.name)), s.created_at
on conflict do nothing;

----------------------------------------------------------------------
-- STEP 2b -- MERGE into entities that already exist and are still in play.
-- Never touches a rejected row (invariant 4) or one already dispositioned.
----------------------------------------------------------------------
with pending as (
    select s.*, normalize_domain(s.domain) as nd
    from staging_candidates s
    where s.imported = false
      and not exists (select 1 from segments policy where policy.id = s.segment_id
          and policy.config->'sourcing'->>'provider' = 'apollo'
          and not (coalesce(policy.config->'sourcing'->'allowed_sources', '[]'::jsonb) ? s.source))
      and s.segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
),
pairs as (
    select e.id as entity_id, p.*
    from pending p
    join entities e
      on e.segment_id = p.segment_id
     and (
           (p.nd is not null and normalize_domain(e.domain) = p.nd)
        or (p.nd is null and e.domain is null and lower(e.name) = lower(p.name))
         )
    where e.status not in ('rejected', 'contacted', 'in_conversation', 'archived')
)
update entities e
set metadata =
        jsonb_set(
            jsonb_set(
                e.metadata,
                '{scoring_inputs}',
                -- existing first, then the incoming values RESTRICTED to keys
                -- the existing row admits it never verified. `||` lets the
                -- right side win, so real evidence replaces a defaulted 0 and
                -- nothing else is disturbed.
                coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)
                || (
                    select coalesce(jsonb_object_agg(k.key, k.value), '{}'::jsonb)
                    from jsonb_each(coalesce(pairs.raw->'scoring_inputs', '{}'::jsonb)) k
                    where not (coalesce(e.metadata->'scoring_inputs', '{}'::jsonb) ? k.key)
                       or coalesce(e.metadata->'unverified_inputs', '[]'::jsonb) ? k.key
                   )
            ),
            '{source_history}',
            coalesce(e.metadata->'source_history', '[]'::jsonb)
            || jsonb_build_array(jsonb_build_object(
                   'source', pairs.source,
                   'source_url', pairs.source_url,
                   'seen_at', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SSZ')))
        )
        -- keep each source's raw payload under its own key, so a reviewer can
        -- see the YouTube channel AND the trade headline for one company
        || jsonb_build_object('discovery_raw',
               coalesce(e.metadata->'discovery_raw', '{}'::jsonb)
               || jsonb_build_object(pairs.source, pairs.raw - 'scoring_inputs'))
from pairs
where e.id = pairs.entity_id;

----------------------------------------------------------------------
-- STEP 3 -- mark every staging row with what happened to it.
----------------------------------------------------------------------
with pending as (
    select s.id, s.name, s.segment_id,
           coalesce(normalize_domain(s.domain), lower(s.name)) as match_key
    from staging_candidates s
    where s.imported = false
      and not exists (select 1 from segments policy where policy.id = s.segment_id
          and policy.config->'sourcing'->>'provider' = 'apollo'
          and not (coalesce(policy.config->'sourcing'->'allowed_sources', '[]'::jsonb) ? s.source))
      and s.segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
),
outcome as (
    -- Compared against the PRE-RUN snapshot, so an entity this run created is
    -- correctly an insert rather than a match against itself.
    select p.id,
           case
             -- the name-level shield in step 2a: a staging row whose NAME
             -- matches an archived/rejected company was not inserted, whatever
             -- its domain says. Label it so the audit trail explains the gap.
             when exists (select 1 from entities sh
                          where sh.segment_id = p.segment_id
                            and sh.status in ('rejected','archived')
                            and lower(sh.name) = lower(p.name))
                  and x.entity_id is null        then 'skipped_shielded_name'
             when x.entity_id is null            then 'inserted'
             when x.status = 'rejected'          then 'skipped_rejected'
             else                                     'merged_duplicate'
           end as result
    from pending p
    left join promote_preexisting x on x.match_key = p.match_key
)
update staging_candidates s
set imported = true,
    import_result = o.result
from outcome o
where s.id = o.id;

----------------------------------------------------------------------
-- CONFIRM
----------------------------------------------------------------------
select source, count(*) as entities, count(domain) as with_domain
from entities
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
group by source
order by source;

select import_result, count(*)
from staging_candidates
where segment_id = (select id from segments where slug = current_setting('tvf.segment', true))
group by import_result
order by import_result;

select count(*) as still_unimported
from staging_candidates
where imported = false
  and segment_id = (select id from segments where slug = current_setting('tvf.segment', true));
-- Expect 0. Re-running this whole file should then change nothing at all.
