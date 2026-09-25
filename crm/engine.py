"""Transactional accepting engine. Embed this object in the existing lab broker.

Command handlers only run inside Work. No agent may obtain this connection or
forge ActorContext; authentication is the broker boundary, not JSON role fields.
"""
from __future__ import annotations
import copy, json, hashlib, sqlite3, shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from jsonschema import Draft202012Validator
from .codec import jcs, loads, digest, ZERO, MAX_I64, integer, utcnow, text, ulid
from .db import Database, ROOT
from .errors import CRMError, Conflict, Unsupported
from .storage import Vault
from .model import FACETS, INITIAL, wire
from .ids import durable_id

SCHEMA = json.loads((ROOT/'schema/ingest_command_v4.schema.json').read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
CAPS = {x['command_type']:x['capability'] for x in json.loads((ROOT/'contracts/command_registry_v4.json').read_text())['commands']}
CAPS['entity.tag.set'] = 'entity.edit'
CAPS['entity.lww.set'] = 'entity.lww'
ALL_CAPS = frozenset(CAPS.values()) | {'sync','query','read','capture','artifact.register'}

@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    capabilities: frozenset[str]

class Work:
    def __init__(self, engine, conn, actor, packet, seq, now):
        self.engine, self.c, self.actor, self.packet = engine, conn, actor, packet
        self.tenant = packet['tenant_id']; self.seq, self.now = seq, now
        self.base = integer(packet['base']['commit_seq']) if packet.get('base') else None
        self.op = packet['operation_id']; self.epoch = integer(packet['authority_epoch'], 1)
        self.dirty = {}; self.original = {}; self.fields = {}; self.refresh = set()
        self.events = []; self.result = {}; self.changed = False; self.interaction_ids = set()

    def get(self, eid, live=True, kind=None):
        row = self.dirty.get(eid)
        if row is None:
            r=self.c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=?',(self.tenant,eid)).fetchone()
            if not r: raise Conflict('NOT_FOUND')
            row=dict(r)
        if live and (row['deleted_at'] is not None or row['merged_into_id'] is not None):
            raise Conflict('TOMBSTONED')
        if kind and row['entity_kind'] not in (kind if isinstance(kind,tuple) else (kind,)):
            raise Conflict('ENTITY_KIND')
        return row

    def facet(self, eid):
        row=self.get(eid,live=False); table,key=FACETS[row['entity_kind']]
        r=self.c.execute(f'SELECT * FROM {table} WHERE tenant_id=? AND {key}=?',(self.tenant,eid)).fetchone()
        if not r: raise CRMError('MISSING_FACET',exit_code=7)
        return dict(r)

    def depend(self, eid, fields=(), guards=()):
        self.get(eid)
        if self.base is None: raise Conflict('BASE_REQUIRED')
        first=self.c.execute('SELECT min(commit_seq) FROM entity_versions WHERE tenant_id=? AND entity_id=?',(self.tenant,eid)).fetchone()[0]
        if first is None or first>self.base: raise Conflict('ENTITY_NOT_AT_BASE')
        for name in set(fields)|{'deleted_at','merged_into_id'}:
            r=self.c.execute('SELECT v.commit_seq FROM field_revisions f JOIN entity_versions v ON v.tenant_id=f.tenant_id AND v.entity_id=f.entity_id AND v.entity_rev=f.field_rev WHERE f.tenant_id=? AND f.entity_id=? AND f.field_name=?',(self.tenant,eid,name)).fetchone()
            if r and r[0]>self.base: raise Conflict('FIELD_CONFLICT')
        for name in guards:
            r=self.c.execute('SELECT commit_seq FROM relation_guards WHERE tenant_id=? AND entity_id=? AND guard_name=?',(self.tenant,eid,name)).fetchone()
            if r and r[0]>self.base: raise Conflict('RELATION_CONFLICT')

    def edit(self,eid,fields=()):
        if eid not in self.dirty:
            row=self.get(eid); self.original[eid]=copy.deepcopy(row); self.dirty[eid]=dict(row)
        self.fields.setdefault(eid,set()).update(fields); self.refresh.add(eid)
        self.changed=True
        return self.dirty[eid]

    def insert(self,table,values):
        # table and keys originate exclusively from fixed handler code.
        cols=','.join(values); marks=','.join('?' for _ in values)
        self.c.execute(f'INSERT INTO {table}({cols}) VALUES({marks})',tuple(values.values()))

    def update_facet(self,eid,changes):
        table,key=FACETS[self.get(eid)['entity_kind']]
        self.edit(eid,changes)
        self.c.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in changes)+f' WHERE tenant_id=? AND {key}=?',(*changes.values(),self.tenant,eid))

    def guard(self,eid,name):
        self.c.execute('INSERT INTO relation_guards VALUES(?,?,?,1,?) ON CONFLICT(tenant_id,entity_id,guard_name) DO UPDATE SET guard_rev=guard_rev+1,commit_seq=excluded.commit_seq',(self.tenant,eid,name,self.seq))
        self.refresh.add(eid)

    def actor_exists(self,aid):
        if aid is not None and not self.c.execute('SELECT 1 FROM actors WHERE tenant_id=? AND actor_id=? AND disabled=0',(self.tenant,aid)).fetchone():
            raise Conflict('ACTOR_UNAVAILABLE')

    def artifact(self,aid):
        r=self.c.execute('SELECT * FROM artifacts WHERE tenant_id=? AND artifact_id=?',(self.tenant,aid)).fetchone()
        if not r: raise Conflict('ARTIFACT_NOT_REGISTERED')
        return dict(r)

    def add_event(self,kind,data,eid=None):
        self.events.append({'event_kind':kind,'entity_id':eid,'data':wire(data)})
        self.changed=True

    def snapshot(self,eid):
        core=dict(self.dirty.get(eid) or self.get(eid,live=False)); core.pop('state_digest',None)
        table,key=FACETS[core['entity_kind']]
        facet=dict(self.c.execute(f'SELECT * FROM {table} WHERE tenant_id=? AND {key}=?',(self.tenant,eid)).fetchone())
        aux={}
        for rel,k in [('entity_aliases','entity_id'),('contact_channels','patron_id'),('campaign_memberships','entity_id'),('entity_tags','entity_id'),('claims','resource_id')]:
            aux[rel]=[dict(r) for r in self.c.execute(f'SELECT * FROM {rel} WHERE tenant_id=? AND {k}=? ORDER BY rowid',(self.tenant,eid))]
        return wire({'entity':core,'facet':facet,'relations':aux})

    def persist_entities(self):
        for eid in sorted(self.dirty):
            row=self.dirty[eid]; old=self.original.get(eid)
            if old:
                row.update(entity_rev=old['entity_rev']+1,last_commit_seq=self.seq,mutation_epoch=self.epoch,updated_at=self.now,updated_by=self.actor.actor_id)
            snap=self.snapshot(eid); raw=jcs(snap)
            if len(raw)>24576: raise CRMError('ENTITY_SNAPSHOT_TOO_LARGE')
            row['state_digest']=digest(raw)
            if old:
                keys=[k for k in row if k not in ('tenant_id','entity_id','entity_kind')]
                self.c.execute('UPDATE entities SET '+','.join(k+'=?' for k in keys)+' WHERE tenant_id=? AND entity_id=?',(*(row[k] for k in keys),self.tenant,eid))
            # create row was provisionally inserted once, with correct digest computed below;
            # creation uses a placeholder digest derived before insert and is replaced via
            # the final insert at creation handler time, not an UPDATE revision bypass.
            else:
                # Entity row not inserted yet; facets use deferred foreign keys.
                self.insert('entities',row)
            self.insert('entity_versions',{'tenant_id':self.tenant,'entity_id':eid,'entity_rev':row['entity_rev'],'commit_seq':self.seq,'state_digest':row['state_digest'],'state_jcs':raw,'recorded_at':self.now})
            for name in self.fields.get(eid,set()):
                self.c.execute('INSERT INTO field_revisions VALUES(?,?,?,?) ON CONFLICT(tenant_id,entity_id,field_name) DO UPDATE SET field_rev=excluded.field_rev',(self.tenant,eid,name,row['entity_rev']))
            before=None
            if old:
                before=loads(self.c.execute('SELECT state_jcs FROM entity_versions WHERE tenant_id=? AND entity_id=? AND entity_rev=?',(self.tenant,eid,old['entity_rev'])).fetchone()[0],24576)
            self.events.append({'event_kind':'entity.revision','entity_id':eid,'prior_entity_rev':str(old['entity_rev']) if old else None,'new_entity_rev':str(row['entity_rev']),'before_digest':digest(before) if before else None,'after':snap,'changed_fields':sorted(self.fields.get(eid,set()))})

    def finish(self,disposition=None):
        from .search import refresh_entities, refresh_interactions
        from .projection import render
        self.persist_entities()
        # Invalidation fan-out is bounded; it is never deferred beyond the commit.
        for eid in tuple(self.refresh):
            row=self.get(eid,live=False)
            if row['entity_kind']=='organization':
                self.refresh.update(r[0] for r in self.c.execute('SELECT patron_id FROM patrons WHERE tenant_id=? AND organization_id=?',(self.tenant,eid)))
        if len(self.refresh)>25: raise CRMError('TOO_LARGE_FOR_ATOMIC_COMMAND')
        refresh_entities(self.c,self.tenant,self.refresh,self.seq)
        renamed={eid for eid, fields in self.fields.items() if set(fields)&{'display_name','deleted_at','merged_into_id'}}
        refresh_interactions(self.c,self.tenant,renamed,self.seq,ids=self.interaction_ids,limit=128)
        self.engine.fault('after_search')
        projections=[]
        for eid in sorted(self.refresh):
            tab,row=render(self.c,self.tenant,eid,self.seq)
            projections.append({'tab':tab,'entity_id':eid,'row':row})
        if not self.events: self.events=[{'event_kind':'command.outcome','entity_id':None}]
        # Projection after-images are separate frames, captured at commit: an older
        # batch can never accidentally display future, unreplicated canonical state.
        for p in projections:
            self.events.append({'event_kind':'projection.after','entity_id':p['entity_id'],'projection':p})
        disposition=disposition or ('COMMITTED' if self.changed else 'SATISFIED_NO_CHANGE')
        if len(self.events)>128: raise CRMError('EVENT_COUNT_LIMIT')
        outcome={'disposition':disposition,'operation_id':self.op,'commit_seq':str(self.seq),'data':wire(self.result)}
        prev=self.c.execute('SELECT head_digest FROM ledger_state').fetchone()[0]
        event_digests=[]; total=0
        for i,ev in enumerate(self.events):
            ev.update(ledger_id=self.packet['ledger_id'],tenant_id=self.tenant,commit_seq=str(self.seq),event_ordinal=str(i),event_count=str(len(self.events)),operation_id=self.op,actor_id=self.actor.actor_id,disposition=disposition,recorded_at=self.now)
            raw=jcs(ev)
            if len(raw)>24576: raise CRMError('AUDIT_EVENT_TOO_LARGE')
            h=digest(raw,'CRM3:event:v1'); event_digests.append(h); total+=len(raw)
            self.insert('audit_log',dict(tenant_id=self.tenant,commit_seq=self.seq,event_ordinal=i,event_kind=ev['event_kind'],entity_id=ev.get('entity_id'),prior_entity_rev=int(ev['prior_entity_rev']) if ev.get('prior_entity_rev') else None,new_entity_rev=int(ev['new_entity_rev']) if ev.get('new_entity_rev') else None,event_jcs=raw,event_digest=h))
        manifest={'ledger_id':self.packet['ledger_id'],'tenant_id':self.tenant,'commit_seq':str(self.seq),'operation_id':self.op,'event_count':str(len(self.events)),'previous_digest':prev,'event_digests':event_digests}
        raw=jcs(manifest); txdigest=digest(raw,'CRM3:transaction:v1')
        total+=len(raw)+len(jcs(outcome))
        # Conservative wire overhead reserve; final full request packing rechecks.
        if total*2+8192>262144: raise CRMError('TRANSACTION_PUBLICATION_TOO_LARGE')
        self.insert('operation_outcomes',dict(tenant_id=self.tenant,operation_id=self.op,semantic_digest=digest(self.packet),actor_id=self.actor.actor_id,command_type=self.packet['command_type'],disposition=disposition,commit_seq=self.seq,outcome_jcs=jcs(outcome),recorded_at=self.now))
        self.insert('audit_transactions',dict(tenant_id=self.tenant,commit_seq=self.seq,operation_id=self.op,authority_epoch=self.epoch,actor_id=self.actor.actor_id,event_count=len(self.events),previous_digest=prev,transaction_digest=txdigest,manifest_jcs=raw,recorded_at=self.now))
        self.engine.fault('before_outbox')
        self.insert('sync_outbox',dict(tenant_id=self.tenant,commit_seq=self.seq,encoded_bytes=total*2+8192,batch_id=None,state='QUEUED',created_at=self.now))
        self.c.execute('UPDATE ledger_state SET commit_seq=?,head_digest=? WHERE singleton=1',(self.seq,txdigest))
        self.engine.fault('before_commit')
        return outcome

