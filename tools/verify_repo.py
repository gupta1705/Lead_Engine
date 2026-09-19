#!/usr/bin/env python3
"""verify_repo.py -- P0's repo-side self-check.

P0's done-when is "repo and DB agree". The DB half needs a human with the
Supabase SQL editor (sql/00_verify_state.sql). THIS is the repo half, and it
is fully mechanical, so it runs on every rung from here on -- not just once.

What it checks:
  1. Every sql/*.sql actually PARSES as PostgreSQL. Catches the class of bug
     that otherwise surfaces as a syntax error in the Supabase editor halfway
     through a sitting -- e.g. an unescaped apostrophe inside a single-quoted
     jsonb literal, which is exactly what bit 03/03b on 2026-08-20.
     Requires `pip install -r tools/requirements.txt`; skipped with a loud
     notice if pglast is missing, because the rest of the checks still have
     value without it.
     LIMIT: this is the SQL parser, so a CREATE FUNCTION body is only checked
     as an opaque dollar-quoted string -- a plpgsql error *inside* 06_score.sql
     would still slip through to first execution. Nothing available offline
     parses plpgsql; the first run of the scorer is still its real test.
  2. config/segment.us-production-houses.json is valid JSON.
  3. The JSON embedded in 03 and 03b is the SAME config as the .json file.
     Three copies of one config is a standing drift risk; this check is what
     makes keeping three copies safe.
  4. The v3 shape that 00_verify_state.sql checks the live DB against:
     6 rubric criteria / 4 gates / 3 modifiers (the review checklist was
     removed on 2026-09-19, and must stay gone), with
     genre_fit=15, right_size=20, revenue_above_cap=-20, thresholds 25/60.
  5. Structural invariants: every rubric/modifier/gate input path sits under
     metadata.scoring_inputs, keys are unique, rubric points are positive,
     each modifier carries exactly one of max_penalty/max_bonus, and every
     scoring_inputs key used in 04_insert_template.sql is one the config
     actually defines. That last one matters more than it looks: invariant 1
     (null != zero) means a typo'd key scores as "never assessed" forever and
     never raises an error -- the failure is silent by design.

Usage:  python tools/verify_repo.py     (exit 0 = green)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "segment.us-production-houses.json"
SQL_DIR = ROOT / "sql"
SEGMENT_SQL = ["03_segment_us_production_houses.sql", "03b_sync_segment_config_v3.sql"]

# The v3 shape, mirrored from sql/00_verify_state.sql. When an owner rubric
# review changes these, both files change together -- that is the point.
EXPECTED_COUNTS = {
    "rubric": 6,
    "gates": 4,
    "score_modifiers": 3,
}
EXPECTED_WEIGHTS = {"genre_fit": 15, "right_size": 20}
EXPECTED_PENALTY = {"revenue_above_cap": -20}
# Owner-set thresholds: review 25 / priority 60 set 2026-08-21; priority
# lowered to 45 on 2026-08-30 (owner decision) -- the verified band tops
# out at 57, so 60 was an aspiration no lead could meet.
EXPECTED_THRESHOLDS = {"score_threshold_review": 25, "score_threshold_priority": 45}

failures = []
notices = []


def fail(msg):
    failures.append(msg)


def extract_jsonb_literal(sql_text):
    """Pull the '{...}'::jsonb config literal out of a segment SQL file."""
    m = re.search(r"'(\{.*?\})'::jsonb", sql_text, re.S)
    if not m:
        raise ValueError("no '{...}'::jsonb literal found")
    # Postgres doubles a literal apostrophe inside a single-quoted string.
    return json.loads(m.group(1).replace("''", "'"))


def check_sql_parses():
    """1. Every SQL file is syntactically valid PostgreSQL."""
    try:
        from pglast import parse_sql
        from pglast.parser import ParseError
    except ImportError:
        notices.append(
            "SQL PARSE CHECK SKIPPED -- pglast is not installed.\n"
            "        Install it with:  pip install pglast\n"
            "        Without it, a SQL syntax error is only discovered when you\n"
            "        paste the file into the Supabase editor, mid-sitting."
        )
        return

    for path in sorted(SQL_DIR.glob("*.sql")):
        src = path.read_text(encoding="utf-8")
        try:
            parse_sql(src)
            print("  ok    parse   " + path.name)
        except ParseError as e:
            idx = getattr(e, "index", None)
            where = ""
            if idx is not None:
                line = src[:idx].count("\n") + 1
                ctx = src[max(0, idx - 70):idx].replace("\n", " ")
                where = " (line %d, just after: ...%s)" % (line, ctx)
            fail("%s does not parse as PostgreSQL: %s%s" % (path.name, e, where))


def check_config_copies():
    """2 + 3. Config is valid JSON, and all three copies of it agree."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail("%s is not valid JSON: %s" % (CONFIG.name, e))
        return {}
    print("  ok    json    " + CONFIG.name)

    canonical = json.dumps(cfg, sort_keys=True)
    for name in SEGMENT_SQL:
        path = SQL_DIR / name
        if not path.exists():
            fail("%s is missing" % name)
            continue
        try:
            embedded = extract_jsonb_literal(path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError) as e:
            fail("%s: could not read its embedded config JSON: %s" % (name, e))
            continue
        if json.dumps(embedded, sort_keys=True) != canonical:
            only_json = sorted(set(cfg) - set(embedded))
            only_sql = sorted(set(embedded) - set(cfg))
            differ = sorted(
                k for k in set(cfg) & set(embedded)
                if json.dumps(cfg[k], sort_keys=True)
                != json.dumps(embedded[k], sort_keys=True)
            )
            detail = ""
            if only_json:
                detail += "; keys only in the .json: %s" % only_json
            if only_sql:
                detail += "; keys only in the .sql: %s" % only_sql
            if differ:
                detail += "; differing keys: %s" % differ
            fail("%s: embedded config has DRIFTED from %s%s"
                 % (name, CONFIG.name, detail))
        else:
            print("  ok    match   %s == %s" % (name, CONFIG.name))
    return cfg


