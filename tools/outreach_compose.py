#!/usr/bin/env python3
"""outreach_compose.py -- an email a person writes, to the leads they picked.

The owner, 2026-09-27: "in the universal segment there should be a widget to send mail to them".
Universal leads come from an Apollo search, not a harvest, so no one template fits them all: the
person writes the email once, for the leads they picked, and the page shows it as each of them will
read it. Approving it is the same gate as everywhere else -- a person read this text and stands
behind it -- and it makes the same thing an approved draft is: one approved outbound row per
company, sent by the scheduler from the approver's own Gmail (outreach.send_from = "approver"),
inside that address's daily limit, signed with their name and title over the project's footer.

What an email may use: {{first_name}}, the first name of the person it goes to ("there" when none
is known, so "Hi {{first_name}}," still reads), and {{company}}, the company as a person writes it.
Anything else in double braces is refused before anything is written.

Every recipient passes the checks an approval makes (tools/outreach_policy.check_drafts): a usable
address, one first email per company and per inbox in the project, a company still open to
contact. A lead still in To review is shortlisted by being written to -- choosing to email it is
that decision. `plan(..., apply=False)` runs all of it and undoes it, so the page can say who will
be skipped and why before anyone approves.
"""
import re

FIELDS = ("first_name", "company")
MAX_RECIPIENTS = 100
TEMPLATE_KEY = "compose"
REVIEW_STATUSES = ("discovered", "enriched", "scored", "ready_for_review", "shortlisted")
PLACEHOLDER = re.compile(r"{{\s*(\w+)\s*}}")
UUID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)

# the best-ranked usable address at each company (contact_rank, sql/28), as the drafting step picks it
RECIPIENTS_SQL = """
select e.id, e.name, e.status, e.metadata, e.domain,
       c.id as contact_id, c.full_name, c.email, c.source, c.role_title
from entities e
left join lateral (
    select c.* from contacts c
    where c.entity_id = e.id and c.email is not null
      and contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) > -500
    order by contact_rank(c.full_name, c.email, c.role_title, c.email_status, e.domain) desc,
             c.created_at, c.id
    limit 1) c on true
where e.id = any(%s::uuid[]) and e.segment_id = (select id from segments where slug = %s)
"""
OPENER_SQL = """
select status from outreach
where entity_id = %s and direction = 'outbound' and coalesce(sequence_step, 0) = 0
  and status not in ('cancelled', 'failed')
order by created_at desc limit 1
"""


class Refused(ValueError):
    """The email itself cannot go (an unknown field, an empty subject): nothing is written."""
    code = 400


class NeedsProfile(Refused):
    """The person has no name and title yet, and the email is signed with them."""
    code = 409


def compose_on(cfg):
    """Does this project let a person write an email to leads they pick? (outreach.compose)"""
    return bool((cfg or {}).get("compose"))


def _get(row, key):
    return row[key] if isinstance(row, dict) else row[0]


def unknown_fields(*texts):
    return sorted({m for t in texts for m in PLACEHOLDER.findall(t or "") if m not in FIELDS})


def check_text(subject, body):
    """-> the reason the email as written cannot be approved, or None."""
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject:
        return "Write a subject."
    if "\n" in subject or "\r" in subject:
        return "The subject must be one line."
    if not body:
        return "Write the email."
    bad = unknown_fields(subject, body)
    if bad:
        return "%s is not a field an email can use. It can use {{first_name}} and {{company}}." % (
            ", ".join("{{%s}}" % b for b in bad))
    if "SET_ME" in subject + body:
        return "The email still says SET_ME."
    return None


def fields_for(row):
    """{first_name, company, named} for one recipient row (RECIPIENTS_SQL)."""
    import draft_render as dr
    import newsmatch
    company = newsmatch.display_name(row["name"] or "")
    first = dr.greeting_person(row["full_name"], row["email"], company, row["metadata"] or {}, row["source"])
    return {"first_name": first or "there", "company": company, "named": bool(first)}


def render(text, fields):
    """The text with its fields filled in; {{company}}'s reads "Angel Studios'" like the drafts do."""
    import draft_render as dr
    norm = PLACEHOLDER.sub(lambda m: "{{%s}}" % m.group(1), text or "")
    return dr.render(norm, {"first_name": fields["first_name"], "company": fields["company"]})


def message(subject, body, fields, footer):
    """-> (subject, body) as this recipient receives it, the footer under it."""
    return render(subject.strip(), fields), render(body.strip(), fields) + "\n\n" + footer


