#!/usr/bin/env python3
"""discover_clipping_networks.py -- LCX Clipping: the publishers behind several shows, as leads of their own.

    python tools/discover_clipping_networks.py [--min-shows 2] [--dry-run]

The owner, 2026-11-12 (from the research on Clipping leads): "add lead pools where one person decides for a budget:
podcast production companies and small networks, as white-label partners (one yes covers many shows)".

No new requests: the shows the podcast harvest already read carry their publisher (Apple's artist, the feed's
author). A publisher with --min-shows or more shows in the pool, that is not a major network (config
major_networks: those have their own editors) nor a person's name, is staged as one lead, kind "network":
  * its shows, their episodes added up, its best cadence, revenue signals and language;
  * the address its shows publish, when one address (or one domain) serves them -- the publisher's, not a host's;
  * its website as the lead's domain, unless a show already holds that domain (the promote step would merge the
    network into that show), in which case the site is kept on the lead only.
Staged as source "publisher_group"; the promote chain scores and gates it like any other lead. Idempotent: a
publisher already staged or already a lead is skipped.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import personname

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
SOURCE = "publisher_group"
GENERIC = {"unknown", "various", "various artists", "podcast", "podcasts", "the podcast", "anonymous", "n/a", "na"}
FREE = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "me.com", "aol.com", "protonmail.com",
        "proton.me", "live.com", "msn.com", "ymail.com"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def host_of(url):
    m = re.match(r"https?://(?:www\.)?([^/:?#]+)", url or "", re.I)
    return m.group(1).lower() if m else None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def group_leads(rows, majors, min_shows):
    """rows: (name, domain, status, metadata) of the segment's podcast shows -> {publisher key: lead dict}."""
    by = collections.defaultdict(list)
    names = {}
    for name, domain, status, meta in rows:
        pf = meta.get("podcast_feed") or (meta.get("discovery_raw") or {}).get("apple_podcasts", {}).get("podcast_feed") or {}
        pub = ((meta.get("discovery_raw") or {}).get("apple_podcasts") or {}).get("artist") or pf.get("author") or ""
        key = re.sub(r"\s+", " ", pub).strip().lower()
        if len(key) < 4 or key in GENERIC or not re.search(r"[a-z]", key):
            continue
        if any(re.search(r"\b" + re.escape(m), key) for m in majors):    # "iheartpodcast" in "iheartpodcasts"
            continue
        by[key].append((name, domain, status, meta, pf))
        names.setdefault(key, re.sub(r"\s+", " ", pub).strip())
    out = {}
    for key, shows in by.items():
        if len(shows) < min_shows:
            continue
        display = names[key]
        # a person who hosts two shows is a creator, not a publisher: their shows are leads already
        if personname.looks_like_person(display) and not re.search(r"\b(network|media|studios?|productions?|podcasts?|"
                                                                     r"group|inc|llc|ltd|company)\b", key):
            continue
        si_list = [s[3].get("scoring_inputs") or {} for s in shows]
        episodes = sum(int(num(s[4].get("episode_count")) or 0) for s in shows)
        cadence = max((num(s[4].get("cadence_per_month")) or 0) for s in shows)
        hits = sorted({h for s in shows for h in (s[4].get("monetization_hits") or [])})[:8]
        emails = collections.Counter((s[4].get("owner_email") or "").lower() for s in shows if s[4].get("owner_email"))
        sites = collections.Counter(host_of(s[4].get("website")) for s in shows if host_of(s[4].get("website")))
        email = None
        if emails:
            top, n = emails.most_common(1)[0]
            dom = top.split("@")[-1]
            # one address for several shows, or one at the publisher's own site: the publisher's own
            if n >= 2 or (dom not in FREE and dom in sites):
                email = top
        site = sites.most_common(1)[0][0] if sites else None
        active = any(si.get("activity_signal") == "active" for si in si_list)
        langs = [num(si.get("language_match")) for si in si_list if num(si.get("language_match")) is not None]
        countries = {si.get("country_signal") for si in si_list if si.get("country_signal")}
        si = {"archive_size": 1.0 if episodes >= 100 else 0.5 if episodes >= 40 else 0.0,
              "cadence": 1.0 if cadence >= 4 else 0.5 if cadence >= 2 else 0.0,
              "monetization_signals": 1.0 if len(hits) >= 2 else 0.5 if hits else 0.0,
              "reachable_contact": 1.0 if email else 0.5 if site else 0.0,
              "has_reachable_presence": bool(email or site),
              "network_owned": 0.0, "major_network_signal": False, "company_run": 1.0}
        if langs:
            si["language_match"] = max(langs)
        if active:
            si["activity_signal"] = "active"
        elif all(x.get("activity_signal") == "confirmed_dormant" for x in si_list):
            si["activity_signal"] = "confirmed_dormant"
        if countries == {"disallowed"}:
            si["country_signal"] = "disallowed"
        us = [num(x.get("us_priority")) for x in si_list if num(x.get("us_priority")) is not None]
        if us:
            si["us_priority"] = max(us)
        show_names = [s[0] for s in shows]
        why = "Publishes %d shows in our pool (%s), %d episodes between them%s; one agreement covers every show." % (
            len(shows), ", ".join(show_names[:4]) + (" and more" if len(shows) > 4 else ""), episodes,
            ", the busiest %g a month" % cadence if cadence else "")
        out[key] = {"name": display[:200], "site": site, "email": email, "raw": {
            "kind": "network", "category": "network", "why_fit": why, "scoring_inputs": si,
            "network": {"shows": show_names[:40], "show_count": len(shows), "total_episodes": episodes,
                        "best_cadence_per_month": cadence or None, "monetization_hits": hits,
                        "website": ("https://" + site) if site else None, "contact_email": email}}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-shows", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)), cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    majors = [m.lower() for m in cfg.get("major_networks", [])]
    rows = db.run(lambda cur: (cur.execute(
        "select name, domain, status, metadata from entities where segment_id = %s and source = 'apple_podcasts'",
        (seg_id,)), cur.fetchall())[1])
    rows = [(n, d, s, m if isinstance(m, dict) else json.loads(m or "{}")) for n, d, s, m in rows]
    leads = group_leads(rows, majors, args.min_shows)
    taken_names = set(db.run(lambda cur: (cur.execute(
        "select lower(name) from entities where segment_id = %s union select lower(name) from staging_candidates"
        " where segment_id = %s", (seg_id, seg_id)), [r[0] for r in cur.fetchall()])[1]))
    taken_domains = {(d or "").lower() for _, d, _, _ in rows if d}
    staged = 0
    for key, lead in sorted(leads.items(), key=lambda kv: -kv[1]["raw"]["network"]["show_count"]):
        if lead["name"].lower() in taken_names:
            continue
        domain = lead["site"] if lead["site"] and lead["site"] not in taken_domains else None
        log("  %-40s %2d shows  %s  %s" % (lead["name"][:40], lead["raw"]["network"]["show_count"],
                                           lead["email"] or "-", domain or ("(site %s)" % lead["site"] if lead["site"] else "")))
        if not args.dry_run:
            db.run(lambda cur, _l=lead, _d=domain: cur.execute(
                "insert into staging_candidates (segment_id, name, domain, source, source_url, raw) values (%s,%s,%s,%s,%s,%s)",
                (seg_id, _l["name"], _d, SOURCE, _l["raw"]["network"]["website"], json.dumps(_l["raw"]))))
        staged += 1
    db.close()
    log("\n%d publisher(s) with %d+ shows; %d staged as network leads%s. Next: the promote chain."
        % (len(leads), args.min_shows, staged, " (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
