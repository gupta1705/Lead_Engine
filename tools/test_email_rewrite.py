"""Regression tests for rewrite proposals, footer preservation, and authenticated routes.
The API fixtures use one rolled-back transaction; no emails are approved or sent.
"""
import json
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app")]
os.environ["SCHEDULER_ENABLED"] = "0"
import email_rewrite as rewrite
import draft_render as dr
import llm


class RewriteTests(unittest.TestCase):
    def proposal(self, subject="Hello", body="A clearer email."):
        return patch.object(llm, "_chat", return_value=json.dumps({"subject": subject, "body": body}))

    def test_preserves_footer_and_sender(self):
        cfg = {"send_from": "approver", "sender": {"name": "Project", "title": "BD"}}
        person = {"name": "Kartikeya", "title": "Strategy"}
        footer = dr.footer_for(cfg, person["name"], person["title"])
        with self.proposal() as chat:
            result = rewrite.rewrite("Original", "An email.\n\n" + footer, "Shorter", cfg, person)
        self.assertEqual(result["body"], "A clearer email.\n\n" + footer)
        sent = json.loads(chat.call_args[0][0][1]["content"])
        self.assertEqual(sent["body"], "An email.")
        self.assertNotIn("postal_address", result["body"])

    def test_preserves_compose_placeholders(self):
        with self.proposal("Hi {{company}}", "Hello {{first_name}},\nCould we talk to {{company}}?"):
            result = rewrite.rewrite("Hello {{company}}", "Hi {{first_name}}, a call with {{company}}?")
        self.assertIn("{{first_name}}", result["body"])

    def test_rejects_changed_placeholders(self):
        with self.proposal("Hello", "Hi there."), self.assertRaises(llm.Unavailable):
            rewrite.rewrite("Hello", "Hi {{first_name}}.")

    def test_rejects_new_destinations(self):
        with self.proposal(body="Visit https://invented.example.com"), self.assertRaises(llm.Unavailable):
            rewrite.rewrite("Hello", "A short call?")

    def test_rejects_invented_numbers(self):
        with self.proposal(body="We made 999 films."), self.assertRaises(llm.Unavailable):
            rewrite.rewrite("Hello", "We make films.")

    def test_rejects_bad_model_output(self):
        for output in ("not JSON", "[]", '{"subject":"Hello","body":""}',
                       '{"subject":"Hello\\nInjected","body":"Text"}'):
            with self.subTest(output=output), patch.object(llm, "_chat", return_value=output), self.assertRaises(llm.Unavailable):
                rewrite.rewrite("Hello", "Original.")

    def test_input_refusals_make_no_model_call(self):
        with patch.object(llm, "_chat") as chat:
            for subject, body, instructions in (("", "Text", ""), ("A\nB", "Text", ""),
                                                ("Hello", "", ""), ("Hello", "Text", "x" * 2001),
                                                (12, "Text", "")):
                with self.assertRaises(ValueError):
                    rewrite.rewrite(subject, body, instructions)
            chat.assert_not_called()

    def test_keeps_numbers_already_in_the_draft(self):
        with self.proposal(body="We have made 7 series."):
            result = rewrite.rewrite("Hello", "We have made 7 series and would like a call.")
        self.assertIn("7 series", result["body"])

    def test_provider_failure_keeps_proposal_unsaved(self):
        with patch.object(llm, "_chat", side_effect=llm.Unavailable("offline")), self.assertRaises(llm.Unavailable):
            rewrite.rewrite("Hello", "Original.")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bcrypt
        import psycopg2
        import main
        import auth
        from run_sql import load_db_url
        from test_api import TxConn, NoPool
        from fastapi.testclient import TestClient
        cls.main = main
        cls.conn = psycopg2.connect(load_db_url(), connect_timeout=15)
        cls.cur = cls.conn.cursor()
        tx = TxConn(cls.conn)
        cls.patches = [patch.object(main, "_checkout", tx.begin), patch.object(main, "_POOL", NoPool())]
        for p in cls.patches:
            p.start()
        tag = uuid.uuid4().hex[:8]
        cls.slug = "zz-rewrite-" + tag
        cfg = json.loads((ROOT / "config/segment.universal.json").read_text(encoding="utf-8"))
        cfg.pop("sourcing", None)                  # legacy test lead; the Apollo-only gates: test_apollo_constraints
        cls.cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'ZZ rewrite','company',%s) returning id",
                        (cls.slug, json.dumps(cfg)))
        sid = cls.cur.fetchone()[0]
        email = "zz-rewrite-" + tag + "@example.com"
        hashed = bcrypt.hashpw(uuid.uuid4().hex.encode(), bcrypt.gensalt(4)).decode()
        cls.cur.execute("insert into app_users(email,password_hash,role,name,title) values(%s,%s,'member','Asha','Partnerships')", (email, hashed))
        cls.cookies = {auth.COOKIE: auth.make_cookie(email, hashed), "tvf_segment": cls.slug}
        cls.cur.execute("insert into entities(segment_id,name,source,status) values(%s,'Rewrite Company','test','shortlisted') returning id", (sid,))
        eid = cls.cur.fetchone()[0]
        cls.cur.execute("insert into outreach(entity_id,template_key,subject,body,status) values(%s,'test','Original','Original body.','drafted') returning id", (eid,))
        cls.oid = str(cls.cur.fetchone()[0])
        main._SEG_CACHE.update(at=0.0, rows=[])
        cls.client = TestClient(main.app, follow_redirects=False)

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()
        for p in reversed(cls.patches):
            p.stop()
        cls.main._SEG_CACHE.update(at=0.0, rows=[])

    def call(self, path, body=None, cookies=True):
        self.client.cookies.clear()
        return self.client.post(path, cookies=self.cookies if cookies else {},
                                json=body or {"subject": "Unsaved subject", "body": "Unsaved edits.", "instructions": "Shorter"})

    def test_rewrite_requires_signin(self):
        self.assertEqual(self.call("/api/outreach/rewrite", cookies=False).status_code, 401)

    def test_saved_draft_proposal_uses_unsaved_edits_and_changes_no_row(self):
        with patch.object(llm, "_chat", return_value=json.dumps({"subject": "Proposal", "body": "Clearer edits."})) as chat:
            r = self.call("/api/outreach/" + self.oid + "/rewrite")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"subject": "Proposal", "body": "Clearer edits."})
        payload = json.loads(chat.call_args[0][0][1]["content"])
        self.assertEqual(payload["body"], "Unsaved edits.")
        self.cur.execute("select subject,body,status from outreach where id=%s", (self.oid,))
        self.assertEqual(self.cur.fetchone(), ("Original", "Original body.", "drafted"))

    def test_compose_proposal_creates_nothing(self):
        self.cur.execute("select count(*) from outreach")
        count = self.cur.fetchone()[0]
        with patch.object(llm, "_chat", return_value=json.dumps({"subject": "Proposal", "body": "Clearer edits."})):
            r = self.call("/api/outreach/rewrite")
        self.assertEqual(r.status_code, 200, r.text)
        self.cur.execute("select count(*) from outreach")
        self.assertEqual(self.cur.fetchone()[0], count)

    def test_no_rewrite_for_approved_messages(self):
        self.cur.execute("update outreach set status='approved' where id=%s", (self.oid,))
        try:
            with patch.object(llm, "_chat") as chat:
                self.assertEqual(self.call("/api/outreach/" + self.oid + "/rewrite").status_code, 409)
                chat.assert_not_called()
        finally:
            self.cur.execute("update outreach set status='drafted' where id=%s", (self.oid,))

    def test_other_project_cannot_rewrite_draft(self):
        old = self.cookies["tvf_segment"]
        self.cookies["tvf_segment"] = "us-production-houses"
        try:
            self.assertEqual(self.call("/api/outreach/" + self.oid + "/rewrite").status_code, 404)
        finally:
            self.cookies["tvf_segment"] = old

    def test_provider_error_is_actionable_and_secret_free(self):
        with patch.object(llm, "_chat", side_effect=llm.Unavailable("secret test detail")):
            r = self.call("/api/outreach/" + self.oid + "/rewrite")
        self.assertEqual(r.status_code, 503)
        self.assertIn("unchanged", r.text)
        self.assertNotIn("secret test detail", r.text)

    def test_save_records_model_text_without_approval(self):
        self.client.cookies.clear()
        r = self.client.patch("/api/outreach/" + self.oid, cookies=self.cookies,
                              json={"subject": "Edited", "body": "Rewritten text.", "ai_rewritten": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.cur.execute("select status,generated_hook from outreach where id=%s", (self.oid,))
        self.assertEqual(self.cur.fetchone(), ("drafted", "Rewritten text."))
        self.cur.execute("update outreach set subject='Original',body='Original body.',generated_hook=null where id=%s", (self.oid,))

    def test_footer_without_address_can_be_saved(self):
        r = self.call("/api/outreach/footer", {"text": '{{sender_name}}\nReply "no thanks" to stop.', "sender": {"postal_address": ""}})
        self.assertEqual(r.status_code, 200, r.text)


if __name__ == "__main__":
    unittest.main()
