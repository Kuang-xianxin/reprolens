"""Admission covers receive, endpoint work and final response send, not just headers."""
import asyncio
import json
import logging
import time
from uuid import uuid4
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse


class RequestBudgetMiddleware:
    def __init__(self,app,metrics,limit=32,idle_timeout=10):
        self.app=app
        self.metrics=metrics
        self.limit=limit
        self.idle_timeout=idle_timeout

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        metrics=self.metrics
        if metrics['active']>=self.limit:
            metrics['rejected']+=1
            try:
                # Rejected clients also consume socket/send resources. Bound the
                # whole refusal, and never attempt another response after timeout.
                await asyncio.wait_for(JSONResponse({'code':'server_busy','detail':'Service busy; retry shortly / 服务繁忙，请稍后重试'},status_code=503,headers={'Retry-After':'1'})(scope,receive,send),timeout=self.idle_timeout)
            except TimeoutError:
                metrics['timeouts']+=1
            except (ClientDisconnect,OSError):
                metrics['disconnected']+=1
            return
        metrics['active']+=1
        metrics['peak_active']=max(metrics['peak_active'],metrics['active'])
        started=time.monotonic();request_id=str(uuid4());status=500;headers_sent=False;body_finished=False

        async def bounded_receive():
            nonlocal body_finished
            remaining=max(.001,15-(time.monotonic()-started))
            message=await asyncio.wait_for(receive(),timeout=self.idle_timeout if body_finished else min(self.idle_timeout,remaining))
            if message['type']=='http.request' and not message.get('more_body',False):
                body_finished=True
            return message

        async def bounded_send(message):
            nonlocal status,headers_sent
            if message['type']=='http.response.start':
                headers_sent=True
                status=message['status']
                message={**message,'headers':[*message.get('headers',[]),(b'x-request-id',request_id.encode())]}
            await asyncio.wait_for(send(message),timeout=self.idle_timeout)

        try:
            await self.app(scope,bounded_receive,bounded_send)
        except TimeoutError:
            metrics['timeouts']+=1
            status=504
            if not headers_sent:
                status=408
                try:
                    await asyncio.wait_for(JSONResponse({'code':'request_timeout','detail':'Upload stalled; retry with your saved draft / 上传等待超时，请保留草稿后重试'},status_code=408)(scope,receive,bounded_send),timeout=self.idle_timeout)
                except TimeoutError:
                    metrics['timeouts']+=1
                    status=504
                except (ClientDisconnect,OSError):
                    metrics['disconnected']+=1
            # A response already in progress is abandoned, never relabelled successful.
        except (ClientDisconnect,OSError):
            metrics['disconnected']+=1
        except asyncio.CancelledError:
            metrics['disconnected']+=1
            raise
        finally:
            elapsed=round((time.monotonic()-started)*1000,2)
            metrics['requests']+=1;metrics['active']-=1;metrics['total_ms']+=elapsed
            if status>=500:metrics['errors']+=1
            logging.getLogger('reprolens.requests').info(json.dumps({'request_id':request_id,'method':scope['method'],'status':status,'duration_ms':elapsed}))
