"""Offline regression checks for saved Apollo search constraints. No DB/API calls."""
import copy
import unittest
from unittest.mock import patch

import apollo
import apollo_policy as policy


GROWTH = "organization_headcount_growth_range"
WINDOW = "organization_headcount_growth_past_n_months"


def config():
    return {
        "sourcing": {"contacts": "apollo"},
        "target_contact_roles": ["Founder", "CEO"],
        "enrichment": {"reveal_countries": ["IN"], "include_similar_titles": False},
        "apollo_discovery": {
            "countries": [{"iso": "IN", "name": "India"}],
            "searches": [{"key": "mumbai_decline", "filters": {
                "organization_locations": ["Mumbai, India"],
                "organization_num_employees_ranges": ["1,10", "11,50"],
                WINDOW: 12, GROWTH: {"min": -100, "max": -10}}}],
        },
    }


class RangeConstraintTests(unittest.TestCase):
    def setUp(self):
        # Any accidental account request makes these tests fail before network IO.
        self.network = patch.object(apollo, "_call", side_effect=AssertionError("No Apollo calls allowed"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.cfg = config()

    def filters(self, overrides=None, kind="companies"):
        return policy.constrained_filters(self.cfg, kind, overrides or {})[0]

    def test_default_signed_range_survives_query_serialization(self):
        actual = self.filters()
        self.assertEqual(actual[GROWTH], {"min": -100, "max": -10})
        query = dict(apollo.build_query("companies", actual))
        self.assertEqual(query[GROWTH + "[min]"], "-100")
        self.assertEqual(query[GROWTH + "[max]"], "-10")
        self.assertEqual(query[WINDOW], "12")

    def test_narrowing_a_signed_range_keeps_both_user_bounds(self):
        self.assertEqual(self.filters({GROWTH: {"min": -50, "max": -20}})[GROWTH],
                         {"min": -50, "max": -20})

    def test_wider_range_is_intersected_not_allowed_to_expand(self):
        self.assertEqual(self.filters({GROWTH: {"min": -150, "max": 80}})[GROWTH],
                         {"min": -100, "max": -10})
        with self.assertRaises(ValueError):
            self.filters({GROWTH: {"min": -5, "max": 20}})

    def test_upper_bound_alone_does_not_imply_zero_lower_bound(self):
        self.cfg["apollo_discovery"]["searches"][0]["filters"][GROWTH] = {"max": -10}
        self.assertEqual(self.filters()[GROWTH], {"max": -10})
        self.assertEqual(self.filters({GROWTH: {"max": -20}})[GROWTH], {"max": -20})
        self.assertEqual(self.filters({GROWTH: {"min": -50}})[GROWTH],
                         {"min": -50, "max": -10})

    def test_zero_numeric_bound_is_retained(self):
        locked = self.cfg["apollo_discovery"]["searches"][0]["filters"]
        locked.pop(WINDOW)
        locked.pop(GROWTH)
        locked["revenue_range"] = {"min": 0, "max": 1000}
        self.assertEqual(self.filters({"revenue_range": {"max": 0}})["revenue_range"],
                         {"min": 0, "max": 0})

    def test_window_cannot_change_and_string_equivalent_is_accepted(self):
        self.assertEqual(self.filters({WINDOW: "12"})[WINDOW], 12)
        for changed in (6, "24", 0):
            with self.subTest(window=changed), self.assertRaises(ValueError):
                self.filters({WINDOW: changed})

    def test_boolean_false_constraint_is_not_treated_as_unset(self):
        self.assertIs(self.filters(kind="people")["include_similar_titles"], False)
        for equivalent in (False, "false", "0", 0):
            with self.subTest(value=equivalent):
                self.assertIs(self.filters({"include_similar_titles": equivalent}, "people")
                              ["include_similar_titles"], False)
        for different in (True, "true", "1", 1):
            with self.subTest(value=different), self.assertRaises(ValueError):
                self.filters({"include_similar_titles": different}, "people")

    def test_mumbai_people_search_stays_in_mumbai(self):
        result = self.filters(kind="people")
        self.assertEqual(result["organization_locations"], ["Mumbai, India"])
        self.assertEqual(result["person_titles"], ["Founder", "CEO"])
        self.assertEqual(result["contact_email_status"], ["verified"])
        for location in ("India", "Delhi, India", "United States"):
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.filters({"organization_locations": [location]}, "people")

    def test_reveal_country_can_narrow_a_country_union(self):
        self.cfg["apollo_discovery"]["searches"][0]["filters"]["organization_locations"] = ["India", "United States"]
        self.assertEqual(self.filters(kind="people")["organization_locations"], ["India"])

    def test_disjoint_reveal_country_fails_without_replacing_saved_search(self):
        self.cfg["enrichment"]["reveal_countries"] = ["US"]
        with self.assertRaises(ValueError):
            self.filters(kind="people")

    def test_inputs_are_not_mutated(self):
        before = copy.deepcopy(self.cfg)
        given = {GROWTH: {"max": -20}}
        self.filters(given)
        self.assertEqual(self.cfg, before)
        self.assertEqual(given, {GROWTH: {"max": -20}})


if __name__ == "__main__":
    unittest.main()
