import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from aaron_model_testing import pipeline
from aaron_model_testing.app import create_app
from aaron_model_testing.store import Store
from aaron_model_testing.util import digest


def wait_job(client, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = client.get("/api/jobs/" + job_id).json()
        if result["status"] not in ("running", "queued"):
            return result
        time.sleep(0.02)
    raise TimeoutError("Test worker did not finish")


class FakeServer:
    owned = None

    def __init__(self, config, cancel):
        self.config, self.cancel = config, cancel

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError("Cancelled")

    def request(self, payload, chat=True):
        self.check()
        n = 3 if chat else payload["n_predict"]
        return {
            "success": True,
            "response": "READY",
            "reasoning": "",
            "events": [],
            "request": payload,
            "tool_calls": [],
            "finish_reason": "stop",
            "error": None,
            "metrics": {
                "generation_tps": 50,
                "prompt_tps": 100,
                "input_tokens": len(payload.get("prompt", [])),
                "output_tokens": n,
                "ttft_ms": 10,
                "latency_ms": 100,
            },
        }

    def tokenize(self, text):
        return list(range(len(text)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "verify_model", lambda model, cancel: None)
    monkeypatch.setattr(
        pipeline,
        "probe",
        lambda binary: {
            "path": "fake.exe",
            "sha256": "build",
            "help": "--load-mode",
            "devices": "Vulkan0",
            "dlls": [],
            "version": "test",
        },
    )
    monkeypatch.setattr(pipeline, "environment", lambda: {"fingerprint": "machine"})

    def launch(self, job_id, model, config, build, artifact, name, cancel):
        if config.ctx_size > 2048:
            raise RuntimeError("Simulated OOM")
        artifact.record["commands"].append(
            {
                "argv": ["fake.exe", "--port", "1235"],
                "config": config.model_dump(),
                "command": "fake.exe --port 1235",
                "workspace": name,
            }
        )
        server = FakeServer(config, cancel)
        with self.lock:
            self.active = (job_id, server)
        return server

    def release(self, job_id, server, artifact, name):
        artifact.append(
            {"type": "lifecycle", "workspace": name, "load_ms": 1, "resources": {"ram_peak_mb": 10}}
        )
        self.active = (job_id, None)

    monkeypatch.setattr(pipeline.JobManager, "launch", launch)
    monkeypatch.setattr(pipeline.JobManager, "release", release)
    app = create_app(tmp_path)
    with TestClient(app) as session:
        model = {
            "id": "model",
            "name": "Fake model",
            "filename": "fake.gguf",
            "path": "fake.gguf",
            "sha256": "hash",
            "status": "ready",
            "architecture": "llama",
            "metadata": {},
            "size_bytes": 16,
            "quantisation": "F16",
            "context_capability": 8192,
            "parameter_count": 16,
            "files": [],
        }
        app.state.store.put("models", model)
        session.app_instance = app
        yield session


def new_profile(client, context=1024):
    result = client.post(
        "/api/models/model/profiles", json={"name": "BALANCED", "config": {"ctx_size": context}}
    )
    assert result.status_code == 201
    return result.json()


def test_ui_api_paths_and_local_access_controls(client):
    assert client.get("/").status_code == 200
    assert "Aaron Model Testing" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json()["benchmark_port"] == 1235
    assert client.get("/api/tests").json()["suite"]["id"] == "agent-core-v1.1"
    assert (
        client.post(
            "/api/models/scan", json={"roots": ["x"]}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    settings = client.get("/api/settings").json()
    assert client.put("/api/settings", json={**settings, "benchmark_port": 1234}).status_code == 422
    assert (
        client.post(
            "/api/models/model/profiles", json={"config": {"options": {"--host": "0.0.0.0"}}}
        ).status_code
        == 422
    )
    assert client.get("/api/runs/missing").status_code == 404


def test_pipeline_all_repeats_artifacts_inspector_and_recovery(client):
    profile = new_profile(client)
    body = {
        "model_id": "model",
        "profile_id": profile["id"],
        "stage": "full",
        "contexts": [1024],
        "test_ids": ["instruction-label"],
        "long_context": False,
    }
    job = client.post("/api/runs", json=body).json()
    status = wait_job(client, job["id"])
    assert status["status"] == "completed", status
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["status"] == "completed"
    assert run["summary"]["attempts"] == 6
    assert run["summary"]["metrics"]["generation_tps"]["n"] == 3
    assert run["summary"]["metrics"]["load_ms"]["n"] == 3
    assert run["summary"]["capability"] == 1
    records = run["records"]
    sample = next(r for r in records if r["type"] == "capability")
    inspector = client.get(f"/api/runs/{run['id']}/responses/{sample['id']}").json()
    assert inspector["response"] == "READY"
    assert inspector["test_sha256"] == digest(inspector["test"])
    assert client.get(f"/api/runs/{run['id']}/artifacts").content.startswith(b"PK")
    assert client.get("/api/leaderboard").json()[0]["run_id"] == run["id"]
    store = client.app_instance.state.store
    folder = store.home / "artifacts" / run["id"]
    assert (folder / "records.jsonl").exists()
    from aaron_model_testing.util import file_hash

    checksums = json.loads((folder / "checksums.json").read_text())
    assert checksums["manifest.json"] == file_hash(folder / "manifest.json")
    assert "distribution_notices/THIRD_PARTY_NOTICES.md" in checksums
    assert "distribution_notices/licenses/local_bench-MIT.txt" in checksums
    assert "app_sources/vendor/tune_candidates.py" in checksums
    assert json.loads((folder / "manifest.json").read_text())["model"]["sha256"] == "hash"
    # SQLite index is disposable: restore its rows from durable JSON records.
    with store.connection() as db:
        db.execute("DELETE FROM runs")
    assert not store.all("runs")
    assert store.reindex()["runs"] == 1
    assert store.get("runs", run["id"])["summary"]["reliability"] == 1


def test_load_failures_count_all_scheduled_samples(client):
    profile = new_profile(client)
    body = {
        "model_id": "model",
        "profile_id": profile["id"],
        "stage": "full",
        "contexts": [1024, 4096],
        "test_ids": ["instruction-label"],
        "long_context": False,
    }
    job = client.post("/api/runs", json=body).json()
    status = wait_job(client, job["id"])
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["status"] == "partial"
    assert run["summary"]["errors"] == 3
    assert run["summary"]["attempts"] == 9
    assert run["summary"]["reliability"] == pytest.approx(2 / 3)
    assert run["summary"]["contexts"]["4096"]["generation_tps"]["median"] is None
    assert run["summary"]["partial"] and not run["qualification_eligible"]
    assert client.get("/api/leaderboard").json() == []
    assert run["timing"]["active_seconds"] > 0


def test_tuning_saves_winner_and_never_uses_scored_questions(client):
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "optimise",
            "candidate_limit": 2,
            "contexts": [1024],
        },
    ).json()
    status = wait_job(client, job["id"])
    assert status["status"] == "completed", status
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["winner"]["profile_id"]
    assert len([r for r in run["records"] if r["type"] == "candidate"]) == 2
    assert not any(r["type"] == "capability" for r in run["records"])
    assert len([r for r in run["records"] if r["type"] == "tuning_performance"]) == 6
    assert run["live"]["completed_samples"] == run["planned_samples"] == 18
    assert client.get("/api/leaderboard").json() == []


def test_smart_context_search_prefers_largest_stable_context(client):
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "optimise",
            "candidate_limit": 3,
            "tune_contexts": [1024, 2048, 4096],
            "profile_name": "SMART",
        },
    ).json()
    status = wait_job(client, job["id"])
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["winner"]["config"]["ctx_size"] == 2048
    candidates = [r for r in run["records"] if r["type"] == "candidate"]
    assert len(candidates) == 3 and candidates[-1]["error"] == "Simulated OOM"


