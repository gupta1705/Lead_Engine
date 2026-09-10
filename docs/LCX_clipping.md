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
| Discover | `tools/discover_wikidata_channels.py` | Production companies worldwide with a YouTube channel on Wikidata, US first; the same 3-unit profile. |
| Discover | `tools/import_pool.py` | Carries TVF's production houses and contacts into this segment; one-off. |
| Discover | `tools/discover_youtube_channels.py` | Channel search (100 quota units each), then statistics and the last 50 uploads with durations (3 units per channel). Shorts gap, cadence, audience band, video-first. |
| Promote | `tools/run_chain.py` with `SEGMENT_SLUG=lcx-clipping` | The same self-exclusion, promote, dedupe, zero-unverified, score and gate chain as TVF. The chain SQL now reads its segment from the session. |
| Enrich | `tools/enrich_clipping.py` | Lifts the evidence, finds the person behind the show (`metadata.host`), creates the contact, corrects contacts that carried the show's name, reads the website's front page for a YouTube link, profiles the channel. |
| Enrich | `tools/enrich_sitescrape.py` (Find contacts on sites) | For shows with a website and no address. |
| Draft | `tools/outreach.py draft` | The clipping template with a hook built from the show's own numbers. |

The weekly refresh for the segment (Wednesday 02:00 UTC) is
`discover_podcasts, discover_youtube, discover_wikidata_channels, promote_chain, enrich_clipping, enrich_contacts, promote_chain`.
It runs from the in-app scheduler; nothing in this segment needs the office n8n.

## The rubric

| Criterion | Points | Set by |
|---|---|---|
| Deep back catalogue (100+ long items) | 20 | feed or channel |
| Weekly cadence, active in 90 days | 10 | feed or channel |
| Shorts gap (under 10% of uploads are shorts) | 25 | channel only; unassessed for audio-only shows |
| Audience 10k to 1M subscribers | 25 | channel only |
| Budget signals (sponsors, Patreon, merch, courses) | 15 | feed or channel |
| A business address to write to | 10 | engine |
| Language LCX edits well | 5 | feed or channel |

Modifiers: network-owned (penalty 20), audience above 2M (penalty 20),
video-first (bonus 6, eight or more long uploads among the last fifty),
US-based (bonus 8). Gates: country allowed, active, not kids or music, some
reachable presence, not a major network, not oversized (above 5M
subscribers). Thresholds: reviewable at 25, priority at 45, like TVF.

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

## First live run (2026-09-09)

Two harvests from the laptop, then promote, enrich, promote. Quota spent on
YouTube: about 2,900 units of the daily 10,000.

| | |
|---|---|
| Shows staged | 215 (138 from podcast feeds, 77 YouTube channels) |
| Ready for review | 119 (73 podcasts, 46 channels) |
| Priority band, 45+ | 67 |
| Reviewable band, 25 to 44 | 47 |
| With a published contact | 62 |
| Gated out | 86: 32 dormant, 28 disallowed country, 14 oversized, 11 no reachable presence, 1 major network |

What the run taught, already folded back into the config: a twenty-minute
floor for "long-form" threw away most education and commentary channels
(now eight minutes); a 53-million-subscriber gaming channel scored 92 because
audience only withheld points (now a gate above 5M and a penalty above 2M);
and catalogue plus cadence let a 271-subscriber show outrank the band (audience
raised to 25 points, catalogue and cadence lowered). The next runs skip every
feed and channel already known, so they only pay for new ground.

## People first, and production houses everywhere (2026-09-09, second pass)

The owner's reaction to the first pool was "why are there shows in the
software". The show is the record because it carries the evidence; the person
is who the email goes to; and the portal was showing the show twice. Three
changes, all agreed:

- **The person is pulled out.** `tools/personname.py` reads the feed's author
  and owner fields, the title ("with Doug Smith", "The Joe Rogan Experience",
  "Dr. Shawn Baker Podcast", "Rahul Jain - Business coaching") and the
  description ("hosted by ..."), and stores `metadata.host` with a confidence.
  Only high or medium confidence names a contact or a greeting; words that name
  things (podcast, studio, leadership, finance, healthcare, hoy, hablamos) rule a
  candidate out, and a single first name counts only when it is a known one.
  An existing contact that carried the show's name is corrected by the
  enrichment pass; a real person's name is never touched.
