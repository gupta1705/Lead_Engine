#!/usr/bin/env python3
"""demo_data.py -- the made-up data behind the public demo (/demo).

The owner, 2026-11-01: "create a demo version of this application ... in the login window ... an option demo login
which doesnt display any data but rather allows you to see the ui how different features work i will make that public
access . SO NO DATA SHOULD BE VISIBLE ON IT".

    python tools/demo_data.py            # -> app/demo/data.json (commit it; the demo serves it as it is)

HOW. Two made-up projects (a podcast one, built like LCX Clipping, and a company search, built like Universal),
with made-up people, shows, companies, contacts and emails, are written into the database inside ONE transaction that
is rolled back at the end: nothing is ever committed. The app's own endpoint functions read them back exactly as the
page would (as tools/ui_preview.py does for its snapshot), so every screen of the demo has the real shapes, scores and
explanations. The email copy, sign-offs, CC and project names are the demo's own, never the owner's.

THE GUARD. Before anything is written, the result is checked against everything real: every company, contact, address
and person in the database, every project's name, the owner's email templates and sign-offs, the sending addresses
in the environment, and the team's company names. Any of it in the demo data -- or any email address or link outside
.example -- and nothing is written (exit 1). tools/test_demo.py runs the same check on the committed file.
"""
import datetime as dt
import json
import os
import random
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "demo" / "data.json"
DOMAIN = "demo-studio.example"
PODCASTS, COMPANIES = "demo-podcasts", "demo-companies"
# words that name the real business, wherever they appear in the demo data (whole words)
BANNED_WORDS = ("tvf", "lcx", "viral fever", "theviralfever", "lightscameraexperiment", "lights camera experiment",
                "tvf.in", "contagious online", "reelforge", "reel forge")
ALLOWED = {"universal"}

PEOPLE = [("alex@%s" % DOMAIN, "Alex Rivera", "Partnerships Lead"),        # the visitor
          ("priya@%s" % DOMAIN, "Priya Shah", "Business Development"),
          ("sam@%s" % DOMAIN, "Sam Okafor", "Sales")]
CC = "producer@%s" % DOMAIN

SHOWS = ["The Lanternfish Hour", "Copperline Conversations", "Northwind Kitchen Table", "Quiet Harbor Money Club",
         "The Fernway Founders Show", "Bluebird Study Hall", "Saltmarsh Science Weekly", "The Paper Kite Interviews",
         "Midnight Orchard Stories", "Cobalt Desk Diaries", "The Marigold Workshop", "Tidewater Tech Talk",
         "Granite and Grain Radio", "The Velvet Ledger", "Hollow Pine Health", "Brightwater Parenting Notes",
         "The Juniper Commute", "Larkspur Legal Minute", "Amber Valley Fitness", "The Thimble Report",
         "Silverleaf Career Lab", "Westgate Book Circle", "The Driftwood Garage", "Pebble and Pine Travel",
         "Ironbridge History Hour", "The Citrine Kitchen", "Foxglove Film Club", "Sundial Startups",
         "The Wren Street Debate", "Kestrel Climate Notes", "Oakhaven Design Desk", "The Seabright Sessions",
         "Crimson Kite Comedy Hour", "Willowmere Wellness", "Starling Money Matters", "The Teal Door Interviews"]
HOSTS = ["Maya Linden", "Daniel Okoro", "Priya Varma", "Tom Hesketh", "Lucia Ferrand", "Kenji Arata", "Sara Holm",
         "Ben Adeyemi", "Nora Quill", "Ravi Mehra", "Elise Varga", "Owen Pryce", "Hana Sato", "Felix Brandt",
         "Ines Duarte", "Caleb Moss", "Zara Iqbal", "Leo Fontaine", "Mira Castell", "Jonah Reyes", "Tess Morrow",
         "Arjun Kale", "Greta Lund", "Omar Haddad", "Ruth Calloway", "Ivo Petrov", "Clara Weiss", "Dev Anand Rao",
         "Lena Ortiz", "Marcus Hale", "Yuki Tanabe", "Rosa Delgado", "Nate Ambrose", "Freya Nilsen", "Sol Mendez",
         "Kira Patel"]
CATEGORIES = [["Business", "Entrepreneurship"], ["Education"], ["Arts", "Food"], ["Business", "Investing"],
              ["Business", "Careers"], ["Education", "Self-Improvement"], ["Science"], ["Society & Culture"],
              ["Fiction", "Drama"], ["Business"], ["Arts", "Design"], ["Technology"], ["Leisure", "Hobbies"],
              ["Business", "Investing"], ["Health & Fitness"], ["Kids & Family", "Parenting"], ["Society & Culture"],
              ["Government", "Law"], ["Health & Fitness"], ["News", "Commentary"], ["Business", "Careers"],
              ["Arts", "Books"], ["Leisure", "Automotive"], ["Society & Culture", "Places & Travel"], ["History"],
              ["Arts", "Food"], ["TV & Film", "Film Reviews"], ["Business", "Entrepreneurship"], ["News", "Politics"],
              ["Science", "Earth Sciences"], ["Arts", "Design"], ["Society & Culture"], ["Comedy"],
              ["Health & Fitness", "Mental Health"], ["Business", "Investing"], ["Society & Culture"]]
