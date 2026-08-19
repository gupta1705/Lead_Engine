# TVF Universal Lead Engine — Build Plan (Evolutionary Prototypes)

**Companion to:** `IMPLEMENTATION_PLAN.md` (the *what & why* — architecture, data model, config spec, rubric, compliance). This document is the *how*: the build broken into **prototypes**, each one a working system that produces real leads.

**Method:** agile / **evolutionary prototyping**. We build the thinnest vertical slice through all six pipeline stages, deliver leads with it, then thicken one stage at a time — replacing a human step with automation only after that step has proven to be the thing that hurts most.

**Owners:** **Claude** — authors files (SQL, code, workflow JSON, docs). **You** — anything needing live credentials, a browser, or judgment. **Both** — Claude authors, you execute and confirm.

---

## The Rule

> **Every prototype ends with leads in hand.** A stage that isn't automated yet is done by a human — not skipped, not stubbed. There is never a half-built pipeline that produces nothing.

This works here because the system was designed human-in-the-loop from the start (impl. plan §11): the manual path *is* the documented fallback for every stage. A prototype where four of six stages are a person with the Supabase Table Editor is not a degraded system — it is the system, with fewer stages automated yet.

**Corollary — later prototypes are sketched, not specified.** P1 exists to teach us things that should reshape P2–P5. Writing 200 lines of detail for P4 today would be guessing. Each prototype gets fully specified only when the one before it is done.

---

## Invariants — what we never prototype loosely

Crude plumbing is fine. These four are cheap to do right now and expensive-to-impossible to retrofit:

1. **Null vs zero.** A `scoring_inputs` key that is *absent* means "never assessed" and is excluded from both the earned points and the denominator. A key present with `0` means "checked, confirmed no evidence" and counts fully against the score (impl. plan §6.3/§7.4). Never default an unassessed field to `0`. Getting this backwards produces scores that look plausible and are wrong — and poisons the very data we are trying to learn from.
2. **Provenance.** Every row keeps `source` and `source_url`. Un-reconstructable later.
3. **The schema.** Already live and good; the JSONB design absorbs change well. Evolve workflows freely, evolve tables deliberately.
4. **Reset before gates.** `rejected` entities are permanently shielded from re-import (impl. plan §5.3) — that is a feature in production and a trap while prototyping. `sql/90_reset_prototype.sql` exists so a bad run can be wiped. Hard gates stay **off** until P2, when they are trusted; unknowns pass through anyway, so P1 loses nothing by omitting them.

---

## Where we are today

Carried over from the pre-pivot staged plan — all still valid, none wasted:

| Done | What |
|---|---|
| ✅ Infra | Host + Docker, Supabase project, n8n up and registered |
| ✅ Schema | `sql/01_schema.sql` live; `sql/02_smoke_test.sql` green; RLS verified |
| ✅ Plumbing | n8n ↔ Supabase credential tested, `ok=1` round-trip |
| ✅ Segment config | `config/segment.us-production-houses.json` (v2: 6 rubric criteria / 3 modifiers / 4 gates / 3 review-checklist items) inserted and verified live at 6/4/3 |
| ✅ YouTube connector | All 4 Code-node scripts authored + logic-validated (30/30 checks against a mocked runtime), assembled into `n8n/discovery/conn_youtube_api.json`. Import guide at `n8n/discovery/SETUP.md` |

**The one thing blocking everything: the connector has never run live.** That is P1.1.

---

## Repo Layout

```
Lead Generator/
├── IMPLEMENTATION_PLAN.md          the what & why (reference)
├── BUILD_PLAN.md                   this file — prototype tracking
├── STATUS_UPDATE.md                stakeholder-facing summary
├── config/
│   └── segment.us-production-houses.json
├── docker/
│   └── docker-compose.yml          n8n, localhost-bound
├── sql/
│   ├── 01_schema.sql               ✅ full DDL
│   ├── 02_smoke_test.sql           ✅ insert/verify/cleanup + RLS check
│   ├── 03_segment_us_production_houses.sql   ✅ segment insert (v2, fresh-install ready)
│   ├── 05_promote_minimal.sql      P1 — domain-branch promote, no gates
│   ├── 06_score.sql                P1 — config-driven rubric as one SQL statement
│   ├── 07_review_queue.sql         P1 — the review view
│   └── 90_reset_prototype.sql      P1 — wipe a bad prototype run
└── n8n/
    └── discovery/
        ├── SETUP.md                ✅ one-time import guide
        ├── conn_youtube_api.json   ✅ the 10-node connector
        └── code/*.js               ✅ the 4 Code-node scripts
```

