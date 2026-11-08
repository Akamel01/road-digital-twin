"""Synthetic lidar fixtures with known geometry.

Coordinates are local metres: x runs along the road, y across it, z is up.
The constants below are the geometry the generators build, so tests assert
against them directly.
"""

import numpy as np

SLOPE = 0.02  # ground rises 2 cm per metre along +x
SITE_X = (0.0, 40.0)
SITE_Y = (0.0, 20.0)
CURB_Y = 16.0  # curb line, runs along x at this y
CURB_HEIGHT_M = 0.15  # sidewalk (y >= CURB_Y) sits this much above the road
STRIPES = ((8.0, 9.0, 2.0, 14.0), (28.0, 29.5, 2.0, 14.0))  # (x0, x1, y0, y1)
CANOPY_RECT = (15.0, 30.0, 0.0, 12.0)  # (x0, x1, y0, y1), over part of the road
CANOPY_HEIGHT_M = 5.0  # canopy points sit this far above the ground
WALL_X = 38.0  # wall runs along y from 0 to CURB_Y at this x
WALL_HEIGHT_M = 2.5
INTENSITY_ROAD = 0.2
INTENSITY_PAINT = 0.9
INTENSITY_CANOPY = 0.3
INTENSITY_WALL = 0.4
NOISE_Z_M = 0.003


def ground_z(x, y):
    """Ground height at (x, y): the slope plus the curb step."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    return SLOPE * x + np.where(y >= CURB_Y, CURB_HEIGHT_M, 0.0)


def _axis(a, b, spacing):
    return np.arange(a, b + spacing / 2, spacing)


def _grid(x0, x1, y0, y1, spacing):
    gx, gy = np.meshgrid(_axis(x0, x1, spacing), _axis(y0, y1, spacing), indexing="ij")
    return gx.ravel(), gy.ravel()


def make_plane(seed: int = 0, spacing_m: float = 0.25) -> np.ndarray:
    """Sloped road and sidewalk with painted stripes. Columns: x, y, z, intensity."""
    rng = np.random.default_rng(seed)
    x, y = _grid(*SITE_X, *SITE_Y, spacing_m)
    z = ground_z(x, y) + rng.normal(0, NOISE_Z_M, x.size)
    intensity = INTENSITY_ROAD + rng.normal(0, 0.02, x.size)
    for x0, x1, y0, y1 in STRIPES:
        inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
        intensity[inside] = INTENSITY_PAINT + rng.normal(0, 0.02, inside.sum())
    return np.column_stack([x, y, z, intensity])


def make_canopy(seed: int = 1, spacing_m: float = 0.25) -> np.ndarray:
    """Points CANOPY_HEIGHT_M above the ground over CANOPY_RECT."""
    rng = np.random.default_rng(seed)
    x, y = _grid(*CANOPY_RECT, spacing_m)
    z = ground_z(x, y) + CANOPY_HEIGHT_M + rng.normal(0, NOISE_Z_M, x.size)
    intensity = INTENSITY_CANOPY + rng.normal(0, 0.02, x.size)
    return np.column_stack([x, y, z, intensity])


def make_wall(seed: int = 2, spacing_m: float = 0.25) -> np.ndarray:
    """Vertical wall at x = WALL_X, along the road side of the curb."""
    rng = np.random.default_rng(seed)
    ys, hs = np.meshgrid(
        _axis(0.0, CURB_Y, spacing_m),
        _axis(0.0, WALL_HEIGHT_M, spacing_m),
        indexing="ij",
    )
    y = ys.ravel()
    x = np.full(y.size, WALL_X)
    z = ground_z(x, y) + hs.ravel() + rng.normal(0, NOISE_Z_M, y.size)
    intensity = INTENSITY_WALL + rng.normal(0, 0.02, y.size)
    return np.column_stack([x, y, z, intensity])


def make_scene(seed: int = 0, spacing_m: float = 0.25) -> np.ndarray:
    """Plane, canopy and wall stacked. Columns: x, y, z, intensity."""
    return np.vstack(
        [
            make_plane(seed, spacing_m),
            make_canopy(seed + 1, spacing_m),
            make_wall(seed + 2, spacing_m),
        ]
    )
