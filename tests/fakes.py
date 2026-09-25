"""Deterministic provider model; not evidence of deployed Google behavior."""
import copy,json
from crm.projection import HEADERS
from crm.codec import safe_cell
from crm.google_api import NotApplied,Ambiguous

class Clock:
    def __init__(self):self.value=1_800_000_000.0
    def __call__(self):return self.value
    def advance(self,n=16):self.value+=n

class MemorySheets:
    def __init__(self,config,scheduler):
        self.spreadsheet_id=config['spreadsheet_id'];self.sheet_ids=config['sheet_ids'];self.scheduler=scheduler
        self.cells={};self.grids={sid:{'rows':1000,'columns':max(40,len(HEADERS[name]))} for name,sid in self.sheet_ids.items()}
        for name,headers in HEADERS.items():
            for i,h in enumerate(headers):self.cells[(self.sheet_ids[name],1,i)]=safe_cell(h)
        self.fail=None;self.writes=[];self.read_calls=0
    def metadata(self):
        self.scheduler.reserve('sheets_read');return copy.deepcopy(self.grids)
    def read(self,ranges):
        self.scheduler.reserve('sheets_read');self.read_calls+=1;out={}
        if self.fail=='read':raise RuntimeError('injected read error')
        for sid,row,col,nr,nc in ranges:
            for r in range(row,row+nr):
                for k in range(col,col+nc):out[(sid,r,k)]=copy.deepcopy(self.cells.get((sid,r,k),{}))
        return out
    def write(self,body,reserved=False):
        if not reserved:self.scheduler.reserve('sheets_write')
        if self.fail=='429':self.scheduler.rejected('sheets_write');raise NotApplied(429)
        if self.fail=='timeout_before':self.writes.append(body);raise Ambiguous()
        req=json.loads(body);self.writes.append(body)
        nextcells=copy.deepcopy(self.cells);grids=copy.deepcopy(self.grids)
        for op in req['requests']:
            if 'appendDimension' in op:
                a=op['appendDimension'];grids[a['sheetId']]['rows']+=a['length'];continue
            u=op['updateCells'];s=u['start'];sid=s['sheetId'];row=s['rowIndex']+1;col=s.get('columnIndex',0)
            for dr,r in enumerate(u['rows']):
                for dc,cell in enumerate(r['values']):
                    if sid==self.sheet_ids['Directory'] and col+dc in (27,28):raise AssertionError('publisher wrote human cell')
                    if set(cell['userEnteredValue'])!={'stringValue'}:raise AssertionError('nonliteral publication')
                    nextcells[(sid,row+dr,col+dc)]=copy.deepcopy(cell)
        self.cells=nextcells;self.grids=grids
        if self.fail=='timeout_after':raise Ambiguous()
        return {'spreadsheetId':self.spreadsheet_id,'replies':[{} for _ in req['requests']]}
