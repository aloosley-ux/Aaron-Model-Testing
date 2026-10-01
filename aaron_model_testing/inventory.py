from __future__ import annotations

import gc
import math
import re
from pathlib import Path

from gguf import GGUFReader

from .util import digest, file_hash, now


def json_metadata(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite_float": str(value)}
    if isinstance(value, list):
        return [json_metadata(v) for v in value]
    if isinstance(value, dict):
        return {k: json_metadata(v) for k, v in value.items()}
    return value


def discover(roots: list[str]) -> list[Path]:
    found = set()
    for root in roots:
        path = Path(root).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Model directory/file does not exist: {path}")
        if path.is_file():
            if path.suffix.lower() != ".gguf":
                raise ValueError(f"Not a GGUF: {path}")
            found.add(path)
        else:
            found.update(p.resolve() for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".gguf")
    return sorted(found, key=lambda p: str(p).lower())


def shards(path: Path) -> list[Path]:
    match = re.match(r"(.+)-\d{5}-of-(\d{5})\.gguf$", path.name, re.I)
    if not match:
        return [path]
    count = int(match[2])
    if count > 1000:
        raise ValueError("Invalid split count")
    paths = [path.with_name(f"{match[1]}-{i:05d}-of-{count:05d}.gguf") for i in range(1, count + 1)]
    if not all(p.is_file() for p in paths):
        raise ValueError("Split model is incomplete; all shards are required")
    return paths


def metadata(path: Path) -> tuple[dict, int]:
    # Official llama.cpp GGUF reader; mmap reads headers/tensor dimensions, never loads weights.
    reader = GGUFReader(str(path), "r")
    values = {}
    try:
        for name, field in reader.fields.items():
            if name.startswith("GGUF."):
                continue
            values[name] = json_metadata(field.contents())
        parameters = sum(int(t.n_elements) for t in reader.tensors)
        return values, parameters
    finally:
        del reader
        gc.collect()


def register(path: Path, cancel=None) -> dict:
    parts = shards(path)
    path = parts[0]
    hashes = []
    values, parameters = metadata(path)
    for part in parts:
        stat = part.stat()
        hashes.append(
            {
                "path": str(part),
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": file_hash(part, cancel),
            }
        )
        if part != path:
            _, n = metadata(part)
            parameters += n
        after = part.stat()
        if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
            raise ValueError(f"Model changed while hashing: {part}")
    architecture = values.get("general.architecture", "unknown")
    quant = re.search(r"(?i)(UD-)?(?:IQ\d_[A-Z0-9_]+|Q\d_[A-Z0-9_]+|PQ\d_\d|BF16|F16|F32)", path.stem)
    template = values.get("tokenizer.chat_template")
    external = next(
        (p for p in [path.with_suffix(".jinja"), path.parent / "chat_template.jinja"] if p.exists()), None
    )
    auxiliary = "mmproj" in path.name.lower() or architecture in ("clip", "bert", "nomic-bert")
    fingerprint = hashes[0]["sha256"] if len(parts) == 1 else digest([h["sha256"] for h in hashes])
    return {
        "id": digest(str(path).lower())[:24],
        "name": values.get("general.name", path.stem),
        "path": str(path),
        "filename": path.name,
        "sha256": fingerprint,
        "hash_kind": "sha256" if len(parts) == 1 else "sha256-of-shard-hash-json",
        "files": hashes,
        "size_bytes": sum(h["size_bytes"] for h in hashes),
        "architecture": architecture,
        "parameter_count": parameters or values.get("general.parameter_count"),
        "quantisation": quant[0] if quant else str(values.get("general.file_type", "unknown")),
        "context_capability": values.get(f"{architecture}.context_length"),
        "metadata": values,
        "chat_template": template,
        "external_template_path": str(external) if external else None,
        "source": values.get("general.source.url") or values.get("general.source.huggingface.repository"),
        "notes": "",
        "status": "auxiliary" if auxiliary else "ready",
        "registered_at": now(),
    }


def verify_model(model: dict, cancel=None):
    for part in model["files"]:
        path = Path(part["path"])
        if (
            not path.is_file()
            or path.stat().st_size != part["size_bytes"]
            or file_hash(path, cancel) != part["sha256"]
        ):
            raise ValueError(f"Model fingerprint changed; rescan before running: {path}")
