"""Stage 5 features: markings and crosswalks from lidar intensity on ground points.

Source of truth: docs/design/twin-v1-spec.md, sections 4, 6 (Markings and crosswalks) and 8.
Prior work: docs/research/related-work.md section 3 (guan-2014-road-markings-mls, read at title level only;
its method is not reused); docs/research/multi-sensor-sota.md section 3 (no lidar marking method there).
Clustering uses Open3D cluster_dbscan, which is already a dependency.
Curbs (features.curbs, height-step method, section 6) are found from the same ground points.
Input: ground's ground.laz and qa.json. Output: markings.geojson, crosswalks.geojson, qa.json, and
curbs.geojson only when features.curbs.enabled is true.
Geometry follows the points: gaps are not bridged and no modelled geometry is produced here. Any later
inferred feature must be a separate feature with reliability "modelled" and evidence [].
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import open3d as o3d
import shapely
from shapely.geometry import MultiPoint, mapping, shape
from shapely.ops import unary_union

from twin.contracts import CurbsParams, FeaturesParams, SelectParams, StageResult
from twin.registry import register
from twin.select import go, paint_contrast, road_density

OUTPUT_FILES = ("markings.geojson", "crosswalks.geojson", "qa.json")
# Lidarseg gate. DECISION: ground.laz does not carry the lidarseg label (align and ground are separate stages), so
# each marking collects the labelled load points within this distance (m) in plan. Load points use the dataset
# poses, ground points the refined ones; the radius absorbs that small offset.
LIDARSEG_RADIUS_M = 0.5
LIDARSEG_STEP_M = 0.25
EVIDENCE_LIDARSEG = "lidarseg"
EVIDENCE_NO_LABELS = "lidarseg: insufficient labels"
# Marking types (operator, 2026-11-09). DECISION: distances 1 m as in the ticket; a divider must run within
# DIVIDER_MAX_ANGLE_DEG of the map divider next to it, a stop line within STOP_MAX_ANGLE_DEG of the map stop line's
# long axis (a stop line runs across the lane, so does its map polygon).
TYPE_NEAR_M = 1.0
DIVIDER_MAX_ANGLE_DEG = 20.0
STOP_MAX_ANGLE_DEG = 30.0
# The divider angle test only runs on markings at least this long (m); operator decision 2026-11-09.
DIVIDER_ANGLE_MIN_LEN_M = 3.0
MARKING_TYPES = ("divider", "stop_line", "crosswalk_stripe", "other_paint")
# Operator decision (2026-11-08): markings follow the points, binned 1.0 m along the stripe axis.
BIN_M = 1.0
# DECISION: the intensity percentile is taken per square tile of this side (the spec gives no size;
# matches the ground stage's default ground.tile_m, which this stage does not receive).
TILE_M = 5.0
# DECISION: a cluster at least this long (m) is a line marking. Shorter clusters are stripes or noise.
LINE_MIN_LEN_M = 2.0
# DECISION: two clusters can share a crosswalk group if their centres are within this distance (m) and
# their stripe axes differ by at most this angle (degrees).
CROSS_GROUP_M = 6.0
CROSS_MAX_ANGLE_DEG = 15.0
# DECISION: a crosswalk needs at least this many stripes in one group.
CROSS_MIN_STRIPES = 3
# DECISION: curb step test on a grid of this cell side (m). Each cell takes its median z.
# Ceiling: a cell straddling the edge dilutes the step; a finer cell is noisier.
CURB_CELL_M = 0.25
# DECISION: curb-top points within this distance (m) of each other form one curb line.
CURB_EPS_M = 0.5
CURB_FILE = "curbs.geojson"
# DECISION: non-ground points count as curb input when they are at most step_max_m + this (m) above the
# ground surface. Ground's per-tile plane leaves a straddling sidewalk in nonground.laz. Taller
# non-ground (cars, walls, poles) stays out.
CURB_ABOVE_SLACK_M = 0.05
# DECISION: empty surface cells take the mean of measured neighbours, out to this distance (m), so a
# straddled tile's non-ground side still has a height reference. Used only for the keep filter.
SURFACE_FILL_M = 3.0


def high_intensity(xyz: np.ndarray, intensity: np.ndarray, pct: float) -> np.ndarray:
    """Mask of points at or above the intensity percentile of their TILE_M tile."""
    keep = np.zeros(len(xyz), bool)
    tile = np.floor(xyz[:, :2] / TILE_M).astype(np.int64)
    tile -= tile.min(axis=0)
    dims = tuple(int(d) for d in tile.max(axis=0) + 1)
    keys = np.ravel_multi_index(tile.T, dims)
    order = np.argsort(keys, kind="stable")
    _uniq, start, count = np.unique(keys[order], return_index=True, return_counts=True)
    for s, c in zip(start, count, strict=True):
        idx = order[s : s + c]
        thr = np.percentile(intensity[idx], pct)
        keep[idx] = intensity[idx] >= thr
    return keep


def cluster_xy(xy: np.ndarray, eps: float, min_points: int) -> np.ndarray:
    """DBSCAN labels on the plan (x, y). -1 is noise."""
    pcd = o3d.geometry.PointCloud(
        o3d.utility.Vector3dVector(np.column_stack([xy, np.zeros(len(xy))]))
    )
    return np.asarray(
        pcd.cluster_dbscan(eps=eps, min_points=min_points), dtype=np.int64
    )


def _axis(xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Centre and unit major axis of a point set (PCA on x, y)."""
    c = xy.mean(axis=0)
    cov = np.cov((xy - c).T) if len(xy) > 1 else np.zeros((2, 2))
    _w, v = np.linalg.eigh(cov)
    return c, v[:, 1]


