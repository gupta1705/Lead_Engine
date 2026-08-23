-- 03_SEGMENT_US_PRODUCTION_HOUSES.SQL
-- Registers Segment 1: US Production Houses (Co-Production & Format Licensing).
-- Run once in the Supabase SQL editor, after 01_schema.sql.
-- The config below is byte-for-byte the same content as
-- config/segment.us-production-houses.json (comment-free JSON, as jsonb requires).
--
-- v2 (2026-07): added collaboration_openness rubric criterion (+15, pool now
-- sums to 115), revenue_above_cap modifier (-10, NOT YET connector-automated
-- - reviewer-set for now), is_active gate, and a review_checklist array for
-- the 3 signals free connectors cannot verify (production-company judgment,
-- subtype judgment, independent-ownership judgment).
--
-- v3 (2026-08-20): owner-run rubric weight review (P1/P2 authoring session).
-- genre_fit 25->15, right_size 15->20, revenue_above_cap max_penalty -10->-20.
-- Pool now sums to 110 (was 115). All other weights, modifiers, gates, and
-- thresholds (review 40 / priority 75) reviewed and kept as-is. The live
-- Supabase row still has the v2 numbers as of this commit -- run
-- 03b_sync_segment_config_v3.sql to bring it current (see BUILD_PLAN.md P0).

