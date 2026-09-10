#!/usr/bin/env python3
"""enrich_clipping.py -- Segment 3 enrichment: lift the discovery evidence,
add the YouTube half, find the PERSON behind the show, create the contact.

    python tools/enrich_clipping.py [--limit 300] [--yt-budget 6000] [--site-budget 120] [--force]

For every open-pool row in the segment that still needs work:

  1. LIFT. The promote chain files each connector's record under
     metadata.discovery_raw.<source>. Bring podcast_feed / youtube_channel /
     wikidata / origin / kind / why_fit up to the top level, where the UI, the
     drafts and the export read.
  2. YOUTUBE. A channel linked from the feed, found on the website's front
     page (robots honoured, one fetch), or the channel a carried-over row was
     discovered by, profiled for the shorts gap, audience, cadence,
     video-first. Inputs that were unassessed become assessed. A transient
     failure (timeout, 5xx, quota) is recorded and retried after a week; only
     a definitive answer is stamped as final.
  3. HOST. The person behind the show, from the feed's author or owner, the
     title ("with Doug Smith", "The Joe Rogan Experience"), or the channel
     description ("hosted by ..."). For a production house the company name
     is never mined for a person: the host comes from a named carried-over
     contact or the channel description, or stays unknown. Stored as
     metadata.host with a confidence; only high or medium is ever USED.
  4. CONTACT. The feed's owner address, a business email in the channel
     description, or the contacts a carried-over row brought. Recorded with
     its source; nothing is guessed. A contact whose name is really the
     show's name is corrected to the host, or cleared; any other name is left
     exactly as it is (an accent or an unusual name is not a reason to touch it).
  5. STAMP. clipping_enriched_at and clipping_enrich_version. Bumping
     ENRICH_VERSION revisits every row under new rules without --force, at
     the cost of no network calls unless a channel is still missing.

Then run the promote chain so the new evidence is scored and gated.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from dbconn import Db
import personname
import yt_api

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-clipping")
ENRICH_VERSION = 4                              # 4: review fixes to the name rules, 2026-09-10
OPEN = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")
YT_RE = re.compile(r"https?://(?:www\.|m\.)?youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", re.I)
LIFT = {"apple_podcasts": ("podcast_feed",), "youtube_api": ("youtube_channel",),
        "wikidata_channels": ("youtube_channel", "wikidata"), "tvf_pool": ("origin",)}
COMMON = ("why_fit", "kind", "hq_city", "hq_state")
EMAIL_STATUSES = {"unverified", "valid", "invalid", "catch_all", "unknown"}
CHANNEL_KEYS = ("shorts_gap", "audience_band", "video_first", "oversized_signal", "oversized_audience")
STRONGER_KEYS = ("archive_size", "cadence", "monetization_signals", "reachable_contact")
RETRY_AFTER_DAYS = 7


if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


def site_youtube_link(domain):
    """The first YouTube channel link on a site's front page.
    Returns (url, note, definitive): definitive is False for the transient
    failures worth retrying (unreachable robots.txt, timeouts, 5xx)."""
    from enrich_sitescrape import robots_for, fetch, UA
    rp, err = robots_for(domain)
    if rp is None:
        return None, err, False
    url = "https://%s/" % domain
    if not rp.can_fetch(UA, url):
        return None, "robots disallows", True
    try:
        html = fetch(url)
    except Exception as e:
        code = getattr(e, "code", None)
        return None, "%s%s" % (type(e).__name__, " %s" % code if code else ""), bool(code and 400 <= code < 500 and code != 403)
    m = YT_RE.search(html or "")
    return ("https://www.youtube.com/" + m.group(1), None, True) if m else (None, "no youtube link on the front page", True)


def profile_channel(url, cfg, now):
    item = yt_api.channel_by_ref(url)
    if not item:
        return None, None, None
    pl = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    uploads = yt_api.recent_uploads(pl, 50) if pl else []
    yc = yt_api.profile(item, uploads, cfg)
    return yc, yt_api.inputs_from_channel(yc, cfg, now), yt_api.why_from_channel(yc)


def stale(stamp, now):
    """A transient-failure record older than the retry window, or absent."""
    if not stamp or not stamp.get("at"):
        return True
    try:
        at = dt.datetime.fromisoformat(stamp["at"].replace("Z", "+00:00"))
    except ValueError:
        return True
    return (now - at).days >= RETRY_AFTER_DAYS


def host_for(name, kind, pf, yc, raw, pool):
    """The person behind the show. A company name is never mined."""
    if kind == "production_house" or pool:
        for c in sorted(pool.get("contacts") or [], key=lambda c: not c.get("is_primary")):
            fn = (c.get("full_name") or "").strip()
            if fn and personname.looks_like_person(fn):
                shaped = personname.extract_host(fn) or {}
                return {"name": shaped.get("name") or fn, "first_name": shaped.get("first_name"),
                        "display": fn, "confidence": "high", "source": "pool_contact"}
        return personname.extract_host("", description=(yc or {}).get("description"))
    return personname.extract_host(
        name, author=pf.get("author"), owner_name=pf.get("owner_name"),
        description=pf.get("description") or (yc or {}).get("description"),
        artist=(raw.get("apple_podcasts") or {}).get("artist"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--yt-budget", type=int, default=6000, help="quota units this run may spend on channels")
    ap.add_argument("--site-budget", type=int, default=120, help="websites to read for a YouTube link this run")
    ap.add_argument("--force", action="store_true", help="revisit every open row")
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)

    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    geo = cfg.get("geography", {})

    where, params = "", [seg_id, OPEN]
    if not args.force:
        where = (" and ((metadata->>'clipping_enriched_at') is null"
                 "  or coalesce((metadata->>'clipping_enrich_version')::int, 0) < %s"
                 "  or (metadata->'youtube_channel' is null and metadata->'youtube_lookup' is null"
                 "      and (metadata->'youtube_lookup_error' is null"
                 "           or (metadata->'youtube_lookup_error'->>'at')::timestamptz < now() - interval '%s days')"
                 "      and ((metadata->'podcast_feed'->>'youtube_url') is not null"
                 "           or (metadata->'site_youtube_lookup'->>'url') is not null"
                 "           or source_url ~* 'youtube\\.com/channel/'))"
                 "  or (domain is not null and metadata->'youtube_channel' is null and metadata->'site_youtube_lookup' is null"
                 "      and (metadata->'podcast_feed'->>'youtube_url') is null"
                 "      and (metadata->'site_youtube_error' is null"
                 "           or (metadata->'site_youtube_error'->>'at')::timestamptz < now() - interval '%s days')))"
                 % (ENRICH_VERSION, RETRY_AFTER_DAYS, RETRY_AFTER_DAYS))
    params.append(args.limit)
    rows = db.run(lambda cur: (cur.execute(
        "select id, name, domain, source, source_url, metadata from entities where segment_id=%s and status in %s"
        + where + " order by fit_score desc nulls last, created_at desc limit %s", params), cur.fetchall())[1])
    log("segment %s: %d row(s) to enrich%s" % (SEGMENT, len(rows), " (force)" if args.force else ""))

    lifted = hosts = contacts = renamed = yt_done = yt_failed = sites = 0
    for n, (eid, name, domain, source, source_url, meta) in enumerate(rows, 1):
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        raw = meta.get("discovery_raw") or {}
        changed = {}

        # 1. lift
        for src, keys in LIFT.items():
            r = raw.get(src) or {}
            for key in keys:
                if key not in meta and r.get(key):
                    changed[key] = r[key]
        for key in COMMON:
            if not meta.get(key):
                for src in raw:
                    if (raw.get(src) or {}).get(key):
                        changed[key] = raw[src][key]
                        break
        if any(k in changed for k in ("podcast_feed", "youtube_channel", "wikidata", "origin")):
            lifted += 1
        pf = changed.get("podcast_feed") or meta.get("podcast_feed") or {}
        yc = changed.get("youtube_channel") or meta.get("youtube_channel")
        kind = changed.get("kind") or meta.get("kind")
        pool = raw.get("tvf_pool") or next((v for k, v in raw.items() if k.startswith("pool:")), None) or {}

        # 2. youtube: the feed's link, a link found on the site, or the channel the row came from
        si_new, why_extra = {}, None
        yt_url = None
        if not yc:
            yt_url = (pf.get("youtube_url") or (meta.get("site_youtube_lookup") or {}).get("url")
                      or (source_url if source_url and YT_RE.search(source_url) else None))
            can_lookup = (not yt_url and domain and not meta.get("site_youtube_lookup")
                          and stale(meta.get("site_youtube_error"), now)
                          and sites < args.site_budget and yt_api.USED["units"] + 3 <= args.yt_budget)
            if can_lookup:
                sites += 1
                found, note, definitive = site_youtube_link(domain)
                if definitive:
                    changed["site_youtube_lookup"] = {"at": now.isoformat(), "url": found, "note": note}
                else:
                    changed["site_youtube_error"] = {"at": now.isoformat(), "error": note}
                yt_url = found
                time.sleep(1.0)
        if yt_url and not yc and stale(meta.get("youtube_lookup_error"), now) and not meta.get("youtube_lookup"):
            if yt_api.USED["units"] + 3 <= args.yt_budget:
                try:
                    yc2, si_new, why_extra = profile_channel(yt_url, cfg, now)
                    if yc2:
                        yc = yc2
                        changed["youtube_channel"] = yc
                        yt_done += 1
                    else:
                        si_new, why_extra = {}, None
                        yt_failed += 1
                        changed["youtube_lookup"] = {"url": yt_url, "result": "not found", "at": now.isoformat()}
                except yt_api.QuotaExhausted as e:
                    log("STOP: %s" % e)
                    break
                except Exception as e:
                    si_new, why_extra = {}, None
                    yt_failed += 1
                    changed["youtube_lookup_error"] = {"url": yt_url, "error": str(e)[:200], "at": now.isoformat()}
        # a channel already held gets its inputs recomputed, so a rubric change
        # reaches rows promoted before it existed
        if yc and not si_new:
            try:
                si_new = yt_api.inputs_from_channel(yc, cfg, now)
            except Exception as e:
                log("  channel inputs failed for %s: %r" % (name[:40], e))

        # 3. host, after the channel so its description counts
        host = meta.get("host") or {}
        if args.force or not host.get("checked_at") or "youtube_channel" in changed \
                or int(meta.get("clipping_enrich_version") or 0) < ENRICH_VERSION:
            h = host_for(name, kind, pf, yc, raw, pool)
            host = dict(h or {"name": None, "confidence": "none"})
            host["checked_at"] = now.isoformat()
            changed["host"] = host
            if host.get("name"):
                hosts += 1
        host_name = host.get("name") if host.get("confidence") in ("high", "medium") else None

        # 4. contacts: published address, channel email, or carried-over pool contacts
        wanted = []                                 # (email, who, role, source, status)
        if pf.get("owner_email"):
            wanted.append((pf["owner_email"].lower(), host_name, "Host", "podcast_rss", "unverified"))
        elif (yc or {}).get("email_in_description"):
            wanted.append((yc["email_in_description"].lower(), host_name, "Host / producer", "youtube_description", "unverified"))
        for c in (pool.get("contacts") or []):
            if c.get("email"):
                wanted.append((c["email"].lower(), c.get("full_name"), c.get("role_title") or "Contact",
                               "pool:" + (c.get("source") or "tvf"),
                               c.get("email_status") if c.get("email_status") in EMAIL_STATUSES else "unverified"))
        for email, who, role, src, status in wanted:
            ins = db.run(lambda cur, _e=eid: (cur.execute(
                "insert into contacts (entity_id, full_name, role_title, email, email_status, source, is_primary)"
                " select %s,%s,%s,%s,%s,%s, not exists (select 1 from contacts where entity_id=%s and is_primary)"
                " where not exists (select 1 from contacts where entity_id=%s and lower(email)=%s) returning id",
                (_e, (who or None), role, email, status, src, _e, _e, email)), cur.fetchone())[1])
            if ins:
                contacts += 1
        # a contact whose name is really the show's is corrected; any other name is left alone
        show_strings = {s.strip().lower() for s in (name, pf.get("author"), pf.get("owner_name"), (yc or {}).get("title")) if s}
        for cid, fn in db.run(lambda cur, _e=eid: (cur.execute(
                "select id, full_name from contacts where entity_id=%s", (_e,)), cur.fetchall())[1]):
            if fn and fn.strip().lower() not in show_strings:
                continue
            new = host_name if host_name else None
            if new != fn and (new or fn):
                db.run(lambda cur, _c=cid, _n=new: cur.execute(
                    "update contacts set full_name=%s, updated_at=now() where id=%s", (_n, _c)))
                renamed += 1

        # 5. inputs: the feed's language REGION settles the country for older rows
        si = dict(meta.get("scoring_inputs") or {})
        unverified = list(meta.get("unverified_inputs") or [])
        lang = pf.get("language") or ""
        region = lang.split("-")[1].lower() if "-" in lang else ""
        if re.fullmatch(r"[a-z]{2}", region) and (si.get("us_priority") is None or "us_priority" in unverified):
            for k, v in yt_api.country_inputs(region, geo).items():
                si_new.setdefault(k, v)
        for k, v in si_new.items():
            cur_v = si.get(k)
            take = (k in CHANNEL_KEYS or cur_v is None or k in unverified
                    or (k in STRONGER_KEYS and isinstance(cur_v, (int, float)) and isinstance(v, (int, float)) and v > cur_v)
                    or k not in STRONGER_KEYS)
            if take:
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
        changed["clipping_enrich_version"] = ENRICH_VERSION

        db.run(lambda cur, _e=eid, _c=changed: cur.execute(
            "update entities set metadata = metadata || %s::jsonb, updated_at = now(),"
            " status = case when status = 'discovered' then 'enriched' else status end where id = %s",
            (json.dumps(_c, default=str), _e)))
        log("  %3d. %-38s %s%s%s%s" % (n, name[:38],
                                        ("host=" + host["name"][:22] + " ") if host.get("name") else "",
                                        "contact " if wanted else "", "yt " if "youtube_channel" in changed else "",
                                        "site " if "site_youtube_lookup" in changed or "site_youtube_error" in changed else ""))

    db.close()
    log("\n%d lifted, %d hosts named, %d contacts created, %d contact names corrected, %d channels profiled"
        " (%d lookups failed), %d sites read, %d quota units used."
        % (lifted, hosts, contacts, renamed, yt_done, yt_failed, sites, yt_api.USED["units"]))
    log("Next: promote chain for %s to score and gate the new evidence." % SEGMENT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
