from __future__ import annotations

from pathlib import Path

from .util import file_hash, read_json

ROOT = Path(__file__).parent


CURRENT_BENCHMARK = "agent-core-v1.1"


def load_suite(version=CURRENT_BENCHMARK):
    lock = read_json(ROOT / "benchmarks" / "versions.lock.json")
    for relative, expected in lock[version]["files"].items():
        if file_hash(ROOT / relative) != expected:
            raise ValueError(
                f"Immutable benchmark version changed: {relative}. Publish a new version; do not rewrite {version}"
            )
    suite = read_json(ROOT / "benchmarks" / f"{version}.json")
    return suite, lock[version]
