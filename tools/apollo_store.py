#!/usr/bin/env python3
"""apollo_store.py -- people and companies from Apollo, saved as leads of the Universal project.

The same shape as every other project: a company is an entity, a person is a
contact of it. What Apollo said about each is kept on the entity, so a lead
can always show where it came from:

  metadata.apollo          the company, as Apollo describes it (tools/apollo.org_row)
  metadata.apollo_people   {apollo person id: the person as revealed}, one per person saved
  metadata.saved_from      which search found it, when, and who saved it
  metadata.industry / employees / hq_city / hq_state / hq_country
                           the fields the board and list show

RULES, each one an invariant the other projects already keep:
  * TVF and its affiliates never become leads (config self_exclusion).
  * A rejected or archived company is never brought back. Rejections are the
    shield that stops a company someone already refused from resurfacing.
  * Nothing is overwritten with less: a company search that knows only the name
    and website does not erase the industry a person reveal brought in.
  * Apollo's "email_not_unlocked@domain.com" placeholder is never stored
    (tools/apollo.person_record drops it).
  * A person Apollo reveals without an email is still kept -- by name, title
    and LinkedIn URL -- because that is a way in; the lead shows no address.
"""
import datetime as dt
import json
import re

SHIELDED = ("rejected", "archived")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def norm_domain(v):
    s = str(v or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s).split("/")[0].split("?")[0].split("@")[-1].split(":")[0]
    s = re.sub(r"^www\.", "", s).strip(".")
    return s if "." in s else None


def excluded(org, rule):
    """The self-exclusion rule of the segment config: domains match the host or a subdomain,
    name patterns match as whole words. -> the reason, or None."""
    rule = rule or {}
    dom = norm_domain(org.get("primary_domain") or org.get("website_url"))
    for d in rule.get("domains") or []:
        d = d.lower()
        if dom and (dom == d or dom.endswith("." + d)):
            return "it is TVF (%s)" % d
    name = " ".join(str(org.get("name") or "").lower().split())
    for p in rule.get("name_patterns") or []:
        if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(p.lower()), name):
            return "it is TVF (%s)" % p
    return None


def _merge(old, new):
    """New values win, but an empty new value never erases an old one; dicts merge one level down."""
    out = dict(old or {})
    for k, v in (new or {}).items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def company_fields(org):
    return {"apollo": org, "industry": org.get("industry"), "employees": org.get("estimated_num_employees"),
            "hq_city": org.get("city"), "hq_state": org.get("state"), "hq_country": org.get("country")}


def find_company(cur, seg_id, org):
    """The entity already holding this company: by Apollo ID, then domain, then (no domain) name."""
    dom = norm_domain(org.get("primary_domain") or org.get("website_url"))
    if org.get("id"):
        cur.execute("select id, status, domain, metadata from entities where segment_id = %s"
                    " and metadata->'apollo'->>'id' = %s limit 1", (seg_id, org["id"]))
        row = cur.fetchone()
        if row:
            return row
    if dom:
        cur.execute("select id, status, domain, metadata from entities where segment_id = %s and domain = %s",
                    (seg_id, dom))
        row = cur.fetchone()
        if row:
            return row
    if org.get("name"):
        cur.execute("select id, status, domain, metadata from entities where segment_id = %s"
                    " and domain is null and lower(name) = lower(%s) limit 1", (seg_id, org["name"].strip()))
        return cur.fetchone()
    return None


def _row(r, key):
    return r[key] if isinstance(r, dict) else r[("id", "status", "domain", "metadata").index(key)]


