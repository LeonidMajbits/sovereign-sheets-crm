#!/usr/bin/env python3
"""Production-engine qualification on fresh synthetic tenant ledgers.

Default refuses unsupported SQLite. --compatibility-only is TEST instrumentation
confined to newly allocated temporary roots, and stamps all evidence non-target.
No credentials, browser, real Google Sheet, production DB or network is used.
"""
from pathlib import Path
import sys,os,json,time,sqlite3,platform,tempfile,threading,concurrent.futures,gzip,hashlib,random,math,traceback,resource,argparse,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import crm.db as dbmod
from crm.db import Database
from crm.engine import Engine,ActorContext,ALL_CAPS
from crm.ids import encode
from crm.codec import digest,jcs,loads
from crm.quota import Scheduler,QuotaHold
from crm.sync import Publisher
from crm.google_api import NotApplied,Ambiguous
from qualification.provider import VirtualClock,FaultDomain,TypedSheets


def uid(n):return encode((1700000000000<<80)+n)
def stats(ns):
    s=sorted(ns)
    return {f'p{p}_ms':s[max(0,math.ceil(p/100*len(s))-1)]/1e6 for p in (50,95,99)}|{'max_ms':max(s)/1e6,'samples':len(s)}
def save(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n');tmp.replace(path)
def source_digest():
    files={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for dirname in ('crm','schema','qualification') for p in (ROOT/dirname).rglob('*') if p.is_file() and p.suffix in ('.py','.sql','.json') and 'evidence' not in p.parts}
    return {'files':files,'sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}

def matrix(args):
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    started=time.time();oldfloor=dbmod.MIN_SQLITE;env={'platform':platform.platform(),'machine':platform.machine(),'python':sys.version,'sqlite':sqlite3.sqlite_version,'cpu_count':os.cpu_count(),'target_darwin_arm64':platform.system()=='Darwin' and platform.machine()=='arm64','sqlite_runtime_gate':sqlite3.sqlite_version_info>=oldfloor,'compatibility_only':args.compatibility_only,'network':'SIMULATED_ONLY','source':source_digest()}
    save(output/'environment.json',env)
    if args.require_darwin_arm64 and not env['target_darwin_arm64']:raise RuntimeError('TARGET_MISMATCH')
    if not env['sqlite_runtime_gate'] and not args.compatibility_only:dbmod.runtime_check()
    if args.compatibility_only:dbmod.MIN_SQLITE=min(oldfloor,sqlite3.sqlite_version_info)
    assert args.workers%args.tenants==0 and args.operations%args.workers==0
    per_worker=args.operations//args.workers;assert per_worker%5==0
    per_create=per_worker//5
    temp=Path(tempfile.mkdtemp(prefix='crm-turn6-'))
    dbs=[];engines=[];owners=[];records=[];expected={};loglock=threading.Lock()
    try:
        for t in range(args.tenants):
            db=Database.initialize(temp/f'tenant-{t}',uid(100+t),uid(200+t),uid(300+t))
            e=Engine(db);a=ActorContext(uid(300+t),ALL_CAPS|{'audit.read'})
            with db.transaction() as c:
                for w in range(t,args.workers,args.tenants):c.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(uid(100+t),uid(1000+w),f'worker-{w:03d}','agent'))
            dbs.append(db);engines.append(e);owners.append(a)
        barrier=threading.Barrier(args.workers);replay_barrier=threading.Barrier(args.workers)
        inflight=0;peak=0;completed=0;replayed=0;latencies=[];replay_ns=[]
        def worker(w):
            nonlocal inflight,peak,completed,replayed
            t=w%args.tenants;local=w//args.tenants;e=engines[t];a=ActorContext(uid(1000+w),ALL_CAPS)
            packets=[];trace=[];local_clock=0
            barrier.wait(timeout=120)
            for i in range(per_worker):
                j=i%per_create;eid=uid(100000+local*per_create+j)
                kind='campaign' if j%10==0 else 'person'
                if i<per_create:
                    packet=e.packet('entity.create',{'entity_id':eid,'entity_kind':kind,'display_name':f'{kind} TENANT{t:02d} W{w:03d} E{j:04d}', 'facet':{'slug':f'campaign-{local}-{j}'} if kind=='campaign' else {}},operation_id=uid(1000000+w*per_worker+i),base=None)
                else:
                    local_clock+=1
                    value=f'TENANT{t:02d} worker{w:03d} entity{j:04d} revision{i//per_create}'
                    packet=e.packet('entity.lww.set',{'entity_id':eid,'field':'note','value':value,'logical_clock':str(local_clock)},operation_id=uid(1000000+w*per_worker+i))
                with loglock:inflight+=1;peak=max(peak,inflight)
                tic=time.perf_counter_ns()
                try:result=e.ingest(packet,a)
                finally:
                    elapsed=time.perf_counter_ns()-tic
                    with loglock:inflight-=1
                assert result['disposition']=='COMMITTED',result
                if i>=per_create:
                    assert result['data']['selected'];local_clock=max(local_clock,int(result['data']['receive_clock']))
                packets.append((packet,result));trace.append({'worker':w,'tenant_index':t,'packet':packet,'outcome':result,'ingest_ns':elapsed})
                with loglock:
                    latencies.append(elapsed);completed+=1
                    if i>=per_create:expected[(t,eid)]=value
                    if completed%2500==0:print(f'ADMITTED {completed}/{args.operations}',flush=True)
            replay_barrier.wait(timeout=900)
            for packet,result in packets:
                tic=time.perf_counter_ns();got=e.ingest(packet,a);dt=time.perf_counter_ns()-tic
                assert got==result,'same operation did not return identical outcome'
                with loglock:replayed+=1;replay_ns.append(dt)
            return trace
        tic=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for trace in pool.map(worker,range(args.workers)):records.extend(trace)
        workload_seconds=time.perf_counter()-tic
        assert completed==args.operations and replayed==args.operations
        assert len({(r['tenant_index'],r['packet']['operation_id']) for r in records})==args.operations
        records.sort(key=lambda r:(r['tenant_index'],int(r['outcome']['commit_seq'])))
        with gzip.open(output/'operation_trace.jsonl.gz','wt',encoding='utf-8') as f:
            for r in records:f.write(json.dumps(r,separators=(',',':'))+'\n')
        checks=[]
        for t,e in enumerate(engines):
            chain=e.verify_audit()
            with e.db.read() as c:
                counts={table:c.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('entities','campaigns','entity_versions','operation_outcomes','audit_transactions','sync_outbox','entity_search_documents')}
                assert counts['audit_transactions']==args.operations//args.tenants
                assert counts['entity_versions']==args.operations//args.tenants
                assert counts['entities']==args.operations//5//args.tenants
                assert counts['entity_search_documents']==counts['entities']
                for row in c.execute('SELECT entity_id,entity_rev,note FROM entities'):
                    assert row['entity_rev']==5 and row['note']==expected[(t,row['entity_id'])]
                assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not c.execute('PRAGMA foreign_key_check').fetchall()
                settings={k:c.execute(f'PRAGMA {k}').fetchone()[0] for k in ('journal_mode','synchronous','foreign_keys')}
            # Exercise real rejection of a packet bound to another tenant.
            from crm.errors import CRMError
            foreign=records[0]['packet'] if t else next(r['packet'] for r in records if r['tenant_index']==1)
            try:e.ingest(foreign,owners[t])
            except CRMError as ex:assert ex.code=='TENANT_OR_LEDGER_MISMATCH'
            else:raise AssertionError('cross-tenant mutation admitted')
            checks.append({'tenant_index':t,'chain':chain,'counts':counts,'storage':settings})
        save(output/'local_state_checks.json',checks)
        print('ALL LOCAL STATE AND REPLAY ORACLES PASS',flush=True)
        # Close/reopen actual disk ledgers before cloud drain. No copied live WAL.
        for db in dbs:db.close()
        dbs=[Database(temp/f'tenant-{t}') for t in range(args.tenants)]
        engines=[Engine(db) for db in dbs]
        clock=VirtualClock();rng=random.Random(args.seed);q=Scheduler(temp/'quota','shared-project','shared-principal',clock=clock,pace=15,jitter=rng.random)
        domain=FaultDomain();providers=[];publishers=[]
        for t,e in enumerate(engines):
            config={'spreadsheet_id':f'SIMULATED-tenant-{t}','generation_id':uid(500+t),'sheet_ids':{'Directory':101,'Active Pipeline':102,'Completed Archives':103,'_Control':104,'_Changes':105}}
            p=TypedSheets(config,q,domain);pub=Publisher(e,p,q,config)
            while True:
                try:pub.activate();break
                except QuotaHold as hold:clock.advance(max(.001,hold.until-clock()+.001))
            providers.append(p);publishers.append(pub)
        domain.offline=True;offline_start=clock()
        for t,pub in enumerate(publishers):
            try:pub.run(owners[t],mode='push')
            except ConnectionError:pass
            except QuotaHold:pass
            else:raise AssertionError('offline published')
        assert domain.applied==0
        pending_offline=sum(int(pub.plan()['pending_transactions']) for pub in publishers)
        assert pending_offline==args.operations
        clock.advance(4*3600);domain.offline=False
        q.close();q=Scheduler(temp/'quota','shared-project','shared-principal',clock=clock,pace=15,jitter=rng.random)
        for p,pub in zip(providers,publishers):p.scheduler=q;pub.scheduler=q
        try:q.reserve('sheets_write')
        except QuotaHold:pass
        else:raise AssertionError('restart granted free quota burst')
        domain.reject_remaining=8;domain.periodic_rejections=True;domain.lost_responses={23,251}
        recover_start=clock();pub_start=time.perf_counter();holds=0;unknowns=0
        remaining=set(range(args.tenants));passes=0
        while remaining:
            for t in sorted(remaining):
                passes+=1
                try:publishers[t].run(owners[t],mode='push')
                except QuotaHold as hold:
                    holds+=1;clock.advance(max(.001,hold.until-clock()+.001))
                except NotApplied:pass
                except Ambiguous:unknowns+=1
                if not int(publishers[t].plan()['pending_transactions']):remaining.remove(t)
                if passes%100==0:print(f'DRAIN applied={domain.applied} attempts={domain.attempts} remaining_tenants={len(remaining)}',flush=True)
                assert passes<100000,'drain stalled'
        drain_seconds=time.perf_counter()-pub_start
        batches=[b for p in providers for b in p.batch_trace]
        # Independent cloud-history and final-row oracle, all transactions and rows.
        cloud_checks=[]
        for t,(e,p) in enumerate(zip(engines,providers)):
            frames={};seen_events=0;sid=p.sheet_ids['_Changes'];business_count=0
            for (s,row),line in p.rows.items():
                if s==sid and row>1 and line:
                    if line[0]=='TRANSACTION':frames[int(line[4])]=(line[9],line[8])
                    elif line[0]=='EVENT':seen_events+=1
            with e.db.read() as c:
                txs=c.execute('SELECT * FROM audit_transactions ORDER BY commit_seq').fetchall()
                assert len(frames)==len(txs)
                for tx in txs:assert frames[tx['commit_seq']]==(tx['transaction_digest'],tx['manifest_jcs'].decode())
                expected_events=c.execute('SELECT count(*) FROM audit_log').fetchone()[0];assert seen_events==expected_events
                # Verify every event's exact bytes/digest, not just count.
                event_rows={(int(line[4]),int(line[5])):line for (s,row),line in p.rows.items() if s==sid and row>1 and line and line[0]=='EVENT'}
                for ev in c.execute('SELECT * FROM audit_log'):
                    line=event_rows[(ev['commit_seq'],ev['event_ordinal'])]
                    assert line[8]==ev['event_jcs'].decode() and line[9]==digest(ev['event_jcs'],'CRM3:event:v1')
                for r in c.execute('SELECT * FROM entities'):
                    name='Active Pipeline' if r['entity_kind']=='campaign' else 'Directory'
                    mapping=c.execute('SELECT sheet_id,row_index FROM projection_rows WHERE entity_id=?',(r['entity_id'],)).fetchone()
                    line=p.rows[tuple(mapping)];headers=__import__('crm.projection',fromlist=['HEADERS']).HEADERS[name]
                    assert line[headers.index('entity_id')]==r['entity_id']
                    assert line[headers.index('note')]==r['note'] if 'note' in headers else True
                    assert line[headers.index('tenant_id')]==e.state()['tenant_id'] if False else line[headers.index('tenant_id')]==uid(100+t)
                    assert line[headers.index('entity_rev')]=='5';business_count+=1
                assert not c.execute("SELECT 1 FROM sync_outbox WHERE state!='VERIFIED'").fetchone()
            cloud_checks.append({'tenant':t,'transactions':len(frames),'events':seen_events,'business_rows':business_count,'all_exact':True})
        # Physical starts obey the actual shared rolling admission ceilings.
        starts=q.c.execute('SELECT kind,at FROM starts ORDER BY at').fetchall();maxima={}
        for kind in {x[0] for x in starts}:
            times=[x[1] for x in starts if x[0]==kind];left=0;peakn=0
            for right,at in enumerate(times):
                while times[left]<=at-60:left+=1
                peakn=max(peakn,right-left+1)
            assert peakn<=q.LIMITS[kind];maxima[kind]=peakn
        with gzip.open(output/'batch_trace.jsonl.gz','wt') as f:
            for b in sorted(batches,key=lambda b:b['at']):f.write(json.dumps(b,separators=(',',':'))+'\n')
        save(output/'fault_trace.json',domain.events)
        save(output/'quota_starts.json',{'starts':starts,'rolling_maxima':maxima})
        save(output/'cloud_checks.json',cloud_checks)
        report={'status':'LOCAL_SIMULATED_MATRIX_PASS','production_admitted':False,'environment':env,
          'fixture':{'workers':args.workers,'tenants':args.tenants,'operations':args.operations,'creates':args.operations//5,'lww_mutations':args.operations*4//5,'same_id_replays':replayed,'seed':args.seed,'shared_tabs':'Workers share their tenant workbook tabs; untrusted tenant workbooks remain isolated.'},
          'workload':{'wall_seconds_admission_plus_replays':workload_seconds,'max_overlapping_ingest_calls':peak,'ingest':stats(latencies),'replay':stats(replay_ns)},
          'integrity':{'lost_accepted_operations':0,'missing_entity_versions':0,'duplicate_canonical_effects':0,'cross_tenant_accepts':0,'local_chain_checks':len(checks),'cloud_transactions_exact':sum(x['transactions'] for x in cloud_checks),'cloud_events_exact':sum(x['events'] for x in cloud_checks),'double_spend_scope':'Idempotent CRM effects only; claims and synthetic spend negative control are separate matrix cases. No financial endpoint tested.'},
          'partition':{'virtual_offline_seconds':14400,'pending_after_offline':pending_offline,'reopened_ledgers':len(dbs),'automatic_recovery_without_browser':True},
          'publication':{'batches':len(batches),'write_attempts':domain.attempts,'max_bytes':max(b['bytes'] for b in batches),'max_physical_business_rows':max(b['physical_business_rows'] for b in batches),'bytes':sum(b['bytes'] for b in batches),'429s':sum(x['event']=='429' for x in domain.events),'lost_response_injections':sum(x['event']=='response_lost_after_apply' for x in domain.events),'unknown_exceptions':unknowns,'quota_holds':holds,'rolling_start_maxima':maxima,'virtual_recovery_seconds':clock()-recover_start,'wall_drain_seconds':drain_seconds,'remaining':0},
          'total_wall_seconds':time.time()-started,'peak_rss_platform_units':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'raw_fixture_root':str(temp) if args.keep_fixtures else 'deleted_after_test'}
        save(output/'matrix_results.json',report)
        q.close();print(json.dumps({k:report[k] for k in ('status','fixture','workload','publication')},indent=2),flush=True)
        return report
    finally:
        for db in dbs:
            try:db.close()
            except Exception:pass
        dbmod.MIN_SQLITE=oldfloor
        if not args.keep_fixtures:shutil.rmtree(temp)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--workers',type=int,default=100);p.add_argument('--tenants',type=int,default=10);p.add_argument('--operations',type=int,default=50000);p.add_argument('--seed',type=int,default=260924);p.add_argument('--compatibility-only',action='store_true');p.add_argument('--require-darwin-arm64',action='store_true');p.add_argument('--keep-fixtures',action='store_true');args=p.parse_args()
    try:matrix(args)
    except BaseException as exc:
        Path(args.output).mkdir(parents=True,exist_ok=True);save(Path(args.output)/'matrix_failure.json',{'status':'FAIL','type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()});raise
