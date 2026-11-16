"""Raster method for the features stage (#266, decided in #261).

Ground points are binned into a 5 cm LiDAR-intensity raster and a 5 cm height raster. Paint is the bright
detail left by a white top-hat; components are classified by width (MUTCD: lines 10-30 cm, crosswalk bars
and stop lines 30-90 cm); line centres come from intensity-weighted cross-sections at sub-pixel precision;
collinear dashes are chained into one line. Curbs are the edge of the raised side of a 6-30 cm height step,
smoothed with a B-spline.
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import shapely
from scipy import interpolate, ndimage
from shapely.errors import ShapelyError
from shapely.geometry import MultiPoint, Point, mapping, shape

from twin.contracts import RampsParams

CELL_M = 0.05
SPLAT_CELLS = 1.0  # Gaussian splat of each point (cells); one drive is about one point per 4 cells
CURB_MIN_RAISED_M2 = 4.0  # a curb borders a raised area at least this big (a sidewalk, not a bump)
TOPHAT_M = 1.25  # wider than the widest paint (crosswalk bars, about 0.6 m), so paint survives the top-hat
PAINT_MIN_T = 0.12  # top-hat floor on the 0-1 normalised intensity
PAINT_MIN_AREA_M2 = 0.05
LINE_MAX_W_M = 0.30
BAR_MAX_W_M = 0.90
LINE_MIN_LEN_M = 1.0
COMB_MIN_BARS = 3  # a ladder crosswalk is one component: rails joined by 3+ bars
COMB_LEN_M = (3.0,)  # spans at least one lane
COMB_WID_M = (1.5, 5.0)  # crosswalk width (bar length)
COMB_PITCH_M = (0.5, 1.6)
CROSS_MERGE_M = 1.0
BAR_MIN_LEN_M = 1.2
BIN_M = 1.0  # cross-section spacing along a line
SIMPLIFY_M = 0.02
DASH_MAX_GAP_M = 10.0  # MUTCD broken line: 3 m segments, 9 m gaps
DASH_MAX_OFFSET_M = 0.15
DASH_MAX_ANGLE_DEG = 5.0
BAR_GROUP_M = 3.0
BAR_MAX_ANGLE_DEG = 15.0
CROSS_MIN_BARS = 3
CURB_STEP_MIN_M, CURB_STEP_MAX_M = 0.06, 0.30
CURB_RAISED_M = 0.04  # a cell this far above the 1.5 m smoothed surface is on the raised side
CURB_MIN_LEN_M = 3.0
CURB_SAMPLE_M = 0.25


class Grid:
    """Points binned on a CELL_M grid: row 0 is the north edge."""

    def __init__(self, xy: np.ndarray):
        self.x0 = float(np.floor(xy[:, 0].min()))
        self.y1 = float(np.ceil(xy[:, 1].max()))
        self.w = int((xy[:, 0].max() - self.x0) / CELL_M) + 1
        self.h = int((self.y1 - xy[:, 1].min()) / CELL_M) + 1
        self.col = ((xy[:, 0] - self.x0) / CELL_M).astype(np.int64)
        self.row = ((self.y1 - xy[:, 1]) / CELL_M).astype(np.int64)

    def mean(self, values: np.ndarray, sigma: float = 0.0) -> np.ndarray:
        """Mean of values per cell, NaN where no point fell. sigma > 0 (cells) splats each point with a
        Gaussian first, so a sparse single drive still gives a continuous raster; cells with less than
        a quarter of a point of support stay NaN."""
        flat = self.row * self.w + self.col
        n = np.bincount(flat, minlength=self.w * self.h).reshape(self.h, self.w).astype(float)
        s = np.bincount(flat, weights=values, minlength=self.w * self.h).reshape(self.h, self.w)
        if sigma > 0:
            n, s = ndimage.gaussian_filter(n, sigma), ndimage.gaussian_filter(s, sigma)
            n[n < 0.25 / (2 * np.pi * sigma**2)] = 0  # a quarter of one point's peak weight
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(n > 0, s / n, np.nan)

    def xy(self, r: np.ndarray, c: np.ndarray) -> np.ndarray:
        """Cell centres (fractional rows and columns allowed) to run CRS x, y."""
        return np.column_stack([self.x0 + (c + 0.5) * CELL_M, self.y1 - (r + 0.5) * CELL_M])


def _nan_smooth(a: np.ndarray, sigma: float) -> np.ndarray:
    ok = np.isfinite(a)
    num = ndimage.gaussian_filter(np.where(ok, a, 0.0), sigma)
    den = ndimage.gaussian_filter(ok.astype(float), sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / den


def _sample(a: np.ndarray, rc: np.ndarray) -> np.ndarray:
    r = np.clip(np.round(rc[:, 0]).astype(int), 0, a.shape[0] - 1)
    c = np.clip(np.round(rc[:, 1]).astype(int), 0, a.shape[1] - 1)
    return a[r, c]


def raised(z: np.ndarray) -> np.ndarray:
    """Cells on the raised side of a step (sidewalks, islands): above the 1.5 m smoothed surface."""
    return np.nan_to_num(z - _nan_smooth(z, 1.5 / CELL_M), nan=-1) > CURB_RAISED_M


def paint_mask(intensity: np.ndarray, road: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(paint mask, normalised intensity) from a mean-intensity raster with NaN gaps. road: cells where
    paint may be (default all); the intensity range and threshold come from those cells only."""
    road = np.ones(intensity.shape, bool) if road is None else road
    ok = np.isfinite(intensity) & road
    lo, hi = np.percentile(intensity[ok], [2, 99.5]) if ok.any() else (0.0, 1.0)
    norm = np.clip((intensity - lo) / max(hi - lo, 1e-9), 0, 1)
    # One-cell gaps between scan lines are filled from neighbours so stripes stay whole.
    filled = np.where(ok, norm, _nan_smooth(norm, 1.0))
    filled = np.nan_to_num(filled, nan=0.0)
    k = round(TOPHAT_M / CELL_M) | 1
    tophat = filled - ndimage.grey_opening(filled, size=(k, k))
    near = ndimage.binary_dilation(ok, iterations=1) & road
    t = tophat[near]
    thr = max(PAINT_MIN_T, float(np.median(t) + 6 * np.median(np.abs(t - np.median(t))))) if t.size else 1.0
    mask = (tophat > thr) & near
    mask = ndimage.binary_opening(mask, iterations=1) | (mask & (tophat > 2 * thr))
    return mask, filled


