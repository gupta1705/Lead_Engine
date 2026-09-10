#!/usr/bin/env python3
"""import_pool.py -- carry one segment's discovered companies into another
segment's staging, with their contacts; or repair rows carried earlier.

    SEGMENT_SLUG=lcx-clipping python tools/import_pool.py --from us-production-houses [--limit 1500] [--dry-run]
    SEGMENT_SLUG=lcx-clipping python tools/import_pool.py --from us-production-houses --repair

Why: the TVF segment already holds hundreds of US production houses with a
website and, for many, a named contact. For the clipping segment every one of
them is a possible customer -- a production house has an archive -- and the
clipping enrichment pass then looks for each one's YouTube channel from its
website, or profiles the channel TVF found it by. Copying them is cheaper
than rediscovering them, and the origin is recorded on every row.

What is carried: name, domain, source URL, city and state, the contacts (name,
role, email, verification status), where the row stood in the source segment,
and the source segment's OWN assessment of the inputs that are not about
co-production fit: country, reachable presence, reachable contact. Nothing is
recomputed and nothing is defaulted (Invariant 1): a TVF row archived for being
outside the US arrives with us_priority 0 and no country claim; a YouTube-found
row without a website keeps the "reachable" verdict TVF gave it, because a
channel is a way to be reached.

What is NOT carried: scores, why-it-fits notes and dispositions. A rejection
for co-production fit says nothing about clipping, so TVF's rejected rows come
along; its archived rows come only when the archive reason was geography.

--repair re-derives those carried inputs for rows already in the target from
their origin row, and un-archives a row the presence gate closed on a
recomputed value (the first import, 2026-09-09, did exactly that to 199 rows).
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
CARRY_STATUSES = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted",
                  "contacted", "in_conversation", "rejected")
EMAIL_STATUSES = {"unverified", "valid", "invalid", "catch_all", "unknown"}
CARRIED_KEYS = ("country_signal", "us_priority", "has_reachable_presence", "reachable_contact")


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def carried_inputs(src_si, src_unverified, hq_state, domain, emails, geo, verified_country=None):
    """The origin row's verdicts, translated; absent stays absent."""
    import yt_api
    si = {}
    g = (src_si or {}).get("geography_signal")
    if verified_country:
        si.update(yt_api.country_inputs(verified_country, geo))   # CA/DE come out disallowed, US as priority
    elif g == "us" or hq_state:
        si.update(yt_api.country_inputs("US", geo))
    elif g == "non_us":
        si["us_priority"] = 0.0                     # confirmed not the priority market; country itself unknown
    for key in ("has_reachable_presence", "reachable_contact"):
        if key in (src_si or {}) and key not in (src_unverified or []):
            si[key] = src_si[key]
    # evidence this segment can see for itself outranks an absent origin verdict
    if "has_reachable_presence" not in si and (domain or emails):
        si["has_reachable_presence"] = True
    if emails:
        si["reachable_contact"] = max(float(si.get("reachable_contact") or 0), 1.0)
    elif "reachable_contact" not in si and domain:
        si["reachable_contact"] = 0.5
    return si


