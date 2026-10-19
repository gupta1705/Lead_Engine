"""Recipient choice HTTP checks; all synthetic database writes roll back.

The scheduler is disabled and every job/sender wake raises. No Apollo or email
provider is used; a test-only user signs the normal authenticated requests.
"""
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

import auth
import main
from run_sql import load_db_url
from test_api import NoPool, TxConn


def run():
    conn = psycopg2.connect(load_db_url())
    main._checkout = TxConn(conn).begin
    main._POOL = NoPool()
    main._SEG_CACHE.update(at=0, rows=[])

    def no_jobs(*args, **kwargs):
        raise AssertionError("Choosing a recipient must not start jobs or send mail")

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
        slug = "zz-recipient-" + uuid.uuid4().hex[:8]
        cur.execute("select config from segments where slug='us-production-houses'")
        cfg = cur.fetchone()[0]
        cfg["outreach"]["batch_approval"] = {"enabled": True, "sample_min": 1, "sample_fraction": 0.1, "max_batch": 50}
        # Historical non-Apollo contacts are inserted before the project's saved
        # Apollo policy is enabled, exactly as in migrated production data.
        cfg["sourcing"]["contacts"] = "website"
        cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Recipient test','company',%s) returning id",
                    (slug, json.dumps(cfg)))
        sid = cur.fetchone()[0]
        user = uuid.uuid4().hex + "@test.example"
        password = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users(email,password_hash,name,title) values(%s,%s,'Reviewer','Partnerships')",
                    (user, password))
        cookies = {auth.COOKIE: auth.make_cookie(user, password), "tvf_segment": slug}

        def request(method, path, data=None, who=None):
            client.cookies.clear()
            return client.request(method, path, json=data, cookies=cookies if who is None else who)

        def add_lead(suffix):
            eid = str(uuid.uuid4())
            cur.execute("insert into entities(id,segment_id,name,domain,source,fit_score,metadata,status)"
                        " values(%s,%s,%s,%s,'apollo',75,%s,'shortlisted')",
                        (eid, sid, "Recipient Studio " + suffix, "recipient-" + suffix + ".example",
                         json.dumps({"host": {"first_name": "Wrong Host", "confidence": "high"}})))
            return eid

        def add_contact(eid, name, address, status="valid", source="apollo", verifier="apollo"):
            cur.execute("insert into contacts(entity_id,full_name,email,email_status,source,verifier,role_title)"
                        " values(%s,%s,%s,%s,%s,%s,'Executive Producer') returning id",
                        (eid, name, address, status, source, verifier))
            return str(cur.fetchone()[0])

        eid, fresh, other = (add_lead(s) for s in ("draft", "fresh", "other"))
        sam = add_contact(eid, "Sam Penfield", "info@recipient-draft.example")
        faye = add_contact(eid, "London Faye Butler", "faye@recipient-draft.example")
        direct = add_contact(eid, "Sam Penfield", "sam@recipient-draft.example")
        invalid = add_contact(eid, "Invalid Person", "invalid@recipient-draft.example", "invalid")
        legacy = add_contact(eid, "Legacy Person", "legacy@recipient-draft.example", "valid", "website", None)
        new_contact = add_contact(fresh, "Alex Smith", "alex@recipient-fresh.example")
        wrong_contact = add_contact(other, "Other Person", "other@recipient-other.example")
        duplicate = add_lead("duplicate")
        obsolete = add_contact(duplicate, "Old Person", "info@recipient-duplicate.example ", "unverified", "website", None)
        replacement = add_contact(duplicate, "Verified Person", "info@recipient-duplicate.example")
        cur.execute("insert into outreach(entity_id,contact_id,subject,body) values(%s,%s,'Original subject','Hi there,\n\nOriginal copy')",
                    (duplicate, obsolete))
        cfg["sourcing"]["contacts"] = "apollo"
        cur.execute("update segments set config=%s where id=%s", (json.dumps(cfg), sid))
        main._SEG_CACHE.update(at=0, rows=[])
        custom = "Hi Sam,\n\nA deliberately edited sentence.\nAnother paragraph, unchanged.\n\nCustom signature"
        subject = "A custom subject"
        cur.execute("insert into outreach(entity_id,contact_id,subject,body) values(%s,%s,%s,%s) returning id",
                    (eid, sam, subject, custom))
        oid = str(cur.fetchone()[0])
        url = "/api/leads/" + eid

        check(request("POST", url + "/recipient", {"contact_id": faye}, {}).status_code == 401,
              "recipient selection requires authentication")
        check(request("POST", "/api/leads/not-a-uuid/recipient", {"contact_id": faye}).status_code == 404,
              "malformed lead id returns 404")
        check(request("POST", url + "/recipient", {"contact_id": "bad"}).status_code == 404,
              "malformed contact id returns 404")
        wrong_project = dict(cookies, tvf_segment="us-production-houses")
        check(request("GET", url, who=wrong_project).status_code == 404,
              "lead details are scoped to the active project")
        check(request("POST", url + "/recipient", {"contact_id": faye}, wrong_project).status_code == 404,
              "recipient changes are scoped to the active project")
        for contact_id, label in ((wrong_contact, "another company's contact"), (invalid, "invalid address"),
                                  (legacy, "historical website email in an Apollo project")):
            check(request("POST", url + "/recipient", {"contact_id": contact_id}).status_code == 409,
                  label + " is refused")
        duplicate_detail = request("GET", "/api/leads/" + duplicate).json()
        check([c["id"] for c in duplicate_detail["contacts"] if c["drafts_use"]] == [obsolete],
              "a normalized duplicate does not hide the actual obsolete email recipient")
        check(any(c["id"] == replacement and c["can_select_recipient"] for c in duplicate_detail["contacts"]),
              "an obsolete recipient does not hide an eligible duplicate replacement")
        check(request("POST", "/api/leads/" + duplicate + "/recipient", {"contact_id": replacement}).status_code == 200,
              "a draft can repair its obsolete contact using an eligible normalized duplicate")

        detail = request("GET", url).json()
        badge = [c["id"] for c in detail["contacts"] if c["drafts_use"]]
        check(badge == [sam] and detail["outreach"]["contact_id"] == sam,
              "existing draft badge identifies its actual assigned recipient")
        check(not next(c for c in detail["contacts"] if c["id"] == legacy)["can_select_recipient"],
              "ineligible historical email remains visible but cannot be selected")
        response = request("POST", url + "/recipient", {"contact_id": faye})
        check(response.status_code == 200 and response.json()["draft_updated"],
              "eligible person can replace an unapproved draft recipient")
        cur.execute("select contact_id,subject,body,status,approved_at from outreach where id=%s", (oid,))
        saved = cur.fetchone()
        check(str(saved[0]) == faye and saved[1] == subject and saved[2] == custom.replace("Hi Sam,", "Hi Faye,", 1)
              and saved[3:] == ("drafted", None),
              "recipient change preserves subject, custom copy, approval and status; only greeting changes")
        detail = request("GET", url).json()
        check(detail["selected_recipient_id"] == faye and
              [c["id"] for c in detail["contacts"] if c["drafts_use"]] == [faye],
              "lead detail shows the saved choice and actual draft recipient")
        pref = detail["metadata"]["outreach_recipient"]
        check(pref["contact_id"] == faye and pref["email"] == "faye@recipient-draft.example"
              and pref["chosen_by"] == user and pref["chosen_at"], "recipient choice records who chose it and when")
        listed = request("GET", "/api/leads?status=shortlisted").json()["rows"]
        preview = next(r for r in listed if r["id"] == eid)
        check(preview["email"] == "faye@recipient-draft.example" and preview["contact_name"] == "London Faye Butler",
              "Leads and Board previews use the manually chosen recipient")
        direct_email = request("GET", "/api/outreach/" + oid).json()
        check(direct_email["recipient_contact_id"] == faye, "email previews expose their assigned recipient for concurrency checks")
        for method, path, payload in (("PATCH", "/api/outreach/" + oid,
                                        {"body": "Hi Sam,\n\nA stale editor's copy.", "expected_contact_id": sam}),
                                       ("POST", "/api/outreach/" + oid + "/decision",
                                        {"action": "approve", "expected_contact_id": sam})):
            cur.execute("select contact_id,subject,body,status from outreach where id=%s", (oid,))
            before = cur.fetchone()
            stale = request(method, path, payload)
            check(stale.status_code == 409 and "recipient changed" in stale.json()["detail"],
                  method + " from a stale email preview requires reopening the draft")
            cur.execute("select contact_id,subject,body,status from outreach where id=%s", (oid,))
            check(cur.fetchone() == before, method + " stale preview leaves draft and approval unchanged")
        check(request("PATCH", "/api/outreach/" + oid, {"subject": subject, "expected_contact_id": faye}).status_code == 200,
              "an editor with the current recipient can save normally")
        cur.execute("update outreach set contact_id=%s,body=%s where id=%s", (sam, custom, oid))
        check(request("POST", "/api/outreach/" + oid + "/decision", {"action": "link_contact"}).status_code == 200,
              "automatic contact linking respects the saved recipient preference")
        cur.execute("select contact_id,body from outreach where id=%s", (oid,))
        linked = cur.fetchone()
        check(str(linked[0]) == faye and linked[1] == custom.replace("Hi Sam,", "Hi Faye,", 1),
              "automatic linking uses the chosen contact and updates only its known greeting")
        stale_recipients = {oid: {"contact_id": sam, "email": "info@recipient-draft.example"}}
        stale_sample = request("POST", "/api/outreach/batch/sample", {"ids": [oid], "expected_recipients": stale_recipients})
        check(stale_sample.status_code == 409 and "recipient changed" in stale_sample.json()["detail"],
              "batch sampling refuses a recipient changed since the list was loaded")
        pol = main._policy()
        sample, token = pol.draw_sample([oid], pol.batch_policy(cfg["outreach"]), auth._secret(), user, slug)
        stale_batch = request("POST", "/api/outreach/batch/approve",
                              {"ids": [oid], "sample": sample, "token": token, "expected_recipients": stale_recipients})
        check(stale_batch.status_code == 409 and "recipient changed" in stale_batch.json()["detail"],
              "batch approval refuses a changed recipient even with a valid sample token")
        missing = request("POST", "/api/outreach/batch/sample", {"ids": [oid], "expected_recipients": {}})
        check(missing.status_code == 400, "batch recipient map must cover all selected drafts")
        cur.execute("update contacts set email='faye.changed@recipient-draft.example' where id=%s", (faye,))
        changed_email = request("PATCH", "/api/outreach/" + oid,
                                {"subject": "Stale email", "expected_contact_id": faye,
                                 "expected_contact_email": "faye@recipient-draft.example"})
        check(changed_email.status_code == 409, "same contact ID with a changed email also invalidates the open editor")
        changed_email = request("POST", "/api/outreach/" + oid + "/decision",
                                {"action": "approve", "expected_contact_id": faye,
                                 "expected_contact_email": "faye@recipient-draft.example"})
        check(changed_email.status_code == 409, "same contact ID with a changed email invalidates approval")
        changed_email = request("POST", "/api/outreach/batch/sample",
                                {"ids": [oid], "expected_recipients": {oid: {"contact_id": faye,
                                                                         "email": "faye@recipient-draft.example"}}})
        check(changed_email.status_code == 409, "batch checks email changes as well as contact identity")
        cur.execute("update contacts set email='faye@recipient-draft.example' where id=%s", (faye,))

        edited = "Hello team!\n\nA custom opening that must not be replaced.\nSam is discussed in this paragraph."
        cur.execute("update outreach set body=%s where id=%s", (edited, oid))
        check(request("POST", url + "/recipient", {"contact_id": direct}).status_code == 200,
              "another verified recipient can be selected")
        cur.execute("select body from outreach where id=%s", (oid,))
        check(cur.fetchone()[0] == edited, "nonstandard custom greeting and body are preserved exactly")

        check(request("POST", "/api/leads/" + fresh + "/recipient", {"contact_id": new_contact}).status_code == 200,
              "choice is saved before a lead has an email")
        cur.execute("select count(*) from outreach where entity_id=%s", (fresh,))
        check(cur.fetchone()[0] == 0, "selecting a recipient does not generate or approve an email")
        detail = request("GET", "/api/leads/" + fresh).json()
        check(detail["selected_recipient_id"] == new_contact and not any(c["drafts_use"] for c in detail["contacts"]),
              "a saved future recipient is not falsely labelled as an existing draft recipient")

        cur.execute("update contacts set email_status='invalid' where id=%s", (new_contact,))
        detail = request("GET", "/api/leads/" + fresh).json()
        check(detail["recipient_selection_stale"] and detail["selected_recipient_id"] is None,
              "a later-invalidated preference is reported without silent fallback")
        cur.execute("update entities set metadata=jsonb_set(metadata,'{outreach_recipient}','null'::jsonb) where id=%s", (fresh,))
        check(request("GET", "/api/leads/" + fresh).json()["recipient_selection_stale"],
              "a malformed null preference is also exposed as stale")

        for status, expected in (("approved", "Withdraw approval"), ("sending", "already sending"),
                                 ("send_unknown", "already sending"), ("sent", "email thread")):
            cur.execute("update outreach set status=%s where id=%s", (status, oid))
            cur.execute("select contact_id,subject,body,status from outreach where id=%s", (oid,))
            before = cur.fetchone()
            response = request("POST", url + "/recipient", {"contact_id": faye})
            check(response.status_code == 409 and expected in response.json()["detail"],
                  status + " recipient change is refused with an actionable reason")
            cur.execute("select contact_id,subject,body,status from outreach where id=%s", (oid,))
            check(cur.fetchone() == before, status + " recipient and email remain unchanged")
            check(expected in request("GET", url).json()["recipient_locked_reason"],
                  status + " lead detail exposes the recipient lock")

        cur.execute("update outreach set status='cancelled' where id=%s", (oid,))
        cur.execute("insert into outreach(entity_id,contact_id,direction,status,body) values(%s,%s,'inbound','received','A reply')",
                    (eid, direct))
        check(request("POST", url + "/recipient", {"contact_id": faye}).status_code == 409,
              "an inbound conversation prevents changing the thread recipient")
        cur.execute("select config from segments where slug='lcx-clipping'")
        clipping_cfg = cur.fetchone()[0]
        clipping_slug = "zz-clipping-recipient-" + uuid.uuid4().hex[:8]
        cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Clipping recipient test','company',%s) returning id",
                    (clipping_slug, json.dumps(clipping_cfg)))
        clipping_sid = cur.fetchone()[0]
        clipping_lead = str(uuid.uuid4())
        cur.execute("insert into entities(id,segment_id,name,domain,source,status)"
                    " values(%s,%s,'Clipping Test Show','clipping-test.example','youtube','shortlisted')",
                    (clipping_lead, clipping_sid))
        clipping_contact = add_contact(clipping_lead, "London Faye Butler", "faye@clipping-test.example", "unverified", "website", None)
        clipping_cookies = dict(cookies, tvf_segment=clipping_slug)
        main._SEG_CACHE.update(at=0, rows=[])
        check(request("POST", "/api/leads/" + clipping_lead + "/recipient", {"contact_id": clipping_contact}, clipping_cookies).status_code == 200,
              "clipping retains its existing website-contact eligibility rules")
        clipping_detail = request("GET", "/api/leads/" + clipping_lead, who=clipping_cookies).json()
        check(clipping_detail["selected_recipient_id"] == clipping_contact and clipping_detail["contacts"][0]["can_select_recipient"],
              "clipping selected recipient is visible and selectable without adding Apollo restrictions")
        print("PASS %d checks; all fixture writes rolled back" % checks, flush=True)
    finally:
        conn.rollback()
        conn.close()


