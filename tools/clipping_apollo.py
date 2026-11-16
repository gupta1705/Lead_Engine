"""Add verified Apollo contacts to qualified Clipping leads; never change a recipient.

The pause guard runs before even a free Apollo call. Paid reveals reserve one credit
in a short locked transaction; network requests never run inside retriable Db.run.
"""
import datetime as dt
import json
import math
import re
import urllib.parse

import apollo
import apollo_budget
import apollo_store
from lead_lifecycle import PROTECTED, priority_order

SEGMENT = "lcx-clipping"
OPEN = ("ready_for_review", "shortlisted")
FREE = {"gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "icloud.com", "aol.com", "proton.me", "protonmail.com", "live.com", "me.com"}
PLATFORMS = FREE | {"youtube.com", "youtu.be", "spotify.com", "apple.com", "podcasts.apple.com",
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "linktr.ee", "beacons.ai", "substack.com", "patreon.com", "gumroad.com", "myshopify.com",
    "teachable.com", "thinkific.com", "kajabi.com", "podia.com", "wordpress.com", "wixsite.com"}
THIRD_PARTY = re.compile(r"\b(sponsor(?:ed)?|affiliate|guest|partner offer|recommended)\b", re.I)
IDENTITY_WORDS = re.compile(r"\b(?:my|our|official)\s+(?:business\s+)?(?:website|site|home\s?page)\b", re.I)
URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
PERSON_ID = re.compile(r"^[0-9a-f]{24}$")


def now():
    return dt.datetime.now(dt.timezone.utc)


def number(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) and not isinstance(value, bool) else default
    except (TypeError, ValueError):
        return default


def spending_allowed(cfg):
    b = (cfg or {}).get("clipping_apollo") or {}
    return (b.get("enabled") is True and number(b.get("credits_per_run"), 0) >= 1
            and number(b.get("credits_per_week"), 0) >= 1
            and number(b.get("max_contacts_per_lead"), 1) >= 1)


def stamp_date(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def normal_name(value):
    words = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    return " ".join(w for w in words if w not in {"inc", "incorporated", "llc", "ltd", "limited", "pvt", "private"})


def domain(value):
    value = str(value or "").strip()
    try:
        parsed = urllib.parse.urlparse(value if "://" in value else "https://" + value)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return None
        host = (parsed.hostname or "").lower().removeprefix("www.")
        return host if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host) else None
    except ValueError:
        return None


def near_domain(a, b):
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def owned_domain(value, cfg):
    host = domain(value)
    blocked = PLATFORMS | set(cfg.get("hosting_providers") or [])
    return host if host and not any(near_domain(host, d) for d in blocked) else None


def business_match(lead, cfg):
    """Only first-party identity fields; never episode guests or an arbitrary description URL."""
    meta = lead.get("metadata") or {}
    pf, yc, net = [meta.get(k) or {} for k in ("podcast_feed", "youtube_channel", "network")]
    candidates = []
    if pf.get("website"):
        candidates.append((pf["website"], [pf.get("author"), pf.get("owner_name")],
                           pf.get("feed_url"), "Website and publisher named in the show's feed"))
    if meta.get("kind") == "network" and net.get("website"):
        candidates.append((net["website"], [lead.get("name")], net["website"],
                           "Publisher website shared by its shows"))
    if meta.get("kind") == "production_house" and meta.get("wikidata") and lead.get("domain"):
        candidates.append((lead["domain"], [lead.get("name")], lead.get("source_url"),
                           "Production business from its structured company record"))
    for line in re.split(r"[\r\n]+", yc.get("description") or ""):
        if IDENTITY_WORDS.search(line) and not THIRD_PARTY.search(line):
            for url in URL.findall(line):
                if near_domain(domain(url), domain(yc.get("website"))):
                    candidates.append((url, [yc.get("title")], yc.get("url"),
                                       "Channel explicitly labels this as its own website"))
    for website, names, source, reason in candidates:
        host = owned_domain(website, cfg)
        if not host or not apollo.web_url(source):
            continue
        if lead.get("domain") and not near_domain(host, domain(lead["domain"])):
            continue
        names = list(dict.fromkeys(str(n).strip() for n in names if len(normal_name(n)) >= 4))
        names = [n for n in names if normal_name(n) not in {"unknown", "various", "podcast", "podcasts", "anonymous"}]
        if names:
            return {"domain": host, "business_name": names[0], "names": names,
                    "source_url": source, "reason": reason}
    return None


def roles_for(lead, cfg):
    group = "business" if (lead.get("metadata") or {}).get("kind") in {"network", "production_house"} else "creator"
    return ((cfg.get("clipping_apollo") or {}).get("roles") or {}).get(group) or []


def role_allowed(title, roles):
    # A general "Manager" does not also mean Sales Manager or Product Manager.
    parts = re.split(r"\s+(?:and|at)\s+|[&,/|]", str(title or ""), flags=re.I)
    wanted = {normal_name(r) for r in roles}
    return any(normal_name(p) in wanted for p in parts)


def eligibility_reason(lead, cfg, at=None, check_recent=True):
    at = at or now()
    b = cfg.get("clipping_apollo") or {}
    if lead.get("status") not in OPEN:
        return "lead-not-open"
    if lead.get("protected") or lead.get("suppressed"):
        return "protected-or-suppressed"
    if lead.get("has_verified_contact"):
        return "already-verified"
    if number(lead.get("fit_score"), 0) <= number(b.get("score_over"), 45):
        return "below-score"
    created = stamp_date(lead.get("created_at"))
    if not created or not 0 <= (at-created).total_seconds() < number(b.get("max_lead_age_days"), 14)*86400:
        return "stale-lead"
    meta = lead.get("metadata") or {}
    checked = stamp_date((meta.get("clipping_apollo") or {}).get("checked_at"))
    if check_recent and checked and (at-checked).total_seconds() < number(b.get("recheck_after_days"), 30)*86400:
        return "recently-checked"
    si = meta.get("scoring_inputs") or {}
    for gate in cfg.get("gates") or []:
        path = gate.get("input", "")
        if path.startswith("metadata.scoring_inputs."):
            value = si.get(path.rsplit(".", 1)[1])
            expected = gate.get("exclude_when")
            if value is not None and (value == expected or str(value).lower() == str(expected).lower()):
                return "qualification-gate"
    return None


def preview_choice(people, match, roles):
    names = {normal_name(n) for n in match["names"]}
    for person in people:
        if (PERSON_ID.fullmatch(str(person.get("id") or "")) and person.get("has_email")
                and normal_name(person.get("company")) in names and role_allowed(person.get("title"), roles)):
            if person.get("company_domain") and not near_domain(domain(person["company_domain"]), match["domain"]):
                continue
            return person
    return None


def revealed_reason(person, preview, match, roles, cfg):
    import apollo_policy
    from contacts import junk_reason
    if not person or person.get("apollo_id") != preview.get("id"):
        return "person-mismatch"
    if not apollo_policy.verified(person) or not person.get("name"):
        return "unverified-email"
    email = str(person.get("email") or "").strip().lower()
    email_domain = domain(email.split("@")[-1]) if "@" in email else None
    if junk_reason(email) or not owned_domain(email_domain, cfg) or not near_domain(email_domain, match["domain"]):
        return "not-business-email"
    org = person.get("organization") or {}
    if not near_domain(domain(org.get("primary_domain") or org.get("website_url")), match["domain"]):
        return "current-employer-mismatch"
    if preview.get("company_id") and org.get("id") != preview["company_id"]:
        return "current-employer-mismatch"
    if normal_name(org.get("name")) not in {normal_name(n) for n in match["names"]}:
        return "current-employer-mismatch"
    if not role_allowed(person.get("title"), roles):
        return "irrelevant-role"
    banned = set((cfg.get("geography") or {}).get("disallowed_countries") or [])
    if any(apollo_policy.iso(c) in banned for c in (person.get("country"), org.get("country"))):
        return "excluded-country"
    return None


class Repository:
    def __init__(self, db):
        self.db = db

    def config(self):
        return self.db.run(lambda c: (c.execute("select config from segments where slug=%s", (SEGMENT,)), c.fetchone()[0])[1])

    @staticmethod
    def lead(cur, eid, lock=False):
        if lock:
            cur.execute("select id from entities where id=%s for update", (eid,))
        cur.execute("select row_to_json(e), (" + PROTECTED + ") as protected,"
            " do_not_contact(null,e.id) is not null as suppressed, exists(select 1 from contacts c where"
            " c.entity_id=e.id and c.source='apollo' and c.verifier='apollo' and c.email_status='valid')"
            " from entities e where e.id=%s", (eid,))
        row = cur.fetchone()
        return dict(row[0], protected=row[1], suppressed=row[2], has_verified_contact=row[3]) if row else None

    def candidates(self, cfg, limit):
        cutoff = (now() - dt.timedelta(days=number(cfg["clipping_apollo"].get("recheck_after_days"), 30))).isoformat()
        def read(cur):
            cur.execute("select e.id from entities e join segments s on s.id=e.segment_id where s.slug=%s"
                " and e.status=any(%s) and not (" + PROTECTED + ")"
                " and do_not_contact(null,e.id) is null and e.created_at > now() - %s * interval '1 day'"
                " and coalesce(e.metadata#>>'{clipping_apollo,checked_at}','') < %s"
                " and not exists(select 1 from contacts c where c.entity_id=e.id and c.source='apollo'"
                " and c.verifier='apollo' and c.email_status='valid')"
                " and coalesce(e.fit_score,0)>%s order by " + priority_order() + " limit %s",
                (SEGMENT, list(OPEN), cfg["clipping_apollo"]["max_lead_age_days"], cutoff, cfg["clipping_apollo"]["score_over"], limit))
            ids = [r[0] for r in cur.fetchall()]
            return [self.lead(cur, eid) for eid in ids]
        return self.db.run(read)

    def reserve(self, lead, preview, balance, attempted):
        if number(balance) is None:
            return None
        ref = "clipping-apollo:%s:%s" % (lead["id"], preview["id"])
        def write(cur):
            cur.execute("select id,config from segments where slug=%s for update", (SEGMENT,))
            sid, cfg = cur.fetchone()
            if not spending_allowed(cfg):
                return None
            fresh = self.lead(cur, lead["id"], lock=True)
            if not fresh or eligibility_reason(fresh, cfg):
                return None
            # Revalidate identity if a reviewer or another enrichment changed it during preview.
            match = business_match(fresh, cfg)
            if not match or not preview_choice([preview], match, roles_for(fresh, cfg)):
                return None
            cur.execute("select id from apollo_spend where segment_id=%s and ref=%s", (sid, ref))
            if cur.fetchone():  # includes an uncertain prior request: never buy it again automatically
                return None
            cur.execute("select 1 from entities where metadata->'apollo_people' ? %s or"
                        " metadata->'apollo_enrich'->>'person'=%s limit 1", (preview["id"], preview["id"]))
            if cur.fetchone():
                return None
            block = cfg["clipping_apollo"]
            allowed, _ = apollo_budget.allowance(cur, SEGMENT, block, balance,
                                                number(block["credits_per_run"], 0)-attempted)
            if allowed < 1:
                return None
            cur.execute("insert into apollo_spend(segment_id,kind,credits,ref) values(%s,'reveal',1,%s) returning id", (sid, ref))
            return cur.fetchone()[0]
        return self.db.run(write)

    def settle(self, reservation, credits):
        self.db.run(lambda c: c.execute("update apollo_spend set credits=%s where id=%s and ref like 'clipping-apollo:%%'", (credits, reservation)))

    def save(self, lead, outcome, match=None, person=None, preview=None):
        def write(cur):
            fresh = self.lead(cur, lead["id"], lock=True)
            cur.execute("select config from segments where slug=%s", (SEGMENT,))
            cfg = cur.fetchone()[0]
            if not fresh or eligibility_reason(fresh, cfg, check_recent=False):
                return "protected"
            stamp = {"outcome": outcome, "checked_at": now().isoformat()}
            if match:
                stamp["match"] = {k: v for k, v in match.items() if k != "names"}
            if person:
                current_match = business_match(fresh, cfg)
                if not current_match or current_match["domain"] != match["domain"] or revealed_reason(person, preview, current_match, roles_for(fresh, cfg), cfg):
                    return "identity-changed"
                cur.execute("select do_not_contact(%s,%s)", (person["email"], fresh["id"]))
                if cur.fetchone()[0]:
                    return "suppressed"
                cur.execute("select id from contacts where entity_id=%s and lower(email)=lower(%s)", (fresh["id"], person["email"]))
                if cur.fetchone():
                    stamp["outcome"] = "existing-contact-preserved"
                else:
                    apollo_store.upsert_person(cur, fresh["id"], person)
                    cur.execute("select id from contacts where entity_id=%s and lower(email)=lower(%s)", (fresh["id"], person["email"]))
                    stamp["contact_id"] = str(cur.fetchone()[0])
                    stamp["person_id"] = person["apollo_id"]
            cur.execute("update entities set metadata=jsonb_set(coalesce(metadata,'{}'::jsonb),'{clipping_apollo}',%s::jsonb),"
                        " updated_at=now() where id=%s", (json.dumps(stamp), fresh["id"]))
            return stamp["outcome"]
        return self.db.run(write)


def run(repo, api=apollo, limit=100):
    cfg = repo.config()
    stats = {"paused": not spending_allowed(cfg), "searched": 0, "reveals": 0, "added": 0, "credits_reserved": 0}
    if stats["paused"]:
        return stats
    # The injected API makes the no-call pause guarantee directly testable.
    if not api.key_is_set():
        return dict(stats, stopped="Apollo key is not configured")
    balance = number(api.credits().get("lead_credits_left"))
    if balance is None:
        return dict(stats, stopped="Apollo did not report its balance")
    attempted = 0
    for lead in repo.candidates(cfg, limit):
        cfg = repo.config()
        if not spending_allowed(cfg) or attempted >= number(cfg["clipping_apollo"]["credits_per_run"], 0):
            break
        if eligibility_reason(lead, cfg):
            continue
        match, roles = business_match(lead, cfg), roles_for(lead, cfg)
        if not match or not roles:
            repo.save(lead, "identity-unconfirmed")
            continue
        filters = {"q_organization_domains_list": [match["domain"]], "person_titles": roles,
                   "contact_email_status": ["verified"], "include_similar_titles": False}
        results = api.search_people(filters, 1, 10)
        stats["searched"] += 1
        preview = preview_choice(results.get("people") or [], match, roles)
        if not preview:
            repo.save(lead, "no-confident-match", match)
            continue
        # Re-read balance immediately before the reservation; no unknown balances may spend.
        balance = number(api.credits().get("lead_credits_left"))
        if balance is None:
            return dict(stats, stopped="Apollo did not report its balance")
        reservation = repo.reserve(lead, preview, balance, attempted)
        if reservation is None:
            continue
        attempted += 1
        stats["reveals"] += 1
        stats["credits_reserved"] += 1
        try:
            reply = api.reveal_people([preview["id"]])
        except Exception:
            # The request may have reached Apollo. Keep the reservation and stop, never retry it.
            return dict(stats, stopped="Reveal failed; credit reservation retained")
        people = reply.get("people") or []
        # The shared wrapper normalises an omitted credits field to zero. A returned person
        # still conservatively consumes one reserved credit, even without a usable email.
        cost = 0 if not people and preview["id"] in (reply.get("missing") or []) and not reply.get("error") else 1
        if number(reply.get("credits"), 0) > 0:
            cost = 1
        repo.settle(reservation, cost)
        person = people[0] if len(people) == 1 else None
        reason = revealed_reason(person, preview, match, roles, cfg)
        result = repo.save(lead, reason or "added", match, None if reason else person, preview)
        if result == "added":
            stats["added"] += 1
    return stats


def main():
    import argparse
    from dbconn import Db
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    db = Db()
    try:
        print(json.dumps(run(Repository(db), limit=args.limit)))
    finally:
        db.close()


if __name__ == "__main__":
    main()
