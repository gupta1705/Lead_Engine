#!/usr/bin/env python3
"""mailbox_store.py -- the Gmail addresses people connect in the app (owner, 2026-09-26).

One login per person, each linked to one or more Gmail addresses, each address with its own
daily limit (35). The owner links them -- "I will manually connect the email id they will use to
send" -- on the laptop: `python tools/users.py gmail <person>` runs Google's own sign-in in a
browser, and the lasting sign-in Google hands back is kept here, one row per address in
user_mailboxes (sql/30).

THE SIGN-IN ONLY THE SERVER CAN READ. The laptop seals it with the server's public key (seal());
after its first refresh the server keeps it encrypted with a key from its own SESSION_SECRET
(encrypt()). Either way the database on its own cannot send mail as anyone: a leaked dump or a
stray query result is useless without the server's secret, which the laptop does not have either.

Shared by the app (status, the Outreach counters), tools/users.py (linking) and tools/outreach.py
(send, pull). Works with the app's dict cursor and the tools' tuple cursor alike.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_CAP = 35


def _secret():
    v = os.environ.get("SESSION_SECRET")
    if v:
        return v.encode()
    envfile = ROOT / ".env"
    if envfile.exists():
        for line in io.open(envfile, encoding="utf-8"):
            if line.strip().startswith("SESSION_SECRET="):
                return line.split("=", 1)[1].strip().strip('"').strip("'").encode()
    raise RuntimeError("SESSION_SECRET is not set")


def _fernet(secret=None):
    from cryptography.fernet import Fernet
    raw = secret if isinstance(secret, bytes) else (secret.encode() if secret else _secret())
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"tvf-mailbox-token:" + raw).digest()))


def encrypt(creds, secret=None):
    """Google's authorized-user JSON (dict) -> the text kept in user_mailboxes.token_enc."""
    return _fernet(secret).encrypt(json.dumps(creds).encode()).decode()


# SEALED FOR THE SERVER (owner, 2026-09-26: "I will manually connect the email id they will use to
# send"). The owner connects each person's sending address on the laptop (tools/users.py gmail), whose
# .env has a different SESSION_SECRET from Render's, so the laptop cannot use the key above. It seals
# the sign-in for the server instead: a one-off X25519 key agreed with the server's public key, HKDF to
# a Fernet key -- the construction of a libsodium sealed box, from the cryptography package's own
# primitives. Only the server, whose private key comes from its SESSION_SECRET, can open it. The laptop
# gets the public key from the live site over HTTPS (/api/mailboxes/server-key).
SEALED = "x25519:"


def _server_private(secret=None):
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    raw = secret if isinstance(secret, bytes) else (secret.encode() if secret else _secret())
    return X25519PrivateKey.from_private_bytes(hashlib.sha256(b"tvf-mailbox-x25519:" + raw).digest())


def _raw(public_key):
    from cryptography.hazmat.primitives import serialization
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def server_public_key(secret=None):
    """This server's public key, base64: what the laptop seals a sign-in with."""
    return base64.b64encode(_raw(_server_private(secret).public_key())).decode()


def _sealing_fernet(shared, one_off_public, server_public):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=b"tvf-mailbox-seal" + one_off_public + server_public).derive(shared)
    return Fernet(base64.urlsafe_b64encode(key))


