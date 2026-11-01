#!/usr/bin/env python3
"""test_api.py -- every HTTP endpoint, called the way the page calls it, as a regression table.

    python tools/test_api.py

The real app (app/main.py with its auth, ops and universal routers) runs in-process under FastAPI's
TestClient against the real database inside ONE transaction that is rolled back at the end: each
request's commit is a savepoint released, each rollback a rollback to that savepoint, so nothing an
endpoint writes survives. Nothing leaves the machine: the scheduler never starts
(SCHEDULER_ENABLED=0), a kick or a pipeline run is recorded instead of run, and Apollo answers from
a stub, so no credit is spent and no email can go. The export runs tools/export_leads.py for real,
which only reads.

Checked: the auth wall (401 for the API, a redirect for pages and files, tampered, expired and stale
cookies), login and its limit on guesses, JSON-only writes, every read endpoint for every project,
every write the page makes and the error each bad input gets (never a 500), the sending window's
answers (a draft's window, an approval's own moment, a batch's days, an approval that can no longer be
withdrawn), that no secret appears in any response, and how long each call takes. Exit code 1 on any
failure.
"""
import io
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                # the app as the server runs it (uvicorn app.main:app): app/universal.py
sys.path.insert(0, str(ROOT / "tools"))      # imports app.auth
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"                # the real scheduler must never start in a test

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import main  # noqa: E402
import auth  # noqa: E402
import apollo  # noqa: E402

RESULTS, TIMES = [], []
TVF = "us-production-houses"
OID = ["5f%022x" % i for i in range(1, 6)]
PID = ["6a%022x" % i for i in range(1, 6)]


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-72s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:100]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:100])))


class TxConn:
    """The app's pooled connection, replaced by the test's one transaction."""

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


