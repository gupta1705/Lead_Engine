#!/usr/bin/env python3
"""outreach_policy.py -- follow-up sequences and batch approval.

The owner approved both on 2026-09-10 for sales segments. A segment turns
them on in its config (outreach.follow_ups, outreach.batch_approval); a
segment that says nothing keeps the original rules: one email per company,
a person reads and approves every draft. TVF says nothing.

Every function takes a cursor and never commits, so the same code serves the
command line (tools/outreach.py), the web API (app/main.py) and the test
(tools/test_outreach_policy.py, which runs inside a transaction it rolls back).

FOLLOW-UPS
  An opener that was sent, to a company still 'contacted', gets follow-up
  step k once step k-1 has been sent at least `after_days` ago, when:
    * the company has not replied (an auto-reply triaged 'neutral' does not
      count; an untriaged reply does, until someone looks at it),
    * nothing is pending or wedged in the thread (a draft, an approved row,
      an unknown send outcome, a failure, a parked send error),
    * the thread has not been stopped (a person pressed Stop, cancelled a
      follow-up, or marked a reply positive or negative),
    * the contact's address did not fail verification,
    * the segment's sequence has a step k.
  Follow-ups are DRAFTS. They go through approval like any other email.
  The database refuses to send one after a reply (sql/23 trigger).

BATCH APPROVAL
  A person selects drafts; the server draws a random spot-check sample
  (at least sample_min, or sample_fraction of the batch, whichever is more)
  and signs the batch and the sample together. Approval requires that
  signature, so the sample cannot be hand-picked or swapped. Every draft is
  checked before it is approved (no unfilled {{placeholders}}, no SET_ME, a
  valid address, a company still in a sendable state); failures are skipped
  and reported. Every approved row records who approved it, when, how, and
  whether it was in the sample.

MAILBOXES
  A segment may send from several mailboxes (outreach.mailboxes). Openers go
  to the connected mailbox with the most room left today; a follow-up always
  leaves from the mailbox that sent its opener (the database enforces this,
  sql/24). Each mailbox has a daily cap and an optional warm-up ramp that
  starts counting on its first sending day. A segment without `mailboxes`
  has one implicit mailbox, the original single sender, so TVF is unchanged.
  Bounces (mailer-daemon replies) mark the address invalid and end the thread.

THE SENDING WINDOW (owner, 2026-10-12: "send mails to the sender's time region between 10 to 10:30AM
and that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13")
  A project with outreach.send_window gives every approved email its own second inside 10:00-10:30 in
  its recipient's zone (tools/send_window.py says where and when), drawn when it is approved, on every
  approval path, and stored on the row (sql/34), so the Approved list says when each one goes. One
  function places them all (place_send): never two from one address closer than the gap, never more
  in a window than its addresses hold, never more on a UTC day than their daily limits. A window that
  passes unsent moves the email to the next window at a new random second (settle_schedule), never to
  a late afternoon. A project without the block keeps no times and sends as it always did.
"""
import datetime as dt
import hashlib
import hmac
import json
import math
import random
import re
import secrets
import time
import uuid

from recipient_selection import ELIGIBLE_CONTACT_SQL, PREFERENCE_MATCH_SQL

PLACEHOLDER_RE = re.compile(r"{{\w+}}")
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
PENDING = ("drafted", "approved", "sending")
WEDGED = ("send_unknown", "failed")
MAX_STEPS = 3                                   # mirrors the CHECK in sql/23


# ------------------------------------------------------------------ config
def followup_steps(outreach_cfg):
    """The segment's follow-up steps, validated, or [] when off."""
    f = (outreach_cfg or {}).get("follow_ups") or {}
    if not f.get("enabled"):
        return []
    steps = sorted(f.get("steps") or [], key=lambda s: int(s.get("step", 0)))
    keys = {t["key"] for t in (outreach_cfg or {}).get("templates") or []}
    for i, s in enumerate(steps, 1):
        if int(s.get("step", 0)) != i:
            raise ValueError("follow_ups.steps must be numbered 1..n without gaps")
        if int(s.get("after_days", 0)) < 1:
            raise ValueError("follow_ups step %d: after_days must be at least 1" % i)
        if s.get("template") not in keys:
            raise ValueError("follow_ups step %d: unknown template %r" % (i, s.get("template")))
    if len(steps) > MAX_STEPS:
        raise ValueError("at most %d follow-up steps (database CHECK)" % MAX_STEPS)
    return steps


def batch_policy(outreach_cfg):
    """{'sample_min', 'sample_fraction', 'max_batch', 'allow_generated',
    'generated_sample_fraction'} or None when off."""
    b = (outreach_cfg or {}).get("batch_approval") or {}
    if not b.get("enabled"):
        return None
    frac = min(1.0, max(0.0, float(b.get("sample_fraction", 0.1))))
    return {"sample_min": max(1, int(b.get("sample_min", 3))),
            "sample_fraction": frac,
            "max_batch": max(1, int(b.get("max_batch", 100))),
            # A spot check stands for a batch because every draft in it came
            # from one template. A sentence a model wrote for one lead can be
            # wrong on its own, so by default those are approved one at a time.
            "allow_generated": bool(b.get("allow_generated", False)),
            "generated_sample_fraction": min(1.0, max(
                frac, float(b.get("generated_sample_fraction", 0.25))))}


def required_sample(n, policy, has_generated=False):
    frac = policy["generated_sample_fraction"] if has_generated else policy["sample_fraction"]
    return min(n, max(policy["sample_min"], math.ceil(n * frac)))


def outreach_config(cur, segment):
    cur.execute("select config->'outreach' from segments where slug = %s", (segment,))
    row = cur.fetchone()
    cfg = (row[0] if not isinstance(row, dict) else list(row.values())[0]) if row else None
    return cfg if isinstance(cfg, dict) else json.loads(cfg or "{}")


# --------------------------------------------------------------- follow-ups
CANDIDATES_SQL = """
with openers as (
    select o0.id, o0.entity_id, o0.contact_id, o0.subject
    from outreach o0
    join entities e on e.id = o0.entity_id
    where o0.direction = 'outbound' and o0.sequence_step = 0 and o0.status = 'sent'
      and o0.stopped_reason is null
      and e.status = 'contacted'
      and e.segment_id = (select id from segments where slug = %(segment)s)
),
chain as (
    select op.id as opener_id,
           max(x.sequence_step) filter (where x.status = 'sent') as last_step,
           bool_or(x.status in ('drafted', 'approved', 'sending')) as pending,
           bool_or(x.status in ('send_unknown', 'failed')
                   or (x.status = 'approved' and x.send_error is not null)) as wedged
    from openers op
    join outreach x on (x.id = op.id or x.parent_id = op.id) and x.direction = 'outbound'
    group by op.id
)
select op.id as opener_id, op.entity_id, op.contact_id, op.subject as opener_subject,
       e.name as company, e.metadata, c.full_name, c.email, c.email_status,
       ch.last_step,
       (select s.sent_at from outreach s
         where (s.id = op.id or s.parent_id = op.id) and s.direction = 'outbound'
           and s.sequence_step = ch.last_step and s.status = 'sent'
         order by s.sent_at desc limit 1) as last_sent_at
from openers op
join chain ch on ch.opener_id = op.id
join entities e on e.id = op.entity_id
left join contacts c on c.id = op.contact_id
where not ch.pending and not ch.wedged
  and not exists (select 1 from outreach r
                  where r.entity_id = op.entity_id and r.direction = 'inbound'
                    and r.triage is distinct from 'neutral')
  and c.email is not null
  and c.email_status is distinct from 'invalid'
  and contact_allowed(c.entity_id,c.source,c.verifier,c.email_status)
"""