def test_shutdown_recovery_marks_interrupted_without_attaching(tmp_path):
    store = Store(tmp_path)
    store.put("jobs", {"id": "oldjob", "status": "running"})
    store.put("runs", {"id": "oldrun", "status": "running"})
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/jobs/oldjob").json()["status"] == "interrupted"
        assert store.get("runs", "oldrun")["status"] == "interrupted"


def test_pending_job_cancellation_is_durable(client):
    manager = client.app_instance.state.manager
    gate = threading.Event()
    original = manager.scan
    manager.scan = lambda job_id, roots, event: gate.wait(1)
    first = manager.submit("scan", {"roots": ["unused"]})
    second = manager.submit("scan", {"roots": ["unused"]})
    assert client.post("/api/jobs/" + second["id"] + "/cancel").json()["cancellation_requested"]
    gate.set()
    assert wait_job(client, first["id"])["status"] == "completed"
    cancelled = wait_job(client, second["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["active_seconds"] is None and cancelled["total_elapsed_seconds"] >= 0
    manager.scan = original


def test_pipeline_embedded_think_grades_final_and_inspector_preserves_raw(client, monkeypatch):
    original = FakeServer.request

    def request(self, payload, chat=True):
        result = original(self, payload, chat)
        if chat:
            result["response"] = " \n<think>reasoning...</think> READY\n"
        return result

    monkeypatch.setattr(FakeServer, "request", request)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "capability",
            "test_ids": ["instruction-label"],
            "contexts": [1024],
            "long_context": False,
        },
    ).json()
    status = wait_job(client, job["id"])
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["summary"]["capability"] == 1
    sample = next(r for r in run["records"] if r["type"] == "capability")
    inspected = client.get(f"/api/runs/{run['id']}/responses/{sample['id']}").json()
    assert inspected["response"] == " \n<think>reasoning...</think> READY\n"
    assert inspected["final_answer"] == "READY"
    assert inspected["reasoning"] == "reasoning..."
    derived = client.post(f"/api/runs/{run['id']}/regrade").json()
    assert derived["id"] != run["id"] and derived["summary"]["capability"] == 1


