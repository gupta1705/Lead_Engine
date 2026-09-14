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

The segment sends from its own mailboxes, never TVF's: `main`, `second` and
`third` in the config. For each one you want to use, put its address in `.env`
(`GMAIL_SENDER_ADDRESS_LCX_CLIPPING`, `GMAIL_SENDER_ADDRESS_LCX_2`,
`GMAIL_SENDER_ADDRESS_LCX_3`) and run
`SEGMENT_SLUG=lcx-clipping python tools/outreach.py auth --mailbox main` (then
`second`, `third`) once; the token lands in `.gmail_token.lcx-clipping.<key>.json`,
which git ignores. One mailbox is enough to start. Fill the `SET_ME` sender
name and postal address in the config. `outreach.py mailboxes` shows what is
connected and how much each can send today. Send and pull are the same
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

## Mailbox rotation (2026-09-10)

Openers are spread across the connected mailboxes: each goes to the one with
the most room left today. A follow-up always leaves from the mailbox that
sent its opener, because a Gmail thread belongs to one mailbox; the database
enforces that at the moment of sending (`sql/24`), and reply pulls read each
thread through its own mailbox.

Each mailbox warms up from its first send: ten emails a day, five more every
two days, up to forty. Three warm mailboxes give 120 a day, which is also the
segment's ceiling. A bounce (a mailer-daemon reply) marks the address invalid
and ends that thread, so no mailbox writes to it again. The Mailboxes panel in
Operations shows each mailbox's cap, sends and room left today.

Use addresses on a sending domain that belongs to LCX alone, not the main
company domain, so a bad week never touches everyday mail. The signature
name is shared, so the mailboxes should belong to the same person or desk.

## The footer, and what makes each email personal (2026-09-12)

**The footer is one setting for the whole segment.** Sign-off, postal address
and the line that lets someone out used to be four lines copied into every
template. They are now `outreach.footer.text`, edited in the app under
**Outreach -> Footer**; every template ends with `{{footer}}`. Saving it also
offers to put the new footer on the drafts already waiting for approval --
only the footer is swapped, so anything written by hand above it survives
untouched. The save is refused unless what comes out carries a postal address
and a way off the list: both are required of commercial email, and both are
what keep a sending domain alive. `sql/25_outreach_footer.sql` lifted the
first version of the text out of the templates verbatim, so nothing about
what goes out changed when it was applied.

**Every email is built from that lead's own row.** Nothing is invented and no
model writes prose, so a draft cannot claim something the row does not
support. What it can say, from `tools/draft_render.py`:

| Field | What it says | Where it comes from |
|---|---|---|
| `{{greeting_name}}` | Their first name, never the show's | `metadata.host` at high or medium confidence, else the contact's own name, else `there` |
| `{{hook}}` | One or two sentences of their numbers: archive size, subscribers, cadence, average length, then the shorts gap | `podcast_feed` and `youtube_channel.recent` |
| `{{latest_work}}` | Their most recent episode **by name** | `recent.latest_title` / `podcast_feed.latest_title`, only within 120 days, screened for links and emoji, cut at 78 characters |
| `{{clip_math}}` | Their own average length turned into a number of shorts | `avg_long_minutes` or `avg_duration_min` |

Two rules keep it honest. A sentence is dropped rather than softened when the
evidence is missing -- a channel that already clips gets no shorts-gap line,
because that line would not be true of it. And a title is quoted only when it
is recent enough that calling it recent is still true; otherwise the email
says "one of your recent episodes" and names nothing.

The **phrasing** varies per lead, chosen by a hash of the lead's id: four
openings and four ways into the second sentence. Six hundred identical
sentences read as a blast to a person and to a spam filter. Because the choice
is a hash and not a random number, the same lead always renders the same way,
so redrafting never quietly changes text somebody already read.
`tools/test_draft_render.py` is the regression table for all of it.

## The opening line, written by a model (2026-09-12)

Owner's brief: "go ahead and build the groq personalisation". The first
sentence of a clipping draft may now be **written** from that lead's facts
rather than assembled from them. Everything else is unchanged: the same
template, the same footer, the same approval.

**Groq, not Gemini's free tier.** Google's API terms say content sent to the
unpaid tier is used to improve their products, with human reviewers, and tell
you not to send confidential information through it. What we would be sending
is the prospect list. Groq's documented default is no retention (30-day logs
for abuse and reliability only, with a zero-retention switch) and its services
agreement says inputs and outputs are not used for training. Volume never
decided it: the segment's ceiling is 120 emails a day against a free plan of
roughly a thousand requests.

