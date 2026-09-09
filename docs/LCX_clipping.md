# Segment 3: LCX clipping

Built 2026-09-09. The engine's first sales segment, for LCX's clipping service:
turning long-form episodes and videos into short vertical clips. It is the
first segment that proves the "a segment is a config row plus connectors"
promise end to end, and the first one whose discovery runs entirely in the
cloud.

## Who it finds

Creators and podcasters with a deep back catalogue and few or no shorts, in
countries where cold business email is lawful. The tiers, from the planning
conversation:

| Tier | Who | Found through |
|---|---|---|
| 1 | Video podcasters with a catalogue | Apple's podcast search, then the show's own feed |
| 2 | Long-form YouTube creators: interviews, finance, education, commentary, sport | YouTube Data API channel search |
| 3 | Coaching institutes, regional publishers, companies that run webinars | YouTube, same connector, different queries |

Networks, broadcasters, children's content and music are gated out.

## How it is wired

Everything segment-specific is in `config/segment.lcx-clipping.json`, applied
to the database by `sql/03d_segment_lcx_clipping.sql` (regenerate with
`python tools/gen_segment_sql.py lcx-clipping` after editing the JSON).

| Step | Tool | What it does |
|---|---|---|
| Discover | `tools/discover_podcasts.py` | Keyless. Search terms x store countries against Apple's public podcast search, then each new show's RSS feed: catalogue size, cadence, episode length, categories, language, the published business address, budget signals in the show notes, a YouTube link. Computes the scoring inputs it can settle. |
| Discover | `tools/discover_youtube_channels.py` | Channel search (100 quota units each), then statistics and the last 50 uploads with durations (3 units per channel). Shorts gap, cadence, audience band, video-first. |
| Promote | `tools/run_chain.py` with `SEGMENT_SLUG=lcx-clipping` | The same self-exclusion, promote, dedupe, zero-unverified, score and gate chain as TVF. The chain SQL now reads its segment from the session. |
| Enrich | `tools/enrich_clipping.py` | Lifts the feed and channel evidence to the top level of metadata, creates the contact from the published address, profiles YouTube channels linked from podcast feeds, then re-runs the chain to score the new evidence. |
| Enrich | `tools/enrich_sitescrape.py` (Find contacts on sites) | For shows with a website and no address. |
| Draft | `tools/outreach.py draft` | The clipping template with a hook built from the show's own numbers. |

The weekly refresh for the segment (Wednesday 02:00 UTC) is
`discover_podcasts, discover_youtube, promote_chain, enrich_clipping, enrich_contacts, promote_chain`.
It runs from the in-app scheduler; nothing in this segment needs the office n8n.

## The rubric

| Criterion | Points | Set by |
|---|---|---|
| Deep back catalogue (100+ long items) | 25 | feed or channel |
| Weekly cadence, active in 90 days | 15 | feed or channel |
| Shorts gap (under 10% of uploads are shorts) | 25 | channel only; unassessed for audio-only shows |
| Audience 10k to 1M subscribers | 15 | channel only |
| Budget signals (sponsors, Patreon, merch, courses) | 15 | feed or channel |
| A business address to write to | 10 | engine |
| Language LCX edits well | 5 | feed or channel |

Modifiers: network-owned (penalty 20), video-first (bonus 6). Gates: country
allowed, active, not kids or music, some reachable presence, not a major
network. Thresholds: reviewable at 25, priority at 45, like TVF.

## Running it

From the portal: pick **LCX Clipping** in the Projects menu, then Create runs
any job, or Operations shows them all. From a terminal:

```bash
SEGMENT_SLUG=lcx-clipping python tools/discover_podcasts.py --max-searches 60 --limit-feeds 300
```

```bash
SEGMENT_SLUG=lcx-clipping python tools/discover_youtube_channels.py --max-searches 15 --limit-channels 400
```

```bash
SEGMENT_SLUG=lcx-clipping python tools/run_chain.py
```

```bash
SEGMENT_SLUG=lcx-clipping python tools/enrich_clipping.py
```

Then the chain again, and the board fills. Drafts:

```bash
SEGMENT_SLUG=lcx-clipping python tools/outreach.py draft
```

## Sending as LCX

The segment sends from its own mailbox. Set `GMAIL_SENDER_ADDRESS_LCX_CLIPPING`
in `.env`, run `SEGMENT_SLUG=lcx-clipping python tools/outreach.py auth` once
(the token lands in `.gmail_token.lcx-clipping.json`), and fill the `SET_ME`
sender name and postal address in the config. Send and pull are the same
commands with `SEGMENT_SLUG=lcx-clipping`; each only touches this segment's
rows and its own daily cap.

## The portal

The main portal lists every segment under Projects; switching changes every
screen. A separate clipping-only portal is the same image with two variables,
`deploy/render.lcx-clipping.yaml` (Blueprint Path on Render). See
`docs/DEPLOY.md`.

## Not built yet, by decision

- Follow-up threads (an opener plus two follow-ups, then stop) and batch
  approval of templated mail. Both change a guarantee the owner set for TVF
  and need an explicit yes.
- Mailbox rotation and warm-up. Needed above roughly forty sends a day.
- Sample-first outreach: a "needs sample" state where the draft waits until
  three clips are attached. Cheap to add once the production side exists.
- Podcast Index as a second directory (needs a free key). Apple alone gives
  more shows than the sending capacity can use.
