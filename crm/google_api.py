"""Fixed-host direct Google REST transport. No browser, redirect, or mutation retry.

Only the trusted broker loads credentials. HTTP effects remain unverified until
Publisher compares every intended cell, including immutable journal frames.
"""
from __future__ import annotations
import base64,json,time,urllib.request,urllib.parse,urllib.error,hashlib,os
from pathlib import Path
from .codec import pairs
from .errors import CRMError

class NotApplied(CRMError):
    def __init__(self,status,retry_after=0):
        super().__init__('GOOGLE_REJECTED',exit_code=4 if status in (401,403) else 10 if status==429 else 7,retryable=status in (401,429))
        self.status=status;self.retry_after=retry_after

class Ambiguous(CRMError):
    def __init__(self):super().__init__('UNKNOWN','Provider effect has not been established.',9)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def b64(data):return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

class ServiceAccount:
    def __init__(self,path,scopes,scheduler):
        p=Path(path).expanduser()
        if p.is_symlink() or p.stat().st_mode & 0o077:raise CRMError('INSECURE_CREDENTIAL',exit_code=4)
        self.info=json.loads(p.read_text(),object_pairs_hook=pairs)
        if self.info.get('type')!='service_account' or self.info.get('token_uri')!='https://oauth2.googleapis.com/token':raise CRMError('CREDENTIAL_TYPE_OR_TOKEN_HOST',exit_code=4)
        if scheduler.principal!=self.info.get('client_email'):raise CRMError('QUOTA_PRINCIPAL_MISMATCH',exit_code=4)
        self.scopes=tuple(scopes);self.scheduler=scheduler;self.token=None;self.expires=0
        self.opener=urllib.request.build_opener(NoRedirect)

    def authorization(self):
        if self.token and time.time()<self.expires-60:return 'Bearer '+self.token
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        self.scheduler.reserve('token');now=int(time.time())
        header=b64(json.dumps({'alg':'RS256','typ':'JWT'},separators=(',',':')).encode())
        claims=b64(json.dumps({'iss':self.info['client_email'],'scope':' '.join(self.scopes),'aud':'https://oauth2.googleapis.com/token','iat':now,'exp':now+3600},separators=(',',':')).encode())
        signing=(header+'.'+claims).encode();key=load_pem_private_key(self.info['private_key'].encode(),password=None)
        assertion=signing.decode()+'.'+b64(key.sign(signing,padding.PKCS1v15(),hashes.SHA256()))
        request=urllib.request.Request('https://oauth2.googleapis.com/token',data=urllib.parse.urlencode({'grant_type':'urn:ietf:params:oauth:grant-type:jwt-bearer','assertion':assertion}).encode(),method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
        try:
            with self.opener.open(request,timeout=20) as response:
                raw=response.read(65537)
                if len(raw)>65536:raise ValueError()
                result=json.loads(raw,object_pairs_hook=pairs)
            if not isinstance(result.get('access_token'),str):raise ValueError()
            self.token=result['access_token'];self.expires=time.time()+min(int(result['expires_in']),3600)
            return 'Bearer '+self.token
        except Exception as exc:
            raise CRMError('AUTH_BLOCKED','Token acquisition failed; no browser fallback.',4) from exc

class GoogleREST:
    def __init__(self,credentials,scheduler):
        self.credentials=credentials;self.scheduler=scheduler;self.opener=urllib.request.build_opener(NoRedirect)

    def call(self,url,*,method='GET',body=None,quota='sheets_read',mutation=False,limit=8*1024*1024,reserved=False):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('sheets.googleapis.com','www.googleapis.com') or parsed.username or parsed.port:
            raise CRMError('PROVIDER_HOST_NOT_PINNED',exit_code=4)
        auth=self.credentials.authorization()  # no Sheets effect yet
        if not reserved:self.scheduler.reserve(quota)
        req=urllib.request.Request(url,data=body,method=method,headers={'Authorization':auth,'Content-Type':'application/json','Accept':'application/json'})
        try:
            with self.opener.open(req,timeout=30) as response:
                raw=response.read(limit+1)
                if len(raw)>limit:raise ValueError('response limit')
                if response.status!=200 or 'application/json' not in response.headers.get('Content-Type',''):raise ValueError('response type')
                result=json.loads(raw,object_pairs_hook=pairs)
            self.scheduler.succeeded(quota)
            return result
        except urllib.error.HTTPError as exc:
            # Only authentic fixed-host structured 4xx responses establish pre-application rejection.
            raw=exc.read(65537)
            try:err=json.loads(raw,object_pairs_hook=pairs);structured=isinstance(err.get('error'),dict)
            except Exception:structured=False
            if exc.code in (400,401,403,404,429) and structured:
                retry=0
                try:retry=max(0,int(exc.headers.get('Retry-After','0')))
                except ValueError:pass
                if exc.code==429:self.scheduler.rejected(quota,retry)
                if exc.code==401:self.credentials.token=None
                raise NotApplied(exc.code,retry) from exc
            if mutation:raise Ambiguous() from exc
            raise CRMError('PROVIDER_READ_FAILED',exit_code=10,retryable=True) from exc
        except (CRMError,):raise
        except Exception as exc:
            if mutation:raise Ambiguous() from exc
            raise CRMError('PROVIDER_READ_FAILED',exit_code=10,retryable=True) from exc

class Sheets:
    def __init__(self,rest:GoogleREST,spreadsheet_id:str,sheet_ids:dict):
        if not spreadsheet_id or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for ch in spreadsheet_id):raise CRMError('SPREADSHEET_ID')
        self.rest=rest;self.spreadsheet_id=spreadsheet_id;self.sheet_ids=dict(sheet_ids)
        self.titles={v:k for k,v in sheet_ids.items()}
        self.base='https://sheets.googleapis.com/v4/spreadsheets/'+spreadsheet_id

    def metadata(self):
        fields='spreadsheetId,properties(importFunctionsExternalUrlAccessAllowed),sheets(properties,merges)'
        result=self.rest.call(self.base+'?'+urllib.parse.urlencode({'fields':fields}))
        if result.get('spreadsheetId')!=self.spreadsheet_id:raise CRMError('RESOURCE_ID_MISMATCH',exit_code=7)
        got={}
        for s in result.get('sheets',[]):
            p=s['properties'];sid=p['sheetId'];title=p['title']
            if title in self.sheet_ids:
                if self.sheet_ids[title]!=sid or s.get('merges'):raise CRMError('LAYOUT_HOLD',exit_code=7)
                got[sid]=dict(rows=p['gridProperties']['rowCount'],columns=p['gridProperties']['columnCount'])
        if set(got)!=set(self.sheet_ids.values()):raise CRMError('LAYOUT_HOLD',exit_code=7)
        return got

    def read(self,ranges):
        params=[('includeGridData','true'),('fields','spreadsheetId,sheets(properties(sheetId),data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,dataSourceFormula,dataSourceTable,pivotTable,chipRuns,textFormatRuns))))')]
        requested=set()
        for sid,row,col,nrows,ncols in ranges:
            if sid not in self.titles or row<1 or col<0 or nrows*ncols>10000:raise CRMError('READ_RANGE')
            def letters(n):
                s='';n+=1
                while n:s=chr(65+(n-1)%26)+s;n=(n-1)//26
                return s
            title=self.titles[sid].replace("'","''")
            params.append(('ranges',f"'{title}'!{letters(col)}{row}:{letters(col+ncols-1)}{row+nrows-1}"))
            requested.update((sid,r,k) for r in range(row,row+nrows) for k in range(col,col+ncols))
        if len(requested)>15000:raise CRMError('READ_CELL_LIMIT')
        data=self.rest.call(self.base+'?'+urllib.parse.urlencode(params))
        if data.get('spreadsheetId')!=self.spreadsheet_id:raise CRMError('RESOURCE_ID_MISMATCH',exit_code=7)
        cells={k:{} for k in requested}
        for sheet in data.get('sheets',[]):
            sid=sheet['properties']['sheetId']
            for grid in sheet.get('data',[]):
                startrow=grid.get('startRow',0)+1;startcol=grid.get('startColumn',0)
                for dr,rd in enumerate(grid.get('rowData',[])):
                    for dc,cell in enumerate(rd.get('values',[])):
                        k=(sid,startrow+dr,startcol+dc)
                        if k in requested:cells[k]=cell
        return cells

    def write(self,body,*,reserved=False):
        return self.rest.call(self.base+':batchUpdate',method='POST',body=body,quota='sheets_write',mutation=True,reserved=reserved)