def upsert_company(cur, seg_id, org, saved_from=None):
    """-> (entity_id, "created" | "updated" | "shielded:<status>")."""
    name = " ".join(str(org.get("name") or "").split())
    if not name:
        raise ValueError("a company needs a name")
    dom = norm_domain(org.get("primary_domain") or org.get("website_url"))
    row = find_company(cur, seg_id, org)
    fields = {k: v for k, v in company_fields(org).items() if v not in (None, "", [], {})}
    if row:
        eid, status = _row(row, "id"), _row(row, "status")
        if status in SHIELDED:
            return str(eid), "shielded:%s" % status
        meta = _merge(_row(row, "metadata") or {}, fields)
        if saved_from and not meta.get("saved_from"):
            meta["saved_from"] = saved_from
        new_domain = _row(row, "domain")
        if not new_domain and dom:
            cur.execute("select 1 from entities where segment_id = %s and domain = %s", (seg_id, dom))
            if not cur.fetchone():
                new_domain = dom            # a website learned later; never one another lead holds
        cur.execute("update entities set metadata = %s::jsonb, domain = %s, updated_at = now() where id = %s",
                    (json.dumps(meta), new_domain, eid))
        return str(eid), "updated"
    meta = dict(fields)
    if saved_from:
        meta["saved_from"] = saved_from
    cur.execute(
        "insert into entities (segment_id, name, domain, source, source_url, metadata, status, status_changed_at)"
        " values (%s, %s, %s, 'apollo', %s, %s::jsonb, 'ready_for_review', now()) returning id",
        (seg_id, name, dom, org.get("linkedin_url") or org.get("website_url"), json.dumps(meta)))
    got = cur.fetchone()
    return str(got["id"] if isinstance(got, dict) else got[0]), "created"


def upsert_person(cur, entity_id, person):
    """The person as a contact of the company, and on the entity's apollo_people.
    -> "added" | "updated" """
    pid = person.get("apollo_id")
    info = {k: person.get(k) for k in ("name", "title", "headline", "seniority", "departments", "linkedin_url",
                                       "city", "state", "country", "apollo_email_status") if person.get(k)}
    info["has_email"] = bool(person.get("email"))
    info["saved_at"] = now_iso()
    cur.execute(
        "update entities set metadata = jsonb_set(metadata, '{apollo_people}',"
        " case when jsonb_typeof(metadata->'apollo_people') = 'object' then metadata->'apollo_people'"
        " else '{}'::jsonb end || jsonb_build_object(%s::text, %s::jsonb)), updated_at = now() where id = %s",
        (pid, json.dumps(info), entity_id))
    name = person.get("name") or None
    title = person.get("title") or None
    email = person.get("email")
    note = "apollo:%s" % pid
    if email:
        cur.execute("select id from contacts where entity_id = %s and lower(email) = lower(%s)", (entity_id, email))
        got = cur.fetchone()
        if got:
            cur.execute(
                "update contacts set full_name = coalesce(full_name, %s), role_title = coalesce(%s, role_title),"
                " linkedin_url = coalesce(%s, linkedin_url),"
                " email_status = case when email_status = 'invalid' then email_status else %s end,"
                " verifier = 'apollo', updated_at = now() where id = %s",
                (name, title, person.get("linkedin_url"), person.get("email_status") or "unverified",
                 got["id"] if isinstance(got, dict) else got[0]))
            return "updated"
        cur.execute(
            "insert into contacts (entity_id, full_name, role_title, linkedin_url, email, email_status,"
            " email_verified_at, verifier, source, notes)"
            " values (%s, %s, %s, %s, %s, %s, case when %s = 'valid' then now() end, 'apollo', 'apollo', %s)",
            (entity_id, name, title, person.get("linkedin_url"), email, person.get("email_status") or "unverified",
             person.get("email_status") or "unverified", note))
        return "added"
    # no address: kept by name, once
    cur.execute("select id from contacts where entity_id = %s and email is null and"
                " (notes = %s or (full_name is not null and lower(full_name) = lower(%s)))",
                (entity_id, note, name or ""))
    got = cur.fetchone()
    if got:
        cur.execute("update contacts set role_title = coalesce(%s, role_title), linkedin_url = coalesce(%s, linkedin_url),"
                    " updated_at = now() where id = %s",
                    (title, person.get("linkedin_url"), got["id"] if isinstance(got, dict) else got[0]))
        return "updated"
    cur.execute("insert into contacts (entity_id, full_name, role_title, linkedin_url, email, email_status, source, notes)"
                " values (%s, %s, %s, %s, null, 'unknown', 'apollo', %s)",
                (entity_id, name, title, person.get("linkedin_url"), note))
    return "added"


