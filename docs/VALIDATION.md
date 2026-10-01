# v0.1 validation record

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
