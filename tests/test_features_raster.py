import json
import logging

import laspy
import numpy as np
import pytest
import shapely

from twin.contracts import FeaturesParams
from twin.runner import StageContext
from twin.stages import features_raster as fr
from twin.stages.ground import surface_grid


def _write_nonground_and_surface(ground_dir, ground_xyzi, nonground_xyzi):
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
    zmean, count = surface_grid(ground_xyzi[:, :2], ground_xyzi[:, 2], origin, 0.5, shape)
    np.savez_compressed(ground_dir / "surface.npz", z=zmean, count=count, origin=origin, cell_m=np.float64(0.5))


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
    (run / "4_ground" / "qa.json").write_text(json.dumps({"height_valid": True, "not_scanned_enough": []}))
    (run / "3_align").mkdir()
    (run / "3_align" / "qa.json").write_text(json.dumps({"method": "kiss-icp", "fallback_used": False, "fallback_reason": None, "xy_drift_p95_m": 0.12}))
    return StageContext(run_dir=run, scene_token="s", seed=0, log=logging.getLogger("t"))


ROAD, PAINT = 10.0, 80.0


def _ground(xs, ys, paint, z=None, rng=None):
    """Ground points on a 2.5 cm grid (about 16 per 5 cm cell's area), intensity PAINT where paint(x, y)."""
    gx, gy = np.meshgrid(xs, ys)
    x, y = gx.ravel(), gy.ravel()
    rng = rng or np.random.default_rng(0)
    x, y = x + rng.uniform(-0.01, 0.01, x.size), y + rng.uniform(-0.01, 0.01, y.size)
    zz = np.zeros_like(x) if z is None else z(x, y)
    return np.column_stack([x, y, zz, np.where(paint(x, y), PAINT, ROAD)])


def _grid(x0, x1, y0, y1, step=0.025):
    return np.arange(x0, x1, step), np.arange(y0, y1, step)


def test_solid_line_centre_within_3cm():
    xs, ys = _grid(0, 12, -2, 2)
    pts = _ground(xs, ys, lambda x, y: np.abs(y - 0.37) < 0.075)  # 15 cm line centred on y = 0.37
    markings, crosswalks, _ = fr.extract(pts)
    assert len(markings) == 1 and not crosswalks
    coords = np.array(markings[0]["geometry"]["coordinates"])
    assert np.abs(coords[:, 1] - 0.37).max() < 0.03
    assert markings[0]["properties"]["length_m"] > 11


def test_dashes_chain_into_one_line():
    xs, ys = _grid(0, 30, -2, 2)
    pts = _ground(xs, ys, lambda x, y: (np.abs(y) < 0.075) & ((x % 12) < 3))  # 3 m dashes, 9 m gaps
    markings, _, _ = fr.extract(pts)
    assert len(markings) == 1
    assert markings[0]["properties"]["dashes"] == 3
    assert np.abs(np.array(markings[0]["geometry"]["coordinates"])[:, 1]).max() < 0.03


def test_ladder_crosswalk_is_one_polygon():
    # Rails along x at y = 0 and y = 3 (20 cm), bars 40 cm wide every 1 m between them, 8 m across.
    xs, ys = _grid(-2, 10, -2, 5)
    rails = lambda x, y: ((np.abs(y) < 0.1) | (np.abs(y - 3) < 0.1)) & (x >= 0) & (x <= 8)
    bars = lambda x, y: ((x % 1.0) < 0.4) & (y >= 0) & (y <= 3) & (x >= 0) & (x <= 8)
    pts = _ground(xs, ys, lambda x, y: rails(x, y) | bars(x, y))
    markings, crosswalks, _ = fr.extract(pts)
    assert len(crosswalks) == 1
    poly = shapely.Polygon([c[:2] for c in crosswalks[0]["geometry"]["coordinates"][0]])
    truth = shapely.box(0, -0.1, 8.4, 3.1)
    assert poly.intersection(truth).area / poly.union(truth).area > 0.9
    assert not markings  # rails and bars are inside the crosswalk, not separate lines


def test_curb_on_height_step_within_5cm():
    xs, ys = _grid(0, 10, -3, 3)
    pts = _ground(xs, ys, lambda x, y: np.zeros_like(x, bool), z=lambda x, y: np.where(y > 0.4, 0.15, 0.0))
    curbs = fr.extract_curbs(pts[:, :3])
    assert curbs
    longest = max(curbs, key=lambda f: f["properties"]["length_m"])
    c = np.array(longest["geometry"]["coordinates"])
    assert longest["properties"]["length_m"] > 7
    assert np.median(np.abs(c[:, 1] - 0.4)) < 0.05


def _features_registry_or_skip():
    try:
        import open3d  # noqa: F401
    except ImportError:  # pragma: no cover - env dependent
        pytest.skip("open3d unavailable")
    import twin.stages.features  # noqa: F401
    from twin import registry

    return registry


