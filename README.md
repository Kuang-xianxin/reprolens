# ReproLens

**Turn scattered bug evidence into an issue you can check.**

A private local workspace for students and independent developers who receive a description, a log and follow-up messages. Organize environment, steps, actual and expected results; jump from a report line to its source; correct the draft; then export only the evidence you choose.

把零散的问题描述、日志和补充回复整理成可核对的 issue：逐条回到原文，修改后重新检查，再导出需要分享的材料。

## Try a complete report

Python 3.12 on Windows is the verified platform. Manual editing requires no paid account, model download, frontend build or database server.

```powershell
python -m venv --without-pip .venv
python -m pip --python .venv/Scripts/python.exe install --no-clean --no-compile -r requirements.lock.txt
.venv/Scripts/python.exe scripts/serve.py
```

Open `http://127.0.0.1:8211`. See [deployment](DEPLOYMENT.md) for explicit local-model configuration. The launcher binds loopback and discards inherited provider keys and endpoints. Public/team hosting is outside this release.

1. Create an issue from a description and deliberately selected UTF-8 files.
2. Edit the four sections manually, use labelled rules, or ask a configured local AI to organize the sources.
3. Expand a section's source matches and jump to the original line. Matching is recomputed as you edit; rewritten text is marked for checking.
4. Correct categories and omissions. Source matching establishes where text came from, not that it is true or complete.
5. Save, review content and privacy, and confirm this version. Preview/copy/download Markdown with optional cited excerpts or full sources. Both are off by default.
6. Reopen saved issues, add new evidence, or restore an earlier version as a new draft. Changes require confirmation again.

## A reproducible example

```powershell
python examples/csv-lab/reproduce.py --output runtime/my-csv-lab
```

Use a new output directory. The intentionally faulty standard-library CSV reader produces `12.50` for plain UTF-8 and `KeyError: 'amount'` for a file with the same rows and a BOM. Import its `steps.txt`, `observed.log` and `environment.txt`. This is an executed controlled example, not a customer incident. ReproLens itself never runs submitted code. [Demo guide](docs/DEMO.md)

## What is different

A Markdown template already provides the right headings. ReproLens adds preserved sources, edit-aware source lookup, explicit confirmation, version recovery and selective evidence export. A local model proposes categories using source references; program code copies exact fragments and checks offsets. Reviewers can fix a classification without rewriting the source or disguising the model's original result.

No user study establishes that this is faster than a template. The audience, adoption and time-saving benefit remain hypotheses.

## Quality and boundaries

The current model contract is `source_selection_v3`. Fresh evaluation exposed overlapping full-line/fragment selections; the adapter now offers one non-overlapping granularity per line. In the resulting ten-case diagnostic batch, agent semantic review found seven sufficient results and three partial results. Remaining problems include omitted expectations/corrections and missing questions. These were constructed cases; reused diagnostics are not an independent accuracy estimate. Historical failures are retained. [Evaluation details](docs/EVALUATION.md)

AI only helps organize supplied text. ReproLens does not reproduce bugs, diagnose causes, scan repositories or post issues. Cases retain at most 12,000 source characters / 24,000 UTF-8 bytes; AI defaults to 6,000 characters and refuses oversized input without truncating the saved case. Sources are local files protected by the OS account, not application encryption.

## Implementation and checks

FastAPI/Pydantic + SQLite WAL + native JavaScript/CSS; HTTPX calls an explicitly configured loopback model. LangGraph runs typed stages inside durable SQLite-backed jobs. Refresh does not lose a job, and a stale AI proposal cannot overwrite a newer saved draft. [Architecture](docs/ARCHITECTURE.md) · [Evidence trace and learning notes](docs/SOURCE_TRACE.md)

```powershell
.venv/Scripts/python.exe scripts/check.py
node scripts/check-frontend.mjs
node scripts/check-source-trace.mjs
```

Tests use isolated databases. Mechanical checks and model semantic review are different evidence. The package excludes live databases, private inputs, model weights and credentials.

## Contest and attribution

MIT source. This project was developed with substantial Codex agent assistance and the Devpost Learn Skill Pack. [Scope](devpost/scope.md), [PRD](devpost/prd.md), [specification](devpost/spec.md), [actual skill usage](devpost/skill-use.md) and [checklist](devpost/checklist.md) preserve the planning chain. Participant review, personal learning reflection and any final submission are not inferred from agent implementation or tests.
