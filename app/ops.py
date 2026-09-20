#!/usr/bin/env python3
"""ops.py -- the pipeline's tools as one-click jobs in the UI.

WHY ONE JOB AT A TIME. Every tool here either writes to the same database
tables or crawls with per-host politeness budgets. Two enrichment passes at
once means double the request rate to somebody's small website and two
writers racing on scoring_inputs. A single execution slot makes the whole
class of problem impossible, and a BD team genuinely never needs two of
these running concurrently.

WHY SUBPROCESSES AND NOT IMPORTS. The tools are already battle-tested as
CLIs -- durable connections, per-row commits, resumable stamps. Running them
as subprocesses means the UI gets exactly the behaviour the terminal gets,
including the logs, and a crashing tool can never take the web server down
with it.

OUTREACH IS NOT A BUTTON HERE. Drafting and sending run by themselves since
2026-09-19 (the owner's simple flow: shortlist, approve, sent): the jobs exist
so the scheduler's outreach_tick can run them through this same slot, but they
are hidden from the grid. The only way an email leaves is a person approving
that email. Reply pull and triage stay in the terminal (tools/outreach.py).

NO JOB GRID (2026-09-19). Every job here is a step of a pipeline the scheduler
runs (app/scheduler.py), so Operations offers the whole weekly refresh, not its
steps one by one, and shows the log of whatever holds the slot. The n8n
harvests, which the server cannot run, and the finished one-offs (pool import,
startup backfill) left the list; their tools still run from a terminal.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

REPO = Path(__file__).resolve().parent.parent
LOGDIR = REPO / "logs" / "ops"

PY = "python"

JOBS = {
    "discover_podcasts": {
        "label": "Harvest: podcasts (Apple search + feeds)",
        "group": "Discover",
        "desc": "Keyless. Search terms x store countries, then each new show's own "
                "feed: catalogue, cadence, contact, YouTube link. Runs here in the cloud.",
        "cmd": [PY, "tools/discover_podcasts.py", "--max-searches", "60", "--limit-feeds", "300"],
        "segments": ["lcx-clipping"],
    },
    "discover_youtube": {
        "label": "Harvest: YouTube channels (shorts gap)",
        "group": "Discover",
        "desc": "Channel search plus statistics and the last 50 uploads with durations. "
                "About 2,700 quota units per run.",
        "cmd": [PY, "tools/discover_youtube_channels.py", "--max-searches", "15", "--limit-channels", "400"],
        "segments": ["lcx-clipping"],
    },
    "enrich_clipping": {
        "label": "Enrich shows (contact + YouTube evidence)",
        "group": "Enrich",
        "desc": "Lift the feed evidence, create the contact from the published address, "
                "profile linked YouTube channels for the shorts gap.",
        "cmd": [PY, "tools/enrich_clipping.py", "--limit", "300"],
        "segments": ["lcx-clipping"],
    },
    "discover_wikidata_channels": {
        "label": "Harvest: production companies with a YouTube channel (Wikidata)",
        "group": "Discover",
        "desc": "Film, TV and animation companies worldwide that list a channel on Wikidata, "
                "US first; each channel profiled for the shorts gap. About 3 quota units per company.",
        "cmd": [PY, "tools/discover_wikidata_channels.py", "--limit-channels", "300"],
        "segments": ["lcx-clipping"],
    },
    "discover_startup_news": {
        "label": "Harvest: startup news (distress + funding)",
        "group": "Discover",
        "desc": "Google News headlines about layoffs, shutdowns, salary delays, insolvency and rescue rounds "
                "from the last 40 days. Headlines only; no article page is ever fetched.",
        "cmd": [PY, "tools/discover_startup_news.py"],
        "segments": ["startup-acquisitions"],
    },
    "enrich_startups": {
        "label": "Check startups (city, website, app, news)",
        "group": "Enrich",
        "desc": "Places each startup in Mumbai or elsewhere, reads its own website and App Store app, "
                "asks the news about it by name, and scores it.",
        "cmd": [PY, "tools/enrich_startups.py", "--limit", "400"],
        "segments": ["startup-acquisitions"],
    },
    "promote_chain": {
        "label": "Promote + score + gates",
        "group": "Process",
        "desc": "Staging into the pool: self-exclusion, promote, merge "
                "duplicates, zero-unverified, score, apply gates.",
        "cmd": [PY, "tools/run_chain.py"],
    },
    "resolve_domains": {
        "label": "Resolve missing websites",
        "group": "Enrich",
        "desc": "Wikidata lookup + verified guessing for domainless companies.",
        "cmd": [PY, "tools/resolve_domains.py", "--limit", "100", "--guess"],
    },
    "enrich_aicp": {
        "label": "Enrich from AICP records",
        "group": "Enrich",
        "desc": "Directory detail API: websites, emails, named people.",
        "cmd": [PY, "tools/enrich_aicp.py", "--limit", "250"],
        "segments": ["us-production-houses"],
    },
    "enrich_contacts": {
        "label": "Find contacts on sites",
        "group": "Enrich",
        "desc": "Polite site-scrape of companies with no contact yet.",
        "cmd": [PY, "tools/enrich_sitescrape.py", "--limit", "200", "--workers", "8"],
    },
    "enrich_apollo": {
        "label": "Ask Apollo for the missing addresses",
        "group": "Enrich",
        "desc": "Leads with a website and nobody to write to: one free search on the domain for the "
                "target roles, then 1 credit for the best person's work address. Capped per run, and "
                "only for a segment whose config enables it.",
        "cmd": [PY, "tools/enrich_apollo.py", "--limit", "120", "--budget", "150"],
        "segments": ["us-production-houses"],
    },
    "qualify_sites": {
        "label": "Qualify from sites",
        "group": "Enrich",
        "desc": "Team size, collaboration invitations, genre, platform credits.",
        "cmd": [PY, "tools/enrich_sitescrape.py", "--qualify",
                "--limit", "300", "--workers", "8"],
        "segments": ["us-production-houses"],
    },
    "news_sweep": {
        "label": "News evidence sweep",
        "group": "Enrich",
        "desc": "Ask the news archive about each contactable company by name, shortlisted ones included.",
        "cmd": [PY, "tools/enrich_newscheck.py", "--limit", "200", "--shortlisted"],
        "segments": ["us-production-houses"],
    },
    # The simple flow (owner, 2026-09-19): shortlist, approve, sent. These three run by themselves --
    # after a shortlist, after an approval, and every fifteen minutes (app/scheduler.py outreach_tick) --
    # so they are "hidden": not on the Operations page, not runnable from it. Approval stays the human
    # decision on every email; send only ever sends what a person approved.
    "draft_outreach": {
        "label": "Draft outreach emails",
        "group": "Outreach",
        "desc": "Personalised drafts for shortlisted leads. Drafts are inert "
                "until you approve each one in the Outreach tab.",
        "cmd": [PY, "tools/outreach.py", "draft"],
        "hidden": True,
    },
    "draft_followups": {
        "label": "Draft follow-ups",
        "group": "Outreach",
        "desc": "Follow-ups that are due, in the opener's thread. Stopped by any reply. "
                "Drafts still need approval in the Outreach tab.",
        "cmd": [PY, "tools/outreach.py", "followups"],
        "segments": ["lcx-clipping"],
        "hidden": True,
    },
    "send_outreach": {
        "label": "Send approved emails",
        "group": "Outreach",
        "desc": "Sends the emails a person approved, within the day's cap, from the connected mailboxes.",
        "cmd": [PY, "tools/outreach.py", "send"],
        "hidden": True,
    },
}

_LOCK = threading.Lock()
_STATE = {}     # key -> {status, started, finished, rc, log}
_CURRENT = {"key": None, "proc": None}



def _execute(key, job, logpath, env_extra=None):
    """Run one job's subprocess to completion. Returns its exit code.
    Assumes the caller already holds the slot (claimed _CURRENT['key']=key).
    env_extra carries SEGMENT_SLUG, so the same tool serves every segment."""
    with io_open(logpath, "w") as logf:
        try:
            logf.write("[ops] %s  segment=%s\n" % (key, (env_extra or {}).get("SEGMENT_SLUG", "default")))
            proc = subprocess.Popen(
                job["cmd"], cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(env_extra or {})})
            _CURRENT["proc"] = proc
            rc = proc.wait()
        except Exception as e:
            logf.write("\nrunner error: %r\n" % (e,))
            rc = -1
    with _LOCK:
        _STATE[key].update(status="done" if rc == 0 else "failed",
                           finished=time.time(), rc=rc)
    return rc


def _claim(key):
    """Take the single execution slot for key. Returns a logpath, or None if
    another job holds it. Shared by the HTTP handler and the scheduler, so the
    two can never run a job concurrently."""
    LOGDIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        if _CURRENT["key"]:
            return None
        logpath = LOGDIR / ("%s-%d.log" % (key, int(time.time())))
        _STATE[key] = {"status": "running", "started": time.time(),
                       "finished": None, "rc": None, "log": str(logpath)}
        _CURRENT["key"] = key
        return logpath


def _release():
    with _LOCK:
        _CURRENT["key"] = None
        _CURRENT["proc"] = None


def run_blocking(key, wait_slot=0, env=None):
    """Scheduler path: run one job to completion, respecting the single slot.

    Returns (rc, logpath_str). rc is None if the slot could not be claimed
    within wait_slot seconds (a manual job was running) or the job is
    unavailable in this environment. Blocks the CALLING thread, which for the
    scheduler is its own dedicated thread -- never the web server's.
    """
    job = JOBS.get(key)
    if not job:
        return None, None
    waited = 0.0
    logpath = _claim(key)
    while logpath is None and waited < wait_slot:
        time.sleep(2); waited += 2
        logpath = _claim(key)
    if logpath is None:
        return None, None
    try:
        rc = _execute(key, job, logpath, env)
    finally:
        _release()
    return rc, str(logpath)


def io_open(path, mode):
    import io as _io
    return _io.open(path, mode, encoding="utf-8", errors="replace")


def build_router():
    r = APIRouter()
    LOGDIR.mkdir(parents=True, exist_ok=True)

    @r.get("/api/ops")
    def busy_job():
        """The job holding the single slot, if any, so Operations can show its log."""
        key = _CURRENT["key"]
        return {"busy": key, "label": JOBS[key]["label"] if key in JOBS else key}

    @r.get("/api/ops/{key}/log")
    def job_log(key: str, tail: int = 120):
        st = _STATE.get(key)
        if not st or not st.get("log"):
            return {"lines": []}
        try:
            lines = io_open(st["log"], "r").read().splitlines()
        except OSError:
            lines = []
        return {"lines": lines[-max(10, min(tail, 500)):],
                "status": st.get("status")}

    @r.post("/api/ops/{key}/stop")
    def stop_job(key: str):
        if key == "send_outreach":
            raise HTTPException(409, "a send stops only by finishing: stopped midway, its email would stay marked sending")
        with _LOCK:
            if _CURRENT["key"] != key or not _CURRENT["proc"]:
                raise HTTPException(409, "that job is not running")
            _CURRENT["proc"].terminate()
        return {"ok": True}

    return r
