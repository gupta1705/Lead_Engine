#!/usr/bin/env python3
"""test_enrich_apollo.py -- the Apollo enrichment pass, as a regression table.

    python tools/test_enrich_apollo.py

Part one needs no key and no network: who gets picked out of a search, which
searches are made and in what order, and when a reveal is refused as somebody
who has moved on. Part two runs the lead selection and the write against the
real database inside one transaction that is rolled back: a throwaway segment,
leads in every state, then ROLLBACK. LCX Services' scoring-v4 guards (the owner,
2026-10-07: reveals only for leads over 60 whose own site was read and that are
not the wrong buyer; banks and mid-size companies need a named person) are
checked the same way, and that US Production Houses has none of them. Not one
credit is spent by this file. Exit code 1 on any failure.
"""
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import apollo  # noqa: E402
import enrich_apollo as ea  # noqa: E402

RESULTS = []
ROLES = ["Founder", "Head of Development", "Executive Producer"]


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-62s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                               + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


def hit(title, email=True, i=1):
    return {"id": "%024x" % (0xc000 + i), "first_name": "P%d" % i, "last_name_obfuscated": "Q***n",
            "title": title, "has_email": email, "company": "Firm"}


def offline():
    print("-- who is worth a credit")
    check("the config's order is the preference order",
          [ea.role_rank(t, ROLES)[0] for t in ("Founder and CEO", "Head of Development", "Executive Producer", "Runner")],
          [3, 2, 1, 0])
    check("an address beats a better title without one",
          ea.pick([hit("Founder", email=False, i=1), hit("Executive Producer", i=2)], ROLES)[0]["id"], hit("", i=2)["id"])
    check("among addresses, the target role wins",
          ea.pick([hit("Executive Producer", i=3), hit("Founder", i=4)], ROLES)[1], "a Founder")
    check("no target role: any senior title, and the reason says so",
          ea.pick([hit("Office Assistant", i=5), hit("Managing Director", i=6)], ROLES)[1], "a senior title")
    tvf = ["Founder", "Co-Founder", "Head of Development", "Development Executive", "Executive Producer",
           "Head of Acquisitions", "Head of Distribution"]
    check("no exact role: the title sharing most words with the roles wins (Severin Films, 2026-09-21)",
          ea.pick([hit("Head of QC, Licensor and Elements Research", i=9), hit("Acquisitions/Producer", i=10)],
                  tvf)[0]["title"], "Acquisitions/Producer")
    check("nobody at all", ea.pick([], ROLES), (None, None))

    print("\n-- the searches, narrowest first (all free)")
    calls = []

    def stub(filters, page, per_page, answer=None):
        calls.append(filters)
        return {"total": len(answer or []), "people": answer or []}
    apollo.search_people = lambda f, p, n: stub(f, p, n, [] if len(calls) < 2 else [hit("Head of Development")])
    people, total = ea.search("firm.com", ROLES, True)
    check("verified target roles, then the roles, then whoever is there",
          [sorted(c.keys()) for c in calls],
          [["contact_email_status", "person_titles", "q_organization_domains_list"],
           ["person_titles", "q_organization_domains_list"],
           ["contact_email_status", "q_organization_domains_list"]][:len(calls)])
    check("the pass that answered is the one that is used", (len(people), total), (1, 1))

    calls[:] = []
    apollo.search_people = lambda f, p, n: stub(f, p, n, [hit("Marketing Intern"), hit("Office Coordinator")]
                                                if len(calls) >= 2 else [])
    people, _ = ea.search("firm.com", ROLES, True)
    check("the widest pass is anyone at the company, so juniors are not paid for", people, [])

    calls[:] = []
    apollo.search_people = lambda f, p, n: stub(f, p, n, [hit("Head of Development")])
    ea.search("firm.com", [], False)
    check("no target roles configured: one search, no title filter and no status filter",
          [sorted(c.keys()) for c in calls], [["q_organization_domains_list"]])

    calls[:] = []
    answers = [[], [hit("Executive Producer", email=False, i=7)], [hit("Managing Director", i=8)]]
    apollo.search_people = lambda f, p, n: stub(f, p, n, answers[len(calls)])
    people, _ = ea.search("imaginaryforces.com", ROLES, True)
    check("the right role with no address does not end the search: a senior person with one is found",
          [p["id"] for p in people], [hit("", i=8)["id"]])
    calls[:] = []
    answers = [[], [hit("Executive Producer", email=False, i=7)], []]
    apollo.search_people = lambda f, p, n: stub(f, p, n, answers[len(calls)])
    people, _ = ea.search("imaginaryforces.com", ROLES, True)
    check("nobody anywhere has an address: the role match is still reported, so the lead says why",
          [p["id"] for p in people], [hit("", i=7)["id"]])

    print("\n-- a lead with no website, looked up by its name (1 credit)")
    check("a headline's '<place>-based' and the legal words go; the industry word stays",
          [ea.name_key(n) for n in ("Atlanta-Based Freeli Films, LLC", "Sentient Entertainment", "The Asylum",
                                    "Los Angeles-based Temple Hill Entertainment")],
          ["freeli films", "sentient entertainment", "asylum", "temple hill entertainment"])
    org = lambda name, dom, i: {"id": "%024x" % (0xe000 + i), "name": name, "primary_domain": dom}
    apollo.search_companies = lambda f, p, n: {"companies": [org("Freeli Films", "freelifilms.com", 1),
                                                             org("Freeli Films Group", "freeligroup.com", 2)]}
    check("exactly one company carries the exact name: that one",
          ea.find_company("Atlanta-Based Freeli Films")[0]["primary_domain"], "freelifilms.com")
    apollo.search_companies = lambda f, p, n: {"companies": [org("Sentient Entertainment", "sentient.tv", 1),
                                                             org("Sentient Entertainment", "sentientent.com", 2)]}
    check("two companies share the name: neither, and a person decides",
          ea.find_company("Sentient Entertainment"), (None, "2 companies in Apollo are named 'sentient entertainment'"
                                                            " -- left for a person"))
    apollo.search_companies = lambda f, p, n: {"companies": [org("Premeditated Productions", "facebook.com", 1)]}
    check("a platform is not a company's website", ea.find_company("Premeditated Productions")[0], None)
    apollo.search_companies = lambda f, p, n: {"companies": [org("Premeditated Media", "premeditated.media", 1)]}
    check("a near name is not the name", ea.find_company("Premeditated Productions")[0], None)

    print("\n-- the reveal has to have landed at this company")
    def person(domain=None, email=None, name="Firm"):
        return {"name": "P Q", "email": email,
                "organization": {"name": name, "primary_domain": domain} if (domain or name) else {}}
    check("the employer's domain matches", ea.same_company(person("firm.com"), "firm.com"), True)
    check("a subdomain is the same company", ea.same_company(person("mail.firm.com"), "firm.com"), True)
    check("no employer domain, but the address is at the lead's",
          ea.same_company(person(None, "p@firm.com"), "firm.com"), True)
    check("moved on: employer and address both elsewhere",
          ea.same_company(person("other.com", "p@other.com"), "firm.com"), False)
    severin = person("severinfilms.com", "kl@severinfilms.com", "Severin Films LLC")
    check("Apollo's own website for the company counts when it was searched there",
          (ea.same_company(severin, "severin-films.com"), ea.same_company(severin, "severin-films.com",
                                                                        "severinfilms.com")), (False, True))

    calls[:] = []
    apollo.search_people = lambda f, p, n: stub(f, p, n, [hit("Acquisitions/Producer")])
    ea.search("severin-films.com", ROLES, True, org_id="672c5f34b0a5ee00014985cb")
    check("searching Apollo's record of the company: by its id, not the lead's website",
          (calls[0].get("organization_ids"), "q_organization_domains_list" in calls[0]),
          (["672c5f34b0a5ee00014985cb"], False))

    print("\n-- the gate that keeps credits where the owner put them")
    check("a segment with no enrichment block spends nothing",
          ea.enrich_block({})["enabled"], False)
    check("provider apollo but not enabled: still nothing",
          ea.enrich_block({"enrichment": {"provider": "apollo"}})["enabled"], False)
    blk = ea.enrich_block({"enrichment": {"provider": "apollo", "enabled": True, "credits_per_run": 40}})
    check("enabled: the run's ceiling and the defaults around it",
          (blk["enabled"], blk["credits_per_run"], blk["verified_only"], blk["stale_days"], blk["score_over"]),
          (True, 40, True, 30, None))
    check("score_over is read as a number, and nonsense is no threshold rather than a crash",
          [ea.enrich_block({"enrichment": {"score_over": v}})["score_over"] for v in (30, "30", "thirty")],
          [30.0, 30.0, None])

    print("\n-- what an address is worth to the score (reachable_decision_maker)")
    check("a named person with a verified address: full marks",
          ea.contact_value({"name": "Nina Shah", "email": "n@x.com", "email_status": "valid"}), 1.0)
    check("a catch-all address may land anywhere: half",
          ea.contact_value({"name": "Nina Shah", "email": "n@x.com", "email_status": "catch_all"}), 0.5)
    check("an address with nobody's name on it: half",
          ea.contact_value({"name": "", "email": "n@x.com", "email_status": "valid"}), 0.5)
    check("an address Apollo has not verified: half, as the rubric says",
          ea.contact_value({"name": "Nina Shah", "email": "n@x.com", "email_status": "unverified"}), 0.5)
    check("nothing to write to: nothing", ea.contact_value({"name": "Nina Shah", "email": None}), 0.0)
    import dbconn
    keep = (dbconn.Db, apollo.key_is_set, ea.segment_config, sys.argv)
    dbconn.Db = lambda *a, **k: FakeDb(None)
    apollo.key_is_set = lambda: False
    ea.segment_config = lambda db: {"enrichment": {"provider": "apollo", "enabled": True}}
    sys.argv = ["enrich_apollo.py"]
    try:
        check("no key on the server: the step skips, and the weekly refresh carries on", ea.main(), 0)
    finally:
        dbconn.Db, apollo.key_is_set, ea.segment_config, sys.argv = keep

    live = json.loads((HERE.parent / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))
    check("production houses is the segment the owner turned on", ea.enrich_block(live)["enabled"], True)
    for slug in ("lcx-clipping", "startup-acquisitions", "universal"):
        cfg = json.loads((HERE.parent / "config" / ("segment.%s.json" % slug)).read_text(encoding="utf-8"))
        check("%s Apollo enrichment follows the sourcing policy" % slug,
              ea.enrich_block(cfg)["enabled"], slug != "lcx-clipping")
    check("production houses keeps its own rules: no weekly cap, no country hold, the old pick, no cross-project skip",
          [ea.enrich_block(live)[k] for k in ("credits_per_week", "reveal_countries", "employer_check", "strict_roles",
                                              "skip_known_elsewhere")],
          [None, [], False, False, False])
    check("  and none of LCX Services' 2026-10-07 guards: no site-read rule, no named-person rule, over 22.5",
          [ea.enrich_block(live)[k] for k in ("site_read", "named_for", "score_over")], [False, [], 22.5])
    for slug in ("lcx-clipping", "startup-acquisitions", "universal"):
        cfg = json.loads((HERE.parent / "config" / ("segment.%s.json" % slug)).read_text(encoding="utf-8"))
        check("  nor %s" % slug, [ea.enrich_block(cfg)[k] for k in ("site_read", "named_for")], [False, []])

    print("\n-- LCX Services (the owner, 2026-10-07: \"Enriching from apollo is acceptable\")")
    lcx = json.loads((HERE.parent / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
    b = ea.enrich_block(lcx)
    check("on, inside a stated budget: 120 a week, 700 kept for the others, over 60, four countries",
          (b["enabled"], b["credits_per_week"], b["keep_in_reserve"], b["score_over"], b["reveal_countries"]),
          (True, 120, 700, 60.0, ["US", "GB", "IN", "AE"]))
    check("  scoring v4 (2026-10-07): only leads whose own site was read; banks and mid-size companies need a"
          " named person, so an inbox alone does not end the search there",
          (b["site_read"], b["named_for"]), (True, ["corporate_teams", "financial_services"]))
    check("  the named-person rule follows the shortlist's: off with auto-shortlist off, or with no list",
          (ea.enrich_block(dict(lcx, auto_shortlist=dict(lcx["auto_shortlist"], enabled=False)))["named_for"],
           ea.enrich_block(dict(lcx, auto_shortlist=dict(lcx["auto_shortlist"], named_contact_for="corporate_teams")))
           ["named_for"]), ([], []))
    check("  no 1-credit name lookups (every lead has a website)", b["by_name"], False)
    check("who to look for depends on the lead: a school's principal, a hotel's director of sales",
          (ea.roles_for(lcx, "schools")[0], ea.roles_for(lcx, "hospitality")[0]),
          ("Principal", "Director of Sales and Marketing"))
    check("  a lead of no known audience falls back to the project's list",
          ea.roles_for(lcx, None) == lcx["target_contact_roles"], True)
    check("the employer check: the same company under its legal name passes, another company does not",
          [ea.works_at({"company": c}, n) for c, n in (("Gyldendal A/S", "Gyldendal"), ("Harrods Ltd", "Harrods"),
                                                       ("Ladybird Books", "Penguin Random House"), ("", "X"),
                                                       ("First Horizon", "First Citizens Bank"),
                                                       ("Bank of Marin", "Bank of Hope"),
                                                       ("Marriott Vacations Worldwide", "Marriott International"),
                                                       ("AG Barr Group", "A.G. Barr"), ("Abe's of Maine", "Abes of Maine"),
                                                       ("Arte Studio", "Artemis Partners"))],
          [True, True, False, False, False, False, True, True, True, False])
    check("  a lead saved from the search page names its country as Apollo does: still one of the four",
          [x in ea.country_forms(["US", "GB", "IN", "AE"]) for x in ("US", "UNITED KINGDOM", "UAE", "AUSTRALIA", "AU")],
          [True, True, True, False, False])
    roles = ea.roles_for(lcx, "attractions")
    senior = b["senior"]

    def strict(titles):
        who, _ = ea.pick([hit(x, i=i) for i, x in enumerate(titles, 1)], roles, strict=True, senior_re=senior)
        return who["title"] if who else None
    check("strict: a title that only shares 'director' is not paid for",
          strict(["Director of Benefits Administration"]), None)
    check("  nor a vice president of something else", strict(["Vice President of Architecture"]), None)
    check("  a role, a real shared word, or a founder is",
          [strict([x]) for x in ("Head of Marketing", "VP Guest Experience", "Co Founder")],
          ["Head of Marketing", "VP Guest Experience", "Co Founder"])
    check("  the only person Apollo lists is no longer reason enough", strict(["MD"]), None)


class FakeDb:
    """dbconn.Db against one open test transaction."""

    def __init__(self, cur):
        self.cur = cur

    def run(self, fn):
        return fn(self.cur)

    def close(self):
        pass


def database():
    print("\n-- lead selection and the write, against the database (rolled back)")
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    db = FakeDb(cur)
    try:
        slug = "zz-test-enrich-" + uuid.uuid4().hex[:6]
        ea.SEGMENT = slug
        rubric = [{"key": "reachable_decision_maker", "points": 10,
                   "input": "metadata.scoring_inputs.reachable_decision_maker"},
                  {"key": "genre_fit", "points": 10, "input": "metadata.scoring_inputs.genre_fit"}]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'test', 'company', %s::jsonb)"
                    " returning id", (slug, json.dumps({"enrichment": {"provider": "apollo", "enabled": True},
                                                          "rubric": rubric})))
        seg = cur.fetchone()[0]

        def lead(name, domain, status, meta="{}"):
            cur.execute("insert into entities (segment_id, name, domain, source, status, status_changed_at, metadata)"
                        " values (%s, %s, %s, 'test', %s, now(), %s::jsonb) returning id",
                        (seg, name, domain, status, meta))
            return cur.fetchone()[0]

        def contact(eid, email, name=None, status="valid"):
            cur.execute("insert into contacts (entity_id, full_name, email, email_status, source)"
                        " values (%s, %s, %s, %s, 'test')", (eid, name, email, status))

        nothing = lead("Nothing To Write To", "nothing.example", "ready_for_review")
        short = lead("Shortlisted No Address", "short.example", "shortlisted")
        inbox = lead("Inbox Only", "inbox.example", "ready_for_review")
        contact(inbox, "info@inbox.example")
        named = lead("Already Named", "named.example", "ready_for_review")
        contact(named, "ava@named.example", "Ava Producer")
        lead("Rejected", "rejected.example", "rejected")
        lead("Archived", "archived.example", "archived")
        lead("No Website", None, "ready_for_review")
        fresh = lead("Asked Yesterday", "fresh.example", "ready_for_review",
                     json.dumps({"apollo_checked": "v1:none",
                                 "apollo_checked_at": (__import__("datetime").datetime.now(
                                     __import__("datetime").timezone.utc)).isoformat()}))

        got = [r[1] for r in ea.candidates(db, False, 50, 30, False)]
        check("shortlisted first, then whoever has nothing to write to",
              got, ["Shortlisted No Address", "Nothing To Write To"])
        check("a rejected, archived or website-less lead is never enriched",
              [n for n in got if n in ("Rejected", "Archived", "No Website")], [])
        check("a lead asked about yesterday is left alone", "Asked Yesterday" in got, False)
        check("--recheck asks about it again",
              "Asked Yesterday" in [r[1] for r in ea.candidates(db, False, 50, 30, True)], True)
        check("--unnamed is the other half: an inbox with nobody's name on it",
              [r[1] for r in ea.candidates(db, True, 50, 30, False)], ["Inbox Only"])
        check("a lead that already has a named person is not in either list",
              "Already Named" in got + [r[1] for r in ea.candidates(db, True, 50, 30, False)], False)

        revealed = {"apollo_id": "%024x" % 0xd001, "name": "Nina Shah", "first_name": "Nina",
                    "title": "Head of Development", "email": "nina@nothing.example", "email_status": "valid",
                    "apollo_email_status": "verified", "linkedin_url": "https://www.linkedin.com/in/nina",
                    "organization": {"name": "Nothing To Write To", "primary_domain": "nothing.example"}}
        what, _ = ea.stamp(db, nothing, "written", person=revealed, credits=1)
        cur.execute("select full_name, email, email_status, source, verifier from contacts where entity_id = %s",
                    (nothing,))
        check("the address is written as a contact of the lead, verified by Apollo",
              (what, cur.fetchall()), ("added", [("Nina Shah", "nina@nothing.example", "valid", "apollo", "apollo")]))
        cur.execute("select metadata->>'apollo_checked', metadata->'apollo_enrich'->>'name',"
                    " metadata->'apollo_people'->%s->>'title' from entities where id = %s",
                    (revealed["apollo_id"], nothing))
        check("the lead records what was bought, and from whom",
              cur.fetchone(), ("v1:written", "Nina Shah", "Head of Development"))
        check("it is not offered again", [r[1] for r in ea.candidates(db, False, 50, 30, False)],
              ["Shortlisted No Address"])

        ea.stamp(db, short, "none")
        cur.execute("select metadata->>'apollo_checked', metadata ? 'apollo_enrich' from entities where id = %s",
                    (short,))
        check("a lead Apollo knows nobody at is stamped and costs nothing",
              cur.fetchone(), ("v1:none", False))

        contact(inbox, "nina@inbox.example", "Nina Shah")
        cur.execute("select refresh_primary_contacts(%s)", (slug,))
        cur.execute("select c.email from contacts c where c.entity_id = %s and c.is_primary", (inbox,))
        check("the named person becomes the one a draft writes to; info@ stays on the lead",
              cur.fetchone()[0], "nina@inbox.example")

        print("\n-- the owner's rule: Apollo is for companies scoring over 30")
        at30 = lead("Exactly Thirty", "thirty.example", "ready_for_review")
        above = lead("Just Over", "over.example", "ready_for_review")
        below = lead("Well Under", "under.example", "ready_for_review")
        for eid, score in ((at30, 30), (above, 30.5), (below, 12)):
            cur.execute("update entities set fit_score = %s where id = %s", (score, eid))
        got = [r[1] for r in ea.candidates(db, False, 50, 30, True, 30)]
        check("over 30 means over: 30.5 is asked about, 30 and 12 are not",
              [n for n in got if n in ("Exactly Thirty", "Just Over", "Well Under")], ["Just Over"])
        check("no threshold configured: every open lead without an address, as before",
              {"Exactly Thirty", "Just Over", "Well Under"} <= {r[1] for r in ea.candidates(db, False, 50, 30, True)},
              True)

        print("\n-- a written address is scored, never marked down")
        cur.execute("update entities set metadata = metadata || %s::jsonb where id = %s",
                    (json.dumps({"scoring_inputs": {"reachable_decision_maker": 0, "genre_fit": 1},
                                 "unverified_inputs": ["reachable_decision_maker"]}), above))
        cur.execute("select score_entity(%s)", (above,))
        before = cur.fetchone()[0]
        moved = ea.credit_contact(cur, above, 1.0)
        cur.execute("select metadata->'scoring_inputs'->>'reachable_decision_maker',"
                    " metadata->'unverified_inputs' ? 'reachable_decision_maker', fit_score from entities where id = %s",
                    (above,))
        rdm, still_defaulted, after = cur.fetchone()
        check("the defaulted 0 becomes 1.0, stops being 'not checked', and the score goes up",
              (float(rdm), still_defaulted, moved is not None and float(after) > float(before)), (1.0, False, True))
        check("a catch-all later does not mark a named person down", ea.credit_contact(cur, above, 0.5), None)
        cur.execute("select (metadata->'scoring_inputs'->>'reachable_decision_maker')::numeric from entities"
                    " where id = %s", (above,))
        check("and the 1.0 stays", float(cur.fetchone()[0]), 1.0)

        print("\n-- no website: the lead is included only when the config says to look it up by name")
        nosite = lead("Premeditated Productions", None, "shortlisted")
        cur.execute("update entities set fit_score = 29.6 where id = %s", (nosite,))
        check("find_website_by_name off: a lead without a website is not offered",
              "Premeditated Productions" in [r[1] for r in ea.candidates(db, False, 50, 30, True, 22.5)], False)
        check("on: it is, when it scores over the line",
              "Premeditated Productions" in [r[1] for r in ea.candidates(db, False, 50, 30, True, 22.5, True)], True)
        got = ea.give_website(db, nosite, {"id": "%024x" % 0xe101, "name": "Premeditated Productions",
                                           "primary_domain": "https://www.premeditatedproductions.com/"})
        cur.execute("select domain, metadata->>'domain_resolution' from entities where id = %s", (nosite,))
        check("the website Apollo knows is written, with where it came from",
              (got, cur.fetchone()), ("premeditatedproductions.com",
                                      ("premeditatedproductions.com",
                                       "apollo company search: Premeditated Productions (%024x)" % 0xe101)))
        twin = lead("Premeditated Prods", None, "ready_for_review")
        check("a website another lead already holds is not written: the same company twice is a merge",
              ea.give_website(db, twin, {"id": "%024x" % 0xe102, "name": "Premeditated Prods",
                                         "primary_domain": "premeditatedproductions.com"}), None)
        cur.execute("select domain, metadata->>'domain_conflict' from entities where id = %s", (twin,))
        check("and the lead says why", cur.fetchone(),
              (None, "premeditatedproductions.com already belongs to Premeditated Productions"))
    finally:
        conn.rollback()
        cur.close()
        conn.close()


