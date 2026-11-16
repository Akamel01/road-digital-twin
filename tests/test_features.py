"""Stage 5 features: synthetic ground with stripes, no devkit, no data."""

import json
import logging
import math

import laspy
import numpy as np
from shapely.geometry import shape

from twin import registry
from twin.contracts import FeaturesParams, GroundParams
from twin.runner import StageContext
from twin.stages.ground import ransac_ground, surface_grid

STRIPE = 200.0
ARC_R = 30.0
ARC_CENTRE = (0.0, -30.0)


def _background(rng):
    """Road-like ground far from the stripes: 0.1 m spacing, intensity 0-30."""
    x, y = np.meshgrid(
        np.arange(-15.0, 15.0, 0.1), np.arange(40.0, 50.0, 0.1), indexing="ij"
    )
    x, y = x.ravel(), y.ravel()
    return np.column_stack([x, y, np.zeros_like(x), rng.uniform(0, 30, x.size)])


def _band(xs, ys, half=0.25):
    """Solid stripe sampled at 0.1 m: points on a grid of ys (across) for each xs (along)."""
    gx, gy = np.meshgrid(xs, np.arange(-half, half + 1e-9, 0.1), indexing="ij")
    gx, gy = gx.ravel(), gy.ravel()
    return np.column_stack([gx, gy, np.zeros_like(gx), np.full(gx.size, STRIPE)])


def _ground_with(rng, stripes):
    return np.vstack([_background(rng), *stripes])


def _lane_and_crosswalk(rng):
    lane = _band(np.arange(0.0, 10.0, 0.1), np.array([5.0]))
    lane[:, 1] += 5.0 - lane[:, 1].mean()  # centre the stripe on y = 5
    stripes = [lane]
    for k in range(5):
        x0 = 20.0 + k
        gy, gx = np.meshgrid(
            np.arange(0.0, 4.0, 0.1), np.arange(x0, x0 + 0.5, 0.1), indexing="ij"
        )
        n = gx.size
        stripes.append(
            np.column_stack([gx.ravel(), gy.ravel(), np.zeros(n), np.full(n, STRIPE)])
        )
    return _ground_with(rng, stripes)


def _arc(rng):
    """Solid curved line: arc radius 30 m, 20 m chord, 0.5 m wide, centred on ARC_CENTRE."""
    alpha = np.arcsin(10.0 / ARC_R)
    phi = np.arange(np.pi / 2 - alpha, np.pi / 2 + alpha, 0.1 / ARC_R)
    pts = []
    for d in np.arange(-0.25, 0.2501, 0.1):
        r = ARC_R + d
        x = ARC_CENTRE[0] + r * np.cos(phi)
        y = ARC_CENTRE[1] + r * np.sin(phi)
        pts.append(np.column_stack([x, y, np.zeros_like(x), np.full(x.size, STRIPE)]))
    return _ground_with(rng, pts)


def _gapped_line(rng):
    """Solid stripe along x at y = 0 with a 3 m occluded gap, x 6 to 9."""
    xs = np.arange(0.0, 15.0, 0.1)
    xs = xs[(xs < 6.0) | (xs >= 9.0)]
    return _ground_with(rng, [_band(xs, np.array([0.0]))])


def _write_nonground_and_surface(ground_dir, ground_xyzi, nonground_xyzi):
    """nonground.laz and surface.npz as the ground stage writes them (0.5 m mean-z grid)."""
    if nonground_xyzi is None:
        nonground_xyzi = np.empty((0, 4))
    allp = np.vstack([ground_xyzi[:, :3], nonground_xyzi[:, :3]])
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001] * 3)
    header.offsets = allp.min(axis=0)
    las = laspy.LasData(header)
    las.xyz = nonground_xyzi[:, :3]
    las.intensity = nonground_xyzi[:, 3].astype(np.uint16)
    las.write(ground_dir / "nonground.laz")
    origin = ground_xyzi[:, :2].min(axis=0)
    span = np.floor((ground_xyzi[:, :2].max(axis=0) - origin) / 0.5).astype(int)
    shape = (int(span[1]) + 1, int(span[0]) + 1)
    zmean, count = surface_grid(
        ground_xyzi[:, :2], ground_xyzi[:, 2], origin, 0.5, shape
    )
    np.savez_compressed(
        ground_dir / "surface.npz",
        z=zmean,
        count=count,
        origin=origin,
        cell_m=np.float64(0.5),
    )


