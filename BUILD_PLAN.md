# TVF Universal Lead Engine — Build Plan (Rapid Evolutionary Prototypes)

**The product:** an internal TVF tool that discovers leads from **multiple independent sources**, qualifies them, human-reviews them, and **automatically reaches out** — ramping from **15–20 contacted leads/week (v1)** to **100/week (v2)**. Near-zero cash cost: the Apollo subscription (provided) plus pennies of LLM reply-classification are the only spend. First segment: small US production houses for **co-production and format licensing** (never branded-content client work). Fixed pipeline — **Discover (multi-source) → Promote/Dedupe → Enrich → Verify → Score → Review → Outreach → Triage** — with everything segment-specific living in a config row, not code, so Segment 2 (startup acquisition targets) is a config row + connectors, nothing else. From P18 onward a **web interface** is the operator's single daily surface. Original architecture, data model, rubric, and compliance reasoning: see `IMPLEMENTATION_PLAN.md` at commit `9383569`.

**What changed on 2026-08-20** (owner decisions, recorded):

1. **Outreach automation.** Shortlisted leads get a templated email from a TVF Gmail account (owner supplies the account). **Single email only — no follow-up sequence.**
2. **Reply-based triage.** Replies are read by an LLM and filed into a **positive folder** or **negative folder**; the web UI allows one-click re-filing of any misclassification. **No reply within 7 days → negative folder automatically.**
3. **Human on the send trigger, permanently.** Sends go out via **one-click batch approval** in the web UI — the operator sees the week's drafted emails and approves the batch. Never fully automatic.
4. **One touch per company — hard guarantee.** A dedicated `outreach` table records every company ever contacted; a company (by entity, by domain, and by email address, **across all segments**) can never be emailed twice.
5. **Web interface.** Review queue, outreach approval, folders, and KPIs live in a simple web app (Next.js + Supabase auth), replacing the Supabase Table Editor as the daily surface.
6. **Apollo is the enrichment/verification backbone** (subscription provided). Hunter and Reoon are dropped from the critical path; the pattern-guess hedge and DIY verification pacing they required are deleted. Site-scrape extraction survives only as a *conditional fallback* for companies Apollo doesn't cover.
7. **Scale target: 100 contacted leads/week (v2).** v1 still ships at 15–20/wk; a dedicated scale phase (volume ramp + deliverability guardrails) takes it to 100.

**What changed on 2026-08-20, second pass:** discovery sources were originally sequenced as "YouTube now, everything else later, only if we need volume." That's wrong — **leads must come from multiple independent sources from the base build, not just YouTube.** Google News RSS, X-intent signals, Wikidata, and the AICP directory are now built in Phase B, immediately after YouTube, before the first rubric checkpoint — not deferred to the v2 scale phase. The config file (`config/segment.us-production-houses.json`) already listed all five sources with a `phase` hint; the ladder now honors that instead of only building phase 1.

**The method:** evolutionary prototyping in **small rungs, quick succession**. Each rung is one sitting, answers one question, and ends with something observably working.

**Owners:** **Claude** authors (SQL, code, workflow JSON, web app, docs) **and, from 2026-08-23, executes SQL directly** against the live database via `tools/run_sql.py` (owner decision). **You** retain everything needing a browser, a signup, or judgment: credential errands, review dispositions, and — permanently, per invariant 6 — the outreach send trigger. That last one is not softened by this change: batch approval stays a human action in the web UI, and `run_sql.py` refuses DROP/TRUNCATE/DELETE unless explicitly overridden, because invariants 4 and 5 depend on rows never silently disappearing.

---

## The Rules

1. **One sitting, one question, observable end.** A rung that can't finish in a sitting is two rungs. A rung whose result you can't *see* (a query result, a populated table, a green run, a rendered page) isn't done.
2. **Leads never stop.** From P3 onward the review loop exists, so every prototype run doubles as a lead-delivery run. A stage not yet automated is done by a human — never skipped, never stubbed. There is no separate "test mode."
3. **Pipelined authoring.** While you execute rung N, Claude authors rung N+1 (and N+2 where independent). You should never be free with nothing ready to run.
4. **Re-adopt, don't retype.** Validated artifacts from commit `9383569` (schema, segment config, YouTube connector) re-enter the repo only when a rung demands them — via `git checkout 9383569 -- <path>` — and are re-verified at adoption time. Nothing enters speculatively.
5. **Batch when green.** If a rung finishes in under 30 minutes and the next one needs nothing new acquired, take both in one sitting.
6. **Specify one rung deep.** Rungs are fully specified only when the rung before them is done. Everything below the current rung is a committed *shape*, not a committed *spec*.

