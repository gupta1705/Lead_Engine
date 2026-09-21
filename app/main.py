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
import re
import time
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pgpool
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# SEGMENT 3 (2026-09-09): one deployment, many segments. SEGMENT_SLUG is now
# the DEFAULT segment; a request picks another with the tvf_segment cookie
# (set by POST /api/segment/select from the Projects menu). SEGMENTS_ALLOWED
# (comma list) pins a deployment to a subset -- that is how a portal for one
# segment is made: the same image, one env var.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
SEGMENTS_ALLOWED = [s.strip() for s in os.environ.get("SEGMENTS_ALLOWED", "").split(",") if s.strip()]
SEGMENT_COOKIE = "tvf_segment"
_SEG_CACHE = {"at": 0.0, "rows": []}


def current_segment(request: Request) -> str:
    """FastAPI dependency: the segment this request works on."""
    return getattr(request.state, "segment", None) or SEGMENT
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# no API console: every action has one place, on the page, with what it acts on in view
app = FastAPI(title="TVF Lead Engine", docs_url=None, redoc_url=None, openapi_url=None)

# ---------------------------------------------------------------- auth wall
# Everything except the login surface requires a session. The login page is
# fully self-contained (inline CSS) precisely so nothing else needs to be on
# the public side of this wall.
AUTH_EXEMPT = ("/login", "/api/auth/state", "/api/auth/login", "/api/auth/setup",
               "/api/health")


SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                    "Referrer-Policy": "same-origin"}


@app.middleware("http")
async def auth_wall(request, call_next):
    from starlette.responses import JSONResponse, RedirectResponse
    import auth as _auth
    # The path the router serves, NOT request.url.path: Starlette rebuilds request.url from the Host
    # header, so "Host: x/api/health#" made /api/leads look like the public /api/health and walked
    # past this wall (found 2026-09-21; Render's edge refuses such a Host, the code no longer relies on it).
    path = request.scope.get("path") or "/"
    # A write from another site is refused outright. SameSite=Lax already keeps the cookie off it in
    # every current browser; this does not depend on that, or on onrender.com being a public suffix.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        site = request.headers.get("sec-fetch-site")
        if site and site not in ("same-origin", "none"):
            return JSONResponse({"detail": "a request from another site is refused"}, status_code=403)
    request.state.user = None
    request.state.segment = _segment_for(request)
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
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
    if path.startswith("/api/"):
        return JSONResponse({"detail": "not signed in"}, status_code=401)
    return RedirectResponse("/login", status_code=302)


def _id(value, what="lead"):
    """A row id from the URL, or 404: a malformed one used to reach Postgres and come back a 500."""
    import uuid as _uuid
    try:
        return str(_uuid.UUID(str(value)))
    except ValueError:
        raise HTTPException(404, "no such %s" % what)

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


# ------------------------------------------------------------------ segments
UI_DEFAULTS = {
    "project_name": None, "key_prefix": "TVF",
    "board_title": "Lead board", "list_title": "Leads", "entity_label": "company",
    "card_fields": [], "details": [],
}


def segment_rows(force=False):
    """Active segments, cached for five minutes; filtered by SEGMENTS_ALLOWED."""
    if force or time.monotonic() - _SEG_CACHE["at"] > 300 or not _SEG_CACHE["rows"]:
        try:
            with cursor() as cur:
                cur.execute("select slug, name, entity_type, config->'ui' as ui,"
                            " config->>'score_threshold_review' as review,"
                            " config->>'score_threshold_priority' as priority,"
                                                       " config->'outreach'->'follow_ups' as follow_ups,"
                            " config->'outreach'->'batch_approval' as batch_approval,"
                            " coalesce((config->'auto_shortlist'->>'enabled')::boolean, false) as auto_shortlist,"
                            " config->'auto_shortlist'->>'min_score' as auto_min"
                            " from segments where is_active order by slug")
                rows = [dict(r) for r in cur.fetchall()]
            if SEGMENTS_ALLOWED:
                rows = [r for r in rows if r["slug"] in SEGMENTS_ALLOWED]
            _SEG_CACHE.update(at=time.monotonic(), rows=rows)
        except Exception:
            if not _SEG_CACHE["rows"]:
                _SEG_CACHE["rows"] = [{"slug": SEGMENT, "name": SEGMENT, "entity_type": "",
                                       "ui": None, "review": "25", "priority": "45",
                                       "follow_ups": None, "batch_approval": None, "auto_shortlist": False}]
    return _SEG_CACHE["rows"]


