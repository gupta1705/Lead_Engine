#!/usr/bin/env python3
"""test_autoflow.py -- the simple flow (owner, 2026-09-19): shortlisted leads get their email drafted,
approved emails are sent, both without a person pressing anything else.

    python tools/test_autoflow.py

Runs app/scheduler.py's outreach_work / outreach_tick / kick_outreach against the real database
inside one transaction that is rolled back: a throwaway segment, companies, contacts and outreach
rows, then ROLLBACK. The jobs themselves (tools/outreach.py draft / send) are not run -- a stand-in
records which ones the flow asked for; what they do is covered by their own tests and was unchanged.
Exit code 1 on any failure.
"""
import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from run_sql import load_db_url  # noqa: E402
import scheduler as sched  # noqa: E402

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-64s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:100]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:100])))


class FakeOps:
    """Stands in for app/ops.py: records the jobs the flow runs, succeeds."""

    def __init__(self):
        self.calls = []

    def run_blocking(self, key, wait_slot=0, env=None):
        self.calls.append((key, (env or {}).get("SEGMENT_SLUG")))
        return 0, None

    def io_open(self, path, mode):
        raise OSError("no log in the test")


def main():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False

    @contextmanager
    def cursor():
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur

    saved_env = {k: os.environ.get(k) for k in ("GMAIL_SENDER_ADDRESS", "GMAIL_TOKEN_JSON")}
    for k in saved_env:
        os.environ.pop(k, None)
    s = sched.Scheduler(cursor, FakeOps(), "us-production-houses")
    # "connected" is decided by this test alone, not by the machine it runs on: since 2026-09-21 the
    # laptop has a real Gmail token (.gmail_token.json) and address in .env, which the scheduler would
    # otherwise find and count as a connected mailbox
    s.mailbox_connected = lambda mb: bool(os.environ.get(mb["email_env"])) and bool(os.environ.get(mb["token_env"]))
    try:
        with cursor() as cur:
            def segment(config):
                slug = "zz-test-flow-" + uuid.uuid4().hex[:6]
                cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'test', 'company', %s)"
                            " returning id", (slug, json.dumps(config)))
                return slug, cur.fetchone()["id"]

            def lead(seg_id, status, email="kay.%s@example.com"):
                cur.execute("insert into entities (segment_id, name, domain, source, status) values"
                            " (%s, %s, %s, 'test', %s) returning id",
                            (seg_id, "ZZ flow " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example", status))
                eid = cur.fetchone()["id"]
                cid = None
                if email:
                    cur.execute("insert into contacts (entity_id, full_name, email, email_status) values"
                                " (%s, 'Kay Doe', %s, 'valid') returning id", (eid, email % uuid.uuid4().hex[:6]))
                    cid = cur.fetchone()["id"]
                return eid, cid

            def mail(eid, cid, status, sent_today=False):
                cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, sent_at)"
                            " values (%s, %s, 't', 'Hello', 'Body', %s, case when %s then now() end) returning id",
                            (eid, cid, status, sent_today))
                return cur.fetchone()["id"]

            def runs(slug):
                cur.execute("select step, trigger, status from pipeline_runs where segment = %s order by started_at, step"
                            " nulls first", (slug,))
                return [(r["step"], r["trigger"], r["status"]) for r in cur.fetchall()]

            outreach = {"templates": [{"key": "t", "subject": "Hello", "body": "Body"}], "daily_send_cap": 2,
                        "sender": {"name": "Kay", "postal_address": "1 Example Road, Mumbai 400001"}}

            # a project that writes no email (Universal) is never touched
            quiet, _ = segment({"rubric": []})
            check("a project with no email templates: nothing to do", (s.outreach_work(quiet), s.outreach_tick(quiet)),
                  (None, "idle"))

            slug, seg_id = segment({"outreach": outreach})
            check("nothing shortlisted, nothing approved: idle, nothing recorded",
                  (s.outreach_tick(slug), runs(slug), s._ops.calls), ("idle", [], []))

            eid, cid = lead(seg_id, "shortlisted")
            lead(seg_id, "shortlisted", email=None)               # no address: nothing to draft for it
            w = s.outreach_work(slug)
            check("a shortlisted lead with an address needs its draft", (w["draft"], w["send"]), (True, False))
            check("the tick drafts it, recorded as a run", (s.outreach_tick(slug, "manual"), s._ops.calls, runs(slug)),
                  ("ok", [("draft_outreach", slug)],
                   [(None, "manual", "ok"), ("draft_outreach", "manual", "ok")]))

            mail(eid, cid, "drafted")
            check("once drafted, nothing more to do until it is approved", s.outreach_work(slug)["draft"], False)
            cur.execute("update outreach set status = 'approved' where entity_id = %s", (eid,))
            w = s.outreach_work(slug)
            check("approved, but no mailbox connected: nothing is sent", (w["approved"], w["connected"], w["send"]),
                  (True, [], False))

            os.environ["GMAIL_SENDER_ADDRESS"] = "kay@example.com"
            os.environ["GMAIL_TOKEN_JSON"] = "{\"token\": \"test\"}"
            w = s.outreach_work(slug)
            check("a connected mailbox: the approved email is sent", (w["connected"], w["send"]), (["default"], True))
            s._ops.calls.clear()
            check("the tick sends it", (s.outreach_tick(slug, "manual"), s._ops.calls), ("ok", [("send_outreach", slug)]))

            cur.execute("update segments set config = jsonb_set(config, '{outreach,sender,name}', '\"SET_ME\"')"
                        " where id = %s", (seg_id,))
            check("a sender still saying SET_ME: nothing is sent", s.outreach_work(slug)["send"], False)
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sender,name}', '\"Kay\"')"
                        " where id = %s", (seg_id,))

            # the owner's pause (2026-09-21): only US Production Houses sends for now
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sending_paused}', 'true')"
                        " where id = %s", (seg_id,))
            w = s.outreach_work(slug)
            check("sending paused for the project: the approved email waits, drafting carries on",
                  (w["paused"], w["send"], w["connected"]), (True, False, ["default"]))
            cur.execute("update segments set config = config #- '{outreach,sending_paused}' where id = %s", (seg_id,))
            check("the pause lifted: it is sent again", s.outreach_work(slug)["send"], True)

            for _ in range(2):                                  # the day's cap of 2 already used
                e2, c2 = lead(seg_id, "contacted")
                mail(e2, c2, "sent", sent_today=True)
            check("the day's cap is used up: it waits for tomorrow's tick", s.outreach_work(slug)["send"], False)
            # the owner's rule (2026-09-21): past the day's limit, the rest go out from the next day on.
            # Tomorrow is simulated by moving today's sends to yesterday: the waiting email is sent again.
            cur.execute("update outreach set sent_at = sent_at - interval '1 day' where status = 'sent' and entity_id in"
                        " (select id from entities where segment_id = %s)", (seg_id,))
            check("the next day the count starts again and the waiting email goes out",
                  s.outreach_work(slug)["send"], True)
            cur.execute("update outreach set sent_at = sent_at + interval '1 day' where status = 'sent' and entity_id in"
                        " (select id from entities where segment_id = %s)", (seg_id,))

            # ten shortlists in a row are one or two runs, not ten
            count = {"n": 0}

            def slow_tick(segment, trigger="schedule"):
                count["n"] += 1
                time.sleep(0.3)
                return "ok"
            s.outreach_tick = slow_tick
            started = [s.kick_outreach(slug, "manual") for _ in range(10)]
            for _ in range(40):
                time.sleep(0.1)
                with s._kick_lock:
                    if slug not in s._kicking:
                        break
            check("ten kicks in a row: one run started, one more round, then done",
                  (started.count(True), count["n"], slug in s._kicking), (1, 2, False))

            # taking a lead off the shortlist takes its waiting email with it (2026-09-19): the
            # Cancel draft button went, and nothing may go out to a company a person just refused
            import main as app_main
            app_main.cursor = cursor
            e3, c3 = lead(seg_id, "shortlisted")
            m3 = mail(e3, c3, "drafted")
            out = app_main.decide(str(e3), {"decision": "reject", "reason": "not a fit"})
            cur.execute("select status from outreach where id = %s", (m3,))
            check("rejecting a shortlisted lead withdraws its waiting draft",
                  (out["status"], out["withdrawn"], cur.fetchone()["status"]), ("rejected", 1, "cancelled"))
            e4, c4 = lead(seg_id, "shortlisted")
            m4 = mail(e4, c4, "approved")
            out = app_main.decide(str(e4), {"decision": "reset"})
            cur.execute("select status from outreach where id = %s", (m4,))
            check("moving an approved lead back to review withdraws its email too",
                  (out["status"], out["withdrawn"], cur.fetchone()["status"]), ("ready_for_review", 1, "cancelled"))

            # one weekly refresh at a time: six clicks in six seconds once queued six (2026-09-17)
            ran = {"n": 0}

            def slow_steps(pipeline, steps, trigger, segment):
                ran["n"] += 1
                time.sleep(0.4)
            s._run_steps = slow_steps
            s.pipelines = lambda segment=None: {"weekly_refresh": ["promote_chain"]}
            threads = [threading.Thread(target=s.run_pipeline, args=("weekly_refresh", "manual", slug)) for _ in range(6)]
            for t in threads:
                t.start()
            time.sleep(0.1)
            busy = s.is_running(slug, "weekly_refresh")
            for t in threads:
                t.join()
            check("six starts at once: one weekly refresh runs, the rest are refused",
                  (ran["n"], busy, s.is_running(slug, "weekly_refresh")), (1, True, False))
    finally:
        conn.rollback()
        conn.close()
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
