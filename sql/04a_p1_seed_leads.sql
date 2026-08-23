-- 04A_P1_SEED_LEADS.SQL
-- P1 -- the 10 hand-researched candidates, ready to run.
--
-- SOURCE: 20th-Aug_USProductionHouseLeads.xlsx (sheet "Target List", 10 rows),
-- owner-compiled 2026-08-20. Every scoring_inputs value below is derived from
-- a column in that sheet -- Specialty, Team Size, Ownership, Est. Revenue,
-- $1M Cap Fit, Collaboration Signals, TVF Collaboration Angle, Notes.
--
-- THE RULE THIS FILE TAKES SERIOUSLY (invariant 1, null != zero):
--   A key is present ONLY where the sheet carries actual evidence for it.
--   Where the sheet is silent, the key is ABSENT -- not 0.
--
--   The big one: `international_ip_experience` (30 points, the single
--   strongest rubric signal) is set on ONE company -- Tonko House, whose ONI
--   was an explicit Japan-US multi-studio co-production. For the other nine
--   the sheet simply does not say, and it was not compiled to answer that
--   question. Writing 0 there would be a lie of a specific kind: it would
--   claim someone checked for a format deal and found none. Nobody checked.
--   So those nine score normalized over a 70-point pool instead of 100 --
--   "fit among what we know", exactly as the scorer intends.
--
--   PRACTICAL CONSEQUENCE, worth knowing before you read the rankings: if you
--   happen to know that one of these nine HAS adapted or co-produced foreign
--   IP, adding that key will move them substantially. It is the highest-value
--   blank on the board.
--
--   `reachable_decision_maker` is absent everywhere by design -- it is
--   engine-set from a verified contact at P10/P16, never reviewer-set.
--
-- CONTACTS: the sheet carries real published emails and named roles. They are
-- parked in `metadata.p1_research`, NOT inserted into the `contacts` table.
-- P10 is where contacts land, and P17 measures Apollo against P10 as the human
-- baseline -- preloading contacts here would quietly corrupt that comparison.
-- Nothing is lost; the research travels with the row.
--
-- Run the whole file once. Then run CHECK 2 in 04_insert_template.sql -- it
-- should return zero rows.