COMPANY_NAMES = ["Brightfold Media", "Cinderpath Studios", "Halcyon Reel Co", "Mosaic Owl Films", "Tallgrass Pictures",
                 "Bluefin Creative House", "Overlook Story Lab", "Parkline Productions", "Sablewood Agency",
                 "Kitebird Digital", "Glassriver Content", "Morrow and Finch Media"]
COMPANY_PEOPLE = [("Elena Park", "Head of Partnerships"), ("Marcus Bell", "Founder"), ("Ama Owusu", "Creative Director"),
                  ("Jonas Weber", "Head of Content"), ("Ria Kapoor", "Executive Producer"), ("Theo Grant", "CEO"),
                  ("Lina Moreau", "Head of Marketing"), ("Paul Achebe", "Managing Director"), ("Sofia Lind", "Producer"),
                  ("Hugo Brandt", "Head of Growth"), ("Mei Chen", "Partnerships Manager"), ("Iris Novak", "COO")]
CITIES = [("Austin", "TX", "United States"), ("Brooklyn", "NY", "United States"), ("Denver", "CO", "United States"),
          ("Portland", "OR", "United States"), ("London", None, "United Kingdom"), ("Toronto", "ON", "Canada"),
          ("Chicago", "IL", "United States"), ("Bristol", None, "United Kingdom"), ("Seattle", "WA", "United States"),
          ("Atlanta", "GA", "United States"), ("Manchester", None, "United Kingdom"), ("Los Angeles", "CA", "United States")]

# ------------------------------------------------------------------ the demo's own words
OPENER_A = {"key": "demo_opener_numbers", "subject": "Short clips from {{company}}",
            "subject_fallback": "Short clips from your show",
            "body": "Hi {{greeting_name}},\n\n{{hook}}\n\nWe are a small studio that turns long episodes into short "
                    "vertical clips for Shorts, Reels and TikTok: {{clip_math}}. We cut them, caption them and send "
                    "them back for you to approve before anything is posted.\n\nWould three free sample clips from "
                    "{{latest_work}} be useful, so you can judge for yourself?\n\n{{footer}}"}
OPENER_B = {"key": "demo_opener_simple", "subject": "A few clips from {{company}}?",
            "subject_fallback": "A few clips from your show?",
            "body": "Hi {{greeting_name}},\n\n{{hook}}\n\nWe help shows like yours get more out of every episode by "
                    "cutting it into short clips, captioned and ready to post. You approve each one first.\n\n"
                    "Happy to make a couple from {{latest_work}}, free, if you would like to see them.\n\n{{footer}}"}
FOLLOW_UP = {"key": "demo_followup_1", "kind": "follow_up", "subject": "Re: {{opener_subject}}",
             "body": "{{hello}}\n\nBringing this back to the top of your inbox. The offer of three free sample clips "
                     "still stands, if it is useful.\n\n{{footer}}"}
FOOTER = "Best,\n{{sender_name}}\n{{sender_title}}, Demo Studio"
COMPOSE_TPL = {"key": "demo_compose", "subject": "Short videos for {{company}}",
               "body": "Hi {{first_name}},\n\nWe make short-form video for teams like yours. Would a quick call next "
                       "week be useful?\n\n{{footer}}"}

