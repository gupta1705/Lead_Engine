#!/usr/bin/env python3
"""outreach.py -- Phase F: drafts, sends, replies, triage.

THE ONE RULE THAT SHAPES EVERYTHING HERE: no email leaves this system without
a human having read THAT exact text and clicked approve. The commands are
deliberately separated so the dangerous one is small and auditable:

    draft    render personalised drafts for shortlisted leads   (see below)
    auth     one-time Gmail OAuth consent, done BY THE OWNER    (browser)
    send     send APPROVED drafts only, capped per run          (Gmail API)
    pull     fetch replies to sent threads                      (Gmail API)
    triage   classify fetched replies with Claude               (Anthropic API)

WHAT MAKES A SEND SAFE, layer by layer:
  * the database: one outbound row per entity, unique index (Invariant 5)
  * the row:      status must be 'approved' -- a state only the UI sets
  * the run:      daily_send_cap from config is a hard ceiling
  * the address:  refuses to send when the contact email failed verification
  * the identity: GMAIL_SENDER_ADDRESS comes from .env, never from config,
                  so a config typo cannot impersonate anyone
  * the moment:   with outreach.send_window, only from the email's own random
                  second until its window closes, 10:00-10:30 on its
                  recipient's clock -- checked by the claim and by the
                  database itself (sql/34, cmd_send)

THE ONE NETWORK CALL IN `draft`. A segment with outreach.generated_hook on lets
a model write the opening sentence from that lead's own facts (tools/llm.py).
It is the only outbound call the draft step makes, it needs GROQ_API_KEY, and
every way it can fail -- no key, no network, an answer that does not survive
the checks -- ends in the sentence the engine assembles itself. Drafting never
stops because a model had a bad day.

CREDENTIALS, and what happens without them. Gmail needs an OAuth client
(credentials in .env as GOOGLE_OAUTH_CLIENT_ID/SECRET) plus a one-time consent
in the owner's browser (`auth`). Triage needs ANTHROPIC_API_KEY. Every command
that lacks its credential exits with instructions, not a stack trace -- the
draft pipeline works TODAY with no credentials at all.
"""
import argparse
import base64
import io
import json
import os
import re
import sys
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# The segment this run works on. Segment 2 is meant to be "a config row and
# connectors, nothing else" -- so the slug comes from the environment, and
# every tool, the app, and the container agree on SEGMENT_SLUG.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
TOKEN_PATH = ROOT / ".gmail_token.json"          # gitignored, holds the refresh token
# Segment 3: a segment may name its own sender variable (config outreach.sender
# .email_env); load_outreach_config then points the token at a per-segment
# file / variable, so LCX never sends from TVF's mailbox or vice versa.
SENDER_ENV = "GMAIL_SENDER_ADDRESS"
TOKEN_ENV = "GMAIL_TOKEN_JSON"
MAILBOXES = []                                   # filled by load_outreach_config (outreach_policy.mailbox_list)
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def log(m):
    print(m, flush=True)


def env(name):
    v = os.environ.get(name)
    if v:
        return v
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_outreach_config(db):
    """The segment's outreach block, and its mailboxes. SENDER_ENV / TOKEN_*
    keep describing the first mailbox, which for a segment without rotation
    is exactly the single sender it always had."""
    global SENDER_ENV, TOKEN_ENV, TOKEN_PATH, MAILBOXES
    import outreach_policy as pol
    cfg = db.run(lambda cur: (cur.execute(
        "select config->'outreach' from segments where slug = %s", (SEGMENT,)),
        cur.fetchone())[1][0])
    if not cfg:
        sys.exit("config has no outreach block for segment %s" % SEGMENT)
    try:
        MAILBOXES = pol.mailbox_list(cfg, SEGMENT)
    except ValueError as e:
        sys.exit("config outreach.mailboxes is invalid: %s" % e)
    first = MAILBOXES[0]
    SENDER_ENV, TOKEN_ENV, TOKEN_PATH = first["email_env"], first["token_env"], ROOT / first["token_file"]
    return cfg


def mailbox_by_key(key):
    if not key:
        return MAILBOXES[0]
    for mb in MAILBOXES:
        if mb["key"] == key:
            return mb
    sys.exit("no mailbox %r in segment %s; it has: %s" % (key, SEGMENT, ", ".join(m["key"] for m in MAILBOXES)))


def mailbox_connected(mb):
    """Its address is set and its Gmail token is on this machine (file or variable)."""
    return bool(env(mb["email_env"])) and ((ROOT / mb["token_file"]).exists() or bool(env(mb["token_env"])))


# ------------------------------------------------------------------ draft
# How an email is personalised and how its footer is built now live in
# tools/draft_render.py, because the app renders the same emails when the
# footer changes. Importing the names keeps this file reading as it did.
from draft_render import build_context, pick_template, render_message  # noqa: E402
from mail_copy import has_forbidden_copy  # noqa: E402
from outreach_policy import OUT_TODAY_SQL, TAKEN_AT_SEND  # noqa: E402
from outreach_policy import DUPLICATE_SQL as _DUPLICATE_SQL  # noqa: E402
from outreach_policy import SELECTED_RECIPIENT_SQL, SELECTED_RECIPIENT_REASON  # noqa: E402
from recipient_selection import CONTACT_SELECTION_SQL, recipient_metadata  # noqa: E402


