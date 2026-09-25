"""Optional Drive intake consumer with independently verified sender/custody MACs.

Drive metadata is transport provenance, never command authority. Configuration
pins sender capabilities and actor identities separately from all packet content.
"""
from __future__ import annotations
import json,hmac,urllib.parse,urllib.request
from datetime import datetime,timezone
from .codec import loads,jcs,digest,mac,timestamp,ulid,utcnow
from .engine import ActorContext
from .errors import CRMError

ENVELOPE_KEYS={'protocol','kind','delivery_id','sender_key_id','audience','tenant_id','ledger_id','issued_at','expires_at','nonce','payload','payload_digest','mac'}
CUSTODY_KEYS={'protocol','gateway_key_id','tenant_id','ledger_id','delivery_id','sender_key_id','envelope_digest','payload_digest','received_at','file_id','mac'}
HINT_KEYS={'workbook_id','sheet_id','generation_id','start_row','end_row_exclusive','start_column','end_column_exclusive','change_class','captured_at','trigger_id'}


def _when(s):return datetime.fromisoformat(timestamp(s).replace('Z','+00:00')).timestamp()

def verify_delivery(raw,config,*,now=None):
    outer=loads(raw,196608)
    if not isinstance(outer,dict) or set(outer)!={'envelope','custody'}:raise CRMError('STAGING_SCHEMA')
    if jcs(outer)!=raw:raise CRMError('STAGING_NONCANONICAL')
    e,c=outer['envelope'],outer['custody']
    if not isinstance(e,dict) or set(e)!=ENVELOPE_KEYS or not isinstance(c,dict) or set(c)!=CUSTODY_KEYS:raise CRMError('STAGING_SCHEMA')
    if e['protocol']!='crm.ingress.v4' or c['protocol']!='crm.custody.v1':raise CRMError('INGRESS_PROTOCOL')
    ulid(e['delivery_id']);ulid(e['tenant_id']);ulid(e['ledger_id'])
    if (e['tenant_id'],e['ledger_id'],e['audience'])!=(config['tenant_id'],config['ledger_id'],config['audience']):raise CRMError('INGRESS_SCOPE',exit_code=4)
    sender=config['senders'].get(e['sender_key_id'])
    gateway=config['gateway_keys'].get(c['gateway_key_id'])
    if not sender or not gateway:raise CRMError('INGRESS_KEY',exit_code=4)
    if not isinstance(e['mac'],str) or not hmac.compare_digest(e['mac'],mac(bytes.fromhex(sender['key_hex']),{k:v for k,v in e.items() if k!='mac'})):
        raise CRMError('INGRESS_SENDER_MAC',exit_code=4)
    if not isinstance(c['mac'],str) or not hmac.compare_digest(c['mac'],mac(bytes.fromhex(gateway),{k:v for k,v in c.items() if k!='mac'},'CRM5:custody:v1')):
        raise CRMError('INGRESS_CUSTODY_MAC',exit_code=4)
    for k in ('tenant_id','ledger_id','delivery_id','sender_key_id','payload_digest'):
        if e[k]!=c[k]:raise CRMError('CUSTODY_BINDING')
    if c['envelope_digest']!=digest(e) or e['payload_digest']!=digest(e['payload']):raise CRMError('CUSTODY_DIGEST')
    issued,expires,admitted=_when(e['issued_at']),_when(e['expires_at']),_when(c['received_at'])
    now=now if now is not None else datetime.now(timezone.utc).timestamp()
    if not 0<=expires-issued<=300 or issued>admitted+60 or expires<admitted-60 or admitted>now+60:raise CRMError('INVALID_ADMISSION_TIME')
    if not isinstance(e['nonce'],str) or len(e['nonce'])!=64 or any(x not in '0123456789abcdef' for x in e['nonce']):raise CRMError('NONCE_FORMAT')
    if c['file_id'] is not None:raise CRMError('UNSUPPORTED_CUSTODY_FILE_BINDING')
    if e['kind']=='dirty_hint':
        p=e['payload']
        if 'dirty_hint' not in sender['capabilities'] or set(p)!=HINT_KEYS:raise CRMError('HINT_CAPABILITY_OR_SCHEMA',exit_code=4)
        if p['workbook_id']!=config['workbook_id'] or p['generation_id']!=config['generation_id'] or p['sheet_id'] not in config['sheet_ids'].values():raise CRMError('HINT_PIN')
        for name in ('start_row','end_row_exclusive','start_column','end_column_exclusive'):
            if type(p[name]) is not int or not 0<=p[name]<=10000000:raise CRMError('HINT_RANGE')
        if p['end_row_exclusive']<p['start_row'] or p['end_column_exclusive']<p['start_column']:raise CRMError('HINT_RANGE')
        if p['change_class'] not in ('EDIT','STRUCTURE','WHOLE_SHEET'):raise CRMError('HINT_CLASS')
        timestamp(p['captured_at'])
    elif e['kind']=='command':
        if len(jcs(e['payload']))>65536:raise CRMError('COMMAND_TOO_LARGE')
    else:raise CRMError('INGRESS_KIND')
    actor=ActorContext(sender['actor_id'],frozenset(sender['capabilities']))
    return e,actor

