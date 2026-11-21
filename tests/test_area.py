import json
import re
import sys
import types

import numpy as np
import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import box, mapping

import twin.area as area_mod
from twin.area import (
    _rebuild_poly,
    drive_correction,
    load_polygon_geojson,
    make_area,
    resolve_tokens,
)
from twin.cli import main
from twin.contracts import StageResult
from twin.stages.load import MAP_ORIGIN_LATLON, run_crs

A, B = "a" * 32, "b" * 32


def write_tables(root, poses):
    """poses: {scene name: [(x, y)]}, one ego pose each (sweep poses count the same as keyframes)."""
    v = root / "v1.0-test"
    v.mkdir(parents=True)
    scenes, samples, sds, egos = [], [], [], []
    for i, (name, pts) in enumerate(poses.items()):
        desc = "Rain, night" if name == "scene-2" else "sunny"
        scenes.append(
            {"token": f"sc{i}", "name": name, "log_token": "log", "description": desc}
        )
        samples.append({"token": f"smp{i}", "scene_token": f"sc{i}"})
        for j, (x, y) in enumerate(pts):
            egos.append({"token": f"e{i}{j}", "translation": [x, y, 0]})
            sds.append({"sample_token": f"smp{i}", "ego_pose_token": f"e{i}{j}"})
    scenes.append(
        {"token": "so", "name": "scene-9", "log_token": "log2", "description": "x"}
    )
    samples.append({"token": "smpo", "scene_token": "so"})
    egos.append({"token": "eo", "translation": [5, 5, 0]})
    sds.append({"sample_token": "smpo", "ego_pose_token": "eo"})
    logs = [
        {"token": "log", "location": "boston-seaport", "date_captured": "2018-09-18"},
        {
            "token": "log2",
            "location": "singapore-onenorth",
            "date_captured": "2018-09-18",
        },
    ]
    tables = [
        ("scene", scenes),
        ("sample", samples),
        ("sample_data", sds),
        ("ego_pose", egos),
        ("log", logs),
    ]
    for n, t in tables:
        (v / f"{n}.json").write_text(json.dumps(t))


def utm_of(geom):
    tr = run_crs(MAP_ORIGIN_LATLON)
    return shapely.transform(geom, lambda a: np.column_stack(tr.transform(a[:, 0], a[:, 1])))


def lonlat_of(geom_utm):
    tr = Transformer.from_crs("EPSG:32619", "EPSG:4326", always_xy=True)
    return shapely.transform(geom_utm, lambda a: np.column_stack(tr.transform(a[:, 0], a[:, 1])))


def write_geojson(path, geom, wrapper=True):
    geometry = mapping(geom)
    doc = {"type": "Feature", "properties": {}, "geometry": geometry} if wrapper else geometry
    path.write_text(json.dumps(doc))


def define_args(tmp_path, store, *source):
    return ["area", "define", "a3", *source, "--buffer", "10",
            "--location", "boston-seaport", "--version", "v1.0-test",
            "--dataroot", str(tmp_path), "--store", str(store)]


BASE = box(-10, -10, 0, 0)  # map-frame polygon used by the existing fixture's scenes


def test_area_drives_rain_and_held_out(tmp_path):
    write_tables(
        tmp_path,
        {
            "scene-1": [(100, 100), (5, 5)],  # one pose inside the buffer only
            "scene-2": [(0, 5)],  # inside, rain
            "scene-3": [(100, 100)],  # never near
        },
    )
    polys = {A: shapely.box(-10, -10, 0, 0), B: shapely.box(500, 500, 510, 510)}
    area = make_area("t", polys, [A[:8]], 10.0, tmp_path, "v1.0-test", "boston-seaport")
    got = {d["scene"]: d for d in area["drives"]}
    assert sorted(got) == ["scene-1", "scene-2"]  # scene-9 is on another map
    assert got["scene-2"]["rain"] and not got["scene-2"]["build_input"]
    assert not got["scene-1"]["rain"] and got["scene-1"]["build_input"]
    assert got["scene-1"]["date"] == "2018-09-18"
    assert area["epsg"] == 32619 and area["polygon"]["type"] == "Polygon"
    again = make_area(
        "t",
        polys,
        [A[:8]],
        10.0,
        tmp_path,
        "v1.0-test",
        "boston-seaport",
        include_rain=True,
    )
    assert all(d["build_input"] for d in again["drives"])


