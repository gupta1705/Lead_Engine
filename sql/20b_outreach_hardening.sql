-- 20B_OUTREACH_HARDENING.SQL
-- Applies the confirmed findings of the 30-agent hostile review (2026-08-31)
-- that ran before the first email was ever sent. The two criticals both
-- reduced to the same shape: THE GAP BETWEEN GMAIL ACCEPTING A MESSAGE AND
-- THE DATABASE RECORDING IT. Anything that lives in that gap -- a concurrent
-- send run, a pooler drop, a process kill -- caused a second email to a
-- company that already received one, which is exactly what Invariant 5
-- exists to make impossible.
--
-- The fix is a claim-first protocol, and it needs two new states:
--
--   'sending'       claimed by one send run, atomically, BEFORE the Gmail
--                   call. A concurrent run cannot claim the same row; a
--                   crash leaves the row visibly stuck in 'sending' for a
--                   human, never silently re-sendable.
--   'send_unknown'  the Gmail call errored in a way that does NOT prove the
--                   message was unsent (timeout after accept, 5xx, socket
--                   reset). The truth is unknowable from here, so the row
--                   keeps its one-touch slot and a human settles it against
--                   the Gmail Sent folder. 'failed' is reserved for a human
--                   verdict, no longer auto-assigned by an except clause.
--
-- Both new states deliberately COUNT as touches: the one-touch index already
-- excludes only ('cancelled','failed'), so no index change is needed -- but
-- the CHECK constraint must learn the new states.

alter table outreach drop constraint if exists outreach_status_check;
alter table outreach add constraint outreach_status_check
    check (status in ('drafted','approved','sending','sent','send_unknown',
                      'failed','received','triaged','cancelled'));

-- Reply ingestion must be idempotent: Db.run retries once on a dropped
-- connection, and a retried insert was creating duplicate inbox rows. One
-- Gmail message = one row, enforced here, so 'on conflict do nothing' works.
create unique index if not exists uq_outreach_gmail_message
    on outreach(gmail_message_id) where gmail_message_id is not null;

-- Folder view: two review findings were rows falling into folders no UI pill
-- showed ('cancelled' vanished entirely; a wedged send had nowhere to be
-- seen). Every status now has exactly one visible home.
drop view if exists outreach_folders;
create view outreach_folders with (security_invoker = true) as
select
  o.id, o.entity_id, e.name as company, e.domain,
  c.full_name as contact_name, c.email as contact_email,
  o.direction, o.status, o.triage, o.triage_reason,
  o.subject, o.body, o.template_key, o.send_error,
  o.sent_at, o.created_at, o.gmail_thread_id,
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
