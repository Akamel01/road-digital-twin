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

def _synthetic_ramp_cloud(with_gap=True, gap_x=4.0, width=1.5, run_m=1.5, h=0.125):
    # Synthetic: road at z=0 (y < curb_y), sidewalk at z=h (y >= curb_y). Ramp at 1:12 (1.5m run, 0.125m rise)
    # with flares; small flat landing at curb line keeps local height step low for candidate detection.
    xs = np.arange(0, 12, 0.1)
    ys = np.arange(-3, 4, 0.1)
    gx, gy = np.meshgrid(xs, ys)
    x, y = gx.ravel(), gy.ravel()
    curb_y = 0.4
    z = np.where(y >= curb_y, h, 0.0)
    if with_gap:
        # ramp body: slopes up over sidewalk from curb_y+flat to curb_y+run_m
        flat = 0.2
        t = np.clip((y - (curb_y + flat)) / max(run_m - flat, 1e-6), 0.0, 1.0)
        ramp_z = t * h
        ramp_zone = (x >= gap_x) & (x <= gap_x + width) & (y >= curb_y) & (y <= curb_y + run_m)
        z = np.where(ramp_zone, np.where(y <= curb_y + flat, 0.0, ramp_z), z)
        # small flat lip at edges to keep local step low for detection at boundaries
        lip = (x >= gap_x - 0.05) & (x <= gap_x + width + 0.05) & (y >= curb_y - 0.05) & (y <= curb_y + flat)
        z = np.where(lip & (y >= curb_y), 0.0, z)
        # flares
        for side, sign in ((gap_x, -1), (gap_x + width, 1)):
            fx_in = (x >= side - 0.6) & (x < side) if sign < 0 else (x > side) & (x <= side + 0.6)
            m = fx_in & (y >= curb_y) & (y <= curb_y + run_m)
            xt = np.clip(np.abs(x[m] - side) / 0.6, 0.0, 1.0)
            yt = np.clip((y[m] - (curb_y + flat)) / max(run_m - flat, 1e-6), 0.0, 1.0)
            edge = np.where(y[m] <= curb_y + flat, 0.0, yt * h)
            z[m] = edge + xt * (h - edge)
    return np.column_stack([x, y, z])


def _ramp_inputs(with_gap=True, with_crosswalk=True, gap_x=4.0, width=1.5):
    pts = _synthetic_ramp_cloud(with_gap=with_gap, gap_x=gap_x, width=width)
    curb_y = 0.4
    h = 0.125
    # continuous curb line; low-step (z=0) along ramp width gives detected candidate width ~width
    if with_gap:
        # uniform curb samples; low step (z=0) over [gap_x, gap_x+width] gives candidate width = width
        xs_c = np.arange(0.0, 12.0001, 0.25)
        dense = []
        for xx in xs_c:
            zz = 0.0 if (gap_x - 1e-9 <= xx <= gap_x + width + 1e-9) else float(h)
            dense.append([float(xx), curb_y, zz])
        curbs = [{"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"},
                  "geometry": {"type": "LineString", "coordinates": dense}}]
    else:
        curbs = [{"type": "Feature", "properties": {"id": "curb-0001", "kind": "curb"},
                  "geometry": {"type": "LineString", "coordinates": [[0.0, curb_y, h], [12.0, curb_y, h]]}}]
    cw = []
    if with_crosswalk:
        cx = gap_x + width / 2
        poly = shapely.Polygon([(cx - 1.0, -2.8), (cx + 1.0, -2.8), (cx + 1.0, 0.2), (cx - 1.0, 0.2)])
        cw = [{"type": "Feature", "properties": {"id": "X-1", "kind": "crosswalk"}, "geometry": shapely.geometry.mapping(poly)}]
    return pts, curbs, cw


def test_ramp_at_crosswalk_width_and_slope():
    pts, curbs, cw = _ramp_inputs()
    # synthetic 1.5m ramp at 1:12 with flares: boundary curb samples sit on 12.5cm edge so step~0.114cm
    # in 35cm window; relax candidate threshold to include full 1.5m gap span.
    ramps = fr.extract_ramps(pts, curbs, cw, params=type("P", (), {
        "gap_min_m": 1.0, "gap_max_m": 3.0, "height_step_max_m": 0.12,
        "crosswalk_end_m": 3.0, "measure_cell_m": 0.25, "min_measure_cells": 4,
    })())
    assert ramps, "expected a detected ramp"
    curb_ramps = [r for r in ramps if r["properties"]["kind"] == "curb_ramp"]
    assert curb_ramps, f"expected curb_ramp, got {[r['properties']['kind'] for r in ramps]}"
    r = curb_ramps[0]
    p = r["properties"]
    assert abs(p["width_m"] - 1.5) <= 0.1
    assert p["running_slope_pct"] is not None
    assert abs(p["running_slope_pct"] - 8.33) <= 1.0


def test_curb_without_gap_gives_no_ramp():
    pts, curbs, cw = _ramp_inputs(with_gap=False, with_crosswalk=False)
    ramps = fr.extract_ramps(pts, curbs, cw)
    assert ramps == []


def test_gap_away_from_crosswalk_is_driveway_or_ramp():
    pts, curbs, cw = _ramp_inputs(with_crosswalk=False)
    ramps = fr.extract_ramps(pts, curbs, cw)
    assert ramps, "expected a detected ramp"
    kinds = {r["properties"]["kind"] for r in ramps}
    assert "driveway_or_ramp" in kinds
    assert "curb_ramp" not in kinds


def test_ramp_indeterminate_when_too_few_cells_per_side():
    pts, curbs, cw = _ramp_inputs()
    ramps = fr.extract_ramps(pts, curbs, cw, params=type("P", (), {
        "gap_min_m": 1.0, "gap_max_m": 3.0, "height_step_max_m": 0.02,
        "crosswalk_end_m": 3.0, "measure_cell_m": 0.25, "min_measure_cells": 100,
    })())
    assert ramps
    assert all(r["properties"]["status"] == "indeterminate" for r in ramps)
    assert all(r["properties"]["running_slope_pct"] is None for r in ramps)
