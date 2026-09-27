-- 30_accounts_mailboxes.sql -- one login per person, each with their own Gmail (owner, 2026-09-26)
--
-- The owner asked for an account per person (suhasc@, kartikeyap@, upangyay@theviralfever.com),
-- each linked to one or more Gmail addresses with their own 35-a-day limit, and to see which
-- account reached out to each lead. Additive only: new columns on app_users and one new table.
--
--   app_users.name / title        the sign-off on the emails that person approves: they go out
--                                 from that person's own Gmail, signed by them
--   app_users.must_change_password
--                                 a starting password handed out by the owner works once; the
--                                 first sign-in asks for the person's own
--   user_mailboxes                a Gmail address the owner linked to a person (tools/users.py
--                                 gmail <login>). token_enc is Google's sign-in for it, sealed
--                                 for the server with a key derived from its SESSION_SECRET
--                                 (tools/mailbox_store.py): the database alone cannot send mail
--                                 as anyone. Removing a login removes its connections.

alter table app_users add column if not exists name text;
alter table app_users add column if not exists title text;
alter table app_users add column if not exists must_change_password boolean not null default false;
alter table app_users add column if not exists password_changed_at timestamptz;

create table if not exists user_mailboxes (
    id uuid primary key default gen_random_uuid(),
    user_email text not null references app_users (email) on delete cascade on update cascade,
    address text not null,
    token_enc text not null,
    daily_cap integer not null default 35 check (daily_cap between 1 and 2000),
    enabled boolean not null default true,
    connected_at timestamptz not null default now(),
    last_error text,
    last_error_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- one connection per address, whoever made it; a person may connect several
create unique index if not exists uq_user_mailboxes_address on user_mailboxes (lower(address));
create index if not exists ix_user_mailboxes_user on user_mailboxes (lower(user_email));

-- sent today per mailbox, for the per-address 35-a-day count
create index if not exists ix_outreach_sender_day on outreach (lower(sender_address), sent_at)
    where direction = 'outbound' and sender_address is not null;
