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
  "weekly_target": null,
  "score_threshold_review": 0,
  "score_threshold_priority": 0,
  "brief": "LCX Services: any business, found with Apollo''s search, offered all eighteen LCX services in one email (docs/LCX Services.pdf). The owner, 2026-10-06: \"i wanna build outreach a single one offering all these services\". It works like Universal: no scoring rubric and no harvest; a person searches Apollo on this project''s search page, saves the people or companies worth writing to, picks them on the Leads page and presses Write email, and the services email (outreach.compose_start) is already in the box, to send as it is or edit first. Everything after that -- shortlisting, rejecting, contacts, export, replies -- is the same as every other project.",
  "target_contact_roles": [],
  "rubric": [],
  "score_modifiers": [],
  "gates": [],
  "sources": [
    {
      "slug": "apollo",
      "name": "Apollo.io API (people and company search, bulk people reveal)",
      "kind": "api",
      "phase": 1,
      "detail": "tools/apollo.py, from this project''s search page (the same page and key as Universal; what is saved here stays here). People search is free and returns a preview (first name, masked last name, title, employer). Saving a person reveals them with people/bulk_match: 1 credit per person Apollo holds data for. Company search is 1 credit per page. Key: APOLLO_API_KEY in .env and in Render''s Environment tab."
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
    "guidance": "TVF and its affiliates never enter the lead pool, from any source. An Apollo search can return TVF''s own people and companies; saving one is refused, the same way the promote chain refuses them for the other segments. Domains match on the host or a subdomain, name patterns as whole words."
  },
  "outreach": {
    "compose": true,
    "send_from": "approver",
    "sender": {
      "name": "LCX",
      "title": "Business Development",
      "postal_address": "Contagious Online Media Network Pvt Ltd. 702, 7th Floor, A Wing, Fortune Terraces, Opp. Citi Mall, New Link Rd, Andheri West, Mumbai, Maharashtra 400053",
      "guidance": "Never what a recipient reads: an email here is written by a person and signed with their own name and title (app_users), with this postal address under it. The owner, 2026-10-06: TVF''s Mumbai office address, the same as US Production Houses and Universal."
    },
    "footer": {
      "text": "Warm regards,\n{{sender_name}}\n{{sender_title}}\n\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
      "guidance": "The block every email here ends with: the writer''s sign-off, the postal address and the way out, as in Universal. Edited from Outreach -> Footer."
    },
    "compose_start": {
      "subject": "18 things LCX can do for {{company}}",
      "body": "Hi {{first_name}},\n\nI''m writing from LCX. We work in three areas, and at least one of them should be useful to {{company}}:\n\n1. Repurposing as a Service: turning what you already own into new formats that reach more people.\n- Reel Forge: long form videos cut into reels and distributed across 5 to 10 Instagram pages.\n- Airbnb / Property Content: property photos turned into cinematic reels, carousels and home tours.\n- AI VFX + Animation: existing footage made cinematic with AI environments and effects.\n- Audiobooks and Audio Web Shows: books adapted into audio shows. Writers keep the rights and the revenue.\n\n2. AI Asset Creation: new content and experiences from scratch, without the cost of a traditional shoot or build.\n- AI Video for Brands: product, ad and campaign videos without separate shoots.\n- AI Real Estate Visualisation: blueprints turned into realistic visuals and walkthroughs before construction.\n- Explainer Videos: complex products, services and concepts explained visually.\n- Shop Display Videos: screen content for retail spaces showcasing collections, offers and promotions.\n- AI UGC Product Videos: AI influencers creating recurring product content on a brand''s own page.\n- AI Podcasts / Audio Content: AI characters in conversation about products, brands and financial services.\n- Virtual Tours for Schools: virtual field trips to space, the ocean, ancient civilisations and landmarks.\n- AI Reality Experiences: immersive VR experiences and games.\n\n3. Tech Solutions: systems and tools businesses use in their daily operations, training and sales.\n- Creator × Brand Marketplace: a platform for brands to discover nano and micro influencers and run campaigns.\n- Local Business Tech and Automation: billing, bookings, WhatsApp follow ups and dashboards for cafes, salons and gyms.\n- AI Business Assistant: on demand answers on sales, tasks and inventory for business owners.\n- AI Simulations for Training: real world scenarios that test and score sales and customer facing teams.\n- AI Fashion Stylist: an AI mirror near changing rooms that completes the look from store stock.\n- AI Onboarding Employee: a digital trainer that teaches, tests and scores new hires across 10 to 15 parameters.\n\nIf one of these fits what {{company}} is working on, reply with its name and I''ll send examples of our work.",
      "source": "docs/LCX Services.pdf",
      "guidance": "The email the Write email box starts from in this project: the owner''s one email offering every LCX service (2026-10-06), approved by the owner as it reads here. Each service line is the services sheet''s own wording; the sheet cuts off the description of AI Reality Experiences after \"games\", so it ends there. The person writing can change anything before approving, and what they approve is what is sent. It may use {{first_name}} and {{company}} only (tools/outreach_compose.py); the footer goes under it."
    },
    "guidance": "The owner, 2026-10-06: one email offering all the LCX services, to any business. Leads come from Apollo, not a harvest, so there are no templates and nothing is drafted: a person picks leads (Leads page, or one lead) and presses Write email; the box starts from outreach.compose_start (tools/outreach_compose.py). The page shows how it reads for each of them; approving it is the same gate as everywhere -- one approved email per company, checked like an approved draft -- and it goes out from the writer''s own Gmail (send_from approver, linked by the owner with tools/users.py gmail), inside that address''s daily limit, which it shares with every other project. Not paused: the owner chose ''send once approved'' for this project. A lead still in To review is shortlisted by being written to. Replies land in Outreach -> Replies."
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
    "guidance": "The same five endpoints and limits as Universal (see config/segment.universal.json): people search 0 credits, company search 1 credit per page, bulk_match 1 credit per person Apollo has data for. max_reveal_per_save caps one save; the page asks before every save that costs credits."
  },
  "ui": {
    "project_name": "LCX Services",
    "key_prefix": "LXS",
    "board_title": "LCX Services leads",
    "list_title": "Leads",
    "entity_label": "company",
    "entity_plural": "companies",
    "summary_label": "Company",
    "search_page": "apollo",
    "default_route": "universal",
    "hide_routes": [
      "ops",
      "reports"
    ],
    "card_fields": [
      {
        "path": "metadata.industry",
        "label": "",
        "format": "text"
      },
      {
        "path": "metadata.employees",
        "label": "people",
        "format": "number"
      },
      {
        "path": "metadata.hq_country",
        "label": "",
        "format": "text"
      }
    ],
    "details": [
      {
        "path": "metadata.industry",
        "label": "Industry",
        "format": "text"
      },
      {
        "path": "metadata.employees",
        "label": "Employees",
        "format": "number"
      },
      {
        "path": "metadata.hq_country",
        "label": "Country",
        "format": "text"
      },
      {
        "path": "metadata.apollo.founded_year",
        "label": "Founded",
        "format": "text"
      },
      {
        "path": "metadata.apollo.annual_revenue_printed",
        "label": "Revenue",
        "format": "text"
      },
      {
        "path": "metadata.apollo.total_funding_printed",
        "label": "Funding",
        "format": "text"
      },
      {
        "path": "metadata.apollo.latest_funding_stage",
        "label": "Latest round",
        "format": "text"
      },
      {
        "path": "metadata.apollo.short_description",
        "label": "Apollo''s description",
        "format": "text"
      },
      {
        "path": "metadata.apollo.keywords",
        "label": "Keywords",
        "format": "list"
      },
      {
        "path": "metadata.saved_from.summary",
        "label": "Found by",
        "format": "text"
      }
    ]
  },
  "schedule": [],
  "pipelines": {
    "enrich_contacts": [
      "enrich_contacts"
    ]
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
