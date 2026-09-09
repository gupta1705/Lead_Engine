#!/usr/bin/env python3
"""yt_api.py -- the YouTube Data API v3 calls Segment 3 needs, with the quota
arithmetic written down.

Costs (units, from a 10,000/day quota):
  search.list          100   -- discovery only, never per lead
  channels.list          1   -- up to 50 channels per call
  playlistItems.list     1   -- the uploads playlist, 50 videos per call
  videos.list            1   -- durations for those 50 videos

So a channel's full profile (statistics + last 50 uploads with durations)
costs 3 units; a run that profiles a thousand channels spends 3,000.
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://www.googleapis.com/youtube/v3/"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
COST = {"search": 100}
USED = {"units": 0, "calls": 0}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.I)
SOCIAL = ("youtube.com", "youtu.be", "instagram.com", "twitter.com", "x.com", "facebook.com", "tiktok.com",
          "linktr.ee", "beacons.ai", "bio.link", "discord.gg", "discord.com", "t.me", "patreon.com", "spotify.com",
          "apple.com", "apple.co", "amzn.to", "amazon.com", "bit.ly", "goo.gl", "twitch.tv", "linkedin.com",
          "threads.net", "snapchat.com", "reddit.com", "whatsapp.com", "telegram.me", "paypal.com", "buymeacoffee.com")


class QuotaExhausted(Exception):
    pass


def api_key():
    v = os.environ.get("YOUTUBE_API_KEY")
    if v:
        return v
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith("YOUTUBE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("YOUTUBE_API_KEY is not set (env or .env)")


def call(endpoint, **params):
    params["key"] = api_key()
    url = API + endpoint + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    USED["units"] += COST.get(endpoint, 1)
    USED["calls"] += 1
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 403 and "quota" in body.lower():
            raise QuotaExhausted("YouTube quota exhausted for today")
        raise RuntimeError("youtube %s -> %d: %s" % (endpoint, e.code, body[:200]))


def iso_duration_seconds(s):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def channel_ref(url):
    """'https://www.youtube.com/@x' -> ('handle', '@x'); channel/UC.. -> ('id', 'UC..');
    c/name or user/name -> ('username', 'name')."""
    m = re.search(r"youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", url or "", re.I)
    if not m:
        return None, None
    ref = m.group(1)
    if ref.startswith("@"):
        return "handle", ref
    kind, _, name = ref.partition("/")
    return ("id", name) if kind == "channel" else ("username", name)


def channel_by_ref(url):
    kind, ref = channel_ref(url)
    if not kind:
        return None
    params = {"part": "snippet,statistics,contentDetails,topicDetails"}
    params["forHandle" if kind == "handle" else "id" if kind == "id" else "forUsername"] = ref
    items = call("channels", **params).get("items", [])
    return items[0] if items else None


def channels_by_ids(ids):
    out = []
    for i in range(0, len(ids), 50):
        out += call("channels", part="snippet,statistics,contentDetails,topicDetails",
                    id=",".join(ids[i:i + 50]), maxResults=50).get("items", [])
    return out


def recent_uploads(uploads_playlist_id, n=50):
    items = call("playlistItems", part="contentDetails,snippet", playlistId=uploads_playlist_id,
                 maxResults=min(n, 50)).get("items", [])
    vids = [i["contentDetails"]["videoId"] for i in items if i.get("contentDetails", {}).get("videoId")]
    if not vids:
        return []
    details = call("videos", part="contentDetails,snippet", id=",".join(vids[:50])).get("items", [])
    out = []
    for v in details:
        out.append({"id": v["id"], "title": v["snippet"].get("title", ""),
                    "published_at": v["snippet"].get("publishedAt"),
                    "description": (v["snippet"].get("description") or "")[:1500],
                    "duration_s": iso_duration_seconds(v.get("contentDetails", {}).get("duration"))})
    return out


def website_from(text, hosting=()):
    for u in URL_RE.findall(text or ""):
        host = urllib.parse.urlparse(u).netloc.lower()
        host = host[4:] if host.startswith("www.") else host
        if not host or any(host == s or host.endswith("." + s) for s in SOCIAL + tuple(hosting)):
            continue
        return u, host
    return None, None


def profile(item, uploads, cfg):
    """One channel + its last uploads -> the youtube_channel metadata block."""
    import datetime as dt
    ycfg = cfg.get("youtube_channel_discovery", {})
    long_min = int(ycfg.get("long_min_seconds", 1200))
    shorts_max = int(ycfg.get("shorts_max_seconds", 180))
    money_pats = [p.lower() for p in cfg.get("monetization_patterns", [])]
    sn, st = item.get("snippet", {}), item.get("statistics", {})
    durs = [u for u in uploads if u["duration_s"] is not None]
    long_ = [u for u in durs if u["duration_s"] >= long_min]
    shorts = [u for u in durs if u["duration_s"] <= shorts_max]
    dates = sorted(u["published_at"] for u in uploads if u.get("published_at"))
    upm = None
    if len(dates) >= 2:
        first = dt.datetime.fromisoformat(dates[0].replace("Z", "+00:00"))
        last = dt.datetime.fromisoformat(dates[-1].replace("Z", "+00:00"))
        span_days = max((last - first).days, 7)
        upm = round(len(dates) / (span_days / 30.0), 1)
    blob = (sn.get("description", "") + " " + " ".join(u["description"] for u in uploads[:20])).lower()
    hits = sorted({p for p in money_pats if p in blob})[:8]
    email = next((e for e in EMAIL_RE.findall(sn.get("description", "") + " " + " ".join(u["description"] for u in uploads[:5]))
                  if not e.lower().endswith(("@youtube.com", "@google.com"))), None)
    website, domain = website_from(sn.get("description", ""), cfg.get("hosting_providers", ()))
    topics = [t.rsplit("/", 1)[-1].replace("_", " ") for t in item.get("topicDetails", {}).get("topicCategories", [])]
    custom = sn.get("customUrl") or ""
    return {
        "channel_id": item["id"],
        "url": "https://www.youtube.com/" + (custom if custom.startswith("@") else "channel/" + item["id"]),
        "handle": custom or None, "title": sn.get("title"), "country": sn.get("country"),
        "language": sn.get("defaultLanguage"), "published_at": sn.get("publishedAt"),
        "subscribers": int(st.get("subscriberCount") or 0), "video_count": int(st.get("videoCount") or 0),
        "view_count": int(st.get("viewCount") or 0), "topics": topics[:6],
        "description": (sn.get("description") or "")[:600], "website": website, "website_domain": domain,
        "email_in_description": email.lower() if email else None, "monetization_hits": hits,
        "recent": {"sampled": len(uploads), "long_count": len(long_), "shorts_count": len(shorts),
                   "medium_count": len(durs) - len(long_) - len(shorts),
                   "shorts_share": round(len(shorts) / len(durs), 3) if durs else None,
                   "avg_long_minutes": round(sum(u["duration_s"] for u in long_) / len(long_) / 60) if long_ else None,
                   "uploads_per_month": upm, "last_upload_at": dates[-1] if dates else None,
                   "latest_title": uploads[0]["title"] if uploads else None},
    }


def inputs_from_channel(yc, cfg, now):
    """scoring_inputs a channel profile can settle. Absent keys stay absent
    (Invariant 1); the caller merges these over what discovery already knew."""
    import datetime as dt
    geo, langs = cfg.get("geography", {}), cfg.get("languages", {})
    ycfg = cfg.get("youtube_channel_discovery", {})
    majors = [m.lower() for m in cfg.get("major_networks", [])]
    r = yc["recent"]
    si = {}
    total = r["long_count"] + r["shorts_count"] + r["medium_count"]
    if total:
        est_long = yc["video_count"] * (r["long_count"] / total)
        si["archive_size"] = 1.0 if est_long >= 100 else 0.5 if est_long >= 40 else 0.0
        if r["shorts_share"] is not None:
            si["shorts_gap"] = 1.0 if r["shorts_share"] < 0.10 else 0.5 if r["shorts_share"] < 0.30 else 0.0
        si["video_first"] = 1.0 if r["long_count"] >= int(ycfg.get("min_recent_long", 10)) else 0.0
    if r["uploads_per_month"] is not None:
        si["cadence"] = 1.0 if r["uploads_per_month"] >= 4 else 0.5 if r["uploads_per_month"] >= 2 else 0.0
    subs = yc["subscribers"]
    si["audience_band"] = 1.0 if 10_000 <= subs <= 1_000_000 else 0.5 if 3_000 <= subs < 10_000 or 1_000_000 < subs <= 3_000_000 else 0.0
    si["oversized_signal"] = subs > 5_000_000          # gate: not a clipping customer
    si["oversized_audience"] = 1.0 if subs > 2_000_000 else 0.0   # penalty band below the gate
    si["monetization_signals"] = 1.0 if len(yc["monetization_hits"]) >= 2 else 0.5 if yc["monetization_hits"] else 0.0
    if yc.get("email_in_description"):
        si["reachable_contact"] = 1.0
    elif yc.get("website"):
        si["reachable_contact"] = 0.5
    if r["last_upload_at"]:
        age = (now - dt.datetime.fromisoformat(r["last_upload_at"].replace("Z", "+00:00"))).days
        si["activity_signal"] = "active" if age <= 90 else "confirmed_dormant" if age > 180 else "quiet"
    c = (yc.get("country") or "").upper()
    if c in geo.get("disallowed_countries", []):
        si["country_signal"] = "disallowed"
    elif c in geo.get("allowed_countries", []):
        si["country_signal"] = "allowed"
    lang = (yc.get("language") or "").lower().split("-")[0]
    if lang:
        si["language_match"] = 1.0 if lang in langs.get("full", []) else 0.5 if lang in langs.get("partial", []) else 0.0
    elif c == "IN":
        si["language_match"] = 1.0
    topics = " ".join(yc.get("topics", [])).lower()
    si["excluded_category_signal"] = bool(re.search(r"\bmusic\b|children", topics))
    si["has_reachable_presence"] = True
    title = (yc.get("title") or "").lower()
    major = any(re.search(r"\b" + re.escape(m) + r"\b", title) for m in majors)
    si["major_network_signal"] = bool(major)
    si["network_owned"] = 1.0 if major else 0.0
    return si


def why_from_channel(yc):
    r = yc["recent"]
    return ("YouTube: %s subscribers, %d videos; among the last %d uploads %d are long-form (avg %s min) and %d are shorts; %s."
            % (f"{yc['subscribers']:,}", yc["video_count"], r["sampled"], r["long_count"],
               r["avg_long_minutes"] if r["avg_long_minutes"] else "?", r["shorts_count"],
               ("business email in the channel description" if yc.get("email_in_description") else
                "website in the channel description" if yc.get("website") else "no contact route in the description")))
