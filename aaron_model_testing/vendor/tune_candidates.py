# Vendored MIT code. See THIRD_PARTY_NOTICES.md and licenses/.
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Literal

CandidateKind = Literal["bench", "server"]
PresetName = Literal["quick", "standard", "thorough"]


@dataclass(frozen=True)
class Candidate:
    threads: int
    batch_threads: int
    batch_size: int
    ubatch_size: int
    flash_attn: bool
    mmap: bool
    ctx_size: int
    cache_type_k: str
    cache_type_v: str

    def bench_args(self) -> list[str]:
        return [
            "-t",
            str(self.threads),
            "-b",
            str(self.batch_size),
            "-ub",
            str(self.ubatch_size),
            "-fa",
            "1" if self.flash_attn else "0",
            "-mmp",
            "1" if self.mmap else "0",
            "-ctk",
            self.cache_type_k,
            "-ctv",
            self.cache_type_v,
        ]

    def server_args(self) -> list[str]:
        args = [
            "-t",
            str(self.threads),
            "-tb",
            str(self.batch_threads),
            "-b",
            str(self.batch_size),
            "-ub",
            str(self.ubatch_size),
            "-fa",
            "on" if self.flash_attn else "off",
            "-c",
            str(self.ctx_size),
            "-ctk",
            self.cache_type_k,
            "-ctv",
            self.cache_type_v,
        ]
        args.append("--mmap" if self.mmap else "--no-mmap")
        return args

    def runtime_args(self, kind: CandidateKind) -> list[str]:
        if kind == "bench":
            return self.bench_args()
        if kind == "server":
            return self.server_args()
        raise ValueError(f"unknown candidate kind: {kind}")

    def as_dict(self) -> dict[str, object]:
        return {
            "threads": self.threads,
            "batch_threads": self.batch_threads,
            "batch_size": self.batch_size,
            "ubatch_size": self.ubatch_size,
            "flash_attn": self.flash_attn,
            "mmap": self.mmap,
            "ctx_size": self.ctx_size,
            "cache_type_k": self.cache_type_k,
            "cache_type_v": self.cache_type_v,
        }


@dataclass(frozen=True)
class CandidatePreset:
    name: PresetName
    thread_options: list[int]
    batch_thread_options: list[int]
    batch_sizes: list[int]
    ubatch_sizes: list[int]
    flash_attn_options: list[bool]
    mmap_options: list[bool]
    ctx_sizes: list[int]
    cache_type_pairs: list[tuple[str, str]]


def preset_names() -> tuple[PresetName, ...]:
    return ("quick", "standard", "thorough")


def default_candidates(logical_cpus: int) -> list[Candidate]:
    """Build the standard candidate matrix."""
    return build_candidates(logical_cpus, preset="standard")


def build_candidates(logical_cpus: int, *, preset: PresetName = "standard") -> list[Candidate]:
    """Build an ordered runtime-flag candidate matrix for a tuning depth."""
    candidate_preset = build_preset(logical_cpus, preset)
    candidates: list[Candidate] = []

    for threads, batch_threads, batch_size, ubatch_size, flash_attn, mmap, ctx_size, cache_types in product(
        candidate_preset.thread_options,
        candidate_preset.batch_thread_options,
        candidate_preset.batch_sizes,
        candidate_preset.ubatch_sizes,
        candidate_preset.flash_attn_options,
        candidate_preset.mmap_options,
        candidate_preset.ctx_sizes,
        candidate_preset.cache_type_pairs,
    ):
        if ubatch_size > batch_size:
            continue
        cache_type_k, cache_type_v = cache_types
        candidates.append(
            Candidate(
                threads=threads,
                batch_threads=batch_threads,
                batch_size=batch_size,
                ubatch_size=ubatch_size,
                flash_attn=flash_attn,
                mmap=mmap,
                ctx_size=ctx_size,
                cache_type_k=cache_type_k,
                cache_type_v=cache_type_v,
            )
        )

    return candidates


def select_candidates(logical_cpus: int, *, preset: PresetName, kind: CandidateKind, limit: int) -> list[Candidate]:
    if limit < 1:
        raise RuntimeError("--limit must be at least 1")

    selected: list[Candidate] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in build_candidates(logical_cpus, preset=preset):
        key = tuple(candidate.runtime_args(kind))
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def candidate_from_dict(payload: dict[str, object]) -> Candidate:
    try:
        return Candidate(
            threads=positive_int(payload["threads"], "threads"),
            batch_threads=positive_int(payload["batch_threads"], "batch_threads"),
            batch_size=positive_int(payload["batch_size"], "batch_size"),
            ubatch_size=positive_int(payload["ubatch_size"], "ubatch_size"),
            flash_attn=bool(payload["flash_attn"]),
            mmap=bool(payload["mmap"]),
            ctx_size=positive_int(payload["ctx_size"], "ctx_size"),
            cache_type_k=string_value(payload["cache_type_k"], "cache_type_k"),
            cache_type_v=string_value(payload["cache_type_v"], "cache_type_v"),
        )
    except KeyError as exc:
        raise RuntimeError(f"profile candidate is missing {exc.args[0]}") from exc


