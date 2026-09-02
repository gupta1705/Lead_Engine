#!/usr/bin/env python3
"""enrich_sitescrape.py -- B1: contact enrichment by reading a company's own site.

WHY THIS EXISTS. The ladder routed enrichment through Apollo (P16), with
site-scraping as backlog item B1 in case Checkpoint 2 showed Apollo missing
small shops. The Apollo subscription is not available for a while, so B1 is
promoted from fallback to primary. It is a smaller downgrade than it sounds:
the P1 hand-research found a published address on nearly every site in the
batch -- info@exit73studios.com, meerkats@meerkatmedia.org, and Neon Zoo
publishing both hello@ and the founder's direct address -- and for 2-20-person
shops a role inbox usually lands on a founder's desk anyway. That size band is
precisely Apollo's documented weak spot.

The rubric already models the difference honestly:
    reachable_decision_maker = 1.0  named person, target role, real mailbox
                               0.5  role address (info@, hello@) -- reachable,
                                    but not a named decision-maker
                               0.0  nothing reachable

COMPLIANCE, which is not negotiable here (BUILD_PLAN compliance lines):
  * robots.txt is honoured. If it disallows a path, that path is not fetched.
  * Only public first-party pages -- the company's own site, nothing else.
  * NEVER LinkedIn. Not the site, not a cached copy, not via a search engine.
  * One request at a time per host, with a delay. This is someone's small
    business website, not a load-test target.
  * Data stays internal. Nothing is republished.

WHAT IT SETS, AND WHAT IT REFUSES TO GUESS
  reachable_decision_maker  from what was actually found (see scale above)
  collaboration_openness    ONLY on an explicit invitation in the site's own
                            words -- the config gives full credit for exactly
                            that, and this is the one source that can read it
  has_reachable_presence    true, confirmed by a live site
It sets nothing else. Headcount, genre and revenue are not reliably legible
from a homepage, and a plausible guess in those fields is worse than a blank:
04b marks blanks as unverified, so a human can see what still needs checking.

Usage:
    python tools/enrich_sitescrape.py --limit 5 --dry-run
    python tools/enrich_sitescrape.py --limit 25
    python tools/enrich_sitescrape.py --source google_news_rss --limit 12
"""
import os
import argparse
from concurrent.futures import ThreadPoolExecutor
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# The segment this run works on. Segment 2 is meant to be "a config row and
# connectors, nothing else" -- so the slug comes from the environment, and
# every tool, the app, and the container agree on SEGMENT_SLUG.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
UA = ("TVF-Lead-Engine/0.1 (internal BD research; contact aitools@theviralfever.com)")
TIMEOUT = 15
DELAY_SECONDS = 2.0          # between requests to the same host
MAX_PAGES_PER_SITE = 4
SITE_STAMP = "v2"

# Pages worth trying, in priority order. Anything not linked from the homepage
# is not guessed at beyond these conventional paths.
CANDIDATE_PATHS = ["/", "/contact", "/contact-us", "/about", "/about-us",
                   "/team", "/our-team", "/people", "/connect"]

LINK_HINTS = re.compile(r"contact|about|team|people|connect|work with", re.I)

EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", re.I)

# Addresses that are never a lead: asset pipelines, trackers, CMS boilerplate.
EMAIL_NOISE = re.compile(
    r"(sentry|wixpress|example\.|yourdomain|domain\.com|email\.com|"
    r"@2x|\.png|\.jpg|\.jpeg|\.gif|\.svg|\.webp|\.css|\.js|"
    r"godaddy|squarespace|wordpress|shopify|cloudflare|sentry\.io)", re.I)

# A role inbox: reachable, but nobody in particular.
ROLE_LOCALPARTS = {
    "info", "hello", "contact", "hi", "mail", "email", "office", "admin",
    "enquiries", "inquiries", "general", "team", "studio", "press", "media",
    "support", "help", "hey", "reach", "connect", "work", "jobs", "careers",
    # added 2026-08-27 after the first live run read merch@ as a named person
    "merch", "shop", "store", "sales", "billing", "accounts", "legal",
    "privacy", "news", "newsletter", "subscribe", "booking", "bookings",
    "submissions", "casting", "no-reply", "noreply", "donotreply", "webmaster",
}

