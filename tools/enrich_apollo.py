#!/usr/bin/env python3
"""enrich_apollo.py -- the address Apollo has for a lead nobody can write to yet.

    python tools/enrich_apollo.py --limit 50 --budget 150
    python tools/enrich_apollo.py --unnamed        # an inbox, but nobody's name on it
    python tools/enrich_apollo.py --dry-run        # who would be revealed; spends nothing

WHY. On 2026-09-20, the day the key arrived, the pool looked like this: 658
open leads had a company website and no address anyone could write to (412
clipping, 213 production houses, 33 startups), and 401 more had only a shared
inbox with nobody's name on it. The first group is skipped by drafting
entirely; the second is why a draft says "Hi team at ...". Sampled free
through people search the same day, Apollo knows somebody at 12 of 15
production-house domains (11 of them with an address on file), 11 of 15
startup domains and 6 of 15 clipping domains -- clipping leads are creators
rather than companies, which is why this runs where it pays and nowhere else.

The config wrote this down long before it was built: enrichment.provider is
"apollo", contact_method is "apollo_org_match_then_people_search", the roles
come from target_contact_roles and Apollo's verification status maps onto
contacts.email_status. That block said "nothing reads this until P16". This is
P16.

WHAT IT COSTS. Searching is free -- the lead's domain and the segment's target
roles go to people search, which answers with first names, masked surnames and
titles. Only the one person worth writing to is revealed, and a reveal costs 1
credit, charged only when Apollo has that person. Phones and personal
addresses are never asked for (8 credits each, and a mobile has to be
delivered to a public webhook). --budget caps a run; the config carries the
default.

RULES, each one an invariant the rest of the engine already keeps:
  * ENABLED PER SEGMENT, in the config's enrichment block (provider apollo,
    enabled true). The owner's decision on 2026-09-20 was production houses
    only, so running this by hand against another segment spends nothing.
  * OPEN LEADS ONLY (ready_for_review, shortlisted). A rejected or archived
    lead is never enriched: the rejection is a shield, not a pause.
  * ONLY LEADS WORTH IT. score_over in the config (30 for production houses,
    the owner's rule on 2026-09-21: "if a company has a score over 30 apollo
    should find their contact addresses") keeps credits off the long tail --
    before it, a run took the best 120 by score whatever they scored, which
    meant paying for companies at 0-9.
  * THE ADDRESS COUNTS. A written contact earns the rubric's
    reachable_decision_maker (10 points; 1.0 a named person, 0.5 a catch-all),
    on the scale sql/10_enrich_template.sql set for Apollo contacts, and the
    lead is re-scored on the spot. Never lowered: a finding from AICP or the
    site that is worth more stays.
  * THE PERSON HAS TO STILL WORK THERE. Apollo's domain filter counts past
    employers too, so a revealed person whose employer and address both sit at
    some other domain is not written. The credit is spent either way; the
    wrong address is not worth keeping.
  * CONTACTS ARE ADDED, NEVER REPLACED. The info@ address stays exactly where
    it is; the named person simply outranks it (sql/28_contact_rank.sql).
  * NOTHING IS SENT HERE. A new address means the lead can be drafted, and
    every draft still waits for a person to approve it.

Durability rules from tools/dbconn.py apply: a reconnecting connection, one
commit per lead, and a per-lead stamp carrying its date, so an interrupted run
resumes and a lead Apollo did not know is tried again a month later.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import apollo  # noqa: E402
import apollo_store as store  # noqa: E402

SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
STAMP = "v1"
OPEN_STATUSES = ["ready_for_review", "shortlisted"]
DELAY = 0.5             # between leads; paid plans allow 200 searches a minute
STALE_DAYS = 30         # a lead Apollo did not know is worth asking about again later
DEFAULT_BUDGET = 150    # credits per run, unless the config says otherwise

# A title worth an address when the segment's own target roles matched nobody at the company.
# Same vocabulary contact_rank() pays its role bonus for, so the two agree on who is senior.
SENIOR_RE = re.compile(
    r"(founder|owner|ceo|chief executive|chief |president|managing director|partner|principal"
    r"|head of|director|executive producer|producer|manager|lead)", re.I)


def log(m):
    print(m, flush=True)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def segment_config(db):
    row = db.run(lambda cur: (cur.execute("select config from segments where slug = %s", (SEGMENT,)),
                              cur.fetchone())[1])
    if not row:
        return None
    cfg = row[0] if not isinstance(row, dict) else row["config"]
    return cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")


def enrich_block(cfg):
    """The enrichment block, with the defaults this tool runs on."""
    b = dict((cfg or {}).get("enrichment") or {})
    try:
        over = float(b["score_over"]) if b.get("score_over") is not None else None
    except (TypeError, ValueError):
        over = None
    return {"provider": b.get("provider"),
            "enabled": b.get("enabled") is True,
            "verified_only": b.get("verified_only") is not False,
            "credits_per_run": int(b.get("credits_per_run") or DEFAULT_BUDGET),
            "stale_days": int(b.get("recheck_after_days") or STALE_DAYS),
            "score_over": over}


def contact_value(person):
    """reachable_decision_maker for what Apollo gave, on the scale sql/10_enrich_template.sql set for
    Apollo contacts: 1.0 a named person with a real address, 0.5 an address Apollo calls catch-all
    (it may land anywhere), 0 nobody."""
    if not person or not person.get("email"):
        return 0.0
    if person.get("email_status") == "catch_all" or not person.get("name"):
        return 0.5
    return 1.0


def credit_contact(cur, eid, value):
    """Give the lead the contact points its new address earns, and re-score it. Never lowers:
    an AICP or site-scrape finding worth more stays. -> (old score, new score), or None."""
    cur.execute("select (metadata->'scoring_inputs'->>'reachable_decision_maker')::numeric,"
                " coalesce(metadata->'unverified_inputs', '[]'::jsonb) ? 'reachable_decision_maker',"
                " fit_score from entities where id = %s", (eid,))
    row = cur.fetchone()
    if not row:
        return None
    current, defaulted, before = row[0], row[1], row[2]
    if current is not None and not defaulted and float(current) >= value:
        return None
    cur.execute("select set_scoring_input(%s, 'reachable_decision_maker', to_jsonb(%s::numeric))", (eid, value))
    cur.execute("select score_entity(%s)", (eid,))
    return before, cur.fetchone()[0]


def role_rank(title, roles):
    """How well a search hit's title matches the segment's target roles: (rank, the role it matched).
    Earlier in target_contact_roles is a better rank, so the config's order is the preference order."""
    t = " ".join(str(title or "").lower().split())
    if not t:
        return 0, None
    for i, role in enumerate(roles):
        r = " ".join(str(role or "").lower().split())
        if r and r in t:
            return len(roles) - i, role
    return 0, None


