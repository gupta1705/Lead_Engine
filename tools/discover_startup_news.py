#!/usr/bin/env python3
"""discover_startup_news.py -- startup segment connector: struggling startups
from news HEADLINES, and the Mumbai startups that raised a small round in
2021-24.

    python tools/discover_startup_news.py                 # weekly: distress headlines from the last 40 days
    python tools/discover_startup_news.py --backfill      # distress over 24 months + the funding cohort
    python tools/discover_startup_news.py --backfill --track funding --dry-run

WHY HEADLINES AND NOTHING MORE. Inc42's and Entrackr's terms forbid scraping,
spidering and "any systematic or automated data collection", so their article
pages are never fetched. Google News RSS carries the headline, the publisher
and a link, which is what the TVF connectors have always read. A row keeps
that link, so a person can read the story in one click.

WHAT IT FINDS. Two queries lists in config startup_discovery:
  * distress: layoffs, shutdowns, salary delays, insolvency, down and rescue
    rounds, sale talks -- India-wide, because a headline rarely says where a
    company is. tools/enrich_startups.py places each one; the mumbai_region
    gate archives the rest.
  * funding: "Mumbai-based" startups raising seed, angel or pre-Series A money
    between 2021 and mid-2024. Their runway has had time to run out; the
    enrichment pass decides which have gone quiet.
Each search covers one quarter, because a search returns at most 100 items.
Only publishers in startup_discovery.publishers count, which keeps foreign
startup news -- a large share of what "startup shuts down" returns -- out.

The headline rules are tools/startup_signals.py (regression table:
tools/test_startup_signals.py). One staging row per company per run, carrying
every new event; an event already known to the segment is never staged twice.
"""
import argparse
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db  # noqa: E402
import startup_signals as ss  # noqa: E402

SEGMENT = os.environ.get("SEGMENT_SLUG", "startup-acquisitions")
SOURCE = "startup_news"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
RSS = "https://news.google.com/rss/search"
DELAY = 2.2

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def rss(query):
    """[(title, publisher, publisher_url, link, published_at_iso)] for one search."""
    url = RSS + "?" + urllib.parse.urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                root = ET.fromstring(r.read())
            break
        except Exception as e:
            if attempt == 2:
                log("    search failed (%s): %s" % (type(e).__name__, query[:80]))
                return []
            time.sleep(6)
    out = []
    for it in root.findall(".//item"):
        title = it.findtext("title") or ""
        src = it.find("source")
        pub = (src.text or "") if src is not None else ""
        pub_url = src.get("url", "") if src is not None else ""
        if pub and title.endswith(" - " + pub):
            title = title[: -len(" - " + pub)]
        when = None
        try:
            when = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(dt.timezone.utc).isoformat()
        except Exception:
            pass
        out.append((title.strip(), pub, pub_url, it.findtext("link") or "", when))
    return out


def allowed(pub_url, publishers):
    host = urllib.parse.urlparse(pub_url or "").netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return bool(host) and any(host == p or host.endswith("." + p) for p in publishers)


