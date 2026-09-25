"""Restricted content-addressed opaque files with durability before SQL pointers."""
from pathlib import Path
import hashlib, os, stat, tempfile
from .errors import CRMError

def check_root(root: Path):
    resolved = root.expanduser().resolve()
    forbidden = ('cloudstorage', 'google drive', 'googledrive', 'dropbox', 'onedrive', 'icloud', '.git')
    if any(any(word in part.lower() for word in forbidden) for part in resolved.parts):
        raise CRMError('SYNCED_DATA_ROOT', exit_code=7)
    package_root=Path(__file__).resolve().parent.parent
    if resolved==package_root or resolved.is_relative_to(package_root):
        raise CRMError('DATA_INSIDE_SOURCE_BUNDLE',exit_code=7)
    if any((parent/'.git').exists() for parent in (resolved,*resolved.parents)):
        raise CRMError('DATA_INSIDE_REPOSITORY',exit_code=7)
    return resolved

def private_dir(root: Path):
    root = check_root(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise CRMError('INSECURE_DIRECTORY', exit_code=7)
    return root

def fsync_dir(path: Path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

class Vault:
    def __init__(self, root: Path, limit=1048576):
        self.root = private_dir(root)
        self.limit = limit

    def put(self, data: bytes) -> tuple[str, int]:
        if len(data) > self.limit:
            raise CRMError('EVIDENCE_TOO_LARGE')
        name = hashlib.sha256(data).hexdigest()
        target = self.root / name
        if target.exists():
            if target.is_symlink() or target.read_bytes() != data:
                raise CRMError('VAULT_INTEGRITY', exit_code=7)
            return name, len(data)
        fd, tmp = tempfile.mkstemp(prefix='.new-', dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.link(tmp, target)  # no-overwrite publication on the same filesystem
            fsync_dir(self.root)
        except FileExistsError:
            if target.read_bytes() != data:
                raise CRMError('VAULT_INTEGRITY', exit_code=7)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return name, len(data)

    def get(self, name: str) -> bytes:
        if len(name) != 64 or any(c not in '0123456789abcdef' for c in name):
            raise CRMError('INVALID_OBJECT_REF')
        path = self.root/name
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_size > self.limit:
                raise CRMError('VAULT_OBJECT_TYPE', exit_code=7)
            with os.fdopen(fd, 'rb', closefd=False) as f: data = f.read(self.limit+1)
        finally: os.close(fd)
        if hashlib.sha256(data).hexdigest() != name:
            raise CRMError('VAULT_INTEGRITY', exit_code=7)
        return data
