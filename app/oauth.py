"""oauth.py -- signing an MCP client in with OAuth 2.1, so claude.ai's custom connectors can use the Lead Engine.

The owner, 2026-10-26, asked whether claude.ai in the browser should connect too: "yup". claude.ai's custom connectors
cannot send a key; they sign in. This is the smallest authorization server that does what the MCP specification and
Claude's connector documentation ask (checked 2026-10-26):

  GET  /.well-known/oauth-protected-resource[/mcp]   RFC 9728: the resource (exactly <base>/mcp) and its server
  GET  /.well-known/oauth-authorization-server       RFC 8414: the endpoints below, PKCE S256, no OpenID
  POST /oauth/register                               RFC 7591: a client registers itself (claude.ai does, per
                                                     connection); public unless it asks to use a secret
  GET  /oauth/authorize                              the person, signed in to the Lead Engine, sees who is asking
                                                     and where it sends them back, and allows it or not
  POST /oauth/authorize                              their answer (a signed form, same site only)
  POST /oauth/token                                  form-encoded: a code (PKCE checked) or a refresh token for an
                                                     access token; refresh tokens rotate on every use

A 401 from /mcp names where to start: WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-
protected-resource" (app/api_v1.challenge).

WHAT A CLIENT GETS
An access token is an api_keys row like a key made by hand (sql/43, sql/44): it works as the person who allowed it,
only on /api/v1 and /mcp, may approve emails only if the person ticked that, and lasts an hour; the refresh token
(60 days, used once) renews it. The person sees the connection in the app (account menu, API and MCP) and Revoke
ends it for good. Codes last five minutes and are used once. Codes and refresh tokens are kept only as SHA-256.

Redirects go only where the client registered: https anywhere, http only to this machine (localhost, any port, for
Claude Code), or an app's own scheme. The page always says where it is sending the person back to.
"""
import base64
import collections
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

CODE_SECONDS = 300
ACCESS_SECONDS = 3600
REFRESH_DAYS = 60
FORM_SECONDS = 900
SCOPE = "lead-engine"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
METHODS = ("none", "client_secret_post", "client_secret_basic")
BAD_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob", "http", "https"}
_REG = collections.defaultdict(collections.deque)          # address -> registration times (30 an hour)
_LOCK = threading.Lock()


def base_url(request):
    """This server as the world reaches it: PUBLIC_BASE_URL when set, else the request's own host and scheme."""
    base = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    host = request.headers.get("host", "")
    if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", host):
        host = "localhost"
    proto = "https" if request.headers.get("x-forwarded-proto") == "https" else request.url.scheme
    return "%s://%s" % (proto, host)


def resource(request):
    return base_url(request) + "/mcp"


def metadata_url(request):
    return base_url(request) + "/.well-known/oauth-protected-resource"


def _h(v):
    return hashlib.sha256(str(v).encode("utf-8")).hexdigest()


def _secret():
    import auth
    return auth._secret()


def redirect_ok(uri):
    """May a client register this redirect? https, http to this machine, or an app's own scheme; never a fragment."""
    try:
        u = urllib.parse.urlsplit(str(uri))
    except ValueError:
        return False
    if u.fragment or len(str(uri)) > 500:
        return False
    if u.scheme == "https":
        return bool(u.hostname)
    if u.scheme == "http":
        return u.hostname in LOOPBACK
    return bool(re.fullmatch(r"[a-z][a-z0-9+.\-]*", u.scheme or "")) and u.scheme not in BAD_SCHEMES


def redirect_matches(uri, registered):
    """The redirect asked for is one registered; on this machine (http, localhost) the port may differ (RFC 8252)."""
    if not uri:
        return False
    if uri in registered:
        return True
    try:
        u = urllib.parse.urlsplit(uri)
    except ValueError:
        return False
    if u.scheme != "http" or u.hostname not in LOOPBACK:
        return False
    for r in registered:
        v = urllib.parse.urlsplit(r)
        if v.scheme == "http" and v.hostname in LOOPBACK and v.path == u.path and v.query == u.query:
            return True
    return False


def _back(uri, **params):
    """Back to the client, with these parameters (and nothing of ours in a fragment)."""
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return RedirectResponse(uri + ("&" if urllib.parse.urlsplit(uri).query else "?") + q, status_code=302)


