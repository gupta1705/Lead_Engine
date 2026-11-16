"""Follow-up approval/reporting under LCX-only opener routing; all fixtures roll back."""
import json
import os
import sys
import uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT/'tools'),str(ROOT/'app')]
os.environ['SCHEDULER_ENABLED']='0'
os.environ['SESSION_SECRET']='fixture-followup-routing'
import psycopg2
import bcrypt
from fastapi.testclient import TestClient
import main, auth, api_v1
from run_sql import load_db_url
from test_api import TxConn, NoPool

def run():
    conn=psycopg2.connect(load_db_url())
    main._checkout=TxConn(conn).begin; main._POOL=NoPool()
    main._scheduler.kick_outreach=lambda *a,**k:None
    main._scheduler.wake_sender=lambda *a,**k:None
    client=TestClient(main.app,follow_redirects=False)
    try:
        c=conn.cursor()
        # Old orphaned audit entries from previous deployments are not current
        # jobs; database activity is checked before running these fixtures.
        c.execute("select count(*) from pipeline_runs where status='running' and started_at>now()-interval '6 hours'")
        assert c.fetchone()[0]==0, 'Run database tests after the active pipeline finishes'
        tag=uuid.uuid4().hex[:8]; slug='zz-followup-'+tag
        parent='parent-'+tag+'@tvf.example'; reviewer='review-'+tag+'@tvf.example'; alias='parent-'+tag+'@lcx.example'
        cfg={'outreach':{'send_from':'approver','send_as_domain':'lcx.example','sign_as':'approver',
              'sender':{'name':'Fixture Sender','title':'Partnerships'},'footer':{'text':'{{sender_name}}\n{{sender_title}}'},
              'batch_approval':{'enabled':True,'sample_min':1,'sample_fraction':0.1}}}
        c.execute("insert into segments(slug,name,entity_type,config) values(%s,'Fixture','company',%s::jsonb) returning id",(slug,json.dumps(cfg)))
        sid=c.fetchone()[0]
        pw=bcrypt.hashpw(b'fixture-password',bcrypt.gensalt(4)).decode()
        for who in (parent,reviewer):
            c.execute("insert into app_users(email,password_hash,name,title) values(%s,%s,'Fixture Sender','Partnerships')",(who,pw))
        c.execute("insert into user_mailboxes(user_email,address,token_enc,daily_cap,send_as) values(%s,%s,'fixture',80,%s::jsonb)",
                  (parent,parent,json.dumps([{'address':alias,'name':'Fixture Sender'}])))
        cookies={auth.COOKIE:auth.make_cookie(reviewer,pw),'tvf_segment':slug}
        def call(method,path,**kw):
            client.cookies.clear(); return client.request(method,path,cookies=cookies,**kw)
        ids=[]
        for sent_as in (None,alias):
            c.execute("insert into entities(segment_id,name,source,status) values(%s,%s,'test','contacted') returning id",(sid,'Fixture '+uuid.uuid4().hex))
            eid=c.fetchone()[0]
            c.execute("insert into contacts(entity_id,full_name,email,email_status) values(%s,'Kay',%s,'valid') returning id",(eid,uuid.uuid4().hex+'@recipient.example'))
            cid=c.fetchone()[0]
            c.execute("insert into outreach(entity_id,contact_id,subject,body,status,approved_by,sender_address,sender_mailbox,sent_as,gmail_thread_id,gmail_message_id,sent_at)"
                      " values(%s,%s,'Fixture','Hello','sent',%s,%s,%s,%s,'fixture-thread',%s,now()-interval '5 days') returning id",(eid,cid,parent,parent,parent,sent_as,uuid.uuid4().hex))
            pid=c.fetchone()[0]
            c.execute("insert into outreach(entity_id,contact_id,subject,body,status,parent_id,sequence_step) values(%s,%s,'Re: Fixture','Hello Kay\n\nFixture Sender\nPartnerships','drafted',%s,1) returning id",(eid,cid,pid))
            fid=str(c.fetchone()[0]); ids.append(fid)
            expected=sent_as or parent
            preview=call('GET','/api/outreach/'+fid).json()
            assert preview['planned_sender']==expected and preview['sending_account']==parent, preview
            formatted=api_v1.Ops._email(preview,full=True)
            assert formatted['sender']==expected and formatted['sender_rule']=='original_thread'
            result=call('POST','/api/outreach/'+fid+'/decision',json={'action':'approve'})
            assert result.status_code==200,result.text
            assert result.json()['sends_from']==[expected],result.text
            assert result.json()['can_send'] is True, 'Original owner can send even if reviewer has no mailbox'
        assert set(main._sends_from(slug,reviewer,ids))=={parent,alias}
        assert main._sends_from(slug,parent)==[alias], 'New emails still use the LCX domain policy'
        c.execute("update user_mailboxes set last_error='fixture disconnected' where address=%s",(parent,))
        assert not main._can_send(slug,reviewer,ids[0])
        assert main._sends_from(slug,reviewer,ids[0])==[parent], 'Disconnection must not select another sender'
        print('Follow-up sender reporting passed: TVF originals, alias originals, cross-person approval, batch reporting, API details and disconnected parent. No emails sent.')
    finally:
        conn.rollback(); conn.close()

if __name__=='__main__':run()
