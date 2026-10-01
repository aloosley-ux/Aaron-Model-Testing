"""Versioned diagnostics around immutable scoring; never estimate missing native tokens."""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

from jsonschema import Draft202012Validator

from .aggregation import aggregate
from .performance import distribution
from .scoring import strict_json

EVIDENCE_VERSION = "benchmark-evidence-v1"
SAMPLE_TYPES = {"capability", "performance", "tuning_performance", "tuning_guardrail"}


def number(value):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        else None
    )


def first_number(*values):
    return next((number(v) for v in values if number(v) is not None), None)


def native_metrics(usage, timings):
    details = usage.get("completion_tokens_details") or {}
    # A separate final-answer count must be reported explicitly. Subtracting reasoning
    # from completion counts can include tool/control tokens and is not a native split.
    return {
        "input_tokens": first_number(usage.get("prompt_tokens"), timings.get("prompt_n")),
        "output_tokens": first_number(usage.get("completion_tokens"), timings.get("predicted_n")),
        "reasoning_tokens": first_number(details.get("reasoning_tokens")),
        "final_answer_tokens": first_number(details.get("final_answer_tokens")),
        "prompt_duration_ms": number(timings.get("prompt_ms")),
        "generation_duration_ms": number(timings.get("predicted_ms")),
        "inference_duration_ms": (
            timings["prompt_ms"] + timings["predicted_ms"]
            if number(timings.get("prompt_ms")) is not None
            and number(timings.get("predicted_ms")) is not None
            else None
        ),
    }


def failure_reason(sample):
    grade = sample.get("grade", {})
    if sample.get("finish_reason") == "length":
        return "token_budget_truncation"
    if not sample.get("success"):
        return sample.get("error_kind") or "inference_error"
    if grade.get("valid") is False or grade.get("score") is None:
        return "unavailable_grade"
    if grade.get("passed"):
        return None
    rule = sample.get("test", {}).get("rule", {})
    kind = rule.get("type")
    if rule and kind not in ("exact", "number", "regex", "rubric", "json", "tool", "restraint", "code"):
        return "parser_or_harness_error"
    answer = sample.get("final_answer", sample.get("response", "")) or ""
    if kind == "json":
        try:
            value = strict_json(answer.strip())
        except (ValueError, TypeError):
            return "malformed_structured_output"
        if list(Draft202012Validator(rule["schema"]).iter_errors(value)):
            return "schema_failure"
    if kind == "tool":
        calls = sample.get("tool_calls") or []
        if len(calls) != 1:
            return "tool_selection_failure"
        try:
            call = calls[0]["function"]
            value = strict_json(call["arguments"])
            name = call["name"]
        except (ValueError, TypeError, KeyError):
            return "malformed_tool_call"
        if name != rule["name"]:
            return "tool_selection_failure"
        if list(Draft202012Validator(rule["schema"]).iter_errors(value)):
            return "schema_failure"
    if kind == "restraint" and sample.get("tool_calls"):
        return "tool_selection_failure"
    if sample.get("category", "").startswith("extraction"):
        return "extraction_mismatch"
    return "wrong_answer"


def diagnose(sample):
    """Read-only derivation. Raw streams, responses and original grades are untouched."""
    metrics = {
        **native_metrics(sample.get("usage") or {}, sample.get("native_timings") or {}),
        **sample.get("metrics", {}),
    }
    # Legacy failed requests kept latency/TTFT at the top level.
    duration = first_number(
        sample.get("sample_duration_ms"), metrics.get("latency_ms"), sample.get("latency_ms")
    )
    embedded = sample.get("response", "").lstrip().startswith("<think>")
    tokens = {
        key: number(metrics.get(key))
        for key in ("input_tokens", "output_tokens", "reasoning_tokens", "final_answer_tokens")
    }
    return {
        "version": EVIDENCE_VERSION,
        **tokens,
        "sample_duration_ms": duration,
        "request_duration_ms": first_number(metrics.get("latency_ms"), sample.get("latency_ms")),
        "ttft_ms": first_number(metrics.get("ttft_ms"), sample.get("ttft_ms")),
        "ttfa_ms": None if embedded else number(metrics.get("ttfa_ms")),
        "ttfa_status": "unavailable_embedded_reasoning"
        if embedded
        else "native_stream"
        if number(metrics.get("ttfa_ms")) is not None
        else "unavailable",
        **{
            k: number(metrics.get(k))
            for k in ("prompt_duration_ms", "generation_duration_ms", "inference_duration_ms")
        },
        "finish_reason": sample.get("finish_reason"),
        "truncated": sample.get("finish_reason") == "length"
        if sample.get("finish_reason") is not None
        else None,
        "failure_reason": failure_reason(sample)
        if sample.get("type") == "capability"
        else sample.get("error_kind"),
        "grader_outcome": "unavailable"
        if sample.get("grade", {}).get("valid") is False
        else "pass"
        if sample.get("grade", {}).get("passed")
        else "fail",
        "executed": sample.get("executed", True),
        "token_source": sample.get("input_token_source", "native_usage_or_timing")
        if tokens["input_tokens"] is not None
        else "unavailable",
    }


