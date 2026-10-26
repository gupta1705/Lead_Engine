# The Lead Engine's API and MCP server

Use the Lead Engine from another program, or from an AI assistant such as Claude.

- **The API** is plain JSON over HTTPS, under `https://tvf-lead-engine.onrender.com/api/v1`.
- **The MCP server** is at `https://tvf-lead-engine.onrender.com/mcp`. It offers the same actions as tools that an
  assistant can call (Claude Desktop, Claude Code, Cursor and others).

Both work **as you**, with a key you make in the app.

## What it can and cannot do

| It can | It cannot |
|---|---|
| list projects, search leads, read a lead in full | approve or send an email |
| read any Outreach folder, and any email in full | run a refresh, or spend Apollo credits |
| add a lead you found by hand, with the email to it **as a draft** | connect or use anyone's Gmail |
| shortlist or reject a lead | reach the app's own pages and endpoints |
| change a draft's subject, text or CC | make, see or revoke keys |

Every email made or changed through the API waits in **Outreach, Drafts**, signed with your name and title. It goes
out only when a person reads it and approves it in the app. The rule that a person approves every email holds here
too.

## Getting a key

1. In the app, open the account menu at the bottom of the sidebar, then **API and MCP**.
2. Name the key (for example *Claude on my laptop*) and press **Make a key**.
3. **Copy it straight away.** It starts with `tle_`, is shown once, and can never be shown again. Only its
   fingerprint is kept.

Rules for keys:

- **Keep it like a password.** Anyone who has it can do, as you, what the table above allows.
- **Lost or leaked:** press **Revoke** next to it, and make a new one. A revoked key stops within half a minute.
- **Limits:** up to 10 live keys per person, and up to 120 calls a minute per key.
- **People leaving:** a key stops when its person's login is removed. It also doesn't work while that login is
  still on its starting password.

## Connecting an assistant (MCP)

**Claude Code:**

```bash
claude mcp add --transport http lead-engine https://tvf-lead-engine.onrender.com/mcp --header "Authorization: Bearer tle_YOUR_KEY"
```

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

**Other clients** (Cursor and the like): a Streamable HTTP server at `/mcp`, with the header
`Authorization: Bearer tle_YOUR_KEY`.

The app's **API and MCP** window shows these snippets with your own key filled in, right after you make it.

Then ask in plain words, for example:

- *"What's in my LCX Clipping drafts?"*
- *"Find shortlisted production houses in Los Angeles."*
- *"Add Northlight Pictures, maya@northlight.com, to US Production Houses with a short intro email."*

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

The server speaks the MCP initialize handshake, protocol versions 2024-11-05 to 2025-11-25. It is stateless: every
call is one POST, answered with JSON. There is no OAuth sign-in, so clients that only connect through OAuth (for
example claude.ai's custom connectors) cannot use it yet. Claude Desktop through `mcp-remote` can.

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

Adding a lead:

```bash
curl -X POST https://tvf-lead-engine.onrender.com/api/v1/projects/us-production-houses/leads \
  -H "Authorization: Bearer tle_YOUR_KEY" -H "Content-Type: application/json" \
  -d '{"company": "Northlight Pictures", "website": "northlight.com", "country": "US", "city": "Los Angeles",
       "contact_name": "Maya Chen", "role": "Head of Development", "email": "maya@northlight.com",
       "subject": "{{company}} and The Viral Fever",
       "body": "Hi {{first_name}},\n\nI came across your slate and would love to talk about a series together."}'
```

What you send:

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
| `401` | No key, or the key is unknown or revoked. |
| `403` | A key used outside `/api/v1` and `/mcp`. |
| `404` | No such project, lead or email. |
| `422` | The lead cannot be taken. `problems` names each field. |
| `429` | Over 120 calls a minute. |

## How it is built

- **The API and MCP server:** `app/api_v1.py`. The nine actions call the app's own endpoint functions, so a rule
  that holds on the page holds here.
- **The keys:** `sql/43_api_keys.sql` (only a SHA-256 of each key is kept).
- **Drafts and added leads:** made the way the app's own Add a lead makes them (`tools/manual_lead.py`, drafts
  only).
- **Tests:** `tools/test_api_v1.py`.