REPLIES = {
    "positive_answered": ("Re: {s}", "This sounds interesting. Can you send over a couple of samples from our latest "
                          "episode? Thursday works for a quick call too.", "positive", "interested",
                          "Interested: Asks for samples and offers a call on Thursday."),
    "positive_waiting": ("Re: {s}", "Thanks for reaching out! We have been meaning to do more short-form. What would "
                         "this cost for four episodes a month?", "positive", "question",
                         "Has a question: Asks the price for four episodes a month."),
    "positive_marked": ("Re: {s}", "Yes, let's talk. I'm free most mornings next week.", "positive", "interested",
                        "Interested: Offers a call next week, mornings."),
    "question_waiting": ("Re: {s}", "Who else do you work with? Do you have examples I could look at?", None, "question",
                         "Has a question: Asks for examples of past work."),
    "not_now": ("Re: {s}", "Not the right time for us, we are between seasons. Maybe check back in February?", None,
                "not_now", "Not now: Between seasons; suggests February."),
    "negative": ("Re: {s}", "Thanks, but we handle clips in-house. Please take us off your list.", "negative",
                 "not_interested", "Not interested: They clip in-house."),
    "auto": ("Out of office", "I'm away until Monday with limited access to email. I'll reply when I'm back.",
             "neutral", "auto_reply", "Auto-reply: Away until Monday."),
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def strip_guidance(x):
    """The owner's notes on a config (every *guidance key) are theirs: none goes into the demo."""
    if isinstance(x, dict):
        return {k: strip_guidance(v) for k, v in x.items() if not k.endswith("guidance")}
    if isinstance(x, list):
        return [strip_guidance(v) for v in x]
    return x


def podcast_config():
    real = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))
    keep = ("entity_type", "weekly_target", "batch_size", "score_threshold_review", "score_threshold_priority",
            "target_contact_roles", "languages", "rubric", "score_modifiers", "gates", "metadata_fields", "schedule",
            "pipelines", "lead_retention", "video_first_min_recent_long")
    c = strip_guidance({k: real[k] for k in keep if k in real})
    # the scoring stays as it is; its labels speak of "our studio", not of the real one
    c = json.loads(re.sub(r"\bLCX\b", "our studio", json.dumps(c)))
    c["auto_shortlist"] = {"enabled": False}           # leads wait in To review, so a visitor can shortlist or reject
    ui = strip_guidance(real["ui"])
    ui.update(project_name="Podcast Partnerships", key_prefix="POD", board_title="Podcast leads",
              list_title="Shows and hosts", project_type="Demo project")
    ui.pop("sidebar_note", None)
    c["ui"] = ui
    o = strip_guidance(real["outreach"])
    for k in ("reelforge_templates", "mailboxes", "signed_intro"):
        o.pop(k, None)
    o.update(sender={"name": "Demo Studio", "title": "Partnerships", "company": "Demo Studio", "postal_address": ""},
             neutral_hook="{{company}} has a long back catalogue that could feed a steady stream of short clips.",
             templates=[OPENER_A, OPENER_B, FOLLOW_UP], footer={"text": FOOTER}, default_cc=[CC],
             follow_ups={"enabled": True, "steps": [{"step": 1, "after_days": 4, "template": FOLLOW_UP["key"]}]},
             generated_hook={"enabled": False}, send_from="approver", sign_as="approver", hook_style="clipping")
    c["outreach"] = o
    return c


def company_config():
    real = json.loads((ROOT / "config" / "segment.universal.json").read_text(encoding="utf-8"))
    keep = ("entity_type", "weekly_target", "score_threshold_review", "score_threshold_priority", "target_contact_roles",
            "rubric", "score_modifiers", "gates", "apollo", "schedule", "pipelines")
    c = strip_guidance({k: real[k] for k in keep if k in real})
    ui = strip_guidance(real["ui"])
    ui.update(project_name="Company Search", key_prefix="CMP", board_title="Company leads", list_title="Companies",
              project_type="Demo project")
    c["ui"] = ui
    o = strip_guidance(real["outreach"])
    o.update(sender={"name": "Demo Studio", "title": "Business Development", "postal_address": ""},
             templates=[COMPOSE_TPL, FOLLOW_UP], footer={"text": FOOTER}, default_cc=[CC], compose=True,
             send_from="approver",
             follow_ups={"enabled": True, "steps": [{"step": 1, "after_days": 4, "template": FOLLOW_UP["key"]}]})
    c["outreach"] = o
    return c


# ------------------------------------------------------------------ what is real, for the guard
def sensitive_strings(cur):
    """Everything real the demo data must not contain: (text, kind), lowercased."""
    out = set()

    def add(v, kind, min_len=5):
        v = (v or "").strip().lower()
        if len(v) >= min_len:
            out.add((v, kind))
    cur.execute("select email, name from app_users")
    for r in cur.fetchall():
        add(r["email"], "a team login", 3)
        add(r["name"], "a team member's name", 4)
        add(r["email"].split("@")[0], "a team login's name", 4)
    cur.execute("select address from user_mailboxes")
    for r in cur.fetchall():
        add(r["address"], "a connected Gmail", 3)
    cur.execute("select email, full_name from contacts")
    for r in cur.fetchall():
        add(r["email"], "a contact's address", 3)
        if r["full_name"] and " " in r["full_name"].strip():
            add(r["full_name"], "a contact's name", 7)
    cur.execute("select name, domain from entities")
    for r in cur.fetchall():
        n = (r["name"] or "").strip()
        # a name of two words or more, or one long word: a one-word show called "History" is no evidence
        if len(n.split()) >= 2 and len(n) >= 8 or len(n) >= 10:
            add(n, "a lead's name", 8)
        add(r["domain"], "a lead's website", 5)
    cur.execute("select slug, name, config from segments")
    for r in cur.fetchall():
        add(r["slug"], "a project's slug", 5)
        add(r["name"], "a project's name", 5)
        cfg = r["config"] or {}
        add((cfg.get("ui") or {}).get("project_name"), "a project's name", 5)
        o = cfg.get("outreach") or {}
        s = o.get("sender") or {}
        for k in ("name", "postal_address", "company"):          # a title ("Business Development") is no one's
            add(s.get(k), "a sender's details", 6)
        for a in o.get("default_cc") or []:
            add(a, "a CC address", 3)
        texts = [(o.get("footer") or {}).get("text") or "", o.get("neutral_hook") or ""]
        texts += [t.get(k) or "" for t in o.get("templates") or [] if isinstance(t, dict) for k in ("subject", "body")]
        for t in texts:
            # the owner's copy, a sentence at a time (placeholders apart)
            for sent in re.split(r"(?<=[.!?])\s+|\n+", re.sub(r"{{\s*\w+\s*}}", " ", t)):
                add(re.sub(r"\s+", " ", sent), "the owner's email copy", 25)
    for k, v in os.environ.items():
        if v and "@" in v and len(v) < 120:
            add(v, "an address in the environment (%s)" % k, 3)
    for w in BANNED_WORDS:
        out.add((w, "the real business"))
    # "Universal" is a project's name, and also the name of the app's Apollo page (a view, ui.default_route)
    return {(s, k) for s, k in out if s not in ALLOWED}


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://([^/\s\"']+)")


