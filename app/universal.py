#!/usr/bin/env python3
"""universal.py -- the Universal page's API: Apollo search, reveal-and-save, saved searches.

    GET    /api/universal/status             is Apollo connected, credits left, the filters
    POST   /api/universal/search             one page of people (0 credits) or companies (1 credit)
    POST   /api/universal/save               people: reveal then save (1 credit each); companies: save
    GET    /api/universal/searches           saved searches
    POST   /api/universal/searches           save one (a name already taken is updated)
    DELETE /api/universal/searches/{id}      delete one

A project has this page when its config says ui.search_page "apollo": Universal,
and since 2026-10-06 LCX Services. The page names its project on every call
(?project=<slug>) and everything saved goes there -- never to a project without
the page, so a save cannot land in another project's pool by accident, and a
second tab switched to another project does not move this tab's saves with it.
A call that names none (a page loaded before 2026-10-06) is for the cookie's
project when it has the page, and otherwise for Universal, as before.

Apollo is called outside any database transaction. A reveal of 100 people is
ten API calls; holding a connection open across them would starve the pool.
The Apollo client is tools/apollo.py; what a save writes is tools/apollo_store.py.
"""
import os
import sys
import threading
import time

from fastapi import APIRouter, Body, HTTPException, Request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import apollo  # noqa: E402
import apollo_store  # noqa: E402

SLUG = "universal"                 # the project a call that names none falls back to
_STATUS = {"at": 0.0, "value": None}
_LOCK = threading.Lock()
# seconds: the status panel costs two Apollo calls (0 credits, but rate-limited, and ~3 s). The credits are
# refreshed right after anything that spends one (a company page, a reveal), so 5 minutes loses nothing.
STATUS_TTL = 300


def _apollo_http(e):
    """An ApolloError as the HTTP error the page shows."""
    msg = str(e)
    if e.status == 429:
        wait = " Try again in %d seconds." % e.retry_after if e.retry_after else ""
        return HTTPException(429, msg.rstrip() + wait)
    if e.code == "NO_KEY":
        return HTTPException(409, msg)
    if e.status in (401, 403, 422):
        return HTTPException(400, msg)
    return HTTPException(502, msg)


def has_page(cfg):
    """Does this project search Apollo for its leads? (ui.search_page)"""
    return ((cfg or {}).get("ui") or {}).get("search_page") == "apollo"


