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

    print("\n-- production houses: the owner's template (samples of 2026-09-18), from the real config")
    import json
    import llm
    real = json.loads((Path(__file__).resolve().parent.parent / "config" / "segment.us-production-houses.json")
                      .read_text(encoding="utf-8"))["outreach"]
    real = dict(real, sender=dict(real["sender"], postal_address=ADDR))
    taste = {"site_about": {"description": "Taste is a tabletop production company making food and beverage films."},
             "aicp_detail": {"company_type": "Tabletop Commercial Production Company"},
             "why_fit": "INTERNAL: arguably the most AI-relevant craft on the list", "hq_city": "Los Angeles"}
    toons = {"aicp_detail": {"company_type": "Animation Studio"},
             "site_about": {"description": "We make hand-drawn animated series for kids and families."}}

    def email(company, meta, name, addr, gen=None):
        ctx = dr.build_context(real, company, meta, name, addr, seed="x", now=NOW, generator=gen)
        tpl = dr.pick_template(real, meta, ctx)
        return dr.render_message(tpl, ctx)

    s1, b1 = email("Taste In Motion, Inc.", taste, "Becky Donahue", "becky@tasteinmotion.com")
    s2, b2 = email("Myriad Pictures", {}, None, "info@myriadpictures.com")
    s3, b3 = email("Toon Works", toons, None, "hello@toonworks.com")
    written = lambda facts, seed: {"theme": "Food Stories That Travel",
                                   "paragraph": "A tabletop studio built around food and beverage films is rare. "
                                                "That is exactly how we think."}
    s4, b4 = email("Taste In Motion, Inc.", taste, "Becky Donahue", "becky@tasteinmotion.com", gen=written)

    def boom(facts, seed):
        raise RuntimeError("model down")
    s5, b5 = email("Taste In Motion, Inc.", taste, "Becky Donahue", "becky@tasteinmotion.com", gen=boom)
    checks = [
        ("a named person: the samples' greeting", b1.startswith("Hello Becky,\n\nI trust you are well.\n\nI am Kartikeya,"
                                                               " and I lead Business Development and IP Strategy at The "
                                                               "Viral Fever (TVF), one of India's leading"), True),
        ("a named person: the samples' subject", s1.startswith("From TVF in India — On "), True),
        ("four paragraphs, then the sign-off", b1.split("\n\nWarm regards,")[0].count("\n\n"), 5),
        ("paragraph two is about them", "\n\nWhich is why Taste In Motion caught my attention." in b1
         or "\n\nWhich is why Taste In Motion drew me in." in b1, True),
        ("the owner's sign-off, then the address and the way out",
         "Warm regards,\nKartikeya\nBusiness Development and IP Strategy\n\n" + ADDR in b1, True),
        ("their city in the ask", "work around your schedule in LA." in b1, True),
        ("the research note never reaches the email", "INTERNAL" in b1 + b4 + b5, False),
        ("nobody named: the samples' plain greeting", b2.startswith("Hello,\n\nI am Kartikeya, and I handle Business "
                                                                    "Development and IP Strategy at The Viral Fever (TVF, "
                                                                    "India)"), True),
        ("nobody named: the samples' subject and close", (s2.startswith("On "),
                                                         "Either way, I would love to hear from you." in b2), (True, True)),
        ("an animation studio gets the animation lane", ("extending it into animation" in b3, "kids and family" in b3),
         (True, True)),
        ("a written paragraph and theme are used", ("A tabletop studio built around food" in b4,
                                                    s4 == "From TVF in India — On Food Stories That Travel"), (True, True)),
        ("a model that fails leaves the plain paragraph", "Which is why Taste In Motion" in b5 and "{{" not in b5, True),
        ("no placeholder left anywhere", "{{" in s1 + b1 + s2 + b2 + s3 + b3 + s4 + b4, False),
    ]
    tonko, tonko_answer = llm.PARTNER_EXAMPLES[0]
    edit = lambda **kw: dict(tonko_answer, **kw)
    checks += [
        ("the owner's own samples pass the model checks",
         [llm.check_partner(a, f)[1] for f, a in llm.PARTNER_EXAMPLES], [None, None]),
        ("a name not in the facts is refused", llm.check_partner(edit(paragraph=tonko_answer["paragraph"].replace(
            "after Pixar", "after Pixar and DreamWorks")), tonko)[1], "names 'DreamWorks', which is not in the facts"),
        ("a number not in the facts is refused", (llm.check_partner(edit(paragraph="Across 12 films since Pixar, you "
                                                  "have made craft carry emotion, and it is rare. That is exactly how we "
                                                  "think about our own work."), tonko)[1] or "").startswith("numbers"),
         True),
        ("the next paragraph's pitch is refused", llm.check_partner(edit(paragraph=tonko_answer["paragraph"] +
                                                  " It aligns with our co-production plans."), tonko)[1] is not None, True),
        ("the person written to is never named", llm.check_partner(edit(paragraph="What Robert built after Pixar, "
                                                  "from The Dam Keeper onward, is rare and quietly extraordinary, and "
                                                  "it moves audiences of every age. That is exactly how we think."),
                                                  dict(tonko, writing_to="Robert"))[1],
         "names the person it is written to"),
        ("a theme that names someone falls back", llm.check_partner(edit(theme="Pixar Roots, Indian Stories"),
                                                                    tonko)[0][0], None),
    ]
    # first full run (2026-09-18): an email to Matt said "founded by ... Matthew Wilkinson"
    two_m = {"company": "2M Productions", "in_their_own_words": {"about_page": "founded by Michelle Valdez and "
             "Matthew Wilkinson; a dance studio that will keep making films"}}
    two_m_para = {"theme": "Stories Built to Travel",
                  "paragraph": "You built a dance studio that will keep making films, founded by Michelle Valdez and "
                               "Matthew Wilkinson, and it is rare to see. That is exactly how we think."}
    checks += [
        ("Matt is Matthew Wilkinson: never named", llm.check_partner(two_m_para, dict(
            two_m, writing_to="Matt", writing_to_full_name="Matthew N. Wilkinson"))[1],
         "names the person it is written to"),
        ("'will' and 'dance' are not Will or Dan", [llm.check_partner(two_m_para, dict(two_m, writing_to=w))[1]
                                                    for w in ("Will", "Dan")], [None, None]),
        ("the recipient is not in the list of names", [p["name"] for p in dr.tvf_facts(
            "2M Productions", {"aicp_detail": {"people": [
                {"first": "Matthew", "last": "Wilkinson", "title": "Founder"},
                {"first": "Michelle", "last": "Valdez", "title": "Founder"}]}}, "general",
            writing_to="Matt", writing_to_name="Matthew N. Wilkinson").get("people", [])], ["Michelle Valdez"]),
        ("a quoted description is never cut mid-thought", dr._whole_clause(
            "Neon Zoo is an award-winning independent film studio, founded by director Elyse Kelly, known for "
            "telling captivating stories that resonate deeply with audiences and spark meaningful conversation "
            "across the world today."), "Neon Zoo is an award-winning independent film studio, founded by director "
                                        "Elyse Kelly"),
    ]
    # the first full run's weak paragraphs (2026-09-18), each now closed by a rule
    bronson = {"company": "Bronson Canyon Pictures", "recent_news": {
        "headline": "Fox Entertainment Studios Signs Jeffrey Levine and Bronson Canyon Pictures To First-Look Deal",
        "deal": "first-look deal", "reported_by": "Variety", "when": "December 2025"}}
    fox = ("Your first-look deal with Fox Entertainment Studios, reported by Variety in December 2025, is a vote of "
           "confidence in the TV drama you develop. That is exactly how we think.")
    iron = {"company": "Ironbound Films", "in_their_own_words": {"site_title": "Ironbound Films"}}
    insignia = {"company": "Insignia Films", "genres": ["comedy"], "in_their_own_words": {
        "site_description": "Insignia Films, a documentary production studio based in New York City"}}
    white = {"company": "Whitewater Films", "genres": ["drama"], "in_their_own_words": {
        "site_description": "Rick Rosenthal is an award-winning producer and director with over 35 years in film and "
                            "television"}}
    seen = []
    real_complete = llm.complete_partner
    llm.complete_partner = lambda facts, pol, seed=None, previous=None, reason=None: (seen.append(facts), json.dumps(
        {"theme": "Stories Built to Travel", "paragraph": "You describe yourselves as a documentary production "
                                                          "studio, and that focus is rare. That is exactly how we think."}))[1]
    try:
        writer = llm.make_partner_writer({"model": "m", "min_words": 15, "max_words": 75, "max_calls": 5, "rpm": 0,
                                          "kind": "paragraph"})
        wrote = (writer(iron, "x"), writer(dict(insignia, lane="conscience"), "x"),
                 writer({"company": "Toon Works", "lane": "animation",
                         "in_their_own_words": {"site_description": "We make hand-drawn animated series."}}, "x"))
    finally:
        llm.complete_partner = real_complete
    checks += [
        ("'this December' is refused, the month and year pass",
         [llm.check_partner({"theme": "Drama", "paragraph": p}, bronson)[1] is None
          for p in (fox.replace("in December 2025", "this December"), fox)], [False, True]),
        ("relative time words are refused, 'just as' is not",
         [bool(llm.RELATIVE_DATE.search(s)) for s in ("you recently signed", "was just placed at #4", "your recent "
          "first-look deal", "Bronson Canyon Pictures' recent first-look deal", "reported in December 2025",
          "your most recent film", "we hold just as firmly")],
         [True, True, True, True, False, False, False]),
        ("the company named over and over is refused", llm.check_partner(
            {"theme": "Stories", "paragraph": "Ironbound Films, as presented on your site, is the name of your studio, "
                                              "Ironbound Films, and the brand you operate under, Ironbound Films. That "
                                              "is exactly how we think."}, iron)[1], "names the company over and over"),
        ("'TV' and the M of '2M' are not names", [llm.check_partner({"theme": "x", "paragraph": p}, f)[1] for p, f in (
            (fox, bronson), ("You position 2M Productions as a dance studio that will keep making films, and it is "
                             "rare to see. That is exactly how we think.", two_m))], [None, None]),
        ("'powerhouse' and 'leveraging' are refused", [llm.check_partner(edit(paragraph=tonko_answer["paragraph"]
                                                       .replace(a, b)), tonko)[1] for a, b in (
            ("is rare and quietly extraordinary", "is a creative powerhouse"),
            ("carries genuinely emotional", "leveraging genuinely emotional"))], ["uses 'powerhouse'", "uses 'leverag'"]),
        ("a page title alone: no model call", (wrote[0], writer.stats["skipped"], len(seen)), (None, 1, 2)),
        ("genre words never reach the model", ("genres" in seen[0],
                                               (wrote[1] or {}).get("paragraph", "").startswith("You describe")),
         (False, True)),
        ("the lane reaches it only when it is animation", [f.get("lane") for f in seen], [None, "animation"]),
        ("a biography is not quoted as their belief", dr.tvf_fit_fallback(white),
         "The drama at the heart of your work is the same ground our own series stand on."),
        ("...their about page is, when it is about them", dr.tvf_fit_fallback(dict(white, in_their_own_words=dict(
            white["in_their_own_words"], about_page="Whitewater Films develops and produces film and television with "
                                                    "emerging filmmakers."))).startswith(
            "Your own site puts it simply: “Whitewater Films develops and produces"), True),
        ("a sentence naming one of their people is not quoted", dr.tvf_fit_fallback(dict(white, people=[
            {"name": "Rick Rosenthal", "role": "Founder"}], in_their_own_words={
            "site_description": "Founded by Rick Rosenthal, a home for emerging filmmakers"}))[:9], "The drama"),
        ("a page's list of projects is not their description", dr.tvf_facts("Mayan Productions", {"site_about": {
            "title": "Home Page - Paul Dektor", "description": "Selected Projects Coca-Cola Bets Famous 'Hilltop' "
            "Jingle Still Has Fizz With Modern Crowds Peter Dinklage and Shirley MacLaine at their very best"}},
            "general").get("in_their_own_words"), {"site_title": "Home Page - Paul Dektor"}),
        ("their own description is still quoted", dr.tvf_fit_fallback(insignia),
         "Your own site puts it simply: “Insignia Films, a documentary production studio based in New York City”. "
         "That is exactly the kind of company we hoped to find."),
        ("'how we think' follows something they believe", dr.tvf_fit_fallback({
            "company": "Hungry Man", "in_their_own_words": {
                "site_description": "hungryman is an independent production company based in LOS ANGELES, NEW YORK, "
                                    "AND SÃO PAULO.",
                "about_page": "hungryman is a global production company with offices in London, New York, Los Angeles "
                              "and São Paulo. hungryman was founded in 1997 around a pretty simple idea: make great "
                              "work and everything else will follow. Nearly 30 years later, we're still at it."}}),
         "Your own site puts it simply: “hungryman was founded in 1997 around a pretty simple idea: make great work "
         "and everything else will follow”. That is close to how we think about our own work, and rare to find."),
    ]
    for label, got, want in checks:
        ok = got == want
        bad += not ok
        print("%s  %-52s -> %r" % ("ok  " if ok else "FAIL", label, got))

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