# The config gives FULL credit for "an explicit collaboration/partnership
# invitation on their own site". These are that invitation, in site language.
INVITATION_RE = re.compile(
    r"(work with us|partner with us|collaborate with us|let'?s collaborate|"
    r"open to collaboration|co-?production|partnership enquiries|"
    r"partnership inquiries|pitch us|get in touch about a project|"
    r"looking for partners|we collaborate with)", re.I)

# TVF's lanes, read from the company's own self-description. Full credit for
# genre_fit needs credit-verified evidence; a site SAYING "comedy" is real but
# self-reported, so it scores 0.5 and records which words matched.
GENRE_RE = re.compile(
    r"\b(comedy|comedic|sitcom|sketch comedy|satir(?:e|ical)|humor(?:ous)?|"
    r"slice[- ]of[- ]life|coming[- ]of[- ]age|young[- ]adult|"
    r"scripted (?:series|comedy|content)|web series|branded comedy)\b", re.I)

# "Our series premiered on Netflix" is distribution evidence. "A commercial
# for Netflix" is service work for an advertiser that happens to be a
# streamer -- the opposite of a route to market -- so ad-vocabulary within the
# window disqualifies the match.
PLATFORM_RE = re.compile(
    r"\b(series|show|film|feature|documentary|original)s?\b[^.<]{0,60}?"
    r"\b(netflix|hulu|hbo(?: max)?|max|amazon prime|prime video|apple tv\+?|"
    r"disney\+|peacock|paramount\+)\b", re.I)
SERVICE_WORK_RE = re.compile(
    r"\b(commercial|branded?|spot|campaign|advertis|promo)\w*\b", re.I)

TARGET_ROLE_RE = re.compile(
    r"(founder|co-?founder|head of development|development executive|"
    r"executive producer|head of acquisitions|head of distribution|"
    r"managing director|creative director|president|owner|partner)", re.I)


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """Follow 307/308 the way every browser does.

    Python 3.11 handles these; 3.10, which this runs on, does not -- it raises
    HTTPError instead. Because robots_for() fails CLOSED on an unexpected
    status, that turned an ordinary "we moved to www" redirect into "this site
    refuses robots inspection, skip it entirely". A live batch lost Bob
    Industries to exactly that. Failing closed is right; failing closed on a
    redirect is just a missing feature.
    """
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)

    http_error_307 = http_error_308


_OPENER = urllib.request.build_opener(_Redirect308)


