-- 34_SEND_WINDOW.SQL
-- Each email goes out at its own second between 10:00 and 10:30 in its recipient's time zone. The owner,
-- 2026-10-12: "I want you to send mails to the sender's time region between 10 to 10:30AM and that must
-- be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13 and so on".
-- The moment is drawn when the email is approved (tools/outreach_policy.place_send) and stored here, so
-- the Approved list can say when each one goes; the sender claims a row only inside its own window.
--
--   send_after        the moment drawn for it (UTC); the sender claims it at or after this
--   send_before       the end of its window: past this unsent, it is moved to the next window at a new
--                     random second (settle_schedule), never sent late in the afternoon
--   send_tz           the IANA zone the window is in (the recipient's, or the sender's when the config says)
--   send_tz_reason    why that zone, in plain English ("recipient: Texas, United States")
--   send_plan         a fingerprint of the window config it was placed under: a config change re-places it
--   send_reschedules  how many windows it has missed; three that were not a pause raise an alert
--   send_wait_why     why it last moved ("the thread's address was at its daily limit")
--
-- NULL send_after: no time -- the project has no window (it sends as before this file), or the row is
-- not approved yet. Old code never sets send_after, so this file changes nothing until the new code and
-- a config block are both live.
--
-- THE GUARD. The claim (tools/outreach.py cmd_send: approved -> sending) checks the window in its own
-- WHERE; the trigger repeats it so no other path -- an older checkout's sender, a hand-run UPDATE -- can
-- send outside it. It raises rather than returning NULL: the old sender cancels a follow-up whose claim
-- matched nothing, and a loud crash that sends nothing is the right failure. The 60 s of grace exist only
-- so the new claim, which checks strictly against the same clock, can never trip it.
--
-- Additive: seven columns, a check, two indexes, a guard trigger, the folders view with the columns at its
-- end. No row is touched, nothing is dropped (create or replace trigger, Postgres 14+), so no
-- --allow-destructive. The view gets back security_invoker, which sql/32's create-or-replace left off
-- (a view owned by postgres over RLS tables would hand rows to anon; sql/20).

alter table outreach add column if not exists send_after timestamptz;
alter table outreach add column if not exists send_before timestamptz;
alter table outreach add column if not exists send_tz text;
alter table outreach add column if not exists send_tz_reason text;
alter table outreach add column if not exists send_plan text;
alter table outreach add column if not exists send_reschedules integer not null default 0;
alter table outreach add column if not exists send_wait_why text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'outreach_send_window_shape') then
    alter table outreach add constraint outreach_send_window_shape
      check ((send_after is null) = (send_before is null)
             and (send_after is null or send_after < send_before));
  end if;
end $$;

-- the sender's pick (approved, due) and the per-address gap check (the last claim on an address)
create index if not exists ix_outreach_send_due on outreach (send_after)
  where direction = 'outbound' and status = 'approved' and send_error is null;
create index if not exists ix_outreach_sender_inflight on outreach (lower(sender_address))
  where direction = 'outbound' and status in ('sending', 'send_unknown');

-- ------------------------------------------------------------ the guard
create or replace function outreach_send_window_guard() returns trigger
language plpgsql as $$
begin
  if new.send_after is not null and (clock_timestamp() < new.send_after
       or clock_timestamp() >= new.send_before + interval '60 seconds') then
    raise exception 'send window: outreach % may go only between % and %', new.id, new.send_after, new.send_before;
  end if;
  return new;
end $$;

create or replace trigger trg_outreach_send_window_guard
    before update of status on outreach
    for each row when (old.status = 'approved' and new.status = 'sending')
    execute function outreach_send_window_guard();

-- ---------------------------------------------------------- folder view
-- sql/32's select, unchanged, with the seven columns at its end (create or replace may only add columns
-- after the existing ones)
create or replace view outreach_folders with (security_invoker = true) as
 SELECT o.id,
    o.entity_id,
    e.name AS company,
    e.domain,
    c.full_name AS contact_name,
    c.email AS contact_email,
    o.direction,
    o.status,
    o.triage,
    o.triage_reason,
    o.subject,
    o.body,
    o.template_key,
    o.send_error,
    o.sent_at,
    o.created_at,
    o.gmail_thread_id,
    o.sequence_step,
    o.parent_id,
    o.stopped_reason,
    o.approved_at,
    o.approved_by,
    o.approval_mode,
    o.spot_checked,
    o.sender_mailbox,
    o.sender_address,
    o.generated_hook,
    o.generated_hook IS NOT NULL AS generated,
        CASE
            WHEN o.status = 'drafted'::text THEN 'drafts'::text
            WHEN o.status = ANY (ARRAY['approved'::text, 'sending'::text]) THEN 'outbox'::text
            WHEN o.status = 'sent'::text THEN 'sent'::text
            WHEN o.status = ANY (ARRAY['failed'::text, 'send_unknown'::text]) THEN 'attention'::text
            WHEN o.triage = 'positive'::text THEN 'positive'::text
            WHEN o.triage = 'negative'::text THEN 'negative'::text
            WHEN o.status = ANY (ARRAY['received'::text, 'triaged'::text]) THEN 'inbox'::text
            WHEN o.status = 'cancelled'::text THEN 'cancelled'::text
            ELSE 'attention'::text
        END AS folder,
    o.attachments,
    o.send_after,
    o.send_before,
    o.send_tz,
    o.send_tz_reason,
    o.send_plan,
    o.send_reschedules,
    o.send_wait_why
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;
