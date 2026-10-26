---
status: draft
participant_review: pending
execution: explicitly-authorized-delegated-build
---
# ReproLens implementation specification

## Runtime and data
Python3.12, FastAPI/Pydantic strict JSON, HTTPX, LangGraph and standard-library SQLite. Native JavaScript modules/CSS; no frontend build. One loopback service and one worker. Dependency versions are pinned. Launch through scripts/serve.py or sanitized scripts/start.ps1.

SQLite WAL schema2 stores cases, immutable revisions, idempotency/operation records and durable jobs/checkpoints. Compare-and-swap commits prevent stale overwrite. Schema upgrades preserve a backup; history is not deleted. Service lease enforces the local single-instance boundary. See ../DATABASE.md and ../docs/ARCHITECTURE.md for exact tables and limits.

## Core modules
- app.py/schemas.py: HTTP contracts, input limits, confirmation and export gates.
- store.py/jobs.py/workflow.py: revisions, persistent tasks, typed extraction/validation/projection stages and stale-result rejection.
- model.py: optional local inference; source_selection_v3 selects0–12 refs/categories and0–2 questions. Program copies source text. A line with multiple literal punctuation fragments is offered only as non-overlapping fragments; original full lines remain preserved. Instructions inside sources are untrusted.
- evidence.py: exact source identity, line and Unicode-codepoint span validation. Legacy citations without character spans remain readable.
- trace.py/source-trace.js: equivalent bounded indexes; outer ASCII spaces are ignored, wording is not paraphrase-matched. Keep at most three locations per identical text plus a count. UI details display at most80 report lines; downloaded references cover all matched report lines.
- issue.py: current confirmed-version export; cited excerpts and full sources are separate opt-ins. One first exact location is used when identical text occurs repeatedly. Matching demonstrates location, not causality/truth/completeness.
- workbench.js/i18n.js/CSS: four-field editor, immediate trace refresh, source jump and return focus, preview/history, Chinese/English interface. User material is not translated.

## Failure and model boundaries
Request/body/output/time/storage bounds and isolated tests remain in ../docs/ROBUSTNESS.md. Durable queue uses one worker, bounded model cache/singleflight and circuit breaker. Raw model selection is distinct from edited draft. Questions for already populated categories are conservatively suppressed while retained privately; this can hide a useful detailed follow-up. Missing sections are still visible. No semantic-completeness guarantee, remote fallback or paid key inheritance.

## Verification
scripts/check.py isolates test DB/environment; JS golden fixtures verify parity and task polling. Real model calls and UI actions are separately recorded. Mechanical pass does not mean model semantic acceptance. Final model limitations are described in ../docs/EVALUATION.md. Personal participant review is pending.
