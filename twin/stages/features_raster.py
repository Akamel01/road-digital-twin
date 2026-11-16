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
from shapely.geometry import MultiPoint, mapping

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


def _paint_intermediates(intensity: np.ndarray, road: np.ndarray | None = None):
    """Shared paint-mask intermediates (road is normalised to a bool array)."""
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
    return road, ok, norm, filled, tophat, near, thr


def paint_mask(intensity: np.ndarray, road: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(paint mask, normalised intensity) from a mean-intensity raster with NaN gaps. road: cells where
    paint may be (default all); the intensity range and threshold come from those cells only."""
    road, _ok, _norm, filled, tophat, near, thr = _paint_intermediates(intensity, road)
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


def centreline(comp: dict, weight: np.ndarray) -> tuple[np.ndarray, int]:
    """Sub-pixel centre line (row, col) of a stripe: per BIN_M cross-section, the intensity-weighted mean
    offset across the axis, then the median of the rows that fall in the bin. Returns (line, n_bins_skipped)."""
    rc, c, u, t = comp["rc"], comp["c"], comp["u"], comp["t"]
    n = np.array([-u[1], u[0]])
    s = (rc - c) @ n
    w = weight[rc[:, 0], rc[:, 1]] + 1e-3
    step = BIN_M / CELL_M
    edges = np.arange(t.min(), t.max() + step, step)
    pts = []
    skipped = 0
    for a, b in itertools.pairwise(edges):
        k = (t >= a) & (t <= b)
        if k.sum() < 3:
            skipped += 1
            continue
        pts.append(c + u * float(np.average(t[k], weights=w[k])) + n * float(np.average(s[k], weights=w[k])))
    ends = [c + u * t.min() + n * float(np.average(s, weights=w)), c + u * t.max() + n * float(np.average(s, weights=w))]
    line = np.array([ends[0], *pts, ends[1]]) if pts else np.array(ends)
    return line[np.argsort((line - c) @ u)], skipped


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
    road = ~raised(z)
    road_inter, ok, norm, filled, tophat, near, thr = _paint_intermediates(intensity, road=road)
    mask, weight = paint_mask(intensity, road=road)
    raw_mask = (tophat > thr) & near
    lab, n_raw = ndimage.label(mask, structure=np.ones((3, 3)))
    min_px = PAINT_MIN_AREA_M2 / CELL_M**2
    comps = [_shape(rc) for rc in _components(mask)]
    n_components_raw = int(n_raw)
    n_components_dropped_small = n_components_raw - len(comps)
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
    n_bins_skipped = 0
    for comp in singles:
        rc_line, skipped = centreline(comp, weight)
        n_bins_skipped += skipped
        xy = grid.xy(rc_line[:, 0], rc_line[:, 1])
        d = xy[-1] - xy[0]
        length = float(np.linalg.norm(d))
        if length <= 0:
            continue
        segs.append({"xy": xy, "rc": rc_line, "dir": d / length, "mid": xy.mean(axis=0), "len_m": length,
                     "wid": comp["wid"], "n": len(comp["rc"])})  # fmt: skip
    markings = []
    dropped_short_final = 0
    chains = _chain_dashes(segs)
    n_chain_singletons = sum(1 for g in chains if len(g) == 1)
    for group in chains:
        parts = sorted((segs[i] for i in group), key=lambda s: float(s["mid"] @ segs[group[0]]["dir"]))
        xy = np.vstack([p["xy"] for p in parts])
        rc = np.vstack([p["rc"] for p in parts])
        line = shapely.LineString(xy).simplify(SIMPLIFY_M)
        if line.length < LINE_MIN_LEN_M:
            dropped_short_final += 1
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
    n_lines = len(lines)
    n_bars = len(bars)
    n_combs = len(combs)
    n_unclassified = len(comps) - n_lines - n_bars - n_combs
    chains_list = chains
    counts = {
        "n_road_cells": int(road_inter.sum()),
        "paint_threshold": float(thr),
        "n_paint_cells_raw": int(raw_mask.sum()),
        "n_paint_cells": int(mask.sum()),
        "n_components_raw": n_components_raw,
        "n_components_dropped_small": n_components_dropped_small,
        "n_components": len(comps),
        "n_lines": n_lines,
        "n_bars": n_bars,
        "n_combs": n_combs,
        "n_unclassified": n_unclassified,
        "n_bar_groups": int(n_groups if "n_groups" in locals() else 0),
        "n_crosswalks": len(crosswalks),
        "n_used_lines": len(used_lines),
        "n_used_bars": len(used_bars),
        "n_singles": len(singles),
        "n_chains": len(chains_list),
        "n_chain_singletons": n_chain_singletons,
        "n_dropped_short_final": dropped_short_final,
        "n_markings_extracted": len(markings),
        "n_markings": len(markings),
        "n_bins_skipped": n_bins_skipped,
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
