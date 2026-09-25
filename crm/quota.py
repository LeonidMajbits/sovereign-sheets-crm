"""Shared, persistent physical-call admission across tenant databases.

All brokers sharing a Google principal/project MUST use the same quota_root.
This is transport bookkeeping, not a second business commit authority.
"""
from pathlib import Path
import sqlite3,time,os,threading,random,math
from .db import runtime_check
from .storage import private_dir
from .errors import CRMError

class QuotaHold(CRMError):
    def __init__(self,until):
        super().__init__('QUOTA_HOLD','Physical request deferred by shared quota admission.',10,True)
        self.until=until

class Scheduler:
    LIMITS={'sheets_read':30,'sheets_write':20,'drive_read':30,'drive_write':10,'token':30}
    def __init__(self,root,project,principal,clock=None,pace=15.0,jitter=None):
        runtime_check();self.root=private_dir(Path(root));self.project=project;self.principal=principal
        # During one process lifetime, wall-clock adjustments cannot refill quotas.
        # Persisted UTC-like coordinates retain a conservative full-window hold
        # after restart; live elapsed time is always monotonic in production.
        if clock is None:
            wall_anchor=time.time();mono_anchor=time.monotonic()
            self.clock=lambda:wall_anchor+(time.monotonic()-mono_anchor)
        else:self.clock=clock  # explicit deterministic test clock
        self.pace=pace;self.lock=threading.RLock()
        self.jitter=jitter or random.SystemRandom().random
        path=self.root/'quota.db';new=not path.exists()
        if new:
            try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            except FileExistsError:new=False
        if path.is_symlink() or path.stat().st_mode&0o077:raise CRMError('INSECURE_QUOTA_STORE',exit_code=7)
        self.c=sqlite3.connect(path,isolation_level=None,timeout=2,check_same_thread=False)
        self.c.executescript('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS starts(project TEXT,principal TEXT,kind TEXT,at REAL); CREATE INDEX IF NOT EXISTS starts_window ON starts(project,principal,kind,at); CREATE TABLE IF NOT EXISTS domains(project TEXT,principal TEXT,kind TEXT,not_before REAL,failures INTEGER,last_clock REAL,PRIMARY KEY(project,principal,kind));')
        # Existing scheduler history does not get a free burst after host restart.
        self.restart_until=0 if new else self.clock()+60

    def reserve(self,kind):
        if kind not in self.LIMITS:raise CRMError('QUOTA_CLASS')
        with self.lock:
            now=self.clock();self.c.execute('BEGIN IMMEDIATE')
            try:
                r=self.c.execute('SELECT * FROM domains WHERE project=? AND principal=? AND kind=?',(self.project,self.principal,kind)).fetchone()
                if r and now<r[5]:
                    self.c.execute('UPDATE domains SET not_before=?,last_clock=? WHERE project=? AND principal=? AND kind=?',(now+60,now,self.project,self.principal,kind));self.c.commit();raise QuotaHold(now+60)
                until=max(self.restart_until,r[3] if r else 0)
                if now<until:raise QuotaHold(until)
                times=[x[0] for x in self.c.execute('SELECT at FROM starts WHERE project=? AND principal=? AND kind=? AND at>? ORDER BY at',(self.project,self.principal,kind,now-60))]
                project_count=self.c.execute('SELECT count(*) FROM starts WHERE project=? AND kind=? AND at>?',(self.project,kind,now-60)).fetchone()[0]
                if len(times)>=self.LIMITS[kind] or project_count>=240:raise QuotaHold((times[0]+60.001) if times else now+60)
                if kind=='sheets_write' and times and now-times[-1]<self.pace:raise QuotaHold(times[-1]+self.pace)
                self.c.execute('INSERT INTO starts VALUES(?,?,?,?)',(self.project,self.principal,kind,now))
                self.c.execute('INSERT INTO domains VALUES(?,?,?,0,0,?) ON CONFLICT(project,principal,kind) DO UPDATE SET last_clock=excluded.last_clock',(self.project,self.principal,kind,now))
                self.c.commit()
            except BaseException:
                if self.c.in_transaction:self.c.rollback()
                raise

    def rejected(self,kind,retry_after=0):
        with self.lock:
            self.c.execute('BEGIN IMMEDIATE')
            try:
                r=self.c.execute('SELECT failures,not_before FROM domains WHERE project=? AND principal=? AND kind=?',(self.project,self.principal,kind)).fetchone()
                n=(r[0] if r else 0)+1
                sample=float(self.jitter())
                if not math.isfinite(sample) or not 0.0<=sample<=1.0:raise CRMError('INVALID_JITTER')
                # Full jitter is bounded above, but never bypasses provider/pacing
                # lower bounds. Persistent failures share one five-minute probe.
                delay=300 if n>=8 else sample*min(60,2**n)
                calculated_until=self.clock()+max(delay,retry_after,self.pace if kind=='sheets_write' else 0)
                existing_until=float(r[1]) if (r and r[1] is not None) else 0.0
                until=max(calculated_until,existing_until)
                self.c.execute('INSERT INTO domains VALUES(?,?,?,?,?,?) ON CONFLICT(project,principal,kind) DO UPDATE SET not_before=MAX(domains.not_before,excluded.not_before),failures=excluded.failures,last_clock=excluded.last_clock',(self.project,self.principal,kind,until,n,self.clock()))
                self.c.commit();return until
            except BaseException:self.c.rollback();raise

    def succeeded(self,kind):
        with self.lock:
            now=self.clock()
            self.c.execute('UPDATE domains SET failures=CASE WHEN not_before<=? THEN 0 ELSE failures END,not_before=CASE WHEN not_before<=? THEN 0.0 ELSE not_before END WHERE project=? AND principal=? AND kind=?',(now,now,self.project,self.principal,kind))
    def close(self):self.c.close()
