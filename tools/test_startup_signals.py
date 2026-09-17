#!/usr/bin/env python3
"""test_startup_signals.py -- the headline rules, as a regression table.

    python tools/test_startup_signals.py

Every case is a real headline from the first collection (2026-09-17): Google
News RSS, distress windows July 2024 to September 2026 and Mumbai funding
windows 2021 to mid-2024. The wrong answers the first extractor gave are cases
here too ("Cred's", "300", "Four Years", the creditor instead of the debtor),
so a rule change that brings one back fails loudly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import startup_signals as ss

# (headline, kind, company, city)   company None = must name nobody
CASES = [
    ("Food delivery startup Thrive to shut down operations amid intense competition", "shutdown", "Thrive", None),
    ("Peak XV-backed Kenko Health shuts down after running out of funds", "shutdown", "Kenko Health", None),
    ("Elevation Capital-backed AI Fashion Startup Alle Shuts Down", "shutdown", "Alle", None),
    ("Exclusive: Stellaris-Backed BeepKart Shuts Down", "shutdown", "BeepKart", None),
    ("Warburg Pincus-backed Whatfix lays off 6% of staff; trims sales, marketing roles", "layoffs", "Whatfix", None),
    ("ISN Exclusive: Peak XV-backed Pristyn Care sacks 50 employees in cost cutting move", "layoffs", "Pristyn Care", None),
    ("ISN Exclusive: Shark Tank-featured jeans startup Freakins fires 10% of its employees", "layoffs", "Freakins", None),
    ("Abrupt layoffs at Talrop: Nearly 300 employees awaiting pending wages", "salary_delays", "Talrop", None),
    ("Kavin Bharti Mittal to shut down Hike after India's real-money gaming ban", "shutdown", "Hike", None),
    ("Hike, the 13-year-old startup, shuts down; founder Kavin Mittal terms it difficult decision", "shutdown", "Hike", None),
    ("Ireda files insolvency plea against Gensol over Rs 510 crore default", "insolvency", "Gensol", None),
    ("M2P Fintech to acquire Mad Street Den in distress sale", "distress_sale", "Mad Street Den", None),
    ("Sugar Cosmetics seeks ₹100-150 crore rescue funding at steep valuation cut", "down_round", "Sugar Cosmetics", None),
    ("Scoop: Credit card startup Uni eyes fresh funds at over 70% valuation cut amid RBI curbs", "down_round", "Uni", None),
    ("Cred’s Valuation Slashed By 45% In New Funding Round, Now Valued At $3.5 Billion", "down_round", "Cred", None),
    ("Four Years After Raising $3.5m, Nigerian Edtech Startup Edukoya Shuts Down, Cites Market Conditions",
     "shutdown", "Edukoya", "outside"),
    ("Mumbai-based Fintech Startup TransBank Secures $1mn In Seed Round", "funding", "TransBank", "mumbai"),
    ("Mumbai’s GetSetHome Secures $1 Million in Seed Funding from Mistry Ventures", "funding", "GetSetHome", "mumbai"),
    ("Mumbai-based D2C brand Skillmatics raises $16 million in funding led by Sofia Ventures", "funding", "Skillmatics", "mumbai"),
    ("Drone tech startup Enercomp raises Rs 2 Cr in bridge round", "bridge_round", "Enercomp", None),
    ("'Shocked, worried, broken': Mumbai's Habitat to shut down after vandalism over Kunal Kamra show",
     "shutdown", "Habitat", "mumbai"),
    ("Leap.club shuts down, cofounder Das joins Google", "shutdown", "Leap.club", None),
    ("Livspace lays off 1,000 employees, cofounder Saurabh Jain exits", "layoffs", "Livspace", None),
    ("Audiotech startup Pocket FM lets go of around 200 writers; Here’s why", "layoffs", "Pocket FM", None),
    ("Former Udaan executives' quick fashion delivery startup Klydo halts operations", "shutdown", "Klydo", None),
    ("Flipkart-backed NeuroPixel.AI announces shutting down operations", "shutdown", "NeuroPixel.AI", None),
    ("Kenko Health shuts down; investors drag insurtech startup to NCLT", "shutdown", "Kenko Health", None),
    ("Shark Tank India-featured Patilkaki raises funding from Cap70 Angels, others", "funding", "Patilkaki", None),
    ("Jaibir Nihal Singh-founded TraqCheck raises funding at $17 million valuation", "funding", "TraqCheck", None),
    # nobody, or not one company
    ("From Byju’s, Koo to Bluelearn: 7 Indian startups that went from hype to layoffs and shutdowns", None, None, None),
    ("[Funding roundup] Human Edge, MyMuse, Algomage, Bored Beverages, Perpetuity Capita secure deals", None, None, None),
    ("Funding and acquisitions in Indian startups this week [Aug 17 - Aug 22]", None, None, None),
    ("2 Lakh+ Kirana Stores Shut Down with Quick Commerce Surge in India", "shutdown", None, None),
    ("Bryan Johnson to Shut Down Anti-Ageing Company? Real Reason Behind Biohacker's Plan REVEALED", "shutdown", None, None),
    ("Indian IT Startup Shuts Down Overnight, 19 Employees Laid Off On Video Call", "shutdown", None, None),
    ("Life in Bengaluru: ‘When we shut down our startup, we celebrated’", "shutdown", None, None),
    ("Tech layoffs top 73,000 in 2026 as AI drives cuts at Meta, Oracle, others", "layoffs", None, None),
    ("A Year Of Pink Slips: Around 9,500 In Blues As Startups Cut Jobs", "layoffs", None, None),
    # an NCLT nod for a merger or a move is not insolvency
    ("Meesho Secures NCLT Nod to Shift HQ to India, Inches Closer to IPO", None, None, None),
    # wrong answers from the first full run (2026-09-17)
    ("\"Hits The Right Chords\": Unacademy CEO's Reply On Startup Failure Before Mass Layoffs", "layoffs", None, None),
    ("Exclusive: Prime Venture Partners Backed Dozee Lays Off Around 40 Employees", "layoffs", "Dozee", None),
    ("Unions are getting a boost in Bengaluru tech industry. Byju’s layoffs was a catalyst", "layoffs", "Byju", None),
    ("\"America, I Love You\": Indian Woman's Tearful Goodbye As She Leaves US After Being Laid Off", "layoffs", None, None),
    ("Tech layoffs in January 2026: From Amazon to Pinterest, list of companies cutting jobs", "layoffs", None, None),
    ("Work at a Startup? Your Job is Far More Prone to Layoffs Than You Think", "layoffs", None, None),
    ("Sarvam’s Voice Stack, Layoffs At Interview Kickstart & More", "layoffs", "Interview Kickstart", None),
    ("'I Got Laid Off Before I Even Received My Offer Letter': Indian Woman Says She Lost Her US Job In Just 6 Mo",
     "layoffs", None, None),
    ("Silent layoffs: Around 35,000 tech jobs may be eliminated this year; India’s IT sector sees AI shift", "layoffs", None, None),
    ("Women-centric finance app SALT halts operations", "shutdown", "SALT", None),
    ("1K Kirana Collapse: Bankruptcy, Distress Sale Loom for Info Edge-Backed Kirana Tech Startup", "shutdown", "1K Kirana", None),
    ("NCLT orders probe against Byju's RP, ousted creditors Glas Trust, Aditya Birla back in CoC", "insolvency", None, None),
    ("Behind bankruptcy plea of London start-up: It hired 700 Indian engineers to pose as AI tools", "insolvency", None, None),
    # an insolvency headline, but a dispute dismissed or withdrawn names nobody in trouble
    ("Corporate insolvency: NCLAT dismisses plea against Nuvoco’s Vadraj acquisition; tribunal backs NCLT appro",
     "insolvency", None, None),
    ("Ola-Rosmerta Dispute Resolved, Insolvency Petition Withdrawn", "insolvency", None, None),
    ("Beyond insolvency: Rethinking resolution strategies for India’s stressed real estate sector", "insolvency", None, None),
    ("Dunzo Looking For A Distress Sale To Address Financial Woes: Report", "distress_sale", "Dunzo", None),
    ("BluSmart Drivers Stage Protest Over Unpaid Salaries, Abrupt Job Losses", "salary_delays", "BluSmart", None),
    ("Malaysia Shuts Down Network School Founded by Balaji Srinivasan", "shutdown", None, None),
    ("Snabbit Strengthens Leadership with Acquihire of Pync Founders", "acquisition_talks", "Pync", None),
]

# resolve(): the kind after deciding whether the whole company or one unit closed
RESOLVE = [
    ("Zomato shuts down intercity food delivery service Legends", "unit_shutdown", "Zomato"),
    ("Proptech startup Localize shuts down US operations amid real estate crisis", "unit_shutdown", "Localize"),
    ("Peak XV-backed Kenko Health shuts down after running out of funds", "shutdown", "Kenko Health"),
    ("Kavin Bharti Mittal to shut down Hike after India's real-money gaming ban", "shutdown", "Hike"),
    ("Quick Fashion Startup Blip Shuts Shop", "shutdown", "Blip"),
    ("Food delivery startup Thrive to shut down operations amid intense competition", "shutdown", "Thrive"),
    # constructed, not collected: a three-word company name that reads like a person's
    ("Mad Street Den lays off 30% of its staff", "layoffs", "Mad Street Den"),
]

MONEY = [
    ("Mumbai-based Fintech Startup TransBank Secures $1mn In Seed Round", 1_000_000),
    ("Drone tech startup Enercomp raises Rs 2 Cr in bridge round", 2e7 / 85.0),
    ("Algomage raises $850k in pre-seed funding", 850_000),
    ("Mumbai-based D2C brand Skillmatics raises $16 million in funding", 16_000_000),
    ("The Health Factory startup raises INR 2 crore expanded seed funding", 2e7 / 85.0),
    # what a number measures matters (first run, 2026-09-17)
    ("Lending platform Niro shuts down after $100m AUM milestone", None),
    ("Jaibir Nihal Singh-founded TraqCheck raises funding at $17 million valuation", None),
    ("Vast cuts 46 jobs while advertising 277 openings after $500 million raise", 500_000_000),
]

SECTORS = {"1": {"label": "Media, content, consumer attention", "words": ["media", "content", "gaming", "edtech", "audio"]},
           "0.5": {"label": "Consumer brands and apps", "words": ["d2c", "food delivery", "fashion", "beauty"]},
           "0": {"label": "Other", "words": ["fintech", "saas", "insurtech"]}}
SECTOR_CASES = [("Food delivery startup", 0.5), ("Audiotech startup", None), ("edtech startup", 1.0),
                ("Fintech startup", 0.0), ("D2C beauty brand with a media arm", 1.0)]


CFG = {"startup_discovery": {"sector_tiers": SECTORS, "major_companies": ["Zomato", "Byju's"]}}


def _ev(track, kind, strength, months_ago, title, amount=None, rnd=None):
    import datetime as dt
    when = (NOW - dt.timedelta(days=int(months_ago * 30.44))).isoformat()
    return {"track": track, "kind": kind, "strength": strength, "title": title, "publisher": "Inc42",
            "link": "https://news.example/%s/%s" % (kind, months_ago), "published_at": when,
            "amount_usd": amount, "round": rnd, "descriptor": ""}


def _now():
    import datetime as dt
    return dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc)


NOW = _now()

# score_inputs(): situation -> the inputs that must come out (only the keys listed are checked)
SCORING = [
    ("fresh shutdown of a small Mumbai edtech, site says closed",
     dict(name="Bluelearn", events=[_ev("distress", "shutdown", 1.0, 2, "Edtech startup Bluelearn to shut down"),
                                   _ev("funding", "funding", 0.0, 40, "Bluelearn raises $3 Mn in seed round", 3e6, "seed")],
          geo={"headline": [], "news": {}}, site={"status": "closed", "city": "mumbai", "city_phrase": "Andheri East, Mumbai 400069"},
          app=None),
     {"distress_evidence": 1.0, "distress_recency": 1.0, "mumbai_confirmed": 1.0, "geography_signal": "mumbai",
      "small_deal": 1.0, "tvf_fit": 1.0, "major_or_oversized_signal": False, "long_dead": 0.0, "recently_funded": 0.0}),
    ("the quiet cohort: a 2022 seed, nothing since, the domain gone",
     dict(name="GetSetHome", events=[_ev("funding", "funding", 0.0, 48, "Mumbai's GetSetHome Secures $1 Million in Seed Funding", 1e6, "seed")],
          geo={"headline": [["mumbai", "Mumbai's", "Mumbai's GetSetHome Secures $1 Million"]], "news": {}},
          site={"status": "unreachable"}, app=None),
     {"distress_evidence": 0.5, "mumbai_confirmed": 1.0, "small_deal": 1.0}),
    ("a funded startup with a live site is not quietly struggling",
     dict(name="Kutuki", events=[_ev("funding", "funding", 0.0, 40, "Kutuki raises $2 Mn", 2e6, "seed")],
          geo={"headline": [], "news": {"mumbai": 2, "outside": 0}}, site={"status": "up", "city": None}, app=None),
     {"distress_evidence": 0.0, "mumbai_confirmed": 0.5, "something_to_keep": 1.0, "activity_signal": "active"}),
    ("placed elsewhere by its own website",
     dict(name="Klydo", events=[_ev("distress", "shutdown", 1.0, 2, "Quick fashion delivery startup Klydo halts operations")],
          geo={"headline": [], "news": {"mumbai": 1, "outside": 0}}, site={"status": "closed", "city": "outside"}, app=None),
     {"geography_signal": "outside_mumbai", "mumbai_confirmed": 0.0}),
    ("a big raise and a listed name are not cheap",
     dict(name="Zomato", events=[_ev("distress", "unit_shutdown", 0.5, 7, "Zomato shuts down intercity food delivery service Legends")],
          geo={}, site=None, app=None),
     {"major_or_oversized_signal": True, "distress_evidence": 0.5, "distress_recency": 0.5}),
    ("a $60M round is past the cap",
     dict(name="Blip", events=[_ev("distress", "layoffs", 1.0, 3, "Blip lays off 30%"),
                              _ev("funding", "funding", 0.0, 20, "Blip raises $60 Mn in Series B", 6e7, "series_b_plus")],
          geo={}, site=None, app=None),
     {"major_or_oversized_signal": True, "small_deal": 0.0}),
    ("sold after the trouble",
     dict(name="Pync", events=[_ev("distress", "shutdown", 1.0, 8, "House-help startup Pync shuts down amid fierce competition"),
                              _ev("sale", "acquired", 0.0, 8, "Snabbit acquires Pync founders")],
          geo={}, site=None, app=None),
     {"acquired_signal": True}),
    ("an ordinary round last quarter outweighs a pivot",
     dict(name="Stratzy", events=[_ev("distress", "pivot", 0.5, 6, "Stratzy pivots to advisory"),
                                 _ev("funding", "funding", 0.0, 3, "Stratzy raises $4 Mn in seed round", 4e6, "seed")],
          geo={}, site=None, app=None),
     {"recently_funded": 1.0}),
    ("shut down two years ago: still listed, but penalised; four years ago: long gone",
     dict(name="Otipy", events=[_ev("distress", "shutdown", 1.0, 20, "Otipy shuts down")], geo={}, site=None, app=None),
     {"long_dead": 1.0, "distress_evidence": 1.0, "distress_recency": 0.0, "activity_signal": "active"}),
    ("an investor called Unicorn India Ventures does not make a startup a unicorn",
     dict(name="StampMyVisa", events=[_ev("distress", "bridge_round", 0.5, 11, "StampMyVisa raises Rs 4 Cr in bridge round led by Unicorn India Ventures",
                                          4e7 / 85, "bridge")], geo={}, site=None, app=None),
     {"major_or_oversized_signal": False, "small_deal": 1.0, "distress_evidence": 0.5}),
    ("a CEO who shares his mistakes is not a listed company",
     dict(name="Parker", events=[_ev("distress", "insolvency", 1.0, 10, "As one of America's biggest Fintech startup Parker files for bankruptcy; CEO shares 6 'mistakes' he says")],
          geo={}, site=None, app=None),
     {"major_or_oversized_signal": False}),
    ("a site that refuses robots is not a dead site",
     dict(name="Wify", events=[_ev("funding", "funding", 0.0, 40, "Wify raises $3 Mn in pre-Series A round", 3e6, "pre_series_a")],
          geo={}, site={"status": "error", "note": "wify.co.in homepage: HTTP 403"}, app=None),
     {"distress_evidence": 0.0}),
    ("nothing heard for four years",
     dict(name="Oldco", events=[_ev("funding", "funding", 0.0, 50, "Oldco raises $1 Mn", 1e6, "seed")], geo={}, site=None, app=None),
     {"activity_signal": "confirmed_dormant"}),
]


def main():
    fails = 0
    for label, kw, want in SCORING:
        si, _out = ss.score_inputs(kw["name"], kw["events"], kw["geo"], kw["site"], kw["app"], CFG, NOW)
        bad = {k: (v, si.get(k)) for k, v in want.items() if si.get(k) != v}
        if bad:
            fails += 1
            print("FAIL scoring: %s\n     want/got %s" % (label, bad))
    for title, kind, company, city in CASES:
        e = ss.event_for(title)
        got_kind = e["kind"] if e else None
        got_co = ss.company_for(title, e) if e else None
        got_city = ss.city_for(title, got_co)[0] if got_co else None
        ok = got_kind == kind and got_co == company and (company is None or got_city == city)
        if not ok:
            fails += 1
            print("FAIL %s\n     want kind=%r company=%r city=%r\n     got  kind=%r company=%r city=%r"
                  % (title, kind, company, city, got_kind, got_co, got_city))
    for title, kind, company in RESOLVE:
        r = ss.resolve(title) or {}
        if r.get("kind") != kind or r.get("company") != company:
            fails += 1
            print("FAIL resolve %s\n     want %r %r, got %r %r" % (title, kind, company, r.get("kind"), r.get("company")))
    for title, want in MONEY:
        got = ss.money_usd(title)
        if (want is None) != (got is None) or (want is not None and abs(got - want) > 1):
            fails += 1
            print("FAIL money %s: want %s got %s" % (title, want, got))
    for text, want in SECTOR_CASES:
        got = ss.sector_for(text, SECTORS)[0]
        if got != want:
            fails += 1
            print("FAIL sector %r: want %s got %s" % (text, want, got))
    total = len(CASES) + len(RESOLVE) + len(MONEY) + len(SECTOR_CASES) + len(SCORING)
    print("%d of %d checks passed" % (total - fails, total))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
