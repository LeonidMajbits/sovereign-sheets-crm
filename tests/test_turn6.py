"""Turn 6 regression tests. No Google services or financial endpoint is contacted."""
import random,copy,concurrent.futures
import pytest
from crm.engine import ActorContext
from crm.codec import MAX_I64
from crm.ids import new_id
from crm.errors import CRMError
from crm.quota import Scheduler,QuotaHold
from tests.fakes import Clock
from tests.test_crm_core import create,get,patch


def candidate(e,eid,n,value,field='note',base='current'):
    return e.packet('entity.lww.set',{'entity_id':eid,'field':field,'value':value,'logical_clock':str(n)},base=base)


def test_lww_candidate_history_not_erased(core):
    e,a=core;eid=create(e,a);base=e.base()
    hi=e.ingest(candidate(e,eid,10,'high',base=base),a)
    lo=e.ingest(candidate(e,eid,3,'low',base=base),a)
    assert hi['data']['selected'] and not lo['data']['selected']
    assert get(e,eid)['note']=='high' and get(e,eid)['entity_rev']==2
    with e.db.read() as c:
        assert c.execute("SELECT count(*) FROM audit_log WHERE event_kind='lamport.candidate'").fetchone()[0]==2
    e.verify_audit()


def test_lww_equal_clock_total_order_and_retry(core):
    e,a=core;eid=create(e,a);base=e.base()
    p=candidate(e,eid,10,'lower',base=base);q=candidate(e,eid,10,'higher',base=base)
    assert q['operation_id']>p['operation_id']
    win=e.ingest(q,a);e.ingest(p,a)
    assert get(e,eid)['note']=='higher';assert e.ingest(q,a)==win


def test_lww_actor_tie_break_is_authenticated(core):
    e,a=core;eid=create(e,a);base=e.base();aid=new_id()
    with e.db.transaction() as c:c.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(e.state()['tenant_id'] if False else c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0],aid,'second','agent'))
    b=ActorContext(aid,a.capabilities)
    pairs=[(candidate(e,eid,9,'a',base=base),a),(candidate(e,eid,9,'b',base=base),b)]
    for p,x in reversed(pairs):e.ingest(p,x)
    assert get(e,eid)['note']==max(pairs,key=lambda px:(px[1].actor_id,px[0]['operation_id']))[0]['payload']['value']


def test_lww_based_patch_cannot_bypass(core):
    e,a=core;eid=create(e,a);e.ingest(candidate(e,eid,1,'owned'),a)
    r=patch(e,a,eid,note='bypass')
    assert r['disposition']=='CONFLICT' and r['data']['code']=='LWW_FIELD_OWNED'
    assert patch(e,a,eid,next_action='independent')['disposition']=='COMMITTED'


def test_lww_first_use_needs_unchanged_field(core):
    e,a=core;eid=create(e,a);p=candidate(e,eid,1,'old');patch(e,a,eid,note='recent')
    assert e.ingest(p,a)['disposition']=='CONFLICT';assert get(e,eid)['note']=='recent'


def test_lww_requires_separate_capability(core):
    e,a=core;eid=create(e,a)
    with pytest.raises(CRMError):e.ingest(candidate(e,eid,1,'denied'),ActorContext(a.actor_id,frozenset({'entity.edit'})))


@pytest.mark.parametrize('field',['status','amount_minor','currency','holder_actor_id','entity_id','claim_generation'])
def test_lww_protected_fields_not_admitted(core,field):
    e,a=core;eid=create(e,a)
    with pytest.raises(CRMError):e.ingest(candidate(e,eid,1,'unsafe',field),a)


@pytest.mark.parametrize('clock',['0','-1','1e3','01',str(MAX_I64)])
def test_lww_clock_domain(core,clock):
    e,a=core;eid=create(e,a);p=candidate(e,eid,1,'x');p['payload']['logical_clock']=clock
    with pytest.raises(CRMError):e.ingest(p,a)


def test_lww_failure_rolls_back_clock_and_state(core):
    e,a=core;eid=create(e,a);p=candidate(e,eid,1,'x')
    def fail(point):
        if point=='before_outbox':raise RuntimeError('crash fixture')
    e.fault=fail
    with pytest.raises(RuntimeError):e.ingest(p,a)
    e.fault=lambda _:None
    assert get(e,eid)['note'] is None
    with e.db.read() as c:assert not c.execute("SELECT 1 FROM runtime_state WHERE key LIKE 'lamport.%'").fetchone()
    assert e.ingest(p,a)['data']['selected']


def test_lww_tombstone_no_resurrection(core):
    e,a=core;eid=create(e,a);p=candidate(e,eid,999,'resurrect')
    e.ingest(e.packet('entity.tombstone',{'entity_id':eid,'reason':'fixture'}),a)
    assert e.ingest(p,a)['disposition']=='CONFLICT'


def test_lww_value_equal_advances_register_not_entity(core):
    e,a=core;eid=create(e,a);e.ingest(candidate(e,eid,1,'x'),a);rev=get(e,eid)['entity_rev']
    e.ingest(candidate(e,eid,2,'x'),a)
    assert get(e,eid)['entity_rev']==rev
    assert not e.ingest(candidate(e,eid,1,'stale'),a)['data']['selected']