def percentile_distribution(values):
    values = sorted(number(v) for v in values if number(v) is not None)
    result = distribution(values)
    # Nearest-rank p95, explicit and stable even for small sample sets.
    result["p95"] = values[math.ceil(0.95 * len(values)) - 1] if values else None
    return result


def seconds_between(start, end):
    try:
        a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
        if a.tzinfo is None or b.tzinfo is None:
            return None
        return number((b - a).total_seconds())
    except (ValueError, TypeError):
        return None


def timing_view(record):
    if record.get("regrade"):
        return record.get("timing") or {
            "version": EVIDENCE_VERSION,
            "source": "inference_timestamps",
            "active_seconds": seconds_between(
                record["regrade"].get("inference_created_at"), record["regrade"].get("inference_finished_at")
            ),
            "queue_wait_seconds": None,
            "total_elapsed_seconds": None,
            "phases": {},
        }
    return record.get("timing") or {
        "version": EVIDENCE_VERSION,
        "source": "timestamps",
        "queue_wait_seconds": seconds_between(record.get("queued_at"), record.get("started_at")),
        "active_seconds": seconds_between(
            record.get("started_at") or record.get("created_at"), record.get("finished_at")
        ),
        "total_elapsed_seconds": seconds_between(
            record.get("queued_at") or record.get("created_at"), record.get("finished_at")
        ),
        "phases": {},
    }


def eligible(record):
    return (
        record.get("status") == "completed" and not record.get("smoke") and record.get("stage") != "optimise"
    )


def enrich_summary(summary, records, record):
    caps = [r for r in records if r.get("type") == "capability"]
    samples = [r for r in records if r.get("type") in SAMPLE_TYPES]
    evidence = [r.get("diagnostics") or diagnose(r) for r in samples]
    cap_evidence = [r.get("diagnostics") or diagnose(r) for r in caps]
    tokens = {}
    for key in ("input_tokens", "output_tokens", "reasoning_tokens", "final_answer_tokens"):
        values = [e[key] for e in evidence if e.get(key) is not None]
        tokens[key] = {
            "total": sum(values) if values else None,
            "observed_samples": len(values),
            "samples": len(samples),
            "complete": bool(samples) and len(values) == len(samples),
        }
    correct = sum(
        r.get("success")
        and not r.get("legacy_grading_warning")
        and r.get("grade", {}).get("valid", True)
        and r.get("grade", {}).get("passed") is True
        for r in caps
    )
    cap_output = [e["output_tokens"] for e in cap_evidence if e.get("output_tokens") is not None]
    active = timing_view(record).get("active_seconds")

    def rate(count):
        return count * 60 / active if active and count is not None else None

    executed = sum(e["executed"] for e in evidence)
    cap_executed = sum(e["executed"] for e in cap_evidence)
    output_total = tokens["output_tokens"]["total"] if tokens["output_tokens"]["complete"] else None
    result = {
        **summary,
        "evidence_version": EVIDENCE_VERSION,
        "partial": record.get("status") != "completed",
        "qualification_eligible": eligible(record),
        "tokens": tokens,
        "capability_response_tokens": percentile_distribution(cap_output),
        "capability_sample_duration_ms": percentile_distribution(
            [e["sample_duration_ms"] for e in cap_evidence]
        ),
        "failure_reasons": dict(
            Counter(e["failure_reason"] for e in cap_evidence if e.get("failure_reason"))
        ),
        "efficiency": {
            "denominator": "active_run_seconds_including_setup",
            "samples_per_minute": rate(executed),
            "capability_samples_per_minute": rate(cap_executed),
            "correct_capability_samples_per_minute": rate(correct) if caps else None,
            "correct_capability_samples": correct,
            "output_tokens_per_minute": rate(output_total),
            "output_tokens_per_correct_answer": sum(cap_output) / correct
            if correct and len(cap_output) == len(caps)
            else None,
        },
    }
    return result


def summarize_evidence(records, record):
    return enrich_summary(aggregate(records), records, record)


def present_record(record):
    """Backward reads never write migrations into historical artifacts."""
    timing = timing_view(record)
    if record.get("status") == "interrupted" and timing.get("source") == "monotonic":
        timing = {**timing, "interrupted_lower_bound": True}
    summary = {
        **record.get("summary", {}),
        "partial": record.get("status") != "completed",
        "qualification_eligible": eligible(record),
    }
    if "efficiency" not in summary:
        active = timing.get("active_seconds")
        passed = record.get("live", {}).get("pass_count")
        summary["efficiency"] = {
            "denominator": "timestamp_derived_active_seconds",
            "samples_per_minute": summary.get("attempts", 0) * 60 / active if active else None,
            "capability_samples_per_minute": summary.get("capability_samples", 0) * 60 / active
            if active
            else None,
            "correct_capability_samples_per_minute": passed * 60 / active
            if active and passed is not None
            else None,
        }
    return {**record, "timing": timing, "summary": summary, "qualification_eligible": eligible(record)}
