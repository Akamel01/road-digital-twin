"""Stage 5 features: markings and crosswalks from lidar intensity on ground points.

Source of truth: docs/design/twin-v1-spec.md, sections 4, 6 (Markings and crosswalks) and 8.
Prior work: docs/research/related-work.md section 3 (guan-2014-road-markings-mls, read at title level only;
its method is not reused); docs/research/multi-sensor-sota.md section 3 (no lidar marking method there).
Clustering uses Open3D cluster_dbscan, which is already a dependency.
Input: ground's ground.laz and qa.json. Output: markings.geojson, crosswalks.geojson, qa.json.
Curbs (features.curbs, height-step method) are not part of this stage yet.
Geometry follows the points: gaps are not bridged and no modelled geometry is produced here. Any later
inferred feature must be a separate feature with reliability "modelled" and evidence [].
"""

from __future__ import annotations

import json
from typing import Any

import laspy
import numpy as np
import open3d as o3d
from shapely.geometry import MultiPoint, mapping
from shapely.ops import unary_union

from twin.contracts import FeaturesParams, StageResult
from twin.registry import register

OUTPUT_FILES = ("markings.geojson", "crosswalks.geojson", "qa.json")
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
    xy: np.ndarray, c: np.ndarray, u: np.ndarray, bin_m: float = BIN_M
) -> list[tuple[np.ndarray, int]]:
    """Pieces of one stripe: median (x, y) per bin along the axis. An empty bin ends a piece.

    A piece of one bin uses that bin's two real extreme points as vertices. Returns (vertices, n_points)
    per piece; no point is invented.
    """
    t = (xy - c) @ u
    # Equal bins that span the stripe, about bin_m long each. This avoids a sliver bin at the end.
    nb = max(1, round((t.max() - t.min()) / bin_m))
    width = (t.max() - t.min()) / nb
    b = np.minimum(np.floor((t - t.min()) / width), nb - 1).astype(np.int64)
    bins = np.unique(b)
    pieces = []
    for group in np.split(bins, np.flatnonzero(np.diff(bins) > 1) + 1):
        in_piece = np.isin(b, group)
        if len(group) >= 2:
            verts = np.array([np.median(xy[b == g], axis=0) for g in group])
        else:
            sel, tt = xy[in_piece], t[in_piece]
            verts = np.array([sel[np.argmin(tt)], sel[np.argmax(tt)]])
        pieces.append((verts, int(in_piece.sum())))
    return pieces


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

    Returns (markings, crosswalks, counts). Coordinates are in run CRS with z from the cluster mean.
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
        for verts, n in binned_pieces(cl["xy"], cl["c"], cl["u"]):
            length = float(np.hypot(*np.diff(verts, axis=0).T).sum())
            if length <= 0:
                continue
            markings.append(
                _feature(
                    "marking",
                    f"marking-{len(markings) + 1:04d}",
                    "LineString",
                    _lift(verts.tolist(), cl["z"]),
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
    fc = lambda feats: json.dumps({"type": "FeatureCollection", "features": feats})
    (out / "markings.geojson").write_text(fc(markings))
    (out / "crosswalks.geojson").write_text(fc(crosswalks))
    qa = {
        "method": "intensity",
        "intensity_pct": params.intensity_pct,
        "cluster_eps_m": params.cluster_eps_m,
        "min_points": params.min_points,
        "n_ground": len(xyz),
        # Copied from ground so consumers read one place. Markings are not gated on them here.
        "height_valid": ground_qa.get("height_valid"),
        "not_scanned_enough": ground_qa.get("not_scanned_enough", []),
        **counts,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=qa)
