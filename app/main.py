#!/usr/bin/env python3
"""main.py -- P18/P19: the review queue in a browser.

WHY THIS EXISTS. Everything the engine knows has lived in psql output and xlsx
files. That is fine for one operator who wrote the SQL and useless for a BD
team, which is the actual audience: someone who wants to see a company, read
the evidence, and say yes or no without learning the schema.

WHAT IT DELIBERATELY IS NOT. There is no build step, no npm, no framework. The
frontend is three static files served by this process. That is a deployment
decision, not a taste one: the deadline is 2026-09-03 and a container that only
has to pip install and copy files cannot fail in the ways a node toolchain can.
The review surface is a table, a detail panel and two buttons; vanilla is
genuinely the right size for it.

SECURITY POSTURE, STATED PLAINLY. This binds to localhost and has NO
authentication. That is correct for the local-Docker deployment it was built
for and stops being correct the moment the port is exposed to a network. The
cloud step adds auth BEFORE that happens -- see docs/DEPLOY.md. The database URL
is read from the environment and never rendered into a response.
"""
import io
import os
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pgpool
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

app = FastAPI(title="TVF Lead Engine", docs_url="/api/docs")

# ---------------------------------------------------------------- auth wall
# Everything except the login surface requires a session. The login page is
# fully self-contained (inline CSS) precisely so nothing else needs to be on
# the public side of this wall.
AUTH_EXEMPT = ("/login", "/api/auth/state", "/api/auth/login", "/api/auth/setup",
               "/api/health")


@app.middleware("http")
async def auth_wall(request, call_next):
    from starlette.responses import JSONResponse, RedirectResponse
    import auth as _auth
    path = request.url.path
    request.state.user = None
    token = request.cookies.get(_auth.COOKIE)
    if token:
        def lookup(email):
            with cursor() as cur:
                cur.execute("select password_hash from app_users"
                            " where lower(email) = lower(%s)", (email,))
                row = cur.fetchone()
                return row["password_hash"] if row else None
        request.state.user = _auth.parse_cookie(token, lookup)
    if path in AUTH_EXEMPT or request.state.user:
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "not signed in"}, status_code=401)
    return RedirectResponse("/login", status_code=302)

_POOL = None
_LAST_USED = {}            # id(conn) -> monotonic time of its last good use
IDLE_PROBE_AFTER = 30      # seconds idle before a connection is probed first

OPEN_STATUSES = "('discovered','enriched','scored','ready_for_review')"


