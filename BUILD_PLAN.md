# TVF Universal Lead Engine — Build Plan (Rapid Evolutionary Prototypes)

**The product:** an internal TVF tool delivering **15–20 qualified, verified, human-reviewed leads per week** at $0 cash cost. First segment: small US production houses for **co-production and format licensing** (never branded-content client work). Fixed pipeline — **Discover → Promote/Dedupe → Enrich → Verify → Score → Review** — with everything segment-specific living in a config row, not code. Full architecture, data model, rubric, and compliance reasoning: see `IMPLEMENTATION_PLAN.md` at commit `9383569` (removed from the working tree, preserved in history).

**The method:** evolutionary prototyping in **small rungs, quick succession**. ~19 prototypes to v1. Each rung is one sitting, answers one question, and ends with something observably working. No rung waits on another sitting's worth of authoring — see *Cadence* below.

**Owners:** **Claude** authors (SQL, code, workflow JSON, docs); **You** execute anything needing live credentials, a browser, or judgment.

---

## The Rules

1. **One sitting, one question, observable end.** A rung that can't finish in a sitting is two rungs. A rung whose result you can't *see* (a query result, a populated table, a green run) isn't done.
2. **Leads never stop.** From P3 onward the review loop exists, so every prototype run doubles as a lead-delivery run. A stage not yet automated is done by a human — never skipped, never stubbed. There is no separate "test mode."
3. **Pipelined authoring.** While you execute rung N, Claude authors rung N+1 (and N+2 where independent). You should never be free with nothing ready to run.
4. **Re-adopt, don't retype.** Validated artifacts from commit `9383569` (schema, segment config, YouTube connector) re-enter the repo only when a rung demands them — via `git checkout 9383569 -- <path>` — and are re-verified at adoption time. Nothing enters speculatively.
5. **Batch when green.** If a rung finishes in under 30 minutes and the next one needs nothing new acquired, take both in one sitting. Quick succession beats ceremony.
6. **Specify one rung deep.** Rungs are fully specified only when the rung before them is done. Everything below P4 in this document is a committed *shape*, not a committed *spec* — early rungs exist to reshape later ones.

---

## Invariants — never prototyped loosely

Crude plumbing is fine; these four are cheap now and brutal to retrofit:

1. **Null ≠ zero.** A `scoring_inputs` key that is *absent* means "never assessed" — excluded from both earned points and the denominator. A key present with `0` means "checked, confirmed no evidence" — counts fully against the score. Never default an unassessed field to `0`; it produces plausible-looking wrong scores and poisons the calibration data.
2. **Provenance.** Every row carries `source` and `source_url`. Un-reconstructable later.
3. **Schema discipline.** Workflows evolve freely; tables evolve deliberately. The JSONB design absorbs most change without DDL.
4. **Reset before gates.** `rejected` entities are permanently shielded from re-import — a production feature, a prototyping trap. A reset script exists from P4; hard gates stay off until P9, when they're trusted (they only fire on *confirmed* disqualifying evidence and pass unknowns through, so early rungs lose nothing by omitting them).

Compliance lines that hold through every prototype: no LinkedIn scraping or automation, ever · no DIY port-25 SMTP verification · no automating CAPTCHA-gated reveals (YouTube About email, Instagram email button) · scrape only public first-party pages, respect robots.txt, keep data internal.

**Quota walls that shape the ladder:** Reoon free ≈ **20 verifications/day** (no rollover) · Hunter free = **50 credits/month**, burned per email returned · YouTube API = 10k units/day (searches cost 100, channel reads 1 — searches are the scarce thing). Any rung touching Reoon/Hunter is built against **fixtures first, live calls last**.

---

## Live-state note

The Supabase database currently *predates* the repo wipe: schema live, segment row inserted (v2: 6 rubric criteria / 3 modifiers / 4 gates / 3 review-checklist items), smoke test green, n8n↔Supabase round-trip verified. P0 reconciles repo ↔ database so the two agree before anything else happens.

---

## The Ladder

*Your time* = the human sitting for that rung. Claude's authoring happens ahead of it (Rule 3).