def _components(mask: np.ndarray) -> list[np.ndarray]:
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    min_px = PAINT_MIN_AREA_M2 / CELL_M**2
    return [np.argwhere(lab == i + 1) for i in range(n) if (lab == i + 1).sum() >= min_px]


def _shape(rc: np.ndarray) -> dict:
    """Axis (unit, row/col space), centre, length and width in metres of a pixel set."""
    c = rc.mean(axis=0)
    d = rc - c
    _, vecs = np.linalg.eigh(d.T @ d)
    u = vecs[:, 1]
    t, s = d @ u, d @ np.array([-u[1], u[0]])
    return {"c": c, "u": u, "len": (np.ptp(t) + 1) * CELL_M, "wid": (np.ptp(s) + 1) * CELL_M, "rc": rc, "t": t}


def centreline(comp: dict, weight: np.ndarray) -> np.ndarray:
    """Sub-pixel centre line (row, col) of a stripe: per BIN_M cross-section, the intensity-weighted mean
    offset across the axis, then the median of the rows that fall in the bin."""
    rc, c, u, t = comp["rc"], comp["c"], comp["u"], comp["t"]
    n = np.array([-u[1], u[0]])
    s = (rc - c) @ n
    w = weight[rc[:, 0], rc[:, 1]] + 1e-3
    step = BIN_M / CELL_M
    edges = np.arange(t.min(), t.max() + step, step)
    pts = []
    for a, b in itertools.pairwise(edges):
        k = (t >= a) & (t <= b)
        if k.sum() < 3:
            continue
        pts.append(c + u * float(np.average(t[k], weights=w[k])) + n * float(np.average(s[k], weights=w[k])))
    ends = [c + u * t.min() + n * float(np.average(s, weights=w)), c + u * t.max() + n * float(np.average(s, weights=w))]
    line = np.array([ends[0], *pts, ends[1]]) if pts else np.array(ends)
    return line[np.argsort((line - c) @ u)]


def _merge_crosswalks(cws: list[dict]) -> list[dict]:
    """One crosswalk per crossing: pieces within CROSS_MERGE_M of each other become their convex hull."""
    polys = [shapely.Polygon([c[:2] for c in f["geometry"]["coordinates"][0]]) for f in cws]
    k = len(polys)
    adj = np.array([[polys[i].distance(polys[j]) <= CROSS_MERGE_M for j in range(k)] for i in range(k)], bool)
    n, lab = _graph_components(adj) if k else (0, [])
    out = []
    for g in range(n):
        idx = [i for i in range(k) if lab[i] == g]
        hull = shapely.union_all([polys[i] for i in idx]).convex_hull
        zc = float(np.median([cws[i]["geometry"]["coordinates"][0][0][2] for i in idx]))
        props = {"n_points": sum(cws[i]["properties"]["n_points"] for i in idx),
                 "stripes": sum(cws[i]["properties"]["stripes"] for i in idx), "area_m2": round(float(hull.area), 3)}  # fmt: skip
        out.append(_feature("crosswalk", f"crosswalk-{len(out) + 1:04d}", "Polygon",
                            [[[x, y, zc] for x, y in mapping(hull)["coordinates"][0]]], props))  # fmt: skip
    return out


def _bars_across(comp: dict) -> int:
    """Bars in a comb-shaped component: runs of the pixel profile along its long axis above half the peak
    (rails add a low constant, each bar a tall peak)."""
    if not (COMB_LEN_M[0] <= comp["len"] and COMB_WID_M[0] <= comp["wid"] <= COMB_WID_M[1]):
        return 0
    t = np.round(comp["t"]).astype(int)
    prof = np.bincount(t - t.min())
    high = np.concatenate([[False], prof > 0.5 * prof.max(), [False]])
    starts = np.flatnonzero(np.diff(high.astype(int)) == 1)
    if len(starts) < COMB_MIN_BARS:
        return 0
    gap = np.diff(starts) * CELL_M  # bar pitch, MUTCD continental/ladder about 0.6-1.5 m
    if not (COMB_PITCH_M[0] <= np.median(gap) <= COMB_PITCH_M[1]) or gap.std() > 0.35 * gap.mean():
        return 0
    return len(starts)


