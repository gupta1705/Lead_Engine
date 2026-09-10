#!/usr/bin/env python3
"""test_mailboxes.py -- mailbox rotation, warm-up and bounces, against the real
database inside one transaction that is rolled back at the end.

    python tools/test_mailboxes.py

Needs sql/24 applied and the lcx-clipping config synced. Exit code 1 on failure.
"""
import datetime as dt
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg2
import outreach_policy as pol
from run_sql import load_db_url

SEG = "lcx-clipping"
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("   (%s)" % (detail,)) if detail != "" and not cond else ""))


def main():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    today = dt.datetime.now(dt.timezone.utc).date()
    try:
        # ------------------------------------------------------------ config
        tvf = pol.mailbox_list(pol.outreach_config(cur, "us-production-houses"), "us-production-houses")
        check("TVF has one implicit mailbox", len(tvf) == 1 and tvf[0]["key"] == "default", tvf)
        check("TVF keeps its original token file and variable",
              tvf[0]["token_file"] == ".gmail_token.json" and tvf[0]["token_env"] == "GMAIL_TOKEN_JSON")
        cfg = pol.outreach_config(cur, SEG)
        boxes = pol.mailbox_list(cfg, SEG)
        check("LCX has three mailboxes", [b["key"] for b in boxes] == ["main", "second", "third"], boxes)
        check("per-mailbox token files", boxes[1]["token_file"] == ".gmail_token.lcx-clipping.second.json"
              and boxes[1]["token_env"] == "GMAIL_TOKEN_JSON_LCX_CLIPPING_SECOND")
        try:
            pol.mailbox_list({"mailboxes": [{"key": "a", "email_env": "X"}, {"key": "a", "email_env": "Y"}]}, SEG)
            check("duplicate mailbox keys are refused", False)
        except ValueError:
            check("duplicate mailbox keys are refused", True)

        # ----------------------------------------------------------- warm-up
        mb = boxes[0]
        check("never sent -> start at 10", pol.cap_today(mb, None, today) == 10)
        check("first day -> 10", pol.cap_today(mb, today, today) == 10)
        check("day 3 -> 15", pol.cap_today(mb, today - dt.timedelta(days=2), today) == 15)
        check("day 13 -> 40", pol.cap_today(mb, today - dt.timedelta(days=12), today) == 40)
        check("never above the daily cap", pol.cap_today(mb, today - dt.timedelta(days=90), today) == 40)
        check("no warm-up -> the daily cap", pol.cap_today(dict(mb, warmup=None), None, today) == 40)
        check("disabled -> 0", pol.cap_today(dict(mb, enabled=False), None, today) == 0)

        # ------------------------------------------------------------- usage
        cur.execute("select id from segments where slug=%s", (SEG,))
        seg_id = cur.fetchone()[0]

        def company():
            cur.execute("insert into entities (segment_id, name, source, status) values (%s,%s,'test','contacted') returning id",
                        (seg_id, "ZZ mailbox test " + uuid.uuid4().hex[:8]))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, is_primary) values (%s,'Pat Doe',%s,true) returning id",
                        (eid, "pat.%s@example.com" % uuid.uuid4().hex[:6]))
            return eid, cur.fetchone()[0]

        before = {s["key"]: s for s in pol.mailbox_status(cur, SEG, boxes, today)}
        opened = []
        for key, days_ago in (("main", 0), ("main", 0), ("second", 4)):
            e, c = company()
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, sender_mailbox,"
                        " sender_address, gmail_thread_id, gmail_message_id) values (%s,%s,'S','b','sent',"
                        " now() - make_interval(days => %s), %s, %s, %s, %s) returning id",
                        (e, c, days_ago, key, key + "@lcx.example", "t-" + uuid.uuid4().hex, "m-" + uuid.uuid4().hex))
            opened.append((e, c, cur.fetchone()[0], key))
        st = {s["key"]: s for s in pol.mailbox_status(cur, SEG, boxes, today)}
        check("main: two sent today", st["main"]["sent_today"] == before["main"]["sent_today"] + 2, st["main"])
        check("second: warmed from its first send four days ago", st["second"]["cap_today"] == 20, st["second"])
        check("third: never sent, starts at 10", st["third"]["cap_today"] == 10 and st["third"]["warmup_day"] == 0)
        check("the sending address is remembered", st["second"]["last_address"] == "second@lcx.example")

        rem = [(k, st[k]["remaining"]) for k in ("main", "second", "third")]
        check("least loaded wins", pol.pick_mailbox(rem, {"main", "second", "third"}) == "second", rem)
        check("only connected mailboxes are picked", pol.pick_mailbox(rem, {"main", "third"}) == "third", rem)
        check("nothing connected -> no mailbox", pol.pick_mailbox(rem, set()) is None)
        check("all full -> no mailbox", pol.pick_mailbox([("main", 0), ("second", 0)], {"main", "second"}) is None)

        # ------------------------------ follow-ups stay on the opener's mailbox
        e, c, opener, key = opened[2]                          # sent from "second"
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id)"
                    " values (%s,%s,'Re: S','x','approved',1,%s) returning id", (e, c, opener))
        fu = cur.fetchone()[0]
        cur.execute("update outreach set status='sending', sender_mailbox='main', sender_address='main@lcx.example'"
                    " where id=%s and status='approved' returning sender_mailbox, sender_address", (fu,))
        got = cur.fetchone()
        check("the database moves a follow-up onto its opener's mailbox", got == ("second", "second@lcx.example"), got)

        e2, c2, opener2, _ = opened[0]
        cur.execute("update outreach set sender_mailbox=null where id=%s", (opener2,))
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id)"
                    " values (%s,%s,'Re: S','x','approved',1,%s) returning id", (e2, c2, opener2))
        fu2 = cur.fetchone()[0]
        cur.execute("update outreach set status='sending', sender_mailbox='main', sender_address='main@lcx.example'"
                    " where id=%s returning sender_mailbox", (fu2,))
        check("an opener from before rotation keeps the chosen mailbox", cur.fetchone()[0] == "main")

        # ------------------------------------------------------------ bounces
        check("mailer-daemon is a bounce", pol.is_bounce("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "x"))
        check("a failure notice subject is a bounce", pol.is_bounce("someone@x.com", "Delivery Status Notification (Failure)"))
        check("a human reply is not", not pol.is_bounce("Pat Doe <pat@example.com>", "Re: three shorts from your latest episode?"))
        check("a human quoting 'undeliverable' in a Re: is not", not pol.is_bounce("pat@example.com", "Re: undeliverable?"))
        e3, c3, opener3, _ = opened[1]
        pol.mark_bounce(cur, e3, c3)
        cur.execute("select email_status, verifier from contacts where id=%s", (c3,))
        check("a bounce marks the address invalid", cur.fetchone() == ("invalid", "bounce"))
        cur.execute("select stopped_reason from outreach where id=%s", (opener3,))
        check("a bounce ends the thread", (cur.fetchone()[0] or "").startswith("bounced"))
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
