# TVF Universal Lead Engine — Build Plan (Stages & Substages)

**Companion to:** `IMPLEMENTATION_PLAN.md` (the *what & why*). This document is the *how*: the build broken into stages and small substages. Each substage has **one deliverable and one exit check**, sized to be completed (and verified) in a single short sitting.

**Owners:**
- **Claude** — authored/built by Claude in this project folder (files, SQL, workflow JSON, research).
- **You** — requires things only you can do: creating accounts, pasting credentials, clicking through web UIs, judgment calls.
- **Both** — Claude authors the artifact (SQL, node code, workflow design); you execute it in the live UI/database and confirm the exit check. (Claude never holds DB credentials and cannot click the n8n editor — so any row whose *verification* happens in a live system is Both.)

**Stage → Implementation-plan phase mapping:** S0–S2 = Phase 0 (infra). Two Phase-0 checklist items deliberately land later, where the data they need exists: the segment-config insert in S3.1–S3.2 and the review view in S7.1. · **S3 = Phase 1 (discovery), now connector-first: segment config (§6.1/§8) *and* the first Layer-A connector — YouTube Data API — built and proven here.** No manual seed. · S4–S6 = Phase 1–2 core (dedupe/promote, Layer-B enrichment, verify+score) · S7 = Phase 1–2 (review layer + runbook) · S8 = Phase 1 exit (first delivered batch, sourced by the YouTube connector) · S9 = the remaining Layer-A connectors (Google News/X-intent, Wikidata, AICP) + Phases 3–4 backlog.

---

## Repo Layout (target)

```
Lead Generator/
├── LeadGenerator.txt                     original doc (reference only)
├── IMPLEMENTATION_PLAN.md                the what & why
├── BUILD_PLAN.md                         this file — build tracking
├── docker/
│   └── docker-compose.yml                n8n (localhost-bound)
├── sql/
│   ├── 01_schema.sql                     full DDL (§5.1 of impl. plan)
│   ├── 02_smoke_test.sql                 insert/verify/cleanup + RLS check
│   ├── 03_segment_us_production_houses.sql   segment row insert
│   ├── 05_kpi_queries.sql                weekly retro queries
│   ├── 06_review_queue_view.sql          the review surface (SQL view)
│   └── 07_shortlist_export.sql           weekly handoff CSV query (S7.4)
├── config/
│   └── segment.us-production-houses.json comment-free segment config
├── n8n/
│   ├── run_a_promote_dedupe.json         exported workflow
│   ├── run_b_verify_score.json           exported workflow (Reoon verify + score)
│   ├── enrichment.json                   Layer-B site-scrape + pattern + confirm (S5)
│   ├── error_notify.json                 exported error workflow
│   ├── discovery/                        Layer-A connectors — built ONE AT A TIME
│   │   ├── conn_youtube_api.json         [S3, built 1st] ✅ pre-built, 10-node workflow, ready to import
│   │   ├── SETUP.md                      ✅ one-time import guide for conn_youtube_api (credentials, run, verify)
│   │   ├── code/                         ✅ the 4 Code-node scripts, source of truth (embedded copies live in the .json)
│   │   │   ├── 01_split_queries.js
│   │   │   ├── 02_flatten_search_results.js
│   │   │   ├── 03_filter_score_shape.js  admission filter + scoring/gate signals + domain/email extraction
│   │   │   └── 04_summarize_source_run.js
│   │   ├── conn_google_news_rss.json     [S9.1, 2nd] deal-signal monitoring
│   │   ├── conn_x_intent_signals.json    [S9.2, 2nd] X/Twitter founder-collab posts (via Google RSS)
│   │   ├── conn_wikidata.json            [S9.3, 3rd] film/TV seed
│   │   └── conn_aicp_scrape.json         [S9.4, 4th] commercial-shop directory
│   └── scoring_code_node.js              generic scoring logic (source of truth)
└── docs/
    └── runbook.md                        operator guide: the FULL weekly loop (Mon–Fri)
```

---

## Stage S0 — Workspace & Accounts