def drill_candidates(seed: Candidate, logical_cpus: int, *, limit: int) -> list[Candidate]:
    """Build a nearest-neighbor server tuning pass around a known-good candidate."""
    if limit < 1:
        raise RuntimeError("--limit must be at least 1")

    options: list[Candidate] = [seed]
    options.append(replace_candidate(seed, flash_attn=not seed.flash_attn))

    for threads in nearby_thread_values(seed.threads, logical_cpus):
        options.append(replace_candidate(seed, threads=threads, batch_threads=min(seed.batch_threads, threads)))
        options.append(replace_candidate(seed, threads=threads, batch_threads=threads))

    for batch_threads in nearby_thread_values(seed.batch_threads, logical_cpus):
        options.append(replace_candidate(seed, batch_threads=batch_threads))

    for batch_size in nearby_batch_values(seed.batch_size):
        options.append(replace_candidate(seed, batch_size=batch_size, ubatch_size=min(seed.ubatch_size, batch_size)))

    for ubatch_size in nearby_ubatch_values(seed.ubatch_size):
        if ubatch_size <= seed.batch_size:
            options.append(replace_candidate(seed, ubatch_size=ubatch_size))

    for batch_size in nearby_batch_values(seed.batch_size):
        for ubatch_size in nearby_ubatch_values(seed.ubatch_size):
            if ubatch_size <= batch_size:
                options.append(replace_candidate(seed, batch_size=batch_size, ubatch_size=ubatch_size))

    options.append(replace_candidate(seed, mmap=not seed.mmap))

    for ctx_size in nearby_context_values(seed.ctx_size):
        options.append(replace_candidate(seed, ctx_size=ctx_size))

    for cache_type_k, cache_type_v in nearby_cache_type_pairs(seed.cache_type_k, seed.cache_type_v):
        options.append(replace_candidate(seed, cache_type_k=cache_type_k, cache_type_v=cache_type_v))

    return dedupe_candidates(options)[:limit]


def replace_candidate(seed: Candidate, **changes: object) -> Candidate:
    values = seed.as_dict()
    values.update(changes)
    return candidate_from_dict(values)


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    selected: list[Candidate] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        if candidate.ubatch_size > candidate.batch_size:
            continue
        key = tuple(candidate.server_args())
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
    return selected


def nearby_thread_values(value: int, logical_cpus: int) -> list[int]:
    step = max(1, logical_cpus // 6)
    return unique(
        [
            value,
            max(1, value - step),
            min(logical_cpus, value + step),
            max(1, logical_cpus // 3),
            max(1, logical_cpus // 2),
            max(1, (logical_cpus * 2) // 3),
            logical_cpus,
        ]
    )


def nearby_batch_values(value: int) -> list[int]:
    return unique([value, 512, 1024, 2048, 4096])


def nearby_ubatch_values(value: int) -> list[int]:
    return unique([value, 128, 256, 512, 1024])


def nearby_context_values(value: int) -> list[int]:
    return unique([value, 2048, 4096, 8192, 16384])


def nearby_cache_type_pairs(cache_type_k: str, cache_type_v: str) -> list[tuple[str, str]]:
    return unique_pairs([(cache_type_k, cache_type_v), ("f16", "f16"), ("q8_0", "q8_0")])


def positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or value < 1:
        raise RuntimeError(f"profile candidate has invalid {name}: {value!r}")
    return value


def string_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"profile candidate has invalid {name}: {value!r}")
    return value


def build_preset(logical_cpus: int, preset: PresetName) -> CandidatePreset:
    half = max(1, logical_cpus // 2)
    third = max(1, logical_cpus // 3)
    two_thirds = max(1, (logical_cpus * 2) // 3)
    three_quarters = max(1, (logical_cpus * 3) // 4)

    if preset == "quick":
        return CandidatePreset(
            name=preset,
            thread_options=unique([half, logical_cpus]),
            batch_thread_options=unique([half]),
            batch_sizes=[1024, 512],
            ubatch_sizes=[512, 256],
            flash_attn_options=[True, False],
            mmap_options=[True],
            ctx_sizes=[4096],
            cache_type_pairs=[("f16", "f16")],
        )
    if preset == "standard":
        return CandidatePreset(
            name=preset,
            thread_options=unique([half, third, logical_cpus]),
            batch_thread_options=unique([half, third]),
            batch_sizes=[1024, 512, 2048],
            ubatch_sizes=[512, 256, 128],
            flash_attn_options=[True, False],
            mmap_options=[True],
            ctx_sizes=[4096],
            cache_type_pairs=[("f16", "f16")],
        )
    if preset == "thorough":
        return CandidatePreset(
            name=preset,
            thread_options=unique([half, two_thirds, three_quarters, third, logical_cpus]),
            batch_thread_options=unique([half, two_thirds, third]),
            batch_sizes=[1024, 512, 2048, 4096],
            ubatch_sizes=[512, 256, 1024, 128],
            flash_attn_options=[True, False],
            mmap_options=[True, False],
            ctx_sizes=[4096, 8192],
            cache_type_pairs=[("f16", "f16"), ("q8_0", "q8_0")],
        )
    raise ValueError(f"unknown preset: {preset}")


def unique(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def unique_pairs(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
