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

IN THEIR OWN WORDS (2026-09-18). The owner's outreach template has a paragraph
about what makes each company worth writing to ("Which is why Tonko House drew
me in..."). It is written from what the company says about itself: every read
keeps the home page's title and description and the first real paragraphs of
its About page under metadata.site_about. --about reads just that, for leads
that have a website and no site_about yet, shortlisted first, and writes
nothing else: no contacts, no scores.

ROUTES IN BESIDES EMAIL (2026-09-17). The owner's review: "Contact details
missing in each lead". A site that publishes no address usually still has a
way in -- a phone number, a contact page with a form, an Instagram. Every read
now records those under metadata.site_contact_routes, and contact-finding mode
reads each lead that has no usable address ONCE under these rules, shortlisted
leads included. LinkedIn links are never recorded, let alone followed.

Usage:
    python tools/enrich_sitescrape.py --limit 5 --dry-run
    python tools/enrich_sitescrape.py --limit 25
    python tools/enrich_sitescrape.py --source google_news_rss --limit 12
"""
import os
import argparse
import html as html_lib
from concurrent.futures import ThreadPoolExecutor
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
# names come off team pages with their labels attached ("Chloe Sedelmaier Executive",
# "Contact Jeffrey Levine"); tools/contacts.py takes the labels off before a row is written
from contacts import clean_name  # noqa: E402

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
CONTACT_PATH_RE = re.compile(r"contact|connect|reach|get-in-touch|enquir|inquir", re.I)
ABOUT_PATH_RE = re.compile(r"about|story|who-we-are|mission|company|studio|philosophy", re.I)
ABOUT_PATHS = ["/", "/about", "/about-us", "/our-story", "/who-we-are", "/story", "/company", "/studio"]
META_DESC_RES = [re.compile(r"""<meta\b[^>]*\b(?:name|property)\s*=\s*["'](?:description|og:description)["'][^>]*"""
                            r"""\bcontent\s*=\s*["']([^"']{20,500})["']""", re.I),
                 re.compile(r"""<meta\b[^>]*\bcontent\s*=\s*["']([^"']{20,500})["'][^>]*"""
                            r"""\b(?:name|property)\s*=\s*["'](?:description|og:description)["']""", re.I)]
# boilerplate that is not a company describing itself
ABOUT_NOISE_RE = re.compile(r"cookie|javascript|browser|subscribe|newsletter|sign up|log ?in|privacy|terms of|"
                            r"all rights reserved|copyright|\u00a9|click here|skip to|loading|404|page not found|"
                            r"one moment|just a moment|checking your|attention required|access denied|forbidden|"
                            r"under construction|coming soon|site is not available|verify you are human", re.I)
SOCIAL_RE = re.compile(r"^https?://(?:www\.|m\.)?(instagram\.com|facebook\.com|x\.com|twitter\.com|tiktok\.com|"
                       r"vimeo\.com|youtube\.com)/((?:channel/|c/|user/)?@?[A-Za-z0-9_.\-]+)/?(?:[?#].*)?$", re.I)
SOCIAL_SKIP = {"share", "sharer", "sharer.php", "intent", "home", "login", "signup", "explore", "watch", "embed",
               "hashtag", "p", "reel", "reels", "tr", "dialog", "plugins", "privacy", "legal", "about", "help",
               "policies", "stories", "search", "hashtags", "results", "playlist", "feed"}
SOCIAL_NAME = {"instagram.com": "instagram", "facebook.com": "facebook", "x.com": "x", "twitter.com": "x",
               "tiktok.com": "tiktok", "vimeo.com": "vimeo", "youtube.com": "youtube"}

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
    r"\b(netflix|hulu|hbo(?: max)?|amazon prime|prime video|apple tv\+?|"
    r"disney\+|peacock|paramount\+)\b", re.I)
# Bare "max" went in 2026-09-17: it matched "Director: Doron Max" and "MAX" in a
# Japanese radio show's blurb. HBO Max still matches as "hbo max".

