#!/usr/bin/env python3
"""scheduler.py -- P25 unattended pipeline, driven from the app container.

WHY IT LIVES HERE AND NOT IN N8N. n8n schedules the HARVESTS -- that is its
core competency and it survives a reboot through the container's restart
policy. But the promote/score/gate chain and the enrichment passes are the
tested Python and SQL this repo already ships; re-implementing them as n8n
Postgres nodes would create a second copy of logic that has bitten this
project repeatedly (config vs live DB, .js vs workflow JSON). So the app
schedules the Python/SQL half through the EXACT ops-runner used by the manual
buttons -- one code path for scheduled and hand-run alike -- and n8n schedules
the harvests. The two are coordinated by day offset, which is precisely how
BUILD_PLAN designed them (harvest weekly, Run A Tue, Run B Wed).

WHAT MAKES UNATTENDED SAFE:
  * every pipeline and every step writes to pipeline_runs -- a run in the dark
    still leaves a trail a human reads on Monday
  * a step that fails STOPS the pipeline (a half-enriched pool is not scored on
    stale evidence) and fires the alert
  * the alert is a webhook ping (Discord/Slack shape); if no webhook is
    configured it degrades to a logged warning and never crashes the loop
  * the single-slot lock is shared with manual runs, so a scheduled pipeline
    and a human clicking Run can never collide
  * sending needs a connected Gmail mailbox; without one nothing is sent and
    nothing is recorded

THE SIMPLE FLOW (owner, 2026-09-19): "leads are displayed, shortlisted and
after approval sent." Two steps used to wait for a person to remember them:
pressing Draft emails after shortlisting, and running `outreach.py send` in a
terminal after approving. Both now happen by themselves (outreach_tick): a
shortlisted lead with an address gets its draft, a due follow-up gets drafted,
and an approved email goes out -- within the day's cap, from a connected
mailbox, through the same tools with the same checks. Approval is still the
human decision on every email; nothing leaves that a person did not approve.
It runs right after a shortlist or an approval (kick_outreach, off the
request thread) and every fifteen minutes for whatever a trigger missed: a
busy job slot, a cap that reset overnight, a follow-up that fell due. A tick
with no work does nothing and records nothing.

THE SENDING WINDOW (owner, 2026-10-12). A project with outreach.send_window sends each approved email at
its own random second between 10:00 and 10:30 on its recipient's clock. Those sends do not wait for the
fifteen-minute tick or the single job slot: _send_loop looks every few seconds and starts each due send in
its own lane (app/ops.py run_send). A project without the block is sent by the tick, as before. The loop
runs wherever the scheduler does unless SEND_LOOP_ENABLED=0 (send_loop_wanted), and Operations says
whether it is on (/api/schedule send_loop).

Nothing outbound happens without the Gmail credential the owner adds.
"""
import io
import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# work the simple flow looks for before it runs anything
DRAFT_NEEDED_SQL = """
select 1 from entities e
where e.segment_id = (select id from segments where slug = %s)
  and e.status = 'shortlisted'
  and not exists (select 1 from outreach o where o.entity_id = e.id and o.direction = 'outbound'
                    and o.status not in ('cancelled', 'failed'))
  and exists (select 1 from contacts c where c.entity_id = e.id and c.email is not null
                and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500 and contact_allowed(c.entity_id,c.source,c.verifier,c.email_status))
limit 1"""
# An approved email is there to send when it has no time (a project without a sending window; or one the
# send run itself will place first) or its own moment has come and its window is still open (sql/34).
APPROVED_SQL = """
select 1 from outreach o join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %(segment)s)
  and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
  and (o.send_after is null or (o.send_after <= %(now)s and %(now)s < o.send_before))
limit 1"""
# Replies and bounces reach the app only through `outreach.py pull`, which nothing ran: Replies stayed
# empty, a reply never paused a follow-up and a bounce never marked its address (found 2026-09-21).
# Pulled hourly while a segment has recent sent threads (the window cmd_pull reads, 60 days).
PULL_DUE_SQL = """
select exists (select 1 from outreach o join entities e on e.id = o.entity_id
               where e.segment_id = (select id from segments where slug = %(segment)s)
                 and o.direction = 'outbound' and o.status = 'sent' and o.gmail_thread_id is not null
                 and o.sent_at > now() - interval '60 days')
   and not exists (select 1 from pipeline_runs r
                   where r.segment = %(segment)s and r.step = 'pull_replies' and r.status = 'ok'
                     and r.started_at > now() - make_interval(mins => %(every)s)) as due"""
PULL_EVERY_MINUTES = 60
TICK_MINUTES = 15
# A lead's reply, within minutes (owner, 2026-10-28: an alert when a lead replies): every five minutes a quick look
# (`outreach.py pull --recent`: one Gmail search per address, then only the threads with something new), in the
# replies' own lane (app/ops.py run_pull), for each project with threads to read. The hourly full read stays.
REPLY_EVERY_SECONDS = 300
REPLY_THREADS_SQL = """
select 1 from outreach o join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %s)
  and o.direction = 'outbound' and o.status = 'sent' and o.gmail_thread_id is not null
  and o.sent_at > now() - interval '60 days'
limit 1"""
# From the approver (owner, 2026-09-26): an approved email can go when its approver has a Gmail connected
# in the app, working (no sign-in error), with room left today under that address's own limit.
APPROVER_SENDABLE_SQL = """
select 1 from outreach o
join entities e on e.id = o.entity_id
join user_mailboxes m on lower(m.user_email) = lower(o.approved_by) and m.enabled and m.last_error is null
where e.segment_id = (select id from segments where slug = %(segment)s)
  and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
  and (o.send_after is null or (o.send_after <= %(now)s and %(now)s < o.send_before))
  and (select count(*) from outreach x
        where x.direction = 'outbound' and lower(x.sender_address) = lower(m.address)
          and x.status in ('sent', 'sending', 'send_unknown')
          and coalesce(x.sent_at, x.updated_at)::date = current_date) < m.daily_cap
limit 1"""

