-- 33_APOLLO_HARVEST.SQL
-- Apollo as a weekly source of corporate leads (LCX Services; owner, 2026-10-07: "i want to reachout
-- to buisnesses to normal corporates not just cafes ... Enriching from apollo is acceptable").
--
-- apollo_cursors   where each saved search slice got to: a company page is paid for (1 credit), so the
--                  next run asks for the next page, never the same one twice. One row per project and
--                  slice (search key and country).
-- apollo_spend     every credit spent, when, by which project and on what: a company page, a person
--                  revealed, a company looked up by name. A project's weekly cap and the reserve kept for
--                  the others are read from here, so a second run in the same week (a refresh pressed by
--                  hand) cannot spend the week's credits again.
-- Additive only: two new tables and an index.

create table if not exists apollo_cursors (
    segment_id   uuid not null references segments(id),
    search_key   text not null,
    next_page    integer not null default 1 check (next_page between 1 and 500),
    total_pages  integer,
    runs         integer not null default 0,
    last_run_at  timestamptz,
    exhausted_at timestamptz,
    primary key (segment_id, search_key)
);

create table if not exists apollo_spend (
    id          bigserial primary key,
    segment_id  uuid references segments(id),
    at          timestamptz not null default now(),
    kind        text not null check (kind in ('company_page', 'reveal', 'company_lookup')),
    credits     numeric not null check (credits >= 0),
    ref         text
);

create index if not exists apollo_spend_segment_at on apollo_spend (segment_id, at);
