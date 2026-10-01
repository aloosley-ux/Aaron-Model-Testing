# Contributing

Read README, AGENTS.md, architecture and methodology. Use Python 3.12, a local virtual environment and feature branch. Install the dependency lock, then `pip install --no-deps -e .`. Tests use fake native adapters and tiny generated GGUFs; no GPU or production service is required.

Run `.\scripts\check.ps1` (dependency consistency, Ruff, pytest), then `.\scripts\validate.ps1` (isolated real HTTP inventory/profile persistence and cleanup). Inspect `git diff --check`, the full diff and status; keep generated evidence ignored and report remaining manual validation. Optional `npm ci` and `npm run test:ui` check the shipped JavaScript against a running API in an isolated DOM. Use browser visual QA when available. The UI itself requires no Node installation. Runtime changes also need a native smoke/cleanup check on supported hardware. See README for commands and AGENTS.md for the definition of done.

Keep benchmark versions immutable. Changed frozen definitions/scoring/workloads require a new version, preserved source and determinism/golden tests. Do not regenerate existing locks. Add adversarial scoring cases and ownership/cancellation tests where relevant. Extend bounded Python syntax with budgets rather than host execution.

Reuse code after checking its licence/revision; retain notices and document adaptations. Never copy reference-only source. Keep weights, binaries, settings, databases and generated results out of Git. PRs should explain behaviour, validation and measurement/version implications.
