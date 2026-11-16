"""Offline Clipping Apollo acceptance tests. No database, network, credits or mail."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clipping_apollo as ca

NOW = dt.datetime(2026, 11, 16, 12, tzinfo=dt.timezone.utc)
PID, OID = "a" * 24, "b" * 24


def config(enabled=True):
    return {"clipping_apollo": {"enabled": enabled, "credits_per_run": 2, "credits_per_week": 2,
            "keep_in_reserve": 700, "score_over": 45, "max_lead_age_days": 14,
            "recheck_after_days": 30, "max_contacts_per_lead": 1,
            "roles": {"creator": ["Founder", "Creator", "Host", "Manager"],
                      "business": ["Founder", "Executive Producer", "Head of Content"]}},
            "hosting_providers": ["libsyn.com"], "geography": {"disallowed_countries": ["CA", "DE", "AT", "IT"]},
            "gates": [{"input": "metadata.scoring_inputs.activity_signal", "exclude_when": "confirmed_dormant"}]}


def lead():
    return {"id": "lead-1", "name": "Conversations with Example", "domain": "example.test",
        "status": "shortlisted", "fit_score": 80, "created_at": "2026-11-15T12:00:00+00:00",
        "metadata": {"podcast_feed": {"website": "https://example.test", "author": "Example Media LLC",
            "feed_url": "https://feed.test/show.xml"}, "creator_offers": {"priority": True},
            "scoring_inputs": {"activity_signal": "active"},
            "outreach_recipient": {"contact_id": "chosen-contact", "email": "chosen@example.test"}},
        "protected": False, "suppressed": False, "has_verified_contact": False}


def preview():
    return {"id": PID, "company": "Example Media", "company_id": OID,
            "has_email": True, "title": "Founder"}


def person():
    return {"apollo_id": PID, "name": "Sample Person", "email": "sample@example.test",
            "email_status": "valid", "apollo_email_status": "verified", "title": "Founder",
            "organization": {"id": OID, "name": "Example Media", "primary_domain": "example.test", "country": "United States"}}


class NoApollo:
    def __getattr__(self, key):
        raise AssertionError("Apollo must not be touched: " + key)


class FakeRepo:
    def __init__(self, cfg=None, rows=None):
        self.cfg, self.rows = cfg or config(), rows if rows is not None else [lead()]
        self.saved, self.reserved, self.settled = [], [], []
        self.block_reservation = False

    def config(self): return copy.deepcopy(self.cfg)
    def candidates(self, cfg, limit): return copy.deepcopy(self.rows[:limit])
    def reserve(self, row, who, balance, attempted):
        if self.block_reservation:
            return None
        self.reserved.append((row["id"], who["id"], balance, attempted))
        return len(self.reserved)
    def settle(self, reservation, credits): self.settled.append((reservation, credits))
    def save(self, row, outcome, match=None, result=None, who=None):
        self.saved.append((row, outcome, match, result))
        return outcome


class FakeApollo:
    def __init__(self, result=None):
        self.calls, self.balance = [], 1000
        self.result = result if result is not None else {"people": [person()], "credits": 0}
        self.previews = [preview()]
        self.raise_reveal = False
    def key_is_set(self): self.calls.append("key"); return True
    def credits(self): self.calls.append("balance"); return {"lead_credits_left": self.balance}
    def search_people(self, filters, page, size):
        self.calls.append(("search", filters)); return {"people": self.previews}
    def reveal_people(self, ids):
        self.calls.append(("reveal", ids))
        if self.raise_reveal:
            raise RuntimeError("Simulated uncertain network result")
        return self.result


class ClippingApolloTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(ca, "now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_disabled_or_zero_budget_makes_no_apollo_calls(self):
        for field, value in [("enabled", False), ("credits_per_run", 0), ("credits_per_week", 0), ("max_contacts_per_lead", 0)]:
            cfg = config(); cfg["clipping_apollo"][field] = value
            repo = FakeRepo(cfg)
            self.assertTrue(ca.run(repo, NoApollo())["paused"])
            self.assertFalse(repo.saved or repo.reserved)

    def test_unknown_balance_fails_before_search_or_reveal(self):
        api, repo = FakeApollo(), FakeRepo()
        api.balance = None
        self.assertIn("balance", ca.run(repo, api)["stopped"])
        self.assertEqual(api.calls, ["key", "balance"])
        self.assertFalse(repo.reserved)

    def test_only_verified_exact_role_preview_and_current_business_are_accepted(self):
        match = ca.business_match(lead(), config())
        self.assertIsNotNone(match)
        self.assertEqual(match["domain"], "example.test")
        for changed in [{"company": "Example Consulting"}, {"title": "Product Manager"},
                        {"has_email": False}, {"company_domain": "other.test"}]:
            self.assertIsNone(ca.preview_choice([dict(preview(), **changed)], match, ["Founder", "Manager"]))
        self.assertEqual(ca.preview_choice([preview()], match, ["Founder"])["id"], PID)
        self.assertIsNone(ca.revealed_reason(person(), preview(), match, ["Founder"], config()))

    def test_wrong_current_employer_is_rejected_even_with_matching_email(self):
        match = ca.business_match(lead(), config())
        for changes in [{"primary_domain": "different.test"}, {"id": "c"*24}, {"name": "Example Other"}]:
            value = person(); value["organization"].update(changes)
            self.assertEqual(ca.revealed_reason(value, preview(), match, ["Founder"], config()), "current-employer-mismatch")

    def test_unverified_personal_unrelated_role_and_excluded_country_are_rejected(self):
        match = ca.business_match(lead(), config())
        for changes in [{"apollo_email_status": "unverified"}, {"email_status": "catch_all"},
                        {"email": "sample@gmail.com"}, {"title": "Sales Manager"}, {"country": "Canada"},
                        {"apollo_id": "c"*24}]:
            self.assertIsNotNone(ca.revealed_reason(dict(person(), **changes), preview(), match, ["Founder"], config()))

    def test_youtube_arbitrary_sponsor_link_is_not_ownership(self):
        row = lead(); row["metadata"] = {"youtube_channel": {"title": "Example Media", "website": "https://example.test",
            "url": "https://www.youtube.com/channel/example", "description": "Sponsored by Example https://example.test"}}
        self.assertIsNone(ca.business_match(row, config()))
        row["metadata"]["youtube_channel"]["description"] = "Official website: https://example.test"
        self.assertIsNotNone(ca.business_match(row, config()))
        row["metadata"]["youtube_channel"]["description"] = "Guest's official website: https://example.test"
        self.assertIsNone(ca.business_match(row, config()))

    def test_hosts_shared_platforms_and_conflicting_domains_are_skipped(self):
        for url in ["https://show.libsyn.com", "https://patreon.com/show", "https://wrong.test"]:
            row = lead(); row["metadata"]["podcast_feed"]["website"] = url
            self.assertIsNone(ca.business_match(row, config()))

    def test_retired_protected_old_low_score_and_disqualified_leads_are_skipped(self):
        for changes in [{"status": "archived"}, {"status": "rejected"}, {"protected": True}, {"suppressed": True},
                        {"created_at": "2026-11-01T12:00:00+00:00"}, {"fit_score": 45}, {"has_verified_contact": True}]:
            self.assertIsNotNone(ca.eligibility_reason(dict(lead(), **changes), config()))
        row = lead(); row["metadata"]["scoring_inputs"]["activity_signal"] = "confirmed_dormant"
        self.assertEqual(ca.eligibility_reason(row, config()), "qualification-gate")

    def test_success_adds_one_contact_without_mutating_lead_or_selection(self):
        repo, api = FakeRepo(), FakeApollo()
        before = copy.deepcopy(repo.rows)
        result = ca.run(repo, api)
        self.assertEqual(result["added"], 1)
        self.assertEqual(len(repo.reserved), 1)
        self.assertEqual(repo.settled, [(1, 1)], "Omitted/normalised API credit field cannot make a returned person free")
        self.assertEqual(repo.rows, before)
        search = next(c[1] for c in api.calls if isinstance(c, tuple) and c[0] == "search")
        self.assertFalse(search["include_similar_titles"])
        self.assertEqual(search["contact_email_status"], ["verified"])
        self.assertEqual(repo.saved[-1][3]["email"], "sample@example.test")

    def test_failed_reservation_and_uncertain_request_do_not_retry(self):
        repo, api = FakeRepo(), FakeApollo()
        repo.block_reservation = True
        self.assertEqual(ca.run(repo, api)["reveals"], 0)
        self.assertFalse(any(isinstance(c, tuple) and c[0] == "reveal" for c in api.calls))
        repo, api = FakeRepo(), FakeApollo(); api.raise_reveal = True
        self.assertIn("retained", ca.run(repo, api)["stopped"])
        self.assertEqual(len(repo.reserved), 1)
        self.assertFalse(repo.settled)

    def test_confirmed_missing_result_releases_reserved_credit(self):
        repo = FakeRepo()
        ca.run(repo, FakeApollo({"people": [], "missing": [PID], "credits": 0}))
        self.assertEqual(repo.settled, [(1, 0)])
        self.assertIsNone(repo.saved[-1][3])

    def test_protected_save_rechecks_entity_and_does_not_write(self):
        queries = []
        row = lead(); row["protected"] = True
        class Cur:
            def execute(self, query, params): queries.append(query)
            def fetchone(self): return (config(),)
        class Db:
            def run(self, callback): return callback(Cur())
        repo = ca.Repository(Db())
        with patch.object(repo, "lead", return_value=row) as locked:
            self.assertEqual(repo.save(lead(), "added", ca.business_match(lead(), config()), person(), preview()), "protected")
        self.assertTrue(locked.call_args.kwargs["lock"])
        self.assertFalse(any(q.lower().startswith(("update", "insert", "delete")) for q in queries))

    def test_candidate_limit_applies_after_recent_and_existing_contact_filters(self):
        queries = []
        class Cur:
            def execute(self, query, params): queries.append((query, params))
            def fetchall(self): return []
        class Db:
            def run(self, callback): return callback(Cur())
        self.assertEqual(ca.Repository(Db()).candidates(config(), 7), [])
        query, params = queries[0]
        self.assertLess(query.index("clipping_apollo,checked_at"), query.index(" limit "))
        self.assertLess(query.index("c.email_status='valid'"), query.index(" limit "))
        self.assertEqual(params[-1], 7)

    def test_existing_public_contact_is_never_overwritten(self):
        queries = []
        class Cur:
            result = None
            def execute(inner, query, params):
                queries.append((query, params))
                if query.startswith("select config"):
                    inner.result = (config(),)
                elif query.startswith("select do_not_contact"):
                    inner.result = (None,)
                elif query.startswith("select id from contacts"):
                    inner.result = ("existing-public-contact",)
                else:
                    inner.result = None
            def fetchone(inner): return inner.result
        class Db:
            def run(self, callback): return callback(Cur())
        repo = ca.Repository(Db())
        with patch.object(repo, "lead", return_value=lead()), patch.object(ca.apollo_store, "upsert_person") as upsert:
            result = repo.save(lead(), "added", ca.business_match(lead(), config()), person(), preview())
        self.assertEqual(result, "existing-contact-preserved")
        upsert.assert_not_called()
        updates = [q for q, _ in queries if q.startswith("update")]
        self.assertEqual(len(updates), 1)
        self.assertIn("'{clipping_apollo}'", updates[0])
        self.assertNotIn("outreach", updates[0])

    def test_reservation_is_idempotent_and_checks_budget_under_project_lock(self):
        queries, state = [], {"reserved": False}
        class Cur:
            result = None
            def execute(inner, query, params):
                queries.append(query)
                if query.startswith("select id,config from segments"):
                    inner.result = ("segment-1", config())
                elif query.startswith("select id from apollo_spend"):
                    inner.result = (1,) if state["reserved"] else None
                elif query.startswith("insert into apollo_spend"):
                    self.assertFalse(state["reserved"])
                    self.assertEqual(params, ("segment-1", "clipping-apollo:lead-1:" + PID))
                    state["reserved"], inner.result = True, (1,)
                else:
                    inner.result = None
            def fetchone(inner): return inner.result
        class Db:
            def run(self, callback): return callback(Cur())
        repo = ca.Repository(Db())
        with patch.object(repo, "lead", return_value=lead()), \
                patch.object(ca.apollo_budget, "allowance", return_value=(1, "test budget")) as allowance:
            self.assertEqual(repo.reserve(lead(), preview(), 1000, 0), 1)
            self.assertIsNone(repo.reserve(lead(), preview(), 1000, 0))
            self.assertIsNone(repo.reserve(lead(), preview(), None, 0))
        allowance.assert_called_once()
        self.assertIn("for update", queries[0])
        self.assertEqual(sum(q.startswith("insert into apollo_spend") for q in queries), 1)

    def test_run_cap_is_not_bypassed_when_returned_people_lack_credit_amount(self):
        rows = [dict(lead(), id="lead-"+str(i)) for i in range(5)]
        repo, api = FakeRepo(rows=rows), FakeApollo()
        result = ca.run(repo, api)
        self.assertEqual(result["reveals"], 2)
        self.assertEqual(len(repo.reserved), 2)
        self.assertEqual(repo.settled, [(1, 1), (2, 1)])


if __name__ == "__main__":
    unittest.main()
