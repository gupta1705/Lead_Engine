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

Later that day the owner settled how its leads are rated: "think and decide one". Scoring v4 asks
first whether a business really is a buyer for us. It leaves out sanctioned countries, adult,
gambling, tobacco and weapons businesses, and companies too big to answer a cold email. It
shortlists a lead only once its site has been read and it has someone to write to, and for banks
and mid-size companies that must be a named person. See [The score](#the-score) and
`docs/LCX_scoring_cheatsheet.md`.

The services are the 18 on `docs/LCX Services.pdf`, in three clusters: Repurposing as a Service
(4), AI Asset Creation (8) and Tech Solutions (6).

## Who it finds

Every service has buyers; an **audience** is one kind of buyer, the services it is pitched first,
and where it is found (`config/segment.lcx-services.json`, `audiences`). Since 2026-10-13 the email
pitches ONE lead service per lead (see *The lead service*); the audience's first service is only the
fallback when no rule matches, and the rest show on the lead as *Also fits*.

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
  most 80). Taken 10-5,000 people first, then unknown size, then larger; over 50,000 never,
  because the `not_major` gate would archive them (the line was 100,000 until 2026-10-07).
  Within each size, English-speaking markets come first, then unknown countries, then the rest
  (the email and the deck are in English). For every 50 companies staged it also fetches, free,
  what the judge reads: YouTube, TikTok and Instagram accounts, revenue, pupils, parent company
  and class. `python tools/lcx_judge.py --backfill-wikidata` fetches the same for leads saved
  before.
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
| `promote_chain` | `tools/run_chain.py` | Self-exclusion, promote, dedupe, judge inputs (`tools/lcx_judge.py`), zero-unverified, score, gates, auto-shortlist. |
| `enrich_lcx_services` | `tools/enrich_lcx_services.py` | The address a business published becomes a contact; the audience, services, place, size and buying signal go on the lead. |
| `enrich_contacts_lcxs` | `tools/enrich_sitescrape.py --limit 1000` | The polite site pass: robots.txt honoured, never LinkedIn. It keeps the home page's words, language and linked accounts for the judge. A domain that does not resolve is stamped (`dead_since`) and read once more 7 days later. |
| `promote_chain` | | Judges again on the site text just read, and scores; leads with a usable contact and a read site cross the line. |
| `enrich_apollo_lcxs` | `tools/enrich_apollo.py --limit 200` | A lead scoring over 60 whose own site was read, not the wrong buyer nor too big, with still nobody to write to: the right person, from Apollo, inside the week's budget. |
| `promote_chain` | | Scores what the steps found; a named person found by Apollo carries a lead over the line. |

Then the scheduler's outreach tick drafts each shortlisted lead with an address, from the one
template, with the deck attached. A person approves (one at a time or a spot-checked batch), and
it goes from their own Gmail inside its daily limit, at its own random minute between 10:00 and
10:30 on its recipient's clock, Monday to Friday (`outreach.send_window`, the owner, 2026-10-12;
`docs/runbook.md`, *Goes out*). Where the company is comes from its records here: the recipient's
own Apollo record, the FDIC's state for a bank, OpenStreetMap's city, Wikidata's country, a phone's
area code; one with no place at all goes at New York's 10:00. The Apollo search page stays for
adding a lead by hand; what it spends there counts in the same week.

## Apollo: who is paid for, and the budget

The free ways come first: the address a business publishes, then its own website. Only a lead
that fits well and still has nobody to write to goes to Apollo (the owner, 2026-10-07: reveals
only for leads over 60 whose own site was read and that are not the wrong buyer):

- it scores over 60 (`score_over`);
- its own site was read, real text and not a bot wall (`require_site_read`), and is the
  company's own;
- `wrong_buyer` is 0 and `too_big` is under 1;
- nobody to write to. For banks and mid-size companies (`auto_shortlist.named_contact_for`), an
  inbox with nobody's name on it counts as nobody, because the shortlist needs a named person
  there.

A named person adds 10 points or more, so every reveal can carry a lead over 60 past the line
of 70. For each lead that qualifies:

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

Scoring v4, decided by the owner on 2026-10-07 ("think and decide one"), on a simulation over the
2,402 leads held that day. It asks first "is this really a buyer for us?". What earns full, half
and none for every input is on `docs/LCX_scoring_cheatsheet.md`; `tools/verify_repo.py` fails if
that page, the config and `sql/03f` disagree on a number.

**Who sets the inputs.** Nobody types them in. `tools/lcx_judge.py` is a step of every promote
chain, after the merge and before `sql/04b`. It sets each input from what is stored on the lead:
- its name and domain;
- its Wikidata, Apollo, FDIC or OpenStreetMap record;
- the title, description and About text the site pass read, and the accounts that site links.

