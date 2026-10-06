#!/usr/bin/env python3
"""test_lcx_services.py -- the LCX Services project: one email offering every LCX service (2026-10-06).

    python tools/test_lcx_services.py

The owner: "Under docs there is lcx services i wanna build outreach a single one offering all these
services", then chose a new project like Universal (Apollo search, Write email), TVF's Mumbai address
under it, and sending once approved. Checked:

  * the repo's config: the email offers all 18 services on the sheet (docs/LCX Services.pdf), passes
    the compose checks, ends over TVF's address, sends from the approver, is not paused; the
    generated SQL is the JSON's
  * the page is handed that email to start the Write email box from (Universal is handed none)
  * approving it sends it, rendered for each person, signed by the writer
  * the Apollo search page works on the project it shows (?project=): searches and saves land
    there and nowhere else, a project without the page is refused, and a page that names no project
    keeps the old behaviour (the cookie's project if it has the page, else Universal)
  * a lead with nobody at it points to Apollo search, as in Universal

The real app runs in-process against the real database inside ONE transaction that is rolled back,
as tools/test_compose.py does: throwaway projects, people and leads, then ROLLBACK. Apollo is never
called (saving companies is free and local) and nothing is sent. Exit code 1 on any failure.
"""
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
import explain  # noqa: E402
import gen_segment_sql  # noqa: E402
import outreach_compose  # noqa: E402

RESULTS = []
# the 18 services on docs/LCX Services.pdf, by the names the sheet gives them
SERVICES = ["Reel Forge", "Airbnb / Property Content", "AI VFX + Animation", "Audiobooks and Audio Web Shows",
            "AI Video for Brands", "AI Real Estate Visualisation", "Explainer Videos", "Shop Display Videos",
            "AI UGC Product Videos", "AI Podcasts / Audio Content", "Virtual Tours for Schools",
            "AI Reality Experiences", "Creator × Brand Marketplace", "Local Business Tech and Automation",
            "AI Business Assistant", "AI Simulations for Training", "AI Fashion Stylist", "AI Onboarding Employee"]


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


