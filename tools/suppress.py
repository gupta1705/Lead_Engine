#!/usr/bin/env python3
"""suppress.py -- the do-not-contact list by hand (sql/48; the owner, 2026-11-12).

    python tools/suppress.py add maya@show.com "asked on a call not to be emailed"
    python tools/suppress.py add show.com "the whole company asked us to stop" --domain
    python tools/suppress.py remove maya@show.com
    python tools/suppress.py list [--limit 50]

An address on the list gets no draft, no approval and no send from any project; a domain covers every address at
that organisation (never a free mailbox provider such as gmail.com). The engine adds entries itself for unsubscribe
and "not interested" replies, bounces and inboxes nobody reads; this is for everything else.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import outreach_policy as pol  # noqa: E402
from dbconn import Db  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("value", help="an email address, or a domain with --domain")
    a.add_argument("reason")
    a.add_argument("--domain", action="store_true", help="the whole organisation's domain")
    a.add_argument("--by", default=None, help="who asked for it")
    r = sub.add_parser("remove")
    r.add_argument("value")
    ls = sub.add_parser("list")
    ls.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    db = Db()
    try:
        if args.cmd == "add":
            v = args.value.strip().lower()
            if args.domain:
                v = v.split("@")[-1]
                if v in pol.FREE_MAIL_DOMAINS:
                    sys.exit("%s is a free mailbox provider: add the address itself, not the whole domain" % v)
                n = db.run(lambda cur: (cur.execute(
                    "insert into suppressions (kind, value, reason, source, created_by) values ('domain', %s, %s,"
                    " 'manual', %s) on conflict (kind, value) do nothing", (v, args.reason, args.by)), cur.rowcount)[1])
            else:
                if "@" not in v:
                    sys.exit("that is not an email address; for a whole company use --domain")
                n = db.run(lambda cur: pol.suppress(cur, v, args.reason, "manual", by=args.by))
            print("added" if n else "already on the list", v)
        elif args.cmd == "remove":
            v = args.value.strip().lower()
            n = db.run(lambda cur: (cur.execute("delete from suppressions where value = %s", (v,)), cur.rowcount)[1])
            print("removed %d entr%s for %s" % (n, "y" if n == 1 else "ies", v))
        else:
            rows = db.run(lambda cur: (cur.execute(
                "select kind, value, reason, source, created_at::date from suppressions order by created_at desc limit %s",
                (args.limit,)), cur.fetchall())[1])
            total = db.run(lambda cur: (cur.execute("select count(*) from suppressions"), cur.fetchone()[0])[1])
            for kind, value, reason, source, at in rows:
                print("%-6s %-40s %-12s %s  %s" % (kind, value[:40], source, at, reason[:60]))
            print("%d on the list" % total)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