def test_monitor_updates_while_request_is_still_active_and_cancels(client, monkeypatch):
    original = FakeServer.request
    entered, release = threading.Event(), threading.Event()
    chats = 0

    def request(self, payload, chat=True):
        nonlocal chats
        if chat:
            chats += 1
            if chats == 3:
                entered.set()
                while not release.wait(0.01):
                    self.check()
        return original(self, payload, chat)

    monkeypatch.setattr(FakeServer, "request", request)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "contexts": [1024],
            "long_context": False,
            "test_ids": ["instruction-label"],
        },
    ).json()
    try:
        assert entered.wait(5)
        status = client.get("/api/jobs/" + job["id"]).json()
        monitor = client.get(f"/api/runs/{status['run_id']}/live").json()
        live = monitor["live"]
        assert live["status"] == "running" and live["phase"] == "Capability"
        assert live["completed_samples"] == 5 and live["planned_samples"] == 6
        assert live["current_test"] == "instruction-label" and live["current_repeat"] == 3
        assert live["progress_fraction"] == pytest.approx(5 / 6)
        assert live["capability"] == 1 and live["reliability"] == 1 and live["pass_count"] == 2
        assert live["generation_tps"] == 50 and live["prompt_tps"] == 100
        assert live["eta_seconds"] >= 0 and live["resources"] == {}
        assert live["events"][-1]["outcome"] == "PASS"
        time.sleep(0.05)
        later = client.get(f"/api/runs/{status['run_id']}/live").json()
        assert later["live"]["elapsed_seconds"] > live["elapsed_seconds"]
        assert client.post(f"/api/jobs/{job['id']}/cancel").json()["cancellation_requested"]
        final = wait_job(client, job["id"])
        assert final["status"] == "cancelled"
        assert client.get(f"/api/runs/{status['run_id']}/live").json()["live"]["status"] == "cancelled"
        recorded = client.get(f"/api/runs/{status['run_id']}").json()
        assert recorded["summary"]["partial"] and not recorded["qualification_eligible"]
        assert recorded["summary"]["tokens"]["output_tokens"]["total"] == 390
        assert recorded["timing"]["phases"]["capability"] > 0
        assert recorded["timing"]["active_seconds"] > 0
        assert client.get("/api/leaderboard").json() == []
    finally:
        release.set()


