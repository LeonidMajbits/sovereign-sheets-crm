"""Core behavioral integration suite. Every mutation uses the real frozen DDL."""
import copy,json,sqlite3,threading,concurrent.futures,hashlib,os
import pytest
from crm.codec import loads,jcs,digest,integer,literal_cell,safe_cell,escape_display
from crm.errors import CRMError,Conflict
from crm.ids import new_id,durable_id
from crm.engine import ActorContext
from crm.db import Database
from crm.search import search,compile_query
from crm.quarantine import capture,list_proposals
from crm.service import Broker
from crm.google_api import Ambiguous,NotApplied
from crm.quota import QuotaHold,Scheduler
from tests.fakes import Clock


def create(e,a,kind='person',name='Ada Lovelace',facet=None):
    eid=new_id();p=e.packet('entity.create',{'entity_id':eid,'entity_kind':kind,'display_name':name,'facet':facet or {}},base=None if kind in ('person','organization','campaign','project','thread') and not (facet or {}).get('lead_actor_id') and not (facet or {}).get('organization_id') else 'current')
    result=e.ingest(p,a);assert result['disposition']=='COMMITTED',result
    return eid

def patch(e,a,eid,**changes):return e.ingest(e.packet('entity.patch',{'entity_id':eid,'changes':changes}),a)
def get(e,eid):
    with e.db.read() as c:return dict(c.execute('SELECT * FROM entities WHERE entity_id=?',(eid,)).fetchone())
def sq(e,q,scope='entities',**kwargs):
    with e.db.read() as c:return search(c,e.state()['tenant_id'] if False else c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0],q,scope=scope,**kwargs)
def record_artifact(e,a,tmp_path,body=b'approved fixture'):
    path=tmp_path/new_id();path.write_bytes(body);ref='fixture:'+new_id();e.artifact_registry[ref]=path
    aid=new_id();p=e.packet('artifact.register',{'artifact_id':aid,'media_type':'text/plain','size_bytes':str(len(body)),'sha256':hashlib.sha256(body).hexdigest(),'object_ref':ref,'object_version':'1','visibility':'local_only'})
    assert e.ingest(p,a)['disposition']=='COMMITTED';return aid

def worktree(e,a):
    project=create(e,a,'project','Research',{'slug':'research-'+new_id().lower()})
    stage=create(e,a,'stage','Stage One',{'project_id':project,'plan_version':'1','stage_ordinal':'1','required':True})
    ticket=create(e,a,'ticket','Task',{'project_id':project,'plan_version':'1','parent_work_item_id':stage})
    dispatch=create(e,a,'dispatch','Attempt',{'work_item_id':ticket,'actor_id':a.actor_id,'attempt_no':'1','prompt_hash':'a'*64,'target_app':'ChatGPT','connector_account_id':'fixture'})
    return project,stage,ticket,dispatch


def test_ddl_loaded(core):
    e,a=core
    with e.db.read() as c:
        assert c.execute('PRAGMA foreign_keys').fetchone()[0]==1
        assert c.execute('PRAGMA synchronous').fetchone()[0]==2
        assert c.execute('PRAGMA trusted_schema').fetchone()[0]==0
        assert c.execute('PRAGMA journal_mode').fetchone()[0]=='wal'
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('entity_fts','interaction_fts')").fetchone()[0]==2


def test_production_floor_fails_before_files(tmp_path,monkeypatch):
    import crm.db as d
    monkeypatch.setattr(d.sqlite3,'sqlite_version_info',(3,46,1));monkeypatch.setattr(d,'MIN_SQLITE',(3,51,3))
    root=tmp_path/'must-not-exist'
    with pytest.raises(CRMError,match='require'):Database.initialize(root,new_id(),new_id(),new_id())
    assert not root.exists()


def test_second_authority_rejected(core):
    e,a=core
    with pytest.raises(CRMError) as err:Database(e.db.root)
    assert err.value.code=='AUTHORITY_ALREADY_RUNNING'