def seal(creds, server_public_b64):
    """The sign-in, readable only by the server whose public key this is -> token_enc text."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    server_public = base64.b64decode(server_public_b64)
    one_off = X25519PrivateKey.generate()
    shared = one_off.exchange(X25519PublicKey.from_public_bytes(server_public))
    one_off_public = _raw(one_off.public_key())
    box = _sealing_fernet(shared, one_off_public, server_public).encrypt(json.dumps(creds).encode()).decode()
    return SEALED + base64.urlsafe_b64encode(one_off_public).decode() + ":" + box


def decrypt(token_enc, secret=None):
    """-> the authorized-user dict, or None when it cannot be read (another server's key, damage).
    Reads both forms: sealed on the laptop for this server, or encrypted here after a refresh."""
    from cryptography.fernet import InvalidToken
    text = str(token_enc or "")
    try:
        if text.startswith(SEALED):
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
            one_off_b64, box = text[len(SEALED):].split(":", 1)
            one_off_public = base64.urlsafe_b64decode(one_off_b64)
            private = _server_private(secret)
            shared = private.exchange(X25519PublicKey.from_public_bytes(one_off_public))
            return json.loads(_sealing_fernet(shared, one_off_public, _raw(private.public_key())).decrypt(box.encode()))
        return json.loads(_fernet(secret).decrypt(text.encode()).decode())
    except (InvalidToken, ValueError, TypeError):
        return None


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(r) if isinstance(r, dict) else dict(zip(cols, r)) for r in cur.fetchall()]


# Sent today per address, across every project: a mailbox's limit is the mailbox's, whatever it sent
# for. "out" also counts a send in flight and one whose outcome is unknown, which may have gone.
# The day is the database's, UTC, like every other count here (midnight UTC is 05:30 in India).
USAGE_SQL = """
select lower(sender_address) as address,
       count(*) filter (where status = 'sent' and sent_at::date = current_date) as sent_today,
       count(*) filter (where status in ('sent', 'sending', 'send_unknown')
                          and coalesce(sent_at, updated_at)::date = current_date) as out_today,
       max(sent_at) as last_sent
from outreach
where direction = 'outbound' and sender_address is not null
group by 1
"""

# what goes out today from one address, counted inside the send's claim (tools/outreach.py)
OUT_TODAY_FOR_SQL = """
select count(*) from outreach
where direction = 'outbound' and lower(sender_address) = lower(%s)
  and status in ('sent', 'sending', 'send_unknown') and coalesce(sent_at, updated_at)::date = current_date
"""


def usage(cur):
    cur.execute(USAGE_SQL)
    return {r["address"]: r for r in _rows(cur)}


def mailboxes(cur, user_email=None, with_token=False):
    """Every connected address (or one person's), with today's use:
    [{id, user_email, address, daily_cap, enabled, connected_at, last_error, last_error_at,
      sent_today, out_today, remaining, last_sent, usable}] -- usable: enabled and no sign-in error.
    with_token adds token_enc, for the sender; nothing that reaches a page ever carries it."""
    sql = ("select id, user_email, address, daily_cap, enabled, connected_at, last_error, last_error_at"
           + (", token_enc" if with_token else "") + " from user_mailboxes"
           + (" where lower(user_email) = lower(%s)" if user_email else "") + " order by lower(user_email), connected_at")
    cur.execute(sql, (user_email,) if user_email else None)
    rows = _rows(cur)
    use = usage(cur) if rows else {}
    for r in rows:
        u = use.get(r["address"].lower()) or {}
        r["id"] = str(r["id"])
        r["sent_today"] = int(u.get("sent_today") or 0)
        r["out_today"] = int(u.get("out_today") or 0)
        r["remaining"] = max(0, int(r["daily_cap"]) - r["out_today"])
        r["last_sent"] = u.get("last_sent")
        r["usable"] = bool(r["enabled"]) and not r["last_error"]
    return rows


def save(cur, user_email, address, creds=None, token_enc=None, daily_cap=None, move=False):
    """Keep the sign-in for an address, for this person: `creds` encrypted here, or `token_enc` already
    sealed for the server. An address linked to someone else is refused (ValueError) unless `move`:
    one address, one person, or "reached out by" would say two things."""
    address = address.strip().lower()
    token = token_enc or encrypt(creds)
    cur.execute("select id, user_email from user_mailboxes where lower(address) = %s", (address,))
    got = _rows(cur)
    if got and got[0]["user_email"].lower() != user_email.lower() and not move:
        raise ValueError("%s is already linked to %s" % (address, got[0]["user_email"]))
    if got:
        cur.execute("update user_mailboxes set user_email = %s, token_enc = %s, enabled = true, last_error = null,"
                    " last_error_at = null, daily_cap = coalesce(%s, daily_cap), connected_at = now(), updated_at = now()"
                    " where id = %s returning id", (user_email.lower(), token, daily_cap, got[0]["id"]))
    else:
        cur.execute("insert into user_mailboxes (user_email, address, token_enc, daily_cap)"
                    " values (%s, %s, %s, coalesce(%s, %s)) returning id",
                    (user_email.lower(), address, token, daily_cap, DEFAULT_CAP))
    return str(_rows(cur)[0]["id"])


def update_token(cur, mailbox_id, creds):
    """A refreshed access token, kept so the next run does not refresh again."""
    cur.execute("update user_mailboxes set token_enc = %s, updated_at = now() where id = %s",
                (encrypt(creds), str(mailbox_id)))


def mark_error(cur, mailbox_id, message):
    """Google refused the sign-in (revoked, expired, password changed): the address needs
    connecting again, and says so on the page until it is."""
    cur.execute("update user_mailboxes set last_error = %s, last_error_at = now(), updated_at = now() where id = %s",
                (str(message)[:300], str(mailbox_id)))


def remove(cur, address):
    """Unlink a sending address. -> the row removed ({address, user_email, token_enc}), or None."""
    cur.execute("delete from user_mailboxes where lower(address) = lower(%s) returning address, user_email, token_enc",
                (address.strip(),))
    got = _rows(cur)
    return got[0] if got else None


def remove_own(cur, mailbox_id, user_email):
    """A person disconnects one of their own addresses (app/mailbox_connect.py). -> the row removed, or None
    when it is not theirs: nobody unlinks someone else's address from the app."""
    cur.execute("delete from user_mailboxes where id = %s and lower(user_email) = lower(%s)"
                " returning address, user_email, token_enc", (str(mailbox_id), user_email))
    got = _rows(cur)
    return got[0] if got else None


def credentials(row):
    """The authorized-user dict for a row carrying token_enc, or None."""
    return decrypt(row.get("token_enc")) if row else None