def quarters(start, end):
    d = start
    while d < end:
        m = d.month + 3
        nxt = dt.date(d.year + (m - 1) // 12, (m - 1) % 12 + 1, 1)
        yield d, min(nxt, end)
        d = nxt


def plan(disc, track, backfill, today):
    """[(track, key, query-with-window)] for this run."""
    jobs = []
    if track in ("distress", "all"):
        if backfill:
            months = int(disc.get("distress_months", 24))
            start = (today.replace(day=1) - dt.timedelta(days=months * 30.44)).replace(day=1)
            start = dt.date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
            windows = list(quarters(start, today + dt.timedelta(days=1)))
        else:
            windows = [(today - dt.timedelta(days=int(disc.get("incremental_days", 40))), today + dt.timedelta(days=1))]
        for q in disc.get("distress_queries", []):
            for a, b in windows:
                jobs.append(("distress", q["key"], "%s after:%s before:%s" % (q["query"], a, b)))
    if track in ("funding", "all") and backfill:
        start = dt.date.fromisoformat(disc.get("funding_from", "2021-01-01"))
        end = dt.date.fromisoformat(disc.get("funding_to", "2024-07-01"))
        for q in disc.get("funding_queries", []):
            for a, b in quarters(start, end):
                jobs.append(("funding", q["key"], "%s after:%s before:%s" % (q["query"], a, b)))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="the full distress window and the 2021-24 funding cohort")
    ap.add_argument("--track", choices=("distress", "funding", "all"), default="all")
    ap.add_argument("--max-queries", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    today = dt.datetime.now(dt.timezone.utc).date()

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s -- run sql/03c first" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    disc = cfg.get("startup_discovery")
    if not disc:
        sys.exit("segment %s has no startup_discovery block" % SEGMENT)
    publishers = [p.lower() for p in disc.get("publishers", [])]
    inr = float(disc.get("inr_per_usd", 85))

    known = set(db.run(lambda cur: (cur.execute(
        "select jsonb_array_elements(raw->'events')->>'link' from staging_candidates"
        " where segment_id=%s and source=%s and raw ? 'events'"
        " union select jsonb_array_elements(metadata->'press_events')->>'link' from entities"
        " where segment_id=%s and metadata ? 'press_events'", (seg_id, SOURCE, seg_id)),
        [r[0] for r in cur.fetchall()])[1]))
    log("segment %s: %d headline(s) already known" % (SEGMENT, len(known)))

    jobs = plan(disc, args.track, args.backfill, today)[:args.max_queries]
    log("%d search(es): %s%s\n" % (len(jobs), "backfill" if args.backfill else "last %s days" % disc.get("incremental_days", 40),
                                   "  [DRY RUN]" if args.dry_run else ""))
    run_id = None
    if not args.dry_run:
        run_id = db.run(lambda cur: (cur.execute(
            "insert into source_runs (segment_id, source, status) values (%s,%s,'running') returning id",
            (seg_id, SOURCE)), cur.fetchone()[0])[1])

    companies, seen_titles = {}, set()
    items = foreign = no_company = 0
    for n, (track, key, query) in enumerate(jobs, 1):
        got = rss(query)
        fresh = 0
        for title, pub, pub_url, link, when in got:
            items += 1
            if title in seen_titles or link in known:
                continue
            seen_titles.add(title)
            if not allowed(pub_url, publishers):
                foreign += 1
                continue
            r = ss.resolve(title)
            if not r or not r.get("company"):
                no_company += 1
                continue
            name = r["company"]
            city, phrase = ss.city_for(title, name)
            ev = {"track": r["track"], "kind": r["kind"], "strength": r["strength"], "title": r["title"],
                  "publisher": pub, "publisher_url": pub_url, "link": link, "published_at": when,
                  "round": r.get("round"), "amount_usd": ss.money_usd(r["title"], inr),
                  "descriptor": ss.descriptor_of(title, name), "query": key}
            c = companies.setdefault(ss.name_key(name), {"names": {}, "events": [], "headline_city": []})
            c["names"][name] = c["names"].get(name, 0) + 1
            c["events"].append(ev)
            if city:
                c["headline_city"].append([city, phrase, r["title"]])
            fresh += 1
        log("  %3d/%d %-8s %-15s %3d items, %2d new events  %s" % (n, len(jobs), track, key, len(got), fresh,
                                                                   query.split(" after:")[-1]))
        time.sleep(DELAY)

    log("\n%d items read, %d from publishers outside the list, %d naming no single startup; %d companies"
        % (items, foreign, no_company, len(companies)))
    now = dt.datetime.now(dt.timezone.utc)
    staged = 0
    for key, c in sorted(companies.items(), key=lambda kv: -len(kv[1]["events"])):
        name = max(c["names"].items(), key=lambda kv: kv[1])[0]
        events = sorted(c["events"], key=lambda e: e.get("published_at") or "", reverse=True)
        geo = {"headline": c["headline_city"]}
        si, out = ss.score_inputs(name, events, geo, None, None, cfg, now)
        # the connector only asserts what the headlines prove; enrichment decides the rest
        keep = {k: si[k] for k in ("distress_evidence", "distress_recency", "major_or_oversized_signal",
                                    "acquired_signal", "small_deal", "recently_funded", "long_dead") if k in si}
        if c["headline_city"]:
            keep["mumbai_confirmed"] = si["mumbai_confirmed"]
            if si.get("geography_signal") == "outside_mumbai":
                keep["geography_signal"] = "outside_mumbai"
        raw = {"events": events, "headline_city": c["headline_city"], "scoring_inputs": keep,
               "descriptor": next((e["descriptor"] for e in events if e.get("descriptor")), ""),
               "why_fit": out.get("why_fit")}
        log("  %-30s %2d event(s)  %-22s %s" % (name[:30], len(events), (out.get("distress_label") or "")[:22],
                                               (c["headline_city"][0][0] if c["headline_city"] else "")))
        if not args.dry_run:
            db.run(lambda cur, _n=name, _l=events[0]["link"], _r=raw: cur.execute(
                "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
                " values (%s,%s,null,%s,%s,%s)", (seg_id, _n, SOURCE, _l, json.dumps(_r, default=str))))
        staged += 1

    if run_id:
        db.run(lambda cur: cur.execute(
            "update source_runs set finished_at=now(), status='succeeded', candidates_found=%s, candidates_new=%s,"
            " notes=%s where id=%s",
            (len(companies), staged, "searches=%d items=%d foreign=%d no_company=%d" % (len(jobs), items, foreign, no_company),
             run_id)))
    db.close()
    log("\nstaged %d startup(s). Next: promote chain, then Check startups (tools/enrich_startups.py) for %s" % (staged, SEGMENT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
