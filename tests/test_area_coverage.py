import json

import numpy as np
import pytest
import shapely

import twin.area as area_mod
import twin.area_coverage as ac
from twin import cli


def test_rebuild_map_frame_polygon_and_grid_origin_deterministic():
    # simple unit squares in map frame
    polys = {"a": shapely.box(0, 0, 5, 5), "b": shapely.box(5, 0, 10, 5)}
    poly = ac.rebuild_map_frame_polygon(polys, ["a", "b"], buffer_m=0.0)
    assert poly.area == 50.0
    ox, oy = ac.grid_origin(poly)
    assert (ox, oy) == (0.0, 0.0)
    poly_b = ac.rebuild_map_frame_polygon(polys, ["a"], buffer_m=2.0)
    assert poly_b.bounds[0] == -2.0
    assert ac.grid_origin(poly_b) == (-5.0, -5.0)  # floor(-2/5)*5


def test_road_eligible_i1_intersection_area_and_exclusion():
    # polygon covers [0,10)x[0,5); drivable only covers left cell [0,5)x[0,5)
    poly = shapely.box(0, 0, 10, 5)
    drivable = shapely.box(0, 0, 5, 5)
    cells, _ = ac.build_grid(poly, drivable)
    by_ix = {c.ix: c for c in cells}
    assert by_ix[0].road_eligible is True
    assert by_ix[1].road_eligible is False
    # boundary touch only (edge contact) => intersection area 0, ineligible
    poly2 = shapely.box(0, 0, 5, 5)
    drivable2 = shapely.box(5, 0, 10, 5)
    cells2, _ = ac.build_grid(poly2, drivable2)
    assert all(not c.road_eligible for c in cells2)

    acc = ac.init_accumulator(cells)
    # add a road-surface point in ineligible cell (ix=1) and in eligible (ix=0)
    pts = np.array([[7.5, 2.5, 0.0], [2.5, 2.5, 0.0]])
    ac.accumulate_drive(
        acc, pts, poly, drivable, labels_flat_driveable=np.array([True, True])
    )
    recs = ac.cell_records(acc, density_threshold_pts_m2=50.0)
    r0 = next(r for r in recs if r["ix"] == 0)
    r1 = next(r for r in recs if r["ix"] == 1)
    assert r0["road_eligible"] is True and r0["drive_count"] == 1
    assert r1["road_eligible"] is False and r1["low_coverage"] is False
    # ineligible excluded from gains: baseline low in r0 only; candidate fixes r0
    # by adding drive_count (>=2) and sampled density above threshold.
    acc2 = ac.init_accumulator(cells)
    ac.accumulate_drive(
        acc2, pts, poly, drivable, labels_flat_driveable=np.array([True, True])
    )
    dense = np.array(
        [[x, y, 0.0] for x in np.linspace(0.5, 4.5, 40) for y in np.linspace(0.5, 4.5, 32)]
    )
    ac.accumulate_drive(
        acc2, dense, poly, drivable, labels_flat_driveable=np.ones(len(dense), bool)
    )
    base = ac.cell_records(acc)
    cand = ac.cell_records(acc2)
    assert ac.low_coverage_cells(base) == {(0, 0)}
    assert ac.cells_gained(base, cand) == 1


def test_ground_class_primary_and_geometric_fallback_same_union():
    drivable = shapely.box(0, 0, 5, 5)
    # 3 points on road plane, 1 raised (above tol) - all inside drivable
    pts = np.array([[1, 1, 0.0], [2, 2, 0.0], [3, 3, 0.0], [4, 4, 1.0]])
    labels = np.array([True, True, False, False])  # only first two are driveable by lidarseg
    mask_l, src_l = ac.road_surface_mask(pts, drivable, labels_flat_driveable=labels)
    assert src_l == "lidarseg_flat.driveable_surface"
    assert mask_l.tolist() == [True, True, False, False]
    mask_g, src_g = ac.road_surface_mask(pts, drivable, labels_flat_driveable=None)
    assert src_g == "geometric_road_mask_fallback"
    # geometric keeps 3 ground-z-close, drops raised 1m point
    assert mask_g.tolist() == [True, True, True, False]


