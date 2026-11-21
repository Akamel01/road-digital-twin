import json

import numpy as np
from shapely.geometry import box, mapping

from twin import areasteps
from twin.cli import main
from twin.contracts import Params, StageResult


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def _write_area(work, name="a1"):
    (work / "areas").mkdir(parents=True, exist_ok=True)
    poly = mapping(box(0, 0, 10, 10))
    area = {"name": name, "polygon": poly, "drives": [{"scene": "s1", "date": "d1"}]}
    (work / "areas" / f"{name}.json").write_text(json.dumps(area))
    merged = work / "areas" / f"{name}-merged"
    merged.mkdir(parents=True, exist_ok=True)
    (merged / "drives.json").write_text(json.dumps([{"scene": "s1", "date": "d1"}]))
    np.savez(merged / "merged.npz", x=np.array([1.0]), y=np.array([1.0]), z=np.array([0.0]), intensity=np.array([1.0]), drive=np.array([0]))
    return area, merged


def test_load_step_writes_standins(tmp_path, monkeypatch):
    from twin import areatwin as at

    area, work = _write_area(tmp_path)
    monkeypatch.setattr(at, "area_inputs", lambda drives, work, polygon: ([], [{"type": "Feature", "properties": {"layer": "drivable_area"}, "geometry": mapping(box(0, 0, 10, 10))}]))
    out = tmp_path / "out"
    res = areasteps.load_step(work, area, out)
    assert res.status == "ok"
    load = out / "1_load"
    for fn in ["facilities.geojson", "reference.full.geojson", "reference.geojson", "poses.json"]:
        assert (load / fn).is_file()
    poses = json.loads((load / "poses.json").read_text())
    assert poses["poses"][0]["matrix"][0][0] == 1.0
    assert (out / "metrics.json").is_file()
    checks = json.loads((out / "checks.json").read_text())
    assert checks["version"] == 1
    names = {c["name"] for c in checks["checks"]}
    assert "stage_ok" in names


def test_mask_step_writes_parked(tmp_path, monkeypatch):
    from twin import areatwin as at

    area, work = _write_area(tmp_path)
    monkeypatch.setattr(at, "parked_vehicles", lambda drives, work, centre, polygon: np.array([[1.0, 2.0, 3.0]]))
    out = tmp_path / "out"
    res = areasteps.mask_step(work, area, out)
    assert res.status == "ok"
    with np.load(out / "2_mask" / "parked.npz") as f:
        assert f["x"].tolist() == [1.0]
        assert f["z"].tolist() == [3.0]
        assert f["sweep"].tolist() == [0]


def test_align_step_identity(tmp_path):
    out = tmp_path / "out"
    res = areasteps.align_step(out)
    assert res.status == "ok"
    qa = json.loads((out / "3_align" / "qa.json").read_text())
    assert qa == {"method": "merged-icp", "fallback_used": False, "xy_drift_p95_m": None}
    poses = json.loads((out / "3_align" / "poses.json").read_text())
    assert poses["poses"][0]["matrix"] == np.eye(4).tolist()


def test_ground_step_uses_merged_cloud(tmp_path, monkeypatch):
    from twin import areatwin as at

    area, work = _write_area(tmp_path)
    load_dir = tmp_path / "load"
    (load_dir / "1_load").mkdir(parents=True)
    (load_dir / "1_load" / "facilities.geojson").write_text(json.dumps(_fc([])))
    align_dir = tmp_path / "align"
    (align_dir / "3_align").mkdir(parents=True)
    (align_dir / "3_align" / "qa.json").write_text(json.dumps({"method": "merged-icp", "fallback_used": False, "xy_drift_p95_m": None}))

    called = {}

    class G:
        @staticmethod
        def voxel_first(xyz, voxel_m):
            called["voxel_m"] = voxel_m
            return np.arange(len(xyz))

        @staticmethod
        def ransac_ground(p, q, seed):
            return None

        @staticmethod
        def split_and_write(ctx, params, method, classify, xyz, intensity, sweep, labels, drv, align_qa, features):
            called["n"] = len(xyz)
            called["align_qa"] = align_qa
            (ctx.stage_dir("ground")).mkdir(parents=True, exist_ok=True)
            return StageResult(status="ok", metrics={"ground_metric": 1.0}, files=["4_ground/x"])

    monkeypatch.setattr(at, "ground", G())
    res = areasteps.ground_step(work, area, json.loads((work / "drives.json").read_text()), load_dir, align_dir, tmp_path / "out", Params(), __import__("logging").getLogger("t"))
    assert res.status == "ok"
    assert called["n"] == 1
    assert called["align_qa"]["method"] == "merged-icp"
    assert res.metrics["ground_metric"] == 1.0


