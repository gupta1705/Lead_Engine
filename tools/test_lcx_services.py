#!/usr/bin/env python3
"""test_lcx_services.py -- the LCX Services project, end to end (2026-10-06).

    python tools/test_lcx_services.py

The owner: one outreach offering every service on docs/LCX Services.pdf, then "it should generate the
leads on its own ... like we source leads for us production houses", "email should be a pitch deck of
services" (a PDF deck attached), everywhere cold business email is allowed, sent once approved.

Checked:
  * the config: every one of the 18 services has buyers to find; the score (v4, the owner 2026-10-07:
    "think and decide one"), by sql/06's arithmetic on the config's own weights: a 100-point pool, the
    basics alone (64, 69 with a named person) never cross the line of 70 and one real signal from the
    company does (72, 74), a perfect wrong buyer or giant stays out (62); the shortlist needs a usable
    contact, a named one for banks and mid-size companies, and a read site; the countries; the weekly
    refresh's steps exist; Apollo inside its budget; the one template attaches the deck, which is built,
    five 16:9 pages, small; the generated SQL is the JSON's
  * the harvest, offline: what a Wikidata, OpenStreetMap, Apollo or FDIC record becomes (only the inputs
    a record settles by itself; the facts the judge reads kept) and what is left out (a consent-law
    country, a chain's branch, a platform page, no name), the order, the city rotation
  * against the database, in ONE transaction rolled back at the end: staging -> the promote chain's
    own SQL and its judge step (tools/lcx_judge.py) -> the published address lifted into a contact ->
    the site pass's text -> judged again, scored -> auto-shortlisted only with a contact (named for a
    mid-size company) and a read site -> drafted with the deck -> approval refuses a missing deck -> the
    page lists the draft with its deck and opens it, and nothing else
  * a project that starts its Write email box from its own email (outreach.compose_start)
  * the Apollo search page works on the project it shows; a project without it is refused
  * an address that answered us in another project gets nothing new
Nothing is sent and no network is used. Exit code 1 on any failure.
"""
import argparse
import datetime as dt
import decimal
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import main  # noqa: E402
import auth  # noqa: E402
import build_deck  # noqa: E402
import dbconn  # noqa: E402
import discover_lcx_services as disc  # noqa: E402
import enrich_lcx_services as lift  # noqa: E402
import explain  # noqa: E402
import gen_segment_sql  # noqa: E402
import lcx_judge  # noqa: E402
import ops  # noqa: E402
import outreach  # noqa: E402
import outreach_compose  # noqa: E402
import outreach_policy as pol  # noqa: E402

RESULTS = []
# the 18 services on docs/LCX Services.pdf, by the names the sheet gives them
SERVICES = ["Reel Forge", "Airbnb / Property Content", "AI VFX + Animation", "Audiobooks and Audio Web Shows",
            "AI Video for Brands", "AI Real Estate Visualisation", "Explainer Videos", "Shop Display Videos",
            "AI UGC Product Videos", "AI Podcasts / Audio Content", "Virtual Tours for Schools",
            "AI Reality Experiences", "Creator × Brand Marketplace", "Local Business Tech and Automation",
            "AI Business Assistant", "AI Simulations for Training", "AI Fashion Stylist", "AI Onboarding Employee"]
# the promote chain's first steps, as tools/run_chain.py runs them: the judge (a Python step) after the merge,
# before 04b fills what is still missing
CHAIN = ["sql/05a_self_exclusion.sql", "sql/05_promote_minimal.sql", "sql/05c_merge_name_duplicates.sql",
         "tools/lcx_judge.py", "sql/04b_zero_unverified.sql"]


def sql06(si, cfg):
    """sql/06_score.sql's arithmetic, written out again here so the config is checked by the scorer's own rule
    and not by the judge's copy of it: earned / assessed points x 100, plus each assessed modifier's value x
    its max_bonus or max_penalty, clamped to 0..100, rounded half up to 2 places (numeric). A key that is
    absent or None is not assessed."""
    D = decimal.Decimal
    earned = assessed = delta = D(0)
    for c in cfg["rubric"]:
        v = si.get(c["key"])
        if v is not None:
            earned += D(str(v)) * D(str(c["points"]))
            assessed += D(str(c["points"]))
    for m in cfg["score_modifiers"]:
        v = si.get(m["key"])
        if v is not None:
            delta += D(str(v)) * D(str(m["max_penalty"] if "max_penalty" in m else m["max_bonus"]))
    if not assessed:
        return None
    s = max(D(0), min(D(100), earned / assessed * 100 + delta))
    return float(s.quantize(D("0.01"), rounding=decimal.ROUND_HALF_UP))


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-74s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


class TxConn:
    """The app's pooled connection, replaced by the test's one transaction (see tools/test_api.py)."""

    def __init__(self, conn):
        self._c, self.closed = conn, 0

    def begin(self):
        with self._c.cursor() as cur:
            cur.execute("savepoint api_req")
        return self

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def commit(self):
        with self._c.cursor() as cur:
            cur.execute("release savepoint api_req")

    def rollback(self):
        with self._c.cursor() as cur:
            cur.execute("rollback to savepoint api_req")
            cur.execute("release savepoint api_req")


class NoPool:
    def putconn(self, conn, close=False):
        pass


class TxDb:
    """dbconn.Db on the same transaction, for the command-line tools (see tools/test_send.py)."""

    def __init__(self, conn):
        self._conn = conn

    def __call__(self, url=None):
        return self

    def run(self, fn, on_reconnect=None):
        with self._conn.cursor() as cur:
            cur.execute("savepoint tool_step")
            try:
                out = fn(cur)
            except Exception:
                cur.execute("rollback to savepoint tool_step")
                raise
            cur.execute("release savepoint tool_step")
            return out

    def close(self):
        pass


