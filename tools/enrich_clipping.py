#!/usr/bin/env python3
"""enrich_clipping.py -- Segment 3 enrichment: lift the discovery evidence into
the pool's shape, create the contact, add the YouTube half.

    python tools/enrich_clipping.py [--limit 300] [--yt-budget 6000] [--force]

For every open-pool show in the segment that has not been enriched yet:

  1. LIFT. The promote chain files the connector's record under
     metadata.discovery_raw.<source>. Bring podcast_feed / youtube_channel /
     why_fit up to the top level, where the UI, the drafts and the export read.
  2. CONTACT. The feed's owner address (or a business email in the channel
     description) becomes the primary contact. Source is recorded; nothing is
     guessed.
  3. YOUTUBE. A podcast whose feed links a YouTube channel gets the channel's
     statistics and last 50 uploads (3 quota units): shorts gap, audience band,
     cadence, video-first. Those inputs were unassessed until now; they become
     assessed, and 04b's placeholders for them are lifted (Invariant 1).
  4. STAMP. clipping_enriched_at, so the pass is resumable and the weekly
     refresh only pays for what is new. --force re-does everything.

Then run the promote chain again so the new evidence is scored and gated.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import yt_api

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
OPEN = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")


if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--yt-budget", type=int, default=6000, help="quota units this run may spend on channels")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])

    where = "" if args.force else " and (metadata->>'clipping_enriched_at') is null"
    rows = db.run(lambda cur: (cur.execute(
        "select id, name, source, metadata from entities where segment_id=%s and status in %s" + where +
        " order by created_at desc limit %s", (seg_id, OPEN, args.limit)), cur.fetchall())[1])
    log("segment %s: %d show(s) to enrich" % (SEGMENT, len(rows)))

    lifted = contacts = yt_done = yt_failed = 0
    for n, (eid, name, source, meta) in enumerate(rows, 1):
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        raw = (meta.get("discovery_raw") or {})
        changed = {}
        # 1. lift
        for src, key in (("apple_podcasts", "podcast_feed"), ("youtube_api", "youtube_channel")):
            if key not in meta and (raw.get(src) or {}).get(key):
                changed[key] = raw[src][key]
        if not meta.get("why_fit"):
            for src in ("apple_podcasts", "youtube_api"):
                if (raw.get(src) or {}).get("why_fit"):
                    changed["why_fit"] = raw[src]["why_fit"]
                    break
        if changed:
            lifted += 1
        pf = changed.get("podcast_feed") or meta.get("podcast_feed") or {}
        yc = changed.get("youtube_channel") or meta.get("youtube_channel")

        # 2. contact
        email = (pf.get("owner_email") or (yc or {}).get("email_in_description") or "").lower().strip()
        if email:
            who = pf.get("owner_name") or pf.get("author") or (yc or {}).get("title")
            src = "podcast_rss" if pf.get("owner_email") else "youtube_description"
            ins = db.run(lambda cur, _e=eid: (cur.execute(
                "insert into contacts (entity_id, full_name, role_title, email, source, is_primary)"
                " select %s,%s,%s,%s,%s, not exists (select 1 from contacts where entity_id=%s and is_primary)"
                " where not exists (select 1 from contacts where entity_id=%s and lower(email)=%s) returning id",
                (_e, (who or None), "Host / producer", email, src, _e, _e, email)), cur.fetchone())[1])
            if ins:
                contacts += 1

        # 3. youtube for podcasts with a channel link
        si_new, why_extra = {}, None
        if not yc and pf.get("youtube_url") and yt_api.USED["units"] + 3 <= args.yt_budget:
            try:
                item = yt_api.channel_by_ref(pf["youtube_url"])
                if item:
                    pl = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                    uploads = yt_api.recent_uploads(pl, 50) if pl else []
                    yc = yt_api.profile(item, uploads, cfg)
                    changed["youtube_channel"] = yc
                    si_new = yt_api.inputs_from_channel(yc, cfg, now)
                    why_extra = yt_api.why_from_channel(yc)
                    yt_done += 1
                else:
                    yt_failed += 1
                    changed["youtube_lookup"] = {"url": pf["youtube_url"], "result": "not found", "at": now.isoformat()}
            except yt_api.QuotaExhausted as e:
                log("STOP: %s" % e)
                break
            except Exception as e:
                yt_failed += 1
                changed["youtube_lookup"] = {"url": pf["youtube_url"], "result": str(e)[:200], "at": now.isoformat()}

        # a channel we already hold (YouTube-sourced rows, or a podcast profiled
        # on an earlier pass) gets its inputs recomputed, so a rubric change --
        # such as the oversized gate added after the first live run -- reaches
        # rows that were promoted before it existed
        if yc and not si_new:
            try:
                si_new = yt_api.inputs_from_channel(yc, cfg, now)
            except Exception as e:
                log("  channel inputs failed for %s: %r" % (name[:40], e))

        # merge inputs: the channel settles shorts_gap / audience_band / video_first;
        # for the shared keys keep the stronger evidence
        si = dict(meta.get("scoring_inputs") or {})
        unverified = list(meta.get("unverified_inputs") or [])
        for k, v in si_new.items():
            if k in ("shorts_gap", "audience_band", "video_first", "archive_size", "cadence", "monetization_signals",
                     "reachable_contact", "oversized_signal", "oversized_audience"):
                cur_v = si.get(k)
                if k in ("shorts_gap", "audience_band", "video_first", "oversized_signal", "oversized_audience") \
                        or cur_v is None or k in unverified \
                        or (isinstance(cur_v, (int, float)) and isinstance(v, (int, float)) and v > cur_v):
                    si[k] = v
                    if k in unverified:
                        unverified.remove(k)
            elif k not in si or k in unverified:
                si[k] = v
                if k in unverified:
                    unverified.remove(k)
        if si_new:
            changed["scoring_inputs"] = si
            changed["unverified_inputs"] = unverified
        if why_extra:
            base = changed.get("why_fit") or meta.get("why_fit") or ""
            if "YouTube:" not in base:
                changed["why_fit"] = (base.rstrip(". ") + ". " if base else "") + why_extra
        changed["clipping_enriched_at"] = now.isoformat()

        db.run(lambda cur, _e=eid, _c=changed: cur.execute(
            "update entities set metadata = metadata || %s::jsonb, updated_at = now(),"
            " status = case when status = 'discovered' then 'enriched' else status end where id = %s",
            (json.dumps(_c, default=str), _e)))
        log("  %3d. %-40s %s%s%s" % (n, name[:40], "lift " if changed.get("podcast_feed") or changed.get("youtube_channel") else "",
                                      "contact " if email else "", "yt " if si_new else ""))

    db.close()
    log("\n%d lifted, %d contacts created, %d channels profiled (%d lookups failed), %d quota units used."
        % (lifted, contacts, yt_done, yt_failed, yt_api.USED["units"]))
    log("Next: promote chain for %s to score and gate the new evidence." % SEGMENT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
