#!/usr/bin/env python3
"""test_compose.py -- writing one email to the leads a person picked (the Universal project, 2026-09-27).

    python tools/test_compose.py

The real app runs in-process (FastAPI's TestClient) against the real database inside ONE transaction
that is rolled back at the end, the way tools/test_api.py does it: a throwaway project with the
Universal config from the repo (outreach.compose on), throwaway people and leads, then ROLLBACK.
Nothing is sent: the scheduler never starts and its kick is recorded instead.

Checked: the page's question (who it goes to, how each is greeted, who is skipped and why) changes
nothing; approving makes exactly one approved email per company, rendered for each person with the
writer's own sign-off and the project's footer, approval_mode 'compose', and shortlists a lead that
was still in To review; every refusal (unknown field, empty or two-line subject, no name and title,
a project without compose) writes nothing; one email per company and per inbox holds across writes.
With the repo's sending window (owner, 2026-10-12): the page's question names each recipient's
window and no minute; approving draws each one's own second and keeps it on the email.
Exit code 1 on any failure.
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

RESULTS = []


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
        cfg = json.loads((ROOT / "config" / "segment.universal.json").read_text(encoding="utf-8"))
        check("the repo's Universal config lets a person write emails", (cfg["outreach"]["compose"],
              cfg["outreach"]["send_from"], "outreach" in cfg["ui"]["hide_routes"]), (True, "approver", False))
        slug = "zz-compose-" + uuid.uuid4().hex[:6]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ compose', 'company', %s)"
                    " returning id", (slug, json.dumps(cfg)))
        seg_id = cur.fetchone()[0]
        other = "zz-compose-other-" + uuid.uuid4().hex[:6]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ other', 'company', %s)"
                    " returning id", (other, json.dumps(cfg)))
        other_id = cur.fetchone()[0]

        def person(name=None, title=None):
            email = "zz-compose-%s@example.com" % uuid.uuid4().hex[:6]
            pw = bcrypt.hashpw(b"zz", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s, %s)",
                        (email, pw, name, title))
            return email, {auth.COOKIE: auth.make_cookie(email, pw), "tvf_segment": slug}

        writer, as_writer = person("Asha Rao", "Partnerships")
        nameless, as_nameless = person()

        def lead(status="ready_for_review", contact=("Elena Moss", "elena"), seg=seg_id, name=None):
            tag = uuid.uuid4().hex[:6]
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'apollo', %s)"
                        " returning id", (seg, name or ("ZZ Studio %s" % tag), "zz-%s.example" % tag, status))
            eid = str(cur.fetchone()[0])
            if contact:
                full, local = contact
                cur.execute("insert into contacts (entity_id, full_name, email, email_status, source) values"
                            " (%s, %s, %s, 'valid', 'apollo')", (eid, full, "%s@zz-%s.example" % (local, tag)))
            return eid

        def status_of(eid):
            cur.execute("select status from entities where id = %s", (eid,))
            return cur.fetchone()[0]

        def openers(eid):
            cur.execute("select status, approval_mode, approved_by, subject, body from outreach"
                        " where entity_id = %s and direction = 'outbound' order by created_at", (eid,))
            return cur.fetchall()

        a = lead()                                                   # To review, a named person
        b = lead("shortlisted", contact=(None, "info"))              # shortlisted, a shared inbox: no first name
        c = lead(contact=None)                                       # no address
        d = lead("contacted")                                        # already contacted
        e = lead("rejected")                                         # rejected
        f = lead()                                                   # has an email from us already
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status)"
                    " select %s, id, 't', 'Hi', 'Body', 'approved' from contacts where entity_id = %s", (f, f))
        g1 = lead(name="ZZ Twin Pictures")                            # two leads, one company name
        g2 = lead(name="ZZ Twin Pictures")
        x = lead(seg=other_id)                                       # another project's lead
        ids = [a, b, c, d, e, f, g1, g2, x]

        # ---------------------------------------------------------------- asking first
        print("-- the page asks first")
        r = call("POST", "/api/outreach/compose/check", cookies=as_writer, json={"ids": ids})
        j = r.json()
        check("the check answers", r.status_code, 200)
        check("  who it goes to", sorted(x["id"] for x in j["ready"]), sorted([a, b, g1]))
        byid = {x["id"]: x for x in j["ready"]}
        check("  a named person is greeted by first name", (byid[a]["first_name"], byid[a]["named"]), ("Elena", True))
        check("  a shared inbox is greeted 'there', and it says so", (byid[b]["first_name"], byid[b]["named"]), ("there", False))
        reasons = {s["id"]: s["reason"] for s in j["skipped"]}
        check("  no address: skipped", reasons.get(c), "no email address to write to")
        check("  already contacted: skipped", reasons.get(d), "already contacted")
        check("  rejected: skipped", reasons.get(e), "it was rejected")
        check("  an email from us already: skipped", reasons.get(f), "it already has an email from us (approved)")
        check("  a second company of the same name: skipped", reasons.get(g2), "a company of the same name already has a first email from us")
        check("  another project's lead: skipped", reasons.get(x), "not a lead of this project")
        check("  the footer is the writer's own sign-off without a postal address",
              (j["footer"].startswith("Warm regards,\nAsha Rao\nPartnerships"), "Contagious Online Media" in j["footer"],
               "no thanks" in j["footer"]), (True, False, True))
        check("  and what approving will do: no Gmail linked to them yet", (j["can_send"], j["mailboxes"]), (False, []))
        check("  asking changed nothing: the To review lead is still in To review", status_of(a), "ready_for_review")
        check("  and nothing was written", (openers(a), openers(b)), ([], []))
        # the sending window (owner, 2026-10-12): the page names the window approving aims at, never a minute
        check("  each says the 10:00-10:30 on its recipient's clock that approving aims at, and why that zone",
              all(x["window"]["enabled"] and "10:00-10:30" in x["window"]["window_label"] and x["window"]["send_tz_reason"]
                  and "schedule" not in x for x in j["ready"]), True)
        r = call("POST", "/api/outreach/compose/check", cookies=as_writer, json={"ids": [a], "body": "Hi {{last_name}}"})
        check("  an unknown field is caught while writing", (r.status_code, "{{last_name}}" in r.json()["detail"]), (400, True))

        # ---------------------------------------------------------------- refusals write nothing
        print("\n-- what is refused")
        good = {"ids": [a, b], "subject": "Hello from TVF, {{company}}",
                "body": "Hi {{first_name}},\n\nWe make shows in India, and {{company}}'s work caught our eye."}
        for name, body, code in (("an unknown field", dict(good, body="Hi {{nickname}},\n\nx"), 400),
                                 ("an empty subject", dict(good, subject="  "), 400),
                                 ("a two-line subject", dict(good, subject="Hello\nthere"), 400),
                                 ("an empty email", dict(good, body="   "), 400),
                                 ("no leads", dict(good, ids=[]), 400)):
            r = call("POST", "/api/outreach/compose", cookies=as_writer, json=body)
            check("%s: %d" % (name, code), r.status_code, code)
        for name, ids in (("ids that are not ids", ["not-a-lead", "1; drop table x"]), ("ids that are not a list", "abc"),
                          ("ids that are a number", 7)):
            r = call("POST", "/api/outreach/compose", cookies=as_writer, json=dict(good, ids=ids))
            check("%s: 400, never a server error" % name, r.status_code, 400)
        r = call("POST", "/api/outreach/compose/check", cookies=as_writer, json={"ids": [a, "junk"]})
        check("  a mangled id among good ones is just skipped", ([x["id"] for x in r.json()["ready"]],
              [s["reason"] for s in r.json()["skipped"]]), ([a], ["not a lead of this project"]))
        r = call("POST", "/api/outreach/compose", cookies=as_nameless, json=good)
        check("someone with no name and title yet: 409, they sign it", (r.status_code, "name and title" in r.json()["detail"]), (409, True))
        tvf = dict(as_writer, tvf_segment="us-production-houses")
        check("a project without it: 403", call("POST", "/api/outreach/compose", cookies=tvf, json=good).status_code, 403)
        check("  and nothing was written by any of them", (openers(a), openers(b), status_of(a)), ([], [], "ready_for_review"))

        # ---------------------------------------------------------------- approving
        print("\n-- approving")
        r = call("POST", "/api/outreach/compose", cookies=as_writer, json=good)
        j = r.json()
        check("approved: one email for each of the two", (r.status_code, j["approved"]), (200, 2))
        check("  sent on at once (the scheduler's kick)", kicks[-1:], [(slug, "manual")])
        check("  each drew its own second in its recipient's window on approval, in the page's words",
              all(x.get("schedule") and x["schedule"]["send_label"] and x["schedule"]["send_tz"] for x in j["ready"]), True)
        cur.execute("select count(*) from outreach where entity_id = any(%s::uuid[]) and direction = 'outbound'"
                    " and status = 'approved' and send_after is not null and send_after < send_before"
                    " and send_after > now()", ([a, b],))
        check("  and keeps it on the email (send_after, sql/34), in the future", cur.fetchone()[0], 2)
        oa = openers(a)
        check("  one approved email for the To review lead, written here", [(o[0], o[1], o[2]) for o in oa],
              [("approved", "compose", writer)])
        check("  and that lead is shortlisted by being written to", status_of(a), "shortlisted")
        subj, body = oa[0][3], oa[0][4]
        cur.execute("select name from entities where id = %s", (a,))
        aname = cur.fetchone()[0]
        check("  its subject, filled in", subj, "Hello from TVF, %s" % aname)
        check("  its body greets Elena and ends with Asha's sign-off and opt-out",
              (body.startswith("Hi Elena,\n\nWe make shows in India, and %s's work caught our eye." % aname),
               body.endswith("you won't hear from me again."), "\nAsha Rao\nPartnerships\n" in body), (True, True, True))
        ob = openers(b)
        check("  the shared inbox reads 'Hi there,'", ob[0][4].startswith("Hi there,"), True)
        r = call("GET", "/api/outreach?folder=outbox", cookies=as_writer)
        check("  both wait in Approved (no Gmail yet), beside the one planted earlier",
              sorted(x["entity_id"] for x in r.json()["rows"]), sorted([a, b, f]))
        msg = [x for x in r.json()["rows"] if x["entity_id"] == a][0]
        check("  and say how they were approved", (msg["approval_mode"], msg["approved_by_name"]), ("compose", "Asha Rao"))
        check("  and when each goes out, for the Goes out column", bool(msg.get("schedule") and msg["schedule"]["send_short"]), True)

        print("\n-- once only")
        r = call("POST", "/api/outreach/compose", cookies=as_writer, json=good)
        j = r.json()
        check("writing to the same two again: nothing approved", (r.status_code, j["approved"]), (200, 0))
        check("  each skipped: an email from us already", sorted(s["reason"] for s in j["skipped"]),
              ["already contacted", "it already has an email from us (approved)"]
              if status_of(b) == "contacted" else ["it already has an email from us (approved)"] * 2)
        check("  still one email each", (len(openers(a)), len(openers(b))), (1, 1))

        print("\n-- the page's picture of the project")
        r = call("GET", "/api/segment", cookies=as_writer)
        pol = r.json()["outreach_policy"]
        check("compose on, no Drafts folder (nothing is drafted)", (pol["compose"], pol["drafts"]), (True, False))
        check("  its sending window, for the page's words", (pol["send_window"] or {}).get("start"), "10:00")
        check("  the Outreach page is not hidden", "outreach" in r.json()["ui"].get("hide_routes", []), False)
        r = call("GET", "/api/segment", cookies=tvf)
        pol = r.json()["outreach_policy"]
        check("US Production Houses: no compose, Drafts as ever", (pol["compose"], pol["drafts"]), (False, True))
    finally:
        conn.rollback()
        conn.close()
    fails = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rolled back; nothing sent)" % (fails, len(RESULTS)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main_())
