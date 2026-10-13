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
        self.calls, self.fail = [], set()

    def run_blocking(self, key, wait_slot=0, env=None):
        self.calls.append((key, (env or {}).get("SEGMENT_SLUG")))
        return (1 if key in self.fail else 0), None

    def run_send(self, segment, env=None, stay=0, max_seconds=None, on_start=None, wait=0, busy=None):
        """The send's own lane (app/ops.py): recorded under the job's key, as the slot's jobs are. self.log, when
        set, is what the run 'printed' (its SEND-SUMMARY line is what the loop reads). fail "busy": a send for the
        project is already running; "workers": no send worker came free within `wait`."""
        self.calls.append(("send_outreach", segment))
        self.stays = getattr(self, "stays", []) + [stay]
        self.waits = getattr(self, "waits", []) + [wait]
        self.max_seconds = max_seconds
        for why, flag in (("project", "busy"), ("workers", "workers")):
            if flag in self.fail:
                if busy is not None:
                    busy["why"] = why
                return None, None
        if on_start:
            on_start()
        return (1 if "send_outreach" in self.fail else 0), ("fake.log" if getattr(self, "log", None) else None)

    def send_busy(self, segment):
        return "busy" in self.fail

    def send_workers_free(self):
        return getattr(self, "free", 2)

    def io_open(self, path, mode):
        if path == "fake.log" and getattr(self, "log", None):
            import io
            return io.StringIO(self.log)
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
            # a drafting step that fails must not hold back the approved email behind it (2026-09-21)
            lead(seg_id, "shortlisted")                         # needs a draft
            s._ops.calls.clear()
            s._ops.fail = {"draft_outreach"}
            check("drafting fails: the run says failed, and the approved email is still sent",
                  (s.outreach_tick(slug, "manual"), s._ops.calls),
                  ("failed", [("draft_outreach", slug), ("send_outreach", slug)]))
            s._ops.fail = set()

            # the note that explains SET_ME is not a sender field: it must never block a send (2026-09-21: it
            # did, and the first approved email sat in Approved with the footer filled in)
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sender,guidance}',"
                        " '\"postal_address MUST be set before the first send (approval refuses SET_ME)\"')"
                        " where id = %s", (seg_id,))
            check("a note that mentions SET_ME does not stop a real sender from sending",
                  s.outreach_work(slug)["send"], True)
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

            # replies are fetched by themselves, hourly, while there are recent sent threads (2026-09-21)
            check("no sent thread yet: no reply fetch", s.outreach_work(slug)["pull"], False)
            e5, c5 = lead(seg_id, "contacted")
            m5 = mail(e5, c5, "sent", sent_today=True)
            cur.execute("update outreach set gmail_thread_id = 'zz-thread' where id = %s", (m5,))
            check("a sent thread: replies are due to be fetched", s.outreach_work(slug)["pull"], True)
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sending_paused}', 'true')"
                        " where id = %s", (seg_id,))
            check("  a sending pause does not stop reading replies", s.outreach_work(slug)["pull"], True)
            cur.execute("update segments set config = config #- '{outreach,sending_paused}' where id = %s", (seg_id,))
            cur.execute("insert into pipeline_runs (pipeline, step, trigger, status, segment, finished_at)"
                        " values ('outreach', 'pull_replies', 'schedule', 'ok', %s, now())", (slug,))
            check("  fetched in the last hour: not again yet", s.outreach_work(slug)["pull"], False)
            cur.execute("update pipeline_runs set started_at = now() - interval '61 minutes' where segment = %s"
                        " and step = 'pull_replies'", (slug,))
            check("  an hour later: due again", s.outreach_work(slug)["pull"], True)
            s._ops.calls.clear()
            s.outreach_tick(slug, "manual")
            check("  and the tick fetches replies first", s._ops.calls[:1], [("pull_replies", slug)])
            cur.execute("update outreach set gmail_thread_id = null where id = %s", (m5,))

            # from the approver's own Gmail (owner, 2026-09-26): there is something to send only when an
            # approval's approver has a working Gmail connected with room left today
            aslug, aseg = segment({"outreach": dict(outreach, send_from="approver")})
            who = "zz-flow-%s@example.com" % uuid.uuid4().hex[:6]
            cur.execute("insert into app_users (email, password_hash, role) values (%s, 'x', 'member')", (who,))
            ae, ac = lead(aseg, "shortlisted")
            am = mail(ae, ac, "approved")
            cur.execute("update outreach set approved_by = %s where id = %s", (who, am))
            check("approver mode: approved, but its approver has no Gmail: nothing to send",
                  s.outreach_work(aslug)["send"], False)
            addr = "zz-flow-%s@zz-mail.example" % uuid.uuid4().hex[:6]
            cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap) values (%s, %s, 'x', 1)"
                        " returning id", (who, addr))
            mbid = cur.fetchone()["id"]
            check("  their Gmail connected: it is sent", s.outreach_work(aslug)["send"], True)
            cur.execute("update user_mailboxes set last_error = 'sign-in: revoked' where id = %s", (mbid,))
            check("  its sign-in refused: nothing to send until they reconnect", s.outreach_work(aslug)["send"], False)
            cur.execute("update user_mailboxes set last_error = null where id = %s", (mbid,))
            e9, c9 = lead(aseg, "contacted")
            m9 = mail(e9, c9, "sent", sent_today=True)
            cur.execute("update outreach set sender_address = %s where id = %s", (addr, m9))
            check("  that address at its limit for today (1): nothing to send", s.outreach_work(aslug)["send"], False)
            cur.execute("update user_mailboxes set daily_cap = 2 where id = %s", (mbid,))
            check("  room again: it is sent", s.outreach_work(aslug)["send"], True)

            # a project whose emails a person writes (outreach.compose, Universal since 2026-09-27): no
            # templates, so nothing is ever drafted -- but what they approved goes out like any approval
            cslug, cseg = segment({"outreach": {"compose": True, "send_from": "approver",
                                                "sender": {"name": "TVF", "title": "BD",
                                                           "postal_address": "1 Example Road, Mumbai 400001"}}})
            ce, cc = lead(cseg, "shortlisted")
            w = s.outreach_work(cslug)
            check("compose project: something to look at, nothing to draft", (w is not None, w and w["draft"]), (True, False))
            cm = mail(ce, cc, "approved")
            cur.execute("update outreach set approved_by = %s, approval_mode = 'compose' where id = %s", (who, cm))
            check("  a written email approved by someone with a Gmail: it is sent", s.outreach_work(cslug)["send"], True)
            s._ops.calls.clear()
            s.outreach_tick(cslug, "manual")
            check("  the tick sends and never drafts", [k for k, _ in s._ops.calls], ["send_outreach"])

            # the sending window (owner, 2026-10-12: each approved email at its own random second, 10:00-10:30
            # on its recipient's clock): an email is there to send only inside its own window
            import send_window as sw
            block = {"enabled": True, "start": "10:00", "end": "10:30", "timezone_of": "recipient",
                     "fallback_timezone": "America/New_York", "guidance": "test"}
            plan = sw.plan_key(sw.window_cfg({"send_window": block}))
            wslug, wseg = segment({"outreach": dict(outreach, send_window=block)})
            we_, wc_ = lead(wseg, "shortlisted")
            wm = mail(we_, wc_, "approved")
            cur.execute("update outreach set send_after = now() + interval '1 hour', send_before = now() + interval '90 minutes',"
                        " send_tz = 'America/New_York', send_tz_reason = 'test', send_plan = %s where id = %s"
                        " returning send_after, send_before", (plan, wm))
            sa, sb = (lambda r: (r["send_after"], r["send_before"]))(cur.fetchone())
            import datetime as _dt
            check("an approved email whose moment has not come: nothing to send yet",
                  (s.outreach_work(wslug, now=sa - _dt.timedelta(minutes=5))["approved"],
                   s.outreach_work(wslug, now=sa - _dt.timedelta(minutes=5))["send"]), (False, False))
            check("  at its moment, inside its window: it is sent",
                  (s.outreach_work(wslug, now=sa + _dt.timedelta(seconds=30))["send"]), True)
            check("  once its window has closed: not sent late (the send run moves it to the next window)",
                  s.outreach_work(wslug, now=sb + _dt.timedelta(minutes=1))["approved"], False)
            cur.execute("update outreach set send_after = null, send_before = null where id = %s", (wm,))
            check("  one with no time yet in a timed project: the send run is started, and places it first",
                  s.outreach_work(wslug, now=sa)["approved"], True)
            # due now, on the database's clock: the tick's send goes through the send's own lane
            cur.execute("update outreach set send_after = clock_timestamp() - interval '1 minute',"
                        " send_before = clock_timestamp() + interval '20 minutes', send_plan = %s where id = %s", (plan, wm))
            s._ops.calls.clear()
            s._ops.fail = {"busy"}

            def send_step_detail(slug_):
                cur.execute("select detail from pipeline_runs where segment = %s and step = 'send_outreach'"
                            " and status = 'skipped' order by detail", (slug_,))
                return [r_["detail"] for r_ in cur.fetchall()]
            check("a send for the project already running: the tick's send step is skipped, not queued",
                  (s.outreach_tick(wslug, "manual"), s._ops.calls, runs(wslug)[-1]),
                  ("skipped", [("send_outreach", wslug)], ("send_outreach", "manual", "skipped")))
            # second review, 2026-10-12: the tick's send waits a few minutes for a free send worker, as the slot's jobs
            # wait for the slot -- a project with no window is sent only by the tick -- and says which was busy
            check("  the tick's send waits for a free send worker (longer than a timed run may hold one)",
                  (s._ops.waits[-1], sched.TICK_SEND_WAIT > sched.SEND_LOOP_MAX_RUN), (sched.TICK_SEND_WAIT, True))
            s._ops.fail = {"workers"}
            s.outreach_tick(wslug, "manual")
            check("  every worker busy all that time: skipped, saying so (not 'already running')",
                  send_step_detail(wslug),
                  ["skipped: a send for this project is already running",
                   "skipped: every send worker stayed busy for %d minutes; the next tick tries again"
                   % (sched.TICK_SEND_WAIT // 60)])
            s._ops.fail = set()
            started = []
            real_run = s._send_run

            def fake_run(slug_, due_ids=None):          # the run itself is checked below; here only who starts
                started.append(slug_)
                with s._kick_lock:
                    s._sending.discard(slug_)
            s._send_run = fake_run
            s.segments = lambda: [wslug, slug]
            nxt = s._send_pass()
            time.sleep(0.3)
            check("the send loop: a project with an email due gets its own send at once (not the next tick)",
                  started, [wslug])
            check("  a project without a window is left to the tick", slug in started, False)
            cur.execute("update outreach set send_after = clock_timestamp() + interval '40 seconds',"
                        " send_before = clock_timestamp() + interval '25 minutes' where id = %s", (wm,))
            started.clear()
            nxt = s._send_pass()
            time.sleep(0.3)
            check("  nothing due yet: no send, and the loop knows when to look again (40 s)",
                  (started, nxt is not None and 30 <= nxt <= 41), ([], True))
            cur.execute("update outreach set send_after = clock_timestamp() - interval '1 minute' where id = %s", (wm,))
            s._cooldown[wslug] = (time.time() + 60, 120)
            started.clear()
            s._send_pass()
            time.sleep(0.3)
            check("  after a failed send the project waits out its cool-down", started, [])
            s._cooldown.clear()
            cur.execute("update segments set config = jsonb_set(config, '{outreach,sending_paused}', 'true') where id = %s",
                        (wseg,))
            started.clear()
            s._send_pass()
            time.sleep(0.3)
            check("  a paused project is not sent", started, [])
            cur.execute("update segments set config = config #- '{outreach,sending_paused}' where id = %s", (wseg,))

            def one_pass():
                started.clear()
                s._send_pass()
                time.sleep(0.3)
                return list(started)
            # review, 2026-10-12: never a second run for a project, and none for due emails the last run could
            # do nothing with (another machine's sign-in) -- they stay due all window, and the loop must not spin
            with s._kick_lock:
                s._sending.add(wslug)
            check("  a project whose send is still going gets no second one", one_pass(), [])
            with s._kick_lock:
                s._sending.discard(wslug)
            s._left[wslug] = {str(wm): time.time() + 60}
            check("  due emails the last run could do nothing with start no new run (it cannot spin)", one_pass(), [])
            s._left[wslug] = {str(wm): time.time() - 1}
            check("  after IDLE_RETRY it tries them again", one_pass(), [wslug])
            # one send worker free and two projects due: one starts, and the next free worker goes to the other
            w2slug, w2seg = segment({"outreach": dict(outreach, send_window=block)})
            e2_, c2_ = lead(w2seg, "shortlisted")
            wm2 = mail(e2_, c2_, "approved")
            cur.execute("update outreach set send_after = clock_timestamp() - interval '1 minute', send_before ="
                        " clock_timestamp() + interval '20 minutes', send_tz = 'America/New_York', send_tz_reason = 'test',"
                        " send_plan = %s where id = %s", (plan, wm2))
            s.segments = lambda: [wslug, w2slug, slug]
            s._ops.free = 1
            s._wanted.clear()
            first = one_pass()
            waited = [x for x in (wslug, w2slug) if x not in first]
            check("  one send worker free, two projects due: one starts, the other waits its turn",
                  (len(first), len(waited), bool(waited) and waited[0] in s._wanted), (1, 1, True))
            check("  and the next free worker goes to the one that waited", one_pass(), waited)
            s._ops.free = 2
            s._wanted.clear()
            # one project's look failing (a database error, a lead the resolver chokes on) stops no other
            alerts = []
            s.alert = lambda text: alerts.append(text)
            real_look = s._look
            s._look = lambda slug_, r_, pol_, sw_: (_ for _ in ()).throw(RuntimeError("boom")) if slug_ == wslug \
                else real_look(slug_, r_, pol_, sw_)
            check("  one project's look failing: the others still start, and the owner is told",
                  (one_pass(), len([a for a in alerts if "could not look" in a])), ([w2slug], 1))
            one_pass()
            check("  told once, not every pass", len([a for a in alerts if "could not look" in a]), 1)
            del s._look
            cur.execute("update outreach set status = 'cancelled' where id = %s", (wm2,))
            s.segments = lambda: [wslug, slug]

            s._send_run = real_run
            del s.segments
            s._ops.calls.clear()

            def by_pipeline(slug_):
                # every row of this transaction has one started_at (now()), so they are counted, not ordered
                cur.execute("select pipeline, count(*) filter (where step is null) as whole,"
                            " count(*) filter (where step = 'send_outreach') as step_"
                            " from pipeline_runs where segment = %s group by 1 order by 1", (slug_,))
                return {r_["pipeline"]: (r_["whole"], r_["step_"]) for r_ in cur.fetchall()}
            before_runs = by_pipeline(wslug)
            s._send_run(wslug)
            after_runs = by_pipeline(wslug)
            check("  a timed send runs in the send lane, stays on for the next moment (55 s) for at most 5 minutes",
                  (s._ops.calls, s._ops.stays[-1], s._ops.max_seconds), ([("send_outreach", wslug)], 55, 300))
            # second review, 2026-10-12: under the tick's "outreach" a timed run (about one a minute in a window) took
            # over the Drafting and sending line and hid a tick whose drafting had failed; it is its own pipeline now
            check("  recorded as its own pipeline, 'send': a whole-run row and its step, the tick's rows untouched",
                  (after_runs.get("send"), after_runs.get("outreach") == before_runs.get("outreach")), ((1, 1), True))
            # Gmail refusing an address is handled by the run (it moved that address's emails): no back-off for the
            # project, the owner told once a day per address, and emails moved three times told (review, 2026-10-12)
            s._ops.log = "...\nSEND-SUMMARY " + json.dumps({
                "sent": 0, "deferred": 2, "parked": 0, "cancelled": 0, "left_alone": ["zz-left-1"],
                "refused": {"zz-a@zz.example": "Gmail refused zz-a@zz.example (429)"}, "alert_ids": ["zz-moved-1"]})
            alerts.clear()
            s._cooldown.clear()
            s._send_run(wslug)
            s._send_run(wslug)
            check("  a run that handled a Gmail refusal: no back-off, the address told once, the 3rd move told once",
                  (wslug in s._cooldown, len([a for a in alerts if "Gmail refused zz-a@zz.example (429)" in a]),
                   len([a for a in alerts if "missed 3 sending windows" in a]), "zz-left-1" in s._left.get(wslug, {})),
                  (False, 1, 1, True))
            # second review, 2026-10-12: such a run ends OK, so the refusal is written on its rows -- Operations shows
            # the day's latest (/api/schedule refused) -- or a lasting one showed green day after day
            cur.execute("select step, status, detail from pipeline_runs where segment = %s and pipeline = 'send'"
                        " and detail like 'Gmail refused zz-a@%%' order by step nulls first", (wslug,))
            noted = [(r_["step"], r_["status"]) for r_ in cur.fetchall()]
            check("  and the refusal is written on its run rows (both OK), for Operations to show",
                  noted, [(None, "ok"), (None, "ok"), ("send_outreach", "ok"), ("send_outreach", "ok")])
            # the same from the fifteen-minute tick's send: on its step, and on its whole run's detail
            s._ops.calls.clear()
            check("  the tick's send that handled one: OK, and the refusal written on its step and its run",
                  (s.outreach_tick(wslug, "manual"), s._ops.calls), ("ok", [("send_outreach", wslug)]))
            cur.execute("select step, status from pipeline_runs where segment = %s and pipeline = 'outreach'"
                        " and status = 'ok' and detail like 'Gmail refused zz-a@%%' order by step nulls first", (wslug,))
            check("    (its rows)", [(r_["step"], r_["status"]) for r_ in cur.fetchall()], [(None, "ok"), ("send_outreach", "ok")])
            # a run that sent, moved, parked and cancelled nothing: every email due when it started rests IDLE_RETRY,
            # even one no path of the run named in left_alone -- and the loop is woken only once that is remembered,
            # or its next pass starts a new run for those very emails (second review, 2026-10-12)
            s._ops.log = "...\nSEND-SUMMARY " + json.dumps({
                "sent": 0, "deferred": 0, "parked": 0, "cancelled": 0, "left_alone": [], "refused": {}, "alert_ids": []})
            s._left.pop(wslug, None)
            real_wake = s._send_wake

            class WakeSpy:
                seen = []

                def set(self):
                    self.seen.append(sorted((s._left.get(wslug) or {}).keys()))
            s._send_wake = WakeSpy()
            try:
                s._send_run(wslug, due_ids=["zz-due-1", "zz-due-2"])
            finally:
                s._send_wake = real_wake
            check("  a run that did nothing at all: the emails due at its start rest, remembered before the loop wakes",
                  WakeSpy.seen, [["zz-due-1", "zz-due-2"]])
            s._left.pop(wslug, None)
            s._after_send(wslug, {"sent": 1, "left_alone": []}, due_ids=["zz-due-3"])
            check("  one that sent something: the rest are not held back", sorted(s._left.get(wslug) or {}), [])
            s._ops.log = None
            s._ops.fail = {"send_outreach"}
            s._send_run(wslug)
            s._ops.fail = set()
            cur.execute("select step, status, detail from pipeline_runs where segment = %s and trigger = 'schedule'"
                        " and pipeline = 'send' and status = 'failed' order by step nulls first", (wslug,))
            failed_rows = [(r_["step"], r_["status"], r_["detail"] if r_["step"] is None else None) for r_ in cur.fetchall()]
            check("  a run that crashed backs the project off (2 minutes), and Operations shows where it failed",
                  ((s._cooldown.get(wslug) or (0, 0))[1], failed_rows),
                  (120, [(None, "failed", "failed at step 'send_outreach'"), ("send_outreach", "failed", None)]))
            s._cooldown.clear()
            del s.alert
            cur.execute("update outreach set status = 'cancelled' where id = %s", (wm,))

            # the real send lane (app/ops.py run_send), its subprocess stood in for: with every send worker held, a
            # send that may wait takes the first one that comes free; one that may not gives up at once, saying
            # which was busy -- the workers, or a send of the project's own (second review, 2026-10-12)
            import ops as real_ops
            ran = []
            real_exec = real_ops._execute
            real_ops._execute = lambda key, job, logpath, env_extra=None, track=True, extra_args=None: (
                ran.append((key, (env_extra or {}).get("SEGMENT_SLUG"), track, list(extra_args or []))), 0)[1]
            lane = "zz-lane-" + uuid.uuid4().hex[:6]
            held = 0
            try:
                for _ in range(real_ops._SEND_WORKERS):
                    held += 1 if real_ops._SEND_SEM.acquire(blocking=False) else 0
                busy = {}
                got = real_ops.run_send(lane, {}, wait=0, busy=busy)
                check("the send lane: every worker busy and no wait -- nothing runs, and it says the workers were busy",
                      (got, busy, ran), ((None, None), {"why": "workers"}, []))
                threading.Timer(0.4, real_ops._SEND_SEM.release).start()
                held -= 1
                t0, busy = time.monotonic(), {}
                rc_, path_ = real_ops.run_send(lane, {}, wait=5, busy=busy)
                check("  allowed to wait: it takes the worker that comes free, and runs (beside the slot)",
                      (rc_, bool(path_), busy, ran, 0.3 < time.monotonic() - t0 < 4),
                      (0, True, {}, [("send_outreach", lane, False, ["--stay", "0"])], True))
                lock = real_ops._send_lock(lane)
                lock.acquire()
                try:
                    t0, busy = time.monotonic(), {}
                    got = real_ops.run_send(lane, {}, wait=5, busy=busy)
                finally:
                    lock.release()
                check("  a send of the project's own already running: it never waits, and says that",
                      (got, busy, time.monotonic() - t0 < 1), ((None, None), {"why": "project"}, True))
            finally:
                real_ops._execute = real_exec
                for _ in range(held):
                    real_ops._SEND_SEM.release()
            free_now = [real_ops._SEND_SEM.acquire(blocking=False) for _ in range(real_ops._SEND_WORKERS)]
            for got_one in free_now:
                if got_one:
                    real_ops._SEND_SEM.release()
            check("  every worker free again afterwards", (free_now.count(True), real_ops.send_workers_free()),
                  (real_ops._SEND_WORKERS, real_ops._SEND_WORKERS))

            # the send loop runs wherever the scheduler runs, unless SEND_LOOP_ENABLED=0 (review, 2026-10-12)
            wanted = sched.Scheduler.send_loop_wanted
            check("the send loop runs wherever the scheduler does: no SEND_LOOP_ENABLED needed",
                  (wanted({})[0], wanted({"SCHEDULER_ENABLED": "1"})[0], wanted({"SEND_LOOP_ENABLED": "1"})[0]),
                  (True, True, True))
            check("  off only when SEND_LOOP_ENABLED=0 says so, or where the scheduler is off, saying why",
                  (wanted({"SEND_LOOP_ENABLED": "0"})[0], "SEND_LOOP_ENABLED=0" in wanted({"SEND_LOOP_ENABLED": "0"})[1],
                   wanted({"SCHEDULER_ENABLED": "0"})[0]), (False, True, False))
            check("  a loop never started says so on Operations", s.send_loop_state()["on"], False)

            # after a restart (every deploy) each segment gets one round at once, not at the next quarter hour
            kicked = []
            real_kick, real_segments = s.kick_outreach, s.segments
            s.kick_outreach = lambda seg, trigger="manual": kicked.append((seg, trigger))
            s.segments = lambda: [slug, quiet]
            check("a restart sends what was approved while it was down: one round per segment, at once",
                  (s.catch_up(), [seg for seg, _ in kicked]), ([slug, quiet], [slug, quiet]))
            s.kick_outreach, s.segments = real_kick, real_segments
            # every trigger the flow records must be one pipeline_runs accepts: a refused one ("startup",
            # 2026-09-21) let the round run but left no line in the run history
            for trigger in sorted({t for _, t in kicked} | {"schedule", "manual"}):
                cur.execute("savepoint trig")
                check("the run history accepts the trigger %r" % trigger,
                      s._open("outreach", None, trigger, slug) is not None, True)
                cur.execute("rollback to savepoint trig")

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
