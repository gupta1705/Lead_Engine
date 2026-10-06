-- 03E_SEGMENT_UNIVERSAL.SQL
-- Segment config row for 'universal'. GENERATED from config/segment.universal.json
-- by tools/gen_segment_sql.py; edit the JSON, regenerate, never hand-edit this
-- literal. Idempotent: an existing row is updated to the file's content.
insert into segments (slug, name, entity_type, config)
values (
  'universal',
  'Universal -- any company or person, found with Apollo search',
  'company',
  '{
  "entity_type": "company",
  "weekly_target": null,
  "score_threshold_review": 0,
  "score_threshold_priority": 0,
  "brief": "Universal: any company, any person, found with Apollo''s search. No scoring rubric and no harvest: a person searches Apollo on the Universal page, ticks the people or companies worth keeping, and saves them here as leads. Everything after that -- shortlisting, rejecting, contacts, export -- is the same as every other project, and since 2026-09-27 a person can write an email to the leads they pick (outreach.compose).",
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
      "detail": "tools/apollo.py, from the Universal page. People search is free and returns a preview (first name, masked last name, title, employer). Saving a person reveals them with people/bulk_match: 1 credit per person Apollo holds data for. Company search is 1 credit per page. Key: APOLLO_API_KEY in .env and in Render''s Environment tab."
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
      "name": "The Viral Fever",
      "title": "Business Development",
      "postal_address": "Contagious Online Media Network Pvt Ltd. 702, 7th Floor, A Wing, Fortune Terraces, Opp. Citi Mall, New Link Rd, Andheri West, Mumbai, Maharashtra 400053",
      "guidance": "Never what a recipient reads: an email here is written by a person and signed with their own name and title (app_users), with this postal address under it. The same company address as US Production Houses."
    },
    "footer": {
      "text": "Warm regards,\n{{sender_name}}\n{{sender_title}}\n\n{{postal_address}}\nIf this isn''t relevant, reply \"no thanks\" and you won''t hear from me again.",
      "guidance": "The block every email here ends with: the writer''s sign-off, TVF''s postal address and the way out, as in US Production Houses. Edited from Outreach -> Footer."
    },
    "guidance": "Owner, 2026-09-27: \"in the universal segment there should be a widget to send mail to them\". Universal leads come from Apollo, not a harvest, so there are no templates and nothing is drafted: a person picks leads (Leads page, or one lead) and writes one email with {{first_name}} and {{company}} in it (tools/outreach_compose.py). The page shows how it reads for each of them; approving it is the same gate as everywhere -- one approved email per company, checked like an approved draft -- and it goes out from the writer''s own Gmail (send_from approver, linked by the owner with tools/users.py gmail), inside that address''s daily limit, which it shares with every other project. A lead still in To review is shortlisted by being written to. Replies land in Outreach -> Replies."
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
    "guidance": "The five endpoints the Universal page calls, and the only ones a scoped Apollo key needs (Apollo: Settings > Integrations > API Keys > Create new key; a master key also works). Costs, from docs.apollo.io on 2026-09-19: people search 0 credits; company search 1 credit per page of up to 100; bulk_match 1 credit per person Apollo has data for, 0 for a miss; usage stats and profile 0. Personal emails and phone numbers are never requested. max_reveal_per_save caps one save, so a slip of the select-all box cannot spend hundreds of credits at once; the page asks before every save that costs credits."
  },
  "ui": {
    "project_name": "Universal",
    "key_prefix": "UNI",
    "board_title": "Universal leads",
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
