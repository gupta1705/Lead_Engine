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

WHAT IS DELIBERATELY NOT HERE: outreach send/pull/triage. Those stay in the
terminal (tools/outreach.py) until the Gmail credential exists; a button that
sends email deserves its own considered UI moment, not a slot in a generic
job grid. Drafting IS here -- drafts are inert until a human approves them.

Harvests (P4-P8) run through the n8n CLI, which exists on the host but not
inside the app container; those jobs report themselves unavailable there
rather than failing, and the UI says why. P25 moves them fully into Docker.
"""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

REPO = Path(__file__).resolve().parent.parent
LOGDIR = REPO / "logs" / "ops"

PY = "python"

JOBS = {
    "harvest_news": {
        "label": "Harvest: Google News",
        "group": "Discover",
        "desc": "Run the P5 connector -- deal/format headlines into staging.",
        "cmd": ["n8n", "execute", "--id", "newsrssdiscov01"],
        "needs": "n8n",
        "segments": ["us-production-houses"],
    },
    "harvest_wikidata": {
        "label": "Harvest: Wikidata",
        "group": "Discover",
        "desc": "Run the P7 seed -- US film+TV companies, domains attached.",
        "cmd": ["n8n", "execute", "--id", "wikidataseed01"],
        "needs": "n8n",
        "segments": ["us-production-houses"],
    },
    "harvest_youtube": {
        "label": "Harvest: YouTube",
        "group": "Discover",
        "desc": "Run the P4 connector (quota ~750 units/run).",
        "cmd": ["n8n", "execute", "--id", "ytdiscovery00001"],
        "needs": "n8n",
        "segments": ["us-production-houses"],
    },
    "harvest_aicp": {
        "label": "Harvest: AICP directory",
        "group": "Discover",
        "desc": "Re-scrape the member directory (names refresh).",
        "cmd": ["n8n", "execute", "--id", "aicpdirectory1"],
        "needs": "n8n",
        "segments": ["us-production-houses"],
    },
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
    "import_pool": {
        "label": "Import the TVF production-house pool",
        "group": "Discover",
        "desc": "Copy the US production houses TVF already discovered, contacts included, into this "
                "segment; the enrichment pass then looks for each one's YouTube channel.",
        "cmd": [PY, "tools/import_pool.py", "--from", "us-production-houses", "--limit", "1500"],
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
    "discover_startup_backfill": {
        "label": "Harvest: startup news, full backfill",
        "group": "Discover",
        "desc": "Two years of distress headlines plus the Mumbai startups that raised a small round in 2021-24. "
                "About 120 searches; a few minutes.",
        "cmd": [PY, "tools/discover_startup_news.py", "--backfill"],
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
    "draft_outreach": {
        "label": "Draft outreach emails",
        "group": "Outreach",
        "desc": "Personalised drafts for shortlisted leads. Drafts are inert "
                "until you approve each one in the Outreach tab.",
        "cmd": [PY, "tools/outreach.py", "draft"],
    },
    "draft_followups": {
        "label": "Draft follow-ups",
        "group": "Outreach",
        "desc": "Follow-ups that are due, in the opener's thread. Stopped by any reply. "
                "Drafts still need approval in the Outreach tab.",
        "cmd": [PY, "tools/outreach.py", "followups"],
        "segments": ["lcx-clipping"],
    },
}

_LOCK = threading.Lock()
_STATE = {}     # key -> {status, started, finished, rc, log}
_CURRENT = {"key": None, "proc": None}


def _available(job):
    if job.get("needs") == "n8n" and shutil.which("n8n") is None:
        return False, "needs the n8n CLI -- run from the host until P25"
    return True, None


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


def _runner(key, job, logpath, env_extra=None):
    """HTTP path: execute then release the slot."""
    try:
        _execute(key, job, logpath, env_extra)
    finally:
        with _LOCK:
            _CURRENT["key"] = None
            _CURRENT["proc"] = None


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
    ok, _why = _available(job)
    if not ok:
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
    def list_jobs(request: Request):
        seg = getattr(request.state, "segment", None)
        out = []
        for key, job in JOBS.items():
            if seg and job.get("segments") and seg not in job["segments"]:
                continue
            ok, why = _available(job)
            st = _STATE.get(key, {})
            out.append({
                "key": key, "label": job["label"], "group": job["group"],
                "desc": job["desc"], "available": ok, "unavailable_reason": why,
                "status": st.get("status"),
                "running": _CURRENT["key"] == key,
                "started": st.get("started"), "finished": st.get("finished"),
                "rc": st.get("rc"),
            })
        return {"jobs": out, "busy": _CURRENT["key"]}

    @r.post("/api/ops/{key}/run")
    def run_job(key: str, request: Request):
        job = JOBS.get(key)
        if not job:
            raise HTTPException(404, "no such job")
        seg = getattr(request.state, "segment", None)
        if seg and job.get("segments") and seg not in job["segments"]:
            raise HTTPException(409, "that job does not apply to this segment")
        ok, why = _available(job)
        if not ok:
            raise HTTPException(409, why)
        logpath = _claim(key)
        if logpath is None:
            raise HTTPException(409, "another job is running: " + (_CURRENT["key"] or "?"))
        env = {"SEGMENT_SLUG": seg} if seg else None
        threading.Thread(target=_runner, args=(key, job, logpath, env),
                         daemon=True).start()
        return {"ok": True, "log": str(logpath.name)}

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
        with _LOCK:
            if _CURRENT["key"] != key or not _CURRENT["proc"]:
                raise HTTPException(409, "that job is not running")
            _CURRENT["proc"].terminate()
        return {"ok": True}

    return r
