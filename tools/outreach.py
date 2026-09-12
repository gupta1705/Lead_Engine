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


def cmd_draft(args):
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    requested = None
    if getattr(args, "template", None):
        requested = next((t for t in cfg["templates"] if t["key"] == args.template), None)
        if not requested:
            sys.exit("unknown template %r; segment %s has: %s"
                     % (args.template, SEGMENT, [t["key"] for t in cfg["templates"]]))
    openers = [t for t in cfg["templates"] if t.get("kind") != "follow_up"]
    tpl = requested or next((t for t in openers if not t.get("when")), openers[0])
    sender = cfg["sender"]
    if "SET_ME" in json.dumps(sender) and not args.dry_run:
        log("NOTE: sender.name / postal_address still say SET_ME in config.")
        log("      Drafts will render with those placeholders visible, which")
        log("      is safe -- approval will catch them -- but fix the config")
        log("      before anyone approves.\n")

    rows = db.run(lambda cur: (cur.execute("""
        select e.id, e.name, e.metadata, c.id, c.full_name, c.email
        from entities e
        join contacts c on c.entity_id = e.id and c.is_primary
        where e.segment_id = (select id from segments where slug = %s)
          and e.status = 'shortlisted'
          and c.email is not null
          and not exists (select 1 from outreach o
                          where o.entity_id = e.id and o.direction = 'outbound'
                            and o.status not in ('cancelled','failed'))
        order by e.fit_score desc nulls last limit %s
    """, (SEGMENT, args.limit)), cur.fetchall())[1])

    if not rows:
        log("nothing to draft -- no shortlisted lead with a contact lacks a draft")
        db.close(); return 0

    log("drafting %d email(s) from template %s%s\n"
        % (len(rows), requested["key"] if requested else "auto (per-lead when-conditions)",
           "  [DRY RUN]" if args.dry_run else ""))

    import llm
    gen = llm.make_generator(cfg, log=log)
    if gen:
        log("  the opening sentence is written by %s from each lead's own facts;"
            % gen.policy["model"])
        log("  one that fails the checks falls back to the built-in hook\n")
    elif llm.policy(cfg):
        log("  GROQ_API_KEY is not set, so every hook is the built-in one\n")

    made = 0
    for eid, company, meta, cid, cname, email in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        tpl = requested or pick_template(cfg, meta)
        # only a template that actually uses {{hook}} is worth a model call
        use_gen = gen if "{{hook}}" in (tpl.get("body") or "") else None
        ctx = build_context(cfg, company, meta, cname, email, seed=eid, generator=use_gen)
        subject, body = render_message(tpl, ctx)
        written = ctx.get("generated_hook") or None
        log("  %-32s -> %-34s [%s]%s" % (company[:32], email, tpl["key"],
                                         "  written" if written else ""))
        if args.dry_run:
            continue
        db.run(lambda cur, _e=eid, _c=cid, _s=subject, _b=body, _g=written: cur.execute(
            "insert into outreach (entity_id, contact_id, template_key, subject, body,"
            " generated_hook) values (%s, %s, %s, %s, %s, %s) on conflict do nothing",
            (_e, _c, tpl["key"], _s, _b, _g)))
        made += 1

    db.close()
    if gen:
        st = gen.stats
        log("\n  model: %d written, %d rejected, %d unavailable"
            % (st["ok"], st["rejected"], st["failed"]))
        if st["ok"]:
            log("  written drafts are approved one at a time unless the segment's"
                " batch_approval.allow_generated says otherwise")
    log("\n%d draft(s) created. Review and approve them in the UI (Outreach tab)"
        % made)
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
        ctx = build_context(cfg, company, meta, row["full_name"], row["email"],
                            seed=row["entity_id"], opener_subject=row["opener_subject"])
        subject, body = render_message(tpl, ctx)
        log("  %-32s step %d -> %-34s %s" % (company[:32], step["step"], row["email"], subject[:40]))
        if args.dry_run:
            continue
        new = db.run(lambda cur, _r=row, _s=step, _k=tpl["key"], _sub=subject, _b=body:
                     pol.insert_followup(cur, _r, _s["step"], _k, _sub, _b))
        made += 1 if new else 0
    db.close()
    log("\n%d follow-up draft(s) created. Approve them in the Outreach tab (Drafts)." % made)
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
    """
    import datetime as dt
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    if "SET_ME" in json.dumps(cfg.get("sender", {})):
        sys.exit("refusing to send: config outreach.sender still contains SET_ME")
    connected = {mb["key"]: env(mb["email_env"]).strip() for mb in MAILBOXES
                 if mb["enabled"] and mailbox_connected(mb)}
    if not connected:
        sys.exit("no mailbox is connected for segment %s. For each mailbox, set its address in .env (%s)\n"
                 "and run: SEGMENT_SLUG=%s python tools/outreach.py auth --mailbox <key>"
                 % (SEGMENT, ", ".join(mb["email_env"] for mb in MAILBOXES), SEGMENT))
    mbmap = {mb["key"]: mb for mb in MAILBOXES}
    today = dt.datetime.now(dt.timezone.utc).date()
    status = db.run(lambda cur: pol.mailbox_status(cur, SEGMENT, MAILBOXES, today))
    order = [st["key"] for st in status]
    remaining = {st["key"]: (st["remaining"] if st["key"] in connected else 0) for st in status}
    for st in status:
        log("  mailbox %-10s %-5s cap %3d today, %3d sent, %3d left" % (
            st["key"], "on" if st["key"] in connected else "off", st["cap_today"], st["sent_today"], remaining[st["key"]]))

    daily_cap = int(cfg.get("daily_send_cap", 20))
    sent_today = sum(st["sent_today"] for st in status)
    budget = min(max(0, daily_cap - sent_today), sum(remaining.values()), args.limit)
    if budget <= 0:
        log("nothing can go today: segment %d/%d sent, connected mailboxes have %d left"
            % (sent_today, daily_cap, sum(remaining.values())))
        db.close(); return 0

    rows = db.run(lambda cur: (cur.execute("""
        select o.id, o.entity_id, o.subject, o.body,
               c.email, c.email_status, e.name, e.status,
               o.sequence_step, p.gmail_thread_id, p.stopped_reason,
               (select s.gmail_message_id from outreach s
                 where (s.id = o.parent_id or s.parent_id = o.parent_id)
                   and s.direction = 'outbound' and s.status = 'sent'
                   and s.sequence_step < o.sequence_step
                 order by s.sequence_step desc limit 1) as prev_message_id,
               exists (select 1 from outreach r where r.entity_id = o.entity_id
                        and r.direction = 'inbound' and r.triage is distinct from 'neutral') as replied,
               p.sender_mailbox as parent_mailbox
        from outreach o
        join entities e on e.id = o.entity_id
        left join contacts c on c.id = o.contact_id
        left join outreach p on p.id = o.parent_id
        where o.status = 'approved' and o.direction = 'outbound'
          and o.send_error is null
          and e.segment_id = (select id from segments where slug = %s)
        order by (o.sequence_step > 0) desc, o.created_at limit %s
    """, (SEGMENT, budget * 3)), cur.fetchall())[1])
    if not rows:
        log("nothing approved to send"); db.close(); return 0

    email_re = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
    services, sent, by_box = {}, 0, {}

    def park(oid, why):
        """Take the row out of the sendable set, visibly, without burning cap."""
        db.run(lambda cur, _o=oid, _w=why: cur.execute(
            "update outreach set send_error=%s, updated_at=now()"
            " where id=%s and status='approved'", (_w, _o)))

    def cancel(oid, why):
        """A follow-up that must never go out: cancelled with the reason."""
        db.run(lambda cur, _o=oid, _w=why: cur.execute(
            "update outreach set status='cancelled', stopped_reason=%s, updated_at=now()"
            " where id=%s and status='approved'", (_w, _o)))

    for (oid, eid, subject, body, email, estatus, company, ent_status,
         step, thread_id, stopped, prev_mid, replied, parent_mb) in rows:
        if sent >= budget:
            break
        step = int(step or 0)
        if step > 0:
            why = None
            if replied:
                why = "paused: reply received"
            elif stopped:
                why = "thread stopped: %s" % stopped
            elif ent_status != "contacted":
                why = "company is now '%s'" % ent_status
            if why:
                log("  %-32s follow-up %d CANCELLED: %s" % (company[:32], step, why))
                cancel(oid, why)
                continue
        problem = None
        if not email or not email_re.match(email.strip()):
            problem = "recipient address missing or malformed: %r" % (email,)
        elif estatus == "invalid":
            problem = "recipient failed verification"
        elif re.search(r"{{\w+}}", (subject or "") + (body or "")):
            problem = "unfilled {{placeholder}} in subject or body"
        elif step == 0 and ent_status not in ("shortlisted", "contacted"):
            problem = "entity is now '%s' -- approval predates that decision" % ent_status
        elif step > 0 and not thread_id:
            problem = "the opener has no Gmail thread to follow up in"
        if problem:
            log("  %-32s PARKED: %s" % (company[:32], problem))
            park(oid, problem)
            continue

        # 1. pick the mailbox
        if step > 0:
            mb_key = parent_mb or order[0]
            if mb_key not in connected:
                log("  %-32s follow-up %d waits: mailbox %s is not connected on this machine" % (company[:32], step, mb_key))
                continue
            if remaining.get(mb_key, 0) <= 0:
                log("  %-32s follow-up %d waits: mailbox %s is at today's cap" % (company[:32], step, mb_key))
                continue
        else:
            mb_key = pol.pick_mailbox([(k, remaining.get(k, 0)) for k in order], set(connected))
            if not mb_key:
                log("  every connected mailbox is at today's cap")
                break

        # 2. claim, and take the mailbox the database settled on
        claimed = db.run(lambda cur, _o=oid, _k=mb_key, _a=connected[mb_key]: (cur.execute(
            "update outreach set status='sending', sender_mailbox=%s, sender_address=%s, updated_at=now()"
            " where id=%s and status='approved' returning sender_mailbox", (_k, _a, _o)),
            cur.fetchone())[1])
        if not claimed:
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
                " updated_at=now() where id=%s and status='sending'", (_o,)))
            continue
        sender_addr = connected[mb_key]
        if mb_key not in services:
            services[mb_key] = gmail_service(mbmap[mb_key])
        svc = services[mb_key]

        # 3. send
        msg = MIMEText(body)
        msg["to"], msg["from"], msg["subject"] = email.strip(), sender_addr, subject
        request_body = {}
        if step > 0:
            request_body["threadId"] = thread_id
            if prev_mid:
                try:
                    prev = svc.users().messages().get(
                        userId="me", id=prev_mid, format="metadata",
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
            log("  %-32s UNKNOWN OUTCOME via %s: %s" % (company[:32], mb_key, str(e)[:70]))
            db.run(lambda cur, _o=oid, _err=str(e)[:400]: cur.execute(
                "update outreach set status='send_unknown', send_error=%s,"
                " updated_at=now() where id=%s and status='sending'", (_err, _o)))
            continue
        # 4. record
        db.run(lambda cur, _o=oid, _e=eid, _m=resp: (
            cur.execute(
                "update outreach set status='sent', sent_at=now(),"
                " gmail_message_id=%s, gmail_thread_id=%s, updated_at=now()"
                " where id=%s and status='sending'",
                (_m.get("id"), _m.get("threadId"), _o)),
            cur.execute(
                "update entities set status='contacted', status_changed_at=now(),"
                " updated_at=now() where id=%s and status='shortlisted'", (_e,))))
        sent += 1
        by_box[mb_key] = by_box.get(mb_key, 0) + 1
        log("  %-32s SENT%s via %-8s -> %s" % (company[:32], (" follow-up %d" % step) if step else "", mb_key, email))
    db.close()
    log("\n%d sent this run (%s); %d sent today in the segment (ceiling %d)"
        % (sent, ", ".join("%s %d" % kv for kv in by_box.items()) or "none", sent_today + sent, daily_cap))
    return 0


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
    """
    import outreach_policy as pol
    from dbconn import Db
    db = Db()
    load_outreach_config(db)
    mbmap = {mb["key"]: mb for mb in MAILBOXES}
    own = [a.strip().lower() for a in (env(mb["email_env"]) for mb in MAILBOXES) if a]
    threads = db.run(lambda cur: (cur.execute("""
        select distinct o.gmail_thread_id, o.entity_id, o.contact_id, coalesce(o.sender_mailbox, %s)
        from outreach o join entities e on e.id = o.entity_id
        where o.status = 'sent' and o.direction = 'outbound' and o.gmail_thread_id is not null
          and e.segment_id = (select id from segments where slug = %s)
    """, (MAILBOXES[0]["key"], SEGMENT)), cur.fetchall())[1])
    if not threads:
        log("no sent threads to poll"); db.close(); return 0
    by_box = {}
    for tid, eid, cid, mbk in threads:
        by_box.setdefault(mbk, []).append((tid, eid, cid))
    found = errors = paused = bounced = skipped = 0
    for mbk, items in by_box.items():
        mb = mbmap.get(mbk)
        if not mb or not mailbox_connected(mb):
            skipped += len(items)
            log("  mailbox %s: %d thread(s) skipped -- not connected on this machine" % (mbk, len(items)))
            continue
        svc = gmail_service(mb)
        for tid, eid, cid in items:
            try:
                t = svc.users().threads().get(userId="me", id=tid, format="full").execute()
            except Exception as e:
                errors += 1
                log("  %s thread %s: fetch failed (%s) -- continuing" % (mbk, tid, type(e).__name__))
                continue
            for m in t.get("messages", []):
                labels = set(m.get("labelIds") or [])
                if "SENT" in labels or "DRAFT" in labels:
                    continue                      # ours, or not yet sent by anyone
                headers = {h["name"].lower(): h["value"]
                           for h in m.get("payload", {}).get("headers", [])}
                frm = (headers.get("from") or "").lower()
                if any(a in frm for a in own):
                    continue                      # ours, sent from another client
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
    db.close()
    log("\n%d new repl(ies), %d bounce(s), %d follow-up(s) paused; %d thread error(s); %d thread(s) on"
        " unconnected mailboxes. Next: python tools/outreach.py triage" % (found, bounced, paused, errors, skipped))
    return 0


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
    sub.add_parser("pull")
    t = sub.add_parser("triage"); t.add_argument("--limit", type=int, default=50)
    f = sub.add_parser("followups"); f.add_argument("--limit", type=int, default=60)
    f.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return {"draft": cmd_draft, "auth": cmd_auth, "send": cmd_send,
            "pull": cmd_pull, "triage": cmd_triage, "followups": cmd_followups,
            "mailboxes": cmd_mailboxes}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
