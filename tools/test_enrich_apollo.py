#!/usr/bin/env python3
"""test_enrich_apollo.py -- the Apollo enrichment pass, as a regression table.

    python tools/test_enrich_apollo.py

Part one needs no key and no network: who gets picked out of a search, which
searches are made and in what order, and when a reveal is refused as somebody
who has moved on. Part two runs the lead selection and the write against the
real database inside one transaction that is rolled back: a throwaway segment,
leads in every state, then ROLLBACK. Not one credit is spent by this file.
Exit code 1 on any failure.
"""
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
        check("%s spends nothing" % slug, ea.enrich_block(cfg)["enabled"], False)


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
    finally:
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
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
