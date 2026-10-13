#!/usr/bin/env python3
"""test_send_window.py -- the sending window's arithmetic and the time-zone resolver, as a regression table.

    python tools/test_send_window.py

Offline: no database, no clock (every "now" is fixed here). The owner, 2026-10-12: each email between
10:00 and 10:30 in its recipient's time zone, at its own minute -- "not like all mail going at 10:15".
What is checked:

  * the config: defaults, off means None, a wrong block is refused loudly, every shipped config's block
    (when it has one) is valid, the plan fingerprint follows what decides a time
  * where a reader is, for every shape of place the live leads hold: ISO codes, Apollo's country and
    state names ("United Kingdom" / "England", "New York"), US state codes (FDIC STALP, AICP) including
    "IN" (Indiana, never India), cities (El Paso and Pensacola keep another zone than their state),
    phones (an area code gives the state, a calling code the country only), channel and podcast
    countries, the project's assumption and zone, sender mode, nothing at all
  * the windows: India and Nepal's offsets, the DST weeks of New York, London and Sydney, Monday to
    Friday in the recipient's own zone, an approval inside, at the end of and after a window, the spring
    gap and the autumn fold
  * the draw: whole seconds, inside [10:00, 10:29), spread over the whole window, never closer than the
    spacing to another send from the address, None when the window is full
  * the words every page shows

Exit code 1 on any failure.
"""
import datetime as dt
import json
import random
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import send_window as sw  # noqa: E402
import tz_places as tp  # noqa: E402

UTC = dt.timezone.utc
RESULTS = []


def check(label, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %s%s" % ("ok  " if ok else "FAIL", label, "" if ok else "\n        got  %r\n        want %r" % (got, want)))


def at(y, mo, d, h, mi, s=0, zone="UTC"):
    """A wall time in a zone, as UTC (test helper: the zone's own rules, fold 0)."""
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=ZoneInfo(zone)).astimezone(UTC)


W = sw.window_cfg({"send_window": {}})                                   # the defaults
LCXS = sw.window_cfg({"send_window": {"fallback_timezone": "America/New_York"}})
PH = sw.window_cfg({"send_window": {"fallback_timezone": "America/Los_Angeles", "assumed_country": "US",
                                    "country_zones": {"US": "America/Los_Angeles"}}})
STARTUP = sw.window_cfg({"send_window": {"assumed_country": "IN"}})
SENDER = sw.window_cfg({"send_window": {"timezone_of": "sender"}})


def zone(meta, cfg=None, contact=None):
    return sw.recipient_zone(meta, cfg or LCXS, contact)


