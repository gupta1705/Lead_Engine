#!/usr/bin/env python3
"""send_window.py -- when an approved email goes out: at its own second between 10:00 and 10:30 in its
recipient's time zone. Pure: no database, no clock of its own (every function is handed "now").

The owner, 2026-10-12: "I want you to send mails to the sender's time region between 10 to 10:30AM and
that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13 and so
on". Read as where the mail is going: 10:00 in Mumbai is 05:30 in London, and an email that lands before
its reader's day starts sits under the morning's pile. One line of config flips it to the sender's clock
(timezone_of "sender").

WHAT EACH PART DOES
  window_cfg(outreach cfg)   the project's outreach.send_window with its defaults filled, or None (no block,
                             or enabled false): a project without it sends exactly as before
  recipient_zone(meta, ...)  the IANA zone of the person an email goes to, and why, from what the lead
                             holds (below); unknown -> fallback_timezone
  windows(zone, ...)         each eligible day's window in UTC: Monday to Friday in THAT zone, wall times
                             through the zone's own DST rules
  pick_moment(lo, hi, ...)   one whole second, uniform over the seconds still free: never two sends from
                             one address closer than the spacing (min_gap_seconds + 10, so the sender's
                             1-5 s of jitter cannot break the 45 s gap)
  send_label / window_label  the words every page shows: "Tue 14 Oct, 10:17 New York time (19:47 IST)"
  plan_key(wcfg)             a fingerprint of the settings a time was drawn under: a stored time whose
                             fingerprint differs is placed again (tools/outreach_policy.settle_schedule)

WHERE A RECIPIENT IS, best evidence first (each kind of lead holds a different subset):
  1 the recipient's own Apollo record (metadata.apollo_people[id]; matched by contacts.notes
    "apollo:<id>" or the LinkedIn URL) -- a person in London at a US company reads at London's 10:00
  2 the company, from a source that knows: FDIC (state, city), OpenStreetMap (city, country), Wikidata
    (country), metadata.hq_state / hq_city, an Apollo company saved from the search page (metadata.apollo),
    and metadata.hq_country -- unless the only country the lead's records hold is the one its Apollo
    harvest searched in (discovery_raw.*.apollo_search), which says where it was looked for, not where
    it is
  3 other people at the company (Apollo): their state and city, never their country
  4 phone numbers: a +1 number's area code gives the state ("phone area code 312"); any other calling
    code gives the country only
  5 the harvest's search country (weak)
  6 a channel's or a feed's country: YouTube's channel country, Wikidata's, the YouTube search region,
    a podcast's language tag ("en-gb"), the Apple Podcasts chart it came from
  7 the project's assumed_country (US Production Houses: "US", the AICP is American)
The country is the first that names one; the state the first that is a state OF THAT COUNTRY ("IN" is
Indiana only in the US); the city the first in that country the tables know. The zone is the first of:
a city that keeps another zone than its state (tz_places.CITY_OVERRIDES: El Paso), the state, a known
city, the project's country_zones (US Production Houses: US -> Los Angeles), the country's main business
zone (US -> New York), the country's only zone. The reason is stored with the time and shown on the page.

All arithmetic is in UTC. A wall time is turned into UTC once, by the zone (the first of two in an
autumn fold, the next real minute in a spring gap); no timedelta is ever added to an aware local time.
"""
import datetime as dt
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import tz_places as tp  # noqa: E402

UTC = dt.timezone.utc

DEFAULTS = {
    "enabled": True,
    "start": "10:00",
    "end": "10:30",
    "timezone_of": "recipient",          # or "sender": every email at the sender's 10:00-10:30
    "sender_timezone": "Asia/Kolkata",
    "fallback_timezone": "Asia/Kolkata",  # a lead that names no place at all
    "assumed_country": None,              # ISO2: the country a project's leads are in when a lead says nothing
    "country_zones": {},                  # {ISO2: IANA zone}: this project's zone for a country with several
    "weekdays_only": True,                # Monday to Friday in the recipient's zone
    "min_gap_seconds": 45,                # never two sends from one address closer than this
    "min_lead_seconds": 120,              # an approval is never placed sooner than this
    "guidance": None,
}
TAIL_S = 60            # no moment in a window's last minute: a send that starts at 10:29:59 can finish late
JITTER_ROOM_S = 10     # spacing_s = min_gap_seconds + this: the sender's 1-5 s of jitter never breaks the gap
LEAD_LEFT_S = 120      # next_window: a window with less than this left after the lead time is passed over
PLAN_KEYS = ("timezone_of", "start", "end", "sender_timezone", "fallback_timezone", "assumed_country",
             "country_zones", "weekdays_only")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ------------------------------------------------------------- the data
