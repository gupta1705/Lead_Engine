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
  * schedules for anything that SENDS email stay off until Gmail is configured

Everything here is opt-in-safe: the loop only fires the enrichment pipeline,
which reads and writes our own database and politely crawls sites we already
visit. Nothing outbound happens without the Gmail credential the owner adds.
"""
import json
import threading
import time
import urllib.request
from datetime import datetime, timezone

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
    def __init__(self, cursor, ops, segment="us-production-houses"):
        self._cursor = cursor          # app DB contextmanager
        self._ops = ops                # the ops module (run_blocking, JOBS)
        self._segment = segment
        self._thread = None
        self._stop = threading.Event()
        self._fired = {}               # name -> last-fired minute-key, dedupe

    # ---------------------------------------------------------------- config
    def schedule(self):
        try:
            with self._cursor() as cur:
                cur.execute("select config->'schedule' from segments where slug=%s",
                            (self._segment,))
                row = cur.fetchone()
            got = row and row[0]
            if got:
                return got
        except Exception:
            pass
        return DEFAULT_SCHEDULE

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
    def _open(self, pipeline, step, trigger):
        """Insert a 'running' row, return its id (the app cursor is a
        RealDictCursor, so rows come back as dicts, not tuples)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    "insert into pipeline_runs (pipeline, step, trigger, status)"
                    " values (%s,%s,%s,'running') returning id",
                    (pipeline, step, trigger))
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
    def run_pipeline(self, pipeline, trigger="schedule"):
        steps = PIPELINES.get(pipeline)
        if not steps:
            return
        print("[scheduler] pipeline '%s' starting (%s)" % (pipeline, trigger), flush=True)
        pid = self._open(pipeline, None, trigger)
        for key in steps:
            sid = self._open(pipeline, key, trigger)
            rc, logpath = self._ops.run_blocking(key, wait_slot=600)
            if rc is None:
                # slot never freed, or job unavailable here -- skip, do not fail
                self._close(sid, "skipped", "unavailable or slot busy")
                print("[scheduler]   %s skipped" % key, flush=True)
                continue
            if rc != 0:
                tail = self._logtail(logpath)
                self._close(sid, "failed", tail)
                self._close(pid, "failed", "stopped at step '%s'" % key)
                self.alert("TVF Lead Engine: pipeline '%s' FAILED at step '%s'.\n%s"
                           % (pipeline, key, tail[-400:]))
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
            for entry in self.schedule():
                name = entry.get("name", entry.get("pipeline", "?"))
                if self._fired.get(name) == minute_key:
                    continue
                if self._due(entry, now):
                    self._fired[name] = minute_key
                    try:
                        self.run_pipeline(entry["pipeline"])
                    except Exception as e:
                        self.alert("TVF Lead Engine: scheduler crashed running "
                                   "'%s': %r" % (name, e))
                        print("[scheduler] run_pipeline crashed: %r" % e, flush=True)
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