class FakeApollo:
    """tools/apollo.py's one network function, answering with the documented shapes."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, query=None, body=None, timeout=30):
        self.calls.append(path)
        if path == "/users/api_profile":
            return {"first_name": "Test", "last_name": "Key", "email": "key@zz-api.example", "team_id": "t"}
        if path == "/usage_stats/credit_usage_stats":
            return {"credit_usage_stats": {"lead_credit": {"left_over": 2483, "limit": 2500, "consumed": 17}},
                    "current_credit_cycle": {"end_date": "2026-10-20"}}
        if path == "/mixed_people/api_search":
            return {"total_entries": 1, "people": [{"id": PID[0], "first_name": "Elena", "last_name_obfuscated": "Mo***s",
                                                    "title": "Producer", "has_email": True,
                                                    "organization": {"name": "Northwind Pictures"}}]}
        if path == "/mixed_companies/search":
            return {"pagination": {"total_entries": 1, "total_pages": 1}, "accounts": [],
                    "organizations": [{"id": OID[0], "name": "ZZ Arcade Co", "website_url": "http://zz-arcade.example",
                                       "founded_year": 2001}]}
        if path == "/people/bulk_match":
            ids = [d.get("id") for d in (body or {}).get("details", [])]
            return {"matches": [{"id": i, "first_name": "Elena", "last_name": "Moss", "name": "Elena Moss",
                                 "email": "elena@zz-northwind.example", "email_status": "verified", "title": "Producer",
                                 "organization": {"id": OID[1], "name": "ZZ Northwind Pictures",
                                                  "primary_domain": "zz-northwind.example"}} for i in ids],
                    "credits_consumed": len(ids)}
        raise apollo.ApolloError("unexpected Apollo call in the test: %s" % path, status=500)


def secrets():
    """Values that must never appear in a response. Read from the environment and .env; never printed."""
    names = ("SUPABASE_DB_URL", "APOLLO_API_KEY", "SESSION_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET",
             "GROQ_API_KEY", "YOUTUBE_API_KEY", "GMAIL_TOKEN_JSON")
    vals = [os.environ.get(n) for n in names]
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k in names and v:
                vals.append(v.strip().strip('"').strip("'"))
    out = set()
    for v in vals:
        if not v:
            continue
        out.add(v)
        m = re.match(r"postgres(?:ql)?://[^:]+:([^@]+)@", v)
        if m:
            out.add(m.group(1))                          # the database password on its own
    token = ROOT / ".gmail_token.json"
    if token.exists():
        try:
            t = json.loads(token.read_text())
            out.update(x for x in (t.get("refresh_token"), t.get("client_secret"), t.get("token")) if x)
        except ValueError:
            pass
    return [s for s in out if len(s) >= 8]


def main_():
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0.0, rows=[])
    fake = FakeApollo()
    real_call = apollo._call
    apollo._call = fake
    apollo.key_is_set = lambda: True
    kicks, runs = [], []
    main._scheduler.kick_outreach = lambda seg, trigger="manual": kicks.append((seg, trigger))
    main._scheduler.run_pipeline = lambda pipeline, trigger="schedule", segment=None: runs.append(
        (pipeline, trigger, segment))
    secret_values = secrets()
    leaked = []

    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))

    def call(method, url, cookies=None, **kw):
        # only the cookies a check names: the client would otherwise keep what a response set (a login,
        # a project picked) and send it with every later call
        client.cookies.clear()
        t0 = time.monotonic()
        r = client.request(method, url, cookies=cookies, **kw)
        TIMES.append((time.monotonic() - t0, method, url.split("?")[0]))
        body = r.content.decode("utf-8", "ignore") if not url.startswith("/api/export") else ""
        for s in secret_values:
            if s in body or s in str(r.headers):
                leaked.append(url)
        return r

    try:
        cur = conn.cursor()                          # the setup cursor, open for the whole run
        # a user of the test's own, and a throwaway project copied from US Production Houses
        email = "zz-api-%s@example.com" % uuid.uuid4().hex[:6]
        password = "zz-" + uuid.uuid4().hex
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role) values (%s, %s, 'member')",
                    (email, pw_hash))
        slug = "zz-api-" + uuid.uuid4().hex[:6]
        # the project's own-mailbox mode, whatever the live one says: per-person sending (send_from
        # "approver", 2026-09-26) has its own table, tools/test_accounts.py
        # (config - 'sourcing'): legacy test leads; the Apollo-only gates have their own suite, test_apollo_constraints
        cur.execute("insert into segments (slug, name, entity_type, config) select %s, 'ZZ API test', 'company',"
                    " (config - 'sourcing') #- '{outreach,sending_paused}' #- '{outreach,send_from}' from segments"
                    " where slug = %s returning id", (slug, TVF))
        seg_id = cur.fetchone()[0]

        def company(status="ready_for_review", score=50, address=True):
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score) values"
                        " (%s, %s, %s, 'test', %s, %s) returning id",
                        (seg_id, "ZZ API " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example", status, score))
            eid = cur.fetchone()[0]
            cid = None
            if address:
                cur.execute("insert into contacts (entity_id, full_name, email, email_status) values"
                            " (%s, 'Kay Doe', %s, 'valid') returning id",
                            (eid, "kay.%s@zz-api.example" % uuid.uuid4().hex[:6]))
                cid = cur.fetchone()[0]
            return str(eid), cid

        def draft(eid, cid, status="drafted", subject="From TVF in India", body="Hello Kay,\n\nBody\n\nVedansh"):
            cur.execute("insert into outreach (entity_id, contact_id, template_key, subject, body, status)"
                        " values (%s, %s, 't', %s, %s, %s) returning id", (eid, cid, subject, body, status))
            return str(cur.fetchone()[0])

        good = {auth.COOKIE: auth.make_cookie(email, pw_hash)}
        tvf = dict(good, tvf_segment=TVF)
        mine = dict(good, tvf_segment=slug)

        # ------------------------------------------------------------ the wall
        print("-- the auth wall")
        check("the API without a session: 401", (call("GET", "/api/leads").status_code,
                                                 call("GET", "/api/leads").json()), (401, {"detail": "not signed in"}))
        for url in ("/api/stats", "/api/outreach", "/api/mailboxes", "/api/kpis", "/api/schedule", "/api/ops",
                    "/api/universal/status", "/api/universal/searches", "/api/export.xlsx", "/api/outreach/footer"):
            check("  GET %s without a session: 401" % url, call("GET", url).status_code, 401)
        for method, url in (("POST", "/api/leads/x/decision"), ("POST", "/api/outreach/x/decision"),
                            ("PATCH", "/api/outreach/x"), ("POST", "/api/outreach/footer"),
                            ("POST", "/api/outreach/batch/approve"), ("POST", "/api/schedule/run/weekly_refresh"),
                            ("POST", "/api/universal/save"), ("DELETE", "/api/universal/searches/x"),
                            ("POST", "/api/ops/send_outreach/stop"), ("POST", "/api/segment/select")):
            check("  %s %s without a session: 401" % (method, url), call(method, url, json={}).status_code, 401)
        r = call("GET", "/")
        check("the page without a session: sent to /login", (r.status_code, r.headers.get("location")), (302, "/login"))
        check("the page's script without a session: sent to /login", call("GET", "/app.js").status_code, 302)
        # the wall must judge the path the router serves: Starlette rebuilds request.url from the Host
        # header, so "Host: x/api/health#" made /api/leads look like the public /api/health (2026-09-21)
        for host in ("x/api/health#", "x/api/health?", "x/login#"):
            r = call("GET", "/api/stats", headers={"host": host})
            check("  a Host header of %r does not open the API: 401" % host, r.status_code, 401)
        r = call("POST", "/api/outreach/%s/decision" % uuid.uuid4(), headers={"host": "x/api/health#"},
                 json={"action": "approve"})
        check("  nor approve an email that way", r.status_code, 401)
        check("the login page is public", call("GET", "/login").status_code, 200)
        r = call("GET", "/privacy")
        check("the privacy policy is public (Google's consent screen links to it), and self-contained",
              (r.status_code, "Limited Use" in r.text, 'src="app.js"' in r.text or 'href="style.css"' in r.text),
              (200, True, False))
        check("  but only that page: its file under /static stays behind the wall",
              call("GET", "/privacy.html").status_code, 302)
        h = call("GET", "/api/health")
        check("health is public and says ok", (h.status_code, h.json().get("ok")), (200, True))
        check("auth state: set up, not signed in (the login page offers the demo)", call("GET", "/api/auth/state").json(),
              {"needs_setup": False, "authed": False, "user": None, "demo": True})
        check("no API console (docs, openapi)", [call("GET", u, cookies=tvf).status_code
                                                 for u in ("/docs", "/openapi.json", "/redoc")], [404, 404, 404])
        for url in ("/.env", "/../.env", "/%2e%2e/.env", "/..%2f.env", "/.gmail_token.json", "/static/../../.env"):
            r = call("GET", url, cookies=tvf)
            check("  %s is not served" % url, r.status_code in (404, 400) and "SUPABASE" not in r.text, True)

        # ------------------------------------------------------------ sessions
        print("\n-- sessions")
        check("a valid session cookie gets in", call("GET", "/api/segment", cookies=tvf).status_code, 200)
        e_, x_, fp_, sig_ = good[auth.COOKIE].split("|")
        forged = {auth.COOKIE: "|".join(["owner@example.com", x_, fp_, sig_])}
        check("a cookie with another email in it: 401", call("GET", "/api/stats", cookies=forged).status_code, 401)
        longer = {auth.COOKIE: "|".join([e_, str(int(x_) + 86400 * 365), fp_, sig_])}
        check("a cookie with its expiry pushed out: 401", call("GET", "/api/stats", cookies=longer).status_code, 401)
        expired_x = int(time.time()) - 10
        expired = {auth.COOKIE: "|".join([e_, str(expired_x), fp_, auth._sign(e_, expired_x, fp_)])}
        check("an expired cookie, correctly signed: 401", call("GET", "/api/stats", cookies=expired).status_code, 401)
        check("garbage in the cookie: 401", call("GET", "/api/stats", cookies={auth.COOKIE: "a|b"}).status_code, 401)
        with conn.cursor() as _unused:
            cur.execute("savepoint pw")
            cur.execute("update app_users set password_hash = %s where email = %s",
                        (bcrypt.hashpw(b"another-password", bcrypt.gensalt(4)).decode(), email))
        check("after a password change the old cookie is dead", call("GET", "/api/stats", cookies=tvf).status_code, 401)
        with conn.cursor() as _unused:
            cur.execute("rollback to savepoint pw")
        check("  (and back once the password is restored)", call("GET", "/api/stats", cookies=tvf).status_code, 200)

        # ------------------------------------------------------------ login
        print("\n-- login")
        auth._ATTEMPTS.clear()
        ip = {"x-forwarded-for": "203.0.113.7"}
        check("setup is closed once a user exists", call("POST", "/api/auth/setup",
                                                         json={"email": "x@example.com", "password": "x" * 12}).status_code, 409)
        check("a wrong password: 401", call("POST", "/api/auth/login", headers=ip,
                                            json={"email": email, "password": "wrong"}).status_code, 401)
        check("an unknown email: the same 401", call("POST", "/api/auth/login", headers=ip,
                                                     json={"email": "nobody@example.com", "password": "x"}).status_code, 401)
        r = call("POST", "/api/auth/login", json={"email": email.upper(), "password": password})
        sc = r.headers.get("set-cookie", "")
        check("the right password (email in any case): 200 and a session cookie", (r.status_code, sc.startswith(auth.COOKIE + "=")),
              (200, True))
        check("  httpOnly, SameSite=Lax, 7 days", ("httponly" in sc.lower(), "samesite=lax" in sc.lower(), "max-age=604800" in sc.lower()),
              (True, True, True))
        r = call("POST", "/api/auth/login", headers={"x-forwarded-proto": "https"}, json={"email": email, "password": password})
        check("  Secure when the request came over HTTPS", "secure" in r.headers.get("set-cookie", "").lower(), True)
        for _ in range(8):
            call("POST", "/api/auth/login", headers=ip, json={"email": email, "password": "wrong"})
        check("ten wrong guesses from one address: the next is refused (429)",
              call("POST", "/api/auth/login", headers=ip, json={"email": email, "password": password}).status_code, 429)
        spoof = {"x-forwarded-for": "198.51.100.%d, 203.0.113.7" % (uuid.uuid4().int % 250)}
        check("  a made-up first hop in X-Forwarded-For does not get round it",
              call("POST", "/api/auth/login", headers=spoof, json={"email": email, "password": "wrong"}).status_code, 429)
        auth._ATTEMPTS.clear()
        r = call("POST", "/api/auth/logout", cookies=good)
        check("logout clears the cookie", (r.status_code, "max-age=0" in r.headers.get("set-cookie", "").lower()), (200, True))

        # ------------------------------------------------------------ JSON only
        print("\n-- writes take JSON only (a cross-site form cannot make one)")
        e1, c1 = company()
        for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
            r = call("POST", "/api/leads/%s/decision" % e1, cookies=mine, content=b'{"decision": "shortlist"}',
                     headers={"content-type": ctype})
            check("  a %s body is refused" % ctype.split(";")[0], r.status_code, 422)
        # a body with no content type at all is parsed as JSON by FastAPI, so the browser's own word on
        # where a request came from decides (Sec-Fetch-Site), whatever the body
        for site in ("cross-site", "same-site"):
            r = call("POST", "/api/leads/%s/decision" % e1, cookies=mine, content=b'{"decision": "shortlist"}',
                     headers={"sec-fetch-site": site})
            check("  a write the browser marks %s is refused: 403" % site, r.status_code, 403)
        r = call("POST", "/api/schedule/run/weekly_refresh", cookies=tvf, headers={"sec-fetch-site": "cross-site"})
        check("  even one with no body (run a pipeline from another site): 403", (r.status_code, runs), (403, []))
        check("  a cross-site login is refused too", call("POST", "/api/auth/login", headers={"sec-fetch-site": "cross-site"},
                                                          json={"email": email, "password": password}).status_code, 403)
        check("  reading from another site's link still works (GET)",
              call("GET", "/api/segment", cookies=tvf, headers={"sec-fetch-site": "cross-site"}).status_code, 200)
        r = call("GET", "/api/segment", cookies=tvf)
        check("  responses say nosniff, no framing, same-origin referrers",
              [r.headers.get(h) for h in ("x-content-type-options", "x-frame-options", "referrer-policy")],
              ["nosniff", "DENY", "same-origin"])

        # ------------------------------------------------------------ reads
        print("\n-- every read, every project")
        for seg in [r_["slug"] for r_ in main.segment_rows(force=True) if not r_["slug"].startswith("zz-")]:
            ck = dict(good, tvf_segment=seg)
            codes = {u: call("GET", u, cookies=ck).status_code for u in (
                "/api/segment", "/api/segments", "/api/stats", "/api/leads", "/api/leads?status=all&limit=5",
                "/api/leads?status=shortlisted", "/api/leads?contact=yes", "/api/leads?contact=no&q=film",
                "/api/outreach", "/api/outreach?folder=outbox", "/api/outreach?folder=sent", "/api/outreach?folder=inbox",
                "/api/outreach?folder=attention", "/api/outreach/footer", "/api/mailboxes", "/api/kpis", "/api/schedule",
                "/api/ops")}
            bad = {u: c for u, c in codes.items() if c != 200}
            check("%s: all %d read endpoints answer 200" % (seg, len(codes)), bad, {})
        seg = call("GET", "/api/segment", cookies=tvf).json()
        check("US Production Houses: thresholds and the auto-shortlist line", (seg["thresholds"], seg["auto_shortlist"],
              seg["auto_shortlist_min"]), ({"review": 25.0, "priority": 45.0}, True, 30.0))
        lst = call("GET", "/api/leads?status=all&limit=500", cookies=tvf).json()
        check("the leads list: its total is with + without an address",
              lst["total"], lst["with_address"] + lst["without_address"])
        yes = call("GET", "/api/leads?status=all&contact=yes&limit=500", cookies=tvf).json()
        check("  the contact filter: 'has an address' returns exactly that many, each with an email",
              (yes["total"], all(r_["email"] for r_ in yes["rows"])), (lst["with_address"], True))
        check("  sorted by score, highest first",
              [float(r_["fit_score"]) for r_ in lst["rows"]] == sorted((float(r_["fit_score"]) for r_ in lst["rows"]),
                                                                       reverse=True), True)
        lead = next(r_ for r_ in lst["rows"] if r_["email"])
        d = call("GET", "/api/leads/%s" % lead["id"], cookies=tvf)
        check("a lead's detail: 200 with contacts, criteria and the analysis",
              (d.status_code, all(k in d.json() for k in ("contacts", "criteria", "explain", "outreach"))), (200, True))
        check("a lead that does not exist: 404",
              call("GET", "/api/leads/%s" % uuid.uuid4(), cookies=tvf).status_code, 404)
        check("a lead id that is not an id: 404, not a server error",
              call("GET", "/api/leads/not-a-lead", cookies=tvf).status_code, 404)
        for q in ("limit=-1", "offset=-5", "limit=0", "limit=100000", "min_score=abc", "status=nonsense"):
            c = call("GET", "/api/leads?" + q, cookies=tvf).status_code
            check("  /api/leads?%s: a clean answer, not a server error" % q, c in (200, 400, 422), True)
        mb = call("GET", "/api/mailboxes", cookies=tvf).json()
        check("US Production Houses: sending today per person (each from their own address), not paused",
              (mb.get("mode"), isinstance(mb.get("accounts"), list), mb["paused"]), ("approver", True, None))
        check("  resets at the next midnight UTC", mb["resets_at"].endswith("T00:00:00+00:00"), True)
        own = call("GET", "/api/mailboxes", cookies=mine).json()
        check("a project sending from its own mailbox: 35 a day on the counter", (own["segment_cap"], own["limit_today"]),
              (35, 35))
        lcx = call("GET", "/api/mailboxes", cookies=dict(good, tvf_segment="lcx-clipping")).json()
        # the owner resumed LCX Clipping's sending on 2026-10-19 (d69eab1), from each approver's own Gmail since
        # 2026-10-21 (83949eb): not paused, per person -- and this test user has no Gmail, so cannot send
        check("  LCX Clipping sends again, from each approver's Gmail (this user has none)",
              (lcx.get("mode"), bool(lcx["paused"]), lcx["can_send"]), ("approver", False, False))
        k = call("GET", "/api/kpis", cookies=tvf).json()
        check("the numbers page has its queries", len(k) >= 3 and "by_source" in k, True)
        x = call("GET", "/api/export.xlsx?status=shortlisted", cookies=tvf)
        check("the export: an .xlsx file", (x.status_code, x.content[:2], "spreadsheetml" in x.headers.get("content-type", "")),
              (200, b"PK", True))
        x = call("GET", "/api/export.xlsx?status=all&contact=yes&q=film", cookies=tvf)
        check("  with filters too", (x.status_code, x.content[:2]), (200, b"PK"))
        check("the page itself, signed in: stamped script and style, not cached",
              (lambda r_: (r_.status_code, bool(re.search(r'src="app\.js\?v=\d+"', r_.text)),
                           r_.headers.get("cache-control")))(call("GET", "/", cookies=tvf)), (200, True, "no-store"))
        check("  and its script is served", call("GET", "/app.js", cookies=tvf).status_code, 200)

        # ------------------------------------------------------------ writes
        print("\n-- the writes the page makes (throwaway project, rolled back)")
        check("pick a project that does not exist: 404",
              call("POST", "/api/segment/select", cookies=good, json={"slug": "nope"}).status_code, 404)
        r = call("POST", "/api/segment/select", cookies=good, json={"slug": slug})
        check("pick the test project: 200 and the project cookie", (r.status_code, "tvf_segment=" + slug in r.headers.get("set-cookie", "")),
              (200, True))
        r = call("POST", "/api/leads/%s/decision" % e1, cookies=mine, json={"decision": "shortlist"})
        check("shortlist: 200, and the email is drafted straight away", (r.status_code, r.json().get("drafting"), kicks[-1:]),
              (200, True, [(slug, "manual")]))
        m1 = None
        with conn.cursor() as _unused:
            m1 = draft(e1, c1)
        r = call("POST", "/api/leads/%s/decision" % e1, cookies=mine, json={"decision": "reject", "reason": "test"})
        check("reject: the waiting draft is withdrawn with it", (r.status_code, r.json()["status"], r.json()["withdrawn"]),
              (200, "rejected", 1))
        check("reset: back to review", call("POST", "/api/leads/%s/decision" % e1, cookies=mine,
                                            json={"decision": "reset"}).json()["status"], "ready_for_review")
        check("a decision that does not exist: 400", call("POST", "/api/leads/%s/decision" % e1, cookies=mine,
                                                          json={"decision": "maybe"}).status_code, 400)
        check("a lead that does not exist: 404", call("POST", "/api/leads/%s/decision" % uuid.uuid4(), cookies=mine,
                                                      json={"decision": "shortlist"}).status_code, 404)
        check("a lead id that is not an id: 404, not a server error",
              call("POST", "/api/leads/not-a-lead/decision", cookies=mine, json={"decision": "shortlist"}).status_code, 404)

        e2, c2 = company("shortlisted")
        with conn.cursor() as _unused:
            m2 = draft(e2, c2)
            m_setme = draft(*company("shortlisted"), body="Hello,\n\nBody\n\nSET_ME")
            m_break = draft(*company("shortlisted"), subject="Hello\nBcc: evil@zz-api.example")
        check("edit a draft: 200", call("PATCH", "/api/outreach/%s" % m2, cookies=mine,
                                        json={"subject": "Edited subject"}).status_code, 200)
        check("a subject edited to two lines: 400", call("PATCH", "/api/outreach/%s" % m2, cookies=mine,
                                                         json={"subject": "Hello\nBcc: x@zz-api.example"}).status_code, 400)
        check("a draft id that is not an id: 404", call("PATCH", "/api/outreach/nope", cookies=mine,
                                                        json={"subject": "x"}).status_code, 404)
        check("approve a draft with SET_ME in it: refused", call("POST", "/api/outreach/%s/decision" % m_setme, cookies=mine,
                                                                 json={"action": "approve"}).status_code, 409)
        check("approve a draft whose subject has a line break: refused",
              call("POST", "/api/outreach/%s/decision" % m_break, cookies=mine, json={"action": "approve"}).status_code, 409)
        # the sending window (owner, 2026-10-12: each approved email at its own random second, 10:00-10:30 on its
        # recipient's clock), switched on for the test project as the repo's US Production Houses config has it
        block = json.loads((ROOT / "config" / "segment.us-production-houses.json").read_text(encoding="utf-8"))[
            "outreach"]["send_window"]
        cur.execute("update segments set config = jsonb_set(config, '{outreach,send_window}', %s::jsonb) where id = %s",
                    (json.dumps(block), seg_id))
        w = call("GET", "/api/outreach/%s/window" % m2, cookies=mine).json()
        check("a draft's window: the 10:00-10:30 approving it aims at, its recipient's clock and why, never a minute",
              (w.get("enabled"), "10:00-10:30" in (w.get("window_label") or ""), bool(w.get("send_tz_reason"))),
              (True, True, True))
        check("  another project's draft, or no such one: nothing to say",
              (call("GET", "/api/outreach/%s/window" % m2, cookies=tvf).json(),
               call("GET", "/api/outreach/%s/window" % uuid.uuid4(), cookies=mine).json(),
               call("GET", "/api/outreach/nope/window", cookies=mine).status_code), ({"enabled": False}, {"enabled": False}, 404))
        kicks.clear()
        r = call("POST", "/api/outreach/%s/decision" % m2, cookies=mine, json={"action": "approve"})
        check("approve a good draft: 200, and the send is kicked", (r.status_code, r.json().get("ok"), kicks), (200, True, [(slug, "manual")]))
        sched = r.json().get("schedule") or {}
        check("  and the answer says when it goes: its own second in its recipient's window, in the page's words",
              (bool(sched.get("send_label")), " time" in (sched.get("send_label") or ""), bool(sched.get("send_tz_reason"))),
              (True, True, True))
        ob = next((x for x in call("GET", "/api/outreach?folder=outbox", cookies=mine).json()["rows"] if x["id"] == m2), {})
        check("  the Approved folder carries the same time, for its Goes out column",
              ((ob.get("schedule") or {}).get("send_short"), (ob.get("schedule") or {}).get("send_after")),
              (sched.get("send_short"), sched.get("send_after")))
        check("  approved, its draft window has nothing more to say", call("GET", "/api/outreach/%s/window" % m2,
                                                                         cookies=mine).json(), {"enabled": False})
        lead_now = call("GET", "/api/leads/%s" % e2, cookies=mine).json()
        check("  the lead's analysis says when it goes out", (lead_now["explain"]["analysis"]["next_step"],
              (lead_now["outreach"].get("schedule") or {}).get("send_label")),
              ("Approved: it goes out %s." % sched.get("send_label"), sched.get("send_label")))
        with conn.cursor() as _unused:
            cur.execute("select status, approved_by, approval_mode from outreach where id = %s", (m2,))
            check("  recorded against the person who approved it", list(cur.fetchone()), ["approved", email, "single"])
            cur.execute("select send_after > now(), send_after < send_before, send_tz is not null from outreach where id = %s",
                        (m2,))
            check("  and its moment is kept on the email (sql/34), in the future", list(cur.fetchone()), [True, True, True])
            # parked with a send error, nothing sends it: no time is promised anywhere (review, 2026-10-12)
            cur.execute("update outreach set send_error = 'recipient failed verification' where id = %s", (m2,))
        held = next((x for x in call("GET", "/api/outreach?folder=outbox", cookies=mine).json()["rows"] if x["id"] == m2), {})
        hs = held.get("schedule") or {}
        check("  held back with a send error: Approved says Held and why, and promises no time",
              (hs.get("held"), hs.get("held_why"), hs.get("send_short"), hs.get("send_after")),
              (True, "recipient failed verification", None, None))
        lead_held = call("GET", "/api/leads/%s" % e2, cookies=mine).json()
        check("  and the lead's analysis says it is held, not when it goes",
              lead_held["explain"]["analysis"]["next_step"],
              "Approved, but held back: recipient failed verification. It is not sent.")
        with conn.cursor() as _unused:
            cur.execute("update outreach set send_error = null where id = %s", (m2,))
        sl = call("GET", "/api/schedule", cookies=mine).json().get("send_loop") or {}
        check("Operations says whether the timed sender runs here (not in a test: the scheduler is off), and why",
              (sl.get("on"), bool(sl.get("why"))), (False, True))
        # second review, 2026-10-12: the timed sends are their own pipeline, "send", so the tick's line keeps its own
        # last run; and a Gmail refusal a send handled (its run ends OK) is shown for a day, not hidden behind "OK"
        with conn.cursor() as _unused:
            cur.execute("insert into pipeline_runs (pipeline, step, trigger, status, detail, segment, started_at)"
                        " values ('outreach', null, 'schedule', 'failed', 'failed at step(s) ''draft_outreach''', %s, now()),"
                        " ('send', null, 'schedule', 'ok', null, %s, now()),"
                        " ('send', 'send_outreach', 'schedule', 'ok',"
                        "  'Gmail refused old@zz-api.example (403): its emails moved', %s, now() - interval '25 hours')",
                        (slug, slug, slug))
        sch = call("GET", "/api/schedule", cookies=mine).json()
        last_ = sch.get("last") or {}
        check("  /api/schedule: the tick's last run and the timed sender's, each under its own name",
              ((last_.get("outreach") or {}).get("status"), (last_.get("send") or {}).get("status")), ("failed", "ok"))
        check("  a refusal older than a day is not shown", sch.get("refused"), None)
        with conn.cursor() as _unused:
            cur.execute("insert into pipeline_runs (pipeline, step, trigger, status, detail, segment)"
                        " values ('send', 'send_outreach', 'schedule', 'ok', 'Gmail refused zz-a@zz-api.example (403): its"
                        " emails moved to their next window, saying why; the other addresses carry on', %s)", (slug,))
        ref = call("GET", "/api/schedule", cookies=mine).json().get("refused") or {}
        check("  the day's latest refusal is, with when it was",
              ((ref.get("detail") or "").startswith("Gmail refused zz-a@zz-api.example (403)"), bool(ref.get("at"))),
              (True, True))
        main.segment_rows(force=True)                      # the window was switched on above, inside this test
        pol_info = call("GET", "/api/segment", cookies=mine).json().get("outreach_policy") or {}
        check("  the page knows whose clock the window is on, and the sender's place, for its sentences",
              ((pol_info.get("send_window") or {}).get("timezone_of"), (pol_info.get("send_window") or {}).get("sender_place")),
              ("recipient", "India"))
        check("approve it again: 409", call("POST", "/api/outreach/%s/decision" % m2, cookies=mine,
                                            json={"action": "approve"}).status_code, 409)
        check("edit it once approved: 409 (approval means THIS text)", call("PATCH", "/api/outreach/%s" % m2, cookies=mine,
                                                                            json={"body": "changed"}).status_code, 409)
        check("an unknown action: 400", call("POST", "/api/outreach/%s/decision" % m2, cookies=mine,
                                             json={"action": "launch"}).status_code, 400)
        check("mark an outbound email as a reply: 409", call("POST", "/api/outreach/%s/decision" % m2, cookies=mine,
                                                             json={"action": "mark_positive"}).status_code, 409)
        # one first email per inbox, and per company name (2026-09-21)
        e_twin, c_twin = company("shortlisted", address=False)
        cur.execute("insert into contacts (entity_id, full_name, email, email_status)"
                    " select %s, 'Kay Doe', upper(email), 'valid' from contacts where id = %s returning id", (e_twin, c2))
        m_twin = draft(e_twin, cur.fetchone()[0])
        r = call("POST", "/api/outreach/%s/decision" % m_twin, cookies=mine, json={"action": "approve"})
        check("approve a second first email to an inbox that already has one: refused, and why",
              (r.status_code, "already has a first email" in r.json().get("detail", "")), (409, True))
        cur.execute("select name from entities where id = %s", (e2,))
        twin_name = cur.fetchone()[0]
        e_same, c_same = company("shortlisted")
        cur.execute("update entities set name = upper(%s) where id = %s", (twin_name, e_same))
        m_same = draft(e_same, c_same)
        r = call("POST", "/api/outreach/%s/decision" % m_same, cookies=mine, json={"action": "approve"})
        check("approve a first email to a company of the same name: refused",
              (r.status_code, "same name" in r.json().get("detail", "")), (409, True))
        # two drafts to one inbox checked together (a batch): only the first is approvable
        import outreach_policy
        e_a, c_a = company("shortlisted")
        e_b, _ = company("shortlisted", address=False)
        cur.execute("insert into contacts (entity_id, full_name, email, email_status)"
                    " select %s, 'Kay Doe', email, 'valid' from contacts where id = %s returning id", (e_b, c_a))
        c_b = cur.fetchone()[0]
        d_a, d_b = draft(e_a, c_a), draft(e_b, c_b)
        ok_ids, skipped = outreach_policy.check_drafts(cur, [d_a, d_b], slug)
        check("two drafts to one inbox in one batch: the first passes, the second is held back",
              (len(ok_ids), [s_["reason"] for s_ in skipped]),
              (1, ["another selected draft goes to the same address or company"]))
        check("cancel the approved email: 200", call("POST", "/api/outreach/%s/decision" % m2, cookies=mine,
                                                     json={"action": "cancel"}).status_code, 200)
        e_go, c_go = company("shortlisted")
        with conn.cursor() as _unused:
            m_go = draft(e_go, c_go, status="sending")
        r = call("POST", "/api/outreach/%s/decision" % m_go, cookies=mine, json={"action": "cancel"})
        check("withdrawing one already going out: 409, and why", (r.status_code, r.json().get("detail")),
              (409, "already going out: it can no longer be withdrawn"))
        cur.execute("update outreach set status = 'sent', sent_at = now() where id = %s", (m_go,))
        r = call("POST", "/api/outreach/%s/decision" % m_go, cookies=mine, json={"action": "cancel"})
        check("  one already sent: 409, already sent", (r.status_code, r.json().get("detail")), (409, "already sent"))
        check("a message that does not exist: 404", call("POST", "/api/outreach/%s/decision" % uuid.uuid4(), cookies=mine,
                                                         json={"action": "approve"}).status_code, 404)
        check("a message id that is not an id: 404, not a server error",
              call("POST", "/api/outreach/nope/decision", cookies=mine, json={"action": "approve"}).status_code, 404)
        with conn.cursor() as _unused:
            cur.execute("update entities set status = 'contacted' where id = %s", (e2,))
            cur.execute("insert into outreach (entity_id, contact_id, direction, subject, body, status, gmail_message_id)"
                        " values (%s, %s, 'inbound', 'Re: hello', 'Sounds good', 'received', %s) returning id",
                        (e2, c2, "zz-" + uuid.uuid4().hex))
            reply = str(cur.fetchone()[0])
        r = call("POST", "/api/outreach/%s/decision" % reply, cookies=mine, json={"action": "mark_positive"})
        check("a positive reply moves the company into conversation", (r.status_code, r.json().get("entity_promoted")), (200, True))
        call("POST", "/api/outreach/%s/decision" % reply, cookies=mine, json={"action": "mark_negative"})
        with conn.cursor() as _unused:
            cur.execute("select status from entities where id = %s", (e2,))
            check("  and marking it negative walks that back", cur.fetchone()[0], "contacted")

        check("batch approval is off for this project: 403",
              call("POST", "/api/outreach/batch/sample", cookies=mine, json={"ids": [m2]}).status_code, 403)
        ck_lcx = dict(good, tvf_segment="lcx-clipping")
        check("LCX batch: nothing selected is a 400", call("POST", "/api/outreach/batch/sample", cookies=ck_lcx,
                                                           json={"ids": []}).status_code, 400)
        check("LCX batch: a forged spot-check token is refused",
              call("POST", "/api/outreach/batch/approve", cookies=ck_lcx,
                   json={"ids": [m2], "sample": [m2], "token": "forged"}).status_code, 409)
        # a batch with a sending window: each approved one draws its own second, and the answer says when, by day
        bslug = "zz-api-batch-" + uuid.uuid4().hex[:6]
        # 2026-10-13: clipping signs as the approver (outreach.sign_as), and since 2026-10-21 sends from the approver's
        # Gmail (send_from approver); both need a name and title this test user does not have. This block is about the
        # sending window, so the copy drops sign_as and send_from (signing has its own checks in test_subjects,
        # test_approver_sign and test_lcxs_v3; per-person sending in test_accounts and test_send)
        cur.execute("insert into segments (slug, name, entity_type, config) select %s, 'ZZ API batch', 'company',"
                    " config #- '{outreach,sending_paused}' #- '{outreach,sign_as}' #- '{outreach,send_from}'"
                    " from segments where slug = 'lcx-clipping' returning id", (bslug,))
        bseg = cur.fetchone()[0]
        lcx_block = json.loads((ROOT / "config" / "segment.lcx-clipping.json").read_text(encoding="utf-8"))[
            "outreach"]["send_window"]
        cur.execute("update segments set config = jsonb_set(config, '{outreach,send_window}', %s::jsonb) where id = %s",
                    (json.dumps(lcx_block), bseg))
        main.segment_rows(force=True)
        bck = dict(good, tvf_segment=bslug)
        bids = []
        for _ in range(3):
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score) values"
                        " (%s, %s, %s, 'test', 'shortlisted', 50) returning id",
                        (bseg, "ZZ API batch " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
            be = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s, 'valid')"
                        " returning id", (be, "kay.%s@zz-api.example" % uuid.uuid4().hex[:6]))
            bids.append(draft(be, cur.fetchone()[0]))
        smp = call("POST", "/api/outreach/batch/sample", cookies=bck, json={"ids": bids}).json()
        r = call("POST", "/api/outreach/batch/approve", cookies=bck,
                 json={"ids": smp.get("approvable"), "sample": smp.get("sample"), "token": smp.get("token")})
        wins = r.json().get("windows") or []
        check("a batch with a sending window: approved, and when each goes by its recipients' days and places",
              (r.status_code, r.json().get("approved"), sum(d["count"] for d in wins),
               all(d["label"] and d["places"] and d["day"] for d in wins)), (200, 3, 3, True))
        # second review, 2026-10-12: a paused project's are held, and a held email is never promised a day -- the
        # answer has no windows for the page to put in its message, skipped drafts or not
        cur.execute("update segments set config = jsonb_set(config, '{outreach,sending_paused}', '\"test pause\"')"
                    " where id = %s", (bseg,))
        pids = []
        for _ in range(3):
            cur.execute("insert into entities (segment_id, name, domain, source, status, fit_score) values"
                        " (%s, %s, %s, 'test', 'shortlisted', 50) returning id",
                        (bseg, "ZZ API batch " + uuid.uuid4().hex[:6], uuid.uuid4().hex[:8] + ".example"))
            be = cur.fetchone()[0]
            cur.execute("insert into contacts (entity_id, full_name, email, email_status) values (%s, 'Kay Doe', %s, 'valid')"
                        " returning id", (be, "kay.%s@zz-api.example" % uuid.uuid4().hex[:6]))
            pids.append(draft(be, cur.fetchone()[0]))
        smp = call("POST", "/api/outreach/batch/sample", cookies=bck, json={"ids": pids}).json()
        r = call("POST", "/api/outreach/batch/approve", cookies=bck,
                 json={"ids": smp.get("approvable"), "sample": smp.get("sample"), "token": smp.get("token")})
        check("  the same in a paused project: approved, said to be paused, and no day promised",
              (r.status_code, r.json().get("approved"), bool(r.json().get("paused")), r.json().get("windows")),
              (200, 3, True, []))

        f = call("GET", "/api/outreach/footer", cookies=mine).json()
        check("the footer reads back with no problems", (bool(f["text"]), f["problems"]), (True, []))
        r = call("POST", "/api/outreach/footer", cookies=mine, json={"text": "Thanks,\n{{sender_name}}",
                                                                   "sender": {"postal_address": ""}})
        # 2026-10-13, the owner: no footer carries an opt-out line now, so one without it saves; the empty and
        # unknown-field checks still refuse
        check("a footer without an opt-out line now saves", r.status_code, 200)
        r = call("POST", "/api/outreach/footer", cookies=mine, json={"text": "   ", "sender": {"postal_address": ""}})
        check("an empty footer is refused", r.status_code, 400)
        r = call("POST", "/api/outreach/footer", cookies=mine, json={"text": "Thanks,\n{{fit_score}}",
                                                                   "sender": {"postal_address": ""}})
        check("a footer with an unknown field is refused", r.status_code, 400)
        r = call("POST", "/api/outreach/footer", cookies=mine, json={"text": f["text"], "sender": f["sender"]})
        check("saving the same footer: 200", (r.status_code, r.json().get("ok")), (200, True))

        check("run a pipeline that does not exist: 404",
              call("POST", "/api/schedule/run/nope", cookies=tvf).status_code, 404)
        r = call("POST", "/api/schedule/run/weekly_refresh", cookies=tvf)
        time.sleep(0.3)
        check("run the weekly refresh: 200, handed to the scheduler (a stand-in here)", (r.status_code, runs[-1:]),
              (200, [("weekly_refresh", "manual", TVF)]))
        main._scheduler._running.add((TVF, "weekly_refresh"))
        check("  a second one while it runs: 409", call("POST", "/api/schedule/run/weekly_refresh", cookies=tvf).status_code, 409)
        main._scheduler._running.discard((TVF, "weekly_refresh"))
        check("stopping a send midway is refused", call("POST", "/api/ops/send_outreach/stop", cookies=tvf).status_code, 409)
        check("stopping a job that is not running: 409", call("POST", "/api/ops/qualify_sites/stop", cookies=tvf).status_code, 409)
        check("a job's log that does not exist: empty", call("GET", "/api/ops/nope/log", cookies=tvf).json(), {"lines": []})

        # ------------------------------------------------------------ universal
        print("\n-- the Universal page (Apollo stubbed: no credit spent)")
        st = call("GET", "/api/universal/status", cookies=tvf).json()
        check("status: connected, credits shown, the filters listed",
              (st["apollo"]["connected"], st["apollo"]["credits"]["lead_credits_left"], bool(st["filters"])), (True, 2483, True))
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "people", "filters": {"q_text": "producers in California"}})
        if r.status_code != 200:
            print("  people search answered %s: %s" % (r.status_code, r.text[:300]))
        pj = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check("people search: 200, the preview rows, how the words were read",
              (r.status_code, len(pj.get("people", [])), bool(pj.get("read_as"))), (200, 1, True))
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "companies", "filters": {"q_text": "US arcades"}})
        check("company search: 200 and the company", (r.status_code, [c["name"] for c in r.json().get("companies", [])]),
              (200, ["ZZ Arcade Co"]))
        check("  read as a segment and a place", r.json().get("read_as", "").lower().count("arcade") > 0
              and "united states" in r.json().get("read_as", "").lower(), True)
        # a likely typo in a paid company search is asked about first, and Apollo is not called
        paid_before = fake.calls.count("/mixed_companies/search")
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "companies", "filters": {"q_text": "UAE Restraunts"}})
        check("a company search with a typo is held: no Apollo call, no credit, a suggestion",
              (r.status_code, r.json().get("held"), r.json().get("did_you_mean"), fake.calls.count("/mixed_companies/search") - paid_before),
              (200, True, "UAE Restaurants", 0))
        r = call("POST", "/api/universal/search", cookies=tvf,
                 json={"kind": "companies", "filters": {"q_text": "UAE Restraunts"}, "as_typed": True})
        check("  searched as typed when asked: Apollo is called", (r.status_code, bool(r.json().get("held")),
              fake.calls.count("/mixed_companies/search") - paid_before), (200, False, 1))
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "people", "filters": {"q_text": "UAE Restraunts"}})
        check("  a people search (free) runs, with the suggestion beside it",
              (r.status_code, bool(r.json().get("held")), r.json().get("did_you_mean")), (200, False, "UAE Restaurants"))
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "people", "filters": {"q_text": "UAE restaurants"}})
        # the reading names the levels searched (since 2026-10-19: "People · Management level: Owner, Founder, C-suite")
        check("a people search with no job: decision makers, and the page is told so",
              (r.status_code, r.json().get("decision_makers"), "Management level: Owner, Founder" in r.json().get("read_as", "")),
              (200, True, True))
        r = call("POST", "/api/universal/search", cookies=tvf, json={"kind": "people", "filters": {"q_text": "owners of restaurants in Dubai"}})
        check("  with a job typed: that job, no default", (r.status_code, r.json().get("decision_makers")), (200, False))
        check("a search with no kind: 400", call("POST", "/api/universal/search", cookies=tvf, json={}).status_code, 400)
        check("a filter Apollo would refuse: 400", call("POST", "/api/universal/search", cookies=tvf,
                                                        json={"kind": "companies", "filters": {"revenue_range": {"min": -5}}}).status_code, 400)
        check("a page that is not a number: 400, not a server error",
              call("POST", "/api/universal/search", cookies=tvf, json={"kind": "people", "page": "two"}).status_code, 400)
        # the plain save path, in this test's own project (no Apollo-only sourcing). A project with sourcing.contacts
        # "apollo" (the live US Production Houses since 2026-10-19) refuses a save without the server's receipt of a
        # fresh search, and a person whose company has not qualified: tools/test_apollo_constraints.py
        r = call("POST", "/api/universal/save", cookies=tvf, json={"kind": "people", "ids": [PID[0]], "filters": {}})
        check("an Apollo-only project: a save without a fresh search's receipt is refused, nothing revealed",
              (r.status_code, "Search again" in r.json().get("detail", "")), (409, True))
        # a throwaway copy of Universal without the Apollo-only sourcing, named in the URL as the page names it
        uni = "zz-api-uni-" + uuid.uuid4().hex[:6]
        cur.execute("insert into segments (slug, name, entity_type, config, is_active) select %s, 'ZZ API universal',"
                    " entity_type, (config - 'sourcing'), true from segments where slug = 'universal'", (uni,))
        main.segment_rows(force=True)
        save_url = "/api/universal/save?project=" + uni
        before = len([c for c in fake.calls if c == "/people/bulk_match"])
        r = call("POST", save_url, cookies=tvf, json={"kind": "people", "ids": [PID[0]], "filters": {}})
        if r.status_code != 200:
            print("  (save answered %s: %s)" % (r.status_code, r.text[:300]))
        check("reveal and save one person: 200, one credit, saved",
              (r.status_code, r.json().get("credits"), len([c for c in fake.calls if c == "/people/bulk_match"]) - before),
              (200, 1, 1))
        r = call("POST", save_url, cookies=tvf, json={"kind": "people", "ids": [PID[0]], "filters": {}})
        check("  saving the same person again reveals nothing (no second credit)", (r.status_code, r.json().get("credits"),
              r.json().get("already_saved")), (200, 0.0, 1))
        check("save nobody: 400", call("POST", save_url, cookies=tvf, json={"kind": "people", "ids": []}).status_code, 400)
        r = call("POST", save_url, cookies=tvf, json={"kind": "companies", "companies": [
            {"id": OID[2], "name": "ZZ Saved Co", "website_url": "https://zz-saved.example"}]})
        check("save a company: 200, free", (r.status_code, r.json().get("credits")), (200, 0))
        name = "ZZ test search " + uuid.uuid4().hex[:4]
        r = call("POST", "/api/universal/searches", cookies=tvf, json={"name": name, "kind": "people",
                                                                      "filters": {"person_titles": ["producer"]}})
        sid = r.json().get("id")
        check("save a search: 200", r.status_code, 200)
        check("  it is listed, with its summary", any(s["id"] == sid and s["summary"] for s in
                                                     call("GET", "/api/universal/searches", cookies=tvf).json()["searches"]), True)
        r = call("POST", "/api/universal/searches", cookies=tvf, json={"name": name.upper(), "kind": "people",
                                                                      "filters": {"person_titles": ["director"]}})
        check("  the same name again updates it, not a second copy", r.json().get("id"), sid)
        check("  a search with no name: 400", call("POST", "/api/universal/searches", cookies=tvf,
                                                   json={"name": " ", "kind": "people"}).status_code, 400)
        check("  delete it: 200, then 404", (call("DELETE", "/api/universal/searches/%s" % sid, cookies=tvf).status_code,
                                             call("DELETE", "/api/universal/searches/%s" % sid, cookies=tvf).status_code), (200, 404))

        # ------------------------------------------------------------ overall
        print("\n-- overall")
        check("no secret appears in any response", sorted(set(leaked)), [])
        slow = sorted(TIMES, reverse=True)[:5]
        print("        slowest calls: " + "; ".join("%.1fs %s %s" % t for t in slow))
        check("no call took over 20 seconds", [t for t in TIMES if t[0] > 20], [])
    finally:
        conn.rollback()
        conn.close()
        apollo._call = real_call
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks, %d calls (all rows rolled back; nothing sent, no credit spent)"
          % (bad, len(RESULTS), len(TIMES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
