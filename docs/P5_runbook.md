# P5 — Google News RSS connector

**~30 min.** The infrastructure is already standing from P4, so this rung is
mostly "run it and read what comes back".

---

## Why this connector matters more than the last one

P4 taught us something concrete: **YouTube surfaces channels, and the companies
this segment wants mostly do not run channels.** 125 candidates, 4 usable
websites, and a harvest full of solo animators and regional video shops.

News RSS looks for a different thing entirely — **trade-press announcements of
deals**. That is the actual footprint of a company that co-produces and licenses
IP: it shows up in Variety and Deadline when it signs something.

It is also the **only source that can set `international_ip_experience`** — 30
points, the heaviest criterion in the rubric, currently a defaulted zero on nine
of your ten leads.

And it costs nothing: Google News exposes search as RSS, so there is no API key,
no quota, no signup. Six queries, six feed reads.

---

## Already done

| | |
|---|---|
| Workflow | `n8n/discovery/conn_google_news_rss.json` — 8 nodes, imported |
| Credentials | Postgres linked; **no API key needed for this source** |
| Code nodes | `11_split_news_queries.js`, `12_extract_companies.js`, shared `04_summarize_source_run.js` |
| Fixtures | **28 checks green** (`node n8n/discovery/test/run_news_fixtures.js`) |
| Config | `news_rss_discovery_queries` — 6 deal-focused queries, live in the DB |

---

## Run it

1. http://localhost:5678 → **conn_google_news_rss**
2. **Test workflow**

Then:

```
python tools/run_sql.py -c "select count(*) from staging_candidates where source='google_news_rss';"
python tools/run_sql.py -c "select name, raw->'scoring_inputs' as inputs, raw->>'headline' as headline from staging_candidates where source='google_news_rss' limit 15;"
```

**Done when:** rows tagged `source='google_news_rss'` exist, and — the part that
actually matters — **spot-check that `international_ip_experience` is set
correctly on a real hit.** Open the `source_url` of a row that got the 30 points
and confirm the headline really does describe a format or co-production deal.

---

## What the extractor will and will not do

**It only credits the 30 points on cross-border IP language** in the headline or
summary: *format rights, adaptation rights, remake rights, local adaptation,
English-language remake, co-production*. The query that found the article earns
nothing — that was P4's `genre_fit` mistake and it is deliberately not repeated.

**A domestic commission earns a different, weaker claim.** "Netflix Orders Series
From X" sets `distribution_relationship` (20 pts), not
`international_ip_experience`. Getting a show commissioned proves route to
market; it says nothing about adapting foreign IP.

**Ambiguous phrasing earns nothing.** "Acquires the rights" could be a Korean
format or a domestic novel. It is recorded in `raw.ambiguous_phrases` for a
reviewer to judge, and scores zero automatically.

**Names must end in a company suffix.** *Lantern Row Media* is admitted; a bare
*Lantern Row* is not. This throws away real companies on purpose — a wrong name
here becomes a wrong company in the review queue and eventually a cold email to
a stranger, while a missed one costs only a lead we never knew about.

**Buyers and trade outlets are never leads.** Netflix, BBC, Variety and ~40
others are excluded, so a deal headline yields the seller rather than the
streamer that bought it.

**Geography, size and genre are left blank**, because a headline cannot tell you
any of them. `04b_zero_unverified.sql` turns those blanks into explicit zeros
before scoring and records them as unverified.

---

## Expect low volume, and do not read that as failure

Six queries against a news feed will not return 125 rows. Trade press announces
maybe a handful of relevant deals a week, and the extractor discards anything it
cannot name confidently.

**Ten well-evidenced rows from this source are worth more than the entire
YouTube harvest**, because each one arrives with the criterion the rubric weighs
most heavily already proven — and with a headline URL a reviewer can check in
fifteen seconds.

If a run returns nothing at all, that is a query problem, not a plumbing
problem: widen `news_rss_discovery_queries` in config and re-run. The connector
is config-driven, so that is an edit to one JSON array followed by
`python tools/run_sql.py sql/03b_sync_segment_config_v3.sql`.

---

## Then

**P6 — X-intent signals.** Same RSS mechanism, different query set, so it should
be quick. It is also the rung that first proves cross-source dedupe matters: run
YouTube and News RSS back to back and a company that both find must produce
**one** entity, not two.