def strings_of(x, out=None):
    out = [] if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            out.append(str(k))
            strings_of(v, out)
    elif isinstance(x, list):
        for v in x:
            strings_of(v, out)
    elif isinstance(x, str):
        out.append(x)
    return out


def leaks(data, sensitive):
    """-> [problem] for the demo data: anything real in it, or any address or link off .example."""
    text = "\n".join(strings_of(data)).lower()
    found = []
    for s, kind in sorted(sensitive):
        m = s in text and re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", text)
        if m:
            found.append("%s: %r, in ...%s..." % (kind, s, text[max(0, m.start() - 50):m.end() + 50].replace("\n", " | ")))
    for e in sorted(set(EMAIL.findall(text))):
        if not e.endswith(".example"):
            found.append("an address off .example: %r" % e)
    for host in sorted(set(URL.findall(text))):
        if not host.split(":")[0].endswith(".example"):
            found.append("a link off .example: %r" % host)
    return found


# ------------------------------------------------------------------ the made-up rows
#           episodes, a month, shorts of the last 30, subscribers, revenue signals
PROFILES = [(210, 4, 0, 96000, ["sponsor read"]), (64, 2, 11, 42000, []), (46, 1, 1, 8600, ["Patreon"]),
            (340, 8, 14, 1800000, ["membership"]), (28, 0.5, 2, 2400, []), (120, 4, 3, 210000, ["promo code"]),
            (88, 2, 6, 15000, []), (44, 4, 0, 5200, ["sponsor read"]), (150, 1, 18, 640000, [])]


def podcast_meta(i, rnd, now):
    """A show's feed and channel, and the scoring inputs the real scorer reads, consistent with each other."""
    name, host = SHOWS[i], HOSTS[i]
    dom = slugify(name) + ".example"
    # a spread of shows, as a real week finds them: strong, already clipping, small, big, thin, steady
    eps, cad, shorts, subs, hits = PROFILES[i % len(PROFILES)]
    eps = int(eps * rnd.uniform(0.85, 1.25))
    subs = int(subs * rnd.uniform(0.8, 1.3))
    mins = rnd.choice([24, 38, 45, 52, 61, 75, 90])
    sampled = 30
    longs = sampled - shorts - rnd.choice([0, 1, 2])
    latest = now - dt.timedelta(days=rnd.randint(2, 20))
    titles = ["Ep %d: What we got wrong about %s" % (eps, rnd.choice(["pricing", "habits", "focus", "hiring", "sleep"])),
              "Ep %d: A conversation with an old friend" % eps, "Ep %d: Listener questions, part two" % eps]
    has_channel = i % 5 != 3
    pf = {"feed_url": "https://feeds.%s/podcast.rss" % dom, "episode_count": eps, "cadence_per_month": cad,
          "avg_duration_min": mins, "latest_title": rnd.choice(titles), "latest_at": latest.isoformat(),
          "categories": CATEGORIES[i], "monetization_hits": hits}
    yc = None
    if has_channel:
        yc = {"url": "https://video.%s/@%s" % (dom, slugify(name)[:18]), "subscribers": subs,
              "video_count": eps + rnd.randint(10, 80), "monetization_hits": hits[:1],
              "recent": {"sampled": sampled, "long_count": longs, "shorts_count": shorts,
                         "medium_count": sampled - longs - shorts, "uploads_per_month": cad,
                         "shorts_share": round(shorts / float(sampled), 3), "avg_long_minutes": mins,
                         "latest_title": pf["latest_title"], "last_upload_at": latest.isoformat()}}
    band = (1 if 10000 <= subs <= 1000000 else 0.5 if 3000 <= subs <= 3000000 else 0) if yc else None
    si = {"archive_size": 1 if eps >= 100 else 0.5 if eps >= 40 else 0,
          "cadence": 1 if cad >= 2 else 0.5 if cad >= 1 else 0,
          "shorts_gap": (1 if shorts / float(sampled) < 0.1 else 0.5 if shorts / float(sampled) < 0.25 else 0) if yc else None,
          "audience_band": band, "monetization_signals": 1 if hits else 0, "reachable_contact": 1,
          "language_match": 1 if i % 7 else 0, "network_owned": 0,
          "video_first": 1 if yc and longs >= 26 and subs >= 50000 else 0,
          "oversized_audience": 0, "us_priority": 1 if i % 4 == 0 else 0, "activity_signal": "active"}
    si = {k: v for k, v in si.items() if v is not None}
    why = "%s publishes %s long episodes%s, and almost none of it is cut into shorts yet." % (
        name, "about %g" % cad if cad < 4 else "weekly", ", %d minutes on average" % mins)
    meta = {"podcast_feed": pf, "host": {"name": host}, "why_fit": why, "scoring_inputs": si}
    if yc:
        meta["youtube_channel"] = yc
    return name, dom, meta