def _components(adj: list[list[int]]) -> list[list[int]]:
    seen = [False] * len(adj)
    out = []
    for s in range(len(adj)):
        if seen[s]:
            continue
        stack, comp = [s], []
        seen[s] = True
        while stack:
            i = stack.pop()
            comp.append(i)
            for j in adj[i]:
                if not seen[j]:
                    seen[j] = True
                    stack.append(j)
        out.append(comp)
    return out


def binned_pieces(
    xyz: np.ndarray, c: np.ndarray, u: np.ndarray, bin_m: float = BIN_M
) -> list[tuple[np.ndarray, int]]:
    """Pieces of one stripe: median (x, y, z) per bin along the axis. An empty bin ends a piece.

    A piece of one bin uses that bin's two real extreme points as vertices. Returns (vertices, n_points)
    per piece; no point is invented.
    """
    t = (xyz[:, :2] - c) @ u
    # Equal bins that span the stripe, about bin_m long each. This avoids a sliver bin at the end.
    nb = max(1, round((t.max() - t.min()) / bin_m))
    width = (t.max() - t.min()) / nb
    b = np.minimum(np.floor((t - t.min()) / width), nb - 1).astype(np.int64)
    bins = np.unique(b)
    pieces = []
    for group in np.split(bins, np.flatnonzero(np.diff(bins) > 1) + 1):
        in_piece = np.isin(b, group)
        if len(group) >= 2:
            verts = np.array([np.median(xyz[b == g], axis=0) for g in group])
        else:
            sel, tt = xyz[in_piece], t[in_piece]
            verts = np.array([sel[np.argmin(tt)], sel[np.argmax(tt)]])
        pieces.append((verts, int(in_piece.sum())))
    return pieces