def test_initialization_never_overwrites(core):
    e,a=core
    with pytest.raises(FileExistsError):Database.initialize(e.db.root,new_id(),new_id(),new_id())


def test_create_version_search_outbox_atomic(core):
    e,a=core;eid=create(e,a)
    assert get(e,eid)['entity_rev']==1
    with e.db.read() as c:
        assert c.execute('SELECT count(*) FROM entity_versions').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM sync_outbox').fetchone()[0]==1
    assert sq(e,'Lovelace')['matches'][0]['entity_id']==eid
    assert e.verify_audit()['transactions']=='1'


def test_patch_retains_history(core):
    e,a=core;eid=create(e,a);patch(e,a,eid,note='New approved note')
    assert get(e,eid)['entity_rev']==2
    with e.db.read() as c:assert c.execute('SELECT count(*) FROM entity_versions WHERE entity_id=?',(eid,)).fetchone()[0]==2


def test_idempotency_before_stale_base(core):
    e,a=core;eid=create(e,a);p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'first'}})
    r=e.ingest(p,a);patch(e,a,eid,note='second')
    assert e.ingest(p,a)==r;assert get(e,eid)['entity_rev']==3


def test_same_operation_changed_payload(core):
    e,a=core;eid=create(e,a);p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'first'}});e.ingest(p,a)
    p['payload']['changes']['note']='malicious alternate'
    with pytest.raises(CRMError) as exc:e.ingest(p,a)
    assert exc.value.code=='OPERATION_ID_REUSED'


def test_disjoint_patch_merge(core):
    e,a=core;eid=create(e,a);b=e.base();p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'note'}},base=b)
    patch(e,a,eid,next_action='call');assert e.ingest(p,a)['disposition']=='COMMITTED'
    assert get(e,eid)['next_action']=='call';assert get(e,eid)['note']=='note'


def test_same_field_conflict(core):
    e,a=core;eid=create(e,a);p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'offline'}})
    patch(e,a,eid,note='local');result=e.ingest(p,a)
    assert result['disposition']=='CONFLICT';assert get(e,eid)['note']=='local'
    with e.db.read() as c:assert c.execute('SELECT count(*) FROM quarantine_proposals').fetchone()[0]==1


def test_aba_conflict(core):
    e,a=core;eid=create(e,a);p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'stale'}})
    patch(e,a,eid,note='intermediate');patch(e,a,eid,note=None)
    assert e.ingest(p,a)['disposition']=='CONFLICT'


def test_nochange_no_fake_revision(core):
    e,a=core;eid=create(e,a);r=patch(e,a,eid,display_name='Ada Lovelace')
    assert r['disposition']=='SATISFIED_NO_CHANGE';assert get(e,eid)['entity_rev']==1
    assert e.state()['commit_seq']==2


@pytest.mark.parametrize('failure',['after_domain','after_search','before_outbox','before_commit'])
def test_injected_failure_rolls_back_all(core,failure):
    e,a=core;eid=create(e,a);before=e.state()['commit_seq']
    def fault(point):
        if point==failure:raise RuntimeError('deliberate test fault')
    e.fault=fault
    with pytest.raises(RuntimeError):patch(e,a,eid,note='MUSTNOTCOMMIT')
    e.fault=lambda _:None
    assert e.state()['commit_seq']==before;assert get(e,eid)['note'] is None;assert not sq(e,'MUSTNOTCOMMIT')['matches'];e.verify_audit()


def test_immutable_history_guard(core):
    e,a=core;create(e,a)
    with pytest.raises(sqlite3.IntegrityError):
        with e.db.transaction() as c:c.execute('DELETE FROM audit_log')


def test_hard_delete_guard(core):
    e,a=core;eid=create(e,a)
    with pytest.raises(sqlite3.IntegrityError):
        with e.db.transaction() as c:c.execute('DELETE FROM entities WHERE entity_id=?',(eid,))


