# Research and reuse

Source checkouts were inspected before implementation on 1 October 2026. Exact revisions/notices are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Reference trees are ignored locally, not shipped wholesale.

| Project | Source studied | Product decision |
| --- | --- | --- |
| Happynood/llm-inference-benchmark, MIT | FastAPI/history schema, manifests, streaming TTFT/repeat aggregation, Pareto comparisons, deterministic rubrics, UI/API | Reused complete text-rubric module; adopted separate capability/speed axes, raw trials and hash provenance. Replaced Python-binding/backend and NVIDIA collectors with native Windows ownership/telemetry. No torch/CUDA/vLLM stack installed. |
| ianzepp/llama-gguf-tune, MIT | Candidate dataclass/preset matrix, deduplication, nearest-neighbour drill, native bench JSON, server health loop, metadata/winners | Directly vendored/composed matrix/drill code. Added diverse bounded selection, GPU/context axes, profiles, median/all-repeat stability and deadlines. Translated newer Windows load-mode flags; replaced free-port/process cleanup assumptions. |
| SupermodularAI/local_bench, MIT | Quality tasks/graders, streamed OpenAI provider, reasoning separation, token budgets, throughput integrity, history/diff | Vendored graders/Grade model. Original agent tasks add strict schema/tool grading; lenient extraction would reward invalid compliance here. Kept reasoning separate, no judge, durable histories. |
| kylebakerio/LLM-Tuner, no licence found | Dashboard/runtime command concept, native monitor, benchmark/depth workflow | Ideas only: exact commands, per-model settings and context-depth inspection. No code/assets/datasets copied, no PM2/RPC orchestration. |
| 7amzaRando/BenchMax, AGPLv3 | README, backend lifecycle/queue, needle retrieval and long-context memory source | Ideas only: explicit lifecycle and broader context retention. No implementation/tests/prompts/corpus/UI copied. Original seeded synthetic corpus measures token depths rather than character estimates. |

This product composes reusable MIT code with machine-specific adapters. It uses the official GGUF reader rather than reimplementing a binary format, and the exact user's native server build rather than introducing a separate Python-binding build. Static SVG charts avoid frontend production infrastructure. Benchmark definitions and future integration boundaries are project-specific.
