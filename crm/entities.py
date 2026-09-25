"""Typed mutation handlers. No generic facet upsert, force switch or implicit merge."""
from __future__ import annotations
import hashlib, re
from pathlib import Path
from datetime import datetime,timezone,timedelta
from .codec import integer,text,timestamp,normalize_name,loads,digest,MAX_I64
from .errors import CRMError,Conflict,Unsupported
from .model import FACETS,INITIAL,GRAPHS,TERMINAL

INT_COLUMNS={'plan_version','stage_ordinal','attempt_no','active_plan_version','amount_minor'}
TEXT_CAPS={'slug':128,'objective':2048,'lead_model':128,'acceptance_ref':2048,'funding_band':128,'external_thread_id':512,'connector_account_id':256,'target_app':80}


def _actor_ref(w,aid):
    if aid is not None:
        if w.base is None:raise Conflict('BASE_REQUIRED')
        w.actor_exists(aid)


def create(w,p):
    eid,kind=p['entity_id'],p['entity_kind']
    if w.c.execute('SELECT 1 FROM entities WHERE tenant_id=? AND entity_id=?',(w.tenant,eid)).fetchone():raise Conflict('ENTITY_EXISTS')
    title=text(p['display_name'],1024)
    if not title.strip():raise CRMError('EMPTY_NAME')
    if title.lstrip().startswith('='):raise CRMError('FORMULA_LIKE_TITLE')
    f=dict(p['facet']); table,key=FACETS[kind]
    for k,v in tuple(f.items()):
        if k in INT_COLUMNS and v is not None:f[k]=integer(v,0 if k in ('active_plan_version','amount_minor') else 1)
        if k in TEXT_CAPS and v is not None:text(v,TEXT_CAPS[k])
        if k=='due_at' and v is not None:timestamp(v)
    if kind in ('campaign','project'):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,127}',f['slug']):raise CRMError('INVALID_SLUG')
        _actor_ref(w,f.get('lead_actor_id'))
    if kind=='person' and f.get('organization_id'):
        w.get(f['organization_id'],kind='organization');w.depend(f['organization_id']);w.guard(f['organization_id'],'children')
    if f.get('funding_currency') and f['funding_currency'] not in w.engine.currencies:raise CRMError('CURRENCY_NOT_ALLOWED')
    if kind in ('stage','ticket'):
        project=f['project_id']; w.get(project,kind='project');w.depend(project,('status',),('work_items',))
        if w.get(project)['status']!='active':raise Conflict('PROJECT_NOT_ACTIVE')
        _actor_ref(w,f.get('assigned_actor_id'))
        if f.get('parent_work_item_id'):
            parent=f['parent_work_item_id'];w.get(parent,kind='stage');w.depend(parent,('status',),('children',))
            pf=w.facet(parent)
            if pf['project_id']!=project or pf['plan_version']!=f['plan_version']:raise Conflict('PARENT_PLAN_MISMATCH')
            if w.get(parent)['status'] in TERMINAL['stage']:raise Conflict('TERMINAL_PARENT')
            w.guard(parent,'children')
        if 'required' in f:f['required']=int(f['required'])
        w.guard(project,'work_items')
    if kind in ('opportunity','contract'):
        for parent,typ in [(f['project_id'],'project'),(f['primary_patron_id'],('person','organization'))]:
            w.get(parent,kind=typ);w.depend(parent,('status',));w.guard(parent,'children')
        if f.get('amount_minor') is not None and not f.get('currency'):raise CRMError('CURRENCY_REQUIRED')
        if f.get('currency') and f['currency'] not in w.engine.currencies:raise CRMError('CURRENCY_NOT_ALLOWED')
        if f.get('origin_opportunity_id'):
            origin=f['origin_opportunity_id'];w.get(origin,kind='opportunity');w.depend(origin,('status',));of=w.facet(origin)
            if of['project_id']!=f['project_id'] or of['primary_patron_id']!=f['primary_patron_id']:raise Conflict('ORIGIN_MISMATCH')
            w.guard(origin,'children')
    if kind=='dispatch':
        wid=f['work_item_id'];w.get(wid,kind=('ticket','stage'));w.depend(wid,('status',),('dispatches',))
        if w.get(wid)['status'] in TERMINAL['ticket']:raise Conflict('TERMINAL_WORK_ITEM')
        _actor_ref(w,f['actor_id'])
        if f.get('thread_id'):
            tid=f['thread_id'];w.get(tid,kind='thread');w.depend(tid,('status',));tf=w.facet(tid)
            if (tf['target_app'],tf['connector_account_id'])!=(f['target_app'],f['connector_account_id']):raise Conflict('THREAD_ACCOUNT_MISMATCH')
            w.guard(tid,'children')
        w.guard(wid,'dispatches')
    row=dict(tenant_id=w.tenant,entity_id=eid,entity_kind=kind,display_name=title,status=INITIAL[kind],note=text(p.get('note'),2048,True),next_action=text(p.get('next_action'),1024,True),entity_rev=1,last_commit_seq=w.seq,mutation_epoch=w.epoch,state_digest='0'*64,created_at=w.now,updated_at=w.now,deleted_at=None,merged_into_id=None,updated_by=w.actor.actor_id)
    w.dirty[eid]=row;w.fields[eid]=set(row)|set(f);w.refresh.add(eid);w.changed=True
    w.insert(table,dict(tenant_id=w.tenant,**{key:eid},entity_kind=kind,**f))
    if kind=='dispatch':w.insert('claims',dict(tenant_id=w.tenant,resource_id=eid,claim_generation=0,holder_actor_id=None,claim_operation_id=None,claim_state='UNCLAIMED',authority_epoch=w.epoch,updated_commit_seq=w.seq))
    w.result={'entity_id':eid,'entity_rev':'1'}