def log(msg):
    print(msg, flush=True)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
    })
    with _OPENER.open(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return ""
        return r.read(2_000_000).decode("utf-8", "ignore")


def robots_for(domain):
    """Returns a parser that answers can_fetch. Fail CLOSED on a real error."""
    rp = urllib.robotparser.RobotFileParser()
    url = "https://%s/robots.txt" % domain
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with _OPENER.open(req, timeout=TIMEOUT) as r:
            rp.parse(r.read(200_000).decode("utf-8", "ignore").splitlines())
        return rp, None
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.parse([])          # no robots.txt means no restrictions
            return rp, None
        return None, "robots.txt HTTP %s" % e.code
    except Exception as e:
        return None, "robots.txt unreachable (%s)" % type(e).__name__


def has_mx(domain):
    """Cheap deliverability sanity check without sending anything.

    Not mailbox-level verification -- that needs SMTP probing, which is rude
    and unreliable. This only proves the domain can receive mail at all, which
    is enough to catch a dead or parked domain.
    """
    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def classify_email(addr):
    local = addr.split("@", 1)[0].lower()
    base = re.split(r"[.\-_+]", local)[0]
    if base in ROLE_LOCALPARTS or local in ROLE_LOCALPARTS:
        return "role"
    return "personal"


def looks_like_company(candidate, company):
    """Reject a 'name' that is really the company name echoed back.

    The first live run pulled name="Soft White Underbelly" off
    softwhiteunderbelly.org -- correct as text, useless as a person.
    """
    if not candidate or not company:
        return False
    c = re.sub(r"[^a-z]", "", candidate.lower())
    k = re.sub(r"[^a-z]", "", company.lower())
    return bool(c) and (c in k or k in c)


def find_name_for(html, addr, company=None):
    """Look for a human name adjacent to a personal address. Conservative."""
    i = html.lower().find(addr.lower())
    if i < 0:
        return None, None
    window = re.sub(r"<[^>]+>", " ", html[max(0, i - 400):i + 200])
    window = re.sub(r"\s+", " ", window)
    role = TARGET_ROLE_RE.search(window)
    # A name: two or three capitalised words not immediately part of a sentence
    m = re.search(r"\b([A-Z][a-z]{1,15}(?:\s+[A-Z][a-z'\-]{1,15}){1,2})\b", window)
    name = m.group(1) if m else None

    # Strip a role word that got glued onto the end. Live run produced
    # "Eric Stern Managing" from "Eric Stern, Managing Director".
    if name:
        name = re.sub(TARGET_ROLE_RE, "", name).strip(" ,-")
        name = re.sub(r"\s+", " ", name)
        if len(name.split()) < 2:
            name = None

    # The commonest false positive by far: the company's own name sitting next
    # to its own address. "Soft White Underbelly" and "American Genre Film"
    # both came back as people on live runs.
    if looks_like_company(name, company):
        name = None

    # THE DECIDING CHECK. A personal mailbox is almost always derived from the
    # person's name -- monica@, e.stern@, estern@, eric.stern@. If the name we
    # scraped off the page cannot produce this local-part, we found a page and
    # an address but we do NOT know whose it is.
    #
    # That distinction is worth 10 points: reachable_decision_maker = 1.0 means
    # "a named person in a target role", and "Art House" next to monica@ does
    # not meet that bar. Rejecting the name here demotes the row to the 0.5
    # role tier, which is the honest answer -- we can reach them, we just
    # cannot address them by name.
    if name and not name_matches_local(name, addr):
        name = None

    return name, (role.group(1).title() if role else None)


def name_matches_local(name, addr):
    """Could this mailbox plausibly belong to this person?"""
    local = re.sub(r"[^a-z]", "", addr.split("@", 1)[0].lower())
    if not local:
        return False
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in name.split() if p]
    parts = [p for p in parts if len(p) > 1]
    if not parts:
        return False
    first, last = parts[0], parts[-1]
    candidates = {first, last, first + last, last + first,
                  first[:1] + last, first + last[:1], last[:1] + first}
    if local in candidates:
        return True
    # a whole name part inside the mailbox
    if any(p in local for p in parts if len(p) >= 4):
        return True
    # diminutives: matt@ is Matthew, tim@ is Timothy. startswith is already
    # directional, so length 3 is safe -- except department-word locals.
    if local in {"art", "ads", "ad", "ed", "pr", "hr", "it", "biz", "dev", "ops"}:
        return False
    return len(local) >= 3 and any(p.startswith(local) for p in parts)


# Role words that appear beside a person's name on a team/about page. Used to
# COUNT people, which is the only headcount evidence a public site reliably
# gives. Deliberately broad: on a 6-person shop the titles are idiosyncratic
# ("Chief Frame-Fucker" is a real one from this pool).
TEAM_ROLE_RE = re.compile(
    r"\b(founder|co-?founder|partner|president|owner|ceo|cfo|coo|"
    r"executive producer|producer|director of|head of|managing|principal|"
    r"creative director|art director|editor|writer|designer|animator|"
    r"coordinator|supervisor|manager|strategist|developer|assistant)\b", re.I)

PERSON_RE = re.compile(r"\b([A-Z][a-z]{1,14})\s+([A-Z][a-z'\-]{1,18})\b")

