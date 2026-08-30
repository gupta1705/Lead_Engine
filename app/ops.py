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

from fastapi import APIRouter, HTTPException

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
    },
    "harvest_wikidata": {
        "label": "Harvest: Wikidata",
        "group": "Discover",
        "desc": "Run the P7 seed -- US film+TV companies, domains attached.",
        "cmd": ["n8n", "execute", "--id", "wikidataseed01"],
        "needs": "n8n",
    },
    "harvest_youtube": {
        "label": "Harvest: YouTube",
        "group": "Discover",
        "desc": "Run the P4 connector (quota ~750 units/run).",
        "cmd": ["n8n", "execute", "--id", "ytdiscovery00001"],
        "needs": "n8n",
    },
    "harvest_aicp": {
        "label": "Harvest: AICP directory",
        "group": "Discover",
        "desc": "Re-scrape the member directory (names refresh).",
        "cmd": ["n8n", "execute", "--id", "aicpdirectory1"],
        "needs": "n8n",
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
    },
    "news_sweep": {
        "label": "News evidence sweep",
        "group": "Enrich",
        "desc": "Ask the news archive about each contactable company by name.",
        "cmd": [PY, "tools/enrich_newscheck.py", "--limit", "200"],
    },
    "draft_outreach": {
        "label": "Draft outreach emails",
        "group": "Outreach",
        "desc": "Personalised drafts for shortlisted leads. Drafts are inert "
                "until you approve each one in the Outreach tab.",
        "cmd": [PY, "tools/outreach.py", "draft"],
    },
}

_LOCK = threading.Lock()
_STATE = {}     # key -> {status, started, finished, rc, log}
_CURRENT = {"key": None, "proc": None}


def _available(job):
    if job.get("needs") == "n8n" and shutil.which("n8n") is None:
        return False, "needs the n8n CLI -- run from the host until P25"
    return True, None


def _runner(key, job, logpath):
    with io_open(logpath, "w") as logf:
        try:
            proc = subprocess.Popen(
                job["cmd"], cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
            _CURRENT["proc"] = proc
            rc = proc.wait()
        except Exception as e:
            logf.write("\nrunner error: %r\n" % (e,))
            rc = -1
    with _LOCK:
        _STATE[key].update(status="done" if rc == 0 else "failed",
                           finished=time.time(), rc=rc)
        _CURRENT["key"] = None
        _CURRENT["proc"] = None


def io_open(path, mode):
    import io as _io
    return _io.open(path, mode, encoding="utf-8", errors="replace")


def build_router():
    r = APIRouter()
    LOGDIR.mkdir(parents=True, exist_ok=True)

    @r.get("/api/ops")
    def list_jobs():
        out = []
        for key, job in JOBS.items():
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
    def run_job(key: str):
        job = JOBS.get(key)
        if not job:
            raise HTTPException(404, "no such job")
        ok, why = _available(job)
        if not ok:
            raise HTTPException(409, why)
        with _LOCK:
            if _CURRENT["key"]:
                raise HTTPException(409, "another job is running: " + _CURRENT["key"])
            logpath = LOGDIR / ("%s-%d.log" % (key, int(time.time())))
            _STATE[key] = {"status": "running", "started": time.time(),
                           "finished": None, "rc": None, "log": str(logpath)}
            _CURRENT["key"] = key
        threading.Thread(target=_runner, args=(key, job, logpath),
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
