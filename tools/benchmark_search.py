#!/usr/bin/env python3
"""Disposable search fixture; NEVER opens an existing database.

Test instrumentation permits the installed SQLite ONLY in a new TemporaryDirectory.
It does not change the production floor or supply a runtime bypass. Interaction
loading uses internal audited 50-record fixture transactions, not public ingestion.
"""
from pathlib import Path
import sys,argparse,tempfile,time,platform,json,sqlite3
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import crm.db as dbmod
from crm.db import Database
from crm.engine import Engine,ActorContext,ALL_CAPS,Work
from crm.ids import new_id
from crm.codec import utcnow
from crm.search import search
from crm.errors import CRMError
from crm.service import Broker
ENTITY_SQL='''SELECT e.entity_id,e.entity_kind,e.display_name,e.status,e.entity_rev,
 d.source_projection_seq,d.search_generation,bm25(entity_fts,0,0,0,5,3,2,1,1,0,0,0) score
 FROM entity_fts JOIN entity_search_documents d ON d.search_doc_id=entity_fts.rowid
 JOIN entities e ON e.tenant_id=d.tenant_id AND e.entity_id=d.entity_id
 WHERE entity_fts MATCH ? AND e.tenant_id=? AND e.deleted_at IS NULL
 ORDER BY score,e.entity_id LIMIT 20'''
INTERACTION_SQL='''SELECT i.interaction_id,i.patron_id,d.patron_id resolved_patron_id,i.subject,i.occurred_at,d.source_commit_seq,d.search_generation,
 bm25(interaction_fts,0,0,0,0,2,2,1,1,0,0,0,0) score FROM interaction_fts
 JOIN interaction_search_documents d ON d.search_doc_id=interaction_fts.rowid
 JOIN interactions i ON i.tenant_id=d.tenant_id AND i.interaction_id=d.interaction_id
 JOIN entities e ON e.tenant_id=d.tenant_id AND e.entity_id=d.patron_id
 WHERE interaction_fts MATCH ? AND i.tenant_id=? AND e.deleted_at IS NULL
 AND i.record_kind!='retraction' AND NOT EXISTS(SELECT 1 FROM interactions n WHERE n.tenant_id=i.tenant_id AND n.supersedes_interaction_id=i.interaction_id)
 ORDER BY score,i.interaction_id LIMIT 20'''

def stats(values):
    s=sorted(values)
    def percentile(n):return s[min(len(s)-1,max(0,int(n*len(s))-1))]/1e6
    return dict(samples=len(s),p50_ms=percentile(.5),p95_ms=percentile(.95),p99_ms=percentile(.99),max_ms=s[-1]/1e6)

