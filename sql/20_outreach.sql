-- 20_OUTREACH.SQL
-- Phase F begins: the table where a shortlist becomes a conversation.
--
-- DESIGN DECISIONS, AND WHY:
--
-- 1. DRAFTS ARE ROWS, NOT EMAILS. Nothing in this system sends on its own.
--    The pipeline is drafted -> approved -> sent, and the approve transition
--    only ever happens from a human click in the review UI. The send command
--    refuses anything not approved. This is not caution theatre: the moment
--    an engine emails a stranger un-reviewed, one bad merge field ("Dear
--    {{first_name}}") costs more goodwill than the whole pool is worth.
--
-- 2. ONE TOUCH PER COMPANY, ENFORCED BY THE DATABASE (Invariant 5). The
--    partial unique index below makes a second outbound row for the same
--    entity IMPOSSIBLE, not discouraged. Every layer above this one -- the
--    draft command, the UI, a future n8n workflow -- can be buggy and the
--    invariant still holds. Follow-up sequences are a v2 feature and will be
--    designed deliberately, not smuggled in as duplicate rows.
--
-- 3. REPLIES LIVE IN THE SAME TABLE (direction = 'inbound', thread_id ties
--    them together). One place answers "what has ever passed between us and
--    this company", which is what a BD person actually asks.
--
-- 4. TRIAGE IS A LABEL, NOT AN ACTION. The classifier writes
--    positive/negative/neutral/needs_human and its reasoning; a human decides
--    what happens next. On a confirmed positive the ENTITY moves to
--    in_conversation -- by the human's click, same as review dispositions.

create table if not exists outreach (
    id uuid primary key default gen_random_uuid(),
    entity_id uuid not null references entities(id) on delete cascade,
    contact_id uuid references contacts(id) on delete set null,
    direction text not null default 'outbound'
        check (direction in ('outbound', 'inbound')),
    template_key text,
    subject text,
    body text,
    status text not null default 'drafted'
        check (status in (
            'drafted',      -- rendered, waiting for a human eye
            'approved',     -- a human read THIS text and said send it
            'sent',         -- accepted by Gmail; gmail_message_id set
            'failed',       -- send attempted, Gmail said no; error in send_error
            'received',     -- inbound reply, not yet triaged
            'triaged',      -- inbound reply, classifier has labelled it
            'cancelled'     -- human withdrew a draft
        )),
    triage text
        check (triage in ('positive', 'negative', 'neutral', 'needs_human')),
    triage_reason text,
    gmail_message_id text,
    gmail_thread_id text,
    send_error text,
    sent_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Invariant 5. One outbound touch per company, forever, at the schema level.
create unique index if not exists uq_outreach_one_touch
    on outreach(entity_id) where direction = 'outbound'
                             and status not in ('cancelled', 'failed');

create index if not exists idx_outreach_status on outreach(status);
create index if not exists idx_outreach_entity on outreach(entity_id);
create index if not exists idx_outreach_thread on outreach(gmail_thread_id)
    where gmail_thread_id is not null;

-- Same posture as every other table: RLS on, service role only. The anon key
-- that ships in browser code must never be able to read email bodies.
alter table outreach enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'outreach' and policyname = 'service_all') then
    create policy service_all on outreach
      for all to service_role using (true) with check (true);
  end if;
end $$;

-- The folder views P19 deferred "until the table they read exists". It does
-- now. security_invoker for the same reason review_queue has it: a view owned
-- by postgres over an RLS table would hand rows to anon.
create or replace view outreach_folders with (security_invoker = true) as
select
  o.id, o.entity_id, e.name as company, e.domain,
  c.full_name as contact_name, c.email as contact_email,
  o.direction, o.status, o.triage, o.triage_reason,
  o.subject, o.body, o.template_key,
  o.sent_at, o.created_at, o.gmail_thread_id,
  case
    when o.status in ('drafted')             then 'drafts'
    when o.status in ('approved')            then 'outbox'
    when o.status = 'sent'                   then 'sent'
    when o.status = 'failed'                 then 'failed'
    when o.triage = 'positive'               then 'positive'
    when o.triage = 'negative'               then 'negative'
    when o.status in ('received','triaged')  then 'inbox'
    else 'other'
  end as folder
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id;
