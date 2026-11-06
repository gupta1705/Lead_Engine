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
    {{placeholder}}, a company rejected after approval, a subject with a line break, an address that
    has answered us in another project since it was approved (a follow-up to them is cancelled)
  * an attached file (LCX Services' deck): sent as itself, byte for byte, named as approved; held
    back when the file changed after approval
  * the owner's pause, and a sender still saying SET_ME
  * a Gmail error on the send (send_unknown, never retried by itself), and a Gmail sign-in that
    fails before anything is sent (the email goes back to Approved, not stuck in 'sending')
  * the sending window (owner, 2026-10-12; window_mode): an email goes only inside its own window,
    the claim and sql/34's trigger refuse one outside it, a missed window moves once, never two
    from one address under the gap, what cannot go moves to its next window with the reason, a
    follow-up keeps its opener's zone and looks at its thread first, a sign-in this machine cannot
    read is left alone, an email stuck in 'sending' is swept, and switching the window off clears
    the times

Exit code 1 on any failure.
"""
import argparse
import base64
import contextlib
import email
import email.header
import io
import json
import os
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
# This machine plays the laptop (not the server: outreach.on_the_server) unless a check says otherwise
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ.pop("SEND_LOOP_ENABLED", None)


def run_logged(args):
    """cmd_send, its output echoed, -> (rc, the run's summary line as a dict: tools/outreach.py SUMMARY_TAG)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = outreach.cmd_send(args)
    text = out.getvalue()
    sys.stdout.write(text)
    tagged = [ln for ln in text.splitlines() if ln.startswith(outreach.SUMMARY_TAG)]
    return rc, (json.loads(tagged[-1][len(outreach.SUMMARY_TAG):]) if tagged else None)


def approver_mode(cur, gmail):
    """From the approver (owner, 2026-09-26): an email goes out from the Gmail of the person who approved
    it, the address of theirs with the most room first, each address up to its own daily limit; someone
    with no Gmail connected waits; nobody's approval ever leaves from somebody else's address."""
    import os
    import mailbox_store as store
    os.environ.setdefault("SESSION_SECRET", "zz-send-test-" + uuid.uuid4().hex)
    args = argparse.Namespace(limit=500)
    print("\n-- from the approver's own Gmail, each address with its own limit")
    # Legacy sender fixtures; strict Apollo gates are tested in test_apollo_constraints.
    slug = "zz-send-appr-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (approver)', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    # no sending window here, whatever the live config says: the window has its own section (window_mode)
    cur.execute("update segments set config = jsonb_set(config #- '{outreach,sending_paused}' #- '{outreach,send_window}',"
                " '{outreach,send_from}', '\"approver\"') where id = %s", (seg_id,))
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


def alias_mode(cur, gmail):
    """Sending as a Gmail alias (owner, 2026-10-15: "We can't login from LCX wala mail because it's an extension").
    The LCX address is a "Send mail as" alias inside the approver's TVF Gmail: the approver connects that account,
    and a project with outreach.send_as_domain sends through it with the alias in the From line -- read from Gmail,
    never a TVF address for an LCX email, the account's own limit counted."""
    import os
    import mailbox_store as store
    os.environ.setdefault("SESSION_SECRET", "zz-send-test-" + uuid.uuid4().hex)
    args = argparse.Namespace(limit=500)
    print("\n-- sending as the account's alias on the project's domain (sql/36)")
    slug = "zz-send-alias-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (alias)', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(jsonb_set(config #- '{outreach,sending_paused}'"
                " #- '{outreach,send_window}', '{outreach,send_from}', '\"approver\"'),"
                " '{outreach,send_as_domain}', '\"zz-lcx.example\"') where id = %s", (seg_id,))
    outreach.SEGMENT = slug
    tag = uuid.uuid4().hex[:6]
    cara, dev = "zz-cara-%s@example.com" % tag, "zz-dev-%s@example.com" % tag
    for who_, name in ((cara, "Cara Lee"), (dev, "Dev Rao")):
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', %s, 'T')",
                    (who_, name))
    cara_acct, dev_acct = "cara.%s@zz-tvf.example" % tag, "dev.%s@zz-tvf.example" % tag
    alias = "cara.%s@zz-lcx.example" % tag

    def mailbox(owner, address, send_as):
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, send_as)"
                    " values (%s, %s, %s, 35, %s::jsonb) returning id",
                    (owner, address, store.encrypt({"refresh_token": "1//" + address}), send_as))
        return str(cur.fetchone()[0])
    cara_box = mailbox(cara, cara_acct, None)              # its aliases not read yet: the first send reads them
    mailbox(dev, dev_acct, "[]")                           # read: none on the project's domain
    outreach.user_gmail_service = lambda db, box: gmail
    gmail.send_as = [{"sendAsEmail": cara_acct.upper(), "isPrimary": True, "verificationStatus": "accepted"},
                     {"sendAsEmail": alias.upper(), "displayName": "Cara at LCX", "verificationStatus": "accepted"},
                     {"sendAsEmail": "pending.%s@zz-lcx.example" % tag, "verificationStatus": "pending"}]
    gmail.sendas_reads, gmail.rewrite_from = 0, None

    def approved_by(who_, step=0, parent=None, eid=None, cid=None):
        if eid is None:
            cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                        " (%s, %s, %s, 'test', 'shortlisted') returning id",
                        (seg_id, "ZZ alias " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay', %s,"
                        " 'valid') returning id", (eid, "kay.%s@zz-alias.example" % uuid.uuid4().hex[:6]))
            cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_at,"
                    " approved_by, approval_mode, sequence_step, parent_id, created_at) values (%s, %s, 't', 'Hello',"
                    " 'Hello Kay,\n\nBody', 'approved', now(), %s, 'single', %s, %s, clock_timestamp()) returning id",
                    (eid, cid, who_, step, parent))
        return cur.fetchone()[0], eid, cid

    def row(oid):
        cur.execute("select status, lower(sender_address), sent_as from outreach where id = %s", (oid,))
        return list(cur.fetchone())

    first, eid, cid = approved_by(cara)
    waits = approved_by(dev)[0]
    before = len(gmail.sent)
    run_logged(args)
    check("Cara's approval goes through her TVF account, as her LCX alias, named as Gmail names it",
          (row(first), [header(m, "From") for m in gmail.sent[before:]]),
          (["sent", cara_acct, alias], ["Cara at LCX <%s>" % alias]))
    cur.execute("select send_as from user_mailboxes where id = %s", (cara_box,))
    check("  her aliases read from Gmail once and kept: the verified one, not the primary, not a pending one",
          (cur.fetchone()[0], gmail.sendas_reads), ([{"address": alias, "name": "Cara at LCX"}], 1))
    check("  its Message-ID is on the alias's domain", gmail.sent[-1]["Message-ID"].endswith("@zz-lcx.example>"), True)
    check("Dev's Gmail has no address on the project's domain: his approval waits, nothing goes from his TVF address",
          (row(waits), dev_acct in [str(m["From"]).lower() for m in gmail.sent]), (["approved", None, None], False))
    second = approved_by(cara)[0]
    gmail.rewrite_from = cara_acct
    run_logged(args)
    check("Gmail does not accept the alias and sends as the account: what the recipient saw is recorded, not assumed",
          (row(second), gmail.sendas_reads), (["sent", cara_acct, None], 1))
    gmail.rewrite_from = None
    follow = approved_by(cara, step=1, parent=first, eid=eid, cid=cid)[0]
    run_logged(args)
    check("a follow-up keeps its thread's From: the alias", (row(follow)[0], row(follow)[2],
                                                            header(gmail.sent[-1], "From")),
          ("sent", alias, "Cara at LCX <%s>" % alias))
    cur.execute(store.OUT_TODAY_FOR_SQL, (cara_acct,))
    check("  the alias shares the account's daily limit: every one counted on the account", cur.fetchone()[0], 3)

    # A personal From selection works on an unrestricted project too. The alias
    # is verified live before sending; follow-ups retain their original identity.
    cur.execute("update segments set config = config #- '{outreach,send_as_domain}' where id=%s", (seg_id,))
    cur.execute("update user_mailboxes set from_address=%s where id=%s", (alias, cara_box))
    preferred, preferred_eid, preferred_cid = approved_by(cara)
    run_logged(args)
    check("a chosen alias sends through its parent on a project with no domain restriction",
          (row(preferred), header(gmail.sent[-1], "From")), (["sent", cara_acct, alias], "Cara at LCX <%s>" % alias))
    cur.execute("update user_mailboxes set from_address=null where id=%s", (cara_box,))
    direct = approved_by(cara)[0]
    run_logged(args)
    check("choosing the parent again restores its From address", row(direct), ["sent", cara_acct, None])
    pinned = approved_by(cara, step=1, parent=preferred, eid=preferred_eid, cid=preferred_cid)[0]
    run_logged(args)
    check("a follow-up retains its alias after the person's sender preference changes", row(pinned), ["sent", cara_acct, alias])
    cur.execute("update user_mailboxes set from_address=%s where id=%s", (alias, cara_box))
    gmail.send_as = []
    removed = approved_by(cara)[0]
    sent_before = len(gmail.sent)
    run_logged(args)
    check("Gmail removed the selected alias: approval waits and does not fall back to the parent",
          (row(removed)[0], len(gmail.sent) - sent_before), ("approved", 0))


