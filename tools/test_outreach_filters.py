"""Outreach filtering, numeric ordering, pagination and unsendable previews; all writes roll back."""
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
import main
from run_sql import load_db_url
from test_api import TxConn, NoPool


def run():
    conn = psycopg2.connect(load_db_url())
    main._checkout = TxConn(conn).begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0, rows=[])
    main._scheduler.kick_outreach = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No send jobs allowed"))
    client = TestClient(main.app, follow_redirects=False)
    checks = 0
    def check(condition, name):
        nonlocal checks
        assert condition, name
        checks += 1
        print("ok " + name, flush=True)
    try:
        cur = conn.cursor()
        cur.execute((ROOT / 'supabase/migrations/20261019105938_unaddressed_outreach_previews.sql').read_text())
        slug = "zz-outreach-" + uuid.uuid4().hex[:8]
        cur.execute("select config from segments where slug='us-production-houses'")
        cfg = cur.fetchone()[0]
        cfg["audiences"] = [{"key": "hotel", "label": "Hotels"}, {"key": "school", "label": "Schools"}]
        cfg["outreach"].pop("send_from", None)
        cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Outreach test','company',%s) returning id", (slug, json.dumps(cfg)))
        sid = cur.fetchone()[0]
        email = uuid.uuid4().hex + "@test.example"
        password = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users(email,password_hash,name,title) values(%s,%s,'Test Person','Development')", (email, password))
        cookies = {auth.COOKIE: auth.make_cookie(email, password), "tvf_segment": slug}
        def call(method, url, **kw):
            client.cookies.clear()
            return client.request(method, url, cookies=cookies, **kw)
        def get(**params):
            r = call("GET", "/api/outreach", params=params)
            check(r.status_code == 200, "outreach request succeeds " + str(params))
            return r.json()
        fixtures = []
        for n in range(207):
            eid, oid = str(uuid.uuid4()), str(uuid.uuid4())
            category = "hotel" if n < 205 else "school"
            subscriber = [9, 100, 20, "hidden", None, 0][n % 6]
            meta = {"kind": category, "youtube_channel": {"subscribers": subscriber, "view_count": subscriber}}
            fixtures.append((eid, sid, "Filter fixture %03d" % n, "%s.example" % eid, n, json.dumps(meta), oid, "Photos" if n < 205 else "Trips"))
        execute_values(cur, "insert into entities(id,segment_id,name,domain,source,fit_score,metadata,status) values %s",
                       [r[:6] for r in fixtures], template="(%s::uuid,%s::uuid,%s,%s,'apollo',%s,%s::jsonb,'shortlisted')")
        execute_values(cur, "insert into outreach(id,entity_id,subject,body,service,created_at) values %s",
                       [(r[6], r[0], "Stories built to travel", "Hello,\n\nA draft to review.", r[7], n) for n, r in enumerate(fixtures)],
                       template="(%s::uuid,%s::uuid,%s,%s,%s,timestamptz '2020-01-01'+%s*interval '1 minute')")
        first = get(sort="score", direction="desc")
        check(first["total"] == 207 and len(first["rows"]) == 200, "all rows counted beyond the first page")
        second = get(sort="score", direction="desc", offset=200)
        check(len(second["rows"]) == 7 and not {r['id'] for r in first['rows']} & {r['id'] for r in second['rows']}, "stable non-overlapping pages")
        filtered = get(category="school", service="Trips", sort="score")
        check(filtered["total"] == 2 and all(r["category"] == "school" for r in filtered["rows"]), "combined category/service filters apply before pagination")
        check(filtered["counts"]["drafts"] == 207 and filtered["filtered_counts"]["drafts"] == 2, "filtered folder totals preserve the global sidebar count")
        check({c["key"]: c["label"] for c in filtered["categories"]}["hotel"] == "Hotels", "business categories use configured labels")
        for key, field in (("subscribers", "subscriber_count"), ("views", "view_count"), ("score", "lead_score")):
            for direction in ("asc", "desc"):
                rows = get(sort=key, direction=direction)["rows"]
                values = [r[field] for r in rows if r[field] is not None]
                check(values == sorted(values, reverse=direction == "desc"), key + " sorts numerically " + direction)
                if key != "score":
                    all_rows = rows + get(sort=key, direction=direction, offset=200)["rows"]
                    values = [r[field] for r in all_rows]
                    first_unknown = next(i for i, v in enumerate(values) if v is None)
                    check(all(v is None for v in values[first_unknown:]) and 0 in values[:first_unknown], "unknown metrics last; real zero retained " + key + direction)
        old = get(sort="date", direction="asc", limit=1)["rows"][0]
        new = get(sort="date", direction="desc", limit=1)["rows"][0]
        check(old["id"] == fixtures[0][6] and new["id"] == fixtures[-1][6], "oldest and newest dates work in both directions")
        check(call("GET", "/api/outreach?sort=score;delete%20from%20entities").status_code == 400, "sort SQL injection is rejected")
        check(get(category="hotel' or true --")["total"] == 0, "filter values are bound parameters")
        check(old["approval_blocked"] and not old["contact_email"], "unaddressed drafts are visible and blocked")
        for forbidden in ('approved','sending'):
            cur.execute('savepoint cannot_send_preview')
            try:
                cur.execute('update outreach set status=%s where id=%s',(forbidden,old['id']))
            except psycopg2.errors.CheckViolation:
                cur.execute('rollback to savepoint cannot_send_preview')
                check(True,'database rejects unaddressed '+forbidden)
            else:
                raise AssertionError('Unaddressed preview became '+forbidden)
        cur.execute("insert into contacts(entity_id,email,email_status,source,verifier,email_verified_at) values(%s,'downgraded@test.example','valid','apollo','apollo',now()) returning id", (fixtures[1][0],))
        downgraded=cur.fetchone()[0]
        cur.execute("update contacts set email_status='unverified' where id=%s",(downgraded,))
        cur.execute('savepoint invalid_recipient')
        try:
            cur.execute('update outreach set contact_id=%s where id=%s',(downgraded,fixtures[1][6]))
        except psycopg2.errors.CheckViolation:
            cur.execute('rollback to savepoint invalid_recipient')
            check(True,'an unverified assigned email is rejected even for a draft')
        else:
            raise AssertionError('An unverified assigned recipient was accepted')
        oid, eid = fixtures[0][6], fixtures[0][0]
        check(call("POST", "/api/outreach/%s/decision" % oid, json={"action": "approve"}).status_code == 409, "addressless draft cannot be approved")
        check(call("POST", "/api/outreach/%s/decision" % oid, json={"action": "link_contact"}).status_code == 409, "recipient link refuses a missing verified contact")
        cur.execute("insert into contacts(entity_id,full_name,email,email_status,source,verifier,email_verified_at) values(%s,'Verified Person','verified@test.example','valid','apollo','apollo',now())", (eid,))
        other = dict(cookies, tvf_segment="us-production-houses")
        client.cookies.clear()
        r = client.post("/api/outreach/%s/decision" % oid, cookies=other, json={"action": "link_contact"})
        check(r.status_code == 404, "recipient linking is scoped to the current project")
        cur.execute("update entities set status='ready_for_review' where id=%s", (eid,))
        check(call("POST", "/api/outreach/%s/decision" % oid, json={"action": "link_contact"}).status_code == 409, "linking preserves company qualification")
        cur.execute("update entities set status='shortlisted' where id=%s", (eid,))
        check(call("POST", "/api/outreach/%s/decision" % oid, json={"action": "link_contact"}).status_code == 200, "qualified verified contact can be linked without approval")
        row = get(sort="date", direction="asc", limit=1)["rows"][0]
        check(row["contact_email"] == "verified@test.example" and not row["approval_blocked"] and row["status"] == "drafted", "link makes a preview reviewable and leaves it drafted")
        cur.execute("select count(*) from outreach o join entities e on e.id=o.entity_id where e.segment_id=%s and o.status<>'drafted'", (sid,))
        check(cur.fetchone()[0] == 0, "no fixture email approved or sent")
        print("PASS %d checks; all writes rolled back" % checks)
    finally:
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    run()
