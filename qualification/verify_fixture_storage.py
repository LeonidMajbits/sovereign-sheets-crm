#!/usr/bin/env python3
"""Read-only final fixture checks; never mutate/repair a database.
Only accepts a generated crm-turn6-* fixture root in the OS temporary directory.
The main matrix already verifies audit chains and cloud frames separately.
"""
from pathlib import Path
import argparse,json,sqlite3,tempfile,hashlib

def verify(root):
    root=Path(root).resolve();temp=Path(tempfile.gettempdir()).resolve()
    if root.parent!=temp or not root.name.startswith('crm-turn6-'):
        raise ValueError('Only a fresh run_matrix temporary fixture is admitted')
    checks=[]
    for d in sorted(root.glob('tenant-*')):
        c=sqlite3.connect((d/'crm.db').as_uri()+'?mode=ro',uri=True)
        try:
            c.execute('PRAGMA query_only=ON');c.execute('BEGIN');c.row_factory=sqlite3.Row
            tenant=c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0]
            entities=list(c.execute('SELECT entity_id,note,entity_rev FROM entities ORDER BY entity_id'))
            count=0
            for r in c.execute('SELECT d.*,f.summary AS f_summary,f.source_entity_rev AS f_revision,f.entity_id AS f_entity_id,f.tenant_id AS f_tenant FROM entity_search_documents d JOIN entity_fts f ON f.rowid=d.search_doc_id'):
                assert r['tenant_id']==r['f_tenant']==tenant
                assert r['entity_id']==r['f_entity_id']
                assert r['summary']==r['f_summary']
                assert int(r['source_entity_rev'])==int(r['f_revision'])
                entity=c.execute('SELECT note,entity_rev FROM entities WHERE entity_id=?',(r['entity_id'],)).fetchone()
                assert r['summary']==(entity['note'] or '')
                assert int(r['source_entity_rev'])==entity['entity_rev'];count+=1
            assert count==len(entities)
            assert c.execute('SELECT count(*) FROM entity_fts').fetchone()[0]==len(entities)
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
            assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            checks.append({'tenant':tenant,'entities':len(entities),'exact_current_fts_documents':count,
                           'integrity_check':'ok','foreign_key_violations':0,
                           'canonical_note_digest':hashlib.sha256(json.dumps([list(x) for x in entities],separators=(',',':')).encode()).hexdigest()})
        finally:c.close()
    assert checks,'No fixture ledgers found'
    return {'status':'PASS','tenants':checks,'total_exact_current_fts_documents':sum(x['exact_current_fts_documents'] for x in checks),
            'scope':'Read-only per-tenant snapshots; business state is quiescent. Exact current FTS text/revisions and SQLite integrity, not performance.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture-root',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=verify(a.fixture_root)
    with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({'status':result['status'],'exact_documents':result['total_exact_current_fts_documents']}))
