# v0.1 validation record

## v0.1.1 hardening validation (2026-10-01)

- **66 pytest tests pass**, including exact/multiline/JSON/native-tool answers after reasoning, native reasoning preference, malformed blocks, raw preservation, checksum/test-identity refusal, derived regrading, legacy invalid-result presentation, qualification presets, live progress during blocked inference and active cancellation. Ruff lint, formatting of changed Python files, frontend formatting/syntax and dependency checks pass. The frozen v1 entry/files are unchanged; v1.1 is separately locked. The test environment emits one existing Starlette/httpx deprecation warning.
- **Frontend DOM tests pass** against a temporary real app on `127.0.0.1:4322`: navigation, profile editor, Quick/Full/Smoke preset controls, disabled-field submission, inspector, comparisons, live polling, bounded activity, HTML escaping and final/invalid states. The shipped JS also observed an actual native run's progress increase while inference was active. Connected computer-use inventory returned no browser surfaces; **browser visual QA was not performed**.
- **Existing QClaw full run `f81a12410ff64ef6984cd6911f0bc085` was regraded without inference.** Derived run `b7cd1dde4753471d98721fe047c24b81` has **73.6842% capability (168/228 passes)**, 100% reliability, zero runtime errors and unchanged native performance measurements. All 246 source records (237 inference attempts and 9 load observations) remain intact. The new artifact copies the complete verified original evidence and stores previous grades, parser/grader versions and changed harness/comparison identities. Source and derived checksums verify. Fifty-one token-budget truncations remain failures. A first derived attempt hit a Windows reader lock and is retained as failed; bounded atomic-replace retries resolved it without altering original evidence.
- **Real Vulkan capability/performance validation:** QClaw Q8_0, saved FAST profile, three `instruction-label` repeats at its 4096 profile context and three performance repeats at 2048. Run `3d599c3fedc84695a24eb6d2a5ba9003` completed with capability/reliability 100%. Every actual `<think>...</think> READY` answer was preserved raw, extracted into reasoning/final fields and passed. RX 9060 XT/Vulkan0 logs, CPU/GPU/VRAM monitor snapshots and artifact checksums were inspected; decode median was 54.28 tok/s. This focused validation was not a full qualification rerun.
- **Real cancellation:** performance run `52b8c495be2a4012a4e725d594368b13` was cancelled during its third generation after two successful 1024-token repeats. Its two successful samples and failed partial third stream remain inspectable; job/run are cancelled and checksums verify. Owned PID 27216 exited and port 1235 released. The successful run's owned PIDs 28092 and 30676 also exited. Read-only listener/PID creation-time checks retained Cortana PID 4960 on 1234 throughout. No request was sent to 1234 and no production configuration was touched.

The pre-existing user app on 4321 was left running. Validation used a separate ignored data directory (`.local/v011-validation`) and a temporary foreground app instance. That instance was stopped; 4322 released, a fresh bind on 1235 succeeded, and both the production and pre-existing app PID/creation times remained unchanged. Restart the normal app to load the new Python API. No 40-minute inference benchmark was repeated. Reasoning extraction does not repair genuine wrong answers or exhausted token budgets; embedded-thinking TTFA retains its first-content timing limitation described in methodology.

The sections below retain the original v0.1 validation record.

Validated on the target Windows 11 machine on 2026-10-01 with Python 3.12, AMD Ryzen 5 7600X, 32 GB system RAM and RX 9060 XT 16 GB. Native llama.cpp build 11015 (`c57da6fd8`), Vulkan. Generated evidence and weights remain outside Git in `.local/` and `.research/`.

## Automated validation

