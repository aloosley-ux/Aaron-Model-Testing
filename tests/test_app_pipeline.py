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
    assert wait_job(client, second["id"])["status"] == "cancelled"
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
    assert client.get("/api/leaderboard").json()[0]["request"]["qualification"] == "quick"


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
