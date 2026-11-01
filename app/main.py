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
               "/api/health",
               "/privacy",                     # what Google's consent screen links to (static/privacy.html)
               "/api/mailboxes/server-key",   # a public key, for the owner's laptop (app/mailbox_connect.py)
               # signing an MCP client in (app/oauth.py): the discovery documents, registering, the token exchange,
               # and the page that asks the person (it checks the session itself and sends them to log in)
               "/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp",
               "/.well-known/oauth-authorization-server", "/oauth/register", "/oauth/token", "/oauth/authorize")
# The public demo (owner, 2026-11-01: "a demo login which doesnt display any data ... public access"): the app's own
# page, script and styles, its Docs without addresses or the real projects, and app/demo's pretend /api (mock.js) with
# made-up data (data.json, tools/demo_data.py). Exactly these paths, nothing under them: the demo page asks this server
# for nothing else -- no session, no data. DEMO_ENABLED=0 turns it off (404, and the login page offers no demo).
DEMO_ON = os.environ.get("DEMO_ENABLED", "1") != "0"
DEMO_FILES = {"/demo/app.js": ("static/app.js", "application/javascript"),
              "/demo/style.css": ("static/style.css", "text/css"),
              "/demo/mock.js": ("demo/mock.js", "application/javascript"),
              "/demo/data.json": ("demo/data.json", "application/json")}
