"""MIT llama-gguf-tune candidate matrix + drill, adapted for Windows Vulkan and bounded staged search."""

from __future__ import annotations

import os

from .profiles import RuntimeConfig
from .tuning_guardrails import GUARDRAIL_VERSION
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


OPTIMISER_VERSION = "capability-guarded-tuning-v1"


def objective_components(summary, name, guardrail, baseline, context):
    runtime = objective(summary, name)
    coverage = guardrail.get("complete", False)
    baseline_available = baseline.get("complete", False)
    score = guardrail.get("score")
    baseline_score = baseline.get("score")
    # No aggregate-score tolerance hides a lost task: every baseline pass must
    # still pass the same deterministic repeat under BALANCED and SMART.
    regressions = sorted(set(baseline.get("passed_checks", [])) - set(guardrail.get("passed_checks", [])))
    eligible = runtime is not None and (name == "FAST" or coverage and baseline_available and not regressions)
    return {
        "version": OPTIMISER_VERSION,
        "objective": name,
        "runtime_score": runtime,
        "guardrail_version": GUARDRAIL_VERSION if name != "FAST" else None,
        "guardrail_score": score,
        "baseline_guardrail_score": baseline_score,
        "guardrail_complete": coverage if name != "FAST" else None,
        "regressed_checks": regressions,
        "tested_context": context,
        "eligible": eligible,
        "rejection_reason": "unstable_or_missing_performance"
        if runtime is None
        else "baseline_guardrail_unavailable"
        if name != "FAST" and not baseline_available
        else "incomplete_guardrail"
        if name != "FAST" and not coverage
        else "capability_guardrail_regression"
        if regressions and name != "FAST"
        else None,
    }


def selection_key(components):
    if not components["eligible"]:
        return None
    runtime = components["runtime_score"]
    if components["objective"] == "SMART":
        return (components["guardrail_score"], components["tested_context"], runtime)
    return (runtime,)


def config_deltas(baseline, winner):
    effects = {
        "ctx_size": "context handling",
        "sampling": "sampling/reasoning behaviour",
        "template": "sampling/reasoning behaviour",
        "options": "model-specific runtime/context/reasoning behaviour",
        "cache_type_k": "resource use; numerical precision can affect answers",
        "cache_type_v": "resource use; numerical precision can affect answers",
    }
    return {
        key: {
            "baseline": baseline.get(key),
            "winner": value,
            "effect": effects.get(key, "runtime speed/resource use"),
        }
        for key, value in winner.items()
        if baseline.get(key) != value
    }
