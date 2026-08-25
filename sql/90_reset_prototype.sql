-- 90_RESET_PROTOTYPE.SQL
-- DESTRUCTIVE. Clears the un-decided pipeline so a connector can be re-run from
-- a clean slate during Phase B, without leaving half-imported rows behind.
--
-- `tools/run_sql.py` REFUSES this file unless you pass --allow-destructive.
-- That is deliberate and you should leave it that way:
--     python tools/run_sql.py sql/90_reset_prototype.sql --dry-run
--     python tools/run_sql.py sql/90_reset_prototype.sql --allow-destructive
--
----------------------------------------------------------------------
-- WHAT IT WILL NEVER DELETE, AND WHY
----------------------------------------------------------------------
-- Invariant 4: **`rejected` entities are permanently shielded from re-import.**
-- A rejection is a human decision with a reason attached. If a reset wiped
-- them, the next connector run would re-discover the same company, it would
-- climb back into the review queue, and someone would spend the judgement a
-- second time -- or worse, approve what was already refused. The rejected rows
-- ARE the shield; deleting them removes it.
--
-- Invariant 5: **one touch per company, ever.** From P20 the `outreach` table
-- is append-only history and a company that has been emailed can never be
-- emailed again. Any entity carrying outreach history is untouchable here.
-- That table does not exist yet, so the guard below is written to become
-- active the moment it does, rather than being remembered later.
--
-- Also preserved: `shortlisted`, `contacted`, `in_conversation`, `archived`.
-- Every one of those represents a decision or an action already taken.
--
-- SO WHAT DOES IT DELETE? Only rows nobody has judged yet:
--   - staging_candidates (the connector inbox -- always safe, pre-decision)
--   - source_runs (the connector logbook)
--   - entities still sitting in discovered / enriched / scored / ready_for_review
--
-- A reset is therefore never a way to "start over completely". That is the
-- point. If you genuinely need a bare database, rebuild it: 01 -> 02 -> 03.

----------------------------------------------------------------------
-- STEP 1 -- look before you leap. Run this ALONE first; it deletes nothing.
----------------------------------------------------------------------
select
    'WILL DELETE: entities (un-decided)' as what,
    count(*)                             as rows
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status in ('discovered', 'enriched', 'scored', 'ready_for_review')
union all
select 'WILL DELETE: staging_candidates', count(*)
from staging_candidates
where segment_id = (select id from segments where slug = 'us-production-houses')
union all
select 'WILL DELETE: source_runs', count(*)
from source_runs
where segment_id = (select id from segments where slug = 'us-production-houses')
union all
select 'WILL KEEP: rejected (the re-import shield)', count(*)
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status = 'rejected'
union all
select 'WILL KEEP: shortlisted / contacted / in_conversation / archived', count(*)
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and status in ('shortlisted', 'contacted', 'in_conversation', 'archived');

----------------------------------------------------------------------
-- STEP 2 -- the reset itself.
----------------------------------------------------------------------

-- 2a. The connector inbox. Nothing here has ever been judged.
delete from staging_candidates
where segment_id = (select id from segments where slug = 'us-production-houses');

-- 2b. The connector logbook.
delete from source_runs
where segment_id = (select id from segments where slug = 'us-production-houses');

-- 2c. Un-decided entities only. `contacts` rows disappear with them via
--     ON DELETE CASCADE, which is correct: a contact exists only to be
--     reachable, and the entity it belonged to is gone.
--
--     The `not exists` clause is the outreach shield. It is written against
--     information_schema so it is inert until the P20 table exists, and
--     protective from the moment it does -- no edit required, and no chance
--     of someone forgetting to add it later.
delete from entities e
where e.segment_id = (select id from segments where slug = 'us-production-houses')
  and e.status in ('discovered', 'enriched', 'scored', 'ready_for_review')
  and not exists (
        select 1
        from information_schema.tables t
        where t.table_schema = 'public' and t.table_name = 'outreach'
  );

----------------------------------------------------------------------
-- STEP 3 -- confirm what survived.
----------------------------------------------------------------------
select status, count(*)
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
group by status
order by status;

select
    (select count(*) from staging_candidates
      where segment_id = (select id from segments where slug = 'us-production-houses')) as staging_left,
    (select count(*) from source_runs
      where segment_id = (select id from segments where slug = 'us-production-houses')) as runs_left;
-- Both should be 0. Any `rejected` count should be unchanged from step 1.

----------------------------------------------------------------------
-- ⚑ WHEN THE `outreach` TABLE LANDS AT P20, TIGHTEN 2c.
-- The clause above is coarse: once `outreach` exists it disables the entity
-- delete entirely, which is safe but blunt. Replace it then with a per-row
-- check so a reset still works on entities that were never contacted:
--
--   and not exists (select 1 from outreach o where o.entity_id = e.id)
--
-- Coarse-and-safe now, precise later. The wrong order -- precise now, remembered
-- later -- is how a company gets emailed twice.
----------------------------------------------------------------------