def test_prefix_must_be_unique_and_long_enough():
    known = {A: 0, "aaaaaaaabbbb": 0}
    for bad in ("aaaaaaaa", "aaaa", "zzzzzzzz"):
        with pytest.raises(ValueError):
            resolve_tokens([bad], known)
    assert resolve_tokens(["aaaaaaaabb"], known) == ["aaaaaaaabbbb"]


def test_drive_correction_centres_on_map_frame():
    c = {"dx_m": 1, "dy_m": 2, "dz_m": 3, "yaw_deg": 90}
    centre = np.array([100.0, 200.0, 0.0])
    assert drive_correction(c, centre) @ np.array([100.0, 200.0, 0.0, 1.0]) == pytest.approx([101.0, 202.0, 3.0, 1.0])
    assert drive_correction(c)[:3, 3] == pytest.approx([1.0, 2.0, 3.0])
    assert np.allclose(drive_correction(None), np.eye(4))
    assert np.allclose(drive_correction(None, centre), np.eye(4))


def test_define_cli_polygon_writes_area_with_drives(tmp_path, capsys):
    write_tables(tmp_path, {"scene-1": [(100, 100), (5, 5)], "scene-2": [(0, 5)], "scene-3": [(100, 100)]})
    store = tmp_path / "store"
    f = tmp_path / "poly.geojson"
    write_geojson(f, utm_of(BASE), wrapper=True)
    rc = main(define_args(tmp_path, store, "--polygon", str(f)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 drives, 1 rain" in out
    area = json.loads((store / "areas" / "a3.json").read_text())
    assert area["intersections"] == []
    assert {d["scene"] for d in area["drives"]} == {"scene-1", "scene-2"}
    assert area["epsg"] == 32619
    assert area["buffer_m"] == 10.0
    from shapely.geometry import shape
    assert shape(area["polygon"]).equals_exact(utm_of(BASE.buffer(10)), 1e-6)
    rain = next(d for d in area["drives"] if d["scene"] == "scene-2")
    assert rain["build_input"] is False


def test_make_area_polygon_matches_intersection_selection(tmp_path):
    write_tables(tmp_path, {"scene-1": [(100, 100), (5, 5)], "scene-2": [(0, 5)], "scene-3": [(100, 100)]})
    polys = {A: BASE}
    area_p = make_area("a3", None, [], 10.0, tmp_path, "v1.0-test", "boston-seaport", polygon=BASE)
    area_i = make_area("a3", polys, [A[:8]], 10.0, tmp_path, "v1.0-test", "boston-seaport")
    assert [d["scene"] for d in area_p["drives"]] == [d["scene"] for d in area_i["drives"]]
    from shapely.geometry import shape
    assert shape(area_p["polygon"]).equals_exact(shape(area_i["polygon"]), 1e-6)
    assert area_p["intersections"] == []


def test_load_polygon_geojson_utm_and_wgs84(tmp_path):
    utm_file = tmp_path / "utm.geojson"
    write_geojson(utm_file, utm_of(BASE), wrapper=True)
    g1 = load_polygon_geojson(utm_file)
    assert g1.geom_type == "Polygon"
    assert g1.equals_exact(BASE, 1e-6)

    wgs_file = tmp_path / "wgs.geojson"
    write_geojson(wgs_file, lonlat_of(utm_of(BASE)), wrapper=False)
    g2 = load_polygon_geojson(wgs_file)
    assert g2.geom_type == "Polygon"
    assert g2.equals_exact(BASE, 1e-6)


def test_load_polygon_geojson_accepted_inputs(tmp_path):
    # FeatureCollection with one feature
    fc_file = tmp_path / "fc.geojson"
    doc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": mapping(utm_of(BASE))}]}
    fc_file.write_text(json.dumps(doc))
    g1 = load_polygon_geojson(fc_file)
    assert g1.equals_exact(BASE, 1e-6)

    # MultiPolygon: unioned into one map-frame polygon
    small_mp = shapely.MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)])
    mp_file = tmp_path / "mp.geojson"
    write_geojson(mp_file, utm_of(small_mp), wrapper=True)
    g2 = load_polygon_geojson(mp_file)
    assert g2.equals_exact(small_mp, 1e-6)

    # rebuild round-trips a MultiPolygon saved in EPSG:32619
    small_mp = shapely.MultiPolygon([shapely.box(0, 0, 1, 1), shapely.box(2, 2, 3, 3)])
    area_def = {"location": "boston-seaport", "intersections": [], "buffer_m": 0.0, "polygon": mapping(utm_of(small_mp))}
    rebuilt = _rebuild_poly(area_def, None)
    assert rebuilt.equals_exact(small_mp, 1e-6)


