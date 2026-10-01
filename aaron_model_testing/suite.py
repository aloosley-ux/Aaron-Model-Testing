from __future__ import annotations

from pathlib import Path

from .util import file_hash, read_json

ROOT = Path(__file__).parent


def load_suite():
    lock = read_json(ROOT / "benchmarks" / "versions.lock.json")
    for relative, expected in lock["agent-core-v1"]["files"].items():
        if file_hash(ROOT / relative) != expected:
            raise ValueError(
                f"Immutable benchmark version changed: {relative}. Publish a new version; do not rewrite v1"
            )
    suite = read_json(ROOT / "benchmarks" / "agent-core-v1.json")
    return suite, lock["agent-core-v1"]
