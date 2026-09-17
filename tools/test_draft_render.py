#!/usr/bin/env python3
"""test_draft_render.py -- the footer rules and the personalisation, as a
regression table.

    python tools/test_draft_render.py

Two things are guarded here and they fail in opposite directions.

THE FOOTER must never be savable without a postal address and a way off the
list: that is what commercial email is required to carry and what keeps a
sending domain alive, and a footer is one careless keystroke from losing it.

THE PERSONALISATION must never say anything the lead's own row does not
support. Every case below is built from the shape of real rows in the live
clipping pool -- a channel with no shorts, a channel that already clips, a
feed with no YouTube, a title that is somebody's advert. Exit code 1 on any
failure.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draft_render as dr

NOW = dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc)
ADDR = "7th Floor, Veera Desai Road, Andheri West, Mumbai 400053, India"
GOOD_SENDER = {"name": "Ravi Menon", "title": "Clipping desk, LCX", "postal_address": ADDR}

# (label, footer text, sender, substring expected in the first problem or None)
FOOTER_CASES = [
    ("the standard footer", dr.DEFAULT_FOOTER, GOOD_SENDER, None),
    ("empty", "   ", GOOD_SENDER, "empty"),
    ("sender not filled in yet", dr.DEFAULT_FOOTER,
     {"name": "SET_ME", "title": "x", "postal_address": "SET_ME street"}, "SET_ME"),
    ("no postal address", '{{sender_name}}\nreply "no thanks" to stop',
     {"name": "Ravi", "postal_address": ""}, "postal address"),
    ("address but no way out", "{{sender_name}}\n" + ADDR, GOOD_SENDER, "No way out"),
    ("unknown field", "{{sender_name}}\n{{fit_score}}\n" + ADDR + '\nreply "no thanks"',
     GOOD_SENDER, "not a field"),
    ("a literal address, no placeholder", "Ravi Menon\n" + ADDR + "\nUnsubscribe: reply STOP",
     GOOD_SENDER, None),
    ("plain-English opt-out", "{{sender_name}}\n{{postal_address}}\n"
     "Say the word and I'll remove you from the list.", GOOD_SENDER, None),
]

# (label, metadata, expected substring in the hook, forbidden substring or None)
YT = lambda **kw: {"youtube_channel": kw}
HOOK_CASES = [
    ("no shorts at all", YT(video_count=859, subscribers=590000,
                            recent={"sampled": 50, "long_count": 22, "shorts_count": 0}),
     "not one is a short", None),
    ("exactly one short reads as singular",
     YT(video_count=1191, recent={"sampled": 50, "long_count": 46, "shorts_count": 1}),
     "only 1 is a short", "1 are shorts"),
    ("one long upload reads as singular",
     YT(video_count=12, recent={"sampled": 8, "long_count": 1, "shorts_count": 0}),
     "1 is long-form", "1 are long-form"),
    ("already clipping: no gap sentence is claimed",
     YT(video_count=400, recent={"sampled": 50, "long_count": 20, "shorts_count": 25}),
     "400 videos on YouTube", "shorts"),
    ("a feed with no channel still has a hook",
     {"podcast_feed": {"episode_count": 178, "cadence_per_month": 5.3, "avg_duration_min": 42}},
     "178 episodes, a new one every week, averaging 42 minutes", None),
    ("nothing known: no hook, the segment's neutral line is used instead", {}, None, None),
]

# (label, title, expected cleaned title or None)
TITLE_CASES = [
    ("plain", "Ep 219: What People-First Leadership Actually Requires",
     "Ep 219: What People-First Leadership Actually Requires"),
    ("a link in the title is an advert", "New drop! https://shop.example.com", None),
    ("an address in the title", "Email me at hi@example.com", None),
    ("emoji only", "\U0001f525\U0001f525\U0001f525", None),
    ("newlines and runs of space", "Part  one\nof  two", "Part one of two"),
    ("over-long is cut on a word", "A" * 20 + " " + "B" * 40 + " " + "C" * 40, "A" * 20 + " " + "B" * 40 + "..."),
]


def main():
    bad = 0
    print("-- footer")
    for label, text, sender, want in FOOTER_CASES:
        problems = dr.validate_footer(text, sender)
        ok = (not problems) if want is None else any(want in p for p in problems)
        bad += not ok
        print("%s  %-38s -> %s" % ("ok  " if ok else "FAIL", label,
                                   "accepted" if not problems else problems[0][:70]))

    print("\n-- hook")
    for label, meta, want, forbid in HOOK_CASES:
        got = dr.hook_for_clipping(meta, "Example Show", seed="seed-1")
        ok = (got is None) if want is None else (want in (got or ""))
        if ok and forbid:
            ok = forbid not in (got or "")
        bad += not ok
        print("%s  %-52s -> %s" % ("ok  " if ok else "FAIL", label, (got or "(none)")[:80]))

    print("\n-- titles quoted back at a lead")
    for label, title, want in TITLE_CASES:
        got = dr.clean_title(title)
        ok = got == want
        bad += not ok
        print("%s  %-38s -> %r%s" % ("ok  " if ok else "FAIL", label, got,
                                     "" if ok else "  (want %r)" % want))

    print("\n-- their most recent work, by name")
    fresh = {"youtube_channel": {"recent": {"latest_title": "Zero to One, live",
                                            "last_upload_at": "2026-09-05T16:00:34Z"}}}
    stale = {"youtube_channel": {"recent": {"latest_title": "Zero to One, live",
                                            "last_upload_at": "2024-01-05T16:00:34Z"}}}
    checks = [
        ("fresh upload is named", dr.latest_work(fresh, NOW), 'your recent upload, "Zero to One, live"'),
        ("two years stale is not called recent", dr.latest_work(stale, NOW), "one of your recent uploads"),
        ("nothing known names nothing", dr.latest_work({}, NOW), "one of your recent uploads"),
        ("a feed says episodes", dr.latest_work({"podcast_feed": {"episode_count": 4}}, NOW),
         "one of your recent episodes"),
        ("clip math from their own length",
         dr.clip_math({"youtube_channel": {"recent": {"avg_long_minutes": 43}}}),
         "a 43-minute video is 7 to 11 shorts"),
        ("no length known still says something true",
         dr.clip_math({}), "one long video usually carries six to ten shorts"),
    ]
    for label, got, want in checks:
        ok = got == want
        bad += not ok
        print("%s  %-44s -> %s%s" % ("ok  " if ok else "FAIL", label, got,
                                     "" if ok else "  (want %r)" % want))

    print("\n-- phrasing varies between leads, never within one")
    meta = YT(video_count=300, subscribers=90000,
              recent={"sampled": 50, "long_count": 40, "shorts_count": 0})
    seen = {dr.hook_for_clipping(meta, "Show %d" % i, seed="lead-%d" % i).split(":")[0].split(" has")[0]
            for i in range(40)}
    ok = len(seen) > 1
    bad += not ok
    print("%s  %d different openings across 40 leads" % ("ok  " if ok else "FAIL", len(seen)))
    a = dr.hook_for_clipping(meta, "Show", seed="same-lead")
    b = dr.hook_for_clipping(meta, "Show", seed="same-lead")
    ok = a == b
    bad += not ok
    print("%s  the same lead renders identically twice" % ("ok  " if ok else "FAIL"))

    print("\n-- production houses: what the opening sentence may say (owner's review, 2026-09-17)")
    recent = "Tue, 02 Jun 2026 17:00:00 GMT"
    angel = {"criterion": "distribution_relationship", "phrase": "first-look deal", "published": recent,
             "headline": "The McDonough Company Inks First-Look Deal With Angel Studios - Deadline"}
    tvf_cases = [
        ("the research note never reaches the prospect",
         dr.hook_for({"why_fit": "Arguably the most AI-relevant craft on the list: rotoscope IS human "
                                 "performance capture."}, "Minnow Mountain", "s", NOW), None, None),
        ("somebody else's headline is never quoted",
         dr.hook_for({"news_evidence": [dict(angel, headline="Chelsea Handler Inks First-Look Deal With "
                                                             "NBCUniversal - The Hollywood Reporter")]},
                     "Chelsea", "s", NOW), None, None),
        ("an undated headline is not mentioned",
         dr.hook_for({"news_evidence": [dict(angel, published=None)]}, "Angel Studios", "s", NOW), None, None),
        ("a headline over a year old is not mentioned",
         dr.hook_for({"news_evidence": [dict(angel, published="Mon, 04 Jan 2016 10:00:00 GMT")]},
                     "Angel Studios", "s", NOW), None, None),
        ("a recent deal about them, in plain words",
         dr.hook_for({"news_evidence": [angel]}, "Angel Studios", "s", NOW), "first-look deal", "Deadline -"),
        ("the site's own genre words, as a person says them",
         dr.hook_for({"site_genre_evidence": ["humorous", "satirical", "web series"]}, "Merman Branded", "s",
                     NOW), "comedy and satire", "humorous"),
    ]
    for label, got, want, forbid in tvf_cases:
        ok = (got is None) if want is None else (want in (got or ""))
        if ok and forbid:
            ok = forbid not in (got or "")
        bad += not ok
        print("%s  %-48s -> %s" % ("ok  " if ok else "FAIL", label, (got or "(none: the neutral line)")[:80]))

    tvf_cfg = {"sender": GOOD_SENDER, "greeting_fallback": "{{company}} team", "footer": {"text": dr.DEFAULT_FOOTER},
               "templates": [{"key": "t", "subject": "{{company}} x TVF", "body": "Hi {{greeting_name}},\n\n{{hook}}"
                              "\n\nGiven {{company}}'s work.\n\n{{footer}}"}]}
    renders = [
        ("a listed person is greeted by name", "Taste In Motion, Inc.", "Becky Donahue", "becky@tasteinmotion.com",
         "Hi Becky,", "team"),
        ("a shared inbox with nobody named greets the team", "Myriad Pictures", None, "info@myriadpictures.com",
         "Hi Myriad Pictures team,", None),
        ("no legal form in the company's name", "Taste In Motion, Inc.", None, "info@tasteinmotion.com",
         "Given Taste In Motion's work", "Inc."),
        ("a name ending in s takes an apostrophe only", "Angel Studios", None, "info@angel.com",
         "Given Angel Studios' work", "Studios's"),
    ]
    for label, company, name, email, want, forbid in renders:
        ctx = dr.build_context(tvf_cfg, company, {}, name, email, seed="x", now=NOW)
        subject, body = dr.render_message(tvf_cfg["templates"][0], ctx)
        ok = want in body and not (forbid and forbid in body.split("\n\n")[0] + subject + body)
        bad += not ok
        print("%s  %-48s -> %s" % ("ok  " if ok else "FAIL", label, body.replace("\n", " ")[:80]))

    print("\n-- a rendered email has no placeholder left in it")
    cfg = {"sender": GOOD_SENDER, "hook_style": "clipping", "greeting_fallback": "there",
           "neutral_hook": "We map shows with a back catalogue and no short-form.",
           "footer": {"text": dr.DEFAULT_FOOTER},
           "templates": [{"key": "t", "subject": "{{company}}: shorts?",
                          "body": "Hi {{greeting_name}},\n\n{{hook}}\n\nThree out of "
                                  "{{latest_work}} -- {{clip_math}}.\n\n{{footer}}"}]}
    for label, m in (("rich row", dict(meta, host={"first_name": "Ravi", "confidence": "high"})),
                     ("empty row", {})):
        try:
            ctx = dr.build_context(cfg, "Example Show", m, seed="x", now=NOW)
            subject, body = dr.render_message(cfg["templates"][0], ctx)
            ok = "{{" not in subject + body and "SET_ME" not in body
        except ValueError as e:
            ok, body = False, str(e)
        bad += not ok
        print("%s  %-10s -> %s" % ("ok  " if ok else "FAIL", label, body.replace("\n", " ")[:90]))

    print("\n%d failure(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