def test_raster_method_runs_in_the_stage(tmp_path):
    registry = _features_registry_or_skip()
    xs, ys = _grid(0, 12, -2, 2)
    ctx = _ctx(tmp_path, _ground(xs, ys, lambda x, y: np.abs(y) < 0.075))
    result = registry.lookup("features", "raster")(ctx, FeaturesParams())
    assert result.status == "ok"
    out = ctx.stage_dir("features")
    assert json.loads((out / "qa.json").read_text())["method"] == "raster"
    assert json.loads((out / "markings.geojson").read_text())["features"]


def test_raster_method_keeps_intensity_markings(tmp_path):
    registry = _features_registry_or_skip()
    xs, ys = _grid(0, 12, -2, 2)
    pts = _ground(xs, ys, lambda x, y: np.abs(y) < 0.075)
    out = {}
    for method in ("intensity", "raster"):
        ctx = _ctx(tmp_path / method, pts)
        assert registry.lookup("features", method)(ctx, FeaturesParams()).status == "ok"
        out[method] = json.loads((ctx.stage_dir("features") / "markings.geojson").read_text())["features"]
    assert out["raster"] and out["raster"] == out["intensity"]


# ---- ramps (M3)
# ---- ramps (M3)

def _synthetic_ramp_cloud(with_gap=True, gap_x=4.0, width=1.5, run_m=1.5, h=None, cross_slope=0.0):
    # road z=0, sidewalk z=h, ramp rises over run_m along +y from curb_y
    if h is None:
        h = run_m / 12.0
    xs = np.arange(-1.0, 14.0, 0.05)
    ys = np.arange(-4.0, 4.0, 0.05)
    gx, gy = np.meshgrid(xs, ys)
    x, y = gx.ravel(), gy.ravel()
    curb_y = 0.4
    z = np.where(y >= curb_y, h, 0.0)
    if cross_slope:
        z = z + np.where(y >= curb_y, (x - gap_x - width / 2.0) * cross_slope, 0.0)
    if with_gap:
        ramp_zone = (x >= gap_x) & (x <= gap_x + width) & (y >= curb_y)
        t = np.clip((y - curb_y) / run_m, 0.0, 1.0)
        ramp_z = t * h
        if cross_slope:
            ramp_z = ramp_z + (x - gap_x - width / 2.0) * cross_slope
        z = np.where(ramp_zone, ramp_z, z)
        for side, sign in ((gap_x, -1), (gap_x + width, 1)):
            fx = (x >= side - 0.6) & (x < side) if sign < 0 else (x > side) & (x <= side + 0.6)
            m = fx & (y >= curb_y)
            xt = np.clip(np.abs(x[m] - side) / 0.6, 0.0, 1.0)
            yt = np.clip((y[m] - curb_y) / run_m, 0.0, 1.0)
            ramp_edge = yt * h
            if cross_slope:
                ramp_edge = ramp_edge + (x[m] - gap_x - width / 2.0) * cross_slope
            z[m] = xt * h + (1.0 - xt) * ramp_edge
    return np.column_stack([x, y, z])


def _ramp_inputs(with_gap=True, with_crosswalk=True, gap_x=4.0, width=1.5, run_m=1.5, h=None, cross_slope=0.0, split_curb=False):
    pts = _synthetic_ramp_cloud(with_gap=with_gap, gap_x=gap_x, width=width, run_m=run_m, h=h, cross_slope=cross_slope)
    curb_y = 0.4
    if h is None:
        h = run_m / 12.0
    if with_gap and split_curb:
        left = [[0.0, curb_y, h], [gap_x, curb_y, h]]
        right = [[gap_x + width, curb_y, h], [12.0, curb_y, h]]
        curbs = [
            {"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"}, "geometry": {"type": "LineString", "coordinates": left}},
            {"type": "Feature", "properties": {"id": "curb-0002", "kind": "curb"}, "geometry": {"type": "LineString", "coordinates": right}},
        ]
    elif with_gap:
        xs_c = np.arange(0.0, 12.0001, 0.25)
        # ensure exact gap edges present for non-grid widths (e.g. 1.2m)
        xs_c = np.unique(np.concatenate([xs_c, [gap_x, gap_x + width]]))
        dense = []
        for xx in xs_c:
            # low-step (gap) samples span width along curb
            zz = 0.0 if (gap_x - 1e-9 <= xx <= gap_x + width + 1e-9) else float(h)
            dense.append([float(xx), curb_y, zz])
        curbs = [{"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"}, "geometry": {"type": "LineString", "coordinates": dense}}]
    else:
        curbs = [{"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"}, "geometry": {"type": "LineString", "coordinates": [[0.0, curb_y, h], [12.0, curb_y, h]]}}]
    cw = []
    if with_crosswalk:
        cx = gap_x + width / 2
        poly = shapely.Polygon([(cx - 1.0, -2.8), (cx + 1.0, -2.8), (cx + 1.0, 0.2), (cx - 1.0, 0.2)])
        cw = [{"type": "Feature", "properties": {"id": "X-1", "kind": "crosswalk"}, "geometry": shapely.geometry.mapping(poly)}]
    return pts, curbs, cw


