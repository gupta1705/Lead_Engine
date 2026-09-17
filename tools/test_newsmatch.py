#!/usr/bin/env python3
"""test_newsmatch.py -- is a headline about THIS company? As a regression table.

    python tools/test_newsmatch.py

The first eight rows are the real news credits on the production-house pool
on 2026-09-17: four were somebody else's news and had earned 20 points each.
Exit code 1 on any failure.
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import newsmatch as nm

# (company, headline, is it about them)
CASES = [
    ("Angel Studios", "The McDonough Company Inks First-Look Deal With Angel Studios - Deadline", True),
    ("Anonymous Content", "The Atlantic, Anonymous Content Sign First-Look Deal (EXCLUSIVE) - Variety", True),
    ("Stoopid Buddy Stoodios", "Stoopid Buddy Stoodios Inks First-Look Deal With 20th Century Fox Film - Deadline", True),
    ("Maximum Effort", "Ryan Reynolds Expands Disney Ties With First-Look Deal Between Maximum Effort and 20th "
                       "Television - Laughing Place", True),
    ("Chelsea", "Chelsea Handler Inks First-Look Deal With NBCUniversal - The Hollywood Reporter", False),
    ("Heaven", "Highway to Heaven reboot gets series order from Fox - JoBlo", False),
    ("Liebling", "Sam Raimi, Debbie Liebling Sign First-Look Deal With Skydance Television - Variety", False),
    ("Tomorrow", "Disney’s 20th Television forms first-look deal with Vox Media - Tomorrow's Publisher", False),
    # the rules, one at a time
    ("Tomorrow", "Tomorrow Studios Sets Series Order - Deadline", False),           # a different company
    ("Heaven", "Heaven Inks First-Look Deal With Hulu - Deadline", True),           # a one-word name as a company
    ("Heaven", "Heaven's Gate documentary gets series order - Variety", False),     # possessive of something else
    ("Taste In Motion, Inc.", "Taste In Motion Lands Series Order - Variety", True),  # legal form dropped
    ("Neon Zoo", "neon zoo lands series order", True),                              # case does not matter
    ("Neon Zoo", "Neon Zookeepers get a series order", False),                      # whole words only
    ("Indie Film", "Indie Film Producer Low Spark Launches TV Division With First-Look Deal At CBS Television "
                   "Studios - deadline.com", False),                                # a description, not a name
    ("Indie Film", "Indie Film Signs First-Look Deal With Hulu - Variety", True),   # generic name, used as a name
    ("Dirty Films", "Searchlight Pictures Signs First-Look Deal With Cate Blanchett’s Dirty Films - Variety", True),
    ("Tomorrow Studios", "‘Snowpiercer’ Producer Tomorrow Studios Strikes First-Look Deal With ‘Medici’ Outfit "
                         "Big Light Productions (EXCLUSIVE) - Variety", True),
]

DISPLAY = [
    ("Taste In Motion, Inc.", "Taste In Motion"),
    ("Pictures In A Row (Picrow, Inc.)", "Pictures In A Row"),
    ("Merman Branded, LLC", "Merman Branded"),
    ("Mayan Productions, Inc", "Mayan Productions"),
    ("The McDonough Company", "The McDonough Company"),
    ("Supply&Demand", "Supply&Demand"),
]


def main():
    bad = 0
    print("-- is the headline about them")
    for company, title, want in CASES:
        got = nm.names_company(company, title)
        ok = got == want
        bad += not ok
        print("%s  %-24s %-70s -> %s" % ("ok  " if ok else "FAIL", company[:24], title[:70], got))
    print("\n-- the company as a sentence names it")
    for raw, want in DISPLAY:
        got = nm.display_name(raw)
        ok = got == want
        bad += not ok
        print("%s  %-36s -> %r" % ("ok  " if ok else "FAIL", raw, got))
    print("\n-- what an email may mention")
    now = dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc)
    ev = {"phrase": "first-look deal", "published": "Tue, 13 Jan 2026 08:00:00 GMT",
          "headline": "The McDonough Company Inks First-Look Deal With Angel Studios - Deadline"}
    checks = [
        ("a dated deal about them", nm.usable_news("Angel Studios", [ev], now)[:2], ("first-look deal", "Deadline")),
        ("undated: never", nm.usable_news("Angel Studios", [dict(ev, published=None)], now), None),
        ("over a year old: never", nm.usable_news("Angel Studios", [dict(ev, published="Mon, 04 Jan 2016 10:00:00 GMT")],
                                                  now), None),
        ("a publisher's domain becomes its name", nm.usable_news("Premeditated Productions", [dict(
            ev, headline="Premeditated Productions Lands Five-Year Extension Of First-Look Deal At Amazon MGM Studios "
                         "- deadline.com")], now)[:2], ("first-look deal", "Deadline")),
        ("somebody else's news: never", nm.usable_news("Chelsea", [dict(
            ev, headline="Chelsea Handler Inks First-Look Deal With NBCUniversal - The Hollywood Reporter")], now), None),
    ]
    for label, got, want in checks:
        ok = got == want
        bad += not ok
        print("%s  %-30s -> %r" % ("ok  " if ok else "FAIL", label, got))
    print("\n%d failure(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