def lcx_guards():
    """LCX Services' scoring-v4 guards on who is a candidate (the owner, 2026-10-07: "Apollo reveals only for leads
    over 60 whose own site was read and that are not the wrong buyer"; "banks and mid-size companies need a named
    person"), against the database, rolled back: enrichment.require_site_read and auto_shortlist.named_contact_for,
    read through enrich_block() as main() reads them."""
    print("\n-- LCX Services' guards: a credit only where the site was read, and a name for banks and corporates"
          " (rolled back)")
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    db = FakeDb(cur)
    keep = ea.SEGMENT
    try:
        slug = "zz-lcx-guard-" + uuid.uuid4().hex[:6]
        cfg = {"enrichment": {"provider": "apollo", "enabled": True, "score_over": 60, "require_site_read": True},
               "auto_shortlist": {"enabled": True, "min_score": 70,
                                  "named_contact_for": ["corporate_teams", "financial_services"]},
               "rubric": [{"key": "reachable_decision_maker", "points": 10,
                           "input": "metadata.scoring_inputs.reachable_decision_maker"}]}
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'g', 'company', %s::jsonb)"
                    " returning id", (slug, json.dumps(cfg)))
        seg = cur.fetchone()[0]
        ea.SEGMENT = slug

        def lead(name, kind="consumer_brands", pages=3, judged=True, site_read=True, theirs=True, wrong=0.0, big=0.0,
                 score=65, contact=None, gate=None):
            """A lead as the site pass and tools/lcx_judge.py leave it: pages read, the judge's site_read and
            site_theirs, its wrong_buyer and too_big; and a contact (None, 'inbox' or 'named')."""
            dom = name.lower().replace(" ", "-") + ".example"
            meta = {"kind": kind, "site_contact_routes": {"pages_read": pages},
                    "scoring_inputs": dict({"wrong_buyer": wrong, "too_big": big}, **(gate or {}))}
            if judged:
                meta["lcx_judgement"] = {"site_read": site_read, "site_theirs": theirs}
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score, metadata) values"
                        " (%s, %s, %s, 'test', 'ready_for_review', %s, %s::jsonb) returning id",
                        (seg, name, dom, score, json.dumps(meta)))
            eid = cur.fetchone()[0]
            if contact == "named_role":
                # a named person at accounting@ ranks below an unnamed info@ (sql/28): the drafter writes to info@
                cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                            " (%s, null, %s, 'valid', 'test'), (%s, 'Raj Patel', %s, 'valid', 'test')",
                            (eid, "info@" + dom, eid, "accounting@" + dom))
            elif contact:
                cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                            " (%s, %s, %s, 'valid', 'test')", (eid, "Ava Shah" if contact == "named" else None,
                                                               ("ava@" if contact == "named" else "info@") + dom))
            return name
        ok = lead("Read And Theirs")
        lead("Never Read", pages=0)
        lead("Bot Wall Only", site_read=False)
        lead("Not Judged Yet", judged=False)
        lead("Wrong Buyer Half", wrong=0.5)
        half_big = lead("Too Big Half", big=0.5)
        lead("Too Big Full", big=1.0)
        lead("Not Their Site", theirs=False)
        unknown = lead("Theirs Unknown", theirs=None)
        lead("Under Sixty", score=55)
        corp = lead("Corporate Inbox Only", "corporate_teams", contact="inbox")
        bank = lead("Bank Inbox Only", "financial_services", contact="inbox")
        lead("Brand Inbox Only", contact="inbox")
        lead("Corporate Named", "corporate_teams", contact="named")
        role_named = lead("Bank Named Role Inbox", "financial_services", contact="named_role")
        drafted = lead("Bank Already Drafted", "financial_services", contact="inbox")
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body) select e.id, c.id, 't',"
                    " 'S', 'B' from entities e join contacts c on c.entity_id = e.id where e.segment_id = %s"
                    " and e.name = %s", (seg, drafted))
        freed = lead("Bank Draft Cancelled", "financial_services", contact="inbox")
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status) select e.id, c.id,"
                    " 't', 'S', 'B', 'cancelled' from entities e join contacts c on c.entity_id = e.id"
                    " where e.segment_id = %s and e.name = %s", (seg, freed))
        gated = [lead("A Major's Brand", gate={"oversized_signal": True}),
                 lead("Brand Unsafe", gate={"brand_risk_signal": "unsafe"}),
                 lead("Sanctioned Country", gate={"country_signal": "unpayable"}),
                 lead("Consent Law Country", gate={"country_signal": "disallowed"}),
                 lead("Dead Site", gate={"activity_signal": "dead"})]
        b = ea.enrich_block(cfg)

        def picked(unnamed=False, block=None):
            bb = block or b
            return sorted(r[1] for r in ea.candidates(db, unnamed, 50, 30, True, bb["score_over"], False, None,
                                                      bb["site_read"], bb["named_for"]))
        got = picked()
        check("the default pass: read and theirs, not the wrong buyer, under too big, over 60; and the bank and"
              " corporate with only an inbox", got, sorted([ok, half_big, unknown, corp, bank, role_named, freed]))
        check("  never a lead whose email is already drafted (a person found now would not be written to);"
              " a cancelled draft frees it", (drafted in got, freed in got), (False, True))
        check("  a bank whose only named person sits at accounting@: the drafter would write to info@, so Apollo"
              " looks for a named one", role_named in got, True)
        check("  never a lead a gate excludes (a major, brand-unsafe, sanctioned or consent-law, a dead site): gates"
              " never archive a shortlisted lead, so the queue checks their signals itself",
              [n for n in gated if n in got], [])
        check("  never: a site not read, a bot wall, a lead not judged yet, the wrong buyer (even half), too big,"
              " a site not theirs",
              [n for n in ("Never Read", "Bot Wall Only", "Not Judged Yet", "Wrong Buyer Half", "Too Big Full",
                           "Not Their Site") if n in got], [])
        check("  a brand with an inbox has someone to write to; a corporate with a named person is done",
              [n for n in ("Brand Inbox Only", "Corporate Named") if n in got], [])
        check("--unnamed: every read lead whose only address has nobody's name on it",
              picked(unnamed=True), sorted([bank, "Brand Inbox Only", corp, freed]))
        off = ea.enrich_block(dict(cfg, auto_shortlist=dict(cfg["auto_shortlist"], enabled=False)))
        check("auto-shortlist off: an inbox is draftable again, so the corporate's is enough", corp in picked(block=off),
              False)
        plain = ea.enrich_block({"enrichment": {"provider": "apollo", "enabled": True, "score_over": 60}})
        check("a project without the keys (US Production Houses): neither guard, every lead over the line with nobody",
              picked(block=plain), sorted(["Read And Theirs", "Never Read", "Bot Wall Only", "Not Judged Yet",
                                           "Wrong Buyer Half", "Too Big Half", "Too Big Full", "Not Their Site",
                                           "Theirs Unknown"] + gated))
        # (the plain project's default pass takes only leads with no usable address, so neither bank is in it)
    finally:
        ea.SEGMENT = keep
        conn.rollback()
        cur.close()
        conn.close()


