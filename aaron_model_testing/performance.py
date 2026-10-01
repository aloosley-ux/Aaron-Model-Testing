"""Version 1 unscored, deterministic performance workloads, held separate from capability tests."""

from __future__ import annotations

import math
import statistics

from .util import digest


def distribution(values):
    values = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return {
        "n": len(values),
        "median": statistics.median(values) if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "variance": statistics.variance(values) if len(values) > 1 else None,
        "stddev": statistics.stdev(values) if len(values) > 1 else None,
    }


def workload(server, input_tokens, output_tokens, repeat):
    # Tokenise controlled text once, then send exact token ids. No estimated chars/token.
    text = f"Unscored workload version 1, repetition {repeat}.\n" + (
        "A quiet observatory records ordinary weather and writes a detailed daily report. "
        * (input_tokens + 1)
    )
    tokens = server.tokenize(text)[:input_tokens]
    if len(tokens) != input_tokens:
        raise ValueError("Unable to build exact-length input")
    result = server.request(
        {
            "prompt": tokens,
            "n_predict": output_tokens,
            "ignore_eos": True,
            "temperature": 0,
            "seed": 42,
            "top_k": 0,
            "top_p": 1,
            "min_p": 0,
        },
        chat=False,
    )
    metrics = result.get("metrics", {})
    result["success"] = bool(
        result["success"]
        and metrics.get("output_tokens") == output_tokens
        and metrics.get("generation_tps")
        and metrics.get("prompt_tps")
        and metrics.get("input_tokens") == input_tokens
    )
    if not result["success"] and not result.get("error"):
        result["error"] = "Incomplete generation, missing timings, or prompt token reuse; sample rejected"
    result.update(
        {
            "type": "performance",
            "input_tokens_target": input_tokens,
            "output_tokens_target": output_tokens,
            "repeat": repeat,
            "prompt_sha256": digest(tokens),
            "workload_version": "performance-v1",
        }
    )
    return result


def summarize(records):
    perf = [r for r in records if r.get("type") == "performance"]
    cap = [r for r in records if r.get("type") == "capability"]
    metrics = {}
    for key in (
        "generation_tps",
        "prompt_tps",
        "ttft_ms",
        "ttfa_ms",
        "latency_ms",
        "input_tokens",
        "output_tokens",
    ):
        metrics[key] = distribution([r.get("metrics", {}).get(key) for r in perf if r.get("success")])
    curves = {}
    for r in perf:
        context = str(r.get("context_size"))
        curves.setdefault(context, []).append(r)
    contexts = {
        context: {
            key: distribution([r.get("metrics", {}).get(key) for r in items if r.get("success")])
            for key in ("generation_tps", "prompt_tps", "ttft_ms", "latency_ms")
        }
        for context, items in curves.items()
    }
    categories = {}
    for r in cap:
        categories.setdefault(r["category"], []).append(r.get("grade", {}).get("score", 0))
    scored = [r.get("grade", {}).get("score", 0) for r in cap]
    attempts = [r for r in records if r.get("type") in ("performance", "capability")]
    return {
        "metrics": metrics,
        "contexts": contexts,
        "categories": {k: {"score": statistics.mean(v), "n": len(v)} for k, v in categories.items()},
        "capability": statistics.mean(scored) if scored else None,
        "capability_samples": len(cap),
        "attempts": len(attempts),
        "reliability": sum(bool(r.get("success")) for r in attempts) / len(attempts) if attempts else None,
        "errors": sum(not r.get("success") for r in attempts),
    }
