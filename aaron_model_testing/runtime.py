from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

from . import __version__
from .config import Settings
from .evidence import native_metrics
from .processes import OwnedProcess, Telemetry
from .profiles import RuntimeConfig
from .util import command_text, digest, file_hash, write_json


def probe(binary: str) -> dict:
    path = Path(binary).resolve()
    if not path.is_file():
        raise ValueError("Set the path to an existing native llama.cpp binary in Settings")
    output = {}
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_")}
    for key, flag in [("version", "--version"), ("help", "--help"), ("devices", "--list-devices")]:
        result = subprocess.run(
            [str(path), flag],
            capture_output=True,
            timeout=20,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output[key] = result.stdout + result.stderr
        if result.returncode:
            raise ValueError(f"Runtime probe {flag} failed: {output[key][-2000:]}")
    output.update(
        {
            "path": str(path),
            "sha256": file_hash(path),
            "dlls": [{"name": p.name, "sha256": file_hash(p)} for p in sorted(path.parent.glob("*.dll"))],
        }
    )
    return output


def environment() -> dict:
    data = {
        "app_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "ram_bytes": psutil.virtual_memory().total,
        "available_ram_bytes": psutil.virtual_memory().available,
        "measurement": "one owned inference lane; warm OS file cache; prompt cache disabled",
        "gpu": [],
        "gpu_environment": {
            k: v
            for k, v in os.environ.items()
            if k.startswith(("GGML_VK_", "OMP_", "KMP_")) or k in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES")
        },
    }
    if os.name == "nt":
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json",
                ],
                capture_output=True,
                timeout=15,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            data["gpu"] = json.loads(r.stdout) if r.returncode == 0 else []
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    try:
        data["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], timeout=5, text=True
        ).strip()
        data["git_dirty"] = bool(
            subprocess.check_output(["git", "status", "--porcelain"], timeout=5, text=True)
        )
    except (OSError, subprocess.SubprocessError):
        data["git_commit"] = None
    # Stable fingerprint excludes free memory and git dirty status.
    data["fingerprint"] = digest(
        {k: data[k] for k in ("platform", "cpu", "logical_cpus", "ram_bytes", "gpu")}
    )
    return data


def port_free(port=1235):
    if port != 1235:
        raise ValueError("Only dedicated benchmark port 1235 is allowed")
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                "Benchmark port 1235 is occupied; no existing process will be stopped"
            ) from exc


def server_command(settings: Settings, model: dict, config: RuntimeConfig, build: dict, work: Path):
    help_text = build["help"]
    argv = [
        build["path"],
        "-m",
        model["path"],
        "--host",
        "127.0.0.1",
        "--port",
        "1235",
        "--parallel",
        "1",
        "--device",
        settings.device,
        "-ngl",
        str(config.gpu_layers),
        "-t",
        str(config.threads),
        "-tb",
        str(config.batch_threads),
        "-b",
        str(config.batch_size),
        "-ub",
        str(config.ubatch_size),
        "-c",
        str(config.ctx_size),
        "-ctk",
        config.cache_type_k,
        "-ctv",
        config.cache_type_v,
        "-fa",
        "on" if config.flash_attn else "off",
    ]
    if "--load-mode" in help_text:
        argv.extend(["--load-mode", "mmap" if config.mmap else "none"])
    elif "--no-mmap" in help_text:
        argv.append("--mmap" if config.mmap else "--no-mmap")
    else:
        raise ValueError("This runtime does not advertise a supported mmap/load-mode control")
    for flag in ("--jinja", "--no-context-shift", "--offline"):
        if flag in help_text:
            argv.append(flag)
    if "--fit " in help_text:
        argv.extend(["--fit", "off"])
    if "--cache-ram" in help_text:
        argv.extend(["--cache-ram", "0"])
    # Current llama.cpp routes library device/offload INFO through verbosity 4.
    # Keep that evidence in every run rather than relying on requested flags alone.
    if "--log-verbosity" in help_text:
        argv.extend(["--log-verbosity", "4"])
    for flag, value in config.options.items():
        if flag not in help_text:
            raise ValueError(f"This build does not support {flag}")
        argv.append(flag)
        if value is not None and value is not True:
            argv.append(str(value))
    if config.template is not None:
        if "--chat-template-file" not in help_text:
            raise ValueError("Runtime does not support external Jinja templates")
        work.mkdir(parents=True, exist_ok=True)
        path = work / "chat-template.jinja"
        path.write_text(config.template, encoding="utf-8")
        argv.extend(["--chat-template-file", str(path.resolve())])
    return argv


