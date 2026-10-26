import asyncio
import copy
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from reprolens.app import create_app
from reprolens.model import ModelSettings
from reprolens.store import Store

def path():return Path(__file__).resolve().parents[1]/'runtime/tests'/('reliability-'+str(uuid4())+'.sqlite3')

def test_model_backpressure_cancellation_and_release():
    async def exercise():
        started=asyncio.Event()
        async def runner(settings,sources):
            started.set()
            await asyncio.sleep(20)
        app=create_app(path(),settings=ModelSettings(timeout=30),model_runner=runner)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            case=(await client.post('/api/cases',json={'title':'Cancellation','description':'An actual error'})).json()
            url='/api/cases/'+case['id']
            first=asyncio.create_task(client.post(url+'/analyze',json={'revision':1,'mode':'ai'}))
            await started.wait()
            second=await client.post(url+'/analyze',json={'revision':1,'mode':'ai'})
            assert second.status_code==429 and second.headers['Retry-After']=='3'
            operation=(await client.get(url+'/operations')).json()[0]
            assert operation['status']=='running'
            cancelled=await client.post(url+'/operations/'+operation['id']+'/cancel',json={})
            assert cancelled.json()['status']=='cancellation_requested'
            result=(await first).json()
            assert result['last_attempt']['error']=='cancelled'
            assert (await client.get('/api/metrics')).json()['model_active']==0
            assert (await client.get(url+'/operations')).json()[0]['status']=='failed'
            assert (await client.post(url+'/analyze',json={'revision':result['revision'],'mode':'rules'})).status_code==200
    asyncio.run(exercise())

def test_database_busy_is_bounded_and_retryable():
    db=path()
    with TestClient(create_app(db,settings=ModelSettings())) as c:
        with sqlite3.connect(db) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            start=time.monotonic()
            response=c.post('/api/cases',json={'title':'Busy','description':'An error'})
            elapsed=time.monotonic()-start
            assert response.status_code==503 and response.json()['code']=='database_busy'
            assert response.headers['Retry-After']=='1' and elapsed<2.5
        assert c.post('/api/cases',json={'title':'Recovered','description':'An error'}).status_code==201

def test_interrupted_operation_recovers_on_restart():
    db=path()
    with TestClient(create_app(db,settings=ModelSettings())) as c:
        case=c.post('/api/cases',json={'title':'Restart','description':'An error'}).json()
        c.app.state.store.start_operation('unfinished',case['id'],1)
    with TestClient(create_app(db,settings=ModelSettings())) as c:
        op=c.get('/api/cases/'+case['id']+'/operations').json()[0]
        assert op['status']=='interrupted' and op['error']=='service_restarted'
        assert c.get('/api/cases/'+case['id']).json()==case

def test_capacity_and_corruption_fail_without_destroying_source(monkeypatch):
    import reprolens.store as storage
    db=path()
    with TestClient(create_app(db,settings=ModelSettings())) as c:
        case=c.post('/api/cases',json={'title':'Capacity','description':'Original source'}).json()
        monkeypatch.setattr(storage,'MAX_REVISIONS',1)
        response=c.put('/api/cases/'+case['id']+'/draft',json={'revision':1,'title':'Changed','fields':{'observed':'error'}})
        assert response.status_code==507
        assert c.get('/api/cases/'+case['id']).json()==case
        bad=copy.deepcopy(case);bad['sources'][0]['text']='tampered'
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE cases SET document=? WHERE id=?',(json.dumps(bad),case['id']))
        response=c.get('/api/cases/'+case['id'])
        assert response.status_code==503 and response.json()['code']=='integrity_failed'
        assert c.get('/api/cases/'+case['id']+'/history/1').json()==case

def test_ordered_list_uses_index_and_paging_is_bounded():
    db=path();store=Store(db)
    with sqlite3.connect(db) as conn:
        plan=conn.execute("EXPLAIN QUERY PLAN SELECT document FROM cases ORDER BY json_extract(document,'$.updated_at') DESC LIMIT 40").fetchall()
    assert any('cases_updated_idx' in row[3] for row in plan)
    with TestClient(create_app(db,settings=ModelSettings())) as c:
        assert c.get('/api/cases?limit=101').status_code==422

def test_deadline_and_request_ids():
    async def runner(settings,sources):
        await asyncio.sleep(2)
    with TestClient(create_app(path(),settings=ModelSettings(timeout=.03),model_runner=runner)) as c:
        created=c.post('/api/cases',json={'title':'Deadline','description':'An error'})
        assert created.headers['X-Request-ID']
        case=created.json()
        response=c.post('/api/cases/'+case['id']+'/analyze',json={'revision':1,'mode':'ai'})
        assert response.json()['last_attempt']['error']=='timeout'
        assert c.get('/api/metrics').json()['model_active']==0


def test_request_admission_rejects_excess_and_recovers():
    async def exercise():
        app=create_app(path(),settings=ModelSettings())
        entered=0;started=asyncio.Event();release=asyncio.Event()
        @app.get('/test-only-slow')
        async def slow():
            nonlocal entered
            entered+=1
            if entered==32:started.set()
            await release.wait()
            return {'ok':True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            pending=[asyncio.create_task(client.get('/test-only-slow')) for _ in range(32)]
            await started.wait()
            overloaded=await client.get('/api/health')
            assert overloaded.status_code==503 and overloaded.headers['Retry-After']=='1'
            release.set()
            assert all(r.status_code==200 for r in await asyncio.gather(*pending))
            assert (await client.get('/api/health')).status_code==200
    asyncio.run(exercise())
