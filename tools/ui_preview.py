#!/usr/bin/env python3
"""ui_preview.py -- look at the web UI without logging in and without touching
production: a snapshot of real data, served behind a mocked /api.

    python tools/ui_preview.py --generate               # snapshot -> logs/ui_fixtures.json
    python tools/ui_preview.py --serve [--port 8123]    # http://127.0.0.1:8123/

WHY. The app sits behind a login, and the tool that helps build the UI must not
hold anyone's password. So the preview serves app/static as-is and answers
every /api call from a JSON snapshot taken with the same endpoint functions the
real server runs. Filters, paging, decisions, folder moves and job runs are
re-implemented in the mock closely enough to exercise every screen; nothing
the preview does reaches the database while serving.

The snapshot carries real company and contact data, so it lives under logs/
(gitignored) and is never committed. The public demo uses the same mock with
made-up data instead (tools/demo_data.py).
"""
import argparse
import http.server
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
DEFAULT_FIXTURES = ROOT / "logs" / "ui_fixtures.json"
FOLDERS = ["drafts", "followups", "outbox", "sent", "inbox", "attention"]
STATUSES = ["open", "shortlisted", "contacted", "in_conversation", "rejected", "archived"]


def generate(out, slug):
    sys.path.insert(0, str(ROOT / "app"))
    sys.path.insert(0, str(ROOT))
    import main                                  # the real endpoint functions
    import ops
    fx = {"auth": {"needs_setup": False, "authed": True, "user": None}}
    fx["segment"] = main.segment_info(slug)
    fx["segments"] = main.segments_list(slug)
    # Add a lead: what each project's form says (tools/manual_lead.project)
    import manual_lead
    with main.cursor() as cur:
        cur.execute("select slug, config from segments where is_active")
        fx["manual_projects"] = {r["slug"]: manual_lead.project(r["config"] or {}) for r in cur.fetchall()}
    with main.cursor() as cur:
        # the person the preview is signed in as: the owner, or anyone, with a name so no first-sign-in screen
        cur.execute("select email, name, title from app_users order by role = 'owner' desc, created_at limit 1")
        row = cur.fetchone()
        fx["auth"]["user"] = row["email"] if row else "owner@example.com"
        fx["auth"].update(name=(row or {}).get("name") or "Preview Person",
                          title=(row or {}).get("title") or "Business Development", must_change_password=False)

    class _Req:                                   # what the endpoints read off a request: who is signed in
        state = type("S", (), {"user": fx["auth"]["user"]})()
    req = _Req()
    fx["stats"] = main.stats(segment=slug)
    fx["kpis"] = main.kpis(segment=slug)
    seen, leads = set(), []
    for st in STATUSES:
        for r in main.leads(status=st, limit=500, segment=slug)["rows"]:
            if r["id"] not in seen:
                seen.add(r["id"]); leads.append(r)
    fx["leads"] = leads
    # decided leads first (they carry the richest evidence), then the open pool in score order,
    # at most 250 of each so the snapshot stays small. A single cap of 400 was spent entirely on
    # LCX's 451 shortlisted leads, and the To review list, which the manual photographs, had none.
    open_ = {"discovered", "enriched", "scored", "ready_for_review"}
    ordered = sorted((r for r in leads if r["status"] != "archived"),
                     key=lambda r: (1 if r["status"] in open_ else 0, -(float(r["fit_score"] or 0))))
    detail_ids = ([r["id"] for r in ordered if r["status"] not in open_][:250]
                  + [r["id"] for r in ordered if r["status"] in open_][:250])
    fx["details"] = {}
    for i, lid in enumerate(detail_ids):
        fx["details"][lid] = main.lead(lid)
        if i % 50 == 0:
            print("  details %d/%d" % (i, len(detail_ids)), flush=True)
    rows, counts = [], {}
    for f in FOLDERS:
        d = main.outreach_list(req, folder=f, segment=slug)
        rows += d["rows"] + d.get("negative_rows", []); counts = d["counts"]   # Replies keeps Negative apart
    fx["outreach"] = {"rows": rows, "counts": counts}
    # a project that searches Apollo (Universal, LCX Services) has no mailboxes of its own: each person sends from theirs
    apollo_page = (fx["segment"].get("ui") or {}).get("search_page") == "apollo"
    fx["mailboxes"] = None if apollo_page else main.mailboxes_state(req, segment=slug)
    fx["me_mailboxes"] = {"mailboxes": []}
    fx["footer"] = main.footer_get(segment=slug)
    fx["schedule"] = main.schedule_state(segment=slug)
    fx["ops"] = {"busy": None}
    # the Apollo page: its filter list, straight from tools/apollo.py; the searches themselves are
    # answered by a pretend Apollo in the mock (made-up people at example.com), so no key and no credit
    import apollo
    import explain
    with main.cursor() as cur:
        cur.execute("select config->'apollo' as a from segments where slug = %s", (slug if apollo_page else "universal",))
        row = cur.fetchone()
    a = (row or {}).get("a") or {}
    fx["universal"] = {"filters": apollo.FILTERS, "endpoints": a.get("endpoints") or [],
                       "per_page": a.get("per_page") or 25, "max_reveal_per_save": a.get("max_reveal_per_save") or 100}
    # a lead as a save would leave it, explained by the real explain.py, for the lead dialog
    demo = {"id": "00000000-0000-4000-8000-00000000d3m0", "name": "Demo Pictures", "domain": "demopictures.example",
            "source": "apollo", "status": "ready_for_review", "fit_score": None, "status_reason": None,
            "status_changed_at": None, "created_at": "2026-09-19T10:00:00+00:00", "updated_at": None,
            "metadata": {"industry": "entertainment", "employees": 24, "hq_city": "Mumbai", "hq_country": "India",
                         "apollo": {"id": "a" * 24, "name": "Demo Pictures", "industry": "entertainment",
                                    "estimated_num_employees": 24, "city": "Mumbai", "country": "India",
                                    "founded_year": 2014, "phone": "+91 22 0000 0000",
                                    "linkedin_url": "https://www.linkedin.com/company/example",
                                    "short_description": "A made-up studio, for the preview."},
                         "apollo_people": {"b" * 24: {"name": "Asha Example", "title": "Head of Partnerships",
                                                      "seniority": "head", "city": "Mumbai", "country": "India",
                                                      "has_email": True}},
                         "saved_from": {"summary": "People · Job titles: head of partnerships",
                                        "at": "2026-09-19T10:00:00+00:00", "by": fx["auth"]["user"]}}}
    contacts = explain.rank_contacts([{"id": "c1", "full_name": "Asha Example", "role_title": "Head of Partnerships",
                                       "email": "asha@demopictures.example", "email_status": "valid", "is_primary": True,
                                       "source": "apollo", "linkedin_url": "https://www.linkedin.com/in/example",
                                       "rank": 95}], demo["domain"])
    demo["contacts"] = contacts
    demo["outreach"] = None
    demo["explain"] = explain.explain_lead("universal", {"rubric": [], "ui": {"search_page": "apollo"}}, demo, contacts)
    demo["criteria"] = []
    demo["thresholds"] = {"review": 0, "priority": 0}
    if apollo_page:
        # a project that searches Apollo starts empty: one made-up saved lead, so the board, list and dialog have something
        fx["details"][demo["id"]] = demo
        fx["leads"].append({"id": demo["id"], "name": demo["name"], "domain": demo["domain"], "source": "apollo",
                            "status": "ready_for_review", "fit_score": 0, "why_fit": None, "kind": None,
                            "host_name": None, "fields": ["entertainment", "24", "India"], "city": "Mumbai",
                            "state": None, "n_contacts": 1, "email": "asha@demopictures.example",
                            "contact_name": "Asha Example"})
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write(json.dumps(fx, default=str))
    print("wrote %s: %d leads, %d details, %d outreach rows" % (out, len(leads), len(fx["details"]), len(rows)))


