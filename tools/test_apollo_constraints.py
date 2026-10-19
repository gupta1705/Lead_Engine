"""Apollo-only routing, verified email and manual-policy regression tests.

All API answers are mocked. Database cases roll back. No credits or emails.
"""
import copy
import json
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import apollo
import apollo_policy as policy
import apollo_store
import discover_lcx_services as discovery
import lcx_judge
from app import universal


def config(slug="lcx-services"):
    return json.loads((ROOT / "config" / ("segment." + slug + ".json")).read_text(encoding="utf-8"))


class PolicyTests(unittest.TestCase):
    def test_verified_is_checked_after_reveal(self):
        for status in ("unverified", "extrapolated", "guessed", "catch_all", "accept_all", None):
            self.assertFalse(policy.verified(apollo.person_record({"email": "person@company.test", "email_status": status})))
        self.assertTrue(policy.verified(apollo.person_record({"email": "person@company.test", "email_status": "verified"})))
        self.assertFalse(policy.verified({"email": "person@company.test", "email_status": "valid"}))

    def test_every_project_search_preserves_automatic_filters(self):
        for slug in ("lcx-services", "us-production-houses", "startup-acquisitions"):
            cfg = config(slug)
            for s in policy.searches(cfg):
                with self.subTest(project=slug, search=s["key"]):
                    actual, selected = policy.constrained_filters(cfg, "companies", {policy.TARGET: s["key"]})
                    self.assertEqual(selected, s)
                    expected = discovery.apollo_filters({"search": s, "country": {"iso": "ALL"}})
                    for key, value in expected.items():
                        self.assertEqual(actual[key], value, key)
                    apollo.build_query("companies", actual)

    def test_manual_cannot_widen_size_keywords_geography_or_email_status(self):
        cfg = config()
        key = next(s["key"] for s in policy.searches(cfg) if s.get("audience") == "consumer_brands" and not s.get("signal"))
        for filters in ({"organization_num_employees_ranges": ["5001,10000"]},
                        {"q_text": "German mining companies"},
                        {"organization_locations": ["Germany"]},
                        {"q_organization_keyword_tags": ["weapons"]}):
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                policy.constrained_filters(cfg, "companies", {policy.TARGET: key, **filters})
        f, _ = policy.constrained_filters(config("universal"), "people", {"contact_email_status": ["unverified"]})
        self.assertEqual(f["contact_email_status"], ["verified"])
        f, _ = policy.constrained_filters(cfg, "companies", {policy.TARGET: key, "organization_num_employees_ranges": ["21,50"]})
        self.assertEqual(f["organization_num_employees_ranges"], ["21,50"])

    def test_contradictory_apollo_facts_fail_both_manual_and_automatic(self):
        cfg = config()
        sl = discovery.apollo_slices(cfg)[0]
        aud = policy.audience(cfg, sl["search"])
        org = {"id": "a" * 24, "name": "Company", "primary_domain": "company.test", "country": "Germany"}
        self.assertIsNotNone(policy.company_reason(org, cfg, sl["search"]))
        self.assertIsNone(discovery.apollo_row(org, sl, aud, cfg)[0])

    def test_receipts_are_bound_to_project_policy_user_and_payload(self):
        cfg = config()
        token = universal._receipt("one", cfg, "companies", {"id": "a" * 24, "name": "Original"}, {}, "owner")
        self.assertEqual(universal._read_receipt(token, "one", cfg, "companies", "owner")["row"]["name"], "Original")
        for seg, c, user, t in (("two", cfg, "owner", token), ("one", cfg, "someone", token),
                                ("one", {**cfg, "changed": True}, "owner", token), ("one", cfg, "owner", token + "x")):
            with self.assertRaises(Exception):
                universal._read_receipt(t, seg, c, "companies", user)


