-- 49_MAILBOX_CAP_80.SQL
-- The per-address daily SENDING limit goes from 50 to 80 (owner, 2026-11-13: "Can we increase the limit now of the
-- email sending", chose 80). Approvals were never limited; this is how many emails one Google account (with all
-- its aliases) sends a day. Addresses at 50 move to 80; an address put at another limit on purpose
-- (users.py gmail --cap) is left alone. New rows default to 80 (tools/mailbox_store.DEFAULT_CAP).

alter table user_mailboxes alter column daily_cap set default 80;

update user_mailboxes set daily_cap = 80, updated_at = now() where daily_cap = 50;

select address, daily_cap from user_mailboxes order by address;
