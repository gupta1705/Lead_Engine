#!/usr/bin/env python3
"""test_lcx_services.py -- the LCX Services project, end to end (2026-10-06).

    python tools/test_lcx_services.py

The owner: one outreach offering every service on docs/LCX Services.pdf, then "it should generate the
leads on its own ... like we source leads for us production houses", "email should be a pitch deck of
services" (a PDF deck attached), everywhere cold business email is allowed, sent once approved.

Checked:
  * the config: every one of the 18 services has buyers to find; a lead nobody can be written to can
    never be auto-shortlisted; the countries; the weekly refresh's steps exist; Apollo is off; the one
    template attaches the deck, which is built, five 16:9 pages, small; the generated SQL is the JSON's
  * the harvest, offline: what a Wikidata or OpenStreetMap record becomes and what is left out (a
    consent-law country, a chain's branch, a platform page, no name), the order, the city rotation
  * against the database, in ONE transaction rolled back at the end: staging -> the promote chain's
    own SQL -> the published address lifted into a contact -> scored -> auto-shortlisted -> drafted
    with the deck -> approval refuses a missing deck -> the page lists the draft with its deck and
    opens it, and nothing else
  * a project that starts its Write email box from its own email (outreach.compose_start)
  * the Apollo search page works on the project it shows; a project without it is refused
  * an address that answered us in another project gets nothing new
Nothing is sent and no network is used. Exit code 1 on any failure.
"""
import argparse
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
CHAIN = ["sql/05a_self_exclusion.sql", "sql/05_promote_minimal.sql", "sql/05c_merge_name_duplicates.sql",
         "sql/04b_zero_unverified.sql"]


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
    rub = {r["key"]: r["points"] for r in cfg["rubric"]}
    bonus = sum(m.get("max_bonus", 0) for m in cfg["score_modifiers"])
    nobody = sum(p for k, p in rub.items() if k != "reachable_decision_maker") / sum(rub.values()) * 100 + bonus
    check("a lead nobody can be written to can never be auto-shortlisted", nobody < cfg["auto_shortlist"]["min_score"], True)
    inbox = (rub["reachable_decision_maker"] * 0.5 + rub["audience_fit"] + rub["established"]) / sum(rub.values()) * 100
    check("  a published business address at a company of unknown size can", inbox > cfg["auto_shortlist"]["min_score"], True)
    check("everywhere except the consent-law countries", (cfg["geography"]["allowed_countries"],
          sorted(cfg["geography"]["disallowed_countries"])), ([], ["AT", "CA", "DE", "IT"]))
    steps = cfg["pipelines"]["weekly_refresh"]
    check("the weekly refresh's steps all exist, and run here", [s for s in steps if s not in ops.JOBS or
          ops.JOBS[s].get("segments") not in (None, ["lcx-services"])], [])
    check("  on Fridays, like a harvest", (cfg["schedule"][0]["pipeline"], cfg["schedule"][0]["dow"]), ("weekly_refresh", 4))
    check("Apollo is not used for it (the owner: 'forget apollo for a sec')", cfg["enrichment"]["enabled"], False)
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
    check("  scored for what it is", row["raw"]["scoring_inputs"], {"audience_fit": 1.0, "has_reachable_presence": True,
          "established": 1.0, "right_size": 1.0, "oversized_signal": False, "country_signal": "allowed", "english_market": 1.0})
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
    check("  a complete listing counts as established, a local business is the right size",
          (row["raw"]["scoring_inputs"]["established"], row["raw"]["scoring_inputs"]["right_size"]), (1.0, 1.0))
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
    real = (disc.overpass, disc.wikidata_ids, disc.wikidata_details, disc.time.sleep)
    disc.time.sleep = lambda s: None
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

        def fake_ids(match):                 # each audience its own companies, half of them in an English market
            base = int(match["values"][0][1:]) % 100000 * 100
            return {"Q%d" % (base + i): (100 + i, ["US"] if i % 2 else ["JP"]) for i in range(1, 30)}

        def fake_details(qids):
            return {q: {"qid": q, "label": "Co %s" % q, "webs": ["https://co-%s.example" % q.lower()], "isos": ["US"],
                        "employees": 300, "emails": []} for q in qids}
        disc.wikidata_ids, disc.wikidata_details = fake_ids, fake_details
        saved = []
        rows, why = disc.run_wikidata(cfg, 90, 80, set(), set(), emit=saved.append)
        n_aud = len(disc.audiences(cfg, "wikidata"))
        check("Wikidata: every company saved as it is found, an equal share per audience",
              (len(saved) == len(rows), len(rows), 90 // n_aud), (True, n_aud * (90 // n_aud), 10))
        base = int(disc.audiences(cfg, "wikidata")[0]["wikidata"][0]["values"][0][1:]) % 100000 * 100
        check("  the English-speaking market taken first within the same size", [r["raw"]["wikidata"]["qid"] for r in rows[:3]],
              ["Q%d" % (base + i) for i in (1, 3, 5)])
    finally:
        disc.overpass, disc.wikidata_ids, disc.wikidata_details, disc.time.sleep = real
    meta, email, src = lift.lift({"discovery_raw": {"lcx_osm": row["raw"]}, "why_fit": "a person's own words"})
    check("lifting: the audience, services and place go on the lead, a person's words stay",
          (meta["kind"], meta["audience"], meta["hq_city"], meta["hq_country"], meta["why_fit"], email, src),
          ("local_business", "Cafe, salon or gym", "London", "GB", "a person's own words", "hello@beanthere.example", "lcx_osm"))
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
        city = {"name": "London", "country": "GB", "lat": 51.5, "lon": -0.12}
        staged = [disc.wikidata_row({"qid": "Q9%s1" % tag[:4].encode().hex()[:6], "label": "ZZ Acme Foods %s" % tag,
                                     "webs": ["https://zz-acme-%s.example" % tag], "isos": ["IN"], "employees": 450,
                                     "emails": []}, brands, cfg)[0],
                  disc.osm_row({"type": "node", "id": int(tag, 16), "tags": {
                      "amenity": "cafe", "name": "ZZ Bean There %s" % tag, "website": "https://zz-bean-%s.example" % tag,
                      "email": "hello@zz-bean-%s.example" % tag, "opening_hours": "Mo-Su 08:00-18:00"}}, city, cafes, cfg)[0]]
        for r in staged:
            cur.execute("insert into staging_candidates (segment_id, name, domain, source, source_url, raw) values"
                        " (%s, %s, %s, %s, %s, %s)", (lx_id, r["name"], r["domain"],
                                                      "lcx_wikidata" if "wikidata" in r["raw"] else "lcx_osm",
                                                      r["source_url"], json.dumps(r["raw"])))
        cur.execute("select set_config('tvf.segment', %s, true)", (lx,))
        for f in CHAIN:
            cur.execute((ROOT / f).read_text(encoding="utf-8"))
        cur.execute("select name, status, metadata from entities where segment_id = %s order by name", (lx_id,))
        got = {r[0]: r for r in cur.fetchall()}
        acme, bean = got.get("ZZ Acme Foods %s" % tag), got.get("ZZ Bean There %s" % tag)
        check("both are leads of LCX Services after the promote chain", (bool(acme), bool(bean)), (True, True))
        lift.SEGMENT = lx
        sys.argv = ["enrich_lcx_services.py"]
        lift.main()
        cur.execute("select e.name, c.email, c.source, c.email_status from contacts c join entities e on e.id = c.entity_id"
                    " where e.segment_id = %s", (lx_id,))
        check("the cafe's published address became its contact", [tuple(r) for r in cur.fetchall()],
              [("ZZ Bean There %s" % tag, "hello@zz-bean-%s.example" % tag, "osm", "unverified")])
        cur.execute("select count(*) from score_segment(%s)", (lx,))
        cur.fetchone()
        cur.execute((ROOT / "sql" / "13_apply_gates.sql").read_text(encoding="utf-8"))
        cur.execute("select refresh_primary_contacts(%s)", (lx,))
        cur.execute((ROOT / "sql" / "14_auto_shortlist.sql").read_text(encoding="utf-8"))
        cur.execute("select name, status, round(fit_score)::int, metadata->>'audience', metadata->>'hq_city' from entities"
                    " where segment_id = %s order by name", (lx_id,))
        rows = {r[0]: r[1:] for r in cur.fetchall()}
        check("the cafe, with an address: 25 + 20 + 15 + 15, +4 English, and shortlisted by itself", rows["ZZ Bean There %s" % tag],
              ("shortlisted", 79, "Cafe, salon or gym", "London"))
        check("the brand, nobody to write to yet: 54, under the line, left in To review", rows["ZZ Acme Foods %s" % tag][:2],
              ("ready_for_review", 54))
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
        check("  an auto-reply does not", (ok_ids, auto in why), ([auto], False))
        check("  an address that bounced: not approvable", why.get(bounced), "this address bounced an earlier email from us")

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
