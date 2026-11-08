import numpy as np
import pytest
import shapely

from twin.cli import main
from twin.contracts import SelectParams
from twin.select import go, paint_contrast, road_density, run_select


def grid_points(x0, x1, y0, y1, step, z=0.0):
    xs = np.arange(x0 + step / 2, x1, step)
    ys = np.arange(y0 + step / 2, y1, step)
    gx, gy = np.meshgrid(xs, ys)
    return np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, z)])


def test_density_of_known_grid_over_known_square():
    square = shapely.box(0, 0, 10, 10)  # 100 m2
    pts = grid_points(0, 10, 0, 10, 0.5)  # 400 points, all on the ground
    assert road_density(pts, [square]) == pytest.approx(4.0)


def test_density_drops_points_outside_polygon_and_above_ground():
    square = shapely.box(0, 0, 10, 10)
    pts = grid_points(0, 10, 0, 10, 0.5)
    outside = grid_points(20, 30, 0, 10, 0.5)  # 400 points, off the road
    raised = grid_points(0, 1, 0, 1, 0.5, z=1.0)  # 4 points 1 m above ground
    all_pts = np.vstack([pts, outside, raised])
    assert road_density(all_pts, [square]) == pytest.approx(4.0)


def test_density_zero_without_polygons():
    assert road_density(grid_points(0, 1, 0, 1, 0.5), []) == 0.0


def test_contrast_of_known_intensity_mix():
    # 90 asphalt points at 10, 10 paint points at 100.
    # median = 10; 95th percentile = 100; ratio = 10.
    values = np.concatenate([np.full(90, 10.0), np.full(10, 100.0)])
    assert paint_contrast(values) == pytest.approx(10.0)


def test_contrast_uniform_is_one():
    assert paint_contrast(np.full(50, 7.0)) == pytest.approx(1.0)


def test_contrast_empty_is_zero():
    assert paint_contrast(np.array([])) == 0.0


def test_go_thresholds_default():
    p = SelectParams()
    assert go(50.0, 1.5, p) is True
    assert go(49.9, 2.0, p) is False
    assert go(60.0, 1.49, p) is False


def test_go_min_density_override():
    p = SelectParams(min_density_pts_m2=100)
    assert go(60.0, 2.0, p) is False
    assert go(100.0, 2.0, p) is True


def test_cli_select_missing_data_exits_2(tmp_path, capsys):
    assert main(["select", "--dataroot", str(tmp_path)]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_select_rejects_out_of_range_threshold(tmp_path):
    assert run_select(tmp_path, min_density=0) == 2
