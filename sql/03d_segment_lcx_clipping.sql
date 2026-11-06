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
      "label": "Established audience, with no upper subscriber limit",
      "points": 25,
      "input": "metadata.scoring_inputs.audience_band",
      "guidance": "1.0 at 10k+ subscribers with no ceiling; 0.5 at 3k-10k; 0 below. Audience size alone never excludes a larger channel. Unknown remains unassessed."
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
      "label": "Not children''s content or music-only performances",
      "input": "metadata.scoring_inputs.excluded_category_signal",
      "exclude_when": true,
      "guidance": "Children''s content and music-only performance channels remain excluded. Music teaching, production tutorials, theory, business and original music discussion qualify. Genre alone does not exclude a music educator."
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
      "Stories for Kids",
      "Education for Kids"
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
        "query": "filmmaking education online course",
        "genre_hint": "filmmaking",
        "offer_priority": true
      },
      {
        "query": "cinematography lighting course",
        "genre_hint": "filmmaking",
        "offer_priority": true
      },
      {
        "query": "video editing course filmmaker",
        "genre_hint": "filmmaking",
        "offer_priority": true
      },
      {
        "query": "filmmaking tutorial Patreon",
        "genre_hint": "filmmaking",
        "offer_priority": true
      },
      {
        "query": "music production online course",
        "genre_hint": "music_education",
        "offer_priority": true
      },
      {
        "query": "music theory lessons membership",
        "genre_hint": "music_education",
        "offer_priority": true
      },
      {
        "query": "guitar lessons Patreon",
        "genre_hint": "music_education",
        "offer_priority": true
      },
      {
        "query": "piano teaching online course",
        "genre_hint": "music_education",
        "offer_priority": true
      },
      {
        "query": "business education course creator",
        "genre_hint": "business",
        "offer_priority": true
      },
      {
        "query": "entrepreneurship course newsletter",
        "genre_hint": "business",
        "offer_priority": true
      },
      {
        "query": "marketing education paid community",
        "genre_hint": "business",
        "offer_priority": true
      },
      {
        "query": "creator newsletter Substack",
        "genre_hint": "education",
        "offer_priority": true
      },
      {
        "query": "educational YouTube channel Patreon",
        "genre_hint": "education",
        "offer_priority": true
      },
      {
        "query": "personal finance education course",
        "genre_hint": "finance",
        "offer_priority": true
      },
      {
        "query": "photography course creator",
        "genre_hint": "education",
        "offer_priority": true
      },
      {
        "query": "coding tutorials paid course",
        "genre_hint": "education",
        "offer_priority": true
      },
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
    "guidance": "A channel search costs 100 quota units, so a run does at most a few dozen searches; the channel statistics and the last 50 uploads cost 3 units per channel. The shorts gap, cadence and audience come straight from the API -- the pitch sentence is a fact. Long-form starts at eight minutes: a ten-minute explainer clips as well as an hour-long interview, and a twenty-minute floor threw away most education and commentary channels on the first live run (2026-09-09).",
    "offer_query_fraction": 0.65
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
    "kind",
    "creator_offers",
    "category"
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
    "key_prefix": "LCX",
    "board_title": "Clipping leads",
    "list_title": "Creators and studios",
    "entity_label": "show",
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
        "path": "metadata.podcast_feed.categories",
        "label": "Categories",
        "format": "list"
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
        "path": "metadata.youtube_channel.video_count",
        "label": "Videos on the channel",
        "format": "number"
      },
      {
        "path": "metadata.youtube_channel.recent.avg_long_minutes",
        "label": "Average long video (min)",
        "format": "number"
      },
      {
        "path": "metadata.creator_offers.summary",
        "label": "Creator''s own offer evidence",
        "format": "text"
      }
    ],
    "lead_first": "person",
    "summary_label": "Host · show",
    "entity_plural": "shows",
    "prioritize_fresh_leads": true
  },
  "outreach": {
    "sender": {
      "name": "LCX",
      "title": "Clipping desk",
      "company": "LCX",
      "postal_address": "",
      "email_env": "GMAIL_SENDER_ADDRESS_LCX_CLIPPING",
      "guidance": "Canonical LCX identity used to store drafts. Each approver''s connected Gmail sends new mail and their profile supplies the displayed sign-off. Postal address is optional and not in the footer; no unused SET_ME placeholder may block sending. The email_env entry is retained only for historical pool mail."
    },
    "sign_as": "approver",
    "sign_as_guidance": "Emails are signed by their approver and sent from that person''s connected Gmail (send_from approver).",
    "subject_max_words": 16,
    "subject_max_words_guidance": "LCX Clipping catalogue subjects may name the show; long names use the fallback subject.",
    "send_window": {
      "enabled": true,
      "start": "10:00",
      "end": "10:30",
      "timezone_of": "recipient",
      "sender_timezone": "Asia/Kolkata",
      "fallback_timezone": "America/New_York",
      "weekdays_only": true,
      "min_gap_seconds": 45,
      "min_lead_seconds": 120,
      "guidance": "Owner, 2026-10-12: \"I want you to send mails to the sender''s time region between 10 to 10:30AM and that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13 and so on after approval implement it\". Each approved email goes out at its own random second between start and end on its RECIPIENT''s clock (10:00 in Mumbai is 05:30 in London, too early to be read), drawn when it is approved and shown in Approved as \"Goes out\", with the time in India beside it. Where the recipient is comes from what the lead holds -- the person''s own Apollo record, the company''s state or city, a phone''s area code, its country -- and the reason is kept on the email (tools/send_window.py). Monday to Friday on the recipient''s clock (weekdays_only): an approval after today''s window, or at a weekend, takes the next weekday''s. An email whose window passes unsent (the server down, its address at its daily limit) moves to the next window at a new random time, never later the same day. Never two emails from one address closer than min_gap_seconds; never one sooner than min_lead_seconds after its approval. To send on the sender''s clock instead (every email 10:00-10:30 India time) set timezone_of to \"sender\"; to switch the window off set enabled to false -- the stored times are cleared and approvals go out as soon as they can, as before. docs/runbook.md, \"Goes out\". Sending is paused for this project (sending_paused); the window applies from the day it is lifted. A show that names no place goes at New York''s 10:00 (fallback_timezone)."
    },
    "daily_send_cap": 120,
    "hook_style": "clipping",
    "neutral_hook": "{{company}}''s long-form catalogue could reach new audiences through short clips.",
    "templates": [
      {
        "key": "lcx_catalogue_distribution_v1",
        "subject": "{{channel_name}} | Clipping + Distribution",
        "subject_fallback": "Your channel | Clipping + Distribution",
        "body": "{{hello}}\n\nI trust you are doing well.\n\n{{catalogue_opening}} {{catalogue_opportunity}}\n\nThat gap is exactly where we come in. In today''s landscape, excellent content also needs visibility. We are LCX, a new-age media agency built to help your work reach the viewers it deserves. We combine clipping with distribution workflows across social platforms to help turn passive viewers into loyal fans.\n\nWe would be glad to send across a few sample clips so you can judge the quality for yourself. If there is a particular episode you have in mind, share the name and we will build the samples around it.\n\nThank you for your time. I hope we can work together to turn your viewers into fans.\n\n{{footer}}"
      },
      {
        "key": "clipping_followup_1",
        "kind": "follow_up",
        "subject": "Re: {{opener_subject}}",
        "body": "{{hello}}\n\nI hope you are doing well.\n\nFollowing up on my note about helping {{company}} reach new audiences through short clips and distribution across social platforms.\n\nWe would be glad to send across a few sample clips so you can judge the quality for yourself. If there is a particular episode you have in mind, share the name and we will build the samples around it.\n\nThank you for your time.\n\n{{footer}}"
      }
    ],
    "guidance": "Owner, 2026-11-05: use the supplied LCX media-agency catalogue/distribution template as the single opener. Use each lead''s own show name and recorded episode count, with a neutral catalogue sentence when the count is unknown. Do not repeat Lex Fridman or a fixed 10,000-reel estimate on unrelated leads; a clip estimate requires supporting evidence. The sample-clips invitation is authorized. No em dashes or reply-yes offers. Sign with the actual approver''s name. The existing one follow-up after four days stays enabled, with matching sample-clips copy. Sending, qualification, contact selection and approval rules are preserved.",
    "greeting_fallback": "there",
    "follow_ups": {
      "enabled": true,
      "steps": [
        {
          "step": 1,
          "after_days": 4,
          "template": "clipping_followup_1"
        }
      ],
      "guidance": "Owner, 2026-10-23: \"set only 1 follow up after 4 days\" (it was two, 4 and 7 days, decided 2026-09-10). One thread per company: the opener plus this one follow-up, in the same Gmail thread, 4 days after the opener was sent. Any reply pauses the thread at once; a reply triaged as an auto-reply lets it resume, anything else ends it. A person can stop a thread from the message dialog. A follow-up is a draft in the Follow-ups tab and needs approval like any email. The database caps a thread at three follow-ups and refuses to send one after a reply (sql/23)."
    },
    "batch_approval": {
      "enabled": true,
      "sample_min": 3,
      "sample_fraction": 0.1,
      "guidance": "Owner decision 2026-09-10. Templated drafts may be approved together: select them in Drafts, read the random sample the server draws (at least sample_min, or sample_fraction of the batch, whichever is more), tick each, approve. Every draft is checked first (no {{placeholder}}, no SET_ME, a valid address, a sendable company). The approver''s name, the batch and the sample are recorded.",
      "allow_generated": false,
      "generated_guidance": "A spot check stands for a batch because every draft in it came from one template. A model-written sentence can be wrong on its own, so those drafts are approved one at a time. Set allow_generated to true once you have read enough of them to trust it; batches containing them then draw generated_sample_fraction instead of sample_fraction.",
      "generated_sample_fraction": 0.25
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
    "mailbox_guidance": "Legacy project-pool entries are retained for historical reply polling. New emails use the approving person''s connected Gmail and that mailbox''s cross-project daily cap.",
    "footer": {
      "text": "Regards,\n{{sender_name}}",
      "guidance": "Owner''s 2026-11-05 sign-off, using the actual approver''s name. Kartikeya is an example, not a shared identity."
    },
    "default_cc": [
      "amritanshv@lightscameraexperiment.com"
    ],
    "default_cc_guidance": "The owner, 2026-10-22: \"add a feature to cc someone from the software itself. Make default cc to the email amritanshv@lightscameraexperiment.com and obvio make a toggle to switch that off\". Every email of this project is copied to these addresses unless the person approving it switches that off in the email (the CC toggle) or changes the list. The list an email is approved with is the one it goes out with (outreach.cc, sql/39, frozen at approval): changing this default never changes an email already approved. A reply from one of these addresses is not taken for the recipient''s reply. [] copies nobody by default.",
    "generated_hook": {
      "model": "openai/gpt-oss-120b",
      "enabled": false,
      "guidance": "Owner''s catalogue template, 2026-11-05. Recorded show facts only; no generated hooks or model calls.",
      "provider": "groq",
      "max_words": 45,
      "max_calls_per_run": 200,
      "requests_per_minute": 25
    },
    "reelforge_templates": "lcx-catalogue-20261106",
    "send_from": "approver",
    "send_from_guidance": "Owner, 2026-10-21: use the Gmail connected to the person who approves the email, as other projects do. LCX Clipping must not wait for an unconfigured server pool. Each real mailbox keeps its own shared daily limit across projects; legacy pool settings remain only for historical reply reads.",
    "prioritize_fresh_leads": true
  },
  "schedule": [
    {
      "name": "weekly refresh",
      "pipeline": "weekly_refresh",
      "dow": 2,
      "hour": 2,
      "minute": 0,
      "enabled": true
    }
  ],
  "pipelines": {
    "weekly_refresh": [
      "expire_leads",
      "discover_podcasts",
      "discover_youtube",
      "discover_wikidata_channels",
      "prepare_clipping_candidates",
      "enrich_clipping",
      "enrich_contacts",
      "promote_chain",
      "draft_outreach"
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
  "video_first_min_recent_long": 8,
  "auto_shortlist": {
    "enabled": true,
    "guidance": "Owner decision 2026-09-14. Every ready_for_review lead with fit_score strictly above min_score is shortlisted by the last step of the promote chain (sql/14_auto_shortlist.sql) instead of by hand. Rejected, archived and contacted rows are never touched, and a lead a person moves back to review is never shortlisted again (metadata.auto_shortlisted_at). Shortlisting sends nothing: every draft still needs approval. Set enabled to false to go back to shortlisting by hand.",
    "min_score": 20
  },
  "lead_retention": {
    "enabled": true,
    "days": 14,
    "keep_approved_and_conversations": true
  },
  "creator_targeting": {
    "version": "creator-offers-20261106",
    "offer_required": false,
    "prioritise_owned_offers": true,
    "no_subscriber_ceiling": true,
    "allow_music_education": true,
    "guidance": "Prioritise creators with first-party evidence of their own product, course, newsletter, membership or service. A podcast is not required. Sponsor or affiliate mentions do not prove an owned offer. Strong creators without an offer remain eligible. No upper subscriber limit or size-only penalty. Music education and original music discussion qualify; children''s and music-only performance content remain excluded."
  }
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
