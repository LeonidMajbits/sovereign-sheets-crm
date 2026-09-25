"""Single-owner SQLite authority. No cloud I/O is allowed in write transactions."""
from __future__ import annotations
import contextlib, fcntl, hashlib, os, sqlite3, threading
from pathlib import Path
from .codec import ZERO, utcnow, ulid, digest
from .errors import CRMError
from .storage import private_dir, fsync_dir

MIN_SQLITE = (3, 51, 3)
ROOT = Path(__file__).resolve().parent.parent
DDL = ROOT/'schema/crm_schema_v4.sql'
DDL_SHA = '3de6e4f720f8b25c9e52d52c7ba94d18759f50e7d03ff0515f2f0126ed3a11dd'

def runtime_check():
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise CRMError('UNSUPPORTED_SQLITE', f'Linked SQLite {sqlite3.sqlite_version}; require >=3.51.3.', 7)

def connect(path: Path, readonly=False):
    runtime_check()
    mode = 'ro' if readonly else 'rw'
    conn = sqlite3.connect(path.as_uri()+f'?mode={mode}', uri=True, isolation_level=None,
                           timeout=2.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA recursive_triggers=ON')
    conn.execute('PRAGMA trusted_schema=OFF')
    conn.execute('PRAGMA busy_timeout=2000')
    try: conn.enable_load_extension(False)
    except AttributeError: pass
    if not readonly:
        if conn.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower() != 'wal':
            conn.close(); raise CRMError('WAL_UNAVAILABLE', exit_code=7)
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA wal_autocheckpoint=1000')
    if hasattr(conn, 'setlimit'):
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 2*1024*1024)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 1024*1024)
    return conn

class Database:
    def __init__(self, root: str | Path):
        runtime_check()  # fail BEFORE mkdir, files, journals or lock acquisition
        self.root = private_dir(Path(root))
        self.path = self.root/'crm.db'
        if not self.path.exists() or self.path.is_symlink() or self.path.stat().st_mode & 0o077:
            raise CRMError('DATABASE_MISSING_OR_INSECURE', exit_code=7)
        self._lockfile = open(self.root/'authority.lock', 'a+b')
        os.chmod(self.root/'authority.lock', 0o600)
        try: fcntl.flock(self._lockfile, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._lockfile.close(); raise CRMError('AUTHORITY_ALREADY_RUNNING', exit_code=6) from exc
        try:
            self.conn = connect(self.path)
        except Exception:
            self.close(); raise
        self.mutex = threading.RLock()
        self._inside = False
        try:
            row = self.conn.execute('SELECT ddl_digest FROM schema_migrations WHERE version=4').fetchone()
            if not row or row[0] != DDL_SHA:
                raise CRMError('SCHEMA_DIGEST_MISMATCH', exit_code=7)
            self.conn.execute('SELECT count(*) FROM entity_fts').fetchone()
            fp=self.conn.execute("SELECT value FROM runtime_state WHERE key='schema_fingerprint'").fetchone()
            actual=digest([list(r) for r in self.conn.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")])
            if not fp or fp[0]!=actual: raise CRMError('SCHEMA_FINGERPRINT_MISMATCH',exit_code=7)
        except Exception:
            self.close(); raise

    @classmethod
    def initialize(cls, root, tenant_id, ledger_id, actor_id, actor_name='Local operator'):
        runtime_check()
        for x in (tenant_id, ledger_id, actor_id): ulid(x)
        root = private_dir(Path(root))
        if hashlib.sha256(DDL.read_bytes()).hexdigest() != DDL_SHA:
            raise CRMError('DDL_DIGEST_MISMATCH', exit_code=7)
        fd = os.open(root/'crm.db', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        os.close(fd)
        conn = connect(root/'crm.db')
        try:
            conn.executescript('BEGIN IMMEDIATE;\n'+DDL.read_text()+'\n'+(ROOT/'schema/runtime_extension_v5.sql').read_text())
            now = utcnow()
            conn.execute('INSERT INTO ledger_state VALUES(1,?,?,4,1,0,?,1,\'NORMAL\',?)', (tenant_id,ledger_id,ZERO,now))
            conn.execute('INSERT INTO actors VALUES(?,?,?,?,0)', (tenant_id,actor_id,actor_name,'human'))
            conn.execute('INSERT INTO schema_migrations VALUES(4,?,?,NULL,?)', (DDL_SHA,now,'frozen-v4'))
            ext = hashlib.sha256((ROOT/'schema/runtime_extension_v5.sql').read_bytes()).hexdigest()
            conn.execute('INSERT INTO schema_migrations VALUES(5,?,?,NULL,?)', (ext,now,'additive-runtime-v5'))
            from .ids import durable_id
            system_actor=durable_id(conn)
            conn.execute('INSERT INTO actors VALUES(?,?,?,?,0)',(tenant_id,system_actor,'CRM runtime','service'))
            conn.execute('INSERT INTO runtime_state VALUES(?,?)',('system_actor_id',system_actor))
            fingerprint=digest([list(r) for r in conn.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")])
            conn.execute('INSERT INTO runtime_state VALUES(?,?)',('schema_fingerprint',fingerprint))
            conn.commit()
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
        fsync_dir(root)
        return cls(root)

    @contextlib.contextmanager
    def transaction(self):
        with self.mutex:
            if self._inside:
                raise CRMError('REENTRANT_TRANSACTION', exit_code=7)
            self._inside = True
            try:
                self.conn.execute('BEGIN IMMEDIATE')
                yield self.conn
                self.conn.commit()
            except sqlite3.OperationalError as exc:
                self.conn.rollback()
                if 'locked' in str(exc).lower():
                    raise CRMError('BUSY', exit_code=6, retryable=True) from exc
                raise
            except BaseException:
                self.conn.rollback(); raise
            finally:
                self._inside = False

    @contextlib.contextmanager
    def read(self):
        with self.mutex:
            if self._inside:
                raise CRMError('REENTRANT_READ', exit_code=7)
            self.conn.execute('BEGIN')
            try: yield self.conn
            finally: self.conn.rollback()

    def checkpoint(self):
        with self.mutex: return tuple(self.conn.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone())

    def backup(self, destination: Path):
        if destination.exists(): raise CRMError('BACKUP_EXISTS')
        with self.mutex:
            fd = os.open(destination, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600); os.close(fd)
            target = sqlite3.connect(destination)
            try: self.conn.backup(target)
            finally: target.close()
        return hashlib.sha256(destination.read_bytes()).hexdigest()

    def close(self):
        if getattr(self, 'conn', None): self.conn.close(); self.conn = None
        if getattr(self, '_lockfile', None):
            fcntl.flock(self._lockfile, fcntl.LOCK_UN); self._lockfile.close(); self._lockfile = None