def check_v3_shape(cfg):
    """4. The v3 shape 00_verify_state.sql checks the live DB against."""
    mark = len(failures)
    for key, expected_n in EXPECTED_COUNTS.items():
        actual = len(cfg.get(key, []))
        if actual != expected_n:
            fail("config.%s: expected %d entries (v3), found %d"
                 % (key, expected_n, actual))
    if "review_checklist" in cfg:
        fail("config.review_checklist is back: the owner removed the checklist on 2026-09-19")
    if len(failures) == mark:
        print("  ok    counts  6 rubric / 4 gates / 3 modifiers / no checklist")

    mark = len(failures)
    rubric = {c.get("key"): c for c in cfg.get("rubric", [])}
    for key, pts in EXPECTED_WEIGHTS.items():
        if key not in rubric:
            fail("config.rubric is missing '%s'" % key)
        elif rubric[key].get("points") != pts:
            fail("config.rubric.%s.points: expected %s (v3), found %s"
                 % (key, pts, rubric[key].get("points")))

    mods = {m.get("key"): m for m in cfg.get("score_modifiers", [])}
    for key, pen in EXPECTED_PENALTY.items():
        if key not in mods:
            fail("config.score_modifiers is missing '%s'" % key)
        elif mods[key].get("max_penalty") != pen:
            fail("config.score_modifiers.%s.max_penalty: expected %s (v3), found %s"
                 % (key, pen, mods[key].get("max_penalty")))
    if len(failures) == mark:
        print("  ok    weights genre_fit=15, right_size=20, revenue_above_cap=-20")

    mark = len(failures)
    for key, val in EXPECTED_THRESHOLDS.items():
        if cfg.get(key) != val:
            fail("config.%s: expected %s, found %s" % (key, val, cfg.get(key)))
    if len(failures) == mark:
        print("  ok    thresh  review=25, priority=45")


