import json

import numpy as np
import shapely

from tests.test_features import _ctx
from twin import registry
from twin.contracts import FeaturesParams
from twin.stages import features_raster as fr

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


def test_raster_method_runs_in_the_stage(tmp_path):
    xs, ys = _grid(0, 12, -2, 2)
    ctx = _ctx(tmp_path, _ground(xs, ys, lambda x, y: np.abs(y) < 0.075))
    result = registry.lookup("features", "raster")(ctx, FeaturesParams())
    assert result.status == "ok"
    out = ctx.stage_dir("features")
    assert json.loads((out / "qa.json").read_text())["method"] == "raster"
    assert json.loads((out / "markings.geojson").read_text())["features"]


def test_paint_mask_returns_two_tuple():
    import numpy as np
    xs, ys = _grid(0, 4, -1, 1)
    pts = _ground(xs, ys, lambda x, y: np.abs(y) < 0.075)
    grid = fr.Grid(pts[:, :2])
    intensity = grid.mean(pts[:, 3], sigma=fr.SPLAT_CELLS)
    road = np.ones(intensity.shape, bool)
    mask, weight = fr.paint_mask(intensity, road=road)
    assert isinstance(mask, np.ndarray)
    assert mask.dtype == bool
    assert isinstance(weight, np.ndarray)
    assert weight.dtype.kind == "f"


def test_extract_count_keys_present_and_types():
    xs, ys = _grid(0, 12, -2, 2)
    pts = _ground(xs, ys, lambda x, y: np.abs(y) < 0.075)
    _markings, _crosswalks, counts = fr.extract(pts)
    expected_int = [
        "n_road_cells", "n_paint_cells_raw", "n_paint_cells", "n_components_raw",
        "n_components_dropped_small", "n_components", "n_lines", "n_bars", "n_combs",
        "n_unclassified", "n_bar_groups", "n_crosswalks", "n_used_lines",
        "n_used_bars", "n_singles", "n_chains", "n_chain_singletons",
        "n_dropped_short_final", "n_markings_extracted", "n_markings", "n_bins_skipped",
    ]
    for k in expected_int:
        assert k in counts, k
        assert isinstance(counts[k], int), (k, type(counts[k]))
    assert "paint_threshold" in counts
    assert isinstance(counts["paint_threshold"], float)


def test_markings_source_intensity(tmp_path):
    xs, ys = _grid(0, 12, -2, 2)
    ctx = _ctx(tmp_path, _ground(xs, ys, lambda x, y: np.abs(y) < 0.075))
    from twin.contracts import FeaturesParams

    result = __import__("twin", fromlist=["registry"]).registry.lookup("features", "raster")(ctx, FeaturesParams())
    assert result.status == "ok"
    qa = json.loads((ctx.stage_dir("features") / "qa.json").read_text())
    assert qa["markings_source"] == "intensity"
    assert "n_markings_intensity" in qa
    assert isinstance(qa["n_markings_intensity"], int)