def config():
    print("\n-- the config")
    check("no block: the project sends as before (None)", sw.window_cfg({}), None)
    check("no outreach config at all: None", sw.window_cfg(None), None)
    check("enabled false: None (one line turns it off)", sw.window_cfg({"send_window": {"enabled": False}}), None)
    check("defaults: 10:00-10:30 in the recipient's zone, Monday to Friday, 45 s gap, 2 min lead",
          {k: W[k] for k in ("start", "end", "timezone_of", "sender_timezone", "fallback_timezone",
                             "weekdays_only", "min_gap_seconds", "min_lead_seconds")},
          {"start": "10:00", "end": "10:30", "timezone_of": "recipient", "sender_timezone": "Asia/Kolkata",
           "fallback_timezone": "Asia/Kolkata", "weekdays_only": True, "min_gap_seconds": 45,
           "min_lead_seconds": 120})
    check("derived: spacing 55 s (the 45 s gap plus room for the sender's jitter), last minute unused",
          (W["spacing_s"], W["tail_s"]), (55, 60))
    check("a whole segment config is read too", sw.window_cfg({"outreach": {"send_window": {"start": "9:05"}}})["start"],
          "09:05")
    check("country codes are upper-cased", (PH["assumed_country"], sorted(PH["country_zones"])), ("US", ["US"]))
    for label, block, needle in [
        ("start after end", {"start": "10:30", "end": "10:00"}, "before its end"),
        ("not a time", {"start": "25:00"}, "HH:MM"),
        ("timezone_of misspelt", {"timezone_of": "reader"}, "timezone_of"),
        ("a zone that does not exist", {"fallback_timezone": "Mars/Olympus"}, "not a time zone"),
        ("a country name where a code goes", {"assumed_country": "USA"}, "two-letter"),
        ("a project zone that does not exist", {"country_zones": {"US": "America/Nowhere"}}, "not a time zone"),
        ("a key it does not know (a typo)", {"timezone": "Asia/Kolkata"}, "does not know"),
        ("a window too short for one email", {"start": "10:00", "end": "10:01"}, "too short"),
    ]:
        try:
            sw.window_cfg({"send_window": block})
            got = "accepted"
        except ValueError as e:
            got = "refused" if needle in str(e) else "refused, but said: %s" % e
        check("refused loudly: " + label, got, "refused")
    for path in sorted((ROOT / "config").glob("segment.*.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        has = isinstance((cfg.get("outreach") or {}).get("send_window"), dict)
        check("%s: its send_window %s" % (path.name, "is valid" if has else "is absent (sends as before)"),
              sw.config_problems(cfg.get("outreach") or {}), [])
    k = sw.plan_key(W)
    check("plan_key: 12 characters, the same every time", (len(k), sw.plan_key(dict(W))), (12, k))
    check("plan_key changes with timezone_of", sw.plan_key(SENDER) != k, True)
    check("plan_key changes with the window's hours", sw.plan_key(dict(W, end="10:45")) != k, True)
    check("plan_key changes with a project's country zone", sw.plan_key(PH) != sw.plan_key(LCXS), True)
    check("plan_key ignores the gap (it shapes the draw, not the window)", sw.plan_key(dict(W, min_gap_seconds=60)), k)
    check("self_check passes (tzdata is installed and readable)", sw.self_check(), True)


LIVE_COUNTRIES = ("US GB IN AE SG CZ SE AU PH NO MY IE NG LT DK FI LK RS NZ SZ LV JP RO CN ZA ES ID IL PK BG HR "
                  "BH MD TW CH TR FR NL VN RU BR KR DE MX KE BD GR EG UA AI SH KZ PT AM NP KG CR HT IT CA").split()


def countries():
    print("\n-- every country the live leads name resolves to a real zone")
    bad = []
    for c in LIVE_COUNTRIES:
        z, why = zone({"hq_country": c})
        if not sw.zone_ok(z) or why.startswith("fallback"):
            bad.append((c, z, why))
    check("%d countries, each to a zone of its own" % len(LIVE_COUNTRIES), bad, [])
    for meta, want in [
        ({"hq_country": "US"}, ("America/New_York", "country US, no region: main business zone")),
        ({"hq_country": "GB"}, ("Europe/London", "country GB")),
        ({"hq_country": "IN"}, ("Asia/Kolkata", "country IN")),
        ({"hq_country": "AE"}, ("Asia/Dubai", "country AE")),
        ({"hq_country": "AU"}, ("Australia/Sydney", "country AU, no region: main business zone")),
        ({"hq_country": "NP"}, ("Asia/Kathmandu", "country NP")),
        ({"hq_country": "DE"}, ("Europe/Berlin", "country DE")),        # Busingen keeps Berlin's clock
        ({"hq_country": "MY"}, ("Asia/Kuala_Lumpur", "country MY")),    # so does Kuching
    ]:
        check("hq_country %s" % meta["hq_country"], zone(meta), want)
    print("\n-- country names as Apollo and others write them")
    for name, want in [("United States", "America/New_York"), ("United Kingdom", "Europe/London"),
                       ("England", "Europe/London"), ("Scotland", "Europe/London"), ("UK", "Europe/London"),
                       ("United Arab Emirates", "Asia/Dubai"), ("UAE", "Asia/Dubai"), ("USA", "America/New_York"),
                       ("India", "Asia/Kolkata"), ("Costa Rica", "America/Costa_Rica"), ("South Korea", "Asia/Seoul"),
                       ("Czechia", "Europe/Prague"), ("Czech Republic", "Europe/Prague"),
                       ("Viet Nam", "Asia/Ho_Chi_Minh"), ("Türkiye", "Europe/Istanbul"), ("Eswatini", "Africa/Mbabane"),
                       ("Côte d'Ivoire", "Africa/Abidjan"), ("Trinidad and Tobago", "America/Port_of_Spain"),
                       ("Saint Lucia", "America/St_Lucia"), ("Hong Kong", "Asia/Hong_Kong"), ("singapore", "Asia/Singapore")]:
        check("country %r" % name, zone({"apollo": {"country": name}})[0], want)
    check("a country nobody has heard of falls back", zone({"hq_country": "Atlantis"}),
          ("America/New_York", "fallback: no location held"))


def regions_and_cities():
    print("\n-- US states, by code and by name; a state is read only inside its own country")
    fd = lambda st, city=None: {"discovery_raw": {"lcx_fdic": {"fdic": {"state": st, "city": city, "country_iso": "US"}}}}
    for meta, want in [
        (fd("TX", "Lubbock"), ("America/Chicago", "company state TX (FDIC)")),
        (fd("IN", "Fishers"), ("America/Indiana/Indianapolis", "company state IN (FDIC)")),
        (fd("AZ", "Phoenix"), ("America/Phoenix", "company state AZ (FDIC)")),
        (fd("HI", "Honolulu"), ("Pacific/Honolulu", "company state HI (FDIC)")),
        (fd("WA", "Seattle"), ("America/Los_Angeles", "company state WA (FDIC)")),
        (fd("MI", "Detroit"), ("America/Detroit", "company state MI (FDIC)")),
        (fd("ID", "Boise"), ("America/Boise", "company state ID (FDIC)")),
        (fd("PR", "San Juan"), ("America/Puerto_Rico", "company state PR (FDIC)")),
        (fd("TX", "El Paso"), ("America/Denver", "company city El Paso, TX (FDIC)")),
        (fd("FL", "Pensacola"), ("America/Chicago", "company city Pensacola, FL (FDIC)")),
        (fd("FL", "Tallahassee"), ("America/New_York", "company state FL (FDIC)")),
        (fd("KY", "Glasgow"), ("America/Chicago", "company city Glasgow, KY (FDIC)")),
        (fd("TN", "Knoxville"), ("America/New_York", "company city Knoxville, TN (FDIC)")),
        (fd("TN", "Bristol"), ("America/New_York", "company city Bristol, TN (FDIC)")),
        (fd("CT", "Bristol"), ("America/New_York", "company state CT (FDIC)")),
        (fd("FL", "Milton"), ("America/Chicago", "company city Milton, FL (FDIC)")),
        (fd("MA", "Milton"), ("America/New_York", "company state MA (FDIC)")),
        (fd("ID", "Coeur d'Alene"), ("America/Los_Angeles", "company city Coeur d'Alene, ID (FDIC)")),
        ({"hq_country": "US", "hq_state": "Texas"}, ("America/Chicago", "company state Texas")),
        ({"hq_country": "US", "hq_state": "New York"}, ("America/New_York", "company state New York")),
        ({"hq_country": "US", "hq_state": "Washington"}, ("America/Los_Angeles", "company state Washington")),
        ({"hq_country": "US", "hq_state": "District of Columbia"}, ("America/New_York", "company state District of Columbia")),
        ({"hq_country": "US", "hq_state": "DC"}, ("America/New_York", "company state DC")),
        ({"hq_country": "IN", "hq_state": "IN"}, ("Asia/Kolkata", "country IN")),
        ({"hq_country": "IN", "hq_state": "Maharashtra", "hq_city": "Mumbai"}, ("Asia/Kolkata", "country IN")),
        ({"hq_country": "AU", "hq_state": "WA"}, ("Australia/Perth", "company state WA")),
        ({"hq_country": "AU", "hq_state": "Victoria"}, ("Australia/Melbourne", "company state Victoria")),
        ({"hq_country": "CA", "hq_state": "BC"}, ("America/Vancouver", "company state BC")),
        ({"hq_country": "CA", "hq_state": "Québec"}, ("America/Toronto", "company state Québec")),
        ({"hq_country": "Brazil", "hq_state": "São Paulo"}, ("America/Sao_Paulo", "company state São Paulo")),
        ({"hq_country": "BR", "hq_state": "Amazonas"}, ("America/Manaus", "company state Amazonas")),
        ({"hq_country": "MX", "hq_state": "Baja California"}, ("America/Tijuana", "company state Baja California")),
        ({"hq_country": "ID", "hq_state": "Bali"}, ("Asia/Makassar", "company state Bali")),
        ({"hq_country": "RU", "hq_state": "Novosibirsk Oblast"}, ("Asia/Novosibirsk", "company state Novosibirsk Oblast")),
        ({"hq_country": "PT", "hq_state": "Azores"}, ("Atlantic/Azores", "company state Azores")),
    ]:
        check("%s" % json.dumps(meta, ensure_ascii=False)[:90], zone(meta), want)
    print("\n-- cities, when no state is held")
    for meta, want in [
        ({"hq_country": "US", "hq_city": "Indianapolis"}, ("America/Indiana/Indianapolis", "company city Indianapolis")),
        ({"hq_country": "US", "hq_city": "El Paso"}, ("America/Denver", "company city El Paso")),
        ({"hq_country": "US", "hq_city": "Pensacola"}, ("America/Chicago", "company city Pensacola")),
        ({"hq_country": "US", "hq_city": "San Francisco"}, ("America/Los_Angeles", "company city San Francisco")),
        ({"hq_country": "US", "hq_city": "Brooklyn"}, ("America/New_York", "company city Brooklyn")),
        ({"hq_country": "CA", "hq_city": "Calgary"}, ("America/Edmonton", "company city Calgary")),
        ({"hq_country": "ES", "hq_city": "Las Palmas"}, ("Atlantic/Canary", "company city Las Palmas")),
        ({"hq_country": "MY", "hq_city": "Kuching"}, ("Asia/Kuching", "company city Kuching")),
        ({"discovery_raw": {"lcx_osm": {"osm": {"city": "Dubai", "country_iso": "AE"}}}},
         ("Asia/Dubai", "company country AE (OpenStreetMap)")),
        ({"hq_country": "US", "hq_city": "Springfield"}, ("America/New_York", "country US, no region: main business zone")),
        ({"hq_city": "Mumbai"}, ("America/New_York", "fallback: no location held")),   # a city alone names no country
    ]:
        check("%s" % json.dumps(meta)[:90], zone(meta), want)


def people_and_phones():
    print("\n-- the recipient's own Apollo record, matched by the contact's notes or LinkedIn URL")
    company_us = {"hq_country": "US", "discovery_raw": {"lcx_wikidata": {"wikidata": {"country_iso": "US"}}}}
    london = dict(company_us, apollo_people={
        "p1": {"country": "United Kingdom", "state": "England", "city": "London",
               "linkedin_url": "http://www.linkedin.com/in/zz-asha"},
        "p2": {"country": "United States", "state": "Texas", "city": "Austin"}})
    check("Apollo's 'United Kingdom' / 'England' form", zone(london, contact={"notes": "apollo:p1"}),
          ("Europe/London", "recipient: England, United Kingdom"))
    check("the recipient beats the company (the company is American)",
          zone(london, contact={"notes": "apollo:p1"})[0], "Europe/London")
    check("matched by LinkedIn URL whatever its scheme, www or trailing slash",
          zone(london, contact={"linkedin_url": "https://linkedin.com/in/zz-asha/"})[0], "Europe/London")
    check("Apollo's 'New York' state form",
          zone({"apollo_people": {"p9": {"country": "United States", "state": "New York", "city": "New York"}}},
               contact={"notes": "apollo:p9"}),
          ("America/New_York", "recipient: New York, United States"))
    check("a recipient in El Paso keeps Mountain time",
          zone({"apollo_people": {"p9": {"country": "United States", "state": "Texas", "city": "El Paso"}}},
               contact={"notes": "apollo:p9"}),
          ("America/Denver", "recipient: El Paso, Texas, United States"))
    # City: the first item that gives a city in the resolved state decides (review, 2026-10-12): a lower-ranked
    # city that CITY_OVERRIDES knows never beats the recipient's own city
    def me_and(city, state, other):
        return dict(other, apollo_people=dict(other.get("apollo_people") or {},
                                              me={"country": "United States", "state": state, "city": city}))
    mate = lambda city, state: {"apollo_people": {"mate": {"country": "United States", "state": state, "city": city}}}
    fdic_at = lambda city, st: {"discovery_raw": {"lcx_fdic": {"fdic": {"state": st, "city": city, "country_iso": "US"}}}}
    for label, meta, want in [
        ("a recipient in Houston with a colleague in El Paso stays on Central time",
         me_and("Houston", "Texas", mate("El Paso", "Texas")), ("America/Chicago", "recipient: Texas, United States")),
        ("  with the bank's head office in El Paso (FDIC): still Central",
         me_and("Houston", "Texas", fdic_at("El Paso", "TX")), ("America/Chicago", "recipient: Texas, United States")),
        ("  Miami with a colleague in Pensacola: Eastern",
         me_and("Miami", "Florida", mate("Pensacola", "Florida")), ("America/New_York", "recipient: Florida, United States")),
        ("  Nashville with a colleague in Knoxville: Central",
         me_and("Nashville", "Tennessee", mate("Knoxville", "Tennessee")),
         ("America/Chicago", "recipient: Tennessee, United States")),
    ]:
        check(label, zone(meta, contact={"notes": "apollo:me"}), want)
    check("  a recipient with a state but no city: the company's city in that state decides",
          zone(dict(fdic_at("El Paso", "TX"), apollo_people={"me": {"country": "United States", "state": "Texas"}}),
               contact={"notes": "apollo:me"}),
          ("America/Denver", "company city El Paso, TX (FDIC)"))
    check("someone else at the company gives the state, not the country (the recipient is unmatched)",
          zone(london, contact={"notes": "apollo:nobody"}),
          ("America/Chicago", "a colleague at the company: Texas, United States (Apollo)"))
    check("a colleague in another country is not read: the company's main zone",
          zone(dict(company_us, apollo_people={"p1": {"country": "United Kingdom", "state": "England"}})),
          ("America/New_York", "company country US (Wikidata), no region: main business zone"))
    check("a company saved from the Apollo search page (Universal)",
          zone({"apollo": {"country": "India", "state": "Maharashtra", "city": "Mumbai"}, "hq_country": "India",
                "hq_state": "Maharashtra", "hq_city": "Mumbai"})[0], "Asia/Kolkata")

    print("\n-- phones: an area code gives the state, a calling code the country only")
    harvest_gb = lambda phone: {"hq_country": "GB", "discovery_raw": {"lcx_apollo": {
        "apollo_search": {"country_iso": "GB"}, "apollo": {"phone": phone}}}}
    check("a phone beats the country of the search the lead was found in",
          zone(harvest_gb("+1 312-555-0100")), ("America/Chicago", "phone area code 312"))
    check("the search country, when nothing better is held",
          zone({"hq_country": "GB", "discovery_raw": {"lcx_apollo": {"apollo_search": {"country_iso": "GB"}}}}),
          ("Europe/London", "country GB (the search it was found in)"))
    check("hq_country backed by Wikidata is not the search's: it stands",
          zone({"hq_country": "GB", "discovery_raw": {"lcx_wikidata": {"wikidata": {"country_iso": "GB"}},
                                                      "lcx_apollo": {"apollo_search": {"country_iso": "US"},
                                                                     "apollo": {"phone": "+1 312 555 0100"}}}}),
          ("Europe/London", "company country GB (Wikidata)"))
    site = lambda *p: {"site_contact_routes": {"phones": list(p)}}
    for meta, want in [
        (site("(415) 555-0100"), ("America/Los_Angeles", "phone area code 415")),
        (site("Tel: 212.555.0100"), ("America/New_York", "phone area code 212")),
        (site("+1 915 555 0100"), ("America/Denver", "phone area code 915")),          # El Paso's own code
        (site("+1 (604) 555-0100"), ("America/Vancouver", "phone area code 604")),
        (site("+1 876 555 0100"), ("America/Jamaica", "phone area code 876")),
        (site("+44 20 7946 0000"), ("Europe/London", "phone dial code +44")),
        (site("0044 20 7946 0000"), ("Europe/London", "phone dial code +44")),
        (site("+61 2 9999 0000"), ("Australia/Sydney", "phone dial code +61, no region: main business zone")),
        (site("+971 4 000 0000"), ("Asia/Dubai", "phone dial code +971")),
        (site("+91 98200 12345"), ("Asia/Kolkata", "phone dial code +91")),
        (site("7012345678"), ("America/New_York", "fallback: no location held")),     # a bare run says nothing
        (site("+1 800 555 0100"), ("America/New_York", "fallback: no location held")),  # toll-free says nothing
        (site({"number": "+1 512 555 0100"}), ("America/Chicago", "phone area code 512")),
        ({"hq_country": "US", "aicp_detail": {"phone": "(312) 555-0100"}}, ("America/Chicago", "phone area code 312")),
    ]:
        check("phone %s" % json.dumps(meta)[:80], zone(meta), want)

    print("\n-- channels and feeds (the clipping project)")
    for meta, want in [
        ({"youtube_channel": {"country": "GB"}}, ("Europe/London", "channel country GB (YouTube)")),
        ({"discovery_raw": {"youtube_api": {"region": "US", "youtube_channel": {"country": "IN"}}}},
         ("Asia/Kolkata", "channel country IN (YouTube)")),
        ({"discovery_raw": {"youtube_api": {"region": "MX"}}},
         ("America/Mexico_City", "country MX (the YouTube search it was found in), no region: main business zone")),
        ({"discovery_raw": {"wikidata_channels": {"wikidata": {"country_iso": "JP"}}}},
         ("Asia/Tokyo", "channel country JP (Wikidata)")),
        ({"discovery_raw": {"apple_podcasts": {"country_hint": "US", "podcast_feed": {"language": "en-gb"}}}},
         ("Europe/London", "podcast language en-gb")),
        ({"discovery_raw": {"apple_podcasts": {"country_hint": "GB", "podcast_feed": {"language": "en"}}}},
         ("Europe/London", "country GB (the Apple Podcasts chart it was found in)")),
        ({"discovery_raw": {"apple_podcasts": {"podcast_feed": {"language": "es-419"}}}},
         ("America/New_York", "fallback: no location held")),                         # 419 is not a country
    ]:
        check("%s" % json.dumps(meta)[:90], zone(meta), want)

    print("\n-- the project's assumption and zone, sender mode, nothing at all")
    check("assumed_country (Startup Acquisitions: India)", zone({}, STARTUP),
          ("Asia/Kolkata", "assumed country IN (project)"))
    check("US Production Houses: no state -> the project's zone for the US (Los Angeles)", zone({}, PH),
          ("America/Los_Angeles", "assumed country US (project), no region: the project's zone for US"))
    check("  a state still wins over the project's zone (AICP hq_state NY)", zone({"hq_state": "NY"}, PH),
          ("America/New_York", "company state NY"))
    check("  so does a known city", zone({"hq_city": "New York"}, PH), ("America/New_York", "company city New York"))
    check("  and the state 'CA' is California inside the US", zone({"hq_state": "CA", "hq_city": "Santa Monica"}, PH),
          ("America/Los_Angeles", "company state CA"))
    check("sender mode: every email on the sender's clock", zone(london, SENDER, {"notes": "apollo:p1"}),
          ("Asia/Kolkata", "sender's clock (India)"))
    check("an empty record falls back (LCX Services: New York)", zone({}), ("America/New_York", "fallback: no location held"))
    check("an empty record falls back (defaults: India)", sw.recipient_zone({}, W), ("Asia/Kolkata", "fallback: no location held"))
    check("metadata as JSON text is read too", zone(json.dumps({"hq_country": "GB"}))[0], "Europe/London")


def first_window(z, after, cfg=W):
    return next(sw.windows(z, cfg, after))


def windows():
    print("\n-- 10:00 local, as UTC: offsets and the DST weeks")
    for label, z, day, want in [
        ("India (UTC+5:30)", "Asia/Kolkata", (2026, 10, 14), (4, 30)),
        ("Nepal (UTC+5:45)", "Asia/Kathmandu", (2026, 10, 14), (4, 15)),
        ("Dubai (UTC+4)", "Asia/Dubai", (2026, 10, 14), (6, 0)),
        ("New York, Fri 30 Oct (still EDT)", "America/New_York", (2026, 10, 30), (14, 0)),
        ("New York, Mon 2 Nov (EST from 1 Nov)", "America/New_York", (2026, 11, 2), (15, 0)),
        ("London, Fri 23 Oct (BST)", "Europe/London", (2026, 10, 23), (9, 0)),
        ("London, Mon 26 Oct (GMT from 25 Oct)", "Europe/London", (2026, 10, 26), (10, 0)),
        ("Sydney, Fri 2 Oct (AEST)", "Australia/Sydney", (2026, 10, 2), (0, 0)),
        ("Sydney, Mon 5 Oct (AEDT from 4 Oct): 23:00 UTC the day before", "Australia/Sydney", (2026, 10, 5), (23, 0)),
    ]:
        ws, we, d = first_window(z, at(*day, 0, 1, zone=z))
        check(label, (d, ws.hour, ws.minute, int((we - ws).total_seconds())), (dt.date(*day), want[0], want[1], 1800))
    ws, _, d = first_window("Australia/Sydney", at(2026, 10, 4, 22, 0))
    check("the weekday is the recipient's: Sunday 22:00 UTC is Monday in Sydney, its window opens at 23:00 UTC",
          (d, ws), (dt.date(2026, 10, 5), at(2026, 10, 4, 23, 0)))

    print("\n-- Monday to Friday in the recipient's zone")
    fri_eve = at(2026, 10, 16, 18, 0, zone="America/New_York")
    check("Friday evening goes to Monday", first_window("America/New_York", fri_eve)[2], dt.date(2026, 10, 19))
    check("without weekdays_only, to Saturday", first_window("America/New_York", fri_eve, dict(W, weekdays_only=False))[2],
          dt.date(2026, 10, 17))
    days = [d for _, _, d in sw.windows("America/New_York", W, at(2026, 10, 12, 0, 0))]
    check("60 days: only weekdays, one window each, in order",
          (all(d.weekday() < 5 for d in days), len(days) == len(set(days)), days == sorted(days), len(days)),
          (True, True, True, 43))

    print("\n-- an approval inside, at the end of and after a window (New York, Mon 12 Oct)")
    ny = "America/New_York"

    def placed(now):
        """lo/hi the way outreach_policy.place_send draws from them: [max(start, now + lead), end - 60 s)."""
        ws, we = sw.next_window(ny, W, now)
        lo = max(ws, now + dt.timedelta(seconds=W["min_lead_seconds"]))
        return ws, lo, we - dt.timedelta(seconds=W["tail_s"])
    ws, lo, hi = placed(at(2026, 10, 12, 10, 10, zone=ny))
    check("approved at 10:10: today's window, the draw from 10:12", (ws.astimezone(ZoneInfo(ny)).date(),
                                                                        lo >= at(2026, 10, 12, 10, 12, zone=ny)),
          (dt.date(2026, 10, 12), True))
    check("  and before 10:29", hi, at(2026, 10, 12, 10, 29, zone=ny))
    check("approved at 10:25: still today (3 minutes left after the lead time)",
          placed(at(2026, 10, 12, 10, 25, zone=ny))[0].astimezone(ZoneInfo(ny)).date(), dt.date(2026, 10, 12))
    check("approved at 10:27: tomorrow (1 minute left is not enough)",
          placed(at(2026, 10, 12, 10, 27, zone=ny))[0].astimezone(ZoneInfo(ny)).date(), dt.date(2026, 10, 13))
    check("approved at 10:30: tomorrow", placed(at(2026, 10, 12, 10, 30, zone=ny))[0].astimezone(ZoneInfo(ny)).date(),
          dt.date(2026, 10, 13))
    check("approved at 15:00: tomorrow, never late in the afternoon",
          placed(at(2026, 10, 12, 15, 0, zone=ny))[0], at(2026, 10, 13, 10, 0, zone=ny))
    check("approved at 07:00: today at 10:00", placed(at(2026, 10, 12, 7, 0, zone=ny))[1], at(2026, 10, 12, 10, 0, zone=ny))
    check("approved Friday 10:29: Monday", placed(at(2026, 10, 16, 10, 29, zone=ny))[0].astimezone(ZoneInfo(ny)).date(),
          dt.date(2026, 10, 19))

    print("\n-- the spring gap and the autumn fold (synthetic windows)")
    gap = dict(W, start="01:30", end="03:30", weekdays_only=False)
    ws, we, _ = first_window(ny, at(2026, 3, 8, 0, 0, zone=ny), gap)
    check("New York 8 Mar 2026, 01:30-03:30: 06:30-07:30 UTC (02:00-03:00 does not exist)",
          (ws, we), (dt.datetime(2026, 3, 8, 6, 30, tzinfo=UTC), dt.datetime(2026, 3, 8, 7, 30, tzinfo=UTC)))
    ws, _, _ = first_window(ny, at(2026, 3, 8, 0, 0, zone=ny), dict(gap, start="02:30"))
    check("  a start inside the gap moves to the next real minute, 03:00 EDT", ws, dt.datetime(2026, 3, 8, 7, 0, tzinfo=UTC))
    fold = dict(W, start="01:15", end="01:45", weekdays_only=False)
    ws, we, _ = first_window("Europe/London", at(2026, 10, 24, 12, 0), fold)
    check("London 25 Oct 2026, 01:15-01:45 happens twice: the first (BST), 00:15-00:45 UTC",
          (ws, we), (dt.datetime(2026, 10, 25, 0, 15, tzinfo=UTC), dt.datetime(2026, 10, 25, 0, 45, tzinfo=UTC)))
    check("next_window on a Saturday gives Monday's", sw.next_window(ny, W, at(2026, 10, 17, 9, 0, zone=ny))[0],
          at(2026, 10, 19, 10, 0, zone=ny))


def draws():
    print("\n-- the draw: whole seconds, uniform over the window, never too close")
    ny = "America/New_York"
    lo, hi = at(2026, 10, 12, 10, 0, zone=ny), at(2026, 10, 12, 10, 29, zone=ny)
    rng = random.Random(20261012)
    got = [sw.pick_moment(lo, hi, [], 55, rng) for _ in range(1000)]
    check("1000 seeded draws: all inside [10:00, 10:29)", all(lo <= m < hi for m in got), True)
    check("  each a whole second", all(m.microsecond == 0 for m in got), True)
    spread = (max(got) - min(got)).total_seconds() / 60
    check("  spread over more than 25 minutes (%.1f)" % spread, spread > 25, True)
    minutes = Counter(int((m - lo).total_seconds() // 60) for m in got)
    check("  every one of the 29 minutes is used", sorted(minutes) == list(range(29)), True)
    check("  no minute holds more than twice its share (%d..%d of ~34)" % (min(minutes.values()), max(minutes.values())),
          max(minutes.values()) <= 2 * 1000 / 29 and min(minutes.values()) >= 1000 / 29 / 2, True)
    check("  not all at one minute: %d distinct seconds" % len(set(got)), len(set(got)) > 500, True)
    m = sw.pick_moment(lo + dt.timedelta(microseconds=250000), hi, [], 55, random.Random(1))
    check("a start with a fraction of a second still gives whole seconds, never before it",
          (m.microsecond, m >= lo + dt.timedelta(seconds=1)), (0, True))
    taken = [lo + dt.timedelta(seconds=57 * k) for k in range(30)]              # 10:00:00 ... 10:27:33
    rest = [sw.pick_moment(lo, hi, taken, 55, random.Random(k)) for k in range(200)]
    check("30 taken: every draw at least 55 s from each of them",
          all(m is not None and min(abs((m - t).total_seconds()) for t in taken) >= 55 for m in rest), True)
    check("  which leaves only 10:28:28-10:28:59", all(at(2026, 10, 12, 10, 28, 28, zone=ny) <= m < hi for m in rest), True)
    check("a full window gives None", sw.pick_moment(lo, hi, taken + [at(2026, 10, 12, 10, 28, 40, zone=ny)], 55,
                                                     random.Random(2)), None)
    check("an empty span gives None", sw.pick_moment(hi, lo, [], 55, random.Random(3)), None)
    check("taken moments outside the window do not block it",
          sw.pick_moment(lo, lo + dt.timedelta(seconds=5), [lo - dt.timedelta(seconds=56)], 55, random.Random(4)) is not None,
          True)
    fills = []
    for seed in range(200):
        r, mine = random.Random(seed), []
        while True:
            x = sw.pick_moment(lo, hi, mine, 55, r)
            if x is None:
                break
            mine.append(x)
        mine.sort()
        fills.append((len(mine), min((b - a).total_seconds() for a, b in zip(mine, mine[1:]))))
    n = [f[0] for f in fills]
    check("filling a window draw by draw: never two closer than 55 s", min(f[1] for f in fills) >= 55, True)
    check("  it holds %d-%d (mean %.1f) before no second is free; slots_per_window's 31 is the ceiling"
          % (min(n), max(n), sum(n) / len(n)), (min(n) >= 18, max(n) <= sw.slots_per_window(1800, W)), (True, True))
    check("slots_per_window(30 minutes) = 31", sw.slots_per_window(1800, W), 31)
    check("a pool of two addresses shares the window at half the spacing",
          sw.pick_moment(lo, hi, taken, 55 / 2, random.Random(5)) is not None, True)
    check("the default draw is the system's (no seed to guess)", sw.pick_moment(lo, hi, [], 55) is not None, True)


def words():
    print("\n-- the words every page shows")
    t = dt.datetime(2026, 10, 14, 14, 17, 41, tzinfo=UTC)
    check("send_label, New York", sw.send_label(t, "America/New_York", W), "Wed 14 Oct, 10:17 New York time (19:47 IST)")
    check("send_label, Honolulu: India is already on Thursday",
          sw.send_label(dt.datetime(2026, 10, 14, 20, 17, tzinfo=UTC), "Pacific/Honolulu", W),
          "Wed 14 Oct, 10:17 Honolulu time (Thu 01:47 IST)")
    check("send_label, India: no bracket on the sender's own clock",
          sw.send_label(dt.datetime(2026, 10, 14, 4, 47, tzinfo=UTC), "Asia/Kolkata", W), "Wed 14 Oct, 10:17 India time")
    check("send_label, London", sw.send_label(dt.datetime(2026, 10, 14, 9, 13, tzinfo=UTC), "Europe/London", W),
          "Wed 14 Oct, 10:13 UK time (14:43 IST)")
    check("send_label, Sydney after its clocks went forward",
          sw.send_label(dt.datetime(2026, 10, 4, 23, 17, tzinfo=UTC), "Australia/Sydney", W),
          "Mon 5 Oct, 10:17 Sydney time (04:47 IST)")
    check("send_label from an ISO string", sw.send_label("2026-10-14T14:17:41+00:00", "America/New_York", W)[:22],
          "Wed 14 Oct, 10:17 New ")
    check("send_label for a sender in London", sw.send_label(t, "America/New_York", dict(W, sender_timezone="Europe/London")),
          "Wed 14 Oct, 10:17 New York time (15:17 BST)")
    check("send_short", sw.send_short(t, "America/New_York"), "Wed 10:17 New York")
    ws, we = sw.next_window("America/New_York", W, dt.datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    check("window_label, New York", sw.window_label(ws, we, "America/New_York", W),
          "Wed 14 Oct, 10:00-10:30 New York time (19:30-20:00 IST)")
    ws, we = sw.next_window("Pacific/Honolulu", W, dt.datetime(2026, 10, 14, 12, 0, tzinfo=UTC))
    check("window_label, Honolulu", sw.window_label(ws, we, "Pacific/Honolulu", W),
          "Wed 14 Oct, 10:00-10:30 Honolulu time (Thu 01:30-02:00 IST)")
    ws, we = sw.next_window("Asia/Kolkata", W, dt.datetime(2026, 10, 14, 0, 0, tzinfo=UTC))
    check("window_label, India", sw.window_label(ws, we, "Asia/Kolkata", W), "Wed 14 Oct, 10:00-10:30 India time")
    check("day_label has no leading zero", sw.day_label(dt.date(2026, 10, 5)), "Mon 5 Oct")
    check("local_day is the recipient's date", sw.local_day(dt.datetime(2026, 10, 4, 23, 17, tzinfo=UTC), "Australia/Sydney"),
          dt.date(2026, 10, 5))
    for z, want in [("America/New_York", "New York"), ("Europe/London", "UK"), ("Asia/Kolkata", "India"),
                    ("Asia/Dubai", "UAE"), ("America/Indiana/Indianapolis", "Indianapolis"),
                    ("America/Argentina/Buenos_Aires", "Buenos Aires"), ("Asia/Seoul", "South Korea"),
                    ("Asia/Kathmandu", "Nepal")]:
        check("place_name %s" % z, sw.place_name(z), want)


def data():
    print("\n-- the tables")
    zones = set(tp.MAIN_ZONE.values()) | set(tp.NANP_ZONE.values())
    zones |= {z for c in tp.REGIONS.values() for z in c.values()}
    zones |= {z for c in tp.CITY_HINTS.values() for z in c.values()}
    zones |= {z for c in tp.CITY_OVERRIDES.values() for z in c.values()}
    zones |= set(tp.SINGLE_ZONE.values())
    check("every zone named in tz_places is real (%d)" % len(zones), sorted(z for z in zones if not sw.zone_ok(z)), [])
    codes = {c for c, _ in tp.NANP.values()} | set(tp.DIAL.values()) | set(tp.ALIASES.values()) | set(tp.MAIN_ZONE)
    check("every country code named is a real one", sorted(c for c in codes if c not in tp.ISO_NAME), [])
    check("no toll-free code is read as a place", [c for c in ("800", "833", "844", "855", "866", "877", "888")
                                                  if c in tp.NANP], [])
    check("every region code is a real state of its country",
          sorted((cc, r) for cc, rs in tp.NANP.items() for cc2, r in [rs] if r and tp.fold(r) not in tp.REGION_CODE.get(cc2, {})), [])
    check("REGIONS covers the nine countries where the state decides", sorted(tp.REGIONS),
          sorted(["US", "CA", "AU", "BR", "MX", "RU", "ID", "ES", "PT"]))
    check("every multi-zone country in REGIONS has a main zone", sorted(c for c in tp.REGIONS if c not in tp.MAIN_ZONE), [])
    check("about 330+ area codes (%d)" % len(tp.NANP), len(tp.NANP) >= 330, True)
    check("fold: accents, case, punctuation, 'Saint'", [tp.fold(x) for x in ("São Paulo", "St. John's", "SAINT LUCIA",
                                                                             "Trinidad & Tobago", "Coeur d'Alene")],
          ["sao paulo", "st johns", "st lucia", "trinidad and tobago", "coeur dalene"])


def main():
    config()
    countries()
    regions_and_cities()
    people_and_phones()
    windows()
    draws()
    words()
    data()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
