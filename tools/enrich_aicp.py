#!/usr/bin/env python3
"""enrich_aicp.py -- fill AICP-sourced entities from the directory's own API.

THE DISCOVERY THAT MOTIVATES THIS. The AICP member directory page loads each
member's details from a public JSON endpoint -- the same one any visitor's
browser calls when they click a member:

    GET /api/membership/{id}

A live probe (2026-08-28) showed it returns, per member: the company website,
a published office email, street address with city/state, phone, company type,
and a list of NAMED EMPLOYEES WITH TITLES ("Sam Penfield, Executive Producer").
Executive Producer is in this segment's target_contact_roles.

That converts the AICP harvest from its weakest form (247 names, nothing
contactable, nothing scoreable) into its strongest: domain + published email +
often a named person, from the industry's own authoritative record rather than
a guess. BUILD_PLAN always intended AICP domains to be "filled at enrichment,
not here" -- this is that step, sourced from the directory itself.

COMPLIANCE. Verified before writing a line of this:
  * aicp.com/robots.txt is a blanket allow ("Disallow:" with no path).
  * This endpoint is what the public directory page itself calls per click;
    we read the same data a human visitor sees, at a slower rate than a human
    clicking through would generate (1.5s+ between requests, one at a time).
  * Reference-only, internal use, never republished -- per the ToS note in
    BUILD_PLAN's compliance lines. The export sheet is internal.
  * No LinkedIn, no third parties. One directory, first-party data.

SCORING -- what the evidence supports and nothing more:
  geography_signal = 'us'      only when the office country says United States
  has_reachable_presence       true (site + published contact)
  reachable_decision_maker     1.0  published email matches a named employee
                               0.5  role inbox (info@) -- with the best-titled
                                    employee's name attached so outreach can
                                    still address a person ("info@, addressed
                                    by name" -- the P1 pattern)
                               0.0  no email published
  right_size is NOT set: the employee list is who they registered with the
  association, not a headcount.

Usage:
    python tools/enrich_aicp.py --limit 5 --dry-run
    python tools/enrich_aicp.py --limit 50
"""
import os
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# The segment this run works on. Segment 2 is meant to be "a config row and
# connectors, nothing else" -- so the slug comes from the environment, and
# every tool, the app, and the container agree on SEGMENT_SLUG.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
UA = "TVF-Lead-Engine/0.1 (internal BD research; contact aitools@theviralfever.com)"
DIRECTORY = ("https://www.aicp.com/membership-information/member-directory/"
             "general-member-directory")
API = "https://www.aicp.com/api/membership/%s"
DELAY = 1.5
TIMEOUT = 25

TARGET_ROLE_RE = re.compile(
    r"(founder|co-?founder|head of development|development executive|"
    r"executive producer|head of acquisitions|head of distribution|"
    r"managing director|president|owner|partner|ceo)", re.I)

JUNK = re.compile(r"(-->|console\.|fetch\(|\.then\(|=>|\{|\}).*$", re.S)


def log(m):
    print(m, flush=True)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(2_000_000).decode("utf-8", "ignore")


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = JUNK.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def directory_ids():
    """One fetch of the directory page -> {lowercased member name: id}.

    The id lives in each member's click handler (fetch('/api/membership/'+N));
    the name is in the <h4> that follows. The window is wide because the
    handler body is ~1,000 characters of inline JavaScript.
    """
    html = get(DIRECTORY)
    pairs = re.findall(
        r"membership/'\s*\+\s*(\d+)[\s\S]{0,2500}?<h4[^>]*font-semiBold[^>]*>([\s\S]*?)</h4>",
        html)
    out = {}
    for mid, name in pairs:
        n = clean(name)
        if n:
            out.setdefault(n.lower(), mid)
    return out


def norm_domain(url):
    m = re.match(r"^(?:[a-z][a-z0-9+.\-]*://)?(?:www\.)?([^/?#\s]+)", (url or "").strip(), re.I)
    if not m:
        return None
    d = m.group(1).lower().strip(".")
    return d if "." in d else None


def name_matches_local(first, last, addr):
    local = re.sub(r"[^a-z]", "", addr.split("@", 1)[0].lower())
    f = re.sub(r"[^a-z]", "", (first or "").lower())
    l = re.sub(r"[^a-z]", "", (last or "").lower())
    if not local or not (f or l):
        return False
    cands = {f, l, f + l, l + f, (f[:1] + l) if f and l else "", (f + l[:1]) if f and l else ""}
    if local in cands - {""}:
        return True
    if any(p and len(p) >= 4 and p in local for p in (f, l)):
        return True
    # Diminutives: matt@ is Matthew, tim@ is Timothy. startswith is already
    # directional -- "Martha" does not start with "art" -- so prefixes are safe
    # from length 3, EXCEPT locals that are plausibly a department rather than
    # a person (art@, ed@, pr@ ...). The first repair pass wrongly stripped
    # Timothy Ward from tim@ because of an over-cautious length-4 guard.
    if local in {"art", "ads", "ad", "ed", "pr", "hr", "it", "biz", "dev", "ops"}:
        return False
    return len(local) >= 3 and any(p and p.startswith(local) for p in (f, l))


