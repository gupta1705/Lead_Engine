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
import base64
import hashlib
import hmac
import json
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
import apollo_policy as policy  # noqa: E402

SLUG = "universal"                 # the project a call that names none falls back to
_STATUS = {"at": 0.0, "value": None}
_LOCK = threading.Lock()
# seconds: the status panel costs two Apollo calls (0 credits, but rate-limited, and ~3 s). The credits are
# refreshed right after anything that spends one (a company page, a reveal), so 5 minutes loses nothing.
STATUS_TTL = 300


def _receipt(seg_id, cfg, kind, row, filters, user):
    """Carry the server's Apollo answer to save, without trusting browser-supplied facts."""
    from app.auth import _secret
    payload = {"segment": str(seg_id), "config": _policy_hash(cfg), "kind": kind, "row": row,
               "filters": filters, "user": user, "expires": int(time.time()) + 7200}
    data = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode()
    return data + "." + hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()


def _policy_hash(cfg):
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def _read_receipt(token, seg_id, cfg, kind, user):
    from app.auth import _secret
    try:
        data, signature = str(token).rsplit(".", 1)
        expected = hmac.new(_secret(), data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(data))
        if (payload["segment"] != str(seg_id) or payload["config"] != _policy_hash(cfg)
                or payload["kind"] != kind or payload["user"] != user or payload["expires"] < time.time()):
            raise ValueError()
        return payload
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, "Search again before saving: the result is missing, expired, or the project constraints changed.")


def _qualified(cur, seg_id, candidate, cfg):
    """Use the same score, site and country eligibility as automatic contact enrichment."""
    import enrich_apollo as ea
    block = ea.enrich_block(cfg)
    sql = "select e.id,e.name,e.domain,e.metadata from entities e where e.segment_id=%s and lower(e.name)=lower(%s) and e.status=any(%s)"
    args = [seg_id, candidate.get("company") or "", ea.OPEN_STATUSES]
    cutoff = (ea.dt.datetime.now(ea.dt.timezone.utc) - ea.dt.timedelta(days=block["stale_days"])).isoformat()
    sql += " and coalesce(e.metadata->>'apollo_checked_at','') < %s"
    args.append(cutoff)
    if block["score_over"] is not None:
        sql += " and coalesce(e.fit_score,0)>%s"
        args.append(block["score_over"])
    if block["site_read"]:
        sql += ea.SITE_READ_SQL
    if block["reveal_countries"]:
        sql += " and upper(trim(coalesce(e.metadata->>'hq_country','')))=any(%s)"
        args.append(ea.country_forms(block["reveal_countries"]))
    cur.execute(sql, args)
    rows = cur.fetchall()
    return rows[0] if len(rows) == 1 else None


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


def _spend(cursor, seg_id, kind, credits, ref):
    """Credits spent from this page, into the ledger (tools/apollo_budget.py), in a transaction of their own
    and before anything else is done with what was bought, so a save that fails afterwards cannot take the
    record of the spend with it. A missing ledger table never fails the search or the save paid for."""
    import apollo_budget
    try:
        with cursor() as cur:
            apollo_budget.record_by_id(cur, seg_id, kind, credits, ref)
    except Exception:                                   # noqa: BLE001
        pass


