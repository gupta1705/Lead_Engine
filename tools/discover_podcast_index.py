#!/usr/bin/env python3
"""discover_podcast_index.py -- LCX Clipping: shows from Podcast Index, the open podcast directory (the owner,
2026-11-12, after the research: the Apple search terms are nearly exhausted -- 150 searches found 61 shows we had not
seen).

    python tools/discover_podcast_index.py [--max-new 400] [--dry-run]

Needs PODCASTINDEX_API_KEY and PODCASTINDEX_API_SECRET (free, from https://api.podcastindex.org/signup). Without
them the step says so and does nothing.

Two calls per run, each answering up to 1,000 shows (https://podcastindex-org.github.io/docs-api/):
  * podcasts/trending -- shows getting listens now, in the project's languages;
  * search/byterm for each of the project's search terms (podcast_discovery.queries).
A show is kept only if Podcast Index says it is alive, has enough episodes (podcast_discovery.min_track_count), a
recent episode (podcast_discovery.max_days_since_release) and no excluded category, and its feed is one we have
never seen. Its own feed is then read exactly as the Apple harvest reads one (tools/discover_podcasts.shape), and it
is staged as source "podcast_index"; the promote chain scores and gates it like any other show.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db  # noqa: E402
import discover_podcasts as dp  # noqa: E402

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
SOURCE = "podcast_index"
API = "https://api.podcastindex.org/api/1.0/"
UA = "TVF-Lead-Engine/1.0"


def log(m):
    print(m, flush=True)


def env(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def call(path, params, key, secret):
    """One signed request (Podcast Index auth: sha1 of key + secret + the unix time, in the Authorization header)."""
    now = str(int(time.time()))
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params), headers={
        "User-Agent": UA, "X-Auth-Key": key, "X-Auth-Date": now,
        "Authorization": hashlib.sha1((key + secret + now).encode()).hexdigest()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def candidate(feed):
    """A Podcast Index feed record in the shape discover_podcasts.shape() reads from Apple's search."""
    cats = feed.get("categories") or {}
    names = list(cats.values()) if isinstance(cats, dict) else []
    return {"feedUrl": feed.get("url") or feed.get("originalUrl"), "collectionName": feed.get("title"),
            "trackCount": feed.get("episodeCount") or 0, "artistName": feed.get("author") or feed.get("ownerName"),
            "collectionId": feed.get("itunesId") or ("pi-%s" % feed.get("id")), "collectionViewUrl": None,
            "genres": names, "primaryGenreName": names[0] if names else None, "_country": None,
            "_term": "podcast_index", "_pi_id": feed.get("id"),
            "_newest": feed.get("newestItemPublishTime") or feed.get("lastUpdateTime")}


