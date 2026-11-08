"""Stage 5 features: synthetic ground with stripes, no devkit, no data."""

import json
import logging

import numpy as np
from shapely.geometry import shape

from twin import registry
from twin.contracts import FeaturesParams
from twin.runner import StageContext


def _ground(rng):
    """Flat ground at 0.1 m spacing, background intensity 0-30, with one lane line and one crosswalk."""
    x, y = np.meshgrid(
        np.arange(0.0, 40.0, 0.1), np.arange(0.0, 20.0, 0.1), indexing="ij"
    )
    x, y = x.ravel(), y.ravel()
    inten = rng.uniform(0, 30, x.size)
    # Lane line: 0.5 m wide along x at y = 5, x 0..10, intensity 200.
    lane = (np.abs(y - 5.0) <= 0.25) & (x <= 10.0)
    inten[lane] = 200.0
    # Crosswalk: five 0.5 m wide stripes along y (4 m long) at x = 20, 21, ..., 24.
    for k in range(5):
        x0 = 20.0 + k
        stripe = (x >= x0) & (x <= x0 + 0.5) & (y >= 0.0) & (y <= 4.0)
        inten[stripe] = 200.0
    z = 0.01 * x
    return np.column_stack([x, y, z, inten])


def _ctx(tmp_path, ground_xyzi):
    run = tmp_path / "run"
    (run / "4_ground").mkdir(parents=True)
    import laspy

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


def test_lane_and_crosswalk_found_in_place(tmp_path):
    rng = np.random.default_rng(0)
    ctx = _ctx(tmp_path, _ground(rng))
    result = registry.lookup("features", "intensity")(ctx, FeaturesParams())
    assert result.status == "ok"

    out = ctx.stage_dir("features")
    markings = json.loads((out / "markings.geojson").read_text())["features"]
    crosswalks = json.loads((out / "crosswalks.geojson").read_text())["features"]

    assert len(markings) == 1
    line = shape(markings[0]["geometry"])
    (x0, y0, _), (x1, y1, _) = line.coords
    assert {round(x0), round(x1)} == {0, 10}
    assert abs(y0 - 5.0) < 0.2 and abs(y1 - 5.0) < 0.2
    assert markings[0]["properties"]["kind"] == "marking"

    assert len(crosswalks) == 1
    poly = shape(crosswalks[0]["geometry"])
    minx, miny, maxx, maxy = poly.bounds
    assert minx < 20.1 and maxx > 24.4
    assert miny < 0.1 and maxy > 3.9
    assert crosswalks[0]["properties"]["kind"] == "crosswalk"

    qa = json.loads((out / "qa.json").read_text())
    assert qa["height_valid"] is True
    assert qa["not_scanned_enough"] == ["S-0001"]


def test_min_points_removes_isolated_noise(tmp_path):
    rng = np.random.default_rng(1)
    ground = _ground(rng)
    ground[:, 3] = rng.uniform(0, 30, len(ground))  # no stripes at all
    ctx = _ctx(tmp_path, ground)
    registry.lookup("features", "intensity")(ctx, FeaturesParams())
    out = ctx.stage_dir("features")
    assert json.loads((out / "markings.geojson").read_text())["features"] == []
    assert json.loads((out / "crosswalks.geojson").read_text())["features"] == []