DEMO_PATHS = ("/demo", "/demo/docs.html") + tuple(DEMO_FILES)
# what a person still on a starting password may call: the screen that replaces it
MUST_CHANGE_OK =("/api/auth/state", "/api/auth/password", "/api/auth/profile", "/api/auth/logout",
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
    request.state.must_change = False
    request.state.via_key = False
    request.state.segment = _segment_for(request)
    # the API and MCP server (app/api_v1.py): a person's key, on /api/v1 and /mcp only
    import api_v1 as _api
    key_user, refusal = _api.authenticate(request, path, cursor)
    if refusal is not None:
        for k, v in SECURITY_HEADERS.items():
            refusal.headers.setdefault(k, v)
        return refusal
    if key_user:
        request.state.user, request.state.via_key = key_user, True
    token = None if key_user else request.cookies.get(_auth.COOKIE)
    if token:
        found = {}

        def lookup(email):
            with cursor() as cur:
                cur.execute("select password_hash, must_change_password from app_users"
                            " where lower(email) = lower(%s)", (email,))
                row = cur.fetchone()
            if not row:
                return None
            found.update(row)
            return row["password_hash"]
        request.state.user = _auth.parse_cookie(token, lookup)
        request.state.must_change = bool(request.state.user and found.get("must_change_password"))
    # A starting password the owner handed out (the same one, to everybody: 2026-09-26) opens nothing
    # but the screen that replaces it. Enforced here, not just on the page.
    if request.state.user and request.state.must_change and path.startswith("/api/") and path not in MUST_CHANGE_OK:
        return JSONResponse({"detail": "Choose your own password first.", "must_change_password": True},
                            status_code=403)
    if path in AUTH_EXEMPT or (DEMO_ON and path in DEMO_PATHS) or request.state.user:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
    if path.startswith("/api/") or path == "/mcp":
        # a program is told how to get in, not sent to a login page
        # ... and an MCP client (claude.ai) where to sign in: resource_metadata (RFC 9728, app/oauth.py)
        return JSONResponse({"detail": "not signed in" if path.startswith("/api/") and not path.startswith("/api/v1/")
                             else "Sign in, or send a key: Authorization: Bearer tle_... (account menu, API and MCP)."},
                            status_code=401, headers={"WWW-Authenticate": _api.challenge(request)})
    if path.startswith("/.well-known/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
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
                            " coalesce((config->'outreach'->>'compose')::boolean, false) as compose,"
                            " config->'outreach'->'compose_start' as compose_start,"
                            " config->'outreach'->'send_window' as send_window,"
                            " config->'outreach'->'default_cc' as default_cc,"
                            # first-email templates only: a project whose emails people write (Universal) may
                            # still have a follow-up template, and drafts no first emails
                            " exists (select 1 from jsonb_array_elements(case when jsonb_typeof("
                            "   config->'outreach'->'templates') = 'array' then config->'outreach'->'templates'"
                            "   else '[]'::jsonb end) t where coalesce(t->>'kind', '') <> 'follow_up') as has_templates,"
                            " coalesce((config->'auto_shortlist'->>'enabled')::boolean, false) as auto_shortlist,"
                            " config->'auto_shortlist'->>'min_score' as auto_min,"
                            # LCX Services (2026-10-13): each lead pitched ONE service (config lead_service)
                            " config ? 'lead_service' as lead_service"
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


def _sw():
    """tools/send_window.py -- when an approved email goes out: its own second in 10:00-10:30, its
    recipient's clock (owner, 2026-10-12)."""
    _policy()
    import send_window
    return send_window


def _wcfg(cfg):
    """The project's sending window with its defaults, or None: no block, enabled false -- or a block that
    does not read, which the send itself refuses loudly and tools/verify_repo.py catches before a deploy.
    A page is never broken by it."""
    try:
        return _sw().window_cfg(cfg)
    except ValueError:
        return None


def outreach_policy_info(row):
    fu = row.get("follow_ups") or {}
    return {
        "follow_ups": ({"enabled": True,
                        "steps": [{"step": s.get("step"), "after_days": s.get("after_days")}
                                  for s in (fu.get("steps") or [])]} if fu.get("enabled") else None),
        "batch_approval": _policy().batch_policy({"batch_approval": row.get("batch_approval")}),
        # a person writes the email to leads they pick (tools/outreach_compose.py); with no templates
        # nothing is ever drafted, so the page leaves the Drafts folder out
        "compose": bool(row.get("compose")),
        # the email the Write email box starts from (outreach.compose_start; LCX Services: every LCX
        # service in one email), or None for a box that starts from "Hi {{first_name}},"
        "compose_start": _compose_start(row) if row.get("compose") else None,
        "drafts": bool(row.get("has_templates", True)),
        # each approved email at its own second, 10:00-10:30 on its recipient's clock (owner, 2026-10-12)
        "send_window": _window_info(row.get("send_window")),
        # who an email is copied to unless its approver switches that off (owner, 2026-10-22; sql/39)
        "default_cc": [str(a).strip().lower() for a in (row.get("default_cc") or []) if str(a).strip()],
    }


def _window_info(block):
    w = _wcfg({"send_window": block}) if block else None
    if not w:
        return None
    # sender_place: "India", for the page's sentences when timezone_of is "sender" -- every email then goes on
    # the sender's clock, and saying "its recipient's time zone" would be wrong (review, 2026-10-12)
    return dict({k: w[k] for k in ("enabled", "start", "end", "timezone_of", "weekdays_only", "sender_timezone")},
                sender_place=_sw().place_name(w["sender_timezone"]))


def _compose_start(row):
    s = row.get("compose_start")
    if not isinstance(s, dict):
        return None
    subject, body = str(s.get("subject") or "").strip(), str(s.get("body") or "").strip()
    return {"subject": subject, "body": body} if subject and body else None


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
               " and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500 and contact_allowed(c.entity_id,c.source,c.verifier,c.email_status))")

# THE LEAD SERVICE (the owner's review of the LCX Services emails, 2026-10-13, point 12). Each LCX Services lead is
# tagged with ONE service from the deck (tools/lcx_judge.py, config lead_service, stored as metadata.lead_service),
# its email pitches that one, and the email records which one it pitched (outreach.service, sql/35): a record of
# what was sold to whom. So the Leads page and the Board get one row of tabs, a service each with its count, the
# lead sheet says which service and why (and a person may pick another), and Outreach says what each email pitches.
# Only a project whose config has lead_service rules gets any of it: every other project's pages and answers are
# exactly what they were. `service` is the tag's name ("name" is the brief's word for the same value, kept beside it).
LS_SERVICE = "coalesce(e.metadata #>> '{lead_service,service}', e.metadata #>> '{lead_service,name}')"
# a lead's tab: its service; "none" for not a buyer (never drafted); "hold" for one the rules left to a person
# ("Check service"); NULL for a lead not tagged yet, which only All counts
LS_KEY = ("(case when " + LS_SERVICE + " is not null then " + LS_SERVICE +
          " when e.metadata #>> '{lead_service,basis}' = 'not_a_buyer' then 'none'"
          " when jsonb_typeof(e.metadata -> 'lead_service') = 'object' then 'hold' end)")
SERVICE_BUCKETS = ("hold", "none")          # Check service, Not a buyer: after the services, in this order


def sells_services(segment):
    """Does this project pitch one service per lead (config lead_service: LCX Services)?"""
    row = next((r for r in segment_rows() if r["slug"] == segment), None)
    return bool(row and row.get("lead_service"))


def service_counts(rows):
    """[{key, n}] from (key, n) rows: the services, most leads first, then Check service and Not a buyer. A tab
    with no lead is left out: every tab shown has something behind it (owner, 2026-09-19)."""
    got = {r["k"]: int(r["n"]) for r in rows if r["k"] is not None and int(r["n"]) > 0}
    named = sorted(((k, n) for k, n in got.items() if k not in SERVICE_BUCKETS), key=lambda kv: (-kv[1], kv[0]))
    return [{"key": k, "n": n} for k, n in named] + [{"key": k, "n": got[k]} for k in SERVICE_BUCKETS if k in got]


@app.get("/api/leads")
def leads(q: str = "", source: str = "", status: str = "open", contact: str = "",
          min_score: float = 0, limit: int = 100, offset: int = 0, service: str = "",
          segment: str = Depends(current_segment)):
    sells = sells_services(segment)
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
    if segment_info(segment)["ui"].get("prioritize_fresh_leads"):
        from lead_lifecycle import priority_order
        order = priority_order()
    # The contact filter is kept out of `clause` so the counts below can say how
    # the CURRENT selection splits -- which is what decides whether the filter is
    # worth showing at all. The lead-service tab is kept out the same way, for the
    # same reason: each tab's count is the current selection's, whichever tab is on.
    clause = " and ".join(where)
    svc_clause, svc_params = "", []
    if sells and service:
        svc_clause = " and " + (LS_KEY if service in SERVICE_BUCKETS else LS_SERVICE) + " = %s"
        svc_params = [service]
    contact_clause = (" and " + HAS_ADDRESS if contact == "yes" else
                      " and not " + HAS_ADDRESS if contact == "no" else "")
    rows_clause = clause + svc_clause + contact_clause

    # Segment 3: the UI's card_fields are metadata paths the segment config
    # names; select them as columns so cards never need the whole metadata.
    import re as _re
    fields = []
    for f in (segment_info(segment)["ui"].get("card_fields") or []):
        path = str(f.get("path", ""))
        if _re.fullmatch(r"metadata(\.[A-Za-z0-9_]+)+", path):
            fields.append("{" + ",".join(path.split(".")[1:]) + "}")
    extra = "".join(" e.metadata #>> '%s' as f%d," % (p, i) for i, p in enumerate(fields))
    if sells:
        extra += " " + LS_KEY + " as service,"      # the card's "Selling" tag

    from recipient_selection import CONTACT_SELECTION_SQL
    with cursor() as cur:
        cur.execute(
            "select e.id, e.name, e.domain, e.source, e.status,"
            " round(coalesce(e.fit_score,0)::numeric,1) as fit_score,"
            " e.metadata->>'why_fit' as why_fit, e.metadata->>'kind' as kind,"
            " case when e.metadata->'host'->>'confidence' in ('high','medium')"
            "      then e.metadata->'host'->>'name' end as host_name," + extra +
            " e.metadata->>'hq_city' as city, e.metadata->>'hq_state' as state,"
            # The same saved recipient preference the drafter and composer use.
            " (select picked.email from (" + CONTACT_SELECTION_SQL + ") picked) as email,"
            " (select picked.full_name from (" + CONTACT_SELECTION_SQL + ") picked) as contact_name,"
            # who reached out to it: the approver of its latest first email that went out (2026-09-26)
            " (select o.approved_by from outreach o where o.entity_id = e.id and o.direction = 'outbound'"
            "   and o.status = 'sent' and coalesce(o.sequence_step, 0) = 0 order by o.sent_at desc limit 1) as reached_by"
            " from entities e where " + rows_clause +
            " order by " + order + " limit %s offset %s",
            params + svc_params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        people = _people() if any(r["reached_by"] for r in rows) else {}
        for r in rows:
            r["fields"] = [r.pop("f%d" % i) for i in range(len(fields))]
            r["reached_by_name"] = _display(r["reached_by"], people)
        cur.execute("select count(*) filter (where " + HAS_ADDRESS + ") as with_address,"
                    " count(*) filter (where not " + HAS_ADDRESS + ") as without_address"
                    " from entities e where " + clause + svc_clause, params + svc_params)
        split = cur.fetchone()
        total = (split["with_address"] if contact == "yes" else
                 split["without_address"] if contact == "no" else
                 split["with_address"] + split["without_address"])
        out = {"total": total, "rows": rows,
               "with_address": split["with_address"], "without_address": split["without_address"]}
        if sells:
            # every tab's count for the current selection (its other filters, the address filter included), and
            # All's: the Board adds its columns' up, so its tabs count what is on the board
            cur.execute("select " + LS_KEY + " as k, count(*) as n from entities e where " + clause + contact_clause +
                        " group by 1", params)
            got = [dict(r) for r in cur.fetchall()]
            out["service_counts"] = service_counts(got)
            out["service_all"] = sum(int(r["n"]) for r in got)
    return out


# -------------------------------------------------------------------- detail
def _recipient_locked_reason(messages):
    """Changing a recipient never changes an approval or an existing conversation."""
    if any(m["status"] in ("sending", "send_unknown") for m in messages):
        return "This email is already sending. Its recipient cannot be changed."
    if any(m["direction"] == "inbound" or m["status"] == "sent" for m in messages):
        return "This lead already has an email thread. Its recipient cannot be changed."
    if any(m["direction"] == "outbound" and m["status"] == "approved" for m in messages):
        return "Withdraw approval before changing the recipient."
    return None


def _recipient_greeting(body, old_contact, contact, entity, ocfg, preference):
    """Replace only the known initial greeting; leave all custom email copy intact."""
    from recipient_selection import recipient_metadata
    dr = _render()
    meta = entity.get("metadata") or {}
    old = old_contact or {}
    before = dr.pick_greeting(old.get("full_name"), old.get("email"), entity["name"],
                              recipient_metadata(meta), ocfg, old.get("source"))
    after = dr.pick_greeting(contact.get("full_name"), contact.get("email"), entity["name"],
                             recipient_metadata(dict(meta, outreach_recipient=preference)), ocfg,
                             contact.get("source"))
    if before != after:
        for salutation in ("Hi", "Hello", "Dear"):
            prefix = "%s %s," % (salutation, before)
            if (body or "").startswith(prefix):
                return "%s %s," % (salutation, after) + body[len(prefix):]
    person = dr.greeting_person(contact.get("full_name"), contact.get("email"), entity["name"],
                                recipient_metadata(dict(meta, outreach_recipient=preference)), contact.get("source"))
    if person:
        for salutation in ("Hi", "Hello", "Dear"):
            prefix = salutation + ","
            if (body or "").startswith(prefix):
                return "%s %s," % (salutation, person) + body[len(prefix):]
    return body


@app.get("/api/leads/{lead_id}")
def lead(lead_id: str, segment: str = Depends(current_segment)):
    from recipient_selection import select_contact
    lead_id = _id(lead_id)
    with cursor() as cur:
        cur.execute(
            "select e.*, s.slug as segment_slug, s.config as segment_config"
            " from entities e join segments s on s.id = e.segment_id"
            " where e.id = %s and s.slug = %s", (lead_id, segment))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        # every address, best first: the order the draft step uses (contact_rank, sql/28)
        cur.execute(
            "select c.id, c.full_name, c.role_title, c.email, c.email_status, c.is_primary, c.source, c.notes,"
            " c.linkedin_url, contact_allowed(c.entity_id,c.source,c.verifier,c.email_status) as contact_allowed,"
            " case when contact_allowed(c.entity_id,c.source,c.verifier,c.email_status)"
            " then contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) else -1000 end as rank"
            " from contacts c join entities e on e.id = c.entity_id"
            " where c.entity_id = %s order by rank desc, c.created_at, c.id", (lead_id,))
        all_contacts = [dict(c, id=str(c["id"])) for c in cur.fetchall()]
        picked = select_contact(cur, lead_id)
        sells = isinstance(row.get("segment_config"), dict) and "lead_service" in row["segment_config"]
        cur.execute(
            "select id, contact_id, status, subject, template_key, approved_by, approved_at, sender_address, sent_at,"
            " send_after, send_before, send_tz, send_tz_reason, send_plan, send_reschedules, send_wait_why, send_error,"
            " service, sent_as"                   # the one service it pitched (sql/35); the alias it went as (sql/36)
            " from outreach"
            " where entity_id = %s and direction = 'outbound' and coalesce(sequence_step, 0) = 0"
            " and status not in ('cancelled', 'failed') order by created_at desc limit 1", (lead_id,))
        draft = cur.fetchone()
        actual_id = str(draft["contact_id"]) if draft and draft["contact_id"] else None
        metadata = row.get("metadata") or {}
        has_preference = "outreach_recipient" in metadata
        selected_id = str(picked["id"]) if picked and has_preference else actual_id or (
            str(picked["id"]) if picked else None)
        # Keep one row per address, preserving the actual assigned contact's identity even
        # when another source has since inserted the same email with a higher rank.
        from contacts import junk_reason

        def selectable_contact(contact):
            return bool(contact.get("email") and contact.get("contact_allowed") and contact.get("rank", -1000) > -500
                        and contact.get("email_status") != "invalid" and not junk_reason(contact["email"]))

        contacts, by_email, representatives = [], {}, {}
        for c in sorted(all_contacts, key=lambda c: (c["id"] != actual_id, c["id"] != selected_id)):
            key = (c.get("email") or "").strip().lower() or c["id"]
            representative = by_email.get(key)
            if representative is None or (not selectable_contact(representative) and selectable_contact(c)):
                # An obsolete assigned row must not hide the eligible replacement at
                # the same normalized address. Keep its badge and expose the repair.
                by_email[key] = c
                contacts.append(c)
                representative = c
            representatives[c["id"]] = representative["id"]
        selected_id = representatives.get(selected_id, selected_id)
        cur.execute("select direction,status from outreach where entity_id=%s", (lead_id,))
        row["recipient_locked_reason"] = _recipient_locked_reason(cur.fetchall())
        row["selected_recipient_id"] = selected_id
        row["recipient_selection_stale"] = has_preference and picked is None
        # when it goes (approved) or which window approving it aims at (a draft): the words explain.py and
        # the lead sheet show, from tools/send_window.py's labels (owner, 2026-10-12)
        timing = {}
        if draft:
            ocfg = (row.get("segment_config") or {}).get("outreach") or {}
            wcfg = _wcfg(ocfg)
            timing["schedule"] = _policy().schedule_view(dict(draft), wcfg, paused=_policy().sending_paused(ocfg))
            if draft["status"] == "drafted" and wcfg:
                timing["window"] = _policy().draft_window(cur, str(draft["id"]), ocfg)

    # What the score is made of, what nobody has checked yet, the analysis a
    # reviewer used to be left to do by ticking boxes, and every route in.
    # app/explain.py; the owner's review of 2026-09-17 asked for all four.
    import explain
    cfg = row.pop("segment_config") or {}
    slug = row.pop("segment_slug")
    ranked = explain.rank_contacts(contacts, row.get("domain"))
    for c in ranked:
        c["drafts_use"] = c["id"] == actual_id
        c["selected_recipient"] = c["id"] == selected_id
        allowed = c.pop("contact_allowed", False)
        c["can_select_recipient"] = bool(c["usable"] and allowed
                                         and c.get("rank", -1000) > -500)
        c["recipient_unavailable_reason"] = None if c["can_select_recipient"] else (
            c.get("unusable_reason") or "This address is not eligible for sending under this project's contact rules.")
    row["contacts"] = ranked
    outreach = dict(draft, id=str(draft["id"])) if draft else None
    if outreach:
        outreach["contact_id"] = str(outreach["contact_id"]) if outreach.get("contact_id") else None
        # who reached out (owner, 2026-09-26): the person who approved it, from which address, when
        outreach["approved_by_name"] = _display(outreach.get("approved_by"), _people())
        _shown_sender(outreach)
        for k in ("approved_at", "sent_at"):
            outreach[k] = outreach[k].isoformat() if outreach.get(k) else None
        for k in ("send_after", "send_before", "send_tz", "send_tz_reason", "send_plan", "send_reschedules",
                  "send_wait_why", "send_error"):
            outreach.pop(k, None)                 # one shape for a time, everywhere: schedule (and window)
        if not sells and outreach.get("service") is None:
            outreach.pop("service", None)         # LCX Services' alone: every other project's answer is as before
        outreach.update(timing)
    row["outreach"] = outreach
    row["explain"] = explain.explain_lead(slug, cfg, row, ranked, outreach)
    row["criteria"] = [dict(c, assessed=c["state"] != explain.UNCHECKED) for c in row["explain"]["criteria"]]
    if sells:
        # the one service its email pitches, why, and the 18 a person may pick from instead (LCX Services)
        row["lead_service"] = lead_service_view(cfg, row)
    meta = row.get("metadata") or {}
    h = meta.get("host") or {}
    row["host_name"] = h.get("name") if h.get("confidence") in ("high", "medium") else None
    row["thresholds"] = {"review": cfg.get("score_threshold_review"), "priority": cfg.get("score_threshold_priority")}
    row["id"] = str(row["id"])
    row["segment_id"] = str(row["segment_id"])
    return row


@app.post("/api/leads/{lead_id}/recipient")
def lead_recipient_pick(lead_id: str, request: Request, body: dict = Body(...),
                        segment: str = Depends(current_segment)):
    """Choose an eligible contact, saving it for future drafts or retargeting an unapproved opener."""
    import datetime as _dt
    from recipient_selection import ELIGIBLE_CONTACT_SQL
    lead_id = _id(lead_id)
    contact_id = _id((body or {}).get("contact_id"), "contact")
    user = getattr(request.state, "user", None) or "unknown"
    with cursor() as cur:
        # Entity first, outreach second: drafting and manual contact linking use this order too.
        cur.execute("select e.id,e.name,e.metadata,s.config from entities e"
                    " join segments s on s.id=e.segment_id where e.id=%s and s.slug=%s for update of e",
                    (lead_id, segment))
        entity = cur.fetchone()
        if not entity:
            raise HTTPException(404, "No such lead in this project.")
        cur.execute("select id,direction,status,contact_id,body,coalesce(sequence_step,0) as sequence_step"
                    " from outreach where entity_id=%s order by created_at,id for update", (lead_id,))
        messages = cur.fetchall()
        locked = _recipient_locked_reason(messages)
        if locked:
            raise HTTPException(409, locked)
        cur.execute("select c.* from contacts c join entities e on e.id=c.entity_id"
                    " where c.id=%s and c.entity_id=%s and " + ELIGIBLE_CONTACT_SQL + " for share of c",
                    (contact_id, lead_id))
        contact = cur.fetchone()
        if not contact:
            raise HTTPException(409, "Choose an eligible email belonging to this lead. Apollo projects require an Apollo-verified contact.")
        preference = {"contact_id": contact_id, "email": contact["email"], "chosen_by": user,
                      "chosen_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()}
        draft = next((m for m in messages if m["direction"] == "outbound" and m["status"] == "drafted"
                      and m["sequence_step"] == 0), None)
        changed = False
        if draft and str(draft.get("contact_id")) != contact_id:
            cur.execute("select full_name,email,source from contacts where id=%s", (draft["contact_id"],))
            old_contact = cur.fetchone()
            text = _recipient_greeting(draft["body"], old_contact, contact, entity,
                                       (entity["config"] or {}).get("outreach") or {}, preference)
            cur.execute("update outreach set contact_id=%s,body=%s,updated_at=now() where id=%s and status='drafted'",
                        (contact_id, text, draft["id"]))
            changed = True
        cur.execute("update entities set metadata=jsonb_set(coalesce(metadata,'{}'::jsonb),'{outreach_recipient}',%s),"
                    " updated_at=now() where id=%s", (psycopg2.extras.Json(preference), lead_id))
    return {"ok": True, "selected_recipient_id": contact_id, "draft_updated": changed,
            "outreach_id": str(draft["id"]) if draft else None}


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


# ------------------------------------------------------------ lead service
def lead_service_view(cfg, row, people=None):
    """The lead sheet's Lead service box (LCX Services): the one service its email pitches and why (the rule, its
    reason and evidence), who chose it (the rules, or a person, who the rules never overrule), why its email is held
    if it is (app/explain.lead_service, from the drafter's own gate), the other services it fits (metadata.services,
    what the sheet called "Pitch first" before one service was picked), and the 18 a person may pick from."""
    import explain
    s = explain.lead_service(cfg, row) or {}
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    gp = (cfg.get("outreach") or {}).get("generated_pitch") or {}
    choices = [x for x in (gp.get("all_services") or list(gp.get("service_lines") or {})) if isinstance(x, str)]
    by = s.get("set_by")
    person = by not in (None, "", "rules")
    if person and people is None:
        people = _people()
    return dict(s, label=s.get("service") or explain.SERVICE_BUCKET_LABEL.get(s.get("key")),
                by_person=person, set_by_name=_display(by, people) if person else None,
                also_fits=[x for x in (meta.get("services") or []) if isinstance(x, str) and x != s.get("service")],
                choices=choices)


@app.post("/api/leads/{lead_id}/service")
def lead_service_pick(lead_id: str, request: Request, body: dict = Body(...)):
    """A person picks the one service a lead's email pitches, or confirms the rules' pick (LCX Services; the owner's
    review of its emails, 2026-10-13, point 12). Theirs stands: the rules never undo a person's choice
    (tools/lcx_judge.py), and the drafter's holds (Check service, Read site first, an audience-only pick) give way to
    it. A first email still waiting for approval that pitches something else is withdrawn, and the lead is drafted
    again pitching this one; an email already approved or sent keeps what it pitched (sql/35)."""
    import datetime as _dt
    lead_id = _id(lead_id)
    want = str((body or {}).get("service") or "").strip()
    user = getattr(request.state, "user", None) or ""
    with cursor() as cur:
        cur.execute("select e.id, e.name, e.status, e.metadata, s.slug, s.config"
                    " from entities e join segments s on s.id = e.segment_id where e.id = %s for update of e",
                    (lead_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such lead")
        row = dict(row)
        cfg = row.pop("config") or {}
        if "lead_service" not in cfg:
            raise HTTPException(409, "This project does not pitch one service per lead.")
        gp = (cfg.get("outreach") or {}).get("generated_pitch") or {}
        choices = [x for x in (gp.get("all_services") or list(gp.get("service_lines") or {})) if isinstance(x, str)]
        if want not in choices:
            raise HTTPException(400, "Pick one of the %d services in the deck." % len(choices))
        meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
        old = meta.get("lead_service") if isinstance(meta.get("lead_service"), dict) else None
        people = _people()
        name = _display(user, people)
        tag = {"service": want, "name": want, "rule": "person", "basis": "person", "reason": "Picked by %s" % name,
               "evidence": "", "set_by": user,
               "decided_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()}
        # what the rules had picked, kept beside it, so the sheet (and anyone reading the row) can still see it
        prior = old.get("rules_pick") if old and old.get("set_by") not in (None, "", "rules") else old
        if isinstance(prior, dict):
            tag["rules_pick"] = {k: prior[k] for k in ("service", "rule", "basis", "reason", "evidence")
                                 if prior.get(k) is not None}
        cur.execute("update entities set metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{lead_service}', %s),"
                    " updated_at = now() where id = %s", (psycopg2.extras.Json(tag), lead_id))
        cur.execute("update outreach set status = 'cancelled', stopped_reason = %s, updated_at = now()"
                    " where entity_id = %s and direction = 'outbound' and status = 'drafted'"
                    " and coalesce(sequence_step, 0) = 0 and service is distinct from %s",
                    (("service changed to %s by %s" % (want, name))[:200], lead_id, want))
        withdrawn = cur.rowcount
        cur.execute("select status, service from outreach where entity_id = %s and direction = 'outbound'"
                    " and coalesce(sequence_step, 0) = 0 and status not in ('cancelled', 'failed')"
                    " order by created_at desc limit 1", (lead_id,))
        live = cur.fetchone()
        row["metadata"] = dict(meta, lead_service=tag)
        view = lead_service_view(cfg, row, people)
    # shortlisted with no email left: drafted now, pitching this service (app/scheduler.py), as a shortlist is
    drafting = bool(row["status"] == "shortlisted" and not live and (cfg.get("outreach") or {}).get("templates"))
    if drafting:
        _scheduler.kick_outreach(row["slug"], "manual")
    return {"ok": True, "lead_service": view, "withdrawn": withdrawn, "drafting": drafting,
            "email": {"status": live["status"], "service": live["service"]} if live else None}


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
def _outreach_select():
    """Shared row shape for a folder and a direct email lookup."""
    import outreach_query as oq
    from recipient_selection import CONTACT_SELECTION_SQL
    pol = _policy()
    return (
        "select f.*,e.fit_score as lead_score," + oq.CATEGORY + " as category,"
        + oq.SUBSCRIBERS + " as subscriber_count," + oq.VIEWS + " as view_count,"
        " stored.contact_id as recipient_contact_id,"
        # a reply: when it came, and whether our side has answered it, when and how (sql/46, waiting on us)
        " case when f.direction = 'inbound' then " + pol.received("stored") + " end as received_at,"
        " stored.answered_at, stored.answered_by, stored.answered_how, stored.reply_kind,"
        " " + pol.unanswered("stored") + " as awaiting_answer,"
        # a follow-up's thread owner: the opener's approver, whose Gmail it goes out from and who signs it
        " case when coalesce(f.sequence_step, 0) > 0 and f.status = 'drafted' then"
        "  (select p.approved_by from outreach p where p.id = f.parent_id) end as thread_owner,"
        " e.status as lead_status,c.email_status,contact_allowed(e.id,c.source,c.verifier,c.email_status) as contact_verified,"
        " (e.status in ('shortlisted','contacted') and exists(select 1 from (" + CONTACT_SELECTION_SQL
        + ") available)) as can_link_contact"
        " from outreach_folders f join entities e on e.id = f.entity_id"
        " join outreach stored on stored.id=f.id left join contacts c on c.id=stored.contact_id"
    )


def _present_outreach(rows, request, segment, cfg, people=None):
    """Use the same sender preview and approval checks wherever an email opens."""
    people = _people() if people is None else people
    me = people.get((getattr(request.state, "user", None) or "").lower())
    dr, pol = _render(), _policy()
    wcfg, paused = _wcfg(cfg), pol.sending_paused(cfg)
    sells = sells_services(segment)
    for r in rows:
        r["id"] = str(r["id"]); r["entity_id"] = str(r["entity_id"])
        if not sells and r.get("service") is None:
            # the one service an email pitched (sql/35) is LCX Services' alone: everyone else's rows are as before
            r.pop("service", None)
        # who reached out: the person who approved it, from their own Gmail (sender_address)
        r["approved_by_name"] = _display(r.get("approved_by"), people)
        _shown_sender(r)
        # who it is copied to (sql/39): as set on it; a draft or approval still at null takes the project's default
        # (as the sender would); a sent email shows exactly who it went to (the sender records it)
        default_cc = [str(a).strip().lower() for a in (cfg.get("default_cc") or []) if str(a).strip()]
        if r.get("direction") == "outbound":
            r["cc_default"] = default_cc
            r["cc"] = (list(r["cc"]) if r.get("cc") is not None
                       else default_cc if r["status"] in ("drafted", "approved") else [])
        if r["status"] == "drafted" and r["direction"] == "outbound":
            owner = people.get(str(r.get("thread_owner") or "").lower()) if int(r.get("sequence_step") or 0) > 0 else None
            r["body"] = dr.personalize(r["body"], cfg, owner if owner and owner.get("name") and owner.get("title") else me)
            r["approval_blocked"] = ("Needs a verified contact before approval." if not r.get("contact_email")
                else "Recipient failed email verification." if r.get("email_status") == "invalid"
                else "Recipient email is not eligible for sending." if not r.get("contact_verified")
                else "Company qualification is still in review." if not r.get("sequence_step")
                     and r["lead_status"] not in ("shortlisted", "contacted") else None)
        if r["direction"] == "outbound" and r["status"] in ("approved", "sending", "sent"):
            # when it goes (or went): its recipient's clock and India's, and why that zone -- or, held back
            # (a send error, or sending paused), no time at all and why
            r["schedule"] = pol.schedule_view(r, wcfg, paused=paused)
    return rows


@app.get("/api/outreach")
def outreach_list(request: Request, folder: str = "drafts", category: str = "", service: str = "",
                  sort: str = "default", direction: str = "desc", limit: int = 200, offset: int = 0,
                  negatives_apart: bool = True, segment: str = Depends(current_segment)):
    """One folder of the outreach_folders view, newest first, for this segment. Replies holds
    every reply, marked or not (the mark is on the row); 'untriaged' counts the ones nobody has
    marked yet, which is what the sidebar count shows.

    Where emails go out from the approver's own Gmail, a draft is shown as the person looking at it
    would send it: their sign-off, their voice (tools/draft_render.personalize). Approving stores
    exactly that; the stored draft stays in the project's own form until then.

    Replies (owner, 2026-10-28: "Set replies to newest first as default and if a reply is categorised as [negative]
    create another section at the bottom of this page only which has the negative replies"): the list holds the
    replies not marked Negative, newest first; the Negative ones come apart, newest first, as negative_rows (all of
    them, at most 200, whatever the filters) for their own section under it. The API (negatives_apart=False) keeps
    every reply in one list."""
    apart = folder == "inbox" and negatives_apart
    folders = (["inbox", "positive"] if apart else ["inbox", "positive", "negative"]) if folder == "inbox" else [folder]
    talking = folder == "conversation"          # In conversation: a company per row, not a folder of the view
    pol = _policy()
    import outreach_query as oq
    try:
        order = oq.ordering(folder, sort, direction)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if len(category) > 200 or len(service) > 200:
        raise HTTPException(400, "That outreach filter is too long.")
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    base = "e.segment_id = (select id from segments where slug = %s)"
    filters, params = [], [segment]
    if category:
        filters.append(oq.CATEGORY + " = %s"); params.append(category)
    if service:
        filters.append("f.service = %s"); params.append(service)
    clause = base + (" and " + " and ".join(filters) if filters else "")
    people = _people()
    with cursor() as cur:
        cfg = pol.outreach_config(cur, segment)
        order = oq.ordering(folder, sort, direction, bool(cfg.get("prioritize_fresh_leads")))
        if talking:
            cur.execute(_outreach_select() + " where " + oq.CONVERSATION + " and " + clause +
                        " order by " + order + " limit %s offset %s", params + [limit, offset])
        else:
            cur.execute(
                _outreach_select() +
                " where f.folder = any(%s) and " + clause +
                " order by " + order + " limit %s offset %s", [folders] + params + [limit, offset])
        rows = [dict(r) for r in cur.fetchall()]
        rows = _present_outreach(rows, request, segment, cfg, people)
        negative_rows = None
        if apart:
            cur.execute(_outreach_select() + " where f.folder = 'negative' and " + base +
                        " order by " + oq.WHEN + " desc, f.id limit 200", [segment])
            negative_rows = _present_outreach([dict(r) for r in cur.fetchall()], request, segment, cfg, people)
        if talking and rows:
            # who on our side is in it (whoever's first email it answers), how long the thread is, and since when
            # it waits for our answer (sql/46)
            cur.execute("select e.id as eid,"
                        " (select p.approved_by from outreach p where p.entity_id = e.id and p.direction = 'outbound'"
                        "   and coalesce(p.sequence_step, 0) = 0 and p.status = 'sent' order by p.sent_at desc limit 1)"
                        "   as reached_by,"
                        " (select count(*) from outreach m where m.entity_id = e.id and (m.direction = 'inbound'"
                        "   or m.status = 'sent')) as messages, " + oq.waiting_since("e.id") + " as waiting_since"
                        " from entities e where e.id = any(%s::uuid[])", ([r["entity_id"] for r in rows],))
            extra = {str(x["eid"]): x for x in cur.fetchall()}
            for r in rows:
                x = extra.get(r["entity_id"]) or {}
                r["reached_by"] = x.get("reached_by")
                r["reached_by_name"] = _display(x.get("reached_by"), people) if x.get("reached_by") else None
                r["thread_messages"] = x.get("messages") or 0
                r["waiting_since"] = x.get("waiting_since")
        def talk(where):
            # In conversation, and how many of them wait on us, are counted in the same round trip as the folders
            # (neither is a folder of the view)
            them = " from outreach_folders f join entities e on e.id = f.entity_id where " + oq.CONVERSATION + " and "
            return (" union all select 'conversation', count(*)" + them + where
                    + " union all select 'waiting', count(*)" + them + oq.waiting_since() + " is not null and " + where)
        cur.execute("select f.folder, count(*) as n from outreach_folders f"
                    " join entities e on e.id = f.entity_id"
                    " where e.segment_id = (select id from segments where slug = %s) group by f.folder" + talk(base),
                    (segment, segment, segment))
        counts = oq.folder_counts(cur.fetchall())
        cur.execute("select f.folder,count(*) as n from outreach_folders f join entities e on e.id=f.entity_id"
                    " where " + clause + " group by f.folder" + talk(clause), params * 3)
        filtered_counts = oq.folder_counts(cur.fetchall())
        cur.execute("select " + oq.CATEGORY + " as key,count(*) as n from outreach_folders f"
                    " join entities e on e.id=f.entity_id where " + base + " group by 1 order by 1", (segment,))
        categories = [dict(r) for r in cur.fetchall()]
        cur.execute("select config->'audiences' as audiences from segments where slug=%s", (segment,))
        audiences = (cur.fetchone() or {}).get("audiences") or []
        labels = {a["key"]: a.get("label") or a["key"] for a in audiences if a.get("key")}
        for item in categories:
            item["label"] = labels.get(item["key"], item["key"].replace("_", " ").capitalize())
        cur.execute("select f.service as key,count(*) as n from outreach_folders f join entities e on e.id=f.entity_id"
                    " where " + base + " and nullif(f.service,'') is not null group by 1 order by 1", (segment,))
        services = [dict(r) for r in cur.fetchall()]
    total = filtered_counts.get(folder, 0)
    if apart:                                    # the list's own pages: the Negative ones are under it
        total = max(0, total - filtered_counts.get("negative_n", 0))
    out = {"rows": rows, "counts": counts, "filtered_counts": filtered_counts,
           "total": total, "categories": categories, "services": services,
           "limit": limit, "offset": offset}
    if negative_rows is not None:
        out["negative_rows"] = negative_rows
    return out


@app.get("/api/outreach/attachment")
def outreach_attachment(path: str = ""):
    """A file an email carries (outreach.attachments, sql/32; LCX Services: the services deck), opened
    from the email's sheet so whoever approves it reads exactly what goes with it. Only files under
    docs/decks/ can be attached, so only those are served here."""
    try:
        full = _policy().attachment_file(path)
    except ValueError:
        raise HTTPException(404, "no such attachment")
    if not os.path.isfile(full):
        raise HTTPException(404, "no such attachment")
    import mimetypes
    name = os.path.basename(full)
    return FileResponse(full, filename=name, content_disposition_type="inline",
                        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream")


def _rewrite_email(body, cfg, person=None, context=None):
    _render()  # adds tools/ to the import path
    import email_rewrite
    import llm
    b = body or {}
    try:
        result = email_rewrite.rewrite(b.get("subject", ""), b.get("body", ""),
                                       b.get("instructions", ""), cfg, person, context)
        from mail_copy import clean_text
        for field in ("subject", "body"):
            if result.get(field) is not None:
                result[field] = clean_text(result[field], remove_offer=field == "body")
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except llm.Unavailable:
        raise HTTPException(503, "Email rewriting is unavailable right now. Your draft is unchanged; try again shortly.")


@app.post("/api/outreach/rewrite")
def outreach_compose_rewrite(request: Request, body: dict = Body(...),
                             segment: str = Depends(current_segment)):
    """Rewrite the unsaved email in the compose window. Never creates or approves outreach."""
    want = str((body or {}).get("project") or "").strip()
    with cursor() as cur:
        if want:
            # Add a lead (tools/manual_lead.py): the email is for the project the person picked there
            if want not in [r["slug"] for r in segment_rows()]:
                raise HTTPException(404, "no such project")
            cfg = _policy().outreach_config(cur, want)
        else:
            cfg = _policy().outreach_config(cur, segment)
            if not cfg.get("compose"):
                raise HTTPException(403, "Writing emails to picked leads is not on for this project.")
        cur.execute("select email, name, title from app_users where lower(email) = lower(%s)",
                    (getattr(request.state, "user", ""),))
        person = cur.fetchone()
    return _rewrite_email(body, cfg, dict(person) if person else None)


@app.post("/api/outreach/{oid}/rewrite")
def outreach_draft_rewrite(oid: str, request: Request, body: dict = Body(...),
                           segment: str = Depends(current_segment)):
    """Return an editable rewrite of the current draft, including unsaved edits. No write occurs."""
    oid = _id(oid, "draft")
    with cursor() as cur:
        cur.execute("select o.status, o.direction, e.name as company, s.slug"
                    " from outreach o join entities e on e.id = o.entity_id"
                    " join segments s on s.id = e.segment_id where o.id = %s", (oid,))
        row = cur.fetchone()
        if not row or row["slug"] != segment:
            raise HTTPException(404, "No such draft in this project.")
        if row["status"] != "drafted" or row["direction"] != "outbound":
            raise HTTPException(409, "Only outbound drafts can be rewritten.")
        cfg = _policy().outreach_config(cur, segment)
        cur.execute("select email, name, title from app_users where lower(email) = lower(%s)",
                    (getattr(request.state, "user", ""),))
        person = cur.fetchone()
    return _rewrite_email(body, cfg, dict(person) if person else None, {"company": row["company"]})


def _locked_recipients(cur, ids, segment):
    """Lock entities, their emails, then contacts in a stable order for a preview check."""
    cur.execute("select e.id from entities e join segments s on s.id=e.segment_id"
                " where s.slug=%s and e.id in (select entity_id from outreach where id=any(%s::uuid[]))"
                " order by e.id for update of e", (segment, ids))
    cur.fetchall()
    cur.execute("select o.id,o.contact_id from outreach o join entities e on e.id=o.entity_id"
                " join segments s on s.id=e.segment_id where o.id=any(%s::uuid[]) and s.slug=%s"
                " order by e.id,o.created_at,o.id for update of o", (ids, segment))
    rows = {str(r["id"]): dict(r) for r in cur.fetchall()}
    if set(rows) != set(ids):
        raise HTTPException(404, "No such email in this project.")
    contact_ids = sorted({str(r["contact_id"]) for r in rows.values() if r["contact_id"]})
    cur.execute("select id,email from contacts where id=any(%s::uuid[]) order by id for share", (contact_ids,))
    emails = {str(r["id"]): r["email"] for r in cur.fetchall()}
    return {oid: {"contact_id": str(row["contact_id"]) if row["contact_id"] else None,
                  "email": emails.get(str(row["contact_id"]))} for oid, row in rows.items()}


def _recipient_email(value):
    return str(value).strip().lower() if value is not None else None


def _check_expected_recipient(cur, oid, body, segment):
    """A stale open preview must be reopened before its changed recipient is approved or edited."""
    b = body or {}
    if "expected_contact_id" not in b and "expected_contact_email" not in b:
        return
    actual = _locked_recipients(cur, [oid], segment)[oid]
    if "expected_contact_id" in b:
        expected = b["expected_contact_id"]
        expected = _id(expected, "contact") if expected is not None else None
        changed = actual["contact_id"] != expected
    else:
        changed = False
    if "expected_contact_email" in b:
        changed = changed or _recipient_email(actual["email"]) != _recipient_email(b["expected_contact_email"])
    if changed:
        raise HTTPException(409, "The recipient changed. Reopen this draft before editing or approving.")


def _check_expected_recipients(cur, ids, body, segment):
    """The recipient map must cover every selected email, including ones outside the random sample."""
    if "expected_recipients" not in (body or {}):
        return
    expected = body["expected_recipients"]
    if not isinstance(expected, dict):
        raise HTTPException(400, "Recipient details are missing. Refresh the selected drafts and try again.")
    ids = [_id(oid, "message") for oid in ids]
    expected = {_id(oid, "message"): recipient for oid, recipient in expected.items()}
    if any(not isinstance(expected.get(oid), dict)
            or "contact_id" not in expected[oid] or "email" not in expected[oid] for oid in ids):
        raise HTTPException(400, "Recipient details are missing. Refresh the selected drafts and try again.")
    actual = _locked_recipients(cur, ids, segment)
    for oid in ids:
        contact_id = expected[oid]["contact_id"]
        contact_id = _id(contact_id, "contact") if contact_id is not None else None
        if actual[oid]["contact_id"] != contact_id or _recipient_email(actual[oid]["email"]) != _recipient_email(expected[oid]["email"]):
            raise HTTPException(409, "A selected draft's recipient changed. Reopen the drafts and select them again before approving.")


@app.patch("/api/outreach/{oid}")
def outreach_edit(oid: str, request: Request, body: dict = Body(...),
                  segment: str = Depends(current_segment)):
    """Edit a draft's subject/body. Approval means a human read THIS text, so
    editing is only legal while the row is still a draft. The body comes back as the editor saw it
    (their sign-off, their voice) and is stored in the project's own form, so the next person to
    open it sees it as theirs."""
    oid = _id(oid, "draft")
    subject = (body or {}).get("subject")
    text = (body or {}).get("body")
    # who it is copied to (owner, 2026-10-22; sql/39): a list, [] for nobody, or null for the project's default
    cc_given = "cc" in (body or {})
    cc = _clean_cc(body["cc"]) if cc_given else None
    if subject is not None and ("\n" in str(subject) or "\r" in str(subject)):
        # one line, always: the sender refuses a subject with a line break in it
        raise HTTPException(400, "the subject must be one line")
    dr = _render()
    if subject is not None:
        subject = dr.clean_text(str(subject), remove_offer=False)
    if text is not None:
        me = _people().get((getattr(request.state, "user", None) or "").lower())
        with cursor() as cur:
            cur.execute("select s.slug from outreach o join entities e on e.id = o.entity_id"
                        " join segments s on s.id = e.segment_id where o.id = %s", (oid,))
            seg = cur.fetchone()
            cfg = _policy().outreach_config(cur, seg["slug"]) if seg else {}
        text = dr.canonicalize(text, cfg, me)
    with cursor() as cur:
        _check_expected_recipient(cur, oid, body, segment)
        cur.execute(
            "update outreach set subject = coalesce(%s, subject),"
            " body = coalesce(%s, body), generated_hook = case when %s then coalesce(%s, body)"
            " else generated_hook end, cc = case when %s then %s::text[] else cc end, updated_at = now()"
            " where id = %s and status = 'drafted' returning id",
            (subject, text, (body or {}).get("ai_rewritten") is True, text, cc_given, cc, oid))
        if not cur.fetchone():
            raise HTTPException(409, "only drafts can be edited")
    return {"ok": True}


_CC_RE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[a-z]{2,}$")
CC_MAX = 10


def _clean_cc(value):
    """A CC list from the page -> lower-cased, de-duplicated addresses, or None (the project's default). Anything
    that is not an email address is refused (400), so Gmail never sees a malformed Cc line."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise HTTPException(400, "cc is a list of email addresses")
    out = []
    for v in value:
        a = str(v or "").strip().lower()
        if not a:
            continue
        if not _CC_RE.match(a):
            raise HTTPException(400, "%s is not an email address" % str(v)[:80])
        if a not in out:
            out.append(a)
    if len(out) > CC_MAX:
        raise HTTPException(400, "at most %d addresses in CC" % CC_MAX)
    return out


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
        if action == "link_contact":
            from recipient_selection import select_contact
            if int(msg.get("sequence_step") or 0) > 0:
                raise HTTPException(409, "An existing email thread keeps its original recipient.")
            cur.execute("select e.id,e.name,e.metadata,e.status as lead_status,s.slug,s.config from entities e"
                        " join segments s on s.id=e.segment_id where e.id=%s for update of e", (eid,))
            row = cur.fetchone()
            if row["slug"] != segment:
                raise HTTPException(404, "No such draft in this project.")
            cur.execute("select status,direction,contact_id,body from outreach where id=%s for update", (oid,))
            draft = cur.fetchone()
            if draft["status"] != "drafted" or draft["direction"] != "outbound" or row["lead_status"] not in ("shortlisted", "contacted"):
                raise HTTPException(409, "Qualify the company before linking its draft recipient.")
            contact = select_contact(cur, eid)
            if not contact:
                raise HTTPException(409, "No eligible verified contact is available. Check the lead's selected recipient.")
            cur.execute("select full_name,email,source from contacts where id=%s", (draft["contact_id"],))
            old_contact = cur.fetchone()
            preference = (row.get("metadata") or {}).get("outreach_recipient")
            text = _recipient_greeting(draft["body"], old_contact, contact, row,
                                       (row["config"] or {}).get("outreach") or {}, preference) if preference else draft["body"]
            cur.execute("update outreach set contact_id=%s,body=%s,updated_at=now() where id=%s and status='drafted'",
                        (contact["id"], text, oid))
            return {"ok": True}
        elif action == "approve":
            _check_expected_recipient(cur, oid, body, segment)
            cfg = pol.outreach_config(cur, segment)
            dr = _render()
            too_long = long_subjects(cur, [oid], cfg)
            if too_long:
                raise HTTPException(409, "cannot approve: " + too_long[0]["reason"])
            signed = signs_by_person(segment, cfg)
            if dr.signs_as_approver(cfg) or signed:
                # signed by the approver (from their own Gmail, or LCX Clipping's pool): exactly the text they were shown
                cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user,))
                person = cur.fetchone()
                if not person or not person["name"] or not person["title"]:
                    raise HTTPException(409, needs_signer(segment) if signed else
                                        "Add your name and title first (the account menu at the bottom of the sidebar): "
                                        "the emails you approve are signed with them.")
                signer = _sign_as(cur, oid, dict(person))      # a follow-up: its thread's owner
                cur.execute("select body from outreach where id = %s and status = 'drafted'", (oid,))
                row = cur.fetchone()
                if row:
                    mine = dr.personalize(row["body"], cfg, signer)
                    if signed and project_signoff(mine, cfg, signer):
                        raise HTTPException(409, "cannot approve: " + project_signoff(mine, cfg, signer))
                    if mine != row["body"]:
                        cur.execute("update outreach set body = %s, updated_at = now()"
                                    " where id = %s and status = 'drafted'", (mine, oid))
            ok, skipped = pol.check_drafts(cur, [oid], segment)
            if skipped:
                raise HTTPException(409, "cannot approve: " + skipped[0]["reason"])
            # through the API or MCP (app/api_v1.py, a key that may approve): recorded as such (sql/44)
            mode = "api" if getattr(request.state, "via_key", False) else "single"
            cur.execute("update outreach set status='approved', approved_at=now(), approved_by=%s,"
                        " approval_mode=%s, spot_checked=true, updated_at=now()"
                        " where id=%s and status='drafted' returning id", (user, mode, oid))
        elif action == "cancel":
            cur.execute("update outreach set status='cancelled', updated_at=now()"
                        " where id=%s and status in ('drafted','approved')"
                        " returning id", (oid,))
            if not cur.fetchone():
                # an approved email can be withdrawn until its moment comes; once claimed it is Gmail's
                cur.execute("select status from outreach where id = %s", (oid,))
                now = (cur.fetchone() or {}).get("status")
                if now in ("sending", "send_unknown"):
                    raise HTTPException(409, "already going out: it can no longer be withdrawn")
                if now == "sent":
                    raise HTTPException(409, "already sent")
                raise HTTPException(409, "row is not in a state that allows cancel")
            if (msg["sequence_step"] or 0) > 0:
                pol.stop_thread(cur, eid, "stopped: follow-up cancelled by %s" % user)
            return {"ok": True}
        elif action == "stop_sequence":
            n = pol.stop_thread(cur, eid, "stopped by %s" % user)
            return {"ok": True, "cancelled": n}
        elif action == "mark_answered":
            # answered another way -- a call, WhatsApp, a new email (sql/46): the company's replies waiting on us are
            # answered now, by this person; one answered in its thread the pull sees by itself
            cur.execute("update outreach r set answered_at = now(), answered_by = %s, answered_how = 'marked'"
                        " where r.entity_id = %s and " + pol.unanswered("r") + " returning r.id", (user, eid))
            n = len(cur.fetchall())
            if not n:
                raise HTTPException(409, "No reply of this company is waiting for an answer.")
            return {"ok": True, "answered": n}
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
        # Approving draws its own second in its recipient's next 10:00-10:30 (owner, 2026-10-12) and keeps
        # it on the row; with no free minute in 60 days the approval is not made, and the page says why
        try:
            sched = pol.schedule_sends(cur, [oid], cfg, segment).get(oid)
        except pol.NoSendSlot as e:
            raise HTTPException(409, "cannot approve: %s" % e)
    # approved: it is sent now, not when someone next opens a terminal (app/scheduler.py) -- or, with a
    # sending window, at its own moment: the send loop is told it has a new one to wait for
    _scheduler.kick_outreach(segment, "manual")
    _scheduler.wake_sender()
    return {"ok": True, "can_send": _can_send(segment, user), "paused": _send_paused(segment),
            "sends_from": _sends_from(segment, user), "schedule": sched}


@app.get("/api/outreach/{oid}/window")
def outreach_window(oid: str, segment: str = Depends(current_segment)):
    """The window approving this draft now aims at -- {enabled, send_tz, send_tz_reason, window_label}, a
    window and never a minute, which is drawn on approval -- or {"enabled": false}: no window for this
    project, or not a draft of it."""
    oid = _id(oid, "message")
    with cursor() as cur:
        cur.execute("select 1 from outreach o join entities e on e.id = o.entity_id"
                    " where o.id = %s and o.direction = 'outbound' and o.status = 'drafted'"
                    " and e.segment_id = (select id from segments where slug = %s)", (oid, segment))
        if not cur.fetchone():
            return {"enabled": False}
        cfg = _policy().outreach_config(cur, segment)
        if not _wcfg(cfg):
            return {"enabled": False}
        return _policy().draft_window(cur, oid, cfg)


@app.post("/api/outreach/batch/sample")
def outreach_batch_sample(request: Request, body: dict = Body(...),
                          segment: str = Depends(current_segment)):
    """Step 1 of batch approval: check the selected drafts, draw a random
    spot-check sample on the server, and sign batch + sample together."""
    import auth as _a
    pol = _policy()
    ids = sorted({str(i) for i in ((body or {}).get("ids") or [])})
    with cursor() as cur:
        cfg = pol.outreach_config(cur, segment)
        policy = pol.batch_policy(cfg)
        if not policy:
            raise HTTPException(403, "batch approval is off for this segment")
        if not ids:
            raise HTTPException(400, "select at least one draft")
        if len(ids) > policy["max_batch"]:
            raise HTTPException(400, "a batch is at most %d drafts" % policy["max_batch"])
        _check_expected_recipients(cur, ids, body, segment)
        unsigned = long_subjects(cur, ids, cfg)   # a subject over the cap is left out, saying why (2026-10-13)
        if signs_by_person(segment, cfg):
            # LCX Services (and LCX Clipping, signed by its approver since 2026-10-13): said before the sample is read,
            # not after (step 2 refuses the same, the same way): no name or title, or a draft that would still go out
            # signed by the project
            cur.execute("select email, name, title from app_users where lower(email) = lower(%s)",
                        (getattr(request.state, "user", None) or "",))
            person = cur.fetchone()
            if not person or not person["name"] or not person["title"]:
                raise HTTPException(409, needs_signer(segment))
            dr = _render()
            cur.execute("select id, body from outreach where id = any(%s::uuid[]) and status = 'drafted'", (ids,))
            for row in cur.fetchall():
                signer = _sign_as(cur, row["id"], dict(person))
                why = project_signoff(dr.personalize(row["body"], cfg, signer), cfg, signer)
                if why and str(row["id"]) not in {u["id"] for u in unsigned}:
                    unsigned.append({"id": str(row["id"]), "reason": why})
        held = {u["id"] for u in unsigned}
        ok, skipped = pol.check_drafts(cur, [i for i in ids if i not in held], segment, policy)
        skipped += unsigned
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
        cfg = pol.outreach_config(cur, segment)
        policy = pol.batch_policy(cfg)
        if not policy:
            raise HTTPException(403, "batch approval is off for this segment")
        _check_expected_recipients(cur, ids, body, segment)
        dr = _render()
        signed = signs_by_person(segment, cfg)
        # drafts that would still go out signed by the project (LCX Services, LCX Clipping), and, in every project with
        # outreach.subject_max_words, one whose subject is over it (2026-10-13): left out, saying why, and left as they are
        unsigned = long_subjects(cur, ids, cfg)
        if dr.signs_as_approver(cfg) or signed:
            # each one is signed by the approver (from their Gmail, or LCX Clipping's pool), as the sample they read was
            cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user or "",))
            person = cur.fetchone()
            if not person or not person["name"] or not person["title"]:
                raise HTTPException(409, needs_signer(segment) if signed else
                                    "Add your name and title first (the account menu at the bottom of the sidebar).")
            too_long = {u["id"] for u in unsigned}
            cur.execute("select id, body from outreach where id = any(%s::uuid[]) and status = 'drafted'", (ids,))
            for row in cur.fetchall():
                if str(row["id"]) in too_long:
                    continue
                signer = _sign_as(cur, row["id"], dict(person))
                mine = dr.personalize(row["body"], cfg, signer)
                why = project_signoff(mine, cfg, signer) if signed else None
                if why:
                    unsigned.append({"id": str(row["id"]), "reason": why})
                    continue
                if mine != row["body"]:
                    cur.execute("update outreach set body = %s, updated_at = now() where id = %s and status = 'drafted'",
                                (mine, row["id"]))
        held = {u["id"] for u in unsigned}
        ok, skipped = pol.check_drafts(cur, [i for i in ids if i not in held], segment, policy)
        skipped += unsigned
        # re-checked here, not trusted from step 1: the rule is about what is
        # being approved now, and a draft may have been redrafted since
        if len(sample) < pol.required_sample(len(ids), policy,
                                             bool(pol.generated_among(cur, ok))):
            raise HTTPException(400, "the spot-check sample is too small for this batch")
        # each approved one gets its own second in its recipient's window (outreach_policy.schedule_sends)
        batch_id, approved, schedule = pol.apply_batch(cur, ok, sample, user, segment, len(ids), skipped)
    if approved:
        _scheduler.kick_outreach(segment, "manual")          # approved means sent: no terminal step
        _scheduler.wake_sender()
    # "9 on Tue 14 Oct (6 New York, 3 UK), 3 on Wed 15 Oct": by the recipients' own days ([] without a window).
    # A paused project's are held, and a held email is never shown a send time (second review, 2026-10-12): the
    # times drawn now move on at each missed window until the pause is lifted, so none is promised
    paused = _send_paused(segment)
    return {"batch_id": batch_id, "approved": approved, "skipped": skipped, "can_send": _can_send(segment, user),
            "paused": paused, "sends_from": _sends_from(segment, user),
            "windows": [] if paused else pol.window_summary(schedule)}


def _compose_module():
    """tools/outreach_compose.py -- an email a person writes to leads they picked."""
    import sys
    p = os.path.join(REPO, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    import outreach_compose
    return outreach_compose


def _compose(request, body, segment, apply):
    comp = _compose_module()
    b = body or {}
    user = getattr(request.state, "user", None) or ""
    with cursor() as cur:
        cfg = _policy().outreach_config(cur, segment)
        if not comp.compose_on(cfg):
            raise HTTPException(403, "writing emails to picked leads is not on for this project")
        cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user,))
        person = cur.fetchone()
        try:
            out = comp.plan(cur, segment, b.get("ids") or [], b.get("subject") or "", b.get("body") or "",
                            dict(person) if person else None, cfg, apply=apply,
                            cc=_clean_cc(b["cc"]) if "cc" in b else None)
        except comp.Refused as e:
            raise HTTPException(e.code, str(e))
        boxes = []
        if cfg.get("send_from") == "approver":
            boxes = [{k: m[k] for k in ("address", "daily_cap", "out_today", "remaining", "usable")}
                     for m in _mailbox_store().mailboxes(cur, user_email=user)]
    out.update(approved=len(out["ready"]) if apply else 0, fields=list(comp.FIELDS), max=comp.MAX_RECIPIENTS,
               mailboxes=boxes, can_send=_can_send(segment, user), paused=_send_paused(segment),
               sends_from=_sends_from(segment, user))
    return out


@app.post("/api/outreach/compose/check")
def outreach_compose_check(request: Request, body: dict = Body(...), segment: str = Depends(current_segment)):
    """Before a person approves an email they wrote: who it goes to and how it greets each of them, who
    is skipped and why, the footer it ends with, and what approving will do. Nothing is kept."""
    return _compose(request, body, segment, apply=False)


@app.post("/api/outreach/compose")
def outreach_compose(request: Request, body: dict = Body(...), segment: str = Depends(current_segment)):
    """Approve an email a person wrote, for the leads they picked (the owner, 2026-09-27: "in the universal
    segment there should be a widget to send mail to them"). The same gate and the same sending as an
    approved draft: one approved email per company, from the approver's own Gmail, inside its daily limit."""
    out = _compose(request, body, segment, apply=True)
    if out["approved"]:
        _scheduler.kick_outreach(segment, "manual")            # approved means sent: no terminal step
        _scheduler.wake_sender()                                # each at its own moment, where there is a window
    return out


# --------------------------------------------------------- a lead found by hand
def _manual_module():
    """tools/manual_lead.py -- a lead a person found on their own, and the email they write to it."""
    _compose_module()                                           # tools/ on the import path
    import manual_lead
    return manual_lead


def _manual(request, body, apply):
    ml, comp = _manual_module(), _compose_module()
    b = dict(body or {})
    if "cc" in b:
        b["cc"] = _clean_cc(b["cc"])
    user = getattr(request.state, "user", None) or ""
    with cursor() as cur:
        cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user,))
        person = cur.fetchone()
        try:
            out = ml.run(cur, b, dict(person) if person else None, apply=apply,
                         segments=[r["slug"] for r in segment_rows()])
        except ml.Problems as e:
            return {"problems": e.problems, "warnings": {}, "project": None, "ready": [], "skipped": []}
        except comp.Refused as e:
            raise HTTPException(e.code, str(e))
        slug = out["project"]["slug"]
        cfg = _policy().outreach_config(cur, slug)
        boxes = []
        if cfg.get("send_from") == "approver":
            boxes = [{k: m[k] for k in ("address", "daily_cap", "out_today", "remaining", "usable")}
                     for m in _mailbox_store().mailboxes(cur, user_email=user)]
    out.update(mailboxes=boxes, can_send=_can_send(slug, user), paused=_send_paused(slug),
               sends_from=_sends_from(slug, user), send_window=_window_info(cfg.get("send_window")))
    return out


@app.post("/api/leads/manual/check")
def manual_lead_check(request: Request, body: dict = Body(...)):
    """As a person fills in Add a lead: what is missing or wrong, the lead it matches if it is already in the
    project, how the email reads, where it sends from and when. Nothing is kept."""
    return _manual(request, body, apply=False)


@app.post("/api/leads/manual")
def manual_lead_add(request: Request, body: dict = Body(...)):
    """Add a lead a person found on their own, in the project they picked, and approve the email they wrote to it
    (the owner, 2026-10-23: "send custom mail to a lead that we find on our own ... select the category it belongs
    to and then the usual"). The usual: it goes out from the approver's own Gmail in the project's sending window,
    copied to the default CC, with one follow-up four days later if nobody replies. All or nothing: when the email
    cannot go, no lead is added."""
    out = _manual(request, body, apply=True)
    if out.get("outreach_id"):
        slug = out["project"]["slug"]
        _SEG_CACHE.update(at=0.0)                               # the Leads page's sources now include Manual
        _scheduler.kick_outreach(slug, "manual")
        _scheduler.wake_sender()
    return out


def _can_send(segment, user=None):
    """Can an approval go out, and is sending not paused? Where emails go out from the approver's own
    Gmail: does this person have one connected and working? The page words an approval by it:
    "sending now", "sends as soon as a mailbox is connected", or "waits: sending is paused"."""
    try:
        with cursor() as cur:
            cfg = _policy().outreach_config(cur, segment)
            if _policy().sending_paused(cfg):
                return False
            if cfg.get("send_from") == "approver":
                return any(b["usable"] for b in _mailbox_store().mailboxes(cur, user_email=user or ""))
        return any(mb["enabled"] and _scheduler.mailbox_connected(mb)
                   for mb in _policy().mailbox_list(cfg, segment))
    except Exception:
        return False


def _sends_from(segment, user):
    """The approver's own addresses an approval of theirs goes out from (the one with most room first),
    or [] where the project sends from its own mailboxes."""
    try:
        with cursor() as cur:
            cfg = _policy().outreach_config(cur, segment)
            if cfg.get("send_from") != "approver":
                return []
            boxes = [b for b in _mailbox_store().mailboxes(cur, user_email=user or "") if b["usable"]]
        out = []
        for b in sorted(boxes, key=lambda b: -b["remaining"]):
            shown = _sends_as(b, cfg)
            if shown is not None:
                out.append(shown)
        return out
    except Exception:
        return []


def _shown_sender(row):
    """The From address the recipient saw (sql/36): an email sent as the account's alias shows the alias, and
    the account it went through as sent_through. Every other row is as it was."""
    alias = row.pop("sent_as", None)
    if alias:
        row["sent_through"] = row.get("sender_address")
        row["sender_address"] = alias
    return row


def _sends_as(box, cfg):
    """The From address an approval of this project goes out as through `box`: its alias on the project's
    send_as_domain (sql/36; LCX Services writes as LCX), the account itself where the project has none, the
    account while its aliases are not read yet (the next send reads them), or None when it has no alias there."""
    store = _mailbox_store()
    alias = store.alias_for(box, cfg.get("send_as_domain"))
    if alias is None:
        return None if cfg.get("send_as_domain") else box["address"]
    return box["address"] if alias == store.UNREAD else alias["address"]


def _send_paused(segment):
    """Why sending is paused for this segment (outreach.sending_paused), or None."""
    try:
        with cursor() as cur:
            return _policy().sending_paused(_policy().outreach_config(cur, segment))
    except Exception:
        return None


# ------------------------------------------------------------------ people
# One login per person (owner, 2026-09-26). Their name is how the page says who approved or reached out
# to a lead, and their name and title sign the emails they approve.
def _sign_as(cur, oid, person):
    """Who signs this draft. A follow-up goes out in its thread, from the Gmail of the person who approved the
    opener, so it is signed by them too (owner, 2026-10-23: follow-ups for every project), whoever approves it;
    when they have no name and title any more, and for every other draft, by `person`, the approver."""
    cur.execute("select u.email, u.name, u.title from outreach f join outreach p on p.id = f.parent_id"
                " join app_users u on lower(u.email) = lower(p.approved_by)"
                " where f.id = %s and coalesce(f.sequence_step, 0) > 0", (str(oid),))
    owner = cur.fetchone()
    return dict(owner) if owner and owner["name"] and owner["title"] else person


def _people():
    """{email (lower case): {"email", "name", "title"}} for everyone with a login."""
    with cursor() as cur:
        cur.execute("select email, name, title from app_users")
        return {r["email"].lower(): dict(r) for r in cur.fetchall()}


def _display(email, people):
    """A person's name for the page; the part of the address before the @ for someone without one."""
    if not email:
        return None
    p = people.get(email.lower())
    return (p and p.get("name")) or email.split("@")[0]


# LCX Services (the owner's review of its emails, 2026-10-13, point 10): an email is signed by the person who approves
# it, never by the project's own canonical sender ("LCX", the name a draft is stored under) or a SET_ME. So approving
# one is refused while the approver's profile has no name or no title, whatever outreach.send_from says, and refused
# when what would go out still ends with the project's sign-off (a footer edited by hand, so it could not be swapped
# for the approver's). Keyed on the project pitching one service per lead (config lead_service): every other project
# approves exactly as before.
NEEDS_SIGNER = ("Set your name and title in your profile first (Your name and title, in the account menu at the bottom "
                "of the sidebar): LCX Services emails are signed with them, never with the project's own name.")
# The owner, 2026-10-13 ("sign with the approver's name"): LCX Clipping sends from its own pool mailboxes but signs
# each email with the approver's name and title (outreach.sign_as "approver"), so the same guard holds there
NEEDS_SIGNER_ANY = ("Set your name and title in your profile first (Your name and title, in the account menu at the "
                    "bottom of the sidebar): this project's emails are signed with them, never with the project's own "
                    "name.")


def signs_by_person(segment, cfg=None):
    """Is every email of this project signed by the person who approves it, never by the project's own sender?
    LCX Services (it pitches one service per lead), and any project with outreach.sign_as "approver"."""
    return sells_services(segment) or (cfg or {}).get("sign_as") == "approver"


def needs_signer(segment):
    return NEEDS_SIGNER if sells_services(segment) else NEEDS_SIGNER_ANY


def long_subjects(cur, ids, cfg):
    """[{id, reason}] for the drafts among `ids` whose subject is over outreach.subject_max_words. The owner,
    2026-10-13: "subject for all emails for all services should be less than 5 or equal to 5 words". The draft step
    keeps new drafts inside it (tools/draft_render.capped_subject); this keeps one drafted before then, or given a
    longer subject by hand, from being approved, so a longer subject never ships. Universal (no cap): nothing."""
    cap = (cfg or {}).get("subject_max_words")
    if not cap or not ids:
        return []
    dr = _render()
    cur.execute("select id, subject from outreach where id = any(%s::uuid[]) and status = 'drafted'", (list(ids),))
    out = []
    for r in cur.fetchall():
        n = dr.subject_words(r["subject"] or "")
        if n > int(cap):
            out.append({"id": str(r["id"]),
                        "reason": "its subject is %d words, and a subject is at most %d: shorten the subject, or wait "
                                  "for the email to be drafted again" % (n, int(cap))})
    return out


def project_signoff(body, cfg, person):
    """Why `body` would still go out signed by the project rather than by `person`, or None."""
    dr = _render()
    canon, mine = dr.footer_for(cfg), dr.footer_for(cfg, person.get("name"), person.get("title"))
    if canon == mine:
        return None                       # the person's name and title are the project's own
    project = ((cfg.get("sender") or {}).get("name") or "").strip()
    if (canon and canon in (body or "")) or (project and project != (person.get("name") or "").strip()
                                             and any(ln.strip() == project for ln in (body or "").splitlines())):
        return ("its sign-off still reads %s, the project's name, not your name and title, so it would not go out "
                "signed by you. Put the footer back as it was drafted, or end the email with your own name and title."
                % (project or "the project's sender"))
    return None


def _mailbox_store():
    import sys
    p = os.path.join(REPO, "tools")
    if p not in sys.path:
        sys.path.insert(0, p)
    import mailbox_store
    return mailbox_store


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
    shown = {"name": sender.get("name", "") or "",
             "title": sender.get("title", "") or "",
             "postal_address": sender.get("postal_address", "") or ""}
    if sender.get("company"):
        # LCX Services (2026-10-13): the project's company on the title line, {{sender_company}}, for the preview
        shown["company"] = sender["company"]
    # a project with no company of its own is not offered {{sender_company}}: it would always read as nothing
    fields = [f for f in dr.FOOTER_FIELDS if f != "sender_company" or sender.get("company")]
    return {"text": text, "fields": fields,
            "sender": shown,
            "problems": dr.validate_footer(text, sender),
            "drafts_pending": pending}


@app.get("/api/outreach/{oid}")
def outreach_detail(oid: str, request: Request, segment: str = Depends(current_segment)):
    """An exact email, independent of the folder's filters or current page."""
    oid = _id(oid, "email")
    with cursor() as cur:
        cur.execute(_outreach_select() +
                    " where f.id = %s and e.segment_id = (select id from segments where slug = %s)",
                    (oid, segment))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "no such email")
        cfg = _policy().outreach_config(cur, segment)
    return _present_outreach([dict(row)], request, segment, cfg)[0]


@app.post("/api/outreach/footer")
def footer_set(body: dict = Body(...), segment: str = Depends(current_segment)):
    """Save the footer and the sender it names.

    A postal address is optional, and the default footer omits it (owner,
    2026-10-09); no opt-out line is required (owner, 2026-10-13: removed from
    every footer).

    Drafts waiting for approval get the new footer too: they cannot be approved
    with a footer that still says SET_ME. Only the footer is swapped, and a draft
    somebody edited at the end by hand is left exactly as they left it --
    rebuilding it would throw their words away."""
    dr, pol = _render(), _policy()
    b = body or {}
    text = dr.clean_text((b.get("text") or "").strip(), remove_offer=False)
    given = b.get("sender") or {}
    with cursor() as cur:
        old = pol.outreach_config(cur, segment)
        sender = dict(old.get("sender") or {})
        for k in ("name", "title", "postal_address"):
            if k in given:
                sender[k] = dr.clean_text((given.get(k) or "").strip(), remove_offer=False)
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
    current sign-off. The swap is by suffix, not by re-rendering the whole email:
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
def mailboxes_state(request: Request, segment: str = Depends(current_segment)):
    """The segment's sending mailboxes: cap for today (warm-up included), sends
    today, room left, and whether this server can send from each (connected:
    its address and Gmail token are set here). Addresses are the ones recorded
    on sent email; the credentials themselves are never shown.

    Where emails go out from the approver's own Gmail (owner, 2026-09-26): every person, each of their
    addresses with today's use of its own limit, and how many of their approvals are waiting."""
    import datetime as _dt
    pol = _policy()
    with cursor() as cur:
        cfg = pol.outreach_config(cur, segment)
        if cfg.get("send_from") == "approver":
            return _approver_mailboxes(cur, cfg, segment, getattr(request.state, "user", None) or "")
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
        scheduled = _scheduled_by_day(cur, segment, _wcfg(cfg))
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
            # with a sending window: the approved emails by the day they go out, on India's clock
            "scheduled": scheduled,
            "limit_today": min(segment_cap, sum(int(r.get("cap_today") or 0) for r in out if r.get("enabled"))),
            "resets_at": _dt.datetime.combine(now.date() + _dt.timedelta(days=1), _dt.time(0),
                                              tzinfo=_dt.timezone.utc).isoformat(),
            "can_send": any(r["connected"] for r in out) and not pol.sending_paused(cfg)}


def _scheduled_by_day(cur, segment, wcfg, by_approver=False):
    """Approved emails that hold a time, counted by the day they go out on the sender's clock (India):
    [{day, label "Tue 14 Oct", count}], or {approver: [...]}. Empty without a window. The Outreach page's
    counters say from it when the waiting ones go, instead of guessing from today's room."""
    if not wcfg:
        return {} if by_approver else []
    from zoneinfo import ZoneInfo
    sw = _sw()
    tz = ZoneInfo(wcfg["sender_timezone"])
    cur.execute("select lower(o.approved_by) as who, o.send_after from outreach o join entities e on e.id = o.entity_id"
                " where e.segment_id = (select id from segments where slug = %s) and o.direction = 'outbound'"
                "   and o.status = 'approved' and o.send_error is null and o.send_after is not null", (segment,))
    groups = {}
    for r in cur.fetchall():
        day = sw._utc(r["send_after"]).astimezone(tz).date()
        g = groups.setdefault(r["who"] if by_approver else None, {})
        g[day] = g.get(day, 0) + 1

    def days(g):
        return [{"day": d.isoformat(), "label": sw.day_label(d), "count": n} for d, n in sorted(g.items())]
    if by_approver:
        return {k: days(g) for k, g in groups.items()}
    return days(groups.get(None, {}))


def _approver_mailboxes(cur, cfg, segment, me):
    import datetime as _dt
    store = _mailbox_store()
    boxes = store.mailboxes(cur)
    cur.execute("select email, name from app_users order by lower(coalesce(name, email))")
    people = [dict(r) for r in cur.fetchall()]
    cur.execute("select lower(o.approved_by) as who, count(*) as n from outreach o join entities e on e.id = o.entity_id"
                " where e.segment_id = (select id from segments where slug = %s) and o.direction = 'outbound'"
                "   and o.status = 'approved' and o.send_error is null group by 1", (segment,))
    waiting = {r["who"]: int(r["n"]) for r in cur.fetchall()}
    paused = _policy().sending_paused(cfg)
    by_day = _scheduled_by_day(cur, segment, _wcfg(cfg), by_approver=True)
    keep = ("id", "address", "daily_cap", "sent_today", "out_today", "remaining", "usable", "last_error")
    accounts = []
    for p in people:
        mine = []
        for b in boxes:
            if b["user_email"].lower() != p["email"].lower():
                continue
            row = {k: b[k] for k in keep}
            # this project's From through it (sql/36): its LCX alias for LCX Services. An account with no alias
            # on the project's domain cannot send for it, and says so (no_alias)
            row["sends_as"] = _sends_as(b, cfg)
            if row["sends_as"] is None:
                row.update(usable=False, no_alias=cfg.get("send_as_domain"))
            elif cfg.get("send_as_domain") and store.alias_for(b, cfg["send_as_domain"]) == store.UNREAD:
                row["alias_unread"] = cfg["send_as_domain"]      # looked up in that Gmail at its first send
            mine.append(row)
        accounts.append({"email": p["email"], "name": p["name"] or p["email"].split("@")[0],
                         "me": p["email"].lower() == me.lower(), "mailboxes": mine,
                         "approved_waiting": waiting.get(p["email"].lower(), 0),
                         # their approvals with a time, by the day they go out (India's clock)
                         "scheduled": by_day.get(p["email"].lower(), [])})
    accounts.sort(key=lambda a: (not a["me"], a["name"].lower()))           # yours first
    mine = next((a for a in accounts if a["me"]), {"mailboxes": [], "approved_waiting": 0})
    now = _dt.datetime.now(_dt.timezone.utc)
    return {"mode": "approver", "paused": paused, "accounts": accounts,
            "approved_waiting": sum(waiting.values()),
            "resets_at": _dt.datetime.combine(now.date() + _dt.timedelta(days=1), _dt.time(0),
                                              tzinfo=_dt.timezone.utc).isoformat(),
            "can_send": not paused and any(b["usable"] for b in mine["mailboxes"]),
            # the old single-counter fields, so a page from before this change still shows something true
            "sent_today": sum(b["sent_today"] for b in mine["mailboxes"]),
            "limit_today": sum(b["daily_cap"] for b in mine["mailboxes"] if b["usable"]) or None,
            "segment_cap": None, "rotation": False, "mailboxes": []}


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
            out[qname] = rows if qname in ("by_source", "by_account") else (rows[0] if rows else {})
    people = _people()
    for r in out.get("by_account") or []:
        r["name"] = _display(r.get("account"), people)
    return out


@app.get("/api/health")
def health():
    try:
        with cursor() as cur:
            cur.execute("select 1 as ok")
            cur.fetchone()
        return {"ok": True, "release": os.environ.get("RENDER_GIT_COMMIT", "local"), "sourcing_version": 3}
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

import universal as _universal_module          # the Apollo search page (Universal, LCX Services)
app.include_router(_universal_module.build_router(
    cursor, allowed=(lambda: SEGMENTS_ALLOWED) if SEGMENTS_ALLOWED else None))

import mailbox_connect as _mailbox_connect_module   # each person's Gmail: connected in the app, or linked by the owner
app.include_router(_mailbox_connect_module.build_router(cursor))

import api_v1 as _api_v1_module                # the API (/api/v1) and MCP server (/mcp), with each person's keys
app.include_router(_api_v1_module.build_router(_sys.modules[__name__]))

import oauth as _oauth_module                  # signing an MCP client in (claude.ai's custom connectors)
app.include_router(_oauth_module.build_router(cursor))

import team_report as _team_report_module      # Reports, Team: what each person sent, and how it was answered
app.include_router(_team_report_module.build_router(
    cursor, current_segment, lambda: {s["slug"]: s["project_name"] for s in segments_list(None)["segments"]}))

# ---------------------------------------------------------------- scheduler
import scheduler as _sched_module
_scheduler = _sched_module.Scheduler(cursor, _ops_module, SEGMENT,
                                     allowed=SEGMENTS_ALLOWED or None)


@app.on_event("startup")
def _start_scheduler():
    # The zone data the sending window reads (tzdata, requirements.txt). Without it every email would go at
    # the fallback zone's 10:00, so a server missing it does not start: the deploy's health check fails and
    # the running version stays up (RuntimeError "time-zone data missing: pip install tzdata").
    _sw().self_check()
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
        # The latest Gmail refusal a send handled, in the last day (second review, 2026-10-12). Such a run ends
        # OK -- it moved that address's emails and the others carried on -- and with no alert webhook set an "OK"
        # alone showed Operations green day after day while an address stayed refused. Its send_outreach step is
        # the only OK one with a detail: what was refused (app/scheduler.py _refusal_note)
        cur.execute(
            "select detail, started_at from pipeline_runs where coalesce(segment, %s) = %s and step = 'send_outreach'"
            " and status = 'ok' and detail is not null and started_at > now() - interval '24 hours'"
            " order by started_at desc limit 1", (SEGMENT, segment))
        f = cur.fetchone()
        refused = {"detail": f["detail"], "at": f["started_at"].isoformat()} if f else None
    # whether the timed sender runs in this server (review, 2026-10-12): off, a project with a sending window
    # sends only at the fifteen-minute ticks and most of each window moves to the next weekday
    return {"schedule": _scheduler.schedule(segment),
            "webhook_configured": bool(_scheduler.alert_webhook()),
            "send_loop": _scheduler.send_loop_state(),
            "refused": refused,
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



@app.get("/privacy")
def privacy_page():
    # public: Google's consent screen for connecting a Gmail links here (owner, 2026-10-14). Self-contained,
    # like the login page, so nothing else needs to be on the public side of the wall.
    from fastapi.responses import HTMLResponse
    html = io.open(os.path.join(HERE, "static", "privacy.html"), encoding="utf-8").read()
    return HTMLResponse(html)


@app.get("/login")
def login_page():
    from fastapi.responses import HTMLResponse
    html = io.open(os.path.join(HERE, "static", "login.html"),
                   encoding="utf-8").read()
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------------- the demo (DEMO_PATHS, above)
def _demo_version():
    return str(int(max(os.path.getmtime(os.path.join(HERE, f)) for f, _ in DEMO_FILES.values())))


@app.get("/demo")
def demo_page():
    """The app's own page, with the pretend /api in front of it: every call it makes is answered in the browser,
    from made-up data. Nothing here reads the database, and no session is made."""
    import json as _json
    from fastapi.responses import HTMLResponse
    if not DEMO_ON:
        raise HTTPException(404, "not found")
    v = _demo_version()
    conf = {"demo": True, "fixtures": "/demo/data.json?v=" + v, "docs": "/demo/docs.html?v=" + v,
            "badge": "Demo · made-up data · nothing is saved or sent", "signin": "/login"}
    html = io.open(os.path.join(HERE, "static", "index.html"), encoding="utf-8").read()
    html = (html.replace('href="style.css"', 'href="/demo/style.css?v=%s"' % v)
                .replace('<script src="app.js"></script>',
                         '<script>window.__MOCK__ = %s;</script>\n<script src="/demo/mock.js?v=%s"></script>\n'
                         '<script src="/demo/app.js?v=%s"></script>' % (_json.dumps(conf), v, v)))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/demo/app.js")
@app.get("/demo/style.css")
@app.get("/demo/mock.js")
@app.get("/demo/data.json")
def demo_file(request: Request):
    if not DEMO_ON:
        raise HTTPException(404, "not found")
    rel, media = DEMO_FILES[request.scope["path"]]
    return FileResponse(os.path.join(HERE, rel), media_type=media, headers={"Cache-Control": "public, max-age=3600"})


_DEMO_PROJECTS = """<h2 id="projects">Projects</h2>
<p>The demo has two made-up projects; the tool itself has one per kind of lead, each with its own email.</p>
<table>
  <thead><tr><th>Project</th><th>Who it finds</th><th>How the email is made</th></tr></thead>
  <tbody>
    <tr><td><strong>Podcast Partnerships</strong></td><td>Podcasts and video shows with a back catalogue. The host is
      the face of the lead.</td><td>Drafted from the project's templates, with a line of the show's own numbers. Batch
      approval with a spot check.</td></tr>
    <tr><td><strong>Company Search</strong></td><td>Anyone you search for on Apollo yourself (in the demo, a pretend
      Apollo with made-up people).</td><td>You write the email (Write email), for the leads you pick.</td></tr>
  </tbody>
</table>

"""
# the real projects and the business, as the demo's Docs speak of them (longest first)
_DEMO_WORDS = (("TVF, LCX or another domain", "any domain"), ("US Production Houses", "the production-company project"),
               ("LCX Clipping", "Podcast Partnerships"), ("LCX Services'", "the services project's"),
               ("LCX Services", "the services project"), ("Startup Acquisition Targets", "the startup project"),
               ("The Viral Fever", "Demo Studio"), ("ReelForge", "the project's"), ("TVF's", "the studio's"),
               ("LCX's", "the studio's"), ("TVF", "the studio"), ("LCX", "the studio"))


@app.get("/demo/docs.html")
def demo_docs():
    """The Docs page for the demo: the projects it has, no names of the real ones, and no one's address."""
    from fastapi.responses import HTMLResponse
    if not DEMO_ON:
        raise HTTPException(404, "not found")
    html = io.open(os.path.join(HERE, "static", "docs.html"), encoding="utf-8").read()
    html = re.sub(r'<h2 id="projects">.*?(?=<h2 )', lambda m: _DEMO_PROJECTS, html, count=1, flags=re.S)
    for real, said in _DEMO_WORDS:
        html = html.replace(real, said)
    html = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                  lambda m: m.group(0) if m.group(0).lower().endswith(".example") else "someone@example.com", html)
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600"})


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