def _ctx(tmp_path, ground_xyzi, nonground_xyzi=None):
    run = tmp_path / "run"
    (run / "4_ground").mkdir(parents=True)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001] * 3)
    header.offsets = ground_xyzi[:, :3].min(axis=0)
    las = laspy.LasData(header)
    las.xyz = ground_xyzi[:, :3]
    las.intensity = ground_xyzi[:, 3].astype(np.uint16)
    las.write(run / "4_ground" / "ground.laz")
    _write_nonground_and_surface(run / "4_ground", ground_xyzi, nonground_xyzi)
    (run / "4_ground" / "qa.json").write_text(
        json.dumps({"height_valid": True, "not_scanned_enough": ["S-0001"]})
    )
    (run / "3_align").mkdir()
    (run / "3_align" / "qa.json").write_text(
        json.dumps(
            {
                "method": "kiss-icp",
                "fallback_used": False,
                "fallback_reason": None,
                "xy_drift_p95_m": 0.12,
            }
        )
    )
    return StageContext(
        run_dir=run, scene_token="s", seed=0, log=logging.getLogger("t")
    )


def _run(tmp_path, ground):
    ctx = _ctx(tmp_path, ground)
    result = registry.lookup("features", "intensity")(ctx, FeaturesParams())
    assert result.status == "ok"
    out = ctx.stage_dir("features")
    markings = json.loads((out / "markings.geojson").read_text())["features"]
    crosswalks = json.loads((out / "crosswalks.geojson").read_text())["features"]
    return markings, crosswalks, out


def test_lane_and_crosswalk_found_in_place(tmp_path):
    markings, crosswalks, out = _run(
        tmp_path, _lane_and_crosswalk(np.random.default_rng(0))
    )

    assert len(markings) == 1
    m = markings[0]
    assert m["properties"]["kind"] == "marking"
    (x0, y0, _), (x1, y1, _) = (
        m["geometry"]["coordinates"][0],
        m["geometry"]["coordinates"][-1],
    )
    assert x0 < 1.0 and x1 > 9.0  # bin medians: first and last 1 m bins
    assert abs(y0 - 5.0) < 0.2 and abs(y1 - 5.0) < 0.2

    assert len(crosswalks) == 1
    cw = crosswalks[0]
    assert cw["properties"]["kind"] == "crosswalk"
    assert cw["properties"]["stripes"] == 5
    minx, miny, maxx, maxy = shape(cw["geometry"]).bounds
    assert minx < 20.1 and maxx > 24.3
    assert miny < 0.1 and maxy > 3.85

    qa = json.loads((out / "qa.json").read_text())
    assert qa["height_valid"] is True
    assert qa["not_scanned_enough"] == ["S-0001"]


def test_curved_line_follows_the_arc(tmp_path):
    markings, _, _ = _run(tmp_path, _arc(np.random.default_rng(0)))

    assert len(markings) == 1
    coords = np.array(markings[0]["geometry"]["coordinates"])
    cx, cy = ARC_CENTRE
    radial_error = np.abs(np.hypot(coords[:, 0] - cx, coords[:, 1] - cy) - ARC_R)
    assert radial_error.max() < 0.05
    assert len(coords) >= 15  # about 20 m of arc in 1 m bins


def test_occluded_gap_splits_the_line(tmp_path):
    markings, _, _ = _run(tmp_path, _gapped_line(np.random.default_rng(0)))

    assert len(markings) == 2
    for m in markings:
        xs = np.array(m["geometry"]["coordinates"])[:, 0]
        assert xs.max() <= 6.5 or xs.min() >= 8.5  # nothing bridges the gap