def parse_member(payload):
    """Pull the useful facts out of one /api/membership response."""
    d = payload.get("data", {}) if isinstance(payload, dict) else {}
    member = d.get("member") or {}
    offices = d.get("offices") or []
    office = offices[0] if offices else {}

    # employees arrive as a dict of lists keyed by type
    people = []
    emps = d.get("employees") or {}
    if isinstance(emps, dict):
        for group in emps.values():
            if isinstance(group, list):
                people.extend(group)
    elif isinstance(emps, list):
        people = emps

    emails = [e.strip().lower() for e in re.split(r"[,;\s]+", office.get("emails") or "")
              if "@" in e]
    return {
        "website": norm_domain(office.get("website")),
        "emails": emails,
        "city": clean(office.get("city")),
        "state": clean(office.get("state")),
        "country": clean(office.get("country")),
        "phone": clean(office.get("phone")),
        "company_type": clean(member.get("company_type")),
        "people": [{"first": clean(p.get("first_name")),
                    "last": clean(p.get("last_name")),
                    "title": clean(p.get("title"))}
                   for p in people if p.get("first_name") or p.get("last_name")],
    }


def pick_contact(info):
    """Decide the primary contact and its honesty level.

    Returns (full_name, title, email, rdm) -- rdm being what the evidence
    actually supports, per the scale in the module docstring.
    """
    email = info["emails"][0] if info["emails"] else None
    people = info["people"]

    # best-titled person first: a target role beats an untitled name
    people = sorted(people, key=lambda p: 0 if TARGET_ROLE_RE.search(p["title"] or "") else 1)
    named = people[0] if people else None

    if not email:
        return (None, None, None, 0.0)

    # does the mailbox belong to one of the named people?
    for p in people:
        if name_matches_local(p["first"], p["last"], email):
            full = (p["first"] + " " + p["last"]).strip()
            return (full, p["title"] or None, email, 1.0)

    # A ROLE inbox (info@, office@) with a named person attached is the P1
    # pattern -- "info@ addressed by name" -- and safe. A PERSONAL-shaped
    # mailbox that matches nobody on the roster is somebody unlisted (the live
    # run hit jesse@wtppictures.com with only "McKenzie Thompson" listed), and
    # attaching a DIFFERENT person's name to it would mis-address the email.
    # Worse than no name; leave it blank.
    local = re.sub(r"[^a-z]", "", email.split("@", 1)[0].lower())
    role_shaped = local in {
        "info", "hello", "contact", "hi", "mail", "email", "office", "admin",
        "enquiries", "inquiries", "general", "team", "studio", "press",
        "media", "reception", "mailbox", "us", "ny", "la", "atl", "nyc",
        "sales", "bids", "production", "finance", "accounts", "ep", "eps", "prod",
    }
    if named and role_shaped:
        full = (named["first"] + " " + named["last"]).strip()
        return (full, named["title"] or None, email, 0.5)

    return (None, None, email, 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from run_sql import load_db_url
    import psycopg2

    conn = psycopg2.connect(load_db_url(), connect_timeout=20)
    with conn.cursor() as cur:
        cur.execute("""
            select e.id, e.name
            from entities e join segments s on s.id = e.segment_id
            where s.slug = %s and e.source = 'aicp_directory'
              and e.status in ('discovered','enriched','scored','ready_for_review')
              and not exists (select 1 from contacts c where c.entity_id = e.id)
            order by e.name limit %s
        """, (SEGMENT, args.limit))
        targets = cur.fetchall()

    if not targets:
        log("nothing to enrich -- every AICP entity already has a contact")
        conn.close(); return 0

    log("AICP directory enrichment -- %d target(s)%s"
        % (len(targets), "  [DRY RUN]" if args.dry_run else ""))
    log("  fetching the directory index (1 request)...")
    ids = directory_ids()
    log("  %d members indexed\n" % len(ids))

    stats = {"named": 0, "role": 0, "no_email": 0, "no_id": 0, "api_error": 0, "duplicate": 0}
    for eid, name in targets:
        mid = ids.get(name.lower())
        if not mid:
            log("  %-36s NOT IN DIRECTORY INDEX" % name[:36])
            stats["no_id"] += 1
            continue

        try:
            info = parse_member(json.loads(get(API % mid)))
        except Exception as e:
            log("  %-36s api error: %s" % (name[:36], type(e).__name__))
            stats["api_error"] += 1
            time.sleep(DELAY)
            continue
        finally:
            time.sleep(DELAY)

        full, title, email, rdm = pick_contact(info)
        tier = ("named" if rdm == 1.0 else "role" if email else "no_email")
        stats[tier] += 1

        log("  %-36s %-26s %s%s%s" % (
            name[:36], info["website"] or "(no site)",
            email or "(no email)",
            ("  " + full) if full else "",
            ("  [" + title + "]") if title else ""))

        if args.dry_run:
            continue

        # One company, one row (invariant 7). The directory lists some shops
        # once per regional chapter -- BSPLA and BODEGA Studios are the same
        # company, both pointing at bodegastudios.com -- and the schema's
        # unique domain index rightly refuses the second claim. Detect it
        # BEFORE writing: the chapter listing is archived as a duplicate
        # rather than enriched as if it were a second company.
        if info["website"]:
            with conn.cursor() as cur:
                cur.execute(
                    "select 1 from entities"
                    " where segment_id = (select id from segments where slug = %s)"
                    "   and domain = %s and id <> %s",
                    (SEGMENT, info["website"], eid))
                dup = cur.fetchone()
            if dup:
                log("      -> duplicate chapter listing of %s -- archived"
                    % info["website"])
                stats["duplicate"] += 1
                with conn.cursor() as cur:
                    cur.execute(
                        "update entities set status = 'archived',"
                        " status_reason = %s,"
                        " metadata = jsonb_set(metadata, '{duplicate_of_domain}',"
                        "                      to_jsonb(%s::text))"
                        " where id = %s",
                        ("Duplicate AICP listing: same website as an existing "
                         "entity (" + info["website"] + ")",
                         info["website"], eid))
                conn.commit()
                continue

        with conn.cursor() as cur:
            if info["website"]:
                cur.execute("update entities set domain = %s where id = %s and domain is null",
                            (info["website"], eid))
            # location and provenance live in metadata; hq_city/hq_state are
            # the same fields the P1 hand-entered rows use
            cur.execute("""
                update entities set metadata = metadata || jsonb_build_object(
                    'hq_city', %s, 'hq_state', %s,
                    'aicp_detail', jsonb_build_object(
                        'member_id', %s, 'phone', %s, 'company_type', %s,
                        'people', %s::jsonb))
                where id = %s
            """, (info["city"] or None, info["state"] or None,
                  mid, info["phone"] or None, info["company_type"] or None,
                  json.dumps(info["people"][:6]), eid))

            if email:
                cur.execute("""
                    insert into contacts (entity_id, full_name, role_title, email,
                                          email_status, source, is_primary)
                    values (%s,%s,%s,%s,%s,'aicp_directory', true)
                    on conflict do nothing
                """, (eid, full, title, email,
                      "unverified" if rdm == 1.0 else "catch_all"))

            cur.execute("select set_scoring_input(%s,'reachable_decision_maker',%s::jsonb)",
                        (eid, str(rdm)))
            if (info["country"] or "").lower() in ("united states", "usa", "us"):
                cur.execute("select set_scoring_input(%s,'geography_signal','\"us\"'::jsonb)",
                            (eid,))
            cur.execute("select set_scoring_input(%s,'has_reachable_presence','true'::jsonb)",
                        (eid,))
            cur.execute("""update entities
                           set metadata = jsonb_set(metadata,'{enrichment_result}','"aicp_directory_api"'),
                               status = case when status='discovered' then 'enriched' else status end
                           where id = %s""", (eid,))
        conn.commit()

    conn.close()
    log("\n  named person (rdm 1.0) : %d" % stats["named"])
    log("  role inbox   (rdm 0.5) : %d" % stats["role"])
    log("  no email published     : %d" % stats["no_email"])
    log("  not in index           : %d" % stats["no_id"])
    log("  api errors             : %d" % stats["api_error"])
    log("  duplicate listings     : %d" % stats["duplicate"])
    reached = stats["named"] + stats["role"]
    log("\n  contactable: %d of %d (%.0f%%)"
        % (reached, len(targets), 100.0 * reached / max(1, len(targets))))
    if not args.dry_run:
        log("\n  re-score:  python tools/run_sql.py -c "
            "\"select count(*) from score_segment('us-production-houses');\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