def test_tombstone_removes_search(core):
    e,a=core;eid=create(e,a)
    assert e.ingest(e.packet('entity.tombstone',{'entity_id':eid,'reason':'closed duplicate'}),a)['disposition']=='COMMITTED'
    assert not sq(e,'Lovelace')['matches'];assert get(e,eid)['deleted_at']


def test_tombstone_no_resurrection(core):
    e,a=core;eid=create(e,a);p=e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'old'}})
    e.ingest(e.packet('entity.tombstone',{'entity_id':eid,'reason':'retire'}),a)
    assert e.ingest(p,a)['disposition']=='CONFLICT'


def test_tenant_mismatch(core):
    e,a=core;p=e.packet('entity.create',{'entity_id':new_id(),'entity_kind':'person','display_name':'X','facet':{}},base=None);p['tenant_id']=new_id()
    with pytest.raises(CRMError) as exc:e.ingest(p,a)
    assert exc.value.exit_code==4;assert e.state()['commit_seq']==0


def test_capability_cannot_come_from_packet(core):
    e,a=core;eid=create(e,a);weak=ActorContext(a.actor_id,frozenset({'read'}))
    with pytest.raises(CRMError):e.ingest(e.packet('entity.patch',{'entity_id':eid,'changes':{'note':'no'}}),weak)
    assert get(e,eid)['note'] is None


@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":1.2}',b'{"x":9007199254740992}',b'\xef\xbb\xbf{}',b'{"x":"\\ud800"}',b'{}junk'])
def test_strict_json_rejects(raw):
    with pytest.raises(CRMError):loads(raw)


def test_jcs_utf16_order():
    assert jcs({'\U0001f600':1,'\ue000':2}).decode()=='{"😀":1,"\ue000":2}'


@pytest.mark.parametrize('value',['=IMAGE("https://invalid.example")','@SUM(A1)','+1+2','-1+2','  =NOW()'])
def test_outbound_formula_tokens_inert(value):
    cell=safe_cell(value)
    assert cell['userEnteredValue']=={'stringValue':value};assert 'formulaValue' not in cell['userEnteredValue']
    assert escape_display(value).startswith("'")


def test_phone_plus_not_globally_stripped():
    value='+1 416 555 0100';assert safe_cell(value)['userEnteredValue']['stringValue']==value


@pytest.mark.parametrize('cell',[{'userEnteredValue':{'formulaValue':'=1+1'},'effectiveValue':{'stringValue':'innocent'}},{'effectiveValue':{'stringValue':'innocent'}},{'userEnteredValue':{'numberValue':1}},{'userEnteredValue':{'stringValue':'=1'}},{'userEnteredValue':{'stringValue':'x'},'chipRuns':[]}])
def test_typed_cells_rejected(cell):
    with pytest.raises(CRMError):literal_cell(cell)


def test_alias_search_and_get(core):
    e,a=core;eid=create(e,a);e.ingest(e.packet('entity.alias.set',{'alias_id':new_id(),'entity_id':eid,'original_value':'Countess Ada','retire':False}),a)
    assert sq(e,'Countess Ada')['matches'][0]['entity_id']==eid
    b=Broker(e,cursor_key=b'k'*32);r,code=b.handle(a,'get',{'id':'countess ada'});assert code==0;assert r['data']['entity']['entity_id']==eid


def test_tag_search(core):
    e,a=core;eid=create(e,a);r=e.ingest(e.packet('entity.tag.set',{'entity_id':eid,'tag':'research-patron','present':True}),a)
    assert r['disposition']=='COMMITTED';assert sq(e,'research patron')['matches']


@pytest.mark.parametrize('name,query',[('Наталья Исследователь','Наталья'),('לאון מחקר','מחקר'),('Renée Curie','Renee')])
def test_multilingual_search(core,name,query):
    e,a=core;eid=create(e,a,name=name);assert sq(e,query)['matches'][0]['entity_id']==eid


