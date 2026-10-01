from __future__ import annotations

import json
import queue
import shutil
import threading
import traceback
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .aggregation import aggregate
from .config import Settings
from .grading import GRADER_VERSION, grade_result
from .inventory import discover, register, verify_model
from .live import EVENT_LIMIT, activity, snapshot
from .longcontext import KINDS, build_case
from .performance import summarize, workload
from .profiles import RuntimeConfig
from .runtime import NativeServer, allocations, environment, probe
from .suite import ROOT, load_suite
from .tuning import candidates, objective
from .util import digest, distribution_notices, file_hash, now, write_json


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    profile_id: str
    stage: Literal["full", "performance", "capability", "optimise"] = "full"
    smoke: bool = False
    qualification: Literal["custom", "quick", "full", "smoke"] = "custom"
    contexts: list[int] = Field(default_factory=lambda: [2048, 4096, 8192], min_length=1, max_length=6)
    repeats: int = Field(default=3, ge=3, le=10)
    generation_tokens: int = Field(default=128, ge=16, le=1024)
    long_context: bool = True
    depths: list[float] = Field(default_factory=lambda: [0.1, 0.5, 0.9], min_length=1, max_length=5)
    test_ids: list[str] | None = None
    preset: Literal["quick", "standard", "thorough", "drill"] = "quick"
    candidate_limit: int | None = Field(default=None, ge=1, le=128)
    tune_contexts: list[int] | None = Field(default=None, min_length=1, max_length=6)
    profile_name: Literal["FAST", "BALANCED", "SMART"] = "BALANCED"
    load_repeats: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def valid(self):
        if self.qualification != "custom":
            if self.stage != "full" or self.test_ids is not None:
                raise ValueError(
                    "Qualification presets require performance + the complete standard capability suite"
                )
            self.smoke = self.qualification == "smoke"
            self.contexts = [2048, 8192] if self.qualification == "quick" else [2048, 4096, 8192]
            self.repeats = 3
            self.long_context = self.qualification == "full"
            self.depths = [0.1, 0.5, 0.9]
            self.generation_tokens = 128
            self.load_repeats = 3
        if len(set(self.contexts)) != len(self.contexts) or any(
            not 512 <= n <= 262144 for n in self.contexts
        ):
            raise ValueError("Use unique contexts between 512 and 262144")
        if len(set(self.depths)) != len(self.depths) or any(not 0.01 <= d <= 0.99 for d in self.depths):
            raise ValueError("Use unique insertion depths between .01 and .99")
        if self.tune_contexts is not None and (
            len(set(self.tune_contexts)) != len(self.tune_contexts)
            or any(not 512 <= c <= 262144 for c in self.tune_contexts)
        ):
            raise ValueError("Use unique tuning contexts between 512 and 262144")
        return self


class ArtifactRun:
    def __init__(self, store, record):
        self.store, self.record = store, record
        self.path = store.home / "artifacts" / record["id"]
        self.path.mkdir(parents=True, exist_ok=False)
        self.records = []
        self.file = (self.path / "records.jsonl").open("a", encoding="utf-8", newline="\n")
        self.save()

    def save(self):
        write_json(self.path / "manifest.json", self.record)
        self.store.put("runs", self.record)

    def summary(self):
        return aggregate(self.records)

    def phase(self, phase, **values):
        live = self.record.setdefault("live", {"events": []})
        live.update({"phase": phase, "current_test": None, "current_repeat": None, **values})
        self.save()

    def append(self, result):
        import os

        result = {"id": f"sample-{len(self.records) + 1:05d}", "timestamp": now(), **result}
        self.records.append(result)
        self.file.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
        self.file.flush()
        os.fsync(self.file.fileno())
        self.record["sample_count"] = len(self.records)
        self.record["summary"] = self.summary()
        live = self.record.setdefault("live", {"events": []})
        event = activity(result)
        if event:
            live["events"] = [*live.get("events", []), event][-EVENT_LIMIT:]
        self.record["live"] = snapshot(self.record, self.records)
        self.save()

    def finish(self, status, error=None):
        self.record.update(status=status, error=error, finished_at=now())
        self.record["live"] = snapshot(self.record, self.records)
        self.record["live"]["phase"] = status
        self.record["summary"] = self.summary()
        write_json(self.path / "summary.json", self.record["summary"])
        self.save()
        # Digest file inventory permits independent artifact verification.
        from .util import file_hash

        files = {
            str(p.relative_to(self.path)).replace("\\", "/"): file_hash(p)
            for p in self.path.rglob("*")
            if p.is_file() and p != self.path / "checksums.json"
        }
        write_json(self.path / "checksums.json", files)
        self.file.close()


