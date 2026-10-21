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
    "expire_leads": {
        "label": "Clear expired leads",
        "group": "Process",
        "desc": "Archive untouched leads after the project's retention period; keep approvals and conversations.",
        "cmd": [PY, "tools/lead_lifecycle.py"],
        "hidden": True,
    },
    "discover_apollo": {
        "label": "Find leads on Apollo",
        "group": "Discover",
        "desc": "Apollo company searches using this project's constraints, saved search cursors and credit budget.",
        "cmd": [PY, "tools/discover_apollo.py"],
        "segments": ["us-production-houses", "startup-acquisitions", "lcx-services"],
    },
    "prepare_apollo": {
        "label": "Read Apollo company records",
        "group": "Enrich",
        "desc": "Carry Apollo's company ID, headquarters and audience into qualification and contact matching.",
        "cmd": [PY, "tools/enrich_lcx_services.py", "--limit", "3000"],
    },
    "verify_sites": {
        "label": "Check company fit",
        "group": "Enrich",
        "desc": "Read company sites to verify project constraints; contacts come from Apollo.",
        "cmd": [PY, "tools/enrich_sitescrape.py", "--qualify", "--evidence-only", "--limit", "1000", "--workers", "8"],
    },
    "enrich_apollo_project": {
        "label": "Find decision makers on Apollo",
        "group": "Enrich",
        "desc": "Find the project's target roles and verified work addresses within its existing Apollo budget.",
        "cmd": [PY, "tools/enrich_apollo.py", "--limit", "200"],
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
    "discover_lcx_wikidata": {
        "label": "Harvest: companies to pitch (Wikidata)",
        "group": "Discover",
        "desc": "Operating companies with a website in each audience's classes and industries (brands, retailers, "
                "real estate, hotels, publishers, financial services, studios and agencies, attractions, schools). "
                "Free, no key.",
        "cmd": [PY, "tools/discover_lcx_services.py", "--source", "wikidata"],
        "segments": ["lcx-services"],
    },
    "discover_lcx_osm": {
        "label": "Harvest: local businesses to pitch (OpenStreetMap)",
        "group": "Discover",
        "desc": "Independent cafes, salons, gyms, shops, estate agents, guest houses, schools and attractions that "
                "publish a website or an address, a few cities a week. Free, no key.",
        "cmd": [PY, "tools/discover_lcx_services.py", "--source", "osm"],
        "segments": ["lcx-services"],
    },
    "discover_lcx_apollo": {
        "label": "Harvest: corporates to pitch (Apollo company search)",
        "group": "Discover",
        "desc": "Mid-size companies with their websites, from Apollo's company search: companies hiring for content, "
                "video or training now, recently funded ones, and each audience by size and country. 1 credit a page of "
                "100, inside the project's weekly cap; a page that would come back empty is never bought.",
        "cmd": [PY, "tools/discover_lcx_services.py", "--source", "apollo"],
        "segments": ["lcx-services"],
    },
    "discover_lcx_fdic": {
        "label": "Harvest: US banks to pitch (FDIC register)",
        "group": "Discover",
        "desc": "Insured US banks of the right size, with their own websites, from the FDIC's public register. "
                "Free, no key.",
        "cmd": [PY, "tools/discover_lcx_services.py", "--source", "fdic"],
        "segments": ["lcx-services"],
    },
    "enrich_apollo_lcxs": {
        "label": "Ask Apollo for a named person (LCX Services)",
        "group": "Enrich",
        "desc": "Leads that fit well and still have nobody to write to after the site pass: one free search at the "
                "company for its audience's roles, then 1 credit for the best person's verified work address. Inside "
                "the weekly cap, never under the reserve kept for the other projects.",
        "cmd": [PY, "tools/enrich_apollo.py", "--limit", "200"],
        "segments": ["lcx-services"],
    },
    "enrich_lcx_services": {
        "label": "Lift what the harvest found (addresses, audience)",
        "group": "Enrich",
        "desc": "An address the business published becomes a contact; the audience, the services to pitch "
                "first and the place go on the lead.",
        "cmd": [PY, "tools/enrich_lcx_services.py", "--limit", "3000"],
        "segments": ["lcx-services"],
    },
    "enrich_contacts_lcxs": {
        "label": "Find contacts on sites (a week's harvest)",
        "group": "Enrich",
        "desc": "The polite site pass, sized for LCX Services' weekly harvest: up to 1,000 websites, best-scoring "
                "first (corporates before cafes), robots.txt honoured, never LinkedIn. It runs before any Apollo "
                "credit, so nothing is paid for a company that publishes an address.",
        "cmd": [PY, "tools/enrich_sitescrape.py", "--limit", "1000", "--workers", "8"],
        "segments": ["lcx-services"],
    },
    "promote_chain": {
        "label": "Promote + score + gates",
        "group": "Process",
        "desc": "Staging into the pool: self-exclusion, promote, merge "
                "duplicates, judge inputs (LCX Services), zero-unverified, score, apply gates, auto-shortlist.",
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
    "pull_replies": {
        "label": "Fetch replies",
        "group": "Outreach",
        "desc": "Replies and bounces to sent emails, read from each thread's mailbox: a reply pauses "
                "the follow-ups, a bounce marks the address. Reads Gmail, never sends. Hourly, by itself.",
        "cmd": [PY, "tools/outreach.py", "pull"],
        "hidden": True,
    },
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
        "desc": "Sends each approved email at its own time in its sending window (10:00-10:30 on its "
                "recipient's clock, or the sender's where the project says so), inside each address's daily "
                "limit.",
        "cmd": [PY, "tools/outreach.py", "send"],
        "hidden": True,
    },
}

