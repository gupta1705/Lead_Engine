-- 03F_SEGMENT_LCX_SERVICES.SQL
-- Segment config row for 'lcx-services'. GENERATED from config/segment.lcx-services.json
-- by tools/gen_segment_sql.py; edit the JSON, regenerate, never hand-edit this
-- literal. Idempotent: an existing row is updated to the file's content.
insert into segments (slug, name, entity_type, config)
values (
  'lcx-services',
  'LCX Services -- any business, offered every LCX service in one email',
  'company',
  '{
  "entity_type": "company",
  "weekly_target": 1200,
  "score_threshold_review": 25,
  "score_threshold_priority": 70,
  "brief": "LCX Services: businesses everywhere cold business email is allowed, offered every LCX service in one email with the services deck attached (docs/LCX Services.pdf; the deck is docs/decks/LCX Services - pitch deck.pdf). The owner, 2026-10-06: \"i wanna build outreach a single one offering all these services\" and \"it should generate the leads on its own\"; 2026-10-07: \"i want to reachout to buisnesses to normal corporates not just cafes and all think about whats the best places we can source our leads from and use it . Enriching from apollo is acceptable\". So it harvests by itself every Friday: mid-size corporates from Apollo''s company search (those hiring for content or training right now, recently funded ones, and each audience by size and country), listed companies and notable firms from Wikidata, US banks from the FDIC register, and a small stream of local businesses from OpenStreetMap. Then an address from the business itself or its own website, a named person from Apollo for a well-fitting lead that has none (inside a weekly credit cap), and a draft a person approves. docs/LCX_services.md.",
  "target_contact_roles": [
    "Owner",
    "Founder",
    "Co-Founder",
    "CEO",
    "Managing Director",
    "Director",
    "General Manager",
    "Head of Marketing",
    "Marketing Manager",
    "Brand Manager",
    "Principal"
  ],
  "geography": {
    "allowed_countries": [],
    "priority_countries": [],
    "disallowed_countries": [
      "CA",
      "DE",
      "AT",
      "IT"
    ],
    "english_markets": [
      "US",
      "GB",
      "IE",
      "IN",
      "AE",
      "SG",
      "AU",
      "NZ",
      "ZA",
      "PH",
      "MY",
      "NG",
      "KE",
      "HK",
      "LK",
      "PK",
      "BD",
      "GH",
      "QA",
      "BH",
      "OM"
    ],
    "guidance": "The owner, 2026-10-06: \"Everywhere allowed\" -- every country except those whose law needs consent before a cold business email: Canada (CASL), Germany and Austria (UWG), Italy, the same set as LCX Clipping. A company is left out only on evidence: Wikidata says its only country is one of them, or the city it was found in is. english_markets earns a small bonus (score_modifiers.english_market) because the email and the deck are in English; it never leaves anyone out."
  },
  "audiences": [
    {
      "key": "corporate_teams",
      "label": "Mid-size company",
      "fit": 1.0,
      "services": [
        "AI Onboarding Employee",
        "AI Simulations for Training",
        "AI Business Assistant",
        "Explainer Videos",
        "AI Podcasts / Audio Content"
      ],
      "wikidata": [
        {
          "property": "P414",
          "values": [],
          "note": "listed on a stock exchange: ordinary corporates the class and industry queries miss"
        }
      ],
      "contact_roles": [
        "Head of Learning and Development",
        "Learning and Development Manager",
        "Head of Training",
        "Head of Sales Enablement",
        "Chief People Officer",
        "HR Director",
        "Head of Internal Communications",
        "Head of Customer Experience"
      ]
    },
    {
      "key": "consumer_brands",
      "label": "Consumer brand",
      "fit": 1.0,
      "services": [
        "AI Video for Brands",
        "AI UGC Product Videos",
        "Explainer Videos",
        "Creator × Brand Marketplace"
      ],
      "wikidata": [
        {
          "property": "P452",
          "values": [
            "Q12752882",
            "Q11828862",
            "Q540912",
            "Q4899370",
            "Q581105",
            "Q57262277",
            "Q11990434",
            "Q484847"
          ],
          "note": "industry: cosmetics, clothing, food, beverages, consumer electronics, jewellery, furniture, e-commerce"
        }
      ],
      "contact_roles": [
        "Chief Marketing Officer",
        "Head of Marketing",
        "Brand Director",
        "Head of Brand",
        "Head of Ecommerce",
        "Head of Content",
        "Founder"
      ]
    },
    {
      "key": "retailers",
      "label": "Retailer",
      "fit": 1.0,
      "services": [
        "Shop Display Videos",
        "AI Fashion Stylist",
        "AI Simulations for Training",
        "AI Onboarding Employee"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q507619",
            "Q2549179",
            "Q18043413",
            "Q1941779",
            "Q4382945"
          ],
          "note": "retail chain, department store chain, supermarket chain, fashion house, online shop"
        },
        {
          "property": "P452",
          "values": [
            "Q126793"
          ],
          "note": "industry: retail"
        }
      ],
      "contact_roles": [
        "Head of Marketing",
        "Marketing Director",
        "Head of Visual Merchandising",
        "Head of Retail Operations",
        "Head of Learning and Development",
        "Head of Customer Experience"
      ]
    },
    {
      "key": "real_estate",
      "label": "Real estate developer or agent",
      "fit": 1.0,
      "services": [
        "AI Real Estate Visualisation",
        "Airbnb / Property Content",
        "Explainer Videos"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q17487600"
          ],
          "note": "real estate developer"
        },
        {
          "property": "P452",
          "values": [
            "Q695829"
          ],
          "note": "industry: real estate development"
        }
      ],
      "osm": [
        [
          "office",
          "estate_agent"
        ]
      ],
      "contact_roles": [
        "Founder",
        "Managing Director",
        "Head of Marketing",
        "Marketing Director",
        "Sales Director",
        "Director of Sales and Marketing"
      ]
    },
    {
      "key": "hospitality",
      "label": "Hotel or short stay",
      "fit": 1.0,
      "services": [
        "Airbnb / Property Content",
        "AI Reality Experiences",
        "AI Onboarding Employee"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q1631129",
            "Q3117865"
          ],
          "note": "hotel chain, hotel group"
        },
        {
          "property": "P452",
          "values": [
            "Q1495452"
          ],
          "note": "industry: hospitality"
        }
      ],
      "osm": [
        [
          "tourism",
          "guest_house"
        ],
        [
          "tourism",
          "hotel"
        ],
        [
          "tourism",
          "apartment"
        ]
      ],
      "contact_roles": [
        "Director of Sales and Marketing",
        "Marketing Director",
        "Head of Marketing",
        "General Manager",
        "Head of Learning and Development",
        "Revenue and Distribution Director"
      ]
    },
    {
      "key": "publishers",
      "label": "Publisher",
      "fit": 1.0,
      "services": [
        "Audiobooks and Audio Web Shows",
        "AI Podcasts / Audio Content"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q2085381",
            "Q1320047"
          ],
          "note": "publishing house, book publisher"
        }
      ],
      "contact_roles": [
        "Publisher",
        "Head of Audio",
        "Head of Digital",
        "Rights Director",
        "Head of Audience Development",
        "Managing Director"
      ]
    },
    {
      "key": "financial_services",
      "label": "Bank, insurer or investment firm",
      "fit": 0.5,
      "services": [
        "AI Podcasts / Audio Content",
        "AI Simulations for Training",
        "AI Onboarding Employee",
        "Explainer Videos"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q22687",
            "Q2143354",
            "Q4230006"
          ],
          "note": "bank, insurance company, asset management company"
        },
        {
          "property": "P452",
          "values": [
            "Q837171"
          ],
          "note": "industry: financial services"
        }
      ],
      "contact_roles": [
        "Head of Marketing",
        "Head of Content",
        "Head of Brand",
        "Head of Learning and Development",
        "Head of Sales Enablement",
        "Chief Marketing Officer"
      ]
    },
    {
      "key": "studios_agencies",
      "label": "Studio or agency",
      "fit": 1.0,
      "services": [
        "Reel Forge",
        "AI VFX + Animation",
        "AI Video for Brands",
        "Explainer Videos"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q1762059",
            "Q10689397",
            "Q1107679",
            "Q216931"
          ],
          "note": "film production company, television production company, animation studio, advertising agency"
        }
      ],
      "contact_roles": [
        "Founder",
        "Managing Director",
        "Creative Director",
        "Head of Production",
        "Head of Partnerships"
      ]
    },
    {
      "key": "attractions",
      "label": "Theme park, museum or attraction",
      "fit": 0.5,
      "services": [
        "AI Reality Experiences",
        "Explainer Videos"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q194195"
          ],
          "note": "amusement park"
        }
      ],
      "osm": [
        [
          "tourism",
          "theme_park"
        ],
        [
          "tourism",
          "museum"
        ]
      ],
      "contact_roles": [
        "Marketing Director",
        "Head of Marketing",
        "Head of Guest Experience",
        "Commercial Director",
        "General Manager"
      ]
    },
    {
      "key": "schools",
      "label": "School",
      "fit": 1.0,
      "services": [
        "Virtual Tours for Schools",
        "AI Reality Experiences"
      ],
      "wikidata": [
        {
          "property": "P31",
          "values": [
            "Q572835"
          ],
          "note": "international school"
        }
      ],
      "osm": [
        [
          "amenity",
          "school"
        ]
      ],
      "contact_roles": [
        "Principal",
        "Head of School",
        "Head of Admissions",
        "Director of Admissions",
        "Marketing Director",
        "Bursar"
      ]
    },
    {
      "key": "local_business",
      "label": "Cafe, salon or gym",
      "fit": 1.0,
      "services": [
        "Local Business Tech and Automation",
        "AI Business Assistant"
      ],
      "osm": [
        [
          "amenity",
          "cafe"
        ],
        [
          "shop",
          "hairdresser"
        ],
        [
          "shop",
          "beauty"
        ],
        [
          "leisure",
          "fitness_centre"
        ]
      ],
      "contact_roles": [
        "Founder",
        "Owner",
        "Operations Director",
        "Head of Marketing"
      ]
    },
    {
      "key": "local_retail",
      "label": "Independent shop",
      "fit": 1.0,
      "services": [
        "Shop Display Videos",
        "AI Fashion Stylist",
        "Local Business Tech and Automation"
      ],
      "osm": [
        [
          "shop",
          "clothes"
        ],
        [
          "shop",
          "boutique"
        ],
        [
          "shop",
          "shoes"
        ],
        [
          "shop",
          "jewelry"
        ]
      ],
      "contact_roles": [
        "Founder",
        "Owner",
        "Operations Director",
        "Head of Marketing"
      ]
    }
  ],
  "audiences_guidance": "Who buys which of the 18 services on docs/LCX Services.pdf, where they are found (tools/discover_lcx_services.py) and who to write to there (contact_roles, the titles Apollo is searched for, best first). Every email offers every service; the audience decides who is found, what the lead says it fits (why_fit, Pitch first) and audience_fit in the rubric: 1.0 where the sheet''s services fit directly, 0.5 where the sale is slower (banks and insurers, attractions). corporate_teams (2026-10-07) is the owner''s \"normal corporates\": any industry, 201-5,000 people, for the training, onboarding and explainer services. wikidata entries match a class (P31), an industry (P452) or a stock-exchange listing (P414); osm entries are OpenStreetMap tag pairs; the Apollo searches are in apollo_discovery.",
  "discovery": {
    "skip_known_elsewhere": true,
    "wikidata": {
      "max_new_per_run": 600,
      "per_audience": 80,
      "max_minutes": 40
    },
    "osm": {
      "max_new_per_run": 150,
      "cities_per_run": 2,
      "max_minutes": 40
    },
    "guidance": "Each Friday''s refresh stages up to 600 new companies from Wikidata (an equal share for each audience, at most per_audience; 10 to 5,000 people first, and within that English-speaking markets first), the Apollo pages the week''s credits allow (apollo_discovery, about 900 companies), up to 200 US banks from the FDIC register, and up to 150 local businesses from OpenStreetMap (2 cities a week): the owner wants normal corporates, \"not just cafes\". The site pass after it reads up to 1,000 websites, best-scoring first. Each business is saved the moment it is found, and a run stops asking for more after max_minutes; what it did not reach waits for next week. skip_known_elsewhere: a business already a lead of another project is not staged here, so nobody is pitched by two projects from the same address.",
    "fdic": {
      "max_new_per_run": 200
    }
  },
  "osm_discovery": {
    "endpoints": [
      "https://overpass-api.de/api/interpreter",
      "https://overpass.kumi.systems/api/interpreter",
      "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    ],
    "radius_m": 12000,
    "pause_seconds": 3,
    "cities": [
      {
        "name": "London",
        "country": "GB",
        "lat": 51.5072,
        "lon": -0.1276
      },
      {
        "name": "New York",
        "country": "US",
        "lat": 40.7128,
        "lon": -74.006
      },
      {
        "name": "Mumbai",
        "country": "IN",
        "lat": 19.076,
        "lon": 72.8777
      },
      {
        "name": "Dubai",
        "country": "AE",
        "lat": 25.2048,
        "lon": 55.2708
      },
      {
        "name": "Sydney",
        "country": "AU",
        "lat": -33.8688,
        "lon": 151.2093
      },
      {
        "name": "Singapore",
        "country": "SG",
        "lat": 1.3521,
        "lon": 103.8198
      },
      {
        "name": "Los Angeles",
        "country": "US",
        "lat": 34.0522,
        "lon": -118.2437
      },
      {
        "name": "Manchester",
        "country": "GB",
        "lat": 53.4808,
        "lon": -2.2426
      },
      {
        "name": "Delhi",
        "country": "IN",
        "lat": 28.6139,
        "lon": 77.209
      },
      {
        "name": "Melbourne",
        "country": "AU",
        "lat": -37.8136,
        "lon": 144.9631
      },
      {
        "name": "Chicago",
        "country": "US",
        "lat": 41.8781,
        "lon": -87.6298
      },
      {
        "name": "Dublin",
        "country": "IE",
        "lat": 53.3498,
        "lon": -6.2603
      },
      {
        "name": "Bengaluru",
        "country": "IN",
        "lat": 12.9716,
        "lon": 77.5946
      },
      {
        "name": "Abu Dhabi",
        "country": "AE",
        "lat": 24.4539,
        "lon": 54.3773
      },
      {
        "name": "San Francisco",
        "country": "US",
        "lat": 37.7749,
        "lon": -122.4194
      },
      {
        "name": "Birmingham",
        "country": "GB",
        "lat": 52.4862,
        "lon": -1.8904
      },
      {
        "name": "Auckland",
        "country": "NZ",
        "lat": -36.8485,
        "lon": 174.7633
      },
      {
        "name": "Hyderabad",
        "country": "IN",
        "lat": 17.385,
        "lon": 78.4867
      },
      {
        "name": "Miami",
        "country": "US",
        "lat": 25.7617,
        "lon": -80.1918
      },
      {
        "name": "Edinburgh",
        "country": "GB",
        "lat": 55.9533,
        "lon": -3.1883
      },
      {
        "name": "Brisbane",
        "country": "AU",
        "lat": -27.4698,
        "lon": 153.0251
      },
      {
        "name": "Cape Town",
        "country": "ZA",
        "lat": -33.9249,
        "lon": 18.4241
      },
      {
        "name": "Pune",
        "country": "IN",
        "lat": 18.5204,
        "lon": 73.8567
      },
      {
        "name": "Houston",
        "country": "US",
        "lat": 29.7604,
        "lon": -95.3698
      },
      {
        "name": "Glasgow",
        "country": "GB",
        "lat": 55.8642,
        "lon": -4.2518
      },
      {
        "name": "Kuala Lumpur",
        "country": "MY",
        "lat": 3.139,
        "lon": 101.6869
      },
      {
        "name": "Chennai",
        "country": "IN",
        "lat": 13.0827,
        "lon": 80.2707
      },
      {
        "name": "Seattle",
        "country": "US",
        "lat": 47.6062,
        "lon": -122.3321
      },
      {
        "name": "Perth",
        "country": "AU",
        "lat": -31.9523,
        "lon": 115.8613
      },
      {
        "name": "Johannesburg",
        "country": "ZA",
        "lat": -26.2041,
        "lon": 28.0473
      },
      {
        "name": "Austin",
        "country": "US",
        "lat": 30.2672,
        "lon": -97.7431
      },
      {
        "name": "Kolkata",
        "country": "IN",
        "lat": 22.5726,
        "lon": 88.3639
      },
      {
        "name": "Manila",
        "country": "PH",
        "lat": 14.5995,
        "lon": 120.9842
      },
      {
        "name": "Boston",
        "country": "US",
        "lat": 42.3601,
        "lon": -71.0589
      },
      {
        "name": "Ahmedabad",
        "country": "IN",
        "lat": 23.0225,
        "lon": 72.5714
      },
      {
        "name": "Atlanta",
        "country": "US",
        "lat": 33.749,
        "lon": -84.388
      },
      {
        "name": "Nairobi",
        "country": "KE",
        "lat": -1.2921,
        "lon": 36.8219
      },
      {
        "name": "Lagos",
        "country": "NG",
        "lat": 6.5244,
        "lon": 3.3792
      },
      {
        "name": "Dallas",
        "country": "US",
        "lat": 32.7767,
        "lon": -96.797
      },
      {
        "name": "Hong Kong",
        "country": "HK",
        "lat": 22.3193,
        "lon": 114.1694
      }
    ],
    "guidance": "OpenStreetMap''s Overpass API, the endpoints tried in turn (the main one did not answer from the office on 2026-10-06; a mirror did). Each run takes discovery.osm.cities_per_run of these cities, a different few each ISO week, and asks each audience''s tags within radius_m of the centre, for places that publish a website or an email address. Coverage follows the map''s volunteers: on 2026-10-06 London had about 1,400 cafes with a website or address, Mumbai 26. Cities in English-speaking business markets only, since the email and the deck are in English; add a city here and it joins the rotation. Data (c) OpenStreetMap contributors, ODbL, recorded on each lead it found."
  },
  "hosting_providers": [
    "facebook.com",
    "fb.com",
    "instagram.com",
    "linktr.ee",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "wa.me",
    "whatsapp.com",
    "google.com",
    "goo.gl",
    "g.page",
    "business.site",
    "sites.google.com",
    "maps.app.goo.gl",
    "bit.ly",
    "wixsite.com",
    "wordpress.com",
    "blogspot.com",
    "squarespace.com",
    "weebly.com",
    "yelp.com",
    "tripadvisor.com",
    "booking.com",
    "airbnb.com",
    "zomato.com",
    "swiggy.com",
    "justdial.com",
    "fresha.com",
    "booksy.com",
    "treatwell.co.uk",
    "ubereats.com",
    "doordash.com",
    "deliveroo.co.uk",
    "wikipedia.org",
    "wikidata.org"
  ],
  "rubric": [
    {
      "key": "reachable_decision_maker",
      "label": "Someone to write to: a named person (full) or the business''s own published address (half)",
      "points": 50,
      "input": "metadata.scoring_inputs.reachable_decision_maker",
      "guidance": "1.0 a named person in a deciding role with their own verified address (Apollo, the site pass, or a person); 0.5 a business address (info@, hello@) the business publishes on OpenStreetMap, on Wikidata or on its own site (tools/enrich_lcx_services.py, enrich_contacts). Half the points on purpose: a lead nobody can be written to tops out at 50 (54 with the English bonus) and never crosses the auto-shortlist line at 55, so nothing is shortlisted that cannot be drafted."
    },
    {
      "key": "audience_fit",
      "label": "A buyer the services fit directly",
      "points": 20,
      "input": "metadata.scoring_inputs.audience_fit",
      "guidance": "From the lead''s audience (config audiences, fit): 1.0 brands, retailers, real estate, hotels and short stays, publishers, studios and agencies, schools, cafes, salons and gyms, independent shops; 0.5 banks and insurers, attractions, where the sale is slower."
    },
    {
      "key": "established",
      "label": "An established business",
      "points": 15,
      "input": "metadata.scoring_inputs.established",
      "guidance": "1.0 a company notable enough for Wikidata, or a local business that publishes its website and its phone or opening hours; 0.5 a local business with less on record."
    },
    {
      "key": "right_size",
      "label": "The size that buys this and answers a cold email",
      "points": 15,
      "input": "metadata.scoring_inputs.right_size",
      "guidance": "1.0 at 10 to 5,000 people, or an independent local business; 0.5 at 1-9 or 5,001-50,000 people; 0 above 50,000 (a procurement process, not a reply). Unverified (0) when Wikidata gives no headcount."
    }
  ],
  "score_modifiers": [
    {
      "key": "english_market",
      "label": "BONUS: an English-speaking business market",
      "max_bonus": 4,
      "input": "metadata.scoring_inputs.english_market",
      "guidance": "The email and the deck are in English. 1.0 in geography.english_markets, 0 in any other allowed country, absent when the country is unknown. Four points: enough to order two equal leads, never enough to shortlist a lead nobody can be written to."
    }
  ],
  "gates": [
    {
      "key": "country_allowed",
      "label": "Not in a country where cold business email needs consent",
      "input": "metadata.scoring_inputs.country_signal",
      "exclude_when": "disallowed",
      "guidance": "Fires only on confirmed evidence of a disallowed country (geography.disallowed_countries). Unknown always passes."
    },
    {
      "key": "not_giant",
      "label": "Not a company of over 100,000 people",
      "input": "metadata.scoring_inputs.oversized_signal",
      "exclude_when": true,
      "guidance": "Set from Wikidata''s headcount. Companies that size buy through procurement and have in-house teams for all of this; a cold email from LCX is not how they buy. Unknown passes."
    },
    {
      "key": "usable_first_party_presence",
      "label": "Some way to reach them: a website or an address",
      "input": "metadata.scoring_inputs.has_reachable_presence",
      "exclude_when": false,
      "guidance": "Fires only on an explicit false. The harvest stages nothing without a website or a published address, so this is a guard."
    }
  ],
  "auto_shortlist": {
    "enabled": true,
    "min_score": 55,
    "guidance": "Like the production houses: every lead in To review scoring above 55 is shortlisted by the last step of the promote chain, and a shortlisted lead with an address is drafted within minutes. 55 is just above what a lead nobody can be written to can score (50, 54 with the English bonus), so everything shortlisted can be drafted. Shortlisting sends nothing: every email is approved by a person. Leads at or below the line stay in To review, where a person can shortlist one by hand."
  },
  "enrichment": {
    "enabled": true,
    "provider": "apollo",
    "contact_method": "published_address_then_site_scrape_then_apollo",
    "email_verifier": "apollo",
    "credits_per_run": 110,
    "credits_per_week": 120,
    "keep_in_reserve": 700,
    "score_over": 43,
    "verified_only": true,
    "find_website_by_name": false,
    "recheck_after_days": 30,
    "reveal_countries": [
      "US",
      "GB",
      "IN",
      "AE"
    ],
    "current_employer_check": true,
    "senior_titles": "(founder|owner|ceo|chief executive|chief marketing|chief commercial|chief operating|chief people|(?<!vice )president|managing director|general manager|principal|head of school|head teacher|headmaster|headmistress)",
    "guidance": "The owner, 2026-10-07: \"Enriching from apollo is acceptable\". Addresses come first from the business itself (what it publishes, then its own website: free); a lead that fits well (scoring over score_over) and still has nobody to write to gets one free Apollo people search for its audience''s contact_roles at its current employer, then 1 credit for the best person''s verified work address (tools/enrich_apollo.py, enrich_apollo_lcxs). The week''s cap, credits_per_week, covers this project''s Apollo spending together, the search page''s included: about 10 company pages and 110 people. The week runs from Friday 00:00 UTC, the refresh''s day. The ledger (apollo_spend, sql/33) counts every credit, so a refresh pressed by hand cannot spend the week twice, and nothing is spent once fewer than keep_in_reserve credits are left for the month (nor when Apollo cannot say what is left), so US Production Houses keeps its week. reveal_countries: only leads based in the US, the UK, India and the UAE. skip_revealed_elsewhere: nobody already revealed for another project is paid for again. Change the numbers here (then tools/gen_segment_sql.py lcx-services and sql/03f). A person is paid for only when their title is one of the audience''s contact_roles, shares a real word with one (marketing, brand, training, admissions...; not ''director'' or ''head''), or is senior (senior_titles: founder, chief executive, managing director, principal...): the only person Apollo lists is not a reason to spend.",
    "require_fitting_role": true,
    "skip_revealed_elsewhere": true
  },
  "sources": [
    {
      "slug": "lcx_apollo",
      "name": "Apollo.io company search (weekly, inside the credit cap)",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_lcx_services.py --source apollo: mid-size companies with their websites, by audience, size and country, the ones hiring for content, training or store staff now and the recently funded first. 1 credit a page of 100."
    },
    {
      "slug": "lcx_wikidata",
      "name": "Wikidata (listed companies, and companies by class and industry)",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_lcx_services.py --source wikidata: operating companies with an official website, listed on a stock exchange or in an audience''s classes and industries. CC0, free."
    },
    {
      "slug": "lcx_fdic",
      "name": "FDIC BankFind (US banks)",
      "kind": "api",
      "phase": 1,
      "detail": "tools/discover_lcx_services.py --source fdic: US banks of $1-20 billion with their websites. Public domain, free."
    },
    {
      "slug": "lcx_osm",
      "name": "OpenStreetMap (local businesses around a city)",
      "kind": "api",
      "phase": 2,
      "detail": "tools/discover_lcx_services.py --source osm: independent cafes, salons, gyms, shops, estate agents, guest houses, schools and attractions that publish a website or an address, 2 cities a week. ODbL."
    },
    {
      "slug": "apollo",
      "name": "Apollo.io search (by hand)",
      "kind": "api",
      "phase": 2,
      "detail": "The Apollo search page, for adding a lead by hand. Saving a person reveals them: 1 credit each."
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
      "contagious online media",
      "tvf"
    ],
    "guidance": "TVF and its affiliates never enter the lead pool, from any source. Domains match on the host or a subdomain, name patterns as whole words."
  },
  "outreach": {
    "send_from": "approver",
    "sender": {
      "name": "LCX",
      "title": "Business Development",
      "postal_address": "Contagious Online Media Network Pvt Ltd. 702, 7th Floor, A Wing, Fortune Terraces, Opp. Citi Mall, New Link Rd, Andheri West, Mumbai, Maharashtra 400053",
      "guidance": "Never what a recipient reads as the sign-off: the email goes from the approver''s own Gmail, signed with their name and title (app_users), with this postal address under it. The owner, 2026-10-06: TVF''s Mumbai office address, as US Production Houses and Universal."
    },
    "footer": {
      "text": "Warm regards,\n{{sender_name}}\n{{sender_title}}\n\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
      "guidance": "The block every email here ends with: the approver''s sign-off, the postal address and the way out. Edited from Outreach -> Footer."
    },
    "greeting_fallback": "there",
    "templates": [
      {
        "key": "lcx_services_deck_v1",
        "subject": "18 things LCX can do for {{company}}",
        "body": "Hi {{greeting_name}},\n\nI''m writing from LCX. We work in three areas, and at least one of them should be useful to {{company}}. Our services deck is attached.\n\nIf one fits, reply with its name and I''ll send examples.\n\n{{footer}}",
        "attachments": [
          "docs/decks/LCX Services - pitch deck.pdf"
        ],
        "guidance": "The owner''s choice, 2026-10-06: a short email with the services deck attached as a PDF, in the wording the owner approved. {{greeting_name}} is the person''s first name when one is known, else ''there''. The deck in attachments goes with every email from this template; the sender checks it is the same file that was drafted and approved, and holds the email back if it changed."
      }
    ],
    "batch_approval": {
      "enabled": true,
      "sample_min": 3,
      "sample_fraction": 0.1,
      "max_batch": 100,
      "allow_generated": false,
      "generated_sample_fraction": 0.25,
      "guidance": "Every draft here comes from one template with no model-written sentence, so they may be approved together: select them in Drafts, read the random sample the server draws (at least sample_min, or sample_fraction of the batch, whichever is more), tick each, approve. Every draft is checked first (no {{placeholder}}, no SET_ME, a valid address, a sendable company, the deck present)."
    },
    "guidance": "The owner, 2026-10-06: one email offering every LCX service, with the services deck attached, to the businesses the weekly harvest finds. Like US Production Houses: a shortlisted lead with an address is drafted by itself from the one template, a person approves it (one at a time, or a spot-checked batch), and it goes from that person''s own Gmail (send_from approver, linked by the owner with tools/users.py gmail), inside that address''s daily limit, which it shares with every other project. One first email per company and per inbox; no follow-ups. Not paused: the owner chose ''send once approved''. Replies land in Outreach -> Replies."
  },
  "apollo": {
    "per_page": 25,
    "max_reveal_per_save": 100,
    "endpoints": [
      "api/v1/mixed_people/api_search",
      "api/v1/mixed_companies/search",
      "api/v1/people/bulk_match",
      "api/v1/usage_stats/credit_usage_stats",
      "api/v1/users/api_profile"
    ],
    "guidance": "The search page''s settings, the same as Universal (see config/segment.universal.json): people search 0 credits, company search 1 credit per page, bulk_match 1 credit per person Apollo has data for. max_reveal_per_save caps one save; the page asks before every save that costs credits."
  },
  "ui": {
    "project_name": "LCX Services",
    "key_prefix": "LXS",
    "board_title": "LCX Services leads",
    "list_title": "Leads",
    "entity_label": "business",
    "entity_plural": "businesses",
    "summary_label": "Why",
    "search_page": "apollo",
    "default_route": "board",
    "hide_routes": [],
    "card_fields": [
      {
        "path": "metadata.audience",
        "label": "",
        "format": "text"
      },
      {
        "path": "metadata.hq_city",
        "label": "",
        "format": "text"
      },
      {
        "path": "metadata.hq_country",
        "label": "",
        "format": "text"
      }
    ],
    "details": [
      {
        "path": "metadata.audience",
        "label": "Audience",
        "format": "text"
      },
      {
        "path": "metadata.services",
        "label": "Pitch first",
        "format": "list"
      },
      {
        "path": "metadata.buying_signal",
        "label": "Signal",
        "format": "text"
      },
      {
        "path": "metadata.hq_city",
        "label": "City",
        "format": "text"
      },
      {
        "path": "metadata.hq_country",
        "label": "Country",
        "format": "text"
      },
      {
        "path": "metadata.size_band",
        "label": "Size",
        "format": "text"
      },
      {
        "path": "metadata.employees",
        "label": "Employees",
        "format": "number"
      },
      {
        "path": "metadata.industry",
        "label": "Industry",
        "format": "text"
      },
      {
        "path": "metadata.apollo.short_description",
        "label": "Apollo''s description",
        "format": "text"
      },
      {
        "path": "metadata.saved_from.summary",
        "label": "Found by",
        "format": "text"
      }
    ]
  },
  "schedule": [
    {
      "name": "weekly refresh",
      "pipeline": "weekly_refresh",
      "dow": 4,
      "hour": 2,
      "minute": 0,
      "enabled": true
    }
  ],
  "pipelines": {
    "weekly_refresh": [
      "discover_lcx_wikidata",
      "discover_lcx_apollo",
      "discover_lcx_fdic",
      "discover_lcx_osm",
      "promote_chain",
      "enrich_lcx_services",
      "enrich_contacts_lcxs",
      "enrich_apollo_lcxs",
      "promote_chain"
    ],
    "enrich_contacts": [
      "enrich_contacts"
    ]
  },
  "apollo_discovery": {
    "pages_per_run": 10,
    "signal_pages_per_run": 4,
    "per_page": 100,
    "countries": [
      {
        "name": "United States",
        "iso": "US"
      },
      {
        "name": "United Kingdom",
        "iso": "GB"
      },
      {
        "name": "India",
        "iso": "IN"
      },
      {
        "name": "United Arab Emirates",
        "iso": "AE"
      }
    ],
    "searches": [
      {
        "key": "corporates_hiring_trainers",
        "audience": "corporate_teams",
        "signal": "hiring for training and onboarding now",
        "posted_within_days": 30,
        "filters": {
          "organization_num_employees_ranges": [
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ],
          "q_organization_job_titles": [
            "learning and development manager",
            "training manager",
            "sales trainer",
            "instructional designer",
            "sales enablement manager",
            "onboarding specialist"
          ]
        }
      },
      {
        "key": "corporates_hiring_frontline",
        "audience": "corporate_teams",
        "signal": "hiring sales and service staff now",
        "posted_within_days": 30,
        "filters": {
          "organization_num_employees_ranges": [
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ],
          "q_organization_job_titles": [
            "sales representative",
            "customer service representative",
            "account executive"
          ],
          "organization_num_jobs_range": {
            "min": 10
          }
        }
      },
      {
        "key": "brands_hiring_content",
        "audience": "consumer_brands",
        "signal": "hiring for content and video now",
        "posted_within_days": 30,
        "filters": {
          "q_organization_keyword_tags": [
            "consumer goods",
            "cosmetics",
            "apparel & fashion",
            "food & beverages",
            "luxury goods & jewelry",
            "sporting goods",
            "consumer electronics",
            "wine & spirits"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ],
          "q_organization_job_titles": [
            "content marketing manager",
            "social media manager",
            "video editor",
            "video producer",
            "content creator",
            "brand manager"
          ]
        }
      },
      {
        "key": "brands_recently_funded",
        "audience": "consumer_brands",
        "signal": "raised money in the last 90 days",
        "funded_within_days": 90,
        "filters": {
          "q_organization_keyword_tags": [
            "consumer goods",
            "cosmetics",
            "apparel & fashion",
            "food & beverages",
            "luxury goods & jewelry",
            "sporting goods",
            "consumer electronics",
            "wine & spirits"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ],
          "latest_funding_amount_range": {
            "min": 2000000,
            "max": 60000000
          }
        }
      },
      {
        "key": "retailers_hiring_store_staff",
        "audience": "retailers",
        "signal": "hiring store staff now",
        "posted_within_days": 30,
        "filters": {
          "q_organization_keyword_tags": [
            "retail",
            "supermarkets"
          ],
          "organization_num_employees_ranges": [
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ],
          "q_organization_job_titles": [
            "store associate",
            "sales associate",
            "visual merchandiser",
            "store manager"
          ],
          "organization_num_jobs_range": {
            "min": 10
          }
        }
      },
      {
        "key": "hotels_hiring_content_or_training",
        "audience": "hospitality",
        "signal": "hiring for content or training now",
        "posted_within_days": 30,
        "filters": {
          "q_organization_keyword_tags": [
            "hospitality",
            "hotels"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ],
          "q_organization_job_titles": [
            "social media manager",
            "content creator",
            "training manager",
            "guest experience manager"
          ]
        }
      },
      {
        "key": "developers_hiring_marketing",
        "audience": "real_estate",
        "signal": "hiring for marketing and sales now",
        "posted_within_days": 30,
        "filters": {
          "q_organization_keyword_tags": [
            "real estate development"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ],
          "q_organization_job_titles": [
            "marketing manager",
            "sales manager"
          ]
        }
      },
      {
        "key": "brands",
        "audience": "consumer_brands",
        "filters": {
          "q_organization_keyword_tags": [
            "consumer goods",
            "cosmetics",
            "apparel & fashion",
            "food & beverages",
            "luxury goods & jewelry",
            "sporting goods",
            "consumer electronics",
            "wine & spirits"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ]
        }
      },
      {
        "key": "developers",
        "audience": "real_estate",
        "filters": {
          "q_organization_keyword_tags": [
            "real estate development"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ]
        }
      },
      {
        "key": "retailers",
        "audience": "retailers",
        "filters": {
          "q_organization_keyword_tags": [
            "retail",
            "supermarkets"
          ],
          "organization_num_employees_ranges": [
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ]
        }
      },
      {
        "key": "hotels",
        "audience": "hospitality",
        "filters": {
          "q_organization_keyword_tags": [
            "hospitality",
            "hotels"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ]
        }
      },
      {
        "key": "publishers",
        "audience": "publishers",
        "filters": {
          "q_organization_keyword_tags": [
            "publishing",
            "book publishing",
            "newspapers",
            "online media"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ]
        }
      },
      {
        "key": "insurers_and_investment_firms",
        "audience": "financial_services",
        "filters": {
          "q_organization_keyword_tags": [
            "insurance",
            "investment management",
            "financial services"
          ],
          "organization_num_employees_ranges": [
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ]
        }
      },
      {
        "key": "schools",
        "audience": "schools",
        "filters": {
          "q_organization_keyword_tags": [
            "primary/secondary education"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000"
          ]
        }
      },
      {
        "key": "attractions",
        "audience": "attractions",
        "filters": {
          "q_organization_keyword_tags": [
            "amusement parks",
            "museums & institutions",
            "recreational facilities & services"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500",
            "501,1000",
            "1001,2000",
            "2001,5000"
          ]
        }
      },
      {
        "key": "agencies",
        "audience": "studios_agencies",
        "filters": {
          "q_organization_keyword_tags": [
            "marketing & advertising",
            "animation"
          ],
          "organization_num_employees_ranges": [
            "11,50",
            "51,200",
            "201,500"
          ]
        }
      }
    ],
    "guidance": "Apollo''s company search: 1 credit a page of up to 100 companies, each with its website and Apollo''s own id for it (tools/discover_lcx_services.py --source apollo). A slice is one search in one country; each run buys pages_per_run pages, signal_pages_per_run of them from the signal searches (a company hiring for training, content or store staff right now, or recently funded, has the budget and the gap today), the rest from the plain audience searches, least-run slice first, and each slice''s next page the run after (apollo_cursors, sql/33). The ledger row and the cursor are written together the moment a page is bought, so a page paid for is never bought again. A signal search counts back from today, so it is a new set each time: once used up it rests for its window (30 or 90 days), then starts again at page 1; a plain search, once used up, waits until its cursor is reset. A free people search with the same filters goes first, and a page that would come back empty is never bought (the funding search has no free check: people search does not take it). Countries: the US, the UK, India and the UAE, where an Apollo address may be written to without prior consent; Australia, New Zealand and South Africa need consent the way Apollo finds an address, so they are left out. The answer has no industry, size or country, so they come from the slice. Tags are Apollo''s own, matched word for word (checked free on 2026-10-07: every one finds thousands); ''real estate development'', not ''real estate'', which pulls brokerages; no ''media production'' or ''film'', which US Production Houses already covers."
  },
  "fdic_discovery": {
    "audience": "financial_services",
    "assets_min_thousands": 1000000,
    "assets_max_thousands": 20000000,
    "guidance": "Every insured US bank, from the FDIC''s public BankFind API (public domain, no key; 4,223 active on 2026-10-07, nearly all with their own website). Banks of $1 to 20 billion in assets are the right size: a marketing team of their own, no procurement maze; about 940 of them. Up to discovery.fdic.max_new_per_run a week, largest first, until they are all in."
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
