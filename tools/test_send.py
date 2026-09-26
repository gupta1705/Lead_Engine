#!/usr/bin/env python3
"""test_send.py -- tools/outreach.py send, the step that emails a real person, as a regression table.

    python tools/test_send.py

cmd_send runs for real against the real database inside ONE transaction that is rolled back: a
throwaway segment (US Production Houses' config with a daily cap of 3), shortlisted companies,
contacts and approved emails, then ROLLBACK. Gmail is a stand-in that records every message it is
handed and can be told to fail, so nothing leaves the machine. What is checked:

  * the daily cap, and the rest going out the next day, oldest first
  * what a sent row and its company look like afterwards
  * the message itself: To, From, Subject (non-ASCII encoded), body, no Cc/Bcc
  * what is held back, visibly and without spending the cap: a bad address, an unfilled
    {{placeholder}}, a company rejected after approval, a subject with a line break
  * the owner's pause, and a sender still saying SET_ME
  * a Gmail error on the send (send_unknown, never retried by itself), and a Gmail sign-in that
    fails before anything is sent (the email goes back to Approved, not stuck in 'sending')

Exit code 1 on any failure.
"""
import argparse
import base64
import email
import email.header
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import psycopg2  # noqa: E402
from run_sql import load_db_url  # noqa: E402
import dbconn  # noqa: E402
import outreach  # noqa: E402

RESULTS = []
SENDER = "sender@zz-send-test.example"
REAL_USER_GMAIL = outreach.user_gmail_service


def approver_mode(cur, gmail):
    """From the approver (owner, 2026-09-26): an email goes out from the Gmail of the person who approved
    it, the address of theirs with the most room first, each address up to its own daily limit; someone
    with no Gmail connected waits; nobody's approval ever leaves from somebody else's address."""
    import os
    import mailbox_store as store
    os.environ.setdefault("SESSION_SECRET", "zz-send-test-" + uuid.uuid4().hex)
    args = argparse.Namespace(limit=500)
    print("\n-- from the approver's own Gmail, each address with its own limit")
    slug = "zz-send-appr-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (approver)', 'company', config from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(config #- '{outreach,sending_paused}', '{outreach,send_from}',"
                " '\"approver\"') where id = %s", (seg_id,))
    outreach.SEGMENT = slug
    tag = uuid.uuid4().hex[:6]
    asha, bala = "zz-asha-%s@example.com" % tag, "zz-bala-%s@example.com" % tag
    for who in (asha, bala):
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', 'P', 'T')", (who,))
    one, two = "asha.one.%s@zz-mail.example" % tag, "asha.two.%s@zz-mail.example" % tag

    def mailbox(owner, address, cap):
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap) values (%s, %s, %s, %s)"
                    " returning id", (owner, address, store.encrypt({"refresh_token": "1//" + address}), cap))
        return str(cur.fetchone()[0])
    mailbox(asha, one, 2)
    mailbox(asha, two, 1)
    used = []

    def fake_user_gmail(db, box):
        used.append(box["address"])
        return gmail
    outreach.user_gmail_service = fake_user_gmail

    def approved_by(who):
        cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                    " (%s, %s, %s, 'test', 'shortlisted') returning id",
                    (seg_id, "ZZ appr " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
        eid = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay', %s, 'valid')"
                    " returning id", (eid, "kay.%s@zz-appr.example" % uuid.uuid4().hex[:6]))
        cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_at,"
                    " approved_by, approval_mode, created_at) values (%s, %s, 't', 'Hello', 'Hello Kay,\n\nBody',"
                    " 'approved', now(), %s, 'single', clock_timestamp()) returning id", (eid, cid, who))
        return cur.fetchone()[0]

    def row(oid):
        cur.execute("select status, lower(sender_address), send_error is not null from outreach where id = %s", (oid,))
        return list(cur.fetchone())

    hers = [approved_by(asha) for _ in range(4)]
    his = approved_by(bala)
    before = len(gmail.sent)
    outreach.cmd_send(args)
    check("Asha's four: three go (2 + 1 from her two addresses), the fourth waits for tomorrow",
          [row(o)[0] for o in hers], ["sent", "sent", "sent", "approved"])
    check("  from her address with the most room first", [row(o)[1] for o in hers[:3]], [one, one, two])
    check("  and the From line says so", [m["From"].lower() for m in gmail.sent[before:]], [one, one, two])
    check("Bala has no Gmail connected: his approval waits, untouched (no error, nothing sent from Asha's)",
          row(his), ["approved", None, False])
    cur.execute("select count(*) from outreach where lower(sender_address) in (%s, %s) and approved_by <> %s", (one, two, asha))
    check("  nothing anyone else approved left from Asha's addresses", cur.fetchone()[0], 0)

    # two runs at once: the other run's sends are simulated by a stale view of today; the claim counts for real
    real_mailboxes = store.mailboxes
    store.mailboxes = lambda *a, **k: [dict(b, out_today=0, sent_today=0, remaining=b["daily_cap"], usable=True)
                                       for b in real_mailboxes(*a, **k)]
    try:
        outreach.cmd_send(args)
    finally:
        store.mailboxes = real_mailboxes
    check("each address's limit holds against another run's sends: the fourth still waits", row(hers[3])[0], "approved")

    # Bala connects a Gmail whose sign-in Google no longer accepts
    bad = "bala.%s@zz-mail.example" % tag
    bad_id = mailbox(bala, bad, 35)

    class Refused(Exception):
        pass
    Refused.__name__ = "RefreshError"

    def refusing(db, box):
        if box["address"] == bad:
            raise Refused("invalid_grant: Token has been expired or revoked.")
        return gmail
    outreach.user_gmail_service = refusing
    rc = outreach.cmd_send(args)
    cur.execute("select last_error is not null from user_mailboxes where id = %s", (bad_id,))
    marked = cur.fetchone()[0]
    check("his Gmail's sign-in refused: the email back in Approved, the address marked to reconnect, the run failed",
          (row(his)[0], marked, rc), ("approved", True, 1))
    outreach.user_gmail_service = fake_user_gmail
    before = len(gmail.sent)
    rc = outreach.cmd_send(args)
    check("  a marked address is not tried again until he reconnects", (row(his)[0], len(gmail.sent) - before, rc),
          ("approved", 0, 0))
    cur.execute("update user_mailboxes set last_error = null where id = %s", (bad_id,))
    outreach.cmd_send(args)
    check("  reconnected: it goes, from his own address", row(his)[:2], ["sent", bad])


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-70s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


