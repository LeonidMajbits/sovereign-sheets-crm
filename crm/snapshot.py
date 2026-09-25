"""Signed, complete local snapshots; restoration is fenced in RECOVERY_HOLD.

Verification keys are supplied independently, never trusted from the archive.
This module does not promote a restored database or fence another running host.
"""
from __future__ import annotations
import hashlib,os,shutil,sqlite3
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey,Ed25519PublicKey
from .codec import jcs,loads,utcnow,digest
from .ids import new_id
from .errors import CRMError
from .storage import fsync_dir,private_dir
from .db import runtime_check


def file_hash(path):
    h=hashlib.sha256();n=0
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block);n+=len(block)
    return h.hexdigest(),n


def copy_checked(source,target,expected=None):
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    h=hashlib.sha256();n=0
    try:
        with source.open('rb') as src,os.fdopen(fd,'wb') as out:
            for block in iter(lambda:src.read(1024*1024),b''):
                h.update(block);n+=len(block);out.write(block)
            out.flush();os.fsync(out.fileno())
    except BaseException:
        try:os.close(fd)
        except OSError:pass
        raise
    if expected is not None and h.hexdigest()!=expected:raise CRMError('SNAPSHOT_PART_CHANGED',exit_code=7)
    return h.hexdigest(),n


def create_snapshot(engine,destination,signing_key:Ed25519PrivateKey,signer_key_id:str):
    destination=Path(destination)
    if destination.exists():raise CRMError('SNAPSHOT_DESTINATION_EXISTS')
    destination.mkdir(parents=True,mode=0o700);parts=[];sid=new_id()
    with engine.db.mutex:
        audit=engine.verify_audit();state=engine.state()
        engine.db.backup(destination/'crm.db')
        h,n=file_hash(destination/'crm.db');parts.append({'path':'crm.db','sha256':h,'bytes':str(n)})
        with engine.db.read() as c:
            evidence={r[0] for r in c.execute('SELECT evidence_object_ref FROM quarantine_proposals')}
            publications={r[0] for r in c.execute('SELECT payload_object_ref FROM publication_batches')}
            artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts')]
            claims=c.execute("SELECT count(*) FROM claims WHERE claim_state!='UNCLAIMED'").fetchone()[0]
        for category,refs,vault in (('evidence',evidence,engine.vault),('publications',publications,engine.objects)):
            for ref in sorted(refs):
                # Verify the opaque source before copying; never render it.
                vault.get(ref)
                h,n=copy_checked(vault.root/ref,destination/category/ref,ref)
                parts.append({'path':category+'/'+ref,'sha256':h,'bytes':str(n)})
        registry={}
        for artifact in artifacts:
            ref=artifact['object_ref']
            if ref not in engine.artifact_registry:raise CRMError('SNAPSHOT_ARTIFACT_COVERAGE',exit_code=7)
            relative='artifacts/'+artifact['artifact_id']
            h,n=copy_checked(Path(engine.artifact_registry[ref]),destination/relative,artifact['sha256'])
            if n!=artifact['size_bytes']:raise CRMError('SNAPSHOT_ARTIFACT_COVERAGE',exit_code=7)
            parts.append({'path':relative,'sha256':h,'bytes':str(n)});registry[ref]=relative
        manifest={'protocol':'crm.checkpoint.v1','snapshot_id':sid,'schema_version':'4','runtime_extension':'5','tenant_id':state['tenant_id'],'ledger_id':state['ledger_id'],'authority_epoch':str(state['authority_epoch']),'terminal_commit_seq':str(state['commit_seq']),'chain_head_digest':audit['head_digest'],'search_generation':str(state['search_generation']),'signer_key_id':signer_key_id,'recorded_at':utcnow(),'parts':parts,'artifact_registry':registry,'active_claims':str(claims),'coverage':'database+dedup+tombstones+evidence+prepared_publications+registered_artifacts'}
        raw=jcs(manifest);signature=signing_key.sign(b'CRM3:checkpoint:v1\n'+raw)
        for name,data in [('manifest.json',raw),('manifest.sig',signature)]:
            fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        fsync_dir(destination)
        verify_snapshot(destination,signing_key.public_key(),state['ledger_id'])
        with engine.db.transaction() as c:
            c.execute('INSERT INTO snapshot_manifests VALUES(?,?,?,?,?,?,?,?)',(state['tenant_id'],sid,state['commit_seq'],digest(raw),'snapshot:'+sid,signer_key_id,signature,utcnow()))
    return manifest


def verify_snapshot(root,public_key:Ed25519PublicKey,expected_ledger:str):
    root=Path(root).resolve();raw=(root/'manifest.json').read_bytes()
    if len(raw)>4*1024*1024:raise CRMError('SNAPSHOT_MANIFEST_LIMIT')
    manifest=loads(raw,4*1024*1024)
    if jcs(manifest)!=raw or manifest.get('protocol')!='crm.checkpoint.v1' or manifest.get('ledger_id')!=expected_ledger:raise CRMError('SNAPSHOT_IDENTITY',exit_code=7)
    try:public_key.verify((root/'manifest.sig').read_bytes(),b'CRM3:checkpoint:v1\n'+raw)
    except Exception as exc:raise CRMError('SNAPSHOT_SIGNATURE',exit_code=7) from exc
    seen=set()
    for part in manifest['parts']:
        path=root/part['path']
        if path.is_symlink() or not path.resolve().is_relative_to(root) or part['path'] in seen:raise CRMError('SNAPSHOT_PART_PATH',exit_code=7)
        h,n=file_hash(path)
        if h!=part['sha256'] or str(n)!=part['bytes']:raise CRMError('SNAPSHOT_PART_DIGEST',exit_code=7)
        seen.add(part['path'])
    if 'crm.db' not in seen:raise CRMError('SNAPSHOT_MISSING_DATABASE',exit_code=7)
    return manifest


def restore_fenced(root,destination,public_key:Ed25519PublicKey,expected_ledger:str):
    runtime_check()
    root=Path(root);manifest=verify_snapshot(root,public_key,expected_ledger)
    destination=Path(destination)
    if destination.exists():raise CRMError('RESTORE_DESTINATION_EXISTS')
    destination=private_dir(destination)
    for part in manifest['parts']:copy_checked(root/part['path'],destination/part['path'],part['sha256'])
    # Never reissue work from stale history. No CLI command silently clears this.
    c=sqlite3.connect(destination/'crm.db',isolation_level=None)
    try:
        c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE ledger_state SET mode='RECOVERY_HOLD' WHERE singleton=1");c.commit()
    finally:c.close()
    fsync_dir(destination)
    return {'state':'RECOVERY_HOLD','ledger_id':expected_ledger,'source_snapshot_id':manifest['snapshot_id'],'artifact_registry':{ref:str(destination/path) for ref,path in manifest['artifact_registry'].items()},'promotion':'requires separately verified old-authority and executor fencing; not automatic'}
