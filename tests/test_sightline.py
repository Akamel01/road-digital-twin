"""ISD sight line test: synthetic flat road, no data, no devkit."""

import numpy as np

from twin.contracts import IsdParams
from twin.sightline import BLOCKED, CLEAR, INDETERMINATE, Surface, sight_line

CELL = 0.5
ORIGIN = (-5.0, -5.0)
N = 50  # 25 m square, x and y from -5 to 20; eye at (0, 0), object at (15, 0)
EYE = (0.0, 0.0)
OBJ = (15.0, 0.0)


def _surface(count=50):
    """Flat ground at z = 0, every cell holding `count` ground points."""
    return Surface(
        z=np.zeros((N, N)),
        count=np.full((N, N), count, dtype=np.int64),
        origin=np.array(ORIGIN, dtype=float),
        cell_m=CELL,
    )


def _run(surface, nonground=None, parked=None, height_valid=True):
    return sight_line(
        EYE,
        OBJ,
        surface=surface,
        nonground_xyz=np.empty((0, 3)) if nonground is None else nonground,
        params=IsdParams(),
        height_valid=height_valid,
        parked_xyz=parked,
    )


def _points(x, z):
    """Points across the road at x, y in [-2, 2], z from z[0] to z[1]."""
    ys, zs = np.meshgrid(np.linspace(-2, 2, 41), np.linspace(*z, 20))
    xs = np.full(ys.size, x)
    return np.column_stack([xs, ys.ravel(), zs.ravel()])


def test_flat_road_is_clear():
    assert _run(_surface()).status == CLEAR


def test_canopy_above_line_does_not_block():
    canopy = _points(7.5, (3.0, 6.0))
    assert _run(_surface(), nonground=canopy).status == CLEAR


def test_wall_blocks():
    wall = _points(7.5, (0.1, 2.0))
    assert _run(_surface(), nonground=wall).status == BLOCKED


def test_kerb_under_line_does_not_block():
    kerb = _points(7.5, (0.1, 0.15))
    assert _run(_surface(), nonground=kerb).status == CLEAR


def test_fence_crossing_line_blocks():
    fence = _points(7.5, (0.1, 1.2))
    assert _run(_surface(), nonground=fence).status == BLOCKED


def test_wall_outside_band_does_not_block():
    # 0.3 m band: a wall 1 m to the side of the line is not on it.
    wall = np.column_stack([np.full(40, 7.5), np.full(40, 1.0), np.linspace(0.1, 2.0, 40)])
    assert _run(_surface(), nonground=wall).status == CLEAR


def test_coverage_gap_is_indeterminate():
    surface = _surface()
    centres = ORIGIN[0] + (np.arange(N) + 0.5) * CELL
    surface.count[:, (centres >= 6.0) & (centres < 8.0)] = 0
    assert _run(surface).status == INDETERMINATE


def test_height_invalid_is_indeterminate():
    assert _run(_surface(), height_valid=False).status == INDETERMINATE


def test_parked_box_blocks_only_with_parked():
    box = np.column_stack(
        [np.full(60, 7.5), np.linspace(-1, 1, 60), np.linspace(0.5, 1.5, 60)]
    )
    assert _run(_surface()).status == CLEAR
    assert _run(_surface(), parked=box).status == BLOCKED