def _segment_for(request):
    want = request.cookies.get(SEGMENT_COOKIE)
    slugs = [r["slug"] for r in segment_rows()]
    if want and want in slugs:
        return want
    if SEGMENT in slugs or not slugs:
        return SEGMENT
    return slugs[0]


def ui_for(row):
    ui = dict(UI_DEFAULTS)
    ui.update({k: v for k, v in (row.get("ui") or {}).items() if v is not None})
    if not ui["project_name"]:
        # "US Production Houses -- Co-Pro & Format" / "... \u2014 ..." -> the first clause
        ui["project_name"] = re.split(r"\s+(?:--|\u2014|\u2013)\s+|\s\(", row["name"])[0].strip()
    return ui


def segment_info(slug):
    row = next((r for r in segment_rows() if r["slug"] == slug), None)
    if not row:
        raise HTTPException(404, "no such segment")
    return {"slug": row["slug"], "name": row["name"], "entity_type": row["entity_type"],
            "ui": ui_for(row),
            "thresholds": {"review": float(row["review"] or 25), "priority": float(row["priority"] or 45)},
            "auto_shortlist": bool(row.get("auto_shortlist")),
            # where the automatic line sits: below the review line (LCX, 20 < 25) the To review column
            # holds only what the line left behind; above it (production houses, 30 > 25) there is a
            # band between the two that a person still reviews
            "auto_shortlist_min": float(row["auto_min"]) if row.get("auto_shortlist") and row.get("auto_min") else None,
            "outreach_policy": outreach_policy_info(row)}


def _policy():
    """tools/outreach_policy.py -- the follow-up and batch-approval rules the
    command line and this API share."""
    import sys
    p = os.path.join(REPO, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    import outreach_policy
    return outreach_policy


def outreach_policy_info(row):
    fu = row.get("follow_ups") or {}
    return {
        "follow_ups": ({"enabled": True,
                        "steps": [{"step": s.get("step"), "after_days": s.get("after_days")}
                                  for s in (fu.get("steps") or [])]} if fu.get("enabled") else None),
        "batch_approval": _policy().batch_policy({"batch_approval": row.get("batch_approval")}),
    }


def segments_list(current):
    out = []
    for r in segment_rows():
        ui = ui_for(r)
        out.append({"slug": r["slug"], "name": r["name"], "entity_type": r["entity_type"],
                    "project_name": ui["project_name"], "key_prefix": ui["key_prefix"],
                    "current": r["slug"] == current})
    return {"current": current, "segments": out}


@app.get("/api/segment")
def api_segment(segment: str = Depends(current_segment)):
    return segment_info(segment)


@app.get("/api/segments")
def api_segments(segment: str = Depends(current_segment)):
    return segments_list(segment)


@app.post("/api/segment/select")
def api_segment_select(request: Request, body: dict = Body(...)):
    slug = ((body or {}).get("slug") or "").strip()
    if slug not in [r["slug"] for r in segment_rows(force=True)]:
        raise HTTPException(404, "no such segment on this deployment")
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"ok": True, "segment": slug})
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(SEGMENT_COOKIE, slug, max_age=365 * 86400, path="/", httponly=True,
                    samesite="lax", secure=secure)
    return resp


# --------------------------------------------------------------------- stats
@app.get("/api/stats")
def stats(segment: str = Depends(current_segment)):
    """The status counts and the project's sources, in one round trip."""
    with cursor() as cur:
        cur.execute(
            "with e as (select * from entities where segment_id ="
            " (select id from segments where slug = %s))"
            " select (select count(*) from e where status = 'shortlisted') as shortlisted,"
            " (select count(*) from e where status = 'rejected') as rejected,"
            " (select count(*) from e where status = 'contacted') as contacted,"
            " (select count(*) from e where status = 'in_conversation') as in_conversation,"
            " (select count(*) from e where status = 'archived') as archived,"
            " (select count(*) from e where status in " + OPEN_STATUSES + ") as open_pool",
            (segment,))
        s = dict(cur.fetchone())

        # the sources this project has: the Leads source filter and whether it is worth showing
        cur.execute(
            "select source, count(*) as n from entities where segment_id ="
            " (select id from segments where slug = %s) group by source order by n desc", (segment,))
        s["by_source"] = [dict(r) for r in cur.fetchall()]

    return s


# ---------------------------------------------------------------------- list
# An address a draft could actually use: the same test the drafting step makes
# (contact_rank, sql/28), so "Has an address" here and "can be written to"
# there are the same sentence.
HAS_ADDRESS = ("exists (select 1 from contacts c where c.entity_id = e.id"
               " and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)")


