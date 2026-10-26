-- 44_API_APPROVE_OAUTH.SQL
-- The owner, 2026-10-26, on the API and MCP server (sql/43): approving through it, "Yea allow it", and connecting
-- claude.ai in the browser, "yup". app/api_v1.py and app/oauth.py.
--
-- 1. An email approved through the API or MCP is recorded as such: approval_mode 'api', approved by the person
--    whose key it was (the page says "approved through the API"). It goes through exactly the app's own approval
--    (app/main.outreach_decide): the same checks, the same signing, the same sending window and daily limit.
-- 2. Each key says whether it may approve (and so send): api_keys.can_approve. A key made in the app is asked
--    when it is made; a claude.ai connection when it is allowed. Keys made before this may (the owner's "allow it").
-- 3. OAuth 2.1 for MCP clients that sign in rather than take a key (claude.ai's custom connectors, Claude Desktop
--    and Code too): a client registers itself (RFC 7591), a signed-in person allows it on a page of ours, and it
--    gets an access token, which is an api_keys row that expires within the hour (client_id names the client), and
--    a refresh token that renews it, rotated on every use. Codes and refresh tokens are kept only as SHA-256.
--    Revoking the connection in the app (account menu, API and MCP) ends both.

alter table outreach drop constraint if exists outreach_approval_mode_check;
alter table outreach add constraint outreach_approval_mode_check
    check (approval_mode is null or approval_mode in ('single', 'batch', 'compose', 'api'));

alter table api_keys add column if not exists can_approve boolean not null default true;
alter table api_keys add column if not exists expires_at timestamptz;           -- an OAuth access token's end
alter table api_keys add column if not exists client_id text;                   -- the OAuth client; null for a key

create table if not exists oauth_clients (
    client_id        text primary key,
    client_name      text not null,
    redirect_uris    text[] not null,
    secret_hash      text,                         -- only for a client that asked to authenticate with a secret
    auth_method      text not null default 'none' check (auth_method in ('none', 'client_secret_post',
                                                                         'client_secret_basic')),
    created_at       timestamptz not null default now(),
    last_used_at     timestamptz
);

create table if not exists oauth_grants (
    id             uuid primary key default gen_random_uuid(),
    kind           text not null check (kind in ('code', 'refresh')),
    token_hash     text not null unique,
    client_id      text not null references oauth_clients (client_id) on delete cascade,
    user_email     text not null references app_users (email) on delete cascade on update cascade,
    redirect_uri   text,                           -- a code: where it was sent
    code_challenge text,                           -- a code: PKCE S256
    resource       text,
    can_approve    boolean not null default false,
    key_id         uuid references api_keys (id) on delete cascade,   -- a refresh token: the access it renews
    created_at     timestamptz not null default now(),
    expires_at     timestamptz not null,
    used_at        timestamptz
);
create index if not exists idx_oauth_grants_key on oauth_grants (key_id);

select (select count(*) from api_keys) as keys, (select count(*) from oauth_clients) as clients;
