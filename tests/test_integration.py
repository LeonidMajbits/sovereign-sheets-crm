"""Real broker/socket and cross-language crypto; Google remains an interface mock."""
import copy,json,secrets,subprocess,threading,os,sys,hashlib,sqlite3
from pathlib import Path
from datetime import datetime,timezone,timedelta
import pytest
from crm.codec import jcs,mac,digest,utcnow
from crm.errors import CRMError
from crm.service import Broker,UnixBrokerServer,LocalAuthenticator
from crm.cli import invoke,parse
from crm.engine import Engine,ALL_CAPS,ActorContext
from crm.db import Database
from crm.ids import new_id
from crm.ingress import verify_delivery
from tests.test_crm_core import create,worktree,record_artifact,get,patch

ROOT=Path(__file__).resolve().parent.parent

def test_apps_script_node_suite():
    r=subprocess.run(['node',str(ROOT/'tests/test_apps_script.js')],capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stdout+r.stderr
    result=json.loads(r.stdout);assert result['passed']>=20;assert result['failed']==0


def test_python_to_apps_script_to_python_custody(core,tmp_path):
    e,a=core;s=e.state();gateway='22'*32;sender='11'*32
    payload=e.packet('entity.create',{'entity_id':new_id(),'entity_kind':'person','display_name':'Cross-language patron','facet':{}},base=None)
    config={'profile':'optional_ingress','tenant_id':s['tenant_id'],'ledger_id':s['ledger_id'],'audience':'test','staging_folder_id':'fixture-folder','workbook_id':'fixture-book','generation_id':new_id(),'sheet_ids':{'Directory':101,'Active Pipeline':102,'Completed Archives':103,'_Control':104,'_Changes':105},'gateway_key_id':'gateway-v1','gateway_key_hex':gateway,'gateway_sender_key_id':'gateway','senders':{'client':{'key_hex':sender,'capabilities':['entity.create'],'actor_id':a.actor_id},'gateway':{'key_hex':'33'*32,'capabilities':['dirty_hint'],'actor_id':a.actor_id}}}
    envelope={'protocol':'crm.ingress.v4','kind':'command','delivery_id':new_id(),'sender_key_id':'client','audience':'test','tenant_id':s['tenant_id'],'ledger_id':s['ledger_id'],'issued_at':utcnow(),'expires_at':(datetime.now(timezone.utc)+timedelta(seconds=300)).isoformat(timespec='milliseconds').replace('+00:00','Z'),'nonce':secrets.token_hex(32),'payload':payload,'payload_digest':digest(payload)}
    envelope['expires_at']=(datetime.fromisoformat(envelope['issued_at'].replace('Z','+00:00'))+timedelta(seconds=300)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    envelope['mac']=mac(bytes.fromhex(sender),envelope)
    path=tmp_path/'packet.json';path.write_bytes(jcs({'config':config,'envelope':envelope}))
    process=subprocess.run(['node',str(ROOT/'tests/test_apps_script.js'),'--roundtrip',str(path)],capture_output=True,text=True,timeout=30);assert process.returncode==0,process.stderr
    data=json.loads(process.stdout);assert data['response']['state']=='RECEIVED',data
    raw=data['recordedBody'].encode();home=dict(config,gateway_keys={'gateway-v1':gateway})
    # Four-hour delay does not invalidate an authenticated original admission time.
    admitted,actor=verify_delivery(raw,home,now=datetime.now(timezone.utc).timestamp()+14400)
    receipt={'file_id':'file-1','content_digest':digest(raw),'delivery_id':envelope['delivery_id']}
    result=e.ingest(admitted['payload'],actor,staging_receipt=receipt);assert result['disposition']=='COMMITTED'
    seq=e.state()['commit_seq'];receipt['file_id']='file-duplicate'
    assert e.ingest(admitted['payload'],actor,staging_receipt=receipt)==result
    assert e.state()['commit_seq']==seq
    with e.db.read() as c:assert c.execute('SELECT count(*) FROM staging_receipts').fetchone()[0]==2
    broken=json.loads(raw);broken['custody']['received_at']=utcnow()
    broken['custody']['envelope_digest']='0'*64
    with pytest.raises(CRMError):verify_delivery(jcs(broken),home)


def test_authenticated_unix_cli(core,tmp_path):
    e,a=core;eid=create(e,a);sock=Path(f"/tmp/crm_{secrets.token_hex(4)}.sock");key=secrets.token_hex(32)
    broker=Broker(e,cursor_key=b'c'*32);principals={'client':{'actor_id':a.actor_id,'capabilities':sorted(a.capabilities),'key_hex':key}}
    server=UnixBrokerServer(sock,broker,principals);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=tmp_path/'client.json';config.write_bytes(jcs({'socket':str(sock),'key_id':'client','key_hex':key}));config.chmod(0o600)
    try:
        result,code=invoke(config,'get',{'id':eid});assert code==0;assert result['data']['entity']['entity_id']==eid
        env=dict(os.environ,CRM_CLIENT_CONFIG=str(config))
        child=subprocess.run([sys.executable,str(ROOT/'tools/crm-lab.py'),'search','Ada'],env=env,capture_output=True,text=True,timeout=30)
        assert child.returncode==0,child.stdout+child.stderr;assert json.loads(child.stdout)['data']['matches'];assert not child.stderr
        dry=subprocess.run([sys.executable,str(ROOT/'tools/crm-lab.py'),'sync','--dry-run'],env=env,capture_output=True,text=True,timeout=30)
        assert dry.returncode==0;assert json.loads(dry.stdout)['data']['network_used'] is False
        packet_path=tmp_path/'made-command.json'
        maker=[sys.executable,str(ROOT/'tools/crm-make-command.py'),'--command','entity.create',
               '--payload',str(ROOT/'examples/new-person.payload.json'),'--independent','--output',str(packet_path)]
        prepared=subprocess.run(maker,env=env,capture_output=True,text=True,timeout=30)
        assert prepared.returncode==0,prepared.stdout+prepared.stderr
        assert json.loads(prepared.stdout)['state']=='PREPARED_NOT_INGESTED'
        before=e.state()['commit_seq']
        accepted=subprocess.run([sys.executable,str(ROOT/'tools/crm-lab.py'),'ingest',str(packet_path)],env=env,capture_output=True,text=True,timeout=30)
        assert accepted.returncode==0,accepted.stdout+accepted.stderr
        assert e.state()['commit_seq']==before+1
        refused=subprocess.run(maker,env=env,capture_output=True,text=True,timeout=30)
        assert refused.returncode==7 and json.loads(refused.stdout)['error']=='PACKET_EXISTS_RESEND_UNCHANGED'
    finally:server.shutdown();server.server_close();thread.join(timeout=5);sock.unlink(missing_ok=True)


@pytest.mark.parametrize('argv',[['list','--limit','1','--limit','2'],['sync','--push','--pull'],['proposals','resolve','x','--accept','--reject'],['list','--invented','a']])
def test_cli_rejects_ambiguous_options(argv):
    with pytest.raises(CRMError):parse(argv)


def test_restart_holds_claims(core):
    e,a=core;*_,dispatch=worktree(e,a);token=e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)['data']['claim_token']
    root=e.db.root;e.db.close();db2=Database(root);e2=Engine(db2)
    try:
        with db2.read() as c:assert c.execute('SELECT claim_state FROM claims WHERE resource_id=?',(dispatch,)).fetchone()[0]=='RECOVERY_HOLD'
        assert e2.ingest(e2.packet('claim.release',{'resource_id':dispatch,'claim_token':token,'reason':'late stale worker'}),a)['disposition']=='CONFLICT'
        e2.verify_audit()
    finally:db2.close()


def test_fencing_requires_host_proof(core,tmp_path):
    e,a=core;*_,dispatch=worktree(e,a);e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)
    artifact=record_artifact(e,a,tmp_path)
    p=e.packet('claim.recover',{'resource_id':dispatch,'expected_generation':'1','fencing_evidence_artifact_id':artifact,'reason':'requested recovery'})
    with pytest.raises(CRMError) as exc:e.ingest(p,a)
    assert exc.value.code=='FENCING_PROVIDER_REQUIRED'
    e.fencing_verifier=lambda evidence,eid,claim: True # synthetic executor proof; never production default
    assert e.ingest(p,a)['disposition']=='COMMITTED'


