"""Offline acceptance cases for researched startup searches and the credit pause.

Only local fixtures and mocked database callbacks are used. No API keys, network,
database connections, paid searches, enrichment or mail are involved.
"""
import copy
import datetime as dt
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import apollo
import apollo_policy
import startup_acquisitions
import startup_apollo


def config(slug="startup-acquisitions"):
    return json.loads((ROOT / "config" / ("segment." + slug + ".json")).read_text(encoding="utf-8"))


class StartupApolloTests(unittest.TestCase):
    def setUp(self):
        self.original = config()
        self.cfg = startup_apollo.configure(self.original)

    def test_twelve_searches_preserve_geographic_priority_and_fallbacks(self):
        searches = self.cfg["apollo_discovery"]["searches"]
        self.assertEqual(len(searches), 12)
        self.assertEqual(len({s["key"] for s in searches}), 12)
        expected_areas = [["Mumbai, India"], ["Navi Mumbai, India", "Thane, India"], ["India"]]
        for index, area in enumerate(expected_areas):
            group = searches[index * 4:(index + 1) * 4]
            self.assertEqual([s["filters"]["organization_locations"] for s in group], [area] * 4)
            self.assertIn("media_creator_consumer", group[0]["key"])
            self.assertIn("software_ai", group[1]["key"])
            self.assertIn("media_creator_consumer", group[2]["key"])
            self.assertIn("software_ai", group[3]["key"])
            self.assertEqual(group[0]["filters"]["q_organization_keyword_tags"],
                             group[2]["filters"]["q_organization_keyword_tags"])
            self.assertEqual(group[1]["filters"]["q_organization_keyword_tags"],
                             group[3]["filters"]["q_organization_keyword_tags"])
            for search in group:
                f = search["filters"]
                sizes = set()
                for band in f["organization_num_employees_ranges"]:
                    low, high = map(int, band.split(","))
                    sizes.update(range(low, high + 1))
                self.assertEqual(sizes, set(range(1, 51)))
                self.assertNotIn("revenue_range", f)
                self.assertNotIn("total_funding_range", f)
                self.assertNotIn("latest_funding_date_range", f)
                self.assertNotIn("founded_year", f)
                self.assertNotIn("400053", json.dumps(f))
            for search in group[:2]:
                self.assertEqual(search["filters"]["organization_headcount_growth_past_n_months"], 12)
                self.assertEqual(search["filters"]["organization_headcount_growth_range"], {"min": -100, "max": -10})
            for search in group[2:]:
                self.assertNotIn("organization_headcount_growth_past_n_months", search["filters"])
                self.assertNotIn("organization_headcount_growth_range", search["filters"])

    def test_each_preset_serializes_documented_apollo_parameters(self):
        for search in self.cfg["apollo_discovery"]["searches"]:
            with self.subTest(search=search["key"]):
                query = apollo.build_query("companies", search["filters"], page=1, per_page=100)
                self.assertIn(("page", "1"), query)
                self.assertIn(("per_page", "100"), query)
                for location in search["filters"]["organization_locations"]:
                    self.assertIn(("organization_locations[]", location), query)
                for keyword in search["filters"]["q_organization_keyword_tags"]:
                    self.assertIn(("q_organization_keyword_tags[]", keyword), query)
                if "decline_12m" in search["key"]:
                    self.assertIn(("organization_headcount_growth_past_n_months", "12"), query)
                    self.assertIn(("organization_headcount_growth_range[min]", "-100"), query)
                    self.assertIn(("organization_headcount_growth_range[max]", "-10"), query)
                else:
                    self.assertFalse(any(k.startswith("organization_headcount_growth") for k, _ in query))

    def test_manual_search_keeps_the_same_decline_window_and_can_only_narrow(self):
        selected = self.cfg["apollo_discovery"]["searches"][0]
        filters, _ = apollo_policy.constrained_filters(self.cfg, "companies", {
            "_project_search": selected["key"],
            "organization_headcount_growth_range": {"max": -20},
        })
        self.assertEqual(filters["organization_headcount_growth_range"], {"min": -100, "max": -20})
        self.assertEqual(filters["organization_headcount_growth_past_n_months"], 12)
        self.assertEqual(filters["organization_locations"], ["Mumbai, India"])
        with self.assertRaises(ValueError):
            apollo_policy.constrained_filters(self.cfg, "companies", {
                "_project_search": selected["key"], "organization_headcount_growth_past_n_months": 6})

    def test_configuration_is_pure_idempotent_and_preserves_outreach_and_scores(self):
        before = copy.deepcopy(self.original)
        changed = startup_apollo.configure(self.original)
        self.assertEqual(self.original, before)
        self.assertEqual(startup_apollo.configure(changed), changed)
        permitted = {"enrichment", "target_contact_roles", "apollo_discovery"}
        self.assertEqual({k: v for k, v in changed.items() if k not in permitted},
                         {k: v for k, v in before.items() if k not in permitted})
        self.assertEqual(changed["outreach"], before["outreach"])
        self.assertEqual(changed["rubric"], before["rubric"])
        self.assertEqual(changed["startup_acquisition"], before["startup_acquisition"])
        self.assertFalse(changed["enrichment"]["enabled"])
        self.assertEqual(changed["enrichment"]["credits_per_run"], 0)
        self.assertEqual(changed["enrichment"]["credits_per_week"], 0)
        self.assertFalse(changed["enrichment"]["include_similar_titles"])
        self.assertTrue(changed["enrichment"]["verified_only"])
        self.assertTrue(changed["enrichment"]["current_employer_check"])

    def test_pause_preserves_every_other_setting_and_clipping(self):
        for path in (ROOT / "config").glob("segment.*.json"):
            original = json.loads(path.read_text(encoding="utf-8"))
            before = copy.deepcopy(original)
            result = startup_apollo.pause(original)
            with self.subTest(project=path.name):
                self.assertEqual(original, before)
                self.assertEqual(startup_apollo.pause(result), result)
                if (original.get("enrichment") or {}).get("provider") == "apollo":
                    self.assertFalse(result["enrichment"]["enabled"])
                    self.assertEqual(result["enrichment"]["credits_per_run"], 0)
                    self.assertEqual(result["enrichment"]["credits_per_week"], 0)
                    self.assertEqual({k: v for k, v in result.items() if k != "enrichment"},
                                     {k: v for k, v in before.items() if k != "enrichment"})
                else:
                    self.assertEqual(result, original)

    def test_search_membership_does_not_manufacture_distress_or_price_evidence(self):
        now = dt.datetime(2026, 11, 16, 12, tzinfo=dt.timezone.utc)
        for search in self.cfg["apollo_discovery"]["searches"]:
            metadata = {
                "apollo": {"country": "India", "city": "Mumbai", "industry": "Software",
                           "estimated_num_employees": 2, "annual_revenue": 1000, "total_funding": 100,
                           "headcount_growth_12m": -50},
                "apollo_search": {"key": search["key"], "filters": search["filters"]},
                "site_health": {"status": "up"},
            }
            inputs, assessment = startup_acquisitions.assess(metadata, self.cfg, now)
            self.assertEqual(inputs["distress_current"], 0)
            self.assertEqual(inputs["affordability"], 0)
            self.assertEqual(inputs["salvage_value"], 0)
            self.assertFalse(assessment["price_confirmed"])
            self.assertFalse(assessment["contact_eligible"])

    def test_manual_paid_guard_exits_before_status_or_database_callbacks(self):
        from app import universal

        def forbidden(*args, **kwargs):
            raise AssertionError("Disabled spending must not consult Apollo or a database callback")

        self.assertIn("disabled", universal._budget(forbidden, "fixture", self.cfg, forbidden, 1))
        self.assertIn("disabled", universal._budget(forbidden, "fixture", self.cfg, forbidden, 100))

    def test_startup_contact_search_keeps_exact_verified_roles_without_widening(self):
        import enrich_apollo

        with patch.object(enrich_apollo.apollo, "search_people", return_value={"people": [], "total": 0}) as search:
            result = enrich_apollo.search("example.test", roles=startup_apollo.ROLES,
                verified_only=True, org_id="a" * 24, similar_titles=False)
        self.assertEqual(result, ([], 0))
        search.assert_called_once_with({
            "organization_ids": ["a" * 24],
            "person_titles": startup_apollo.ROLES,
            "include_similar_titles": False,
            "contact_email_status": ["verified"],
        }, 1, 10)

    def test_other_segments_retain_default_similar_titles_and_senior_fallback(self):
        import enrich_apollo

        person = {"title": "CEO", "has_email": True}
        with patch.object(enrich_apollo.apollo, "search_people", side_effect=[
                {"people": [], "total": 0}, {"people": [person], "total": 1}]) as search:
            result = enrich_apollo.search("example.test", roles=["Producer"], verified_only=True)
        self.assertEqual(result, ([person], 1))
        self.assertEqual(search.call_count, 2)
        self.assertEqual(search.call_args_list[0].args[0], {
            "q_organization_domains_list": ["example.test"], "person_titles": ["Producer"],
            "include_similar_titles": True, "contact_email_status": ["verified"],
        })
        self.assertEqual(search.call_args_list[1].args[0], {
            "q_organization_domains_list": ["example.test"], "contact_email_status": ["verified"],
        })

    def test_scheduled_discovery_uses_only_fake_config_read_before_disabled_exit(self):
        import discover_apollo

        class FakeCursor:
            def execute(self, statement, args):
                if not statement.startswith("select id, config from segments"):
                    raise AssertionError("Only the initial project-config read is permitted")

            def fetchone(inner):
                return ("fixture", self.cfg)

        class FakeDb:
            closed = False
            reads = 0

            def run(inner, callback):
                inner.reads += 1
                return callback(FakeCursor())

            def close(inner):
                inner.closed = True

        class NoApollo:
            def __getattr__(self, name):
                raise AssertionError("Apollo access is forbidden while paused: " + name)

        db = FakeDb()
        output = io.StringIO()
        with patch.object(discover_apollo, "SEGMENT", "startup-acquisitions"), \
             patch.object(discover_apollo, "Db", return_value=db), \
             patch.object(discover_apollo, "apollo", NoApollo()), \
             patch.object(sys, "argv", ["discover_apollo.py", "--pages", "100"]), \
             redirect_stdout(output):
            self.assertEqual(discover_apollo.main(), 0)
        self.assertIn("no calls or credits used", output.getvalue())
        self.assertEqual(db.reads, 1)
        self.assertTrue(db.closed)


if __name__ == "__main__":
    unittest.main()
