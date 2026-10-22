-- 39_OUTREACH_CC.SQL
-- CC from the app (owner, 2026-10-22: "add a feature to cc someone from the software itself. Make default cc to
-- the email amritanshv@lightscameraexperiment.com and obvio make a toggle to switch that off").
--
--   outreach.cc   who the email is copied to, as approved. NULL: not decided on this draft -- the project's
--                 default (config outreach.default_cc) applies. '{}': nobody (the person switched the default
--                 off). A list: exactly those addresses (the default, kept or not, and any added).
--
-- FROZEN AT APPROVAL. A person approves an email with the copy list they were shown, so the trigger below
-- writes the project's default into a draft still at NULL the moment it becomes approved, whichever path
-- approved it (one email, a batch, the compose widget). Changing the default later never changes an email
-- already approved. The sender (tools/outreach.py) sends to cc; a row approved before this file (NULL) gets
-- the project's default at send time, as it would have been given at approval.
--
-- Additive: one nullable column, one trigger, the folders view with cc at its end (create or replace may
-- only add columns after the existing ones; sql/36's select is kept as it is). No row is touched.

alter table outreach add column if not exists cc text[];

create or replace function outreach_cc_frozen() returns trigger
language plpgsql as $$
begin
  if new.cc is null and new.direction = 'outbound' then
    select array(select lower(btrim(x)) from jsonb_array_elements_text(
             coalesce(s.config #> '{outreach,default_cc}', '[]'::jsonb)) as x where btrim(x) <> '')
      into new.cc
      from entities e join segments s on s.id = e.segment_id where e.id = new.entity_id;
    new.cc := coalesce(new.cc, '{}');
  end if;
  return new;
end $$;

create or replace trigger trg_outreach_cc_frozen
    before update of status on outreach
    for each row when (new.status = 'approved' and old.status is distinct from 'approved')
    execute function outreach_cc_frozen();

-- ---------------------------------------------------------- folder view
-- sql/36's select, unchanged, with cc at its end
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
    o.service,
    o.sent_as,
    o.cc
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;

select count(*) filter (where cc is not null) as rows_with_cc, count(*) as outreach_rows from outreach;
