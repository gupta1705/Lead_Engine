#!/usr/bin/env python3
"""n8n_setup.py -- load the connector and its credentials into n8n via the CLI.

SETUP.md walks through doing this by hand: import the workflow, then click into
five nodes and re-point each at the right credential, because n8n ties
credentials to an internal instance ID rather than a name. That is fine once
and tedious every time a connector is added -- and Phase B adds four more.

This does the same thing through `n8n import:credentials` and
`n8n import:workflow`, so the credential exists under the exact name the
workflow JSON already references and the nodes link themselves.

THE CREDENTIAL NEVER ENTERS A TRANSCRIPT. Values are read from the gitignored
`.env`, written to a temp file inside the OS temp directory, imported, and the
temp file is deleted in a `finally` block -- including on error. Nothing is
printed but field names.

ORDER MATTERS: create the n8n owner account in the browser FIRST
(http://localhost:5678), then run this. Recent n8n versions attach imported
credentials to the instance owner, so importing into an instance that has no
owner yet can leave them orphaned and invisible in the UI.

Usage:
    python tools/n8n_setup.py            # import credentials + workflow
    python tools/n8n_setup.py --check    # report what it would do, change nothing
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
# Every connector workflow in the discovery folder. Adding P6-P8 later means
# dropping a JSON file in, not editing this list.
WORKFLOW_DIR = ROOT / "n8n" / "discovery"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("conn_*.json"))
WORKFLOW = WORKFLOWS[0] if WORKFLOWS else WORKFLOW_DIR / "conn_youtube_api.json"

PG_CREDENTIAL_NAME = "Supabase — Lead Engine"
YT_CREDENTIAL_NAME = "YouTube Data API Key"


def read_env():
    if not ENV.exists():
        sys.exit("no .env at %s -- copy .env.example and fill it in" % ENV)
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def pg_credential(db_url):
    """Turn a postgres URI into n8n's Postgres credential shape."""
    u = urlparse(db_url)
    if not u.hostname:
        sys.exit("SUPABASE_DB_URL does not look like a postgres URI")
    return {
        # n8n 2.x requires an id on import; a stable one keeps re-runs
        # idempotent rather than creating a duplicate each time.
        "id": "supabaseleadeng1",
        "name": PG_CREDENTIAL_NAME,
        "type": "postgres",
        "data": {
            "host": u.hostname,
            "port": u.port or 5432,
            "database": (u.path or "/postgres").lstrip("/") or "postgres",
            "user": unquote(u.username or ""),
            "password": unquote(u.password or ""),
            # Supabase terminates TLS at the pooler and requires encryption,
            # but presents a cert chain node-postgres will not verify by
            # default. "require" encrypts without demanding verification,
            # which is what every Supabase client does here.
            "ssl": "require",
            "allowUnauthorizedCerts": True,
        },
    }