**What the model is given** is a whitelist, not a filtered row --
`draft_render.facts_for()` -- and every number sits under the thing it
measures: `whole_youtube_channel` (videos, subscribers),
`most_recent_youtube_uploads` (how many were checked, long-form, shorts, and
the average length of the long-form ones), `podcast_feed` (episodes, cadence,
average length), plus the company name and topics from the platform's own
category list. No email address, no contact name, no scraped page text, no
URLs -- and, since the first live run, no country and no episode title (below).
A lead with no counts at all is not sent: there is nothing specific to say, and
the segment's neutral hook is the more honest line.

**What is done with what comes back**, all in `tools/llm.py`:

| Check | Why |
|---|---|
| Every number must appear in the facts, unrounded | "over 2,000 videos" for 2,185 is a claim we did not verify |
| At least one number | "creates documentary-style content" is true of anyone |
| An average may not be stated as a length | "all 60-minute pieces", "at 42 minutes each" |
| No link, address, markdown, emoji or symbols | it is a sentence, not a page |
| One or two sentences, a word cap | a model asked for a line will write an essay |
| Banned words: sales, and proportion | "guarantee", "viral", "10x"; "mostly", "majority" |
| Anything rejected falls back | the deterministic hook is always there |

A rejected answer is never retried into something weaker.

**What the first live run changed (2026-09-14).** Five of the model's sentences
had every number right and a claim wrong, and each was closed where it
started. The average length of a channel's recent long videos came back applied
to "each" of its 2,185 videos -- so the facts are now grouped by scope instead
of flat. A channel's registration country came back as "19,400 US
subscribers" -- so the country is no longer sent. The latest episode title was
mentioned in six of seven sentences, but the template already names it in the
offer line, so those emails said it twice; three also quoted a cut-off title
and one carried its emoji -- so the title is no longer sent, which also means
no text the lead controls reaches the prompt at all. "24 of 50" became
"mostly", and an average became "all 60-minute pieces" -- so both are refused.
The checks themselves had two bugs the run exposed: the m of "42 minutes" was
read as a million, and a reasoning model's token budget ran out before it
answered. Both fixed, and every case is now a row in the regression table.

What the checks still cannot catch is a claim whose numbers are all right --
"your most recent 22 long-form uploads" when the 22 are among the last 50. That
is why a written draft is approved on its own.

**It cannot break drafting.** No key, no network, a bad answer -- each ends in
the hook the engine writes itself, with a line in the log and a count at the
end of the run. `python tools/llm.py --check` proves a key works;
`--try 5` prints the built-in and the written hook side by side for five real
leads.

**The approval rule that follows.** A spot check stands for a batch because
every draft in it came from one template. A sentence written once, for one
lead, can be wrong on its own, so a written draft is **not eligible for batch
approval** (`batch_approval.allow_generated: false`) and must be approved
individually. Set that flag to true once enough of them have been read; batches
carrying written drafts then draw `generated_sample_fraction` (0.25) instead of
`sample_fraction` (0.1). The rule is enforced from `outreach.generated_hook` on
the row, which also stores the exact sentence for audit. `sql/26`.

`tools/test_generated_hook.py` is the regression table: a whitelist check, a
hostile set of model answers (rounding, links, arithmetic, markdown, refusals,
an instruction smuggled in through a title), the fallback paths, and the batch
rule end to end against the database.

## Automatic shortlisting (2026-09-14)

Owner's brief: "Instead of shortlisting i want you to automatically shortlist
anyone with score above 20." Every lead in review with a fit score strictly
above 20 is shortlisted by the last step of the promote chain
(`sql/14_auto_shortlist.sql`), so it happens after every refresh and every
re-score without anyone pressing anything. The rule is config
(`auto_shortlist`: `enabled`, `min_score`) and is on for this segment only;
the TVF segments still shortlist by hand.

What it will not do: touch a rejected, archived or contacted lead; shortlist a
score of exactly 20; or shortlist a lead again after a person has moved it back
to review. Every lead it shortlists carries `metadata.auto_shortlisted_at`, and
a stamped lead that is back in review is left there. Its status reason reads
"auto-shortlisted: score N is above 20". Turned on without a threshold, it
stops the chain rather than guess.

Shortlisting sends nothing. It makes a lead eligible for a draft, and every
draft still needs a person's approval.

**First run:** 451 leads shortlisted -- 317 in the priority band (45+), 16
between 20 and 25, 83 production houses. 255 have an email address and can be
drafted now; the other 196 wait for a contact. None of the 591 left in review
scores above 20.

**What follows from it.** **Draft emails** drafts up to 20 per press, and a
draft whose opening line Groq wrote is approved on its own, never in a batch.
255 contactable leads are therefore up to 255 individual approvals unless
`batch_approval.allow_generated` is turned on. `tools/test_auto_shortlist.py`
covers the rule (13 checks, rolled back).

## Not built yet, by decision
- Sample-first outreach: a "needs sample" state where the draft waits until
  three clips are attached. Cheap to add once the production side exists.
- Podcast Index as a second directory (needs a free key). Apple alone gives
  more shows than the sending capacity can use.