def curb_top_mask(xyz: np.ndarray, params: CurbsParams) -> np.ndarray:
    """Points on the high side of a height step: their cell's median z is step_min_m to step_max_m above
    the median z of a 4-neighbour cell. Lower-side and flat cells are not marked.
    """
    tile = np.floor((xyz[:, :2] - xyz[:, :2].min(axis=0)) / CURB_CELL_M).astype(
        np.int64
    )
    dims = tuple(int(d) for d in tile.max(axis=0) + 1)
    key = np.ravel_multi_index(tile.T, dims)
    order = np.lexsort((xyz[:, 2], key))
    _cells, start, count = np.unique(key[order], return_index=True, return_counts=True)
    med = np.full(int(np.prod(dims)), np.nan)
    med[_cells] = xyz[order, 2][start + (count - 1) // 2]
    grid = np.pad(med.reshape(dims), 1, constant_values=np.nan)
    nx, ny = dims
    core = grid[1:-1, 1:-1]
    high = np.zeros(dims, bool)
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nb = grid[1 + di : 1 + di + nx, 1 + dj : 1 + dj + ny]
        dz = core - nb  # NaN (no ground in the neighbour cell) compares False
        high |= (dz >= params.step_min_m) & (dz <= params.step_max_m)
    return high[tile[:, 0], tile[:, 1]]


def extract_curbs(xyz: np.ndarray, params: CurbsParams, min_points: int) -> list[dict]:
    """Curb LineStrings from ground points xyz (N, 3). Vertex z is the bin median of measured points."""
    pts = xyz[curb_top_mask(xyz, params)]
    if len(pts) == 0:
        return []
    labels = cluster_xy(pts[:, :2], CURB_EPS_M, min_points)
    curbs: list[dict] = []
    for lab in np.unique(labels[labels >= 0]):
        p = pts[labels == lab]
        c, u = _axis(p[:, :2])
        t = (p[:, :2] - c) @ u
        if t.max() - t.min() < LINE_MIN_LEN_M:
            continue
        for verts, n in binned_pieces(p, c, u):
            length = float(np.hypot(*np.diff(verts[:, :2], axis=0).T).sum())
            if length <= 0:
                continue
            curbs.append(
                _feature(
                    "curb",
                    f"curb-{len(curbs) + 1:04d}",
                    "LineString",
                    [[float(v) for v in vert] for vert in verts],
                    {
                        "n_points": n,
                        "length_m": round(length, 3),
                        "points_per_m": round(n / length, 3),
                    },
                )
            )
    return curbs


def _near_ground_nonground(ground_dir, max_above_m: float) -> np.ndarray:
    """Non-ground points at most max_above_m above the ground surface of their cell.

    Cells with no surface (no ground point in them) are skipped. Heights come from surface.npz (mean
    ground z per cell).
    """
    las = laspy.read(ground_dir / "nonground.laz")
    xyz = np.column_stack([las.x, las.y, las.z]).astype(np.float64)
    with np.load(ground_dir / "surface.npz") as f:
        zg, origin, cell = f["z"], f["origin"], float(f["cell_m"])
    zg = _fill_surface(zg, cell)
    ny, nx = zg.shape
    ij = np.floor((xyz[:, :2] - origin) / cell).astype(np.int64)
    inside = (ij >= 0).all(axis=1) & (ij[:, 0] < nx) & (ij[:, 1] < ny)
    surf = np.full(len(xyz), np.nan)
    surf[inside] = zg[ij[inside, 1], ij[inside, 0]]
    return xyz[xyz[:, 2] - surf <= max_above_m]  # NaN surface compares False


def _fill_surface(zg: np.ndarray, cell: float) -> np.ndarray:
    """Fill empty surface cells from measured neighbours, out to SURFACE_FILL_M, by repeated 8-neighbour mean.

    Used only as the height reference for the keep filter. Curb vertices never take these values.
    """
    z = zg.copy()
    for _ in range(max(1, round(SURFACE_FILL_M / cell))):
        nan = np.isnan(z)
        if not nan.any():
            break
        pad = np.pad(z, 1, constant_values=np.nan)
        acc = np.zeros_like(z)
        cnt = np.zeros_like(z)
        ny, nx = z.shape
        for di in (0, 1, 2):
            for dj in (0, 1, 2):
                if di == 1 and dj == 1:
                    continue
                nb = pad[di : di + ny, dj : dj + nx]
                ok = ~np.isnan(nb)
                acc[ok] += nb[ok]
                cnt[ok] += 1
        fill = nan & (cnt > 0)
        z[fill] = acc[fill] / cnt[fill]
    return z


def _lift(coords: Any, z: float) -> Any:
    """Add a z value to nested shapely coordinate lists."""
    if isinstance(coords[0], (list, tuple)):
        return [_lift(c, z) for c in coords]
    return [float(coords[0]), float(coords[1]), float(z)]


def _feature(
    kind: str, fid: str, geom: str, coords: Any, props: dict[str, Any]
) -> dict[str, Any]:
    # Every feature carries its evidence: the sensors that saw it (the colour stage adds "camera" later).
    return {
        "type": "Feature",
        "properties": {
            "id": fid,
            "kind": kind,
            "evidence": ["lidar"],
            "reliability": "observed",
            **props,
        },
        "geometry": {"type": geom, "coordinates": coords},
    }


def extract(
    xyz: np.ndarray, params: FeaturesParams
) -> tuple[list[dict], list[dict], dict[str, int]]:
    """Markings (LineStrings) and crosswalks (Polygons) from ground points xyz (N, 3) with intensity.

    Returns (markings, crosswalks, counts). Coordinates are in run CRS with marking z measured per vertex (bin median) and crosswalk z the stripes' mean.
    """
    xyz, intensity = xyz[:, :3], xyz[:, 3]
    keep = high_intensity(xyz, intensity, params.intensity_pct)
    pts = xyz[keep]
    labels = cluster_xy(pts[:, :2], params.cluster_eps_m, params.min_points)
    clusters = []
    for lab in np.unique(labels[labels >= 0]):
        p = pts[labels == lab]
        c, u = _axis(p[:, :2])
        t = (p[:, :2] - c) @ u
        clusters.append(
            {
                "xy": p[:, :2],
                "xyz": p[:, :3],
                "z": float(p[:, 2].mean()),
                "n": len(p),
                "c": c,
                "u": u,
                "len": float(t.max() - t.min()),
            }
        )

    # Crosswalk candidates: clusters close together with near-parallel axes, grouped by connectivity.
    k = len(clusters)
    adj: list[list[int]] = [[] for _ in range(k)]
    if k:
        cen = np.array([cl["c"] for cl in clusters])
        ax = np.array([cl["u"] for cl in clusters])
        dist = np.linalg.norm(cen[:, None, :] - cen[None, :, :], axis=2)
        par = np.abs(ax @ ax.T) >= np.cos(np.radians(CROSS_MAX_ANGLE_DEG))
        near = (dist <= CROSS_GROUP_M) & par
        for i, j in zip(*np.nonzero(np.triu(near, 1)), strict=True):
            adj[i].append(int(j))
            adj[j].append(int(i))

    crosswalks: list[dict] = []
    used = set()
    for comp in _components(adj):
        if len(comp) < CROSS_MIN_STRIPES:
            continue
        cen = np.array([clusters[i]["c"] for i in comp])
        mean_u = np.mean([clusters[i]["u"] for i in comp], axis=0)
        mean_u /= np.linalg.norm(mean_u)
        normal = np.array([-mean_u[1], mean_u[0]])
        along = np.ptp(cen @ mean_u)
        across = np.ptp(cen @ normal)
        # Stripes side by side (across the group wider than along it) are a crosswalk.
        # Collinear dashes of one line are not.
        if across <= along:
            continue
        # Footprint = union of each stripe's observed hull. Gaps between stripes are not filled.
        footprints = [
            MultiPoint([tuple(q) for q in clusters[i]["xy"]]).convex_hull for i in comp
        ]
        group = unary_union([f for f in footprints if f.area > 0])
        if group.is_empty or group.area == 0:
            continue
        z = float(np.mean([clusters[i]["z"] for i in comp]))
        n = int(sum(clusters[i]["n"] for i in comp))
        crosswalks.append(
            _feature(
                "crosswalk",
                f"crosswalk-{len(crosswalks) + 1:04d}",
                group.geom_type,
                _lift(mapping(group)["coordinates"], z),
                {
                    "n_points": n,
                    "stripes": len(comp),
                    "area_m2": round(float(group.area), 3),
                    "points_per_m2": round(n / group.area, 3),
                },
            )
        )
        used.update(comp)

    markings: list[dict] = []
    for i, cl in enumerate(clusters):
        if i in used or cl["len"] < LINE_MIN_LEN_M:
            continue
        for verts, n in binned_pieces(cl["xyz"], cl["c"], cl["u"]):
            length = float(np.hypot(*np.diff(verts[:, :2], axis=0).T).sum())
            if length <= 0:
                continue
            markings.append(
                _feature(
                    "marking",
                    f"marking-{len(markings) + 1:04d}",
                    "LineString",
                    [[float(v) for v in vert] for vert in verts],
                    {
                        "n_points": n,
                        "length_m": round(length, 3),
                        "points_per_m": round(n / length, 3),
                    },
                )
            )

    counts = {
        "n_high_intensity": int(keep.sum()),
        "n_clusters": k,
        "n_markings": len(markings),
        "n_crosswalks": len(crosswalks),
    }
    return markings, crosswalks, counts


def lidarseg_gate(
    markings: list[dict], load_dir: Path | None, params: FeaturesParams
) -> tuple[list[dict], dict[str, int]]:
    """Keep a marking only if its lidarseg-labelled points are mostly flat.driveable_surface.

    Labels come from load's points.npz (255 = no label, i.e. a non-keyframe sweep). A marking with fewer than
    lidarseg_min_points labelled points nearby is kept as it is, with evidence noting it. A marking whose flat share
    is below lidarseg_flat_share is dropped. Nothing is invented or relabelled.
    """
    xy = seg = None
    drv = None
    if load_dir is not None and (load_dir / "lidarseg.json").is_file():
        meta = json.loads((load_dir / "lidarseg.json").read_text())
        drv = meta.get("driveable_index")
        with np.load(load_dir / "points.npz") as f:
            if "lidarseg" in f.files:
                lab = f["lidarseg"] != meta.get("sentinel", 255)
                xy = np.column_stack([f["x"][lab], f["y"][lab]])
                seg = f["lidarseg"][lab]
    tree = None
    if xy is not None and len(xy) and drv is not None:
        pcd = o3d.geometry.PointCloud(
            o3d.utility.Vector3dVector(np.column_stack([xy, np.zeros(len(xy))]))
        )
        tree = o3d.geometry.KDTreeFlann(pcd)
    kept: list[dict] = []
    counts = {"n_dropped_lidarseg": 0, "n_lidarseg_insufficient_labels": 0}
    for m in markings:
        n = flat = 0
        if tree is not None:
            line = shapely.segmentize(
                shapely.force_2d(shape(m["geometry"])), LIDARSEG_STEP_M
            )
            hit: set[int] = set()
            for x, y in shapely.get_coordinates(line):
                hit.update(
                    tree.search_radius_vector_3d([x, y, 0.0], LIDARSEG_RADIUS_M)[1]
                )
            idx = np.fromiter(hit, int, len(hit))
            n = len(idx)
            flat = int((seg[idx] == drv).sum()) if n else 0
        props = m["properties"]
        props["lidarseg_n_labelled"] = n
        if n < params.lidarseg_min_points:
            props["lidarseg_flat_share"] = None
            props["evidence"] = [*props["evidence"], EVIDENCE_NO_LABELS]
            counts["n_lidarseg_insufficient_labels"] += 1
        elif flat / n < params.lidarseg_flat_share:
            counts["n_dropped_lidarseg"] += 1
            continue
        else:
            props["lidarseg_flat_share"] = round(flat / n, 3)
            props["evidence"] = [*props["evidence"], EVIDENCE_LIDARSEG]
        kept.append(m)
    return kept, counts


def _chord(line: shapely.LineString) -> np.ndarray:
    c = np.asarray(line.coords)
    d = c[-1, :2] - c[0, :2]
    return d / (np.linalg.norm(d) or 1.0)


def _angle_deg(u: np.ndarray, v: np.ndarray) -> float:
    """Angle between two directions, ignoring sign: 0 to 90 degrees."""
    return math.degrees(math.acos(min(1.0, abs(float(u @ v)))))


def _long_axis(poly: shapely.Polygon) -> np.ndarray:
    pts = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:3]
    a, b = pts[1] - pts[0], pts[2] - pts[1]
    d = a if np.linalg.norm(a) >= np.linalg.norm(b) else b
    return d / (np.linalg.norm(d) or 1.0)