def patch(w,p):
    eid=p['entity_id'];changes=p['changes']
    from .lamport import assert_based_write_allowed
    assert_based_write_allowed(w,eid,changes)
    w.depend(eid,changes)
    row=w.get(eid)
    cleaned={k:text(v,2048 if k=='note' else 1024,k!='display_name') for k,v in changes.items()}
    if 'display_name' in cleaned and (not cleaned['display_name'].strip() or cleaned['display_name'].lstrip().startswith('=')):raise CRMError('INVALID_NAME')
    diff={k:v for k,v in cleaned.items() if row[k]!=v}
    if diff:w.edit(eid,diff).update(diff)
    w.result={'entity_id':eid}


def token(w,eid,provided):
    r=w.c.execute('SELECT * FROM claims WHERE tenant_id=? AND resource_id=?',(w.tenant,eid)).fetchone()
    if not r or r['claim_state']!='HELD' or r['holder_actor_id']!=w.actor.actor_id:raise Conflict('CLAIM_NOT_HELD')
    expected={'resource_id':eid,'claim_generation':str(r['claim_generation']),'holder_actor_id':r['holder_actor_id'],'claim_operation_id':r['claim_operation_id'],'authority_epoch':str(r['authority_epoch'])}
    if provided!=expected or r['authority_epoch']!=w.epoch:raise Conflict('STALE_CLAIM_TOKEN')
    return dict(r)


def assert_no_actions(w,eid):
    if w.c.execute("SELECT 1 FROM external_actions WHERE tenant_id=? AND resource_id=? AND state IN ('PREPARED','IN_FLIGHT','UNKNOWN') LIMIT 1",(w.tenant,eid)).fetchone():raise Conflict('UNSETTLED_EXTERNAL_ACTION')


