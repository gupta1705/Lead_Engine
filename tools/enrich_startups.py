#!/usr/bin/env python3
"""enrich_startups.py -- startup segment enrichment: place each startup, read
its website and its app, ask the news about it by name, and score it.

    python tools/enrich_startups.py [--limit 400] [--workers 6] [--force] [--no-site] [--dry-run]

For every open row in the segment that is new, or was last checked a week ago:

  1. EVENTS. The connector's headlines (metadata.discovery_raw.startup_news)
     join metadata.press_events, one per link.
  2. NEWS BY NAME. One Google News RSS search for the company's exact name with
     city, funding and distress words, from the listed publishers only. A
     headline counts only when it names the company: it adds a round, a later
     trouble, a sale ("X acquires <it>"), or a place ("Mumbai-based <it>").
  3. WEBSITE. Its domain, or one found by trying the obvious ones and keeping a
     page only when it names the company AND reads Indian (a rupee sign, +91, an
     Indian city, Pvt Ltd, a .in address) -- a guess that fails either test is
     somebody else's site. robots.txt honoured; a few pages per site, two
     seconds apart. From the pages: a Mumbai-region address or PIN, another
     city's, a closing notice, a parked or for-sale page, App Store links.
  4. APP. Apple's public lookup for an App Store app the site links to: when it
     was last updated and how many ratings it has.
  5. SCORE. tools/startup_signals.score_inputs(), the function the connector
     uses too, sets the scoring inputs and the words a reviewer reads. A key it
     could not assess is left out, so the zero-unverified rule records it.

News searches run one at a time (Google News is one host); site reads run in
parallel across different hosts. Every row commits on its own and carries a
stamp, so an interrupted pass resumes. Then run the promote chain.
"""
import argparse
import datetime as dt
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db  # noqa: E402
import startup_signals as ss  # noqa: E402
import enrich_sitescrape as site_io  # noqa: E402   fetch() and robots_for(), the B1 politeness rules
import resolve_domains as rd  # noqa: E402            is_third_party()
from discover_startup_news import rss, allowed  # noqa: E402

SEGMENT = os.environ.get("SEGMENT_SLUG", "startup-acquisitions")
VERSION = "v1"
RSS_DELAY = 2.2
SITE_DELAY = 2.0

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------------- news
CITY_WORDS = "Mumbai OR Bengaluru OR Bangalore OR Delhi OR Gurugram OR Gurgaon OR Noida OR Pune OR Hyderabad OR Chennai"
EVENT_WORDS = 'raises OR funding OR "shuts down" OR layoffs OR "lays off" OR acquires OR acquired OR insolvency OR startup'


def news_by_name(name, publishers, inr):
    """(new events, headline city cues, {'mumbai': n, 'outside': n}) from one search."""
    got = rss('"%s" (%s OR %s)' % (name.replace('"', ""), CITY_WORDS, EVENT_WORDS))
    events, heads, counts = [], [], {"mumbai": 0, "outside": 0}
    for title, pub, pub_url, link, when in got:
        if not allowed(pub_url, publishers) or not ss.mentions(title, name):
            continue
        hit = re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(name), title, re.I)
        city, phrase = ss.city_for(title, hit.group(0) if hit else name)
        if city:
            counts[city] += 1
            heads.append([city, phrase, ss.clean_title(title)])
        r = ss.resolve(title)
        if r and r.get("company") and ss.name_key(r["company"]) == ss.name_key(name):
            events.append({"track": r["track"], "kind": r["kind"], "strength": r["strength"], "title": r["title"],
                           "publisher": pub, "publisher_url": pub_url, "link": link, "published_at": when,
                           "round": r.get("round"), "amount_usd": ss.money_usd(r["title"], inr),
                           "descriptor": ss.descriptor_of(title, name), "query": "by_name"})
        elif ss.acquired_in(title, name):
            events.append({"track": "sale", "kind": "acquired", "strength": 0.0, "title": ss.clean_title(title),
                           "publisher": pub, "publisher_url": pub_url, "link": link, "published_at": when,
                           "query": "by_name"})
    return events, heads, counts


