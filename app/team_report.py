"""team_report.py -- Reports, Team: what each person sent, over a time span, and how it was answered.

The owner, 2026-10-27: "in reports section i want you to add a section which allows to see how many outreaches each
person has sent in different timelines their response rate and all".

    GET /api/reports/team?period=7d&scope=all

period   today (since midnight, India's clock), 7d, 30d, 90d, all
scope    all (every project) or project (the one the page is on)

WHAT IS COUNTED, PER PERSON
  sent              first emails that went out in the span, credited to the person who approved them (their Gmail,
                    their name); one per company, so this is also companies reached
  followups         follow-ups that went out in the span, credited to whoever's thread it is (they go from the first
                    email's Gmail, signed by its sender)
  replied           of those first emails, how many companies wrote back, at any time since. An auto-reply or a
                    bounce notice (triaged 'neutral') is not a reply, exactly as follow-ups count it
                    (tools/outreach_policy.py). reply_rate = replied / sent
  positive/negative replies a person marked so; positive_rate = positive / sent
  bounced           first emails whose address rejected them (stopped_reason 'bounced...'); bounce_rate = / sent
  median_reply_hours  the typical time from a first email to its first reply
  median_answer_hours the typical time from that first reply to our first answer: written in the thread (the pull
                    sees it), or marked answered another way (sql/46; the owner, 2026-10-29)
  waiting_on_us     companies whose real reply nobody on our side has answered yet (now, not limited to the span)
  approved_waiting  approved now and not gone yet (not limited to the span)
  series            first emails sent per day (spans up to 30 days, India's days) or per week (90 days, all)
Every person with a login is listed, so a person who sent nothing shows as nothing; anyone who approved emails and
has since lost their login is listed too.
"""
import datetime as dt
import os
import re
import sys
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

IST = ZoneInfo("Asia/Kolkata")
PERIODS = {"today": "Today", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days", "all": "All time"}

OPENERS = """
openers as (
  select o.id, o.entity_id, lower(o.approved_by) as who, o.sent_at, s.slug,
         coalesce(o.stopped_reason, '') like 'bounced%%' as bounced
  from outreach o join entities e on e.id = o.entity_id join segments s on s.id = e.segment_id
  where o.direction = 'outbound' and coalesce(o.sequence_step, 0) = 0 and o.status = 'sent'
    and o.approved_by is not null and o.sent_at is not null
    and (%(since)s::timestamptz is null or o.sent_at >= %(since)s::timestamptz)
    and (%(slug)s::text is null or s.slug = %(slug)s::text)
)"""

PER_PERSON = "with " + OPENERS + """,
replies as (
  select op.id, min(__RECEIVED__) as first_at, min(r.answered_at) as answered_at,
         bool_or(r.triage = 'positive') as pos, bool_or(r.triage = 'negative') as neg
  from openers op
  join outreach r on r.entity_id = op.entity_id and r.direction = 'inbound'
   and r.triage is distinct from 'neutral' and r.created_at >= op.sent_at
  group by op.id
)
select op.who, (op.who is null) as total,
       count(*) as sent, count(rp.id) as replied,
       count(*) filter (where rp.pos) as positive, count(*) filter (where rp.neg) as negative,
       count(*) filter (where op.bounced) as bounced, max(op.sent_at) as last_sent_at,
       percentile_cont(0.5) within group (order by extract(epoch from rp.first_at - op.sent_at) / 3600.0)
         as median_reply_hours,
       percentile_cont(0.5) within group (order by extract(epoch from rp.answered_at - rp.first_at) / 3600.0)
         as median_answer_hours
from openers op left join replies rp on rp.id = op.id
group by grouping sets ((op.who), ())
"""

FOLLOWUPS = """
select lower(p.approved_by) as who, count(*) as n
from outreach f join outreach p on p.id = f.parent_id
join entities e on e.id = f.entity_id join segments s on s.id = e.segment_id
where f.direction = 'outbound' and coalesce(f.sequence_step, 0) > 0 and f.status = 'sent' and p.approved_by is not null
  and (%(since)s::timestamptz is null or f.sent_at >= %(since)s::timestamptz)
  and (%(slug)s::text is null or s.slug = %(slug)s::text)
group by 1
"""

WAITING = """
select lower(o.approved_by) as who, count(*) as n
from outreach o join entities e on e.id = o.entity_id join segments s on s.id = e.segment_id
where o.direction = 'outbound' and o.status in ('approved', 'sending') and o.approved_by is not null
  and (%(slug)s::text is null or s.slug = %(slug)s::text)
group by 1
"""

# the companies waiting on this person's answer now (not limited to the span): a real reply to their thread that
# nobody on our side has answered (sql/46)
WAITING_ON_US = """
select lower(o.approved_by) as who, count(distinct o.entity_id) as n
from outreach o join entities e on e.id = o.entity_id join segments s on s.id = e.segment_id
where o.direction = 'outbound' and coalesce(o.sequence_step, 0) = 0 and o.status = 'sent' and o.approved_by is not null
  and e.status not in ('rejected', 'archived')
  and exists (select 1 from outreach r where r.entity_id = o.entity_id and __UNANSWERED__)
  and (%(slug)s::text is null or s.slug = %(slug)s::text)
group by 1
"""

BY_PROJECT = "with " + OPENERS + " select who, slug, count(*) as n from openers group by 1, 2"

SERIES = "with " + OPENERS + """
select who, date_trunc(%(bucket)s, sent_at at time zone 'Asia/Kolkata')::date as d, count(*) as n
from openers group by 1, 2
"""


def span(period, now=None):
    """-> (since as an aware datetime or None, bucket 'day' or 'week', label)."""
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(IST)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), "day", PERIODS[period]
    if period in ("7d", "30d", "90d"):
        days = int(period[:-1])
        return now - dt.timedelta(days=days), ("day" if days <= 30 else "week"), PERIODS[period]
    return None, "week", PERIODS["all"]


