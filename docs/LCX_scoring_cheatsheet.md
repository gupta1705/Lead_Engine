# LCX Services: scoring cheat sheet

Scoring v4. The owner decided it on 2026-10-07 with the words "think and decide one". The numbers come from
`config/segment.lcx-services.json` (`rubric`, `score_modifiers`, `gates`, `auto_shortlist`, `enrichment`,
`judge`). `tools/verify_repo.py` fails if this page and the config disagree on any number below.

Nobody types these values in. On every chain run, `tools/lcx_judge.py` sets each input from the lead's own
stored record: its name and domain, its Wikidata, Apollo, FDIC or OpenStreetMap record, and the title,
description and About text the site pass read. Next to each input it writes the phrase it matched, under
`metadata.lcx_judgement`, so the reason is kept on the lead's record. The lead page does not show it yet;
`python tools/lcx_judge.py --explain "<company>"` prints it, writing nothing. Use this page to read a score,
not to write one.

## At a glance

| Setting | Value | Means |
|---|---|---|
| `buyer_confirmed` | 30 | The company's own site uses its audience's words |
| `buyer_size` | 25 | Big enough to pay, small enough to answer, judged by the audience's bands |
| `content_activity` | 20 | Already posts: video and Instagram accounts |
| `audience_fit` | 15 | How directly the 18 services fit this kind of buyer |
| `reachable_decision_maker` | 10 | A named person 1.0, a business inbox 0.5 |
| `buying_trigger` | +8 | Bonus: a reason to buy now |
| `priority_market` | +4 | Bonus: the US, the UK, India or the UAE (half for other English markets) |
| `wrong_buyer` | -50 | Penalty: not a buyer of this |
| `too_big` | -50 | Penalty: too big to answer a cold email, or part of a large group |
| `non_english_site` | -15 | Penalty: its own site is not in English |
| `min_score` | 70 | Shortlisted only when strictly above, with a usable contact and a read site |
| `score_over` | 60 | Apollo looks for a person only when strictly above, and only once the site was read |
| `score_threshold_review` | 50 | Display band |
| `score_threshold_priority` | 85 | Display band |

## How a score is made

- Each input is **0, 0.5 or 1**. The score is the points earned divided by the points assessed, times 100.
  Then each bonus and penalty is added (value times its size), and the result is kept between 0 and 100. This
  is `sql/06_score.sql`, the same for every project.
- **Unknown is not 0.** An input nobody can settle yet, such as a site that hasn't been read or a company
  nobody has measured, is stored as JSON null. It is left out of both sides of the division, so the score is
  out of what is known. The shortlist rule below stops that from rewarding ignorance.
- A bonus or penalty that does not apply is simply absent: it costs nothing.
- Some inputs were retired on 2026-10-07: `established`, `right_size`, `english_market`, and the
  production-house keys the site pass used to write into LCX leads (`genre_fit`, `collaboration_openness`,
  `distribution_relationship`). The judge deletes them on every run, so they are never scored again.

## The five criteria

### `buyer_confirmed`: 30 points

Is the business the kind of buyer it was filed as, in its own words?

- **Full:** its own home page (title, description, About) uses at least two of its audience's words. A hotel
  says rooms, suites or book direct. A school says admissions, curriculum or IB. A developer says apartments,
  villas or off-plan. A bank says loans, mortgages or credit union. The words are in `audiences[].site_words`.
- **Half:**
  - one such word; or
  - a directory that sorts companies says so, and the site says nothing either way. That means Wikidata's
    class or industry, an OpenStreetMap shop or amenity tag, or the FDIC bank register; or
  - a mid-size company (`corporate_teams`) whose site was read and has none of the words. Any employer that
    size is the audience unless the wrong-buyer check says otherwise.
- **None:**
  - only Apollo's keyword search says so, and the company's own site does not back it up. The site may be
    unread, or read with none of the words; or
  - the site that answers is not this company's (neither its name nor its initials appear) and has none of
    the words. When it does have some of the words, the lead keeps half.
- **Unknown:** only for a company saved from the Apollo search page that its own words cannot place in any
  audience.
- A bot wall ("Just a moment", "Access denied") or a parked page does not count as text.

### `buyer_size`: 25 points

Each lead is judged by its audience's own band (`audiences[].size_bands`). The first source that applies is
used: FDIC assets, then revenue (Apollo, or Wikidata after the back-fill), then pupils (schools), then
headcount, then the OpenStreetMap record, then Apollo's search band.

| Audience | Full | Half |
|---|---|---|
| Mid-size companies | 200-5,000 people, or $20M-1B revenue | 50-199 or 5,001-20,000 people; $4-20M or $1-5B |
| Banks and insurers | $1-10bn of assets; 100-5,000 people; $20M-2B | $0.3-1bn or $10-50bn of assets; 20-99 or 5,001-20,000 people |
| Retailers, hotels | 20-5,000 people, or $5M-1B | 5-19 or 5,001-20,000 people; $1-5M or $1-3B |
| Studios and agencies | 11-200 people, or $1-50M | 2-10 or 201-1,000 people; $0.2-1M or $50-250M |
| Cafes, salons, gyms, independent shops | 2-50 people, or $0.2-20M; several locations named on their own site | 1 or 51-200 people; one premises with a website |
| Schools | 300-3,000 pupils (else staff as below) | 100-299 or 3,001-6,000 pupils |
| Brands, developers, publishers, attractions | 20-1,000 people, or $5-500M | 10-19 or 1,001-5,000 people; $1-5M or $0.5-2.5B |