class Engine:
    def __init__(self, db: Database, *, artifact_registry=None, currencies=('CAD','USD','EUR','GBP'), fencing_verifier=None, fault:Callable[[str],None]|None=None):
        self.db=db; self.vault=Vault(db.root/'evidence'); self.objects=Vault(db.root/'publications',2*1024*1024)
        self.artifact_registry=artifact_registry or {}; self.currencies=frozenset(currencies); self.fencing_verifier=fencing_verifier
        self.fault=fault or (lambda _:None)
        self._restart_holds()

    def _restart_holds(self):
        if getattr(self.db,'engine_attached',False):
            raise CRMError('ENGINE_ALREADY_ATTACHED',exit_code=7)
        self.db.engine_attached=True
        with self.db.transaction() as c:
            for r in c.execute("SELECT * FROM publication_batches WHERE state='IN_FLIGHT'").fetchall():
                c.execute("UPDATE publication_batches SET state='UNKNOWN' WHERE batch_id=?",(r['batch_id'],))
                c.execute('INSERT INTO delivery_events(tenant_id,batch_id,attempt_id,event_kind,recorded_at,reason_code) VALUES(?,?,?,?,?,?)',(r['tenant_id'],r['batch_id'],durable_id(c),'RESTART_UNKNOWN',utcnow(),'UNCERTAIN_PRIOR_SEND'))
            held=[r[0] for r in c.execute("SELECT resource_id FROM claims WHERE claim_state='HELD'")]
        for eid in held:
            with self.db.transaction() as c:
                s=dict(c.execute('SELECT * FROM ledger_state').fetchone())
                aid=c.execute("SELECT value FROM runtime_state WHERE key='system_actor_id'").fetchone()[0]
                actor=ActorContext(aid,frozenset())
                packet=dict(schema_version='crm.system.v1',operation_id=durable_id(c),tenant_id=s['tenant_id'],ledger_id=s['ledger_id'],authority_epoch=str(s['authority_epoch']),base={'commit_seq':str(s['commit_seq']),'transaction_digest':s['head_digest']},command_type='system.restart_hold',payload={'resource_id':eid})
                w=Work(self,c,actor,packet,s['commit_seq']+1,utcnow())
                c.execute("UPDATE claims SET claim_state='RECOVERY_HOLD',updated_commit_seq=? WHERE tenant_id=? AND resource_id=?",(w.seq,w.tenant,eid))
                w.edit(eid,('claim',));w.guard(eid,'claim');w.add_event('claim.restart_hold',{'resource_id':eid},eid);w.finish()

    def state(self):
        with self.db.read() as c: return dict(c.execute('SELECT * FROM ledger_state').fetchone())

    def base(self):
        s=self.state(); return {'commit_seq':str(s['commit_seq']),'transaction_digest':s['head_digest']}

    def packet(self,command_type,payload,operation_id=None,base='current'):
        # Trusted convenience for integrations; a caller retry must retain returned packet.
        from .ids import new_id
        s=self.state()
        return dict(schema_version=('crm.command.v6' if command_type=='entity.lww.set' else 'crm.command.v5' if command_type=='entity.tag.set' else 'crm.command.v4'),operation_id=operation_id or new_id(),tenant_id=s['tenant_id'],ledger_id=s['ledger_id'],authority_epoch=str(s['authority_epoch']),template_version='1',base=self.base() if base=='current' else base,command_type=command_type,payload=payload)

    def validate(self,packet):
        raw=jcs(packet)
        if len(raw)>65536: raise CRMError('COMMAND_TOO_LARGE')
        if packet.get('command_type')=='entity.lww.set':
            from .lamport import validate
            validate(packet,VALIDATOR)
        elif packet.get('command_type')=='entity.tag.set':
            # Explicit v5 additive command; all v4 commands retain their frozen schemas.
            shadow=copy.deepcopy(packet); shadow['schema_version']='crm.command.v4';shadow['command_type']='entity.patch';shadow['payload']={'entity_id':packet.get('payload',{}).get('entity_id'),'changes':{'note':''}}
            if not VALIDATOR.is_valid(shadow): raise CRMError('COMMAND_SCHEMA')
            p=packet['payload']
            if packet['schema_version']!='crm.command.v5' or set(p)!={'entity_id','tag','present'} or type(p['present']) is not bool:
                raise CRMError('COMMAND_SCHEMA')
            ulid(p['entity_id']); text(p['tag'],128)
            if not p['tag'] or p['tag']!=p['tag'].strip(): raise CRMError('INVALID_TAG')
        elif not VALIDATOR.is_valid(packet):
            raise CRMError('COMMAND_SCHEMA','Packet does not match the frozen typed command schema.')
        return packet

    def authorize(self,c,actor,cap):
        s=dict(c.execute('SELECT * FROM ledger_state').fetchone())
        r=c.execute('SELECT disabled FROM actors WHERE tenant_id=? AND actor_id=?',(s['tenant_id'],actor.actor_id)).fetchone()
        if not r or r[0] or cap not in actor.capabilities:
            raise CRMError('CAPABILITY_DENIED',exit_code=4)
        return s

    def check_capacity(self,c,s):
        if s['mode']!='NORMAL':raise CRMError('AUTHORITY_HOLD',exit_code=7)
        if s['commit_seq']>=MAX_I64:raise CRMError('SEQUENCE_EXHAUSTED',exit_code=7)
        pending=c.execute("SELECT coalesce(sum(encoded_bytes),0) FROM sync_outbox WHERE state!='VERIFIED'").fetchone()[0]
        if pending>=1024**3 or shutil.disk_usage(self.db.root).free<64*1024*1024:
            raise CRMError('CAPACITY_BACKPRESSURE',exit_code=10)

    def ingest(self,packet,actor:ActorContext,*,staging_receipt=None):
        if isinstance(packet,(str,bytes)): packet=loads(packet)
        self.validate(packet)
        cmd=packet['command_type']; cap=CAPS[cmd]
        with self.db.transaction() as c:
            s=self.authorize(c,actor,cap)
            if packet['tenant_id']!=s['tenant_id'] or packet['ledger_id']!=s['ledger_id']:
                raise CRMError('TENANT_OR_LEDGER_MISMATCH',exit_code=4)
            prior=c.execute('SELECT * FROM operation_outcomes WHERE tenant_id=? AND operation_id=?',(s['tenant_id'],packet['operation_id'])).fetchone()
            if prior:
                if prior['actor_id']!=actor.actor_id: raise CRMError('OUTCOME_ACTOR_MISMATCH',exit_code=4)
                if prior['semantic_digest']!=digest(packet): raise CRMError('OPERATION_ID_REUSED',exit_code=5)
                outcome=loads(prior['outcome_jcs'])
                self._staging_receipt(c,s['tenant_id'],staging_receipt,packet['operation_id'],'DUPLICATE')
                return outcome
            self.check_capacity(c,s)
            c.execute('SAVEPOINT domain')
            w=Work(self,c,actor,packet,s['commit_seq']+1,utcnow())
            try:
                if integer(packet['authority_epoch'],1)!=s['authority_epoch']: raise Conflict('AUTHORITY_EPOCH')
                b=packet['base']
                if b is not None:
                    n=integer(b['commit_seq']); r=c.execute('SELECT transaction_digest FROM audit_transactions WHERE tenant_id=? AND commit_seq=?',(s['tenant_id'],n)).fetchone()
                    expected=ZERO if n==0 else (r[0] if r else None)
                    if n>s['commit_seq'] or expected!=b['transaction_digest']: raise Conflict('BASE_UNAVAILABLE')
                elif cmd!='entity.create': raise Conflict('BASE_REQUIRED')
                from .entities import dispatch
                if cmd=='entity.lww.set':
                    from .lamport import apply
                    apply(w,packet['payload'])
                else:dispatch(w,cmd,packet['payload'])
                self.fault('after_domain')
                result=w.finish()
                c.execute('RELEASE domain')
                self._staging_receipt(c,s['tenant_id'],staging_receipt,packet['operation_id'],'CAPTURED')
                return result
            except (Conflict,sqlite3.IntegrityError) as exc:
                if isinstance(exc,sqlite3.IntegrityError): exc=Conflict('RELATIONAL_CONSTRAINT')
                c.execute('ROLLBACK TO domain'); c.execute('RELEASE domain')
                w=Work(self,c,actor,packet,s['commit_seq']+1,utcnow())
                # Keep potentially poisoned proposed bytes outside audit/search/SQL.
                ref,size=self.vault.put(jcs(packet))
                from .quarantine import record_observation
                record_observation(w,source='command',resource=packet['operation_id'],entity=None,field=None,ref=ref,size=size,value_kind='command',reason=exc.code,base=w.base)
                w.result={'code':exc.code,'proposal_id':w.result['proposal_id']}
                result=w.finish('CONFLICT')
                self._staging_receipt(c,s['tenant_id'],staging_receipt,packet['operation_id'],'CAPTURED')
                return result

    @staticmethod
    def _staging_receipt(c,tenant,receipt,operation_id,disposition):
        if receipt is None:return
        c.execute('INSERT INTO staging_receipts VALUES(?,?,?,?,?,?,?)',(tenant,receipt['file_id'],receipt['content_digest'],receipt['delivery_id'],operation_id,disposition,utcnow()))

    def verify_audit(self):
        return verify_chain(self.db)

