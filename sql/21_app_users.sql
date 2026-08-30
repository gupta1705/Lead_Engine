-- 21_APP_USERS.SQL
-- Accounts for the web UI, ahead of it going public.
--
-- Design, stated briefly because auth is where cleverness goes to die:
--   * passwords stored as bcrypt hashes, never anything else
--   * the FIRST account is created through the setup screen the app shows
--     when this table is empty -- the owner types their own password into
--     their own app; nothing here ever ships a default credential
--   * further accounts via tools/users.py, run by the owner
--   * roles: 'owner' can manage users later; 'member' works the queue.
--     Enforcement beyond that is a later rung -- today every authenticated
--     user sees the same tool.
--   * RLS service-only like every other table: the anon key must never read
--     password hashes.

create table if not exists app_users (
    id uuid primary key default gen_random_uuid(),
    email text not null unique,
    password_hash text not null,
    role text not null default 'member' check (role in ('owner', 'member')),
    created_at timestamptz not null default now(),
    last_login_at timestamptz
);

alter table app_users enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'app_users' and policyname = 'service_all') then
    create policy service_all on app_users
      for all to service_role using (true) with check (true);
  end if;
end $$;