def _chain_dashes(lines: list[dict]) -> list[list[int]]:
    """Groups of collinear dashes: same direction, on one line, gaps up to DASH_MAX_GAP_M."""
    k = len(lines)
    parent = list(range(k))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cos_max = np.cos(np.radians(DASH_MAX_ANGLE_DEG))
    for i in range(k):
        for j in range(i + 1, k):
            a, b = lines[i], lines[j]
            if abs(float(a["dir"] @ b["dir"])) < cos_max:
                continue
            d = b["mid"] - a["mid"]
            along = abs(float(d @ a["dir"]))
            off = abs(float(d @ np.array([-a["dir"][1], a["dir"][0]])))
            gap = along - (a["len_m"] + b["len_m"]) / 2
            if off <= DASH_MAX_OFFSET_M and gap <= DASH_MAX_GAP_M:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(k):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _feature(kind: str, fid: str, geom: str, coords: Any, props: dict) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": fid, "kind": kind, "evidence": ["lidar"], "reliability": "observed", **props},
        "geometry": {"type": geom, "coordinates": coords},
    }


def extract(xyzi: np.ndarray) -> tuple[list[dict], list[dict], dict]:
    """Markings (LineStrings) and crosswalks (Polygons) from ground points (N, 4: x, y, z, intensity) in
    run CRS. Same contract as features.extract."""
    grid = Grid(xyzi[:, :2])
    intensity = grid.mean(xyzi[:, 3], sigma=SPLAT_CELLS)
    z = _nan_smooth(grid.mean(xyzi[:, 2]), 1.5)
    mask, weight = paint_mask(intensity, road=~raised(z))
    comps = [_shape(rc) for rc in _components(mask)]
    combs = [c for c in comps if c["wid"] > BAR_MAX_W_M and _bars_across(c) >= COMB_MIN_BARS]
    lines = [c for c in comps if c["wid"] <= LINE_MAX_W_M and c["len"] >= LINE_MIN_LEN_M]
    bars = [c for c in comps if LINE_MAX_W_M < c["wid"] <= BAR_MAX_W_M and c["len"] >= BAR_MIN_LEN_M]

    # Crosswalks: 3+ parallel bars side by side; ladder rails (lines across the bars, touching the group)
    # belong to the crosswalk too.
    k = len(bars)
    adj = np.zeros((k, k), bool)
    for i in range(k):
        for j in range(i + 1, k):
            near = np.linalg.norm(bars[i]["c"] - bars[j]["c"]) * CELL_M <= BAR_GROUP_M
            par = abs(float(bars[i]["u"] @ bars[j]["u"])) >= np.cos(np.radians(BAR_MAX_ANGLE_DEG))
            adj[i, j] = adj[j, i] = near and par
    n_groups, glab = (0, np.zeros(0, int)) if k == 0 else _graph_components(adj)
    crosswalks, used_bars, used_lines = [], set(), set()
    for comb in combs:
        hull = MultiPoint([tuple(p) for p in grid.xy(comb["rc"][:, 0], comb["rc"][:, 1])]).convex_hull
        zc = float(np.nanmedian(_sample(z, comb["rc"])))
        crosswalks.append(
            _feature("crosswalk", f"crosswalk-{len(crosswalks) + 1:04d}", "Polygon",
                     [[[x, y, zc] for x, y in mapping(hull)["coordinates"][0]]],
                     {"n_points": len(comb["rc"]), "stripes": _bars_across(comb), "area_m2": round(float(hull.area), 3)})
        )  # fmt: skip
    for g in range(n_groups):
        members = np.flatnonzero(glab == g)
        if len(members) < CROSS_MIN_BARS:
            continue
        rc = np.vstack([bars[i]["rc"] for i in members])
        hull = MultiPoint([tuple(p) for p in grid.xy(rc[:, 0], rc[:, 1])]).convex_hull
        for li, ln in enumerate(lines):
            mid = grid.xy(*ln["c"][:, None])[0]
            if hull.buffer(0.5).contains(shapely.Point(mid)) and abs(float(ln["u"] @ bars[members[0]]["u"])) < 0.5:
                used_lines.add(li)
                hull = MultiPoint([*hull.exterior.coords, *map(tuple, grid.xy(ln["rc"][:, 0], ln["rc"][:, 1]))]).convex_hull
        zc = float(np.nanmedian(_sample(z, rc)))
        crosswalks.append(
            _feature("crosswalk", f"crosswalk-{len(crosswalks) + 1:04d}", "Polygon",
                     [[[x, y, zc] for x, y in mapping(hull)["coordinates"][0]]],
                     {"n_points": len(rc), "stripes": len(members), "area_m2": round(float(hull.area), 3)})
        )  # fmt: skip
        used_bars.update(members.tolist())

    crosswalks = _merge_crosswalks(crosswalks)

    # Lines (and bars that are not part of a crosswalk, i.e. stop lines) become centre lines.
    singles = [lines[i] for i in range(len(lines)) if i not in used_lines]
    singles += [bars[i] for i in range(k) if i not in used_bars]
    segs = []
    for comp in singles:
        rc_line = centreline(comp, weight)
        xy = grid.xy(rc_line[:, 0], rc_line[:, 1])
        d = xy[-1] - xy[0]
        length = float(np.linalg.norm(d))
        if length <= 0:
            continue
        segs.append({"xy": xy, "rc": rc_line, "dir": d / length, "mid": xy.mean(axis=0), "len_m": length,
                     "wid": comp["wid"], "n": len(comp["rc"])})  # fmt: skip
    markings = []
    for group in _chain_dashes(segs):
        parts = sorted((segs[i] for i in group), key=lambda s: float(s["mid"] @ segs[group[0]]["dir"]))
        xy = np.vstack([p["xy"] for p in parts])
        rc = np.vstack([p["rc"] for p in parts])
        line = shapely.LineString(xy).simplify(SIMPLIFY_M)
        if line.length < LINE_MIN_LEN_M:
            continue
        coords = np.array(line.coords)
        zs = _sample(z, rc[np.argmin(np.linalg.norm(xy[:, None] - coords[None], axis=2), axis=0)])
        n = int(sum(p["n"] for p in parts))
        markings.append(
            _feature("marking", f"marking-{len(markings) + 1:04d}", "LineString",
                     [[float(x), float(y), float(zz)] for (x, y), zz in zip(coords, zs, strict=True)],
                     {"n_points": n, "length_m": round(line.length, 3), "points_per_m": round(n / line.length, 3),
                      "width_m": round(float(np.median([p["wid"] for p in parts])), 3), "dashes": len(parts)})
        )  # fmt: skip
    counts = {
        "n_paint_cells": int(mask.sum()),
        "n_components": len(comps),
        "n_markings": len(markings),
        "n_crosswalks": len(crosswalks),
        "raster_cell_m": CELL_M,
    }
    return markings, crosswalks, counts