def test_quick_qualification_uses_complete_standard_suite_and_eligible_workload(client):
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "qualification": "quick",
            "contexts": [512],
            "long_context": True,
        },
    ).json()
    status = wait_job(client, job["id"])
    run = client.get("/api/runs/" + status["run_id"]).json()
    assert run["request"]["contexts"] == [2048, 8192] and run["request"]["repeats"] == 3
    assert not run["request"]["long_context"] and not run["smoke"]
    suite = client.get("/api/tests").json()["suite"]
    caps = [r for r in run["records"] if r["type"] == "capability"]
    assert {r["test_id"] for r in caps} == {t["id"] for t in suite["tests"]}
    assert len(caps) == len(suite["tests"]) * 3 == 93
    assert all(r["context_size"] == profile["config"]["ctx_size"] for r in caps)
    assert run["planned_samples"] == 99
    assert run["live"]["completed_samples"] == 99
    assert len(run["live"]["events"]) == 30
    # The preset is eligible only when completed; the fake 8192 context fails to load.
    assert run["status"] == "partial" and not run["qualification_eligible"]
    assert client.get("/api/leaderboard").json() == []


def test_full_and_smoke_presets_keep_existing_methodology():
    full = pipeline.RunRequest(
        model_id="m",
        profile_id="p",
        qualification="full",
        contexts=[512],
        repeats=7,
        long_context=False,
        depths=[0.2],
    )
    assert full.contexts == [2048, 4096, 8192] and full.repeats == 3
    assert full.long_context and full.depths == [0.1, 0.5, 0.9] and not full.smoke
    smoke = pipeline.RunRequest(model_id="m", profile_id="p", qualification="smoke")
    assert smoke.smoke and not smoke.long_context
    with pytest.raises(ValueError):
        pipeline.RunRequest(
            model_id="m", profile_id="p", qualification="quick", test_ids=["instruction-label"]
        )


def test_queued_run_duration_keeps_wait_separate_from_monotonic_active_time(client):
    manager = client.app_instance.state.manager
    entered, gate = threading.Event(), threading.Event()

    def scan(job_id, roots, event):
        entered.set()
        assert gate.wait(5)

    manager.scan = scan
    first = manager.submit("scan", {"roots": []})
    assert entered.wait(5)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "capability",
            "contexts": [1024],
            "test_ids": ["instruction-label"],
            "long_context": False,
        },
    ).json()
    time.sleep(0.08)
    gate.set()
    wait_job(client, first["id"])
    final = wait_job(client, job["id"])
    run = client.get("/api/runs/" + final["run_id"]).json()
    timing = run["timing"]
    assert timing["queue_wait_seconds"] >= 0.08
    assert timing["total_elapsed_seconds"] == pytest.approx(
        timing["queue_wait_seconds"] + timing["active_seconds"]
    )
    assert sum(timing["phases"].values()) == pytest.approx(timing["active_seconds"], abs=0.001)
    assert run["started_at"] and run["queued_at"] and run["finished_at"]
    assert run["summary"]["efficiency"]["correct_capability_samples_per_minute"] == pytest.approx(
        180 / timing["active_seconds"]
    )


def test_failed_setup_retains_timing_and_is_ineligible(client, monkeypatch):
    monkeypatch.setattr(
        pipeline, "probe", lambda binary: (_ for _ in ()).throw(RuntimeError("broken runtime"))
    )
    profile = new_profile(client)
    job = client.post("/api/runs", json={"model_id": "model", "profile_id": profile["id"]}).json()
    final = wait_job(client, job["id"])
    run = client.get("/api/runs/" + final["run_id"]).json()
    assert run["status"] == "failed" and run["timing"]["active_seconds"] > 0
    assert not run["qualification_eligible"] and run["summary"]["partial"]