def build_router(cursor, allowed=None):
    """allowed: the project slugs this deployment serves (SEGMENTS_ALLOWED), or None for any."""
    r = APIRouter()

    def segment(cur, request):
        named = (request.query_params.get("project") or "").strip()
        want = [named] if named else [getattr(request.state, "segment", None), SLUG]
        for slug in dict.fromkeys(s for s in want if s):
            if allowed is not None and slug not in allowed():
                continue
            cur.execute("select id, config from segments where slug = %s and is_active", (slug,))
            row = cur.fetchone()
            if row and has_page(row["config"]):
                return row["id"], row["config"] or {}
        if named:
            raise HTTPException(404, "this project does not search Apollo for its leads")
        raise HTTPException(404, "the Universal project is not set up: run sql/03e_segment_universal.sql")

    def status(force=False):
        with _LOCK:
            # a check Apollo could not answer (busy, timed out) is asked again soon, not in five minutes
            ttl = STATUS_TTL if (_STATUS["value"] or {}).get("connected") is not None else 20
            if force or time.monotonic() - _STATUS["at"] > ttl or _STATUS["value"] is None:
                _STATUS["value"] = apollo.status()
                _STATUS["at"] = time.monotonic()
            return _STATUS["value"]

    @r.get("/api/universal/status")
    def universal_status(request: Request):
        with cursor() as cur:
            _, cfg = segment(cur, request)
        a = cfg.get("apollo") or {}
        return {"apollo": status(),
                "max_reveal_per_save": int(a.get("max_reveal_per_save") or 100),
                "endpoints": a.get("endpoints") or [],
                "filters": apollo.FILTERS}

    @r.post("/api/universal/search")
    def universal_search(request: Request, body: dict = Body(...)):
        b = body or {}
        kind = b.get("kind")
        # a page of companies costs one credit whatever its size, so it is always a full page;
        # people are free and come in the project's page size
        with cursor() as cur:
            _, cfg = segment(cur, request)
        people_per = int((cfg.get("apollo") or {}).get("per_page") or 25)
        q_text = (b.get("filters") or {}).get("q_text")
        suggestion = apollo.did_you_mean(q_text) if kind in ("people", "companies") else None
        if kind == "companies" and suggestion and not b.get("as_typed"):
            # a page of companies costs a credit whatever it finds, so a likely typo is asked about first
            # and Apollo is not called (owner, 2026-09-21: "UAE Restraunts" found nothing and cost one)
            return {"companies": [], "total": 0, "page": 1, "total_pages": 0, "held": True,
                    "did_you_mean": suggestion, "read_as": ""}
        try:
            if kind == "people":
                out = apollo.search_people(b.get("filters") or {}, b.get("page") or 1, people_per)
            elif kind == "companies":
                out = apollo.search_companies(b.get("filters") or {}, b.get("page") or 1, apollo.MAX_PER_PAGE)
            else:
                raise HTTPException(400, "search people or companies")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except apollo.ApolloError as e:
            raise _apollo_http(e)
        with cursor() as cur:
            seg_id, _ = segment(cur, request)
            if kind == "people":
                have = apollo_store.saved_person_ids(cur, seg_id, [p["id"] for p in out["people"]])
                for p in out["people"]:
                    p["saved"] = p["id"] in have
            else:
                have = apollo_store.saved_company_ids(cur, seg_id, [c["id"] for c in out["companies"]])
                for c in out["companies"]:
                    c["saved"] = have.get(c["id"])          # the lead's status, or None
        if kind == "companies":
            status(force=True)                              # a page of companies cost a credit
        # how the search bar's words were read ("companies tagged "arcade" or "arcades", based in United
        # States"), so the page can say what was searched rather than leave the reading hidden
        bar, out["read_as"] = apollo.read_search_text(kind, q_text, panel=b.get("filters") or {})
        # no job typed: the decision makers were searched, and the page offers everyone instead (free)
        out["decision_makers"] = "person_seniorities" in bar
        out["did_you_mean"] = suggestion                    # shown beside an empty result: free to try
        return out

    @r.post("/api/universal/save")
    def universal_save(request: Request, body: dict = Body(...)):
        b = body or {}
        kind = b.get("kind")
        user = getattr(request.state, "user", None) or "unknown"
        filters = b.get("filters") or {}
        try:
            summary = apollo.describe(kind, filters) if kind in ("people", "companies") else ""
        except Exception:
            summary = ""
        saved_from = {"kind": kind, "summary": summary, "at": apollo_store.now_iso(), "by": user}
        with cursor() as cur:
            seg_id, cfg = segment(cur, request)
        rule = cfg.get("self_exclusion") or {}
        cap = int((cfg.get("apollo") or {}).get("max_reveal_per_save") or 100)

        if kind == "people":
            ids = [str(i) for i in dict.fromkeys(b.get("ids") or [])]
            if not ids:
                raise HTTPException(400, "tick at least one person")
            if len(ids) > cap:
                raise HTTPException(400, "up to %d people in one save (%d ticked)" % (cap, len(ids)))
            with cursor() as cur:
                already = apollo_store.saved_person_ids(cur, seg_id, ids)
            todo = [i for i in ids if i not in already]
            revealed = {"people": [], "missing": [], "credits": 0.0, "error": None, "unrevealed": []}
            if todo:
                try:
                    revealed = apollo.reveal_people(todo)
                except apollo.ApolloError as e:
                    raise _apollo_http(e)
            # "at most N per company" is applied on the page, before this call: here it would come
            # after the reveal, and the people it dropped would already have cost a credit each
            with cursor() as cur:
                rep = apollo_store.save_people(cur, seg_id, revealed["people"], rule, saved_from)
            rep.update(already_saved=len(already), not_found=len(revealed["missing"]),
                       credits=revealed["credits"], requested=len(ids),
                       error=revealed.get("error"), unrevealed=len(revealed.get("unrevealed") or []))
            status(force=True)
            return rep

        if kind == "companies":
            rows = [apollo.org_row(o) for o in (b.get("companies") or []) if isinstance(o, dict)]
            rows = [o for o in rows if o.get("name") and apollo._ID.match(str(o.get("id") or ""))]
            if not rows:
                raise HTTPException(400, "tick at least one company")
            if len(rows) > 100:
                raise HTTPException(400, "up to 100 companies in one save")
            with cursor() as cur:
                rep = apollo_store.save_companies(cur, seg_id, rows, rule, saved_from)
            rep.update(requested=len(rows), credits=0)
            return rep
        raise HTTPException(400, "save people or companies")

    # ------------------------------------------------------------ saved searches
    @r.get("/api/universal/searches")
    def searches_list(request: Request):
        with cursor() as cur:
            seg_id, _ = segment(cur, request)
            cur.execute("select id, name, kind, filters, created_by, updated_at from saved_searches"
                        " where segment_id = %s order by lower(name)", (seg_id,))
            rows = [dict(x) for x in cur.fetchall()]
        for x in rows:
            x["id"] = str(x["id"])
            x["updated_at"] = x["updated_at"].isoformat() if x["updated_at"] else None
            x["summary"] = apollo.describe(x["kind"], x["filters"] or {})
        return {"searches": rows}

    @r.post("/api/universal/searches")
    def searches_save(request: Request, body: dict = Body(...)):
        b = body or {}
        name = " ".join(str(b.get("name") or "").split())[:80]
        kind = b.get("kind")
        filters = b.get("filters") or {}
        if not name:
            raise HTTPException(400, "give the search a name")
        if kind not in ("people", "companies"):
            raise HTTPException(400, "save a people or a company search")
        try:
            apollo.build_query(kind, filters)            # only a search Apollo would accept is kept
        except ValueError as e:
            raise HTTPException(400, str(e))
        import json
        user = getattr(request.state, "user", None) or "unknown"
        with cursor() as cur:
            seg_id, _ = segment(cur, request)
            cur.execute(
                "insert into saved_searches (segment_id, name, kind, filters, created_by) values (%s, %s, %s, %s::jsonb, %s)"
                " on conflict (segment_id, lower(name)) do update set kind = excluded.kind, filters = excluded.filters,"
                " updated_at = now() returning id", (seg_id, name, kind, json.dumps(filters), user))
            sid = str(cur.fetchone()["id"])
        return {"ok": True, "id": sid, "name": name}

    @r.delete("/api/universal/searches/{search_id}")
    def searches_delete(request: Request, search_id: str):
        with cursor() as cur:
            seg_id, _ = segment(cur, request)
            cur.execute("delete from saved_searches where id::text = %s and segment_id = %s returning id",
                        (search_id, seg_id))
            if not cur.fetchone():
                raise HTTPException(404, "no such saved search")
        return {"ok": True}

    return r
