import shutil

import pytest

from aaron_model_testing.pipeline import ArtifactRun
from aaron_model_testing.regrade import regrade, verify_evidence
from aaron_model_testing.scoring import score
from aaron_model_testing.store import Store
from aaron_model_testing.suite import ROOT, load_suite
from aaron_model_testing.util import digest, file_hash, write_json


def original_run(tmp_path):
    store = Store(tmp_path)
    suite, lock = load_suite("agent-core-v1")
    record = {
        "id": "original",
        "status": "running",
        "created_at": "2026-10-01T10:00:00+00:00",
        "benchmark": {"id": suite["id"], "lock": lock},
        "harness_sha256": "old-harness",
        "summary": {},
        "sample_count": 0,
        "comparability_group": "old-group",
    }
    artifact = ArtifactRun(store, record)
    write_json(artifact.path / "benchmark.json", suite)
    for relative in lock["files"]:
        target = artifact.path / "benchmark_sources" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    test = suite["tests"][0]
    case = {
        **test,
        "messages": [
            {"role": "system", "content": suite["system"]},
            {"role": "user", "content": test["prompt"]},
        ],
    }
    raw = " \n<think>reasoning...</think> READY\n"
    artifact.append(
        {
            "type": "capability",
            "category": test["category"],
            "test_id": test["id"],
            "response": raw,
            "reasoning": "",
            "events": [{"content": raw}],
            "success": True,
            "test": case,
            "test_sha256": digest(case),
            "prompt_sha256": digest(case["messages"]),
            "grade": score(raw, case["rule"]),
            "finish_reason": "stop",
        }
    )
    artifact.finish("completed")
    return store, artifact.path


def test_regrade_preserves_entire_original_and_versions_derived_evidence(tmp_path):
    store, source = original_run(tmp_path)
    before = {p.relative_to(source).as_posix(): file_hash(p) for p in source.rglob("*") if p.is_file()}
    derived = regrade(store, "original")
    assert derived["id"] != "original"
    assert derived["summary"]["capability"] == 1
    assert store.get("runs", "original")["summary"]["capability"] == 0
    assert derived["benchmark"]["id"] == "agent-core-v1.1"
    assert derived["comparability_group"] != "old-group"
    assert derived["regrade"]["changed_grades"] == 1
    path = store.home / "artifacts" / derived["id"]
    assert verify_evidence(path)
    assert verify_evidence(path / "source_evidence")
    import json

    sample = json.loads((path / "records.jsonl").read_text(encoding="utf-8"))
    assert sample["response"] == " \n<think>reasoning...</think> READY\n"
    assert sample["final_answer"] == "READY" and sample["reasoning"] == "reasoning..."
    assert sample["previous_grade"]["score"] == 0
    assert sample["events"] == [{"content": sample["response"]}]
    assert before == {
        p.relative_to(source).as_posix(): file_hash(p) for p in source.rglob("*") if p.is_file()
    }


def test_legacy_api_warns_without_mutating_original_zero_grade(tmp_path):
    from fastapi.testclient import TestClient

    from aaron_model_testing.app import create_app

    store, source = original_run(tmp_path)
    before = file_hash(source / "manifest.json")
    with TestClient(create_app(tmp_path)) as client:
        record = client.get("/api/runs/original").json()
        assert record["summary"]["capability"] is None
        assert record["summary"]["capability_status"] == "invalid"
        sample = record["records"][0]
        assert sample["legacy_grading_warning"]
        assert sample["grade"]["score"] == 0  # Historical evidence, explicitly unvalidated.
        assert store.get("runs", "original")["summary"]["capability"] == 0
    assert file_hash(source / "manifest.json") == before


@pytest.mark.parametrize("tamper", ["response", "extra", "rule"])
def test_regrade_refuses_changed_or_unrecognised_evidence(tmp_path, tamper):
    import json

    store, source = original_run(tmp_path)
    if tamper == "extra":
        (source / "unexpected.txt").write_text("not checksummed")
    else:
        path = source / "records.jsonl"
        sample = json.loads(path.read_text(encoding="utf-8"))
        if tamper == "response":
            sample["response"] = "changed"
        else:
            sample["test"]["rule"]["expected"] = "WRONG"
        path.write_text(json.dumps(sample) + "\n", encoding="utf-8")
        if tamper == "rule":
            hashes = json.loads((source / "checksums.json").read_text())
            hashes["records.jsonl"] = file_hash(path)
            write_json(source / "checksums.json", hashes)
    with pytest.raises(ValueError):
        regrade(store, "original")
    assert len(store.all("runs")) == 1
