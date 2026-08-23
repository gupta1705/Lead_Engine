#!/usr/bin/env python3
"""expected_scores.py -- P2's "recompute it on paper" step, automated.

P2's done-when is: *one entity's score recomputed by hand matches the scorer
exactly*. This does that for every row at once, so the check becomes a diff
instead of arithmetic on a notepad.

WHY THIS IS A REAL CHECK AND NOT A TAUTOLOGY: it is an INDEPENDENT
reimplementation, written from the rubric rules as stated in BUILD_PLAN.md and
the config -- deliberately not translated from sql/06_score.sql. Two
separately-derived implementations agreeing on ten rows is evidence. Copying
the SQL logic into Python would have produced a check that agrees with the
scorer by construction and therefore proves nothing.

If they disagree, the disagreement names the row and the criterion to look at.

Reads the seed rows straight out of sql/04a_p1_seed_leads.sql, so editing a
scoring input there is reflected here immediately.

Usage:  python tools/expected_scores.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "segment.us-production-houses.json"
SEED = ROOT / "sql" / "04a_p1_seed_leads.sql"

INSERT_RE = re.compile(
    r"where slug = 'us-production-houses'\),\s*'([^']+)',.*?'(\{.*?\})'::jsonb",
    re.S,
)


def load_seed_rows(sql_text):
    """Return [(company_name, metadata_dict)] for every INSERT in the seed."""
    rows = []
    for m in INSERT_RE.finditer(sql_text):
        meta = json.loads(m.group(2).replace("''", "'"))
        if "scoring_inputs" in meta:
            rows.append((m.group(1), meta))
    return rows


def score(meta, cfg):
    """Apply the rubric exactly as BUILD_PLAN.md's invariants describe it.

    Returns (final, base, delta, criteria_assessed). final is None when nothing
    was assessed -- the scorer withholds a score rather than inventing one.
    """
    inputs = meta.get("scoring_inputs", {})

    earned = 0.0
    pool_assessed = 0.0
    assessed = 0
    for crit in cfg["rubric"]:
        key = crit["input"].rsplit(".", 1)[-1]
        # Invariant 1: a key that is absent, or present as null, means NEVER
        # ASSESSED -- excluded from the numerator and the denominator alike.
        # Never defaulted to zero.
        if inputs.get(key) is None:
            continue
        assessed += 1
        pool_assessed += crit["points"]
        earned += float(inputs[key]) * crit["points"]

    if pool_assessed == 0:
        return None, None, None, assessed

    base = (earned / pool_assessed) * 100.0

    # Modifiers are a delta applied AFTER normalizing, and only ever adjust a
    # score the rubric already produced.
    delta = 0.0
    for mod in cfg["score_modifiers"]:
        key = mod["input"].rsplit(".", 1)[-1]
        if inputs.get(key) is None:
            continue
        weight = mod["max_penalty"] if "max_penalty" in mod else mod["max_bonus"]
        delta += float(inputs[key]) * weight

    final = max(0.0, min(100.0, base + delta))
    return round(final, 2), round(base, 2), round(delta, 2), assessed


def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = load_seed_rows(SEED.read_text(encoding="utf-8"))
    if not rows:
        print("no seed rows found in %s" % SEED.name)
        return 1

    review = cfg["score_threshold_review"]
    priority = cfg["score_threshold_priority"]
    pool = sum(c["points"] for c in cfg["rubric"])
    n_criteria = len(cfg["rubric"])

    results = []
    for name, meta in rows:
        final, base, delta, assessed = score(meta, cfg)
        results.append((final, base, delta, assessed, name))
    results.sort(key=lambda r: (r[0] is None, -(r[0] or 0)))

    print("Expected P2 output -- compare against:")
    print("  select name, fit_score from entities where source = 'manual_p1' "
          "order by fit_score desc;\n")
    print("  %-28s %7s %7s %7s  %s" % ("company", "score", "base", "delta", "assessed"))
    print("  " + "-" * 76)
    for final, base, delta, assessed, name in results:
        print("  %-28s %7s %7s %7s  %d/%d criteria"
              % (name, final, base, delta, assessed, n_criteria))

    queued = [r for r in results if r[0] is not None and r[0] >= review]
    flagged = [r for r in results if r[0] is not None and r[0] >= priority]
    parked = [r for r in results if r[0] is not None and r[0] < review]

    print("")
    print("  thresholds: review >= %s, priority >= %s   (full rubric pool = %s points)"
          % (review, priority, pool))
    print("  %d flagged priority | %d reach the review queue | %d parked below review"
          % (len(flagged), len(queued), len(parked)))
    if parked:
        print("")
        print("  Parked below %s -- these will NOT appear in the P3 review queue:" % review)
        for r in parked:
            print("    - %-26s %s" % (r[4], r[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