class RoutingTests(unittest.TestCase):
    def test_all_18_services_from_apollo_records_without_retired_taxonomy(self):
        cfg = config()
        cases = [
            ("corporate_teams", "hospitality", "We employ a frontline workforce of technicians", {}, "AI Onboarding Employee"),
            ("corporate_teams", "consumer services", "Customer support teams and call centres", {}, "AI Simulations for Training"),
            ("consumer_brands", "wholesale", "Wholesale stock and trade accounts", {}, "AI Business Assistant"),
            ("financial_services", "insurance", "An insurance company with policyholders", {}, "Explainer Videos"),
            ("financial_services", "banking", "A community bank", {}, "AI Podcasts / Audio Content"),
            ("consumer_brands", "consumer goods", "We make household products", {}, "AI Video for Brands"),
            ("consumer_brands", "cosmetics", "Skin care serums", {"instagram": "https://instagram.com/zz"}, "AI UGC Product Videos"),
            ("consumer_brands", "consumer goods", "Join our creator program", {}, "Creator \u00d7 Brand Marketplace"),
            ("retailers", "retail", "Visit our furniture stores and showrooms", {}, "Shop Display Videos"),
            ("retailers", "apparel & fashion", "Clothing in our stores", {}, "AI Fashion Stylist"),
            ("real_estate", "real estate development", "Off-plan homes under construction", {}, "AI Real Estate Visualisation"),
            ("hospitality", "hospitality", "Vacation villas and holiday rentals", {}, "Airbnb / Property Content"),
            ("publishers", "book publishing", "We publish novels and books from our authors", {}, "Audiobooks and Audio Web Shows"),
            ("attractions", "museums & institutions", "Our museum offers a day out", {}, "AI Reality Experiences"),
            ("studios_agencies", "media production", "Watch our full episodes and web series", {"youtube": "https://youtube.com/@zz"}, "Reel Forge"),
            ("studios_agencies", "film production", "Independent film and television production company", {}, "AI VFX + Animation"),
            ("schools", "primary/secondary education", "Our school welcomes pupils", {}, "Virtual Tours for Schools"),
            ("local_business", "restaurants", "Independent coffee cafe", {}, "Local Business Tech and Automation"),
        ]
        routed = set()
        for kind, industry, text, socials, expected in cases:
            lead = {"name": "Zz Example", "domain": "zzexample.test", "source": "apollo", "metadata": {
                "kind": kind, "apollo": {"id": "a" * 24, "industry": industry, "short_description": text,
                "estimated_num_employees": 40, "country": "United States"}, "site_contact_routes": {"socials": socials}}}
            with self.subTest(service=expected):
                tag = lcx_judge.lead_service(lead, cfg)
                self.assertEqual(tag["service"], expected, tag)
                routed.add(tag["service"])
                # The exact automatic-discovery storage shape must route identically.
                meta = lead["metadata"]
                automatic = copy.deepcopy(lead)
                automatic["metadata"] = {"discovery_raw": {"lcx_apollo": {"kind": kind, "apollo": meta["apollo"]}},
                                          "site_contact_routes": meta["site_contact_routes"]}
                self.assertEqual(lcx_judge.lead_service(automatic, cfg)["service"], expected)
        self.assertEqual(routed, set(cfg["outreach"]["generated_pitch"]["all_services"]))

    def test_competitors_and_human_choices_are_not_rerouted(self):
        cfg = config()
        for text in ("We sell visual effects and post-production", "We are an animation studio making animated films"):
            lead = {"name": "Zz Studio", "source": "apollo", "metadata": {"kind": "studios_agencies",
                    "apollo": {"short_description": text}}}
            self.assertIsNone(lcx_judge.lead_service(lead, cfg)["service"])
        choice = {"service": "Explainer Videos", "set_by": "owner@example.test"}
        lead["metadata"]["lead_service"] = choice
        self.assertEqual(lcx_judge.lead_service(lead, cfg), choice)


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from run_sql import load_db_url
        cls.conn = psycopg2.connect(load_db_url(), connect_timeout=20)
        cls.cur = cls.conn.cursor()
        cls.cur.execute((ROOT / "sql/38_apollo_verified_contacts.sql").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def setUp(self):
        self.cur.execute("savepoint case_start")

    def tearDown(self):
        self.cur.execute("rollback to savepoint case_start")

    def project(self, cfg):
        slug = "zz-policy-" + uuid.uuid4().hex[:12]
        self.cur.execute("insert into segments(slug,name,entity_type,config) values(%s,'Test','company',%s) returning id", (slug, json.dumps(cfg)))
        return self.cur.fetchone()[0], slug

    def test_db_and_store_reject_unverified_but_clipping_is_unchanged(self):
        import psycopg2
        for slug in ("us-production-houses", "startup-acquisitions", "lcx-services", "universal", "lcx-clipping"):
            sid, _ = self.project(config(slug))
            self.cur.execute("insert into entities(segment_id,name,source) values(%s,'Company','apollo') returning id", (sid,))
            eid = self.cur.fetchone()[0]
            if slug != "lcx-clipping":
                for status in ("unverified", "catch_all", "unknown"):
                    self.cur.execute("savepoint refused")
                    with self.assertRaises(psycopg2.errors.CheckViolation):
                        self.cur.execute("insert into contacts(entity_id,email,email_status,source,verifier) values(%s,'a@firm.test',%s,'apollo','apollo')", (eid, status))
                    self.cur.execute("rollback to savepoint refused")
                with self.assertRaises(ValueError):
                    apollo_store.upsert_person(self.cur, eid, {"apollo_id": "b" * 24, "email": "a@firm.test", "email_status": "valid"})
            else:
                self.cur.execute("insert into contacts(entity_id,email,email_status,source) values(%s,'a@firm.test','unverified','site_scrape')", (eid,))
                self.cur.execute("select contact_allowed(%s,'site_scrape',null,'unverified')", (eid,))
                self.assertTrue(self.cur.fetchone()[0])

    def test_history_is_retained_but_cannot_be_drafted_approved_or_claimed(self):
        import psycopg2
        sid, _ = self.project({})
        self.cur.execute("insert into entities(segment_id,name,source,status) values(%s,'Legacy','apollo','shortlisted') returning id", (sid,))
        eid = self.cur.fetchone()[0]
        self.cur.execute("insert into contacts(entity_id,email,email_status,source,verifier) values(%s,'a@firm.test','unverified','apollo','apollo') returning id", (eid,))
        cid = self.cur.fetchone()[0]
        self.cur.execute("insert into outreach(entity_id,contact_id,direction,status,subject,body) values(%s,%s,'outbound','approved','Hello','Hello') returning id", (eid, cid))
        oid = self.cur.fetchone()[0]
        self.cur.execute("update segments set config=%s where id=%s", (json.dumps(config("universal")), sid))
        self.cur.execute("select contact_allowed(entity_id,source,verifier,email_status) from contacts where id=%s", (cid,))
        self.assertFalse(self.cur.fetchone()[0])
        for status in ("drafted", "approved", "sending"):
            self.cur.execute("savepoint refused")
            with self.assertRaises(psycopg2.errors.CheckViolation):
                self.cur.execute("update outreach set status=%s where id=%s", (status, oid))
            self.cur.execute("rollback to savepoint refused")
        self.cur.execute("select count(*) from contacts where id=%s", (cid,))
        self.assertEqual(self.cur.fetchone()[0], 1)
        pid = "f" * 24
        self.cur.execute("update entities set metadata=jsonb_build_object('apollo_people',jsonb_build_object(%s::text,%s::jsonb)) where id=%s",
                         (pid, json.dumps({"name": "Legacy", "apollo_email_status": "unverified"}), eid))
        self.assertEqual(apollo_store.saved_person_ids(self.cur, sid, [pid], verified_only=True), set())
        apollo_store.upsert_person(self.cur, eid, {"apollo_id": pid, "name": "Legacy", "email": "a@firm.test",
            "email_status": "valid", "apollo_email_status": "verified"})
        self.assertEqual(apollo_store.saved_person_ids(self.cur, sid, [pid], verified_only=True), {pid})

    def test_changed_service_blocks_an_old_draft(self):
        import psycopg2
        sid, _ = self.project(config())
        self.cur.execute("insert into entities(segment_id,name,source,status,metadata) values(%s,'Company','apollo','shortlisted',%s) returning id",
                         (sid, json.dumps({"lead_service": {"service": "Reel Forge", "set_by": "rules"}})))
        eid = self.cur.fetchone()[0]
        self.cur.execute("insert into contacts(entity_id,email,email_status,source,verifier) values(%s,'founder@firm.test','valid','apollo','apollo') returning id", (eid,))
        cid = self.cur.fetchone()[0]
        self.cur.execute("insert into outreach(entity_id,contact_id,direction,status,subject,body,service) values(%s,%s,'outbound','drafted','Hello','Hello','Reel Forge') returning id", (eid, cid))
        oid = self.cur.fetchone()[0]
        self.cur.execute("update entities set metadata=jsonb_set(metadata,'{lead_service,service}','\"AI VFX + Animation\"') where id=%s", (eid,))
        self.cur.execute("savepoint refused")
        with self.assertRaises(psycopg2.errors.CheckViolation):
            self.cur.execute("update outreach set status='approved' where id=%s", (oid,))
        self.cur.execute("rollback to savepoint refused")

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from psycopg2.extras import RealDictCursor
        @contextmanager
        def cursor():
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
        app = FastAPI()
        @app.middleware("http")
        async def identity(request, call_next):
            request.state.user = "tester@example.test"
            return await call_next(request)
        app.include_router(universal.build_router(cursor))
        return TestClient(app)

    def test_manual_company_save_uses_signed_facts_and_qualification_queue(self):
        cfg = config()
        sid, slug = self.project(cfg)
        search = next(s for s in policy.searches(cfg) if s.get("audience") == "consumer_brands" and not s.get("signal"))
        org = {"id": "a" * 24, "name": "Original", "primary_domain": "original.test", "country": "United States", "estimated_num_employees": 40}
        client = self.client()
        universal._STATUS.update(at=0, value=None)
        with patch.object(apollo, "status", return_value={"connected": True, "credits": {"lead_credits_left": 5000}}), \
             patch.object(apollo, "search_companies", return_value={"companies": [org], "total": 1, "page": 1, "total_pages": 1}) as search_api:
            result = client.post("/api/universal/search?project=" + slug, json={"kind": "companies", "filters": {policy.TARGET: search["key"]}})
            self.assertEqual(result.status_code, 200, result.text)
            row = result.json()["companies"][0]
            row["name"] = "Tampered"
            body = {"kind": "companies", "companies": [row], "receipts": [row["_receipt"]]}
            saved = client.post("/api/universal/save?project=" + slug, json=body)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.cur.execute("select name,status,metadata->>'kind' from entities where segment_id=%s", (sid,))
            self.assertEqual(self.cur.fetchall(), [("Original", "discovered", "consumer_brands")])
            body["receipts"] = []
            self.assertEqual(client.post("/api/universal/save?project=" + slug, json=body).status_code, 409)
            effective = search_api.call_args.args[0]
            self.assertEqual(effective["organization_num_employees_ranges"], search["filters"]["organization_num_employees_ranges"])

    def test_manual_reveal_rechecks_status_and_employer(self):
        cfg = config("universal")
        _, slug = self.project(cfg)
        client = self.client()
        pid = "b" * 24
        candidate = {"id": pid, "first_name": "Test", "title": "Founder", "company": "Original", "has_email": True}
        bad = apollo.person_record({"id": pid, "email": "test@original.test", "email_status": "unverified", "organization": {"id": "a" * 24, "name": "Original"}})
        with patch.object(apollo, "status", return_value={"connected": True, "credits": {"lead_credits_left": 5000}}), \
             patch.object(apollo, "search_people", return_value={"people": [candidate], "total": 1, "page": 1}), \
             patch.object(apollo, "reveal_people", return_value={"people": [bad], "credits": 1, "missing": []}) as reveal:
            result = client.post("/api/universal/search?project=" + slug, json={"kind": "people", "filters": {"q_person_name": "Test"}})
            self.assertEqual(result.status_code, 200, result.text)
            body = {"kind": "people", "ids": [pid], "receipts": [result.json()["people"][0]["_receipt"]]}
            saved = client.post("/api/universal/save?project=" + slug, json=body)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["saved"], 0)
            self.assertIn("verify", saved.json()["skipped"][0]["why"])
            reveal.assert_called_once()

    def test_manual_reveal_requires_qualified_company_and_checks_current_employer(self):
        cfg = config()
        sid, slug = self.project(cfg)
        selected = next(s for s in policy.searches(cfg) if s.get("audience") == "consumer_brands" and not s.get("signal"))
        pid = "c" * 24
        org = {"id": "d" * 24, "name": "Original", "primary_domain": "original.test", "country": "United States", "estimated_num_employees": 40}
        candidate = {"id": pid, "company": "Original", "company_id": org["id"], "title": "Founder", "has_email": True}
        person = apollo.person_record({"id": pid, "name": "Test Founder", "title": "Founder", "email": "founder@original.test", "email_status": "verified", "organization": org})
        client = self.client()
        with patch.object(apollo, "status", return_value={"connected": True, "credits": {"lead_credits_left": 5000}}), \
             patch.object(apollo, "search_people", return_value={"people": [candidate], "total": 1, "page": 1}), \
             patch.object(apollo, "reveal_people", return_value={"people": [person], "credits": 1, "missing": []}) as reveal:
            response = client.post("/api/universal/search?project=" + slug, json={"kind": "people", "filters": {policy.TARGET: selected["key"]}})
            self.assertEqual(response.status_code, 200, response.text)
            body = {"kind": "people", "ids": [pid], "receipts": [response.json()["people"][0]["_receipt"]]}
            saved = client.post("/api/universal/save?project=" + slug, json=body)
            self.assertEqual(saved.status_code, 409, saved.text)
            reveal.assert_not_called()
            self.cur.execute("insert into entities(segment_id,name,domain,source,status,fit_score,metadata) values(%s,'Original','original.test','apollo','ready_for_review',59,%s) returning id",
                             (sid, json.dumps({"kind": "consumer_brands", "hq_country": "US", "site_contact_routes": {"pages_read": 2}, "lcx_judgement": {"site_read": True}})))
            eid = self.cur.fetchone()[0]
            self.assertEqual(client.post("/api/universal/save?project=" + slug, json=body).status_code, 409)
            reveal.assert_not_called()
            self.cur.execute("update entities set fit_score=80 where id=%s", (eid,))
            moved = copy.deepcopy(person)
            moved["organization"] = {"id": "e" * 24, "name": "Moved", "primary_domain": "moved.test"}
            moved["email"] = "founder@moved.test"
            reveal.return_value = {"people": [moved], "credits": 1, "missing": []}
            result = client.post("/api/universal/save?project=" + slug, json=body)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["saved"], 0)
            self.assertIn("employer", result.json()["skipped"][0]["why"])
            # The same cooldown as automatic enrichment applies after a paid attempt.
            self.assertEqual(client.post("/api/universal/save?project=" + slug, json=body).status_code, 409)
            self.cur.execute("update entities set metadata=metadata-'apollo_checked_at' where id=%s", (eid,))
            reveal.return_value = {"people": [person], "credits": 1, "missing": []}
            result = client.post("/api/universal/save?project=" + slug, json=body)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["saved"], 1, result.text)
            self.cur.execute("select email_status,verifier from contacts where entity_id=%s", (eid,))
            self.assertEqual(self.cur.fetchall(), [("valid", "apollo")])

    def test_saved_searches_and_request_caps_cannot_bypass_policy(self):
        cfg = config()
        _, slug = self.project(cfg)
        client = self.client()
        result = client.post("/api/universal/searches?project=" + slug, json={"name": "Bad search", "kind": "companies", "filters": {"organization_locations": ["Germany"]}})
        self.assertEqual(result.status_code, 400, result.text)
        _, slug = self.project(config("universal"))
        with patch.object(apollo, "reveal_people") as reveal:
            result = client.post("/api/universal/save?project=" + slug, json={"kind": "people", "ids": ["%024x" % i for i in range(51)]})
            self.assertEqual(result.status_code, 400, result.text)
            reveal.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
