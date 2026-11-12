#!/usr/bin/env python3
"""discover_podcasts.py -- Segment 3 connector: Apple Podcasts search + RSS.

    python tools/discover_podcasts.py [--limit-feeds 300] [--max-searches 60]
                                      [--terms "a,b"] [--countries US,IN] [--dry-run]

Keyless and compliant. For each (search term x store country) in the segment
config it asks Apple's public podcast search for up to 200 shows, then reads
each NEW show's own RSS feed -- the document a podcaster publishes precisely
so that directories and apps can read it. From the feed:

  * title, website, language, categories, the owner's business contact
  * episode count, cadence over the last 90 days, average length, latest date
  * budget signals in the show notes (sponsors, Patreon, merch, courses)
  * a YouTube channel link, if the show has one

That is the evidence the clipping rubric scores, so scoring_inputs are
computed here and travel with the row; the YouTube half (shorts gap, audience)
is added by tools/enrich_clipping.py once the row is in the pool. Rows land in
staging_candidates for the promote chain. Resumable: a feed already in staging
or in the pool for this segment is never fetched twice.

Politeness: one request per feed with a clear User-Agent, Apple's search at
under twenty calls a minute, no retries that hammer.
"""
import argparse
import datetime as dt
import email.utils
import io
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import personname
import yt_api

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
SOURCE = "apple_podcasts"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
ITUNES = "https://itunes.apple.com/search"
NS = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
      "content": "http://purl.org/rss/1.0/modules/content/"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
YT_RE = re.compile(r"https?://(?:www\.|m\.)?youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
NOREPLY = {"noreply", "no-reply", "donotreply", "do-not-reply", "podcasts", "support", "feedback"}
INDIA_LANGS = {"hi", "ta", "te", "mr", "bn", "gu", "pa", "kn", "ml", "ur"}


if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def http_get(url, timeout=20, max_bytes=3_500_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*",
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes + 1)


def apple_search(term, country, genre_id=None):
    q = {"media": "podcast", "entity": "podcast", "term": term, "country": country, "limit": 200}
    if genre_id:
        q["genreId"] = genre_id
    url = ITUNES + "?" + urllib.parse.urlencode(q)
    for attempt in range(3):
        try:
            data = json.loads(http_get(url, timeout=25).decode("utf-8", "replace"))
            return data.get("results", [])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 503):
                wait = 30 * (attempt + 1)
                log("    apple search throttled (%d), waiting %ds" % (e.code, wait))
                time.sleep(wait)
                continue
            log("    apple search failed: %s" % e)
            return []
        except Exception as e:
            log("    apple search failed: %r" % e)
            return []
    return []


# --------------------------------------------------------------- feed parse
def strip_tags(s):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", s or "")).strip()


def parse_duration(s):
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    parts = s.split(":")
    try:
        parts = [float(x) for x in parts]
    except ValueError:
        return None
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return None


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s.strip())
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                d = dt.datetime.strptime(s.strip()[:len(fmt) + 5], fmt)
                return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
            except Exception:
                pass
    return None


def repair_truncated(raw):
    """A feed cut at max_bytes is not well-formed; keep the whole items we
    got and close the document."""
    cut = raw.rfind(b"</item>")
    if cut < 0:
        return None
    return raw[:cut + len(b"</item>")] + b"</channel></rss>"


def parse_feed(raw):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        fixed = repair_truncated(raw)
        if not fixed:
            return None
        try:
            root = ET.fromstring(fixed)
        except ET.ParseError:
            return None
    ch = root.find("channel")
    if ch is None:
        return None

    def text(el, path):
        n = el.find(path, NS)
        return (n.text or "").strip() if n is not None and n.text else ""

    cats = []
    for c in ch.findall("itunes:category", NS):
        if c.get("text"):
            cats.append(c.get("text"))
        for sub in c.findall("itunes:category", NS):
            if sub.get("text"):
                cats.append(sub.get("text"))
    owner = ch.find("itunes:owner", NS)
    owner_name = text(owner, "itunes:name") if owner is not None else ""
    owner_email = text(owner, "itunes:email") if owner is not None else ""
    items = []
    for it in ch.findall("item"):
        desc = text(it, "description") or text(it, "content:encoded") or text(it, "itunes:summary")
        items.append({
            "title": text(it, "title"),
            "date": parse_date(text(it, "pubDate")),
            "duration": parse_duration(text(it, "itunes:duration")),
            "desc": strip_tags(desc)[:2000],
            "link": text(it, "link"),
        })
    return {
        "title": text(ch, "title"),
        "link": text(ch, "link"),
        "language": text(ch, "language").lower(),
        "description": strip_tags(text(ch, "description") or text(ch, "itunes:summary"))[:3000],
        "author": text(ch, "itunes:author"),
        "owner_name": owner_name,
        "owner_email": owner_email,
        "type": text(ch, "itunes:type"),
        "categories": cats,
        "items": items,
    }


