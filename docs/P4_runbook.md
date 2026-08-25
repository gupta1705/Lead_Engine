# P4 — YouTube connector runs live

**One sitting, ~45 min** (plus ~15 min if Docker needs installing).

The first rung where the machine finds leads instead of you. Everything is
authored, re-verified and waiting — this is the run.

---

## Everything on the repo side is done

| | |
|---|---|
| Connector re-adopted from history | `n8n/discovery/` — workflow + 4 code nodes |
| Code re-verified | **24 fixture checks pass** (`node n8n/discovery/test/run_fixtures.js`) |
| Workflow SQL parsed | 3 embedded statements, valid PostgreSQL |
| Config key it reads | `youtube_discovery_queries` — confirmed present, 6 queries |
| Target columns | `staging_candidates` + `source_runs` — confirmed against the live DB |
| Reset script | `sql/90_reset_prototype.sql` — written, destructive-guarded |
| Zero-unverified rule | generalised to all sources, so YouTube rows score like the rest |

Re-run all of it at any time with `python tools/verify_repo.py`.

**One behaviour change worth knowing before you look at results:**
`genre_fit` from a search-query match now scores **0.5, not 1**. The fixture run
caught it awarding full marks to every channel a genre-flavoured query surfaced,
Netflix included. All the connector actually knows is that YouTube matched the
channel to a string like *"workplace comedy channel"* — real evidence, but weak.
Left at 1 it would have inflated every YouTube lead by up to 15 points against
your hand-researched rows, and Checkpoint 1 (P11) compares approval rate *per
source*. A reviewer who watches the channel can raise it.

---

## Part 1 — Get n8n running (first time only)

Docker is not installed on this machine and the previous n8n host is gone.
There are two ways in, and the second needs no Docker at all.

### Option A — npm (no Docker, already set up for you)

n8n is a Node application and you have Node v22. Installed globally via npm:

```
n8n start
```

Then open **http://localhost:5678**. This is the path taken here, because
installing Docker Desktop needs admin rights, WSL2 and usually a reboot.

Trade-off worth knowing: this runs n8n as a plain process under your user
account. It stops when you close the terminal and does not restart with the
machine. That is fine through Phase B, where every run is triggered by hand.
It stops being fine at **P25 (Unattended)**, where scheduled runs need
something that survives a reboot — that is the natural moment to move to
Option B.

### Option B — Docker (better for P25 onward)

1. Install **Docker Desktop** (docker.com) and let it start.
2. From the repo root:
   ```
   cd docker
   docker compose up -d
   ```
3. Check it is alive: `docker compose logs -f n8n`.

`docker/docker-compose.yml` binds the port to `127.0.0.1`, so the editor is
never exposed to your network, and `restart: unless-stopped` brings it back
after a reboot.

### Either way: create the owner account

First visit to http://localhost:5678 asks for an email and password. **Do this
part yourself** — I do not create accounts or enter passwords. It is local to
this machine, takes thirty seconds, and n8n will not let you past it.

---

## Part 2 — Two credentials (~5 min)

**Postgres** — n8n → Credentials → Add → **Postgres**. Take the values from
your `.env`; the connection details are the same ones `SUPABASE_DB_URL` holds.
Name it exactly **`Supabase — Lead Engine`** and the imported workflow will link
itself without you re-pointing five nodes.

**YouTube** — n8n → Credentials → Add → **Query Auth**.
- Name: `YouTube Data API Key`
- Parameter name: `key`
- Value: your `YOUTUBE_API_KEY`

---

## Part 3 — Import and run (~10 min)

1. n8n → Import from File → `n8n/discovery/conn_youtube_api.json`. Ten nodes
   appear.
2. Re-link credentials on the 5 nodes that need them. **This is normal for any
   imported workflow** — credentials are tied to an instance ID, not a name —
   not a sign anything is broken. `n8n/discovery/SETUP.md` lists exactly which
   nodes and covers the one parameter-binding quirk that varies by n8n version.
3. Click **Test workflow**.

Watch the node counters as it runs. Expect roughly: 6 items out of Split
Queries → up to 150 out of Flatten → fewer out of Filter/Score, because that
node is *supposed* to discard things.

---

## Part 4 — Verify (~10 min)

```
python tools/run_sql.py -c "select count(*) from staging_candidates where source='youtube_api';"
python tools/run_sql.py -c "select * from source_runs where source='youtube_api' order by started_at desc limit 1;"
```

**Done when:** `staging_candidates` has real YouTube rows, one `source_runs` row
records the run, and a spot-check looks sane.

Spot-check three or four `raw` values. Each should carry a `scoring_inputs`
object with at least `has_reachable_presence: true`, plus `genre_fit`,
`geography_signal` or `major_or_oversized_signal` where the evidence existed.
Several should have a real `domain` pulled out of the channel description.

Nothing is reviewable yet — these sit in staging until **P9** promotes them into
`entities`. That is the design: raw finds never touch the table you review.

---

## Quota — the thing that actually constrains this

YouTube gives **10,000 units/day free**, and the two calls are priced very
differently:

| Call | Cost | This run |
|---|---:|---:|
| `search.list` | **100 units** | 6 × 100 = **600** |
| `channels.list` | **1 unit** | ~150 × 1 = **150** |

So one full run costs ~750 units — about 13 runs a day. **Searches are the
scarce thing**, which is why the connector searches narrowly and reads widely.
If you widen the query list later (P27), that is the number that moves.

A quota error looks like HTTP 403 `quotaExceeded`. It resets at midnight
Pacific.

---

## If the first run looks wrong

**Wrong companies admitted.** Expected on run one — the keyword list and the
1,000-subscriber floor in `03_filter_score_shape.js` are starting values, not
final. Tune, then reset and re-run:

```
python tools/run_sql.py sql/90_reset_prototype.sql --dry-run --allow-destructive
python tools/run_sql.py sql/90_reset_prototype.sql --allow-destructive
```

The reset clears staging and the run log but **never touches `rejected`
entities** — those are the shield that stops a re-run resurfacing a company
someone already refused.

**Results attached to the wrong query.** `02_flatten_search_results.js` pairs
search responses to queries by array index. The fixtures prove the logic, but
they cannot prove n8n preserves item order through an HTTP node under live
conditions. If `matched_query` looks wrong on real rows, that pairing is the
first place to look — it is flagged in the file's own header comment.

**A node errors.** Note which node and the exact text. The two likely families
are a YouTube API error (quota, key not enabled, key restricted to the wrong
API) or a Postgres parameter-binding mismatch, which `SETUP.md` step 5 covers.

---

## Then

P5 — the Google News RSS connector. Same shape, and the rung that can finally
set `international_ip_experience`, the 30-point criterion that is currently a
defaulted zero on nine of your ten leads.
