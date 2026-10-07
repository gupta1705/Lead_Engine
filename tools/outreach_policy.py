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
"""
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid

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

CHECK_SQL = """
select o.id, o.status, o.direction, o.subject, o.body, o.sequence_step,
       o.generated_hook, c.email, c.email_status,
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
        elif not r["email"] or not EMAIL_RE.match(r["email"].strip()):
            reason = "recipient address missing or malformed"
        elif r["email_status"] == "invalid":
            reason = "recipient failed verification"
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
    """Approve the checked drafts and record the batch. Returns (batch_id, approved)."""
    batch_id = str(uuid.uuid4())
    approved = 0
    if approve_ids:
        cur.execute(
            "update outreach set status = 'approved', approved_at = now(), approved_by = %s,"
            " approval_mode = 'batch', approval_batch = %s, spot_checked = (id = any(%s::uuid[])),"
            " updated_at = now()"
            " where id = any(%s::uuid[]) and status = 'drafted' and direction = 'outbound'",
            (user, batch_id, [str(s) for s in sample_ids], [str(a) for a in approve_ids]))
        approved = cur.rowcount
    cur.execute(
        "insert into outreach_approval_batches (id, segment_slug, approved_by, requested, approved, sample_ids, skipped)"
        " values (%s, %s, %s, %s, %s, %s::uuid[], %s::jsonb)",
        (batch_id, segment, user or "unknown", requested, approved, [str(s) for s in sample_ids], json.dumps(skipped)))
    return batch_id, approved


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
