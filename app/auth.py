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
  * login rate limiting: 10 failed attempts per 5 minutes, counted per
    visitor address AND per account, in memory -- enough to make online
    guessing pointless against bcrypt (see _attempt_keys for which address).
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


def _attempt_keys(request, email):
    """What a failed login counts against. The FIRST hop of X-Forwarded-For is whatever the client
    wrote, and keying on it alone let a made-up header reset the count on every guess (found
    2026-09-21). The LAST hop is the address the nearest proxy itself saw (Render appends it, Caddy
    writes only it), which a client cannot choose; the account is counted too, so neither a forged
    header nor a pool of addresses buys more than ten guesses at one password in five minutes."""
    fwd = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    peer = request.client.host if request.client else "?"
    keys = {"ip:" + (fwd[-1] if fwd else peer), "ip:" + (fwd[0] if fwd else peer)}
    if email:
        keys.add("email:" + email)
    return keys


def _rate_limited(keys):
    now = time.time()
    if len(_ATTEMPTS) > 5000:                    # forget keys with nothing recent, so the table stays small
        for k in [k for k, v in _ATTEMPTS.items() if not any(now - t < 300 for t in v)]:
            del _ATTEMPTS[k]
    limited = False
    for key in keys:
        hits = [t for t in _ATTEMPTS.get(key, []) if now - t < 300]
        _ATTEMPTS[key] = hits
        limited = limited or len(hits) >= 10
    return limited


def _record_attempt(keys):
    for key in keys:
        _ATTEMPTS.setdefault(key, []).append(time.time())


def build_router(cursor):
    """cursor is the app's DB contextmanager; keeps auth free of its own pool."""
    r = APIRouter()

    def user_count():
        with cursor() as cur:
            cur.execute("select count(*) as n from app_users")
            return cur.fetchone()["n"]

    def get_user(email):
        with cursor() as cur:
            cur.execute("select email, password_hash, role, name, title, must_change_password from app_users"
                        " where lower(email) = lower(%s)", (email,))
            return cur.fetchone()

    @r.get("/api/auth/state")
    def state(request: Request):
        user = getattr(request.state, "user", None)
        out = {"needs_setup": user_count() == 0, "authed": user is not None, "user": user,
               # the login page offers the public demo (/demo, app/main.py) unless DEMO_ENABLED=0
               "demo": os.environ.get("DEMO_ENABLED", "1") != "0"}
        if user:
            # who is signed in, as the page greets them and as their emails are signed (owner, 2026-09-26:
            # one account per person); a starting password handed out by the owner must be replaced first
            u = get_user(user) or {}
            out.update(name=u.get("name") or "", title=u.get("title") or "",
                       must_change_password=bool(u.get("must_change_password")))
        return out

    def _signed_in(request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(401, "not signed in")
        return user

    @r.post("/api/auth/password")
    def change_password(request: Request, body: dict = Body(...)):
        """Your own password, in place of the current one. The first sign-in with a starting password
        the owner handed out comes here before anything else (the app refuses every other call until
        then). Every other session of this person ends: sessions are tied to the password."""
        user = _signed_in(request)
        current = (body or {}).get("current") or ""
        new = (body or {}).get("new") or ""
        row = get_user(user)
        if not row or not bcrypt.checkpw(current.encode(), row["password_hash"].encode()):
            raise HTTPException(400, "The current password is not right.")
        if len(new) < 10:
            raise HTTPException(400, "Choose a password of at least 10 characters.")
        if new == current:
            raise HTTPException(400, "Choose a password different from the one you were given.")
        if new.strip().lower() == user.lower():
            raise HTTPException(400, "Your password cannot be your email address.")
        pw_hash = bcrypt.hashpw(new.encode(), bcrypt.gensalt(12)).decode()
        with cursor() as cur:
            cur.execute("update app_users set password_hash = %s, must_change_password = false,"
                        " password_changed_at = now() where lower(email) = lower(%s)", (pw_hash, user))
        resp = Response(status_code=200, content='{"ok": true}', media_type="application/json")
        _set_cookie(resp, request, make_cookie(row["email"], pw_hash))   # this session carries on
        return resp

    @r.post("/api/auth/profile")
    def profile(request: Request, body: dict = Body(...)):
        """Your name and title: the sign-off on every email you approve, which goes out from your Gmail."""
        user = _signed_in(request)
        name = " ".join(str((body or {}).get("name") or "").split())
        title = " ".join(str((body or {}).get("title") or "").split())
        if not name or len(name) > 80:
            raise HTTPException(400, "Your name, as it should read under your emails (up to 80 characters).")
        if not title or len(title) > 80:
            raise HTTPException(400, "Your title, as it should read under your name (up to 80 characters).")
        if "{{" in name + title or "SET_ME" in name + title:
            raise HTTPException(400, "Write your name and title as they should read.")
        with cursor() as cur:
            cur.execute("update app_users set name = %s, title = %s where lower(email) = lower(%s)", (name, title, user))
        return {"ok": True, "name": name, "title": title}

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
        # Behind a proxy every request arrives from the proxy's own address, so
        # counting that would lock the whole team out after ten bad tries: the
        # visitor comes from X-Forwarded-For, read as _attempt_keys explains.
        email = ((body or {}).get("email") or "").strip().lower()
        password = (body or {}).get("password") or ""
        keys = _attempt_keys(request, email)
        if _rate_limited(keys):
            raise HTTPException(429, "too many attempts -- wait five minutes")
        user = get_user(email)
        # bcrypt against a constant hash when the user is unknown, so the
        # response time does not reveal which emails exist
        target = (user["password_hash"] if user else
                  "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7ZBpUFoV7c6zZ7bIOZK9CmO6GZuKZfa")
        ok = bcrypt.checkpw(password.encode(), target.encode()) and user is not None
        if not ok:
            _record_attempt(keys)
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
