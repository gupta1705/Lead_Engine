#!/usr/bin/env python3
"""test_personname.py -- the name rules as a regression table.

    python tools/test_personname.py

Every case here came from the live clipping pool or from the hostile review of
2026-09-10. A wrong greeting costs a reply, so the table leans on false
positives: a show, a brand or a sponsor must never come back as a person.
Exit code 1 on any failure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personname as p

# (title, kwargs, expected name or None, expected greeting from greeting_name(expected name))
HOST_CASES = [
    ("Tech Talk With Sanjeev", {}, "Sanjeev"),
    ("The L3 Leadership Podcast with Doug Smith", {}, "Doug Smith"),
    ("Dr. Shawn Baker Podcast", {}, "Shawn Baker"),
    ("The Dr. Phil Podcast", {}, "Phil"),
    ("The Homecoming Podcast with Dr.Thema", {}, "Thema"),
    ("Prof. Chadikovski Podcast", {"description": "I am Prof. Dr. Vladimir Chadikovski, welcome."}, "Vladimir Chadikovski"),
    ("Aswath Damodaran", {}, "Aswath Damodaran"),
    ("The Joe Rogan Experience", {}, "Joe Rogan"),
    ("Learn and Earn with Pavan Agrawal", {}, "Pavan Agrawal"),
    ("Rahul Jain- Business coaching India", {}, "Rahul Jain"),
    ("Tech Travel Eat by Sujith Bhakthan", {}, "Sujith Bhakthan"),   # weak cue, known first name: accepted
    ("Travel Diaries by Zorblax Quintero", {}, None),                 # weak cue, unknown first name: refused
    ("Some Show", {"description": "Hosted by Matthew N. Wilkinson."}, "Matthew N. Wilkinson"),
    ("Some Show", {"description": "I’m Hadar Shemesh and this is the show."}, "Hadar Shemesh"),
    ("Some Show", {"description": "I’m Zorblax Quintero and this is the show."}, None),  # weak cue, unknown name
    ("Some Show", {"description": "I’m Sarah Jones and this is the show."}, "Sarah Jones"),
    ("All Ears English Podcast", {"owner_name": "Lindsay McMahon and Michelle Kaplan"}, "Lindsay McMahon"),
    ("The InFluency Podcast", {"author": "Hadar Shemesh"}, "Hadar Shemesh"),
    ("Football Talk", {"author": "Peyton Manning"}, "Peyton Manning"),
    # never a person
    ("Cooking With Fire", {}, None),
    ("Learn Welsh Fast", {}, None),
    ("Best History Documentaries", {}, None),
    ("The Remarkable Leadership Podcast", {}, None),
    ("Stuff You Should Know", {}, None),
    ("Spreading Gyan", {}, None),
    ("Bob Industries", {}, None),
    ("The Daily Show presented by Athletic Greens", {}, None),
    ("MomCo Leadership Podcast", {"author": "MomCo Leaders"}, None),
    ("Hoy Hablamos", {"author": "Hoy Hablamos"}, None),
    ("Techno Vihaan", {}, None),
]

GREETINGS = [
    ("Tech Talk With Sanjeev", None), ("Learn Welsh Fast", None), ("MomCo Leaders", None),
    ("Stuff You Should Know", None), ("J. Smith", None), ("Teacher Stefano", "Stefano"),
    ("Dr. Mayim Bialik", "Mayim"), ("Hadar Shemesh", "Hadar"), ("John Smith", "John"),
    ("Peyton Manning", "Peyton"), ("Sanjeev", "Sanjeev"),
]


def main():
    bad = 0
    for title, kw, want in HOST_CASES:
        h = p.extract_host(title, **kw)
        got = h["name"] if h and h["confidence"] in ("high", "medium") else None
        ok = got == want
        bad += not ok
        print("%s  %-44s -> %-24s %s" % ("ok  " if ok else "FAIL", title[:44], got, "" if ok else "(want %r; %r)" % (want, h)))
    for name, want in GREETINGS:
        got = p.greeting_name(name)
        ok = got == want
        bad += not ok
        print("%s  greet %-38s -> %s%s" % ("ok  " if ok else "FAIL", name, got, "" if ok else "  (want %r)" % want))
    print("\n%d failure(s) of %d cases" % (bad, len(HOST_CASES) + len(GREETINGS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
