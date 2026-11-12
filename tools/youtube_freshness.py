#!/usr/bin/env python3
"""youtube_freshness.py -- YouTube API data is kept at most 30 days (the owner, 2026-11-12, after the research found
the rule in YouTube's Developer Policies: data from the API, statistics included, may be stored for no longer than
30 calendar days, and must then be refreshed or deleted).

    python tools/youtube_freshness.py [--refresh-after 21] [--max-age 30] [--yt-budget 2500] [--dry-run]

For every channel profile the engine holds (metadata.youtube_channel on a lead, and the copies under
metadata.discovery_raw.<source>.youtube_channel and in staging_candidates.raw):
  * a lead still in play (to review, shortlisted, contacted, in conversation) whose profile is --refresh-after days
    old is profiled again (about 3 quota units), and its channel inputs recomputed; the promote chain rescores it;
  * anything else past --max-age days -- an archived or rejected lead, a staged candidate, or a lead the quota did
    not reach -- is reduced to the channel's identity (id, address, handle, title): statistics, descriptions and the
    list of uploads are deleted (yt_api.strip_profile). A later pass profiles it again if the lead comes back.
A profile with no fetched_at (made before this rule) counts from when the lead was enriched or created.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dbconn import Db  # noqa: E402
import yt_api  # noqa: E402

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
LIVE = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted", "contacted", "in_conversation")
RAW_SOURCES = ("youtube_api", "wikidata_channels")


def log(m):
    print(m, flush=True)


def when(s):
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def age_days(yc, meta, created_at, now):
    t = when((yc or {}).get("fetched_at")) or when((meta or {}).get("clipping_enriched_at")) or created_at
    return (now - t).days if t else 9999


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-after", type=int, default=21, help="days before a live lead's profile is fetched again")
    ap.add_argument("--max-age", type=int, default=30, help="days after which an unrefreshed profile is deleted")
    ap.add_argument("--yt-budget", type=int, default=2500, help="quota units this run may spend")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.isoformat()
    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    rows = db.run(lambda cur: (cur.execute(
        "select id, name, status, metadata, created_at from entities where segment_id = %s and"
        " (metadata ? 'youtube_channel' or metadata->'discovery_raw' ?| %s)", (seg_id, list(RAW_SOURCES))), cur.fetchall())[1])
    refreshed = stripped = kept = failed = 0
    for eid, name, status, meta, created in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        yc = meta.get("youtube_channel")
        changed = {}
        if yc and "recent" in yc:
            age = age_days(yc, meta, created, now)
            if status in LIVE and age >= args.refresh_after and yt_api.USED["units"] + 3 <= args.yt_budget and yc.get("url"):
                try:
                    from enrich_clipping import profile_channel
                    yc2, si_new, _why = profile_channel(yc["url"], cfg, now)
                except yt_api.QuotaExhausted as e:
                    log("STOP refreshing: %s" % e)
                    args.yt_budget = 0
                    yc2 = None
                except Exception as e:
                    failed += 1
                    log("  %-40s refresh failed (%s)" % (name[:40], str(e)[:80]))
                    yc2 = None
                if yc2:
                    si = dict(meta.get("scoring_inputs") or {})
                    si.update(si_new or {})
                    changed.update(youtube_channel=yc2, scoring_inputs=si)
                    refreshed += 1
            if not changed and age >= args.max_age:
                changed["youtube_channel"] = yt_api.strip_profile(yc, stamp)
                stripped += 1
            elif not changed:
                kept += 1
        # the connector's own copy under discovery_raw: the same rule
        raw = meta.get("discovery_raw") or {}
        new_raw = None
        for src in RAW_SOURCES:
            ryc = (raw.get(src) or {}).get("youtube_channel")
            if ryc and "recent" in ryc and age_days(ryc, meta, created, now) >= args.max_age:
                new_raw = new_raw or json.loads(json.dumps(raw))
                new_raw[src]["youtube_channel"] = yt_api.strip_profile(ryc, stamp)
        if new_raw is not None:
            changed["discovery_raw"] = new_raw
        if changed and not args.dry_run:
            db.run(lambda cur, _e=eid, _c=changed: cur.execute(
                "update entities set metadata = metadata || %s::jsonb, updated_at = now() where id = %s",
                (json.dumps(_c, default=str), _e)))
    # staged candidates that never became leads keep their raw record: past --max-age, reduced the same way
    staged = db.run(lambda cur: (cur.execute(
        "select id, raw, created_at from staging_candidates where segment_id = %s and raw ? 'youtube_channel'"
        " and created_at < now() - make_interval(days => %s)", (seg_id, args.max_age)), cur.fetchall())[1])
    staged_n = 0
    for sid, raw, created in staged:
        raw = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        ryc = raw.get("youtube_channel") or {}
        if "recent" not in ryc:
            continue
        raw["youtube_channel"] = yt_api.strip_profile(ryc, stamp)
        staged_n += 1
        if not args.dry_run:
            db.run(lambda cur, _s=sid, _r=raw: cur.execute(
                "update staging_candidates set raw = %s::jsonb where id = %s", (json.dumps(_r, default=str), _s)))
    db.close()
    log("%s%d profiles refreshed, %d reduced to the channel's identity (past %d days), %d still fresh, %d refresh"
        " failures; %d staged candidates reduced; %d quota units used."
        % ("[DRY RUN] " if args.dry_run else "", refreshed, stripped, args.max_age, kept, failed, staged_n,
           yt_api.USED["units"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