class JobManager:
    def __init__(self, store, settings: Settings):
        self.store, self.settings = store, settings
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.events = {}
        self.active = None
        self.closing = False
        # Recover an interrupted app, without attaching to/killing any existing process.
        for table in ("jobs", "runs"):
            for record in store.all(table):
                if record.get("status") in ("queued", "running"):
                    record.update(
                        status="interrupted", finished_at=now(), error="Application stopped before completion"
                    )
                    store.put(table, record)
                    if table == "runs":
                        write_json(store.home / "artifacts" / record["id"] / "manifest.json", record)
        self.thread = threading.Thread(target=self._worker, name="amt-single-worker", daemon=True)
        self.thread.start()

    def submit(self, kind: str, payload: dict):
        with self.lock:
            if self.closing:
                raise RuntimeError("Application is shutting down")
            job = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "payload": payload,
                "status": "queued",
                "created_at": now(),
                "progress": "Queued for the single worker",
            }
            self.events[job["id"]] = threading.Event()
            self.store.put("jobs", job)
            self.queue.put(job["id"])
            return job

    def update(self, job_id, **values):
        with self.lock:
            job = self.store.get("jobs", job_id)
            job.update(values)
            self.store.put("jobs", job)

    def cancel(self, job_id):
        with self.lock:
            event = self.events.get(job_id)
            if event is None:
                return False
            event.set()
            if self.active and self.active[0] == job_id:
                server = self.active[1]
                if server and server.owned:
                    server.owned.close()
            return True

    def monitor(self, run_id):
        record = self.store.get("runs", run_id)
        if record is None:
            raise ValueError("Run not found")
        resources = None
        with self.lock:
            if self.active and self.active[0] == record.get("job_id"):
                telemetry = getattr(self.active[1], "telemetry", None)
                if telemetry:
                    resources = telemetry.snapshot()
        # Sample counters are persisted on append; recalculate only the wall clock/ETA here.
        live = dict(record.get("live", {}))
        if record["status"] in ("running", "queued"):
            from datetime import datetime, timezone

            elapsed = (
                datetime.now(timezone.utc) - datetime.fromisoformat(record["created_at"])
            ).total_seconds()
            live["elapsed_seconds"] = max(0, elapsed)
            done, planned = live.get("completed_samples"), record.get("planned_samples")
            live["eta_seconds"] = elapsed / done * max(0, planned - done) if done and planned else None
        live.update(
            status=record["status"], resources=resources or {}, planned_samples=record.get("planned_samples")
        )
        return {
            "id": run_id,
            "model": record["model"]["name"],
            "profile": record["profile"]["name"],
            "stage": record["stage"],
            "qualification": record["request"].get("qualification", "custom"),
            "job_id": record.get("job_id"),
            "summary": record["summary"],
            "live": live,
        }

    def shutdown(self):
        with self.lock:
            self.closing = True
            for job_id in list(self.events):
                self.cancel(job_id)
            self.queue.put(None)
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError("Worker did not stop within shutdown deadline")

    def _worker(self):
        while (job_id := self.queue.get()) is not None:
            event = self.events[job_id]
            try:
                if event.is_set():
                    raise InterruptedError("Cancelled while queued")
                self.update(job_id, status="running", started_at=now())
                job = self.store.get("jobs", job_id)
                if job["kind"] == "scan":
                    self.scan(job_id, job["payload"]["roots"], event)
                elif job["kind"] == "run":
                    self.run(job_id, RunRequest.model_validate(job["payload"]), event)
                else:
                    raise ValueError("Unknown job")
                self.update(job_id, status="completed", finished_at=now(), progress="Complete")
            except InterruptedError as exc:
                self.update(job_id, status="cancelled", finished_at=now(), error=str(exc))
            except Exception as exc:
                self.update(
                    job_id,
                    status="failed",
                    finished_at=now(),
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
            finally:
                with self.lock:
                    self.events.pop(job_id, None)
                    self.active = None
                self.queue.task_done()

    def scan(self, job_id, roots, cancel):
        paths = discover(roots)
        failures, registered, seen = [], [], set()
        for i, path in enumerate(paths):
            if cancel.is_set():
                raise InterruptedError("Inventory cancelled")
            if str(path) in seen:
                continue
            self.update(job_id, progress=f"Reading and hashing {i + 1}/{len(paths)}: {path.name}")
            try:
                record = register(path, cancel)
                seen.update(p["path"] for p in record["files"])
                previous = self.store.get("models", record["id"])
                if previous:
                    for key in ("notes", "source", "name"):
                        if previous.get(key):
                            record[key] = previous[key]
                self.store.put("models", record)
                registered.append(record["id"])
            except InterruptedError:
                raise
            except Exception as exc:
                failures.append({"path": str(path), "error": str(exc)})
        self.update(job_id, result={"registered": registered, "failures": failures})

    def save_profile(self, model, name, config, **extra):
        config = RuntimeConfig.model_validate(config).model_dump()
        record = {
            "id": uuid.uuid4().hex,
            "model_id": model["id"],
            "model_sha256": model["sha256"],
            "name": name,
            "config": config,
            "config_sha256": digest(config),
            "created_at": now(),
            **extra,
        }
        self.store.put("profiles", record)
        return record

    def run(self, job_id, request, cancel):
        model = self.store.get("models", request.model_id)
        profile = self.store.get("profiles", request.profile_id)
        if not model or not profile or profile["model_id"] != model["id"]:
            raise ValueError("Select a model and a matching saved profile")
        if model["status"] != "ready":
            raise ValueError("Auxiliary GGUFs are inventoried but cannot run text benchmarks")
        if profile["model_sha256"] != model["sha256"]:
            raise ValueError("Profile was saved for a different model fingerprint; save a fresh profile")
        base = RuntimeConfig.model_validate(profile["config"])
        suite, lock = load_suite()
        if request.test_ids is not None and (
            not request.test_ids or set(request.test_ids) - {t["id"] for t in suite["tests"]}
        ):
            raise ValueError("Unknown or empty test selection")
        run_id = uuid.uuid4().hex
        record = {
            "id": run_id,
            "job_id": job_id,
            "created_at": now(),
            "status": "running",
            "stage": request.stage,
            "smoke": request.smoke,
            "model_id": model["id"],
            "model": model,
            "profile": profile,
            "request": request.model_dump(),
            "benchmark": {"id": suite["id"], "lock": lock},
            "grader_version": GRADER_VERSION,
            "summary": {},
            "sample_count": 0,
            "commands": [],
        }
        artifact = ArtifactRun(self.store, record)
        # Large token vocabularies belong in a single immutable snapshot, not every progress write.
        write_json(artifact.path / "model.json", model)
        record["model"] = {k: v for k, v in model.items() if k not in ("metadata", "chat_template")}
        record["model"]["metadata_artifact"] = "model.json"
        record["model"]["chat_template_sha256"] = digest(model.get("chat_template"))
        self.update(job_id, run_id=run_id, progress="Verifying all model bytes against registered SHA256")
        artifact.phase("Verifying model hashes")
        try:
            verify_model(model, cancel)
            build = probe(self.settings.server_binary)
            if self.settings.device not in build["devices"]:
                raise ValueError(f"Selected device {self.settings.device} is not in runtime device list")
            env = environment()
            record.update(
                runtime=build,
                environment=env,
                settings=self.settings.model_dump(),
                harness_sha256=digest({str(p.relative_to(ROOT)): file_hash(p) for p in ROOT.rglob("*.py")}),
            )
            record["comparability_group"] = digest(
                {
                    "env": env["fingerprint"],
                    "runtime": build["sha256"],
                    "dlls": build["dlls"],
                    "suite": lock,
                    "harness": record["harness_sha256"],
                    "device": self.settings.device,
                    "gpu_environment": env.get("gpu_environment", {}),
                    "gpu_telemetry": self.settings.gpu_telemetry,
                    "workload": {
                        k: request.model_dump()[k]
                        for k in (
                            "stage",
                            "smoke",
                            "contexts",
                            "repeats",
                            "generation_tokens",
                            "long_context",
                            "depths",
                            "test_ids",
                            "load_repeats",
                        )
                    },
                }
            )
            for relative in lock["files"]:
                target = artifact.path / "benchmark_sources" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            # Preserve the executable's advertised interface and the complete frozen benchmark.
            write_json(artifact.path / "benchmark.json", suite)
            write_json(artifact.path / "runtime.json", build)
            for source in ROOT.rglob("*.py"):
                target = artifact.path / "app_sources" / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            for relative, source in distribution_notices().items():
                target = artifact.path / "distribution_notices" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            artifact.save()
            if request.stage == "optimise":
                self.optimise(job_id, request, model, base, build, artifact, cancel)
            else:
                self.benchmark(job_id, request, model, base, build, artifact, suite, cancel)
            if cancel.is_set():
                raise InterruptedError("Cancelled")
            summary = summarize(artifact.records)
            terminal = "completed" if not summary["errors"] else "partial"
            artifact.finish(terminal)
        except InterruptedError as exc:
            artifact.finish("cancelled", str(exc))
            raise
        except Exception as exc:
            artifact.finish("failed", str(exc))
            raise

    def launch(self, job_id, model, config, build, artifact, name, cancel):
        artifact.phase("Loading", current_context=config.ctx_size)
        server = NativeServer(self.settings, model, config, build, artifact.path / name, cancel)
        with self.lock:
            self.active = (job_id, server)
        artifact.record["commands"].append(
            {
                "workspace": name,
                "argv": server.argv,
                "command": server.command,
                "config": config.model_dump(),
                "config_sha256": digest(config.model_dump()),
            }
        )
        artifact.save()
        try:
            return server.start()
        except Exception:
            server.close()
            raise

    def release(self, job_id, server, artifact, name):
        server.close()
        log = server.owned.tail() if server.owned else ""
        resources = {**(server.resources or {}), "vulkan_buffer_allocated_mb": allocations(log)}
        write_json(artifact.path / name / "resources.json", resources)
        artifact.append(
            {
                "type": "lifecycle",
                "workspace": name,
                "load_ms": server.load_ms,
                "resources": {k: v for k, v in resources.items() if k not in ("samples", "gpu_samples")},
                "context_size": server.config.ctx_size,
                "memory_limit_bytes": getattr(server, "process_memory_limit", None),
                "exit_code": server.owned.process.returncode if server.owned else None,
            }
        )
        with self.lock:
            self.active = (job_id, None)

    def optimise(self, job_id, request, model, base, build, artifact, cancel):
        limit = (
            request.candidate_limit
            or {"quick": 8, "standard": 24, "thorough": 64, "drill": 32}[request.preset]
        )
        # Refine a known winner using its saved profile as the seed. Search is finite and reviewable.
        options = candidates(
            base,
            request.preset,
            limit,
            int(model["metadata"].get(f"{model['architecture']}.block_count", 32)),
        )
        write_json(artifact.path / "candidate-plan.json", [c.model_dump() for c in options])
        if request.tune_contexts:
            expanded = []
            for candidate in options:
                for context in request.tune_contexts:
                    expanded.append(
                        RuntimeConfig.model_validate({**candidate.model_dump(), "ctx_size": context})
                    )
            options = expanded[:limit]
            write_json(artifact.path / "candidate-plan.json", [c.model_dump() for c in options])
        best = None
        best_value = None
        best_key = None
        artifact.record["planned_samples"] = len(options) * request.repeats
        artifact.save()
        for i, config in enumerate(options):
            if cancel.is_set():
                raise InterruptedError("Optimisation cancelled")
            name = f"candidate-{i + 1:03d}"
            self.update(
                job_id,
                progress=f"{request.preset}: candidate {i + 1}/{len(options)}; {request.repeats} repeats",
            )
            server, samples, error = None, [], None
            try:
                if model.get("context_capability") and config.ctx_size > model["context_capability"]:
                    raise ValueError("Requested context exceeds model's declared context capability")
                server = self.launch(job_id, model, config, build, artifact, name, cancel)
                warmup = server.request(
                    {"prompt": "Warmup workload.", "n_predict": 8, "ignore_eos": True}, chat=False
                )
                write_json(artifact.path / name / "warmup.json", warmup)
                for rep in range(request.repeats):
                    artifact.phase(
                        "Optimisation",
                        current_context=config.ctx_size,
                        current_test=f"candidate {i + 1}",
                        current_repeat=rep + 1,
                    )
                    sample = workload(server, 256, 128, rep)
                    sample.update(type="tuning_performance", candidate=i + 1, context_size=config.ctx_size)
                    artifact.append(sample)
                    samples.append({**sample, "type": "performance"})
                    server.check()
                # Check templated chat separately; no scored capability questions are used.
                health = server.request(
                    {
                        "messages": [{"role": "user", "content": "Write a brief greeting."}],
                        "max_tokens": min(256, config.ctx_size // 4),
                    }
                )
                write_json(artifact.path / name / "chat-health.json", health)
                if not health["success"]:
                    raise ValueError("Templated chat stability check failed")
            except InterruptedError:
                raise
            except Exception as exc:
                error = str(exc)
            finally:
                if server:
                    self.release(job_id, server, artifact, name)
            summary = summarize(samples)
            value = objective(summary, request.profile_name) if not error else None
            result = {
                "type": "candidate",
                "candidate": i + 1,
                "config": config.model_dump(),
                "config_sha256": digest(config.model_dump()),
                "summary": summary,
                "objective": value,
                "stable": value is not None,
                "error": error,
            }
            artifact.append(result)
            write_json(artifact.path / name / "candidate.json", result)
            key = (config.ctx_size if request.profile_name == "SMART" else 0, value or 0)
            if value is not None and (best_key is None or key > best_key):
                best, best_value = result, value
                best_key = key
        if best is None:
            raise ValueError(
                "No stable candidate passed all repeated workloads and chat health check; inspect candidate errors"
            )
        profile = self.save_profile(
            model,
            request.profile_name,
            best["config"],
            optimisation_run_id=artifact.record["id"],
            objective=best_value,
            notes="Best tested stable configuration at this context. Capability remains to be measured.",
        )
        artifact.record["winner"] = {"profile_id": profile["id"], **best}
        write_json(artifact.path / "winner.json", artifact.record["winner"])
        artifact.save()
        self.update(job_id, result={"winning_profile_id": profile["id"]})

    def benchmark(self, job_id, request, model, base, build, artifact, suite, cancel):
        tests = [
            t
            for t in suite["tests"]
            if (not request.smoke or t.get("smoke"))
            and (request.test_ids is None or t["id"] in request.test_ids)
        ]
        contexts = [min(base.ctx_size, 1024)] if request.smoke else request.contexts
        output = 32 if request.smoke else request.generation_tokens
        do_perf = request.stage in ("full", "performance")
        do_cap = request.stage in ("full", "capability")
        # Standard capability suite runs once at profile context; long-context matrix runs at all requested contexts.
        contexts = list(dict.fromkeys(([base.ctx_size] if do_cap and not request.smoke else []) + contexts))
        artifact.record["planned_capability_samples"] = (len(tests) * request.repeats if do_cap else 0) + (
            len(request.contexts) * len(request.depths) * len(KINDS) * request.repeats
            if do_cap and request.long_context and not request.smoke
            else 0
        )
        artifact.record["planned_samples"] = artifact.record["planned_capability_samples"] + (
            (1 if request.smoke else len(request.contexts)) * request.repeats if do_perf else 0
        )
        artifact.save()
        base_done = False
        for context in contexts:
            if cancel.is_set():
                raise InterruptedError("Benchmark cancelled")
            config = RuntimeConfig.model_validate({**base.model_dump(), "ctx_size": context})
            name = f"context-{context}"
            server = None
            cap_here = do_cap and not base_done
            long_here = do_cap and request.long_context and not request.smoke and context in request.contexts
            perf_here = do_perf and (request.smoke or context in request.contexts)
            try:
                self.update(job_id, progress=f"Loading context {context}")
                if model.get("context_capability") and context > model["context_capability"]:
                    raise ValueError("Context exceeds the model's declared capability")
                for load_rep in range(request.load_repeats - 1):
                    load_name = f"{name}-load-{load_rep + 1}"
                    self.update(
                        job_id,
                        progress=f"Load timing: context {context}, repeat {load_rep + 1}/{request.load_repeats}",
                    )
                    loader = self.launch(job_id, model, config, build, artifact, load_name, cancel)
                    self.release(job_id, loader, artifact, load_name)
                server = self.launch(job_id, model, config, build, artifact, name, cancel)
                warmup = server.request(
                    {"prompt": "Warmup workload.", "n_predict": 8, "ignore_eos": True}, chat=False
                )
                write_json(artifact.path / name / "warmup.json", warmup)
                if perf_here:
                    for rep in range(request.repeats):
                        artifact.phase(
                            "Performance",
                            current_context=context,
                            current_test="throughput",
                            current_repeat=rep + 1,
                        )
                        self.update(
                            job_id,
                            progress=f"Performance: context {context}, repeat {rep + 1}/{request.repeats}",
                        )
                        sample = workload(
                            server,
                            min(context - output - 64, 256 if request.smoke else context * 3 // 4),
                            output,
                            rep,
                        )
                        sample.update(context_size=context, runtime_config=config.model_dump())
                        artifact.append(sample)
                        server.check()
                if cap_here:
                    for test in tests:
                        case = {
                            **test,
                            "messages": [
                                {"role": "system", "content": suite["system"]},
                                {"role": "user", "content": test["prompt"]},
                            ],
                        }
                        for rep in range(request.repeats):
                            self.capability(job_id, artifact, server, case, context, rep, request.smoke)
                    base_done = True
                if long_here:
                    budget = min(base.sampling.token_budget, context // 4)
                    for depth in request.depths:
                        for kind in KINDS:
                            artifact.phase(
                                "Building long-context case", current_context=context, current_test=kind
                            )
                            case = build_case(
                                kind, context * 3 // 4, depth, base.sampling.seed, server, budget
                            )
                            for rep in range(request.repeats):
                                self.capability(job_id, artifact, server, case, context, rep, False)
            except InterruptedError:
                raise
            except Exception as exc:
                if cancel.is_set():
                    raise InterruptedError("Cancelled") from exc
                artifact.append(
                    {"type": "context_error", "context_size": context, "error": str(exc), "success": False}
                )
                # Failed loads count as missing/failed scheduled samples, not invisible exclusions.
                existing = {
                    (r.get("test_id"), r.get("repeat"))
                    for r in artifact.records
                    if r.get("type") == "capability" and r.get("context_size") == context
                }
                cases = tests if cap_here else []
                if long_here:
                    cases = cases + [
                        {"id": f"long-{kind}-{context * 3 // 4}-{depth}", "category": "long_context_" + kind}
                        for depth in request.depths
                        for kind in KINDS
                    ]
                for test in cases:
                    for rep in range(request.repeats):
                        if (test["id"], rep) not in existing:
                            artifact.append(
                                {
                                    "type": "capability",
                                    "test_id": test["id"],
                                    "category": test["category"],
                                    "repeat": rep,
                                    "context_size": context,
                                    "success": False,
                                    "error": str(exc),
                                    "grade": {
                                        "score": 0,
                                        "passed": False,
                                        "detail": "Not executed: " + str(exc),
                                    },
                                }
                            )
                if perf_here:
                    done = sum(
                        r.get("type") == "performance" and r.get("context_size") == context
                        for r in artifact.records
                    )
                    for rep in range(done, request.repeats):
                        artifact.append(
                            {
                                "type": "performance",
                                "context_size": context,
                                "repeat": rep,
                                "success": False,
                                "error": str(exc),
                            }
                        )
                if cap_here:
                    base_done = True
            finally:
                if server:
                    self.release(job_id, server, artifact, name)

    def capability(self, job_id, artifact, server, case, context, rep, smoke):
        artifact.phase("Capability", current_context=context, current_test=case["id"], current_repeat=rep + 1)
        self.update(job_id, progress=f"Capability: {case['id']}, context {context}, repeat {rep + 1}")
        budget = case.get("max_tokens") or min(
            server.config.sampling.token_budget, 128 if smoke else context // 4
        )
        payload = {"messages": case["messages"], "max_tokens": budget}
        if case.get("tools"):
            payload["tools"] = case["tools"]
        result = server.request(payload)
        result.update(grade_result(result, case["rule"]))
        result.update(
            {
                "type": "capability",
                "test_id": case["id"],
                "category": case["category"],
                "test": case,
                "test_sha256": digest(case),
                "prompt_sha256": digest(case["messages"]),
                "context_size": context,
                "repeat": rep,
                "runtime_config": server.config.model_dump(),
            }
        )
        artifact.append(result)
        server.check()
