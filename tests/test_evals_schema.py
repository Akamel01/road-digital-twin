from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.eval_schema import (
    METRICS,
    REGISTRY_PATH,
    EvalRegistry,
    EvalRun,
    dump_registry,
    load_registry,
)

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SEED = FIXTURES / "evals_seed.json"


def _first_appearance_metrics() -> tuple[str, ...]:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    seen: list[str] = []
    for run in data["runs"]:
        for key in run["metrics"]:
            if key not in seen:
                seen.append(key)
    return tuple(seen)


def test_live_file_matches_seed_prefix():
    reg = load_registry(REGISTRY_PATH)
    assert len(reg.runs) >= 7
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert len(seed["runs"]) == 7
    assert reg.pass_bar.model_dump() == seed["pass_bar"]
    live_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert list(live_raw.keys()) == ["pass_bar", "runs"]
    assert list(live_raw["pass_bar"].keys()) == list(seed["pass_bar"].keys())
    assert [list(r.keys()) for r in live_raw["runs"][:7]] == [list(r.keys()) for r in seed["runs"]]
    assert [list(r["metrics"].keys()) for r in live_raw["runs"][:7]] == [list(r["metrics"].keys()) for r in seed["runs"]]
    for live, fix in zip(reg.runs[:7], seed["runs"]):
        assert live.model_dump(mode="json") == EvalRun.model_validate(fix).model_dump(mode="json")


def test_verbatim_contract():
    reg = load_registry(REGISTRY_PATH)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert len(seed["runs"]) == 7
    live_raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert [list(r.keys()) for r in live_raw["runs"][:7]] == [list(r.keys()) for r in seed["runs"]]
    assert [list(r["metrics"].keys()) for r in live_raw["runs"][:7]] == [list(r["metrics"].keys()) for r in seed["runs"]]
    live_runs = [r.model_dump(mode="json") for r in reg.runs[:7]]
    fix_runs = [EvalRun.model_validate(r).model_dump(mode="json") for r in seed["runs"]]
    assert live_runs == fix_runs
    assert [r["id"] for r in live_runs] == [r["id"] for r in fix_runs]


def test_metrics_order_matches_seed():
    assert METRICS == _first_appearance_metrics()


def test_dump_roundtrip_stable():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    reg = EvalRegistry.model_validate(data)
    first = dump_registry(reg)
    parsed = json.loads(first)
    second_reg = EvalRegistry.model_validate(parsed)
    second = dump_registry(second_reg)
    assert first == second
    assert parsed == data


def test_duplicate_id_rejected():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"].append(json.loads(json.dumps(data["runs"][0])))
    with pytest.raises(ValidationError):
        EvalRegistry.model_validate(data)


def test_unknown_field_rejected():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"][0]["foo"] = 1
    with pytest.raises(ValidationError):
        EvalRegistry.model_validate(data)


def test_unknown_metric_rejected():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"][0]["metrics"]["nope"] = 1.0
    with pytest.raises(ValidationError):
        EvalRegistry.model_validate(data)


def test_non_finite_metric_rejected():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"][0]["metrics"]["psnr"] = float("nan")
    with pytest.raises(ValidationError):
        EvalRegistry.model_validate(data)


def test_partial_metrics_accepted():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"][0]["metrics"] = {"psnr": 20.0}
    reg = EvalRegistry.model_validate(data)
    assert reg.runs[0].metrics == {"psnr": 20.0}


def test_non_positive_depth_normalised():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    data["runs"][0]["metrics"] = {
        "psnr": 0,
        "ssim": 0.5,
        "road_depth_p95_m": 0,
        "lidar_ground_p50_m": -1,
    }
    reg = EvalRegistry.model_validate(data)
    assert reg.runs[0].metrics == {"psnr": 0.0, "ssim": 0.5}


def test_eval_set_required():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    del data["runs"][0]["eval_set"]
    with pytest.raises(ValidationError):
        EvalRegistry.model_validate(data)


def test_canonical_format():
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert dump_registry(load_registry(REGISTRY_PATH)) == text