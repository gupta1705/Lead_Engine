"""reply_alert.py -- tell the person a lead wrote back (owner, 2026-10-28: "Let's work on making the replies better
how do we send a alert", and then, of email / Slack / Google Chat / WhatsApp: "Email").

Run by `outreach.py pull` for each person's own Gmail (sql/45), after the replies are read:

  * alert_new: each new reply (not a bounce) is read by the model -- what kind of reply it is, and one line on what
    it says -- then starred and labelled "Lead replied" in the Gmail that holds the thread, and a short alert goes
    into that person's own inbox: who replied, the model's reading, the first lines, and where to mark it. An
    auto-reply (out of office) gets no alert and no star: the reminder below still catches a misread one.
  * remind: once a day, on weekdays from 10:00 India time, one reminder per person of the replies nobody has marked
    Positive or Negative for over a day.

The alert is put into the mailbox with Gmail's messages.import, never sent: it goes to no one, it never leaves the
person's own Gmail, it is not in their Sent, and it never counts against their 50 a day. It can never reach the
lead. Each reply is claimed before it is alerted (two pulls at once never alert twice), tried at most MAX_ATTEMPTS
times, and a failure never stops the pull that called it.
"""
import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LABEL = "Lead replied"
# the model's reading of a reply -> what the alert calls it
KINDS = {
    "interested": "Interested",
    "question": "Has a question",
    "not_now": "Not now",
    "referral": "Points to someone else",
    "not_interested": "Not interested",
    "unsubscribe": "Asks not to be emailed",
    "auto_reply": "Auto-reply",
    "other": "Reply",
}
MAX_ATTEMPTS = 3
IST = timezone(timedelta(hours=5, minutes=30))
REMIND_FROM_HOUR = 10          # India time, weekdays
REMIND_AFTER_HOURS = 24

READ_SYSTEM = """You read one reply to a cold outreach email our studio sent to a company or a creator. Say what kind \
of reply it is, and in one short sentence what they said or want.

Kinds:
interested      wants to talk, a call, the deck, prices or samples, or says yes
question        asks something before deciding
not_now         maybe later, busy now, come back in some weeks or months
referral        not the right person: names, copies in or forwards to someone else
not_interested  declines
unsubscribe     asks not to be emailed again
auto_reply      out of office, an automatic acknowledgement or ticket number, a "no longer here" notice
other           anything else

Answer with JSON only: {"kind": "...", "summary": "..."}. The summary is in English, at most 25 words, and says only \
what the reply says: a time they offered, the person they point to, the question they ask."""

QUOTE_START = re.compile(r"^\s*(On .{0,200}wrote:|-{2,}\s*Original Message\s*-{2,}|From: .+|Sent from my \w+)\s*$",
                         re.I)


def base_url():
    """The app as people reach it: PUBLIC_BASE_URL, else Render's own address for the service, else the live one."""
    for k in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        v = (os.environ.get(k) or "").strip()
        if v:
            return v.rstrip("/")
    return "https://tvf-lead-engine.onrender.com"


def fresh_text(body):
    """What they wrote, without the quoted email under it."""
    out = []
    for line in (body or "").replace("\r\n", "\n").split("\n"):
        if QUOTE_START.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line.rstrip())
    text = "\n".join(out).strip()
    return re.sub(r"\n{3,}", "\n\n", text) or (body or "").strip()


