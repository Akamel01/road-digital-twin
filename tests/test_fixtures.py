import numpy as np

from twin import fixtures as fx


def _road_fit(plane):
    road = plane[plane[:, 1] < fx.CURB_Y]
    a = np.column_stack([road[:, 0], road[:, 1], np.ones(len(road))])
    coef, *_ = np.linalg.lstsq(a, road[:, 2], rcond=None)
    return coef


def test_slope_recovered_by_least_squares(plane_points):
    coef = _road_fit(plane_points)
    assert abs(coef[0] - fx.SLOPE) < 1e-3  # along x
    assert abs(coef[1]) < 1e-3  # no cross slope


def test_stripes_sit_in_known_rectangles(plane_points):
    x, y, inten = plane_points[:, 0], plane_points[:, 1], plane_points[:, 3]
    high = inten > 0.6
    spacing = 0.25
    in_any = np.zeros(len(x), bool)
    for x0, x1, y0, y1 in fx.STRIPES:
        rect = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
        in_any |= rect
        assert high[rect].mean() > 0.99
        # bounding box of the bright points matches the rectangle to one grid step
        hx, hy = x[rect & high], y[rect & high]
        assert abs(hx.min() - x0) <= spacing and abs(hx.max() - x1) <= spacing
        assert abs(hy.min() - y0) <= spacing and abs(hy.max() - y1) <= spacing
    assert not np.any(high & ~in_any)  # no bright ground outside the stripes


def test_curb_step_height(plane_points):
    coef = _road_fit(plane_points)
    side = plane_points[plane_points[:, 1] >= fx.CURB_Y]
    predicted = coef[0] * side[:, 0] + coef[1] * side[:, 1] + coef[2]
    assert abs(np.mean(side[:, 2] - predicted) - fx.CURB_HEIGHT_M) < 0.01


def test_canopy_height_above_road(plane_points, canopy_points):
    coef = _road_fit(plane_points)
    predicted = coef[0] * canopy_points[:, 0] + coef[1] * canopy_points[:, 1] + coef[2]
    assert abs(np.mean(canopy_points[:, 2] - predicted) - fx.CANOPY_HEIGHT_M) < 0.01


def test_canopy_is_over_part_of_the_road(canopy_points):
    x0, x1 = fx.CANOPY_RECT[:2]
    assert canopy_points[:, 0].min() >= x0 and canopy_points[:, 0].max() <= x1
    assert canopy_points[:, 1].max() < fx.CURB_Y


def test_wall_is_vertical_at_known_x(wall_points):
    assert np.all(wall_points[:, 0] == fx.WALL_X)
    height = wall_points[:, 2] - fx.ground_z(wall_points[:, 0], wall_points[:, 1])
    assert abs(height.max() - fx.WALL_HEIGHT_M) < 0.01


def test_same_seed_same_points():
    assert np.array_equal(fx.make_scene(seed=3), fx.make_scene(seed=3))
    assert not np.array_equal(fx.make_plane(seed=3), fx.make_plane(seed=4))
