# Architecture

One FastAPI process serves static assets and REST on loopback 4321. A single in-process FIFO worker handles inventory and inference jobs. Durable JSON/JSONL records are indexed by SQLite WAL. No scheduler, Redis, containers, Electron or permanent service is required.

| Module | Boundary |
| --- | --- |
| `inventory.py` | Many roots, split grouping, official metadata-only GGUF reader, streamed hashes, identity verification. |
| `profiles.py` | Immutable validated runtime/sampling revisions; external template contents captured; bounded model options exclude networking/RPC/model substitution/additional lanes. |
| `vendor/`, `tuning.py` | MIT matrices, drills and graders composed with diverse bounded GPU/context search and repeated stability selection. |
| `processes.py` | Owned PID/tree lifetime with Windows Job Objects; hidden child processes; RAM/CPU and optional per-PID GPU counters. |
| `runtime.py` | Native build/help/device probe, DLL hashes, current/legacy flag translation, health/socket ownership, streamed requests and native counters. |
| `pipeline.py` | Plans, repeats, warmups, matrix, cancellation, optimisation, profiles and durable artifacts. |
| `scoring.py`, `codecheck.py` | Deterministic schema/tool checks and budgeted AST unit cases; no host eval/exec. |
| `suite.py`, `benchmarks/` | Frozen v1 definitions/scorers/generators/workload hashes and change detection. |
| `store.py` | Separate SQLite connections, short transactions, file-first writes, recovery/reindex. |
| `app.py`, `static/` | Loopback/origin checks, queue controls, history/comparison/inspection and offline SVG charts. |

## Ownership

An occupied 1235 is refused; its owner is never stopped. Runtime uses an argv list and `shell=False`, a single selected Vulkan device, fixed host/port/parallel count, and removes inherited `LLAMA_*` overrides. Current `--load-mode` replaces older mmap flags where advertised. Automatic fitting is disabled where supported, so requested context/offload cannot silently shrink. Socket ownership must match the new PID before inference.

Windows Job Objects kill the owned tree on close or abrupt parent death. Cancellation closes only that job. Shutdown signals pending jobs, closes the active server, waits for the worker and releases the data-directory lock. Interrupted records are marked on next startup; no old process is attached to or killed. GPU counter queries are bounded transient hidden PowerShell children, active only during telemetry.

An adaptive private-memory limit reserves headroom using available/total RAM. This guards heap/commit growth; mapped pages and driver allocation semantics differ from RSS. Full offload/CPU failures remain candidate evidence; search proceeds to other configurations within its budget.

## Durable layout

```text
.local/
  settings.json
  index.sqlite3
  models/<id>.json
  profiles/<id>.json
  jobs/<id>.json
  runs/<id>.json
  artifacts/<run-id>/
    manifest.json       identity, profile, request, build, environment, argv, status
    model.json          full GGUF metadata/template snapshot, written once
    records.jsonl       individual attempts, scores, partial streams, errors, lifecycle
    benchmark.json
    benchmark_sources/  exact frozen definition/scorer/generator/workload sources
    app_sources/        exact harness sources
    runtime.json        executable/DLL hashes, version, advertised help/device list
    summary.json
    checksums.json      all finished archive files except itself, including manifest
    context-*/          server logs, warmup, CPU/RAM/GPU samples, overridden Jinja
    candidate-*/        equivalent tuning data and chat health checks
    candidate-plan.json
    winner.json
  exports/<run-id>.zip
```

Atomic replacement/fsync protect JSON writes. JSONL appends flush before index updates. Interrupted JSONL can have an incomplete final line; API reads report this. Finished artifacts support independent checksum verification. Back up the whole data directory. Reindex restores SQLite rows from JSON; ZIPs preserve evidence without binaries/weights. Detail GETs return compact samples; the response endpoint retrieves full streams on demand.

## Later stages

Current boundaries cover Stage 0 inventory, Stage 1 optimisation, Stage 2 performance and Stage 3 capability. Stage 4 sterile OpenClaw qualification, Stage 5 controlled Paperclip orchestration and Stage 6 Cortana acceptance are absent. Add separate versioned workload/scorer packages and sterile workspace adapters using the same owned runtime, JobManager, immutable profiles and ArtifactRun. Do not share mutable agent memory/tools/network state with Stage 3. Production acceptance needs explicitly requested integration scope. Add stage types and comparison identities rather than changing old benchmark definitions.
