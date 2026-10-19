"""Exact email links, scoped previews and history; fixture writes always roll back."""
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app")]
os.environ["SCHEDULER_ENABLED"] = "0"

import bcrypt
import psycopg2
from fastapi.testclient import TestClient
from psycopg2.extras import execute_values

import auth
import draft_render as dr
import main
from run_sql import load_db_url
from test_api import NoPool, TxConn


def run():
    conn = psycopg2.connect(load_db_url())
    main._checkout = TxConn(conn).begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0, rows=[])

    def no_jobs(*args, **kwargs):
        raise AssertionError("Read-only email links must not start jobs")

    main._scheduler.kick_outreach = no_jobs
    main._scheduler.wake_sender = no_jobs
    client = TestClient(main.app, follow_redirects=False)
    checks = 0

    def check(condition, name):
        nonlocal checks
        assert condition, name
        checks += 1
        print("ok " + name, flush=True)

    try:
        cur = conn.cursor()
        slug = "zz-email-link-" + uuid.uuid4().hex[:8]
        cur.execute("select config from segments where slug='us-production-houses'")
        cfg = cur.fetchone()[0]
        cfg["audiences"] = [{"key": "hotel", "label": "Hotels"}, {"key": "school", "label": "Schools"}]
        cfg["outreach"]["sign_as"] = "approver"
        cfg["outreach"]["sender"] = {"name": "Project Sender", "title": "Project Title"}
        cfg["outreach"]["footer"] = {"text": "{{sender_name}}\n{{sender_title}}"}
        cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Email link test','company',%s) returning id",
                    (slug, json.dumps(cfg)))
        sid = cur.fetchone()[0]
        email = uuid.uuid4().hex + "@test.example"
        password = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users(email,password_hash,name,title) values(%s,%s,'Review Person','Partnerships')",
                    (email, password))
        cookies = {auth.COOKIE: auth.make_cookie(email, password), "tvf_segment": slug}

        def call(url, who=None):
            client.cookies.clear()
            return client.get(url, cookies=cookies if who is None else who)

        fixtures = [(str(uuid.uuid4()), str(uuid.uuid4()), n) for n in range(204)]
        execute_values(cur, "insert into entities(id,segment_id,name,domain,source,fit_score,metadata,status) values %s",
                       [(eid, sid, "Email link fixture %03d" % n, eid + ".example", json.dumps({"kind": "school" if n == 0 else "hotel"}))
                        for eid, _, n in fixtures],
                       template="(%s::uuid,%s::uuid,%s,%s,'apollo',75,%s::jsonb,'shortlisted')")
        body = "Hi Reviewer,\n\nA draft to review.\n\n" + dr.footer_for(cfg["outreach"])
        execute_values(cur, "insert into outreach(id,entity_id,subject,body,service,created_at) values %s",
                       [(oid, eid, "A useful introduction", body, "School tours" if n == 0 else "Hotel photos", n)
                        for eid, oid, n in fixtures],
                       template="(%s::uuid,%s::uuid,%s,%s,%s,timestamptz '2020-01-01'+%s*interval '1 minute')")
        for eid, oid, n in (fixtures[0], fixtures[202], fixtures[203]):
            cur.execute("insert into contacts(entity_id,full_name,email,email_status,source,verifier,email_verified_at)"
                        " values(%s,'Verified Person',%s,'valid','apollo','apollo',now()) returning id",
                        (eid, "reviewer@" + eid + ".example"))
            cid = cur.fetchone()[0]
            cur.execute("update outreach set contact_id=%s where id=%s", (cid, oid))
        approved, sent = fixtures[202][1], fixtures[203][1]
        for oid, status in ((approved, "approved"), (sent, "sent")):
            cur.execute("update outreach set status=%s,approved_by=%s,approved_at=now(),sender_address=%s,"
                        "sent_at=case when %s='sent' then now() else null end where id=%s",
                        (status, email, email, status, oid))
        target = fixtures[0][1]
        url = "/api/outreach/" + target
        check(call(url, {}).status_code == 401, "direct email requires authentication")
        check(call("/api/outreach/not-a-uuid").status_code == 404, "malformed email id returns 404")
        check(call("/api/outreach/" + str(uuid.uuid4())).status_code == 404, "missing email returns 404")
        check(call(url, dict(cookies, tvf_segment="us-production-houses")).status_code == 404,
              "email from another project returns 404")
        check(call("/api/outreach/footer").status_code == 200, "static footer route is not shadowed")
        page = call("/api/outreach?folder=drafts").json()
        check(len(page["rows"]) == 200 and page["total"] == 202 and target not in {r["id"] for r in page["rows"]},
              "target is beyond the first 200 drafts")
        filtered = call("/api/outreach?folder=drafts&category=hotel&service=Hotel%20photos").json()
        check(target not in {r["id"] for r in filtered["rows"]}, "target is excluded by active category and service filters")
        response = call(url)
        check(response.status_code == 200, "exact email opens outside the folder page and filters")
        detail = response.json()
        matching = call("/api/outreach?folder=drafts&category=school&service=School%20tours").json()["rows"][0]
        check(detail == matching, "direct draft has exactly the folder preview fields")
        check(detail["body"].endswith("Review Person\nPartnerships") and "Project Sender" not in detail["body"],
              "direct draft previews the signed-in reviewer's sign-off")
        check(detail["contact_email"] and detail["contact_verified"] and not detail["approval_blocked"],
              "direct draft retains verified recipient and approval checks")
        blocked = call("/api/outreach/" + fixtures[1][1]).json()
        check(blocked["approval_blocked"] == "Needs a verified contact before approval.",
              "addressless draft remains blocked in the direct preview")
        for oid, status, folder in ((approved, "approved", "outbox"), (sent, "sent", "sent")):
            one = call("/api/outreach/" + oid).json()
            listed = call("/api/outreach?folder=" + folder).json()["rows"][0]
            check(one == listed and one["status"] == status and one["body"] == body,
                  status + " email matches stored history and folder fields")
            check("schedule" in one and one["approved_by_name"] == "Review Person",
                  status + " email includes sending details and approver")
        cur.execute("select status,count(*) from outreach where id=any(%s::uuid[]) group by status", ([f[1] for f in fixtures],))
        check(dict(cur.fetchall()) == {"drafted": 202, "approved": 1, "sent": 1},
              "viewing email links changes no draft, approval or sent state")
        print("PASS %d checks; all fixture writes rolled back" % checks, flush=True)
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    run()
