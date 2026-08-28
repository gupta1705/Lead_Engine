#!/usr/bin/env python3
"""resolve_domains.py -- find a company's website from its name.

THE GAP THIS CLOSES. News RSS produces the best-evidenced leads in the pool --
12 companies with `international_ip_experience` proven from a trade headline --
and not one of them has a domain, because a headline names a company but never
links to its site. AICP is the same: 247 member names, no URLs. Without a
domain, B1 site-scrape enrichment cannot start, so the best leads are the ones
we cannot contact.

TWO METHODS, TRIED IN ORDER OF HOW MUCH THEY CAN BE TRUSTED:

  1. WIKIDATA LABEL LOOKUP. If the company is in Wikidata, P856 gives its
     official website as a fact rather than a guess. CC0, free, and one
     batched SPARQL call covers hundreds of names at once. Highest confidence,
     and cheap enough to try on everything first.

  2. VERIFIED DOMAIN GUESSING. Build candidates from the name
     (lanternrowmedia.com, lanternrow.com, .tv, .studio ...), fetch each, and
     accept ONLY if the page actually names the company. The verification is
     the whole point: without it this is a random-domain generator, and a
     squatter or an unrelated business with a similar name would be recorded
     as a lead and eventually emailed.

WHAT IT WILL NOT DO
  * No search-engine scraping. Google and Bing both forbid it in their terms,
    and a lead pipeline that depends on breaking someone's ToS is not one you
    can run at scale or explain later.
  * No LinkedIn, ever.
  * robots.txt is honoured on every candidate fetch, same as B1.
  * A guess that cannot be verified is recorded as unresolved, not written.
    An unverified domain is worse than none: it looks like progress and sends
    mail to a stranger.

Usage:
    python tools/resolve_domains.py --limit 20 --dry-run
    python tools/resolve_domains.py --source google_news_rss
    python tools/resolve_domains.py --limit 50 --guess       # enable method 2
"""
import argparse
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = "us-production-houses"
UA = "TVF-Lead-Engine/0.1 (internal BD research; contact aitools@theviralfever.com)"
SPARQL = "https://query.wikidata.org/sparql"
TIMEOUT = 20
DELAY = 1.5

# Tried in this order. .com first because it is overwhelmingly the answer;
# .tv/.studio/.film because this industry actually uses them.
TLDS = [".com", ".tv", ".co", ".net", ".studio", ".film", ".media", ".productions"]

# Words dropped when building the shorter candidate. "Lantern Row Media" is
# often lanternrow.com.
SUFFIX_WORDS = {"media", "studio", "studios", "pictures", "films", "film",
                "productions", "production", "entertainment", "company", "co",
                "group", "network", "inc", "llc", "ltd", "limited", "corp",
                "incorporated", "the"}