def test_schema_fingerprint_detects_removed_trigger(core):
    e,a=core;root=e.db.root
    with e.db.transaction() as c:c.execute('DROP TRIGGER entities_no_delete')
    e.db.close()
    with pytest.raises(CRMError) as exc:Database(root)
    assert exc.value.code=='SCHEMA_FINGERPRINT_MISMATCH'


def test_vault_fails_without_advancing_capture(core,monkeypatch):
    from crm.quarantine import capture
    e,a=core;eid=create(e,a);seq=e.state()['commit_seq']
    def fail(_):raise OSError('injected disk full')
    monkeypatch.setattr(e.vault,'put',fail)
    with pytest.raises(OSError):capture(e,a,resource='x',generation=new_id(),sheet=101,row=2,column=28,entity=eid,field='human_note',cell={'userEnteredValue':{'stringValue':'not retained'}})
    assert e.state()['commit_seq']==seq


def test_signed_snapshot_and_fenced_restore(core,tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from crm.snapshot import create_snapshot,verify_snapshot,restore_fenced
    e,a=core;eid=create(e,a);key=Ed25519PrivateKey.generate();dest=tmp_path/'signed_snapshot'
    manifest=create_snapshot(e,dest,key,'test-key')
    assert verify_snapshot(dest,key.public_key(),e.state()['ledger_id'])['snapshot_id']==manifest['snapshot_id']
    with pytest.raises(CRMError):verify_snapshot(dest,Ed25519PrivateKey.generate().public_key(),e.state()['ledger_id'])
    restored=tmp_path/'restored';out=restore_fenced(dest,restored,key.public_key(),e.state()['ledger_id']);assert out['state']=='RECOVERY_HOLD'
    db=Database(restored);copy_engine=Engine(db)
    try:
        with pytest.raises(CRMError) as exc:copy_engine.ingest(copy_engine.packet('entity.patch',{'entity_id':eid,'changes':{'note':'must not resume'}}),a)
        assert exc.value.code=='AUTHORITY_HOLD'
    finally:db.close()


def test_snapshot_tampering_detected(core,tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from crm.snapshot import create_snapshot,verify_snapshot
    e,a=core;create(e,a);key=Ed25519PrivateKey.generate();dest=tmp_path/'snapshot'
    create_snapshot(e,dest,key,'test')
    with (dest/'crm.db').open('ab') as f:f.write(b'tamper')
    with pytest.raises(CRMError) as exc:verify_snapshot(dest,key.public_key(),e.state()['ledger_id'])
    assert exc.value.code=='SNAPSHOT_PART_DIGEST'


def test_merge_preserves_effective_interaction(core,tmp_path):
    e,a=core;one=create(e,a,name='Ada One');two=create(e,a,name='Ada Two')
    iid=new_id();e.ingest(e.packet('interaction.append',{'interaction_id':iid,'patron_id':two,'subject':'Historical meeting','occurred_at':'2026-09-20T12:00:00.000Z'}),a)
    artifact=record_artifact(e,a,tmp_path)
    out=e.ingest(e.packet('entity.merge',{'survivor_id':one,'retired_id':two,'reason':'reviewed same person','evidence_artifact_id':artifact}),a)
    assert out['disposition']=='COMMITTED',out
    from tests.test_crm_core import sq
    result=sq(e,'Historical',scope='interactions')['matches'][0]
    assert result['patron_id']==two;assert result['resolved_patron_id']==one
    assert sq(e,'Ada Two')['matches'][0]['entity_id']==one


def test_rest_field_mask_balanced_and_literal_ranges():
    from crm.google_api import Sheets
    class Rest:
        def call(self,url,**kwargs):
            from urllib.parse import urlsplit,parse_qs
            query=parse_qs(urlsplit(url).query);mask=query['fields'][0]
            assert mask.count('(')==mask.count(')')
            assert query['ranges']==["'Directory'!A2:AE2"]
            return {'spreadsheetId':'fixture','sheets':[]}
    adapter=Sheets(Rest(),'fixture',{'Directory':101})
    assert len(adapter.read([(101,2,0,1,31)]))==31

def test_client_partial_send_is_unknown(tmp_path,monkeypatch):
    import socket
    from crm.cli import invoke
    path=tmp_path/'client.json';path.write_bytes(jcs({'socket':str(tmp_path/'sock'),'key_id':'fixture','key_hex':'a'*64}));path.chmod(0o600)
    class Broken:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,n):pass
        def connect(self,path):pass
        def sendall(self,data):raise OSError('may already have arrived')
    monkeypatch.setattr(socket,'socket',lambda *args:Broken())
    with pytest.raises(CRMError) as err:invoke(path,'ingest',{})
    assert err.value.exit_code==9 and err.value.code=='LOCAL_OUTCOME_UNKNOWN'


def test_fuzzy_candidate_policy(core):
    from tests.test_crm_core import create,sq
    e,a=core;eid=create(e,a,name='Alexandra Forsyth')
    result=sq(e,'Alexanxra Forsyth',fuzzy=True)
    assert result['matches'][0]['entity_id']==eid
    assert float(result['matches'][0]['name_similarity'])>=0.85
    assert not sq(e,'Ax',fuzzy=True)['matches']


def test_provision_only_unused_resource(core,tmp_path):
    from crm.provision import LayoutProvisioner
    from crm.quota import Scheduler
    from crm.sync import Publisher
    from crm.google_api import Sheets
    from tests.fakes import Clock
    from crm.projection import HEADERS
    from crm.codec import safe_cell,loads
    e,a=core;clock=Clock();q=Scheduler(tmp_path/'quota','project','principal',clock=clock)
    config={'spreadsheet_id':'synthetic-id','generation_id':new_id(),'sheet_ids':{'Directory':0,'Active Pipeline':101,'Completed Archives':102,'_Control':103,'_Changes':104}}
    class Creds:
        def authorization(self):return 'test-only-token'
    class Rest:
        credentials=Creds()
        def __init__(self):self.applied=False;self.calls=[];self.nonempty=True
        def call(self,url,**kw):
            from urllib.parse import urlsplit,parse_qs
            self.calls.append((url,kw));params=parse_qs(urlsplit(url).query)
            fields=params.get('fields',[''])[0];assert fields.count('(')==fields.count(')')
            if kw.get('method')=='POST':
                request=loads(kw['body'],524288)
                assert len([x for x in request['requests'] if 'addSheet' in x])==4
                assert all(not x.get('deleteSheet') for x in request['requests'])
                self.applied=True;return {'spreadsheetId':'synthetic-id'}
            if not self.applied:
                values=[{'userEnteredValue':{'stringValue':'existing user data'}}] if self.nonempty else []
                return {'spreadsheetId':'synthetic-id','sheets':[{'properties':{'sheetId':0,'title':'Sheet1','gridProperties':{'rowCount':1000,'columnCount':26}},'data':[{'rowData':[{'values':values}]}]}]}
            if 'ranges' not in params:
                return {'spreadsheetId':'synthetic-id','sheets':[{'properties':{'sheetId':sid,'title':name,'gridProperties':{'rowCount':1000,'columnCount':40}}} for name,sid in config['sheet_ids'].items()]}
            sheets=[]
            for range_ in params['ranges']:
                name=range_.split("'!")[0][1:];row=1 if range_.split("'!")[1].startswith('A1:') else 2
                values=[safe_cell(h) for h in HEADERS[name]] if row==1 else []
                sheets.append({'properties':{'sheetId':config['sheet_ids'][name]},'data':[{'startRow':row-1,'startColumn':0,'rowData':[{'values':values}]}]})
            return {'spreadsheetId':'synthetic-id','sheets':sheets}
    rest=Rest();transport=Sheets(rest,config['spreadsheet_id'],config['sheet_ids']);pub=Publisher(e,transport,q,config);bootstrap=LayoutProvisioner(pub)
    try:
        with pytest.raises(CRMError) as err:bootstrap.run()
        assert err.value.code=='BOOTSTRAP_NONEMPTY_RESOURCE';assert not rest.applied
        rest.nonempty=False;result=bootstrap.run();assert result['state']=='PROVISIONED_AND_ACTIVATED'
        assert bootstrap.run()['reconciled']
        assert len([x for x in rest.calls if x[1].get('method')=='POST'])==1
    finally:q.close()

def test_read_watermark_stays_with_selected_snapshot(core,monkeypatch):
    from crm.service import Broker
    from tests.test_crm_core import create,patch
    e,a=core;eid=create(e,a);broker=Broker(e,cursor_key=b'x'*32);original=broker.result
    def advancing(*args,**kwargs):
        patch(e,a,eid,note='committed after selection')
        return original(*args,**kwargs)
    monkeypatch.setattr(broker,'result',advancing)
    result,code=broker.list(a,{})
    assert code==0 and result['as_of_commit_seq']=='1'
    assert e.state()['commit_seq']==2 and result['data'][0]['note'] is None


def test_private_runtime_cannot_be_in_repository(tmp_path):
    from crm.storage import check_root
    (tmp_path/'.git').mkdir()
    with pytest.raises(CRMError) as err:check_root(tmp_path/'runtime')
    assert err.value.code=='DATA_INSIDE_REPOSITORY'

def test_banded_levenshtein_matches_reference():
    from crm.search import distance
    import random
    rng=random.Random(512)
    for _ in range(200):
        a=''.join(rng.choices('abcde',k=rng.randrange(0,12)));b=''.join(rng.choices('abcde',k=rng.randrange(0,12)))
        full=distance(a,b)
        for cutoff in (1,2):assert distance(a,b,cutoff)==min(full,cutoff+1)


def test_query_budget_does_not_poison_next_write(core):
    from tests.test_crm_core import create,patch
    from crm.search import search
    e,a=core;eid=create(e,a)
    with e.db.read() as c:
        tenant=c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0]
        with pytest.raises(CRMError) as err:search(c,tenant,'Lovelace',budget_ms=0)
        assert err.value.code=='QUERY_BUDGET'
    assert patch(e,a,eid,note='progress hook removed')['disposition']=='COMMITTED'

