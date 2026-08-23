#!/usr/bin/env python3
"""review_sheet.py -- render the P3 review queue as something a human can read.

`select * from review_queue` returns jsonb blobs in a terminal grid, which is
unreadable exactly when it matters most: the moment you are deciding whether a
real company gets contacted. This renders one card per candidate -- score with
its arithmetic shown, why_fit, the scoring inputs that produced the number, the
three human-judgement checklist items, and the research notes the connectors
could not have found.

Reads the live database through the same .env credential as run_sql.py.

Usage:  python tools/review_sheet.py            # all queued candidates
        python tools/review_sheet.py --brief    # one line each
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

SEGMENT = "us-production-houses"


def fetch(sql):
    from run_sql import load_db_url
    import psycopg2
    conn = psycopg2.connect(load_db_url(), connect_timeout=20)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def as_obj(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def fmt_value(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="store_true", help="one line per candidate")
    args = ap.parse_args()

    rows = fetch("""
        select e.id, e.name, e.domain, e.fit_score, e.score_breakdown,
               e.metadata, s.config->'review_checklist' as checklist,
               s.config->>'score_threshold_review'   as t_review,
               s.config->>'score_threshold_priority' as t_priority
        from entities e
        join segments s on s.id = e.segment_id
        where s.slug = '%s' and e.status = 'ready_for_review'
        order by e.fit_score desc nulls last
    """ % SEGMENT)

    if not rows:
        print("Review queue is empty -- every candidate has been dispositioned.")
        return 0

    t_review = float(rows[0]["t_review"])
    t_priority = float(rows[0]["t_priority"])

    if args.brief:
        print("%-28s %7s  %s" % ("company", "score", "flag"))
        print("-" * 60)
        for r in rows:
            score = float(r["fit_score"])
            flag = ("PRIORITY" if score >= t_priority
                    else "" if score >= t_review else "below review threshold")
            print("%-28s %7.2f  %s" % (r["name"], score, flag))
        return 0

    checklist = as_obj(rows[0]["checklist"])

    print("=" * 78)
    print("P3 REVIEW QUEUE -- %d candidates, score-ordered" % len(rows))
    print("thresholds: review >= %g, priority >= %g" % (t_review, t_priority))
    print("=" * 78)

    for n, r in enumerate(rows, 1):
        meta = as_obj(r["metadata"])
        bd = as_obj(r["score_breakdown"])
        research = meta.get("p1_research", {})
        score = float(r["fit_score"])

        flag = ""
        if score >= t_priority:
            flag = "   [PRIORITY]"
        elif score < t_review:
            flag = "   [below review threshold -- routing starts at P15]"

        print("")
        print("-" * 78)
        print("%d. %s  --  %s%s" % (n, r["name"], score, flag))
        print("   %s   id=%s" % (r["domain"] or "(no domain)", r["id"]))
        print("-" * 78)
        print("   WHY: %s" % meta.get("why_fit", "(none)"))

        print("")
        print("   SCORE: %s base %s %s modifiers = %s   (%s of %s criteria assessed)"
              % (bd.get("base_score"),
                 "+" if float(bd.get("modifier_delta", 0)) >= 0 else "-",
                 abs(float(bd.get("modifier_delta", 0))),
                 bd.get("final_score"),
                 bd.get("criteria_known"), bd.get("criteria_total")))

        for c in bd.get("criteria", []):
            if c.get("assessed"):
                print("     + %-28s %s of %s" % (c["key"], c.get("points_earned"),
                                                 c.get("points_possible")))
            else:
                print("     ? %-28s NOT ASSESSED (excluded from the score entirely)"
                      % c["key"])
        for m in bd.get("modifiers", []):
            if m.get("assessed"):
                d = float(m.get("delta", 0))
                if d:
                    print("     %s %-28s %s" % ("-" if d < 0 else "+", m["key"], d))
            else:
                print("     ? %-28s not assessed" % m["key"])

        if research:
            print("")
            print("   RESEARCH (from the source spreadsheet -- not connector-derived):")
            for k in ("key_contact", "published_email", "phone", "ownership",
                      "revenue_estimate", "caveats"):
                v = research.get(k)
                if v:
                    print("     %-18s %s" % (k + ":", v))

        print("")
        print("   HUMAN JUDGEMENT -- these are never auto-enforced:")
        for item in checklist:
            print("     [ ] %s" % item["label"])

    print("")
    print("=" * 78)
    print("TO DISPOSITION -- run these, or tell me the calls and I will:")
    print("")
    print("  shortlist:  update entities set status = 'shortlisted' where id = '<id>';")
    print("  reject:     update entities set status = 'rejected',")
    print("                     status_reason = '<one line, always>' where id = '<id>';")
    print("")
    print("A rejection without a reason is a decision you cannot audit later, and")
    print("rejection reasons read as a group are what tune the rubric at P11.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
