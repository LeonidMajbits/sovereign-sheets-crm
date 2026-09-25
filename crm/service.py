"""Authenticated local broker boundary; embeds into the lab's existing runtime.

The optional reference Unix-socket host is explicitly started by an operator.
The CLI NEVER starts it, opens crm.db, or receives Google credentials.
"""
from __future__ import annotations
import base64,hashlib,hmac,json,os,secrets,socketserver,threading,time
from pathlib import Path
from .codec import jcs,loads,mac,utcnow,timestamp,integer,normalize_name,ULID_RE
from .errors import CRMError,Conflict
from .engine import ActorContext,ALL_CAPS
from .model import FACETS,wire
from .search import search
from .quarantine import list_proposals
from .ids import new_id,durable_id

class Broker:
    def __init__(self,engine,*,publisher=None,inbox=None,cursor_key:bytes):
        if len(cursor_key)<32:raise CRMError('CURSOR_KEY',exit_code=4)
        self.engine=engine;self.db=engine.db;self.publisher=publisher;self.inbox=inbox;self.cursor_key=cursor_key

    def sync_status(self,c):
        r=c.execute("SELECT published_commit_seq FROM projection_resources WHERE state='ACTIVE'").fetchone()
        n=c.execute("SELECT count(*) FROM sync_outbox WHERE state!='VERIFIED'").fetchone()[0]
        unknown=c.execute("SELECT 1 FROM publication_batches WHERE state IN ('UNKNOWN','IN_FLIGHT','QUARANTINED_PUBLICATION') LIMIT 1").fetchone()
        return {'state':'UNKNOWN' if unknown else 'PENDING' if n else 'CURRENT','published_commit_seq':str(r[0]) if r else None,'pending_transactions':str(n)}

    def result(self,command,data=None,*,error=None,operation_id=None,outcome='READ_COMPLETE',ok=True,observed=None):
        if observed is None:
            with self.db.read() as c:
                s=dict(c.execute('SELECT * FROM ledger_state').fetchone());sync=self.sync_status(c)
        else:
            s,sync=observed
        return {'schema_version':'crm.result.v4','command':command,'ok':ok,'outcome':outcome,'error':error,'tenant_id':s['tenant_id'],'ledger_id':s['ledger_id'],'operation_id':operation_id,'as_of_commit_seq':str(s['commit_seq']),'data':wire(data),'sync':sync,'next_cursor':None}

    def _cursor(self,obj):
        payload=jcs(obj);sig=hmac.new(self.cursor_key,b'CRM5:cursor:v1\n'+payload,hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload+b'.'+sig).decode()

    def _parse_cursor(self,value):
        try:
            data=base64.urlsafe_b64decode(value.encode());raw=data[:-33];sig=data[-32:]
            if data[-33:-32]!=b'.' or not hmac.compare_digest(sig,hmac.new(self.cursor_key,b'CRM5:cursor:v1\n'+raw,hashlib.sha256).digest()):raise ValueError()
            return loads(raw,4096)
        except Exception as exc:raise Conflict('INVALID_CURSOR') from exc

    def list(self,actor,args):
        allowed={'campaign','status','kind','limit','cursor'}
        if set(args)-allowed:raise CRMError('UNKNOWN_ARGUMENT')
        limit=args.get('limit',50)
        if type(limit) is not int or not 1<=limit<=200:raise CRMError('LIMIT')
        filters={k:args.get(k) for k in ('campaign','status','kind')};after=None;next_cursor=None
        with self.db.read() as c:
            s=self.engine.authorize(c,actor,'read');tenant=s['tenant_id']
            if filters['kind'] and filters['kind'] not in FACETS:raise CRMError('ENTITY_KIND')
            statuses=json.loads((Path(__file__).resolve().parent.parent/'schema/entity_kinds_and_statuses.json').read_text())['kind_statuses']
            valid=set(statuses[filters['kind']]) if filters['kind'] else {x for a in statuses.values() for x in a}
            if filters['status'] and filters['status'] not in valid:raise CRMError('STATUS_FOR_KIND')
            if filters['campaign']:
                if not ULID_RE.fullmatch(filters['campaign']) or not c.execute('SELECT 1 FROM campaigns WHERE tenant_id=? AND campaign_id=?',(tenant,filters['campaign'])).fetchone():raise Conflict('CAMPAIGN_NOT_FOUND')
            identity={'tenant_id':tenant,'ledger_id':s['ledger_id'],'commit_seq':str(s['commit_seq']),'filters':filters,'limit':limit}
            if args.get('cursor'):
                old=self._parse_cursor(args['cursor'])
                if any(old.get(k)!=v for k,v in identity.items()):raise Conflict('CURSOR_STALE')
                after=old['last']
            sql='SELECT e.* FROM entities e WHERE e.tenant_id=? AND e.deleted_at IS NULL';params=[tenant]
            if filters['kind']:sql+=' AND e.entity_kind=?';params.append(filters['kind'])
            if filters['status']:sql+=' AND e.status=?';params.append(filters['status'])
            if filters['campaign']:sql+=' AND EXISTS(SELECT 1 FROM campaign_memberships m WHERE m.tenant_id=e.tenant_id AND m.entity_id=e.entity_id AND m.campaign_id=?)';params.append(filters['campaign'])
            if after:sql+=' AND (e.entity_kind>? OR (e.entity_kind=? AND e.entity_id>?))';params.extend([after[0],after[0],after[1]])
            sql+=' ORDER BY e.entity_kind,e.entity_id LIMIT ?';params.append(limit+1)
            rows=[dict(r) for r in c.execute(sql,params)]
            if len(rows)>limit:
                rows=rows[:limit];next_cursor=self._cursor(dict(identity,last=[rows[-1]['entity_kind'],rows[-1]['entity_id']]))
            observed=(dict(s),self.sync_status(c))
        result=self.result('list',rows,observed=observed);result['next_cursor']=next_cursor;return result,0

    def get(self,actor,value):
        with self.db.read() as c:
            s=self.engine.authorize(c,actor,'read');tenant=s['tenant_id']
            r=c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,value)).fetchone()
            if not r:
                ids={x[0] for x in c.execute("SELECT entity_id FROM entity_aliases WHERE tenant_id=? AND normalizer_version='nfkc-casefold-ws-v1' AND normalized_key=? AND retired_at IS NULL",(tenant,normalize_name(value)))}
                ids.update(x[0] for x in c.execute('SELECT entity_id FROM legacy_identifiers WHERE tenant_id=? AND original_value=?',(tenant,value)))
                if len(ids)>1:raise Conflict('AMBIGUOUS_ALIAS')
                if ids:r=c.execute('SELECT * FROM entities WHERE tenant_id=? AND entity_id=?',(tenant,next(iter(ids)))).fetchone()
            if not r:raise Conflict('NOT_FOUND')
            table,key=FACETS[r['entity_kind']]
            facet=dict(c.execute(f'SELECT * FROM {table} WHERE tenant_id=? AND {key}=?',(tenant,r['entity_id'])).fetchone())
            fields={f[0]:str(f[1]) for f in c.execute('SELECT field_name,field_rev FROM field_revisions WHERE tenant_id=? AND entity_id=?',(tenant,r['entity_id']))}
            guards={f[0]:{'revision':str(f[1]),'commit_seq':str(f[2])} for f in c.execute('SELECT guard_name,guard_rev,commit_seq FROM relation_guards WHERE tenant_id=? AND entity_id=?',(tenant,r['entity_id']))}
            data={'entity':dict(r),'facet':facet,'field_revisions':fields,'relation_guards':guards,'base':{'commit_seq':str(s['commit_seq']),'transaction_digest':s['head_digest']}}
            observed=(dict(s),self.sync_status(c))
        return self.result('get',data,observed=observed),0

    def resolve(self,actor,args):
        if set(args)-{'id','accept','reject','operation_id'} or bool(args.get('accept'))==bool(args.get('reject')):raise CRMError('RESOLUTION_ARGUMENTS')
        decision='ADOPT' if args.get('accept') else 'REJECT';pid=args['id']
        # Persist the exact first intentional adoption command before sending it to
        # the engine. Repeated convenience invocations do NOT silently renew base.
        key='resolution:'+actor.actor_id+':'+pid+':'+decision+':'+args.get('operation_id','default')
        with self.db.transaction() as c:
            s=self.engine.authorize(c,actor,'resolve_observation')
            old=c.execute('SELECT value FROM runtime_state WHERE key=?',(key,)).fetchone()
            if old:packet=loads(old[0])
            else:
                head=c.execute('SELECT selection_rev FROM observation_heads WHERE tenant_id=? AND proposal_id=?',(s['tenant_id'],pid)).fetchone()
                if not head:raise Conflict('PROPOSAL_NOT_CURRENT')
                op=args.get('operation_id') or durable_id(c)
                packet={'schema_version':'crm.command.v4','operation_id':op,'tenant_id':s['tenant_id'],'ledger_id':s['ledger_id'],'authority_epoch':str(s['authority_epoch']),'template_version':'1','base':{'commit_seq':str(s['commit_seq']),'transaction_digest':s['head_digest']},'command_type':'observation.resolve','payload':{'proposal_id':pid,'selection_revision':str(head[0]),'decision':decision,'reason':'Explicit authenticated CLI resolution'}}
                self.engine.validate(packet)
                c.execute('INSERT INTO runtime_state VALUES(?,?)',(key,jcs(packet).decode()))
        outcome=self.engine.ingest(packet,actor);ok=outcome['disposition']!='CONFLICT'
        return self.result('proposals.resolve',outcome,operation_id=packet['operation_id'],outcome=outcome['disposition'],ok=ok,error=None if ok else {'code':'CONFLICT','retryable':False,'message':'Inspect retained conflict; an explicit new operation is required to rebase.'}),0 if ok else 5

    def handle(self,actor:ActorContext,action,args):
        try:
            if not isinstance(args,dict):raise CRMError('ARGUMENT_TYPE')
            if action=='list':return self.list(actor,args)
            if action in ('get','show'):
                if set(args)!={'id'}:raise CRMError('ARGUMENTS')
                return self.get(actor,args['id'])
            if action=='ingest':
                if set(args)!={'packet'}:raise CRMError('ARGUMENTS')
                outcome=self.engine.ingest(args['packet'],actor);ok=outcome['disposition']!='CONFLICT'
                result=self.result('ingest',outcome,operation_id=outcome['operation_id'],outcome=outcome['disposition'],ok=ok,error=None if ok else {'code':outcome['data'].get('code','CONFLICT'),'retryable':False,'message':'Mutation not applied; conflict evidence retained.'})
                return result,0 if ok else 5
            if action in ('search','query'):
                if set(args)-{'query','scope','limit','fuzzy'} or 'query' not in args:raise CRMError('ARGUMENTS')
                with self.db.read() as c:
                    s=self.engine.authorize(c,actor,'query');data=search(c,s['tenant_id'],args['query'],scope=args.get('scope','entities'),limit=args.get('limit',20),fuzzy=args.get('fuzzy',False))
                    observed=(dict(s),self.sync_status(c))
                return self.result(action,data,observed=observed),0
            if action=='proposals.list':
                with self.db.read() as c:
                    s=self.engine.authorize(c,actor,'read');data=list_proposals(c,s['tenant_id'],args.get('limit',50));observed=(dict(s),self.sync_status(c))
                return self.result(action,data,observed=observed),0
            if action=='proposals.resolve':return self.resolve(actor,args)
            if action=='sync':
                if set(args)-{'mode'}:raise CRMError('ARGUMENTS')
                with self.db.read() as c:self.engine.authorize(c,actor,'sync')
                mode=args.get('mode','both')
                if not self.publisher:
                    if mode=='dry-run':
                        with self.db.read() as c:data=self.sync_status(c)
                        return self.result(action,{'plan':data,'network_used':False,'cloud_configured':False}),0
                    raise CRMError('CLOUD_NOT_CONFIGURED',exit_code=10)
                if self.inbox and mode in ('pull','both'):self.inbox.consume()
                data=self.publisher.run(actor,mode)
                if mode in ('dry-run','pull'):return self.result(action,data),0
                pending=int(data.get('plan',{}).get('pending_transactions','0'))
                return self.result(action,data,outcome='SYNC_PENDING' if pending else 'SYNC_VERIFIED',ok=not pending,error={'code':'PENDING','retryable':True,'message':'Entry target has remaining durable work.'} if pending else None),10 if pending else 0
            if action=='health':
                with self.db.read() as c:
                    s=self.engine.authorize(c,actor,'read');data={'runtime_version':__import__('sqlite3').sqlite_version,'authority_mode':s['mode'],'authority_epoch':str(s['authority_epoch']),'base':{'commit_seq':str(s['commit_seq']),'transaction_digest':s['head_digest']},'cloud_configured':self.publisher is not None,'live_cloud_certified':False};observed=(dict(s),self.sync_status(c))
                return self.result(action,data,observed=observed),0
            if action=='audit':
                with self.db.read() as c:
                    s=self.engine.authorize(c,actor,'read');r=c.execute('SELECT actor_id,outcome_jcs FROM operation_outcomes WHERE tenant_id=? AND operation_id=?',(s['tenant_id'],args['operation_id'])).fetchone()
                    if not r:raise Conflict('NOT_FOUND')
                    if r[0]!=actor.actor_id and 'audit.read' not in actor.capabilities:raise CRMError('CAPABILITY_DENIED',exit_code=4)
                    data=loads(r[1]);observed=(dict(s),self.sync_status(c))
                return self.result(action,data,observed=observed),0
            raise CRMError('UNKNOWN_COMMAND',exit_code=8)
        except CRMError as exc:
            return self.result(action,error={'code':exc.code,'retryable':exc.retryable,'message':str(exc)},outcome=exc.code,ok=False),exc.exit_code
        except OSError:
            return self.result(action,error={'code':'LOCAL_IO','retryable':False,'message':'Local storage or socket operation failed.'},outcome='LOCAL_IO',ok=False),11
        except Exception:
            # Do not leak SQL contents, quarantine, filesystem secrets or stack traces to callers.
            return self.result(action,error={'code':'INTERNAL_INTEGRITY','retryable':False,'message':'Unexpected internal error; transaction rolled back or outcome requires inspection.'},outcome='INTERNAL_INTEGRITY',ok=False),7