def _sign(*parts):
    msg = "|".join(str(p) for p in parts)
    return hmac.new(_secret(), ("oauth|" + msg).encode("utf-8"), hashlib.sha256).hexdigest()


def _err(error, description, status=400):
    return JSONResponse({"error": error, "error_description": description}, status_code=status,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


# --------------------------------------------------------------- the pages
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>%(title)s - TVF Lead Engine</title>
<style>
:root { color-scheme: light; --canvas:#F1F2F5; --surface:#FFFFFF; --text:#101828; --subtle:#475467;
  --border:#E4E7EC; --brand:#4F46E5; --brand-hover:#4338CA; --warn:#B54708; --warn-bg:#FFFAEB; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark; --canvas:#08090C; --surface:#14161B;
  --text:#F0F1F3; --subtle:#B9BEC7; --border:#FFFFFF14; --brand:#5558E8; --brand-hover:#6366F1; --warn:#FEC84B;
  --warn-bg:#FEC84B14; } }
* { box-sizing: border-box; }
body { margin:0; min-height:100dvh; display:flex; align-items:center; justify-content:center; padding:24px 16px;
  background:var(--canvas); color:var(--text); font:15px/22px "Inter", ui-sans-serif, system-ui, -apple-system,
  "Segoe UI", Roboto, sans-serif; }
.card { width:100%%; max-width:460px; background:var(--surface); border:1px solid var(--border); border-radius:16px;
  padding:28px; box-shadow:0 24px 48px -16px rgba(16,24,40,.18); }
h1 { font-size:20px; line-height:28px; margin:0 0 6px; }
p { margin:0 0 12px; color:var(--subtle); }
ul { margin:0 0 16px; padding-left:20px; color:var(--subtle); }
li { margin:4px 0; }
strong { color:var(--text); }
.who { padding:12px 14px; border-radius:10px; border:1px solid var(--border); margin:0 0 16px; }
.check { display:flex; gap:10px; align-items:flex-start; margin:0 0 8px; padding:12px 14px; border-radius:10px;
  background:var(--warn-bg); }
.check input { margin-top:4px; width:16px; height:16px; }
.check span { color:var(--text); }
.check small { display:block; color:var(--warn); }
.back { font-size:13px; margin:12px 0 18px; }
.row { display:flex; gap:10px; justify-content:flex-end; }
button { font-family:inherit; font-size:14px; line-height:20px; font-weight:600; padding:9px 16px; border-radius:10px; border:1px solid var(--border);
  background:var(--surface); color:var(--text); cursor:pointer; }
button.go { background:var(--brand); border-color:var(--brand); color:#fff; }
button.go:hover { background:var(--brand-hover); }
</style></head><body><main class="card">%(body)s</main></body></html>"""


def _page(title, body, status=200):
    return HTMLResponse(PAGE % {"title": html.escape(title), "body": body}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def _problem(text, status=400):
    return _page("Cannot connect", "<h1>This app cannot connect</h1><p>%s</p><p>Nothing was shared with it.</p>"
                 % html.escape(text), status)


# -------------------------------------------------------------- the router
def build_router(cursor):
    r = APIRouter()

    def client(cid):
        with cursor() as cur:
            cur.execute("select * from oauth_clients where client_id = %s", (str(cid or "")[:100],))
            row = cur.fetchone()
        return dict(row) if row else None

    @r.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    @r.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
    def protected_resource(request: Request):
        return {"resource": resource(request), "authorization_servers": [base_url(request)],
                "bearer_methods_supported": ["header"], "scopes_supported": [SCOPE],
                "resource_name": "TVF Lead Engine"}

    @r.get("/.well-known/oauth-authorization-server", include_in_schema=False)
    def authorization_server(request: Request):
        b = base_url(request)
        return {"issuer": b, "authorization_endpoint": b + "/oauth/authorize", "token_endpoint": b + "/oauth/token",
                "registration_endpoint": b + "/oauth/register", "scopes_supported": [SCOPE],
                "response_types_supported": ["code"], "response_modes_supported": ["query"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": list(METHODS),
                "code_challenge_methods_supported": ["S256"],
                "authorization_response_iss_parameter_supported": True}

    @r.post("/oauth/register", include_in_schema=False)
    async def register(request: Request):
        who = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or \
            (request.client.host if request.client else "?")
        with _LOCK:
            q, now = _REG[who], time.monotonic()
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= 30:
                return _err("invalid_client_metadata", "too many registrations from here; try again later", 429)
            q.append(now)
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            return _err("invalid_client_metadata", "the body must be JSON")
        if not isinstance(body, dict):
            return _err("invalid_client_metadata", "the body must be a JSON object")
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not uris or len(uris) > 10 or not all(isinstance(u, str) for u in uris):
            return _err("invalid_redirect_uri", "redirect_uris: one to ten URLs")
        bad = [u for u in uris if not redirect_ok(u)]
        if bad:
            return _err("invalid_redirect_uri", "not allowed as a redirect: %s" % bad[0][:200])
        grants = body.get("grant_types") or ["authorization_code", "refresh_token"]
        if not isinstance(grants, list) or not set(grants) <= {"authorization_code", "refresh_token"}:
            return _err("invalid_client_metadata", "grant_types: authorization_code and refresh_token only")
        if body.get("response_types") not in (None, ["code"]):
            return _err("invalid_client_metadata", "response_types: code only")
        method = body.get("token_endpoint_auth_method") or "none"
        if method not in METHODS:
            return _err("invalid_client_metadata", "token_endpoint_auth_method: one of %s" % ", ".join(METHODS))
        name = " ".join(str(body.get("client_name") or "An MCP client").split())[:80] or "An MCP client"
        cid = "tlc_" + secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32) if method != "none" else None
        with cursor() as cur:
            cur.execute("insert into oauth_clients (client_id, client_name, redirect_uris, secret_hash, auth_method)"
                        " values (%s, %s, %s, %s, %s)", (cid, name, uris, _h(secret) if secret else None, method))
        out = {"client_id": cid, "client_id_issued_at": int(time.time()), "client_name": name, "redirect_uris": uris,
               "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
               "token_endpoint_auth_method": method, "scope": SCOPE}
        if secret:
            out.update(client_secret=secret, client_secret_expires_at=0)
        return JSONResponse(out, status_code=201, headers={"Cache-Control": "no-store"})

    def _check(request, q):
        """-> (client, redirect_uri, error response or None) for an authorization request's parameters."""
        c = client(q.get("client_id"))
        if not c:
            return None, None, _problem("It is not registered with the Lead Engine. Remove the connector and add it "
                                        "again.")
        uri = q.get("redirect_uri") or (c["redirect_uris"][0] if len(c["redirect_uris"]) == 1 else None)
        if not redirect_matches(uri, c["redirect_uris"]):
            return c, None, _problem("It asked to be sent back to an address it did not register.")
        state = q.get("state")
        if q.get("response_type") != "code":
            return c, uri, _back(uri, error="unsupported_response_type", state=state, iss=base_url(request))
        if not q.get("code_challenge") or q.get("code_challenge_method") != "S256":
            return c, uri, _back(uri, error="invalid_request", error_description="PKCE with S256 is required",
                                 state=state, iss=base_url(request))
        res = (q.get("resource") or "").rstrip("/")
        if res and res not in (resource(request), base_url(request)):
            return c, uri, _back(uri, error="invalid_target", error_description="this server is %s" % resource(request),
                                 state=state, iss=base_url(request))
        return c, uri, None

    @r.get("/oauth/authorize", include_in_schema=False)
    def authorize(request: Request):
        q = dict(request.query_params)
        c, uri, bad = _check(request, q)
        if bad:
            return bad
        user = getattr(request.state, "user", None)
        if not user:
            nxt = "/oauth/authorize?" + urllib.parse.urlencode(q)
            return RedirectResponse("/login?next=" + urllib.parse.quote(nxt, safe=""), status_code=302)
        if getattr(request.state, "must_change", False):
            return _page("Finish setting up", "<h1>Finish setting up your account first</h1><p>Open the Lead Engine, "
                         "choose your own password and add your name and title. Then connect again.</p>")
        with cursor() as cur:
            cur.execute("select email, name, title from app_users where lower(email) = lower(%s)", (user,))
            me = cur.fetchone() or {"email": user, "name": None, "title": None}
        expires = int(time.time()) + FORM_SECONDS
        fields = {"client_id": c["client_id"], "redirect_uri": uri, "state": q.get("state") or "",
                  "code_challenge": q["code_challenge"], "resource": (q.get("resource") or "").rstrip("/"),
                  "expires": str(expires)}
        fields["sig"] = _sign(me["email"].lower(), *[fields[k] for k in ("client_id", "redirect_uri", "state",
                                                                          "code_challenge", "resource", "expires")])
        hidden = "".join('<input type="hidden" name="%s" value="%s">' % (k, html.escape(v, quote=True))
                         for k, v in fields.items())
        host = urllib.parse.urlsplit(uri)
        where = host.hostname or host.scheme
        body = (
            "<h1>Allow %(app)s to use the Lead Engine?</h1>"
            "<div class=\"who\">It will work as <strong>%(name)s</strong> (%(email)s), on every project you can see.</div>"
            "<p>It will be able to:</p><ul><li>read leads and emails</li><li>add leads, with draft emails signed by "
            "you</li><li>shortlist and reject leads, edit and withdraw drafts</li></ul>"
            "<form method=\"post\" action=\"/oauth/authorize\">%(hidden)s"
            "<label class=\"check\"><input type=\"checkbox\" name=\"can_approve\" value=\"1\" checked>"
            "<span>Also approve emails<small>An approved email is sent, from your Gmail, signed by you.</small></span>"
            "</label>"
            "<p class=\"back\">Afterwards you go back to <strong>%(where)s</strong>. You can disconnect it at any time "
            "in the Lead Engine (account menu, API and MCP).</p>"
            "<div class=\"row\"><button type=\"submit\" name=\"decision\" value=\"deny\">Cancel</button>"
            "<button class=\"go\" type=\"submit\" name=\"decision\" value=\"allow\">Allow</button></div></form>"
        ) % {"app": html.escape(c["client_name"]), "name": html.escape(me["name"] or me["email"]),
             "email": html.escape(me["email"]), "hidden": hidden, "where": html.escape(where)}
        return _page("Allow access", body)

    @r.post("/oauth/authorize", include_in_schema=False)
    async def consent(request: Request):
        raw = (await request.body()).decode("utf-8", "replace")
        f = {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
        user = getattr(request.state, "user", None)
        if not user:
            return _problem("You are not signed in to the Lead Engine any more. Start again from the app.", 401)
        c = client(f.get("client_id"))
        uri = f.get("redirect_uri") or ""
        if not c or not redirect_matches(uri, c["redirect_uris"]):
            return _problem("The request was not one this page made.")
        try:
            fresh = int(f.get("expires") or 0) > time.time()
        except ValueError:
            fresh = False
        want = _sign(user.lower(), *[f.get(k) or "" for k in ("client_id", "redirect_uri", "state", "code_challenge",
                                                                "resource", "expires")])
        if not fresh or not hmac.compare_digest(want, f.get("sig") or ""):
            return _problem("This page was open too long, or was not made for you. Start again from the app.")
        state = f.get("state") or None
        if f.get("decision") != "allow":
            return _back(uri, error="access_denied", state=state, iss=base_url(request))
        code = secrets.token_urlsafe(32)
        with cursor() as cur:
            cur.execute("select email from app_users where lower(email) = lower(%s)", (user,))
            me = cur.fetchone()
            cur.execute("insert into oauth_grants (kind, token_hash, client_id, user_email, redirect_uri, code_challenge,"
                        " resource, can_approve, expires_at) values ('code', %s, %s, %s, %s, %s, %s, %s,"
                        " now() + make_interval(secs => %s))",
                        (_h(code), c["client_id"], me["email"], uri, f.get("code_challenge"), f.get("resource") or None,
                         f.get("can_approve") == "1", CODE_SECONDS))
        return _back(uri, code=code, state=state, iss=base_url(request))

    def _issue(cur, c, user, can_approve, key_id=None):
        """A new access token (an api_keys row, or the same row renewed) and a new refresh token."""
        import api_v1
        access = api_v1.new_key()
        if key_id:
            cur.execute("select key_hash from api_keys where id = %s", (key_id,))
            old = cur.fetchone()
            cur.execute("update api_keys set key_hash = %s, prefix = %s, expires_at = now() + make_interval(secs => %s)"
                        " where id = %s", (api_v1.hash_key(access), access[:10], ACCESS_SECONDS, key_id))
            if old:
                api_v1._KEYS.pop(old["key_hash"], None)
        else:
            cur.execute("insert into api_keys (user_email, name, prefix, key_hash, can_approve, expires_at, client_id)"
                        " values (%s, %s, %s, %s, %s, now() + make_interval(secs => %s), %s) returning id",
                        (user, c["client_name"][:60], access[:10], api_v1.hash_key(access), can_approve,
                         ACCESS_SECONDS, c["client_id"]))
            key_id = cur.fetchone()["id"]
        refresh = secrets.token_urlsafe(40)
        cur.execute("insert into oauth_grants (kind, token_hash, client_id, user_email, can_approve, key_id, expires_at)"
                    " values ('refresh', %s, %s, %s, %s, %s, now() + make_interval(days => %s))",
                    (_h(refresh), c["client_id"], user, can_approve, key_id, REFRESH_DAYS))
        cur.execute("update oauth_clients set last_used_at = now() where client_id = %s", (c["client_id"],))
        return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS,
                             "refresh_token": refresh, "scope": SCOPE},
                            headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @r.post("/oauth/token", include_in_schema=False)
    async def token(request: Request):
        raw = await request.body()
        ctype = request.headers.get("content-type", "")
        try:
            if "json" in ctype:
                f = json.loads(raw or b"{}")
                f = f if isinstance(f, dict) else {}
            else:
                f = {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace")).items()}
        except ValueError:
            return _err("invalid_request", "the body must be form-encoded")
        cid, secret = f.get("client_id"), f.get("client_secret")
        auth = request.headers.get("authorization") or ""
        if auth[:6].lower() == "basic ":
            try:
                pair = base64.b64decode(auth[6:].strip()).decode("utf-8")
                cid, secret = [urllib.parse.unquote(x) for x in pair.split(":", 1)]
            except (ValueError, UnicodeDecodeError):
                return _err("invalid_client", "unreadable Basic credentials", 401)
        c = client(cid)
        if not c:
            return _err("invalid_client", "unknown client", 401)
        if c["auth_method"] != "none" and not (secret and c["secret_hash"]
                                               and hmac.compare_digest(_h(secret), c["secret_hash"])):
            return _err("invalid_client", "the client's secret did not match", 401)
        grant = f.get("grant_type")
        with cursor() as cur:
            if grant == "authorization_code":
                cur.execute("select * from oauth_grants where kind = 'code' and token_hash = %s for update",
                            (_h(f.get("code") or ""),))
                g = cur.fetchone()
                if not g or g["used_at"] or g["client_id"] != c["client_id"]:
                    return _err("invalid_grant", "unknown or already used code")
                cur.execute("update oauth_grants set used_at = now() where id = %s", (g["id"],))
                cur.execute("select now() > %s as late", (g["expires_at"],))
                if cur.fetchone()["late"]:
                    return _err("invalid_grant", "the code has expired")
                if f.get("redirect_uri") and f["redirect_uri"] != g["redirect_uri"]:
                    return _err("invalid_grant", "redirect_uri does not match the authorization request")
                verifier = f.get("code_verifier") or ""
                expect = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "replace")).digest()) \
                    .decode().rstrip("=")
                if not (43 <= len(verifier) <= 128) or not hmac.compare_digest(expect, g["code_challenge"] or ""):
                    return _err("invalid_grant", "the PKCE code_verifier does not match")
                return _issue(cur, c, g["user_email"], g["can_approve"])
            if grant == "refresh_token":
                cur.execute("select g.*, k.revoked_at from oauth_grants g left join api_keys k on k.id = g.key_id"
                            " where g.kind = 'refresh' and g.token_hash = %s for update of g",
                            (_h(f.get("refresh_token") or ""),))
                g = cur.fetchone()
                if not g or g["used_at"] or g["client_id"] != c["client_id"] or g["revoked_at"] or not g["key_id"]:
                    return _err("invalid_grant", "unknown, used or revoked refresh token")
                cur.execute("select now() > %s as late", (g["expires_at"],))
                if cur.fetchone()["late"]:
                    return _err("invalid_grant", "the refresh token has expired")
                cur.execute("update oauth_grants set used_at = now() where id = %s", (g["id"],))
                return _issue(cur, c, g["user_email"], g["can_approve"], key_id=g["key_id"])
        return _err("unsupported_grant_type", "authorization_code or refresh_token")

    return r
