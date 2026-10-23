-- 41_MAILBOX_CAP_50.SQL
-- The per-address daily limit is 50 (owner, 2026-10-23: "our limit is 50 why does it show 35"). The connected
-- addresses were already at 50; a new one was still created at 35 (tools/mailbox_store.DEFAULT_CAP, now 50). This
-- sets the column's own default to match, for any insert that does not name a limit. No row is changed: an
-- address at another limit was put there on purpose (users.py gmail --cap).

alter table user_mailboxes alter column daily_cap set default 50;

select address, daily_cap from user_mailboxes order by address;