---

## Invariants — never prototyped loosely

Crude plumbing is fine; these are cheap now and brutal to retrofit:

1. **Null ≠ zero — in the ENGINE. Zero-by-default in the DATA (amended 2026-08-23).** The scorer still treats an absent `scoring_inputs` key as "never assessed", excluded from both earned points and the denominator; that machinery is what lets a half-enriched entity be scored mid-pipeline at all, and it stays. **What changed is the data we feed it:** on owner instruction, a rubric or modifier input we cannot verify is now written as an explicit `0` rather than left blank. Reason: excluding unverified criteria from the denominator inflates scores and makes them non-comparable — a 90 computed from 4 of 6 criteria sat in the same column as a 71 computed from 5. The cost is that a `0` no longer distinguishes "checked, found nothing" from "never checked", so `sql/04b_zero_unverified.sql` records every defaulted key in `metadata.p1_unverified`: conservative score, provenance preserved. **Gates are exempt and must stay exempt** — they fire on confirmed disqualifying evidence, so defaulting an unknown gate input to a falsy value would fire `not_a_major_or_oversized` and `usable_first_party_presence` and silently reject real companies for not having been researched.
2. **Provenance.** Every row carries `source` and `source_url`. Un-reconstructable later.
3. **Schema discipline.** Workflows evolve freely; tables evolve deliberately. The JSONB design absorbs most change without DDL.
4. **Reset before gates.** `rejected` entities are permanently shielded from re-import. A reset script exists from P4; hard gates stay off until Phase C.
5. **One touch per company.** The `outreach` table is append-only history, unique per entity, and the send step additionally checks domain and email address **globally across segments** before any send. No prototype, reset, or re-import may ever produce a second email to a company already contacted. The suppression survives everything — including "remove me" replies, which mark the domain permanently unsubscribed.
6. **Human on the send trigger.** Batch approval in the web UI is a design feature, not a prototype crutch. It is never removed.
7. **Same company, different source, one row.** With five discovery sources feeding the same `entities` table, the same real company will legitimately turn up more than once (a YouTube channel *and* a News RSS deal headline *and* an AICP directory listing). Dedupe is not a nice-to-have cleanup step — it's load-bearing from the moment the second connector goes live at P6, so it stays in the ladder immediately after Promote, not pushed to the end.

