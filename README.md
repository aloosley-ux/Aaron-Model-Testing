# Aaron Model Testing

A local GGUF model lab for **Windows 11, AMD Vulkan and native llama.cpp**. Find the best tested stable configuration for each model, then measure speed, practical capability and reliability with controlled workloads. Each model can use its own chat template, sampling, reasoning mode, GPU offload and cache settings.

The app runs at **http://127.0.0.1:4321**. Its owned inference process uses **127.0.0.1:1235**, one lane. It never attaches to, stops or reconfigures Cortana on port **1234**. Nothing is installed as a background service. The frontend works offline and needs no build step, CDN or Electron.

## Start on this machine

Open PowerShell:

```powershell
Set-Location -LiteralPath 'C:\AI\Aaron Model Testing'
.\Start-ModelTesting.ps1 -Install  # first launch / update dependencies
```

For subsequent launches:

```powershell
.\Start-ModelTesting.ps1
```

Open **http://127.0.0.1:4321**. **Ctrl+C** stops the app and its owned benchmark process. The launcher uses a project-local Python 3.12 virtual environment; no administrator rights are needed. If your PowerShell policy blocks scripts, use the direct Python commands below rather than changing system policy.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m aaron_model_testing serve
```

Python 3.12+ is required. The lock file is tested with Python 3.12 on Windows x64. A native Vulkan build of `llama-server.exe` must already exist. The app discovers it on PATH; **Settings** lets you select an exact binary and `Vulkan0`. The RX 9060 XT is `Vulkan0` in the tested build; check **Inspect runtime / hardware** if device numbering changes. `llama-bench.exe` can be recorded in settings for manual cross-checks; v0.1's automated pipeline uses the server's native timing counters plus client streaming measurements.

## Run the first real benchmark

1. **Settings:** check the native server path and selected Vulkan device. Add all model directories, one per line. This machine's models are under `%USERPROFILE%\.lmstudio\models` and `%USERPROFILE%\AI\Models`. Hashing reads the entire file; allow time for large inventories.
2. **Models → Scan:** scan directories or register a single GGUF. Models stay in place. Split models require all shards; projector/embedding GGUFs are inventoried as auxiliary files.
3. **Model detail → Save profile:** start with BALANCED, context 4096, GPU layers 999 (full offload), Flash Attention on and f16 K/V cache. For a larger model, use partial GPU offload if full offload fails. Settings are editable JSON; saves create immutable revisions. An adjacent `.jinja` or `chat_template.jinja` is copied into the profile. Otherwise llama.cpp uses the embedded template.
4. **New benchmark:** select the model and profile, then choose **PIPELINE SMOKE TEST** first. It runs three short performance repeats and three capability questions, each repeated three times, at a small context. Smoke runs validate plumbing and are excluded from the leaderboard.
5. **Automatic optimisation:** choose **quick**. It tests up to eight configurations, each with at least three repeated unscored workloads and a templated chat health check. It saves the best stable tested configuration under FAST, BALANCED or SMART.
6. Refine by selecting the saved winner and running **standard**, **thorough**, then **drill**. Budgets are 24, 64 and 32 candidates respectively. Optional tuning contexts search memory/context tradeoffs with the same 256-input/128-output workload. SMART prioritises the largest tested stable context, then workload time. This is bounded search, not a proof of a global optimum.
7. Screen the winning profile with **QUICK QUALIFICATION** (the default): performance at `2048,8192`, all 31 standard capability tasks at the saved profile context, three repeats, long-context matrix off. Promising models can then use **FULL QUALIFICATION**: performance at `2048,4096,8192`, the same standard suite, and five long-context task types at 10%, 50%, 90% insertion depths at each requested context, three repeats. Both are leaderboard eligible, labelled separately and have distinct comparison identities. Full can take minutes to hours. Custom benchmark / optimisation exposes explicit settings; preset settings are enforced by the API.
8. Use **Leaderboard**, **Compare** and **Runs**. Compare matching workload groups. Click a capability row to inspect the exact prompt, grading rule, raw answer, reasoning, native tool calls, token budget and timings. Download the artifact ZIP when finished.

Active run pages poll every three seconds. **LIVE / PARTIAL** values cover completed inference samples, with the current phase/test/context/repeat, progress, elapsed time, rough ETA, cumulative capability/reliability, pass/fail/error counts and median native throughput from the last 12 successful samples. A 30-entry activity feed and available process CPU/GPU/VRAM counters update during requests. Missing telemetry stays unavailable. Progress excludes separate load observations. Completed runs show **FINAL** aggregates; cancelled/failed/partial runs remain labelled partial. Cancel from the monitor or job strip; only the app's owned inference process is stopped.

For SMART reasoning qualification, copy a profile, enable `sampling.enable_thinking` where the template supports it, increase `sampling.token_budget` (for example 4096), and choose a context with enough generation space. Sampling and reasoning support are model specific: the generic `enable_thinking` switch is not universal. Appropriate template contents and validated runtime options can be supplied per profile. SMART is an intention; capability must still be measured. Optimisation never uses the scored questions.

## Measurements

- Actual token counts, native prompt/generation tok/s, streamed TTFT, time to first final-answer content and request latency.
- At least three performance/capability repeats; three startup-to-health observations per context by default. Startup uses a warm OS file cache, not cold-disk loading.
- Median, minimum, maximum and sample variance; failed and truncated responses remain inspectable.
- Process RAM/CPU. Windows per-PID counters provide sampled dedicated VRAM peaks and busiest-engine utilisation when available. Sparse sampling can miss peaks; this is not whole-device utilisation. Vulkan buffer allocations are labelled separately. GPU sampling can be disabled in Settings for a consistent lower-overhead group.
- Strict exact/JSON schema/tool validation and bounded pure-Python function unit cases. No LLM judge. No untrusted model code is executed on the host.

This small public suite is a practical qualification baseline, not a comprehensive intelligence ranking or contamination-resistant research dataset. Capability, speed and reliability are separate. See [methodology](docs/METHODOLOGY.md).

## Durable data and reproduction

Generated data lives in ignored `.local/`. Set `AMT_DATA_DIR` before launch for another location. SQLite is an index; inventory, profiles, jobs and run manifests also exist as JSON. Each run preserves append-only samples, full model metadata, frozen benchmark/application/optimiser sources, commands, runtime/build/DLL hashes, environment, responses, telemetry, errors, retained licence notices and checksums. Exports of older development runs also include supplemental distribution notices without changing their original artifacts.

```powershell
# Verify an extracted run artifact directory
.\.venv\Scripts\python.exe -m aaron_model_testing verify '.local\artifacts\RUN_ID'