def check_structure(cfg):
    """5. Structural invariants the scorer depends on. Returns known keys."""
    mark = len(failures)
    known_inputs = set()
    for section in ("rubric", "score_modifiers", "gates"):
        seen = set()
        for item in cfg.get(section, []):
            key = item.get("key")
            if key in seen:
                fail("config.%s: duplicate key '%s'" % (section, key))
            seen.add(key)
            path = item.get("input", "")
            if not path.startswith("metadata.scoring_inputs."):
                fail("config.%s.%s.input is '%s' -- every input must live under "
                     "metadata.scoring_inputs (06_score.sql strips the leading "
                     "'metadata.' and reads the rest as a jsonb path)"
                     % (section, key, path))
            else:
                known_inputs.add(path.rsplit(".", 1)[-1])

    # A 0-point rubric criterion would sit in the denominator contributing
    # nothing and quietly distort every score.
    for c in cfg.get("rubric", []):
        pts = c.get("points")
        if not isinstance(pts, (int, float)) or isinstance(pts, bool) or pts <= 0:
            fail("config.rubric.%s.points must be a positive number, got %r"
                 % (c.get("key"), pts))

    for m in cfg.get("score_modifiers", []):
        has_pen = "max_penalty" in m
        has_bon = "max_bonus" in m
        if has_pen == has_bon:
            fail("config.score_modifiers.%s must carry exactly one of "
                 "max_penalty / max_bonus (06_score.sql branches on that)"
                 % m.get("key"))
        if has_pen and m["max_penalty"] > 0:
            fail("config.score_modifiers.%s.max_penalty should be negative, got %s"
                 % (m.get("key"), m["max_penalty"]))
        if has_bon and m["max_bonus"] < 0:
            fail("config.score_modifiers.%s.max_bonus should be positive, got %s"
                 % (m.get("key"), m["max_bonus"]))
    if len(failures) == mark:
        print("  ok    struct  %d scoring_inputs keys, all well-formed" % len(known_inputs))
    return known_inputs


def check_template_keys(cfg, known_inputs):
    """5b. Every scoring_inputs block in every SQL file obeys the config.

    This is CHECK 2 from 04_insert_template.sql, run offline against the files
    instead of online against the rows. Same reasoning: invariant 1 makes a
    mistyped key indistinguishable from an honest blank, so nothing at runtime
    will ever complain -- the criterion just silently vanishes from the score.
    Catching it here means catching it before it reaches the database.
    """
    numeric_keys = set()
    for section in ("rubric", "score_modifiers"):
        for item in cfg.get(section, []):
            path = item.get("input", "")
            if path.startswith("metadata.scoring_inputs."):
                numeric_keys.add(path.rsplit(".", 1)[-1])

    mark = len(failures)
    total_blocks = 0
    for path in sorted(SQL_DIR.glob("*.sql")):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"scoring_inputs"\s*:\s*\{(.*?)\}', src, re.S):
            total_blocks += 1
            block = m.group(1)
            line = src[:m.start()].count("\n") + 1
            for key, raw in re.findall(r'"([a-z0-9_]+)"\s*:\s*([^,\n}]+)', block):
                raw = raw.strip()
                if key not in known_inputs:
                    fail("%s line %d: scoring_inputs key '%s' is not defined in the "
                         "config -- it will read as 'never assessed' forever and "
                         "never raise an error" % (path.name, line, key))
                    continue
                if key == "reachable_decision_maker":
                    fail("%s line %d: reachable_decision_maker is engine-set from a "
                         "verified contact at P10/P16 -- setting it by hand inflates "
                         "the score with a signal no contact record backs up"
                         % (path.name, line))
                    continue
                if key in numeric_keys:
                    try:
                        val = float(raw)
                    except ValueError:
                        fail("%s line %d: %s = %s -- rubric/modifier inputs must be "
                             "numeric" % (path.name, line, key, raw))
                        continue
                    if val not in (0.0, 0.5, 1.0):
                        fail("%s line %d: %s = %s -- rubric/modifier inputs must be "
                             "0, 0.5 or 1" % (path.name, line, key, raw))
    if len(failures) == mark:
        print("  ok    inputs  %d scoring_inputs block(s) across sql/, all valid"
              % total_blocks)


