-- 48_suppressions.sql -- the do-not-contact list (the owner, 2026-11-12: "Keep a proper do-not-contact list").
--
-- Until now the only block was outreach_policy.ANSWERED_SQL, read off the lead tables: an address that replied or
-- bounced. A company that wrote "remove us" was protected only while its lead row and contact row survived, and
-- only at that one address; a reset, a new lead for the same company or another address at the same domain got
-- past it. This list lives outside the lead tables and is checked on its own:
--   * kind 'email'  -- one address, never written to again by any project;
--   * kind 'domain' -- the whole organisation (its own domain; never a free mailbox provider like gmail.com).
-- do_not_contact(email, lead) -> the reason, or NULL. It is checked when a draft is written (tools/outreach.py
-- cmd_draft), when one is approved and when it is sent (outreach_policy.ANSWERED_SQL). Entries are added by the
-- engine (an unsubscribe or "not interested" reply, a bounce, an inbox nobody reads) and by people
-- (tools/suppress.py). Nothing is ever deleted from the lead tables for it.
-- Idempotent: safe to run again.

create table if not exists suppressions (
  id         uuid primary key default gen_random_uuid(),
  kind       text not null check (kind in ('email', 'domain')),
  value      text not null check (value = lower(btrim(value)) and value <> ''),
  reason     text not null,
  source     text not null,          -- unsubscribe, not_interested, bounce, wrong_address, manual, backfill
  created_by text,
  created_at timestamptz not null default now(),
  unique (kind, value)
);

alter table suppressions enable row level security;
do $$
begin
  if not exists (select 1 from pg_policies where tablename = 'suppressions' and policyname = 'service_all') then
    create policy service_all on suppressions for all to service_role using (true) with check (true);
  end if;
end $$;

create or replace function do_not_contact(p_email text, p_entity uuid)
returns text language sql stable as $$
  select s.reason
    from suppressions s
   where (s.kind = 'email' and s.value = lower(btrim(coalesce(p_email, ''))))
      or (s.kind = 'domain' and (
            s.value = lower(split_part(btrim(coalesce(p_email, '')), '@', 2))
         or s.value = (select lower(regexp_replace(e.domain, '^www\.', '')) from entities e where e.id = p_entity)))
   order by s.created_at
   limit 1
$$;

-- what is already known: unsubscribes (the address and its own domain), "not interested" replies, bounces, and
-- inboxes nobody reads
insert into suppressions (kind, value, reason, source)
select distinct 'email', lower(btrim(c.email)),
       case r.reply_kind when 'unsubscribe' then 'asked not to be emailed again'
                         else 'replied: not interested' end,
       'backfill'
  from outreach r join contacts c on c.id = r.contact_id
 where r.direction = 'inbound' and c.email is not null
   and (r.reply_kind in ('unsubscribe', 'not_interested') or r.triage = 'negative')
on conflict (kind, value) do nothing;

insert into suppressions (kind, value, reason, source)
select distinct 'domain', lower(split_part(btrim(c.email), '@', 2)), 'asked not to be emailed again', 'backfill'
  from outreach r join contacts c on c.id = r.contact_id
 where r.direction = 'inbound' and r.reply_kind = 'unsubscribe' and c.email is not null
   and lower(split_part(btrim(c.email), '@', 2)) not in ('gmail.com', 'googlemail.com', 'yahoo.com', 'hotmail.com',
       'outlook.com', 'live.com', 'msn.com', 'icloud.com', 'me.com', 'aol.com', 'protonmail.com', 'proton.me',
       'ymail.com', 'rediffmail.com', 'zoho.com', 'gmx.com', 'mail.com')
on conflict (kind, value) do nothing;

insert into suppressions (kind, value, reason, source)
select distinct 'email', lower(btrim(c.email)),
       case c.verifier when 'bounce' then 'bounced' else 'the inbox is not read' end, 'backfill'
  from contacts c
 where c.email is not null and c.email_status = 'invalid' and c.verifier in ('bounce', 'wrong_address')
on conflict (kind, value) do nothing;

do $$ begin
  raise notice 'PASS 48_suppressions: % entries on the do-not-contact list', (select count(*) from suppressions);
end $$;
