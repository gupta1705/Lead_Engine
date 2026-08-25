-- 05_TEST_PROMOTE_MERGE.SQL
-- Proves the one rule in 05_promote_minimal.sql that is easy to get wrong and
-- impossible to notice when it is wrong.
--
-- THE SCENARIO. A company is found twice, by two connectors, in that order:
--   1. YouTube finds it. The connector cannot know whether it has ever adapted
--      foreign IP, so it leaves `international_ip_experience` absent. 04b then
--      writes an explicit 0 and records the key in `unverified_inputs`.
--   2. News RSS finds the same company later, with a trade headline announcing
--      a format deal. That is a real 1, worth 30 points -- the single heaviest
--      criterion in the rubric.
--
-- A merge rule of "keep existing unless empty" silently keeps the 0, because a
-- defaulted 0 is not empty. Nothing errors. The company just scores 30 points
-- lower than the evidence says it should, forever, and no one can tell from
-- looking at it. That is why this test exists and why it asserts rather than
-- prints: a wrong answer here is invisible in every other view of the data.
--
-- Self-cleaning: removes its own fixtures on both the pass and fail paths.
-- Safe to run against the live database, and safe to re-run.

do $$
declare
    v_segment uuid;
    v_entity  uuid;
    v_ip      text;
    v_genre   text;
    v_sources int;
begin
    select id into v_segment from segments where slug = 'us-production-houses';

    ------------------------------------------------------------------
    -- Clean up anything a previous aborted run left behind
    ------------------------------------------------------------------
    delete from staging_candidates where name = '__merge_test_co__';
    delete from entities where name = '__merge_test_co__';

    ------------------------------------------------------------------
    -- ARRANGE: the entity as it looks after YouTube + 04b.
    -- genre_fit 0.5 is REAL evidence (a genre query matched the channel).
    -- international_ip_experience 0 is a DEFAULT, and says so.
    ------------------------------------------------------------------
    insert into entities (segment_id, name, domain, source, source_url, status, metadata)
    values (v_segment, '__merge_test_co__', null, 'youtube_api',
            'https://youtube.com/channel/TEST', 'discovered',
            jsonb_build_object(
              'scoring_inputs', jsonb_build_object(
                  'international_ip_experience', 0,
                  'genre_fit', 0.5,
                  'has_reachable_presence', true),
              'unverified_inputs', jsonb_build_array('international_ip_experience'),
              'source_history', jsonb_build_array(
                  jsonb_build_object('source', 'youtube_api'))))
    returning id into v_entity;

    -- News RSS finds the same company with a format-deal headline.
    insert into staging_candidates (segment_id, name, domain, source, source_url, raw)
    values (v_segment, '__merge_test_co__', null, 'google_news_rss',
            'https://variety.com/test-format-deal',
            jsonb_build_object(
              'headline', 'Merge Test Co Acquires Format Rights To Korean Hit',
              'ip_format_phrases', jsonb_build_array('format rights'),
              'scoring_inputs', jsonb_build_object(
                  'international_ip_experience', 1,
                  'genre_fit', 1)));

    ------------------------------------------------------------------
    -- ACT: the merge, copied verbatim from 05_promote_minimal.sql STEP 2b.
    ------------------------------------------------------------------
    update entities e
    set metadata =
            jsonb_set(
                jsonb_set(
                    e.metadata,
                    '{scoring_inputs}',
                    coalesce(e.metadata->'scoring_inputs', '{}'::jsonb)
                    || (
                        select coalesce(jsonb_object_agg(k.key, k.value), '{}'::jsonb)
                        from jsonb_each(coalesce(s.raw->'scoring_inputs', '{}'::jsonb)) k
                        where not (coalesce(e.metadata->'scoring_inputs', '{}'::jsonb) ? k.key)
                           or coalesce(e.metadata->'unverified_inputs', '[]'::jsonb) ? k.key
                       )
                ),
                '{source_history}',
                coalesce(e.metadata->'source_history', '[]'::jsonb)
                || jsonb_build_array(jsonb_build_object('source', s.source))
            )
    from staging_candidates s
    where s.name = '__merge_test_co__'
      and e.id = v_entity;

    ------------------------------------------------------------------
    -- ASSERT
    ------------------------------------------------------------------
    select e.metadata->'scoring_inputs'->>'international_ip_experience',
           e.metadata->'scoring_inputs'->>'genre_fit',
           jsonb_array_length(e.metadata->'source_history')
      into v_ip, v_genre, v_sources
      from entities e where e.id = v_entity;

    if v_ip is distinct from '1' then
        raise exception
          'FAIL: real evidence lost. international_ip_experience is % but News RSS proved 1. '
          'A defaulted 0 was treated as a real value and 30 points vanished silently.', v_ip;
    end if;
    raise notice 'PASS 1: a defaulted 0 was overwritten by proven evidence (international_ip_experience = 1)';

    if v_genre is distinct from '0.5' then
        raise exception
          'FAIL: genre_fit is % -- expected 0.5 kept. It was REAL evidence from the '
          'YouTube query match and was not in unverified_inputs, so the incoming 1 '
          'must not overwrite it. Merging everything is as wrong as merging nothing.', v_genre;
    end if;
    raise notice 'PASS 2: verified evidence was NOT overwritten (genre_fit stayed 0.5)';

    if v_sources <> 2 then
        raise exception 'FAIL: source_history has % entries, expected 2 (invariant 7: '
                        'one row, both sources visible in its history)', v_sources;
    end if;
    raise notice 'PASS 3: both sources recorded in source_history (invariant 7)';

    ------------------------------------------------------------------
    -- CLEAN UP
    ------------------------------------------------------------------
    delete from staging_candidates where name = '__merge_test_co__';
    delete from entities where id = v_entity;
    raise notice 'ALL MERGE TESTS PASSED -- fixtures removed';

exception when others then
    -- never leave test rows behind, even on failure
    delete from staging_candidates where name = '__merge_test_co__';
    delete from entities where name = '__merge_test_co__';
    raise;
end $$;

select 'merge semantics verified' as result,
       (select count(*) from entities where name = '__merge_test_co__') as leftover_entities,
       (select count(*) from staging_candidates where name = '__merge_test_co__') as leftover_staging;
