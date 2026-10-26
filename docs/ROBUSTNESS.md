# Reliability verification / 可靠性矩阵

Scope: private Windows/Python3.12 single-process loopback service. The architecture-hardening private record contains commands, failing and passing test receipts, real model outputs, screenshots and raw measurements. The table describes mechanisms and limits, not a claim of universal production readiness.

Run `.venv/Scripts/python.exe scripts/check.py` in a clean install (`.venv-hardening` in this working copy). Run `node scripts/check-frontend.mjs`. Load/model/fault batches must use the coordinator's `run-isolated-check.py --cwd <project> -- <command>` and isolated data. Do not run load against an official service or the working database.

| Trigger | Protection → user result | Code / reproduction | Evidence and boundary |
|---|---|---|---|
| 1. Bursty/slow requests | Admission32 covers receive→final send; idle10s/upload15s;503+Retry-After | limits.py; test_transport_boundaries.py | Existing full-lifecycle guards regressed; real HTTP1/10/30 load below |
| 2. Concurrent edits | CAS revision and one transaction →409 with retained draft; old AI→superseded | store.save; JobStore.finish; test_jobs.py | Browser saved an edit during inference and retained it |
| 3. Duplicate/response-loss retry | request key binds case/revision/language; replay returns same terminal job | JobStore.replay/submit; test_jobs.py | Different payload/key reuse409; same active case deduplicated |
| 4. Queue full/cancellation | queue4, one worker; cancel actual task and await release | jobs.py; test_jobs.py | Fifth unique case429; no orphan inference/future after cancel |
| 5. Process interruption | exclusive lease, persisted extraction checkpoint, max2 attempts, atomic result commit | JobStore.recover/checkpoint/finish | Restart resumes source validation without second inference; pre-checkpoint crash may repeat read-only inference |
| 6. DB lock/availability | busy timeout1s; async paths offload short SQLite work;503 on failure | store.connection; test_reliability.py, test_transport_boundaries.py | Busy write does not block unrelated lightweight endpoints; no remote pool to exhaust |
| 7. Slow SQL/large history | summary projection/indexes; limit100/offset10000; progress deadline500ms | store.list/connection; test_hardening_faults.py | 10k data plans/stats retained. Substring search still bounded full index scan; deadline injection interrupts recursive query |
| 8. Oversized input/results |128KB HTTP/model,12k chars/24k bytes source,6k AI,256KB checkpoint | schemas.py/model.py/jobs.py | Existing limits and new strict version fields tested; no archive/upload extraction |
| 9. Memory/resources | finite tasks/cache, closing DB/HTTP connections, bounded arrays | workflow.py/jobs.py; benchmark.py private record | Actual server RSS/handles across HTTP and60 submit/cancel cycles; short window only |
| 10. Cache stampede/staleness | source+revision+prompt/model/language key; LRU32,60s jitter;singleflight | ModelGateway; test_jobs.py |30 same-key callers→one invocation; changed revision bypasses; TTL/eviction/cancel tested. No factual-write caching |
| 11. Model outage/bad JSON | timeout/bounded output/schema/model/ref validation; circuit3 failures/20s | model.py/workflow.py | Invalid data/timeouts retained as failures. Draft remains editable. No external fallback |
| 12. Retry storm | no automatic network retry; restart<=2; one half-open probe | ModelGateway/JobWorker | Failed calls never cached; idempotency protects committed reports |
| 13. Unknown/partial result | explicit queued/running/failed/superseded/needs_evidence | Job schema and UI |202 is accepted, not success. Six real model calls include actual empty selection; no transaction/payment subsystem |
| 14. Injection/path/XSS/SSRF | plain text and escaped rendering, filenames labels, parameter SQL, loopback model URL/no redirects | schemas/evidence/model/report; test_workflow.py | Prompt injection case ignored by actual model; no arbitrary URL fetch or Zip extraction |
| 15. Access/secrets | loopback host/Origin checks,JSON writes,CSP; job belongs to case; provider env removed,repr hidden,tracing disabled | app.py/model.py/serve.py | Cross-case job404, inherited generic provider config ignored. No public account/workspace security claim |
| 16. Disk/write/backup/migration | transaction rollback,retained pre-migration DB,logical backup checks,new-path restore | database.py; test_hardening_faults.py | Injected write failure and checkpoint failure preserve data; no actual disk-filling test |
| 17. Unbounded observations/history | fixed-label counters;32 cache;1000 revisions/jobs per case;512MiB DB;8MiB log/run | store/jobs/serve | Refuse capacity rather than delete originals; cross-run log/backup retention manual |
| 18. UI race/offline/language | one poll generation,route/list/history sequence guards,fetch deadline,dirty recovery | task-poller.js/workbench.js | Browser refresh/cancel/superseded/failed→retry→manual recovery;390px,en/zh,visible keyboard focus |
| 19. Corrupt source/checkpoint | SHA check; invalid checkpoint refused; summaries verified on backup | Store._decode,JobWorker.run,database.inspect | Tampered checkpoint produces explicit failure without revision update; old history kept |
| 20. Deploy/health/shutdown | fully locked49 dependencies,clean environment,schema2,OS lease,live/ready separation | serve/start/stop,package,tests | Windows relocated artifact is verification target; no public/Linux/container readiness claim |