def cc_mode(cur, gmail):
    """Copying someone (owner, 2026-10-22: "Make default cc to the email amritanshv@lightscameraexperiment.com and
    obvio make a toggle to switch that off"; sql/39): an email goes out with the copy list it was approved with --
    the project's default for one approved before CC existed -- never copying its own recipient or sender, and the
    list it went with is recorded."""
    import os
    import mailbox_store as store
    os.environ.setdefault("SESSION_SECRET", "zz-send-test-" + uuid.uuid4().hex)
    args = argparse.Namespace(limit=500)
    print("\n-- CC: the list it was approved with (sql/39)")
    slug = "zz-send-cc-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (cc)', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(jsonb_set(config #- '{outreach,sending_paused}'"
                " #- '{outreach,send_window}' #- '{outreach,send_as_domain}', '{outreach,send_from}', '\"approver\"'),"
                " '{outreach,default_cc}', '[\"boss@zz-cc.example\"]') where id = %s", (seg_id,))
    outreach.SEGMENT = slug
    tag = uuid.uuid4().hex[:6]
    who = "zz-ccp-%s@example.com" % tag
    acct = "ccp.%s@zz-mail.example" % tag
    cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', 'P', 'T')", (who,))
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap) values (%s, %s, %s, 35)",
                (who, acct, store.encrypt({"refresh_token": "1//" + acct})))
    outreach.user_gmail_service = lambda db, box: gmail

    def approved(cc):
        cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                    " (%s, %s, %s, 'test', 'shortlisted') returning id",
                    (seg_id, "ZZ cc " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
        eid = cur.fetchone()[0]
        to = "kay.%s@zz-ccto.example" % uuid.uuid4().hex[:6]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status, source, verifier) values"
                    " (%s, 'Kay', %s, 'valid', 'apollo', 'apollo') returning id", (eid, to))
        cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_at,"
                    " approved_by, approval_mode, created_at, cc) values (%s, %s, 't', 'Hello', 'Hello Kay,\n\nBody',"
                    " 'approved', now(), %s, 'single', clock_timestamp(), %s::text[]) returning id",
                    (eid, cid, who, [c.replace("{to}", to) for c in cc] if cc is not None else None))
        return cur.fetchone()[0], to

    rows = {"before": approved(None), "off": approved([]),
            "more": approved(["boss@zz-cc.example", "Partner@zz-cc.example", "{to}", acct])}
    before = len(gmail.sent)
    run_logged(args)
    sent = {header(m, "To"): m for m in gmail.sent[before:]}

    def cc_of(key):
        m = sent.get(rows[key][1])
        return None if m is None else header(m, "Cc")

    def stored(key):
        cur.execute("select status, cc from outreach where id = %s", (rows[key][0],))
        return list(cur.fetchone())
    check("approved before CC existed: copied to the project's default, and that recorded",
          (cc_of("before"), stored("before")), ("boss@zz-cc.example", ["sent", ["boss@zz-cc.example"]]))
    check("the default switched off: no Cc line at all", (cc_of("off"), stored("off")), (None, ["sent", []]))
    check("the default and someone added, never its own recipient or sender: all lower-case",
          (cc_of("more"), stored("more")[1]),
          ("boss@zz-cc.example, partner@zz-cc.example", ["boss@zz-cc.example", "partner@zz-cc.example"]))