# The send loop's look at every project: approved emails due now, ones whose window passed unsent, ones with
# no time yet, and how long until the next one's moment -- on the database's clock, the one the claim reads.
DUE_SQL = """
select s.slug,
       count(*) filter (where o.send_after <= clock_timestamp() and clock_timestamp() < o.send_before) as due,
       array_agg(o.id::text) filter (where o.send_after <= clock_timestamp() and clock_timestamp() < o.send_before)
           as due_ids,
       count(*) filter (where o.send_before <= clock_timestamp()) as missed,
       count(*) filter (where o.send_after is null) as unscheduled,
       count(*) filter (where o.send_after is not null) as timed_rows,
       extract(epoch from min(o.send_after) filter (where o.send_after > clock_timestamp()) - clock_timestamp())
           as next_in
from outreach o
join entities e on e.id = o.entity_id
join segments s on s.id = e.segment_id
where o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
group by 1"""
SEND_LOOP_STAY = 55          # a send run waits this long for the next email's moment (tools/outreach.py --stay)
SEND_LOOP_MAX_RUN = 300      # and holds its send worker at most this long (--max-seconds; review, 2026-10-12):
                             # with three projects due at once and two workers, the third waits minutes, not 15
SEND_LOOP_MAX_WAIT = 15      # the loop looks again at least this often
SWEEP_EVERY = 60             # seconds between looks for an email left in 'sending'
COOLDOWN_FIRST, COOLDOWN_MAX = 120, 1800   # after a send run that crashed: 2 minutes, doubling up to 30
IDLE_RETRY = 300             # a due email the last run could do nothing with (another machine's sign-in) starts
                             # no new run for this long: the loop never spins on it all window
TICK_SEND_WAIT = 360         # the tick's send waits this long for a free send worker (second review, 2026-10-12):
                             # longer than SEND_LOOP_MAX_RUN, so a worker held by a timed run comes free first
SUMMARY_TAG = "SEND-SUMMARY "   # the last line of a send run's log (tools/outreach.py SUMMARY_TAG)

# Pipelines: an ordered list of ops-job keys. A pipeline fails at the first
# step that fails; later steps do not run. run_chain appears twice in the
# refresh on purpose -- promote the freshly harvested rows first, then re-run
# it at the end to re-score once enrichment has added evidence, applying gates
# against the final scores.
PIPELINES = {
    "weekly_refresh": [
        "discover_apollo",
        "promote_chain",
        "prepare_apollo",
        "verify_sites",
        "news_sweep",
        "promote_chain",
        "enrich_apollo_project",
        "promote_chain",
    ],
}

# Default schedule (UTC). Conservative: one weekly refresh, Tuesday 02:00 UTC,
# a few hours after a Monday-night harvest would land. Overridable via the
# segment config's optional `schedule` block.
DEFAULT_SCHEDULE = [
    {"name": "weekly refresh", "pipeline": "weekly_refresh",
     "dow": 1, "hour": 2, "minute": 0, "enabled": True},
]


def _now():
    return datetime.now(timezone.utc)