def test_every_feature_carries_evidence_and_density(tmp_path):
    markings, crosswalks, _ = _run(
        tmp_path, _lane_and_crosswalk(np.random.default_rng(0))
    )

    for m in markings:
        p = m["properties"]
        # no lidarseg in this synthetic run: kept, with the note
        assert p["evidence"] == ["lidar", "lidarseg: insufficient labels"]
        assert p["reliability"] == "observed"
        assert p["n_points"] > 0
        assert p["points_per_m"] == round(p["n_points"] / p["length_m"], 3)
    for c in crosswalks:
        p = c["properties"]
        assert p["evidence"] == ["lidar"]
        assert p["reliability"] == "observed"
        assert p["n_points"] > 0
        assert p["points_per_m2"] == round(p["n_points"] / p["area_m2"], 3)


def test_min_points_removes_isolated_noise(tmp_path):
    rng = np.random.default_rng(1)
    ground = _background(rng)
    ground[:, 3] = rng.uniform(0, 30, len(ground))  # no stripes at all
    markings, crosswalks, _ = _run(tmp_path, ground)
    assert markings == []
    assert crosswalks == []


def test_marking_height_is_measured_per_vertex():
    """A stripe on a 4% grade keeps its grade: each vertex z is the bin's median, not a flat mean."""
    from twin.stages.features import binned_pieces

    x = np.linspace(0, 10, 400)
    xyz = np.column_stack([x, np.zeros_like(x), 0.04 * x])
    pieces = binned_pieces(xyz, np.array([5.0, 0.0]), np.array([1.0, 0.0]))
    assert len(pieces) == 1
    verts = pieces[0][0]
    assert np.allclose(verts[:, 2], 0.04 * verts[:, 0], atol=0.01)


def _road_with_curb(rng, step, edge=0.0):
    """Flat road (x < edge) and a sidewalk `step` m higher (x >= edge), 20 m along y. 5 mm noise, 0.05 m spacing."""
    x, y = np.meshgrid(
        np.arange(-10.0, 10.0, 0.05), np.arange(0.0, 20.0, 0.05), indexing="ij"
    )
    x, y = x.ravel(), y.ravel()
    z = np.where(x >= edge, step, 0.0) + rng.normal(0, 0.005, x.size)
    return np.column_stack([x, y, z, rng.uniform(0, 30, x.size)])


def _curb_run(tmp_path, ground, nonground=None, **curbs):
    ctx = _ctx(tmp_path, ground, nonground)
    result = registry.lookup("features", "intensity")(ctx, FeaturesParams(curbs=curbs))
    assert result.status == "ok"
    return result, ctx.stage_dir("features")


def test_curb_step_is_found(tmp_path):
    result, out = _curb_run(tmp_path, _road_with_curb(np.random.default_rng(0), 0.15))

    assert "curbs.geojson" in result.files
    curbs = json.loads((out / "curbs.geojson").read_text())["features"]
    assert len(curbs) == 1
    p = curbs[0]["properties"]
    assert p["kind"] == "curb"
    assert p["evidence"] == ["lidar"]
    assert p["reliability"] == "observed"
    assert p["n_points"] > 0
    assert p["points_per_m"] == round(p["n_points"] / p["length_m"], 3)
    coords = np.array(curbs[0]["geometry"]["coordinates"])
    assert (coords[:, 0] > -0.25).all() and (
        coords[:, 0] < 0.5
    ).all()  # on the step at x = 0
    assert np.ptp(coords[:, 1]) > 15  # along the 20 m edge
    assert np.allclose(
        coords[:, 2], 0.15, atol=0.02
    )  # measured height, not a flat guess
    assert json.loads((out / "qa.json").read_text())["n_curbs"] == 1


def test_small_step_is_ignored(tmp_path):
    _, out = _curb_run(tmp_path, _road_with_curb(np.random.default_rng(0), 0.03))

    assert json.loads((out / "curbs.geojson").read_text())["features"] == []


def test_curbs_off_writes_no_file(tmp_path):
    result, out = _curb_run(
        tmp_path, _road_with_curb(np.random.default_rng(0), 0.15), enabled=False
    )

    assert result.status == "ok"
    assert "curbs.geojson" not in result.files
    assert not (out / "curbs.geojson").exists()
    assert (out / "qa.json").is_file()


