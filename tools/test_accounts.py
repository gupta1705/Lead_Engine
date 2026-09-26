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
  * the owner links each person's sending address (users.py gmail): sealed with the server's public key
    so only the server reads it, one address one person (--move to change), refresh and --cap; people
    have nothing to connect in the app
  * the Sending today list, "reached out by" on leads, the lead dialog and the per-person report

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
        out = cfg["outreach"]
        out.pop("sending_paused", None)
        kart_email = "zz-kart-%s@example.com" % tag
        out["send_from"] = "approver"
        # Kartikeya's own lines, from the repo's config (the owner's wording), given to a test login
        repo = json.loads((ROOT / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))
        out["voices"] = {kart_email: repo["outreach"]["voices"]["kartikeyap@theviralfever.com"]}
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
        opener = "I'm writing on behalf of Kartikeya, who leads Business Development and IP Strategy at The Viral Fever (TVF)."
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
              ("I am Kartikeya, and I lead Business Development and IP Strategy at" in k_view, "on behalf of" in k_view,
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

        # ------------------------------------------------------------ sending addresses
        # owner, 2026-09-26: "no need for them to connect their gmails. I will manually connect the email id
        # they will use to send" -- the owner links each address on the laptop (tools/users.py gmail)
        print("\n-- the owner links each person's sending address (tools/users.py gmail)")
        r = call("GET", "/api/mailboxes/server-key")
        check("the server's public key is public, and the one its secret gives", (r.status_code, r.json().get("x25519")),
              (200, store.server_public_key()))
        check("people have nothing to connect: no connect, callback or disconnect in the app",
              [call(m, u, cookies=a).status_code in (404, 405) for m, u in
               (("GET", "/api/mailboxes/connect"), ("GET", "/api/mailboxes/callback?code=x"), ("DELETE", "/api/mailboxes/x"))],
              [True, True, True])

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
            check("  kept for Asha, address in lower case, 35 a day", (row[0], row[1], row[3]), (a_email, a_gmail, 35))
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
            check("and back to Asha, at 35 again", run_users("gmail", a_email, "--move", "--cap", "35"), 0)
        finally:
            users.Db, users._server_key, users._google_signin, gdisc.build, sys.argv = real

        mine = call("GET", "/api/me/mailboxes", cookies=a).json()
        check("Asha's sending address, read-only: the address and today's use, no secrets", (
            [m["address"] for m in mine["mailboxes"]], mine["mailboxes"][0]["remaining"],
            "token_enc" in json.dumps(mine), "zz-asha" in json.dumps(mine)), ([a_gmail], 35, False, False))
        strip = call("GET", "/api/mailboxes", cookies=a).json()
        me_row = next(x for x in strip["accounts"] if x["me"])
        check("Sending today: everyone listed, hers first with her address and 35",
              (strip["mode"], strip["accounts"][0]["me"], [m["address"] for m in me_row["mailboxes"]],
               me_row["mailboxes"][0]["daily_cap"], strip["can_send"]), ("approver", True, [a_gmail], 35, True))
        kart_row = next(x for x in strip["accounts"] if x["email"] == kart_email)
        check("  Kartikeya: no sending address, one approval waiting", (kart_row["mailboxes"], kart_row["approved_waiting"]), ([], 1))
        check("  and nothing secret in it", "token" in json.dumps(strip).replace("tokens", ""), False)

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