@app.get("/api/leads")
def leads(q: str = "", source: str = "", status: str = "open", contact: str = "",
          min_score: float = 0, limit: int = 100, offset: int = 0,
          segment: str = Depends(current_segment)):
    where = ["e.segment_id = (select id from segments where slug = %s)"]
    params = [segment]
    limit, offset = max(0, min(limit, 500)), max(0, offset)      # a negative one was a 500

    if status == "open":
        where.append("e.status in " + OPEN_STATUSES)
    elif status and status != "all":
        where.append("e.status = %s")
        params.append(status)

    if q:
        # the card may be titled by the host, so the host is searchable too
        where.append("(e.name ilike %s or e.domain ilike %s or e.metadata->'host'->>'name' ilike %s)")
        params += ["%" + q + "%"] * 3
    if source:
        where.append("e.source = %s")
        params.append(source)
    if min_score:
        where.append("coalesce(e.fit_score,0) >= %s")
        params.append(min_score)
    order = "e.fit_score desc nulls last, e.name"
    # The contact filter is kept out of `clause` so the counts below can say how
    # the CURRENT selection splits -- which is what decides whether the filter is
    # worth showing at all.
    clause = " and ".join(where)
    rows_clause = clause
    if contact == "yes":
        rows_clause += " and " + HAS_ADDRESS
    elif contact == "no":
        rows_clause += " and not " + HAS_ADDRESS

    # Segment 3: the UI's card_fields are metadata paths the segment config
    # names; select them as columns so cards never need the whole metadata.
    import re as _re
    fields = []
    for f in (segment_info(segment)["ui"].get("card_fields") or []):
        path = str(f.get("path", ""))
        if _re.fullmatch(r"metadata(\.[A-Za-z0-9_]+)+", path):
            fields.append("{" + ",".join(path.split(".")[1:]) + "}")
    extra = "".join(" e.metadata #>> '%s' as f%d," % (p, i) for i, p in enumerate(fields))

    with cursor() as cur:
        cur.execute(
            "select e.id, e.name, e.domain, e.source, e.status,"
            " round(coalesce(e.fit_score,0)::numeric,1) as fit_score,"
            " e.metadata->>'why_fit' as why_fit, e.metadata->>'kind' as kind,"
            " case when e.metadata->'host'->>'confidence' in ('high','medium')"
            "      then e.metadata->'host'->>'name' end as host_name," + extra +
            " e.metadata->>'hq_city' as city, e.metadata->>'hq_state' as state,"
            # the address a draft would use, by the same ranking (sql/28)
            " (select c.email from contacts c where c.entity_id = e.id"
            "   and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500"
            "   order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,"
            "   c.created_at, c.id limit 1) as email,"
            " (select c.full_name from contacts c where c.entity_id = e.id"
            "   and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500"
            "   order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,"
            "   c.created_at, c.id limit 1) as contact_name"
            " from entities e where " + rows_clause +
            " order by " + order + " limit %s offset %s",
            params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["fields"] = [r.pop("f%d" % i) for i in range(len(fields))]
        cur.execute("select count(*) filter (where " + HAS_ADDRESS + ") as with_address,"
                    " count(*) filter (where not " + HAS_ADDRESS + ") as without_address"
                    " from entities e where " + clause, params)
        split = cur.fetchone()
        total = (split["with_address"] if contact == "yes" else
                 split["without_address"] if contact == "no" else
                 split["with_address"] + split["without_address"])
    return {"total": total, "rows": rows,
            "with_address": split["with_address"], "without_address": split["without_address"]}


# -------------------------------------------------------------------- detail
@app.get("/api/leads/{lead_id}")
def lead(lead_id: str):
    lead_id = _id(lead_id)
    with cursor() as cur:
        cur.execute(
            "select e.*, s.slug as segment_slug, s.config as segment_config"
            " from entities e join segments s on s.id = e.segment_id"
            " where e.id = %s", (lead_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        # every address, best first: the order the draft step uses (contact_rank, sql/28)
        cur.execute(
            "select c.id, c.full_name, c.role_title, c.email, c.email_status, c.is_primary, c.source, c.notes,"
            " c.linkedin_url,"
            " contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) as rank"
            " from contacts c join entities e on e.id = c.entity_id"
            " where c.entity_id = %s order by rank desc, c.created_at, c.id", (lead_id,))
        contacts, seen = [], set()
        for c in cur.fetchall():
            c = dict(c)
            key = (c.get("email") or "").lower() or str(c["id"])
            if key in seen:
                continue                          # the same address from two sources is one route
            seen.add(key)
            c["id"] = str(c["id"])
            contacts.append(c)
        cur.execute(
            "select id, status, subject, template_key from outreach"
            " where entity_id = %s and direction = 'outbound' and coalesce(sequence_step, 0) = 0"
            " and status not in ('cancelled', 'failed') order by created_at desc limit 1", (lead_id,))
        draft = cur.fetchone()

    # What the score is made of, what nobody has checked yet, the analysis a
    # reviewer used to be left to do by ticking boxes, and every route in.
    # app/explain.py; the owner's review of 2026-09-17 asked for all four.
    import explain
    cfg = row.pop("segment_config") or {}
    slug = row.pop("segment_slug")
    ranked = explain.rank_contacts(contacts, row.get("domain"))
    row["contacts"] = ranked
    outreach = dict(draft, id=str(draft["id"])) if draft else None
    row["outreach"] = outreach
    row["explain"] = explain.explain_lead(slug, cfg, row, ranked, outreach)
    row["criteria"] = [dict(c, assessed=c["state"] != explain.UNCHECKED) for c in row["explain"]["criteria"]]
    meta = row.get("metadata") or {}
    h = meta.get("host") or {}
    row["host_name"] = h.get("name") if h.get("confidence") in ("high", "medium") else None
    row["thresholds"] = {"review": cfg.get("score_threshold_review"), "priority": cfg.get("score_threshold_priority")}
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
    lead_id = _id(lead_id)
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
            " where id = %s returning id, name, status, status_reason,"
            " (select s.slug from segments s where s.id = entities.segment_id) as segment,"
            " (select jsonb_array_length(coalesce(s.config->'outreach'->'templates', '[]'::jsonb)) > 0"
            "  from segments s where s.id = entities.segment_id) as writes_email",
            (mapping[decision], reason, lead_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        row["id"] = str(row["id"])
        row["withdrawn"] = 0
        if row["status"] != "shortlisted":
            # a lead taken off the shortlist takes its waiting email with it: nothing goes out to a
            # company a person has just rejected or sent back to review
            why = ("lead %s: %s" % (row["status"].replace("_", " "), reason or "decision undone"))[:200]
            cur.execute("update outreach set status = 'cancelled', stopped_reason = %s, updated_at = now()"
                        " where entity_id = %s and direction = 'outbound' and status in ('drafted', 'approved')",
                        (why, lead_id))
            row["withdrawn"] = cur.rowcount
            if row["status"] == "rejected":
                _policy().stop_thread(cur, lead_id, why)      # and no follow-up to a company refused
    # the simple flow (owner, 2026-09-19): shortlisting is the last thing a person does before
    # reading the email, so the email is drafted straight away, off this request (app/scheduler.py)
    row["drafting"] = bool(row["status"] == "shortlisted" and row.pop("writes_email", False))
    if row["drafting"]:
        _scheduler.kick_outreach(row["segment"], "manual")
    return row


# -------------------------------------------------------------------- export
@app.get("/api/export.xlsx")
def export(status: str = "shortlisted", min_score: float = 0, source: str = "", q: str = "",
           contact: str = "", segment: str = Depends(current_segment)):
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
    if q:
        cmd += ["--q", q]
    if contact in ("yes", "no"):
        cmd += ["--contact", contact]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO,
                       env={**os.environ, "SEGMENT_SLUG": segment})
    if not os.path.exists(tmp):
        raise HTTPException(500, "export failed: " + ((r.stderr or r.stdout)[-400:]))
    return FileResponse(
        tmp, filename=segment + "_leads.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------------ outreach
@app.get("/api/outreach")
def outreach_list(folder: str = "drafts", segment: str = Depends(current_segment)):
    """One folder of the outreach_folders view, newest first, for this segment. Replies holds
    every reply, marked or not (the mark is on the row); 'untriaged' counts the ones nobody has
    marked yet, which is what the sidebar count shows."""
    folders = ["inbox", "positive", "negative"] if folder == "inbox" else [folder]
    with cursor() as cur:
        cur.execute(
            "select f.* from outreach_folders f join entities e on e.id = f.entity_id"
            " where f.folder = any(%s) and e.segment_id = (select id from segments where slug = %s)"
            " order by coalesce(f.sent_at, f.created_at) desc limit 200", (folders, segment))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["id"] = str(r["id"]); r["entity_id"] = str(r["entity_id"])
        cur.execute("select f.folder, count(*) as n from outreach_folders f"
                    " join entities e on e.id = f.entity_id"
                    " where e.segment_id = (select id from segments where slug = %s) group by f.folder",
                    (segment,))
        counts = {r["folder"]: r["n"] for r in cur.fetchall()}
    counts["untriaged"] = counts.get("inbox", 0)
    counts["inbox"] = counts["untriaged"] + counts.pop("positive", 0) + counts.pop("negative", 0)
    return {"rows": rows, "counts": counts}


@app.patch("/api/outreach/{oid}")
def outreach_edit(oid: str, body: dict = Body(...)):
    """Edit a draft's subject/body. Approval means a human read THIS text, so
    editing is only legal while the row is still a draft."""
    oid = _id(oid, "draft")
    subject = (body or {}).get("subject")
    text = (body or {}).get("body")
    if subject is not None and ("\n" in str(subject) or "\r" in str(subject)):
        # one line, always: the sender refuses a subject with a line break in it
        raise HTTPException(400, "the subject must be one line")
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
def outreach_decide(oid: str, request: Request, body: dict = Body(...),
                    segment: str = Depends(current_segment)):
    """approve: a human read the draft and stands behind it (checked first, and
    recorded against their name). cancel: withdraw; cancelling a follow-up
    also stops the thread. stop_sequence: no further follow-ups for this
    company. mark_positive / mark_negative: the human verdict on a reply; on
    positive the company moves to in_conversation. Both verdicts stop the
    thread."""
    oid = _id(oid, "message")
    pol = _policy()
    action = (body or {}).get("action")
    user = getattr(request.state, "user", None) or "unknown"
    with cursor() as cur:
        cur.execute("select entity_id, direction, sequence_step from outreach where id=%s", (oid,))
        msg = cur.fetchone()
        if not msg:
            raise HTTPException(404, "no such message")
        eid = msg["entity_id"]
        if action == "approve":
            ok, skipped = pol.check_drafts(cur, [oid], segment)
            if skipped:
                raise HTTPException(409, "cannot approve: " + skipped[0]["reason"])
            cur.execute("update outreach set status='approved', approved_at=now(), approved_by=%s,"
                        " approval_mode='single', spot_checked=true, updated_at=now()"
                        " where id=%s and status='drafted' returning id", (user, oid))
        elif action == "cancel":
            cur.execute("update outreach set status='cancelled', updated_at=now()"
                        " where id=%s and status in ('drafted','approved')"
                        " returning id", (oid,))
            if not cur.fetchone():
                raise HTTPException(409, "row is not in a state that allows cancel")
            if (msg["sequence_step"] or 0) > 0:
                pol.stop_thread(cur, eid, "stopped: follow-up cancelled by %s" % user)
            return {"ok": True}
        elif action == "stop_sequence":
            n = pol.stop_thread(cur, eid, "stopped by %s" % user)
            return {"ok": True, "cancelled": n}
        elif action in ("mark_positive", "mark_negative"):
            label = "positive" if action == "mark_positive" else "negative"
            cur.execute("update outreach set triage=%s, status='triaged',"
                        " updated_at=now() where id=%s and direction='inbound'"
                        " returning entity_id", (label, oid))
            row = cur.fetchone()
            if not row:
                raise HTTPException(409, "not an inbound reply")
            pol.stop_thread(cur, eid, "reply: %s" % label)
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
    # approved: it is sent now, not when someone next opens a terminal (app/scheduler.py)
    _scheduler.kick_outreach(segment, "manual")
    return {"ok": True, "can_send": _can_send(segment), "paused": _send_paused(segment)}


@app.post("/api/outreach/batch/sample")
def outreach_batch_sample(request: Request, body: dict = Body(...),
                          segment: str = Depends(current_segment)):
    """Step 1 of batch approval: check the selected drafts, draw a random
    spot-check sample on the server, and sign batch + sample together."""
    import auth as _a
    pol = _policy()
    ids = sorted({str(i) for i in ((body or {}).get("ids") or [])})
    with cursor() as cur:
        policy = pol.batch_policy(pol.outreach_config(cur, segment))
        if not policy:
            raise HTTPException(403, "batch approval is off for this segment")
        if not ids:
            raise HTTPException(400, "select at least one draft")
        if len(ids) > policy["max_batch"]:
            raise HTTPException(400, "a batch is at most %d drafts" % policy["max_batch"])
        ok, skipped = pol.check_drafts(cur, ids, segment, policy)
        has_generated = bool(pol.generated_among(cur, ok))
    if not ok:
        raise HTTPException(400, "none of the selected drafts can be approved: "
                            + "; ".join(sorted({s["reason"] for s in skipped})))
    sample, token = pol.draw_sample(ok, policy, _a._secret(),
                                    getattr(request.state, "user", None), segment,
                                    has_generated)
    return {"approvable": sorted(ok), "skipped": skipped, "sample": sample,
            "token": token, "generated": has_generated}


@app.post("/api/outreach/batch/approve")
def outreach_batch_approve(request: Request, body: dict = Body(...),
                           segment: str = Depends(current_segment)):
    """Step 2: approve the batch the sample was drawn for. The signature proves
    the sample came from the server for exactly this batch and this person;
    every draft is re-checked, because anything may have changed since."""
    import auth as _a
    pol = _policy()
    b = body or {}
    ids = sorted({str(i) for i in (b.get("ids") or [])})
    sample = sorted({str(i) for i in (b.get("sample") or [])})
    user = getattr(request.state, "user", None)
    if not ids or not set(sample) <= set(ids):
        raise HTTPException(400, "the sample must be drawn from the batch")
    if not pol.verify_sample(ids, sample, b.get("token"), _a._secret(), user, segment):
        raise HTTPException(409, "the spot-check does not match this batch any more; select and check again")
    with cursor() as cur:
        policy = pol.batch_policy(pol.outreach_config(cur, segment))
        if not policy:
            raise HTTPException(403, "batch approval is off for this segment")
        ok, skipped = pol.check_drafts(cur, ids, segment, policy)
        # re-checked here, not trusted from step 1: the rule is about what is
        # being approved now, and a draft may have been redrafted since
        if len(sample) < pol.required_sample(len(ids), policy,
                                             bool(pol.generated_among(cur, ok))):
            raise HTTPException(400, "the spot-check sample is too small for this batch")
        batch_id, approved = pol.apply_batch(cur, ok, sample, user, segment, len(ids), skipped)
    if approved:
        _scheduler.kick_outreach(segment, "manual")          # approved means sent: no terminal step
    return {"batch_id": batch_id, "approved": approved, "skipped": skipped, "can_send": _can_send(segment),
            "paused": _send_paused(segment)}


def _can_send(segment):
    """Is a mailbox connected for this segment on this server, and is sending not paused? The page
    words an approval by it: "sending now", "sends as soon as a mailbox is connected", or "waits:
    sending is paused" (_send_paused)."""
    try:
        with cursor() as cur:
            cfg = _policy().outreach_config(cur, segment)
        if _policy().sending_paused(cfg):
            return False
        return any(mb["enabled"] and _scheduler.mailbox_connected(mb)
                   for mb in _policy().mailbox_list(cfg, segment))
    except Exception:
        return False


def _send_paused(segment):
    """Why sending is paused for this segment (outreach.sending_paused), or None."""
    try:
        with cursor() as cur:
            return _policy().sending_paused(_policy().outreach_config(cur, segment))
    except Exception:
        return None


def _render():
    """tools/draft_render.py -- the renderer the command line and this API
    share, so a draft rebuilt here is byte-identical to one drafted there."""
    import sys
    p = os.path.join(REPO, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    import draft_render
    return draft_render


@app.get("/api/outreach/footer")
def footer_get(segment: str = Depends(current_segment)):
    """The block every email in this segment ends with, and what it resolves
    to right now."""
    dr, pol = _render(), _policy()
    with cursor() as cur:
        cfg = pol.outreach_config(cur, segment)
        cur.execute("select count(*) as n from outreach o"
                    " join entities e on e.id = o.entity_id"
                    " where e.segment_id = (select id from segments where slug = %s)"
                    "   and o.direction = 'outbound' and o.status = 'drafted'", (segment,))
        pending = cur.fetchone()["n"]
    sender = cfg.get("sender") or {}
    text = dr.footer_text(cfg)
    return {"text": text, "fields": list(dr.FOOTER_FIELDS),
            "sender": {"name": sender.get("name", "") or "",
                       "title": sender.get("title", "") or "",
                       "postal_address": sender.get("postal_address", "") or ""},
            "problems": dr.validate_footer(text, sender),
            "drafts_pending": pending}


@app.post("/api/outreach/footer")
def footer_set(body: dict = Body(...), segment: str = Depends(current_segment)):
    """Save the footer and the sender it names.

    It is refused unless what comes out carries a postal address and a way off
    the list. That is the whole reason this is one setting instead of four
    lines copied into every template: the part that has to be right on EVERY
    email should be impossible to get wrong on one of them.

    Drafts waiting for approval get the new footer too: they cannot be approved
    with a footer that still says SET_ME. Only the footer is swapped, and a draft
    somebody edited at the end by hand is left exactly as they left it --
    rebuilding it would throw their words away."""
    dr, pol = _render(), _policy()
    b = body or {}
    text = (b.get("text") or "").strip()
    given = b.get("sender") or {}
    with cursor() as cur:
        old = pol.outreach_config(cur, segment)
        sender = dict(old.get("sender") or {})
        for k in ("name", "title", "postal_address"):
            if k in given:
                sender[k] = (given.get(k) or "").strip()
        problems = dr.validate_footer(text, sender)
        if problems:
            # one problem per line: each is a separate thing to fix, and the
            # dialog lists them as such
            raise HTTPException(400, "\n".join(problems))
        footer = dict(old.get("footer") or {})
        footer["text"] = text
        cur.execute("update segments set config = jsonb_set(jsonb_set(config,"
                    " '{outreach,sender}', %s), '{outreach,footer}', %s)"
                    " where slug = %s returning 1",
                    (psycopg2.extras.Json(sender), psycopg2.extras.Json(footer), segment))
        if not cur.fetchone():
            raise HTTPException(404, "no such segment")
        out = {"ok": True, "preview": dr.resolve_footer(text, sender),
               "rebuilt": 0, "unchanged": 0, "left_alone": 0}
        out.update(_rebuild_drafts(cur, segment, old, pol.outreach_config(cur, segment), dr))
    return out


REBUILD_SQL = """
select o.id, o.template_key, o.subject, o.body, o.entity_id,
       e.name as company, e.metadata, c.full_name, c.email, c.source as contact_source,
       p.subject as opener_subject
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id
left join outreach p on p.id = o.parent_id
where e.segment_id = (select id from segments where slug = %s)
  and o.direction = 'outbound' and o.status = 'drafted'
"""


def _rebuild_drafts(cur, segment, old_cfg, new_cfg, dr):
    """Swap the footer on every draft still waiting for approval.

    ONLY the footer. Everything above it is left exactly as it stands, so a
    draft somebody rewrote by hand keeps their words and still ends with the
    right address. The swap is by suffix, not by re-rendering the whole email:
    re-rendering would also silently apply every change the engine has made to
    greetings and hooks since the draft was written, which is not what saving
    a footer asked for. A draft that does not end with the old footer is left
    untouched and reported -- we cannot tell where its footer starts, and
    guessing would eat somebody's text."""
    cur.execute(REBUILD_SQL, (segment,))
    rows = [dict(r) for r in cur.fetchall()]
    swapped = unchanged = left = 0
    for r in rows:
        meta = r["metadata"] if isinstance(r["metadata"], dict) else {}
        args = dict(contact_name=r["full_name"], contact_email=r["email"],
                    seed=r["entity_id"], opener_subject=r["opener_subject"],
                    contact_source=r["contact_source"])
        try:
            was = dr.build_context(old_cfg, r["company"], meta, **args)["footer"]
            now = dr.build_context(new_cfg, r["company"], meta, **args)["footer"]
        except (ValueError, KeyError, TypeError):
            left += 1
            continue
        body = r["body"] or ""
        if was == now:
            unchanged += 1
            continue
        if not body.endswith(was):
            left += 1
            continue
        cur.execute("update outreach set body = %s, updated_at = now()"
                    " where id = %s and status = 'drafted'",
                    (body[:-len(was)] + now, r["id"]))
        swapped += cur.rowcount
    return {"rebuilt": swapped, "unchanged": unchanged, "left_alone": left}


@app.get("/api/mailboxes")
def mailboxes_state(segment: str = Depends(current_segment)):
    """The segment's sending mailboxes: cap for today (warm-up included), sends
    today, room left, and whether this server can send from each (connected:
    its address and Gmail token are set here). Addresses are the ones recorded
    on sent email; the credentials themselves are never shown."""
    import datetime as _dt
    pol = _policy()
    with cursor() as cur:
        cfg = pol.outreach_config(cur, segment)
        try:
            boxes = pol.mailbox_list(cfg, segment)
        except ValueError as e:
            raise HTTPException(500, "config outreach.mailboxes is invalid: %s" % e)
        status = pol.mailbox_status(cur, segment, boxes, _dt.datetime.now(_dt.timezone.utc).date())
        # approved and waiting to go out: past today's room they go from tomorrow on, oldest first
        cur.execute("select count(*) as n from outreach o join entities e on e.id = o.entity_id"
                    " where e.segment_id = (select id from segments where slug = %s)"
                    "   and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null", (segment,))
        approved_waiting = cur.fetchone()["n"]
    keep = ("key", "email_env", "daily_cap", "warmup", "enabled", "cap_today", "sent_today",
            "remaining", "last_address", "warmup_day")
    out = []
    for st in status:
        row = {k: st.get(k) for k in keep}
        row["first_sent"] = st["first_sent"].isoformat() if st.get("first_sent") else None
        row["connected"] = bool(st.get("enabled")) and _scheduler.mailbox_connected(st)
        out.append(row)
    # The day's counter on the Outreach page (owner, 2026-09-21: "display that counter"). The day is the
    # database's -- UTC -- so it resets at midnight UTC, 05:30 in India; resets_at says exactly when.
    segment_cap = int(cfg.get("daily_send_cap", 20))
    now = _dt.datetime.now(_dt.timezone.utc)
    return {"segment_cap": segment_cap, "rotation": bool(cfg.get("mailboxes")),
            "mailboxes": out, "paused": pol.sending_paused(cfg),
            "sent_today": sum(int(r.get("sent_today") or 0) for r in out),
            "approved_waiting": int(approved_waiting),
            "limit_today": min(segment_cap, sum(int(r.get("cap_today") or 0) for r in out if r.get("enabled"))),
            "resets_at": _dt.datetime.combine(now.date() + _dt.timedelta(days=1), _dt.time(0),
                                              tzinfo=_dt.timezone.utc).isoformat(),
            "can_send": any(r["connected"] for r in out) and not pol.sending_paused(cfg)}


# ------------------------------------------------------------------ kpis
@app.get("/api/kpis")
def kpis(segment: str = Depends(current_segment)):
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
        cur.execute("select set_config('tvf.segment', %s, false)", (segment,))
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

import universal as _universal_module          # the Universal project's Apollo search page
app.include_router(_universal_module.build_router(cursor))

# ---------------------------------------------------------------- scheduler
import scheduler as _sched_module
_scheduler = _sched_module.Scheduler(cursor, _ops_module, SEGMENT,
                                     allowed=SEGMENTS_ALLOWED or None)


@app.on_event("startup")
def _start_scheduler():
    _scheduler.start()


@app.on_event("shutdown")
def _stop_scheduler():
    _scheduler.stop()


@app.get("/api/schedule")
def schedule_state(segment: str = Depends(current_segment)):
    """What runs by itself for this segment, and how each pipeline's last whole run went --
    how 'unattended' becomes observable in Operations. A failed run names the step it stopped
    at. Runs recorded before the segment column existed count under the default segment."""
    with cursor() as cur:
        cur.execute(
            "select distinct on (pipeline) id, pipeline, trigger, status, detail, started_at, finished_at"
            " from pipeline_runs where coalesce(segment, %s) = %s and step is null"
            " order by pipeline, started_at desc", (SEGMENT, segment))
        last = {}
        for r in [dict(x) for x in cur.fetchall()]:
            if r["status"] == "failed":
                cur.execute(
                    "select step, detail from pipeline_runs where coalesce(segment, %s) = %s and pipeline = %s"
                    " and step is not null and status = 'failed' and started_at >= %s"
                    " order by started_at desc limit 1", (SEGMENT, segment, r["pipeline"], r["started_at"]))
                f = cur.fetchone()
                if f:
                    r["failed_step"], r["failed_detail"] = f["step"], (f["detail"] or "")[-400:]
            r["id"] = str(r["id"])
            r["started_at"] = r["started_at"].isoformat() if r["started_at"] else None
            r["finished_at"] = r["finished_at"].isoformat() if r["finished_at"] else None
            last[r["pipeline"]] = r
    return {"schedule": _scheduler.schedule(segment),
            "webhook_configured": bool(_scheduler.alert_webhook()),
            "last": last}


@app.post("/api/schedule/run/{pipeline}")
def schedule_run_now(pipeline: str, segment: str = Depends(current_segment)):
    """Fire a whole pipeline by hand -- the same sequence the scheduler runs,
    recorded the same way, for testing unattended behaviour without waiting for
    the clock. Runs in a background thread so the request returns immediately."""
    import threading
    if pipeline not in _scheduler.pipelines(segment):
        raise HTTPException(404, "no such pipeline for this segment")
    if _scheduler.is_running(segment, pipeline):
        raise HTTPException(409, "A %s is already running for this project." % pipeline.replace("_", " "))
    threading.Thread(target=_scheduler.run_pipeline,
                     args=(pipeline,), kwargs={"trigger": "manual", "segment": segment},
                     daemon=True).start()
    return {"ok": True, "pipeline": pipeline, "segment": segment}



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
