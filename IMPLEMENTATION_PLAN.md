# TVF Universal Lead Engine — Implementation Plan

**Document type:** Internal implementation plan (TVF internal tool — not a commercial product)
**Author:** TVF AI Tools
**Date:** July 13, 2026
**Status:** Draft v1 — for review
**Supersedes:** `LeadGenerator.txt` (GTM Pipeline Implementation Plan, Stages 2–4) — see [Appendix A](#appendix-a--disposition-of-the-original-plan-leadgeneratortxt) for a stage-by-stage disposition of that document.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Background, Goals & Non-Goals](#2-background-goals--non-goals)
3. [Core Design Principles](#3-core-design-principles)
4. [System Architecture](#4-system-architecture)
5. [Data Model (Supabase / PostgreSQL)](#5-data-model-supabase--postgresql)
6. [The Segment Profile — Config Specification](#6-the-segment-profile--config-specification)
7. [Pipeline Stages in Detail](#7-pipeline-stages-in-detail)
8. [Segment 1: US Production Houses (Co-Production & Format Licensing)](#8-segment-1-us-production-houses-co-production--format-licensing)
9. [Future Segment Sketch: Startup Acquisition Targets](#9-future-segment-sketch-startup-acquisition-targets)
10. [Tooling, Free-Tier Limits & Costs](#10-tooling-free-tier-limits--costs)
11. [Weekly Operating Cadence](#11-weekly-operating-cadence)
12. [Phased Roadmap](#12-phased-roadmap)
13. [Compliance & Risk Register](#13-compliance--risk-register)
14. [KPIs & Success Metrics](#14-kpis--success-metrics)
15. [Open Questions](#15-open-questions)
- [Appendix A — Disposition of the Original Plan](#appendix-a--disposition-of-the-original-plan-leadgeneratortxt)
- [Appendix B — Reference Source Directory](#appendix-b--reference-source-directory)

---

## 1. Executive Summary

TVF needs a steady flow of **15–20 qualified leads per week**, starting with **small US production houses** for **co-production and format-licensing** conversations, and later expanding to entirely different lead types (e.g., **startups TVF could acquire**).

Rather than building a one-off list or a segment-specific scraper, we are building a **universal lead engine**: one fixed pipeline —

> **Discover → Dedupe/Store → Enrich → Verify → Score → Review**

(dedupe runs immediately after discovery, so no enrichment effort or credits are ever spent on a company we already know) — where everything segment-specific (sources, fit rubric, target contact roles, metadata fields) lives in a **segment profile**: a configuration object stored as data, not code. Adding a new lead segment later means inserting a new profile row and writing small source importers — **zero changes to the core engine**.

Key decisions locked in during ideation:

| Decision | Choice |
|---|---|
| Tool type | TVF **internal** tool (single-tenant, no external users, no product UI) |
| First segment | Small US production houses — commercial/branded-content shops, digital/YouTube/social studios, and film/TV/streaming producers |
| Collaboration goal | **Co-production of content** and **format licensing / distribution** |
| Volume target | 15–20 curated leads/week (~800–1,000/year) — quality over volume |
| Budget | **Completely free** — a verified $0 engine (YouTube Data API, Wikidata, AICP, Google News RSS for discovery; first-party site-scraping + email-pattern + Hunter free for contacts; Reoon for verification). Paid upgrades (IMDbPro, Clay, LinkedIn Sales Navigator) deferred. See §10 for the verification behind each. |
| Outreach automation | **Explicitly out of scope** — this system produces a ranked, verified, human-reviewed lead list; sending email is a separate, later concern |
| Stack | Supabase (PostgreSQL, free tier) + n8n Community Edition (self-hosted, Docker) + spreadsheet/table review layer |
| Deferred | Go/Gin backend + custom scrapers (and any EC2 host *for them*) — Phase 3 only, if a specific source demands them. (EC2 as a plain n8n host is separately permitted but least-preferred — see §4.3.) |

The strategy insight that shapes everything: **co-production and format licensing are high-value, low-volume, relationship-driven deals.** We need ~100–300 well-chosen companies with the right decision-maker identified — not 10,000 scraped contacts. The system is therefore built for **account-based curation with a human in the loop**, not mass outbound.

---

## 2. Background, Goals & Non-Goals

### 2.1 Background

- The original plan (`LeadGenerator.txt`) described a volume-outbound GTM pipeline: LinkedIn HTML scraping via a Go/Gin backend, algorithmic email permutation, DIY SMTP handshake verification, hardcoded lead scoring, priority queues, tracking pixels, and Discord/Slack VIP alerts.
- During ideation we determined that machinery solves the **wrong problem** for TVF's actual goal (curated co-pro/format leads at 15–20/week), and several of its techniques carry legal/technical risk (LinkedIn ToS violations, AWS blocking outbound port 25, IP blacklisting). See Appendix A.
- What survives from the original plan: the **n8n Community Edition orchestration** choice, the **Supabase/PostgreSQL persistence** choice, the **JSONB metadata column** instinct (generalized), **UPSERT deduplication**, and the **`lead_status` state machine** (generalized).

### 2.2 Goals

1. **Deliver 15–20 qualified, verified, human-reviewed leads per week** for the active segment, starting with US production houses.
2. **Be segment-agnostic at the core.** The same engine must later serve "startups we could acquire" and any future segment purely through configuration + new source importers.
3. **Run on free tooling** until lead quality justifies paid upgrades.
4. **Keep a durable, deduplicated, queryable lead database** in Supabase that outlives any individual spreadsheet or campaign.
5. **Encode lead-fit knowledge as data** (per-segment scoring rubrics) so scoring logic is inspectable, tunable, and reusable.

### 2.3 Non-Goals (explicitly out of scope for this build)

- ❌ **Email sending / sequencing / outreach automation** of any kind. The deliverable stops at "ranked, verified, reviewed lead list."
- ❌ **Branded-content client work and US service/production-partner positioning.** The collaboration goal is co-production and format licensing/distribution *only*. Commercial/branded-content shops are in scope as **co-pro/format counterparties**, not as clients TVF pitches services to, and TVF is not positioning as anyone's US production vendor. Researchers and reviewers must not qualify leads against those excluded motions.
- ❌ Tracking pixels, open/click intent signals, VIP alerting (original Stage 4.4–4.5) — these only matter once outreach exists.
- ❌ Mass scraping of LinkedIn or any ToS-protected source.
- ❌ DIY SMTP (port 25) email verification.
- ❌ Multi-tenant support, external users, or a polished product UI — this is internal tooling.
- ❌ CRM replacement. Once a lead is "in conversation," it graduates out of this system into whatever TVF's BD team uses.

---

## 3. Core Design Principles

1. **The pipeline is fixed; the profile is data.** Every segment flows through the same six stages. What differs — sources, rubric, contact roles, metadata shape — is stored in a `segments.config` JSONB column. No segment-specific logic is ever hardcoded into the engine.
2. **Two layers: per-segment DISCOVERY, shared ENRICHMENT.** This is the key to serving totally different lead types (production houses today, acquisition-target startups later) without a rewrite. **Layer A — Discovery** connectors are segment-specific: *where and how you find candidate companies* (production houses come from YouTube/Wikidata/AICP/trade-press; startups would come from Crunchbase/YC/Product Hunt). Each is a small importer writing rows of one identical shape into `staging_candidates`. **Layer B — Enrichment → Verify** (and the equally-shared Score and Review stages) is segment-agnostic and reused verbatim. (Dedupe/Store isn't part of Layer B — it runs at *intake*, immediately after discovery, so no enrichment effort is spent on a company we already have; see the canonical pipeline in §1.) *Every* company, whatever the segment, has a website with a team/about page, so the same site-scrape → email-pattern → verify contact machinery works for a film studio and a fintech startup alike. Swapping segments = swap Layer-A connectors + the rubric; Layer B, dedupe, scoring, and review never move. The plugin slot is universal; the discovery plugins are not.
3. **Human in the loop, by design.** At 15–20 leads/week, a human review pass is cheap and dramatically raises quality. No lead reaches "shortlisted" without a person confirming it. Automation serves the reviewer; it does not replace them.
4. **Completely free by construction, verified not assumed.** Discovery, enrichment, and verification each run on a source whose free ceiling was adversarially checked to cover ~20–50 leads/week *forever* (not a trial): YouTube Data API (10k units/day), Wikidata (open), Google News RSS (open), first-party site-scraping via self-hosted n8n (uncapped), Hunter free (50 credits/mo, patterns only), Reoon (~20 verifications/day). Notably, **Apollo was dropped** — its free tier is a freemium trap and its ToS prohibits exporting into our own DB — and the tiny founder-run shops we want live on their own websites anyway, not in B2B databases. Custom code (Go/Gin) enters only in Phase 3, and only for sources that genuinely need it.
5. **Right-size for volume.** ~20 leads/week is tiny. No queues, no concurrency infrastructure, no alerting stack. A weekly scheduled n8n run and a review table are sufficient. Complexity is added when a bottleneck is *observed*, not predicted.
6. **Fit-and-appetite scoring beats title-and-geography scoring.** The original "Founder = +40, NY/LA = +20" rubric measures reachability, not deal likelihood. Rubrics in this system score evidence of appetite (e.g., "has already adapted international IP") first.
7. **Everything auditable.** Every entity records its source, every score records its breakdown, every import records a run log. When a lead looks wrong, we can trace why it entered and how it scored.

---

## 4. System Architecture

### 4.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│              LAYER A — DISCOVERY CONNECTORS (per segment)               │
│                                                                         │
│  Segment 1 (Production Houses):            Segment 2 (Startups, later): │
│  · YouTube Data API (digital studios) 1st  · Y Combinator directory     │
│  · Google News RSS + X-intent (signal) 2nd · Product Hunt               │
│  · Wikidata SPARQL (film/TV) 3rd           · Funding-news RSS           │
│  · AICP directory scrape (commercial) 4th  · GitHub                     │
│  (built one at a time, each proven before the next — §8.2/§12)          │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ rows of one identical shape
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     staging_candidates (Supabase)                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 n8n COMMUNITY EDITION (Docker, self-hosted)             │
│                                                                         │
│   RUN A (weekly Schedule Trigger):                                      │
│     → Load active segment profile (segments.config)                     │
│     → Pull batch from staging_candidates                                │
│     → Evaluate hard gates (config.gates) + dedupe + promote (§7.2)      │
│                                                                         │
│   LAYER B — ENRICHMENT (shared across ALL segments):                    │
│     → Scrape entity's /team /about /contact (HTTP+HTML nodes)            │
│     → Guess email pattern; Hunter free = pattern oracle (§7.3)          │
│     → Operator confirms/records the primary contact (light manual gate) │
│                                                                         │
│   RUN B (verify + score, config-driven):                                │
│     → Verify: email validity              (Reoon API, free)             │
│     → Set reachable_decision_maker input; status → enriched             │
│     → Score: apply rubric from config     (Code node, config-driven)    │
│     → Write fit_score + score_breakdown; route to ready_for_review      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      SUPABASE (PostgreSQL, free tier)                   │
│   segments · entities · contacts · staging_candidates · source_runs     │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          REVIEW LAYER (human)                           │
│   Supabase Table Editor view (or synced Google Sheet)                   │
│   Reviewer approves → status: shortlisted                               │
│   Reviewer rejects  → status: rejected (+ reason)                       │
│   Weekly output: 15–20 shortlisted leads handed to BD                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Component Responsibilities

| Component | Responsibility | Explicitly NOT responsible for |
|---|---|---|
| **Discovery connectors (Layer A, per segment)** | Get candidate companies into `staging_candidates` in a uniform shape. Segment 1, built one at a time: YouTube Data API, Google News RSS (+X-intent), Wikidata, AICP scrape. | Dedupe, scoring, contact finding |
| **n8n (Community, Docker)** | Orchestration: the weekly batch run, running the discovery connectors + enrichment/verification, applying the scoring rubric, writing to Supabase | Hosting business logic that belongs in config; sending email |
| **Supabase (PostgreSQL)** | System of record: segments, entities, contacts, staging, run logs. Free tier. | Being a CRM |
| **Enrichment (Layer B, shared)** | Given an entity + domain, find the decision-maker's name/role/email: first-party site scraping (`/team`,`/about`) + email-pattern construction + Hunter free (pattern oracle only). Segment-agnostic. | Company *discovery* (that's Layer A) |
| **Reoon (free tier)** | Validate enriched emails before a human ever sees them (~20/day free, with API) | — |
| **Review layer** | Human approval/rejection; the quality gate | — |
| **Go/Gin backend** | **Deferred to Phase 3.** Only if/when a source needs custom scraping or concurrency n8n can't handle. | — |

### 4.3 Hosting

- **n8n**: Docker container. Options, in order of preference for a $0 start:
  1. An always-on office machine / spare desktop at TVF (true $0).
  2. Oracle Cloud "Always Free" VM (true $0, but signup friction).
  3. AWS EC2 t3.micro — under AWS's current free plan (post-July-2025), new accounts get a **credit-based** allowance (~$100–200, expiring after up to 6 months), *not* the old 12-month free tier; after credits, ~$8–15/month. This was the original plan's choice, but it is **not free forever**. (Hosting n8n on EC2 is distinct from the *deferred* Phase-3 Go/Gin backend — choosing EC2 here does not un-defer that.)
- n8n's visual editor exposed on port 5678 (as in the original plan) — **bind to localhost or put behind basic auth/VPN; do not expose the editor to the public internet.**
- Register the self-hosted instance with an email address to unlock the Community Edition's free registered features (Folders for organizing sub-workflows, "Debug in editor") — carried over from the original plan's sub-stage 3.4.
- n8n's own execution data stays in its default SQLite; **lead data lives exclusively in Supabase** (managed Postgres, free tier).
- **n8n → Supabase connectivity:** configure the n8n Postgres credential with Supabase's **session-mode pooler** connection string (`aws-*.pooler.supabase.com:5432`). The direct `db.<ref>.supabase.co:5432` host is IPv6-only on the free tier and will fail from IPv4-only networks/containers. n8n talks to the database via this Postgres connection (which bypasses RLS as the `postgres` role); the project's `anon` key is never used anywhere in this system (see the RLS block in §5.1).
- **Supabase free tier** limits (as of writing — verify current): 500 MB database, 2 projects, pauses after 1 week of inactivity. At ~1,000 leads/year with JSONB metadata, storage will remain in the low tens of MB — comfortably within limits. The weekly n8n run doubles as keep-alive activity.

---

## 5. Data Model (Supabase / PostgreSQL)

The schema is deliberately **entity-type-agnostic**. A row in `entities` can be a production company today and a fintech startup next quarter; everything type-specific lives in `metadata` (per-entity) and `segments.config` (per-segment).

### 5.1 DDL

```sql
-- ============================================================
-- TVF Universal Lead Engine — schema v1
-- Target: Supabase (PostgreSQL 15+)
-- ============================================================

-- ------------------------------------------------------------
-- segments: one row per lead segment. config drives the engine.
-- ------------------------------------------------------------
create table segments (
  id            uuid primary key default gen_random_uuid(),
  slug          text unique not null,          -- e.g. 'us-production-houses'
  name          text not null,                 -- e.g. 'US Production Houses — Co-Pro & Format'
  entity_type   text not null,                 -- e.g. 'production_company', 'startup'
  config        jsonb not null default '{}',   -- full segment profile (see §6)
  is_active     boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

-- ------------------------------------------------------------
-- entities: the companies/organizations themselves.
-- ------------------------------------------------------------
create table entities (
  id                uuid primary key default gen_random_uuid(),
  segment_id        uuid not null references segments(id),
  name              text not null,
  domain            text,                      -- normalized: lowercase, no www., no protocol
  source            text not null,             -- connector slug, e.g. 'youtube_api', 'google_news_rss'
  source_url        text,                      -- where we found them (auditability)
  metadata          jsonb not null default '{}', -- segment-specific attributes (see §6.3)
  fit_score         numeric,                   -- 0–100, from rubric
  score_breakdown   jsonb,                     -- per-criterion points, for auditability
  status            text not null default 'discovered'
                    check (status in (
                      'discovered',        -- landed from a source, not yet enriched
                      'enriched',          -- contact found + email verified
                      'scored',            -- rubric applied
                      'ready_for_review',  -- in the weekly review batch
                      'shortlisted',       -- human-approved: THIS IS A LEAD
                      'rejected',          -- human-rejected (keep row to prevent re-import)
                      'contacted',         -- BD has reached out (tracked coarsely)
                      'in_conversation',   -- graduated to BD's own tracking
                      'archived'           -- stale / no longer relevant
                    )),
  status_reason     text,                      -- esp. for 'rejected'
  status_changed_at timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- Dedupe key: one company per segment per domain.
-- NOTE: the name-based index only guards duplicates where BOTH rows lack
-- a domain (Postgres treats NULLs as distinct). The cross-case — the same
-- company entering once WITH and once WITHOUT a domain — cannot be caught
-- by any index here; the promote step's pre-insert name check handles it (§7.2).
create unique index uq_entities_segment_domain
  on entities (segment_id, domain) where domain is not null;
create unique index uq_entities_segment_name_nodomain
  on entities (segment_id, lower(name)) where domain is null;

create index idx_entities_status on entities (segment_id, status);
create index idx_entities_score  on entities (segment_id, fit_score desc);
create index idx_entities_metadata on entities using gin (metadata);

-- ------------------------------------------------------------
-- contacts: people at those entities.
-- ------------------------------------------------------------
create table contacts (
  id                uuid primary key default gen_random_uuid(),
  entity_id         uuid not null references entities(id) on delete cascade,
  full_name         text,
  role_title        text,                      -- as found, e.g. 'Head of Development'
  linkedin_url      text,
  email             text,
  email_status      text not null default 'unverified'
                    check (email_status in (
                      'unverified', 'valid', 'invalid', 'catch_all', 'unknown'
                    )),
  email_verified_at timestamptz,
  verifier          text,                      -- e.g. 'reoon'
  source            text,                      -- e.g. 'company_website', 'site_scrape', 'hunter_pattern', 'manual'
  is_primary        boolean not null default false,  -- the contact we'd actually pitch
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- Multiple rows CAN share an entity_id + full_name: when the pattern oracle (Hunter) has
-- no data for a domain, Layer B writes several pattern-guess candidates for the same person
-- (same name, different email); exactly one is promoted to is_primary after verification (§7.3).
create index idx_contacts_entity on contacts (entity_id);
create unique index uq_contacts_entity_email
  on contacts (entity_id, lower(email)) where email is not null;

-- ------------------------------------------------------------
-- staging_candidates: raw, uniform landing zone for ALL connectors.
-- Connectors only ever write here; the engine promotes rows to entities.
-- ------------------------------------------------------------
create table staging_candidates (
  id            uuid primary key default gen_random_uuid(),
  segment_id    uuid not null references segments(id),
  name          text not null,
  domain        text,
  source        text not null,
  source_url    text,
  raw           jsonb not null default '{}',   -- whatever the connector captured, unmodified
  imported      boolean not null default false, -- promoted to entities yet?
  import_result text
                check (import_result in ('inserted','merged_duplicate','skipped_rejected')),
                -- stays NULL until the row is processed (NULL passes the CHECK)
  created_at    timestamptz not null default now()
);

create index idx_staging_pending on staging_candidates (segment_id, imported)
  where imported = false;

-- ------------------------------------------------------------
-- source_runs: audit log of every connector/import execution.
-- ------------------------------------------------------------
create table source_runs (
  id               uuid primary key default gen_random_uuid(),
  segment_id       uuid references segments(id),
  source           text not null,
  started_at       timestamptz not null default now(),
  finished_at      timestamptz,
  candidates_found int not null default 0,
  candidates_new   int not null default 0,    -- after dedupe
  status           text not null default 'running'
                   check (status in ('running','succeeded','failed')),
  error            text,
  notes            text
);

-- ------------------------------------------------------------
-- updated_at maintenance
-- ------------------------------------------------------------
create or replace function set_updated_at() returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_segments_updated  before update on segments  for each row execute function set_updated_at();
create trigger trg_entities_updated  before update on entities  for each row execute function set_updated_at();
create trigger trg_contacts_updated  before update on contacts  for each row execute function set_updated_at();

-- Track status transitions
create or replace function set_status_changed_at() returns trigger as $$
begin
  if new.status is distinct from old.status then
    new.status_changed_at = now();
  end if;
  return new;
end;
$$ language plpgsql;

create trigger trg_entities_status before update on entities
  for each row execute function set_status_changed_at();

-- ------------------------------------------------------------
-- Row Level Security. These tables live in the public schema, which
-- Supabase auto-exposes through its REST (PostgREST) API — without RLS,
-- anyone holding the project's anon key could read/write the entire
-- lead database. Enabling RLS with NO policies blocks all anon/
-- authenticated API access. n8n is unaffected: it connects via the
-- direct Postgres connection (session pooler), which bypasses RLS.
-- The anon key is never used anywhere in this system.
-- ------------------------------------------------------------
alter table segments           enable row level security;
alter table entities           enable row level security;
alter table contacts           enable row level security;
alter table staging_candidates enable row level security;
alter table source_runs        enable row level security;
```

### 5.2 Status Lifecycle

```
                    ┌──────────────┐
   connector ──────▶│  discovered  │
                    └──────┬───────┘
                           ▼  (n8n: contact found + verified)
                    ┌──────────────┐
                    │   enriched   │
                    └──────┬───────┘
                           ▼  (n8n: rubric applied)
                    ┌──────────────┐
                    │    scored    │
                    └──────┬───────┘
                           ▼  (n8n: only if fit_score ≥ score_threshold_review;
                           │   below threshold → stays parked in 'scored')
                    ┌──────────────────┐
                    │ ready_for_review │
                    └───┬──────────┬───┘
              approve   ▼          ▼   reject (+reason)
              ┌─────────────┐  ┌──────────┐
              │ shortlisted │  │ rejected │  ← rows kept forever:
              └──────┬──────┘  └──────────┘    dedupe prevents re-import
                     ▼  (BD acts — outside this system)
              ┌─────────────┐   ┌─────────────────┐   ┌──────────┐
              │  contacted  │──▶│ in_conversation │──▶│ archived │
              └─────────────┘   └─────────────────┘   └──────────┘
```

**"A lead" is defined as an entity in `shortlisted` status**: right segment, scored, decision-maker contact identified, email verified, human-approved. The 15–20/week target counts *shortlisted* entities.

Two annotations the diagram can't draw cleanly:
- **`archived` is reachable from any post-review status** (`shortlisted`, `contacted`, `in_conversation`) *and* from long-parked `scored` rows — not only from `in_conversation` as drawn. Anything stale can be archived.
- The `scored → ready_for_review` transition is **threshold-gated**, not automatic; parked rows can be promoted manually (§7.5).

### 5.3 Deduplication Rules

Carried over and generalized from the original plan's UPSERT design (sub-stage 3.2):

1. **Primary key for dedupe: `(segment_id, normalized domain)`.** Domain normalization: lowercase, strip protocol/`www.`/trailing path.
2. If domain is unknown, fall back to `(segment_id, lower(name))`.
3. On duplicate: **merge, never duplicate.** Metadata merge rule (deterministic): keys present only in the new payload are **added**; for keys present in both, the **existing value is kept** unless it is `null`/empty-string/empty-array, in which case the new value fills it. Append the new source to a `metadata.sources_seen` array; keep the existing status.
   **Exception — rejected entities:** a candidate matching a `rejected` entity is **skipped entirely** (no merge, no metadata update; staging row marked `import_result = 'skipped_rejected'`), so nothing ever mutates or resurrects a rejected row. This is why rejected rows are never deleted.
4. The same company **may** exist in two different segments (a startup could be both an acquisition target and a partner) — dedupe is per-segment by design.

---

## 6. The Segment Profile — Config Specification

The heart of the "universal" design. Everything the engine needs to know about a segment lives in `segments.config`.

### 6.1 Config JSON Schema (informal)

```jsonc
{
  // --- identity ---
  "entity_type": "production_company",       // what a row IS in this segment

  // --- volume & thresholds ---
  "weekly_target": 20,                       // how many shortlist candidates per weekly batch
  "batch_size": 30,                          // pull more than target; review filters down
  "score_threshold_review": 40,              // below this: auto-park as low-priority, don't waste review time
  "score_threshold_priority": 75,            // at/above this: flag "review first"

  // --- who we want to talk to ---
  "target_contact_roles": [                  // ordered by preference
    "Founder", "Co-Founder",
    "Head of Development", "Development Executive",
    "Executive Producer",
    "Head of Acquisitions", "Head of Distribution"
  ],

  // --- scoring rubric (see §7.4 for how the engine applies it) ---
  "rubric": [
    {
      "key": "international_ip_experience",
      "label": "Has adapted or co-produced international IP/formats",
      "points": 30,
      "input": "metadata.scoring_inputs.international_ip_experience",  // boolean or 0–1 fraction
      "guidance": "Trade-press coverage of a format deal, an adapted foreign show in credits, or co-pro credit with a non-US company. STRONGEST signal."
    },
    {
      "key": "genre_fit",
      "label": "Makes content in TVF lanes (comedy, slice-of-life, young-adult, workplace)",
      "points": 25,
      "input": "metadata.scoring_inputs.genre_fit",
      "guidance": "Check credits/website/YouTube. Full points if core focus; half if occasional."
    },
    {
      "key": "distribution_relationship",
      "label": "Live output relationship with a streamer/network/major platform",
      "points": 20,
      "input": "metadata.scoring_inputs.distribution_relationship",
      "guidance": "A co-pro must land somewhere. First-look deals, recent commissions, or consistent platform sales count."
    },
    {
      "key": "right_size",
      "label": "Right size: ~5–50 people, real credits, independent",
      "points": 15,
      "input": "metadata.scoring_inputs.right_size",
      "guidance": "Big enough to execute, small enough to want a partner. LinkedIn headcount + credit history."
    },
    {
      "key": "reachable_decision_maker",
      "label": "Named decision-maker identified and reachable",
      "points": 10,
      "input": "metadata.scoring_inputs.reachable_decision_maker",
      "guidance": "Auto-set by the engine: 1.0 if a target-role contact with a 'valid' email exists, 0.5 if catch_all, else 0."
    },
    {
      "key": "collaboration_openness",
      "label": "Demonstrated openness to collaboration: explicit invitation, collective/partner-led model, or co-production track record",
      "points": 15,
      "input": "metadata.scoring_inputs.collaboration_openness",
      "guidance": "Added later — dilutes the pool from 100 to 115. Full credit for an explicit invitation, collective/partner-led structure, or a co-pro track record; half for a weaker signal."
    }
  ],
  // points now sum to 115 (not enforced; the engine normalizes regardless — §7.4)

  // --- score MODIFIERS: applied AFTER the base 0-100 rubric score, then the
  // final fit_score is clamped to [0,100]. NOT part of the weighted rubric
  // pool above (folding a -20/+6 straight into that sum would either shift
  // every other criterion's relative weight or let the score exceed 100 —
  // see §7.4 for the two-stage formula). ---
  "score_modifiers": [
    {
      "key": "client_work_dominance",
      "label": "PENALTY: output dominated by client/branded-content work, not owned IP",
      "max_penalty": -20,
      "input": "metadata.scoring_inputs.client_work_dominance",
      "guidance": "A /work page full of brand-client logos is a NEGATIVE, not a portfolio positive — it signals work-for-hire, not an IP-owning studio that can co-produce or license a format. 1.0 = entirely client work (full -20), 0 = no evidence of client-work dominance (no penalty — the default/good case). Soft subtractor, not a hard gate: an otherwise-strong candidate can still surface for review, just scored lower."
    },
    {
      "key": "india_diaspora_affinity",
      "label": "BONUS: existing India/Asia ties, diaspora-crossover audience, or prior work with an Indian company",
      "max_bonus": 6,
      "input": "metadata.scoring_inputs.india_diaspora_affinity",
      "guidance": "Rare signal — most good leads will legitimately score 0 here, which must NOT be read as a strike against them. Kept small and additive so it never overrides the 5 primary fit signals; rewards the rare candidate where a TVF pitch has an obvious extra hook."
    },
    {
      "key": "revenue_above_cap",
      "label": "PENALTY: revenue estimate above the ~$1M microbudget-scale ceiling",
      "max_penalty": -10,
      "input": "metadata.scoring_inputs.revenue_above_cap",
      "guidance": "NOT YET CONNECTOR-AUTOMATED. Private companies rarely publish revenue; estimate via third-party tools (LeadIQ, Buzzfile, RocketReach) where available, else reviewer judgment — those tools' free-tier usability hasn't been adversarially verified the way every other tool in §10 has, so this stays reviewer-set until it is. 1.0 = confirmed estimate above ~$1M ('borderline'), 0 = at/under ~$1M or microbudget-scale ('clean fit') or no negative evidence. Soft subtractor — flags, does not auto-reject."
    }
  ],

  // --- HARD GATES: auto-enforced CENTRALLY at Run A's promote step (§7.2),
  // never duplicated per-connector. A candidate failing ANY gate is inserted
  // into entities as status='rejected' with status_reason = the gate key —
  // never silently dropped, so the existing "rejected stays rejected
  // forever" dedupe protection (§5.3) prevents re-processing it every week.
  // Each gate fires ONLY on confirmed disqualifying evidence; blank/unknown
  // always PASSES — this is what keeps a "strict" gate from silently
  // dropping a good lead just because its data happens to be missing.
  // Gate INPUTS are set by the connector at discovery time (cheap, from API
  // fields already in hand) — NOT by Layer B, which runs after Run A and
  // would be too late to feed a promote-time decision. ---
  "gates": [
    {
      "key": "us_geography",
      "label": "Primary operation/HQ must be in the United States",
      "input": "metadata.scoring_inputs.geography_signal",   // 'us' | 'non_us' | null (unknown)
      "exclude_when": "non_us",
      "guidance": "Fires ONLY on confirmed non-US evidence (e.g. YouTube channel country field explicitly set to non-US; a non-US address/phone/currency found later on the site; a foreign ccTLD with no named US office). Blank/unknown passes through."
    },
    {
      "key": "not_a_major_or_oversized",
      "label": "Exclude majors, their named subsidiaries, and anything clearly oversized",
      "input": "metadata.scoring_inputs.major_or_oversized_signal",   // true | false | null
      "exclude_when": true,
      "guidance": "Name/keyword match against known majors, or a confirmed size signal well beyond the ~50-person ceiling (e.g. an extreme subscriber-count outlier). Blank/unknown passes through."
    },
    {
      "key": "usable_first_party_presence",
      "label": "Must have SOME reachable presence — website, owned channel, or social",
      "input": "metadata.scoring_inputs.has_reachable_presence",   // true | false | null
      "exclude_when": false,
      "guidance": "Loosened from 'must have a website' — that wrongly excluded film/TV producers who sell to networks and run no channel. A YouTube channel itself already satisfies this for connector-sourced candidates, so this gate effectively always passes them."
    },
    {
      "key": "is_active",
      "label": "Company/channel must be currently active, not dormant or defunct",
      "input": "metadata.scoring_inputs.activity_signal",   // 'active' | 'confirmed_dormant' | null
      "exclude_when": "confirmed_dormant",
      "guidance": "Fires ONLY on confirmed dormancy (no upload/site activity in 12+ months, an explicit closed/discontinued notice). Blank/unknown passes through. Connector makes a cheap best-effort read from upload recency; Layer B enrichment can override it once it visits the real site."
    }
  ],

  // --- REVIEW CHECKLIST: human-judgment-only signals free connectors cannot
  // verify. Never auto-enforced — these are NOT in the gates array above, and
  // Run A's promote-time gate check never reads this block. The reviewer
  // confirms each item at S7.5 before shortlisting. ---
  "review_checklist": [
    {
      "key": "is_a_content_production_company",
      "label": "Is this actually an IP-owning production company, not a service vendor, agency, institution, or an unrelated same-name LLC?",
      "guidance": "Free sources cannot reliably tell these apart at intake."
    },
    {
      "key": "in_scope_subtype",
      "label": "Is the subtype actually in scope (commercial/branded, digital/social, film/TV/streaming) and NOT corporate/service video?",
      "guidance": "Confirm against real site/channel content, not just the keyword match that got it into staging."
    },
    {
      "key": "independent_ownership",
      "label": "Founder/partner-owned — no studio/network parent, no PE ownership, no large-scale VC backing on record",
      "guidance": "Check Crunchbase/PitchBook/press where feasible — no free connector can verify cap-table structure. A single small convertible note (~$500K) from non-marquee sources is a documented exception, not a disqualifier."
    }
  ],

  // --- YouTube connector search queries (config-driven, not hardcoded in
  // the n8n workflow — tune by editing this array, not the workflow). Each
  // query's genre_hint feeds directly into scoring_inputs.genre_fit for any
  // candidate that query surfaces (§7.1 discovery, §7.4 scoring); tune the
  // exact list during S3.7's real-query testing. ---
  "youtube_discovery_queries": [
    { "query": "digital comedy studio",            "genre_hint": "comedy" },
    { "query": "workplace comedy channel",         "genre_hint": "workplace" },
    { "query": "young adult drama studio",         "genre_hint": "young-adult" },
    { "query": "slice of life web series studio",  "genre_hint": "slice-of-life" },
    { "query": "branded content studio",           "genre_hint": null },
    { "query": "production company",               "genre_hint": null }
  ],

  // --- what metadata this segment records on each entity ---
  "metadata_fields": [
    "subtype",                    // 'commercial_branded' | 'digital_social' | 'film_tv_streaming'
    "hq_city", "hq_state",
    "team_size_estimate",
    "genres",                     // array
    "notable_credits",            // array of strings
    "format_deals",               // array: known format adaptations/co-pros
    "platform_relationships",     // array: streamers/networks they've sold to
    "why_fit",                    // free-text one-liner: why this is a TVF fit
    "scoring_inputs"              // object: the rubric inputs above
  ],

  // --- LAYER A: registered discovery connectors for this segment (all free, verified §10).
  // "phase" = BUILD ORDER — connectors go live one at a time, each proven end-to-end
  // through the full pipeline before the next is built (§8.2/§12). No manual seed. ---
  "sources": [
    { "slug": "youtube_api",    "name": "YouTube Data API v3 (search+channels)", "kind": "api",    "phase": 1,
      "detail": "BUILD FIRST. PRIORITY: digital/YouTube/social studios. 10k units/day free. Filter creators-vs-studios by size/keyword/email-in-description." },
    { "slug": "google_news_rss","name": "Google News RSS (keyword + site: trades)","kind": "rss",  "phase": 2,
      "detail": "SIGNAL: catches 'US shop adapts foreign format' deal announcements from C21/Realscreen/Variety/Deadline. Company named → high international_ip_experience." },
    { "slug": "x_intent_signals","name": "X/Twitter intent posts via Google News RSS", "kind": "rss", "phase": 2,
      "detail": "SIGNAL: founder-collab posts. news.google.com/rss/search?q=site:x.com (\"seeking a studio partner\" OR \"looking to co-produce\" OR \"open to collaboration\") — NOT the X API (paid-only, Feb 2026). Free, no key, but NOISY + PARTIAL: Google indexes only a slice of X, feed mixes profile/search pages + off-topic news → needs a filter step + human review. Supplementary trickle, not a primary source." },
    { "slug": "wikidata",       "name": "Wikidata SPARQL",                       "kind": "api",    "phase": 3,
      "detail": "Film/TV/streaming producer seed: name + official website (P856) + industry. CC0, free forever. Notable-only, so a seed not a stream." },
    { "slug": "aicp_directory", "name": "AICP member directory (scrape)",        "kind": "scrape", "phase": 4,
      "detail": "Commercial/branded shops. Static HTML, names-only (needs domain enrichment). ToS = reference-only: internal use, no resale." }
  ],

  // --- LAYER B: shared enrichment & verification providers (same for every segment) ---
  "enrichment": {
    "contact_method":  "site_scrape_then_pattern",  // scrape /team,/about → guess {first}.{last}@domain; Hunter free = pattern oracle only (§7.3)
    "pattern_oracle":  "hunter_free",               // 50 credits/mo — ONE domain-search per new domain to learn the pattern, then construct + verify locally
    "email_verifier":  "reoon_free"                 // ~20/day free, with API (§10). Replaces Apollo/ZeroBounce.
  }
}
```

### 6.2 What Adding a New Segment Requires

1. Insert one row into `segments` with the new config (entity_type, rubric, roles, metadata_fields, sources).
2. Build/assign its **Layer-A discovery connectors**, one at a time — the only genuinely new work. E.g. "startups to acquire" swaps in YC / Product Hunt / funding-news RSS importers (§9).
3. **Nothing else.** The n8n workflow shell, schema, **Layer-B enrichment** (site-scrape → pattern → verify), scoring engine, dedupe, and review layer are reused **verbatim** — because a startup, like a production house, has a website with a team page and an email to verify. Enrichment is company-shaped, not niche-shaped, so it never changes between segments.

### 6.3 Metadata Convention

- `entities.metadata` holds **only** segment-specific attributes, shaped per `config.metadata_fields`.
- `entities.metadata.scoring_inputs` is the standard sub-object the scoring engine reads: keys matching rubric `key`s, values `true`/`false` or a 0–1 fraction (for partial credit, e.g. `genre_fit: 0.5`).
- Scoring inputs are filled by **connector logic** (cheap heuristics computed from data the connector already has in hand — e.g. `genre_fit` from which search query matched, a keyword match, a subscriber-count threshold), by **Layer B enrichment** (richer estimates from the site content it scrapes anyway — `international_ip_experience`, `distribution_relationship`, `right_size`), and refined by **reviewer corrections** when a human overrides an over/under-credited signal. The `reachable_decision_maker` input is the exception — the engine sets it automatically from contact/verification results.
- **Critical distinction: a missing key ≠ a value of `0`.** A key that's simply *absent* from `scoring_inputs` means "never assessed," and the scoring engine (§7.4) excludes it entirely rather than counting it as a confirmed failure. A key present with value `0` means "actively checked, confirmed no evidence" — that *does* count against the score. Connector and enrichment logic must never default an unassessed field to `0`; leave the key out.
- The same distinction applies to **gate inputs** (`geography_signal`, `major_or_oversized_signal`, `has_reachable_presence`) — these are set by the **connector**, not Layer B, because Run A's promote-time gate check (§7.2) happens *before* enrichment ever runs.

---

## 7. Pipeline Stages in Detail

### 7.1 Stage: Discover (source connectors → staging)

**Job:** get candidate companies into `staging_candidates` in a uniform shape: `{segment_id, name, domain, source, source_url, raw}`.

- **Connector-first from day one — no manual seed phase.** Each Layer-A source is an n8n sub-workflow, built and proven **one at a time**, in the priority order set in §8.2/§6.1: **YouTube Data API** (HTTP Request node) first, then **Google News RSS** + the `x_intent_signals` variant (RSS node), then **Wikidata SPARQL** (HTTP Request), then **AICP** (HTTP Request + HTML node, Extract HTML Content operation). A connector isn't "done" until it's been proven end-to-end through dedupe → enrich → score → review (§7.2–§7.5) — only then does the next one get built.
- **Custom (rare):** a small Go/Gin service only for a source needing real scraping infrastructure that proves valuable *and* is inaccessible to n8n nodes (e.g. a JS-heavy directory). Deferred to Phase 3 (§12).
- Every connector execution writes one `source_runs` row **per source** (started/finished, counts, errors) — this feeds the per-source yield KPI (§14).

**Rule:** connectors never write to `entities` directly. Staging is the single doorway, so dedupe and audit logic exist in exactly one place.

### 7.2 Stage: Dedupe & Promote (staging → entities)

n8n step, runs at the start of the weekly batch (**Run A**):

1. Pull `staging_candidates` where `imported = false` for the active segment.
2. Normalize domain (lowercase; strip protocol, `www.`, paths).
3. **Evaluate hard gates** against `segments.config.gates` (§6.1): for each candidate, check its connector-set gate-input signals (`geography_signal`, `major_or_oversized_signal`, `has_reachable_presence`) against each gate's `exclude_when` rule. Any confirmed disqualifying match → this candidate's target status becomes `rejected` with `status_reason` set to the failing gate's `key`. No confirmed match on any gate (including all-unknown) → target status `discovered`, proceeds normally. **This never short-circuits the UPSERT** — a gate-failed candidate still goes through the exact same dedupe logic in step 4, just landing with `status='rejected'` instead of `discovered`; this is what makes the "rejected stays rejected forever" protection (§5.3) also cover hard-gate rejections, so a bad candidate a connector re-surfaces next week is recognized and skipped, not re-evaluated.
4. UPSERT into `entities` per the rules in §5.3, using the status/status_reason determined in step 3. **Implementation note:** because the dedupe indexes are *partial* indexes, this must be raw SQL via the n8n Postgres node's **Execute Query** operation — the node's built-in "insert or update" operation cannot target partial/expression conflict arbiters, and a single `ON CONFLICT` statement cannot target both indexes. Two branches:
   - **Candidates with a domain:**
     `insert into entities (...) values (...) on conflict (segment_id, domain) where domain is not null do update set ...`
     (the `where domain is not null` predicate must be repeated in the statement or Postgres will not infer the partial index).
   - **Candidates without a domain:** first run a pre-insert lookup for an existing entity in the segment with the same `lower(name)` that *has* a domain — if found, merge into that row (this covers the cross-case duplicate no index can catch, §5.1 note); otherwise
     `insert into entities (...) values (...) on conflict (segment_id, lower(name)) where domain is null do update set ...`
   - Merge semantics per §5.3; candidates matching an *already*-`rejected` entity are skipped untouched (this is distinct from step 3's fresh gate rejections, which still get inserted).
5. Mark staging rows `imported = true` with `import_result` (`inserted` / `merged_duplicate` / `skipped_rejected`).

### 7.3 Stage: Enrich & Verify (entities → contacts)

This is **Layer B — shared across every segment.** For each newly promoted entity (status `discovered`):

0. **Resolve a missing domain, if any.** Some Layer-A connectors can't get a domain at discovery time — YouTube's API exposes no website field at all (verified), so its connector can only cheaply regex-extract one from the channel description (§7.1), which often comes up empty. For any entity still domain-less here, the **Brave Search API** (free tier) resolves the company name to a real website — the search-based "automation booster" from step (d) below, promoted from optional to *required* whenever domain is null. If it still can't find one, the entity proceeds with no domain: contact-finding (step 1) will have nothing to scrape and marks `no_contact_found`, and the scoring-input estimation (step 5) will have nothing to read either.
1. **Find the decision-maker** using the segment's `target_contact_roles`, via the free enrichment cascade (ordered by exactness — stop at the first that yields a Reoon-`valid` email). *"Exact" comes from **verification**, not a lookup: we generate candidate addresses from several free signals and let Reoon decide which is a real, deliverable inbox.*
   - **(a) First-party published email — highest confidence:** n8n HTTP Request → HTML node fetches `/team`, `/about`, `/leadership`, `/contact`, `/press`; a Code step extracts `mailto:` links + name/role blocks by DOM proximity, **decoding obfuscation** (Cloudflare `data-cfemail` XOR, "at"/"dot"). A published `mailto:` is effectively self-verified. Reality (verified): tiny shops publish the *specific person's* address only ~15–30% of the time; the rest expose a generic `hello@`/`info@` (still a real reachable inbox).
   - **(b) Name-first construct + verify — THE workhorse, highest exactness:** pin the decision-maker's *name* (from the team page, a press/media kit, a trade-press or X deal post that named them, or a state business-registry officer lookup). **Hunter free (50/mo) is used *only as the pattern oracle*** — one Domain Search per new domain to learn the pattern, cached (GetProspect free is a backup finder). Never bulk-find on Hunter (§10.2). Two branches from there:
     - **Hunter confirms a pattern:** construct the one address it implies and **Reoon-verify** it. High confidence — the pattern came from a real email Hunter already crawled at that domain, not a guess.
     - **Hunter has nothing** (verified: this is Hunter's own documented weak spot for "smaller websites or smaller companies," i.e. exactly our smallest YouTube-first shops): construct the **top-3 statistically common variants** for the known name — `{first}.{last}@`, `{first}@`, `{f}{last}@` (a tunable constant in the enrichment script, same treatment as the connector's admission-filter keywords, §7.1) — and **Reoon-verify all three independently**, landing all three as separate `contacts` rows (same `entity_id`/`full_name`/`role_title`, different `email`) rather than picking one blind. After verification (step 3 below), exactly one is promoted to `is_primary`: best status wins (`valid` > `catch_all` > `invalid`/`unknown`/still-`unverified`), with `{first}.{last}@` as the tiebreak when two rows land on the same status. Non-winning rows stay in the table (never deleted, per §5.3's never-erase-evidence discipline) as a record of what was already tried, so a later re-enrichment pass doesn't re-guess and re-spend Reoon quota on a candidate already confirmed wrong.
   - **(c) Catch-all fallback:** on Google Workspace / M365 / catch-all domains (common for tiny shops) SMTP accepts everything, so Reoon returns `catch_all`/`unknown` and can't confirm a guess. **This is not solved by (b)'s 3-variant hedge** — on a catch-all domain, all 3 variants come back `catch_all` too, since the mail server accepts any address regardless of correctness. There, either corroborate the exact address from a published source, or fall back to the generic inbox / a couple of RocketReach-free lookups for the stubborn tail.
   - **(d) Automation booster (optional):** **Brave Search API** free tier is the only ToS-clean way to *automate* the "find a literal email" dork (`site:domain "@domain"`, `filetype:pdf`, Wayback for dead pages) inside n8n.
   - **(e) Manual, for digital studios:** YouTube "About" business-email reveal and Instagram business "Email" button are real but **CAPTCHA/ToS-gated → manual, never scripted**.
2. **Record the results — the enrichment→database bridge:** the Operator confirms/enters the found contacts into `contacts` via the **Supabase Table Editor** (or, from Phase 2, a small n8n Form/CSV-upload workflow), filling `full_name`, `role_title`, `email`, `linkedin_url`, `source`. Much of step 1 is automated by n8n, but a human confirms the entry before it counts. It is a named step in the Tuesday cadence (§11). **`is_primary` is set two different ways depending on what's ambiguous:** when the ambiguity is *which person* (multiple people found at the company), the Operator marks the best target-role match `is_primary = true` here, at entry time. When the ambiguity is *which email* (the 3-variant case from step 1(b) — same person, several guessed addresses), `is_primary` is deliberately left `false` here and resolved automatically after verification in step 3 — a human doesn't need to guess which pattern is right when Reoon can just confirm it.
3. **Verify (n8n, Run B):** **Reoon**'s API is called (HTTP Request node) for every new/`unverified` contact email: result → `contacts.email_status` (`valid` / `invalid` / `catch_all` / `unknown`) + `email_verified_at` + `verifier`. **Must call Reoon's Power Mode** (verified: Power Mode's documented status set distinguishes `catch_all` from a genuine valid result via a dedicated `is_catch_all` field; Quick Mode's documented status set has no catch-all category at all, so a constructed guess against a catch-all domain could silently read as valid — confirm the exact request parameter against Reoon's current API reference at build time). Reoon's free tier is ~20 verifications/day, so Run B paces verifications across days if a batch exceeds that (§10.2). **Then resolve `is_primary` for any same-person variant rows from step 1(b):** the row with the best status wins (`valid` > `catch_all` > everything else), `{first}.{last}@` breaks ties, and this row alone is promoted to `is_primary = true` — fully automatic, no operator judgment needed since it's a deterministic comparison, not a fit call.
4. **Engine (same Run B)** sets `metadata.scoring_inputs.reachable_decision_maker` from the primary contact (1.0 `valid` / 0.5 `catch_all` / 0 otherwise) and advances entity status → `enriched`.
5. **Estimate the remaining rubric scoring inputs** from the same site content already scraped in step 1 (only when a domain was resolved): `international_ip_experience` (keyword/language scan of `/about`, `/work`, credits for format-adaptation or co-production mentions), `distribution_relationship` (platform/network names mentioned on the site), `right_size` (team-page headcount hints, "About us" copy), `collaboration_openness` (an explicit collaboration/partnership invitation, a collective/partner-led framing, or a co-production track record on the same pages). Write each into `metadata.scoring_inputs` **only when the site actually gave a signal** — per §6.3's null-vs-zero rule, leave the key absent (not `0`) if it's genuinely unassessed, so the scoring engine (§7.4) excludes rather than penalizes it. (`genre_fit` is **not** touched here — it was already set by the connector from the search query that surfaced the candidate, §7.1/§8.2. `revenue_above_cap` and the 3 `review_checklist` items are **never** set by Layer B either — they require a manual/reviewer lookup, §8.3.)

**Why this was designed Apollo-free — and what the 2026-07-22 subscription decision changes:** Apollo's *free* tier was verified to be a *freemium trap* (export-locked, API paywalled) whose ToS prohibits loading its data into our own database — and it under-covers the smallest digital-first shops regardless (its data correlates with LinkedIn/professional footprint). Scraping a company's own public team page is legally clean, free, and higher-coverage for the YouTube-first subtype, so the cascade above stays the backbone. **However: a paid Apollo Basic subscription (decided 2026-07-22, verified: API included, internal-DB use ToS-permitted — §10.2) adds a person-match/enrichment API as a pending upgrade to this cascade** — most likely slotting in as a step between (a) and (b): when the site-scrape finds no named person, ask Apollo for the decision-maker before falling back to pattern-guessing. Exact placement is a design decision to make when Stage 5 is authored; whatever is decided, Apollo-sourced contacts flow through the same Reoon verification and the same `contacts` rows as every other source.

**Explicitly banned implementations** (from the original plan): scraping LinkedIn HTML for names (ToS violation, brittle, ban risk); generating email permutations + port-25 SMTP handshake verification (AWS blocks outbound 25 by default; at volume it gets IPs blacklisted; unreliable against catch-all domains). Also banned: **automating the YouTube "About" email reveal** (CAPTCHA + ToS). Reoon does the verification job legitimately; site-scrape + pattern does the finding.

**ToS discipline (Layer B):** respect `robots.txt`; scrape only public first-party pages; keep scraped data internal (don't republish); verify-before-store. Treat any YouTube-API-derived field as short-lived (their ~30-day retention rule) and move confirmed contacts into our own records rather than warehousing raw API fields.

### 7.4 Stage: Score (config-driven rubric)

One n8n **Code node**, fully generic — it contains **zero segment knowledge**:

```javascript
// Input: entity rows + the segment's config.rubric + config.score_modifiers
// For each entity:
//   known          = rubric criteria where valueAt(criterion.input) IS ASSESSED
//                    (key present — a literal 0 counts as assessed; a MISSING
//                    key means "never checked" and is excluded entirely)
//   base_raw       = Σ over known: criterion.points × clamp01(valueAt(criterion.input))
//   known_points   = Σ over known: criterion.points
//   base_score     = known_points > 0 ? (base_raw / known_points × 100) : 0   // avoid ÷0 if nothing assessed
//   modifier       = Σ over score_modifiers: (criterion.max_penalty ?? criterion.max_bonus) × clamp01(valueAt(criterion.input) ?? 0)
//                    // modifiers default a missing input to 0 (= no adjustment), which is ALREADY
//                    // consistent with "unassessed doesn't count" — no special-casing needed here
//   score          = clamp(base_score + modifier, 0, 100)   // modifiers can't push the score outside [0,100]
//   breakdown      = { [criterion.key]: awarded points, ..., criteria_known: `${known.length}/${rubric.length}` }
// Writes: entities.fit_score, entities.score_breakdown; status → 'scored'
```

- **Only assessed criteria count — in both the earned points and the total-possible denominator.** A criterion nobody ever evaluated is excluded from the calculation entirely, not treated as a confirmed failure; a criterion that *was* checked and came back negative (value `0`) still counts fully against the score. This is a deliberate reversal of the earlier "missing = 0, still divided by the full 100" design — see §6.3 for why, and for the hard requirement that connector/enrichment code leave a key absent rather than defaulting it to `0` when unassessed (getting this backwards silently breaks the whole rule).
- **`criteria_known` is stored in `score_breakdown`** specifically so a high score built on thin evidence is visible to the reviewer rather than hidden — e.g. a 100 based on 2 of 5 assessed criteria reads very differently from a 100 based on 5 of 5.
- **Modifiers are deliberately NOT part of the weighted rubric pool** — they're applied after normalization, then clamped. Folding a −20/+6 straight into the summed pool would either dilute every other criterion's relative weight or let the score drift outside [0,100]; the two-stage calculation keeps the 5 primary criteria's weighting untouched and the modifiers strictly additive.
- `score_breakdown` is stored so any score can be audited and rubrics can be recalibrated against reviewer decisions later.
- **Scope:** each run re-scores **every** entity currently in `enriched`, `scored`, or `ready_for_review` status for the segment — not just new arrivals. This is what makes reviewer corrections to `scoring_inputs` (§7.5) take effect automatically on the next run.
- Routing: `fit_score < score_threshold_review` → stays `scored` (parked, revisitable); otherwise → `ready_for_review`, with `fit_score ≥ score_threshold_priority` flagged review-first.

**Design note:** this replaces the original plan's hardcoded JavaScript rubric (sub-stage 4.1–4.2, "Founder = +40, NY/LA = +20") with (a) a rubric stored as data, and (b) criteria that measure *deal appetite* rather than *contact reachability*.

### 7.5 Stage: Review (human quality gate)

- Reviewer opens the review view (Supabase Table Editor filtered to `status = 'ready_for_review'`, ordered by `fit_score` desc; or a synced Google Sheet if preferred).
- For each candidate: skim `why_fit`, `score_breakdown`, the primary contact → **approve** (`shortlisted`) or **reject** (`rejected` + one-line `status_reason`).
- Reviewer may correct `scoring_inputs` (e.g., researcher over-credited genre fit) — the next scoring run re-computes automatically.
- Target: 15–20 approvals/week. If approvals run short, pull from the parked `scored` pool — concretely: flip the top-scoring parked rows to `ready_for_review` in the review view, or lower `score_threshold_review` in the segment config (which promotes them on the next scoring run) — or increase next week's `batch_size`.
- Rejection reasons are the tuning signal: recurring reasons (e.g., "too big," "wrong genre") become rubric adjustments in config — not code changes.

### 7.6 Stage: Handoff

- Weekly output: the `shortlisted` batch — exported as CSV/Sheet for BD, or read directly from Supabase.
- When BD acts, they (or the operator) flip status to `contacted` / `in_conversation`. Deeper deal tracking happens in BD's own tools; this system just needs enough state to avoid re-pitching the same company.

---

## 8. Segment 1: US Production Houses (Co-Production & Format Licensing)

### 8.1 Segment Definition

| Field | Value |
|---|---|
| Slug | `us-production-houses` |
| Entity type | `production_company` |
| Subtypes in scope | **commercial/branded-content shops**, **digital/YouTube/social studios**, **film/TV/streaming producers** (corporate/service video vendors explicitly out of scope) |
| Geography | United States |
| Size band | ~5–50 people — real credits, but independent enough to want a partner |
| TVF's goal | **Co-production** of content; **format licensing / distribution** of TVF IP |
| Explicitly NOT the goal | Branded-content client work; acting as a US service/production partner. Commercial shops are targeted **as co-pro/format counterparties**, not as clients or vendors (§2.3). |
| Target roles | Founder / Co-Founder; Head of Development / Development Executive; Executive Producer; Head of Acquisitions / Distribution |
| Priority sub-segment | **Digital studios + streaming producers for co-production** — TVF is digital-first; its catalog (comedy, slice-of-life, young-adult, workplace) maps most directly there. Work these first. |

### 8.2 Discovery Sources (Layer A — all free, adversarially verified §10)

Built **one at a time**, in this order — each connector proven end-to-end through the whole pipeline (dedupe → enrich → score → review) before the next is started (§7.1/§12). There is no manual seed; the first connector's real output *is* the bootstrap batch.

1. **[BUILD FIRST] YouTube Data API v3** — *the standout free find, and the bullseye for the priority sub-segment.* `search.list` (type=channel) + `channels.list` discovers digital/YouTube/social studios via the segment's config-driven `youtube_discovery_queries` (§6.1 — tune by editing config, not the workflow); 10,000 units/day free forever, fully automatable via an n8n HTTP node + API key. Filters creators-vs-studios by title keywords ("studio/media/productions"), a subscriber floor, and an email-in-description. **The API exposes no website/external-link field at all** (verified live) — the connector cheaply regex-extracts a domain from the channel description where present, otherwise leaves it null for Layer B's search-based fallback (§7.3 step 0). The connector also sets `genre_fit` (from the matched query's `genre_hint`) and the four gate-input signals (`geography_signal` from the channel's `country` field, `major_or_oversized_signal` from a subscriber-outlier/keyword check, `has_reachable_presence` — trivially true for any channel, and `activity_signal` — a best-effort read from upload recency) that Run A's promote-time hard gates read (§6.1/§7.2). The other 5 rubric criteria are *not* set here — `international_ip_experience`, `distribution_relationship`, `right_size`, and `collaboration_openness` are estimated later by Layer B from real site content (§7.3 step 5); `reachable_decision_maker` is auto-set after verification. The 3 `review_checklist` items (§6.1) are never connector- or Layer-B-set at all — they're confirmed by the human reviewer at S7.5.
2. **[BUILD SECOND] Google News RSS (keyword + `site:` trade press)** — *the signal feed.* Free RSS that catches "US shop adapts [foreign] format" / "co-production" announcements — including from paywalled trades (`site:c21media.net OR site:realscreen.com OR site:deadline.com`). The named company → straight into staging with `international_ip_experience = true`. Skews to majors, so precision lives in query craft; it's a supplement, not the whole pipeline.
   - **X/Twitter intent posts** (`x_intent_signals`) ride the *same* Google News RSS mechanism, scoped `site:x.com` with founder-collab phrases ("seeking a studio partner", "looking to co-produce", "open to collaboration"). **Verified live** (real 2026 posts returned). This is the *only* free path — X's API is paid-only since Feb 2026 and Nitter is dead. Caveats are real: coverage is **partial + lagged** (Google indexes a slice of X slowly) and **noisy** (profile/search pages + off-topic "co-produce" news mixed in → ~half needs a filter step). A supplementary trickle, human-reviewed, never a primary net.
3. **[BUILD THIRD] Wikidata SPARQL** — *free structured seed for film/TV/streaming producers.* Returns name + official website (P856) + industry, CC0, no key. Only lists *notable* entities, so it's a one-time seed (a few hundred US rows, many mid/large), not a renewable weekly stream — but it's clean name+domain data.
4. **[BUILD FOURTH] AICP member directory (scrape)** — *best niche match for commercial/branded-content shops.* Static public HTML, ~370 US shops, **names only** (each needs domain + contact enrichment downstream). ToS is "reference-only": keep internal, no resale, treat with care.

**Dropped after verification** (do *not* build these): **Apollo free** (freemium trap + ToS prohibits export-to-DB; weak niche coverage anyway → replaced by Layer-B site-scraping); **X/Twitter API** (paid-only since Feb 2026, $0.005/read, no free tier → reach X only via the free `x_intent_signals` Google-RSS path above), and **Nitter** (dead) / **RSS.app free** (2-feed cap) / **Bright Data & Apify X scrapers** (paid); **Google Places / TMDB / Vimeo APIs** (ToS prohibits storing results); **paid-search APIs, Bing (retired), Social Blade** (not actually free at volume); **native Deadline/Variety/THR RSS** (bot-blocked → reach via Google News `site:` instead).

**Deferred paid upgrades** (when budget opens): **IMDbPro** (~$150/yr — highest-accuracy company database for this niche, the designated relief valve if free discovery mines out); **Clay** (managed waterfall enrichment); **LinkedIn Sales Navigator**.

### 8.3 Fit Rubric (6 primary criteria sum to 115; thresholds: review ≥ 40, priority ≥ 75)

| # | Criterion | Points | Evidence to look for |
|---|---|---|---|
| 1 | **Has adapted or co-produced international IP/formats** | **30** | Trade-press deal coverage; adapted foreign show in credits; co-pro credit with a non-US company. *Strongest appetite signal.* |
| 2 | **Makes content in TVF's lanes** (comedy, slice-of-life, young-adult, workplace) | **25** | Credits, website reel, YouTube channel. Full points if core focus; half if occasional. |
| 3 | **Live streamer/network/platform output relationship** | **20** | First-look deals, recent commissions, consistent platform sales — a co-pro has to land somewhere. |
| 4 | **Right size** (~2–20 core people, most under 10, credited, independent) | **15** | Headcount hints, credit history, not a subsidiary of a major. *Tightened from an earlier ~5–50 draft to match the operator's refined definition of "small."* |
| 5 | **Reachable decision-maker** (auto-set by engine) | **10** | Target-role contact with `valid` email = full; `catch_all` = half. |
| 6 | **Demonstrated openness to collaboration** | **15** | Explicit collaboration/partnership invitation on their own site; a collective/partner-led operating model; a co-production track record (distinct from, though overlapping with, #1). Half credit for a weaker/implicit signal. *Added later — dilutes the pool from 100 to 115; the engine's normalization (§7.4) handles a non-100 total automatically.* |

**Score modifiers** (applied *after* the base 0–100 score above, then clamped to [0,100] — see §7.4 for the formula; not part of the weighted-115 pool):

| Modifier | Type | Max | Evidence to look for |
|---|---|---|---|
| **Client-work dominance** | Penalty | **−20** | A `/work` page dominated by brand-client logos = work-for-hire, not an IP-owning studio. Soft subtractor, not a hard reject — a strong candidate can still surface for review, just scored lower. |
| **India / diaspora affinity** | Bonus | **+6** | Existing India/Asia ties, diaspora-crossover audience, or prior work with an Indian company. Rare — most good leads legitimately score 0 here, which is not held against them. |
| **Revenue above cap** | Penalty | **−10** | A third-party revenue estimate (LeadIQ, Buzzfile, RocketReach) above ~$1M — "borderline" vs. "clean fit" (at/under ~$1M or microbudget-scale). **Not yet connector-automated**: those tools' free-tier usability for this pipeline hasn't been adversarially verified the way every other tool in §10 has been, so this input is set by the reviewer, not a connector, until that verification happens. |

**Hard gates** (auto-enforced at Run A's promote step, §7.2 — fire only on *confirmed* disqualifying evidence, never on missing data):

| Gate | Excludes when | Evidence to look for |
|---|---|---|
| **US geography** | Confirmed non-US | Non-US country field, address, phone, or currency; a foreign ccTLD with no named US office. |
| **Not a major or oversized** | Confirmed match | Name/keyword match against known majors, or a confirmed size signal well beyond ~50 people. |
| **Usable first-party presence** | No reachable presence at all | Needs a website, owned channel, or social presence — a YouTube channel alone already satisfies this for connector-sourced candidates. |
| **Is active** | Confirmed dormant/defunct | No upload/site activity in 12+ months, or an explicit closed/discontinued notice. |

**Review checklist** (human-judgment-only — free automated sources cannot verify these, so they are never auto-enforced gates; the reviewer confirms each at S7.5):

| Checklist item | Why it can't be automated |
|---|---|
| **Is actually an IP-owning production company** | Indistinguishable from a service vendor, agency, institution, or unrelated same-name LLC using only free connector data. |
| **Subtype genuinely in scope** | A keyword match that got a candidate into staging isn't proof its real content is commercial/branded, digital/social, or film/TV/streaming rather than corporate/service video. |
| **Independent ownership** | No studio/network parent, no PE ownership, no large-scale VC backing on record — requires a Crunchbase/PitchBook/press lookup no free connector can do. A single small convertible note (e.g. ~$500K) from non-marquee sources is a documented exception, not a disqualifier. |

### 8.4 Bootstrap Plan (Discovery-Connector-First)

There is no manual seed phase — the first real discovery connector's output **is** the bootstrap batch, built and proven one at a time (§8.2):

1. Build the **YouTube Data API connector** first — highest niche fit for the priority digital-studio sub-segment, and the easiest of the four to automate cleanly.
2. Run it and prove it **end-to-end through the full pipeline**: candidates land in `staging_candidates` → promote/dedupe (§7.2) → Layer-B enrichment finds a contact (§7.3) → **Reoon** verifies → score (§7.4) → a human reviews and approves the first **15–20 shortlisted leads**.
3. Only once that loop is proven does the next connector get built — **Google News RSS** (+ `x_intent_signals`), then **Wikidata**, then **AICP** — each added incrementally, each individually proven before the next.
4. **This still validates the rubric and gates before scaling discovery volume** — same principle as before, just with the first automated connector's real output standing in for a hand-picked batch. If shortlist quality is weak after YouTube's first real batch, fix the rubric/gates before adding more connectors — automating a bad filter across four sources just produces bad leads faster.

---

## 9. Future Segment Sketch: Startup Acquisition Targets

Not being built now — documented to prove the architecture generalizes, and as the template for onboarding it later. It is the concrete payoff of the **two-layer** design (§3, principle 2): only **Layer A (discovery) + the rubric** change; **Layer B (site-scrape → email-pattern → Reoon verify), the schema, the n8n shell, scoring, dedupe, and review are reused unchanged** — a startup has a website, a team page, and an email to verify exactly like a production house does.

| Config element | Value (sketch) |
|---|---|
| Slug / entity type | `startup-acquisition-targets` / `startup` |
| Sources (Layer A — the only new build) | Y Combinator directory, Product Hunt, GitHub, funding-news RSS (TechCrunch, Inc42/YourStory for India-adjacent). **Vet each for free-tier + ToS exactly as §10 did** — expect **Crunchbase and AngelList/Wellfound to fail that vetting** (limited free tier + export-restricting ToS, the same profile that got Apollo dropped), so lead with the RSS/directory sources that survive. **LinkedIn is *not* a connector** — manual reviewer lookup only, never automated (the ban in §2.3/§13.1 holds for every segment). |
| Enrichment (Layer B — reused verbatim) | Same site-scrape → email-pattern → Hunter-oracle → Reoon-verify cascade. No new work. |
| Target roles | Founder, Co-Founder, CEO |
| Rubric (sketch) | Strategic/tech fit with TVF (30) · revenue/ARR band (20) · team size & quality (20) · growth trajectory (15) · founder openness signals — e.g. stagnant funding, pivot noise (15) |
| Metadata fields | `funding_total`, `last_round`, `arr_estimate`, `headcount`, `stack`, `product_category`, `why_fit`, `scoring_inputs` |
| What must be built | Config row + source connectors only. Schema, n8n workflow, scoring engine, review layer: **unchanged.** |

Onboarding effort estimate: a config row + a weekend of connector work — that is the payoff of the universal design.

---

## 10. Tooling, Free-Tier Limits & Costs

### 10.1 Stack Summary

| Tool | Role | Tier | Cost | Key limits (verify current — these change) |
|---|---|---|---|---|
| **Supabase** | System of record (PostgreSQL) | Free | $0 | ~500 MB DB; pauses after ~1 wk inactivity (weekly run is our keep-alive); 2 free projects |
| **n8n Community Edition** | Orchestration | Self-hosted | $0 (software) | Unlimited workflows/executions; register instance for Folders + Debug features |
| **n8n hosting** | Runtime | Office machine / Oracle Always-Free / EC2 | $0 – ~$15/mo | EC2: new accounts get a ~6-month credit-based free plan (post-July-2025 AWS rules), then paid |
| **YouTube Data API v3** | Discovery — digital studios (Layer A) | Free | $0 | 10,000 units/day (search=100 units, channels=1); no card. Treat fields as short-lived (~30-day ToS retention) |
| **Wikidata SPARQL** | Discovery — film/TV seed (Layer A) | Free | $0 | Open, CC0, no key; needs a descriptive User-Agent; notable-only coverage |
| **Google News RSS** | Discovery — deal signals (Layer A) | Free | $0 | Unofficial endpoint, no key; polite hourly polling; precision = query craft |
| **AICP directory (scrape)** | Discovery — commercial shops (Layer A) | Free | $0 | Static HTML, names-only; "reference-only" ToS → internal use |
| **First-party site scraping** | Enrichment — contacts (Layer B) | Free (self-hosted n8n) | $0 | Uncapped; respect robots.txt; occasional layout breakage |
| **Hunter.io** | Enrichment — pattern oracle (Layer B) | Free | $0 | 50 credits/mo, burned per email *returned* → use for patterns only, not bulk finding |
| **Reoon** | Email verification (Layer B) | Free | $0 | ~20 verifications/day (no rollover), *with* API — pace across days |
| **Google Sheets** (optional) | Review surface alternative | Free | $0 | — |
| Human time | Discovery check-in + enrichment confirm + review | — | ~2.5–3 h/wk | The real "cost" of the free stack — connector-automated, not hand-researched |

**Total cash cost at launch: $0** (assuming office-machine or Oracle hosting), with ~2.5–3 hours/week of human confirm/review time. That human time *is* the budget trade-off and should be tracked honestly (§14).

### 10.2 Free-Tier Caveats & Pacing (important)

Each free source was adversarially verified (see the research sweep behind §8/§10). The ceilings that actually constrain the weekly design:

- **YouTube Data API:** 10,000 units/day, `search.list` costs **100 units** (so ~100 searches/day) while `channels.list` costs **1 unit** for up to 50 channels — so *discovery searches* are the scarce resource, enrichment reads are effectively free. Ample for our volume. Keep stored API fields short-lived (their ToS retention/database clauses); move confirmed contacts into our own `contacts` rows rather than warehousing raw API data.
- **Reoon (verification):** the free tier is **~20/day, not ~600/month** — it resets daily and does **not** roll over. At ~3–7 verifications/day we have headroom, but a burst of 50 in one Run B will hit the daily wall. **Run B must pace/queue verifications across days** if a batch exceeds ~20. The §7.3 step 1(b) 3-variant hedge (used only when Hunter has no pattern for a domain) spends up to 3 verifications per contact instead of 1 — worst case (every contact that week needs the hedge) is still only ~45–60/week for a 15–20-lead batch, comfortably inside the ~140/week the daily cap allows across 7 days, so this doesn't change the pacing design, just worth knowing it's not free of cost.
- **Hunter (pattern oracle):** 50 credits/month, and credits burn **per email returned**, not per search — one Domain Search on a well-indexed shop can spend several credits at once. So Hunter is used **only** to learn a domain's pattern once, then cached; never for bulk finding, or the 50 credits vanish in days.
- **AICP / market lists:** finite corpora, not renewable streams — they *seed* the pipeline once. "Reference-only" ToS on AICP → internal use, no resale.
- **Google News RSS:** free but unofficial/undocumented; poll politely (hourly), dedupe by `<link>`, and never make it a *sole* load-bearing source (Google can change it without notice).
- **Apollo — free tier dropped; paid Basic subscription decided 2026-07-22 (integration design pending).** The *free* tier remains out of the stack (freemium trap: ~100 email credits/mo, export-locked, no API, ToS bars DB loading). But the paid **Basic** tier was pre-purchase-verified against Apollo's own pages (2026-07-22) and changes the calculus entirely: **API access IS included on Basic** ($49/seat/mo annual, $65 monthly; unified credit pool — 30,000 credits/seat/yr annual or 2,500/mo monthly; email unlock = 1 credit, phone = 8, enrichment 1–9), and the paid ToS **expressly permits** loading Apollo-derived data into our own internal database ("perpetual… license to use the PGI for internal business purposes," retained post-termination; resale/redistribution prohibited — internal-pipeline use at our volume is squarely permitted). Exact per-endpoint rate limits are not published — verify in-app (Settings → API Keys → Usage) during the trial/first month. Where it plugs in (Layer-B person-match enrichment and/or a 5th Layer-A connector for traditional production houses) is a pending design decision — it slots into the existing staging→gates→dedupe→score pipeline like any other source, never around it.

### 10.3 Upgrade Triggers (when to start paying)

| Trigger | Upgrade |
|---|---|
| Free discovery (YouTube/Wikidata/AICP/News) mines out; discovery becomes the bottleneck | **IMDbPro** (~$150/yr) — highest-accuracy company database for this niche |
| Manual enrichment/confirmation >2 h/wk sustained | **Clay** — managed waterfall enrichment replaces the Layer-B site-scrape+pattern step |
| Reoon's ~20/day cap throttles the weekly batch (volume grows past ~100/wk) | **First option: self-host an open-source verifier** — AfterShip/email-verifier (MIT) or Reacher (AGPL, fine for internal unmodified use) both detect catch-all; needs a cheap VPS with open outbound port 25 + clean IP (a few $/mo — won't work from an office/home IP, port 25 is blocked there). Else Reoon paid, or a pay-as-you-go verifier (thousands of verifies for tens of dollars) |
| Need reliable people-search beyond first-party sites | **LinkedIn Sales Navigator** (targeting) — still no scraping |
| A high-value source needs real scraping n8n can't do | Phase 3: Go/Gin connector service |

---

## 11. Weekly Operating Cadence

Designed around the 15–20 leads/week commitment. Roles: **Operator** (runs the system — initially the builder) and **Reviewer** (BD-side quality gate — may be the same person at first, but the *roles* stay distinct).

| Day | Activity | Owner | Time |
|---|---|---|---|
| **Mon** | Discovery check-in: confirm each active connector ran cleanly and staging ≥ 2× weekly target (§8.2); if a source is thin, tune its filter or prioritize building the next connector. | Operator | ~30–45 min |
| **Tue** | In strict order: (1) n8n **Run A** (scheduled): run discovery connectors + promote/dedupe staging → entities; (2) n8n site-scrape/pattern enrichment, then Operator confirms/records the primary contact for ~30 companies (§7.3 step 2); (3) n8n **Run B** (triggered after entry): Reoon-verify emails → set `reachable_decision_maker` → score → route to review. | n8n + Operator | ~1 h |
| **Wed** | Review session: approve/reject `ready_for_review` queue down to 15–20 shortlisted. Log rejection reasons. | Reviewer | ~30–45 min |
| **Thu** | Handoff: shortlist exported/shared with BD. Status flips as BD picks accounts up. | Operator | ~10 min |
| **Fri** | Retro (15 min): shortlist hit rate, rejection-reason patterns, source yield (`source_runs`). Rubric/config tweaks. | Both | ~15 min |

Weekly total: **~2.5–3 hours of human time** producing 15–20 curated, verified, ranked leads — down from the ~3–4h manual-seed estimate now that discovery is connector-automated rather than hand-researched.

---

## 12. Phased Roadmap

### Phase 0 — Foundation (days 1–2)
- [ ] Create Supabase project; run schema DDL (§5.1).
- [ ] Insert Segment 1 row with full config (§6.1 / §8). **Note:** §6.1 is shown as JSONC (with `//` comments) for readability — strip all comments before inserting, or it will fail `jsonb` parsing.
- [ ] Stand up n8n via Docker (localhost-bound editor; register instance).
- [ ] Get keys **when their stage arrives, not necessarily day 1**: **Reoon** (verification) + **Hunter** (pattern oracle) are needed for the Layer-B enrichment stage (Phase 1); the **YouTube Data API** key is only needed when the discovery connector is built (post-v1, Phase 2). All free, no card. *(Apollo and ZeroBounce are no longer used.)*
- [ ] Create the review view (saved Supabase Table Editor view or synced Sheet).

**Exit criteria:** schema live; segment config inserted; n8n reachable; accounts created.

### Phase 1 — First discovery connector, first leads (week 1)
- [ ] Build the **YouTube Data API connector** (§8.2 #1): n8n HTTP Request workflow, `search.list` + `channels.list`, filter creators-vs-studios, write to `staging_candidates`.
- [ ] Run it → promote → enrich (site-scrape + email-pattern, Layer B) → Reoon-verify → score (even manually in SQL/Sheet if n8n scoring isn't fully wired yet).
- [ ] Review session → **first 15–20 shortlisted leads delivered**, sourced entirely by the connector.
- [ ] Retro: rubric/modifier calibration against reviewer decisions — tune before building the next connector.

**Exit criteria:** 15–20 shortlisted leads handed to BD, sourced by the YouTube connector; rubric validated or adjusted. *Prove one connector end-to-end before adding the next — if this phase's shortlist quality is weak, fix the rubric/gates, not add more sources.*

### Phase 2 — Add the remaining discovery connectors (weeks 2–4)
- [ ] n8n weekly workflows, split around the manual enrichment pause (§4.1): **Run A** (Schedule Trigger → load config → run active connectors → promote/dedupe staging) and **Run B** (Operator-triggered after contact entry → verifier → `reachable_decision_maker` → generic scoring Code node → status routing) → (optional) review-batch notification.
- [ ] n8n verifier integration (HTTP Request node, inside Run B).
- [ ] Contact-entry helper: n8n Form workflow so the Operator's enrichment results land in `contacts` without hand-editing rows (§7.3 step 2).
- [ ] Build the remaining connectors **one at a time, each proven before the next** (§8.2 build order): **Google News RSS** (+ `x_intent_signals`), then **Wikidata SPARQL**, then **AICP directory scrape**.
- [ ] `source_runs` logging wired into every connector.

**Exit criteria:** weekly batch runs on schedule, fed by all four discovery connectors; the only mandatory manual steps are discovery-filter review, primary-contact confirmation, and lead review.

### Phase 3 — Custom connectors, only if earned (month 2+)
- [ ] Evaluate: which valuable source is inaccessible to n8n nodes? (Only then:) small **Go/Gin** connector service — goroutine-concurrent fetching of *permitted* public sources, writing into `staging_candidates` via Supabase API. This is the surviving, right-sized descendant of the original plan's Go backend.
- [ ] Paid upgrades per triggers in §10.3 (IMDbPro first — highest leverage for this segment).

**Exit criteria:** discovery keeps staging ≥ 2× weekly target without manual mining time growing.

### Phase 4 — Second segment: prove universality (when TVF says go)
- [ ] Insert `startup-acquisition-targets` segment row (config per §9).
- [ ] Build its connectors (Crunchbase/YC/Product Hunt importers).
- [ ] Run both segments through the **same** engine on the same cadence.

**Exit criteria:** two live segments; core engine untouched by the second onboarding. If anything core *had* to change, fix the abstraction before segment 3.

---

## 13. Compliance & Risk Register

### 13.1 Compliance Positions (decided)

| Area | Position |
|---|---|
| **LinkedIn** | Manual browsing/search only. **No scraping, no automation against LinkedIn, ever** — ToS violation, account/IP bans, and legally gray. This reverses the original plan's sub-stage 2.3. |
| **SMTP verification** | **Never** DIY port-25 handshake verification (original sub-stage 2.5): AWS blocks outbound 25 by default; at volume it blacklists our IPs; catch-all domains defeat it anyway. Commercial verifier APIs only. |
| **Third-party API/scrape ToS** | Use only APIs as intended (YouTube key, Reoon, Hunter) and scrape only public first-party pages; respect robots.txt; keep data internal; honor YouTube's ~30-day retention on API-derived fields. **Apollo: free-tier automation stays banned (its free ToS bars export-to-DB); the paid Basic plan's ToS expressly permits internal-database use** (verified 2026-07-22, §10.2) — internal use only, no resale/redistribution. AICP directory is reference-only → internal, no resale. |
| **Public directories** | Film-office and market participant lists are published for exactly this kind of business-development use; respect robots.txt and rate limits if any parsing is automated. |
| **CAN-SPAM / GDPR / DPDP** | Outreach is out of scope, but the **list is built outreach-ready**: every row keeps `source`/`source_url` (provenance), business emails at business domains only, and deletion on request is trivial (single database). Contacts are overwhelmingly US business contacts (CAN-SPAM regime — which governs the *sending* TVF will eventually do); any EU/UK person data that enters would carry GDPR obligations on *storage*, so the segment stays US-only by config. |
| **Personal data minimization** | We store: name, business role, business email, LinkedIn URL. Nothing sensitive, nothing personal beyond professional identity. |

### 13.2 Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Reoon's ~20/day verification cap throttles a big batch | Medium | Low | Run B paces verifications across days (§10.2); upgrade trigger defined (§10.3) |
| 2 | First-party sites hide their team / no contact found | Medium | Medium | Email-pattern construction + Hunter pattern-oracle, with a 3-variant guess-and-verify hedge when Hunter has no data (§7.3 step 1(b)); else mark `no_contact_found` and still score the company |
| 3 | Free sources mine out after ~2–3 months | Medium | Medium | Source-yield tracking in `source_runs` flags decay early; IMDbPro is the designated relief valve |
| 4 | Rubric miscalibrated → weak shortlists | Medium | High | Phase 1 validates before automation; rejection reasons feed weekly rubric tuning; `score_breakdown` enables retroactive audit |
| 5 | Single-operator dependency (bus factor 1) | High | Medium | This document + config-as-data + n8n visual workflows keep the system legible; cadence doc (§11) is the runbook |
| 6 | Supabase free project pauses from inactivity | Low | Low | Weekly run is inherent keep-alive |
| 7 | n8n instance dies silently → missed weekly batch | Medium | Low | Cadence includes a human Tuesday step, so a dead run is noticed same-day; n8n error workflow → email/Discord notification in Phase 2 |
| 8 | Scope creep back toward outbound automation | Medium | Medium | §2.3 non-goals; any outreach system is a separate project with its own compliance review |
| 9 | Duplicate outreach embarrassment (BD pitches same company twice) | Low | High | Per-segment dedupe + `contacted`/`in_conversation` statuses; rejected/contacted rows never deleted |
| 10 | Free-tier terms/limits change under us | Medium | Low | §10 limits flagged "verify current"; nothing in the architecture is coupled to a specific vendor tier |

---

## 14. KPIs & Success Metrics

Reviewed at the Friday retro; tracked in a simple dashboard query over Supabase (or a Sheet).

| KPI | Definition | Target |
|---|---|---|
| **Shortlisted leads/week** | Entities newly `shortlisted` in the week | **15–20** (the headline commitment) |
| **Review approval rate** | shortlisted ÷ ready_for_review | ≥ 60% — below that, the rubric or sources are miscalibrated |
| **Contact find rate** | Entities with a target-role primary contact ÷ entities enriched | ≥ 70% |
| **Email validity rate** | `valid` ÷ verified | ≥ 80% (`catch_all` tracked separately) |
| **Priority-lead share** | fit_score ≥ 75 among shortlisted | ≥ 25% — proxy for source quality |
| **Source yield** | New (post-dedupe) candidates per source per week (`source_runs`) | Trend per source; retire sources that decay |
| **Operator time/week** | Honest log of hours | ≤ 3 h (connector-first estimate, §11); sustained breach = automation/upgrade trigger (§10.3) |
| **Downstream signal** (lagging, once BD engages) | Reply/meeting rate on shortlisted leads, reported back by BD monthly | Informational — the ultimate rubric-tuning signal |

**The single metric that matters most in month 1: review approval rate.** It measures whether the engine finds companies a human agrees are real prospects. Optimize that before optimizing volume or automation.

---

## 15. Open Questions

| # | Question | Owner | Needed by |
|---|---|---|---|
| 1 | Who is the named **Reviewer** (BD-side quality gate)? Same person as Operator initially? | TVF | Phase 1 |
| 2 | Where does n8n live — office machine, Oracle free VM, or EC2? (Decides the only potential cash cost.) | TVF | Phase 0 |
| 3 | Review surface: Supabase Table Editor (zero extra work) or synced Google Sheet (friendlier for BD)? | Reviewer | Phase 1 |
| 4 | What does BD use for deal tracking, so `in_conversation` handoff has a defined destination? | TVF BD | Phase 1–2 |
| 5 | Budget approval threshold for IMDbPro (~$150/yr) if discovery quality demands it early? | TVF | Phase 2–3 |
| 6 | Priority order for future segments after production houses (startups-to-acquire confirmed as #2 — anything else queued?) | TVF | Phase 4 |
| 7 | Should shortlisted leads sync automatically to a BD tool (Sheet/CRM webhook) or is weekly CSV export fine? | TVF BD | Phase 2 |

---

## Appendix A — Disposition of the Original Plan (`LeadGenerator.txt`)

Stage-by-stage account of what was **kept, generalized, replaced, or dropped**, and why.

| Original sub-stage | Content | Disposition |
|---|---|---|
| 2.1 | n8n Community via Docker on EC2, port 5678, webhook ingest | **Kept (modified):** n8n via Docker survives as the orchestrator. Hosting broadened beyond EC2 (§4.3); editor not publicly exposed; primary trigger is a weekly schedule rather than a webhook (webhook ingest optional for future connectors). |
| 2.2 | Go/Gin backend, goroutines for concurrent search-engine scraping | **Deferred to Phase 3, repurposed:** no mass scraping backend at launch; a small Go/Gin *connector service* may appear later for permitted sources only. At 20 leads/week, concurrency infrastructure is premature. |
| 2.3 | Parse LinkedIn directory HTML titles for names/titles | **Dropped — banned.** LinkedIn ToS violation, IP/account bans, brittle. Replaced by Layer-B first-party site-scraping of the company's own `/team`/`/about` pages (§7.3). |
| 2.4 | Algorithmic email permutation generation | **Kept (reframed).** Email-pattern construction survives as a legitimate Layer-B step — learn a domain's pattern once (Hunter free oracle), then construct + Reoon-verify. This is the disciplined version of the original idea. |
| 2.5 | DIY MX lookup + port-25 SMTP handshake verification | **Dropped — banned.** AWS blocks outbound 25; blacklisting risk; defeated by catch-all domains. Replaced by commercial verifier API (§7.3). |
| 3.1 | Supabase PostgreSQL; `companies`/`leads` tables; JSONB metadata | **Kept, generalized:** Supabase survives as system of record. Tables generalized to segment-agnostic `entities`/`contacts` with `segments.config` driving shape (§5). JSONB metadata instinct fully retained. |
| 3.2 | UPSERT deduplication on email | **Kept, improved:** UPSERT dedupe survives, keyed on `(segment_id, domain)` for companies (email dedupe on contacts), with merge semantics and never-delete-rejected (§5.3). |
| 3.3 | n8n Switch-node industry tagging (e.g. `production_house_under_10`) | **Generalized:** tagging becomes segment `metadata` fields + `subtype`, defined in config rather than Switch-node branches (§6.3). |
| 3.4 | Register n8n instance; Folders; Debug in editor | **Kept as-is** (§4.3). |
| 3.5 | `lead_status` state machine (`discovered` → `enriched_and_ready`) | **Kept, expanded:** full lifecycle with human-review states (§5.2) — the review gate is the biggest addition. |
| 4.1 | Hardcoded scoring rubric ("Founder = +40, NY/LA = +20") | **Replaced:** rubric moves from code to `segments.config` data (§6.1); criteria redesigned to measure deal appetite, not reachability (§8.3). |
| 4.2 | n8n JS Code node applies matrix, appends score | **Kept, made generic:** one config-driven Code node with zero segment knowledge (§7.4); adds stored `score_breakdown`. |
| 4.3 | If-node routes leads scoring above 80 points → `priority_outbound` queue | **Replaced:** thresholds move into config (`score_threshold_review` / `score_threshold_priority`); routing goes to *human review*, not an outbound queue (§7.4–7.5). |
| 4.4 | Tracking pixel + redirect endpoints; intent-based score bumps | **Out of scope** (non-goal §2.3): belongs to a future outreach project, with its own compliance review. |
| 4.5 | Discord/Slack VIP alerting on perfect scores/high intent | **Out of scope** for lead gen; the only surviving notification is an optional "weekly batch ready for review" ping (Phase 2). |

**Summary:** the original plan's *infrastructure instincts* (n8n, Supabase, JSONB, UPSERT, state machine, config-adjacent scoring) survive; its *acquisition tactics* (LinkedIn scraping, email permutation, DIY SMTP) are replaced with legitimate free-tier equivalents; and its *volume-outbound machinery* (queues, pixels, alerts) is cut as out-of-scope for a 15–20/week curated, account-based motion.

---

## Appendix B — Reference Source Directory

Quick links, grouped by the two-layer model (URLs verified at time of writing; expect drift). Endpoints/quotas were confirmed in the §10 research sweep.

**LAYER A — Discovery connectors (free, built one at a time — build order noted):**
- **[1st] YouTube Data API v3** — developers.google.com/youtube/v3 · endpoints `search.list` + `channels.list` · 10k units/day · needs a Google Cloud API key. *Priority: digital studios.*
- **[2nd] Google News RSS** — news.google.com/rss/search?q=… · keyword + `site:c21media.net OR site:realscreen.com OR site:deadline.com` for deal signals (also the `x_intent_signals` `site:x.com` variant) · RSS node, dedupe by `<link>`.
- **[3rd] Wikidata SPARQL** — query.wikidata.org/sparql · SELECT film-production companies (Q1762059) in the US (P17=Q30) with website (P856) · descriptive User-Agent required.
- **[4th] AICP member directory** — aicp.com/membership-information/member-directory (East & West chapters) · static HTML scrape, names-only, reference-only ToS.

**LAYER B — Enrichment & verification (free, shared across segments):**
- **First-party site scraping** — the entity's own `/team` `/about` `/leadership` `/contact` pages via n8n HTTP + HTML nodes. The workhorse.
- **Hunter.io** — hunter.io (free 50 credits/mo) · **pattern oracle only** · native n8n node.
- **Reoon Email Verifier** — emailverifier.reoon.com (free ~20/day, with API) · the verification gate.

**Paid, deferred (upgrade triggers §10.3):**
- IMDbPro — pro.imdb.com (~$150/yr) · highest-accuracy niche discovery
- Clay — clay.com · managed waterfall enrichment
- LinkedIn Sales Navigator — linkedin.com/sales · targeting (no scraping)

**Dropped after verification (do not use):** Apollo (freemium trap + ToS), Google Places/TMDB/Vimeo (no-store ToS), Bing Web Search (retired), Social Blade / paid-search APIs (not free at volume).

---

*End of implementation plan. Next step per Phase 0: create the Supabase project and run the schema in §5.1.*
