-- 23_PIPELINE_RUNS_SEGMENT.SQL
-- Segment 3 (2026-09-09): the app now runs pipelines for more than one
-- segment, so every run records which one. Old rows stay null and are shown
-- under the default segment. Idempotent.
alter table pipeline_runs add column if not exists segment text;
create index if not exists idx_pipeline_runs_segment on pipeline_runs(segment, started_at desc);