def test_legacy_detail_derives_diagnostics_without_modifying_artifact(client):
    from aaron_model_testing.grading import grade_result
    from aaron_model_testing.util import file_hash, write_json

    store = client.app_instance.state.store
    folder = store.home / "artifacts" / "legacy-evidence"
    folder.mkdir(parents=True)
    raw = {
        "id": "sample-old",
        "type": "capability",
        "success": True,
        "response": "[]",
        "category": "structured_output",
        "test": {"rule": {"type": "json", "schema": {"type": "object"}}},
        "metrics": {"input_tokens": 12, "output_tokens": 2, "latency_ms": 20},
    }
    raw.update(grade_result(raw, raw["test"]["rule"]))
    (folder / "records.jsonl").write_text(json.dumps(raw) + "\n", encoding="utf-8")
    record = {
        "id": "legacy-evidence",
        "status": "completed",
        "stage": "capability",
        "smoke": False,
        "model": {"name": "old model"},
        "profile": {"name": "old profile"},
        "created_at": "2026-10-01T00:00:00+00:00",
        "finished_at": "2026-10-01T00:01:10+00:00",
        "benchmark": {"id": "agent-core-v1.1"},
        "summary": {"capability": 0},
    }
    store.put("runs", record)
    write_json(folder / "manifest.json", record)
    hashes = {name: file_hash(folder / name) for name in ("manifest.json", "records.jsonl")}
    run = client.get("/api/runs/legacy-evidence").json()
    assert run["timing"]["active_seconds"] == 70
    assert run["records"][0]["diagnostics"]["failure_reason"] == "schema_failure"
    assert run["summary"]["failure_reasons"] == {"schema_failure": 1}
    assert hashes == {name: file_hash(folder / name) for name in hashes}


@pytest.mark.parametrize("objective,expected_candidate", [("FAST", 2), ("BALANCED", 1)])
def test_objective_separate_from_name_and_balanced_rejects_faster_regression(
    client, monkeypatch, objective, expected_candidate
):
    from aaron_model_testing.tuning_guardrails import BALANCED_TASKS

    original = FakeServer.request

    def request(self, payload, chat=True):
        result = original(self, payload, chat)
        if not self.config.flash_attn:
            result["metrics"]["generation_tps"] = 100
        if chat:
            content = payload["messages"][0]["content"]
            task = next((t for t in BALANCED_TASKS if t["prompt"] == content), None)
            if task:
                expected = task["rule"]["expected"]
                result["response"] = expected if isinstance(expected, str) else json.dumps(expected)
                if not self.config.flash_attn and task["id"] == "tune-parse":
                    result["response"] = "bad"
        return result

    monkeypatch.setattr(FakeServer, "request", request)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "optimise",
            "candidate_limit": 2,
            "optimisation_objective": objective,
            "profile_name": "My tuned profile",
        },
    ).json()
    final = wait_job(client, job["id"])
    assert final["status"] == "completed", final
    run = client.get("/api/runs/" + final["run_id"]).json()
    assert run["winner"]["candidate"] == expected_candidate
    assert run["optimisation_objective"] == objective and run["save_winner_as"] == "My tuned profile"
    saved = next(p for p in client.get("/api/profiles").json() if p["id"] == run["winner"]["profile_id"])
    assert saved["name"] == "My tuned profile" and saved["optimisation_objective"] == objective
    report = run["optimisation_report"]
    assert not report["partial"] and report["candidates_tested"] == 2
    assert report["baseline"]["config"] == profile["config"]
    if objective == "BALANCED":
        assert report["candidates"][1]["components"]["rejection_reason"] == "capability_guardrail_regression"
        assert report["runtime_score_improvement_percent"] == 0
    else:
        assert report["runtime_score_improvement_percent"] == 100
        assert report["parameter_deltas"]["flash_attn"]["winner"] is False
        assert not any(r["type"] == "tuning_guardrail" for r in run["records"])