def transition(w,p):
    from .campaigns import assert_complete
    eid=p['entity_id'];row=w.get(eid);kind=row['entity_kind'];to=p['to_status']
    w.depend(eid,('status',),('children','dispatches','claim'))
    if kind=='dispatch':token(w,eid,p.get('claim_token'))
    if to==row['status']:return
    if to not in GRAPHS[kind].get(row['status'],set()):raise Conflict('INVALID_TRANSITION')
    evidence=p.get('evidence_artifact_id')
    required=(to in ('completed','signed','fulfilled','won') or row['status'] in ('completed','closed','unknown'))
    if required and not evidence:raise Conflict('ACCEPTANCE_EVIDENCE_REQUIRED')
    if evidence:w.artifact(evidence)
    if to=='completed':assert_complete(w,eid)
    if kind=='stage' and to=='cancelled':
        if w.c.execute("SELECT 1 FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.parent_work_item_id=? AND e.deleted_at IS NULL AND e.status NOT IN ('completed','cancelled') LIMIT 1",(w.tenant,eid)).fetchone():raise Conflict('STAGE_CHILDREN_UNFINISHED')
    if kind in ('stage','ticket') and to in ('completed','cancelled'):
        if w.c.execute("SELECT 1 FROM dispatch_attempts d JOIN claims c ON c.tenant_id=d.tenant_id AND c.resource_id=d.dispatch_id WHERE d.tenant_id=? AND d.work_item_id=? AND c.claim_state!='UNCLAIMED' LIMIT 1",(w.tenant,eid)).fetchone():raise Conflict('CHILD_CLAIM_HELD')
    if kind=='dispatch' and to in TERMINAL[kind]:assert_no_actions(w,eid)
    w.edit(eid,('status',))['status']=to
    if evidence:
        field='result_artifact_id' if kind in ('stage','ticket') else 'receipt_artifact_id' if kind=='project' else 'artifact_id' if kind in ('opportunity','contract') else 'output_artifact_id' if kind=='dispatch' else None
        if field:w.update_facet(eid,{field:evidence})
    if kind in ('stage','ticket'):
        f=w.facet(eid);w.guard(f['project_id'],'work_items')
        if f['parent_work_item_id']:w.guard(f['parent_work_item_id'],'children')
    for r in w.c.execute('SELECT campaign_id FROM campaign_memberships WHERE tenant_id=? AND entity_id=?',(w.tenant,eid)):
        w.guard(r[0],'memberships')
    w.result={'entity_id':eid,'status':to}


def tombstone(w,p):
    eid=p['entity_id'];w.depend(eid,guards=('children','work_items','memberships','dispatches','claim','channels','aliases','timeline'))
    # v0.5 requires current base for destructive graph operations, a stricter safe
    # subset of v4 conditional merging. Never infer absence from a stale snapshot.
    if w.base!=w.seq-1:raise Conflict('DESTRUCTIVE_CURRENT_BASE_REQUIRED')
    checks=[('patrons','organization_id'),('projects','project_id'),('work_items','project_id'),('work_items','parent_work_item_id'),('commercial_records','primary_patron_id'),('commercial_records','project_id'),('commercial_records','origin_opportunity_id'),('dispatch_attempts','work_item_id'),('dispatch_attempts','thread_id')]
    for table,col in checks:
        if table=='projects':continue
        facet_id={'patrons':'patron_id','work_items':'work_item_id','commercial_records':'commercial_id','dispatch_attempts':'dispatch_id'}[table]
        if w.c.execute(f'SELECT 1 FROM {table} f JOIN entities e ON e.tenant_id=f.tenant_id AND e.entity_id=f.{facet_id} WHERE f.tenant_id=? AND f.{col}=? AND e.deleted_at IS NULL LIMIT 1',(w.tenant,eid)).fetchone():raise Conflict('LIVE_REFERENCES')
    claim=w.c.execute('SELECT claim_state FROM claims WHERE tenant_id=? AND resource_id=?',(w.tenant,eid)).fetchone()
    if claim and claim[0]!='UNCLAIMED':raise Conflict('CLAIM_HELD')
    w.edit(eid,('deleted_at',))['deleted_at']=w.now
    w.add_event('entity.tombstone',{'reason':text(p['reason'],1024)},eid)


def alias(w,p):
    eid=p['entity_id'];w.depend(eid,guards=('aliases',));value=text(p['original_value'],1024)
    if not value.strip():raise CRMError('EMPTY_ALIAS')
    aid=p['alias_id'];old=w.c.execute('SELECT * FROM entity_aliases WHERE tenant_id=? AND alias_id=?',(w.tenant,aid)).fetchone()
    if old:
        if old['entity_id']!=eid or old['original_value']!=value:raise Conflict('ALIAS_ID_REUSED')
        if p['retire'] and not old['retired_at']:w.c.execute('UPDATE entity_aliases SET retired_at=? WHERE tenant_id=? AND alias_id=?',(w.now,w.tenant,aid))
        else:return
    else:
        if p['retire']:raise Conflict('ALIAS_NOT_FOUND')
        if p.get('source_artifact_id'):w.artifact(p['source_artifact_id'])
        w.insert('entity_aliases',dict(tenant_id=w.tenant,alias_id=aid,entity_id=eid,original_value=value,normalized_key=normalize_name(value),normalizer_version='nfkc-casefold-ws-v1',verified=0,source_artifact_id=p.get('source_artifact_id'),retired_at=None))
    w.edit(eid,('aliases',));w.guard(eid,'aliases')


