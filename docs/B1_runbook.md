# B1 — Site-scrape enrichment (replaces P16 while Apollo is unavailable)

Reads a company's **own website** and extracts the contact details they have
chosen to publish. No API key, no subscription, no quota.

```
python tools/enrich_sitescrape.py --limit 5 --dry-run     # look, change nothing
python tools/enrich_sitescrape.py --limit 25              # write contacts
python tools/enrich_sitescrape.py --source wikidata --limit 50
```

---

## Why this is a smaller downgrade than it sounds

Apollo's documented weak spot is 2–10-person companies — which is exactly the
target profile. Your own P1 research found a published address on nearly every
site in the batch: `info@exit73studios.com`, `meerkats@meerkatmedia.org`, and
Neon Zoo publishing *both* `hello@` and the founder's direct line.

For a shop that size, a role inbox lands on a founder's desk.

The rubric already prices the difference honestly, so nothing has to be fudged:

| Found | `reachable_decision_maker` |
|---|---|
| Named person in a target role | **1.0** |
| Role inbox (`info@`, `hello@`) | **0.5** |
| Nothing published | **0** |

**Bonus criterion nothing else can set:** `collaboration_openness`. The config
gives full credit for *"an explicit collaboration/partnership invitation on
their own site"* — and this is the only source that reads their site. "Work
with us", "partner with us", "co-production", in their own words.

---

## Compliance, enforced in code rather than documented

- **robots.txt is parsed per domain and `can_fetch` is checked on every URL.**
  If robots.txt can't be read at all, the domain is **skipped** — it fails
  closed, not open.
- **2 seconds between requests**, in a `finally` block so it holds even when a
  fetch throws. These are small studios' own websites.
- **First-party pages only.** An address at another company's domain is
  discarded.
- **LinkedIn is never touched** — not the site, not a cache, not via search.
- Data stays internal. Nothing is republished.

---

## What it refuses to guess

It sets `reachable_decision_maker`, `collaboration_openness` and
`has_reachable_presence`. **Nothing else.**

Headcount, genre and revenue are not reliably legible from a homepage, and a
plausible-looking guess in those fields is worse than a blank: `04b` records
blanks in `unverified_inputs` so a reviewer can see what still needs checking,
while a fabricated `right_size` just vanishes into the score with no trace.

Email verification is **MX/DNS only** — enough to catch a dead or parked domain,
not mailbox-level. Real verification needs SMTP probing, which is both rude and
unreliable. Contacts are written as `unverified` or `catch_all` accordingly,
never as `valid`.

---

## It skips rows the pipeline already knows are wrong

Discovery captured these signals and the first version simply wasn't reading
them — it burned 4 of 10 slots on companies dissolved in 2008, 2016, 2017 and
2024.

| Skipped | Why |
|---|---|
| `activity_signal = confirmed_dormant` | Wikidata P576 dissolution date. Nobody answers a dead company's inbox. |
| `major_or_oversized_signal = true` | The gates reject them at P13 anyway. |
| Has a `parent_organisation` | The brief wants founder/partner ownership with no studio or network parent. |

For the Wikidata pool that is **309 rows → 204 addressable**. A third were never
worth a request.

---

## Expect a modest hit rate, and read it correctly

Roughly **30% of sites publish a usable address**, and most of those are role
inboxes rather than named people. Many modern sites use a contact form instead.

That is not the tool failing. It is the honest ceiling of what companies choose
to publish — and it is measured, per run, in the summary counters. A company
with no published address is recorded as `no_contact_found` with
`reachable_decision_maker = 0` rather than skipped silently, because at
Checkpoint 2 a confirmed miss and an untried row must not look the same.

---

## The gap this does not close

**The 12 best leads have no domain.** They came from News RSS, where a headline
names a company but never links to its website. B1 needs a domain to start from.

Resolving those needs a name→domain step that does not exist yet. Until then,
the fastest path for those twelve is to look them up by hand and fill the
`domain` column — after which B1 handles them like any other row.

---

## After a run

```
python tools/run_sql.py -c "select count(*) from score_segment('us-production-houses');"
python tools/export_leads.py --min-score 25
```

Enriched rows gain up to 10 points from `reachable_decision_maker` and 15 from
`collaboration_openness`, and — more importantly — they stop being defaulted
zeros, so their score starts reflecting evidence instead of ignorance.