### Phase A — the loop exists (zero automation)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P0** | **Foundations errand** | Re-adopt from history: `sql/01_schema.sql`, `sql/02_smoke_test.sql`, `sql/03_segment...sql`, `config/segment...json`, `docker/docker-compose.yml`. Verify live DB matches the files (6/4/3 check query). **Acquire every credential in one batch:** YouTube Data API key, Reoon account, Hunter account — all free, no card. Nothing after this rung ever stalls on a signup. | Repo and DB agree; three keys in hand | ~45 min |
| **P1** | **Hand-fed candidates** | Claude authors an insert template. You enter ~8 companies into `entities` by hand — the 10 already delivered to BD plus a few fresh — filling `metadata.scoring_inputs` from their real sites. Absent key = not assessed (invariant 1). | 8 rows in `entities` with human-set inputs | ~45 min |
| **P2** | **Scoring works** | `sql/06_score.sql`: the rubric as one config-driven statement — reads `config.rubric` + `score_modifiers`, counts only assessed criteria in numerator *and* denominator, normalizes to 100, applies modifiers, clamps [0,100], writes `fit_score` + `score_breakdown` (incl. `criteria_known`). Zero segment knowledge. | You recompute one entity's score on paper; matches exactly | ~20 min |
| **P3** | **Review loop closes** | `sql/07_review_queue.sql` (view over `ready_for_review`, score-ordered). You work the queue in the Table Editor: approve → `shortlisted`, reject → `rejected` + one-line reason. | Every candidate dispositioned; **approval-rate #1 recorded**. The loop now exists — every later rung rides it | ~30 min |

### Phase B — real discovery feeds the loop

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P4** | **Connector runs live** | Re-adopt `n8n/discovery/` from history (connector + SETUP.md + code — built and logic-validated 30/30, never run live). Plus `sql/90_reset_prototype.sql`. You: create 2 credentials, import, run. | `staging_candidates` has real YouTube rows; one `source_runs` row; `raw.scoring_inputs` spot-check sane | ~45 min |
| **P5** | **Promote (minimal)** | `sql/05_promote_minimal.sql`: normalize domain → insert as `discovered`, **domain branch only**, no gates. Re-run = no-op. | Connector candidates are `entities`; re-run inserts nothing | ~15 min |
| **P6** | **Manual enrich + verify, small** | Runbook stub for the manual pass. You: top 5 candidates → find decision-maker on `/team` `/about` `/contact` → enter into `contacts` (name, role, email, `source`, `is_primary`) → verify in **Reoon's web UI** → set `email_status`. Fill `scoring_inputs` from the site while there. | 5 entities enriched, verified, inputs set | ~60 min |
| **P7** | **⚑ CHECKPOINT 1 — rubric on real data** | Score + review the connector batch end-to-end. Compute approval rate on *discovered* (not hand-picked) candidates. Read rejection reasons as a pattern; tune rubric/thresholds **in config only**; re-score; confirm ranking improves. | **Approval ≥ 60% → proceed. Below → tune config and repeat P7** (cheap: same data, re-run one SQL statement). Do not automate a filter that's still wrong | ~45 min |

### Phase C — automate the middle (Run A)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P8** | **Run A skeleton** | n8n workflow: Manual trigger → load active config → fetch pending staging → domain-normalize (Code) → insert branch from P5 → mark staging + `source_runs`. Replaces the hand-run promote. | Fresh connector batch flows staging → entities with no SQL editor open | ~30 min |
| **P9** | **Gates on** | Gate-check Code node reading `config.gates` against connector-set signals. Fires **only on confirmed** disqualifying evidence (`non_us`, oversized, no presence, confirmed dormant); all-unknown passes. Gate-failed rows land as `rejected` + reason — *through* the same upsert, so the rejected-shield covers them. | Synthetic proof: 4 known-bad candidates reject with right reasons; 1 all-unknown passes as `discovered` | ~30 min |
| **P10** | **Dedupe edges** | The two-branch upsert completed: domainless branch (`on conflict (segment_id, lower(name)) where domain is null`) + the cross-case pre-check (same name arriving with and without a domain must merge, not duplicate). Merge semantics: new keys added, existing values kept unless empty, sources appended, status kept; rejected matches skipped untouched. | Re-import proof: duplicate batch + synthetic edge rows → all `merged_duplicate`, 0 new entities | ~30 min |

### Phase D — automate verify + score (Run B)

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P11** | **Scoring in n8n** | Port `06_score.sql` to the generic scoring Code node (or wrap the SQL in an Execute Query node — decide at authoring). Scope rule: re-scores **every** entity in `enriched`/`scored`/`ready_for_review`, so reviewer corrections take effect next run. Threshold routing: `< review` stays parked, `≥ review` → queue, `≥ priority` flagged. | Batch scores match the SQL scorer exactly; routing distributes correctly | ~20 min |
| **P12** | **Reoon API** | HTTP node → Reoon **Power Mode** (the only mode with a real `catch_all` distinction — confirm the exact parameter against current docs). Map to `email_status` enum; write `email_verified_at`, `verifier`. **Pacing:** batch > 20 → queue remainder for tomorrow, never burst. Auto-set `reachable_decision_maker` (1.0 valid / 0.5 catch_all / 0) and advance → `enriched`. Built against fixtures; live calls last. | 2–3 known-good/bad emails verify correctly; over-cap batch defers | ~30 min |
| **P13** | **Pattern oracle + hedge** | Hunter free as pattern oracle only — one Domain Search per new domain, cached. Pattern found → construct 1 address. Nothing → the 3-variant hedge (`{first}.{last}@`, `{first}@`, `{f}{last}@`) landed as 3 rows, `is_primary` unset; after verification exactly one promoted (best status wins, `{first}.{last}@` breaks ties). Losing rows kept — they're the record of what not to re-spend Reoon quota on. | Synthetic 3-row hedge resolves to exactly 1 `is_primary`; Hunter cache prevents repeat lookups | ~30 min |