def test_define_cli_wgs84_polygon_saved_in_utm(tmp_path):
    write_tables(tmp_path, {"scene-1": [(100, 100), (5, 5)], "scene-2": [(0, 5)], "scene-3": [(100, 100)]})
    store = tmp_path / "store"
    f = tmp_path / "wgs.geojson"
    write_geojson(f, lonlat_of(utm_of(BASE)), wrapper=False)
    rc = main(define_args(tmp_path, store, "--polygon", str(f)))
    assert rc == 0
    area = json.loads((store / "areas" / "a3.json").read_text())
    from shapely.geometry import shape
    assert shape(area["polygon"]).equals_exact(utm_of(BASE.buffer(10)), 1e-6)
    assert area["epsg"] == 32619
    assert {d["scene"] for d in area["drives"]} == {"scene-1", "scene-2"}


def test_define_cli_rejects_intersection_and_polygon(tmp_path, monkeypatch, capsys):
    write_tables(tmp_path, {"scene-1": [(5, 5)]})
    store = tmp_path / "store"
    f = tmp_path / "poly.geojson"
    write_geojson(f, utm_of(BASE), wrapper=True)
    monkeypatch.setattr(area_mod, "load_intersections", lambda root, location: {A: BASE})
    rc = main(define_args(tmp_path, store, "--intersection", A[:8], "--polygon", str(f)))
    assert rc == 2
    err = capsys.readouterr().err
    assert "--intersection and --polygon are mutually exclusive" in err
    assert not (store / "areas" / "a3.json").exists()


def test_define_cli_requires_one_source(tmp_path, capsys):
    write_tables(tmp_path, {"scene-1": [(5, 5)]})
    store = tmp_path / "store"
    rc = main(define_args(tmp_path, store))
    assert rc == 2
    err = capsys.readouterr().err
    assert "one of --intersection or --polygon is required" in err
    assert not (store / "areas" / "a3.json").exists()


def test_define_intersection_cli_still_works(tmp_path, monkeypatch):
    write_tables(tmp_path, {"scene-1": [(100, 100), (5, 5)], "scene-2": [(0, 5)], "scene-3": [(100, 100)]})
    store = tmp_path / "store"
    monkeypatch.setattr(area_mod, "load_intersections", lambda root, location: {A: BASE})
    rc = main(define_args(tmp_path, store, "--intersection", A[:8]))
    assert rc == 0
    area = json.loads((store / "areas" / "a3.json").read_text())
    assert area["intersections"] == [A]
    assert {d["scene"] for d in area["drives"]} == {"scene-1", "scene-2"}


