#!/usr/bin/env python3
"""test_demo.py -- the public demo (/demo; the owner, 2026-11-01: "SO NO DATA SHOULD BE VISIBLE ON IT"), as a table.

    python tools/test_demo.py

The real app in-process (FastAPI's TestClient), signed in as nobody, and the committed app/demo/data.json checked
against the real database (read only: nothing is written). Checked:

  * the demo page and its five files open without a sign-in; the page runs the pretend /api in front of the app
  * nothing else opens: not the app's own page, script or Docs, not a path under /demo, not one /api call
  * the demo's Docs: the demo's projects, none of the real ones, no one's address
  * the demo data: nothing real in it (every company, contact, address, team member, project name and the owner's
    email copy in the database, tools/demo_data.leaks), every address and link on .example, only made-up people
  * the pretend /api in demo mode answers everything itself: no call reaches the server
  * DEMO_ENABLED=0: the demo is gone, and the login page no longer offers it
Exit code 1 on any failure.
"""
import json
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ.setdefault("SESSION_SECRET", "zz-demo-test-" + uuid.uuid4().hex)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from run_sql import load_db_url  # noqa: E402

import demo_data  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RESULTS = []


def check(name, got, want):
    ok = got == want
    RESULTS.append(ok)
    print("%s  %-84s -> %s" % ("ok  " if ok else "FAIL", name, json.dumps(got, default=str)[:110]
                                + ("" if ok else "   (want %s)" % json.dumps(want, default=str)[:110])))


def main_():
    import main
    client = TestClient(main.app, follow_redirects=False)

    print("-- the demo opens without a sign-in")
    r = client.get("/demo")
    page = r.text
    check("/demo: the app's page", (r.status_code, "<div" in page), (200, True))
    check("  with the pretend /api in front of the app, in demo mode",
          ('"demo": true' in page, page.index("/demo/mock.js") < page.index("/demo/app.js"), 'src="app.js"' in page),
          (True, True, False))
    for path, kind in (("/demo/app.js", "javascript"), ("/demo/style.css", "css"), ("/demo/mock.js", "javascript"),
                       ("/demo/data.json", "json"), ("/demo/docs.html", "html")):
        r = client.get(path)
        check("  %s" % path, (r.status_code, kind in r.headers.get("content-type", "")), (200, True))

    print("\n-- nothing else opens")
    for path in ("/", "/app.js", "/docs.html", "/index.html", "/demo/", "/demo/x", "/demo/data.json/x",
                 "/demo/../docs.html"):
        r = client.get(path)
        check("  %s: to the login page" % path, (r.status_code, r.headers.get("location")), (302, "/login"))
    for path in ("/api/leads", "/api/outreach?folder=inbox", "/api/stats", "/api/reports/team", "/api/v1/projects"):
        check("  %s: refused" % path, client.get(path).status_code, 401)

    print("\n-- the demo's Docs")
    docs = client.get("/demo/docs.html").text
    check("its projects are the demo's", ("Podcast Partnerships" in docs, "Company Search" in docs), (True, True))
    check("  none of the real ones, and not the business's name",
          [w for w in ("LCX", "TVF", "Viral Fever", "US Production Houses", "ReelForge") if w in docs], [])
    check("  no one's address", sorted({e for e in re.findall(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", docs)
                                        if not (e.endswith(".example") or e.endswith("@example.com"))}), [])

    print("\n-- the demo data")
    data = json.loads((ROOT / "app" / "demo" / "data.json").read_text(encoding="utf-8"))
    conn = psycopg2.connect(load_db_url())
    conn.set_session(readonly=True)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            sensitive = demo_data.sensitive_strings(cur)
    finally:
        conn.close()
    found = demo_data.leaks(data, sensitive)
    check("nothing real in it (checked against %d real strings)" % len(sensitive), found[:3], [])
    projects = data["projects"]
    check("its projects: the two made-up ones", sorted(projects), sorted([demo_data.PODCASTS, demo_data.COMPANIES]))
    people = {p for fx in projects.values() for a in (fx.get("mailboxes") or {}).get("accounts") or []
              for p in [a["email"]]}
    check("  its people: made-up, at the demo's domain", sorted(people), sorted(p[0] for p in demo_data.PEOPLE))
    check("  signed in as the made-up visitor", {fx["auth"]["user"] for fx in projects.values()},
          {demo_data.PEOPLE[0][0]})
    pod = projects[demo_data.PODCASTS]
    folders = {(r["direction"], r["status"]) for r in pod["outreach"]["rows"]}
    check("  every screen has something: leads in each column, drafts, approved, sent, replies",
          ({l["status"] for l in pod["leads"]} >= {"ready_for_review", "shortlisted", "contacted", "in_conversation"},
           {("outbound", "drafted"), ("outbound", "approved"), ("outbound", "sent"), ("inbound", "received")} <= folders),
          (True, True))
    check("  a waiting reply among them (In conversation)",
          any(r.get("awaiting_answer") for r in pod["outreach"]["rows"]), True)

    print("\n-- the pretend /api in demo mode")
    mock = (ROOT / "app" / "demo" / "mock.js").read_text(encoding="utf-8")
    demo_block = mock.index("if (CONF.demo && u.origin === location.origin")
    check("a page request in demo mode stays in the page (only its Docs are fetched, from /demo)",
          ("return realFetch(CONF.docs, opts);" in mock[demo_block:demo_block + 400],
           'return json({ detail: "That is not part of the demo." }, 404);' in mock[demo_block:demo_block + 400]),
          (True, True))
    tail = mock[mock.index("window.fetch = async"):mock.index("const notInDemo")]
    check("  every /api call is answered in the page: no realFetch for /api",
          (tail.count("realFetch("), 'CONF.demo ? "That is not part of the demo."' in tail), (2, True))

    print("\n-- DEMO_ENABLED=0")
    main.DEMO_ON = False
    try:
        check("/demo: behind the sign-in, like everything else", client.get("/demo").status_code, 302)
        check("  its data too", client.get("/demo/data.json").status_code, 302)
    finally:
        main.DEMO_ON = True
    os.environ["DEMO_ENABLED"] = "0"
    try:
        check("the login page offers no demo", client.get("/api/auth/state").json().get("demo"), False)
    finally:
        os.environ.pop("DEMO_ENABLED", None)
    check("  and with it on, it does", client.get("/api/auth/state").json().get("demo"), True)

    bad = RESULTS.count(False)
    print("\n%d failure(s) of %d checks (nothing written)" % (bad, len(RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main_())