def test_fts_grammar_cannot_inject(core):
    e,a=core;create(e,a);assert compile_query('x OR tenant_id:evil')=='"x" AND "OR" AND "tenant" AND "id" AND "evil"'
    assert not sq(e,'x OR tenant_id:evil')['matches']


def test_org_rename_refreshes_dependents(core):
    e,a=core;org=create(e,a,'organization','OldOrg');person=create(e,a,facet={'organization_id':org});patch(e,a,org,display_name='NewOrg')
    ids={r['entity_id'] for r in sq(e,'NewOrg')['matches']};assert org in ids and person in ids;assert not sq(e,'OldOrg')['matches']


def test_interaction_does_not_revise_patron(core):
    e,a=core;eid=create(e,a);before=get(e,eid)['entity_rev'];iid=new_id()
    r=e.ingest(e.packet('interaction.append',{'interaction_id':iid,'patron_id':eid,'subject':'Discovery call','occurred_at':'2026-09-20T12:00:00.000Z'}),a)
    assert r['disposition']=='COMMITTED';assert get(e,eid)['entity_rev']==before;assert sq(e,'Discovery',scope='interactions')['matches'][0]['interaction_id']==iid


def test_interaction_supersession(core):
    e,a=core;eid=create(e,a);iid=new_id()
    e.ingest(e.packet('interaction.append',{'interaction_id':iid,'patron_id':eid,'subject':'Obsolete','occurred_at':'2026-09-20T12:00:00.000Z'}),a)
    e.ingest(e.packet('interaction.supersede',{'interaction_id':new_id(),'patron_id':eid,'supersedes_interaction_id':iid,'record_kind':'correction','subject':'Corrected','occurred_at':'2026-09-20T12:00:00.000Z'}),a)
    assert not sq(e,'Obsolete',scope='interactions')['matches'];assert sq(e,'Corrected',scope='interactions')['matches']


def test_campaign_membership_filter(core):
    e,a=core;cid=create(e,a,'campaign','Mission',{'slug':'mission'});eid=create(e,a)
    assert e.ingest(e.packet('campaign.membership.set',{'campaign_id':cid,'entity_id':eid,'present':True,'is_primary':True}),a)['disposition']=='COMMITTED'
    r,code=Broker(e,cursor_key=b'c'*32).handle(a,'list',{'campaign':cid});assert code==0;assert len(r['data'])==1


def test_plan_selection_and_progress_guard(core):
    e,a=core;project,stage,ticket,dispatch=worktree(e,a)
    assert e.ingest(e.packet('project.plan.select',{'project_id':project,'plan_version':'1'}),a)['disposition']=='COMMITTED'
    assert e.ingest(e.packet('entity.transition',{'entity_id':project,'to_status':'completed'}),a)['disposition']=='CONFLICT'


def test_two_simultaneous_claims_one_winner(core):
    e,a=core;*_,dispatch=worktree(e,a);base=e.base()
    packets=[e.packet('claim.acquire',{'resource_id':dispatch},base=base) for _ in range(2)]
    barrier=threading.Barrier(2)
    def run(p):barrier.wait();return e.ingest(p,a)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(run,packets))
    assert sorted(r['disposition'] for r in results)==['COMMITTED','CONFLICT']
    with e.db.read() as c:assert c.execute('SELECT claim_generation FROM claims WHERE resource_id=?',(dispatch,)).fetchone()[0]==1


def test_old_claim_token_rejected(core):
    e,a=core;*_,dispatch=worktree(e,a)
    token=e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)['data']['claim_token']
    e.ingest(e.packet('claim.release',{'resource_id':dispatch,'claim_token':token,'reason':'done'}),a)
    new=e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)['data']['claim_token']
    assert new['claim_generation']=='2'
    assert e.ingest(e.packet('claim.release',{'resource_id':dispatch,'claim_token':token,'reason':'late'}),a)['disposition']=='CONFLICT'