def company_meta(i, rnd, now, saved_by):
    name = COMPANY_NAMES[i]
    city, state, country = CITIES[i]
    person, title = COMPANY_PEOPLE[i]
    industry = rnd.choice(["entertainment", "media production", "marketing and advertising", "online media"])
    employees = rnd.choice([8, 14, 22, 35, 60, 120])
    hexid = uuid.UUID(int=rnd.getrandbits(128)).hex[:24]
    meta = {"industry": industry, "employees": employees, "hq_city": city, "hq_state": state, "hq_country": country,
            "apollo": {"id": hexid, "name": name, "industry": industry, "estimated_num_employees": employees,
                       "city": city, "country": country, "founded_year": rnd.randint(2006, 2021),
                       "short_description": "%s is a made-up %s business in %s, for the demo." % (name, industry, city)},
            "apollo_people": {uuid.UUID(int=rnd.getrandbits(128)).hex[:24]: {
                "name": person, "title": title, "seniority": "head", "city": city, "country": country, "has_email": True}},
            "saved_from": {"summary": "People · Job titles: %s · %s" % (title.lower(), country),
                           "at": (now - dt.timedelta(days=rnd.randint(1, 12))).isoformat(), "by": saved_by}}
    return name, slugify(name) + ".example", meta, person, title


