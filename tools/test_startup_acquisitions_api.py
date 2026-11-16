"""One rollback transaction: acquisition evidence API, decisions/history and credit pause."""
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'app')]
os.environ['SCHEDULER_ENABLED']='0'
os.environ['SESSION_SECRET']='fixture-startup-evidence'
import bcrypt
import psycopg2
from fastapi.testclient import TestClient
import main,auth,apollo,universal
import startup_acquisitions as sa
from run_sql import load_db_url
from test_api import TxConn,NoPool

def run():
    conn=psycopg2.connect(load_db_url())
    main._checkout=TxConn(conn).begin;main._POOL=NoPool()
    main._scheduler.kick_outreach=lambda *a,**k:None
    main._scheduler.wake_sender=lambda *a,**k:None
    client=TestClient(main.app,follow_redirects=False)
    try:
        cur=conn.cursor()
        cur.execute("select count(*) from pipeline_runs where status='running' and started_at>now()-interval '6 hours'")
        assert cur.fetchone()[0]==0,'Wait for active pipeline before database fixtures'
        cur.execute("select id,config from segments where slug='startup-acquisitions'")
        sid,original=cur.fetchone();cfg=sa.configure(original)
        cur.execute("update segments set config=%s::jsonb where id=%s",(json.dumps(cfg),sid))
        tag=uuid.uuid4().hex[:10];user='fixture-'+tag+'@example.test'
        pw=bcrypt.hashpw(b'fixture-password',bcrypt.gensalt(4)).decode()
        cur.execute("insert into app_users(email,password_hash,name,title) values(%s,%s,'Fixture','Research')",(user,pw))
        cookies={auth.COOKIE:auth.make_cookie(user,pw),'tvf_segment':'startup-acquisitions'}
        def call(path,body):
            client.cookies.clear()
            return client.post(path,json=body,cookies=cookies)
        meta={'apollo':{'country':'India','city':'Mumbai','industry':'Software','raw_address':'Andheri West Mumbai 400053'},'hq_country':'IN'}
        cur.execute("insert into entities(segment_id,name,domain,source,status,metadata) values(%s,%s,%s,'apollo','shortlisted',%s::jsonb) returning id",(sid,'Fixture '+tag,tag+'.example.test',json.dumps(meta)))
        eid=str(cur.fetchone()[0])
        cur.execute("insert into contacts(entity_id,full_name,email,email_status,source,verifier) values(%s,'Fixture Founder',%s,'valid','apollo','apollo') returning id",(eid,'founder@'+tag+'.example.test'))
        cid=cur.fetchone()[0]
        cur.execute("insert into outreach(entity_id,contact_id,subject,body,status) values(%s,%s,'Fixture subject','Preserve this text','drafted') returning id",(eid,cid))
        oid=cur.fetchone()[0]
        import datetime as dt
        evidence={'asking_price_inr':5_000_000,'price_source':'Founder call reference','asset_summary':'Working product and small engineering team',
                  'asset_source':'Founder product demo','distress_summary':'Founder confirms unpaid salaries and runway issue',
                  'distress_source':'Founder call notes','checked_at':dt.date.today().isoformat(),'deal_type':'full_company_acquisition'}
        endpoint='/api/leads/'+eid+'/acquisition-evidence'
        result=call(endpoint,evidence)
        assert result.status_code==200,result.text
        assert result.json()['assessment']['contact_eligible'] is True,result.text
        cur.execute("select status,fit_score,score_breakdown->>'points_possible_assessed',metadata->'startup_review'->>'updated_by' from entities where id=%s",(eid,))
        status,score,possible,by=cur.fetchone()
        assert status=='shortlisted' and score==95 and float(possible)==100 and by==user,(status,score,possible,by)
        cur.execute("select status,subject,body from outreach where id=%s",(oid,))
        assert cur.fetchone()==('drafted','Fixture subject','Preserve this text')
        assert call(endpoint,dict(evidence,asking_price_inr=10_000_000)).json()['assessment']['contact_eligible'] is False
        assert call(endpoint,dict(evidence,price_source='')).status_code==400
        assert call(endpoint,dict(evidence,scoring_inputs={'affordability':1})).status_code==400
        cur.execute("update entities set status='rejected' where id=%s",(eid,))
        assert call(endpoint,evidence).status_code==200
        cur.execute("select status from entities where id=%s",(eid,));assert cur.fetchone()[0]=='rejected'
        with patch.object(apollo,'search_companies',side_effect=AssertionError('No paid request')) as paid:
            response=call('/api/universal/search?project=startup-acquisitions',{'kind':'companies','filters':{'_project_search':cfg['apollo_discovery']['searches'][0]['key']}})
            assert response.status_code==409,response.text
            paid.assert_not_called()
        print('Startup API passed: strict price ceiling, evidence validation, 100-point score, preserved decisions/drafts, paused manual spending. Fixtures rolled back; no mail or Apollo credits.')
    finally:
        conn.rollback();conn.close()

if __name__=='__main__':run()
