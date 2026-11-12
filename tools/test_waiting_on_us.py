#!/usr/bin/env python3
"""test_waiting_on_us.py -- Waiting on us (sql/46; the owner, 2026-10-29: "Implement 6", build 6 of the outreach
research): which conversations wait for our answer, and for how long, as a table.

    python tools/test_waiting_on_us.py          (after python tools/run_sql.py sql/46_waiting_on_us.sql)

The real `outreach.py pull` against the real database inside ONE transaction that is rolled back, with a Gmail that
answers from threads made up here, and no model. Checked:

  * the pull notes on each reply when it came (Gmail's date) and when our side first wrote in the thread after it:
    from this Gmail (SENT), or from another of our addresses (the project's CC); a draft is no answer; a second reply
    after our answer waits again; a reply read before sql/46 is filled in by the next pull
  * the five-minute look (--recent) reads a thread waiting on us even with nothing new in it, and only those
  * what waits: not a bounce notice, not a reply marked Negative, not one the model read as a no or an unsubscribe --
    unless a person marked it Positive
  * In conversation: the ones waiting on us first, the longest wait at the top, with since when; counted on the tab
  * Replies: each reply says whether it waits
  * answered another way, marked in its sheet: the company's waiting replies answered by that person; twice is refused
  * Team: the typical time to our answer, and how many wait on each person now
  * the daily reminder: the replies waiting a day for an answer, apart from those only unmarked
  * the API: waiting_on_us, waiting_since and the count
Exit code 1 on any failure.
"""
import argparse
import base64
import contextlib
import io
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-wait-test-" + uuid.uuid4().hex
os.environ["PUBLIC_BASE_URL"] = "https://leads.example.test"

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import dbconn  # noqa: E402
import outreach  # noqa: E402
import outreach_policy as pol  # noqa: E402
import reply_alert as ra  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


# ------------------------------------------------------------------ a Gmail made of threads
class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    """threads().get answers from .store; messages().list (the quick look) from .recent; what reply_alert asks
    (labels, modify, the From header, import) is recorded."""

    def __init__(self):
        self.store, self.recent, self.reads, self.imports = {}, set(), [], []

    def users(self):
        return self

    def threads(self):
        return Threads(self)

    def messages(self):
        return Messages(self)

    def labels(self):
        return Labels()


class Threads:
    def __init__(self, g):
        self.g = g

    def get(self, userId, id, format=None):
        def go():
            self.g.reads.append(id)
            return {"id": id, "messages": list(self.g.store[id])}
        return Call(go)


class Messages:
    def __init__(self, g):
        self.g = g

    def list(self, userId, q=None, maxResults=None, pageToken=None):
        return Call(lambda: {"messages": [{"id": "m", "threadId": t} for t in self.g.recent]})

    def modify(self, userId, id, body):
        return Call(lambda: {})

    def get(self, userId, id, format=None, metadataHeaders=None):
        return Call(lambda: {"payload": {"headers": [{"name": "From", "value": "Maya <maya@zz.example>"}]}})

    def import_(self, userId, body, **k):
        import email
        msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
        plain = next(p.get_payload(decode=True).decode("utf-8") for p in msg.walk() if p.get_content_type() == "text/plain")
        return Call(lambda: self.g.imports.append("Subject: %s\n%s" % (msg["Subject"], plain)) or {"id": "imp"})


class Labels:
    def list(self, userId):
        return Call(lambda: {"labels": [{"id": "Label_1", "name": ra.LABEL}]})


