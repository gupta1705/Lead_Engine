# LCX Services

Built 2026-10-06. One outreach offering every LCX service, with the services deck attached, to
businesses the engine finds by itself. In the owner's words, that day:

- "Under docs there is lcx services i wanna build outreach a single one offering all these services"
- "it should generate the leads on its own for the people and businesses we can pitch the services to"
- "like we source leads for us production houses i want leads to come like that"
- "email should be a pitch deck of services", answered as: a PDF deck attached to a short email
- where: "Everywhere allowed" (every country except those whose law needs consent before a cold
  business email); and "send once approved", from each approver's own address

On 2026-10-07 the owner widened it: "i want to reachout to buisnesses to normal corporates not just
cafes and all ... Enriching from apollo is acceptable". So Apollo's company search, the FDIC's bank
register and Wikidata's listed companies were added as sources, OpenStreetMap was cut back, and
Apollo finds the right person at a lead that has nobody to write to, inside a weekly budget.

The services are the 18 on `docs/LCX Services.pdf`, in three clusters: Repurposing as a Service
(4), AI Asset Creation (8) and Tech Solutions (6).

## Who it finds

Every service has buyers; an **audience** is one kind of buyer, the services it is pitched first,
and where it is found (`config/segment.lcx-services.json`, `audiences`).

| Audience | Pitch first | Found on | Written to (Apollo, best first) |
|---|---|---|---|
| Mid-size company (any industry, 201-5,000 people) | AI Onboarding Employee, AI Simulations for Training, AI Business Assistant, Explainer Videos, AI Podcasts / Audio Content | Apollo (hiring signals), Wikidata (listed companies) | Head of Learning and Development, Head of Training, Chief People Officer... |
| Consumer brand | AI Video for Brands, AI UGC Product Videos, Explainer Videos, Creator × Brand Marketplace | Apollo, Wikidata | Chief Marketing Officer, Head of Marketing, Brand Director... |
| Retailer | Shop Display Videos, AI Fashion Stylist, AI Simulations for Training, AI Onboarding Employee | Apollo, Wikidata | Head of Marketing, Head of Visual Merchandising... |
| Real estate developer or agent | AI Real Estate Visualisation, Airbnb / Property Content, Explainer Videos | Apollo, Wikidata, OpenStreetMap | Founder, Managing Director, Head of Marketing... |
| Hotel or short stay | Airbnb / Property Content, AI Reality Experiences, AI Onboarding Employee | Apollo, Wikidata, OpenStreetMap | Director of Sales and Marketing, Marketing Director... |
| Publisher | Audiobooks and Audio Web Shows, AI Podcasts / Audio Content | Apollo, Wikidata | Publisher, Head of Audio, Head of Digital... |
| Bank, insurer or investment firm | AI Podcasts / Audio Content, AI Simulations for Training, AI Onboarding Employee, Explainer Videos | FDIC (US banks), Apollo (insurers, investment firms), Wikidata | Head of Marketing, Head of Content, Head of Brand... |
| Studio or agency | Reel Forge, AI VFX + Animation, AI Video for Brands, Explainer Videos | Apollo, Wikidata | Founder, Managing Director, Creative Director... |
| Theme park, museum or attraction | AI Reality Experiences, Explainer Videos | Apollo, Wikidata, OpenStreetMap | Marketing Director, Head of Guest Experience... |
| School | Virtual Tours for Schools, AI Reality Experiences | Apollo, Wikidata, OpenStreetMap | Principal, Head of School, Head of Admissions... |
| Cafe, salon or gym | Local Business Tech and Automation, AI Business Assistant | OpenStreetMap | Founder, Owner |
| Independent shop | Shop Display Videos, AI Fashion Stylist, Local Business Tech and Automation | OpenStreetMap | Founder, Owner |

Every email still offers every service; the audience decides who is found and what the lead says
it fits.