# ------------------------------------------------------------------- site
MMR_RX = re.compile(r"\b(Navi Mumbai|Mumbai|Thane|Bombay|Powai|Andheri|Bandra Kurla Complex|Bandra|Lower Parel|Worli|"
                    r"Goregaon|Malad|Vikhroli|BKC|Vashi|Airoli|Juhu|Kurla|Chembur|Ghatkopar|Borivali|Kandivali|Dadar|"
                    r"Prabhadevi|Santacruz|Vile Parle|Mulund|Belapur|Kharghar)\b")
OTHER_RX = re.compile(r"\b(Bengaluru|Bangalore|New Delhi|Delhi|Gurugram|Gurgaon|Noida|Pune|Hyderabad|Chennai|Kolkata|"
                      r"Ahmedabad|Jaipur|Kochi|Chandigarh|Indore|Lucknow|Coimbatore)\b")
MMR_PIN = re.compile(r"(?:,|-|–|pin(?:code)?:?|mumbai|thane|maharashtra)\s*(40[01]\s?\d{3})\b", re.I)
OTHER_PIN = re.compile(r"(?:,|-|–|pin(?:code)?:?|karnataka|delhi|haryana|telangana|tamil nadu|uttar pradesh|kerala)\s*"
                       r"((?:560|110|122|201|411|500|600|700|380|302|682|160|452|226|641)\s?\d{3})\b", re.I)
INDIA_CUE = re.compile(r"₹|\+91|\bIndia\b|\bPvt\.?\s*Ltd\b|\bPrivate Limited\b|\bLLP\b|\bMumbai\b|\bBengaluru\b|"
                       r"\bBangalore\b|\bDelhi\b|\bGurugram\b|\bPune\b|\bHyderabad\b|\bChennai\b", re.I)
CLOSED = re.compile(r"we\s+(?:have|'ve)\s+(?:shut\s+down|closed|wound\s+down|ceased)|we\s+are\s+(?:shutting\s+down|closing)"
                    r"|we're\s+(?:shutting\s+down|closing)|has\s+(?:shut\s+down|ceased\s+operations)|ceased\s+(?:its\s+)?operations"
                    r"|no\s+longer\s+(?:operational|in\s+operation|accepting\s+orders)|decided\s+to\s+shut\s+down"
                    r"|(?:services?|operations)\s+(?:has|have)\s+been\s+(?:discontinued|suspended)|permanently\s+closed"
                    r"|thank\s+you\s+for\s+being\s+(?:a\s+)?part\s+of\s+(?:our|this)\s+journey", re.I)
PARKED = re.compile(r"domain\s+(?:name\s+)?(?:is|may\s+be)\s+for\s+sale|buy\s+this\s+domain|this\s+domain\s+has\s+expired"
                    r"|domain\s+has\s+expired|parked\s+(?:free|domain|by)|sedoparking|parkingcrew|hugedomains|afternic"
                    r"|dan\.com|this\s+site\s+can.t\s+be\s+reached|account\s+(?:has\s+been\s+)?suspended", re.I)
APPSTORE = re.compile(r"(?:apps|itunes)\.apple\.com/[^\"'\s<>]*?/id(\d{6,12})")
PLAY = re.compile(r"play\.google\.com/store/apps/details\?id=([\w.]+)")


def text_of(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.S | re.I)
    return " ".join(re.sub(r"<[^>]+>", " ", t).split())


def resolves(domain):
    """DNS says the name exists. One retry: with several workers looking names up at once, a
    lookup can fail that succeeds a second later (first run, 2026-09-17: stratzy.in)."""
    for attempt in (1, 2):
        try:
            socket.getaddrinfo(domain, None)
            return True
        except socket.gaierror as e:
            if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)) or attempt == 2:
                return False
        except Exception:
            if attempt == 2:
                return False
        time.sleep(1.0)
    return False


def get_page(url):
    """(html, error) -- error is an HTTP code, 'unreachable' or None."""
    try:
        return site_io.fetch(url), None
    except urllib.error.HTTPError as e:
        return "", str(e.code)
    except Exception:
        return "", "unreachable"