- **Half** also covers a company known only from Apollo's search band, which is a filter rather than a
  measurement.
- **None:** outside both bands. Above them sits a procurement process; below them there is no budget.
- **Unknown:** no source measures it. The lead is then scored out of the other 75 points.

### `content_activity`: 20 points

Does it already pay for content?

- **Full:** a video account (YouTube, TikTok or Vimeo) plus at least one more of those or Instagram. It can be
  linked from its own site, or listed for it on Wikidata or OpenStreetMap.
- **Half:** exactly one of them.
- **None:** the site was read and links none of them. Facebook, X or LinkedIn on their own earn nothing.
- **Unknown:**
  - the site hasn't been read yet, or it refused the reader (robots.txt, a dead domain); and
  - no directory lists an account.
  A directory listing can only raise this input; it never writes 0.

### `audience_fit`: 15 points

The owner's audience table, unchanged.

- **Full:** brands, retailers, real estate, hotels and short stays, publishers, studios and agencies, schools,
  mid-size companies, cafes, salons and gyms, independent shops.
- **Half:** banks and insurers, and attractions. The sale is slower there.

### `reachable_decision_maker`: 10 points

Set by the contact tools (the site pass, `enrich_lcx_services`, `enrich_apollo`), never by the judge. The
judge only writes 0 where there is nothing.

- **Full:** a named person with their own address.
- **Half:** a business inbox the company publishes (info@, hello@).
- **None:** nobody yet.

Whether a lead can be drafted is decided by the shortlist rule below, not by these points.

## Bonuses and penalties

### `buying_trigger`: +8

- **Full:** Apollo's signal searches show it is hiring for training and onboarding, for content and video, or
  for marketing, or it raised money in the last 90 days. This counts in full only once its own site has been
  read and is theirs. Before that it earns half.
- **Half:**
  - hiring frontline staff (sales and service, stores), once its site has been read; or
  - a launch or opening phrase in its own words: "now open", "pre-launch", "admissions open", "we're hiring".
- It fades with age: half after 60 days, gone after 120.
- It is cancelled when `wrong_buyer` is 1.0, because a staffing firm's hiring is its product.

### `priority_market`: +4

- **Full:** based in the US, the UK, India or the UAE (`enrichment.reveal_countries`).
- **Half:** another English-speaking market (`geography.english_markets`).
- **None:** anywhere else.
- **Absent:** the country is unknown.

### `wrong_buyer`: -50

- **1.0:** clear evidence in the company's name, page title or domain. A plain self-description anywhere on
  its site also counts: "a non-profit", "registered charity", "venture capital", "staffing agency", "online
  courses", "AI video studio". The kinds that count:
  - software and SaaS vendors, IT services, payments and POS;
  - staffing, recruitment and outsourcing firms;
  - e-learning, training and AI-content competitors (NIIT, Coursera, FranklinCovey...);
  - universities and business schools filed as anything but a school;
  - charities, associations, societies and institutes;
  - investment firms, holding companies, lessors and ratings agencies;
  - government bodies, including .gov and .mil domains;
  - agencies or software sold to the audience itself;
  - B2B suppliers;
  - a studio US Production Houses already holds.
- **0.5:** the same word only in the description, or a borderline type:
  - asset managers;
  - marketplaces and distributors;
  - liquor stores and drinks distributors filed as brands;
  - commercial property, REITs and lenders filed as developers;
  - news and media titles;
  - consultancies and law firms filed as mid-size companies;
  - a .org domain on a company audience;
  - a non-profit publisher or attraction.
- Schools are exempt from the non-profit, college, institute and academy tests, because an Indian 'Public
  School' is private.
- Legal forms such as 'National Association' and 'Building Society' are taken off before matching.
- The name lists match the whole name once Inc, Ltd or Group is taken off. So 'Kforce Inc' is the staffing
  firm, and 'Beacon Hill School' is not Beacon Hill.
- Why -50: a lead that is perfect in every other way, with both bonuses, still scores only 62.

### `too_big`: -50

- **1.0:**
  - revenue of $2-10B, more than 20,000 people, or more than $50bn of assets;
  - a brand's page on its group's domain (courtyard.marriott.com);
  - its own words say 'is now part of' or 'was acquired by';
  - a parent organisation of over 5,000 people, or a parent on the majors list. On Wikidata that is the
    parent organisation; an owner that is a fund or a state does not count by its size. On Apollo it is a
    parent company we already hold.
