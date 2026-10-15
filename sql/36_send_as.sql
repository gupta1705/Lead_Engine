-- 36_SEND_AS.SQL
-- Sending as a Gmail alias (owner, 2026-10-15: "We can't login from LCX wala mail because it's an extension").
-- The LCX address (suhas@lightscameraexperiment.com) is not a Google account of its own: it is a "Send mail
-- as" alias inside the person's TVF Gmail (suhasc@theviralfever.com), so Google's sign-in cannot connect it.
-- The person connects their real account; a project with outreach.send_as_domain sends through that account
-- with the alias on that domain in the From line (tools/outreach.py), the way Gmail's own From menu does.
--
--   user_mailboxes.send_as   the account's verified "send mail as" aliases, as Gmail lists them
--                            (users.settings.sendAs, read with the gmail.modify permission everyone already
--                            gave): [{"address": ..., "name": ...}], the primary address left out. NULL: not
--                            read yet (an address linked from the laptop); the next send reads it.
--   outreach.sent_as         the From address the recipient saw, when it was an alias -- read back from the
--                            sent message, not assumed. NULL: the account's own address (sender_address).
--
-- sender_address stays the ACCOUNT: an alias shares its account's daily limit and spacing (Gmail counts the
-- account), so every count, the claim's cap and the gap are unchanged.
--
-- Additive: two nullable columns and the folders view with sent_as at its end (create or replace may only add
-- columns after the existing ones; sql/35's select is kept as it is). No row is touched, nothing is dropped.

alter table user_mailboxes add column if not exists send_as jsonb;
alter table outreach add column if not exists sent_as text;

-- ---------------------------------------------------------- folder view
-- sql/35's select, unchanged, with sent_as at its end
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
    o.sent_as
   FROM outreach o
     JOIN entities e ON e.id = o.entity_id
     LEFT JOIN contacts c ON c.id = o.contact_id;

select count(*) filter (where send_as is not null) as mailboxes_with_aliases_read, count(*) as mailboxes
from user_mailboxes;
