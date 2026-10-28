-- 45_reply_alerts.sql -- an alert in the sender's Gmail when a lead replies (owner, 2026-10-28: "Let's work on
-- making the replies better how do we send a alert", then "Email").
--
-- tools/reply_alert.py, run by `outreach.py pull` (every five minutes since this change, app/scheduler.py):
--   * the reply itself is starred and labelled "Lead replied" in the Gmail that holds the thread;
--   * a short alert (who replied, the model's reading of it, the first lines, a link to the app) is put
--     straight into that person's own inbox (Gmail's messages.import: nothing is sent to anyone, it never
--     leaves their mailbox, and it never counts against their 50 a day);
--   * once a day, from 10:00 India time, a reminder of the replies nobody has marked for over a day.
-- Idempotent: safe to run again.

alter table outreach add column if not exists reply_kind text;           -- the model's reading (reply_alert.KINDS)
alter table outreach add column if not exists alerted_at timestamptz;     -- the alert is in the person's inbox
alter table outreach add column if not exists alert_attempts int not null default 0;
alter table outreach add column if not exists alert_claimed_at timestamptz;   -- two pulls never alert twice
alter table outreach add column if not exists alert_error text;           -- the last attempt's failure

-- the replies that came before alerts existed are not alerted now: the daily reminder covers the unmarked ones
update outreach set alerted_at = created_at
 where direction = 'inbound' and alerted_at is null and created_at < now();

create index if not exists outreach_unalerted_idx on outreach (gmail_thread_id)
 where direction = 'inbound' and alerted_at is null;

-- one reminder per person per day (India's day), claimed before it is delivered
create table if not exists reply_reminders (
  user_email text not null,
  day        date not null,
  replies    int  not null default 0,
  sent_at    timestamptz not null default now(),
  primary key (user_email, day)
);

do $$ begin
  raise notice 'PASS 45_reply_alerts: outreach alert columns and reply_reminders in place';
end $$;