class DriveInbox:
    def __init__(self,engine,rest,config):
        self.engine,self.rest,self.config=engine,rest,config
        folder=config['staging_folder_id']
        if not folder or any(x not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for x in folder):raise CRMError('STAGING_FOLDER_ID')

    def read_bytes(self,file_id):
        if not file_id or any(x not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for x in file_id):raise CRMError('DRIVE_FILE_ID')
        authorization=self.rest.credentials.authorization();self.rest.scheduler.reserve('drive_read')
        url='https://www.googleapis.com/drive/v3/files/'+file_id+'?alt=media&supportsAllDrives=true'
        req=urllib.request.Request(url,headers={'Authorization':authorization,'Accept':'application/json'})
        try:
            with self.rest.opener.open(req,timeout=30) as response:
                raw=response.read(196609)
                if response.status!=200 or len(raw)>196608:raise CRMError('STAGING_FILE_LIMIT')
                return raw
        except CRMError:raise
        except Exception as exc:raise CRMError('DRIVE_READ_FAILED',exit_code=10,retryable=True) from exc

    def consume(self):
        e=self.engine
        with e.db.read() as c:
            s=dict(c.execute('SELECT * FROM ledger_state').fetchone())
            cursor=c.execute("SELECT cursor_value FROM capture_checkpoints WHERE source_key='drive_staging'").fetchone()
        params={'q':"'"+self.config['staging_folder_id']+"' in parents and trashed=false",'pageSize':'100','fields':'nextPageToken,files(id,mimeType,size,parents,trashed)','supportsAllDrives':'true','includeItemsFromAllDrives':'true'}
        if cursor and cursor[0]:params['pageToken']=cursor[0]
        page=self.rest.call('https://www.googleapis.com/drive/v3/files?'+urllib.parse.urlencode(params),quota='drive_read')
        processed=0
        for item in page.get('files',[]):
            if item.get('trashed') or self.config['staging_folder_id'] not in item.get('parents',[]) or item.get('mimeType')!='application/json':continue
            if int(item.get('size','0'))>196608:raise CRMError('STAGING_FILE_LIMIT')
            raw=self.read_bytes(item['id']);content_digest=digest(raw)
            with e.db.read() as c:
                old=c.execute('SELECT content_digest FROM staging_receipts WHERE tenant_id=? AND file_id=?',(s['tenant_id'],item['id'])).fetchall()
            if old:
                if any(x[0]!=content_digest for x in old):raise CRMError('STAGED_FILE_MUTATED',exit_code=7)
                continue
            receipt={'file_id':item['id'],'content_digest':content_digest,'delivery_id':None}
            try:
                envelope,actor=verify_delivery(raw,self.config)
                receipt['delivery_id']=envelope['delivery_id']
                if envelope['kind']=='command':
                    e.ingest(envelope['payload'],actor,staging_receipt=receipt)
                else:
                    with e.db.transaction() as c:
                        c.execute("INSERT INTO capture_checkpoints VALUES(?,'board_scan','[-1,0]',1,NULL,NULL) ON CONFLICT(tenant_id,source_key) DO UPDATE SET cursor_value='[-1,0]',dirty=1",(s['tenant_id'],))
                        c.execute('INSERT INTO staging_receipts VALUES(?,?,?,?,?,?,?)',(s['tenant_id'],item['id'],content_digest,envelope['delivery_id'],None,'CAPTURED',utcnow()))
                processed+=1
            except CRMError as exc:
                if exc.exit_code in (6,7,9,10,11):raise
                # Reject authenticated-invalid and malformed intake without copying
                # its raw bytes into SQL, audit, FTS or a model-visible error message.
                with e.db.transaction() as c:
                    c.execute('INSERT INTO staging_receipts VALUES(?,?,?,?,?,?,?)',(s['tenant_id'],item['id'],content_digest,receipt['delivery_id'] or 'UNAUTHENTICATED',None,'REJECTED',utcnow()))
        # The page cursor follows persisted per-file custody. End-of-list restarts
        # a full overlapping enumeration; filename/time ordering is never a cursor.
        with e.db.transaction() as c:
            c.execute("INSERT INTO capture_checkpoints VALUES(?,'drive_staging',?,0,?,?) ON CONFLICT(tenant_id,source_key) DO UPDATE SET cursor_value=excluded.cursor_value,last_scan_at=excluded.last_scan_at,last_complete_sweep_at=coalesce(excluded.last_complete_sweep_at,last_complete_sweep_at)",(s['tenant_id'],page.get('nextPageToken'),utcnow(),utcnow() if not page.get('nextPageToken') else None))
        return {'processed':processed,'has_next_page':bool(page.get('nextPageToken'))}
