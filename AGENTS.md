# Development instructions

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