def find_domain(name):
    """A website that is this startup's, or (None, reason).

    A guess is kept only when the page names the company AND something ties it
    to this company rather than a namesake: a .in address, an Indian marker on
    the page (a rupee sign, +91, an Indian city, Pvt Ltd), or -- for a
    distinctive name of seven letters or more -- the name in the page's own
    title. mentoria.com names Mentoria in its title and never says "India"; the
    first run's India-only rule threw it away."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    full = "".join(w.lower() for w in words)
    if len(full) < 4:
        return None, "name too short to guess a website from"
    stems = [full, full + "india", "get" + full, full + "app"]
    tlds = [".com", ".in", ".co.in", ".co", ".io", ".ai", ".app"]
    fetched = 0
    for stem in stems:
        for tld in tlds:
            dom = stem + tld
            if rd.is_third_party(dom) or not resolves(dom):
                continue
            fetched += 1
            html, err = get_page("https://%s/" % dom)
            time.sleep(SITE_DELAY)
            if not err and html:
                txt = text_of(html)
                title = text_of((re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [None, ""])[1])
                if ss.name_key(name) in ss.name_key(txt):
                    if tld in (".in", ".co.in") or INDIA_CUE.search(txt):
                        return dom, "guessed %s: the page names it and reads Indian" % dom
                    if len(full) >= 7 and ss.name_key(name) in ss.name_key(title):
                        return dom, "guessed %s: its own title names it" % dom
            if fetched >= 6:
                return None, "no candidate website named it"
    return None, "no candidate website named it"


def read_site(domain):
    """What the startup's own pages say about it."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if not resolves(domain):
        return {"status": "unreachable", "note": "%s no longer resolves" % domain, "domain": domain, "checked_at": now}
    rp, why = site_io.robots_for(domain)
    if rp is None:
        return {"status": "unread", "note": "%s: %s" % (domain, why), "domain": domain, "checked_at": now}
    pages, home_err = [], None
    for path in ("/", "/contact", "/contact-us", "/about", "/about-us"):
        url = "https://%s%s" % (domain, path)
        if not rp.can_fetch(site_io.UA, url):
            continue
        html, err = get_page(url)
        time.sleep(SITE_DELAY)
        if path == "/" and (err or not html):
            home_err = err or "empty"
            break
        if html:
            pages.append(html)
        if len(pages) >= 3:
            break
    if home_err in ("401", "403", "429", "503"):
        return {"status": "unread", "note": "%s refuses automated requests (HTTP %s)" % (domain, home_err),
                "domain": domain, "checked_at": now}
    if home_err:
        return {"status": "error" if home_err not in ("unreachable",) else "unreachable",
                "note": "%s homepage: %s" % (domain, "HTTP " + home_err if home_err.isdigit() else home_err),
                "domain": domain, "checked_at": now}
    if not pages:
        return {"status": "unread", "note": "%s: robots.txt keeps us out" % domain, "domain": domain, "checked_at": now}
    home = pages[0]
    txt = " ".join(text_of(p) for p in pages)
    title = text_of((re.search(r"<title[^>]*>(.*?)</title>", home, re.S | re.I) or [None, ""])[1])[:160]
    desc = (re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{0,300})', home, re.I) or [None, ""])[1]
    status, note = "up", "%s is up" % domain
    if PARKED.search(text_of(home)[:3000]):
        status, note = "parked", "%s is parked or for sale" % domain
    elif CLOSED.search(txt):
        m = CLOSED.search(txt)
        status, note = "closed", "%s says: \"...%s...\"" % (domain, txt[max(0, m.start() - 60):m.end() + 60].strip())
    m_hits = MMR_RX.findall(txt)
    m_pins = MMR_PIN.findall(txt)
    o_hits = OTHER_RX.findall(txt)
    o_pins = OTHER_PIN.findall(txt)
    city, phrase = None, None
    if (m_hits or m_pins) and not (o_hits or o_pins):
        city = "mumbai"
    elif (o_hits or o_pins) and not (m_hits or m_pins):
        city = "outside"
    elif m_pins and not o_pins:
        city = "mumbai"
    elif o_pins and not m_pins:
        city = "outside"
    elif m_hits or o_hits:
        city = "mixed"
    anchor = (MMR_PIN.search(txt) or MMR_RX.search(txt)) if city in ("mumbai", "mixed") else (
        OTHER_PIN.search(txt) or OTHER_RX.search(txt)) if city == "outside" else None
    if anchor:
        phrase = txt[max(0, anchor.start() - 70):anchor.end() + 20].strip()
    apps = list(dict.fromkeys(APPSTORE.findall(" ".join(pages))))
    plays = list(dict.fromkeys(PLAY.findall(" ".join(pages))))
    year = max([int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d)", " ".join(pages), re.I)] or [0])
    return {"status": status, "note": note + ("; copyright %d" % year if year else ""), "domain": domain,
            "city": city, "city_phrase": phrase, "title": title, "description": desc, "app_ids": apps[:3],
            "play_ids": plays[:3], "copyright_year": year or None, "checked_at": now}


def app_lookup(app_id):
    url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode({"id": app_id, "country": "in"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": site_io.UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8")).get("results") or []
    except Exception:
        return None
    if not res:
        return None
    a = res[0]
    last = a.get("currentVersionReleaseDate")
    months = None
    if last:
        months = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last.replace("Z", "+00:00"))).days / 30.44
    return {"name": a.get("trackName"), "url": a.get("trackViewUrl"), "ratings": a.get("userRatingCount") or 0,
            "last_update": last,
            "note": "%s on the App Store: %s ratings, last updated %s" % (
                a.get("trackName"), "{:,}".format(a.get("userRatingCount") or 0),
                ("%d months ago" % months) if months is not None else "unknown")}