def test_covered_predicate_points_outside_area_ignored_and_density_threshold():
    poly = shapely.box(0, 0, 5, 5)
    drivable = shapely.box(0, 0, 5, 5)
    cells, _ = ac.build_grid(poly, drivable)
    assert len(cells) == 1
    acc = ac.init_accumulator(cells)
    # 2 inside road-surface points (density 0.08) + many outside polygon ignored
    inside = np.array([[1, 1, 0.0], [2, 2, 0.0]])
    outside = np.array([[10, 10, 0.0], [20, 20, 0.0]])
    pts = np.vstack([inside, outside])
    ac.accumulate_drive(
        acc, pts, poly, drivable, labels_flat_driveable=np.ones(len(pts), bool)
    )
    recs = ac.cell_records(acc, density_threshold_pts_m2=50.0)
    r = recs[0]
    assert r["drive_count"] == 1
    assert r["road_surface_points"] == 2
    assert r["density_pts_m2"] == 2 / 25.0
    assert r["low_coverage"] is True  # drive_count<2 and density < 50

    # add second drive with enough points to exceed sampled density threshold
    acc2 = ac.init_accumulator(cells)
    ac.accumulate_drive(acc2, inside, poly, drivable, labels_flat_driveable=np.ones(2, bool))
    big = np.array(
        [[x, y, 0.0] for x in np.linspace(0.5, 4.5, 40) for y in np.linspace(0.5, 4.5, 32)]
    )
    # 1280 points in 25m2 -> 51.2 pts/m2 sampled density
    ac.accumulate_drive(acc2, big, poly, drivable, labels_flat_driveable=np.ones(len(big), bool))
    r2 = ac.cell_records(acc2, density_threshold_pts_m2=50.0)[0]
    assert r2["drive_count"] == 2
    assert r2["density_pts_m2"] > 50.0
    assert r2["low_coverage"] is False


def test_coverage_json_structure_order_and_metadata(tmp_path):
    poly = shapely.box(0, 0, 10, 5)
    drivable = shapely.box(0, 0, 10, 5)
    cells, origin = ac.build_grid(poly, drivable)
    acc = ac.init_accumulator(cells)
    ac.accumulate_drive(
        acc, np.array([[1, 1, 0.0]]), poly, drivable, labels_flat_driveable=np.array([True])
    )
    recs = ac.cell_records(acc)
    # deterministic order by (ix,iy): (0,0),(1,0)
    assert [(r["ix"], r["iy"]) for r in recs] == [(0, 0), (1, 0)]
    doc = ac.coverage_document(
        "seaport",
        tmp_path / "areas" / "seaport.json",
        "boston-seaport",
        origin,
        recs,
        density_threshold_pts_m2=50.0,
        ground_sources=["lidarseg_flat.driveable_surface"],
        baseline_scene_tokens=["tokA"],
        extra_metadata={
            "epsg_persisted_polygon": 32619,
            "dataset_version_area": "v1.0-test",
            "suggest_version": "v1.0-trainval",
            "generated_with": "twin.area_coverage",
        },
    )
    assert doc["schema_version"] == 1
    assert doc["frame"] == "nuScenes-local-tmerc"
    assert doc["cell_m"] == 5.0
    assert doc["density_threshold_pts_m2"] == 50.0
    assert doc["sweep_step"] == 4
    assert doc["density_semantics"] == "sampled_every_4th_keyframe"
    assert doc["grid_origin_map"] == [0.0, 0.0]
    assert doc["epsg_persisted_polygon"] == 32619
    out = tmp_path / "areas" / "seaport.coverage.json"
    ac.atomic_write_json(out, doc)
    loaded = ac.read_json(out)
    assert loaded["cells"][0].keys() >= {
        "ix",
        "iy",
        "x0",
        "y0",
        "road_eligible",
        "drive_count",
        "density_pts_m2",
        "road_surface_points",
        "low_coverage",
    }
    assert json.loads(out.read_text())["cells"] == recs


# --- M2 suggest-drives / ranking / CLI / apply tests (synthetic/mocked) ---


