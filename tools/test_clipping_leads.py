#!/usr/bin/env python3
"""test_clipping_leads.py -- better LCX Clipping leads (the owner, 2026-11-12: "Apply all these suggested changes"),
as a table.

    python tools/test_clipping_leads.py          (after python tools/run_sql.py sql/47_clipping_leads.sql)

Pure checks, then the real database inside ONE transaction that is rolled back. Checked:

  * who reads an address (person_reachable): a named host's own mailbox, a person's, a business inbox, a shared
    inbox, a feed or support address, none
  * whether there is video (video_source): a channel; none after every lookup; not known yet; never for a network
  * a channel posting mostly shorts is marked as already clipping
  * publishers' network leads: two or more shows, majors and people left out, the shared address chosen
  * contact_rank: a feed-only address is never written to; contact_source_bonus: the site's address first, only
    where the project prefers it
  * gates after shortlisting: a lead the engine shortlisted is archived and its unsent emails withdrawn; one a person
    shortlisted stands; a contacted lead keeps its history and loses only an unsent follow-up
  * a reply from an unread inbox: not a reply, the address retired, follow-ups stopped, no alert
  * Reports, Who replies: counted by kind of lead, a rate only from 30 sent
Exit code 1 on any failure.
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("SESSION_SECRET", "zz-clip-test-" + uuid.uuid4().hex)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import discover_clipping_networks as nets  # noqa: E402
import enrich_clipping as ec  # noqa: E402
import reply_alert as ra  # noqa: E402
import yt_api  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


class TxDb:
    def __init__(self, conn):
        self.conn = conn

    def run(self, fn):
        with self.conn.cursor() as cur:
            return fn(cur)


def pure():
    print("-- who reads an address")
    pr = ec.person_reachable
    check("a named host's own mailbox", pr("maya@show.com", True), 1.0)
    check("a person's mailbox, no host named; a business inbox", (pr("maya@gmail.com", False), pr("business@show.com", True)), (0.5, 0.5))
    check("a shared inbox", (pr("info@show.com", True), pr("hello@show.com", False)), (0.25, 0.25))
    check("a feed, support or no-reply address; none", (pr("feeds@show.com", True), pr("support@x.com", True),
                                                        pr("noreply@x.com", True), pr(None, True)), (0.0, 0.0, 0.0, 0.0))

    print("\n-- whether there is video")
    vs = ec.video_source
    check("a channel on record", vs({}, {"channel_id": "x"}, {}, "show.com", None), True)
    check("no link in the feed, the site read and none found: no video", vs({}, None, {"site_youtube_lookup": {"url": None}}, "show.com", None), False)
    check("  no site at all, no link in the feed: no video", vs({}, None, {}, None, None), False)
    check("  the channel lookup found nothing: no video", vs({"youtube_url": "u"}, None, {"youtube_lookup": {"result": "not found"}}, None, None), False)
    check("the site still to read: not known yet", vs({}, None, {}, "show.com", None), None)
    check("  a link not yet profiled, or a lookup to retry: not known yet",
          (vs({"youtube_url": "u"}, None, {}, None, None), vs({}, None, {"site_youtube_error": {"at": "x"}}, "show.com", None)), (None, None))
    check("  a network or a production house: never asked", (vs({}, None, {}, None, "network"), vs({}, None, {}, None, "production_house")), (None, None))

    print("\n-- already clipping")
    def channel(share):
        return {"recent": {"long_count": 10, "shorts_count": int(share * 30), "medium_count": 0, "shorts_share": share,
                           "uploads_per_month": 4, "last_upload_at": None}, "video_count": 300, "subscribers": 50000,
                "monetization_hits": [], "country": "", "language": "en", "title": "x", "description": "", "topics": []}
    marks = [yt_api.inputs_from_channel(channel(s), {}, None).get("already_clips") for s in (0.05, 0.35, 0.72)]
    check("under 30% shorts: no; 30-50%: half; over half: yes", marks, [0.0, 0.5, 1.0])

    print("\n-- publishers' network leads")
    def show(name, pub, email=None, site=None, eps=80):
        pf = {"owner_email": email, "website": site, "episode_count": eps, "cadence_per_month": 4, "monetization_hits": ["sponsor"]}
        return (name, None, "archived", {"discovery_raw": {"apple_podcasts": {"artist": pub, "podcast_feed": pf}},
                                         "podcast_feed": pf, "scoring_inputs": {"activity_signal": "active", "language_match": 1.0}})
    rows = [show("A1", "Evergreen Media", "info@evergreen.example", "https://evergreen.example/a"),
            show("A2", "Evergreen Media", "info@evergreen.example", "https://evergreen.example/b"),
            show("A3", "Evergreen Media", "host@gmail.com"),
            show("B1", "iHeartPodcasts", "x@iheart.example"), show("B2", "iHeartPodcasts", "x@iheart.example"),
            show("C1", "Maya Linden"), show("C2", "Maya Linden"),
            show("D1", "Lone Studio")]
    got = nets.group_leads(rows, ["iheartpodcast"], 2)
    check("two shows or more, majors and a person's name left out", sorted(got), ["evergreen media"])
    ev = got["evergreen media"]
    check("  its shows, episodes added up, the address its shows share, kind network",
          (ev["raw"]["network"]["show_count"], ev["raw"]["network"]["total_episodes"], ev["email"], ev["raw"]["kind"]),
          (3, 240, "info@evergreen.example", "network"))
    check("  scored as a company that decides for its shows", (ev["raw"]["scoring_inputs"]["company_run"],
                                                                 ev["raw"]["scoring_inputs"]["archive_size"]), (1.0, 1.0))


def database():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        tag = uuid.uuid4().hex[:6]
        cfg = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
        cfg.pop("sourcing", None)
        slug = "zz-clip-" + tag
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ Clip', 'creator_show', %s, true)"
                    " returning id", (slug, json.dumps(cfg)))
        seg = cur.fetchone()["id"]
        other = "zz-clip-other-" + tag
        cfg2 = dict(cfg, enrichment={})
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, 'ZZ Other', 'creator_show', %s, true)"
                    " returning id", (other, json.dumps(cfg2)))
        seg2 = cur.fetchone()["id"]

        def lead(s, name, status, si=None, meta=None):
            m = dict(meta or {}, scoring_inputs=si or {})
            cur.execute("insert into entities (segment_id, name, domain, source, metadata, status) values (%s,%s,%s,'apple_podcasts',%s,%s)"
                        " returning id", (s, "%s %s" % (name, tag), "%s-%s.example" % (name.lower(), tag), json.dumps(m), status))
            return cur.fetchone()["id"]

        def contact(e, email, source):
            cur.execute("insert into contacts (entity_id, email, email_status, source) values (%s,%s,'unverified',%s) returning id",
                        (e, email, source))
            return cur.fetchone()["id"]

        print("\n-- which address is written to")
        cur.execute("select contact_rank(null, 'feeds@show.example', null, 'unverified', null) as r")
        check("a feed-only address is never written to", cur.fetchone()["r"] <= -500, True)
        cur.execute("select contact_rank(null, 'maya@show.example', null, 'unverified', null) as r")
        check("  a person's address is, as before", cur.fetchone()["r"] > -500, True)
        e1 = lead(seg, "Pref", "shortlisted")
        e2 = lead(seg2, "Plain", "shortlisted")
        cur.execute("select contact_source_bonus(%s, 'site_scrape') a, contact_source_bonus(%s, 'podcast_rss') b,"
                    " contact_source_bonus(%s, 'site_scrape') c, contact_source_bonus(%s, 'podcast_rss') d", (e1, e1, e2, e2))
        r = cur.fetchone()
        check("Clipping (prefer_site_contacts): the site's address first, the feed's after", (r["a"], r["b"]), (40, -10))
        check("  any other project: no change", (r["c"], r["d"]), (0, 0))
        feed = contact(e1, "maya.linden@gmail.com", "podcast_rss")
        site = contact(e1, "contact@pref-%s.example" % tag, "site_scrape")
        from recipient_selection import select_contact
        check("  the drafter writes to the site's address", str(select_contact(cur, e1)["id"]), str(site))
        cur.execute("select refresh_primary_contacts(%s)", (slug,))
        cur.execute("select id from contacts where entity_id = %s and is_primary", (e1,))
        check("  and it is the primary contact", str(cur.fetchone()["id"]), str(site))
        del feed

        print("\n-- gates after shortlisting")
        bad = {"country_signal": "disallowed"}
        auto = lead(seg, "Auto", "shortlisted", bad, {"auto_shortlisted_at": "2026-11-01"})
        hand = lead(seg, "Hand", "shortlisted", bad)
        sent = lead(seg, "Sent", "contacted", bad)
        silent = lead(seg, "NoVideo", "shortlisted", {"video_source": False}, {"auto_shortlisted_at": "2026-11-01"})
        ids = {}
        for e, st in ((auto, "drafted"), (hand, "drafted"), (sent, "sent"), (silent, "drafted")):
            c = contact(e, "p@%s.example" % uuid.uuid4().hex[:6], "podcast_rss")
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, gmail_thread_id)"
                        " values (%s,%s,'s','b',%s,%s,%s) returning id",
                        (e, c, st, "now()" if st == "sent" else None, "t-%s" % uuid.uuid4().hex if st == "sent" else None))
            ids[e] = cur.fetchone()["id"]
        cur.execute("update outreach set sent_at = now() where id = %s", (ids[sent],))
        cur.execute("insert into outreach (entity_id, subject, body, status, sequence_step, parent_id) values (%s,'Re: s','b','drafted',1,%s)"
                    " returning id", (sent, ids[sent]))
        fu = cur.fetchone()["id"]
        cur.execute("select set_config('tvf.segment', %s, true)", (slug,))
        cur.execute((ROOT / "sql" / "13_apply_gates.sql").read_text(encoding="utf-8"))
        def status(table, i):
            cur.execute("select status from %s where id = %%s" % table, (i,))
            return cur.fetchone()["status"]
        check("the engine's shortlist in a blocked country: archived, its draft withdrawn",
              (status("entities", auto), status("outreach", ids[auto])), ("archived", "cancelled"))
        check("  no video to clip: the same", (status("entities", silent), status("outreach", ids[silent])), ("archived", "cancelled"))
        check("a person's shortlist stands, its draft too", (status("entities", hand), status("outreach", ids[hand])), ("shortlisted", "drafted"))
        check("a contacted lead keeps its status and what was sent; its unsent follow-up is withdrawn",
              (status("entities", sent), status("outreach", ids[sent]), status("outreach", fu)), ("contacted", "sent", "cancelled"))

        print("\n-- a reply from an inbox nobody reads")
        e3 = lead(seg, "Feed", "contacted")
        c3 = contact(e3, "feeds@feed-%s.example" % tag, "podcast_rss")
        cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, gmail_thread_id, gmail_message_id)"
                    " values (%s,%s,'Clips','Hello','sent',now() - interval '2 days',%s,%s) returning id",
                    (e3, c3, "zz-t-" + tag, "zz-m-" + tag))
        opener = cur.fetchone()["id"]
        cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, gmail_message_id, gmail_thread_id)"
                    " values (%s,%s,'inbound','Re: Clips','This address is NOT READ BY ANYONE.','received',%s,%s) returning id",
                    (e3, c3, "zz-in-" + tag, "zz-t-" + tag))
        rid = cur.fetchone()["id"]
        imports = []

        class G:
            def users(self): return self
            def messages(self): return self
            def labels(self): return self
            def list(self, **k): return self
            def modify(self, **k): return self
            def get(self, **k): return self
            def create(self, **k): return self
            def import_(self, **k): imports.append(1); return self
            def execute(self): return {"labels": [], "id": "L"}
        n = ra.alert_new(TxDb(conn), G(), {"address": "a@zz.example", "user_email": "a@zz.example"}, ["zz-t-" + tag],
                         log=lambda m: None, chat=lambda *a, **k: '{"kind": "wrong_address", "summary": "The feed address is not read."}')
        cur.execute("select triage, reply_kind from outreach where id = %s", (rid,))
        r = cur.fetchone()
        check("not a reply (triaged neutral), read as a wrong address, no alert", (r["triage"], r["reply_kind"], n, len(imports)),
              ("neutral", "wrong_address", 0, 0))
        cur.execute("select email_status, verifier from contacts where id = %s", (c3,))
        check("  the address is never written to again", dict(cur.fetchone()), {"email_status": "invalid", "verifier": "wrong_address"})
        cur.execute("select stopped_reason from outreach where id = %s", (opener,))
        check("  no follow-up goes to it", (cur.fetchone()["stopped_reason"] or "")[:31], "stopped: the address is not rea")

        print("\n-- the AI marks the replies itself")
        def replied(name, text, triage=None):
            e = lead(seg, name, "contacted")
            c = contact(e, "%s@%s.example" % (name.lower(), uuid.uuid4().hex[:6]), "site_scrape")
            t = "zz-t-%s-%s" % (name, tag)
            cur.execute("insert into outreach (entity_id, contact_id, subject, body, status, sent_at, gmail_thread_id, gmail_message_id)"
                        " values (%s,%s,'Clips','Hello','sent',now() - interval '2 days',%s,%s) returning id", (e, c, t, t + "-o"))
            o = cur.fetchone()["id"]
            cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, triage, gmail_message_id, gmail_thread_id)"
                        " values (%s,%s,'inbound','Re: Clips',%s,%s,%s,%s,%s) returning id",
                        (e, c, text, "triaged" if triage else "received", triage, t + "-i", t))
            return e, o, cur.fetchone()["id"], t
        def read_as(kind):
            return lambda *a, **k: '{"kind": "%s", "summary": "x"}' % kind
        box = {"address": "a@zz.example", "user_email": "a@zz.example"}
        yes, yes_o, yes_r, yes_t = replied("Yes", "Yes, send samples please.")
        ra.alert_new(TxDb(conn), G(), box, [yes_t], log=lambda m: None, chat=read_as("interested"))
        cur.execute("select triage, triage_reason from outreach where id = %s", (yes_r,))
        r = cur.fetchone()
        check("interested: marked Positive by the AI, saying so", (r["triage"], (r["triage_reason"] or "")[:24]),
              ("positive", "Marked positive by AI. A"))
        check("  the company moves to In conversation, its follow-ups stop",
              (status("entities", yes), bool(cur.execute("select stopped_reason from outreach where id = %s", (yes_o,)) or cur.fetchone()["stopped_reason"])),
              ("in_conversation", True))
        no, _, no_r, no_t = replied("No", "No thanks.")
        ra.alert_new(TxDb(conn), G(), box, [no_t], log=lambda m: None, chat=read_as("not_interested"))
        cur.execute("select triage from outreach where id = %s", (no_r,))
        check("not interested: marked Negative, the company stays contacted", (cur.fetchone()["triage"], status("entities", no)),
              ("negative", "contacted"))
        away, _, away_r, away_t = replied("Away", "Out of office until Monday.")
        ra.alert_new(TxDb(conn), G(), box, [away_t], log=lambda m: None, chat=read_as("auto_reply"))
        cur.execute("select triage from outreach where id = %s", (away_r,))
        check("an out-of-office: not a reply (neutral)", cur.fetchone()["triage"], "neutral")
        kept, _, kept_r, kept_t = replied("Kept", "Not now.", triage="positive")
        cur.execute("update outreach set alerted_at = null where id = %s", (kept_r,))
        ra.alert_new(TxDb(conn), G(), box, [kept_t], log=lambda m: None, chat=read_as("not_interested"))
        cur.execute("select triage from outreach where id = %s", (kept_r,))
        check("a reply a person already marked keeps that mark", cur.fetchone()["triage"], "positive")

        print("\n-- Reports, Who replies")
        import team_report as tr
        out = tr.replies_by_lead(cur, slug)
        src = {g["value"]: g for g in out["dimensions"]["source"]}
        addr = {g["value"]: g["sent"] for g in out["dimensions"]["address"]}
        # 6 first emails: the gated one, the unread inbox, and the four the AI marked; 3 human replies (yes, no, the
        # one a person marked) -- the unread inbox and the out-of-office are not replies
        check("this project's first emails, by source; unread inboxes and auto-replies are no reply",
              (out["sent"], out["replied"], src["apple_podcasts"]["sent"]), (6, 3, 6))
        check("  by address: a feed address apart", addr.get("Nobody reads it (feed, support)"), 1)
        check("  too few to show a rate", src["apple_podcasts"]["reply_rate"], None)
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    pure()
    database()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    sys.exit(1 if bad else 0)