def site_work(row, look_for_domain):
    """Everything the startup's own site and app say. Runs in a worker thread: no database here."""
    name, domain = row["name"], row["domain"]
    method = None
    if not domain and look_for_domain:
        domain, method = find_domain(name)
    site = read_site(domain) if domain else None
    if site and method:
        site["domain_method"] = method
    app = None
    if site and site.get("app_ids"):
        app = app_lookup(site["app_ids"][0])
    return row["id"], domain, method, site, app


# ---------------------------------------------------------------- rescore
def gates_fire(si, cfg):
    """The gates this segment's config would fire on these inputs."""
    fired = []
    for g in cfg.get("gates", []):
        key = str(g.get("input", "")).split(".")[-1]
        if key in si and str(si[key]).lower() == str(g.get("exclude_when")).lower():
            fired.append(g["key"])
    return fired


def rescore(db, seg_id, cfg, reopen, dry_run):
    """Recompute every row's inputs from the evidence already stored -- no network.

    For when the rules change. Amounts are re-read from each headline, because
    the first run's parser took "$100m AUM" for a round. With reopen, a row a
    GATE archived (never a person's rejection) goes back to review when the
    corrected rules no longer fire any gate."""
    now = dt.datetime.now(dt.timezone.utc)
    inr = float((cfg.get("startup_discovery") or {}).get("inr_per_usd", 85))
    rows = db.run(lambda cur: (cur.execute("""
        select id, name, status, status_reason, metadata from entities
        where segment_id = %s
          and (status in ('discovered', 'enriched', 'scored', 'ready_for_review')
               or (%s and status = 'archived' and status_reason like 'Gate %%'))""", (seg_id, reopen)), cur.fetchall())[1])
    changed = reopened = 0
    for rid, name, status, reason, meta in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        raw = (meta.get("discovery_raw") or {}).get("startup_news") or {}
        events = merge_events(meta.get("press_events"), raw.get("events"), name=name)
        for e in events:
            if e.get("title") and e.get("track") in ("funding", "distress"):
                e["amount_usd"] = ss.money_usd(e["title"], inr)
        heads = meta.get("headline_city") or raw.get("headline_city") or []
        geo = {"headline": heads, "news": meta.get("news_city") or {}}
        si, out = ss.score_inputs(name, events, geo, meta.get("site_health"), meta.get("app"), cfg, now)
        new_meta = dict(meta)
        new_meta.update(out)
        new_meta["press_events"] = events
        scoring = dict(meta.get("scoring_inputs") or {})
        scoring.update(si)
        new_meta["scoring_inputs"] = scoring
        new_meta["unverified_inputs"] = [k for k in (meta.get("unverified_inputs") or []) if k not in si]
        back = status == "archived" and not gates_fire(scoring, cfg)
        if back:
            new_meta["gate_reopened"] = {"at": now.isoformat(), "was": reason}
            reopened += 1
            log("  reopened %-30s (was: %s)" % (name[:30], (reason or "")[:60]))
        changed += 1
        if dry_run:
            continue
        db.run(lambda cur, _id=rid, _m=new_meta, _b=back: cur.execute(
            "update entities set metadata = %s, updated_at = now()"
            + (", status = 'ready_for_review', status_reason = null, status_changed_at = now()" if _b else "")
            + " where id = %s", (json.dumps(_m, default=str), _id)))
    log("\nrescored %d row(s), reopened %d that a gate had archived. Next: promote chain" % (changed, reopened))


