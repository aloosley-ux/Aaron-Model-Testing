import json
import os
import sys
import threading
import time

import httpx
import psutil
import pytest

from aaron_model_testing.config import Settings
from aaron_model_testing.processes import OwnedProcess
from aaron_model_testing.profiles import RuntimeConfig
from aaron_model_testing.runtime import NativeServer, port_free, server_command


def test_command_is_argv_native_device_port_and_load_mode(tmp_path):
    config = RuntimeConfig(template="{{ messages }}", mmap=False)
    build = {
        "path": "C:/runtime with spaces/llama-server.exe",
        "help": "--load-mode --jinja --no-context-shift --offline --fit on --cache-ram --chat-template-file --log-verbosity",
    }
    argv = server_command(Settings(), {"path": "C:/models with spaces/a.gguf"}, config, build, tmp_path)
    assert argv[argv.index("--port") + 1] == "1235"
    assert argv[argv.index("--device") + 1] == "Vulkan0"
    assert argv[argv.index("--parallel") + 1] == "1"
    assert argv[argv.index("--load-mode") + 1] == "none"
    assert argv[argv.index("--log-verbosity") + 1] == "4"
    assert "1234" not in argv
    assert (tmp_path / "chat-template.jinja").read_text() == "{{ messages }}"
    with pytest.raises(ValueError):
        Settings(benchmark_port=1234)
    with pytest.raises(ValueError):
        RuntimeConfig(options={"--port": "1234"})
    with pytest.raises(ValueError):
        RuntimeConfig(ubatch_size=2048, batch_size=512)
    with pytest.raises(ValueError):
        port_free(1234)
    numeric = RuntimeConfig(options={"--n-cpu-moe": 1, "--rope-scale": 1.0})
    argv = server_command(
        Settings(),
        {"path": "model.gguf"},
        numeric,
        {**build, "help": build["help"] + " --n-cpu-moe --rope-scale"},
        tmp_path,
    )
    assert argv[argv.index("--n-cpu-moe") + 1] == "1"
    assert argv[argv.index("--rope-scale") + 1] == "1.0"
    with pytest.raises(ValueError):
        RuntimeConfig(options={"--n-cpu-moe": True})


def test_stream_counts_native_tokens_and_separates_thinking(tmp_path):
    build = {"path": "not-launched", "help": "--load-mode"}
    server = NativeServer(Settings(), {"path": "a.gguf"}, RuntimeConfig(), build, tmp_path, threading.Event())
    events = [
        {"choices": [{"delta": {"reasoning_content": "Let me think"}}]},
        {"choices": [{"delta": {"content": "READY"}}]},
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"completion_tokens": 8, "prompt_tokens": 32},
            "timings": {
                "prompt_n": 32,
                "predicted_n": 8,
                "prompt_per_second": 120,
                "predicted_per_second": 40,
            },
        },
    ]
    data = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
    server.client.close()
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data)),
    )
    result = server.request({"messages": [{"role": "user", "content": "test"}]})
    assert result["success"]
    assert result["response"] == "READY"
    assert result["reasoning"] == "Let me think"
    assert result["metrics"]["output_tokens"] == 8  # Not SSE chunk count (2).
    assert result["metrics"]["generation_tps"] == 40
    assert result["metrics"]["ttft_ms"] <= result["metrics"]["ttfa_ms"]
    server.close()


def test_failed_stream_keeps_partial_answer(tmp_path):
    server = NativeServer(
        Settings(),
        {"path": "a.gguf"},
        RuntimeConfig(),
        {"path": "unused", "help": "--load-mode"},
        tmp_path,
        threading.Event(),
    )
    data = 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\ndata: {"error":"OOM"}\n\n'
    server.client.close()
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data)),
    )
    result = server.request({})
    assert not result["success"] and result["response"] == "partial" and "OOM" in result["error"]
    server.close()


def test_malformed_native_stream_retains_previous_response_and_reports_harness_error(tmp_path):
    server = NativeServer(
        Settings(),
        {"path": "a.gguf"},
        RuntimeConfig(),
        {"path": "unused", "help": "--load-mode"},
        tmp_path,
        threading.Event(),
    )
    server.client.close()
    data = 'data: {"choices":[{"delta":{"content":"raw prefix"}}]}\n\ndata: bad-json\n\n'
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data)),
    )
    try:
        result = server.request({})
        assert result["response"] == "raw prefix" and not result["success"]
        assert result["error_kind"] == "parser_or_harness_error"
        assert result["metrics"]["output_tokens"] is None
    finally:
        server.close()


def test_missing_native_stop_reason_stays_unavailable_without_changing_success_contract(tmp_path):
    server = NativeServer(
        Settings(),
        {"path": "a.gguf"},
        RuntimeConfig(),
        {"path": "unused", "help": "--load-mode"},
        tmp_path,
        threading.Event(),
    )
    server.client.close()
    data = 'data: {"choices":[{"delta":{"content":"READY"}}],"usage":{"prompt_tokens":9,"completion_tokens":2}}\n\ndata: [DONE]\n\n'
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data)),
    )
    try:
        result = server.request({})
        assert result["success"] and result["finish_reason"] is None
        from aaron_model_testing.evidence import diagnose

        assert diagnose(result)["truncated"] is None
    finally:
        server.close()