def channel(w,p):
    eid=p['patron_id'];w.get(eid,kind=('person','organization'));w.depend(eid,guards=('channels',))
    value=text(p['original_value'],1024);kind=p['channel_kind'];ext=p.get('extension');region=p.get('region');normal=None;ver='literal-v1'
    if kind in ('domain','email'):
        import idna
        domain=value if kind=='domain' else value.rsplit('@',1)[-1]
        try:domain=idna.encode(domain.rstrip('.').lower(),uts46=False).decode().lower()
        except (idna.IDNAError,UnicodeError) as exc:raise CRMError('INVALID_DOMAIN') from exc
        if kind=='email':
            if value.count('@')!=1 or not value.split('@')[0]:raise CRMError('INVALID_EMAIL')
            normal=value.rsplit('@',1)[0]+'@'+domain
        else:normal=domain
        ver='idna2008-v1'
    elif kind=='phone':
        # Do not guess a country. International shape is a candidate key, not
        # numbering-plan validation; local forms remain unresolved unless parser installed.
        try:
            import phonenumbers
        except ImportError:
            raise Unsupported('PHONE_NORMALIZER_UNAVAILABLE','Install phonenumbers to admit phone channels.')
        try:
            parsed=phonenumbers.parse(value,region)
            if not phonenumbers.is_possible_number(parsed):raise ValueError()
            normal=phonenumbers.format_number(parsed,phonenumbers.PhoneNumberFormat.E164)
            if parsed.extension and ext and parsed.extension!=ext:raise ValueError()
            ext=ext or parsed.extension or None
            ver='libphonenumber-'+phonenumbers.__version__
        except Exception as exc:raise CRMError('INVALID_PHONE') from exc
    else:normal=value
    old=w.c.execute('SELECT * FROM contact_channels WHERE tenant_id=? AND channel_id=?',(w.tenant,p['channel_id'])).fetchone()
    if old:
        if (old['patron_id'],old['channel_kind'],old['original_value'])!=(eid,kind,value):raise Conflict('CHANNEL_ID_REUSED')
        if p['retire'] and not old['retired_at']:
            if w.facet(eid)['primary_channel_id']==p['channel_id']:raise Conflict('PRIMARY_CHANNEL_RETIRE')
            w.c.execute('UPDATE contact_channels SET retired_at=? WHERE tenant_id=? AND channel_id=?',(w.now,w.tenant,p['channel_id']))
        else:return
    else:
        if p['retire']:raise Conflict('CHANNEL_NOT_FOUND')
        if p.get('source_artifact_id'):w.artifact(p['source_artifact_id'])
        w.insert('contact_channels',dict(tenant_id=w.tenant,channel_id=p['channel_id'],patron_id=eid,channel_kind=kind,original_value=value,normalized_value=normal,normalizer_version=ver,extension=ext,source_region=region,verified=0,source_artifact_id=p.get('source_artifact_id'),retired_at=None))
    w.edit(eid,('channels',));w.guard(eid,'channels')


def primary_channel(w,p):
    eid=p['patron_id'];w.get(eid,kind=('person','organization'));w.depend(eid,('primary_channel_id',),('channels',))
    cid=p['channel_id']
    if cid:
        r=w.c.execute('SELECT 1 FROM contact_channels WHERE tenant_id=? AND channel_id=? AND patron_id=? AND retired_at IS NULL',(w.tenant,cid,eid)).fetchone()
        if not r:raise Conflict('CHANNEL_NOT_OWNED')
    if w.facet(eid)['primary_channel_id']!=cid:w.update_facet(eid,{'primary_channel_id':cid})


