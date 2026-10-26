#!/usr/bin/env python3
"""test_oauth.py -- signing an MCP client in with OAuth 2.1 (app/oauth.py), as claude.ai's custom connectors do
(owner, 2026-10-26: claude.ai in the browser, "yup"), as a table.

    python tools/test_oauth.py

The real app in-process (FastAPI's TestClient) against the real database inside ONE transaction that is rolled back,
with sql/42-44 applied inside it. Checked, in the order claude.ai goes:

  * a 401 from /mcp points at the protected-resource document, which names exactly <base>/mcp and this server;
    the authorization-server document lists the endpoints, S256 and no other PKCE method
  * registering (RFC 7591): claude.ai's callback and Claude Code's loopback are taken, anything else refused
  * authorizing: signed out goes to the login page and back; a bad client or redirect is refused on our page, never
    sent anywhere; no PKCE is sent back as an error; the page names the app, the person and where it goes back to
  * the person's answer: a forged or stale form is refused; Cancel sends back access_denied; Allow sends a code
  * the token exchange (form-encoded): a wrong verifier, a reused code, another client, all refused; the token works
    on /mcp as that person; refreshing rotates both tokens and the old ones stop; a secret client needs its secret
  * the person sees the connection in the app and Disconnect ends it, refresh token too; approving is only for a
    connection that was allowed to
Exit code 1 on any failure.
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-oauth-test-" + uuid.uuid4().hex
os.environ.pop("PUBLIC_BASE_URL", None)

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
BASE = "http://testserver"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


class TxConn:
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


def pkce():
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")


def main_():
    import main
    import auth
    conn = psycopg2.connect(load_db_url())
    conn.autocommit = False
    tx = TxConn(conn)
    main._checkout = tx.begin
    main._POOL = NoPool()
    main._scheduler.kick_outreach = lambda seg, trigger="manual": None
    main._scheduler.wake_sender = lambda: None
    client = TestClient(main.app, follow_redirects=False, raise_server_exceptions=bool(os.environ.get("ZZ_RAISE")))
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        for f in ("42_manual_leads.sql", "43_api_keys.sql", "44_api_approve_oauth.sql"):
            cur.execute((ROOT / "sql" / f).read_text(encoding="utf-8"))
        main._SEG_CACHE.update(at=0.0, rows=[])
        tag = uuid.uuid4().hex[:6]
        email = "zz-oauth-%s@example.com" % tag
        h = bcrypt.hashpw(b"zz-oauth-password", bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users (email, password_hash, role, name, title) values (%s, %s, 'member',"
                    " 'Olu Auth', 'Partnerships')", (email, h))
        ck = {auth.COOKIE: auth.make_cookie(email, h)}

        def get(path, cookies=None, **kw):
            client.cookies.clear()
            return client.get(path, cookies=cookies, **kw)

        def post(path, cookies=None, **kw):
            client.cookies.clear()
            return client.post(path, cookies=cookies, **kw)

        print("-- discovery")
        r = post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        wa = r.headers.get("www-authenticate", "")
        check("a 401 from /mcp points at the protected-resource document",
              (r.status_code, 'resource_metadata="%s/.well-known/oauth-protected-resource"' % BASE in wa),
              (401, True))
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            d = get(path).json()
            check("%s: exactly <base>/mcp, served by this server" % path,
                  (d["resource"], d["authorization_servers"]), (BASE + "/mcp", [BASE]))
        a = get("/.well-known/oauth-authorization-server").json()
        check("the authorization server: its endpoints, PKCE S256 only, codes and refresh tokens",
              (a["issuer"], a["authorization_endpoint"], a["token_endpoint"], a["registration_endpoint"],
               a["code_challenge_methods_supported"], sorted(a["grant_types_supported"])),
              (BASE, BASE + "/oauth/authorize", BASE + "/oauth/token", BASE + "/oauth/register", ["S256"],
               ["authorization_code", "refresh_token"]))

        print("\n-- registering")
        r = post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [CLAUDE],
                                          "grant_types": ["authorization_code", "refresh_token"],
                                          "response_types": ["code"], "token_endpoint_auth_method": "none"})
        reg = r.json()
        cid = reg.get("client_id", "")
        check("claude.ai registers itself: a public client", (r.status_code, cid.startswith("tlc_"),
                                                              "client_secret" in reg), (201, True, False))
        for bad in ("javascript:alert(1)", "http://evil.example/cb", "https://x.example/cb#frag"):
            r = post("/oauth/register", json={"client_name": "x", "redirect_uris": [bad]})
            check("  refused as a redirect: %s" % bad, (r.status_code, r.json().get("error")),
                  (400, "invalid_redirect_uri"))
        r = post("/oauth/register", json={"client_name": "Claude Code", "redirect_uris": ["http://localhost:33418/callback"]})
        loop = r.json()["client_id"]
        check("Claude Code's loopback is taken", r.status_code, 201)

        print("\n-- authorizing")
        verifier, challenge = pkce()
        q = {"response_type": "code", "client_id": cid, "redirect_uri": CLAUDE, "code_challenge": challenge,
             "code_challenge_method": "S256", "state": "st-" + tag, "scope": "lead-engine",
             "resource": BASE + "/mcp"}
        url = "/oauth/authorize?" + urllib.parse.urlencode(q)
        r = get(url)
        loc = r.headers.get("location", "")
        check("signed out: to the login page, and back here after", (r.status_code, loc.startswith("/login?next="),
              urllib.parse.unquote(loc.split("next=", 1)[-1]).startswith("/oauth/authorize?")), (302, True, True))
        r = get("/oauth/authorize?" + urllib.parse.urlencode(dict(q, client_id="tlc_nope")), cookies=ck)
        check("an unknown client: refused on our page, sent nowhere", (r.status_code, "location" in r.headers),
              (400, False))
        r = get("/oauth/authorize?" + urllib.parse.urlencode(dict(q, redirect_uri="https://evil.example/cb")),
                cookies=ck)
        check("  a redirect it did not register: refused on our page", (r.status_code, "location" in r.headers),
              (400, False))
        r = get("/oauth/authorize?" + urllib.parse.urlencode({k: v for k, v in q.items() if k != "code_challenge"}),
                cookies=ck)
        check("  no PKCE: sent back with invalid_request",
              (r.status_code, "error=invalid_request" in r.headers.get("location", "")), (302, True))
        r = get("/oauth/authorize?" + urllib.parse.urlencode(dict(q, resource="https://other.example/mcp")), cookies=ck)
        check("  another server's resource: invalid_target", "error=invalid_target" in r.headers.get("location", ""),
              True)
        r = get(url, cookies=ck)
        page = r.text
        check("signed in: the page names the app, the person, and where it goes back",
              (r.status_code, "Claude" in page, "Olu Auth" in page, "claude.ai" in page,
               r.headers.get("x-frame-options")), (200, True, True, True, "DENY"))
        form = {m.group(1): html.unescape(m.group(2))
                for m in re.finditer(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page)}

        def answer(decision, approve=True, **change):
            body = dict(form, decision=decision, **change)
            if approve:
                body["can_approve"] = "1"
            return post("/oauth/authorize", cookies=ck, content=urllib.parse.urlencode(body),
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = answer("allow", state="forged")
        check("a changed form is refused", (r.status_code, "location" in r.headers), (400, False))
        r = answer("deny")
        check("Cancel: back with access_denied and its state",
              ("error=access_denied" in r.headers.get("location", ""), "state=st-" + tag in r.headers["location"]),
              (True, True))

        def code_for(approve=True):
            r = answer("allow", approve=approve)
            back = urllib.parse.urlsplit(r.headers.get("location", ""))
            qs = dict(urllib.parse.parse_qsl(back.query))
            return r, back, qs
        r, back, qs = code_for()
        check("Allow: back to claude.ai with a code, its state and the issuer",
              (r.status_code, "%s://%s%s" % (back.scheme, back.netloc, back.path), bool(qs.get("code")),
               qs.get("state"), qs.get("iss")), (302, CLAUDE, True, "st-" + tag, BASE))

        print("\n-- tokens")

        def token(**f):
            client.cookies.clear()
            return client.post("/oauth/token", content=urllib.parse.urlencode(f),
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
        r = token(grant_type="authorization_code", code=qs["code"], client_id=cid, redirect_uri=CLAUDE,
                  code_verifier=secrets.token_urlsafe(48))
        check("a wrong PKCE verifier: invalid_grant (and the code is spent)", (r.status_code, r.json()["error"]),
              (400, "invalid_grant"))
        r = token(grant_type="authorization_code", code=qs["code"], client_id=cid, redirect_uri=CLAUDE,
                  code_verifier=verifier)
        check("  the spent code, even with the right verifier: invalid_grant", r.json().get("error"), "invalid_grant")
        r, back, qs = code_for()
        r = token(grant_type="authorization_code", code=qs["code"], client_id=loop, redirect_uri=CLAUDE,
                  code_verifier=verifier)
        check("another client's code: invalid_grant", r.json().get("error"), "invalid_grant")
        r, back, qs = code_for()
        r = token(grant_type="authorization_code", code=qs["code"], client_id=cid, redirect_uri=CLAUDE,
                  code_verifier=verifier)
        tok = r.json()
        check("the exchange: a bearer token for an hour and a refresh token, never cached",
              (r.status_code, tok.get("token_type"), tok.get("expires_in"), bool(tok.get("refresh_token")),
               r.headers.get("cache-control")), (200, "Bearer", 3600, True, "no-store"))

        def mcp(access, method="tools/call", params=None):
            client.cookies.clear()
            return client.post("/mcp", headers={"Authorization": "Bearer " + access},
                               json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        r = mcp(tok["access_token"], params={"name": "whoami", "arguments": {}})
        check("the token works on /mcp, as the person who allowed it",
              (r.status_code, r.json()["result"]["structuredContent"]["email"]), (200, email))
        r = token(grant_type="refresh_token", refresh_token=tok["refresh_token"], client_id=cid)
        tok2 = r.json()
        check("refreshing: new tokens", (r.status_code, tok2["access_token"] != tok["access_token"],
                                         tok2["refresh_token"] != tok["refresh_token"]), (200, True, True))
        r = token(grant_type="refresh_token", refresh_token=tok["refresh_token"], client_id=cid)
        check("  the old refresh token is spent: invalid_grant", r.json().get("error"), "invalid_grant")
        check("  the old access token stops", mcp(tok["access_token"], "ping").status_code, 401)
        check("  the new one works", mcp(tok2["access_token"], "ping").status_code, 200)

        print("\n-- the person's side")
        client.cookies.clear()
        keys = client.get("/api/keys", cookies=ck).json()["keys"]
        conn_row = [k for k in keys if k["connected_app"] and not k["revoked_at"]]
        check("the connection shows in the app, as a connected app that may approve",
              [(k["name"], k["can_approve"]) for k in conn_row], [("Claude", True)])
        client.cookies.clear()
        r = client.delete("/api/keys/%s" % conn_row[0]["id"], cookies=ck)
        check("Disconnect: the token stops", (r.status_code, mcp(tok2["access_token"], "ping").status_code), (200, 401))
        r = token(grant_type="refresh_token", refresh_token=tok2["refresh_token"], client_id=cid)
        check("  and it cannot renew itself", r.json().get("error"), "invalid_grant")
        r, back, qs = code_for(approve=False)
        tok3 = token(grant_type="authorization_code", code=qs["code"], client_id=cid, redirect_uri=CLAUDE,
                     code_verifier=verifier).json()
        r = mcp(tok3["access_token"], params={"name": "approve_email", "arguments": {"email_id": str(uuid.uuid4())}})
        check("allowed without approving: approve_email is refused", (r.json()["result"]["isError"],
              "may not approve" in r.json()["result"]["content"][0]["text"]), (True, True))

        print("\n-- loopback and secrets")
        v2, c2 = pkce()
        r = get("/oauth/authorize?" + urllib.parse.urlencode({
            "response_type": "code", "client_id": loop, "redirect_uri": "http://127.0.0.1:5555/callback",
            "code_challenge": c2, "code_challenge_method": "S256"}), cookies=ck)
        check("Claude Code's loopback: another port, 127.0.0.1 for localhost, is the same", r.status_code, 200)
        r = post("/oauth/register", json={"client_name": "Secretive", "redirect_uris": ["https://app.example/cb"],
                                          "token_endpoint_auth_method": "client_secret_post"})
        sec = r.json()
        check("a client that asks for a secret gets one", bool(sec.get("client_secret")), True)
        r = token(grant_type="refresh_token", refresh_token="x", client_id=sec["client_id"])
        check("  and is refused without it (invalid_client)", (r.status_code, r.json()["error"]), (401, "invalid_client"))
        r = token(grant_type="refresh_token", refresh_token="x", client_id=sec["client_id"],
                  client_secret=sec["client_secret"])
        check("  with it, it gets as far as the grant", r.json()["error"], "invalid_grant")
        r = token(grant_type="password", client_id=cid)
        check("an unknown grant type", r.json()["error"], "unsupported_grant_type")
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