def test_change_step_flags_features_and_masks_reference(tmp_path, monkeypatch):
    from twin import areatwin as at

    area, work = _write_area(tmp_path)
    # Make merged cloud with two drives/dates so change detection can run; simple case: no change regions.
    np.savez(work / "merged.npz", x=np.array([1.0, 2.0]), y=np.array([1.0, 2.0]), z=np.array([0.0, 0.0]), intensity=np.array([1.0, 1.0]), drive=np.array([0, 0]))
    drives = [{"scene": "s1", "date": "d1"}]

    features = tmp_path / "features"
    (features / "5_features").mkdir(parents=True)
    feat = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"id": "m1"}, "geometry": mapping(box(1, 1, 2, 2))}]}
    (features / "5_features" / "markings.geojson").write_text(json.dumps(feat))
    (features / "5_features" / "qa.json").write_text(json.dumps({"qa": 1}))

    load = tmp_path / "load"
    (load / "1_load").mkdir(parents=True)
    ref = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"layer": "drivable_area"}, "geometry": mapping(box(0, 0, 10, 10))}]}
    (load / "1_load" / "reference.full.geojson").write_text(json.dumps(ref))
    (load / "1_load" / "facilities.geojson").write_text(json.dumps(_fc([])))
    (load / "1_load" / "reference.geojson").write_text(json.dumps(ref))
    (load / "1_load" / "poses.json").write_text(json.dumps({"poses": []}))

    monkeypatch.setattr(at, "support", lambda feats, *a, **k: [f["properties"].setdefault("support", {"n_drives": 1, "drives": {"s1": 5}}) for f in feats])
    monkeypatch.setattr(at, "flag_changed", lambda feats, regions: 0)
    monkeypatch.setattr(at, "mask_reference", lambda reference, regions: reference)

    out = tmp_path / "out"
    res = areasteps.change_step(work, area, drives, features, load, out)
    assert res.status == "ok"
    assert (out / "change.geojson").is_file()
    assert (out / "5_features" / "markings.geojson").is_file()
    marked = json.loads((out / "5_features" / "markings.geojson").read_text())["features"][0]
    assert marked["properties"]["support"]["n_drives"] == 1
    assert "n_features" in res.metrics
    assert (out / "1_load" / "reference.geojson").is_file()


def test_change_step_copies_qa_and_facilities(tmp_path, monkeypatch):
    from twin import areatwin as at

    area, work = _write_area(tmp_path)
    np.savez(work / "merged.npz", x=np.array([1.0]), y=np.array([1.0]), z=np.array([0.0]), intensity=np.array([1.0]), drive=np.array([0]))
    drives = [{"scene": "s1", "date": "d1"}]
    features = tmp_path / "features"
    (features / "5_features").mkdir(parents=True)
    (features / "5_features" / "qa.json").write_text(json.dumps({"features_qa": True}))
    load = tmp_path / "load"
    (load / "1_load").mkdir(parents=True)
    ref = _fc([{"type": "Feature", "properties": {"layer": "drivable_area"}, "geometry": mapping(box(0, 0, 10, 10))}])
    (load / "1_load" / "reference.full.geojson").write_text(json.dumps(ref))
    (load / "1_load" / "facilities.geojson").write_text(json.dumps(_fc([{"type": "Feature", "properties": {"id": "f1"}, "geometry": mapping(box(0, 0, 1, 1))}])))
    (load / "1_load" / "reference.geojson").write_text(json.dumps(ref))
    (load / "1_load" / "poses.json").write_text(json.dumps({"poses": [{"matrix": np.eye(4).tolist()}]}))
    monkeypatch.setattr(at, "support", lambda *a, **k: None)
    monkeypatch.setattr(at, "flag_changed", lambda *a, **k: 0)
    monkeypatch.setattr(at, "mask_reference", lambda reference, regions: reference)

    out = tmp_path / "out"
    res = areasteps.change_step(work, area, drives, features, load, out)
    assert res.status == "ok"
    assert json.loads((out / "5_features" / "qa.json").read_text())["features_qa"] is True
    fac = json.loads((out / "1_load" / "facilities.geojson").read_text())
    assert fac["features"][0]["properties"]["id"] == "f1"


def test_area_step_cli_load(tmp_path, monkeypatch):
    from twin import areatwin as at

    _area, work = _write_area(tmp_path)
    monkeypatch.setattr(at, "area_inputs", lambda drives, work, polygon: ([], []))
    area_path = tmp_path / "areas" / "a1.json"
    out = tmp_path / "node-out"
    rc = main(["area", "step", "load", "--work", str(work), "--area", str(area_path), "--out", str(out)])
    assert rc == 0
    assert (out / "1_load" / "reference.geojson").is_file()
    checks = json.loads((out / "checks.json").read_text())
    assert any(c["name"] == "stage_ok" and c["pass"] is True for c in checks["checks"])
