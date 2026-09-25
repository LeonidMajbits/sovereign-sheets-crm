#!/usr/bin/env python3
"""100 workers overlap accepting transactions with one active publisher.
Fresh synthetic single-tenant workload. No live cloud and no bulk SQL seeding.
"""
from pathlib import Path
import sys,argparse,tempfile,sqlite3,time,threading,concurrent.futures,random,shutil,traceback,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import crm.db as dbmod
from crm.db import Database
from crm.engine import Engine,ActorContext,ALL_CAPS
from crm.quota import Scheduler,QuotaHold
from crm.sync import Publisher
from crm.google_api import NotApplied,Ambiguous
from crm.codec import loads
from qualification.provider import VirtualClock,FaultDomain,TypedSheets
from qualification.run_matrix import uid,save,stats,source_digest

def run(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True);floor=dbmod.MIN_SQLITE
    if args.compatibility_only:dbmod.MIN_SQLITE=min(floor,sqlite3.sqlite_version_info)
    else:dbmod.runtime_check()
    root=Path(tempfile.mkdtemp(prefix='crm-stream-q6-'));db=q=None
    try:
        db=Database.initialize(root/'runtime',uid(900),uid(901),uid(902));e=Engine(db);owner=ActorContext(uid(902),ALL_CAPS)
        with db.transaction() as c:
            for w in range(100):c.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(uid(900),uid(1000+w),f'stream-{w}','agent'))
        clock=VirtualClock();q=Scheduler(root/'quota','project','principal',clock=clock,jitter=random.Random(260924).random)
        domain=FaultDomain();config={'spreadsheet_id':'SIMULATED-stream','generation_id':uid(999),'sheet_ids':{'Directory':101,'Active Pipeline':102,'Completed Archives':103,'_Control':104,'_Changes':105}}
        provider=TypedSheets(config,q,domain);pub=Publisher(e,provider,q,config);pub.activate();domain.reject_remaining=2
        gate=threading.Barrier(100);done=threading.Event();guard=threading.Lock();completed=0;latencies=[];applied_while_active=[];failures=[];expected={};peak=0;active=0
        def producer(w):
            nonlocal completed,peak,active
            actor=ActorContext(uid(1000+w),ALL_CAPS);counter=0;gate.wait(120)
            for i in range(20):
                j=i%4;eid=uid(70000+w*4+j);kind='campaign' if j==0 else 'person'
                if i<4:
                    p=e.packet('entity.create',{'entity_id':eid,'entity_kind':kind,'display_name':f'Stream {w} item {j}','facet':{'slug':f'campaign-{w}'} if kind=='campaign' else {}},base=None)
                else:
                    counter+=1;value=f'Stream {w} item {j} pass {i//4}'
                    p=e.packet('entity.lww.set',{'entity_id':eid,'field':'note','value':value,'logical_clock':str(counter)})
                with guard:active+=1;peak=max(peak,active)
                start=time.perf_counter_ns()
                try:r=e.ingest(p,actor)
                finally:
                    with guard:active-=1
                assert r['disposition']=='COMMITTED'
                if i>=4:counter=max(counter,int(r['data']['receive_clock']))
                with guard:
                    completed+=1;latencies.append(time.perf_counter_ns()-start)
                    if i>=4:expected[eid]=value
        def drain():
            try:
                last=0;steps=0
                while not done.is_set() or int(pub.plan()['pending_transactions']):
                    steps+=1;assert steps<100000
                    try:pub.run(owner,mode='push')
                    except QuotaHold as hold:clock.advance(max(.001,hold.until-clock()+.001))
                    except (NotApplied,Ambiguous):pass
                    if domain.applied!=last:
                        with guard:at=completed
                        if at<2000:applied_while_active.append({'batch_number':domain.applied,'admitted_at_observation':at})
                        last=domain.applied
                    if not done.is_set():time.sleep(.001)
            except BaseException:failures.append(traceback.format_exc())
        start=time.perf_counter();thread=threading.Thread(target=drain);thread.start()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:list(pool.map(producer,range(100)))
        finally:done.set()
        thread.join(timeout=900);assert not thread.is_alive(),'drain did not finish';assert not failures,failures
        assert completed==2000 and applied_while_active
        chain=e.verify_audit();frames={};events={}
        for (sid,row),line in provider.rows.items():
            if sid!=105 or row<=1 or not line:continue
            if line[0]=='TRANSACTION':frames[int(line[4])]=line[8]
            if line[0]=='EVENT':events[(int(line[4]),int(line[5]))]=line[8]
        with db.read() as c:
            assert c.execute('SELECT count(*) FROM entities').fetchone()[0]==400
            for r in c.execute('SELECT * FROM entities'):
                assert r['entity_rev']==5 and r['note']==expected[r['entity_id']]
                m=c.execute('SELECT sheet_id,row_index FROM projection_rows WHERE entity_id=?',(r['entity_id'],)).fetchone();line=provider.rows[tuple(m)]
                from crm.projection import HEADERS
                heads=HEADERS['Active Pipeline' if r['entity_kind']=='campaign' else 'Directory']
                assert line[heads.index('entity_rev')]=='5'
                if 'note' in heads:assert line[heads.index('note')]==r['note']
            assert len(frames)==2000
            for r in c.execute('SELECT * FROM audit_transactions'):assert frames[r['commit_seq']]==r['manifest_jcs'].decode()
            assert len(events)==c.execute('SELECT count(*) FROM audit_log').fetchone()[0]
            for r in c.execute('SELECT * FROM audit_log'):assert events[(r['commit_seq'],r['event_ordinal'])]==r['event_jcs'].decode()
            assert not c.execute("SELECT 1 FROM sync_outbox WHERE state!='VERIFIED'").fetchone()
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
        result={'status':'PASS','source':source_digest(),'compatibility_only':args.compatibility_only,'workers':100,'operations':2000,'current_records':400,'max_overlapping_ingest_calls':peak,'publications_before_all_admitted':applied_while_active,'batches':domain.applied,'attempts':domain.attempts,'wall_seconds':time.perf_counter()-start,'ingest_latency':stats(latencies),'cloud_transactions_exact':len(frames),'cloud_events_exact':len(events),'audit':chain,'pending_after_drain':0,'google':'SIMULATED'}
        save(output/'streaming_results.json',result);print(json.dumps({k:v for k,v in result.items() if k!='source'},indent=2),flush=True)
    finally:
        if q:q.close()
        if db:db.close()
        dbmod.MIN_SQLITE=floor;shutil.rmtree(root)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--compatibility-only',action='store_true');args=p.parse_args()
    try:run(args)
    except BaseException as e:
        out=Path(args.output);out.mkdir(parents=True,exist_ok=True);save(out/'streaming_failure.json',{'status':'FAIL','error':repr(e),'traceback':traceback.format_exc()});raise