def _graph_components(adj: np.ndarray) -> tuple[int, np.ndarray]:
    """Connected components of an adjacency matrix: (count, label per node)."""
    seen = -np.ones(len(adj), int)
    g = 0
    for i in range(len(adj)):
        if seen[i] >= 0:
            continue
        stack = [i]
        seen[i] = g
        while stack:
            for j in np.flatnonzero(adj[stack.pop()]):
                if seen[j] < 0:
                    seen[j] = g
                    stack.append(j)
        g += 1
    return g, seen


def extract_curbs(xyz: np.ndarray) -> list[dict]:
    """Curb LineStrings from ground (plus near-ground) points (N, 3): the outline of raised areas where the
    height step across 35 cm is 6-30 cm, B-spline smoothed and sampled every CURB_SAMPLE_M."""
    grid = Grid(xyz[:, :2])
    z = _nan_smooth(grid.mean(xyz[:, 2]), 1.5)
    up = raised(z)
    lab, n = ndimage.label(up)
    big = np.flatnonzero(np.bincount(lab.ravel())[1:] * CELL_M**2 >= CURB_MIN_RAISED_M2) + 1
    up = np.isin(lab, big)
    zf = np.nan_to_num(z, nan=np.nanmedian(z))
    step = ndimage.maximum_filter(zf, size=7) - ndimage.minimum_filter(zf, size=7)
    observed = ndimage.binary_erosion(np.isfinite(z), iterations=3)
    edge = up & ~ndimage.binary_erosion(up) & observed
    edge &= (step >= CURB_STEP_MIN_M) & (step <= CURB_STEP_MAX_M)
    gy, gx = np.gradient(_nan_smooth(z, 1.0))
    grad = np.nan_to_num(np.hypot(gx, gy))
    curbs = []
    lab, n = ndimage.label(edge, structure=np.ones((3, 3)))
    for i in range(n):
        rc = np.argwhere(lab == i + 1).astype(float)
        if len(rc) * CELL_M < CURB_MIN_LEN_M:
            continue
        rc = _to_steepest(_order(rc), grad)  # order the contiguous edge first; snapping scatters it
        xy = grid.xy(rc[:, 0], rc[:, 1])
        length = float(np.hypot(*np.diff(xy, axis=0).T).sum())
        if length < CURB_MIN_LEN_M:
            continue
        try:
            tck, _ = interpolate.splprep(xy.T, s=len(xy) * (0.5 * CELL_M) ** 2, k=3)
            uu = np.linspace(0, 1, max(int(length / CURB_SAMPLE_M), 2))
            sm = np.column_stack(interpolate.splev(uu, tck))
        except (ValueError, TypeError):
            sm = xy
        rcs = np.column_stack([(grid.y1 - sm[:, 1]) / CELL_M - 0.5, (sm[:, 0] - grid.x0) / CELL_M - 0.5])
        zs = _sample(ndimage.minimum_filter(zf, size=7), rcs)  # the gutter (low) side
        curbs.append(
            _feature("curb", f"curb-{len(curbs) + 1:04d}", "LineString",
                     [[float(x), float(y), float(zz)] for (x, y), zz in zip(sm, zs, strict=True)],
                     {"n_points": len(rc), "length_m": round(length, 3), "points_per_m": round(len(rc) / length, 3)})
        )  # fmt: skip
    return curbs


def _to_steepest(rc: np.ndarray, grad: np.ndarray, r: int = 4) -> np.ndarray:
    """Move each edge cell (in walking order) to the steepest cell within r cells: the curb face, not the raised
    mask's edge. Order is kept; repeats are dropped."""
    out = rc.copy()
    for i, (y, x) in enumerate(rc.astype(int)):
        y0, x0 = max(y - r, 0), max(x - r, 0)
        win = grad[y0 : y + r + 1, x0 : x + r + 1]
        dy, dx = np.unravel_index(int(np.argmax(win)), win.shape)
        out[i] = (y0 + dy, x0 + dx)
    keep = np.r_[True, np.any(np.diff(out, axis=0) != 0, axis=1)]
    return out[keep]


