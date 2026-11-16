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

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy import ndimage

CELL_M = 0.25
WINDOW_HALF_CELLS = 12
WINDOW_SIZE = WINDOW_HALF_CELLS * 2 + 1  # 25
WINDOW_CELLS = WINDOW_SIZE * WINDOW_SIZE
N_ROAD = 25

_STOPS_X = np.array([0.0, 0.0625, 0.125, 0.1875, 0.25], dtype=np.float64)
_STOPS_RGB = np.array(
    [
        [0x0F, 0x14, 0x33],
        [0x1A, 0x59, 0xA6],
        [0x26, 0xB3, 0x8C],
        [0xF2, 0xD9, 0x33],
        [0xFF, 0xFF, 0xFF],
    ],
    dtype=np.float64,
)


@dataclass
class HeightField:
    h: np.ndarray  # (ny, nx) float64, NaN=no-data
    ix0: int
    iy0: int

    def value(self, ix: int, iy: int) -> float | None:
        x = ix - self.ix0
        y = iy - self.iy0
        if x < 0 or y < 0 or y >= self.h.shape[0] or x >= self.h.shape[1]:
            return None
        v = float(self.h[y, x])
        return None if not np.isfinite(v) else v


def _lattice_index(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ix = np.floor(np.asarray(x, dtype=np.float64) / CELL_M).astype(np.int64)
    iy = np.floor(np.asarray(y, dtype=np.float64) / CELL_M).astype(np.int64)
    return ix, iy


def _drive_grid(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, ix0: int, iy0: int, nx: int, ny: int
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    grid = np.full((ny, nx), np.nan, dtype=np.float64)
    defined = np.zeros((ny, nx), dtype=bool)
    if len(x) == 0:
        return grid, defined
    ix, iy = _lattice_index(x, y)
    gx = ix - ix0
    gy = iy - iy0
    valid = (gx >= 0) & (gx < nx) & (gy >= 0) & (gy < ny)
    if not np.any(valid):
        return grid, defined
    gx = gx[valid]
    gy = gy[valid]
    zv = z[valid]
    flat = gy * nx + gx
    n = ny * nx
    sums = np.bincount(flat, weights=zv, minlength=n)
    counts = np.bincount(flat, minlength=n)
    has = counts >= 1
    means = np.full(n, np.nan, dtype=np.float64)
    means[has] = sums[has] / counts[has]
    grid = means.reshape((ny, nx))
    defined = has.reshape((ny, nx))
    return grid, defined


def _nan_percentile_linear_last(vals: np.ndarray, p: float) -> np.ndarray:
    """Percentile p of defined (non-nan) values along last axis, linear method.
    Assumes each row has >=1 defined value."""
    # sort puts nans at end
    s = np.sort(vals, axis=-1)
    valid = np.isfinite(s)
    n = valid.sum(axis=-1)  # shape prefix
    # index in valid prefix: (n-1)*p/100
    idxf = (n.astype(np.float64) - 1.0) * (p / 100.0)
    i0 = np.floor(idxf).astype(np.int64)
    i1 = np.ceil(idxf).astype(np.int64)
    i1 = np.minimum(i1, n - 1)
    # gather
    prefix_shape = vals.shape[:-1]
    flat_s = s.reshape(-1, s.shape[-1])
    flat_i0 = i0.reshape(-1)
    flat_i1 = i1.reshape(-1)
    rows = np.arange(flat_s.shape[0])
    v0 = flat_s[rows, flat_i0]
    v1 = flat_s[rows, flat_i1]
    frac = (idxf.reshape(-1) - flat_i0.astype(np.float64))
    out = v0 + (v1 - v0) * frac
    return out.reshape(prefix_shape)


def compute_height_above_road(
    drive_points: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> HeightField:
    """Compute build-wide H (meters above road) from one or more drives.

    drive_points: list of (x,y,z) arrays per drive (EPSG:32619 meters).
    Returns HeightField; NaN means no-data.
    """
    if not drive_points:
        return HeightField(np.zeros((0, 0), dtype=np.float64), 0, 0)

    bounds_ix: list[int] = []
    bounds_iy: list[int] = []
    norm: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for x, y, z in drive_points:
        xa = np.asarray(x, dtype=np.float64)
        ya = np.asarray(y, dtype=np.float64)
        za = np.asarray(z, dtype=np.float64)
        norm.append((xa, ya, za))
        if len(xa):
            ix, iy = _lattice_index(xa, ya)
            bounds_ix.extend([int(ix.min()), int(ix.max())])
            bounds_iy.extend([int(iy.min()), int(iy.max())])
    if not bounds_ix:
        return HeightField(np.zeros((0, 0), dtype=np.float64), 0, 0)

    ix0, ix1 = min(bounds_ix), max(bounds_ix)
    iy0, iy1 = min(bounds_iy), max(bounds_iy)
    nx = ix1 - ix0 + 1
    ny = iy1 - iy0 + 1

    pad = WINDOW_HALF_CELLS
    deltas: list[np.ndarray] = []
    for xa, ya, za in norm:
        mean_grid, defined = _drive_grid(xa, ya, za, ix0, iy0, nx, ny)
        delta = np.full((ny, nx), np.nan, dtype=np.float64)
        if not np.any(defined):
            deltas.append(delta)
            continue
        support = ndimage.uniform_filter(
            defined.astype(np.float64), size=WINDOW_SIZE, mode="constant", cval=0.0
        ) * WINDOW_CELLS
        road_ok = (support >= N_ROAD) & defined
        if np.any(road_ok):
            pad_mean = np.pad(mean_grid, pad, mode="constant", constant_values=np.nan)
            pad_def = np.pad(defined, pad, mode="constant", constant_values=False)
            win_mean = sliding_window_view(pad_mean, (WINDOW_SIZE, WINDOW_SIZE))
            win_def = sliding_window_view(pad_def, (WINDOW_SIZE, WINDOW_SIZE))
            wm = win_mean.reshape(ny, nx, WINDOW_CELLS)
            wd = win_def.reshape(ny, nx, WINDOW_CELLS)
            vals = np.where(wd, wm, np.nan)
            road = _nan_percentile_linear_last(vals, 10.0)
            delta[road_ok] = mean_grid[road_ok] - road[road_ok]
        deltas.append(delta)

    stack = np.stack(deltas, axis=0)
    all_nan = np.all(~np.isfinite(stack), axis=0)
    all_nan = np.all(~np.isfinite(stack), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        h = np.nanmean(stack, axis=0)
    h = np.where(all_nan, np.nan, h)
    return HeightField(h, ix0, iy0)


def render_height_rgba(
    h_map: HeightField,
    x0: float,
    y0: float,
    cell: float,
    side: int,
) -> np.ndarray:
    """Render RGBA (side,side,4) uint8 for publish grid. Uses north-up binning:
    col=floor((x-x0)/cell), row=side-1-floor((y-y0)/cell). Nearest-containing 25cm cell.
    """
    out = np.zeros((side, side, 4), dtype=np.uint8)
    if side <= 0 or h_map.h.size == 0:
        return out
    cols = np.arange(side)
    rows = np.arange(side)
    px = x0 + (cols + 0.5) * cell
    py = y0 + (side - 1 - rows + 0.5) * cell
    ix = np.floor(px / CELL_M).astype(np.int64) - h_map.ix0
    iy = np.floor(py / CELL_M).astype(np.int64) - h_map.iy0
    ixg, iyg = np.meshgrid(ix, iy)
    inside = (iyg >= 0) & (iyg < h_map.h.shape[0]) & (ixg >= 0) & (ixg < h_map.h.shape[1])
    vals = np.full((side, side), np.nan, dtype=np.float64)
    vals[inside] = h_map.h[iyg[inside], ixg[inside]]
    valid = np.isfinite(vals)
    if not np.any(valid):
        return out
    hv = np.clip(vals[valid], 0.0, 0.25)
    r = np.interp(hv, _STOPS_X, _STOPS_RGB[:, 0])
    g = np.interp(hv, _STOPS_X, _STOPS_RGB[:, 1])
    b = np.interp(hv, _STOPS_X, _STOPS_RGB[:, 2])
    out[valid, 0] = np.rint(r).astype(np.uint8)
    out[valid, 1] = np.rint(g).astype(np.uint8)
    out[valid, 2] = np.rint(b).astype(np.uint8)
    out[valid, 3] = 255
    return out
