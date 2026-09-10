#!/usr/bin/env python3
"""discover_wikidata_channels.py -- Segment 3 connector: production companies
worldwide that list a YouTube channel on Wikidata, United States first.

    python tools/discover_wikidata_channels.py [--limit-channels 300] [--per-class 800] [--dry-run]

The owner widened the clipping segment from creators to production houses,
everywhere, US first. Wikidata is the one open, worldwide directory of
production companies, and its P2397 property is a YouTube channel ID, which
is exactly the evidence the rubric needs: the channel's catalogue, cadence
and shorts gap come from the same 3-unit profile the other connectors use.

One SPARQL query per company class, direct instances only (a subclass walk
times out on the public endpoint, as the TVF connector found). Companies with
a US country come first, the rest follow; a company already known to this
segment is skipped before it costs a quota unit. Rows land in
staging_candidates for the promote chain, marked kind=production_house so the
drafts use the studio template.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import personname
import yt_api

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
SOURCE = "wikidata_channels"
SPARQL = "https://query.wikidata.org/sparql"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
QUERY = """SELECT ?item ?itemLabel ?yt ?web ?iso WHERE {
  ?item wdt:P31 wd:%s ; wdt:P2397 ?yt .
  OPTIONAL { ?item wdt:P856 ?web . }
  OPTIONAL { ?item wdt:P17 ?c . ?c wdt:P297 ?iso . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,[AUTO_LANGUAGE]". }
} LIMIT %d"""
DEFAULT_CLASSES = [{"qid": "Q1762059", "label": "film production company"},
                   {"qid": "Q10689397", "label": "television production company"},
                   {"qid": "Q1107679", "label": "animation studio"}]


if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def sparql(query):
    url = SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["results"]["bindings"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-channels", type=int, default=300, help="companies to profile this run (3 units each)")
    ap.add_argument("--per-class", type=int, default=None, help="SPARQL LIMIT per company class")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    wcfg = cfg.get("wikidata_channel_discovery", {})
    classes = wcfg.get("entity_classes") or DEFAULT_CLASSES
    per_class = args.per_class or int(wcfg.get("per_class_limit", 800))
    min_subs = int(wcfg.get("min_subscribers", 1000))
    min_videos = int(wcfg.get("min_videos", 30))
    min_recent_long = int(wcfg.get("min_recent_long", 8))
    geo = cfg.get("geography", {})
    prio = set(geo.get("priority_countries") or ["US"])

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

    found = {}                                  # channel id -> company record
    for cls in classes:
        try:
            rows = sparql(QUERY % (cls["qid"], per_class))
        except Exception as e:
            log("  class %s (%s): query failed: %s" % (cls["qid"], cls.get("label", ""), str(e)[:120]))
            time.sleep(2)
            continue
        fresh = 0
        for b in rows:
            yt = (b.get("yt") or {}).get("value", "")
            if not yt.startswith("UC"):
                continue
            rec = found.get(yt)
            if rec is None:
                if yt in known_ids:
                    continue
                rec = found[yt] = {"qid": b["item"]["value"].rsplit("/", 1)[-1],
                                   "label": (b.get("itemLabel") or {}).get("value", ""),
                                   "class": cls.get("label", cls["qid"]), "web": None, "iso": None}
                fresh += 1
            if not rec["web"] and (b.get("web") or {}).get("value"):
                rec["web"] = b["web"]["value"]
            if not rec["iso"] and (b.get("iso") or {}).get("value"):
                rec["iso"] = b["iso"]["value"].upper()
        log("  class %-32s %4d rows, %4d new companies" % (cls.get("label", cls["qid"])[:32], len(rows), fresh))
        time.sleep(1.5)

    ordered = sorted(found.items(), key=lambda kv: (0 if kv[1]["iso"] in prio else 1 if kv[1]["iso"] else 2, kv[1]["label"]))
    us = sum(1 for _, r in ordered if r["iso"] in prio)
    log("\n%d new companies with a channel (%d in %s); profiling up to %d" % (len(ordered), us, "/".join(sorted(prio)), args.limit_channels))
    ordered = ordered[:args.limit_channels]

    staged = skipped = 0
    try:
        for start in range(0, len(ordered), 50):
            chunk = ordered[start:start + 50]
            items = yt_api.channels_by_ids([cid for cid, _ in chunk])
            recs = dict(chunk)
            for item in items:
                rec = recs.get(item["id"])
                if not rec:
                    continue
                st = item.get("statistics", {})
                subs, vids = int(st.get("subscriberCount") or 0), int(st.get("videoCount") or 0)
                if subs < min_subs or vids < min_videos:
                    skipped += 1
                    continue
                pl = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if not pl:
                    skipped += 1
                    continue
                uploads = yt_api.recent_uploads(pl, 50)
                yc = yt_api.profile(item, uploads, cfg)
                if yc["recent"]["long_count"] < min_recent_long:
                    skipped += 1
                    log("  %-36s skipped: %d long among last %d" % ((rec["label"] or yc["title"] or "")[:36], yc["recent"]["long_count"], yc["recent"]["sampled"]))
                    continue
                si = yt_api.inputs_from_channel(yc, cfg, now)
                if not yc.get("country") and rec["iso"]:
                    si.update(yt_api.country_inputs(rec["iso"], geo))
                website, domain = None, None
                if rec["web"]:
                    website, domain = yt_api.website_from(rec["web"], cfg.get("hosting_providers", ()))
                if not domain:
                    website, domain = yc.get("website"), yc.get("website_domain")
                if website and si.get("reachable_contact", 0) < 0.5:
                    si["reachable_contact"] = 0.5
                why = "%s on Wikidata%s. %s" % (rec["class"].capitalize(),
                                                (" (%s)" % rec["iso"]) if rec["iso"] else "", yt_api.why_from_channel(yc))
                name = (rec["label"] or yc.get("title") or "").strip()[:200]
                if not name or name.startswith("Q") and name[1:].isdigit():
                    name = (yc.get("title") or "").strip()[:200]
                row = {"name": name, "domain": domain,
                       "source_url": "https://www.youtube.com/channel/" + yc["channel_id"],
                       "raw": {"kind": "production_house",
                               "wikidata": {"qid": rec["qid"], "class": rec["class"], "country_iso": rec["iso"], "website": website},
                               "youtube_channel": yc, "why_fit": why, "scoring_inputs": si,
                               "host": personname.extract_host(yc.get("title") or "", description=yc.get("description"))}}
                log("  %-36s %-3s subs=%-9s long=%-2d shorts=%-2d %s" % (
                    name[:36], rec["iso"] or "--", f"{subs:,}", yc["recent"]["long_count"], yc["recent"]["shorts_count"],
                    si.get("activity_signal", "")))
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
    finally:
        if run_id:
            db.run(lambda cur: cur.execute(
                "update source_runs set finished_at=now(), status='succeeded', candidates_found=%s,"
                " candidates_new=%s, notes=%s where id=%s",
                (len(found), staged, "quota units used: %d; skipped by floors: %d" % (yt_api.USED["units"], skipped), run_id)))
        db.close()
    log("\nstaged %d production compan%s; %d skipped by the size floors; quota used %d units"
        % (staged, "y" if staged == 1 else "ies", skipped, yt_api.USED["units"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