def build(conn):
    """Write the made-up rows (never committed) and read every screen's data back through the app."""
    import psycopg2.extras
    rnd = random.Random(20261101)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("select now() as n")
    now = cur.fetchone()["n"]
    ago = lambda **k: now - dt.timedelta(**k)    # noqa: E731
    sensitive = sensitive_strings(cur)

    import mailbox_store as store
    for email, name, title in PEOPLE:
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, 'demo', 'member', %s, %s)",
                    (email, name, title))
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap, enabled) values"
                    " (%s, %s, %s, 50, true)", (email, email, store.encrypt({"refresh_token": "demo"})))
    me = PEOPLE[0]
    seg = {}
    for slug, name, cfg in ((PODCASTS, "Podcast Partnerships (demo)", podcast_config()),
                            (COMPANIES, "Company Search (demo)", company_config())):
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) values (%s, %s, %s, %s, true)"
                    " returning id", (slug, name, cfg["entity_type"], json.dumps(cfg)))
        seg[slug] = (cur.fetchone()["id"], cfg)

    from draft_render import build_context, pick_template, render_message, personalize
    import draft_render as dr

    def person(email):
        p = next(x for x in PEOPLE if x[0] == email)
        return {"email": p[0], "name": p[1], "title": p[2]}

    # ---------------------------------------------------------- Podcast Partnerships
    seg_id, cfg = seg[PODCASTS]
    ocfg = cfg["outreach"]
    plan = (["ready_for_review"] * 9 + ["shortlisted"] * 11 + ["contacted"] * 11 + ["in_conversation"] * 3
            + ["rejected"] * 2)
    shows = []
    for i, status in enumerate(plan):
        name, dom, meta = podcast_meta(i, rnd, now)
        created = ago(days=rnd.randint(1, 24), hours=rnd.randint(0, 20))
        source = rnd.choice(["apple_podcasts", "apple_podcasts", "youtube_api", "wikidata_channels"])
        cur.execute("insert into entities (segment_id, name, domain, source, source_url, metadata, status, status_reason,"
                    " created_at, status_changed_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                    (seg_id, name, dom, source, "https://%s/" % dom, json.dumps(meta), status,
                     "Not a fit: they already clip every episode." if status == "rejected" else None,
                     created, created + dt.timedelta(hours=rnd.randint(1, 30))))
        eid = cur.fetchone()["id"]
        cur.execute("select score_entity(%s)", (eid,))
        host = meta["host"]["name"]
        cid = None
        if i % 9 != 4 or status not in ("ready_for_review",):          # a couple of open leads have no address yet
            cur.execute("insert into contacts (entity_id, full_name, role_title, email, email_status, verifier, source,"
                        " is_primary) values (%s, %s, 'Host', %s, 'valid', 'feed', 'podcast_feed', true) returning id",
                        (eid, host, "%s@%s" % (host.split()[0].lower(), dom)))
            cid = cur.fetchone()["id"]
        shows.append({"eid": eid, "cid": cid, "name": name, "host": host, "dom": dom, "meta": meta, "status": status})

    def draft(s, opener_subject=None, follow=False):
        ctx = build_context(ocfg, s["name"], s["meta"], s["host"], "%s@%s" % (s["host"].split()[0].lower(), s["dom"]),
                            seed=str(s["eid"]), opener_subject=opener_subject, now=now)
        tpl = FOLLOW_UP if follow else pick_template(ocfg, s["meta"], ctx)
        subject, body = render_message(tpl, ctx)
        return tpl["key"], subject, body

    def outbound(s, status, step=0, parent=None, sent_days=None, by=None, mode="single", subject=None, body=None,
                 key=None, generated=None, error=None):
        if subject is None:
            key, subject, body = draft(s)
        if by and status != "drafted":
            body = personalize(body, ocfg, person(by))
        sent_at = ago(days=sent_days, hours=rnd.randint(0, 6)) if sent_days is not None else None
        approved_at = (sent_at - dt.timedelta(hours=rnd.randint(2, 20))) if sent_at else (ago(hours=rnd.randint(1, 30)) if by else None)
        tid = "demo-thread-%s" % s["eid"] if status == "sent" or parent else None
        cur.execute("insert into outreach (entity_id, contact_id, direction, template_key, subject, body, status,"
                    " sent_at, approved_at, approved_by, approval_mode, spot_checked, sender_mailbox, sender_address,"
                    " gmail_thread_id, gmail_message_id, sequence_step, parent_id, generated_hook, send_error, cc,"
                    " created_at) values (%s, %s, 'outbound', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " %s, %s, %s, %s, %s) returning id",
                    (s["eid"], s["cid"], key, subject, body, status, sent_at, approved_at, by,
                     mode if by else None, True if by else None, by if sent_at else None, by if sent_at else None,
                     tid, ("demo-msg-%s" % uuid.UUID(int=rnd.getrandbits(128))) if sent_at else None, step, parent,
                     generated, error, [CC] if by else None,
                     (approved_at or ago(hours=rnd.randint(1, 40))) - dt.timedelta(hours=2)))
        return cur.fetchone()["id"], subject

    def reply(s, kind, days, answered=None, how=None, by=None):
        subj, text, triage, rkind, reading = REPLIES[kind]
        at = ago(days=days, hours=rnd.randint(0, 8))
        status = "triaged" if triage else "received"
        cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, triage, triage_reason,"
                    " gmail_message_id, gmail_thread_id, created_at, received_at, reply_kind, alerted_at, answered_at,"
                    " answered_by, answered_how) values (%s, %s, 'inbound', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " %s, %s, %s)",
                    (s["eid"], s["cid"], subj.format(s=s["opener_subject"]),
                     "%s\n\n%s" % (text, s["host"].split()[0]), status, triage, "AI's reading: " + reading,
                     "demo-reply-%s" % uuid.UUID(int=rnd.getrandbits(128)), "demo-thread-%s" % s["eid"],
                     at + dt.timedelta(minutes=3), at, rkind, at + dt.timedelta(minutes=4),
                     (at + dt.timedelta(hours=answered)) if answered else None, by, how))

    senders = [PEOPLE[0][0], PEOPLE[0][0], PEOPLE[1][0], PEOPLE[2][0]]
    short, contacted = [s for s in shows if s["status"] == "shortlisted"], \
        [s for s in shows if s["status"] in ("contacted", "in_conversation")]
    for n, s in enumerate(short):
        if n < 6:
            if n == 2:                                   # one draft with a line a model wrote, approved on its own
                key, subject, body = draft(s)
                line = "Your episode on pricing would cut into several strong clips on its own."
                body = body.replace("\n\n", "\n\n%s " % line, 1)
                outbound(s, "drafted", subject=subject, body=body, key=key, generated=line)
            else:
                outbound(s, "drafted")
        elif n < 9:
            outbound(s, "approved", by=senders[n % 4], mode="batch" if n == 7 else "single")
        elif n == 9:
            outbound(s, "failed", by=senders[0], sent_days=None,
                     error="Gmail refused it: the address does not exist (550 5.1.1). The address is marked invalid.")
        else:
            outbound(s, "drafted")
    for n, s in enumerate(contacted):
        by = senders[n % 4]
        oid, subj = outbound(s, "sent", sent_days=rnd.randint(5, 16), by=by, mode="batch" if n % 3 else "single")
        s["opener_subject"], s["opener"], s["by"] = subj, oid, by
    for n, s in enumerate(contacted):
        if s["status"] == "in_conversation":
            kind = ["positive_answered", "positive_waiting", "positive_marked"][n % 3]
            reply(s, kind, rnd.randint(1, 4),
                  answered=None if kind == "positive_waiting" else rnd.choice([2, 5, 20]),
                  how={"positive_answered": "thread", "positive_marked": "marked"}.get(kind),
                  by=s["by"] if kind != "positive_waiting" else None)
        elif n in (0, 1, 2):                        # follow-ups due: drafted, waiting for approval
            key, subject, body = draft(s, opener_subject=s["opener_subject"], follow=True)
            outbound(s, "drafted", step=1, parent=s["opener"], subject=subject, body=body, key=key)
        elif n in (3, 4):                           # follow-ups that went
            key, subject, body = draft(s, opener_subject=s["opener_subject"], follow=True)
            outbound(s, "sent", step=1, parent=s["opener"], sent_days=1, by=s["by"], subject=subject, body=body, key=key)
        elif n == 5:
            reply(s, "question_waiting", 2)
        elif n == 6:
            reply(s, "not_now", 3, answered=6, how="thread", by=s["by"])
        elif n == 7:
            reply(s, "negative", 4)
        elif n == 8:
            reply(s, "auto", 3)
    # what ran by itself, for Operations
    for days in (8, 1):
        start = ago(days=days, hours=2)
        cur.execute("insert into pipeline_runs (pipeline, trigger, status, started_at, finished_at, segment)"
                    " values ('weekly_refresh', 'schedule', 'ok', %s, %s, %s)",
                    (start, start + dt.timedelta(minutes=31), PODCASTS))
        for k, step in enumerate(cfg["pipelines"]["weekly_refresh"]):
            cur.execute("insert into pipeline_runs (pipeline, step, trigger, status, started_at, finished_at, segment)"
                        " values ('weekly_refresh', %s, 'schedule', 'ok', %s, %s, %s)",
                        (step, start + dt.timedelta(minutes=3 * k), start + dt.timedelta(minutes=3 * k + 2), PODCASTS))
    for mins in (14, 74):
        cur.execute("insert into pipeline_runs (pipeline, trigger, status, started_at, finished_at, segment)"
                    " values ('outreach', 'schedule', 'ok', %s, %s, %s)",
                    (ago(minutes=mins), ago(minutes=mins - 1), PODCASTS))

    # ---------------------------------------------------------- Company Search
    seg_id, ccfg = seg[COMPANIES]
    plan = ["ready_for_review"] * 6 + ["shortlisted"] * 2 + ["contacted"] * 4
    for i, status in enumerate(plan):
        name, dom, meta, pname, ptitle = company_meta(i, rnd, now, me[0])
        created = ago(days=rnd.randint(1, 12))
        cur.execute("insert into entities (segment_id, name, domain, source, metadata, status, created_at,"
                    " status_changed_at) values (%s, %s, %s, 'apollo', %s, %s, %s, %s) returning id",
                    (seg_id, name, dom, json.dumps(meta), status, created, created))
        eid = cur.fetchone()["id"]
        cur.execute("insert into contacts (entity_id, full_name, role_title, email, email_status, verifier, source,"
                    " is_primary) values (%s, %s, %s, %s, 'valid', 'apollo', 'apollo', true) returning id",
                    (eid, pname, ptitle, "%s@%s" % (pname.split()[0].lower(), dom)))
        cid = cur.fetchone()["id"]
        if status in ("shortlisted", "contacted"):
            first = pname.split()[0]
            subject = "Short videos for %s" % name
            body = ("Hi %s,\n\nWe make short-form video for teams like yours: explainers, launch clips and social "
                    "cuts. Would a quick call next week be useful?\n\nBest,\n%s\n%s, Demo Studio" % (first, me[1], me[2]))
            sent = status == "contacted"
            at = ago(days=rnd.randint(2, 9)) if sent else None
            cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, sent_at,"
                        " approved_at, approved_by, approval_mode, spot_checked, sender_mailbox, sender_address,"
                        " gmail_thread_id, gmail_message_id, cc, created_at) values (%s, %s, 'outbound', %s, %s, %s,"
                        " %s, %s, %s, 'compose', true, %s, %s, %s, %s, %s, %s)",
                        (eid, cid, subject, body, "sent" if sent else "approved", at,
                         (at or ago(hours=3)) - dt.timedelta(minutes=30), me[0], me[0] if sent else None,
                         me[0] if sent else None, "demo-thread-%s" % eid if sent else None,
                         ("demo-msg-%s" % uuid.UUID(int=rnd.getrandbits(128))) if sent else None, [CC],
                         (at or ago(hours=3)) - dt.timedelta(hours=1)))
            if sent and i == len(plan) - 1:
                s = {"eid": eid, "cid": cid, "host": pname, "opener_subject": subject}
                reply(s, "positive_waiting", 1)
    return now, sensitive


