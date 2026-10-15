#!/usr/bin/env python3
"""users.py -- manage web-UI accounts from the terminal (owner only).

The first account is created through the app's own setup screen on first run.
This tool is for everything after: adding teammates, resetting a forgotten
password, listing who has access. Passwords are prompted for, never passed as
arguments (which would land in shell history).

    python tools/users.py list
    python tools/users.py team   a@theviralfever.com b@theviralfever.com [--remove old@theviralfever.com]
    python tools/users.py add    teammate@theviralfever.com [--starting]
    python tools/users.py passwd teammate@theviralfever.com [--starting]
    python tools/users.py remove teammate@theviralfever.com
    python tools/users.py gmail  teammate@theviralfever.com [--cap 35] [--move]
    python tools/users.py gmail-remove sending@theviralfever.com

One account per person (owner, 2026-09-26): each person signs in with their own
login, and the emails they approve go out from the Gmail address the owner links
to them, signed with their name.

`gmail` links a sending address to a person: Google's own sign-in opens in a
browser, the owner signs in to the address that person will send from, and the
sign-in is sealed so that only the live server can read it (it is fetched the
server's public key first, over HTTPS). Each address sends up to 35 a day
(`--cap` for another number); a person may have several. Running it again for
the same address refreshes its sign-in; `--move` moves an address from one
person to another. `gmail-remove` unlinks an address.

`team` sets up several people at once with one STARTING password: it works for
their first sign-in only, which asks each of them for their own password, their
name and their title. Anyone listed who already has a login gets the starting
password too. `--remove` takes logins away (after a typed yes); their connected
Gmail addresses go with them, their approvals and sent emails stay in the history.
`--starting` does the same for one person with `add` or `passwd`.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bcrypt
from dbconn import Db


def _prompt_password(starting=False):
    """A password typed twice, hashed. A starting password (used once, then replaced by the person's
    own) may be as short as 8; one somebody keeps needs 10."""
    minimum = 8 if starting else 10
    p1 = getpass.getpass("%s (%d+ characters): " % ("Starting password" if starting else "New password", minimum))
    if len(p1) < minimum:
        sys.exit("too short -- %d characters minimum" % minimum)
    if p1 != getpass.getpass("Confirm: "):
        sys.exit("passwords did not match")
    return bcrypt.hashpw(p1.encode(), bcrypt.gensalt(12)).decode()


def _emails(args):
    out = []
    for a in args:
        e = a.strip().lower()
        if "@" not in e or e.startswith("--"):
            sys.exit("not an email address: %r" % a)
        out.append(e)
    return out


def _env(name):
    import io
    import os
    v = os.environ.get(name)
    if v:
        return v.strip()
    envfile = Path(__file__).resolve().parent.parent / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def _server_key():
    """The live server's public key, over HTTPS: a sign-in sealed with it is readable only there."""
    import json
    import urllib.request
    base = (_env("PUBLIC_BASE_URL") or "https://tvf-lead-engine.onrender.com").rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/mailboxes/server-key", timeout=30) as r:
            key = json.loads(r.read().decode()).get("x25519")
    except Exception as e:
        sys.exit("could not get the server's key from %s (%s). Is the latest version deployed?" % (base, e))
    if not key:
        sys.exit("the server at %s did not give a key" % base)
    return key


def _google_signin():
    """Google's own sign-in, in a browser, for the address the person will send from -> Credentials."""
    cid, csec = _env("GOOGLE_OAUTH_CLIENT_ID"), _env("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not csec:
        sys.exit("GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be in .env (the Desktop client)")
    import mailbox_store as store
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": cid, "client_secret": csec,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": store.TOKEN_URI, "redirect_uris": ["http://localhost"]}},
        [store.GMAIL_SCOPE])
    return flow.run_local_server(
        port=0, prompt="consent select_account",
        authorization_prompt_message="A browser window is opening. Sign in to the address this person will send from.\n",
        success_message="Connected. You can close this tab and go back to the terminal.")


