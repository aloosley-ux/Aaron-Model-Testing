from __future__ import annotations

import argparse
import json

from .config import data_home
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Aaron Model Testing — local Windows Vulkan benchmarks")
    parser.add_argument(
        "command", choices=["serve", "reindex", "verify", "regrade"], nargs="?", default="serve"
    )
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        from .app import create_app

        print("Aaron Model Testing: http://127.0.0.1:4321 — Ctrl+C shuts down owned benchmarks")
        uvicorn.run(create_app(), host="127.0.0.1", port=4321, workers=1, timeout_graceful_shutdown=20)
    elif args.command == "reindex":
        from .app import HomeLock

        lock = HomeLock(data_home())
        try:
            print(json.dumps(Store(data_home()).reindex(), indent=2))
        finally:
            lock.close()
    elif args.command == "regrade":
        from .regrade import regrade

        if not args.path:
            parser.error("regrade requires a source run ID")
        result = regrade(Store(data_home()), args.path)
        print(
            json.dumps(
                {
                    "id": result["id"],
                    "source_run_id": args.path,
                    "grader_version": result["grader_version"],
                    "capability": result["summary"]["capability"],
                    "capability_samples": result["summary"]["capability_samples"],
                    "reliability": result["summary"]["reliability"],
                    "errors": result["summary"]["errors"],
                    "changed_grades": result["regrade"]["changed_grades"],
                },
                indent=2,
            )
        )
    else:
        from pathlib import Path

        from .util import file_hash, read_json

        if not args.path:
            parser.error("verify requires a run artifact directory")
        path = Path(args.path).resolve()
        hashes = read_json(path / "checksums.json")
        failures = []
        for relative, expected in hashes.items():
            item = (path / relative).resolve()
            if not item.is_relative_to(path) or not item.is_file() or file_hash(item) != expected:
                failures.append(relative)
        print(json.dumps({"verified_files": len(hashes), "failures": failures}, indent=2))
        if failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