def register_artifact(w,p):
    ref=p['object_ref'];registry=w.engine.artifact_registry
    if ref not in registry:raise CRMError('UNTRUSTED_OBJECT_REFERENCE',exit_code=4)
    path=Path(registry[ref]).resolve()
    if path.is_symlink() or not path.is_file():raise CRMError('ARTIFACT_UNAVAILABLE')
    h=hashlib.sha256();size=0
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block);size+=len(block)
    if size!=integer(p['size_bytes']) or h.hexdigest()!=p['sha256']:raise Conflict('ARTIFACT_DIGEST_MISMATCH')
    old=w.c.execute('SELECT * FROM artifacts WHERE tenant_id=? AND artifact_id=?',(w.tenant,p['artifact_id'])).fetchone()
    values=dict(tenant_id=w.tenant,artifact_id=p['artifact_id'],media_type=text(p['media_type'],128),size_bytes=size,sha256=p['sha256'],object_ref=ref,object_version=p['object_version'],visibility=p['visibility'],verified_at=w.now)
    if old:
        if any(old[k]!=v for k,v in values.items() if k!='verified_at'):raise Conflict('ARTIFACT_ID_REUSED')
        return
    w.insert('artifacts',values)
    # Only logical object reference; never registry filesystem paths in audit.
    w.add_event('artifact.registered',values)


def interaction(w,p,correction=False):
    eid=p['patron_id'];w.get(eid,kind=('person','organization'));w.depend(eid,('status',))
    occurred=timestamp(p['occurred_at'])
    if datetime.fromisoformat(occurred.replace('Z','+00:00'))>datetime.now(timezone.utc)+timedelta(minutes=5):raise CRMError('FUTURE_TOUCHPOINT')
    if p.get('thread_id'):w.get(p['thread_id'],kind='thread');w.depend(p['thread_id'],('status',))
    if p.get('source_artifact_id'):w.artifact(p['source_artifact_id'])
    values=dict(tenant_id=w.tenant,interaction_id=p['interaction_id'],patron_id=eid,thread_id=p.get('thread_id'),supersedes_interaction_id=p.get('supersedes_interaction_id'),record_kind=p['record_kind'] if correction else 'touchpoint',subject=text(p['subject'],512),summary=text(p.get('summary'),2048,True),approved_excerpt=text(p.get('approved_excerpt'),4096,True),source_artifact_id=p.get('source_artifact_id'),occurred_at=occurred,recorded_at=w.now,commit_seq=w.seq,actor_id=w.actor.actor_id)
    old=w.c.execute('SELECT * FROM interactions WHERE tenant_id=? AND interaction_id=?',(w.tenant,p['interaction_id'])).fetchone()
    if old:
        if any(old[k]!=v for k,v in values.items() if k not in ('recorded_at','commit_seq')):raise Conflict('INTERACTION_ID_REUSED')
        return
    if correction:
        old=w.c.execute('SELECT * FROM interactions WHERE tenant_id=? AND interaction_id=? AND patron_id=?',(w.tenant,p['supersedes_interaction_id'],eid)).fetchone()
        if not old or old['commit_seq']>w.base:raise Conflict('PREDECESSOR_UNAVAILABLE')
        if w.c.execute('SELECT 1 FROM interactions WHERE tenant_id=? AND supersedes_interaction_id=?',(w.tenant,p['supersedes_interaction_id'])).fetchone():raise Conflict('PREDECESSOR_SUPERSEDED')
        w.interaction_ids.add(p['supersedes_interaction_id'])
    w.insert('interactions',values);w.interaction_ids.add(p['interaction_id']);w.refresh.add(eid)
    if p.get('thread_id'):w.refresh.add(p['thread_id'])
    w.guard(eid,'timeline');w.add_event('interaction.recorded',values,eid)


