-- 40_OUTREACH_FOLLOWUPS_FOLDER.SQL
-- A tab of their own for follow-ups (owner, 2026-10-23: "Create another tab for follow ups"). A follow-up draft
-- (sequence_step > 0, waiting for a person to approve it) is in the 'followups' folder; Drafts keeps first emails
-- only. Once approved a follow-up is in Approved, once sent in Sent, as before (marked as a follow-up there).
--
-- Only the folder expression changes: sql/39's select, every column in the same place, so create or replace keeps
-- working. No row is touched.

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
            WHEN o.status = 'drafted'::text AND COALESCE(o.sequence_step, 0) > 0 THEN 'followups'::text
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
    o.service,
    o.sent_as,
    o.cc
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;

select folder, count(*) from outreach_folders where folder in ('drafts', 'followups') group by 1 order by 1;
