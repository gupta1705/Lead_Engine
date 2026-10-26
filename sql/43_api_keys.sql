-- 43_API_KEYS.SQL
-- The Lead Engine's API and MCP server (owner, 2026-10-26: "I want to build mcp and api for this so build it").
-- A program (or an AI assistant through MCP) works as one person, with a key that person made in the app
-- (account menu, API and MCP). The key acts as them: their name and title sign what it drafts, and everything it
-- does is recorded as theirs. It reaches only /api/v1 and /mcp, never the app's own endpoints, and it cannot
-- approve or send an email: a person still does that in the app (app/api_v1.py).
--
-- Only a SHA-256 of each key is kept. The key itself is shown once, when it is made, and can never be shown
-- again; a lost key is revoked and a new one made. A revoked key stays as a row (who had what, until when).
-- Removing a person's login removes their keys with it.

create table if not exists api_keys (
    id           uuid primary key default gen_random_uuid(),
    user_email   text not null references app_users (email) on delete cascade on update cascade,
    name         text not null check (length(btrim(name)) between 1 and 60),
    prefix       text not null,                    -- the key's first characters, to tell keys apart in the list
    key_hash     text not null unique,             -- sha256 hex of the whole key
    created_at   timestamptz not null default now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);

create index if not exists idx_api_keys_user on api_keys (user_email);

select count(*) as keys from api_keys;