class FakeNusc:
    def __init__(
        self, scenes, samples_by_scene, sample_data_by_sample, ego_poses, lidar_points_by_sd=None
    ):
        self.scenes = scenes
        self.samples_by_scene = samples_by_scene
        self.sample_data_by_sample = sample_data_by_sample
        self.ego_poses = ego_poses
        self.lidar_points_by_sd = lidar_points_by_sd or {}
        self.dataroot = "."
        self.lidarseg_name2idx_mapping = {}
        self.category = []

    def get(self, table, token):
        if table == "scene":
            return self.scenes[token]
        if table == "sample":
            # token is sample token
            for samples in self.samples_by_scene.values():
                for item in samples:
                    if item["token"] == token:
                        return item
        if table == "sample_data":
            return self.sample_data_by_sample[token]
        if table == "calibrated_sensor":
            return {"rotation": [1, 0, 0, 0], "translation": [0, 0, 0]}
        if table == "ego_pose":
            return self.ego_poses[token]
        if table == "lidarseg":
            raise KeyError(token)
        raise KeyError((table, token))

    def get_sample_data_path(self, sd_token):
        return sd_token  # not used; we monkeypatch LidarPointCloud


class FakeMap:
    def __init__(self, drivable_by_bounds=None):
        self.drivable_by_bounds = drivable_by_bounds or {}

    def get_records_in_patch(self, bounds, layer_names, mode):
        assert layer_names == ["drivable_area"]
        assert mode == "intersect"
        key = tuple(round(float(x), 6) for x in bounds)
        return {"drivable_area": list(self.drivable_by_bounds.get(key, []))}

    def get(self, layer, token):
        assert layer == "drivable_area"
        return {"polygon_tokens": [token]}

    def extract_polygon(self, token):
        # token itself is a shapely geometry in tests
        return token


def _write_tables(root, version, *, logs, scenes, samples, sample_data, ego_pose):
    v = root / version
    v.mkdir(parents=True, exist_ok=True)

    def w(name, obj):
        (v / f"{name}.json").write_text(json.dumps(obj))

    w("log", logs)
    w("scene", scenes)
    w("sample", samples)
    w("sample_data", sample_data)
    w("ego_pose", ego_pose)


def test_accumulate_drive_observations_handles_mixed_sources(monkeypatch):
    poly = shapely.box(0, 0, 5, 5)
    drivable = shapely.box(0, 0, 5, 5)
    cells, origin = ac.build_grid(poly, drivable)
    acc = ac.init_accumulator(cells)
    pts = np.array([[1.0, 1.0, 0.0]], dtype=float)

    def fake_samples(nusc, scene_token, polygon, step):
        yield pts, np.array([True])
        yield pts, None

    monkeypatch.setattr(area_mod, "_sampled_lidar_points_for_scene", fake_samples)
    src = area_mod._accumulate_drive_observations(
        acc, object(), "tok", poly, drivable, ac.SWEEP_STEP, origin[0], origin[1]
    )
    assert src == ["geometric_road_mask_fallback", "lidarseg_flat.driveable_surface"]
    assert _flatten_sources_for_test([src]) == src
    # one distinct drive across two sampled keyframes must count once per covered cell
    recs = ac.cell_records(acc)
    assert len(recs) == 1
    assert recs[0]["drive_count"] == 1
    assert recs[0]["road_surface_points"] == 2


def test_single_drive_multiple_sampled_keyframes_counts_once():
    poly = shapely.box(0, 0, 5, 5)
    drivable = shapely.box(0, 0, 5, 5)
    cells, origin = ac.build_grid(poly, drivable)
    acc = ac.init_accumulator(cells)
    kf1 = np.array([[1.0, 1.0, 0.0], [2.0, 2.0, 0.0]])
    kf2 = np.array([[3.0, 3.0, 0.0]])
    labels1 = np.ones(len(kf1), bool)
    labels2 = np.ones(len(kf2), bool)
    covered_all = set()
    for pts, labels in [(kf1, labels1), (kf2, labels2)]:
        _, covered = ac.accumulate_drive_points(
            acc,
            pts,
            poly,
            drivable,
            labels_flat_driveable=labels,
            ox=origin[0],
            oy=origin[1],
            count_drive=False,
        )
        covered_all.update(covered)
    ac.mark_drive_coverage(acc, covered_all)
    recs = ac.cell_records(acc)
    assert len(recs) == 1
    r = recs[0]
    assert r["drive_count"] == 1
    assert r["road_surface_points"] == 3
    assert r["density_pts_m2"] == 3 / 25.0


