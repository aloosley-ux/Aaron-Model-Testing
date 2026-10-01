# Development instructions

Aaron Model Testing is a local GGUF optimisation and qualification lab for Windows 11, Python 3.12+ and AMD Vulkan. One FastAPI process serves REST and offline static HTML/CSS/JS on loopback 4321; one FIFO worker owns native llama.cpp inference on loopback 1235. JSON/JSONL artifacts are durable; SQLite is a disposable index. No production Node runtime or build step is required.

## Workflow and commands

- Read the task and these instructions. `TASK.md` is a reusable task contract; fill it only when useful, and honour the maintainer's current request. Inspect Git branch/status and relevant docs before edits. Use a feature branch, preserve unrelated work, and never force-reset or rewrite history.
- Setup/start: `.\Start-ModelTesting.ps1 -Install` initially, then `.\Start-ModelTesting.ps1`; Ctrl+C shuts down owned work. Use the locked `.venv` environment. Direct setup commands and runtime requirements are in [README.md](README.md). Preserve both dependency locks. RTK is only this maintainer's command proxy, never an app dependency.
- Health: `.\scripts\check.ps1` runs dependency consistency, Ruff and the existing pytest suite (including frozen benchmark, ownership, cancellation and pipeline tests).
- Real validation: `.\scripts\validate.ps1` starts the real HTTP app in-process on OS-assigned loopback ports, scans a tiny generated GGUF, saves a profile, restarts and checks persistence and cleanup. Evidence stays in a unique ignored `.local/validation/` directory. It never loads weights for inference or uses the normal data directory, and can run alongside the normal app.
- Definition of done: implement only the task scope, fix check/validation failures, inspect `git diff --check`, the complete diff and status, keep generated/local files ignored, then leave reviewable changes and report commands, evidence and remaining limitations. Do not commit/push unless requested.
- Continue autonomously on routine reversible work. Ask only for a materially ambiguous requirement, destructive action, production/customer data, missing credentials/permissions or a material scope change.

## Paths and references

`aaron_model_testing/app.py`, `static/`: API/UI; `pipeline.py`: jobs/artifacts; `runtime.py`, `processes.py`: native ownership; `inventory.py`, `profiles.py`, `store.py`: model/profile/data lifecycle; `suite.py`, `benchmarks/`: frozen measurement versions; `tests/`: pytest and optional DOM integration; `scripts/`: development entry points. Normal generated data/settings live in ignored `.local/` (or `AMT_DATA_DIR`); do not use existing results as scratch data.

Read [architecture](docs/ARCHITECTURE.md), [methodology](docs/METHODOLOGY.md), [validation](docs/VALIDATION.md) and [contributing](CONTRIBUTING.md) as relevant. Native inference requires a separately installed Vulkan `llama-server.exe` and real GGUF weights selected in Settings. The automatic validation does not prove GPU inference or browser appearance: runtime changes require the hardware smoke/cleanup check below; UI changes require DOM checks and browser visual QA when available.

## Project constraints

Build a coherent local model lab for Windows 11 + AMD Vulkan. Prefer adapting existing licensed work over reinventing working components; review source and licence before reuse. Keep provenance in THIRD_PARTY_NOTICES.md and preserve upstream notices.

- Use a feature branch; do not change main directly. Respect maintainer session instructions. On this maintainer's machine, also follow `C:\Users\da_re\.codex\RTK.md` when present (prefix agent shell commands with `rtk`). RTK must not become a runtime dependency.
- Never connect benchmarks to port 1234, stop processes by executable name, modify Cortana configuration, or override networking through profile options. Only owned PID/trees on loopback port 1235 may be terminated. Never add a permanent service.
- Use argv-based `shell=False` processes, Windows Job Objects and bounded deadlines. Test cancellation/shutdown when changing ownership. Probe the selected binary's `--help`; legacy flags disappear. Select one Vulkan device. Avoid CUDA/NVIDIA assumptions.
- Stream model hashes and read GGUF metadata without loading weights. Keep generated data, GGUFs, databases, binaries, research trees, logs and workspaces ignored.
- SQLite is disposable. Write artifacts before updating the index. Preserve every attempt and partial response. Do not fabricate counts, substitute SSE chunks for tokens, turn absent telemetry into zero or hide failed scheduled samples.
- Files locked in `benchmarks/versions.lock.json` are immutable. Do not regenerate a lock to conceal changes. Publish a new benchmark version with preserved frozen source when scoring/workloads change. Formatting also changes file hashes.
- Optimisation must not query scored questions. SMART does not imply measured intelligence. Comparison identities must include changes affecting measurement.
- Never eval/exec/spawn untrusted model code. Coding tests use the bounded interpreter; extending syntax needs adversarial/budget tests.
- Keep the UI offline with no production Node/build-server dependency. Escape model output and paths before HTML insertion.
- Run pytest and Ruff. For UI changes, start the app and run optional `npm run test:ui`; distinguish DOM checks from browser visual QA. Runtime changes need a small native smoke test if available, artifact inspection and proof that 1235 releases while the production PID remains unchanged.
- Keep documentation accurate and limitations explicit. Do not implement future integration stages unless requested.
