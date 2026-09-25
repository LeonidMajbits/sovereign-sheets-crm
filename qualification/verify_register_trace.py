#!/usr/bin/env python3
"""Independent audit-trace oracle. Reads trace evidence, not a live CRM database.
It reconstructs Lamport registers without importing the implementation under test.
Requires the complete synthetic operation trace emitted by run_matrix.py.
"""
from __future__ import annotations
import argparse,gzip,json,hashlib
from pathlib import Path

def verify(path:Path):
    heads={};values={};receive={};outcomes=set();creates=0;candidates=0
    with gzip.open(path,'rt',encoding='utf-8') as f:
        for line in f:
            x=json.loads(line);p=x['packet'];r=x['outcome'];t=p['tenant_id'];op=p['operation_id']
            assert (t,op) not in outcomes, 'duplicate operation in accepted trace'
            outcomes.add((t,op));assert r['disposition']=='COMMITTED'
            if p['command_type']=='entity.create':creates+=1;continue
            assert p['command_type']=='entity.lww.set'
            v=p['payload'];k=(t,v['entity_id'],v['field']);n=int(v['logical_clock'])
            # The synthetic authenticated actor mapping is explicit in run_matrix.uid.
            actor_number=(1700000000000<<80)+1000+x['worker']
            alphabet='0123456789ABCDEFGHJKMNPQRSTVWXYZ';actor=''
            for _ in range(26):actor=alphabet[actor_number&31]+actor;actor_number >>= 5
            rank=(n,actor,op)
            expected_selected=k not in heads or rank>heads[k]
            assert r['data']['selected']==expected_selected
            if expected_selected:heads[k]=rank;values[k]=v['value']
            winner=r['data']['winner']
            assert (int(winner['logical_clock']),winner['actor_id'],winner['operation_id'])==heads[k]
            receive[t]=max(receive.get(t,0),n)+1
            assert int(r['data']['receive_clock'])==receive[t]
            candidates+=1
    digest=hashlib.sha256(json.dumps([[*k,list(heads[k]),values[k]] for k in sorted(heads)],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return {'status':'PASS','source_trace_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'distinct_operations':len(outcomes),'entity_creates':creates,'lamport_candidates':candidates,
            'registers':len(heads),'tenants':len(receive),'final_registers_digest':digest,
            'scope':'Independent reconstruction of every recorded rank, selected outcome and receive-clock recurrence; not an independent cloud or disk durability proof.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--trace',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=verify(Path(a.trace));out=Path(a.output)
    with out.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
