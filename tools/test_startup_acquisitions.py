"""Acquisition research acceptance cases. No network, credits or mail."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT),str(ROOT/"tools")]
import startup_acquisitions as sa
import startup_signals as ss
import apollo_policy
from app import universal

NOW = dt.datetime(2026,11,16,12,tzinfo=dt.timezone.utc)
CFG = sa.configure(json.loads((ROOT/"config/segment.startup-acquisitions.json").read_text(encoding="utf-8")))

def metadata():
    return {"apollo":{"country":"India","city":"Mumbai","industry":"Software","raw_address":"Andheri West, Mumbai 400053"},
            "hq_country":"IN", "press_events":[{"track":"distress","strength":1,"title":"Example delays salaries",
            "published_at":"2026-11-15", "link":"https://publisher.test/example"}],
            "site_health":{"status":"up"},"startup_review":sa.valid_review({"asking_price_inr":5_000_000,
            "price_source":"Founder call, 15 November", "asset_summary":"Working video editor and engineering team",
            "asset_source":"Product demo and founder call", "checked_at":"2026-11-15", "deal_type":"full_company_acquisition"},"reviewer@test",NOW)}

class AcquisitionTests(unittest.TestCase):
    def result(self,m): return sa.assess(m,CFG,NOW)

    def test_owner_constraints_and_preserved_mail(self):
        original = json.loads((ROOT/"config/segment.startup-acquisitions.json").read_text(encoding="utf-8"))
        configured = sa.configure(original)
        self.assertEqual(configured["outreach"], original["outreach"])
        self.assertEqual(sum(c["points"] for c in configured["rubric"]),100)
        self.assertFalse(configured["enrichment"]["enabled"])
        self.assertEqual(configured["enrichment"]["credits_per_run"],0)
        self.assertEqual(configured["enrichment"]["credits_per_week"],0)
        self.assertEqual(sa.configure(configured),configured)
        for search in apollo_policy.searches(configured):
            filters,_ = apollo_policy.constrained_filters(configured,"companies",{"_project_search":search["key"]})
            self.assertEqual(filters["organization_locations"],search["filters"]["organization_locations"])

    def test_purchase_ceiling_is_strict_and_zero_is_valid(self):
        for price,allowed in [(0,True),(9_999_999,True),(10_000_000,False),(12_000_000,False)]:
            m=metadata(); m["startup_review"]["asking_price_inr"]=price
            si,out=self.result(m)
            self.assertEqual(si["affordability"],1 if allowed else 0)
            self.assertEqual(si["acquisition_price_blocked"],not allowed)
            self.assertEqual(out["contact_eligible"],allowed)

    def test_funding_and_revenue_never_imply_affordable_price(self):
        m=metadata();m["startup_review"].pop("asking_price_inr")
        m["apollo"].update(total_funding=10000,annual_revenue=1000,estimated_num_employees=2)
        si,out=self.result(m)
        self.assertEqual(si["affordability"],0)
        self.assertFalse(out["price_confirmed"])
        self.assertIn("unconfirmed",out["status"])
        self.assertTrue(out["contact_eligible"],"A price-discovery conversation is research, not a confirmed deal")

    def test_stale_quote_is_unknown_and_future_quote_is_rejected(self):
        m=metadata();m["startup_review"]["checked_at"]="2026-01-01"
        self.assertFalse(self.result(m)[1]["price_confirmed"])
        with self.assertRaises(ValueError):
            sa.valid_review({"asking_price_inr":100,"price_source":"Founder call","checked_at":"2026-11-17"},"owner",NOW)

    def test_homepage_and_funding_gap_do_not_establish_distress_or_salvage(self):
        m=metadata();m["press_events"]=[];m["startup_review"]={}
        si,out=self.result(m)
        self.assertEqual(si["distress_current"],0)
        self.assertEqual(si["salvage_value"],0)
        self.assertFalse(out["contact_eligible"])

    def test_zero_month_distress_is_not_lost_and_future_news_is_ignored(self):
        m=metadata();m["press_events"][0]["published_at"]=NOW.isoformat()
        self.assertEqual(self.result(m)[0]["distress_current"],1)
        si,_=ss.score_inputs("Example",m["press_events"],{},None,None,CFG,NOW)
        self.assertEqual(si["distress_evidence"],1)
        m["press_events"][0]["published_at"]="2026-12-01"
        self.assertEqual(self.result(m)[0]["distress_current"],0)

    def test_proximity_ranks_neighbourhoods_without_inventing_distance(self):
        rows=[("Mumbai","Andheri West, Mumbai 400053",1),("Mumbai","Juhu, Mumbai",.8),
              ("Mumbai",None,.6),("Thane","Thane",.4),("Pune","Pune",.1),
              ("Pune","Andheri West",.1)]
        for city,address,points in rows:
            m=metadata();m["apollo"].update(city=city,raw_address=address)
            si,out=self.result(m)
            self.assertEqual(si["office_proximity"],points,(city,address))
            self.assertIn("not a measured distance",out["proximity_summary"])
            self.assertTrue(out["contact_eligible"],"Other Indian cities remain eligible")

    def test_foreign_headquarters_and_existing_exclusions_cannot_qualify(self):
        m=metadata();m["apollo"]["country"]="United States"
        si,out=self.result(m)
        self.assertTrue(si["acquisition_country_blocked"])
        self.assertFalse(out["contact_eligible"])
        for key in ("acquired_signal","major_or_oversized_signal"):
            m=metadata();m["scoring_inputs"]={key:True}
            self.assertFalse(self.result(m)[1]["contact_eligible"])

    def test_manual_evidence_sources_required_and_scores_cannot_be_injected(self):
        for data in [{"asking_price_inr":1},{"asset_summary":"Code"},{"affordability":1},
                     {"asking_price_inr":"NaN","price_source":"x","checked_at":"2026-11-15"}]:
            with self.assertRaises(ValueError): sa.valid_review(data,"owner",NOW)
        with self.assertRaises(ValueError):
            sa.valid_review({"deal_type":"asset_purchase"},"owner",NOW)
        m=metadata();m["startup_review"]["deal_type"]="asset_purchase"
        self.assertFalse(self.result(m)[1]["price_confirmed"])

    def test_manual_and_automatic_reveal_rules_and_paused_budget(self):
        import enrich_apollo
        class Cur:
            def execute(self,sql,args): self.sql=sql
            def fetchall(self): return []
        class DB:
            def __init__(self): self.cur=Cur()
            def run(self,fn): return fn(self.cur)
        db=DB()
        with patch.object(enrich_apollo,"SEGMENT","startup-acquisitions"):
            enrich_apollo.candidates(db,False,10,30,False)
        self.assertIn(sa.CONTACT_SQL,db.cur.sql)
        universal._qualified(db.cur,"fixture",{"company":"Example"},CFG)
        self.assertIn(sa.CONTACT_SQL,db.cur.sql)
        with patch.object(universal,"_budget",wraps=universal._budget):
            def forbidden(*args): raise AssertionError("Must not call Apollo or DB while spending disabled")
            self.assertIn("disabled",universal._budget(forbidden,"fixture",CFG,forbidden,1))

    def test_score_cannot_normalise_missing_contact_to_a_higher_total(self):
        m=sa.refresh(metadata(),CFG,NOW)
        self.assertTrue(all(c["key"] in m["scoring_inputs"] for c in CFG["rubric"]))
        self.assertEqual(m["scoring_inputs"]["reachable_decision_maker"],0)
        self.assertEqual(m["scoring_inputs"]["no_struggle_signal"],0)

    def test_scheduled_discovery_pauses_before_any_apollo_call(self):
        import discover_apollo
        class Cur:
            def execute(self,*args): pass
            def fetchone(self): return ("fixture",CFG)
        class DB:
            def run(self,fn): return fn(Cur())
            def close(self): pass
        with patch.object(discover_apollo,"SEGMENT","startup-acquisitions"), \
             patch.object(discover_apollo,"Db",return_value=DB()), \
             patch.object(sys,"argv",["discover_apollo.py"]), \
             patch.object(discover_apollo.apollo,"key_is_set",side_effect=AssertionError("No Apollo call")), \
             patch.object(discover_apollo.apollo,"credits",side_effect=AssertionError("No Apollo call")):
            self.assertEqual(discover_apollo.main(),0)

if __name__=="__main__":unittest.main()