# Pages that list REPRESENTED TALENT rather than staff. A commercial production
# company's /directors page names the directors on its roster -- freelancers it
# represents, not employees -- so counting them would inflate a 6-person shop
# into a 20-person one. Arts & Sciences lists 14 directors and is a boutique.
ROSTER_PATH_RE = re.compile(r"/(directors?|talent|roster|artists?|cast)", re.I)

# Words that look like a person but are not one. A whitelist of full phrases
# was tried first and failed immediately: "Founding Director" is not in it, so
# it counted as a fourth employee on a three-person team page. Rejecting on
# WORD membership instead is structural -- no title, however inventive, can
# survive it, because every title is built from these words.
NON_NAME_WORDS = set("""
founder founding co-founder partner partners president owner ceo cfo coo cto
executive producer producers production productions director directors creative
managing manager management head chief senior junior associate assistant
supervisor coordinator editor editorial writer writers designer design animator
animation strategist developer development artist artists talent roster
company studio studios film films media group inc llc ltd
new york los angeles san francisco united states privacy policy terms cookie
read more learn get in touch contact about our work team home news careers
case study post latest all rights reserved copyright
award awards nominated winning emmy oscar academy peabody clio
city center centre county state park avenue street airlines air
american america national international global worldwide
project projects series film2 episode season client clients brand brands
university college institute foundation museum theatre theater
""".split())


def looks_like_person(first, last):
    """Reject anything built out of job-title or navigation vocabulary."""
    return (first.lower() not in NON_NAME_WORDS
            and last.lower() not in NON_NAME_WORDS)


def count_people(html, path):
    """How many distinct humans does this page name?

    Returns (count, kind) where kind is 'staff' or 'roster'. Only names that sit
    within ~120 characters of a role word are counted, which is what separates a
    team page from a page that merely mentions two people in a paragraph.

    This is EVIDENCE, not truth: it is recorded alongside the count and the page
    it came from so a reviewer can check it in one click. A site with no team
    page yields nothing rather than a guess.
    """
    text = re.sub(r"<[^>]+>", " | ", html)
    text = re.sub(r"\s+", " ", text)
    people = set()
    leadership = False
    for m in PERSON_RE.finditer(text):
        full = m.group(0)
        if not looks_like_person(m.group(1), m.group(2)):
            continue
        window = text[max(0, m.start() - 120):m.end() + 120]
        if TEAM_ROLE_RE.search(window):
            people.add(full.lower())
            if LEADERSHIP_RE.search(window):
                leadership = True
    kind = "roster" if ROSTER_PATH_RE.search(path or "") else "staff"
    return len(people), kind, leadership


LEADERSHIP_RE = re.compile(
    r"\b(founder|founding|co-?founder|partner|president|owner|ceo|principal|"
    r"managing director|executive producer|head of)\b", re.I)


