"""Single-owner, exact-byte outbox publication and bounded typed reconciliation.

The transport is injected, enabling real REST and fault-controlled integration
fixtures through the same planner. UNKNOWN is read-reconciled, never resent.
"""
from __future__ import annotations
import copy,json,threading
from .codec import jcs,loads,digest,utcnow,safe_cell,ZERO
from .errors import CRMError
from .ids import durable_id,new_id
from .projection import HEADERS,TABKEY,LAYOUT_DIGEST,row_digest
from .google_api import NotApplied,Ambiguous
from .quarantine import capture

LIMIT_BYTES=524288


def entered(cell):
    value=cell.get('userEnteredValue') or {}
    if value=={} and not cell.get('effectiveValue'):return ''
    if set(value)=={'stringValue'} and not any(k in cell for k in ('dataSourceFormula','dataSourceTable','pivotTable','chipRuns','textFormatRuns')):
        return value['stringValue']
    return None


def update(sid,row,col,values):
    return {'updateCells':{'start':{'sheetId':sid,'rowIndex':row-1,'columnIndex':col},'rows':[{'values':[safe_cell(str(v)) for v in line]} for line in values], 'fields':'userEnteredValue,userEnteredFormat.numberFormat'}}


def expected_cells(request):
    result={}
    for op in request['requests']:
        u=op.get('updateCells')
        if not u:continue
        start=u['start']
        for dr,r in enumerate(u['rows']):
            for dc,cell in enumerate(r['values']):result[(start['sheetId'],start['rowIndex']+dr+1,start.get('columnIndex',0)+dc)]=cell['userEnteredValue']['stringValue']
    return result


def request_ranges(request):
    out=[]
    for op in request['requests']:
        u=op.get('updateCells')
        if u:out.append((u['start']['sheetId'],u['start']['rowIndex']+1,u['start'].get('columnIndex',0),len(u['rows']),max(len(r['values']) for r in u['rows'])))
    return out