def _flatten_sources_for_test(values):
    out = set()
    for v in values:
        if isinstance(v, list):
            out.update(v)
        else:
            out.add(v)
    return sorted(out)



def test_ranking_pinned_m3_example_and_diversity_vs_existing_area_only():
    # baseline area drives: sunny/day only (no rain, no night, has day bucket)
    existing = [{"scene": "base", "scene_token": "tb", "description": "Clear day"}]
    base = [
        {
            "ix": i,
            "iy": 0,
            "road_eligible": True,
            "low_coverage": True,
            "drive_count": 0,
            "density_pts_m2": 0.0,
            "road_surface_points": 0,
            "x0": 0.0,
            "y0": 0.0,
        }
        for i in range(5)
    ]

    def fixed_cells(n):
        return [
            {
                **base[i],
                "low_coverage": i >= n,
                "drive_count": 2 if i < n else 0,
                "density_pts_m2": 100.0 if i < n else 0.0,
            }
            for i in range(5)
        ]

    candidates = [
        {
            "scene": "s-010",
            "scene_token": "t2",
            "description": "night drive",
            "candidate_records": fixed_cells(5),
        },  # A
        {
            "scene": "s-010",
            "scene_token": "t1",
            "description": "rain unknown",
            "candidate_records": fixed_cells(5),
        },  # B
        {
            "scene": "s-005",
            "scene_token": "t9",
            "description": "clear day",
            "candidate_records": fixed_cells(5),
        },  # C
        {
            "scene": "s-001",
            "scene_token": "t0",
            "description": "rain night",
            "candidate_records": fixed_cells(4),
        },  # D
    ]
    ranked = ac.rank_candidates(candidates, base, existing, top_n=10)
    assert [r["scene_token"] for r in ranked] == ["t2", "t1", "t9", "t0"]
    assert ranked[0]["diversity"] == 2
    assert ranked[1]["diversity"] == 1
    assert ranked[2]["diversity"] == 0
    # diversity vs existing area drives only (not greedy): if existing had night, A loses bonus
    existing2 = [{"scene": "base", "scene_token": "tb", "description": "night day"}]
    ranked2 = ac.rank_candidates([candidates[0], candidates[1]], base, existing2, top_n=10)
    assert ranked2[0]["scene_token"] == "t1"


def test_time_of_day_precedence_and_flags():
    assert ac.time_of_day_bucket("Rainy night in the morning") == "night"
    assert ac.time_of_day_bucket("dawn patrol") == "dawn"
    assert ac.time_of_day_bucket("late evening dusk? dusk first") == "dusk"
    assert ac.time_of_day_bucket("sunny afternoon day") == "afternoon"
    assert ac.time_of_day_bucket("clear skies") == "unknown"
    f = ac.drive_flags("Night, rain")
    assert f["rain"] is True and f["night"] is True and f["time_of_day_bucket"] == "night"


def test_resolve_area_z1_and_missing_lists_tried(tmp_path):
    store = tmp_path / "store"
    (store / "areas").mkdir(parents=True)
    target = store / "areas" / "seaport.json"
    target.write_text(
        json.dumps(
            {
                "name": "seaport",
                "location": "boston-seaport",
                "intersections": ["a" * 32],
                "buffer_m": 0,
                "drives": [],
            }
        )
    )
    resolved = area_mod.resolve_area_arg("areas/seaport.json", store)
    assert resolved == target.resolve()
    resolved2 = area_mod.resolve_area_arg("seaport.json", store)
    assert resolved2 == target.resolve()
    with pytest.raises(FileNotFoundError) as ei:
        area_mod.resolve_area_arg("nope.json", store)
    msg = str(ei.value)
    assert "tried paths:" in msg
    assert "nope.json" in msg
    assert str((store / "nope.json").resolve()) in msg or str(store / "nope.json") in msg
    assert str((store / "areas" / "nope.json").resolve()) in msg or str(
        store / "areas" / "nope.json"
    ) in msg