def check_cheatsheet_current(cfg):
    """6. docs/P1_scoring_cheatsheet.md still matches the config it came from.

    A hand-editable copy of the rubric would drift the first time an owner
    review changed a weight -- and a stale cheat sheet is worse than none,
    because it has you scoring against last month's rubric while believing you
    are current. So it is generated, and this check re-runs the generator and
    compares.
    """
    doc = ROOT / "docs" / "P1_scoring_cheatsheet.md"
    gen = ROOT / "tools" / "gen_p1_cheatsheet.py"
    if not gen.exists():
        return
    if not doc.exists():
        fail("docs/P1_scoring_cheatsheet.md is missing -- run "
             "`python tools/gen_p1_cheatsheet.py`")
        return
    sys.path.insert(0, str(gen.parent))
    try:
        import gen_p1_cheatsheet
    except ImportError as e:
        fail("could not import the cheat-sheet generator: %s" % e)
        return
    expected = gen_p1_cheatsheet.render(cfg)
    actual = doc.read_text(encoding="utf-8").replace("\r\n", "\n")
    if actual != expected:
        fail("docs/P1_scoring_cheatsheet.md is STALE -- the config has changed "
             "since it was generated. Re-run `python tools/gen_p1_cheatsheet.py`. "
             "(Scoring against a stale rubric is the failure this check exists "
             "to prevent.)")
    else:
        print("  ok    doc     P1_scoring_cheatsheet.md matches the config")


def check_n8n_workflows(cfg):
    """7. n8n connector workflows are structurally sound.

    A workflow is a JSON file full of SQL strings and config-key references,
    none of which any editor checks. The SQL inside a Postgres node is exactly
    as capable of a syntax error as a .sql file -- and far easier to miss,
    because it only surfaces when the workflow runs live, mid-sitting, after
    the API calls have already burned quota.
    """
    wf_dir = ROOT / "n8n"
    if not wf_dir.exists():
        return
    try:
        from pglast import parse_sql
        from pglast.parser import ParseError
        can_parse = True
    except ImportError:
        can_parse = False

    mark = len(failures)
    n_wf = n_sql = 0
    for path in sorted(wf_dir.rglob("*.json")):
        try:
            wf = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail("%s is not valid JSON: %s" % (path.name, e))
            continue
        n_wf += 1
        nodes = wf.get("nodes", [])
        if not nodes:
            fail("%s has no nodes" % path.name)
            continue

        for node in nodes:
            params = node.get("parameters", {}) or {}
            query = params.get("query")
            if not query or not isinstance(query, str):
                continue
            n_sql += 1
            # Config keys the workflow reads must actually exist in the config.
            for key in re.findall(r"config->'([a-z0-9_]+)'", query):
                if key not in cfg:
                    fail("%s node '%s' reads config->'%s', which the config "
                         "does not define" % (path.name, node.get("name"), key))
            if can_parse:
                try:
                    parse_sql(query)
                except ParseError as e:
                    fail("%s node '%s': SQL does not parse: %s"
                         % (path.name, node.get("name"), e))
    if len(failures) == mark:
        print("  ok    n8n     %d workflow(s), %d embedded SQL statement(s) valid"
              % (n_wf, n_sql))


