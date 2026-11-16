"""Pure lead-detail payload regression: fake reads, real contact ranking, no database or API."""
import copy
import datetime as dt
import json
import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools"), str(ROOT)]
os.environ.setdefault("SESSION_SECRET", "offline-clipping-payload-test-only")
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["SEND_LOOP_ENABLED"] = "0"

import main
import explain
import recipient_selection
from configure_clipping_apollo import configure

LEAD = "00000000-0000-4000-8000-000000000001"
PUBLIC = "00000000-0000-4000-8000-000000000002"
APOLLO = "00000000-0000-4000-8000-000000000003"
PID = "a" * 24
CHECKED = dt.datetime(2026, 11, 16, 12, tzinfo=dt.timezone.utc)


class PayloadTests(unittest.TestCase):
    def payload(self, note="apollo:" + PID, enabled=False, run_budget=0, week_budget=0):
        cfg = configure(json.loads((ROOT / "config/segment.lcx-clipping.json").read_text(encoding="utf-8")))
        cfg["clipping_apollo"].update(enabled=enabled, credits_per_run=run_budget, credits_per_week=week_budget)
        lead = {"id": LEAD, "segment_id": LEAD, "segment_slug": "lcx-clipping", "segment_config": cfg,
                "name": "Fixture Show", "domain": "example.test", "status": "shortlisted",
                "metadata": {"outreach_recipient": {"contact_id": PUBLIC},
                             "clipping_apollo": {"person_id": PID, "checked_at": CHECKED.isoformat(),
                                 "match": {"business_name": "Fixture Studio", "domain": "example.test"}}}}
        contacts = [
            {"id": PUBLIC, "full_name": "Fixture Show", "email": "hello@example.test", "email_status": "unverified",
             "role_title": None, "is_primary": True, "source": "podcast_rss", "notes": "private source detail",
             "verifier": None, "email_verified_at": None, "linkedin_url": None, "contact_allowed": True, "rank": 10},
            {"id": APOLLO, "full_name": "Alex Example", "email": "alex@example.test", "email_status": "valid",
             "role_title": "Executive Producer", "is_primary": False, "source": "apollo", "notes": note,
             "verifier": "apollo", "email_verified_at": CHECKED, "linkedin_url": None,
             "contact_allowed": True, "rank": 100},
        ]

        class FakeCursor:
            statements = []

            def execute(self, statement, args):
                self.statements.append(statement)
                if statement.startswith("select e.*, s.slug"):
                    self.answer = copy.deepcopy(lead)
                elif statement.startswith("select c.id, c.full_name"):
                    if "c.verifier, c.email_verified_at" not in statement:
                        raise AssertionError("The API must request contact verification provenance")
                    self.answer = copy.deepcopy(contacts)
                elif statement.startswith("select id, contact_id, status, subject"):
                    self.answer = None
                elif statement.startswith("select direction,status from outreach"):
                    self.answer = []
                else:
                    raise AssertionError("Unexpected query or mutation in read-only fixture: " + statement)

            def fetchone(self):
                return self.answer

            def fetchall(self):
                return self.answer

        cur = FakeCursor()

        @contextmanager
        def fake_cursor():
            yield cur

        with patch.object(main, "cursor", fake_cursor), \
             patch.object(recipient_selection, "select_contact", return_value={"id": PUBLIC}), \
             patch.object(explain, "explain_lead", return_value={"criteria": []}), \
             patch("psycopg2.connect", side_effect=AssertionError("No database connections allowed")):
            result = main.lead(LEAD, segment="lcx-clipping")
        self.assertEqual(len(cur.statements), 4)
        return result

    def test_verified_provenance_survives_actual_ranker_without_raw_notes(self):
        result = self.payload()
        by_id = {c["id"]: c for c in result["contacts"]}
        self.assertTrue(all("notes" not in c for c in result["contacts"]))
        self.assertEqual(by_id[APOLLO]["apollo_person_id"], PID)
        self.assertEqual(by_id[APOLLO]["verifier"], "apollo")
        self.assertEqual(by_id[APOLLO]["email_verified_at"], CHECKED)
        self.assertEqual(result["metadata"]["clipping_apollo"]["person_id"], PID)
        self.assertEqual(result["selected_recipient_id"], PUBLIC)
        self.assertTrue(by_id[PUBLIC]["selected_recipient"])
        self.assertFalse(by_id[APOLLO]["selected_recipient"])
        self.assertTrue(by_id[APOLLO]["can_select_recipient"])
        self.assertIsNone(result["outreach"])

    def test_unstructured_contact_notes_are_never_exposed_as_person_ids(self):
        result = self.payload(note="apollo:" + PID + "; private note")
        contact = next(c for c in result["contacts"] if c["id"] == APOLLO)
        self.assertNotIn("notes", contact)
        self.assertNotIn("apollo_person_id", contact)

    def test_pause_indicator_requires_flag_and_both_positive_budgets(self):
        for enabled, run, week, expected in [(False, 0, 0, False), (True, 0, 10, False),
                                            (True, 10, 0, False), (False, 10, 10, False),
                                            (True, 10, 10, True)]:
            with self.subTest(enabled=enabled, run=run, week=week):
                result = self.payload(enabled=enabled, run_budget=run, week_budget=week)
                self.assertEqual(result["apollo_contact_matching"], {"enabled": expected, "spending_enabled": expected})


if __name__ == "__main__":
    unittest.main()
