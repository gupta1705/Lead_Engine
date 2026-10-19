#!/usr/bin/env python3
"""Recipient preference checks; --db adds read-only database policy checks.

The database checks use synthetic CTE rows and an existing Apollo project ID so
the real contact_allowed/contact_rank functions run. No row is inserted or
updated, and the connection is explicitly read-only.
"""
import json
import sys
import unittest
import uuid
from unittest.mock import patch

from recipient_selection import CONTACT_SELECTION_SQL, recipient_metadata, select_contact

RUN_DB = "--db" in sys.argv
if RUN_DB:
    sys.argv.remove("--db")


class SelectionHelpers(unittest.TestCase):
    def test_tuple_cursor_returns_named_columns(self):
        class Cursor:
            description = [("id",), ("email",), ("recipient_rank",)]

            def execute(self, sql, params):
                self.sql, self.params = sql, params

            def fetchone(self):
                return ("contact", "person@example.com", 80)

        cur = Cursor()
        self.assertEqual(select_contact(cur, "entity"),
                         {"id": "contact", "email": "person@example.com", "recipient_rank": 80})
        self.assertEqual(cur.params, ("entity",))

    def test_dictionary_cursor_and_no_contact(self):
        class Cursor:
            def execute(self, sql, params):
                pass

            def fetchone(self):
                return self.row

        cur = Cursor()
        cur.row = {"id": "contact", "email": "person@example.com"}
        self.assertEqual(select_contact(cur, "entity"), cur.row)
        cur.row = None
        self.assertIsNone(select_contact(cur, "entity"))

    def test_manual_choice_suppresses_only_old_host_fallback(self):
        original = {"host": {"first_name": "Someone Else"}, "kind": "podcast",
                    "outreach_recipient": {"contact_id": "chosen"}}
        cleaned = recipient_metadata(original)
        self.assertNotIn("host", cleaned)
        self.assertEqual(cleaned["kind"], "podcast")
        self.assertIn("host", original)
        automatic = {"host": {"first_name": "Usual Host"}}
        self.assertIs(recipient_metadata(automatic), automatic)

    def test_compose_greeting_uses_chosen_person(self):
        from outreach_compose import fields_for
        row = {"name": "Example Studio", "full_name": "Beth Carter",
               "email": "beth@example.com", "source": "apollo",
               "metadata": {"host": {"first_name": "Wrong", "confidence": "high"},
                            "outreach_recipient": {"contact_id": "chosen"}}}
        self.assertEqual(fields_for(row)["first_name"], "Beth")
        row.update(full_name=None, email="info@example.com")
        self.assertEqual(fields_for(row)["first_name"], "there")


class ApprovalPreferenceGuards(unittest.TestCase):
    def row(self, **changes):
        return {"id": "draft", "slug": "project", "direction": "outbound", "status": "drafted",
                "subject": "Subject", "body": "Hello Beth,\nA reviewed email.", "sequence_step": 0,
                "generated_hook": None, "email": "beth@example.com", "email_status": "valid",
                "verified_allowed": True, "service_matches": True, "entity_status": "shortlisted",
                "entity_name": "Example Studio", "entity_id": "entity", "attachments": None,
                **changes}

    def approve(self, row):
        import outreach_policy as pol

        class Cursor:
            description = [(key,) for key in row]

            def execute(self, sql, params):
                pass

            def fetchall(self):
                return [row]

            def fetchone(self):
                return None

        with patch.object(pol, "refresh_attachments"), patch.object(pol, "answered_elsewhere", return_value=None):
            return pol.check_drafts(Cursor(), ["draft"], "project")

    def test_stale_selection_blocks_approval_with_clear_reason(self):
        import outreach_policy as pol
        for match in (False, None):
            with self.subTest(match=match):
                self.assertEqual(self.approve(self.row(selected_recipient_matches=match)),
                                 ([], [{"id": "draft", "reason": pol.SELECTED_RECIPIENT_REASON}]))

    def test_valid_selection_and_legacy_mock_rows_still_approve(self):
        self.assertEqual(self.approve(self.row(selected_recipient_matches=True)), (["draft"], []))
        self.assertEqual(self.approve(self.row()), (["draft"], []))


