"""Raw bytes live only in the private vault. SQL exposes safe discrepancy metadata."""
import json
from .codec import digest,jcs,loads,literal_cell,text,integer,utcnow
from .errors import CRMError,Conflict
from .ids import durable_id


def record_observation(w,*,source,resource,entity,field,ref,size,value_kind,reason,base=None,generation=None,sheet=None,row=None,column=None):
    sourcekey=digest({'source':source,'resource':resource,'generation':generation,'sheet':sheet,'row':row,'column':column,'entity':entity,'field':field})
    old=w.c.execute('SELECT * FROM observation_heads WHERE tenant_id=? AND source_key_digest=?',(w.tenant,sourcekey)).fetchone()
    if old is None and reason=='BLANK_DRAFT':
        w.result={'proposal_id':None,'duplicate':True};return None
    if old and old['observed_digest']==ref:
        w.result={'proposal_id':old['proposal_id'],'duplicate':True};return old['proposal_id']
    pid=durable_id(w.c)
    seq=w.c.execute('SELECT coalesce(max(observation_seq),0)+1 FROM quarantine_proposals WHERE tenant_id=?',(w.tenant,)).fetchone()[0]
    w.insert('quarantine_proposals',dict(tenant_id=w.tenant,proposal_id=pid,observation_seq=seq,source_kind=source,source_resource_id=resource,source_generation_id=generation,source_sheet_id=sheet,source_row=row,source_column=column,target_entity_id=entity,target_field=field,evidence_digest=ref,evidence_size=size,evidence_object_ref=ref,reason_code=reason,value_kind=value_kind,base_commit_seq=base,captured_at=w.now,capture_operation_id=w.op))
    selection=(old['selection_rev']+1) if old else 1
    w.c.execute('INSERT INTO observation_heads VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,source_key_digest) DO UPDATE SET proposal_id=excluded.proposal_id,selection_rev=excluded.selection_rev,observed_digest=excluded.observed_digest',(w.tenant,sourcekey,pid,selection,ref))
    w.result={'proposal_id':pid,'selection_revision':str(selection)}
    w.add_event('observation.captured',{'proposal_id':pid,'evidence_digest':ref,'evidence_size':str(size),'reason_code':reason,'selection_revision':str(selection)},entity)
    if entity:w.refresh.add(entity)
    return pid


def capture(engine,actor,*,resource,generation,sheet,row,column,entity,field,cell):
    """Trusted scanner entrypoint. Caller cannot choose an arbitrary network URL.
    Scanner has already checked pinned resource/row identity; typed raw bytes remain
    solely in Vault. Empty transitions are captured too, invalidating stale adoption.
    """
    from .engine import Work
    try:
        value=literal_cell(cell)
        reason=('BLANK_DRAFT' if value=='' else 'CAPTURED_UNBASED') if field in ('human_note','human_status') else 'DIRECT_CANONICAL_EDIT';kind='string'
    except CRMError as exc:
        reason=exc.code;kind='rejected_cell'
    raw=json.dumps(cell,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode('utf-8');ref,size=engine.vault.put(raw)
    with engine.db.transaction() as c:
        s=engine.authorize(c,actor,'capture')
        engine.check_capacity(c,s)
        op=durable_id(c)
        packet=dict(schema_version='crm.capture.internal.v1',operation_id=op,tenant_id=s['tenant_id'],ledger_id=s['ledger_id'],authority_epoch=str(s['authority_epoch']),base=None,command_type='observation.capture',payload={'source_digest':ref,'resource':resource,'entity_id':entity,'field':field})
        w=Work(engine,c,actor,packet,s['commit_seq']+1,utcnow())
        if entity:w.get(entity,live=False)
        record_observation(w,source='sheet_scan' if field in ('human_note','human_status') else 'direct_drift',resource=resource,entity=entity,field=field,ref=ref,size=size,value_kind=kind,reason=reason,generation=generation,sheet=sheet,row=row,column=column)
        if w.result.get('duplicate'):return w.result
        return w.finish('CAPTURED_UNBASED')


def resolve(w,p):
    pid=p['proposal_id']
    proposal=w.c.execute('SELECT * FROM quarantine_proposals WHERE tenant_id=? AND proposal_id=?',(w.tenant,pid)).fetchone()
    if not proposal:raise Conflict('PROPOSAL_NOT_FOUND')
    if w.c.execute('SELECT 1 FROM proposal_resolutions WHERE tenant_id=? AND proposal_id=?',(w.tenant,pid)).fetchone():raise Conflict('PROPOSAL_ALREADY_RESOLVED')
    head=w.c.execute('SELECT * FROM observation_heads WHERE tenant_id=? AND proposal_id=?',(w.tenant,pid)).fetchone()
    if not head or head['selection_rev']!=integer(p['selection_revision'],1):raise Conflict('OBSERVATION_SUPERSEDED')
    eid=proposal['target_entity_id'];decision=p['decision']
    if decision=='ADOPT':
        if not eid or proposal['target_field'] not in ('human_note','human_status') or proposal['reason_code']!='CAPTURED_UNBASED':raise Conflict('PROPOSAL_NOT_ADOPTABLE')
        w.get(eid,kind=('person','organization'))
        value=literal_cell(loads(w.engine.vault.get(proposal['evidence_object_ref']),1048576))
        if not value:raise Conflict('BLANK_IS_NOT_CLEAR')
        from .entities import patch,transition
        if proposal['target_field']=='human_note':patch(w,{'entity_id':eid,'changes':{'note':value}})
        else:transition(w,{'entity_id':eid,'to_status':value})
    w.insert('proposal_resolutions',dict(tenant_id=w.tenant,proposal_id=pid,operation_id=w.op,decision=decision,selected_revision=head['selection_rev'],actor_id=w.actor.actor_id,reason_code='EXPLICIT_RESOLUTION',resolved_at=w.now))
    w.add_event('observation.resolved',{'proposal_id':pid,'decision':decision,'reason':text(p['reason'],1024)},eid)
    if eid:w.refresh.add(eid)
    w.result={'proposal_id':pid,'decision':decision}


def list_proposals(c,tenant,limit=50):
    if type(limit) is not int or not 1<=limit<=200:raise CRMError('LIMIT')
    return [dict(r) for r in c.execute('''SELECT p.proposal_id,p.observation_seq,p.target_entity_id,p.target_field,p.evidence_digest,p.evidence_size,p.reason_code,p.value_kind,p.captured_at,h.selection_rev,r.decision,
     CASE WHEN h.proposal_id IS NULL THEN 1 ELSE 0 END superseded
     FROM quarantine_proposals p LEFT JOIN observation_heads h ON h.tenant_id=p.tenant_id AND h.proposal_id=p.proposal_id
     LEFT JOIN proposal_resolutions r ON r.tenant_id=p.tenant_id AND r.proposal_id=p.proposal_id
     WHERE p.tenant_id=? ORDER BY p.observation_seq DESC LIMIT ?''',(tenant,limit))]
