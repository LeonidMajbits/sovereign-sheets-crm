#!/usr/bin/env python3
"""Lamport confluence, 100-way claims, abrupt process exits and negative controls.
All fixtures are newly created and synthetic. This is not a payment system test.
"""
from pathlib import Path
import sys,os,json,sqlite3,tempfile,random,threading,concurrent.futures,time,subprocess,shutil,argparse,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import crm.db as dbmod
from crm.db import Database
from crm.engine import Engine,ActorContext,ALL_CAPS
from crm.codec import jcs,loads
from crm.errors import CRMError
from qualification.run_matrix import uid,save,source_digest

def fresh(root,actors=100):
    db=Database.initialize(root,uid(100),uid(200),uid(300));e=Engine(db);a=ActorContext(uid(300),ALL_CAPS)
    with db.transaction() as c:
        for i in range(actors):c.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(uid(100),uid(1000+i),f'worker{i}','agent'))
    return e,a,[ActorContext(uid(1000+i),ALL_CAPS) for i in range(actors)]
def create(e,a,eid,kind,facet,name='fixture'):
    p=e.packet('entity.create',{'entity_id':eid,'entity_kind':kind,'display_name':name,'facet':facet},base=None if kind in ('person','project') else 'current')
    r=e.ingest(p,a);assert r['disposition']=='COMMITTED',r

def confluence(root):
    runs=[]
    for seed in (1,17,99,260924):
        e,a,actors=fresh(root/f'lww-{seed}');eid=uid(100000);create(e,a,eid,'person',{})
        base=e.base();packets=[e.packet('entity.lww.set',{'entity_id':eid,'field':'note','value':f'candidate-{i}','logical_clock':str(i%5+1)},operation_id=uid(200000+i),base=base) for i in range(100)]
        order=list(range(100));random.Random(seed).shuffle(order);barrier=threading.Barrier(100)
        def send(i):barrier.wait(120);return i,e.ingest(packets[i],actors[i])
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:out=list(pool.map(send,order))
        expect=max(range(100),key=lambda i:(int(packets[i]['payload']['logical_clock']),actors[i].actor_id,packets[i]['operation_id']))
        with e.db.read() as c:
            row=c.execute('SELECT note,entity_rev FROM entities WHERE entity_id=?',(eid,)).fetchone()
            assert row['note']==f'candidate-{expect}'
            assert c.execute("SELECT count(*) FROM audit_log WHERE event_kind='lamport.candidate'").fetchone()[0]==100
            # Every approved proposal survives in audit even if never current.
            candidates=[loads(r[0])['data']['value'] for r in c.execute("SELECT event_jcs FROM audit_log WHERE event_kind='lamport.candidate'")]
            assert set(candidates)=={f'candidate-{i}' for i in range(100)}
        for i,r in out:assert e.ingest(packets[i],actors[i])==r
        runs.append({'seed':seed,'workers':100,'candidates':100,'winner':expect,'canonical_revisions':row['entity_rev'],'retained_candidates':len(candidates),'same_id_retries':100,'observed_order':[i for i,r in sorted(out,key=lambda pair:int(pair[1]['commit_seq']))],'chain':e.verify_audit()})
        e.db.close()
    return runs

def claims(root,rounds=10):
    e,a,actors=fresh(root/'claims');data=[]
    for roundno in range(rounds):
        project,stage,ticket,dispatch=[uid(300000+roundno*10+i) for i in range(4)]
        create(e,a,project,'project',{'slug':f'project-{roundno}'})
        create(e,a,stage,'stage',{'project_id':project,'plan_version':'1','stage_ordinal':'1','required':True})
        create(e,a,ticket,'ticket',{'project_id':project,'plan_version':'1','parent_work_item_id':stage})
        create(e,a,dispatch,'dispatch',{'work_item_id':ticket,'actor_id':a.actor_id,'attempt_no':'1','prompt_hash':'a'*64,'target_app':'ChatGPT','connector_account_id':'synthetic'})
        base=e.base();packets=[e.packet('claim.acquire',{'resource_id':dispatch},base=base) for _ in actors]
        barrier=threading.Barrier(100);begin={}
        def send(i):
            barrier.wait(120);begin[i]=time.perf_counter_ns();return i,e.ingest(packets[i],actors[i])
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:out=list(pool.map(send,range(100)))
        wins=[(i,r) for i,r in out if r['disposition']=='COMMITTED'];assert len(wins)==1
        assert sum(r['disposition']=='CONFLICT' for i,r in out)==99
        winner,result=wins[0];token=result['data']['claim_token'];before=e.state()['commit_seq']
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
            replay=list(pool.map(lambda i:e.ingest(packets[i],actors[i]),range(100)))
        assert e.state()['commit_seq']==before
        assert all(replay[i]==dict(out)[i] for i in range(100))
        release=e.packet('claim.release',{'resource_id':dispatch,'claim_token':token,'reason':'synthetic claim round complete'})
        assert e.ingest(release,actors[winner])['disposition']=='COMMITTED'
        other=(winner+1)%100;new=e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),actors[other]);assert new['disposition']=='COMMITTED'
        stale=e.ingest(e.packet('claim.release',{'resource_id':dispatch,'claim_token':token,'reason':'stale attempted release'}),actors[winner]);assert stale['disposition']=='CONFLICT'
        with e.db.read() as c:
            row=c.execute('SELECT * FROM claims WHERE resource_id=?',(dispatch,)).fetchone();assert row['holder_actor_id']==actors[other].actor_id and row['claim_generation']==2
        data.append({'round':roundno,'attempts':100,'successful_current_claimants':1,'conflicts':99,'exact_retries':100,'retry_added_transactions':0,'stale_release_rejected':True,'submission_spread_ms':(max(begin.values())-min(begin.values()))/1e6})
    chain=e.verify_audit();e.db.close();return {'rounds':data,'chain':chain,'financial_endpoint_tested':False}

