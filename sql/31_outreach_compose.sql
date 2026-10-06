-- 31_OUTREACH_COMPOSE.SQL
-- An email a person writes to the leads they picked (the Universal project; the owner, 2026-09-27:
-- "in the universal segment there should be a widget to send mail to them"). tools/outreach_compose.py
-- makes one approved outbound row per company, exactly what an approved draft is, and records how it
-- was approved: approval_mode 'compose' -- the person wrote it and approved it, for these leads, with
-- how it reads for each of them in front of them.
--
-- DESTRUCTIVE STATEMENTS, reviewed: DROP CONSTRAINT (the approval_mode check, added back by the next
-- statement with one more value allowed). No row is touched. Run with --allow-destructive.

alter table outreach drop constraint if exists outreach_approval_mode_check;
alter table outreach add constraint outreach_approval_mode_check
    check (approval_mode is null or approval_mode in ('single', 'batch', 'compose'));
