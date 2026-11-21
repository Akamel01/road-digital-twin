import json

import numpy as np
import pytest
from recon_core.checks import read_checks

from twin import registry
from twin.cli import main
from twin.contracts import STAGE_NAMES, StageResult
from twin.stagecli import stage_command


def _box(size=(2.0, 4.0, 1.5), centre=(10.0, 5.0, 0.0), parked=False):
    # nuScenes size [w,l,h], quat identity
    return {
        "token": "t",
        "category": "vehicle.car",
        "center": list(centre),
        "size": list(size),
        "rotation": [1.0, 0.0, 0.0, 0.0],
        "parked": parked,
    }


def _write_load_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    pts = np.array(
        [
            [10.0, 5.0, 0.0, 1.0, 0],   # inside box
            [30.0, 5.0, 0.0, 2.0, 0],   # outside
        ],
        dtype=float,
    )
    np.savez_compressed(
        path / "points.npz",
        x=pts[:, 0].astype(np.float64),
        y=pts[:, 1].astype(np.float64),
        z=pts[:, 2].astype(np.float64),
        intensity=pts[:, 3].astype(np.float32),
        sweep=pts[:, 4].astype(np.uint16),
    )
    (path / "boxes.json").write_text(
        json.dumps({"crs": "EPSG:32619", "sweeps": [{"sweep": 0, "timestamp_us": 0, "boxes": [_box()]}]})
    )


def test_parser_accepts_all_stage_names(tmp_path):
    for name in STAGE_NAMES:
        out = tmp_path / f"out-{name}"
        # No inputs, will fail with exit 2 on missing required inputs or bad args, but parser accepts.
        rc = main(["stage", name, "--in", str(tmp_path), "--out", str(out)])
        assert rc == 2


def test_mask_stage_writes_outputs_metrics_and_checks(tmp_path):
    load_dir = tmp_path / "1_load"
    _write_load_dir(load_dir)
    out = tmp_path / "node"

    rc = stage_command("mask", [load_dir], out)

    assert rc == 0
    assert (out / "2_mask" / "points.npz").is_file()
    assert (out / "2_mask" / "parked.npz").is_file()
    assert (out / "metrics.json").is_file()
    checks_path = out / "checks.json"
    checks = read_checks(checks_path)
    names = {c.name for c in checks}
    assert "stage_ok" in names
    assert all(c.passed for c in checks)
    with np.load(out / "2_mask" / "points.npz") as f:
        assert len(f["x"]) == 1
        assert float(f["x"][0]) == pytest.approx(30.0)


def test_stage_accepts_run_folder_or_stage_dir(tmp_path):
    # Run folder with 1_load child
    run_dir = tmp_path / "run"
    _write_load_dir(run_dir / "1_load")
    (run_dir / "run.json").write_text(json.dumps({"data": {"scene_token": "tok"}}))
    out1 = tmp_path / "out-run"
    rc1 = stage_command("mask", [run_dir], out1)
    assert rc1 == 0
    assert (out1 / "2_mask" / "points.npz").is_file()

    # Bare stage dir
    stage_dir = tmp_path / "bare" / "1_load"
    _write_load_dir(stage_dir)
    out2 = tmp_path / "out-stage"
    rc2 = stage_command("mask", [stage_dir], out2)
    assert rc2 == 0
    assert (out2 / "2_mask" / "points.npz").is_file()


def test_missing_required_input_returns_2(tmp_path):
    out = tmp_path / "out"
    rc = stage_command("mask", [tmp_path], out)  # tmp_path has no 1_load
    assert rc == 2


def test_missing_extra_input_returns_2(tmp_path):
    # features requires ground per STAGES, plus extras load, align, ground; give ground only.
    ground = tmp_path / "4_ground"
    ground.mkdir()
    out = tmp_path / "out"
    rc = stage_command("features", [ground], out)
    assert rc == 2


