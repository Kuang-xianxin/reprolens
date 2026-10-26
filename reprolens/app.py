import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .evidence import make_source, reviewed_content, rule_extract, validate_extraction
from .model import ModelFailure, ModelSettings, call_model
from .report import render_report
from .schemas import AnalyzeInput, AppendInput, CaseInput, ReviewInput, DraftInput, ConfirmInput, RestoreInput, enforce_budget
from .issue import fields_from_analysis, render_issue
from .limits import RequestBudgetMiddleware
from .store import Capacity, Conflict, Corrupt, Store, now
from .jobs import JobWorker, QueueFull
from .workflow import ModelGateway, run_workflow
from .schemas import JobInput

ROOT = Path(__file__).resolve().parent
CHECKLIST = {"sources_reviewed", "hypotheses_separated", "privacy_reviewed"}


def create_app(db_path=None, settings=None, model_runner=None):
    running={}
    @asynccontextmanager
    async def lifespan(instance):
        await asyncio.to_thread(instance.state.store.recover_operations)
        await worker.start()
        try:
            yield
        finally:
            for task in tuple(running.values()):
                task.cancel()
            if running:
                await asyncio.gather(*tuple(running.values()),return_exceptions=True)
            await worker.stop()
    app = FastAPI(title="ReproLens", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])
    store = Store(db_path or os.getenv("REPROLENS_DB", str(ROOT.parent / "data" / "reprolens.sqlite3")))
    config = settings or ModelSettings.from_env()
    runner = model_runner or call_model
    gateway = ModelGateway(config,runner)
    worker = JobWorker(store,gateway)
    app.state.worker = worker
    app.state.gateway = gateway
    model_lock = asyncio.Lock()
    app.state.store = store
    metrics={'requests':0,'rejected':0,'active':0,'peak_active':0,'errors':0,'total_ms':0.0,'timeouts':0,'disconnected':0}
    app.state.metrics=metrics

    @app.get('/api/metrics')
    def request_metrics():
        return {**metrics,'model_active':len(gateway.flights),'request_limit':32,'model_limit':1,
                'model':gateway.metrics,'cache_entries':len(gateway.cache),'worker_errors':worker.errors,
                'worker_alive':bool(worker.task and not worker.task.done())}

    @app.exception_handler(QueueFull)
    async def queue_full(request,exc):
        return JSONResponse({'code':'queue_full','detail':'Four reports are already waiting; retry shortly / 整理队列已满，请稍后重试'},status_code=429,headers={'Retry-After':'3'})

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin writes forbidden"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON required"}, status_code=415)
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 128_000:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"code":"revision_conflict","detail": str(exc)}, status_code=409)

    @app.exception_handler(Capacity)
    async def capacity_handler(request,exc):
        return JSONResponse({'code':'capacity_reached','detail':str(exc)},status_code=507)

    @app.exception_handler(Corrupt)
    async def corrupt_handler(request,exc):
        return JSONResponse({'code':'integrity_failed','detail':'Stored source failed integrity check; restore a verified backup / 材料完整性检查失败，请从已校验备份恢复'},status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request,exc):
        return JSONResponse({'code':'validation_error','detail':'Check required fields, text limits and source names / 请检查必填内容、文本上限和材料名称',
                             'errors':[{'field':'.'.join(map(str,e['loc'])),'code':e['type']} for e in exc.errors()]},status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_handler(request,exc):
        busy=isinstance(exc,sqlite3.OperationalError) and any(word in str(exc).lower() for word in ('locked','busy'))
        return JSONResponse({'code':'database_busy' if busy else 'database_unavailable','detail':'Database busy; retry shortly / 数据库繁忙，请稍后重试' if busy else 'Database unavailable; retain draft and check storage / 数据库不可用，请保留草稿并检查存储'},status_code=503,headers={'Retry-After':'1'})

    def get_case(case_id, revision=None):
        try:
            case = store.get(case_id)
        except KeyError:
            raise HTTPException(404, "Case not found")
        if revision is not None and revision != case["revision"]:
            raise Conflict("Case changed; reload before continuing / 案例已更新，请重新载入")
        return case

    @app.get("/api/health")
    def health():
        try:
            config.validate()
            model_status = "configured_unverified"
        except ModelFailure as exc:
            model_status = exc.code
        return {"status": "ok", "model_status": model_status, "model": config.model or None,
                "remote_inference_allowed": config.allow_remote, "executes_code": False,
                "limits": {"source_characters":12000,"source_bytes":24000,"description_characters":6000,"ai_characters":config.input_char_limit}}

    @app.get('/api/ready')
    def readiness():
        try:
            schema = store.ready()
        except Exception:
            return JSONResponse({'status':'unavailable','database':'unavailable'},status_code=503)
        if worker.task and worker.task.done():
            return JSONResponse({'status':'unavailable','worker':'stopped'},status_code=503)
        return {'status':'ready','database':'ready','schema_version':schema,'workflow':'local_single_user','ai':health()['model_status']}

    @app.get("/api/cases")
    def list_cases(q: str = Query(default='',max_length=160), status: str = Query(default='all',pattern='^(all|draft|confirmed)$'), offset: int = Query(default=0,ge=0,le=10000), limit: int = Query(default=100,ge=1,le=100)):
        return store.list(q,status,offset,limit)

    @app.post("/api/cases", status_code=201)
    def create_case(payload: CaseInput):
        sources = [make_source("s0", "description", "description", payload.description)]
        sources += [make_source(f"s{i}", s.name, s.kind, s.text) for i, s in enumerate(payload.sources, 1)]
        return store.create({"id": str(uuid4()), "title": payload.title, "sources": sources,
                             "created_at": now(), "updated_at": now(), "revision": 1, "analysis": None, "review": None},payload.request_id)

    @app.get("/api/cases/{case_id}")
    def read_case(case_id: str):
        return get_case(case_id)

    @app.post("/api/cases/{case_id}/sources")
    def append_source(case_id: str, payload: AppendInput):
        case = get_case(case_id, payload.revision)
        if len(case["sources"]) >= 12:
            raise HTTPException(422, "At most 12 total sources; create a smaller case")
        try:
            enforce_budget([s["text"] for s in case["sources"]] + [payload.text])
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        case["sources"].append(make_source(f"s{len(case['sources'])}", payload.name, payload.kind, payload.text))
        case["analysis"], case["review"] = None, None
        return store.save(case, payload.revision, 'source_added')

    @app.post("/api/cases/{case_id}/analyze")
    async def analyze(case_id: str, payload: AnalyzeInput):
        case = await asyncio.to_thread(get_case,case_id,payload.revision)
        analysis = {"mode": payload.mode, "model": None, "created_at": now(), "status": "ready", "claims": [], "questions": []}
        operation_id=None
        try:
            if payload.mode == "ai":
                if model_lock.locked():
                    raise HTTPException(429, "Model busy; wait for the current request",headers={'Retry-After':'3'})
                async with model_lock:
                    operation_id=str(uuid4())
                    await asyncio.to_thread(store.start_operation,operation_id,case_id,payload.revision)
                    task=asyncio.create_task(run_workflow(gateway,case,payload.language))
                    running[operation_id]=task
                    try:
                        async with asyncio.timeout(config.timeout):
                            graph_analysis=await task
                    except TimeoutError:
                        raise ModelFailure('timeout')
                    except asyncio.CancelledError:
                        raise ModelFailure('cancelled')
                    finally:
                        running.pop(operation_id,None)
                analysis.update(graph_analysis)
            else:
                extraction = rule_extract(case["sources"])
                if extraction is None:
                    raise ModelFailure("no_short_observation")
                analysis.update(validate_extraction(extraction, case["sources"], question_origin="rules"))
                if not extraction.claims:
                    analysis.update(status="needs_evidence", error="no_relevant_evidence")
        except ModelFailure as exc:
            analysis.update(status="failed", error=exc.code)
        except HTTPException:
            raise
        except Exception:
            analysis.update(status='failed',error='processing_failed')
        case['last_attempt'] = analysis
        async def save_attempt(action):
            try:
                result=await asyncio.to_thread(store.save,case,payload.revision,action)
            except Conflict:
                if operation_id: await asyncio.to_thread(store.finish_operation,operation_id,'superseded','revision_conflict')
                raise
            if operation_id: await asyncio.to_thread(store.finish_operation,operation_id,analysis['status'],analysis.get('error'))
            return result
        if analysis['status']=='failed' and (case.get('analysis') or case.get('draft')):
            return await save_attempt('analysis_failed')
        case["analysis"], case["review"] = analysis, None
        if analysis['status']=='ready':
            case['draft'] = {'fields':fields_from_analysis(analysis),'origin':payload.mode,'saved_at':now()}
        return await save_attempt('organized_'+payload.mode if analysis['status']=='ready' else 'analysis_'+analysis['status'])

    @app.post('/api/cases/{case_id}/jobs',status_code=202)
    async def submit_job(case_id: str,payload: JobInput):
        replay=await asyncio.to_thread(worker.jobs.replay,case_id,payload.revision,payload.language,payload.request_id)
        if replay:return replay
        case=await asyncio.to_thread(get_case,case_id,payload.revision)
        if sum(len(s['text']) for s in case['sources'])>config.input_char_limit:
            raise HTTPException(422,'AI input limit exceeded; manual editing is available / 材料超过 AI 上限，可以继续手动编辑')
        if worker.task is None or worker.task.done():
            raise HTTPException(503,'Worker unavailable; restart the local service / 整理服务不可用，请重启本机服务')
        result=await asyncio.to_thread(worker.jobs.submit,case,config,payload.language,payload.request_id)
        worker.wake.set()
        return result

    @app.get('/api/cases/{case_id}/jobs')
    def list_jobs(case_id: str):
        get_case(case_id)
        return worker.jobs.list(case_id)

    def get_job(case_id,job_id):
        try:row=worker.jobs.get(job_id)
        except KeyError:raise HTTPException(404,'Task not found')
        if row['case_id']!=case_id:raise HTTPException(404,'Task not found')
        return worker.jobs.public(row)

    @app.get('/api/cases/{case_id}/jobs/{job_id}')
    def read_job(case_id: str,job_id: str):
        return get_job(case_id,job_id)

    @app.post('/api/cases/{case_id}/jobs/{job_id}/cancel')
    async def cancel_job(case_id: str,job_id: str):
        await asyncio.to_thread(get_job,case_id,job_id)
        return await worker.cancel(job_id)

    @app.get('/api/cases/{case_id}/operations')
    def operations(case_id: str):
        get_case(case_id)
        return store.operations(case_id)

    @app.post('/api/cases/{case_id}/operations/{operation_id}/cancel')
    async def cancel_operation(case_id: str,operation_id: str):
        await asyncio.to_thread(get_case,case_id)
        operations=await asyncio.to_thread(store.operations,case_id)
        if not any(op['id']==operation_id for op in operations):
            raise HTTPException(404,'Operation not found')
        task=running.get(operation_id)
        if task:
            task.cancel()
            return {'status':'cancellation_requested'}
        return {'status':'already_finished'}

    @app.put('/api/cases/{case_id}/draft')
    def save_draft(case_id: str, payload: DraftInput):
        case = get_case(case_id,payload.revision)
        fields = payload.fields.model_dump()
        if case['title']==payload.title and (case.get('draft') or {}).get('fields')==fields:
            return case
        case['title']=payload.title
        case['draft']={'fields':fields,'origin':'reviewer','saved_at':now()}
        case['review']=None
        return store.save(case,payload.revision,'draft_saved')

    @app.post('/api/cases/{case_id}/confirm')
    def confirm_issue(case_id: str,payload: ConfirmInput):
        case = get_case(case_id,payload.revision)
        draft = case.get('draft')
        if not draft or not draft['fields']['observed'].strip():
            raise HTTPException(422,'Add an actual result before confirming / 请先填写实际结果')
        if not payload.sources_reviewed or not payload.privacy_reviewed:
            raise HTTPException(422,'Review the report and sharing scope / 请检查报告与分享范围')
        case['review']={'kind':'issue','confirmed_at':now(),'analysis_revision':payload.revision,
                        'missing_fields':[key for key,value in draft['fields'].items() if not value.strip()]}
        return store.save(case,payload.revision,'confirmed')

    @app.get('/api/cases/{case_id}/history')
    def history(case_id: str):
        try: store.revision(case_id)
        except KeyError: raise HTTPException(404,'Case not found')
        return store.history(case_id)

    @app.get('/api/cases/{case_id}/history/{revision}')
    def version(case_id: str,revision: int):
        try:
            return store.version(case_id,revision)
        except KeyError:
            raise HTTPException(404,'Version not found')

    @app.post('/api/cases/{case_id}/restore')
    def restore(case_id: str,payload: RestoreInput):
        try: current=store.revision(case_id)
        except KeyError: raise HTTPException(404,'Case not found')
        if current!=payload.revision: raise Conflict('Case changed; reload before restoring / 问题已更新，请重新载入')
        try:
            restored=store.version(case_id,payload.target_revision)
        except KeyError:
            raise HTTPException(404,'Version not found')
        restored['review']=None
        restored['restored_from']=payload.target_revision
        return store.save(restored,payload.revision,'restored')

    @app.get('/api/cases/{case_id}/issue.md')
    def issue_export(case_id: str,lang: str = Query(default='en',pattern='^(en|zh)$'),sources: bool = False,revision: int | None = None,evidence: bool = False):
        case=get_case(case_id,revision)
        if not case.get('review') or case['review'].get('kind')!='issue':
            raise HTTPException(409,'Confirm the current report before export / 请先确认当前报告')
        return Response(render_issue(case,lang,sources,evidence),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="reprolens-{case_id[:8]}-v{case["revision"]}.md"'})

    @app.get('/api/cases/{case_id}/case.json')
    def archive_export(case_id: str):
        return JSONResponse(get_case(case_id),headers={'Content-Disposition':f'attachment; filename="reprolens-{case_id[:8]}.json"'})

    @app.post("/api/cases/{case_id}/review")
    def review(case_id: str, payload: ReviewInput):
        case = get_case(case_id,payload.revision)
        analysis = case.get("analysis")
        if not analysis or analysis["status"] != "ready":
            raise HTTPException(409, "Analyze the current sources before review")
        claims = analysis["claims"]
        if set(payload.decisions) != {c["id"] for c in claims}:
            raise HTTPException(422, "Explicitly accept or reject every claim")
        if set(payload.checklist) != CHECKLIST or not all(payload.checklist.values()):
            raise HTTPException(422, "Complete all three review checks")
        by_id = {c["id"]: c for c in claims}
        for claim_id in payload.category_overrides:
            claim = by_id.get(claim_id)
            if (claim is None or payload.decisions[claim_id] != "accept" or
                    claim["kind"] != "fact" or claim["support"] != "source_matched"):
                raise HTTPException(422, "Only accepted, source-matched facts can be reclassified / 只能纠正已采纳且引用匹配的事实分类")
        if (len(set(payload.excluded_questions)) != len(payload.excluded_questions) or
                any(i < 0 or i >= len(analysis["questions"]) or analysis["questions"][i].get("origin") != "model"
                    for i in payload.excluded_questions)):
            raise HTTPException(422, "Only existing model questions can be excluded / 只能排除现有模型问题")
        accepted, _, missing = reviewed_content(analysis, payload.decisions, payload.category_overrides, payload.excluded_questions)
        if any(c["support"] != "source_matched" for c in accepted):
            raise HTTPException(422, "Unsupported claims cannot be accepted")
        if not any(c["kind"] == "fact" and c["category"] == "observed" for c in accepted):
            raise HTTPException(422, "Include at least one actual observation; environment alone is insufficient / 至少采纳一条实际现象，仅有环境不能确认")
        case["review"] = {"decisions": payload.decisions, "checklist": payload.checklist,
                           "category_overrides": payload.category_overrides,
                           "excluded_questions": payload.excluded_questions, "missing_fields": missing,
                           "confirmed_at": now(), "analysis_revision": payload.revision}
        return store.save(case, payload.revision, 'legacy_review')

    @app.get("/api/cases/{case_id}/report.md")
    def export_report(case_id: str):
        case = get_case(case_id)
        if not case.get("review"):
            raise HTTPException(409, "Human confirmation required before export")
        report = render_issue(case,include_sources=True) if case['review'].get('kind')=='issue' else render_report(case)
        return Response(report, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="reprolens-{case_id[:8]}.md"'})

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "workbench.html")

    @app.get('/static/workbench.css')
    def workbench_css():
        return FileResponse(ROOT/'static'/'workbench.css',media_type='text/css')

    @app.get('/static/workbench.js')
    def workbench_js():
        return FileResponse(ROOT/'static'/'workbench.js',media_type='application/javascript')

    @app.get('/static/i18n.js')
    def translations():
        return FileResponse(ROOT/'static'/'i18n.js',media_type='application/javascript')

    @app.get('/static/task-poller.js')
    def task_poller():
        return FileResponse(ROOT/'static'/'task-poller.js',media_type='application/javascript')

    @app.get('/static/source-trace.js')
    def source_trace():
        return FileResponse(ROOT/'static'/'source-trace.js',media_type='application/javascript')

    @app.get("/static/style.css")
    def stylesheet():
        # Windows registry MIME mappings can mislabel CSS; nosniff then blocks it.
        return FileResponse(ROOT / "static" / "style.css", media_type="text/css")

    @app.get("/static/app.js")
    def javascript():
        return FileResponse(ROOT / "static" / "app.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.add_middleware(RequestBudgetMiddleware,metrics=metrics)
    return app


app = create_app()