_LOCK = threading.Lock()
_STATE = {}     # key -> {status, started, finished, rc, log}
_CURRENT = {"key": None, "proc": None}

# THE SEND'S OWN LANE (owner, 2026-10-12: each email "between 10 to 10:30AM", at its own minute). An
# email timed for 10:13 in Mumbai is due at 04:43 UTC -- inside the Friday weekly refresh, which holds the
# single slot above for two or three hours from 02:00 UTC. Waiting for the slot would send India's whole
# window late, so a send runs beside the slot, never in it: one per project at a time (_SEND_LOCKS), at
# most SEND_WORKERS at once across projects (memory: each is a Python process). It needs no slot to be
# safe -- two senders can never send one email twice: the claim in tools/outreach.py cmd_send is atomic,
# counted under an advisory lock per address, and sql/34 refuses a claim outside the email's window.
_SEND_LOCKS = {}
_SEND_GUARD = threading.Lock()
_SEND_WORKERS = max(1, int(os.environ.get("SEND_WORKERS") or 2))
_SEND_SEM = threading.BoundedSemaphore(_SEND_WORKERS)
_SEND_ACTIVE = [0]              # workers held right now (run_send)


def _send_lock(segment):
    with _SEND_GUARD:
        return _SEND_LOCKS.setdefault(segment, threading.Lock())


def send_busy(segment):
    """Is a send for this project running now (its lane)?"""
    return _send_lock(segment).locked()


def send_workers_free():
    """How many send workers (SEND_WORKERS, default 2) are free right now. The send loop asks before it
    starts projects' runs, and gives a free one to the project that has waited longest (app/scheduler.py)."""
    with _SEND_GUARD:
        return max(0, _SEND_WORKERS - _SEND_ACTIVE[0])


def run_send(segment, env=None, stay=0, max_seconds=None, on_start=None, wait=0, busy=None):
    """Run `outreach.py send` for one project in the send lane, to completion. -> (rc, logpath), or
    (None, None) when a send for this project is already running or every send worker is busy -- the
    next pass of the send loop (or the next tick) tries again. stay: seconds the run keeps going for the
    next email's moment (tools/outreach.py --stay; the send loop passes 55, a tick 0). max_seconds: how long
    a staying run may hold its worker (--max-seconds); the send loop keeps it short, so one busy project
    cannot keep the others' due emails waiting past their window (review, 2026-10-12). on_start(): called
    once the project's lane and a worker are both held, just before the run -- the caller records the run
    then, and never records one that did not start.
    The project's own lock is taken first, never waited for: a project never has two runs, and the one
    running sends what is due. A worker second: one project never holds more than one of the SEND_WORKERS.
    wait: seconds to wait for a free worker (second review, 2026-10-12). The tick passes a few minutes, as
    run_blocking waited for the slot: a project with no sending window is sent only by the tick, and giving up
    at once while timed projects held both workers left its approved email for the next tick, 15 minutes on.
    The send loop passes 0: it looks again in seconds. busy: a dict that, when nothing ran, gets
    busy["why"] = "project" (a send for it is already running) or "workers" (none came free in time)."""
    lock = _send_lock(segment)
    if not lock.acquire(blocking=False):
        if busy is not None:
            busy["why"] = "project"
        return None, None
    try:
        if not (_SEND_SEM.acquire(timeout=wait) if wait and wait > 0 else _SEND_SEM.acquire(blocking=False)):
            if busy is not None:
                busy["why"] = "workers"
            return None, None
        with _SEND_GUARD:
            _SEND_ACTIVE[0] += 1
        try:
            LOGDIR.mkdir(parents=True, exist_ok=True)
            slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in str(segment).lower())
            logpath = LOGDIR / ("send_outreach-%s-%d.log" % (slug, int(time.time() * 1000)))
            with _LOCK:
                # Operations shows the latest send's log under the job's own key
                _STATE["send_outreach"] = {"status": "running", "started": time.time(),
                                           "finished": None, "rc": None, "log": str(logpath)}
            if on_start:
                on_start()
            extra = ["--stay", str(int(stay or 0))]
            if max_seconds:
                extra += ["--max-seconds", str(int(max_seconds))]
            rc = _execute("send_outreach", JOBS["send_outreach"], logpath, dict(env or {}, SEGMENT_SLUG=segment),
                          track=False, extra_args=extra)
            return rc, str(logpath)
        finally:
            with _SEND_GUARD:
                _SEND_ACTIVE[0] -= 1
            _SEND_SEM.release()
    finally:
        lock.release()


def _execute(key, job, logpath, env_extra=None, track=True, extra_args=None):
    """Run one job's subprocess to completion. Returns its exit code.
    Assumes the caller already holds the slot (claimed _CURRENT['key']=key) -- or, with track=False, runs
    in the send lane (run_send), which leaves the slot and its stop button alone.
    env_extra carries SEGMENT_SLUG, so the same tool serves every segment."""
    with _LOCK:
        state = _STATE.get(key)
    with io_open(logpath, "w") as logf:
        try:
            logf.write("[ops] %s  segment=%s\n" % (key, (env_extra or {}).get("SEGMENT_SLUG", "default")))
            logf.flush()
            proc = subprocess.Popen(
                list(job["cmd"]) + list(extra_args or []), cwd=str(REPO), stdout=logf, stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(env_extra or {})})
            if track:
                _CURRENT["proc"] = proc
            rc = proc.wait()
        except Exception as e:
            logf.write("\nrunner error: %r\n" % (e,))
            rc = -1
    with _LOCK:
        if state is not None:
            state.update(status="done" if rc == 0 else "failed", finished=time.time(), rc=rc)
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
