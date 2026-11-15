import json

import numpy as np
import shapely

import twin.area_coverage as ac


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
    ac.accumulate_drive(acc, pts, poly, drivable, labels_flat_driveable=np.array([True, True]))
    recs = ac.cell_records(acc, density_threshold_pts_m2=50.0)
    r0 = next(r for r in recs if r["ix"] == 0)
    r1 = next(r for r in recs if r["ix"] == 1)
    assert r0["road_eligible"] is True and r0["drive_count"] == 1
    assert r1["road_eligible"] is False and r1["low_coverage"] is False
    # ineligible excluded from gains: baseline low in r0 only; candidate fixes r0
    # by adding drive_count (>=2) and sampled density above threshold.
    acc2 = ac.init_accumulator(cells)
    ac.accumulate_drive(acc2, pts, poly, drivable, labels_flat_driveable=np.array([True, True]))
    dense = np.array([[x, y, 0.0] for x in np.linspace(0.5, 4.5, 40) for y in np.linspace(0.5, 4.5, 32)])
    ac.accumulate_drive(acc2, dense, poly, drivable, labels_flat_driveable=np.ones(len(dense), bool))
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
    ac.accumulate_drive(acc, pts, poly, drivable, labels_flat_driveable=np.ones(len(pts), bool))
    recs = ac.cell_records(acc, density_threshold_pts_m2=50.0)
    r = recs[0]
    assert r["drive_count"] == 1
    assert r["road_surface_points"] == 2
    assert r["density_pts_m2"] == 2 / 25.0
    assert r["low_coverage"] is True  # drive_count<2 and density < 50

    # add second drive with enough points to exceed sampled density threshold
    acc2 = ac.init_accumulator(cells)
    ac.accumulate_drive(acc2, inside, poly, drivable, labels_flat_driveable=np.ones(2, bool))
    big = np.array([[x, y, 0.0] for x in np.linspace(0.5, 4.5, 40) for y in np.linspace(0.5, 4.5, 32)])
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
    ac.accumulate_drive(acc, np.array([[1, 1, 0.0]]), poly, drivable, labels_flat_driveable=np.array([True]))
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
        "ix", "iy", "x0", "y0", "road_eligible", "drive_count", "density_pts_m2", "road_surface_points", "low_coverage",
    }
    assert json.loads(out.read_text())["cells"] == recs