def test_load_polygon_geojson_validates(tmp_path):
    # 2-feature FeatureCollection
    fc = tmp_path / "fc.geojson"
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(utm_of(BASE))},
        {"type": "Feature", "properties": {}, "geometry": mapping(utm_of(BASE))},
    ]}
    fc.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=re.escape("FeatureCollection must contain exactly 1 feature, found 2")):
        load_polygon_geojson(fc)

    # Point
    pt = tmp_path / "point.geojson"
    write_geojson(pt, shapely.geometry.Point(0, 0), wrapper=False)
    with pytest.raises(ValueError, match=re.escape("unsupported GeoJSON type 'Point'")):
        load_polygon_geojson(pt)

    # empty Polygon
    ep = tmp_path / "empty.geojson"
    ep.write_text(json.dumps({"type": "Polygon", "coordinates": []}))
    with pytest.raises(ValueError, match=re.escape("polygon is empty")):
        load_polygon_geojson(ep)

    # invalid ring (self-crossing)
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps({"type": "Polygon", "coordinates": [[[0,0],[10,10],[0,10],[10,0],[0,0]]]}))
    with pytest.raises(ValueError, match=re.escape("invalid polygon")):
        load_polygon_geojson(bad)

    # structural error reports the actual file path
    short = tmp_path / "short.geojson"
    short.write_text(json.dumps({"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}))
    with pytest.raises(ValueError, match=re.escape(str(short))):
        load_polygon_geojson(short)

    # malformed JSON
    mj = tmp_path / "malformed.geojson"
    mj.write_text("{not json")
    with pytest.raises(ValueError, match=re.escape("cannot read polygon")):
        load_polygon_geojson(mj)

    # non-finite coordinate
    nf = tmp_path / "nf.geojson"
    nf.write_text(json.dumps({"type": "Polygon", "coordinates": [[[0,0],[1,1],[2,float('nan')],[0,0]]]}))
    with pytest.raises(ValueError, match=re.escape("polygon has non-finite coordinates")):
        load_polygon_geojson(nf)

    # empty MultiPolygon
    emp = tmp_path / "emp.geojson"
    emp.write_text(json.dumps({"type": "MultiPolygon", "coordinates": []}))
    with pytest.raises(ValueError, match=re.escape("polygon is empty")):
        load_polygon_geojson(emp)

    # swapped lon/lat (WGS84 plausibility)
    swapped = tmp_path / "swapped.geojson"
    # BASE in map frame -> lonlat, then swap x/y
    ll = lonlat_of(utm_of(BASE))
    swapped_geom = shapely.transform(ll, lambda a: np.column_stack([a[:, 1], a[:, 0]]))
    write_geojson(swapped, swapped_geom, wrapper=False)
    with pytest.raises(ValueError, match=re.escape("polygon is not near the map origin")):
        load_polygon_geojson(swapped)


def test_rebuild_poly_uses_saved_polygon_when_no_intersections():
    area_def = {"location": "boston-seaport", "intersections": [], "buffer_m": 5.0, "polygon": mapping(utm_of(BASE.buffer(5)))}
    assert _rebuild_poly(area_def, None).equals_exact(BASE.buffer(5), 1e-6)


def test_suggest_drives_command_polygon_area(tmp_path, monkeypatch):
    import json as _json
    root = tmp_path / "data"
    ver = "v1.0-test"
    root.mkdir()
    (root / ver).mkdir()
    logs = [{"token": "l", "location": "boston-seaport", "date_captured": "2018-01-01"}]
    scenes = [{"token": "sc0", "name": "scene-1", "log_token": "l", "description": "sunny", "first_sample_token": "s0"}]
    samples = [{"token": "s0", "scene_token": "sc0", "next": ""}]
    sdata = [{"token": "sd0", "sample_token": "s0", "ego_pose_token": "e0", "calibrated_sensor_token": "cs", "is_key_frame": True, "filename": "samples/LIDAR_TOP/x.bin"}]
    ego = [{"token": "e0", "translation": [0, 0, 0], "rotation": [1, 0, 0, 0]}]
    cal = [{"token": "cs", "translation": [0, 0, 0], "rotation": [1, 0, 0, 0]}]
    for name, obj in [("log", logs), ("scene", scenes), ("sample", samples), ("sample_data", sdata), ("ego_pose", ego), ("calibrated_sensor", cal), ("category", []), ("lidarseg", [])]:
        (root / ver / f"{name}.json").write_text(_json.dumps(obj))

    class FakeMap:
        def __init__(self, *a, **k):
            pass
        def get_records_in_patch(self, *a, **k):
            return {"drivable_area": []}
        def get(self, *a, **k):
            return {"polygon_tokens": []}
        def extract_polygon(self, t):
            return shapely.box(0, 0, 1, 1)
    monkeypatch.setattr(area_mod, "nuscenes_map_class", lambda: (lambda **kw: FakeMap()))

    area_path = tmp_path / "a3.json"
    area = make_area("a3", None, [], 0.0, root, ver, "boston-seaport", polygon=BASE)
    area_path.write_text(_json.dumps(area))
    rc = area_mod.suggest_drives_command(str(area_path), 1, dataroot=str(root), store=str(tmp_path), version=ver)
    assert rc == 0


def test_polygon_area_merge_and_twin(tmp_path, monkeypatch):
    # isolate the open3d fake to this test so it does not leak into other modules
    fake = types.ModuleType("open3d")
    monkeypatch.setitem(sys.modules, "open3d", fake)
    from twin import areatwin, merge
    write_tables(tmp_path, {"scene-1": [(100, 100), (5, 5)], "scene-2": [(0, 5)], "scene-3": [(100, 100)]})
    store = tmp_path / "store"
    (store / "areas").mkdir(parents=True, exist_ok=True)
    area = make_area("a3", None, [], 10.0, tmp_path, "v1.0-test", "boston-seaport", include_rain=True, polygon=BASE)
    assert area["drives"]
    (store / "areas" / "a3.json").write_text(json.dumps(area, indent=2) + "\n")

    from shapely.geometry import shape
    poly_shape = shape(area["polygon"])
    def fake_build_drive(sc, work, polygon, params, log):
        assert polygon.equals_exact(poly_shape, 1e-9)
        c = poly_shape.centroid
        return np.array([[c.x, c.y, 0.0, 1.0, 0.0]])
    monkeypatch.setattr(merge, "build_drive", fake_build_drive)

    # pts for merge? merge_area reads drives and builds clouds; stub register_drives.
    names = [d["scene"] for d in area["drives"]]
    def fake_register_drives(*a, **k):
        return {"reference": names[0], "corrections": {k2: np.eye(4) for k2 in names},
                "surfaces": {k2: np.zeros(6) for k2 in names},
                "info": {k2: {} for k2 in names},
                "layer_cells": {k2: 0 for k2 in names}, "pairs": []}
    monkeypatch.setattr(merge, "register_drives", fake_register_drives)
    monkeypatch.setenv("NUSCENES_VERSION", "v1.0-test")
    rc = merge.area_merge_command("a3", store)
    assert rc == 0
    out = store / "areas" / "a3-merged"
    assert (out / "merged.npz").exists()
    assert (out / "drives.json").exists()
    assert (out / "manifest.json").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["data"]["nuscenes_version"] == "v1.0-test"
    drives_json = json.loads((out / "drives.json").read_text())
    assert isinstance(drives_json, list)
    assert [d["scene"] for d in drives_json] == ["scene-1", "scene-2"]
    merged = np.load(out / "merged.npz")
    # merged cloud lies inside polygon
    from shapely.geometry import shape as _shape
    poly = _shape(area["polygon"])
    xs, ys = merged["x"], merged["y"]
    assert len(xs) == 2
    assert np.all(shapely.contains_xy(poly, xs, ys))

    # twin part
    monkeypatch.setattr(areatwin, "parked_vehicles", lambda drives, work, centre, polygon: np.empty((0, 3)))
    class _G:
        POINT_FIELDS = ("x", "y", "z", "intensity", "sweep")
        @staticmethod
        def voxel_first(xyz, voxel_m):
            return np.arange(len(xyz))
        @staticmethod
        def ransac_ground(p, q, seed):
            return None
        @staticmethod
        def split_and_write(*a, **k):
            return StageResult(status="ok", metrics={})
    monkeypatch.setattr(areatwin, "ground", _G())
    monkeypatch.setattr(areatwin, "_stage", lambda ctx, st, params, pipeline: {"seconds": 0.0, "metrics": {}})
    monkeypatch.setattr(areatwin, "support", lambda *a, **k: None)
    # area_inputs returns list of drives? signature (drives, work, polygon) -> tuple[list, list]. Need drivable area feature covering polygon.
    def area_inputs(drives, work, polygon):
        feat = {"type": "Feature", "properties": {"layer": "drivable_area"}, "geometry": mapping(polygon)}
        return ([], [feat])
    monkeypatch.setattr(areatwin, "area_inputs", area_inputs)
    rc2 = areatwin.area_twin_command("a3", store)
    assert rc2 == 0
    twin_out = store / "areas" / "a3-twin"
    assert (twin_out / "change.json").exists()
    change = json.loads((twin_out / "change.json").read_text())
    assert change["area"] == "a3"
    assert change["n_drives"] == 2
    assert (twin_out / "manifest.json").exists()
