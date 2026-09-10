-- 03D_SEGMENT_LCX_CLIPPING.SQL
-- Segment config row for 'lcx-clipping'. GENERATED from config/segment.lcx-clipping.json
-- by tools/gen_segment_sql.py; edit the JSON, regenerate, never hand-edit this
-- literal. Idempotent: an existing row is updated to the file's content.
insert into segments (slug, name, entity_type, config)
values (
  'lcx-clipping',
  'LCX Clipping -- creators and podcasters with a back catalogue',
  'creator_show',
  '{
  "entity_type": "creator_show",
  "weekly_target": 150,
  "batch_size": 60,
  "score_threshold_review": 25,
  "score_threshold_priority": 45,
  "target_contact_roles": [
    "Host",
    "Co-Host",
    "Producer",
    "Executive Producer",
    "Founder",
    "Creator",
    "Head of Content",
    "Marketing"
  ],
  "geography": {
    "allowed_countries": [],
    "priority_countries": [
      "US"
    ],
    "disallowed_countries": [
      "CA",
      "DE",
      "AT",
      "IT"
    ],
    "guidance": "Everywhere on the planet, the United States first (owner, 2026-09-09). An empty allowed list means every country except the disallowed set; the priority list earns the us_priority bonus and gets six searches in ten. Disallowed by design: Canada (CASL requires consent), Germany and Austria (UWG: consent for B2B email), Italy (consent). The connectors mark a lead ''disallowed'' only on confirmed evidence -- a channel''s country field, a feed''s language REGION suffix (a bare language is not a country), Wikidata''s country -- and blank always passes (Invariant 1)."
  },
  "languages": {
    "full": [
      "en",
      "hi"
    ],
    "partial": [
      "es",
      "pt",
      "ta",
      "te",
      "mr",
      "bn",
      "gu",
      "pa",
      "ur",
      "ar"
    ],
    "guidance": "Clipping quality depends on editors understanding the content. English and Hindi are full credit; the partial list is where LCX can work with a native reviewer. Anything else scores 0 on language_match but is not gated out."
  },
  "rubric": [
    {
      "key": "archive_size",
      "label": "Deep back catalogue of long-form (100+ episodes or long videos)",
      "points": 20,
      "input": "metadata.scoring_inputs.archive_size",
      "guidance": "1.0 at 100+ long-form items, 0.5 at 40-99, 0 below 40. From the feed''s episode count (Apple''s trackCount when the feed is capped) or the channel''s long-video count. The archive is the raw material; no archive, nothing to clip. LOWERED 2026-09-09 from 25 to 20 (see audience_band)."
    },
    {
      "key": "cadence",
      "label": "Publishes weekly or better and is active in the last 90 days",
      "points": 10,
      "input": "metadata.scoring_inputs.cadence",
      "guidance": "1.0 at 4+ items a month over the last 90 days, 0.5 at 2-3 a month, 0 below. A show that still publishes needs clips every week; that is the retainer. LOWERED 2026-09-09 from 15 to 10 (see audience_band)."
    },
    {
      "key": "shorts_gap",
      "label": "Shorts gap: long-form output with few or no shorts",
      "points": 25,
      "input": "metadata.scoring_inputs.shorts_gap",
      "guidance": "1.0 when under 10% of the last 50 uploads are shorts, 0.5 at 10-30%, 0 at 30%+ (they already clip). Only assessable when a YouTube channel is known -- for an audio-only podcast it stays unassessed, which is not evidence either way. This number IS the pitch: ''you have 214 episodes and 3 shorts''."
    },
    {
      "key": "audience_band",
      "label": "Audience in the band that can pay but has no in-house team (10k-1M subscribers)",
      "points": 25,
      "input": "metadata.scoring_inputs.audience_band",
      "guidance": "1.0 at 10k-1M subscribers, 0.5 at 3k-10k or 1M-3M, 0 outside. Below the band there is no budget; above it there is usually an editor on staff. Unassessed when no channel is known. RAISED 2026-09-09 from 15 to 25 after the first live run: catalogue and cadence alone let a 271-subscriber show outrank the band, and the audience is what decides whether there is a budget."
    },
    {
      "key": "monetization_signals",
      "label": "Evidence of a budget: sponsors, Patreon, merch, courses, a paid newsletter",
      "points": 15,
      "input": "metadata.scoring_inputs.monetization_signals",
      "guidance": "Regex over the feed description and recent episode notes (or channel and video descriptions): sponsor reads, promo codes, Patreon, merch, membership, course, newsletter. 1.0 at two or more distinct signals, 0.5 at one, 0 when we looked and found none."
    },
    {
      "key": "reachable_contact",
      "label": "A business address to write to",
      "points": 10,
      "input": "metadata.scoring_inputs.reachable_contact",
      "guidance": "Auto-set by the engine: 1.0 for an email the show published itself (feed owner address, not a hosting provider''s), 0.5 for a website with a contact route, 0 for neither."
    },
    {
      "key": "language_match",
      "label": "Content in a language LCX edits well",
      "points": 5,
      "input": "metadata.scoring_inputs.language_match",
      "guidance": "1.0 for English or Hindi, 0.5 for the partial list, 0 otherwise. Small weight on purpose: it shapes the order, it does not veto."
    }
  ],
  "score_modifiers": [
    {
      "key": "network_owned",
      "label": "PENALTY: produced by a network or studio with its own post team",
      "max_penalty": -20,
      "input": "metadata.scoring_inputs.network_owned",
      "guidance": "1.0 when the feed''s author or owner is a known network (iHeart, Wondery, NPR, Spotify Studios and the like) or the channel is a media brand''s. They have editors; the pitch is a different one. Soft subtractor; the biggest names are also hard-gated below."
    },
    {
      "key": "video_first",
      "label": "BONUS: the show is video-first on YouTube",
      "max_bonus": 6,
      "input": "metadata.scoring_inputs.video_first",
      "guidance": "1.0 when a YouTube channel with long-form uploads is confirmed. Video-native shows are the easiest to clip well and the quickest to see results."
    },
    {
      "key": "oversized_audience",
      "label": "PENALTY: audience between 2M and 5M subscribers, probably staffed",
      "max_penalty": -20,
      "input": "metadata.scoring_inputs.oversized_audience",
      "guidance": "1.0 when subscribers are above 2M (the gate takes over above 5M). Keeps big-but-not-huge channels in the pool, ranked below the band where the pitch lands."
    },
    {
      "key": "us_priority",
      "label": "BONUS: based in the United States, the segment''s first market",
      "max_bonus": 8,
      "input": "metadata.scoring_inputs.us_priority",
      "guidance": "1.0 when the country is confirmed US (channel country, feed language region, Wikidata, or the TVF pool), 0 for any other confirmed country, absent when unknown. Eight points is enough to rank a US show above an otherwise identical one elsewhere, not enough to lift a weak lead into the band."
    }
  ],
  "gates": [
    {
      "key": "country_allowed",
      "label": "Must not be in a country where cold business email is off limits",
      "input": "metadata.scoring_inputs.country_signal",
      "exclude_when": "disallowed",
      "guidance": "Fires ONLY on confirmed evidence of a disallowed country (see geography.disallowed_countries). Blank/unknown always passes through."
    },
    {
      "key": "is_active",
      "label": "Show or channel must be currently active, not dormant",
      "input": "metadata.scoring_inputs.activity_signal",
      "exclude_when": "confirmed_dormant",
      "guidance": "Fires ONLY when the latest episode or upload is more than 180 days old. Blank/unknown always passes through."
    },
    {
      "key": "not_excluded_category",
      "label": "Not children''s content or music",
      "input": "metadata.scoring_inputs.excluded_category_signal",
      "exclude_when": true,
      "guidance": "Kids & Family (COPPA exposure, brand risk) and Music (licensing makes clips a liability) are out. Set from Apple genres or YouTube topic categories. Blank passes."
    },
    {
      "key": "usable_first_party_presence",
      "label": "Must have SOME way to be reached: email, website, or channel",
      "input": "metadata.scoring_inputs.has_reachable_presence",
      "exclude_when": false,
      "guidance": "Fires only on an explicit false: no email, no website, no channel. Blank passes."
    },
    {
      "key": "not_major_network",
      "label": "Exclude the biggest podcast networks and broadcasters outright",
      "input": "metadata.scoring_inputs.major_network_signal",
      "exclude_when": true,
      "guidance": "Name match against major_networks. These are not customers for a clipping desk; they are the competition''s customers or have their own. Blank passes."
    },
    {
      "key": "not_oversized",
      "label": "Exclude channels far beyond the band (over 5M subscribers)",
      "input": "metadata.scoring_inputs.oversized_signal",
      "exclude_when": true,
      "guidance": "First live run (2026-09-09): a 40M-subscriber gaming channel scored 92 because audience_band only withholds 15 points. Channels that size have a post team and a procurement process; they are not clipping customers. Set from the channel''s subscriber count. Blank passes."
    }
  ],
  "review_checklist": [
    {
      "key": "independent_show",
      "label": "Is this an independent show (host- or small-studio-owned), not a network, broadcaster, or brand production?",
      "guidance": "Networks and brands have post teams and procurement. The feed author, the website footer, and the channel''s About page usually settle it in thirty seconds."
    },
    {
      "key": "clip_friendly_content",
      "label": "Is the content clip-friendly: talk, interview, commentary, education, comedy, sport analysis, not music or kids?",
      "guidance": "Clips need a speaking moment with a hook. Ambient, music, or children''s content does not produce them and carries licensing or COPPA risk."
    },
    {
      "key": "real_business_contact",
      "label": "Does the contact look like the host''s or producer''s real business address, not a hosting-provider or agency inbox?",
      "guidance": "Feeds sometimes carry the hosting platform''s address or an agency''s. Writing there wastes the one touch. Prefer the address on the show''s own site when they differ."
    }
  ],
  "podcast_discovery": {
    "countries": [
      "US",
      "GB",
      "IN",
      "AU",
      "NZ",
      "IE",
      "SG",
      "PH",
      "ZA",
      "AE",
      "NG",
      "MX",
      "BR",
      "FR",
      "NL",
      "SE"
    ],
    "min_track_count": 40,
    "excluded_genres": [
      "Kids & Family",
      "Music",
      "Stories for Kids",
      "Education for Kids",
      "Music Commentary",
      "Music History",
      "Music Interviews"
    ],
    "queries": [
      {
        "term": "interview podcast",
        "genre_hint": "society"
      },
      {
        "term": "business podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "entrepreneurship podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "startup founders podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "marketing podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "sales podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "real estate investing podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "personal finance podcast",
        "genre_id": 1321,
        "genre_hint": "finance"
      },
      {
        "term": "investing podcast",
        "genre_id": 1321,
        "genre_hint": "finance"
      },
      {
        "term": "comedy podcast",
        "genre_id": 1303,
        "genre_hint": "comedy"
      },
      {
        "term": "improv comedy podcast",
        "genre_id": 1303,
        "genre_hint": "comedy"
      },
      {
        "term": "self improvement podcast",
        "genre_id": 1304,
        "genre_hint": "education"
      },
      {
        "term": "how to podcast",
        "genre_id": 1304,
        "genre_hint": "education"
      },
      {
        "term": "language learning podcast",
        "genre_id": 1304,
        "genre_hint": "education"
      },
      {
        "term": "technology podcast",
        "genre_id": 1318,
        "genre_hint": "technology"
      },
      {
        "term": "artificial intelligence podcast",
        "genre_id": 1318,
        "genre_hint": "technology"
      },
      {
        "term": "software engineering podcast",
        "genre_id": 1318,
        "genre_hint": "technology"
      },
      {
        "term": "health and wellness podcast",
        "genre_id": 1512,
        "genre_hint": "health"
      },
      {
        "term": "fitness podcast",
        "genre_id": 1512,
        "genre_hint": "health"
      },
      {
        "term": "mental health podcast",
        "genre_id": 1512,
        "genre_hint": "health"
      },
      {
        "term": "nutrition podcast",
        "genre_id": 1512,
        "genre_hint": "health"
      },
      {
        "term": "true crime podcast",
        "genre_id": 1488,
        "genre_hint": "true_crime"
      },
      {
        "term": "history podcast",
        "genre_id": 1487,
        "genre_hint": "history"
      },
      {
        "term": "science podcast",
        "genre_id": 1533,
        "genre_hint": "science"
      },
      {
        "term": "sports talk podcast",
        "genre_id": 1545,
        "genre_hint": "sports"
      },
      {
        "term": "football podcast",
        "genre_id": 1545,
        "genre_hint": "sports"
      },
      {
        "term": "cricket podcast",
        "genre_id": 1545,
        "genre_hint": "sports"
      },
      {
        "term": "basketball podcast",
        "genre_id": 1545,
        "genre_hint": "sports"
      },
      {
        "term": "film podcast",
        "genre_id": 1309,
        "genre_hint": "tv_film"
      },
      {
        "term": "television recap podcast",
        "genre_id": 1309,
        "genre_hint": "tv_film"
      },
      {
        "term": "gaming podcast",
        "genre_id": 1502,
        "genre_hint": "leisure"
      },
      {
        "term": "parenting podcast",
        "genre_id": 1324,
        "genre_hint": "society"
      },
      {
        "term": "relationships podcast",
        "genre_id": 1324,
        "genre_hint": "society"
      },
      {
        "term": "culture podcast",
        "genre_id": 1324,
        "genre_hint": "society"
      },
      {
        "term": "leadership podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "creator economy podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "career advice podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "news commentary podcast",
        "genre_id": 1489,
        "genre_hint": "news"
      },
      {
        "term": "politics podcast",
        "genre_id": 1489,
        "genre_hint": "news"
      },
      {
        "term": "Hindi podcast",
        "genre_hint": "india"
      },
      {
        "term": "India business podcast",
        "genre_id": 1321,
        "genre_hint": "india"
      },
      {
        "term": "Bollywood podcast",
        "genre_id": 1309,
        "genre_hint": "india"
      },
      {
        "term": "UPSC podcast",
        "genre_id": 1304,
        "genre_hint": "india"
      },
      {
        "term": "startup India podcast",
        "genre_id": 1321,
        "genre_hint": "india"
      },
      {
        "term": "motivational podcast",
        "genre_id": 1304,
        "genre_hint": "education"
      },
      {
        "term": "spirituality podcast",
        "genre_id": 1314,
        "genre_hint": "spirituality"
      },
      {
        "term": "law podcast",
        "genre_id": 1321,
        "genre_hint": "business"
      },
      {
        "term": "medical podcast",
        "genre_id": 1512,
        "genre_hint": "health"
      },
      {
        "term": "design podcast",
        "genre_id": 1301,
        "genre_hint": "arts"
      },
      {
        "term": "photography podcast",
        "genre_id": 1301,
        "genre_hint": "arts"
      }
    ],
    "guidance": "Apple''s public podcast search needs no key and returns up to 200 shows per term and store country, with the feed URL and the episode count. The feed itself carries what we score on and the business address the show published on purpose. Terms are broad on purpose: the rubric, not the query, decides who ranks."
  },
  "youtube_channel_discovery": {
    "regions": [
      {
        "code": "US",
        "language": "en"
      },
      {
        "code": "US",
        "language": "es"
      },
      {
        "code": "GB",
        "language": "en"
      },
      {
        "code": "IN",
        "language": "en"
      },
      {
        "code": "IN",
        "language": "hi"
      },
      {
        "code": "AU",
        "language": "en"
      },
      {
        "code": "NZ",
        "language": "en"
      },
      {
        "code": "IE",
        "language": "en"
      },
      {
        "code": "SG",
        "language": "en"
      },
      {
        "code": "PH",
        "language": "en"
      },
      {
        "code": "ZA",
        "language": "en"
      },
      {
        "code": "NG",
        "language": "en"
      },
      {
        "code": "AE",
        "language": "en"
      },
      {
        "code": "MX",
        "language": "es"
      },
      {
        "code": "BR",
        "language": "pt"
      },
      {
        "code": "FR",
        "language": "fr"
      }
    ],
    "min_subscribers": 3000,
    "min_videos": 40,
    "min_recent_long": 10,
    "shorts_max_seconds": 180,
    "long_min_seconds": 480,
    "queries": [
      {
        "query": "podcast full episode",
        "genre_hint": "podcast"
      },
      {
        "query": "interview show",
        "genre_hint": "podcast"
      },
      {
        "query": "talk show channel",
        "genre_hint": "talk"
      },
      {
        "query": "founder interview",
        "genre_hint": "business"
      },
      {
        "query": "business explained",
        "genre_hint": "business"
      },
      {
        "query": "personal finance explained",
        "genre_hint": "finance"
      },
      {
        "query": "stock market analysis",
        "genre_hint": "finance"
      },
      {
        "query": "technology review long",
        "genre_hint": "technology"
      },
      {
        "query": "self improvement talk",
        "genre_hint": "education"
      },
      {
        "query": "lecture series",
        "genre_hint": "education"
      },
      {
        "query": "cricket analysis show",
        "genre_hint": "sports"
      },
      {
        "query": "sports debate show",
        "genre_hint": "sports"
      },
      {
        "query": "comedy podcast episode",
        "genre_hint": "comedy"
      },
      {
        "query": "true crime documentary channel",
        "genre_hint": "true_crime"
      },
      {
        "query": "history documentary channel",
        "genre_hint": "history"
      },
      {
        "query": "UPSC lecture",
        "genre_hint": "india"
      },
      {
        "query": "Hindi podcast",
        "genre_hint": "india"
      },
      {
        "query": "startup India talk",
        "genre_hint": "india"
      },
      {
        "query": "health podcast doctor",
        "genre_hint": "health"
      },
      {
        "query": "webinar recording",
        "genre_hint": "b2b"
      },
      {
        "query": "production company showreel",
        "genre_hint": "production_house"
      },
      {
        "query": "production house web series",
        "genre_hint": "production_house"
      },
      {
        "query": "documentary production company",
        "genre_hint": "production_house"
      },
      {
        "query": "video production studio",
        "genre_hint": "production_house"
      },
      {
        "query": "film studio behind the scenes",
        "genre_hint": "production_house"
      },
      {
        "query": "media company original series",
        "genre_hint": "production_house"
      },
      {
        "query": "animation studio series",
        "genre_hint": "production_house"
      },
      {
        "query": "podcast network",
        "genre_hint": "network"
      },
      {
        "query": "regional news channel",
        "genre_hint": "publisher"
      },
      {
        "query": "conference talks channel",
        "genre_hint": "b2b"
      }
    ],
    "guidance": "A channel search costs 100 quota units, so a run does at most a few dozen searches; the channel statistics and the last 50 uploads cost 3 units per channel. The shorts gap, cadence and audience come straight from the API -- the pitch sentence is a fact. Long-form starts at eight minutes: a ten-minute explainer clips as well as an hour-long interview, and a twenty-minute floor threw away most education and commentary channels on the first live run (2026-09-09)."
  },
  "hosting_providers": [
    "anchor.fm",
    "spotify.com",
    "spotifyforpodcasters.com",
    "podcasters.spotify.com",
    "buzzsprout.com",
    "libsyn.com",
    "podbean.com",
    "transistor.fm",
    "simplecast.com",
    "megaphone.fm",
    "acast.com",
    "captivate.fm",
    "redcircle.com",
    "spreaker.com",
    "audioboom.com",
    "rss.com",
    "soundcloud.com",
    "blubrry.com",
    "omny.fm",
    "omnycontent.com",
    "art19.com",
    "podcastone.com",
    "whooshkaa.com",
    "podigee.io",
    "ausha.co",
    "pinecast.com",
    "fireside.fm",
    "zencastr.com",
    "podcasts.apple.com",
    "apple.co",
    "youtube.com",
    "youtu.be",
    "linktr.ee",
    "beacons.ai",
    "bio.link",
    "linkin.bio",
    "kuku.fm",
    "hubhopper.com",
    "castos.com",
    "podomatic.com",
    "ivoox.com",
    "audible.com",
    "amazon.com",
    "google.com",
    "podcasts.google.com",
    "feeds.feedburner.com",
    "feedburner.com",
    "substack.com",
    "wixsite.com",
    "squarespace.com",
    "wordpress.com",
    "medium.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "patreon.com"
  ],
  "major_networks": [
    "iheartradio",
    "iheartmedia",
    "iheartpodcast",
    "wondery",
    "npr",
    "bbc",
    "spotify studios",
    "gimlet",
    "the ringer",
    "barstool",
    "audacy",
    "cumulus",
    "siriusxm",
    "stitcher",
    "vox media",
    "new york times",
    "the new york times",
    "crooked media",
    "dear media",
    "kast media",
    "podcastone",
    "sony music",
    "amazon music",
    "audible",
    "qcode",
    "lemonada",
    "pushkin",
    "slate",
    "headgum",
    "earwolf",
    "team coco",
    "studio71",
    "cbc",
    "abc news",
    "cnn",
    "fox news",
    "espn",
    "nbc",
    "cbs",
    "msnbc",
    "the economist",
    "the guardian",
    "bloomberg",
    "wall street journal",
    "the athletic",
    "times internet",
    "ndtv",
    "india today",
    "zee",
    "star",
    "red fm",
    "radio mirchi",
    "spotify"
  ],
  "monetization_patterns": [
    "patreon",
    "sponsor",
    "sponsored by",
    "brought to you by",
    "promo code",
    "use code",
    "discount code",
    "merch",
    "newsletter",
    "substack",
    "buymeacoffee",
    "buy me a coffee",
    "ko-fi",
    "membership",
    "members only",
    "masterclass",
    "course",
    "affiliate",
    "shop the",
    "support the show",
    "become a supporter",
    "premium episodes",
    "bonus episodes",
    "join the community",
    "book a call",
    "consulting"
  ],
  "metadata_fields": [
    "podcast_feed",
    "youtube_channel",
    "why_fit",
    "scoring_inputs",
    "host",
    "kind"
  ],
  "sources": [
    {
      "slug": "apple_podcasts",
      "name": "Apple Podcasts search + the show''s own RSS feed",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_podcasts.py -- keyless. Search terms x store countries -> feed URLs -> feed parsed for cadence, catalogue, monetization signals, YouTube link and the published contact."
    },
    {
      "slug": "youtube_api",
      "name": "YouTube Data API v3 (channel search + statistics + last 50 uploads)",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_youtube_channels.py and the YouTube half of tools/enrich_clipping.py. Needs YOUTUBE_API_KEY. Shorts gap, cadence, audience, monetization hits."
    },
    {
      "slug": "wikidata_channels",
      "name": "Wikidata production companies with a YouTube channel",
      "kind": "api",
      "phase": 2,
      "detail": "tools/discover_wikidata_channels.py -- SPARQL per class, then the same 3-unit channel profile. Worldwide, US first. kind=production_house."
    },
    {
      "slug": "tvf_pool",
      "name": "TVF''s US production-house pool, carried over with contacts",
      "kind": "import",
      "phase": 2,
      "detail": "tools/import_pool.py --from us-production-houses. Name, website, contacts and origin; the enrichment pass finds the YouTube channel from the website."
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
      "lcx clipping"
    ],
    "guidance": "TVF and LCX properties never enter the pool. Same conservative matching as the TVF segment: exact host or subdomain, whole-word name patterns."
  },
  "enrichment": {
    "provider": "feed_and_youtube",
    "contact_method": "feed_owner_email_then_site_scrape",
    "email_verifier": "none_yet",
    "guidance": "The contact usually arrives with the discovery record (the feed''s owner address). tools/enrich_clipping.py lifts it into contacts, adds YouTube evidence for shows with a channel, and computes the scoring inputs. The site-scrape pass (enrich_contacts) still runs for shows with a website and no address."
  },
  "ui": {
    "project_name": "LCX Clipping",
    "project_type": "Sales segment",
    "key_prefix": "LCX",
    "board_title": "Clipping leads",
    "list_title": "Creators and studios",
    "entity_label": "show",
    "sidebar_note": "You''re in the <strong>LCX clipping</strong> segment: creators, podcasters and production houses with a back catalogue and no shorts, worldwide, US first. Discovery, enrichment and drafting all run here.",
    "card_fields": [
      {
        "path": "metadata.podcast_feed.episode_count",
        "label": "episodes",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.subscribers",
        "label": "subs",
        "format": "compact"
      },
      {
        "path": "metadata.youtube_channel.recent.shorts_share",
        "label": "shorts",
        "format": "percent"
      },
      {
        "path": "metadata.podcast_feed.cadence_per_month",
        "label": "/mo",
        "format": "number1"
      }
    ],
    "details": [
      {
        "path": "host_name",
        "label": "Host",
        "format": "text"
      },
      {
        "path": "metadata.kind",
        "label": "Kind",
        "format": "text"
      },
      {
        "path": "metadata.podcast_feed.feed_url",
        "label": "Feed",
        "format": "link"
      },
      {
        "path": "metadata.youtube_channel.url",
        "label": "Channel",
        "format": "link"
      },
      {
        "path": "metadata.podcast_feed.language",
        "label": "Language",
        "format": "text"
      },
      {
        "path": "metadata.podcast_feed.categories",
        "label": "Categories",
        "format": "list"
      },
      {
        "path": "metadata.podcast_feed.hosting_provider",
        "label": "Hosted on",
        "format": "text"
      }
    ],
    "evidence": [
      {
        "path": "metadata.podcast_feed.episode_count",
        "label": "Episodes in the catalogue",
        "format": "number"
      },
      {
        "path": "metadata.podcast_feed.cadence_per_month",
        "label": "Episodes a month, last 90 days",
        "format": "number1"
      },
      {
        "path": "metadata.podcast_feed.avg_duration_min",
        "label": "Average episode length (min)",
        "format": "number"
      },
      {
        "path": "metadata.podcast_feed.latest_at",
        "label": "Latest episode",
        "format": "date"
      },
      {
        "path": "metadata.youtube_channel.subscribers",
        "label": "YouTube subscribers",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.video_count",
        "label": "Videos on the channel",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.recent.long_count",
        "label": "Long videos among the last 50 uploads",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.recent.shorts_count",
        "label": "Shorts among the last 50 uploads",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.recent.avg_long_minutes",
        "label": "Average long video (min)",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.recent.uploads_per_month",
        "label": "Uploads a month",
        "format": "number1"
      },
      {
        "path": "metadata.podcast_feed.monetization_hits",
        "label": "Budget signals in the show notes",
        "format": "list"
      },
      {
        "path": "metadata.youtube_channel.monetization_hits",
        "label": "Budget signals on the channel",
        "format": "list"
      }
    ],
    "lead_first": "person",
    "summary_label": "Host · show",
    "entity_plural": "shows"
  },
  "outreach": {
    "sender": {
      "name": "SET_ME e.g. the LCX clipping lead",
      "title": "Clipping desk, LCX",
      "postal_address": "SET_ME street address for the email footer (CAN-SPAM)",
      "email_env": "GMAIL_SENDER_ADDRESS_LCX_CLIPPING",
      "guidance": "sender.name and postal_address MUST be set before the first send. The sending addresses come from the environment variables named in outreach.mailboxes, never from config."
    },
    "daily_send_cap": 120,
    "hook_style": "clipping",
    "neutral_hook": "We''ve been mapping shows with a deep back catalogue and almost no short-form, and {{company}} came up.",
    "templates": [
      {
        "key": "clipping_intro_v1",
        "subject": "{{company}}: three shorts from your latest episode?",
        "body": "Hi {{greeting_name}},\n\n{{hook}}\n\nI run the clipping desk at LCX. We turn long episodes into short vertical clips -- the hook, the captions, the reframing -- and deliver within 48 hours of each new episode, so every release also gets ten shorts working for it on YouTube, Instagram and TikTok. Our editors cut; you approve.\n\nRather than describe it: reply \"yes\" and we''ll clip your latest episode into three shorts, free, so you can judge the quality before anything else is discussed.\n\n{{sender_name}}\n{{sender_title}}\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
        "guidance": "First touch for creators and podcasters. {{hook}} is one sentence of THEIR numbers -- episodes, cadence, length, shorts count -- built by the draft command from the feed and channel evidence, so it is true by construction. Greeting: a person''s first name when the engine found one (metadata.host at high or medium confidence); otherwise ''there''. Never the show''s name."
      },
      {
        "key": "clipping_studio_v1",
        "when": {
          "metadata.kind": "production_house"
        },
        "subject": "{{company}}: shorts from your archive, three on us",
        "body": "Hi {{greeting_name}},\n\n{{hook}}\n\nI run the clipping desk at LCX. We turn long-form -- episodes, trailers, behind-the-scenes, interviews -- into short vertical clips with the hook, the captions and the reframing done, delivered within 48 hours, so every release keeps working on YouTube, Instagram and TikTok long after the premiere. Our editors cut; your team approves.\n\nRather than describe it: reply \"yes\" and we''ll clip one piece from your channel into three shorts, free, so you can judge the quality first.\n\n{{sender_name}}\n{{sender_title}}\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
        "guidance": "Production houses and studios (metadata.kind = production_house, set by the Wikidata connector and the TVF pool import). Same evidence hook, studio wording: ''your archive'', ''your team approves''. Picked automatically by the draft command through the `when` condition."
      },
      {
        "key": "clipping_followup_1",
        "kind": "follow_up",
        "subject": "Re: {{opener_subject}}",
        "body": "Hi {{greeting_name}},\n\nFloating this back up in case it got buried. The offer stands: reply \"yes\" and we''ll cut three shorts from one of your recent long videos or episodes, free, so you can judge the quality before anything else is discussed.\n\n{{sender_name}}\n{{sender_title}}\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
        "guidance": "Follow-up 1, sent in the opener''s thread four days after it if nobody replied. Short on purpose."
      },
      {
        "key": "clipping_followup_2",
        "kind": "follow_up",
        "subject": "Re: {{opener_subject}}",
        "body": "Hi {{greeting_name}},\n\nLast note from me on this. If short-form from your back catalogue is ever on the list, reply here and the three free shorts are yours. Otherwise I''ll leave you be.\n\n{{sender_name}}\n{{sender_title}}\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
        "guidance": "Follow-up 2, the last one: seven days after follow-up 1. After this the thread is closed for good."
      }
    ],
    "guidance": "Everything outbound is drafted -> human-approved -> sent, in that order. Approval may be one draft at a time or a spot-checked batch (batch_approval). daily_send_cap is a hard daily ceiling per mailbox and counts follow-ups. One thread per company, enforced by the database: an opener, then at most the follow_ups steps, stopped by any reply. Templates carry an optional `when` condition on metadata; follow-up templates are marked kind=follow_up and are never used as openers. greeting_fallback is what ''Hi ...'' says when no person is known.",
    "greeting_fallback": "there",
    "follow_ups": {
      "enabled": true,
      "steps": [
        {
          "step": 1,
          "after_days": 4,
          "template": "clipping_followup_1"
        },
        {
          "step": 2,
          "after_days": 7,
          "template": "clipping_followup_2"
        }
      ],
      "guidance": "Owner decision 2026-09-10. One thread per company: the opener plus these steps, in the same Gmail thread, each counted from the previous email''s send. Any reply pauses the thread at once; a reply triaged as an auto-reply lets it resume, anything else ends it. A person can stop a thread from the message dialog. Follow-ups are drafts and need approval like any email. The database caps a thread at three follow-ups and refuses to send one after a reply (sql/23)."
    },
    "batch_approval": {
      "enabled": true,
      "sample_min": 3,
      "sample_fraction": 0.1,
      "max_batch": 100,
      "guidance": "Owner decision 2026-09-10. Templated drafts may be approved together: select them in Drafts, read the random sample the server draws (at least sample_min, or sample_fraction of the batch, whichever is more), tick each, approve. Every draft is checked first (no {{placeholder}}, no SET_ME, a valid address, a sendable company). The approver''s name, the batch and the sample are recorded."
    },
    "mailboxes": [
      {
        "key": "main",
        "email_env": "GMAIL_SENDER_ADDRESS_LCX_CLIPPING",
        "daily_cap": 40,
        "warmup": {
          "start_cap": 10,
          "step": 5,
          "every_days": 2
        }
      },
      {
        "key": "second",
        "email_env": "GMAIL_SENDER_ADDRESS_LCX_2",
        "daily_cap": 40,
        "warmup": {
          "start_cap": 10,
          "step": 5,
          "every_days": 2
        }
      },
      {
        "key": "third",
        "email_env": "GMAIL_SENDER_ADDRESS_LCX_3",
        "daily_cap": 40,
        "warmup": {
          "start_cap": 10,
          "step": 5,
          "every_days": 2
        }
      }
    ],
    "mailbox_guidance": "Owner decision 2026-09-10. Openers are spread across the connected mailboxes, each to the one with the most room left today; follow-ups always leave from the mailbox that sent the opener (sql/24 enforces it). A mailbox takes part once its address is in .env under email_env and `outreach.py auth --mailbox <key>` has been run on the sending machine; the others are skipped, never guessed. Warm-up: start_cap a day from the mailbox''s first send, +step every every_days, up to daily_cap (10 -> 40 over twelve days). Use addresses on a sending domain of LCX''s own, not the main company domain, so a bad week cannot hurt everyday mail. The signature name is shared, so the mailboxes should belong to the same person or desk. daily_send_cap is the ceiling across all of them."
  },
  "schedule": [
    {
      "name": "weekly refresh",
      "pipeline": "weekly_refresh",
      "dow": 2,
      "hour": 2,
      "minute": 0,
      "enabled": true
    },
    {
      "name": "daily follow-ups",
      "pipeline": "followups",
      "dow": "*",
      "hour": 3,
      "minute": 30,
      "enabled": true
    }
  ],
  "pipelines": {
    "weekly_refresh": [
      "discover_podcasts",
      "discover_youtube",
      "discover_wikidata_channels",
      "promote_chain",
      "enrich_clipping",
      "enrich_contacts",
      "promote_chain"
    ],
    "rescore": [
      "promote_chain"
    ],
    "followups": [
      "draft_followups"
    ]
  },
  "wikidata_channel_discovery": {
    "entity_classes": [
      {
        "qid": "Q1762059",
        "label": "film production company"
      },
      {
        "qid": "Q10689397",
        "label": "television production company"
      },
      {
        "qid": "Q1107679",
        "label": "animation studio"
      }
    ],
    "per_class_limit": 800,
    "min_subscribers": 1000,
    "min_videos": 30,
    "min_recent_long": 8,
    "guidance": "tools/discover_wikidata_channels.py. Direct instances of each class that list a YouTube channel (P2397), with website (P856) and country (P17 -> ISO). One query per class; subclass walks time out. Priority countries are profiled first. Floors are lower than for creators because a production house with a modest channel and a deep archive is still a clipping customer."
  },
  "video_first_min_recent_long": 8
}'::jsonb
)
on conflict (slug) do update
  set name = excluded.name,
      entity_type = excluded.entity_type,
      config = excluded.config,
      updated_at = now();

select slug, entity_type,
       jsonb_array_length(config->'rubric')  as rubric_criteria,
       jsonb_array_length(config->'gates')   as gates,
       config->>'score_threshold_review'     as review_at,
       config->>'score_threshold_priority'   as priority_at
from segments order by slug;