def test_ramp_at_crosswalk_width_and_slope():
    pts, curbs, cw = _ramp_inputs()
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps, "expected a detected ramp"
    curb_ramps = [r for r in ramps if r["properties"]["kind"] == "curb_ramp"]
    assert curb_ramps, f"expected curb_ramp, got {[r['properties']['kind'] for r in ramps]}"
    p = curb_ramps[0]["properties"]
    assert abs(p["width_m"] - 1.5) <= 0.1
    assert p["run_length_m"] is not None
    assert p["running_slope_pct"] is not None
    assert abs(p["running_slope_pct"] - 8.33) <= 1.0


def test_exact_1_12_ramp_1_48_cross_slope():
    # exact 1:12 ramp 1.2m run with 1:48 cross slope, running slope within 0.5pp, side/cross within 0.5pp
    pts, curbs, cw = _ramp_inputs(width=1.5, run_m=1.2, cross_slope=1.0 / 48.0)
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps
    p = next(r for r in ramps if r["properties"]["kind"] == "curb_ramp")["properties"]
    assert abs(p["width_m"] - 1.5) <= 0.1
    assert p["run_length_m"] is not None
    assert abs(p["run_length_m"] - 1.2) <= 0.2
    assert p["running_slope_pct"] is not None
    assert abs(p["running_slope_pct"] - 8.33) <= 0.5
    assert p["cross_slope_pct"] is not None
    assert abs(p["cross_slope_pct"] - 2.08) <= 0.5


def test_1_10_ramp_running_exceeds():
    pts, curbs, cw = _ramp_inputs(run_m=1.2, h=0.12)  # 10%
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps
    p = ramps[0]["properties"]
    assert p["running_slope_pct"] is not None
    assert p["running_slope_pct"] > 8.33
    assert p["running_slope_status"] == "exceeds"


def test_13mm_gutter_lip_exceeds():
    pts, curbs, cw = _ramp_inputs()
    # add a 13mm lip at gutter line (y around curb_y) on ramp side
    m = (pts[:, 0] >= 4.0) & (pts[:, 0] <= 5.5) & (pts[:, 1] >= 0.38) & (pts[:, 1] <= 0.45)
    pts[m, 2] += 0.013
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps
    p = ramps[0]["properties"]
    assert p["gutter_step_m"] is not None
    assert p["gutter_step_m"] >= 0.010
    assert p["gutter_step_status"] == "exceeds"


def test_curb_without_gap_gives_no_ramp():
    pts, curbs, cw = _ramp_inputs(with_gap=False, with_crosswalk=False)
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps == []


def test_gap_away_from_crosswalk_is_driveway_or_ramp():
    pts, curbs, cw = _ramp_inputs(with_crosswalk=False)
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps, "expected a detected ramp"
    kinds = {r["properties"]["kind"] for r in ramps}
    assert "driveway_or_ramp" in kinds
    assert "curb_ramp" not in kinds


def test_two_polyline_gap_detected():
    pts, curbs, cw = _ramp_inputs(with_crosswalk=False, split_curb=True)
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    assert ramps, "expected ramp from two separate curb polylines with 1.5m gap"


def test_ramp_indeterminate_when_too_few_cells_per_side():
    pts, curbs, cw = _ramp_inputs()
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams(min_measure_cells=100))
    assert ramps
    assert all(r["properties"]["status"] == "indeterminate" for r in ramps)
    assert all(r["properties"]["running_slope_pct"] is None for r in ramps)


def test_extract_ramps_timing_2m_points():
    import time
    rng = np.random.default_rng(0)
    n = 2_000_000
    # dense-ish area around a simple ramp so candidate/path exercised on 2M cloud
    x = rng.uniform(-2, 14, n)
    y = rng.uniform(-4, 4, n)
    curb_y = 0.4
    h = 0.125
    z = np.where(y >= curb_y, h, 0.0)
    ramp_zone = (x >= 4.0) & (x <= 5.5) & (y >= curb_y)
    t = np.clip((y - curb_y) / 1.5, 0.0, 1.0)
    z = np.where(ramp_zone, t * h, z)
    pts = np.column_stack([x, y, z])
    curbs = [{"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"},
              "geometry": {"type": "LineString", "coordinates": [[0.0, curb_y, h], [4.0, curb_y, h], [5.5, curb_y, 0.0], [12.0, curb_y, h]]}}]
    cw = []
    t0 = time.perf_counter()
    ramps = fr.extract_ramps(pts, curbs, cw, fr.RampsParams())
    dt = time.perf_counter() - t0
    assert dt < 10.0, f"extract_ramps took {dt:.2f}s on 2M points"
    assert isinstance(ramps, list)