def acquire(w,p):
    eid=p['resource_id'];row=w.get(eid,kind='dispatch');w.depend(eid,('status','claim'),('claim',))
    if row['status']!='queued':raise Conflict('DISPATCH_NOT_QUEUED')
    r=w.c.execute('SELECT * FROM claims WHERE tenant_id=? AND resource_id=?',(w.tenant,eid)).fetchone()
    if r['claim_state']!='UNCLAIMED':raise Conflict('ALREADY_CLAIMED')
    gen=r['claim_generation']+1
    if gen>MAX_I64:raise CRMError('CLAIM_GENERATION_EXHAUSTED',exit_code=7)
    w.c.execute("UPDATE claims SET claim_generation=?,holder_actor_id=?,claim_operation_id=?,claim_state='HELD',authority_epoch=?,updated_commit_seq=? WHERE tenant_id=? AND resource_id=?",(gen,w.actor.actor_id,w.op,w.epoch,w.seq,w.tenant,eid))
    w.edit(eid,('claim',));w.guard(eid,'claim')
    w.result={'claim_token':dict(resource_id=eid,claim_generation=str(gen),holder_actor_id=w.actor.actor_id,claim_operation_id=w.op,authority_epoch=str(w.epoch))}


def release(w,p,recover=False):
    eid=p['resource_id'];w.get(eid,kind='dispatch');w.depend(eid,('claim',),('claim',));assert_no_actions(w,eid)
    if recover:
        r=w.c.execute('SELECT * FROM claims WHERE tenant_id=? AND resource_id=?',(w.tenant,eid)).fetchone()
        if r['claim_generation']!=integer(p['expected_generation']):raise Conflict('STALE_CLAIM_TOKEN')
        evidence=w.artifact(p['fencing_evidence_artifact_id'])
        if w.engine.fencing_verifier is None:
            raise Unsupported('FENCING_PROVIDER_REQUIRED','The host must verify actual executor fencing; an artifact hash alone is not proof.')
        if not w.engine.fencing_verifier(evidence,eid,dict(r)):
            raise Conflict('FENCING_NOT_ESTABLISHED')
        if w.base!=w.seq-1:raise Conflict('RECOVERY_CURRENT_BASE_REQUIRED')
        if r['claim_state']=='UNCLAIMED':return
    else:token(w,eid,p['claim_token'])
    w.c.execute("UPDATE claims SET holder_actor_id=NULL,claim_operation_id=NULL,claim_state='UNCLAIMED',authority_epoch=?,updated_commit_seq=? WHERE tenant_id=? AND resource_id=?",(w.epoch,w.seq,w.tenant,eid))
    w.edit(eid,('claim',));w.guard(eid,'claim');w.add_event('claim.released',{'reason':text(p['reason'],1024),'recovery':recover},eid)


def chunk(w,p):
    eid=p['dispatch_id'];w.get(eid,kind='dispatch');w.depend(eid,('claim','status'),('claim',));token(w,eid,p['claim_token'])
    idx=integer(p['chunk_index']);artifact=w.artifact(p['artifact_id'])
    if artifact['sha256']!=p['sha256']:raise Conflict('CHUNK_DIGEST')
    old=w.c.execute('SELECT * FROM thread_chunks WHERE tenant_id=? AND dispatch_id=? AND chunk_index=?',(w.tenant,eid,idx)).fetchone()
    if old:
        if (old['sha256'],old['artifact_id'])!=(p['sha256'],p['artifact_id']):raise Conflict('CHUNK_ID_REUSED')
        return
    w.insert('thread_chunks',dict(tenant_id=w.tenant,dispatch_id=eid,chunk_index=idx,sha256=p['sha256'],artifact_id=p['artifact_id'],commit_seq=w.seq))
    w.refresh.add(eid);w.add_event('dispatch.chunk',p,eid)


def terms(w,p):
    eid=p['commercial_id'];row=w.get(eid,kind=('opportunity','contract'))
    w.depend(eid,('status','amount_minor','currency','due_at','artifact_id'))
    if row['status'] in TERMINAL[row['entity_kind']] or (row['entity_kind']=='contract' and row['status']!='draft'):raise Conflict('IMMUTABLE_COMMERCIAL_TERMS')
    amount=integer(p['amount_minor']) if p['amount_minor'] is not None else None;currency=p['currency']
    if (amount is not None and currency is None) or (currency is not None and currency not in w.engine.currencies):raise CRMError('CURRENCY_REQUIRED_OR_INVALID')
    changes={'amount_minor':amount,'currency':currency}
    if 'due_at' in p:changes['due_at']=timestamp(p['due_at']) if p['due_at'] is not None else None
    if 'artifact_id' in p:
        if p['artifact_id']:w.artifact(p['artifact_id'])
        changes['artifact_id']=p['artifact_id']
    old=w.facet(eid);changes={k:v for k,v in changes.items() if old[k]!=v}
    if changes:w.update_facet(eid,changes)