def lcx_run():
    """LCX Services' rules end to end, with Apollo stubbed: the country hold, the search at the current
    employer, the employer check, nobody paid for twice across projects, the weekly cap and the ledger."""
    print("\n-- an LCX Services run, Apollo stubbed (rolled back)")
    import psycopg2
    import apollo_budget
    import dbconn
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    keep = (dbconn.Db, apollo.key_is_set, apollo.search_people, apollo.reveal_people, apollo.credits, ea.SEGMENT,
            sys.argv, ea.DELAY)
    calls, reveals = [], []
    try:
        tag = uuid.uuid4().hex[:6]
        slug, other = "zz-lcx-enrich-" + tag, "zz-other-enrich-" + tag
        cfg = {"rubric": [{"key": "reachable_decision_maker", "points": 50,
                           "input": "metadata.scoring_inputs.reachable_decision_maker"}],
               "target_contact_roles": ["Founder"],
               "audiences": [{"key": "consumer_brands", "contact_roles": ["Head of Marketing", "Chief Marketing Officer"]}],
               "enrichment": {"provider": "apollo", "enabled": True, "credits_per_run": 110, "credits_per_week": 3,
                              "keep_in_reserve": 700, "verified_only": True, "reveal_countries": ["US", "GB"],
                              "current_employer_check": True, "require_fitting_role": True,
                              "skip_revealed_elsewhere": True, "senior_titles": "(founder|chief executive)"}}
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 't', 'company', %s::jsonb) returning id",
                    (slug, json.dumps(cfg)))
        seg = cur.fetchone()[0]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'o', 'company', '{}'::jsonb) returning id",
                    (other,))
        oseg = cur.fetchone()[0]

        def lead(name, domain, country, extra=None, seg_id=None):
            meta = dict({"kind": "consumer_brands", "hq_country": country}, **(extra or {}))
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score, metadata)"
                        " values (%s, %s, %s, 'test', 'ready_for_review', 50, %s::jsonb) returning id",
                        (seg_id or seg, name, domain, json.dumps(meta)))
            return cur.fetchone()[0]
        good = lead("ZZ Good Brand", "good-%s.example" % tag, "US")
        held = lead("ZZ Australian Brand", "au-%s.example" % tag, "AU")
        org = "%024x" % 0xa0f1
        known = lead("ZZ Apollo Found", "found-%s.example" % tag, "GB", {"apollo": {"id": org}})
        moved = lead("ZZ Another Employer", "moved-%s.example" % tag, "US")
        twice = lead("ZZ Already Revealed", "twice-%s.example" % tag, "US")
        spare = lead("ZZ Over The Cap", "cap-%s.example" % tag, "US")
        named = lead("ZZ A Named Country", "named-%s.example" % tag, "United Kingdom")
        cur.execute("update entities set fit_score = 60 where id = %s", (named,))
        for i in range(3):                           # better scored, but based where nothing is paid for
            hx = lead("ZZ Held %d" % i, "held%d-%s.example" % (i, tag), "Australia")
            cur.execute("update entities set fit_score = 70 where id = %s", (hx,))
        dup_person = "%024x" % 0xb0b0
        lead("ZZ Elsewhere", "elsewhere-%s.example" % tag, "US", {"apollo_enrich": {"person": dup_person}}, seg_id=oseg)
        cur.execute("insert into apollo_spend (segment_id, kind, credits, ref) values (%s, 'company_page', 1, 'this week')",
                    (seg,))

        last = [None]

        def people(filters, page=1, per_page=10):
            calls.append(filters)
            dom = (filters.get("q_organization_domains_list") or [None])[0]
            last[0] = dom or "found-%s.example" % tag
            if filters.get("organization_ids"):
                return {"total": 1, "people": [dict(hit("Head of Marketing", i=31), company="ZZ Apollo Found")]}
            if dom and dom.startswith("moved-"):
                return {"total": 1, "people": [dict(hit("Head of Marketing", i=32), company="Some Other Firm")]}
            if dom and dom.startswith("twice-"):
                return {"total": 1, "people": [dict(hit("Head of Marketing", i=33), id=dup_person, company="ZZ Already Revealed")]}
            name = {"good-": "ZZ Good Brand", "cap-": "ZZ Over The Cap"}
            co = next((v for k, v in name.items() if dom and dom.startswith(k)), "Firm")
            return {"total": 2, "people": [dict(hit("Director of Benefits", i=34), company=co),
                                           dict(hit("Chief Marketing Officer", i=35), company=co)]}

        def reveal(ids):
            reveals.extend(ids)
            pid, dom = ids[0], last[0]                 # the company just searched
            return {"people": [{"apollo_id": pid, "name": "Pat Example", "first_name": "Pat", "title": "Head of Marketing",
                                "email": "pat@%s" % dom, "email_status": "valid", "apollo_email_status": "verified",
                                "organization": {"name": "x", "primary_domain": dom}}], "missing": [], "credits": 1.0}
        dbconn.Db = lambda *a, **k: FakeDb(cur)
        apollo.key_is_set = lambda: True
        apollo.search_people, apollo.reveal_people = people, reveal
        apollo.credits = lambda: {"lead_credits_left": 2204}
        ea.SEGMENT, ea.DELAY = slug, 0
        sys.argv = ["enrich_apollo.py", "--limit", "20"]
        check("the run completes", ea.main(), 0)

        def checked(eid):
            cur.execute("select metadata->>'apollo_checked' from entities where id = %s", (eid,))
            return cur.fetchone()[0]
        check("a lead based outside the reveal countries is held, not stamped", checked(held), None)
        check("  held in the query itself, so better-scored held leads never crowd the rest out",
              any(any("held" in d for d in (c.get("q_organization_domains_list") or [])) for c in calls), False)
        check("a lead whose country is Apollo's name for one of the four is searched (its people work elsewhere: free)",
              checked(named), "v1:other-employer")
        check("a lead the Apollo harvest found is searched at its current employer, by Apollo's id",
              any(c.get("organization_ids") == [org] for c in calls), True)
        check("  and its person is revealed", checked(known), "v1:written")
        check("people who work somewhere else now: nothing paid", checked(moved), "v1:other-employer")
        check("a person already revealed for another project is not paid for again", checked(twice), "v1:known-elsewhere")
        check("the strict pick paid for the CMO, not the benefits director",
              "%024x" % (0xc000 + 34) in reveals, False)
        check("the weekly cap: 3 a week, 1 already spent this week, so 2 reveals and no more", len(reveals), 2)
        check("  the lead over the cap is left for next week, unstamped", checked(spare), None)
        cur.execute("select kind, credits from apollo_spend where segment_id = %s order by id", (seg,))
        check("every credit is in the ledger", [(k, float(c)) for k, c in cur.fetchall()],
              [("company_page", 1.0), ("reveal", 1.0), ("reveal", 1.0)])
        block = ea.enrich_block(cfg)
        check("the allowance reads the ledger: the week's cap is used up",
              apollo_budget.allowance(cur, slug, cfg["enrichment"], 2204, 110)[0], 0)
        check("  and the reserve binds when the month runs low",
              apollo_budget.allowance(cur, slug, dict(cfg["enrichment"], credits_per_week=None), 701, 110)[0], 1)
        check("  (the block reads the cap the run used)", block["credits_per_week"], 3)
        check("  and when Apollo cannot say what is left, a project keeping a reserve spends nothing",
              apollo_budget.allowance(cur, slug, dict(cfg["enrichment"], credits_per_week=None), None, 110),
              (0, "the balance: Apollo did not say what is left, and 700 must be kept for the other projects"))
        check("  a project with no budget stated is not held by it", apollo_budget.allowance(cur, slug, {}, None, 110)[0], 110)
        cur.execute("delete from apollo_spend where segment_id = %s", (seg,))
        cur.execute("select (date_trunc('week', (now() at time zone 'utc') - interval '4 days') + interval '4 days')"
                    " at time zone 'utc'")
        friday = cur.fetchone()[0].astimezone(dt.timezone.utc)
        for at, n in ((friday - dt.timedelta(minutes=5), 100), (friday + dt.timedelta(minutes=5), 7)):
            cur.execute("insert into apollo_spend (segment_id, kind, credits, at) values (%s, 'reveal', %s, %s)", (seg, n, at))
        check("the week runs from Friday 00:00 UTC: last Thursday night's spend is last week's",
              (apollo_budget.spent(cur, slug), apollo_budget.spent(cur, segment_id=seg), friday.weekday(),
               (friday.hour, friday.minute)), (7.0, 7.0, 4, (0, 0)))
    finally:
        (dbconn.Db, apollo.key_is_set, apollo.search_people, apollo.reveal_people, apollo.credits, ea.SEGMENT,
         sys.argv, ea.DELAY) = keep
        conn.rollback()
        cur.close()
        conn.close()


def main():
    offline()
    try:
        database()
    except Exception as e:                       # noqa: BLE001 -- a missing database is a failure, not a crash
        RESULTS.append(False)
        print("FAIL  database part: %r" % (e,))
    try:
        lcx_guards()
    except Exception as e:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        RESULTS.append(False)
        print("FAIL  LCX guards: %r" % (e,))
    try:
        lcx_run()
    except Exception as e:                       # noqa: BLE001
        import traceback
        traceback.print_exc()
        RESULTS.append(False)
        print("FAIL  LCX run: %r" % (e,))
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