def due_followups(cur, segment, steps, now):
    """[(candidate_row_dict, step_dict)] for every thread whose next step is due."""
    if not steps:
        return []
    cur.execute(CANDIDATES_SQL, {"segment": segment})
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        row = dict(zip(cols, r)) if not isinstance(r, dict) else dict(r)
        nxt = int(row["last_step"] or 0) + 1
        if nxt > len(steps) or not row["last_sent_at"]:
            continue
        step = steps[nxt - 1]
        if (now - row["last_sent_at"]).total_seconds() >= int(step["after_days"]) * 86400:
            out.append((row, step))
    return out


def insert_followup(cur, row, step_no, template_key, subject, body):
    """Insert a follow-up draft; None if the step already exists (unique index)."""
    cur.execute(
        "insert into outreach (entity_id, contact_id, template_key, subject, body, sequence_step, parent_id)"
        " values (%s, %s, %s, %s, %s, %s, %s) on conflict do nothing returning id",
        (row["entity_id"], row["contact_id"], template_key, subject, body, step_no, row["opener_id"]))
    got = cur.fetchone()
    return (got[0] if not isinstance(got, dict) else got["id"]) if got else None


def opener_id_for(cur, entity_id):
    cur.execute("select id from outreach where entity_id = %s and direction = 'outbound'"
                " and sequence_step = 0 and status not in ('cancelled', 'failed')"
                " order by created_at desc limit 1", (entity_id,))
    got = cur.fetchone()
    return (got[0] if not isinstance(got, dict) else got["id"]) if got else None


def stop_thread(cur, entity_id, reason):
    """Permanent: no further follow-ups for this company; pending ones cancelled.
    Returns the number of pending follow-ups cancelled."""
    oid = opener_id_for(cur, entity_id)
    if not oid:
        return 0
    cur.execute("update outreach set stopped_reason = %s, updated_at = now()"
                " where id = %s and stopped_reason is null", (reason[:200], oid))
    cur.execute("update outreach set status = 'cancelled', stopped_reason = %s, updated_at = now()"
                " where parent_id = %s and status in ('drafted', 'approved')", (reason[:200], oid))
    return cur.rowcount


def pause_on_reply(cur, entity_id):
    """A reply arrived: cancel pending follow-ups, but do not stop the thread.
    If the reply turns out to be an auto-reply (triaged neutral), the next
    follow-up run drafts the step again."""
    cur.execute("update outreach set status = 'cancelled', stopped_reason = 'paused: reply received',"
                " updated_at = now()"
                " where entity_id = %s and direction = 'outbound' and sequence_step > 0"
                " and status in ('drafted', 'approved')", (entity_id,))
    return cur.rowcount


# ---------------------------------------------------------- batch approval
def _payload(user, segment, ids, sample, exp):
    return "|".join([user or "", segment, ",".join(sorted(ids)), ",".join(sorted(sample)), str(exp)])


def draw_sample(ids, policy, secret, user, segment, has_generated=False, ttl=3600):
    """Server-drawn random sample plus a signature over batch + sample. A batch
    carrying model-written openers draws the bigger fraction."""
    ids = sorted({str(i) for i in ids})
    if not ids:
        raise ValueError("select at least one draft")
    if len(ids) > policy["max_batch"]:
        raise ValueError("a batch is at most %d drafts" % policy["max_batch"])
    k = required_sample(len(ids), policy, has_generated)
    sample = sorted(secrets.SystemRandom().sample(ids, k))
    exp = int(time.time()) + ttl
    sig = hmac.new(secret, _payload(user, segment, ids, sample, exp).encode(), hashlib.sha256).hexdigest()
    return sample, "%d.%s" % (exp, sig)


