#!/usr/bin/env python3
"""test_reply_alerts.py -- the alert when a lead replies (tools/reply_alert.py, sql/45) and Replies with the Negative
ones apart at the bottom (owner, 2026-10-28), as a table.

    python tools/test_reply_alerts.py

The real database inside ONE transaction that is rolled back, a Gmail that only records what it is asked, and a model
that answers by the reply's subject. Checked:

  * a new reply: read by the model, starred and labelled "Lead replied", an alert put in the inbox of the person
    whose Gmail holds the thread (Gmail's import: to no one else, nothing sent), with who replied, the reading, the
    reply's first lines and the link; the reading kept on the reply; never twice, even with two pulls at once
  * a bounce notice: nothing; an auto-reply: no star, no alert, but its reading kept
  * Gmail refusing the alert: tried again on the next pull, at most three times
  * no model: the alert still goes, without a reading
  * the daily reminder: weekdays from 10:00 India time, the replies nobody marked or answered for a day, once a day per
    person (tools/test_waiting_on_us.py has the answered side)
  * quoted text is cut from what the alert shows
  * Replies: newest first, the Negative ones apart (negative_rows) and out of the list and its count; the API keeps
    them in one list
Exit code 1 on any failure.
"""
import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-alert-test-" + uuid.uuid4().hex
os.environ["PUBLIC_BASE_URL"] = "https://leads.example.test"

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import reply_alert as ra  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


# ------------------------------------------------------------------ a Gmail that records
class Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    def __init__(self):
        self.calls, self.labels, self.fail_import = [], [], 0

    def users(self):
        return self

    def messages(self):
        return self

    def __getattr__(self, name):
        raise AttributeError(name)

    # labels().list / create share the names with messages(): told apart by kwargs
    def list(self, userId, **k):
        return Call(lambda: {"labels": list(self.labels)})

    def create(self, userId, body):
        def go():
            self.labels.append({"id": "Label_9", "name": body["name"]})
            self.calls.append(("label_create", body["name"]))
            return {"id": "Label_9"}
        return Call(go)

    def modify(self, userId, id, body):
        return Call(lambda: self.calls.append(("modify", id, sorted(body["addLabelIds"]))) or {})

    def get(self, userId, id, format=None, metadataHeaders=None):
        return Call(lambda: {"payload": {"headers": [{"name": "From", "value": "Maya Chen <maya@zz.example>"}]}})

    def import_(self, userId, body, **k):
        def go():
            if self.fail_import:
                self.fail_import -= 1
                raise RuntimeError("gmail said no")
            import email
            msg = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
            plain = next(p.get_payload(decode=True).decode("utf-8") for p in msg.walk()
                         if p.get_content_type() == "text/plain")
            raw = "".join("%s: %s\n" % kv for kv in msg.items()) + "\n" + plain     # headers, then the text
            self.calls.append(("import", body["labelIds"], raw, k))
            return {"id": "imp"}
        return Call(go)


class Users:
    def __init__(self, g):
        self.g = g

    def labels(self):
        return self.g

    def messages(self):
        return self.g


class Gmail:
    def __init__(self):
        self.g = FakeGmail()

    def users(self):
        return Users(self.g)

    @property
    def calls(self):
        return self.g.calls


class TxDb:
    def __init__(self, conn):
        self.conn = conn

    def run(self, fn):
        with self.conn.cursor() as cur:
            return fn(cur)


def chat_by_subject(messages, model, **k):
    text = messages[-1]["content"]
    if "Out of office" in text:
        return '{"kind": "auto_reply", "summary": "Away until Monday."}'
    if "Pricing" in text:
        return 'Sure: {"kind": "question", "summary": "Asks what it costs per episode."}'
    return '{"kind": "interested", "summary": "Wants a call on Thursday."}'


def no_model(messages, model, **k):
    raise RuntimeError("GROQ_API_KEY is not set")


