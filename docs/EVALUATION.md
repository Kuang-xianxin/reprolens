# Model evaluation and limits

Recorded 2026-10-24/25, local Qwen3.5-4B Q5_K_M, temperature0, structured JSON,6000 source characters,1200 output tokens. Calls used production persistent jobs → LangGraph → local model, serially under the shared inference lock. Coding-agent text was not substituted for product inference. Inputs are constructed diagnostics, including logs from an actually executed controlled CSV lab.

## What happened
The first fresh eight-case run exposed whole mixed paragraphs assigned to one category, redundant questions and omitted corrections. A fragment version offered both full lines and their parts; three paragraph cases failed closed with overlapping-reference errors. Those failed runs remain in the private evidence archive.

The next revision offers one non-overlapping granularity per line. The same ten diagnostics were rerun once without per-case retries. Two cases originally withheld from prompt changes had already been seen in the preceding fragment failure run; they are regression cases in this final batch, not pristine holdouts. The original mechanical rubric expected some full lines and therefore fails when equivalent fragments are selected. Its raw results were preserved, not relabelled.

## Agent semantic review of final ten diagnostics
| Case | Assessment | Evidence |
|---|---|---|
| Actual CSV lab, complete input | Sufficient | Both outcomes, input steps, Windows/Python and12.50 expectation retained |
| CSV lab, missing environment | Partial | Core evidence retained, no model question for missing environment |
| Chinese negation | Sufficient | No-crash negation, stale value and refresh behavior retained as observations |
| Unknown versions | Sufficient | Unknown version not asserted as known; specific version question |
| Instructions embedded in log | Partial | Malicious instructions ignored, actual error retained; explicit expected error handling omitted |
| Only instructions, no incident | Sufficient | Empty evidence selection; needs_evidence result |
| Later Chinese correction | Partial | Actual/expected retained, explicit no-deletion correction omitted |
| Mixed English paragraph | Sufficient | Environment, two steps, observed and expected correctly separated |
| Chinese paragraph | Sufficient | Environment, three actions, empty result and expected header retained |
| Account switch paragraph | Sufficient | Both accounts, switching steps and contradictory displayed data retained |

Seven sufficient and three partial within this bounded diagnostic set. Review was performed by the implementation agent, not an independent human or user study. This is not a general accuracy estimate. Historical six-case successes do not override these newly observed failures.

## Consequences for the product
The source lookup deliberately checks literal location, not meaning. Review the whole source for omissions. Manually correct categories; add missing text; re-confirm after edits. Missing-category labels are deterministic interface checks, distinct from model questions. Suppressing questions about populated sections reduces repetition but can remove useful follow-up detail.

Unmeasured: adoption, time saved against a Markdown template, real-world completeness, accessibility with assistive technology and deployment beyond one local user. No automatic reproduction or root-cause accuracy is claimed.