def test_curb_found_through_the_ground_split(tmp_path):
    """Step 2.5 m in: the 5 m RANSAC tile straddles it, so the sidewalk lands in nonground.laz."""
    cloud = _road_with_curb(np.random.default_rng(0), 0.15, edge=2.5)
    is_ground = ransac_ground(cloud[:, :3], GroundParams())
    assert (
        ~is_ground & (cloud[:, 0] >= 2.5)
    ).any()  # some sidewalk really is non-ground
    _, out = _curb_run(tmp_path, cloud[is_ground], nonground=cloud[~is_ground])

    curbs = json.loads((out / "curbs.geojson").read_text())["features"]
    assert len(curbs) == 1
    coords = np.array(curbs[0]["geometry"]["coordinates"])
    assert (coords[:, 0] > 2.4).all() and (coords[:, 0] < 2.9).all()
    assert np.allclose(coords[:, 2], 0.15, atol=0.02)


def test_taller_nonground_is_not_curb_input(tmp_path):
    """A 1 m tall wall on the sidewalk stays out of curb input: no curb line from it."""
    rng = np.random.default_rng(0)
    road = _road_with_curb(rng, 0.0)
    road[:, 2] = np.where(road[:, 0] >= 2.5, 0.0, 0.0) + rng.normal(0, 0.005, len(road))
    wall_x = np.full(400, 2.5)
    wall = np.column_stack(
        [
            wall_x,
            np.linspace(0, 20, 400),
            np.linspace(0.0, 1.0, 400),
            np.full(400, 10.0),
        ]
    )
    _, out = _curb_run(tmp_path, road, nonground=wall)

    assert json.loads((out / "curbs.geojson").read_text())["features"] == []


def test_every_feature_carries_pose(tmp_path):
    markings, crosswalks, _ = _run(
        tmp_path, _lane_and_crosswalk(np.random.default_rng(0))
    )
    curbs = json.loads(
        (
            _curb_run(tmp_path / "c", _road_with_curb(np.random.default_rng(0), 0.15))[
                1
            ]
            / "curbs.geojson"
        ).read_text()
    )["features"]

    assert markings and crosswalks and curbs
    for f in (*markings, *crosswalks, *curbs):
        assert f["properties"]["pose"] == {
            "method": "kiss-icp",
            "fallback_used": False,
            "xy_drift_p95_m": 0.12,
        }


def test_extractable_on_paint_and_not_on_flat_intensity(tmp_path):
    _, _, out = _run(tmp_path, _lane_and_crosswalk(np.random.default_rng(0)))
    assert json.loads((out / "qa.json").read_text())["markings_extractable"] is True

    rng = np.random.default_rng(0)
    flat = _background(rng)
    flat[:, 3] = rng.uniform(10, 12, len(flat))  # contrast about 1.1, below 1.5
    _, _, out = _run(tmp_path / "flat", flat)
    qa = json.loads((out / "qa.json").read_text())
    assert qa["markings_extractable"] is False
    assert qa["paint_contrast"] < 1.5


# ------------------------------------------------------------------ lidarseg gate and marking types

from shapely.geometry import LineString, Polygon

from twin.stages.features import (
    lidarseg_gate,
    marking_type,
    type_markings,
)

DRV = 24


def _marking(y=5.0):
    return {
        "type": "Feature",
        "properties": {
            "id": "m",
            "kind": "marking",
            "evidence": ["lidar"],
            "reliability": "observed",
        },
        "geometry": {"type": "LineString", "coordinates": [[0, y, 0], [10, y, 0]]},
    }


def _load_dir(tmp_path, labels, y=5.0):
    """load folder with 100 points along y, labels per point (255 = unlabelled)."""
    d = tmp_path / "1_load"
    d.mkdir(exist_ok=True)
    n = len(labels)
    np.savez(
        d / "points.npz",
        x=np.linspace(0, 10, n),
        y=np.full(n, y),
        lidarseg=np.asarray(labels, np.uint8),
    )
    (d / "lidarseg.json").write_text(
        json.dumps({"driveable_index": DRV, "sentinel": 255, "n_labelled": 0})
    )
    return d