- **37 pytest tests pass.** Coverage includes synthetic GGUF inventories and shards, full hashes, frozen benchmark hashes, deterministic grading, bounded adversarial coding responses, streamed native token accounting, partial responses, context failures, optimisation budgets, SMART context selection, durable artifacts, reindexing, queued cancellation, interrupted recovery and owned Windows process-tree cleanup.
- **Ruff passes.** `pip check` reports no broken requirements. Exact dependency versions are pinned in `requirements.lock.txt`.
- **Live frontend DOM checks pass** against the running app: leaderboard, inventory, metadata, profile editor, run form, test definitions, runtime settings, run history, response inspector and comparison charts. The optional Happy DOM development dependency was upgraded after an audit finding; final `npm audit` reports zero vulnerabilities.
- Built and installed the distributable wheel into an isolated test directory. Verified immutable suite loading and resolution of the project licence, third-party notices and all three retained MIT licences. New run bundles snapshot notices and optimiser source; exports also supply the notices for older development runs.
- Native run artifact verification passes, including the hardware verification's 35 checksummed files. Benchmark sources are also checked against the Git index so Windows line-ending conversion cannot invalidate the frozen version.

The connected computer-use provider exposed no browser surfaces. The frontend was exercised through its real shipped JavaScript and live API in an isolated DOM; **browser visual QA was not performed**. This is recorded rather than represented as a screenshot review.

## Real native pipeline

Registered 18 unique GGUF files from the two existing model roots, with deduplication of resolved aliases and identification of auxiliary projector files. One custom `Ternary-Bonsai-2-27B-PQ2_0.gguf` file could not be read: quantisation type 142 is unsupported by the installed official GGUF reader. Its failure is retained in the scan job and shown in the Models view. Compatibility with a specialised Bonsai runtime is not claimed.

Using existing Qwen3.5-2B Q4_K_M weights:

- Smoke runs completed three performance requests and three capability tasks repeated three times, including real raw responses and deterministic scores. Smoke runs are excluded from the leaderboard.
- A real **quick optimisation sweep tested eight candidates**, three performance repeats and an unscored chat health check per candidate. Run `29c283775dda43899837039711a80249` saved a FAST winner with full offload, six threads, batch 1024, ubatch 512, Flash Attention and f16 caches.
- Full capability qualification, run `9c643e5ca76f410f9e705f54f47070fc`, completed **123 scored responses plus three performance requests**: 31 core tasks and five long-context kinds at two depths, repeated three times. Transport reliability was 100%; capability was 67.07%. This small model's actual failures remain inspectable; success does not mean it answered every task correctly. This initial run used a 2048-token context and is not proof of 32K+ capability.
- Updated smoke validation exercised **three separate load observations** and sampled Windows RAM/CPU/VRAM/GPU counters.
- Focused [hardware verification](HARDWARE_VERIFICATION.md) confirms RX 9060 XT on Vulkan0, effective 25/25 layer offload and telemetry agreement. The sole acceleration-verification fix enables otherwise hidden device/offload logs; inference settings were unchanged.

## Isolation, cancellation and shutdown

All native HTTP requests used the owned benchmark listener at **127.0.0.1:1235**. The app used **127.0.0.1:4321**. Read-only socket inspections consistently showed Cortana on port 1234, PID 4960; no production requests, configuration changes or termination occurred.

An active performance job was cancelled through the API: job and run became `cancelled`, port 1235 released and its owned inference process exited. A separate active job was interrupted by closing the app through Ctrl+C: app and inference listeners disappeared, owned inference PID 8236 was gone and port 1234 retained PID 4960. On restart the app preserved the three completed performance samples and marked the job/run `interrupted`, without attaching to an old process. The PowerShell launcher was also started successfully against the installed environment.

## Practical limits

This is a usable initial local lab, not proof that every installed model has been optimally tuned. Only the identified small model received real tuning and capability qualification during validation. Standard/thorough/drill search and larger context matrices are implemented and covered by automated checks, but exhaustive real sweeps would take much longer. Native `llama-bench` is discoverable for manual cross-checks; automated v0.1 measurement uses the native server. No OpenClaw, Paperclip or production acceptance integration is implemented.

GPU counters are sampled and nullable; they can miss peaks. Coding qualification accepts bounded pure-Python function syntax rather than arbitrary project execution. Public deterministic questions can be memorised and cover a limited practical workload. Compare matching workload/build/environment groups and inspect raw answers before interpreting results.