def window_mode(cur, gmail):
    """The sending window (owner, 2026-10-12: "send mails to the sender's time region between 10 to 10:30AM and
    that must be randmized"): each approved email holds its own second inside its recipient's 10:00-10:30
    (send_after, sql/34) and goes then -- not before, not after its window, never two from one address under
    the gap -- and what cannot go in its window moves to the next one with the reason."""
    import time
    import mailbox_store as store
    import outreach_policy as pol
    import send_window as sw
    print("\n-- the sending window: each email at its own second, 10:00-10:30 on its recipient's clock")
    block = {"enabled": True, "start": "10:00", "end": "10:30", "timezone_of": "recipient",
             "sender_timezone": "Asia/Kolkata", "fallback_timezone": "America/New_York", "weekdays_only": True,
             "min_gap_seconds": 2, "min_lead_seconds": 120, "guidance": "test"}
    plan = sw.plan_key(sw.window_cfg({"send_window": block}))
    slug = "zz-send-win-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (window)', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(jsonb_set(config #- '{outreach,mailboxes}' #- '{outreach,send_from}'"
                " #- '{outreach,sending_paused}', '{outreach,daily_send_cap}', '10'), '{outreach,send_window}', %s::jsonb)"
                " where id = %s", (json.dumps(block), seg_id))
    outreach.SEGMENT = slug
    # each run stays a few seconds, as the app's send loop does: one that meets an address's gap waits it out
    args = argparse.Namespace(limit=500, stay=5, max_seconds=30)

    def approved(status="shortlisted", approver="test", seg=None):
        cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'test', %s)"
                    " returning id", (seg or seg_id, "ZZ win " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example",
                                      status))
        eid = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s, 'valid')"
                    " returning id", (eid, "kay.%s@zz-win.example" % uuid.uuid4().hex[:6]))
        cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_at,"
                    " approved_by, approval_mode, created_at) values (%s, %s, 't', 'Hello', 'Hello Kay,\n\nBody',"
                    " 'approved', now(), %s, 'single', clock_timestamp()) returning id", (eid, cid, approver))
        return cur.fetchone()[0], eid, cid

    def at(oid, after, before, tz="America/New_York"):
        """Its own moment and window end, seconds from the database's clock now."""
        cur.execute("update outreach set send_after = clock_timestamp() + make_interval(secs => %s),"
                    " send_before = clock_timestamp() + make_interval(secs => %s), send_tz = %s,"
                    " send_tz_reason = coalesce(send_tz_reason, 'test'), send_plan = %s where id = %s",
                    (after, before, tz, plan, oid))

    def timing(oid):
        cur.execute("select status, send_after > clock_timestamp(), send_reschedules, send_wait_why, send_error,"
                    " send_tz, send_tz_reason from outreach where id = %s", (oid,))
        return list(cur.fetchone())

    def follow_up(tz="Europe/London", reason="test: London"):
        """An opener sent in a London window five days ago, under this config, and its follow-up, approved,
        with no time yet."""
        oid, eid, cid = approved("contacted")
        cur.execute("update outreach set status = 'sent', sent_at = clock_timestamp() - interval '5 days',"
                    " gmail_thread_id = %s, gmail_message_id = %s, sender_mailbox = 'default', sender_address = %s,"
                    " send_tz = %s, send_tz_reason = %s, send_plan = %s where id = %s",
                    ("zz-wthread-" + uuid.uuid4().hex[:8], "zz-wmsg-" + uuid.uuid4().hex[:8], SENDER, tz, reason,
                     plan, oid))
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id,"
                    " approved_at, approved_by, created_at) values (%s, %s, 'Re: Hello', 'Again', 'approved', 1, %s,"
                    " now(), 'test', clock_timestamp()) returning id", (eid, cid, oid))
        return cur.fetchone()[0], eid

    a = approved()[0]; at(a, 600, 2400)                 # its moment is ten minutes away
    b = approved()[0]; at(b, -5, 1200)                  # due now
    c = approved()[0]; at(c, -2400, -600)               # its window passed unsent
    h = approved()[0]                                   # approved while the window was off: no time yet
    g = approved()[0]; at(g, -2400, -600)
    cur.execute("update outreach set status = 'send_unknown', send_error = 'timed out' where id = %s", (g,))

    # the claim, and sql/34's guard behind it, refuse an email outside its window
    cur.execute("update outreach set status = 'sending' where id = %s and status = 'approved'"
                " and send_after <= clock_timestamp() and clock_timestamp() < send_before returning id", (c,))
    check("a claim after its window is refused by the claim's own condition", cur.fetchone(), None)
    cur.execute("savepoint guard")
    try:
        cur.execute("update outreach set status = 'sending' where id = %s", (c,))
        raised = None
    except psycopg2.Error as e:
        raised = "send window" in str(e)
    cur.execute("rollback to savepoint guard")
    check("  and by the database itself (sql/34's trigger raises)", raised, True)

    cfg = pol.outreach_config(cur, slug)
    moved = pol.settle_schedule(cur, slug, cfg)
    check("the window passed unsent: moved to the next one at a new second, and says why",
          (timing(c)[:4], moved["moved"]), (["approved", True, 1, "the server did not send it in its window"], 1))
    check("  approved with no time: given one, in the future", (timing(h)[:3], moved["scheduled"]), (["approved", True, 0], 1))
    check("  one whose outcome is unknown is not touched", timing(g)[:3], ["send_unknown", False, 0])
    again = pol.settle_schedule(cur, slug, cfg)
    check("  a second settle moves nothing again", (again["moved"], again["scheduled"], timing(c)[2]), (0, 0, 1))

    n = len(gmail.sent)
    outreach.cmd_send(args)
    check("a run: the email due now goes, the one ten minutes away waits", (timing(b)[0], timing(a)[:3]),
          ("sent", ["approved", True, 0]))
    check("  the one given a time is not sent early", timing(h)[:2], ["approved", True])
    check("  one email went", len(gmail.sent) - n, 1)

    # never two from one address under the gap (2 s here): the second waits it out in the same run (--stay)
    d = approved()[0]; at(d, -5, 1200)
    e = approved()[0]; at(e, -4, 1200)
    t0 = time.monotonic()
    outreach.cmd_send(argparse.Namespace(limit=500, stay=20, max_seconds=60))
    took = time.monotonic() - t0
    cur.execute("select extract(epoch from (select sent_at from outreach where id = %s) - (select sent_at from outreach"
                " where id = %s))", (e, d))
    gap = cur.fetchone()[0]
    check("two due at once from one address: both go in one run, the second after the gap",
          (timing(d)[0], timing(e)[0], gap is not None and float(gap) >= 2.0, took < 30), ("sent", "sent", True, True))

    # a follow-up goes at its first email's clock, and looks at its thread before it goes
    fu, fu_eid = follow_up()
    pol.settle_schedule(cur, slug, cfg)
    check("a follow-up keeps its first email's time zone, and says so", timing(fu)[5:],
          ["Europe/London", "same as the first email: test: London"])
    # one whose first email went on the sender's clock (the project since switched to "recipient") is placed on
    # its recipient's: here the fallback zone, as its lead names no place (review, 2026-10-12)
    fu_s, _es = follow_up(tz="Asia/Kolkata", reason="sender's clock (India)")
    pol.settle_schedule(cur, slug, cfg)
    check("  not one whose first email went on the sender's clock: placed on its recipient's", timing(fu_s)[5:],
          ["America/New_York", "fallback: no location held"])
    cur.execute("update outreach set status = 'cancelled' where id = %s", (fu_s,))
    at(fu, -5, 1200, tz="Europe/London")
    reply_id = "zz-wreply-" + uuid.uuid4().hex[:8]
    gmail.thread = [{"id": "zz-ours", "labelIds": ["SENT"], "payload": {"headers": [{"name": "From", "value": SENDER}]}},
                    {"id": reply_id, "labelIds": ["INBOX"], "payload": {"headers": [{"name": "From",
                                                                                     "value": "Kay <kay@zz-win.example>"}]}}]
    n = len(gmail.sent)
    outreach.cmd_send(args)
    check("  a reply in its thread the app has not read yet: it waits for its next window, nothing sent",
          (timing(fu)[:4], len(gmail.sent) - n), (["approved", True, 1, "a reply in the thread is not read yet"], 0))
    cur.execute("insert into outreach (entity_id, direction, subject, body, status, triage, gmail_message_id)"
                " values (%s, 'inbound', 'Re: Hello', 'Out of office', 'triaged', 'neutral', %s)", (fu_eid, reply_id))
    at(fu, -5, 1200, tz="Europe/London")
    outreach.cmd_send(args)
    check("  once that reply is read as an auto-reply, it goes", timing(fu)[0], "sent")
    gmail.thread = None

    # review, 2026-10-12: a message in the thread from another of OUR addresses (a colleague's linked Gmail, the
    # project's other mailboxes) is ours, as the pull counts it -- never a reply waiting to be read
    ctag = uuid.uuid4().hex[:6]
    colleague, colleague_login = "zz-colleague-%s@zz-mail.example" % ctag, "zz-coll-%s@example.com" % ctag
    cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', 'C', 'T')",
                (colleague_login,))
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, enabled)"
                " values (%s, %s, 'sealed-for-the-server', 35, false)", (colleague_login, colleague))
    fu3, _e3 = follow_up()
    at(fu3, -5, 1200, tz="Europe/London")
    gmail.thread = [{"id": "zz-ours", "labelIds": ["SENT"], "payload": {"headers": [{"name": "From", "value": SENDER}]}},
                    {"id": "zz-coll-" + ctag, "labelIds": ["INBOX"],
                     "payload": {"headers": [{"name": "From", "value": "A Colleague <%s>" % colleague.upper()}]}}]
    outreach.cmd_send(args)
    check("  a message in its thread from another of our addresses is ours: the follow-up goes", timing(fu3)[0], "sent")
    # the thread cannot be read: tried again in its next window, never counted as an unread reply for ever
    fu4, _e4 = follow_up()
    at(fu4, -5, 1200, tz="Europe/London")
    gmail.thread = None                                 # the look raises
    outreach.cmd_send(args)
    check("  its thread cannot be read just now: it moves to its next window, saying that, not 'a reply'",
          timing(fu4)[:5], ["approved", True, 1,
                            "its thread could not be read just now (RuntimeError): it tries again in its next window", None])

    class Gone(Exception):
        resp = type("R", (), {"status": 404})()
    fu5, _e5 = follow_up()
    at(fu5, -5, 1200, tz="Europe/London")
    gmail.thread = Gone("HttpError 404: thread not found")
    n = len(gmail.sent)
    outreach.cmd_send(args)
    check("  its thread is gone from Gmail (404): parked with the reason, not sent blind",
          (timing(fu5)[0], timing(fu5)[4], len(gmail.sent) - n),
          ("approved", "its Gmail thread cannot be read (404): the follow-up is not sent", 0))
    gmail.thread = None

    # second review, 2026-10-12: the look at the thread refused because of the ADDRESS -- a revoked sign-in whose
    # cached access token has not run out yet (RefreshError), a permission taken away (403) -- is the address
    # refused, as at the send: out for the run, named for the alert, its emails moved with that reason. It used to
    # count as a passing problem with this one email, moved day after day, the owner told only after 3 moves
    class RevokedAtThread(Exception):
        pass
    RevokedAtThread.__name__ = "RefreshError"
    fu7, _e7 = follow_up()
    at(fu7, -5, 1200, tz="Europe/London")
    gmail.thread = RevokedAtThread("invalid_grant: Token has been expired or revoked.")
    n = len(gmail.sent)
    try:
        rc, summ = run_logged(args)
    finally:
        gmail.thread = None
    check("  its look at the thread refused for the address (a revoked sign-in): the address is refused, as at a send",
          (rc, timing(fu7)[:5], len(gmail.sent) - n),
          (0, ["approved", True, 1, "Gmail refused %s (sign-in)" % SENDER, None], 0))
    check("    and named in the run's last line, for the one alert", (summ or {}).get("refused"),
          {"default": "Gmail refused %s (sign-in)" % SENDER})

    class BarredAtThread(Exception):
        resp = type("R", (), {"status": 403})()
    fu8, _e8 = follow_up()
    at(fu8, -5, 1200, tz="Europe/London")
    gmail.thread = BarredAtThread("HttpError 403: Insufficient Permission")
    try:
        rc, summ = run_logged(args)
    finally:
        gmail.thread = None
    check("    a 403 that is not a rate limit: the same", (rc, timing(fu8)[3], sorted((summ or {}).get("refused") or {})),
          (0, "Gmail refused %s (403)" % SENDER, ["default"]))

    class SlowAtThread(Exception):
        resp = type("R", (), {"status": 403})()
        error_details = [{"reason": "userRateLimitExceeded"}]
    fu9, _e9 = follow_up()
    at(fu9, -5, 1200, tz="Europe/London")
    gmail.thread = SlowAtThread("HttpError 403: User Rate Limit Exceeded")
    try:
        rc, summ = run_logged(args)
    finally:
        gmail.thread = None
    check("    a 403 rate limit is passing: only this email moves, and no address is refused",
          (rc, timing(fu9)[3], (summ or {}).get("refused")),
          (0, "its thread could not be read just now (403): it tries again in its next window", {}))

    # Gmail refusing the address (429) in a timed run is handled, not a failed run (review, 2026-10-12): its email
    # moves with the reason, and the run's last line names the address for the send loop's one alert
    class Limited(Exception):
        resp = type("R", (), {"status": 429})()
    r429 = approved()[0]
    at(r429, -5, 1200)
    time.sleep(2.2)                                     # past the address's gap
    gmail.fail = Limited("HttpError 429: rate limit")
    try:
        rc, summ = run_logged(args)
    finally:
        gmail.fail = None
    check("Gmail refuses the address (429) in a timed run: the run does not fail, the email moves, saying why",
          (rc, timing(r429)[:4]), (0, ["approved", True, 1, "Gmail refused %s (429)" % SENDER]))
    check("  and its last line names the refused address, for the send loop's one alert",
          (summ or {}).get("refused"), {"default": "Gmail refused %s (429)" % SENDER})

    fu2, _e2 = follow_up()
    at(fu2, -5, 1200, tz="Europe/London")
    real_answered = pol.answered_elsewhere

    def window_closes(cur_, email, eid):
        # its window closes between the run picking it and claiming it
        cur_.execute("update outreach set send_after = clock_timestamp() - interval '2 minutes',"
                     " send_before = clock_timestamp() - interval '1 second' where id = %s", (fu2,))
        return real_answered(cur_, email, eid)
    pol.answered_elsewhere = window_closes
    time.sleep(2.2)                                     # past the address's gap, so the claim itself is what refuses
    try:
        outreach.cmd_send(args)
    finally:
        pol.answered_elsewhere = real_answered
    cur.execute("select status, stopped_reason from outreach where id = %s", (fu2,))
    check("a follow-up whose claim fails only because its window closed is not cancelled", list(cur.fetchone()),
          ["approved", None])

    # its address at the day's limit: moved to the next window, saying why, not sent late
    cur.execute("select count(*) from outreach o join entities en on en.id = o.entity_id where en.segment_id = %s"
                " and o.status = 'sent' and o.sent_at::date = current_date", (seg_id,))
    today = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(config, '{outreach,daily_send_cap}', %s::jsonb) where id = %s",
                (str(today), seg_id))
    f = approved()[0]; at(f, -5, 1200)
    outreach.cmd_send(args)
    check("the day's limit reached: it moves to its next window with the reason",
          timing(f)[:4], ["approved", True, 1, "the project's daily limit of %d was reached" % today])

    # from the approver: a sign-in this machine cannot read is the server's -- untouched, never marked
    tag = uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config) select %s, 'send test (window, approver)',"
                " 'company', (config - 'sourcing') from segments where id = %s returning id", ("zz-send-wina-" + tag, seg_id))
    seg2 = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(jsonb_set(config, '{outreach,send_from}', '\"approver\"'),"
                " '{outreach,daily_send_cap}', '35') where id = %s", (seg2,))
    people = {}
    for who, name in (("pia", "Pia"), ("quinn", "Quinn"), ("ravi", "Ravi")):
        people[who] = "zz-%s-%s@example.com" % (who, tag)
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', %s, 'T')",
                    (people[who], name))
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap) values (%s, %s, 'sealed-for-the-server', 35)"
                " returning id", (people["pia"], "pia.%s@zz-mail.example" % tag))
    pia_box = cur.fetchone()[0]
    ravi_addr = "ravi.%s@zz-mail.example" % tag
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap) values (%s, %s, %s, 35)",
                (people["ravi"], ravi_addr, store.encrypt({"refresh_token": "1//" + ravi_addr})))
    outreach.SEGMENT = "zz-send-wina-" + tag
    i_ = approved(approver=people["pia"], seg=seg2)[0]; at(i_, -5, 1200)
    j_ = approved(approver=people["quinn"], seg=seg2)[0]; at(j_, -5, 1200)
    k_ = approved(approver=people["ravi"], seg=seg2)[0]; at(k_, -5, 1200)
    before = timing(i_)
    outreach.cmd_send(args)
    cur.execute("select last_error from user_mailboxes where id = %s", (pia_box,))
    marked = cur.fetchone()[0]                          # read before timing() runs its own query
    check("from the approver: a sign-in not readable here leaves the email untouched, and the address unmarked",
          (timing(i_) == before, marked), (True, None))
    check("  someone with no sending address: moved to the next window, saying so",
          timing(j_)[:4], ["approved", True, 1, "Quinn has no sending address"])
    cur.execute("select status, lower(sender_address) from outreach where id = %s", (k_,))
    check("  and the one whose sign-in is here goes, from its approver's address", list(cur.fetchone()), ["sent", ravi_addr])

    # a follow-up whose thread's address the database says cannot send (it needs connecting again) is not left
    # alone all window for the loop to start runs for: it moves, saying so, on any machine (review, 2026-10-12)
    people["sam"] = "zz-sam-%s@example.com" % tag
    cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', 'Sam', 'T')",
                (people["sam"],))
    sam_addr = "sam.%s@zz-mail.example" % tag
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, last_error)"
                " values (%s, %s, %s, 35, 'sign-in: revoked')", (people["sam"], sam_addr, store.encrypt({"refresh_token": "1//x"})))
    so_, so_e, so_c = approved("contacted", approver=people["sam"], seg=seg2)
    cur.execute("update outreach set status = 'sent', sent_at = clock_timestamp() - interval '5 days', gmail_thread_id = %s,"
                " gmail_message_id = %s, sender_mailbox = %s, sender_address = %s where id = %s",
                ("zz-sthread-" + tag, "zz-smsg-" + tag, sam_addr, sam_addr, so_))
    cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id, approved_at,"
                " approved_by, created_at) values (%s, %s, 'Re: Hello', 'Again', 'approved', 1, %s, now(), %s,"
                " clock_timestamp()) returning id", (so_e, so_c, so_, people["sam"]))
    sfu = cur.fetchone()[0]
    at(sfu, -5, 1200)
    outreach.cmd_send(args)
    check("a follow-up whose thread's address needs connecting again moves, saying so (not left alone all window)",
          timing(sfu)[:4], ["approved", True, 1, "the thread's address %s needs connecting again" % sam_addr])

    # Second review, 2026-10-12: only SEND_LOOP_ENABLED=1 makes a run the server. The laptop's own Docker stack
    # (docker-compose.yml) has the scheduler on, reaches the live database with the laptop's SESSION_SECRET and
    # says SEND_LOOP_ENABLED=0: its runs must leave every address it cannot read alone, never mark them all
    real_boxes = store.mailboxes
    pia_addr = "pia.%s@zz-mail.example" % tag
    for env_now in ({"SCHEDULER_ENABLED": "1"}, {"SCHEDULER_ENABLED": "1", "SEND_LOOP_ENABLED": "0"}):
        store.mailboxes = lambda *a, **k: [b for b in real_boxes(*a, **k) if tag in b["address"]]
        saved = {k_: os.environ.get(k_) for k_ in ("SCHEDULER_ENABLED", "SEND_LOOP_ENABLED")}
        os.environ.update(env_now)
        try:
            rc, summ = run_logged(args)
        finally:
            for k_, v_ in saved.items():
                if v_ is None:
                    os.environ.pop(k_, None)
                else:
                    os.environ[k_] = v_
            store.mailboxes = real_boxes
        cur.execute("select last_error from user_mailboxes where id = %s", (pia_box,))
        marked = cur.fetchone()[0]
        check("  not the server (%s): an address it cannot read is left alone, unmarked, its email untouched"
              % " ".join("%s=%s" % kv for kv in sorted(env_now.items())),
              (rc, marked, timing(i_) == before, str(i_) in ((summ or {}).get("left_alone") or [])), (0, None, True, True))

    # second review, 2026-10-12: another machine's due email past the point where a run stops (here Gmail refuses
    # this machine's one readable address, so the pass breaks off) is still named as left alone -- the send loop
    # starts a run for any due email missing from left_alone, and one left out made it start one every few seconds
    r_ = approved(approver=people["ravi"], seg=seg2)[0]
    at(r_, -600, 1200)                                  # due before Pia's, so the pass reaches it first

    class Limited2(Exception):
        resp = type("R", (), {"status": 429})()
    gmail.fail = Limited2("HttpError 429: rate limit")
    store.mailboxes = lambda *a, **k: [b for b in real_boxes(*a, **k) if tag in b["address"]]
    try:
        rc, summ = run_logged(args)
    finally:
        gmail.fail = None
        store.mailboxes = real_boxes
    check("a pass that breaks off (its one readable address refused): another machine's due email is still left alone",
          (rc, timing(r_)[3], str(i_) in ((summ or {}).get("left_alone") or []), timing(i_) == before),
          (0, "Gmail refused %s (429)" % ravi_addr, True, True))

    # and a "server" that can read none of several sign-ins holds the wrong SESSION_SECRET (a second deployment, a
    # secret that changed), not that many damaged rows: nothing is marked, the run fails loudly, the emails wait
    tag2 = uuid.uuid4().hex[:6]
    cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'x', 'member', 'Tess', 'T')",
                ("zz-tess-%s@example.com" % tag2,))
    cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap)"
                " values (%s, %s, 'sealed-for-another-server', 35) returning id",
                ("zz-tess-%s@example.com" % tag2, "tess.%s@zz-mail.example" % tag2))
    tess_box = cur.fetchone()[0]
    store.mailboxes = lambda *a, **k: [b for b in real_boxes(*a, **k)
                                       if b["address"].lower() in (pia_addr, "tess.%s@zz-mail.example" % tag2)]
    os.environ["SEND_LOOP_ENABLED"] = "1"
    try:
        rc, summ = run_logged(args)
    finally:
        os.environ.pop("SEND_LOOP_ENABLED", None)
        store.mailboxes = real_boxes
    cur.execute("select count(*) from user_mailboxes where id in (%s, %s) and last_error is not null", (pia_box, tess_box))
    n_marked = cur.fetchone()[0]
    check("a server that can read none of several sign-ins: nothing marked, the run fails, the email waits untouched",
          (rc, n_marked, timing(i_) == before, str(i_) in ((summ or {}).get("left_alone") or [])), (1, 0, True, True))
    cur.execute("delete from user_mailboxes where id = %s", (tess_box,))

    # the same unreadable sign-in ON THE SERVER: marked "connect it again" at once, as before the window (review,
    # 2026-10-12) -- the run handles it (its email moves, saying so) and does not fail. Only this test's
    # addresses are looked at here, so no live row is touched even inside the rolled-back transaction
    store.mailboxes = lambda *a, **k: [b for b in real_boxes(*a, **k) if tag in b["address"]]
    os.environ["SEND_LOOP_ENABLED"] = "1"
    try:
        rc, summ = run_logged(args)
    finally:
        os.environ.pop("SEND_LOOP_ENABLED", None)
        store.mailboxes = real_boxes
    cur.execute("select last_error from user_mailboxes where id = %s", (pia_box,))
    marked = cur.fetchone()[0] or ""
    check("on the server, a sign-in it cannot read is marked to connect again; its email moves, saying so",
          ("cannot be read on the server" in marked, timing(i_)[:4]),
          (True, ["approved", True, 1, "Pia's sending address needs linking again"]))
    check("  handled, not a failed run, and named for the loop's one alert",
          (rc, sorted((summ or {}).get("refused") or {})), (0, ["pia.%s@zz-mail.example" % tag]))

    # an email left in 'sending' (a send that died between its claim and Gmail's answer)
    outreach.SEGMENT = slug
    s_ = approved()[0]
    cur.execute("update outreach set status = 'sending', updated_at = clock_timestamp() - interval '20 minutes'"
                " where id = %s", (s_,))
    swept = pol.sweep_stale_sending(cur)
    cur.execute("select status, send_error like 'left in sending for 15 minutes%%' from outreach where id = %s", (s_,))
    check("left in 'sending' for 15 minutes: marked unknown, to check Gmail's Sent before resending",
          (swept >= 1, list(cur.fetchone())), (True, ["send_unknown", True]))

    # the window switched off: the times are cleared, and they go as soon as they can, as before
    cur.execute("update segments set config = jsonb_set(jsonb_set(config, '{outreach,send_window,enabled}', 'false'),"
                " '{outreach,daily_send_cap}', '50') where id = %s", (seg_id,))
    outreach.cmd_send(args)
    cur.execute("select count(*) from outreach o join entities en on en.id = o.entity_id where en.segment_id = %s"
                " and o.status = 'approved' and o.send_after is not null", (seg_id,))
    check("the window switched off: no times left, and the waiting ones go out",
          (cur.fetchone()[0], timing(a)[0], timing(f)[0], timing(h)[0]), (0, "sent", "sent", "sent"))
    check("  the one of unknown outcome is still left for a person", timing(g)[0], "send_unknown")

    # a run with no window (its config read at its start) whose follow-up was just given a time by another
    # process -- the window switched on, the send loop's settle -- leaves it for its window: the claim failing
    # is not the reply guard, and it is never cancelled (review, 2026-10-12)
    fu6, _e6 = follow_up()

    def scheduled_meanwhile(cur_, email_, eid_):
        cur_.execute("update outreach set send_after = clock_timestamp() + interval '1 hour',"
                     " send_before = clock_timestamp() + interval '90 minutes', send_tz = 'Europe/London'"
                     " where id = %s and send_after is null", (fu6,))
        return real_answered(cur_, email_, eid_)
    pol.answered_elsewhere = scheduled_meanwhile
    try:
        outreach.cmd_send(args)
    finally:
        pol.answered_elsewhere = real_answered
    cur.execute("select status, stopped_reason from outreach where id = %s", (fu6,))
    check("a run with no window whose follow-up was just given a time elsewhere: left for its window, not cancelled",
          list(cur.fetchone()), ["approved", None])


