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
                and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)
limit 1"""
APPROVED_SQL = """
select 1 from outreach o join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %s)
  and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
limit 1"""
TICK_MINUTES = 15

# Pipelines: an ordered list of ops-job keys. A pipeline fails at the first
# step that fails; later steps do not run. run_chain appears twice in the
# refresh on purpose -- promote the freshly harvested rows first, then re-run
# it at the end to re-score once enrichment has added evidence, applying gates
# against the final scores.
PIPELINES = {
    "weekly_refresh": [
        "promote_chain",      # bring harvested staging into the pool, score, gate
        "resolve_domains",    # fill missing websites
        "enrich_aicp",        # directory detail: emails, named people
        "enrich_contacts",    # site-scrape contacts for whoever still lacks one
        "qualify_sites",      # team size, invitations, genre, platform credits
        "news_sweep",         # per-company IP/distribution evidence
        "promote_chain",      # re-score with the new evidence, re-apply gates
    ],
    "rescore": ["promote_chain"],
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
    def run_pipeline(self, pipeline, trigger="schedule", segment=None):
        segment = segment or self._segment
        steps = self.pipelines(segment).get(pipeline)
        if not steps:
            return
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
            if not (cfg or {}).get("templates"):
                return None
            cur.execute(DRAFT_NEEDED_SQL, (segment,))
            draft = cur.fetchone() is not None
            steps = pol.followup_steps(cfg)
            followups = bool(steps) and bool(pol.due_followups(cur, segment, steps, now))
            cur.execute(APPROVED_SQL, (segment,))
            approved = cur.fetchone() is not None
            boxes = pol.mailbox_list(cfg, segment)
            connected = [mb["key"] for mb in boxes if mb["enabled"] and self.mailbox_connected(mb)]
            room = 0
            if approved and connected and "SET_ME" not in json.dumps(cfg.get("sender") or {}):
                status = pol.mailbox_status(cur, segment, boxes, now.date())
                sent_today = sum(st["sent_today"] for st in status)
                room = min(max(0, int(cfg.get("daily_send_cap", 20)) - sent_today),
                           sum(st["remaining"] for st in status if st["key"] in connected))
        return {"draft": draft, "followups": followups, "approved": approved, "connected": connected,
                "send": approved and room > 0}

    def outreach_tick(self, segment, trigger="schedule"):
        """Draft what needs drafting, send what is approved. -> "idle" | "ok" | "skipped" | "failed"."""
        work = self.outreach_work(segment)
        if not work:
            return "idle"
        steps = ([("draft_followups", work["followups"]), ("draft_outreach", work["draft"]),
                  ("send_outreach", work["send"])])
        steps = [k for k, needed in steps if needed]
        if not steps:
            return "idle"
        print("[outreach] %s (%s): %s" % (segment, trigger, ", ".join(steps)), flush=True)
        pid = self._open("outreach", None, trigger, segment)
        env, outcome = {"SEGMENT_SLUG": segment}, "ok"
        for key in steps:
            sid = self._open("outreach", key, trigger, segment)
            rc, logpath = self._ops.run_blocking(key, wait_slot=600, env=env)
            if rc is None:
                self._close(sid, "skipped", "the job slot stayed busy; the next tick tries again")
                outcome = "skipped"
                continue
            if rc != 0:
                tail = self._logtail(logpath)
                self._close(sid, "failed", tail)
                self._close(pid, "failed", "stopped at step '%s'" % key)
                self.alert("TVF Lead Engine [%s]: outreach step '%s' FAILED.\n%s" % (segment, key, tail[-400:]))
                return "failed"
            self._close(sid, "ok")
        self._close(pid, outcome)
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

    def _loop(self):
        # settle: let the web server finish starting before the first check
        self._stop.wait(20)
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

    def start(self):
        import os
        if os.environ.get("SCHEDULER_ENABLED", "1") not in ("1", "true", "yes"):
            print("[scheduler] disabled by SCHEDULER_ENABLED", flush=True)
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[scheduler] started", flush=True)

    def stop(self):
        self._stop.set()
