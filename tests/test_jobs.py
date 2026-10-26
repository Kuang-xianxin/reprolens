import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reprolens.app import create_app
from reprolens.evidence import make_source, rule_extract
from reprolens.jobs import InstanceLease, Job, JobStore
from reprolens.model import ModelFailure, ModelSettings
from reprolens.store import Store, now
from reprolens.workflow import FlowState, ModelGateway, run_workflow, source_key


def path():
    return Path(__file__).resolve().parents[1]/'runtime/tests'/('jobs-'+str(uuid4())+'.sqlite3')


def config():
    return ModelSettings(base_url='http://127.0.0.1:11436/v1',model='fixture',timeout=2)


async def success(settings,sources):
    return rule_extract(sources), {'model':'fixture'}


def create(c,title='Synthetic task'):
    return c.post('/api/cases',json={'title':title,'description':'Actual: Preview shows zero records.\nExpected: Preview shows one record.'}).json()


def submit(c,case,key=None):
    return c.post('/api/cases/'+case['id']+'/jobs',json={'revision':case['revision'],'request_id':key or str(uuid4()),'language':'en'})


def wait(c,case,job):
    deadline=time.monotonic()+6
    while time.monotonic()<deadline:
        value=c.get(f"/api/cases/{case['id']}/jobs/{job['id']}").json()
        if value['status'] not in ('queued','running'):return value
        time.sleep(.02)
    raise AssertionError('job did not finish')


def test_durable_graph_main_path_and_atomic_commit():
    with TestClient(create_app(path(),config(),success)) as c:
        case=create(c);key=str(uuid4());job=submit(c,case,key).json();done=wait(c,case,job)
        assert done['status']=='ready' and done['result_revision']==2
        current=c.get('/api/cases/'+case['id']).json()
        assert current['analysis']['workflow']=='langgraph-v1'
        assert current['analysis']['source_revision']==1 and current['review'] is None
        assert c.get('/api/cases/'+case['id']+'/issue.md').status_code==409
        row=c.app.state.worker.jobs.get(job['id'])
        assert row['checkpoint_hash']==hashlib.sha256(row['checkpoint'].encode()).hexdigest()
        assert len(c.get('/api/cases/'+case['id']+'/history').json())==2
        assert submit(c,case,key).json()==done


def test_idempotency_queue_bound_and_real_cancel_release():
    async def slow(settings,sources):await asyncio.sleep(10)
    with TestClient(create_app(path(),config(),slow)) as c:
        cases=[create(c,str(i)) for i in range(5)]
        key=str(uuid4());first=submit(c,cases[0],key).json()
        assert submit(c,cases[0],key).json()['id']==first['id']
        assert submit(c,cases[1],key).status_code==409
        assert submit(c,cases[0]).json()['id']==first['id']
        for case in cases[1:4]:assert submit(c,case).status_code==202
        rejection=submit(c,cases[4]);assert rejection.status_code==429
        assert rejection.headers['Retry-After']=='3'
        result=c.post(f"/api/cases/{cases[0]['id']}/jobs/{first['id']}/cancel",json={}).json()
        assert result['status']=='cancelled'
        assert c.app.state.worker.active_id!=first['id'] or not c.app.state.gateway.flights
        assert c.get('/api/cases/'+cases[0]['id']).json()['revision']==1
        assert submit(c,cases[4]).status_code==202


def test_changed_source_rejects_late_result():
    async def delayed(settings,sources):
        await asyncio.sleep(.2)
        return await success(settings,sources)
    with TestClient(create_app(path(),config(),delayed)) as c:
        case=create(c);job=submit(c,case).json()
        saved=c.put('/api/cases/'+case['id']+'/draft',json={'revision':1,'title':case['title'],'fields':{'observed':'My retained edit'}}).json()
        done=wait(c,case,job)
        assert done['status']=='superseded'
        assert c.get('/api/cases/'+case['id']).json()==saved


def test_restart_from_extracted_checkpoint_without_second_inference():
    db=path();app=create_app(db,config(),success)
    with TestClient(app) as c:case=create(c)
    store=Store(db);jobs=JobStore(store);job=jobs.submit(case,config(),'en',str(uuid4()))
    jobs.take()
    state=FlowState(sources=case['sources'],source_revision=1,language='en',stage='extracted',extraction=rule_extract(case['sources']),meta={'model':'fixture'})
    jobs.checkpoint(job['id'],state.model_dump(mode='json'))
    calls=0
    async def forbidden(settings,sources):
        nonlocal calls
        calls+=1
        raise AssertionError('checkpoint must skip inference')
    with TestClient(create_app(db,config(),forbidden)) as c:
        done=wait(c,case,job)
        assert done['status']=='ready' and done['attempts']==2 and calls==0


