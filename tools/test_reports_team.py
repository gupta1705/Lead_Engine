#!/usr/bin/env python3
"""test_reports_team.py -- Reports, Team (app/team_report.py) and Outreach, In conversation (owner, 2026-10-27), as a
table.

    python tools/test_reports_team.py

The real app in-process (FastAPI's TestClient) against the real database inside ONE transaction that is rolled back,
with a project of its own and two people of its own, so every number below is known exactly. Checked:

  * Team: first emails per person within the span (today, 7, 30, 90 days, all time), credited to who approved them;
    a follow-up credited to whose thread it is; a company that wrote back counted once, an auto-reply or bounce
    notice not at all; reply, positive and bounce rates; the typical time to a reply; approved and still to go; a
    bar per day that adds up; this project or all projects; a person with nothing sent still listed
  * In conversation: a company per row that wrote back with a real reply (its latest), not a bounce notice, not one
    marked Not interested, not one rejected since; who reached out and how long the thread is; counted on the tab;
    the API's in_conversation folder lists the same
Exit code 1 on any failure.
"""
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
os.environ["SESSION_SECRET"] = "zz-team-test-" + uuid.uuid4().hex

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


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


def main_():
    import main
    import auth
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        for f in ("43_api_keys.sql", "44_api_approve_oauth.sql"):
            cur.execute((ROOT / "sql" / f).read_text(encoding="utf-8"))
        tag = uuid.uuid4().hex[:6]
        slug = "zz-team-" + tag
        cfg = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
        cfg.pop("sourcing", None)
        cfg["outreach"].pop("send_window", None)
        cfg.setdefault("ui", {})["project_name"] = "ZZ Team"     # not the copied project's own name
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ Team', 'company',"
                    " %s, true) returning id", (slug, json.dumps(cfg)))
        seg = cur.fetchone()["id"]
        main._SEG_CACHE.update(at=0.0, rows=[])

        def person(name):
            email = "zz-team-%s-%s@example.com" % (name.lower(), tag)
            h = bcrypt.hashpw(b"zz-team-password", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', %s,"
                        " 'Partnerships')", (email, h, name))
            return email, {auth.COOKIE: auth.make_cookie(email, h), "tvf_segment": slug}
        ann, ck = person("Ann")
        bob, _ = person("Bob")
        cat, _ = person("Cat")                      # sends nothing: still listed

        def lead(i):
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s,"
                        " 'test', 'contacted') returning id", (seg, "ZZ Show %d %s" % (i, tag), "zz%d-%s.example" % (i, tag)))
            e = cur.fetchone()["id"]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, %s, %s,"
                        " 'valid') returning id", (e, "Host %d" % i, "host%d@zz%d-%s.example" % (i, i, tag)))
            return e, cur.fetchone()["id"]

        def sent(e, c, by, ago, step=0, parent=None, stopped=None):
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                        " approved_at, sent_at, sequence_step, parent_id, stopped_reason, sender_address,"
                        " gmail_thread_id, gmail_message_id) values (%s, %s, 'zz', 'Hello', 'Hello', 'sent', %s,"
                        " now() - %s::interval, now() - %s::interval, %s, %s, %s, %s, %s, %s) returning id",
                        (e, c, by, ago, ago, step, parent, stopped, by, "zz-t-" + uuid.uuid4().hex,
                         "zz-m-" + uuid.uuid4().hex))
            return cur.fetchone()["id"]

        def reply(e, ago, triage=None, status="received"):
            cur.execute("insert into outreach (entity_id, direction, subject, body, status, triage, created_at)"
                        " values (%s, 'inbound', 'Re: Hello', 'Thanks!', %s, %s, now() - %s::interval) returning id",
                        (e, status, triage, ago))
            return cur.fetchone()["id"]
        e1, c1 = lead(1)
        o1 = sent(e1, c1, ann, "2 days")
        r1 = reply(e1, "45 hours")                                 # 3 hours after the first email
        sent(e1, c1, bob, "1 day", step=1, parent=o1)               # a follow-up: Ann's thread, approved by Bob
        e2, c2 = lead(2)
        sent(e2, c2, ann, "1 day", stopped="bounced: the address rejected the email")
        reply(e2, "23 hours", triage="neutral", status="triaged")   # a bounce notice: not a reply
        e3, c3 = lead(3)
        sent(e3, c3, ann, "40 days")
        e4, c4 = lead(4)
        sent(e4, c4, bob, "1 minute")
        r4 = reply(e4, "30 seconds", triage="positive", status="triaged")
        e5, c5 = lead(5)
        sent(e5, c5, bob, "3 days")
        reply(e5, "2 days", triage="negative", status="triaged")    # Not interested
        e6, c6 = lead(6)                                           # approved, still to go
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                    " approved_at) values (%s, %s, 'zz', 'Hi', 'Hi', 'approved', %s, now())", (e6, c6, bob))

        def team(period, scope="project"):
            client.cookies.clear()
            r = client.get("/api/reports/team?period=%s&scope=%s" % (period, scope), cookies=ck)
            return r.status_code, r.json()

        print("-- Team")
        st, d = team("7d")
        by = {p["account"]: p for p in d["people"]}
        a, b = by[ann], by[bob]
        check("7 days: Ann's first emails, the company that wrote back, the bounce",
              (st, a["sent"], a["replied"], a["reply_rate"], a["bounced"], a["bounce_rate"]),
              (200, 2, 1, 50.0, 1, 50.0))
        check("  her follow-up is hers, though Bob approved it", (a["followups"], b["followups"]), (1, 0))
        check("  the typical time to a reply: 3 hours", a["median_reply_hours"], 3.0)
        check("  Bob: two sent, one positive, one not interested, one approved to go",
              (b["sent"], b["replied"], b["positive"], b["negative"], b["approved_waiting"]), (2, 2, 1, 1, 1))
        check("  Cat sent nothing and is still listed", (by[cat]["sent"], by[cat]["reply_rate"]), (0, None))
        check("  a bar per day, adding up to what was sent", (len(d["buckets"]), sum(a["series"]), d["bucket"]),
              (8, 2, "day"))
        check("  everyone: the totals", (d["totals"]["sent"], d["totals"]["replied"], d["totals"]["followups"],
                                          d["totals"]["approved_waiting"]), (4, 3, 1, 1))
        check("  most sent first", [p["account"] for p in d["people"]][:2] in ([ann, bob], [bob, ann]), True)
        st, d = team("90d")
        check("90 days: the email of 40 days ago counts", {p["account"]: p["sent"] for p in d["people"]}[ann], 3)
        st, d = team("30d")
        check("30 days: it does not", {p["account"]: p["sent"] for p in d["people"]}[ann], 2)
        st, d = team("today")
        tb = {p["account"]: p for p in d["people"]}
        check("today: only Bob's email of a minute ago, and no bars", (tb[bob]["sent"], tb[ann]["sent"], d["buckets"]),
              (1, 0, []))
        st, d = team("all", scope="all")
        aa = {p["account"]: p for p in d["people"]}[ann]
        check("all projects: the project is named beside her count", [(x["name"], x["sent"]) for x in aa["projects"]],
              [("ZZ Team", 3)])
        st, d = team("forever")
        check("a span it does not know: refused", st, 400)

        print("\n-- In conversation")

        def folder(f):
            client.cookies.clear()
            return client.get("/api/outreach?folder=%s" % f, cookies=ck).json()
        d = folder("conversation")
        ids = [r["id"] for r in d["rows"]]
        check("companies that wrote back for real, their latest reply: not the bounce, not Not interested",
              sorted(ids), sorted([str(r1), str(r4)]))
        row = next(r for r in d["rows"] if r["id"] == str(r1))
        check("  who reached out, and how long the thread is", (row["reached_by"], row["thread_messages"]), (ann, 3))
        check("  counted on the tab", d["counts"]["conversation"], 2)
        r5 = reply(e1, "1 hour")
        d = folder("conversation")
        check("a newer reply from the same company replaces it: still one row",
              [r["id"] for r in d["rows"] if r["entity_id"] == str(e1)], [str(r5)])
        cur.execute("update entities set status = 'rejected' where id = %s", (e1,))
        check("rejected since: out of it", [r["entity_id"] for r in folder("conversation")["rows"]], [str(e4)])
        client.cookies.clear()
        r = client.post("/api/keys", cookies=ck, json={"name": "zz"})
        key = r.json()["key"]
        client.cookies.clear()
        r = client.get("/api/v1/projects/%s/emails?folder=in_conversation" % slug,
                       headers={"Authorization": "Bearer " + key})
        check("the API's in_conversation folder lists the same",
              (r.status_code, [x["lead_id"] for x in r.json()["rows"]], r.json()["counts"]["in_conversation"]),
              (200, [str(e4)], 1))
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
