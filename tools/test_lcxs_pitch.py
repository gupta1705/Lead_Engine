#!/usr/bin/env python3
"""test_lcxs_pitch.py -- LCX Services' model-written lines and the leash on the model, offline.

    python tools/test_lcxs_pitch.py

The owner, 2026-10-08: "make a email structure for me that groq will follow". Rewritten 2026-10-13 for the v3
email (the owner's review: problem first, ONE lead service): the model writes two lines, a problem a business
like this usually has and how the lead's one service solves it (tools/llm.py LCXS_SYSTEM v3, check_lcxs,
make_lcxs_writer; tools/draft_render.lcxs_facts), or says no_fit. v2 (the opener and two services) is kept only
for the drafts already written with it. No API key and no network: the model is a stub. What is tested: the facts
the model is handed (its own words, never the company or the person, the one service with its fixed lines), the
checks on what comes back, and the writer (one retry told why, a no_fit is not retried, no call without words of
theirs). The 18 services' copy, the greeting, the footer, the lead-service rules and the draft gate are in
tools/test_lcxs_v3.py. Exit code 1 on any failure.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import draft_render as dr  # noqa: E402
import lcx_judge as LJ  # noqa: E402
import llm  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RESULTS = []
CFG = json.loads((ROOT / "config" / "segment.lcx-services.json").read_text(encoding="utf-8"))
OUT = CFG["outreach"]
POL = llm.lcxs_policy(OUT)
ALL = OUT["generated_pitch"]["all_services"]


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-86s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, ensure_ascii=False)[:90]
                               + ("" if ok else "   (want %s)" % json.dumps(want, ensure_ascii=False)[:120])))


HOTEL = {"kind": "hospitality", "audience": "Hotel or short stay",
         "discovery_raw": {"lcx_wikidata": {"kind": "hospitality", "wikidata": {"country_iso": "GB",
                                                                               "classes": ["hotel"]}}},
         "site_about": {"description": "A boutique hotel on the seafront with a rooftop bar and sea-view rooms."},
         "site_contact_routes": {"socials": {"instagram": "x"}, "pages_read": 3},
         "lcx_judgement": {"site_read": True, "site_theirs": True}, "scoring_inputs": {"buying_trigger": 0}}


def tagged(meta):
    lead = {"name": "Ocean Crest Hotels", "domain": "oceancrest.example", "source": "lcx_wikidata", "metadata": meta}
    return dict(meta, lead_service=LJ.lead_service(lead, CFG))


P0, S0 = llm.LCXS_EXAMPLES[0][1]["problem"], llm.LCXS_EXAMPLES[0][1]["solution"]


def the_config():
    print("\n-- the policy")
    check("the draft step picks v3 first; v2 and v1 kept for the drafts written with them",
          [t["key"] for t in OUT["templates"]][:1], ["lcx_services_problem_v3"])
    check("  the policy: on, Groq, the word ranges of v3, three requests a minute",
          (OUT["generated_pitch"]["enabled"], OUT["generated_pitch"]["provider"], POL["problem_words"],
           POL["solution_words"], POL["rpm"], POL["kind"], sorted(POL["services"]) == sorted(ALL)),
          (True, "groq", (14, 30), (18, 40), 3, "lcxs", True))
    check("  every service has the deck's own line", sorted(OUT["generated_pitch"]["service_lines"]) == sorted(ALL), True)
    check("  a model-written draft is approved one at a time", OUT["batch_approval"]["allow_generated"], False)


def the_facts():
    print("\n-- what the model is handed (draft_render.lcxs_facts v3)")
    m = tagged(HOTEL)
    f = dr.lcxs_facts(OUT, "Ocean Crest Hotels", m, writing_to="Ailsa")
    sent = llm.model_facts(f)
    check("their kind, their own words, the accounts they post on, ONE lead service",
          sorted(sent), ["already_posts_on", "in_their_own_words", "lead_service", "they_are"])
    check("  the one service, with its fixed lines as a hint", (sent["lead_service"]["name"],
                                                                bool(sent["lead_service"].get("problem_hint"))),
          ("Airbnb / Property Content", True))
    check("  never the company or the person (only under _check, stripped before the call)",
          ("Ocean Crest" in json.dumps(sent), "Ailsa" in json.dumps(sent), f["_check"]["writing_to"]),
          (False, False, "Ailsa"))
    faded = dict(m, buying_signal="hiring for training and onboarding now", scoring_inputs={"buying_trigger": 0})
    check("  a signal that has faded is not given", "reason_to_buy_now" in dr.lcxs_facts(OUT, "X", faded), False)


def the_leash():
    print("\n-- the checks on an answer (llm.check_lcxs v3)")
    f = dict(llm.LCXS_EXAMPLES[0][0], _check={"company": "Ocean Crest", "writing_to": "Ailsa", "all_services": ALL})
    for ex_facts, ex_answer in llm.LCXS_EXAMPLES:
        ff = dict(ex_facts, _check={"company": "Ocean Crest", "writing_to": "Ailsa", "all_services": ALL})
        check("the spec's example passes: %s" % ex_facts["lead_service"]["name"],
              tuple(llm.check_lcxs(json.dumps(ex_answer), ff, POL)), (ex_answer, None))

    def v(p, s):
        got, why = llm.check_lcxs(json.dumps({"problem": p, "solution": s}), f, POL)
        return "ok" if got else why
    check("rejects a question", v(P0[:-1] + "?", S0), "the problem is a question")
    check("rejects two problem sentences",
          v("Guests usually decide from photos. The photos show the rooms but never the feel of a stay.", S0),
          "the problem is more than 1 sentence")
    check("rejects a problem that is too short", v("Guests decide from photos.", S0), "the problem is 4 words (14 to 30)")
    check("rejects the service named in the problem",
          v("Without Airbnb / Property Content, guests usually decide from the photos they see on a phone.", S0),
          "the problem names the service; the solution does that")
    check("rejects a solution with no service", v(P0, S0.replace("Airbnb / Property Content turns", "We turn")),
          "the solution must name Airbnb / Property Content exactly once, exactly as written")
    check("rejects a number not in the deck's line", v(P0, S0.replace("cinematic reels", "12 cinematic reels")),
          "the solution has numbers that are not in the deck's line: [12.0]")
    check("rejects a place name", v(P0.replace("by the sea", "in Brighton"), S0),
          "the problem names 'Brighton', which is not allowed")
    check("rejects an answer that is not the JSON asked for", llm.check_lcxs("Sure! Here you go.", f, POL)[0], None)


def the_writer():
    print("\n-- the writer (llm.make_lcxs_writer), with the API stubbed")
    keep = llm.complete_lcxs
    asked = []
    script = []
    f = dr.lcxs_facts(OUT, "Ocean Crest Hotels", tagged(HOTEL), writing_to="Ailsa")
    try:
        def stub(facts, pol, seed=None, previous=None, reason=None):
            asked.append(reason)
            return json.dumps(script.pop(0))
        llm.complete_lcxs = stub
        w = llm.make_lcxs_writer(POL)
        script[:] = [{"problem": P0.replace("your hotel", "Ocean Crest Hotels"), "solution": S0}, {"problem": P0, "solution": S0}]
        check("a rejected answer gets one retry, told why, and the second answer is used",
              (w(f), asked), ({"problem": P0, "solution": S0}, [None, "names the company, which the email already does"]))
        asked.clear()
        script[:] = [{"problem": "x", "solution": "y"}, {"problem": "x", "solution": "y"}]
        check("  two rejections: nothing (the fixed lines are used)", w(f), None)
        asked.clear()
        script[:] = [{"no_fit": "They only run a booking website."}]
        check("  a no_fit is an answer, not retried", (w(f), asked), ({"no_fit": "They only run a booking website."},
                                                                        [None]))
        asked.clear()
        bare = dr.lcxs_facts(OUT, "Ocean Crest Hotels", tagged(dict(HOTEL, site_about={}, lcx_judgement={},
                                                                    site_contact_routes={})))
        check("  nothing of theirs on record: no call at all", (w(bare), asked), (None, []))
        check("  counted", (w.stats["ok"], w.stats["rejected"], w.stats["no_fit"], w.stats["skipped"]), (1, 1, 1, 1))
    finally:
        llm.complete_lcxs = keep
    gen = llm.make_generator(dict(OUT, generated_pitch=dict(OUT["generated_pitch"], enabled=False)))
    check("generated_pitch off: no model, every draft on the fixed lines",
          gen is None or getattr(gen, "policy", {}).get("kind") != "lcxs", True)


def main():
    the_config()
    the_facts()
    the_leash()
    the_writer()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (offline: no database, no network)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