def test_blank_canonical_cell_is_captured_not_ignored(cloud):
    from tests.test_crm_core import create
    e,a,p,t,q,clock=cloud;eid=create(e,a);p.run(a,'push');clock.advance(61)
    with e.db.read() as c:row=c.execute('SELECT sheet_id,row_index FROM projection_rows WHERE entity_id=?',(eid,)).fetchone()
    t.cells[(row[0],row[1],2)]={}
    result=p.pull(a)
    assert result['captured']==1
    with e.db.read() as c:
        item=c.execute("SELECT reason_code FROM quarantine_proposals WHERE target_field='display_name'").fetchone()
        assert item[0]=='DIRECT_CANONICAL_EDIT'


def test_idle_pipeline_drift_is_captured(cloud):
    from tests.test_crm_core import create
    from crm.codec import safe_cell
    e,a,p,t,q,clock=cloud;eid=create(e,a,'project','Current Project',{'slug':'current-project'});p.run(a,'push');clock.advance(61)
    with e.db.read() as c:row=c.execute('SELECT sheet_id,row_index FROM projection_rows WHERE entity_id=?',(eid,)).fetchone()
    t.cells[(row[0],row[1],2)]=safe_cell('untrusted remote replacement')
    assert p.pull(a)['captured']==1
    with e.db.read() as c:assert c.execute('SELECT display_name FROM entities WHERE entity_id=?',(eid,)).fetchone()[0]=='Current Project'

