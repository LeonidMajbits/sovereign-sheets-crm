"""Tests explicitly use the installed SQLite for behavioral compatibility only.
The production floor is NOT bypassable through any runtime flag or environment.
Target SQLite>=3.51.3 rerun remains a release gate when this interpreter is older.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pytest
import crm.db as dbmod
from crm.db import Database
from crm.engine import Engine,ActorContext,ALL_CAPS
from crm.ids import new_id
from crm.quota import Scheduler
from crm.sync import Publisher
from tests.fakes import Clock,MemorySheets

@pytest.fixture(autouse=True)
def allow_test_sqlite(monkeypatch):
    monkeypatch.setattr(dbmod,'MIN_SQLITE',min(dbmod.MIN_SQLITE,dbmod.sqlite3.sqlite_version_info))

@pytest.fixture
def core(tmp_path):
    ids=[new_id() for _ in range(3)];root=tmp_path/'runtime';root.mkdir(mode=0o700)
    db=Database.initialize(root,*ids)
    engine=Engine(db);actor=ActorContext(ids[2],ALL_CAPS|{'audit.read'})
    yield engine,actor
    db.close()

@pytest.fixture
def cloud(core,tmp_path):
    engine,actor=core;clock=Clock();q=Scheduler(tmp_path/'shared_quota','test-project','test-principal',clock=clock,pace=15)
    config={'spreadsheet_id':'synthetic-spreadsheet','generation_id':new_id(),'sheet_ids':{'Directory':101,'Active Pipeline':102,'Completed Archives':103,'_Control':104,'_Changes':105}}
    transport=MemorySheets(config,q);publisher=Publisher(engine,transport,q,config);publisher.activate()
    yield engine,actor,publisher,transport,q,clock
    q.close()