def offline(cfg, uni):
    o, tpl = cfg["outreach"], cfg["outreach"]["templates"][0]
    print("-- the config")
    pitched = {s for a in cfg["audiences"] for s in a.get("services") or []}
    check("every one of the 18 services on the sheet has buyers to find", [s for s in SERVICES if s not in pitched], [])
    check("  and nothing is pitched that is not on the sheet", sorted(pitched - set(SERVICES)), [])
    check("  every audience is found somewhere", [a["key"] for a in cfg["audiences"] if not (a.get("wikidata") or a.get("osm"))], [])
    print("\n-- the score (v4, the owner 2026-10-07: \"think and decide one\"), by sql/06's arithmetic on the config")
    rub = {r["key"]: r["points"] for r in cfg["rubric"]}
    mods = {m["key"]: m for m in cfg["score_modifiers"]}
    check("a pool of 100: confirmed in its own words 30, size 25, content 20, fit 15, reach 10",
          (sum(rub.values()), rub), (100, {"buyer_confirmed": 30, "buyer_size": 25, "content_activity": 20,
                                           "audience_fit": 15, "reachable_decision_maker": 10}))
    check("  bonuses +8 trigger, +4 market; penalties -50 wrong buyer, -50 too big, -15 not English; one each",
          ({k: m.get("max_bonus", m.get("max_penalty")) for k, m in mods.items()},
           [k for k, m in mods.items() if ("max_bonus" in m) == ("max_penalty" in m)]),
          ({"buying_trigger": 8, "priority_market": 4, "wrong_buyer": -50, "too_big": -50, "non_english_site": -15}, []))
    check("  every input is read from metadata.scoring_inputs under its own key",
          [x["key"] for x in cfg["rubric"] + cfg["score_modifiers"] if x["input"] != "metadata.scoring_inputs." + x["key"]],
          [])
    line = cfg["auto_shortlist"]["min_score"]
    # the lattice the line was set on: a directory label (0.5), the right size, a full-fit audience, a
    # business inbox and a priority market are "the basics"; the site read and linking no account (0)
    basics = {"buyer_confirmed": 0.5, "buyer_size": 1.0, "content_activity": 0.0, "audience_fit": 1.0,
              "reachable_decision_maker": 0.5, "priority_market": 1.0}
    perfect = {k: 1.0 for k in list(rub) + ["buying_trigger", "priority_market"]}
    lattice = [("the basics alone", basics, 64.0, False),
               ("  the same with a named person: reach alone never pushes the basics over",
                dict(basics, reachable_decision_maker=1.0), 69.0, False),
               ("  + a strong buying trigger crosses", dict(basics, buying_trigger=1.0), 72.0, True),
               ("  + one video or Instagram account crosses", dict(basics, content_activity=0.5), 74.0, True),
               ("  + its own words confirming the audience crosses", dict(basics, buyer_confirmed=1.0), 79.0, True),
               ("a perfect lead with both bonuses but the wrong buyer stays out", dict(perfect, wrong_buyer=1.0),
                62.0, False),
               ("  or too big", dict(perfect, too_big=1.0), 62.0, False)]
    for name, si, want, over in lattice:
        got = sql06(si, cfg)
        check("%s: %g, %s the line of %g" % (name, want, "over" if over else "not over", line), (got, got > line),
              (want, over))
    check("the shortlist: above 70, only with a contact the drafter writes to (a named one for banks and mid-size"
          " companies), and only once its content was assessed (its site read)",
          {k: cfg["auto_shortlist"].get(k) for k in ("enabled", "min_score", "require_contact", "named_contact_for",
                                                    "require_assessed")},
          {"enabled": True, "min_score": 70, "require_contact": True,
           "named_contact_for": ["corporate_teams", "financial_services"], "require_assessed": ["content_activity"]})
    check("  every audience named there is one, and the assessed input is the rubric's",
          ([k for k in cfg["auto_shortlist"]["named_contact_for"] if k not in {a["key"] for a in cfg["audiences"]}],
           [k for k in cfg["auto_shortlist"]["require_assessed"] if k not in rub]), ([], []))
    check("display bands: review 50, priority 85", (cfg["score_threshold_review"], cfg["score_threshold_priority"]),
          (50, 85))
    check("the gates: consent law, sanctioned countries, the majors, brand safety, a live site, a way in",
          [(g["key"], g["exclude_when"]) for g in cfg["gates"]],
          [("country_allowed", "disallowed"), ("payable_country", "unpayable"), ("not_major", True),
           ("brand_safe", "unsafe"), ("site_alive", "dead"), ("usable_first_party_presence", False)])
    check("  sanctioned: Russia, Belarus, Iran, North Korea, Syria, Cuba",
          sorted(cfg["geography"]["unpayable_countries"]), ["BY", "CU", "IR", "KP", "RU", "SY"])
    check("the judge is on, and every audience has its own words and size bands to be judged by",
          (cfg["judge"]["enabled"], [a["key"] for a in cfg["audiences"] if not (a.get("site_words") and a.get("size_bands"))]),
          (True, []))
    check("  cafes keep full audience fit; banks and attractions half",
          {a["key"]: a["fit"] for a in cfg["audiences"] if a["key"] in ("local_business", "financial_services", "attractions")},
          {"local_business": 1.0, "financial_services": 0.5, "attractions": 0.5})
    check("  the retired inputs are scored nowhere", [k for k in cfg["judge"]["retired_inputs"] if k in rub or k in mods], [])
    check("everywhere except the consent-law countries", (cfg["geography"]["allowed_countries"],
          sorted(cfg["geography"]["disallowed_countries"])), ([], ["AT", "CA", "DE", "IT"]))
    steps = cfg["pipelines"]["weekly_refresh"]
    check("the weekly refresh's steps all exist, and run here", [s for s in steps if s not in ops.JOBS or
          ops.JOBS[s].get("segments") not in (None, ["lcx-services"])], [])
    check("  on Fridays, like a harvest", (cfg["schedule"][0]["pipeline"], cfg["schedule"][0]["dow"]), ("weekly_refresh", 4))
    e = cfg["enrichment"]
    check("Apollo is on (the owner, 2026-10-07: 'Enriching from apollo is acceptable'), inside a stated budget",
          (e["enabled"], e["provider"], e["credits_per_week"], e["keep_in_reserve"], e["reveal_countries"]),
          (True, "apollo", 120, 700, ["US", "GB", "IN", "AE"]))
    check("  reveals only for leads over 60 whose own site was read (the owner, 2026-10-07)",
          (e["score_over"], e["require_site_read"]), (60, True))
    check("  the discovery pages fit inside the week's cap with room for the reveals",
          cfg["apollo_discovery"]["pages_per_run"] <= e["credits_per_week"] - e["credits_per_run"], True)
    check("  Apollo searches only where its addresses may be written to without consent",
          [c["iso"] for c in cfg["apollo_discovery"]["countries"]], ["US", "GB", "IN", "AE"])
    check("  every Apollo search names an audience that exists, and every audience has contact roles",
          ([s["key"] for s in cfg["apollo_discovery"]["searches"] if s["audience"] not in {a["key"] for a in cfg["audiences"]}],
           [a["key"] for a in cfg["audiences"] if not a.get("contact_roles")]), ([], []))
    check("normal corporates: an audience of mid-size companies for the training services, listed companies included",
          [(a["key"], a["wikidata"][0]["property"]) for a in cfg["audiences"] if a["key"] == "corporate_teams"],
          [("corporate_teams", "P414")])
    check("fewer cafes: OpenStreetMap down to 150 a week, 2 cities",
          (cfg["discovery"]["osm"]["max_new_per_run"], cfg["discovery"]["osm"]["cities_per_run"]), (150, 2))
    check("emails are drafted, not written by hand; sent from the approver; not paused",
          (bool(o["templates"]), "compose" in o, o["send_from"], "sending_paused" in o), (True, False, "approver", False))
    check("TVF's Mumbai address goes under it (the owner's choice)", o["sender"]["postal_address"],
          uni["outreach"]["sender"]["postal_address"])
    check("one template, the wording the owner approved", (tpl["subject"], tpl["body"].splitlines()[2]),
          ("18 things LCX can do for {{company}}", "I'm writing from LCX. We work in three areas, and at least one of"
           " them should be useful to {{company}}. Our services deck is attached."))
    check("  it attaches the deck", tpl["attachments"], ["docs/decks/LCX Services - pitch deck.pdf"])
    check("the deck is built: a PDF, five 16:9 pages, small enough to attach", build_deck.check(), [])
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    check("  and the server's image carries it (the sender reads it there)",
          ("COPY docs/decks/ ./docs/decks/" in docker, [x for x in ignored if x in ("docs", "docs/", "docs/decks", "*.pdf")]),
          (True, []))
    deck = (ROOT / "docs" / "decks" / "lcx-services-deck.html").read_text(encoding="utf-8")
    check("  every service is on it", [s for s in SERVICES if s.replace("×", "&times;") not in deck], [])
    check("the generated SQL is the JSON's", gen_segment_sql.render("lcx-services", cfg),
          (ROOT / "sql" / "03f_segment_lcx_services.sql").read_text(encoding="utf-8"))

    print("\n-- the harvest, offline")
    brands = next(a for a in cfg["audiences"] if a["key"] == "consumer_brands")
    good = {"qid": "Q101", "label": "Acme Foods", "webs": ["https://www.acmefoods.example/"], "isos": ["IN"],
            "employees": 450, "emails": ["mailto:hello@acmefoods.example"]}
    row, why = disc.wikidata_row(good, brands, cfg)
    check("a Wikidata company: its website, country, size and address", (row["domain"], row["raw"]["wikidata"]["country_iso"],
          row["raw"]["published_email"], row["source_url"]), ("acmefoods.example", "IN", "hello@acmefoods.example",
                                                               "https://www.wikidata.org/wiki/Q101"))
    check("  staged with only what the record settles by itself; the judge sets the rest on each chain run",
          row["raw"]["scoring_inputs"], {"audience_fit": 1.0, "has_reachable_presence": True, "oversized_signal": False,
                                         "country_signal": "allowed"})
    check("  a company over 50,000 people is oversized (not_major); one in a sanctioned country is unpayable",
          (disc.wikidata_row(dict(good, employees=60000), brands, cfg)[0]["raw"]["scoring_inputs"]["oversized_signal"],
           disc.wikidata_row(dict(good, isos=["RU"]), brands, cfg)[0]["raw"]["scoring_inputs"]["country_signal"]),
          (True, "unpayable"))
    check("  and says what to pitch", row["raw"]["why_fit"].endswith("Pitch first: AI Video for Brands, AI UGC Product Videos,"
                                                                       " Explainer Videos, Creator × Brand Marketplace."), True)
    for name, rec, reason in (("only in a consent-law country", dict(good, isos=["DE"]), "a consent-law country"),
                              ("a platform page for a website", dict(good, webs=["https://facebook.com/acme"]), "no website of its own"),
                              ("no name in English", dict(good, label="Q101"), "no name in English")):
        check("  left out: %s" % name, disc.wikidata_row(rec, brands, cfg), (None, reason))
    check("  a company in Germany and India is kept, as Indian", disc.wikidata_row(dict(good, isos=["DE", "IN"]), brands, cfg)[0]
          ["raw"]["wikidata"]["country_iso"], "IN")
    order = sorted([("Q5", 120000), ("Q4", 7000), ("Q3", None), ("Q2", 300), ("Q1", 5)], key=lambda x: disc.size_order(*x))
    check("  the right size first, the giants last", [q for q, _ in order], ["Q2", "Q3", "Q4", "Q1", "Q5"])
    mk = [disc.market(isos, cfg) for isos in (["GB"], [], ["JP"], ["DE"], ["DE", "IN"])]
    check("  an English-speaking market first, then unknown, then the rest; consent-law only never", mk, [0, 1, 2, 3, 0])
    same = sorted([("Q7", 300, 2), ("Q9", 300, 0), ("Q8", 300, 1)], key=lambda x: disc.size_order(*x))
    check("  so among companies of the same size, the English-speaking one is taken first", [q for q, _, _ in same],
          ["Q9", "Q8", "Q7"])
    cafes = next(a for a in cfg["audiences"] if a["key"] == "local_business")
    city = {"name": "London", "country": "GB", "lat": 51.5, "lon": -0.12}
    el = {"type": "node", "id": 42, "tags": {"amenity": "cafe", "name": "Bean There", "website": "https://beanthere.example",
                                             "email": "Hello@BeanThere.example; other@x.example", "phone": "+44 20 0000 0000"}}
    row, why = disc.osm_row(el, city, cafes, cfg)
    check("an OpenStreetMap cafe: its own website and published address", (row["domain"], row["raw"]["published_email"],
          row["raw"]["osm"]["attribution"]), ("beanthere.example", "hello@beanthere.example", disc.ATTRIBUTION))
    check("  staged with only what the record settles; a complete listing (website and phone) noted for the order",
          (row["raw"]["scoring_inputs"], row["raw"]["osm"]["complete"]),
          ({"audience_fit": 1.0, "has_reachable_presence": True, "country_signal": "allowed"}, True))
    tagged = disc.osm_row(dict(el, tags=dict(el["tags"], **{"contact:instagram": "https://instagram.com/beanthere",
                                                           "youtube": "https://youtube.com/@beanthere"})),
                          city, cafes, cfg)[0]
    check("  the accounts it lists for itself are kept: the judge counts them as content",
          ({k: v for k, v in tagged["raw"]["osm"].items() if k in disc.OSM_ACCOUNT_TAGS},
           lcx_judge.judge({"name": "Bean There", "domain": "beanthere.example",
                            "metadata": {"kind": "local_business", "discovery_raw": {"lcx_osm": tagged["raw"]}}},
                           cfg)[0]["content_activity"]),
          ({"contact:instagram": "https://instagram.com/beanthere", "youtube": "https://youtube.com/@beanthere"}, 1.0))
    for name, tags, reason in (("a chain's branch", dict(el["tags"], brand="Costa"), "a chain's branch"),
                               ("nothing to reach it by", {"amenity": "cafe", "name": "No Site"}, "no website or address of its own"),
                               ("no name", {"amenity": "cafe", "website": "https://x.example"}, "no name"),
                               ("another kind of place", {"amenity": "bank", "name": "B", "website": "https://b.example"},
                                "another kind of place")):
        check("  left out: %s" % name, disc.osm_row(dict(el, tags=tags), city, cafes, cfg), (None, reason))
    insta = disc.osm_row(dict(el, tags={"amenity": "cafe", "name": "Insta Cafe", "website": "https://instagram.com/insta",
                                        "email": "insta@gmail.com"}), city, cafes, cfg)[0]
    check("  an Instagram page is no website, but its published address still counts", (insta["domain"],
          insta["raw"]["published_email"]), (None, "insta@gmail.com"))
    cities = cfg["osm_discovery"]["cities"]
    import datetime as dt
    weeks = [{c["name"] for c in disc.city_slice(cities, 6, dt.date(2026, 1, 5) + dt.timedelta(weeks=w))} for w in range(7)]
    check("the cities rotate: seven weeks cover all %d" % len(cities), len(set().union(*weeks)), len(cities))
    check("  each week a different six", all(len(w) == 6 for w in weeks) and weeks[0] != weeks[1], True)
    q = disc.osm_query(city, cafes, 12000)
    check("one Overpass query per city and audience, for places with a website or an address",
          ('[~"^(amenity|leisure|shop)$"~"^(beauty|cafe|fitness_centre|hairdresser)$"]' in q,
           '[~"^(contact:)?(website|email)$"~"."]' in q, "(around:12000,51.5,-0.12)" in q), (True, True, True))
    # the two loops, with the network stubbed: what is found is saved as it is found, the even shares hold
    real = (disc.overpass, disc.wikidata_ids, disc.wikidata_details, disc.time.sleep, disc.wikidata_extra)
    disc.time.sleep = lambda s: None
    extra_calls = []

    def fake_extra(qids):
        """The judge's Wikidata fields (lcx_judge.wikidata_more), stubbed: the config has judge.enabled, so the
        harvest asks for them for every 50 companies staged."""
        extra_calls.append(list(qids))
        return {q: {"socials": {"youtube": "UC" + q}, "students": 400} for q in qids}
    disc.wikidata_extra = fake_extra
    try:
        import re

        def fake_overpass(query, endpoints, pause=2.0):
            """39 cafes around each city, every third publishing an address; every other audience's
            endpoint fails."""
            if "fitness_centre" not in query:
                raise RuntimeError("no OpenStreetMap endpoint answered: HTTP Error 504")
            off = int(abs(float(re.search(r"around:\d+,(-?[\d.]+)", query).group(1))) * 1000)
            return [{"type": "node", "id": off + i, "tags": {"amenity": "cafe", "name": "Cafe %d" % (off + i),
                     "website": "https://cafe%d.example" % (off + i),
                     **({"email": "hi@cafe%d.example" % (off + i)} if i % 3 == 0 else {})}} for i in range(1, 40)]
        disc.overpass = fake_overpass
        saved = []
        one = dict(cfg, osm_discovery=dict(cfg["osm_discovery"], cities=cfg["osm_discovery"]["cities"][:2]))
        rows, why = disc.run_osm(one, 120, 2, set(), set(), ["x"], emit=saved.append)
        per = 120 // (2 * len(disc.audiences(cfg, "osm")))
        check("OpenStreetMap: every place is saved as it is found", [r["source_url"] for r in saved],
              [r["source_url"] for r in rows])
        check("  an even share per city and audience (%d each), those with an address first" % per,
              (len(rows), len({r["raw"]["osm"]["city"] for r in rows}), all(r["raw"]["published_email"] for r in rows)),
              (2 * per, 2, True))
        check("  an endpoint that fails skips that city and audience, and the run goes on", len(rows) > 0, True)
        rows, why = disc.run_osm(one, 600, 2, set(), set(), ["x"], emit=saved.append, deadline=disc.time.monotonic() - 1)
        check("  out of time: it stops asking, keeping what it has", rows, [])

        def wd_base(match):
            return (int(match["values"][0][1:]) if match.get("values") else int(match["property"][1:])) % 100000 * 100

        def fake_ids(match):                 # each audience its own companies, half of them in an English market
            base = wd_base(match)
            return {"Q%d" % (base + i): (100 + i, ["US"] if i % 2 else ["JP"]) for i in range(1, 30)}

        def fake_details(qids):
            return {q: {"qid": q, "label": "Co %s" % q, "webs": ["https://co-%s.example" % q.lower()], "isos": ["US"],
                        "employees": 300, "emails": []} for q in qids}
        disc.wikidata_ids, disc.wikidata_details = fake_ids, fake_details
        saved = []
        rows, why = disc.run_wikidata(cfg, 90, 80, set(), set(), emit=saved.append)
        n_aud = len(disc.audiences(cfg, "wikidata"))
        check("Wikidata: every company saved as it is found, an equal share per audience",
              (len(saved) == len(rows), len(rows)), (True, n_aud * (90 // n_aud)))
        base = wd_base(disc.audiences(cfg, "wikidata")[0]["wikidata"][0])
        check("  the English-speaking market taken first within the same size", [r["raw"]["wikidata"]["qid"] for r in rows[:3]],
              ["Q%d" % (base + i) for i in (1, 3, 5)])
        check("  each with the judge's Wikidata fields (accounts, pupils, ...), at most 50 a query, each fetched once",
              (all(r["raw"]["wikidata"].get("socials") and r["raw"]["wikidata"].get("details_at") for r in rows),
               max(len(c) for c in extra_calls) <= 50, sorted(q for c in extra_calls for q in c)
               == sorted(r["raw"]["wikidata"]["qid"] for r in rows)), (True, True, True))

        def down(qids):
            raise OSError("Wikidata did not answer")
        disc.wikidata_extra = down
        rows, why = disc.run_wikidata(cfg, 20, 80, set(), set())
        check("  Wikidata down for those fields: the companies are staged anyway, for the back-fill to fill",
              (len(rows) > 0, any("details_at" in r["raw"]["wikidata"] for r in rows)), (True, False))
    finally:
        disc.overpass, disc.wikidata_ids, disc.wikidata_details, disc.time.sleep, disc.wikidata_extra = real
    print("\n-- the corporate sources, offline")
    sls = disc.apollo_slices(cfg)
    now = dt.datetime(2026, 10, 9, 2, 0, tzinfo=dt.timezone.utc)
    sig = next(s for s in sls if s["key"] == "corporates_hiring_trainers|US")
    fixed = next(s for s in sls if s["key"] == "brands|US")
    ago = lambda d: now - dt.timedelta(days=d)          # noqa: E731
    check("a fixed search goes on page by page, and waits once used up",
          [disc.slice_page(fixed, {"brands|US": c}, now) for c in
           ({"next_page": 4, "last_run_at": ago(60)}, {"exhausted": True, "exhausted_at": ago(400)})], [4, None])
    check("  a signal search (hiring in the last 30 days) rests 30 days once used up, then starts again at page 1",
          [disc.slice_page(sig, {sig["key"]: c}, now) for c in
           ({"exhausted": True, "exhausted_at": ago(3)}, {"exhausted": True, "exhausted_at": ago(31)})], [None, 1])
    check("  part-way through, it goes on with its next page however long ago (page 1 would be the same big employers)",
          [disc.slice_page(sig, {sig["key"]: {"next_page": 3, "last_run_at": ago(d)}}, now) for d in (7, 40)], [3, 3])
    check("Apollo: every search in every country, one cursor each",
          (len(sls), len({s["key"] for s in sls})),
          (len(cfg["apollo_discovery"]["searches"]) * 4, len(cfg["apollo_discovery"]["searches"]) * 4))
    check("  the first run mixes countries: a diagonal through searches and countries, not every US slice first",
          [s["key"] for s in disc.slice_order([s for s in sls if not s["search"].get("signal")], {})][:6],
          ["brands|US", "developers|US", "brands|GB", "retailers|US", "developers|GB", "brands|IN"])
    hiring = next(s for s in sls if s["key"] == "corporates_hiring_trainers|GB")
    f = disc.apollo_filters(hiring, dt.date(2026, 10, 7))
    check("  a signal slice: its country, and jobs posted in the last 30 days",
          (f["organization_locations"], f["organization_job_posted_at_range"]),
          (["United Kingdom"], {"min": "2026-09-07", "max": "2026-10-07"}))
    funded = disc.apollo_filters(next(s for s in sls if s["key"] == "brands_recently_funded|US"), dt.date(2026, 10, 7))
    check("  the funded slice: rounds in the last 90 days, and no free check (people search has no funding filter)",
          (funded["latest_funding_date_range"]["min"],
           any(k in funded for k in disc.COMPANY_ONLY)), ("2026-07-09", True))
    # sizes: since 2026-10-07 the judge sizes a lead by its audience's own bands (tools/test_lcx_judge.py);
    # an Apollo row keeps the slice's band as text, below, and that band alone is half
    aud_corp = next(a for a in cfg["audiences"] if a["key"] == "corporate_teams")
    org = {"id": "a" * 24, "name": "Acme Training Ltd", "website_url": "https://www.acme-training.example/",
           "primary_domain": "acme-training.example", "founded_year": 2001, "linkedin_url": "https://linkedin.com/x"}
    arow, _ = disc.apollo_row(org, hiring, aud_corp, cfg, dt.date(2026, 10, 7))
    check("an Apollo company: its website, Apollo's id, and the slice's country and size",
          (arow["domain"], arow["source_url"], arow["raw"]["apollo_search"]["country_iso"], arow["raw"]["apollo"]["id"]),
          ("acme-training.example", "https://app.apollo.io/#/organizations/" + "a" * 24, "GB", "a" * 24))
    check("  staged with only what the record settles; its buying signal kept, dated, for the judge to fade",
          (arow["raw"]["scoring_inputs"], arow["raw"]["apollo_search"]["signal"],
           arow["raw"]["apollo_search"]["signal_seen_at"], arow["raw"]["apollo_search"]["size_band"]),
          ({"audience_fit": 1.0, "has_reachable_presence": True, "country_signal": "allowed"},
           "hiring for training and onboarding now", "2026-10-07", "201-5,000 people"))
    check("  says why: the signal, the country, what to pitch",
          arow["raw"]["why_fit"].startswith("Mid-size company in United Kingdom, on Apollo (hiring for training and onboarding now)."),
          True)
    check("  never a LinkedIn link kept", "linkedin" in json.dumps(arow), False)
    big = disc.apollo_row(dict(org, annual_revenue_printed="12B", owned_by_organization_id="b" * 24), hiring, aud_corp,
                          cfg, dt.date(2026, 10, 7))[0]["raw"]
    check("  revenue of $10B or more is oversized (not_major), and the parent company's id is kept for the judge",
          (big["scoring_inputs"]["oversized_signal"], big["apollo"]["owned_by_organization_id"],
           disc.apollo_row(dict(org, annual_revenue_printed="4.8M"), hiring, aud_corp, cfg,
                           dt.date(2026, 10, 7))[0]["raw"]["scoring_inputs"]["oversized_signal"]), (True, "b" * 24, False))
    check("  TVF itself is never a lead", disc.apollo_row(dict(org, name="The Viral Fever", website_url="https://theviralfever.com"),
                                                          hiring, aud_corp, cfg)[1], "TVF or an affiliate")
    check("  Apollo's primary domain first, as a company saved from the search page has it",
          disc.apollo_row(dict(org, website_url="https://acme-training.example.co.uk/careers"), hiring, aud_corp, cfg)[0]["domain"],
          "acme-training.example")
    check("  nor a company with only a social page", disc.apollo_row(dict(org, website_url="https://facebook.com/acme",
                                                                         primary_domain=None), hiring, aud_corp, cfg)[1],
          "no website of its own")
    banks = [{"NAME": "Big Bank", "WEBADDR": "www.bigbank.example", "CITY": "NEW YORK", "STALP": "NY", "ASSET": 900000000, "CERT": 1},
             {"NAME": "Mid Bank", "WEBADDR": "http://www.MIDBANK.example", "CITY": "DALLAS", "STALP": "TX", "ASSET": 5000000, "CERT": 2},
             {"NAME": "Mid Bank Two", "WEBADDR": "midbank2.example", "CITY": "BOSTON", "STALP": "MA", "ASSET": 1200000, "CERT": 3},
             {"NAME": "Tiny Bank", "WEBADDR": "tiny.example", "CITY": "X", "STALP": "WI", "ASSET": 200000, "CERT": 4},
             {"NAME": "No Site Bank", "WEBADDR": "", "CITY": "X", "STALP": "WI", "ASSET": 3000000, "CERT": 5}]
    got, why = disc.run_fdic(cfg, 10, set(), {"midbank2.example"}, banks=banks)
    check("FDIC: only banks of $1-20 billion with a website, largest first, none already a lead",
          ([r["domain"] for r in got], sorted(why.items())),
          (["midbank.example"], [("already a lead here or in another project", 1), ("no website of its own", 1),
                                 ("outside the asset band", 2)]))
    keep_fb = disc.fdic_banks

    def down():
        raise OSError("timed out")
    disc.fdic_banks = down
    try:
        check("  FDIC down: no banks this run, and the step does not fail the refresh",
              disc.run_fdic(cfg, 10, set(), set()), ([], {"FDIC BankFind did not answer": 1}))
    finally:
        disc.fdic_banks = keep_fb
    check("  a bank: the financial-services audience, in the US, its assets kept (the judge sizes it by them)",
          (got[0]["raw"]["kind"], got[0]["raw"]["fdic"]["country_iso"], got[0]["raw"]["fdic"]["assets_thousands"],
           got[0]["raw"]["scoring_inputs"]),
          ("financial_services", "US", 5000000, {"audience_fit": 0.5, "has_reachable_presence": True,
                                                 "country_signal": "allowed"}))
    meta, email, src = lift.lift({"discovery_raw": {"lcx_osm": row["raw"]}, "why_fit": "a person's own words"})
    check("lifting: the audience, services and place go on the lead, a person's words stay",
          (meta["kind"], meta["audience"], meta["hq_city"], meta["hq_country"], meta["why_fit"], email, src),
          ("local_business", "Cafe, salon or gym", "London", "GB", "a person's own words", "hello@beanthere.example", "lcx_osm"))
    meta, email, src = lift.lift({"discovery_raw": {"lcx_apollo": arow["raw"]}})
    check("  an Apollo company: its country and size band from the search, its Apollo record for the person search",
          (meta["kind"], meta["hq_country"], meta["buying_signal"], meta["apollo"]["id"], email, src),
          ("corporate_teams", "GB", "hiring for training and onboarding now", "a" * 24, None, "lcx_apollo"))
    m = lift.with_reachable({"scoring_inputs": {"reachable_decision_maker": 0}, "unverified_inputs": ["reachable_decision_maker", "x"]})
    check("  a published address is half the contact points, and no longer unverified",
          (m["scoring_inputs"]["reachable_decision_maker"], m["unverified_inputs"]), (0.5, ["x"]))
    check("  a named person found earlier is never lowered", lift.with_reachable({"scoring_inputs": {"reachable_decision_maker": 1.0}})
          ["scoring_inputs"]["reachable_decision_maker"], 1.0)


def main_():
    cfg = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
    uni = json.loads((ROOT / "config" / "segment.universal.json").read_text(encoding="utf-8"))
    offline(cfg, uni)

    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    kicks = []
    main._scheduler.kick_outreach = lambda seg, trigger="manual": kicks.append((seg, trigger))
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)
    real_db, real_seg, real_lift_seg = dbconn.Db, outreach.SEGMENT, lift.SEGMENT
    dbconn.Db = TxDb(conn)

    def call(method, url, cookies=None, **kw):
        client.cookies.clear()
        return client.request(method, url, cookies=cookies, **kw)

    try:
        cur = conn.cursor()

        def project(slug, c):
            cur.execute("insert into segments (slug, name, entity_type, config) values (%s, %s, 'company', %s)"
                        " returning id", (slug, "ZZ " + slug, json.dumps(c)))
            return cur.fetchone()[0]

        tag = uuid.uuid4().hex[:6]
        lx, un, no, cp = ("zz-lcxs-" + tag, "zz-uni-" + tag, "zz-noapollo-" + tag, "zz-compose-" + tag)
        lx_id, un_id = project(lx, cfg), project(un, uni)
        plain = json.loads(json.dumps(cfg))
        plain["ui"].pop("search_page")
        no_id = project(no, plain)
        start = {"subject": "Hello from LCX, {{company}}", "body": "Hi {{first_name}},\n\nA starting email."}
        cp_cfg = json.loads(json.dumps(uni))
        cp_cfg["outreach"]["compose_start"] = start
        project(cp, cp_cfg)
        main._SEG_CACHE.update(at=0.0, rows=[])
        email = "zz-lcxs-%s@example.com" % tag
        pw = bcrypt.hashpw(b"zz", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                    (email, pw, "Asha Rao", "Partnerships"))
        session = auth.make_cookie(email, pw)

        def as_(slug):
            return {auth.COOKIE: session, "tvf_segment": slug}

        # ------------------------------------------------------------ the harvest, into the pool
        print("\n-- the harvest, through the promote chain, to a draft with the deck")
        brands = next(a for a in cfg["audiences"] if a["key"] == "consumer_brands")
        cafes = next(a for a in cfg["audiences"] if a["key"] == "local_business")
        corps = next(a for a in cfg["audiences"] if a["key"] == "corporate_teams")
        city = {"name": "London", "country": "GB", "lat": 51.5, "lon": -0.12}
        bean_n, acme_n = "ZZ Bean There %s" % tag, "ZZ Acme Foods %s" % tag
        toys_n, corp_n = "ZZ Unread Toys %s" % tag, "ZZ Northwind %s" % tag
        qid = lambda n: "Q9%s%d" % (tag[:4].encode().hex()[:6], n)        # noqa: E731
        staged = [disc.wikidata_row({"qid": qid(1), "label": acme_n, "webs": ["https://zz-acme-%s.example" % tag],
                                     "isos": ["IN"], "employees": 450, "emails": []}, brands, cfg)[0],
                  disc.osm_row({"type": "node", "id": int(tag, 16), "tags": {
                      "amenity": "cafe", "name": bean_n, "website": "https://zz-bean-%s.example" % tag,
                      "email": "hello@zz-bean-%s.example" % tag, "opening_hours": "Mo-Su 08:00-18:00"}}, city, cafes, cfg)[0],
                  # a brand that publishes an inbox on Wikidata, and whose site nobody has read
                  disc.wikidata_row({"qid": qid(2), "label": toys_n, "webs": ["https://zz-toys-%s.example" % tag],
                                     "isos": ["GB"], "employees": 300, "emails": ["mailto:hello@zz-toys-%s.example" % tag]},
                                    brands, cfg)[0],
                  # a listed mid-size company, which the site pass will find only an info@ inbox for
                  disc.wikidata_row({"qid": qid(3), "label": corp_n, "webs": ["https://zz-northwind-%s.example" % tag],
                                     "isos": ["GB"], "employees": 800, "emails": []}, corps, cfg)[0]]
        for r in staged:
            cur.execute("insert into staging_candidates (segment_id, name, domain, source, source_url, raw) values"
                        " (%s, %s, %s, %s, %s, %s)", (lx_id, r["name"], r["domain"],
                                                      "lcx_wikidata" if "wikidata" in r["raw"] else "lcx_osm",
                                                      r["source_url"], json.dumps(r["raw"])))
        # a company already ruled out, found again under another website: the name-level shield keeps it out,
        # and the chain must say so rather than fail (it did, on LCX Clipping's refresh of 2026-10-07)
        shield = "ZZ Ruled Out %s" % tag
        cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'lcx_wikidata',"
                    " 'archived')", (lx_id, shield, "zz-ruled-%s.example" % tag))
        cur.execute("insert into staging_candidates (segment_id, name, domain, source, source_url, raw) values"
                    " (%s, %s, %s, 'lcx_wikidata', %s, %s)", (lx_id, shield, "zz-ruled-again-%s.example" % tag,
                                                              "https://www.wikidata.org/wiki/Q77%s" % tag[:4].encode().hex()[:5],
                                                              json.dumps(staged[0]["raw"])))
        cur.execute("select set_config('tvf.segment', %s, true)", (lx,))
        lcx_judge.SEGMENT = lx

        def chain(steps=CHAIN):
            for f in steps:
                if f.endswith(".py"):
                    check("  the chain's judge step runs (exit 0)", lcx_judge.main([]), 0)
                else:
                    cur.execute((ROOT / f).read_text(encoding="utf-8"))
        chain()
        cur.execute("select name, status, metadata from entities where segment_id = %s order by name", (lx_id,))
        got = {r[0]: r for r in cur.fetchall()}
        check("all four are leads of LCX Services after the promote chain", sorted(n for n in got if n != "ZZ Ruled Out %s" % tag),
              sorted([acme_n, bean_n, corp_n, toys_n]))
        si = got[acme_n][2]["scoring_inputs"]
        check("  judged at once: unknown as JSON null (no site read, nobody measured), reach 0, no retired key",
              ({k: si.get(k, "absent") for k in ("buyer_confirmed", "buyer_size", "content_activity", "audience_fit",
                                                 "reachable_decision_maker", "established", "right_size")},
               got[acme_n][2]["lcx_judgement"]["buyer_confirmed"]),
              ({"buyer_confirmed": 0.5, "buyer_size": 1.0, "content_activity": None, "audience_fit": 1.0,
                "reachable_decision_maker": 0, "established": "absent", "right_size": "absent"},
               "Wikidata class or industry"))
        cur.execute("select import_result from staging_candidates where segment_id = %s and name = %s", (lx_id, shield))
        check("a company ruled out before, found again: kept out, and the chain says why", [r[0] for r in cur.fetchall()],
              ["skipped_shielded_name"])
        cur.execute("select count(*) from entities where segment_id = %s and name = %s", (lx_id, shield))
        check("  still one lead of that name, the archived one", cur.fetchone()[0], 1)
        lift.SEGMENT = lx
        sys.argv = ["enrich_lcx_services.py"]
        lift.main()
        cur.execute("select e.name, c.email, c.source, c.email_status from contacts c join entities e on e.id = c.entity_id"
                    " where e.segment_id = %s order by e.name", (lx_id,))
        check("the published addresses became contacts (the cafe's on the map, the toy brand's on Wikidata)",
              [tuple(r) for r in cur.fetchall()],
              [(bean_n, "hello@zz-bean-%s.example" % tag, "osm", "unverified"),
               (toys_n, "hello@zz-toys-%s.example" % tag, "wikidata", "unverified")])
        # the site pass (tools/enrich_sitescrape.py), as it leaves a lead: the home page's own words, the accounts
        # it links, and for the corporate an info@ inbox read off its site (reach 0.5, a role inbox)
        read_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
        site = {bean_n: ("%s | Café and coffee in London" % bean_n, "Our café serves speciality coffee and brunch every day.",
                         {"instagram": "https://www.instagram.com/zzbean"}),
                corp_n: ("%s | Stores nationwide" % corp_n,
                         "Our 2,000 team members serve customers in 40 stores and a customer service centre.",
                         {"youtube": "https://www.youtube.com/@zznorthwind", "instagram": "https://www.instagram.com/zznw"})}
        for name, (title, desc, socials) in site.items():
            cur.execute("update entities set metadata = metadata || jsonb_build_object('site_about', %s::jsonb,"
                        " 'site_contact_routes', %s::jsonb) where segment_id = %s and name = %s",
                        (json.dumps({"title": title, "description": desc, "about": "", "read_at": read_at}),
                         json.dumps({"socials": socials, "pages_read": 3, "read_at": read_at}), lx_id, name))
        cur.execute("insert into contacts (entity_id, email, email_status, source) select id, 'info@' || domain,"
                    " 'unverified', 'site_scrape' from entities where segment_id = %s and name = %s", (lx_id, corp_n))
        cur.execute("update entities set metadata = jsonb_set(metadata, '{scoring_inputs,reachable_decision_maker}', '0.5')"
                    " where segment_id = %s and name = %s", (lx_id, corp_n))
        # the toy brand's accounts are listed on Wikidata: content_activity is assessed, its site still unread
        cur.execute("update entities set metadata = jsonb_set(metadata, '{discovery_raw,lcx_wikidata,wikidata,socials}',"
                    " '{\"youtube\": \"UCzztoys\", \"instagram\": \"zztoys\"}'::jsonb) where segment_id = %s and name = %s",
                    (lx_id, toys_n))
        # the refresh's next promote_chain: its judge reads the new site text, then 04b (promote and merge have
        # nothing new to take, and their temporary tables cannot be made twice in one transaction)
        chain(CHAIN[CHAIN.index("tools/lcx_judge.py"):])
        cur.execute("select count(*) from score_segment(%s)", (lx,))
        cur.fetchone()
        cur.execute((ROOT / "sql" / "13_apply_gates.sql").read_text(encoding="utf-8"))
        cur.execute("select refresh_primary_contacts(%s)", (lx,))
        cur.execute((ROOT / "sql" / "14_auto_shortlist.sql").read_text(encoding="utf-8"))
        cur.execute("select name, status, fit_score::float, metadata->>'audience', metadata->>'hq_city', status_reason,"
                    " score_breakdown->'points_possible_assessed', metadata from entities where segment_id = %s"
                    " order by name", (lx_id,))
        rows = {r[0]: r[1:] for r in cur.fetchall()}
        check("the cafe: its own words 30, Instagram 10, one premises 12.5, fit 15, an inbox 5, +4 the UK: 76.5,"
              " shortlisted by itself", rows[bean_n][:4], ("shortlisted", 76.5, "Cafe, salon or gym", "London"))
        check("  and says why: over the line, someone to write to, its content assessed", rows[bean_n][4],
              "auto-shortlisted: score 76.5 is above 70, with someone to write to; assessed: content_activity;"
              " its site read")
        check("the brand: over the line on the 80 points known (72.75), but nobody to write to and its site unread:"
              " left in To review", (rows[acme_n][:2], rows[acme_n][5]), (("ready_for_review", 72.75), 80))
        check("a published inbox, over the line, its accounts listed on Wikidata (content assessed), but its own"
              " site never read: not shortlisted (require_site_read)",
              (rows[toys_n][0], rows[toys_n][1] > 70, rows[toys_n][6]["scoring_inputs"]["content_activity"],
               rows[toys_n][6]["lcx_judgement"]["site_checked"]), ("ready_for_review", True, 1.0, False))
        check("a mid-size company at 99 with only an info@ inbox: held for a named person",
              rows[corp_n][:2], ("ready_for_review", 99.0))
        judged_vals = [(n, k, v) for n in (acme_n, bean_n, corp_n, toys_n) for k, v in rows[n][6]["scoring_inputs"].items()
                       if k in {c["key"] for c in cfg["rubric"] + cfg["score_modifiers"]} and v not in (None, 0, 0.5, 1)]
        check("every scored input on them is 0, 0.5, 1 or unknown, and no retired input is left",
              (judged_vals, [(n, k) for n in rows if n in (acme_n, bean_n, corp_n, toys_n)
                             for k in cfg["judge"]["retired_inputs"] if k in rows[n][6]["scoring_inputs"]]), ([], []))
        check("  the judge's evidence is on the lead, for a reviewer to overrule",
              (rows[bean_n][6]["lcx_judgement"]["buyer_confirmed"].startswith("own words: "),
               rows[bean_n][6]["lcx_judgement"]["content_activity"], rows[corp_n][6]["lcx_judgement"]["site_read"]),
              (True, "instagram", True))
        outreach.SEGMENT = lx
        outreach.cmd_draft(argparse.Namespace(limit=20, template=None, dry_run=False))
        cur.execute("select o.id, o.subject, o.body, o.attachments from outreach o join entities e on e.id = o.entity_id"
                    " where e.segment_id = %s", (lx_id,))
        drafts = cur.fetchall()
        check("one draft, for the cafe", [d[1] for d in drafts], ["18 things LCX can do for ZZ Bean There %s" % tag])
        oid, subject, body, atts = drafts[0]
        check("  greeting the inbox, offering the deck", body.splitlines()[:3], ["Hi there,", "", "I'm writing from LCX. We work in"
              " three areas, and at least one of them should be useful to ZZ Bean There %s. Our services deck is attached." % tag])
        check("  the deck is recorded on it, fingerprinted", [(a["name"], a["path"], a["bytes"] > 100000, len(a["sha256"]))
                                                             for a in atts],
              [("LCX Services - pitch deck.pdf", "docs/decks/LCX Services - pitch deck.pdf", True, 64)])
        check("  and it can be approved", pol.check_drafts(cur, [str(oid)], lx)[1], [])
        cur.execute("update outreach set attachments = %s where id = %s",
                    (json.dumps([dict(atts[0], path="docs/decks/gone.pdf", name="gone.pdf")]), oid))
        check("a draft whose deck is gone cannot be approved", pol.check_drafts(cur, [str(oid)], lx)[1],
              [{"id": str(oid), "reason": "the attached gone.pdf is missing"}])
        cur.execute("update outreach set attachments = %s where id = %s",
                    (json.dumps([dict(atts[0], sha256="0" * 64)]), oid))
        pol.check_drafts(cur, [str(oid)], lx)
        cur.execute("select attachments->0->>'sha256' from outreach where id = %s", (oid,))
        check("  a draft made before the deck was rebuilt takes the current one when approved", cur.fetchone()[0], atts[0]["sha256"])

        print("\n-- the page")
        seg = call("GET", "/api/segment", cookies=as_(lx)).json()
        check("LCX Services: drafts, no Write email box, opens on the board",
              (seg["outreach_policy"]["drafts"], seg["outreach_policy"]["compose"], seg["outreach_policy"]["compose_start"],
               seg["ui"]["default_route"], seg["ui"]["hide_routes"]), (True, False, None, "board", []))
        listed = call("GET", "/api/outreach?folder=drafts", cookies=as_(lx)).json()["rows"]
        check("  the draft is listed with its deck", [(r["company"], [a["name"] for a in r.get("attachments") or []]) for r in listed],
              [("ZZ Bean There %s" % tag, ["LCX Services - pitch deck.pdf"])])
        r = call("GET", "/api/outreach/attachment", cookies=as_(lx), params={"path": atts[0]["path"]})
        check("  the deck opens from the app, as itself", (r.status_code, r.headers.get("content-type"), len(r.content)),
              (200, "application/pdf", atts[0]["bytes"]))
        check("  inline, not a download", r.headers.get("content-disposition", "").startswith("inline"), True)
        for bad in ("../.env", "docs/decks/../../.env", "app/main.py", "docs/LCX Services.pdf"):
            check("  nothing else is served: %s" % bad, call("GET", "/api/outreach/attachment", cookies=as_(lx),
                                                            params={"path": bad}).status_code, 404)
        check("  and nobody signed out", call("GET", "/api/outreach/attachment", params={"path": atts[0]["path"]}).status_code, 401)
        ex = explain.explain_lead(lx, cfg, {"id": "x", "name": "ZZ Empty", "domain": None, "status": "ready_for_review",
                                            "metadata": {}, "fit_score": None, "score_breakdown": None}, [], None)
        check("a lead with nobody at it points to Apollo search, the way to add one by hand", ex["analysis"]["next_step"],
              "Find a way in: save a person at it from Apollo search.")

        # ------------------------------------------------------------ a named person found at the corporate
        print("\n-- a mid-size company is shortlisted once a named person is found (the owner, 2026-10-07)")
        cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) select id, 'Raj Patel',"
                    " 'accounting@' || domain, 'unverified', 'site_scrape' from entities where segment_id = %s and name = %s",
                    (lx_id, corp_n))
        cur.execute((ROOT / "sql" / "14_auto_shortlist.sql").read_text(encoding="utf-8"))
        cur.execute("select status from entities where segment_id = %s and name = %s", (lx_id, corp_n))
        check("  a name on accounting@ is not enough: the drafter would still write to info@, so it waits",
              cur.fetchone()[0], "ready_for_review")
        cur.execute("insert into contacts (entity_id, full_name, role_title, email, email_status, source, verifier)"
                    " select id, 'Nina Shah', 'Head of Learning and Development', 'nina@' || domain, 'valid', 'apollo',"
                    " 'apollo' from entities where segment_id = %s and name = %s", (lx_id, corp_n))
        cur.execute("select refresh_primary_contacts(%s)", (lx,))
        cur.execute((ROOT / "sql" / "14_auto_shortlist.sql").read_text(encoding="utf-8"))
        cur.execute("select status, status_reason from entities where segment_id = %s and name = %s", (lx_id, corp_n))
        check("  as enrich_apollo writes one: shortlisted on the next chain run, and says why", cur.fetchone(),
              ("shortlisted", "auto-shortlisted: score 99.0 is above 70, with a named person to write to;"
                              " assessed: content_activity; its site read"))
        outreach.cmd_draft(argparse.Namespace(limit=20, template=None, dry_run=False))
        cur.execute("select c.email, o.body from outreach o join entities e on e.id = o.entity_id join contacts c"
                    " on c.id = o.contact_id where e.segment_id = %s and e.name = %s", (lx_id, corp_n))
        drafted = [(r[0], r[1].splitlines()[0]) for r in cur.fetchall()]
        check("  and drafted to that person, not the info@ inbox", drafted, [("nina@zz-northwind-%s.example" % tag, "Hi Nina,")])
        cur.execute("select status from entities where segment_id = %s and name = any(%s) order by name",
                    (lx_id, [acme_n, toys_n]))
        check("  the brand with nobody and the unread one still wait in To review", [r[0] for r in cur.fetchall()],
              ["ready_for_review", "ready_for_review"])

        # ------------------------------------------------------------ a project with its own starting email
        print("\n-- a project that starts the Write email box from its own email")
        pc = call("GET", "/api/segment", cookies=as_(cp)).json()["outreach_policy"]
        check("its email is handed to the page", (pc["compose"], pc["compose_start"]), (True, start))
        check("Universal is handed none", call("GET", "/api/segment", cookies=as_(un)).json()["outreach_policy"]["compose_start"], None)
        check("  nor a project without Write email", call("GET", "/api/segment", cookies=as_("us-production-houses")).json()
              ["outreach_policy"].get("compose_start"), None)
        check("  and the starting email passes the checks", outreach_compose.check_text(start["subject"], start["body"]), None)

        # ------------------------------------------------------------ someone who answered us elsewhere
        print("\n-- an address that answered us in another project gets nothing new")

        def answered(local, triage, bounce=False):
            """An email from the Universal project to local@..., their reply (triage) or a bounce, and a
            draft for the same address in LCX Services."""
            t = uuid.uuid4().hex[:6]
            addr = "%s@zz-%s.example" % (local, t)
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'apollo',"
                        " 'contacted') returning id", (un_id, "ZZ Earlier %s" % t, "zz-%s.example" % t))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status, source, verifier) values"
                        " (%s, 'Ravi Kumar', %s, %s, 'apollo', %s) returning id",
                        (eid, addr, "invalid" if bounce else "valid", "bounce" if bounce else None))
            cid = cur.fetchone()[0]
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, sent_at)"
                        " values (%s, %s, 'compose', 'Hello', 'Body', 'sent', now())", (eid, cid))
            if not bounce:
                cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, triage)"
                            " values (%s, %s, 'inbound', 'Re: Hello', 'No thanks', %s, %s)",
                            (eid, cid, "triaged" if triage else "received", triage))
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'lcx_osm',"
                        " 'shortlisted') returning id", (lx_id, "ZZ Again %s" % t, "zz-again-%s.example" % t))
            lid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                        " (%s, 'Ravi Kumar', %s, 'valid', 'osm') returning id", (lid, addr.upper()))
            lcid = cur.fetchone()[0]
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body) values"
                        " (%s, %s, 'lcx_services_deck_v1', 'S', 'B') returning id", (lid, lcid))
            return str(cur.fetchone()[0])

        no_thanks, unread, auto, bounced = (answered("ravi", "negative"), answered("mohan", None),
                                            answered("ooo", "neutral"), answered("gone", None, bounce=True))
        ok_ids, skipped = pol.check_drafts(cur, [no_thanks, unread, auto, bounced], lx)
        why = {s["id"]: s["reason"] for s in skipped}
        check("they said no thanks to Universal's email: not approvable here",
              why.get(no_thanks), "this address has replied to an earlier email from us: answer them in that thread")
        check("  a reply nobody has read yet counts too", why.get(unread),
              "this address has replied to an earlier email from us: answer them in that thread")
        check("  an auto-reply is not an answer: that inbox is held only because it already had its first email",
              why.get(auto), "this address already has a first email from us, under another lead")
        check("  an address that bounced: not approvable", why.get(bounced), "this address bounced an earlier email from us")

        # ------------------------------------------------------------ the Apollo harvest, stubbed
        print("\n-- the Apollo harvest, Apollo stubbed: signals first, cursors, the ledger, nothing bought twice")
        import apollo
        keep_ap = (apollo.search_people, apollo.search_companies)
        bought, spends = [], []
        try:
            def free(filters, page=1, per_page=1):
                empty = "Hong Kong" in filters.get("organization_locations", []) or \
                    "zz-empty-tag" in (filters.get("q_organization_keyword_tags") or [])
                return {"total": 0 if empty else 500, "people": []}

            def paid(filters, page=1, per_page=100):
                bought.append((filters.get("organization_locations")[0], page, filters.get("q_organization_job_titles") is not None))
                n = len(bought)
                return {"total_pages": 2, "companies": [
                    {"id": "%024x" % (n * 1000 + i), "name": "ZZ Co %d-%d %s" % (n, i, tag),
                     "website_url": "https://zz-co-%d-%d-%s.example" % (n, i, tag)} for i in range(3)]}
            apollo.search_people, apollo.search_companies = free, paid
            small = json.loads(json.dumps(cfg))
            small["apollo_discovery"]["countries"] = [{"name": "United States", "iso": "US"}, {"name": "Hong Kong", "iso": "HK"}]
            small["apollo_discovery"]["searches"] = (
                [dict(s) for s in cfg["apollo_discovery"]["searches"] if s.get("signal")][:6] +
                [dict(s) for s in cfg["apollo_discovery"]["searches"] if not s.get("signal")][:3])
            small["apollo_discovery"]["signal_pages_per_run"] = 2
            got, why_not, n = disc.run_apollo(dbconn.Db, lx_id, small, 5, set(), set(),
                                              spend=lambda cur_, c, ref: spends.append((c, ref)))
            check("5 pages bought: 2 from signal searches, then the plain ones", (n, [b[2] for b in bought]),
                  (5, [True, True, False, False, False]))
            check("  every page is in the ledger as it is bought", len(spends), 5)
            cur.execute("select next_page from apollo_cursors where segment_id = %s and exhausted_at is null"
                        " order by search_key limit 1", (lx_id,))
            check("  a bought slice's next run asks for page 2", cur.fetchone()[0], 2)
            check("  the companies found, with their websites", len(got), 15)
            bought.clear()
            got2, _, n2 = disc.run_apollo(dbconn.Db, lx_id, small, 5, set(), set(r["domain"] for r in got))
            check("the next run: the signal slices not yet run, then page 2 of the plain ones",
                  [(b[1]) for b in bought], [1, 1, 2, 2, 2])
            check("  a slice that would come back empty (the free check) is never bought",
                  [b for b in bought if b[0] == "Hong Kong"], [])
            cur.execute("select search_key from apollo_cursors where segment_id = %s and exhausted_at is not null"
                        " and search_key like %s order by 1", (lx_id, "%|HK"))
            check("  and is set aside", [r[0] for r in cur.fetchall()],
                  sorted(["brands|HK", "developers|HK", "retailers|HK", small["apollo_discovery"]["searches"][0]["key"] + "|HK",
                          small["apollo_discovery"]["searches"][1]["key"] + "|HK"]))
            check("  a company found before is not staged again", len(got2), 0)
            cur.execute("select search_key from apollo_cursors where segment_id = %s and exhausted_at is not null"
                        " and search_key like %s order by 1", (lx_id, "%|US"))
            check("  a slice's last page used up: it waits until its cursor is reset",
                  [r[0] for r in cur.fetchall()], ["brands|US", "developers|US", "retailers|US"])
            bought.clear()

            def broken(cur_, c, ref):
                raise RuntimeError("ledger down")
            got3, _, n3 = disc.run_apollo(dbconn.Db, lx_id, small, 5, set(), set(), spend=broken)
            cur.execute("select count(*) from apollo_cursors where segment_id = %s and search_key = %s and runs = 1",
                        (lx_id, "retailers_hiring_store_staff|US"))
            check("a page whose ledger row cannot be written: buying stops at once, nothing staged from it",
                  (len(bought), n3, len(got3)), (1, 1, 0))
            check("  and its cursor did not move either (one transaction), so the cap was not overrun unseen",
                  cur.fetchone()[0], 0)
        finally:
            apollo.search_people, apollo.search_companies = keep_ap

        # ------------------------------------------------------------ one first email per company, across projects
        print("\n-- one first email per company and per inbox, whichever project wrote it")
        t2 = uuid.uuid4().hex[:6]
        cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'apollo', 'contacted')"
                    " returning id", (un_id, "ZZ Pitched %s" % t2, "zz-pitched-%s.example" % t2))
        pe = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, email, email_status, source) values (%s, %s, 'valid', 'apollo')"
                    " returning id", (pe, "ceo@zz-pitched-%s.example" % t2))
        pc = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, sent_at)"
                    " values (%s, %s, 't', 'S', 'B', 'sent', now())", (pe, pc))

        def draft_for(domain, email):
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'lcx_apollo',"
                        " 'shortlisted') returning id", (lx_id, "ZZ Again %s" % uuid.uuid4().hex[:6], domain))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, email, email_status, source) values (%s, %s, 'valid', 'apollo')"
                        " returning id", (eid, email))
            cid = cur.fetchone()[0]
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body) values (%s, %s, 't', 'S', 'B')"
                        " returning id", (eid, cid))
            return str(cur.fetchone()[0])
        same_co = draft_for("zz-pitched-%s.example" % t2, "sales@zz-pitched-%s.example" % t2)
        same_inbox = draft_for("zz-other-%s.example" % t2, "ceo@zz-pitched-%s.example" % t2)
        fresh = draft_for("zz-fresh-%s.example" % t2, "hello@zz-fresh-%s.example" % t2)
        ok_ids, skipped = pol.check_drafts(cur, [same_co, same_inbox, fresh], lx)
        why = {s["id"]: s["reason"] for s in skipped}
        check("a company Universal already wrote to gets no first email from LCX Services",
              why.get(same_co), "this company already has a first email from us in another project")
        check("  nor does that person's inbox, under any lead", why.get(same_inbox),
              "this address already has a first email from us, under another lead")
        check("  a company nobody has written to can be approved", ok_ids, [fresh])
        cur.execute("update outreach set stopped_reason = 'bounced: the address rejected the email' where entity_id = %s",
                    (pe,))
        ok_ids, skipped = pol.check_drafts(cur, [same_co], lx)
        check("  a first email that bounced reached nobody there: the company is not used up",
              (ok_ids, [s["reason"] for s in skipped]), ([same_co], []))

        # ------------------------------------------------------------ the search page's spending
        print("\n-- the Apollo search page writes what it spends to the ledger, and keeps to the project's budget")
        import universal as uni_page
        keep_sc, keep_st, keep_rv = apollo.search_companies, apollo.status, apollo.reveal_people
        asked = []
        balance = {"left": 2000}
        try:
            def page_co(filters, page=1, per_page=100):
                asked.append("companies")
                return {"total": 1, "page": 1, "total_pages": 1, "per_page": per_page,
                        "companies": [{"id": "e" * 24, "name": "ZZ Page Co", "website_url": "https://zz-page.example"}]}
            apollo.search_companies = page_co
            apollo.status = lambda: {"key_set": True, "connected": True, "problems": [],
                                     "credits": {"lead_credits_left": balance["left"]}}
            apollo.reveal_people = lambda ids: asked.append("reveal") or {
                "people": [], "missing": list(ids), "credits": float(len(ids)), "error": None, "unrevealed": []}

            def fresh():
                uni_page._STATUS.update(at=0.0, value=None)
            fresh()
            r = call("POST", "/api/universal/search?project=" + lx, cookies=as_(lx),
                     json={"kind": "companies", "filters": {"q_organization_keyword_tags": ["retail"]}})
            cur.execute("select kind, credits::float, ref from apollo_spend where segment_id = %s and ref like 'search page%%'",
                        (lx_id,))
            check("a page of companies searched by hand: 1 credit, counted in the project's week",
                  (r.status_code, cur.fetchall()), (200, [("company_page", 1.0, "search page, by hand")]))
            r = call("POST", "/api/universal/save?project=" + lx, cookies=as_(lx),
                     json={"kind": "people", "ids": ["%024x" % (0xd000 + i) for i in range(3)]})
            cur.execute("select coalesce(sum(credits), 0)::float from apollo_spend where segment_id = %s"
                        " and kind = 'reveal' and ref like 'search page%%'", (lx_id,))
            check("  people revealed by hand: on the ledger before they are saved", (r.status_code, cur.fetchone()[0]),
                  (200, 3.0))
            cur.execute("insert into apollo_spend (segment_id, kind, credits, ref) values (%s, 'reveal', 200, 'zz the week')",
                        (lx_id,))
            del asked[:]
            fresh()
            r = call("POST", "/api/universal/search?project=" + lx, cookies=as_(lx),
                     json={"kind": "companies", "filters": {"q_organization_keyword_tags": ["retail"]}})
            check("  the week's budget used up: the page says so and Apollo is not asked",
                  (r.status_code, "budget" in r.json().get("detail", ""), asked), (409, True, []))
            r = call("POST", "/api/universal/save?project=" + lx, cookies=as_(lx),
                     json={"kind": "people", "ids": ["%024x" % 0xd100]})
            check("  nor is anyone revealed", (r.status_code, asked), (409, []))
            cur.execute("delete from apollo_spend where segment_id = %s and ref = 'zz the week'", (lx_id,))
            balance["left"] = 700
            fresh()
            r = call("POST", "/api/universal/search?project=" + lx, cookies=as_(lx),
                     json={"kind": "companies", "filters": {"q_organization_keyword_tags": ["retail"]}})
            check("  700 left in the month: the reserve is the other projects', so nothing", (r.status_code, asked), (409, []))
            balance["left"] = None
            fresh()
            r = call("POST", "/api/universal/search?project=" + lx, cookies=as_(lx),
                     json={"kind": "companies", "filters": {"q_organization_keyword_tags": ["retail"]}})
            check("  Apollo cannot say what is left: nothing, rather than risk the reserve", (r.status_code, asked), (409, []))
            r = call("POST", "/api/universal/search?project=" + un, cookies=as_(un),
                     json={"kind": "companies", "filters": {"q_organization_keyword_tags": ["retail"]}})
            check("  Universal states no budget: searched as before", (r.status_code, asked), (200, ["companies"]))
        finally:
            apollo.search_companies, apollo.status, apollo.reveal_people = keep_sc, keep_st, keep_rv
            uni_page._STATUS.update(at=0.0, value=None)

        # ------------------------------------------------------------ the search page's project
        print("\n-- the Apollo search page works on the project it shows")
        sname = "ZZ salons " + tag
        body = {"name": sname, "kind": "companies", "filters": {"q_organization_keyword_tags": ["salon"]}}
        r = call("POST", "/api/universal/searches?project=" + lx, cookies=as_(lx), json=body)
        check("save a search in LCX Services: 200", r.status_code, 200)
        cur.execute("select segment_id from saved_searches where lower(name) = lower(%s)", (sname,))
        check("  it is kept in LCX Services", [x[0] for x in cur.fetchall()], [lx_id])

        def listed_in(slug, cookie):
            return [s["name"] for s in call("GET", "/api/universal/searches?project=" + slug,
                                            cookies=as_(cookie)).json().get("searches", [])]
        check("  listed there", sname in listed_in(lx, lx), True)
        check("  and not in Universal's list", sname in listed_in(un, un), False)

        def saved(seg_id, name):
            cur.execute("select count(*) from entities where segment_id = %s and name = %s", (seg_id, name))
            return cur.fetchone()[0]

        co = "ZZ Saved Co %s" % tag
        r = call("POST", "/api/universal/save?project=" + lx, cookies=as_(lx), json={"kind": "companies", "companies": [
            {"id": uuid.uuid4().hex[:24], "name": co, "website_url": "https://zz-saved-%s.example" % tag}]})
        check("save a company in LCX Services: 200, free", (r.status_code, r.json().get("credits")), (200, 0))
        check("  it is an LCX Services lead, and not a Universal one", (saved(lx_id, co), saved(un_id, co)), (1, 0))
        co2 = "ZZ Other Tab Co %s" % tag
        r = call("POST", "/api/universal/save?project=" + lx, cookies=as_(un), json={"kind": "companies", "companies": [
            {"id": uuid.uuid4().hex[:24], "name": co2, "website_url": "https://zz-tab-%s.example" % tag}]})
        check("another tab switched to Universal: this tab's save still lands where it shows",
              (r.status_code, saved(lx_id, co2), saved(un_id, co2)), (200, 1, 0))
        co3 = "ZZ Refused Co %s" % tag
        r = call("POST", "/api/universal/save?project=" + no, cookies=as_(no), json={"kind": "companies", "companies": [
            {"id": uuid.uuid4().hex[:24], "name": co3, "website_url": "https://zz-no-%s.example" % tag}]})
        check("a project without the search page: 404, nothing saved", (r.status_code, saved(no_id, co3)), (404, 0))
        check("  nor its status asked", call("GET", "/api/universal/status?project=" + no, cookies=as_(no)).status_code, 404)
        r = call("POST", "/api/universal/save?project=zz-nope-" + tag, cookies=as_(lx), json={"kind": "companies",
                 "companies": [{"id": uuid.uuid4().hex[:24], "name": "ZZ Nowhere"}]})
        check("  nor a project that does not exist", r.status_code, 404)
        co4 = "ZZ Old Page Co %s" % tag
        r = call("POST", "/api/universal/save", cookies=as_(lx), json={"kind": "companies", "companies": [
            {"id": uuid.uuid4().hex[:24], "name": co4, "website_url": "https://zz-old-%s.example" % tag}]})
        check("a page that names no project saves to the cookie's project when it has the page",
              (r.status_code, saved(lx_id, co4), saved(un_id, co4)), (200, 1, 0))
        mark = "ZZ universal fallback " + tag
        cur.execute("insert into saved_searches (segment_id, name, kind, filters, created_by) select id, %s, 'people',"
                    " '{\"person_titles\": [\"producer\"]}'::jsonb, 'zz' from segments where slug = 'universal'", (mark,))
        r = call("GET", "/api/universal/searches", cookies=as_(no))
        check("  and to Universal when the cookie's project has none, as before",
              (r.status_code, mark in [s["name"] for s in r.json().get("searches", [])]), (200, True))
    finally:
        dbconn.Db, outreach.SEGMENT, lift.SEGMENT = real_db, real_seg, real_lift_seg
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rolled back; nothing sent)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