def _budget(cursor, seg_id, cfg, status, need):
    """A project with a stated Apollo budget (LCX Services: enrichment.credits_per_week, keep_in_reserve)
    spends from this page inside it, the same week the weekly runs count. -> None when `need` credits fit,
    else what to tell the person. A project without one (Universal) is not checked, as before."""
    import apollo_budget
    block = (cfg or {}).get("enrichment") or {}
    if policy.strict(cfg) and (block.get("enabled") is not True or block.get("provider") != "apollo"):
        return "Apollo spending is disabled for this project."
    if not apollo_budget.capped(block):
        return None
    left = ((status() or {}).get("credits") or {}).get("lead_credits_left")
    with cursor() as cur:
        n, why = apollo_budget.allowance(cur, None, block, left, segment_id=seg_id)
    if n >= need:
        return None
    return ("this project's Apollo budget has %d credit(s) left now (set by %s), and this needs %d: "
            "the owner sets the budget in the project's config" % (max(0, n), why, need))


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
        definitions = list(apollo.FILTERS)
        if policy.strict(cfg) and policy.searches(cfg):
            auds = {a["key"]: a.get("label", a["key"]) for a in cfg.get("audiences") or []}
            definitions.insert(0, {"key": policy.TARGET, "label": "Project targeting group", "for": ["people", "companies"],
                "type": "window", "group": "Project", "options": [[s["key"], auds.get(s.get("audience"), s["key"].replace("_", " ")) +
                    (" · " + s["signal"] if s.get("signal") else "")] for s in policy.searches(cfg)],
                "help": "Project geography, size, industry and contact rules apply to every search. Save companies first for qualification."})
        return {"apollo": status(),
                "max_reveal_per_save": min(int(a.get("max_reveal_per_save") or 100),
                    int((cfg.get("enrichment") or {}).get("credits_per_run") or 100)) if policy.strict(cfg) else int(a.get("max_reveal_per_save") or 100),
                "endpoints": a.get("endpoints") or [],
                "project_constraints": policy.strict(cfg), "filters": definitions}

    @r.post("/api/universal/search")
    def universal_search(request: Request, body: dict = Body(...)):
        b = body or {}
        kind = b.get("kind")
        # a page of companies costs one credit whatever its size, so it is always a full page;
        # people are free and come in the project's page size
        with cursor() as cur:
            seg_id, cfg = segment(cur, request)
        try:
            filters, selected = policy.constrained_filters(cfg, kind, b.get("filters") or {})
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        people_per = int((cfg.get("apollo") or {}).get("per_page") or 25)
        q_text = (b.get("filters") or {}).get("q_text")
        suggestion = apollo.did_you_mean(q_text) if kind in ("people", "companies") else None
        if kind == "companies" and suggestion and not b.get("as_typed"):
            # a page of companies costs a credit whatever it finds, so a likely typo is asked about first
            # and Apollo is not called (owner, 2026-09-21: "UAE Restraunts" found nothing and cost one)
            return {"companies": [], "total": 0, "page": 1, "total_pages": 0, "held": True,
                    "did_you_mean": suggestion, "read_as": ""}
        if kind == "companies":
            over = _budget(cursor, seg_id, cfg, status, 1)
            if over:
                raise HTTPException(409, over)
        try:
            if kind == "people":
                out = apollo.search_people(filters, b.get("page") or 1, people_per)
            elif kind == "companies":
                out = apollo.search_companies(filters, b.get("page") or 1, apollo.MAX_PER_PAGE)
            else:
                raise HTTPException(400, "search people or companies")
        except ValueError as e:
            raise HTTPException(400, str(e))
        except apollo.ApolloError as e:
            raise _apollo_http(e)
        if kind == "companies":
            # the page cost a credit: into the ledger first, where the project's weekly cap reads it (sql/33)
            _spend(cursor, seg_id, "company_page", 1, "search page, by hand")
        if policy.strict(cfg):
            user = getattr(request.state, "user", None) or "unknown"
            results = out["people" if kind == "people" else "companies"]
            if kind == "companies":
                results[:] = [row for row in results if not policy.company_reason(row, cfg, selected, filters)]
            for row in results:
                signed_filters = dict(filters)
                if selected:
                    signed_filters[policy.TARGET] = selected["key"]
                row["_receipt"] = _receipt(seg_id, cfg, kind, dict(row), signed_filters, user)
        with cursor() as cur:
            if kind == "people":
                have = apollo_store.saved_person_ids(cur, seg_id, [p["id"] for p in out["people"]], verified_only=policy.strict(cfg))
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
        bar, _ = apollo.read_search_text(kind, q_text, panel=b.get("filters") or {})
        out["read_as"] = apollo.describe(kind, filters)
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
        strict = policy.strict(cfg)
        if strict:
            cap = min(cap, int((cfg.get("enrichment") or {}).get("credits_per_run") or cap))
        receipts = {}
        if strict:
            for token in b.get("receipts") or []:
                payload = _read_receipt(token, seg_id, cfg, kind, user)
                receipts[str(payload["row"]["id"])] = payload

        if kind == "people":
            ids = [str(i) for i in dict.fromkeys(b.get("ids") or [])]
            if not ids:
                raise HTTPException(400, "tick at least one person")
            if len(ids) > cap:
                raise HTTPException(400, "up to %d people in one save (%d ticked)" % (cap, len(ids)))
            with cursor() as cur:
                already = apollo_store.saved_person_ids(cur, seg_id, ids, verified_only=strict)
            todo = [i for i in ids if i not in already]
            if strict and any(i not in receipts for i in todo):
                raise HTTPException(409, "Search again before revealing these people.")
            qualified = {}
            if strict and policy.searches(cfg):
                with cursor() as cur:
                    for pid in todo:
                        row = _qualified(cur, seg_id, receipts[pid]["row"], cfg)
                        if not row:
                            raise HTTPException(409, "Save the company first and let it pass this project's qualification before revealing a contact.")
                        qualified[pid] = row
                        import enrich_apollo as ea
                        roles = ea.roles_for(cfg, (row["metadata"] or {}).get("kind"))
                        block = ea.enrich_block(cfg)
                        if block["strict_roles"] and not ea.pick([receipts[pid]["row"]], roles, strict=True, senior_re=block["senior"])[0]:
                            raise HTTPException(409, "The search result is outside this project's contact roles.")
                        if block["skip_known_elsewhere"]:
                            cur.execute("select 1 from entities where segment_id<>%s and"
                                " (metadata->'apollo_enrich'->>'person'=%s or coalesce(metadata->'apollo_people','{}'::jsonb) ? %s) limit 1",
                                (seg_id, pid, pid))
                            if cur.fetchone():
                                raise HTTPException(409, "This person has already been revealed for another project; no credits spent.")
            revealed = {"people": [], "missing": [], "credits": 0.0, "error": None, "unrevealed": []}
            if todo:
                over = _budget(cursor, seg_id, cfg, status, len(todo))
                if over:
                    raise HTTPException(409, over)
                try:
                    revealed = apollo.reveal_people(todo)
                except apollo.ApolloError as e:
                    raise _apollo_http(e)
                _spend(cursor, seg_id, "reveal", revealed.get("credits") or 0, "search page, by hand")
            # "at most N per company" is applied on the page, before this call: here it would come
            # after the reveal, and the people it dropped would already have cost a credit each
            rejected, accepted = [], []
            for person in revealed["people"]:
                why = None
                receipt = receipts.get(str(person.get("apollo_id")))
                if strict:
                    if not receipt:
                        why = "Apollo returned a different person"
                    elif not policy.verified(person):
                        why = "Apollo did not verify the work email"
                    else:
                        selected = policy.target(cfg, receipt["filters"])
                        why = policy.company_reason(person.get("organization") or {}, cfg, selected, receipt["filters"])
                        import enrich_apollo as ea
                        employer = qualified.get(str(person.get("apollo_id")))
                        candidate = receipt["row"]
                        org = person.get("organization") or {}
                        if employer and not ea.same_company(person, employer["domain"]):
                            why = "Current employer differs from the qualified company"
                        elif candidate.get("company_id") and org.get("id") != candidate["company_id"]:
                            why = "Current employer differs from the search result"
                        elif candidate.get("company_domain") and not ea.same_company(person, candidate["company_domain"]):
                            why = "Current employer differs from the search result"
                        elif not ea.works_at({"company": org.get("name")}, candidate.get("company")):
                            why = "Current employer differs from the search result"
                        roles = ea.roles_for(cfg, (employer["metadata"] or {}).get("kind") if employer else policy.audience(cfg, selected).get("key"))
                        if roles and not ea.pick([dict(person, has_email=True)], roles, strict=True,
                                                 senior_re=ea.enrich_block(cfg)["senior"])[0]:
                            why = "Current title is outside the project's contact roles"
                if why:
                    rejected.append({"name": person.get("name"), "why": why})
                else:
                    accepted.append(person)
            with cursor() as cur:
                rep = apollo_store.save_people(cur, seg_id, accepted, rule, saved_from)
                if qualified:
                    touched = [str(row["id"]) for pid, row in qualified.items()
                               if pid not in (revealed.get("unrevealed") or [])]
                    if touched:
                        cur.execute("update entities set metadata=metadata || jsonb_build_object('apollo_checked_at',%s::text), updated_at=now() where id=any(%s::uuid[])",
                                    (apollo_store.now_iso(), touched))
            rep["skipped"].extend(rejected)
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
            if strict:
                if any(str(row["id"]) not in receipts for row in rows):
                    raise HTTPException(409, "Search again before saving these companies.")
                rows = [receipts[str(row["id"])]["row"] for row in rows]
            with cursor() as cur:
                rep = {"saved": 0, "companies_created": 0, "companies_updated": 0, "skipped": [], "saved_ids": []}
                for row in rows:
                    origin = dict(saved_from)
                    if strict and policy.searches(cfg):
                        context = receipts[str(row["id"])]["filters"]
                        selected = policy.target(cfg, context)
                        aud = policy.audience(cfg, selected)
                        origin["project_target"] = {"kind": aud.get("key") or cfg.get("entity_type"),
                            "apollo_search": {"key": selected["key"], "signal": selected.get("signal"),
                                "signal_seen_at": apollo_store.now_iso() if selected.get("signal") else None},
                            "qualification_pending": True}
                    result = apollo_store.save_companies(cur, seg_id, [row], rule, origin)
                    for key in rep:
                        rep[key] += result[key]
            rep.update(requested=len(rows), credits=0)
            if strict and policy.searches(cfg):
                rep["saved_status"] = "discovered"
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
        import json
        user = getattr(request.state, "user", None) or "unknown"
        with cursor() as cur:
            seg_id, cfg = segment(cur, request)
            try:
                policy.constrained_filters(cfg, kind, filters)
            except (ValueError, TypeError) as e:
                raise HTTPException(400, str(e))
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