def pool_elsewhere(cur, gmail):
    """The pool (review, 2026-10-12): a mailbox whose token is on another machine is not full. When this machine's
    mailboxes are at their cap and another's still has room by the database's count, the emails are left for that
    machine, untouched; "every mailbox was at its daily limit" is said only when it is true."""
    import outreach_policy as pol
    import send_window as sw
    print("\n-- the pool: a mailbox connected only on another machine, with room left")
    block = {"enabled": True, "start": "10:00", "end": "10:30", "timezone_of": "recipient",
             "sender_timezone": "Asia/Kolkata", "fallback_timezone": "America/New_York", "weekdays_only": True,
             "min_gap_seconds": 2, "min_lead_seconds": 120, "guidance": "test"}
    plan = sw.plan_key(sw.window_cfg({"send_window": block}))
    boxes = [{"key": "main", "email_env": "ZZ_MAIN_SENDER_ADDRESS", "daily_cap": 1},
             {"key": "second", "email_env": "ZZ_SECOND_SENDER_ADDRESS", "daily_cap": 3}]
    slug = "zz-send-pool-" + uuid.uuid4().hex[:6]
    cur.execute("insert into segments (slug, name, entity_type, config)"
                " select %s, 'send test (pool)', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                " returning id", (slug,))
    seg_id = cur.fetchone()[0]
    cur.execute("update segments set config = jsonb_set(jsonb_set(jsonb_set(config #- '{outreach,send_from}'"
                " #- '{outreach,sending_paused}', '{outreach,daily_send_cap}', '50'), '{outreach,mailboxes}', %s::jsonb),"
                " '{outreach,send_window}', %s::jsonb) where id = %s", (json.dumps(boxes), json.dumps(block), seg_id))
    outreach.SEGMENT = slug

    def mail(status="approved", box=None):
        cur.execute("insert into entities (segment_id, name, domain, source, status) values (%s, %s, %s, 'test', %s)"
                    " returning id", (seg_id, "ZZ pool " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example",
                                      "shortlisted" if status == "approved" else "contacted"))
        eid = cur.fetchone()[0]
        cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s, 'valid')"
                    " returning id", (eid, "kay.%s@zz-pool.example" % uuid.uuid4().hex[:6]))
        cid = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_at,"
                    " approved_by, approval_mode, created_at, sent_at, sender_mailbox, sender_address) values"
                    " (%s, %s, 't', 'Hello', 'Hello Kay,\n\nBody', %s, now(), 'test', 'single', clock_timestamp(),"
                    " case when %s = 'sent' then clock_timestamp() end, %s, %s) returning id",
                    (eid, cid, status, status, box, SENDER if box else None))
        return cur.fetchone()[0]

    def timing(oid):
        cur.execute("select status, send_after > clock_timestamp(), send_reschedules, send_wait_why from outreach"
                    " where id = %s", (oid,))
        return list(cur.fetchone())

    mail("sent", "main")                                # main has sent its one for today
    due = mail()
    cur.execute("update outreach set send_after = clock_timestamp() - interval '5 seconds', send_before ="
                " clock_timestamp() + interval '20 minutes', send_tz = 'America/New_York', send_tz_reason = 'test',"
                " send_plan = %s where id = %s", (plan, due))
    # a follow-up in a thread the other machine's mailbox started, due now: only that machine can send it
    opener = mail("sent", "second")
    cur.execute("update outreach set gmail_thread_id = %s where id = %s", ("zz-pthread-" + uuid.uuid4().hex[:6], opener))
    cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id, approved_at,"
                " approved_by, created_at, send_after, send_before, send_tz, send_tz_reason, send_plan)"
                " select entity_id, contact_id, 'Re: Hello', 'Again', 'approved', 1, id, now(), 'test', clock_timestamp(),"
                " clock_timestamp() - interval '5 seconds', clock_timestamp() + interval '20 minutes', 'America/New_York',"
                " 'test', %s from outreach where id = %s returning id", (plan, opener))
    theirs = cur.fetchone()[0]
    real_connected = outreach.mailbox_connected
    outreach.mailbox_connected = lambda mb: mb["key"] == "main"   # second's token is on another machine
    args = argparse.Namespace(limit=500, stay=0, max_seconds=30)
    try:
        rc, summ = run_logged(args)
        check("this machine's mailbox at its cap, another's with room: the email is left for that machine, untouched",
              (rc, timing(due), str(due) in ((summ or {}).get("left_alone") or [])),
              (0, ["approved", False, 0, None], True))
        # second review, 2026-10-12: the run stopping early (no room here) still names the other machine's follow-up
        # as left alone, so the send loop does not start a run for it every few seconds all window
        check("  and the follow-up in the other machine's thread is named as left alone too, untouched",
              (timing(theirs), str(theirs) in ((summ or {}).get("left_alone") or [])),
              (["approved", False, 0, None], True))
        for _ in range(3):
            mail("sent", "second")                      # the other machine sends second's three
        rc, summ = run_logged(args)
        check("  every mailbox at its cap by the database's count: now it moves, saying so",
              (rc, timing(due)), (0, ["approved", True, 1, "every mailbox was at its daily limit"]))
    finally:
        outreach.mailbox_connected = real_connected


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
    """users().messages().send(...).execute() records the raw message; fail= makes it raise.
    users().threads().get(...).execute() answers with .thread (a follow-up's look at its thread)."""

    def __init__(self):
        self.sent, self.fail, self.thread = [], None, None
        self._kind = self._op = None
        # users.settings.sendAs (sql/36) and the From Gmail puts on a sent message (None: the one it was given)
        self.send_as, self.rewrite_from, self.sendas_reads = [], None, 0

    def users(self):
        return self

    def settings(self):
        self._kind = "settings"
        return self

    def sendAs(self):
        return self

    def list(self, userId):
        self._op = "sendas"
        return self

    def messages(self):
        self._kind = "messages"
        return self

    def threads(self):
        self._kind = "threads"
        return self

    def send(self, userId, body):
        self._body, self._op = body, "send"
        return self

    def get(self, **kw):
        if self._kind == "threads":
            self._op = "thread"
            return self
        if self._kind == "messages" and kw.get("metadataHeaders") == ["From"]:
            self._op = "readback"                     # the sender reads back an alias send's From line
            return self
        raise RuntimeError("no previous message in the test")

    def execute(self):
        if self._op == "sendas":
            self._op = None
            self.sendas_reads += 1
            return {"sendAs": self.send_as}
        if self._op == "readback":
            self._op = None
            return {"payload": {"headers": [{"name": "From", "value": self.rewrite_from or self.sent[-1]["From"]}]}}
        if self._op == "thread":
            self._op = None
            if self.thread is None:
                raise RuntimeError("no thread in the test")
            if isinstance(self.thread, Exception):
                raise self.thread
            return {"messages": self.thread}
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
                        " select %s, 'send test', 'company', (config - 'sourcing') from segments where slug = 'us-production-houses'"
                        " returning id", (slug,))
            seg_id = cur.fetchone()[0]
            # the project's own mailbox (the pool), whatever the live config says: sending from each
            # approver's own address has its own section below (approver_mode)
            cur.execute("update segments set config = jsonb_set(config #- '{outreach,mailboxes}' #- '{outreach,send_from}'"
                        " #- '{outreach,send_window}', '{outreach,daily_send_cap}', '3') where id = %s", (seg_id,))
            outreach.SEGMENT = slug

            def approved(subject="From TVF in India: café notes", body=None, address=None, status="shortlisted",
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
                text = body or "Hello Kay,\n\nI’m writing on behalf of Kartikeya: café test.\n\nVedansh"
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
                  [m["To"], m["From"], header(m, "Subject")], [rows[0][2], SENDER, "From TVF in India: café notes"])
            check("  the body as written, in UTF-8", m.get_payload(decode=True).decode(m.get_content_charset()),
                  "Hello Kay,\n\nI’m writing on behalf of Kartikeya: café test.\n\nVedansh")
            # copied to the project's default CC and nobody else (owner, 2026-10-22; sql/39), never blind-copied
            cur.execute("select config #> '{outreach,default_cc}' from segments where slug = %s", (outreach.SEGMENT,))
            want_cc = ", ".join(cur.fetchone()[0] or []) or None
            check("  copied only to the project's default CC, nobody blind-copied", [m.get("Cc"), m.get("Bcc")],
                  [want_cc, None])
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

            # ------------------------------------- an answer from them, elsewhere, since approval
            print("\n-- an address that answered us in another project since it was approved")
            cur.execute("insert into segments (slug, name, entity_type, config) select %s, 'send test other', 'company',"
                        " (config - 'sourcing') from segments where slug = 'us-production-houses' returning id",
                        ("zz-send-other-" + uuid.uuid4().hex[:6],))
            other_seg = cur.fetchone()[0]

            def answered_elsewhere():
                """Their reply ("no thanks") to another project's email -> the address."""
                addr = "lee.%s@zz-send-test.example" % uuid.uuid4().hex[:6]
                cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                            " (%s, %s, %s, 'test', 'contacted') returning id",
                            (other_seg, "ZZ other " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
                oe = cur.fetchone()[0]
                cur.execute("insert into contacts (entity_id, full_name, email, email_status) values"
                            " (%s, 'Lee Doe', %s, 'valid') returning id", (oe, addr))
                oc = cur.fetchone()[0]
                cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, triage)"
                            " values (%s, %s, 'inbound', 'Re: hello', 'No thanks', 'triaged', 'negative')", (oe, oc))
                return addr

            opener_to = approved(address=answered_elsewhere().upper())
            fu_ent = approved(address=answered_elsewhere())          # a thread here, whose follow-up is due
            cur.execute("update outreach set status = 'sent', sent_at = now() - interval '5 days', gmail_thread_id = %s,"
                        " gmail_message_id = %s where id = %s",
                        ("zz-thread-" + uuid.uuid4().hex[:8], "zz-msg-" + uuid.uuid4().hex[:8], fu_ent[0]))
            cur.execute("update entities set status = 'contacted' where id = %s", (fu_ent[1],))
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sequence_step, parent_id,"
                        " approved_at, approved_by, created_at) select entity_id, contact_id, 'Re: ' || subject, 'Again',"
                        " 'approved', 1, id, now(), 'test', clock_timestamp() from outreach where id = %s returning id",
                        (fu_ent[0],))
            fu = cur.fetchone()[0]
            n = len(gmail.sent)
            outreach.cmd_send(args)
            cur.execute("select send_error from outreach where id = %s", (opener_to[0],))
            parked_why = cur.fetchone()[0]                       # read before state() runs its own query
            check("a first email to them is parked, with the reason", (state(opener_to[0])[:2], parked_why),
                  (["approved", True], "this address has replied to an earlier email from us: answer them in that thread"))
            cur.execute("select status, stopped_reason from outreach where id = %s", (fu,))
            check("  a follow-up to them is cancelled, with the reason", list(cur.fetchone()),
                  ["cancelled", "this address has replied to an earlier email from us: answer them in that thread"])
            check("  and nothing went to them", len(gmail.sent) - n, 0)

            # ------------------------------------------------------------ an attached deck
            print("\n-- an email with the deck attached (LCX Services)")
            import outreach_policy as pol
            deck = pol.attachment_record("docs/decks/LCX Services - pitch deck.pdf")
            with_deck = approved(subject="18 things LCX can do for you", body="Hi Kay,\n\nOur services deck is attached.")
            cur.execute("update outreach set attachments = %s where id = %s", (json.dumps([deck]), with_deck[0]))
            changed = approved(subject="A deck changed after approval")
            cur.execute("update outreach set attachments = %s where id = %s",
                        (json.dumps([dict(deck, sha256="0" * 64)]), changed[0]))
            n = len(gmail.sent)
            outreach.cmd_send(args)
            check("the email with the deck is sent", state(with_deck[0])[0], "sent")
            m = next((x for x in gmail.sent[n:] if x["To"] == with_deck[2]), None)
            parts = [(p.get_content_type(), p.get_filename()) for p in m.walk() if not p.is_multipart()] if m else None
            check("  as its text and the deck, named as it was approved", parts,
                  [("text/plain", None), ("application/pdf", "LCX Services - pitch deck.pdf")])
            pdf = next(p for p in m.walk() if p.get_content_type() == "application/pdf").get_payload(decode=True) if m else b""
            check("  the deck's bytes, unchanged", pdf == pol.attachment_bytes(deck), True)
            check("  the text as written", next(p for p in m.walk() if p.get_content_type() == "text/plain")
                  .get_payload(decode=True).decode("utf-8") if m else None, "Hi Kay,\n\nOur services deck is attached.")
            cur.execute("select send_error from outreach where id = %s", (changed[0],))
            held = cur.fetchone()[0]                             # read before state() runs its own query
            check("a deck that changed after approval holds the email back, with the reason", (state(changed[0])[:2], held),
                  (["approved", True], "the attached LCX Services - pitch deck.pdf has changed since this email was approved"))
            check("  and it was not sent", any(x["To"] == changed[2] for x in gmail.sent[n:]), False)
            cur.execute("update outreach set sent_at = sent_at - interval '2 days' where id = %s", (with_deck[0],))

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
            alias_mode(cur, gmail)
            cc_mode(cur, gmail)
            window_mode(cur, gmail)
            pool_elsewhere(cur, gmail)
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