# ------------------------------------------------------------------- main
def still_about(e, name):
    """The current headline rules still say this story is about this company. Events stored
    under the first run's rules can belong to someone else: 'Snabbit Strengthens Leadership
    with Acquihire of Pync Founders' was Snabbit's then and is Pync's now."""
    if e.get("kind") == "acquired":
        return ss.acquired_in(e.get("title"), name)
    r = ss.resolve(e.get("title") or "")
    return bool(r and r.get("company") and ss.name_key(r["company"]) == ss.name_key(name))


def merge_events(*lists, name=None):
    seen, out = set(), []
    for lst in lists:
        for e in lst or []:
            key = e.get("link") or e.get("title")
            if key and key not in seen and (name is None or still_about(e, name)):
                seen.add(key)
                out.append(e)
    return sorted(out, key=lambda e: e.get("published_at") or "", reverse=True)[:40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="revisit rows checked in the last week too")
    ap.add_argument("--no-site", action="store_true", help="news only; skip websites and apps")
    ap.add_argument("--sites-only", action="store_true", help="websites and apps only, for rows with no website read or found")
    ap.add_argument("--rescore", action="store_true", help="no network: recompute every row from stored evidence")
    ap.add_argument("--reopen-gated", action="store_true", help="with --rescore: return rows a gate archived that no gate fires on now")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    if args.rescore:
        rescore(db, seg_id, cfg, args.reopen_gated, args.dry_run)
        db.close()
        return 0
    disc = cfg.get("startup_discovery") or {}
    publishers = [p.lower() for p in disc.get("publishers", [])]
    inr = float(disc.get("inr_per_usd", 85))

    if args.sites_only:
        # rows whose website has never been read, or read without finding one
        where = "(%s or not (e.metadata ? 'site_health') or e.domain is null)" % ("true" if args.force else "false")
        params = (seg_id, args.limit)
    else:
        where = ("(%s or coalesce(e.metadata->>'startup_enrich_version', '') <> %%s"
                 " or (e.metadata->>'startup_enriched_at')::timestamptz < now() - interval '7 days')"
                 % ("true" if args.force else "false"))
        params = (seg_id, VERSION, args.limit)
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.domain, e.metadata
        from entities e
        where e.segment_id = %s
          and e.status in ('discovered', 'enriched', 'scored', 'ready_for_review')
          and """ + where + """
        order by (e.metadata ? 'startup_enriched_at'), e.created_at
        limit %s""", params), cur.fetchall())[1])
    held = dict(db.run(lambda cur: (cur.execute(
        "select domain, name from entities where segment_id=%s and domain is not null", (seg_id,)), cur.fetchall())[1]))
    log("segment %s: %d startup(s) to check%s\n" % (SEGMENT, len(rows), "  [DRY RUN]" if args.dry_run else ""))
    rows = [{"id": r[0], "name": r[1], "domain": r[2], "metadata": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}")}
            for r in rows]

    # 1-2. events and news by name, one search at a time; each row saved as soon as it is done,
    # so an interrupted pass keeps what it learned (the first run held it all until the end)
    for i, row in enumerate(rows, 1):
        meta = row["metadata"]
        raw = (meta.get("discovery_raw") or {}).get("startup_news") or {}
        ev, heads, counts = ([], [], meta.get("news_city") or {"mumbai": 0, "outside": 0}) if args.sites_only \
            else news_by_name(row["name"], publishers, inr)
        row["events"] = merge_events(meta.get("press_events"), raw.get("events"), ev, name=row["name"])
        row["heads"] = [list(h) for h in {tuple(h) for h in (meta.get("headline_city") or []) + (raw.get("headline_city") or []) + heads}]
        row["news_city"] = counts
        if args.sites_only:
            continue
        log("  news %3d/%d  %-30s %2d event(s), Mumbai %d / elsewhere %d" % (
            i, len(rows), row["name"][:30], len(row["events"]), counts.get("mumbai", 0), counts.get("outside", 0)))
        write_row(db, row, row["domain"], meta.get("site_health"), meta.get("app"), cfg, now, held, args.dry_run)
        time.sleep(RSS_DELAY)

    # 3-4. sites and apps, in parallel across hosts; each row saved when its site is read
    if not args.no_site:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futs = {pool.submit(site_work, row, True): row for row in rows}
            for n, f in enumerate(as_completed(futs), 1):
                row = futs[f]
                try:
                    _rid, domain, _method, site, app = f.result()
                except Exception as e:
                    log("  site worker failed for %s: %r" % (row["name"], e))
                    continue
                log("  site %3d/%d  %-30s %-28s %s" % (n, len(rows), row["name"][:30], (domain or "-")[:28],
                                                      (site or {}).get("status", "no website found")))
                row["metadata"] = fresh_meta(db, row["id"]) or row["metadata"]
                write_row(db, row, domain, site, app, cfg, now, held, args.dry_run)
    db.close()
    log("\nchecked %d startup(s). Next: promote chain for %s, so the new evidence is scored and gated" % (len(rows), SEGMENT))
    return 0


def fresh_meta(db, rid):
    got = db.run(lambda cur: (cur.execute("select metadata from entities where id = %s", (rid,)), cur.fetchone())[1])
    if not got:
        return None
    return got[0] if isinstance(got[0], dict) else json.loads(got[0] or "{}")


def write_row(db, row, domain, site, app, cfg, now, held, dry_run):
    """Score one row from everything known about it and save it. Returns 1 when written."""
    meta = row["metadata"]
    if domain and not row["domain"] and domain in held and held[domain] != row["name"]:
        site = dict(site or {}, note="%s is already the website of %s in this segment" % (domain, held[domain]))
        domain = None                          # a duplicate for a person to settle, not a second owner
    geo = {"headline": row["heads"], "news": row["news_city"]}
    si, out = ss.score_inputs(row["name"], row["events"], geo, site, app, cfg, now)
    new_meta = dict(meta)
    new_meta.update(out)
    new_meta["press_events"] = row["events"]
    new_meta["headline_city"] = row["heads"]
    new_meta["news_city"] = row["news_city"]
    new_meta["descriptor"] = next((e.get("descriptor") for e in row["events"] if e.get("descriptor")),
                                  meta.get("descriptor") or "")
    if site:
        new_meta["site_health"] = site
    if app:
        new_meta["app"] = app
    scoring = dict(meta.get("scoring_inputs") or {})
    scoring.update(si)
    new_meta["scoring_inputs"] = scoring
    new_meta["unverified_inputs"] = [k for k in (meta.get("unverified_inputs") or []) if k not in si]
    new_meta["startup_enriched_at"] = now.isoformat()
    new_meta["startup_enrich_version"] = VERSION
    if dry_run:
        return 0
    db.run(lambda cur, _id=row["id"], _m=new_meta, _d=domain if not row["domain"] else None: (
        cur.execute("update entities set metadata = %s, updated_at = now() where id = %s",
                    (json.dumps(_m, default=str), _id)),
        _d and cur.execute(
            "update entities set domain = %s where id = %s and domain is null and not exists ("
            " select 1 from entities o where o.segment_id = entities.segment_id and o.domain = %s)",
            (_d, _id, _d))))
    if domain and not row["domain"]:
        held[domain] = row["name"]
        row["domain"] = domain
    row["metadata"] = new_meta
    return 1


if __name__ == "__main__":
    sys.exit(main())