def verify_sample(ids, sample, token, secret, user, segment):
    try:
        exp_s, sig = str(token).split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if time.time() > exp:
        return False
    ids = sorted({str(i) for i in ids})
    sample = sorted({str(i) for i in sample})
    want = hmac.new(secret, _payload(user, segment, ids, sample, exp).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


# One first email per inbox and per company, not per lead row (2026-09-21): the same address filed
# under two leads (a podcast network's one inbox behind four shows), or one company found under two
# websites (Close-Up Productions: closeupprod.com and closeupproductions.com), must not get two
# openers. -> the reason, or NULL. `statuses` says what counts as taken: approval also counts other
# approved rows; the sender counts only what has gone or may have gone.
# Since 2026-10-07 the inbox and the website hold across projects: every project writes from the same
# TVF address, so a person or a company gets one first email from us, not one per project. (The name
# rule stays within a project: two companies of one name in different markets are not the same one.)
DUPLICATE_SQL = """
select case
  when exists (
    select 1 from outreach o2
    join contacts c2 on c2.id = o2.contact_id
    join entities e2 on e2.id = o2.entity_id
    where lower(c2.email) = lower(coalesce(%(email)s, c.email))
      and o2.id <> o.id and o2.entity_id <> o.entity_id
      and o2.direction = 'outbound' and coalesce(o2.sequence_step, 0) = 0
      and o2.status = any(%(statuses)s))
    then 'this address already has a first email from us, under another lead'
  -- the same company (its website) under another project's lead: one first email per company from us,
  -- whichever project wrote it (2026-10-07, with LCX Services' Apollo harvest beside Universal's page)
  when e.domain is not null and exists (
    select 1 from outreach o2 join entities e2 on e2.id = o2.entity_id
    where e2.segment_id <> e.segment_id and normalize_domain(e2.domain) = normalize_domain(e.domain)
      and o2.direction = 'outbound' and coalesce(o2.sequence_step, 0) = 0
      and o2.status = any(%(statuses)s)
      -- a first email that bounced reached nobody there: it does not use up the company
      and coalesce(o2.stopped_reason, '') not like 'bounced%%')
    then 'this company already has a first email from us in another project'
  when exists (
    select 1 from outreach o2 join entities e2 on e2.id = o2.entity_id
    where e2.segment_id = e.segment_id and lower(e2.name) = lower(e.name) and e2.id <> e.id
      and o2.direction = 'outbound' and coalesce(o2.sequence_step, 0) = 0
      and o2.status = any(%(statuses)s))
    then 'a company of the same name already has a first email from us'
  end
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id
where o.id = %(oid)s
"""
TAKEN_AT_APPROVAL = ["approved", "sending", "sent", "send_unknown"]
TAKEN_AT_SEND = ["sending", "sent", "send_unknown"]

# An address that has answered an email from us -- anything but an auto-reply -- or bounced one, under
# any lead in any project, gets nothing new from any project (2026-10-06, with LCX Services: Universal
# and LCX Services both write to any business, over the same TVF address). "If this isn't relevant,
# reply "no thanks" and you won't hear from me again" has to hold across projects, and someone already
# in a conversation is answered there, by a person, not sent a second cold email. Their own lead's
# thread is left to the thread rules (a reply pauses or ends it). -> the reason, or NULL.
ANSWERED_SQL = """
select case
  when exists (
    select 1 from outreach r join contacts c on c.id = r.contact_id
    where r.direction = 'inbound' and r.triage is distinct from 'neutral'
      and lower(c.email) = lower(%(email)s) and r.entity_id <> %(entity)s::uuid)
    then 'this address has replied to an earlier email from us: answer them in that thread'
  when exists (
    select 1 from contacts c
    where lower(c.email) = lower(%(email)s) and c.email_status = 'invalid' and c.verifier = 'bounce')
    then 'this address bounced an earlier email from us'
end
"""


def answered_elsewhere(cur, email, entity_id):
    """-> why this address must get no new email from us (ANSWERED_SQL), or None."""
    if not email or not entity_id:
        return None
    cur.execute(ANSWERED_SQL, {"email": email.strip(), "entity": str(entity_id)})
    row = cur.fetchone()
    if not row:
        return None
    return row[0] if not isinstance(row, dict) else list(row.values())[0]


# ------------------------------------------------------------------ attachments
# Files an email carries (sql/32; LCX Services' deck, the owner 2026-10-06: "email should be a pitch
# deck of services" -> "PDF deck attached"). A template names them (outreach.templates[].attachments),
# only files under docs/decks/ can be named, and each email keeps the fingerprint of the file it
# carries: a draft takes the current file when it is approved (refresh_attachments), and the sender
# sends exactly the approved bytes or holds the email back. What a person approved is what is sent.
ATTACH_DIR = ("docs", "decks")
ATTACH_MAX_BYTES = 5 * 1024 * 1024


def _repo():
    import os
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _attach_parts(path):
    parts = [p for p in str(path or "").replace("\\", "/").split("/") if p]
    if len(parts) < 3 or tuple(parts[:2]) != ATTACH_DIR or any(p in (".", "..") for p in parts):
        raise ValueError("an attachment must be a file under docs/decks/, not %r" % (path,))
    return parts


def attachment_file(path):
    """The absolute path of a repo-relative attachment; ValueError when it is not under docs/decks/."""
    import os
    return os.path.join(_repo(), *_attach_parts(path))


def attachment_record(path):
    """{name, path, sha256, bytes} for one attachment, read now. ValueError/OSError when it cannot go."""
    parts = _attach_parts(path)
    with open(attachment_file(path), "rb") as f:
        data = f.read()
    if not data:
        raise ValueError("%s is empty" % "/".join(parts))
    if len(data) > ATTACH_MAX_BYTES:
        raise ValueError("%s is %d KB: an attachment over %d KB is not sent"
                         % ("/".join(parts), len(data) // 1024, ATTACH_MAX_BYTES // 1024))
    return {"name": parts[-1], "path": "/".join(parts), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def attachments_for(tpl):
    """The records for a template's attachments ([] when it names none)."""
    return [attachment_record(p) for p in (tpl or {}).get("attachments") or []]


def attachment_problem(atts):
    """-> why these attachments cannot go as recorded, or None."""
    for a in atts or []:
        name = (a or {}).get("name") if isinstance(a, dict) else None
        try:
            with open(attachment_file(a.get("path")), "rb") as f:
                data = f.read()
        except (ValueError, OSError, AttributeError):
            return "the attached %s is missing" % (name or "file")
        if hashlib.sha256(data).hexdigest() != a.get("sha256"):
            return "the attached %s has changed since this email was approved" % (name or "file")
    return None


def attachment_bytes(a):
    with open(attachment_file(a["path"]), "rb") as f:
        return f.read()


def refresh_attachments(cur, ids):
    """Drafts take the current file of each attachment (a deck rebuilt since they were drafted), so the
    person approving one approves the file they can open now. Approved and sent emails are never touched.
    A file that is gone is left recorded as it was: the check then says it is missing."""
    ids = [str(i) for i in ids or []]
    if not ids:
        return 0
    cur.execute("select id, attachments from outreach where id = any(%s::uuid[]) and status = 'drafted'"
                " and attachments is not null", (ids,))
    changed = 0
    for r in cur.fetchall():
        oid, atts = (r["id"], r["attachments"]) if isinstance(r, dict) else (r[0], r[1])
        atts = atts if isinstance(atts, list) else json.loads(atts or "[]")
        try:
            fresh = [attachment_record(a["path"]) for a in atts]
        except (ValueError, OSError, KeyError, TypeError):
            continue
        if fresh != atts:
            cur.execute("update outreach set attachments = %s, updated_at = now() where id = %s and status = 'drafted'",
                        (json.dumps(fresh), oid))
            changed += 1
    return changed

# What has gone out today, or may have: the cap counts a send whose outcome is unknown, and one in
# flight in another run. The day is the database's, UTC, as everywhere else.
OUT_TODAY_SQL = """
select count(*) from outreach o
join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %s)
  and o.direction = 'outbound' and o.status in ('sent', 'sending', 'send_unknown')
  and coalesce(o.sent_at, o.updated_at)::date = current_date
"""

# A saved choice is part of the exact email a person reviews. If its address or
# eligibility changes, neither approval nor the sender may substitute someone
# else. Projects/leads with no saved choice keep their existing checks.
SELECTED_RECIPIENT_SQL = "(" + PREFERENCE_MATCH_SQL + """ and (
    not (coalesce(e.metadata, '{}'::jsonb) ? 'outreach_recipient')
    or (c.entity_id = e.id and """ + ELIGIBLE_CONTACT_SQL + ")) )"
SELECTED_RECIPIENT_REASON = ("Selected recipient changed or is no longer eligible; "
                             "choose and review the recipient again.")

CHECK_SQL = """
select o.id, o.status, o.direction, o.subject, o.body, o.sequence_step,
       o.generated_hook, c.email, c.email_status,
       contact_allowed(e.id,c.source,c.verifier,c.email_status) as verified_allowed,
       """ + SELECTED_RECIPIENT_SQL + """ as selected_recipient_matches,
       (coalesce(s.config#>>'{sourcing,contacts}','') <> 'apollo' or not (s.config ? 'lead_service') or coalesce(o.sequence_step,0)>0 or
        (o.service is not null and o.service=coalesce(e.metadata#>>'{lead_service,service}',e.metadata#>>'{lead_service,name}'))) as service_matches,
       e.status as entity_status, s.slug, e.name as entity_name, o.entity_id, o.attachments
from outreach o
join entities e on e.id = o.entity_id
join segments s on s.id = e.segment_id
left join contacts c on c.id = o.contact_id
where o.id = any(%s::uuid[])
"""


def check_drafts(cur, ids, segment, policy=None):
    """-> (approvable_ids, [{"id", "reason"}]) for the given draft ids.

    `policy` is passed only on the BATCH path. With it, a draft whose opening
    sentence a model wrote is held back unless the segment allows generated
    drafts in a batch -- a random few cannot stand for text that was written
    once, for one lead. Approving that same draft on its own is unaffected,
    which is the whole point: it is still approvable, just not in bulk."""
    ids = [str(i) for i in ids]
    refresh_attachments(cur, ids)                 # a draft carries the file a person can open now
    cur.execute(CHECK_SQL, (ids,))
    cols = [d[0] for d in cur.description]
    found = {}
    for r in cur.fetchall():
        row = dict(zip(cols, r)) if not isinstance(r, dict) else dict(r)
        found[str(row["id"])] = row
    ok, skipped = [], []
    chosen = set()               # addresses and company names already approvable in THIS call (a batch)
    for i in ids:
        r = found.get(i)
        reason = None
        if not r:
            reason = "no such draft"
        elif r["slug"] != segment:
            reason = "belongs to another segment"
        elif r["direction"] != "outbound" or r["status"] != "drafted":
            reason = "not a draft any more (%s)" % r["status"]
        elif not (r["subject"] or "").strip():
            reason = "empty subject"
        elif "\n" in (r["subject"] or "") or "\r" in (r["subject"] or ""):
            reason = "the subject has a line break in it"           # the sender would refuse it (2026-09-21)
        elif PLACEHOLDER_RE.search((r["subject"] or "") + (r["body"] or "")):
            reason = "unfilled {{placeholder}}"
        elif "SET_ME" in (r["subject"] or "") + (r["body"] or ""):
            reason = "sender details still say SET_ME"
        elif not r.get("selected_recipient_matches", True):
            reason = SELECTED_RECIPIENT_REASON
        elif not r["email"] or not EMAIL_RE.match(r["email"].strip()):
            reason = "recipient address missing or malformed"
        elif r["email_status"] == "invalid":
            reason = "recipient failed verification"
        elif not r["verified_allowed"]:
            reason = "Apollo has not verified the recipient email"
        elif not r["service_matches"]:
            reason = "the lead's service changed; create and review a fresh draft"
        elif r["sequence_step"] == 0 and r["entity_status"] not in ("shortlisted", "contacted"):
            reason = "company is now '%s'" % r["entity_status"]
        elif r["sequence_step"] > 0 and r["entity_status"] != "contacted":
            reason = "company is now '%s'" % r["entity_status"]
        elif policy and not policy["allow_generated"] and r["generated_hook"]:
            reason = "its opening line was written by a model; approve it on its own"
        elif not (r["body"] or "").strip():
            reason = "empty body"
        else:
            reason = (attachment_problem(r.get("attachments"))
                      or answered_elsewhere(cur, r["email"], r["entity_id"]))
            if not reason and r["sequence_step"] == 0:
                cur.execute(DUPLICATE_SQL, {"oid": i, "email": None, "statuses": TAKEN_AT_APPROVAL})
                dup = cur.fetchone()
                reason = (dup[0] if not isinstance(dup, dict) else list(dup.values())[0]) if dup else None
                keys = {"email:" + r["email"].strip().lower(), "name:" + (r["entity_name"] or "").strip().lower()}
                if not reason and keys & chosen:
                    reason = "another selected draft goes to the same address or company"
                if not reason:
                    chosen |= keys
        if reason:
            skipped.append({"id": i, "reason": reason})
        else:
            ok.append(i)
    return ok, skipped


def generated_among(cur, ids):
    """Which of these drafts had their opening sentence written by a model.
    A batch containing any of them needs a bigger sample."""
    if not ids:
        return set()
    cur.execute("select id from outreach where id = any(%s::uuid[])"
                " and generated_hook is not null", ([str(i) for i in ids],))
    return {str(r["id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def apply_batch(cur, approve_ids, sample_ids, user, segment, requested, skipped):
    """Approve the checked drafts, give each its moment in its recipient's window (schedule_sends), and
    record the batch. Returns (batch_id, approved, {id: schedule view}) -- {} where the project has no window.
    One email with no free minute in 60 days does not undo the batch: it stays approved with no time, and
    the next settle_schedule tries it again."""
    batch_id = str(uuid.uuid4())
    ids = []
    if approve_ids:
        cur.execute(
            "update outreach set status = 'approved', approved_at = now(), approved_by = %s,"
            " approval_mode = 'batch', approval_batch = %s, spot_checked = (id = any(%s::uuid[])),"
            " updated_at = now()"
            " where id = any(%s::uuid[]) and status = 'drafted' and direction = 'outbound' returning id",
            (user, batch_id, [str(s) for s in sample_ids], [str(a) for a in approve_ids]))
        ids = [str(r["id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()]
    approved = len(ids)
    cur.execute(
        "insert into outreach_approval_batches (id, segment_slug, approved_by, requested, approved, sample_ids, skipped)"
        " values (%s, %s, %s, %s, %s, %s::uuid[], %s::jsonb)",
        (batch_id, segment, user or "unknown", requested, approved, [str(s) for s in sample_ids], json.dumps(skipped)))
    schedule = schedule_sends(cur, ids, outreach_config(cur, segment), segment, strict=False) if ids else {}
    return batch_id, approved, schedule


# ---------------------------------------------------------------- mailboxes
DEFAULT_MAILBOX = "default"
MAILBOX_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def mailbox_list(outreach_cfg, segment):
    """The segment's sending mailboxes, validated. Token file and variable
    names are derived here so every tool agrees on them."""
    cfg = outreach_cfg or {}
    seg_var = segment.upper().replace("-", "_")
    boxes = cfg.get("mailboxes") or []
    if not boxes:
        env_name = (cfg.get("sender") or {}).get("email_env") or "GMAIL_SENDER_ADDRESS"
        custom = env_name != "GMAIL_SENDER_ADDRESS"
        return [{"key": DEFAULT_MAILBOX, "email_env": env_name,
                 "daily_cap": max(1, int(cfg.get("daily_send_cap", 20))), "warmup": None, "enabled": True,
                 "token_file": (".gmail_token.%s.json" % segment) if custom else ".gmail_token.json",
                 "token_env": ("GMAIL_TOKEN_JSON_" + seg_var) if custom else "GMAIL_TOKEN_JSON"}]
    out, seen = [], set()
    for b in boxes:
        key = str(b.get("key") or "").strip()
        if not MAILBOX_KEY_RE.match(key) or key in seen:
            raise ValueError("mailbox keys must be unique lowercase letters, digits or _: %r" % key)
        seen.add(key)
        if not b.get("email_env"):
            raise ValueError("mailbox %s: email_env is required" % key)
        w = b.get("warmup")
        if w:
            w = {"start_cap": max(1, int(w.get("start_cap", 10))), "step": max(0, int(w.get("step", 5))),
                 "every_days": max(1, int(w.get("every_days", 2)))}
        out.append({"key": key, "email_env": b["email_env"], "daily_cap": max(1, int(b.get("daily_cap", 40))),
                    "warmup": w or None, "enabled": b.get("enabled", True) is not False,
                    "token_file": ".gmail_token.%s.%s.json" % (segment, key),
                    "token_env": "GMAIL_TOKEN_JSON_%s_%s" % (seg_var, key.upper())})
    return out


SENDER_FIELDS = ("name", "title", "postal_address", "email_env")


def sender_unset(sender):
    """Does a real sender field still hold the SET_ME placeholder? Only the fields an email carries are
    looked at -- never sender.guidance, whose own text explains SET_ME. Scanning the whole block with
    json.dumps (as the scheduler and `outreach.py send` did) meant the note alone blocked every send:
    the first approved email of 2026-09-21 sat in Approved with the footer filled in and the mailbox
    connected, because the guidance mentions the word."""
    s = sender or {}
    return any("SET_ME" in str(s.get(k) or "") for k in SENDER_FIELDS)


def sending_paused(cfg):
    """Why sending is paused for this segment, or None. outreach.sending_paused (owner, 2026-09-21:
    "temporarily block sending emails from anything else other than us production houses").
    Only the send stops: drafting and approval carry on, and an approved email waits in Approved
    until the pause is lifted. Checked by the scheduler before it sends, by `outreach.py send`
    itself, and by the page when it says what approving will do."""
    if not (cfg or {}).get("sending_paused"):
        return None
    return str(cfg.get("sending_paused_reason") or "sending is paused for this project")


def cap_today(mb, first_sent, today):
    """Warm-up: start_cap until the mailbox has sent, then +step every
    every_days counted from its first sending day, never above daily_cap."""
    if not mb.get("enabled", True):
        return 0
    w = mb.get("warmup")
    if not w:
        return mb["daily_cap"]
    if not first_sent:
        return min(mb["daily_cap"], w["start_cap"])
    days = max(0, (today - first_sent).days)
    return min(mb["daily_cap"], w["start_cap"] + w["step"] * (days // w["every_days"]))


USAGE_SQL = """
select coalesce(o.sender_mailbox, %(default)s) as mailbox,
       count(*) filter (where o.sent_at::date = current_date) as sent_today,
       min(o.sent_at)::date as first_sent,
       max(o.sender_address) as last_address
from outreach o
join entities e on e.id = o.entity_id
where o.direction = 'outbound' and o.status = 'sent'
  and e.segment_id = (select id from segments where slug = %(segment)s)
group by 1
"""


def mailbox_status(cur, segment, boxes, today):
    """Each mailbox with its cap for today, sends today and room left.
    Emails recorded before rotation existed count against the first mailbox."""
    cur.execute(USAGE_SQL, {"segment": segment, "default": boxes[0]["key"]})
    cols = [d[0] for d in cur.description]
    usage = {}
    for r in cur.fetchall():
        row = dict(zip(cols, r)) if not isinstance(r, dict) else dict(r)
        usage[row["mailbox"]] = row
    out = []
    for mb in boxes:
        u = usage.get(mb["key"]) or {}
        first = u.get("first_sent")
        cap = cap_today(mb, first, today)
        sent = int(u.get("sent_today") or 0)
        out.append(dict(mb, cap_today=cap, sent_today=sent, remaining=max(0, cap - sent), first_sent=first,
                        last_address=u.get("last_address"),
                        warmup_day=((today - first).days + 1) if first else 0))
    return out


def pick_mailbox(remaining, connected):
    """remaining: [(key, room left today)] in config order. The connected
    mailbox with the most room wins; ties go to the earlier one."""
    best = None
    for key, left in remaining:
        if key in connected and left > 0 and (best is None or left > best[1]):
            best = (key, left)
    return best[0] if best else None


BOUNCE_FROM = re.compile(r"mailer-daemon|postmaster@|mail delivery (?:sub)?system", re.I)
BOUNCE_SUBJECT = re.compile(r"delivery status notification \(failure\)|undeliverable|undelivered mail"
                            r"|delivery (?:has )?failed|returned mail|failure notice|address not found", re.I)


def is_bounce(from_header, subject):
    """A delivery failure notice, not a person."""
    return bool(BOUNCE_FROM.search(from_header or "")) or (
        bool(BOUNCE_SUBJECT.search(subject or "")) and not (subject or "").lower().startswith("re:"))


def mark_bounce(cur, entity_id, contact_id):
    """The address rejected the email: never write to it again, end the thread."""
    if contact_id:
        cur.execute("update contacts set email_status = 'invalid', verifier = 'bounce',"
                    " email_verified_at = now(), updated_at = now() where id = %s", (contact_id,))
    return stop_thread(cur, entity_id, "bounced: the address rejected the email")


# ------------------------------------------------------------ the sending window
# The owner, 2026-10-12: "I want you to send mails to the sender's time region between 10 to 10:30AM and
# that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13 and so
# on". Where a reader is and when their window opens are tools/send_window.py's (pure, no database); this
# part reads and writes the rows (sql/34). Every function takes a cursor, never commits, and works with
# the app's dict cursor and the tools' tuple cursor alike.
MISSES_TO_ALERT = 3          # windows an email may miss (a pause aside) before the owner is told


class NoSendSlot(ValueError):
    """No free second in any window of the next 60 days for this approver (or this project's mailboxes)."""


def _sw():
    import send_window
    return send_window


def _dicts(cur):
    cols = [d[0] for d in cur.description]
    return [dict(r) if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _first(cur):
    r = cur.fetchone()
    if r is None:
        return None
    return list(r.values())[0] if isinstance(r, dict) else r[0]


def db_now(cur):
    """The database's clock now: clock_timestamp(), not now(), which is the transaction's start and in a long
    one minutes old. Every moment is drawn and compared on the clock the sender's claim checks against."""
    cur.execute("select clock_timestamp() as now")
    return _first(cur)


# what placing an email needs: where its reader is (the lead's metadata, the contact's own Apollo record)
# and, for a follow-up, the zone its first email went in -- a thread keeps one clock
_SCHED_SQL = """
select o.id, o.status, coalesce(o.sequence_step, 0) as sequence_step, lower(o.approved_by) as approver,
       e.metadata, c.notes, c.linkedin_url, p.send_tz as ptz, p.send_tz_reason as preason, p.send_plan as pplan,
       o.send_after, o.send_before, o.send_tz, o.send_tz_reason, o.send_plan, o.send_reschedules,
       o.send_wait_why, o.send_error
from outreach o
join entities e on e.id = o.entity_id
left join contacts c on c.id = o.contact_id
left join outreach p on p.id = o.parent_id
where {where}
order by (coalesce(o.sequence_step, 0) > 0) desc, o.created_at
"""
_SEG_APPROVED = ("e.segment_id = (select id from segments where slug = %(segment)s)"
                 " and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null")
_WRITE_SQL = ("update outreach set send_after = %s, send_before = %s, send_tz = %s, send_tz_reason = %s,"
              " send_plan = %s, send_wait_why = %s where id = %s and status = 'approved'")
# a move to the next window: guarded by the window it was in, so two settles at once move it once
_MOVE_SQL = ("update outreach set send_after = %s, send_before = %s, send_reschedules = send_reschedules + 1,"
             " send_wait_why = %s where id = %s and status = 'approved' and send_before = %s"
             " returning send_reschedules")
_UNPLACED_SQL = ("update outreach set send_after = null, send_before = null, send_plan = null, send_wait_why = %s"
                 " where id = %s and status = 'approved'")

# The moments a key already holds. From the approver: that person's approvals in every project that sends
# from the approver -- their addresses are theirs whatever they approved for, and Universal, LCX Services
# and US Production Houses all send through them. From the pool: the project's own.
_PLACED_APPROVER_SQL = """
select o.id, o.send_after from outreach o
join entities e on e.id = o.entity_id
join segments s on s.id = e.segment_id
where o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
  and o.send_after >= %(lo)s and o.send_after < %(hi)s
  and lower(o.approved_by) = %(person)s and s.config->'outreach'->>'send_from' = 'approver'
"""
_SENT_APPROVER_SQL = """
select coalesce(o.sent_at, o.updated_at) as at from outreach o
where o.direction = 'outbound' and o.status in ('sent', 'sending', 'send_unknown')
  and coalesce(o.sent_at, o.updated_at) >= %(lo)s
  and (lower(o.approved_by) = %(person)s or lower(o.sender_address) = any(%(addrs)s::text[]))
"""
_PLACED_POOL_SQL = """
select o.id, o.send_after from outreach o join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %(segment)s)
  and o.direction = 'outbound' and o.status = 'approved' and o.send_error is null
  and o.send_after >= %(lo)s and o.send_after < %(hi)s
"""
_SENT_POOL_SQL = """
select coalesce(o.sent_at, o.updated_at) as at from outreach o join entities e on e.id = o.entity_id
where e.segment_id = (select id from segments where slug = %(segment)s)
  and o.direction = 'outbound' and o.status in ('sent', 'sending', 'send_unknown')
  and coalesce(o.sent_at, o.updated_at) >= %(lo)s
"""


SENDER_CLOCK = "sender's clock"          # how send_window.recipient_zone's reason starts in sender mode


def _zone_for(row, w):
    """(zone, why) for one row. A follow-up goes at its first email's clock; anything else is placed from
    what its lead holds (send_window.recipient_zone).
    The first email's zone is kept only when it was its recipient's, under the config in force now (review,
    2026-10-12): one placed on the sender's clock, or under another window config (its send_plan), is
    resolved again -- a project switched from "sender" to "recipient" must not send a New York follow-up at
    India's 10:00, 00:30 in New York."""
    if (int(row.get("sequence_step") or 0) > 0 and row.get("ptz") and w.get("timezone_of") == "recipient"
            and not str(row.get("preason") or "").startswith(SENDER_CLOCK)
            and row.get("pplan") == _sw().plan_key(w)):
        return row["ptz"], "same as the first email: %s" % (row.get("preason") or row["ptz"])
    meta = row.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta or "{}")
    return _sw().recipient_zone(meta or {}, w, {"notes": row.get("notes"), "linkedin_url": row.get("linkedin_url")})


class _Placer:
    """place_send's memory inside one transaction: each key's capacity, the moments it already holds and
    what it has sent. A batch of a hundred is then a hundred UPDATEs, not four hundred queries, and each
    moment drawn is seen by the next draw."""

    def __init__(self, cur, w, cfg, segment, now, rng=None):
        self.cur, self.w, self.cfg, self.segment = cur, w, cfg or {}, segment
        self.now = _sw()._utc(now)
        self.rng = rng or random.SystemRandom()
        self.approver_mode = self.cfg.get("send_from") == "approver"
        self.keys = {}

    def key(self, row):
        """Who sends it: the approver's own addresses (send_from "approver"), or the project's mailboxes."""
        if self.approver_mode:
            return "approver:" + str(row.get("approver") or "").lower()
        return "segment:" + self.segment

    def lock(self, rows):
        """Every key these rows use, locked in one order before anything is drawn: two approvals for one
        person wait for each other (never one second twice), and two settles never deadlock."""
        for k in sorted({self.key(r) for r in rows}):
            self._state(k)

    def _state(self, k):
        st = self.keys.get(k)
        if st is not None:
            return st
        cur, sw = self.cur, _sw()
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", ("outreach-schedule:" + k,))
        p = {"lo": self.now - dt.timedelta(days=1), "hi": self.now + dt.timedelta(days=63), "segment": self.segment}
        if self.approver_mode:
            import mailbox_store as store
            person = k.split(":", 1)[1]
            boxes = [b for b in store.mailboxes(cur, user_email=person) if b["usable"]] if person else []
            # one person's addresses, each with its own limit: n draws can share a gap, the day holds their sum
            n = max(1, len(boxes))
            daily = sum(int(b["daily_cap"]) for b in boxes) if boxes else store.DEFAULT_CAP
            p.update(person=person, addrs=[b["address"].lower() for b in boxes])
            cur.execute(_PLACED_APPROVER_SQL, p)
            placed = {str(r["id"]): sw._utc(r["send_after"]) for r in _dicts(cur)}
            cur.execute(_SENT_APPROVER_SQL, p)
            sent = [sw._utc(r["at"]) for r in _dicts(cur) if r["at"]]

            def daily_for(day, _d=daily):
                return _d
        else:
            every = mailbox_list(self.cfg, self.segment)
            boxes = [b for b in every if b["enabled"]]
            n = max(1, len(boxes))
            cur.execute(USAGE_SQL, {"segment": self.segment, "default": every[0]["key"]})
            first = {r["mailbox"]: r["first_sent"] for r in _dicts(cur)}
            ceiling = int(self.cfg.get("daily_send_cap", 20))

            def daily_for(day, _b=boxes, _f=first, _c=ceiling):
                # the project's ceiling, and each mailbox's warm-up cap on THAT day
                return min(_c, sum(cap_today(b, _f.get(b["key"]), day) for b in _b))
            cur.execute(_PLACED_POOL_SQL, p)
            placed = {str(r["id"]): sw._utc(r["send_after"]) for r in _dicts(cur)}
            cur.execute(_SENT_POOL_SQL, p)
            sent = [sw._utc(r["at"]) for r in _dicts(cur) if r["at"]]
        st = {"n": n, "daily_for": daily_for, "placed": placed, "sent": sent}
        self.keys[k] = st
        return st

    def place(self, row, zone, after=None):
        """-> (moment, window end) for one row: the first window from `after` (else now) with a free second
        that fits every rule, the second drawn uniformly over the free ones. NoSendSlot when none in 60 days.
          * the approval's lead time (min_lead_seconds) and never in a window's last minute
          * at most n x slots_per_window in one window (n: the key's addresses)
          * at most the key's daily limit placed and sent on the window's UTC day -- "35 a day" is a UTC-day
            count everywhere (mailbox_store.USAGE_SQL), so a window is counted on the day the claim counts it
          * no two moments of the key closer than spacing_s / n"""
        sw, w = _sw(), self.w
        st = self._state(self.key(row))
        oid = str(row["id"])
        others = [t for i, t in st["placed"].items() if i != oid]
        sent, n = st["sent"], st["n"]
        spacing = float(w["spacing_s"])
        pad, tail = dt.timedelta(seconds=spacing), dt.timedelta(seconds=w["tail_s"])
        start = max(self.now, sw._utc(after)) if after else self.now
        lead = self.now + dt.timedelta(seconds=w["min_lead_seconds"])
        for ws, we, _day in sw.windows(zone, w, start):
            lo, hi = max(ws, lead, start), we - tail
            if (hi - lo).total_seconds() < 60:
                continue
            if sum(1 for t in others if ws <= t < we) >= n * sw.slots_per_window((we - ws).total_seconds(), w):
                continue
            day = ws.date()                                   # ws is UTC: the day the cap counts it on
            used = sum(1 for t in others if t.date() == day) + sum(1 for t in sent if t.date() == day)
            if used >= st["daily_for"](day):
                continue
            taken = [t for t in others + sent if ws - pad <= t < we + pad]
            m = sw.pick_moment(lo, hi, taken, spacing / n, self.rng)
            if m is not None:
                st["placed"][oid] = m
                return m, we
        raise NoSendSlot("no free sending minute in the next 60 days")


def place_send(cur, row, zone, wcfg, cfg, segment, now, rng=None, after=None):
    """The one capacity rule, for one row ({id, approver}): -> (send_after, send_before). See _Placer.place.
    Used by approving (schedule_sends), a missed window (settle_schedule) and a deferral (defer_rows)."""
    return _Placer(cur, wcfg, cfg, segment, now, rng).place(row, zone, after=after)


def _place_rows(cur, rows, w, cfg, segment, now=None, rng=None, why=None, strict=False):
    """Resolve each row's zone, draw its moment, store both. -> {id: schedule view}."""
    if not rows:
        return {}
    placer = _Placer(cur, w, cfg, segment, now or db_now(cur), rng)
    placer.lock(rows)
    plan = _sw().plan_key(w)
    out = {}
    for r in rows:
        zone, reason = _zone_for(r, w)
        try:
            sa, sb = placer.place(r, zone)
        except NoSendSlot as e:
            if strict:
                raise
            cur.execute(_UNPLACED_SQL, (str(e), r["id"]))
            continue
        cur.execute(_WRITE_SQL, (sa, sb, zone, reason, plan, why, r["id"]))
        out[str(r["id"])] = schedule_view(dict(r, status="approved", send_after=sa, send_before=sb, send_tz=zone,
                                               send_tz_reason=reason, send_wait_why=why), w)
    return out


def schedule_sends(cur, ids, cfg, segment, now=None, rng=None, strict=True):
    """Give each approved email its own moment in its recipient's next window and store it, with the zone
    and why (sql/34). -> {id: schedule view}; {} where the project has no window. Every approval path calls
    it: one at a time and a batch (app/main.py), an email a person wrote (tools/outreach_compose.py).
    strict: an email with no free minute in 60 days raises NoSendSlot, so a single approval says so and is
    not made; otherwise it stays approved with no time and the reason, and settle_schedule tries again."""
    w = _sw().window_cfg(cfg)
    ids = [str(i) for i in ids or []]
    if not w or not ids:
        return {}
    cur.execute(_SCHED_SQL.replace("{where}", "o.id = any(%(ids)s::uuid[]) and o.status = 'approved'"), {"ids": ids})
    return _place_rows(cur, _dicts(cur), w, cfg, segment, now, rng, strict=strict)


def settle_schedule(cur, segment, cfg, paused=False, now=None, rng=None):
    """Bring every approved email of the project in line with its window config. -> {cleared, scheduled,
    replanned, moved, alert_ids}. Run by the sender before each run and by the app's send loop.
      window off   every stored time is cleared: the emails send as they did before the window existed
      no time yet  placed (an approval made while the window was off, or with no free minute then)
      placed under another config (send_plan)   placed again, zone and all ("the sending window changed")
      window passed unsent (server down, the job busy, a cap)   moved to the next window at a new random
                   second, never sent late; one that has missed MISSES_TO_ALERT and was not paused is
                   returned in alert_ids
    Never touches a parked email (send_error) or one sending or of unknown outcome."""
    sw = _sw()
    out = {"cleared": 0, "scheduled": 0, "replanned": 0, "moved": 0, "alert_ids": []}
    w = sw.window_cfg(cfg)
    if not w:
        cur.execute("update outreach o set send_after = null, send_before = null, send_plan = null"
                    " from entities e where e.id = o.entity_id"
                    " and e.segment_id = (select id from segments where slug = %s)"
                    " and o.direction = 'outbound' and o.status = 'approved' and o.send_after is not null", (segment,))
        out["cleared"] = cur.rowcount
        return out
    now = sw._utc(now or db_now(cur))
    plan = sw.plan_key(w)
    cur.execute(_SCHED_SQL.replace("{where}", _SEG_APPROVED + " and (o.send_after is null or o.send_plan is distinct"
                                   " from %(plan)s or o.send_before <= %(now)s)"),
                {"segment": segment, "plan": plan, "now": now})
    rows = _dicts(cur)
    if not rows:
        return out
    placer = _Placer(cur, w, cfg, segment, now, rng)
    placer.lock(rows)
    for r in rows:
        oid = r["id"]
        if r["send_after"] is not None and r.get("send_plan") == plan:
            # its window passed unsent: the same zone, the next window. The reason is this move's, not the
            # last one's -- a row deferred yesterday for a cap and missed today because the server was down
            # must not still say "at its daily limit"
            zone = r.get("send_tz") or _zone_for(r, w)[0]
            try:
                sa, sb = placer.place(r, zone, after=now)
            except NoSendSlot as e:
                cur.execute(_UNPLACED_SQL, (str(e), oid))
                continue
            why = "sending is paused" if paused else "the server did not send it in its window"
            cur.execute(_MOVE_SQL, (sa, sb, why, oid, r["send_before"]))
            got = _first(cur)
            if got is not None:
                out["moved"] += 1
                if not paused and int(got) >= MISSES_TO_ALERT:
                    out["alert_ids"].append(str(oid))
            continue
        replan = r["send_after"] is not None
        zone, reason = _zone_for(r, w)
        try:
            sa, sb = placer.place(r, zone)
        except NoSendSlot as e:
            cur.execute(_UNPLACED_SQL, (str(e), oid))
            continue
        cur.execute(_WRITE_SQL, (sa, sb, zone, reason, plan,
                                 "the sending window changed in the config" if replan else None, oid))
        out["replanned" if replan else "scheduled"] += 1
    return out


def defer_rows(cur, ids, cfg, segment, why, now=None, rng=None, alerts=None):
    """Move approved emails, still in their window, to the next one at a new random second, saying why (the
    sender: an address at its daily limit, no address linked, Gmail refusing it, a reply not read yet).
    -> how many moved. Nothing happens where the project has no window.
    alerts: a list the ids are added to that have now moved MISSES_TO_ALERT times or more -- the same count
    settle_schedule alerts on, so an email moved every day for one reason is told of, not moved for ever
    (review, 2026-10-12)."""
    w = _sw().window_cfg(cfg)
    ids = [str(i) for i in ids or []]
    if not w or not ids:
        return 0
    cur.execute(_SCHED_SQL.replace("{where}", "o.id = any(%(ids)s::uuid[]) and o.status = 'approved'"
                                              " and o.send_before is not null"), {"ids": ids})
    rows = _dicts(cur)
    if not rows:
        return 0
    placer = _Placer(cur, w, cfg, segment, now or db_now(cur), rng)
    placer.lock(rows)
    moved = 0
    for r in rows:
        zone = r.get("send_tz") or _zone_for(r, w)[0]
        try:
            sa, sb = placer.place(r, zone, after=r["send_before"])
        except NoSendSlot:
            continue                                  # left where it is: settle_schedule moves it when it passes
        cur.execute(_MOVE_SQL, (sa, sb, why, r["id"], r["send_before"]))
        got = _first(cur)
        if got is not None:
            moved += 1
            if alerts is not None and int(got) >= MISSES_TO_ALERT:
                alerts.append(str(r["id"]))
    return moved


def sweep_stale_sending(cur, minutes=15):
    """An email left in 'sending' (the sender stopped between its claim and Gmail's answer: a crash, a
    deploy) becomes 'send_unknown', so a person checks Gmail's Sent before it is sent again. -> how many."""
    cur.execute("update outreach set status = 'send_unknown',"
                " send_error = 'left in sending for 15 minutes (the sender stopped mid-send): check Gmail Sent"
                " before resending', updated_at = clock_timestamp()"
                " where direction = 'outbound' and status = 'sending'"
                " and updated_at < clock_timestamp() - make_interval(mins => %s)", (int(minutes),))
    return cur.rowcount


def _iso(t):
    return _sw()._utc(t).isoformat() if t else None


def schedule_view(row, wcfg, paused=None):
    """The one shape every API returns for an email's time, or None when it has none:
    {send_after, send_before (ISO UTC), send_tz, send_tz_reason, send_label "Tue 14 Oct, 10:17 New York time
    (19:47 IST)", send_short "Tue 10:17 New York", window_label "Tue 14 Oct, 10:00-10:30 New York time
    (19:30-20:00 IST)", reschedules, wait_why, held: false}. An approved email of a project whose window is off
    has no time any more (settle_schedule clears it), so it gets None too.
    HELD (review, 2026-10-12): an approved email that will not go -- parked with a send_error (park(), or
    unclaim with a reason), which nothing sends and settle_schedule leaves alone, or one of a project whose
    sending is paused (`paused`: outreach_policy.sending_paused) -- gets {held: true, held_why} and no time at
    all: a "Goes out Tue 10:13" that passes and stays would be a promise nobody keeps."""
    if not row:
        return None
    if wcfg is not None and row.get("status") == "approved" and (row.get("send_error") or paused):
        return {"held": True, "held_why": row.get("send_error") or paused,
                "send_after": None, "send_before": None, "send_tz": row.get("send_tz"),
                "send_tz_reason": row.get("send_tz_reason"), "send_label": None, "send_short": None,
                "window_label": None, "reschedules": int(row.get("send_reschedules") or 0),
                "wait_why": row.get("send_wait_why")}
    if not row.get("send_after") or not row.get("send_before") or not row.get("send_tz"):
        return None
    if wcfg is None and row.get("status") == "approved":
        return None
    sw = _sw()
    from zoneinfo import ZoneInfo
    w = wcfg or sw.DEFAULTS
    sa, sb, zone = sw._utc(row["send_after"]), sw._utc(row["send_before"]), row["send_tz"]
    ws = sw._wall_to_utc(sb.astimezone(ZoneInfo(zone)).date(), w["start"], ZoneInfo(zone))
    if not ws <= sa < sb:
        ws = sa                                       # a time placed under another window: label what it holds
    return {"send_after": _iso(sa), "send_before": _iso(sb), "send_tz": zone,
            "send_tz_reason": row.get("send_tz_reason"),
            "send_label": sw.send_label(sa, zone, w), "send_short": sw.send_short(sa, zone),
            "window_label": sw.window_label(ws, sb, zone, w),
            "reschedules": int(row.get("send_reschedules") or 0), "wait_why": row.get("send_wait_why"),
            "held": False}


def draft_window(cur, oid, cfg):
    """{enabled, send_tz, send_tz_reason, window_label} for a draft: the window approving it now aims at --
    a window, never a minute. The minute is drawn on approval; one shown here would promise a time nobody
    holds. {"enabled": False} where the project has no window (or no such email)."""
    sw = _sw()
    try:
        w = sw.window_cfg(cfg)
    except ValueError:
        w = None
    if not w:
        return {"enabled": False}
    cur.execute(_SCHED_SQL.replace("{where}", "o.id = %(id)s"), {"id": str(oid)})
    rows = _dicts(cur)
    if not rows:
        return {"enabled": False}
    zone, reason = _zone_for(rows[0], w)
    nw = sw.next_window(zone, w, db_now(cur))
    return {"enabled": True, "send_tz": zone, "send_tz_reason": reason,
            "window_label": sw.window_label(nw[0], nw[1], zone, w) if nw else None}


def window_summary(schedules):
    """What a batch approval did, by the recipient's own day and place, for the page to say "9 on Tue 14 Oct
    (6 New York, 3 UK), 3 on Wed 15 Oct": [{day, label, count, places: [[place, n]]}], by date."""
    sw = _sw()
    days = {}
    for v in (schedules or {}).values():
        if not v or v.get("held") or not v.get("send_after"):
            continue                                  # held: it goes on no day
        d = sw.local_day(v["send_after"], v["send_tz"])
        place = sw.place_name(v["send_tz"])
        days.setdefault(d, {})
        days[d][place] = days[d].get(place, 0) + 1
    return [{"day": d.isoformat(), "label": sw.day_label(d), "count": sum(p.values()),
             "places": [[k, n] for k, n in sorted(p.items(), key=lambda kv: (-kv[1], kv[0]))]}
            for d, p in sorted(days.items())]
