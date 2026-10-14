-- 35_OUTREACH_SERVICE.SQL
-- Which LCX service an email pitched: a record of what we sold to whom. The owner's review of the LCX
-- Services emails, 2026-10-13, point 12: each lead is tagged with ONE lead service (tools/lcx_judge.py,
-- config lead_service, stored as metadata.lead_service), the email pitches that service, and the outreach
-- row records which one it pitched. Until now every email named two services (v2) or all eighteen (v1), so
-- nothing said what was sold.
--
--   service   the service the email pitched, exactly as the deck names it ("AI Onboarding Employee").
--             Written by the draft step (tools/outreach.py cmd_draft) from the lead's lead_service. NULL:
--             a project that does not sell one service (every project but LCX Services), or an LCX email
--             drafted before this file (v1 offered all eighteen, v2 two of them).
--
-- FROZEN ONCE SENT. Re-tagging a lead later (a rule edited, a person picking another service) must never
-- rewrite what an email already sent said it was selling, so a row that has gone out (or may have) cannot
-- have its service changed: the trigger raises. A draft's service follows its draft and may be changed.
--
-- Reports group by outreach.service for anything sent and by metadata.lead_service for the pipeline.
--
-- Additive: one column, one index, a guard trigger, and the folders view with the column at its end
-- (create or replace may only add columns after the existing ones; sql/34's select is kept as it is).
-- No row is touched and nothing is dropped, so no --allow-destructive.

alter table outreach add column if not exists service text;

create index if not exists ix_outreach_service on outreach (service) where service is not null;

-- ------------------------------------------------------------ the guard
create or replace function outreach_service_frozen() returns trigger
language plpgsql as $$
begin
  if old.sent_at is not null or old.status in ('sending', 'sent', 'send_unknown') then
    raise exception 'outreach %: it was sent pitching %, and what was sold to whom is not rewritten',
      old.id, coalesce(old.service, 'no single service');
  end if;
  return new;
end $$;

create or replace trigger trg_outreach_service_frozen
    before update of service on outreach
    for each row when (new.service is distinct from old.service)
    execute function outreach_service_frozen();

-- ---------------------------------------------------------- folder view
-- sql/34's select, unchanged, with the service at its end
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
    o.send_wait_why,
    o.service
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;

select count(*) filter (where service is not null) as rows_with_a_service, count(*) as outreach_rows from outreach;