def test_checkpoint_tampering_and_restart_limit_are_explicit():
    db=path()
    with TestClient(create_app(db,config(),success)) as c:case=create(c)
    jobs=JobStore(Store(db));job=jobs.submit(case,config(),'en',str(uuid4()));jobs.take()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET checkpoint='{}',checkpoint_hash='bad' WHERE id=?",(job['id'],))
    with TestClient(create_app(db,config(),success)) as c:
        done=wait(c,case,job)
        assert done['status']=='failed' and done['error']=='checkpoint_mismatch'
        assert c.get('/api/cases/'+case['id']).json()['revision']==1
    with sqlite3.connect(db) as conn:conn.execute("UPDATE jobs SET status='running',attempts=2 WHERE id=?",(job['id'],))
    jobs.recover();assert jobs.get(job['id'])['error']=='restart_limit'


def test_dependency_failure_does_not_destroy_confirmed_draft_and_worker_survives():
    calls=0
    async def flaky(settings,sources):
        nonlocal calls
        calls+=1
        if calls==1:raise RuntimeError('synthetic private diagnostic must not be exposed')
        return await success(settings,sources)
    with TestClient(create_app(path(),config(),flaky)) as c:
        case=create(c)
        case=c.put('/api/cases/'+case['id']+'/draft',json={'revision':1,'title':case['title'],'fields':{'observed':'Retained actual result'}}).json()
        case=c.post('/api/cases/'+case['id']+'/confirm',json={'revision':2,'sources_reviewed':True,'privacy_reviewed':True}).json()
        done=wait(c,case,submit(c,case).json())
        assert done['error']=='processing_failed'
        assert c.get('/api/cases/'+case['id']).json()==case
        assert wait(c,case,submit(c,case).json())['status']=='ready'
        assert c.get('/api/ready').status_code==200


def test_gateway_singleflight_cache_version_circuit_and_waiter_cancellation():
    async def check():
        calls=0
        async def runner(settings,sources):
            nonlocal calls
            calls+=1;await asyncio.sleep(.03)
            return rule_extract(sources), {'model':'fixture'}
        sources=[make_source('s0','description','description','Observed: error')]
        gate=ModelGateway(config(),runner,capacity=2,ttl=.1,cooldown=.03)
        results=await asyncio.gather(*[gate.infer('same',sources,'en') for _ in range(30)])
        assert calls==1 and gate.metrics['coalesced']==29 and len(results)==30
        await gate.infer('same',sources,'en');assert calls==1
        await gate.infer('revision2',sources,'en');assert calls==2
        await gate.infer('revision3',sources,'en');assert len(gate.cache)==2
        await asyncio.sleep(.13);await gate.infer('revision3',sources,'en');assert calls==4
        async def bad(settings,sources):raise ModelFailure('connection_error')
        gate=ModelGateway(config(),bad,cooldown=.03)
        for i in range(3):
            with pytest.raises(ModelFailure):await gate.infer(str(i),sources,'en')
        with pytest.raises(ModelFailure,match='model_cooling_down'):await gate.infer('4',sources,'en')
        await asyncio.sleep(.04);gate.runner=runner
        await gate.infer('5',sources,'en');assert gate.failures==0
        gate=ModelGateway(config(),runner)
        leader=asyncio.create_task(gate.infer('shared',sources,'en'))
        await asyncio.sleep(.005)
        waiter=asyncio.create_task(gate.infer('shared',sources,'en'))
        await asyncio.sleep(.005);waiter.cancel()
        await asyncio.gather(waiter,return_exceptions=True)
        await leader;assert not gate.flights
    asyncio.run(check())


def test_service_lease_and_strict_state():
    db=path();Store(db)
    first=InstanceLease(db);second=InstanceLease(db)
    first.acquire()
    with pytest.raises(RuntimeError):second.acquire()
    first.release();second.acquire();second.release()
    with pytest.raises(ValueError):FlowState(sources=[],source_revision=1,stage='confirmed')
    with pytest.raises(ValueError):FlowState(sources=[],source_revision=0)


def test_wrong_case_task_and_upper_bounds():
    with TestClient(create_app(path(),config(),success)) as c:
        a,b=create(c),create(c);job=submit(c,a).json()
        assert c.get(f"/api/cases/{b['id']}/jobs/{job['id']}").status_code==404
        assert c.post(f"/api/cases/{b['id']}/jobs/{job['id']}/cancel",json={}).status_code==404
        assert c.get('/api/cases?offset=10001').status_code==422
        assert c.post('/api/cases/'+a['id']+'/jobs',json={'revision':'1','request_id':str(uuid4())}).status_code==422
        assert c.post('/api/cases/'+b['id']+'/confirm',json={'revision':1,'sources_reviewed':'true','privacy_reviewed':True}).status_code==422
