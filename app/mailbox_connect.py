#!/usr/bin/env python3
"""mailbox_connect.py -- the sending addresses behind each login (owner, 2026-09-26).

    GET /api/me/mailboxes          the addresses the signed-in person's emails go out from, with today's
                                   use of each one's limit (read-only: the owner links them)
    GET /api/mailboxes/server-key  this server's public key (public): what the owner's laptop seals a
                                   Gmail sign-in with, so that only this server can read it

One login per person; an email a person approves goes out from the address the owner linked to them
(tools/outreach.py, send_from "approver"). The owner links it on the laptop -- "I will manually connect
the email id they will use to send" -- with `python tools/users.py gmail <person>`: Google's own sign-in
opens in a browser, the owner signs in to the sending address, and the sign-in is sealed for this
server and stored (tools/mailbox_store.py). Nobody else connects anything, and nothing is shown to a
page but addresses and counts.
"""
import os
import sys

from fastapi import APIRouter, HTTPException, Request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if os.path.join(REPO, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(REPO, "tools"))
import mailbox_store as store  # noqa: E402

SERVER_KEY_PATH = "/api/mailboxes/server-key"


def build_router(cursor):
    r = APIRouter()

    @r.get(SERVER_KEY_PATH)
    def server_key():
        # a public key: nothing secret in it, and the laptop fetches it over HTTPS from this server
        return {"x25519": store.server_public_key()}

    @r.get("/api/me/mailboxes")
    def mine(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(401, "not signed in")
        with cursor() as cur:
            rows = store.mailboxes(cur, user_email=user)
        keep = ("address", "daily_cap", "sent_today", "out_today", "remaining", "usable", "last_error")
        return {"mailboxes": [{k: b.get(k) for k in keep} for b in rows]}

    return r