def cmd_draft(args):
    from dbconn import Db
    from lead_lifecycle import priority_order
    db = Db()
    cfg = load_outreach_config(db)
    requested = None
    if getattr(args, "template", None):
        requested = next((t for t in cfg["templates"] if t["key"] == args.template), None)
        if not requested:
            sys.exit("unknown template %r; segment %s has: %s"
                     % (args.template, SEGMENT, [t["key"] for t in cfg["templates"]]))
    openers = [t for t in cfg["templates"] if t.get("kind") != "follow_up"]
    if not openers and not requested:
        # a project whose first emails people write (Universal: only a follow-up template, 2026-10-23)
        log("no first-email templates in segment %s: its first emails are written by people" % SEGMENT)
        db.close(); return 0
    tpl = requested or next((t for t in openers if not t.get("when")), openers[0])
    sender = cfg["sender"]
    import outreach_policy as _pol
    if _pol.sender_unset(sender) and not args.dry_run:
        log("NOTE: sender.name / postal_address still say SET_ME in config.")
        log("      Drafts will render with those placeholders visible, which")
        log("      is safe -- approval will catch them -- but fix the config")
        log("      before anyone approves.\n")

    # Respect the recipient the reviewer chose; otherwise use the best-ranked
    # eligible contact. A stale choice holds the lead instead of changing who
    # receives it. The shared selector retains contact verification/rank checks.
    order = priority_order() if cfg.get("prioritize_fresh_leads") else "e.fit_score desc nulls last,e.created_at desc,e.id"
    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.metadata, c.id, c.full_name, c.email, c.source
        from entities e
        join lateral (""" + CONTACT_SELECTION_SQL + """) c on true
        where e.segment_id = (select id from segments where slug = %s)
          and e.status = 'shortlisted'
          and not exists (select 1 from outreach o
                          where o.entity_id = e.id and o.direction = 'outbound'
                            and o.status not in ('cancelled','failed'))
        order by """ + order + """ limit %s
    """, (SEGMENT, args.limit)), cur.fetchall())[1])

    if not rows:
        log("nothing to draft -- no shortlisted lead with a contact lacks a draft")
        db.close(); return 0

    log("drafting %d email(s) from template %s%s\n"
        % (len(rows), requested["key"] if requested else "auto (per-lead when-conditions)",
           "  [DRY RUN]" if args.dry_run else ""))

    import llm
    gen = llm.make_generator(cfg, log=log)
    part = ("the problem and solution lines" if llm.lcxs_policy(cfg) else
            "the paragraph about each company" if llm.partner_policy(cfg) else "the opening sentence")
    if gen:
        log("  %s is written by %s from each lead's own facts;" % (part, gen.policy["model"]))
        log("  one that fails the checks falls back to the built-in text\n")
    elif llm.policy(cfg) or llm.partner_policy(cfg) or llm.lcxs_policy(cfg):
        log("  GROQ_API_KEY is not set, so %s is the built-in one\n" % part)

    # the files a template attaches (LCX Services: the services deck), read and fingerprinted once a run;
    # a template whose file is missing drafts nothing, rather than emails that say "attached" and are not
    attach_cache = {}

    def files_for(t):
        if t["key"] not in attach_cache:
            attach_cache[t["key"]] = _pol.attachments_for(t)
        return attach_cache[t["key"]]

    made = skipped = 0
    for eid, company, meta, cid, cname, email, csource in rows:
        try:
            meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
            tpl = requested or pick_template(cfg, meta)
            # only a template that actually uses {{hook}} is worth a model call (LCX Services v3, 2026-10-13: its
            # {{problem}} and {{solution}} lines)
            use_gen = gen if any(p in (tpl.get("body") or "") for p in ("{{hook}}", "{{pitch}}", "{{problem}}")) \
                else None
            ctx = build_context(cfg, company, recipient_metadata(meta), cname, email, seed=eid, generator=use_gen,
                                contact_source=csource)
            # the production-house templates differ by whether the email greets a person by name
            tpl = requested or pick_template(cfg, meta, ctx)
            subject, body = render_message(tpl, ctx)
            files = files_for(tpl)
        except Exception as e:
            # one lead that cannot be drafted (a stray {{word}} in its site text, say) is skipped and
            # named; it used to stop the run, and every lead after it went undrafted (2026-09-21)
            skipped += 1
            log("  %-32s SKIPPED: could not draft it: %s" % (company[:32], str(e)[:120]))
            continue
        written = ctx.get("generated_hook") or None
        log("  %-32s -> %-34s [%s]%s%s" % (company[:32], email, tpl["key"],
                                           "  written" if written else "",
                                           ("  + " + ", ".join(f["name"] for f in files)) if files else ""))
        if args.dry_run:
            continue
        # outreach.service (sql/35, 2026-10-13): the one service an LCX Services email pitched, a record of what was
        # sold to whom; NULL for every other project's email
        def save_draft(cur):
            # Rendering may take time. Serialize with a reviewer changing the
            # recipient, then recheck their latest choice before saving it.
            cur.execute("select id from entities where id = %s for update", (eid,))
            cur.execute(
                "insert into outreach (entity_id, contact_id, template_key, subject, body,"
                " generated_hook, attachments, service)"
                " select %s, %s, %s, %s, %s, %s, %s, %s"
                " from entities e join lateral (" + CONTACT_SELECTION_SQL + ") c on true"
                " where e.id = %s and e.status = 'shortlisted' and c.id = %s"
                " and lower(btrim(c.email)) = lower(btrim(%s))"
                " and (select config#>>'{outreach,reelforge_templates}' from segments where id=e.segment_id)"
                " is not distinct from %s"
                " on conflict do nothing returning id",
                (eid, cid, tpl["key"], subject, body, written, json.dumps(files) if files else None,
                 ctx.get("lead_service"), eid, cid, email, cfg.get("reelforge_templates")))
            return cur.fetchone() is not None

        if not db.run(save_draft):
            skipped += 1
            log("  %-32s SKIPPED: recipient/lead changed or an email already exists" % company[:32])
            continue
        made += 1

    db.close()
    if gen:
        st = gen.stats
        log("\n  model: %d written, %d rejected, %d unavailable, %d with nothing specific to say"
            % (st["ok"], st["rejected"], st["failed"], st["skipped"]))
        if st["ok"]:
            log("  written drafts are approved one at a time unless the segment's"
                " batch_approval.allow_generated says otherwise")
    log("\n%d draft(s) created%s. Review and approve them in the UI (Outreach tab)"
        % (made, (", %d lead(s) skipped -- see above" % skipped) if skipped else ""))
    return 0


def cmd_followups(args):
    """Draft the follow-ups that are due, for segments with outreach.follow_ups
    on. Rules in tools/outreach_policy.py; the drafts go through approval like
    any other email, and the database refuses to send one after a reply."""
    import datetime as dt
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    try:
        steps = pol.followup_steps(cfg)
    except ValueError as e:
        sys.exit("config outreach.follow_ups is invalid: %s" % e)
    if not steps:
        log("follow-ups are off for segment %s (config outreach.follow_ups)" % SEGMENT)
        db.close(); return 0
    tpls = {t["key"]: t for t in cfg["templates"]}
    now = dt.datetime.now(dt.timezone.utc)
    due = db.run(lambda cur: pol.due_followups(cur, SEGMENT, steps, now))
    if not due:
        log("no follow-ups due"); db.close(); return 0
    log("%d follow-up(s) due%s\n" % (len(due), "  [DRY RUN]" if args.dry_run else ""))
    made = 0
    for row, step in due[:args.limit]:
        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        company = row["company"]
        tpl = tpls[step["template"]]
        try:
            ctx = build_context(cfg, company, meta, row["full_name"], row["email"],
                                seed=row["entity_id"], opener_subject=row["opener_subject"])
            if row.get("opener_service"):
                # LCX Services: the service its first email pitched (sql/35), not whatever the lead is tagged with now
                ctx["lead_service"] = row["opener_service"]
                ctx.pop("draft_hold", None)
            subject, body = render_message(tpl, ctx)
        except ValueError as e:
            # 2026-10-13: a follow-up whose opener's subject is over outreach.subject_max_words cannot be shortened
            # without leaving the opener's Gmail thread, and may not ship longer, so it is not drafted; named, and
            # the run carries on with the rest
            log("  %-32s step %d SKIPPED: could not draft it: %s" % (company[:32], step["step"], str(e)[:120]))
            continue
        log("  %-32s step %d -> %-34s %s" % (company[:32], step["step"], row["email"], subject[:40]))
        if args.dry_run:
            continue
        new = db.run(lambda cur, _r=row, _s=step, _k=tpl["key"], _sub=subject, _b=body:
                     pol.insert_followup(cur, _r, _s["step"], _k, _sub, _b))
        made += 1 if new else 0
    db.close()
    log("\n%d follow-up draft(s) created. Approve them in the Outreach tab (Follow-ups)." % made)
    return 0


# ------------------------------------------------------------------- gmail
def gmail_service(mb=None):
    """A Gmail client for one mailbox (the first one when none is named)."""
    cid = env("GOOGLE_OAUTH_CLIENT_ID")
    csec = env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not csec:
        sys.exit(
            "Gmail is not configured yet.\n"
            "  1. console.cloud.google.com -> APIs & Services -> enable Gmail API\n"
            "  2. Credentials -> Create OAuth client ID -> Desktop app\n"
            "  3. put GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env\n"
            "  4. run: python tools/outreach.py auth --mailbox <key>   (one-time browser consent per mailbox)")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-api-python-client google-auth-oauthlib")
    # The token lives in a file on a machine with a disk. A cloud host with an
    # ephemeral filesystem gets it through the mailbox's token variable
    # instead: run `auth` once on a laptop, paste the file's contents there.
    token_path = (ROOT / mb["token_file"]) if mb else TOKEN_PATH
    token_env = mb["token_env"] if mb else TOKEN_ENV
    token_json = env(token_env)
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), GMAIL_SCOPES)
    elif token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json), GMAIL_SCOPES)
    else:
        sys.exit("no Gmail token for mailbox %s yet -- run: SEGMENT_SLUG=%s python tools/outreach.py auth --mailbox %s"
                 " (on a diskless host, set %s instead)"
                 % ((mb or MAILBOXES[0])["key"] if (mb or MAILBOXES) else "default", SEGMENT,
                    (mb or MAILBOXES[0])["key"] if (mb or MAILBOXES) else "default", token_env))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        try:
            token_path.write_text(creds.to_json())
        except OSError:
            pass    # read-only or ephemeral disk: the refresh token in the env still works
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def user_gmail_service(db, box):
    """A Gmail client for an address a person connected in the app (tools/mailbox_store.py). The sign-in
    is only readable where it was saved -- the server -- and a refreshed access token is kept."""
    import mailbox_store as store
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-api-python-client google-auth-oauthlib")
    info = store.credentials(box)
    if not info:
        raise RuntimeError("the saved sign-in for %s cannot be read here; connect it again in the app" % box["address"])
    creds = Credentials.from_authorized_user_info(info, [store.GMAIL_SCOPE])
    if not creds.valid:
        creds.refresh(Request())
        db.run(lambda cur: store.update_token(cur, box["id"], json.loads(creds.to_json())))
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def cmd_auth(args):
    """One-time browser consent for one mailbox of the segment."""
    from dbconn import Db
    db = Db()
    load_outreach_config(db)
    db.close()
    mb = mailbox_by_key(getattr(args, "mailbox", None))
    cid = env("GOOGLE_OAUTH_CLIENT_ID")
    csec = env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not csec:
        return gmail_service(mb)          # prints the setup instructions and exits
    addr = env(mb["email_env"])
    if not addr:
        sys.exit("set %s in .env to the address of mailbox %s first" % (mb["email_env"], mb["key"]))
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("pip install google-auth-oauthlib google-api-python-client")
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": cid, "client_secret": csec,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token",
                       "redirect_uris": ["http://localhost"]}},
        GMAIL_SCOPES)
    token_path = ROOT / mb["token_file"]
    log("A browser window will open. Sign in as %s (mailbox %s of segment %s) and" % (addr, mb["key"], SEGMENT))
    log("approve. The token lands in %s (gitignored). For a cloud host with" % token_path.name)
    log("no disk, paste that file's contents into %s." % mb["token_env"])
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    log("token saved -- mailbox %s now takes part in sending and reply pulls" % mb["key"])
    return 0


def cmd_mailboxes(args):
    """Each mailbox: address, token, warm-up, today's cap, sends, room left."""
    import datetime as dt
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    today = dt.datetime.now(dt.timezone.utc).date()
    status = db.run(lambda cur: pol.mailbox_status(cur, SEGMENT, MAILBOXES, today))
    db.close()
    log("segment %s: %d mailbox(es), segment ceiling %d emails a day%s\n"
        % (SEGMENT, len(status), int(cfg.get("daily_send_cap", 20)),
           "" if cfg.get("mailboxes") else " (single mailbox, no rotation)"))
    log("  %-10s %-42s %-6s %-14s %5s %5s %5s" % ("mailbox", "address", "token", "warm-up", "cap", "sent", "left"))
    for st in status:
        addr = env(st["email_env"]) or "(set %s)" % st["email_env"]
        tok = "yes" if ((ROOT / st["token_file"]).exists() or env(st["token_env"])) else "no"
        if not st["enabled"]:
            warm = "disabled"
        elif not st["warmup"]:
            warm = "none"
        elif st["warmup_day"]:
            warm = "day %d" % st["warmup_day"]
        else:
            warm = "not started"
        log("  %-10s %-42s %-6s %-14s %5d %5d %5d" % (st["key"], addr[:42], tok, warm,
                                                    st["cap_today"], st["sent_today"], st["remaining"]))
    return 0