def saved_person_ids(cur, seg_id, ids):
    ids = [str(i) for i in ids or []]
    if not ids:
        return set()
    cur.execute("select k from entities e, jsonb_object_keys(case when jsonb_typeof(e.metadata->'apollo_people')"
                " = 'object' then e.metadata->'apollo_people' else '{}'::jsonb end) k"
                " where e.segment_id = %s and k = any(%s)", (seg_id, ids))
    return {(r["k"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def saved_company_ids(cur, seg_id, ids):
    ids = [str(i) for i in ids or []]
    if not ids:
        return {}
    cur.execute("select metadata->'apollo'->>'id' as aid, status from entities where segment_id = %s"
                " and metadata->'apollo'->>'id' = any(%s)", (seg_id, ids))
    return {(r["aid"] if isinstance(r, dict) else r[0]): (r["status"] if isinstance(r, dict) else r[1])
            for r in cur.fetchall()}


def _each(cur, rep, name, fn):
    """One row in its own savepoint: a row that fails is reported and the rest are still saved.
    A reveal has already been paid for, so one bad row must not throw away the other nine."""
    cur.execute("savepoint apollo_row")
    try:
        out = fn()
        cur.execute("release savepoint apollo_row")
        return out
    except Exception as e:                                   # noqa: BLE001 -- reported, not hidden
        cur.execute("rollback to savepoint apollo_row")
        rep["skipped"].append({"name": name, "why": "could not be saved (%s)" % str(e).splitlines()[0][:120]})
        return None


def save_people(cur, seg_id, people, rule=None, saved_from=None):
    """Revealed people (tools/apollo.person_record) -> leads. -> a report the page can show."""
    rep = {"saved": 0, "with_email": 0, "companies_created": 0, "companies_updated": 0, "skipped": [],
           "saved_ids": []}
    touched = set()
    for p in people:
        org = dict(p.get("organization") or {})
        if not org.get("name"):
            rep["skipped"].append({"name": p.get("name"), "why": "Apollo gave no employer"})
            continue
        why = excluded(org, rule)
        if why:
            rep["skipped"].append({"name": p.get("name"), "why": why})
            continue

        def one(p=p, org=org):
            eid, what = upsert_company(cur, seg_id, org, saved_from)
            if what.startswith("shielded"):
                return eid, what
            upsert_person(cur, eid, p)
            return eid, what
        got = _each(cur, rep, p.get("name"), one)
        if not got:
            continue
        eid, what = got
        if what.startswith("shielded"):
            rep["skipped"].append({"name": p.get("name"), "why": "%s was %s earlier" % (org["name"], what.split(":")[1])})
            continue
        if eid not in touched:
            touched.add(eid)
            rep["companies_created" if what == "created" else "companies_updated"] += 1
        rep["saved"] += 1
        rep["saved_ids"].append(p.get("apollo_id"))
        rep["with_email"] += 1 if p.get("email") else 0
    return rep


def save_companies(cur, seg_id, orgs, rule=None, saved_from=None):
    rep = {"saved": 0, "companies_created": 0, "companies_updated": 0, "skipped": [], "saved_ids": []}
    for org in orgs:
        why = excluded(org, rule)
        if why:
            rep["skipped"].append({"name": org.get("name"), "why": why})
            continue
        got = _each(cur, rep, org.get("name"), lambda org=org: upsert_company(cur, seg_id, org, saved_from))
        if not got:
            continue
        eid, what = got
        if what.startswith("shielded"):
            rep["skipped"].append({"name": org.get("name"), "why": "it was %s earlier" % what.split(":")[1]})
            continue
        rep["saved"] += 1
        rep["saved_ids"].append(org.get("id"))
        rep["companies_created" if what == "created" else "companies_updated"] += 1
    return rep