def run(output,runs=2,queries=2000,common=200):
    original=dbmod.MIN_SQLITE;actual=sqlite3.sqlite_version_info;dbmod.MIN_SQLITE=min(original,actual)
    try:
        with tempfile.TemporaryDirectory(prefix='crm-retrieval-fixture-') as temp:
            ids=[new_id() for _ in range(3)];db=Database.initialize(Path(temp)/'runtime',*ids)
            e=Engine(db);a=ActorContext(ids[2],ALL_CAPS);tenant=ids[0];sequence=[];groups={};seed_start=time.perf_counter()
            def create(kind,facet):
                idx=len(sequence);eid=new_id();name=f'{kind} Record{idx:06d} research'
                result=e.ingest(e.packet('entity.create',{'entity_id':eid,'entity_kind':kind,'display_name':name,'facet':facet},base=None if not facet else 'current'),a)
                if result['disposition']!='COMMITTED':raise RuntimeError(result)
                sequence.append(eid);groups.setdefault(kind,[]).append(eid);return eid
            for _ in range(50):create('organization',{})
            for i in range(640):create('person',{'organization_id':groups['organization'][i%50]})
            for i in range(50):create('project',{'slug':f'project-{i}'})
            for i in range(10):create('campaign',{'slug':f'campaign-{i}'})
            for i in range(50):create('thread',{'target_app':'ChatGPT','connector_account_id':'synthetic','external_thread_id':f'thread-{i}'})
            for i in range(50):create('stage',{'project_id':groups['project'][i],'plan_version':'1','stage_ordinal':'1','required':True})
            for i in range(50):create('ticket',{'project_id':groups['project'][i],'plan_version':'1','parent_work_item_id':groups['stage'][i]})
            for i in range(50):create('dispatch',{'work_item_id':groups['ticket'][i],'actor_id':a.actor_id,'attempt_no':'1','prompt_hash':'a'*64,'target_app':'ChatGPT','connector_account_id':'synthetic','thread_id':groups['thread'][i]})
            for kind in ('opportunity','contract'):
                for i in range(25):create(kind,{'project_id':groups['project'][i],'primary_patron_id':groups['person'][i]})
            print('Created',len(sequence),'entities',flush=True)
            for idx,eid in enumerate(sequence):
                for j in range(3):
                    r=e.ingest(e.packet('entity.alias.set',{'entity_id':eid,'alias_id':new_id(),'original_value':f'Alias{idx:06d} label{j}','retire':False}),a)
                    if r['disposition']!='COMMITTED':raise RuntimeError(r)
            print('Created 3000 aliases',flush=True)
            summary=('research evidence collaboration results data '*24)[:1024];interaction_ids=[]
            for group in range(1000):
                packet=e.packet('fixture.bulk_interactions',{},base='current')
                with db.transaction() as c:
                    state=c.execute('SELECT * FROM ledger_state').fetchone();packet['authority_epoch']=str(state['authority_epoch'])
                    w=Work(e,c,a,packet,state['commit_seq']+1,utcnow());patron=groups['person'][group%640]
                    for j in range(50):
                        idx=group*50+j;iid=new_id();interaction_ids.append(iid)
                        data=dict(tenant_id=tenant,interaction_id=iid,patron_id=patron,thread_id=groups['thread'][group%50],supersedes_interaction_id=None,record_kind='touchpoint',subject=f'Touchpoint Event{idx:06d}',summary=summary,approved_excerpt=None,source_artifact_id=None,occurred_at='2026-09-01T12:00:00.000Z',recorded_at=w.now,commit_seq=w.seq,actor_id=a.actor_id)
                        w.insert('interactions',data);w.interaction_ids.add(iid);w.add_event('interaction.fixture',data,patron)
                    w.guard(patron,'timeline');w.finish()
                if (group+1)%250==0:print('Loaded',len(interaction_ids),'effective interactions',flush=True)
            seed_seconds=time.perf_counter()-seed_start;e.verify_audit();db.checkpoint();results={}
            classes={
                'exact_id_sql':(lambda c,i:list(c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=? AND deleted_at IS NULL',(tenant,sequence[i%1000]))),queries,1.0),
                'entity_fts_selective_sql':(lambda c,i:list(c.execute(ENTITY_SQL,(f'"Record{i%1000:06d}"',tenant))),queries,1.0),
                'interaction_fts_selective_sql':(lambda c,i:list(c.execute(INTERACTION_SQL,(f'"Event{(i*23)%50000:06d}"',tenant))),queries,1.0),
                'entity_fts_common_sql':(lambda c,i:list(c.execute(ENTITY_SQL,('"research"',tenant))),common,1.0),
                'interaction_fts_common_sql':(lambda c,i:list(c.execute(INTERACTION_SQL,('"research"',tenant))),common,1.0),
                'entity_full_retrieval':(lambda c,i:search(c,tenant,f'Record{i%1000:06d}'),queries,5.0),
                'interaction_full_retrieval':(lambda c,i:search(c,tenant,f'Event{(i*23)%50000:06d}',scope='interactions'),queries,5.0),
                'bounded_fuzzy_retrieval':(lambda c,i:search(c,tenant,f'person Recorx{50+i%640:06d} research',fuzzy=True),common,5.0)}
            for name,(fn,n,target) in classes.items():
                batches=[]
                for rep in range(runs):
                    with db.read() as c:
                        for i in range(min(100,n)):
                            try:fn(c,i)
                            except CRMError:pass
                        durations=[];errors={}
                        for i in range(n):
                            start=time.perf_counter_ns()
                            try:fn(c,i)
                            except CRMError as exc:errors[exc.code]=errors.get(exc.code,0)+1
                            durations.append(time.perf_counter_ns()-start)
                    m=stats(durations);m['errors']=errors;m['p95_target_ms']=target;m['p95_under_target']=not errors and m['p95_ms']<target;batches.append(m)
                results[name]=batches;print(name,'p95_ms',[round(x['p95_ms'],4) for x in batches],flush=True)
            broker=Broker(e,cursor_key=b'benchmark-fixture-key-not-deployed')
            broker_runs=[]
            for rep in range(runs):
                for i in range(100):broker.handle(a,'search',{'query':f'Record{i:06d}'})
                times=[];errors={}
                for i in range(queries):
                    start=time.perf_counter_ns();value,code=broker.handle(a,'search',{'query':f'Record{i%1000:06d}'});times.append(time.perf_counter_ns()-start)
                    if code:errors[str(code)]=errors.get(str(code),0)+1
                record=stats(times);record.update(errors=errors,p95_target_ms=5.0,p95_under_target=not errors and record['p95_ms']<5.0);broker_runs.append(record)
            results['broker_entity_read']=broker_runs
            print('broker_entity_read p95_ms',[round(x['p95_ms'],4) for x in broker_runs],flush=True)
            quality={'fuzzy_fixture_queries':200,'fuzzy_target_in_top20':0,'fuzzy_truncated':0}
            with db.read() as c:
                for i in range(200):
                    try:r=search(c,tenant,f'person Recorx{50+i:06d} research',fuzzy=True)
                    except CRMError:r={'matches':[],'truncated_candidates':True}
                    quality['fuzzy_target_in_top20']+=int(sequence[50+i] in [x['entity_id'] for x in r['matches']]);quality['fuzzy_truncated']+=int(r['truncated_candidates'])
            counts={t:db.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['entities','entity_aliases','interactions','entity_fts','interaction_fts','audit_transactions']}
            report={'fixture':'crm-search-v5-mixed-1000-3000-50000','counts':counts,'kinds':{k:len(v) for k,v in groups.items()},'average_interaction_summary_bytes':len(summary.encode()),'seed_seconds':seed_seconds,'seed_note':'Entities/aliases use public engine commands; interactions use 1000 audited internal 50-record fixture transactions. Not an ingest throughput claim.','environment':{'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'machine':platform.machine(),'processor':platform.processor()},'production_runtime_floor':'.'.join(map(str,original)),'production_runtime_met':actual>=original,'compatibility_fixture_only':actual<original,'runs':runs,'warmup_per_run':100,'selective_queries_per_run':queries,'stress_queries_per_run':common,'concurrent_writer':False,'cold_cli_measured':False,'results':results,'quality':quality,'fixture_revision':'2; fuzzy query retains the full stored name and changes exactly one character; earlier pre-tuning fixture omitted the trailing word and cannot establish recall','overall_gate':'NOT_CERTIFIED: target runtime, concurrent writer and full 2000-query stress repetition remain. Missed classes are FAILED in this fixture.'}
            Path(output).write_text(json.dumps(report,indent=2)+'\n');db.close()
    finally:dbmod.MIN_SQLITE=original
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--runs',type=int,default=2);p.add_argument('--queries',type=int,default=2000);p.add_argument('--common',type=int,default=200);a=p.parse_args()
    if min(a.runs,a.queries,a.common)<1:raise SystemExit('positive counts required')
    run(a.output,a.runs,a.queries,a.common)
