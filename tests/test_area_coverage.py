import json
import sys
import types

import numpy as np
import shapely

import twin.area_coverage as ac
from twin import area


def _tables(root, ver, **tables):
    v = root / ver
    v.mkdir(parents=True, exist_ok=True)
    for name, obj in tables.items():
        (v / f"{name}.json").write_text(json.dumps(obj))


def _pcd(path, xyz, n=5):
    """Write a point file where nuScenes keeps LIDAR_TOP keyframes (samples/LIDAR_TOP/<name>)."""
    path = path.parent / "samples" / "LIDAR_TOP" / path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.zeros((len(xyz), n), dtype=np.float32)
    if len(xyz):
        arr[:, :3] = np.asarray(xyz, dtype=np.float32)
    arr.tofile(path)


def _scene_env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    ver = "v1.0-trainval"
    logs = [{"token": "l", "location": "boston-seaport", "date_captured": "2018-01-01"}]
    scenes = [
        {"token": "base", "name": "s-base", "log_token": "l", "description": "clear day", "first_sample_token": "b1"},
        {"token": "a", "name": "s-a", "log_token": "l", "description": "rain night", "first_sample_token": "a1"},
        {"token": "b", "name": "s-b", "log_token": "l", "description": "clear day", "first_sample_token": "c1"},
    ]
    samples = [{"token": "b1", "scene_token": "base", "next": ""}, {"token": "a1", "scene_token": "a", "next": ""}, {"token": "c1", "scene_token": "b", "next": ""}]
    def sd(tok, st, ep, fn):
        return {"token": tok, "sample_token": st, "ego_pose_token": ep, "calibrated_sensor_token": "cs", "is_key_frame": True, "filename": f"samples/LIDAR_TOP/{fn}"}
    sdata = [sd("sd_b", "b1", "ep_b", "b.bin"), sd("sd_a", "a1", "ep_a", "a.bin"), sd("sd_c", "c1", "ep_c", "c.bin")]
    ego = [
        {"token": "ep_b", "translation": [2.5, 2.5, 0], "rotation": [1, 0, 0, 0]},
        {"token": "ep_a", "translation": [7.5, 2.5, 0], "rotation": [1, 0, 0, 0]},
        {"token": "ep_c", "translation": [7.5, 2.5, 0], "rotation": [1, 0, 0, 0]},
    ]
    cal = [{"token": "cs", "translation": [0, 0, 0], "rotation": [1, 0, 0, 0]}]
    _tables(root, ver, log=logs, scene=scenes, sample=samples, sample_data=sdata, ego_pose=ego, calibrated_sensor=cal, category=[], lidarseg=[])
    _pcd(root / "b.bin", [[1, 1, 0], [2, 2, 0]])
    _pcd(root / "a.bin", [[7, 2, 0], [8, 2, 0]])
    _pcd(root / "c.bin", [[7, 2, 0], [8, 2, 0]])
    inter = "a" * 32
    area_path = tmp_path / "seaport.json"
    area_def = {"name": "seaport", "location": "boston-seaport", "epsg": 32619, "buffer_m": 0, "intersections": [inter], "drives": [{"scene": "s-base", "scene_token": "base", "date": "2018-01-01", "description": "clear day", "rain": False, "build_input": True}]}
    area_path.write_text(json.dumps(area_def))
    poly = shapely.box(0, 0, 10, 5)
    monkeypatch.setattr(area, "load_intersections", lambda d, l: {inter: poly})
    class M:
        def get_records_in_patch(self, b, layers, mode): return {"drivable_area": ["d"]}
        def get(self, layer, tok): return {"polygon_tokens": ["p"]}
        def extract_polygon(self, tok): return shapely.box(0, 0, 10, 5)
    monkeypatch.setattr(area, "nuscenes_map_class", lambda: (lambda **kw: M()))
    return root, ver, area_path


