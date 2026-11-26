"""The site check reads each site in its own process and kills one past its deadline (2026-11-26).

On the server the run froze right after its first site even with a per-site thread timeout: a worker stuck in C
code (a regex on some page) holds the interpreter lock, so no other thread runs. This proves a reader that spins in
a catastrophic regex is killed on time and the others still come back, in order. No database, no network.

    python tools/test_site_isolation.py
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich_sitescrape as es  # noqa: E402


def fake_reader(t, judged):
    if t[2] == "stuck.example":
        re.match(r"(a+)+$", "a" * 40 + "b")      # exponential backtracking, never lets go of the interpreter lock
    return (t, {"pages": 1}, None)


if __name__ == "__main__":
    targets = [("e%d" % i, "N%d" % i, d, 1) for i, d in enumerate(["a.example", "stuck.example", "b.example",
                                                                    "c.example"])]
    t0 = time.monotonic()
    got = list(es.read_isolated(targets, False, 2, 4, reader=fake_reader))
    took = time.monotonic() - t0
    checks = [
        ("all four come back, in order", [g[0][2] for g in got], [t[2] for t in targets]),
        ("the stuck one is cut off at its deadline", got[1][2], "over 4s"),
        ("the others are read", [g[2] for g in got if g[0][2] != "stuck.example"], [None, None, None]),
        ("well before a hang", took < 20, True),
    ]
    bad = 0
    for name, have, want in checks:
        ok = have == want
        bad += not ok
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "  -> %r (want %r)" % (have, want)))
    print("\n%d passed, %d failed (%.1fs)" % (len(checks) - bad, bad, took))
    sys.exit(1 if bad else 0)