def crash_child(parent,phase,compat):
    # Parent supplies a newly allocated test directory, never an existing ledger.
    root=Path(parent)/'runtime';assert not root.exists()
    if compat:dbmod.MIN_SQLITE=min(dbmod.MIN_SQLITE,sqlite3.sqlite_version_info)
    e,a,_=fresh(root,0);eid=uid(100000);create(e,a,eid,'person',{})
    p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'durable once'}},operation_id=uid(400000))
    path=Path(parent)/'packet.json'
    with path.open('wb') as f:f.write(jcs(p));f.flush();os.fsync(f.fileno())
    if phase!='after_commit':
        def fault(point):
            if point==phase:os._exit(73)
        e.fault=fault
    e.ingest(p,a);os._exit(74)

def crashes(root,compat):
    data=[]
    for phase in ('after_domain','after_search','before_outbox','before_commit','after_commit'):
        parent=root/f'crash-{phase}';parent.mkdir(mode=0o700)
        result=subprocess.run([sys.executable,__file__,'--crash-child',str(parent),'--phase',phase]+(['--compatibility-only'] if compat else []),capture_output=True,timeout=60)
        assert result.returncode==(74 if phase=='after_commit' else 73),(phase,result.stderr.decode())
        p=loads((parent/'packet.json').read_bytes());db=Database(parent/'runtime');e=Engine(db);a=ActorContext(uid(300),ALL_CAPS)
        with db.read() as c:
            before=c.execute('SELECT entity_rev,note FROM entities').fetchone()
            assert before['entity_rev']==(2 if phase=='after_commit' else 1)
            assert bool(c.execute('SELECT 1 FROM operation_outcomes WHERE operation_id=?',(p['operation_id'],)).fetchone())==(phase=='after_commit')
        accepted=e.ingest(p,a);assert accepted['disposition']=='COMMITTED'
        with db.read() as c:
            assert tuple(c.execute('SELECT entity_rev,note FROM entities').fetchone())==(2,'durable once')
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        data.append({'phase':phase,'exit_code':result.returncode,'recovered_revision_before_retry':before['entity_rev'],'final_revision':2,'audit':e.verify_audit()});db.close()
    return data

def run(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True);oldfloor=dbmod.MIN_SQLITE
    if args.compatibility_only:dbmod.MIN_SQLITE=min(oldfloor,sqlite3.sqlite_version_info)
    else:dbmod.runtime_check()
    root=Path(tempfile.mkdtemp(prefix='crm-adversarial-'))
    try:
        result={'status':'PASS','compatibility_only':args.compatibility_only,'source':source_digest(),'lamport':confluence(root),'claims':claims(root),'process_crashes':crashes(root,args.compatibility_only),
        'negative_controls':{'unrestricted_lww_budget':{'initial_balance':100,'two_independent_debits':[80,80],'lww_remaining_balance':20,'total_debits':160,'overspend':60,'safe':False,'scope':'Algebraic counterexample, not money movement'},'unrestricted_zero_overwrite':{'two_values':['A','B'],'one_current_value_possible':True,'preservation_required':'Both proposals in immutable history, not both current in one cell'}}}
        save(output/'adversarial_results.json',result);print(json.dumps({'status':'PASS','lamport_runs':len(result['lamport']),'claim_rounds':len(result['claims']['rounds']),'process_crashes':len(result['process_crashes'])},indent=2))
    finally:dbmod.MIN_SQLITE=oldfloor;shutil.rmtree(root)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output');p.add_argument('--compatibility-only',action='store_true');p.add_argument('--crash-child');p.add_argument('--phase');a=p.parse_args()
    if a.crash_child:crash_child(a.crash_child,a.phase,a.compatibility_only)
    elif not a.output:p.error('--output is required')
    else:
        try:run(a)
        except BaseException as ex:
            save(Path(a.output)/'adversarial_failure.json',{'status':'FAIL','message':str(ex),'traceback':traceback.format_exc()});raise