def test_gate_keeps_a_marking_on_driveable_surface(tmp_path):
    d = _load_dir(tmp_path, [DRV] * 90 + [17] * 10)  # 90 % flat
    kept, c = lidarseg_gate([_marking()], d, FeaturesParams())
    assert len(kept) == 1 and c["n_dropped_lidarseg"] == 0
    p = kept[0]["properties"]
    assert p["reliability"] == "observed" and p["lidarseg_flat_share"] == 0.9
    assert "lidarseg" in p["evidence"]


def test_gate_drops_a_marking_off_the_road(tmp_path):
    d = _load_dir(tmp_path, [DRV] * 50 + [17] * 50)  # 50 % flat < 0.8
    kept, c = lidarseg_gate([_marking()], d, FeaturesParams())
    assert kept == [] and c["n_dropped_lidarseg"] == 1


def test_gate_ignores_unlabelled_points_and_notes_too_few(tmp_path):
    # all sentinel: nothing to judge by, keep with the note (never fabricate a verdict)
    d = _load_dir(tmp_path, [255] * 100)
    kept, c = lidarseg_gate([_marking()], d, FeaturesParams())
    assert len(kept) == 1 and c["n_lidarseg_insufficient_labels"] == 1
    assert kept[0]["properties"]["reliability"] == "observed"
    assert "lidarseg: insufficient labels" in kept[0]["properties"]["evidence"]
    # 5 labelled points only: below the minimum of 10
    d = _load_dir(tmp_path, [DRV] * 5 + [255] * 95)
    kept, c = lidarseg_gate([_marking()], d, FeaturesParams())
    assert len(kept) == 1 and c["n_lidarseg_insufficient_labels"] == 1


def test_gate_share_is_a_parameter(tmp_path):
    d = _load_dir(tmp_path, [DRV] * 60 + [17] * 40)
    assert lidarseg_gate([_marking()], d, FeaturesParams())[0] == []
    kept, _ = lidarseg_gate([_marking()], d, FeaturesParams(lidarseg_flat_share=0.5))
    assert len(kept) == 1


def test_gate_without_load_folder_keeps_with_note():
    kept, c = lidarseg_gate([_marking()], None, FeaturesParams())
    assert len(kept) == 1 and c["n_lidarseg_insufficient_labels"] == 1


REF = {
    "divider": [LineString([(0, 0), (100, 0)])],
    "stop_line": [Polygon([(50, -2), (50.4, -2), (50.4, 2), (50, 2)])],
    "ped_crossing": [Polygon([(20, -3), (24, -3), (24, 3), (20, 3)])],
}


def test_marking_types():
    along_divider = LineString([(5, 0.3), (15, 0.3)])
    assert marking_type(along_divider, REF) == "divider"
    assert marking_type(LineString([(50.2, -1.5), (50.2, 1.5)]), REF) == "stop_line"
    assert marking_type(LineString([(21, -2), (21, 2)]), REF) == "crosswalk_stripe"
    # near the divider but crossing it: not a divider
    assert marking_type(LineString([(60, -2), (60, 2)]), REF) == "other_paint"
    # parallel but 5 m from any divider
    assert marking_type(LineString([(5, 5), (15, 5)]), REF) == "other_paint"
    # near the stop line but along the lane
    assert marking_type(LineString([(48, 1.5), (52, 1.5)]), REF) != "stop_line"


def test_type_markings_sets_property_and_counts():
    ref = [
        {
            "properties": {"layer": "lane_divider"},
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [100, 0]]},
        },
        {
            "properties": {"layer": "drivable_area"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, -9], [9, -9], [9, 9], [0, -9]]],
            },
        },
    ]
    ms = [_marking(0.2), _marking(8.0)]
    counts = type_markings(ms, ref)
    assert [m["properties"]["marking_type"] for m in ms] == ["divider", "other_paint"]
    assert counts == {
        "divider": 1,
        "stop_line": 0,
        "crosswalk_stripe": 0,
        "other_paint": 1,
    }


