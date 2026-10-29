-- 46_waiting_on_us.sql -- "Waiting on us": which conversations are waiting for our answer, and for how long (the
-- owner, 2026-10-29: "Implement 6", build 6 of reports/Outreach platforms lessons for Lead Engine.md).
--
-- `outreach.py pull` reads every message of a thread. Since this change it also notes, on each reply:
--   * received_at   when the reply reached the mailbox (Gmail's own date for it, not when the app read it);
--   * answered_at   when our side first wrote in the thread after it: anything sent from that Gmail, or from
--                   another of our addresses (the project's CC, a send-as alias) -- answered_how 'thread';
--   * answered_by   the address that wrote it.
-- A person who answered another way (a call, WhatsApp, a new email) marks it in the reply's sheet: answered_how
-- 'marked', answered_by their login. Waiting on us is a real reply with no answered_at (outreach_policy.unanswered).
-- Idempotent: safe to run again. The next pull fills both dates in for the replies already there.

alter table outreach add column if not exists received_at timestamptz;
alter table outreach add column if not exists answered_at timestamptz;
alter table outreach add column if not exists answered_by text;
alter table outreach add column if not exists answered_how text;

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'outreach_answered_how_check') then
    alter table outreach add constraint outreach_answered_how_check
      check (answered_how is null or answered_how in ('thread', 'marked'));
  end if;
end $$;

create index if not exists outreach_unanswered_idx on outreach (entity_id)
 where direction = 'inbound' and answered_at is null;

do $$ begin
  raise notice 'PASS 46_waiting_on_us: outreach received_at, answered_at, answered_by, answered_how in place';
end $$;
