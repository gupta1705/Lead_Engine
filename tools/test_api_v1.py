#!/usr/bin/env python3
"""test_api_v1.py -- the Lead Engine's API (/api/v1) and MCP server (/mcp), with each person's keys (owner, 2026-10-26:
"I want to build mcp and api for this so build it"), as a table.

    python tools/test_api_v1.py

The real app in-process (FastAPI's TestClient) against the real database inside ONE transaction that is rolled back,
with sql/42, sql/43 and the repo's configs applied inside it. Checked:

  * keys: made on the page only, shown once, kept only as a fingerprint; a key works as its person, on /api/v1 and
    /mcp only (never the app's own endpoints, never key management); a wrong, revoked or starting-password key is
    refused; at most ten live keys; a key's rate is limited
  * the API: projects, leads, one lead, emails, one email; add a lead with its email kept as a DRAFT (signed for
    whoever opens it, never approved), a dry run that adds nothing, problems named; edit a draft; shortlist/reject;
    approving needs a key that may (and is recorded as through the API); withdrawing takes it back
  * MCP: initialize (version negotiation), notifications, ping, tools/list, tools/call (results and tool errors),
    unknown tools and methods, batches, a parse error, no event stream, another site's page refused
Exit code 1 on any failure.
"""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SESSION_SECRET"] = "zz-api-v1-test-" + uuid.uuid4().hex

import bcrypt  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []
SLUGS = ("us-production-houses", "lcx-services", "lcx-clipping", "startup-acquisitions", "universal")
CFGS = {s: json.loads((ROOT / "config" / ("segment.%s.json" % s)).read_text(encoding="utf-8")) for s in SLUGS}


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


