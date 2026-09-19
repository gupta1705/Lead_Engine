#!/usr/bin/env python3
"""kpis.py -- the v1 numbers, from sql/kpi_queries.sql, for any segment.

The same named queries the dashboard's /api/kpis runs, printed in a terminal.
Segment comes from SEGMENT_SLUG (default us-production-houses), so:

    python tools/kpis.py
    SEGMENT_SLUG=startup-acquisitions python tools/kpis.py
    python tools/kpis.py --json          # machine-readable, e.g. for a weekly note
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = os.environ.get("SEGMENT_SLUG", "us-production-houses")
KPI_SQL = ROOT / "sql" / "kpi_queries.sql"


def load_queries():
    """Split kpi_queries.sql on its '-- name: x' markers -> {name: sql}."""
    text = io.open(KPI_SQL, encoding="utf-8").read()
    out, cur_name, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"--\s*name:\s*(\w+)", line)
        if m:
            if cur_name:
                out[cur_name] = "\n".join(buf).strip().rstrip(";")
            cur_name, buf = m.group(1), []
        elif cur_name is not None and not line.startswith("--"):
            buf.append(line)
    if cur_name:
        out[cur_name] = "\n".join(buf).strip().rstrip(";")
    return out


def run_all(cursor_factory=None):
    """Return {name: row_or_rows}. Uses tools/dbconn when no cursor is given."""
    queries = load_queries()
    results = {}
    from dbconn import Db
    db = Db()
    for name, sql in queries.items():
        def fetch(cur, _sql=sql, _name=name):
            cur.execute("select set_config('tvf.segment', %s, false)", (SEGMENT,))
            cur.execute(_sql)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return rows if _name == "by_source" else (rows[0] if rows else {})
        results[name] = db.run(fetch)
    db.close()
    return results


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = run_all()
    if args.json:
        print(json.dumps(r, default=_plain, indent=1))
        return 0

    print("KPIs -- segment %s\n" % SEGMENT)
    for section in ("funnel", "outreach"):
        row = r.get(section) or {}
        print(section.upper())
        for k, v in row.items():
            print("  %-28s %s" % (k, _plain(v) if v is not None else "-"))
        print()
    print("BY SOURCE")
    print("  %-18s %6s %8s %12s" % ("source", "found", "contact", "shortlisted"))
    for s in r.get("by_source") or []:
        print("  %-18s %6s %8s %12s" % (s["source"], s["found"], s["contactable"], s["approved"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
