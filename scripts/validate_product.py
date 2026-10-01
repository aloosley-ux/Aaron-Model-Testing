"""Exercise the real HTTP app and durable inventory without native inference."""

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import numpy as np
import psutil
import uvicorn
from gguf import GGUFWriter

from aaron_model_testing.app import HomeLock, create_app
from aaron_model_testing.config import Settings
from aaron_model_testing.util import file_hash, write_json


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def protected_listeners():
    """Read ownership only; never send requests to existing app/native services."""
    return sorted(
        (conn.laddr.ip, conn.laddr.port, conn.pid, psutil.Process(conn.pid).create_time())
        for conn in psutil.net_connections(kind="tcp")
        if conn.status == psutil.CONN_LISTEN and conn.laddr.port in (1234, 1235, 4321) and conn.pid
    )


@contextmanager
def live_app(home, evidence):
    # Keep the bound socket until Uvicorn takes it: no free-port probing race.
    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        require(port not in (1234, 1235, 4321), "Unexpected reserved validation port")
        server = uvicorn.Server(
            uvicorn.Config(create_app(home), log_level="warning", timeout_graceful_shutdown=20)
        )
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        evidence.setdefault("http_ports", []).append(port)
        worker.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                require(worker.is_alive(), "HTTP server exited during startup")
                require(time.monotonic() < deadline, "HTTP startup deadline exceeded")
                time.sleep(0.05)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False) as client:
                yield client
        finally:
            server.should_exit = True
            worker.join(timeout=25)
            require(not worker.is_alive(), "HTTP shutdown deadline exceeded")
    require(not server.started or not server.servers[0].is_serving(), "HTTP listener still serving")
    with socket.socket() as released:
        released.bind(("127.0.0.1", port))
    lock = HomeLock(home)
    lock.close()
    require(not server.config.app.state.manager.thread.is_alive(), "FIFO worker still running")
    evidence.setdefault("released_ports", []).append(port)


def response(client, method, path, status=200, **kwargs):
    result = client.request(method, path, **kwargs)
    require(result.status_code == status, f"{method} {path}: {result.status_code} {result.text[:500]}")
    return result


def workflow(home, evidence):
    model_path = home / "fixture model-Q4_K_M.gguf"
    # Same tiny metadata fixture as tests/test_inventory.py; never used for inference.
    writer = GGUFWriter(model_path, "llama")
    try:
        writer.add_string("general.name", "Validation fixture")
        writer.add_uint32("llama.context_length", 4096)
        writer.add_tensor("test.weight", np.zeros((4, 4), dtype=np.float32))
        writer.write_header_to_file()
        writer.write_kv_data_to_file()
        writer.write_tensors_to_file()
    finally:
        writer.close()
    write_json(home / "settings.json", Settings().model_dump())
    with live_app(home, evidence) as client:
        health = response(client, "GET", "/api/health").json()
        require(health["status"] == "ok" and health["benchmark_port"] == 1235, "Invalid health")
        require("Aaron Model Testing" in response(client, "GET", "/").text, "Missing UI")
        for asset in ("app.js", "app.css"):
            require(bool(response(client, "GET", f"/static/{asset}").content), "Empty static asset")
        suite = response(client, "GET", "/api/tests").json()["suite"]
        require(bool(suite["tests"]), "No frozen benchmark tests")
        job = response(client, "POST", "/api/models/scan", 202, json={"roots": [str(model_path)]}).json()
        deadline = time.monotonic() + 15
        while True:
            job = response(client, "GET", f"/api/jobs/{job['id']}").json()
            if job["status"] not in ("queued", "running"):
                break
            require(time.monotonic() < deadline, "Inventory job deadline exceeded")
            time.sleep(0.05)
        require(job["status"] == "completed" and not job["result"]["failures"], f"Scan failed: {job}")
        models = response(client, "GET", "/api/models").json()
        require(len(models) == 1, "Expected one isolated inventory model")
        model_id = models[0]["id"]
        model = response(client, "GET", f"/api/models/{model_id}").json()
        require(model["sha256"] == file_hash(model_path), "Full model hash mismatch")
        require(model["parameter_count"] == 16 and model["context_capability"] == 4096, "Bad metadata")
        profile = response(
            client,
            "POST",
            f"/api/models/{model_id}/profiles",
            201,
            json={"name": "BALANCED", "config": {"ctx_size": 1024}},
        ).json()
        evidence.update(model_id=model_id, profile_id=profile["id"], suite_id=suite["id"])
        require((home / "models" / f"{model_id}.json").is_file(), "Missing durable model")
        require((home / "profiles" / f"{profile['id']}.json").is_file(), "Missing durable profile")
    with live_app(home, evidence) as client:
        require(
            response(client, "GET", f"/api/models/{model_id}").json()["sha256"] == model["sha256"],
            "Inventory did not survive restart",
        )
        require(
            response(client, "GET", "/api/profiles").json() == [profile], "Profile did not survive restart"
        )
        require(
            response(client, "GET", f"/api/jobs/{job['id']}").json()["status"] == "completed",
            "Job did not survive restart",
        )


def main():
    home = Path(__file__).resolve().parents[1] / ".local" / "validation" / uuid.uuid4().hex
    home.mkdir(parents=True)
    evidence = {"status": "running", "data_directory": str(home), "native_inference": "not exercised"}
    write_json(home / "validation.json", evidence)
    try:
        evidence["protected_before"] = protected_listeners()
        workflow(home, evidence)
        evidence["protected_after"] = protected_listeners()
        require(
            evidence["protected_before"] == evidence["protected_after"], "Existing listener ownership changed"
        )
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write_json(home / "validation.json", evidence)
        print(json.dumps(evidence, indent=2))
    print(
        "PASS: real HTTP UI/assets, GGUF scan/hash, profile persistence, restart and cleanup. "
        "Native inference and browser visual QA remain separate hardware/manual checks."
    )


if __name__ == "__main__":
    main()
