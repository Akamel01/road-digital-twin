"""Height-above-road raster: 25cm lattice (EPSG:32619), per-drive road level from 6m window, build-wide averaged deltas.

Pinned (plan B1-B3,B6,B7): ix=floor(x/0.25), iy=floor(y/0.25), per-drive 25cm means (>=1 pt).
Window 6x6m = +/-12 cells (25x25). Road level per (drive,cell) = 10th pct of defined
window cell means for that drive if >=N_ROAD else no-data. delta_d=mean_d-road_d.
H = average(delta_d over contributing drives). No raw-z pooling across drives.
No-data -> transparent (0,0,0,0). h<0 -> 0, h>=0.25 -> 0.25.
Ramp stops: 0,0.0625,0.125,0.1875,0.25m -> #0f1433,#1a59a6,#26b38c,#f2d933,#fff.
Render uses north-up binning: col=floor((x-x0)/cell), row=side-1-floor((y-y0)/cell).
"""

from __future__ import annotations

import numpy as np

CELL_M = 0.25
WINDOW_HALF_CELLS = 12
N_ROAD = 25

# (value_m, r,g,b)
_STOPS: list[tuple[float, int, int, int]] = [
    (0.0, 0x0F, 0x14, 0x33),
    (0.0625, 0x1A, 0x59, 0xA6),
    (0.125, 0x26, 0xB3, 0x8C),
    (0.1875, 0xF2, 0xD9, 0x33),
    (0.25, 0xFF, 0xFF, 0xFF),
]


def _lattice_index(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ix = np.floor(x / CELL_M).astype(np.int64)
    iy = np.floor(y / CELL_M).astype(np.int64)
    return ix, iy


def bin_points_to_25cm_means(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> dict[tuple[int, int], float]:
    """Per-drive 25cm lattice mean height. Defined if >=1 point in cell."""
    if len(x) == 0:
        return {}
    ix, iy = _lattice_index(x.astype(np.float64), y.astype(np.float64))
    zf = z.astype(np.float64)
    keys = np.column_stack([ix, iy])
    # stable unique keys + sums/counts
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    sums = np.bincount(inv, weights=zf, minlength=len(uniq))
    counts = np.bincount(inv, minlength=len(uniq))
    means: dict[tuple[int, int], float] = {}
    for k, s, c in zip(uniq.tolist(), sums.tolist(), counts.tolist()):
        if c >= 1:
            means[(int(k[0]), int(k[1]))] = float(s / c)
    return means


# (removed unused dataclass)


def compute_height_above_road(
    drive_points: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> dict[tuple[int, int], float]:
    """Compute build-wide H (meters above road) from one or more drives.

    drive_points: list of (x,y,z) arrays per drive (EPSG:32619 meters).
    Returns map (ix,iy)->H for defined cells; missing means no-data.
    """
    if not drive_points:
        return {}
    drive_means = [bin_points_to_25cm_means(x, y, z) for x, y, z in drive_points]

    # union of all lattice cells present
    all_cells: set[tuple[int, int]] = set()
    for dm in drive_means:
        all_cells.update(dm.keys())
    if not all_cells:
        return {}

    h_map: dict[tuple[int, int], float] = {}
    for cell in all_cells:
        deltas: list[float] = []
        for dm in drive_means:
            if cell not in dm:
                continue
            mean_d = dm[cell]
            cx, cy = cell
            # build window population of defined cell means for this drive
            pop: list[float] = []
            for dx in range(-WINDOW_HALF_CELLS, WINDOW_HALF_CELLS + 1):
                for dy in range(-WINDOW_HALF_CELLS, WINDOW_HALF_CELLS + 1):
                    nk = (cx + dx, cy + dy)
                    if nk in dm:
                        pop.append(dm[nk])
            if len(pop) < N_ROAD:
                continue
            road_d = float(np.percentile(np.asarray(pop, dtype=np.float64), 10, method="linear"))
            deltas.append(mean_d - road_d)
        if not deltas:
            continue
        h_map[cell] = float(np.mean(np.asarray(deltas, dtype=np.float64)))
    return h_map


def _lerp_color(v: float) -> tuple[int, int, int]:
    # v in [0,0.25]
    if v <= _STOPS[0][0]:
        return (_STOPS[0][1], _STOPS[0][2], _STOPS[0][3])
    if v >= _STOPS[-1][0]:
        return (_STOPS[-1][1], _STOPS[-1][2], _STOPS[-1][3])
    for i in range(len(_STOPS) - 1):
        v0, r0, g0, b0 = _STOPS[i]
        v1, r1, g1, b1 = _STOPS[i + 1]
        if v <= v1:
            t = (v - v0) / (v1 - v0) if v1 > v0 else 0.0
            r = round(r0 + (r1 - r0) * t)
            g = round(g0 + (g1 - g0) * t)
            b = round(b0 + (b1 - b0) * t)
            return (r, g, b)
    return (_STOPS[-1][1], _STOPS[-1][2], _STOPS[-1][3])


def render_height_rgba(
    h_map: dict[tuple[int, int], float],
    x0: float,
    y0: float,
    cell: float,
    side: int,
) -> np.ndarray:
    """Render RGBA (side,side,4) uint8 for publish grid. Uses north-up binning:
    col=floor((x-x0)/cell), row=side-1-floor((y-y0)/cell). Nearest-containing 25cm cell.
    """
    out = np.zeros((side, side, 4), dtype=np.uint8)
    if side <= 0:
        return out
    # iterate pixels by centers
    for row in range(side):
        for col in range(side):
            x = x0 + (col + 0.5) * cell
            y = y0 + (side - 1 - row + 0.5) * cell
            ix = int(np.floor(x / CELL_M))
            iy = int(np.floor(y / CELL_M))
            key = (ix, iy)
            if key not in h_map:
                continue
            h = float(h_map[key])
            h = max(h, 0.0)
            h = min(0.25, h)
            r, g, b = _lerp_color(h)
            out[row, col, 0] = np.uint8(r)
            out[row, col, 1] = np.uint8(g)
            out[row, col, 2] = np.uint8(b)
            out[row, col, 3] = np.uint8(255)
    return out