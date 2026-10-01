"""MIT llama-gguf-tune candidate matrix + drill, adapted for Windows Vulkan and bounded staged search."""

from __future__ import annotations

import os

from .profiles import RuntimeConfig
from .vendor.tune_candidates import Candidate, build_candidates, drill_candidates


def candidates(base: RuntimeConfig, preset: str, limit: int, blocks: int = 32):
    cpus = os.cpu_count() or 8
    original = Candidate(**{k: base.model_dump()[k] for k in Candidate.__dataclass_fields__})
    source = (
        drill_candidates(original, cpus, limit=1000)
        if preset == "drill"
        else build_candidates(cpus, preset=preset)
    )
    output, seen = [], set()

    def add(changes):
        # Context remains fixed within a sweep: lowering context must not win by changing the workload.
        changes["ctx_size"] = base.ctx_size
        value = RuntimeConfig.model_validate({**base.model_dump(), **changes})
        key = value.model_dump_json()
        if key not in seen:
            seen.add(key)
            output.append(value)

    add({})
    # Diverse early candidates: avoid prefix truncation of a huge cartesian product.
    axes = [
        {"flash_attn": not base.flash_attn},
        {"batch_size": 1024, "ubatch_size": 256},
        {"gpu_layers": max(1, blocks // 2)},
        {"threads": max(1, cpus // 3), "batch_threads": max(1, cpus // 3)},
        {"gpu_layers": max(1, blocks * 3 // 4)},
        {"gpu_layers": 0},
        {"cache_type_k": "q8_0", "cache_type_v": "q8_0"},
        {"mmap": not base.mmap},
        {"batch_size": 2048, "ubatch_size": 512},
        {"threads": cpus, "batch_threads": cpus},
        {"gpu_layers": max(1, blocks // 4)},
        {"batch_size": 256, "ubatch_size": 64},
        {"cache_type_k": "q4_0", "cache_type_v": "q4_0"},
    ]
    if preset == "drill":
        axes = [{"gpu_layers": max(0, min(999, base.gpu_layers + offset))} for offset in (-4, 4)] + axes
    for changes in axes[: 6 if preset == "quick" else len(axes)]:
        add(changes)
    # Breadth from the upstream matrix, deterministically interleaved across its range.
    if source:
        stride = max(1, len(source) // max(1, limit - len(output)))
        for candidate in source[::stride] + source:
            add(candidate.as_dict())
            if len(output) >= limit:
                break
    return output[:limit]


def objective(summary: dict, name: str):
    metrics = summary["metrics"]
    if summary["reliability"] != 1 or summary["attempts"] < 3:
        return None
    gen = metrics["generation_tps"]["median"]
    prompt = metrics["prompt_tps"]["median"]
    if not gen or not prompt:
        return None
    # FAST favours decoding. BALANCED/SMART favour fixed-workload time with different context goals supplied by user.
    return gen if name == "FAST" else 1 / (256 / prompt + 128 / gen)