# Stop the app first; rebuild SQLite rows after restoring a complete data-directory backup
.\.venv\Scripts\python.exe -m aaron_model_testing reindex

# Deterministically regrade a completed/partial run without inference
.\.venv\Scripts\python.exe -m aaron_model_testing regrade RUN_ID
```

Back up **all of `.local/`**, not just SQLite. ZIPs do not contain weights or native binaries. Rerun with the recorded model hash, exact binary/DLL build, saved profile and workload request; create a new run rather than overwrite history. Full model hashes are checked before each run. Modified benchmark code under an existing version fails validation. Seeds help repeatability, but Vulkan output is not promised to be bit identical across driver/build changes.

v0.1.1 uses **agent-core-v1.1**: unchanged v1 questions, rules, interpreter, performance workloads and long-context generator, with a frozen reasoning-aware grading wrapper. Native reasoning is preferred; a targeted leading `<think>...</think>` fallback extracts the final answer without stripping arbitrary markup. Raw content and stream events remain exact. Malformed reasoning boundaries produce explicitly unavailable grades rather than a confident aggregate zero. Truncated generations still fail under the existing rule.

**Regrade saved responses** on a terminal run page, or use the CLI above. The source must have a complete verified checksum inventory, recognised frozen sources and preserved test/prompt identities. A new run stores updated grades, the original grades and reasoning, a full source-evidence copy, new grader/harness identities and source hashes. Historical manifests and raw evidence are never changed. Affected legacy v1 capability results are shown as unvalidated until regraded. Regrading is safe alongside the app because it writes only a unique derived run and uses SQLite transactions; it launches no native process.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check aaron_model_testing tests
```

Optional frontend DOM checks against a running app with inventory/results:

```powershell
npm ci
npm run test:ui
```

Node is only a development testing dependency. The shipped UI is static HTML/CSS/JavaScript. Read [architecture](docs/ARCHITECTURE.md), [research and reuse](docs/RESEARCH.md), [validation](docs/VALIDATION.md) and [contributing](CONTRIBUTING.md).

MIT licensed. Substantial reuse and retained copyrights are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). LLM-Tuner and BenchMax were design references; their code was not copied. OpenClaw, Paperclip and Cortana production acceptance remain future stages.