def buckets(since, bucket, first=None, now=None):
    """Every bucket start (an India date) from the span's start (or the first send) to today."""
    today = (now or dt.datetime.now(dt.timezone.utc)).astimezone(IST).date()
    start = since.astimezone(IST).date() if since else (first or today)
    if bucket == "week":
        start -= dt.timedelta(days=start.weekday())
        step = dt.timedelta(days=7)
    else:
        step = dt.timedelta(days=1)
    out = []
    while start <= today and len(out) < 400:
        out.append(start)
        start += step
    return out


def rate(n, d):
    return round(100.0 * n / d, 1) if d else None


def project_name(slug, names):
    """The project's name; an archived copy (history-<slug>-<date>, kept when a project moved to Apollo on
    2026-10-19) is its project, "before <date>": what was sent from it is still that person's outreach."""
    names = names or {}
    if slug in names:
        return names[slug]
    m = re.fullmatch(r"history-(.+)-(\d{4})(\d{2})(\d{2})", slug or "")
    if m:
        when = dt.date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        return "%s (before %d %s)" % (names.get(m.group(1), m.group(1)), when.day, when.strftime("%b"))
    return slug


def _policy():
    """tools/outreach_policy.py: what a reply waiting on us is (sql/46), as the pull and the reminder have it."""
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import outreach_policy
    return outreach_policy