**Goal:** everything external exists; nothing is built yet.
**Exit criteria (infra):** project folder scaffolded; n8n editor opens at `http://localhost:5678`; Supabase live. The free-engine API keys (S0.4 YouTube, S0.5 Reoon/Hunter) are **deferred** — obtained when their stage arrives (Reoon/Hunter at S5 enrichment; YouTube at the S3 connector build — no longer post-v1), not required to close S0's infra.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S0.0 | Decide the n8n host (impl. plan Open Question 2: office machine / Oracle Always-Free VM / EC2) and install Docker on it | You | `docker --version` succeeds on the chosen host | — |
| S0.1 | ✅ Scaffold the repo folder structure (`docker/`, `sql/`, `config/`, `n8n/`, `data/`, `docs/`) | Claude | Folders exist — **done** | — |
| S0.2 | Write `docker/docker-compose.yml` for n8n: image, port `127.0.0.1:5678:5678` (localhost-only), persistent volume, timezone | Claude | File exists; `docker compose config` parses on the host | S0.0, S0.1 |
| S0.3 | Create the Supabase project (free tier). Capture: **session-pooler connection string** (`aws-*.pooler.supabase.com:5432`), database password, project URL, and the **anon key** (needed only for the S1.5 negative test). Store outside the repo (password manager). | You | Can open the project's SQL editor; all four values captured | — |
| S0.4 | *(Do before S3.3 — the YouTube connector is now built pre-v1, not post-v1.)* Get a **YouTube Data API v3** key: Google Cloud console → new project → enable "YouTube Data API v3" → create API key (free, no card). Store outside repo. | You | Key stored; a test `search.list` call returns JSON | — |
| S0.5 | *(Do before S5.)* Sign up for **Reoon** (email verification) and **Hunter** (pattern oracle) free tiers; capture both **API keys** | You | Both keys stored outside repo | — |
| S0.6 | Start n8n: `docker compose up -d`; open editor; create owner account; register the instance (unlocks Folders + Debug in editor) | You | Editor loads; instance registered | S0.0, S0.2 |
| S0.7 | Create n8n folder structure: `Engine/`, `Connectors/`, `Ops/` | You | Folders visible in n8n | S0.6 |

> **Note on S0.3–S0.5:** account creation and credential handling are yours by design — Claude never sees or stores passwords/API keys; workflows reference them only as n8n credentials you paste in.

---

## Stage S1 — Database Live

**Goal:** the full schema running in Supabase, verified safe and correct.
**Exit criteria:** all 5 tables + indexes + triggers + RLS exist; smoke test passes (including both dedupe indexes); anon REST access is blocked.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S1.1 | Author `sql/01_schema.sql` — the complete DDL from impl. plan §5.1 (tables, partial indexes, CHECK constraints, triggers, RLS) | Claude | File complete, matches §5.1 | S0.1 |
| S1.2 | Run `01_schema.sql` in the Supabase SQL editor | You | "Success. No rows returned"; 5 tables visible in Table Editor | S0.3, S1.1 |
| S1.3 | Author `sql/02_smoke_test.sql` — inserts a throwaway segment + entity + contact, then verifies: `updated_at` trigger fires; `status_changed_at` trigger fires; bad `status` value rejected; duplicate `(segment_id, domain)` rejected; **duplicate `(segment_id, lower(name))` with both rows domainless rejected** (the second partial index); then cleans up | Claude | File complete; every assertion labeled with its expected outcome | S1.1 |
| S1.4 | Run the smoke test; confirm every check passes | You | All checks return expected results; cleanup leaves 0 rows | S1.2, S1.3 |
| S1.5 | RLS check: call the project's REST endpoint (`/rest/v1/entities`) with the **anon** key from S0.3 | You | Response is an empty array / permission denied — never data | S1.2 |

---

## Stage S2 — n8n ↔ Supabase Plumbing

**Goal:** n8n can read and write the database.
**Exit criteria:** a test workflow round-trips a query through the session pooler.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S2.1 | Create the Postgres credential in n8n using the **session-pooler** connection string (host `aws-*.pooler.supabase.com`, port 5432) — *not* the direct `db.<ref>.supabase.co` host (IPv6-only on free tier) | You | Credential "connection tested successfully" | S0.6, S0.3 |
| S2.2 | Build a throwaway test workflow: Manual Trigger → Postgres node `SELECT 1` → `SELECT * FROM segments`; confirm it runs, then delete it | Both | Executes green (segments empty until S3.2 — a zero-row result without error is a pass); workspace clean afterwards | S2.1 |

---

## Stage S3 — Segment Config + First Discovery Connector (YouTube)

