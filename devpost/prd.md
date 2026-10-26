---
status: draft
participant_review: pending
execution: explicitly-authorized-delegated-build
---
# ReproLens PRD

## User task
Prepare a specific bug issue from scattered text, with enough traceability to spot omissions and edit mistakes before sharing. A plain Markdown template is the direct alternative. The added cost of a separate tool is justified only if source comparison/version recovery is useful; that remains to be tested with users.

## Screens and actions
- Capture: required title and description; optional deliberately chosen UTF-8 files or notes; explicit size limits.
- Editor: preserved sources and four editable report fields. Label manual/rules/AI origins. Source-match details locate exact full lines or punctuation fragments; edits recompute matches immediately, and unmatched wording remains editable.
- Review: identify missing sections, compare content and review privacy; confirmation belongs to one version. AI does not grant confirmation.
- Export: language headings, copied/downloaded Markdown, optional cited excerpts independently of optional full sources; both off by default. Private case JSON is clearly separate.
- History: browse immutable versions and restore as a new unconfirmed draft.

## Reliability acceptance
Sources ≤12K characters/24KB and initial description ≤6K. AI default ≤6K; refuse rather than truncate. Revisions protect updates; conflict returns409. Creation is idempotent. Saved jobs survive reload and recover after interruption. A proposal based on an older version is superseded. Model failures preserve usable drafts. Local browser drafts survive reload/language switch.

## Evidence acceptance
Test shared Python/JavaScript source-lookup fixtures, Unicode offsets, tampered citations, edits, privacy defaults and revision gates. Exercise the actual UI on desktop/mobile. Record real inference separately from mocks. Inspect categories, coverage, unknowns, corrections and injection attempts, not just quotation validity. See ../docs/EVALUATION.md for failures as well as successes.

## Open gates
Participant review, firsthand learning reflection and user-value validation remain unperformed. Publication needs an approved source package, actual public video and final submission review; a local test is not any of these.