def test_claim_retry_same_generation(core):
    e,a=core;*_,dispatch=worktree(e,a);p=e.packet('claim.acquire',{'resource_id':dispatch});r=e.ingest(p,a);assert e.ingest(p,a)==r


def test_unknown_dispatch_cannot_be_blindly_reclaimed(core):
    e,a=core;*_,dispatch=worktree(e,a);token=e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)['data']['claim_token']
    e.ingest(e.packet('entity.transition',{'entity_id':dispatch,'to_status':'cooking','claim_token':token}),a)
    e.ingest(e.packet('entity.transition',{'entity_id':dispatch,'to_status':'unknown','claim_token':token}),a)
    assert e.ingest(e.packet('claim.acquire',{'resource_id':dispatch}),a)['disposition']=='CONFLICT'


def observation(e,a,eid,value,field='human_note'):
    return capture(e,a,resource='test',generation=new_id(),sheet=101,row=2,column=28,entity=eid,field=field,cell={'userEnteredValue':{'stringValue':value}})


def test_quarantine_no_search_contamination(core):
    e,a=core;eid=create(e,a);out=observation(e,a,eid,'=DANGEROUSNEVERINDEX')
    assert get(e,eid)['note'] is None;assert not sq(e,'DANGEROUSNEVERINDEX')['matches']
    with e.db.read() as c:
        raw=b''.join(bytes(r[0]) for r in c.execute('SELECT event_jcs FROM audit_log'))
        assert b'DANGEROUSNEVERINDEX' not in raw
        assert c.execute('SELECT evidence_object_ref FROM quarantine_proposals').fetchone()[0]


def test_observation_adoption_explicit(core):
    e,a=core;eid=create(e,a);out=observation(e,a,eid,'Approved after review')
    data=out['data'];packet=e.packet('observation.resolve',{'proposal_id':data['proposal_id'],'selection_revision':data['selection_revision'],'decision':'ADOPT','reason':'reviewed'})
    assert e.ingest(packet,a)['disposition']=='COMMITTED';assert get(e,eid)['note']=='Approved after review'


def test_formula_cannot_be_adopted(core):
    e,a=core;eid=create(e,a);out=observation(e,a,eid,'=NOPE');p=e.packet('observation.resolve',{'proposal_id':out['data']['proposal_id'],'selection_revision':out['data']['selection_revision'],'decision':'ADOPT','reason':'attempt'})
    assert e.ingest(p,a)['disposition']=='CONFLICT'


def test_observation_a_b_a_not_digest_deduplicated(core):
    e,a=core;eid=create(e,a);gen=new_id();params=dict(resource='test',generation=gen,sheet=101,row=2,column=28,entity=eid,field='human_note')
    vals=[]
    for value in ('first','second','first'):
        vals.append(capture(e,a,**params,cell={'userEnteredValue':{'stringValue':value}})['data']['proposal_id'])
    assert len(set(vals))==3


def test_repeated_observation_no_echo(core):
    e,a=core;eid=create(e,a);params=dict(resource='test',generation=new_id(),sheet=101,row=2,column=28,entity=eid,field='human_note',cell={'userEnteredValue':{'stringValue':'draft'}})
    capture(e,a,**params);seq=e.state()['commit_seq'];r=capture(e,a,**params)
    assert r['duplicate'];assert e.state()['commit_seq']==seq


def test_proposal_cli_resolution_is_idempotent(core):
    e,a=core;eid=create(e,a);out=observation(e,a,eid,'reviewed');b=Broker(e,cursor_key=b'p'*32);args={'id':out['data']['proposal_id'],'accept':True,'reject':False}
    r,code=b.handle(a,'proposals.resolve',args);assert code==0
    seq=e.state()['commit_seq'];r2,code=b.handle(a,'proposals.resolve',args);assert code==0;assert e.state()['commit_seq']==seq