## Measured load

Actual HTTP on127.0.0.1:18212, Windows11/Python3.12.7; 10,000 synthetic cases, 30 warmup reads. Mix: list40, individual case, confirmed Markdown export, rare substring title search. Shared host and operating-system cache were not controlled. These are local observations, not advertised capacity.

| Concurrent clients | Measured duration | Success | Backpressure | Success p50/p95/p99 ms | Rejection p50/p95/p99 ms |
|---:|---:|---:|---:|---|---|
|1|10.00s|1290|0|6.178 /15.260 /21.267|not applicable|
|10|10.11s|2228|0|24.449 /139.652 /174.982|not applicable|
|30|10.12s|1406|6×503|119.292 /670.201 /1055.900|17.824 /32.742 /32.742|

No other HTTP/transport failures in this sample. Admission peak32; model active0 after the cancellation cycles; metrics active1 is the metrics request itself. First business request after process start4.275ms; repeated access represented by distributions above. This is not a cold disk measurement. Query plan timings: list40≈0.336ms, status-filter40≈0.134ms, rare substring≈10.330ms/70k VM steps. Substring scan remains O(10k), explicitly documented.

RSS: after warmup88.6MB; after load1/10/30:87.6/92.0/54.6MB; after20/40/60 task cycles78.9/79.4/79.4MB; settled79.0MB. Private committed bytes settled84.0MB vs77.6MB initial. Handles214 warmup→405 after30-client load→461/485/472 through task cycles→333 after2s settling. RSS can decrease because Windows trims working sets; retained threads/keepalive sockets affect handles. These data show bounded behavior in this window, **not** a proof that long-lived leaks cannot occur or that handles returned to initial baseline.

## Known retained failures and limits

The initial graph integration over-rejected unsupported claims and broke one legacy human-review test; restored marked-evidence behavior passed. A schema-version assertion was deliberately updated1→2 after the real migration. First fixture browser navigation raced server startup and was refused; later actual navigation succeeded. A screenshot named conflict-mobile-zh was actually desktop after round-local viewport reset; it is retained as mislabelled evidence, not counted as narrow-screen proof. Later narrow captures verify innerWidth=390 and no horizontal overflow. Historical model failure/protocol-deviation evidence remains unchanged.

User benefit and generalized AI semantic accuracy remain unverified. Short synthetic workload, no multi-day soak, no forced physical disk exhaustion, no remote database/network distribution, no public auth or team deployment. No payments/email/public release/final submission occurred.
