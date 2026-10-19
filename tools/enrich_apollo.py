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
  * ONLY LEADS WORTH IT. score_over in the config keeps credits off the long
    tail -- before it, a run took the best 120 by score whatever they scored,
    which meant paying for companies at 0-9. The owner set it to 30 on
    2026-09-21 and lowered it the same day to 22.5: "any lead over 22.5 with
    no contacts find and add them". A company with nobody to write to is
    missing the 10 contact points, so 22.5 is roughly 30 once it has someone.
  * NO WEBSITE IS NOT A DEAD END (find_website_by_name). The lead is looked up
    by its name in Apollo's company search, 1 credit, and accepted only when
    exactly one company carries that exact name ("Atlanta-Based Freeli Films"
    is looked up as "freeli films") with a website that is not a platform's.
    The website is written to the lead unless another lead already holds it,
    which is the same company twice and a merge for a person -- the rule
    tools/resolve_domains.py keeps.
  * THE ADDRESS COUNTS. A written contact earns the rubric's
    reachable_decision_maker (10 points; 1.0 a named person whose address
    Apollo verified, 0.5 any other address), on the rubric's own scale, and the
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

LCX SERVICES (2026-10-07, the owner: "Enriching from apollo is acceptable"). Each of these is
switched on by the project's own config, so US Production Houses runs exactly as it did:
  * enrichment.credits_per_week / keep_in_reserve: a weekly cap counted in the ledger (apollo_spend,
    sql/33, tools/apollo_budget.py) across every run and the harvest's company pages, and a floor of
    credits always left for the other projects. Every credit any project spends is written there.
  * audiences[].contact_roles: who to look for depends on what the lead is (a school's principal, a
    hotel's director of sales, a retailer's head of visual merchandising), not one list for all.
  * metadata.apollo.id (a lead the Apollo harvest found): people are searched at Apollo's record of
    that company, i.e. its current employees, so a past employee is never paid for.
  * enrichment.current_employer_check: for a lead searched by website, a free hit whose employer's
    name is not the lead's is not paid for.
  * enrichment.reveal_countries: only leads based there (US, GB, IN, AE) -- elsewhere the law on
    cold email to an address nobody published is stricter.
  * enrichment.senior_titles: what counts as senior when nobody in the target roles is found, and
    enrichment.require_fitting_role: nobody is paid for whose title is neither a role, nor shares a
    real word with one, nor senior.
  * enrichment.skip_revealed_elsewhere: a person already revealed for another project is not paid for
    again (the same person must not get a first email from two projects, and the credit is saved).
  * enrichment.require_site_read (scoring v4, the owner's decision 2026-10-07: "Apollo reveals only for
    leads over 60 whose own site was read and that are not the wrong buyer"): a lead is a candidate only
    once the site pass has read pages of its site and tools/lcx_judge.py found the company's own words
    there (lcx_judgement.site_read), the site is the company's own (site_theirs is not false),
    wrong_buyer is 0 and too_big under 1.
  * auto_shortlist.named_contact_for (same day): banks and mid-size companies are shortlisted only with a
    named person to write to (sql/14), so for those audiences the default pass also takes a lead whose only
    address is an inbox with nobody's name on it.
A project with a budget also stops the run if a credit cannot be written to the ledger, since its cap
is read from there; when Apollo cannot say what is left, it spends nothing (tools/apollo_budget.py).
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
    countries = [str(c).upper() for c in b.get("reveal_countries") or [] if str(c).strip()]
    senior = None
    if b.get("senior_titles"):
        try:
            senior = re.compile(str(b["senior_titles"]), re.I)
        except re.error:
            senior = None
    # auto_shortlist.named_contact_for (LCX Services, 2026-10-07): audiences the shortlist step only takes with
    # a named person to write to, so a lead of theirs with only an info@ inbox is still one to find a person at
    auto = (cfg or {}).get("auto_shortlist") or {}
    named_for = [str(k) for k in auto.get("named_contact_for") or [] if str(k or "").strip()] \
        if auto.get("enabled") is True and isinstance(auto.get("named_contact_for"), list) else []
    return {"provider": b.get("provider"),
            "enabled": b.get("enabled") is True,
            "verified_only": b.get("verified_only") is not False,
            "credits_per_run": int(b.get("credits_per_run") or DEFAULT_BUDGET),
            "credits_per_week": b.get("credits_per_week"),
            "keep_in_reserve": b.get("keep_in_reserve"),
            "stale_days": int(b.get("recheck_after_days") or STALE_DAYS),
            "score_over": over,
            "by_name": b.get("find_website_by_name") is True,
            "reveal_countries": countries,
            "employer_check": b.get("current_employer_check") is True,
            "strict_roles": b.get("require_fitting_role") is True,
            "skip_known_elsewhere": b.get("skip_revealed_elsewhere") is True,
            "site_read": b.get("require_site_read") is True,
            "named_for": named_for,
            "senior": senior}


def roles_for(cfg, kind):
    """Who to look for at this lead: its audience's contact_roles when the config has them (LCX Services),
    else the segment's one target_contact_roles list."""
    for a in (cfg or {}).get("audiences") or []:
        if kind and a.get("key") == kind and a.get("contact_roles"):
            return [r for r in a["contact_roles"] if str(r or "").strip()]
    return [r for r in ((cfg or {}).get("target_contact_roles") or []) if str(r or "").strip()]


# Words many unrelated companies start with, so sharing one says nothing: "First Citizens Bank" is not
# "First Horizon", nor "Bank of Hope" "Bank of Marin".
COMMON_FIRST = {"first", "bank", "national", "united", "american", "global", "international", "royal", "city",
                "new", "great", "general", "central", "capital", "community", "citizens", "peoples", "people",
                "home", "the", "big", "north", "south", "east", "west", "pacific", "atlantic", "golden", "star"}


def works_at(person, company):
    """Free check, before a credit: does the search hit's current employer carry the lead's name?
    ("Gyldendal A/S" and "Gyldendal" do; "Penguin Random House" and "Ladybird Books" do not; nor do
    "First Citizens Bank" and "First Horizon", which share only a word many companies start with.)"""
    a, b = name_key(person.get("company")), name_key(company)
    if not a or not b:
        return False
    if a == b or a.startswith(b + " ") or b.startswith(a + " "):
        return True
    # the same name spelt with other punctuation: "AG Barr Group" is "A.G. Barr", "Abe's of Maine" "Abes of Maine"
    short, long_ = sorted((a.replace(" ", ""), b.replace(" ", "")), key=len)
    if short == long_ or (len(short) >= 6 and long_.startswith(short)):
        return True
    first = a.split()[0]
    return first == b.split()[0] and first not in COMMON_FIRST and len(first) >= 4


def revealed_elsewhere(db, apollo_id, eid):
    """Was this person already paid for under a lead of another project? Then not again: the same person
    must not get a first email from two projects, and the credit is saved."""
    if not apollo_id:
        return None
    return db.run(lambda cur: (cur.execute(
        "select s.slug from entities e join segments s on s.id = e.segment_id"
        " where e.segment_id <> (select segment_id from entities where id = %s)"
        " and (e.metadata->'apollo_enrich'->>'person' = %s or coalesce(e.metadata->'apollo_people', '{}'::jsonb) ? %s)"
        " limit 1", (eid, apollo_id, apollo_id)), cur.fetchone())[1])


def contact_value(person):
    """reachable_decision_maker for what Apollo gave, on the rubric's own scale ("1.0 if a target-role
    contact has a valid email, 0.5 if catch-all, else 0"; sql/10_enrich_template.sql): 1.0 a named
    person whose address Apollo has verified, 0.5 an address it has not (catch-all, unverified, or
    nobody's name on it), 0 nothing to write to."""
    if not person or not person.get("email"):
        return 0.0
    if person.get("email_status") == "valid" and person.get("name"):
        return 1.0
    return 0.5


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


def role_words(roles):
    """The words the target roles are made of: founder, head, development, executive, producer..."""
    return {w for r in roles for w in re.findall(r"[a-z]+", str(r or "").lower())
            if len(w) > 2 and w not in ("the", "and")}


# Words every kind of title has, so sharing one says nothing about the person's job: "Director of Benefits
# Administration" shares "director" with "Marketing Director" and is still not who LCX writes to.
GENERIC_WORDS = {"director", "head", "manager", "chief", "officer", "senior", "lead", "vice", "president",
                 "executive", "global", "group", "regional", "area", "assistant", "associate", "deputy"}


def pick(people, roles, strict=False, senior_re=None):
    """The one person to pay for: an address first, then the closest role, then the title sharing most
    words with the target roles, then any senior title. The word overlap replaced a title-length tiebreak
    that chose Severin Films' Head of QC over its Acquisitions/Producer.
    strict (enrichment.require_fitting_role, LCX Services): nobody is paid for unless their title is one of
    the roles, shares a word with them that is not a generic one, or is senior (senior_re) -- the only
    person Apollo lists is not a reason to spend a credit."""
    words = role_words(roles)
    meaningful = words - GENERIC_WORDS
    best, best_key, matched = None, None, None
    for p in people:
        title = p.get("title") or ""
        rank, role = role_rank(title, roles)
        title_words = set(re.findall(r"[a-z]+", title.lower()))
        overlap = len(words & title_words)
        senior = 1 if (senior_re or SENIOR_RE).search(title) else 0
        if strict and not rank and not (meaningful & title_words) and not senior:
            continue
        key = (1 if p.get("has_email") else 0, rank, overlap, senior)
        if best_key is None or key > best_key:
            best, best_key, matched = p, key, role
    if not best:
        return None, None
    why = (("a %s" % matched) if matched else "a title close to the target roles" if best_key[2]
           else "a senior title" if best_key[3] else "the only person Apollo lists")
    return best, why


def same_company(person, domain, also=None):
    """Apollo's domain filter counts past employers, so check the reveal actually landed there. `also` is
    the website Apollo files the same company under, when that differs from the lead's (Severin Films:
    severin-films.com on the lead, severinfilms.com in Apollo)."""
    def near(a, b):
        return bool(a) and bool(b) and (a == b or a.endswith("." + b) or b.endswith("." + a))
    org = person.get("organization") or {}
    d = store.norm_domain(org.get("primary_domain") or org.get("website_url"))
    email = (person.get("email") or "").lower()
    at = email.split("@")[-1] if "@" in email else None
    return any(near(d, x) or near(at, x) for x in (domain, also) if x)


def headcount(domain):
    """Free: how many people Apollo lists at the website at all, so "nobody" and "nobody worth a credit"
    read differently in the log."""
    try:
        return apollo.search_people({"q_organization_domains_list": [domain]}, 1, 1)["total"]
    except apollo.ApolloError:
        return None


NO_EMAIL_SQL = """
  and not exists (select 1 from contacts c where c.entity_id = e.id
                  and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)"""

UNNAMED_SQL = """
  and exists (select 1 from contacts c where c.entity_id = e.id
              and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)
  and not exists (select 1 from contacts c where c.entity_id = e.id and c.full_name is not null
                  and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)"""

# auto_shortlist.named_contact_for (LCX Services, 2026-10-07): nobody to write to, as NO_EMAIL_SQL says, OR -- for
# these audiences -- nobody NAMED to write to, by sql/14's own test of a name, so an info@-only bank over the line
# is looked for a person at in the default pass (sql/14 never shortlists it on that inbox alone)
NO_NAMED_SQL = """
  and (not exists (select 1 from contacts c where c.entity_id = e.id
                   and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500)
       or (coalesce(e.metadata->>'kind', '') = any(%s)
           -- the contact the drafter would pick (sql/14's test) has nobody's name on it
           and not exists (select 1 from (
                             select c.full_name from contacts c
                              where c.entity_id = e.id and c.email is not null
                                and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500
                              order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,
                                       c.created_at, c.id
                              limit 1) top
                            where nullif(btrim(coalesce(top.full_name, '')), '') is not null)))"""

# enrichment.require_site_read (LCX Services, scoring v4, 2026-10-07): a credit only for a lead whose own site has
# been read and is its own, that is not the wrong kind of buyer, and not too big to answer -- so nothing is
# spent on a competitor, a software firm, a group's brand page, or a lead nobody has looked at yet. Read means
# both: the site pass fetched its pages (so the free route to an address was tried first) and tools/lcx_judge.py
# found the company's own words there (lcx_judgement.site_read: not a bot wall or a parked page), as the
# 2026-10-07 simulation's queue had it. Until the judge has run on a lead, it is not a candidate.
SITE_READ_SQL = """
  and coalesce((e.metadata->'site_contact_routes'->>'pages_read')::int, 0) > 0
  and coalesce((e.metadata->'lcx_judgement'->>'site_read')::boolean, false)
  and coalesce((e.metadata->'scoring_inputs'->>'wrong_buyer')::numeric, 0) = 0
  and coalesce((e.metadata->'scoring_inputs'->>'too_big')::numeric, 0) < 1
  and coalesce(e.metadata->'lcx_judgement'->>'site_theirs', 'true') <> 'false'
  -- nor one a gate excludes: gates never archive a shortlisted lead, so its signals are checked here
  and coalesce(e.metadata->'scoring_inputs'->>'oversized_signal', 'false') <> 'true'
  and coalesce(e.metadata->'scoring_inputs'->>'brand_risk_signal', '') <> 'unsafe'
  and coalesce(e.metadata->'scoring_inputs'->>'country_signal', '') not in ('disallowed', 'unpayable')
  and coalesce(e.metadata->'scoring_inputs'->>'activity_signal', '') <> 'dead'
  -- nor one whose email is already written: the drafter never drafts a lead twice, so a person found now would
  -- not be written to (the leads shortlisted under the old score, 2026-10-08); a cancelled draft frees it again
  and not exists (select 1 from outreach o where o.entity_id = e.id and o.direction = 'outbound'
                   and o.status not in ('cancelled', 'failed'))"""


# reveal_countries are ISO codes; a lead saved from the search page carries Apollo's country name.
COUNTRY_NAMES = {"US": ("UNITED STATES", "USA", "UNITED STATES OF AMERICA"),
                 "GB": ("UNITED KINGDOM", "UK", "GREAT BRITAIN", "ENGLAND", "SCOTLAND", "WALES", "NORTHERN IRELAND"),
                 "IN": ("INDIA",), "AE": ("UNITED ARAB EMIRATES", "UAE")}


def country_forms(codes):
    """Every way a lead may name one of these countries, upper case: the code and Apollo's names."""
    out = []
    for c in codes or []:
        c = str(c).upper()
        out += [c] + list(COUNTRY_NAMES.get(c, ()))
    return out


def candidates(db, unnamed, limit, stale_days, recheck, score_over=None, by_name=False, countries=None,
               site_read=False, named_for=None):
    """Open leads that Apollo could put a person behind -- and, when the config sets score_over, only
    the ones scoring above it (owner, 2026-09-21: "any lead over 22.5 with no contacts find and add
    them"). A lead without a website is included only when by_name is on: it is looked up by its
    name first. With countries (enrichment.reveal_countries), only leads based there: held leads are
    left out here, not after the limit, so they never crowd out the ones that can be paid for.
    site_read (enrichment.require_site_read): only leads whose own site has been read and is theirs,
    not the wrong buyer and not too big (SITE_READ_SQL). named_for (auto_shortlist.named_contact_for):
    the default pass also takes a lead of those audiences whose only address has nobody's name on it
    (NO_NAMED_SQL). Both are LCX Services' (2026-10-07); a project that sets neither runs as before.
    Shortlisted first, then a buying signal, then best score."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=stale_days)).replace(microsecond=0).isoformat()
    named_for = [k for k in (named_for or []) if k] if not unnamed else []
    sql = """
        select e.id, e.name, e.domain, e.status, e.fit_score, e.metadata->>'kind',
               e.metadata->'apollo'->>'id', upper(e.metadata->>'hq_country')
        from entities e join segments s on s.id = e.segment_id
        where s.slug = %s and e.status = any(%s)
    """ + ("" if (by_name and not unnamed) else "  and e.domain is not null\n") + (
        UNNAMED_SQL if unnamed else NO_NAMED_SQL if named_for else NO_EMAIL_SQL) + (
        SITE_READ_SQL if site_read else "") + ("" if recheck else """
          and coalesce(e.metadata->>'apollo_checked_at', '') < %s""") + ("" if score_over is None else """
          and coalesce(e.fit_score, 0) > %s""") + ("" if not countries else """
          and upper(trim(coalesce(e.metadata->>'hq_country', ''))) = any(%s)""") + """
        order by case when e.status = 'shortlisted' then 0 else 1 end,
                 case when e.metadata ? 'buying_signal' then 0 else 1 end,
                 e.fit_score desc nulls last, e.name
        limit %s"""
    args = ((SEGMENT, OPEN_STATUSES) + ((named_for,) if named_for else ()) + (() if recheck else (cutoff,))
            + (() if score_over is None else (score_over,)) + ((country_forms(countries),) if countries else ())
            + (limit,))
    return db.run(lambda cur: (cur.execute(sql, args), cur.fetchall())[1])


def ledger(db, kind, credits, ref=None):
    """Every credit, into apollo_spend as it is spent (tools/apollo_budget.py), for every project.
    -> True when written. A project with no stated budget goes on without it (the table not there yet);
    one with a budget stops the run (LEDGER_MUST_HOLD), since its cap is read from the ledger."""
    import apollo_budget
    try:
        db.run(lambda cur: apollo_budget.record(cur, SEGMENT, kind, credits, ref))
        return True
    except Exception as e:                          # noqa: BLE001
        log("  (ledger not written: %s)" % str(e).splitlines()[0][:80])
        return False


def stamp(db, eid, outcome, person=None, credits=0.0, via=None):
    """What happened to this lead, on the lead, with its date. `via` is the website Apollo files the
    company under, when the person was found there rather than at the lead's own."""
    patch = {"apollo_checked": "%s:%s" % (STAMP, outcome), "apollo_checked_at": now_iso()}
    if person:
        patch["apollo_enrich"] = {"at": patch["apollo_checked_at"], "person": person.get("apollo_id"),
                                  "name": person.get("name"), "title": person.get("title"),
                                  "email_status": person.get("apollo_email_status"), "credits": credits}
        if via:
            patch["apollo_enrich"]["apollo_domain"] = via

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


def search(domain, roles, verified_only, org_id=None, senior=None):
    """Free. Narrowest first: the target roles with an address on file, then the roles, then anyone senior.
    A pass that finds people but nobody with an address does not end the search -- Imaginary Forces had
    two executive producers with no address and a senior person with one, and the first build stopped at
    the producers. Only when no pass has anyone with an address is the first set of people returned.
    org_id searches Apollo's own record of the company instead of the lead's website."""
    base = {"organization_ids": [org_id]} if org_id else {"q_organization_domains_list": [domain]}
    passes = []
    if roles:
        if verified_only:
            passes.append(dict(base, person_titles=roles, contact_email_status=["verified"]))
        passes.append(dict(base, person_titles=roles))
    passes.append(dict(base, contact_email_status=["verified"]) if verified_only else dict(base))
    fallback = None
    for i, filters in enumerate(passes):
        out = apollo.search_people(filters, 1, 10)
        people = out["people"]
        # the widest pass is anyone at the company: only a senior title is worth a credit there
        if i == len(passes) - 1 and roles:
            people = [p for p in people if (senior or SENIOR_RE).search(p.get("title") or "")]
        if not people:
            continue
        if any(p.get("has_email") for p in people):
            return people, out["total"]
        fallback = fallback or (people, out["total"])
    return fallback or ([], 0)


# Words that say what kind of company it is legally, not which company. Industry words stay:
# "Sentient Entertainment" and "Sentient" are not the same name.
LEGAL_WORDS = {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company", "incorporated",
               "the", "plc", "lp", "llp"}


def name_key(name):
    """A company name reduced to what identifies it: "Atlanta-Based Freeli Films, LLC" -> "freeli films".
    The "<place>-based" prefix is how a headline introduces a company, and the news connector kept it."""
    s = re.sub(r"^[a-z .'&-]+?-based\s+", "", str(name or "").strip(), flags=re.I).lower()
    return " ".join(w for w in re.findall(r"[a-z0-9]+", s) if w not in LEGAL_WORDS)


def find_company(name):
    """1 credit (a company search page). The company's own record in Apollo -- only when exactly one
    company is named exactly this, with a website of its own. -> (org, None) or (None, why)."""
    import resolve_domains
    key = name_key(name)
    if len(key) < 3:
        return None, "the name is too short to look up"
    out = apollo.search_companies({"q_organization_name": key}, 1, 10)
    same = [c for c in out["companies"]
            if name_key(c.get("name")) == key and c.get("primary_domain")
            and not resolve_domains.is_third_party(c.get("primary_domain"))]
    if len(same) == 1:
        return same[0], None
    if not same:
        return None, "Apollo has no company named exactly %r" % key
    return None, "%d companies in Apollo are named %r -- left for a person" % (len(same), key)


def give_website(db, eid, org):
    """The lead's website, from Apollo's record of it -- unless another lead already has that website:
    then it is the same company under a second row, a merge for a person (tools/resolve_domains.py keeps
    the same rule, after that collision stopped two weekly refreshes). -> True when written."""
    dom = store.norm_domain(org.get("primary_domain"))

    def write(cur):
        cur.execute("select name from entities where domain = %s and id <> %s"
                    " and segment_id = (select segment_id from entities where id = %s)", (dom, eid, eid))
        other = cur.fetchone()
        if other:
            cur.execute("update entities set metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{domain_conflict}',"
                        " to_jsonb(%s::text)) where id = %s", ("%s already belongs to %s" % (dom, other[0]), eid))
            return False
        cur.execute("update entities set domain = %s, metadata = jsonb_set(coalesce(metadata, '{}'::jsonb),"
                    " '{domain_resolution}', to_jsonb(%s::text)), updated_at = now() where id = %s and domain is null",
                    (dom, "apollo company search: %s (%s)" % (org.get("name"), org.get("id")), eid))
        return cur.rowcount == 1
    return dom if db.run(write) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="leads to look at")
    ap.add_argument("--budget", type=int, default=0, help="credits this run may spend (default: the config's)")
    ap.add_argument("--unnamed", action="store_true",
                    help="leads that have an inbox but nobody's name: put a person in front of info@")
    ap.add_argument("--recheck", action="store_true", help="leads checked recently too")
    ap.add_argument("--score-over", type=float, default=None,
                    help="only leads scoring above this (default: the config's score_over)")
    ap.add_argument("--lead", action="append", default=[],
                    help="only leads whose name contains this (repeatable): one company on request")
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
        db.close()
        return 1 if (cfg.get("sourcing") or {}).get("provider") == "apollo" else 0

    roles = roles_for(cfg, None)
    budget = args.budget or block["credits_per_run"]
    try:
        left = (apollo.credits() or {}).get("lead_credits_left")
    except apollo.ApolloError as e:
        left = None
        log("credits unknown (%s)" % e)
    if left is not None and left < budget:
        budget = int(left)
    import apollo_budget
    capped = apollo_budget.capped(cfg.get("enrichment") or {})
    stop_after = False
    if capped:
        budget, why = db.run(lambda cur: apollo_budget.allowance(cur, SEGMENT, cfg.get("enrichment") or {}, left, budget))
        log("  budget this run: %d credit(s), set by %s" % (budget, why))
        if budget <= 0:
            log("nothing to spend this week -- nothing revealed")
            db.close(); return 0
    over = args.score_over if args.score_over is not None else block["score_over"]
    above = "" if over is None else " scoring over %g" % over
    rows = candidates(db, args.unnamed, args.limit, block["stale_days"], args.recheck, over, block["by_name"],
                      block["reveal_countries"], block["site_read"], block["named_for"])
    if args.lead:
        rows = [r for r in rows if any(x.lower() in (r[1] or "").lower() for x in args.lead)]
    named = "" if args.unnamed or not block["named_for"] else " and ".join(block["named_for"])
    read = " whose own site has been read" if block["site_read"] else ""
    if not rows:
        log("nothing to enrich -- every open lead%s%s here already has %s%s, or Apollo was asked about it"
            " in the last %d days" % (above, read, "a named person" if args.unnamed else "an address",
                                      " (%s: a named person)" % named if named else "", block["stale_days"]))
        db.close(); return 0

    log("apollo enrichment -- %s | %d lead(s)%s%s%s | budget %d credit(s)%s"
        % (SEGMENT, len(rows), above, read,
           " without a name on the inbox" if args.unnamed else
           " with nothing to write to" + (" (%s: nobody named)" % named if named else ""),
           budget, "  [DRY RUN: nothing is revealed]" if args.dry_run else ""))
    log("  roles: %s" % ("by each lead's audience (audiences[].contact_roles)"
                         if any(a.get("contact_roles") for a in cfg.get("audiences") or [])
                         else ", ".join(roles) if roles else "(any senior title)"))
    if block["reveal_countries"]:
        log("  revealed only for leads based in: %s" % ", ".join(block["reveal_countries"]))
    if left is not None:
        log("  credits left before this run: %s\n" % left)

    spent = 0.0
    stats = {"written": 0, "named": 0, "no_email": 0, "unknown": 0, "elsewhere": 0, "error": 0, "left": 0,
             "websites": 0, "no_company": 0, "held_country": 0, "other_employer": 0, "known_elsewhere": 0}
    for done, (eid, name, domain, status, score, kind, org_id, country) in enumerate(rows):
        if stop_after:                               # the last reveal's ledger row failed (a stated budget)
            break
        if block["reveal_countries"] and (country or "").strip() not in country_forms(block["reveal_countries"]):
            stats["held_country"] += 1
            continue                                 # not stamped: asked about if the list ever widens
        lead_roles = roles_for(cfg, kind)
        if not args.dry_run and spent + 1 > budget:
            stats["left"] = len(rows) - done
            log("\n  budget reached -- %d lead(s) left for the next run" % stats["left"])
            break
        looked_up, also = False, None          # looked up by name this time; Apollo's other website for it
        if not domain:
            # no website: find the company in Apollo by its name first (a company search page, 1 credit)
            if args.dry_run:
                log("  %-34s %-16s no website: would look %r up by name (1 credit)"
                    % (name[:34], status, name_key(name)))
                continue
            looked_up = True
            try:
                org, why = find_company(name)
                spent += 1
                if not ledger(db, "company_lookup", 1, "lead %s" % eid) and capped:
                    log("\n  the ledger could not be written -- stopping, so the week's cap holds")
                    break
            except apollo.ApolloError as e:
                log("  %-34s company lookup failed: %s" % (name[:34], e))
                stats["error"] += 1
                if e.status in (401, 403):
                    db.close(); return 1
                continue
            if not org:
                log("  %-34s %-16s no website, and %s" % (name[:34], status, why))
                stats["no_company"] += 1
                stamp(db, eid, "no-company")
                continue
            domain = give_website(db, eid, org)
            if not domain:
                log("  %-34s %-16s Apollo's website for it, %s, is already another lead's -- left for a person"
                    % (name[:34], status, org.get("primary_domain")))
                stats["no_company"] += 1
                stamp(db, eid, "website-conflict")
                continue
            stats["websites"] += 1
            log("  %-34s %-16s website found: %s (Apollo: %s)" % (name[:34], status, domain, org.get("name")))
            if spent + 1 > budget:
                stats["left"] = len(rows) - done
                log("\n  budget reached -- %d lead(s) left for the next run" % stats["left"])
                break
        try:
            people, total = search(domain, lead_roles, block["verified_only"], org_id=org_id, senior=block["senior"])
        except apollo.ApolloError as e:
            if e.status in (401, 403):
                log("  %-34s %s" % (name[:34], e))
                db.close(); return 1
            if e.status == 429:
                wait = min(int(e.retry_after or 60), 120)
                log("  rate limit: waiting %ds" % wait)
                time.sleep(wait)
                try:
                    people, total = search(domain, lead_roles, block["verified_only"], org_id=org_id,
                                           senior=block["senior"])
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

        if not people and block["by_name"] and not looked_up:
            # Apollo may file the company under another website (Severin Films: severinfilms.com in
            # Apollo, severin-films.com on the lead). Its own record, found by the exact name, is searched.
            if args.dry_run:
                log("  %-34s %-16s nobody at %s: would look %r up by name (1 credit)"
                    % (name[:34], status, domain, name_key(name)))
                continue
            if spent + 1 > budget:
                stats["left"] = len(rows) - done
                log("\n  budget reached -- %d lead(s) left for the next run" % stats["left"])
                break
            try:
                org, _why = find_company(name)
                spent += 1
                if not ledger(db, "company_lookup", 1, "lead %s" % eid) and capped:
                    log("\n  the ledger could not be written -- stopping, so the week's cap holds")
                    break
            except apollo.ApolloError:
                org = None
            alt = store.norm_domain((org or {}).get("primary_domain"))
            if org and alt and alt != domain:
                try:
                    people, total = search(domain, lead_roles, block["verified_only"], org_id=org["id"],
                                           senior=block["senior"])
                except apollo.ApolloError:
                    people = []
                if people:
                    also = alt
                    log("  %-34s %-16s nobody at %s, but Apollo files it under %s"
                        % (name[:34], status, domain, alt))
        if not people:
            n = headcount(domain)
            log("  %-34s %-16s %s" % (name[:34], status,
                "Apollo knows nobody at %s" % domain if not n else
                "Apollo lists %d people at %s, none in a target role or senior with an address" % (n, domain)))
            stats["unknown"] += 1
            if not args.dry_run:
                stamp(db, eid, "none")
            continue
        if block["employer_check"] and not org_id:
            here = [p for p in people if works_at(p, name)]
            if not here:
                log("  %-34s %-16s the people Apollo lists at %s work somewhere else now -- nothing paid"
                    % (name[:34], status, domain))
                stats["other_employer"] += 1
                if not args.dry_run:
                    stamp(db, eid, "other-employer")
                continue
            people = here
        who, why = pick(people, lead_roles, strict=block["strict_roles"], senior_re=block["senior"])
        if not who:
            log("  %-34s %-16s nobody Apollo lists there is in a fitting role -- nothing paid" % (name[:34], status))
            stats["no_fit"] = stats.get("no_fit", 0) + 1
            if not args.dry_run:
                stamp(db, eid, "no-fit")
            continue
        shown = "%s %s -- %s" % (who.get("first_name") or "?", who.get("last_name_obfuscated") or "",
                                 who.get("title") or "no title")
        other = revealed_elsewhere(db, who.get("id"), eid) if block["skip_known_elsewhere"] else None
        if other:
            log("  %-34s %-16s %s was already revealed for %s -- not paid for again"
                % (name[:34], status, shown, other))
            stats["known_elsewhere"] += 1
            if not args.dry_run:
                stamp(db, eid, "known-elsewhere")
            continue
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
        if not ledger(db, "reveal", rep.get("credits") or 0, "lead %s" % eid) and capped:
            log("\n  the ledger could not be written -- stopping, so the week's cap holds")
            stop_after = True
        person = (rep.get("people") or [None])[0]
        if not person:
            log("  %-34s %-16s Apollo had nothing more on %s" % (name[:34], status, shown))
            stats["unknown"] += 1
            stamp(db, eid, "none")
            continue
        if not same_company(person, domain, also):
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
        what, rescored = stamp(db, eid, "written", person=person, credits=rep.get("credits") or 0, via=also)
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
    if stats["websites"] or stats["no_company"]:
        log("  websites found by name  : %d  (not found or not certain: %d)" % (stats["websites"], stats["no_company"]))
    log("  no address on file      : %d" % stats["no_email"])
    log("  Apollo knows nobody     : %d" % stats["unknown"])
    log("  had moved on            : %d" % stats["elsewhere"])
    if stats.get("no_fit"):
        log("  nobody in a fitting role: %d  (not paid for)" % stats["no_fit"])
    if stats["other_employer"]:
        log("  others' employees only  : %d  (not paid for)" % stats["other_employer"])
    if stats["known_elsewhere"]:
        log("  revealed for another project already: %d  (not paid for)" % stats["known_elsewhere"])
    if stats["held_country"]:
        log("  held: based outside %s : %d" % ("/".join(block["reveal_countries"]), stats["held_country"]))
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