def test_cursor_rejects_changed_snapshot(core):
    e,a=core
    for n in range(3):create(e,a,name='Person '+str(n))
    b=Broker(e,cursor_key=b'k'*32);r,code=b.handle(a,'list',{'limit':1});assert code==0;assert r['next_cursor']
    create(e,a,name='New person');r2,code=b.handle(a,'list',{'limit':1,'cursor':r['next_cursor']});assert code==5;assert r2['error']['code']=='CURSOR_STALE'


def test_sync_dry_run_no_side_effects(cloud):
    e,a,p,t,q,clock=cloud;create(e,a)
    before=e.db.path.read_bytes();wal=(e.db.root/'crm.db-wal').read_bytes();calls=t.read_calls
    r=p.run(a,'dry-run');assert r['network_used'] is False;assert t.read_calls==calls
    assert e.db.path.read_bytes()==before;assert (e.db.root/'crm.db-wal').read_bytes()==wal


def test_publication_complete_readback(cloud):
    e,a,p,t,q,clock=cloud;eid=create(e,a);r=p.run(a,'push');assert r['state']=='VERIFIED'
    with e.db.read() as c:assert c.execute('SELECT state FROM sync_outbox').fetchone()[0]=='VERIFIED'
    assert len(t.writes)==1;e.verify_audit()


def test_human_columns_never_overwritten(cloud):
    e,a,p,t,q,clock=cloud;eid=create(e,a);p.run(a,'push');sid=p.config['sheet_ids']['Directory'];t.cells[(sid,2,28)]=safe_cell('UNBASED DRAFT')
    patch(e,a,eid,note='accepted');clock.advance();p.run(a,'push')
    assert t.cells[(sid,2,28)]['userEnteredValue']['stringValue']=='UNBASED DRAFT'


def test_timeout_after_apply_reconciles_without_resend(cloud):
    e,a,p,t,q,clock=cloud;create(e,a);t.fail='timeout_after'
    with pytest.raises(Ambiguous):p.run(a,'push')
    assert len(t.writes)==1;t.fail=None;clock.advance()
    assert p.run(a,'push')['state']=='VERIFIED';assert len(t.writes)==1


def test_timeout_before_apply_holds_no_resend(cloud):
    e,a,p,t,q,clock=cloud;create(e,a);t.fail='timeout_before'
    with pytest.raises(Ambiguous):p.run(a,'push')
    t.fail=None;clock.advance()
    with pytest.raises(Ambiguous):p.run(a,'push')
    assert len(t.writes)==1


def test_429_retains_outbox_and_shared_cooldown(cloud):
    e,a,p,t,q,clock=cloud;create(e,a);t.fail='429'
    with pytest.raises(NotApplied):p.run(a,'push')
    with e.db.read() as c:assert c.execute('SELECT state FROM sync_outbox').fetchone()[0]=='ASSIGNED'
    t.fail=None
    with pytest.raises(QuotaHold):p.run(a,'push')
    clock.advance(61);assert p.run(a,'push')['state']=='VERIFIED'


def test_batch_50_row_bound(cloud):
    e,a,p,t,q,clock=cloud
    for i in range(53):create(e,a,name='Entity '+str(i))
    p.run(a,'push')
    with e.db.read() as c:
        assert c.execute('SELECT max(business_rows) FROM publication_batches').fetchone()[0]<=50
        assert c.execute("SELECT count(*) FROM sync_outbox WHERE state!='VERIFIED'").fetchone()[0]>0
    clock.advance(61);p.run(a,'push')
    with e.db.read() as c:assert c.execute("SELECT count(*) FROM sync_outbox WHERE state!='VERIFIED'").fetchone()[0]==0


def test_old_batch_does_not_publish_future_state(cloud):
    e,a,p,t,q,clock=cloud;eid=create(e,a);meta=p.validate_layout();batch=p.prepare(meta)
    patch(e,a,eid,note='FUTURE NOTE');p.run(a,'push')
    assert t.cells[(101,2,11)]['userEnteredValue']['stringValue']==''
    clock.advance(61);p.run(a,'push');assert t.cells[(101,2,11)]['userEnteredValue']['stringValue']=='FUTURE NOTE'


