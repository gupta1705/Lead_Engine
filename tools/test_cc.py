#!/usr/bin/env python3
"""test_cc.py -- copying someone on an email from the app (owner, 2026-10-22: "add a feature to cc someone from the
software itself. Make default cc to the email amritanshv@lightscameraexperiment.com and obvio make a toggle to switch
that off"), as a table.

    python tools/test_cc.py

The real app runs in-process (FastAPI's TestClient) against the real database inside ONE transaction that is rolled
back: a throwaway project copied from LCX Clipping, a throwaway login, drafts. Checked:

  * the page learns the project's default CC (outreach.default_cc) and every draft shows it until someone changes it
  * the CC switch: switching the default off stores [] (nobody), switching it back, adding someone, removing them,
    null going back to the project's default; anything that is not an email address refused; only a draft
  * approving freezes the list (sql/39): a draft left alone is approved with the project's default, one switched
    off stays switched off, and changing the default later changes no approved email
  * a sent email shows exactly who it was copied to (nothing for one sent before CC existed)

Sending itself (the Cc header, the recipient never copied, the list recorded) is checked in tools/test_send.py.
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
os.environ["SESSION_SECRET"] = "zz-cc-test-" + uuid.uuid4().hex

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import main  # noqa: E402
import auth  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
DEFAULT = "amritanshv@lightscameraexperiment.com"


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-80s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:100]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:100])))


class TxConn:
    """The app's pooled connection, replaced by the test's one transaction (a savepoint per request)."""

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
    main._scheduler.kick_outreach = lambda seg, trigger="manual": None
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))
    cur = conn.cursor()
    try:
        tag = uuid.uuid4().hex[:6]
        slug = "zz-cc-" + tag
        cur.execute("select config from segments where slug = 'lcx-clipping'")
        cfg = cur.fetchone()[0]
        cfg["outreach"]["default_cc"] = [DEFAULT]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ cc', 'company', %s)"
                    " returning id", (slug, json.dumps(cfg)))
        seg_id = cur.fetchone()[0]
        email = "zz-cc-%s@example.com" % tag
        h = bcrypt.hashpw(b"zz-cc-password", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', 'Cee', 'BD')",
                    (email, h))
        me = {auth.COOKIE: auth.make_cookie(email, h), "tvf_segment": slug}
        main._SEG_CACHE.update(at=0.0, rows=[])

        def call(method, url, **kw):
            client.cookies.clear()
            return client.request(method, url, cookies=me, **kw)

        def draft(status="drafted", cc=None):
            cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                        " (%s, %s, %s, 'test', 'shortlisted') returning id",
                        (seg_id, "ZZ cc " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay', %s, 'valid')"
                        " returning id", (eid, "kay.%s@zz-cc.example" % uuid.uuid4().hex[:6]))
            cid = cur.fetchone()[0]
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, cc)"
                        " values (%s, %s, 't', 'Hello', 'Hello Kay,\n\nBody', %s, %s::text[]) returning id",
                        (eid, cid, status, cc))
            return str(cur.fetchone()[0])

        def stored(oid):
            cur.execute("select cc from outreach where id = %s", (oid,))
            return cur.fetchone()[0]

        def shown(oid):
            r = call("GET", "/api/outreach/%s" % oid)
            return r.json().get("cc") if r.status_code == 200 else r.status_code

        def patch(oid, value):
            return call("PATCH", "/api/outreach/%s" % oid, json={"cc": value}).status_code

        print("-- the default CC, and the switch to turn it off (owner, 2026-10-22)")
        r = call("GET", "/api/segment")
        if r.status_code != 200:
            print("  /api/segment answered %s: %s" % (r.status_code, r.text[:200]))
        seg = r.json() if r.status_code == 200 else {"outreach_policy": {}}
        check("the page learns the project's default CC", seg["outreach_policy"]["default_cc"], [DEFAULT])
        d = draft()
        r = call("GET", "/api/outreach/%s" % d).json()
        check("a draft nobody touched: copied to the default (and told it is the default)",
              (r["cc"], r["cc_default"], stored(d)), ([DEFAULT], [DEFAULT], None))
        check("switch the default off: saved as nobody", (patch(d, []), stored(d), shown(d)), (200, [], []))
        check("switch it back on", (patch(d, [DEFAULT]), shown(d)), (200, [DEFAULT]))
        check("add someone: lower-cased, kept once",
              (patch(d, [DEFAULT, "Partner@Example.com", "partner@example.com "]), shown(d)),
              (200, [DEFAULT, "partner@example.com"]))
        check("remove them again", (patch(d, [DEFAULT]), shown(d)), (200, [DEFAULT]))
        check("not an email address: refused, nothing changed",
              (patch(d, ["not an address"]), patch(d, ["a@b"]), patch(d, "x@y.com"), shown(d)),
              (400, 400, 400, [DEFAULT]))
        check("  nor more than 10 addresses", patch(d, ["p%d@example.com" % i for i in range(11)]), 400)
        check("null: back to the project's default", (patch(d, None), stored(d), shown(d)), (200, None, [DEFAULT]))
        r = call("PATCH", "/api/outreach/%s" % d, json={"subject": "Hi again"})
        check("editing the subject alone leaves the CC alone", (r.status_code, stored(d)), (200, None))

        print("\n-- approving freezes the list it was approved with (sql/39)")
        left, off = draft(), draft()
        patch(off, [])
        cur.execute("update outreach set status = 'approved', approved_at = now(), approved_by = %s"
                    " where id = any(%s::uuid[])", (email, [left, off]))
        check("left alone: approved with the project's default", stored(left), [DEFAULT])
        check("switched off: approved with nobody", stored(off), [])
        check("an approved email's CC cannot be changed any more", patch(left, []), 409)
        cur.execute("update segments set config = jsonb_set(config, '{outreach,default_cc}', '[\"new@example.com\"]')"
                    " where id = %s", (seg_id,))
        main._SEG_CACHE.update(at=0.0, rows=[])
        check("changing the default later changes no approved email", (shown(left), shown(off)), ([DEFAULT], []))
        check("  but a draft still on the default follows it", shown(d), ["new@example.com"])

        print("\n-- a sent email shows who it was copied to")
        before = draft(status="sent")
        check("one sent before CC existed: nobody", shown(before), [])
        went = draft(status="sent", cc=[DEFAULT])
        check("one sent with a copy: that address", shown(went), [DEFAULT])
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
