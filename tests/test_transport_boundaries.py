"""Coordinator-found lifecycle regressions; no real model or credentials."""
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from starlette.responses import StreamingResponse
from reprolens.app import create_app
from reprolens.model import ModelSettings
from reprolens.limits import RequestBudgetMiddleware

def path():return Path(__file__).resolve().parents[1]/'runtime/tests'/('transport-'+str(uuid4())+'.sqlite3')

def test_default_settings_ignore_inherited_provider_configuration(monkeypatch):
    monkeypatch.setenv('OPENAI_BASE_URL','https://paid-provider.invalid/v1')
    monkeypatch.setenv('OPENAI_MODEL','external-model')
    monkeypatch.setenv('OPENAI_API_KEY','fixture-not-a-real-key')
    monkeypatch.setenv('REPROLENS_ALLOW_REMOTE_MODEL','1')
    config=ModelSettings.from_env()
    assert not config.base_url and not config.model and not config.api_key and not config.allow_remote

def scope(path,method='GET'):
    return {'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','headers':[(b'host',b'testserver'),(b'content-type',b'application/json')],'server':('testserver',80),'client':('127.0.0.1',9000),'root_path':''}

@pytest.mark.parametrize('kind',['slow_upload','slow_download'])
def test_admission_includes_upload_and_full_response(kind):
    async def exercise():
        app=create_app(path(),settings=ModelSettings())
        release=asyncio.Event();entered=0;started=asyncio.Event()
        @app.get('/slow-response')
        async def slow_response():
            async def body():
                yield b'first'
                await release.wait()
                yield b'last'
            return StreamingResponse(body())
        async def one():
            nonlocal entered
            if kind=='slow_upload':
                async def receive():
                    nonlocal entered
                    entered+=1
                    if entered==32:started.set()
                    await release.wait()
                    return {'type':'http.request','body':b'{"title":"slow","description":"error"}','more_body':False}
                async def send(message):pass
                await app(scope('/api/cases','POST'),receive,send)
            else:
                async def receive():
                    await release.wait()
                    return {'type':'http.disconnect'}
                async def send(message):
                    nonlocal entered
                    if message['type']=='http.response.body' and message.get('body')==b'first':
                        entered+=1
                        if entered==32:started.set()
                await app(scope('/slow-response'),receive,send)
        tasks=[asyncio.create_task(one()) for _ in range(32)]
        try:
            await asyncio.wait_for(started.wait(),5)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                response=await client.get('/api/health')
                assert response.status_code==503
        finally:
            release.set()
            await asyncio.gather(*tasks,return_exceptions=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            assert (await client.get('/api/health')).status_code==200
    asyncio.run(exercise())

def test_analysis_sqlite_lock_does_not_block_health_event_loop():
    async def exercise():
        db=path();app=create_app(db,settings=ModelSettings())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
            case=(await c.post('/api/cases',json={'title':'Locked','description':'An error'})).json()
            with sqlite3.connect(db) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                started=time.monotonic()
                request=asyncio.create_task(c.post('/api/cases/'+case['id']+'/analyze',json={'revision':1,'mode':'ai'}))
                await asyncio.sleep(.05)
                assert (await c.get('/api/health')).status_code==200
                latency=time.monotonic()-started
                response=await request
                assert response.status_code==503
                assert latency<.6
    asyncio.run(exercise())

def test_upload_disconnect_releases_admission():
    async def exercise():
        app=create_app(path(),settings=ModelSettings())
        async def receive():return {'type':'http.disconnect'}
        async def send(message):pass
        await app(scope('/api/cases','POST'),receive,send)
        assert app.state.metrics['active']==0 and app.state.metrics['disconnected']==1
    asyncio.run(exercise())

@pytest.mark.parametrize('kind',['receive_timeout','send_timeout','cancelled'])
def test_timeout_and_cancel_release_full_lifecycle(kind):
    async def exercise():
        metrics=dict(requests=0,rejected=0,active=0,peak_active=0,errors=0,total_ms=0,timeouts=0,disconnected=0)
        blocked=asyncio.Event();seen=[]
        async def receive():await blocked.wait()
        async def send(message):
            if kind=='send_timeout' and message['type']=='http.response.body':await blocked.wait()
            seen.append(message)
        async def downstream(scope,receive,send):
            if kind=='receive_timeout':await receive()
            else:
                await send({'type':'http.response.start','status':200,'headers':[]})
                if kind=='cancelled':await blocked.wait()
                await send({'type':'http.response.body','body':b'x'})
        middleware=RequestBudgetMiddleware(downstream,metrics,idle_timeout=.03)
        task=asyncio.create_task(middleware(scope('/'),receive,send))
        if kind=='cancelled':
            await asyncio.sleep(.01);task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:await task
        assert metrics['active']==0
        if kind=='cancelled':assert metrics['disconnected']==1
        elif kind=='receive_timeout':assert seen[0]['status']==408 and metrics['timeouts']==1
        else:assert metrics['errors']==1 and metrics['timeouts']==1
    asyncio.run(exercise())
