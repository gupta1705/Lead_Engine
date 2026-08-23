# P0 — Foundations errand

**One sitting, ~60 min.** Two halves: stand up the database, then acquire every
credential the whole ladder will ever need — in one batch, so that no rung from
P1 to P28 ever stalls on a signup.

The repo half is already done and machine-checked (`python tools/verify_repo.py`
→ GREEN). Everything below needs your hands.

> **Rebuilding from scratch (2026-08-23).** New Supabase account, nothing
> carried over. That makes Part 1 *simpler* than the plan originally assumed —
> you are building clean, not reconciling a stale row. **Do not run
> `sql/03b_sync_segment_config_v3.sql`**; it exists only to patch the old
> database and is kept for the record.
>
> **Docker + n8n are not part of this sitting.** Nothing before **P4** touches
> n8n — P1, P2 and P3 are pure SQL in the Supabase editor. Rebuild n8n at P4,
> when there is a workflow to actually put in it.

---

## Part 1 — Build the database (~15 min)

### 1.0 — Create the Supabase project

supabase.com → New project.

- **Region:** pick the one nearest you (this is an internal tool; latency is a
  convenience, not a constraint).
- **Database password:** generate one and save it in your password manager now.
  You will not need it for P1–P3 (the SQL editor doesn't ask), but you will need
  it if you ever connect a client directly, and Supabase won't show it again.
- Free tier is enough for the whole of v1.

### 1.1 — Run the three scripts, in order

Supabase → **SQL Editor** → new query → paste the whole file → Run. One file at
a time, in this order:

| # | File | What you should see |
|---|---|---|
| 1 | `sql/01_schema.sql` | `Success. No rows returned` — 5 tables, indexes, triggers, RLS on |
| 2 | `sql/02_smoke_test.sql` | `ALL SMOKE TESTS PASSED`, with `leftover_segments = 0` and `leftover_entities = 0` |
| 3 | `sql/03_segment_us_production_houses.sql` | 1 row inserted — the segment config |

`02` is self-checking and self-cleaning: it proves the triggers fire, the CHECK
constraints reject bad values, the duplicate-domain and duplicate-name indexes
hold, and deleting an entity cascades to its contacts — then deletes all of its
own test data. If any guarantee fails it aborts the whole script with a `FAIL:`
message rather than passing quietly. Run it repeatedly if you like.

### 1.2 — Confirm with `sql/00_verify_state.sql`

Read-only. Three queries; on a fresh build you want:

| Query | Expected |
|---|---|
| 1 — tables exist | **5 rows** (`contacts`, `entities`, `segments`, `source_runs`, `staging_candidates`) |
| 2 — segment config | **1 row**: `6 / 4 / 3 / 3`, `genre_fit = 15`, `right_size = 20`, `revenue_penalty = -20`, thresholds `40 / 75` |
| 3 — existing entities | **0 rows** — correct on a fresh build; P1 is what puts the first rows in |

The header comments inside `00_verify_state.sql` describe a *stale-row* case and
tell you to run `03b`. That branch applied to the old database. On this fresh
one, query 2 should match the v3 numbers on the first try — if it does, ignore
the 03b instruction entirely.

**If query 2 shows `25 / 15 / -10`,** you accidentally ran an old copy of `03`.
Re-run the current `sql/03_segment_us_production_houses.sql` after deleting the
row: `delete from segments where slug = 'us-production-houses';`

### 1.3 — Record the connection details

Supabase → Project Settings → **API**:

- Project URL → `SUPABASE_URL`
- `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` — **server-side only.** This
  key bypasses RLS entirely. It goes in n8n's credential store at P4 and in your
  local `.env`; it never goes near a browser.
- `anon` / publishable key → `SUPABASE_ANON_KEY` (not used until P18)

> **On RLS:** `01_schema.sql` enables row-level security on all five tables and
> deliberately creates **no policies**, so nothing is readable by the `anon` or
> `authenticated` roles. That is correct for now — the SQL editor and the
> service-role key both bypass RLS, and those are the only two things touching
> the data until the web app arrives. Policies get written at **P18**, when
> there is finally a browser session to write them for.

---

## Part 2 — Credentials, all in one batch (~40 min)

Fill each value into a local `.env` as you go — `cp .env.example .env` first.
`.env` is gitignored. The real runtime home for these is n8n's own encrypted
credential store; you paste them there at the rung that needs each one.

### (a) Google Cloud — one project, two APIs, ~20 min

1. **Create the project.** console.cloud.google.com → new project, e.g.
   `tvf-lead-engine`. Use the same Google account that owns the TVF Gmail you
   will send outreach from — it keeps the OAuth consent flow trivial later.
2. **Enable both APIs now** (APIs & Services → Library):
   - **YouTube Data API v3** — used at P4.
   - **Gmail API** — used at P21 (send) and P22 (read replies, apply labels).
   Enabling both now is the point of batching; a second visit later is exactly
   the stall P0 exists to prevent.
3. **API key** (Credentials → Create credentials → API key) → **restrict it**
   to the YouTube Data API v3 under "API restrictions". → `YOUTUBE_API_KEY`.
4. **OAuth client** (Credentials → Create credentials → OAuth client ID):
   - Configure the consent screen first if prompted: **External**, app name
     e.g. "TVF Lead Engine", your own email as support + developer contact.
   - Add the TVF Gmail address as a **test user**.
   - Scopes: `https://www.googleapis.com/auth/gmail.send` and
     `https://www.googleapis.com/auth/gmail.modify` (modify covers reading a
     reply *and* filing it into a label, which is what P22 does).
   - Application type: **Web application**.
   - Authorised redirect URI — exactly, no trailing slash:
     `http://localhost:5678/rest/oauth2-credential/callback`
     (n8n's standard OAuth2 callback; adjust the host only if the n8n editor is
     not reached at `localhost:5678`.)
   - → `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`.
   - Also record the sending address itself → `GMAIL_SENDER_ADDRESS`.

> **⚑ Flag for P21, not for today.** A consent screen left in **Testing**
> publishing status issues refresh tokens that expire after ~7 days — which
> would silently break the unattended reply poller at P25 roughly once a week.
> Before P21 goes live, either publish the consent screen, or fold it into the
> Google Workspace decision already scheduled at P27. Re-check Google's current
> policy at P21 authoring time rather than trusting this note.

### (b) Apollo — key **and** limits, ~10 min

1. Apollo → Settings → Integrations → **API** → create a key →
   `APOLLO_API_KEY`.
2. While you are in there, open Settings → **Plans & Billing / Credit usage**
   and write down the plan's *actual* numbers:
   - export credits per month
   - email credits per month (and whether verified-email reveals cost extra)
   - any API rate limit stated for your plan
3. **Record those three numbers in `BUILD_PLAN.md`** — the "Quota walls" bullet
   has a slot marked `APOLLO PLAN LIMITS (fill at P0)`. Phase D's batch sizing
   is guesswork until they are real.

### (c) Anthropic — 2 min

console.anthropic.com → API keys → create → `ANTHROPIC_API_KEY`.
Used only by the P22 reply classifier, on `claude-haiku-4-5-20251001`. Spend is
pennies per week at v1 volume.

---

## Done when

- [ ] `01` → `02` (`ALL SMOKE TESTS PASSED`) → `03` all run on the new project
- [ ] `00_verify_state.sql` shows 5 tables, `6 / 4 / 3 / 3`, `15 / 20 / -20`, `40 / 75`, 0 entities
- [ ] `python tools/verify_repo.py` exits GREEN (already true; re-run if you edit config)
- [ ] `.env` filled: Supabase URL + both keys, `YOUTUBE_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GMAIL_SENDER_ADDRESS`, `APOLLO_API_KEY`, `ANTHROPIC_API_KEY`
- [ ] Apollo's three real limits written into `BUILD_PLAN.md`
- [ ] P0 marked ✅ in `BUILD_PLAN.md`'s ladder

Then go straight to P1 — `sql/04_insert_template.sql` is written and waiting.

---

## Deferred to P4 (do not do it today)

**Docker + n8n.** Docker is not currently installed on this machine, and the
previous n8n host is gone with the old build. Nothing before P4 needs it: P1
(hand-enter candidates), P2 (score them), P3 (review them) are all SQL in the
Supabase editor.

When P4 arrives, that sitting starts with roughly 15 extra minutes: install
Docker Desktop → `docker compose up -d` in `docker/` → open
`http://localhost:5678` → create the n8n owner account → add the Supabase
credential from your `.env`. Budget for it then, not now.
