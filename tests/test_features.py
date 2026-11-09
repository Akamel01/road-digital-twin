"""Stage 5 features: synthetic ground with stripes, no devkit, no data."""

import json
import logging

import laspy
import numpy as np
from shapely.geometry import shape

from twin import registry
from twin.contracts import FeaturesParams
from twin.runner import StageContext

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


def _ctx(tmp_path, ground_xyzi):
    run = tmp_path / "run"
    (run / "4_ground").mkdir(parents=True)
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001] * 3)
    header.offsets = ground_xyzi[:, :3].min(axis=0)
    las = laspy.LasData(header)
    las.xyz = ground_xyzi[:, :3]
    las.intensity = ground_xyzi[:, 3].astype(np.uint16)
    las.write(run / "4_ground" / "ground.laz")
    (run / "4_ground" / "qa.json").write_text(
        json.dumps({"height_valid": True, "not_scanned_enough": ["S-0001"]})
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
        assert p["evidence"] == ["lidar"]
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