def _nearest(geoms: list, g: Any) -> Any:
    return min(geoms, key=lambda x: x.distance(g)) if geoms else None


def marking_type(line: Any, ref: dict[str, list]) -> str:
    """divider, stop_line, crosswalk_stripe or other_paint, from the map layers in `ref` (2D geometries by layer).

    Order: inside a ped_crossing, then across and within 1 m of a stop_line, then running along and within 1 m of a
    lane or road divider. Anything else is other_paint.
    """
    line = shapely.force_2d(line)
    centre = line.centroid
    if any(p.contains(centre) for p in ref.get("ped_crossing", [])):
        return "crosswalk_stripe"
    stop = _nearest(ref.get("stop_line", []), line)
    if (
        stop is not None
        and stop.distance(line) <= TYPE_NEAR_M
        and _angle_deg(_chord(line), _long_axis(stop)) <= STOP_MAX_ANGLE_DEG
    ):
        return "stop_line"
    div = _nearest(ref.get("divider", []), line)
    if div is not None:
        verts = shapely.points(shapely.get_coordinates(shapely.segmentize(line, 0.25)))
        if float(np.median(shapely.distance(verts, div))) <= TYPE_NEAR_M:
            s = div.project(centre)
            p0 = div.interpolate(max(s - 1.0, 0.0))
            p1 = div.interpolate(min(s + 1.0, div.length))
            d = np.array([p1.x - p0.x, p1.y - p0.y])
            # ponytail: the better fix is to chain dash fragments along a line before measuring their direction.
            # Until then a fragment shorter than DIVIDER_ANGLE_MIN_LEN_M is too short for a reliable chord direction,
            # so only its distance to the divider is tested.
            short = line.length < DIVIDER_ANGLE_MIN_LEN_M
            if np.linalg.norm(d) > 0 and (
                short
                or _angle_deg(_chord(line), d / np.linalg.norm(d))
                <= DIVIDER_MAX_ANGLE_DEG
            ):
                return "divider"
    return "other_paint"