def test_lww_forged_actor_not_payload(core):
    e,a=core;eid=create(e,a);p=candidate(e,eid,1,'x');p['payload']['actor_id']=a.actor_id
    with pytest.raises(CRMError):e.ingest(p,a)


@pytest.mark.parametrize('sample',[0.0,0.25,0.75,1.0])
def test_jitter_bounded_and_retry_after(core,tmp_path,sample):
    clock=Clock();q=Scheduler(tmp_path/'q','p','u',clock=clock,pace=0,jitter=lambda:sample)
    try:
        assert q.rejected('sheets_write')-clock()==2*sample
        assert q.rejected('sheets_write',retry_after=7)-clock()>=7
    finally:q.close()


def test_persistent_quota_hold_shared_restart(core,tmp_path):
    clock=Clock();root=tmp_path/'q';q=Scheduler(root,'p','u',clock=clock,pace=15,jitter=lambda:0.5)
    try:
        for _ in range(8):until=q.rejected('sheets_write')
        assert until-clock()>=300
        with pytest.raises(QuotaHold):q.reserve('sheets_write')
    finally:q.close()
    q=Scheduler(root,'p','u',clock=clock,pace=15)
    try:
        with pytest.raises(QuotaHold):q.reserve('sheets_write')
        clock.advance(301);q.reserve('sheets_write');q.succeeded('sheets_write')
    finally:q.close()


def test_invalid_jitter_does_not_commit(core,tmp_path):
    q=Scheduler(tmp_path/'q','p','u',clock=Clock(),jitter=lambda:float('nan'))
    try:
        with pytest.raises(CRMError):q.rejected('sheets_write')
        assert not q.c.execute('SELECT * FROM domains').fetchone()
    finally:q.close()


def test_canonical_encoder_matches_legacy_reference():
    import json
    from crm.codec import jcs
    rng=random.Random(260924)
    def enc(x):
        if type(x) is dict:return '{'+','.join(enc(k)+':'+enc(x[k]) for k in sorted(x,key=lambda k:k.encode('utf-16be'))) + '}'
        if type(x) is list:return '['+','.join(enc(v) for v in x)+']'
        return json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    atoms=[None,True,False,0,-1,2**53-1,'עברית','русский','😀','\ue000','e\u0301','é','\n\t\x01','quote"slash\\']
    for _ in range(1000):
        obj={str(i)+rng.choice(['😀','a','\ue000']):[rng.choice(atoms),{'b':rng.choice(atoms),'a':rng.choice(atoms)}] for i in range(rng.randrange(1,10))}
        assert jcs(obj)==enc(obj).encode('utf-8')


def test_lww_next_action_and_null(core):
    e,a=core;eid=create(e,a)
    e.ingest(candidate(e,eid,1,'next',field='next_action'),a)
    e.ingest(candidate(e,eid,2,None,field='next_action'),a)
    assert get(e,eid)['next_action'] is None
    assert get(e,eid)['entity_rev']==3
    assert patch(e,a,eid,note='independent')['disposition']=='COMMITTED'


def test_lww_schema_manifest_matches_generated_packet(core):
    import json,jsonschema
    from pathlib import Path
    e,a=core;eid=create(e,a);packet=candidate(e,eid,1,'documented')
    schema=json.loads((Path(__file__).resolve().parents[1]/'schema/lww_command_v6.schema.json').read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(packet)
    assert e.ingest(packet,a)['data']['selected']


def test_lww_packet_preparer_real_socket(core,tmp_path):
    import os,sys,json,secrets,subprocess,threading
    from pathlib import Path
    from crm.codec import jcs
    from crm.service import Broker,UnixBrokerServer
    from crm.cli import invoke
    e,a=core;eid=create(e,a);root=Path(__file__).resolve().parents[1]
    sock=Path(f"/tmp/crm_{secrets.token_hex(4)}.sock");key=secrets.token_hex(32)
    server=UnixBrokerServer(sock,Broker(e,cursor_key=b'm'*32),{'client':{'actor_id':a.actor_id,'capabilities':sorted(a.capabilities),'key_hex':key}})
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=tmp_path/'client.json';config.write_bytes(jcs({'socket':str(sock),'key_id':'client','key_hex':key}));config.chmod(0o600)
    payload=tmp_path/'payload.json';payload.write_bytes(jcs({'entity_id':eid,'field':'note','value':'prepared v6','logical_clock':'1'}))
    packet=tmp_path/'command.json'
    try:
        cmd=[sys.executable,str(root/'tools/crm-make-command.py'),'--command','entity.lww.set','--payload',str(payload),'--output',str(packet)]
        child=subprocess.run(cmd,env=dict(os.environ,CRM_CLIENT_CONFIG=str(config)),capture_output=True,text=True,timeout=30)
        assert child.returncode==0,child.stdout+child.stderr
        obj=json.loads(packet.read_bytes());assert obj['schema_version']=='crm.command.v6'
        assert get(e,eid)['note'] is None
        result,code=invoke(config,'ingest',{'packet':obj});assert code==0
        assert get(e,eid)['note']=='prepared v6'
        seq=e.state()['commit_seq'];again,code=invoke(config,'ingest',{'packet':obj})
        assert code==0 and again['data']==result['data'] and e.state()['commit_seq']==seq
    finally:server.shutdown();server.server_close();thread.join(5);sock.unlink(missing_ok=True)