The word lists are in the config (`judge`, `audiences[].site_words`, `audiences[].size_bands`),
so a word changes without code. The judge writes the phrase it matched under
`metadata.lcx_judgement`. It leaves only `reachable_decision_maker` to the contact tools. An input
nobody can settle yet is JSON null: it is left out of the score, which is then out of what is
known, rather than counted as 0.

| Criterion | Points | Full | Half | None |
|---|---|---|---|---|
| `buyer_confirmed`: the buyer it was filed as, in its own words | 30 | two of its audience's words on its own site | one word; a directory's label (Wikidata, OpenStreetMap, FDIC) the site does not contradict; a mid-size company whose own site has none of the words | only Apollo's keyword search says so; the site is not the company's |
| `buyer_size`: big enough to pay, small enough to answer | 25 | inside its audience's band: mid-size companies 200-5,000 people, banks $1-10bn of assets, cafes 2-50 people or several locations | the band either side; one premises; Apollo's search band alone | outside both |
| `content_activity`: already posts | 20 | a video account and one more (YouTube, TikTok, Vimeo, Instagram) | exactly one | the site was read and links none |
| `audience_fit` | 15 | every audience except two | banks and insurers; attractions | |
| `reachable_decision_maker` | 10 | a named person | a business inbox | nobody yet |

| Bonus or penalty | Size | When |
|---|---|---|
| `buying_trigger` | +8 | Apollo's signal searches (hiring trainers or content people, marketing for a launch, funded in the last 90 days), once its own site is read. Half for frontline hiring, or "now open" and the like in its own words. Half after 60 days, gone after 120; never for a wrong buyer. |
| `priority_market` | +4 | the US, the UK, India or the UAE; half for another English-speaking market |
| `wrong_buyer` | -50 | a software or SaaS firm, a staffing agency, an e-learning competitor, a university, a charity or association, an investor or lessor, a public body, or a vendor to the audience itself. Half for a borderline type, or the word only in the description. |
| `too_big` | -50 | revenue of $2-10B, over 20,000 people, over $50bn of assets, a brand's page on its group's domain, or part of a large group. Half for $1-2B or 5,001-20,000 people. |
| `non_english_site` | -15 | its own site is not in English |

**Gates** archive a lead only on evidence. When nothing is known the lead passes, and a
shortlisted lead is never archived.
- `country_allowed`: Canada, Germany, Austria and Italy, where cold email needs consent. Unchanged.
- `payable_country`: the sanctioned countries LCX cannot invoice (Russia, Belarus, Iran, North
  Korea, Syria, Cuba).
- `not_major`: a major's own domain or a parent organisation on the majors list (`judge.majors`),
  over 50,000 people, $10B of revenue or $100bn of assets. A name that only reads like a major's
  brand costs 50 points (`too_big`) instead of archiving the lead.
- `brand_safe`: adult, gambling, tobacco or weapons, or a site taken over by slot spam.
- `site_alive`: a parked or default page, or a domain that did not resolve on two reads at least 7
  days apart.
- `usable_first_party_presence`: no website and no address. Unchanged.

**The line is 70.** A lead in To review is shortlisted by itself (`sql/14_auto_shortlist.sql`)
only when all four hold:
1. its score is strictly above 70 (`min_score`);
2. it has a contact the drafter will write to (`require_contact`: the same test `tools/outreach.py`
   drafts by), and for banks and mid-size companies (`named_contact_for`) a named person, not an
   info@ inbox;
3. its `content_activity` was assessed (`require_assessed`): its site was read, or a directory
   lists its accounts;
4. its own site was read (`require_site_read`), not only listed by a directory. The site pass
   reads, once, every lead without a read site, including those whose address came with the
   harvest.

The basics alone stay out: a directory label, the right size, a full-fit audience, an inbox and a
priority market score 64, or 69 with a named person. One real signal from the company carries a
lead over: a strong trigger 72, one video or Instagram account 74, its own words 79. A perfect lead
with both bonuses that is the wrong buyer or too big scores 62. A lead over the line that fails 2
or 3 waits in To review, and the chain's log says how many did. It is shortlisted on the first
chain run after it passes. Its reason (`status_reason`) then says which tests it passed.

Display bands: review 50, priority 85.

**Retired 2026-10-07**, deleted by the judge on every run and no longer written by the site pass
here:
- `established`, 1.0 on almost every lead, so it separated nobody;
- `right_size`, which scored a missing Wikidata headcount as 0 and carried the production houses'
  team-page rule (2-20 named staff) into 131 LCX leads;
