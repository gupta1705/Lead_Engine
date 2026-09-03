#!/usr/bin/env python3
"""auth.py -- session auth for the review UI, built for the public step.

THE THREAT MODEL, sized honestly. This protects an internal BD tool holding
contact details and email drafts -- valuable to a spammer, not to a nation
state. The right defence at that size is boring, proven mechanics with no
cleverness:

  * bcrypt for passwords (cost 12), via the maintained `bcrypt` package
  * stateless signed session cookies: email|expiry|HMAC-SHA256(secret).
    The HMAC also covers a fingerprint of the user's password hash, so
    CHANGING A PASSWORD INVALIDATES EVERY OUTSTANDING SESSION for that user
    without needing a session table.
  * httpOnly + SameSite=Lax cookies; Secure is added automatically when the
    request arrived over HTTPS (the Caddy/cloud step), never on plain
    localhost where it would break login entirely.
  * login rate limiting: 10 attempts per IP per 5 minutes, in memory --
    enough to make online guessing pointless against bcrypt.
  * FIRST-RUN SETUP: while app_users is empty, /login offers "create the
    owner account" and the setup endpoint works exactly once. The owner
    types their own password into their own app; no default credential ever
    exists. The race (two setups at the same instant) is settled by the
    unique index on email plus a count check inside one transaction.

CSRF: state-changing endpoints only accept JSON bodies, which cross-site
forms cannot produce, and SameSite=Lax keeps the cookie off cross-site POSTs
in every current browser. Belt and braces, both free.
"""
import hashlib
import hmac
import io
import os
import time
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Body, HTTPException, Request, Response

REPO = Path(__file__).resolve().parent.parent
COOKIE = "tvf_session"
SESSION_DAYS = 7
_ATTEMPTS = {}          # ip -> [timestamps]; pruned on use


def _secret():
    v = os.environ.get("SESSION_SECRET")
    if v:
        return v.encode()
    envfile = REPO / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith("SESSION_SECRET="):
                return line.split("=", 1)[1].strip().encode()
    raise RuntimeError("SESSION_SECRET is not set -- generate one into .env")


def _sign(email, expiry, pw_fingerprint):
    msg = ("%s|%d|%s" % (email, expiry, pw_fingerprint)).encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def _fingerprint(password_hash):
    # ties the session to the CURRENT password without leaking hash material
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def make_cookie(email, password_hash):
    expiry = int(time.time()) + SESSION_DAYS * 86400
    fp = _fingerprint(password_hash)
    return "%s|%d|%s|%s" % (email, expiry, fp, _sign(email, expiry, fp))


def parse_cookie(value, lookup_hash):
    """-> email when the cookie is valid, else None. lookup_hash(email) must
    return the stored password hash or None; sessions die with the password."""
    try:
        email, expiry_s, fp, sig = value.split("|", 3)
        expiry = int(expiry_s)
    except (ValueError, AttributeError):
        return None
    if time.time() > expiry:
        return None
    if not hmac.compare_digest(sig, _sign(email, expiry, fp)):
        return None
    stored = lookup_hash(email)
    if not stored or not hmac.compare_digest(fp, _fingerprint(stored)):
        return None
    return email


def _rate_limited(ip):
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(ip, []) if now - t < 300]
    _ATTEMPTS[ip] = hits
    return len(hits) >= 10


def _record_attempt(ip):
    _ATTEMPTS.setdefault(ip, []).append(time.time())


def build_router(cursor):
    """cursor is the app's DB contextmanager; keeps auth free of its own pool."""
    r = APIRouter()

    def user_count():
        with cursor() as cur:
            cur.execute("select count(*) as n from app_users")
            return cur.fetchone()["n"]

    def get_user(email):
        with cursor() as cur:
            cur.execute("select email, password_hash, role from app_users"
                        " where lower(email) = lower(%s)", (email,))
            return cur.fetchone()

    @r.get("/api/auth/state")
    def state(request: Request):
        return {"needs_setup": user_count() == 0,
                "authed": getattr(request.state, "user", None) is not None,
                "user": getattr(request.state, "user", None)}

    @r.post("/api/auth/setup")
    def setup(request: Request, body: dict = Body(...)):
        """Create the owner account. Works exactly once, while no users exist."""
        email = ((body or {}).get("email") or "").strip().lower()
        password = (body or {}).get("password") or ""
        if "@" not in email or len(password) < 10:
            raise HTTPException(400, "valid email and a password of 10+ characters")
        with cursor() as cur:
            cur.execute("select count(*) as n from app_users")
            if cur.fetchone()["n"] > 0:
                raise HTTPException(409, "setup already completed")
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()
            cur.execute("insert into app_users (email, password_hash, role)"
                        " values (%s, %s, 'owner')", (email, pw_hash))
        resp = Response(status_code=200,
                        content='{"ok": true}', media_type="application/json")
        _set_cookie(resp, request, make_cookie(email, pw_hash))
        return resp

    @r.post("/api/auth/login")
    def login(request: Request, body: dict = Body(...)):
        # Behind Caddy every request arrives from the proxy's address; the
        # first hop of X-Forwarded-For is the real visitor, and rate-limiting
        # on the proxy IP would lock the whole team out after ten bad tries.
        fwd = request.headers.get("x-forwarded-for", "")
        ip = (fwd.split(",")[0].strip() if fwd else
              (request.client.host if request.client else "?"))
        if _rate_limited(ip):
            raise HTTPException(429, "too many attempts -- wait five minutes")
        email = ((body or {}).get("email") or "").strip().lower()
        password = (body or {}).get("password") or ""
        user = get_user(email)
        # bcrypt against a constant hash when the user is unknown, so the
        # response time does not reveal which emails exist
        target = (user["password_hash"] if user else
                  "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZBpUFoV7c6zZ7bIOZK9CmO6GZuKZfa")
        ok = bcrypt.checkpw(password.encode(), target.encode()) and user is not None
        if not ok:
            _record_attempt(ip)
            raise HTTPException(401, "wrong email or password")
        with cursor() as cur:
            cur.execute("update app_users set last_login_at = now()"
                        " where lower(email) = lower(%s)", (email,))
        resp = Response(status_code=200,
                        content='{"ok": true}', media_type="application/json")
        _set_cookie(resp, request, make_cookie(email, user["password_hash"]))
        return resp

    @r.post("/api/auth/logout")
    def logout(request: Request):
        resp = Response(status_code=200,
                        content='{"ok": true}', media_type="application/json")
        resp.delete_cookie(COOKIE, path="/")
        return resp

    return r, get_user


def _set_cookie(resp, request, value):
    secure = request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, value, max_age=SESSION_DAYS * 86400, path="/",
                    httponly=True, samesite="lax", secure=secure)