def verify_chain(db):
    with db.read() as c:
        tenant=c.execute('SELECT tenant_id FROM ledger_state').fetchone()[0]
        prev=ZERO; seq=0
        for tx in c.execute('SELECT * FROM audit_transactions WHERE tenant_id=? ORDER BY commit_seq',(tenant,)):
            seq+=1
            if tx['commit_seq']!=seq or tx['previous_digest']!=prev: raise CRMError('AUDIT_CHAIN',exit_code=7)
            m=loads(tx['manifest_jcs']); hs=[]
            for i,ev in enumerate(c.execute('SELECT * FROM audit_log WHERE tenant_id=? AND commit_seq=? ORDER BY event_ordinal',(tenant,seq))):
                h=digest(ev['event_jcs'],'CRM3:event:v1')
                if i!=ev['event_ordinal'] or h!=ev['event_digest']: raise CRMError('AUDIT_EVENT',exit_code=7)
                hs.append(h)
            if hs!=m['event_digests'] or len(hs)!=tx['event_count'] or digest(tx['manifest_jcs'],'CRM3:transaction:v1')!=tx['transaction_digest']: raise CRMError('AUDIT_MANIFEST',exit_code=7)
            prev=tx['transaction_digest']
        state=c.execute('SELECT commit_seq,head_digest FROM ledger_state').fetchone()
        if tuple(state)!=(seq,prev): raise CRMError('AUDIT_HEAD',exit_code=7)
        if c.execute('PRAGMA foreign_key_check').fetchone(): raise CRMError('FOREIGN_KEY_CHECK',exit_code=7)
        return {'transactions':str(seq),'head_digest':prev,'verified':True}
