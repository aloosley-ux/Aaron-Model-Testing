from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .util import read_json, write_json


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_binary: str = ""
    bench_binary: str = ""
    model_directories: list[str] = Field(default_factory=list)
    device: str = "Vulkan0"
    benchmark_port: int = 1235
    startup_timeout: int = Field(default=180, ge=10, le=900)
    request_timeout: int = Field(default=180, ge=5, le=1800)
    gpu_telemetry: bool = True

    @field_validator("benchmark_port")
    @classmethod
    def dedicated_port(cls, value):
        if value != 1235:
            raise ValueError("The dedicated benchmark port is fixed at 1235; production 1234 is prohibited")
        return value

    @field_validator("device")
    @classmethod
    def vulkan_device(cls, value):
        if not value.startswith("Vulkan") or not value[6:].isdigit():
            raise ValueError("Select a single Vulkan device, for example Vulkan0")
        return value


def data_home() -> Path:
    return Path(os.environ.get("AMT_DATA_DIR", str(Path.cwd() / ".local"))).resolve()


def load_settings(home: Path) -> Settings:
    path = home / "settings.json"
    if path.exists():
        return Settings.model_validate(read_json(path))
    directories = [Path.home() / ".lmstudio" / "models", Path.home() / "AI" / "Models", Path.cwd() / "models"]
    settings = Settings(
        server_binary=shutil.which("llama-server.exe") or shutil.which("llama-server") or "",
        bench_binary=shutil.which("llama-bench.exe") or shutil.which("llama-bench") or "",
        model_directories=[str(p) for p in directories if p.is_dir()],
    )
    write_json(path, settings.model_dump())
    return settings