- **Apollo company search** (`apollo_discovery`): the corporates. 1 credit buys a page of up to 100
  companies, each with its website and Apollo's id for it. 16 searches in 4 countries (the US, the
  UK, India, the UAE): 64 slices, each with its own cursor (`apollo_cursors`, `sql/33`), so a slice's
  next page is bought the run after and no page is bought twice.
  - **Signal searches first** (`signal_pages_per_run`, 4 of the week's 10 pages): companies hiring
    trainers, sales and service staff, content people, store staff or marketers in the last 30
    days, and brands funded in the last 90. A company hiring for it now has the budget and the gap
    today, so these leads go first everywhere after (the person search, the review list).
  - **Then the plain audience searches**: brands, developers, retailers, hotels, publishers,
    insurers and investment firms, schools, attractions and agencies, by Apollo's own industry tags
    and a 10-5,000 headcount.
  - Least-run slice first, so every audience and country gets its turn. A free people search with
    the same filters goes first, and a slice that would come back empty is set aside for nothing.
  - A signal search counts back from today, so once used up it rests for its window (30 or 90
    days) and starts again at page 1; a plain search, once used up, waits until it is reset.
  - Apollo's answer has no industry, size or country, so they come from the slice that found it.
  - Not Australia, New Zealand or South Africa: their law needs consent for an address found the
    way Apollo finds one.
- **FDIC BankFind** (public domain, no key; `fdic_discovery`): every insured US bank; 4,223 were
  active on 2026-10-07. Banks of $1-20 billion in assets (about 940) are the right size: a marketing
  team of their own, no procurement maze. Up to 200 a week, largest first, until all are in.
- **Wikidata** (CC0): operating companies (no dissolved date) of a class or an industry, with an
  official website, and now any company listed on a stock exchange (P414) for the mid-size
  companies. Not in a consent-law country. Up to 600 a week, an equal share per audience (at
  most 80). Taken 10-5,000 people first, then unknown size, then larger; over 100,000 never.
  Within each size, English-speaking markets come first, then unknown countries, then the rest
  (the email and the deck are in English).
- **OpenStreetMap** (ODbL, "(c) OpenStreetMap contributors", kept on each lead): independent places
  that publish a website or an email address, within 12 km of a city centre. Never a chain's
  branch (a brand tag). Cut to 150 a week from 2 of the 40 cities, in turn ("not just cafes").
  The Overpass endpoints are tried in turn; the main one did not answer from the office on
  2026-10-06, a mirror did, slowly.

Every business is saved the moment it is found, and each source stops asking after
`max_minutes`; what it did not reach waits for next week.

Not staged: a business already a lead of another project (`discovery.skip_known_elsewhere`), so
nobody is pitched by two projects from the same address.

## How it is wired

| Step (weekly_refresh, Fridays 02:00 UTC) | Tool | What it does |
|---|---|---|
| `discover_lcx_wikidata` | `tools/discover_lcx_services.py --source wikidata` | Up to 600 new companies, at most 80 per audience. |
| `discover_lcx_apollo` | `tools/discover_lcx_services.py --source apollo` | The week's Apollo pages (10, about 1,000 companies; fewer if the budget says so), signal searches first. |
| `discover_lcx_fdic` | `tools/discover_lcx_services.py --source fdic` | Up to 200 US banks of $1-20 billion, largest first. |
| `discover_lcx_osm` | `tools/discover_lcx_services.py --source osm` | Up to 150 local businesses from 2 cities, an even share per city and audience, those publishing an address first. |
| `promote_chain` | `tools/run_chain.py` | Self-exclusion, promote, dedupe, zero-unverified, score, gates, auto-shortlist. |
| `enrich_lcx_services` | `tools/enrich_lcx_services.py` | The address a business published becomes a contact; the audience, services, place, size and buying signal go on the lead. |
| `enrich_contacts_lcxs` | `tools/enrich_sitescrape.py --limit 1000` | The polite site pass: robots.txt honoured, never LinkedIn. |
| `enrich_apollo_lcxs` | `tools/enrich_apollo.py --limit 200` | A lead scoring over 43 with still nobody to write to: the right person, from Apollo, inside the week's budget. |
| `promote_chain` | | Scores what the steps found; leads with someone to write to cross the shortlist line. |

Then the scheduler's outreach tick drafts each shortlisted lead with an address, from the one
template, with the deck attached. A person approves (one at a time or a spot-checked batch), and
it goes from their own Gmail inside its daily limit. The Apollo search page stays for adding a
lead by hand; what it spends there counts in the same week.

## Apollo: who is paid for, and the budget

The free ways come first: the address a business publishes, then its own website. Only a lead
that fits well (scoring over 43) and still has nobody to write to goes to Apollo.

1. A free people search for that audience's roles (`contact_roles`), at the company. A company
   the Apollo harvest found is searched by Apollo's own id for it, so the people are at that
   company now.
2. The best person is picked. Nobody is paid for unless their title is one of the roles, shares a
   real word with one (marketing, brand, training, admissions; not "director" or "head"), or is
   senior (founder, chief executive, managing director, principal; never a vice president of
   something else). The only person Apollo lists is not reason enough.
3. Checks before the credit: the person must still work at the lead's company (a past employer
   costs nothing), must not have been revealed already for another project
   (`skip_revealed_elsewhere`), and the lead must be based in the US, the UK, India or the UAE
   (leads based elsewhere are left out of the run, so they never crowd out the others).
4. 1 credit reveals their verified work address.

The budget (`enrichment`), the owner's money, stated in the config:

| Setting | Now | Means |
|---|---|---|
| `credits_per_week` | 120 | Everything this project spends in a week (Friday 00:00 UTC to Thursday, the refresh's day): the 10 company pages, up to 110 people, and the search page. About 520 a month. |
| `keep_in_reserve` | 700 | Nothing is spent once fewer than 700 credits are left in the month, nor when Apollo cannot say what is left, so US Production Houses keeps its week. |
| `credits_per_run` | 110 | People revealed in one run, at most. |
| `reveal_countries` | US, GB, IN, AE | Leads based anywhere else are held, not paid for. |

Every credit is written to a ledger (`apollo_spend`, `sql/33`) as it is spent, by the harvest, the
person search and the search page alike, before anything is done with what it bought; a company
page's ledger row and its cursor are one write, so a page paid for is never bought again. Each run
reads the week so far from it, so a refresh pressed by hand cannot spend the week twice, and a run
that cannot write to the ledger stops. The search page keeps to the same budget: once the week is
used up it says so instead of searching. `tools/apollo_budget.py` is the one place the allowance
is worked out. Only LCX Services states a budget; Universal's page and US Production Houses run
as before.

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
- **The Apollo budget:** change `credits_per_week`, `keep_in_reserve` or `credits_per_run` in
  `enrichment`, and `pages_per_run` in `apollo_discovery`; then regenerate and apply `sql/03f`
  as above. `enrichment.enabled: false` stops all of this project's Apollo spending; the free
  sources go on.
- **Another Apollo search:** add it to `apollo_discovery.searches` with its audience, Apollo's own
  tags (check them free on the search page first) and, for a signal, `signal` and
  `posted_within_days` or `funded_within_days`.
- **A slice used up:** clear its `exhausted_at` (and set `next_page` back to 1) in `apollo_cursors`
  to search it again.
- **Tests:** `tools/test_lcx_services.py` (120 checks), the LCX cases in
  `tools/test_enrich_apollo.py` and the deck cases in `tools/test_send.py`.