def type_markings(markings: list[dict], reference: list[dict]) -> dict[str, int]:
    """Set properties.marking_type on each marking, using load's reference features. Returns count per type."""
    ref: dict[str, list] = {"ped_crossing": [], "stop_line": [], "divider": []}
    for f in reference:
        layer = f["properties"].get("layer")
        key = "divider" if layer in ("lane_divider", "road_divider") else layer
        if key in ref:
            g = shapely.force_2d(shape(f["geometry"]))
            ref[key].extend(g.geoms if hasattr(g, "geoms") else [g])
    counts = dict.fromkeys(MARKING_TYPES, 0)
    for m in markings:
        t = marking_type(shape(m["geometry"]), ref)
        m["properties"]["marking_type"] = t
        counts[t] += 1
    return counts


def _measured_footprint(ground_dir) -> list:
    """Union of the 0.5 m surface cells that have ground points: the area road_density divides by."""
    with np.load(ground_dir / "surface.npz") as f:
        measured, origin, cell = f["count"] > 0, f["origin"], float(f["cell_m"])
    iy, ix = np.nonzero(measured)
    x0, y0 = origin[0] + ix * cell, origin[1] + iy * cell
    return [shapely.union_all(shapely.box(x0, y0, x0 + cell, y0 + cell))]