def main_():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    db = TxDb(conn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # sql/45 and 46 are applied live; running their ALTER TABLE here would lock outreach for the live app while
        # this runs
        tag = uuid.uuid4().hex[:6]
        slug = "zz-alert-" + tag
        cfg = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
        cfg.pop("sourcing", None)
        cfg.setdefault("ui", {})["project_name"] = "ZZ Alerts"
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ Alerts',"
                    " 'company', %s, true) returning id", (slug, json.dumps(cfg)))
        seg = cur.fetchone()["id"]
        person = "zz-alert-ann-%s@example.com" % tag
        box_addr = "ann.%s@zzmail.example" % tag
        h = bcrypt.hashpw(b"zz-alert-password", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member', 'Ann',"
                    " 'Partnerships')", (person, h))
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, enabled) values"
                    " (%s, %s, 'x', 50, true)", (person, box_addr))
        box = {"user_email": person, "address": box_addr}

        def lead(i, thread):
            cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'test',"
                        " 'contacted') returning id", (seg, "ZZ Show %d %s" % (i, tag), "zz%d-%s.example" % (i, tag)))
            e = cur.fetchone()["id"]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Maya Chen', %s,"
                        " 'valid') returning id", (e, "maya%d@zz%d-%s.example" % (i, i, tag)))
            c = cur.fetchone()["id"]
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                        " approved_at, sent_at, sender_address, gmail_thread_id, gmail_message_id) values (%s, %s, 'zz',"
                        " '500+ clips per episode', 'Hello', 'sent', %s, now() - interval '3 days', now() - interval"
                        " '3 days', %s, %s, %s)", (e, c, person, box_addr, thread, "zz-m-" + uuid.uuid4().hex))
            return e, c

        def reply(e, c, thread, subject, body="Yes, let's talk.\n\nOn Mon, Ann wrote:\n> Hello", triage=None,
                  status="received", ago="5 minutes"):
            cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, triage,"
                        " gmail_message_id, gmail_thread_id, created_at) values (%s, %s, 'inbound', %s, %s, %s, %s, %s,"
                        " %s, now() - %s::interval) returning id::text",
                        (e, c, subject, body, status, triage, "zz-in-" + uuid.uuid4().hex, thread, ago))
            return cur.fetchone()["id"]

        def row(oid):
            cur.execute("select alerted_at is not null as alerted, alert_attempts, reply_kind, triage_reason,"
                        " alert_error is not null as failed from outreach where id = %s", (oid,))
            return dict(cur.fetchone())

        t1, t2, t3, t4 = ("zz-t-%s-%d" % (tag, i) for i in range(1, 5))
        e1, c1 = lead(1, t1)
        r1 = reply(e1, c1, t1, "Re: 500+ clips per episode")
        e2, c2 = lead(2, t2)
        bounce = reply(e2, c2, t2, "Delivery Status Notification (Failure)", triage="neutral", status="triaged")
        e3, c3 = lead(3, t3)
        ooo = reply(e3, c3, t3, "Out of office")

        print("-- the alert")
        g = Gmail()
        n = ra.alert_new(db, g, box, [t1, t2, t3], log=lambda m: None, chat=chat_by_subject)
        imports = [c for c in g.calls if c[0] == "import"]
        check("one alert: the reply (not the bounce, not the auto-reply)", (n, len(imports)), (1, 1))
        lab, raw, kw = imports[0][1], imports[0][2], imports[0][3]
        check("  into the inbox, unread, important; imported, never spam", (lab, kw.get("neverMarkSpam")),
              (["INBOX", "UNREAD", "IMPORTANT"], True))
        check("  addressed to her own address only", ("To: %s" % box_addr) in raw and raw.count("@zz1-") == 0, True)
        check("  says who replied, the company, the reading and the link",
              all(s in raw for s in ("Maya Chen", "ZZ Show 1 %s" % tag, "Interested: Wants a call on Thursday.",
                                     "https://leads.example.test/#outreach/replies", "ZZ Alerts")), True)
        check("  the subject names the company and the kind", "Subject: ZZ Show 1 %s replied: Interested" % tag in raw, True)
        check("  shows what they wrote, not the quoted email",
              ("Yes, let's talk." in raw, "Ann wrote" in raw), (True, False))
        check("the label \"Lead replied\" is made once", [c for c in g.calls if c[0] == "label_create"],
              [("label_create", "Lead replied")])
        mods = [c for c in g.calls if c[0] == "modify"]
        check("  one message starred: the reply itself", [m[2] for m in mods], [["IMPORTANT", "Label_9", "STARRED"]])
        a = row(r1)
        check("the reading is kept on the reply", (a["alerted"], a["reply_kind"], a["triage_reason"]),
              (True, "interested", "Marked positive by AI. AI's reading: Interested: Wants a call on Thursday."))
        o = row(ooo)
        check("the auto-reply: no alert, its reading kept", (o["alerted"], o["reply_kind"]), (True, "auto_reply"))
        check("the bounce notice: left alone", row(bounce)["alerted"], False)
        n = ra.alert_new(db, g, box, [t1, t2, t3], log=lambda m: None, chat=chat_by_subject)
        check("the next pull: nothing twice", (n, len([c for c in g.calls if c[0] == "import"])), (0, 1))

        e4, c4 = lead(4, t4)
        r4 = reply(e4, c4, t4, "Pricing?")
        cur.execute("update outreach set alert_claimed_at = now() where id = %s", (r4,))
        n = ra.alert_new(db, Gmail(), box, [t4], log=lambda m: None, chat=chat_by_subject)
        check("another pull has claimed it: this one leaves it", (n, row(r4)["alerted"]), (0, False))
        cur.execute("update outreach set alert_claimed_at = null where id = %s", (r4,))
        g = Gmail()
        g.g.fail_import = 5
        ra.alert_new(db, g, box, [t4], log=lambda m: None, chat=chat_by_subject)
        b = row(r4)
        check("Gmail refuses: not alerted, the error kept, one try", (b["alerted"], b["failed"], b["alert_attempts"]),
              (False, True, 1))
        ra.alert_new(db, g, box, [t4], log=lambda m: None, chat=chat_by_subject)
        ra.alert_new(db, g, box, [t4], log=lambda m: None, chat=chat_by_subject)
        n = ra.alert_new(db, g, box, [t4], log=lambda m: None, chat=chat_by_subject)
        check("  tried on each pull, three times at most", (row(r4)["alert_attempts"], n), (3, 0))

        e5, c5 = lead(5, "zz-t-%s-5" % tag)
        r5 = reply(e5, c5, "zz-t-%s-5" % tag, "Re: hello", body="Who is this?")
        g = Gmail()
        n = ra.alert_new(db, g, box, ["zz-t-%s-5" % tag], log=lambda m: None, chat=no_model)
        raw = [c for c in g.calls if c[0] == "import"][0][2]
        check("no model: the alert still goes, without a reading",
              (n, "replied to your email" in raw, "What it says" in raw, row(r5)["reply_kind"]), (1, True, False, None))

        print("\n-- the daily reminder")
        cur.execute("update outreach set created_at = now() - interval '3 days' where id = %s", (r1,))
        wed_9 = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)          # 08:30 in India
        wed_11 = datetime(2026, 10, 28, 5, 40, tzinfo=timezone.utc)        # 11:10
        sat_11 = datetime(2026, 10, 31, 5, 40, tzinfo=timezone.utc)
        g = Gmail()
        check("before 10:00 India time: none", ra.remind(db, g, box, log=lambda m: None, now=wed_9), False)
        check("a Saturday: none", ra.remind(db, g, box, log=lambda m: None, now=sat_11), False)
        cur.execute("select now() as n")
        now = cur.fetchone()["n"]
        live = now.replace(hour=5, minute=40) if now.astimezone(ra.IST).weekday() < 5 else wed_11
        at = live if live <= now else now
        got = ra.remind(db, g, box, log=lambda m: None, now=at)
        raws = [c[2] for c in g.calls if c[0] == "import"]
        if not got:      # the clock in India is before 10:00 or a weekend now: try a weekday at 11:10 instead
            at = wed_11
            got = ra.remind(db, g, box, log=lambda m: None, now=at)
            raws = [c[2] for c in g.calls if c[0] == "import"]
        check("a weekday after 10:00: one reminder", (got, len(raws)), (True, 1))
        check("  of the reply unmarked for over a day, not the fresh ones",
              ("ZZ Show 1 %s" % tag in raws[0], "ZZ Show 5 %s" % tag in raws[0], "Subject: 1 reply is waiting" in raws[0]),
              (True, False, True))
        check("  with its reading", "Interested: Wants a call on Thursday." in raws[0], True)
        # the same day again (the day the reminder above went on; 28 Oct is another day once that date has passed)
        check("  once a day", ra.remind(db, g, box, log=lambda m: None, now=at + timedelta(hours=2)), False)
        cur.execute("update outreach set status = 'triaged', triage = 'positive' where id = %s", (r1,))
        cur.execute("delete from reply_reminders where user_email = lower(%s)", (person,))
        g = Gmail()
        got = ra.remind(db, g, box, log=lambda m: None, now=wed_11) or ra.remind(db, g, box, log=lambda m: None,
                                                                             now=live if live <= now else now)
        raws = [c[2] for c in g.calls if c[0] == "import"]
        check("marked Positive, not answered yet: still in it, as waiting for an answer (sql/46)",
              (got, bool(raws) and "Nobody on our side has answered these" in raws[0]), (True, True))
        cur.execute("update outreach set answered_at = now(), answered_how = 'thread' where id = %s", (r1,))
        cur.execute("delete from reply_reminders where user_email = lower(%s)", (person,))
        check("marked and answered: no reminder for it", ra.remind(db, Gmail(), box, log=lambda m: None, now=wed_11), False)

        print("\n-- Replies, the Negative ones apart")
        import main
        import auth
        main._checkout = lambda: TxConnShim(conn)
        main._POOL = NoPool()
        main._SEG_CACHE.update(at=0.0, rows=[])
        from fastapi.testclient import TestClient
        client = TestClient(main.app, follow_redirects=False)
        cur.execute("update outreach set status = 'triaged', triage = 'negative', created_at = now() - interval '1 hour'"
                    " where id = %s", (r5,))
        ck = {auth.COOKIE: auth.make_cookie(person, h), "tvf_segment": slug}
        d = client.get("/api/outreach?folder=inbox", cookies=ck).json()
        ids = [r["id"] for r in d["rows"]]
        check("the list: not the Negative one", (r5 in ids, r1 in ids), (False, True))
        check("  newest first", [r["id"] for r in d["rows"]] == [r["id"] for r in sorted(
            d["rows"], key=lambda r: r["created_at"], reverse=True)], True)
        # the out-of-office is Negative too (the owner, 2026-11-13: no neutral marks)
        check("  the Negative ones apart, for the section at the bottom", sorted(r["id"] for r in d["negative_rows"]),
              sorted([r5, ooo]))
        check("  the list's count leaves it out; the tab still counts every reply",
              (d["total"], d["counts"]["inbox"]), (len(d["rows"]), len(d["rows"]) + 2))
        from api_v1 import Ops
        got = Ops(main).list_emails(person, {"project": slug, "folder": "replies"})
        check("the API: every reply in one list", r5 in [x["id"] for x in got["rows"]], True)
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


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


if __name__ == "__main__":
    sys.exit(main_())
