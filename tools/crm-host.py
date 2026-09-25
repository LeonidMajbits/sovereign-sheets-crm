#!/usr/bin/env python3
"""Explicit reference host for standalone acceptance, NOT an auto-start daemon.
Production embedding belongs to the existing lab runtime (integration/embed.py).
No timers or background synchronization are added; sync is invoked explicitly.
"""
import argparse,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from crm.codec import loads,jcs
from crm.db import Database
from crm.engine import Engine
from crm.service import Broker,UnixBrokerServer
from crm.errors import CRMError

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    path=Path(args.config).expanduser()
    if path.is_symlink() or path.stat().st_mode&0o077:raise CRMError('INSECURE_BROKER_CONFIG',exit_code=4)
    config=loads(path.read_bytes(),4*1024*1024);db=Database(config['runtime_root']);server=None;scheduler=None
    try:
        engine=Engine(db,artifact_registry=config.get('artifact_registry',{}));publisher=None;inbox=None
        if config.get('cloud'):
            from crm.quota import Scheduler
            from crm.google_api import ServiceAccount,GoogleREST,Sheets
            from crm.sync import Publisher
            cloud=config['cloud'];scheduler=Scheduler(cloud['quota_root'],cloud['consumer_project'],cloud['principal'])
            creds=ServiceAccount(cloud['service_account_file'],['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive.readonly'],scheduler)
            rest=GoogleREST(creds,scheduler);transport=Sheets(rest,cloud['spreadsheet_id'],cloud['sheet_ids'])
            publisher=Publisher(engine,transport,scheduler,cloud)
            # Activation is explicit provisioning, never an automatic overwrite.
            with db.read() as c:
                if not c.execute("SELECT 1 FROM projection_resources WHERE state='ACTIVE'").fetchone():raise CRMError('CLOUD_NOT_ACTIVATED',exit_code=7)
            if config.get('ingress'):
                from crm.ingress import DriveInbox
                inbox=DriveInbox(engine,rest,config['ingress'])
        broker=Broker(engine,publisher=publisher,inbox=inbox,cursor_key=bytes.fromhex(config['cursor_key_hex']))
        server=UnixBrokerServer(config['socket'],broker,config['principals'])
        print('Reference host ready; no automatic sync loop.',file=sys.stderr)
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        if server:
            server.server_close();Path(config['socket']).unlink(missing_ok=True)
        if scheduler:scheduler.close()
        db.close()
if __name__=='__main__':
    try:main()
    except CRMError as exc:
        print(jcs({'ok':False,'error':exc.code,'message':str(exc)}).decode());raise SystemExit(exc.exit_code)