def test_synthetic_coverage_numpy_grids():
    poly = shapely.box(0, 0, 10, 5)
    masks = ac.build_masks(poly, shapely.box(0, 0, 10, 5))
    drive_count, pts = ac.new_grids(masks)
    seen = np.zeros_like(drive_count, np.uint8)
    xy1 = np.array([[1, 1], [2, 2], [3, 3]], dtype=float)
    ac.add_points(pts, seen, masks, xy1, np.ones(len(xy1), bool))
    ac.close_drive(drive_count, seen)
    dense = np.array([[x, y] for x in np.linspace(0.2, 4.8, 40) for y in np.linspace(0.2, 4.8, 32)])
    ac.add_points(pts, seen, masks, dense, np.ones(len(dense), bool))
    ac.close_drive(drive_count, seen)
    density, low = ac.density_low(masks, drive_count, pts, 50.0)
    assert drive_count[0, 0] == 2 and drive_count[0, 1] == 0
    assert pts[0, 0] == len(xy1) + len(dense)
    assert abs(float(density[0, 0]) - pts[0, 0] / 25.0) < 1e-6
    assert not low[0, 0] and low[0, 1]


def test_no_nuscenes_object_constructed(tmp_path, monkeypatch, capsys):
    root, ver, area_path = _scene_env(tmp_path, monkeypatch)

    class Boom:
        def __init__(self, *a, **k): raise AssertionError("NuScenes() must not be constructed")
    # inject stub so import/attr access never loads real devkit (and avoid libGL issues)
    mod = types.ModuleType("nuscenes.nuscenes")
    mod.NuScenes = Boom
    pkg = types.ModuleType("nuscenes"); pkg.nuscenes = mod
    monkeypatch.setitem(sys.modules, "nuscenes", pkg)
    monkeypatch.setitem(sys.modules, "nuscenes.nuscenes", mod)

    rc = area.suggest_drives_command(str(area_path), 10, dataroot=str(root), store=str(tmp_path), version=ver)
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    rows = [l for l in out[1:] if l.strip()]
    assert [r.split()[0] for r in rows] == ["s-a", "s-b"]  # same gain, rain/night diversity tie-break


def test_apply_appends_schema_and_writes_coverage(tmp_path, monkeypatch):
    root, ver, area_path = _scene_env(tmp_path, monkeypatch)
    class Boom:
        def __init__(self, *a, **k): raise AssertionError("NuScenes() must not be constructed")
    mod = types.ModuleType("nuscenes.nuscenes"); mod.NuScenes = Boom
    pkg = types.ModuleType("nuscenes"); pkg.nuscenes = mod
    monkeypatch.setitem(sys.modules, "nuscenes", pkg)
    monkeypatch.setitem(sys.modules, "nuscenes.nuscenes", mod)

    rc = area.suggest_drives_command(str(area_path), 10, apply=True, dataroot=str(root), store=str(tmp_path), version=ver)
    assert rc == 0
    out = json.loads(area_path.read_text())
    added = next(d for d in out["drives"] if d["scene_token"] == "a")
    assert added == {"scene": "s-a", "scene_token": "a", "date": "2018-01-01", "description": "rain night", "rain": True, "build_input": False}
    cov = json.loads((tmp_path / "seaport.coverage.json").read_text())
    assert cov["area"] == "seaport" and cov["cell_m"] == 5.0 and cov["frame"] == "nuScenes-local-tmerc"
    assert isinstance(cov["cells"], list) and cov["cells"]


def test_candidate_cells_gained_positive(tmp_path, monkeypatch, capsys):
    root, ver, area_path = _scene_env(tmp_path, monkeypatch)
    # Make candidate s-a cover the same low-coverage cell as the base drive so
    # that adding it raises drive_count from 1 to 2 and yields cells_gained > 0.
    # overwrite a.bin points to fall in base cell (0,0)
    _pcd(root / "a.bin", [[-6.5, -1.5, 0], [-5.5, -0.5, 0]])
    class Boom:
        def __init__(self, *a, **k): raise AssertionError("NuScenes() must not be constructed")
    mod = types.ModuleType("nuscenes.nuscenes"); mod.NuScenes = Boom
    pkg = types.ModuleType("nuscenes"); pkg.nuscenes = mod
    monkeypatch.setitem(sys.modules, "nuscenes", pkg)
    monkeypatch.setitem(sys.modules, "nuscenes.nuscenes", mod)

    rc = area.suggest_drives_command(str(area_path), 10, density_threshold=0.1, dataroot=str(root), store=str(tmp_path), version=ver)
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    data_rows = [l for l in out if l.strip() and not l.startswith("scene") and len(l.split()) >= 3 and l.split()[0].startswith("s-")]
    assert data_rows, out
    gained = [int(r.split()[2]) for r in data_rows]
    assert any(g > 0 for g in gained), gained


