# Database operations

Scope: one local user, one Uvicorn worker, one application instance. SQLite is the implemented database, not a placeholder for a team service. The official launcher binds 127.0.0.1. Public access, shared network filesystems and concurrent application instances are outside the supported deployment.

## Storage and migration

Default durable path: `data/reprolens.sqlite3`. `scripts/serve.py --db <absolute-path>` selects another database. Current `PRAGMA user_version=2` tracks the schema. Earlier databases are backed up before upgrade. Schema1 introduced revision/creation-request/operation tables; schema2 adds compact summaries, durable jobs/checkpoints and queue indexes. Original sources and historical documents are preserved. Repeated startup is idempotent. A newer schema is refused. See docs/ARCHITECTURE.md for the current recovery path.

Connections enable WAL, foreign keys and FULL synchronous durability. Each connection is closed after its operation. Writer transactions use BEGIN IMMEDIATE and a one-second lock timeout. A version-conditional UPDATE and its immutable snapshot share one transaction: exactly one competing writer succeeds, the other receives 409. No automatic write retries. Model execution happens outside the writer transaction; a source revision changed during inference refuses the late result.

Each saved revision includes sources, original model result, reviewer draft and confirmation. Source additions and draft edits invalidate confirmation. Restore reads a verified prior snapshot and saves it as a new unconfirmed revision. Existing snapshots and failed model outputs are retained. A user-editable report is explicitly separate from original model classification. A text SHA-256 mismatch rejects opening/exporting the corrupted current document; intact historical snapshots remain accessible.

## Backup and recovery

Run with the project interpreter and a clean environment (the start scripts already isolate model credentials):

```powershell
.venv/Scripts/python.exe -m reprolens.database check --db data/reprolens.sqlite3
.venv/Scripts/python.exe -m reprolens.database backup --db data/reprolens.sqlite3 --output backups/reprolens-20261023.sqlite3
.venv/Scripts/python.exe -m reprolens.database restore --db backups/reprolens-20261023.sqlite3 --output data/recovered-20261023.sqlite3
.venv/Scripts/python.exe scripts/serve.py --db data/recovered-20261023.sqlite3
```

Backup uses SQLite's online backup API; do not copy only the main file while WAL writes are active. Destination files must not already exist. Restore validates integrity and table counts and targets a new path, leaving both the original and the backup intact. Stop the previous local service before starting the recovered DB on8211. No command deletes old data. Backup media, cadence and offline copies are the user's operational responsibility; this application does not create a hidden scheduled task.

## Bounds and query behavior

10,000 cases; 1,000 saved revisions and 1,000 model operations per case; writes stop at a 512MiB database+WAL threshold (one already-admitted bounded transaction can cross the threshold). Reads/export/backup remain available. Reaching a limit returns507 with a recovery action; nothing is auto-pruned. Use a new database after archiving. This deliberately trades indefinite retention for bounded local growth without deleting evidence. Application server logs are per-launch; retain or archive them manually. They are excluded from distribution.

List page size ≤100, UI page size40. Schema2 summary/status indexes serve ordering without decoding full case documents. Title substring searches still scan up to the10,000-case cap; they are not a full-text search engine. Confirmed report facts are read from SQLite. A separate bounded model-proposal cache uses version/source/configuration keys and singleflight. Persistent jobs requeue abandoned work with at most two attempts; a saved extraction checkpoint avoids repeating inference. A crash before that checkpoint may repeat inference, while the versioned report commits once. Legacy synchronous operations retain interrupted-state handling.

## Evidence

Automated product/reliability tests exercise a real legacy database, retained backup, new-target restore, two writers, stale export, lock contention, interrupted operation and deliberate source hash corruption. This run also backs up and restores the actual working database into the private delivery record and compares original case documents and historical evidence hashes. Exact results and paths are in the delivery record; a passing SQLite integrity check alone is not evidence of semantic correctness or a disaster-recovery service.
# Schema2 hardening2026-10-24

Current schema is2. Existing schema0/1 databases receive a retained `.pre-v<next>-<timestamp>.bak` before a single transactional migration. Existing case/revision documents remain unchanged. `case_summaries` is transactionally maintained with every case write; `jobs` stores bound request keys, queue states, attempts, heartbeat, checkpoint JSON/SHA and result revision. Completed job and report/history/summary writes share a transaction. Startup holds an OS lock so two services cannot run workers against the same file. Previous schema1 notes below remain historical.

Read/write busy timeout1s; normal SQL progress deadline500ms. Listing reads bounded summaries, not raw model output. Queue<=4, active inference<=1, cases<=10,000, job/history<=1,000 per case, DB+WAL<=512MiB. No automatic deletion of old records. Use `python -m reprolens.database backup --db <db> --output <new-file>` and `restore --db <backup> --output <new-db>`; restore never overwrites an existing destination. Private copies are not source-package content. See docs/ARCHITECTURE.md for crash semantics and cache/version boundaries.

