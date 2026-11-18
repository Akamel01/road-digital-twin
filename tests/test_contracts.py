import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from twin import contracts
from twin.cli import render_schema, write_schemas
from twin.contracts import (
    PARAM_STAGE,
    STAGES,
    LabelFeature,
    Params,
    Pipeline,
    PipelineStage,
    SiteMeta,
    check_rerun,
)

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


def test_every_params_field_has_param_stage_entry():
    for field in Params.model_fields:
        assert field in PARAM_STAGE, f"Params field {field!r} missing from PARAM_STAGE"


def test_check_rerun_differing_merge_params_does_not_raise():
    base_p, base_q = Pipeline(), Params()
    new_q = Params(merge={"heights": True})
    check_rerun(base_p, base_q, base_p, new_q, from_stage="load")


def test_schemas_on_disk_are_current(tmp_path):
    write_schemas(tmp_path)
    for path in sorted(tmp_path.glob("*.schema.json")):
        on_disk = REPO / "schemas" / path.name
        assert on_disk.read_text() == path.read_text(), (
            f"{on_disk} is stale; run `uv run twin schema`"
        )
    assert len(list(tmp_path.glob("*.schema.json"))) == 7


def test_schema_render_is_sorted_json():
    text = render_schema(Params)
    assert text.endswith("\n")
    assert json.loads(text)["title"] == "Params"


def test_params_stage_of_and_groups_for():
    p = Params()
    assert p.stage_of("features") == "features" and p.stage_of("merge") is None
    assert p.groups_for("load") == ["facilities", "seed"]
    assert p.groups_for("outputs") == []


def test_params_get_and_flat():
    p = Params()
    assert p.get("features.cluster_eps_m") == p.features.cluster_eps_m
    assert p.get("seed") == 0
    for bad in ("nope", "features.nope", "seed.x"):
        with pytest.raises(KeyError):
            p.get(bad)
    flat = p.flat()
    assert flat["features.cluster_eps_m"] == p.features.cluster_eps_m and "seed" in flat


def test_params_with_value_validates_and_leaves_original():
    p = Params()
    q = p.with_value("features.cluster_eps_m", 0.5)
    assert q.features.cluster_eps_m == 0.5 and p.features.cluster_eps_m != 0.5
    with pytest.raises(ValidationError):
        p.with_value("features.cluster_eps_m", -1)
    with pytest.raises(KeyError):
        p.with_value("features.nope", 1)


def test_params_bounds():
    lo, hi = Params().bounds("features.cluster_eps_m")
    assert lo is not None and hi is not None and lo < hi
    assert Params().bounds("nope.x") is None and Params().bounds("seed") is None


def test_ramps_params_defaults_and_schema():
    from twin.contracts import FeaturesParams, RampsParams

    r = RampsParams()
    assert r.enabled is True and r.min_measure_cells == 4
    fp = FeaturesParams()
    assert fp.ramps.min_measure_cells == 4
    with pytest.raises(ValidationError):
        RampsParams(gap_min_m=5.0, gap_max_m=1.0)
    assert "ramps.geojson" in STAGES["features"].outputs


def test_site_meta_control_and_notes_default_none():
    m = SiteMeta(
        id="s",
        role="dev",
        polygon={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        created_at="2026-01-01T00:00:00",
        source_area="a",
    )
    assert m.control is None
    assert m.notes is None
    m2 = SiteMeta(
        id="s",
        role="dev",
        polygon={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        created_at="2026-01-01T00:00:00",
        source_area="a",
        control="signalised",
        notes="n",
    )
    assert m2.control == "signalised" and m2.notes == "n"


@pytest.mark.parametrize("t", ["double_line", "ladder", "continental", "transverse"])
def test_label_feature_accepts_extended_types(t):
    elem = {"double_line": "marking", "ladder": "crosswalk", "continental": "crosswalk", "transverse": "crosswalk"}[t]
    f = LabelFeature(
        id="x",
        element=elem,
        type=t,
        origin="operator",
        evidence="ortho",
    )
    assert f.type == t and f.evidence == "ortho"
    # round-trip via dump
    d = f.model_dump(mode="json")
    f2 = LabelFeature.model_validate(d)
    assert f2.evidence == "ortho" and f2.type == t


def test_label_schema_doc_lists_new_fields_and_types():
    text = (REPO / "docs" / "design" / "label-schema.md").read_text()
    for field in ("control", "notes", "evidence"):
        assert field in text, field
    for t in ("double_line", "ladder", "continental", "transverse"):
        assert t in text, t
    # mapping table / normalisation rules
    assert "by→origin" in text
    assert "open ring" in text
    for t in ("double_line", "ladder", "continental", "transverse"):
        assert t in text
    for f in ("control", "notes"):
        assert f in text


def test_decision_record_exists():
    p = REPO / "docs" / "decisions" / "0008-label-tool-persistence.md"
    assert p.is_file()
    text = p.read_text()
    assert "loopback" in text.lower()
    assert "areas root" in text.lower() or "areas-root" in text.lower() or "areas_root" in text


def test_spec_delta_lists_label_routes_and_cli():
    text = (REPO / "docs" / "design" / "twin-v1-spec.md").read_text()
    for s in (
        "twin labels tool",
        "twin labels import",
        "/api/r/labels/{site}/tool",
        "PUT /api/w/labels/{site}",
        "/api/r/geo/latlon",
    ):
        assert s in text, s


def test_docs_do_not_contain_draft_a_ids_or_ranges():
    # real draft-A ids look like smwi...; ranges mention specific coords
    forbidden = ["smwi"]
    for p in [
        REPO / "docs" / "design" / "label-schema.md",
        REPO / "docs" / "decisions" / "0008-label-tool-persistence.md",
        REPO / "docs" / "design" / "twin-v1-spec.md",
    ]:
        text = p.read_text()
        for f in forbidden:
            assert f not in text, (p, f)
    import re

    spec_text = (REPO / "docs" / "design" / "twin-v1-spec.md").read_text() + (REPO / "docs" / "design" / "label-schema.md").read_text()
    # no real draft-A ids (smwi...) and no 6-digit UTM coordinate literals
    assert re.search(r"smwi[0-9a-z]{6,}", spec_text) is None
    assert re.search(r"\b\d{6}\.\d{3}\b", spec_text) is None
