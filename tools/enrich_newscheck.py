#!/usr/bin/env python3
"""enrich_newscheck.py -- ask the news archive about each company BY NAME.

WHY THIS EXISTS. international_ip_experience is worth 30 of 110 points and on
2026-08-29 only 27 of 808 companies had it -- not because the other 781 lack
format experience, but because the signal only ever arrived by ACCIDENT OF
DISCOVERY: P5 searches the news for deal language and takes whatever companies
happen to be in the headlines that week. A company the engine found via AICP
or Wikidata never gets its news read at all.

This tool inverts the direction: for each company already in the pool, query
Google News for that company's name alongside deal vocabulary, and read what
comes back. Same feed, same phrase lists, same politeness as the P5 connector
-- pointed at companies we can actually contact instead of at strangers.

WHAT A HIT REQUIRES, because false positives here cost 30 points each:
  1. the company's name in the HEADLINE itself (not just the page)
  2. a deal phrase in the headline or its description
  3. a name distinctive enough to search: single common English words are
     SKIPPED ("SOCIETY", "Therapy", "brother" would match everything); those
     stay a manual-research job and are listed at the end.

Evidence is written with full provenance -- headline, link, matched phrase --
into metadata.news_evidence, so a reviewer can check any credit in one click.

Durability rules from tools/dbconn.py apply: reconnecting connection, one
commit per company, a per-row stamp so an interrupted pass resumes.
"""
import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = "us-production-houses"
UA = "TVF-Lead-Engine/0.1 (internal BD research; contact aitools@theviralfever.com)"
DELAY = 1.2
TIMEOUT = 20
STAMP = "v1"

# Same vocabulary the P5 extractor earned through live-run tuning. Split by
# what the evidence proves, exactly as 13_extract_companies.js does.
IP_PHRASES = [
    "format rights", "format deal", "formats deal", "adaptation rights",
    "remake rights", "english-language remake", "english language remake",
    "english-language adaptation", "english-language version",
    "local adaptation", "local version", "international co-production",
    "us remake", "american remake", "american adaptation", "acquires format",
    "co-production", "coproduction", "co-produce", "coproduce", "co-producing",
]
DIST_PHRASES = [
    "series order", "straight-to-series", "first-look deal", "overall deal",
    "greenlit", "greenlights", "orders comedy", "orders drama", "orders series",
    "output deal", "picked up to series",
]

# A single common word is unsearchable as a company name: "Therapy" or
# "SOCIETY" match every third headline. Multi-word names pass automatically.
COMMON_WORDS = {
    "society", "therapy", "brother", "story", "believe", "republic", "arts",
    "common", "thread", "wave", "theory", "electric", "sentient", "epic",
    "country", "house", "growing", "film", "films", "media", "studio",
    "studios", "pictures", "entertainment", "productions", "production",
    "company", "partners", "collective", "content", "creative", "digital",
}


def log(m):
    print(m, flush=True)


def distinctive(name):
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if len(words) >= 2:
        return True
    return bool(words) and words[0].lower() not in COMMON_WORDS and len(words[0]) >= 6


def fetch_feed(name):
    q = '"%s" ("format rights" OR "remake" OR "co-production" OR "adaptation" OR "series order" OR "first-look")' % name
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
           + "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(3_000_000).decode("utf-8", "ignore")


def parse_items(xml):
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        block = m.group(1)
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.S)
        l = re.search(r"<link>(.*?)</link>", block, re.S)
        d = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.S)
        title = html.unescape(html.unescape((t.group(1) if t else "").strip()))
        desc = re.sub(r"<[^>]+>", " ", html.unescape(html.unescape((d.group(1) if d else ""))))
        out.append({"title": title, "link": (l.group(1) if l else "").strip(),
                    "desc": re.sub(r"\s+", " ", desc).strip()})
    return out