def log(m):
    print(m, flush=True)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def http(url, accept="text/html"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(1_500_000).decode("utf-8", "ignore")


# ---------------------------------------------------------------- method 1
def wikidata_lookup(names):
    """One SPARQL call for many names. Returns {lowercased name: domain}."""
    if not names:
        return {}
    values = " ".join('"%s"@en' % n.replace('"', '\\"') for n in names)
    # ⚑ The class constraint is not optional. Without it, matching on label
    # alone resolved "Country House" to actsretirement.org -- a retirement
    # community -- because the name is generic and Wikidata has many entities
    # sharing it. A wrong domain here is worse than no domain: it flows into
    # enrichment, gets a contact attached, and eventually someone emails a
    # care home about a co-production.
    #
    # Q1762059 = film production company; P279* walks its subclasses, so
    # television and animation production companies are included too.
    query = """
    SELECT ?label ?website WHERE {
      VALUES ?label { %s }
      ?company rdfs:label ?label .
      ?company wdt:P31/wdt:P279* wd:Q1762059 .
      ?company wdt:P856 ?website .
    }
    """ % values
    url = SPARQL + "?format=json&query=" + urllib.parse.quote(query)
    try:
        data = json.loads(http(url, accept="application/sparql-results+json"))
    except Exception as e:
        log("    wikidata lookup failed (%s)" % type(e).__name__)
        return {}
    out = {}
    for b in data.get("results", {}).get("bindings", []):
        label = b["label"]["value"]
        site = b["website"]["value"]
        m = re.match(r"^[a-z][a-z0-9+.\-]*://(?:www\.)?([^/?#]+)", site, re.I)
        if m:
            out.setdefault(label.lower(), m.group(1).lower())
    return out


# ---------------------------------------------------------------- method 2
def candidates_for(name):
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    if not words:
        return []
    full = "".join(w.lower() for w in words)
    trimmed = "".join(w.lower() for w in words
                      if w.lower() not in SUFFIX_WORDS) or full
    stems = []
    for stem in (full, trimmed):
        if stem and stem not in stems and 3 <= len(stem) <= 40:
            stems.append(stem)
    return [s + t for s in stems for t in TLDS]


def resolves(domain):
    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def robots_ok(domain, url):
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.parse(http("https://%s/robots.txt" % domain, accept="text/plain").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.parse([])
        else:
            return False           # fail closed, same as B1
    except Exception:
        return False
    return rp.can_fetch(UA, url)


def verify(domain, company):
    """Fetch the homepage and require it to actually name the company.

    This is what separates a resolver from a domain generator. Without it,
    'toetagpictures.com' and 'toetag.com' are equally plausible and one of
    them belongs to somebody else entirely.
    """
    url = "https://%s/" % domain
    if not robots_ok(domain, url):
        return None
    try:
        html = http(url)
    except Exception:
        return None
    finally:
        time.sleep(DELAY)
    if not html:
        return None
    text = norm(re.sub(r"<[^>]+>", " ", html))
    target = norm(company)
    if not target:
        return None
    if target in text:
        return "full name on page"
    # a trimmed form is acceptable evidence when the full name is long
    words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", company) if w]
    core = "".join(w for w in words if w not in SUFFIX_WORDS)
    if len(core) >= 8 and core in text:
        return "core name on page"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--source", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--guess", action="store_true",
                    help="also try candidate domains (slower, needs verification)")
    args = ap.parse_args()

    from run_sql import load_db_url
    import psycopg2

    where = ["s.slug = %s", "e.domain is null",
             "e.status in ('discovered','enriched','scored','ready_for_review')"]
    params = [SEGMENT]
    if args.source:
        where.append("e.source = %s")
        params.append(args.source)
    params.append(args.limit)

    conn = psycopg2.connect(load_db_url(), connect_timeout=20)
    with conn.cursor() as cur:
        cur.execute("""
            select e.id, e.name, e.source, e.fit_score
            from entities e join segments s on s.id = e.segment_id
            where %s order by e.fit_score desc nulls last, e.name limit %%s
        """ % " and ".join(where), params)
        rows = cur.fetchall()

    if not rows:
        log("nothing to resolve -- every entity in scope already has a domain")
        conn.close(); return 0

    log("domain resolution -- %d name(s)%s\n"
        % (len(rows), "  [DRY RUN]" if args.dry_run else ""))

    # --- method 1, batched
    log("  Wikidata label lookup (1 request for all %d)..." % len(rows))
    wd = wikidata_lookup([r[1] for r in rows])
    log("    matched %d\n" % len(wd))

    found = {}
    for eid, name, source, score in rows:
        hit = wd.get(name.lower())
        if hit:
            found[eid] = (hit, "wikidata P856")
            log("  %-34s %-28s wikidata" % (name[:34], hit))

    # --- method 2, only if asked
    if args.guess:
        log("")
        for eid, name, source, score in rows:
            if eid in found:
                continue
            for cand in candidates_for(name)[:8]:
                if not resolves(cand):
                    continue
                why = verify(cand, name)
                if why:
                    found[eid] = (cand, "guessed + verified: " + why)
                    log("  %-34s %-28s %s" % (name[:34], cand, why))
                    break

    unresolved = [r for r in rows if r[0] not in found]
    if not args.dry_run and found:
        with conn.cursor() as cur:
            for eid, (dom, method) in found.items():
                cur.execute("""
                    update entities
                    set domain = %s,
                        metadata = jsonb_set(metadata, '{domain_resolution}',
                                             to_jsonb(%s::text))
                    where id = %s and domain is null
                """, (dom, method, eid))
        conn.commit()
    conn.close()

    log("\n  resolved   : %d of %d" % (len(found), len(rows)))
    log("  unresolved : %d" % len(unresolved))
    if unresolved[:6]:
        log("\n  still without a website:")
        for _, n, s, _ in unresolved[:6]:
            log("    %-36s (%s)" % (n[:36], s))
    if not args.guess and unresolved:
        log("\n  Wikidata only covers notable companies. Add --guess to try"
            "\n  candidate domains, each verified by reading the page.")
    if not args.dry_run and found:
        log("\n  now enrich them:  python tools/enrich_sitescrape.py --limit %d"
            % len(found))
    return 0


if __name__ == "__main__":
    sys.exit(main())
