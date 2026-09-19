-- 29_SAVED_SEARCHES.SQL
-- Saved searches for the Universal (Apollo) page, 2026-09-19.
--
-- Apollo's own app lets a person save a search and run it again later. The
-- Universal page does the same: a name, whether it searches people or
-- companies, and the filters exactly as the page sent them to Apollo.
--
-- A table, not a key in segments.config: the config row is regenerated from
-- config/segment.<slug>.json (tools/gen_segment_sql.py), so anything the app
-- wrote into it would be wiped by the next re-sync.
--
-- Idempotent: safe to run again.

create table if not exists saved_searches (
    id          uuid primary key default gen_random_uuid(),
    segment_id  uuid not null references segments(id),
    name        text not null check (length(btrim(name)) between 1 and 80),
    kind        text not null check (kind in ('people', 'companies')),
    filters     jsonb not null default '{}'::jsonb,
    created_by  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- one name per segment, whatever the case: saving under a taken name updates it
create unique index if not exists uq_saved_searches_name
    on saved_searches (segment_id, lower(name));

select count(*) as saved_searches from saved_searches;