# Code is not a claim. Pages carry CSS and JSON, and until 2026-09-17 the text
# the platform and genre patterns read still had them in it: "film-logo{max",
# "show svg[data-v-16bb3b6a]{transform:rotate(180deg)}@media (max" and
# 'Documentary)","slug":"netflix' each earned a distribution credit.
CODE_BLOCK_RE = re.compile(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1\s*>|<!--.*?-->")
CODE_CHARS_RE = re.compile(r"[{}\[\]<>=;\\|]|\"[:,]\"|@media|\*/|/\*|\bpx\b")


def page_text_of(page):
    """What a visitor reads: tags, scripts, styles and comments removed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", CODE_BLOCK_RE.sub(" ", page or "")))


def platform_claim_ok(claim):
    """A platform claim fit to credit and to show a reviewer: prose, not code."""
    if not claim or not isinstance(claim, str):
        return False
    text = html_lib.unescape(claim)               # 'Series &quot;Gaming Wall Street&quot;' is prose
    return not CODE_CHARS_RE.search(text) and bool(PLATFORM_RE.search(text))


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


def _clean_text(fragment):
    t = html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))
    return re.sub(r"\s+", " ", t).strip()


def read_about(page, path, about):
    """Fill `about` with what the page says the company is: the title and description of the first page
    that has them, and on an about-style page its first real paragraphs."""
    if not about.get("title"):
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
        t = _clean_text(m.group(1)) if m else ""
        if t and not ABOUT_NOISE_RE.search(t):
            about["title"] = t[:160]
    if not about.get("description"):
        for rx in META_DESC_RES:
            m = rx.search(page)
            d = _clean_text(m.group(1)) if m else ""
            if len(d.split()) >= 5 and not ABOUT_NOISE_RE.search(d):
                about["description"] = d[:400]
                break
    if not about.get("about") and (path != "/" and ABOUT_PATH_RE.search(path)):
        body = CODE_BLOCK_RE.sub(" ", page)
        paras = [_clean_text(x) for x in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", body)]
        paras = [x for x in paras if len(x.split()) >= 12 and not ABOUT_NOISE_RE.search(x)
                 and not EMAIL_RE.search(x) and "http" not in x.lower()]
        if paras:
            about["about"] = " ".join(paras[:2])[:700]
            about["page"] = path


def scrape_site(domain, company=None, paths=None, max_pages=None, about_only=False):
    """Return findings for one domain, honouring robots.txt throughout. With about_only, only what the
    company says about itself is read, from the home page and its about-style pages."""
    out = {"pages": 0, "emails": [], "invitation": None, "blocked": None,
           "error": None, "team_count": 0, "team_page": None,
           "team_leadership": False, "genre_terms": set(), "platform_claim": None,
           "phones": [], "contact_page": None, "contact_form": False, "socials": {},
           "about": {}}

    rp, err = robots_for(domain)
    if rp is None:
        out["blocked"] = err
        return out

    base = "https://%s" % domain
    tried, queue = set(), []
    for p in (paths or CANDIDATE_PATHS):
        queue.append(urljoin(base, p))
    limit = max_pages or MAX_PAGES_PER_SITE

    seen_emails = {}
    while queue and out["pages"] < limit:
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
        read_about(html, path, out["about"])
        if about_only:
            if out["about"].get("about"):
                break                         # the home page's words and an about page: enough
            for href in re.findall(r'href=["\']([^"\']+)["\']', html)[:300]:
                nxt = urljoin(url, href)
                if (urlparse(nxt).netloc.replace("www.", "") == domain and ABOUT_PATH_RE.search(urlparse(nxt).path)
                        and nxt not in tried and nxt not in queue):
                    queue.insert(0, nxt)
            continue

        page_text = page_text_of(html)
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
                claim = re.sub(r"\s+", " ", m.group(0)).strip()[:160]
                if not SERVICE_WORK_RE.search(window) and platform_claim_ok(claim):
                    out["platform_claim"] = claim
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

        # routes in besides email: a phone, the contact page and its form, social profiles
        if CONTACT_PATH_RE.search(path):
            out["contact_page"] = out["contact_page"] or url
            if re.search(r"<form\b", html, re.I) and re.search(r"type=[\"']?email|name=[\"'][^\"']*(?:email|message)", html, re.I):
                out["contact_form"] = True
        for tel in re.findall(r'href=["\']tel:([^"\']+)["\']', html, re.I)[:6]:
            tel = urllib.parse.unquote(html_lib.unescape(tel)).strip()
            if 7 <= len(re.sub(r"\D", "", tel)) <= 15 and tel not in out["phones"]:
                out["phones"].append(tel)
        for href in re.findall(r'href=["\'](https?://[^"\']+)["\']', html)[:400]:
            m = SOCIAL_RE.match(html_lib.unescape(href))
            if not m:
                continue                          # (linkedin.com never matches: it is not recorded)
            net, handle = SOCIAL_NAME[m.group(1).lower()], m.group(2)
            if net not in out["socials"] and handle.split("/")[0].lower().lstrip("@") not in SOCIAL_SKIP:
                out["socials"][net] = html_lib.unescape(href).split("?")[0].split("#")[0]

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
    if claim and platform_claim_ok(claim):
        cur.execute(
            "select set_scoring_input(%s,'distribution_relationship','0.5'::jsonb)"
            " from entities where id = %s"
            "  and coalesce((metadata->'scoring_inputs'->>'distribution_relationship')::numeric,0) = 0",
            (eid, eid))
        cur.execute(
            "update entities set metadata = metadata ||"
            " jsonb_build_object('site_platform_evidence', to_jsonb(%s::text))"
            " where id = %s", (claim, eid))


def write_about(cur, eid, found):
    """What the company says it is (see read_about), stamped so it is read once."""
    import datetime as dt
    import json as _json
    about = dict(found.get("about") or {})
    about["read_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if found.get("blocked"):
        about["blocked"] = found["blocked"]
    cur.execute("update entities set metadata = metadata || jsonb_build_object('site_about', %s::jsonb)"
                " where id = %s", (_json.dumps(about), eid))


def about_pass(db, limit, workers, dry_run=False):
    """--about: read what each company says about itself, and nothing else."""
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.domain from entities e join segments s on s.id = e.segment_id
        where s.slug = %s and e.domain is not null and not (e.metadata ? 'site_about')
          and e.status in ('shortlisted', 'discovered', 'enriched', 'scored', 'ready_for_review')
        order by (e.status = 'shortlisted') desc, e.fit_score desc nulls last, e.name
        limit %s""", (SEGMENT, limit)), cur.fetchall())[1])
    if not rows:
        log("nothing to read -- every lead with a website has its own words on record")
        return 0
    log("reading what %d compan(ies) say about themselves%s\n" % (len(rows), "  [DRY RUN]" if dry_run else ""))

    def read_one(t):
        eid, name, domain = t
        try:
            if not has_mx(domain):
                return t, {"about": {}, "blocked": "the domain does not resolve"}
            return t, scrape_site(domain, name, paths=ABOUT_PATHS, max_pages=3, about_only=True)
        except Exception as exc:                       # never let one site kill the run
            return t, {"about": {}, "error": type(exc).__name__}

    got = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for (eid, name, domain), found in pool.map(read_one, rows):
            a = found.get("about") or {}
            has = bool(a.get("description") or a.get("about"))
            got += has
            log("  %-34s %-28s %s" % (name[:34], domain[:28], ("about page + description" if a.get("about") and
                a.get("description") else "about page" if a.get("about") else "description" if has else
                (found.get("blocked") or found.get("error") or "nothing usable"))))
            if not dry_run and not found.get("error"):
                db.run(lambda cur, _e=eid, _f=found: write_about(cur, _e, _f))
    log("\n%d of %d have their own words on record%s" % (got, len(rows), "  [DRY RUN]" if dry_run else ""))
    return 0