def _order(rc: np.ndarray) -> np.ndarray:
    """Pixels of a thin edge in walking order: start at one end of the longest axis, step to the nearest
    unvisited pixel, stop at a jump of more than 3 cells (the remainder is dropped)."""
    c = rc.mean(axis=0)
    _, vecs = np.linalg.eigh((rc - c).T @ (rc - c))
    start = int(np.argmin((rc - c) @ vecs[:, 1]))
    left = np.ones(len(rc), bool)
    out = [start]
    left[start] = False
    while left.any():
        d = np.linalg.norm(rc[left] - rc[out[-1]], axis=1)
        j = int(np.argmin(d))
        if d[j] > 3:
            break
        nxt = np.flatnonzero(left)[j]
        out.append(nxt)
        left[nxt] = False
    return rc[out]




def _axis_dir(u: np.ndarray) -> np.ndarray:
    n = float(np.hypot(u[0], u[1]))
    if n <= 0:
        return np.array([1.0, 0.0])
    v = np.array([u[0] / n, u[1] / n], dtype=float)
    if v[0] < 0 or (v[0] == 0 and v[1] < 0):
        v = -v
    return v


def _grouped_median_indices(xy: np.ndarray, origin: np.ndarray, cell: float):
    """Return unique (ix,iy), medians placeholder indices and grouped order for values externally."""
    ij = np.floor((xy - origin) / cell).astype(np.int64)
    key = ij[:, 1].astype(np.int64) * 10_000_000 + ij[:, 0].astype(np.int64)
    order = np.argsort(key, kind="quicksort")
    key_s = key[order]
    ij_s = ij[order]
    _uniq, start, count = np.unique(key_s, return_index=True, return_counts=True)
    return ij_s, order, start, count


def _grouped_medians(values: np.ndarray, order: np.ndarray, start: np.ndarray, count: np.ndarray):
    vs = values[order]
    meds = np.empty(len(start), dtype=float)
    for i, (s, c) in enumerate(zip(start, count)):
        seg = vs[s:s + c]
        m = len(seg) // 2
        part = np.partition(seg, m)
        if len(seg) % 2:
            meds[i] = float(part[m])
        else:
            meds[i] = 0.5 * (float(np.partition(seg, m - 1)[m - 1]) + float(part[m]))
    return meds


def _build_measurement_raster(xyz: np.ndarray, cell: float, centre: np.ndarray, radius: float, tangent: np.ndarray, normal: np.ndarray):
    xy = xyz[:, :2]
    rel = xy - centre
    half_t = radius
    half_n = radius
    d = np.abs(rel @ tangent) <= half_t
    d &= np.abs(rel @ normal) <= half_n
    if not np.any(d):
        return None
    sub = xyz[d]
    origin = np.floor(sub[:, :2].min(axis=0) / cell) * cell
    ij_s, order, start, count = _grouped_median_indices(sub[:, :2], origin, cell)
    meds = _grouped_medians(sub[:, 2], order, start, count)
    ij_u = ij_s[start]
    nx = int(ij_u[:, 0].max()) + 1
    ny = int(ij_u[:, 1].max()) + 1
    grid = np.full((ny, nx), np.nan, dtype=float)
    grid[ij_u[:, 1], ij_u[:, 0]] = meds
    smooth = _nan_smooth(grid, 1.0)
    valid = ndimage.maximum_filter(np.isfinite(grid).astype(float), size=3) > 0
    smooth = np.where(valid, smooth, np.nan)
    xs = origin[0] + (np.arange(nx) + 0.5) * cell
    ys = origin[1] + (np.arange(ny) + 0.5) * cell
    gx, gy = np.meshgrid(xs, ys)
    centres = np.column_stack([gx.ravel(), gy.ravel()])
    return {"smooth": smooth, "meds": grid, "centres": centres, "origin": origin, "cell": cell, "shape": (ny, nx)}


def _fit_plane(t: np.ndarray, n: np.ndarray, z: np.ndarray):
    if len(z) < 3:
        return None
    A = np.column_stack([t, n, np.ones_like(t)])
    try:
        coef, *_ = np.linalg.lstsq(A, z, rcond=None)
    except (np.linalg.LinAlgError, ValueError):
        return None
    return float(coef[0]), float(coef[1]), float(coef[2])


