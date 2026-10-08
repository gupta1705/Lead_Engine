#!/usr/bin/env python3
"""test_lcxs_pitch.py -- LCX Services' email structure and the leash on the model that fills it, offline.

    python tools/test_lcxs_pitch.py

The owner, 2026-10-08: "make a email structure for me that groq will follow". The email (template
lcx_services_deck_v2) keeps the owner's lines word for word and the model writes two parts: an opener about the
company and a pitch naming two of the services its kind of buyer is pitched first (tools/llm.py LCXS_SYSTEM,
tools/draft_render.lcxs_*). No API key and no network: the model is a stub. What is tested is that the checks
hold when a model does what models do -- names the company, invents a client or a number, names a service it was
not given, praises, links, runs long -- and that a failure leaves a correct email (no opener, the plain pitch).
The answers marked "first try" are what Groq wrote on real leads on 2026-10-08.
Exit code 1 on any failure.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import draft_render as dr  # noqa: E402
import llm  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = []
CFG = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
OUT = CFG["outreach"]
POL = llm.lcxs_policy(OUT)


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-86s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, ensure_ascii=False)[:90]
                               + ("" if ok else "   (want %s)" % json.dumps(want, ensure_ascii=False)[:90])))


HOTEL = {"kind": "hospitality", "audience": "Hotel or short stay",
         "services": ["Airbnb / Property Content", "AI Reality Experiences", "AI Onboarding Employee"],
         "site_about": {"title": "Crerar Hotels | Hotels and inns across Scotland",
                        "description": "Independent hotels and inns across Scotland, with 120 rooms and Scottish "
                                       "hospitality. Book at hello@crerar.example or https://crerar.example/book",
                        "about": "Family run since 2004."},
         "lcx_judgement": {"site_read": True, "site_theirs": True},
         "site_contact_routes": {"socials": {"instagram": "https://instagram.com/x", "tiktok": "t", "facebook": "f"},
                                 "pages_read": 3},
         "scoring_inputs": {"buying_trigger": 0}}


def facts(meta=HOTEL, company="Crerar Hotels", person=None):
    return dr.lcxs_facts(OUT, company, meta, writing_to=person)


def verdict(opener, pitch, f=None):
    got, why = llm.check_lcxs(json.dumps({"opener": opener, "pitch": pitch}), f or facts(), POL)
    return "ok" if got else why


GOOD_OPENER = "You run independent hotels and inns across Scotland, with 120 rooms, and you already post on Instagram and TikTok."
GOOD_PITCH = ("I'd start with Airbnb / Property Content, turning your property photos into cinematic reels and "
              "home tours, and AI Onboarding Employee, a digital trainer that teaches and tests new staff.")


def the_config():
    print("-- the structure (config/segment.lcx-services.json outreach)")
    v2 = OUT["templates"][0]
    check("the draft step picks v2 first; v1 kept for the drafts written with it",
          [t["key"] for t in OUT["templates"]], ["lcx_services_deck_v2", "lcx_services_deck_v1"])
    v1 = OUT["templates"][1]
    owner = ["I'm writing from LCX. We work in three areas, and at least one of them should be useful to {{company}}."
             " Our services deck is attached.", "If one fits, reply with its name and I'll send examples."]
    check("the owner's lines are in v2 word for word, and v1's subject and deck are kept",
          ([x in v2["body"] and x in v1["body"] for x in owner], v2["subject"] == v1["subject"],
           v2["attachments"] == v1["attachments"]), ([True, True], True, True))
    check("  the order: greeting, opener, the owner's lines, pitch, the owner's close, footer",
          [v2["body"].index(x) for x in ("Hi {{greeting_name}}", "{{opener_block}}", "I'm writing from LCX",
                                         "{{pitch}}", "If one fits", "{{footer}}")] ==
          sorted(v2["body"].index(x) for x in ("Hi {{greeting_name}}", "{{opener_block}}", "I'm writing from LCX",
                                               "{{pitch}}", "If one fits", "{{footer}}")), True)
    every = {s for a in CFG["audiences"] for s in a.get("services") or []}
    check("every service an audience pitches has the deck's line; 18 services in all",
          (sorted(every - set(OUT["generated_pitch"]["service_lines"])), len(OUT["generated_pitch"]["service_lines"])),
          ([], 18))
    check("  the policy: on, Groq's model, the word ranges, three requests a minute",
          (POL["model"], POL["opener_words"], POL["pitch_words"], POL["rpm"], OUT.get("hook_style")),
          ("openai/gpt-oss-120b", (10, 40), (15, 55), 3, "lcx_services"))
    check("  a model-written draft is approved one at a time", OUT["batch_approval"]["allow_generated"], False)


def the_facts():
    print("\n-- what the model is given (draft_render.lcxs_facts)")
    f = facts()
    check("the audience, its own words (no address, no link), the accounts it posts on, three services",
          (f["they_are"], "@" in json.dumps(f), "http" in json.dumps(f), f["already_posts_on"],
           [s["name"] for s in f["services_to_pitch"]]),
          ("Hotel or short stay", False, False, ["Instagram", "TikTok"],
           ["Airbnb / Property Content", "AI Reality Experiences", "AI Onboarding Employee"]))
    check("  each service with the deck's own line", f["services_to_pitch"][0]["what_it_does"],
          "Property photos turned into cinematic reels, carousels and home tours.")
    check("  no reason to buy now unless buying_trigger still counts", "reason_to_buy_now" in f, False)
    hiring = dict(HOTEL, buying_signal="hiring for training and onboarding now", scoring_inputs={"buying_trigger": 1.0})
    faded = dict(hiring, scoring_inputs={"buying_trigger": 0})
    check("  a live hiring signal is given; one that has faded is not",
          (facts(hiring).get("reason_to_buy_now"), "reason_to_buy_now" in facts(faded)),
          ("hiring for training and onboarding now", False))
    not_theirs = dict(HOTEL, lcx_judgement={"site_read": True, "site_theirs": False})
    wall = dict(HOTEL, lcx_judgement={"site_read": False})
    check("  a site that is not theirs, or a bot wall: none of its words",
          ("in_their_own_words" in facts(not_theirs), "in_their_own_words" in facts(wall)), (False, False))
    check("  the person's first name only as writing_to, which the model must not use",
          facts(person="Ailsa").get("writing_to"), "Ailsa")
    saved = {"audience": None, "lcx_judgement": {}}
    check("  a lead saved by hand with no audience: default_pitch",
          [s["name"] for s in facts(saved, "Acme")["services_to_pitch"]], OUT["generated_pitch"]["default_pitch"])


def the_leash():
    print("\n-- the checks (llm.check_lcxs)")
    check("a good answer passes", verdict(GOOD_OPENER, GOOD_PITCH), "ok")
    check("  first try (Air Zoo): a missing full stop is added, not a rejection",
          llm.check_lcxs(json.dumps({"opener": GOOD_OPENER[:-1], "pitch": GOOD_PITCH}), facts(), POL)[0][0][-1], ".")
    bad = [
        ("names the company", GOOD_OPENER.replace("You run", "Crerar Hotels runs"), GOOD_PITCH,
         "names the company, which the email already does"),
        ("a number not in the facts", GOOD_OPENER.replace("120 rooms", "140 rooms"), GOOD_PITCH,
         "numbers not in the facts: [140.0]"),
        ("a name not in the facts (an invented client)", GOOD_OPENER, GOOD_PITCH + " We did this for Hilton.",
         "the pitch names 'Hilton', which is not in the facts"),
        ("a service it was not given", GOOD_OPENER, "I'd start with Reel Forge, cutting your long videos into"
         " reels, and AI Onboarding Employee, a digital trainer for new staff.",
         "names a service it was not given: ['Reel Forge']"),
        ("no service at all", GOOD_OPENER, "I'd start with the reels and the training tools in the deck, which"
         " suit hotels that hire new staff every season.",
         "the pitch names no service"),
        ("their praise of themselves (first try: 'a top international school')",
         GOOD_OPENER.replace("You run", "You run top"), GOOD_PITCH, "the opener praises them ('top')"),
        ("a sales word", GOOD_OPENER, GOOD_PITCH.replace("turning", "transforming"), "the pitch uses 'transform'"),
        ("a claim about results", GOOD_OPENER, GOOD_PITCH + " Clients see results within weeks.",
         "the pitch uses 'clients'"),
        ("a link", GOOD_OPENER + " See crerar.example/www.", GOOD_PITCH, "the opener contains a link or an address"),
        ("an exclamation", GOOD_OPENER, GOOD_PITCH.replace(".", "!"), "the pitch uses '!'"),
        ("an opener of two sentences", GOOD_OPENER + " You also run events.", GOOD_PITCH,
         "the opener is more than 1 sentence"),
        ("an essay", GOOD_OPENER, GOOD_PITCH + " " + " ".join(["more"] * 40) + ".", "the pitch is 70 words"),
        ("a placeholder", GOOD_OPENER, GOOD_PITCH.replace("your", "{{company}}"), "the pitch uses '{'"),
        ("quotes", GOOD_OPENER.replace("independent", '"independent"'), GOOD_PITCH, "quotes"),
    ]
    for name, o, p, why in bad:
        check("rejects " + name, verdict(o, p), why)
    check("rejects naming the person it is written to",
          verdict("Ailsa, you run independent hotels and inns across Scotland, and post on Instagram.", GOOD_PITCH,
                  facts(person="Ailsa")), "names the person it is written to")
    check("rejects an answer that is not the JSON asked for",
          llm.check_lcxs("Sure, here is the opener: ...", facts(), POL)[1], "not the JSON asked for")
    check("  'roi' is not in 'android', and 'top' not in 'topics' (words, not letters)",
          verdict(GOOD_OPENER.replace("hotels and inns", "hotels, inns and android topics"), GOOD_PITCH), "ok")


def the_email():
    print("\n-- the email (draft_render.build_context with lcx_services)")
    v2 = OUT["templates"][0]

    def mail(gen, meta=HOTEL):
        ctx = dr.build_context(OUT, "Crerar Hotels", meta, "Ailsa Ross", "ailsa@crerar.example", seed="x",
                               generator=gen)
        return ctx, dr.render_message(v2, ctx)[1]
    ctx, body = mail(lambda f, s=None: {"opener": GOOD_OPENER, "pitch": GOOD_PITCH})
    paras = body.split("\n\n")
    check("written: greeting, the opener, the owner's line, the pitch, the owner's close",
          paras[:5], ["Hi Ailsa,", GOOD_OPENER, "I'm writing from LCX. We work in three areas, and at least one of"
                      " them should be useful to Crerar Hotels. Our services deck is attached.", GOOD_PITCH,
                      "If one fits, reply with its name and I'll send examples."])
    check("  recorded as model-written (approved one at a time)", bool(ctx["generated_hook"]), True)
    ctx, body = mail(None)
    paras = body.split("\n\n")
    check("no model (no key, a failed check): no opener, the plain pitch, nothing left blank",
          (paras[:4], "\n\n\n" in body, ctx["generated_hook"]),
          (["Hi Ailsa,", "I'm writing from LCX. We work in three areas, and at least one of them should be useful to"
            " Crerar Hotels. Our services deck is attached.",
            "I'd start with Airbnb / Property Content and AI Reality Experiences.",
            "If one fits, reply with its name and I'll send examples."], False, ""))
    boom = lambda f, s=None: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    check("  a model that throws changes nothing: the plain email", mail(boom)[1] == body, True)
    seen = []
    mail(lambda f, s=None: seen.append(f) or None)
    check("  the model is handed the facts and nothing else (no address, no full name)",
          ("ailsa@" in json.dumps(seen[0]), "Ross" in json.dumps(seen[0]), seen[0].get("writing_to")),
          (False, False, "Ailsa"))


def the_writer():
    print("\n-- the writer (llm.make_lcxs_writer), with the API stubbed")
    keep = llm.complete_lcxs
    answers = []
    try:
        def stub(f, pol, seed=None, previous=None, reason=None):
            answers.append(reason)
            return json.dumps(SCRIPT.pop(0))
        llm.complete_lcxs = stub
        w = llm.make_lcxs_writer(POL)
        SCRIPT = [{"opener": GOOD_OPENER.replace("You run", "Crerar Hotels runs"), "pitch": GOOD_PITCH},
                  {"opener": GOOD_OPENER, "pitch": GOOD_PITCH}]
        got = w(facts())
        check("a rejected answer gets one retry, told why, and the second answer is used",
              (got, answers), ({"opener": GOOD_OPENER, "pitch": GOOD_PITCH},
                               [None, "names the company, which the email already does"]))
        answers.clear()
        SCRIPT = [{"opener": "x", "pitch": "y"}, {"opener": "x", "pitch": "y"}]
        check("  two rejections: nothing (the plain email)", w(facts()), None)
        answers.clear()
        bare = dict(HOTEL, lcx_judgement={}, site_contact_routes={})
        check("  nothing of theirs on record: no call at all", (w(facts(bare)), answers), (None, []))
        check("  counted", (w.stats["ok"], w.stats["rejected"], w.stats["skipped"]), (1, 1, 1))
    finally:
        llm.complete_lcxs = keep
    gen = llm.make_generator(dict(OUT, generated_pitch=dict(OUT["generated_pitch"], enabled=False)))
    check("generated_pitch off: no model, every draft plain", gen is None or getattr(gen, "policy", {}).get("kind") != "lcxs",
          True)


def main():
    the_config()
    the_facts()
    the_leash()
    the_email()
    the_writer()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (offline: no database, no network)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