def test_archive_move_counts_two_physical_rows(cloud):
    e,a,p,t,q,clock=cloud;eid=create(e,a,'project','Project',{'slug':'p'});p.run(a,'push')
    e.ingest(e.packet('entity.transition',{'entity_id':eid,'to_status':'shelved'}),a);clock.advance(61);p.run(a,'push')
    with e.db.read() as c:assert c.execute('SELECT business_rows FROM publication_batches ORDER BY first_commit_seq DESC LIMIT 1').fetchone()[0]==2
    assert t.cells[(102,2,0)]['userEnteredValue']['stringValue']=='';assert t.cells[(103,2,0)]['userEnteredValue']['stringValue']==eid


def test_quota_shared_across_tenants(tmp_path,monkeypatch):
    import crm.db as d;monkeypatch.setattr(d,'MIN_SQLITE',(3,0,0));clock=Clock();q=Scheduler(tmp_path/'quota','p','u',clock=clock,pace=0)
    for _ in range(30):q.reserve('sheets_read')
    with pytest.raises(QuotaHold):q.reserve('sheets_read')
    clock.advance(61);q.reserve('sheets_read');q.close()


def test_expired_quota_restart_does_not_reset_allowance(tmp_path,monkeypatch):
    import crm.db as d;monkeypatch.setattr(d,'MIN_SQLITE',(3,0,0));clock=Clock();root=tmp_path/'q';q=Scheduler(root,'p','u',clock=clock);q.reserve('sheets_write');q.close()
    r=Scheduler(root,'p','u',clock=clock)
    with pytest.raises(QuotaHold):r.reserve('sheets_write')
    clock.advance(61);r.reserve('sheets_write');r.close()


def test_backup_is_consistent(core,tmp_path):
    e,a=core;create(e,a);dest=tmp_path/'backup.sqlite3';e.db.backup(dest)
    c=sqlite3.connect(dest);assert c.execute('SELECT count(*) FROM entities').fetchone()[0]==1;assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';c.close()

