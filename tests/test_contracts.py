import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from twin import contracts
from twin.cli import render_schema, write_schemas
from twin.contracts import STAGES, Params, Pipeline, PipelineStage, check_rerun

REPO = Path(__file__).resolve().parents[1]


def test_defaults_load():
    params = Params()
    assert params.ground.voxel_m == 0.05
    assert params.isd.case == "B1"
    assert params.features.curbs.enabled is True
    assert params.seed == 0
    Pipeline()


def test_out_of_range_param_rejected():
    with pytest.raises(ValidationError):
        Params(ground={"voxel_m": 0.01})


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        Params(ground={"voxel_m": 0.05, "voxl_m": 1})
    with pytest.raises(ValidationError):
        Params(bogus=1)


def test_bad_isd_case_rejected():
    with pytest.raises(ValidationError):
        Params(isd={"case": "B4"})


def test_bad_method_rejected():
    with pytest.raises(ValueError, match="align"):
        Pipeline(align=PipelineStage(method="magic"))


def test_required_stage_cannot_be_disabled():
    with pytest.raises(ValueError, match="ground"):
        Pipeline(ground=PipelineStage(method="csf", enabled=False))


def test_enabled_stage_requiring_disabled_rejected(monkeypatch):
    # No optional stage is required by another in the spec table, so the rule
    # is exercised with a temporary requires entry: accuracy needs colour.
    spec = STAGES["accuracy"]
    monkeypatch.setitem(
        STAGES,
        "accuracy",
        contracts.StageSpec(
            number=spec.number,
            methods=spec.methods,
            requires=(*spec.requires, "colour"),
            outputs=spec.outputs,
            optional=True,
        ),
    )
    with pytest.raises(ValueError, match="accuracy.*colour"):
        Pipeline(colour=PipelineStage(method="zbuffer-topk", enabled=False))


def test_check_rerun_refuses_earlier_stage_change():
    base_p, base_q = Pipeline(), Params()
    new_q = Params(ground={"voxel_m": 0.1})
    with pytest.raises(ValueError, match="re-run from stage ground"):
        check_rerun(base_p, base_q, base_p, new_q, from_stage="features")


def test_check_rerun_refuses_earlier_method_change():
    base_p, base_q = Pipeline(), Params()
    new_p = Pipeline(align=PipelineStage(method="dataset-poses"))
    with pytest.raises(ValueError, match="re-run from stage align"):
        check_rerun(base_p, base_q, new_p, base_q, from_stage="ground")


def test_check_rerun_allows_same_or_later_change():
    base_p, base_q = Pipeline(), Params()
    new_q = Params(features={"intensity_pct": 90})
    check_rerun(base_p, base_q, base_p, new_q, from_stage="features")
    new_q2 = Params(isd={"time_gap_s": 6})
    check_rerun(base_p, base_q, base_p, new_q2, from_stage="features")


def test_check_rerun_setup_key_never_forces_rerun():
    base_p, base_q = Pipeline(), Params()
    new_q = Params(select={"min_contrast": 2.0})
    check_rerun(base_p, base_q, base_p, new_q, from_stage="load")


def test_schemas_on_disk_are_current(tmp_path):
    write_schemas(tmp_path)
    for path in sorted(tmp_path.glob("*.schema.json")):
        on_disk = REPO / "schemas" / path.name
        assert on_disk.read_text() == path.read_text(), (
            f"{on_disk} is stale; run `uv run twin schema`"
        )
    assert len(list(tmp_path.glob("*.schema.json"))) == 5


def test_schema_render_is_sorted_json():
    text = render_schema(Params)
    assert text.endswith("\n")
    assert json.loads(text)["title"] == "Params"