@unittest.skipUnless(RUN_DB, "use --db for read-only live policy checks")
class ReadOnlyDatabaseSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from run_sql import load_db_url
        cls.conn = psycopg2.connect(load_db_url())
        cls.conn.set_session(readonly=True, autocommit=False)
        cls.cur = cls.conn.cursor()
        cls.cur.execute("select e.id from entities e join segments s on s.id=e.segment_id"
                        " where s.config->'sourcing'->>'contacts'='apollo' limit 1")
        got = cls.cur.fetchone()
        if not got:
            cls.conn.close()
            raise unittest.SkipTest("No existing Apollo-policy entity to exercise")
        cls.entity_id = str(got[0])
        cls.ids = [str(uuid.uuid4()) for _ in range(6)]
        cls.contacts = [
            {"id": cls.ids[0], "full_name": "Alice Adams", "email": "alice@example.com",
             "role_title": "Chief Executive Officer"},
            {"id": cls.ids[1], "full_name": "Beth Carter", "email": "beth@example.com",
             "role_title": "Manager"},
            {"id": cls.ids[2], "full_name": "Carol Jones", "email": "carol@example.com",
             "email_status": "unknown"},
            {"id": cls.ids[3], "full_name": "Dana Smith", "email": "dana@example.com",
             "source": "site", "verifier": "smtp"},
            {"id": cls.ids[4], "full_name": "Invalid Person", "email": "invalid@example.com",
             "email_status": "invalid"},
            {"id": cls.ids[5], "entity_id": str(uuid.uuid4()), "full_name": "Other Lead",
             "email": "other@example.com"},
        ]
        cls.contacts = [{"entity_id": cls.entity_id, "source": "apollo", "verifier": "apollo",
                         "email_status": "valid", "role_title": None,
                         "created_at": "2026-01-01T00:00:00Z", **c} for c in cls.contacts]

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def pick(self, metadata):
        self.cur.execute("""
            with entities as (select %s::uuid as id, %s::jsonb as metadata, 'example.com'::text as domain),
            contacts as (
                select * from jsonb_to_recordset(%s::jsonb) as c(
                    id uuid, entity_id uuid, full_name text, email text, source text,
                    role_title text, email_status text, verifier text, created_at timestamptz)
            )
            select c.id from entities e join lateral (
            """ + CONTACT_SELECTION_SQL + ") c on true",
                         (self.entity_id, json.dumps(metadata), json.dumps(self.contacts)))
        row = self.cur.fetchone()
        return str(row[0]) if row else None

    def preference(self, index, **changes):
        return {"outreach_recipient": {"contact_id": self.ids[index],
                                       "email": self.contacts[index]["email"], **changes}}

    def guard(self, metadata, contact_index):
        from outreach_policy import SELECTED_RECIPIENT_SQL
        self.cur.execute("""
            with entities as (select %s::uuid as id, %s::jsonb as metadata, 'example.com'::text as domain),
            contacts as (
                select * from jsonb_to_recordset(%s::jsonb) as c(
                    id uuid, entity_id uuid, full_name text, email text, source text,
                    role_title text, email_status text, verifier text, created_at timestamptz)
            )
            select """ + SELECTED_RECIPIENT_SQL + " from entities e join contacts c on c.id=%s::uuid",
                         (self.entity_id, json.dumps(metadata), json.dumps(self.contacts), self.ids[contact_index]))
        return self.cur.fetchone()[0]

    def test_no_preference_preserves_best_rank(self):
        self.assertEqual(self.pick({}), self.ids[0])

    def test_lower_rank_chosen_contact_wins_and_email_case_is_accepted(self):
        self.assertEqual(self.pick(self.preference(1)), self.ids[1])
        self.assertEqual(self.pick(self.preference(1, email=" BETH@EXAMPLE.COM ")), self.ids[1])

    def test_stale_or_malformed_preference_holds_instead_of_fallback(self):
        for pref in (self.preference(1, email="old@example.com"),
                     self.preference(1, contact_id="not-a-uuid"),
                     {"outreach_recipient": None}, {"outreach_recipient": "bad"},
                     {"outreach_recipient": {}}):
            with self.subTest(preference=pref):
                self.assertIsNone(self.pick(pref))

    def test_unverified_foreign_source_invalid_and_foreign_entity_are_held(self):
        for index in (2, 3, 4, 5):
            with self.subTest(index=index):
                self.assertIsNone(self.pick(self.preference(index)))

    def test_approval_and_sender_guard_enforce_saved_recipient(self):
        self.assertTrue(self.guard({}, 0))
        self.assertTrue(self.guard(self.preference(1), 1))
        self.assertFalse(self.guard(self.preference(1), 0))
        self.assertFalse(self.guard(self.preference(1, email="old@example.com"), 1))
        for index in (2, 3, 4, 5):
            with self.subTest(index=index):
                self.assertFalse(self.guard(self.preference(index), index))

    def test_guarded_policy_pick_and_claim_queries_parse_without_sending(self):
        import outreach
        import outreach_policy as pol
        self.cur.execute(pol.CHECK_SQL, ([],))
        self.assertEqual(self.cur.fetchall(), [])
        self.cur.execute(outreach.PICK_SQL, {"segment": "lcx-services", "timed": True, "n": 0})
        self.assertEqual(self.cur.fetchall(), [])
        # EXPLAIN without ANALYZE only plans the update. This read-only session
        # cannot claim any email or execute a Gmail/network operation.
        self.cur.execute("explain (format json) " + outreach.CLAIM_SQL,
                         ("test-mailbox", "sender@example.com", str(uuid.uuid4())))
        self.assertIsNotNone(self.cur.fetchone())


if __name__ == "__main__":
    unittest.main()
