"""Retention boundary, protected history and freshness ranking; all writes roll back."""
import json
import tempfile
import unittest
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'app'))

import psycopg2
from lead_lifecycle import expire, priority_order, retention_days
from run_sql import load_db_url


class Lifecycle(unittest.TestCase):
    def test_scheduler_expires_before_drafting_and_keeps_send_step(self):
        from scheduler import Scheduler
        from types import SimpleNamespace
        jobs = []
        ops = SimpleNamespace(run_blocking=lambda key, **kw: (jobs.append(key) or 0, None),
                              run_send=lambda *a, **kw: (jobs.append('send_outreach') or 0, None))
        scheduler = Scheduler(None, ops)
        scheduler.outreach_work = lambda segment: dict(expire=True,pull=False,followups=False,draft=True,send=True)
        scheduler._open = lambda *a: None
        scheduler._close = lambda *a: None
        scheduler._send_summary = lambda *a: None
        scheduler._after_send = lambda *a: None
        self.assertEqual(scheduler.outreach_tick('lcx-clipping'), 'ok')
        self.assertEqual(jobs,['expire_leads','draft_outreach','send_outreach'])

    def test_config_is_opt_in(self):
        for value in ({}, {"enabled": False, "days": 14}, {"enabled": True, "days": "14"},
                      {"enabled": True, "days": True}, {"enabled": True, "days": 0}):
            self.assertIsNone(retention_days({"lead_retention": value}))
        self.assertEqual(retention_days({"lead_retention": {"enabled": True, "days": 14}}), 14)

    def test_database_retention_and_ranking(self):
        conn = psycopg2.connect(load_db_url())
        try:
            c = conn.cursor()
            slug = "zz-retention-" + uuid.uuid4().hex[:8]
            c.execute("insert into segments(slug,name,entity_type,config) values(%s,'Test','company',%s) returning id",
                      (slug, json.dumps({"lead_retention": {"enabled": True, "days": 14}})))
            sid = c.fetchone()[0]
            def lead(name, days=20, status="shortlisted", score=50):
                c.execute("insert into entities(segment_id,name,source,status,fit_score,created_at) "
                          "values(%s,%s,'test',%s,%s,now()-%s*interval '1 day') returning id",
                          (sid, name, status, score, days))
                return str(c.fetchone()[0])
            def mail(eid, status="drafted", direction="outbound", approved=False):
                c.execute("insert into outreach(entity_id,status,direction,approved_at,subject,body) "
                          "values(%s,%s,%s,case when %s then now() end,'Test','Test') returning id",
                          (eid, status, direction, approved))
                return str(c.fetchone()[0])
            expired = lead("Expired",14); draft = mail(expired)
            fresh = lead("Fresh",13); fresh_mail = mail(fresh)
            protected = []
            for status in ("approved", "sending", "send_unknown", "sent"):
                eid = lead(status); mail(eid, status); protected.append(eid)
            eid = lead("Reply"); mail(eid, "received", "inbound"); protected.append(eid)
            eid = lead("Prior approval"); mail(eid,"drafted",approved=True); protected.append(eid)
            for status in ("contacted", "in_conversation"):
                protected.append(lead(status,status=status))
            rejected = lead("Rejected",status="rejected")
            c.execute("insert into segments(slug,name,entity_type) values(%s,'Other','company') returning id",(slug+'-other',))
            other_sid = c.fetchone()[0]
            c.execute("insert into entities(segment_id,name,source,status,created_at) "
                      "values(%s,'Other','test','shortlisted',now()-interval '20 days') returning id",(other_sid,))
            other = str(c.fetchone()[0])
            with tempfile.TemporaryDirectory() as folder:
                self.assertEqual(expire(c,slug,backup_dir=folder), {'archived':1,'cancelled_drafts':1,'days':14})
                from pathlib import Path
                backup = json.loads(next(Path(folder).glob('before-*.json')).read_text(encoding='utf-8'))
                self.assertEqual(len(backup['entities']),1)
                self.assertEqual(backup['outreach'][0]['status'],'drafted')
            c.execute("select status from outreach where id=%s",(draft,)); self.assertEqual(c.fetchone()[0],'cancelled')
            for eid in protected+[fresh,other]:
                c.execute("select status from entities where id=%s",(eid,)); self.assertNotEqual(c.fetchone()[0],'archived')
            c.execute("select status from entities where id=%s",(rejected,)); self.assertEqual(c.fetchone()[0],'rejected')
            c.execute("select status from outreach where id=%s",(fresh_mail,)); self.assertEqual(c.fetchone()[0],'drafted')
            self.assertEqual(expire(c,slug)['archived'],0)  # reruns are inert
            self.assertTrue(expire(c,slug+'-other')['disabled'])
            with self.assertRaises(ValueError): expire(c,slug,reset=True)
            strong = lead('Strong fresh',0,score=80)
            old = lead('Strong old',13,score=80)
            weak = lead('Weak fresh',0,score=20)
            c.execute("select e.id from entities e where e.id=any(%s::uuid[]) order by "+priority_order(),([strong,old,weak],))
            self.assertEqual([str(r[0]) for r in c.fetchall()],[strong,old,weak])
            # A refresh updates updated_at, never original discovery age.
            c.execute("update entities set metadata=metadata||'{\"refreshed\":true}'::jsonb where id=%s",(expired,))
            c.execute("select created_at <= now()-interval '14 days' from entities where id=%s",(expired,))
            self.assertTrue(c.fetchone()[0])
            with tempfile.TemporaryDirectory() as folder:
                result = expire(c,slug,reset=True,backup_dir=folder)
            self.assertEqual(result['archived'],4)
            self.assertEqual(result['cancelled_drafts'],1)
            for eid in protected:
                c.execute("select status from entities where id=%s",(eid,))
                self.assertNotEqual(c.fetchone()[0],'archived')
        finally:
            conn.rollback(); conn.close()


if __name__ == '__main__': unittest.main()