def pick(people, roles):
    """The one person to pay for: an address first, then the closest role, then any senior title."""
    best, best_key, matched = None, None, None
    for p in people:
        rank, role = role_rank(p.get("title"), roles)
        senior = 1 if SENIOR_RE.search(p.get("title") or "") else 0
        key = (1 if p.get("has_email") else 0, rank, senior, len(p.get("title") or ""))
        if best_key is None or key > best_key:
            best, best_key, matched = p, key, role
    if not best:
        return None, None
    why = ("a %s" % matched) if matched else ("a senior title" if best_key[2] else "the only person Apollo lists")
    return best, why


def same_company(person, domain):
    """Apollo's domain filter counts past employers, so check the reveal actually landed there."""
    def near(a, b):
        return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
    org = person.get("organization") or {}
    d = store.norm_domain(org.get("primary_domain") or org.get("website_url"))
    if near(d, domain):
        return True
    email = (person.get("email") or "").lower()
    return near(email.split("@")[-1] if "@" in email else None, domain)


NO_EMAIL_SQL = """
  and not exists (select 1 from contacts c where c.entity_id = e.id
                  and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)"""

UNNAMED_SQL = """
  and exists (select 1 from contacts c where c.entity_id = e.id
              and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)
  and not exists (select 1 from contacts c where c.entity_id = e.id and c.full_name is not null
                  and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)"""


