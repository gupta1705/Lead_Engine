#!/usr/bin/env python3
"""mailbox_connect.py -- each person connects the Gmail they send from, inside the app (owner, 2026-10-14:
"a feature which allows users to link a gmail account to send emails in their own without my intervention").

    GET    /api/mailboxes/connect      -> Google's own sign-in, for the person signed in here
    GET    /api/mailboxes/callback     <- Google sends them back: the address is linked to their login
    GET    /api/me/mailboxes           their addresses, with today's use of each one's limit
    DELETE /api/mailboxes/{id}         disconnect one of their own (Google's permission is withdrawn too)
    GET    /api/mailboxes/server-key   this server's public key (public): what `tools/users.py gmail` seals a
                                       sign-in with on the owner's laptop, so that only this server reads it

One login per person, each with one or more sending addresses; an email a person approves goes out from their
own address (tools/outreach.py, send_from "approver"), up to its daily limit. Nobody's password is seen or kept:
Google shows the person what is being allowed (reading, sending and managing mail for that one address) and
hands back a lasting sign-in, which is stored encrypted (tools/mailbox_store.py). The owner can still link an
address for someone from the laptop (`users.py gmail <login>`); both end in the same row.

Needs a Google OAuth client of type "Web application" whose redirect URI is this server's
/api/mailboxes/callback, in GOOGLE_OAUTH_WEB_CLIENT_ID / GOOGLE_OAUTH_WEB_CLIENT_SECRET. The Desktop client the
laptop uses cannot redirect to a website; without the web one, Connect says so and nothing else changes.

The link Google returns through carries a state signed for the person who asked, for ten minutes: nobody can
attach their Gmail to someone else's login, or finish someone else's sign-in. An address already linked to
another person is refused (one address, one person), and Google's permission for it is withdrawn at once.
"""
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.join(REPO, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "tools"))
import mailbox_store as store  # noqa: E402

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = store.TOKEN_URI
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SEND_AS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/settings/sendAs"   # its "Send mail as" aliases (sql/36)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
STATE_SECONDS = 600
CALLBACK_PATH = "/api/mailboxes/callback"
SERVER_KEY_PATH = "/api/mailboxes/server-key"


def _env(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    path = os.path.join(REPO, ".env")
    if os.path.exists(path):
        for line in io.open(path, encoding="utf-8"):
            if line.strip().startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    return None


def web_client():
    """(client_id, client_secret) of the Web application client, or None."""
    cid, sec = _env("GOOGLE_OAUTH_WEB_CLIENT_ID"), _env("GOOGLE_OAUTH_WEB_CLIENT_SECRET")
    return (cid, sec) if cid and sec else None


def redirect_uri(request):
    """Where Google sends people back. PUBLIC_BASE_URL when set; otherwise this request's own host -- Google
    compares it with the URIs registered on the client, so a made-up Host only fails there."""
    base = _env("PUBLIC_BASE_URL")
    if not base:
        host = request.headers.get("host", "")
        if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", host):
            raise HTTPException(400, "bad Host header")
        proto = "https" if request.headers.get("x-forwarded-proto") == "https" else request.url.scheme
        base = "%s://%s" % (proto, host)
    return base.rstrip("/") + CALLBACK_PATH


def _key():
    import auth
    return auth._secret()


def sign_state(email, now=None):
    expiry = int((now or time.time()) + STATE_SECONDS)
    nonce = secrets.token_urlsafe(12)
    msg = "mbx|%s|%d|%s" % (email.lower(), expiry, nonce)
    sig = hmac.new(_key(), msg.encode(), hashlib.sha256).hexdigest()
    return "%d.%s.%s" % (expiry, nonce, sig)


def verify_state(state, email, now=None):
    try:
        expiry_s, nonce, sig = str(state or "").split(".", 2)
        expiry = int(expiry_s)
    except ValueError:
        return False
    if (now or time.time()) > expiry:
        return False
    msg = "mbx|%s|%d|%s" % ((email or "").lower(), expiry, nonce)
    want = hmac.new(_key(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, want)


def _post_form(url, fields, timeout=20):
    """-> (status, json). Google answers errors with a JSON body too."""
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


def _get_json(url, access_token, timeout=20):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + access_token})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


def _revoke(token):
    """Best effort: withdraw Google's permission for a sign-in this server is not keeping."""
    try:
        _post_form(REVOKE_URL, {"token": token}, timeout=10)
    except Exception:
        pass


def _back(kind, text):
    """Back to the Outreach page, which says how it went."""
    return RedirectResponse("/?" + urllib.parse.urlencode({"gmail": kind, "msg": str(text)[:200]}) + "#outreach",
                            status_code=302)