Files arrive when their prototype does. Nothing is created speculatively.

---

## P1 — Walking Skeleton

**Question this prototype answers:** *does the rubric pick companies a human agrees with?*

That is the highest-uncertainty, highest-consequence unknown in the project — impl. plan §14 already names **review approval rate** as the metric that matters most in month one. Everything downstream is wasted effort if the rubric is miscalibrated.

**Why the human fills the scoring inputs in P1 — this is the point, not a shortcut.** If we automate site-scraping first and the shortlist comes out bad, we cannot tell whether the *rubric* is wrong or the *extractor* is wrong. Having a person read the site and set `scoring_inputs` by hand removes that confound entirely: P1 measures rubric quality in isolation. It also produces the human baseline that P3's automated extractor gets graded against.

**Automated:** discovery, promote, scoring, review surface.
**Human:** enrichment (find the contact, read the site, set the inputs), verification, approval.

**Exit criteria:** ~10 candidates scored from human-filled inputs and reviewed; approval rate recorded; rubric/thresholds tuned in config and re-scored. **Decision gate — if approval rate is under 60%, iterate P1 again. Do not start P2.**

| ID | Substage | Owner | Deliverable / exit check |
|---|---|---|---|
| P1.0 | Get the **YouTube Data API key** (free, no card) if not already done | You | Key in hand |
| P1.1 | **Run the connector live.** Follow `n8n/discovery/SETUP.md`: create 2 credentials, import, re-link, run | You | `select count(*) from staging_candidates where source='youtube_api'` > 0; one `source_runs` row; spot-check `raw.scoring_inputs` looks sane |
| P1.2 | Author `sql/05_promote_minimal.sql` — normalize domain (lowercase, strip protocol/`www.`/path) → insert into `entities` as `discovered`, **domain branch only** (`on conflict (segment_id, domain) where domain is not null`), mark staging `imported`. No gates, no domainless branch, no cross-case merge. Plus `sql/90_reset_prototype.sql` | Claude | Both files authored |
| P1.3 | Run the promote SQL in the Supabase editor | You | Entities land `discovered`; staging flagged; re-running is a no-op |
| P1.4 | **Manual enrichment pass.** Pick the ~10 most promising. For each: find the decision-maker on `/team` `/about` `/contact`, record in `contacts` via the Table Editor (`full_name`, `role_title`, `email`, `source`, `is_primary`), verify the email in **Reoon's web UI** and set `email_status`. While on the site, fill `metadata.scoring_inputs` by hand — **leave a key absent if you genuinely could not assess it** (invariant 1) | You | ~10 entities with a primary contact and human-set scoring inputs |
| P1.5 | Author `sql/06_score.sql` — the rubric as one config-driven statement: reads `segments.config.rubric` + `score_modifiers`, resolves each `input` path, counts only assessed criteria in numerator *and* denominator, normalizes to 100, applies modifiers, clamps to [0,100], writes `fit_score` + `score_breakdown` (incl. `criteria_known`). Zero segment knowledge. Plus `sql/07_review_queue.sql` (the `ready_for_review` view, ordered by score) | Claude | Desk-checked against 3 hand-computed examples |
| P1.6 | Run the scorer; hand-check one entity's score on paper against its `score_breakdown` | You | Numbers match exactly |
| P1.7 | **Review session.** Work the queue: approve → `shortlisted`, reject → `rejected` + one-line `status_reason` | You | Every candidate dispositioned; rejection reasons logged |
| P1.8 | **Calibrate.** Compute approval rate. Read the rejection reasons as a pattern, not as individual calls. Tune `rubric` points / `score_thresholds` / `score_modifiers` **in config only**, re-run the scorer, confirm the ranking improves | Both | Approval rate recorded; config tuned; leads delivered |

**What P1 deliberately does not have:** hard gates · domainless + cross-case dedupe · Run A/Run B n8n workflows · Hunter pattern oracle · the 3-variant email hedge · Brave Search domain resolution · per-source `source_runs` granularity · error notification · the contact-entry Form · the other three connectors · scheduling.

---

## P2 — Automate Promote & Score *(sketch)*

**Motivation:** P1's hand-run SQL is the cheapest thing to automate and the least risky to get wrong.

