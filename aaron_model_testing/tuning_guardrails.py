"""Unscored tuning-only v1 tasks. Never used in qualification or capability ranks."""

from __future__ import annotations

from .util import digest

GUARDRAIL_VERSION = "unscored-tuning-v1"

# Deliberately separate definitions, IDs, prompts and expected answers from benchmarks/.
BALANCED_TASKS = [
    {
        "id": "tune-word",
        "prompt": "For this unscored tuning check, return only the lowercase word willow.",
        "rule": {"type": "exact", "expected": "willow"},
    },
    {
        "id": "tune-parse",
        "prompt": 'Unscored tuning check. Station Larch has platform 7. Return only JSON with keys "station" (string) and "platform" (integer).',
        "rule": {
            "type": "json",
            "schema": {
                "type": "object",
                "properties": {"station": {"type": "string"}, "platform": {"type": "integer"}},
                "required": ["station", "platform"],
                "additionalProperties": False,
            },
            "expected": {"station": "Larch", "platform": 7},
        },
    },
]
SMART_TASKS = BALANCED_TASKS + [
    {
        "id": "tune-reason",
        "prompt": "Unscored tuning check. A depot has 13 crates, receives twice that many, then ships 8. Each remaining crate holds 3 jars. Return only the number of jars remaining.",
        "rule": {"type": "exact", "expected": "93"},
    },
    {
        "id": "tune-constraints",
        "prompt": "Unscored tuning check. Mira finishes before Oren. Pavo finishes after Oren. Neri finishes before Mira. Return only the four names in finishing order separated by commas, with no spaces.",
        "rule": {"type": "exact", "expected": "Neri,Mira,Oren,Pavo"},
    },
]


def tasks_for(objective):
    return [] if objective == "FAST" else SMART_TASKS if objective == "SMART" else BALANCED_TASKS


def verify_separation(suite):
    """Refuse accidental prompt/ID reuse before launching any optimisation."""
    ids = {t["id"] for t in suite["tests"]}
    prompts = {digest(t["prompt"]) for t in suite["tests"]}
    for task in SMART_TASKS:
        if task["id"] in ids or digest(task["prompt"]) in prompts:
            raise ValueError("Unscored tuning task overlaps scored qualification evidence")
