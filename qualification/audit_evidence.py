#!/usr/bin/env python3
"""Export synthetic fixture audit bytes and independently verify the compressed stream.
This does not import the CRM implementation. No production database path is accepted.
"""
from pathlib import Path
import argparse,sqlite3,tempfile,json,gzip,hashlib

def digest(raw,domain):return hashlib.sha256(domain.encode()+b'\n'+raw).hexdigest()
def emit(f,kind,raw,h):f.write(json.dumps({'frame':kind,'payload_jcs':raw.decode(),'digest':h},ensure_ascii=False,separators=(',',':'))+'\n')
def export(root,out):
    root=Path(root).resolve()
    if root.parent!=Path(tempfile.gettempdir()).resolve() or not root.name.startswith('crm-turn6-'):raise ValueError('Only synthetic run_matrix fixture roots accepted')
    with gzip.open(out,'xt',encoding='utf-8',compresslevel=6) as f:
        for db in sorted(root.glob('tenant-*/crm.db')):
            c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
            try:
                c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
                for seq,raw,h in c.execute('SELECT commit_seq,manifest_jcs,transaction_digest FROM audit_transactions ORDER BY commit_seq'):
                    emit(f,'transaction',raw,h)
                    for eraw,eh in c.execute('SELECT event_jcs,event_digest FROM audit_log WHERE commit_seq=? ORDER BY event_ordinal',(seq,)):emit(f,'event',eraw,eh)
            finally:c.close()

def verify(path):
    chains={};seen_ops=set();txn=None;ordinal=0;events=0;transactions=0
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            obj=json.loads(line);raw=obj['payload_jcs'].encode();payload=json.loads(raw)
            if obj['frame']=='transaction':
                if txn is not None:assert ordinal==int(txn['event_count'])
                t=payload['tenant_id'];seq=int(payload['commit_seq']);previous=chains.get(t,(0,'0'*64))
                assert seq==previous[0]+1 and payload['previous_digest']==previous[1]
                assert digest(raw,'CRM3:transaction:v1')==obj['digest']
                assert (t,payload['operation_id']) not in seen_ops;seen_ops.add((t,payload['operation_id']))
                assert int(payload['event_count'])==len(payload['event_digests'])
                chains[t]=(seq,obj['digest']);txn=payload;ordinal=0;transactions+=1
            elif obj['frame']=='event':
                assert txn is not None
                assert payload['tenant_id']==txn['tenant_id'] and payload['ledger_id']==txn['ledger_id']
                assert payload['commit_seq']==txn['commit_seq'] and payload['operation_id']==txn['operation_id']
                assert int(payload['event_ordinal'])==ordinal and int(payload['event_count'])==int(txn['event_count'])
                assert digest(raw,'CRM3:event:v1')==obj['digest']==txn['event_digests'][ordinal]
                ordinal+=1;events+=1
            else:raise AssertionError('Unknown frame')
    assert txn is not None and ordinal==int(txn['event_count'])
    return {'status':'PASS','transactions':transactions,'events':events,'tenant_chains':chains,'compressed_bytes':Path(path).stat().st_size,'trace_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'scope':'Complete standalone audit-byte hash/chain/event-coverage verification; trusted head authenticity still depends on a separately trusted receipt.'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--fixture-root');p.add_argument('--trace',required=True);p.add_argument('--result',required=True);a=p.parse_args()
    if a.fixture_root:export(a.fixture_root,a.trace)
    result=verify(a.trace)
    with Path(a.result).open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='tenant_chains'},indent=2))