def test_short_fragment_off_angle_keeps_divider_type():
    c, sn = math.cos(math.radians(40)), math.sin(math.radians(40))
    # 2 m long, 40 degrees off the divider, 0.3 m from it: too short for an angle test
    frag = LineString([(5, 0.3), (5 + 2 * c, 0.3 + 2 * sn)])
    assert marking_type(frag, REF) == "divider"
    # the same angle on a 5 m marking is still not a divider
    long = LineString([(5, 0.3), (5 + 5 * c, 0.3 + 5 * sn)])
    assert marking_type(long, REF) == "other_paint"


def _label_road(ctx, driveable):
    """lidarseg labels on a 0.1 m grid over x -10..10, y 0..20: 24 (driveable) where driveable(x, y), else 26."""
    x, y = np.meshgrid(
        np.arange(-10.0, 10.0, 0.1), np.arange(0.0, 20.0, 0.1), indexing="ij"
    )
    x, y = x.ravel(), y.ravel()
    load = ctx.stage_dir("load")
    load.mkdir()
    (load / "lidarseg.json").write_text(
        json.dumps({"driveable_index": 24, "sentinel": 255})
    )
    np.savez(
        load / "points.npz",
        x=x,
        y=y,
        z=np.zeros_like(x),
        lidarseg=np.where(driveable(x, y), 24, 26).astype(np.uint8),
    )


def _labelled_curb_run(tmp_path, ground, driveable):
    ctx = _ctx(tmp_path, ground)
    _label_road(ctx, driveable)
    result = registry.lookup("features", "intensity")(ctx, FeaturesParams())
    return result.metrics, json.loads(
        (ctx.stage_dir("features") / "curbs.geojson").read_text()
    )["features"]


def test_curb_with_road_on_its_low_side_and_parallel_edge_is_kept(tmp_path):
    qa, curbs = _labelled_curb_run(
        tmp_path, _road_with_curb(np.random.default_rng(0), 0.15), lambda x, y: x < 0
    )

    assert len(curbs) == 1
    p = curbs[0]["properties"]
    assert 0.1 < p["step_m"] < 0.2
    assert p["road_share"] > 0.9
    assert p["edge_angle_deg"] < 5
    assert "lidarseg" in p["evidence"]
    assert qa["n_curb_candidates"] == 1
    assert (
        qa["n_curb_rejected_step"],
        qa["n_curb_rejected_road"],
        qa["n_curb_rejected_parallel"],
    ) == (0, 0, 0)


def test_step_with_no_road_beside_it_is_rejected(tmp_path):
    """A building or sidewalk edge: the same step, but the low side is not driveable surface."""
    qa, curbs = _labelled_curb_run(
        tmp_path, _road_with_curb(np.random.default_rng(0), 0.15), lambda x, y: x < -5
    )

    assert curbs == []
    assert qa["n_curb_candidates"] == 1
    assert qa["n_curb_rejected_road"] == 1
    assert qa["n_curb_rejected_step"] == 0
    assert qa["n_curbs"] == 0


def test_curb_not_parallel_to_the_road_edge_is_rejected(tmp_path):
    """Road surface is on the low side, but the road's edge runs at 45 degrees to the step."""
    qa, curbs = _labelled_curb_run(
        tmp_path, _road_with_curb(np.random.default_rng(0), 0.15), lambda x, y: x < y
    )

    assert curbs == []
    assert qa["n_curb_rejected_parallel"] == 1
    assert qa["n_curb_rejected_road"] == 0


def test_steep_ramp_is_not_a_curb(tmp_path):
    """z rises 0.5 m per metre: every cell has a 0.125 m neighbour step, but across the line it is 0.5 m."""
    x, y = np.meshgrid(
        np.arange(0.0, 6.0, 0.05), np.arange(0.0, 20.0, 0.05), indexing="ij"
    )
    x, y = x.ravel(), y.ravel()
    ramp = np.column_stack([x, y, 0.5 * x, np.full(x.size, 10.0)])
    _, out = _curb_run(tmp_path, ramp)

    qa = json.loads((out / "qa.json").read_text())
    assert qa["n_curb_candidates"] > 0
    assert qa["n_curb_rejected_step"] == qa["n_curb_candidates"]
    assert qa["n_curbs"] == 0
