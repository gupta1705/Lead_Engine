-- 03B_SYNC_SEGMENT_CONFIG.SQL
-- THE STANDING CONFIG SYNC. Run this whenever config/segment.us-production-houses.json
-- changes, to push the repo's config onto the live segments row. Idempotent by
-- construction: it sets `config` to one exact literal, so running it twice is
-- the same as running it once. `tools/verify_repo.py` fails if the JSON below
-- ever drifts from the .json file, which is what makes three copies safe.
--
-- Revision history:
--   v7 (2026-10-14) the owner's template for US Production Houses ("This is the template for us prod
--       house outreach going forwards"): v3 templates in each approver's own voice (signed_intro),
--       the hook line by Groq (generated_paragraph shape line), subject "Stories built to travel",
--       footer "Regards, <name>. The Viral Fever"; the v2 pair kept for older drafts.
--   v6 (2026-10-13) the owner: the opt-out line is removed from the footer ("prod houses also loses last line"),
--       and every subject is at most five words: both templates' subject is "On {{theme}}",
--       the theme at most four words (theme_max_words), subject_max_words 5 with a
--       subject_fallback on each template.
--   v5 (2026-10-12) outreach.send_window (owner: "send mails to the sender's time region between
--       10 to 10:30AM ... randmized"): each approved email at its own random second, 10:00-10:30 on
--       its recipient's clock, US companies with no known state at Los Angeles' 10:00. The
--       2026-10-09 footer change (no postal address) rides along with this sync.
--   v4 (2026-08-23) owner threshold revamp: score_threshold_review 40 -> 25,
--       score_threshold_priority 75 -> 60. The v3 numbers were calibrated
--       against scores computed on partial denominators; once unverified
--       inputs began scoring 0 (see 04b + amended invariant 1) every score
--       dropped and nothing could reach 75 at all, leaving the priority band
--       unreachable. 60/25 restores a working two-band split.
--   v3 (2026-08-20) owner rubric weight review -- notes below.
--
-- ORIGINAL v3 NOTE, kept for the record (2026-08-20).
--
-- The live `segments` row for 'us-production-houses' was inserted from the
-- v2 config (6 rubric criteria at the original weights, revenue_above_cap at
-- -10). Since then, an owner-run rubric weight review changed three numbers:
--   genre_fit             25 -> 15
--   right_size             15 -> 20
--   revenue_above_cap  max_penalty  -10 -> -20
-- (pool now sums to 110, was 115). config/segment.us-production-houses.json
-- and sql/03_segment_us_production_houses.sql were updated to v3, but 03 was
-- never re-run against the live database (it's an INSERT, and the row
-- already exists). This UPDATE brings the live row in sync -- same JSON as
-- 03, copied verbatim.
--
-- Not needed on a fresh install: running 01 -> 02 -> 03 today already inserts
-- the up-to-date v3 config. This file exists only because 03 was run once,
-- earlier, against an older version of itself -- same situation as the
-- historical 04_update_segment_us_production_houses.sql patch at commit
-- 9383569, which this file follows the same pattern as.
--
-- Run in the Supabase SQL editor. Safe to run more than once (idempotent --
-- it just sets config to this exact value each time).

update segments
set config = '{
  "entity_type": "production_company",
  "weekly_target": 40,
  "batch_size": 30,
  "score_threshold_review": 25,
  "score_threshold_priority": 45,
  "target_contact_roles": [
    "Founder",
    "Co-Founder",
    "Head of Development",
    "Development Executive",
    "Executive Producer",
    "Head of Acquisitions",
    "Head of Distribution"
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
  "metadata_fields": [
    "subtype",
    "hq_city",
    "hq_state",
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
      "slug": "apollo",
      "name": "Apollo.io company and decision-maker search",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_apollo.py uses this project''s saved constraints; contact roles and verified work addresses come from Apollo."
    }
  ],
  "self_exclusion": {
    "domains": [
      "theviralfever.com",
      "tvfplay.com"
    ],
    "name_patterns": [
      "the viral fever",
      "girliyapa",
      "contagious online media"
    ],
    "guidance": "TVF and its affiliates must never enter the lead pool. This is not hypothetical: the first live YouTube run on 2026-08-24 surfaced The Viral Fever own channel among 125 candidates. It was caught only because 13.1M subscribers tripped the major_or_oversized gate - a smaller affiliate channel, a regional spinoff, or a partner shop would have sailed through, been scored, reviewed, and eventually put on a send list. Matching is deliberately conservative: domains match on exact host or subdomain, name_patterns match as whole words against a lowercased entity name. Note the absence of a bare tvf pattern - it would match TVFoods, TVFirst and similar unrelated names, and a self-exclusion rule that quietly deletes real leads is worse than the problem it solves. Add specific affiliate names here as they come up rather than broadening the patterns."
  },
  "auto_shortlist": {
    "enabled": true,
    "min_score": 30,
    "guidance": "Owner decision 2026-09-21: automatically shortlist all companies with a score over 30. Every ready_for_review lead with fit_score strictly above min_score is shortlisted by the last step of the promote chain (sql/14_auto_shortlist.sql), the same rule LCX clipping has run at 20 since 2026-09-14. Leads between the review threshold (25) and 30 stay in To review for a person. Rejected, archived and contacted rows are never touched, and a lead a person moves back to review is never shortlisted again (metadata.auto_shortlisted_at). Shortlisting sends nothing: the draft it leads to still needs approval. Set enabled to false to go back to shortlisting by hand."
  },
  "enrichment": {
    "provider": "apollo",
    "enabled": true,
    "score_over": 22.5,
    "find_website_by_name": true,
    "credits_per_run": 150,
    "verified_only": true,
    "recheck_after_days": 30,
    "contact_method": "apollo_people_search",
    "email_verifier": "apollo",
    "fallback": "site_scrape_then_human_confirm",
    "fallback_enabled": false,
    "guidance": "Apollo supplies new contacts in the target roles. Existing score, geographic and site-verification restrictions and credit caps apply. Websites are read only for qualification evidence."
  },
  "outreach": {
    "sender": {
      "name": "Vedansh Gupta",
      "title": "Outreach Consultant",
      "postal_address": "Contagious Online Media Network Pvt Ltd. 702, 7th Floor, A Wing, Fortune Terraces, Opp. Citi Mall, New Link Rd, Andheri West, Mumbai, Maharashtra 400053",
      "guidance": "Sender name and title for the shared sign-off. The address is retained as an optional footer field and omitted from the default email footer (owner, 2026-10-09). The sending address comes from the connected Gmail account."
    },
    "send_window": {
      "enabled": true,
      "start": "10:00",
      "end": "10:30",
      "timezone_of": "recipient",
      "sender_timezone": "Asia/Kolkata",
      "fallback_timezone": "America/Los_Angeles",
      "assumed_country": "US",
      "country_zones": {
        "US": "America/Los_Angeles"
      },
      "weekdays_only": true,
      "min_gap_seconds": 45,
      "min_lead_seconds": 120,
      "guidance": "Owner, 2026-10-12: \"I want you to send mails to the sender''s time region between 10 to 10:30AM and that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13 and so on after approval implement it\". Each approved email goes out at its own random second between start and end on its RECIPIENT''s clock (10:00 in Mumbai is 05:30 in London, too early to be read), drawn when it is approved and shown in Approved as \"Goes out\", with the time in India beside it. Where the recipient is comes from what the lead holds -- the person''s own Apollo record, the company''s state or city, a phone''s area code, its country -- and the reason is kept on the email (tools/send_window.py). Monday to Friday on the recipient''s clock (weekdays_only): an approval after today''s window, or at a weekend, takes the next weekday''s. An email whose window passes unsent (the server down, its address at its daily limit) moves to the next window at a new random time, never later the same day. Never two emails from one address closer than min_gap_seconds; never one sooner than min_lead_seconds after its approval. To send on the sender''s clock instead (every email 10:00-10:30 India time) set timezone_of to \"sender\"; to switch the window off set enabled to false -- the stored times are cleared and approvals go out as soon as they can, as before. docs/runbook.md, \"Goes out\". The AICP''s houses are American (assumed_country), and most of them are in Los Angeles: a US company whose state is not known goes at Los Angeles'' 10:00, not New York''s (country_zones); its state, city or phone decides when one is known."
    },
    "daily_send_cap": 35,
    "subject_max_words": 5,
    "subject_max_words_guidance": "The owner, 2026-10-13: \"subject for all emails for all services should be less than 5 or equal to 5 words\". Every rendered subject is checked against this (tools/draft_render.capped_subject): one over it uses its template''s subject_fallback, and one still over it is not drafted, so a longer subject never ships. \"Re:\" in front of a follow-up is not counted.",
    "theme_max_words": 4,
    "theme_max_words_guidance": "The owner, 2026-10-13: the subject is \"On {{theme}}\", so the theme is at most four words. A longer theme from the model gives way to the lane''s own theme (angles.<lane>.theme), and one of those still longer to \"Stories Built to Travel\" (tools/draft_render.pick_theme).",
    "send_from": "approver",
    "send_from_guidance": "Owner decision 2026-09-26: one login per person (suhasc@, kartikeyap@, upangyay@theviralfever.com), each linked by the owner to one or more Gmail addresses (python tools/users.py gmail <login>, on the owner''s machine: Google''s sign-in, sealed for the server; the person connects nothing). An email goes out from the Gmail of the person who approved it, from the address of theirs with the most room today, up to that address''s own limit (daily_cap on its user_mailboxes row, 35 by default; daily_send_cap here is not used in this mode). It is signed with their own name and title (account menu -> Your name and title), and the page shows each draft as the person looking at it would send it (tools/draft_render.personalize). An approval by someone with no Gmail connected waits in Approved. The project''s own mailbox (GMAIL_SENDER_ADDRESS, vedanshg@) sends nothing new; it still reads replies to the two emails it sent. Set to \"pool\" (or remove) to go back to sending from the project''s own mailbox.",
    "greeting_fallback": "{{company}} team",
    "hook_style": "tvf_partnership",
    "templates": [
      {
        "key": "tvf_partner_named_v3",
        "when": {
          "contact_named": true
        },
        "subject": "Stories built to travel",
        "subject_fallback": "Stories built to travel",
        "body": "Hello {{greeting_name}},\n\nI trust you are well.\n\n{{sender_intro}}, one of India''s leading digital-native content studios. We are best known for series such as Panchayat, Sapne vs. Everyone and Aspirants, and six of our titles rank among India''s ten highest-rated shows on IMDb. {{angle_line}}\n\n{{hook}}\n\nWould you have time for a short call in the coming weeks to explore whether there is a fit? I am based in Mumbai and would gladly work around your schedule.\n\n{{footer}}",
        "guidance": "The owner''s template of 2026-10-14, word for word (\"This is the template for us prod house outreach going forwards fix it should be like this only\"): who we are in the approver''s own voice ({{sender_intro}}: \"I''m Kartikeya, who handles Business Development and IP Strategy at The Viral Fever (TVF)\" for Kartikeya, each other approver with their own name and title, outreach.signed_intro), TVF''s shows, the lane''s own intro line ({{angle_line}}, outreach.angles); then one paragraph: \"Which is why <company> caught my attention.\", the hook line Groq writes from the company''s own facts (generated_paragraph, shape \"line\"; the plain line in tools/draft_render.ph_line_fallback when no model writes one) and the lane''s partnership lines ({{partnership}}); the call, with no city; the sign-off \"Regards, <name>. The Viral Fever\". Subject \"Stories built to travel\" (the owner''s choice that day; at most 5 words). This one when the email greets a named person: \"Hello <first name>, I trust you are well.\""
      },
      {
        "key": "tvf_partner_v3",
        "subject": "Stories built to travel",
        "subject_fallback": "Stories built to travel",
        "body": "Hello,\n\n{{sender_intro}}, one of India''s leading digital-native content studios. We are best known for series such as Panchayat, Sapne vs. Everyone and Aspirants, and six of our titles rank among India''s ten highest-rated shows on IMDb. {{angle_line}}\n\n{{hook}}\n\nWould you have time for a short call in the coming weeks to explore whether there is a fit? I am based in Mumbai and would gladly work around your schedule.\n\n{{footer}}",
        "guidance": "The owner''s template of 2026-10-14, word for word (\"This is the template for us prod house outreach going forwards fix it should be like this only\"): who we are in the approver''s own voice ({{sender_intro}}: \"I''m Kartikeya, who handles Business Development and IP Strategy at The Viral Fever (TVF)\" for Kartikeya, each other approver with their own name and title, outreach.signed_intro), TVF''s shows, the lane''s own intro line ({{angle_line}}, outreach.angles); then one paragraph: \"Which is why <company> caught my attention.\", the hook line Groq writes from the company''s own facts (generated_paragraph, shape \"line\"; the plain line in tools/draft_render.ph_line_fallback when no model writes one) and the lane''s partnership lines ({{partnership}}); the call, with no city; the sign-off \"Regards, <name>. The Viral Fever\". Subject \"Stories built to travel\" (the owner''s choice that day; at most 5 words). This one when no person is named: \"Hello,\" and the same email."
      },
      {
        "key": "tvf_partner_named_v2",
        "when": {
          "contact_named": true,
          "metadata.retired_template": true
        },
        "subject": "On {{theme}}",
        "body": "Hello {{greeting_name}},\n\nI trust you are well.\n\nI''m writing on behalf of Kartikeya, who leads Business Development and IP Strategy at The Viral Fever (TVF), one of India''s leading digital-native content studios. We are best known for series such as Panchayat, Sapne vs. Everyone and Aspirants, and six of our titles rank among India''s ten highest-rated shows on IMDb. {{angle_line}}\n\n{{hook}}\n\n{{partnership}}\n\nWould you have time for a short call in the coming weeks to explore whether there is a fit? I am based in Mumbai and would gladly work around your schedule{{their_city}}.\n\n{{footer}}",
        "guidance": "The owner''s outreach template (samples of 2026-09-18). Four paragraphs: who we are and what we make; which is why this company caught our attention; the partnership and why it fits; a short call. {{angle_line}} and {{partnership}} are the owner''s sentences for the company''s lane, from outreach.angles. {{hook}} is \"Which is why <company> caught my attention.\" and a paragraph about the company written from what it says about itself (generated_paragraph; the plain paragraph in tools/draft_render.py when no model writes one). {{theme}} is the subject''s theme. A human reads every draft before approval. This one when the email greets a named person (samples 5 and 6). 2026-09-21, the owner: the email comes from Vedansh (the footer''s sender) and is written on Kartikeya''s behalf, so the opening names Kartikeya and his role while the sign-off is the footer''s. Subject (owner, 2026-10-13, at most five words): \"On {{theme}}\" for both templates, the theme at most theme_max_words. Kept for the drafts written with it before 2026-10-14; new drafts use the v3 templates, which come first.",
        "subject_fallback": "On Stories Built to Travel"
      },
      {
        "key": "tvf_partner_v2",
        "subject": "On {{theme}}",
        "body": "Hello,\n\nI''m writing on behalf of Kartikeya, who handles Business Development and IP Strategy at The Viral Fever (TVF, India), one of India''s largest digital-native studios. Of the 11 Indian shows on the IMDb Global 250 list, 7 are ours. {{angle_line}}\n\n{{hook}}\n\n{{partnership}}\n\nWould you have time for a short call in the coming weeks? Either way, I would love to hear from you.\n\n{{footer}}",
        "guidance": "The owner''s outreach template (samples of 2026-09-18). Four paragraphs: who we are and what we make; which is why this company caught our attention; the partnership and why it fits; a short call. {{angle_line}} and {{partnership}} are the owner''s sentences for the company''s lane, from outreach.angles. {{hook}} is \"Which is why <company> caught my attention.\" and a paragraph about the company written from what it says about itself (generated_paragraph; the plain paragraph in tools/draft_render.py when no model writes one). {{theme}} is the subject''s theme. A human reads every draft before approval. This one when no person is named (samples 1 to 4). 2026-09-21, the owner: written on Kartikeya''s behalf by the footer''s sender, as in the named template. Subject (owner, 2026-10-13, at most five words): \"On {{theme}}\" for both templates, the theme at most theme_max_words. Kept for the drafts written with it before 2026-10-14; new drafts use the v3 templates, which come first.",
        "subject_fallback": "On Stories Built to Travel",
        "when": {
          "metadata.retired_template": true
        }
      },
      {
        "key": "tvf_partner_followup_v1",
        "kind": "follow_up",
        "subject": "Re: {{opener_subject}}",
        "body": "{{hello}}\n\nI hope you are well. I wanted to follow up on my note about {{company}} and The Viral Fever. If a short call in the coming weeks would be useful, I would gladly work around your schedule.\n\n{{footer}}",
        "guidance": "The follow-up to the owner''s partnership note: the same formal voice (Hello, I hope you are well), the same ask (a short call, around their schedule), signed by the person who sent the note."
      }
    ],
    "follow_ups": {
      "enabled": true,
      "steps": [
        {
          "step": 1,
          "after_days": 4,
          "template": "tvf_partner_followup_v1"
        }
      ],
      "guidance": "Owner, 2026-10-23: \"Make follo ups for all\", after \"set only 1 follow up after 4 days\" for LCX Clipping. One follow-up, four days after the first email went out with no reply, in the same Gmail thread (\"Re: <the first email''s subject>\"), from the same address, signed by the person whose Gmail the thread is in. It is a draft in the Follow-ups tab and needs approval like any email. Any reply stops it at once (an auto-reply lets it resume); Stop follow-ups ends the thread by hand; the database refuses one after a reply (sql/23)."
    },
    "angles": {
      "guidance": "The owner''s own sentences for each lane a production company works in, taken from the samples of 2026-09-18. tools/draft_render.tvf_angle() picks the lane from what the company says about itself and what the engine recorded: animation, then documentary and impact work (conscience), then digital-first (digital), then scripted drama and genre (drama), else general. intro_line ends the first paragraph, partnership is the third, theme is the subject when no model writes one.",
      "general": {
        "intro_line": "Much of our work draws its strength from telling deeply local, human stories with enough craft to travel far beyond India.",
        "partnership": "That shared instinct is why I wanted to reach out. India is one of the world''s richest and least-tapped sources of stories, talent and IP, and I believe there is real potential in how a house like {{company}} and a studio like ours might work together, whether through co-production, international financing, or developing series and films designed to cross borders from the start.",
        "theme": "Stories Built to Travel"
      },
      "animation": {
        "intro_line": "Storytelling has always been the core of what we do, and we are now extending it into animation, an area we have been building toward deliberately and are keen to grow with the right partners.",
        "partnership": "Part of this is a deliberate move into kids and family content built for a global audience, drawing on Indian stories and characters with the potential to travel worldwide. I believe there is real potential in how our storytelling and your artistry might come together, whether co-developing original films and series, or building new IP that reaches audiences of every age across our markets.",
        "theme": "Bringing Our Stories to Animation"
      },
      "conscience": {
        "intro_line": "Much of our best work comes from a single instinct: giving honest, often overlooked lives the dignity of being told well, and telling them with enough craft to travel.",
        "partnership": "That shared instinct is why I wanted to reach out. India holds an extraordinary depth of underrepresented and untold stories, and very few have reached a global audience with the care they deserve. I believe there is real potential in how our two companies might work together, whether co-producing character-driven film and series, or bringing these kinds of stories across our markets.",
        "theme": "Storytelling With a Conscience"
      },
      "digital": {
        "intro_line": "We built long-form scripted storytelling on YouTube in India before the traditional system took us seriously, and grew from there into series, formats and film.",
        "partnership": "That shared belief is why I wanted to reach out. India is one of the richest and least-tapped sources of stories, talent and IP anywhere, and I believe there is real potential in how an indie studio like {{company}} and a studio like ours might work together, whether through co-financing, co-production, or developing series designed to travel. This is precisely the kind of non-standard partnership we are built to lead.",
        "theme": "Building Outside the Traditional System"
      },
      "drama": {
        "intro_line": "Our work has always been built on telling deeply local, human stories with a craft that lets them travel far beyond India.",
        "partnership": "That shared belief is why I wanted to reach out. India is one of the world''s richest and least-tapped sources of exactly these stories, in epics, thrillers, grounded fantasy and character-driven drama, and I believe there is real potential in how a studio like ours and {{company}} might work together, whether through co-production, adaptation, or developing high-concept stories designed to cross borders from the start.",
        "theme": "Stories That Transcend Borders"
      }
    },
    "generated_paragraph": {
      "enabled": false,
      "provider": "groq",
      "model": "openai/gpt-oss-120b",
      "min_words": 10,
      "max_words": 30,
      "max_calls_per_run": 200,
      "requests_per_minute": 3,
      "guidance": "The one line of the owner''s 2026-10-14 template no fixed text can write: after \"Which is why <company> caught my attention.\", one sentence on what at the heart of their work is the same ground TVF''s own series stand on (the owner''s sample: \"The comedy at the heart of your work is the same ground our own series stand on.\"). Written by Groq from tools/draft_render.tvf_facts(): their own site''s words, their named work, their genres; never the company''s or a person''s name, no TVF claims, no praise, no numbers, no dashes; 10 to 30 words. A rejected answer gets one retry, told why; then the plain line (draft_render.ph_line_fallback). The owner, 2026-10-14: \"Groq writes it\".",
      "shape": "line"
    },
    "guidance": "Everything outbound is drafted -> human-approved -> sent, in that order, no exceptions. daily_send_cap is a hard ceiling per send run. One outbound touch per company is enforced by the database (uq_outreach_one_touch), not by this config. The footer -- the sign-off -- is one setting for the whole segment (outreach.footer.text), edited in the app under Outreach -> Footer; templates end with {{footer}}.",
    "footer": {
      "text": "Regards,\n{{sender_name}}.\nThe Viral Fever",
      "guidance": "The owner''s sign-off of 2026-10-14: \"Regards,\", the approver''s own name with a full stop, \"The Viral Fever\". No title, no postal address, no opt-out line (the owner, 2026-10-13)."
    },
    "default_cc": [
      "amritanshv@lightscameraexperiment.com"
    ],
    "default_cc_guidance": "The owner, 2026-10-22: \"add a feature to cc someone from the software itself. Make default cc to the email amritanshv@lightscameraexperiment.com and obvio make a toggle to switch that off\". Every email of this project is copied to these addresses unless the person approving it switches that off in the email (the CC toggle) or changes the list. The list an email is approved with is the one it goes out with (outreach.cc, sql/39, frozen at approval): changing this default never changes an email already approved. A reply from one of these addresses is not taken for the recipient''s reply. [] copies nobody by default.",
    "signed_intro": "I''m {{sender_first}}, who handles {{sender_title}} at The Viral Fever (TVF)",
    "tvf_hook": "line"
  },
  "sourcing": {
    "provider": "apollo",
    "allowed_sources": [
      "apollo",
      "manual"
    ],
    "contacts": "apollo",
    "guidance": "Owner decision 2026-10-19: all new leads and contacts come from Apollo. Existing project constraints, gates and scoring remain. Company websites and news verify already-known leads; they do not discover new ones. Clipping is exempt. Owner, 2026-10-23: a lead a person found on their own is the exception (\"send custom mail to a lead that we find on our own, as in lead is not generated by software\"): Leads -> Add a lead adds it by hand with source ''manual'', and the address that person typed in (contacts source ''manual'', verifier ''person'') may be written to (sql/42, tools/manual_lead.py). Nothing automatic adds a manual lead."
  },
  "schedule": [
    {
      "name": "weekly refresh",
      "pipeline": "weekly_refresh",
      "dow": 1,
      "hour": 2,
      "minute": 0,
      "enabled": true
    }
  ],
  "pipelines": {
    "weekly_refresh": [
      "discover_apollo",
      "promote_chain",
      "prepare_apollo",
      "verify_sites",
      "news_sweep",
      "promote_chain",
      "enrich_apollo_project",
      "promote_chain"
    ]
  },
  "apollo_discovery": {
    "pages_per_run": 5,
    "per_page": 100,
    "countries": [
      {
        "name": "United States",
        "iso": "US"
      }
    ],
    "searches": [
      {
        "key": "independent_film",
        "filters": {
          "q_organization_keyword_tags": [
            "film production",
            "film & television production",
            "motion pictures & film"
          ],
          "organization_num_employees_ranges": [
            "1,10",
            "11,20"
          ]
        }
      },
      {
        "key": "television",
        "filters": {
          "q_organization_keyword_tags": [
            "television production",
            "tv production",
            "scripted television"
          ],
          "organization_num_employees_ranges": [
            "1,10",
            "11,20"
          ]
        }
      },
      {
        "key": "formats",
        "filters": {
          "q_organization_keyword_tags": [
            "independent production",
            "unscripted television",
            "film and television"
          ],
          "organization_num_employees_ranges": [
            "1,10",
            "11,20"
          ]
        }
      }
    ],
    "guidance": "US headquarters, lean independent film/TV production teams. Actual size, majors, activity, genres, distribution and IP partnerships are checked by the existing scoring and gates.",
    "excluded_name_patterns": [
      "disney",
      "warner bros",
      "nbcuniversal",
      "paramount",
      "sony pictures",
      "viacomcbs",
      "mgm",
      "lionsgate",
      "netflix",
      "amazon studios",
      "hbo",
      "a24",
      "universal pictures",
      "20th century"
    ]
  }
}'::jsonb
where slug = 'us-production-houses';

-- Verify it landed:
select
  slug,
  config->'rubric'->1->>'points' as genre_fit_points,      -- expect 15
  config->'rubric'->3->>'points' as right_size_points,     -- expect 20
  config->'score_modifiers'->2->>'max_penalty' as revenue_penalty  -- expect -20
from segments
where slug = 'us-production-houses';