def merge(w,p):
    survivor,retired=p['survivor_id'],p['retired_id'];a=w.get(survivor,kind=('person','organization'));b=w.get(retired,kind=a['entity_kind'])
    if survivor==retired:raise Conflict('SELF_MERGE')
    if w.base!=w.seq-1:raise Conflict('MERGE_CURRENT_BASE_REQUIRED')
    for eid in (survivor,retired):w.depend(eid,tuple(a),('children','channels','aliases','timeline','memberships'))
    w.artifact(p['evidence_artifact_id'])
    # Ambiguous canonical choices are not silently overwritten by a merge.
    for key in ('status','note','next_action'):
        if a[key]!=b[key]:raise Conflict('UNRESOLVED_MERGE_FIELDS')
    af,bf=w.facet(survivor),w.facet(retired)
    for key in ('organization_id','primary_channel_id','patron_type','funding_band','funding_currency','active_cipher_motif'):
        if af[key]!=bf[key]:raise Conflict('UNRESOLVED_MERGE_FACET')
    refs=[]
    for table,key,col in [('patrons','patron_id','organization_id'),('commercial_records','commercial_id','primary_patron_id')]:
        for r in w.c.execute(f'SELECT {key} FROM {table} WHERE tenant_id=? AND {col}=?',(w.tenant,retired)):
            refs.append((r[0],col))
    if len(refs)>20:raise CRMError('TOO_LARGE_FOR_ATOMIC_COMMAND')
    # Memberships must be reconciled explicitly rather than silently duplicated.
    if w.c.execute('SELECT 1 FROM campaign_memberships WHERE tenant_id=? AND entity_id=?',(w.tenant,retired)).fetchone():raise Conflict('MERGE_MEMBERSHIP_REVIEW_REQUIRED')
    for eid,col in refs:
        if w.get(eid)['entity_kind']=='contract' and w.get(eid)['status']!='draft':raise Conflict('SIGNED_COUNTERPARTY_IMMUTABLE')
        w.update_facet(eid,{col:survivor})
    w.edit(retired,('deleted_at','merged_into_id')).update(deleted_at=w.now,merged_into_id=survivor)
    w.guard(survivor,'children');w.refresh.add(survivor)
    w.add_event('entity.merge',{'survivor_id':survivor,'retired_id':retired,'reason':text(p['reason'],1024),'evidence_artifact_id':p['evidence_artifact_id']},retired)


def tag(w,p):
    eid=p['entity_id'];w.depend(eid,guards=('tags',))
    old=w.c.execute('SELECT 1 FROM entity_tags WHERE tenant_id=? AND entity_id=? AND tag=?',(w.tenant,eid,p['tag'])).fetchone()
    if bool(old)==p['present']:return
    if p['present']:w.insert('entity_tags',dict(tenant_id=w.tenant,entity_id=eid,tag=p['tag'],introduced_commit_seq=w.seq))
    else:w.c.execute('DELETE FROM entity_tags WHERE tenant_id=? AND entity_id=? AND tag=?',(w.tenant,eid,p['tag']))
    w.edit(eid,('tags',));w.guard(eid,'tags')


def dispatch(w,cmd,p):
    from .campaigns import membership,select_plan
    from .quarantine import resolve
    handlers={'entity.create':create,'entity.patch':patch,'entity.transition':transition,'entity.tombstone':tombstone,
      'campaign.membership.set':membership,'entity.alias.set':alias,'entity.tag.set':tag,'patron.channel.set':channel,
      'patron.primary_channel.set':primary_channel,'artifact.register':register_artifact,'interaction.append':interaction,
      'interaction.supersede':lambda w,p:interaction(w,p,True),'dispatch.chunk.append':chunk,'claim.acquire':acquire,
      'claim.release':release,'claim.recover':lambda w,p:release(w,p,True),'observation.resolve':resolve,
      'project.plan.select':select_plan,'commercial.terms.set':terms,'entity.merge':merge}
    handlers[cmd](w,p)
