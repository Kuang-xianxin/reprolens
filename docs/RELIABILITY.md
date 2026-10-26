# ReproLens architecture and reliability

The product supports a single local user, one service and small text reports. It deliberately keeps FastAPI + Pydantic strict contracts, a structured model adapter, SQLite transactional checkpoints and framework-free ES modules. This is an editable document workflow with three views, not a multi-tenant team system. Adding a distributed queue/cache or two overlapping agent frameworks would create failure modes without a required user capability.

Data flow: browser draft → strict request model and origin/body checks → version-checked SQLite transaction → full revision snapshot → API document → editable four-section report → explicit confirmation of that saved revision → Markdown download with an optional original-source attachment. Model flow: bounded source text → untrusted-source JSON with line refs → one deadline-bound local request → strict JSON selection schema → exact source reference verification → untouched original analysis plus editable draft. Reviewer wording never retroactively changes model evidence.

The UI separates translation data from the working controller, uses dedicated renderers for capture/editor/preview/history and a single state object. Server-side Pydantic validates all mutations; browser draft recovery is revision-bound. The frontend is JavaScript, not a claim of complete TypeScript coverage. Actual DOM interactions are verified in Egolite. A larger collaboration editor would justify React/TypeScript and a request cache, but public/team deployment remains outside this scope.

| Trigger | Protection / user outcome | Implementation | Verification / boundary |
|---|---|---|---|
| Burst of requests | 32 active requests maximum; excess503 + Retry-After1 | app.request_budget | Controlled read load1/10/30,10s each. Not internet capacity. |
| Two editors save one revision | Conditional UPDATE + snapshot in one transaction; loser409, browser draft retained | Store.save, draft endpoint, browser recovery | Two real SQLite writers; browser concurrent-write recovery |
| Create response lost/retried | Request ID binds original title+sources; same payload returns same case, changed payload409 | Store.create | Idempotency test; UI disables repeat actions |
| Model is busy / hangs | One active call; second429 + Retry-After3; whole-call deadline; explicit cancellation | analyze, operations endpoints, call_model | Delayed fixture proves backpressure/cancel/deadline; fixture is not inference |
| Service stops during inference | Durable running operation becomes interrupted on startup; no automatic replay | operations table + lifespan | Restart test, source/draft unchanged |
| Database writer lock | One-second busy timeout;503, no automatic unsafe retry | Store.connection + SQLite exception handler | Actual BEGIN IMMEDIATE blocker, recovery after release |
| SQL sort / broad search | Updated-time index, page≤100; no N+1; substring scan bounded by case cap | Store.list | EXPLAIN uses cases_updated_idx; search is not indexed full text |
| Large text/file | Request128KB, sources12K chars/24KB, AI6K chars by default, output128KB, files UTF-8/extension checked | schemas, middleware, model, readFiles | Budget tests and import UI. No silent truncation |
| Growing history / DB | 1K revisions/operations per case,10K cases,512MiB write threshold;507, export/backup still available | Store._capacity | Injected limit preserves current document. No auto-deletion |
| Resource retention | Connections/HTTP clients closed; bounded result sizes and counters | Store.connection, call_model, request_budget | 50 warmup+500 list reads: current traced allocation0→60bytes, peak82154bytes. This is only that window, not a no-leak guarantee. |
| Cache stampede / stale cache | No application data cache exists; reads use SQLite | Store.list/get | Not applicable; cache correctness is not advertised |
| Invalid JSON/model ID/tool call/unknown ref | Typed rejection, bounded error code, no code execution | model.call_model + validate_extraction | Mock transport contract tests; fresh semantic quality remains separate |
| Retry storm / duplicate side effects | No automatic model/write retries; explicit UI retry, idempotent creation | API/browser handlers | Deadline + duplicate request tests |
| Late result after edited sources | CAS refuses superseded output; operation records superseded | analyze + Store.save | Existing concurrent-evidence regression |
| XSS/path traversal/SSRF/CSRF | Text escaping, filename labels only, local model URL validation, Host+Origin restrictions, CSP | schemas/model/app/workbench/report | Existing malicious input and cross-origin tests; no zip/file extraction in product |
| Secret leakage | App and tests constructed from environment allowlist; model key excluded from repr; validation errors do not echo input | scripts/serve.py, test runner, ModelSettings | Fixture secret masking test; no inherited paid key used |
| DB/source corruption | integrity+foreign keys for backups; source SHA check on reads; intact history remains readable | Store._decode, database.inspect | Deliberate source corruption first exposed blocked-history bug; fixed, failed receipt retained |
| Disk full / write failure | Transaction rollback and503/capacity507; local browser draft kept | Store transaction + exception handler | Capacity fault verified; physical disk-full fault not injected |
| Telemetry cardinality | Aggregate counters only; request ID per response; no titles/source/model content logged by application | /api/metrics + request middleware | Counter checked after load. Server per-launch logs need manual archival; no automatic pruning |
| UI refresh/language/old request | Browser drafts, route request sequence guard, version conflict recovery, action disabling | workbench controller | Actual Egolite create/reload/language/edit/restore/export; screenshot inspection |
| Clean installation | Locked dependencies, explicit migration, loopback launcher, separate liveness/readiness | DEPLOYMENT.md | Fresh venv and actual HTTP create passed. Docker/cloud/Linux unverified |

Measured load:200 synthetic cases,≈1KB source each, Windows11, Python3.12.7, one local server, shared test lock. Read requests:367/2055/1997 at concurrency1/10/30; all200. p50:18.133/34.687/121.796ms; p95:31.880/64.302/175.367ms; p99:38.928/82.326/269.758ms. Highest observed active requests27. There was no model call, cache or distributed database in this test. Full raw result is private in the delivery record. Tests retain their SQLite files rather than cleaning them in bulk.

Remaining engineering limits: no team authentication, no public-hosting hardening claim, no cross-instance job ownership, no automatic backup schedule, no physical power-loss/disk-full soak, no long-duration RSS leak claim. A service restart interrupts an in-flight model request and requires a user retry; it does not resume an opaque model stream. These are concrete limits of the supported local scope.


## Coordinator review and latest measurements

Four new regressions first failed: inherited generic provider configuration, admission bypass by slow uploads, admission ending before streaming downloads completed, and SQLite busy wait blocking a health request for1.156s. The fixes use outer pure ASGI middleware, admission through final send,10s idle receive/send timeout with15s total upload window, cancellation/disconnect release, and asyncio.to_thread for database calls in async model routes. Project-specific REPROLENS_MODEL_URL/NAME are the only default model identity inputs; no inherited key or remote opt-in is accepted. Failed and fixed XML receipts are retained.

Eight lifecycle tests additionally exercise receive timeout, send timeout, disconnect and task cancellation. Under the coordinator's shared-benchmark lock, the post-fix200-case read run produced352/2177/2093 HTTP200 responses at concurrency1/10/30 over10s each. Latest p95=33.311/63.238/154.013ms, p99=36.585/105.246/390.524ms. All4622 requests succeeded, peak active30. This replaces the earlier headline measurement; both raw runs remain. Store allocation growth was still60bytes over500 measured reads. It does not establish public capacity or long-duration process RSS behavior.

Pasted source text is not silently clipped by HTML maxlength; over-limit text remains visible with the description counter/validation and backend limits. Browser back/navigation while a save or inference is active is queued, so the completed old action cannot overwrite a newly opened case.