def build_router(cursor):
    r = APIRouter()

    def me(request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(401, "not signed in")
        return user

    @r.get(SERVER_KEY_PATH)
    def server_key():
        # a public key: nothing secret in it, and the laptop fetches it over HTTPS from this server
        return {"x25519": store.server_public_key()}

    @r.get("/api/mailboxes/connect")
    def connect(request: Request):
        user = me(request)
        client = web_client()
        if not client:
            return _back("error", "Connecting a Gmail from the app is not switched on yet: the owner adds a Google "
                                  "'Web application' client to the server first.")
        params = {"client_id": client[0], "redirect_uri": redirect_uri(request), "response_type": "code",
                  "scope": store.GMAIL_SCOPE, "access_type": "offline", "prompt": "consent select_account",
                  "include_granted_scopes": "true", "state": sign_state(user)}
        return RedirectResponse(AUTH_URL + "?" + urllib.parse.urlencode(params), status_code=302)

    @r.get(CALLBACK_PATH)
    def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        user = me(request)
        if error:
            return _back("error", "Google did not connect it (%s). Nothing was changed." % error)
        if not verify_state(state, user):
            return _back("error", "That sign-in link expired or was started by someone else. Try Connect again.")
        client = web_client()
        if not client or not code:
            return _back("error", "Google did not send the sign-in back. Try Connect again.")
        status, tok = _post_form(TOKEN_URL, {"code": code, "client_id": client[0], "client_secret": client[1],
                                             "redirect_uri": redirect_uri(request), "grant_type": "authorization_code"})
        if status != 200 or not tok.get("access_token"):
            return _back("error", "Google refused the sign-in (%s). Try Connect again."
                         % (tok.get("error_description") or tok.get("error") or status))
        if store.GMAIL_SCOPE not in str(tok.get("scope") or "").split():
            if tok.get("refresh_token"):
                _revoke(tok["refresh_token"])
            return _back("error", "Gmail was not allowed on Google's screen. Try again and leave the Gmail box ticked.")
        if not tok.get("refresh_token"):
            return _back("error", "Google did not grant lasting access. Try Connect again.")
        status, prof = _get_json(PROFILE_URL, tok["access_token"])
        address = str(prof.get("emailAddress") or "").strip().lower()
        if status != 200 or "@" not in address:
            _revoke(tok["refresh_token"])
            return _back("error", "Could not read which Gmail address this is. Try Connect again.")
        # its "Send mail as" aliases (owner, 2026-10-15: the LCX address is one, inside the TVF account): read now,
        # so Your Gmail shows them at once; one that cannot be read is read again at the next send
        sa_status, sa = _get_json(SEND_AS_URL, tok["access_token"])
        send_as = store.aliases_from(sa.get("sendAs")) if sa_status == 200 else None
        creds = {"refresh_token": tok["refresh_token"], "token_uri": TOKEN_URL, "client_id": client[0],
                 "client_secret": client[1], "scopes": [store.GMAIL_SCOPE],
                 "connected_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            with cursor() as cur:
                store.save(cur, user, address, creds, send_as=send_as)
        except ValueError:
            _revoke(tok["refresh_token"])                  # not kept, so not left granted either
            return _back("error", "%s is already linked to someone else's login, so it was not connected. Ask the "
                                  "owner if it should move to you." % address)
        also = [a["address"] for a in send_as or []]
        return _back("connected", address + (" (it also sends as %s)" % ", ".join(also) if also else ""))

    @r.get("/api/me/mailboxes")
    def mine(request: Request):
        user = me(request)
        with cursor() as cur:
            rows = store.mailboxes(cur, user_email=user)
        keep = ("id", "address", "daily_cap", "sent_today", "out_today", "remaining", "usable", "last_error", "send_as")
        out = []
        for b in rows:
            row = {k: b.get(k) for k in keep}
            row["connected_at"] = b["connected_at"].isoformat() if b.get("connected_at") else None
            out.append(row)
        return {"mailboxes": out, "web_connect": bool(web_client())}

    @r.delete("/api/mailboxes/{mailbox_id}")
    def disconnect(mailbox_id: str, request: Request):
        user = me(request)
        if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", mailbox_id or ""):
            raise HTTPException(404, "not one of your sending addresses")
        with cursor() as cur:
            gone = store.remove_own(cur, mailbox_id, user)
        if not gone:
            raise HTTPException(404, "not one of your sending addresses")
        creds = store.decrypt(gone.get("token_enc"))
        if creds and creds.get("refresh_token"):
            _revoke(creds["refresh_token"])
        return {"ok": True, "address": gone["address"]}

    return r
