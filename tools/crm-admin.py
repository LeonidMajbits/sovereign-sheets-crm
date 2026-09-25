#!/usr/bin/env python3
"""Explicit fresh provisioning and offline audit; never run automatically by CLI."""
import argparse,os,secrets,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from crm.db import Database,runtime_check
from crm.engine import Engine,ALL_CAPS
from crm.ids import new_id
from crm.codec import jcs
from crm.errors import CRMError
from crm.storage import fsync_dir

def write_new(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:f.write(jcs(data)+b'\n');f.flush();os.fsync(f.fileno())

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    init=sub.add_parser('init');init.add_argument('--root',required=True);init.add_argument('--actor-name',required=True)
    audit=sub.add_parser('audit');audit.add_argument('--root',required=True)
    cloud=sub.add_parser('cloud-init');cloud.add_argument('--config',required=True)
    args=p.parse_args()
    try:
        if args.cmd=='init':
            runtime_check();tenant,ledger,actor=[new_id() for _ in range(3)];root=Path(args.root).expanduser().resolve()
            db=Database.initialize(root,tenant,ledger,actor,args.actor_name);db.close()
            key=secrets.token_hex(32);sock=str(root/'crm.sock')
            server={'runtime_root':str(root),'socket':sock,'cursor_key_hex':secrets.token_hex(32),'principals':{'operator':{'key_hex':key,'actor_id':actor,'capabilities':sorted(ALL_CAPS|{'audit.read'})}},'artifact_registry':{},'cloud':None,'ingress':None}
            client={'socket':sock,'key_id':'operator','key_hex':key}
            write_new(root/'broker.json',server);write_new(root/'client.json',client);fsync_dir(root)
            result={'state':'PROVISIONED_LOCAL_ONLY','tenant_id':tenant,'ledger_id':ledger,'actor_id':actor,'broker_config':str(root/'broker.json'),'client_config':str(root/'client.json')}
        elif args.cmd=='cloud-init':
            from crm.codec import loads
            from crm.quota import Scheduler
            from crm.google_api import ServiceAccount,GoogleREST,Sheets
            from crm.sync import Publisher
            from crm.provision import LayoutProvisioner
            path=Path(args.config).expanduser()
            if path.is_symlink() or path.stat().st_mode&0o077:raise CRMError('INSECURE_BROKER_CONFIG',exit_code=4)
            config=loads(path.read_bytes(),4*1024*1024);cloud=config.get('cloud')
            if not cloud:raise CRMError('CLOUD_NOT_CONFIGURED')
            db=Database(config['runtime_root']);scheduler=None
            try:
                engine=Engine(db,artifact_registry=config.get('artifact_registry',{}))
                scheduler=Scheduler(cloud['quota_root'],cloud['consumer_project'],cloud['principal'])
                creds=ServiceAccount(cloud['service_account_file'],['https://www.googleapis.com/auth/spreadsheets'],scheduler)
                rest=GoogleREST(creds,scheduler);transport=Sheets(rest,cloud['spreadsheet_id'],cloud['sheet_ids'])
                publisher=Publisher(engine,transport,scheduler,cloud)
                result=LayoutProvisioner(publisher).run()
            finally:
                if scheduler:scheduler.close()
                db.close()
        else:
            db=Database(args.root)
            try:
                # Read-only audit does not attach an engine or mutate restart holds.
                from crm.engine import verify_chain
                result=verify_chain(db)
            finally:db.close()
        print(jcs(result).decode());return 0
    except CRMError as exc:
        print(jcs({'ok':False,'error':exc.code,'message':str(exc)}).decode());return exc.exit_code
    except FileExistsError:
        print(jcs({'ok':False,'error':'EXISTS_NO_OVERWRITE'}).decode());return 7
if __name__=='__main__':raise SystemExit(main())