### Phase E — automate enrichment extraction (Layer B)

*Deliberately last among the automations: manual enrichment at 15–20/wk is tolerable (~1 h), and this is the flakiest stage (HTML variance across tiny-shop websites). Automate the deterministic things first.*

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P14** | **Site-scrape extraction** | HTTP → HTML nodes over `/team` `/about` `/leadership` `/contact` `/press`; Code node extracts names/roles/`mailto:` by DOM proximity, decoding obfuscation (Cloudflare `data-cfemail` XOR, "at"/"dot"). Built against saved fixtures of ~5 real sites from P6. | Extractor finds the same people the human found on ≥ 4 of 5 fixture sites | ~30 min |
| **P15** | **⚑ CHECKPOINT 2 — extractor vs human** | Estimate site-derived scoring inputs (`international_ip_experience`, `distribution_relationship`, `right_size`, `collaboration_openness`) from the fetched pages. Write a key **only when the site gave a signal** (invariant 1). Compare against the human baseline from P1/P6/P7. | Agreement is good → trust it. Bad → **fix extraction, keep the human in charge of inputs** until it's fixed. Disagreement here is a finding, not a formality | ~45 min |
| **P16** | **Confirm gate** | Contact-entry confirmation step (n8n Form or Table-Editor convention): a human OKs every extracted contact before it counts. `no_contact_found` convention for entities that yield nothing. The human gate is permanent by design — automation serves the reviewer. | An extracted batch flows scrape → confirm → contacts without hand-crafting rows | ~20 min |

### Phase F — production posture → v1

| ID | Prototype | What gets built | Done when | Your time |
|---|---|---|---|---|
| **P17** | **Unattended** | Weekly Schedule Triggers on the proven workflows (connector Sun night; Run A Tue). n8n error workflow → email/Discord on any failed execution — **built before the first unattended run, not after the first silent failure**. | A scheduled run completes with nobody watching; a forced failure produces a ping | ~30 min |
| **P18** | **Operate & measure — v1** | `sql/kpi_queries.sql` (shortlisted/wk, approval rate, contact-find rate, email validity, priority share, per-source yield) · `sql/shortlist_export.sql` (weekly CSV for BD) · `docs/runbook.md` covering the full Mon–Fri cadence. | **v1 = 15–20 shortlisted leads delivered on schedule, human time ≤ ~3 h/wk, runbook complete** | ~45 min |

### Phase G — post-v1 (unspecified until v1 ships)

One connector at a time, each proven end-to-end before the next — automating a mis-tuned filter across more sources just makes bad leads faster:

**P19** Google News RSS (deal signals — named company → `international_ip_experience = 1`) · **P20** X-intent via the same RSS mechanism (`site:x.com` + founder-collab phrases; noisy, needs a filter step, supplementary only) · **P21** Wikidata SPARQL (film/TV seed; one-time, notable-only) · **P22** AICP directory scrape (commercial shops; names-only, reference-only ToS).

**Backlog, pull on trigger:** Apollo Basic integration (subscription decided 2026-07-22; slot the person-match API into the P13/P14 cascade when those are real code) · Clay (manual enrichment > 2 h/wk sustained) · Reoon paid / self-hosted verifier (volume > ~20/day) · IMDbPro ~$150/yr (free discovery mines out) · Go/Gin connector service (a source n8n can't reach) · **Segment 2: startup acquisition targets** (config row + Layer-A connectors only; everything else reused unchanged — the payoff of the universal design) · shortlist auto-sync to BD tooling.

---

## Cadence

Realistic pace with pipelined authoring: **2–4 rungs per week** — Claude authors ahead, your sittings are 15–60 min each, and Rule 5 lets green rungs batch. That puts v1 (P18) at roughly **5–8 weeks**, with leads flowing every week from P3 onward because prototype runs *are* delivery runs.

The two checkpoints (P7, P15) are the only places the ladder deliberately pauses — both are calibration questions where proceeding on a wrong answer poisons everything downstream. Everything else is designed to fall in quick succession.

---

## Progress

Mark rungs done in place (`| **P2** | ✅ ...`).

**Current status:** pre-P0. Live infra (Docker+n8n, Supabase, schema, segment row v2, plumbing round-trip) survives from the previous build and gets reconciled at P0. The YouTube connector is authored and logic-validated at commit `9383569`, awaiting re-adoption at P4 and its first live run.

**Next actions:** (1) You: the P0 errand — keys + accounts. (2) Claude: re-adopt the P0 files and author P1's insert template + P2's scorer, so P1–P3 are waiting when P0 lands.