def extract_ramps(xyz, curbs, crosswalks, params: RampsParams):
    """Curb ramps (Point) from ground (plus near-ground) points and raster curb LineStrings."""
    gap_min = params.gap_min_m
    gap_max = params.gap_max_m
    crosswalk_end = params.crosswalk_end_m
    cell = params.measure_cell_m
    min_cells = params.min_measure_cells
    hstep_max = params.height_step_max_m
    run_thr = params.running_slope_max_pct
    cross_thr = params.cross_slope_max_pct
    flare_thr = params.flare_slope_max_pct
    gutter_thr = params.gutter_step_max_m

    pts = np.asarray(xyz, dtype=float)
    if pts.size == 0:
        return []
    if pts.ndim == 1:
        pts = pts.reshape(-1, 3)
    if pts.shape[1] < 3:
        return []
    pxy = pts[:, :2]
    pz = pts[:, 2]

    curbs = curbs or []
    crosswalks = crosswalks or []

    grid5 = Grid(pxy)
    z5 = grid5.mean(pz, sigma=SPLAT_CELLS)
    z5s = _nan_smooth(z5, 1.0)
    med5 = float(np.nanmedian(z5s)) if np.isfinite(z5s).any() else 0.0
    zf5 = np.nan_to_num(z5s, nan=med5)
    step5 = ndimage.maximum_filter(zf5, size=7) - ndimage.minimum_filter(zf5, size=7)

    cw_polys = []
    for cw in crosswalks:
        try:
            cw_polys.append((cw, shape(cw["geometry"])))
        except (AttributeError, KeyError, TypeError, ValueError, ShapelyError):
            continue

    candidates = []
    curb_endpoints = []

    def add_candidate(rx, ry, ss, i, j):
        # width_m: along-curb extent of low-step ramp/gap run
        width_along = float(ss[j] - ss[i])
        if width_along <= 1e-9:
            dx = float(rx[j] - rx[i]); dy = float(ry[j] - ry[i])
            width_along = float(np.hypot(dx, dy))
        if not (gap_min <= width_along <= gap_max):
            return
        dx = float(rx[j] - rx[i]); dy = float(ry[j] - ry[i])
        nn = float(np.hypot(dx, dy))
        cx = float(np.mean(rx[i:j + 1]))
        cy = float(np.mean(ry[i:j + 1]))
        tangent = np.array([dx / nn, dy / nn]) if nn > 1e-9 else np.array([1.0, 0.0])
        candidates.append((np.array([cx, cy]), width_along, tangent, (float(rx[i]), float(ry[i])), (float(rx[j]), float(ry[j]))))

    for pi, curb in enumerate(curbs):
        try:
            coords = np.asarray(curb["geometry"]["coordinates"], dtype=float)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if coords.ndim != 2 or len(coords) < 2:
            continue
        xy = coords[:, :2]
        seglen = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seglen)])
        total = float(cum[-1])
        if total <= 0:
            continue
        t0 = xy[1] - xy[0]
        t1 = xy[-1] - xy[-2]
        curb_endpoints.append((xy[0].copy(), -_axis_dir(t0), pi))
        curb_endpoints.append((xy[-1].copy(), _axis_dir(t1), pi))
        if total < gap_min:
            continue
        n_samp = max(int(total / CURB_SAMPLE_M) + 1, 2)
        ss = np.linspace(0.0, total, n_samp)
        rx = np.interp(ss, cum, xy[:, 0])
        ry = np.interp(ss, cum, xy[:, 1])
        rc5 = np.column_stack([(grid5.y1 - ry) / CELL_M - 0.5, (rx - grid5.x0) / CELL_M - 0.5])
        steps = _sample(step5, rc5)
        rz = np.interp(ss, cum, coords[:, 2]) if coords.shape[1] >= 3 else None
        low_step = steps < hstep_max
        if rz is not None and np.isfinite(rz).any():
            rz_ref = float(np.nanpercentile(rz, 90))
            if rz_ref >= 0.06:
                low_step = low_step | (rz <= 0.03)
        i = 0
        while i < len(ss):
            if not low_step[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(ss) and low_step[j + 1]:
                j += 1
            add_candidate(rx, ry, ss, i, j)
            i = j + 1

    # R5: curb end pairs 1-3m apart that roughly face each other
    used_pairs = set()
    for a in range(len(curb_endpoints)):
        pa, ta, ia = curb_endpoints[a]
        for b in range(a + 1, len(curb_endpoints)):
            pb, tb, ib = curb_endpoints[b]
            if ia == ib:
                continue
            d = pb - pa
            dist = float(np.hypot(d[0], d[1]))
            if not (gap_min <= dist <= gap_max):
                continue
            u = d / max(dist, 1e-9)
            if float(ta @ u) < 0.4 or float(tb @ (-u)) < 0.4:
                continue
            key = tuple(sorted((a, b)))
            if key in used_pairs:
                continue
            used_pairs.add(key)
            centroid = 0.5 * (pa + pb)
            tangent = _axis_dir(u)
            candidates.append((centroid, dist, tangent, (float(pa[0]), float(pa[1])), (float(pb[0]), float(pb[1]))))

    out = []
    for idx, (centroid, width, tangent, p0, p1) in enumerate(candidates, start=1):
        cx, cy = float(centroid[0]), float(centroid[1])
        normal = np.array([-tangent[1], tangent[0]], dtype=float)

        meas = _build_measurement_raster(pts, cell, centroid, max(5.0, width + 4.0), tangent, normal)
        if meas is None:
            continue
        centres = meas["centres"]
        smooth = meas["smooth"].ravel()
        meds = meas["meds"].ravel()
        valid = np.isfinite(meds)
        values = np.where(valid, meds, smooth)
        if not np.any(valid):
            continue
        proj_n = (centres - centroid) @ normal
        proj_t = (centres - centroid) @ tangent

        # orient normal to raised side: median of raised side 2-3m back
        back_hi = valid & (proj_n >= 2.0) & (proj_n <= 3.0)
        back_lo = valid & (proj_n <= -2.0) & (proj_n >= -3.0)
        side_level_hi = float(np.median(values[back_hi])) if np.any(back_hi) else None
        side_level_lo = float(np.median(values[back_lo])) if np.any(back_lo) else None
        if side_level_hi is None and side_level_lo is None:
            near_hi = valid & (proj_n > 0.5) & (proj_n < 2.0)
            near_lo = valid & (proj_n < -0.5) & (proj_n > -2.0)
            side_level_hi = float(np.median(values[near_hi])) if np.any(near_hi) else None
            side_level_lo = float(np.median(values[near_lo])) if np.any(near_lo) else None
        if side_level_hi is not None and side_level_lo is not None and side_level_lo > side_level_hi:
            normal = -normal
            tangent = np.array([-normal[1], normal[0]], dtype=float)
            proj_n = -proj_n
            proj_t = (centres - centroid) @ tangent
            side_level = side_level_lo
        else:
            side_level = side_level_hi if side_level_hi is not None else side_level_lo

        # R1: gutter = z minimum near curb line along normal in ramp corridor
        corr = valid & (np.abs(proj_t) <= width / 2.0) & (proj_n >= -0.6) & (proj_n <= 3.5)
        run_length_m = None
        running_slope_pct = None
        gutter_z = None
        gutter_n = None
        if np.any(corr):
            pn = proj_n[corr]
            zv = values[corr]
            gmask = (pn >= -0.35) & (pn <= 0.35)
            if not np.any(gmask):
                gmask = (pn >= -0.5) & (pn <= 0.5)
            if np.any(gmask):
                gi = int(np.argmin(zv[gmask]))
                gutter_n = float(pn[gmask][gi])
                gutter_z = float(zv[gmask][gi])
                if side_level is not None:
                    tol = 0.01
                    reach = (pn > gutter_n + 0.1) & (zv >= side_level - tol)
                    if np.any(reach):
                        top_n = float(np.min(pn[reach]))
                        run_length_m = max(top_n - gutter_n, 0.1)
                    else:
                        far = pn > gutter_n + 0.1
                        if np.any(far):
                            run_length_m = max(float(np.max(pn[far])) - gutter_n, 0.1)
                    if run_length_m is not None and gutter_z is not None:
                        running_slope_pct = abs(side_level - gutter_z) / run_length_m * 100.0
        if run_length_m is None:
            run_length_m = width
        rep_run = run_length_m

        # R2: plane fit inside ramp body only, |proj_t|<=width/2 and 0<proj_n<run
        cross_slope_pct = None
        plane_running_slope_pct = None
        if gutter_n is not None:
            body = valid & (np.abs(proj_t) <= width / 2.0) & (proj_n > gutter_n) & (proj_n < gutter_n + run_length_m)
        else:
            body = valid & (np.abs(proj_t) <= width / 2.0) & (proj_n > 0.0) & (proj_n < run_length_m)
        body_n = int(np.count_nonzero(body))
        if body_n >= min_cells:
            coef = _fit_plane(proj_t[body], proj_n[body], values[body])
            if coef is not None:
                a, b, _c = coef
                cross_slope_pct = abs(a) * 100.0
                plane_running_slope_pct = abs(b) * 100.0
        # R2: running slope from plane fit replaces profile estimate; require enough cells
        if body_n < min_cells or plane_running_slope_pct is None:
            running_slope_pct = None
            plane_running_slope_pct = None
            cross_slope_pct = None
        else:
            running_slope_pct = plane_running_slope_pct

        # flare slope: side areas outside ramp body (optional separate)
        flare_slope_pct = None
        flare_mask_left = valid & (proj_t > width / 2.0) & (proj_t <= width / 2.0 + 1.0) & (proj_n > (gutter_n or 0.0)) & (proj_n < (gutter_n or 0.0) + run_length_m)
        flare_mask_right = valid & (proj_t < -width / 2.0) & (proj_t >= -width / 2.0 - 1.0) & (proj_n > (gutter_n or 0.0)) & (proj_n < (gutter_n or 0.0) + run_length_m)
        flare_vals = []
        for fm in (flare_mask_left, flare_mask_right):
            if int(np.count_nonzero(fm)) >= min_cells:
                fcoef = _fit_plane(proj_t[fm], proj_n[fm], values[fm])
                if fcoef is not None:
                    fa, fb, _ = fcoef
                    # slope magnitude along steepest in flare patch
                    flare_vals.append(float(np.hypot(fa, fb) * 100.0))
        if flare_vals:
            flare_slope_pct = max(flare_vals)

        # R3: gutter step lip from 5cm raster, narrow band ±0.15m along normal, inside ramp width
        gutter_step_m = None
        gutter_sparse = False
        try:
            p0a = np.array(p0, dtype=float)
            p1a = np.array(p1, dtype=float)
            seg = p1a - p0a
            seg_len = float(np.hypot(seg[0], seg[1]))
            if seg_len > 1e-6:
                u_seg = _axis_dir(seg)
                n_seg = np.array([-u_seg[1], u_seg[0]])
                if float(n_seg @ normal) < 0:
                    n_seg = -n_seg
                # restrict to local window around candidate to stay cheap
                margin = width / 2.0 + 0.3
                minx = min(p0a[0], p1a[0]) - margin - 0.2
                maxx = max(p0a[0], p1a[0]) + margin + 0.2
                miny = min(p0a[1], p1a[1]) - margin - 0.2
                maxy = max(p0a[1], p1a[1]) + margin + 0.2
                mask = (pxy[:, 0] >= minx) & (pxy[:, 0] <= maxx) & (pxy[:, 1] >= miny) & (pxy[:, 1] <= maxy)
                bxy = pxy[mask]
                bz = pz[mask]
                if len(bxy):
                    rel = bxy - 0.5 * (p0a + p1a)
                    tproj = rel @ u_seg
                    nproj = rel @ n_seg
                    in_band = (np.abs(tproj) <= width / 2.0) & (np.abs(nproj) <= 0.15)
                    if int(np.count_nonzero(in_band)) >= 4:
                        bbxy = bxy[in_band]
                        bbz = bz[in_band]
                        origin5 = np.floor(bbxy.min(axis=0) / CELL_M) * CELL_M
                        ij_s, order, start, count = _grouped_median_indices(bbxy, origin5, CELL_M)
                        meds5 = _grouped_medians(bbz, order, start, count)
                        ij_u = ij_s[start]
                        centres5 = origin5 + (ij_u + 0.5) * CELL_M
                        n5 = (centres5 - 0.5 * (p0a + p1a)) @ n_seg
                        low_side = n5 < 0
                        high_side = n5 >= 0
                        # need coverage on both sides close to lip to resolve 6mm
                        near_low = low_side & (n5 >= -0.15)
                        near_high = high_side & (n5 <= 0.15)
                        if int(np.count_nonzero(near_low)) == 0 or int(np.count_nonzero(near_high)) == 0:
                            gutter_sparse = True
                        else:
                            # aggregate by normal distance to avoid intra-band variation/noise
                            ordern = np.argsort(n5)
                            nord = n5[ordern]
                            zord = meds5[ordern]
                            bins = np.round(nord / CELL_M).astype(np.int64)
                            change = np.concatenate([[0], np.flatnonzero(np.diff(bins)) + 1, [len(bins)]])
                            n_lvl = np.empty(len(change) - 1, dtype=float)
                            z_lvl = np.empty(len(change) - 1, dtype=float)
                            for k in range(len(change) - 1):
                                a, b = change[k], change[k + 1]
                                n_lvl[k] = float(np.median(nord[a:b]))
                                z_lvl[k] = float(np.median(zord[a:b]))
                            if len(z_lvl) >= 2:
                                diffs = np.abs(np.diff(z_lvl))
                                centerish = (n_lvl[:-1] >= -0.12) & (n_lvl[1:] <= 0.12)
                                if np.any(centerish):
                                    gutter_step_m = float(np.max(diffs[centerish]))
                                else:
                                    gutter_sparse = True
                            else:
                                gutter_sparse = True
                    else:
                        gutter_sparse = True
                else:
                    gutter_sparse = True
            else:
                gutter_sparse = True
        except (ValueError, np.linalg.LinAlgError):
            gutter_sparse = True

        # statuses / R3 indeterminate when too sparse to resolve
        insufficient = body_n < min_cells
        if insufficient:
            running_slope_pct = None
            cross_slope_pct = None
            flare_slope_pct = None
            gutter_step_m = None
            running_slope_status = "indeterminate"
            cross_slope_status = "indeterminate"
            flare_slope_status = "indeterminate"
            gutter_step_status = "indeterminate"
        else:
            if running_slope_pct is None or plane_running_slope_pct is None:
                running_slope_status = "indeterminate"
            else:
                running_slope_status = "ok" if plane_running_slope_pct <= run_thr else "exceeds"
            if cross_slope_pct is None:
                cross_slope_status = "indeterminate"
            else:
                cross_slope_status = "ok" if cross_slope_pct <= cross_thr else "exceeds"
            if flare_slope_pct is None:
                flare_slope_status = "indeterminate"
            else:
                flare_slope_status = "ok" if flare_slope_pct <= flare_thr else "exceeds"
            if gutter_step_m is None or gutter_sparse:
                gutter_step_status = "indeterminate"
                gutter_step_m = None if gutter_sparse else gutter_step_m
            else:
                gutter_step_status = "ok" if gutter_step_m <= gutter_thr else "exceeds"

        statuses = [running_slope_status, cross_slope_status, gutter_step_status]
        if "exceeds" in statuses:
            rollup = "exceeds"
        elif "indeterminate" in statuses:
            rollup = "indeterminate"
        else:
            rollup = "ok"

        if gutter_z is not None:
            cz = float(gutter_z)
        else:
            near_mask = np.hypot(pxy[:, 0] - cx, pxy[:, 1] - cy) <= 1.0
            cz = float(np.median(pz[near_mask])) if np.any(near_mask) else 0.0

        nearest_dist = None
        nearest_id = None
        pt = Point(cx, cy)
        for cw, geom in cw_polys:
            try:
                dist = float(geom.distance(pt))
            except (AttributeError, TypeError, ValueError, ShapelyError):
                continue
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist = dist
                nearest_id = cw.get("properties", {}).get("id")
        nearest_crosswalk_m = None if nearest_dist is None else nearest_dist
        kind = "curb_ramp" if (nearest_dist is not None and nearest_dist <= crosswalk_end) else "driveway_or_ramp"

        footprint = np.hypot(pxy[:, 0] - cx, pxy[:, 1] - cy) <= (width / 2.0 + rep_run + 0.5)
        n_pts = int(np.count_nonzero(footprint))

        rep_running = plane_running_slope_pct if plane_running_slope_pct is not None else running_slope_pct
        prop = {
            "id": f"ramp-{idx:04d}",
            "kind": kind,
            "width_m": round(float(width), 2),
            "run_length_m": round(float(rep_run), 2),
            "running_slope_pct": (None if rep_running is None else round(float(rep_running), 1)),
            "cross_slope_pct": (None if cross_slope_pct is None else round(float(cross_slope_pct), 1)),
            "flare_slope_pct": (None if flare_slope_pct is None else round(float(flare_slope_pct), 1)),
            "gutter_step_m": (None if gutter_step_m is None else round(float(gutter_step_m), 3)),
            "running_slope_status": running_slope_status,
            "cross_slope_status": cross_slope_status,
            "flare_slope_status": flare_slope_status,
            "gutter_step_status": gutter_step_status,
            "status": rollup,
            "nearest_crosswalk_m": (None if nearest_crosswalk_m is None else round(float(nearest_crosswalk_m), 3)),
            "crosswalk_id": nearest_id,
            "n_points": n_pts,
        }
        out.append(_feature("ramp", f"ramp-{idx:04d}", "Point", [[cx, cy, cz]], prop))

    return out
