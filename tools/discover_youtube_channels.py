#!/usr/bin/env python3
"""discover_youtube_channels.py -- Segment 3 connector: long-form YouTube
channels with a shorts gap, straight from the Data API.

    python tools/discover_youtube_channels.py [--max-searches 15] [--limit-channels 400] [--dry-run]

For each (query x region) in the segment config: one channel search (100
units), then the statistics and the last 50 uploads with durations for every
channel that clears the size floor (3 units each). The shorts gap, cadence,
audience and budget signals are computed from what the API returns, so the
pitch sentence is a fact. Rows land in staging_candidates. Resumable: a
channel already known to this segment is skipped before it costs anything.

Budget: --max-searches 15 and --limit-channels 400 is about 2,700 units,
leaving the TVF harvest its share of the daily 10,000.
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import personname
import yt_api

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
SOURCE = "youtube_api"


if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-searches", type=int, default=15)
    ap.add_argument("--limit-channels", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    ycfg = cfg.get("youtube_channel_discovery", {})
    min_subs = int(ycfg.get("min_subscribers", 3000))
    min_videos = int(ycfg.get("min_videos", 40))
    min_recent_long = int(ycfg.get("min_recent_long", 10))

    known = set(db.run(lambda cur: (cur.execute(
        "select source_url from staging_candidates where segment_id=%s and source_url like '%%youtube.com/channel/%%'"
        " union select source_url from entities where segment_id=%s and source_url like '%%youtube.com/channel/%%'"
        " union select metadata->'youtube_channel'->>'channel_id' from entities where segment_id=%s"
        "   and metadata->'youtube_channel'->>'channel_id' is not null",
        (seg_id, seg_id, seg_id)), [r[0] for r in cur.fetchall() if r[0]])[1]))
    known_ids = {k.rsplit("/", 1)[-1] for k in known}
    log("segment %s: %d channels already known" % (SEGMENT, len(known_ids)))

    run_id = None
    if not args.dry_run:
        run_id = db.run(lambda cur: (cur.execute(
            "insert into source_runs (segment_id, source, status) values (%s,%s,'running') returning id",
            (seg_id, SOURCE)), cur.fetchone()[0])[1])

    pairs = [(q, r) for q in ycfg.get("queries", []) for r in ycfg.get("regions", [{"code": "US", "language": "en"}])]
    prio = set(cfg.get("geography", {}).get("priority_countries") or ["US"])
    random.Random(now.strftime("%Y-%m-%d")).shuffle(pairs)
    first = [p for p in pairs if p[1]["code"] in prio]
    rest = [p for p in pairs if p[1]["code"] not in prio]
    k = min(len(first), int(round(args.max_searches * 0.6))) if rest else min(len(first), args.max_searches)
    pairs = (first[:k] + rest[:args.max_searches - k])[:args.max_searches]

    found = []
    try:
        for i, (q, region) in enumerate(pairs, 1):
            res = yt_api.call("search", part="snippet", type="channel", q=q["query"], maxResults=50,
                              regionCode=region["code"], relevanceLanguage=region["language"])
            ids = [it["snippet"]["channelId"] for it in res.get("items", []) if it.get("snippet", {}).get("channelId")]
            fresh = [c for c in ids if c not in known_ids]
            known_ids.update(fresh)
            found += [(c, q.get("genre_hint"), region["code"]) for c in fresh]
            log("  search %2d/%d  %-28s %s/%s -> %2d channels, %2d new" % (i, len(pairs), q["query"][:28], region["code"], region["language"], len(ids), len(fresh)))
            time.sleep(0.3)

        log("\n%d new channels; profiling up to %d" % (len(found), args.limit_channels))
        found = found[:args.limit_channels]
        hints = {c: (g, r) for c, g, r in found}
        items = yt_api.channels_by_ids([c for c, _, _ in found])
        staged = skipped = 0
        for n, item in enumerate(items, 1):
            st = item.get("statistics", {})
            subs, vids = int(st.get("subscriberCount") or 0), int(st.get("videoCount") or 0)
            if subs < min_subs or vids < min_videos:
                skipped += 1
                continue
            uploads_pl = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
            if not uploads_pl:
                skipped += 1
                continue
            uploads = yt_api.recent_uploads(uploads_pl, 50)
            yc = yt_api.profile(item, uploads, cfg)
            if yc["recent"]["long_count"] < min_recent_long:
                skipped += 1
                log("  %3d. %-36s skipped: %d long among last %d" % (n, (yc["title"] or "")[:36], yc["recent"]["long_count"], yc["recent"]["sampled"]))
                continue
            si = yt_api.inputs_from_channel(yc, cfg, now)
            why = yt_api.why_from_channel(yc)
            row = {"name": (yc["title"] or "")[:200], "domain": yc.get("website_domain"),
                   "source_url": "https://www.youtube.com/channel/" + yc["channel_id"],
                   "raw": {"genre_hint": hints.get(item["id"], (None, None))[0], "region": hints.get(item["id"], (None, None))[1],
                           "youtube_channel": yc, "why_fit": why, "scoring_inputs": si,
                           "host": personname.extract_host(yc.get("title") or "", description=yc.get("description"))}}
            log("  %3d. %-36s subs=%-8s long=%-2d shorts=%-2d share=%-5s %s" % (
                n, row["name"][:36], f"{subs:,}", yc["recent"]["long_count"], yc["recent"]["shorts_count"],
                yc["recent"]["shorts_share"], si.get("activity_signal", "")))
            if not args.dry_run:
                db.run(lambda cur, _r=row: cur.execute(
                    "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
                    " select %s,%s,%s,%s,%s,%s where not exists (select 1 from staging_candidates"
                    " where segment_id=%s and source_url=%s)",
                    (seg_id, _r["name"], _r["domain"], SOURCE, _r["source_url"], json.dumps(_r["raw"], default=str),
                     seg_id, _r["source_url"])))
            staged += 1
    except yt_api.QuotaExhausted as e:
        log("STOP: %s" % e)
        staged = locals().get("staged", 0)
    finally:
        if run_id:
            db.run(lambda cur: cur.execute(
                "update source_runs set finished_at=now(), status='succeeded', candidates_found=%s,"
                " candidates_new=%s, notes=%s where id=%s",
                (len(found), locals().get("staged", 0), "quota units used: %d" % yt_api.USED["units"], run_id)))
        db.close()
    log("\nstaged %d channel(s); quota used this run: %d units (%d calls)" % (locals().get("staged", 0), yt_api.USED["units"], yt_api.USED["calls"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
