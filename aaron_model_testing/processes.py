"""Own-process lifecycle only. Windows Job Objects kill owned children on parent exit."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import threading
from ctypes import wintypes
from pathlib import Path

import psutil


class JobObject:
    def __init__(self, process, memory_limit=0):
        self.handle = None
        if os.name != "nt":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit:
            info.BasicLimitInformation.LimitFlags |= 0x100
            info.ProcessMemoryLimit = memory_limit
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(handle, wintypes.HANDLE(process._handle)):
            kernel.CloseHandle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        self.kernel, self.handle = kernel, handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OwnedProcess:
    def __init__(self, argv: list[str], log_path: Path, memory_limit=0):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self.log = log_path.open("wb")
        self.lock = threading.Lock()
        # Ignore inherited llama.cpp overrides: exact argv must describe the effective run.
        env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_")}
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                argv,
                stdout=self.log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                shell=False,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
            try:
                self.job = JobObject(self.process, memory_limit)
            except Exception:
                self.process.kill()
                self.process.wait(timeout=5)
                raise
        except Exception:
            self.log.close()
            raise

    def close(self):
        with self.lock:
            if self.log.closed:
                return
            if self.process.poll() is None:
                if os.name == "nt":
                    self.job.close()
                else:
                    import signal

                    os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.job.close()
            self.log.close()

    def tail(self):
        if not self.log.closed:
            self.log.flush()
        with self.log_path.open("rb") as f:
            f.seek(max(0, self.log_path.stat().st_size - 12000))
            return f.read().decode("utf-8", errors="replace")


def windows_gpu_sample(pid: int):
    if os.name != "nt":
        return None
    selector = f"pid_{int(pid)}_*"
    script = "$ErrorActionPreference='Stop'; [pscustomobject]@{ memory=@("
    script += "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUProcessMemory | "
    script += f"Where-Object {{$_.Name -like '{selector}'}} | Select-Object Name,DedicatedUsage,SharedUsage); engine=@("
    script += "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
    script += f"Where-Object {{$_.Name -like '{selector}'}} | Select-Object Name,UtilizationPercentage) "
    script += "} | ConvertTo-Json -Depth 4 -Compress"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            return None
        data = json.loads(result.stdout)
        if not data.get("memory"):
            return None
        return {
            "dedicated_bytes": sum(int(m["DedicatedUsage"]) for m in data["memory"]),
            "shared_bytes": sum(int(m["SharedUsage"]) for m in data["memory"]),
            "busiest_engine_percent": max(
                (int(e["UtilizationPercentage"]) for e in data.get("engine", [])), default=None
            ),
        }
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


class Telemetry:
    def __init__(self, pid: int, gpu_enabled=True):
        self.pid = pid
        self.samples = []
        self.gpu_samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.gpu_thread = (
            threading.Thread(target=self._sample_gpu, daemon=True)
            if gpu_enabled and os.name == "nt"
            else None
        )

    def start(self):
        self.thread.start()
        if self.gpu_thread:
            self.gpu_thread.start()

    def _sample_gpu(self):
        from .util import now

        while not self.stop_event.is_set():
            sample = windows_gpu_sample(self.pid)
            if sample:
                self.gpu_samples.append({"timestamp": now(), **sample})
            if self.stop_event.wait(2):
                break

    def _sample(self):
        import time

        process = psutil.Process(self.pid)
        process.cpu_percent()
        while not self.stop_event.wait(0.25):
            try:
                self.samples.append(
                    {
                        "elapsed_monotonic": time.monotonic(),
                        "rss_bytes": process.memory_info().rss,
                        "cpu_percent_all_cores": process.cpu_percent() / (psutil.cpu_count() or 1),
                        "system_available_bytes": psutil.virtual_memory().available,
                    }
                )
            except psutil.Error:
                break

    def finish(self):
        self.stop_event.set()
        self.thread.join(timeout=2)
        if self.gpu_thread:
            self.gpu_thread.join(timeout=11)
        return {
            "ram_peak_mb": max((s["rss_bytes"] / 2**20 for s in self.samples), default=None),
            "cpu_mean_percent": (
                sum(s["cpu_percent_all_cores"] for s in self.samples) / len(self.samples)
                if self.samples
                else None
            ),
            "vram_peak_mb": max((s["dedicated_bytes"] / 2**20 for s in self.gpu_samples), default=None),
            "gpu_utilisation_percent": max(
                (
                    s["busiest_engine_percent"]
                    for s in self.gpu_samples
                    if s["busiest_engine_percent"] is not None
                ),
                default=None,
            ),
            "gpu_telemetry_note": "Windows per-PID counters: sampled dedicated memory peak and busiest-engine utilisation. Sparse samples may miss peaks.",
            "samples": self.samples,
            "gpu_samples": self.gpu_samples,
        }