- **0.5:**
  - revenue of $1-2B;
  - 5,001-20,000 people, outside mid-size companies;
  - a listed company with revenue over $500M;
  - its own words say it is big or belongs to a group, such as 'one of the largest', 'part of the … group',
    'a subsidiary of', 'a division of', 'investor relations', 'listed on the' or 'Fortune 500'
    (`judge.big_text`);
  - an OpenStreetMap premises whose website is one page of a chain's site.
- Anything bigger is left out by the `not_major` gate.

### `non_english_site`: -15

- **1.0:** the home page's title and description are not in English. Either more than 30% of the letters are
  non-Latin (Chinese, Japanese, Cyrillic, Arabic, Devanagari and the like), or at least three common
  non-English words ('de', 'und', 'het', 'för') outnumber the English ones two to one. When the title and
  description cannot tell, the About paragraph decides.
- **0:** the text reads as English.
- **Absent:** the site hasn't been read, or there is too little text to tell.
- A soft penalty: a strong lead still passes. Language "never leaves anyone out".

## Gates: left out, only on evidence

A gate archives a lead only on evidence. When nothing is known, the lead passes. A shortlisted lead is never
archived by a gate.

| Gate | Fires on |
|---|---|
| `country_allowed` | a country whose law needs consent for cold email: Canada, Germany, Austria, Italy |
| `payable_country` | a sanctioned country LCX cannot invoice: Russia, Belarus, Iran, North Korea, Syria, Cuba (or a .ru, .by, .ir or .su domain when no country is known) |
| `not_major` | a major's own domain (`judge.majors`: a bare name such as `marriott` under any ending, or a full domain such as `paramount.com` for a name that is also a common word), over 50,000 people, revenue of $10B or more, over $100bn of assets, or a parent organisation (Wikidata P749, or Apollo's) on the majors list. A name that only reads like a major's brand is `too_big`'s -50 instead, and an owner (P127, often a fund holding a stake) never archives (2026-10-08) |
| `brand_safe` | adult, gambling, tobacco or weapons words in the name, title or description; a name on `judge.brand_risk_names`; a Wikidata class such as casino; a site taken over by slot spam |
| `site_alive` | a parked or server-default page, or a domain that fails to resolve on two reads at least 7 days apart: neither it nor www. exists. A robots.txt refusal, a timeout, a server error or a DNS hiccup never counts |
| `usable_first_party_presence` | no website and no published address at all |

## The line: who is shortlisted

A lead in To review is shortlisted by itself (`sql/14_auto_shortlist.sql`) when all four hold:

1. Its score is strictly above **70** (`min_score`).
2. It has a contact the drafter will actually write to. For banks and mid-size companies (`named_contact_for`:
   `financial_services`, `corporate_teams`), the contact the drafter picks must be a **named person**, not an
   info@ inbox; a name on accounting@ does not count while info@ ranks above it.
3. Its `content_activity` has been assessed (`require_assessed`): its site was read, or a directory lists its
   accounts.
4. Its own site was read (`require_site_read`: the judge's `site_checked`, its own words or its pages read and
   none a bot wall). A directory listing its accounts is not enough.

A lead over the line that fails 2 or 3 waits in To review. It is shortlisted on the first chain run after it
gets a contact or its site is read. Shortlisting sends nothing: every draft still needs a person's approval.

Why 70: the basics alone stay out, and one real signal from the company carries a lead over.

| Lead | Score | Result |
|---|---|---|
| A directory label, the right size, a full-fit audience, an inbox, a priority market | 64 | stays |
| The same with a named person | 69 | stays |
| The basics plus a strong buying trigger | 72 | crosses |
| The basics plus one video or Instagram account | 74 | crosses |
| The basics plus its own words confirming the audience | 79 | crosses |
| A cafe with its own words, Instagram, one premises and an inbox | 76.5 | crosses |
| A bank whose site confirms it, with YouTube, Instagram and a named person | 96.5 | crosses |
| A perfect lead with both bonuses, but a wrong buyer or too big | 62 | stays |

## Apollo: who is paid for

Apollo looks for a person only at a lead that meets all of these:

- it scores strictly above **60** (`score_over`) and has nobody to write to;
- its own site was read, meaning real text came back and not a bot wall or a parked page
  (`enrichment.require_site_read`);
- the site is the company's own;
- `wrong_buyer` is 0 and `too_big` is under 1;
- it is based in the US, the UK, India or the UAE.

For banks and mid-size companies, an inbox with nobody's name on it counts as nobody to write to. Every
reveal costs a credit, inside 120 a week, with 700 kept in reserve for the other projects. A named person adds
10 points or more, so every paid reveal can carry a lead over 60 past the line.

## Changing a word or a number

The word lists live in the config (`judge` and `audiences[].site_words` / `size_bands`), so a word changes
without code. Edit `config/segment.lcx-services.json`, run `python tools/gen_segment_sql.py lcx-services`, then
apply `sql/03f_segment_lcx_services.sql`. The next chain run judges every lead again. A number on this page is
an owner decision. Change it in the config, on this page and in `tools/verify_repo.py` together.