# ---------------------------------------------------------------- shaping
def host_of(url):
    try:
        h = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def is_provider(host, providers):
    return any(host == p or host.endswith("." + p) for p in providers)


def shape(cand, feed, cfg, now):
    prov = cfg.get("hosting_providers", [])
    money_pats = [p.lower() for p in cfg.get("monetization_patterns", [])]
    majors = [m.lower() for m in cfg.get("major_networks", [])]
    langs = cfg.get("languages", {})
    geo = cfg.get("geography", {})
    items = feed["items"]
    dated = [i for i in items if i["date"]]
    latest = max((i["date"] for i in dated), default=None)
    last90 = [i for i in dated if (now - i["date"]).days <= 90]
    cadence = round(len(last90) / 3.0, 1) if dated else None
    durs = [i["duration"] for i in items[:20] if i["duration"]]
    avg_min = round(sum(durs) / len(durs) / 60.0) if durs else None
    episode_count = max(len(items), int(cand.get("trackCount") or 0))

    blob = (feed["description"] + " " + " ".join(i["desc"] for i in items[:20])).lower()
    hits = sorted({p for p in money_pats if p in blob})[:8]

    yt = None
    for src in [feed["link"], feed["description"]] + [i["desc"] for i in items[:10]]:
        m = YT_RE.search(src or "")
        if m:
            yt = "https://www.youtube.com/" + m.group(1)
            break

    feed_host = host_of(cand["feedUrl"])
    link_host = host_of(feed["link"]) if feed["link"] else ""
    provider = next((p for p in prov if feed_host == p or feed_host.endswith("." + p)), None)
    website, domain = None, None
    if link_host and not is_provider(link_host, prov):
        website, domain = feed["link"], link_host

    email_ = feed["owner_email"].strip().lower()
    if not EMAIL_RE.fullmatch(email_ or "x"):
        email_ = ""
    if email_:
        local, _, edom = email_.partition("@")
        if is_provider(edom, prov) or local in NOREPLY:
            email_ = ""

    lang = feed["language"] or ""
    primary = lang.split("-")[0]
    region = lang.split("-")[1].upper() if "-" in lang else ""
    if not re.fullmatch(r"[A-Z]{2}", region):          # "zh-hans", "es-419": a script or a UN region, not a country
        region = ""
    author_blob = (feed["author"] + " " + feed["owner_name"] + " " + (cand.get("artistName") or "")).lower()
    major = any(re.search(r"\b" + re.escape(m) + r"\b", author_blob) for m in majors)

    si = {}
    si["archive_size"] = 1.0 if episode_count >= 100 else 0.5 if episode_count >= 40 else 0.0
    if cadence is not None:
        si["cadence"] = 1.0 if cadence >= 4 else 0.5 if cadence >= 2 else 0.0
    si["monetization_signals"] = 1.0 if len(hits) >= 2 else 0.5 if hits else 0.0
    si["reachable_contact"] = 1.0 if email_ else 0.5 if website else 0.0
    if primary:
        si["language_match"] = 1.0 if primary in langs.get("full", []) else \
            0.5 if primary in langs.get("partial", []) else 0.0
    if latest:
        age = (now - latest).days
        si["activity_signal"] = "active" if age <= 90 else "confirmed_dormant" if age > 180 else "quiet"
    # a language is not a country: only a region suffix ("en-us", "de-at")
    # is confirmed evidence; a bare language leaves the country unknown
    if region:
        si.update(yt_api.country_inputs(region, geo))
    elif primary in INDIA_LANGS:
        si["country_signal"] = "allowed"
    import creator_offers
    si["excluded_category_signal"] = creator_offers.excluded_content(feed["title"], feed["description"], feed["categories"], cfg)
    si["has_reachable_presence"] = bool(email_ or website or yt)
    si["major_network_signal"] = bool(major)
    si["network_owned"] = 1.0 if major else 0.0
    if not yt:
        si["video_first"] = 0.0

    kind = "weekly" if cadence and cadence >= 4 else "fortnightly" if cadence and cadence >= 2 else "occasional"
    genre = (feed["categories"] or [cand.get("primaryGenreName") or "talk"])[0].lower()
    why = "%s %s show with %d episodes%s; %s; %s." % (
        kind.capitalize(), genre, episode_count,
        (" averaging %d min" % avg_min) if avg_min else "",
        "YouTube channel linked in the feed" if yt else "no YouTube channel found in the feed",
        "business email published in the feed" if email_ else
        "website only, no address published" if website else "no contact route yet")

    podcast_feed = {
        "feed_url": cand["feedUrl"], "apple_url": cand.get("collectionViewUrl"), "itunes_id": cand.get("collectionId"),
        "website": website, "language": lang or None, "categories": feed["categories"][:6],
        "author": feed["author"] or None, "owner_name": feed["owner_name"] or None, "owner_email": email_ or None,
        "episode_count": episode_count, "latest_at": latest.isoformat() if latest else None,
        "cadence_per_month": cadence, "avg_duration_min": avg_min, "youtube_url": yt,
        "hosting_provider": provider, "monetization_hits": hits, "type": feed["type"] or None,
        "latest_title": items[0]["title"] if items else None,
        "description": feed["description"][:600],
        "creator_offers": creator_offers.detect(
            [(feed["description"], cand["feedUrl"], "podcast_feed")]
            + [(i["desc"], i.get("link") or cand["feedUrl"], "podcast_episode") for i in items[:20]]),
    }
    raw = {"itunes_id": cand.get("collectionId"), "artist": cand.get("artistName"),
           "genres": cand.get("genres"), "track_count": cand.get("trackCount"),
           "country_hint": cand.get("_country"), "podcast_feed": podcast_feed,
           "why_fit": why, "category": genre, "scoring_inputs": si}
    raw["host"] = personname.extract_host(feed["title"] or cand.get("collectionName") or "",
                                          author=feed["author"], owner_name=feed["owner_name"],
                                          description=feed["description"], artist=cand.get("artistName"))
    return {"name": (feed["title"] or cand.get("collectionName") or "").strip()[:200],
            "domain": domain, "source_url": cand["feedUrl"], "raw": raw}


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-feeds", type=int, default=300, help="new feeds to read this run")
    ap.add_argument("--max-searches", type=int, default=60, help="Apple search calls this run")
    ap.add_argument("--terms", default=None, help="comma-separated override of the config terms")
    ap.add_argument("--countries", default=None, help="comma-separated override of store countries")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s -- run sql/03d first" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    pd = cfg.get("podcast_discovery", {})
    queries = pd.get("queries", [])
    if args.terms:
        queries = [{"term": t.strip()} for t in args.terms.split(",") if t.strip()]
    countries = (args.countries.split(",") if args.countries else pd.get("countries", ["US"]))
    excluded = {g.lower() for g in pd.get("excluded_genres", [])}
    min_tracks = int(pd.get("min_track_count", 40))
    # a dormant show is skipped here, on Apple's own date for its latest episode, before its feed is read
    # (2026-11-12: 1,278 dormant shows had been read, scored and archived)
    max_age = pd.get("max_days_since_release")
    dormant = 0

    known = set(db.run(lambda cur: (cur.execute(
        "select source_url from staging_candidates where segment_id=%s and source_url is not null"
        " union select source_url from entities where segment_id=%s and source_url is not null",
        (seg_id, seg_id)), [r[0] for r in cur.fetchall()])[1]))
    log("segment %s: %d feeds already known" % (SEGMENT, len(known)))

    run_id = None
    if not args.dry_run:
        run_id = db.run(lambda cur: (cur.execute(
            "insert into source_runs (segment_id, source, status) values (%s,%s,'running') returning id",
            (seg_id, SOURCE)), cur.fetchone()[0])[1])

    # rotate the term list by day so successive runs cover different ground;
    # the priority countries (US) get six searches in ten, the rest share the others
    prio = set(cfg.get("geography", {}).get("priority_countries") or ["US"])
    rnd = random.Random(now.strftime("%Y-%m-%d"))
    pairs = [(q, c) for q in queries for c in countries]
    rnd.shuffle(pairs)
    first = [p for p in pairs if p[1] in prio]
    rest = [p for p in pairs if p[1] not in prio]
    k = min(len(first), int(round(args.max_searches * 0.6))) if rest else min(len(first), args.max_searches)
    pairs = (first[:k] + rest[:args.max_searches - k])[:args.max_searches]

    cands, seen_names = {}, set()
    for i, (q, country) in enumerate(pairs, 1):
        res = apple_search(q["term"], country, q.get("genre_id"))
        fresh = 0
        for r in res:
            fu = r.get("feedUrl")
            if not fu or r.get("collectionId") in cands or fu in known:
                continue
            genres = {g.lower() for g in (r.get("genres") or [])}
            if genres & excluded or (r.get("trackCount") or 0) < min_tracks:
                continue
            released = parse_date(r.get("releaseDate"))
            if max_age and released and (now - released).days > int(max_age):
                dormant += 1
                continue
            nm = (r.get("collectionName") or "").strip().lower()
            if not nm or nm in seen_names:
                continue
            seen_names.add(nm)
            r["_country"] = country
            r["_term"] = q["term"]
            cands[r["collectionId"]] = r
            fresh += 1
        log("  search %2d/%d  %-32s %s  -> %3d results, %3d new" % (i, len(pairs), q["term"][:32], country, len(res), fresh))
        time.sleep(3.2)

    log("\n%d candidate feeds after Apple (%d dormant skipped); reading up to %d" % (len(cands), dormant, args.limit_feeds))
    staged = errors = skipped = 0
    for n, cand in enumerate(list(cands.values())[:args.limit_feeds], 1):
        try:
            raw = http_get(cand["feedUrl"])
        except Exception as e:
            errors += 1
            log("  %3d. %-40s feed fetch failed: %s" % (n, (cand.get("collectionName") or "")[:40], str(e)[:60]))
            time.sleep(0.5)
            continue
        feed = parse_feed(raw)
        if not feed or not feed["items"]:
            skipped += 1
            log("  %3d. %-40s unparseable or empty feed" % (n, (cand.get("collectionName") or "")[:40]))
            time.sleep(0.5)
            continue
        row = shape(cand, feed, cfg, now)
        if not row["name"]:
            skipped += 1
            continue
        si = row["raw"]["scoring_inputs"]
        log("  %3d. %-40s eps=%-4s cad=%-4s email=%s yt=%s %s" % (
            n, row["name"][:40], row["raw"]["podcast_feed"]["episode_count"],
            row["raw"]["podcast_feed"]["cadence_per_month"],
            "y" if row["raw"]["podcast_feed"]["owner_email"] else "-",
            "y" if row["raw"]["podcast_feed"]["youtube_url"] else "-",
            si.get("activity_signal", "")))
        if not args.dry_run:
            db.run(lambda cur, _r=row: cur.execute(
                "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
                " select %s,%s,%s,%s,%s,%s where not exists (select 1 from staging_candidates"
                " where segment_id=%s and source_url=%s)",
                (seg_id, _r["name"], _r["domain"], SOURCE, _r["source_url"], json.dumps(_r["raw"], default=str),
                 seg_id, _r["source_url"])))
        staged += 1
        time.sleep(1.0)

    if run_id:
        db.run(lambda cur: cur.execute(
            "update source_runs set finished_at=now(), status='succeeded', candidates_found=%s,"
            " candidates_new=%s, notes=%s where id=%s",
            (len(cands), staged, "searches=%d errors=%d skipped=%d" % (len(pairs), errors, skipped), run_id)))
    db.close()
    log("\nstaged %d new show(s); %d fetch errors, %d skipped. Next: promote chain for %s" % (staged, errors, skipped, SEGMENT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