def test_first_keyframe_outside_later_inside_included(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    ver = "v1.0-trainval"
    inter = "a" * 32
    logs = [{"token": "l", "location": "boston-seaport", "date_captured": "2018-01-01"}]
    scenes = [
        {"token": "base", "name": "s-base", "log_token": "l", "description": "clear day", "first_sample_token": "b1"},
        {"token": "c", "name": "s-c", "log_token": "l", "description": "clear day", "first_sample_token": "c1"},
    ]
    samples = [
        {"token": "b1", "scene_token": "base", "next": ""},
        {"token": "c1", "scene_token": "c", "next": "c2"},
        {"token": "c2", "scene_token": "c", "next": ""},
    ]
    def sd(tok, st, ep, fn):
        return {"token": tok, "sample_token": st, "ego_pose_token": ep, "calibrated_sensor_token": "cs", "is_key_frame": True, "filename": f"samples/LIDAR_TOP/{fn}"}
    sdata = [sd("sd_b", "b1", "ep_b", "b.bin"), sd("sd_c1", "c1", "ep_c1", "c1.bin"), sd("sd_c2", "c2", "ep_c2", "c2.bin")]
    ego = [
        {"token": "ep_b", "translation": [2.5, 2.5, 0], "rotation": [1, 0, 0, 0]},
        {"token": "ep_c1", "translation": [100.0, 100.0, 0], "rotation": [1, 0, 0, 0]},
        {"token": "ep_c2", "translation": [7.5, 2.5, 0], "rotation": [1, 0, 0, 0]},
    ]
    cal = [{"token": "cs", "translation": [0, 0, 0], "rotation": [1, 0, 0, 0]}]
    _tables(root, ver, log=logs, scene=scenes, sample=samples, sample_data=sdata, ego_pose=ego, calibrated_sensor=cal, category=[], lidarseg=[])
    _pcd(root / "b.bin", [[1, 1, 0], [2, 2, 0]])
    _pcd(root / "c1.bin", [[7, 2, 0]])
    _pcd(root / "c2.bin", [[7, 2, 0], [8, 2, 0]])
    area_path = tmp_path / "seaport.json"
    area_def = {"name": "seaport", "location": "boston-seaport", "epsg": 32619, "buffer_m": 0, "intersections": [inter], "drives": [{"scene": "s-base", "scene_token": "base", "date": "2018-01-01", "description": "clear day", "rain": False, "build_input": True}]}
    area_path.write_text(json.dumps(area_def))
    poly = shapely.box(0, 0, 10, 5)
    monkeypatch.setattr(area, "load_intersections", lambda d, l: {inter: poly})
    class M:
        def get_records_in_patch(self, b, layers, mode): return {"drivable_area": ["d"]}
        def get(self, layer, tok): return {"polygon_tokens": ["p"]}
        def extract_polygon(self, tok): return shapely.box(0, 0, 10, 5)
    monkeypatch.setattr(area, "nuscenes_map_class", lambda: (lambda **kw: M()))

    class Boom:
        def __init__(self, *a, **k): raise AssertionError("NuScenes() must not be constructed")
    mod = types.ModuleType("nuscenes.nuscenes"); mod.NuScenes = Boom
    pkg = types.ModuleType("nuscenes"); pkg.nuscenes = mod
    monkeypatch.setitem(sys.modules, "nuscenes", pkg)
    monkeypatch.setitem(sys.modules, "nuscenes.nuscenes", mod)

    rc = area.suggest_drives_command(str(area_path), 10, dataroot=str(root), store=str(tmp_path), version=ver)
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    names = [l.split()[0] for l in out if l.strip() and l.split() and l.split()[0].startswith("s-")]
    assert "s-c" in names, out
