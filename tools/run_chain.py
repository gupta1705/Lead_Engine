#!/usr/bin/env python3
"""run_chain.py -- the promote-to-gates chain as one command.

The exact sequence run by hand after every harvest, now callable by the ops
runner in the UI. Order matters and is the point of this file existing:
self-exclusion must precede promote (so TVF itself never enters the pool),
duplicate-merge must precede scoring (so evidence lands on one row), a
segment's input judge (LCX Services) runs on the merged row before anything
reads the inputs, and gates run last against fresh scores. Any step failing
stops the chain -- a half-run chain with a clear error beats a full run with
silent damage.
"""
import os
import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Segment 3 (2026-09-09): the chain runs for whichever segment it was started
# for. Every SQL step reads current_setting('tvf.segment'), which run_sql.py
# sets from the same variable, so one chain serves every segment.
SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,60}", SEGMENT):
    sys.exit("bad SEGMENT_SLUG: %r" % SEGMENT)

# A step is run_sql.py's arguments (a .sql file, or -c and a statement), or a Python tool (a path ending
# .py), run with this same interpreter.
STEPS = [
    ("self-exclusion",   ["sql/05a_self_exclusion.sql"]),
    ("promote",          ["sql/05_promote_minimal.sql"]),
    ("merge duplicates", ["sql/05c_merge_name_duplicates.sql"]),
    # LCX Services' scoring v4 (the owner, 2026-10-07: "think and decide one"): every scoring and gate input
    # judged afresh from each lead's stored record (tools/lcx_judge.py), after the merge has put a company's
    # evidence on one row and before anything reads the inputs: 04b fills only what is still missing, and both
    # score steps below score on today's judgement (shortlisted rows included: the judge writes theirs too,
    # or "score shortlisted" would renormalise stale keys). It exits 0 at once for a segment whose config has
    # no judge.enabled, so every other segment's chain runs as before.
    ("judge inputs",     ["tools/lcx_judge.py"]),
    ("zero unverified",  ["sql/04b_zero_unverified.sql"]),
    ("score",            ["-c", "select count(*) from score_segment('%s');" % SEGMENT]),
    # score_segment leaves shortlisted rows alone, but the news sweep and the site pass both write
    # evidence onto them without re-scoring (2026-09-21: Electric Entertainment's co-production
    # headline sat at 40.91 when its evidence gave 68.18). The number is refreshed, the status never
    # is: score_entity only ever advances discovered/enriched rows.
    ("score shortlisted", ["-c", "select count(score_entity(e.id)) from entities e join segments s"
                                 " on s.id = e.segment_id where s.slug = '%s' and e.status = 'shortlisted';"
                                 % SEGMENT]),
    ("apply gates",      ["sql/13_apply_gates.sql"]),
    # one primary contact per company, the best-ranked one (sql/28), after whatever the
    # enrichment passes added; the drafts and the lists read the same ranking (2026-09-17)
    ("primary contacts", ["-c", "select refresh_primary_contacts('%s');" % SEGMENT]),
    # last, so it only ever sees rows the gates have passed; a no-op for any
    # segment whose config does not turn auto_shortlist on (2026-09-14)
    ("auto shortlist",   ["sql/14_auto_shortlist.sql"]),
]


def command(args):
    """The command line for one step: a Python tool runs itself, anything else goes to run_sql.py."""
    if args and args[0].endswith(".py"):
        return [sys.executable, str(REPO / args[0])] + list(args[1:])
    return [sys.executable, str(REPO / "tools" / "run_sql.py")] + list(args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--defer-shortlist", action="store_true",
                        help="Qualify candidates now; shortlist only after enrichment finishes")
    options = parser.parse_args()
    print("segment: %s" % SEGMENT, flush=True)
    # every step is told the segment explicitly: a tool's own default may differ from the chain's
    # (tools/lcx_judge.py defaults to lcx-services, the chain to us-production-houses), so a chain started
    # with no SEGMENT_SLUG must not judge another project's leads
    env = dict(os.environ, SEGMENT_SLUG=SEGMENT)
    for name, args in STEPS:
        if options.defer_shortlist and name == "auto shortlist":
            continue
        print("== %s ==" % name, flush=True)
        rc = subprocess.call(command(args), cwd=str(REPO), env=env)
        if rc != 0:
            print("chain stopped at '%s' (exit %d)" % (name, rc), flush=True)
            return rc
    print("chain complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