def test_suggest_drives_cli_arg_validation_and_missing_area_exit2(tmp_path, capsys):
    store = tmp_path / "store"
    store.mkdir()
    root = tmp_path / "data"
    root.mkdir()
    assert (
        cli.main(
            [
                "area",
                "suggest-drives",
                "missing.json",
                "--top",
                "0",
                "--store",
                str(store),
                "--dataroot",
                str(root),
            ]
        )
        == 2
    )
    assert "--top" in capsys.readouterr().err
    assert (
        cli.main(
            [
                "area",
                "suggest-drives",
                "missing.json",
                "--top",
                "1",
                "--density-threshold",
                "-1",
                "--store",
                str(store),
                "--dataroot",
                str(root),
            ]
        )
        == 2
    )
    assert "density-threshold" in capsys.readouterr().err
    rc = cli.main(
        [
            "area",
            "suggest-drives",
            "areas/seaport.json",
            "--top",
            "1",
            "--store",
            str(store),
            "--dataroot",
            str(root),
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "tried paths:" in err
    assert str(store / "areas" / "seaport.json") in err or "seaport.json" in err


def test_suggest_drives_missing_tables_exit2(tmp_path, capsys):
    store = tmp_path / "store"
    (store / "areas").mkdir(parents=True)
    area_path = store / "areas" / "seaport.json"
    area_path.write_text(
        json.dumps(
            {
                "name": "seaport",
                "location": "boston-seaport",
                "epsg": 32619,
                "buffer_m": 0.0,
                "intersections": ["a" * 32],
                "dataset_version": "v1.0-test",
                "drives": [],
                "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            }
        )
    )
    root = tmp_path / "data"
    root.mkdir()
    rc = area_mod.suggest_drives_command(
        "areas/seaport.json", 1, 50.0, False, root, store, version="v1.0-trainval"
    )
    assert rc == 2
    assert "missing dataset table" in capsys.readouterr().err


def test_suggest_drives_invalid_area_json_exit2(tmp_path, capsys):
    store = tmp_path / "store"
    (store / "areas").mkdir(parents=True)
    (store / "areas" / "bad.json").write_text("{not-json")
    root = tmp_path / "data"
    version = "v1.0-trainval"
    _write_tables(
        root,
        version,
        logs=[],
        scenes=[],
        samples=[],
        sample_data=[],
        ego_pose=[],
    )
    rc = area_mod.suggest_drives_command(
        "areas/bad.json", 1, 50.0, False, root, store, version=version
    )
    assert rc == 2
    assert "failed to read area JSON" in capsys.readouterr().err
    (store / "areas" / "bad.json").write_text(json.dumps(["not", "object"]))
    rc2 = area_mod.suggest_drives_command(
        "areas/bad.json", 1, 50.0, False, root, store, version=version
    )
    assert rc2 == 2
    assert "area JSON must be an object" in capsys.readouterr().err


def _setup_suggest_env(
    tmp_path,
    monkeypatch,
    *,
    baseline_drives=None,
    candidate_scene=True,
):
    store = tmp_path / "store"
    (store / "areas").mkdir(parents=True)
    inter = "a" * 32
    area_path = store / "areas" / "seaport.json"
    if baseline_drives is None:
        baseline_drives = [
            {
                "scene": "base",
                "scene_token": "base_tok",
                "date": "2018-01-01",
                "description": "clear day",
                "rain": False,
                "build_input": True,
            }
        ]
    area_def = {
        "name": "seaport",
        "location": "boston-seaport",
        "epsg": 32619,
        "buffer_m": 0.0,
        "intersections": [inter],
        "dataset_version": "v1.0-test",
        "drives": baseline_drives,
        "polygon": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 5], [0, 5], [0, 0]]]},
        "extra_top": "keepme",
    }
    area_path.write_text(json.dumps(area_def, indent=2) + "\n")
    root = tmp_path / "data"
    version = "v1.0-trainval"
    logs = [{"token": "log1", "location": "boston-seaport", "date_captured": "2018-02-01"}]
    scenes = [{"token": "base_tok", "name": "base", "log_token": "log1", "description": "clear day"}]
    samples = [{"token": "s0", "scene_token": "base_tok"}]
    sds = [{"token": "sd0", "sample_token": "s0", "ego_pose_token": "ep0"}]
    ego = [{"token": "ep0", "translation": [2.5, 2.5, 0.0]}]
    if candidate_scene:
        scenes.append(
            {"token": "cand_tok", "name": "cand", "log_token": "log1", "description": "rain night"}
        )
        samples.append({"token": "s1", "scene_token": "cand_tok"})
        sds.append({"token": "sd1", "sample_token": "s1", "ego_pose_token": "ep1"})
        ego.append({"token": "ep1", "translation": [2.5, 2.5, 0.0]})
    _write_tables(
        root,
        version,
        logs=logs,
        scenes=scenes,
        samples=samples,
        sample_data=sds,
        ego_pose=ego,
    )
    poly = shapely.box(0, 0, 10, 5)
    drivable = shapely.box(0, 0, 10, 5)
    monkeypatch.setattr(area_mod, "load_intersections", lambda dataroot, location: {inter: poly})
    monkeypatch.setattr(area_mod, "_drivable_union", lambda nusc_map, bounds: drivable)
    import twin.devkit_compat as dc

    monkeypatch.setattr(dc, "nuscenes_map_class", lambda: (lambda **kw: FakeMap()))
    fake = FakeNusc(
        {
            s["token"]: {
                **s,
                "first_sample_token": "s0" if s["token"] == "base_tok" else "s1",
            }
            for s in scenes
        },
        {
            "base_tok": [{"token": "s0", "next": "", "data": {}}],
            "cand_tok": [{"token": "s1", "next": "", "data": {}}] if candidate_scene else [],
        },
        {},
        {e["token"]: {"translation": e["translation"], "rotation": [1, 0, 0, 0]} for e in ego},
    )
    return store, root, version, poly, drivable, area_path, area_def, fake