**Goal:** Segment 1 registered with its full config (6-criterion rubric, 3 score modifiers, 4 auto-hard-gates, a 3-item human review checklist, and the config-driven `youtube_discovery_queries` list — impl. plan §6.1/§8); the first Layer-A discovery connector — **YouTube Data API** — built, tuned, and proven to write real, correctly-scored-input candidates into staging. **No manual seed.**
**Exit criteria:** `segments` has 1 row; the YouTube connector runs cleanly end-to-end and writes a real batch of candidates to `staging_candidates`, each carrying `genre_fit` + the 4 gate-input signals in `raw.scoring_inputs`; `source_runs` has a row for the run.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S3.1 | ✅ Author `config/segment.us-production-houses.json` (comment-free JSON per impl. plan §6.1/§8 — incl. the `score_modifiers` block, the `gates` block, the `youtube_discovery_queries` array, and the phase-ordered `sources` list) + `sql/03_segment_us_production_houses.sql` (the INSERT) | Claude | JSON validates (`jq .` / JSON.parse); SQL file ready — **done, v2**: added `collaboration_openness` rubric criterion (rubric now sums to 115), `revenue_above_cap` modifier (reviewer-set, not yet connector-automated), `is_active` gate (4th gate), and a `review_checklist` block for 3 signals no free connector can verify. Both files re-verified byte-for-byte identical, zero SQL-breaking characters | S1.1 |
| S3.2 | ✅ Run the segment insert. **Done 2026-07-22** — initially inserted from a pre-v2 config version (verification showed rubric_criteria=5/gates=3/review_items=NULL instead of 6/4/3), fixed via one-time `sql/04_update_segment_us_production_houses.sql` (byte-verified against the current config file), then **re-verified correct: 6/4/3**. Not a repeatable step — a fresh install's 03 already has the current config. | You | `select slug, jsonb_array_length(config->'rubric') rubric_criteria, jsonb_array_length(config->'gates') gates, jsonb_array_length(config->'review_checklist') review_items from segments` → `us-production-houses`, 6, 4, 3 — **confirmed** | S1.2, S3.1 |
| S3.3–S3.7 | ✅ **Pre-built as one importable workflow** (superseding the original click-by-click plan). Authored all 4 Code-node scripts in `n8n/discovery/code/*.js`, **logic-validated against a mocked n8n runtime + realistic fake YouTube API data** (30 automated checks, all passing — covers admission filter keep/discard, cross-query dedupe, domain/email extraction, gate-signal computation, and the zero-candidates edge case), then assembled `n8n/discovery/conn_youtube_api.json` — a 10-node workflow (trigger → load config → split queries → search.list → flatten+dedupe → channels.list → filter/score/shape → parallel branch into staging_candidates + source_runs inserts). Byte-verified: every embedded script matches its source file exactly; every connection references a real node. **Known v1 simplification, done deliberately, not by accident:** `activity_signal` (the `is_active` gate's input) is left unset by this connector — safe by the gate's own unknown-passes-through design, just not yet actively catching anything; a fuller check can be added later. See `n8n/discovery/SETUP.md` for the one-time import steps. | Claude | All 4 scripts pass their test harness; workflow JSON re-parses and byte-matches its source scripts; **done** — pending only your import + live run (S3.8) | S1.1 |
| S3.8 | **Full test (live, yours):** follow `n8n/discovery/SETUP.md` to create the 2 credentials, import the workflow, re-link credentials, and run it against the real `youtube_discovery_queries`. Review what actually got included/excluded and retune the admission-filter thresholds in `03_filter_score_shape.js` (then re-import) if needed. | You | A real batch lands in `staging_candidates` with sensible `raw.scoring_inputs`; one `source_runs` row appears; spot-check confirms the filter's judgment calls are reasonable | S3.3–S3.7, S3.2, S0.4 |
| S3.9 | Add a weekly **Schedule Trigger** to the proven workflow (timed early Monday / Sunday night, ahead of the Monday cadence check-in, impl. plan §11), alongside the existing Manual Trigger. Re-export if you want the schedule captured in the repo copy. | You | The connector now runs on its own weekly schedule as well as manually | S3.8 |

---

## Stage S4 — Run A: Hard Gates + Promote & Dedupe Workflow

**Goal:** the n8n workflow that evaluates the 4 auto-hard-gates and turns staging rows into deduplicated `entities`.
**Exit criteria:** real batch promoted; the dedupe merge path proven with a re-inserted duplicate batch **and** the two hard edge cases (domainless duplicate, cross-case) **and** each of the 3 hard gates proven to correctly reject on confirmed-bad evidence while passing unknowns through.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S4.1 | Author the promote/dedupe SQL as standalone, testable statements: domain normalization, domain-branch `ON CONFLICT ... WHERE domain IS NOT NULL`, no-domain pre-check + name-branch upsert, `skipped_rejected` handling (impl. plan §7.2). **The upsert statements now take `status`/`status_reason` as parameters** (fed by S4.4's gate check) instead of hardcoding `status='discovered'`. Claude authors; you hand-test in the SQL editor against 2–3 throwaway staging rows (insert them for the test — needs the S3.2 segment row for the FK) | Both | Each statement behaves correctly on the throwaway rows, including a forced `status='rejected'` case; test rows cleaned up | S1.2, S3.2 |
| S4.2 | Build Run A skeleton in n8n `Engine/`: Schedule Trigger (weekly, Tue) **+** Manual Trigger → Postgres "load active segment config" (now including `config.gates`) → Postgres "fetch pending staging rows" | Both | Executes without error; config node returns the segment row incl. `gates` (staging may be empty until the S3 connector has run — zero staging rows is not a failure) | S2.1, S3.2 |
| S4.3 | Add domain-normalization Code node (lowercase, strip protocol/`www.`/path). Claude authors the JS; you paste and run samples | Both | Sample inputs → expected outputs inside the node | S4.2 |
| S4.4 | **Add the hard-gate check Code node** — for each candidate, read its `raw.scoring_inputs` gate signals (`geography_signal`, `major_or_oversized_signal`, `has_reachable_presence` — all set by the connector, `03_filter_score_shape.js`; `activity_signal` is defined by the gate but **not yet set by the v1 YouTube connector** — a deliberate simplification, always absent/unknown from this source today, safe because the gate passes unknowns through) and evaluate against `config.gates`' `exclude_when` rules. Any confirmed match → output `status='rejected'`, `status_reason='<gate key>'`. No confirmed match (incl. all-unknown) → output `status='discovered'`. **Never** fails a candidate for a missing/null signal — only a positively confirmed one. | Both | Sample candidates with known-bad, known-good, and unknown signals all produce the correct status/reason | S4.3 |
| S4.5 | Add the two-branch upsert (IF node on `domain` present → two Execute Query paths from S4.1), **now passing S4.4's status/status_reason into the insert instead of hardcoding `discovered`** | Both | Both branches execute on test items; a gate-failed test item lands as `rejected` with the right reason | S4.1, S4.4 |
| S4.6 | Add: mark staging rows `imported = true` + `import_result`; insert `source_runs` rows **grouped by staging `source`** (candidates_found / candidates_new per source — the S7.3 source-yield KPI needs per-source granularity) | Both | After a run: staging flags set; one `source_runs` row per source in the batch, counts correct | S4.5 |
| S4.7 | **Full test, four parts.** (a) Run 1 on the real YouTube-connector batch from S3.8 → entities land `discovered` or `rejected` per S4.4's gate evaluation, `import_result='inserted'` (however many the connector actually found — no fixed count expected). (b) Run 2 with staging untouched → fetches 0 rows, does nothing (staging is already `imported = true` — this proves the pull filter, not dedupe). (c) **Dedupe proof:** re-insert a copy of ~10 of those rows into staging **plus** synthetic edge-case rows — two domainless rows with the same name, and one domainless row whose `lower(name)` matches an existing entity that *has* a domain → run again → all resolve to `merged_duplicate`, 0 new entities, and the cross-case row merged into the domained entity (not inserted). (d) **Gate proof:** synthetic candidates — one with `geography_signal='non_us'` (must reject), one with `major_or_oversized_signal=true` (must reject), one with `has_reachable_presence=false` (must reject), one with `activity_signal='confirmed_dormant'` (must reject), one with all four signals absent/null (must pass through as `discovered`, proving unknowns are never punished) | Both | All four parts pass | S4.6, S3.8 |
| S4.8 | Export the workflow (n8n UI → download) → save as `n8n/run_a_promote_dedupe.json` | Both | File in repo, re-importable | S4.7 |

---

## Stage S5 — Enrichment (Layer B: site-scrape → pattern → confirm)

**Goal:** the shared, segment-agnostic enrichment path — scrape a company's own site for its decision-maker, construct/verify the email, land it in `contacts`. (This layer is reused unchanged by any future segment, incl. startups.)
**Exit criteria:** 10 real companies enriched end-to-end; contacts in the database with `is_primary` set.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S5.1 | Author `docs/runbook.md` § "Enrichment pass": step-by-step — fetch entity's `/team` `/about` `/leadership` `/contact` → extract name/role/`mailto:` → target-role match (config order) → if no email, learn domain pattern (Hunter free, one lookup/domain, cached); **if Hunter has a pattern, construct 1 address; if Hunter has nothing (its own documented weak spot for small/low-footprint domains), construct the top-3 variant hedge (`{first}.{last}@`, `{first}@`, `{f}{last}@`) and land all 3 as separate rows** → exact fields to record, incl. leaving `is_primary` unset on hedge rows (resolved post-verify, impl. plan §7.3 step 3) → the **no-contact-found convention** (`entities.metadata.enrichment_result = 'no_contact_found'`) → the manual reveal exceptions (YouTube About email = manual only, never scripted) → Table Editor fallback entry path | Claude | Section covers: the site-scrape cascade, role-order matching from config, pattern construction incl. the 3-variant hedge, the manual-only exceptions, every field S5.4 must record, the no-contact-found convention, and the Table Editor fallback. (S5.4 doubles as the usability test.) | S3.1 |
| S5.2 | Build the enrichment n8n workflow in `Engine/`: for each `discovered` entity with a domain → HTTP Request fetch of `/team`,`/about`,`/contact` → HTML node + Code/regex extract of names/roles/`mailto:` → Hunter node for pattern → Code node branches: pattern found → construct 1 candidate; no pattern → construct the 3-variant hedge (`{first}.{last}@`, `{first}@`, `{f}{last}@`) → write candidate `contacts` rows (`is_primary` set now only for the which-*person* call; left `false` on hedge rows for Run B to resolve). Plus a small **Form/Table-Editor confirm** step so a human OKs the entry before it counts. | Claude | Workflow authored: scrape → extract → pattern-or-hedge branch → write contacts → human-confirm gate | S2.1, S0.5 |
| S5.3 | Test + export: run the enrichment workflow against ~3 promoted entities (or one manually inserted test entity), confirm it writes correct `contacts` rows and the confirm gate works; export → `n8n/enrichment.json` | Both | Correct `contacts` rows with right `entity_id` + `is_primary`; export in repo | S5.2, S4.7 |
| S5.4 | **Pilot:** enrich the first 10 highest-promise seed companies for real (auto site-scrape + your confirmation per runbook) | You | ≥7 of 10 have a target-role contact with an email; `is_primary` set on each; runbook gaps noted and fixed in S5.1 | S5.1, S5.3 |

---

## Stage S6 — Run B: Verify + Score

**Goal:** verification and config-driven scoring, ending with routed statuses.
**Exit criteria:** every pilot company that got a contact in S5.4 (≥7 of 10) is scored and routed — pilots with no contact found stay `discovered` by design; one score hand-checked to the point; edge cases pass.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S6.1 | Build Run B skeleton in n8n `Engine/`: **Manual Trigger** (operator-fired after the contact-entry pass, per impl. plan §11 Tuesday step 3) → Postgres "load active segment config" → Postgres "fetch contacts where `email_status = 'unverified'`" | Both | Executes without error; returns the pilot contacts | S2.1, S5.4 |
| S6.2 | **Reoon** verifier integration: HTTP Request node → `emailverifier.reoon.com/api/v1/verify`, **called in Power Mode** (its documented mode with a real `catch_all`/`is_catch_all` distinction — confirm the exact request parameter against Reoon's current API reference; Quick Mode's status set has no catch-all category and must not be used here); map result codes → `email_status` enum (`valid`/`invalid`/`catch_all`/`unknown`); write `email_verified_at`, `verifier='reoon'`. Then, for any group of `contacts` rows sharing an `entity_id`+`full_name` (the impl. plan §7.3 step 1(b) 3-variant hedge), promote exactly one to `is_primary = true`: best status wins (`valid` > `catch_all` > else), `{first}.{last}@` breaks ties. **Pace for the ~20/day free cap**: if the unverified batch exceeds ~20, queue the remainder for the next day (don't burst) — the hedge can spend up to 3 verifications per contact instead of 1 (impl. plan §10.2 math). | Both | 2–3 known-good/known-bad emails verify correctly; a synthetic 3-row hedge group resolves to exactly 1 `is_primary`; over-cap batch defers gracefully | S6.1, S0.5 |
| S6.3 | Add: set `metadata.scoring_inputs.reachable_decision_maker` on the entity from its primary contact (1.0 valid / 0.5 catch_all / 0 else); advance status → `enriched` | Both | Pilot entities show correct input + status | S6.2 |
| S6.4 | Author `n8n/scoring_code_node.js`: generic scorer — reads `config.rubric`, resolves `input` paths, clamps values to [0,1], normalizes to 100, emits `fit_score` + `score_breakdown`. **Zero segment knowledge.** | Claude | Passes desk-check against 3 hand-computed examples | S3.1 |
| S6.5 | Wire the scorer into Run B; write `fit_score` + `score_breakdown`; **scope: re-scores every entity in `enriched`/`scored`/`ready_for_review`** (impl. plan §7.4) | Both | Every `enriched` pilot entity has a score + breakdown | S6.3, S6.4 |
| S6.6 | Threshold routing: `< score_threshold_review` → stays `scored` (parked); `≥` → `ready_for_review`; `≥ score_threshold_priority` → priority flag in metadata | Both | Statuses distribute correctly across the pilot batch | S6.5 |
| S6.7 | **Edge-case test** with synthetic entities: missing scoring inputs (→ 0 for that criterion), partial credit 0.5, no primary contact, rubric points not summing to 100 (→ normalized); clean up after | Both | All four cases produce expected scores | S6.5 |
| S6.8 | Hand-check one real pilot entity: recompute its score from the rubric on paper; compare to `score_breakdown` | You | Numbers match exactly | S6.5 |
| S6.9 | *(Optional, per impl. plan §12 Phase 2)* Run B tail node: notify the Reviewer that the weekly batch is ready (email or Discord webhook) | Both | Ping arrives when Run B finishes | S6.6 |
| S6.10 | Export the workflow → `n8n/run_b_verify_score.json` | Both | File in repo, re-importable. **Rule:** any later node addition (incl. S6.9 if built afterwards) requires a re-export so the file always matches the live workflow | S6.6, S6.7, S6.8, S6.9 (if built) |

---

## Stage S7 — Review Layer, Runbook & Ops

**Goal:** the human quality gate, the weekly output channel, and the complete operator guide.
**Exit criteria:** reviewer can work a batch start-to-finish without touching SQL; shortlist exports cleanly; `docs/runbook.md` covers the **full Mon–Fri loop**; failed runs can't die silently.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S7.1 | Review surface: author `sql/06_review_queue_view.sql` — `create view review_queue as select ... where status = 'ready_for_review' order by fit_score desc` (name, domain, subtype, `why_fit`, score, breakdown, primary contact). A SQL view is used because the Table Editor has no persistable saved-view feature; the view appears in the Table Editor and is linkable | Both | View exists; reviewer opens it and sees the pilot queue | S6.6 |
| S7.2 | Runbook § "Review session": approve → `shortlisted`; reject → `rejected` + one-line `status_reason`; correcting `scoring_inputs` (re-scored automatically next Run B); pulling from the parked pool | Claude | Section complete in `docs/runbook.md` | S5.1 |
| S7.3 | Author `sql/05_kpi_queries.sql`: weekly shortlisted count, review approval rate, contact find rate, email validity rate, priority-lead share, **source yield per source** (from the per-source `source_runs` rows) | Both | Each query runs on pilot data; source-yield returns one row per connector | S6.6, S4.6 |
| S7.4 | Shortlist export: author `sql/07_shortlist_export.sql` producing the weekly CSV — company, contact, email, score, `why_fit`. To test before real shortlists exist: temporarily flip one pilot entity to `shortlisted`, export, flip back | Both | Export has correct columns + the test row; full validation happens at S8.4 | S6.6 |
| S7.5 | Runbook §§ for the rest of the weekly loop: **Monday** discovery check-in (embed the impl.-plan Appendix B connector directory; confirm each active connector ran cleanly and staging ≥ 2× weekly target; if thin, tune its filter or prioritize the next connector build) · **Thursday** handoff + BD status flips (`contacted` / `in_conversation` / `archived`) · **Friday** retro (run KPI queries, log rejection-reason patterns, **log operator hours** — a §14 KPI) | Claude | Runbook now covers the full Mon–Fri cadence of impl. plan §11 | S5.1 |
| S7.6 | n8n error workflow: on any failed execution of Run A/Run B → email/Discord notification (impl.-plan risk #7 mitigation — built **before** the first unattended scheduled run, not after the first silent failure); export → `n8n/error_notify.json` | Both | Forcing a test failure produces a notification; export in repo | S4.8 |

---

## Stage S8 — First Full Weekly Cycle (v1 acceptance)

**Goal:** prove the whole machine by delivering the first real batch.
**Exit criteria (= v1 done):** **15–20 `shortlisted` leads handed to BD**, produced by the full pipeline; runbook covers the full weekly loop; retro logged.

| ID | Substage | Owner | Deliverable / exit check | Depends on |
|---|---|---|---|---|
| S8.1 | Enrich the remaining seed companies (full Layer-B enrichment pass per runbook) | You | Every promoted entity has a primary contact **or** `metadata.enrichment_result = 'no_contact_found'` (the S5.1 convention) | S5.4, S6.10 |
| S8.2 | Execute the full Tuesday sequence for real: Run A → enrichment entry → Run B | Both | Pipeline completes; review queue populated | S8.1 |
| S8.3 | First review session: approve/reject down to 15–20 `shortlisted` | You | 15–20 leads in `shortlisted` | S8.2, S7.1, S7.2 |
| S8.4 | Handoff: run the shortlist export; deliver to BD | You | BD has the file | S8.3, S7.4 |
| S8.5 | Retro: run KPI queries; log rejection-reason patterns + operator hours; tune rubric/thresholds **in config only**; note learnings in runbook | Both | Config updated; retro notes saved; runbook complete per S7.5 | S8.3, S7.3, S7.5 |

---

## Stage S9 — Remaining Discovery Connectors + Backlog

**Sequenced after v1** (S8) — same principle as the original plan, just shifted down one connector: the **YouTube connector's real v1 batch** (built in S3, not deferred) validates the rubric, modifiers, and gates first, so we don't automate a mis-tuned filter across *more* sources before confirming the first one works. Once v1 proves shortlist quality, **S9.1–S9.4 add the remaining three Layer-A connectors**, one at a time, each proven end-to-end before the next — same build pattern as S3.3–S3.9. S9.5+ are pull-when-triggered.

| ID | Item | Owner | Trigger / notes |
|---|---|---|---|
| **S9.1** | **Google News RSS connector** (`conn_google_news_rss.json`): RSS node on keyword + `site:` trade-press queries → dedupe by `<link>` → staging with `international_ip_experience=1` | Both | Right after v1 — free deal-signal feed |
| **S9.2** | **X/Twitter intent connector** (`conn_x_intent_signals.json`): same RSS node, `site:x.com` + founder-collab phrases → **filter step** (regex/cheap-LLM to drop profile/search pages + off-topic news) → unwrap Google redirect → staging. *Not the X API (paid-only); free Google-RSS path, verified live.* | Both | With S9.1 (shares its mechanism) — noisy/partial supplementary trickle; expect ~half filtered out |
| **S9.3** | **Wikidata SPARQL connector** (`conn_wikidata.json`): HTTP node, SPARQL for US film-production companies w/ website → staging (film/TV seed) | Both | After S9.1/S9.2 — one-time seed, then occasional refresh |
| **S9.4** | **AICP scrape connector** (`conn_aicp_scrape.json`): HTTP + HTML node over East/West chapter pages → names → domain-enrich → staging (commercial shops) | Both | After S9.3 — when commercial-shop coverage needed |
| S9.5 | n8n error workflow already at S7.6; extend with per-connector alerting | Both | Once several connectors run unattended |
| S9.6 | **Clay** managed waterfall enrichment — replaces the Layer-B S5 site-scrape+pattern step | You | Manual enrichment/confirm > 2 h/wk sustained (§10.3) |
| S9.7 | Reoon paid / pay-as-you-go verifier | You | Volume outgrows Reoon's ~20/day free cap (§10.3) |
| S9.8 | IMDbPro subscription + sourcing pass | You | Free discovery mines out / discovery is the bottleneck (§10.3) |
| S9.9 | Go/Gin connector service (custom scraping, goroutines) | Both | A valuable source is inaccessible to n8n nodes (§10.3) |
| **S9.10** | **Segment 2: startup acquisition targets** — insert config row (new rubric + roles) + build its **Layer-A connectors only** (YC directory / Product Hunt / funding-news RSS / GitHub — vet each for free-tier + ToS the way §10 vetted segment 1; Crunchbase and AngelList/Wellfound likely fail that vetting, per impl. plan §9. LinkedIn is never a connector.). **Layer B (S5 enrichment), schema, Run A/B, scoring, review = reused unchanged.** | Both | TVF says go |
| S9.11 | Auto-sync shortlist to BD's tool (Sheet/CRM webhook) | Both | BD asks, or weekly CSV handoff causes misses |

---

## Critical Path & Suggested Order

```
S0.0 (host+Docker) → S0.2 → S0.6/S0.7 (n8n up) ──────┐
S0.3 (Supabase) → S1 (DB) → S2 (plumbing) ────────────┤
S0.4 (YouTube key) ────────────────────────────────────┤
S3.1–S3.2 (segment config) ────────────────────────────┴→ S3.3–S3.9 (YouTube connector, built+tuned+proven+scheduled) ─┐
                                                                                                              │
S4.1–S4.6 (Run A build, incl. gate check — startable once S2/S3.2 done) ─────────────────────────────────────────┼→ S4.7–S4.8 (Run A proven, needs S3.8's real data)
                                                                                                              │
S0.5 (Reoon+Hunter keys) ────────────────────────────────────────────────────────→ S5 (Layer-B enrichment + pilot) ←┘
                                        S6.2 (Reoon verify)                          │
                                        S6 (Run B) ←──────────────────────────────────┘
                                          └→ S7 (review + runbook + ops) → S8 (first batch = v1) ✓
                                                                              │
                  S9.1–S9.4 (remaining connectors: Google News/X-intent, Wikidata, AICP) ← after v1
```

- **S3 now builds the YouTube connector itself (S3.3–S3.9)** — no manual research runs alongside it. S3.3 needs the S0.4 API key first. S4 now also evaluates the 3 hard gates (S4.4, a gap patched in this same session) before promoting. S4 *completes* (S4.7) only after S3.8 has produced real staging data, and S5 *starts its pilot* (S5.4) only after Run A is proven (S4.7 via S5.3).
- **v1 (S8) is now connector-first, not manual-seed-first**: the YouTube connector's real batch validates the rubric/modifiers, replacing the old hand-picked-batch validation. **The remaining three connectors (S9.1–S9.4) are built after v1**, so we never automate a mis-tuned filter across more sources before the first one's proven. S0.4 (YouTube key) is needed for S3.3, not for S9.
- **The long pole is S3.3–S3.9 (connector build + tune + schedule) + S5.4/S8.1 real enrichment** — get S0.4 (the API key) early so S3.3 isn't blocked.
- Nothing in S9 blocks v1.

## Progress Tracking

Mark substages done directly in this file (`| S1.2 | ✅ ...`). v1 = S8.3 exit criterion met: **the first 15–20 shortlisted leads delivered**.

**Current status:** Stage S0 infra ✅ (host+Docker, Supabase, n8n up & registered) · Stage S1 ✅ (schema live, smoke test green, RLS verified) · Stage S2 ✅ (n8n↔Supabase credential tested, `ok=1` round-trip) · **Stage S3: S3.1 ✅ done (config incl. `score_modifiers`, `gates`, `review_checklist`, `youtube_discovery_queries`), S3.3–S3.7 ✅ done (the whole YouTube connector authored + logic-validated — 30/30 automated checks pass — and assembled into one importable `n8n/discovery/conn_youtube_api.json`).**

**Everything Claude can do without live n8n/DB access is now done.** What's left is genuinely yours, in order:
1. **S3.2** — run `sql/03_segment_us_production_houses.sql` in Supabase (if not already done).
2. **S0.4** — get the YouTube Data API key, if you haven't.
3. **S3.8** — follow `n8n/discovery/SETUP.md`: create 2 credentials, import the workflow, re-link credentials, run it, verify results, retune the admission filter if needed.
4. **S3.9** — once proven, add the weekly Schedule Trigger.

After that, Stage S4 (hard gates + dedupe/promote) is next, and most of it is already designed in this doc — tell me when S3.8 succeeds and I'll start authoring S4's SQL and Code-node logic the same way (written and validated up front, ready for you to wire in).