def _read_ground(path) -> np.ndarray:
    las = laspy.read(path)
    return np.column_stack(
        [las.x, las.y, las.z, np.asarray(las.intensity, dtype=np.float64)]
    )


@register("features", "intensity")
def run_intensity(ctx: Any, params: FeaturesParams) -> StageResult:
    out = ctx.stage_dir("features")
    out.mkdir(exist_ok=True)
    ground_dir = ctx.input_dir("ground")
    ground_qa = json.loads((ground_dir / "qa.json").read_text())
    xyz = _read_ground(ground_dir / "ground.laz")
    if len(xyz) == 0:
        return StageResult(status="failed", message="no ground points to extract from")

    markings, crosswalks, counts = extract(xyz, params)
    load_dir = ctx.stage_dir("load")
    load_dir = load_dir if load_dir.is_dir() else None
    counts["n_markings_extracted"] = len(markings)
    markings, gate = lidarseg_gate(markings, load_dir, params)
    counts.update(gate)
    counts["n_markings"] = len(markings)
    ref_path = load_dir / "reference.geojson" if load_dir else None
    reference = (
        json.loads(ref_path.read_text())["features"]
        if ref_path and ref_path.is_file()
        else []
    )
    counts["n_markings_by_type"] = type_markings(markings, reference)
    fc = lambda feats: json.dumps({"type": "FeatureCollection", "features": feats})
    curbs: list[dict] = []
    files = list(OUTPUT_FILES)
    if params.curbs.enabled:
        near = _near_ground_nonground(
            ground_dir, params.curbs.step_max_m + CURB_ABOVE_SLACK_M
        )
        curbs = extract_curbs(
            np.vstack([xyz[:, :3], near]), params.curbs, params.min_points
        )
        files.append(CURB_FILE)
        counts["n_curbs"] = len(curbs)
    # Pose quality of the drive, copied onto every element so an auditor sees it per element.
    align_qa = json.loads((ctx.input_dir("align") / "qa.json").read_text())
    pose = {
        "method": align_qa["method"],
        "fallback_used": align_qa["fallback_used"],
        "xy_drift_p95_m": align_qa.get("xy_drift_p95_m"),
    }
    for feat in (*markings, *crosswalks, *curbs):
        feat["properties"]["pose"] = pose
    # Markings extractability: the select check (density plus paint contrast) on this drive's ground.
    density = road_density(xyz[:, :3], _measured_footprint(ground_dir))
    contrast = paint_contrast(xyz[:, 3])
    (out / "markings.geojson").write_text(fc(markings))
    (out / "crosswalks.geojson").write_text(fc(crosswalks))
    if params.curbs.enabled:
        (out / CURB_FILE).write_text(fc(curbs))
    else:
        (out / CURB_FILE).unlink(
            missing_ok=True
        )  # off means no curb file, even from an earlier pass
    qa = {
        "method": "intensity",
        "intensity_pct": params.intensity_pct,
        "cluster_eps_m": params.cluster_eps_m,
        "min_points": params.min_points,
        "lidarseg_flat_share": params.lidarseg_flat_share,
        "lidarseg_min_points": params.lidarseg_min_points,
        "n_ground": len(xyz),
        # Copied from ground so consumers read one place. Markings are not gated on them here.
        "height_valid": ground_qa.get("height_valid"),
        "not_scanned_enough": ground_qa.get("not_scanned_enough", []),
        "markings_extractable": go(density, contrast, SelectParams()),
        "density_pts_m2": round(density, 3),
        "paint_contrast": round(contrast, 3),
        **counts,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(status="ok", files=files, metrics=qa)