def test_suggest_drives_empty_candidates_exit0_writes_coverage_and_apply(
    tmp_path, monkeypatch, capsys
):
    store, root, version, poly, drivable, area_path, area_def, fake = _setup_suggest_env(
        tmp_path, monkeypatch, candidate_scene=False
    )
    rc = area_mod.suggest_drives_command(
        "areas/seaport.json",
        3,
        50.0,
        False,
        root,
        store,
        version=version,
        _nusc_factory=lambda **kw: fake,
        _nusc_map_factory=lambda **kw: FakeMap(
            {tuple(round(x, 6) for x in poly.bounds): [drivable]}
        ),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "scene" in out and "scene_token" in out and "cells_gained" in out
    cov = store / "areas" / "seaport.coverage.json"
    assert cov.exists()
    doc = json.loads(cov.read_text())
    assert doc["schema_version"] == 1
    assert doc["frame"] == "nuScenes-local-tmerc"
    assert doc["density_threshold_pts_m2"] == 50.0
    assert doc["sweep_step"] == 4
    assert doc["density_semantics"] == "sampled_every_4th_keyframe"
    assert doc["area_path"] == str(area_path.resolve())
    assert doc["area_resolved_path"] == str(area_path.resolve())
    assert doc["store"] == str(store.resolve())
    keys = [(c["ix"], c["iy"]) for c in doc["cells"]]
    assert keys == sorted(keys)
    # apply with no available should not corrupt file
    rc2 = area_mod.suggest_drives_command(
        "areas/seaport.json",
        3,
        50.0,
        True,
        root,
        store,
        version=version,
        _nusc_factory=lambda **kw: fake,
        _nusc_map_factory=lambda **kw: FakeMap(
            {tuple(round(x, 6) for x in poly.bounds): [drivable]}
        ),
    )
    assert rc2 == 0
    after = json.loads(area_path.read_text())
    assert after["extra_top"] == "keepme"
    assert after["drives"] == area_def["drives"]


def test_suggest_drives_apply_appends_ranked_preserves_schema_dedupes_and_atomic(
    tmp_path, monkeypatch, capsys
):
    store, root, version, poly, drivable, area_path, area_def, fake = _setup_suggest_env(
        tmp_path, monkeypatch, candidate_scene=True
    )
    area_def["z_top"] = 1
    area_def.pop("extra_top", None)
    area_path.write_text(json.dumps(area_def, indent=2) + "\n")

    def fake_obs(acc, nusc, scene_token, polygon, drivable_union, step, ox, oy):
        if scene_token == "cand_tok":
            pts = np.array(
                [
                    [x, y, 0.0]
                    for x in np.linspace(0.5, 9.5, 60)
                    for y in np.linspace(0.5, 4.5, 30)
                ]
            )
            return ac.accumulate_drive(
                acc,
                pts,
                polygon,
                drivable_union,
                labels_flat_driveable=np.ones(len(pts), bool),
                ox=ox,
                oy=oy,
            )
        return "geometric_road_mask_fallback"

    monkeypatch.setattr(area_mod, "_accumulate_drive_observations", fake_obs)
    rc = area_mod.suggest_drives_command(
        "areas/seaport.json",
        5,
        50.0,
        True,
        root,
        store,
        version=version,
        _nusc_factory=lambda **kw: fake,
        _nusc_map_factory=lambda **kw: FakeMap(
            {tuple(round(x, 6) for x in poly.bounds): [drivable]}
        ),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "cand_tok" in out
    cov = store / "areas" / "seaport.coverage.json"
    assert cov.exists()
    doc = json.loads(cov.read_text())
    assert doc["store"] == str(store.resolve())
    assert doc["suggest_version"] == version
    assert doc["area_resolved_path"] == str(area_path.resolve())
    after = json.loads(area_path.read_text())
    assert after["z_top"] == 1
    assert len(after["drives"]) == 2
    added = after["drives"][1]
    assert added == {
        "scene": "cand",
        "scene_token": "cand_tok",
        "date": "2018-02-01",
        "description": "rain night",
        "rain": True,
        "build_input": False,
    }
    # dedupe: run again should not duplicate
    rc2 = area_mod.suggest_drives_command(
        "areas/seaport.json",
        5,
        50.0,
        True,
        root,
        store,
        version=version,
        _nusc_factory=lambda **kw: fake,
        _nusc_map_factory=lambda **kw: FakeMap(
            {tuple(round(x, 6) for x in poly.bounds): [drivable]}
        ),
    )
    assert rc2 == 0
    after2 = json.loads(area_path.read_text())
    assert len(after2["drives"]) == 2
    raw = area_path.read_text()
    assert raw.endswith("\n")


def test_suggest_drives_mixed_ground_source_writes_coverage_and_applies(
    tmp_path, monkeypatch, capsys
):
    store, root, version, poly, drivable, area_path, _area_def, fake = _setup_suggest_env(
        tmp_path, monkeypatch, candidate_scene=True
    )

    def fake_obs(acc, nusc, scene_token, polygon, drivable_union, step, ox, oy):
        if scene_token == "cand_tok":
            pts = np.array(
                [
                    [x, y, 0.0]
                    for x in np.linspace(0.5, 9.5, 60)
                    for y in np.linspace(0.5, 4.5, 30)
                ]
            )
            ac.accumulate_drive(
                acc,
                pts,
                polygon,
                drivable_union,
                labels_flat_driveable=np.ones(len(pts), bool),
                ox=ox,
                oy=oy,
            )
            ac.accumulate_drive(
                acc,
                pts,
                polygon,
                drivable_union,
                labels_flat_driveable=None,
                ox=ox,
                oy=oy,
            )
            return ["geometric_road_mask_fallback", "lidarseg_flat.driveable_surface"]
        return "geometric_road_mask_fallback"

    monkeypatch.setattr(area_mod, "_accumulate_drive_observations", fake_obs)
    rc = area_mod.suggest_drives_command(
        "areas/seaport.json",
        5,
        50.0,
        True,
        root,
        store,
        version=version,
        _nusc_factory=lambda **kw: fake,
        _nusc_map_factory=lambda **kw: FakeMap(
            {tuple(round(x, 6) for x in poly.bounds): [drivable]}
        ),
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "cand_tok" in out
    cov = store / "areas" / "seaport.coverage.json"
    assert cov.exists(), "coverage.json must be written despite mixed ground sources"
    doc = json.loads(cov.read_text())
    assert doc["ground_sources"] == [
        "geometric_road_mask_fallback",
        "lidarseg_flat.driveable_surface",
    ]
    assert doc["area_resolved_path"] == str(area_path.resolve())
    assert doc["store"] == str(store.resolve())
    after = json.loads(area_path.read_text())
    assert after["drives"][-1]["scene_token"] == "cand_tok"
