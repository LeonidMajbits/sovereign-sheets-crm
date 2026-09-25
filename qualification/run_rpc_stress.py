#!/usr/bin/env python3
"""100 real Unix-socket clients; bounded retry retains exact business packets.
Fresh synthetic fixtures only. No Google request or production identity is used.
"""
from pathlib import Path
import sys,tempfile,sqlite3,threading,concurrent.futures,secrets,time,json,random,shutil,argparse,collections,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import crm.db as dbmod
from crm.engine import ALL_CAPS
from crm.service import Broker,UnixBrokerServer
from crm.cli import invoke
from crm.codec import jcs
from crm.errors import CRMError
from qualification.run_matrix import uid,save,stats,source_digest
from qualification.run_adversarial import fresh

def run(args):
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True);floor=dbmod.MIN_SQLITE
    if args.compatibility_only:dbmod.MIN_SQLITE=min(floor,sqlite3.sqlite_version_info)
    else:dbmod.runtime_check()
    root=Path(tempfile.mkdtemp(prefix='crm-rpc-q6-'));e=a=server=None
    try:
        e,a,actors=fresh(root/'runtime',100);broker=Broker(e,cursor_key=secrets.token_bytes(32));principals={};configs=[]
        sock=root/'broker.sock'
        for i,actor in enumerate(actors):
            key=secrets.token_hex(32);keyid=f'worker-{i}'
            principals[keyid]={'key_hex':key,'actor_id':actor.actor_id,'capabilities':sorted(ALL_CAPS)}
            config=root/f'client-{i}.json';config.write_bytes(jcs({'socket':str(sock),'key_id':keyid,'key_hex':key}));config.chmod(0o600);configs.append(config)
        server=UnixBrokerServer(sock,broker,principals);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        barrier=threading.Barrier(100);lock=threading.Lock();errors=collections.Counter();times=[];attempts=0
        def client(i):
            nonlocal attempts
            rng=random.Random(i+260924);packets=[];barrier.wait(120)
            def send(packet):
                nonlocal attempts
                tic=time.perf_counter_ns()
                for attempt in range(30):
                    with lock:attempts+=1
                    try:
                        result,code=invoke(configs[i],'ingest',{'packet':packet})
                        if code==0:
                            with lock:times.append(time.perf_counter_ns()-tic)
                            return result['data']
                        if code not in (6,9):raise AssertionError(result)
                        label=f'exit_{code}'
                    except CRMError as exc:
                        if exc.code not in ('BROKER_RESPONSE','LOCAL_OUTCOME_UNKNOWN'):raise
                        label=exc.code
                    except OSError as exc:label=type(exc).__name__
                    with lock:errors[label]+=1
                    time.sleep(rng.uniform(.005,min(1.0,.02*2**min(attempt,6))))
                raise RuntimeError('RPC bounded retries exhausted; original packet must remain pending')
            for j in range(5):
                p=e.packet('entity.create',{'entity_id':uid(600000+i*10+j),'entity_kind':'person','display_name':f'RPC worker {i} item {j}','facet':{}},operation_id=uid(800000+i*10+j),base=None)
                r=send(p);assert r['disposition']=='COMMITTED';packets.append((p,r))
            for p,r in packets:assert send(p)==r
        tic=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:list(pool.map(client,range(100)))
        with e.db.read() as c:
            assert c.execute('SELECT count(*) FROM entities').fetchone()[0]==500
            assert c.execute('SELECT count(*) FROM operation_outcomes').fetchone()[0]==500
            assert c.execute('SELECT count(*) FROM entity_versions').fetchone()[0]==500
        report={'status':'PASS','source':source_digest(),'compatibility_only':args.compatibility_only,'workers':100,'canonical_operations':500,'exact_replays':500,'wire_attempts':attempts,'transient_rejections':dict(errors),'logical_request_latency_including_retry':stats(times),'wall_seconds':time.perf_counter()-tic,'audit':e.verify_audit(),'server_inflight_bound':32,'nonce_window_capacity':4096,'sustained_50000_rpc_operations_tested':False,'google_used':False}
        save(out/'rpc_results.json',report);print(json.dumps({k:v for k,v in report.items() if k!='source'},indent=2))
    finally:
        if server:server.shutdown();server.server_close();thread.join(5)
        if e:e.db.close()
        dbmod.MIN_SQLITE=floor;shutil.rmtree(root)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--compatibility-only',action='store_true');a=p.parse_args()
    try:run(a)
    except BaseException as ex:save(Path(a.output)/'rpc_failure.json',{'status':'FAIL','message':str(ex),'traceback':traceback.format_exc()});raise
