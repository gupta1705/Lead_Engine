# P1 — scoring cheat sheet

**Generated from `config/segment.us-production-houses.json` by `tools/gen_p1_cheatsheet.py`. Do not edit by hand — regenerate.**

Keep this open in one tab and the company's site in another.

---

## The rule that matters more than any weight below

**If you could not find evidence either way, DELETE the key.** Do not write `0`, and do not write `null`.

- a **deleted key** means *never assessed* — it is excluded from both the numerator and the denominator, so the score reads "fit among what we know"
- **`0`** means *checked, and confirmed no evidence* — it counts fully against the score

Those two are wildly different judgements that look identical in a hurry. Getting this wrong is the single easiest way to make P11's rubric checkpoint meaningless.

Rubric and modifier values are always **`0`, `0.5`, or `1`**. Gate values are strings or booleans — see the gate section.

---

## Rubric — the 6 scored criteria (pool: 110 points)

The pool does not sum to 100 and does not need to: the scorer normalizes over whichever criteria you actually assessed, so these are *relative* weights, not percentages.

### `international_ip_experience` — 30 points

**Has adapted or co-produced international IP/formats**

Trade-press coverage of a format deal, an adapted foreign show in credits, or co-pro credit with a non-US company. STRONGEST signal.

### `distribution_relationship` — 20 points

**Live output relationship with a streamer/network/major platform**

A co-pro must land somewhere. First-look deals, recent commissions, or consistent platform sales count.

### `right_size` — 20 points

**Right size: ~2-20 core people, most under 10, real credits, independent**

Lean team, not a small studio in name only. Big enough to execute, small enough to want a partner. Headcount hints plus credit history. RAISED 2026-08-20 from 15 (owner rubric review): operational fit is a harder constraint than the original weight implied.

### `genre_fit` — 15 points

**Makes content in TVF lanes (comedy, slice-of-life, young-adult, workplace)**

Check credits/website/YouTube. Full points if core focus; half if occasional. LOWERED 2026-08-20 from 25 (owner rubric review): genre mismatch matters but should weigh less than proven IP-adaptation history or live distribution.

### `collaboration_openness` — 15 points

**Demonstrated openness to collaboration: explicit invitation, collective/partner-led model, or co-production track record**

Full credit for an explicit collaboration/partnership invitation on their own site, a collective or partner-led operating structure, or a track record of co-productions. Half credit for a weaker or implicit signal. Distinct from international_ip_experience, though the two can overlap. ADDED 2026-07: default weight 15. CONFIRMED 2026-08-20 (owner rubric review): kept at 15 despite the overlap with international_ip_experience -- an explicit partnership invitation or collective structure is meaningfully different from having actually adapted a format before. Rubric pool now sums to 110 (was 115) after this review; the engine renormalizes over assessed points regardless of the pool's absolute sum, so this is a relative-weight statement, not a percentage.

### `reachable_decision_maker` — 10 points

**Named decision-maker identified and reachable**

Auto-set by the engine: 1.0 if a target-role contact has a valid email, 0.5 if catch-all, else 0.

---

## Modifiers — applied *after* normalizing, as a delta

A modifier never creates a score on its own; it only adjusts one the rubric already produced.

### `client_work_dominance` — penalty, up to -20

**PENALTY: output dominated by client/branded-content work, not owned IP**

A /work page full of brand-client logos is a NEGATIVE, not a portfolio positive. 1.0 = entirely client work (full -20), 0 = no evidence of client-work dominance (no penalty). Soft subtractor, not a hard gate.

### `india_diaspora_affinity` — bonus, up to +6

**BONUS: existing India/Asia ties, diaspora-crossover audience, or prior work with an Indian company**

Rare signal. Most good leads will legitimately score 0 here, which is not a strike against them. Kept small and additive so it never overrides the 5 primary fit signals.

### `revenue_above_cap` — penalty, up to -20

**PENALTY: revenue estimate above the ~$1M microbudget-scale ceiling (borderline vs clean fit)**

Private production companies rarely publish revenue, so this cannot be verified directly. Estimate via third-party tools (e.g. LeadIQ, Buzzfile, RocketReach) where available, else reviewer judgment. 1.0 = a confirmed third-party estimate above ~$1M (borderline), 0 = at/under ~$1M or microbudget-scale (clean fit) or no negative evidence. Soft subtractor by design, matching a flag-rather-than-auto-drop preference - a reviewer can still drop borderline rows manually if being strict. RAISED 2026-08-20 from -10 to -20 (owner rubric review): now weighted as seriously as client_work_dominance. NOT YET CONNECTOR-AUTOMATED: LeadIQ/Buzzfile/RocketReach free-tier usability for this pipeline has not been adversarially verified the way every other tool in this project has been (see impl. plan §10) - until that verification happens, this input is set by the reviewer/manual lookup at S7.5, not by any connector.

---

## Gates — not scored, and not enforced until P9/P13

Record them at P1 anyway: they are the evidence the gates will read later. Every gate fires **only on confirmed disqualifying evidence** — blank or unknown always passes through. That asymmetry is deliberate: a gate that fired on absence of evidence would silently delete real leads.

### `us_geography`

**Primary operation/HQ must be in the United States**

Excluded when the value is `"non_us"`.

Fires ONLY on confirmed non-US evidence (e.g. YouTube channel country field explicitly non-US). Blank/unknown always passes through.

### `not_a_major_or_oversized`

**Exclude majors, their named subsidiaries, and anything clearly oversized**

Excluded when the value is `true`.

Name/keyword match against known majors, or a confirmed size signal well beyond the ~50-person ceiling. Blank/unknown always passes through.

### `usable_first_party_presence`

**Must have SOME reachable presence: website, owned channel, or social**

Excluded when the value is `false`.

A YouTube channel itself already satisfies this for connector-sourced candidates, so this gate effectively always passes them.

### `is_active`

**Company/channel must be currently active, not dormant or defunct**

Excluded when the value is `"confirmed_dormant"`.

Fires ONLY on confirmed dormancy (e.g. no upload or site activity in 12+ months, an explicit closed/discontinued notice). Blank/unknown always passes through. The connector makes a cheap best-effort read from upload recency at discovery time; Layer B enrichment gets a fuller look once it actually visits the site, and can override that initial guess.

---

## Do not fill these in by hand

- **`reachable_decision_maker`** — engine-set from a verified contact at P10/P16. Setting it yourself inflates the score with a signal no contact record backs up. `sql/04_insert_template.sql` CHECK 2 flags it.

---

## Not scored at all — the 3 human judgement calls (P3)

Free sources cannot verify these, so they are never auto-enforced. They come back as literal checkboxes at review.

### `is_a_content_production_company`

**Is this actually an IP-owning production company, not a service vendor, agency, institution, or an unrelated same-name LLC?**

Free sources cannot reliably tell these apart at intake - this is a human judgment call at review (§7.5), not an auto-enforced gate.

### `in_scope_subtype`

**Is the subtype actually in scope (commercial/branded, digital/social, film/TV/streaming) and NOT corporate/service video?**

Confirm against real site/channel content, not just a keyword match that got it into staging.

### `independent_ownership`

**Founder/partner-owned - no studio/network parent, no PE ownership, no large-scale VC backing on record**

Check Crunchbase/PitchBook/press where feasible. Free automated sources (YouTube API etc.) cannot verify ownership/cap-table structure - this is a manual check, not a connector-computed signal. Precedent for a judgment-call exception: a single small convertible note (e.g. roughly $500K) from non-marquee sources does not by itself disqualify a candidate.