def scrape_site(domain, company=None):
    """Return findings for one domain, honouring robots.txt throughout."""
    out = {"pages": 0, "emails": [], "invitation": None, "blocked": None,
           "error": None, "team_count": 0, "team_page": None,
           "team_leadership": False, "genre_terms": set(), "platform_claim": None}

    rp, err = robots_for(domain)
    if rp is None:
        out["blocked"] = err
        return out

    base = "https://%s" % domain
    tried, queue = set(), []
    for p in CANDIDATE_PATHS:
        queue.append(urljoin(base, p))

    seen_emails = {}
    while queue and out["pages"] < MAX_PAGES_PER_SITE:
        url = queue.pop(0)
        if url in tried:
            continue
        tried.add(url)

        path = urlparse(url).path or "/"
        if not rp.can_fetch(UA, url):
            continue                      # robots.txt says no -- respect it

        try:
            html = fetch(url)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                out["error"] = "HTTP %s" % e.code
                break
            continue
        except Exception as e:
            out["error"] = type(e).__name__
            continue
        finally:
            time.sleep(DELAY_SECONDS)     # be a good guest, always

        if not html:
            continue
        out["pages"] += 1

        page_text = re.sub(r"<[^>]+>", " ", html)
        if out["invitation"] is None:
            m = INVITATION_RE.search(page_text)
            if m:
                out["invitation"] = m.group(1).lower()

        # content signals: what does this company SAY it makes, and where has
        # its original work actually run
        for g in GENRE_RE.findall(page_text):
            out["genre_terms"].add(g.lower())
        if out["platform_claim"] is None:
            for m in PLATFORM_RE.finditer(page_text):
                window = page_text[max(0, m.start() - 80):m.end() + 40]
                if not SERVICE_WORK_RE.search(window):
                    out["platform_claim"] = re.sub(
                        r"\s+", " ", m.group(0)).strip()[:160]
                    break

        # Headcount evidence. Keep the LARGEST staff count seen across the
        # site: a team page names more people than an about page, and the
        # fuller list is the better evidence. Roster pages are counted but
        # never treated as headcount (see ROSTER_PATH_RE).
        n, kind, lead = count_people(html, path)
        if kind == "staff" and n > out["team_count"]:
            out["team_count"] = n
            out["team_page"] = path
            out["team_leadership"] = lead

        for addr in set(EMAIL_RE.findall(html)):
            addr = addr.lower().rstrip(".")
            if EMAIL_NOISE.search(addr):
                continue
            # only first-party addresses; a gmail on their site is still theirs,
            # but an address at another company's domain is not a lead here
            adom = addr.split("@", 1)[1]
            first_party = adom == domain or adom.endswith("." + domain)
            if not first_party:
                # A free-mail address on a company page is only sometimes
                # theirs. Small shops genuinely use gmail -- Abominable
                # Pictures publishes abominableoffice@gmail.com -- but a live
                # run also pulled eliezerdc2020@gmail.com off Mediapro Studio,
                # which is somebody else entirely, probably a credit or a job
                # posting. Accept free-mail ONLY when the mailbox echoes the
                # company name; otherwise we would be emailing a stranger who
                # happened to appear on the page.
                if adom not in ("gmail.com", "outlook.com", "me.com",
                                "hotmail.com", "yahoo.com", "icloud.com"):
                    continue
                local_norm = re.sub(r"[^a-z]", "", addr.split("@", 1)[0].lower())
                words = [re.sub(r"[^a-z]", "", w.lower())
                         for w in re.split(r"[^A-Za-z0-9]+", company or "")]
                words = [w for w in words if len(w) >= 4]
                if not any(w in local_norm for w in words):
                    continue
            if addr not in seen_emails:
                name, role = find_name_for(html, addr, company)
                seen_emails[addr] = {"email": addr, "kind": classify_email(addr),
                                     "name": name, "role": role, "page": path}

        # follow same-host links that look like contact/about/team
        if out["pages"] < MAX_PAGES_PER_SITE:
            for href in re.findall(r'href=["\']([^"\']+)["\']', html)[:300]:
                if not LINK_HINTS.search(href):
                    continue
                nxt = urljoin(url, href)
                if urlparse(nxt).netloc.replace("www.", "") != domain:
                    continue
                if nxt not in tried and nxt not in queue:
                    queue.append(nxt)

    out["emails"] = sorted(seen_emails.values(),
                           key=lambda e: (e["kind"] != "personal", e["email"]))
    return out


def write_content_signals(cur, eid, found):
    """Genre and platform evidence from the site's own pages.

    Both are SELF-REPORTED, so both score 0.5 and both are gated in SQL on the
    current value being absent-or-zero: site self-description must never
    overwrite a full credit earned from news coverage or human research.
    """
    terms = sorted(found.get("genre_terms") or [])
    if terms:
        cur.execute(
            "select set_scoring_input(%s,'genre_fit','0.5'::jsonb)"
            " from entities where id = %s"
            "  and coalesce((metadata->'scoring_inputs'->>'genre_fit')::numeric,0) = 0",
            (eid, eid))
        cur.execute(
            "update entities set metadata = metadata ||"
            " jsonb_build_object('site_genre_evidence', %s::jsonb)"
            " where id = %s",
            ('["' + '","'.join(t.replace('"', '') for t in terms[:8]) + '"]', eid))
    claim = found.get("platform_claim")
    if claim:
        cur.execute(
            "select set_scoring_input(%s,'distribution_relationship','0.5'::jsonb)"
            " from entities where id = %s"
            "  and coalesce((metadata->'scoring_inputs'->>'distribution_relationship')::numeric,0) = 0",
            (eid, eid))
        cur.execute(
            "update entities set metadata = metadata ||"
            " jsonb_build_object('site_platform_evidence', to_jsonb(%s::text))"
            " where id = %s", (claim, eid))


