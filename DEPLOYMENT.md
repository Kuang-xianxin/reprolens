# Install and run

Supported delivery: a private local application on Windows with Python3.12, bound to127.0.0.1:8211. The application uses FastAPI/Pydantic, HTTPX, SQLite and local browser assets. There is no frontend build or paid runtime dependency. Linux/macOS and Docker are not claimed as verified deployments. No public service has been deployed.

```powershell
python -m venv --without-pip .venv
python -m pip --python .venv/Scripts/python.exe install --no-clean --no-compile -r requirements.lock.txt
python -m pip --python .venv/Scripts/python.exe check
.venv/Scripts/python.exe -m reprolens.database migrate --db data/reprolens.sqlite3
.venv/Scripts/python.exe scripts/serve.py
```

Open `http://127.0.0.1:8211`. `serve.py` constructs an allowlisted child environment: inherited OpenAI/provider keys, endpoint variables and proxy variables are not passed to the application. Configuration examples are documentation and are not auto-loaded. The application does not execute supplied code.

For a hidden Windows background process (PowerShell7):

```powershell
./scripts/start.ps1
./scripts/stop.ps1
```

The starter checks the port, uses a sanitized environment and records the actual listener PID, executable, command and creation time in `runtime/service.json`. The stopper verifies that identity before stopping it. Logs go to `runtime/server-<timestamp>.log`. There are no boot tasks, global environment edits or model-service changes. Stop the recorded service before starting another instance.

## Optional shared local model

The full manual report workflow works without AI. A coordinator may supply an existing free local model endpoint. The optional JSON configuration is explicit and accepts only a credential-free loopback endpoint:

```json
{
  "base_url": "http://127.0.0.1:REPLACE_PORT/v1",
  "model": "REPLACE_EXACT_MODEL_ID",
  "timeout": 120,
  "max_tokens": 1200,
  "input_char_limit": 6000,
  "constrained_json": true
}
```

Replace the placeholders before saving as a private runtime/model.json, then run `./scripts/start.ps1 -ModelConfig runtime/model.json`. Only set constrained_json when the allocated runtime supports the adapter's JSON-schema response format. No key is needed or accepted by this launcher. No runtime/model file is included in a source bundle.

Model configuration is not proof of readiness or quality. `/api/health` reports liveness and configured/unconfigured model state. `/api/ready` checks database access and the manual workflow. `/api/metrics` exposes bounded aggregate counters without source text or per-case labels. A model request has a deadline, concurrency1, a persistent operation record and cancellation. Busy requests get429 with Retry-After. Failure leaves the draft intact; restart marks interrupted work. There are no automatic paid fallbacks or automatic model retries.

## Validation and packaging

The private run record includes a fresh virtual environment installed from `requirements.lock.txt`, dependency-check logs, schema migration and an actual HTTP create/readiness check on a temporary loopback port. The first dependency-check command incorrectly assumed pip was installed inside the deliberately pip-free environment; its failure log was kept. The corrected external `pip --python <venv> check` passed. Temporary services were stopped; databases and logs remain.

The reviewable source ZIP is built from an explicit allowlist. It excludes all data/runtime databases, raw inputs, model failures, personal Devpost files, browser automation receipts, local configuration and credentials. It contains source, tests with synthetic fixtures, lockfile, MIT license, operational docs and cross-platform Python entrypoints. It is a local deployment artifact, not a published repository or a contest submission. Restoring the private database is a separate operation; never publish that backup.

Validation commands (run with a sanitized test environment as described in docs/RELIABILITY.md):

```powershell
.venv/Scripts/python.exe scripts/check.py
node --check reprolens/static/workbench.js
node --check reprolens/static/i18n.js
```

The browser is required for editing, preview and downloads; JavaScript is local and no CDN is used. Chrome-compatible clipboard restrictions may require using Markdown download. The service supports no authentication or organizational isolation, so do not expose it via0.0.0.0, public proxy or tunnel.

Generic OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY and remote opt-in variables are ignored by ModelSettings.from_env, including a direct import/ordinary Uvicorn start. scripts/serve.py converts its explicit validated local JSON file to project-specific model URL/name variables without any key.
# Architecture hardening2026-10-24

The current lockfile adds LangGraph1.2.16 and49 total distributions. Existing local installation uses `.venv-hardening` to preserve the old environment without uninstall/cleanup. `start.ps1` prefers it if present; a clean relocated deployment uses the `.venv` in the instructions below. SQLite schema2 migrates at startup with a retained prior backup and exclusive worker lease. Stop the old service before opening the same DB with the new application.

AI now uses persisted `/jobs` and202 responses; queue4/worker1, cancellation, restart checkpoints, circuit breaker and typed source validation. Restart requeues abandoned work with a two-attempt maximum; it does not simply mark it interrupted. `/api/ready` additionally rejects a stopped worker. A failed AI task retains the previous draft. The prior synchronous endpoint remains for compatibility and runs the same typed graph. No remote tracing/fallback or public deployment.

Hidden service logs cap at8MiB per run (no auto-deletion); `--no-access-log` avoids recording search query text. Request counters are aggregate and bounded. Operator retention of old run logs and backups remains necessary. Clean installation, relocated ZIP, real HTTP checks and current limitations are recorded in the architecture-hardening result, superseding earlier evidence below.

