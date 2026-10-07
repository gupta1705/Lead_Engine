#!/usr/bin/env python3
"""enrich_lcx_services.py -- LCX Services: what a harvest found, made usable on each lead.

    python tools/enrich_lcx_services.py [--limit 3000] [--dry-run]

After the promote chain a lead's discovery record sits under metadata.discovery_raw.<source>
(tools/discover_lcx_services.py: lcx_wikidata, lcx_osm, lcx_apollo, lcx_fdic). This step, run before
the site pass:

  * lifts what the board, the list and the drafts read to the top of the metadata, as
    enrich_clipping does for its shows: why_fit, kind (the audience), audience, services,
    hq_country, hq_city, hq_state, employees or size_band, buying_signal, and Apollo's own record
    of the company (metadata.apollo, whose id the reveal step searches people by) -- never over a
    value already there
  * turns the address the business itself published (OpenStreetMap's email tag, Wikidata's
    P968) into a contact, source osm or wikidata, unverified. It is a business address, not a
    person, so reachable_decision_maker is 0.5; a named person (1.0) only ever comes from the
    site pass (enrich_contacts), the Apollo reveal (enrich_apollo) or a person, and a higher value
    is never lowered
  * writes no score: the promote chain after it scores what this set.

A lead is read once (metadata.lcx_enriched_at): a contact a person removed is not put back. A lead
a person has decided -- contacted, rejected, archived -- is never touched.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-services")
SOURCES = ("lcx_osm", "lcx_wikidata", "lcx_apollo", "lcx_fdic")
CONTACT_SOURCE = {"lcx_osm": "osm", "lcx_wikidata": "wikidata", "lcx_apollo": "apollo", "lcx_fdic": "fdic"}
OPEN = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def lift(meta):
    """-> (the metadata with the discovery fields lifted, the published email or None, its source)."""
    meta = dict(meta or {})
    raw_all = meta.get("discovery_raw") or {}
    src = next((s for s in SOURCES if isinstance(raw_all.get(s), dict)), None)
    if not src:
        return meta, None, None
    raw = raw_all[src]
    place = raw.get("osm") or raw.get("wikidata") or raw.get("apollo_search") or raw.get("fdic") or {}
    for key, value in (("why_fit", raw.get("why_fit")), ("kind", raw.get("kind")),
                       ("audience", raw.get("audience")), ("services", raw.get("services")),
                       ("hq_country", place.get("country_iso")), ("hq_city", place.get("city")),
                       ("hq_state", place.get("state")), ("employees", place.get("employees")),
                       ("size_band", place.get("size_band")), ("buying_signal", place.get("signal")),
                       # Apollo's own record of the company: the reveal step searches people at its current
                       # employer by this id, so a past employee is never paid for (tools/enrich_apollo.py)
                       ("apollo", raw.get("apollo"))):
        if value not in (None, "", [], {}) and meta.get(key) in (None, "", [], {}):
            meta[key] = value
    return meta, raw.get("published_email"), src


def with_reachable(meta, value=0.5):
    """reachable_decision_maker raised to `value` (never lowered), and no longer listed as unverified."""
    meta = dict(meta)
    si = dict(meta.get("scoring_inputs") or {})
    try:
        now = float(si.get("reachable_decision_maker"))
    except (TypeError, ValueError):
        now = None
    unverified = [k for k in meta.get("unverified_inputs") or [] if k != "reachable_decision_maker"]
    was_unverified = "reachable_decision_maker" in (meta.get("unverified_inputs") or [])
    if now is None or was_unverified or now < value:
        si["reachable_decision_maker"] = value
    meta["scoring_inputs"] = si
    if "unverified_inputs" in meta:
        meta["unverified_inputs"] = unverified
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=3000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from dbconn import Db
    db = Db()
    rows = db.run(lambda cur: (cur.execute(
        "select e.id, e.name, e.metadata from entities e join segments s on s.id = e.segment_id"
        " where s.slug = %s and e.status = any(%s) and not (e.metadata ? 'lcx_enriched_at')"
        "   and e.metadata->'discovery_raw' ?| %s"
        " order by e.created_at limit %s", (SEGMENT, list(OPEN), list(SOURCES), args.limit)), cur.fetchall())[1])
    log("segment %s: %d lead(s) to read%s" % (SEGMENT, len(rows), "  [DRY RUN]" if args.dry_run else ""))
    lifted = contacts = 0
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for eid, name, meta in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        new, email, src = lift(meta)
        if email:
            new = with_reachable(new)
        new["lcx_enriched_at"] = stamp
        lifted += 1
        if args.dry_run:
            if email:
                contacts += 1
            continue

        def write(cur, _e=eid, _m=new, _email=email, _src=src):
            added = 0
            if _email:
                cur.execute("select 1 from contacts where entity_id = %s and lower(email) = lower(%s)", (_e, _email))
                if not cur.fetchone():
                    cur.execute("insert into contacts (entity_id, email, email_status, source) values (%s, %s,"
                                " 'unverified', %s)", (_e, _email, CONTACT_SOURCE[_src]))
                    added = 1
            cur.execute("update entities set metadata = %s, updated_at = now() where id = %s",
                        (json.dumps(_m), _e))
            return added
        contacts += db.run(write)
    db.close()
    log("%d lead(s) read, %d published address(es) %s" % (lifted, contacts,
                                                         "would become contacts" if args.dry_run else "added as contacts"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
