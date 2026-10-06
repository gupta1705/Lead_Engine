-- 32_OUTREACH_ATTACHMENTS.SQL
-- An email may carry files. The owner, 2026-10-06, for LCX Services: "email should be a pitch deck
-- of services", then "PDF deck attached". What a person approved is what is sent, so each email keeps
-- the files it was drafted with -- [{name, path, sha256, bytes}] -- and the sender sends exactly those
-- bytes, or holds the email back when the file is gone or has changed since
-- (tools/outreach_policy.attachment_problem). NULL: no files, as every email before this.
-- Additive: a new column, a check on its shape, and the folders view with the column at its end.

alter table outreach add column if not exists attachments jsonb;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'outreach_attachments_array') then
    alter table outreach add constraint outreach_attachments_array
      check (attachments is null or jsonb_typeof(attachments) = 'array');
  end if;
end $$;

create or replace view outreach_folders as
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
    o.attachments
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;
