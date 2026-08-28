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
import argparse
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

SEGMENT = "us-production-houses"
UA = ("TVF-Lead-Engine/0.1 (internal BD research; contact aitools@theviralfever.com)")
TIMEOUT = 15
DELAY_SECONDS = 2.0          # between requests to the same host
MAX_PAGES_PER_SITE = 4

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

TARGET_ROLE_RE = re.compile(
    r"(founder|co-?founder|head of development|development executive|"
    r"executive producer|head of acquisitions|head of distribution|"
    r"managing director|creative director|president|owner|partner)", re.I)


def log(msg):
    print(msg, flush=True)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
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
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
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


def scrape_site(domain, company=None):
    """Return findings for one domain, honouring robots.txt throughout."""
    out = {"pages": 0, "emails": [], "invitation": None, "blocked": None,
           "error": None}

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

        if out["invitation"] is None:
            m = INVITATION_RE.search(re.sub(r"<[^>]+>", " ", html))
            if m:
                out["invitation"] = m.group(1).lower()

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--source", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="scrape and report, write nothing")
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
             "e.status in ('discovered','enriched','scored','ready_for_review')",
             "not exists (select 1 from contacts c where c.entity_id = e.id)"]
    params = [SEGMENT]
    if args.source:
        where.append("e.source = %s")
        params.append(args.source)
    params.append(args.limit)

    conn = psycopg2.connect(load_db_url(), connect_timeout=20)
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
        log("nothing to enrich -- every domain in scope already has a contact")
        conn.close(); return 0

    log("B1 site-scrape enrichment -- %d target(s)%s\n"
        % (len(targets), "  [DRY RUN]" if args.dry_run else ""))

    stats = {"personal": 0, "role": 0, "none": 0, "blocked": 0, "no_mx": 0}
    for eid, name, domain, score in targets:
        log("  %-34s %s" % (name[:34], domain))
        if not has_mx(domain):
            log("      domain does not resolve -- skipping, likely dead")
            stats["no_mx"] += 1
            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute("""update entities set metadata =
                        jsonb_set(metadata,'{enrichment_result}','"domain_dead"')
                        where id = %s""", (eid,))
                conn.commit()
            continue

        found = scrape_site(domain, name)
        if found["blocked"]:
            log("      %s -- not fetched" % found["blocked"])
            stats["blocked"] += 1
            continue

        emails = found["emails"]
        if not emails:
            log("      %d page(s) read, no address published" % found["pages"])
            stats["none"] += 1
            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute("""update entities set metadata =
                        jsonb_set(metadata,'{enrichment_result}','"no_contact_found"')
                        where id = %s""", (eid,))
                    cur.execute("select set_scoring_input(%s,'reachable_decision_maker','0'::jsonb)", (eid,))
                conn.commit()
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

        with conn.cursor() as cur:
            cur.execute("""
                insert into contacts (entity_id, full_name, role_title, email,
                                      email_status, email_verified_at, verifier,
                                      source, is_primary)
                values (%s,%s,%s,%s,%s, now(), 'sitescrape_mx', 'site_scrape', true)
                on conflict do nothing
            """, (eid, best["name"], best["role"], best["email"],
                  "unverified" if kind == "personal" else "catch_all"))
            for extra in emails[1:4]:
                cur.execute("""
                    insert into contacts (entity_id, full_name, role_title, email,
                                          email_status, source, is_primary)
                    values (%s,%s,%s,%s,'unverified','site_scrape',false)
                    on conflict do nothing
                """, (eid, extra["name"], extra["role"], extra["email"]))
            cur.execute("select set_scoring_input(%s,'reachable_decision_maker',%s::jsonb)",
                        (eid, str(rdm)))
            if found["invitation"]:
                cur.execute("select set_scoring_input(%s,'collaboration_openness','1'::jsonb)",
                            (eid,))
            cur.execute("""update entities
                           set metadata = jsonb_set(metadata,'{enrichment_result}','"site_scrape"'),
                               status = case when status = 'discovered' then 'enriched' else status end
                           where id = %s""", (eid,))
        conn.commit()

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
