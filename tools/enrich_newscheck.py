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
  1. the headline is ABOUT the company, by the rules in tools/newsmatch.py:
     whole words, the publisher's name is not the headline, and a one-word
     name must stand as a company in the sentence. Until 2026-09-17 this was a
     substring test, and four of five deal credits on the shortlist were other
     people's news ("Chelsea Handler Inks ...", "Highway to Heaven reboot").
  2. a deal phrase in the headline or its description
  3. a name distinctive enough to search: single common English words are
     SKIPPED ("SOCIETY", "Therapy", "brother" would match everything); those
     stay a manual-research job and are listed at the end.

Each credit records the story's publication date, so nothing downstream ever
calls a 2016 deal recent. --rejudge re-applies rule 1 to credits already
written, retracts the ones that fail (kept under metadata.retracted_evidence,
never silently dropped), dates the ones that stand, and re-scores the row.

Evidence is written with full provenance -- headline, link, matched phrase --
into metadata.news_evidence, so a reviewer can check any credit in one click.

Durability rules from tools/dbconn.py apply: reconnecting connection, one
commit per company, a per-row stamp so an interrupted pass resumes.
"""
import os
import argparse
import datetime as dt
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import newsmatch  # noqa: E402

# The segment this run works on. Segment 2 is meant to be "a config row and
# connectors, nothing else" -- so the slug comes from the environment, and
# every tool, the app, and the container agree on SEGMENT_SLUG.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
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
        pub = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        title = html.unescape(html.unescape((t.group(1) if t else "").strip()))
        desc = re.sub(r"<[^>]+>", " ", html.unescape(html.unescape((d.group(1) if d else ""))))
        out.append({"title": title, "link": (l.group(1) if l else "").strip(),
                    "desc": re.sub(r"\s+", " ", desc).strip(),
                    "published": (pub.group(1).strip() if pub else None)})
    return out


def judge(name, items):
    """Return (ip_hit, dist_hit) where each is the item dict + phrase, or None."""
    ip_hit = dist_hit = None
    for it in items[:40]:
        title_l = it["title"].lower()
        if not newsmatch.names_company(name, it["title"]):
            continue                       # rule 1: the headline is about THIS company
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


def rejudge(db, dry_run=False):
    """Retract news credits whose headline is not about the company; date the rest.

    A retracted credit is moved to metadata.retracted_evidence with the reason,
    its criterion drops back to what the remaining evidence supports (a site's
    own platform claim is still worth 0.5 for distribution), and a criterion
    nothing supports any more is set to 0 and listed in unverified_inputs, so
    real evidence found later is free to overwrite it. Shortlisted rows are
    re-scored too: their status is a human decision and stays, but the number
    on them should not rest on somebody else's news."""
    import json as _json
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.status, e.fit_score, e.metadata
        from entities e join segments s on s.id = e.segment_id
        where s.slug = %s and jsonb_typeof(e.metadata->'news_evidence') = 'array'
        order by e.fit_score desc nulls last""", (SEGMENT,)), cur.fetchall())[1])
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    retracted = kept = dated = 0
    for eid, name, status, score, meta in rows:
        meta = meta if isinstance(meta, dict) else _json.loads(meta or "{}")
        evidence = [e for e in (meta.get("news_evidence") or []) if isinstance(e, dict)]
        keep = [e for e in evidence if newsmatch.names_company(name, e.get("headline"))]
        drop = [e for e in evidence if e not in keep]
        # date what stands: the feed still carries the story, with its pubDate
        undated = [e for e in keep if not e.get("published")]
        if undated and not dry_run:
            try:
                items = parse_items(fetch_feed(name))
            except Exception as exc:
                items = []
                log("  %-34s feed error while dating: %s" % (name[:34], type(exc).__name__))
            finally:
                time.sleep(DELAY)
            for e in undated:
                same = next((it for it in items if it["link"] == e.get("link") or it["title"] == e.get("headline")), None)
                if same and same.get("published"):
                    e["published"] = same["published"]
                    dated += 1
        kept += len(keep)
        retracted += len(drop)
        log("  %-34s %-16s kept %d, retracted %d%s" % (
            name[:34], status, len(keep), len(drop),
            "".join("\n      x %s" % (e.get("headline") or "")[:100] for e in drop)))
        if dry_run or (not drop and not undated):
            continue
        si = dict(meta.get("scoring_inputs") or {})
        unverified = list(meta.get("unverified_inputs") or [])
        for crit in {e.get("criterion") for e in drop}:
            if any(e.get("criterion") == crit for e in keep):
                continue
            platform = meta.get("site_platform_evidence")
            fallback = 0.5 if (crit == "distribution_relationship" and isinstance(platform, str)
                               and not re.search(r"[{}<>=;\"]", platform)) else 0
            si[crit] = fallback
            if not fallback and crit not in unverified:
                unverified.append(crit)
        history = list(meta.get("retracted_evidence") or [])
        for e in drop:
            history.append(dict(e, retracted_at=now,
                                reason="the headline is not about this company (tools/newsmatch.py)"))
        patch = {"news_evidence": keep, "scoring_inputs": si, "unverified_inputs": unverified,
                 "retracted_evidence": history}

        def write(cur, _e=eid, _p=patch):
            cur.execute("update entities set metadata = metadata || %s::jsonb, updated_at = now() where id = %s",
                        (_json.dumps(_p), _e))
            cur.execute("select score_entity(%s)", (_e,))
            return cur.fetchone()[0]
        new_score = db.run(write)
        log("      score %s -> %s" % (score, new_score))
    db.close()
    log("\n  credits kept: %d (%d newly dated), retracted: %d%s"
        % (kept, dated, retracted, "  [DRY RUN]" if dry_run else ""))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--min-score", type=float, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rejudge", action="store_true",
                    help="re-apply the headline rules to credits already written: retract the ones "
                         "about somebody else, date the ones that stand, re-score")
    args = ap.parse_args()

    from dbconn import Db
    import json as _json
    db = Db()
    if args.rejudge:
        return rejudge(db, args.dry_run)

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
                                 "link": _ip["link"], "published": _ip.get("published")})
            if _d:
                cur.execute("select set_scoring_input(%s,"
                            "'distribution_relationship','1'::jsonb)", (_e,))
                evidence.append({"criterion": "distribution_relationship",
                                 "phrase": _d["phrase"], "headline": _d["title"],
                                 "link": _d["link"], "published": _d.get("published")})
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