def main_():
    import main
    import auth
    import api_v1
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
        for slug in SLUGS:
            cur.execute("update segments set config = %s where slug = %s", (json.dumps(CFGS[slug]), slug))
        main._SEG_CACHE.update(at=0.0, rows=[])
        tag = uuid.uuid4().hex[:6]

        def person(name, title, starting=False):
            email = "zz-api-%s-%s@example.com" % (name.split()[0].lower(), tag)
            h = bcrypt.hashpw(b"zz-api-password", bcrypt.gensalt(4)).decode()
            cur.execute("insert into app_users (email, password_hash, role, name, title, must_change_password)"
                        " values (%s, %s, 'member', %s, %s, %s)", (email, h, name, title, starting))
            return email, {auth.COOKIE: auth.make_cookie(email, h)}
        zed, zed_ck = person("Zed Tester", "Partnerships")

        def call(method, path, key=None, cookies=None, **kw):
            client.cookies.clear()
            headers = dict(kw.pop("headers", {}) or {})
            if key:
                headers["Authorization"] = "Bearer " + key
            r = client.request(method, path, cookies=cookies, headers=headers, **kw)
            try:
                body = r.json()
            except ValueError:
                body = None
            return r, body

        print("-- keys")
        r, k = call("POST", "/api/keys", cookies=zed_ck, json={"name": "Claude on my laptop"})
        key = (k or {}).get("key", "")
        check("made on the page: shown once, a tle_ key", (r.status_code, key.startswith("tle_"), len(key) > 40),
              (200, True, True))
        cur.execute("select key_hash, prefix, user_email from api_keys where id = %s", (k["id"],))
        row = cur.fetchone()
        check("  only its fingerprint is kept", (row["key_hash"] == hashlib.sha256(key.encode()).hexdigest(),
                                                 key not in json.dumps(row), row["user_email"]), (True, True, zed))
        r, lst = call("GET", "/api/keys", cookies=zed_ck)
        check("  the list never shows the key", (len(lst["keys"]), "key" in lst["keys"][0], lst["mcp"].endswith("/mcp")),
              (1, False, True))
        r, me = call("GET", "/api/v1/me", key=key)
        check("a key works as its person", (r.status_code, me["email"], me["name"]), (200, zed, "Zed Tester"))
        r, _ = call("GET", "/api/v1/me", cookies=zed_ck)
        check("  and the signed-in page may use the API too", r.status_code, 200)
        r, b = call("GET", "/api/leads", key=key)
        check("a key never reaches the app's own endpoints", (r.status_code, b["detail"]),
              (403, "A key works only on /api/v1 and /mcp."))
        r, _ = call("GET", "/api/keys", key=key)
        check("  nor key management (a key cannot make keys)", r.status_code, 403)
        r, _ = call("GET", "/api/v1/me", key="tle_not-a-real-key")
        check("a wrong key: 401, saying how to get in", (r.status_code, r.headers.get("www-authenticate", "")[:6]),
              (401, "Bearer"))
        r, _ = call("POST", "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        check("no key on /mcp: 401, not a login page", r.status_code, 401)
        r, b = call("GET", "/.well-known/oauth-protected-resource")
        check("an MCP client finds where to sign in (OAuth, tools/test_oauth.py)", (r.status_code, b["resource"][-4:]),
              (200, "/mcp"))
        r, _ = call("GET", "/.well-known/something-else")
        check("  any other well-known path: 404", r.status_code, 404)
        new, new_ck = person("Newbie Starter", "Sales", starting=True)
        cur.execute("insert into api_keys (user_email, name, prefix, key_hash) values (%s, 'x', 'tle_x', %s)",
                    (new, hashlib.sha256(b"tle_zz-starting-" + tag.encode()).hexdigest()))
        r, _ = call("GET", "/api/v1/me", key="tle_zz-starting-" + tag)
        check("a login still on its starting password: its key is refused", r.status_code, 401)
        r, k3 = call("POST", "/api/keys", cookies=zed_ck, json={"name": "reads and drafts", "can_approve": False})
        no_approve = k3["key"]
        check("a key can be made that may not approve", (r.status_code, k3["can_approve"]), (200, False))
        r, k2 = call("POST", "/api/keys", cookies=zed_ck, json={"name": "to revoke"})
        call("GET", "/api/v1/me", key=k2["key"])
        r, _ = call("DELETE", "/api/keys/%s" % k2["id"], cookies=zed_ck)
        r2, _ = call("GET", "/api/v1/me", key=k2["key"])
        check("a revoked key stops at once", (r.status_code, r2.status_code), (200, 401))
        for i in range(8):                     # with the first two, ten live keys (the revoked one does not count)
            call("POST", "/api/keys", cookies=zed_ck, json={"name": "spare %d" % i})
        r, b = call("POST", "/api/keys", cookies=zed_ck, json={"name": "one too many"})
        check("at most ten live keys", r.status_code, 409)
        r, b = call("POST", "/api/keys", cookies=zed_ck, json={"name": "  "})
        check("a key needs a name", r.status_code, 400)
        old = api_v1.RATE
        api_v1.RATE = (3, 60)
        api_v1._CALLS.clear()
        try:
            codes = [call("GET", "/api/v1/me", key=key)[0].status_code for _ in range(5)]
        finally:
            api_v1.RATE = old
            api_v1._CALLS.clear()
        check("a key's rate is limited (429 past it)", codes, [200, 200, 200, 429, 429])

        print("\n-- the API")
        r, p = call("GET", "/api/v1/projects", key=key)
        by = {x["slug"]: x for x in p["projects"]}
        check("every project, with what its leads are called",
              (sorted(by), by["lcx-clipping"]["lead_label"], len(by["lcx-services"]["services"] or []),
               by["us-production-houses"]["follow_up_after_days"]),
              (sorted(SLUGS), "show", 18, 4))
        r, _ = call("GET", "/api/v1/projects/no-such/leads", key=key)
        check("an unknown project: 404", r.status_code, 404)
        r, ls = call("GET", "/api/v1/projects/us-production-houses/leads?status=shortlisted&limit=2", key=key)
        check("leads: at most the limit, each with its status",
              (r.status_code, len(ls["rows"]) <= 2, all(x["status"] == "shortlisted" for x in ls["rows"])),
              (200, True, True))
        r, _ = call("GET", "/api/v1/projects/us-production-houses/leads?status=bogus", key=key)
        check("  a status it does not know: refused", r.status_code, 422)
        dom = "zz-api-%s.example" % tag
        lead = {"company": "ZZ API Films %s" % tag, "email": "kelly@" + dom, "contact_name": "Kelly Smith",
                "role": "Head of Development", "website": dom, "country": "US", "city": "Austin",
                "subject": "{{company}} and The Viral Fever", "body": "Hi {{first_name}},\n\nWe should talk."}
        r, dry = call("POST", "/api/v1/projects/us-production-houses/leads", key=key, json=dict(lead, dry_run=True))
        cur.execute("select count(*) as n from entities where domain = %s", (dom,))
        check("a dry run: how it reads, nothing added",
              (r.status_code, dry["added"], dry["reads_as"]["body"].startswith("Hi Kelly,"), cur.fetchone()["n"]),
              (201, False, True, 0))
        r, bad = call("POST", "/api/v1/projects/lcx-clipping/leads", key=key,
                      json=dict(lead, email="kay@show.de", website=None, country=None))
        check("a lead it cannot take: 422, the problem named",
              (r.status_code, "Germany" in json.dumps(bad)), (422, True))
        r, add = call("POST", "/api/v1/projects/us-production-houses/leads", key=key, json=lead)
        eid, oid = add.get("lead_id"), add.get("email_id")
        check("added: the lead, and its email as a DRAFT", (r.status_code, add["added"], add["email_status"], bool(oid)),
              (201, True, "drafted", True))
        cur.execute("select o.status, o.approved_by, o.approved_at, o.body, e.source, c.source as cs, c.verifier"
                    " from outreach o join entities e on e.id = o.entity_id join contacts c on c.id = o.contact_id"
                    " where o.id = %s", (oid,))
        x = cur.fetchone()
        check("  never approved by the key: a person approves it in the app",
              (x["status"], x["approved_by"], x["approved_at"]), ("drafted", None, None))
        check("  the lead and person as Add a lead makes them", (x["source"], x["cs"], x["verifier"]),
              ("manual", "manual", "person"))
        r, em = call("GET", "/api/v1/emails/%s" % oid, key=key)
        check("  stored in the project's own form, shown to its person with their sign-off",
              ("Zed Tester" in x["body"], "Zed Tester" in em["body"], em["folder"], em["to"]["email"]),
              (False, True, "drafts", "kelly@" + dom))
        r, gl = call("GET", "/api/v1/leads/%s" % eid, key=key)
        check("one lead: its person is the recipient, its email a draft",
              (gl["status"], [c["email"] for c in gl["contacts"] if c["is_recipient"]], gl["email"]["status"]),
              ("shortlisted", ["kelly@" + dom], "drafted"))
        r, fl = call("GET", "/api/v1/projects/us-production-houses/emails?folder=drafts&limit=100", key=key)
        check("the drafts folder lists it, and counts every folder",
              (r.status_code, sorted(fl["counts"])[:3], fl["counts"]["drafts"] >= 1),
              (200, ["approved", "attention", "drafts"], True))
        r, ed = call("PATCH", "/api/v1/emails/%s" % oid, key=key, json={"subject": "A better subject"})
        check("edit a draft", (r.status_code, ed["subject"]), (200, "A better subject"))
        r2, _ = call("POST", "/api/outreach/%s/decision" % oid, key=key, json={"action": "approve"})
        check("the app's own approval stays closed to keys", r2.status_code, 403)
        r, b = call("POST", "/api/v1/emails/%s/approve" % oid, key=no_approve)
        cur.execute("select status from outreach where id = %s", (oid,))
        check("a key made without approving may not approve (403), and nothing changed",
              (r.status_code, cur.fetchone()["status"]), (403, "drafted"))
        r, ap = call("POST", "/api/v1/emails/%s/approve" % oid, key=key)
        cur.execute("select status, approval_mode, approved_by, body from outreach where id = %s", (oid,))
        x = cur.fetchone()
        check("a key that may: approved exactly as the app does, recorded as through the API",
              (r.status_code, ap.get("status"), x["status"], x["approval_mode"], x["approved_by"],
               "Zed Tester" in x["body"]), (200, "approved", "approved", "api", zed, True))
        r, wd = call("POST", "/api/v1/emails/%s/withdraw" % oid, key=no_approve)
        cur.execute("select status from outreach where id = %s", (oid,))
        check("withdraw: an approved email not yet gone is taken back", (r.status_code, cur.fetchone()["status"]),
              (200, "cancelled"))
        r, dc = call("POST", "/api/v1/leads/%s/decision" % eid, key=key, json={"decision": "reject",
                                                                               "reason": "not a fit"})
        check("reject: the lead is rejected", (dc["status"], dc["emails_withdrawn"]), ("rejected", 0))
        r, _ = call("PATCH", "/api/v1/emails/%s" % oid, key=key, json={"subject": "too late"})
        check("  a withdrawn email can no longer be edited", r.status_code >= 400, True)
        r, spec = call("GET", "/api/v1/openapi.json", key=key)
        check("the API describes itself (OpenAPI)",
              ("/api/v1/projects/{project}/leads" in spec["paths"], spec["components"]["securitySchemes"]["key"]["scheme"]),
              (True, "bearer"))

        print("\n-- MCP")

        def rpc(payload, **kw):
            r = client.post("/mcp", headers=dict({"Authorization": "Bearer " + key,
                                                  "Accept": "application/json, text/event-stream"},
                                                 **kw.pop("headers", {})), content=json.dumps(payload) if not
                            isinstance(payload, (bytes, str)) else payload, **kw)
            try:
                return r, r.json()
            except ValueError:
                return r, None
        r, ini = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "zz", "version": "0"}}})
        res = ini["result"]
        check("initialize: the version asked for, tools, who it is",
              (r.status_code, res["protocolVersion"], "tools" in res["capabilities"], res["serverInfo"]["name"]),
              (200, "2025-06-18", True, "tvf-lead-engine"))
        r, ini = rpc({"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        check("  a version it does not know: its own newest", ini["result"]["protocolVersion"], "2025-11-25")
        r, b = rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        check("a notification: 202, no body", (r.status_code, r.content), (202, b""))
        r, b = rpc({"jsonrpc": "2.0", "id": "p", "method": "ping"})
        check("ping", b, {"jsonrpc": "2.0", "id": "p", "result": {}})
        r, tl = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = [t["name"] for t in tl["result"]["tools"]]
        check("tools/list: the eleven, each with an object schema",
              (sorted(names), all(t["inputSchema"]["type"] == "object" for t in tl["result"]["tools"])),
              (sorted(["whoami", "list_projects", "search_leads", "get_lead", "list_emails", "get_email", "add_lead",
                       "decide_lead", "edit_draft", "approve_email", "withdraw_email"]), True))
        r, c = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_projects",
                                                                                 "arguments": {}}})
        res = c["result"]
        check("tools/call: text and structured content",
              (res["isError"], len(res["structuredContent"]["projects"]), json.loads(res["content"][0]["text"]) ==
               res["structuredContent"]), (False, 5, True))
        r, c = rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "add_lead", "arguments": dict(
            lead, project="us-production-houses", company="ZZ MCP Co %s" % tag, email="ann@zz-mcp-%s.example" % tag, website="zz-mcp-%s.example" % tag,
            contact_name="Ann Lee", dry_run=True)}})
        check("  add_lead as a dry run", (c["result"]["isError"], (c["result"].get("structuredContent") or {})
                                         .get("reads_as", {}).get("body", c["result"]["content"][0]["text"])[:7]),
              (False, "Hi Ann,"))
        r, c = rpc({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_lead",
                                                                                 "arguments": {"lead_id": "nope"}}})
        check("  a tool that fails says why, as a tool error", (c["result"]["isError"], c["result"]["content"][0]["text"]),
              (True, "no such lead"))
        r, c = rpc({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "send_everything",
                                                                                 "arguments": {}}})
        check("an unknown tool: -32602", c["error"]["code"], -32602)
        r, c = rpc({"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {
            "name": "approve_email", "arguments": {"email_id": oid, "_can_approve": True}}},
            headers={"Authorization": "Bearer " + no_approve})
        check("  approve_email with a key that may not: a tool error, whatever the arguments claim",
              (c["result"]["isError"], "may not approve" in c["result"]["content"][0]["text"]), (True, True))
        r, c = rpc({"jsonrpc": "2.0", "id": 8, "method": "resources/list"})
        check("an unknown method: -32601", c["error"]["code"], -32601)
        r, c = rpc([{"jsonrpc": "2.0", "id": 9, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/x"},
                    {"jsonrpc": "2.0", "id": 10, "method": "tools/list"}])
        check("a batch: one answer per request", [x["id"] for x in c], [9, 10])
        r, c = rpc("{not json")
        check("a parse error", (r.status_code, c["error"]["code"]), (400, -32700))
        r = client.get("/mcp", headers={"Authorization": "Bearer " + key})
        check("no event stream: GET is 405", (r.status_code, r.headers.get("allow")), (405, "POST"))
        r, c = rpc({"jsonrpc": "2.0", "id": 11, "method": "ping"}, headers={"Origin": "https://evil.example"})
        check("a page on another site is refused", r.status_code, 403)
        r, c = rpc({"jsonrpc": "2.0", "id": 12, "method": "ping"}, headers={"Authorization": "Bearer tle_wrong"})
        check("a wrong key on /mcp: 401", r.status_code, 401)
    finally:
        conn.rollback()
        conn.close()
    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (all rows rolled back; nothing sent)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