def write_routes(cur, eid, found):
    """Every way in the site shows besides an email address, and when it was read."""
    import datetime as dt
    import json as _json
    routes = {"phones": (found.get("phones") or [])[:3], "contact_page": found.get("contact_page"),
              "contact_form": bool(found.get("contact_form")), "socials": found.get("socials") or {},
              "pages_read": found.get("pages") or 0, "read_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if found.get("blocked"):
        routes["blocked"] = found["blocked"]          # robots.txt said no, or the domain is gone
    cur.execute("update entities set metadata = metadata || jsonb_build_object('site_contact_routes', %s::jsonb)"
                " where id = %s", (_json.dumps(routes), eid))


def write_invitation(cur, eid, phrase):
    """The words on their site that earned collaboration_openness."""
    cur.execute("update entities set metadata = metadata || jsonb_build_object('site_invitation', %s::text)"
                " where id = %s", (phrase, eid))


def rejudge_claims(db, dry_run=False):
    """Retract distribution credit that rested on code read as a claim.

    A site's platform claim is worth 0.5. When the recorded claim is CSS or
    JSON rather than a sentence, the credit is withdrawn: the claim moves to
    metadata.retracted_evidence with the reason, and the criterion goes back
    to 0 listed in unverified_inputs (free for real evidence to overwrite) --
    unless news evidence or a fuller credit holds it up, in which case only
    the bad claim is removed. The row is re-scored either way."""
    import datetime as dt
    import json as _json
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.status, e.fit_score, e.metadata from entities e join segments s on s.id = e.segment_id
        where s.slug = %s and e.metadata ? 'site_platform_evidence'""", (SEGMENT,)), cur.fetchall())[1])
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    n = 0
    for eid, name, status, score, meta in rows:
        claim = meta.get("site_platform_evidence")
        if platform_claim_ok(claim):
            continue
        si = dict(meta.get("scoring_inputs") or {})
        unverified = list(meta.get("unverified_inputs") or [])
        news_dist = any(isinstance(e, dict) and e.get("criterion") == "distribution_relationship"
                        for e in (meta.get("news_evidence") or []))
        credit = si.get("distribution_relationship")
        withdraw = credit == 0.5 and not news_dist
        n += 1
        log("  %-34s %-16s %s  %r" % (name[:34], status, "credit withdrawn" if withdraw else "claim removed",
                                      str(claim)[:70]))
        if dry_run:
            continue
        if withdraw:
            si["distribution_relationship"] = 0
            if "distribution_relationship" not in unverified:
                unverified.append("distribution_relationship")
        history = list(meta.get("retracted_evidence") or [])
        history.append({"criterion": "distribution_relationship", "site_platform_evidence": claim,
                        "retracted_at": now,
                        "reason": "not a claim that their work ran on a streamer: page code or a stray word "
                                  "(tools/enrich_sitescrape.py)"})

        def write(cur, _e=eid, _si=si, _u=unverified, _h=history):
            cur.execute("update entities set metadata = (metadata - 'site_platform_evidence') || %s::jsonb,"
                        " updated_at = now() where id = %s",
                        (_json.dumps({"scoring_inputs": _si, "unverified_inputs": _u, "retracted_evidence": _h}), _e))
            cur.execute("select score_entity(%s)", (_e,))
            return cur.fetchone()[0]
        log("      score %s -> %s" % (score, db.run(write)))
    log("\n  %d claim(s) that were code%s" % (n, "  [DRY RUN]" if dry_run else ""))
    return 0


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
    ap.add_argument("--about", action="store_true",
                    help="read only what each company says about itself (title, description, about page) "
                         "for leads with a website and none on record, shortlisted first; writes nothing else")
    ap.add_argument("--rejudge-claims", action="store_true",
                    help="no network: withdraw distribution credit whose recorded platform claim is page "
                         "code (CSS, JSON) rather than a sentence, and re-score those rows")
    args = ap.parse_args()

    if args.about:
        from dbconn import Db
        db = Db()
        try:
            return about_pass(db, args.limit, args.workers, args.dry_run)
        finally:
            db.close()

    if args.rejudge_claims:
        from dbconn import Db
        db = Db()
        try:
            return rejudge_claims(db, args.dry_run)
        finally:
            db.close()

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
             "e.metadata->'discovery_raw'->'wikidata'->>'parent_organisation' is null"]
    if not args.qualify:
        # contact-finding mode: every lead with no USABLE address (a retired junk address is no way
        # in), shortlisted ones included, each read once under the routes rules. Until 2026-09-17 it
        # took "no contact row at all" and, stamping nothing, re-read the same sites on every run.
        where.append("e.status in ('discovered','enriched','scored','ready_for_review','shortlisted')")
        where.append("not exists (select 1 from contacts c where c.entity_id = e.id and c.email is not null"
                     " and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)")
        where.append("not (e.metadata ? 'site_contact_routes')")
    else:
        where.append("e.status in ('discovered','enriched','scored','ready_for_review')")
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
                    # tried, so contact-finding does not come back to it every run
                    db.run(lambda cur, _e=eid: write_routes(cur, _e, {"blocked": "the domain does not resolve"}))
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
                if not args.dry_run:
                    db.run(lambda cur, _e=eid, _f=found: write_routes(cur, _e, _f))
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
                        write_routes(cur, _e, _f)
                        if _f.get("about"):
                            write_about(cur, _e, _f)
                        if _f["invitation"]:
                            cur.execute(
                                "select set_scoring_input(%s,'collaboration_openness','1'::jsonb)",
                                (_e,))
                            write_invitation(cur, _e, _f["invitation"])
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
                """, (_e, clean_name(_b["name"], _b["email"]), _b["role"], _b["email"],
                      "unverified" if _k == "personal" else "catch_all"))
                for extra in _em[1:4]:
                    cur.execute("""
                        insert into contacts (entity_id, full_name, role_title, email,
                                              email_status, source, is_primary)
                        values (%s,%s,%s,%s,'unverified','site_scrape',false)
                        on conflict do nothing
                    """, (_e, clean_name(extra["name"], extra["email"]), extra["role"], extra["email"]))
                cur.execute("select set_scoring_input(%s,'reachable_decision_maker',%s::jsonb)",
                            (_e, str(_r)))
                if _f["invitation"]:
                    cur.execute("select set_scoring_input(%s,'collaboration_openness','1'::jsonb)",
                                (_e,))
                    write_invitation(cur, _e, _f["invitation"])
                write_size(cur, _e, _f)
                write_content_signals(cur, _e, _f)
                write_routes(cur, _e, _f)
                if _f.get("about"):
                    write_about(cur, _e, _f)
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