def test_500_logical_agents_deduplicate_and_drain_bounded_batches(cloud,record_property):
    e,operator,p,t,q,clock=cloud
    from crm.engine import ALL_CAPS
    actors=[];packets=[]
    with e.db.transaction() as c:
        tenant=c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0]
        for i in range(500):
            aid=new_id();c.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(tenant,aid,f'Synthetic producer {i}','agent'))
            actors.append(ActorContext(aid,ALL_CAPS))
    for i in range(500):packets.append(e.packet('entity.create',{'entity_id':new_id(),'entity_kind':'person','display_name':f'Synthetic wave {i}','facet':{}},base=None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        results=list(pool.map(lambda pair:e.ingest(*pair),zip(packets,actors)))
    assert all(r['disposition']=='COMMITTED' for r in results)
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        repeats=list(pool.map(lambda pair:e.ingest(*pair),zip(packets,actors)))
    assert results==repeats and e.state()['commit_seq']==500
    for _ in range(20):
        if p.plan()['pending_transactions']=='0':break
        clock.advance(61)  # deterministic quota clock, NOT a wall-time throughput claim
        p.run(operator,'push')
    assert p.plan()['pending_transactions']=='0' and 10<=len(t.writes)<=20
    with e.db.read() as c:
        assert c.execute('SELECT count(*) FROM operation_outcomes').fetchone()[0]==500
        assert c.execute('SELECT max(business_rows) FROM publication_batches').fetchone()[0]<=50
        assert c.execute('SELECT max(payload_bytes) FROM publication_batches').fetchone()[0]<=524288
    assert e.verify_audit()['transactions']=='500'
    record_property('logical_agents',500);record_property('worker_threads',32);record_property('fake_provider_batches',len(t.writes));record_property('clock','simulated')


def test_crm01_cooldown_monotonic_and_not_cleared_by_late_success(tmp_path):
    root = tmp_path / 'quota'
    now = [1000.0]
    q = Scheduler(root, 'proj', 'princ', clock=lambda: now[0], pace=0, jitter=lambda: 0.0)
    try:
        q.reserve('sheets_read') # Request A
        q.reserve('sheets_read') # Request B
        until = q.rejected('sheets_read', retry_after=60)
        with pytest.raises(QuotaHold) as exc:
            q.reserve('sheets_read')
        assert exc.value.until == until
        # Late arrival of older success must not clear active hold
        q.succeeded('sheets_read')
        with pytest.raises(QuotaHold) as exc:
            q.reserve('sheets_read')
        assert exc.value.until == until
        # Advance past deadline: reservation now succeeds
        now[0] = until + 0.1
        q.reserve('sheets_read')
    finally:
        q.close()


def test_crm01_subsequent_shorter_rejection_cannot_shorten_cooldown(tmp_path):
    root = tmp_path / 'quota'
    now = [1000.0]
    q = Scheduler(root, 'proj', 'princ', clock=lambda: now[0], pace=0, jitter=lambda: 0.0)
    try:
        long_until = q.rejected('sheets_read', retry_after=120)
        short_until = q.rejected('sheets_read', retry_after=1)
        assert short_until >= long_until
        with pytest.raises(QuotaHold) as exc:
            q.reserve('sheets_read')
        assert exc.value.until == long_until
    finally:
        q.close()


def test_crm01b_failure_generation_preserved_when_late_success_arrives_under_hold(tmp_path):
    root = tmp_path / 'quota'
    now = [1000.0]
    q = Scheduler(root, 'proj', 'princ', clock=lambda: now[0], pace=0, jitter=lambda: 0.0)
    try:
        q.rejected('sheets_read', retry_after=10)
        q.rejected('sheets_read', retry_after=20)
        until = q.rejected('sheets_read', retry_after=60)
        row = q.c.execute('SELECT failures, not_before FROM domains WHERE project=? AND principal=? AND kind=?', ('proj', 'princ', 'sheets_read')).fetchone()
        assert row[0] == 3
        assert row[1] == until

        # CRM-01b: Late success arriving while hold is active (now < until) must PRESERVE failures count
        q.succeeded('sheets_read')
        row_after = q.c.execute('SELECT failures, not_before FROM domains WHERE project=? AND principal=? AND kind=?', ('proj', 'princ', 'sheets_read')).fetchone()
        assert row_after[0] == 3, f"Expected failures to remain 3 under active hold, got {row_after[0]}"
        assert row_after[1] == until

        # After deadline expires, a legitimate post-hold success clears failures back to 0
        now[0] = until + 0.1
        q.succeeded('sheets_read')
        row_cleared = q.c.execute('SELECT failures, not_before FROM domains WHERE project=? AND principal=? AND kind=?', ('proj', 'princ', 'sheets_read')).fetchone()
        assert row_cleared[0] == 0
        assert row_cleared[1] == 0.0
    finally:
        q.close()


def test_crm_limit01_lamport_exhaustion_boundary(core):
    e, actor = core
    from crm.codec import MAX_I64
    eid = new_id()
    r = e.ingest(e.packet('entity.create', {'entity_id': eid, 'entity_kind': 'person', 'display_name': 'test', 'facet': {}}, base=None), actor)
    assert r['disposition'] == 'COMMITTED'
    # Near-maximum clock
    high = e.ingest(e.packet('entity.lww.set', {'entity_id': eid, 'field': 'note', 'value': 'high', 'logical_clock': str(MAX_I64 - 1)}), actor)
    assert high['disposition'] == 'COMMITTED'
    # Fail-closed exhaustion on subsequent lower clock
    with pytest.raises(CRMError) as exc:
        e.ingest(e.packet('entity.lww.set', {'entity_id': eid, 'field': 'note', 'value': 'low', 'logical_clock': '1'}), actor)
    assert exc.value.code == 'LAMPORT_EXHAUSTED'
