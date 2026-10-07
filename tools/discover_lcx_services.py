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
SOURCES = {"wikidata": "lcx_wikidata", "osm": "lcx_osm"}
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
    for a in (cfg or {}).get("audiences") or []:
        if source == "wikidata" and a.get("wikidata"):
            out.append(a)
        elif source == "osm" and a.get("osm"):
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
    """1.0 at 10-5,000 people (big enough to pay, small enough to answer a cold email), 0.5 at 1-9
    or 5,001-50,000, 0 above; None when nobody said."""
    if employees is None:
        return None
    if 10 <= employees <= 5000:
        return 1.0
    if employees > 50000:
        return 0.0
    return 0.5


def inputs(aud, cfg, iso=None, employees=None, established=None, small=False, reachable=True):
    """The scoring and gate inputs a discovery record can settle (see the config's rubric)."""
    bad, english = geography(cfg)
    si = {"audience_fit": float(aud.get("fit", 1.0)), "has_reachable_presence": bool(reachable)}
    if established is not None:
        si["established"] = established
    size = 1.0 if small else right_size(employees)
    if size is not None:
        si["right_size"] = size
    if employees is not None:
        si["oversized_signal"] = employees > 100000
    if iso:
        si["country_signal"] = "disallowed" if iso in bad else "allowed"
        si["english_market"] = 1.0 if iso in english else 0.0
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
           "scoring_inputs": inputs(aud, cfg, iso=iso, employees=emp, established=1.0)}
    return {"name": name[:200], "domain": domain, "source_url": "https://www.wikidata.org/wiki/" + rec["qid"],
            "raw": raw}, None


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
    raw = {"kind": aud["key"], "audience": aud.get("label"), "services": aud.get("services") or [],
           "why_fit": why_fit(aud, " in %s, on OpenStreetMap (%s)" % (city["name"], cat)),
           "published_email": email,
           "osm": {"type": el.get("type"), "id": el.get("id"), "category": cat, "city": city["name"],
                   "country_iso": iso, "website": url, "email": email, "phone": phone,
                   "attribution": ATTRIBUTION},
           "scoring_inputs": inputs(aud, cfg, iso=iso, established=1.0 if complete else 0.5, small=True)}
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
    prop = {"P31": "wdt:P31", "P452": "wdt:P452"}[match["property"]]
    vals = " ".join("wd:%s" % q for q in match["values"] if QID_RE.match(q))
    rows = sparql("SELECT ?item (MAX(?emp) AS ?e) (GROUP_CONCAT(DISTINCT ?iso; separator=\",\") AS ?isos) WHERE {"
                  " VALUES ?v { %s } ?item %s ?v ; wdt:P856 [] . FILTER NOT EXISTS { ?item wdt:P576 [] }"
                  " OPTIONAL { ?item wdt:P1128 ?emp . } OPTIONAL { ?item wdt:P17 ?c . ?c wdt:P297 ?iso . } }"
                  " GROUP BY ?item" % (vals, prop))
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
                        and not (qids[q][0] or 0) > 100000),            # the gate would archive them anyway
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
                if emit:
                    emit(row)
                took += 1
                if took >= per_audience or len(staged) >= limit:
                    break
            time.sleep(1.5)
        log("  %-28s %5d companies with a website, %5d new, %4d staged" % (aud["key"], len(qids), len(fresh), took))
        if len(staged) >= limit:
            break
    return staged, why_not


def osm_order(row):
    """Places that publish an address first (someone to write to today), then those with a website
    and a phone or opening hours, then the rest."""
    return (0 if row["raw"].get("published_email") else 1,
            -(row["raw"]["scoring_inputs"].get("established") or 0), row["name"].lower())


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=sorted(SOURCES), required=True)
    ap.add_argument("--limit", type=int, default=None, help="most new businesses this run")
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
