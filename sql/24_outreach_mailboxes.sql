-- 24_OUTREACH_MAILBOXES.SQL
-- Mailbox rotation. Owner decision, 2026-09-10: "Build the mailbox rotation".
--
-- A segment may send from several mailboxes (config outreach.mailboxes). The
-- send command spreads openers across them, each capped by its own warm-up
-- ramp. Every outbound row now records which mailbox sent it.
--
-- THE ONE RULE THE DATABASE KEEPS: a follow-up leaves from the mailbox that
-- sent its opener. A Gmail thread belongs to one mailbox; a follow-up sent
-- from another would start a new, unthreaded conversation from a stranger.
-- The guard trigger (first created in sql/23) now overwrites a follow-up's
-- mailbox with its opener's at the moment it is claimed for sending, and the
-- send command uses the value the claim RETURNS, so no bug above this layer
-- can send a follow-up from the wrong mailbox.
--
-- DESTRUCTIVE STATEMENTS, reviewed: DROP VIEW (recreated below). No row is
-- deleted. Run with --allow-destructive.

alter table outreach add column if not exists sender_mailbox text;
alter table outreach add column if not exists sender_address text;

create index if not exists idx_outreach_mailbox_sent on outreach(sender_mailbox, sent_at)
    where direction = 'outbound' and status = 'sent';

create or replace function outreach_sequence_guard() returns trigger
language plpgsql as $$
declare
  parent_mailbox text;
  parent_address text;
begin
  if new.parent_id is not null then
    if not exists (select 1 from outreach p
                   where p.id = new.parent_id and p.entity_id = new.entity_id
                     and p.direction = 'outbound' and p.sequence_step = 0) then
      raise exception 'follow-up must point at the opener of the same company (outreach %)', new.id;
    end if;
  end if;
  if new.sequence_step > 0 and new.status = 'sending'
     and (tg_op = 'INSERT' or old.status is distinct from 'sending') then
    -- the irreversible step: never after a reply (auto-replies excepted) or a stop
    if exists (select 1 from outreach r
               where r.entity_id = new.entity_id and r.direction = 'inbound'
                 and r.triage is distinct from 'neutral')
       or exists (select 1 from outreach p
                  where p.id = new.parent_id and p.stopped_reason is not null) then
      return null;
    end if;
    -- and only from the mailbox that owns the thread
    select p.sender_mailbox, p.sender_address into parent_mailbox, parent_address
      from outreach p where p.id = new.parent_id;
    if parent_mailbox is not null then
      new.sender_mailbox := parent_mailbox;
      new.sender_address := parent_address;
    end if;
  end if;
  return new;
end $$;

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
  o.sender_mailbox, o.sender_address,
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