def write_size(cur, eid, found):
    """Turn a counted team page into right_size -- or, more often, into nothing.

    WHY THIS IS DELIBERATELY TIMID. A live inspection of one team page showed
    the counter finding real staff (Adam Chaves, Alexis Gordon, Jamila Ephron)
    alongside credits and places ("Delta Air", "Kansas City", "John Oliver").
    Precision was roughly two thirds. That is not good enough to drive a
    20-point criterion on its own -- but the errors are not symmetric, and that
    asymmetry is what makes a safe rule possible:

        NOISE ONLY EVER INFLATES A COUNT. It never deflates one.

    So a count of 2-20 proves the true staff number is AT MOST 20, which is
    exactly what "~2-20 core people" asks for. The rule is sound in that band
    and nowhere else:

        2-20, leadership named  -> 1.0   true headcount <= 20, in band
        anything else           -> nothing written

    Above 20 the evidence is genuinely ambiguous -- a 54-name page is either a
    real mid-size company or a boutique whose page lists every collaborator it
    ever hired, and this counter cannot tell those apart. Writing 0 there would
    penalise good boutiques for having generous credits pages. Absent means
    unassessed, the engine renormalises over what it did assess, and a human
    can settle it in one click. That is the whole point of Invariant 1.

    The raw count is recorded either way, so the reviewer sees the evidence
    rather than a bare score.
    """
    n = found.get("team_count") or 0
    if n < 2:
        return
    # record what we saw, always -- even when it is not scoreable
    cur.execute("""update entities set metadata = metadata || jsonb_build_object(
                       'team_size_evidence', jsonb_build_object(
                           'people_named', %s, 'page', %s,
                           'leadership_named', %s, 'method', 'site_team_page',
                           'scored', %s))
                   where id = %s""",
                (n, found.get("team_page"), bool(found.get("team_leadership")),
                 bool(2 <= n <= 20 and found.get("team_leadership")), eid))
    if 2 <= n <= 20 and found.get("team_leadership"):
        cur.execute("select set_scoring_input(%s,'right_size','1'::jsonb)", (eid,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--source", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape and report, write nothing")
    ap.add_argument("--workers", type=int, default=8,
                    help="how many DIFFERENT sites to read at once (default 8). "
                         "Politeness is per-host, not global: every site still "
                         "sees one request every 2 seconds from us, because no "
                         "two workers ever share a domain. Serial reading of "
                         "552 domains measured at ~23 hours, which is a "
                         "fragility problem more than a patience one.")
    ap.add_argument("--qualify", action="store_true",
                    help="read sites for QUALIFICATION signals (team size, "
                         "collaboration invitation) across every domain in "
                         "scope, including companies that already have a "
                         "contact. Without this flag the tool only visits "
                         "companies with no contact yet, which structurally "
                         "excluded the 243 AICP rows -- the best-contactable "
                         "part of the pool -- from ever being scored.")
    args = ap.parse_args()

    from run_sql import load_db_url
    import psycopg2

    # Do not spend polite 2-second requests on companies the pipeline already
    # knows are wrong. Every one of these signals was captured at discovery and
    # was simply not being used: the first Wikidata sample wasted 4 of 10 slots
    # on 4Kids Entertainment (dissolved 2017), 4Kids TV (2008), ABC Signature
    # (2024) and Alchemy (2016) -- all already flagged `confirmed_dormant`.
    where = ["s.slug = %s", "e.domain is not null",
             # a major or an oversized shop: the gates reject it at P13 anyway
             "coalesce(e.metadata->'scoring_inputs'->>'major_or_oversized_signal','false') <> 'true'",
             # dissolved, per Wikidata P576. Nobody answers a dead company's inbox.
             "coalesce(e.metadata->'scoring_inputs'->>'activity_signal','') <> 'confirmed_dormant'",
             # a studio/network subsidiary. The review checklist requires
             # founder/partner ownership with no parent on record, so a
             # subsidiary fails review even if someone does reply.
             "e.metadata->'discovery_raw'->'wikidata'->>'parent_organisation' is null",
             "e.status in ('discovered','enriched','scored','ready_for_review')"]
    if not args.qualify:
        # contact-finding mode: skip anyone we can already reach
        where.append("not exists (select 1 from contacts c where c.entity_id = e.id)")
    else:
        # qualification mode: skip only what has already been read
        # STAMP is versioned: bumping it makes every already-read site
        # eligible for exactly one more pass. v2 = the pass that added genre
        # and platform detection; sites read before it never looked for either.
        where.append("coalesce(e.metadata->>'site_read','') <> %s")
    params = [SEGMENT]
    if args.qualify:
        params.append(SITE_STAMP)
    if args.source:
        where.append("e.source = %s")
        params.append(args.source)
    params.append(args.limit)

    from dbconn import Db
    db = Db()
    conn = db._live()
    with conn.cursor() as cur:
        cur.execute("""
            select e.id, e.name, e.domain, e.fit_score
            from entities e join segments s on s.id = e.segment_id
            where %s
            order by e.fit_score desc nulls last, e.name
            limit %%s
        """ % " and ".join(where), params)
        targets = cur.fetchall()

    if not targets:
        log("nothing to do -- every domain in scope is already "
            + ("read" if args.qualify else "contactable"))
        db.close(); return 0

    log("B1 site-scrape enrichment -- %d target(s)%s\n"
        % (len(targets), "  [DRY RUN]" if args.dry_run else ""))

    stats = {"personal": 0, "role": 0, "none": 0, "blocked": 0, "no_mx": 0}

    # NETWORK IN PARALLEL, DATABASE IN SERIAL.
    # Each worker owns one domain for the whole of its visit, so the 2-second
    # spacing inside scrape_site is still 2 seconds *per site* -- the thing
    # politeness actually means. Nothing shares a host. Writes all happen on
    # this thread against the single connection, so there is no concurrent-DB
    # question to get wrong.
    def read_one(t):
        eid, name, domain, score = t
        try:
            if not has_mx(domain):
                return (t, None, "no_mx")
            return (t, scrape_site(domain, name), None)
        except Exception as exc:                       # never let one site kill the run
            return (t, None, type(exc).__name__)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for t, found, err in pool.map(read_one, targets):
            eid, name, domain, score = t
            done += 1
            log("  [%d/%d] %-32s %s" % (done, len(targets), name[:32], domain))

            if err == "no_mx":
                log("      domain does not resolve -- skipping, likely dead")
                stats["no_mx"] += 1
                if not args.dry_run:
                    db.run(lambda cur, _e=eid: cur.execute(
                        "update entities set metadata ="
                        " jsonb_set(metadata,'{enrichment_result}','\"domain_dead\"')"
                        " where id = %s", (_e,)))
                continue

            if found is None:
                log("      read failed (%s) -- left for a later pass" % err)
                stats["blocked"] += 1
                continue

            if not args.dry_run:
                db.run(lambda cur, _e=eid: cur.execute(
                    "update entities set metadata ="
                    " jsonb_set(metadata,'{site_read}', to_jsonb(%s::text))"
                    " where id = %s", (SITE_STAMP, _e)))

            if found["blocked"]:
                log("      %s -- not fetched" % found["blocked"])
                stats["blocked"] += 1
                continue

            emails = found["emails"]
            if not emails:
                log("      %d page(s) read, no address published%s" % (
                    found["pages"],
                    ("  | team of %d" % found["team_count"]) if found["team_count"] >= 2 else ""))
                stats["none"] += 1
                if not args.dry_run:
                    def _write_no_email(cur, _e=eid, _f=found):
                        # Qualification evidence stands on its own: a site with
                        # no published address can still show a team page and a
                        # partnership invitation, and both are scoreable.
                        write_size(cur, _e, _f)
                        write_content_signals(cur, _e, _f)
                        if _f["invitation"]:
                            cur.execute(
                                "select set_scoring_input(%s,'collaboration_openness','1'::jsonb)",
                                (_e,))
                        # NEVER zero a contact another source already found. In
                        # --qualify mode most rows arrive WITH an AICP contact;
                        # writing 0 here because this particular page published
                        # no mailto: would delete 10 points of real evidence.
                        cur.execute("select 1 from contacts where entity_id = %s", (_e,))
                        if cur.fetchone() is None:
                            cur.execute(
                                "update entities set metadata ="
                                " jsonb_set(metadata,'{enrichment_result}','\"no_contact_found\"')"
                                " where id = %s", (_e,))
                            cur.execute(
                                "select set_scoring_input(%s,'reachable_decision_maker','0'::jsonb)",
                                (_e,))
                    db.run(_write_no_email)
                continue

            best = emails[0]
            kind = best["kind"]
            # reachable_decision_maker = 1.0 means "a NAMED person in a target
            # role". A personal-shaped address with nobody attached to it is
            # reachable but not named, so it scores like a role inbox.
            if kind == "personal" and not best["name"]:
                kind = "role"
            stats[kind] += 1
            rdm = 1.0 if kind == "personal" else 0.5
            log("      %d page(s) | %s (%s)%s%s"
                % (found["pages"], best["email"], kind,
                   "  name=" + best["name"] if best["name"] else "",
                   "  invite=" + found["invitation"] if found["invitation"] else ""))

            if args.dry_run:
                continue

            def _write_found(cur, _e=eid, _f=found, _b=best, _em=emails,
                             _r=rdm, _k=kind):
                cur.execute("""
                    insert into contacts (entity_id, full_name, role_title, email,
                                          email_status, email_verified_at, verifier,
                                          source, is_primary)
                    values (%s,%s,%s,%s,%s, now(), 'sitescrape_mx', 'site_scrape', true)
                    on conflict do nothing
                """, (_e, _b["name"], _b["role"], _b["email"],
                      "unverified" if _k == "personal" else "catch_all"))
                for extra in _em[1:4]:
                    cur.execute("""
                        insert into contacts (entity_id, full_name, role_title, email,
                                              email_status, source, is_primary)
                        values (%s,%s,%s,%s,'unverified','site_scrape',false)
                        on conflict do nothing
                    """, (_e, extra["name"], extra["role"], extra["email"]))
                cur.execute("select set_scoring_input(%s,'reachable_decision_maker',%s::jsonb)",
                            (_e, str(_r)))
                if _f["invitation"]:
                    cur.execute("select set_scoring_input(%s,'collaboration_openness','1'::jsonb)",
                                (_e,))
                write_size(cur, _e, _f)
                write_content_signals(cur, _e, _f)
                cur.execute("""update entities
                               set metadata = jsonb_set(metadata,'{enrichment_result}','"site_scrape"'),
                                   status = case when status = 'discovered' then 'enriched' else status end
                               where id = %s""", (_e,))
            db.run(_write_found)

    conn.close()
    log("\n  named person   : %d" % stats["personal"])
    log("  role address   : %d" % stats["role"])
    log("  nothing found  : %d" % stats["none"])
    log("  robots blocked : %d" % stats["blocked"])
    log("  dead domain    : %d" % stats["no_mx"])
    reached = stats["personal"] + stats["role"]
    log("\n  contactable: %d of %d (%.0f%%)"
        % (reached, len(targets), 100.0 * reached / len(targets)))
    if not args.dry_run:
        log("\n  re-score with:  python tools/run_sql.py -c "
            "\"select count(*) from score_segment('us-production-houses');\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
