# Benchmark methodology v0.1

The unit of evaluation is a model fingerprint and saved runtime/sampling profile on a fingerprinted machine/build. Models can use different supported runtime flags. Definitions, scoring, repetition and measurement scope remain controlled. Profile names are intentions, not intelligence labels.

## Identity

GGUF hashes read all bytes. Split identity is the SHA256 of ordered shard-hash JSON, explicitly labelled; every shard hash is retained. Parameter counts come from tensor dimensions and can include embedding/tied-weight representation differences. Filename quantisation is shown with raw file-type metadata. Context capability is declared metadata, not measured success. Auxiliary files are inventoried without text scoring.

Runs reverify hashes and preserve binary/version/DLL hashes, selected device, drivers, relevant CPU/GPU environment, OS/Python/git state, profile/template contents and every argv. Hardware/build/workload/harness differences change comparison identities and trigger comparison warnings. No fixture results are mixed with real measurements.

## Optimisation

Quick/standard/thorough/drill are deterministic finite passes composed from the MIT tuner matrix/neighbours. Early axes include GPU layers, threads, batch/ubatch and Flash Attention; deeper passes add mmap/KV formats. Template, reasoning, sampling and validated model-specific options are inherited from the selected profile. Unsupported flags, formats or allocations become failed candidates. Every candidate and command is preserved.

Default context is fixed. An optional explicit context list interleaves settings across contexts within the total budget. All candidates use the same unscored 256-input/128-output native workload. Each loads separately, warms up and repeats at least three times. All repeats must pass token-count/timing checks; a separate templated greeting checks chat health. Scored questions are never used for tuning.

FAST maximises median decode tok/s. BALANCED minimises `256/prompt_tps + 128/generation_tps`. SMART prefers the largest tested stable context, then that same workload time. Winners are **best tested stable under the recorded plan**, not global optima or intelligence judgements. Use the winner as the next progressive/drill seed. Sampling/semantic quality is assessed separately.

## Performance and reliability

Performance/capability repeat at least three times with recorded seed and one lane. Native `/completion` receives actual token IDs, `cache_prompt=false`, fixed temperature/seed and `ignore_eos=true`. Native counts must equal exact targets and timings must exist; otherwise the sample fails. SSE chunk counts never stand in for tokens. Standard input is approximately 75% of allocated context with generation/overhead space reserved. Smoke uses 256 input/32 output at a small context.

Each context measures warm resident inference after an excluded, archived warmup. Overall headline speed pools successful samples across contexts; context curves give the more precise comparison. Startup-to-health time includes launch, initialisation, polling and socket ownership. Three starts per context are recorded by default (`load_repeats` 1–5). Hashing warms the OS cache: these are warm file-cache startup observations, not disk cold-start measurements. Tuning loads once per candidate and repeats inference within that process.

TTFT ends on first content, reasoning or tool-call chunk. TTFA ends on first final-answer content. Latency includes local HTTP/stream transport. Prompt/decode tok/s use native timings rather than end-to-end throughput. Usage/timings and raw streams remain available.

Show median, min, max, sample variance and standard deviation. Fewer than two observations has unavailable variance. Successful timing distributions exclude failures, but reliability/coverage includes failed context loads and every unexecuted scheduled inference sample. Missing startup times are never zero-filled. A truncated answer gets a separate zero capability score; inference completion and capability correctness are separate dimensions.

RAM RSS/CPU sample about four times a second. Optional Windows GPU counter queries can take several seconds. Dedicated process memory is reported as sampled VRAM peak; shared bytes remain in raw telemetry. GPU percentage is the maximum observed per-engine value for this PID, not whole-device or summed multi-engine utilisation. Absent counters remain null. Sparse sampling can miss peaks and query overhead can affect measurements; its setting is part of comparison identity. Log-derived Vulkan allocations are separate. Keep other heavy workloads idle for comparisons; the app does not control production workloads to enforce isolation.

## Capability

Agent core v1 has 31 original synthetic tasks: instructions/constraints, strict structured/schema output, extraction, grounding, reasoning, coding/debugging, tool selection/formatting/restraint, planning, uncertainty, hallucination resistance, recovery and context retrieval. Native tool calls are validated, never executed. Strict JSON grades the entire final response and rejects fences/prose, duplicate keys, NaN/Infinity, incorrect types and extra keys. Raw reasoning is separate and never substituted for the answer.

Small pure-function coding cases run in a bounded AST interpreter: plain functions, assignment/arithmetic/conditions/for loops, limited builtins and list append/set add. Imports, arbitrary attributes, IO, eval/exec and unsupported syntax fail. Operation, container, integer and call-depth budgets prevent runaway evaluation. This measures a defined Python subset, not arbitrary coding ability. Unit-case partial credit is inspectable. No LLM judge or model-code host subprocess is used.

Base tasks use the chosen profile context, repeated at least three times. Long-context cases run at each requested context/depth and cover exact retrieval, retrieval plus arithmetic, distant-fact combination, earlier-instruction retention and conflicting distractors. Filler/facts are deterministic and seeded. The tested model's template/tokenizer measure actual input length/depth. Requested targets and measured values are both stored; generation/template space is reserved rather than overflowing/shifting context. Failed context loads contribute zero for all scheduled capability samples there.

Category scores average task/repeat grades. Optional overall capability is sample-weighted, so changing the context matrix changes weighting. It is never multiplied by speed into a composite rank. Compare matching selections and inspect categories. The small public suite is learnable and cannot guarantee production agent behaviour. Later qualification requires separate sterile tool/workspace stages.

## Versions

Definitions, scorer/interpreter, generator, performance workload and reused graders have fixed hashes in `versions.lock.json`. Modified files fail validation. Do not rewrite the lock to hide changes: publish a new version with preserved old implementations. Artifacts snapshot exact sources/hashes; harness changes have a separate comparison hash. Driver/build/seed changes are not assumed bit reproducible.