def test_smart_measures_stronger_reasoning_checks_and_explores_thinking(client, monkeypatch):
    from aaron_model_testing.tuning_guardrails import SMART_TASKS

    original = FakeServer.request

    def request(self, payload, chat=True):
        result = original(self, payload, chat)
        if chat:
            task = next((t for t in SMART_TASKS if t["prompt"] == payload["messages"][0]["content"]), None)
            if task and (task["id"] != "tune-reason" or self.config.sampling.enable_thinking):
                expected = task["rule"]["expected"]
                result["response"] = expected if isinstance(expected, str) else json.dumps(expected)
        return result

    monkeypatch.setattr(FakeServer, "request", request)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={
            "model_id": "model",
            "profile_id": profile["id"],
            "stage": "optimise",
            "candidate_limit": 2,
            "optimisation_objective": "SMART",
            "profile_name": "Reasoning candidate",
        },
    ).json()
    final = wait_job(client, job["id"])
    run = client.get("/api/runs/" + final["run_id"]).json()
    assert run["winner"]["candidate"] == 2
    assert run["winner"]["config"]["sampling"]["enable_thinking"]
    assert run["optimisation_report"]["semantic_or_reasoning_settings_changed"]
    assert run["optimisation_report"]["guardrail"]["tasks"] == 4
    assert run["summary"]["capability_samples"] == 0


def test_tuning_refuses_scored_prompt_leakage_before_launch(client, monkeypatch):
    from aaron_model_testing import tuning_guardrails

    suite = client.get("/api/tests").json()["suite"]
    monkeypatch.setattr(
        tuning_guardrails, "SMART_TASKS", [{"id": "different-id", "prompt": suite["tests"][0]["prompt"]}]
    )
    profile = new_profile(client)
    job = client.post(
        "/api/runs", json={"model_id": "model", "profile_id": profile["id"], "stage": "optimise"}
    ).json()
    final = wait_job(client, job["id"])
    assert final["status"] == "failed" and "overlaps scored" in final["error"]
    run = client.get("/api/runs/" + final["run_id"]).json()
    assert run["commands"] == []


def test_cancelled_optimisation_preserves_partial_candidate_report_without_saved_winner(client, monkeypatch):
    original = FakeServer.request
    entered = threading.Event()

    def request(self, payload, chat=True):
        if chat and payload["messages"][0]["content"].startswith("For this unscored"):
            entered.set()
            while not self.cancel.wait(0.01):
                pass
            return {
                "success": False,
                "response": "partial",
                "metrics": {"input_tokens": 10},
                "error": "cancelled",
                "error_kind": "cancelled",
            }
        return original(self, payload, chat)

    monkeypatch.setattr(FakeServer, "request", request)
    profile = new_profile(client)
    job = client.post(
        "/api/runs",
        json={"model_id": "model", "profile_id": profile["id"], "stage": "optimise", "candidate_limit": 2},
    ).json()
    assert entered.wait(5)
    assert client.post("/api/jobs/" + job["id"] + "/cancel").json()["cancellation_requested"]
    final = wait_job(client, job["id"])
    run = client.get("/api/runs/" + final["run_id"]).json()
    assert run["status"] == "cancelled" and run["summary"]["partial"]
    assert run["optimisation_report"]["partial"] and run["optimisation_report"]["candidates_tested"] == 1
    assert not run.get("winner")
    assert len(client.get("/api/profiles").json()) == 1
    assert run["summary"]["tokens"]["output_tokens"]["total"] == 384


def test_compare_timing_and_partial_exclusion_even_in_same_comparison_group(client):
    profile = new_profile(client)
    ids = []
    for _ in range(2):
        job = client.post(
            "/api/runs",
            json={
                "model_id": "model",
                "profile_id": profile["id"],
                "stage": "capability",
                "contexts": [1024],
                "test_ids": ["instruction-label"],
                "long_context": False,
            },
        ).json()
        ids.append(wait_job(client, job["id"])["run_id"])
    result = client.get("/api/compare", params={"ids": ",".join(ids)}).json()
    assert result["comparable"] and result["warning"] is None
    assert all(
        r["timing"]["active_seconds"] > 0
        and r["summary"]["efficiency"]["correct_capability_samples_per_minute"] > 0
        for r in result["runs"]
    )
    store = client.app_instance.state.store
    partial = store.get("runs", ids[1])
    partial["status"] = "cancelled"
    store.put("runs", partial)
    result = client.get("/api/compare", params={"ids": ",".join(ids)}).json()
    assert not result["comparable"] and "diagnostic" in result["warning"]
    assert result["runs"][1]["summary"]["partial"]
    assert {r["run_id"] for r in client.get("/api/leaderboard").json()} == {ids[0]}
