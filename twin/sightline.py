"""ISD sight line test: is one sight line blocked, clear or indeterminate?

Source of truth: docs/design/twin-v1-spec.md, section 6 (ISD) and section 8.
Heights: docs/research/sight-line-heights.md (defaults 1.08 m eye and 1.08 m object, ISD Case B).
Prior work: docs/research/related-work.md section 6 (gonzalez-gomez-2019, kilani-2021 are the sight-distance
sources; no open code, so nothing is reused) and section 9 (heights).
Inputs: ground's surface.npz (as Surface), nonground points from nonground.laz, and parked points from
mask's parked.npz. This module is the test only; per-leg ISD is the next ticket.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from twin.contracts import IsdParams

CLEAR = "clear"
BLOCKED = "blocked"
INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class SightResult:
    status: str
    reason: str


@dataclass(frozen=True)
class Surface:
    """Ground surface grid (ground stage surface.npz): mean z and ground point count per cell."""

    z: np.ndarray  # (ny, nx) mean ground z, NaN where the cell is empty
    count: np.ndarray  # (ny, nx) ground points per cell
    origin: np.ndarray  # (2,) lower-left corner, run CRS
    cell_m: float

    def cell_ij(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ij = np.floor((xy - self.origin) / self.cell_m).astype(np.int64)
        ny, nx = self.z.shape
        inside = (ij[:, 0] >= 0) & (ij[:, 0] < nx) & (ij[:, 1] >= 0) & (ij[:, 1] < ny)
        return ij, inside

    def z_at(self, xy: np.ndarray) -> np.ndarray:
        """Ground z of the cell holding each (x, y). NaN outside the grid or in an empty cell.

        # DECISION: nearest cell, no interpolation (same as profile); the cell size caps z resolution.
        """
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        ij, inside = self.cell_ij(xy)
        out = np.full(len(xy), np.nan)
        ii = ij[inside]
        out[inside] = self.z[ii[:, 1], ii[:, 0]]
        return out


def _first_short_window(
    surface: Surface, a: np.ndarray, u: np.ndarray, length: float, params: IsdParams
) -> int | None:
    """Index of the first coverage window with fewer than coverage_min_pts ground points, else None.

    # DECISION: the line is cut into consecutive windows of coverage_window_m along its length. A window counts
    # the ground points (surface cell counts, cell centres) within band_m of the line. The last window takes
    # any remainder.
    """
    window = params.coverage_window_m
    n_win = max(1, int(np.ceil(length / window)))
    band = params.band_m
    cell = surface.cell_m
    ny, nx = surface.z.shape
    lo = np.minimum(a, a + u * length) - band - cell
    hi = np.maximum(a, a + u * length) + band + cell
    i0 = max(int(np.floor((lo[0] - surface.origin[0]) / cell)), 0)
    i1 = min(int(np.floor((hi[0] - surface.origin[0]) / cell)) + 1, nx)
    j0 = max(int(np.floor((lo[1] - surface.origin[1]) / cell)), 0)
    j1 = min(int(np.floor((hi[1] - surface.origin[1]) / cell)) + 1, ny)
    if i1 <= i0 or j1 <= j0:
        return 0
    xs = surface.origin[0] + (np.arange(i0, i1) + 0.5) * cell
    ys = surface.origin[1] + (np.arange(j0, j1) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys)
    rel = np.stack([gx.ravel(), gy.ravel()], axis=1) - a
    t = rel @ u
    d = np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0])
    keep = (t >= 0) & (t <= length) & (d <= band)
    win = np.minimum((t[keep] // window).astype(np.int64), n_win - 1)
    counts = surface.count[j0:j1, i0:i1].ravel()[keep]
    per_window = np.bincount(win, weights=counts, minlength=n_win)
    short = np.flatnonzero(per_window < params.coverage_min_pts)
    return int(short[0]) if short.size else None


def _blocked(
    surface: Surface,
    obstacles: np.ndarray,
    eye3: np.ndarray,
    obj3: np.ndarray,
    band_m: float,
) -> bool:
    """True if any obstacle point lies within band_m of the sight line in 3D and above the ground surface.

    The line is the 3D segment from the eye to the object point. A point counts only where its projection
    falls on the segment, so it reaches the line's height. Canopy above the line and kerbs below it stay
    outside band_m and do not block.
    # DECISION: operator, 2026-11-08: 3D distance to the line within isd.band_m (replaces the earlier
    # "above ground, below the line" test). The ground guard keeps ground noise from blocking.
    """
    if len(obstacles) == 0:
        return False
    d = obj3 - eye3
    dd = float(d @ d)
    s = ((obstacles - eye3) @ d) / dd
    on_seg = (s >= 0) & (s <= 1)
    if not on_seg.any():
        return False
    pts = obstacles[on_seg]
    closest = eye3 + s[on_seg, None] * d
    near = np.linalg.norm(pts - closest, axis=1) <= band_m
    if not near.any():
        return False
    pts = pts[near]
    gz = surface.z_at(pts[:, :2])
    return bool((np.isfinite(gz) & (pts[:, 2] > gz)).any())


def sight_line(
    eye_xy: np.ndarray,
    obj_xy: np.ndarray,
    *,
    surface: Surface,
    nonground_xyz: np.ndarray,
    params: IsdParams,
    height_valid: bool,
    parked_xyz: np.ndarray | None = None,
) -> SightResult:
    """Test one sight line from the eye point to the object point, both in run CRS (x, y).

    The eye is eye_height_m above the ground at the eye point, the object object_height_m above the ground at
    the object point. Pass parked_xyz to test the with-parked case (parked vehicles block); leave it None for
    the without-parked case.
    """
    if not height_valid:
        return SightResult(INDETERMINATE, "heights not valid (height_valid=false)")
    a = np.asarray(eye_xy, dtype=float).reshape(2)
    b = np.asarray(obj_xy, dtype=float).reshape(2)
    length = float(np.linalg.norm(b - a))
    if length == 0.0:
        return SightResult(INDETERMINATE, "eye and object at the same point")
    gz = surface.z_at(np.stack([a, b]))
    if not np.isfinite(gz).all():
        return SightResult(INDETERMINATE, "no ground surface at eye or object point")
    u = (b - a) / length
    eye_z = float(gz[0]) + params.eye_height_m
    obj_z = float(gz[1]) + params.object_height_m

    gap = _first_short_window(surface, a, u, length, params)
    if gap is not None:
        return SightResult(
            INDETERMINATE,
            f"coverage gap: window {gap} has fewer than {params.coverage_min_pts} ground points",
        )

    nonground = np.asarray(nonground_xyz, dtype=float).reshape(-1, 3)
    if parked_xyz is None:
        obstacles = nonground
    else:
        obstacles = np.vstack(
            [nonground, np.asarray(parked_xyz, dtype=float).reshape(-1, 3)]
        )
    eye3 = np.array([a[0], a[1], eye_z])
    obj3 = np.array([b[0], b[1], obj_z])
    if _blocked(surface, obstacles, eye3, obj3, params.band_m):
        return SightResult(
            BLOCKED, "object point above ground within band_m of the sight line in 3D"
        )
    return SightResult(CLEAR, "no object point between ground and the sight line")