def plan(cur, segment, entity_ids, subject, body, person, cfg, apply=False):
    """-> {"ready": [...], "skipped": [...], "footer": str}.

    Runs every recipient through exactly what an approval checks. With apply=False (the page asking
    before approving) nothing is kept; with apply=True each recipient that passes becomes an approved
    email (approval_mode 'compose', approved by `person`) and its lead is shortlisted if it was not.
    Refused (nothing written) when the email itself cannot go."""
    import draft_render as dr
    import outreach_policy as pol
    if not isinstance(entity_ids, (list, tuple)):
        raise Refused("Pick at least one lead to write to.")
    ids = list(dict.fromkeys(str(i) for i in entity_ids if i))
    not_ids = [i for i in ids if not UUID_RE.match(i)]          # never a server error for a mangled request
    ids = [i for i in ids if UUID_RE.match(i)]
    if not ids:
        raise Refused("Pick at least one lead to write to.")
    if len(ids) > MAX_RECIPIENTS:
        raise Refused("One email goes to at most %d leads at a time; %d are picked." % (MAX_RECIPIENTS, len(ids)))
    if not (person and person.get("name") and person.get("title")):
        raise NeedsProfile("Add your name and title first (the account menu at the bottom of the sidebar): "
                           "the emails you write are signed with them.")
    subject, body = str(subject or ""), str(body or "")
    why = check_text(subject, body) if apply else (
        check_text("x", "%s %s" % (subject, body)) if unknown_fields(subject, body) else None)
    if why:
        raise Refused(why)
    footer = dr.footer_for(cfg, person["name"], person["title"])
    cur.execute(RECIPIENTS_SQL, (ids, segment))
    rows = {str(r["id"]): r for r in cur.fetchall()}
    ready, skipped = [], [{"id": i, "company": None, "reason": "not a lead of this project"} for i in not_ids]
    cur.execute("savepoint compose_all")
    try:
        for eid in ids:
            r = rows.get(eid)
            if not r:
                skipped.append({"id": eid, "company": None, "reason": "not a lead of this project"})
                continue
            base = {"id": eid, "company": r["name"]}
            if not r["email"]:
                skipped.append(dict(base, reason="no email address to write to"))
                continue
            if r["status"] not in REVIEW_STATUSES:
                skipped.append(dict(base, reason={"contacted": "already contacted", "in_conversation": "already in conversation"}
                                    .get(r["status"], "it was %s" % str(r["status"]).replace("_", " "))))
                continue
            cur.execute(OPENER_SQL, (eid,))
            got = cur.fetchone()
            if got:
                skipped.append(dict(base, reason="it already has an email from us (%s)" % _get(got, "status")))
                continue
            f = fields_for(r)
            cur.execute("savepoint compose_row")
            reason, oid = None, None
            try:
                subj, text = message(subject or "(subject)", body or "(email)", f, footer)
                if r["status"] != "shortlisted":
                    cur.execute("update entities set status = 'shortlisted', status_changed_at = now(), updated_at = now()"
                                " where id = %s and status = any(%s)", (eid, list(REVIEW_STATUSES)))
                cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body)"
                            " values (%s, %s, %s, %s, %s) on conflict do nothing returning id",
                            (eid, r["contact_id"], TEMPLATE_KEY, subj, text))
                got = cur.fetchone()
                if not got:
                    reason = "it already has an email from us"
                else:
                    oid = str(_get(got, "id"))
                    _ok, bad = pol.check_drafts(cur, [oid], segment)
                    if bad:
                        reason = bad[0]["reason"]
                    else:
                        cur.execute("update outreach set status = 'approved', approved_at = now(), approved_by = %s,"
                                    " approval_mode = 'compose', spot_checked = true, updated_at = now()"
                                    " where id = %s and status = 'drafted'", (person["email"], oid))
            except Exception as e:                     # noqa: BLE001 -- one recipient, reported, not the rest
                reason = "could not be written (%s)" % str(e).splitlines()[0][:120]
            if reason:
                cur.execute("rollback to savepoint compose_row")
                skipped.append(dict(base, reason=reason))
                continue
            cur.execute("release savepoint compose_row")
            ready.append(dict(base, contact_name=r["full_name"], email=r["email"], role=r["role_title"],
                              first_name=f["first_name"], named=f["named"], company_as_written=f["company"],
                              outreach_id=oid if apply else None))
    finally:
        if not apply:
            cur.execute("rollback to savepoint compose_all")        # asking changes nothing
        cur.execute("release savepoint compose_all")
    return {"ready": ready, "skipped": skipped, "footer": footer}
