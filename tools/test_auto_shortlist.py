#!/usr/bin/env python3
"""test_auto_shortlist.py -- sql/14_auto_shortlist.sql against the real
database, inside one transaction that is rolled back.

    python tools/test_auto_shortlist.py

The rule shortlists leads with no person looking, so what matters most is what
it must NOT do: shortlist a score of exactly 20, touch a rejected or archived
row, re-shortlist a lead somebody put back, act for a segment that has not
turned it on, or keep acting after it has been turned off. Each of those is a
row below.

The LCX rule is set inside the transaction, so those cases do not depend on
the live config; the US Production Houses cases check its live rule (on, at
30 -- owner, 2026-09-21). Running the step also shortlists the real qualifying rows inside
the transaction; the checks only look at the rows this test creates, and the
rollback at the end undoes everything. Exit code 1 on any failure.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg2
from run_sql import load_db_url

ROOT = Path(__file__).resolve().parent.parent
STEP = (ROOT / "sql" / "14_auto_shortlist.sql").read_text(encoding="utf-8")
SEG = "lcx-clipping"
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name,
                        ("   (%s)" % (detail,)) if detail != "" and not cond else ""))


def main():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("select id from segments where slug = %s", (SEG,))
        seg_id = cur.fetchone()[0]
        cur.execute("select id, config -> 'auto_shortlist' from segments where slug = 'us-production-houses'")
        tvf_id, tvf_rule = cur.fetchone()
        # a segment that has never had the rule: US Production Houses was that segment until the owner
        # turned the rule on for it at 30 (2026-09-21), so the "untouched" case gets a throwaway one
        bare_slug = "zz-test-no-rule-" + uuid.uuid4().hex[:6]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'test', 'company', '{}')"
                    " returning id", (bare_slug,))
        bare_id = cur.fetchone()[0]
        cur.execute("update segments set config = jsonb_set(config, '{auto_shortlist}', %s::jsonb)"
                    " where id = %s", ('{"enabled": true, "min_score": 20}', seg_id))

        def lead(segment_id, status, score, meta=None):
            cur.execute("insert into entities (segment_id, name, source, status, fit_score, metadata)"
                        " values (%s, %s, 'test', %s, %s, %s::jsonb) returning id",
                        (segment_id, "ZZ auto shortlist " + uuid.uuid4().hex[:8], status, score,
                         json.dumps(meta or {})))
            return cur.fetchone()[0]

        def row(i):
            cur.execute("select status, coalesce(status_reason, ''),"
                        " coalesce(metadata, '{}'::jsonb) ? 'auto_shortlisted_at'"
                        " from entities where id = %s", (i,))
            return cur.fetchone()

        def run(segment):
            cur.execute("select set_config('tvf.segment', %s, true)", (segment,))
            cur.execute(STEP)

        low = lead(seg_id, "ready_for_review", 15)
        exactly = lead(seg_id, "ready_for_review", 20)
        just_above = lead(seg_id, "ready_for_review", 20.5)
        high = lead(seg_id, "ready_for_review", 88)
        rejected = lead(seg_id, "rejected", 95)
        archived = lead(seg_id, "archived", 95)
        put_back = lead(seg_id, "ready_for_review", 60,
                        {"auto_shortlisted_at": "2026-09-01T00:00:00+00:00"})
        bare_lead = lead(bare_id, "ready_for_review", 90)

        print("-- the rule, for the segment that has it on")
        run(SEG)
        check("a score of 15 stays in review", row(low)[0] == "ready_for_review", row(low))
        check("a score of exactly 20 is not 'above 20'", row(exactly)[0] == "ready_for_review", row(exactly))
        s = row(just_above)
        check("20.5 is shortlisted", s[0] == "shortlisted", s)
        check("  with a reason that says the rule did it", "auto-shortlisted: score 20.5 is above 20" in s[1], s[1])
        check("  and the stamp that protects a later reset", s[2] is True)
        check("88 is shortlisted", row(high)[0] == "shortlisted", row(high))
        check("a rejected lead stays rejected, whatever its score", row(rejected)[0] == "rejected")
        check("an archived lead stays archived, whatever its score", row(archived)[0] == "archived")
        check("a lead somebody put back in review is left there", row(put_back)[0] == "ready_for_review",
              row(put_back))

        print("\n-- running again")
        cur.execute("select count(*) from entities where segment_id = %s and status = 'shortlisted'", (seg_id,))
        before = cur.fetchone()[0]
        run(SEG)
        cur.execute("select count(*) from entities where segment_id = %s and status = 'shortlisted'", (seg_id,))
        check("shortlists nothing new", cur.fetchone()[0] == before)

        print("\n-- other segments, and off")
        run(bare_slug)
        check("a segment without the rule is untouched", row(bare_lead)[0] == "ready_for_review", row(bare_lead))

        # US Production Houses, by its live rule (owner, 2026-09-21: "short list all companies with a
        # score over 30"): exactly 30 stays in review, anything over it is shortlisted
        check("US Production Houses has the rule on, at 30",
              (tvf_rule or {}).get("enabled") is True and float((tvf_rule or {}).get("min_score") or 0) == 30,
              tvf_rule)
        at_line = lead(tvf_id, "ready_for_review", 30)
        over_line = lead(tvf_id, "ready_for_review", 30.5)
        run("us-production-houses")
        check("  a score of exactly 30 stays in review", row(at_line)[0] == "ready_for_review", row(at_line))
        check("  30.5 is shortlisted", row(over_line)[0] == "shortlisted", row(over_line))
        cur.execute("update segments set config = jsonb_set(config, '{auto_shortlist,enabled}', 'false')"
                    " where id = %s", (seg_id,))
        late = lead(seg_id, "ready_for_review", 70)
        run(SEG)
        check("turned off, it shortlists nothing", row(late)[0] == "ready_for_review", row(late))

        cur.execute("update segments set config = jsonb_set(config, '{auto_shortlist}',"
                    " '{\"enabled\": true}'::jsonb) where id = %s", (seg_id,))
        cur.execute("savepoint no_min")
        try:
            run(SEG)
            check("on but with no min_score, it refuses to guess", False)
        except psycopg2.Error:
            check("on but with no min_score, it refuses to guess", True)
        cur.execute("rollback to savepoint no_min")
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all test rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