def report(cur, period, slug=None, names=None, now=None):
    if period not in PERIODS:
        raise ValueError("period is one of: %s" % ", ".join(PERIODS))
    since, bucket, label = span(period, now)
    p = {"since": since, "slug": slug, "bucket": bucket}
    pol = _policy()
    cur.execute(PER_PERSON.replace("__RECEIVED__", pol.received("r")), p)
    rows = [dict(r) for r in cur.fetchall()]
    total = next((r for r in rows if r["total"]), None)
    per = {r["who"]: r for r in rows if not r["total"]}
    cur.execute(FOLLOWUPS, p)
    fu = {r["who"]: r["n"] for r in cur.fetchall()}
    cur.execute(WAITING, p)
    waiting = {r["who"]: r["n"] for r in cur.fetchall()}
    cur.execute(WAITING_ON_US.replace("__UNANSWERED__", pol.unanswered("r")), p)
    on_us = {r["who"]: r["n"] for r in cur.fetchall()}
    cur.execute(BY_PROJECT, p)
    proj = {}
    for r in cur.fetchall():
        proj.setdefault(r["who"], []).append({"slug": r["slug"], "name": project_name(r["slug"], names),
                                              "sent": r["n"]})
    cur.execute(SERIES, p)
    series_rows = [dict(r) for r in cur.fetchall()]
    first = min((r["d"] for r in series_rows), default=None)
    keys = buckets(since, bucket, first, now) if period != "today" else []
    index = {k: i for i, k in enumerate(keys)}
    series = {}
    for r in series_rows:
        if r["d"] in index:
            series.setdefault(r["who"], [0] * len(keys))[index[r["d"]]] = r["n"]
    cur.execute("select lower(email) as who, name, title from app_users")
    people = {r["who"]: {"name": r["name"], "title": r["title"], "has_login": True} for r in cur.fetchall()}
    for who in set(per) | set(fu) | set(waiting) | set(on_us):
        people.setdefault(who, {"name": None, "title": None, "has_login": False})

    def hours(v):
        return round(float(v), 1) if v is not None else None

    def view(who, r, n_fu, n_wait, n_on_us, info):
        sent = int(r["sent"]) if r else 0
        rep, pos, neg, bnc = [int(r[k]) if r else 0 for k in ("replied", "positive", "negative", "bounced")]
        out = {"sent": sent, "followups": int(n_fu or 0), "replied": rep, "reply_rate": rate(rep, sent),
               "positive": pos, "positive_rate": rate(pos, sent), "negative": neg, "bounced": bnc,
               "bounce_rate": rate(bnc, sent), "median_reply_hours": hours(r.get("median_reply_hours") if r else None),
               "median_answer_hours": hours(r.get("median_answer_hours") if r else None),
               "waiting_on_us": int(n_on_us or 0), "approved_waiting": int(n_wait or 0),
               "last_sent_at": r["last_sent_at"].isoformat() if r and r.get("last_sent_at") else None}
        if who is not None:
            out.update(account=who, name=info.get("name"), title=info.get("title"), has_login=info.get("has_login"),
                       projects=sorted(proj.get(who, []), key=lambda x: -x["sent"]),
                       series=series.get(who, [0] * len(keys)))
        return out
    people_out = [view(who, per.get(who), fu.get(who), waiting.get(who), on_us.get(who), info)
                  for who, info in people.items()]
    people_out.sort(key=lambda x: (-x["sent"], -x["followups"], -x["approved_waiting"], (x["name"] or x["account"]).lower()))
    totals = view(None, total, sum(fu.values()), sum(waiting.values()), sum(on_us.values()), {})
    totals["series"] = [sum(x["series"][i] for x in people_out) for i in range(len(keys))]
    return {"period": period, "label": label, "since": since.isoformat() if since else None, "bucket": bucket,
            "buckets": [k.isoformat() for k in keys], "scope": "project" if slug else "all", "project": slug,
            "people": people_out, "totals": totals}


def build_router(cursor, current_segment, project_names):
    r = APIRouter()

    @r.get("/api/reports/team")
    def team(request: Request, period: str = "7d", scope: str = "all"):
        if scope not in ("all", "project"):
            raise HTTPException(400, "scope is all or project")
        slug = current_segment(request) if scope == "project" else None
        try:
            with cursor() as cur:
                return report(cur, period, slug, names=project_names())
        except ValueError as e:
            raise HTTPException(400, str(e))

    return r