def main_():
    cfg = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
    uni = json.loads((ROOT / "config" / "segment.universal.json").read_text(encoding="utf-8"))
    o, start = cfg["outreach"], cfg["outreach"]["compose_start"]

    # ------------------------------------------------------------------ the config
    print("-- the repo's config")
    check("a new project like Universal: Apollo search, Write email, no drafts",
          (cfg["ui"]["search_page"], o["compose"], "templates" in o, cfg["ui"]["project_name"]),
          ("apollo", True, False, "LCX Services"))
    check("  it sends from the approver's own address, and is not paused",
          (o["send_from"], "sending_paused" in o), ("approver", False))
    check("  TVF's Mumbai address goes under it (the owner's choice)",
          o["sender"]["postal_address"], uni["outreach"]["sender"]["postal_address"])
    check("  the footer carries the address and the way out",
          ("{{postal_address}}" in o["footer"]["text"], "no thanks" in o["footer"]["text"]), (True, True))
    check("the services email passes the checks an approval makes", outreach_compose.check_text(start["subject"], start["body"]), None)
    check("  it offers every one of the 18 services on the sheet", [s for s in SERVICES if "- %s: " % s not in start["body"]], [])
    check("  in the sheet's three groups", [g for g in ("1. Repurposing as a Service:", "2. AI Asset Creation:",
                                                         "3. Tech Solutions:") if g not in start["body"]], [])
    check("  it greets the person and names their company",
          (start["body"].startswith("Hi {{first_name}},"), "{{company}}" in start["subject"]), (True, True))
    check("the generated SQL is the JSON's", gen_segment_sql.render("lcx-services", cfg),
          (ROOT / "sql" / "03f_segment_lcx_services.sql").read_text(encoding="utf-8"))

    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    kicks = []
    main._scheduler.kick_outreach = lambda seg, trigger="manual": kicks.append((seg, trigger))
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)

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
        lx, un, no = "zz-lcxs-" + tag, "zz-uni-" + tag, "zz-noapollo-" + tag
        lx_id, un_id = project(lx, cfg), project(un, uni)
        plain = json.loads(json.dumps(cfg))
        plain["ui"].pop("search_page")
        plain["ui"]["default_route"] = "board"
        no_id = project(no, plain)
        main._SEG_CACHE.update(at=0.0, rows=[])

        email = "zz-lcxs-%s@example.com" % tag
        pw = bcrypt.hashpw(b"zz", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                    (email, pw, "Asha Rao", "Partnerships"))
        session = auth.make_cookie(email, pw)

        def as_(slug):
            return {auth.COOKIE: session, "tvf_segment": slug}

        # -------------------------------------------------------------- what the page is handed
        print("\n-- what the page is handed")
        seg = call("GET", "/api/segment", cookies=as_(lx)).json()
        pol = seg["outreach_policy"]
        check("LCX Services: the Write email box starts from the services email",
              pol.get("compose_start"), {"subject": start["subject"], "body": start["body"]})
        check("  emails are written, never drafted", (pol["compose"], pol["drafts"]), (True, False))
        check("  with its own search page and name", (seg["ui"]["search_page"], seg["ui"]["project_name"], seg["ui"]["key_prefix"]),
              ("apollo", "LCX Services", "LXS"))
        check("Universal: the box starts from the greeting, as before",
              call("GET", "/api/segment", cookies=as_(un)).json()["outreach_policy"].get("compose_start"), None)
        check("a project that writes no email is handed none",
              call("GET", "/api/segment", cookies=as_("us-production-houses")).json()["outreach_policy"].get("compose_start"), None)
        names = [s["project_name"] for s in call("GET", "/api/segments", cookies=as_(lx)).json()["segments"]]
        check("  and LCX Services is in the projects menu", "LCX Services" in names, True)

        # -------------------------------------------------------------- writing the services email
        print("\n-- sending the services email")

        def lead(seg_id, name, contact):
            t = uuid.uuid4().hex[:6]
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'apollo',"
                        " 'ready_for_review') returning id", (seg_id, name, "zz-%s.example" % t))
            eid = str(cur.fetchone()[0])
            if contact:
                full, local = contact
                cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                            " (%s, %s, %s, 'valid', 'apollo')", (eid, full, "%s@zz-%s.example" % (local, t)))
            return eid

        a = lead(lx_id, "ZZ Harbour Realty %s" % tag, ("Priya Shah", "priya"))
        b = lead(lx_id, "ZZ Bloom Salons %s" % tag, (None, "hello"))
        r = call("POST", "/api/outreach/compose", cookies=as_(lx), json={"ids": [a, b], "subject": start["subject"], "body": start["body"]})
        j = r.json()
        check("approving the services email as it is: 2 approved", (r.status_code, j.get("approved")), (200, 2))
        cur.execute("select e.id::text, o.subject, o.body, o.status, o.approval_mode, o.approved_by from outreach o"
                    " join entities e on e.id = o.entity_id where e.segment_id = %s order by e.name", (lx_id,))
        rows = {x[0]: x[1:] for x in cur.fetchall()}
        sa, sb = rows.get(a), rows.get(b)
        check("  one approved email each, written here, approved by the writer",
              [(x[2], x[3], x[4]) for x in (sb, sa)], [("approved", "compose", email)] * 2)
        check("  the subject names their company", sa[0], "18 things LCX can do for ZZ Harbour Realty %s" % tag)
        check("  a named person is greeted by name; a shared inbox, 'there'",
              (sa[1].split("\n")[0], sb[1].split("\n")[0]), ("Hi Priya,", "Hi there,"))
        check("  every service is in what they receive", [s for s in SERVICES if "- %s: " % s not in sa[1]], [])
        check("  their company is filled in", "should be useful to ZZ Harbour Realty %s:" % tag in sa[1], True)
        check("  signed by the writer, over TVF's address, with the way out",
              ("Warm regards,\nAsha Rao\nPartnerships\n\nContagious Online Media Network" in sa[1], sa[1].rstrip().endswith(
                  "you won't hear from me again.")), (True, True))
        check("  no field is left unfilled", "{{" in sa[0] + sa[1] + sb[0] + sb[1], False)
        check("  and the send is started at once (approved means sent)", kicks[-1:], [(lx, "manual")])

        # -------------------------------------------------------------- someone who answered us elsewhere
        print("\n-- an address that answered us in another project gets nothing new")

        def answered(local, triage, bounce=False):
            """An email from the Universal project to local@..., and their reply (triage), or a bounce."""
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
            # the same address, a lead of LCX Services (in capitals: an address is the same whatever its case)
            lid = lead(lx_id, "ZZ Again %s" % t, None)
            cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                        " (%s, 'Ravi Kumar', %s, 'valid', 'apollo')", (lid, addr.upper()))
            return lid

        no_thanks, unread, auto, bounced = (answered("ravi", "negative"), answered("mohan", None),
                                            answered("ooo", "neutral"), answered("gone", None, bounce=True))
        r = call("POST", "/api/outreach/compose/check", cookies=as_(lx), json={"ids": [no_thanks, unread, auto, bounced]})
        why = {s["id"]: s["reason"] for s in r.json()["skipped"]}
        check("they said no thanks to Universal's email: skipped here",
              why.get(no_thanks), "this address has replied to an earlier email from us: answer them in that thread")
        check("  a reply nobody has read yet counts too", why.get(unread),
              "this address has replied to an earlier email from us: answer them in that thread")
        check("  an auto-reply does not: they can be written to", ([x["id"] for x in r.json()["ready"]], auto in why), ([auto], False))
        check("  an address that bounced: skipped", why.get(bounced), "this address bounced an earlier email from us")
        r = call("POST", "/api/outreach/compose", cookies=as_(lx), json={"ids": [no_thanks, bounced], "subject": start["subject"],
                                                                        "body": start["body"]})
        check("  approving them writes nothing", (r.status_code, r.json().get("approved")), (200, 0))
        cur.execute("select count(*) from outreach where entity_id = any(%s::uuid[])", ([no_thanks, bounced],))
        check("  not a row", cur.fetchone()[0], 0)

        # -------------------------------------------------------------- the search page's project
        print("\n-- the Apollo search page works on the project it shows")
        sname = "ZZ salons " + tag
        body = {"name": sname, "kind": "companies", "filters": {"q_organization_keyword_tags": ["salon"]}}
        r = call("POST", "/api/universal/searches?project=" + lx, cookies=as_(lx), json=body)
        check("save a search in LCX Services: 200", r.status_code, 200)
        cur.execute("select segment_id from saved_searches where lower(name) = lower(%s)", (sname,))
        check("  it is kept in LCX Services", [x[0] for x in cur.fetchall()], [lx_id])
        listed = lambda slug, cookie: [s["name"] for s in call("GET", "/api/universal/searches?project=" + slug,  # noqa: E731
                                                               cookies=as_(cookie)).json().get("searches", [])]
        check("  listed there", sname in listed(lx, lx), True)
        check("  and not in Universal's list", sname in listed(un, un), False)

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
        r = call("POST", "/api/universal/searches?project=" + no, cookies=as_(no), json=dict(body, name=sname + " x"))
        check("  nor a search kept there", r.status_code, 404)
        check("  nor its status asked", call("GET", "/api/universal/status?project=" + no, cookies=as_(no)).status_code, 404)
        r = call("POST", "/api/universal/save?project=" + "zz-nope-" + tag, cookies=as_(lx), json={"kind": "companies",
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

        # -------------------------------------------------------------- a lead with nobody at it
        print("\n-- a lead with nobody at it")
        row = {"id": "x", "name": "ZZ Empty Co", "domain": None, "status": "ready_for_review", "metadata": {},
               "fit_score": None, "score_breakdown": None}
        ex = explain.explain_lead(lx, cfg, row, [], None)
        check("points to Apollo search, as in Universal", ex["analysis"]["next_step"],
              "Find a way in: save a person at it from Apollo search.")
        check("  and says what was tried is Apollo, not its website", ex["contact_routes"]["tried"],
              ["Saved from an Apollo company search; nobody at it has been revealed yet."])
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rolled back; nothing sent)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
