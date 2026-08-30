#!/usr/bin/env python3
"""users.py -- manage web-UI accounts from the terminal (owner only).

The first account is created through the app's own setup screen on first run.
This tool is for everything after: adding teammates, resetting a forgotten
password, listing who has access. Passwords are prompted for, never passed as
arguments (which would land in shell history).

    python tools/users.py list
    python tools/users.py add    teammate@theviralfever.com
    python tools/users.py passwd teammate@theviralfever.com
    python tools/users.py remove teammate@theviralfever.com
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bcrypt
from dbconn import Db


def _prompt_password():
    p1 = getpass.getpass("New password (10+ chars): ")
    if len(p1) < 10:
        sys.exit("too short -- 10 characters minimum")
    if p1 != getpass.getpass("Confirm: "):
        sys.exit("passwords did not match")
    return bcrypt.hashpw(p1.encode(), bcrypt.gensalt(12)).decode()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    db = Db()

    if cmd == "list":
        rows = db.run(lambda cur: (cur.execute(
            "select email, role, last_login_at from app_users order by created_at"),
            cur.fetchall())[1])
        for email, role, last in rows:
            print("  %-40s %-7s last login: %s" % (email, role, last or "never"))
        if not rows:
            print("  (no accounts yet -- create the owner via the app setup screen)")

    elif cmd == "add":
        if len(sys.argv) < 3:
            sys.exit("usage: users.py add <email>")
        email = sys.argv[2].strip().lower()
        pw = _prompt_password()
        db.run(lambda cur: cur.execute(
            "insert into app_users (email, password_hash, role)"
            " values (%s, %s, 'member')", (email, pw)))
        print("added", email)

    elif cmd == "passwd":
        if len(sys.argv) < 3:
            sys.exit("usage: users.py passwd <email>")
        email = sys.argv[2].strip().lower()
        pw = _prompt_password()
        n = db.run(lambda cur: (cur.execute(
            "update app_users set password_hash=%s where lower(email)=lower(%s)"
            " returning id", (pw, email)), cur.fetchall())[1])
        print("password reset" if n else "no such user")
        print("(any existing sessions for this user are now invalid)")

    elif cmd == "remove":
        if len(sys.argv) < 3:
            sys.exit("usage: users.py remove <email>")
        email = sys.argv[2].strip().lower()
        n = db.run(lambda cur: (cur.execute(
            "delete from app_users where lower(email)=lower(%s) and role<>'owner'"
            " returning id", (email,)), cur.fetchall())[1])
        print("removed" if n else "no such user, or refusing to remove the owner")

    else:
        sys.exit(__doc__)

    db.close()


if __name__ == "__main__":
    main()
