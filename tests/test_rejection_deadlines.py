"""Coordinator-found stalled rejection/send paths. Tiny in-process ASGI faults."""
import asyncio
import pytest
from starlette.responses import JSONResponse
from reprolens.limits import RequestBudgetMiddleware


@pytest.mark.parametrize('kind',['rejected','normal','bad_input','upload_timeout'])
@pytest.mark.parametrize('blocked_phase',['start','body'])
def test_every_reply_has_bounded_send_and_no_second_headers(kind,blocked_phase):
    async def check():
        metrics=dict(active=0,peak_active=0,rejected=0,requests=0,errors=0,total_ms=0.,timeouts=0,disconnected=0)
        headers=[];blocked=[];released=[]
        async def receive():
            if kind=='upload_timeout':await asyncio.sleep(30)
            return {'type':'http.request','body':b'','more_body':False}
        async def send(message):
            if message['type']=='http.response.start':headers.append(message['status'])
            if (message['type']=='http.response.start')==(blocked_phase=='start'):
                blocked.append(True)
                try:await asyncio.sleep(30)
                finally:released.append(True)
        async def endpoint(scope,receive,send):
            if kind=='upload_timeout':await receive()
            await JSONResponse({'test':'synthetic'},status_code=422 if kind=='bad_input' else 200)(scope,receive,send)
        app=RequestBudgetMiddleware(endpoint,metrics,limit=0 if kind=='rejected' else 1,idle_timeout=.02)
        await asyncio.wait_for(app({'type':'http','method':'POST'},receive,send),timeout=.3)
        assert len(headers)==1
        assert metrics['active']==0 and metrics['timeouts']>=1
        assert blocked==released==[True]
    asyncio.run(check())
