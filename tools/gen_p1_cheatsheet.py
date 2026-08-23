#!/usr/bin/env python3
"""gen_p1_cheatsheet.py -- render docs/P1_scoring_cheatsheet.md from the config.

Filling in 8 companies by hand means deciding 13 values per company. The
guidance for each of those decisions already exists -- but it lives inside a
200-line JSON blob, which is a miserable thing to scroll while you are reading
a production company's /work page in another tab.

So the cheat sheet is GENERATED, never hand-written. If it were hand-written it
would drift from the config the first time an owner rubric review changed a
weight, and a stale cheat sheet is worse than none: it would have you scoring
against last month's rubric while believing you were current.
tools/verify_repo.py re-runs this generator and fails if the checked-in file
does not match, so drift is caught mechanically rather than noticed eventually.

Usage:  python tools/gen_p1_cheatsheet.py     (writes the .md)
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "segment.us-production-houses.json"
OUT = ROOT / "docs" / "P1_scoring_cheatsheet.md"


def render(cfg):
    L = []
    add = L.append

    add("# P1 — scoring cheat sheet")
    add("")
    add("**Generated from `config/segment.us-production-houses.json` by "
        "`tools/gen_p1_cheatsheet.py`. Do not edit by hand — regenerate.**")
    add("")
    add("Keep this open in one tab and the company's site in another.")
    add("")
    add("---")
    add("")
    add("## The rule that matters more than any weight below")
    add("")
    add("**If you could not find evidence either way, DELETE the key.** Do not "
        "write `0`, and do not write `null`.")
    add("")
    add("- a **deleted key** means *never assessed* — it is excluded from both "
        "the numerator and the denominator, so the score reads "
        "\"fit among what we know\"")
    add("- **`0`** means *checked, and confirmed no evidence* — it counts fully "
        "against the score")
    add("")
    add("Those two are wildly different judgements that look identical in a "
        "hurry. Getting this wrong is the single easiest way to make P11's "
        "rubric checkpoint meaningless.")
    add("")
    add("Rubric and modifier values are always **`0`, `0.5`, or `1`**. Gate "
        "values are strings or booleans — see the gate section.")
    add("")
    add("---")
    add("")

    rubric = cfg.get("rubric", [])
    pool = sum(c.get("points", 0) for c in rubric)
    add("## Rubric — the %d scored criteria (pool: %s points)" % (len(rubric), pool))
    add("")
    add("The pool does not sum to 100 and does not need to: the scorer "
        "normalizes over whichever criteria you actually assessed, so these are "
        "*relative* weights, not percentages.")
    add("")
    for c in sorted(rubric, key=lambda x: -x.get("points", 0)):
        add("### `%s` — %s points" % (c.get("key"), c.get("points")))
        add("")
        add("**%s**" % c.get("label", ""))
        add("")
        add(c.get("guidance", ""))
        add("")

    mods = cfg.get("score_modifiers", [])
    add("---")
    add("")
    add("## Modifiers — applied *after* normalizing, as a delta")
    add("")
    add("A modifier never creates a score on its own; it only adjusts one the "
        "rubric already produced.")
    add("")
    for m in mods:
        if "max_penalty" in m:
            amount = "penalty, up to %s" % m["max_penalty"]
        else:
            amount = "bonus, up to +%s" % m["max_bonus"]
        add("### `%s` — %s" % (m.get("key"), amount))
        add("")
        add("**%s**" % m.get("label", ""))
        add("")
        add(m.get("guidance", ""))
        add("")

    gates = cfg.get("gates", [])
    add("---")
    add("")
    add("## Gates — not scored, and not enforced until P9/P13")
    add("")
    add("Record them at P1 anyway: they are the evidence the gates will read "
        "later. Every gate fires **only on confirmed disqualifying evidence** — "
        "blank or unknown always passes through. That asymmetry is deliberate: "
        "a gate that fired on absence of evidence would silently delete real "
        "leads.")
    add("")
    for g in gates:
        add("### `%s`" % g.get("key"))
        add("")
        add("**%s**" % g.get("label", ""))
        add("")
        add("Excluded when the value is `%s`." % json.dumps(g.get("exclude_when")))
        add("")
        add(g.get("guidance", ""))
        add("")

    add("---")
    add("")
    add("## Do not fill these in by hand")
    add("")
    add("- **`reachable_decision_maker`** — engine-set from a verified contact "
        "at P10/P16. Setting it yourself inflates the score with a signal no "
        "contact record backs up. `sql/04_insert_template.sql` CHECK 2 flags it.")
    add("")

    checklist = cfg.get("review_checklist", [])
    add("---")
    add("")
    add("## Not scored at all — the %d human judgement calls (P3)" % len(checklist))
    add("")
    add("Free sources cannot verify these, so they are never auto-enforced. "
        "They come back as literal checkboxes at review.")
    add("")
    for item in checklist:
        add("### `%s`" % item.get("key"))
        add("")
        add("**%s**" % item.get("label", ""))
        add("")
        add(item.get("guidance", ""))
        add("")

    return "\n".join(L).rstrip() + "\n"


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    text = render(cfg)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(text)
    print("wrote %s (%d lines)" % (OUT.relative_to(ROOT), text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
