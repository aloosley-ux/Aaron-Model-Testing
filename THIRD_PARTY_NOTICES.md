# Third-party notices

The following MIT source is substantially reused. Full upstream copyright, permission and warranty notices are retained in `licenses/` and must accompany redistribution. Vendored files are marked; project adapters live outside `vendor/`.

| Exact revision inspected | Reused implementation | Local component / adaptations |
| --- | --- | --- |
| [ianzepp/llama-gguf-tune](https://github.com/ianzepp/llama-gguf-tune/tree/70ed9fd049853f373f35a625263a4e4ac7489255) | `src/llama_gguf_tune/candidates.py`: candidate model, preset matrices, deduplication, nearest-neighbour drill | `vendor/tune_candidates.py` is the complete source plus a provenance comment. `tuning.py` composes it with bounded diverse ordering, GPU/context dimensions and stable repeated selection. `runtime.py` translates current Windows load-mode flags. |
| [SupermodularAI/local_bench](https://github.com/SupermodularAI/local_bench/tree/df78acaa7342b7c56069ef050cedb7815b98840c) | `src/local_bench/quality/graders.py`: Grade/Grader, deterministic numeric/regex/JSON checks and composition | `vendor/graders.py` is the complete source plus a provenance comment. `scoring.py` uses Grade, numeric/regex implementations and adds strict whole-response JSON/schema, native tool checks and bounded unit cases. Permissive upstream JSON extraction is retained but not used for strict compliance. V1 prompts are original synthetic tasks. |
| [Happynood/llm-inference-benchmark](https://github.com/Happynood/llm-inference-benchmark/tree/e5a40d1e35b943b0f8470429a6d216e2c79f1319) | `src/llm_inference_benchmark/task_quality.py`: deterministic required/forbidden/regex text rubrics | `vendor/task_quality.py` is the complete source plus a provenance comment, used by the rubric scorer. Its history/manifests, TTFT and repeats also informed the architecture; Windows process ownership and artifact indexing are project-specific. |

Retained notices:

- **Copyright (c) 2026 Ian Zepp** — [llama-gguf-tune MIT licence](licenses/llama-gguf-tune-MIT.txt).
- **Copyright (c) 2026 Supermodular AI** and **Copyright (c) 2026 aiwinsyou@gmail.com (original "homebench" project)** — [local_bench MIT licence](licenses/local_bench-MIT.txt).
- **Copyright (c) 2026 Alexey** — [llm-inference-benchmark MIT licence](licenses/llm-inference-benchmark-MIT.txt).

The linked full permission/warranty texts are part of these notices. Preserve those files when distributing this project.

[kylebakerio/LLM-Tuner](https://github.com/kylebakerio/LLM-Tuner/tree/05a0fb18c70017047eedd859ba7196e372751b5a) (no licence found at inspection) and [7amzaRando/BenchMax](https://github.com/7amzaRando/BenchMax/tree/3dd34db201b4defae6cd6b269891bf186ffa822d) (AGPLv3) were read for ideas only. **No source, prompts, assets or datasets from either were copied.**

Dependencies retain their package licences. The official llama.cpp `gguf` package is installed for metadata reading. Native binaries and weights are user supplied, not redistributed.