def _message(body, attachments=None):
    """The email as Gmail receives it: the text, and each attached file (outreach.attachments) as
    itself -- application/pdf for the LCX Services deck -- named as it was approved."""
    if not attachments:
        return MIMEText(body)
    import mimetypes
    import outreach_policy as pol
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart("mixed")
    msg.attach(MIMEText(body))
    for a in attachments:
        kind = (mimetypes.guess_type(a["name"])[0] or "application/octet-stream").split("/", 1)
        part = MIMEApplication(pol.attachment_bytes(a), _subtype=kind[1] if kind[0] == "application" else "octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=a["name"])
        msg.attach(part)
    return msg


# The sending window (owner, 2026-10-12: "send mails to the sender's time region between 10 to 10:30AM and
# that must be randmized not like all mail going at 10:15 some must be going at 10:17 some at 10:13"). Each
# approved email of a project with outreach.send_window holds its own second, send_after, inside its
# recipient's 10:00-10:30 (tools/outreach_policy.schedule_sends); these are what the sender adds for it.
#
# What is due: an email inside its own window. One with no time is never sent by a timed project (the
# settle at the start of every run gives it one), and in an untimed project an email that somehow holds a
# time still keeps it -- so the claim below can never trip sql/34's guard, which refuses a claim outside it.
PICK_SQL = """
select o.id, o.entity_id, o.subject, o.body,
       c.email, c.email_status, e.name, e.status as ent_status,
       contact_allowed(e.id,c.source,c.verifier,c.email_status) as verified_allowed,
       """ + SELECTED_RECIPIENT_SQL + """ as selected_recipient_matches,
       (coalesce(s.config#>>'{sourcing,contacts}','') <> 'apollo' or not (s.config ? 'lead_service') or coalesce(o.sequence_step,0)>0 or
        (o.service is not null and o.service=coalesce(e.metadata#>>'{lead_service,service}',e.metadata#>>'{lead_service,name}'))) as service_matches,
       o.sequence_step, p.gmail_thread_id, p.stopped_reason,
       (select s.gmail_message_id from outreach s
         where (s.id = o.parent_id or s.parent_id = o.parent_id)
           and s.direction = 'outbound' and s.status = 'sent'
           and s.sequence_step < o.sequence_step
         order by s.sequence_step desc limit 1) as prev_message_id,
       exists (select 1 from outreach r where r.entity_id = o.entity_id
                and r.direction = 'inbound' and r.triage is distinct from 'neutral') as replied,
       p.sender_mailbox as parent_mailbox, lower(o.approved_by) as approver, o.attachments,
       o.send_after, o.send_before, o.send_tz, p.sent_as as parent_sent_as,
       -- who it is copied to (sql/39): as approved; a row approved before that file gets the project's default
       coalesce(o.cc, array(select lower(btrim(x)) from jsonb_array_elements_text(
                coalesce(s.config #> '{outreach,default_cc}', '[]'::jsonb)) as x where btrim(x) <> '')) as cc
from outreach o
join entities e on e.id = o.entity_id
join segments s on s.id=e.segment_id
left join contacts c on c.id = o.contact_id
left join outreach p on p.id = o.parent_id
where o.status = 'approved' and o.direction = 'outbound'
  and o.send_error is null
  and e.segment_id = (select id from segments where slug = %(segment)s)
  and (case when o.send_after is null then not %(timed)s
            else o.send_after <= clock_timestamp() and clock_timestamp() < o.send_before end)
order by (o.sequence_step > 0) desc, o.send_after nulls first, o.created_at limit %(n)s
"""
# The claim: atomic, committed before Gmail is touched, and -- for an email with a time -- only inside its
# window, on the database's clock (the same clock sql/34's guard reads).
CLAIM_SQL = """
update outreach set status = 'sending', sender_mailbox = %s, sender_address = %s, updated_at = clock_timestamp()
where id = %s and status = 'approved'
  and exists (select 1 from contacts c join entities e on e.id=outreach.entity_id
              where c.id=outreach.contact_id
                and contact_allowed(c.entity_id,c.source,c.verifier,c.email_status)
                and """ + SELECTED_RECIPIENT_SQL + """)
  and (send_after is null or (send_after <= clock_timestamp() and clock_timestamp() < send_before))
returning sender_mailbox
"""
# Seconds since an address last sent, or may have: its last 'sent' row, or a send in flight or of unknown
# outcome. Read inside the claim's lock, so two runs never put two emails from one address closer than the
# gap (min_gap_seconds): a dense window never bursts.
GAP_SQL = """
select extract(epoch from clock_timestamp() - greatest(
  (select max(sent_at) from outreach where direction = 'outbound' and sender_address is not null
     and lower(sender_address) = lower(%(a)s) and status = 'sent'),
  (select max(updated_at) from outreach where direction = 'outbound'
     and lower(sender_address) = lower(%(a)s) and status in ('sending', 'send_unknown'))))
"""
# What a run staying on (--stay) waits for: an email whose moment comes within the stay, its window still open
SOON_SQL = """
select o.id, coalesce(o.sequence_step, 0) as sequence_step, lower(o.approved_by) as approver,
       p.sender_mailbox as parent_mailbox, extract(epoch from o.send_after - clock_timestamp()) as wait
from outreach o
join entities e on e.id = o.entity_id
left join outreach p on p.id = o.parent_id
where o.status = 'approved' and o.direction = 'outbound' and o.send_error is null
  and e.segment_id = (select id from segments where slug = %(segment)s)
  and o.send_after <= clock_timestamp() + make_interval(secs => %(stay)s)
  and o.send_before > clock_timestamp() + interval '5 seconds'
order by o.send_after
"""


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(r) if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


def _due_text(at, zone):
    """"10:13:41 New York time": the moment an email was due, on its recipient's clock (the log)."""
    from zoneinfo import ZoneInfo
    import send_window as sw
    loc = sw._utc(at).astimezone(ZoneInfo(zone or "UTC"))
    return "%s %s time" % (loc.strftime("%H:%M:%S"), sw.place_name(zone) if zone else "UTC")


def on_the_server():
    """Is this the machine that sends: SEND_LOOP_ENABLED=1, which only the server deploys set (render.yaml,
    deploy/render.lcx-clipping.yaml, docker-compose.prod.yml, the Hugging Face Space's variables)? Review,
    2026-10-12: a sign-in the SERVER cannot read means its SESSION_SECRET changed or the row is damaged, and
    the owner must see "connect it again" at once, as before the sending window existed; on any other machine
    (the laptop, whose secret differs by design) it is simply the server's to send. Read from the process's
    own environment only, never .env: nothing in a laptop's .env may make a terminal run mark the server's
    addresses.
    Second review, 2026-10-12: SCHEDULER_ENABLED=1 no longer counts. docker-compose.yml turns the scheduler on
    for the laptop's own Docker stack too, which reaches the live database with the laptop's SESSION_SECRET;
    its first send would have marked every person's address "connect it again", and the server would then have
    held every email until the owner linked each address again. That stack now says SEND_LOOP_ENABLED=0."""
    return str(os.environ.get("SEND_LOOP_ENABLED") or "").strip().lower() in ("1", "true", "yes")


# The last line of every send run: what it did, for the app's send loop (app/scheduler.py), which reads it
# from the run's log to alert once and to know which due emails this machine could do nothing with
SUMMARY_TAG = "SEND-SUMMARY "


def _http_code(e):
    code = getattr(getattr(e, "resp", None), "status", None)
    return int(code) if str(code or "").isdigit() else None


def _rate_limited(e):
    """Is a Gmail 403 a rate or quota limit (rateLimitExceeded, userRateLimitExceeded, dailyLimitExceeded,
    quotaExceeded), a passing thing, rather than the address losing its permission? Read from what the error
    carries: googleapiclient's HttpError keeps Google's reason in error_details, reason and content."""
    text = " ".join(str(getattr(e, k, "") or "") for k in ("error_details", "reason", "content")) + " " + str(e)
    text = text.lower().replace(" ", "")
    return any(w in text for w in ("ratelimit", "quota", "dailylimit", "limitexceeded"))


def thread_unread(db, svc, thread_id, own):
    """Does a follow-up's thread hold a message from them the app has not read yet? The hourly pull reads
    replies, and a follow-up timed for 10:13 can fall between a reply landing and the pull reading it: one
    look at the thread first (owner's rule: a reply stops the sequence). Anything the app already holds as
    an auto-reply (triage neutral) lets the follow-up go, as the pull would.
    own: every address of ours (the project's mailboxes and every address linked in the app) -- a message from
    a colleague's address in the thread is ours, as cmd_pull counts it, never a reply waiting to be read
    (review, 2026-10-12). -> (True | False, None), or (None, the error) when the thread cannot be read: the
    sender decides what that means, so one unreadable thread can never hold its follow-up back for ever."""
    try:
        t = svc.users().threads().get(userId="me", id=thread_id, format="metadata",
                                      metadataHeaders=["From"]).execute()
        theirs = []
        for m in t.get("messages", []) or []:
            if {"SENT", "DRAFT"} & set(m.get("labelIds") or []):
                continue                                        # ours, or not yet sent by anyone
            hdrs = {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers", [])}
            frm = (hdrs.get("from") or "").lower()
            if any(a and a in frm for a in own):
                continue                                        # ours, from another of our addresses
            theirs.append(m["id"])
        if not theirs:
            return False, None
        known = db.run(lambda cur: (cur.execute(
            "select gmail_message_id from outreach where direction = 'inbound' and triage = 'neutral'"
            " and gmail_message_id = any(%s)", (theirs,)), [r[0] for r in cur.fetchall()])[1])
        return bool(set(theirs) - set(known)), None
    except Exception as e:                                      # noqa: BLE001 -- the caller says what it means
        return None, e


def cmd_send(args):
    """Send approved drafts, spread across the segment's mailboxes.

    THE PROTOCOL, in order, per row:
      1. PICK   an opener goes to the connected mailbox with the most room left
                today (each mailbox has its own cap and warm-up ramp); a
                follow-up waits for the mailbox that sent its opener.
      2. CLAIM  update ... set status='sending', sender_mailbox=... where
                status='approved' -- atomic, committed BEFORE Gmail is
                touched. For a follow-up the database refuses the claim after
                a reply or a stop, and overwrites the mailbox with the
                opener's (sql/23, sql/24); the send uses the mailbox the claim
                RETURNS, so a follow-up can only leave from its thread's mailbox.
      3. SEND   the Gmail call from that mailbox. A follow-up goes into the
                opener's thread with In-Reply-To / References set.
      4. RECORD success -> 'sent'. ANY exception -> 'send_unknown': a timeout
                after Gmail accepted is indistinguishable from a failure.

    CAPS: each mailbox's cap for today (warm-up included), and the segment's
    daily_send_cap across all of them. Emails sent today count against both.

    VALIDATION before claiming: one well-formed recipient, no unfilled
    {{placeholders}}, company still sendable. A follow-up whose company has
    replied, moved on, or whose thread was stopped is CANCELLED with the reason.

    THE SENDING WINDOW (outreach.send_window; owner, 2026-10-12). Each approved email holds its own second
    inside its recipient's 10:00-10:30 (send_after, sql/34), and goes then, not before:
      * every run first settles the times (outreach_policy.settle_schedule): one approved with no time gets
        one, one whose window passed unsent moves to the next window at a new random second, and a window
        turned off in the config clears them all, so the project sends as it did before
      * only an email inside its own window is picked, and the claim checks the window again on the
        database's clock; sql/34's trigger refuses any claim outside it, whoever makes it
      * never two from one address closer than min_gap_seconds (checked inside the claim's lock): the email
        tries the approver's other addresses, then waits out the gap in this run
      * an email that cannot go in its window -- its address at its daily limit, no address linked, Gmail
        refusing the address, an unread reply in its thread -- is moved to its next window with the reason
        (outreach_policy.defer_rows), never sent late in the afternoon. Gmail refusing an address is then
        handled, not a failed run (review, 2026-10-12): the run ends 0 and its last line (SUMMARY_TAG) names
        the address, so the send loop alerts once instead of holding every other address of the project
      * a sign-in this machine cannot read (sealed for the server) leaves its emails untouched, for the
        server; on the server itself (on_the_server) it is marked "connect it again", as it always was --
        but when none of several can be read there, the run fails loudly and marks nothing: that is the
        machine's SESSION_SECRET, not every row damaged at once (second review, 2026-10-12)
      * a pool mailbox whose token is on another machine, with room left today, leaves its share of the
        emails to that machine rather than calling every mailbox full
      * --stay N keeps the run going while the next email's moment is under N seconds away (the app's send
        loop, app/scheduler.py), up to --max-seconds
    A project without the block sends exactly as before: no times, no gap, no waiting.
    """
    import datetime as dt
    import time as _time
    import outreach_policy as pol
    import send_window as sw
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    paused = pol.sending_paused(cfg)
    try:
        wcfg = sw.window_cfg(cfg)
    except ValueError as e:
        db.close()
        sys.exit("config outreach.send_window is invalid: %s" % e)
    timed = wcfg is not None
    stay = max(0, int(getattr(args, "stay", 0) or 0)) if timed else 0
    max_seconds = max(1, int(getattr(args, "max_seconds", 900) or 900))
    started = _time.monotonic()
    # the times first, paused or not: a pause moves each missed window on ("sending is paused"), so the
    # day it is lifted nothing goes out late
    st = db.run(lambda cur: pol.settle_schedule(cur, SEGMENT, cfg, paused=bool(paused)))
    if any(st[k] for k in ("cleared", "scheduled", "replanned", "moved")):
        log("sending window: %d given a time, %d placed again (the window changed), %d moved to their next window,"
            " %d times cleared (the window is off)" % (st["scheduled"], st["replanned"], st["moved"], st["cleared"]))
    if st["alert_ids"]:
        log("  %d email(s) have missed %d windows unsent: see Outreach -> Approved"
            % (len(st["alert_ids"]), pol.MISSES_TO_ALERT))
    # what this run did, for its last line (SUMMARY_TAG): the app's send loop alerts from it once, and does not
    # start another run for due emails this machine could do nothing with (left_alone)
    counts = {"deferred": 0, "parked": 0, "cancelled": 0}
    alert_ids = list(st["alert_ids"])
    signin_failed, refused, left_alone = [], {}, set()
    mbmap, sent = {}, 0
    approver_mode = cfg.get("send_from") == "approver"
    # a project that writes as another brand (owner, 2026-10-15, LCX: "We can't login from LCX wala mail because
    # it's an extension"): the approver's Gmail account sends, with its "Send mail as" alias on this domain in
    # the From line (sql/36). An approver whose account has no such alias waits, saying so: an LCX email never
    # goes out from a TVF address. The account's own daily limit and gap count, as Gmail counts them.
    as_domain = (str(cfg.get("send_as_domain") or "").strip().lower().lstrip("@") or None) if approver_mode else None

    def finish(rc=0):
        """Every way out of a run after the settle: Gmail's refusals said once, and the summary line."""
        db.close()
        if signin_failed:
            # a failed step is what raises the alert and shows on Operations: sign in again with
            # `python tools/outreach.py auth`, then update the mailbox's token variable on the server
            failed = list(dict.fromkeys(signin_failed))
            if approver_mode:
                log("Gmail refused %s (sign-in, permission or a limit). If it is the sign-in, its person connects it"
                    " again in the app (account menu, Your Gmail), or the owner links it: python tools/users.py gmail"
                    " <login>." % ", ".join(failed))
            else:
                log("Gmail refused mailbox(es) %s (sign-in, permission or a limit). If it is the sign-in: run"
                    " `python tools/outreach.py auth`, then update %s on the server"
                    % (", ".join(failed), ", ".join(mbmap[k]["token_env"] for k in failed if k in mbmap)))
            if timed:
                # handled (review, 2026-10-12): each of that address's emails moved to its next window with the
                # reason, and the other addresses carried on. A failed run would hold the whole project back
                # (the send loop backs off after a crash), so it ends 0 and the loop alerts from the summary
                log("  its emails moved to their next window, saying why; the run itself did not fail")
            else:
                rc = rc or 1
        log(SUMMARY_TAG + json.dumps({
            "sent": sent, "deferred": counts["deferred"], "parked": counts["parked"],
            "cancelled": counts["cancelled"], "left_alone": sorted(left_alone),
            "refused": {k: refused.get(k) or "Gmail refused %s" % k for k in dict.fromkeys(signin_failed)},
            "alert_ids": list(dict.fromkeys(alert_ids))}, sort_keys=True))
        return rc

    if paused:
        # not a failure: approved emails wait in Approved until the pause is lifted in the config
        log("not sending for %s: %s (config outreach.sending_paused)" % (SEGMENT, paused))
        return finish(0)
    if pol.sender_unset(cfg.get("sender")):
        sys.exit("refusing to send: config outreach.sender still contains SET_ME")

    def pick(n):
        return db.run(lambda cur: (cur.execute(PICK_SQL, {"segment": SEGMENT, "timed": timed, "n": max(1, n)}),
                                   _rows(cur))[1])

    def hold(ids, why, company=""):
        """Due emails that cannot go in this run. With a window: moved to their next window at a new random
        second, saying why (outreach_policy.defer_rows). Without one they wait, as they always did. Either
        way this run is done with them (left_alone): one that could not be moved is not picked again."""
        ids = [str(i) for i in ids if i]
        if not ids:
            return
        left_alone.update(ids)
        if timed:
            again = []
            n = db.run(lambda cur: pol.defer_rows(cur, ids, cfg, SEGMENT, why, alerts=again))
            counts["deferred"] += n
            alert_ids.extend(again)                    # moved MISSES_TO_ALERT times: the owner is told
            log("  %-32s moved to the next window (%d): %s" % (company[:32] if company else "", n, why))
        else:
            log("  %-32s waits: %s" % (company[:32] if company else "", why))

    # Two ways a project sends. The pool (LCX): the project's own mailboxes, from .env / Render, the one
    # with the most room first. From the approver (owner, 2026-09-26; US Production Houses): the Gmail of
    # the person who approved the email, connected by them in the app (tools/mailbox_store.py), each
    # address with its own daily limit -- nobody's approval goes out from somebody else's address.
    by_owner, boxes_of, foreign_owners, names, box_of = {}, {}, set(), {}, {}
    room = None                                         # the project's own ceiling today (the pool)
    db_room = {}                                        # the pool: every enabled mailbox's room today, by the database
    order, connected = [], {}

    def thread_box_why(mb):
        """Why a follow-up's thread address (or pool mailbox) cannot send, by the database or the config --
        true on every machine -- or None when it can, here or on the machine that holds its sign-in."""
        if approver_mode:
            b = box_of.get(mb or "")
            if b is None:
                return "the thread's address %s is no longer linked to anyone" % mb
            if not b["enabled"]:
                return "the thread's address %s is switched off" % mb
            if b["last_error"]:
                return "the thread's address %s needs connecting again" % mb
            return None
        if mb not in mbmap:
            return "the thread's mailbox %s is no longer in the project's config" % mb
        if not mbmap[mb]["enabled"]:
            return "the thread's mailbox %s is switched off in the config" % mb
        return None

    def foreign(r):
        """An email this machine leaves alone, untouched: its thread's mailbox, or every sign-in its
        approver has, is readable only elsewhere (the server; another machine with the pool's token). One
        whose address the database says cannot send is not foreign: it moves, saying why, on any machine."""
        if int(r["sequence_step"] or 0) > 0:
            mb = r["parent_mailbox"] or (order[0] if order else None)
            return mb not in connected and mb not in refused and thread_box_why(mb) is None
        return approver_mode and (r["approver"] or "") in foreign_owners

    def elsewhere():
        """The pool: enabled mailboxes whose token is not on this machine, with room left today by the
        database's count -- the emails this machine cannot send are theirs, not "every mailbox is full"."""
        return [k for k, left in db_room.items() if left > 0 and k not in connected and k not in refused]

    if approver_mode:
        import mailbox_store as store
        boxes = db.run(lambda cur: store.mailboxes(cur, with_token=True))
        box_of = {b["address"].lower(): b for b in boxes}
        server = on_the_server()
        # A sign-in sealed for the server cannot be read on a laptop: that address is the server's to send
        # from. It used to be tried here, fail, and be marked "connect it again" by a run that never could.
        # On the server (on_the_server) one that cannot be read is damaged: marked, as it always was -- unless
        # none of several can, which is the machine's secret, not the rows (below).

        def readable_here(b):
            try:
                return store.credentials(b) is not None
            except Exception:                           # noqa: BLE001 -- no secret or library here
                if server:
                    raise                               # on the server that is a crash the owner hears of
                return False
        readable, unreadable = [], []
        for b in boxes:
            if b["usable"]:
                (readable if readable_here(b) else unreadable).append(b)
        if server and unreadable and not readable and len(unreadable) >= 2:
            # Not one of several can be opened (second review, 2026-10-12): that is this machine's SESSION_SECRET,
            # not every row damaged at once -- a deployment told it is the server that is not (a Hugging Face
            # Space or a second portal, each with its own secret), or a secret that changed. Marking each one
            # would make the owner link every address again for a setting; nothing is marked, the run fails
            # loudly (Operations, the alert) and the emails wait untouched.
            log("none of the %d saved sign-ins can be read here: this server's SESSION_SECRET is not the one they"
                " were sealed for (another deployment's, or it changed). Nothing was marked. Put the right"
                " SESSION_SECRET back, or link each address again (python tools/users.py gmail <login>)."
                % len(unreadable))
            if timed:
                left_alone.update(str(r["id"]) for r in pick(args.limit))
            return finish(1)
        for b in unreadable if server else []:
            why = ("sign-in: the saved sign-in for %s cannot be read on the server; connect it again in the"
                   " app (python tools/users.py gmail <login>)" % b["address"])
            db.run(lambda cur, _b=b, _w=why: store.mark_error(cur, _b["id"], _w))
            b.update(usable=False, last_error=why)
            signin_failed.append(b["address"].lower())
            refused[b["address"].lower()] = "Gmail sign-in for %s cannot be read on the server" % b["address"]
            log("  mailbox %s: its saved sign-in cannot be read on the server -- marked to connect again"
                % b["address"])
        usable = [b for b in boxes if b["usable"]]
        connected = {b["address"].lower(): b["address"].lower() for b in readable}
        mbmap = {b["address"].lower(): b for b in readable}
        order = [b["address"].lower() for b in readable]
        remaining = {b["address"].lower(): b["remaining"] for b in readable}
        for b in boxes:
            boxes_of.setdefault(b["user_email"].lower(), []).append(b)
            if b["address"].lower() in connected:
                by_owner.setdefault(b["user_email"].lower(), []).append(b["address"].lower())
            log("  mailbox %-40s %-5s %-30s cap %3d, %3d out today, %3d left" % (
                b["address"], "on" if b["usable"] else "off", b["user_email"], b["daily_cap"], b["out_today"],
                remaining.get(b["address"].lower(), 0)))
            if b["usable"] and b["address"].lower() not in connected:
                log("    its sign-in cannot be read on this machine; left for the server")
        foreign_owners = {b["user_email"].lower() for b in usable} - set(by_owner)
        names = dict(db.run(lambda cur: (cur.execute("select lower(email), name from app_users"),
                                         [(r[0], r[1]) for r in cur.fetchall()])[1]))
        daily_cap = None
        sent_today = sum(b["sent_today"] for b in boxes)
        if not usable:
            # not a failure: approved emails wait in Approved until their approver connects a Gmail
            relink = any(b["enabled"] and b["last_error"] for b in boxes)
            log("no sending address can send: approved emails wait (each person connects their Gmail in the app,"
                " or the owner runs tools/users.py gmail <login>)")
            if timed:
                due = pick(args.limit)
                hold([r["id"] for r in due], "every sending address needs connecting again" if relink
                     else "no sending address is linked yet", "%d due" % len(due))
            return finish(0)
        if not readable:
            log("every sign-in is the server's: nothing is sent from this machine")
            if timed:
                left_alone.update(str(r["id"]) for r in pick(args.limit))
            return finish(0)
        budget = min(sum(remaining.values()), args.limit)
        if budget <= 0 and not timed:
            log("nothing can go today: every connected Gmail is at its daily limit")
            return finish(0)
        # with a window, each due email is looked at even so: each moves to its next window with its own
        # reason (this person's address at its limit, that one with no address at all)
    else:
        connected = {mb["key"]: env(mb["email_env"]).strip() for mb in MAILBOXES
                     if mb["enabled"] and mailbox_connected(mb)}
        if not connected:
            sys.exit("no mailbox is connected for segment %s. For each mailbox, set its address in .env (%s)\n"
                     "and run: SEGMENT_SLUG=%s python tools/outreach.py auth --mailbox <key>"
                     % (SEGMENT, ", ".join(mb["email_env"] for mb in MAILBOXES), SEGMENT))
        mbmap = {mb["key"]: mb for mb in MAILBOXES}
        today = dt.datetime.now(dt.timezone.utc).date()
        status = db.run(lambda cur: pol.mailbox_status(cur, SEGMENT, MAILBOXES, today))
        order = [st_["key"] for st_ in status]
        remaining = {st_["key"]: (st_["remaining"] if st_["key"] in connected else 0) for st_ in status}
        # Every enabled mailbox's room by the database, wherever its token is (review, 2026-10-12): one not
        # connected HERE is not full. This machine's mailboxes at their cap leave the rest for the machine
        # holding the others' tokens; "every mailbox was at its daily limit" is said only when it is true.
        db_room = {st_["key"]: st_["remaining"] for st_ in status if st_["enabled"]}
        for st_ in status:
            log("  mailbox %-10s %-5s cap %3d today, %3d sent, %3d left" % (
                st_["key"], "on" if st_["key"] in connected else "off", st_["cap_today"], st_["sent_today"],
                remaining[st_["key"]]))

        daily_cap = int(cfg.get("daily_send_cap", 20))
        sent_today = sum(st_["sent_today"] for st_ in status)
        budget = min(max(0, daily_cap - sent_today), sum(remaining.values()), args.limit)
        room = max(0, daily_cap - sent_today)           # the project's own ceiling today, whoever sends
        if budget <= 0:
            log("nothing can go today: segment %d/%d sent, connected mailboxes have %d left"
                % (sent_today, daily_cap, sum(remaining.values())))
            if timed:
                picked = pick(args.limit * 3)
                due = [r for r in picked if not foreign(r)]
                # the ones another machine sends (their thread's mailbox is there) are left alone too, and said so:
                # the send loop starts no new run for them every few seconds (second review, 2026-10-12)
                left_alone.update(str(r["id"]) for r in picked if foreign(r))
                if room > 0 and elsewhere():
                    left_alone.update(str(r["id"]) for r in due)
                    log("  %d due: left for the machine holding mailbox(es) %s, which have room today"
                        % (len(due), ", ".join(elsewhere())))
                else:
                    hold([r["id"] for r in due], "the project's daily limit of %d was reached" % daily_cap
                         if room <= 0 else "every mailbox was at its daily limit", "%d due" % len(due))
            return finish(0)

    email_re = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
    services, by_box = {}, {}
    # without a window the run stops at the day's room, as it always did; with one each due email is looked
    # at, so the ones that cannot go move to their next window with their own reason
    stop_at = args.limit if timed else budget
    own_cache = []                  # every address of ours, for a follow-up's look at its thread

    def own_addresses():
        if not own_cache:
            import mailbox_store as store_
            got = {a.strip().lower() for a in (env(mb["email_env"]) for mb in MAILBOXES) if a}
            for b in db.run(lambda cur: store_.mailboxes(cur)):
                got.add(b["address"].lower())
                got |= {a["address"] for a in (b.get("send_as") or []) if isinstance(a, dict)}   # its aliases (sql/36)
            # the project's default CC (sql/39): our side of the thread, so their reply-all is not the recipient's
            got |= {str(a).strip().lower() for a in (cfg.get("default_cc") or []) if a}
            own_cache.append(got)
        return own_cache[0]

    def who(addr):
        return names.get(addr or "") or ((addr or "").split("@")[0] or "nobody")

    def no_alias_why(approver):
        return ("%s's Gmail has no address on %s to send as: add it in Gmail (Settings, Accounts, Send mail as),"
                " then it goes in its next window" % (who(approver), as_domain))

    def park(oid, why):
        """Take the row out of the sendable set, visibly, without burning cap."""
        counts["parked"] += 1
        db.run(lambda cur, _o=oid, _w=why: cur.execute(
            "update outreach set send_error=%s, updated_at=now()"
            " where id=%s and status='approved'", (_w, _o)))

    def cancel(oid, why):
        """A follow-up that must never go out: cancelled with the reason."""
        counts["cancelled"] += 1
        db.run(lambda cur, _o=oid, _w=why: cur.execute(
            "update outreach set status='cancelled', stopped_reason=%s, updated_at=now()"
            " where id=%s and status='approved'", (_w, _o)))

    def claim(cur, _o, _k, _a):
        """One claim at a time per segment (per address, from the approver), counted against the day's cap
        as it stands NOW: two runs at once (a deploy's old and new server, a terminal run) each took the whole
        day's budget from their start. -> the claimed row, "cap", ("gap", seconds still to wait), or None."""
        if approver_mode:
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", ("outreach-send-mailbox:" + _k,))
            cur.execute(store.OUT_TODAY_FOR_SQL, (_k,))
            if cur.fetchone()[0] >= int(mbmap[_k]["daily_cap"]):
                return "cap"
        else:
            cur.execute("select pg_advisory_xact_lock(hashtext(%s))", ("outreach-send:" + SEGMENT,))
            cur.execute(OUT_TODAY_SQL, (SEGMENT,))
            if cur.fetchone()[0] >= daily_cap:
                return "cap"
        if timed:
            cur.execute(GAP_SQL, {"a": _a})
            since = cur.fetchone()[0]
            if since is not None and float(since) < float(wcfg["min_gap_seconds"]):
                return {"gap": float(wcfg["min_gap_seconds"]) - float(since)}
        cur.execute(CLAIM_SQL, (_k, _a, _o))
        return cur.fetchone()

    def one_pass():
        """Every due email once. -> {id: monotonic moment} for the ones waiting out an address's gap."""
        nonlocal sent
        gap_wait = {}
        rows = pick(max(1, stop_at - sent) * 3)

        def rest(i):
            """This pass's due emails from row i on that are this machine's to settle."""
            return [str(x["id"]) for x in rows[i:] if not foreign(x) and str(x["id"]) not in left_alone]

        def give_up(i, why):
            """No address on this machine can send any more in this run: the rest of this pass's due emails
            move on with the reason -- or, in the pool, stay for the machine whose mailboxes still have room."""
            if timed and elsewhere():
                log("  %d due: left for the machine holding mailbox(es) %s, which have room today"
                    % (len(rest(i)), ", ".join(elsewhere())))
                left_alone.update(rest(i))
            elif timed:
                hold(rest(i), why, "%d due" % len(rest(i)))
        for i, r in enumerate(rows):
            if sent >= stop_at:
                break
            oid, eid, company = r["id"], r["entity_id"], r["name"] or ""
            if str(oid) in left_alone:                  # settled earlier in this run as not this run's to send
                continue
            subject, body, email, atts = r["subject"], r["body"], r["email"], r["attachments"]
            step, ent_status, thread_id = int(r["sequence_step"] or 0), r["ent_status"], r["gmail_thread_id"]
            approver = r["approver"]
            if step > 0:
                why = None
                if r["replied"]:
                    why = "paused: reply received"
                elif r["stopped_reason"]:
                    why = "thread stopped: %s" % r["stopped_reason"]
                elif ent_status != "contacted":
                    why = "company is now '%s'" % ent_status
                if why:
                    log("  %-32s follow-up %d CANCELLED: %s" % (company[:32], step, why))
                    cancel(oid, why)
                    continue
            problem = None
            if not r.get("selected_recipient_matches", True):
                problem = SELECTED_RECIPIENT_REASON
            elif not email or not email_re.match(email.strip()):
                problem = "recipient address missing or malformed: %r" % (email,)
            elif r["email_status"] == "invalid":
                problem = "recipient failed verification"
            elif not r["verified_allowed"]:
                problem = "Apollo has not verified the recipient email"
            elif not r["service_matches"]:
                problem = "the lead's service changed; create and review a fresh draft"
            elif has_forbidden_copy(subject) or has_forbidden_copy(body):
                problem = "the email contains dash punctuation or a free-sample reply offer; clean the draft first"
            elif re.search(r"{{\w+}}", (subject or "") + (body or "")):
                problem = "unfilled {{placeholder}} in subject or body"
            elif re.search(r"[\r\n]", subject or ""):
                # the email library refuses it (an embedded header), and that used to happen after the claim,
                # leaving the row stuck in 'sending' and the rest of the run unsent (found 2026-09-21)
                problem = "the subject has a line break in it"
            elif step == 0 and ent_status not in ("shortlisted", "contacted"):
                problem = "entity is now '%s' -- approval predates that decision" % ent_status
            elif step > 0 and not thread_id:
                problem = "the opener has no Gmail thread to follow up in"
            elif step == 0:
                # one opener per inbox and per company, not per lead row: one address filed under two
                # leads, or one company found under two websites, must not get two first emails
                # ("you won't hear from me again", 2026-09-21)
                problem = db.run(lambda cur, _o=oid, _m=email: (cur.execute(_DUPLICATE_SQL, {
                    "oid": _o, "email": _m, "statuses": TAKEN_AT_SEND}),
                                                               cur.fetchone())[1][0])
            if not problem and atts:
                # the deck a person approved, byte for byte (outreach_policy.attachment_problem), or nothing goes
                problem = pol.attachment_problem(atts)
            if not problem:
                # an address that answered us under another lead or project since this was approved, or
                # bounced, gets nothing new from any project (outreach_policy.ANSWERED_SQL)
                why = db.run(lambda cur, _m=email, _e=eid: pol.answered_elsewhere(cur, _m, _e))
                if why and step > 0:
                    log("  %-32s follow-up %d CANCELLED: %s" % (company[:32], step, why))
                    cancel(oid, why)
                    continue
                problem = why
            if problem:
                log("  %-32s PARKED: %s" % (company[:32], problem))
                park(oid, problem)
                continue
            if foreign(r):
                log("  %-32s left for the server: its sign-in is not readable on this machine" % company[:32])
                left_alone.add(str(oid))
                continue

            # 1. the addresses it may leave from, best first
            if step > 0:
                mb_key = r["parent_mailbox"] or order[0]
                if mb_key in refused:
                    hold([oid], refused[mb_key], company)
                    continue
                if mb_key not in connected:
                    # not foreign (above): the database or the config says its thread's address cannot send.
                    # It moves, saying so, instead of staying due all window for a run to start for it again
                    hold([oid], thread_box_why(mb_key) or "the thread's address %s cannot send" % mb_key, company)
                    continue
                if remaining.get(mb_key, 0) <= 0:
                    hold([oid], "the thread's address was at its daily limit", company)
                    continue
                cands = [mb_key]
            elif approver_mode:
                # the approver's own addresses only, the one with the most room today first
                mine = by_owner.get(approver or "", [])
                if not mine:
                    hold([oid], ("%s's sending address needs linking again" % who(approver))
                         if boxes_of.get(approver or "") else "%s has no sending address" % who(approver), company)
                    continue
                if as_domain:
                    # only an account that can write as the project's brand: its alias on the domain known, or its
                    # aliases not read yet (read below, once the account's Gmail is open)
                    branded = [k for k in mine if store.alias_for(mbmap[k], as_domain) is not None]
                    if not branded:
                        hold([oid], no_alias_why(approver), company)
                        continue
                    mine = branded
                cands = sorted([k for k in mine if k in connected and remaining.get(k, 0) > 0],
                               key=lambda k: (-remaining[k], mine.index(k)))
                if not cands:
                    gone = [k for k in mine if k in refused]
                    hold([oid], refused[gone[0]] if gone and not [k for k in mine if k in connected]
                         else "%s's address was at its daily limit" % who(approver), company)
                    continue
            else:
                cands = [k for k, left in sorted(((k, remaining.get(k, 0)) for k in order), key=lambda kv: -kv[1])
                         if k in connected and left > 0]
                if not cands:
                    log("  every connected mailbox is at today's cap")
                    give_up(i, next(iter(refused.values())) if refused and not connected
                            else "every mailbox was at its daily limit")
                    break
            if room is not None and timed and sent >= room:
                hold(rest(i), "the project's daily limit of %d was reached" % daily_cap, "%d due" % len(rest(i)))
                break

            # 2. claim, and take the mailbox the database settled on. An address under its gap passes the
            #    email on to the approver's next address; the project's day at its cap stops the run
            claimed, gaps, capped = None, [], False
            for k in cands:
                got = db.run(lambda cur, _k=k: claim(cur, oid, _k, connected[_k]))
                if got == "cap":
                    capped = True
                    if approver_mode:
                        log("  %s is at its daily limit of %d (counting every run's sends)" % (k, mbmap[k]["daily_cap"]))
                        remaining[k] = 0
                        continue
                    break
                if isinstance(got, dict):
                    gaps.append(got["gap"])
                    continue
                claimed = got if got else False
                break
            if claimed is None:
                if capped and not approver_mode:
                    log("  the day's cap of %d is reached (counting every run's sends)" % daily_cap)
                    if timed:
                        hold(rest(i), "the project's daily limit of %d was reached" % daily_cap,
                             "%d due" % len(rest(i)))
                    break
                if gaps:
                    # every address it may use sent under the gap ago: it goes in this run once the gap passes
                    wait = max(0.5, min(gaps))
                    gap_wait[str(oid)] = _time.monotonic() + wait
                    log("  %-32s waits %.0fs: its address sent under %ds ago" % (company[:32], wait, wcfg["min_gap_seconds"]))
                    continue
                hold([oid], "%s's address was at its daily limit" % who(approver) if step == 0
                     else "the thread's address was at its daily limit", company)
                continue
            if claimed is False:
                # Why the claim matched nothing, read again whether or not this run has a window (review,
                # 2026-10-12): a run started before a project's window was switched on still claims, and another
                # process may have just given the email its time. Only a reply or a stop is the follow-up guard
                # refusing it (sql/23, sql/24); a window that is not open is not.
                now_ok = db.run(lambda cur: (cur.execute(
                    "select status, send_after is not null,"
                    " coalesce(send_after <= clock_timestamp() and clock_timestamp() < send_before, false)"
                    " from outreach where id = %s", (oid,)), cur.fetchone())[1])
                st_now, has_time, in_window = now_ok or (None, False, False)
                if st_now != "approved":
                    log("  %-32s skipped: no longer approved (%s)" % (company[:32], st_now or "gone"))
                    continue
                if has_time and not in_window:
                    # its window closed while this run worked, or it was just given one: the next settle moves
                    # it to its next window; it is not cancelled
                    log("  %-32s its window is not open now: it goes in its own window" % company[:32])
                    left_alone.add(str(oid))
                    continue
                if step > 0:
                    log("  %-32s follow-up %d refused by the database guard" % (company[:32], step))
                    cancel(oid, "blocked at send: reply received or thread stopped")
                else:
                    log("  %-32s skipped: no longer approved" % company[:32])
                continue
            mb_key = claimed[0]
            if mb_key not in connected:
                log("  %-32s waits: its thread's mailbox %s is not connected on this machine" % (company[:32], mb_key))
                db.run(lambda cur, _o=oid: cur.execute(
                    "update outreach set status='approved', sender_mailbox=null, sender_address=null,"
                    " updated_at=clock_timestamp() where id=%s and status='sending'", (_o,)))
                left_alone.add(str(oid))
                continue
            sender_addr = connected[mb_key]

            def unclaim(why=None, _o=oid):
                """Nothing reached Gmail: back to Approved. With a reason it is parked for a person to look at."""
                if why:
                    counts["parked"] += 1
                db.run(lambda cur: cur.execute(
                    "update outreach set status='approved', sender_mailbox=null, sender_address=null,"
                    " send_error=%s, updated_at=clock_timestamp() where id=%s and status='sending'", (why, _o)))

            def refuse(why):
                """Gmail refused the address (sign-in, permission, a limit): out for the rest of the run, and
                every email it would have sent waits for its next window."""
                refused[mb_key] = why
                connected.pop(mb_key, None)
                remaining[mb_key] = 0
                hold([oid], why, company)

            def address_refused(e, code, what=""):
                """Gmail refused the ADDRESS, not this email -- a sign-in, a permission, a rate or daily limit --
                at the send or at a follow-up's look at its thread (second review, 2026-10-12: one path for
                both, so a revoked sign-in seen first at the thread is not taken for a passing problem with one
                email). The email goes back to Approved untouched, the address sits the rest of the run out and
                its emails move with the reason (refuse), the summary names it for the one alert, and a person's
                own Gmail whose sign-in failed is marked for reconnecting. -> True when no address is left here
                (the pass stops)."""
                unclaim()
                signin_failed.append(mb_key)
                if approver_mode and (type(e).__name__ == "RefreshError" or code == 401):
                    db.run(lambda cur, _b=mbmap[mb_key], _e=e: store.mark_error(cur, _b["id"], "sign-in: %s" % _e))
                log("  mailbox %s: Gmail refused%s (%s: %s) -- %s goes back to Approved"
                    % (mb_key, (" " + what) if what else "", code or "sign-in", str(e)[:100], company[:32]))
                refuse("Gmail refused %s (%s)" % (sender_addr, code or "sign-in"))
                if not connected:
                    give_up(i + 1, refused[mb_key])
                    return True
                return False

            if mb_key not in services:
                try:
                    services[mb_key] = (user_gmail_service(db, mbmap[mb_key]) if approver_mode
                                        else gmail_service(mbmap[mb_key]))
                except (Exception, SystemExit) as e:
                    # a revoked or expired sign-in, or a rotated client secret: the email goes back to
                    # Approved untouched (it used to stay in 'sending' for good), this mailbox sits the rest
                    # of the run out, and the run ends failed so the owner is told. A person's own Gmail is
                    # marked for reconnecting, which the app shows them until they do.
                    unclaim()
                    signin_failed.append(mb_key)
                    if approver_mode:
                        db.run(lambda cur, _b=mbmap[mb_key], _e=e: store.mark_error(cur, _b["id"], "sign-in: %s" % _e))
                    log("  mailbox %s: Gmail sign-in failed (%s) -- %s goes back to Approved"
                        % (mb_key, str(e)[:120], company[:32]))
                    refuse("Gmail refused %s (sign-in)" % sender_addr)
                    if not connected:
                        give_up(i + 1, refused[mb_key])
                        break
                    continue
            svc = services[mb_key]

            # who the From line says (sql/36): the account itself, or its alias on the project's domain. A
            # follow-up keeps its thread's From; an opener reads the account's aliases the first time it needs them
            from_addr, from_name = sender_addr, None
            if approver_mode and step > 0 and r.get("parent_sent_as"):
                from_addr = r["parent_sent_as"].lower()
                from_name = next((a.get("name") for a in (mbmap[mb_key].get("send_as") or [])
                                  if isinstance(a, dict) and a.get("address") == from_addr), None) or names.get(approver or "")
            elif as_domain and step == 0:
                box = mbmap[mb_key]
                alias = store.alias_for(box, as_domain)
                if alias == store.UNREAD:
                    try:
                        got_as = store.read_send_as(svc)
                    except Exception as e:                  # noqa: BLE001 -- the email waits, saying why
                        got_as = None
                        log("  mailbox %s: could not read its Gmail aliases (%s)" % (mb_key, str(e)[:100]))
                    if got_as is not None:
                        db.run(lambda cur, _b=box, _a=got_as: store.set_send_as(cur, _b["id"], _a))
                        box["send_as"] = got_as
                        alias = store.alias_for(box, as_domain)
                if not alias or alias == store.UNREAD:
                    unclaim()
                    hold([oid], no_alias_why(approver) if alias is None
                         else "%s's Gmail aliases could not be read: it is tried again in its next window" % who(approver),
                         company)
                    continue
                from_addr, from_name = alias["address"], alias.get("name") or names.get(approver or "")

            # a follow-up timed for its window looks at its thread first: a reply the hourly pull has not
            # read yet stops it (it goes back to Approved and moves to its next window)
            if timed and step > 0:
                unread, err = thread_unread(db, svc, thread_id, own_addresses() | {sender_addr.lower(), from_addr})
                if unread:
                    unclaim()
                    hold([oid], "a reply in the thread is not read yet", company)
                    continue
                if unread is None:
                    # the thread could not be read (review, 2026-10-12). One that is not there (deleted in Gmail:
                    # 404) never will be: parked, visibly, never sent blind. A refusal of the address itself is
                    # handled as one at the send (address_refused). Anything else (a 429 or 403 rate limit, a
                    # timeout, a server error) is tried again in its next window -- and after MISSES_TO_ALERT
                    # moves the owner is told -- instead of counting as an unread reply for ever
                    code = _http_code(err)
                    if code in (400, 404, 410):
                        unclaim("its Gmail thread cannot be read (%s): the follow-up is not sent" % code)
                        log("  %-32s PARKED: its Gmail thread cannot be read (%s)" % (company[:32], code))
                        continue
                    if type(err).__name__ == "RefreshError" or code == 401 or (code == 403 and not _rate_limited(err)):
                        # the address, not this thread (second review, 2026-10-12): a revoked sign-in whose cached
                        # access token has not run out yet, a permission taken away. Taken for a passing problem,
                        # each of that address's follow-ups moved day after day and the owner heard after 3 moves
                        if address_refused(err, code, "a look at the thread"):
                            break
                        continue
                    unclaim()
                    log("  %-32s its thread could not be read (%s): it tries again in its next window"
                        % (company[:32], code or type(err).__name__))
                    hold([oid], "its thread could not be read just now (%s): it tries again in its next window"
                         % (code or type(err).__name__), company)
                    continue

            # 3. send
            try:
                msg = _message(body, atts)
                if from_addr != sender_addr:
                    # the account's alias (sql/36): Gmail sends it as the alias when the account has it verified
                    from email.utils import formataddr
                    msg_from = formataddr((from_name, from_addr)) if from_name else from_addr
                else:
                    msg_from = sender_addr
                msg["to"], msg["from"], msg["subject"] = email.strip(), msg_from, subject
                # the copy list it was approved with (sql/39), never the recipient or the sender themselves
                cc = [a for a in dict.fromkeys(str(x).strip().lower() for x in (r.get("cc") or []))
                      if a and a not in (email.strip().lower(), sender_addr.lower(), from_addr.lower())]
                if cc:
                    msg["cc"] = ", ".join(cc)
                # our own Message-ID, one per row: an unknown outcome can be settled by searching Sent for
                # rfc822msgid:<tvf-...>, and a transport-level resend of the same POST is recognisable.
                # The row id without its dashes keeps the header on one line (folded at 78 characters)
                msg["Message-ID"] = "<tvf-%s@%s>" % (str(oid).replace("-", ""), from_addr.rsplit("@", 1)[-1])
            except Exception as e:
                unclaim("could not build the message: %s" % str(e)[:300])
                log("  %-32s PARKED: could not build the message: %s" % (company[:32], str(e)[:70]))
                continue
            request_body = {}
            if step > 0:
                request_body["threadId"] = thread_id
                if r["prev_message_id"]:
                    try:
                        prev = svc.users().messages().get(
                            userId="me", id=r["prev_message_id"], format="metadata",
                            metadataHeaders=["Message-ID"]).execute()
                        hdrs = {h["name"].lower(): h["value"]
                                for h in prev.get("payload", {}).get("headers", [])}
                        if hdrs.get("message-id"):
                            msg["In-Reply-To"] = hdrs["message-id"]
                            msg["References"] = hdrs["message-id"]
                    except Exception as e:
                        log("  %-32s (could not read the previous message id: %s; sending in the thread anyway)"
                            % (company[:32], type(e).__name__))
            request_body["raw"] = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            remaining[mb_key] = remaining.get(mb_key, 0) - 1      # an unknown outcome still used the slot
            try:
                resp = svc.users().messages().send(userId="me", body=request_body).execute()
            except Exception as e:
                code = getattr(getattr(e, "resp", None), "status", None)
                code = int(code) if str(code or "").isdigit() else None
                if type(e).__name__ == "RefreshError" or (code and 400 <= code < 500):
                    # Gmail answered and refused: nothing went out. Only a timeout or a server error is a
                    # real unknown; calling a refusal "unknown" wedged every row a run touched (2026-09-21)
                    if type(e).__name__ == "RefreshError" or code in (401, 403, 429):
                        # the mailbox, not the email (sign-in, permission, rate or daily limit): the email
                        # goes back to Approved untouched and the mailbox sits the rest of the run out
                        if address_refused(e, code):
                            break
                        continue
                    unclaim("Gmail refused this email (%s): %s" % (code, str(e)[:300]))
                    remaining[mb_key] = remaining.get(mb_key, 0) + 1
                    log("  %-32s PARKED: Gmail refused it (%s)" % (company[:32], code))
                    continue
                log("  %-32s UNKNOWN OUTCOME via %s: %s" % (company[:32], mb_key, str(e)[:70]))
                db.run(lambda cur, _o=oid, _err=str(e)[:400]: cur.execute(
                    "update outreach set status='send_unknown', send_error=%s,"
                    " updated_at=clock_timestamp() where id=%s and status='sending'", (_err, _o)))
                continue
            # 4. record
            as_alias = from_addr if from_addr != sender_addr else None
            db.run(lambda cur, _o=oid, _e=eid, _m=resp, _a=as_alias, _cc=cc: (
                cur.execute(
                    "update outreach set status='sent', sent_at=clock_timestamp(),"
                    " gmail_message_id=%s, gmail_thread_id=%s, sent_as=%s, cc=%s::text[],"
                    " updated_at=clock_timestamp() where id=%s and status='sending'",
                    (_m.get("id"), _m.get("threadId"), _a, _cc, _o)),
                cur.execute(
                    "update entities set status='contacted', status_changed_at=now(),"
                    " updated_at=now() where id=%s and status='shortlisted'", (_e,))))
            if as_alias:
                # what the recipient saw, read back from the sent message rather than assumed: Gmail puts the
                # account's own address in the From line of an alias it does not accept
                saw = as_alias
                try:
                    got = svc.users().messages().get(userId="me", id=resp.get("id"), format="metadata",
                                                      metadataHeaders=["From"]).execute()
                    from email.utils import parseaddr
                    hdr = next((h["value"] for h in got.get("payload", {}).get("headers", [])
                                if h.get("name", "").lower() == "from"), "")
                    saw = (parseaddr(hdr)[1] or as_alias).lower()
                except Exception as e:                      # noqa: BLE001 -- it was sent; the From is recorded as asked
                    log("  %-32s (could not read back its From line: %s)" % (company[:32], type(e).__name__))
                if saw != as_alias:
                    log("  %-32s NOTE: Gmail sent it as %s, not %s -- is the alias verified in that Gmail?"
                        % (company[:32], saw, as_alias))
                    db.run(lambda cur, _o=oid, _s=saw: cur.execute(
                        "update outreach set sent_as=%s where id=%s",
                        (None if _s == sender_addr.lower() else _s, _o)))
                    as_alias = None if saw == sender_addr.lower() else saw
            sent += 1
            by_box[mb_key] = by_box.get(mb_key, 0) + 1
            due = ""
            if r["send_after"] is not None:
                late = (dt.datetime.now(dt.timezone.utc) - sw._utc(r["send_after"])).total_seconds()
                due = " (due %s, %+ds)" % (_due_text(r["send_after"], r["send_tz"]), round(late))
            log("  %-32s SENT%s%s via %-8s%s -> %s" % (company[:32], (" follow-up %d" % step) if step else "", due,
                                                       mb_key, (" as " + as_alias) if as_alias else "", email))
        # Every due email of another machine's (foreign) is left alone and said so, including the ones past a
        # break above (no address left here, the project's day at its limit): the send loop starts a new run
        # only for due emails missing from the summary's left_alone, and one left out made it start a run every
        # few seconds for the rest of the window (second review, 2026-10-12)
        left_alone.update(str(x["id"]) for x in rows if foreign(x))
        return gap_wait

    while True:
        waiting = one_pass()
        if not (timed and stay > 0) or sent >= stop_at or not connected:
            break
        left = max_seconds - (_time.monotonic() - started)
        now_m = _time.monotonic()
        waits = [t - now_m for t in waiting.values()]
        soon = db.run(lambda cur: (cur.execute(SOON_SQL, {"segment": SEGMENT, "stay": stay}), _rows(cur))[1])
        waits += [float(x["wait"]) for x in soon
                  if str(x["id"]) not in waiting and str(x["id"]) not in left_alone and not foreign(dict(x))]
        if not waits:
            break
        nap = max(1.0, min(waits))
        if nap >= left:
            break
        log("  ...the next email's moment is %.0fs away; the run waits for it" % nap)
        _time.sleep(nap)
    if approver_mode:
        log("\n%d sent this run (%s); each address has its own daily limit"
            % (sent, ", ".join("%s %d" % kv for kv in by_box.items()) or "none"))
    else:
        log("\n%d sent this run (%s); %d sent today in the segment (ceiling %d)"
            % (sent, ", ".join("%s %d" % kv for kv in by_box.items()) or "none", sent_today + sent, daily_cap))
    return finish(0)


def cmd_pull(args):
    """Fetch replies to sent threads, mailbox by mailbox.

    * each thread is read through the mailbox that sent it; a mailbox not
      connected on this machine is skipped and reported, never guessed.
    * OUR OWN messages are never ingested as replies: anything sent by any of
      the segment's mailboxes or carrying the SENT/DRAFT label is skipped.
    * idempotent by unique index on gmail_message_id.
    * a new reply PAUSES the thread (pending follow-ups cancelled); an
      auto-reply triaged neutral lets it resume, anything else ends it.
    * a BOUNCE (mailer-daemon, "Delivery Status Notification (Failure)") marks
      the address invalid and ends the thread, so no mailbox writes to it again.
    * a new reply in a person's own Gmail is starred and labelled there, and an
      alert goes into their inbox; once a day, a reminder of the replies nobody
      has marked (tools/reply_alert.py, sql/45).
    * --recent (the app's five-minute look, app/scheduler.py): only the threads
      with a message in the last two days, found with one search per mailbox, and
      the threads waiting on us; the hourly run without it reads every thread of
      the last 60 days.
    * waiting on us (sql/46): on each reply, when it came and when our side first
      wrote in the thread after it (from this Gmail, or another of our addresses).
    """
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    mbmap = {mb["key"]: mb for mb in MAILBOXES}
    own = [a.strip().lower() for a in (env(mb["email_env"]) for mb in MAILBOXES) if a]
    # the project's default CC (sql/39): our side of the thread -- their reply-all is not the recipient's reply
    own += [str(a).strip().lower() for a in ((cfg or {}).get("default_cc") or []) if a]
    # the addresses people connected in the app: a thread they sent is read through their Gmail
    import mailbox_store as store
    user_boxes = {b["address"].lower(): b for b in db.run(lambda cur: store.mailboxes(cur, with_token=True))}
    own += list(user_boxes)
    # and the aliases they send as (sql/36): a message from one is ours too (it carries SENT anyway)
    own += [a["address"] for b in user_boxes.values() for a in (b.get("send_as") or []) if isinstance(a, dict)]
    threads = db.run(lambda cur: (cur.execute("""
        select distinct o.gmail_thread_id, o.entity_id, o.contact_id, coalesce(o.sender_mailbox, %s)
        from outreach o join entities e on e.id = o.entity_id
        where o.status = 'sent' and o.direction = 'outbound' and o.gmail_thread_id is not null
          and e.segment_id = (select id from segments where slug = %s)
          -- recent threads only: it runs hourly now (app/scheduler.py), and a reply after two months
          -- is rare enough not to read every thread ever sent, every hour
          and o.sent_at > now() - interval '60 days'
    """, (MAILBOXES[0]["key"], SEGMENT)), cur.fetchall())[1])
    if not threads:
        log("no sent threads to poll"); db.close(); return 0
    by_box = {}
    for tid, eid, cid, mbk in threads:
        by_box.setdefault(mbk, []).append((tid, eid, cid))
    # the replies waiting on us (sql/46) are read on the five-minute look too, however old: our answer shows at once
    waiting = set(db.run(lambda cur: (cur.execute(
        "select distinct r.gmail_thread_id from outreach r where r.gmail_thread_id is not null and "
        + pol.unanswered("r")), [x[0] for x in cur.fetchall()])[1]))
    found = errors = paused = bounced = skipped = alerted = answered = 0
    for mbk, items in by_box.items():
        mb = mbmap.get(mbk)
        ub = user_boxes.get(str(mbk or "").lower())
        if ub is not None:
            if not ub["usable"]:
                skipped += len(items)
                log("  %s: %d thread(s) skipped -- its owner has to connect it again" % (mbk, len(items)))
                continue
            try:
                svc = user_gmail_service(db, ub)
            except Exception as e:
                skipped += len(items)
                if type(e).__name__ == "RefreshError":
                    db.run(lambda cur, _b=ub, _e=e: store.mark_error(cur, _b["id"], "sign-in: %s" % _e))
                log("  %s: %d thread(s) skipped -- %s" % (mbk, len(items), str(e)[:120]))
                continue
        elif not mb or not mailbox_connected(mb):
            skipped += len(items)
            log("  mailbox %s: %d thread(s) skipped -- not connected on this machine" % (mbk, len(items)))
            continue
        else:
            svc = gmail_service(mb)
        if getattr(args, "recent", False):
            try:
                fresh = _recent_threads(svc)
            except Exception as e:
                errors += 1
                log("  %s: the quick look failed (%s) -- the hourly run reads every thread" % (mbk, str(e)[:120]))
                continue
            items = [it for it in items if it[0] in fresh or it[0] in waiting]
        for tid, eid, cid in items:
            try:
                t = svc.users().threads().get(userId="me", id=tid, format="full").execute()
            except Exception as e:
                errors += 1
                log("  %s thread %s: fetch failed (%s) -- continuing" % (mbk, tid, type(e).__name__))
                continue
            ours, theirs = [], []                 # (when, from) of our side's messages; (id, when) of theirs
            for m in t.get("messages", []):
                labels = set(m.get("labelIds") or [])
                if "DRAFT" in labels:
                    continue                      # not yet sent by anyone
                headers = {h["name"].lower(): h["value"]
                           for h in m.get("payload", {}).get("headers", [])}
                frm = (headers.get("from") or "").lower()
                if "SENT" in labels or any(a in frm for a in own):
                    ours.append((_message_time(m), frm))   # ours: from this Gmail, or from another of our addresses
                    continue
                theirs.append((m["id"], _message_time(m)))
                subj = headers.get("subject", "")
                bounce = pol.is_bounce(frm, subj)
                mid = m["id"]
                body = _plain_body(m.get("payload", {}))

                def _ingest(cur, _t=tid, _e=eid, _c=cid, _m=mid, _s=subj, _b=body[:8000], _bn=bounce):
                    cur.execute(
                        "insert into outreach (entity_id, contact_id, direction, subject, body, status,"
                        " triage, triage_reason, gmail_message_id, gmail_thread_id)"
                        " values (%s,%s,'inbound',%s,%s,%s,%s,%s,%s,%s)"
                        " on conflict (gmail_message_id) where gmail_message_id"
                        " is not null do nothing returning id",
                        (_e, _c, _s, _b, "triaged" if _bn else "received", "neutral" if _bn else None,
                         "bounce: the address rejected the email" if _bn else None, _m, _t))
                    got = cur.fetchone()
                    if not got:
                        return None, 0
                    if _bn:
                        return got, pol.mark_bounce(cur, _e, _c)
                    return got, pol.pause_on_reply(cur, _e)

                inserted, n = db.run(_ingest)
                if not inserted:
                    continue
                if bounce:
                    bounced += 1
                    log("  %s thread %s: BOUNCE -- address marked invalid, thread ended" % (mbk, tid))
                else:
                    found += 1
                    paused += n
                    log("  %s thread %s: new reply%s" % (mbk, tid, ("; %d pending follow-up(s) paused" % n) if n else ""))
            answered += _note_answers(db, theirs, ours)
        if ub is not None:
            # the person whose Gmail this is hears of it: an alert in their inbox, and the daily reminder
            import reply_alert
            try:
                alerted += reply_alert.alert_new(db, svc, ub, [it[0] for it in items], log)
                reply_alert.remind(db, svc, ub, log)
            except Exception as e:
                log("  %s: reply alerts failed (%s) -- the next pull tries again" % (mbk, str(e)[:160]))
    db.close()
    log("\n%d new repl(ies), %d alert(s), %d bounce(s), %d follow-up(s) paused, %d repl(ies) answered; %d thread"
        " error(s); %d thread(s) on unconnected mailboxes" % (found, alerted, bounced, paused, answered, errors, skipped))
    return 0


def _message_time(m):
    """When Gmail got the message (its internalDate, milliseconds), or None."""
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(int(m["internalDate"]) / 1000.0, tz=dt.timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


ANSWER_SQL = """
update outreach set received_at = coalesce(received_at, %(at)s),
       answered_at = coalesce(answered_at, %(ans)s),
       answered_by = case when answered_at is null and %(ans)s is not null then %(by)s else answered_by end,
       answered_how = case when answered_at is null and %(ans)s is not null then 'thread' else answered_how end
where gmail_message_id = %(mid)s and direction = 'inbound'
  and ((received_at is null and %(at)s is not null) or (answered_at is null and %(ans)s is not null))
returning (answered_how = 'thread' and answered_at = %(ans)s)"""


def _note_answers(db, theirs, ours):
    """Waiting on us (sql/46): on each of their messages already read as a reply, when it came and when our side first
    wrote in the thread after it, and from which address. A date already noted stays. -> replies newly answered."""
    if not theirs:
        return 0
    from email.utils import parseaddr
    rows = []
    for mid, at in theirs:
        nxt = min(((w, frm) for w, frm in ours if at and w and w > at), default=None)
        by = (parseaddr(nxt[1])[1] or nxt[1])[:200] if nxt else None
        rows.append({"mid": mid, "at": at, "ans": nxt[0] if nxt else None, "by": by})

    def _write(cur):
        n = 0
        for r in rows:
            cur.execute(ANSWER_SQL, r)
            got = cur.fetchone()
            n += 1 if got and got[0] else 0
        return n
    return db.run(_write)


def _recent_threads(svc, days=2, pages=5):
    """The threads of this mailbox with a message from outside in the last few days: one search, not one read per
    thread, so the app can look every five minutes."""
    ids, token = set(), None
    for _ in range(pages):
        r = svc.users().messages().list(userId="me", q="newer_than:%dd -in:sent -in:drafts" % days, maxResults=500,
                                        pageToken=token).execute()
        ids.update(m.get("threadId") for m in r.get("messages") or [])
        token = r.get("nextPageToken")
        if not token:
            break
    return ids


def _plain_body(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    for part in payload.get("parts", []) or []:
        got = _plain_body(part)
        if got:
            return got
    return ""


# ------------------------------------------------------------------ triage
TRIAGE_PROMPT = """You triage replies to a B2B outreach email (a studio offering a
partnership or a service to a company or a creator). Classify the reply below.

positive  = any genuine interest: wants a call, asks questions, asks for the
            deck, refers us to the right person
negative  = decline, not interested, unsubscribe, wrong person with no referral
neutral   = auto-reply, out-of-office, ambiguous one-liner

Reply with JSON only: {"triage": "...", "reason": "<one sentence>"}

REPLY:
%s"""


def cmd_triage(args):
    key = env("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set in .env -- replies stay in the "
                 "inbox folder marked needs_human until it is")
    try:
        import anthropic
    except ImportError:
        sys.exit("pip install anthropic")
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    rows = db.run(lambda cur: (cur.execute(
        "select id, entity_id, body from outreach where direction='inbound'"
        " and status='received' limit %s", (args.limit,)), cur.fetchall())[1])
    if not rows:
        log("no untriaged replies"); db.close(); return 0
    client = anthropic.Anthropic(api_key=key)
    for oid, eid, body in rows:
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=200,
                messages=[{"role": "user", "content": TRIAGE_PROMPT % (body or "")[:4000]}])
            data = json.loads(re.search(r"\{.*\}", resp.content[0].text, re.S).group(0))
            label = data.get("triage")
            if label not in ("positive", "negative", "neutral"):
                label = "needs_human"
            reason = (data.get("reason") or "")[:400]
        except Exception as e:
            label, reason = "needs_human", "classifier error: " + type(e).__name__

        def _label(cur, _o=oid, _e=eid, _l=label, _r=reason):
            cur.execute("update outreach set status='triaged', triage=%s, triage_reason=%s,"
                        " updated_at=now() where id=%s", (_l, _r, _o))
            # a real answer ends the thread; an auto-reply (neutral) lets it resume
            if _l in ("positive", "negative"):
                pol.stop_thread(cur, _e, "reply: %s" % _l)

        db.run(_label)
        log("  %s  %s" % (label.ljust(12), reason[:70]))
    db.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--limit", type=int, default=20)
    d.add_argument("--template", default=None, help="template key; omit to pick by the segment when-conditions")
    d.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("auth"); a.add_argument("--mailbox", default=None, help="mailbox key; the first one when omitted")
    sub.add_parser("mailboxes")
    s = sub.add_parser("send"); s.add_argument("--limit", type=int, default=500,
                                               help="most emails this run; the mailbox and segment caps still apply")
    s.add_argument("--stay", type=int, default=0,
                   help="a project with a sending window: keep going while the next email's moment is under this many"
                        " seconds away (the app's send loop uses 55); 0, the default, is one pass")
    s.add_argument("--max-seconds", type=int, default=900, help="the longest a --stay run keeps going")
    pl = sub.add_parser("pull")
    pl.add_argument("--recent", action="store_true", help="only threads with a message in the last two days")
    t = sub.add_parser("triage"); t.add_argument("--limit", type=int, default=50)
    f = sub.add_parser("followups"); f.add_argument("--limit", type=int, default=60)
    f.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return {"draft": cmd_draft, "auth": cmd_auth, "send": cmd_send,
            "pull": cmd_pull, "triage": cmd_triage, "followups": cmd_followups,
            "mailboxes": cmd_mailboxes}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
