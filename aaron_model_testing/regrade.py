"""Regrade verified terminal evidence into a new artifact; never rerun inference."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .grading import GRADER_VERSION, grade_result
from .pipeline import ArtifactRun
from .suite import ROOT, load_suite
from .util import digest, distribution_notices, file_hash, now, read_json, write_json


def verify_evidence(path: Path) -> dict:
    hashes = read_json(path / "checksums.json")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("Missing source evidence checksums")
    for relative, expected in hashes.items():
        item = (path / relative).resolve()
        if not item.is_relative_to(path.resolve()) or not item.is_file() or file_hash(item) != expected:
            raise ValueError(f"Source evidence checksum mismatch: {relative}")
    actual = {
        p.relative_to(path).as_posix()
        for p in path.rglob("*")
        if p.is_file() and p != path / "checksums.json"
    }
    if actual != set(hashes):
        raise ValueError("Source evidence inventory differs from checksums")
    return hashes


def regrade(store, run_id: str) -> dict:
    # Resolve through the index; IDs never become arbitrary input paths.
    indexed = store.get("runs", run_id)
    if indexed is None:
        raise ValueError("Source run not found")
    if indexed.get("status") not in ("completed", "partial"):
        raise ValueError("Regrade requires a completed or partial source run")
    source = (store.home / "artifacts" / indexed["id"]).resolve()
    if source.parent != (store.home / "artifacts").resolve():
        raise ValueError("Invalid source run path")
    hashes = verify_evidence(source)
    original = read_json(source / "manifest.json")
    if original["id"] != run_id or original["status"] not in ("completed", "partial"):
        raise ValueError("Regrade requires completed or partial, checksummed evidence")
    source_suite, source_lock = load_suite(original["benchmark"]["id"])
    if original["benchmark"]["lock"] != source_lock:
        raise ValueError("Source benchmark lock is not a recognised frozen version")
    for relative, expected in source_lock["files"].items():
        if hashes.get("benchmark_sources/" + relative) != expected:
            raise ValueError(f"Source frozen benchmark mismatch: {relative}")
    suite, lock = load_suite()

    def definitions(s):
        return {k: v for k, v in s.items() if k not in ("id", "version")}

    if (
        definitions(source_suite) != definitions(suite)
        or read_json(source / "benchmark.json") != source_suite
    ):
        raise ValueError("Benchmark definitions differ; cannot regrade with this version")
    records = []
    with (source / "records.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            records.append(json.loads(line))  # Refuse incomplete records.
    if len(records) != original["sample_count"] or len({r["id"] for r in records}) != len(records):
        raise ValueError("Source sample inventory mismatch")
    base_tests = {t["id"]: t for t in source_suite["tests"]}
    changed = 0
    output = []
    for sample in records:
        derived = dict(sample)
        if sample.get("type") == "capability":
            case = sample.get("test")
            if case:
                if digest(case) != sample.get("test_sha256") or digest(case["messages"]) != sample.get(
                    "prompt_sha256"
                ):
                    raise ValueError(f"Source test/prompt identity mismatch: {sample['id']}")
                if sample["test_id"] in base_tests:
                    if any(case.get(k) != v for k, v in base_tests[sample["test_id"]].items()):
                        raise ValueError("Source standard test differs from frozen definition")
                elif not sample["test_id"].startswith("long-"):
                    raise ValueError("Unrecognised source test")
                derived.update(grade_result(sample, case["rule"]))
            elif sample.get("success"):
                raise ValueError("Successful capability sample has no preserved grading rule")
            else:
                derived["grade"] = {
                    "score": 0,
                    "passed": False,
                    "valid": True,
                    "version": GRADER_VERSION,
                    "detail": sample.get("error") or "Not executed",
                }
            derived["previous_grade"] = sample.get("grade")
            derived["previous_reasoning"] = sample.get("reasoning")
            changed += derived["grade"].get("score") != sample.get("grade", {}).get("score")
        output.append(derived)
    if not any(r.get("type") == "capability" for r in output):
        raise ValueError("Source run has no capability samples to regrade")
    # Source is checked again before writing a unique derived artifact. No source/index row is updated.
    if verify_evidence(source) != hashes:
        raise ValueError("Source evidence changed during regrade")
    record = {
        **original,
        "id": uuid.uuid4().hex,
        "job_id": None,
        "created_at": now(),
        "status": "regrading",
        "summary": {},
        "sample_count": 0,
        "benchmark": {"id": suite["id"], "lock": lock},
        "grader_version": GRADER_VERSION,
        "regrade": {
            "source_run_id": run_id,
            "source_checksums_sha256": file_hash(source / "checksums.json"),
            "source_records_sha256": hashes["records.jsonl"],
            "source_summary": original["summary"],
            "source_benchmark": original["benchmark"]["id"],
            "source_harness_sha256": original["harness_sha256"],
            "changed_grades": changed,
            "inference_created_at": original["created_at"],
            "inference_finished_at": original["finished_at"],
        },
    }
    record.pop("finished_at", None)
    record.pop("live", None)
    record["harness_sha256"] = digest(
        {p.relative_to(ROOT).as_posix(): file_hash(p) for p in ROOT.rglob("*.py")}
    )
    record["comparability_group"] = digest(
        {
            "inference_group": original.get("comparability_group"),
            "grading_benchmark": lock,
            "grading_harness": record["harness_sha256"],
        }
    )
    artifact = ArtifactRun(store, record)
    try:
        shutil.copytree(source, artifact.path / "source_evidence")
        if verify_evidence(artifact.path / "source_evidence") != hashes:
            raise ValueError("Copied source evidence differs")
        for name in ("model.json", "runtime.json"):
            if (source / name).exists():
                shutil.copyfile(source / name, artifact.path / name)
        write_json(artifact.path / "benchmark.json", suite)
        for relative in lock["files"]:
            target = artifact.path / "benchmark_sources" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for p in ROOT.rglob("*.py"):
            target = artifact.path / "app_sources" / p.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        for relative, notice in distribution_notices().items():
            target = artifact.path / "distribution_notices" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(notice, target)
        for sample in output:
            artifact.append(sample)
        artifact.finish(original["status"])
    except Exception as exc:
        artifact.finish("failed", str(exc))
        raise
    return artifact.record