def judge(name, items):
    """Return (ip_hit, dist_hit) where each is the item dict + phrase, or None."""
    n = name.lower()
    ip_hit = dist_hit = None
    for it in items[:40]:
        title_l = it["title"].lower()
        if n not in title_l:
            continue                       # rule 1: the name in the HEADLINE
        blob = title_l + " " + it["desc"].lower()
        if ip_hit is None:
            for p in IP_PHRASES:
                if p in blob:
                    ip_hit = {**it, "phrase": p}
                    break
        if dist_hit is None:
            for p in DIST_PHRASES:
                if p in blob:
                    dist_hit = {**it, "phrase": p}
                    break
        if ip_hit and dist_hit:
            break
    return ip_hit, dist_hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--min-score", type=float, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from dbconn import Db
    import json as _json
    db = Db()

    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name
        from entities e join segments s on s.id = e.segment_id
        where s.slug = %s
          and e.status in ('discovered','enriched','scored','ready_for_review')
          and coalesce(e.metadata->>'news_checked','') <> %s
          and coalesce((e.metadata->'scoring_inputs'->>'international_ip_experience')::numeric, 0) = 0
          and coalesce(e.metadata->'scoring_inputs'->>'geography_signal','') <> 'non_us'
          and exists (select 1 from contacts c where c.entity_id = e.id)
          and coalesce(e.fit_score, 0) >= %s
        order by e.fit_score desc nulls last, e.name
        limit %s
    """, (SEGMENT, STAMP, args.min_score, args.limit)), cur.fetchall())[1])

    if not rows:
        log("nothing to check -- every eligible company already swept")
        db.close(); return 0

    log("news sweep -- %d compan(ies)%s\n"
        % (len(rows), "  [DRY RUN]" if args.dry_run else ""))

    stats = {"ip": 0, "dist": 0, "nothing": 0, "generic": 0, "error": 0}
    for eid, name in rows:
        if not distinctive(name):
            log("  %-36s SKIPPED: name too generic to search" % name[:36])
            stats["generic"] += 1
            if not args.dry_run:
                db.run(lambda cur, _e=eid: cur.execute(
                    "update entities set metadata = jsonb_set(metadata,"
                    " '{news_checked}', to_jsonb(%s::text)) where id = %s",
                    (STAMP + ":generic", _e)))
            continue

        try:
            items = parse_items(fetch_feed(name))
        except Exception as e:
            log("  %-36s feed error: %s" % (name[:36], type(e).__name__))
            stats["error"] += 1
            time.sleep(DELAY)
            continue
        finally:
            time.sleep(DELAY)

        ip_hit, dist_hit = judge(name, items)
        found = []
        if ip_hit:
            stats["ip"] += 1
            found.append("IP: " + ip_hit["phrase"])
        if dist_hit:
            stats["dist"] += 1
            found.append("dist: " + dist_hit["phrase"])
        if not found:
            stats["nothing"] += 1
        log("  %-36s %s" % (name[:36],
            " | ".join(found) if found else "(%d items, no qualifying headline)" % len(items)))
        if ip_hit:
            log("      %s" % ip_hit["title"][:96])

        if args.dry_run:
            continue

        def write(cur, _e=eid, _ip=ip_hit, _d=dist_hit):
            evidence = []
            if _ip:
                cur.execute("select set_scoring_input(%s,"
                            "'international_ip_experience','1'::jsonb)", (_e,))
                evidence.append({"criterion": "international_ip_experience",
                                 "phrase": _ip["phrase"], "headline": _ip["title"],
                                 "link": _ip["link"]})
            if _d:
                cur.execute("select set_scoring_input(%s,"
                            "'distribution_relationship','1'::jsonb)", (_e,))
                evidence.append({"criterion": "distribution_relationship",
                                 "phrase": _d["phrase"], "headline": _d["title"],
                                 "link": _d["link"]})
            if evidence:
                cur.execute(
                    "update entities set metadata = metadata ||"
                    " jsonb_build_object('news_evidence', %s::jsonb)"
                    " where id = %s", (_json.dumps(evidence), _e))
            cur.execute("update entities set metadata = jsonb_set(metadata,"
                        " '{news_checked}', to_jsonb(%s::text)) where id = %s",
                        (STAMP, _e))
        db.run(write)

    db.close()
    log("\n  IP evidence found       : %d" % stats["ip"])
    log("  distribution evidence   : %d" % stats["dist"])
    log("  nothing in the archive  : %d" % stats["nothing"])
    log("  too-generic names       : %d  (manual research)" % stats["generic"])
    log("  feed errors             : %d" % stats["error"])
    if not args.dry_run:
        log("\n  re-score:  python tools/run_sql.py -c "
            "\"select count(*) from score_segment('us-production-houses');\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