_CHECKED = False


def self_check():
    """The zone data is here and readable. Raises RuntimeError otherwise: the app refuses to start (a missing
    tzdata would send every email at the fallback zone's 10:00)."""
    global _CHECKED
    if _CHECKED:
        return True
    try:
        ZoneInfo("America/New_York")
        if tp.LOAD_ERROR:
            raise RuntimeError(tp.LOAD_ERROR)
        from importlib import resources
        if "America/New_York" not in resources.files("tzdata").joinpath("zoneinfo/zone.tab").read_text(
                encoding="utf-8"):
            raise RuntimeError("zone.tab has no America/New_York")
    except Exception as e:                  # noqa: BLE001 -- one plain message, the cause chained
        raise RuntimeError("time-zone data missing: pip install tzdata") from e
    _CHECKED = True
    return True


def zone_ok(name):
    try:
        ZoneInfo(str(name))
        return True
    except Exception:                        # noqa: BLE001 -- ZoneInfoNotFoundError, ValueError on a bad key
        return False


def _hhmm(s):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(s or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


# ------------------------------------------------------------- the config
def _block(outreach_cfg):
    cfg = outreach_cfg or {}
    if isinstance(cfg, str):
        cfg = json.loads(cfg or "{}")
    if "send_window" not in cfg and isinstance(cfg.get("outreach"), dict):
        cfg = cfg["outreach"]                # handed a whole segment config
    return cfg.get("send_window")


def config_problems(outreach_cfg):
    """What is wrong with a project's outreach.send_window, in plain words; [] when it is fine or absent
    (tools/verify_repo.py runs it over every config)."""
    b = _block(outreach_cfg)
    if b is None:
        return []
    if not isinstance(b, dict):
        return ["outreach.send_window must be an object"]
    out = []
    extra = sorted(set(b) - set(DEFAULTS))
    if extra:
        out.append("outreach.send_window has keys it does not know: %s" % ", ".join(extra))
    w = dict(DEFAULTS, **b)
    if not isinstance(w["enabled"], bool):
        out.append("send_window.enabled must be true or false")
    a, z = _hhmm(w["start"]), _hhmm(w["end"])
    if not a:
        out.append("send_window.start must be HH:MM, e.g. \"10:00\" (got %r)" % (w["start"],))
    if not z:
        out.append("send_window.end must be HH:MM, e.g. \"10:30\" (got %r)" % (w["end"],))
    if a and z and a >= z:
        out.append("send_window.start (%s) must be before its end (%s), on the same day" % (w["start"], w["end"]))
    if w["timezone_of"] not in ("recipient", "sender"):
        out.append("send_window.timezone_of must be \"recipient\" or \"sender\" (got %r)" % (w["timezone_of"],))
    for k in ("sender_timezone", "fallback_timezone"):
        if not zone_ok(w[k]):
            out.append("send_window.%s %r is not a time zone (use an IANA name such as Asia/Kolkata)" % (k, w[k]))
    ac = w["assumed_country"]
    if ac is not None and str(ac).upper() not in tp.ISO_NAME:
        out.append("send_window.assumed_country must be a two-letter country code such as US (got %r)" % (ac,))
    cz = w["country_zones"]
    if not isinstance(cz, dict):
        out.append("send_window.country_zones must be an object {country code: time zone}")
    else:
        for k, v in cz.items():
            if str(k).upper() not in tp.ISO_NAME:
                out.append("send_window.country_zones: %r is not a two-letter country code" % (k,))
            if not zone_ok(v):
                out.append("send_window.country_zones[%s]: %r is not a time zone" % (k, v))
    if not isinstance(w["weekdays_only"], bool):
        out.append("send_window.weekdays_only must be true or false")
    for k in ("min_gap_seconds", "min_lead_seconds"):
        v = w[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or v > 3600:
            out.append("send_window.%s must be a number of seconds from 0 to 3600 (got %r)" % (k, v))
    if not out and a and z:
        span = (z[0] * 60 + z[1] - a[0] * 60 - a[1]) * 60
        if span - TAIL_S < w["min_gap_seconds"] + JITTER_ROOM_S:
            out.append("send_window %s-%s is too short to hold one email (its last minute is never used)"
                       % (w["start"], w["end"]))
    if w["guidance"] is not None and not isinstance(w["guidance"], str):
        out.append("send_window.guidance must be text")
    return out


def window_cfg(outreach_cfg):
    """The project's sending window with its defaults filled, or None: no block, or enabled false. A block
    that is wrong raises ValueError -- a misread window must stop the send, not send at the wrong hour."""
    b = _block(outreach_cfg)
    if not isinstance(b, dict) and b is not None:
        raise ValueError("outreach.send_window must be an object")
    if b is None or b.get("enabled", True) is False:
        return None
    problems = config_problems({"send_window": b})
    if problems:
        raise ValueError("; ".join(problems))
    self_check()
    w = dict(DEFAULTS, **b)
    w["start"] = "%02d:%02d" % _hhmm(w["start"])
    w["end"] = "%02d:%02d" % _hhmm(w["end"])
    w["assumed_country"] = str(w["assumed_country"]).upper() if w["assumed_country"] else None
    w["country_zones"] = {str(k).upper(): v for k, v in (w["country_zones"] or {}).items()}
    w["spacing_s"] = w["min_gap_seconds"] + JITTER_ROOM_S
    w["tail_s"] = TAIL_S
    return w


def plan_key(wcfg):
    """The fingerprint of what decides a stored time (not the gap or lead time, which only shape the draw)."""
    w = wcfg or {}
    basis = {k: w.get(k, DEFAULTS.get(k)) for k in PLAN_KEYS}
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------- where a reader is
def _d(x):
    return x if isinstance(x, dict) else {}


def _text(v):
    if v in (None, "", [], {}) or isinstance(v, (dict, list)):
        return None
    s = " ".join(str(v).split())
    return s or None


def country_iso(text):
    """ISO2 for a country as any source writes it ("US", "United States", "England", "UAE"), or None."""
    s = _text(text)
    if not s:
        return None
    if len(s) == 2 and s.isalpha() and s.upper() in tp.ISO_NAME:
        return s.upper()
    return tp.COUNTRY_NAMES.get(tp.fold(s))


def _norm_li(u):
    s = str(u or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)
    s = re.sub(r"^(www\.|[a-z]{2}\.)(?=linkedin\.)", "", s)
    s = s.split("?")[0].split("#")[0].rstrip("/")
    return s or None


def _item(kind, country=None, region=None, city=None, gives_country=True, **extra):
    it = {"kind": kind, "ctext": _text(country), "iso": country_iso(country), "region": _text(region),
          "city": _text(city), "gives_country": gives_country}
    it.update(extra)
    return it


_NANP_WRITTEN = re.compile(r"(?:1[\s.\-]?)?\(?([2-9]\d\d)\)?[\s.\-]*\d{3}[\s.\-]+\d{4}"
                           r"(?:\s*(?:x|ext\.?|extension)\s*\d+)?", re.I)


def phone_place(s):
    """What a phone number says about where it rings: an evidence item, or None.
    +1 (or a North American number written the North American way, "(312) 555-0100"): the area code's
    country and state. Any other +code: the country only. A bare run of digits says nothing -- an Indian
    mobile and a Chicago landline can share their first three digits."""
    s = str(s or "").strip()
    s = re.sub(r"(?i)^(?:tel|phone|ph|call|t)\s*[:.]?\s*", "", s)
    s = re.sub(r"^[^\d+(]+", "", s)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if s.startswith("+") or (s.startswith("00") and len(digits) > 10):
        d = digits[2:] if s.startswith("00") else digits
        if d.startswith("1"):
            area = d[1:4]
            hit = tp.NANP.get(area) if len(d) >= 11 else None
            if not hit:
                return None
            return _item("phone", hit[0], hit[1], area=area, zone_hint=tp.NANP_ZONE.get(area))
        for n in (3, 2, 1):
            if d[:n] in tp.DIAL:
                return _item("phone", tp.DIAL[d[:n]], dial=d[:n])
        return None
    m = _NANP_WRITTEN.fullmatch(s)
    if m and tp.NANP.get(m.group(1)):
        area = m.group(1)
        hit = tp.NANP[area]
        return _item("phone", hit[0], hit[1], area=area, zone_hint=tp.NANP_ZONE.get(area))
    return None


def _phones(meta):
    out = []

    def add(v):
        if isinstance(v, list):
            for x in v:
                add(x)
        elif isinstance(v, dict):
            add(v.get("number") or v.get("phone") or v.get("value"))
        elif _text(v):
            out.append(str(v))
    for rec in _d(meta.get("discovery_raw")).values():
        if isinstance(rec, dict):
            for part in ("apollo", "osm", "fdic"):
                add(_d(rec.get(part)).get("phone"))
    for k in ("apollo", "aicp_detail", "p1_research"):
        add(_d(meta.get(k)).get("phone"))
    add(_d(meta.get("site_contact_routes")).get("phones"))
    return out


def _evidence(meta, wcfg, contact):
    raw = _d(meta.get("discovery_raw"))

    def parts(name, channel=None):
        """(source, record) for every discovery record holding `name`; channel True/False keeps only
        the clipping project's channel records (wikidata_channels) or only the others."""
        got = []
        for src, rec in raw.items():
            if isinstance(rec, dict) and isinstance(rec.get(name), dict):
                is_ch = src == "wikidata_channels"
                if channel is None or channel == is_ch:
                    got.append((src, rec[name]))
        return got

    ev = []
    people = _d(meta.get("apollo_people"))
    me = None
    if contact:
        m = re.fullmatch(r"\s*apollo:(\S+)\s*", str(contact.get("notes") or ""))
        if m and isinstance(people.get(m.group(1)), dict):
            me = m.group(1)
        want = _norm_li(contact.get("linkedin_url"))
        if me is None and want:
            me = next((pid for pid, p in people.items()
                       if isinstance(p, dict) and _norm_li(p.get("linkedin_url")) == want), None)
    # 1 the recipient
    if me is not None:
        p = people[me]
        ev.append(_item("recipient", p.get("country"), p.get("state"), p.get("city")))
    # 2 the company, from a source that knows
    fdic, osm, wd = parts("fdic"), parts("osm"), parts("wikidata", channel=False)
    for _, f in fdic:
        ev.append(_item("fdic", f.get("country_iso") or "US", f.get("state"), f.get("city")))
    for _, o in osm:
        ev.append(_item("osm", o.get("country_iso"), None, o.get("city")))
    for _, w in wd:
        ev.append(_item("wikidata", w.get("country_iso")))
    ap = _d(meta.get("apollo"))
    searched = [s.get("country_iso") for _, s in parts("apollo_search") if _text(s.get("country_iso"))]
    known = any(_text(x.get("country_iso")) for _, x in fdic + osm + wd) or bool(_text(ap.get("country")))
    hq_weak = bool(searched) and not known          # hq_country was lifted from the search it was found in
    hq_country = None if hq_weak else meta.get("hq_country")
    if _text(hq_country) or _text(meta.get("hq_state")) or _text(meta.get("hq_city")):
        ev.append(_item("hq", hq_country, meta.get("hq_state"), meta.get("hq_city")))
    if _text(ap.get("country")) or _text(ap.get("state")) or _text(ap.get("city")):
        ev.append(_item("apollo_company", ap.get("country"), ap.get("state"), ap.get("city")))
    # 3 other people at the company: their state and city only
    for pid, p in people.items():
        if pid != me and isinstance(p, dict) and (_text(p.get("state")) or _text(p.get("city"))):
            ev.append(_item("colleague", p.get("country"), p.get("state"), p.get("city"), gives_country=False))
    # 4 phones
    for ph in _phones(meta):
        it = phone_place(ph)
        if it:
            ev.append(it)
    # 5 the search it was found in
    if hq_weak and _text(meta.get("hq_country")):
        ev.append(_item("search", meta.get("hq_country")))
    for c in searched:
        ev.append(_item("search", c))
    # 6 a channel's or feed's country
    for c in [_d(meta.get("youtube_channel")).get("country")] + [y.get("country") for _, y in parts("youtube_channel")]:
        if _text(c):
            ev.append(_item("channel", c))
    for _, w in parts("wikidata", channel=True):
        if _text(w.get("country_iso")):
            ev.append(_item("channel_wd", w.get("country_iso")))
    yreg = _d(raw.get("youtube_api")).get("region")
    if _text(yreg):
        ev.append(_item("yt_search", yreg))
    for lang in [_d(meta.get("podcast_feed")).get("language")] + [f.get("language") for _, f in parts("podcast_feed")]:
        m = re.fullmatch(r"[a-z]{2,3}[-_]([a-z]{2})", str(lang or "").strip(), re.I)
        if m and country_iso(m.group(1)):
            ev.append(_item("podcast_lang", m.group(1), lang=str(lang).strip()))
    hint = _d(raw.get("apple_podcasts")).get("country_hint")
    if _text(hint):
        ev.append(_item("apple_chart", hint))
    # 7 the project's assumption
    if wcfg.get("assumed_country"):
        ev.append(_item("assumed", wcfg["assumed_country"]))
    return [e for e in ev if e["iso"] or e["region"] or e["city"]]


_ONE_CLOCK = {}
_PROBES = (dt.datetime(2026, 1, 15, 12, tzinfo=UTC), dt.datetime(2026, 7, 15, 12, tzinfo=UTC))


def one_clock(iso):
    """True when every zone of a country keeps the same time in winter and summer (Germany and Busingen,
    Malaysia and Kuching): its 10:00 needs no region, and its reason says no "main business zone"."""
    if iso not in _ONE_CLOCK:
        zs = tp.COUNTRY_ZONES.get(iso, [])
        _ONE_CLOCK[iso] = len(zs) <= 1 or len({tuple(p.astimezone(ZoneInfo(z)).utcoffset() for p in _PROBES)
                                               for z in zs}) == 1
    return _ONE_CLOCK[iso]


def _say(e, level, iso):
    """The reason, in the words the page shows, for the item that decided at `level` (city/region/country)."""
    k, code = e["kind"], e["iso"] or iso
    if k in ("recipient", "colleague", "apollo_company"):
        bits = []
        if level == "city":
            bits += [e["city"], e["region"]]
        elif level == "region" or (e["region"] and one_clock(iso)):
            bits.append(e["region"])
        bits.append(e["ctext"] or tp.country_name(code))
        txt = ", ".join(b for b in bits if b)
        return {"recipient": "recipient: %s", "colleague": "a colleague at the company: %s (Apollo)",
                "apollo_company": "company: %s (Apollo)"}[k] % txt
    if k in ("fdic", "osm", "wikidata", "hq"):
        tag = {"fdic": " (FDIC)", "osm": " (OpenStreetMap)", "wikidata": " (Wikidata)", "hq": ""}[k]
        if level == "city":
            return "company city %s%s%s" % (e["city"], ", " + e["region"] if e["region"] else "", tag)
        if level == "region":
            return "company state %s%s" % (e["region"], tag)
        return "country %s" % code if k == "hq" else "company country %s%s" % (code, tag)
    if k == "phone":
        return "phone area code %s" % e["area"] if e.get("area") else "phone dial code +%s" % e["dial"]
    if k == "podcast_lang":
        return "podcast language %s" % e["lang"]
    return {"search": "country %s (the search it was found in)",
            "channel": "channel country %s (YouTube)",
            "channel_wd": "channel country %s (Wikidata)",
            "yt_search": "country %s (the YouTube search it was found in)",
            "apple_chart": "country %s (the Apple Podcasts chart it was found in)",
            "assumed": "assumed country %s (project)"}.get(k, "country %s") % code


def recipient_zone(meta, wcfg, contact=None):
    """-> (IANA zone, why). meta is entities.metadata; contact {notes, linkedin_url} picks out the recipient's
    own Apollo record. With timezone_of "sender" every email keeps the sender's clock."""
    w = wcfg or DEFAULTS
    if w.get("timezone_of") == "sender":
        z = w.get("sender_timezone") or DEFAULTS["sender_timezone"]
        return z, "sender's clock (%s)" % place_name(z)
    fallback = w.get("fallback_timezone") or DEFAULTS["fallback_timezone"]
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    ev = _evidence(_d(meta), w, _d(contact))
    cit = next((e for e in ev if e["gives_country"] and e["iso"]), None)
    if not cit:
        return fallback, "fallback: no location held"
    iso = cit["iso"]
    mine = [e for e in ev if e["iso"] in (None, iso)]      # a place is read only inside its own country
    codes = tp.REGION_CODE.get(iso, {})
    reg = next((e for e in mine if e["region"] and tp.fold(e["region"]) in codes), None)
    rcode = codes[tp.fold(reg["region"])] if reg else None
    if rcode:
        # City: the FIRST item that gives a city in that state decides (2026-10-12 review). Every city inside a
        # known state says something -- its state's zone, or its own where CITY_OVERRIDES lists it -- so the
        # search stops there: a colleague in El Paso must not move a recipient in Houston to Mountain time.
        over = tp.CITY_OVERRIDES.get(iso, {})
        first = next((e for e in mine if e["city"] and (not e["region"] or codes.get(tp.fold(e["region"])) == rcode)),
                     None)
        z = over.get(tp.override_key(first["city"], rcode)) if first else None
        if z:
            return z, _say(first, "city", iso)
        return reg.get("zone_hint") or tp.REGIONS[iso][tp.fold(reg["region"])], _say(reg, "region", iso)
    hints = tp.CITY_HINTS.get(iso, {})
    for e in mine:
        if e["city"] and tp.fold(e["city"]) in hints:
            return hints[tp.fold(e["city"])], _say(e, "city", iso)
    zones = tp.COUNTRY_ZONES.get(iso, [])
    if (w.get("country_zones") or {}).get(iso):
        return w["country_zones"][iso], "%s, no region: the project's zone for %s" % (_say(cit, "country", iso), iso)
    if tp.MAIN_ZONE.get(iso) and len(zones) != 1:
        return tp.MAIN_ZONE[iso], _say(cit, "country", iso) + ("" if one_clock(iso) else
                                                                ", no region: main business zone")
    if tp.SINGLE_ZONE.get(iso):
        return tp.SINGLE_ZONE[iso], _say(cit, "country", iso)
    return fallback, "fallback: %s, a place with no zone of its own" % _say(cit, "country", iso)


# ------------------------------------------------------------- the windows
def _utc(x):
    if isinstance(x, str):
        x = dt.datetime.fromisoformat(x.strip().replace("Z", "+00:00"))
    if x.tzinfo is None:
        return x.replace(tzinfo=UTC)
    return x.astimezone(UTC)


def _wall_to_utc(day, hhmm, tz):
    """A wall time on a local day -> the UTC moment. In an autumn fold the first of the two (fold=0); in a
    spring gap (02:30 does not exist in New York on 8 Mar 2026) the next minute that does."""
    h, m = _hhmm(hhmm) if isinstance(hhmm, str) else hhmm
    base = dt.datetime(day.year, day.month, day.day, h, m)          # naive wall time: plain arithmetic
    for step in range(181):
        wall = base + dt.timedelta(minutes=step)
        u = wall.replace(tzinfo=tz, fold=0).astimezone(UTC)
        if u.astimezone(tz).replace(tzinfo=None) == wall:
            return u
    raise ValueError("no real minute within 3 hours of %s %s in %s" % (day, hhmm, tz))


def windows(zone, wcfg, after_utc, days=60):
    """Yield (window start UTC, window end UTC, local date) for each eligible day in `zone`, from the local
    date of after_utc, for `days` calendar days; a window already over by after_utc is passed over."""
    w = wcfg or DEFAULTS
    tz = ZoneInfo(zone)
    after = _utc(after_utc)
    d0 = after.astimezone(tz).date()
    for i in range(days):
        day = d0 + dt.timedelta(days=i)                               # a date, not a time: no zone involved
        if w.get("weekdays_only", True) and day.weekday() >= 5:
            continue
        ws, we = _wall_to_utc(day, w["start"], tz), _wall_to_utc(day, w["end"], tz)
        if we <= ws or we <= after:
            continue
        yield ws, we, day


def next_window(zone, wcfg, now_utc):
    """(start, end) of the first window an approval made now could still go out in -- at least two minutes
    of it left after the lead time -- or None. A draft's page names this window, never a minute."""
    w = wcfg or DEFAULTS
    now = _utc(now_utc)
    earliest = now + dt.timedelta(seconds=w.get("min_lead_seconds", DEFAULTS["min_lead_seconds"]))
    for ws, we, _day in windows(zone, w, now):
        if (we - max(ws, earliest)).total_seconds() >= LEAD_LEFT_S:
            return ws, we
    return None


def pick_moment(lo, hi, taken, spacing_s, rng=None):
    """One whole second in [lo, hi), uniform over those at least spacing_s from every moment in `taken`
    (the open interval (t - spacing, t + spacing) around each is removed). None when no second is free."""
    rng = rng or random.SystemRandom()
    a, b = math.ceil(_utc(lo).timestamp()), math.ceil(_utc(hi).timestamp())
    if b <= a:
        return None
    sp = float(spacing_s or 0)
    cuts = []
    if sp > 0:
        for t in taken or ():
            if t is None:
                continue
            x = _utc(t).timestamp()
            c0, c1 = max(math.floor(x - sp) + 1, a), min(math.ceil(x + sp), b)
            if c0 < c1:
                cuts.append((c0, c1))
    cuts.sort()
    free, cur = [], a
    for c0, c1 in cuts:
        if c0 > cur:
            free.append((cur, c0))
        cur = max(cur, c1)
    if cur < b:
        free.append((cur, b))
    total = sum(y - x for x, y in free)
    if total <= 0:
        return None
    k = rng.randrange(total)
    for x, y in free:
        if k < y - x:
            return dt.datetime.fromtimestamp(x + k, UTC)
        k -= y - x
    return None                              # not reached


def slots_per_window(span_s, wcfg):
    """How many sends one address can have in a window of span_s seconds at the spacing: 31 for 30 minutes.
    A ceiling: moments drawn at random fill a window before they pack it -- about 24 per address per
    30-minute window (22 to 27 over 200 seeded fills, 2026-10-12) -- and pick_moment then answers None, so
    the next window is tried."""
    w = wcfg or {}
    spacing = w.get("spacing_s") or (w.get("min_gap_seconds", DEFAULTS["min_gap_seconds"]) + JITTER_ROOM_S)
    tail = w.get("tail_s", TAIL_S)
    return max(0, int((float(span_s) - tail) // spacing))


# ------------------------------------------------------------- the words
def place_name(zone):
    """"New York", "UK", "India": a country's name when it keeps one zone, else the zone's city."""
    cc = tp.ZONE_COUNTRY.get(zone)
    if cc and len(tp.COUNTRY_ZONES.get(cc, ())) == 1:
        return tp.country_name(cc)
    return str(zone).rsplit("/", 1)[-1].replace("_", " ")


def day_label(d):
    """"Tue 14 Oct" (no leading zero; English whatever the machine's locale)."""
    return "%s %d %s" % (_DAYS[d.weekday()], d.day, _MONTHS[d.month - 1])


def _hm(t):
    return "%02d:%02d" % (t.hour, t.minute)


def local_day(at, zone):
    """The recipient's date of a moment (the Approved list groups by it)."""
    return _utc(at).astimezone(ZoneInfo(zone)).date()


def _sender(wcfg):
    return (wcfg or {}).get("sender_timezone") or DEFAULTS["sender_timezone"]


def send_label(at, zone, wcfg):
    """"Tue 14 Oct, 10:17 New York time (19:47 IST)"; "(Sat 01:47 IST)" when the sender's date differs;
    "Tue 14 Oct, 10:17 India time" when the zone is the sender's own."""
    at = _utc(at)
    loc = at.astimezone(ZoneInfo(zone))
    s = "%s, %s %s time" % (day_label(loc.date()), _hm(loc), place_name(zone))
    sz = _sender(wcfg)
    if zone != sz:
        sl = at.astimezone(ZoneInfo(sz))
        s += " (%s%s %s)" % ("" if sl.date() == loc.date() else _DAYS[sl.weekday()] + " ", _hm(sl), sl.tzname())
    return s


def send_short(at, zone):
    """"Tue 10:17 New York": the Outbox column."""
    loc = _utc(at).astimezone(ZoneInfo(zone))
    return "%s %s %s" % (_DAYS[loc.weekday()], _hm(loc), place_name(zone))


def window_label(ws, we, zone, wcfg):
    """"Tue 14 Oct, 10:00-10:30 New York time (19:30-20:00 IST)": a window, never a minute."""
    ws, we = _utc(ws), _utc(we)
    tz = ZoneInfo(zone)
    a, b = ws.astimezone(tz), we.astimezone(tz)
    s = "%s, %s-%s %s time" % (day_label(a.date()), _hm(a), _hm(b), place_name(zone))
    sz = _sender(wcfg)
    if zone != sz:
        sa, sb = ws.astimezone(ZoneInfo(sz)), we.astimezone(ZoneInfo(sz))
        s += " (%s%s-%s %s)" % ("" if sa.date() == a.date() else _DAYS[sa.weekday()] + " ", _hm(sa), _hm(sb),
                                sa.tzname())
    return s