def test_unknown_method_returns_2(tmp_path):
    load_dir = tmp_path / "1_load"
    _write_load_dir(load_dir)
    out = tmp_path / "out"
    rc = stage_command("mask", [load_dir], out, method="nope")
    assert rc == 2


def test_checks_match_core_schema(tmp_path):
    load_dir = tmp_path / "1_load"
    _write_load_dir(load_dir)
    out = tmp_path / "out"
    rc = stage_command("mask", [load_dir], out)
    assert rc == 0
    doc = json.loads((out / "checks.json").read_text())
    assert doc["version"] == 1
    assert isinstance(doc["checks"], list)
    for c in doc["checks"]:
        assert set(c.keys()) == {"name", "value", "threshold", "pass", "unit"}
        assert isinstance(c["name"], str)
        assert isinstance(c["pass"], bool)


def test_failed_stage_returns_1_and_writes_metrics(tmp_path, monkeypatch):
    load_dir = tmp_path / "1_load"
    _write_load_dir(load_dir)
    out = tmp_path / "out"

    def fake_lookup(stage, method):
        if stage == "mask":
            def _fail(ctx, params):
                return StageResult(status="failed", metrics={"reason": "boom"}, message="boom")
            return _fail
        return registry.lookup(stage, method)

    monkeypatch.setattr("twin.stagecli.registry.lookup", fake_lookup)
    rc = stage_command("mask", [load_dir], out)
    assert rc == 1
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["reason"] == "boom"
    checks = read_checks(out / "checks.json")
    by_name = {c.name: c for c in checks}
    assert by_name["stage_ok"].passed is False
    assert by_name["reason"].value == "boom"


def test_stage_load_no_input_dispatch(tmp_path, monkeypatch):
    out = tmp_path / "node"

    def fake_lookup(stage, method):
        assert stage == "load"

        def _ok(ctx, params):
            return StageResult(status="ok", metrics={"loaded": True})

        return _ok

    monkeypatch.setattr("twin.stagecli.registry.lookup", fake_lookup)
    rc = main(["stage", "load", "--out", str(out), "--scene", "scene-0000"])
    assert rc == 0
    assert (out / "metrics.json").is_file()
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["loaded"] is True


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _core_feature():
    poly = [[-50, -50], [150, -50], [150, 50], [-50, 50], [-50, -50]]
    return {
        "type": "Feature",
        "properties": {"id": "I-0001", "type": "intersection", "name": None},
        "geometry": {"type": "Polygon", "coordinates": [poly]},
    }


def _write_accuracy_inputs(run_dir):
    load_dir = run_dir / "1_load"
    features_dir = run_dir / "5_features"
    load_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)
    (load_dir / "reference.geojson").write_text(json.dumps(_fc([])))
    (load_dir / "facilities.geojson").write_text(json.dumps(_fc([_core_feature()])))
    marking = {
        "type": "Feature",
        "properties": {"id": "m1", "kind": "marking", "reliability": "observed", "marking_type": "other_paint"},
        "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
    }
    (features_dir / "markings.geojson").write_text(json.dumps(_fc([marking])))
    (features_dir / "crosswalks.geojson").write_text(json.dumps(_fc([])))
    (features_dir / "qa.json").write_text(json.dumps({"not_scanned_enough": []}))
    return load_dir, features_dir


def test_real_accuracy_stage_writes_core_readable_checks(tmp_path):
    run_dir = tmp_path / "run"
    load_dir, features_dir = _write_accuracy_inputs(run_dir)
    out = tmp_path / "node"

    rc = stage_command("accuracy", [load_dir, features_dir], out)

    assert rc == 0
    checks = read_checks(out / "checks.json")
    by_name = {c.name: c for c in checks}
    assert by_name["stage_ok"].passed is True
    assert by_name["stage_ok"].value == "ok"
    # "no map layer" branch yields None metrics; they must be core-check compatible.
    assert by_name["marking_types.other_paint.p50_m"].value == "null"
    assert by_name["marking_types.other_paint.reason"].value == "no map layer"