def screens(conn, now):
    """Every screen's data for each demo project, through the app's own endpoint functions."""
    sys.path[:0] = [str(ROOT / "app"), str(ROOT)]
    os.environ["SCHEDULER_ENABLED"] = "0"
    import main
    import explain
    import apollo
    import manual_lead

    class Shim:
        def __init__(self, c):
            self._c, self.closed = c, 0
            with c.cursor() as cur:
                cur.execute("savepoint demo_req")

        def cursor(self, *a, **k):
            return self._c.cursor(*a, **k)

        def commit(self):
            with self._c.cursor() as cur:
                cur.execute("release savepoint demo_req")

        def rollback(self):
            with self._c.cursor() as cur:
                cur.execute("rollback to savepoint demo_req")
                cur.execute("release savepoint demo_req")

    class NoPool:
        def putconn(self, c, close=False):
            pass
    main._checkout = lambda: Shim(conn)
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    # the podcast project explains its scores as LCX Clipping's code does, and the company search as Universal's
    explain.SEGMENTS[PODCASTS] = explain.SEGMENTS["lcx-clipping"]
    me = PEOPLE[0]

    class Req:
        state = type("S", (), {"user": me[0]})()
    req = Req()
    demo = (PODCASTS, COMPANIES)
    listing = {s["slug"]: s for s in main.segments_list(PODCASTS)["segments"] if s["slug"] in demo}
    with main.cursor() as cur:
        cur.execute("select slug, config from segments where slug = any(%s)", (list(demo),))
        configs = {r["slug"]: r["config"] for r in cur.fetchall()}
        import mailbox_store as store
        mine = store.mailboxes(cur, user_email=me[0])
    keep = ("id", "address", "daily_cap", "sent_today", "out_today", "remaining", "usable", "last_error", "send_as")
    me_boxes = {"mailboxes": [dict({k: b.get(k) for k in keep}, connected_at=None) for b in mine]}
    projects = {}
    for slug in demo:
        fx = {"auth": {"needs_setup": False, "authed": True, "user": me[0], "name": me[1], "title": me[2],
                       "must_change_password": False}}
        fx["segment"] = main.segment_info(slug)
        fx["stats"] = main.stats(segment=slug)
        fx["kpis"] = main.kpis(segment=slug)
        seen, leads = set(), []
        for st in ("open", "shortlisted", "contacted", "in_conversation", "rejected", "archived"):
            for r in main.leads(status=st, limit=500, segment=slug)["rows"]:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    leads.append(r)
        fx["leads"] = leads
        fx["details"] = {str(r["id"]): main.lead(r["id"], segment=slug) for r in leads}
        rows = []
        for f in ("drafts", "followups", "outbox", "sent", "inbox", "attention"):
            d = main.outreach_list(req, folder=f, segment=slug)
            rows += d["rows"] + d.get("negative_rows", [])
        for r in rows:
            if r.get("direction") == "outbound" and r.get("status") == "approved":
                r.pop("schedule", None)               # the demo draws its own time, from the visitor's clock
        fx["outreach"] = {"rows": rows}
        mb = main.mailboxes_state(req, segment=slug)
        # every person with a login is listed there (each sends from their own Gmail): in the demo, its made-up people
        mb["accounts"] = [a for a in mb.get("accounts") or [] if a["email"].endswith("@" + DOMAIN)]
        fx["mailboxes"] = mb
        fx["me_mailboxes"] = me_boxes
        fx["footer"] = main.footer_get(segment=slug)
        fx["schedule"] = main.schedule_state(segment=slug)
        fx["schedule"].pop("send_loop", None)       # this laptop's scheduler is off; the demo shows the server's, on
        fx["ops"] = {"busy": None}
        a = configs[COMPANIES].get("apollo") or {}
        fx["universal"] = {"filters": apollo.FILTERS, "endpoints": a.get("endpoints") or [],
                           "per_page": a.get("per_page") or 25, "max_reveal_per_save": a.get("max_reveal_per_save") or 100}
        fx["manual_projects"] = {s: manual_lead.project(configs[s]) for s in demo}
        projects[slug] = fx
    return {"generated_at": now.isoformat(), "order": list(demo), "listing": listing, "projects": projects}


def main_():
    sys.path.insert(0, str(ROOT / "tools"))
    # the made-up Gmail rows need a sealed token; this one is sealed with a key of this run only
    os.environ["SESSION_SECRET"] = "demo-data-" + uuid.uuid4().hex
    import psycopg2
    from run_sql import load_db_url
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    try:
        now, sensitive = build(conn)
        from fastapi.encoders import jsonable_encoder          # as the API answers: ISO dates, numbers as numbers
        data = jsonable_encoder(screens(conn, now))
    finally:
        conn.rollback()                               # nothing made up here is ever committed
        conn.close()
    found = leaks(data, sensitive)
    if found:
        print("NOT WRITTEN: the demo data would show real things:")
        for f in found[:60]:
            print("  - " + f)
        return 1
    OUT.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    n = {s: (len(p["leads"]), len(p["outreach"]["rows"])) for s, p in data["projects"].items()}
    print("wrote %s (%d KB): %s leads/emails; checked against %d real strings, nothing real in it"
          % (OUT.relative_to(ROOT), OUT.stat().st_size // 1024, n, len(sensitive)))
    return 0


if __name__ == "__main__":
    sys.exit(main_())
