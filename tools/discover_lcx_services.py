#!/usr/bin/env python3
"""discover_lcx_services.py -- LCX Services: businesses to offer every LCX service, from public sources.

    python tools/discover_lcx_services.py --source wikidata [--limit 600] [--dry-run]
    python tools/discover_lcx_services.py --source osm [--cities 6] [--limit 600] [--endpoint URL] [--dry-run]

The owner, 2026-10-06: "it should generate the leads on its own for the people and businesses we
can pitch the services to", then "like we source leads for us production houses i want leads to
come like that". So, like the production-house harvests: free public sources, staged for the
promote chain (self-exclusion, dedupe, score, gates), then contacts from each company's own site
(enrich_contacts), then a draft a person approves. Apollo is not used here.

WHO. config `audiences`: each of the 18 services on docs/LCX Services.pdf has buyers, and an
audience is one kind of buyer (consumer brands, retailers, real estate, hotels and short stays,
publishers, financial services, studios and agencies, attractions, schools, local businesses), the
services it is pitched first, and where it is found:

  * wikidata  companies of a class (P31) or an industry (P452) with an official website (P856),
              still operating (no P576 dissolved date), not only in a country where cold business
              email needs consent (geography.disallowed_countries). CC0, one query per audience.
  * osm       independent local businesses -- a chain's branch is not a buyer, so nothing with a
              brand tag -- that publish a website or an email address on OpenStreetMap, around a
              list of cities taken a few a week in turn. ODbL: (c) OpenStreetMap contributors,
              kept on every lead it found.

A company already known here, or already a lead of another project (skip_known_elsewhere), is not
staged again: one company is not pitched by two projects from the same address.

WHAT IT STAGES. staging_candidates rows, source lcx_wikidata or lcx_osm, raw = {kind: audience
key, audience, services, why_fit, published_email, wikidata|osm, scoring_inputs}. The promote chain
makes them leads; tools/enrich_lcx_services.py turns a published address into a contact. Nothing
is fetched from a company's own site here, and never anything from LinkedIn.

SCORING V4 (the owner, 2026-10-07: "think and decide one"). tools/lcx_judge.py sets every scoring input
from the stored record on each chain run, so scoring_inputs carries only what a discovery record settles
by itself: audience_fit, has_reachable_presence, country_signal ('disallowed', 'unpayable' for a
sanctioned country, 'allowed') and oversized_signal (over 50,000 people or $10B of revenue). The
records keep what the judge reads: Apollo's parent company id, latest funding round, social pages and
when its buying signal was seen; OpenStreetMap's account tags (contact:youtube, contact:instagram,
contact:tiktok); and, for a judged project, Wikidata's accounts, revenue, pupils, parents, classes and
industries, fetched for every 50 companies staged (add_wikidata_more).
"""
import argparse
import datetime as dt
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
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = os.environ.get("SEGMENT_SLUG", "lcx-services")
SOURCES = {"wikidata": "lcx_wikidata", "osm": "lcx_osm", "apollo": "lcx_apollo", "fdic": "lcx_fdic"}
FDIC_API = "https://api.fdic.gov/banks/institutions"
SPARQL = "https://query.wikidata.org/sparql"
UA = "TVFLeadEngine/1.0 (+https://github.com/gupta1705/tvf-lead-engine; internal BD tool)"
OSM_ENDPOINTS = ["https://overpass-api.de/api/interpreter",
                 "https://overpass.kumi.systems/api/interpreter",
                 "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
QID_RE = re.compile(r"^Q\d+$")
ATTRIBUTION = "(c) OpenStreetMap contributors, ODbL"

if hasattr(sys.stdout, "reconfigure"):          # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(m):
    print(m, flush=True)


# ------------------------------------------------------------------ the parts that read data
def audiences(cfg, source):
    """The config's audiences that this source can find."""
    out = []
    apollo_keys = {s.get("audience") for s in ((cfg or {}).get("apollo_discovery") or {}).get("searches") or []}
    fdic_key = ((cfg or {}).get("fdic_discovery") or {}).get("audience")
    for a in (cfg or {}).get("audiences") or []:
        if source == "wikidata" and a.get("wikidata"):
            out.append(a)
        elif source == "osm" and a.get("osm"):
            out.append(a)
        elif source == "apollo" and a["key"] in apollo_keys:
            out.append(a)
        elif source == "fdic" and a["key"] == fdic_key:
            out.append(a)
    return out


def geography(cfg):
    g = (cfg or {}).get("geography") or {}
    return ({c.upper() for c in g.get("disallowed_countries") or []},
            {c.upper() for c in g.get("english_markets") or []})


def website(raw, cfg):
    """(url, domain) for a website a company owns, or (None, None) for a platform page."""
    import yt_api
    if not raw:
        return None, None
    raw = raw.strip()
    if not re.match(r"^[a-z]+://", raw, re.I):
        raw = "https://" + raw
    return yt_api.website_from(raw, (cfg or {}).get("hosting_providers") or ())


def published_email(*values):
    """The first well-formed address among OSM's email tags or Wikidata's mailto: values."""
    for v in values:
        for part in re.split(r"[;,\s]+", str(v or "")):
            part = part.strip().strip("<>")
            if part.lower().startswith("mailto:"):
                part = part[7:].split("?")[0]
            if EMAIL_RE.match(part):
                return part.lower()
    return None


def right_size(employees):
    """The harvest's order of preference by headcount (size_order): 1.0 at 10-5,000 people (big enough to
    pay, small enough to answer a cold email), 0.5 at 1-9 or 5,001-50,000, 0 above; None when nobody said.
    Not a scoring input any more: the judge sizes each lead by its audience's bands (buyer_size)."""
    if employees is None:
        return None
    if 10 <= employees <= 5000:
        return 1.0
    if employees > 50000:
        return 0.0
    return 0.5


def giant_lines(cfg):
    """not_major's size lines (config judge.not_major; the owner, 2026-10-07: over 50,000 people or $10B of
    revenue): (people over, revenue from)."""
    nm = ((cfg or {}).get("judge") or {}).get("not_major") or {}
    try:
        return float(nm.get("employees_over", 50000)), float(nm.get("revenue_from", 1e10))
    except (TypeError, ValueError):
        return 50000.0, 1e10


def oversized(employees, revenue, cfg):
    """True over not_major's lines, False under them, None when neither headcount nor revenue is known."""
    people, money = giant_lines(cfg)
    if employees is None and revenue is None:
        return None
    return bool((employees is not None and employees > people) or (revenue is not None and revenue >= money))


def inputs(aud, cfg, iso=None, employees=None, revenue=None, reachable=True):
    """The scoring and gate inputs a discovery record can settle by itself, and nothing else.

    Scoring v4 (the owner, 2026-10-07: "think and decide one"): every other input is judged from the lead's
    stored record on each chain run (tools/lcx_judge.py), so the harvest stages only these four. It no longer
    stages established, right_size or english_market (retired that day), nor a buying_signal score: they were
    copied into a lead by the promote merge whenever its own value was missing, so staging them would put a
    retired key back on every lead found again. The facts they came from stay on the discovery record."""
    bad, _ = geography(cfg)
    unpayable = {c.upper() for c in ((cfg or {}).get("geography") or {}).get("unpayable_countries") or []}
    si = {"audience_fit": float(aud.get("fit", 1.0)), "has_reachable_presence": bool(reachable)}
    big = oversized(employees, revenue, cfg)
    if big is not None:
        si["oversized_signal"] = big
    if iso:
        # disallowed: a consent-law country (country_allowed); unpayable: a sanctioned one LCX cannot invoice
        # (payable_country, geography.unpayable_countries)
        si["country_signal"] = "disallowed" if iso in bad else "unpayable" if iso in unpayable else "allowed"
    return si


def why_fit(aud, where, extra=None):
    services = ", ".join(aud.get("services") or [])
    return "%s%s.%s Pitch first: %s." % (aud.get("label", aud["key"]), where,
                                         (" " + extra) if extra else "", services)


def wikidata_row(rec, aud, cfg):
    """One Wikidata company -> a staging row, or None (and why) when it is not one to stage."""
    bad, _ = geography(cfg)
    name = (rec.get("label") or "").strip()
    if not name or QID_RE.match(name):
        return None, "no name in English"
    isos = [i for i in rec.get("isos") or [] if i]
    if isos and all(i in bad for i in isos):
        return None, "a consent-law country"
    iso = next((i for i in isos if i not in bad), None)
    url, domain = None, None
    for w in rec.get("webs") or []:
        url, domain = website(w, cfg)
        if domain:
            break
    if not domain:
        return None, "no website of its own"
    emp = rec.get("employees")
    email = published_email(*(rec.get("emails") or []))
    where = " on Wikidata" + (" (%s)" % iso if iso else "")
    extra = ("%s people." % format(emp, ",")) if emp else None
    raw = {"kind": aud["key"], "audience": aud.get("label"), "services": aud.get("services") or [],
           "why_fit": why_fit(aud, where, extra), "published_email": email,
           "wikidata": {"qid": rec["qid"], "matched": rec.get("matched"), "country_iso": iso, "website": url,
                        "employees": emp},
           "scoring_inputs": inputs(aud, cfg, iso=iso, employees=emp)}
    return {"name": name[:200], "domain": domain, "source_url": "https://www.wikidata.org/wiki/" + rec["qid"],
            "raw": raw}, None


# OpenStreetMap's tags for a place's own accounts: contact:* is the documented form, the bare key is common too
OSM_ACCOUNT_TAGS = ("contact:youtube", "contact:instagram", "contact:tiktok", "contact:vimeo",
                    "youtube", "instagram", "tiktok", "vimeo")


def osm_category(tags, aud):
    for k, v in aud.get("osm") or []:
        if tags.get(k) == v:
            return "%s=%s" % (k, v)
    return None


def osm_row(el, city, aud, cfg):
    """One OpenStreetMap element -> a staging row, or None (and why)."""
    t = el.get("tags") or {}
    name = (t.get("name:en") or t.get("name") or "").strip()
    if not name:
        return None, "no name"
    cat = osm_category(t, aud)
    if not cat:
        return None, "another kind of place"
    if t.get("brand") or t.get("brand:wikidata"):
        return None, "a chain's branch"
    url, domain = website(t.get("website") or t.get("contact:website") or t.get("url"), cfg)
    email = published_email(t.get("email"), t.get("contact:email"))
    if not domain and not email:
        return None, "no website or address of its own"
    phone = t.get("phone") or t.get("contact:phone")
    complete = bool(domain and (phone or t.get("opening_hours")))
    iso = (city.get("country") or "").upper() or None
    osm = {"type": el.get("type"), "id": el.get("id"), "category": cat, "city": city["name"],
           "country_iso": iso, "website": url, "email": email, "phone": phone, "complete": complete,
           "attribution": ATTRIBUTION}
    # the accounts the place lists for itself (content_activity counts a video or Instagram account a
    # directory lists, tools/lcx_judge.py), as tagged
    for key in OSM_ACCOUNT_TAGS:
        v = str(t.get(key) or "").strip()
        if v:
            osm[key] = v[:300]
    raw = {"kind": aud["key"], "audience": aud.get("label"), "services": aud.get("services") or [],
           "why_fit": why_fit(aud, " in %s, on OpenStreetMap (%s)" % (city["name"], cat)),
           "published_email": email, "osm": osm,
           "scoring_inputs": inputs(aud, cfg, iso=iso)}
    return {"name": name[:200], "domain": domain,
            "source_url": "https://www.openstreetmap.org/%s/%s" % (el.get("type"), el.get("id")), "raw": raw}, None


def city_slice(cities, per_run, today=None):
    """The cities for this run: a different few each ISO week, all of them in turn."""
    if not cities:
        return []
    per_run = max(1, min(per_run, len(cities)))
    week = (today or dt.date.today()).isocalendar()[1]
    start = (week * per_run) % len(cities)
    return [cities[(start + i) % len(cities)] for i in range(per_run)]


# ------------------------------------------------------------------ the network
def _get_json(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sparql(query):
    url = SPARQL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["results"]["bindings"]


def wikidata_ids(match):
    """{QID: (headcount or None, [country ISO codes])} for every operating company with a website
    matching one {property, values} entry."""
    if match["property"] == "P414":
        # listed on any stock exchange: ordinary corporates the class and industry queries miss
        which = "?item wdt:P414 [] ; wdt:P856 [] ."
    else:
        prop = {"P31": "wdt:P31", "P452": "wdt:P452"}[match["property"]]
        vals = " ".join("wd:%s" % q for q in match["values"] if QID_RE.match(q))
        which = "VALUES ?v { %s } ?item %s ?v ; wdt:P856 [] ." % (vals, prop)
    rows = sparql("SELECT ?item (MAX(?emp) AS ?e) (GROUP_CONCAT(DISTINCT ?iso; separator=\",\") AS ?isos) WHERE {"
                  " %s FILTER NOT EXISTS { ?item wdt:P576 [] }"
                  " OPTIONAL { ?item wdt:P1128 ?emp . } OPTIONAL { ?item wdt:P17 ?c . ?c wdt:P297 ?iso . } }"
                  " GROUP BY ?item" % which)
    out = {}
    for b in rows:
        try:
            emp = int(float((b.get("e") or {}).get("value")))
        except (TypeError, ValueError):
            emp = None
        isos = [i.upper() for i in ((b.get("isos") or {}).get("value") or "").split(",") if i]
        out[b["item"]["value"].rsplit("/", 1)[-1]] = (emp, isos)
    return out


def market(isos, cfg):
    """0 an English-speaking business market (the email and the deck are in English), 1 unknown,
    2 any other allowed country, 3 only consent-law countries (never staged)."""
    bad, english = geography(cfg)
    if not isos:
        return 1
    if all(i in bad for i in isos):
        return 3
    return 0 if any(i in english for i in isos) else 2


def size_order(qid, employees, mkt=1):
    """The order companies are taken in: 10-5,000 people first (they buy this and answer a cold
    email), then those Wikidata gives no headcount, then 5,001-50,000, then 1-9, then the giants;
    within each, English-speaking markets first, then unknown, then the rest; then the oldest
    Wikidata entry (usually the better-known company)."""
    band = {1.0: 0, None: 1}.get(right_size(employees), 2 if (employees or 0) > 9 else 3)
    if employees is not None and employees > 50000:
        band = 4
    return band, mkt, int(qid[1:])


def wikidata_details(qids):
    """{qid: {label, webs, isos, employees, emails}} for up to 200 QIDs."""
    vals = " ".join("wd:%s" % q for q in qids if QID_RE.match(q))
    rows = sparql("""SELECT ?item ?itemLabel ?web ?iso ?emp ?email WHERE {
      VALUES ?item { %s } ?item wdt:P856 ?web .
      OPTIONAL { ?item wdt:P17 ?c . ?c wdt:P297 ?iso . }
      OPTIONAL { ?item wdt:P1128 ?emp . }
      OPTIONAL { ?item wdt:P968 ?email . }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en,mul". } }""" % vals)
    out = {}
    for b in rows:
        q = b["item"]["value"].rsplit("/", 1)[-1]
        r = out.setdefault(q, {"qid": q, "label": None, "webs": [], "isos": [], "employees": None, "emails": []})
        r["label"] = r["label"] or (b.get("itemLabel") or {}).get("value")
        for key, field in (("web", "webs"), ("iso", "isos"), ("email", "emails")):
            v = (b.get(key) or {}).get("value")
            if v and v.upper() not in [x.upper() for x in r[field]]:
                r[field].append(v.upper() if key == "iso" else v)
        try:
            e = int(float((b.get("emp") or {}).get("value")))
            r["employees"] = max(r["employees"] or 0, e) or None
        except (TypeError, ValueError):
            pass
    return out


def overpass(query, endpoints, pause=2.0):
    """The elements of one Overpass query, trying each endpoint in turn. Raises RuntimeError when none
    answers; the run logs that city and audience as skipped and goes on."""
    last = None
    for ep in endpoints:
        try:
            return _get_json(ep, data=urllib.parse.urlencode({"data": query}).encode(), timeout=150)["elements"]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            last = e
            time.sleep(pause)
    raise RuntimeError("no OpenStreetMap endpoint answered: %s" % str(last)[:120])


def osm_query(city, aud, radius):
    keys = sorted({k for k, _ in aud["osm"]})
    vals = sorted({v for _, v in aud["osm"]})
    return ('[out:json][timeout:90];nwr[~"^(%s)$"~"^(%s)$"][~"^(contact:)?(website|email)$"~"."]'
            '(around:%d,%s,%s);out tags center;' % ("|".join(keys), "|".join(vals), radius, city["lat"], city["lon"]))


# ------------------------------------------------------------------ Apollo company search
# The owner, 2026-10-07: "i want to reachout to buisnesses to normal corporates not just cafes ... Enriching
# from apollo is acceptable". Apollo's company search is the one source of mid-size corporates that comes
# with each company's website, at 1 credit a page of 100 (0.01 a company). config apollo_discovery: the
# saved searches (an audience's industry tags and sizes, some with a buying signal: hiring for content or
# training, recently funded), each run in every country listed, one page a run, least-run slice first.
# A page that would come back empty is caught first by a free people search with the same filters.
COMPANY_ONLY = ("latest_funding_date_range", "latest_funding_amount_range", "total_funding_range",
                "organization_not_locations", "lookalike_organization_ids", "q_organization_name")


def apollo_slices(cfg):
    """Every (search, country) pair the config asks for, with its cursor key. Ordered on a diagonal through
    searches and countries ((search + country) index, then country), so a run mixes the countries
    instead of taking every US slice before the first UK one."""
    acfg = (cfg or {}).get("apollo_discovery") or {}
    out = []
    for si, s in enumerate(acfg.get("searches") or []):
        for ci, c in enumerate(acfg.get("countries") or []):
            out.append({"key": "%s|%s" % (s["key"], c["iso"]), "search": s, "country": c, "order": (si + ci, ci)})
    return out


def apollo_filters(sl, today=None):
    """The company-search filters for one slice: its search's own, its country, and its signal's dates
    (hiring in the last N days, funded in the last N days) counted back from today."""
    today = today or dt.date.today()
    s = sl["search"]
    f = json.loads(json.dumps(s.get("filters") or {}))
    f["organization_locations"] = [sl["country"]["name"]]
    if s.get("posted_within_days"):
        f["organization_job_posted_at_range"] = {
            "min": (today - dt.timedelta(days=int(s["posted_within_days"]))).isoformat(), "max": today.isoformat()}
    if s.get("funded_within_days"):
        f["latest_funding_date_range"] = {
            "min": (today - dt.timedelta(days=int(s["funded_within_days"]))).isoformat(), "max": today.isoformat()}
    return f


def band_text(bands):
    if not bands:
        return None
    lows = [int(str(b).split(",")[0]) for b in bands]
    highs = [int(str(b).split(",")[1]) for b in bands]
    return "%s-%s people" % (format(min(lows), ","), format(max(highs), ","))


APOLLO_KEEP = ("id", "name", "website_url", "primary_domain", "phone", "founded_year", "publicly_traded_symbol",
               "annual_revenue_printed", "owned_by_organization_id", "latest_funding_round_date", "twitter_url",
               "facebook_url")


def apollo_revenue(org):
    """Apollo's revenue in dollars: its number, or its printed form ("4.8M", "1.6B"), or None."""
    try:
        if org.get("annual_revenue") not in (None, ""):
            return float(org["annual_revenue"])
    except (TypeError, ValueError):
        pass
    m = re.fullmatch(r"\s*\$?([\d.]+)\s*([KMBT]?)\s*", str(org.get("annual_revenue_printed") or ""), re.I)
    try:
        return float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()] if m else None
    except ValueError:
        return None


def apollo_row(org, sl, aud, cfg, today=None):
    """One company from a company-search page -> a staging row, or None (and why). Apollo's answer has no
    industry, size or country, so they come from the slice that found it."""
    import apollo_store
    today = today or dt.date.today()
    name = (org.get("name") or "").strip()
    if not name:
        return None, "no name"
    # Apollo's primary_domain first, as tools/apollo_store.py does, so a company saved by hand from the
    # search page and the same one found here are one company to the skip-sets and the duplicate rule
    url, domain = website(org.get("primary_domain") or org.get("website_url"), cfg)
    if not domain:
        return None, "no website of its own"
    if apollo_store.excluded({"name": name, "primary_domain": domain}, (cfg or {}).get("self_exclusion") or {}):
        return None, "TVF or an affiliate"
    s, iso = sl["search"], sl["country"]["iso"].upper()
    bands = (s.get("filters") or {}).get("organization_num_employees_ranges") or []
    si = inputs(aud, cfg, iso=iso, revenue=apollo_revenue(org))
    how = s.get("signal") or band_text(bands) or "industry search"
    search = {"key": sl["key"], "signal": s.get("signal"), "country_iso": iso, "size_band": band_text(bands)}
    if s.get("signal"):
        # when the signal was seen: the judge's buying_trigger fades it to half after 60 days, gone after 120
        search["signal_seen_at"] = today.isoformat()
    raw = {"kind": aud["key"], "audience": aud.get("label"), "services": aud.get("services") or [],
           "why_fit": why_fit(aud, " in %s, on Apollo (%s)" % (sl["country"]["name"], how)),
           "published_email": None,
           # 2026-10-07 (scoring v4): also the parent company (too_big / not_major, once it is a company we
           # hold), the latest funding round and the company's own social pages (LinkedIn's left out, as
           # everywhere in this engine)
           "apollo": {k: org.get(k) for k in APOLLO_KEEP if org.get(k)},
           "apollo_search": search,
           "scoring_inputs": si}
    return {"name": name[:200], "domain": domain, "source_url": "https://app.apollo.io/#/organizations/%s" % org.get("id"),
            "raw": raw}, None


def precheck(filters):
    """Free: does a company page with these filters have anyone in it? A people search with the same
    company filters answers for nothing. None when it cannot say (a funding filter, which only company
    search takes)."""
    import apollo
    if any(k in filters for k in COMPANY_ONLY):
        return None
    return apollo.search_people(filters, 1, 1)["total"]


def load_cursors(db, seg_id):
    return db.run(lambda cur: (cur.execute(
        "select search_key, next_page, total_pages, runs, exhausted_at, last_run_at from apollo_cursors"
        " where segment_id = %s", (seg_id,)),
        {r[0]: {"next_page": r[1], "total_pages": r[2], "runs": r[3], "exhausted": r[4] is not None,
                "exhausted_at": r[4], "last_run_at": r[5]} for r in cur.fetchall()})[1])


def cursor_sql(cur, seg_id, key, next_page, total_pages, exhausted):
    cur.execute(
        "insert into apollo_cursors (segment_id, search_key, next_page, total_pages, runs, last_run_at, exhausted_at)"
        " values (%s, %s, %s, %s, 1, now(), case when %s then now() end)"
        " on conflict (segment_id, search_key) do update set next_page = excluded.next_page,"
        " total_pages = coalesce(excluded.total_pages, apollo_cursors.total_pages),"
        " runs = apollo_cursors.runs + 1, last_run_at = now(), exhausted_at = excluded.exhausted_at",
        (seg_id, key, max(1, min(500, int(next_page))), total_pages, bool(exhausted)))


def save_cursor(db, seg_id, key, next_page, total_pages, exhausted):
    """Where a slice got to: the next run asks for the next page."""
    db.run(lambda cur: cursor_sql(cur, seg_id, key, next_page, total_pages, exhausted))


def rolling_days(sl):
    """A signal search counts back from today (hiring in the last 30 days, funded in the last 90), so its
    results are a different set each time: the window, in days, or None for a fixed search."""
    s = sl["search"]
    d = s.get("posted_within_days") or s.get("funded_within_days")
    return int(d) if d else None


def slice_page(sl, cursors, now=None):
    """The page to buy next for this slice, or None while it waits.
    A fixed search goes on page by page; once used up (or found empty by the free check) it waits until
    its cursor is reset. A signal search, once used up (or found empty), rests for its window and then
    starts again at page 1, by then a new set of companies. Part-way through, it goes on with its next
    page however long ago it was bought: its results shift with the dates, so that page holds companies
    not seen yet, where page 1 would mostly be the big employers that are always hiring."""
    c = cursors.get(sl["key"]) or {}
    days = rolling_days(sl)
    now = now or dt.datetime.now(dt.timezone.utc)
    if days and c.get("exhausted_at") is not None and now - c["exhausted_at"] >= dt.timedelta(days=days):
        return 1
    if c.get("exhausted"):
        return None
    return c.get("next_page") or 1


def slice_order(slices, cursors, now=None):
    """Least-run first, so every audience and country gets its turn; then the diagonal (apollo_slices).
    A slice that is waiting (slice_page) is left out."""
    live = [s for s in slices if slice_page(s, cursors, now) is not None]
    return sorted(live, key=lambda s: ((cursors.get(s["key"]) or {}).get("runs", 0), s["order"]))


def run_apollo(db, seg_id, cfg, pages, skip_urls, skip_domains, emit=None, deadline=None, spend=None,
               dry_run=False, today=None):
    """Up to `pages` company pages (1 credit each), each the next page of the least-run slice. The ledger
    (spend(cur, credits, ref)) and the slice's cursor are written together, in one transaction, the moment
    Apollo answers and before anything is done with the companies: a page paid for is always on the ledger
    and never asked for again, whatever happens next. Every company is then handed to emit(row) as it
    arrives. -> (rows staged, {reason: count}, pages bought)."""
    import apollo
    auds = {a["key"]: a for a in (cfg or {}).get("audiences") or []}
    acfg = (cfg or {}).get("apollo_discovery") or {}
    per_page = int(acfg.get("per_page") or 100)
    cursors = load_cursors(db, seg_id)
    staged, why_not, bought = [], {}, 0
    # up to signal_pages_per_run pages from the signal searches (a buying signal, best leads, small sets),
    # the rest from the plain audience searches (the volume); signals again if the plain ones run out
    ordered = slice_order(apollo_slices(cfg), cursors)
    sig_cap = int(acfg.get("signal_pages_per_run") if acfg.get("signal_pages_per_run") is not None else pages)
    signal = [s for s in ordered if s["search"].get("signal")]
    base = [s for s in ordered if not s["search"].get("signal")]
    bought_signal = [0]

    def queue():
        for s in signal:
            if bought_signal[0] >= sig_cap:
                break
            yield s, True
        yield from ((s, False) for s in base)
        yield from ((s, True) for s in signal if s not in seen)
    seen = []
    for sl, is_signal in queue():
        seen.append(sl)
        if bought >= pages:
            break
        if deadline and time.monotonic() > deadline:
            log("  stopping: this run's time is up (--max-minutes); the rest wait for the next run")
            break
        aud = auds.get(sl["search"].get("audience"))
        if not aud:
            log("  %-34s skipped: no audience %r in the config" % (sl["key"], sl["search"].get("audience")))
            continue
        filters = apollo_filters(sl, today)
        page = slice_page(sl, cursors) or 1
        try:
            n = precheck(filters)
        except (apollo.ApolloError, ValueError) as e:
            log("  %-34s free check failed: %s" % (sl["key"], str(e)[:100]))
            if isinstance(e, apollo.ApolloError) and e.status in (401, 403):
                break
            continue
        if n == 0:
            log("  %-34s nobody on Apollo matches: set aside, no credit spent" % sl["key"])
            if not dry_run:
                save_cursor(db, seg_id, sl["key"], page, None, True)
            continue
        if dry_run:
            log("  %-34s page %d would be bought (%s people at matching companies, free check)"
                % (sl["key"], page, "?" if n is None else format(n, ",")))
            bought += 1
            bought_signal[0] += 1 if is_signal else 0
            continue
        try:
            out = apollo.search_companies(filters, page, per_page)
        except apollo.ApolloError as e:
            log("  %-34s company search failed: %s" % (sl["key"], str(e)[:100]))
            if e.status in (401, 403):
                break
            if e.status == 429:
                time.sleep(min(int(e.retry_after or 60), 120))
            continue
        except ValueError as e:
            log("  %-34s skipped: %s" % (sl["key"], str(e)[:100]))
            continue
        bought += 1
        bought_signal[0] += 1 if is_signal else 0
        total_pages = min(int(out.get("total_pages") or 0), 500) or None
        done = not out.get("companies") or (total_pages is not None and page >= total_pages) or page >= 500
        ref = "%s p%d" % (sl["key"], page)
        try:
            db.run(lambda cur: (spend(cur, 1, ref) if spend else None,
                                cursor_sql(cur, seg_id, sl["key"], page + 1, total_pages, done)))
        except Exception as e:                      # noqa: BLE001 -- the ledger must hold: stop buying
            log("  %-34s page %d bought, but the ledger and cursor could not be written (%s): stopping, so"
                " the week's cap is not overrun" % (sl["key"], page, str(e).splitlines()[0][:80]))
            break
        took = 0
        for org in out.get("companies") or []:
            row, why = apollo_row(org, sl, aud, cfg, today)
            if row and (row["source_url"] in skip_urls or row["domain"] in skip_domains):
                row, why = None, "already a lead here or in another project"
            if not row:
                why_not[why] = why_not.get(why, 0) + 1
                continue
            skip_domains.add(row["domain"])
            skip_urls.add(row["source_url"])
            staged.append(row)
            if emit:
                emit(row)
            took += 1
        log("  %-34s page %d of %s: %3d companies, %3d new%s" % (
            sl["key"], page, total_pages or "?", len(out.get("companies") or []), took, "  (last page)" if done else ""))
        time.sleep(0.5)
    return staged, why_not, bought


# ------------------------------------------------------------------ FDIC BankFind (US banks)
# Every insured US bank, from the FDIC's own public API: name, its website, city and state, and total
# assets, a real size measure. US government work, public domain. config fdic_discovery: which audience
# they are, and the asset band that is the right size (assets are in thousands of dollars, as the API
# gives them). A finite list: the first runs take a share each week, then only new charters appear.
def fdic_banks():
    """Every active bank: [{NAME, WEBADDR, CITY, STALP, ASSET, CERT}]."""
    q = urllib.parse.urlencode({"filters": "ACTIVE:1", "fields": "NAME,WEBADDR,CITY,STALP,ASSET,CERT",
                                "limit": 10000, "format": "json"})
    return [d["data"] for d in _get_json(FDIC_API + "?" + q).get("data") or [] if d.get("data")]


def fdic_row(b, aud, cfg):
    """One bank -> a staging row, or None (and why)."""
    fcfg = (cfg or {}).get("fdic_discovery") or {}
    name = " ".join(str(b.get("NAME") or "").split())
    if not name:
        return None, "no name"
    url, domain = website(b.get("WEBADDR"), cfg)
    if not domain:
        return None, "no website of its own"
    try:
        assets = int(b.get("ASSET") or 0)                    # thousands of dollars
    except (TypeError, ValueError):
        assets = 0
    lo, hi = int(fcfg.get("assets_min_thousands") or 0), int(fcfg.get("assets_max_thousands") or 10 ** 12)
    if not lo <= assets <= hi:
        return None, "outside the asset band"
    si = inputs(aud, cfg, iso="US")                         # its size is judged from assets_thousands
    where = " in %s, %s, on the FDIC's register (%s bn dollars in assets)" % (
        (b.get("CITY") or "").title(), b.get("STALP") or "", format(round(assets / 1e6, 1), ","))
    raw = {"kind": aud["key"], "audience": aud.get("label"), "services": aud.get("services") or [],
           "why_fit": why_fit(aud, where), "published_email": None,
           "fdic": {"cert": b.get("CERT"), "city": (b.get("CITY") or "").title(), "state": b.get("STALP"),
                    "assets_thousands": assets, "website": url, "country_iso": "US"},
           "scoring_inputs": si}
    return {"name": name[:200], "domain": domain,
            "source_url": "https://banks.data.fdic.gov/bankfind-suite/bankfind/details/%s" % b.get("CERT"),
            "raw": raw}, None


def run_fdic(cfg, limit, skip_urls, skip_domains, emit=None, banks=None):
    """Up to `limit` new banks in the asset band, largest first (they have the marketing teams)."""
    key = ((cfg or {}).get("fdic_discovery") or {}).get("audience")
    aud = next((a for a in (cfg or {}).get("audiences") or [] if a["key"] == key), None)
    if not aud:
        return [], {}
    if banks is None:
        try:
            banks = fdic_banks()
        except Exception as e:                      # noqa: BLE001 -- one source down never stops the refresh
            log("  FDIC BankFind did not answer (%s): no banks this run, the rest of the refresh goes on"
                % str(e).splitlines()[0][:100])
            return [], {"FDIC BankFind did not answer": 1}
    staged, why_not = [], {}
    for b in sorted(banks, key=lambda x: -(int(x.get("ASSET") or 0))):
        if len(staged) >= limit:
            break
        row, why = fdic_row(b, aud, cfg)
        if row and (row["source_url"] in skip_urls or row["domain"] in skip_domains):
            row, why = None, "already a lead here or in another project"
        if not row:
            why_not[why] = why_not.get(why, 0) + 1
            continue
        skip_domains.add(row["domain"])
        skip_urls.add(row["source_url"])
        staged.append(row)
        if emit:
            emit(row)
    log("  FDIC: %d active banks, %d staged" % (len(banks), len(staged)))
    return staged, why_not


# ------------------------------------------------------------------ the run
def known_here(db, seg_id, source):
    def q(cur):
        cur.execute("select source_url from staging_candidates where segment_id = %s and source = %s"
                    " union select source_url from entities where segment_id = %s and source = %s",
                    (seg_id, source, seg_id, source))
        urls = {r[0] for r in cur.fetchall() if r[0]}
        cur.execute("select normalize_domain(domain) from entities where segment_id = %s and domain is not null"
                    " union select normalize_domain(domain) from staging_candidates where segment_id = %s"
                    " and domain is not null", (seg_id, seg_id))
        return urls, {r[0] for r in cur.fetchall() if r[0]}
    return db.run(q)


def known_elsewhere(db, seg_id):
    """Domains that are already leads of another project."""
    return db.run(lambda cur: (cur.execute(
        "select distinct normalize_domain(domain) from entities where segment_id <> %s and domain is not null",
        (seg_id,)), {r[0] for r in cur.fetchall() if r[0]})[1])


def run_wikidata(cfg, limit, per_audience, skip_urls, skip_domains, emit=None, deadline=None):
    """-> (rows staged, {reason: count} not staged). Each row is handed to emit(row) as it is found, so a
    run that is stopped keeps what it found; the run ends early at `deadline` (time.monotonic())."""
    staged, why_not = [], {}
    auds = audiences(cfg, "wikidata")
    # every audience gets its share of the run, so the last in the list is not left with nothing
    per_audience = max(1, min(per_audience, limit // max(1, len(auds))))
    # a judged project (scoring v4): the judge's Wikidata fields too, for every 50 companies staged
    more = ((cfg or {}).get("judge") or {}).get("enabled") is True
    got_more = {}
    pending = []

    def flush():
        if more and pending:
            add_wikidata_more(pending, got_more)
        for r in pending:
            if emit:
                emit(r)
        del pending[:]
    for aud in auds:
        if deadline and time.monotonic() > deadline:
            log("  stopping: this run's time is up (--max-minutes); the rest wait for the next run")
            break
        qids = {}
        for match in aud["wikidata"]:
            try:
                got = wikidata_ids(match)
            except Exception as e:
                log("  %-28s %s query failed: %s" % (aud["key"], match["property"], str(e)[:100]))
                time.sleep(3)
                continue
            for q, (emp, isos) in got.items():
                was = qids.get(q, (None, []))
                qids[q] = (max(emp or 0, was[0] or 0) or None, sorted(set(isos) | set(was[1])))
            time.sleep(1.5)
        mkt = {q: market(isos, cfg) for q, (_, isos) in qids.items()}
        fresh = sorted((q for q in qids if "https://www.wikidata.org/wiki/" + q not in skip_urls
                        and mkt[q] < 3                                  # only in a consent-law country
                        and not (qids[q][0] or 0) > giant_lines(cfg)[0]),  # not_major would archive them
                       key=lambda q: size_order(q, qids[q][0], mkt[q]))
        took = 0
        for start in range(0, len(fresh), 200):
            if took >= per_audience or len(staged) >= limit:
                break
            try:
                details = wikidata_details(fresh[start:start + 200])
            except Exception as e:
                log("  %-28s details query failed: %s" % (aud["key"], str(e)[:100]))
                time.sleep(3)
                continue
            for q in fresh[start:start + 200]:
                rec = details.get(q)
                if not rec:
                    continue
                rec["matched"] = [m["property"] for m in aud["wikidata"]]
                row, why = wikidata_row(rec, aud, cfg)
                if row and row["domain"] in skip_domains:
                    row, why = None, "already a lead here or in another project"
                if not row:
                    why_not[why] = why_not.get(why, 0) + 1
                    continue
                skip_domains.add(row["domain"])
                skip_urls.add(row["source_url"])
                staged.append(row)
                pending.append(row)
                if not more or len(pending) >= 50:
                    flush()                          # saved as found (in fifties when the judge's fields come too)
                took += 1
                if took >= per_audience or len(staged) >= limit:
                    break
            flush()
            time.sleep(1.5)
        log("  %-28s %5d companies with a website, %5d new, %4d staged" % (aud["key"], len(qids), len(fresh), took))
        if len(staged) >= limit:
            break
    flush()
    if more and staged:
        log("  Wikidata fields for the judge, of %d staged: %s" % (len(staged), ", ".join(
            "%s %d" % (k, got_more.get(k, 0)) for k in ("socials", "revenue", "students", "parents", "classes"))))
    return staged, why_not


def wikidata_extra(qids):
    """The judge's Wikidata fields for up to 50 QIDs: tools/lcx_judge.wikidata_more, the very fetch its
    --backfill-wikidata runs (a test stubs this)."""
    import lcx_judge
    return lcx_judge.wikidata_more(qids)


def add_wikidata_more(rows, counts=None):
    """Scoring v4 (2026-10-07): what tools/lcx_judge.py reads from Wikidata beyond the harvest's own query --
    the company's YouTube, TikTok and Instagram accounts (P2397, P7085, P2003), revenue (P2139), pupils
    (P2196), parent organisation and owner (P749, P127) with the parent's headcount, and its classes and
    industries (P31, P452) -- onto each row's wikidata record, stamped details_at so --backfill-wikidata
    leaves it be. Free, CC0, four queries for up to 50 companies. A failed fetch leaves the rows as they are:
    they are staged anyway, and the back-fill fills them later."""
    qids = [r["raw"]["wikidata"]["qid"] for r in rows if (r["raw"].get("wikidata") or {}).get("qid")]
    if not qids:
        return
    try:
        found = wikidata_extra(qids)
    except Exception as e:                          # noqa: BLE001 -- one source down never stops the harvest
        log("  Wikidata fields for the judge not fetched (%s): left to --backfill-wikidata" % str(e)[:100])
        return
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    for r in rows:
        rec = r["raw"].get("wikidata") or {}
        fields = dict(found.get(rec.get("qid")) or {})
        for k in fields:
            if counts is not None and fields[k]:
                counts[k] = counts.get(k, 0) + 1
        rec.update(fields, details_at=stamp)


def osm_order(row):
    """Places that publish an address first (someone to write to today), then those with a website
    and a phone or opening hours, then the rest."""
    return (0 if row["raw"].get("published_email") else 1,
            0 if (row["raw"].get("osm") or {}).get("complete") else 1, row["name"].lower())


def run_osm(cfg, limit, cities_per_run, skip_urls, skip_domains, endpoints, per_place=None, emit=None, deadline=None):
    """-> (rows staged, {reason: count} not staged), each row handed to emit(row) as it is found; the run
    ends early at `deadline` (time.monotonic())."""
    ocfg = cfg.get("osm_discovery") or {}
    cities = city_slice(ocfg.get("cities") or [], cities_per_run)
    radius = int(ocfg.get("radius_m") or 12000)
    pause = float(ocfg.get("pause_seconds") or 3)
    auds = audiences(cfg, "osm")
    # one city's cafes must not fill the week: an even share for every city and audience
    per_place = per_place or max(1, limit // max(1, len(cities) * len(auds)))
    staged, why_not = [], {}
    log("  cities this run: %s (up to %d per city and audience)" % (", ".join(c["name"] for c in cities), per_place))
    for city in cities:
        for aud in auds:
            if len(staged) >= limit:
                break
            if deadline and time.monotonic() > deadline:
                log("  stopping: this run's time is up (--max-minutes); the rest wait for the next run")
                return staged, why_not
            try:
                els = overpass(osm_query(city, aud, radius), endpoints)
            except Exception as e:
                log("  %-14s %-22s skipped: %s" % (city["name"], aud["key"], str(e)[:100]))
                time.sleep(pause)
                continue
            rows = []
            for el in els:
                row, why = osm_row(el, city, aud, cfg)
                if row and (row["source_url"] in skip_urls or (row["domain"] and row["domain"] in skip_domains)):
                    row, why = None, "already a lead here or in another project"
                if not row:
                    why_not[why] = why_not.get(why, 0) + 1
                    continue
                rows.append(row)
            took = 0
            for row in sorted(rows, key=osm_order):
                if took >= per_place or len(staged) >= limit:
                    break
                if row["domain"] and row["domain"] in skip_domains:
                    continue                         # two places of one business, one website
                if row["domain"]:
                    skip_domains.add(row["domain"])
                skip_urls.add(row["source_url"])
                staged.append(row)
                if emit:
                    emit(row)
                took += 1
            log("  %-14s %-22s %4d places, %4d usable, %4d staged" % (city["name"], aud["key"], len(els), len(rows), took))
            time.sleep(pause)
    return staged, why_not


def apollo_run(db, seg_id, cfg, args, skip_urls, skip_domains, emit, deadline):
    """The Apollo source's gate and budget: only when the project has Apollo spending on (enrichment.enabled,
    provider apollo -- the owner's yes), never past the week's cap or the reserve (tools/apollo_budget.py),
    and every page written to the ledger as it is bought."""
    import apollo
    import apollo_budget
    import enrich_apollo
    block = cfg.get("enrichment") or {}
    gate = enrich_apollo.enrich_block(cfg)
    if gate["provider"] != "apollo" or not gate["enabled"]:
        log("Apollo spending is off for %s (enrichment.enabled) -- nothing bought" % SEGMENT)
        return [], {}
    if not apollo.key_is_set():
        log("APOLLO_API_KEY is not set -- skipped, nothing spent")
        return [], {}
    acfg = cfg.get("apollo_discovery") or {}
    want = int(args.limit or acfg.get("pages_per_run") or 10)
    try:
        left = (apollo.credits() or {}).get("lead_credits_left")
    except apollo.ApolloError as e:
        left = None
        log("  credits unknown (%s)" % e)
    pages, why = db.run(lambda cur: apollo_budget.allowance(cur, SEGMENT, block, left, want))
    log("  Apollo: up to %d company page(s) this run (set by %s)%s"
        % (pages, why, "  [DRY RUN: free checks only, nothing bought]" if args.dry_run else ""))
    if pages <= 0:
        return [], {}

    def spend(cur, credits, ref):                  # inside run_apollo's own transaction, with the cursor
        apollo_budget.record(cur, SEGMENT, "company_page", credits, ref)
    staged, why_not, bought = run_apollo(db, seg_id, cfg, pages, skip_urls, skip_domains, emit=emit,
                                         deadline=deadline, spend=spend, dry_run=args.dry_run)
    log("  Apollo: %d page(s) %s" % (bought, "would be bought" if args.dry_run else "bought, 1 credit each"))
    return staged, why_not


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), required=True)
    ap.add_argument("--limit", type=int, default=None, help="most new businesses this run (Apollo: company pages)")
    ap.add_argument("--per-audience", type=int, default=None, help="Wikidata: most new companies per audience")
    ap.add_argument("--cities", type=int, default=None, help="OpenStreetMap: cities this run")
    ap.add_argument("--endpoint", action="append", default=None,
                    help="OpenStreetMap: an Overpass endpoint to use instead of the config's (repeatable)")
    ap.add_argument("--max-minutes", type=float, default=None,
                    help="stop asking for more after this long (config discovery.<source>.max_minutes, else 40)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from dbconn import Db
    db = Db()
    seg = db.run(lambda cur: (cur.execute("select id, config from segments where slug=%s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not seg:
        sys.exit("no segments row for %s" % SEGMENT)
    seg_id, cfg = seg[0], seg[1] if isinstance(seg[1], dict) else json.loads(seg[1])
    if not audiences(cfg, args.source):
        log("segment %s has no audiences for %s (config audiences): nothing to do" % (SEGMENT, args.source))
        db.close(); return 0
    source = SOURCES[args.source]
    skip_urls, skip_domains = known_here(db, seg_id, source)
    if (cfg.get("discovery") or {}).get("skip_known_elsewhere", True):
        skip_domains |= known_elsewhere(db, seg_id)
    log("segment %s, source %s: %d already staged from it, %d domains already leads%s"
        % (SEGMENT, source, len(skip_urls), len(skip_domains), "  [DRY RUN]" if args.dry_run else ""))

    dcfg = (cfg.get("discovery") or {}).get(args.source) or {}
    limit = args.limit or int(dcfg.get("max_new_per_run") or 600)
    run_id = None
    if not args.dry_run:
        run_id = db.run(lambda cur: (cur.execute(
            "insert into source_runs (segment_id, source, status) values (%s,%s,'running') returning id",
            (seg_id, source)), cur.fetchone()[0])[1])
    staged, why_not, error = [], {}, None
    deadline = time.monotonic() + 60 * float(args.max_minutes or dcfg.get("max_minutes") or 40)

    def emit(r):
        """One business into staging the moment it is found: a run that is stopped keeps what it found
        (dbconn's second rule: never batch the writes to the end)."""
        if args.dry_run:
            return
        db.run(lambda cur, _r=r: cur.execute(
            "insert into staging_candidates (segment_id, name, domain, source, source_url, raw)"
            " select %s,%s,%s,%s,%s,%s where not exists (select 1 from staging_candidates"
            " where segment_id=%s and source_url=%s)",
            (seg_id, _r["name"], _r["domain"], source, _r["source_url"], json.dumps(_r["raw"]),
             seg_id, _r["source_url"])))
    try:
        if args.source == "wikidata":
            staged, why_not = run_wikidata(cfg, limit, args.per_audience or int(dcfg.get("per_audience") or 150),
                                           skip_urls, skip_domains, emit=emit, deadline=deadline)
        elif args.source == "fdic":
            staged, why_not = run_fdic(cfg, limit, skip_urls, skip_domains, emit=emit)
        elif args.source == "apollo":
            staged, why_not = apollo_run(db, seg_id, cfg, args, skip_urls, skip_domains, emit, deadline)
        else:
            staged, why_not = run_osm(cfg, limit, args.cities or int(dcfg.get("cities_per_run") or 6),
                                      skip_urls, skip_domains,
                                      args.endpoint or (cfg.get("osm_discovery") or {}).get("endpoints") or OSM_ENDPOINTS,
                                      emit=emit, deadline=deadline)
    except Exception as e:                                   # noqa: BLE001 -- recorded on the run, then raised
        error = str(e)[:500]
        raise
    finally:
        if run_id:
            db.run(lambda cur: cur.execute(
                "update source_runs set finished_at=now(), status=%s, candidates_found=%s, candidates_new=%s,"
                " notes=%s, error=%s where id=%s",
                ("failed" if error else "succeeded", len(staged) + sum(why_not.values()), len(staged),
                 json.dumps({"not_staged": why_not}), error, run_id)))
        db.close()
    by = {}
    for r in staged:
        by[r["raw"]["kind"]] = by.get(r["raw"]["kind"], 0) + 1
    log("\n%d staged%s: %s" % (len(staged), " (dry run: nothing written)" if args.dry_run else "",
                               ", ".join("%s %d" % kv for kv in sorted(by.items())) or "none"))
    log("with a published address: %d" % sum(1 for r in staged if r["raw"].get("published_email")))
    if why_not:
        log("not staged: %s" % ", ".join("%s %d" % kv for kv in sorted(why_not.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