# The pretend /api lives in app/demo/mock.js, shared with the public demo (served at /demo by app/main.py): the
# preview feeds it this snapshot, the demo its made-up data (tools/demo_data.py).


def serve(port, fixtures):
    if not fixtures.exists():
        sys.exit("no snapshot at %s -- run: python tools/ui_preview.py --generate" % fixtures)
    fixture_bytes = fixtures.read_bytes()

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(STATIC), **kw)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                html = io.open(STATIC / "index.html", encoding="utf-8").read()
                # the mock too: a change to it must reach the browser, not its cached copy
                v = str(int(max([os.path.getmtime(STATIC / f) for f in ("app.js", "style.css")]
                                + [os.path.getmtime(ROOT / "app" / "demo" / "mock.js")])))
                html = (html.replace('href="style.css"', 'href="style.css?v=%s"' % v)
                            .replace('<script src="app.js"></script>',
                                     '<script src="/__mock.js?v=%s"></script>\n<script src="app.js?v=%s"></script>' % (v, v)))
                return self._send(html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/__mock.js":
                return self._send((ROOT / "app" / "demo" / "mock.js").read_bytes(), "application/javascript")
            if path == "/__fixtures.json":
                return self._send(fixture_bytes, "application/json")
            if path == "/login":
                return self._send(io.open(STATIC / "login.html", encoding="utf-8").read().encode("utf-8"),
                                  "text/html; charset=utf-8")
            return super().do_GET()

        def _send(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            pass

    print("UI preview on http://127.0.0.1:%d/  (snapshot: %s)" % (port, fixtures), flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--fixtures", type=Path, default=None)
    ap.add_argument("--segment", default=os.environ.get("SEGMENT_SLUG", "us-production-houses"))
    a = ap.parse_args()
    if a.fixtures is None:
        a.fixtures = ROOT / "logs" / ("ui_fixtures.%s.json" % a.segment)
    if a.generate:
        generate(a.fixtures, a.segment)
    if a.serve:
        serve(a.port, a.fixtures)
    if not a.generate and not a.serve:
        ap.print_help()


if __name__ == "__main__":
    main()
