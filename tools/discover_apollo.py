#!/usr/bin/env python3
"""Apollo discovery for each project's saved constraints; clipping keeps its own harvests.

Uses the existing persisted search cursors, dedupe and credit ledger. --dry-run
only makes free checks and never advances a cursor, reveals a person or buys a page.
"""
import argparse
import json
import os
import re
import time

import apollo
import apollo_budget
import apollo_store
import discover_lcx_services as discovery
from dbconn import Db

SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")


def company_row(org, sl, aud, cfg, today=None):
    """Apollo facts only: partnership fit and distress still require qualification."""
    if cfg.get("judge", {}).get("enabled"):
        return discovery.apollo_row(org, sl, aud, cfg, today)
    name = str(org.get("name") or "").strip()
    _, domain = discovery.website(org.get("primary_domain") or org.get("website_url"), cfg)
    if not name or not domain or not org.get("id"):
        return None, "missing company name, Apollo id or own website"
    if apollo_store.excluded({"name": name, "primary_domain": domain}, cfg.get("self_exclusion") or {}):
        return None, "TVF or an affiliate"
    iso = sl["country"]["iso"].upper()
    actual_country = str(org.get("country") or "").strip().lower()
    allowed = {"US": {"us", "usa", "united states", "united states of america"},
               "IN": {"in", "india"}}
    if actual_country and iso in allowed and actual_country not in allowed[iso]:
        return None, "Apollo headquarters outside the project's country"
    if cfg.get("entity_type") == "production_company":
        patterns = (cfg.get("apollo_discovery") or {}).get("excluded_name_patterns") or []
        if any(re.search(r"\b" + re.escape(term) + r"\b", name, re.I) for term in patterns):
            return None, "known major studio"
        employees = org.get("estimated_num_employees")
        if employees is not None and float(employees) > 50:
            return None, "confirmed size beyond the production-house ceiling"
    si = {"has_reachable_presence": True}
    if cfg.get("entity_type") == "production_company":
        si["geography_signal"] = "us"  # constrained Apollo headquarters search
    search = {"key": sl["key"], "country_iso": iso,
              "city": org.get("city"), "state": org.get("state"),
              "employees": org.get("estimated_num_employees"),
              "size_band": discovery.band_text(sl["search"].get("filters", {}).get("organization_num_employees_ranges"))}
    raw = {"apollo": apollo.org_row(org), "apollo_search": search,
           "kind": cfg["entity_type"], "scoring_inputs": si,
           "why_fit": "Apollo search: " + sl["search"]["key"] + "; qualification pending"}
    return {"name": name[:200], "domain": domain,
            "source_url": "https://app.apollo.io/#/organizations/" + str(org["id"]), "raw": raw}, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=None)
    parser.add_argument("--max-minutes", type=float, default=40)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = Db()
    run_id = None
    staged, excluded = [], {}
    error = None
    try:
        row = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
        if not row:
            raise RuntimeError("Project not found: " + SEGMENT)
        seg_id, cfg = row
        if SEGMENT == "lcx-clipping" or (cfg.get("sourcing") or {}).get("provider") != "apollo":
            raise RuntimeError("Apollo-only discovery is not enabled for this project.")
        acfg = cfg.get("apollo_discovery") or {}
        if not acfg.get("searches") or not acfg.get("countries"):
            raise RuntimeError("No automatic Apollo searches configured; use this project's Apollo search page.")
        if not apollo.key_is_set():
            raise RuntimeError("Apollo is required: configure APOLLO_API_KEY before running discovery.")
        block = cfg.get("enrichment") or {}
        if block.get("provider") != "apollo" or block.get("enabled") is not True:
            raise RuntimeError("Apollo spending is disabled for this project.")
        want = args.pages if args.pages is not None else int(acfg.get("pages_per_run", 5))
        if want <= 0 or args.max_minutes <= 0:
            raise ValueError("Pages and maximum minutes must be positive.")
        left = apollo.credits().get("lead_credits_left")
        if left is None:
            raise RuntimeError("Apollo did not report its balance; no credits will be spent.")
        pages, why = db.run(lambda cur: apollo_budget.allowance(cur, SEGMENT, block, left, want))
        print("%s: up to %d Apollo pages (%s)%s" % (SEGMENT, pages, why, " [free checks only]" if args.dry_run else ""), flush=True)
        if pages <= 0:
            return 0
        source = acfg.get("source", "apollo")
        if source not in (cfg.get("sourcing") or {}).get("allowed_sources", []):
            raise RuntimeError("Discovery source is not allowed by the project's policy.")
        urls, domains = discovery.known_here(db, seg_id, source)
        if cfg.get("discovery", {}).get("skip_known_elsewhere", True):
            domains |= discovery.known_elsewhere(db, seg_id)
        if not args.dry_run:
            run_id = db.run(lambda cur: (cur.execute(
                "insert into source_runs(segment_id,source,status) values(%s,%s,'running') returning id",
                (seg_id, source)), cur.fetchone()[0])[1])

        def persist_page(cur, items):
            for item in items:
                cur.execute(
                    "insert into staging_candidates(segment_id,name,domain,source,source_url,raw)"
                    " select %s,%s,%s,%s,%s,%s where not exists"
                    " (select 1 from staging_candidates where segment_id=%s and source_url=%s)",
                    (seg_id, item["name"], item["domain"], source, item["source_url"], json.dumps(item["raw"]), seg_id, item["source_url"]))

        def spend(cur, credits, ref):
            apollo_budget.record(cur, SEGMENT, "company_page", credits, ref)

        staged, excluded, bought = discovery.run_apollo(
            db, seg_id, cfg, pages, urls, domains, page_sink=None if args.dry_run else persist_page,
            deadline=time.monotonic() + args.max_minutes * 60, spend=spend,
            dry_run=args.dry_run, row_builder=company_row, strict=True)
        print("%d staged; %d pages %s; excluded: %s" % (len(staged), bought,
              "checked without buying" if args.dry_run else "bought", json.dumps(excluded)), flush=True)
        return 0
    except Exception as exc:
        error = str(exc)[:500]
        print("Apollo discovery failed: " + error, flush=True)
        return 1
    finally:
        if run_id:
            db.run(lambda cur: cur.execute(
                "update source_runs set finished_at=now(),status=%s,candidates_found=%s,candidates_new=%s,notes=%s,error=%s where id=%s",
                ("failed" if error else "succeeded", len(staged)+sum(excluded.values()), len(staged),
                 json.dumps({"not_staged": excluded}), error, run_id)))
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
