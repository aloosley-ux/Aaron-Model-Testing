from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path: Path, cancel=None) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Cancelled while hashing")
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
    # Windows readers briefly deny replacement while holding a file open.
    # Keep atomic writes, retry only that transient failure, and bound the wait.
    deadline = time.monotonic() + 1
    while True:
        try:
            temp.replace(path)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def command_text(argv: list[str]) -> str:
    # Display form for cmd.exe; execution ALWAYS uses an argv array with shell=False.
    return subprocess.list2cmdline(argv)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def distribution_notices() -> dict[str, Path]:
    """Find redistributable notices in a checkout or an installed wheel."""
    from importlib.metadata import distribution

    names = (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "licenses/llama-gguf-tune-MIT.txt",
        "licenses/local_bench-MIT.txt",
        "licenses/llm-inference-benchmark-MIT.txt",
    )
    root = Path(__file__).resolve().parent.parent
    if (root / "pyproject.toml").is_file() and all((root / name).is_file() for name in names):
        return {name: root / name for name in names}
    package = distribution("aaron-model-testing")
    files = package.files or []
    return {
        name: Path(package.locate_file(next(f for f in files if str(f).endswith("/licenses/" + name))))
        for name in names
    }
