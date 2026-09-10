-- 23_OUTREACH_SEQUENCES.SQL
-- Follow-up sequences and batch approval. Owner decision, 2026-09-10:
-- "Build the follow-ups and batch approval" -- for sales segments (LCX
-- clipping first). The TVF segment keeps its original policy because its
-- config enables neither; nothing below changes what TVF can send.
--
-- WHAT CHANGES IN INVARIANT 5
--   Before: one outbound touch per company, forever (unique on entity_id).
--   After:  one THREAD per company, forever. The opener (sequence_step 0) is
--           still unique per company across all time, and each follow-up step
--           can exist at most once, capped at three by a CHECK. So the most a
--           company can ever receive is an opener plus the follow-ups its
--           segment config allows (LCX: two), all in the opener's thread.
--   A follow-up must point at the opener of the SAME company (trigger), and
--   can never be claimed for sending once that company has replied with
--   anything other than an auto-reply, or once its thread has been stopped
--   (trigger returns NULL, so the claim sees no row and nothing is sent).
--   That last rule holds even if every layer above the database is buggy.
--
-- BATCH APPROVAL AUDIT
--   approved_at / approved_by / approval_mode ('single' | 'batch') /
--   approval_batch / spot_checked on every approved row, and one
--   outreach_approval_batches row per batch recording who approved how many,
--   which drafts were in the server-drawn spot-check sample, and what was
--   skipped and why.
--
-- DESTRUCTIVE STATEMENTS, reviewed: DROP INDEX (the old one-touch index,
-- dropped only AFTER its replacement exists, so there is no moment without a
-- uniqueness guarantee), DROP TRIGGER and DROP VIEW (both recreated in this
-- file). No row is deleted. Run with --allow-destructive.

-- --------------------------------------------------------------- columns
alter table outreach add column if not exists sequence_step integer not null default 0;
alter table outreach add column if not exists parent_id uuid references outreach(id) on delete set null;
alter table outreach add column if not exists stopped_reason text;
alter table outreach add column if not exists approved_at timestamptz;
alter table outreach add column if not exists approved_by text;
alter table outreach add column if not exists approval_mode text;
alter table outreach add column if not exists approval_batch uuid;
alter table outreach add column if not exists spot_checked boolean;

alter table outreach drop constraint if exists outreach_sequence_step_check;
alter table outreach add constraint outreach_sequence_step_check
    check (sequence_step between 0 and 3
           and (sequence_step = 0 or (direction = 'outbound' and parent_id is not null)));

alter table outreach drop constraint if exists outreach_approval_mode_check;
alter table outreach add constraint outreach_approval_mode_check
    check (approval_mode is null or approval_mode in ('single', 'batch'));

-- --------------------------------------------------- one thread per company
create unique index if not exists uq_outreach_one_touch_step
    on outreach(entity_id, sequence_step) where direction = 'outbound'
                                            and status not in ('cancelled', 'failed');
drop index if exists uq_outreach_one_touch;

create index if not exists idx_outreach_parent on outreach(parent_id) where parent_id is not null;

-- ------------------------------------------------------------ the guard
create or replace function outreach_sequence_guard() returns trigger
language plpgsql as $$
begin
  if new.parent_id is not null then
    if not exists (select 1 from outreach p
                   where p.id = new.parent_id and p.entity_id = new.entity_id
                     and p.direction = 'outbound' and p.sequence_step = 0) then
      raise exception 'follow-up must point at the opener of the same company (outreach %)', new.id;
    end if;
  end if;
  -- The irreversible step. A follow-up is never claimed for sending once the
  -- company has replied (auto-replies triaged 'neutral' excepted) or the
  -- thread has been stopped. Returning NULL skips the update silently; the
  -- send command's claim then finds no row and sends nothing.
  if new.sequence_step > 0 and new.status = 'sending'
     and (tg_op = 'INSERT' or old.status is distinct from 'sending') then
    if exists (select 1 from outreach r
               where r.entity_id = new.entity_id and r.direction = 'inbound'
                 and r.triage is distinct from 'neutral')
       or exists (select 1 from outreach p
                  where p.id = new.parent_id and p.stopped_reason is not null) then
      return null;
    end if;
  end if;
  return new;
end $$;

drop trigger if exists trg_outreach_sequence_guard on outreach;
create trigger trg_outreach_sequence_guard
    before insert or update on outreach
    for each row execute function outreach_sequence_guard();

-- ------------------------------------------------------ approval batches
create table if not exists outreach_approval_batches (
    id uuid primary key default gen_random_uuid(),
    segment_slug text not null,
    approved_by text not null,
    requested integer not null,
    approved integer not null,
    sample_ids uuid[] not null,
    skipped jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

alter table outreach_approval_batches enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'outreach_approval_batches' and policyname = 'service_all') then
    create policy service_all on outreach_approval_batches
      for all to service_role using (true) with check (true);
  end if;
end $$;

-- ---------------------------------------------------------- folder view
-- Same folders as 20b; the sequence and approval columns are added so the UI
-- can show "Follow-up 1", who approved a draft, and why a step was stopped.
drop view if exists outreach_folders;
create view outreach_folders with (security_invoker = true) as
select
  o.id, o.entity_id, e.name as company, e.domain,
  c.full_name as contact_name, c.email as contact_email,
  o.direction, o.status, o.triage, o.triage_reason,
  o.subject, o.body, o.template_key, o.send_error,
  o.sent_at, o.created_at, o.gmail_thread_id,
  o.sequence_step, o.parent_id, o.stopped_reason,
  o.approved_at, o.approved_by, o.approval_mode, o.spot_checked,
  case
    when o.status = 'drafted'                       then 'drafts'
    when o.status in ('approved','sending')         then 'outbox'
    when o.status = 'sent'                          then 'sent'
    when o.status in ('failed','send_unknown')      then 'attention'
    when o.triage = 'positive'                      then 'positive'
    when o.triage = 'negative'                      then 'negative'
    when o.status in ('received','triaged')         then 'inbox'
    when o.status = 'cancelled'                     then 'cancelled'
    else 'attention'
  end as folder
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id;
