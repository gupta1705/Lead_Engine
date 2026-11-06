#!/usr/bin/env python3
"""test_accounts.py -- one login per person, each with their own Gmail (owner, 2026-09-26), as a table.

    python tools/test_accounts.py

The real app runs in-process (FastAPI's TestClient) against the real database inside ONE transaction that
is rolled back: throwaway people, a throwaway project in "send from the approver" mode, drafts, sending
addresses. Google is a stand-in (the owner's sign-in in tools/users.py gmail, the profile), so nothing
leaves the machine, and the server's secret is a test one. Checked:

  * a starting password opens nothing but the screen that replaces it; changing it keeps this session and
    ends the others; the rules on a new password; name and title
  * each person sees a draft as THEY would send it (their sign-off, Kartikeya his own first-person line),
    saving an edit stores the project's own form, approving stores theirs and needs a name and title
  * the owner links a person's sending address (users.py gmail): sealed with the server's public key
    so only the server reads it, one address one person (--move to change), refresh and --cap
  * each person connects their own Gmail in the app (owner, 2026-10-14): off without a Web application
    client, Google's sign-in with a state only they can finish, an address someone else holds refused and
    its permission withdrawn, disconnecting only their own
  * the Sending today list, "reached out by" on leads, the lead dialog and the per-person report
  * with the repo's sending window (owner, 2026-10-12): an approval draws its own moment even before the
    approver has an address, and Sending today counts each person's approvals by the day they go

Exit code 1 on any failure.
"""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-accounts-test-" + uuid.uuid4().hex     # a test key: cookies and sign-ins
os.environ.pop("PUBLIC_BASE_URL", None)

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import main  # noqa: E402
import auth  # noqa: E402
import mailbox_store as store  # noqa: E402
import draft_render as dr  # noqa: E402

RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-74s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:100]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:100])))


class TxConn:
    """The app's pooled connection, replaced by the test's one transaction (a savepoint per request)."""

    def __init__(self, conn):
        self._c, self.closed = conn, 0

    def begin(self):
        with self._c.cursor() as cur:
            cur.execute("savepoint api_req")
        return self

    def cursor(self, *a, **k):
        return self._c.cursor(*a, **k)

    def commit(self):
        with self._c.cursor() as cur:
            cur.execute("release savepoint api_req")

    def rollback(self):
        with self._c.cursor() as cur:
            cur.execute("rollback to savepoint api_req")
            cur.execute("release savepoint api_req")


class NoPool:
    def putconn(self, conn, close=False):
        pass


def pure():
    print("-- the sign-in is encrypted, and only this server's key reads it")
    creds = {"refresh_token": "1//zz-refresh", "client_id": "cid", "client_secret": "sec"}
    blob = store.encrypt(creds)
    check("it round-trips", store.decrypt(blob), creds)
    check("the refresh token is not in the stored text", "zz-refresh" in blob, False)
    check("another server's key cannot read it", store.decrypt(blob, secret=b"another-secret"), None)
    check("damage reads as nothing, not a crash", store.decrypt("not-a-token"), None)
    print("\n-- sealed on the laptop for the server: only the server's secret opens it")
    server_secret, laptop_secret = b"the-server-secret", b"the-laptop-secret"
    key = store.server_public_key(server_secret)
    check("the server's public key: the same every time from the same secret",
          (key == store.server_public_key(server_secret), key == store.server_public_key(laptop_secret)), (True, False))
    sealed = store.seal(creds, key)
    check("sealed with it, the refresh token is not in the stored text", ("zz-refresh" in sealed, sealed.startswith(store.SEALED)),
          (False, True))
    check("the server opens it", store.decrypt(sealed, secret=server_secret), creds)
    check("the laptop cannot, though it sealed it", store.decrypt(sealed, secret=laptop_secret), None)
    check("sealing twice gives two different texts (a new one-off key each time)", store.seal(creds, key) != sealed, True)
    tampered = sealed[:-6] + ("A" if sealed[-6] != "A" else "B") + sealed[-5:]
    check("a changed character: refused, not misread", store.decrypt(tampered, secret=server_secret), None)

    print("\n-- a draft as each person would send it (tools/draft_render.py)")
    cfg = {"send_from": "approver",
           "sender": {"name": "Vedansh Gupta", "title": "Outreach Consultant", "postal_address": "702 Fortune Terraces, Mumbai 400053"},
           "footer": {"text": "Warm regards,\n{{sender_name}}\n{{sender_title}}\n\n{{postal_address}}\nReply no thanks."},
           "voices": {"guidance": "text",
                      "kartikeya@zz.example": [["I'm writing on behalf of Kartikeya, who leads BD at",
                                                "I am Kartikeya, and I lead BD at"]]}}
    canon = ("Hello Kay,\n\nI'm writing on behalf of Kartikeya, who leads BD at TVF.\n\n"
             + dr.footer_for(cfg))
    suhas = {"email": "suhas@zz.example", "name": "Suhas C", "title": "Business Development"}
    kart = {"email": "Kartikeya@zz.example", "name": "Kartikeya", "title": "Business Development and IP Strategy"}
    mine = dr.personalize(canon, cfg, suhas)
    check("Suhas sees his own sign-off", mine.endswith("Warm regards,\nSuhas C\nBusiness Development\n\n"
                                                       "702 Fortune Terraces, Mumbai 400053\nReply no thanks."), True)
    check("  and the opener as written (on Kartikeya's behalf)", "on behalf of Kartikeya" in mine, True)
    check("  the reverse gives back exactly the stored draft", dr.canonicalize(mine, cfg, suhas), canon)
    his = dr.personalize(canon, cfg, kart)
    check("Kartikeya sees his own first-person opener", ("I am Kartikeya, and I lead BD at TVF" in his,
                                                         "on behalf of" in his), (True, False))
    check("  signed by him", "\nKartikeya\nBusiness Development and IP Strategy\n" in his, True)
    check("  and the reverse gives back the stored draft", dr.canonicalize(his, cfg, kart), canon)
    check("no name or title yet: shown as stored", dr.personalize(canon, cfg, {"email": "x@zz.example", "name": "X"}), canon)
    pool = dict(cfg, send_from="pool")
    check("a project that sends from its own mailbox: shown as stored", dr.personalize(canon, pool, suhas), canon)
    edited = canon.replace(dr.footer_for(cfg), "Cheers,\nsomeone")
    check("a footer somebody rewrote by hand is left alone", dr.personalize(edited, cfg, suhas), edited)


