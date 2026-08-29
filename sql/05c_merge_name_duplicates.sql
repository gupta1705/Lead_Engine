-- 05C_MERGE_NAME_DUPLICATES.SQL
--
-- INVARIANT 7 says one entity per company across sources. Two unique indexes
-- enforce most of it:
--
--   uq_entities_segment_domain          one row per domain
--   uq_entities_segment_name_nodomain   one row per name AMONG DOMAINLESS ROWS
--
-- Between them sits a gap. A row WITH a domain and a row WITHOUT one may share
-- a name, because neither index covers that pair. Four companies landed in it:
--
--   Dharma Productions   news row (no domain) + news row (dharma-production.com)
--   Angel Studios        news row (no domain) + wikidata row (with domain)
--   Searchlight Pictures news row (no domain) + wikidata row (with domain)
--
-- The cost is not cosmetic. Evidence splits across the pair: the news row
-- carries international_ip_experience, worth 30 points and the single hardest
-- signal to obtain, while the row with the domain is the only one that can be
-- site-scraped or emailed. Both rows then score mid-range and NEITHER shows
-- what the engine actually knows about that company.
--
-- WHAT THIS DOES. For each name where exactly one row has a domain:
--   * merges scoring_inputs, taking the STRONGER value per key -- evidence
--     from either source is real evidence, and 04b's defaulted 0 must never
--     beat a genuine finding
--   * moves contacts across (on conflict do nothing; the unique index on
--     entity_id+email already dedupes)
--   * unions source_history so provenance survives the merge
--   * archives the domainless row with a reason, rather than deleting it --
--     rejected and archived rows are the shield against re-discovery
--
-- LEFT ALONE ON PURPOSE: names where BOTH rows have a domain (close-up
-- productions). Two different domains may be two genuinely different shops
-- with the same name, and guessing wrong merges two real companies into one.
-- Those are flagged at the end for a human to settle.

do $$
declare
  seg uuid;
  merged int := 0;
  r record;
begin
  select id into seg from segments where slug = 'us-production-houses';

  for r in
    select lower(e.name) as nm,
           (array_agg(e.id) filter (where e.domain is not null))[1] as keep_id,
           (array_agg(e.id) filter (where e.domain is null))[1]     as drop_id
    from entities e
    where e.segment_id = seg
      and e.status in ('discovered','enriched','scored','ready_for_review')
    group by lower(e.name)
    having count(*) = 2
       and count(*) filter (where e.domain is not null) = 1
       and count(*) filter (where e.domain is null) = 1
  loop
    -- stronger-wins merge of scoring_inputs
    update entities keep
       set metadata = jsonb_set(
             keep.metadata, '{scoring_inputs}',
             (
               select coalesce(jsonb_object_agg(k, v), '{}'::jsonb)
               from (
                 -- 'stronger wins': prefer a real finding over 04b's
                 -- defaulted 0/false. There is no max() for jsonb, and
                 -- these values are a mix of numbers, strings and bools,
                 -- so rank by meaningfulness and take the first.
                 select key as k,
                        (array_agg(val order by
                           case when val::text in ('0','0.0','""','false','null')
                                then 1 else 0 end,
                           val::text desc))[1] as v
                 from (
                   select key, value as val
                     from jsonb_each(coalesce(keep.metadata->'scoring_inputs','{}'::jsonb))
                   union all
                   select key, value
                     from jsonb_each(coalesce(drop.metadata->'scoring_inputs','{}'::jsonb))
                 ) both_sides
                 group by key
               ) winner
             ))
      from entities drop
     where keep.id = r.keep_id and drop.id = r.drop_id;

    -- a key proven by either row is no longer unverified on the survivor
    update entities keep
       set metadata = jsonb_set(
             keep.metadata, '{unverified_inputs}',
             coalesce((
               select jsonb_agg(x)
               from jsonb_array_elements_text(
                      coalesce(keep.metadata->'unverified_inputs','[]'::jsonb)) t(x)
               where (keep.metadata->'scoring_inputs'->>x) is null
                  or (keep.metadata->'scoring_inputs'->>x) = '0'
             ), '[]'::jsonb))
     where keep.id = r.keep_id;

    -- provenance and the evidence payload of the row being retired
    update entities keep
       set metadata = keep.metadata || jsonb_build_object(
             'merged_from', coalesce(keep.metadata->'merged_from','[]'::jsonb)
               || jsonb_build_array(jsonb_build_object(
                    'source', drop.source,
                    'source_url', drop.source_url,
                    'discovery_raw', drop.metadata->'discovery_raw')),
             'why_fit', coalesce(keep.metadata->>'why_fit', drop.metadata->>'why_fit')),
           updated_at = now()
      from entities drop
     where keep.id = r.keep_id and drop.id = r.drop_id;

    update contacts set entity_id = r.keep_id
     where entity_id = r.drop_id
       and not exists (select 1 from contacts c2
                        where c2.entity_id = r.keep_id
                          and lower(c2.email) = lower(contacts.email));

    delete from contacts where entity_id = r.drop_id;

    update entities
       set status = 'archived',
           status_reason = 'Merged into the row carrying this company''s domain '
                           '(invariant 7: one entity per company)',
           status_changed_at = now()
     where id = r.drop_id;

    merged := merged + 1;
  end loop;

  raise notice 'merged % duplicate name pair(s)', merged;
end $$;

-- Names where BOTH rows have a domain: not safe to merge automatically.
select 'NEEDS A HUMAN: same name, two domains' as note,
       lower(name) as company, string_agg(domain, ' | ') as domains
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status in ('discovered','enriched','scored','ready_for_review')
  and domain is not null
group by lower(name) having count(*) > 1;