insert into segments (slug, name, entity_type, config)
values (
  'us-production-houses',
  'US Production Houses — Co-Pro & Format',
  'production_company',
  '{
  "entity_type": "production_company",
  "weekly_target": 20,
  "batch_size": 30,
  "score_threshold_review": 25,
  "score_threshold_priority": 60,
  "target_contact_roles": [
    "Founder", "Co-Founder",
    "Head of Development", "Development Executive",
    "Executive Producer",
    "Head of Acquisitions", "Head of Distribution"
  ],
  "rubric": [
    {
      "key": "international_ip_experience",
      "label": "Has adapted or co-produced international IP/formats",
      "points": 30,
      "input": "metadata.scoring_inputs.international_ip_experience",
      "guidance": "Trade-press coverage of a format deal, an adapted foreign show in credits, or co-pro credit with a non-US company. STRONGEST signal."
    },
    {
      "key": "genre_fit",
      "label": "Makes content in TVF lanes (comedy, slice-of-life, young-adult, workplace)",
      "points": 15,
      "input": "metadata.scoring_inputs.genre_fit",
      "guidance": "Check credits/website/YouTube. Full points if core focus; half if occasional. LOWERED 2026-08-20 from 25 (owner rubric review): genre mismatch matters but should weigh less than proven IP-adaptation history or live distribution."
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
      "label": "Right size: ~2-20 core people, most under 10, real credits, independent",
      "points": 20,
      "input": "metadata.scoring_inputs.right_size",
      "guidance": "Lean team, not a small studio in name only. Big enough to execute, small enough to want a partner. Headcount hints plus credit history. RAISED 2026-08-20 from 15 (owner rubric review): operational fit is a harder constraint than the original weight implied."
    },
    {
      "key": "reachable_decision_maker",
      "label": "Named decision-maker identified and reachable",
      "points": 10,
      "input": "metadata.scoring_inputs.reachable_decision_maker",
      "guidance": "Auto-set by the engine: 1.0 if a target-role contact has a valid email, 0.5 if catch-all, else 0."
    },
    {
      "key": "collaboration_openness",
      "label": "Demonstrated openness to collaboration: explicit invitation, collective/partner-led model, or co-production track record",
      "points": 15,
      "input": "metadata.scoring_inputs.collaboration_openness",
      "guidance": "Full credit for an explicit collaboration/partnership invitation on their own site, a collective or partner-led operating structure, or a track record of co-productions. Half credit for a weaker or implicit signal. Distinct from international_ip_experience, though the two can overlap. ADDED 2026-07: default weight 15. CONFIRMED 2026-08-20 (owner rubric review): kept at 15 despite the overlap with international_ip_experience -- an explicit partnership invitation or collective structure is meaningfully different from having actually adapted a format before. Rubric pool now sums to 110 (was 115) after this review; the engine renormalizes over assessed points regardless of the pool''s absolute sum, so this is a relative-weight statement, not a percentage."
    }
  ],
  "score_modifiers": [
    {
      "key": "client_work_dominance",
      "label": "PENALTY: output dominated by client/branded-content work, not owned IP",
      "max_penalty": -20,
      "input": "metadata.scoring_inputs.client_work_dominance",
      "guidance": "A /work page full of brand-client logos is a NEGATIVE, not a portfolio positive. 1.0 = entirely client work (full -20), 0 = no evidence of client-work dominance (no penalty). Soft subtractor, not a hard gate."
    },
    {
      "key": "india_diaspora_affinity",
      "label": "BONUS: existing India/Asia ties, diaspora-crossover audience, or prior work with an Indian company",
      "max_bonus": 6,
      "input": "metadata.scoring_inputs.india_diaspora_affinity",
      "guidance": "Rare signal. Most good leads will legitimately score 0 here, which is not a strike against them. Kept small and additive so it never overrides the 5 primary fit signals."
    },
    {
      "key": "revenue_above_cap",
      "label": "PENALTY: revenue estimate above the ~$1M microbudget-scale ceiling (borderline vs clean fit)",
      "max_penalty": -20,
      "input": "metadata.scoring_inputs.revenue_above_cap",
      "guidance": "Private production companies rarely publish revenue, so this cannot be verified directly. Estimate via third-party tools (e.g. LeadIQ, Buzzfile, RocketReach) where available, else reviewer judgment. 1.0 = a confirmed third-party estimate above ~$1M (borderline), 0 = at/under ~$1M or microbudget-scale (clean fit) or no negative evidence. Soft subtractor by design, matching a flag-rather-than-auto-drop preference - a reviewer can still drop borderline rows manually if being strict. RAISED 2026-08-20 from -10 to -20 (owner rubric review): now weighted as seriously as client_work_dominance. NOT YET CONNECTOR-AUTOMATED: LeadIQ/Buzzfile/RocketReach free-tier usability for this pipeline has not been adversarially verified the way every other tool in this project has been (see impl. plan §10) - until that verification happens, this input is set by the reviewer/manual lookup at S7.5, not by any connector."
    }
  ],
  "gates": [
    {
      "key": "us_geography",
      "label": "Primary operation/HQ must be in the United States",
      "input": "metadata.scoring_inputs.geography_signal",
      "exclude_when": "non_us",
      "guidance": "Fires ONLY on confirmed non-US evidence (e.g. YouTube channel country field explicitly non-US). Blank/unknown always passes through."
    },
    {
      "key": "not_a_major_or_oversized",
      "label": "Exclude majors, their named subsidiaries, and anything clearly oversized",
      "input": "metadata.scoring_inputs.major_or_oversized_signal",
      "exclude_when": true,
      "guidance": "Name/keyword match against known majors, or a confirmed size signal well beyond the ~50-person ceiling. Blank/unknown always passes through."
    },
    {
      "key": "usable_first_party_presence",
      "label": "Must have SOME reachable presence: website, owned channel, or social",
      "input": "metadata.scoring_inputs.has_reachable_presence",
      "exclude_when": false,
      "guidance": "A YouTube channel itself already satisfies this for connector-sourced candidates, so this gate effectively always passes them."
    },
    {
      "key": "is_active",
      "label": "Company/channel must be currently active, not dormant or defunct",
      "input": "metadata.scoring_inputs.activity_signal",
      "exclude_when": "confirmed_dormant",
      "guidance": "Fires ONLY on confirmed dormancy (e.g. no upload or site activity in 12+ months, an explicit closed/discontinued notice). Blank/unknown always passes through. The connector makes a cheap best-effort read from upload recency at discovery time; Layer B enrichment gets a fuller look once it actually visits the site, and can override that initial guess."
    }
  ],
  "review_checklist": [
    {
      "key": "is_a_content_production_company",
      "label": "Is this actually an IP-owning production company, not a service vendor, agency, institution, or an unrelated same-name LLC?",
      "guidance": "Free sources cannot reliably tell these apart at intake - this is a human judgment call at review (§7.5), not an auto-enforced gate."
    },
    {
      "key": "in_scope_subtype",
      "label": "Is the subtype actually in scope (commercial/branded, digital/social, film/TV/streaming) and NOT corporate/service video?",
      "guidance": "Confirm against real site/channel content, not just a keyword match that got it into staging."
    },
    {
      "key": "independent_ownership",
      "label": "Founder/partner-owned - no studio/network parent, no PE ownership, no large-scale VC backing on record",
      "guidance": "Check Crunchbase/PitchBook/press where feasible. Free automated sources (YouTube API etc.) cannot verify ownership/cap-table structure - this is a manual check, not a connector-computed signal. Precedent for a judgment-call exception: a single small convertible note (e.g. roughly $500K) from non-marquee sources does not by itself disqualify a candidate."
    }
  ],
  "youtube_discovery_queries": [
    { "query": "digital comedy studio", "genre_hint": "comedy" },
    { "query": "workplace comedy channel", "genre_hint": "workplace" },
    { "query": "young adult drama studio", "genre_hint": "young-adult" },
    { "query": "slice of life web series studio", "genre_hint": "slice-of-life" },
    { "query": "branded content studio", "genre_hint": null },
    { "query": "production company", "genre_hint": null }
  ],
  "metadata_fields": [
    "subtype",
    "hq_city", "hq_state",
    "team_size_estimate",
    "genres",
    "notable_credits",
    "format_deals",
    "platform_relationships",
    "why_fit",
    "scoring_inputs"
  ],
  "sources": [
    {
      "slug": "youtube_api",
      "name": "YouTube Data API v3 (search+channels)",
      "kind": "api",
      "phase": 1,
      "detail": "BUILD FIRST. PRIORITY: digital/YouTube/social studios. 10k units/day free. Filters creators-vs-studios by size/keyword/email-in-description; sets genre_fit from the genre_hint of the matched query, plus the 4 gate-input signals."
    },
    {
      "slug": "google_news_rss",
      "name": "Google News RSS (keyword + site: trades)",
      "kind": "rss",
      "phase": 2,
      "detail": "SIGNAL: catches deal-announcement headlines such as a US shop adapting a foreign format. Company named leads to a high international_ip_experience score."
    },
    {
      "slug": "x_intent_signals",
      "name": "X/Twitter intent posts via Google News RSS",
      "kind": "rss",
      "phase": 2,
      "detail": "SIGNAL: founder-collab posts via a site:x.com Google News RSS query. Not the X API (paid-only since Feb 2026). Noisy and partial, needs a filter step plus human review."
    },
    {
      "slug": "wikidata",
      "name": "Wikidata SPARQL",
      "kind": "api",
      "phase": 3,
      "detail": "Film/TV/streaming producer seed: name plus official website plus industry. CC0, free forever. Notable-only, so a seed rather than a stream."
    },
    {
      "slug": "aicp_directory",
      "name": "AICP member directory (scrape)",
      "kind": "scrape",
      "phase": 4,
      "detail": "Commercial/branded shops. Static HTML, names only, needs domain enrichment downstream. ToS is reference-only."
    }
  ],
  "enrichment": {
    "provider": "apollo",
    "contact_method": "apollo_org_match_then_people_search",
    "email_verifier": "apollo",
    "fallback": "site_scrape_then_human_confirm",
    "fallback_enabled": false,
    "guidance": "Apollo is the enrichment and verification backbone (owner decision 2026-08-20): organization match by domain, then people search filtered to target_contact_roles, then Apollo verification status mapped onto contacts.email_status. Hunter (pattern oracle) and Reoon (verifier) were dropped from the critical path on the same date, and the pattern-guess hedge they required is deleted with them. The site-scrape path survives only as backlog item B1, disabled by default: it is pulled into the ladder only if Checkpoint 2 (P17) shows Apollo missing more than roughly 30 percent of 2-10-person shops. Nothing reads this block until P16 -- it records the decision, it is not live wiring."
  }
}'::jsonb
);
