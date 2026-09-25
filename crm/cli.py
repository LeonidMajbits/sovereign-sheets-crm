"""Thin authenticated client. No sqlite imports, Google credentials or auto-start."""
from __future__ import annotations
import argparse,json,os,secrets,socket,sys,hmac
from pathlib import Path
from .codec import jcs,loads,mac,utcnow
from .errors import CRMError

class Parser(argparse.ArgumentParser):
    def error(self,message):raise CRMError('USAGE',message,2)

def parser():
    p=Parser(prog='./lab crm',description='Local broker client; JSON output is the default.')
    sub=p.add_subparsers(dest='action',required=True)
    ls=sub.add_parser('list');ls.add_argument('--campaign');ls.add_argument('--status');ls.add_argument('--kind');ls.add_argument('--limit',type=int,default=50);ls.add_argument('--cursor')
    ing=sub.add_parser('ingest');ing.add_argument('file')
    for name in ('get','show'):
        x=sub.add_parser(name);x.add_argument('id')
    for name in ('query','search'):
        x=sub.add_parser(name);x.add_argument('query');x.add_argument('--scope',choices=['entities','interactions'],default='entities');x.add_argument('--limit',type=int,default=20);x.add_argument('--fuzzy',action='store_true')
    sync=sub.add_parser('sync');m=sync.add_mutually_exclusive_group();m.add_argument('--push',action='store_true');m.add_argument('--pull',action='store_true');m.add_argument('--dry-run',action='store_true')
    props=sub.add_parser('proposals');ps=props.add_subparsers(dest='proposal_action',required=True)
    pl=ps.add_parser('list');pl.add_argument('--limit',type=int,default=50)
    pr=ps.add_parser('resolve');pr.add_argument('id');g=pr.add_mutually_exclusive_group(required=True);g.add_argument('--accept',action='store_true');g.add_argument('--reject',action='store_true');pr.add_argument('--operation-id')
    sub.add_parser('health');a=sub.add_parser('audit');a.add_argument('operation_id')
    return p

def parse(argv):
    options=[x.split('=')[0] for x in argv if x.startswith('--')]
    if len(options)!=len(set(options)):raise CRMError('DUPLICATE_OPTION',exit_code=2)
    d=vars(parser().parse_args(argv));action=d.pop('action')
    if action=='ingest':
        path=Path(d['file'])
        with path.open('rb') as f:raw=f.read(65537)
        d={'packet':loads(raw,65536)}
    elif action=='sync':d={'mode':'dry-run' if d['dry_run'] else 'push' if d['push'] else 'pull' if d['pull'] else 'both'}
    elif action=='proposals':action+='.'+d.pop('proposal_action')
    return action,{k:v for k,v in d.items() if v is not None}

def invoke(config,action,args):
    path=Path(config).expanduser()
    if path.is_symlink() or path.stat().st_mode&0o077:raise CRMError('INSECURE_CLIENT_CONFIG',exit_code=4)
    data=loads(path.read_bytes(),16384)
    if set(data)!={'socket','key_id','key_hex'}:raise CRMError('CLIENT_CONFIG',exit_code=4)
    key=bytes.fromhex(data['key_hex']);nonce=secrets.token_hex(32)
    request={'protocol':'crm.local.v1','key_id':data['key_id'],'nonce':nonce,'issued_at':utcnow(),'action':action,'args':args}
    request['mac']=mac(key,request,'CRM5:local-request:v1')
    sent=False
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
            sock.settimeout(120);sock.connect(data['socket'])
            sent=True  # sendall may transmit a complete request before reporting failure.
            sock.sendall(jcs(request)+b'\n')
            with sock.makefile('rb') as f:raw=f.readline(2*1024*1024+1)
    except OSError as exc:
        if sent and action in ('ingest','proposals.resolve','sync'):
            raise CRMError('LOCAL_OUTCOME_UNKNOWN','Inspect or retry the same operation identity; no new business ID.',9) from exc
        raise
    if not raw.endswith(b'\n') or len(raw)>2*1024*1024:raise CRMError('BROKER_RESPONSE',exit_code=9 if action in ('ingest','proposals.resolve','sync') else 7)
    response=loads(raw,2*1024*1024);signature=response.pop('mac',None)
    if response.get('nonce')!=nonce or response.get('protocol')!='crm.local.result.v1' or not isinstance(signature,str) or not hmac.compare_digest(signature,mac(key,response,'CRM5:local-result:v1')):raise CRMError('BROKER_RESPONSE_AUTH',exit_code=4)
    return response['result'],response['exit_code']

def main(argv=None):
    action='unknown'
    try:
        action,args=parse(sys.argv[1:] if argv is None else argv)
        config=os.environ.get('CRM_CLIENT_CONFIG')
        if not config:raise CRMError('CLIENT_NOT_CONFIGURED','Set CRM_CLIENT_CONFIG to a private client configuration.',4)
        result,code=invoke(config,action,args)
    except KeyboardInterrupt:
        result={'ok':False,'command':action,'error':{'code':'INTERRUPTED','message':'Inspect the original operation ID before retrying.'}};code=130
    except CRMError as exc:
        result={'ok':False,'command':action,'error':{'code':exc.code,'message':str(exc),'retryable':exc.retryable}};code=exc.exit_code
    except (OSError,ValueError):
        result={'ok':False,'command':action,'error':{'code':'CLIENT_IO','message':'Cannot reach configured broker or read command. No broker was started.'}};code=11
    # Pre-authentication client failures have the same result shape, with unknown
    # authority coordinates rather than invented values from an untrusted file.
    if 'schema_version' not in result:
        result={'schema_version':'crm.result.v4','command':action,'ok':False,
                'outcome':None,'error':result['error'],'tenant_id':None,'ledger_id':None,
                'operation_id':None,'as_of_commit_seq':None,'data':None,
                'sync':{'state':'UNKNOWN','published_commit_seq':None,'pending_transactions':None},
                'next_cursor':None}
        result['error'].setdefault('retryable',False)
    sys.stdout.buffer.write(jcs(result)+b'\n');sys.stdout.buffer.flush();return code
