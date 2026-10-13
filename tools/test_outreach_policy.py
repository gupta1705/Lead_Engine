#!/usr/bin/env python3
"""test_outreach_policy.py -- follow-ups and batch approval against the real
database, inside one transaction that is rolled back at the end.

    python tools/test_outreach_policy.py

Nothing it creates survives: a throwaway company, contacts and outreach rows
are inserted, every rule is exercised, then ROLLBACK. It needs sql/23 applied
and the lcx-clipping config synced (follow_ups and batch_approval on).
Exit code 1 on any failure.
"""
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg2
import outreach_policy as pol
from run_sql import load_db_url

SEG = "lcx-clipping"
SECRET = b"test-secret"
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("   (%s)" % detail) if detail and not cond else ""))


def main():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    now = dt.datetime.now(dt.timezone.utc)
    try:
        cfg = pol.outreach_config(cur, SEG)
        steps = pol.followup_steps(cfg)
        policy = pol.batch_policy(cfg)
        check("lcx-clipping has two follow-up steps", len(steps) == 2, steps)
        check("lcx-clipping has batch approval", policy is not None)
        tvf = pol.outreach_config(cur, "us-production-houses")
        check("TVF keeps one touch (no follow-ups)", pol.followup_steps(tvf) == [])
        check("TVF keeps single approval", pol.batch_policy(tvf) is None)

        cur.execute("select id from segments where slug=%s", (SEG,))
        seg_id = cur.fetchone()[0]

        def company(status):
            cur.execute("insert into entities (segment_id, name, source, status) values (%s,%s,'test',%s) returning id",
                        (seg_id, "ZZ policy test " + uuid.uuid4().hex[:8], status))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, is_primary) values (%s,'Pat Doe',%s,true) returning id",
                        (eid, "pat.%s@example.com" % uuid.uuid4().hex[:6]))
            return eid, cur.fetchone()[0]

        # ---------------------------------------------------------- follow-ups
        eid, cid = company("contacted")
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, gmail_thread_id,"
                    " gmail_message_id) values (%s,%s,'Opener subject','b','sent', now() - interval '10 days',"
                    " 'thread-test', %s) returning id", (eid, cid, "m-" + uuid.uuid4().hex))
        opener = cur.fetchone()[0]

        def due_for():
            return [(r, s) for r, s in pol.due_followups(cur, SEG, steps, now) if r["entity_id"] == eid]

        d = due_for()
        check("opener sent 10 days ago -> follow-up 1 due", len(d) == 1 and d[0][1]["step"] == 1, d)
        f1 = pol.insert_followup(cur, d[0][0], 1, steps[0]["template"], "Re: Opener subject", "fu1")
        check("follow-up 1 drafted", f1 is not None)
        check("a second follow-up 1 is refused by the unique index",
              pol.insert_followup(cur, d[0][0], 1, steps[0]["template"], "x", "y") is None)
        check("nothing due while a follow-up is pending", due_for() == [])

        cur.execute("update outreach set status='sent', sent_at=now() - interval '3 days' where id=%s", (f1,))
        check("follow-up 1 sent 3 days ago -> step 2 not due yet (7 days)", due_for() == [])
        cur.execute("update outreach set sent_at=now() - interval '8 days' where id=%s", (f1,))
        d = due_for()
        check("follow-up 1 sent 8 days ago -> follow-up 2 due", len(d) == 1 and d[0][1]["step"] == 2, d)

        cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, gmail_message_id,"
                    " gmail_thread_id) values (%s,%s,'inbound','Re','out of office','received',%s,'thread-test') returning id",
                    (eid, cid, "r-" + uuid.uuid4().hex))
        reply = cur.fetchone()[0]
        check("an untriaged reply pauses the thread", due_for() == [])
        cur.execute("update outreach set status='triaged', triage='neutral' where id=%s", (reply,))
        check("an auto-reply (neutral) lets it resume", len(due_for()) == 1)

        f2 = pol.insert_followup(cur, due_for()[0][0], 2, steps[1]["template"], "Re: Opener subject", "fu2")
        cur.execute("update outreach set status='approved' where id=%s", (f2,))
        cur.execute("update outreach set triage='negative' where id=%s", (reply,))
        cur.execute("update outreach set status='sending' where id=%s and status='approved' returning id", (f2,))
        check("database guard refuses to send a follow-up after a real reply", cur.fetchone() is None)
        cur.execute("select status from outreach where id=%s", (f2,))
        check("the refused follow-up is still unsent", cur.fetchone()[0] == "approved")

        n = pol.stop_thread(cur, eid, "reply: negative")
        cur.execute("select stopped_reason from outreach where id=%s", (opener,))
        check("stop_thread marks the opener", cur.fetchone()[0] == "reply: negative")
        cur.execute("select status from outreach where id=%s", (f2,))
        check("stop_thread cancels the pending follow-up", cur.fetchone()[0] == "cancelled" and n == 1)
        cur.execute("update outreach set triage='neutral' where id=%s", (reply,))
        check("a stopped thread stays stopped even if the reply is re-labelled", due_for() == [])

        # pause_on_reply cancels pending follow-ups without stopping the thread
        eid_p, cid_p = company("contacted")
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, gmail_thread_id)"
                    " values (%s,%s,'S','b','sent', now() - interval '10 days','t-p') returning id", (eid_p, cid_p))
        op_p = cur.fetchone()[0]
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, sequence_step, parent_id)"
                    " values (%s,%s,'Re: S','x',1,%s) returning id", (eid_p, cid_p, op_p))
        fu_p = cur.fetchone()[0]
        check("pause_on_reply cancels one pending follow-up", pol.pause_on_reply(cur, eid_p) == 1)
        cur.execute("select o.stopped_reason, f.stopped_reason from outreach o, outreach f where o.id=%s and f.id=%s", (op_p, fu_p))
        a, b = cur.fetchone()
        check("pause leaves the thread open and says why", a is None and b == "paused: reply received")

        # structural guards
        other, other_c = company("contacted")
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status) values (%s,%s,'S','b','sent') returning id",
                    (other, other_c))
        foreign = cur.fetchone()[0]
        cur.execute("savepoint sp")
        try:
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, sequence_step, parent_id)"
                        " values (%s,%s,'x','y',1,%s)", (eid, cid, foreign))
            check("a follow-up pointing at another company's opener is refused", False)
        except psycopg2.Error:
            check("a follow-up pointing at another company's opener is refused", True)
        cur.execute("rollback to savepoint sp")
        try:
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, sequence_step, parent_id)"
                        " values (%s,%s,'x','y',4,%s)", (eid, cid, opener))
            check("more than three follow-ups is refused by the CHECK", False)
        except psycopg2.Error:
            check("more than three follow-ups is refused by the CHECK", True)
        cur.execute("rollback to savepoint sp")
        try:
            cur.execute("insert into outreach (entity_id, contact_id, subject, body) values (%s,%s,'second opener','z')",
                        (eid, cid))
            check("a second opener to the same company is still impossible", False)
        except psycopg2.Error:
            check("a second opener to the same company is still impossible", True)
        cur.execute("rollback to savepoint sp")

        # ------------------------------------------------------- batch approval
        drafts = []
        for i in range(5):
            e2, c2 = company("shortlisted")
            body = "Hi Pat, a clean draft." if i else "Hi {{greeting_name}}, broken."
            cur.execute("insert into outreach (entity_id, contact_id, subject, body) values (%s,%s,'Subject',%s) returning id",
                        (e2, c2, body))
            drafts.append(str(cur.fetchone()[0]))
        ok, skipped = pol.check_drafts(cur, drafts, SEG)
        check("check_drafts passes the four clean drafts", len(ok) == 4, ok)
        check("check_drafts skips the one with a placeholder",
              len(skipped) == 1 and "placeholder" in skipped[0]["reason"], skipped)
        ok_tvf, sk_tvf = pol.check_drafts(cur, drafts, "us-production-houses")
        check("drafts from another segment are refused", ok_tvf == [] and len(sk_tvf) == 5)

        sample, token = pol.draw_sample(ok, policy, SECRET, "tester@x", SEG)
        check("sample size is max(3, 10%) of four = 3", len(sample) == 3 and set(sample) <= set(ok), sample)
        check("the signature verifies", pol.verify_sample(ok, sample, token, SECRET, "tester@x", SEG))
        other_sample = sorted(set(ok) - set(sample))[:1] + sample[1:]
        check("a swapped sample is rejected", not pol.verify_sample(ok, other_sample, token, SECRET, "tester@x", SEG))
        check("another user's token is rejected", not pol.verify_sample(ok, sample, token, SECRET, "someone@else", SEG))
        check("a changed batch is rejected", not pol.verify_sample(ok[:3], sample, token, SECRET, "tester@x", SEG))

        # the sending window (owner, 2026-10-12) as the repo has it for this project, inside this transaction
        # only: approving draws each one's own second in its recipient's window
        block = json.loads((Path(__file__).resolve().parent.parent / "config" / ("segment.%s.json" % SEG))
                           .read_text(encoding="utf-8"))["outreach"].get("send_window")
        cur.execute("update segments set config = jsonb_set(config, '{outreach,send_window}', %s::jsonb) where slug = %s",
                    (json.dumps(block), SEG))
        batch_id, approved, schedule = pol.apply_batch(cur, ok, sample, "tester@x", SEG, len(drafts), skipped)
        check("four drafts approved", approved == 4)
        cur.execute("select count(*) from outreach where approval_batch = %s and send_after is not null"
                    " and send_before > send_after and send_tz is not null and send_tz_reason is not null", (batch_id,))
        check("each approved one holds its own moment in its recipient's window, with its zone and why",
              (cur.fetchone()[0], len(schedule)) == (4, 4), schedule)
        check("  and the page's words for it: \"Tue 14 Oct, 10:17 New York time (19:47 IST)\"",
              all(v and v["send_label"] and " time" in v["send_label"] for v in schedule.values()), schedule)

        # moved for the same reason again and again: the third move is told (review, 2026-10-12), as a missed
        # window's is -- never moved for ever in silence
        wcfg_seg = pol.outreach_config(cur, SEG)
        moved_id = sorted(schedule)[0]
        cur.execute("update outreach set send_reschedules = 2 where id = %s", (moved_id,))
        told = []
        n_moved = pol.defer_rows(cur, [moved_id], wcfg_seg, SEG, "test: its address was at its daily limit", alerts=told)
        cur.execute("select send_reschedules, send_wait_why from outreach where id = %s", (moved_id,))
        check("defer_rows: moved to its next window with the reason, and its third move is told",
              (n_moved, cur.fetchone(), told) == (1, (3, "test: its address was at its daily limit"), [moved_id]),
              (n_moved, told))
        told = []
        other_id = sorted(schedule)[1]
        pol.defer_rows(cur, [other_id], wcfg_seg, SEG, "test", alerts=told)
        check("  a first move is not told", told == [], told)

        # the page's words for an approved email that will not go (review, 2026-10-12): held, never a time
        import send_window as sw
        wcfg = sw.window_cfg(wcfg_seg)
        cur.execute("select id, status, send_after, send_before, send_tz, send_tz_reason, send_reschedules, send_wait_why,"
                    " send_error from outreach where id = %s", (other_id,))
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, cur.fetchone()))
        plain = pol.schedule_view(row, wcfg)
        check("an approved email with its moment: a time to show, not held",
              (plain["held"], bool(plain["send_label"]), bool(plain["send_after"])) == (False, True, True), plain)
        parked = pol.schedule_view(dict(row, send_error="recipient failed verification"), wcfg)
        check("  parked with a send error (nothing sends it): held, with the reason, and no time at all",
              (parked["held"], parked["held_why"], parked["send_label"], parked["send_short"], parked["send_after"])
              == (True, "recipient failed verification", None, None, None), parked)
        paused_v = pol.schedule_view(row, wcfg, paused="sending is paused for this project")
        check("  sending paused for the project: held, saying so",
              (paused_v["held"], paused_v["held_why"], paused_v["send_label"])
              == (True, "sending is paused for this project", None), paused_v)
        check("  a project without a window keeps its old words (no view)",
              pol.schedule_view(dict(row, send_error="x"), None) is None)
        summary = pol.window_summary({"a": plain, "b": parked})
        check("  a batch's days count only the emails that go", sum(d["count"] for d in summary) == 1, summary)

        # a follow-up keeps its first email's zone only when that was its recipient's, under today's config
        fu_row = {"sequence_step": 1, "ptz": "Europe/London", "preason": "recipient: England, United Kingdom",
                  "pplan": sw.plan_key(wcfg), "metadata": {"hq_country": "US"}}
        check("a follow-up goes at its first email's clock",
              pol._zone_for(fu_row, wcfg) == ("Europe/London", "same as the first email: recipient: England, United Kingdom"),
              pol._zone_for(fu_row, wcfg))
        own = sw.recipient_zone({"hq_country": "US"}, wcfg)
        check("  not when that clock was the sender's (a project switched from \"sender\" to \"recipient\")",
              pol._zone_for(dict(fu_row, ptz="Asia/Kolkata", preason="sender's clock (India)"), wcfg) == own,
              pol._zone_for(dict(fu_row, ptz="Asia/Kolkata", preason="sender's clock (India)"), wcfg))
        check("  nor when it was placed under another window config (its send_plan)",
              pol._zone_for(dict(fu_row, pplan="0123456789ab"), wcfg) == own
              and pol._zone_for(dict(fu_row, pplan=None), wcfg) == own)
        cur.execute("update segments set config = config #- '{outreach,send_window}' where slug = %s", (SEG,))
        cur.execute("select count(*) from outreach o join entities e on e.id = o.entity_id where e.segment_id = %s"
                    " and o.status = 'approved' and o.send_after is not null", (seg_id,))
        before = cur.fetchone()[0]
        pol.settle_schedule(cur, SEG, pol.outreach_config(cur, SEG))
        cur.execute("select count(*) from outreach where approval_batch = %s and send_after is null", (batch_id,))
        check("the window switched off: the stored times are cleared, so they send as before",
              (before >= 4, cur.fetchone()[0]) == (True, 4))
        cur.execute("select count(*), count(*) filter (where spot_checked), min(approved_by), min(approval_mode)"
                    " from outreach where approval_batch=%s", (batch_id,))
        cnt, spot, by, mode = cur.fetchone()
        check("audit: batch, approver, three spot-checked", cnt == 4 and spot == 3 and by == "tester@x" and mode == "batch",
              (cnt, spot, by, mode))
        cur.execute("select requested, approved, cardinality(sample_ids), jsonb_array_length(skipped)"
                    " from outreach_approval_batches where id=%s", (batch_id,))
        check("batch record: 5 requested, 4 approved, 3 sampled, 1 skipped", cur.fetchone() == (5, 4, 3, 1))
        check("a big batch needs a bigger sample", pol.required_sample(80, policy) == 8)

        # ------------------------------------------------------------ templates
        import draft_render
        fu_tpl = {t["key"]: t for t in cfg["templates"]}
        # through the real context builder, so a template that grows a new
        # field is caught here rather than at send time
        ctx = draft_render.build_context(cfg, "Acme", {"host": {"first_name": "Pat", "confidence": "high"}},
                                         seed="test", opener_subject="Opener subject")
        for st in steps:
            t = fu_tpl[st["template"]]
            try:
                draft_render.render(t["subject"], ctx); draft_render.render(t["body"], ctx)
                check("template %s renders with no leftover placeholder" % t["key"], True)
            except ValueError as e:
                check("template %s renders with no leftover placeholder" % t["key"], False, e)
        check("a follow-up template is never picked as an opener",
              draft_render.pick_template(cfg, {"kind": "creator_show"})["key"] == "clipping_intro_v1")
        check("studio opener still picked for production houses",
              draft_render.pick_template(cfg, {"kind": "production_house"})["key"] == "clipping_studio_v1")
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