- `english_market`, replaced by `priority_market`;
- the production-house keys the site pass wrote into LCX leads (`genre_fit`,
  `collaboration_openness`, `distribution_relationship`).

**Switching it on** is one deployment, in this order:
1. the code: the judge step in `tools/run_chain.py`, `sql/14`, the site pass, discovery and
   `enrich_apollo`. On the old config the judge step, `sql/14`, the site pass and `enrich_apollo` do
   what they did before; discovery stages the new, smaller set of inputs at once, so steps 1 and 2 go
   out together, with no harvest between them;
2. `python tools/run_sql.py sql/03f_segment_lcx_services.sql`;
3. `python tools/lcx_judge.py --backfill-wikidata`;
4. `SEGMENT_SLUG=lcx-services python tools/run_chain.py`.

`sql/03f` applied alone would score every lead on inputs nobody has written yet. Leads already
shortlisted under the old score are never un-shortlisted by the rule. What to do with those that
no longer qualify is the owner's call.

## The email and the deck

The owner's review of the v2 emails (2026-10-13) changed the email to **problem first, one service**
(template `lcx_services_problem_v3`). v2 (`lcx_services_deck_v2`, "18 things LCX can do", two services)
and v1 are kept only for the drafts already written with them; they cannot be approved once
`sql/03f` is live, because their sign-off still reads LCX. They are re-drafted separately.

- **Subject:** the lead service's own, at most five words, no dash and no colon
  (`generated_pitch.service_copy[<service>].subject`). `outreach.subject_max_words` is 5: a rendered
  subject over the cap falls back to the template's `subject_fallback` ("An idea for your business"),
  and approval refuses any stored subject over the cap.

  | Lead service | Subject |
  |---|---|
  | Reel Forge | One video, many reels |
  | Airbnb / Property Content | Your property photos, in motion |
  | AI VFX + Animation | Bigger scenes, same footage |
  | Audiobooks and Audio Web Shows | Your backlist, as audio shows |
  | AI Video for Brands | Campaign videos without the shoot |
  | AI Real Estate Visualisation | Walkthroughs before the first brick |
  | Explainer Videos | One video, fewer questions |
  | Shop Display Videos | What's on your store screens? |
  | AI UGC Product Videos | Your brand's own AI creator |
  | AI Podcasts / Audio Content | Your products, as a conversation |
  | Virtual Tours for Schools | Field trips without the bus |
  | AI Reality Experiences | A new reason to visit |
  | Creator × Brand Marketplace | Finding the right micro influencers |
  | Local Business Tech and Automation | Less admin behind the counter |
  | AI Business Assistant | Ask your business a question |
  | AI Simulations for Training | Rehearse before the real customer |
  | AI Fashion Stylist | A mirror that completes outfits |
  | AI Onboarding Employee | The same training, every hire |

- **Body**, top to bottom:
  1. The greeting (`outreach.greeting`): "Hello <first name>," and "I trust you are well." when a
     person is named, else "Hello,". Never "Hi there".
  2. **The problem**: one sentence about a problem a business like this usually has. Never their
     metrics, awards or achievements, never a question, no number.
  3. **The solution**: how the ONE lead service solves it, naming that service once, exactly as
     the deck names it.
  4. Who we are, in the deck's words: "I'm writing from LCX, where we repurpose what a business
     already owns, create new content and experiences with AI, and build the tools teams use every
     day. Our services deck is attached."
  5. One small ask: "Would it be useful if I sent you a few examples, along with a short note on how
     this could work for {{company}}?" `{{company}}` is the name as a person writes it (a tagline,
     ® or ™, "Official", a foreign legal form cut off), or "your team" when it is still long.
  6. The footer: "Warm regards," the approver's name, and "<title>, LCX". No postal address, no
     opt-out line (the owner, 2026-10-13: "remove the last line from every single service"). Any
     reply that is not neutral still stops all mail to that address.