def yt_credential(api_key):
    """YouTube takes the key as a ?key= query parameter, not a header."""
    return {
        "id": "youtubeapikey001",
        "name": YT_CREDENTIAL_NAME,
        "type": "httpQueryAuth",
        "data": {"name": "key", "value": api_key},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report readiness and change nothing")
    args = ap.parse_args()

    env = read_env()
    n8n = shutil.which("n8n")

    have_db = bool(env.get("SUPABASE_DB_URL"))
    have_yt = bool(env.get("YOUTUBE_API_KEY"))

    print("n8n setup -- readiness\n")
    print("  n8n on PATH ............ %s" % ("yes" if n8n else "NO"))
    print("  SUPABASE_DB_URL ........ %s" % ("set" if have_db else "EMPTY"))
    print("  YOUTUBE_API_KEY ........ %s" % ("set" if have_yt else "EMPTY"))
    print("  workflow files ......... %d found" % len(WORKFLOWS))

    if args.check:
        print("\n(--check: nothing imported)")
        if not have_yt:
            print("\nYOUTUBE_API_KEY is empty. The Postgres credential and the")
            print("workflow can still be imported now; re-run this after adding")
            print("the key and it will add the YouTube credential too.")
        return 0

    if not n8n:
        sys.exit("\nn8n is not on PATH. Install it with:  npm install -g n8n")
    if not WORKFLOW.exists():
        sys.exit("\nworkflow file missing: %s" % WORKFLOW)

    creds = []
    if have_db:
        creds.append(pg_credential(env["SUPABASE_DB_URL"]))
    if have_yt:
        creds.append(yt_credential(env["YOUTUBE_API_KEY"]))
    if not creds:
        sys.exit("\nnothing to import -- .env has neither value")

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=".json", prefix="n8n_creds_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(creds, fh)

        print("\nimporting %d credential(s): %s"
              % (len(creds), ", ".join(c["name"] for c in creds)))
        r = subprocess.run([n8n, "import:credentials", "--input=" + tmp],
                           capture_output=True, text=True)
        # never echo the command line or file contents on failure
        if r.returncode != 0:
            print("  FAILED (exit %d)" % r.returncode)
            print("  " + (r.stderr.strip().splitlines() or ["(no stderr)"])[-1])
            print("\n  Add them by hand instead -- n8n/discovery/SETUP.md steps 1-2.")
        else:
            print("  ok")

        # Every connector, not just the first. Phase B adds one per rung, and
        # importing only WORKFLOWS[0] silently left conn_x_intent_signals out.
        for wf in WORKFLOWS:
            print("\nimporting workflow: %s" % wf.name)
            r = subprocess.run([n8n, "import:workflow", "--input=" + str(wf)],
                               capture_output=True, text=True)
            # n8n exits 0 on failure, so surface its output either way; the
            # database check below is what actually decides.
            for line in (r.stdout + r.stderr).strip().splitlines()[-3:]:
                if line.strip():
                    print("  " + line)
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
            print("\n(temp credential file deleted)")

    # n8n's CLI exits 0 even when an import fails -- verified: a NOT NULL
    # constraint violation on workflow_entity.id still returned 0. So the exit
    # code above proves nothing. Confirm against n8n's own database instead.
    print("\nverifying against n8n's database:")
    import sqlite3
    dbp = os.path.expanduser("~/.n8n/database.sqlite")
    if not os.path.exists(dbp):
        print("  no ~/.n8n/database.sqlite -- check the UI by hand")
    else:
        conn = sqlite3.connect(dbp)
        try:
            have = {cid for cid, in conn.execute("select id from credentials_entity")}
            rows = conn.execute(
                "select name, nodes from workflow_entity").fetchall()
            if not rows:
                print("  NO WORKFLOWS PRESENT -- the import did not land")
                return 1
            nodes = [n for _, blob in rows for n in json.loads(blob)]
            print("  %d workflow(s) present: %s"
                  % (len(rows), ", ".join(r[0] for r in rows)))
            broken = [(n["name"], ref.get("id"))
                      for n in nodes
                      for ref in (n.get("credentials") or {}).values()
                      if ref.get("id") not in have]
            if broken:
                for name, cid in broken:
                    print("  BROKEN  %-32s credential id %s not found" % (name, cid))
                print("\n  Those nodes will show a credential warning in the UI.")
                return 1
            n_linked = sum(1 for n in nodes if n.get("credentials"))
            print("  workflow present; %d credential-using node(s), all linked"
                  % n_linked)
        finally:
            conn.close()

    print("\nOpen http://localhost:5678 -- the workflow should be there with its")
    print("credentials already linked. Check the 5 credential-using nodes show a")
    print("credential rather than a warning, then click Test workflow.")
    if not have_yt:
        print("\nNOTE: no YouTube credential was imported (YOUTUBE_API_KEY empty).")
        print("The two HTTP nodes will fail until you add the key and re-run this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
