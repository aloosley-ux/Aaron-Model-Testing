"""Reasoning-aware grade validity plus the frozen v1 aggregation methodology."""

from __future__ import annotations

from .performance import distribution, summarize


def aggregate(records):
    caps = [r for r in records if r.get("type") == "capability"]
    invalid = [
        r for r in caps if r.get("grade", {}).get("valid") is False or r.get("grade", {}).get("score") is None
    ]
    # Frozen v1 aggregation expects numeric grades. Never expose its placeholders as scores.
    safe = [{**r, "grade": {**r.get("grade", {}), "score": 0}} if r in invalid else r for r in records]
    result = summarize(safe)
    result["invalid_grades"] = len(invalid)
    result["capability_status"] = "invalid" if invalid else "valid" if caps else "pending"
    if invalid:
        result["capability"] = None
        result["capability_warning"] = (
            "Final-answer extraction/grading unavailable for one or more samples; inspect responses"
        )
        categories = {r["category"] for r in invalid}
        for category in categories:
            result["categories"][category]["score"] = None
    life = [r for r in records if r.get("type") == "lifecycle"]
    result["metrics"]["load_ms"] = distribution([r.get("load_ms") for r in life])
    result["resources"] = {
        key: distribution([r.get("resources", {}).get(key) for r in life])
        for key in ("ram_peak_mb", "vram_peak_mb", "cpu_mean_percent", "gpu_utilisation_percent")
    }
    return result
