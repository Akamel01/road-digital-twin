from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

METRICS: tuple[str, ...] = (
    "psnr",
    "ssim",
    "road_depth_p50_m",
    "road_depth_p95_m",
    "sidewalk_depth_p50_m",
    "sidewalk_depth_p95_m",
    "lidar_all_p50_m",
    "lidar_all_p95_m",
    "lidar_ground_p50_m",
    "lidar_ground_p95_m",
)

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "docs" / "evals" / "recon-v2-results.json"
ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class PassBar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    psnr_min: float
    road_depth_p95_max_m: float


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ID_PATTERN)
    date: date
    approach: str = Field(min_length=1)
    variant: str = ""
    ticket: int = Field(gt=0)
    iterations: int = Field(gt=0)
    train_minutes: float | None = Field(default=None, ge=0)
    gaussian_cap: int | None = Field(default=None, ge=1)
    eval_set: str = Field(min_length=1)
    notes: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)

    @field_validator("metrics", mode="before")
    @classmethod
    def _metrics(cls, v: Any) -> Any:
        if v is None:
            v = {}
        if not isinstance(v, dict):
            raise ValueError("metrics must be an object")  # noqa: TRY004
        out: dict[str, float] = {}
        for key, value in v.items():
            if key not in METRICS:
                raise ValueError(f"unknown metric: {key}")
            if isinstance(value, bool):
                raise ValueError(f"metric {key} must be a number, not bool")  # noqa: TRY004
            if not isinstance(value, (int, float)):
                raise ValueError(f"metric {key} must be a number")  # noqa: TRY004
            f = float(value)
            if not math.isfinite(f):
                raise ValueError(f"metric {key} must be finite")
            if key.endswith("_m") and f <= 0:
                continue
            out[key] = f
        return out


class EvalRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_bar: PassBar
    runs: list[EvalRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> EvalRegistry:
        seen: set[str] = set()
        for run in self.runs:
            if run.id in seen:
                raise ValueError(f"duplicate id: {run.id}")
            seen.add(run.id)
        return self


def load_registry(path: Path = REGISTRY_PATH) -> EvalRegistry:
    return EvalRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))


def dump_registry(reg: EvalRegistry) -> str:
    return json.dumps(reg.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"