class Scheduler:
    def __init__(self, cursor, ops, segment="us-production-houses", allowed=None):
        self._cursor = cursor          # app DB contextmanager
        self._ops = ops                # the ops module (run_blocking, JOBS)
        self._segment = segment        # the default segment
        self._allowed = allowed        # SEGMENTS_ALLOWED, or None for every active one
        self._thread = None
        self._stop = threading.Event()
        self._fired = {}               # (segment, name) -> last-fired minute-key, dedupe
        self._kick_lock = threading.Lock()
        self._kicking, self._kick_again = set(), set()   # segments with an outreach run going / asked again
        self._last_tick = None         # minute-key of the last fifteen-minute outreach tick
        self._running = set()          # (segment, pipeline) runs in progress: a second start is refused
        self._send_thread = None       # the send loop (_send_loop): timed emails, in their own lane
        self._send_wake = threading.Event()
        self._plans = {}               # segment -> the send_window fingerprint last settled
        self._cooldown = {}            # segment -> (until, seconds): after a send run that crashed
        self._alerted = set()          # what the send loop has already told the owner about
        self._sending = set()          # segments whose send-loop run has been started and not yet ended
        self._left = {}                # segment -> {outreach id: until}: due, but the last run could not send it
        self._wanted = {}              # segment -> since when it has waited for a free send worker
        self._send_loop_on = None      # whether start() started the send loop, and why not (send_loop_state)
        self._send_loop_why = "the scheduler has not started"

    # ---------------------------------------------------------------- config
    def segments(self):
        """Every active segment this deployment serves (SCHEDULER_SEGMENTS
        narrows it further). Each gets its own schedule and pipelines."""
        import os
        env = [s.strip() for s in os.environ.get("SCHEDULER_SEGMENTS", "").split(",") if s.strip()]
        if env:
            return env
        try:
            with self._cursor() as cur:
                cur.execute("select slug from segments where is_active order by slug")
                slugs = [r["slug"] for r in cur.fetchall()]
            if self._allowed:
                slugs = [s for s in slugs if s in self._allowed]
            return slugs or [self._segment]
        except Exception:
            return [self._segment]

    def _config(self, segment, key):
        """The app cursor is a RealDictCursor: rows are dicts, so the column
        is aliased and read by name (the original schedule() indexed [0] and
        silently fell back to the default schedule every time)."""
        try:
            with self._cursor() as cur:
                cur.execute("select config->%s as v from segments where slug=%s", (key, segment))
                row = cur.fetchone()
            return row["v"] if row else None
        except Exception:
            return None

    def schedule(self, segment=None):
        """A segment's own schedule block; the built-in default applies only
        to the deployment's default segment, so a config-only segment with
        no schedule (startup-acquisitions) never runs the TVF pipeline."""
        segment = segment or self._segment
        got = self._config(segment, "schedule")
        if got:
            return got
        return DEFAULT_SCHEDULE if segment == self._segment else []

    def pipelines(self, segment=None):
        got = self._config(segment or self._segment, "pipelines")
        return got if isinstance(got, dict) and got else PIPELINES

    def alert_webhook(self):
        import os
        return os.environ.get("ALERT_WEBHOOK_URL")

    # ---------------------------------------------------------------- alerts
    def alert(self, text):
        url = self.alert_webhook()
        if not url:
            print("[scheduler] ALERT (no webhook configured): " + text, flush=True)
            return
        # Discord expects {"content"}, Slack {"text"}; sending both is harmless
        body = json.dumps({"content": text, "text": text}).encode()
        try:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print("[scheduler] alert webhook failed: %r -- %s" % (e, text), flush=True)

    # ------------------------------------------------------------ audit rows
    def _open(self, pipeline, step, trigger, segment=None):
        """Insert a 'running' row, return its id (the app cursor is a
        RealDictCursor, so rows come back as dicts, not tuples)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "insert into pipeline_runs (pipeline, step, trigger, status, segment)"
                    " values (%s,%s,%s,'running',%s) returning id",
                    (pipeline, step, trigger, segment or self._segment))
                return str(cur.fetchone()["id"])
        except Exception as e:
            print("[scheduler] could not open pipeline_runs row: %r" % e, flush=True)
            return None

    def _close(self, row_id, status, detail=None):
        if not row_id:
            return
        try:
            with self._cursor() as cur:
                cur.execute(
                    "update pipeline_runs set status=%s, detail=%s, finished_at=now()"
                    " where id=%s", (status, detail, row_id))
        except Exception as e:
            print("[scheduler] could not close pipeline_runs row: %r" % e, flush=True)

    # -------------------------------------------------------------- run once
    def is_running(self, segment, pipeline):
        with self._kick_lock:
            return (segment, pipeline) in self._running

    def run_pipeline(self, pipeline, trigger="schedule", segment=None):
        segment = segment or self._segment
        steps = self.pipelines(segment).get(pipeline)
        if not steps:
            return
        with self._kick_lock:
            # six clicks in six seconds once queued six refreshes (2026-09-17): one at a time
            if (segment, pipeline) in self._running:
                return
            self._running.add((segment, pipeline))
        try:
            self._run_steps(pipeline, steps, trigger, segment)
        finally:
            with self._kick_lock:
                self._running.discard((segment, pipeline))

    def _run_steps(self, pipeline, steps, trigger, segment):
        print("[scheduler] pipeline '%s' starting (%s) for %s" % (pipeline, trigger, segment), flush=True)
        pid = self._open(pipeline, None, trigger, segment)
        env = {"SEGMENT_SLUG": segment}
        for key in steps:
            sid = self._open(pipeline, key, trigger, segment)
            # half an hour, not ten minutes: an outreach run drafting twenty production-house emails at
            # three model calls a minute can hold the slot for a while, and the refresh should wait for it
            rc, logpath = self._ops.run_blocking(key, wait_slot=1800, env=env)
            if rc is None:
                # slot never freed, or job unavailable here -- skip, do not fail
                self._close(sid, "skipped", "unavailable or slot busy")
                print("[scheduler]   %s skipped" % key, flush=True)
                continue
            if rc != 0:
                tail = self._logtail(logpath)
                self._close(sid, "failed", tail)
                self._close(pid, "failed", "stopped at step '%s'" % key)
                self.alert("TVF Lead Engine [%s]: pipeline '%s' FAILED at step '%s'.\n%s"
                           % (segment, pipeline, key, tail[-400:]))
                print("[scheduler] pipeline '%s' failed at '%s'" % (pipeline, key),
                      flush=True)
                return
            self._close(sid, "ok")
            print("[scheduler]   %s ok" % key, flush=True)
        self._close(pid, "ok")
        print("[scheduler] pipeline '%s' complete" % pipeline, flush=True)

    def _logtail(self, logpath, n=1200):
        if not logpath:
            return ""
        try:
            return self._ops.io_open(logpath, "r").read()[-n:]
        except OSError:
            return ""

    # --------------------------------------------------------- the simple flow
    @staticmethod
    def _env(name):
        v = os.environ.get(name)
        if v:
            return v
        path = os.path.join(REPO, ".env")
        if os.path.exists(path):
            for line in io.open(path, encoding="utf-8"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
        return None

    def mailbox_connected(self, mb):
        """The same test tools/outreach.py makes: an address, and a Gmail token on this machine."""
        return bool(self._env(mb["email_env"])) and (
            os.path.exists(os.path.join(REPO, mb["token_file"])) or bool(self._env(mb["token_env"])))

    def outreach_work(self, segment, now=None):
        """What the flow has to do for a segment right now, or None when the segment writes no email."""
        tools = os.path.join(REPO, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import outreach_policy as pol
        now = now or _now()
        with self._cursor() as cur:
            cfg = pol.outreach_config(cur, segment)
            from lead_lifecycle import PROTECTED, OPEN, retention_days
            cur.execute("select config from segments where slug=%s", (segment,))
            retention = cur.fetchone()
            days = retention_days(retention["config"]) if retention else None
            expire = False
            if days:
                cur.execute("select 1 from entities e join segments s on s.id=e.segment_id "
                            "where s.slug=%s and e.status in %s and not (" + PROTECTED + ") "
                            "and e.created_at <= now() - %s * interval '1 day' limit 1", (segment, OPEN, days))
                expire = cur.fetchone() is not None
            # first emails to draft: opener templates only. Universal's emails are written by people and it has
            # only a follow-up template (owner, 2026-10-23), so it drafts no first emails
            templates = any(isinstance(t, dict) and t.get("kind") != "follow_up" for t in (cfg or {}).get("templates") or [])
            # a project whose emails a person writes (outreach.compose, the Universal project since
            # 2026-09-27) has nothing to draft, but what they approved still has to go out
            if not templates and not (cfg or {}).get("compose") and not pol.followup_steps(cfg):
                return None
            draft = False
            if templates:
                cur.execute(DRAFT_NEEDED_SQL, (segment,))
                draft = cur.fetchone() is not None
            steps = pol.followup_steps(cfg)
            followups = bool(steps) and bool(pol.due_followups(cur, segment, steps, now))
            cur.execute(APPROVED_SQL, {"segment": segment, "now": now})
            approved = cur.fetchone() is not None
            boxes = pol.mailbox_list(cfg, segment)
            connected = [mb["key"] for mb in boxes if mb["enabled"] and self.mailbox_connected(mb)]
            paused = pol.sending_paused(cfg)                 # the owner's pause: approved emails wait
            approver_mode = cfg.get("send_from") == "approver"
            if approver_mode:
                # people's own Gmail addresses, connected in the app; the project's mailbox (the env one)
                # still reads replies to what it sent, but sends nothing new
                cur.execute("select address from user_mailboxes where enabled and last_error is null")
                connected = connected + [r["address"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            pull = False
            if connected:                                    # reading replies is not sending: a pause does not stop it
                cur.execute(PULL_DUE_SQL, {"segment": segment, "every": PULL_EVERY_MINUTES})
                row = cur.fetchone()
                pull = bool(row["due"] if isinstance(row, dict) else row[0])
            room = 0
            if approved and connected and not paused and not pol.sender_unset(cfg.get("sender")):
                if approver_mode:
                    cur.execute(APPROVER_SENDABLE_SQL, {"segment": segment, "now": now})
                    room = 1 if cur.fetchone() is not None else 0
                else:
                    status = pol.mailbox_status(cur, segment, boxes, now.date())
                    sent_today = sum(st["sent_today"] for st in status)
                    room = min(max(0, int(cfg.get("daily_send_cap", 20)) - sent_today),
                               sum(st["remaining"] for st in status if st["key"] in connected))
        return {"draft": draft, "followups": followups, "approved": approved, "connected": connected,
                "paused": bool(paused), "send": approved and room > 0, "pull": pull, "expire": expire}

    def outreach_tick(self, segment, trigger="schedule"):
        """Draft what needs drafting, send what is approved. -> "idle" | "ok" | "skipped" | "failed"."""
        work = self.outreach_work(segment)
        if not work:
            return "idle"
        # replies first: a reply that arrived pauses the follow-ups the next step would draft
        steps = ([("expire_leads", work.get("expire")), ("pull_replies", work.get("pull")), ("draft_followups", work["followups"]),
                  ("draft_outreach", work["draft"]), ("send_outreach", work["send"])])
        steps = [k for k, needed in steps if needed]
        if not steps:
            return "idle"
        print("[outreach] %s (%s): %s" % (segment, trigger, ", ".join(steps)), flush=True)
        pid = self._open("outreach", None, trigger, segment)
        env, outcome, failed, notes = {"SEGMENT_SLUG": segment}, "ok", [], []
        for key in steps:
            sid = self._open("outreach", key, trigger, segment)
            note = None
            if key == "send_outreach":
                # the send has its own lane (app/ops.py run_send): never behind the weekly refresh's slot. It waits
                # a few minutes for a free send worker, as the slot's jobs wait for the slot (second review,
                # 2026-10-12): a project with no sending window is sent only here, and giving up at once while
                # timed sends held both workers left its approved email for the next tick
                busy = {}
                rc, logpath = self._ops.run_send(segment, env, wait=TICK_SEND_WAIT, busy=busy)
                if rc is None:
                    self._close(sid, "skipped", "skipped: every send worker stayed busy for %d minutes; the next tick"
                                " tries again" % (TICK_SEND_WAIT // 60) if busy.get("why") == "workers"
                                else "skipped: a send for this project is already running")
                    outcome = "skipped" if outcome == "ok" else outcome
                    continue
                # what the run said it did: an address Gmail refused, emails moved three times (alerted once)
                summary = self._send_summary(logpath)
                self._after_send(segment, summary)
                note = self._refusal_note(summary)
            else:
                rc, logpath = self._ops.run_blocking(key, wait_slot=600, env=env)
            if rc is None:
                self._close(sid, "skipped", "the job slot stayed busy; the next tick tries again")
                outcome = "skipped" if outcome == "ok" else outcome
                continue
            if rc != 0:
                tail = self._logtail(logpath)
                self._close(sid, "failed", tail)
                self.alert("TVF Lead Engine [%s]: outreach step '%s' FAILED.\n%s" % (segment, key, tail[-400:]))
                # the steps are independent: a drafting step that failed (one lead that could not be
                # drafted) used to stop the run before its send, holding every approved email (2026-09-21)
                failed.append(key)
                outcome = "failed"
                continue
            # a send that handled a Gmail refusal ends 0: its rows say what was refused, so Operations shows it
            self._close(sid, "ok", note)
            if note:
                notes.append(note)
        detail = "; ".join(([("failed at step(s) %s" % ", ".join("'%s'" % k for k in failed))] if failed else []) + notes)
        self._close(pid, outcome, detail or None)
        return outcome

    def kick_outreach(self, segment, trigger="manual"):
        """Run outreach_tick for a segment in the background. A kick while one is running asks it to
        go round once more instead of starting a second: ten shortlists in a row are one or two runs."""
        with self._kick_lock:
            if segment in self._kicking:
                self._kick_again.add(segment)
                return False
            self._kicking.add(segment)

        def run():
            while True:
                try:
                    self.outreach_tick(segment, trigger)
                except Exception as e:                      # never let a background run die silently
                    print("[outreach] %s crashed: %r" % (segment, e), flush=True)
                    self.alert("TVF Lead Engine [%s]: the outreach run crashed: %r" % (segment, e))
                with self._kick_lock:
                    if segment in self._kick_again:
                        self._kick_again.discard(segment)
                        continue
                    self._kicking.discard(segment)
                    return
        threading.Thread(target=run, daemon=True).start()
        return True

    # ---------------------------------------------------------- the send loop
    def wake_sender(self):
        """An approval just gave an email its moment: look again now rather than at the next pass."""
        self._send_wake.set()

    def _alert_once(self, key, text):
        if key in self._alerted:
            return
        self._alerted.add(key)
        self.alert(text)

    def _missed_alert(self, slug, ids):
        """Approved emails that have moved MISSES_TO_ALERT times (a pause aside): told once each."""
        fresh = [i for i in dict.fromkeys(ids or []) if ("missed", i) not in self._alerted]
        for i in fresh:
            self._alerted.add(("missed", i))
        if fresh:
            tools = os.path.join(REPO, "tools")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import outreach_policy as pol
            self.alert("TVF Lead Engine [%s]: %d approved email(s) have missed %d sending windows in a row and moved"
                       " again: see Outreach -> Approved (why each moved is on it)."
                       % (slug, len(fresh), pol.MISSES_TO_ALERT))

    def _send_summary(self, logpath):
        """The run's own account of itself, its log's last SUMMARY_TAG line (tools/outreach.py cmd_send):
        {sent, deferred, parked, cancelled, left_alone, refused, alert_ids}, or None."""
        if not logpath:
            return None
        try:
            text = self._ops.io_open(logpath, "r").read()
        except (OSError, AttributeError):
            return None
        for line in reversed(text.splitlines()):
            if line.startswith(SUMMARY_TAG):
                try:
                    got = json.loads(line[len(SUMMARY_TAG):])
                except ValueError:
                    return None
                return got if isinstance(got, dict) else None
        return None

    @staticmethod
    def _refusal_note(summary):
        """What a send run that handled a Gmail refusal writes on its run rows (second review, 2026-10-12):
        "Gmail refused a@x (403): its emails moved to their next window, saying why". Such a run ends 0 -- it
        moved that address's emails and the others carried on -- so without a word its rows read only "OK", and
        a lasting refusal (an account barred from sending) showed Operations green day after day, the alert
        webhook still unset. Operations shows the latest one (/api/schedule refused). -> text or None."""
        refused = (summary or {}).get("refused") or {}
        if not refused:
            return None
        return ("%s: %s emails moved to their next window, saying why; the other addresses carry on"
                % ("; ".join(str(refused[k]) for k in sorted(refused)), "its" if len(refused) == 1 else "their"))

    def _after_send(self, slug, summary, due_ids=None):
        """What a finished send run said (review, 2026-10-12): Gmail refusing an address is told once a day
        per address -- the run handled it, moving that address's emails, so it is not a failure that holds
        the project back -- emails that have moved three times are told once, and the due emails it could do
        nothing with start no new run for IDLE_RETRY seconds.
        due_ids: what DUE_SQL said was due when the send loop started the run. A run that sent, moved, parked and
        cancelled nothing could do nothing with any of them, whichever way it went (second review, 2026-10-12):
        they wait IDLE_RETRY too, even where a path of the run forgot to name one in left_alone, so the loop
        never starts a run every few seconds for the rest of a window."""
        if not summary:
            return
        self._missed_alert(slug, summary.get("alert_ids"))
        day = _now().strftime("%Y-%m-%d")
        for addr, why in sorted((summary.get("refused") or {}).items()):
            self._alert_once(("refused", slug, addr, day),
                             "TVF Lead Engine [%s]: %s. Its emails moved to their next window, saying why; the other"
                             " addresses carry on. If it is the sign-in, its person connects it again in the app"
                             " (account menu, Your Gmail), or the owner links it (tools/users.py gmail <login>)."
                             % (slug, why))
        left = list(summary.get("left_alone") or [])
        if due_ids and not any(int(summary.get(k) or 0) for k in ("sent", "deferred", "parked", "cancelled")):
            left += [str(i) for i in due_ids]
        if left:
            until = time.time() + IDLE_RETRY
            memo = self._left.setdefault(slug, {})
            for i in left:
                memo[str(i)] = until

    def _look(self, slug, r, pol, sw):
        """One project's part of a pass: settle its times where they need it, and say whether a send should
        start for it now. -> (seconds to its next moment or None, start?)."""
        try:
            with self._cursor() as cur:
                cfg = pol.outreach_config(cur, slug)
            w = sw.window_cfg(cfg)
        except ValueError as e:
            self._alert_once(("config", slug, str(e)),
                             "TVF Lead Engine [%s]: outreach.send_window is not valid, nothing is sent until it is"
                             " fixed: %s" % (slug, e))
            return None, False
        paused = pol.sending_paused(cfg)
        plan = sw.plan_key(w) if w else None
        if (slug not in self._plans or self._plans[slug] != plan
                or (w and (r["missed"] or r["unscheduled"])) or (not w and r["timed_rows"])):
            # times to give, move, place again or clear: the same settle every send run starts with
            with self._cursor() as cur:
                out = pol.settle_schedule(cur, slug, cfg, paused=bool(paused))
            self._plans[slug] = plan
            self._missed_alert(slug, out["alert_ids"])
        if not w:
            return None, False
        nxt = float(r["next_in"]) if r.get("next_in") is not None else None
        if paused or not r["due"]:
            return nxt, False
        until, _secs = self._cooldown.get(slug, (0, 0))
        if time.time() < until:
            return nxt, False
        # never a second run for a project (review, 2026-10-12): one started by this loop and not yet ended,
        # or one in its lane from a tick
        with self._kick_lock:
            if slug in self._sending:
                return nxt, False
        if self._ops.send_busy(slug):
            return nxt, False
        # nor one for due emails the last run could do nothing with (another machine's sign-in): they stay due
        # all window, and a run started for them every few seconds would only leave them alone again
        now = time.time()
        memo = {i: t for i, t in (self._left.get(slug) or {}).items() if t > now}
        self._left[slug] = memo
        due_ids = {str(i) for i in (r.get("due_ids") or [])}
        if due_ids and due_ids <= set(memo):
            return nxt, False
        return nxt, True

    def _send_pass(self):
        """One look at every project's approved emails (DUE_SQL); settle their times where they need it and
        start a send for each project with an email due now. -> seconds to the next moment, or None.
        Each project's look stands alone (review, 2026-10-12): one that fails -- a database error, a lead whose
        metadata the zone resolver chokes on -- is told once and the others carry on."""
        tools = os.path.join(REPO, "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        import outreach_policy as pol
        import send_window as sw
        served = set(self.segments())
        with self._cursor() as cur:
            cur.execute(DUE_SQL)
            rows = [dict(r) for r in cur.fetchall()]
        next_in, ready, due_of = None, [], {}
        for r in rows:
            slug = r["slug"]
            if slug not in served:
                continue
            due_of[slug] = [str(i) for i in (r.get("due_ids") or [])]
            try:
                nxt, start = self._look(slug, r, pol, sw)
            except Exception as e:                    # noqa: BLE001 -- one project never stops the others
                print("[send] %s: the look failed: %r" % (slug, e), flush=True)
                self._alert_once(("pass", slug, type(e).__name__),
                                 "TVF Lead Engine [%s]: the send loop could not look at this project's approved emails"
                                 " (%s: %s); the other projects carry on." % (slug, type(e).__name__, str(e)[:200]))
                continue
            if nxt is not None:
                next_in = nxt if next_in is None else min(next_in, nxt)
            if start:
                ready.append(slug)
        # a free send worker goes to the project that has waited longest for one (SEND_WORKERS, app/ops.py)
        ready.sort(key=lambda s: self._wanted.get(s, float("inf")))
        free_fn = getattr(self._ops, "send_workers_free", None)
        free = free_fn() if free_fn else len(ready)
        for slug in ready:
            if free <= 0:
                self._wanted.setdefault(slug, time.time())
                continue
            free -= 1
            with self._kick_lock:
                self._sending.add(slug)
            try:
                threading.Thread(target=self._send_run, args=(slug,), kwargs={"due_ids": due_of.get(slug)},
                                 daemon=True).start()
            except Exception as e:                    # noqa: BLE001 -- no thread: nothing is running for it
                with self._kick_lock:
                    self._sending.discard(slug)
                print("[send] %s: could not start its send: %r" % (slug, e), flush=True)
        return next_in

    def _send_run(self, slug, due_ids=None):
        """One timed send for a project, recorded as its own pipeline, "send": a whole-run row and its
        send_outreach step (review, 2026-10-12: a step row alone never showed on Operations), opened only
        once the run has its lane and a worker. Second review, 2026-10-12: under the tick's "outreach" a timed
        run, about one a minute in a window, took over the Drafting and sending line within a minute of a tick
        whose drafting failed, hiding the failure; under "send" it feeds the Timed sending line instead
        (/api/schedule last.send). Gmail refusing an address is handled by the run, alerted from its summary
        and written on its rows; only a run that crashed (non-zero) backs the project off.
        due_ids: what was due when the loop started it (_after_send). The loop is woken to look again only once
        what this run left alone is remembered: woken first, its next pass started a new run for those very
        emails before the memo was written."""
        rows = {}

        def on_start():
            rows["pid"] = self._open("send", None, "schedule", slug)
            rows["sid"] = self._open("send", "send_outreach", "schedule", slug)
            self._wanted.pop(slug, None)
        try:
            busy = {}
            try:
                rc, logpath = self._ops.run_send(slug, {"SEGMENT_SLUG": slug}, stay=SEND_LOOP_STAY,
                                                 max_seconds=SEND_LOOP_MAX_RUN, on_start=on_start, busy=busy)
            except Exception as e:                    # never let a send thread die silently
                rc, logpath = -1, None
                print("[send] %s crashed: %r" % (slug, e), flush=True)
            if rc is None:
                # the project's lane or every worker was busy: nothing ran, nothing is recorded; with no worker
                # free it waits its turn for the next one (_send_pass)
                if (busy.get("why") or ("project" if self._ops.send_busy(slug) else "workers")) == "workers":
                    self._wanted.setdefault(slug, time.time())
                return
            if not rows:
                on_start()                            # it failed before it started: still on the record
            summary = self._send_summary(logpath)
            self._after_send(slug, summary, due_ids)
            if rc == 0:
                note = self._refusal_note(summary)
                self._cooldown.pop(slug, None)
                self._close(rows.get("sid"), "ok", note)
                self._close(rows.get("pid"), "ok", note)
                return
            tail = self._logtail(logpath)
            self._close(rows.get("sid"), "failed", tail)
            self._close(rows.get("pid"), "failed", "failed at step 'send_outreach'")
            until, secs = self._cooldown.get(slug, (0, 0))
            # doubling only while it keeps failing: a crash days after the last one starts again at 2 minutes
            secs = COOLDOWN_FIRST if not secs or time.time() - until > secs else min(COOLDOWN_MAX, secs * 2)
            self._cooldown[slug] = (time.time() + secs, secs)
            self._alert_once(("send-failed", slug, int(time.time() // secs)),
                             "TVF Lead Engine [%s]: a timed send FAILED; the next try is in %d minutes.\n%s"
                             % (slug, secs // 60, tail[-400:]))
        finally:
            with self._kick_lock:
                self._sending.discard(slug)
            self._send_wake.set()                     # look again now: a freed worker goes to whoever waits

    def _send_loop(self):
        """Each approved email at its own second (owner, 2026-10-12: "send mails to the sender's time region
        between 10 to 10:30AM and that must be randmized not like all mail going at 10:15 some must be going
        at 10:17 some at 10:13"). The fifteen-minute tick would send a window's emails at 10:00, 10:15 and
        10:30 in bunches, and the main loop is held for hours by the Friday refresh (02:00 UTC, across
        India's 04:30-05:00 UTC window), so this loop runs on its own thread: it looks every few seconds --
        sooner when the next moment is near, or when an approval wakes it -- and starts a send in the send
        lane (app/ops.py run_send) for each project with an email due, which stays on for the next moment
        (--stay). Two senders never race: the claim in tools/outreach.py is the guarantee, and sql/34 refuses
        a claim outside the email's window. Every minute it also turns an email left in 'sending' by a send
        that died into 'send_unknown' (outreach_policy.sweep_stale_sending), so a person checks Gmail's Sent
        before it is sent again."""
        self._stop.wait(5)
        last_sweep = 0.0
        while not self._stop.is_set():
            wait = SEND_LOOP_MAX_WAIT
            try:
                if time.monotonic() - last_sweep >= SWEEP_EVERY:
                    last_sweep = time.monotonic()
                    tools = os.path.join(REPO, "tools")
                    if tools not in sys.path:
                        sys.path.insert(0, tools)
                    import outreach_policy as pol
                    with self._cursor() as cur:
                        n = pol.sweep_stale_sending(cur)
                    if n:
                        self.alert("TVF Lead Engine: %d email(s) were left mid-send (a send stopped between its claim"
                                   " and Gmail's answer); marked 'send unknown' -- check Gmail's Sent before resending."
                                   % n)
                next_in = self._send_pass()
                if next_in is not None:
                    wait = max(1.0, min(SEND_LOOP_MAX_WAIT, next_in))
            except Exception as e:                        # the loop outlives any one bad pass
                print("[send] pass failed: %r" % (e,), flush=True)
            self._send_wake.wait(wait)
            self._send_wake.clear()

    def reply_pass(self):
        """One quick look for replies in every project that has threads to read. -> the projects looked at."""
        looked = []
        for segment in self.segments():
            with self._cursor() as cur:
                cur.execute(REPLY_THREADS_SQL, (segment,))
                if cur.fetchone() is None:
                    continue
            rc, logpath = self._ops.run_pull(segment, recent=True)
            if rc is None:
                continue                                  # one is still running for it
            looked.append(segment)
            if rc != 0:
                self._alert_once(("reply_pull", segment), "TVF Lead Engine [%s]: the five-minute look for replies"
                                 " FAILED.\n%s" % (segment, self._logtail(logpath)[-400:]))
        return looked

    def _reply_loop(self):
        """Every five minutes, a quick look for replies (REPLY_EVERY_SECONDS): a lead's reply reaches the app, and
        the alert the inbox of the person who wrote to them, within minutes, not at the next hour."""
        self._stop.wait(60)
        while not self._stop.is_set():
            try:
                self.reply_pass()
            except Exception as e:                        # the loop outlives any one bad pass
                print("[replies] pass failed: %r" % (e,), flush=True)
            self._stop.wait(REPLY_EVERY_SECONDS)

    # ------------------------------------------------------------- the loop
    def _due(self, entry, now):
        if not entry.get("enabled", True):
            return False
        if entry.get("dow") not in ("*", None) and entry["dow"] != now.weekday():
            return False
        if int(entry.get("hour", 0)) != now.hour:
            return False
        if int(entry.get("minute", 0)) != now.minute:
            return False
        return True

    def catch_up(self):
        """One outreach round for every segment, right after the server starts. A restart (every deploy)
        otherwise left an approval waiting for the next quarter-hour tick: on 2026-09-21 the first real
        email waited from its 09:19 deploy to the 09:30 tick. -> the segments kicked.
        Recorded as "schedule": pipeline_runs.trigger accepts only schedule and manual, and a "startup"
        row was refused, so the round ran with no line in the run history."""
        segments = self.segments()
        for segment in segments:
            self.kick_outreach(segment, "schedule")
        return segments

    def _loop(self):
        # settle: let the web server finish starting before the first check
        self._stop.wait(20)
        if not self._stop.is_set():
            try:
                self.catch_up()                 # whatever was approved while the server was restarting
            except Exception as e:              # never let the catch-up stop the loop from starting
                print("[scheduler] catch-up after start failed: %r" % e, flush=True)
        while not self._stop.is_set():
            now = _now()
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            for segment in self.segments():
                for entry in self.schedule(segment):
                    name = entry.get("name", entry.get("pipeline", "?"))
                    if self._fired.get((segment, name)) == minute_key:
                        continue
                    if self._due(entry, now):
                        self._fired[(segment, name)] = minute_key
                        try:
                            self.run_pipeline(entry["pipeline"], segment=segment)
                        except Exception as e:
                            self.alert("TVF Lead Engine [%s]: scheduler crashed running "
                                       "'%s': %r" % (segment, name, e))
                            print("[scheduler] run_pipeline crashed: %r" % e, flush=True)
            # the simple flow's catch-up: every fifteen minutes, draft and send whatever is waiting
            if now.minute % TICK_MINUTES == 0 and self._last_tick != minute_key:
                self._last_tick = minute_key
                for segment in self.segments():
                    self.kick_outreach(segment, "schedule")
            # wake a little under once a minute so no minute is skipped
            self._stop.wait(30)

    @staticmethod
    def send_loop_wanted(environ=None):
        """-> (on, why). The send loop runs wherever the scheduler runs, unless SEND_LOOP_ENABLED=0 says
        otherwise (review, 2026-10-12). It used to need SEND_LOOP_ENABLED=1, which only render.yaml set:
        docker-compose.prod.yml, deploy/render.lcx-clipping.yaml, the Hugging Face fallback (docs/DEPLOY.md) and
        a Render service not synced from the Blueprint left it off, and then timed emails went only at the
        fifteen-minute ticks and most of each window moved to the next day, silently. A machine that cannot
        read the sign-ins (a laptop running the app) is harmless with it on: its sends leave those emails
        alone, and the loop does not start again for them (IDLE_RETRY). Only SEND_LOOP_ENABLED=1 makes a send
        run count itself the server (tools/outreach.py on_the_server); the laptop's Docker stack
        (docker-compose.yml) says 0 and runs no loop (second review, 2026-10-12)."""
        env = os.environ if environ is None else environ
        if str(env.get("SCHEDULER_ENABLED", "1")).strip().lower() not in ("1", "true", "yes"):
            return False, "the scheduler is off here (SCHEDULER_ENABLED=%s)" % env.get("SCHEDULER_ENABLED")
        if str(env.get("SEND_LOOP_ENABLED", "")).strip().lower() in ("0", "false", "no"):
            return False, ("SEND_LOOP_ENABLED=%s: timed emails go only at the fifteen-minute ticks, and most of"
                           " each window moves to the next weekday" % env.get("SEND_LOOP_ENABLED"))
        return True, "each approved email goes at its own second; the loop looks every few seconds"

    def send_loop_state(self):
        """{on, why} for Operations (/api/schedule): is the timed sender running in this server?"""
        if self._send_thread and self._send_thread.is_alive():
            return {"on": True, "why": self._send_loop_why}
        if self._send_loop_on:
            return {"on": False, "why": "it was started and has stopped: restart the server"}
        return {"on": False, "why": self._send_loop_why}

    def start(self):
        import os
        if os.environ.get("SCHEDULER_ENABLED", "1") not in ("1", "true", "yes"):
            print("[scheduler] disabled by SCHEDULER_ENABLED", flush=True)
            self._send_loop_on, self._send_loop_why = False, self.send_loop_wanted()[1]
            print("[scheduler] send loop OFF: %s" % self._send_loop_why, flush=True)
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[scheduler] started", flush=True)
        # the timed sends' loop: wherever the scheduler runs, unless SEND_LOOP_ENABLED=0 (send_loop_wanted).
        # One line at start says which, so a server where it is off says so in its log, and on Operations
        self._send_loop_on, self._send_loop_why = self.send_loop_wanted()
        if self._send_loop_on:
            self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
            self._send_thread.start()
            print("[scheduler] send loop ON: %s" % self._send_loop_why, flush=True)
            # the five-minute look for replies: where the sends run (the server), never on a laptop's stack
            threading.Thread(target=self._reply_loop, daemon=True).start()
            print("[scheduler] reply look ON: every %d minutes" % (REPLY_EVERY_SECONDS // 60), flush=True)
        else:
            print("[scheduler] send loop OFF: %s" % self._send_loop_why, flush=True)

    def stop(self):
        self._stop.set()
        self._send_wake.set()
