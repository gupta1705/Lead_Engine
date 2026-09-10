#!/usr/bin/env python3
"""outreach.py -- Phase F: drafts, sends, replies, triage.

THE ONE RULE THAT SHAPES EVERYTHING HERE: no email leaves this system without
a human having read THAT exact text and clicked approve. The commands are
deliberately separated so the dangerous one is small and auditable:

    draft    render personalised drafts for shortlisted leads   (no network)
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
    global SENDER_ENV, TOKEN_ENV, TOKEN_PATH
    cfg = db.run(lambda cur: (cur.execute(
        "select config->'outreach' from segments where slug = %s", (SEGMENT,)),
        cur.fetchone())[1][0])
    if not cfg:
        sys.exit("config has no outreach block for segment %s" % SEGMENT)
    SENDER_ENV = (cfg.get("sender") or {}).get("email_env") or "GMAIL_SENDER_ADDRESS"
    if SENDER_ENV != "GMAIL_SENDER_ADDRESS":
        TOKEN_PATH = ROOT / (".gmail_token.%s.json" % SEGMENT)
        TOKEN_ENV = "GMAIL_TOKEN_JSON_" + SEGMENT.upper().replace("-", "_")
    return cfg


# ------------------------------------------------------------------ draft
def greeting_for(full_name, email, company, fallback=None):
    """A person -> first name. Anything else -> the segment's fallback.

    The contact's name is only used when it reads as a person: a feed that
    published its address under the show's name must never produce
    "Hi Tech Talk". The fallback comes from config outreach.greeting_fallback
    ("there" for the clipping segment, "team at {{company}}" by default)."""
    import personname
    first = personname.greeting_name(full_name)
    if first:
        return first
    return (fallback or "team at {{company}}").replace("{{company}}", company)


def pick_template(cfg, meta):
    """The first template whose `when` conditions match the lead's metadata
    (e.g. {"metadata.kind": "production_house"}), else the first template
    with no conditions."""
    tpls = cfg["templates"]
    for t in tpls:
        w = t.get("when") or {}
        if not w:
            continue
        ok = True
        for path, want in w.items():
            parts = path.split(".")
            if parts and parts[0] == "metadata":
                parts = parts[1:]
            v = meta
            for part in parts:
                v = v.get(part) if isinstance(v, dict) else None
            if v != want:
                ok = False
                break
        if ok:
            return t
    return next((t for t in tpls if not t.get("when")), tpls[0])


def hook_for(meta, company):
    """One sentence of THEIR evidence, so the email reads researched, not
    blasted. Priority: news evidence > research why_fit > site genre language.
    Returns None when nothing defensible exists -- the template then uses a
    neutral line, and the human approving the draft sees exactly that."""
    for ev in (meta.get("news_evidence") or []):
        h = (ev.get("headline") or "").strip()
        if h:
            return ('Saw the news -- "%s" -- which is exactly the kind of '
                    'cross-border thinking we look for in a partner.' % h[:120])
    why = (meta.get("why_fit") or "").strip()
    if why:
        return why.split(". ")[0].rstrip(".") + "."
    genres = meta.get("site_genre_evidence") or []
    if genres:
        return ("Your work in %s sits squarely in the lanes TVF's formats "
                "live in." % ", ".join(genres[:3]))
    return None


NEUTRAL_HOOK = ("We've been mapping US independents whose work overlaps with "
                "TVF's lanes, and {{company}} made our shortlist.")


def hook_for_clipping(meta, company):
    """Segment 3: one sentence of THEIR numbers -- episodes, cadence, length,
    the shorts count -- from the feed and channel evidence. True by
    construction; a person still reads it before it goes anywhere."""
    pf = meta.get("podcast_feed") or {}
    yc = meta.get("youtube_channel") or {}
    r = yc.get("recent") or {}
    bits = []
    if pf.get("episode_count"):
        s = "%s has %d episodes" % (company, int(pf["episode_count"]))
        cad = pf.get("cadence_per_month")
        if cad and cad >= 4:
            s += ", publishes weekly"
        elif cad and cad >= 1:
            s += ", publishes about %s a month" % ("%g" % cad)
        if pf.get("avg_duration_min"):
            s += ", averaging %d minutes an episode" % int(pf["avg_duration_min"])
        bits.append(s)
    elif yc.get("video_count"):
        bits.append("%s has %d videos on YouTube" % (company, int(yc["video_count"])))
    if r.get("sampled"):
        bits.append("of your last %d YouTube uploads, %d are long-form and %d are shorts"
                    % (int(r["sampled"]), int(r.get("long_count") or 0), int(r.get("shorts_count") or 0)))
    elif pf.get("episode_count"):
        bits.append("as far as we can see, none of it is being cut into short-form")
    if not bits:
        return None
    return "Quick one: " + "; ".join(bits) + "."


def render(template, ctx):
    out = template
    for k, v in ctx.items():
        out = out.replace("{{%s}}" % k, v)
    leftover = re.findall(r"{{\w+}}", out)
    if leftover:
        raise ValueError("unfilled placeholders: %s" % leftover)
    return out


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
    tpl = requested or next((t for t in cfg["templates"] if not t.get("when")), cfg["templates"][0])
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

    made = 0
    import personname
    for eid, company, meta, cid, cname, email in rows:
        meta = meta if isinstance(meta, dict) else json.loads(meta or "{}")
        tpl = requested or pick_template(cfg, meta)
        hook = (hook_for_clipping(meta, company) if cfg.get("hook_style") == "clipping"
                else hook_for(meta, company)) or cfg.get("neutral_hook") or NEUTRAL_HOOK
        ctx = {
            "company": company,
            # the contact's own name when it is a person; else the host the engine
            # found (high/medium only); else the segment's fallback. Never a show name.
            "greeting_name": (personname.greeting_name(cname)
                              or ((meta.get("host") or {}).get("first_name")
                                  if (meta.get("host") or {}).get("confidence") in ("high", "medium") else None)
                              or greeting_for(None, email, company, cfg.get("greeting_fallback"))),
            "hook": hook.replace("{{company}}", company),
            "sender_name": sender.get("name", ""),
            "sender_title": sender.get("title", ""),
            "postal_address": sender.get("postal_address", ""),
        }
        subject = render(tpl["subject"], ctx)
        body = render(tpl["body"], ctx)
        log("  %-32s -> %-34s [%s] %s" % (company[:32], email, tpl["key"], subject[:40]))
        if args.dry_run:
            continue
        db.run(lambda cur, _e=eid, _c=cid, _s=subject, _b=body: cur.execute(
            "insert into outreach (entity_id, contact_id, template_key, subject, body)"
            " values (%s, %s, %s, %s, %s) on conflict do nothing",
            (_e, _c, tpl["key"], _s, _b)))
        made += 1

    db.close()
    log("\n%d draft(s) created. Review and approve them in the UI (Outreach tab)"
        % made)
    return 0


# ------------------------------------------------------------------- gmail
def gmail_service():
    cid = env("GOOGLE_OAUTH_CLIENT_ID")
    csec = env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not csec:
        sys.exit(
            "Gmail is not configured yet.\n"
            "  1. console.cloud.google.com -> APIs & Services -> enable Gmail API\n"
            "  2. Credentials -> Create OAuth client ID -> Desktop app\n"
            "  3. put GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env\n"
            "  4. run: python tools/outreach.py auth   (one-time browser consent)")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-api-python-client google-auth-oauthlib")
    # The token lives in .gmail_token.json on a machine with a disk. A cloud
    # host with an ephemeral filesystem (Render, Spaces) gets it through the
    # GMAIL_TOKEN_JSON variable instead: run `auth` once on a laptop, paste
    # the file's contents into the host's secrets UI. Same token either way.
    token_json = env(TOKEN_ENV)
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_SCOPES)
    elif token_json:
        creds = Credentials.from_authorized_user_info(json.loads(token_json),
                                                      GMAIL_SCOPES)
    else:
        sys.exit("no Gmail token yet -- run: python tools/outreach.py auth"
                 " (on a diskless host, set GMAIL_TOKEN_JSON instead)")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        try:
            TOKEN_PATH.write_text(creds.to_json())
        except OSError:
            pass    # read-only or ephemeral disk: the refresh token in the env still works
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def cmd_auth(args):
    from dbconn import Db
    load_outreach_config(Db())            # per-segment token path and variable
    cid = env("GOOGLE_OAUTH_CLIENT_ID")
    csec = env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not csec:
        return gmail_service()          # prints the setup instructions and exits
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
    log("A browser window will open. Sign in with the %s mailbox (%s) and" % (SEGMENT, env(SENDER_ENV) or SENDER_ENV))
    log("approve. The token lands in %s (gitignored). For a cloud" % TOKEN_PATH.name)
    log("host with no disk, paste that file's contents into %s." % TOKEN_ENV)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json())
    log("token saved -- send and pull are now live")
    return 0


def cmd_send(args):
    """Send approved drafts. Rewritten after the hostile review (2026-08-31).

    THE PROTOCOL, in order, per row:
      1. CLAIM  update ... set status='sending' where id=%s and status='approved'
                -- atomic and committed BEFORE Gmail is touched. A concurrent
                run cannot claim the same row; a withdrawal that lands first
                wins (the claim simply fails); a crash leaves 'sending', which
                is visible and NOT re-sendable.
      2. SEND   the Gmail call.
      3. RECORD success -> 'sent' (guarded on status='sending').
                ANY exception -> 'send_unknown', because a timeout after
                Gmail accepted is indistinguishable from a failure here.
                The one-touch slot stays occupied either way; a human settles
                'send_unknown' against the Gmail Sent folder.

    THE CAP is genuinely daily now: rows already sent today count against it,
    so three invocations in a day still send at most daily_send_cap emails.

    VALIDATION before claiming: exactly one well-formed recipient address, no
    unfilled {{placeholders}} (an edit in the UI can introduce one), entity
    still in a sendable status (a company rejected after approval is skipped).
    Skipped rows get send_error set and are excluded from future selection,
    so they cannot wedge the queue -- they surface in the Attention folder.
    """
    from dbconn import Db
    db = Db()
    cfg = load_outreach_config(db)
    sender_addr = env(SENDER_ENV)
    if not sender_addr:
        sys.exit("%s is not set in .env (the sender mailbox for segment %s)" % (SENDER_ENV, SEGMENT))
    if "SET_ME" in json.dumps(cfg.get("sender", {})):
        sys.exit("refusing to send: config outreach.sender still contains SET_ME")

    daily_cap = int(cfg.get("daily_send_cap", 20))
    sent_today = db.run(lambda cur: (cur.execute(
        "select count(*) as n from outreach o join entities e on e.id = o.entity_id"
        " where o.direction='outbound' and o.status='sent' and o.sent_at::date = current_date"
        " and e.segment_id = (select id from segments where slug = %s)", (SEGMENT,)),
        cur.fetchone())[1][0])
    budget = min(max(0, daily_cap - sent_today), args.limit)
    if budget <= 0:
        log("daily cap reached: %d already sent today (cap %d)"
            % (sent_today, daily_cap))
        db.close(); return 0

    rows = db.run(lambda cur: (cur.execute("""
        select o.id, o.entity_id, o.subject, o.body,
               c.email, c.email_status, e.name, e.status
        from outreach o
        join entities e on e.id = o.entity_id
        left join contacts c on c.id = o.contact_id
        where o.status = 'approved' and o.direction = 'outbound'
          and o.send_error is null
          and e.segment_id = (select id from segments where slug = %s)
        order by o.created_at limit %s
    """, (SEGMENT, budget * 2)), cur.fetchall())[1])
    if not rows:
        log("nothing approved to send"); db.close(); return 0

    svc = gmail_service()
    email_re = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
    sent = 0

    def park(oid, why):
        """Take the row out of the sendable set, visibly, without burning cap."""
        db.run(lambda cur, _o=oid, _w=why: cur.execute(
            "update outreach set send_error=%s, updated_at=now()"
            " where id=%s and status='approved'", (_w, _o)))

    for oid, eid, subject, body, email, estatus, company, ent_status in rows:
        if sent >= budget:
            break
        problem = None
        if not email or not email_re.match(email.strip()):
            problem = "recipient address missing or malformed: %r" % (email,)
        elif estatus == "invalid":
            problem = "recipient failed verification"
        elif re.search(r"{{\w+}}", (subject or "") + (body or "")):
            problem = "unfilled {{placeholder}} in subject or body"
        elif ent_status not in ("shortlisted", "contacted"):
            problem = "entity is now '%s' -- approval predates that decision" % ent_status
        if problem:
            log("  %-32s PARKED: %s" % (company[:32], problem))
            park(oid, problem)
            continue

        claimed = db.run(lambda cur, _o=oid: (cur.execute(
            "update outreach set status='sending', updated_at=now()"
            " where id=%s and status='approved' returning id", (_o,)),
            cur.fetchone())[1])
        if not claimed:
            log("  %-32s skipped: no longer approved" % company[:32])
            continue

        msg = MIMEText(body)
        msg["to"], msg["from"], msg["subject"] = email.strip(), sender_addr, subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            resp = svc.users().messages().send(
                userId="me", body={"raw": raw}).execute()
        except Exception as e:
            # The message MAY have been delivered -- a timeout after accept
            # looks exactly like this. Never auto-mark 'failed': that would
            # free the one-touch slot for a company that might have the email
            # in its inbox already.
            log("  %-32s UNKNOWN OUTCOME: %s" % (company[:32], str(e)[:70]))
            db.run(lambda cur, _o=oid, _err=str(e)[:400]: cur.execute(
                "update outreach set status='send_unknown', send_error=%s,"
                " updated_at=now() where id=%s and status='sending'", (_err, _o)))
            continue
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
        log("  %-32s SENT -> %s" % (company[:32], email))
    db.close()
    log("\n%d sent this run; %d sent today total (cap %d)"
        % (sent, sent_today + sent, daily_cap))
    return 0


def cmd_pull(args):
    """Fetch replies to sent threads. Hardened per the review:

    * OUR OWN messages in a thread are never ingested as prospect replies --
      anything sent by GMAIL_SENDER_ADDRESS or carrying the SENT/DRAFT label
      is skipped. Before this, the owner's own follow-up became a 'reply'
      and the triage classifier scored our own email.
    * idempotent by unique index on gmail_message_id + on conflict do nothing,
      so a retried commit (dbconn's reconnect path) cannot duplicate a row.
    * one thread failing to fetch no longer aborts the run -- later threads
      still get their replies; errors are reported at the end.
    """
    from dbconn import Db
    db = Db()
    load_outreach_config(db)              # per-segment sender and token
    sender_addr = (env(SENDER_ENV) or "").lower()
    svc = gmail_service()
    threads = db.run(lambda cur: (cur.execute("""
        select o.gmail_thread_id, o.entity_id, o.contact_id
        from outreach o join entities e on e.id = o.entity_id
        where o.status = 'sent' and o.gmail_thread_id is not null
          and e.segment_id = (select id from segments where slug = %s)
    """, (SEGMENT,)), cur.fetchall())[1])
    if not threads:
        log("no sent threads to poll"); db.close(); return 0
    found = errors = 0
    for tid, eid, cid in threads:
        try:
            t = svc.users().threads().get(userId="me", id=tid,
                                          format="full").execute()
        except Exception as e:
            errors += 1
            log("  thread %s: fetch failed (%s) -- continuing" % (tid, type(e).__name__))
            continue
        for m in t.get("messages", []):
            labels = set(m.get("labelIds") or [])
            if "SENT" in labels or "DRAFT" in labels:
                continue                      # ours, or not yet sent by anyone
            headers = {h["name"].lower(): h["value"]
                       for h in m.get("payload", {}).get("headers", [])}
            if sender_addr and sender_addr in (headers.get("from") or "").lower():
                continue                      # ours, sent from another client
            mid = m["id"]
            body = _plain_body(m.get("payload", {}))
            inserted = db.run(lambda cur, _t=tid, _e=eid, _c=cid, _m=mid,
                              _s=headers.get("subject", ""), _b=body[:8000]: (
                cur.execute(
                    "insert into outreach (entity_id, contact_id, direction,"
                    " subject, body, status, gmail_message_id, gmail_thread_id)"
                    " values (%s,%s,'inbound',%s,%s,'received',%s,%s)"
                    " on conflict (gmail_message_id) where gmail_message_id"
                    " is not null do nothing returning id",
                    (_e, _c, _s, _b, _m, _t)),
                cur.fetchone())[1])
            if inserted:
                found += 1
                log("  new reply on thread %s" % tid)
    db.close()
    log("\n%d new repl(ies); %d thread error(s). Next: python tools/outreach.py triage"
        % (found, errors))
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
TRIAGE_PROMPT = """You triage replies to a B2B partnership email from TVF (an
Indian studio proposing co-production/format licensing to US production
companies). Classify the reply below.

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
    from dbconn import Db
    db = Db()
    rows = db.run(lambda cur: (cur.execute(
        "select id, body from outreach where direction='inbound'"
        " and status='received' limit %s", (args.limit,)), cur.fetchall())[1])
    if not rows:
        log("no untriaged replies"); db.close(); return 0
    client = anthropic.Anthropic(api_key=key)
    for oid, body in rows:
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
        db.run(lambda cur, _o=oid, _l=label, _r=reason: cur.execute(
            "update outreach set status='triaged', triage=%s, triage_reason=%s,"
            " updated_at=now() where id=%s", (_l, _r, _o)))
        log("  %s  %s" % (label.ljust(12), reason[:70]))
    db.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft"); d.add_argument("--limit", type=int, default=20)
    d.add_argument("--template", default=None, help="template key; omit to pick by the segment when-conditions")
    d.add_argument("--dry-run", action="store_true")
    sub.add_parser("auth")
    s = sub.add_parser("send"); s.add_argument("--limit", type=int, default=20)
    sub.add_parser("pull")
    t = sub.add_parser("triage"); t.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    return {"draft": cmd_draft, "auth": cmd_auth, "send": cmd_send,
            "pull": cmd_pull, "triage": cmd_triage}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