def candidates(db, unnamed, limit, stale_days, recheck, score_over=None):
    """Open leads with a website that Apollo could put a person behind -- and, when the config
    sets score_over, only the ones scoring above it (owner, 2026-09-21: "if a company has a score
    over 30 apollo should find their contact addresses"). Shortlisted first, then best score."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=stale_days)).replace(microsecond=0).isoformat()
    sql = """
        select e.id, e.name, e.domain, e.status, e.fit_score
        from entities e join segments s on s.id = e.segment_id
        where s.slug = %s and e.status = any(%s) and e.domain is not null
    """ + (UNNAMED_SQL if unnamed else NO_EMAIL_SQL) + ("" if recheck else """
          and coalesce(e.metadata->>'apollo_checked_at', '') < %s""") + ("" if score_over is None else """
          and coalesce(e.fit_score, 0) > %s""") + """
        order by case when e.status = 'shortlisted' then 0 else 1 end,
                 e.fit_score desc nulls last, e.name
        limit %s"""
    args = ((SEGMENT, OPEN_STATUSES) + (() if recheck else (cutoff,))
            + (() if score_over is None else (score_over,)) + (limit,))
    return db.run(lambda cur: (cur.execute(sql, args), cur.fetchall())[1])


def stamp(db, eid, outcome, person=None, credits=0.0):
    """What happened to this lead, on the lead, with its date."""
    patch = {"apollo_checked": "%s:%s" % (STAMP, outcome), "apollo_checked_at": now_iso()}
    if person:
        patch["apollo_enrich"] = {"at": patch["apollo_checked_at"], "person": person.get("apollo_id"),
                                  "name": person.get("name"), "title": person.get("title"),
                                  "email_status": person.get("apollo_email_status"), "credits": credits}

    def write(cur):
        cur.execute("update entities set metadata = coalesce(metadata, '{}'::jsonb) where id = %s and metadata is null",
                    (eid,))
        cur.execute("update entities set metadata = metadata || %s::jsonb, updated_at = now() where id = %s",
                    (json.dumps(patch), eid))
        if person:
            what = store.upsert_person(cur, eid, person)
            # the address is evidence the rubric pays for (reachable_decision_maker, 10 points):
            # the lead is re-scored now, not at the next refresh
            rescored = credit_contact(cur, eid, contact_value(person)) if person.get("email") else None
            return what, rescored
        return None, None
    return db.run(write)


def search(domain, roles, verified_only):
    """Free. Narrowest first: the target roles with an address on file, then the roles, then anyone senior."""
    base = {"q_organization_domains_list": [domain]}
    passes = []
    if roles:
        if verified_only:
            passes.append(dict(base, person_titles=roles, contact_email_status=["verified"]))
        passes.append(dict(base, person_titles=roles))
    passes.append(dict(base, contact_email_status=["verified"]) if verified_only else dict(base))
    for i, filters in enumerate(passes):
        out = apollo.search_people(filters, 1, 10)
        people = out["people"]
        if people:
            # the widest pass is anyone at the company: only a senior title is worth a credit there
            if i == len(passes) - 1 and roles:
                people = [p for p in people if SENIOR_RE.search(p.get("title") or "")]
                if not people:
                    continue
            return people, out["total"]
    return [], 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="leads to look at")
    ap.add_argument("--budget", type=int, default=0, help="credits this run may spend (default: the config's)")
    ap.add_argument("--unnamed", action="store_true",
                    help="leads that have an inbox but nobody's name: put a person in front of info@")
    ap.add_argument("--recheck", action="store_true", help="leads checked recently too")
    ap.add_argument("--score-over", type=float, default=None,
                    help="only leads scoring above this (default: the config's score_over)")
    ap.add_argument("--dry-run", action="store_true", help="search only; reveal nothing, spend nothing")
    args = ap.parse_args()

    from dbconn import Db
    db = Db()
    cfg = segment_config(db)
    if cfg is None:
        log("no segment %r" % SEGMENT)
        db.close(); return 1
    block = enrich_block(cfg)
    if block["provider"] != "apollo" or not block["enabled"]:
        log("Apollo enrichment is not enabled for %s -- nothing spent.\n"
            "  Turn it on in config/segment.%s.json: enrichment.enabled = true (provider apollo)."
            % (SEGMENT, SEGMENT))
        db.close(); return 0
    if not apollo.key_is_set():
        # Enrichment is optional, so a missing key is a skip and not a failure: failing here would
        # stop the whole weekly refresh (app/scheduler.py) before qualifying and the news sweep.
        log("APOLLO_API_KEY is not set (env, or Render's Environment tab) -- skipped, nothing spent.")
        db.close(); return 0

    roles = [r for r in (cfg.get("target_contact_roles") or []) if str(r or "").strip()]
    budget = args.budget or block["credits_per_run"]
    try:
        left = (apollo.credits() or {}).get("lead_credits_left")
    except apollo.ApolloError as e:
        left = None
        log("credits unknown (%s)" % e)
    if left is not None and left < budget:
        budget = int(left)
    over = args.score_over if args.score_over is not None else block["score_over"]
    above = "" if over is None else " scoring over %g" % over
    rows = candidates(db, args.unnamed, args.limit, block["stale_days"], args.recheck, over)
    if not rows:
        log("nothing to enrich -- every open lead%s here already has %s, or Apollo was asked about it"
            " in the last %d days" % (above, "a named person" if args.unnamed else "an address", block["stale_days"]))
        db.close(); return 0

    log("apollo enrichment -- %s | %d lead(s)%s%s | budget %d credit(s)%s"
        % (SEGMENT, len(rows), above, " without a name on the inbox" if args.unnamed else " with nothing to write to",
           budget, "  [DRY RUN: nothing is revealed]" if args.dry_run else ""))
    log("  roles: %s" % (", ".join(roles) if roles else "(any senior title)"))
    if left is not None:
        log("  credits left before this run: %s\n" % left)

    spent = 0.0
    stats = {"written": 0, "named": 0, "no_email": 0, "unknown": 0, "elsewhere": 0, "error": 0, "left": 0}
    for done, (eid, name, domain, status, score) in enumerate(rows):
        if not args.dry_run and spent + 1 > budget:
            stats["left"] = len(rows) - done
            log("\n  budget reached -- %d lead(s) left for the next run" % stats["left"])
            break
        try:
            people, total = search(domain, roles, block["verified_only"])
        except apollo.ApolloError as e:
            if e.status in (401, 403):
                log("  %-34s %s" % (name[:34], e))
                db.close(); return 1
            if e.status == 429:
                wait = min(int(e.retry_after or 60), 120)
                log("  rate limit: waiting %ds" % wait)
                time.sleep(wait)
                try:
                    people, total = search(domain, roles, block["verified_only"])
                except apollo.ApolloError as e2:
                    log("  %-34s stopped: %s" % (name[:34], e2))
                    break
            else:
                log("  %-34s search failed: %s" % (name[:34], e))
                stats["error"] += 1
                time.sleep(DELAY)
                continue
        finally:
            time.sleep(DELAY)

        if not people:
            log("  %-34s %-16s Apollo knows nobody at %s" % (name[:34], status, domain))
            stats["unknown"] += 1
            if not args.dry_run:
                stamp(db, eid, "none")
            continue
        who, why = pick(people, roles)
        shown = "%s %s -- %s" % (who.get("first_name") or "?", who.get("last_name_obfuscated") or "",
                                 who.get("title") or "no title")
        if args.dry_run:
            log("  %-34s %-16s would reveal %s (%s)%s"
                % (name[:34], status, shown, why, "" if who.get("has_email") else "  [no address on file]"))
            continue
        if not who.get("has_email"):
            log("  %-34s %-16s %s has no address on file" % (name[:34], status, shown))
            stats["no_email"] += 1
            stamp(db, eid, "no-email")
            continue

        try:
            rep = apollo.reveal_people([who["id"]])
        except apollo.ApolloError as e:
            log("  %-34s reveal failed: %s" % (name[:34], e))
            stats["error"] += 1
            if e.status in (401, 403):
                db.close(); return 1
            continue
        spent += float(rep.get("credits") or 0)
        person = (rep.get("people") or [None])[0]
        if not person:
            log("  %-34s %-16s Apollo had nothing more on %s" % (name[:34], status, shown))
            stats["unknown"] += 1
            stamp(db, eid, "none")
            continue
        if not same_company(person, domain):
            org = (person.get("organization") or {}).get("name") or "somewhere else"
            log("  %-34s %-16s %s works at %s now -- not written"
                % (name[:34], status, person.get("name") or shown, org))
            stats["elsewhere"] += 1
            stamp(db, eid, "elsewhere", credits=rep.get("credits") or 0)
            continue
        if not person.get("email"):
            log("  %-34s %-16s %s revealed without an address" % (name[:34], status, person.get("name") or shown))
            stats["no_email"] += 1
            stamp(db, eid, "no-email", person=person, credits=rep.get("credits") or 0)
            continue
        what, rescored = stamp(db, eid, "written", person=person, credits=rep.get("credits") or 0)
        stats["written"] += 1
        stats["named"] += 1 if person.get("name") else 0
        log("  %-34s %-16s %s, %s  <%s>  %s%s%s"
            % (name[:34], status, person.get("name") or "(no name)", person.get("title") or "no title",
               person.get("email"), person.get("email_status"), "" if what == "added" else "  (already known)",
               "  score %s -> %s" % rescored if rescored else ""))

    if not args.dry_run and stats["written"]:
        n = db.run(lambda cur: (cur.execute("select refresh_primary_contacts(%s)", (SEGMENT,)),
                                cur.fetchone()[0])[1])
        log("\n  primary contact re-chosen on %s lead(s)" % n)
    db.close()

    log("\n  addresses written       : %d" % stats["written"])
    log("  no address on file      : %d" % stats["no_email"])
    log("  Apollo knows nobody     : %d" % stats["unknown"])
    log("  had moved on            : %d" % stats["elsewhere"])
    log("  errors                  : %d" % stats["error"])
    log("  credits spent           : %g%s" % (spent, "  [DRY RUN: none]" if args.dry_run else ""))
    if not args.dry_run:
        try:
            log("  credits left            : %s" % (apollo.credits() or {}).get("lead_credits_left"))
        except apollo.ApolloError:
            pass
        if stats["written"]:
            log("\n  Drafting picks these up by itself within fifteen minutes; every draft still waits"
                "\n  for approval in Outreach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
