# RX 9060 XT acceleration verification

Verified on 2026-10-01 through the application's benchmark path, not an attached inference service. Verdict: **the tested Qwen3.5-2B profile uses the discrete RX 9060 XT through Vulkan with all 25 runtime-reported layers offloaded.** No GPU-selection or inference configuration fix was needed. A small logging fix was required to make effective offload inspectable.

## Same real workload before and after the logging fix

| Evidence | Before | After |
| --- | --- | --- |
| Durable run ID | `d6f520e338f0498190817b51a11c1c69` | `b38f55ea2a2844beaaa0b9ab3b99b51d` |
| Device argument | `--device Vulkan0` | Same |
| Offload argument | `-ngl 999` | Same |
| Logging | Runtime default verbosity 3 | Explicit `--log-verbosity 4` |
| Effective device/offload lines | Hidden by runtime log threshold | RX 9060 XT; `offloaded 25/25 layers to GPU` |
| Median prompt processing | 6,138.43 tok/s | 6,237.75 tok/s |
| Median generation | 140.60 tok/s | 144.69 tok/s |
| Dedicated VRAM sampled peak | 1,404.00 MiB | 1,404.00 MiB |
| Process CPU lifecycle mean, all 12 logical cores | 5.18% | 5.21% |

Both runs used three independent **3,072-input / 512-output token** workloads, a 4,096-token context, one inference lane, seed 42, temperature 0, no prompt reuse and the same configuration hash `2faf462f5aa9d5eaafa5553a72d146c1a5793b80d93af9591c1008fbff4b1553`. Differences in timings are ordinary run variation, not evidence that the logging change improves inference.

The exact cause of the missing evidence was this build's log callback: library INFO maps to verbosity 4, while the server defaults to 3. See the [matching llama.cpp source](https://github.com/ggml-org/llama.cpp/blob/c57da6fd8/common/log.cpp#L496). The only application change was adding verbosity 4 when advertised by the selected binary's help. Scored benchmark definitions were unchanged.

## Runtime identity and effective configuration

Native `llama-server.exe`, version `0.4.1-dev`, build **11015**, commit **c57da6fd8**, Clang 20.1.8, Windows x86_64. Model: `Qwen3.5-2B-Q4_K_M.gguf`, SHA256 `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223`.

Native enumeration distinguishes:

```text
Vulkan0: AMD Radeon RX 9060 XT (16304 MiB, 15416 MiB free)
Vulkan1: AMD Radeon(TM) Graphics (16180 MiB, 15371 MiB free)
```

The actual server log then records:

```text
llama_prepare_model_devices: using device Vulkan0 (AMD Radeon RX 9060 XT) (unknown id) - 15416 MiB free
load_tensors: offloaded 25/25 layers to GPU
load_tensors: Vulkan0 model buffer size = 1211.05 MiB
llama_context: flash_attn = enabled
llama_kv_cache: Vulkan0 KV buffer size = 48.00 MiB
llama_memory_recurrent: Vulkan0 RS buffer size = 19.27 MiB
sched_reserve: Vulkan0 compute buffer size = 52.02 MiB
```

Device identity comes from llama.cpp's device name and selected backend, not Task Manager adapter numbering. The runtime supplies `unknown id` for its optional hardware identifier; the recorded backend index is **Vulkan0**. Vulkan1 is enumerated but is not selected and has no model/KV/compute allocations in this run.

The archived command includes these arguments, following the exact binary and model paths preserved in the manifest:

```text
--host 127.0.0.1 --port 1235 --parallel 1 --device Vulkan0 -ngl 999
-t 6 -tb 6 -b 1024 -ub 512 -c 4096 -ctk f16 -ctv f16 -fa on
--load-mode mmap --jinja --no-context-shift --offline --fit off
--cache-ram 0 --log-verbosity 4
```

The log also records 397.85 MiB of CPU-mapped model data and small Vulkan host buffers. Full layer offload does not eliminate host mappings, input handling, sampling or HTTP work. The effective 25/25 offload, Vulkan0 allocations, low measured CPU use and sustained GPU activity support GPU inference; the presence of a CPU-mapped buffer alone does not indicate CPU-heavy inference.

## Measurements and telemetry agreement

| Measurement from the after run | Observed value |
| --- | --- |
| Before launch | No benchmark process; Vulkan reports 15,416 MiB free on the discrete device |
| Early startup per-PID dedicated allocation | 6.60 MiB |
| Later load/warmup observation | 1,375.65 MiB; query spans startup phases |
| During inference per-PID dedicated allocation | 1,404.00 MiB, independently queried and reported by the app |
| During inference shared allocation | 15.14 MiB |
| App GPU busiest-engine samples | 79%, 49%, 79%, 80%, 79% after startup |
| Independently queried GPU busiest-engine samples during inference | Usually 78–80%; one 97% sample |
| CPU lifecycle mean | 5.21% of 12 logical cores, about 0.63 core equivalent |
| Process RAM peak | 1,464.05 MiB |
| Startup to healthy | 1,406.19 ms; one observation in this focused check |
| Prompt tok/s, median / min / max | 6,237.75 / 6,181.94 / 6,278.23 |
| Generation tok/s, median / min / max | 144.69 / 144.64 / 144.92 |
| Streamed TTFT median | 494.01 ms |
| Request latency median | 4,025.99 ms |
| Successful performance requests | 3/3; exact native counts 3,072 and 512 each time |

The app and independent Windows driver queries filter the owned inference PID **27080**. The app's 80% sampled engine peak is consistent with the separate samples; differing query times explain the separate 97% observation. These are sparse **per-process busiest-engine counters**, not whole-device occupancy or continuously measured peaks. CPU measurements include load, warmup and inference. Additional device-enumeration and driver queries ran alongside this verification, so these timings are diagnostic evidence rather than a clean publication measurement. The runtime's enumerated free-memory value did not update during the probe; it should not be used to calculate a live VRAM delta. Dedicated driver counters provide the useful allocation evidence.

No fallback, allocation failure, Flash Attention fallback or partial-offload warning appeared. The log contains unrelated CORS/no-key and disabled idle-slot-cache warnings, and notes that the requested context is below the model's training context. None indicates a GPU fallback.

## Durable evidence and isolation

Local evidence, deliberately excluded from Git:

- `.local/hardware-verification.json`: before/after listener ownership, independent counters, exact command, native identity lines and same-run metrics.
- `.local/artifacts/b38f55ea2a2844beaaa0b9ab3b99b51d/`: manifest, native server log, raw responses, startup settings, telemetry samples, runtime/build/DLL hashes, source snapshots and checksums.
- The before run remains under `.local/artifacts/d6f520e338f0498190817b51a11c1c69/`.

Artifact verification passed for all **35 files** in the after run. Port 1235 was released after both runs. Cortana's listener on port 1234 remained PID **4960**; verification made no requests to that listener. This proves acceleration for the tested model/profile/build, not full offload feasibility for every larger model.