- **The portal leads with the person.** In this segment the card title is the
  host, the show sits underneath, the list's first column is "Host · show",
  the dialog says "Doug Smith, host of The L3 Leadership Podcast". Segments
  without a person-first flag render exactly as before.
- **No greeting ever uses a show name.** `greeting_for` greets by first name
  only when the contact reads as a person; otherwise the segment's
  `greeting_fallback` ("there"). The TVF segment keeps "team at {{company}}".
- **The rules are a regression table.** `python tools/test_personname.py`
  holds every case the live pool and a hostile review (2026-09-10) produced:
  "Dr. Phil", glued "Dr.Thema", initials, co-host pairs, sponsors behind "by",
  brands like "Bob Industries". Change a rule, run the table. Weak cues ("by",
  "I'm") only accept a known first name; production houses never have a
  person mined from the company name.

And the targeting widened to **creators plus production houses, worldwide,
United States first**:

| | |
|---|---|
| Geography | Everywhere except Canada, Germany, Austria and Italy (consent laws). `priority_countries: ["US"]` earns an 8-point `us_priority` bonus and six searches in ten. |
| Wikidata | `tools/discover_wikidata_channels.py`: film, TV and animation companies that list a YouTube channel (P2397), with country and website; each channel profiled for the shorts gap. `kind = production_house`. |
| TVF pool | `tools/import_pool.py --from us-production-houses`: TVF's US production houses with their contacts, carried over; the enrichment pass reads each website's front page for a YouTube link (robots honoured) and profiles the channel. |
| Studio template | `clipping_studio_v1`, chosen automatically when `metadata.kind` is `production_house`. |
| Weekly refresh | now runs the Wikidata harvest as well. The pool import is a one-off from the Create button; `import_pool.py --repair` re-derives a carried row's country and reachability from its origin if the rules change. |
| Revisiting rows | `enrich_clipping.py` stamps `clipping_enrich_version`; bumping the constant makes the weekly refresh revisit every row under new host and contact rules without repeating any network call. Transient site or channel failures are retried after a week; only definitive answers are final. |

## Follow-ups and batch approval (2026-09-10)

The owner said yes to both. They are on for this segment only; TVF keeps one
email per company and one approval per draft, because its config enables
neither.

**One thread per company.** The opener, then follow-up 1 four days later and
follow-up 2 seven days after that, both as replies in the opener's Gmail
thread, then nothing, ever. The database enforces it (`sql/23`): an opener
is unique per company, each step at most once, no more than three steps, a
follow-up must point at its own company's opener, and a follow-up can never
be claimed for sending once the company has replied or the thread was
stopped. `outreach.py pull` pauses a thread the moment a reply lands; an
auto-reply (triaged neutral) lets it resume, a real answer ends it. Anyone
can press **Stop follow-ups** on a message. Follow-ups are drafted daily at
03:30 UTC (or with **Draft follow-ups** in Outreach) and approved like any
other email. The daily send cap counts them.

**Batch approval.** In Drafts, tick the drafts and press **Approve
selected**. The server draws a random spot-check sample (at least three, or
a tenth of the batch), and the approval stays locked until each sampled
draft has been opened and ticked. The sample is signed with the batch, so it
cannot be swapped for hand-picked drafts. Every draft is checked first (no
unfilled placeholder, no SET_ME, a valid address, a company still in a
sendable state) and the failures are listed, not approved. Each approved row
records who approved it, when, whether in a batch and whether it was in the
sample; each batch is a row in `outreach_approval_batches`.

Reports now count companies contacted and follow-ups separately, and the
reply and positive rates are per company, so follow-ups cannot inflate them.
`python tools/test_outreach_policy.py` exercises every rule above against
the live database inside a transaction it rolls back.

## Not built yet, by decision
- Mailbox rotation and warm-up. Needed above roughly forty sends a day.
- Sample-first outreach: a "needs sample" state where the draft waits until
  three clips are attached. Cheap to add once the production side exists.
- Podcast Index as a second directory (needs a free key). Apple alone gives
  more shows than the sending capacity can use.