def load_pair(db, src_slug):
    ids = db.run(lambda cur: (cur.execute(
        "select slug, id, config from segments where slug in (%s, %s)", (src_slug, SEGMENT)),
        {r[0]: (r[1], r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}")) for r in cur.fetchall()})[1])
    if src_slug not in ids or SEGMENT not in ids:
        sys.exit("both segments must exist: have %s" % sorted(ids))
    return ids[src_slug][0], ids[SEGMENT][0], ids[SEGMENT][1]


def fetch_source_rows(db, src_id, limit, only_ids=None):
    extra = " and e.id = any(%s::uuid[])" if only_ids else ""
    params = [src_id, CARRY_STATUSES] + ([only_ids] if only_ids else []) + [limit]
    return db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.domain, e.source, e.source_url, e.status, e.status_reason,
               e.metadata->>'hq_city', e.metadata->>'hq_state',
               e.metadata->'scoring_inputs', e.metadata->'unverified_inputs',
               e.metadata->'discovery_raw'->'youtube_api'->>'channel_id',
               e.metadata->>'verified_country',
               coalesce((select json_agg(json_build_object('full_name', c.full_name, 'role_title', c.role_title,
                          'email', c.email, 'email_status', c.email_status, 'source', c.source, 'is_primary', c.is_primary))
                         from contacts c where c.entity_id = e.id and c.email is not null), '[]'::json)
        from entities e
        where e.segment_id = %s
          and (e.status in %s or (e.status = 'archived' and e.status_reason ilike 'Gate us_geography%%'))""" + extra + """
        order by e.fit_score desc nulls last, e.created_at
        limit %s""", params), cur.fetchall())[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True, help="source segment slug")
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repair", action="store_true", help="re-derive carried inputs for rows already imported")
    args = ap.parse_args()
    if args.src == SEGMENT:
        sys.exit("source and target segment are the same")
    source_key = "pool:" + args.src if args.src != "us-production-houses" else "tvf_pool"

    db = Db()
    src_id, dst_id, cfg = load_pair(db, args.src)
    geo = cfg.get("geography", {})

    if args.repair:
        return repair(db, args, src_id, dst_id, geo, source_key)

    have_dom = set(db.run(lambda cur: (cur.execute(
        "select lower(domain) from entities where segment_id=%s and domain is not null"
        " union select lower(domain) from staging_candidates where segment_id=%s and domain is not null",
        (dst_id, dst_id)), {r[0] for r in cur.fetchall()})[1]))
    have_name = set(db.run(lambda cur: (cur.execute(
        "select lower(name) from entities where segment_id=%s"
        " union select lower(name) from staging_candidates where segment_id=%s", (dst_id, dst_id)),
        {r[0] for r in cur.fetchall()})[1]))

    rows = fetch_source_rows(db, src_id, args.limit)
    log("segment %s -> %s: %d candidate rows" % (args.src, SEGMENT, len(rows)))

    staged = skipped = 0
    for (eid, name, domain, src, src_url, status, reason, city, state, src_si, src_unv, yt_id, vc, contacts) in rows:
        contacts = contacts if isinstance(contacts, list) else json.loads(contacts or "[]")
        src_si = src_si if isinstance(src_si, dict) else json.loads(src_si or "{}")
        src_unv = src_unv if isinstance(src_unv, list) else json.loads(src_unv or "[]")
        key_dom = (domain or "").lower()
        if (key_dom and key_dom in have_dom) or (not key_dom and name.lower() in have_name):
            skipped += 1
            continue
        emails = [c for c in contacts if c.get("email")]
        si = carried_inputs(src_si, src_unv, state, domain, emails, geo, vc)
        why = ("Production house carried over from the TVF pool (found by %s%s); "
               "clipping evidence pending a YouTube channel lookup." % (src, ", " + state if state else ""))
        raw = {"kind": "production_house",
               "origin": {"segment": args.src, "entity_id": str(eid), "status": status, "reason": reason,
                          "source": src, "youtube_channel_id": yt_id},
               "hq_city": city, "hq_state": state,
               "contacts": [{"full_name": c.get("full_name"), "role_title": c.get("role_title"), "email": c["email"],
                             "email_status": c.get("email_status") if c.get("email_status") in EMAIL_STATUSES else "unverified",
                             "source": c.get("source"), "is_primary": bool(c.get("is_primary"))} for c in emails],
               "why_fit": why, "scoring_inputs": si, "host": None}
        log("  %-40s %-28s %-16s contacts=%d %s" % (name[:40], (domain or "-")[:28], status, len(emails),
                                                   " ".join("%s=%s" % kv for kv in si.items())))
        if not args.dry_run:
            db.run(lambda cur, _n=name, _d=domain, _u=src_url, _r=raw: cur.execute(
                "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
                " select %s,%s,%s,%s,%s,%s where not exists (select 1 from staging_candidates"
                " where segment_id=%s and (lower(domain)=lower(%s) or (domain is null and lower(name)=lower(%s))))",
                (dst_id, _n, _d, source_key, _u, json.dumps(_r, default=str), dst_id, _d or "", _n)))
        if key_dom:
            have_dom.add(key_dom)
        have_name.add(name.lower())
        staged += 1
    db.close()
    log("\nstaged %d row(s) from %s; %d already present. Next: promote chain for %s, then enrich_clipping"
        % (staged, args.src, skipped, SEGMENT))
    return 0


def origin_of(meta, source_key):
    return meta.get("origin") or ((meta.get("discovery_raw") or {}).get(source_key) or {}).get("origin") or {}


def repair(db, args, src_id, dst_id, geo, source_key):
    """Rows already carried: re-derive the carried inputs from the origin and
    reopen any row the presence gate archived on a recomputed value."""
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.domain, e.status, e.status_reason, e.metadata
        from entities e
        where e.segment_id = %s and (e.metadata->'origin'->>'segment' = %s
               or e.metadata->'discovery_raw'->%s->'origin'->>'segment' = %s)
        limit %s""", (dst_id, args.src, source_key, args.src, args.limit)), cur.fetchall())[1])
    log("repairing %d carried row(s) in %s from %s" % (len(rows), SEGMENT, args.src))
    origins = {}
    origin_ids = [origin_of(m if isinstance(m, dict) else json.loads(m), source_key).get("entity_id") for _, _, _, _, _, m in rows]
    origin_ids = [o for o in origin_ids if o]
    for r in fetch_source_rows(db, src_id, len(origin_ids) + 1, only_ids=origin_ids) if origin_ids else []:
        origins[str(r[0])] = r
    fixed = reopened = 0
    for eid, name, domain, status, reason, meta in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        o = origins.get(origin_of(meta, source_key).get("entity_id"))
        if not o:
            continue
        (_, _, _, _, _, _, _, _, state, src_si, src_unv, yt_id, vc, contacts) = o
        contacts = contacts if isinstance(contacts, list) else json.loads(contacts or "[]")
        src_si = src_si if isinstance(src_si, dict) else json.loads(src_si or "{}")
        src_unv = src_unv if isinstance(src_unv, list) else json.loads(src_unv or "[]")
        emails = [c for c in contacts if c.get("email")]
        want = carried_inputs(src_si, src_unv, state, domain, emails, geo, vc)
        si = dict(meta.get("scoring_inputs") or {})
        unverified = [k for k in (meta.get("unverified_inputs") or []) if k not in want]
        for k in CARRIED_KEYS:
            si.pop(k, None)                     # the first import's recomputed values go
        si.update(want)
        changed = {"scoring_inputs": si, "unverified_inputs": unverified}
        origin = dict(origin_of(meta, source_key)); origin["youtube_channel_id"] = yt_id
        changed["origin"] = origin
        reopen = status == "archived" and (reason or "").startswith("Gate usable_first_party_presence")
        log("  %-40s %s%s" % (name[:40], " ".join("%s=%s" % kv for kv in want.items()), "  REOPEN" if reopen else ""))
        if not args.dry_run:
            db.run(lambda cur, _e=eid, _c=changed, _r=reopen: cur.execute(
                "update entities set metadata = metadata || %s::jsonb, updated_at = now()"
                + (", status = 'enriched', status_reason = null, status_changed_at = now()" if _r else "")
                + " where id = %s", (json.dumps(_c, default=str), _e)))
        fixed += 1
        reopened += reopen
    db.close()
    log("\nrepaired %d row(s), reopened %d. Next: promote chain for %s to re-score and re-gate." % (fixed, reopened, SEGMENT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