def read_reply(subject, body, chat=None):
    """-> (kind, summary), or (None, None) when the model is not there or answers nonsense."""
    try:
        if chat is None:
            import llm
            chat = llm._chat
            model = llm.DEFAULT_MODEL
        else:
            model = "test"
        raw = chat([{"role": "system", "content": READ_SYSTEM},
                    {"role": "user", "content": "Subject: %s\n\n%s" % (subject or "", fresh_text(body)[:4000])}],
                   model, temperature=0.0, max_tokens=700, timeout=25, retries=1)
        m = re.search(r"\{.*\}", raw or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        return None, None
    kind = str(data.get("kind") or "").strip().lower().replace(" ", "_").replace("-", "_")
    summary = re.sub(r"\s+", " ", str(data.get("summary") or "")).strip()[:300] or None
    if kind not in KINDS:
        kind = "other" if summary else None
    return kind, summary


# ------------------------------------------------------------------ gmail
def _label_id(svc, cache):
    if "id" in cache:
        return cache["id"]
    labels = svc.users().labels().list(userId="me").execute().get("labels") or []
    got = next((lb["id"] for lb in labels if (lb.get("name") or "").lower() == LABEL.lower()), None)
    if not got:
        got = svc.users().labels().create(userId="me", body={
            "name": LABEL, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()["id"]
    cache["id"] = got
    return got


def _from_header(svc, message_id):
    try:
        m = svc.users().messages().get(userId="me", id=message_id, format="metadata",
                                       metadataHeaders=["From"]).execute()
        for h in (m.get("payload") or {}).get("headers") or []:
            if h.get("name", "").lower() == "from":
                return h.get("value")
    except Exception:
        pass
    return None


def deliver(svc, address, subject, text, html):
    """Put one message into this person's own inbox, unread: Gmail's import, so nothing is sent to anyone."""
    msg = MIMEMultipart("alternative")
    msg["From"] = '"Lead Engine" <%s>' % address
    msg["To"] = address
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=(address.split("@")[-1] or "lead-engine"))
    msg["X-Lead-Engine"] = "reply-alert"
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return svc.users().messages().import_(userId="me", body={"raw": raw, "labelIds": ["INBOX", "UNREAD", "IMPORTANT"]},
                                          neverMarkSpam=True, internalDateSource="dateHeader").execute()


# ------------------------------------------------------------------ the alert
def _who(from_header, contact_name, contact_email):
    name, addr = parseaddr(from_header or "")
    if addr:
        return ("%s <%s>" % (name, addr)) if name and name.lower() != addr.lower() else addr
    if contact_name and contact_email:
        return "%s <%s>" % (contact_name, contact_email)
    return contact_name or contact_email or "Someone"


def alert_message(r, kind, summary, who):
    """-> (subject, text, html) for one reply. r: the row ALERT_SQL gives."""
    company, project = r["company"] or "A lead", r["project"] or "the Lead Engine"
    label = KINDS.get(kind) if kind else None
    subject = ("%s replied: %s" % (company, label)) if label and kind != "other" else ("%s replied to your email" % company)
    said = fresh_text(r["body"])
    said = said[:700] + ("..." if len(said) > 700 else "")
    link = base_url() + "/#outreach/replies"
    reading = ("%s: %s" % (label, summary) if summary else label) if label else None
    lines = ["%s at %s replied to \"%s\" (%s)." % (who, company, r["opener_subject"] or r["subject"] or "your email", project), ""]
    if reading:
        lines += ["What it says: %s" % reading, "(read by AI: check the reply itself before you act on it)", ""]
    lines += ["Their reply:", ""] + ["  " + ln for ln in said.split("\n")] + [
        "",
        "Answer it from the thread in this Gmail: it is starred and labelled \"%s\"." % LABEL,
        "Then mark it Positive or Negative in the Lead Engine (%s, Outreach, Replies): %s" % (project, link)]
    text = "\n".join(lines)
    html = ("<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#172b4d\">"
            "<p><b>%s</b> at <b>%s</b> replied to &ldquo;%s&rdquo; (%s).</p>"
            % (escape(who), escape(company), escape(r["opener_subject"] or r["subject"] or "your email"), escape(project))
            + ("<p style=\"background:#e9f2ff;padding:10px 12px;border-radius:6px\"><b>What it says:</b> %s<br>"
               "<span style=\"color:#626f86;font-size:12px\">Read by AI: check the reply itself before you act on it."
               "</span></p>" % escape(reading) if reading else "")
            + "<p style=\"margin-bottom:4px\"><b>Their reply</b></p>"
            "<blockquote style=\"margin:0;padding:8px 12px;border-left:3px solid #c1c7d0;color:#44546f;"
            "white-space:pre-wrap\">%s</blockquote>" % escape(said)
            + "<p>Answer it from the thread in this Gmail: it is starred and labelled &ldquo;%s&rdquo;.</p>" % LABEL
            + "<p><a href=\"%s\">Mark it in the Lead Engine</a> (%s, Outreach, Replies).</p></div>"
            % (escape(link), escape(project)))
    return subject, text, html


ALERT_SQL = """
select i.id::text, i.gmail_message_id, i.gmail_thread_id, i.subject, i.body, e.name,
       coalesce(nullif(s.config->'ui'->>'project_name', ''), s.name), c.full_name, c.email,
       (select o.subject from outreach o where o.entity_id = i.entity_id and o.direction = 'outbound'
           and o.status = 'sent' and o.gmail_thread_id = i.gmail_thread_id order by o.sent_at limit 1)
from outreach i
join entities e on e.id = i.entity_id
join segments s on s.id = e.segment_id
left join contacts c on c.id = i.contact_id
where i.direction = 'inbound' and i.alerted_at is null and i.gmail_thread_id = any(%s)
  and coalesce(i.triage, '') <> 'neutral'                -- a bounce notice, or a reply someone called an auto-reply
  and i.alert_attempts < %s
order by i.created_at"""
ALERT_COLS = ("id", "message_id", "thread_id", "subject", "body", "company", "project", "contact_name",
              "contact_email", "opener_subject")

CLAIM_SQL = """
update outreach set alert_claimed_at = now(), alert_attempts = alert_attempts + 1
where id = %s and alerted_at is null and alert_attempts < %s
  and (alert_claimed_at is null or alert_claimed_at < now() - interval '10 minutes')
returning id"""


def alert_new(db, svc, box, thread_ids, log=print, chat=None):
    """Alert this person of every new reply in these threads (the ones read through their Gmail). -> alerts put in."""
    thread_ids = [t for t in thread_ids if t]
    if not thread_ids:
        return 0
    rows = db.run(lambda cur: (cur.execute(ALERT_SQL, (thread_ids, MAX_ATTEMPTS)), cur.fetchall())[1])
    cache, done = {}, 0
    for row in rows:
        r = dict(zip(ALERT_COLS, row))
        if not db.run(lambda cur, _i=r["id"]: (cur.execute(CLAIM_SQL, (_i, MAX_ATTEMPTS)), cur.fetchone())[1]):
            continue                                  # another pull has it, or it is done
        kind, summary = read_reply(r["subject"], r["body"], chat=chat)
        note = ("AI's reading: %s%s" % (KINDS[kind], (": " + summary) if summary else "")) if kind else None
        try:
            if kind != "auto_reply":
                try:
                    svc.users().messages().modify(userId="me", id=r["message_id"], body={
                        "addLabelIds": [_label_id(svc, cache), "STARRED", "IMPORTANT"]}).execute()
                except Exception as e:                # the alert matters more than the star: go on
                    log("  reply %s: could not star it (%s)" % (r["id"], str(e)[:100]))
                who = _who(_from_header(svc, r["message_id"]), r["contact_name"], r["contact_email"])
                subject, text, html = alert_message(r, kind, summary, who)
                deliver(svc, box["address"], subject, text, html)
                done += 1
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:300])
            db.run(lambda cur, _i=r["id"], _e=err: cur.execute(
                "update outreach set alert_error = %s, alert_claimed_at = null where id = %s", (_e, _i)))
            log("  reply %s: alert failed (%s) -- tried again on the next pull" % (r["id"], err[:120]))
            continue
        db.run(lambda cur, _i=r["id"], _k=kind, _n=note: cur.execute(
            "update outreach set alerted_at = now(), alert_error = null, reply_kind = %s,"
            " triage_reason = coalesce(triage_reason, %s), updated_at = now() where id = %s", (_k, _n, _i)))
        log("  reply %s: %s" % (r["id"], ("alert put in %s's inbox (%s)" % (box["address"], KINDS.get(kind, "not read")))
                                 if kind != "auto_reply" else "an auto-reply: no alert"))
    return done