def greeting_checks():
    """Fast focused checks for literal unnamed template salutations; no DB connection."""
    entity = {"name": "Example Studio", "metadata": {}}
    old = {"full_name": None, "email": "info@example.com", "source": "apollo"}
    chosen = {"full_name": "Sam Penfield", "email": "sam@example.com", "source": "apollo"}
    preference = {"contact_id": str(uuid.uuid4()), "email": chosen["email"]}
    suffix = "\n\nA custom sentence.\n\nCustom signature"
    for salutation in ("Hi", "Hello", "Dear"):
        before = salutation + "," + suffix
        expected = salutation + " Sam," + suffix
        assert main._recipient_greeting(before, old, chosen, entity, {}, preference) == expected
    unnamed = {"full_name": None, "email": "contact@example.com", "source": "apollo"}
    assert main._recipient_greeting("Hello," + suffix, old, unnamed, entity, {}, preference) == "Hello," + suffix
    assert main._recipient_greeting("Hello Someone Else," + suffix, old, chosen, entity, {}, preference) == "Hello Someone Else," + suffix
    print("PASS 5 literal greeting checks; no database or provider used", flush=True)


if __name__ == "__main__":
    if "--greetings-only" in sys.argv:
        greeting_checks()
    else:
        greeting_checks()
        run()