def check_workflow_code_sync():
    """10. Workflow JSON jsCode matches the .js files it claims to come from.

    n8n stores a Code node script INSIDE the workflow JSON, and the repo also
    keeps it as a reviewable .js file. Two copies, and on 2026-08-24 they
    diverged: the genre_fit fix landed in the .js file, the fixtures passed
    against it, and n8n kept running the stale embedded copy -- so 123 live
    companies were scored on evidence nobody had. Green tests, wrong data.
    """
    import subprocess
    tool = ROOT / "tools" / "sync_workflow_code.py"
    if not tool.exists():
        return
    r = subprocess.run([sys.executable, str(tool), "--check"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        bad = [l.strip() for l in r.stdout.splitlines()
               if "DRIFTED" in l or "UNMAPPED" in l]
        indent = "\n        "
        fail("workflow JSON has drifted from the .js files:"
             + indent + indent.join(bad)
             + indent + "n8n runs the JSON, not the .js files. Fix with:"
             + indent + "python tools/sync_workflow_code.py"
             + indent + "python tools/n8n_setup.py")
    else:
        n = 0
        for line in r.stdout.splitlines():
            if "already in sync" in line:
                n = int(line.strip().split()[0])
        print("  ok    wfcode  %d Code node(s) match their .js source" % n)


def check_connector_fixtures():
    """8. The connector Code nodes still behave, run as node.js.

    These scripts were logic-validated once before the repo was cleared and
    have never run against live YouTube. Rule 4 says a re-adopted artifact is
    re-verified at adoption, not trusted because it passed once.
    """
    import shutil
    import subprocess
    test_dir = ROOT / "n8n" / "discovery" / "test"
    # Every connector gets its own fixture file; discover them rather than
    # naming one, so P6-P8 are covered the moment they are written instead of
    # whenever someone remembers to add them here.
    tests = sorted(test_dir.glob("run_*fixtures.js")) if test_dir.exists() else []
    if not tests:
        return
    if not shutil.which("node"):
        notices.append(
            "CONNECTOR FIXTURES SKIPPED -- node.js is not on PATH.\n"
            "        Run them with:  node n8n/discovery/test/run_*_fixtures.js"
        )
        return
    total = 0
    for test in tests:
        r = subprocess.run(["node", str(test)], capture_output=True, text=True)
        if r.returncode != 0:
            bad = [l.strip() for l in (r.stdout + r.stderr).splitlines() if "FAIL" in l]
            fail("%s FAILED:\n        %s"
                 % (test.name, "\n        ".join(bad[:8] or ["(run it directly)"])))
        else:
            total += sum(1 for l in r.stdout.splitlines() if l.strip().startswith("PASS"))
    if total:
        print("  ok    conn    %d connector fixture checks across %d file(s)"
              % (total, len(tests)))


def check_live_config(cfg):
    """9. The LIVE database config matches the repo config.

    verify_repo has always compared the three repo copies to each other, which
    is not the same as checking the database. On 2026-08-24 that gap bit:
    `news_rss_discovery_queries` was added to all three repo copies, everything
    reported GREEN, and the P5 connector still returned nothing -- because
    03b was never re-run, so the live segments row had never heard of the key.
    The failure was silent and looked like a broken connector.

    Needs SUPABASE_DB_URL; skipped with a notice when absent, so the offline
    checks still run on a machine with no credentials.
    """
    env = ROOT / ".env"
    if not env.exists():
        return
    url = None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SUPABASE_DB_URL="):
            url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        notices.append("LIVE CONFIG CHECK SKIPPED -- SUPABASE_DB_URL not set in .env")
        return
    try:
        import psycopg2
    except ImportError:
        notices.append("LIVE CONFIG CHECK SKIPPED -- psycopg2 not installed")
        return
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
    except Exception:
        notices.append("LIVE CONFIG CHECK SKIPPED -- could not reach the database")
        return
    try:
        with conn.cursor() as cur:
            cur.execute("select config from segments where slug = %s",
                        ("us-production-houses",))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        fail("no segments row for 'us-production-houses' in the live database")
        return
    live = row[0] if isinstance(row[0], dict) else json.loads(row[0])

    only_repo = sorted(set(cfg) - set(live))
    only_live = sorted(set(live) - set(cfg))
    differ = sorted(k for k in set(cfg) & set(live)
                    if json.dumps(cfg[k], sort_keys=True)
                    != json.dumps(live[k], sort_keys=True))
    if only_repo or only_live or differ:
        detail = ""
        if only_repo:
            detail += "; in the repo but NOT live: %s" % only_repo
        if only_live:
            detail += "; live but not in the repo: %s" % only_live
        if differ:
            detail += "; differing: %s" % differ
        fail("LIVE DATABASE CONFIG HAS DRIFTED from the repo%s\n"
             "        Fix: python tools/run_sql.py sql/03b_sync_segment_config_v3.sql"
             % detail)
    else:
        print("  ok    live    database config matches the repo exactly")


def main():
    print("TVF Lead Engine -- repo self-check (P0, repo half)\n")
    check_sql_parses()
    cfg = check_config_copies()
    if cfg:
        check_v3_shape(cfg)
        known = check_structure(cfg)
        check_template_keys(cfg, known)
        check_cheatsheet_current(cfg)
        check_n8n_workflows(cfg)
        check_live_config(cfg)
    check_workflow_code_sync()
    check_connector_fixtures()

    print("")
    for n in notices:
        print("  NOTE  " + n)
    if failures:
        print("\nFAILED -- %d problem(s):\n" % len(failures))
        for f in failures:
            print("  * %s\n" % f)
        return 1
    print("GREEN -- repo is self-consistent.")
    print("The other half of P0 is the live database: run sql/00_verify_state.sql")
    print("in the Supabase SQL editor and compare against the numbers above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
