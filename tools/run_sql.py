#!/usr/bin/env python3
"""run_sql.py -- run a .sql file against the live Supabase database.

Owner decision 2026-08-23: Claude runs the SQL from here on, rather than
handing files over to be pasted into the Supabase editor.

THE CREDENTIAL NEVER ENTERS A TRANSCRIPT. This script reads SUPABASE_DB_URL
out of the gitignored `.env` at runtime. It is never printed, never echoed on
error, and never passed on a command line (which would put it in shell
history). If a connection error message contains it, the message is redacted
before display.

WHAT IT DOES
  - splits the file into statements with the real Postgres parser (pglast), so
    dollar-quoted function bodies and DO blocks stay intact rather than being
    chopped at a semicolon inside a string
  - runs the whole file in ONE transaction: either the entire script applies or
    none of it does. Postgres DDL is transactional, so a script that fails
    halfway does not leave a half-built schema behind
  - prints RAISE NOTICE output, which is the entire point of 02_smoke_test.sql
    -- without it you cannot see the PASS lines
  - prints result sets as tables

THE DESTRUCTIVE GUARD
  DROP, TRUNCATE and DELETE are refused unless --allow-destructive is passed.
  This is not ceremony. This project's core guarantees are "one touch per
  company, ever" and "rejected entities are permanently shielded from
  re-import" (BUILD_PLAN.md invariants 4 and 5), and both are enforced by rows
  that must not silently disappear. An accidental DELETE on `outreach` at P24
  means a real company gets emailed twice.

  Detection is AST-based, not regex: a DELETE *inside* a DO block or a function
  body is not flagged, because the parser sees a DoStmt, not a DeleteStmt.
  That is correct -- 02_smoke_test.sql cleans up after itself that way.

USAGE
  python tools/run_sql.py sql/04a_p1_seed_leads.sql
  python tools/run_sql.py sql/00_verify_state.sql --dry-run
  python tools/run_sql.py -c "select count(*) from entities"
  python tools/run_sql.py sql/90_reset_prototype.sql --allow-destructive
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
ENV_KEY = "SUPABASE_DB_URL"

DESTRUCTIVE_NODES = {
    "DropStmt": "DROP",
    "TruncateStmt": "TRUNCATE",
    "DeleteStmt": "DELETE",
    "DropdbStmt": "DROP DATABASE",
    "DropRoleStmt": "DROP ROLE",
    "DropOwnedStmt": "DROP OWNED",
}

MAX_ROWS = 60
MAX_CELL = 70


def load_db_url():
    """Read SUPABASE_DB_URL from .env. Never returns it to anything that prints."""
    if not ENV.exists():
        sys.exit(
            "No .env file found at %s\n"
            "Create it with:  cp .env.example .env\n"
            "then fill in SUPABASE_DB_URL (see .env.example for where to get it)."
            % ENV
        )
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == ENV_KEY:
            val = val.strip().strip('"').strip("'")
            if val:
                return val
    sys.exit(
        "%s is not set in .env\n\n"
        "Get it from: Supabase -> Project Settings -> Database -> Connection string\n"
        "  -> choose the *Session pooler* tab (port 5432), copy the URI, and\n"
        "     replace [YOUR-PASSWORD] with your database password.\n"
        "Paste it into .env as:  %s=postgresql://...\n"
        "Do NOT paste it into chat -- .env is gitignored, chat is not."
        % (ENV_KEY, ENV_KEY)
    )


def redact(text, secret):
    """Strip the connection string (and its password) out of any message."""
    out = str(text)
    if secret:
        out = out.replace(secret, "<SUPABASE_DB_URL redacted>")
        m = re.search(r"://[^:]+:([^@]+)@", secret)
        if m and m.group(1):
            out = out.replace(m.group(1), "<password redacted>")
    return out


def classify(stmt_sql):
    """Return (node_type_name, destructive_label_or_None) for one statement."""
    from pglast import parse_sql
    try:
        parsed = parse_sql(stmt_sql)
    except Exception:
        return "unparsed", None
    if not parsed:
        return "empty", None
    node = parsed[0].stmt
    name = type(node).__name__
    return name, DESTRUCTIVE_NODES.get(name)


def render_table(columns, rows):
    if not rows:
        return "    (0 rows)"
    def cell(v):
        s = "NULL" if v is None else str(v)
        s = s.replace("\n", " ")
        return s if len(s) <= MAX_CELL else s[:MAX_CELL - 1] + "…"
    shown = rows[:MAX_ROWS]
    table = [[cell(v) for v in r] for r in shown]
    widths = [len(c) for c in columns]
    for r in table:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(v))
    out = ["    " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns))]
    out.append("    " + "  ".join("-" * w for w in widths))
    for r in table:
        out.append("    " + "  ".join(v.ljust(widths[i]) for i, v in enumerate(r)))
    if len(rows) > MAX_ROWS:
        out.append("    ... %d more row(s) not shown" % (len(rows) - MAX_ROWS))
    else:
        out.append("    (%d row%s)" % (len(rows), "" if len(rows) == 1 else "s"))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Run SQL against the live Supabase DB.")
    ap.add_argument("file", nargs="?", help="path to a .sql file")
    ap.add_argument("-c", "--command", help="inline SQL instead of a file")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the statements and stop, without connecting")
    ap.add_argument("--allow-destructive", action="store_true",
                    help="permit DROP / TRUNCATE / DELETE (refused by default)")
    ap.add_argument("--autocommit", action="store_true",
                    help="run each statement outside a transaction")
    args = ap.parse_args()

    if args.command:
        sql_text, label = args.command, "<inline>"
    elif args.file:
        path = Path(args.file)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            sys.exit("no such file: %s" % path)
        sql_text, label = path.read_text(encoding="utf-8"), path.name
    else:
        ap.error("give a .sql file or -c \"SQL\"")

    import pglast
    statements = [s for s in pglast.split(sql_text) if s.strip()]

    print("%s -- %d statement(s)\n" % (label, len(statements)))

    blocked = []
    plan = []
    for i, stmt in enumerate(statements, 1):
        kind, destructive = classify(stmt)
        plan.append((i, stmt, kind, destructive))
        if destructive and not args.allow_destructive:
            blocked.append((i, destructive, kind))

    if blocked:
        print("REFUSED -- destructive statement(s) found:\n")
        for i, verb, kind in blocked:
            print("  statement %d: %s (%s)" % (i, verb, kind))
        print("\nThis project's invariants depend on rows not silently disappearing")
        print("(one touch per company; rejected entities shielded from re-import).")
        print("Re-run with --allow-destructive if this is genuinely intended.")
        return 2

    if args.dry_run:
        for i, stmt, kind, _ in plan:
            first = " ".join(stmt.split())[:100]
            print("  %2d. [%s] %s%s" % (i, kind, first, "..." if len(first) == 100 else ""))
        print("\n(dry run -- nothing was executed, no connection made)")
        return 0

    db_url = load_db_url()
    import psycopg2

    try:
        conn = psycopg2.connect(db_url, connect_timeout=20)
    except Exception as e:
        print("CONNECTION FAILED: %s" % redact(e, db_url))
        print("\nCommon causes:")
        print("  - password contains a special character (@ : / #) and is not")
        print("    percent-encoded in the URI")
        print("  - using the Direct connection string (IPv6-only) instead of the")
        print("    Session pooler string -- prefer the pooler on port 5432")
        print("  - wrong database password (it is NOT the service-role key)")
        return 1

    conn.autocommit = bool(args.autocommit)
    failed = False
    try:
        with conn.cursor() as cur:
            for i, stmt, kind, _ in plan:
                first = " ".join(stmt.split())[:90]
                print("  %2d. [%s] %s%s" % (i, kind, first, "..." if len(first) == 90 else ""))
                del conn.notices[:]
                try:
                    cur.execute(stmt)
                except Exception as e:
                    failed = True
                    print("\n    ERROR: %s" % redact(e, db_url))
                    break
                for n in conn.notices:
                    print("    | %s" % n.rstrip())
                if cur.description:
                    cols = [d[0] for d in cur.description]
                    print(render_table(cols, cur.fetchall()))
                elif cur.rowcount is not None and cur.rowcount >= 0:
                    print("    %d row(s) affected" % cur.rowcount)
                print("")
        if failed:
            if not args.autocommit:
                conn.rollback()
                print("ROLLED BACK -- nothing in this file was applied.")
            return 1
        if not args.autocommit:
            conn.commit()
        print("COMMITTED -- %d statement(s) applied." % len(plan))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
