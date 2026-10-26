# ReproLens architecture / 架构与维护

The product remains a private, loopback bug-report preparation workspace. The verified topology is one application process, one database and one active inference. It does not reproduce bugs or publish issues. Engineering complexity stays behind the editor.

Current source-selection contract is v3: non-overlapping literal fragments, validated Unicode-codepoint spans and edit-aware report/source lookup. Legacy line-only records remain readable. See SOURCE_TRACE.md and EVALUATION.md for implementation tradeoffs and current semantic failures; older six-case acceptance does not establish general quality.

## Main control flow

`POST /api/cases/{id}/jobs` → validate bounded request/version → transactional idempotency and queue reservation → HTTP 202 → one durable worker → **LangGraph 1.2.16** `FlowState` → `extract` → persisted typed extraction checkpoint → `verify_sources` → atomic case/revision/summary/job commit → browser polls → person reviews/edits → confirmation → Markdown.

`FlowState` is a Pydantic schema with allowed phases, language and source revision. `Job` separately validates queue/processing/terminal status. The source selection adapter still validates model ID, JSON, line identities, duplicates, output bounds and exact quotations. Human confirmation is a separate versioned API, never a graph-generated decision. Unsupported evidence remains explicitly marked and excluded from the generated report fields; the legacy reviewer cannot accept it. Exact citation matching is not semantic accuracy.

LangGraph is genuinely on the inference path, not a listed unused dependency. We use a purpose-built transactional checkpoint column in SQLite instead of a second LangGraph checkpoint database: after extraction, recovery routes directly to source validation. This preserves atomic report/job commit and retains historical raw output. It is **not** an implementation of LangGraph's general Checkpointer interface, arbitrary interrupts or time travel. The two-node graph has recursion_limit=4. No tools, external tracing or LangSmith service is enabled (`tracing_context(enabled=False)`).

## Jobs, versions and failure recovery

- Four unfinished jobs total; one worker coroutine; no unbounded thread executor submissions. Queue overflow returns 429 and Retry-After. Each case has at most one active job through a partial unique index. Requests bind key to case/revision/language; response-loss retry returns the same terminal job.
- A service owns an OS file lock for this DB. Crash releases ownership automatically. Normal startup converts abandoned running jobs to queued (maximum two execution attempts); jobs queued longer than ten minutes expire. A persisted extraction skips another model call. A crash before checkpoint may repeat read-only inference; this is at-least-once inference, exactly-once versioned report commit.
- One short transaction reserves work, then ends. The model is awaited with no database transaction/lock held. Heartbeats update every two seconds. Final report/version/history/summary and terminal job status commit in one transaction, guarded by the original revision. Any intervening edit leads to superseded, leaving current content intact.
- Cancellation writes terminal state, cancels and awaits the actual inference task. It does not merely mark a row while orphaning work. Shutdown cancels/awaits tasks; next startup resumes unfinished work. Ordinary job exceptions are isolated; worker DB failure retries are bounded by job attempts, and an explicitly dead worker makes readiness fail and new jobs return 503. Restart is the recovery for a stopped worker.
- Model timeout/failure preserves the existing report and confirmation. No remote fallback or retry storm. Three consecutive gateway failures open a 20-second circuit; one subsequent probe is allowed by the single-inference gate. Manual editing/export of already-confirmed reports stays available.

## Cache and SQL

The model gateway has at most 32 proposal entries, TTL 60s with ±15% jitter, one in-flight key and same-key singleflight waiters. Key = case ID + revision + source SHA values + model endpoint/model/budgets/schema + language + prompt/contract version. Failures are not cached. Confirmation/current report facts are never served from this cache. Same-key cancellation does not cancel the owner; owner failure/cancellation releases all waiters. Ordinary product jobs are deduplicated before inference; the gateway also protects the retained synchronous compatibility API.

Schema2 adds small `case_summaries`, ordered/status indexes, durable `jobs` and queue/case indexes. List/search no longer loads/parses full raw model JSON. Substring title search is still O(N) over at most 10,000 bounded titles; it is not a full-text index. Limit<=100/offset<=10,000 and SQLite progress-handler deadline500ms prevent unbounded execution. Busy timeout1s is separate. The audit records real query plans, statistics, approximate VM steps and 10,000-row measurements; an index scan alone is not proof that substring search is selective.

SQLite remains justified by loopback/single-service topology, not by ignoring concurrency. There are at most32 admitted HTTP lifecycles plus the worker's short DB work; connections close at operation exit. WAL/FULL, foreign keys, CAS snapshots, pre-migration backup and new-path restore protect data. Multi-user/public/multi-instance service requires a separate security/storage design; it is outside this delivery, not secretly supported by SQLite.

## Frontend and resource boundaries

Plain ES modules retain the existing editor. `task-poller.js` owns one poll generation for the current route; completed old requests cannot update another case. List, history and selected-revision requests also carry sequence guards. An AI completion defers while a save is active; edits made while its result is loading become a recoverable draft. Switching languages changes labels, not source/model text. Polling fetch deadlines are12s; connection loss retries at a bounded interval with a preserved draft. No React/TanStack migration was needed for this existing finite workflow.

Request admission covers receive through final send, including slow uploads/downloads and disconnects. Request/model responses <=128KB, saved source<=12,000 chars/24,000 UTF-8 bytes, inference default<=6,000 chars, typed checkpoint<=256KB, database<=512MiB, revisions/jobs<=1,000 per case, cases<=10,000. Capacity refusal retains existing data. Request metrics have fixed labels, no case IDs/source text. Background logs cap at8MiB per service run and then drain/discard further bytes; files are never auto-deleted. Old run logs/backups need operator-managed retention. History is retained, not pruned behind the user's back.

## Dependencies and evidence

Direct production: Python3.12, FastAPI0.159.1, Pydantic2.14.1, HTTPX0.28.1, Uvicorn0.54.0, LangGraph1.2.16 (MIT). All49 installed distributions are locked; `dependency-licenses.json` in the private delivery record records transitive licenses. The original environment remains, and the validated new environment is `.venv-hardening`. No model weights were downloaded by this project.

Official material checked2026-10-24: [LangGraph StateGraph/schema/nodes](https://docs.langchain.com/oss/python/langgraph/graph-api), [persistence and checkpointers](https://docs.langchain.com/oss/python/langgraph/persistence), [package metadata/license](https://pypi.org/pypi/langgraph/json). These explain framework contracts; local tests establish this implementation's narrower behavior.

## 学习与面试

以“点击AI后马上刷新”为例：普通HTTP协程随进程退出而消失；本方案先保存任务，再返回202，浏览器只查询状态。任务的生命周期不再绑定页面。面试可问：为何202不是成功结果？为什么不能在SQLite事务里等待模型？为什么保存点之后重启不需要再推理？为什么推理可能执行两次而报告只提交一次？

以“AI在第3版开始，人已保存第4版”为例：提交时仍检查source_revision=3，当前已是4就标superseded。缓存键也含版本，不能把旧来源的结果拿到新报告。再问：取消一个等待者为什么不应取消其他等待者共用的请求？TTL抖动能解决什么，不能解决什么？短时RSS平稳为什么不能证明永不泄漏？

工具越新不代表系统越可靠。这里的框架负责明确阶段和类型，数据库事务负责事实，UI负责不丢编辑，测试必须分别覆盖这些边界。用户价值与模型泛化仍需真实使用验证。
