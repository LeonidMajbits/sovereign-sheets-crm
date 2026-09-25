"""Explicit, journaled bootstrap of a provisioned UNUSED spreadsheet.

This is administration, not a runtime fallback. No file is created, copied,
shared or deleted. A new attempt requires an empty, single-sheet resource.
An inconclusive send is only read-reconciled and is never blindly repeated.
"""
from __future__ import annotations
import urllib.parse
from .codec import jcs, loads, digest, utcnow
from .errors import CRMError
from .google_api import NotApplied, Ambiguous
from .projection import HEADERS
from .sync import update

class LayoutProvisioner:
    def __init__(self,publisher):
        self.publisher=publisher;self.engine=publisher.engine;self.db=publisher.db
        self.transport=publisher.transport
        if not hasattr(self.transport,'rest'):raise CRMError('PROVISION_REST_REQUIRED')
        self.rest=self.transport.rest
        self.key='layout_bootstrap:'+digest(publisher.config['spreadsheet_id'].encode())

    def _get(self):
        with self.db.read() as c:
            r=c.execute('SELECT value FROM runtime_state WHERE key=?',(self.key,)).fetchone()
            return loads(r[0],65536) if r else None

    def _set(self,state):
        with self.db.transaction() as c:
            c.execute('INSERT INTO runtime_state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (self.key,jcs(state).decode()))

    def _fresh_plan(self):
        # A bounded complete user-entered-data inspection, not a formatted-value
        # peek at A1. Default grid may be at most 1000x64 and must contain no data.
        # Build field masks structurally and keep parenthesis balance tested.
        fields='spreadsheetId,sheets(properties,merges,data(rowData(values(userEnteredValue,effectiveValue,note,dataSourceFormula,dataSourceTable,pivotTable,chipRuns,textFormatRuns))))'
        result=self.rest.call(self.transport.base+'?'+urllib.parse.urlencode({'includeGridData':'true','fields':fields}),limit=2*1024*1024)
        config=self.publisher.config
        if result.get('spreadsheetId')!=config['spreadsheet_id'] or len(result.get('sheets',[]))!=1:
            raise CRMError('BOOTSTRAP_REQUIRES_UNUSED_SINGLE_SHEET',exit_code=7)
        original=result['sheets'][0];props=original['properties'];grid=props.get('gridProperties',{})
        if props['sheetId']!=config['sheet_ids']['Directory'] or props.get('sheetType','GRID')!='GRID' or original.get('merges'):
            raise CRMError('BOOTSTRAP_DIRECTORY_ID_OR_LAYOUT',exit_code=7)
        if not (1<=grid.get('rowCount',0)<=1000 and 1<=grid.get('columnCount',0)<=64):
            raise CRMError('BOOTSTRAP_GRID_BOUNDS',exit_code=7)
        for data in original.get('data',[]):
            for row in data.get('rowData',[]):
                if any(any(v not in (None,{},[], '') for v in cell.values()) for cell in row.get('values',[])):
                    raise CRMError('BOOTSTRAP_NONEMPTY_RESOURCE',exit_code=7)
        requests=[]
        for name,headers in HEADERS.items():
            properties={'sheetId':config['sheet_ids'][name],'title':name,
                        'gridProperties':{'rowCount':1000,'columnCount':max(40,len(headers)), 'frozenRowCount':1},
                        'hidden':name.startswith('_')}
            if name=='Directory':
                requests.append({'updateSheetProperties':{'properties':properties,'fields':'title,gridProperties,hidden'}})
            else:requests.append({'addSheet':{'properties':properties}})
            requests.append(update(properties['sheetId'],1,0,[headers]))
            protection={'range':{'sheetId':properties['sheetId']},'description':'CRM publisher-owned cells',
                        'warningOnly':False}
            if name=='Directory':protection['unprotectedRanges']=[{'sheetId':properties['sheetId'],'startRowIndex':1,'startColumnIndex':27,'endColumnIndex':29}]
            requests.append({'addProtectedRange':{'protectedRange':protection}})
        body=jcs({'requests':requests})
        ref,_size=self.engine.objects.put(body)
        return {'state':'PREPARED','object_ref':ref,'payload_digest':digest(body),'prepared_at':utcnow(),
                'spreadsheet_id':config['spreadsheet_id'],'generation_id':config['generation_id'],
                'sheet_ids':config['sheet_ids']}

    def run(self):
        with self.publisher.lock:
            state=self._get()
            if state and any(state[k]!=self.publisher.config[k] for k in ('spreadsheet_id','generation_id','sheet_ids')):
                raise CRMError('BOOTSTRAP_PIN_MISMATCH',exit_code=7)
            if state and state['state'] in ('IN_FLIGHT','UNKNOWN','VERIFIED'):
                try:self.publisher.validate_layout()
                except CRMError as exc:
                    raise CRMError('BOOTSTRAP_UNKNOWN','Readback has not established bootstrap; do not resend into this resource.',9) from exc
                state['state']='VERIFIED';self._set(state)
                self.publisher.activate()
                return {'state':'PROVISIONED_AND_ACTIVATED','reconciled':True}
            if state is None:
                with self.db.read() as c:
                    if c.execute('SELECT 1 FROM projection_resources').fetchone():raise CRMError('EXISTING_PROJECTION_REQUIRES_MIGRATION',exit_code=7)
                state=self._fresh_plan();self._set(state)
            body=self.engine.objects.get(state['object_ref'])
            if digest(body)!=state['payload_digest']:raise CRMError('BOOTSTRAP_PAYLOAD_CORRUPT',exit_code=7)
            self.rest.credentials.authorization();self.publisher.scheduler.reserve('sheets_write')
            state['state']='IN_FLIGHT';self._set(state)
            try:self.transport.write(body,reserved=True)
            except NotApplied:
                state['state']='RETRYABLE_NOT_APPLIED';self._set(state);raise
            except Exception as exc:
                state['state']='UNKNOWN';self._set(state);raise Ambiguous() from exc
            try:self.publisher.validate_layout()
            except Exception as exc:
                state['state']='UNKNOWN';self._set(state);raise Ambiguous() from exc
            state['state']='VERIFIED';self._set(state)
            self.publisher.activate()
            return {'state':'PROVISIONED_AND_ACTIVATED','reconciled':False}
