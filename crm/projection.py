"""Pure deterministic row rendering. Human-owned cells are never publication values."""
import json
from .db import ROOT
from .codec import digest,jcs
from .model import FACETS,TERMINAL,predecessors
MANIFEST=json.loads((ROOT/'schema/sheets_columns_v4.json').read_text())
HEADERS={k:[c['header'] for c in v] for k,v in MANIFEST['tabs'].items()}
TABKEY={'Directory':'directory','Active Pipeline':'active_pipeline','Completed Archives':'completed_archives'}
LAYOUT_DIGEST=digest(MANIFEST)


def render(c,tenant,eid,seq):
    e=dict(c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,eid)).fetchone())
    kind=e['entity_kind'];table,key=FACETS[kind];f=dict(c.execute(f'SELECT * FROM {table} WHERE tenant_id=? AND {key}=?',(tenant,eid)).fetchone())
    state=dict(c.execute('SELECT * FROM ledger_state').fetchone())
    terminal=kind in TERMINAL and (e['status'] in TERMINAL[kind] or e['deleted_at'])
    tab='Directory' if kind in ('person','organization','thread') else 'Completed Archives' if terminal else 'Active Pipeline'
    row={h:'' for h in HEADERS[tab] if h not in ('human_status','human_note')}
    for k in row:
        if k in e and e[k] is not None:row[k]=str(e[k])
        if k in f and f[k] is not None:row[k]=str(f[k])
    row.update(entity_id=eid,entity_kind=kind,ledger_id=state['ledger_id'],tenant_id=tenant,authority_epoch=str(state['authority_epoch']),projection_seq=str(seq),generation_id='',sync_state='TOMBSTONED' if e['deleted_at'] else 'CURRENT')
    membership=c.execute('SELECT campaign_id FROM campaign_memberships WHERE tenant_id=? AND entity_id=? AND is_primary=1',(tenant,eid)).fetchone()
    if membership:row['primary_campaign_id' if tab=='Directory' else 'campaign_id']=membership[0]
    if kind in ('person','organization'):
        if f.get('organization_id'):
            r=c.execute('SELECT display_name FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,f['organization_id'])).fetchone();row['organization_name']=r[0] if r else ''
        if f.get('primary_channel_id'):
            r=c.execute('SELECT original_value FROM contact_channels WHERE tenant_id=? AND channel_id=? AND retired_at IS NULL',(tenant,f['primary_channel_id'])).fetchone();row['contact_channel']=r[0] if r else ''
        owners=predecessors(c,tenant,eid)
        r=c.execute("SELECT max(i.occurred_at) FROM interactions i WHERE i.tenant_id=? AND i.patron_id IN ("+','.join('?' for _ in owners)+") AND i.record_kind!='retraction' AND NOT EXISTS(SELECT 1 FROM interactions n WHERE n.tenant_id=i.tenant_id AND n.supersedes_interaction_id=i.interaction_id)",(tenant,*owners)).fetchone();row['last_touchpoint']=r[0] or ''
        p=c.execute('''SELECT p.proposal_id,p.evidence_digest,p.reason_code,p.capture_operation_id,r.decision FROM quarantine_proposals p LEFT JOIN proposal_resolutions r ON r.tenant_id=p.tenant_id AND r.proposal_id=p.proposal_id WHERE p.tenant_id=? AND p.target_entity_id=? ORDER BY p.observation_seq DESC LIMIT 1''',(tenant,eid)).fetchone()
        if p:
            row['human_ack']=jcs({'proposal_id':p['proposal_id'],'captured_digest':p['evidence_digest'],'disposition':p['decision'] or p['reason_code']}).decode()
            pending=c.execute("SELECT p.reason_code FROM quarantine_proposals p JOIN observation_heads h ON h.tenant_id=p.tenant_id AND h.proposal_id=p.proposal_id LEFT JOIN proposal_resolutions r ON r.tenant_id=p.tenant_id AND r.proposal_id=p.proposal_id WHERE p.tenant_id=? AND p.target_entity_id=? AND r.proposal_id IS NULL AND p.reason_code!='BLANK_DRAFT'",(tenant,eid)).fetchall()
            if pending:row['sync_state']='CONFLICT' if any(x[0]!='CAPTURED_UNBASED' for x in pending) else 'PENDING_INPUT'
    project=eid if kind=='project' else f.get('project_id')
    if kind=='dispatch':
        wf=c.execute('SELECT * FROM work_items WHERE tenant_id=? AND work_item_id=?',(tenant,f['work_item_id'])).fetchone();project=wf['project_id'];row['parent_id']=f['work_item_id']
        claim=c.execute('SELECT * FROM claims WHERE tenant_id=? AND resource_id=?',(tenant,eid)).fetchone()
        row['claim_generation']=str(claim['claim_generation']);row['claim_state']=claim['claim_state'];row['owner_actor_id']=claim['holder_actor_id'] or f['actor_id']
        chunks=[r[0] for r in c.execute('SELECT chunk_index FROM thread_chunks WHERE tenant_id=? AND dispatch_id=? ORDER BY chunk_index',(tenant,eid))];idx=-1
        for n in chunks:
            if n!=idx+1:break
            idx=n
        row['chunk_index']=str(idx) if idx>=0 else ''
    if project and 'project_id' in row:
        row['project_id']=project
        pf=c.execute('SELECT * FROM projects WHERE tenant_id=? AND project_id=?',(tenant,project)).fetchone()
        stages=c.execute("SELECT w.stage_ordinal,w.required,e.status FROM work_items w JOIN entities e ON e.tenant_id=w.tenant_id AND e.entity_id=w.work_item_id WHERE w.tenant_id=? AND w.project_id=? AND w.plan_version=? AND w.entity_kind='stage' AND e.deleted_at IS NULL ORDER BY stage_ordinal",(tenant,project,pf['active_plan_version'])).fetchall()
        row['stage_total']=str(len(stages));unresolved=[r['stage_ordinal'] for r in stages if r['required'] and r['status']!='completed'];row['stage_current']=str(min(unresolved) if unresolved else (stages[-1]['stage_ordinal'] if stages else 0))
    if 'parent_id' in row and not row['parent_id']:row['parent_id']=f.get('parent_work_item_id') or f.get('origin_opportunity_id') or ''
    if 'owner_actor_id' in row and not row['owner_actor_id']:row['owner_actor_id']=f.get('lead_actor_id') or f.get('assigned_actor_id') or ''
    aid=f.get('result_artifact_id') or f.get('receipt_artifact_id') or f.get('artifact_id') or f.get('output_artifact_id')
    if aid and 'artifact_id' in row:
        ar=c.execute('SELECT sha256 FROM artifacts WHERE tenant_id=? AND artifact_id=?',(tenant,aid)).fetchone();row['artifact_id']=aid;row['sha256_receipt']=ar[0]
    if tab=='Completed Archives':
        # Pin the most recent entry into terminal routing, not a later note revision.
        closed=None
        prev_terminal=False
        for v in c.execute('SELECT state_jcs,commit_seq,recorded_at FROM entity_versions WHERE tenant_id=? AND entity_id=? ORDER BY entity_rev',(tenant,eid)):
            old=json.loads(v['state_jcs'])['entity'];nowterm=bool(old['deleted_at']) or old['status'] in TERMINAL[kind]
            if nowterm and not prev_terminal:closed=(v['recorded_at'],v['commit_seq'])
            prev_terminal=nowterm
        if closed:row['closed_at'],row['terminal_commit_seq']=closed[0],str(closed[1])
    row={k:('' if v is None else str(v)) for k,v in row.items() if k in HEADERS[tab]}
    row['record_digest']=row_digest(row)
    return tab,row


def row_digest(row):
    return digest({k:v for k,v in row.items() if k not in ('record_digest','human_status','human_note','human_ack','sync_state')})
