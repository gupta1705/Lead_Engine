# The Lead Engine's API and MCP server

Use the Lead Engine from another program, or from an AI assistant such as Claude.

- **The API** is plain JSON over HTTPS, under `https://tvf-lead-engine.onrender.com/api/v1`.
- **The MCP server** is at `https://tvf-lead-engine.onrender.com/mcp`. It offers the same actions as tools that an
  assistant can call (claude.ai, Claude Desktop, Claude Code, Cursor and others).

Both work **as you**: with a key you make in the app, or, for claude.ai, by signing in as you.

## What it can and cannot do

| It can | It cannot |
|---|---|
| list projects, search leads, read a lead in full | run a refresh, or spend Apollo credits |
| read any Outreach folder, and any email in full | connect or use anyone's Gmail |
| add a lead you found by hand, with the email to it **as a draft** | reach the app's own pages and endpoints |
| shortlist or reject a lead | make, see or revoke keys |
| change a draft's subject, text or CC, or withdraw it | |
| **approve an email**, only if you allowed it (see below) | |

**Approving sends the email.** It is exactly the app's own Approve:

- the same checks, refused when the email fails one;
- your Gmail, signed by you;
- the project's sending window (10:00 to 10:30 on the recipient's clock) and its daily limit;
- the project's CC, and its follow-up four days later.

The email shows "Approved by you, through the API or an assistant (MCP)". **Withdraw** takes back an approved email
until it starts going out.

Each key, and each connected app, either may approve or may not. You choose when you make the key, or when you
allow the app. A key that may not approve can still do everything else.

## Getting a key

1. In the app, open the account menu at the bottom of the sidebar, then **API and MCP**.
2. Name the key (for example *Claude on my laptop*). Untick **It may approve emails** if this key should only read
   and draft. Then press **Make a key**.
3. **Copy it straight away.** It starts with `tle_`, is shown once, and can never be shown again. Only its
   fingerprint is kept.

Rules for keys:

- **Keep it like a password.** Anyone who has it can do, as you, what the key allows.
- **Lost or leaked:** press **Revoke** next to it, and make a new one. A revoked key stops within half a minute.
- **Limits:** up to 10 live keys per person, and up to 120 calls a minute per key.
- **People leaving:** a key stops when its person's login is removed. It also doesn't work while that login is
  still on its starting password.

## Connecting an assistant (MCP)

**claude.ai** (in the browser) needs no key:

1. In claude.ai: **Settings**, **Connectors**, **Add custom connector**.
2. Paste `https://tvf-lead-engine.onrender.com/mcp`, and press **Add**.
3. Press **Connect**. The Lead Engine opens: log in if it asks, then **Allow**. Untick **Also approve emails** if
   Claude should only read and draft.
4. You land back in claude.ai, connected.

The connection shows in the app (**API and MCP**) as a connected app. **Disconnect** there ends it.

**Claude Code:**

```bash
claude mcp add --transport http lead-engine https://tvf-lead-engine.onrender.com/mcp --header "Authorization: Bearer tle_YOUR_KEY"
```

Without `--header`, Claude Code signs in through the browser, as claude.ai does.

**Claude Desktop** needs Node.js installed. Add this to `claude_desktop_config.json` (Settings, Developer, Edit
config), then restart Claude:

```json
{
  "mcpServers": {
    "lead-engine": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://tvf-lead-engine.onrender.com/mcp", "--header", "Authorization:${AUTH}"],
      "env": { "AUTH": "Bearer tle_YOUR_KEY" }
    }
  }
}
```

**Other clients** (Cursor and the like): a Streamable HTTP server at `/mcp`. Either sign in (OAuth), or send the
header `Authorization: Bearer tle_YOUR_KEY`.

The app's **API and MCP** window shows these snippets with your own key filled in, right after you make it.

Then ask in plain words, for example:

- *"What's in my LCX Clipping drafts?"*
- *"Find shortlisted production houses in Los Angeles."*
- *"Add Northlight Pictures, maya@northlight.com, to US Production Houses with a short intro email, show it to me,
  and approve it if I say so."*

### The tools

| Tool | What it does |
|---|---|
| `whoami` | Your name and title, your connected Gmail addresses and today's room on each. |
| `list_projects` | Every project: its slug, what its leads are called, its lead counts, its follow-up and default CC, and for LCX Services the services an email may pitch. |
| `search_leads` | One project's leads, best score first. Filter by status, by text, and by whether there is an address. |
| `get_lead` | One lead in full: score and analysis, place, contacts (and which one an email goes to), and its email. |
| `list_emails` | One Outreach folder (`drafts`, `followups`, `approved`, `sent`, `replies`, `attention`), with counts for every folder. |
| `get_email` | One email in full, as you would send it. |
| `add_lead` | A lead found by hand, with its email **as a draft**. `dry_run` checks it and shows how it reads, and adds nothing. |
| `decide_lead` | Shortlist, or reject with a reason. Rejecting withdraws its waiting email. |
| `edit_draft` | Change a draft's subject, text or CC. |
| `approve_email` | Approve a draft or follow-up draft. **It will be sent.** Only with a key or connection that may approve. |
| `withdraw_email` | Take back a draft, or an approved email not yet gone. |

