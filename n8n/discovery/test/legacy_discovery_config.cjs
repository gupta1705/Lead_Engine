// Archived connector fixtures, independent of the active Apollo-only configuration.
module.exports = {
  "youtube_discovery_queries": [
    {
      "query": "digital comedy studio",
      "genre_hint": "comedy"
    },
    {
      "query": "workplace comedy channel",
      "genre_hint": "workplace"
    },
    {
      "query": "young adult drama studio",
      "genre_hint": "young-adult"
    },
    {
      "query": "slice of life web series studio",
      "genre_hint": "slice-of-life"
    },
    {
      "query": "branded content studio",
      "genre_hint": null
    },
    {
      "query": "production company",
      "genre_hint": null
    }
  ],
  "news_rss_discovery_queries": [
    {
      "query": "\"local adaptation\" OR \"English-language remake\" production company",
      "deal_kind": "adaptation"
    },
    {
      "query": "\"US remake\" OR \"American remake\" series",
      "deal_kind": "adaptation"
    },
    {
      "query": "\"format rights\" OR \"remake rights\" producer",
      "deal_kind": "format_deal"
    },
    {
      "query": "\"international co-production\" series",
      "deal_kind": "co_production"
    },
    {
      "query": "\"acquires format\" OR \"format deal\" television",
      "deal_kind": "format_deal"
    },
    {
      "query": "\"first-look deal\" independent production company",
      "deal_kind": "output_deal"
    },
    {
      "query": "\"format\" adaptation \"US version\" series producer",
      "deal_kind": "adaptation"
    },
    {
      "query": "\"co-develop\" OR \"co-development\" series independent producer",
      "deal_kind": "co_production"
    },
    {
      "query": "\"scripted format\" OR \"unscripted format\" US remake producer",
      "deal_kind": "format_deal"
    },
    {
      "query": "\"greenlit\" comedy series independent production company",
      "deal_kind": "output_deal"
    }
  ],
  "x_intent_discovery_queries": [
    {
      "query": "\"open to co-productions\" production company",
      "intent": "explicit_invitation"
    },
    {
      "query": "indie production company \"looking for partners\"",
      "intent": "explicit_invitation"
    },
    {
      "query": "\"seeking a production partner\" series",
      "intent": "explicit_invitation"
    },
    {
      "query": "\"accepting submissions\" production company series",
      "intent": "open_door"
    },
    {
      "query": "\"co-production partner\" series OR film",
      "intent": "explicit_invitation"
    },
    {
      "query": "\"seeking co-producers\" OR \"seeking co-producer\"",
      "intent": "explicit_invitation"
    },
    {
      "query": "site:x.com \"co-production\" film series",
      "intent": "social_post"
    },
    {
      "query": "site:x.com production company \"looking for\" partner",
      "intent": "social_post"
    },
    {
      "query": "\"looking for co-production partners\" series",
      "intent": "explicit_invitation"
    },
    {
      "query": "\"format available\" OR \"formats available\" for adaptation",
      "intent": "explicit_invitation"
    }
  ],
  "wikidata_discovery": {
    "entity_classes": [
      "Q1762059",
      "Q10689397"
    ],
    "country": "Q30",
    "limit": 600,
    "guidance": "Wikidata SPARQL seed. entity_classes: Q1762059 is film production company, Q10689397 is television production company. They are SIBLING classes, not parent/child - a live probe on 2026-08-28 showed the film tree alone misses 124 US TV production companies with websites, so both are queried via VALUES and each subclass tree is still walked. country Q30 is the United States, which is what makes geography_signal us a fact rather than a guess. A live probe on 2026-08-25 found 363 US production companies carrying an official website (P856) - and the website is the whole point: every other connector leaves domain null, and Apollo matches organisations by domain at P16. CC0, no key, no quota. Notable-only, so this is a seed re-run occasionally rather than a weekly stream, and it skews LARGE - the first page is Icon Productions, Relativity Media, Warner Independent. Expect a low hit rate against the 2-20 person target and lean on major_or_oversized_signal plus the P13 gate. Only 14 of 363 carry an employee count, so size stays an enrichment question. For Segment 2, change entity_class here rather than touching any code."
  }
};
