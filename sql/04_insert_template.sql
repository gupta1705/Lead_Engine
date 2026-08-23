-- 04_INSERT_TEMPLATE.SQL
-- P1 — Hand-fed candidates.
-- Copy the TEMPLATE block below once per company (~8 times), fill it in from
-- the company's real website/YouTube/socials, and run each INSERT in the
-- Supabase SQL editor. A worked EXAMPLE follows the template so you can see
-- realistic values in place.
--
-- THE ONE RULE THAT MATTERS (invariant 1, null != zero):
--   - If you genuinely could not find evidence either way for a scoring
--     input, DELETE that key from the JSON entirely. Do not set it to 0,
--     and do not set it to JSON null either -- both a missing key and an
--     explicit null are treated as "not yet assessed" by the scorer (06_score.sql),
--     but deleting the key is the clean, unambiguous way to say it.
--   - Only write 0 when you looked and confirmed there's genuinely no
--     evidence (e.g. you read their /work page and it's 100% owned IP, so
--     client_work_dominance = 0). 0 means "checked, no", not "didn't check".
--   - Values for rubric/modifier inputs are always 0, 0.5, or 1 (partial
--     credit is allowed per the config's guidance text for that criterion).
--
-- Field reference (from config/segment.us-production-houses.json):
--   rubric inputs         -> metadata.scoring_inputs.{international_ip_experience,
--                             genre_fit, distribution_relationship, right_size,
--                             reachable_decision_maker, collaboration_openness}
--   score_modifiers inputs -> metadata.scoring_inputs.{client_work_dominance,
--                             india_diaspora_affinity, revenue_above_cap}
--   gate inputs            -> metadata.scoring_inputs.{geography_signal,
--                             major_or_oversized_signal, has_reachable_presence,
--                             activity_signal}   (not scored, just informational
--                             at this stage -- gates don't fire until P9/P13)
--   other metadata_fields  -> subtype, hq_city, hq_state, team_size_estimate,
--                             genres, notable_credits, format_deals,
--                             platform_relationships, why_fit

----------------------------------------------------------------------
-- TEMPLATE -- copy this block, fill it in, delete any scoring_inputs
-- key you can't honestly assess, then run.
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'COMPANY NAME',
  'companydomain.com',
  'manual_p1',
  'https://companydomain.com',
  'discovered',
  '{
    "subtype": "digital",
    "hq_city": "CITY",
    "hq_state": "STATE",
    "team_size_estimate": null,
    "genres": ["comedy"],
    "notable_credits": [],
    "format_deals": [],
    "platform_relationships": [],
    "why_fit": "One or two sentences on why this company is a plausible co-pro/format partner.",
    "scoring_inputs": {
      "international_ip_experience": 0,
      "genre_fit": 1,
      "distribution_relationship": 0.5,
      "right_size": 1,
      "collaboration_openness": 0,
      "client_work_dominance": 0,
      "india_diaspora_affinity": 0,
      "geography_signal": "us",
      "has_reachable_presence": true
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- WORKED EXAMPLE -- a filled-in, realistic row. Notice:
--   - reachable_decision_maker and revenue_above_cap and activity_signal
--     are DELETED, not set to 0/false -- genuinely not assessed yet
--     (reachable_decision_maker gets auto-set once a contact exists;
--     revenue_above_cap needs a third-party lookup this rung doesn't do;
--     activity_signal needs an upload-recency check this rung doesn't do).
--   - major_or_oversized_signal is also omitted: nothing suggested it's
--     oversized, but that's an "unknown", not a confirmed "false".
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Lantern Row Media',
  'lanternrowmedia.com',
  'manual_p1',
  'https://lanternrowmedia.com',
  'discovered',
  '{
    "subtype": "digital",
    "hq_city": "Austin",
    "hq_state": "TX",
    "team_size_estimate": "6-10",
    "genres": ["workplace comedy", "slice-of-life"],
    "notable_credits": ["Office Hours (web series, 3 seasons)"],
    "format_deals": [],
    "platform_relationships": ["recurring YouTube originals slot"],
    "why_fit": "Small, founder-led comedy studio with a workplace-comedy focus and a public partner-inquiries page -- squarely in TVF genre lanes.",
    "scoring_inputs": {
      "international_ip_experience": 0,
      "genre_fit": 1,
      "distribution_relationship": 0.5,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0,
      "india_diaspora_affinity": 0,
      "geography_signal": "us",
      "has_reachable_presence": true
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- CHECK 1: what landed. One row per company. (keys_assessed uses a scalar
-- subquery because jsonb_object_keys is set-returning -- put it directly in
-- the select list and it multiplies your rows instead of counting them.)
----------------------------------------------------------------------
select
  name,
  domain,
  status,
  (select count(*)
     from jsonb_object_keys(coalesce(metadata->'scoring_inputs', '{}'::jsonb))
  ) as keys_assessed,
  metadata->'scoring_inputs' as scoring_inputs
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1'
order by name;

----------------------------------------------------------------------
-- CHECK 2: THE ONE THAT MATTERS -- a config-driven audit of what you typed.
--
-- Every problem this finds is a SILENT one. Invariant 1 (null != zero) means
-- an unassessed key and a mistyped key look identical to the scorer: both read
-- as "never assessed", neither raises an error, and the score comes out looking
-- perfectly reasonable while quietly ignoring a criterion you believed you had
-- filled in. This query is the only thing standing between a stray keystroke
-- and a rubric checkpoint (P11) built on numbers that were never what you meant.
--
-- WANT: zero rows. Any row is something to fix before running P2.
----------------------------------------------------------------------
with seg as (
  select id, config from segments where slug = 'us-production-houses'
),
-- every scoring_inputs key the config actually defines, plus its section:
-- rubric/modifier keys are numeric (0 / 0.5 / 1), gate keys are strings or
-- booleans, so the rules below differ per section.
known as (
  select split_part(x.item->>'input', '.', 3) as input_key,
         x.section
  from seg
  cross join lateral (
    select 'rubric'   as section, jsonb_array_elements(seg.config->'rubric')           as item
    union all
    select 'modifier',            jsonb_array_elements(seg.config->'score_modifiers')
    union all
    select 'gate',                jsonb_array_elements(seg.config->'gates')
  ) x
),
-- every key/value pair actually typed into a P1 row
entered as (
  select e.id, e.name, kv.key, kv.value
  from entities e
  cross join lateral jsonb_each(coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)) kv
  where e.segment_id = (select id from seg)
    and e.source = 'manual_p1'
),
rows_ as (
  select e.id, e.name, e.domain, e.metadata
  from entities e
  where e.segment_id = (select id from seg)
    and e.source = 'manual_p1'
)
select * from (
  -- (a) a key the config has never heard of -- nearly always a typo
  select en.name, 'unknown scoring_inputs key' as issue,
         en.key || ' = ' || en.value::text as detail
  from entered en
  where en.key not in (select input_key from known)

  union all
  -- (b) explicit JSON null: means the same as deleting the key, but reads
  --     ambiguously to a human. Delete the key instead (see the rule up top).
  select en.name, 'key is explicit null -- delete the key instead',
         en.key
  from entered en
  where jsonb_typeof(en.value) = 'null'

  union all
  -- (c) a rubric/modifier input that is not a number
  select en.name, 'rubric/modifier value is not a number',
         en.key || ' = ' || en.value::text
  from entered en
  join known k on k.input_key = en.key
  where k.section in ('rubric', 'modifier')
    and jsonb_typeof(en.value) not in ('number', 'null')

  union all
  -- (d) a rubric/modifier input outside the allowed 0 / 0.5 / 1
  select en.name, 'rubric/modifier value outside 0 / 0.5 / 1',
         en.key || ' = ' || en.value::text
  from entered en
  join known k on k.input_key = en.key
  where k.section in ('rubric', 'modifier')
    and jsonb_typeof(en.value) = 'number'
    and (en.value #>> '{}')::numeric not in (0, 0.5, 1)

  union all
  -- (e) reachable_decision_maker is ENGINE-set, from a verified contact at
  --     P10/P16 -- not reviewer-set. Filling it by hand at P1 inflates the
  --     score with a signal no contact record backs up.
  select en.name, 'reachable_decision_maker set by hand -- leave it to the engine',
         en.value::text
  from entered en
  where en.key = 'reachable_decision_maker'

  union all
  -- (f) nothing assessed at all -- P2 withholds a score entirely for this row
  select r.name, 'no scoring_inputs at all -- P2 will leave fit_score NULL', ''
  from rows_ r
  where (select count(*)
           from jsonb_object_keys(coalesce(r.metadata->'scoring_inputs', '{}'::jsonb))
        ) = 0

  union all
  -- (g) why_fit is the sentence actually read at review (P3). Blank now means
  --     a blank card later, once the company has faded from memory.
  select r.name, 'why_fit missing or empty', ''
  from rows_ r
  where coalesce(trim(r.metadata->>'why_fit'), '') = ''

  union all
  -- (h) no domain: legal (AICP rows land this way at P8) but at P1 it is
  --     nearly always an omission worth a second look
  select r.name, 'no domain -- allowed, but unusual for a hand-entered row', ''
  from rows_ r
  where coalesce(trim(r.domain), '') = ''
) issues
order by name, issue;

----------------------------------------------------------------------
-- CHECK 3: coverage. Which criteria did you actually assess, across all 8?
-- A criterion assessed on 1 of 8 companies cannot tell you anything at the
-- P11 rubric checkpoint. This is the early warning for that.
----------------------------------------------------------------------
select
  k.section,
  k.input_key,
  count(en.id)                                   as companies_assessed,
  (select count(*) from entities e
    where e.segment_id = (select id from segments where slug = 'us-production-houses')
      and e.source = 'manual_p1')                as companies_total
from (
  select split_part(x.item->>'input', '.', 3) as input_key, x.section
  from segments s
  cross join lateral (
    select 'rubric' as section, jsonb_array_elements(s.config->'rubric')          as item
    union all
    select 'modifier',          jsonb_array_elements(s.config->'score_modifiers')
    union all
    select 'gate',              jsonb_array_elements(s.config->'gates')
  ) x
  where s.slug = 'us-production-houses'
) k
left join (
  select e.id, kv.key
  from entities e
  cross join lateral jsonb_each(coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)) kv
  where e.segment_id = (select id from segments where slug = 'us-production-houses')
    and e.source = 'manual_p1'
    and jsonb_typeof(kv.value) <> 'null'
) en on en.key = k.input_key
group by k.section, k.input_key
order by k.section, companies_assessed desc, k.input_key;