def _set_password(cur, email, pw_hash, starting, role="member"):
    """Create the login, or give an existing one this password. -> 'added' | 'reset'."""
    cur.execute("update app_users set password_hash = %s, must_change_password = %s"
                " where lower(email) = lower(%s) returning id", (pw_hash, starting, email))
    if cur.fetchone():
        return "reset"
    cur.execute("insert into app_users (email, password_hash, role, must_change_password)"
                " values (%s, %s, %s, %s)", (email, pw_hash, role, starting))
    return "added"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    args = [a for a in sys.argv[2:]]
    starting = "--starting" in args
    args = [a for a in args if a != "--starting"]
    db = Db()

    if cmd == "list":
        rows = db.run(lambda cur: (cur.execute(
            "select u.email, u.role, u.name, u.title, u.must_change_password, u.last_login_at,"
            " (select string_agg(m.address || case when m.last_error is null then '' else ' (reconnect)' end, ', ')"
            "    from user_mailboxes m where lower(m.user_email) = lower(u.email)) as gmail"
            " from app_users u order by u.created_at"), cur.fetchall())[1])
        for email, role, name, title, must, last, gmail in rows:
            print("  %-36s %-7s %-28s %s" % (email, role, ((name or "-") + (", " + title if title else ""))[:28],
                                            "starting password, not signed in yet" if must else
                                            "last login: %s" % (last or "never")))
            print("  %-36s Gmail: %s" % ("", gmail or "none connected"))
        if not rows:
            print("  (no accounts yet -- create the owner via the app setup screen)")

    elif cmd == "team":
        remove = []
        if "--remove" in args:
            i = args.index("--remove")
            remove, args = _emails(args[i + 1:]), args[:i]
        emails = _emails(args)
        if not emails:
            sys.exit("usage: users.py team <email> [<email> ...] [--remove <email> ...]")
        clash = set(emails) & set(remove)
        if clash:
            sys.exit("both kept and removed: %s" % ", ".join(sorted(clash)))
        print("Accounts to set up with one starting password: %s" % ", ".join(emails))
        print("Each person's first sign-in asks for their own password, name and title.")
        pw = _prompt_password(starting=True)
        if remove:
            answer = input("Remove the login%s %s? Their connected Gmail goes too; their past approvals and"
                           " sent emails stay. Type yes: " % ("s" if len(remove) > 1 else "", ", ".join(remove)))
            if answer.strip().lower() != "yes":
                sys.exit("nothing changed")

        def apply(cur):
            done = [(e, _set_password(cur, e, pw, True)) for e in emails]
            gone = []
            for e in remove:
                cur.execute("delete from app_users where lower(email) = lower(%s) returning email", (e,))
                if cur.fetchone():
                    gone.append(e)
            # somebody stays the owner: the first one listed, when the owner was among those removed
            cur.execute("select count(*) from app_users where role = 'owner'")
            promoted = None
            if cur.fetchone()[0] == 0:
                cur.execute("update app_users set role = 'owner' where lower(email) = lower(%s)", (emails[0],))
                promoted = emails[0]
            return done, gone, promoted
        done, gone, promoted = db.run(apply)
        for e, what in done:
            print("  %-40s %s, starting password set" % (e, what))
        for e in gone:
            print("  %-40s removed" % e)
        for e in remove:
            if e not in gone:
                print("  %-40s had no login" % e)
        if promoted:
            print("  %-40s is now the owner" % promoted)
        print("Done. Send each person the site address and the starting password; they choose their own at"
              " first sign-in. Link the address each one sends from later with: users.py gmail <login>"
              " (until then, what they approve waits in Approved).")

    elif cmd == "add":
        emails = _emails(args)
        if len(emails) != 1:
            sys.exit("usage: users.py add <email> [--starting]")
        pw = _prompt_password(starting)
        what = db.run(lambda cur: _set_password(cur, emails[0], pw, starting))
        print("%s %s%s" % (what, emails[0], " (starting password: they choose their own at first sign-in)"
                           if starting else ""))

    elif cmd == "passwd":
        emails = _emails(args)
        if len(emails) != 1:
            sys.exit("usage: users.py passwd <email> [--starting]")
        pw = _prompt_password(starting)
        n = db.run(lambda cur: (cur.execute(
            "update app_users set password_hash=%s, must_change_password=%s where lower(email)=lower(%s)"
            " returning id", (pw, starting, emails[0])), cur.fetchall())[1])
        print("password reset" if n else "no such user")
        print("(any existing sessions for this user are now invalid)")

    elif cmd == "gmail":
        import json
        import mailbox_store as store
        cap, move = None, "--move" in args
        args = [a for a in args if a != "--move"]
        if "--cap" in args:
            i = args.index("--cap")
            try:
                cap = int(args[i + 1])
            except (IndexError, ValueError):
                sys.exit("--cap needs a number, e.g. --cap 35")
            if not 1 <= cap <= 2000:
                sys.exit("--cap is between 1 and 2000 a day")
            args = args[:i] + args[i + 2:]
        emails = _emails(args)
        if len(emails) != 1:
            sys.exit("usage: users.py gmail <person's login> [--cap 35] [--move]")
        person = emails[0]
        known = db.run(lambda cur: (cur.execute("select email from app_users where lower(email) = lower(%s)",
                                                (person,)), cur.fetchone())[1])
        if not known:
            sys.exit("no login %s -- create it first (users.py team ...)" % person)
        key = _server_key()                                # before the browser: fail early, not after signing in
        creds = _google_signin()
        from googleapiclient.discovery import build
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        address = gmail.users().getProfile(userId="me").execute()["emailAddress"].strip().lower()
        try:
            send_as = store.read_send_as(gmail)        # its "Send mail as" aliases (sql/36): the LCX address is one
        except Exception:                              # noqa: BLE001 -- read again at the next send
            send_as = None
        info = json.loads(creds.to_json())
        if not info.get("refresh_token"):
            sys.exit("Google did not give a lasting sign-in for %s; run it again" % address)
        try:
            db.run(lambda cur: store.save(cur, known[0], address, token_enc=store.seal(info, key),
                                          daily_cap=cap, move=move, send_as=send_as))
        except ValueError as e:
            sys.exit("%s (add --move to move it to %s)" % (e, known[0]))
        per_day = db.run(lambda cur: (cur.execute("select daily_cap from user_mailboxes where lower(address) = %s",
                                                  (address,)), cur.fetchone())[1][0])
        print("%s now sends from %s (%d a day). Emails they approve go out from it; the Outreach page shows its count."
              % (known[0], address, per_day))
        if send_as:
            print("  it can also send as: %s" % ", ".join(a["address"] for a in send_as))

    elif cmd == "gmail-remove":
        import mailbox_store as store
        emails = _emails(args)
        if len(emails) != 1:
            sys.exit("usage: users.py gmail-remove <sending address>")
        if input("Unlink %s? Emails its person approves stop going out from it. Type yes: " % emails[0]).strip().lower() != "yes":
            sys.exit("nothing changed")
        gone = db.run(lambda cur: store.remove(cur, emails[0]))
        print("unlinked %s from %s" % (gone["address"], gone["user_email"]) if gone else "no such sending address")
        print("(Google's permission for it stays until it is removed at myaccount.google.com -> Security)")

    elif cmd == "remove":
        emails = _emails(args)
        if len(emails) != 1:
            sys.exit("usage: users.py remove <email>")
        n = db.run(lambda cur: (cur.execute(
            "delete from app_users where lower(email)=lower(%s) and role<>'owner'"
            " returning id", (emails[0],)), cur.fetchall())[1])
        print("removed" if n else "no such user, or refusing to remove the owner (use: team ... --remove)")

    else:
        sys.exit(__doc__)

    db.close()


if __name__ == "__main__":
    main()
