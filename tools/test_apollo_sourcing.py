#!/usr/bin/env python3
"""Apollo intake regression checks. DB fixtures run in a rolled-back transaction; no API credits spent."""
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import apollo
import discover_apollo as new
import discover_lcx_services as discovery
import enrich_lcx_services as lift

PROJECTS = ("us-production-houses", "startup-acquisitions", "lcx-services", "universal")


def config(slug):
    return json.loads((ROOT / "config" / ("segment." + slug + ".json")).read_text(encoding="utf-8"))


class PolicyTests(unittest.TestCase):
    def test_constraints_and_clipping_preserved(self):
        for slug in (*PROJECTS, "lcx-clipping"):
            current = config(slug)
            before = json.loads(subprocess.check_output(
                ["git", "show", "HEAD:config/segment." + slug + ".json"], cwd=ROOT))
            if slug == "lcx-clipping":
                self.assertEqual(current, before)
            for key in ("rubric", "gates", "score_modifiers", "self_exclusion", "auto_shortlist", "outreach", "target_contact_roles"):
                self.assertEqual(current.get(key), before.get(key), (slug, key))

    def test_all_non_clipping_projects_use_apollo(self):
        old_jobs = {"discover_startup_news", "discover_lcx_wikidata", "discover_lcx_osm", "discover_lcx_fdic",
                    "resolve_domains", "enrich_aicp", "enrich_contacts", "enrich_contacts_lcxs"}
        for slug in PROJECTS:
            c = config(slug)
            self.assertEqual(c["sourcing"]["provider"], "apollo")
            self.assertEqual(c["sourcing"]["contacts"], "apollo")
            self.assertTrue(all(s["slug"] in c["sourcing"]["allowed_sources"] for s in c["sources"]))
            for steps in c["pipelines"].values():
                self.assertFalse(old_jobs.intersection(steps), slug)

    def test_mumbai_locations_are_not_replaced_by_country(self):
        c = config("startup-acquisitions")
        sl = discovery.apollo_slices(c)[0]
        f = discovery.apollo_filters(sl)
        self.assertEqual(f["organization_locations"], ["Mumbai, India", "Navi Mumbai, India", "Thane, India"])

    def test_lcx_has_all_audiences_and_worldwide_coverage(self):
        c = config("lcx-services")
        self.assertEqual({a["key"] for a in c["audiences"]}, {s["audience"] for s in c["apollo_discovery"]["searches"]})
        sl = next(s for s in discovery.apollo_slices(c) if s["country"]["iso"] == "ALL")
        f = discovery.apollo_filters(sl)
        self.assertNotIn("organization_locations", f)
        self.assertIn("Canada", f["organization_not_locations"])
        self.assertIn("Russia", f["organization_not_locations"])

    def test_company_record_is_lifted_without_inventing_qualification(self):
        c = config("us-production-houses")
        sl = discovery.apollo_slices(c)[0]
        org = {"id": "a" * 24, "name": "Example Film", "primary_domain": "examplefilm.test", "country": "United States"}
        row, why = new.company_row(org, sl, None, c)
        self.assertIsNone(why)
        meta, email, source = lift.lift({"discovery_raw": {"apollo": row["raw"]}})
        self.assertEqual(meta["apollo"]["id"], org["id"])
        self.assertEqual(meta["hq_country"], "US")
        self.assertIsNone(email)
        self.assertEqual(row["raw"]["scoring_inputs"], {"has_reachable_presence": True, "geography_signal": "us"})
        org["country"] = "Canada"
        self.assertIsNone(new.company_row(org, sl, None, c)[0])
        org.update(name="The Viral Fever", primary_domain="theviralfever.com", country="United States")
        self.assertIsNone(new.company_row(org, sl, None, c)[0])

    def test_dry_run_never_buys_or_moves_cursor(self):
        c = config("us-production-houses")
        with patch.object(discovery, "load_cursors", return_value={}), \
             patch.object(discovery, "precheck", return_value=100), \
             patch.object(apollo, "search_companies") as buy, \
             patch.object(discovery, "save_cursor") as save:
            rows, _, pages = discovery.run_apollo(None, "fixture", c, 1, set(), set(),
                dry_run=True, row_builder=new.company_row, strict=True)
        self.assertEqual((rows, pages), ([], 1))
        buy.assert_not_called()
        save.assert_not_called()

    def test_apollo_failure_is_a_failure_not_a_successful_empty_harvest(self):
        with patch.object(discovery, "load_cursors", return_value={}), \
             patch.object(discovery, "precheck", side_effect=apollo.ApolloError("unavailable", status=503)):
            with self.assertRaises(apollo.ApolloError):
                discovery.run_apollo(None, "fixture", config("us-production-houses"), 1, set(), set(),
                    row_builder=new.company_row, strict=True)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from run_sql import load_db_url
        cls.conn = psycopg2.connect(load_db_url(), connect_timeout=20)
        cls.cur = cls.conn.cursor()
        cls.cur.execute((ROOT / "sql/37_apollo_sourcing.sql").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def setUp(self):
        self.cur.execute("savepoint test_case")

    def tearDown(self):
        self.cur.execute("rollback to savepoint test_case")

    def project(self, cfg):
        slug = "zz-apollo-" + uuid.uuid4().hex[:12]
        self.cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Test','company',%s) returning id",
                         (slug, json.dumps(cfg)))
        return self.cur.fetchone()[0], slug

    def test_old_connectors_blocked_for_every_target_but_clipping_allowed(self):
        import psycopg2
        for slug in PROJECTS:
            sid, _ = self.project(config(slug))
            for table in ("staging_candidates", "entities"):
                self.cur.execute("savepoint refused")
                with self.assertRaises(psycopg2.errors.CheckViolation):
                    self.cur.execute("insert into " + table + "(segment_id,name,source) values(%s,'Legacy','wikidata')", (sid,))
                self.cur.execute("rollback to savepoint refused")
                self.cur.execute("insert into " + table + "(segment_id,name,source) values(%s,'Apollo','apollo')", (sid,))
        sid, _ = self.project(config("lcx-clipping"))
        self.cur.execute("insert into staging_candidates(segment_id,name,source) values(%s,'Podcast','apple_podcasts')", (sid,))

    def test_legacy_pending_staging_is_not_promoted(self):
        sid, slug = self.project({})
        self.cur.execute("insert into staging_candidates(segment_id,name,domain,source) values(%s,'Old','old.test','wikidata')", (sid,))
        self.cur.execute("update segments set config=%s where id=%s", (json.dumps(config("us-production-houses")), sid))
        self.cur.execute("insert into staging_candidates(segment_id,name,domain,source) values(%s,'New','new.test','apollo')", (sid,))
        self.cur.execute("select set_config('tvf.segment',%s,true)", (slug,))
        self.cur.execute((ROOT / "sql/05_promote_minimal.sql").read_text(encoding="utf-8"))
        self.cur.execute("select name,source from entities where segment_id=%s", (sid,))
        self.assertEqual(self.cur.fetchall(), [("New", "apollo")])
        self.cur.execute("select imported from staging_candidates where segment_id=%s and source='wikidata'", (sid,))
        self.assertFalse(self.cur.fetchone()[0])

    def test_contact_policy_keeps_website_evidence_separate(self):
        import psycopg2
        sid, _ = self.project(config("lcx-services"))
        self.cur.execute("insert into entities(segment_id,name,source) values(%s,'Company','apollo') returning id", (sid,))
        eid = self.cur.fetchone()[0]
        self.cur.execute("savepoint contact_refused")
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.cur.execute("insert into contacts(entity_id,email,source) values(%s,'test@example.test','site_scrape')", (eid,))
        self.cur.execute("rollback to savepoint contact_refused")
        self.cur.execute("insert into contacts(entity_id,email,source) values(%s,'test@example.test','apollo')", (eid,))

    def test_discovery_stages_the_page_and_resumes_without_rebuying(self):
        cfg = config("us-production-houses")
        cfg["apollo_discovery"]["searches"] = cfg["apollo_discovery"]["searches"][:1]
        sid, slug = self.project(cfg)
        cursor = self.cur

        class TransactionDb:
            def run(self, fn):
                return fn(cursor)

            def close(self):
                pass

        org = {"id": "b" * 24, "name": "Fixture Film", "primary_domain": uuid.uuid4().hex + ".test"}
        with patch.object(new, "SEGMENT", slug), patch.object(new, "Db", TransactionDb), \
             patch.object(apollo, "key_is_set", return_value=True), \
             patch.object(apollo, "credits", return_value={"lead_credits_left": 2000}), \
             patch.object(discovery, "precheck", return_value=1), \
             patch.object(discovery.time, "sleep"), \
             patch.object(apollo, "search_companies", return_value={"companies": [org], "total_pages": 1}) as buy, \
             patch.object(sys, "argv", ["discover_apollo.py", "--pages", "1"]):
            self.assertEqual(new.main(), 0)
            self.assertEqual(new.main(), 0)
            self.assertEqual(buy.call_count, 1)
        self.cur.execute("select source,raw->'apollo'->>'id' from staging_candidates where segment_id=%s", (sid,))
        self.assertEqual(self.cur.fetchall(), [("apollo", org["id"])])
        self.cur.execute("select sum(credits) from apollo_spend where segment_id=%s", (sid,))
        self.assertEqual(float(self.cur.fetchone()[0]), 1)
        self.cur.execute("select next_page,exhausted_at is not null from apollo_cursors where segment_id=%s", (sid,))
        self.assertEqual(self.cur.fetchall(), [(2, True)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