class NativeServer:
    def __init__(self, settings, model, config, build, work, cancel: threading.Event):
        self.settings, self.config, self.cancel = settings, config, cancel
        self.argv = server_command(settings, model, config, build, work)
        self.command = command_text(self.argv)
        self.client = httpx.Client(
            base_url="http://127.0.0.1:1235", timeout=settings.request_timeout, trust_env=False
        )
        self.owned = None
        self.telemetry = None
        self.resources = None
        self.work = work
        self.load_ms = None
        self.process_memory_limit = None

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError("Benchmark cancelled")
        if self.owned and self.owned.process.poll() is not None:
            raise RuntimeError("llama-server exited: " + self.owned.tail()[-4000:])

    def start(self):
        self.check()
        port_free()
        start = time.perf_counter()
        memory = psutil.virtual_memory()
        self.process_memory_limit = int(min(memory.total * 0.85, max(512 * 2**20, memory.available * 0.9)))
        write_json(
            self.work / "startup.json",
            {
                "memory_limit_bytes": self.process_memory_limit,
                "available_ram_bytes": memory.available,
                "gpu_telemetry": self.settings.gpu_telemetry,
                "removed_inherited_environment_prefix": "LLAMA_",
            },
        )
        self.owned = OwnedProcess(
            self.argv,
            self.work / "server.log",
            memory_limit=self.process_memory_limit,
        )
        self.telemetry = Telemetry(self.owned.process.pid, gpu_enabled=self.settings.gpu_telemetry)
        self.telemetry.start()
        deadline = time.monotonic() + self.settings.startup_timeout
        try:
            while time.monotonic() < deadline:
                self.check()
                try:
                    response = self.client.get("/health", timeout=1)
                    if response.status_code == 200 and response.json().get("status") == "ok":
                        # Never benchmark a process other than the one we launched (bind-race protection).
                        owners = {
                            c.pid
                            for c in psutil.net_connections(kind="tcp")
                            if c.laddr and c.laddr.port == 1235 and c.status == psutil.CONN_LISTEN
                        }
                        if self.owned.process.pid not in owners:
                            raise RuntimeError("Port 1235 belongs to another process")
                        self.load_ms = (time.perf_counter() - start) * 1000
                        return self
                except (httpx.HTTPError, ValueError):
                    pass
                self.cancel.wait(0.2)
            raise TimeoutError("llama-server did not become healthy: " + self.owned.tail()[-4000:])
        except Exception:
            self.close()
            raise

    def close(self):
        if self.owned:
            self.owned.close()
        if self.telemetry and self.resources is None:
            self.resources = self.telemetry.finish()
        # Closing the HTTP client occurs in the worker; cancellation closes the owned process only.
        self.client.close()

    def tokenize(self, text: str) -> list[int]:
        self.check()
        r = self.client.post("/tokenize", json={"content": text, "add_special": False})
        r.raise_for_status()
        return r.json()["tokens"]

    def render(self, messages, tools=None) -> str:
        body = {"messages": messages, **self.config.sampling.request_args()}
        if tools:
            body["tools"] = tools
        response = self.client.post("/apply-template", json=body)
        response.raise_for_status()
        return response.json()["prompt"]

    def request(self, payload: dict, chat=True) -> dict:
        self.check()
        body = {**self.config.sampling.request_args(), **payload, "stream": True, "cache_prompt": False}
        if chat:
            body["stream_options"] = {"include_usage": True}
        text, reasoning, events = [], [], []
        tool_calls = {}
        first, answer_first = None, None
        usage, timings, finish_reason = {}, {}, None
        start = time.perf_counter()
        deadline = time.monotonic() + self.settings.request_timeout
        error, error_kind = None, None
        try:
            with self.client.stream(
                "POST", "/v1/chat/completions" if chat else "/completion", json=body
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    self.check()
                    if time.monotonic() > deadline:
                        raise TimeoutError("Total request deadline exceeded")
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    events.append(event)
                    if "error" in event:
                        raise RuntimeError(str(event["error"]))
                    elapsed = (time.perf_counter() - start) * 1000
                    delta = (event.get("choices") or [{}])[0].get("delta", {}) if chat else event
                    content = delta.get("content") or ""
                    thought = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    if not isinstance(content, str) or not isinstance(thought, str):
                        raise TypeError("Non-string content in native stream")
                    if content or thought or delta.get("tool_calls"):
                        first = elapsed if first is None else first
                    if content or delta.get("tool_calls"):
                        answer_first = elapsed if answer_first is None else answer_first
                    if content:
                        text.append(content)
                    reasoning.append(thought)
                    for call in delta.get("tool_calls", []):
                        index = call.get("index", 0)
                        target = tool_calls.setdefault(
                            index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        if call.get("id"):
                            target["id"] = call["id"]
                        for key in ("name", "arguments"):
                            target["function"][key] += call.get("function", {}).get(key, "")
                    if event.get("usage"):
                        usage.update(event["usage"])
                    if event.get("timings"):
                        timings.update(event["timings"])
                    finish_reason = (event.get("choices") or [{}])[0].get("finish_reason") or finish_reason
                    if not chat and event.get("stop"):
                        finish_reason = "length" if event.get("stopped_limit") else "stop"
        except Exception as exc:
            # Preserve counters, stop state and timings already received, including on cancellation.
            error = str(exc)
            error_kind = (
                "cancelled"
                if self.cancel.is_set() or isinstance(exc, InterruptedError)
                else "timeout"
                if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                else "parser_or_harness_error"
                if isinstance(exc, (json.JSONDecodeError, TypeError, KeyError, AttributeError))
                else "inference_error"
            )
        counts = native_metrics(usage, timings)
        predicted = counts["output_tokens"]
        success = bool(error is None and predicted and (text or reasoning or tool_calls))
        if error is None and not success:
            error = "No server token count returned" if predicted is None else "Empty response"
            error_kind = "inference_error"
        # Native timing is decode throughput. Never count SSE chunks as tokens.
        return {
            "response": "".join(text),
            "reasoning": "".join(reasoning),
            "events": events,
            "request": body,
            "tool_calls": list(tool_calls.values()),
            "usage": usage,
            "native_timings": timings,
            "metrics": {
                **counts,
                "generation_tps": timings.get("predicted_per_second"),
                "prompt_tps": timings.get("prompt_per_second"),
                "ttft_ms": first,
                "ttfa_ms": answer_first,
                "latency_ms": (time.perf_counter() - start) * 1000,
            },
            "finish_reason": finish_reason,
            "success": success,
            "error": error,
            "error_kind": error_kind,
        }


def allocations(log: str):
    """Allocated backend buffers are useful, but not a measured driver VRAM peak."""
    values = re.findall(r"Vulkan\d+.*?buffer size\s*=\s*([\d.]+)\s*MiB", log)
    return sum(float(v) for v in values) if values else None
