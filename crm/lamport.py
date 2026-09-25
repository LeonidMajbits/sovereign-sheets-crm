"""Opt-in, audited Lamport registers for note/next_action only.

This is an explicit v6 extension, NOT a replacement for guarded claims, money,
status, identities or unbased human-input reconciliation. First use acquires
field ownership after a based check. Ordinary patches cannot bypass ownership.
All authenticated candidates (including losers) are immutable audit events.
"""
from __future__ import annotations
import copy
from .codec import integer, jcs, loads, text, ulid, MAX_I64
from .errors import CRMError, Conflict

FIELDS = frozenset({'note', 'next_action'})
KINDS = frozenset({'person', 'organization', 'campaign', 'project'})

def key(entity_id,field):
    return 'lamport.v6.head:' + entity_id + ':' + field

def validate(packet,validator):
    p=packet.get('payload',{})
    if not isinstance(p,dict) or set(p)!={'entity_id','field','value','logical_clock'}:
        raise CRMError('COMMAND_SCHEMA')
    shadow=copy.deepcopy(packet)
    shadow.update(schema_version='crm.command.v4',command_type='entity.patch',
                  payload={'entity_id':p.get('entity_id'),'changes':{'note':''}})
    if packet.get('schema_version')!='crm.command.v6' or not validator.is_valid(shadow):
        raise CRMError('COMMAND_SCHEMA')
    ulid(p['entity_id'])
    if p['field'] not in FIELDS:raise CRMError('LWW_FIELD_FORBIDDEN')
    if integer(p['logical_clock'],1)>=MAX_I64:raise CRMError('LAMPORT_EXHAUSTED')
    value=text(p['value'],2048 if p['field']=='note' else 1024,True)
    if value is not None and value.lstrip().startswith('='):raise CRMError('FORMULA_LIKE_INPUT')

def assert_based_write_allowed(w,eid,changes):
    for field in changes:
        if field in FIELDS and w.c.execute('SELECT 1 FROM runtime_state WHERE key=?',(key(eid,field),)).fetchone():
            raise Conflict('LWW_FIELD_OWNED')

def apply(w,p):
    eid,field=p['entity_id'],p['field']
    row=w.get(eid,kind=tuple(KINDS));w.depend(eid)
    name=key(eid,field)
    prior=w.c.execute('SELECT value FROM runtime_state WHERE key=?',(name,)).fetchone()
    head=loads(prior[0]) if prior else None
    if head is None:w.depend(eid,(field,))
    clock=integer(p['logical_clock'],1)
    lr=w.c.execute("SELECT value FROM runtime_state WHERE key='lamport.v6.receive_clock'").fetchone()
    received=max(int(lr[0]) if lr else 0,clock)+1
    if received>MAX_I64:raise CRMError('LAMPORT_EXHAUSTED',exit_code=7)
    rank=(clock,w.actor.actor_id,w.op)
    previous=(int(head['logical_clock']),head['actor_id'],head['operation_id']) if head else None
    selected=previous is None or rank>previous
    record={'logical_clock':str(clock),'actor_id':w.actor.actor_id,'operation_id':w.op}
    if selected:
        w.c.execute('INSERT INTO runtime_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(name,jcs(record).decode()))
        if row[field]!=p['value']:w.edit(eid,(field,))[field]=p['value']
    w.c.execute("INSERT INTO runtime_state VALUES('lamport.v6.receive_clock',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(received),))
    w.add_event('lamport.candidate',{'field':field,'value':p['value'],'rank':record,
               'previous_winner':head,'selected':selected,'receive_clock':str(received)},eid)
    w.result={'entity_id':eid,'field':field,'selected':selected,'winner':record if selected else head,
              'receive_clock':str(received)}