def api():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    kicks = []
    main._scheduler.kick_outreach = lambda seg, trigger="manual": kicks.append((seg, trigger))
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=False)

    def call(method, url, cookies=None, **kw):
        client.cookies.clear()
        return client.request(method, url, cookies=cookies, **kw)

    cur = conn.cursor()
    try:
        tag = uuid.uuid4().hex[:6]
        slug = "zz-acct-" + tag
        cur.execute("select config from segments where slug = 'us-production-houses'")
        cfg = cur.fetchone()[0]
        cfg.pop("sourcing", None)                  # legacy test leads; the Apollo-only gates: test_apollo_constraints
        out = cfg["outreach"]
        out.pop("sending_paused", None)
        kart_email = "zz-kart-%s@example.com" % tag
        out["send_from"] = "approver"
        # Kartikeya's own lines, from the repo's config (the owner's wording), given to a test login
        repo = json.loads((ROOT / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))
        # since 2026-10-14 every approver speaks in their own name (outreach.signed_intro), not through voices
        out["signed_intro"] = repo["outreach"]["signed_intro"]
        # and its sending window (owner, 2026-10-12): each approval at its own second, 10:00-10:30 its recipient's clock
        out["send_window"] = repo["outreach"]["send_window"]
        cur.execute("insert into segments (slug, name, entity_type, config) values (%s, 'ZZ accounts', 'company', %s)"
                    " returning id", (slug, json.dumps(cfg)))
        seg_id = cur.fetchone()[0]

        def person(email, password, must=False, name=None, title=None):
            h = bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, must_change_password, name, title)"
                        " values (%s, %s, 'member', %s, %s, %s)", (email, h, must, name, title))
            return {auth.COOKIE: auth.make_cookie(email, h), "tvf_segment": slug}

        new_email, start_pw = "zz-new-%s@example.com" % tag, "tvf-start-" + tag
        newbie = person(new_email, start_pw, must=True)
        a_email = "zz-a-%s@example.com" % tag
        a = person(a_email, "zz-" + uuid.uuid4().hex, name="Asha Rao", title="Business Development")
        k = person(kart_email, "zz-" + uuid.uuid4().hex, name="Kartikeya", title="Business Development and IP Strategy")
        b_email = "zz-b-%s@example.com" % tag
        b = person(b_email, "zz-" + uuid.uuid4().hex)                  # no name or title yet

        # ------------------------------------------------------------ passwords
        print("\n-- a starting password opens nothing but the screen that replaces it")
        st = call("GET", "/api/auth/state", cookies=newbie).json()
        check("signed in, told to choose a password", (st["authed"], st["must_change_password"]), (True, True))
        check("  every other call is refused (403), the leads included", [call("GET", u, cookies=newbie).status_code
              for u in ("/api/stats", "/api/leads", "/api/outreach", "/api/me/mailboxes")], [403, 403, 403, 403])
        check("  and so is approving an email", call("POST", "/api/outreach/%s/decision" % uuid.uuid4(), cookies=newbie,
                                                      json={"action": "approve"}).status_code, 403)
        pw = lambda cur_pw, new: call("POST", "/api/auth/password", cookies=newbie, json={"current": cur_pw, "new": new})
        check("the wrong starting password: 400", pw("nope", "a-good-long-password").status_code, 400)
        check("a new one under 10 characters: 400", pw(start_pw, "short").status_code, 400)
        check("the starting one again: 400", pw(start_pw, start_pw).status_code, 400)
        r = pw(start_pw, "zz-my-own-password")
        fresh = {auth.COOKIE: r.cookies.get(auth.COOKIE), "tvf_segment": slug}
        check("its own password: 200, and this session carries on", (r.status_code, bool(fresh[auth.COOKIE])), (200, True))
        check("  the page opens now", call("GET", "/api/stats", cookies=fresh).status_code, 200)
        check("  the old session is over (it was the old password's)", call("GET", "/api/stats", cookies=newbie).status_code, 401)
        check("  and the state says so", call("GET", "/api/auth/state", cookies=fresh).json()["must_change_password"], False)
        check("changing it again later: the current one is needed", call("POST", "/api/auth/password", cookies=fresh,
              json={"current": start_pw, "new": "zz-another-password"}).status_code, 400)

        print("\n-- name and title: the sign-off on your emails")
        prof = lambda body: call("POST", "/api/auth/profile", cookies=fresh, json=body)
        check("no name: 400", prof({"name": " ", "title": "BD"}).status_code, 400)
        check("no title: 400", prof({"name": "Neha", "title": ""}).status_code, 400)
        check("a placeholder is not a name: 400", prof({"name": "{{sender_name}}", "title": "BD"}).status_code, 400)
        r = prof({"name": "  Neha   Shah ", "title": "Partnerships "})
        check("saved, spaces tidied", r.json(), {"ok": True, "name": "Neha Shah", "title": "Partnerships"})
        st = call("GET", "/api/auth/state", cookies=fresh).json()
        check("  the state carries them", (st["name"], st["title"]), ("Neha Shah", "Partnerships"))

        # ------------------------------------------------------------ drafts
        print("\n-- each person sees a draft as they would send it; approving stores theirs")

        def company(status="shortlisted"):
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score) values"
                        " (%s, %s, %s, 'test', %s, 40) returning id",
                        (seg_id, "ZZ Acct " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example", status))
            eid = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s, 'valid')"
                        " returning id", (eid, "kay.%s@zz-acct.example" % uuid.uuid4().hex[:6]))
            return str(eid), cur.fetchone()[0]
        canon_footer = dr.footer_for(out)
        # the project's own "I'm <first name>, who handles <title> at The Viral Fever (TVF)" (owner, 2026-10-14)
        opener = dr.signed_intro(out, out["sender"]["name"], out["sender"]["title"]) + "."
        body = "Hello Kay,\n\nI trust you are well.\n\n" + opener + "\n\nA call?\n\n" + canon_footer
        e1, c1 = company()
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status) values"
                    " (%s, %s, 't', 'From TVF in India', %s, 'drafted') returning id", (e1, c1, body))
        d1 = str(cur.fetchone()[0])

        def shown(cookies):
            rows = call("GET", "/api/outreach?folder=drafts", cookies=cookies).json()["rows"]
            return next(r["body"] for r in rows if r["id"] == d1)
        a_view = shown(a)
        check("Asha's view: her name and title sign it", a_view.endswith(dr.footer_for(out, "Asha Rao", "Business Development")), True)
        k_view = shown(k)
        check("Kartikeya's view: his first-person line, his sign-off",
              ("I'm Kartikeya, who handles Business Development and IP Strategy at The Viral Fever (TVF)." in k_view,
               opener in k_view,
               k_view.endswith(dr.footer_for(out, "Kartikeya", "Business Development and IP Strategy"))), (True, False, True))
        cur.execute("select body from outreach where id = %s", (d1,))
        check("  the stored draft is untouched by looking", cur.fetchone()[0], body)
        edited = a_view.replace("A call?", "A short call next week?")
        r = call("PATCH", "/api/outreach/%s" % d1, cookies=a, json={"body": edited})
        cur.execute("select body from outreach where id = %s", (d1,))
        stored = cur.fetchone()[0]
        check("Asha edits it: stored in the project's own form, her words kept",
              (r.status_code, stored.endswith(canon_footer), "A short call next week?" in stored), (200, True, True))
        check("  so Kartikeya sees her edit, signed by him", ("A short call next week?" in shown(k),
              shown(k).endswith(dr.footer_for(out, "Kartikeya", "Business Development and IP Strategy"))), (True, True))
        r = call("POST", "/api/outreach/%s/decision" % d1, cookies=b, json={"action": "approve"})
        check("someone with no name or title cannot approve (409, and why)",
              (r.status_code, "name and title" in r.json().get("detail", "")), (409, True))
        kicks.clear()
        r = call("POST", "/api/outreach/%s/decision" % d1, cookies=k, json={"action": "approve"})
        cur.execute("select status, approved_by, body from outreach where id = %s", (d1,))
        st_, by, final = cur.fetchone()
        check("Kartikeya approves: the stored email is his version, approved by him",
              (r.status_code, st_, by, final == dr.personalize(stored, out, {"email": kart_email, "name": "Kartikeya",
                                                                                "title": "Business Development and IP Strategy"})),
              (200, "approved", kart_email, True))
        check("  no Gmail connected: it cannot go out yet, and the answer says so",
              (r.json()["can_send"], r.json()["sends_from"]), (False, []))
        sched = r.json().get("schedule") or {}
        check("  its own moment in its recipient's window is drawn even so, and said in the page's words",
              (bool(sched.get("send_label")), sched.get("send_tz") is not None), (True, True))

        # ------------------------------------------------------------ sending addresses
        # the owner can link an address for someone on the laptop (tools/users.py gmail); since 2026-10-14 each
        # person can also connect their own in the app (below)
        print("\n-- the owner links a person's sending address (tools/users.py gmail)")
        r = call("GET", "/api/mailboxes/server-key")
        check("the server's public key is public, and the one its secret gives", (r.status_code, r.json().get("x25519")),
              (200, store.server_public_key()))

        import users
        import googleapiclient.discovery as gdisc
        a_gmail = "asha.%s@zz-mail.example" % tag

        class FakeCreds:
            def __init__(self, refresh="1//zz-asha"):
                self.refresh = refresh

            def to_json(self):
                return json.dumps({"token": "ya29.zz", "refresh_token": self.refresh, "client_id": "desk",
                                   "client_secret": "desk-secret", "token_uri": store.TOKEN_URI, "scopes": [store.GMAIL_SCOPE]})

        class FakeGmailProfile:
            def __init__(self, address):
                self.address = address

            def users(self):
                return self

            def getProfile(self, userId):
                return self

            def execute(self):
                return {"emailAddress": self.address}

        class TxDb:                       # dbconn.Db on this test's one transaction
            def __init__(self, *a, **k):
                pass

            def run(self, fn, on_reconnect=None):
                with conn.cursor() as c:
                    c.execute("savepoint users_step")
                    try:
                        out_ = fn(c)
                    except Exception:
                        c.execute("rollback to savepoint users_step")
                        raise
                    c.execute("release savepoint users_step")
                    return out_

            def close(self):
                pass

        signed_in_as = {"address": a_gmail.upper(), "creds": FakeCreds()}
        real = (users.Db, users._server_key, users._google_signin, gdisc.build, sys.argv)
        users.Db = TxDb
        users._server_key = lambda: store.server_public_key()
        users._google_signin = lambda: signed_in_as["creds"]
        gdisc.build = lambda *a_, **k_: FakeGmailProfile(signed_in_as["address"])

        def run_users(*argv):
            sys.argv = ["users.py"] + list(argv)
            try:
                users.main()
                return 0
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 1
        try:
            check("linking to a login that does not exist is refused", run_users("gmail", "nobody-%s@example.com" % tag), 1)
            check("the owner links Asha's sending address", run_users("gmail", a_email), 0)
            cur.execute("select user_email, address, token_enc, daily_cap from user_mailboxes where lower(address) = %s", (a_gmail,))
            row = cur.fetchone()
            check("  kept for Asha, address in lower case, 50 a day (the owner's limit, 2026-10-23)", (row[0], row[1], row[3]),
                  (a_email, a_gmail, 50))
            check("  sealed for the server: not readable as stored, readable with the server's secret",
                  ("1//zz-asha" in row[2], row[2].startswith(store.SEALED), (store.decrypt(row[2]) or {}).get("refresh_token")),
                  (False, True, "1//zz-asha"))
            check("  and not with any other secret", store.decrypt(row[2], secret=b"not-the-server"), None)
            check("the same address for Kartikeya: refused, it is Asha's", run_users("gmail", kart_email), 1)
            signed_in_as["creds"] = FakeCreds("1//zz-asha-2")
            check("running it again for Asha refreshes her sign-in, a new limit if given",
                  run_users("gmail", a_email, "--cap", "20"), 0)
            cur.execute("select count(*), max(daily_cap) from user_mailboxes where lower(address) = %s", (a_gmail,))
            got = list(cur.fetchone())
            cur.execute("select token_enc from user_mailboxes where lower(address) = %s", (a_gmail,))
            check("  one row, cap 20, the new sign-in", (got, (store.decrypt(cur.fetchone()[0]) or {}).get("refresh_token")),
                  ([1, 20], "1//zz-asha-2"))
            check("  a cap that makes no sense is refused", run_users("gmail", a_email, "--cap", "0"), 1)
            signed_in_as["creds"] = FakeCreds(refresh=None)
            check("Google gives no lasting sign-in: nothing kept", run_users("gmail", a_email), 1)
            signed_in_as["creds"] = FakeCreds()
            check("--move gives it to Kartikeya", run_users("gmail", kart_email, "--move"), 0)
            cur.execute("select user_email from user_mailboxes where lower(address) = %s", (a_gmail,))
            check("  now his", cur.fetchone()[0], kart_email)
            check("and back to Asha, at 50 again", run_users("gmail", a_email, "--move", "--cap", "50"), 0)
        finally:
            users.Db, users._server_key, users._google_signin, gdisc.build, sys.argv = real

        mine = call("GET", "/api/me/mailboxes", cookies=a).json()
        check("Asha's sending address, read-only: the address and today's use, no secrets", (
            [m["address"] for m in mine["mailboxes"]], mine["mailboxes"][0]["remaining"],
            "token_enc" in json.dumps(mine), "zz-asha" in json.dumps(mine)), ([a_gmail], 50, False, False))
        strip = call("GET", "/api/mailboxes", cookies=a).json()
        me_row = next(x for x in strip["accounts"] if x["me"])
        check("Sending today: everyone listed, hers first with her address and 35",
              (strip["mode"], strip["accounts"][0]["me"], [m["address"] for m in me_row["mailboxes"]],
               me_row["mailboxes"][0]["daily_cap"], strip["can_send"]), ("approver", True, [a_gmail], 50, True))
        kart_row = next(x for x in strip["accounts"] if x["email"] == kart_email)
        check("  Kartikeya: no sending address, one approval waiting", (kart_row["mailboxes"], kart_row["approved_waiting"]), ([], 1))
        check("  and the day it goes out (India's clock), for the counter: one, on its day",
              ([d["count"] for d in kart_row["scheduled"]], all(d["label"] and d["day"] for d in kart_row["scheduled"])),
              ([1], True))
        check("  and nothing secret in it", "token" in json.dumps(strip).replace("tokens", ""), False)

        # ------------------------------------------------------------ connecting a Gmail in the app
        # owner, 2026-10-14: "a feature which allows users to link a gmail account to send emails in their own
        # without my intervention" -- Google's own sign-in, from the account menu (app/mailbox_connect.py)
        print("\n-- each person connects their own Gmail in the app (app/mailbox_connect.py, Google a stand-in)")
        import urllib.parse as up
        import mailbox_connect as mc
        web_vars = ("GOOGLE_OAUTH_WEB_CLIENT_ID", "GOOGLE_OAUTH_WEB_CLIENT_SECRET")
        saved_env = {name: os.environ.pop(name, None) for name in web_vars}
        real_mc = (mc._post_form, mc._get_json, mc._env)
        google = {"token": (200, {}), "profile": (200, {}), "posts": []}

        def fake_post(url, fields, timeout=20):
            google["posts"].append((url, dict(fields)))
            return google["token"] if url == mc.TOKEN_URL else (200, {})

        def back(r):
            qq = up.parse_qs(up.urlparse(r.headers.get("location", "")).query)
            return (qq.get("gmail") or [None])[0], (qq.get("msg") or [""])[0]

        def revoked():
            return [f.get("token") for u, f in google["posts"] if u == mc.REVOKE_URL]
        try:
            mc._env = lambda name: os.environ.get(name)          # never the laptop's own .env
            off = call("GET", "/api/me/mailboxes", cookies=a).json()
            r = call("GET", "/api/mailboxes/connect", cookies=a)
            check("no Web application client on the server: Connect says so, and goes nowhere else",
                  (off["web_connect"], r.status_code, back(r)[0], r.headers.get("location", "").startswith("/?")),
                  (False, 302, "error", True))
            check("  signed out: refused", call("GET", "/api/mailboxes/connect").status_code, 401)
            os.environ["GOOGLE_OAUTH_WEB_CLIENT_ID"] = "web-zz.apps.googleusercontent.com"
            os.environ["GOOGLE_OAUTH_WEB_CLIENT_SECRET"] = "web-zz-secret"
            # Gmail's profile, and its "Send mail as" list (sql/36): the LCX address lives in the TVF account
            google["sendas"] = (200, {"sendAs": []})
            mc._post_form, mc._get_json = fake_post, (lambda url, token, timeout=20: google["sendas"]
                                                       if url == mc.SEND_AS_URL else google["profile"])
            check("with one: switched on", call("GET", "/api/me/mailboxes", cookies=a).json()["web_connect"], True)
            r = call("GET", "/api/mailboxes/connect", cookies=a)
            loc = up.urlparse(r.headers.get("location", ""))
            q = {name: v[0] for name, v in up.parse_qs(loc.query).items()}
            check("Connect: Google's own sign-in, for Gmail, lasting, back to this server's callback",
                  (r.status_code, loc.netloc, q.get("client_id"), q.get("scope"), q.get("access_type"),
                   q.get("redirect_uri", "").endswith("/api/mailboxes/callback"), "web-zz-secret" in r.headers["location"]),
                  (302, "accounts.google.com", "web-zz.apps.googleusercontent.com", store.GMAIL_SCOPE, "offline", True, False))
            state = q.get("state", "")
            check("  the state is Asha's alone", (mc.verify_state(state, a_email), mc.verify_state(state, kart_email)),
                  (True, False))
            check("  and expires in ten minutes", mc.verify_state(state, a_email, now=__import__("time").time() + 601), False)
            a2 = "asha.two.%s@zz-mail.example" % tag
            good = (200, {"access_token": "ya29.zz", "refresh_token": "1//zz-web-asha",
                          "scope": "openid " + store.GMAIL_SCOPE})
            google["token"], google["profile"] = good, (200, {"emailAddress": a2.upper()})
            cb = "/api/mailboxes/callback?code=c&state="
            check("Kartikeya cannot finish Asha's sign-in", back(call("GET", cb + up.quote(state), cookies=k))[0], "error")
            check("  nor can a made-up state", back(call("GET", cb + "123.x.y", cookies=a))[0], "error")
            check("  Google's own refusal: nothing changed",
                  back(call("GET", "/api/mailboxes/callback?error=access_denied&state=" + up.quote(state), cookies=a))[0],
                  "error")
            google["token"], google["posts"] = (200, {"access_token": "ya29.zz", "refresh_token": "1//zz-noscope",
                                                      "scope": "openid email"}), []
            check("  Gmail left unticked on Google's screen: not kept, Google's permission withdrawn",
                  (back(call("GET", cb + up.quote(state), cookies=a))[0], revoked()), ("error", ["1//zz-noscope"]))
            google["token"] = good
            lcx = "asha.%s@zz-lcx.example" % tag
            google["sendas"] = (200, {"sendAs": [{"sendAsEmail": a2, "isPrimary": True},
                                                 {"sendAsEmail": lcx, "displayName": "Asha at LCX",
                                                  "verificationStatus": "accepted"}]})
            r = call("GET", cb + up.quote(state), cookies=a)
            cur.execute("select user_email, daily_cap, token_enc, send_as from user_mailboxes where lower(address) = %s",
                        (a2,))
            row = cur.fetchone()
            creds = store.decrypt(row[2]) if row else {}
            check("Asha connects a second Gmail herself: linked to her, at 50, the address as Google says it",
                  (back(r)[0], back(r)[1].startswith(a2), row[:2] if row else None), ("connected", True, (a_email, 50)))
            check("  its LCX alias read at once (an LCX address cannot be signed in to: it lives in this account)",
                  (row[3], ("also sends as " + lcx) in back(r)[1]),
                  ([{"address": lcx, "name": "Asha at LCX"}], True))
            check("  stored encrypted, for the web client; nothing of it in the redirect",
                  (creds.get("refresh_token"), creds.get("client_id"), "zz-web-asha" in row[2],
                   "zz-web-asha" in r.headers["location"]),
                  ("1//zz-web-asha", "web-zz.apps.googleusercontent.com", False, False))
            mine = call("GET", "/api/me/mailboxes", cookies=a).json()["mailboxes"]
            check("  Your Gmail lists both, with no secrets",
                  (sorted(m["address"] for m in mine), "zz-web-asha" in json.dumps(mine), "token" in json.dumps(mine)),
                  (sorted([a_gmail, a2]), False, False))
            check("  and the alias it also sends as", [m["send_as"] for m in mine if m["address"] == a2],
                  [[{"address": lcx, "name": "Asha at LCX"}]])
            check("Google sign-in suggests the real login, without restricting account choice", q.get("login_hint"), a_email)
            refresh = "/api/mailboxes/%s/refresh-aliases" % next(m["id"] for m in mine if m["address"] == a2)
            sender = refresh.replace("refresh-aliases", "sender")
            pending_alias = "pending.%s@zz-lcx.example" % tag
            accepted = google["sendas"]
            google["sendas"] = (200, {"sendAs": accepted[1]["sendAs"] + [
                {"sendAsEmail": pending_alias, "verificationStatus": "pending"}]})
            check("refresh reads the parent's verified aliases, without a separate alias login",
                  call("POST", refresh, cookies=a).json().get("send_as"), [{"address": lcx, "name": "Asha at LCX"}])
            before_posts = len(google["posts"])
            check("another person cannot refresh or choose this mailbox's sender",
                  [call("POST", url, cookies=k, json={"address": lcx}).status_code for url in (refresh, sender)], [404, 404])
            check("ownership is checked before contacting Google", len(google["posts"]), before_posts)
            check("signed out cannot change the sender", call("POST", sender, json={"address": lcx}).status_code, 401)
            check("a verified alias can be chosen for any project, with no domain rule",
                  call("POST", sender, cookies=a, json={"address": lcx.upper()}).json().get("sends_as"), lcx)
            check("the parent stays the linked account and keeps its cap",
                  [(m["address"], m["from_address"], m["daily_cap"]) for m in call("GET", "/api/me/mailboxes", cookies=a).json()["mailboxes"] if m["address"] == a2],
                  [(a2, lcx, 50)])
            for invalid in (pending_alias, "someone@other.example"):
                check("a pending or arbitrary From is rejected: " + invalid,
                      call("POST", sender, cookies=a, json={"address": invalid}).status_code, 400)
            google["sendas"] = (503, {})
            check("a Google outage cannot overwrite the selected sender", call("POST", refresh, cookies=a).status_code, 502)
            cur.execute("select from_address,send_as from user_mailboxes where lower(address)=%s", (a2,))
            check("the selection and verified cache survive a failed refresh", cur.fetchone(),
                  (lcx, [{"address": lcx, "name": "Asha at LCX"}]))
            google["sendas"] = (200, {"sendAs": []})
            call("POST", refresh, cookies=a)
            vanished = next(m for m in call("GET", "/api/mailboxes", cookies=a).json()["accounts"] if m["me"])
            check("a removed selected alias is unavailable, with no silent parent fallback",
                  [(m["sends_as"], m["usable"], bool(m.get("sender_issue"))) for m in vanished["mailboxes"] if m["address"] == a2],
                  [(None, False, True)])
            google["sendas"] = accepted
            check("the person can explicitly return to the parent sender",
                  call("POST", sender, cookies=a, json={"address": a2}).json().get("sends_as"), a2)
            # a project that writes as LCX (outreach.send_as_domain, LCX Services): Sending today and the approve
            # dialog name the From each account gives it
            cur.execute("update segments set config = jsonb_set(config, '{outreach,send_as_domain}', '\"zz-lcx.example\"')"
                        " where id = %s", (seg_id,))
            def froms():
                me_row = next(x for x in call("GET", "/api/mailboxes", cookies=a).json()["accounts"] if x["me"])
                return {m["address"]: (m["sends_as"], m["usable"], m.get("no_alias")) for m in me_row["mailboxes"]}
            got = froms()
            check("a project that writes as LCX: her new Gmail goes as its LCX alias; the one whose aliases are not "
                  "read yet goes as itself until the next send reads them",
                  (got.get(a2), got.get(a_gmail)), ((lcx, True, None), (a_gmail, True, None)))
            cur.execute("update user_mailboxes set send_as = '[]'::jsonb where lower(address) = %s", (a_gmail,))
            check("  an account read and found with no LCX alias cannot send for it, and says why",
                  froms().get(a_gmail), (None, False, "zz-lcx.example"))
            cur.execute("update segments set config = config #- '{outreach,send_as_domain}' where id = %s", (seg_id,))
            cur.execute("update user_mailboxes set send_as = null where lower(address) = %s", (a_gmail,))
            google["posts"] = []
            r = call("GET", cb + up.quote(mc.sign_state(kart_email)), cookies=k)
            cur.execute("select user_email from user_mailboxes where lower(address) = %s", (a2,))
            check("Kartikeya signs in to Asha's address: refused, it stays hers, his sign-in withdrawn",
                  (back(r)[0], cur.fetchone()[0], revoked()), ("error", a_email, ["1//zz-web-asha"]))
            a2_id = next(m["id"] for m in mine if m["address"] == a2)
            check("  nor can he disconnect it", call("DELETE", "/api/mailboxes/" + a2_id, cookies=k).status_code, 404)
            google["posts"] = []
            r = call("DELETE", "/api/mailboxes/" + a2_id, cookies=a)
            cur.execute("select count(*) from user_mailboxes where lower(address) = %s", (a2,))
            check("Asha disconnects it: gone, and Google's permission withdrawn",
                  (r.status_code, cur.fetchone()[0], revoked()), (200, 0, ["1//zz-web-asha"]))
            check("  a made-up id: 404", call("DELETE", "/api/mailboxes/not-an-id", cookies=a).status_code, 404)
            cur.execute("select count(*) from user_mailboxes where lower(address) = %s", (a_gmail,))
            check("  the address the owner linked for her is untouched", cur.fetchone()[0], 1)
        finally:
            mc._post_form, mc._get_json, mc._env = real_mc
            for name, v in saved_env.items():
                os.environ.pop(name, None)
                if v is not None:
                    os.environ[name] = v

        # ------------------------------------------------------------ reached out by
        print("\n-- who reached out")
        e2, c2 = company("contacted")
        cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status, approved_by,"
                    " approved_at, sender_address, sender_mailbox, sent_at, gmail_message_id) values"
                    " (%s, %s, 't', 'Hi', 'Body', 'sent', %s, now(), %s, %s, now(), %s)",
                    (e2, c2, a_email, a_gmail, a_gmail, "zz-" + uuid.uuid4().hex))
        rows = call("GET", "/api/leads?status=contacted", cookies=a).json()["rows"]
        got = next((x for x in rows if x["id"] == e2), {})
        check("the leads list: reached out by Asha", (got.get("reached_by"), got.get("reached_by_name")), (a_email, "Asha Rao"))
        d = call("GET", "/api/leads/%s" % e2, cookies=a).json()["outreach"]
        check("the lead dialog: who, from which address, when", (d["approved_by_name"], d["sender_address"], bool(d["sent_at"])),
              ("Asha Rao", a_gmail, True))
        sent = call("GET", "/api/outreach?folder=sent", cookies=a).json()["rows"]
        check("the Sent folder names her", [x.get("approved_by_name") for x in sent if x["entity_id"] == e2], ["Asha Rao"])
        by = call("GET", "/api/kpis", cookies=a).json().get("by_account") or []
        mine_row = next((x for x in by if x["account"] == a_email), {})
        check("Reports, by person: Asha 1 sent today, Kartikeya 1 approved",
              ((mine_row.get("name"), mine_row.get("sent"), mine_row.get("sent_today")),
               [(x["name"], x["approved"], x["sent"]) for x in by if x["account"] == kart_email]),
              (("Asha Rao", 1, 1), [("Kartikeya", 1, 0)]))

        # Approval volume is independent of the mailbox's daily sending capacity.
        # A legacy batch limit must not reject a larger human-reviewed selection.
        import outreach_policy as pol
        cfg["outreach"]["batch_approval"] = {"enabled": True, "sample_min": 3, "sample_fraction": 0.1, "max_batch": 50}
        cur.execute("update segments set config=%s::jsonb where id=%s", (json.dumps(cfg), seg_id))
        main._SEG_CACHE.update(at=0.0, rows=[])
        bulk_ids = []
        for _ in range(125):
            be, bc = company()
            cur.execute("update entities set metadata='{\"country\":\"US\",\"city\":\"New York\"}'::jsonb where id=%s", (be,))
            cur.execute("insert into outreach (entity_id,contact_id,template_key,subject,body,status)"
                        " values (%s,%s,'t','Fixture bulk approval',%s,'drafted') returning id", (be, bc, body))
            bulk_ids.append(str(cur.fetchone()[0]))
        sampled = call("POST", "/api/outreach/batch/sample", cookies=a, json={"ids": bulk_ids})
        smp = sampled.json()
        check("125 drafts can be sampled despite the old 50-item batch setting",
              (sampled.status_code, len(smp.get("approvable", []))), (200, 125))
        approved = call("POST", "/api/outreach/batch/approve", cookies=a,
                        json={"ids": smp.get("approvable", []), "sample": smp.get("sample", []), "token": smp.get("token", "")})
        check("all 125 can be approved at once, independently of today's remaining capacity",
              (approved.status_code, approved.json().get("approved")), (200, 125))
        cur.execute("select send_after::date,count(*) from outreach where id=any(%s::uuid[])"
                    " and send_after is not null group by 1", (bulk_ids,))
        per_day = cur.fetchall()
        check("the queue spreads across later days and never schedules more than 50 per day",
              (sum(r[1] for r in per_day), max([r[1] for r in per_day] or [0]) <= 50, len(per_day) >= 3), (125, True, True))
        cur.execute("select daily_cap from user_mailboxes where lower(address)=%s", (a_gmail,))
        check("unlimited approvals do not raise the sending cap", cur.fetchone()[0], 50)
        full_e, full_c = company()
        cur.execute("insert into outreach (entity_id,contact_id,template_key,subject,body,status)"
                    " values (%s,%s,'t','Fixture full schedule',%s,'drafted') returning id", (full_e, full_c, body))
        full_id = str(cur.fetchone()[0])
        old_place = pol._Placer.place
        def full_schedule(*args, **kwargs):
            raise pol.NoSendSlot("no free sending minute in the next 60 days")
        try:
            pol._Placer.place = full_schedule
            queued = call("POST", "/api/outreach/%s/decision" % full_id, cookies=a, json={"action": "approve"})
        finally:
            pol._Placer.place = old_place
        cur.execute("select status,send_after,send_wait_why from outreach where id=%s", (full_id,))
        waiting_row = cur.fetchone()
        check("a full planning horizon keeps a single email approved and waiting",
              (queued.status_code, waiting_row[0], waiting_row[1], bool(waiting_row[2])), (200, "approved", None, True))
    finally:
        conn.rollback()
        conn.close()


def main_():
    pure()
    api()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back; Google was a stand-in)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