def keep(feed, cfg, now, known):
    """-> why it is left out, or None."""
    pd = cfg.get("podcast_discovery", {})
    url = feed.get("url") or feed.get("originalUrl")
    if not url or url in known:
        return "known"
    if feed.get("dead"):
        return "dead"
    eps = feed.get("episodeCount")
    if eps is not None and int(eps) < int(pd.get("min_track_count", 40)):
        return "few episodes"
    newest = feed.get("newestItemPublishTime") or feed.get("lastUpdateTime")
    max_age = pd.get("max_days_since_release")
    if max_age and newest and (now - dt.datetime.fromtimestamp(int(newest), dt.timezone.utc)).days > int(max_age):
        return "dormant"
    cats = {c.lower() for c in ((feed.get("categories") or {}).values() if isinstance(feed.get("categories"), dict) else [])}
    excluded = {g.lower() for g in pd.get("excluded_genres", [])} | {"kids", "family"}
    if cats and cats <= excluded:
        return "excluded category"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new", type=int, default=400, help="new feeds to read this run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key, secret = env("PODCASTINDEX_API_KEY"), env("PODCASTINDEX_API_SECRET")
    if not key or not secret:
        log("PODCASTINDEX_API_KEY / PODCASTINDEX_API_SECRET are not set: skipped (free keys at"
            " https://api.podcastindex.org/signup)")
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    known = set(db.run(lambda cur: (cur.execute(
        "select source_url from staging_candidates where segment_id=%s and source_url is not null"
        " union select source_url from entities where segment_id=%s and source_url is not null",
        (seg_id, seg_id)), [r[0] for r in cur.fetchall()])[1]))
    langs = cfg.get("languages", {}).get("full", ["en"])
    feeds, why = {}, {}

    def take(items, label):
        n = 0
        for f in items or []:
            reason = keep(f, cfg, now, known)
            if reason:
                why[reason] = why.get(reason, 0) + 1
                continue
            url = f.get("url") or f.get("originalUrl")
            if url not in feeds:
                feeds[url] = f
                n += 1
        log("  %-40s %4d shows, %3d new" % (label[:40], len(items or []), n))

    try:
        res = call("podcasts/trending", {"max": 1000, "lang": ",".join(langs), "since": int(time.time()) - 7 * 86400}, key, secret)
        take(res.get("feeds"), "trending (%s)" % ",".join(langs))
        for q in (cfg.get("podcast_discovery", {}).get("queries") or []):
            time.sleep(1.0)
            res = call("search/byterm", {"q": q["term"], "max": 200, "clean": ""}, key, secret)
            take(res.get("feeds"), "search: " + q["term"])
    except Exception as e:
        log("Podcast Index call failed: %s" % str(e)[:200])
        if not feeds:
            db.close()
            return 1
    log("\n%d new show(s) from Podcast Index; left out: %s; reading up to %d feeds"
        % (len(feeds), ", ".join("%s %d" % kv for kv in sorted(why.items())) or "none", args.max_new))
    run_id = None
    if not args.dry_run:
        run_id = db.run(lambda cur: (cur.execute(
            "insert into source_runs (segment_id, source, status) values (%s,%s,'running') returning id",
            (seg_id, SOURCE)), cur.fetchone()[0])[1])
    staged = errors = 0
    for n, f in enumerate(list(feeds.values())[:args.max_new], 1):
        cand = candidate(f)
        try:
            feed = dp.parse_feed(dp.http_get(cand["feedUrl"]))
        except Exception as e:
            errors += 1
            log("  %3d. %-40s feed fetch failed: %s" % (n, (cand["collectionName"] or "")[:40], str(e)[:60]))
            continue
        if not feed or not feed["items"]:
            errors += 1
            continue
        row = dp.shape(cand, feed, cfg, now)
        if not row["name"]:
            continue
        row["raw"]["podcast_index_id"] = cand["_pi_id"]
        log("  %3d. %-40s eps=%-4s email=%s yt=%s" % (n, row["name"][:40], row["raw"]["podcast_feed"]["episode_count"],
                                                     "y" if row["raw"]["podcast_feed"]["owner_email"] else "-",
                                                     "y" if row["raw"]["podcast_feed"]["youtube_url"] else "-"))
        if not args.dry_run:
            db.run(lambda cur, _r=row: cur.execute(
                "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
                " select %s,%s,%s,%s,%s,%s where not exists (select 1 from staging_candidates"
                " where segment_id=%s and source_url=%s)",
                (seg_id, _r["name"], _r["domain"], SOURCE, _r["source_url"], json.dumps(_r["raw"], default=str),
                 seg_id, _r["source_url"])))
        staged += 1
        time.sleep(0.5)
    if run_id:
        db.run(lambda cur: cur.execute(
            "update source_runs set finished_at=now(), status='succeeded', candidates_found=%s, candidates_new=%s,"
            " notes=%s where id=%s", (len(feeds), staged, "errors=%d" % errors, run_id)))
    db.close()
    log("\nstaged %d new show(s); %d feed errors%s. Next: the promote chain." % (staged, errors, " (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
