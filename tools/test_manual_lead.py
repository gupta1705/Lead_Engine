#!/usr/bin/env python3
"""test_manual_lead.py -- Add a lead: a lead a person found on their own, its project, and the email they write
(owner, 2026-10-23: "Add a feature to send custom mail to a lead that we find on our own, as in lead is not generated
by software and then there should be an option to select the category it belongs to and then the usual"), as a table.

    python tools/test_manual_lead.py

Offline first (what the form refuses), then the real app in-process (FastAPI's TestClient) against the real database
inside ONE transaction that is rolled back, with sql/42 applied inside it. Checked:

  * the form: a name and an address are needed; a bad address, site or country is named; a country the project
    never emails (consent law, or one it cannot be paid from) is refused, also when only the address's country
    domain says so; LCX Services needs the service it pitches; our own addresses and TVF itself are refused
  * asking changes nothing; approving adds the lead (source manual, shortlisted, who added it, its country), the
    contact the person vouched for (allowed in an Apollo-only project, sql/42), and one approved email to that
    person, signed by the writer, copied to the default CC (or nobody when switched off)
  * a company already in the project is used, never added twice: its waiting automatic draft is replaced; a rejected
    one is reopened, and the page says so first; one already contacted, or already written to, is refused and
    nothing is kept
  * LCX Services: the email pitches the picked service and carries the deck (or not, when left out)
  * the usual after it is sent: four days later with no reply, the thread is due its one follow-up
  * no name and title yet: refused, as for any email a person writes
Exit code 1 on any failure.
"""
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-manual-lead-test-" + uuid.uuid4().hex

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import manual_lead as ml  # noqa: E402
import outreach_policy as pol  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
SLUGS = ("us-production-houses", "lcx-services", "lcx-clipping", "startup-acquisitions", "universal")
CFGS = {s: json.loads((ROOT / "config" / ("segment.%s.json" % s)).read_text(encoding="utf-8")) for s in SLUGS}
CC = ["amritanshv@lightscameraexperiment.com"]


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-86s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


def offline():
    print("-- the form")
    ph, lcxs, clip = CFGS["us-production-houses"], CFGS["lcx-services"], CFGS["lcx-clipping"]
    probs = lambda body, cfg=ph: ml.read(body, cfg)[1]                                     # noqa: E731
    check("nothing typed: the company and the address are asked for", sorted(probs({})), ["company", "email"])
    check("Clipping calls its lead a show", probs({}, clip)["company"], "Write the show's name.")
    check("a bad address, site and country are each named",
          sorted(probs({"company": "A", "email": "kay at acme", "website": "acme", "country": "Narnia"})),
          ["country", "email", "website"])
    check("a whole lead reads clean", probs({"company": "Acme Studios", "email": "Kay@Acme.com ",
                                             "website": "https://www.acme.com/about", "country": "US"}), {})
    s = ml.read({"company": "Acme", "email": "kay@gmail.com", "website": ""}, ph)[0]
    check("a free mailbox is not the lead's domain", (s["email"], s["domain"]), ("kay@gmail.com", None))
    s = ml.read({"company": "Acme", "email": "kay@acme.com", "website": "www.acme-films.co.uk/x"}, ph)[0]
    check("the site's domain is the lead's", s["domain"], "acme-films.co.uk")
    check("Clipping: an address in Germany is refused (consent law)",
          "Germany" in probs({"company": "A", "email": "kay@show.de"}, clip).get("email", ""), True)
    check("  unless its country is given as somewhere else",
          probs({"company": "A", "email": "kay@show.de", "country": "United States"}, clip), {})
    check("  and a country of Canada is refused outright", "Canada" in probs(
        {"company": "A", "email": "kay@show.com", "country": "Canada"}, clip).get("country", ""), True)
    check("Production Houses has no such list", probs({"company": "A", "email": "kay@show.de"}), {})
    check("LCX Services: the service is asked for", probs({"company": "A", "email": "kay@a.com"}, lcxs),
          {"service": "Pick the service this email pitches."})
    check("  one it cannot be paid from is refused", "cannot be paid" in probs(
        {"company": "A", "email": "kay@a.com", "country": "Russia", "service": "AI Onboarding Employee"}, lcxs)
        .get("country", ""), True)
    for slug in SLUGS:
        p = ml.project(CFGS[slug])
        check("%s: one follow-up 4 days on, the default CC%s" % (slug, ", the deck" if p["files"] else ""),
              (p["follow_up_days"], p["default_cc"], p["files"]),
              (4, CC, ["LCX Services - pitch deck.pdf"] if slug == "lcx-services" else []))
    check("LCX Services offers the deck's 18 services", len(ml.project(lcxs)["services"]), 18)