def test_shared_exact_domain_remains_multiple_candidates(core):
    from tests.test_crm_core import create,sq
    e,a=core;ids=[create(e,a,name='Contact A'),create(e,a,name='Contact B')]
    for eid in ids:
        result=e.ingest(e.packet('patron.channel.set',{'patron_id':eid,'channel_id':new_id(),'channel_kind':'domain','original_value':'Example.COM.','retire':False}),a)
        assert result['disposition']=='COMMITTED'
    result=sq(e,'domain:example.com')
    assert {r['entity_id'] for r in result['matches']}==set(ids)
    assert result['identity_merge_permitted'] is False


def test_email_local_part_not_silently_casefolded(core):
    from tests.test_crm_core import create,sq
    e,a=core;eid=create(e,a)
    e.ingest(e.packet('patron.channel.set',{'patron_id':eid,'channel_id':new_id(),'channel_kind':'email','original_value':'Ada+Lab@Example.COM','retire':False}),a)
    assert sq(e,'email:Ada+Lab@example.com')['matches'][0]['entity_id']==eid
    assert not sq(e,'email:ada+lab@example.com')['matches']


def test_production_quota_clock_ignores_wall_jump(core,tmp_path,monkeypatch):
    import crm.quota as module
    wall=[10000.0];mono=[50.0]
    monkeypatch.setattr(module.time,'time',lambda:wall[0])
    monkeypatch.setattr(module.time,'monotonic',lambda:mono[0])
    scheduler=module.Scheduler(tmp_path/'quota-monotonic','project','principal')
    try:
        scheduler.reserve('sheets_write');wall[0]+=3600
        with pytest.raises(module.QuotaHold):scheduler.reserve('sheets_write')
        mono[0]+=16
        scheduler.reserve('sheets_write')
    finally:scheduler.close()