def db_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if url:
        return url
    # Fall back to the repo .env so `python app/main.py` works without
    # exporting anything by hand. Never logged, never returned to a client.
    envfile = os.path.join(REPO, ".env")
    if os.path.exists(envfile):
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith("SUPABASE_DB_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("SUPABASE_DB_URL is not set")


def _pool():
    global _POOL
    if _POOL is None:
        # TCP keepalives, so a NAT or the pooler cannot silently forget an
        # idle connection: the kernel notices within about a minute and the
        # next checkout sees a closed socket instead of a hang.
        _POOL = pgpool.ThreadedConnectionPool(
            1, 8, db_url(), connect_timeout=20,
            keepalives=1, keepalives_idle=30, keepalives_interval=10,
            keepalives_count=3)
    return _POOL


def _checkout():
    """A connection known to be alive.

    Supabase's session pooler drops idle connections without telling the
    client, so the first query on a dead one fails -- and whoever asked
    first (the uptime ping, every five minutes) got a 503 while everyone
    after it got a fresh connection. Seen live on 2026-09-04, an hour after
    the Render deploy. A connection idle for a while is now probed with
    `select 1` and replaced if the probe fails; the probe costs one round
    trip and only happens after IDLE_PROBE_AFTER seconds of idleness.
    """
    pool = _pool()
    for _ in range(3):
        conn = pool.getconn()
        if conn.closed:
            _LAST_USED.pop(id(conn), None)
            pool.putconn(conn, close=True)
            continue
        if time.monotonic() - _LAST_USED.get(id(conn), 0) > IDLE_PROBE_AFTER:
            try:
                with conn.cursor() as cur:
                    cur.execute("select 1")
                    cur.fetchone()
            except Exception:
                _LAST_USED.pop(id(conn), None)
                pool.putconn(conn, close=True)
                continue
        return conn
    raise RuntimeError("no live database connection after three attempts")


@contextmanager
def cursor():
    conn = _checkout()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
        _LAST_USED[id(conn)] = time.monotonic()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass    # a dead connection cannot roll back; the original error matters
        raise
    finally:
        _POOL.putconn(conn, close=bool(conn.closed))


# --------------------------------------------------------------------- stats
@app.get("/api/stats")
def stats():
    """Everything the dashboard needs, in one round trip."""
    with cursor() as cur:
        cur.execute(
            "with e as (select * from entities where segment_id ="
            " (select id from segments where slug = %s))"
            " select (select count(*) from e) as total,"
            " (select count(*) from e where domain is not null) as with_domain,"
            " (select count(*) from e where exists (select 1 from contacts c"
            "    where c.entity_id = e.id)) as with_contact,"
            " (select count(*) from e where exists (select 1 from contacts c"
            "    where c.entity_id = e.id and c.full_name is not null)) as named_contact,"
            " (select count(*) from e where status = 'shortlisted') as shortlisted,"
            " (select count(*) from e where status = 'rejected') as rejected,"
            " (select count(*) from e where status in " + OPEN_STATUSES + ") as open_pool",
            (SEGMENT,))
        s = dict(cur.fetchone())

        cur.execute(
            "select source, count(*) as n,"
            " count(*) filter (where domain is not null) as with_domain,"
            " count(*) filter (where exists (select 1 from contacts c"
            "   where c.entity_id = entities.id)) as with_contact,"
            " round(avg(fit_score)::numeric,1) as avg_score,"
            " count(*) filter (where fit_score >= 25) as reviewable"
            " from entities where segment_id ="
            " (select id from segments where slug = %s)"
            " group by source order by reviewable desc, n desc", (SEGMENT,))
        s["by_source"] = [dict(r) for r in cur.fetchall()]

        cur.execute(
            "select case when fit_score is null or fit_score = 0 then '0'"
            "            when fit_score < 10 then '1-9'"
            "            when fit_score < 25 then '10-24'"
            "            when fit_score < 40 then '25-39'"
            "            when fit_score < 60 then '40-59'"
            "            else '60+' end as band, count(*) as n"
            " from entities where segment_id ="
            " (select id from segments where slug = %s)"
            " and status in " + OPEN_STATUSES + " group by 1", (SEGMENT,))
        got = {r["band"]: r["n"] for r in cur.fetchall()}
        s["histogram"] = [{"band": b, "n": got.get(b, 0)}
                          for b in ("0", "1-9", "10-24", "25-39", "40-59", "60+")]

        # Evidence coverage: which criteria the engine can actually SEE. This is
        # the most diagnostic number in the product -- a criterion nobody scores
        # is points nobody can earn, and that is invisible in a score alone.
        cur.execute(
            "select"
            " count(*) filter (where (metadata->'scoring_inputs'->>'international_ip_experience')::numeric > 0) as international_ip_experience,"
            " count(*) filter (where (metadata->'scoring_inputs'->>'genre_fit')::numeric > 0) as genre_fit,"
            " count(*) filter (where (metadata->'scoring_inputs'->>'distribution_relationship')::numeric > 0) as distribution_relationship,"
            " count(*) filter (where (metadata->'scoring_inputs'->>'right_size')::numeric > 0) as right_size,"
            " count(*) filter (where (metadata->'scoring_inputs'->>'reachable_decision_maker')::numeric > 0) as reachable_decision_maker,"
            " count(*) filter (where (metadata->'scoring_inputs'->>'collaboration_openness')::numeric > 0) as collaboration_openness"
            " from entities where segment_id ="
            " (select id from segments where slug = %s)"
            " and status in " + OPEN_STATUSES, (SEGMENT,))
        s["coverage"] = dict(cur.fetchone())

        cur.execute("select config->'rubric' as rubric from segments where slug = %s",
                    (SEGMENT,))
        s["rubric"] = cur.fetchone()["rubric"]
    return s


# ---------------------------------------------------------------------- list
@app.get("/api/leads")
def leads(q: str = "", source: str = "", status: str = "open",
          min_score: float = 0, has_contact: int = 0,
          sort: str = "score", limit: int = 100, offset: int = 0):
    where = ["e.segment_id = (select id from segments where slug = %s)"]
    params = [SEGMENT]

    if status == "open":
        where.append("e.status in " + OPEN_STATUSES)
    elif status and status != "all":
        where.append("e.status = %s")
        params.append(status)

    if q:
        where.append("(e.name ilike %s or e.domain ilike %s)")
        params += ["%" + q + "%", "%" + q + "%"]
    if source:
        where.append("e.source = %s")
        params.append(source)
    if min_score:
        where.append("coalesce(e.fit_score,0) >= %s")
        params.append(min_score)
    if has_contact:
        where.append("exists (select 1 from contacts c where c.entity_id = e.id)")

    order = {"score": "e.fit_score desc nulls last, e.name",
             "name": "e.name",
             "recent": "e.created_at desc"}.get(sort, "e.fit_score desc nulls last")
    clause = " and ".join(where)

    with cursor() as cur:
        cur.execute(
            "select e.id, e.name, e.domain, e.source, e.status,"
            " round(coalesce(e.fit_score,0)::numeric,1) as fit_score,"
            " e.metadata->>'why_fit' as why_fit,"
            " e.metadata->>'hq_city' as city, e.metadata->>'hq_state' as state,"
            " (select count(*) from contacts c where c.entity_id = e.id) as n_contacts,"
            " (select c.email from contacts c where c.entity_id = e.id"
            "   order by c.is_primary desc nulls last limit 1) as email,"
            " (select c.full_name from contacts c where c.entity_id = e.id"
            "   order by c.is_primary desc nulls last limit 1) as contact_name"
            " from entities e where " + clause +
            " order by " + order + " limit %s offset %s",
            params + [min(limit, 500), offset])
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("select count(*) as n from entities e where " + clause, params)
        total = cur.fetchone()["n"]
    return {"total": total, "rows": rows}


# -------------------------------------------------------------------- detail
@app.get("/api/leads/{lead_id}")
def lead(lead_id: str):
    with cursor() as cur:
        cur.execute(
            "select e.*, s.config->'rubric' as rubric,"
            " s.config->'review_checklist' as checklist"
            " from entities e join segments s on s.id = e.segment_id"
            " where e.id = %s", (lead_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        cur.execute(
            "select full_name, role_title, email, email_status, is_primary, source"
            " from contacts where entity_id = %s"
            " order by is_primary desc nulls last", (lead_id,))
        row["contacts"] = [dict(c) for c in cur.fetchall()]

    # Explain the score criterion by criterion, INCLUDING what was never
    # assessed. A reviewer needs "nobody looked at this" to read differently
    # from "we looked and it scored zero" -- that distinction is the entire
    # design of unverified_inputs, and hiding it in the UI would waste it.
    meta = row.get("metadata") or {}
    si = meta.get("scoring_inputs") or {}
    unverified = set(meta.get("unverified_inputs") or [])
    criteria = []
    for r in (row.get("rubric") or []):
        key = r["key"]
        raw = si.get(key)
        numeric = isinstance(raw, (int, float)) and not isinstance(raw, bool)
        criteria.append({
            "key": key,
            "label": r.get("label", key),
            "points": r["points"],
            "value": raw,
            "earned": round(float(r["points"]) * float(raw), 1) if numeric else 0,
            "assessed": (key in si) and (key not in unverified),
            "guidance": r.get("guidance", ""),
        })
    row["criteria"] = criteria
    row.pop("rubric", None)
    row["id"] = str(row["id"])
    row["segment_id"] = str(row["segment_id"])
    return row


# -------------------------------------------------------------------- decide
@app.post("/api/leads/{lead_id}/decision")
def decide(lead_id: str, body: dict = Body(...)):
    """Shortlist or reject one lead. Rejections keep their reason.

    Rejected rows are never deleted -- they are the shield that stops a later
    harvest resurfacing a company someone already refused (Invariant 4).
    """
    decision = (body or {}).get("decision")
    reason = ((body or {}).get("reason") or "").strip() or None
    mapping = {"shortlist": "shortlisted", "reject": "rejected",
               "reset": "ready_for_review"}
    if decision not in mapping:
        raise HTTPException(400, "decision must be shortlist, reject or reset")
    with cursor() as cur:
        cur.execute(
            "update entities set status = %s, status_reason = %s,"
            " status_changed_at = now(), updated_at = now()"
            " where id = %s returning id, name, status, status_reason",
            (mapping[decision], reason, lead_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        row["id"] = str(row["id"])
    return row


# -------------------------------------------------------------------- export
@app.get("/api/export.xlsx")
def export(status: str = "shortlisted", min_score: float = 0, source: str = ""):
    """The owner's 17-column sheet, generated live from the current selection.

    Takes the same filters the review queue is showing, because a reviewer who
    has just narrowed the list to what they care about expects the download to
    match. Exporting only the shortlist regardless of the screen was the
    original behaviour and it produced a near-empty file whenever nothing had
    been shortlisted yet -- a bad first impression of a working pipeline.
    """
    import subprocess
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "tvf_leads_export.xlsx")
    if os.path.exists(tmp):
        os.remove(tmp)
    cmd = ["python", os.path.join(REPO, "tools", "export_leads.py"),
           "-o", tmp, "--status", status]
    if min_score:
        cmd += ["--min-score", str(min_score)]
    if source:
        cmd += ["--source", source]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
    if not os.path.exists(tmp):
        raise HTTPException(500, "export failed: " + ((r.stderr or r.stdout)[-400:]))
    return FileResponse(
        tmp, filename="TVF_leads.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------------ outreach
@app.get("/api/outreach")
def outreach_list(folder: str = "drafts"):
    """One folder of the outreach_folders view, newest first."""
    with cursor() as cur:
        cur.execute(
            "select * from outreach_folders where folder = %s"
            " order by coalesce(sent_at, created_at) desc limit 200", (folder,))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"]); r["entity_id"] = str(r["entity_id"])
        cur.execute("select folder, count(*) as n from outreach_folders group by folder")
        counts = {r["folder"]: r["n"] for r in cur.fetchall()}
    return {"rows": rows, "counts": counts}


@app.patch("/api/outreach/{oid}")
def outreach_edit(oid: str, body: dict = Body(...)):
    """Edit a draft's subject/body. Approval means a human read THIS text, so
    editing is only legal while the row is still a draft."""
    subject = (body or {}).get("subject")
    text = (body or {}).get("body")
    with cursor() as cur:
        cur.execute(
            "update outreach set subject = coalesce(%s, subject),"
            " body = coalesce(%s, body), updated_at = now()"
            " where id = %s and status = 'drafted' returning id",
            (subject, text, oid))
        if not cur.fetchone():
            raise HTTPException(409, "only drafts can be edited")
    return {"ok": True}


@app.post("/api/outreach/{oid}/decision")
def outreach_decide(oid: str, body: dict = Body(...)):
    """approve: a human read the draft and stands behind it. cancel: withdraw.
    mark_positive / mark_negative: the human verdict on a reply -- on positive
    the company moves to in_conversation, the state the whole engine exists to
    produce."""
    action = (body or {}).get("action")
    with cursor() as cur:
        if action == "approve":
            cur.execute("update outreach set status='approved', updated_at=now()"
                        " where id=%s and status='drafted' returning id", (oid,))
        elif action == "cancel":
            cur.execute("update outreach set status='cancelled', updated_at=now()"
                        " where id=%s and status in ('drafted','approved')"
                        " returning id", (oid,))
        elif action in ("mark_positive", "mark_negative"):
            label = "positive" if action == "mark_positive" else "negative"
            cur.execute("update outreach set triage=%s, status='triaged',"
                        " updated_at=now() where id=%s and direction='inbound'"
                        " returning entity_id", (label, oid))
            row = cur.fetchone()
            if not row:
                raise HTTPException(409, "not an inbound reply")
            eid = row["entity_id"]
            if label == "positive":
                # promote; report honestly if the entity was in a state the
                # promotion could not apply to (review finding: silent no-op)
                cur.execute("update entities set status='in_conversation',"
                            " status_changed_at=now() where id=%s"
                            " and status in ('contacted','shortlisted')"
                            " returning id", (eid,))
                promoted = cur.fetchone() is not None
                return {"ok": True, "entity_promoted": promoted}
            # a correction must be able to walk the promotion back -- but only
            # when no OTHER reply still stands positive for this company
            cur.execute("select 1 from outreach where entity_id=%s"
                        " and direction='inbound' and triage='positive'"
                        " and id <> %s limit 1", (eid, oid))
            if cur.fetchone() is None:
                cur.execute("update entities set status='contacted',"
                            " status_changed_at=now() where id=%s"
                            " and status='in_conversation'", (eid,))
            return {"ok": True}
        else:
            raise HTTPException(400, "unknown action")
        if not cur.fetchone():
            raise HTTPException(409, "row is not in a state that allows " + action)
    return {"ok": True}


# ------------------------------------------------------------------ kpis
@app.get("/api/kpis")
def kpis():
    """The v1 numbers (P26), from sql/kpi_queries.sql -- the same named
    queries tools/kpis.py prints, so a terminal and the dashboard never
    disagree about what 'approval rate' means."""
    import re as _re
    text = io.open(os.path.join(REPO, "sql", "kpi_queries.sql"),
                   encoding="utf-8").read()
    queries, name, buf = {}, None, []
    for line in text.splitlines():
        m = _re.match(r"--\s*name:\s*(\w+)", line)
        if m:
            if name:
                queries[name] = "\n".join(buf).strip().rstrip(";")
            name, buf = m.group(1), []
        elif name is not None and not line.startswith("--"):
            buf.append(line)
    if name:
        queries[name] = "\n".join(buf).strip().rstrip(";")
    out = {}
    with cursor() as cur:
        # the queries read the segment from a session setting, so the .sql
        # file is valid PostgreSQL that verify_repo can parse
        cur.execute("select set_config('tvf.segment', %s, false)", (SEGMENT,))
        for qname, sql in queries.items():
            cur.execute(sql)
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                for k, v in list(r.items()):
                    if hasattr(v, "isoformat"):
                        r[k] = v.isoformat()
                    elif v is not None and not isinstance(v, (int, float, str, bool)):
                        r[k] = float(v)
            out[qname] = rows if qname == "by_source" else (rows[0] if rows else {})
    return out


@app.get("/api/health")
def health():
    try:
        with cursor() as cur:
            cur.execute("select 1 as ok")
            cur.fetchone()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(503, "database unreachable: " + type(e).__name__)


# CACHE BUSTING, and why it is not optional here.
# There is no build step, so app.js and style.css keep the same URL forever.
# A browser that cached them serves the OLD UI against the NEW API after every
# deploy -- observed live on 2026-08-29, where a reloaded page ran a version of
# app.js that predated the change being tested. With a team sharing one
# deployment that reads as "the feature does not work".
#
# STATIC_V is stamped from the newest mtime under static/ and appended to the
# asset URLs in index.html as it is served, so the URL changes exactly when the
# bytes do -- and never otherwise, which keeps ordinary caching working.
def _static_version():
    newest = 0.0
    d = os.path.join(HERE, "static")
    for f in os.listdir(d):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(d, f)))
        except OSError:
            pass
    return str(int(newest))


@app.get("/")
def index():
    from fastapi.responses import HTMLResponse
    html = io.open(os.path.join(HERE, "static", "index.html"),
                   encoding="utf-8").read()
    v = _static_version()
    html = (html.replace('href="style.css"', 'href="style.css?v=%s"' % v)
                .replace('src="app.js"', 'src="app.js?v=%s"' % v))
    # no-store, not no-cache: the shell is what carries the version stamps,
    # so a stale shell defeats the whole mechanism. It is one small document.
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


import sys as _sys
_sys.path.insert(0, HERE)
import auth as _auth_module
_auth_router, _ = _auth_module.build_router(cursor)
app.include_router(_auth_router)

import ops as _ops_module
app.include_router(_ops_module.build_router())

# ---------------------------------------------------------------- scheduler
import scheduler as _sched_module
_scheduler = _sched_module.Scheduler(cursor, _ops_module, SEGMENT)


@app.on_event("startup")
def _start_scheduler():
    _scheduler.start()


@app.on_event("shutdown")
def _stop_scheduler():
    _scheduler.stop()


@app.get("/api/schedule")
def schedule_state():
    """The configured schedule plus the most recent pipeline runs -- this is
    how 'unattended' becomes observable in the Operations tab."""
    with cursor() as cur:
        cur.execute(
            "select id, pipeline, step, trigger, status, detail,"
            " started_at, finished_at from pipeline_runs"
            " order by started_at desc limit 40")
        runs = [dict(r) for r in cur.fetchall()]
        for r in runs:
            r["id"] = str(r["id"])
            r["started_at"] = r["started_at"].isoformat() if r["started_at"] else None
            r["finished_at"] = r["finished_at"].isoformat() if r["finished_at"] else None
    return {"schedule": _scheduler.schedule(),
            "pipelines": list(_sched_module.PIPELINES.keys()),
            "webhook_configured": bool(_scheduler.alert_webhook()),
            "runs": runs}


@app.post("/api/schedule/run/{pipeline}")
def schedule_run_now(pipeline: str):
    """Fire a whole pipeline by hand -- the same sequence the scheduler runs,
    recorded the same way, for testing unattended behaviour without waiting for
    the clock. Runs in a background thread so the request returns immediately."""
    import threading
    if pipeline not in _sched_module.PIPELINES:
        raise HTTPException(404, "no such pipeline")
    threading.Thread(target=_scheduler.run_pipeline,
                     args=(pipeline,), kwargs={"trigger": "manual"},
                     daemon=True).start()
    return {"ok": True, "pipeline": pipeline}


@app.post("/api/schedule/test-alert")
def schedule_test_alert():
    """Fire the alert webhook on demand -- 'a forced failure pings', proven
    without breaking anything."""
    _scheduler.alert("TVF Lead Engine: this is a test alert from the "
                     "Operations tab. If you can read this, alerting works.")
    return {"ok": True, "webhook_configured": bool(_scheduler.alert_webhook())}


@app.get("/login")
def login_page():
    from fastapi.responses import HTMLResponse
    html = io.open(os.path.join(HERE, "static", "login.html"),
                   encoding="utf-8").read()
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