# ------------------------------------------------------------------ the daily reminder
WAITING_SQL = """
select i.id::text, i.created_at, e.name, coalesce(nullif(s.config->'ui'->>'project_name', ''), s.name),
       c.full_name, i.reply_kind, i.triage_reason
from outreach i
join entities e on e.id = i.entity_id
join segments s on s.id = e.segment_id
left join contacts c on c.id = i.contact_id
where i.direction = 'inbound' and i.status = 'received' and i.triage is null
  and i.created_at < %s - make_interval(hours => %s)
  and e.status not in ('rejected', 'archived')
  and exists (select 1 from outreach x join user_mailboxes m on lower(m.address) = lower(x.sender_address)
              where x.gmail_thread_id = i.gmail_thread_id and x.direction = 'outbound' and x.status = 'sent'
                and lower(m.user_email) = lower(%s))
order by i.created_at"""


def _ago(then, now):
    days = int((now - then).total_seconds() // 86400)
    return "yesterday" if days <= 1 else "%d days ago" % days


def reminder_message(rows, now):
    n = len(rows)
    subject = "%d %s waiting for you" % (n, "reply is" if n == 1 else "replies are")
    link = base_url() + "/#outreach/replies"
    items = []
    for _id, at, company, project, contact, kind, note in rows:
        reading = note[len("AI's reading: "):] if note and note.startswith("AI's reading: ") else (KINDS.get(kind) or "")
        items.append(("%s%s, %s, %s" % (company, (" (%s)" % contact) if contact else "", project, _ago(at, now)), reading))
    text = "\n".join(
        ["Nobody has marked these replies Positive or Negative yet:", ""]
        + ["- %s%s" % (head, ("\n    " + reading) if reading else "") for head, reading in items]
        + ["", "Answer each from its thread in your Gmail (labelled \"%s\"), then mark it in the Lead Engine, Outreach,"
               " Replies: %s" % (LABEL, link),
           "Marked replies stop showing here."])
    html = ("<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#172b4d\">"
            "<p>Nobody has marked these replies Positive or Negative yet:</p><ul>"
            + "".join("<li><b>%s</b>%s</li>" % (escape(head), ("<br><span style=\"color:#44546f\">%s</span>"
                                                               % escape(reading)) if reading else "")
                      for head, reading in items)
            + "</ul><p>Answer each from its thread in your Gmail (labelled &ldquo;%s&rdquo;), then "
              "<a href=\"%s\">mark it in the Lead Engine</a> (Outreach, Replies). Marked replies stop showing here.</p>"
              "</div>" % (LABEL, escape(link)))
    return subject, text, html


def remind(db, svc, box, log=print, now=None):
    """Once a day per person (weekdays, from 10:00 India time): the replies to their emails nobody has marked for a
    day. -> True when a reminder was put in."""
    now = now or datetime.now(timezone.utc)
    ist = now.astimezone(IST)
    if ist.weekday() >= 5 or ist.hour < REMIND_FROM_HOUR:
        return False
    person = box["user_email"]
    rows = db.run(lambda cur: (cur.execute(WAITING_SQL, (now, REMIND_AFTER_HOURS, person)), cur.fetchall())[1])
    if not rows:
        return False
    day = ist.date()
    claimed = db.run(lambda cur: (cur.execute(
        "insert into reply_reminders (user_email, day, replies) values (lower(%s), %s, %s)"
        " on conflict do nothing returning day", (person, day, len(rows))), cur.fetchone())[1])
    if not claimed:
        return False                                  # today's is in already
    try:
        deliver(svc, box["address"], *reminder_message(rows, now))
    except Exception as e:
        # give the claim back, so the next pull tries again
        db.run(lambda cur: cur.execute("delete from reply_reminders where user_email = lower(%s) and day = %s",
                                       (person, day)))
        log("  %s: the daily reminder failed (%s) -- tried again on the next pull" % (box["address"], str(e)[:120]))
        return False
    log("  %s: reminder of %d unmarked repl(ies) put in the inbox" % (box["address"], len(rows)))
    return True
