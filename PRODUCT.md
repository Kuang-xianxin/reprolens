# ReproLens

Current delivery update (2026-10-24/25): the editor now recomputes exact source matches as wording changes, jumps to original lines and exports optional cited excerpts independently of full sources. source_selection_v3 uses non-overlapping literal fragments. The latest ten-case diagnostic review found seven sufficient and three partial results; omitted expected behavior/corrections and missing questions remain known limitations. See docs/EVALUATION.md and current devpost/scope.md, prd.md and spec.md. The dated sections below preserve earlier decisions/results and are not current general-accuracy claims.

ReproLens helps a student maintaining a Python tool turn scattered bug descriptions and selected logs into an issue they can review, correct and share. This is the original DIRECTION.md scope. A previous coordinator brief incorrectly changed it to research claims; that PRODUCT is preserved in the private incorrect-brief-preserved record. The owner never requested that change.

## User, task and result

Target user (hypothesis): a student or independent developer receiving a classmate's short description, a log fragment and follow-up messages. The repeated task is to assemble environment, ordered steps, actual result and expected result; identify what is still missing; correct classification; and produce a usable issue without losing the original material.

Inputs: user-authored description (up to 6,000 characters), deliberately chosen UTF-8 text/log/code/Markdown/CSV/JSON files or pasted notes, up to 12,000 total source characters / 24,000 bytes. No code execution, repository scanning, paper analysis or automatic reproduction. Model input is independently capped at 6,000 characters by default: longer cases remain fully saved and editable, and AI refuses rather than truncates. The UI shows both limits.

Output: an editable report with four concrete sections, missing-section prompts, a confirmed Markdown issue in Chinese or English, optional raw-source attachment, and a private JSON case archive. Interface translation never translates user material. Every server mutation retains a version; restoring an earlier version creates a new unconfirmed version.

Main path: create/import → optionally organize with clearly labelled rules or a configured local AI → compare with source → edit title and report fields → save → fill or explicitly leave missing details → review content/privacy → confirm current report → preview/copy/download issue. Sources and original model selections are kept separately from reviewer wording. AI failures preserve usable drafts and can be retried. Refresh and language changes preserve unsaved browser drafts; version conflicts require choosing the latest or retained draft.

## Evidence and unverified assumptions

The direction research archived Python and Chromium's official bug-report guidance. It establishes the report structure and need for concrete steps/environment/expected/actual results; it does not establish adoption, report frequency or time savings for students. See the existing DIRECTION.md and docs/DIRECTION_AND_REVIEW_20261023.md. No user interview or usability study is claimed.

Open questions: whether these users receive enough fragmented reports to need a separate tool; whether a Markdown template suffices; whether AI classification reduces correction effort; whether local storage is preferred. Test by observing the same user complete the same real report with a template and ReproLens; record omissions, corrections and time, without assuming improvement.

Historical model evidence is retained: six Qwen3-4B cases had one pass, one partial and four semantic failures. Exact quotations were not proof of correct classification. New semantic acceptance requires fresh inference through the coordinator's shared free/local runtime and independent scoring; coding-agent reasoning is never product inference. A complete manual report workflow is useful independently of that pending acceptance.

## Delivered operating scope

Private single-user local application, one service on loopback. SQLite WAL with durable directory, schema migration, immutable revision snapshots, transactional compare-and-swap, idempotent creation, online backup and restore to a new database. Public/team/multi-instance hosting is not supported by this scope. No identity provider or PostgreSQL is introduced without such a requirement. The local machine's user account protects files; they are not encrypted by this application. Private databases, raw inputs and failure records are excluded from public source packaging.

## Architecture hardening2026-10-24

The same end-to-end user task now survives page refresh and process interruption through persisted AI jobs and typed LangGraph stages. Users can keep editing while AI works; a proposal based on an older version is not applied. Queue/cancel/retry states are short user actions, not engineering explanations. This directly addresses loss of work and uncertainty during slow inference; demand, time savings and preference over a Markdown template remain unverified hypotheses. SQLite schema2 and an exclusive service lease implement the local topology; no new team/public hosting claim is added.


## 2026-10-23 latest verification

Fresh Qwen3.5-4B evaluation: two separately preserved serial six-case batches,6000 input characters/1200 output tokens. First batch had correct evidence/category/gap judgments but one wrong-language question. The explicit-language batch passes all six bounded cases, including actual empty selection for non-incident instructions. This is not a general accuracy rate or demand validation. Historical failures remain unchanged. Transport hardening now covers the complete ASGI receive/response lifecycle and offloads asynchronous-route SQLite work from the event loop. Generic OPENAI credentials/configuration are ignored even on ordinary direct application import.