- Run A in n8n: Schedule + Manual trigger → load config → fetch pending staging → domain-normalize → **hard-gate check** (now switched on, gates fire only on confirmed evidence) → two-branch upsert → mark staging + `source_runs`.
- Port `sql/06_score.sql` to the generic scoring Code node (`n8n/scoring_code_node.js`), or keep the SQL if it is working — decide when we get there.
- Dedupe edge cases: domainless duplicates and the cross-case (same name, one row with a domain and one without).

**Exit:** a batch flows discovery → scored without anyone opening the SQL editor. Gate behaviour proven on synthetic candidates: each gate rejects on confirmed-bad evidence and **passes all-unknown through**.

---

## P3 — Automate Enrichment Extraction *(sketch)*

**Motivation:** by P3, manual enrichment is the biggest time sink — impl. plan §11 budgets it as the bulk of the weekly hour.

- Layer B site-scrape: HTTP → HTML node over `/team` `/about` `/leadership` `/contact` `/press`; Code node extracts names/roles/`mailto:` by DOM proximity, decoding obfuscation (Cloudflare `data-cfemail`, "at"/"dot").
- Estimate the site-derived scoring inputs from the same fetched pages.
- Human still confirms every entry before it counts.

**Exit:** contact find rate measured against P1's human baseline. **If the extractor's scoring inputs disagree badly with the human's, that is a finding** — fix extraction before trusting it.

---

## P4 — Automate Verification *(sketch)*

- Reoon API in **Power Mode** (the only mode with a real `catch_all` distinction) → `email_status`, `email_verified_at`, `verifier`.
- Hunter free as pattern oracle — one Domain Search per new domain, cached, never bulk.
- The 3-variant hedge when Hunter has nothing, plus automatic `is_primary` resolution (best status wins, `{first}.{last}@` breaks ties).
- Pace against the ~20/day free cap; queue the overflow.
- Auto-set `reachable_decision_maker` from the primary contact.

**Note:** free-tier quotas make iteration non-free — Reoon is ~20/day, Hunter 50/month. Build this stage against fixtures, not by trial-and-error on the live API.

---

## P5 — Harden, Schedule, Document → **v1**

- Weekly Schedule Triggers on the proven workflows.
- Error workflow (impl. plan risk #7) — **built before the first unattended run**, not after the first silent failure.
- `sql/kpi_queries.sql`, `sql/shortlist_export.sql`.
- `docs/runbook.md` covering the full Mon–Fri cadence (impl. plan §11).
- Contact-entry Form workflow.

**Exit = v1:** 15–20 shortlisted leads delivered per week on schedule, with human time inside the ~2.5–3 h/wk budget.

---

## P6+ — Widen Discovery

Only after v1 is stable. One connector at a time, each proven end-to-end before the next — automating a mis-tuned filter across four sources just produces bad leads faster.

1. **Google News RSS** — deal-signal feed; named company → `international_ip_experience = 1`.
2. **X intent signals** — same RSS mechanism, `site:x.com` + founder-collab phrases. Noisy and partial; needs a filter step. Supplementary trickle, never primary.
3. **Wikidata SPARQL** — film/TV seed; notable-only, so a one-time seed not a stream.
4. **AICP directory scrape** — commercial shops; names-only, needs domain enrichment. Reference-only ToS.

---

## Backlog — pull when triggered

| Item | Trigger |
|---|---|
| **Apollo Basic integration** (subscription decided 2026-07-22; placement still open — likely Layer-B person-match between cascade steps (a) and (b)) | Decide during P3/P4, when the enrichment cascade is real code |
| Clay managed enrichment | Manual enrichment > 2 h/wk sustained |
| Reoon paid / self-hosted verifier | Volume outgrows ~20/day |
| IMDbPro (~$150/yr) | Free discovery mines out |
| Go/Gin connector service | A valuable source is inaccessible to n8n nodes |
| **Segment 2 — startup acquisition targets** | TVF says go. Config row + Layer-A connectors only; Layer B, schema, scoring, review reused unchanged |
| Auto-sync shortlist to BD tooling | BD asks, or CSV handoff causes misses |

---

## Progress Tracking

Mark substages done in place (`| P1.2 | ✅ ...`).

**Current status:** Infra, schema, plumbing, segment config, and the YouTube connector build are ✅ (see *Where we are today*). **P1 is live work, blocked at P1.0/P1.1 — the API key and the first real connector run.** Everything after P1.1 that Claude can author without live access (P1.2, P1.5) can be written in parallel and be waiting.

**Open questions still unanswered** (impl. plan §15): who is the named Reviewer · where n8n lives long-term · Table Editor vs synced Sheet for review · BD's deal-tracking destination for `in_conversation`.