The server speaks the MCP initialize handshake, protocol versions 2024-11-05 to 2025-11-25. It is stateless: every
call is one POST, answered with JSON. Signing in is OAuth 2.1: discovery (RFC 9728 and RFC 8414), dynamic client
registration, PKCE S256 and rotating refresh tokens.

## The API

Send the key on every call: `Authorization: Bearer tle_...`. Bodies are JSON. The full machine-readable description
is at `/api/v1/openapi.json` (with a key).

| Call | What it does |
|---|---|
| `GET /api/v1/me` | Who this key works as. |
| `GET /api/v1/projects` | Every project, with its lead counts. |
| `GET /api/v1/projects/{project}/leads?status=open&q=&has_address=&limit=25&offset=0` | Search a project's leads. `status`: open, shortlisted, contacted, in_conversation, rejected, archived, all. |
| `POST /api/v1/projects/{project}/leads` | Add a lead found by hand, with its email as a draft (below). |
| `GET /api/v1/leads/{id}` | One lead in full. |
| `POST /api/v1/leads/{id}/decision` | `{"decision": "shortlist" or "reject", "reason": "..."}` |
| `GET /api/v1/projects/{project}/emails?folder=drafts&limit=25&offset=0` | One Outreach folder. |
| `GET /api/v1/emails/{id}` | One email in full. |
| `PATCH /api/v1/emails/{id}` | `{"subject": ..., "body": ..., "cc": [...]}`. Drafts only. |
| `POST /api/v1/emails/{id}/approve` | Approve it. **It will be sent.** Only with a key that may approve. |
| `POST /api/v1/emails/{id}/withdraw` | Take back a draft, or an approved email not yet gone. |

Adding a lead:

```bash
curl -X POST https://tvf-lead-engine.onrender.com/api/v1/projects/us-production-houses/leads \
  -H "Authorization: Bearer tle_YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"company": "Northlight Pictures", "website": "northlight.com", "country": "US", "city": "Los Angeles",
       "contact_name": "Maya Chen", "role": "Head of Development", "email": "maya@northlight.com",
       "subject": "{{company}} and The Viral Fever",
       "body": "Hi {{first_name}},\n\nI came across your slate and would love to talk about a series together."}'
```

Then, to send it, use the `email_id` it returns:

```bash
curl -X POST https://tvf-lead-engine.onrender.com/api/v1/emails/EMAIL_ID/approve -H "Authorization: Bearer tle_YOUR_KEY"
```

What you send when adding a lead:

- **Required:** `company`, `email`, `subject` and `body`.
- **Placeholders:** `{{first_name}}` and `{{company}}` are filled in. Don't add a sign-off: yours goes under it.
- **Optional:** `contact_name`, `role`, `website`, `country` (sets when it lands: 10:00 to 10:30 there), `city`, and
  `cc` (omit it for the project's default, `[]` for nobody).
- **LCX Services:** `service` is one of the services `list_projects` gives. `attach_deck` defaults to true.
- **`dry_run: true`** checks it and shows how it reads, and adds nothing.

The rules are the app's **Add a lead** rules:

- A lead already in the project is used, not added twice.
- A draft the software wrote for it, which nobody approved yet, is replaced.
- Refused: a lead already contacted, an address or company that already has a first email from us in any project,
  our own addresses, and countries the project never emails.

The answer (`201`) gives:

- `lead_id` and `email_id`;
- `reads_as`, the email exactly as it will read;
- what it matched, if anything.

Errors:

| Status | Meaning |
|---|---|
| `401` | No key, or the key or sign-in is unknown, revoked or expired. |
| `403` | A key used outside `/api/v1` and `/mcp`, or approving with a key that may not. |
| `404` | No such project, lead or email. |
| `409` | The app refused it, for example a draft that fails a check. The reason is given. |
| `422` | The lead cannot be taken. `problems` names each field. |
| `429` | Over 120 calls a minute. |

## How it is built

- **The API and MCP server:** `app/api_v1.py`. The eleven actions call the app's own endpoint functions, so a rule
  that holds on the page holds here.
- **Signing in:** `app/oauth.py`.
  - The documents at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server`, then
    `/oauth/register`, `/oauth/authorize` (the page that asks you) and `/oauth/token`.
  - A connected app's access token lasts an hour. Its refresh token lasts 60 days and is used once.
- **The keys and connections:** `sql/43_api_keys.sql` and `sql/44_api_approve_oauth.sql`. Only a SHA-256 of each
  key, code and refresh token is kept.
- **Drafts and added leads:** made the way the app's own Add a lead makes them (`tools/manual_lead.py`).
- **Tests:** `tools/test_api_v1.py` and `tools/test_oauth.py`.
