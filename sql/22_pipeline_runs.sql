-- 22_PIPELINE_RUNS.SQL
-- The audit trail that makes "unattended" observable (P25).
--
-- The done-when for P25 is "a scheduled run completes with nobody watching."
-- The whole risk of that sentence is the "nobody watching" part: a run that
-- happens in the dark and leaves no trace is indistinguishable from a run that
-- never happened. So every scheduled pipeline, and every step inside it,
-- writes a row here -- start, finish, status, and a tail of its log if it
-- failed. The Operations tab reads this back, so a human can walk in on Monday
-- and see exactly what ran over the weekend and whether it was clean.
--
-- n8n harvests keep their OWN trail in source_runs (they always have); this
-- table is for the Python/SQL pipeline the app scheduler drives. Between the
-- two, nothing runs unattended without a record.

create table if not exists pipeline_runs (
    id uuid primary key default gen_random_uuid(),
    pipeline text not null,          -- 'weekly_refresh', 'outreach_poll', ...
    step text,                       -- null for the pipeline row, set per step
    trigger text not null default 'schedule'
        check (trigger in ('schedule', 'manual')),
    status text not null default 'running'
        check (status in ('running', 'ok', 'failed', 'skipped')),
    detail text,                     -- error tail or a short note
    started_at timestamptz not null default now(),
    finished_at timestamptz
);

create index if not exists idx_pipeline_runs_recent
    on pipeline_runs(started_at desc);

alter table pipeline_runs enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'pipeline_runs' and policyname = 'service_all') then
    create policy service_all on pipeline_runs
      for all to service_role using (true) with check (true);
  end if;
end $$;
