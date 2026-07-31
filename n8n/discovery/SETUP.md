# Setting up `conn_youtube_api` — one-time import guide

This connector was authored and logic-validated outside n8n (see `code/*.js` and the
test harness results). Bringing it to life is a one-time setup: two credentials,
one import, one test run.

## 1. Create the YouTube API credential

n8n → **Credentials** → **Add credential** → search **"Query Auth"**.
- Name: `YouTube Data API Key`
- Query parameter name: `key`
- Value: your S0.4 API key

Save.

## 2. Confirm your Supabase credential name

This workflow expects your existing S2.1 Postgres credential to be named
**`Supabase — Lead Engine`**. If yours has a different name, that's fine — you'll
just re-point each Postgres node at your actual credential in step 4 below.

## 3. Import the workflow

n8n → **Connectors** folder → **Create workflow ▾** → **Import from File** (or
drag-and-drop) → select `n8n/discovery/conn_youtube_api.json`.

You should see 10 connected nodes appear: a trigger, 2 Postgres nodes feeding
into the search, 2 HTTP Request nodes (YouTube search + channel details), 3 Code
nodes (the validated scripts), and a final branch writing to both
`staging_candidates` and `source_runs`.

## 4. Re-link credentials (expected — not an error)

Because credentials are tied to your n8n instance's internal IDs, not names, a
freshly imported workflow always shows its credential-using nodes as needing
reassignment. Click into each of these 4 nodes and pick the right credential
from the dropdown:
- **Load Config** → your Supabase credential
- **Search Channels** → `YouTube Data API Key`
- **Get Channel Details** → `YouTube Data API Key`
- **Insert Staging Candidates** → your Supabase credential
- **Insert Source Run** → your Supabase credential

This is normal for any imported n8n workflow, not a sign anything's broken.

## 5. One thing to verify on the two Postgres INSERT nodes

The **Insert Staging Candidates** and **Insert Source Run** nodes use
parameterized queries (`$1, $2, ...`) rather than inlining values directly into
the SQL text — this is deliberate, since a company name or description
containing an apostrophe would otherwise break the query (we hit this exact
class of bug twice already in this project). Depending on your n8n version, the
field where you enter the parameter list may be labeled differently than where
I placed it in the JSON (e.g. a dedicated "Query Parameters" field vs. an
options sub-field). If the node's UI doesn't show your parameter values in the
place you'd expect, look for a "Query Parameters" or similar field near the
query box — the *values* to put there are already correct:

- **Insert Staging Candidates**: `{{ $json.segment_id }},{{ $json.name }},{{ $json.domain }},{{ $json.source }},{{ $json.source_url }},{{ JSON.stringify($json.raw) }}`
- **Insert Source Run**: `{{ $json.segment_id }},{{ $json.source }},{{ $json.candidates_found }},{{ $json.candidates_new }},{{ $json.status }}`

## 6. Run it

Click **Test workflow**. Expect it to fan out to 6 YouTube searches, flatten
and dedupe into individual channels, fetch full details per channel, filter
down to the ones that look like real studios, and write the survivors to
`staging_candidates` plus one summary row to `source_runs`.

## What "it worked" looks like

- Every node shows green.
- `select count(*) from staging_candidates where source = 'youtube_api';` returns
  something greater than 0 (exact count depends on real search results — there's
  no fixed target).
- `select * from source_runs where source = 'youtube_api' order by started_at desc limit 1;`
  shows one row with `candidates_found` matching that count.
- Spot-check a few `raw` values in `staging_candidates` — each should have a
  `scoring_inputs` object with at least `has_reachable_presence: true`, and
  `genre_fit`, `geography_signal`, or `major_or_oversized_signal` present when
  the underlying evidence existed.

## If something errors

Paste the exact error text and which node it came from — the two likeliest
categories are (a) a YouTube API error (quota, key not enabled, malformed
request) or (b) a Postgres parameter-binding mismatch per step 5 above. Both are
quick fixes once we can see the real error.

## After a successful run (S3.8 exit criteria met)

Review the admission filter's judgment calls in `03_filter_score_shape.js` —
the keyword list and subscriber floor are starting values, not final. Tune
them based on what actually got included/excluded, then re-run. Once you're
happy with the results, add a weekly **Schedule Trigger** to the workflow
(early Monday / Sunday night) alongside the existing Manual Trigger — that's
S3.9, and it's the last step before this connector is fully live.
