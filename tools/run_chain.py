#!/usr/bin/env python3
"""run_chain.py -- the promote-to-gates chain as one command.

The exact sequence run by hand after every harvest, now callable by the ops
runner in the UI. Order matters and is the point of this file existing:
self-exclusion must precede promote (so TVF itself never enters the pool),
duplicate-merge must precede scoring (so evidence lands on one row), and
gates run last against fresh scores. Any step failing stops the chain --
a half-run chain with a clear error beats a full run with silent damage.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

STEPS = [
    ("self-exclusion",   ["sql/05a_self_exclusion.sql"]),
    ("promote",          ["sql/05_promote_minimal.sql"]),
    ("merge duplicates", ["sql/05c_merge_name_duplicates.sql"]),
    ("zero unverified",  ["sql/04b_zero_unverified.sql"]),
    ("score",            ["-c", "select count(*) from score_segment('us-production-houses');"]),
    ("apply gates",      ["sql/13_apply_gates.sql"]),
]


def main():
    for name, args in STEPS:
        print("== %s ==" % name, flush=True)
        rc = subprocess.call(
            [sys.executable, str(REPO / "tools" / "run_sql.py")] + args,
            cwd=str(REPO))
        if rc != 0:
            print("chain stopped at '%s' (exit %d)" % (name, rc), flush=True)
            return rc
    print("chain complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
