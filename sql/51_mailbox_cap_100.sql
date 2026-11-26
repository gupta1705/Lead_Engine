-- 51_MAILBOX_CAP_100.SQL
-- The per-address daily SENDING limit goes from 80 to 100 (owner, 2026-11-26: "Can we increase the email limit now",
-- chose 100). Approvals stay unlimited. Addresses at 80 move to 100; an address put at another limit on purpose
-- (users.py gmail --cap) is left alone. New rows default to 100 (tools/mailbox_store.DEFAULT_CAP).

alter table user_mailboxes alter column daily_cap set default 100;

update user_mailboxes set daily_cap = 100, updated_at = now() where daily_cap = 80;

select address, daily_cap from user_mailboxes order by address;