Compliance lines that hold through every prototype: no LinkedIn scraping or automation, ever (Apollo's licensed data is fine; touching LinkedIn ourselves is not) · outreach is one-to-one, relevant B2B email — truthful sender identity, no deceptive subject lines, any opt-out request honored immediately and permanently (CAN-SPAM: recipients are US companies) · scrape only public first-party pages, respect robots.txt, keep data internal · no automating CAPTCHA-gated reveals · the AICP directory pull is names-only, reference-only ToS — no bulk republishing, just names into our own enrichment pipeline.

**Quota walls that shape the ladder:** YouTube API = 10k units/day (searches cost 100, channel reads 1 — searches are the scarce thing) · RSS sources (Google News, X-intent-via-RSS) have no meaningful quota — polling cost is the only limit · Wikidata SPARQL is CC0/free forever, but notable-only, so it's a one-time seed, not a recurring stream · AICP directory is a static-HTML scrape, cheap but needs its own domain-enrichment pass downstream since it yields names only · **Apollo = Basic plan, confirmed 2026-08-23: $49/seat/month billed annually, 30,000 credits per seat per year, GRANTED UPFRONT (annual pool, not a monthly allowance that expires). API access included — the feature list carries both “API Enrichment” and “CSV, CRM & API Data Enrichment”, settling the question the public pricing page left ambiguous.** Rate limits per Apollo docs for Basic: 200/min on standard endpoints; enrichment endpoints 1,000/min with **no hourly or daily cap**. Headroom against the ladder, at a conservative 2 credits per company (org match + email reveal): v1 needs ~1,700–3,500/yr (6–12% of the pool), v2 at 100 contacted/wk needs ~8,800 companies/yr ≈ 17,700 credits (~59%). **Credits are not the binding constraint at any point in this plan** — Apollo’s coverage of 2–10-person shops is (see Checkpoint 2, P17) · Gmail free ≈ 500 sends/day hard cap, but **cold-outreach deliverability caps us far lower**: ~20–25 sends/day, spread across weekdays, is the ceiling that keeps a Gmail address out of spam folders. 100/wk ÷ 5 weekdays = 20/day fits exactly — with zero headroom. *Flag for v2: a Google Workspace address on a tvf.in subdomain would be materially safer at this volume; decision deferred to P27.*

---

## Live-state note

**Superseded 2026-08-23.** The previous Supabase database (and the n8n host it talked to) is being **abandoned and rebuilt from scratch on a new Supabase account.** Nothing carries over — no schema, no segment row, no data, no credentials.

That simplifies P0 rather than complicating it. The whole "the live row is stale, reconcile it" problem disappears: a fresh project runs `01_schema.sql` → `02_smoke_test.sql` → `03_segment_us_production_houses.sql` and lands on the current v3 config directly. **`sql/03b_sync_segment_config_v3.sql` is NOT run on a fresh database** — it exists only to patch the old one, and is kept for the record. `00_verify_state.sql` is still run, now as a *confirmation* that the fresh build landed correctly rather than as a diff against a stale row.

n8n is likewise gone and gets rebuilt, but **nothing before P4 touches it** — P1, P2 and P3 are pure SQL in the Supabase editor, so the n8n rebuild belongs in the P4 sitting, not this one.

---

## The Ladder

*Your time* = the human sitting for that rung. Claude's authoring happens ahead of it (Rule 3).

### Phase A — the loop exists (zero automation)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P0** | ✅ **Foundations errand** *(DB verified live 2026-08-23; credential batch deferred — Google needed by P4)* | Files re-adopted (done, staged). **Build the database fresh on the new Supabase account:** `01_schema.sql` → `02_smoke_test.sql` (self-cleaning, leaves 0 rows) → `03_segment_us_production_houses.sql`, then `00_verify_state.sql` to confirm 6/4/3/3 + 15/20/-20 + 40/75. `03b` is not run on a fresh database. **Acquire every credential in one batch:** (a) one Google Cloud project with **YouTube Data API + Gmail API** enabled, an API key for YouTube, and an **OAuth client** (for n8n's Gmail credential later — same project, one errand); (b) **Apollo API key** from the provided subscription — record the plan's actual credit limits in this file; (c) **Anthropic API key** (reply classifier, pennies). Nothing after this rung ever stalls on a signup. **Step-by-step: `docs/P0_errand.md`.** Repo side ✅ 2026-08-23 — `python tools/verify_repo.py` is GREEN and is now the standing mechanical half of this check (it parses every SQL file, and would have caught the syntax error that made `03b` unrunnable). | Repo and DB agree (`verify_repo.py` GREEN **and** `00_verify_state.sql` showing 6/4/3/3 + 15/20/-20); three credentials + OAuth client in `.env`; Apollo limits recorded above | ~60 min |
| **P1** | ✅ **Hand-fed candidates** *(2026-08-23 — 10 rows live, CHECK 2 clean)* | Insert template. You enter ~8 companies into `entities` by hand, filling `metadata.scoring_inputs` from their real sites. Absent key = not assessed (invariant 1). | 8 rows with human-set inputs | ~45 min |
| **P2** | ✅ **Scoring works** *(2026-08-23 — all 10 match an independent implementation exactly)* | `sql/06_score.sql`: the rubric as one config-driven statement — counts only assessed criteria in numerator *and* denominator, normalizes to 100, applies modifiers, clamps [0,100], writes `fit_score` + `score_breakdown`. Zero segment knowledge. | One entity's score recomputed on paper matches exactly | ~20 min |
| **P3** | ✅ **Review loop closes** *(2026-08-23 — 7 shortlisted / 3 rejected; **approval rate #1 = 70%**)* | `sql/07_review_queue.sql` (view over `ready_for_review`, score-ordered). You work the queue in the Table Editor (the web UI replaces this at P18): approve → `shortlisted`, reject → `rejected` + reason. | Every candidate dispositioned; **approval-rate #1 recorded** | ~30 min |

### Phase B — real discovery feeds the loop (all five sources)

*Each connector is its own rung: same shape every time (fetch → cheap auto-signal-fill → write to `staging_candidates` + one `source_runs` row), so each one after the first goes faster.*

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P4** | **YouTube connector runs live** | Re-adopt `n8n/discovery/` from history (logic-validated 30/30, never run live) + `sql/90_reset_prototype.sql`. Searches the 6 config queries, fetches channel details, admits studio-like channels (keyword or ≥1,000 subs), auto-fills `genre_fit`/`geography_signal`/`major_or_oversized_signal`/`has_reachable_presence`, extracts domain + email from the description. You: credentials, import, run. | `staging_candidates` has real YouTube rows; one `source_runs` row; spot-check sane | ~45 min |
| **P5** | **Google News RSS connector** | New n8n workflow: config-driven query list (deal/format-adaptation keyword searches + `site:` trade-press queries) against Google News RSS → parse feed items → same staging shape. A matched headline naming a company sets `international_ip_experience = 1` — the strongest rubric signal, and RSS is the only source that can supply it cheaply. | `staging_candidates` has real News RSS rows tagged `source='google_news_rss'`; spot-check the `international_ip_experience` signal is set correctly on a real hit | ~30 min |
| **P6** | **X-intent connector + first cross-source dedupe proof** | Same RSS mechanism, `site:x.com` + founder-collaboration-phrase queries (not the paid X API). Noisy by design — needs a basic relevance filter node before landing in staging. This is also the first rung with **two connectors live**, so it doubles as the real-world test of invariant 7: run YouTube + X-intent back to back and confirm a company either source could plausibly find doesn't silently duplicate once promoted. | Staging rows tagged `source='x_intent_signals'`, filtered for obvious noise; a manual promote of an overlapping test pair shows one entity, not two (full automated dedupe lands at P14 — this is the manual proof it's needed) | ~30 min |
| **P7** | **Wikidata SPARQL seed** | One-time(ish) pull: SPARQL query for film/TV/streaming production companies with an official website property. CC0, free forever, notable-only — a seed, not a recurring stream, so this workflow is expected to be re-run occasionally, not scheduled weekly. | Staging rows tagged `source='wikidata'`; sane names + domains | ~25 min |
| **P8** | **AICP directory connector** | Static-HTML scrape of the AICP member directory (names-only; ToS is reference-only, ✗ no bulk republishing — internal use only). Names land in staging without a domain; domain gets filled at enrichment (P16), not here. | Staging rows tagged `source='aicp_directory'`, name populated, domain null (expected) | ~25 min |
| **P9** | **Promote (all sources, minimal)** | `sql/05_promote_minimal.sql`: normalize domain → insert as `discovered` across every `source` value in staging, domain branch only, no gates yet. Re-run = no-op. | Every connector's candidates are `entities`; re-run inserts nothing; `select source, count(*) from entities group by source` shows all 5 | ~20 min |
| **P10** | **Manual enrich via Apollo, small** | Runbook stub. You: top 5 candidates from across the combined pool → **Apollo web app**: match company by domain, find a target-role person (config `target_contact_roles`), take the verified email → enter into `contacts` (name, role, email, `email_status`, `source='apollo_manual'`, `is_primary`) → fill `scoring_inputs` from the site. This sitting also *is* the human baseline Checkpoint 2 measures against. | 5 entities enriched with Apollo-verified contacts, inputs set | ~45 min |
| **P11** | **⚑ CHECKPOINT 1 — rubric on real, multi-source data** | Score + review the full combined batch (all 5 sources) end-to-end. Approval rate on *discovered* candidates, broken out **per source** — a rubric that only works well on YouTube-shaped signals is a finding, not a pass. Read rejection reasons as a pattern; tune rubric/thresholds **in config only**; re-score. | **Approval ≥ 60% overall → proceed. Below → tune config and repeat P11.** Note any source performing far below the others — feeds P23's per-source yield tracking later | ~45 min |

### Phase C — automate the middle (Run A)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P12** | **Run A skeleton** | n8n: Manual trigger → load config → fetch pending staging (all sources) → domain-normalize → P9 insert branch → mark staging + `source_runs`. | Staging → entities with no SQL editor open | ~30 min |
| **P13** | **Gates on** | Gate-check node reading `config.gates`. Fires **only on confirmed** disqualifying evidence; all-unknown passes. Gate-failed rows land `rejected` + reason through the same upsert. | 4 known-bad candidates (drawn from real sources, not just YouTube) reject with right reasons; 1 all-unknown passes | ~30 min |
| **P14** | **Dedupe edges, fully automated** | Two-branch upsert completed: domainless branch + cross-case pre-check. Merge semantics: new keys added, existing kept unless empty, sources appended (so an entity found by both YouTube and News RSS shows both in its history), rejected matches skipped untouched. This retires the manual proof from P6. | Duplicate batch + synthetic edges → all `merged_duplicate`, 0 new entities; a real re-run across all 5 connectors produces zero new duplicate entities | ~35 min |

### Phase D — automate enrich + verify + score (Run B, on Apollo)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P15** | **Scoring in n8n** | Port `06_score.sql` into Run B. Re-scores **every** entity in `enriched`/`scored`/`ready_for_review` so reviewer corrections take effect next run. Threshold routing: `< review` parked, `≥ review` → queue, `≥ priority` flagged. | Batch scores match the SQL scorer exactly; routing correct | ~20 min |
| **P16** | **Apollo enrichment API** | HTTP nodes → Apollo: organization match by domain (fills in the domain AICP-sourced rows are missing) → people search filtered to `target_contact_roles` → email + Apollo's verification status. Map to `email_status` (confirm exact fields against current API docs at authoring). Write `email_verified_at`, `verifier='apollo'`; auto-set `reachable_decision_maker`; advance → `enriched`. `no_contact_found` convention when Apollo returns nobody. Credit-aware: skip entities already enriched. Fixtures first, live calls last. | 5 entities enrich end-to-end via API matching what the Apollo web app shows; AICP-sourced rows get a domain filled in; no repeat spend on re-run | ~40 min |
| **P17** | **⚑ CHECKPOINT 2 — Apollo vs human** | Run B over a fresh multi-source batch. Measure against the P10 human baseline: contact-find rate, role accuracy, email validity, and the **miss rate on tiny shops** (Apollo's known weak spot is 2–10-person companies — exactly our target). | Miss rate acceptable (≤ ~30%) → proceed; site-scrape fallback stays in backlog. Higher → pull backlog item **B1** into the ladder before Phase F | ~45 min |

### Phase E — the web interface

*Next.js + Supabase (magic-link auth, RLS-backed), deployable free (Vercel) or run locally. Thin by design: the database is the product; the UI is a window.*

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P18** | **Review queue in the browser** | App skeleton + auth + the review queue page: score-ordered cards with `score_breakdown`, contacts, `why_fit`, source badge, review-checklist items as literal checkboxes (rendered from config, so Segment 2 renders free). Approve/reject + reason buttons doing exactly what P3 did in the Table Editor. | You disposition a real batch entirely in the browser; Table Editor retired for review | ~30 min |
| **P19** | **Dashboard + folders (empty)** | Pipeline funnel counts, approval rate, **per-source yield** (all 5 sources), entity detail view; **positive / negative folder views** (views over the `outreach` table — empty until Phase F, rendered now so triage lands in a finished home). | Dashboard numbers match hand-run SQL | ~20 min |

### Phase F — outreach (the new spine)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P20** | **Outreach schema + one-touch guarantee** | `sql/08_outreach.sql`: `outreach` table — `entity_id` (**unique**), `contact_id`, gmail `thread_id`/`message_id`, `sent_at`, `status` (`drafted` → `approved` → `sent` → `replied_positive` \| `replied_negative` \| `no_reply_negative` \| `unsubscribed`), `classified_by` (`ai`/`human`), reply text, timestamps. Plus the **global suppression check**: a function the send path calls that refuses any entity whose domain *or* contact email appears in any prior outreach row, any segment (invariant 5). Config gains an `outreach` block: subject/body template with merge fields, `reply_window_days: 7`, `daily_send_cap: 25`. Draft generator (n8n): `shortlisted` → `drafted` rows. | Drafts render with correct merge fields in the web UI; a second draft for the same entity — and for a *different* entity on an already-contacted domain — is refused | ~30 min |
| **P21** | **Send via Gmail** | Web UI batch-approve page (invariant 6) → n8n Gmail node (OAuth from P0) sends from the TVF Gmail; store `thread_id`/`message_id`; outreach → `sent`; entity → `contacted`. Suppression check runs *at send time*, not just draft time. | A test batch to your own addresses sends; threads recorded; re-approve sends nothing twice | ~30 min |
| **P22** | **Replies in + AI triage** | n8n Gmail Trigger polls the account → match incoming to `thread_id` → store reply → Claude (Haiku) classifies: `positive` / `negative` / `auto_reply` (OOO — ignored, timer keeps running) / `bounce` (→ contact `email_status='invalid'`, timer keeps running) / `unsubscribe` (→ `unsubscribed` + permanent domain suppression). Files the folder; entity → `in_conversation` (positive) or `archived` + reason (negative). Web UI: one-click re-file, which also sets `classified_by='human'` — the correction log is the classifier's calibration data. | Seeded test replies (one of each class) all file correctly; a re-file sticks | ~40 min |
| **P23** | **The 1-week timer** | Daily scheduled workflow: `sent` rows with `sent_at < now() - reply_window_days` and no reply → `no_reply_negative`, entity → `archived` (`no_reply`). | A backdated test row flips to the negative folder on the next run | ~15 min |
| **P24** | **⚑ CHECKPOINT 3 — outreach live, small** | First real batch: 10–15 approved leads. Seed-test deliverability first (send to your own gmail/outlook test inboxes — landing in spam = stop and fix before real sends). Then live: watch replies flow, folders fill, timer close the stragglers. **This checkpoint completing = v1 exists**: the full loop, multi-source, at 15–20/wk. | Real replies triaged correctly; nothing in spam on seed test; zero double-touches; **reply-rate #1 recorded** | ~45 min over the week |

### Phase G — production posture (v1 hardening)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P25** | **Unattended** | Schedule Triggers: YouTube + News RSS + X-intent connectors (weekly), Wikidata (monthly-ish), AICP (monthly-ish), Run A (Tue), Run B (Wed), reply poll (hourly), timer (daily). n8n error workflow → email/Discord ping — **built before the first unattended run, not after the first silent failure**. | A scheduled run completes with nobody watching; a forced failure pings | ~30 min |
| **P26** | **Operate & measure — v1 ships** | `sql/kpi_queries.sql` (contacted/wk, approval rate, contact-find rate, email validity, reply rate, positive rate, **per-source yield**) wired into the P19 dashboard · `docs/runbook.md` for the weekly cadence. | **v1 = 15–20 leads contacted on schedule, sourced from all 5 connectors, replies auto-triaged, human time ≤ ~3 h/wk, runbook complete** | ~45 min |

### Phase H — scale to 100/week (v2)

*All discovery sources already exist by v1 (Phase B) — scaling is about volume and deliverability, not new connectors.*

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P27** | **Volume ramp + deliverability guardrails** | Ramp 20 → 50 → 100/wk over ~3 weeks, never jumping. Widen discovery query lists per source (more YouTube seed queries, more RSS keyword combinations) if the existing 5 sources undershoot ~170 discovered/wk needed for 100 contacted/wk at ~60% approval. Enforce `daily_send_cap`, spread sends across weekdays, monitor bounce + spam-complaint signals on the dashboard; auto-halt sends if bounce rate spikes. **Decision point recorded here:** stay on the Gmail address vs. move to a Google Workspace address on a tvf.in subdomain (materially safer at this volume; owner's call). | 100 contacted in one week with reply rate holding and zero deliverability incidents | ~30 min/wk during ramp |
| **P28** | **Review throughput** | Review at 100/wk means ~170 dispositions/wk. UI: keyboard-driven review, bulk actions on obvious rejects, priority-first ordering. Target: review ≤ 1.5 h/wk at full volume. | A full week's queue cleared inside the time budget | ~30 min |

### Post-v2 backlog — pull on trigger

**B1** Site-scrape contact extraction + human confirm gate (fixtures from P10; pulled early if Checkpoint 2 shows Apollo missing tiny shops) · **B2 Segment 2: startups** — config row (new rubric, gates, outreach template) + segment-appropriate connectors; entities, scoring, review UI, outreach, folders, and the one-touch guarantee all reuse unchanged — *the payoff of the universal design* · **B3** additional discovery sources beyond the original five, if per-source yield data from P19/P26 shows the pool still undershooting · **B4** IMDbPro ~$150/yr (if free discovery mines out) · **B5** reply-classifier tuning from the human re-file log · **B6** shortlist/folder auto-sync to BD tooling.

---

## Cadence

Pipelined authoring, sittings of 15–60 min, 2–4 rungs/week. **v1 (P26, full multi-source loop at 15–20/wk) ≈ 8–11 weeks — Phase B is longer now (8 rungs, 5 connectors) than the original YouTube-only sketch, but every later phase runs on a richer, more representative pool from day one instead of retrofitting sources in after the fact. v2 (P28, 100/wk) ≈ 3–4 weeks after.** Leads flow every week from P3 onward; outreach flows from P24 onward. The three checkpoints (P11 rubric-on-multi-source, P17 Apollo quality, P24 deliverability) are the only deliberate pauses — each is a calibration question where proceeding on a wrong answer poisons everything downstream.

---

## Progress

Mark rungs done in place (`| **P2** | ✅ ...`).

**Current status:** **P0 database + repo halves ✅ (2026-08-23). Credential batch deliberately deferred. Current rung: P1.**

*Database (done):* rebuilt from scratch on a new Supabase account — `01_schema.sql` → `02_smoke_test.sql` (all passed, 0 rows left behind) → `03_segment_us_production_houses.sql`, confirmed with `00_verify_state.sql`. `03b` was correctly **not** run. Supabase URL + service-role + anon keys are in a local `.env`.

*Credentials (deferred by decision, not forgotten):* Google Cloud, Apollo and Anthropic keys are not yet acquired. This breaks P0’s original “one batch” intent, and the cost is real but bounded and known: **Google is needed at P4, Apollo at P16, Anthropic at P22** — nothing in P1–P3 touches any of them. The errand stays live in `docs/P0_errand.md`; the risk is only that P4 now opens with a signup instead of a run. Apollo’s three plan limits are still blank in the Quota-walls bullet above.

*Repo (done, machine-verified):* `tools/verify_repo.py` exits GREEN — all 8 SQL files parse under the real Postgres parser, the config JSON is identical across its three copies (`config/*.json`, `sql/03`, `sql/03b`) when compared as parsed JSON, the v3 shape checks out (6/4/3/3, 15/20/-20, thresholds 40/75), and every `scoring_inputs` key in the P1 template is one the config actually defines. Three defects were found and fixed in the process:
1. **`sql/03` and `sql/03b` did not parse.** An unescaped apostrophe (`the pool's absolute sum`) inside the `'{...}'::jsonb` literal ended the SQL string early — `syntax error at or near "s"`. 03b is the one file P0 tells you to run, so this would have failed on paste. Escaped to `pool''s`; both files now parse clean.
2. **The config's `enrichment` block still named Hunter + Reoon**, which owner decision 6 (2026-08-20) dropped in favour of Apollo. Rewritten to the Apollo path with the site-scrape fallback recorded as disabled-by-default backlog B1 — fixed in all three copies *before* 03b is ever run, so no `03c` patch is ever needed.
3. **A stale Hunter comment in `01_schema.sql`** explaining why `contacts` allows several rows per person. The index is still right; the reason is now Apollo returning multiple addresses, so the comment says that.

*P1 authoring (done, 2026-08-23):* `sql/04_insert_template.sql` gained a config-driven audit — CHECK 2 flags unknown/mistyped `scoring_inputs` keys, explicit nulls, values outside 0/0.5/1, a hand-set `reachable_decision_maker` (engine-set only), and missing `why_fit`. Every one of those failures is otherwise **silent**: invariant 1 makes a typo indistinguishable from an honest blank, so a mistyped key would quietly drop a criterion and still produce a plausible-looking score. CHECK 3 reports per-criterion coverage across the batch, which is the early warning for P11 arriving with a criterion assessed on 1 of 8 rows. Plus `docs/P1_scoring_cheatsheet.md` — the 13 decisions per company, rendered from the config by `tools/gen_p1_cheatsheet.py` rather than hand-written, because a hand-written copy would drift on the next rubric review and have you scoring against a stale rubric while believing you were current. `verify_repo.py` re-runs the generator and fails if the checked-in file does not match.

*Standing state:* n8n does not exist yet — it is rebuilt at P4, along with Docker (not installed on this machine). The YouTube connector awaits re-adoption at P4; the other four connectors (News RSS, X-intent, Wikidata, AICP) are unwritten and get authored ahead of P5–P8 per Rule 3.

**⚑ Open item surfaced 2026-08-23 — answer before P4, not before P1:** the n8n host is *not* this machine. Docker is not installed on the Windows box the repo lives on, so `docker/docker-compose.yml` cannot come up here as-is; the previous build's n8n ran on a different host. P1–P3 are pure Supabase SQL and are unaffected. Before P4: either confirm the old host is reachable, or install Docker here and re-add the Supabase credential in a fresh n8n (~15 min P4 does not currently budget for).

**P1 seeded (2026-08-23):** `sql/04a_p1_seed_leads.sql` — all **10** companies from the owner-compiled `20th-Aug_USProductionHouseLeads.xlsx` (not 8; more rows is strictly better for the P11 rubric checkpoint, and dropping two arbitrarily would throw away research). Every `scoring_inputs` value traces to a column in that sheet.

*The consequential call:* **`international_ip_experience` is set on exactly one row** (Tonko House — ONI was an explicit Japan-US multi-studio co-production). For the other nine the sheet is silent, and it was not compiled to answer that question, so the key is **absent, not 0**. Writing 0 would assert that someone checked for a format deal and found none; nobody checked. Those nine therefore normalize over a 70-point pool rather than 100 — “fit among what we know”, exactly as designed. It is the highest-value blank on the board: filling it in for any of the nine moves them substantially, because it is the 30-point criterion.

*Contacts deliberately NOT inserted.* The sheet carries real published emails and named roles; they are parked in `metadata.p1_research`, not in the `contacts` table. P10 is where contacts land and P17 measures Apollo against P10 as the human baseline — preloading them here would quietly corrupt that comparison. Nothing is lost; the research travels with the row.

*Cross-check tooling:* `tools/expected_scores.py` is an **independent** reimplementation of the rubric, written from the stated rules rather than translated from `06_score.sql`, so P2’s “recompute on paper” step is a diff instead of notepad arithmetic — and an agreement between the two actually means something. `verify_repo.py` now also validates every `scoring_inputs` block across `sql/` offline (unknown keys, non-0/0.5/1 values, hand-set `reachable_decision_maker`), which is CHECK 2 run against the files before they ever reach the database.

**Expected P2 result** (verify against this): Lowbrow 90.0 · Tonko 71.0 · Neon Zoo / Meerkat / Chiodo 68.57 · Exit 73 65.0 · Minnow 59.29 · Block & Tackle 37.86 · Tandem 33.57 · Calabash 19.29. **3 of 10 park below the review threshold of 40** and will not reach the P3 queue — the two pure service shops (Calabash brand-ads, Block & Tackle title design) and Tandem. That is the rubric doing its job for a co-production/format play, but it is the first thing to sanity-check at P3: if you disagree, the fix is a config weight, never a hand-edited score.

**PHASE A COMPLETE — P0 ✅ P1 ✅ P2 ✅ P3 ✅ (2026-08-23, all run live via `tools/run_sql.py`).** The loop exists: candidates in, scored, reviewed, dispositioned. **Approval rate #1 = 70% (7 shortlisted / 3 rejected).**

*P0 database half confirmed live:* 5 tables, 6/4/3/3, 15/20/-20, thresholds 40/75, 0 pre-existing entities. Postgres 17.6.

*P1:* 10 rows from `sql/04a_p1_seed_leads.sql` (evidence as the source sheet supported it), then **`sql/04b_zero_unverified.sql`** applying the owner rule that an unverified input scores 0 — see the amended invariant 1. CHECK 2 clean. Config-driven and idempotent, so it works unchanged for Segment 2.

*P2 — done-when met twice over:* `06_score.sql` and `tools/expected_scores.py`, two implementations derived independently from the spec, agreed on all ten rows **before** the policy change and again **after** it. Two matching runs against different data is a much stronger result than the single reconciliation the rung asked for.

**Scores after the zero-unverified rule** (all now out of the full 110-point pool, so finally comparable to each other): Tonko House 63.27 · Lowbrow 53.64 · Neon Zoo / Meerkat / Chiodo 40.00 · Exit 73 37.73 · Minnow 26.82 · Tandem 14.09 · Block & Tackle 13.18 · Calabash 5.00. **5 of 10 now sit at or above the review threshold, down from 7, and the top of the list changed hands:** Lowbrow fell from 90.00 to 53.64 and Tonko House took first. That reordering is the rule working as intended — Tonko is the only candidate with verified international co-production experience, which is the single thing this segment exists to find.

**⚠ Threshold recalibration is now due at P11.** 40/75 were set against scores computed on partial denominators. Under the new rule nothing reaches 75 at all, so `score_threshold_priority` is currently unreachable and the priority band is dead. Do not hand-edit scores to compensate — fix the thresholds in config, which is exactly what the P11 checkpoint is for.

**⚠ SECURITY DEFECT FOUND AND FIXED (2026-08-23) — `review_queue` was leaking to the public anon key.** A Postgres view runs with its **owner’s** privileges by default, so a view owned by `postgres` over RLS-protected tables serves every row to anyone who can select from it — and Supabase grants `anon` SELECT on public objects. Verified live rather than assumed: as `anon`, `entities` returned **0** rows (RLS doing its job) while `review_queue` returned **all 10**. The anon key ships in browser code by design, so this was a live leak path for the entire lead list, contacts included. Fixed with `security_invoker = true` in both `sql/07_review_queue.sql` and the live view; re-probed after: `anon` now gets 0, `postgres` still gets 10. **Standing rule for P18 onward: every view over these tables must set `security_invoker = true`,** or RLS is decorative.

*Review surfaces:* `tools/review_sheet.py` (terminal) and `tools/review_artifact.py`, which generates a browser page from the live database — a deliberate P18 precursor. Its one load-bearing design decision: a defaulted zero renders as a hatched, dashed bar labelled `unverified`, visually distinct from a zero someone actually checked. A reviewer reading a low score can see instantly whether it reflects evidence or absence of research.

**Next actions:** (1) **You — P3, the only judgement step:** disposition all 10 (shortlist / reject + a one-line reason, always). Tell me the calls and I will write them. Then **approval rate #1** gets recorded here. (2) **Highest-value thing you can add:** `international_ip_experience` is a defaulted zero on 9 of 10 and is worth up to 27 points. If you know any of them has co-produced or adapted foreign IP, say so and I will re-score. (3) **You — before P4:** the Google Cloud half of `docs/P0_errand.md`, plus the Docker/n8n question. (4) **Claude, next authoring pass:** re-adopt and re-verify the YouTube connector for P4, then author the P5 Google News RSS connector.
