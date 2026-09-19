# Segment 2: struggling Mumbai startups

Rebuilt 2026-09-17. The owner's brief: *"find a list of startups that are
currently struggling based out of bombay which we can acquire for little to no
resources or give them our support."*

The segment existed since 2026-09-03 as a proof that a second segment is a
config row plus connectors: creator-tool companies in the US or India, no
connectors of its own, no leads. That targeting is replaced. The project keeps
its slug (`startup-acquisitions`), its key prefix (STA) and its outreach block,
which is untouched: who writes to a struggling founder, and how, is the
owner's call.

## Who it finds

A startup, with public evidence that it is in trouble, placed in the Mumbai
region (Mumbai, Navi Mumbai, Thane), small enough that buying it or backing it
costs little, ranked by how much TVF's content, audience and distribution
could change its trajectory.

Sector is not a filter. Every struggling Mumbai startup is kept and `tvf_fit`
ranks them: media, content, entertainment, gaming, audio, edtech and
community products first, consumer brands and apps second, fintech, SaaS,
logistics and health last. Narrowing to media-only later is a gate in the
config, not a new harvest.

## Where the evidence comes from, and where it may not

| Source | What it gives | Rule |
|---|---|---|
| Google News RSS headlines | layoffs, shutdowns, salary delays, insolvency, down and rescue rounds, sale talks; small Mumbai rounds in 2021-24 | headlines only, listed Indian publishers only |
| The startup's own website | a Mumbai-region address or PIN, another city's, a closing notice, a parked or for-sale page, App Store links | robots.txt honoured, a few pages, two seconds apart |
| Apple's App Store lookup | when its app was last updated, how many ratings it has | public API, only for an app its own site links to |

**Not used, by decision:**

- **Trade-press article pages.** Entrackr's terms say *"You must not conduct any
  systematic or automated data collection activities"*; Inc42's forbid scraping,
  data mining and spidering. Their sitemaps are open and their robots.txt
  permits crawling, but the terms decide. A row carries the headline and its
  link, and a person reads the story.
- **The Startup India (DPIIT) directory.** Its data server's robots.txt is
  `Disallow: /`.
- **LinkedIn**, as everywhere in this project.
- **Paid databases** (Tracxn, Venture Intelligence, Private Circle). They would
  give every Mumbai startup's funding history, headcount trend and filings, which is far
  better coverage than headlines. Buying one is the owner's decision; the
  engine would take it as another connector.

## How it is wired

| Step | Tool | What it does |
|---|---|---|
| Discover | `tools/discover_startup_news.py` | Distress queries India-wide (a headline rarely says where a company is) and funding queries for Mumbai, one search per quarter because a search returns at most 100 items. `--backfill` covers two years of distress and the 2021-24 funding cohort; the weekly run covers the last 40 days. |
| Promote | `tools/run_chain.py` | The same chain as every segment: self-exclusion, promote, merge, zero-unverified, score, gates. |
| Enrich | `tools/enrich_startups.py` | News by name (one search per company), its website and its app, then `score_inputs()`. |
| Contacts | `tools/enrich_sitescrape.py` (Find contacts on sites) | The founder or a role inbox, from the startup's own site. |

The headline rules live in `tools/startup_signals.py` and are a regression table,
`tools/test_startup_signals.py`, built from real headlines, including every wrong answer
the first runs gave: "Cred's", "Four Years", "Tearful Goodbye", the creditor
instead of the debtor, the acquirer instead of the acqui-hired.

Weekly refresh, Thursday 02:00 UTC: `discover_startup_news, promote_chain,
enrich_startups, enrich_contacts, promote_chain`. (Operations showed it as
Wednesday until 2026-09-19, counting days from Sunday; it has always run on
Thursday.)

## The rubric

| Criterion | Points | Evidence |
|---|---|---|
| Distress evidence | 30 | 1.0 the company itself shut down, laid off, delayed salaries, went into insolvency, raised a down or rescue round or sold in distress, or its site says it closed; 0.5 a bridge round, sale talks, a founder exit, a pivot, a unit closed, or the quiet cohort (a small round 30+ months ago, nothing since, site or app gone dark) |
| Recency | 10 | 1.0 within 6 months, 0.5 within 12 |
| Mumbai confirmed | 15 | 1.0 its own site or a "Mumbai-based" headline; 0.5 its coverage leans Mumbai |
| Small deal | 15 | largest stated round up to $5M 1.0, up to $20M 0.5 |
| TVF fit | 20 | sector tiers in config |
| Something to keep | 10 | 1.0 a live site or an app with 1,000+ ratings; 0.5 an app or a body of coverage |
| Reachable founder | 10 | set by the site-scrape pass |

Penalties: an ordinary round in the last 12 months (-20: not out of runway);
shut down more than a year ago (-15). Gates: placed outside the Mumbai region;
a unicorn, a listed company, a $50M+ round or a name on the large-company
list; already acquired; nothing heard for three years. Thresholds: reviewable
at 25, priority at 45.

## Running it

From the portal: pick the startup project from the project switcher at the
top of the sidebar, then **Operations → Run weekly refresh** runs the whole
refresh now. The backfill, and the steps one at a time, run from a terminal
(the portal's backfill and per-step buttons went on 2026-09-19):

```bash
SEGMENT_SLUG=startup-acquisitions python tools/discover_startup_news.py --backfill
```

```bash
SEGMENT_SLUG=startup-acquisitions python tools/run_chain.py
```

```bash
SEGMENT_SLUG=startup-acquisitions python tools/enrich_startups.py
```

Then the chain again.

## The first list (2026-09-17)

| Step | Result |
|---|---|
| Headlines kept | 1,378 stories on 319 startups: 253 about trouble, 1,091 about funding |
| Gated out (archived, with the reason) | 187: 82 too big (a unicorn, a listing, a $50M+ round or a name on the large-company list), 69 placed outside the Mumbai region, 33 no sign of life for three years, 3 already sold |
| Open for review | 132 |
| In the review band (25+) | 30, 12 of them in the priority band (45+) |
| Placed in Mumbai | 59 of the 132, but only 2 of the 30 in the band: Covrzy (shut down March 2026) and Zuppa (bridge round, July 2025) |
| Websites tried for a contact | 126; 70 startups now have an address, 4 of them a named founder's. Only 4 of the 30 in the band do: most of their websites are gone |

**What the first list taught, and what changed because of it.**

- *Mumbai and struggling rarely come together in a headline.* The funding cohort (Mumbai startups that raised a small round in 2021-24) placed 57 companies in Mumbai with no sign of struggle at all, and their fit and a small round carried them into the review band: Khyaal, Expertrons, SuperBottoms, Skillmatics. The brief is *struggling* startups, so a company whose coverage and website were read with no sign of trouble now takes a 40-point penalty (`no_struggle_signal`). It stays in the list, below the line, and the penalty lifts the day a headline shows trouble.
- *A shutdown headline almost never says where the company was.* 28 of the 30 in the band are "city not known": their stories name no city and, for most, their website is gone. The engine does not guess a city. The lead dialog says so ("City not known") and asks for a check of the founders' profiles or the registered address before the lead is treated as a Mumbai startup. A paid startup database would settle this in bulk; that is the owner's call.

The priority band after the penalty: Medial, Covrzy, Juleo, Kult, Freakins, NeuroPixel.AI, Beatoven.ai, Flutter, Satvacart, Klydo, Zave, Pync. Every one of them shows public trouble in 2025-26; only Covrzy is confirmed in Mumbai.
