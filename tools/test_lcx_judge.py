#!/usr/bin/env python3
"""test_lcx_judge.py -- LCX Services' input judge (tools/lcx_judge.py), offline, as a regression table.

    python tools/test_lcx_judge.py

The owner, 2026-10-07, on the scoring design: "think and decide one". Decided that day (scoring v4): the
rubric asks "is this really a buyer for us?" first; sanctioned countries, adult / gambling / tobacco / weapons
businesses and companies too big to answer a cold email are left out; banks and mid-size companies need a
named person; -15 for a website not in English. Every input is set by tools/lcx_judge.py from the lead's own
stored record against the word lists in config/segment.lcx-services.json, and judge(lead, cfg) is pure, so
every recipe is checked here on synthetic leads with no database and no network.

Checked, against the REPO config (what will be applied with sql/03f):
  * every misfire the 2026-10-07 simulation found on the 2,402 live leads, and the case it was mistaken for
    (a 'National Association' bank, Beacon Hill School and the staffing firm Beacon Hill, 'foundation' in
    make-up copy, 'universities' on a school's site, Platform4, 'university' in a biotech description,
    Kforce Inc, courtyard.marriott.com, a school site taken over by slot spam, a Japanese title, an Apollo
    'retailer' whose own site has no retail words), and the other sunk leads by kind (a lessor, a venture
    fund, a .gov domain, an Amazon agency, hotel software, an e-learning firm, a marketplace, a workspace
    developer, a site that is not the company's, an adult studio, LVMH's Belmond)
  * each rubric input, modifier and gate input: full, half, none and unknown, as the config's guidance says
  * a buying signal fading with age, and cancelled for a wrong buyer
  * score(): sql/06's arithmetic, the lattice the line of 70 was set on (64 / 69 stay, 72 / 74 / 79 cross,
    a perfect wrong buyer or giant 62 stays), JSON null out of the denominator, round half up, clamped
  * planned(): what the write leaves (unknown as JSON null, reach 0 only where absent, retired keys gone,
    the 0 sql/04b writes for an absent modifier left alone) and a second pass over its own output changes
    nothing
  * main(): a project whose config has no judge.enabled is left alone (the chain step is a no-op there)
Exit code 1 on any failure.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import lcx_judge as LJ  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252; the fixtures are not all ASCII
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = []
CFG = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
NOW = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.timezone.utc)
SEEN = []                                        # every judged inputs dict, for the 0 / 0.5 / 1 check at the end


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-80s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str, ensure_ascii=False)[:100]
                               + ("" if ok else "   (want %s)" % json.dumps(want, default=str, ensure_ascii=False)[:100])))


def lead(name, domain, kind, src="lcx_wikidata", rec=None, title=None, description="", about="", socials=None,
         pages=None, meta=None, **extra):
    """A lead as the promote chain and the site pass leave it: its discovery record under
    metadata.discovery_raw.<src> ({'wikidata': {...}}, {'apollo_search': {...}}, ...), and when a site text is
    given, metadata.site_about and site_contact_routes (pages read, the accounts it links)."""
    m = {"scoring_inputs": {}}
    if kind:
        m["kind"] = kind
    if src:
        m["discovery_raw"] = {src: dict({"kind": kind} if kind else {}, **(rec or {}))}
    if title is not None or description or about:
        m["site_about"] = {"title": title or "", "description": description, "about": about}
    if socials is not None or pages is not None or title is not None:
        m["site_contact_routes"] = {"socials": socials or {}, "pages_read": 3 if pages is None else pages}
    m.update(meta or {})
    return dict({"name": name, "domain": domain, "source": src or "apollo", "metadata": m}, **extra)


def judged(L, cfg=None, now=None):
    i, g, ev = LJ.judge(L, cfg or CFG, now or NOW)
    SEEN.append(i)
    return i, g, ev


def inp(L, *keys, **kw):
    i, g, _ = judged(L, **kw)
    return tuple(i[k] for k in keys) if len(keys) > 1 else i[keys[0]]


def gate(L, key, **kw):
    return judged(L, **kw)[1][key]


def wd(iso="GB", **k):
    return {"wikidata": dict({"country_iso": iso}, **k)}


def aps(iso="US", **k):
    return {"apollo_search": dict({"country_iso": iso}, **k)}


def misfires():
    print("-- the misfires the 2026-10-07 simulation found, and what each was mistaken for")
    bank = lead("First Citizens Bank, National Association", "firstcitizens.example", "financial_services", "lcx_fdic",
                {"fdic": {"assets_thousands": 5000000, "country_iso": "US"}},
                title="First Citizens Bank | Personal & Business Banking",
                description="Checking, savings, loans and mortgages.")
    check("a 'National Association' bank is not an association (legal forms are taken off first)",
          inp(bank, "wrong_buyer", "buyer_confirmed", "buyer_size"), (0.0, 1.0, 1.0))
    check("  nor a 'Savings and Loan Association'",
          inp(lead("Home Federal Savings and Loan Association", "homefed.example", "financial_services", "lcx_fdic",
                   {"fdic": {"assets_thousands": 2000000, "country_iso": "US"}}), "wrong_buyer"), 0.0)
    check("  but a trade association filed as a bank is",
          inp(lead("Independent Bankers Association", "ibassoc.example", "financial_services", rec=wd("US")),
              "wrong_buyer"), 1.0)
    check("Beacon Hill School is not the staffing firm Beacon Hill",
          inp(lead("Beacon Hill School", "beaconhillschool.example", "schools", rec=wd(),
                   title="Beacon Hill School", description="Admissions are open for our primary pupils."),
              "wrong_buyer"), 0.0)
    check("  Beacon Hill, the staffing firm, is (the whole name, once 'Inc' is off)",
          inp(lead("Beacon Hill Inc", "bhsg.example", "corporate_teams", "lcx_apollo", aps()), "wrong_buyer"), 1.0)
    kforce = lead("Kforce Inc", "kforce.example", "corporate_teams", "lcx_apollo",
                  aps(signal="hiring for training and onboarding now"),
                  title="Kforce | Technology and Finance Talent", description="We connect people and companies.")
    check("Kforce Inc is staffing, and its hiring is its product: no buying trigger",
          inp(kforce, "wrong_buyer", "buying_trigger"), (1.0, None))
    check("'foundation' in make-up copy is not a non-profit",
          inp(lead("Glow Cosmetics", "glowcosmetics.example", "consumer_brands", rec=wd(),
                   title="Glow Cosmetics | Make-up and skincare",
                   description="Shop our new foundation, concealer and skin care range."), "wrong_buyer"), 0.0)
    check("  a foundation by name is",
          inp(lead("Hope Foundation", "hopefoundation.example", "consumer_brands", rec=wd()), "wrong_buyer"), 1.0)
    check("'universities' on a school's site is not academic",
          inp(lead("Oakridge International School", "oakridge.example", "schools", rec=wd("IN"),
                   title="Oakridge International School",
                   description="Our students go on to the world's top universities. Admissions open."),
              "wrong_buyer"), 0.0)
    check("  a university filed as a school is",
          inp(lead("Northgate University", "northgate.example", "schools", rec=wd(), title="Northgate University"),
              "wrong_buyer"), 1.0)
    check("Platform4, a production company, is not a software vendor",
          inp(lead("Platform4", "platform4.example", "studios_agencies", rec=wd(),
                   title="Platform4 | Film and TV production", description="A production company."),
              "wrong_buyer"), 0.0)
    check("  'platform' in the title is read without the company's own name (Platform Bistro is a cafe)",
          inp(lead("Platform Bistro", "platformbistro.example", "local_business", "lcx_osm",
                   {"osm": {"country_iso": "GB", "website": "https://platformbistro.example/"}},
                   title="Platform Bistro | Brunch and coffee"), "wrong_buyer"), 0.0)
    check("  a title selling a platform is a vendor",
          inp(lead("Zeta Hospitality", "zetahq.example", "hospitality", rec=wd(),
                   title="Zeta | The platform hotel groups run on"), "wrong_buyer"), 1.0)
    check("'university' in a biotech's description is not academic",
          inp(lead("Helix Bio", "helixbio.example", "corporate_teams", "lcx_apollo", aps(), title="Helix Bio",
                   description="Founded by researchers from Stanford University, we make therapies."),
              "wrong_buyer"), 0.0)
    court = lead("Courtyard by Marriott Mumbai", "courtyard.marriott.com", "hospitality", rec=wd("IN"))
    i, g, ev = judged(court)
    check("courtyard.marriott.com is a major's brand: the gate, and too big on the group's domain",
          (g["oversized_signal"], i["too_big"], LJ.gates_fired(g)), (True, 1.0, ["not_major"]))
    check("  and the lead says which group", ev["oversized_signal"].startswith("major or a major's brand: Marriott"),
          True)
    spam = lead("St. Anne's High School", "stannehighschool.example", "schools", "lcx_osm",
                {"osm": {"country_iso": "IN", "website": "https://stannehighschool.example/"}},
                title="Data HK: Keluaran HK | Togel Hongkong", description="Data hk prize togel")
    check("a school site taken over by slot spam is unsafe", (gate(spam, "brand_risk_signal"),
                                                              LJ.gates_fired(judged(spam)[1])),
          ("unsafe", ["brand_safe"]))
    jp = lead("Hoshino Shobo", "hoshino-shobo.example", "publishers", rec=wd("JP"),
              title="株式会社星野書房 | 書籍・コミックの出版社", description="星野書房の公式サイトです。新刊情報をお届けします。")
    check("a Japanese title is not English: -15", inp(jp, "non_english_site"), 1.0)
    cloud = lead("Cloudly AI", "cloudly.example", "retailers", "lcx_apollo", aps(), title="Cloudly AI",
                 description="We help teams ship faster with our AI coworkers.")
    check("an Apollo 'retailer' whose own site has no retail words: not confirmed",
          inp(cloud, "buyer_confirmed", "wrong_buyer"), (0.0, 0.5))

    print("\n-- the other leads the old score had near the top, sunk by kind")
    lessor = lead("Aerline Capital", "aerline.example", "corporate_teams", rec=wd("IE", employees=700),
                  title="Aerline Capital", description="The world's leading aircraft lessor, with 1,700 aircraft.")
    i, _, _ = judged(lessor)
    check("an aircraft lessor (AerCap was 94): the full -50", i["wrong_buyer"], 1.0)
    check("  its score falls far under the line", LJ.score(LJ.planned({}, i, judged(lessor)[1], LJ.lists(CFG))[0],
                                                           CFG)[0] < 40, True)
    check("a venture fund in its own words",
          inp(lead("North Ridge Partners", "northridge.example", "corporate_teams", rec=wd("US"),
                   title="North Ridge Partners", description="A venture capital firm backing founders."),
              "wrong_buyer"), 1.0)
    check("a .gov domain", inp(lead("Federal Funding Bank", "ffb.treasury.gov", "financial_services", rec=wd("US")),
                               "wrong_buyer"), 1.0)
    check("an Amazon agency filed as a brand",
          inp(lead("Prime Clickers", "primeclickers.example", "consumer_brands", "lcx_apollo", aps(),
                   title="Prime Clickers | Amazon agency for brands"), "wrong_buyer"), 1.0)
    check("hotel software filed as a hotel",
          inp(lead("Suiteline", "suiteline.example", "hospitality", "lcx_apollo", aps(),
                   title="Suiteline | Hotel operations software"), "wrong_buyer"), 1.0)
    check("an e-learning firm (a competitor)",
          inp(lead("Navi Learn", "navilearn.example", "publishers", rec=wd("IN"), title="Navi Learn",
                   description="E-learning and test prep for every grade."), "wrong_buyer"), 1.0)
    check("  and the named competitors list", inp(lead("NIIT Limited", "niit.example", "corporate_teams", rec=wd("IN")),
                                                  "wrong_buyer"), 1.0)
    check("a marketplace filed as a brand: half",
          inp(lead("Laceup", "laceup.example", "consumer_brands", rec=wd(),
                   title="Laceup | The sneaker marketplace"), "wrong_buyer"), 0.5)
    check("a workspace developer filed as real estate: half",
          inp(lead("Reava Developments", "reava.example", "real_estate", rec=wd("GB"),
                   title="Reava | Workspaces and offices", description="We develop homes and offices."),
              "wrong_buyer"), 0.5)
    notours = lead("Zenora Bank Nigeria Plc", "znbk.example", "financial_services", rec=wd("NG"),
                   title="Lagos Internet Exchange Point", description="Peering for networks across West Africa.")
    i, _, ev = judged(notours)
    check("a domain now serving someone else (Afribank's): not theirs, not confirmed, a supplier",
          (ev["site_theirs"], i["buyer_confirmed"], i["wrong_buyer"]), (False, 0.0, 1.0))
    check("an adult studio by name (Vixen)", gate(lead("Vixen Media Group", "vixen.example", "studios_agencies",
                                                       rec=wd("US")), "brand_risk_signal"), "unsafe")
    check("LVMH's Belmond: a major's brand by its domain", gate(lead("Belmond", "belmond.com", "hospitality",
                                                                     rec=wd()), "oversized_signal"), True)


def buyer_confirmed():
    print("\n-- buyer_confirmed (30): the business is the buyer it was filed as, in its own words")
    hotel = dict(title="The Larkspur | Boutique hotel", description="Rooms and suites by the sea. Book direct.")
    check("full: two or more of its audience's words on its own site",
          inp(lead("The Larkspur", "larkspur.example", "hospitality", rec=wd(), **hotel), "buyer_confirmed"), 1.0)
    check("half: one word", inp(lead("The Larkspur", "larkspur.example", "hospitality", rec=wd(),
                                     title="The Larkspur", description="Welcome to our hotel."), "buyer_confirmed"), 0.5)
    check("half: a directory label, site not read (Wikidata, OpenStreetMap, the FDIC register)",
          [inp(lead("Larkspur", "larkspur.example", "hospitality", src, rec), "buyer_confirmed") for src, rec in
           (("lcx_wikidata", wd()), ("lcx_osm", {"osm": {"country_iso": "GB"}}),
            ("lcx_fdic", {"fdic": {"country_iso": "US"}}))], [0.5, 0.5, 0.5])
    check("  and the label stands when the site was read and says nothing either way",
          inp(lead("The Larkspur", "larkspur.example", "hospitality", rec=wd(), title="The Larkspur",
                   description="Welcome."), "buyer_confirmed"), 0.5)
    check("none: only Apollo's keyword search says so, site not read",
          inp(lead("Larkspur", "larkspur.example", "hospitality", "lcx_apollo", aps()), "buyer_confirmed"), 0.0)
    check("  nor read with none of the words",
          inp(lead("The Larkspur", "larkspur.example", "hospitality", "lcx_apollo", aps(), title="The Larkspur",
                   description="Welcome."), "buyer_confirmed"), 0.0)
    check("  a mid-size company from Apollo keeps half: any employer that size is the audience",
          inp(lead("Larkspur Group", "larkspur.example", "corporate_teams", "lcx_apollo", aps(),
                   title="Larkspur Group", description="Welcome."), "buyer_confirmed"), 0.5)
    check("  a site that is not the company's: half with its words, none without",
          [inp(lead("Larkspur Hotel Lisbon", "lshl.example", "hospitality", rec=wd(), title=t, description=d),
               "buyer_confirmed") for t, d in (("Seaside Inn", "Rooms and suites."), ("Domain parking", "Ads."))],
          [0.5, 0.0])
    check("  a bot wall is no text: back to the label",
          inp(lead("The Larkspur", "larkspur.example", "hospitality", rec=wd(), title="Just a moment...",
                   description="Rooms and suites."), "buyer_confirmed"), 0.5)
    save = lead("Larkspur Rooms", "larkspur.example", None, None, title="Larkspur Rooms | Boutique hotel",
                description="Forty rooms and suites. Book direct.", meta={"apollo": {"id": "a" * 24}})
    i, _, ev = judged(save)
    check("unknown: a search-page save its own words cannot place -- and placed when they can",
          (inp(lead("Larkspur", "larkspur.example", None, None, title="Larkspur", description="Hello.",
                    meta={"apollo": {"id": "b" * 24}}), "buyer_confirmed", "audience_fit"),
           i["buyer_confirmed"], i["audience_fit"], ev.get("kind")),
          ((None, None), 1.0, 1.0, "hospitality (from its own words)"))


def buyer_size():
    print("\n-- buyer_size (25): big enough to pay, small enough that one cold email reaches who decides")
    fd = lambda a: lead("Minn Bank", "minnbank.example", "financial_services", "lcx_fdic",   # noqa: E731
                        {"fdic": {"assets_thousands": a, "country_iso": "US"}})
    check("a bank by its assets: $1-10bn full, $0.3-1bn or $10-50bn half, smaller none",
          [inp(fd(a), "buyer_size") for a in (2940968, 500000, 20000000, 100000)], [1.0, 0.5, 0.5, 0.0])
    check("  a bank with no assets figure: unknown, not 0", inp(fd(None), "buyer_size"), None)
    rev = lambda r, kind="studios_agencies": lead("Reel Co", "reelco.example", kind, "lcx_apollo",  # noqa: E731
                                                   dict(aps(size_band="11-50 people"),
                                                        apollo={"annual_revenue_printed": r}))
    check("revenue against the audience's band (studios: $1-50M full, $50-250M half)",
          [inp(rev(r), "buyer_size") for r in ("4.8M", "150M", "2B", "374K")], [1.0, 0.5, 0.0, 0.5])
    check("  the same revenue for a mid-size company ($20M-1B full)", inp(rev("150M", "corporate_teams"), "buyer_size"),
          1.0)
    hc = lambda n, kind="corporate_teams": lead("Northwind", "northwind.example", kind, rec=wd(employees=n))  # noqa: E731
    check("headcount against the audience's band (mid-size: 200-5,000 full, 50-199 or 5,001-20,000 half)",
          [inp(hc(n), "buyer_size") for n in (800, 100, 8000, 30, 40000)], [1.0, 0.5, 0.5, 0.0, 0.0])
    check("  a cafe's band is 2-50", inp(hc(12, "local_business"), "buyer_size"), 1.0)
    check("a school by its pupils first (300-3,000 full, 100-299 half), whatever its staff",
          [inp(lead("Elm School", "elm.example", "schools", rec=wd(students=s, employees=4)), "buyer_size")
           for s in (1200, 150, 50)], [1.0, 0.5, 0.0])
    osm = lambda t=None, web="https://bean.example/": lead("Bean", "bean.example", "local_business", "lcx_osm",  # noqa: E731
                                                            {"osm": {"country_iso": "GB", "website": web}}, title=t,
                                                            description="Coffee and brunch." if t else "")
    check("OpenStreetMap: several locations in its own words full, one premises half, no website none",
          [inp(osm("Bean | Our locations"), "buyer_size"), inp(osm(), "buyer_size"), inp(osm(web=None), "buyer_size")],
          [1.0, 0.5, 0.0])
    check("Apollo's search band alone is half (a filter, not a measurement)",
          inp(lead("Reel Co", "reelco.example", "consumer_brands", "lcx_apollo", aps(size_band="11-50 people")),
              "buyer_size"), 0.5)
    check("unknown: nobody measured it (JSON null, scored out of the other 75 points)",
          inp(lead("Elm Park", "elmpark.example", "attractions", rec=wd()), "buyer_size"), None)


def content_activity():
    print("\n-- content_activity (20): already pays for content -- video and Instagram accounts")
    site = lambda s, pages=3: lead("Glow", "glow.example", "consumer_brands", rec=wd(), socials=s,  # noqa: E731
                                   pages=pages)
    check("full: a video account and one more (YouTube + Instagram, YouTube + TikTok)",
          [inp(site({"youtube": "u", "instagram": "i"}), "content_activity"),
           inp(site({"youtube": "u", "tiktok": "t"}), "content_activity")], [1.0, 1.0])
    check("half: exactly one (Instagram alone, YouTube alone)",
          [inp(site({"instagram": "i"}), "content_activity"), inp(site({"youtube": "u"}), "content_activity")],
          [0.5, 0.5])
    check("none: the site was read and links none of them; Facebook, X and LinkedIn earn nothing",
          [inp(site({}), "content_activity"), inp(site({"facebook": "f", "x": "x"}), "content_activity")], [0.0, 0.0])
    check("unknown: the site not read and no directory lists an account",
          inp(lead("Glow", "glow.example", "consumer_brands", rec=wd()), "content_activity"), None)
    check("  a site refused (robots.txt): still unknown, not 0", inp(site({}, pages=0), "content_activity"), None)
    wall = lead("Glow", "glow.example", "consumer_brands", rec=wd(), title="Just a moment...", socials={}, pages=1)
    check("  a site whose only page was a bot wall: unknown, not 'no accounts' (and not a read site)",
          (inp(wall, "content_activity"), judged(wall)[2]["site_checked"]), (None, False))
    checked = lambda **k: judged(lead("Glow", "glow.example", "consumer_brands", rec=wd(), **k))[2]["site_checked"]  # noqa: E731
    check("  site_checked: its own words read, or pages read with none a bot wall; not a directory listing",
          (checked(title="Glow | Skincare", description="Serums and SPF."), checked(socials={}, pages=2),
           checked()), (True, True, False))
    check("a directory's accounts count unread: Wikidata's YouTube + Instagram, OpenStreetMap's contact:instagram",
          [inp(lead("Acme Toys", "acmetoys.example", "consumer_brands",
                    rec=wd("US", socials={"youtube": "UC1", "instagram": "acme"})), "content_activity"),
           inp(lead("Bean", "bean.example", "local_business", "lcx_osm",
                    {"osm": {"country_iso": "GB", "contact:instagram": "beanldn"}}), "content_activity")], [1.0, 0.5])
    check("  a directory never writes 0: one listing only Facebook leaves it unknown",
          inp(lead("Acme Toys", "acmetoys.example", "consumer_brands", rec=wd("US", socials={"facebook": "acme"})),
              "content_activity"), None)


def audience_and_reach():
    print("\n-- audience_fit (15) and reachable_decision_maker (10)")
    fit = {k: inp(lead("X Co", "x.example", k, rec=wd()), "audience_fit") for k in
           ("consumer_brands", "corporate_teams", "financial_services", "attractions", "local_business", "schools")}
    check("the owner's table: banks and attractions half, every other audience full, cafes full",
          fit, {"consumer_brands": 1.0, "corporate_teams": 1.0, "financial_services": 0.5, "attractions": 0.5,
                "local_business": 1.0, "schools": 1.0})
    check("reach is the contact tools': kept as stored, 0 when there is none",
          [inp(lead("X Co", "x.example", "schools", rec=wd(),
                    meta={"scoring_inputs": {"reachable_decision_maker": r}} if r is not None else None),
               "reachable_decision_maker") for r in (1.0, 0.5, None)], [1.0, 0.5, 0.0])


def wrong_buyer():
    print("\n-- wrong_buyer (-50): not a buyer of this")
    w = lambda kind, name="Kestrel", dom="kestrel.example", **k: inp(lead(name, dom, kind, rec=wd("US"), **k),  # noqa: E731
                                                                     "wrong_buyer")
    check("0 when nothing matches, always written", w("consumer_brands", title="Kestrel | Outdoor apparel",
                                                      description="Jackets and boots."), 0.0)
    check("'any' self-descriptions count in full from the description ('a registered charity')",
          w("consumer_brands", title="Kestrel", description="Kestrel is a registered charity."), 1.0)
    check("  schools are exempt from the non-profit test (an Indian 'Public School' is private)",
          w("schools", title="Kestrel School", description="Kestrel is a non-profit school. Admissions open."), 0.0)
    check("  and an attraction or publisher gets half (per_audience)",
          w("attractions", title="Kestrel Zoo", description="A registered charity and zoo."), 0.5)
    check("'nt' words: full in the name or title, half in the description",
          (w("consumer_brands", title="Kestrel | Recruitment"),
           w("consumer_brands", title="Kestrel", description="Recruitment for retail brands.")), (1.0, 0.5))
    check("'title' words (academic) never from the description",
          (w("corporate_teams", title="Kestrel | Business School"),
           w("corporate_teams", title="Kestrel", description="Our team studied at a business school.")), (1.0, 0.0))
    check("software: full in the title; a description's full for a mid-size company, half for the bare word",
          (w("consumer_brands", title="Kestrel | Payroll software"),
           w("corporate_teams", title="Kestrel", description="Workflow automation for finance teams."),
           w("corporate_teams", title="Kestrel", description="We build software for shops.")), (1.0, 1.0, 0.5))
    check("  half from the description for the other audiences",
          w("consumer_brands", title="Kestrel", description="Workflow automation for finance teams."), 0.5)
    check("  banks only on 'software' or 'SaaS', at half; studios never",
          (w("financial_services", title="Kestrel | Banking software"),
           w("financial_services", title="Kestrel Bank", description="Workflow automation for loans."),
           w("studios_agencies", title="Kestrel | Software explainer films")), (0.5, 0.0, 0.0))
    check("a .org domain on a company audience: half", w("consumer_brands", dom="kestrel.org"), 0.5)
    check("domains: .gov and .mil full; .edu or .ac outside schools full, a school's .edu nothing",
          (w("corporate_teams", dom="kestrel.mil"), w("corporate_teams", dom="kestrel.ac.uk"),
           w("schools", dom="kestrel.edu", title="Kestrel Academy", description="Admissions open for pupils.")),
          (1.0, 1.0, 0.0))
    check("name words (institute, council, ...), schools exempt for theirs ('Kestrel Institute' school)",
          (w("corporate_teams", name="Kestrel Institute"), w("schools", name="Kestrel Institute")), (1.0, 0.0))
    check("a staffing word in the domain, as a whole word (kestrel-talent, not kestreltalent)",
          (w("corporate_teams", dom="kestrel-talent.example"), w("corporate_teams", dom="kestreltalent.example")),
          (1.0, 0.0))
    check("a studio US Production Houses already holds",
          inp(lead("Kestrel Films", "kestrelfilms.example", "studios_agencies", rec=wd("US"), in_ph=True),
              "wrong_buyer"), 1.0)
    check("'only' rules apply to their audience, and to a lead not yet placed in one",
          (inp(lead("Harbour Advisory", "harbouradvisory.example", None, None,
                    title="Harbour Advisory | Management consulting",
                    description="A law firm and advisers to growing companies."), "wrong_buyer"),
           w("corporate_teams", title="Kestrel | Management consulting"),
           w("consumer_brands", title="Kestrel | Management consulting")), (0.5, 0.5, 0.0))


def too_big():
    print("\n-- too_big (-50): too big to answer a cold email, or part of a large group")
    tb = lambda kind="consumer_brands", **rec: inp(lead("Kestrel", "kestrel.example", kind, rec=wd("US", **rec)),  # noqa: E731
                                                   "too_big")
    rv = lambda r, sym=None: inp(lead("Kestrel", "kestrel.example", "consumer_brands", "lcx_apollo",  # noqa: E731
                                      dict(aps(), apollo=dict({"annual_revenue_printed": r},
                                                              **({"publicly_traded_symbol": sym} if sym else {})))),
                                 "too_big")
    check("revenue: $2-10B full, $1-2B half, less nothing", [rv(r) for r in ("3B", "1.5B", "400M")], [1.0, 0.5, 0.0])
    check("  listed with revenue over $500M: half", (rv("600M", "KSTL"), rv("600M")), (0.5, 0.0))
    check("people: over 20,000 full; 5,001-20,000 half, except for mid-size companies",
          (tb(employees=25000), tb(employees=8000), tb("corporate_teams", employees=8000), tb(employees=900)),
          (1.0, 0.5, 0.0, 0.0))
    check("a bank with over $50bn of assets", inp(lead("Big Bank", "bigbank.example", "financial_services", "lcx_fdic",
                                                       {"fdic": {"assets_thousands": 60000000, "country_iso": "US"}}),
                                                  "too_big"), 1.0)
    check("a brand's page on its group's domain, not www or shop",
          [inp(lead("Kestrel", d, "consumer_brands", rec=wd()), "too_big") for d in
           ("kestrel.groupco.example", "shop.kestrel.example", "kestrel.co.uk")], [1.0, 0.0, 0.0])
    check("an OpenStreetMap premises on one page of a chain's site: half",
          [inp(lead("Ginger Andheri", "gingerhotels.example", "hospitality", "lcx_osm",
                    {"osm": {"country_iso": "IN", "city": "Mumbai", "website": u}}), "too_big")
           for u in ("https://www.gingerhotels.example/ginger-mumbai-andheri", "https://gingerhotels.example/")],
          [0.5, 0.0])
    own = lambda d: inp(lead("Kestrel", "kestrel.example", "consumer_brands", rec=wd(), title="Kestrel",  # noqa: E731
                             description=d), "too_big")
    check("its own words: 'is now part of' full; 'a subsidiary of', 'investor relations' half",
          [own(d) for d in ("Kestrel is now part of Northwind.", "Kestrel is a subsidiary of Northwind.",
                            "Investor relations and careers.")], [1.0, 0.5, 0.5])
    par = lambda via, n, label="Northwind Holdings", dom=None: tb(parents=[dict(  # noqa: E731
        {"qid": "Q1", "label": label, "via": via, "employees": n}, **({"domain": dom} if dom else {}))])
    check("a Wikidata parent organisation of over 5,000 people: full; an owner (often a fund or a state): never by size",
          (par("P749", 12000), par("P127", 12000), par("P749", 900)), (1.0, 0.0, 0.0))
    check("  a parent on the majors list, either way, is a major's brand (too_big full)",
          (par("P749", None, "LVMH", "lvmh.com"), par("P127", None, "LVMH", "lvmh.com")), (1.0, 1.0))
    pg = lambda via: gate(lead("Kestrel", "kestrel.example", "consumer_brands",  # noqa: E731
                               rec=wd(parents=[{"qid": "Q2", "label": "LVMH", "via": via, "domain": "lvmh.com"}])),
                          "oversized_signal")
    check("  but only a parent organisation (P749) archives: an owner (P127) may be a fund holding a stake",
          (pg("P749"), pg("P127")), (True, False))
    sub = lambda parent=None: lead("Sub Brand", "subbrand.example", "consumer_brands", "lcx_apollo",  # noqa: E731
                                   dict(aps(), apollo={"id": "a1", "owned_by_organization_id": "p1"}),
                                   **({"apollo_parent": parent} if parent else {}))
    check("Apollo's parent, when it is a company we hold, by its size; a bare id names nobody and adds nothing",
          (inp(sub({"name": "Big Parent Co", "domain": "bigparent.example", "employees": 12000}), "too_big"),
           inp(sub(), "too_big")), (1.0, 0.0))


def buying_trigger():
    print("\n-- buying_trigger (+8): a reason to buy now")
    sig = lambda s, site=True, seen="2026-10-01T00:00:00+00:00", kind="corporate_teams": lead(  # noqa: E731
        "Northwind", "northwind.example", kind, "lcx_apollo", aps(signal=s, signal_seen_at=seen),
        **(dict(title="Northwind | Stores nationwide", description="Our stores and team members.") if site else {}))
    check("a strong signal (training, content, funding, marketing) once its own site is read and theirs: full",
          [inp(sig(s), "buying_trigger") for s in ("hiring for training and onboarding now", "hiring for content and"
                                                   " video now", "raised money in the last 90 days",
                                                   "hiring marketing staff for a launch")], [1.0, 1.0, 1.0, 1.0])
    check("  before the site is read: half", inp(sig("hiring for content and video now", site=False), "buying_trigger"),
          0.5)
    check("a frontline signal: half once the site is read, nothing before",
          (inp(sig("hiring sales and service staff now"), "buying_trigger"),
           inp(sig("hiring store staff now", site=False), "buying_trigger")), (0.5, None))
    check("it fades: half after 60 days, gone after 120",
          [inp(sig("hiring for training and onboarding now", seen="2026-10-01T00:00:00Z"), "buying_trigger",
               now=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=d)) for d in (10, 61, 121)],
          [1.0, 0.5, None])
    check("  dated by when its Apollo row was staged when the signal carries no date",
          inp(dict(sig("hiring for training and onboarding now", seen=None), staged_at="2026-05-01T00:00:00+00:00"),
              "buying_trigger"), None)
    check("a launch or opening phrase in its own words: half",
          inp(lead("Larkspur", "larkspur.example", "hospitality", rec=wd(), title="Larkspur | Now open",
                   description="Rooms and suites by the sea."), "buying_trigger"), 0.5)
    check("  and a faded signal leaves those words to speak",
          inp(dict(lead("Northwind", "northwind.example", "corporate_teams", "lcx_apollo",
                        aps(signal="hiring for training and onboarding now", signal_seen_at="2026-01-01T00:00:00Z"),
                        title="Northwind | We're hiring", description="Stores and team members nationwide.")),
              "buying_trigger"), 0.5)
    check("absent with no signal (a bonus: absence costs nothing)",
          inp(lead("Larkspur", "larkspur.example", "hospitality", rec=wd()), "buying_trigger"), None)


def market_language():
    print("\n-- priority_market (+4) and non_english_site (-15)")
    pm = lambda iso: inp(lead("X Co", "x.example", "consumer_brands", rec=wd(iso)), "priority_market")  # noqa: E731
    check("the US, the UK, India and the UAE full; another English market half; elsewhere none",
          [pm(c) for c in ("US", "GB", "IN", "AE", "SG", "FR")], [1.0, 1.0, 1.0, 1.0, 0.5, 0.0])
    check("  absent when the country is unknown", inp(lead("X Co", "x.example", "consumer_brands", rec={}),
                                                      "priority_market"), None)
    check("  a search-page save's country as Apollo names it",
          inp(lead("X Co", "x.example", None, None, meta={"hq_country": "United Kingdom"}), "priority_market"), 1.0)
    ne = lambda t, d="", a="": inp(lead("Kestrel", "kestrel.example", "hospitality", rec=wd(), title=t,  # noqa: E731
                                        description=d, about=a), "non_english_site")
    check("not English: non-Latin letters, or foreign function words outnumbering English ones",
          (ne("Отель Кестрел | Номера и люксы"),
           ne("Stayokay | Hostels in Nederland", "Boek je verblijf voor een nacht in een van onze hostels en de stad")),
          (1.0, 1.0))
    check("English: 0; too little to tell: absent, then the About paragraph decides",
          (ne("Kestrel | Rooms and suites by the sea", "Book your stay with us"), ne("Kestrel"),
           ne("Kestrel", "", "We are a family hotel on the coast and our rooms look over the sea.")), (0.0, None, 0.0))
    check("  a site not read: absent", inp(lead("Kestrel", "kestrel.example", "hospitality", rec=wd()),
                                           "non_english_site"), None)


def gates():
    print("\n-- the gate inputs (only ever on evidence: unknown always passes)")
    cs = lambda iso, dom="kestrel.example": gate(lead("Kestrel", dom, "consumer_brands", rec=wd(iso) if iso else {}),  # noqa: E731
                                                 "country_signal")
    check("country_signal: consent-law 'disallowed', sanctioned 'unpayable', else 'allowed', unknown removed",
          [cs(c) for c in ("DE", "RU", "IR", "CU", "US", None)], ["disallowed", "unpayable", "unpayable", "unpayable",
                                                                   "allowed", None])
    check("  no country known: a .ru domain counts as sanctioned", cs(None, "kestrel.ru"), "unpayable")
    os_ = lambda **rec: gate(lead("Kestrel", "kestrel.example", "corporate_teams", rec=wd("US", **rec)),  # noqa: E731
                             "oversized_signal")
    check("oversized_signal (not_major): over 50,000 people, a major's domain, else False",
          (os_(employees=60000), os_(employees=40000),
           gate(lead("Courtyard Leeds", "courtyard.marriott.com", "hospitality", rec=wd()), "oversized_signal")),
          (True, False, True))
    hie = lead("Holiday Inn Express Leeds", "hiexpress.example", "hospitality", rec=wd())
    check("  a name that only reads like a major's brand: not archived, but too_big full (-50)",
          (gate(hie, "oversized_signal"), inp(hie, "too_big")), (False, 1.0))
    check("  a full majors domain matches only itself: paramount.com is Paramount, paramount.co.in is not",
          (gate(lead("Paramount Pictures", "paramount.com", "studios_agencies", rec=wd("US")), "oversized_signal"),
           gate(lead("Paramount Cables", "paramount.co.in", "corporate_teams", rec=wd("IN")), "oversized_signal")),
          (True, False))
    check("  a bare majors name matches it under any ending: legoland.co.uk is Merlin's",
          gate(lead("Legoland Windsor", "legoland.co.uk", "attractions", rec=wd()), "oversized_signal"), True)
    check("  revenue of $10B or more; over $100bn of assets",
          (gate(lead("Kestrel", "kestrel.example", "consumer_brands", "lcx_apollo",
                     dict(aps(), apollo={"annual_revenue_printed": "12B"})), "oversized_signal"),
           gate(lead("Big Bank", "bigbank.example", "financial_services", "lcx_fdic",
                     {"fdic": {"assets_thousands": 150000000, "country_iso": "US"}}), "oversized_signal")), (True, True))
    br = lambda name, **k: gate(lead(name, "kestrel.example", "consumer_brands", rec=wd(**k.pop("rec", {})), **k),  # noqa: E731
                                "brand_risk_signal")
    check("brand_risk_signal: an unsafe word, a name on the list, a Wikidata class; else removed",
          (br("Kestrel Vape Co"), br("DraftKings"), br("Kestrel", rec={"classes": ["casino"]}),
           br("Kestrel", title="Kestrel | Gift sets", description="Wine and chocolate hampers.")),
          ("unsafe", "unsafe", "unsafe", None))
    check("activity_signal: a parked or default page is dead",
          gate(lead("Kestrel", "kestrel.example", "consumer_brands", rec=wd(),
                    title="Apache2 Ubuntu Default Page: It works"), "activity_signal"), "dead")
    gone = lead("Gone Ltd", "gone-ltd.example", "consumer_brands", rec=wd(),
                meta={"site_contact_routes": {"socials": {}, "pages_read": 0, "blocked": "the domain does not resolve",
                                              "read_at": "2026-10-07T10:00:00+00:00"},
                      "dead_since": "2026-10-07T10:00:00+00:00"})
    again = json.loads(json.dumps(gone))
    again["metadata"]["site_contact_routes"]["read_at"] = "2026-10-15T10:00:00+00:00"
    back = json.loads(json.dumps(again))
    back["metadata"]["site_about"] = {"read_at": "2026-10-16T10:00:00+00:00", "title": "Gone Ltd | Shoes",
                                      "description": "Shop shoes."}
    check("  a domain that does not resolve: not dead on one read; dead read again 7+ days on; alive once it answers",
          [gate(x, "activity_signal") for x in (gone, again, back)], [None, "dead", None])
    once = dict(CFG, judge=dict(CFG["judge"], dead_after_days=0))
    check("  judge.dead_after_days 0: one failed read is enough (the simulation's assumption)",
          gate(gone, "activity_signal", cfg=once), "dead")
    check("  a robots.txt refusal or a timeout is never 'gone'",
          gate(lead("Kestrel", "kestrel.example", "consumer_brands", rec=wd(),
                    meta={"site_contact_routes": {"pages_read": 0, "blocked": "robots.txt disallows",
                                                  "read_at": "2026-10-15T10:00:00+00:00"},
                          "dead_since": "2026-10-01T10:00:00+00:00"}), "activity_signal"), None)
    check("gates_fired names the config's gates, one input feeding two (country_allowed / payable_country)",
          (LJ.gates_fired({"country_signal": "disallowed"}), LJ.gates_fired({"country_signal": "unpayable"}),
           LJ.gates_fired({"oversized_signal": True, "brand_risk_signal": "unsafe", "activity_signal": "dead"}),
           LJ.gates_fired({"oversized_signal": False, "country_signal": "allowed"})),
          (["country_allowed"], ["payable_country"], ["not_major", "brand_safe", "site_alive"], []))
    keys = {g["key"] for g in CFG["gates"]}
    check("  and every gate it can name is one the config has", {"country_allowed", "payable_country", "not_major",
                                                                 "brand_safe", "site_alive"} <= keys, True)


def scores():
    print("\n-- score(): sql/06's arithmetic, and the lattice the line of 70 was set on")
    line = CFG["auto_shortlist"]["min_score"]
    base = {"buyer_confirmed": 0.5, "buyer_size": 1.0, "content_activity": 0.0, "audience_fit": 1.0,
            "reachable_decision_maker": 0.5, "priority_market": 1.0}
    s = lambda **k: LJ.score(dict(base, **k), CFG)[0]                     # noqa: E731
    perfect = {k: 1.0 for k in ("buyer_confirmed", "buyer_size", "content_activity", "audience_fit",
                                "reachable_decision_maker", "buying_trigger", "priority_market")}
    cases = [("the basics: a directory label, the right size, full fit, an inbox, a priority market", s(), 64.0),
             ("  the same with a named person (reach alone never pushes the basics over)",
              s(reachable_decision_maker=1.0), 69.0),
             ("  + a frontline or launch trigger", s(buying_trigger=0.5), 68.0),
             ("  + a strong trigger", s(buying_trigger=1.0), 72.0),
             ("  + one video or Instagram account", s(content_activity=0.5), 74.0),
             ("  + its own words confirming the audience", s(buyer_confirmed=1.0), 79.0),
             ("  one account in another English market", s(content_activity=0.5, priority_market=0.5), 72.0),
             ("  one account in a non-English market (70.0 exactly stays)", s(content_activity=0.5, priority_market=0),
              70.0),
             ("a perfect lead with both bonuses but wrong_buyer 1.0", LJ.score(dict(perfect, wrong_buyer=1.0), CFG)[0],
              62.0),
             ("  or too_big 1.0", LJ.score(dict(perfect, too_big=1.0), CFG)[0], 62.0),
             ("an unread Apollo lead (label 0, size 1, strong signal half)",
              LJ.score({"buyer_confirmed": 0.0, "buyer_size": 1.0, "content_activity": None, "audience_fit": 1.0,
                        "reachable_decision_maker": 0.0, "buying_trigger": 0.5, "priority_market": 1.0}, CFG)[0], 58.0),
             ("a bank whose site confirms it, with YouTube + Instagram and a named person",
              LJ.score({"buyer_confirmed": 1.0, "buyer_size": 1.0, "content_activity": 1.0, "audience_fit": 0.5,
                        "reachable_decision_maker": 1.0, "priority_market": 1.0}, CFG)[0], 96.5),
             ("a cafe with its own words, Instagram, one premises and an inbox",
              LJ.score({"buyer_confirmed": 1.0, "buyer_size": 0.5, "content_activity": 0.5, "audience_fit": 1.0,
                        "reachable_decision_maker": 0.5, "priority_market": 1.0}, CFG)[0], 76.5)]
    for name, got, want in cases:
        check("%s: %s, %s the line" % (name, want, "over" if want > line else "not over"), got, want)
    check("unknown (JSON null) is out of the denominator: label, size, fit, inbox known = 75 of 80, +4",
          LJ.score(dict(base, content_activity=None), CFG), (79.0, 80.0))
    check("nothing assessed: no score at all", LJ.score({"priority_market": 1.0}, CFG), (None, 0.0))
    check("clamped to 0..100", (LJ.score(dict(perfect, wrong_buyer=1.0, too_big=1.0, non_english_site=1.0), CFG)[0],
                                LJ.score(perfect, CFG)[0]), (0.0, 100.0))
    check("rounded half up as Postgres numeric does (52.5 of 80 known = 65.625, +4 = 69.625 -> 69.63, not 69.62)",
          LJ.score({"buyer_confirmed": 0.5, "buyer_size": 0.5, "content_activity": None, "audience_fit": 1.0,
                    "reachable_decision_maker": 1.0, "priority_market": 1.0}, CFG), (69.63, 80.0))


def write_plan():
    print("\n-- planned(): what the write leaves, and that it settles")
    J = LJ.lists(CFG)
    L = lead("Glow Cosmetics", "glowcosmetics.example", "consumer_brands", rec=wd(employees=300),
             meta={"scoring_inputs": {"established": 1.0, "right_size": 1.0, "english_market": 1.0, "genre_fit": 0.5,
                                      "audience_fit": 1.0, "has_reachable_presence": True, "buying_trigger": 0},
                   "unverified_inputs": ["buyer_size", "content_activity", "reachable_decision_maker"]})
    i, g, ev = judged(L)
    new, setv, drop, verified, unv = LJ.planned(L["metadata"], i, g, J)
    check("the retired keys are deleted (established, right_size, english_market, the production houses' keys)",
          [k for k in ("established", "right_size", "english_market", "genre_fit") if k in new], [])
    check("an unknown rubric input is written as JSON null (in the set), never left out",
          ("content_activity" in setv, setv["content_activity"], new["content_activity"]), (True, None, None))
    check("reach written as 0 where there was none; the harvest's has_reachable_presence kept",
          (new["reachable_decision_maker"], new["has_reachable_presence"]), (0, True))
    check("an absent modifier: sql/04b's stored 0 is left alone (removing it would rewrite every lead each run)",
          ("buying_trigger" in drop, new.get("buying_trigger")), (False, 0))
    check("  an absent gate input is removed (unknown passes)", ("brand_risk_signal" in drop,
                                                                  "brand_risk_signal" in new), (True, False))
    check("what it set to a value is no longer unverified; what it left unknown stays",
          unv, ["content_activity", "reachable_decision_maker"])
    m2 = dict(L["metadata"], scoring_inputs=new, unverified_inputs=unv, lcx_judgement=ev)
    i2, g2, ev2 = judged(dict(L, metadata=m2))
    new2, _, _, _, unv2 = LJ.planned(m2, i2, g2, J)
    check("a second pass over its own output changes nothing (so an unchanged lead is not written)",
          (new2 == new, unv2 == unv, LJ.same_judgement(ev, ev2)), (True, True, True))
    check("  a stored reach is never changed", LJ.planned({"scoring_inputs": {"reachable_decision_maker": 0.5}}, i, g,
                                                           J)[0]["reachable_decision_maker"], 0.5)
    check("the evidence names what matched, for a reviewer to overrule",
          (ev["buyer_confirmed"], ev["buyer_size"], ev["site_read"]),
          ("Wikidata class or industry", "300 people", False))


def config_and_main():
    print("\n-- the config's lists, and the chain step on a project without the judge")
    J = LJ.Lists(CFG)
    check("the judge is on in the repo config, and every word list compiles", (J.enabled, len(J.wrong) > 10,
                                                                               len(J.major_domain) > 50), (True, True, True))
    check("  the inputs it owns are the config's rubric and modifiers, reach aside",
          (set(LJ.RUBRIC_KEYS) | {LJ.REACH} == {c["key"] for c in CFG["rubric"]},
           set(LJ.MODIFIER_KEYS) == {m["key"] for m in CFG["score_modifiers"]}), (True, True))
    check("  and each gate input it writes feeds a config gate",
          sorted({g["input"].split(".")[-1] for g in CFG["gates"]} - set(LJ.GATE_KEYS)), ["has_reachable_presence"])
    bad = [v for i in SEEN for k, v in i.items() if v is not None and v not in (0, 0.5, 1)]
    check("every value judged above is 0, 0.5, 1 or unknown (%d leads)" % len(SEEN), bad, [])

    import dbconn
    logs = []

    class Cur:
        def execute(self, *a):
            logs.append(a[0])

        def fetchone(self):
            return ("seg-id", {"rubric": []})

    class Db:
        def __init__(self, *a, **k):
            pass

        def run(self, fn):
            return fn(Cur())

        def close(self):
            pass
    keep = dbconn.Db
    dbconn.Db = Db
    try:
        check("main(): a project whose config has no judge.enabled is left alone, exit 0", LJ.main([]), 0)
        check("  having only read its segment row", logs, ["select id, config from segments where slug = %s"])
    finally:
        dbconn.Db = keep
    try:
        LJ.main(["--config", "x.json"])
        refused = False
    except SystemExit:
        refused = True
    check("  --config judges with a file the database has not been given: only with --dry-run", refused, True)


def domains():
    print("\n-- domains: registered names, regional endings, a brand page on a group's domain")
    check("the registered domain, ending included",
          [LJ.reg_domain(d) for d in ("courtyard.marriott.com", "acme.co.uk", "acme.uk.com", "www.acme.com")],
          ["marriott.com", "acme.co.uk", "acme.uk.com", "acme.com"])
    check("a brand's page on its group's domain: courtyard.marriott.com, movieworld.myfun.com.au",
          [LJ.subdomain_of_group(d) for d in ("courtyard.marriott.com", "movieworld.myfun.com.au")], [True, True])
    check("  not a regional or hosted ending, a language, nor the company's own careers or corporate pages",
          [LJ.subdomain_of_group(d) for d in ("acme.uk.com", "acme.vercel.app", "en.acme.com", "fr.acme.co.uk",
                                              "careers.acme.com", "groupe.acme.fr", "corporate.acme.in")],
          [False] * 7)
    cu = lead("Northwind Credit Union", "northwindcu.org", "financial_services", "lcx_fdic",
              {"fdic": {"assets_thousands": 2000000, "country_iso": "US"}},
              title="Northwind Credit Union | Loans, mortgages and savings")
    check("a credit union on a .org domain is a bank, not an association: no wrong_buyer",
          inp(cu, "wrong_buyer"), 0.0)


def site_dns():
    print("\n-- the site pass: a domain is dead only on a definite 'no such host', for it and www.")
    import socket
    import enrich_sitescrape as ES
    keep = socket.getaddrinfo
    calls = []

    def fake(answers):
        def getaddrinfo(host, *a, **k):
            calls.append(host)
            r = answers.get(host, "nohost")
            if r == "ok":
                return [("x",)]
            raise socket.gaierror(socket.EAI_AGAIN if r == "again" else socket.EAI_NONAME, r)
        return getaddrinfo
    try:
        socket.getaddrinfo = fake({"acme.example": "ok"})
        a = ES.resolves("acme.example")
        socket.getaddrinfo = fake({"www.acme.example": "ok"})
        b = ES.resolves("acme.example")
        socket.getaddrinfo = fake({})
        c = ES.resolves("acme.example")
        socket.getaddrinfo = fake({"acme.example": "again"})
        d = ES.resolves("acme.example")
    finally:
        socket.getaddrinfo = keep
    check("resolves: the domain, or only its www., is alive; both 'no such host' is dead; a DNS hiccup is unknown",
          (a, b, c, d), (True, True, False, None))
    sql, params = ES.targets_query(False, None, 10, judged=True, days=7)
    check("  a judged project's contact pass also reads, once, a lead whose address came with the harvest",
          "not (e.metadata ? 'site_contact_routes'))" in sql and "(not exists (select 1 from contacts" in sql, True)
    sql2, _ = ES.targets_query(False, None, 10, judged=False)
    check("  other projects: only leads with no usable address, as before",
          "and not exists (select 1 from contacts" in sql2.replace("\n", " ") or
          " not exists (select 1 from contacts" in sql2, True)


def main():
    misfires()
    buyer_confirmed()
    buyer_size()
    content_activity()
    audience_and_reach()
    wrong_buyer()
    too_big()
    buying_trigger()
    market_language()
    gates()
    scores()
    write_plan()
    config_and_main()
    domains()
    site_dns()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (offline: no database, no network)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