class TxDb:
    """dbconn.Db on the test's one transaction: every run() is a savepoint, nothing is committed."""

    def __init__(self, conn):
        self._conn = conn

    def __call__(self, url=None):
        return self

    def run(self, fn, on_reconnect=None):
        with self._conn.cursor() as cur:
            cur.execute("savepoint send_step")
            try:
                out = fn(cur)
            except Exception:
                cur.execute("rollback to savepoint send_step")
                raise
            cur.execute("release savepoint send_step")
            return out

    def close(self):
        pass


class FakeGmail:
    """users().messages().send(...).execute() records the raw message; fail= makes it raise."""

    def __init__(self):
        self.sent, self.fail = [], None

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self._body = body
        return self

    def get(self, **kw):
        raise RuntimeError("no previous message in the test")

    def execute(self):
        if self.fail:
            raise self.fail
        raw = base64.urlsafe_b64decode(self._body["raw"])
        self.sent.append(email.message_from_bytes(raw))
        n = len(self.sent)
        return {"id": "zz-msg-%d-%s" % (n, uuid.uuid4().hex[:6]), "threadId": "zz-thread-%d" % n}


def header(msg, name):
    v = msg.get(name)
    return None if v is None else str(email.header.make_header(email.header.decode_header(v)))


def main():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    db = TxDb(conn)
    gmail = FakeGmail()
    real = (dbconn.Db, outreach.gmail_service, outreach.env, outreach.mailbox_connected, outreach.SEGMENT)
    dbconn.Db = db
    outreach.gmail_service = lambda mb=None: gmail
    outreach.env = lambda name: SENDER if name.endswith("SENDER_ADDRESS") else real[2](name)
    outreach.mailbox_connected = lambda mb: True
    args = argparse.Namespace(limit=500)
    try:
        with conn.cursor() as cur:
            slug = "zz-send-test-" + uuid.uuid4().hex[:6]
            cur.execute("insert into segments (slug, name, entity_type, config)"
                        " select %s, 'send test', 'company', config from segments where slug = 'us-production-houses'"
                        " returning id", (slug,))
            seg_id = cur.fetchone()[0]
            cur.execute("update segments set config = jsonb_set(config #- '{outreach,mailboxes}',"
                        " '{outreach,daily_send_cap}', '3') where id = %s", (seg_id,))
            outreach.SEGMENT = slug

            def approved(subject="From TVF in India — a note", body=None, address=None, status="shortlisted",
                         name=None):
                cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                            " (%s, %s, %s, 'test', %s) returning id",
                            (seg_id, name or "ZZ send " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example",
                             status))
                eid = cur.fetchone()[0]
                addr = address or "kay.%s@zz-send-test.example" % uuid.uuid4().hex[:6]
                cur.execute("insert into contacts (entity_id, full_name, email, email_status) values"
                            " (%s, 'Kay Doe', %s, 'valid') returning id", (eid, addr))
                cid = cur.fetchone()[0]
                text = body or "Hello Kay,\n\nI’m writing on behalf of Kartikeya — test.\n\nVedansh"
                # clock_timestamp, not now(): now() is one instant for the whole transaction, and the
                # send order ("oldest first") needs the rows apart
                cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status,"
                            " approved_at, approved_by, approval_mode, created_at) values"
                            " (%s, %s, 't', %s, %s, 'approved', now(), 'test', 'single', clock_timestamp()) returning id",
                            (eid, cid, subject, text))
                return cur.fetchone()[0], eid, addr

            def state(oid):
                cur.execute("select o.status, o.send_error is not null, o.sender_address, o.gmail_message_id is not null,"
                            " e.status from outreach o join entities e on e.id = o.entity_id where o.id = %s", (oid,))
                return list(cur.fetchone())

            # ---------------------------------------------------------------- the cap
            print("-- the daily cap (3 in this test), and the rest the next day")
            rows = [approved() for _ in range(5)]
            outreach.cmd_send(args)
            check("five approved, cap 3: three go, oldest first",
                  [state(o)[0] for o, _, _ in rows], ["sent", "sent", "sent", "approved", "approved"])
            check("a sent row: from the mailbox's address, with its Gmail ids; its company contacted",
                  state(rows[0][0]), ["sent", False, SENDER, True, "contacted"])
            m = gmail.sent[0]
            check("the message: To the contact, From the mailbox, Subject as written (non-ASCII kept)",
                  [m["To"], m["From"], header(m, "Subject")], [rows[0][2], SENDER, "From TVF in India — a note"])
            check("  the body as written, in UTF-8", m.get_payload(decode=True).decode(m.get_content_charset()),
                  "Hello Kay,\n\nI’m writing on behalf of Kartikeya — test.\n\nVedansh")
            check("  nobody copied in", [m.get("Cc"), m.get("Bcc")], [None, None])
            check("  our own Message-ID, one per row, on one line", m["Message-ID"],
                  "<tvf-%s@%s>" % (str(rows[0][0]).replace("-", ""), SENDER.split("@")[1]))
            outreach.cmd_send(args)
            check("run again the same day: nothing more goes", len(gmail.sent), 3)
            cur.execute("update outreach set sent_at = sent_at - interval '1 day' where status = 'sent'"
                        " and entity_id in (select id from entities where segment_id = %s)", (seg_id,))
            outreach.cmd_send(args)
            check("the next day: the two that waited go out", [state(o)[0] for o, _, _ in rows[3:]], ["sent", "sent"])
            cur.execute("update outreach set sent_at = sent_at - interval '2 days' where status = 'sent'"
                        " and entity_id in (select id from entities where segment_id = %s)", (seg_id,))

            # ----------------------------------------------------------- held back
            print("\n-- held back visibly, without using the cap")
            bad = approved(address="kay@@zz-send-test.example")
            ph = approved(body="Hello {{first_name}},\n\nBody")
            rej = approved()
            cur.execute("update entities set status = 'rejected' where id = %s", (rej[1],))
            crlf = approved(subject="Hello\nBcc: evil@zz-send-test.example")
            same_inbox = approved(address=rows[0][2].upper())         # an address already written to
            cur.execute("select name from entities where id = %s", (rows[1][1],))
            same_name = approved(name=cur.fetchone()[0].lower())      # a company already written to
            good = approved()
            before = len(gmail.sent)
            try:
                outreach.cmd_send(args)
                crashed = None
            except Exception as e:                       # noqa: BLE001 -- the crash is what is being tested
                crashed = type(e).__name__
            check("a run with a bad row in it does not crash", crashed, None)
            check("a malformed address is parked, not sent", state(bad[0])[:2], ["approved", True])
            check("an unfilled {{placeholder}} is parked", state(ph[0])[:2], ["approved", True])
            check("a company rejected after approval is parked", state(rej[0])[:2], ["approved", True])
            check("a subject with a line break is parked, never stuck in 'sending'", state(crlf[0])[:2],
                  ["approved", True])
            check("an address that already had a first email, under another lead, is parked",
                  state(same_inbox[0])[:2], ["approved", True])
            check("a company of the same name that already had one is parked", state(same_name[0])[:2],
                  ["approved", True])
            check("the good one in the same run still goes, and only it", (state(good[0])[0], len(gmail.sent) - before),
                  ("sent", 1))
            if gmail.sent[before:]:
                check("  and no header was smuggled in", gmail.sent[-1].get("Bcc"), None)

            # --------------------------------------------------------- pause, sender
            print("\n-- the owner's pause, and a sender still saying SET_ME")
            waiting = approved()
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sending_paused}', '\"test pause\"')"
                        " where id = %s", (seg_id,))
            n = len(gmail.sent)
            check("paused: the run returns quietly", outreach.cmd_send(args), 0)
            check("  and nothing is sent", (len(gmail.sent) - n, state(waiting[0])[0]), (0, "approved"))
            cur.execute("update segments set config = config #- '{outreach,sending_paused}' where id = %s", (seg_id,))
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sender,name}', '\"SET_ME\"')"
                        " where id = %s", (seg_id,))
            try:
                outreach.cmd_send(args)
                refused = False
            except SystemExit:
                refused = True
            check("a sender saying SET_ME: the run refuses", (refused, state(waiting[0])[0]), (True, "approved"))
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sender,name}', '\"Vedansh Gupta\"')"
                        " where id = %s", (seg_id,))

            # ----------------------------------------------------------- Gmail fails
            print("\n-- Gmail failing")
            gmail.fail = RuntimeError("timed out after the request was written")
            outreach.cmd_send(args)
            check("an error on the send: send_unknown with the error kept (it may have gone)",
                  state(waiting[0])[:2], ["send_unknown", True])
            gmail.fail = None
            n = len(gmail.sent)
            outreach.cmd_send(args)
            check("  and it is never retried by itself", (len(gmail.sent) - n, state(waiting[0])[0]), (0, "send_unknown"))

            signin = approved()

            def refused_signin(mb=None):
                raise RuntimeError("invalid_grant: token has been expired or revoked")
            outreach.gmail_service = refused_signin
            try:
                outreach.cmd_send(args)
            except Exception:                             # noqa: BLE001
                pass
            check("Gmail sign-in fails before anything is sent: the email goes back to Approved",
                  state(signin[0])[0], "approved")
            outreach.gmail_service = lambda mb=None: gmail
            outreach.cmd_send(args)
            check("  and goes out on the next run once sign-in works", state(signin[0])[0], "sent")

            class Refused(Exception):
                def __init__(self, status):
                    super().__init__("HttpError %d" % status)
                    self.resp = type("R", (), {"status": status})()
            # today's three (the cap) are moved to two days ago, so these runs have room to try
            cur.execute("update outreach set sent_at = sent_at - interval '2 days', updated_at = updated_at - interval"
                        " '2 days' where status in ('sent', 'send_unknown') and entity_id in"
                        " (select id from entities where segment_id = %s)", (seg_id,))
            refused_one = approved()
            gmail.fail = Refused(400)
            outreach.cmd_send(args)
            check("Gmail refuses one email (400): it is parked, not 'unknown'", state(refused_one[0])[:2],
                  ["approved", True])
            limited = approved()
            gmail.fail = Refused(429)
            check("Gmail's rate limit (429): the run ends failed, so the owner hears of it", outreach.cmd_send(args), 1)
            check("  and the email is back in Approved, untouched, for the next run", state(limited[0])[:2],
                  ["approved", False])
            gmail.fail = None
            outreach.cmd_send(args)
            check("  which sends it", state(limited[0])[0], "sent")

            # two runs at once: each took the day's whole budget from its own start. The other run's
            # sends are simulated by a stale count at the start; the claim must see the real one.
            # A cap of 1, with the one sent above out today.
            cur.execute("update segments set config = jsonb_set(config, '{outreach,daily_send_cap}', '1') where id = %s",
                        (seg_id,))
            import outreach_policy
            real_status = outreach_policy.mailbox_status
            outreach_policy.mailbox_status = lambda *a, **k: [dict(st, sent_today=0, remaining=st["cap_today"])
                                                              for st in real_status(*a, **k)]
            late = approved()
            try:
                outreach.cmd_send(args)
            finally:
                outreach_policy.mailbox_status = real_status
            check("the cap holds against another run's sends (1 out today, cap 1): nothing more goes",
                  state(late[0])[0], "approved")

            approver_mode(cur, gmail)
    finally:
        conn.rollback()
        conn.close()
        dbconn.Db, outreach.gmail_service, outreach.env, outreach.mailbox_connected, outreach.SEGMENT = real
        outreach.user_gmail_service = REAL_USER_GMAIL
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back; nothing was sent)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
