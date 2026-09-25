"""Bounded typed Sheets model for qualification; NEVER a live Google adapter.

Validates the real publisher's complete requests before atomic apply. Unlike the
small unit-test fake it copies only touched rows, not the entire accumulated
workbook. Quotas use the real Scheduler and injected virtual elapsed time.
"""
import json,hashlib
from collections import Counter
from crm.projection import HEADERS
from crm.codec import safe_cell
from crm.google_api import NotApplied,Ambiguous

class VirtualClock:
    def __init__(self):self.value=1_800_000_000.0
    def __call__(self):return self.value
    def advance(self,seconds):
        assert seconds>=0;self.value+=seconds

class FaultDomain:
    def __init__(self):
        self.offline=False;self.attempts=0;self.applied=0
        self.reject_remaining=0;self.periodic_rejections=False;self.lost_responses=set()
        self.events=[]
    def begin(self,scheduler):
        self.attempts+=1
        if self.reject_remaining or (self.periodic_rejections and self.attempts%97==0):
            if self.reject_remaining:self.reject_remaining-=1
            until=scheduler.rejected('sheets_write',retry_after=1)
            self.events.append({'event':'429','attempt':self.attempts,'at':scheduler.clock(),'retry_at':until})
            raise NotApplied(429)

class TypedSheets:
    def __init__(self,config,scheduler,domain):
        self.spreadsheet_id=config['spreadsheet_id'];self.sheet_ids=config['sheet_ids']
        self.scheduler=scheduler;self.domain=domain
        self.rows={(sid,1):list(HEADERS[name]) for name,sid in self.sheet_ids.items()}
        self.grids={sid:{'rows':1000,'columns':max(40,len(HEADERS[name]))} for name,sid in self.sheet_ids.items()}
        self.batch_trace=[];self.applied_hashes=set();self.read_calls=0
    def metadata(self):
        self.scheduler.reserve('sheets_read')
        if self.domain.offline:raise ConnectionError('synthetic partition before send')
        return {k:dict(v) for k,v in self.grids.items()}
    def read(self,ranges):
        self.scheduler.reserve('sheets_read');self.read_calls+=1
        if self.domain.offline:raise ConnectionError('synthetic partition read')
        out={}
        for sid,row,col,nr,nc in ranges:
            assert sid in self.grids
            for r in range(row,row+nr):
                line=self.rows.get((sid,r),[])
                for k in range(col,col+nc):
                    value=line[k] if k<len(line) else ''
                    out[(sid,r,k)]=safe_cell(value) if value else {}
        return out
    def write(self,body,reserved=False):
        if not reserved:self.scheduler.reserve('sheets_write')
        if self.domain.offline:raise ConnectionError('synthetic partition')
        self.domain.begin(self.scheduler)
        assert len(body)<=524288
        h=hashlib.sha256(body).hexdigest()
        assert h not in self.applied_hashes,'duplicate possibly-applied send'
        request=json.loads(body);nextrows={};grids={k:dict(v) for k,v in self.grids.items()}
        business=set();changes=self.sheet_ids['_Changes'];directory=self.sheet_ids['Directory']
        for op in request['requests']:
            if 'appendDimension' in op:
                a=op['appendDimension'];assert a['dimension']=='ROWS';assert a['length']>0
                grids[a['sheetId']]['rows']+=a['length'];continue
            assert set(op)=={'updateCells'}
            u=op['updateCells'];s=u['start'];sid=s['sheetId'];col=s.get('columnIndex',0)
            assert u['fields']=='userEnteredValue,userEnteredFormat.numberFormat'
            for dr,row in enumerate(u['rows']):
                r=s['rowIndex']+1+dr;assert 1<=r<=grids[sid]['rows']
                k=(sid,r)
                if k not in nextrows:nextrows[k]=list(self.rows.get(k,[]))
                line=nextrows[k]
                width=col+len(row['values']);assert width<=grids[sid]['columns']
                if len(line)<width:line.extend(['']*(width-len(line)))
                for dc,cell in enumerate(row['values']):
                    c=col+dc;assert set(cell['userEnteredValue'])=={'stringValue'}
                    assert cell['userEnteredFormat']['numberFormat']['type']=='TEXT'
                    assert not(sid==directory and c in (27,28)), 'human cell overwritten'
                    value=cell['userEnteredValue']['stringValue'];assert isinstance(value,str)
                    if sid==changes and k in self.rows and c<len(self.rows[k]):
                        assert self.rows[k][c]==value,'immutable cloud history overwritten'
                    line[c]=value
                if sid in (directory,self.sheet_ids['Active Pipeline'],self.sheet_ids['Completed Archives']):business.add(k)
        assert len(business)<=50
        self.rows.update(nextrows);self.grids=grids;self.applied_hashes.add(h)
        self.domain.applied+=1;self.scheduler.succeeded('sheets_write')
        receipt=next(line for (sid,r),line in nextrows.items() if sid==changes and line and line[0]=='BATCH_RECEIPT')
        manifest=json.loads(receipt[8])
        self.batch_trace.append({'spreadsheet_id':self.spreadsheet_id,'at':self.scheduler.clock(),
            'body_sha256':h,'bytes':len(body),'physical_business_rows':len(business),
            'batch_id':manifest['batch_id'],'first_commit_seq':manifest['first_commit_seq'],
            'last_commit_seq':manifest['last_commit_seq']})
        if self.domain.applied in self.domain.lost_responses:
            self.domain.events.append({'event':'response_lost_after_apply','applied':self.domain.applied,'body_sha256':h})
            raise Ambiguous()
        return {'spreadsheetId':self.spreadsheet_id,'replies':[{} for _ in request['requests']]}
