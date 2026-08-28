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

_POOL = None

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


@contextmanager
def cursor():
    global _POOL
    if _POOL is None:
        _POOL = pgpool.ThreadedConnectionPool(1, 8, db_url(), connect_timeout=20)
    conn = _POOL.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _POOL.putconn(conn)


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
def export(status: str = "shortlisted"):
    """The owner's 17-column sheet, generated live from the current selection."""
    import subprocess
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "tvf_leads_export.xlsx")
    if os.path.exists(tmp):
        os.remove(tmp)
    r = subprocess.run(
        ["python", os.path.join(REPO, "tools", "export_leads.py"),
         "-o", tmp, "--status", status],
        capture_output=True, text=True, cwd=REPO)
    if not os.path.exists(tmp):
        raise HTTPException(500, "export failed: " + ((r.stderr or r.stdout)[-400:]))
    return FileResponse(
        tmp, filename="TVF_leads.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/health")
def health():
    try:
        with cursor() as cur:
            cur.execute("select 1 as ok")
            cur.fetchone()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(503, "database unreachable: " + type(e).__name__)


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True),
          name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