@pytest.mark.parametrize(
    "failure,error_kind",
    [
        (TimeoutError("deadline"), "timeout"),
        (InterruptedError("cancelled"), "cancelled"),
        (ValueError("OOM"), "inference_error"),
    ],
)
def test_failed_stream_retains_native_counters_and_timing(tmp_path, failure, error_kind):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            yield b'data: {"usage":{"prompt_tokens":9,"completion_tokens":4,"completion_tokens_details":{"reasoning_tokens":0,"final_answer_tokens":4}},"timings":{"prompt_ms":2,"predicted_ms":6}}\n\n'
            raise failure

    server = NativeServer(
        Settings(),
        {"path": "a.gguf"},
        RuntimeConfig(),
        {"path": "unused", "help": "--load-mode"},
        tmp_path,
        threading.Event(),
    )
    server.client.close()
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=BrokenStream())),
    )
    try:
        result = server.request({})
        assert not result["success"] and result["error_kind"] == error_kind
        assert result["response"] == "partial" and len(result["events"]) == 2
        assert result["metrics"]["input_tokens"] == 9 and result["metrics"]["output_tokens"] == 4
        assert result["metrics"]["reasoning_tokens"] == 0 and result["metrics"]["final_answer_tokens"] == 4
        assert result["metrics"]["inference_duration_ms"] == 8
        assert result["metrics"]["latency_ms"] >= result["metrics"]["ttft_ms"]
    finally:
        server.close()


def test_reasoning_alias_embedded_content_and_streamed_native_tools(tmp_path):
    from aaron_model_testing.grading import grade_result

    server = NativeServer(
        Settings(),
        {"path": "a.gguf"},
        RuntimeConfig(),
        {"path": "unused", "help": "--load-mode"},
        tmp_path,
        threading.Event(),
    )
    events = [
        {"choices": [{"delta": {"reasoning": "native reasoning"}}]},
        {"choices": [{"delta": {"content": "<think>embedded</think>"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "call-1", "function": {"name": "lookup", "arguments": '{"x":'}}
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "2}"}}]},
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"completion_tokens": 10, "prompt_tokens": 30},
        },
    ]
    data = "".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n"
    server.client.close()
    server.client = httpx.Client(
        base_url="http://127.0.0.1:1235",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data)),
    )
    try:
        result = server.request({})
        assert result["reasoning"] == "native reasoning"
        assert result["response"] == "<think>embedded</think>" and result["events"] == events
        fields = grade_result(
            result, {"type": "tool", "name": "lookup", "schema": {"type": "object"}, "arguments": {"x": 2}}
        )
        assert fields["grade"]["passed"]
        assert fields["reasoning"] == "native reasoning"
        assert result["tool_calls"][0]["function"]["arguments"] == '{"x":2}'
    finally:
        server.close()


def test_own_process_cleanup_and_no_global_kill(tmp_path, monkeypatch):
    monkeypatch.setenv("LLAMA_ARG_PORT", "1234")
    script = tmp_path / "owned.py"
    pidfile = tmp_path / "pid.txt"
    script.write_text(
        "import os,sys,time,subprocess\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        "Path(sys.argv[1]).write_text(str(child.pid)+'|'+os.getenv('LLAMA_ARG_PORT','clean'))\n"
        "time.sleep(60)\n"
    )
    process = OwnedProcess([sys.executable, str(script), str(pidfile)], tmp_path / "process.log")
    try:
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        child, env = pidfile.read_text().split("|")
        assert env == "clean"
        child = int(child)
    finally:
        process.close()
    process.close()  # Idempotent cancellation/shutdown.
    assert process.process.poll() is not None
    if os.name == "nt":
        deadline = time.monotonic() + 3
        while psutil.pid_exists(child) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(child)


@pytest.mark.skipif(os.name != "nt", reason="Windows driver counter adapter")
def test_driver_counters_keep_memory_and_engine_units(monkeypatch):
    from types import SimpleNamespace

    from aaron_model_testing import processes

    captured = []

    def run(argv, **kwargs):
        captured.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "memory": [
                        {"DedicatedUsage": 2**30, "SharedUsage": 1024},
                        {"DedicatedUsage": 2**20, "SharedUsage": 0},
                    ],
                    "engine": [{"UtilizationPercentage": 17}, {"UtilizationPercentage": 44}],
                }
            ),
        )

    monkeypatch.setattr(processes.subprocess, "run", run)
    result = processes.windows_gpu_sample(123)
    assert result["dedicated_bytes"] == 2**30 + 2**20
    assert result["busiest_engine_percent"] == 44
    assert "pid_123_*" in captured[0][-1]
    assert "1234" not in captured[0][-1]