def message(mid, at, frm, subject="Re: 500+ clips per episode", labels=(), body="Sounds good, tell me more."):
    return {"id": mid, "labelIds": list(labels), "internalDate": str(int(at.timestamp() * 1000)),
            "payload": {"mimeType": "text/plain", "headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subject}],
                        "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}}


class TxDb:
    """dbconn.Db on the test's one transaction: every run() is a savepoint, nothing is committed."""

    def __init__(self, conn):
        self._conn = conn

    def __call__(self, url=None):
        return self

    def run(self, fn, on_reconnect=None):
        with self._conn.cursor() as cur:
            cur.execute("savepoint wait_step")
            try:
                out = fn(cur)
            except Exception:
                cur.execute("rollback to savepoint wait_step")
                raise
            cur.execute("release savepoint wait_step")
            return out

    def close(self):
        pass


class TxConnShim:
    def __init__(self, conn):
        self._c, self.closed = conn, 0
        with conn.cursor() as cur:
            cur.execute("savepoint api_req")

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


def pull(recent=False):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = outreach.cmd_pull(argparse.Namespace(recent=recent))
    return rc, out.getvalue()


def main_():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    db = TxDb(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    real = (dbconn.Db, outreach.user_gmail_service, outreach.SEGMENT, ra.read_reply)
    try:
        # sql/46 is applied live; running its ALTER TABLE here would lock outreach for the live app while this runs
        import mailbox_store as store
        tag = uuid.uuid4().hex[:6]
        slug = "zz-wait-" + tag
        cc = "cc.%s@zzmail.example" % tag
        cfg = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
        cfg.pop("sourcing", None)
        cfg.setdefault("ui", {})["project_name"] = "ZZ Waiting"
        cfg.setdefault("outreach", {})["default_cc"] = [cc]
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ Waiting',"
                    " 'company', %s, true) returning id", (slug, json.dumps(cfg)))
        seg = cur.fetchone()["id"]
        person = "zz-wait-ann-%s@example.com" % tag
        box_addr = "ann.%s@zzmail.example" % tag
        h = bcrypt.hashpw(b"zz-wait-password", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', 'Ann',"
                    " 'Partnerships')", (person, h))
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, enabled) values"
                    " (%s, %s, %s, 50, true)", (person, box_addr, store.encrypt({"refresh_token": "1//zz"})))
        cur.execute("select now() as n")
        now = cur.fetchone()["n"]
        ago = lambda hours: now - timedelta(hours=hours)   # noqa: E731
        g = FakeGmail()
        dbconn.Db = db
        outreach.SEGMENT = slug
        outreach.user_gmail_service = lambda _db, _box: g
        # no model: the replies stay unmarked, as this suite is about answering them (the AI's own marks are in
        # tools/test_clipping_leads.py)
        ra.read_reply = lambda subject, body, chat=None: (None, None)
        ours = "Ann <%s>" % box_addr

        def lead(key, theirs, sent_hours=72):
            """A company with our first email in thread zz-<key>, and its messages after it in Gmail."""
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'test',"
                        " 'contacted') returning id", (seg, "ZZ %s %s" % (key, tag), "zz-%s-%s.example" % (key.lower(), tag)))
            e = cur.fetchone()["id"]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Maya Chen', %s,"
                        " 'valid') returning id", (e, "maya@zz-%s-%s.example" % (key.lower(), tag)))
            c = cur.fetchone()["id"]
            tid = "zz-%s-%s" % (key, tag)
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                        " approved_at, sent_at, sender_mailbox, sender_address, gmail_thread_id, gmail_message_id)"
                        " values (%s, %s, 'zz', '500+ clips per episode', 'Hello', 'sent', %s, %s, %s, %s, %s, %s, %s)",
                        (e, c, person, ago(sent_hours), ago(sent_hours), box_addr, box_addr, tid, "zz-o-" + tid))
            g.store[tid] = [message("zz-o-" + tid, ago(sent_hours), ours, "500+ clips per episode", ["SENT"])] + theirs
            return {"e": str(e), "c": c, "t": tid}

        def lead_mail(key):
            return "Maya <maya@zz-%s-%s.example>" % (key.lower(), tag)

        def reply_row(mid):
            cur.execute("select id::text, received_at, answered_at, answered_by, answered_how, status, triage"
                        " from outreach where gmail_message_id = %s", (mid,))
            return dict(cur.fetchone() or {})

        A = lead("A", [message("zz-a1-" + tag, ago(30), lead_mail("A"))])
        B = lead("B", [message("zz-b1-" + tag, ago(26), lead_mail("B")),
                       message("zz-b2-" + tag, ago(24), ours, labels=["SENT"])])
        C = lead("C", [message("zz-c1-" + tag, ago(28), lead_mail("C")),
                       message("zz-c2-" + tag, ago(27), "Amrit <%s>" % cc)])
        D = lead("D", [message("zz-d1-" + tag, ago(20), lead_mail("D")),
                       message("zz-d2-" + tag, ago(19), ours, labels=["DRAFT"])])
        E = lead("E", [message("zz-e1-" + tag, ago(40), lead_mail("E")),
                       message("zz-e2-" + tag, ago(37), ours, labels=["SENT"]),
                       message("zz-e3-" + tag, ago(10), lead_mail("E"))])
        F = lead("F", [message("zz-f1-" + tag, ago(30), "Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                               "Delivery Status Notification (Failure)")])
        # G: its reply was read before sql/46 (no dates on it); we answered in Gmail since
        G = lead("G", [message("zz-g1-" + tag, ago(120), lead_mail("G")),
                       message("zz-g2-" + tag, ago(115), ours, labels=["SENT"])], sent_hours=200)
        cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, gmail_message_id,"
                    " gmail_thread_id, created_at) values (%s, %s, 'inbound', 'Re: 500+ clips per episode', 'Yes', 'received',"
                    " %s, %s, %s)", (G["e"], G["c"], "zz-g1-" + tag, G["t"], ago(119)))

        print("-- the pull notes when each reply came, and when we answered it")
        rc, text = pull()
        check("the pull runs", rc, 0)
        if os.environ.get("ZZ_SHOW_PULL"):
            print(text)
        a, b, c, d = (reply_row("zz-%s1-%s" % (k, tag)) for k in "abcd")
        e1, e3, gg = reply_row("zz-e1-" + tag), reply_row("zz-e3-" + tag), reply_row("zz-g1-" + tag)
        check("a reply: when Gmail got it, not when the app read it", abs((a["received_at"] - ago(30)).total_seconds()) < 1, True)
        check("  nobody answered: it waits", (a["answered_at"], a["answered_how"]), (None, None))
        check("answered from this Gmail (SENT): when, from which address, in the thread",
              (abs((b["answered_at"] - ago(24)).total_seconds()) < 1, b["answered_by"], b["answered_how"]),
              (True, box_addr, "thread"))
        check("answered by the project's CC (our side, not SENT here): answered", (c["answered_by"], c["answered_how"]),
              (cc, "thread"))
        check("a draft of an answer: no answer yet", d["answered_at"], None)
        check("a second reply after our answer: the first answered, the second waits",
              (e1["answered_at"] is not None, e3["answered_at"]), (True, None))
        check("a reply read before sql/46: both dates filled in by the next pull",
              (abs((gg["received_at"] - ago(120)).total_seconds()) < 1, abs((gg["answered_at"] - ago(115)).total_seconds()) < 1),
              (True, True))
        check("the run says how many it saw answered", "4 repl(ies) answered" in text, True)
        rc, text = pull()
        check("the next pull: nothing new, nothing changed", ("0 repl(ies) answered" in text, reply_row("zz-b1-" + tag)["answered_at"] == b["answered_at"]),
              (True, True))

        print("\n-- the five-minute look reads the threads waiting on us")
        g.store[A["t"]].append(message("zz-a2-" + tag, ago(1), ours, labels=["SENT"]))
        g.recent, g.reads = set(), []
        rc, text = pull(recent=True)
        check("nothing new in two days, but A waits: read, and its answer seen",
              (reply_row("zz-a1-" + tag)["answered_how"], reply_row("zz-a1-" + tag)["answered_by"]), ("thread", box_addr))
        check("  only the waiting threads are read (A, D, E)", sorted(g.reads), sorted([A["t"], D["t"], E["t"]]))
        g.store[A["t"]].pop()
        cur.execute("update outreach set answered_at = null, answered_by = null, answered_how = null"
                    " where gmail_message_id = %s", ("zz-a1-" + tag,))

        print("\n-- what waits for an answer")
        def waits(mid):
            cur.execute("select " + pol.unanswered("r") + " as w from outreach r where gmail_message_id = %s", (mid,))
            return cur.fetchone()["w"]
        check("the bounce notice does not", waits("zz-f1-" + tag), False)
        check("an unanswered reply does; an answered one does not", (waits("zz-a1-" + tag), waits("zz-b1-" + tag)), (True, False))
        cur.execute("update outreach set reply_kind = 'not_interested' where gmail_message_id = %s", ("zz-d1-" + tag,))
        check("the model read it as a no: it does not", waits("zz-d1-" + tag), False)
        cur.execute("update outreach set triage = 'positive', status = 'triaged' where gmail_message_id = %s", ("zz-d1-" + tag,))
        check("  a person marked it Positive: it does", waits("zz-d1-" + tag), True)
        cur.execute("update outreach set triage = 'negative' where gmail_message_id = %s", ("zz-d1-" + tag,))
        check("marked Negative: it does not", waits("zz-d1-" + tag), False)
        cur.execute("update outreach set triage = null, status = 'received', reply_kind = null where gmail_message_id = %s",
                    ("zz-d1-" + tag,))

        print("\n-- In conversation, Replies, and answered another way")
        import main
        import auth
        main._checkout = lambda: TxConnShim(conn)
        main._POOL = NoPool()
        main._SEG_CACHE.update(at=0.0, rows=[])
        from fastapi.testclient import TestClient
        client = TestClient(main.app, follow_redirects=False)
        ck = {auth.COOKIE: auth.make_cookie(person, h), "tvf_segment": slug}
        d = client.get("/api/outreach?folder=conversation", cookies=ck).json()
        order = [r["entity_id"] for r in d["rows"]]
        check("In conversation: the waiting ones first, the longest wait on top (A, D, E)", order[:3], [A["e"], D["e"], E["e"]])
        check("  then the rest; not the bounce", (sorted(order[3:]) == sorted([B["e"], C["e"], G["e"]]), F["e"] in order),
              (True, False))
        since = {r["entity_id"]: r["waiting_since"] for r in d["rows"]}
        check("  since when: the oldest unanswered reply (E: its second one)",
              (since[A["e"]][:16] == ago(30).isoformat()[:16], since[E["e"]][:16] == ago(10).isoformat()[:16], since[B["e"]]),
              (True, True, None))
        check("  counted on the tab: 3 waiting", (d["counts"]["waiting"], d["counts"]["conversation"]), (3, 6))
        r = client.get("/api/outreach?folder=inbox", cookies=ck).json()
        flag = {x["id"]: x["awaiting_answer"] for x in r["rows"]}
        check("Replies: each says whether it waits", (flag[a["id"]], flag[b["id"]], flag[e1["id"]], flag[e3["id"]]),
              (True, False, False, True))
        ans = [x for x in r["rows"] if x["id"] == b["id"]][0]
        check("  and how it was answered", (ans["answered_by"], ans["answered_how"]), (box_addr, "thread"))

        from api_v1 import Ops
        got = Ops(main).list_emails(person, {"project": slug, "folder": "in_conversation"})
        row_a = [x for x in got["rows"] if x["lead_id"] == A["e"]][0]
        check("the API: waiting_on_us, waiting_since, and the count",
              (row_a["waiting_on_us"], row_a["waiting_since"] is not None, got["counts"]["waiting_on_us"]), (True, True, 3))

        print("\n-- Team, before anything is marked")
        t = client.get("/api/reports/team?period=all&scope=project", cookies=ck).json()
        ann = [p for p in t["people"] if p["account"] == person][0]
        # B answered 2 h after, C 1 h, E 3 h, G 5 h: the typical time is 2.5 h; A, D and E wait
        check("the typical time to our answer, per person", ann["median_answer_hours"], 2.5)
        check("  how many wait on them now", (ann["waiting_on_us"], t["totals"]["waiting_on_us"]), (3, 3))

        print("\n-- the daily reminder")
        cur.execute("delete from reply_reminders where user_email = lower(%s)", (person,))
        when = now
        while when.astimezone(ra.IST).weekday() >= 5 or when.astimezone(ra.IST).hour < ra.REMIND_FROM_HOUR:
            when = (when + timedelta(days=1)).replace(hour=5, minute=40)        # 11:10 India time
        g.imports = []
        got = ra.remind(db, g, {"user_email": person, "address": box_addr}, log=lambda m: None, now=when)
        mail = g.imports[0] if g.imports else ""
        check("one reminder", (got, len(g.imports)), (True, 1))
        waiting_part, unmarked_part = (mail.split("Nobody has marked these")[0], mail.split("Nobody has marked these")[-1])
        over_a_day = (when - ago(20)) > timedelta(hours=24)      # D's reply, 20 hours old now: a day old by then?
        check("  waiting for an answer over a day: A; D only once its reply is a day old",
              ("ZZ A %s" % tag in waiting_part, "ZZ D %s" % tag in waiting_part, "Nobody on our side has answered these" in waiting_part),
              (True, over_a_day, True))
        check("  only unmarked (answered): B, C, G apart, under their own heading",
              all("ZZ %s %s" % (k, tag) in unmarked_part for k in "BCG") and "ZZ B %s" % tag not in waiting_part, True)
        check("  says the answer is seen by itself, and where to say it was answered another way",
              ("sees your answer within minutes" in mail, "#outreach/conversation" in mail), (True, True))

        print("\n-- answered another way")
        res = client.post("/api/outreach/%s/decision" % a["id"], json={"action": "mark_answered"}, cookies=ck)
        check("marked answered: done", (res.status_code, res.json().get("answered")), (200, 1))
        a2 = reply_row("zz-a1-" + tag)
        check("  answered now, by that person, another way", (a2["answered_by"], a2["answered_how"], a2["answered_at"] is not None),
              (person, "marked", True))
        res = client.post("/api/outreach/%s/decision" % a["id"], json={"action": "mark_answered"}, cookies=ck)
        check("  twice: refused, nothing waits", res.status_code, 409)
        rc, text = pull()
        check("  the next pull leaves the mark as it is", reply_row("zz-a1-" + tag)["answered_how"], "marked")
        d = client.get("/api/outreach?folder=conversation", cookies=ck).json()
        check("In conversation: 2 waiting now, D first", (d["counts"]["waiting"], d["rows"][0]["entity_id"]), (2, D["e"]))
        t = client.get("/api/reports/team?period=all&scope=project", cookies=ck).json()
        check("Team: 2 wait on her now", [p for p in t["people"] if p["account"] == person][0]["waiting_on_us"], 2)

        check("a message with no date: no time, so no answer is guessed", outreach._message_time({"id": "x"}), None)
    finally:
        dbconn.Db, outreach.user_gmail_service, outreach.SEGMENT, ra.read_reply = real
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