----------------------------------------------------------------------
-- 1. Exit 73 Studios -- Riverhead, NY
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Exit 73 Studios',
  'exit73studios.com',
  'manual_p1',
  'https://exit73studios.com',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Riverhead",
    "hq_state": "NY",
    "team_size_estimate": "2 owners + ~5 including regular collaborators",
    "genres": ["adult comedy", "kids animation"],
    "notable_credits": [
      "#BLUD (own indie game, with Humble Games)",
      "Animation for Nickelodeon, Cartoon Network, Disney, CollegeHumor"
    ],
    "format_deals": [],
    "platform_relationships": ["Nickelodeon", "Cartoon Network", "Disney", "CollegeHumor"],
    "why_fit": "Two-person low-overhead 2D shop with dual-lane DNA that mirrors TVF: Burns is ex-Augenblick (Comedy Central / Adult Swim), Fox comes from the Nick Jr side. Transmedia proof via their own indie game. A natural India-US short-form comedy format exchange.",
    "scoring_inputs": {
      "genre_fit": 1,
      "distribution_relationship": 0.5,
      "right_size": 1,
      "collaboration_openness": 0.5,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 1",
      "key_contact": "Chris Burns - Co-owner/Director/Animator; Bob Fox - Co-owner/President",
      "published_email": "info@exit73studios.com",
      "phone": "+1 631-381-0200",
      "ownership": "Self-owned by two childhood friends; no investors on record",
      "revenue_estimate": "Under $1M (LeadIQ / Cience est.) -- graded CLEAN FIT",
      "caveats": "Broker-reported first-name@ direct addresses exist but are UNVERIFIED -- use info@ addressed by name. Relational hook: Burns worked at Augenblick Studios."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 2. Lowbrow Studios -- Fairfield, CT
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Lowbrow Studios',
  'lowbrowstudios.com',
  'manual_p1',
  'https://lowbrowstudios.com',
  'discovered',
  '{
    "subtype": "digital_social",
    "hq_city": "Fairfield",
    "hq_state": "CT",
    "team_size_estimate": "2-10 (LinkedIn; ~7 per Lusha)",
    "genres": ["adult comedy", "digital comedy"],
    "notable_credits": [
      "Sonic For Hire",
      "Dorkly (owned channel, bought out of the CollegeHumor orbit in 2023)",
      "Cyanide & Happiness"
    ],
    "format_deals": [],
    "platform_relationships": [
      "Dorkly YouTube (owned)", "CollegeHumor", "Disney", "MTV",
      "Nickelodeon", "Mattel", "Rooster Teeth", "Dropout"
    ],
    "why_fit": "The closest US analog to the TVF web-native origin story: 20+ years of platform comedy animation PLUS owned distribution via the Dorkly YouTube channel. An acquirer, never acquired. Ready format-exchange partner. Annie-nominated.",
    "scoring_inputs": {
      "genre_fit": 1,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 2",
      "key_contact": "Mike Parker - Founder/Owner",
      "published_email": "info@lowbrowstudios.com",
      "phone": null,
      "ownership": "Self-owned (LinkedIn); no investors on record",
      "revenue_estimate": "$0-1M (LeadIQ & Lusha est.) -- graded CLEAN FIT",
      "caveats": "LinkedIn page lives at /company/cu-animation (old College University slug) -- do not be thrown by it. Email is their stated first touch; no phone published."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 3. Neon Zoo -- Washington, DC
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Neon Zoo',
  'neonzoo.co',
  'manual_p1',
  'https://neonzoo.co',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Washington",
    "hq_state": "DC",
    "team_size_estimate": "Tiny core + worldwide freelance roster",
    "genres": ["documentary animation", "impact storytelling"],
    "notable_credits": [
      "Victim/Suspect (Netflix)",
      "Seduced (Starz)",
      "The New Yorker",
      "Nat Geo and Planned Parenthood micro-doc series (2025-26)"
    ],
    "format_deals": [],
    "platform_relationships": ["Netflix", "Starz", "National Geographic", "The New Yorker", "ACLU", "UN Foundation"],
    "why_fit": "Opens a doc-animation lane TVF does not yet cover. The deliberate no-house-style philosophy pairs with a multi-style treatments library, and the distributed-artist model maps 1:1 onto an AI-augmented remote pipeline. Founder teaches animation at Georgetown.",
    "scoring_inputs": {
      "genre_fit": 0,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 3",
      "key_contact": "Elyse Kelly - Founder & Director (legal entity: Otter & Line Productions, LLC d/b/a Neon Zoo)",
      "published_email": "hello@neonzoo.co (studio); elyse@neonzoo.co (her own published card)",
      "phone": "+1 202-827-5003 (studio)",
      "ownership": "Woman-owned, founder-run; no investors on record",
      "revenue_estimate": "Not published; micro-studio scale -- graded CLEAN FIT",
      "caveats": "The founder publishes her own direct email AND mobile on a business-card page of the studio site -- verified self-published. Use it respectfully, with a personal note, never a blast."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 4. Meerkat Media -- Brooklyn, NY
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Meerkat Media',
  'meerkatmedia.org',
  'manual_p1',
  'https://meerkatmedia.org',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Brooklyn",
    "hq_state": "NY",
    "team_size_estimate": "8-13 worker-owners + ~15 artists-in-residence",
    "genres": ["documentary", "series"],
    "notable_credits": [
      "Dark Money (Oscar-shortlisted, co-production)",
      "Sundance and Tribeca titles",
      "Commissions for Netflix, NYT, NatGeo, Ford Foundation"
    ],
    "format_deals": [],
    "platform_relationships": ["Netflix", "The New York Times", "National Geographic", "Ford Foundation"],
    "why_fit": "The most values-aligned structure on the list: a consensus-run, profit-sharing worker cooperative -- a philosophical cousin to TVF writers-room collectivism. Emmy-nominated, with commissions that prove client-services muscle. Strong India-US documentary co-pro candidate.",
    "scoring_inputs": {
      "genre_fit": 0,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 4",
      "key_contact": "Jay Arthur Sterrenberg - Co-founder & member-owner (consensus-run; no CEO)",
      "published_email": "meerkats@meerkatmedia.org",
      "phone": "+1 401-954-4240 (co-op directory listing)",
      "ownership": "100% worker-owned cooperative -- structurally no outside investors",
      "revenue_estimate": "Not published; co-op scale -- graded CLEAN FIT",
      "caveats": "No single decision-maker: the collective inbox IS the exec channel, and consensus process means allowing longer response cycles."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 5. Calabash -- Chicago, IL
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Calabash',
  'calabashanimation.com',
  'manual_p1',
  'https://calabashanimation.com',
  'discovered',
  '{
    "subtype": "commercial_branded",
    "hq_city": "Chicago",
    "hq_state": "IL",
    "team_size_estimate": "~6 full-time core + 12+ global freelancers",
    "genres": ["brand character animation", "advertising"],
    "notable_credits": [
      "Lucky the Leprechaun", "Trix Rabbit", "Charlie the Tuna", "Keebler Elves",
      "Stubble Trouble (own Oscar-nominated short)"
    ],
    "format_deals": [],
    "platform_relationships": [],
    "why_fit": "THE American brand-character craft house, and a direct partner for the TVF brand/ad lane. The homepage explicitly says they are exploring AI-generated animation, gaming and immersive entertainment -- a pre-warmed door for The Viral Labs.",
    "scoring_inputs": {
      "genre_fit": 0,
      "distribution_relationship": 0,
      "right_size": 1,
      "collaboration_openness": 0.5,
      "client_work_dominance": 1,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 5",
      "key_contact": "Sean Henry - President & Executive Producer; Wayne Brejcha - Chairman & Creative Director",
      "published_email": "info@calabashanimation.com; sean@calabashanimation.com (Chicago Creative Directory)",
      "phone": "+1 312-243-3433",
      "ownership": "Founders sold to two veteran staffers in 2004 -- employee-owners; no outside investors",
      "revenue_estimate": "Not published; boutique scale -- graded CLEAN FIT",
      "caveats": "IMPORTANT: the contact page states they do NOT accept unsolicited material or proposals -- frame outreach as a production/partnership inquiry, never pitch IP cold."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 6. Chiodo Bros. Productions -- Burbank, CA
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Chiodo Bros. Productions',
  'chiodobros.com',
  'manual_p1',
  'https://chiodobros.com',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Burbank",
    "hq_state": "CA",
    "team_size_estimate": "Three brothers + per-project crews",
    "genres": ["stop-motion", "practical FX", "horror-comedy"],
    "notable_credits": [
      "Killer Klowns from Outer Space (own IP; Universal Halloween Horror Nights, video game)",
      "Alien Xmas (Netflix stop-motion special)",
      "Team America puppets", "Elf", "The Simpsons stop-motion segments"
    ],
    "format_deals": [],
    "platform_relationships": ["Netflix", "Disney", "Paramount", "Universal"],
    "why_fit": "The handcraft counterweight to an AI pipeline, with real franchise-building instinct shown by the Killer Klowns renaissance. Indian folklore in handmade puppet form is a natural pitch; Stephen teaches at CalArts.",
    "scoring_inputs": {
      "genre_fit": 0.5,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 0.5,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 6",
      "key_contact": "Edward Chiodo - Co-chairman & Head of Production (runs new business); Stephen Chiodo - Director; Charles Chiodo - Art lead",
      "published_email": null,
      "phone": "+1 818-842-5656",
      "ownership": "Family-owned for 40+ years; no investors on record",
      "revenue_estimate": "Not published; family-studio scale -- graded CLEAN FIT",
      "caveats": "NO published email -- site contact form or phone only. Edward is the business door. Two addresses circulate (Burbank and San Fernando) -- confirm on first contact."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 7. Minnow Mountain -- Austin, TX
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Minnow Mountain',
  'minnowmountain.com',
  'manual_p1',
  'https://minnowmountain.com',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Austin",
    "hq_state": "TX",
    "team_size_estimate": "~6 core (RocketReach)",
    "genres": ["rotoscope animation", "adult animation", "slice-of-life"],
    "notable_credits": [
      "Undone S1-2 (Amazon)",
      "Apollo 10 1/2 (Netflix, Linklater)",
      "Tower (PBS, Emmy-winning)",
      "Critical Role title sequence"
    ],
    "format_deals": [],
    "platform_relationships": ["Amazon", "Netflix", "PBS"],
    "why_fit": "Arguably the most AI-relevant craft on the list: rotoscope IS human performance capture, the exact frontier a TVF/Viral Labs hybrid pipeline lives on. Their 2024 expansion into originals plus 2D services means they are actively seeking partners.",
    "scoring_inputs": {
      "genre_fit": 0.5,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 1,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 7",
      "key_contact": "Craig Staggs - Co-founder, Creative Lead & Director; Steph Swope - Co-founder & Producer",
      "published_email": "info@minnowmountain.com",
      "phone": null,
      "ownership": "Founder-owned LLC; no investors on record",
      "revenue_estimate": "~$10.4M/yr (RocketReach est.) -- graded BORDERLINE, est. far over $1M",
      "caveats": "REVENUE ESTIMATE LOOKS INFLATED: a 6-person core at $10.4M is implausible -- likely Undone/Apollo production budgets flowing through the LLC. Graded honestly per the method, so revenue_above_cap = 1 costs it 20 points. Reviewer may override at P3."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 8. Block & Tackle -- Long Island City, NY
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Block & Tackle',
  'blockandtackle.tv',
  'manual_p1',
  'https://blockandtackle.tv',
  'discovered',
  '{
    "subtype": "commercial_branded",
    "hq_city": "Long Island City",
    "hq_state": "NY",
    "team_size_estimate": "~6-11",
    "genres": ["main titles", "show packaging", "network branding"],
    "notable_credits": [
      "The Americans -- Paper Trail main title",
      "The 1619 Project (Emmy-nominated)"
    ],
    "format_deals": [],
    "platform_relationships": ["HBO", "FX", "ESPN", "Hulu", "Google"],
    "why_fit": "A premium title/packaging partner to give TVF originals international-grade wrapping. Deliberately style-agnostic, which makes them a ready collaborator for the multi-style treatments library.",
    "scoring_inputs": {
      "genre_fit": 0,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 0.5,
      "client_work_dominance": 1,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0.5,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 8",
      "key_contact": "Adam Gault - Partner & Creative Director; Ted Kotsaftis - Partner & Creative Director",
      "published_email": "info@blockandtackle.tv",
      "phone": "+1 347-848-0866",
      "ownership": "Partner-owned; no investors on record",
      "revenue_estimate": "Estimates CONFLICT: under $1M (Selling.com) vs $1M-5M (Salary.com / SignalHire) -- graded BORDERLINE, straddles the cap",
      "caveats": "Conflicting estimates are why revenue_above_cap is 0.5, not 1 -- the guidance reserves 1.0 for a CONFIRMED estimate above the cap. CAUTION: Crunchbase lists a wrong founder for this LLC -- trust the studio site and LinkedIn."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 9. Tandem Pictures -- New York, NY
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Tandem Pictures',
  'tandempictures.com',
  'manual_p1',
  'https://tandempictures.com',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "New York",
    "hq_state": "NY",
    "team_size_estimate": "Small core (~5-11)",
    "genres": ["indie film", "branded content"],
    "notable_credits": [
      "Run Amok (Sundance 2026)", "Black Bear", "The Surrogate",
      "Brand films for Amazon, Chase, Ford, Netflix, Cadillac"
    ],
    "format_deals": [],
    "platform_relationships": ["Amazon", "Netflix", "Chase", "Ford", "Cadillac"],
    "why_fit": "US indie co-production plus a festival pathway, with four Sundance premieres and a working brand-film arm -- a double door of features AND branded. The certified-green production playbook is exportable know-how for Indian productions.",
    "scoring_inputs": {
      "genre_fit": 0,
      "distribution_relationship": 0.5,
      "right_size": 1,
      "collaboration_openness": 0.5,
      "client_work_dominance": 0.5,
      "india_diaspora_affinity": 0,
      "revenue_above_cap": 0.5,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 9",
      "key_contact": "Julie Christeas - Founder & CEO; Jonathan Blitstein - COO & Co-owner",
      "published_email": "info@tandempictures.com (Careers, Press and All Other Inquiries)",
      "phone": null,
      "ownership": "Woman-owned & operated; repped by Circle of Confusion (representation, not investment); no PE/VC on record",
      "revenue_estimate": "Under $5M band (ZoomInfo); not published -- graded BORDERLINE, feature slate suggests near/above cap",
      "caveats": "Revenue genuinely unknown, only suggestive -- hence 0.5 rather than 1. Single inbox for everything: address it to Christeas or Blitstein by name."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- 10. Tonko House -- Berkeley, CA
--     The only row with international_ip_experience set -- see the header.
----------------------------------------------------------------------
insert into entities (segment_id, name, domain, source, source_url, status, metadata)
values (
  (select id from segments where slug = 'us-production-houses'),
  'Tonko House',
  'tonkohouse.com',
  'manual_p1',
  'https://tonkohouse.com',
  'discovered',
  '{
    "subtype": "film_tv_streaming",
    "hq_city": "Berkeley",
    "hq_state": "CA",
    "team_size_estimate": "~9 core (RocketReach); wider network ~18",
    "genres": ["folklore", "family animation"],
    "notable_credits": [
      "ONI: Thunder God Tale (Netflix, 2022)",
      "The Dam Keeper (Oscar-nominated short; feature in development)"
    ],
    "format_deals": [
      "ONI -- multi-studio Japan-US co-production with Megalis, Marza, Anima and Dwarf"
    ],
    "platform_relationships": ["Netflix", "First Second (publishing arm)"],
    "why_fit": "The folklore blueprint: ONI is national mythology done as premium family animation via international co-production -- the exact model a Samudra-Manthan-class Indian mythology project needs. Publishing arm gives built-in transmedia; they run their own festival and education arm.",
    "scoring_inputs": {
      "international_ip_experience": 1,
      "genre_fit": 0,
      "distribution_relationship": 1,
      "right_size": 1,
      "collaboration_openness": 1,
      "client_work_dominance": 0,
      "india_diaspora_affinity": 1,
      "revenue_above_cap": 1,
      "geography_signal": "us",
      "major_or_oversized_signal": false,
      "has_reachable_presence": true,
      "activity_signal": "active"
    },
    "p1_research": {
      "source_document": "20th-Aug_USProductionHouseLeads.xlsx, Target List row 10",
      "key_contact": "Robert Kondo - Co-founder & President; Daisuke Dice Tsutsumi - Co-founder & Creator; Kane Lee - Executive Producer",
      "published_email": null,
      "phone": null,
      "ownership": "Founder-owned by two ex-Pixar art directors; no investors on record",
      "revenue_estimate": "~$5M/yr (RocketReach est.) -- graded BORDERLINE, over $1M",
      "caveats": "Aspirational anchor of the set. Contact form only; founders and Kane Lee reachable via LinkedIn. india_diaspora_affinity = 1 on the strength of the Japan-US co-production and Japanese-American founder -- Asia ties, not India specifically."
    }
  }'::jsonb
);

----------------------------------------------------------------------
-- CONFIRM: 10 rows landed.
----------------------------------------------------------------------
select count(*) as p1_rows
from entities
where segment_id = (select id from segments where slug = 'us-production-houses')
  and source = 'manual_p1';
-- Expect 10.

-- Now run CHECK 2 and CHECK 3 in 04_insert_template.sql.
-- CHECK 2 must return ZERO rows before you move to P2.