class TxConn:
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


def api():
    import main
    import auth
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    kicked = []
    main._scheduler.kick_outreach = lambda seg, trigger="manual": kicked.append(seg)
    main._scheduler.wake_sender = lambda: None
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # the repo's rules and configs, whatever the live database has yet (all rolled back)
        cur.execute((ROOT / "sql" / "42_manual_leads.sql").read_text(encoding="utf-8"))
        for slug in SLUGS:
            cur.execute("update segments set config = %s where slug = %s", (json.dumps(CFGS[slug]), slug))
        main._SEG_CACHE.update(at=0.0, rows=[])
        tag = uuid.uuid4().hex[:6]

        def person(name, title):
            email = "zz-ml-%s-%s@example.com" % (name.split()[0].lower(), tag)
            h = bcrypt.hashpw(b"zz-ml-password", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                        (email, h, name, title))
            return email, {auth.COOKIE: auth.make_cookie(email, h)}
        kart, ck = person("Kartikeya", "Business Development and IP Strategy")
        _nobody, ck_new = person("Newcomer", None)

        def call(path, body, cookies=ck):
            client.cookies.clear()
            r = client.post(path, json=body, cookies=cookies)
            return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})

        def lead(**kw):
            b = {"project": "us-production-houses", "company": "ZZ Hand Films %s" % tag,
                 "website": "zz-hand-%s.example" % tag, "country": "United States", "city": "Austin",
                 "name": "Kelly Smith", "role": "Head of Development", "email": "kelly@zz-hand-%s.example" % tag,
                 "subject": "A partnership for {{company}}", "body": "Hi {{first_name}},\n\nI found your work and "
                 "would like to talk about a partnership.", "cc": None}
            b.update(kw)
            if b.get("cc") is None:
                b.pop("cc")
            return b

        def rows(domain):
            cur.execute("select e.id, e.source, e.status, e.status_reason, e.metadata, count(o.id) as emails"
                        " from entities e left join outreach o on o.entity_id = e.id where e.domain = %s"
                        " group by e.id", (domain,))
            return cur.fetchall()

        print("\n-- asking changes nothing")
        dom = "zz-hand-%s.example" % tag
        st, r = call("/api/leads/manual/check", {"project": "us-production-houses"})
        check("an empty form: what is missing, and the project's sign-off", (st, sorted(r["problems"]),
              "Kartikeya" in r["footer"]), (200, ["company", "email"], True))
        st, r = call("/api/leads/manual/check", lead())
        check("a whole lead: ready, greeted by first name, nothing it matches",
              (st, r["problems"], len(r["ready"]), r["ready"][0]["first_name"], r["match"]),
              (200, {}, 1, "Kelly", None))
        check("  and nothing was written", rows(dom), [])
        st, r = call("/api/leads/manual/check", {"project": "no-such-project"})
        check("a project that is not there", r["problems"], {"project": "Pick the project this lead belongs to."})
        st, r = call("/api/leads/manual/check", lead(project="us-production-houses"), cookies=ck_new)
        check("no name and title yet: refused (emails are signed with them)", st, 409)
        st, r = call("/api/leads/manual/check", lead(email=kart))
        check("one of our own addresses is refused", r["problems"].get("email"), "That is one of our own addresses.")
        st, r = call("/api/leads/manual/check", lead(email="someone@theviralfever.com"))
        check("TVF itself is never a lead", "TVF itself" in r["problems"].get("company", ""), True)

        print("\n-- approving: the lead, the person, the email")
        st, r = call("/api/leads/manual", lead())
        oid, eid = r.get("outreach_id"), r.get("lead_id")
        check("approved: one email, the project kicked", (st, bool(oid), kicked[-1:]),
              (200, True, ["us-production-houses"]))
        cur.execute("select e.source, e.status, e.status_reason, e.metadata, c.source as csrc, c.verifier,"
                    " c.full_name, c.role_title, o.status as ost, o.approval_mode, o.approved_by, o.template_key,"
                    " o.cc, o.subject, o.body, o.contact_id = c.id as to_her"
                    " from entities e join outreach o on o.entity_id = e.id join contacts c on c.entity_id = e.id"
                    " where o.id = %s", (oid,))
        x = cur.fetchone()
        m = x["metadata"]
        check("the lead: added by hand, shortlisted, who added it, where it is",
              (x["source"], x["status"], x["status_reason"], m["added_by_hand"]["by"], m["hq_country"], m["hq_city"]),
              ("manual", "shortlisted", "Added by hand by Kartikeya", kart, "US", "Austin"))
        check("the person: vouched for by a person, allowed in an Apollo-only project",
              (x["csrc"], x["verifier"], x["full_name"], x["role_title"]),
              ("manual", "person", "Kelly Smith", "Head of Development"))
        check("the email: approved by its writer, to her, copied to the default CC",
              (x["ost"], x["approval_mode"], x["approved_by"], x["template_key"], x["to_her"], x["cc"]),
              ("approved", "compose", kart, "compose", True, CC))
        check("  as she reads it: her name, the company, signed by the writer",
              (x["subject"], x["body"].startswith("Hi Kelly,"), "Kartikeya" in x["body"]),
              ("A partnership for ZZ Hand Films %s" % tag, True, True))
        cur.execute("select metadata #>> '{outreach_recipient,contact_id}' as rc from entities where id = %s", (eid,))
        rc = cur.fetchone()["rc"]
        check("  and the lead's recipient is her", rc, _contact(cur, eid, "kelly@zz-hand-%s.example" % tag))

        st, r = call("/api/leads/manual", lead(name="Kelly Smith"))
        check("the same lead again: refused, and nothing new kept",
              ("already has an email from us" in r["problems"].get("lead", ""), r["outreach_id"],
               [(z["source"], z["emails"]) for z in rows(dom)]),
              (True, None, [("manual", 1)]))
        st, r = call("/api/leads/manual", lead(email="kay@zz-cc-%s.example" % tag, website="zz-cc-%s.example" % tag,
                                               company="ZZ CC Co %s" % tag, cc=[]))
        cur.execute("select cc from outreach where id = %s", (r.get("outreach_id"),))
        check("the CC switched off: nobody is copied", cur.fetchone()["cc"], [])

        print("\n-- a company already in the project")
        cur.execute("select id from segments where slug = 'us-production-houses'")
        ph_id = cur.fetchone()["id"]

        def existing(status, reason=None, draft=False, slug_id=ph_id, name="ZZ Known"):
            d = "zz-known-%s-%s.example" % (status, tag)
            cur.execute("insert into entities (segment_id, name, domain, source, status, status_reason) values"
                        " (%s, %s, %s, 'apollo', %s, %s) returning id", (slug_id, "%s %s" % (name, status), d, status,
                                                                      reason))
            e = cur.fetchone()["id"]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status, verifier, source) values"
                        " (%s, 'Ada Lane', %s, 'valid', 'apollo', 'apollo') returning id", (e, "ada@" + d))
            c = cur.fetchone()["id"]
            if draft:
                cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body) values"
                            " (%s, %s, 'tvf_partner_v3', 'Auto', 'Hello Ada') returning id", (e, c))
                return d, e, cur.fetchone()["id"]
            return d, e, None
        d, e, auto = existing("shortlisted", draft=True)
        body = lead(company="ZZ Known shortlisted", website=d, email="kay@" + d, name="Kay Ito")
        st, r = call("/api/leads/manual/check", body)
        check("the page says it is the same lead, and that yours replaces its waiting draft",
              ((r["match"] or {}).get("id"), r["replaces_draft"], r["problems"]), (str(e), True, {}))
        st, r = call("/api/leads/manual", body)
        cur.execute("select status, stopped_reason from outreach where id = %s", (auto,))
        a = cur.fetchone()
        cur.execute("select count(*) as n from entities where segment_id = %s and domain = %s", (ph_id, d))
        check("approved: the draft is replaced, no second lead",
              (bool(r["outreach_id"]), a["status"], a["stopped_reason"], cur.fetchone()["n"]),
              (True, "cancelled", "replaced by an email Kartikeya wrote", 1))
        cur.execute("select c.email from outreach o join contacts c on c.id = o.contact_id where o.id = %s",
                    (r["outreach_id"],))
        check("  and it goes to the person typed in, not the one on file", cur.fetchone()["email"], "kay@" + d)

        d, e, _ = existing("rejected", reason="too small")
        body = lead(company="ZZ Known rejected", website=d, email="ada@" + d, name="Ada Lane")
        st, r = call("/api/leads/manual/check", body)
        check("a rejected lead: the page says approving reopens it", (r["reopens"], r["match"]["status_reason"]),
              ("rejected", "too small"))
        st, r = call("/api/leads/manual", body)
        cur.execute("select status, metadata #>> '{reopened_by_hand,was}' as was from entities where id = %s", (e,))
        y = cur.fetchone()
        check("  approved: reopened, and what it was is kept", (bool(r["outreach_id"]), y["status"], y["was"]),
              (True, "shortlisted", "rejected"))
        cur.execute("select source, verifier from contacts where entity_id = %s", (e,))
        check("  the Apollo-verified address it had stays Apollo's", dict(cur.fetchone()),
              {"source": "apollo", "verifier": "apollo"})

        d, e, _ = existing("contacted")
        st, r = call("/api/leads/manual", lead(company="ZZ Known contacted", website=d, email="new@" + d))
        cur.execute("select count(*) as n from contacts where entity_id = %s", (e,))
        check("one already contacted: refused, nothing added to it",
              ("already contacted" in r["problems"].get("lead", ""), r["outreach_id"], cur.fetchone()["n"]),
              (True, None, 1))

        print("\n-- LCX Services: the service, and the deck")
        base = lead(project="lcx-services", company="ZZ Bakery %s" % tag, website="zz-bakery-%s.example" % tag,
                    email="owner@zz-bakery-%s.example" % tag, country="United Kingdom", city="Leeds")
        st, r = call("/api/leads/manual/check", base)
        check("no service picked: asked for", r["problems"], {"service": "Pick the service this email pitches."})
        st, r = call("/api/leads/manual", dict(base, service="AI Onboarding Employee"))
        cur.execute("select o.service, o.attachments, e.metadata #>> '{lead_service,service}' as tag"
                    " from outreach o join entities e on e.id = o.entity_id where o.id = %s", (r.get("outreach_id"),))
        z = cur.fetchone() or {}
        check("approved: it pitches the picked service, the lead is tagged with it, the deck goes with it",
              (z.get("service"), z.get("tag"), [a["name"] for a in z.get("attachments") or []]),
              ("AI Onboarding Employee", "AI Onboarding Employee", ["LCX Services - pitch deck.pdf"]))
        st, r = call("/api/leads/manual", dict(base, service="Explainer Videos", attach=False,
                                               company="ZZ Bakery Two %s" % tag, website="zz-bakery2-%s.example" % tag,
                                               email="owner@zz-bakery2-%s.example" % tag))
        cur.execute("select attachments from outreach where id = %s", (r.get("outreach_id"),))
        check("  with the deck left out: none", (cur.fetchone() or {}).get("attachments", "missing"), None)

        print("\n-- the usual, after it goes")
        cur.execute("update outreach set status = 'sent', sent_at = now() - interval '5 days',"
                    " gmail_thread_id = %s, gmail_message_id = %s, sender_address = %s where id = %s",
                    ("zz-thread-" + tag, "zz-msg-" + tag, "kartikeyap@zz.example", oid))
        cur.execute("update entities set status = 'contacted' where id = %s", (eid,))
        steps = pol.followup_steps(CFGS["us-production-houses"]["outreach"])
        due = [str(row["opener_id"]) for row, _s in
               pol.due_followups(cur, "us-production-houses", steps, dt.datetime.now(dt.timezone.utc))]
        check("five days on with no reply: its one follow-up is due", str(oid) in due, True)
        st, r = call("/api/leads/manual/check", lead(name="Kelly Smith"))
        check("and adding it again now says it was already contacted",
              "already contacted" in r["problems"].get("lead", ""), True)
    finally:
        conn.rollback()
        conn.close()


def _contact(cur, eid, email):
    cur.execute("select id from contacts where entity_id = %s and lower(email) = %s", (eid, email))
    got = cur.fetchone()
    return str(got["id"]) if got else None


def main_():
    offline()
    api()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back; nothing sent)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