class Publisher:
    def __init__(self,engine,transport,scheduler,config):
        self.engine=engine;self.db=engine.db;self.transport=transport;self.scheduler=scheduler
        self.config=copy.deepcopy(config);self.lock=threading.Lock()
        required={'spreadsheet_id','generation_id','sheet_ids'}
        if not required<=set(config) or set(config['sheet_ids'])!=set(HEADERS):raise CRMError('CLOUD_CONFIG')
        if len(set(config['sheet_ids'].values()))!=5 or any(type(x) is not int or x<0 for x in config['sheet_ids'].values()):raise CRMError('SHEET_ID_CONFIG')
        if transport.spreadsheet_id!=config['spreadsheet_id'] or transport.sheet_ids!=config['sheet_ids']:raise CRMError('TRANSPORT_PIN_MISMATCH',exit_code=7)

    def validate_layout(self):
        meta=self.transport.metadata()
        ranges=[(self.config['sheet_ids'][name],1,0,1,len(headers)) for name,headers in HEADERS.items()]
        cells=self.transport.read(ranges)
        for name,headers in HEADERS.items():
            sid=self.config['sheet_ids'][name]
            if meta[sid]['columns']<len(headers):raise CRMError('LAYOUT_HOLD',exit_code=7)
            for i,h in enumerate(headers):
                if entered(cells.get((sid,1,i),{}))!=h:raise CRMError('LAYOUT_HOLD',exit_code=7)
        return meta

    def activate(self):
        """Explicit administrator step; verifies already-provisioned literal headers.
        Never creates/replaces a workbook, renames tabs, or rewrites existing content.
        """
        self.validate_layout()
        sid=self.config['sheet_ids']['_Control']
        control=self.transport.read([(sid,2,0,1,len(HEADERS['_Control']))])
        with self.db.transaction() as c:
            s=c.execute('SELECT * FROM ledger_state').fetchone()
            existing=c.execute("SELECT * FROM projection_resources WHERE tenant_id=? AND state='ACTIVE'",(s['tenant_id'],)).fetchone()
            if existing:
                if existing['generation_id']!=self.config['generation_id'] or existing['spreadsheet_id']!=self.config['spreadsheet_id']:raise CRMError('ACTIVE_PROJECTION_EXISTS',exit_code=7)
                return
            if any(entered(control.get((sid,2,i),{}))!='' for i in range(len(HEADERS['_Control']))):raise CRMError('NONEMPTY_CONTROL_REQUIRES_RECONCILIATION',exit_code=7)
            if c.execute('SELECT 1 FROM sync_outbox WHERE state!=\'QUEUED\'').fetchone():raise CRMError('PRIOR_PUBLICATION_REQUIRES_RECOVERY',exit_code=7)
            c.execute('INSERT INTO projection_resources VALUES(?,?,?,?,?,0,2,?)',(s['tenant_id'],self.config['generation_id'],self.config['spreadsheet_id'],'ACTIVE',LAYOUT_DIGEST,utcnow()))
            c.execute('INSERT INTO runtime_state VALUES(?,?)',('cloud_config',jcs(self.config).decode()))

    def plan(self):
        with self.db.read() as c:
            counts=c.execute("SELECT count(*),coalesce(sum(encoded_bytes),0),min(commit_seq),max(commit_seq) FROM sync_outbox WHERE state!='VERIFIED'").fetchone()
            pending=[dict(r) for r in c.execute("SELECT batch_id,state,first_commit_seq,last_commit_seq,business_rows,payload_bytes FROM publication_batches WHERE state!='VERIFIED' ORDER BY first_commit_seq LIMIT 10")]
            return {'pending_transactions':str(counts[0]),'estimated_bytes':str(counts[1]),'first_commit_seq':str(counts[2]) if counts[2] is not None else None,'target_commit_seq':str(counts[3]) if counts[3] is not None else None,'batches':pending,'network_used':False,'cloud_facts':'last_verified_only'}

    def _make(self,c,txs,batchid,resource,meta):
        tenant=resource['tenant_id'];gen=resource['generation_id'];sidmap=self.config['sheet_ids']
        latest={};frames=[];assignments=[];retirements=[]
        for tx in txs:
            manifest=loads(tx['manifest_jcs'],24576)
            frames.append(['TRANSACTION',self.engine._sync_ledger,tenant,gen,str(tx['commit_seq']),'',str(tx['event_count']),tx['operation_id'],jcs(manifest).decode(),tx['transaction_digest'],tx['previous_digest'],batchid])
            for ev in c.execute('SELECT * FROM audit_log WHERE tenant_id=? AND commit_seq=? ORDER BY event_ordinal',(tenant,tx['commit_seq'])):
                data=loads(ev['event_jcs'],24576)
                if digest(ev['event_jcs'],'CRM3:event:v1')!=ev['event_digest']:raise CRMError('AUDIT_CORRUPT',exit_code=7)
                frames.append(['EVENT',self.engine._sync_ledger,tenant,gen,str(tx['commit_seq']),str(ev['event_ordinal']),str(tx['event_count']),tx['operation_id'],ev['event_jcs'].decode(),ev['event_digest'],'',batchid])
                if data['event_kind']=='projection.after':latest[data['entity_id']]=data['projection']
        nextrows={sid:max(2,c.execute('SELECT coalesce(max(row_index),1)+1 FROM projection_slots WHERE generation_id=? AND sheet_id=?',(gen,sid)).fetchone()[0]) for name,sid in sidmap.items() if name in TABKEY}
        requests=[];physical=set();business=[]
        for eid,p in sorted(latest.items()):
            name=p['tab'];sid=sidmap[name];key=TABKEY[name]
            previous=c.execute('SELECT * FROM projection_rows WHERE tenant_id=? AND generation_id=? AND entity_id=?',(tenant,gen,eid)).fetchall()
            same=None
            for old in previous:
                active=c.execute('SELECT retired FROM projection_slots WHERE generation_id=? AND sheet_id=? AND row_index=?',(gen,old['sheet_id'],old['row_index'])).fetchone()
                if not active or active[0]:continue
                if old['tab_key']==key:same=old
                else:
                    if old['tab_key']=='directory':raise CRMError('DIRECTORY_MOVE_PROHIBITED',exit_code=7)
                    oldname=next(k for k,v in TABKEY.items() if v==old['tab_key'])
                    vals=['']*len(HEADERS[oldname]);requests.append(update(old['sheet_id'],old['row_index'],0,[vals]));physical.add((old['sheet_id'],old['row_index']));business.append([old['sheet_id'],old['row_index'],oldname,True])
                    retirements.append([old['sheet_id'],old['row_index']])
            rindex=same['row_index'] if same else nextrows[sid]
            if not same:nextrows[sid]+=1
            row=dict(p['row']);row['generation_id']=gen;row['record_digest']=row_digest(row)
            vals=[row.get(h,'') for h in HEADERS[name]]
            if name=='Directory':
                requests.append(update(sid,rindex,0,[vals[:27]]));requests.append(update(sid,rindex,29,[vals[29:]]))
            else:requests.append(update(sid,rindex,0,[vals]))
            physical.add((sid,rindex));business.append([sid,rindex,name,False])
            assignments.append({'entity_id':eid,'tab_key':key,'sheet_id':sid,'row_index':rindex,'projection_seq':int(row['projection_seq']),'row_digest':row['record_digest']})
        if len(physical)>50:raise CRMError('BATCH_ROW_LIMIT')
        start=resource['change_next_row'];receiptrow=start+len(frames);changes=sidmap['_Changes']
        if frames:requests.append(update(changes,start,0,frames))
        state=c.execute('SELECT * FROM ledger_state').fetchone();last=txs[-1]
        remaining=c.execute('SELECT count(*),coalesce(sum(encoded_bytes),0),min(created_at) FROM sync_outbox WHERE commit_seq>? AND state!=\'VERIFIED\'',(last['commit_seq'],)).fetchone()
        control=[state['ledger_id'],tenant,'4','crm.protocol.v4',gen,LAYOUT_DIGEST,str(last['commit_seq']),last['transaction_digest'],'1','','',utcnow(),'PENDING' if remaining[0] else 'HEALTHY',str(remaining[0]),str(remaining[1]),remaining[2] or '',str(nextrows[sidmap['Directory']]),str(nextrows[sidmap['Active Pipeline']]),str(nextrows[sidmap['Completed Archives']]),str(receiptrow+1)]
        requests.append(update(sidmap['_Control'],2,0,[control]))
        needed={sid:2 for sid in sidmap.values()};needed[changes]=receiptrow
        for sid,rindex,_,_ in business:needed[sid]=max(needed[sid],rindex)
        growth=[]
        for sid,n in needed.items():
            if n>meta[sid]['rows']:growth.append({'appendDimension':{'sheetId':sid,'dimension':'ROWS','length':n-meta[sid]['rows']}})
        core={'requests':growth+requests}
        receipt={'batch_id':batchid,'generation_id':gen,'first_commit_seq':str(txs[0]['commit_seq']),'last_commit_seq':str(last['commit_seq']),'projection_body_digest':digest(core)}
        rframe=['BATCH_RECEIPT',state['ledger_id'],tenant,gen,str(last['commit_seq']),'','','',jcs(receipt).decode(),digest(receipt,'CRM4:batch-receipt:v1'),'',batchid]
        request={'requests':growth+requests+[update(changes,receiptrow,0,[rframe])]}
        raw=jcs(request)
        if len(raw)>LIMIT_BYTES:raise CRMError('BATCH_BYTE_LIMIT')
        return {'request':request,'assignments':assignments,'retirements':retirements,'business':business,'receipt_row':receiptrow,'last_commit_seq':last['commit_seq'],'first_commit_seq':txs[0]['commit_seq'],'physical_rows':len(physical),'payload_digest':digest(raw),'payload_bytes':len(raw),'next_change_row':receiptrow+1}

    def prepare(self,meta):
        with self.db.transaction() as c:
            old=c.execute("SELECT * FROM publication_batches WHERE state!='VERIFIED' ORDER BY first_commit_seq LIMIT 1").fetchone()
            if old:return dict(old)
            s=c.execute('SELECT * FROM ledger_state').fetchone();self.engine._sync_ledger=s['ledger_id']
            r=c.execute("SELECT * FROM projection_resources WHERE tenant_id=? AND state='ACTIVE'",(s['tenant_id'],)).fetchone()
            if not r or r['generation_id']!=self.config['generation_id']:raise CRMError('PROJECTION_NOT_ACTIVE',exit_code=7)
            txs=c.execute("SELECT t.* FROM sync_outbox o JOIN audit_transactions t ON t.tenant_id=o.tenant_id AND t.commit_seq=o.commit_seq WHERE o.tenant_id=? AND o.state='QUEUED' ORDER BY o.commit_seq LIMIT 50",(s['tenant_id'],)).fetchall()
            if not txs:return None
            if txs[0]['commit_seq']!=r['published_commit_seq']+1:raise CRMError('OUTBOX_GAP',exit_code=7)
            if any(b['commit_seq']!=a['commit_seq']+1 for a,b in zip(txs,txs[1:])):
                raise CRMError('OUTBOX_GAP',exit_code=7)
            bid=durable_id(c);best=None
            # Build the full bounded candidate once; do not re-serialize prefixes
            # 1,2,...,50. If too large, find a safe smaller prefix. Coalescing can
            # make cost nonmonotone, so this seeks a VALID prefix, not a claim of
            # globally optimal packing. Every chosen request is checked exactly.
            try:best=self._make(c,txs,bid,r,meta)
            except CRMError as exc:
                if exc.code not in ('BATCH_ROW_LIMIT','BATCH_BYTE_LIMIT'):raise
                lo,hi=1,len(txs)-1
                while lo<=hi:
                    mid=(lo+hi)//2
                    try:
                        candidate=self._make(c,txs[:mid],bid,r,meta);best=candidate;lo=mid+1
                    except CRMError as smaller:
                        if smaller.code not in ('BATCH_ROW_LIMIT','BATCH_BYTE_LIMIT'):raise
                        hi=mid-1
                if best is None:raise CRMError('INDIVISIBLE_PUBLICATION_TOO_LARGE',exit_code=7)
            ref,_=self.engine.objects.put(jcs(best))
            for a in best['assignments']:
                c.execute('INSERT OR IGNORE INTO projection_slots VALUES(?,?,?,?,0)',(r['generation_id'],a['sheet_id'],a['row_index'],a['entity_id']))
            values=(s['tenant_id'],bid,r['generation_id'],best['first_commit_seq'],best['last_commit_seq'],best['physical_rows'],best['payload_bytes'],best['payload_digest'],ref,best['receipt_row'],'PREPARED',utcnow(),None)
            c.execute('INSERT INTO publication_batches VALUES('+','.join('?' for _ in values)+')',values)
            c.execute("UPDATE sync_outbox SET state='ASSIGNED',batch_id=? WHERE tenant_id=? AND commit_seq BETWEEN ? AND ?",(bid,s['tenant_id'],best['first_commit_seq'],best['last_commit_seq']))
            return dict(c.execute('SELECT * FROM publication_batches WHERE batch_id=?',(bid,)).fetchone())

    def _state(self,batch,state,kind,attempt,status=None):
        with self.db.transaction() as c:
            c.execute('UPDATE publication_batches SET state=? WHERE tenant_id=? AND batch_id=?',(state,batch['tenant_id'],batch['batch_id']))
            c.execute('INSERT INTO delivery_events(tenant_id,batch_id,attempt_id,event_kind,recorded_at,http_status) VALUES(?,?,?,?,?,?)',(batch['tenant_id'],batch['batch_id'],attempt,kind,utcnow(),status))

    def _preflight(self,plan,actor,meta):
        ranges=[]
        for sid,row,name,_ in plan['business']:
            if row<=meta[sid]['rows']:ranges.append((sid,row,0,1,len(HEADERS[name])))
        if not ranges:return
        cells=self.transport.read(ranges)
        incidents=[]
        with self.db.read() as c:
            gen=self.config['generation_id']
            for sid,row,name,_ in plan['business']:
                shadow=c.execute('SELECT cells_jcs FROM projection_shadows WHERE generation_id=? AND sheet_id=? AND row_index=?',(gen,sid,row)).fetchone()
                expected=loads(shadow[0]) if shadow else {}
                assignment=next((a for a in plan['assignments'] if a['sheet_id']==sid and a['row_index']==row),None)
                entity=assignment['entity_id'] if assignment else next((r[0] for r in c.execute('SELECT entity_id FROM projection_slots WHERE generation_id=? AND sheet_id=? AND row_index=?',(gen,sid,row))),None)
                for col,h in enumerate(HEADERS[name]):
                    if h in ('human_status','human_note'):continue
                    cell=cells.get((sid,row,col),{})
                    actual=entered(cell);wanted=expected.get(str(col),'')
                    if actual==wanted:continue
                    if col==0 or h in ('tenant_id','ledger_id','generation_id'):
                        raise CRMError('IDENTITY_OR_GENERATION_DRIFT',exit_code=7)
                    # Previously captured, explicitly rejected/kept-local canonical
                    # discrepancy may now be repaired. Unresolved differences hold.
                    encoded=json.dumps(cell,ensure_ascii=False,separators=(',',':'),sort_keys=True,allow_nan=False).encode()
                    hsh=digest(encoded)
                    approved=c.execute("SELECT 1 FROM quarantine_proposals p JOIN proposal_resolutions r ON r.tenant_id=p.tenant_id AND r.proposal_id=p.proposal_id WHERE p.source_resource_id=? AND p.source_sheet_id=? AND p.source_row=? AND p.source_column=? AND p.evidence_digest=? AND r.decision IN ('REJECT','KEEP_LOCAL')",(self.config['spreadsheet_id'],sid,row,col,hsh)).fetchone()
                    if not approved:incidents.append((sid,row,col,entity,h,cell))
        for sid,row,col,entity,h,cell in incidents[:10]:
            capture(self.engine,actor,resource=self.config['spreadsheet_id'],generation=self.config['generation_id'],sheet=sid,row=row,column=col,entity=entity,field=h,cell=cell)
        if incidents:raise CRMError('DRIFT_HOLD','Captured canonical differences require explicit disposition.',7)

    def verify(self,batch,plan):
        data=self.transport.read(request_ranges(plan['request']))
        expected=expected_cells(plan['request'])
        if any(entered(data.get(key,{}))!=value for key,value in expected.items()):return False
        # Complete cell coverage plus exactly one possibly applied send. Known 4xx
        # rejections do not remain potentially live. Hidden retries are forbidden.
        with self.db.transaction() as c:
            attempts=c.execute("SELECT count(*) FROM delivery_events WHERE batch_id=? AND event_kind='SEND'",(batch['batch_id'],)).fetchone()[0]
            rejected=c.execute("SELECT count(*) FROM delivery_events WHERE batch_id=? AND event_kind='NOT_APPLIED'",(batch['batch_id'],)).fetchone()[0]
            if attempts-rejected!=1:raise CRMError('MULTIPLE_POSSIBLY_LIVE_ATTEMPTS',exit_code=9)
            for a in plan['assignments']:
                c.execute('INSERT INTO projection_rows VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,generation_id,tab_key,entity_id) DO UPDATE SET sheet_id=excluded.sheet_id,row_index=excluded.row_index,projection_seq=excluded.projection_seq,row_digest=excluded.row_digest',(batch['tenant_id'],batch['generation_id'],a['tab_key'],a['entity_id'],a['sheet_id'],a['row_index'],a['projection_seq'],a['row_digest']))
            for sid,row in plan['retirements']:c.execute('UPDATE projection_slots SET retired=1 WHERE generation_id=? AND sheet_id=? AND row_index=?',(batch['generation_id'],sid,row))
            rows={}
            for (sid,row,col),value in expected.items():rows.setdefault((sid,row),{})[str(col)]=value
            for (sid,row),values in rows.items():
                c.execute('INSERT INTO projection_shadows VALUES(?,?,?,?) ON CONFLICT(generation_id,sheet_id,row_index) DO UPDATE SET cells_jcs=excluded.cells_jcs',(batch['generation_id'],sid,row,jcs(values)))
            c.execute("UPDATE publication_batches SET state='VERIFIED',verified_at=? WHERE batch_id=?",(utcnow(),batch['batch_id']))
            c.execute("UPDATE sync_outbox SET state='VERIFIED' WHERE batch_id=?",(batch['batch_id'],))
            c.execute('UPDATE projection_resources SET published_commit_seq=?,change_next_row=? WHERE tenant_id=? AND generation_id=?',(plan['last_commit_seq'],plan['next_change_row'],batch['tenant_id'],batch['generation_id']))
        return True

    def pull(self,actor):
        """One <=100-row slice across all three boards, not a per-agent full scan.
        Current entered cells are compared to last VERIFIED shadows, not newer
        unpublished local values. No domain state is adopted by this scanner.
        """
        self.validate_layout();gen=self.config['generation_id']
        with self.db.read() as c:
            state=dict(c.execute('SELECT * FROM ledger_state').fetchone())
            r=c.execute("SELECT cursor_value FROM capture_checkpoints WHERE source_key='board_scan'").fetchone()
            cursor=loads(r[0],128) if r and r[0] else [-1,0]
            rows=c.execute("""SELECT p.*,s.cells_jcs FROM projection_rows p
                JOIN projection_slots z ON z.generation_id=p.generation_id AND z.sheet_id=p.sheet_id AND z.row_index=p.row_index
                JOIN projection_shadows s ON s.generation_id=p.generation_id AND s.sheet_id=p.sheet_id AND s.row_index=p.row_index
                WHERE p.generation_id=? AND z.retired=0 AND (p.sheet_id>? OR (p.sheet_id=? AND p.row_index>?))
                ORDER BY p.sheet_id,p.row_index LIMIT 100""",(gen,cursor[0],cursor[0],cursor[1])).fetchall()
        def checkpoint(value,complete=False):
            with self.db.transaction() as c:
                c.execute("""INSERT INTO capture_checkpoints VALUES(?,'board_scan',?,0,?,?)
                    ON CONFLICT(tenant_id,source_key) DO UPDATE SET cursor_value=excluded.cursor_value,
                    last_scan_at=excluded.last_scan_at,last_complete_sweep_at=coalesce(excluded.last_complete_sweep_at,last_complete_sweep_at)""",
                    (state['tenant_id'],jcs(value).decode(),utcnow(),utcnow() if complete else None))
        if not rows:
            checkpoint([-1,0],True);return {'captured':0,'sweep_complete':True}
        titles={v:k for k,v in self.config['sheet_ids'].items()}
        data=self.transport.read([(r['sheet_id'],r['row_index'],0,1,len(HEADERS[titles[r['sheet_id']]])) for r in rows]);count=0;last=cursor
        for row in rows:
            sid=row['sheet_id'];ri=row['row_index'];eid=row['entity_id'];headers=HEADERS[titles[sid]]
            expected=loads(row['cells_jcs'],65536)
            identities={'entity_id':eid,'ledger_id':state['ledger_id'],'tenant_id':state['tenant_id'],'generation_id':gen}
            for field,wanted in identities.items():
                col=headers.index(field);cell=data.get((sid,ri,col),{})
                if entered(cell)!=wanted:
                    capture(self.engine,actor,resource=self.config['spreadsheet_id'],generation=gen,sheet=sid,row=ri,column=col,entity=eid,field=field,cell=cell)
                    raise CRMError('ROW_IDENTITY_DRIFT','Identity evidence retained; positional publication remains held.',7)
            with self.db.read() as c:kind=c.execute('SELECT entity_kind FROM entities WHERE entity_id=?',(eid,)).fetchone()[0]
            for col,field in enumerate(headers):
                cell=data.get((sid,ri,col),{});human=field in ('human_note','human_status')
                if human and kind not in ('person','organization'):continue
                if not human and entered(cell)==expected.get(str(col),''):continue
                if count>=100:
                    checkpoint(last);return {'captured':count,'sweep_complete':False,'capture_budget_reached':True}
                out=capture(self.engine,actor,resource=self.config['spreadsheet_id'],generation=gen,sheet=sid,row=ri,column=col,entity=eid,field=field,cell=cell)
                if not out.get('duplicate'):count+=1
            last=[sid,ri]
        checkpoint(last)
        return {'captured':count,'sweep_complete':False,'rows_examined':len(rows)}

    def run(self,actor,mode='both'):
        if mode=='dry-run':return self.plan()
        if mode not in ('both','push','pull'):raise CRMError('SYNC_MODE')
        with self.lock:
            with self.db.read() as c:self.engine.authorize(c,actor,'sync')
            pull=None
            if mode in ('both','pull'):pull=self.pull(actor)
            if mode=='pull':return {'pull':pull,'plan':self.plan()}
            meta=self.validate_layout();batch=self.prepare(meta)
            if batch is None:return {'state':'VERIFIED','plan':self.plan(),'pull':pull}
            plan=loads(self.engine.objects.get(batch['payload_object_ref']),2*1024*1024)
            raw=jcs(plan['request'])
            if digest(raw)!=batch['payload_digest']:raise CRMError('PREPARED_BYTES_CHANGED',exit_code=7)
            if batch['state'] in ('IN_FLIGHT','UNKNOWN'):
                self._state(batch,'UNKNOWN','RECONCILE',new_id())
                if self.verify(batch,plan):return {'state':'VERIFIED','plan':self.plan()}
                raise Ambiguous()
            if batch['state']=='QUARANTINED_PUBLICATION':raise Ambiguous()
            self._preflight(plan,actor,meta)
            # Refresh credentials BEFORE reserving/sending; a failure here is not a sent mutation.
            if hasattr(self.transport,'rest'):self.transport.rest.credentials.authorization()
            self.scheduler.reserve('sheets_write')
            attempt=new_id();self._state(batch,'IN_FLIGHT','SEND',attempt)
            try:
                self.transport.write(raw,reserved=True)
            except NotApplied as exc:
                self._state(batch,'RETRYABLE_NOT_APPLIED','NOT_APPLIED',attempt,exc.status)
                raise
            except BaseException:
                self._state(batch,'UNKNOWN','AMBIGUOUS',attempt)
                raise
            try:
                if not self.verify(batch,plan):
                    self._state(batch,'UNKNOWN','READBACK_MISMATCH',attempt);raise Ambiguous()
            except BaseException:
                with self.db.read() as c:current=c.execute('SELECT state FROM publication_batches WHERE batch_id=?',(batch['batch_id'],)).fetchone()[0]
                if current!='VERIFIED':self._state(batch,'UNKNOWN','VERIFICATION_INCOMPLETE',attempt)
                raise
            return {'state':'VERIFIED','plan':self.plan(),'pull':pull}
