from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sampling(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float = Field(default=0, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    top_k: int = Field(default=0, ge=0, le=1000)
    min_p: float = Field(default=0, ge=0, le=1)
    repeat_penalty: float = Field(default=1, ge=0.5, le=2)
    seed: int = Field(default=42, ge=0, le=2147483647)
    enable_thinking: bool | None = False
    token_budget: int = Field(default=1024, ge=64, le=16384)

    def request_args(self):
        data = self.model_dump(exclude={"enable_thinking", "token_budget"})
        if self.enable_thinking is not None:
            data["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        return data


# Extensible, bounded model options. Never allow networking, model substitution or additional lanes here.
OPTIONS = {
    "--cpu-moe": None,
    "--n-cpu-moe": "int",
    "--n-cpu-ffn": "int",
    "--swa-full": None,
    "--no-kv-offload": None,
    "--no-op-offload": None,
    "--no-repack": None,
    "--rope-scaling": {"none", "linear", "yarn"},
    "--rope-scale": "float",
    "--rope-freq-base": "float",
    "--rope-freq-scale": "float",
    "--yarn-orig-ctx": "int",
    "--reasoning-budget": "int",
    "--reasoning-format": {"none", "deepseek", "auto"},
}


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gpu_layers: int = Field(default=999, ge=0, le=999)
    threads: int = Field(default_factory=lambda: max(1, (os.cpu_count() or 8) // 2), ge=1, le=256)
    batch_threads: int = Field(default_factory=lambda: max(1, (os.cpu_count() or 8) // 2), ge=1, le=256)
    batch_size: int = Field(default=512, ge=32, le=8192)
    ubatch_size: int = Field(default=128, ge=16, le=8192)
    flash_attn: bool = True
    mmap: bool = True
    ctx_size: int = Field(default=4096, ge=512, le=262144)
    cache_type_k: Literal["f16", "q8_0", "q4_0"] = "f16"
    cache_type_v: Literal["f16", "q8_0", "q4_0"] = "f16"
    options: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    template: str | None = Field(default=None, max_length=500000)
    sampling: Sampling = Field(default_factory=Sampling)

    @model_validator(mode="after")
    def valid_combinations(self):
        if self.ubatch_size > self.batch_size:
            raise ValueError("ubatch must be <= batch")
        for flag, value in self.options.items():
            if flag not in OPTIONS:
                raise ValueError(f"Unsupported runtime option: {flag}")
            rule = OPTIONS[flag]
            if rule is None and value is not True and value is not None:
                raise ValueError(f"{flag} is a switch")
            if isinstance(rule, set) and value not in rule:
                raise ValueError(f"Invalid {flag} value")
            if rule in ("int", "float"):
                try:
                    if isinstance(value, bool):
                        raise ValueError()
                    number = float(value)
                    if not 0 <= number <= 1000000 or (rule == "int" and number != int(number)):
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError(f"Invalid {flag} numeric value") from None
        return self


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="BALANCED", min_length=1, max_length=60)
    config: RuntimeConfig = Field(default_factory=RuntimeConfig)
    notes: str = Field(default="", max_length=10000)