- **Lines 2 and 3** are written by Groq (`outreach.generated_pitch`, `tools/llm.py` `LCXS_SYSTEM` v3,
  `check_lcxs`) when the lead has words of its own on record or a fresh buying signal; otherwise, or
  when the model's answer fails its checks twice, they are the service's fixed lines in
  `service_copy` (with `by_audience` variants for banks and studios). The model is handed only
  `tools/draft_render.lcxs_facts()`: its kind, its own words, the accounts it posts on and the one
  lead service. It never sees or names the company or the person. The checks refuse a dash of any
  kind, a number in the problem, a number in the solution that is not in the deck's line, another
  service or an invented one, the company, a place, praise ("award-winning"), a diagnosis ("you
  are losing"), quotes, links and emoji. The model may answer `no_fit` instead; that lead is held.
- **No dash anywhere:** every inserted value and the whole email above the footer are cleaned
  (`draft_render.dash_clean`), and a draft that still has an em dash, en dash, figure dash,
  horizontal bar or minus used as punctuation is refused.
- **The draft gate:** a lead the rules call **Not a buyer** is never drafted. **Check service** (a
  hold rule matched, the model said `no_fit`, or the service came only from the audience with nothing
  to confirm it) and **Read site first** (found by Apollo, site not read, and no person picked the
  service) are skipped and named in the draft log.
- **Approval:** a draft with model-written text is approved one at a time
  (`batch_approval.allow_generated` false). Every approver needs a name and a title in their
  profile; the email goes out signed with them. The outreach row records the service it pitched
  (`outreach.service`, `sql/35`), and that field cannot change once the email is sent.
  Tests: `tools/test_lcxs_v3.py` (the copy, the greeting, the footer, every rule, the checks, the
  gate) and `tools/test_lcxs_pitch.py` (the facts, the checks, the writer).

## The lead service

Each lead is tagged with ONE lead service (`lead_service` in the config; `tools/lcx_judge.py`
`choose_service`, every chain run, after the scoring inputs). It is stored on the lead as
`metadata.lead_service` = {service, rule, basis, reason, evidence, set_by, decided_at}.

1. **Not a buyer** first: `wrong_buyer` of 1, or a name that is not a buyer in its audience (a
   racing team among retailers, a law or investment firm among property companies).
2. Then the rules in order; the first that matches wins. **Signal** rules (a live Apollo hiring
   signal), then **fact** rules (what the lead's own site, Wikidata or OpenStreetMap says: publishes
   books, sells off-plan, lists rentals, a school, an attraction, a cafe, stores with screens, a
   contact centre, a large workforce, a product that needs explaining, a brand on TikTok), then
   **type** rules (a developer, a hotel, a brand, a bank). Two **hold** rules (a studio that sells
   visual effects or animation itself) leave the service for a person to pick.
3. Nothing matched: the first service its audience is pitched (`basis` audience). No audience on
   record: held.
4. A person's pick (`set_by` is their email, from **Change service** on the lead sheet) is never
   undone by the rules. An unchanged tag keeps the day it was decided.

The **Leads** and **Board** pages have a tab per service with its count, plus **Check service** and
**Not a buyer**; a tab with no leads is hidden. The lead sheet shows the service, why, and what else
fits. `python tools/lcx_judge.py --explain "<company>"` prints the tag the rules would give.
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

- **When emails go:** `outreach.send_window` (10:00-10:30 on the recipient's clock; `"timezone_of":
  "sender"` puts every email on India's clock instead, `"enabled": false` sends as soon as approved),
  then `python tools/gen_segment_sql.py lcx-services` and `python tools/run_sql.py
  sql/03f_segment_lcx_services.sql`. Times already drawn under the old setting are drawn again.
- **Another kind of buyer, a class, a tag, a city:** edit `audiences` or `osm_discovery.cities`,
  then `python tools/gen_segment_sql.py lcx-services` and `python tools/run_sql.py
  sql/03f_segment_lcx_services.sql`. The next Friday finds them.
- **A word the judge reads** (a staffing firm's name, a major's domain, a hotel's words): edit
  `judge` or `audiences[].site_words` the same way. The next chain run judges every lead again.
  `python tools/lcx_judge.py --explain "<company>"` shows what it would decide for the leads of
  that name, in a read-only transaction (before `sql/03f` is applied, add
  `--config config/segment.lcx-services.json`). A weight, the line or `score_over` is an owner decision: change it in the
  config, on the cheat sheet and in `tools/verify_repo.py` together.
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
- **The email's copy** (a subject, a problem or solution line, a rule): edit `generated_pitch.service_copy`
  or `lead_service.rules`, then regenerate and apply `sql/03f` as above, and run `tools/test_lcxs_v3.py`.
- **Tests:** `tools/test_lcxs_v3.py` and `tools/test_lcxs_pitch.py` (offline: the v3 email, the lead
  service, the model's checks), `tools/test_lcx_services.py` (the score's line worked out from the
  config, and a cafe, a brand, a mid-size company and an unread site taken from the harvest to a
  draft), `tools/test_lcx_judge.py` (144 checks, offline: every misfire the simulation found and
  each input's full, half, none and unknown), the LCX cases in `tools/test_enrich_apollo.py` and
  the deck cases in `tools/test_send.py`.
