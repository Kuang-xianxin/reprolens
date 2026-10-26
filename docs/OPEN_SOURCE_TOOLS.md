# Tool and dependency provenance

2026-10-24 continuation: the existing Qwen3.5-4B weight file was verified against the retained SHA256 and its local runtime restarted without downloading weights. The current trace UI used Impeccable reference guidance; its context loader did not return and was stopped. Two ui-ux-pro-max searches did not yield an applicable recommendation. Source/semantic checks and actual Egolite inspection are the evidence for this change; no automated design-audit pass is claimed. Earlier descriptions below refer to earlier development rounds.

Runtime stack is pinned in requirements.lock.txt. Python standard-library SQLite provides the database; no new database server, paid provider, remote telemetry or cloud deployment was installed. A fresh virtual environment installed that lockfile and passed dependency checks. Package metadata/license inventory is retained in the private delivery record.

Design tools: the already installed ui-ux-pro-max local search library and Impeccable references were used as instructed. Their shared installation/source receipts belong to the coordinator's design-tools record. This project ran the local UI search only, rejected a mismatched landing-page recommendation, and used the productivity/editor and error-recovery results. Impeccable launcher, hooks and recursive cleanup were not executed. The frontend uses original layout/CSS and an original geometric SVG mark, not a copied proprietary theme.

Formatting: Prettier3.6.2, MIT, obtained from the public npm registry with exact tarball SHA512 integrity validation. Tar members were checked to stay inside the selected tool directory, with symlinks/hardlinks refused. The formatter ran directly through Node; npm install/lifecycle hooks/automatic cleanup were not run. It is a development tool, not shipped in the app or required to run it. Its package LICENSE and receipt are retained with the downloaded tool.

Model: Qwen3.5-4B Q5_K_M runtime was allocated by the parent coordinator, who provided an Apache-2.0 license record and weight SHA256. This worker did not download weights or change the runtime. Production requests use the allocated local model ID, never the coding agent as an inference endpoint. The supplied model license is coordinator evidence, not an independent weight-file audit by this worker.

The ReproLens source license is MIT. Public publication is still not performed; the source ZIP is an allowlisted review artifact. Raw inputs, historical failures, existing databases, private registration files and runtime configuration are not included.
