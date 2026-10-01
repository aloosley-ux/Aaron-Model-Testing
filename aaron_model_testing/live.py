"""Bounded monitor snapshots from durable samples and the existing telemetry sampler."""

from __future__ import annotations

from datetime import datetime, timezone

from .aggregation import aggregate
from .performance import distribution

EVENT_LIMIT = 30
ROLLING_SAMPLES = 12
SAMPLE_TYPES = {"performance", "capability", "tuning_performance"}


def activity(sample):
    kind = sample.get("type")
    if kind == "lifecycle":
        outcome, test = "LOAD", "context loaded / released"
    elif kind in SAMPLE_TYPES:
        outcome = (
            "ERROR"
            if not sample.get("success")
            else "UNAVAILABLE"
            if sample.get("grade", {}).get("valid") is False
            else "FAIL"
            if sample.get("grade", {}).get("passed") is False
            else "PASS"
        )
        test = sample.get("test_id") or kind.replace("_", " ")
    else:
        return None
    return {
        "timestamp": sample["timestamp"],
        "outcome": outcome,
        "test": test,
        "context": sample.get("context_size"),
        "repeat": sample["repeat"] + 1 if "repeat" in sample else None,
    }


def snapshot(record, records, resources=None):
    samples = [r for r in records if r.get("type") in SAMPLE_TYPES]
    caps = [r for r in samples if r.get("type") == "capability"]
    summary = aggregate([r for r in samples if r.get("type") != "tuning_performance"])
    elapsed = max(
        0, (datetime.now(timezone.utc) - datetime.fromisoformat(record["created_at"])).total_seconds()
    )
    if record.get("finished_at"):
        elapsed = max(
            0,
            (
                datetime.fromisoformat(record["finished_at"]) - datetime.fromisoformat(record["created_at"])
            ).total_seconds(),
        )
    planned = record.get("planned_samples")
    completed = len(samples)
    active = record["status"] in ("running", "queued")
    metrics = [r.get("metrics", {}) for r in samples if r.get("success")][-ROLLING_SAMPLES:]
    return {
        **record.get("live", {}),
        "status": record["status"],
        "completed_samples": completed,
        "planned_samples": planned,
        "progress_fraction": min(1, completed / planned) if planned else None,
        "elapsed_seconds": elapsed,
        "eta_seconds": elapsed / completed * max(0, planned - completed)
        if active and completed and planned
        else None,
        "pass_count": sum(r.get("success") and r.get("grade", {}).get("passed") is True for r in caps),
        "fail_count": sum(r.get("success") and r.get("grade", {}).get("passed") is False for r in caps),
        "error_count": sum(not r.get("success") for r in samples),
        "invalid_grades": summary["invalid_grades"],
        "capability": summary["capability"],
        "capability_status": summary["capability_status"],
        "capability_samples": len(caps),
        "reliability": sum(bool(r.get("success")) for r in samples) / completed if completed else None,
        "generation_tps": distribution([m.get("generation_tps") for m in metrics])["median"],
        "prompt_tps": distribution([m.get("prompt_tps") for m in metrics])["median"],
        "rolling_samples": len(metrics),
        "resources": resources or {},
    }
