from __future__ import annotations

import json
import os
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings, data_home, load_settings
from .pipeline import JobManager, RunRequest
from .profiles import ProfileRequest
from .runtime import environment, probe, server_command
from .store import Store
from .suite import load_suite
from .util import command_text, distribution_notices, write_json


class ScanRequest(BaseModel):
    roots: list[str] = Field(min_length=1, max_length=30)


class ModelNotes(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=10000)


class HomeLock:
    def __init__(self, home):
        home.mkdir(parents=True, exist_ok=True)
        self.file = (home / "application.lock").open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another Aaron Model Testing instance owns this data directory") from None

    def close(self):
        if os.name == "nt":
            import msvcrt

            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def create_app(home: Path | None = None):
    home = home or data_home()

    @asynccontextmanager
    async def lifespan(app):
        lock = HomeLock(home)
        try:
            store = Store(home)
            settings = load_settings(home)
            load_suite()
            app.state.store = store
            app.state.manager = JobManager(store, settings)
            app.state.probe_lock = threading.Lock()
            app.state.build = None
            try:
                yield
            finally:
                app.state.manager.shutdown()
        finally:
            lock.close()

    app = FastAPI(title="Aaron Model Testing", version=__version__, lifespan=lifespan)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "Loopback access only"}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin not in (
                "http://127.0.0.1:4321",
                "http://localhost:4321",
                "http://testserver",
            ):
                return JSONResponse({"detail": "Foreign browser origin is prohibited"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def bad_state(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def get(table, record_id):
        result = app.state.store.get(table, record_id)
        if result is None:
            raise HTTPException(404, f"{table[:-1].title()} not found")
        return result

    def cached_build():
        with app.state.probe_lock:
            if app.state.build is None:
                app.state.build = probe(app.state.manager.settings.server_binary)
            return app.state.build

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "benchmark_port": 1235, "inference_lanes": 1}

    @app.get("/api/settings")
    def settings():
        return app.state.manager.settings.model_dump()

    @app.put("/api/settings")
    def update_settings(settings: Settings):
        with app.state.manager.lock:
            if app.state.manager.events:
                raise RuntimeError("Wait for jobs to finish or cancel them before changing settings")
            app.state.manager.settings = settings
            app.state.build = None
            write_json(home / "settings.json", settings.model_dump())
        return settings.model_dump()

    @app.get("/api/runtime")
    def runtime():
        return {"runtime": cached_build(), "environment": environment()}

    @app.get("/api/models")
    def models():
        return [
            {k: v for k, v in model.items() if k not in ("metadata", "chat_template", "files")}
            for model in app.state.store.all("models")
        ]

    @app.post("/api/models/scan", status_code=202)
    def scan(request: ScanRequest):
        return app.state.manager.submit("scan", request.model_dump())

    @app.get("/api/models/{model_id}")
    def model_detail(model_id: str):
        model = get("models", model_id)
        model["profiles"] = [p for p in app.state.store.all("profiles") if p["model_id"] == model_id]
        model["runs"] = [run_brief(r) for r in app.state.store.all("runs") if r["model_id"] == model_id]
        return model

    @app.patch("/api/models/{model_id}")
    def notes(model_id: str, request: ModelNotes):
        model = get("models", model_id)
        model.update(request.model_dump(exclude_unset=True))
        if not model["name"]:
            raise ValueError("Model name is required")
        app.state.store.put("models", model)
        return model

    @app.post("/api/models/{model_id}/profiles", status_code=201)
    def profile(model_id: str, request: ProfileRequest):
        model = get("models", model_id)
        config = request.config.model_dump()
        if config["template"] is None and model.get("external_template_path"):
            # Save contents, not a mutable external dependency.
            path = Path(model["external_template_path"])
            if path.stat().st_size > 500000:
                raise ValueError("External template exceeds limit")
            config["template"] = path.read_text(encoding="utf-8")
        return app.state.manager.save_profile(model, request.name, config, notes=request.notes)

    @app.get("/api/profiles")
    def profiles():
        return app.state.store.all("profiles")

    @app.get("/api/profiles/{profile_id}/command")
    def command(profile_id: str):
        from .profiles import RuntimeConfig

        saved = get("profiles", profile_id)
        model = get("models", saved["model_id"])
        config = RuntimeConfig.model_validate(saved["config"])
        argv = server_command(
            app.state.manager.settings, model, config, cached_build(), home / "previews" / profile_id
        )
        return {"argv": argv, "command": command_text(argv), "config": saved["config"], "preview": True}

    @app.get("/api/jobs")
    def jobs():
        return app.state.store.all("jobs")[:100]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        return get("jobs", job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        get("jobs", job_id)
        return {"cancellation_requested": app.state.manager.cancel(job_id)}

    @app.post("/api/runs", status_code=202)
    def start(request: RunRequest):
        model = get("models", request.model_id)
        profile = get("profiles", request.profile_id)
        if model["status"] != "ready" or profile["model_id"] != model["id"]:
            raise ValueError("Select a text model and one of its saved profiles")
        return app.state.manager.submit("run", request.model_dump())

    def run_brief(record):
        return {
            k: v
            for k, v in record.items()
            if k not in ("model", "runtime", "environment", "commands", "settings", "benchmark")
        }

    @app.get("/api/runs")
    def runs():
        return [run_brief(r) for r in app.state.store.all("runs")]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str, include_raw: bool = False):
        record = get("runs", run_id)
        records = []
        path = home / "artifacts" / run_id / "records.jsonl"
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        sample = json.loads(line)
                        records.append(
                            sample
                            if include_raw
                            else {
                                k: v
                                for k, v in sample.items()
                                if k
                                not in (
                                    "events",
                                    "response",
                                    "reasoning",
                                    "request",
                                    "test",
                                    "runtime_config",
                                )
                            }
                        )
                    except json.JSONDecodeError:
                        record["artifact_warning"] = (
                            "An incomplete JSONL record was found after interrupted writing"
                        )
        record["records"] = records
        return record

    @app.get("/api/runs/{run_id}/responses/{sample_id}")
    def response(run_id: str, sample_id: str):
        found = next((r for r in run(run_id, include_raw=True)["records"] if r["id"] == sample_id), None)
        if found is None:
            raise HTTPException(404, "Sample not found")
        return found

    @app.get("/api/runs/{run_id}/artifacts")
    def export(run_id: str):
        record = get("runs", run_id)
        if record["status"] in ("running", "queued"):
            raise RuntimeError("Export after the run finishes to get a consistent archive")
        folder = home / "artifacts" / run_id
        path = home / "exports" / (run_id + ".zip")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in folder.rglob("*"):
                if item.is_file():
                    archive.write(item, item.relative_to(folder))
            # Older development runs lack notice snapshots; accompany their reused source too.
            for relative, notice in distribution_notices().items():
                name = "distribution_notices/" + relative
                if not (folder / name).is_file():
                    archive.write(notice, name)
        return FileResponse(path, filename=f"amt-{run_id}.zip", media_type="application/zip")

    @app.get("/api/tests")
    def tests():
        suite, lock = load_suite()
        return {"suite": suite, "lock": lock}

    @app.get("/api/leaderboard")
    def leaderboard():
        output, seen = [], set()
        for r in sorted(app.state.store.all("runs"), key=lambda r: r["created_at"], reverse=True):
            if r["status"] not in ("completed", "partial") or r["smoke"] or r["stage"] == "optimise":
                continue
            key = (r["model"]["sha256"], r["profile"]["config_sha256"], r.get("comparability_group"))
            if key in seen:
                continue
            seen.add(key)
            lifecycle = [s for s in run(r["id"])["records"] if s.get("type") == "lifecycle"]
            ram = [s.get("resources", {}).get("ram_peak_mb") for s in lifecycle]
            output.append(
                {
                    "run_id": r["id"],
                    "model_id": r["model_id"],
                    "model_name": r["model"]["name"],
                    "profile_name": r["profile"]["name"],
                    "profile_id": r["profile"]["id"],
                    "quantisation": r["model"]["quantisation"],
                    "status": r["status"],
                    "summary": r["summary"],
                    "request": r["request"],
                    "created_at": r["created_at"],
                    "comparability_group": r.get("comparability_group"),
                    "ram_peak_mb": max((n for n in ram if n is not None), default=None),
                    "vram_peak_mb": r["summary"].get("resources", {}).get("vram_peak_mb", {}).get("max"),
                }
            )
        return output

    @app.get("/api/compare")
    def compare(ids: str):
        values = ids.split(",")
        if not 2 <= len(values) <= 6:
            raise ValueError("Select 2–6 run IDs")
        records = [get("runs", v) for v in values]
        groups = {r.get("comparability_group") for r in records}
        return {
            "comparable": len(groups) == 1 and None not in groups,
            "warning": None
            if len(groups) == 1 and None not in groups
            else "Workload, build or machine differs; interpret comparison with care",
            "runs": [run_brief(r) for r in records],
        }

    return app
