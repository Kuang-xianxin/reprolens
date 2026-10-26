import asyncio
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reprolens.app import create_app
from reprolens.database import inspect, restore
from reprolens.evidence import make_source, rule_extract
from reprolens.jobs import JobStore,db_call
from reprolens.model import ModelFailure, ModelSettings
from reprolens.store import Store, now
from reprolens.workflow import ModelGateway

ROOT=Path(__file__).resolve().parents[1]
def path():return ROOT/'runtime/tests'/('faults-'+str(uuid4())+'.sqlite3')
async def good(settings,sources):return rule_extract(sources),{'model':'fixture'}


def test_v1_migration_backup_summary_atomicity_and_new_path_restore():
    db=path();db.parent.mkdir(parents=True,exist_ok=True)
    source=make_source('s0','description','description','Actual: error')
    doc=dict(id='old',revision=1,title='Legacy',sources=[source],created_at=now(),updated_at=now(),analysis=None,review=None)
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE cases(id TEXT PRIMARY KEY,revision INTEGER,document TEXT)')
        c.execute('INSERT INTO cases VALUES(?,?,?)',('old',1,json.dumps(doc)))
        c.execute('PRAGMA user_version=1')
    store=Store(db);assert store.get('old')==doc and store.list()[0]['id']=='old'
    backup=list(db.parent.glob(db.name+'.pre-v2-*'));assert len(backup)==1
    assert inspect(backup[0])['schema_version']==1
    Store(db);assert len(list(db.parent.glob(db.name+'.pre-v2-*')))==1
    with store.connection() as c:
        c.execute("CREATE TRIGGER fail_summary BEFORE UPDATE ON cases BEGIN SELECT RAISE(ABORT,'synthetic disk write failure'); END")
    changed=store.get('old');changed['title']='must not commit'
    with pytest.raises(sqlite3.IntegrityError):store.save(changed,1)
    assert store.get('old')==doc and store.list()[0]['title']=='Legacy'
    archived=db.with_suffix('.backup');store.backup(archived)
    target=db.with_suffix('.restored');assert restore(archived,target)==inspect(archived)
    assert Store(target).get('old')==doc


def test_slow_query_progress_deadline_and_connection_recovery():
    store=Store(path())
    started=time.monotonic()
    with pytest.raises(sqlite3.OperationalError,match='interrupted'):
        with store.connection() as c:
            c.execute('WITH RECURSIVE cnt(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM cnt WHERE x<100000000) SELECT sum(x) FROM cnt').fetchone()
    assert time.monotonic()-started<2
    assert store.ready()==2


def test_checkpoint_write_failure_isolated_worker_recovers(monkeypatch):
    with TestClient(create_app(path(),ModelSettings(model='fixture',timeout=1),good)) as c:
        case=c.post('/api/cases',json={'title':'Failure recovery','description':'Actual: error'}).json()
        jobs=c.app.state.worker.jobs;real=jobs.checkpoint;calls=0
        def failing(job,state):
            nonlocal calls
            calls+=1
            if calls==1:raise sqlite3.OperationalError('synthetic disk full')
            return real(job,state)
        monkeypatch.setattr(jobs,'checkpoint',failing)
        url='/api/cases/'+case['id']+'/jobs'
        for expected in ['failed','ready']:
            job=c.post(url,json={'revision':1,'request_id':str(uuid4())}).json()
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                done=c.get(url+'/'+job['id']).json()
                if done['status'] not in ('queued','running'):break
                time.sleep(.02)
            assert done['status']==expected
        assert c.get('/api/ready').status_code==200


def test_gateway_owner_cancel_and_waiter_timeout_are_bounded():
    async def check():
        event=asyncio.Event()
        async def block(settings,sources):event.set();await asyncio.sleep(10)
        gateway=ModelGateway(ModelSettings(timeout=.1),block)
        owner=asyncio.create_task(gateway.infer('a',[],'en'));await event.wait()
        waiter=asyncio.create_task(gateway.infer('a',[],'en'));await asyncio.sleep(.01)
        owner.cancel();await asyncio.gather(owner,return_exceptions=True)
        result=await asyncio.wait_for(asyncio.gather(waiter,return_exceptions=True),.2)
        assert isinstance(result[0],asyncio.CancelledError) and not gateway.flights
        with pytest.raises(ModelFailure,match='timeout'):await gateway.infer('b',[],'en')
        assert not gateway.flights
    asyncio.run(check())


def test_worker_unexpected_death_is_reported_not_ready():
    with TestClient(create_app(path(),ModelSettings(),good)) as c:
        # Explicit termination is distinguishable from ordinary per-job exceptions.
        c.portal.call(c.app.state.worker.stop)
        assert c.get('/api/ready').status_code==503
        case=c.post('/api/cases',json={'title':'Manual remains usable','description':'Actual: error'}).json()
        assert c.post('/api/cases/'+case['id']+'/jobs',json={'revision':1,'request_id':str(uuid4())}).status_code==503
        assert c.get('/api/cases/'+case['id']).status_code==200


def test_cancelling_database_await_drains_the_underlying_thread():
    async def check():
        finished=[]
        def bounded_write():time.sleep(.08);finished.append(True)
        task=asyncio.create_task(db_call(bounded_write))
        await asyncio.sleep(.01);task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        assert finished==[True]
    asyncio.run(check())
