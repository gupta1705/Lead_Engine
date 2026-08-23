-- 02_SMOKE_TEST.SQL
-- Proves the schema's guarantees actually fire. Self-checking:
--   - RAISE NOTICE on each pass
--   - RAISE EXCEPTION (aborts the whole script) on the first failure
--   - deletes all its own test data, leaving 0 rows behind
-- Safe to run repeatedly. Run the whole file in the Supabase SQL editor.
--
-- Note on now(): inside one transaction now() is frozen to the transaction's
-- start time, so we can't prove a trigger "fired" by watching the clock move.
-- Instead each trigger test writes a fake OLD timestamp (year 2000) and checks
-- whether the trigger OVERRODE it. Overridden = trigger fired.

DO $$
DECLARE
    v_segment_id   UUID;
    v_entity_id    UUID;
    v_ts           TIMESTAMPTZ;
    v_old          CONSTANT TIMESTAMPTZ := '2000-01-01 00:00:00+00';
    v_contacts_left INT;
BEGIN
    ----------------------------------------------------------------
    -- Defensive pre-clean (in case a prior aborted run left rows)
    ----------------------------------------------------------------
    DELETE FROM entities WHERE source = 'smoke';
    DELETE FROM segments WHERE slug = '__smoketest__';

    ----------------------------------------------------------------
    -- SETUP: a throwaway segment + entity (with domain) + contact
    ----------------------------------------------------------------
    INSERT INTO segments (slug, name, entity_type)
    VALUES ('__smoketest__', 'Smoke Test', 'test')
    RETURNING id INTO v_segment_id;

    INSERT INTO entities (segment_id, name, domain, source, status)
    VALUES (v_segment_id, 'Test Co', 'testco.com', 'smoke', 'discovered')
    RETURNING id INTO v_entity_id;

    INSERT INTO contacts (entity_id, full_name, email, is_primary)
    VALUES (v_entity_id, 'Jane Test', 'jane@testco.com', TRUE);

    ----------------------------------------------------------------
    -- TEST 1: updated_at trigger fires on UPDATE (entities)
    ----------------------------------------------------------------
    UPDATE entities SET updated_at = v_old, name = 'Test Co v2'
    WHERE id = v_entity_id
    RETURNING updated_at INTO v_ts;
    IF v_ts = v_old THEN
        RAISE EXCEPTION 'FAIL: updated_at trigger did not fire (kept the fake 2000 value)';
    END IF;
    RAISE NOTICE 'PASS 1: updated_at trigger fires';

    ----------------------------------------------------------------
    -- TEST 2a: status_changed_at trigger fires WHEN status changes
    ----------------------------------------------------------------
    UPDATE entities SET status_changed_at = v_old, status = 'enriched'
    WHERE id = v_entity_id
    RETURNING status_changed_at INTO v_ts;
    IF v_ts = v_old THEN
        RAISE EXCEPTION 'FAIL: status_changed_at did not fire on a real status change';
    END IF;
    RAISE NOTICE 'PASS 2a: status_changed_at fires on status change';

    ----------------------------------------------------------------
    -- TEST 2b: status_changed_at does NOT fire when status is unchanged
    ----------------------------------------------------------------
    UPDATE entities SET status_changed_at = v_old, name = 'Test Co v3'
    WHERE id = v_entity_id                       -- status stays 'enriched'
    RETURNING status_changed_at INTO v_ts;
    IF v_ts <> v_old THEN
        RAISE EXCEPTION 'FAIL: status_changed_at fired even though status did not change';
    END IF;
    RAISE NOTICE 'PASS 2b: status_changed_at correctly stays put when status is unchanged';

    ----------------------------------------------------------------
    -- TEST 3: bad status value is rejected by the CHECK constraint
    ----------------------------------------------------------------
    BEGIN
        INSERT INTO entities (segment_id, name, source, status)
        VALUES (v_segment_id, 'Bad Status Co', 'smoke', 'not_a_real_status');
        RAISE EXCEPTION 'FAIL: an invalid status value was accepted';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'PASS 3: invalid status rejected by CHECK';
    END;

    ----------------------------------------------------------------
    -- TEST 4: duplicate (segment_id, domain) is rejected
    ----------------------------------------------------------------
    BEGIN
        INSERT INTO entities (segment_id, name, domain, source)
        VALUES (v_segment_id, 'Dup Domain Co', 'testco.com', 'smoke');
        RAISE EXCEPTION 'FAIL: a duplicate domain was accepted';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'PASS 4: duplicate domain rejected';
    END;

    ----------------------------------------------------------------
    -- TEST 5: duplicate domain-less name is rejected (case-insensitive)
    ----------------------------------------------------------------
    INSERT INTO entities (segment_id, name, source)          -- domain NULL, ok
    VALUES (v_segment_id, 'No Domain Co', 'smoke');
    BEGIN
        INSERT INTO entities (segment_id, name, source)      -- same lower(name), domain NULL
        VALUES (v_segment_id, 'no domain co', 'smoke');
        RAISE EXCEPTION 'FAIL: a duplicate domain-less name was accepted';
    EXCEPTION WHEN unique_violation THEN
        RAISE NOTICE 'PASS 5: duplicate domain-less name rejected (case-insensitive)';
    END;

    ----------------------------------------------------------------
    -- TEST 6: bad email_status is rejected (contacts CHECK)
    ----------------------------------------------------------------
    BEGIN
        INSERT INTO contacts (entity_id, email, email_status)
        VALUES (v_entity_id, 'x@testco.com', 'bogus');
        RAISE EXCEPTION 'FAIL: an invalid email_status was accepted';
    EXCEPTION WHEN check_violation THEN
        RAISE NOTICE 'PASS 6: invalid email_status rejected by CHECK';
    END;

    ----------------------------------------------------------------
    -- CLEANUP: delete the entity (must cascade to its contact), then segment.
    -- If ON DELETE CASCADE were missing, this DELETE would itself raise a
    -- foreign_key_violation — so a clean delete is also the cascade proof.
    ----------------------------------------------------------------
    DELETE FROM entities WHERE segment_id = v_segment_id;

    SELECT count(*) INTO v_contacts_left FROM contacts WHERE entity_id = v_entity_id;
    IF v_contacts_left <> 0 THEN
        RAISE EXCEPTION 'FAIL: contact rows survived their deleted entity (cascade broken)';
    END IF;
    RAISE NOTICE 'PASS 7: deleting an entity cascades to its contacts';

    DELETE FROM segments WHERE id = v_segment_id;

    RAISE NOTICE 'ALL SMOKE TESTS PASSED';
END $$;

-- Final banner + proof that nothing was left behind.
SELECT
    'ALL SMOKE TESTS PASSED' AS result,
    (SELECT count(*) FROM segments WHERE slug = '__smoketest__') AS leftover_segments,
    (SELECT count(*) FROM entities WHERE source = 'smoke')       AS leftover_entities;
