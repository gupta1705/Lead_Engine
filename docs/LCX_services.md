# LCX Services

Built 2026-10-06. One outreach offering every LCX service, with the services deck attached, to
businesses the engine finds by itself. In the owner's words, that day:

- "Under docs there is lcx services i wanna build outreach a single one offering all these services"
- "it should generate the leads on its own for the people and businesses we can pitch the services to"
- "like we source leads for us production houses i want leads to come like that"
- "email should be a pitch deck of services", answered as: a PDF deck attached to a short email
- where: "Everywhere allowed" (every country except those whose law needs consent before a cold
  business email); and "send once approved", from each approver's own address

The services are the 18 on `docs/LCX Services.pdf`, in three clusters: Repurposing as a Service
(4), AI Asset Creation (8) and Tech Solutions (6).

## Who it finds

Every service has buyers; an **audience** is one kind of buyer, the services it is pitched first,
and where it is found (`config/segment.lcx-services.json`, `audiences`).

| Audience | Pitch first | Found on |
|---|---|---|
| Consumer brand | AI Video for Brands, AI UGC Product Videos, Explainer Videos, Creator × Brand Marketplace | Wikidata (industries) |
| Retailer | Shop Display Videos, AI Fashion Stylist, AI Simulations for Training, AI Onboarding Employee | Wikidata |
| Real estate developer or agent | AI Real Estate Visualisation, Airbnb / Property Content, Explainer Videos | Wikidata, OpenStreetMap |
| Hotel or short stay | Airbnb / Property Content, AI Reality Experiences, AI Onboarding Employee | Wikidata, OpenStreetMap |
| Publisher | Audiobooks and Audio Web Shows, AI Podcasts / Audio Content | Wikidata |
| Bank, insurer or investment firm | AI Podcasts / Audio Content, AI Simulations for Training, AI Onboarding Employee, Explainer Videos | Wikidata |
| Studio or agency | Reel Forge, AI VFX + Animation, AI Video for Brands, Explainer Videos | Wikidata |
| Theme park, museum or attraction | AI Reality Experiences, Explainer Videos | Wikidata, OpenStreetMap |
| School | Virtual Tours for Schools, AI Reality Experiences | Wikidata, OpenStreetMap |
| Cafe, salon or gym | Local Business Tech and Automation, AI Business Assistant | OpenStreetMap |
| Independent shop | Shop Display Videos, AI Fashion Stylist, Local Business Tech and Automation | OpenStreetMap |

Every email still offers every service; the audience decides who is found and what the lead says
it fits.

- **Wikidata** (CC0): operating companies (no dissolved date) of a class or an industry, with an
  official website. Not only in a consent-law country. About 30,000 matched on 2026-10-06. Each
  audience gets an equal share of a run. Taken 10-5,000 people first, then unknown size, then
  larger; over 100,000 never. Within each size, English-speaking markets come first, then
  unknown countries, then the rest (the email and the deck are in English).
- **OpenStreetMap** (ODbL, "(c) OpenStreetMap contributors", kept on each lead): independent places
  that publish a website or an email address, within 12 km of a city centre. Never a chain's
  branch (a brand tag). Six of the 40 cities a week, in turn. Coverage follows the map's
  volunteers: London had about 1,400 cafes with a website or address, Mumbai 26. The Overpass
  endpoints are tried in turn; the main one did not answer from the office on 2026-10-06, a mirror
  did, slowly.

Not staged: a business already a lead of another project (`discovery.skip_known_elsewhere`), so
nobody is pitched by two projects from the same address.

## How it is wired

| Step (weekly_refresh, Fridays 02:00 UTC) | Tool | What it does |
|---|---|---|
| `discover_lcx_wikidata` | `tools/discover_lcx_services.py --source wikidata` | Up to 600 new companies, at most 80 per audience. |
| `discover_lcx_osm` | `tools/discover_lcx_services.py --source osm` | Up to 600 local businesses, an even share per city and audience, those publishing an address first. |
| `promote_chain` | `tools/run_chain.py` | Self-exclusion, promote, dedupe, zero-unverified, score, gates, auto-shortlist. |
| `enrich_lcx_services` | `tools/enrich_lcx_services.py` | The address a business published becomes a contact; the audience, services and place go on the lead. |
| `enrich_contacts_lcxs` | `tools/enrich_sitescrape.py --limit 600` | The polite site pass: robots.txt honoured, never LinkedIn. |
| `promote_chain` | | Scores what the two steps found; leads with an address cross the shortlist line. |

Then the scheduler's outreach tick drafts each shortlisted lead with an address, from the one
template, with the deck attached. A person approves (one at a time or a spot-checked batch), and
it goes from their own Gmail inside its daily limit. Apollo is not used (`enrichment.enabled` is
false: "forget apollo for a sec"). The Apollo search page stays for adding a lead by hand.

## The score

| Criterion | Points | Set by |
|---|---|---|
| Someone to write to: a named person 1.0, a published business address 0.5 | 50 | enrich_lcx_services, the site pass |
| A buyer the services fit directly (the audience's fit) | 20 | discovery |
| Established: on Wikidata, or a full listing on the map | 15 | discovery |
| The right size: 10-5,000 people, or an independent local business | 15 | discovery |
| Bonus: an English-speaking business market | +4 | discovery |

Auto-shortlist is above 55. A lead nobody can be written to tops out at 50 (54 with the bonus),
so everything shortlisted can be drafted. Gates archive a lead only on evidence: a consent-law
country, over 100,000 people, or nothing to reach it by.

## The email and the deck

- Subject: `18 things LCX can do for {{company}}`.
- Body: the owner-approved short email, then the approver's sign-off over TVF's Mumbai address and
  the opt-out.
- The deck is `docs/decks/LCX Services - pitch deck.pdf`: five 16:9 pages, built from
  `docs/decks/lcx-services-deck.html` by `python tools/build_deck.py`. The pages are a cover, one
  page per cluster in the sheet's colours and words, and the next step.
- The sheet cuts off the line for AI Reality Experiences after "games", so the deck stops there.
- The cover's one-line summary and the last page's three steps are not on the sheet. They were
  written for the deck.

Attachments (`sql/32`, `outreach.attachments`) are files under `docs/decks/` only.
1. A draft records each file's name, path, size and SHA-256.
2. Approving a draft re-reads the file, so the approver approves what they can open now from
   **Attached**.
3. The sender attaches exactly the approved bytes. A file that changed or went missing since then
   holds the email back with the reason.

## Changing it

- **Another kind of buyer, a class, a tag, a city:** edit `audiences` or `osm_discovery.cities`,
  then `python tools/gen_segment_sql.py lcx-services` and `python tools/run_sql.py
  sql/03f_segment_lcx_services.sql`. The next Friday finds them.
- **The deck:** edit the HTML, then `python tools/build_deck.py`, then commit both files.
- **Apollo enrichment:** set `enrichment.enabled`, with a weekly credit budget the owner sets, as
  for US Production Houses (`tools/enrich_apollo.py`).
- **Tests:** `tools/test_lcx_services.py` (80 checks) and the deck cases in `tools/test_send.py`.
