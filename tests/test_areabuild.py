import json
import logging
from pathlib import Path

import numpy as np

from twin import areabuild
from twin.cli import main
from twin.contracts import Params
from twin.gates import evaluate
from twin.runrecord import eval_document, write_document


def _make_store(tmp_path: Path, name: str = "a1") -> Path:
    base = tmp_path / "store"
    areas = base / "areas"
    merged = areas / f"{name}-merged"
    merged.mkdir(parents=True)
    (areas / f"{name}.json").write_text(json.dumps({"name": name, "polygon": {"type": "Polygon", "coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}))
    np.savez(merged / "merged.npz", x=np.array([1.0]), y=np.array([1.0]), z=np.array([0.0]), intensity=np.array([1.0]), drive=np.array([0]))
    (merged / "drives.json").write_text(json.dumps([{"scene": "s1", "date": "d1"}]))
    # merged record for assemble
    write_document(merged, {"run_id": "merged", "data": {"scene_token": "s1"}, "metrics": {"align": {"cross_drive_ground_p95_m": 0.03}}})
    (merged / "qa.json").write_text("{}\n")
    return base


def _fake_core_run(
    core_dir: Path,
    node_metrics: dict[str, dict],
    *,
    fail_node: str | None = None,
    durations: list[float] | None = None,
):
    core_dir = Path(core_dir)
    nodes_dir = core_dir / "nodes"
    nodes = []
    order = ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]
    out_map = {
        "load": "1_load", "mask": "2_mask", "align": "3_align", "ground": "4_ground",
        "features": "5_features", "change": None, "profile": "7_profile", "isd": "8_isd", "accuracy": "9_accuracy",
    }
    for i, n in enumerate(order):
        nd = nodes_dir / n
        nd.mkdir(parents=True, exist_ok=True)
        status = "failed" if n == fail_node else "done"
        metrics = node_metrics.get(n, {})
        (nd / "metrics.json").write_text(json.dumps(metrics))
        checks = [{"name": "stage_ok", "value": status, "pass": status == "done"}]
        for ck, cv in _flatten_metric_checks(metrics):
            checks.append({"name": ck, "value": cv, "pass": True})
        (nd / "checks.json").write_text(json.dumps({"version": 1, "checks": checks}))
        if n == "change":
            (nd / "change.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
            (nd / "1_load").mkdir(parents=True, exist_ok=True)
            (nd / "1_load" / "reference.geojson").write_text('{"type":"FeatureCollection","features":[]}')
            (nd / "1_load" / "facilities.geojson").write_text('{"type":"FeatureCollection","features":[]}')
            (nd / "1_load" / "poses.json").write_text('{"poses":[{"matrix":[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}]}')
            (nd / "5_features").mkdir(parents=True, exist_ok=True)
            (nd / "5_features" / "markings.geojson").write_text('{"type":"FeatureCollection","features":[]}')
        else:
            od = nd / out_map[n]
            od.mkdir(parents=True, exist_ok=True)
            if n == "ground":
                (od / "qa.json").write_text("{}")
        duration = float(durations[i]) if durations is not None else float(i + 1)
        nodes.append({"name": n, "status": status, "duration_s": duration, "checks": checks, "outputs": {}, "error": (f"{n} failed" if n == fail_node else None)})
        if n == fail_node:
            for m in order[i + 1:]:
                nodes.append({"name": m, "status": "not_run", "duration_s": 0.0, "checks": [], "outputs": {}})
            break
    (core_dir / "run.json").write_text(json.dumps({"version": 1, "pipeline": "area-twin", "manifest_hash": "h", "core_version": "0.1.0", "status": "failed" if fail_node else "succeeded", "nodes": nodes}))
    return 1 if fail_node else 0


def _flatten_metric_checks(tree: dict, prefix: str = "") -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for key, val in tree.items():
        name = f"{prefix}{key}"
        if isinstance(val, dict):
            out.extend(_flatten_metric_checks(val, name + "."))
        else:
            out.append((name, val))
    return out


def test_manifest_wraps_area_flow_in_core_nodes(tmp_path):
    from recon_core.manifest import validate_manifest

    base = _make_store(tmp_path)
    manifest = areabuild.area_manifest(base, "a1")
    assert validate_manifest(manifest) == []
    names = [n["name"] for n in manifest["nodes"]]
    assert names == ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]
    assert len(names) == 9
    for node in manifest["nodes"]:
        for arg in node["command"]:
            assert "/{in." not in arg and "/{out." not in arg
            # no interior placeholders
            if "{in." in arg or "{out." in arg:
                assert arg.count("{") == 1 and arg.count("}") == 1
        # every input type covers command refs? checked by validate_manifest; also producer/consumer types match.
        assert node["output_types"]["root"] == "dir"


def test_manifest_pipeline_inputs_resolve_under_workdir(tmp_path):
    base = _make_store(tmp_path)
    name = "a1"
    # create capture and params as expected by manifest
    cap = base / "areas" / f"{name}-capture"
    cap.mkdir()
    (cap / "capture.json").write_text("{}")
    (base / "areas" / f"{name}-params.json").write_text("{}")
    manifest = areabuild.area_manifest(base, name)
    workdir = base / "areas" / f"{name}-twin-core"
    workdir.mkdir(parents=True)
    for key, rel in manifest["inputs"].items():
        p = (workdir / rel).resolve()
        assert p.exists(), f"missing pipeline input {key}: {p}"


def test_area_build_gates_match_todays_twin_metrics(tmp_path, monkeypatch):
    base = _make_store(tmp_path)
    name = "a1"
    # hand-written twin record metrics (today's)
    twin_doc = {
        "run_id": "area-a1-twin",
        "data": {"scene_token": "s1"},
        "metrics": {
            "align": {"cross_drive_ground_p95_m": 0.03},
            "ground": {"z_disagreement_p95_m": 0.05},
            "accuracy": {
                "elements": {
                    "markings": {"p95_m": 0.2, "matched_p95_m": 0.2, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                    "crosswalks": {"p95_m": 0.4, "matched_p95_m": 0.4, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                    "curbs": {"p95_m": 0.4, "matched_p95_m": 0.4, "false_positive_rate": 0.05, "p50_m": 0.1, "coverage": 0.8},
                }
            },
        },
        "stages": [{"seconds": 1.0}],
    }
    expected = evaluate(twin_doc)

    node_metrics = {
        # align is a twin-level metric not produced by a core node; include it so
        # eval_document(core_record) can express G2 like the hand-written twin record.
        "align": {"cross_drive_ground_p95_m": 0.03},
        "ground": {"z_disagreement_p95_m": 0.05},
        "change": {"n_features": 1, "n_features_changed": 0, "n_change_regions": 0, "change_area_m2": 0.0, "noise": {}, "by_date": {}},
        "accuracy": twin_doc["metrics"]["accuracy"],
    }

    def fake_core_run(manifest_path, core_dir):
        # Durations sum to 1.0s so eval_document(runtime) matches twin_doc stages.
        return _fake_core_run(core_dir, node_metrics, durations=[0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.2])

    monkeypatch.setattr(areabuild, "core_run", fake_core_run)
    monkeypatch.setattr("twin.capture.build_area_capture", lambda *a, **k: Path(a[1]))

    summary = areabuild.area_build(base, name, __import__("logging").getLogger("t"))
    gates = json.loads((base / "areas" / f"{name}-twin" / "gates.json").read_text())
    core_record = json.loads((base / "areas" / f"{name}-twin" / "core-run.json").read_text())
    from_core = evaluate(eval_document(core_record, f"area-{name}-twin"))

    assert set(gates["gates"].keys()) == set(from_core["gates"].keys()) == set(expected["gates"].keys())
    for gid in gates["gates"]:
        assert gates["gates"][gid]["checks"] == from_core["gates"][gid]["checks"] == expected["gates"][gid]["checks"]
        assert gates["gates"][gid]["status"] == from_core["gates"][gid]["status"] == expected["gates"][gid]["status"]
    assert gates["verdict"] == from_core["verdict"] == expected["verdict"]
    assert summary["gates_verdict"] == gates["verdict"]


def test_area_build_assembles_todays_layout(tmp_path, monkeypatch):
    base = _make_store(tmp_path)
    name = "a1"
    node_metrics = {
        "ground": {"z_disagreement_p95_m": 0.1},
        "change": {"n_features": 2, "n_features_changed": 1, "n_change_regions": 1, "change_area_m2": 1.5, "noise": {}, "by_date": {"d1": {"regions": 1, "area_m2": 1.5}}},
        "accuracy": {"elements": {}},
    }
    monkeypatch.setattr(areabuild, "core_run", lambda mp, cd: _fake_core_run(cd, node_metrics))
    monkeypatch.setattr("twin.capture.build_area_capture", lambda *a, **k: Path(a[1]))
    areabuild.area_build(base, name, __import__("logging").getLogger("t"))
    out = base / "areas" / f"{name}-twin"
    for d in ["1_load", "2_mask", "3_align", "4_ground", "5_features", "7_profile", "8_isd", "9_accuracy"]:
        assert (out / d).exists()
    assert (out / "change.geojson").is_file()
    assert (out / "run.json").is_file()
    assert (out / "core-run.json").is_file()
    assert (out / "merged.npz").is_symlink() or (out / "merged.npz").exists()
    assert (out / "drives.json").exists()
    # change.json fields
    change = json.loads((out / "change.json").read_text())
    for k in ["area", "n_drives", "n_features", "n_features_changed", "n_change_regions", "change_area_m2", "noise", "seconds", "twin_seconds", "by_date"]:
        assert k in change


def test_area_build_node_failure_returns_1(tmp_path, monkeypatch):
    base = _make_store(tmp_path)
    name = "a1"
    monkeypatch.setattr(areabuild, "core_run", lambda mp, cd: _fake_core_run(cd, {}, fail_node="ground"))
    monkeypatch.setattr("twin.capture.build_area_capture", lambda *a, **k: Path(a[1]))
    rc = main(["area", "build", name, "--store", str(base)])
    assert rc == 1
    assert (base / "areas" / f"{name}-twin-core").exists()


def test_area_build_command_rejects_unknown_area(tmp_path):
    rc = main(["area", "build", "missing", "--store", str(tmp_path / "store")])
    assert rc == 2


def test_area_build_preserves_existing_user_params(tmp_path, monkeypatch):
    base = _make_store(tmp_path)
    name = "a1"
    params_path = base / "areas" / f"{name}-params.json"
    user_params = Params().model_dump(mode="json")
    user_params["ground"]["voxel_m"] = 0.2
    user_params["seed"] = 7
    user_text = json.dumps(user_params, indent=2, sort_keys=True) + "\n"
    params_path.write_text(user_text)

    seen = {}

    def fake_core_run(manifest_path, core_dir):
        seen["manifest"] = json.loads(Path(manifest_path).read_text())
        seen["params"] = json.loads(params_path.read_text())
        return _fake_core_run(
            core_dir,
            {
                "ground": {"z_disagreement_p95_m": 0.1},
                "change": {
                    "n_features": 0,
                    "n_features_changed": 0,
                    "n_change_regions": 0,
                    "change_area_m2": 0.0,
                    "noise": {},
                    "by_date": {},
                },
                "accuracy": {"elements": {}},
            },
        )

    monkeypatch.setattr(areabuild, "core_run", fake_core_run)
    monkeypatch.setattr("twin.capture.build_area_capture", lambda *a, **k: Path(a[1]))

    areabuild.area_build(base, name, __import__("logging").getLogger("t"))

    assert params_path.read_text() == user_text
    assert seen["params"]["ground"]["voxel_m"] == 0.2
    assert seen["params"]["seed"] == 7
    assert seen["manifest"]["inputs"]["params"] == f"../{name}-params.json"


def _make_core_dir_for_assemble(base: Path, name: str) -> tuple[Path, dict]:
    merged = base / "areas" / f"{name}-merged"
    merged.mkdir(parents=True, exist_ok=True)
    np.savez(merged / "merged.npz", x=np.array([1.0]), y=np.array([1.0]), z=np.array([0.0]), intensity=np.array([1.0]), drive=np.array([0]))
    (merged / "drives.json").write_text(json.dumps([{"scene": "s1", "date": "d1"}]))
    write_document(merged, {"run_id": "merged", "data": {"scene_token": "s1"}, "metrics": {"align": {}}})
    (merged / "qa.json").write_text("{}\n")
    (base / "areas" / f"{name}.json").write_text(json.dumps({"name": name, "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}))

    core_dir = base / "areas" / f"{name}-twin-core"
    nodes_dir = core_dir / "nodes"
    for n, outd in [("mask", "2_mask"), ("align", "3_align"), ("ground", "4_ground"), ("profile", "7_profile"), ("isd", "8_isd"), ("accuracy", "9_accuracy")]:
        nd = nodes_dir / n / outd
        nd.mkdir(parents=True, exist_ok=True)
        (nodes_dir / n / "metrics.json").write_text(json.dumps({"z_disagreement_p95_m": 0.1} if n == "ground" else {"elements": {}} if n == "accuracy" else {}))
        (nodes_dir / n / "checks.json").write_text('{"version":1,"checks":[]}')

    change_node = nodes_dir / "change"
    (change_node / "1_load").mkdir(parents=True, exist_ok=True)
    (change_node / "5_features").mkdir(parents=True, exist_ok=True)
    (change_node / "change.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    (change_node / "metrics.json").write_text(json.dumps({"n_features": 0, "n_features_changed": 0, "n_change_regions": 0, "change_area_m2": 0.0, "noise": {}, "by_date": {}}))
    (change_node / "checks.json").write_text('{"version":1,"checks":[]}')
    # minimal required files copied/symlinked by assemble
    for p in ["1_load/reference.geojson", "1_load/facilities.geojson", "1_load/poses.json", "5_features/markings.geojson"]:
        (change_node / p).write_text("{}")

    nodes = []
    for n in ["load", "mask", "align", "ground", "features", "change", "profile", "isd", "accuracy"]:
        nodes.append({"name": n, "status": "done", "duration_s": 1.0, "checks": [], "outputs": {}, "error": None})
    (core_dir / "run.json").write_text(json.dumps({"version": 1, "status": "succeeded", "nodes": nodes}))
    manifest = areabuild.area_manifest(base, name)
    return core_dir, manifest


def test_assemble_area_twin_threads_check_date(tmp_path, monkeypatch):
    base = tmp_path / "store"
    base.mkdir()
    name = "a1"
    core_dir, manifest = _make_core_dir_for_assemble(base, name)

    monkeypatch.setattr("twin.areabuild.construction_check", lambda *a, **k: {"ok": True}, raising=False)
    monkeypatch.setattr("twin.areatwin.construction_check", lambda *a, **k: {"ok": True})

    summary = areabuild.assemble_area_twin(base, name, core_dir, manifest, check_date="2018-08-01")
    assert summary["construction_check"] == {"ok": True}
    change = json.loads((base / "areas" / f"{name}-twin" / "change.json").read_text())
    assert change["construction_check"] == {"ok": True}


def test_assemble_area_twin_check_date_none(tmp_path, monkeypatch):
    base = tmp_path / "store"
    base.mkdir()
    name = "a1"
    core_dir, manifest = _make_core_dir_for_assemble(base, name)

    summary = areabuild.assemble_area_twin(base, name, core_dir, manifest, check_date=None)
    assert summary["construction_check"] is None
    change = json.loads((base / "areas" / f"{name}-twin" / "change.json").read_text())
    assert change["construction_check"] is None


def test_every_manifest_command_parses_with_real_cli(tmp_path):
    from twin.cli import build_parser

    base = tmp_path / "store"
    base.mkdir()
    manifest = areabuild.area_manifest(base, "x")
    parser = build_parser()
    for node in manifest["nodes"]:
        cmd = list(node["command"])
        if cmd and cmd[0].endswith("twin"):
            args = cmd[1:]
        elif len(cmd) >= 4 and cmd[0] == "python" and cmd[1] == "-m" and cmd[2] == "twin.cli":
            args = cmd[3:]
        else:
            # handle sys.executable variant: python -m twin.cli
            if "twin.cli" in cmd:
                idx = cmd.index("twin.cli")
                args = cmd[idx + 1:]
            else:
                args = cmd[:]
        ns = parser.parse_args(args)
        # area step nodes
        if "area" in args and "step" in args:
            assert ns.step == node["name"], (node["name"], ns)
        elif "stage" in args:
            assert ns.name == node["name"], (node["name"], ns)
        assert getattr(ns, "out", None) is not None


def _make_synthetic_area(tmp_path: Path, name="site-tiny") -> Path:
    base = tmp_path / "store"
    areas = base / "areas"
    areas.mkdir(parents=True)
    merged = areas / f"{name}-merged"
    merged.mkdir()
    drives_dir = merged / "drives"
    drives_dir.mkdir()

    poly_coords = [[[-10.0, -10.0], [10.0, -10.0], [10.0, 10.0], [-10.0, 10.0], [-10.0, -10.0]]]
    area_doc = {
        "name": name,
        "location": "boston-seaport",
        "epsg": 32619,
        "buffer_m": 2.0,
        "intersections": [],
        "polygon": {"type": "Polygon", "coordinates": poly_coords},
        "dataset_version": "v1.0-test",
        "drives": [
            {"scene": "scene-a", "scene_token": "tok-a", "date": "2018-05-01", "description": "dry", "rain": False, "build_input": True},
            {"scene": "scene-b", "scene_token": "tok-b", "date": "2018-05-02", "description": "dry", "rain": False, "build_input": True},
        ],
    }
    (areas / f"{name}.json").write_text(json.dumps(area_doc))

    grid_x = np.linspace(-8, 8, 21)
    grid_y = np.linspace(-8, 8, 21)
    gx, gy = np.meshgrid(grid_x, grid_y)
    base_xs = gx.ravel()
    base_ys = gy.ravel()
    xs = np.tile(base_xs, 12)
    ys = np.tile(base_ys, 12)
    zs = np.zeros_like(xs)
    intensity = np.ones_like(xs, dtype=float)
    stripe = np.abs(xs) < 1.0
    intensity[stripe] = 100.0
    rng = np.random.default_rng(0)
    drive = rng.integers(0, 2, len(xs)).astype(np.int64)
    np.savez(merged / "merged.npz", x=xs, y=ys, z=zs, intensity=intensity, drive=drive)

    z_surface = [0.0] * 6
    drives_list = []
    for i, scene in enumerate(["scene-a", "scene-b"]):
        drives_list.append({
            "index": i,
            "scene": scene,
            "date": f"2018-05-0{i+1}",
            "role": "reference" if i == 0 else "registered",
            "correction": {"dx_m": 0.0, "dy_m": 0.0, "dz_m": 0.0, "translation_m": 0.0, "yaw_deg": 0.0},
            "z_surface": z_surface,
            "n_points": int((drive == i).sum()),
        })
        ddir = drives_dir / scene
        (ddir / "1_load").mkdir(parents=True)
        (ddir / "2_mask").mkdir(parents=True)
        (ddir / "3_align").mkdir(parents=True)

        ref_feat = {
            "type": "Feature",
            "properties": {"layer": "drivable_area", "token": "ref1"},
            "geometry": {"type": "Polygon", "coordinates": poly_coords},
        }
        (ddir / "1_load" / "facilities.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        (ddir / "1_load" / "reference.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [ref_feat]}))
        poses = {"poses": [{"sweep": 0, "timestamp_us": 1000 + i * 100, "matrix": np.eye(4).tolist()}]}
        (ddir / "1_load" / "poses.json").write_text(json.dumps(poses))
        cameras = {
            "cameras": [
                {
                    "channel": "CAM_FRONT",
                    "sample_token": f"s{i}",
                    "timestamp_us": 1000 + i * 100,
                    "image": f"samples/CAM_FRONT/{scene}.jpg",
                    "intrinsics": [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
                    "extrinsics": {"translation": [0.0, 0.0, 1.0], "rotation_wxyz": [1.0, 0.0, 0.0, 0.0]},
                }
            ]
        }
        (ddir / "1_load" / "cameras.json").write_text(json.dumps(cameras))
        img = base / "nuscenes" / "samples" / "CAM_FRONT" / f"{scene}.jpg"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"")

        np.savez(ddir / "2_mask" / "parked.npz", x=np.array([]), y=np.array([]), z=np.array([]), intensity=np.array([]), sweep=np.array([], dtype=np.uint16))

        align_poses = {
            "poses": [
                {"sweep": 0, "timestamp_us": 1000 + i * 100, "matrix": np.eye(4).tolist()},
                {"sweep": 1, "timestamp_us": 2000 + i * 100, "matrix": np.eye(4).tolist()},
            ]
        }
        (ddir / "3_align" / "poses.json").write_text(json.dumps(align_poses))
        (ddir / "3_align" / "qa.json").write_text(json.dumps({"method": "merged-icp", "fallback_used": False, "xy_drift_p95_m": None}))

    (merged / "drives.json").write_text(json.dumps(drives_list))

    from twin.runrecord import write_document
    write_document(merged, {"run_id": "area-site-tiny", "data": {"nuscenes_version": "v1.0-test"}, "metrics": {"align": {"cross_drive_ground_p95_m": 0.1}}, "stages": []})

    (merged / "qa.json").write_text("{}\n")
    return base


def test_real_manifest_runs_end_to_end_on_synthetic_area(tmp_path, monkeypatch):
    base = _make_synthetic_area(tmp_path)
    monkeypatch.setenv("NUSCENES_ROOT", str(base / "nuscenes"))
    name = "site-tiny"
    monkeypatch.setenv("TWIN_RUNS", str(base))
    areabuild.area_build(base, name, logging.getLogger("test"))
    core_dir = base / "areas" / f"{name}-twin-core"
    core_doc = json.loads((core_dir / "run.json").read_text())
    nodes = core_doc.get("nodes", [])
    assert len(nodes) == 9
    assert all(n.get("status") == "done" for n in nodes), [n.get("status") for n in nodes]
    twin_dir = base / "areas" / f"{name}-twin"
    for d in ["1_load", "2_mask", "3_align", "4_ground", "5_features", "7_profile", "8_isd", "9_accuracy"]:
        assert (twin_dir / d).exists(), d
    assert (twin_dir / "run.json").is_file()
    gates = json.loads((twin_dir / "gates.json").read_text())
    assert "gates" in gates
    for g in ("G1", "G2", "G3", "G4", "G5", "G6"):
        assert g in gates["gates"], g
    assert "verdict" in gates


def test_area_build_rebuilds_stale_multi_drive_capture(tmp_path, monkeypatch):
    base = _make_store(tmp_path)
    name = "a1"
    single = tmp_path / "single.json"
    single.write_text(json.dumps({"version": 1, "captures": ["s1"]}))
    assert areabuild._capture_stale(single) is False
    capture_json = base / "areas" / f"{name}-capture" / "capture.json"
    capture_json.parent.mkdir()
    capture_json.write_text(json.dumps({"version": 1, "captures": ["s1", "s2"]}))
    calls = []

    def fake_build(merged_dir, out, area_name):
        calls.append(area_name)
        (Path(out) / "capture.json").write_text(
            json.dumps({"version": 1, "captures": ["s1", "s2"],
                        "image_captures": {"s1/a.jpg": "s1", "s2/b.jpg": "s2"}})
        )
        return Path(out)

    node_metrics = {
        "ground": {"z_disagreement_p95_m": 0.1},
        "change": {"n_features": 0, "n_features_changed": 0, "n_change_regions": 0,
                    "change_area_m2": 0.0, "noise": {}, "by_date": {}},
        "accuracy": {"elements": {}},
    }
    monkeypatch.setattr("twin.capture.build_area_capture", fake_build)
    monkeypatch.setattr(areabuild, "core_run", lambda mp, cd: _fake_core_run(cd, node_metrics))
    log = logging.getLogger("test")

    areabuild.area_build(base, name, log)
    assert len(calls) == 1  # stale multi-drive capture rebuilt
    areabuild.area_build(base, name, log)
    assert len(calls) == 1  # complete capture reused
