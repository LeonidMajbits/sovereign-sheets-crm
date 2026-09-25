#!/usr/bin/env python3
"""Create a NEW durable command packet from a trusted broker read; never ingest.
Do not use this to retry an old command: resend its unchanged existing file.
"""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from crm.codec import loads,jcs
from crm.cli import invoke
from crm.ids import new_id
from crm.storage import fsync_dir
from crm.errors import CRMError

def main():
    p=argparse.ArgumentParser();p.add_argument('--command',required=True);p.add_argument('--payload',required=True);p.add_argument('--output',required=True);p.add_argument('--independent',action='store_true');a=p.parse_args()
    config=os.environ.get('CRM_CLIENT_CONFIG')
    if not config:raise CRMError('CLIENT_NOT_CONFIGURED',exit_code=4)
    payload=loads(Path(a.payload).read_bytes(),65536)
    if a.command=='entity.create':payload.setdefault('entity_id',new_id())
    if a.independent and a.command!='entity.create':raise CRMError('INDEPENDENT_ONLY_CREATE')
    health,code=invoke(config,'health',{})
    if code:raise CRMError('BROKER_NOT_READY',exit_code=code)
    packet={'schema_version':('crm.command.v6' if a.command=='entity.lww.set' else 'crm.command.v5' if a.command=='entity.tag.set' else 'crm.command.v4'),
            'operation_id':new_id(),'tenant_id':health['tenant_id'],'ledger_id':health['ledger_id'],
            'authority_epoch':health['data']['authority_epoch'],'template_version':'1',
            'base':None if a.independent else health['data']['base'],'command_type':a.command,'payload':payload}
    raw=jcs(packet)+b'\n'
    if len(raw)>65536:raise CRMError('COMMAND_TOO_LARGE')
    target=Path(a.output).expanduser();fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    fsync_dir(target.parent)
    print(jcs({'state':'PREPARED_NOT_INGESTED','operation_id':packet['operation_id'],'packet_file':str(target)}).decode())
if __name__=='__main__':
    try:main()
    except CRMError as e:
        print(jcs({'ok':False,'error':e.code}).decode());raise SystemExit(e.exit_code)
    except FileExistsError:
        print(jcs({'ok':False,'error':'PACKET_EXISTS_RESEND_UNCHANGED'}).decode());raise SystemExit(7)