class LocalAuthenticator:
    def __init__(self,principals):
        self.principals=principals;self.seen={};self.lock=threading.Lock()
    def authenticate(self,env):
        required={'protocol','key_id','nonce','issued_at','action','args','mac'}
        if not isinstance(env,dict) or set(env)!=required or env['protocol']!='crm.local.v1':raise CRMError('LOCAL_ENVELOPE',exit_code=4)
        record=self.principals.get(env['key_id'])
        if not record:raise CRMError('LOCAL_AUTH',exit_code=4)
        body={k:v for k,v in env.items() if k!='mac'};key=bytes.fromhex(record['key_hex'])
        if not isinstance(env['mac'],str) or not hmac.compare_digest(env['mac'],mac(key,body,'CRM5:local-request:v1')):raise CRMError('LOCAL_AUTH',exit_code=4)
        timestamp(env['issued_at']);from datetime import datetime
        issued=datetime.fromisoformat(env['issued_at'].replace('Z','+00:00')).timestamp();now=time.time()
        if abs(now-issued)>60 or not isinstance(env['nonce'],str) or len(env['nonce'])!=64 or any(x not in '0123456789abcdef' for x in env['nonce']):raise CRMError('LOCAL_EXPIRED',exit_code=4)
        with self.lock:
            self.seen={k:v for k,v in self.seen.items() if now-v<120}
            ident=(env['key_id'],env['nonce'])
            if ident in self.seen:raise CRMError('LOCAL_REPLAY',exit_code=4)
            if len(self.seen)>=4096:raise CRMError('LOCAL_ADMISSION_BUSY',exit_code=6)
            self.seen[ident]=now
        return ActorContext(record['actor_id'],frozenset(record['capabilities'])),key

class UnixBrokerServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True;request_queue_size=128
    def __init__(self,path,broker,principals):
        self.broker=broker;self.auth=LocalAuthenticator(principals);self.gate=threading.BoundedSemaphore(32)
        # Never unlink an existing socket: it could belong to a live runtime.
        if os.path.lexists(path):raise CRMError('SOCKET_EXISTS',exit_code=7)
        super().__init__(str(path),RPCHandler);os.chmod(path,0o600)

class RPCHandler(socketserver.StreamRequestHandler):
    def handle(self):
        if not self.server.gate.acquire(False):return
        try:
            self.request.settimeout(120)
            raw=self.rfile.readline(131073)
            if not raw.endswith(b'\n') or len(raw)>131072:return
            env=loads(raw,131072)
            actor,key=self.server.auth.authenticate(env)
            result,exitcode=self.server.broker.handle(actor,env['action'],env['args'])
            response={'protocol':'crm.local.result.v1','nonce':env['nonce'],'exit_code':exitcode,'result':result}
            response['mac']=mac(key,response,'CRM5:local-result:v1')
            self.wfile.write(jcs(response)+b'\n');self.wfile.flush()
        except Exception:
            # Unauthenticated peers receive no internal result or prior-operation data.
            return
        finally:self.server.gate.release()
