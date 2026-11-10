"""Stage 4 ground: aggregate aligned sweeps, voxel-downsample, split ground / non-ground, grid the surface, QA.

Source of truth: docs/design/twin-v1-spec.md, sections 4, 6 (Ground) and 8.
Prior work: docs/research/multi-sensor-sota.md section 3 (road-surface methods there are camera-based,
none gives a lidar ground filter); docs/research/related-work.md section 3 (lidar-only road features).
Methods: ransac-tiles (Open3D segment_plane per tile) and csf (cloth-simulation-filter, Apache-2.0).
Input: mask's points.npz; align's poses.json and qa.json; load's poses.json (dataset poses) and
facilities.geojson. Output: ground.laz, nonground.laz, surface.npz, qa.json.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import CSF
import laspy
import numpy as np
import pyproj
from shapely import contains_xy
from shapely.geometry import shape

from twin import heights
from twin.contracts import GroundParams, StageResult
from twin.registry import register
from twin.stages import align

CRS_EPSG = 32619
GROUND_CLASS = 2
UNASSIGNED_CLASS = 1
LAZ_SCALE_M = 0.001
POINT_FIELDS = ("x", "y", "z", "intensity", "sweep")
OUTPUT_FILES = ("ground.laz", "nonground.laz", "surface.npz", "qa.json")

# DECISION: RANSAC iteration count per tile (the spec sets none). Open3D's RNG is seeded from params.seed.
RANSAC_ITERATIONS = 1000
# DECISION: a tile needs at least this many points for a plane fit.
MIN_PLANE_POINTS = 3
# DECISION: a tile's plane must be near-horizontal (|normal z| >= 0.9, about 25 degrees), so a wall-only tile
# does not yield a "ground" plane.
MIN_PLANE_NORMAL_Z = 0.9
# DECISION: CSF iteration count and rigidness (the spec sets neither). Flat-to-gentle road: rigidness 3 is the
# package default range midpoint for road-scale clouds.
CSF_ITERATIONS = 500
CSF_RIGIDNESS = 3
# DECISION: the sweep-disagreement QA only uses points within this height of the cell's ground surface, so
# points from one sweep that sit off the road are compared and points above (vehicles, canopy) are not.
# 2026-11-10 amendment (ADR 0005): the QA also uses ground-class points only (see qa_ground), so walls, kerbs
# and vegetation inside the band no longer count as disagreement.
QA_BAND_M = 0.5


# ------------------------------------------------------------------ aggregation


def aligned_points(
    fields: dict[str, np.ndarray], ref: np.ndarray, refined: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """All masked points moved from run CRS into the refined frame.

    Returns xyz (N, 3), intensity (N,), sweep (N,) in the same order.
    Each point goes to its ego frame (dataset pose inverse, via align.ego_sweeps), then through its sweep's
    refined pose. With refined == ref this is the identity.
    """
    egos = align.ego_sweeps(fields, ref)
    order = np.argsort(fields["sweep"].astype(np.int64), kind="stable")
    intensity = fields["intensity"][order]
    xyz = []
    for k, p in enumerate(egos):
        t = refined[k]
        xyz.append(p @ t[:3, :3].T + t[:3, 3])
    lengths = [len(p) for p in egos]
    sweep = np.repeat(np.arange(len(egos), dtype=np.int32), lengths)
    return np.vstack(xyz), intensity, sweep


def voxel_first(xyz: np.ndarray, voxel_m: float) -> np.ndarray:
    """Indices of the first point in each voxel. Keeps each kept point's own intensity and sweep."""
    ijk = np.floor(xyz / voxel_m).astype(np.int64)
    ijk -= ijk.min(axis=0)
    dims = tuple(int(d) for d in ijk.max(axis=0) + 1)
    flat = np.ravel_multi_index(ijk.T, dims)
    _, first = np.unique(flat, return_index=True)
    return first


# ------------------------------------------------------------------ ground split


def _best_plane(
    pts: np.ndarray, dist: float, rng: np.random.Generator
) -> tuple[np.ndarray, float] | None:
    """Best of RANSAC_ITERATIONS planes through 3 random points: (inlier mask, |normal z|), or None.

    DECISION: own numpy RANSAC with a seeded generator. Open3D's segment_plane is multi-threaded, so the same seed
    gave different inliers from run to run (issue 139). Ties go to the first plane drawn.
    """
    n = len(pts)
    pick = rng.integers(0, n, size=(RANSAC_ITERATIONS, 3))
    p0, p1, p2 = pts[pick[:, 0]], pts[pick[:, 1]], pts[pick[:, 2]]
    normal = np.cross(p1 - p0, p2 - p0)
    norm = np.linalg.norm(normal, axis=1)
    ok = norm > 1e-9
    if not ok.any():
        return None
    normal[ok] /= norm[ok, None]
    counts = np.full(RANSAC_ITERATIONS, -1)
    for lo in range(
        0, RANSAC_ITERATIONS, 100
    ):  # chunked: keeps the distance matrix small
        sl = slice(lo, lo + 100)
        d = np.abs(
            np.einsum("kj,nj->kn", normal[sl], pts)
            - (normal[sl] * p0[sl]).sum(1)[:, None]
        )
        counts[sl] = np.where(ok[sl], (d <= dist).sum(axis=1), -1)
    best = int(np.argmax(counts))
    d = np.abs((pts - p0[best]) @ normal[best])
    return d <= dist, float(abs(normal[best, 2]))


def ransac_ground(xyz: np.ndarray, params: GroundParams, seed: int = 0) -> np.ndarray:
    """Per tile: fit one plane with RANSAC; its inliers are ground. Tiles with no near-horizontal plane are non-ground.

    Each tile draws from its own generator, seeded by (seed, tile key), so a tile's result does not depend on
    the others and the run repeats exactly.
    """
    ground = np.zeros(len(xyz), bool)
    tile = np.floor(xyz[:, :2] / params.tile_m).astype(np.int64)
    tile -= tile.min(axis=0)
    dims = tuple(int(d) for d in tile.max(axis=0) + 1)
    keys = np.ravel_multi_index(tile.T, dims)
    order = np.argsort(keys, kind="stable")
    uniq, start, count = np.unique(keys[order], return_index=True, return_counts=True)
    for key, s, c in zip(uniq, start, count, strict=True):
        if c < MIN_PLANE_POINTS:
            continue
        idx = order[s : s + c]
        best = _best_plane(
            xyz[idx], params.ransac_dist_m, np.random.default_rng([seed, int(key)])
        )
        if best is None or best[1] < MIN_PLANE_NORMAL_Z:
            continue
        ground[idx[best[0]]] = True
    return ground


def csf_ground(xyz: np.ndarray, params: GroundParams) -> np.ndarray:
    """Cloth simulation filter over the whole cloud (cloth-simulation-filter, Apache-2.0)."""
    csf = CSF.CSF()
    csf.params.bSloopSmooth = False
    csf.params.cloth_resolution = params.csf_cloth_m
    csf.params.rigidness = CSF_RIGIDNESS
    csf.params.interations = CSF_ITERATIONS
    # DECISION: the CSF classification threshold reuses ground.ransac_dist_m (the spec gives none for CSF).
    csf.params.class_threshold = params.ransac_dist_m
    csf.setPointCloud(xyz.tolist())
    ground_idx = CSF.VecInt()
    off_idx = CSF.VecInt()
    csf.do_filtering(ground_idx, off_idx, False)
    ground = np.zeros(len(xyz), bool)
    ground[np.fromiter(ground_idx, dtype=np.int64, count=len(ground_idx))] = True
    return ground


# ------------------------------------------------------------------ surface and QA


def grid_index(xy: np.ndarray, origin: np.ndarray, cell_m: float) -> np.ndarray:
    return np.floor((xy - origin) / cell_m).astype(np.int64)


def surface_grid(
    xy: np.ndarray,
    z: np.ndarray,
    origin: np.ndarray,
    cell_m: float,
    shape_yx: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Mean ground z and point count per cell. Empty cells have z = NaN."""
    ny, nx = shape_yx
    ij = grid_index(xy, origin, cell_m)
    flat = ij[:, 1] * nx + ij[:, 0]
    count = np.bincount(flat, minlength=nx * ny)
    zsum = np.bincount(flat, weights=z, minlength=nx * ny)
    with np.errstate(invalid="ignore", divide="ignore"):
        zmean = np.where(count > 0, zsum / np.maximum(count, 1), np.nan)
    return zmean.reshape(ny, nx), count.reshape(ny, nx)


def sweep_disagreement_p95(
    xy: np.ndarray,
    z: np.ndarray,
    sweep: np.ndarray,
    origin: np.ndarray,
    cell_m: float,
    shape_yx: tuple[int, int],
    zmean: np.ndarray,
) -> float | None:
    """P95 over cells of (max - min) across sweeps of each sweep's mean z in the cell.

    Only points within QA_BAND_M of the cell's ground surface count, and only cells seen by two or more sweeps.
    Returns None when no cell has two sweeps.
    """
    _ny, nx = shape_yx
    ij = grid_index(xy, origin, cell_m)
    flat = ij[:, 1] * nx + ij[:, 0]
    surf = zmean.ravel()[flat]
    band = np.isfinite(surf) & (np.abs(z - surf) <= QA_BAND_M)
    if not band.any():
        return None
    flat, z, sweep = flat[band], z[band], sweep[band].astype(np.int64)
    n_sweeps = int(sweep.max()) + 1
    cs = flat * n_sweeps + sweep
    uniq, inv = np.unique(cs, return_inverse=True)
    mean_cs = np.bincount(inv, weights=z) / np.bincount(inv)
    cell_of = uniq // n_sweeps
    cells, cinv = np.unique(cell_of, return_inverse=True)
    cmax = np.full(len(cells), -np.inf)
    cmin = np.full(len(cells), np.inf)
    np.maximum.at(cmax, cinv, mean_cs)
    np.minimum.at(cmin, cinv, mean_cs)
    n_per_cell = np.bincount(cinv)
    spread = (cmax - cmin)[n_per_cell >= 2]
    if spread.size == 0:
        return None
    return float(np.percentile(spread, 95))


def qa_ground(
    split_ground: np.ndarray, labels: np.ndarray | None, driveable_index: int | None
) -> np.ndarray:
    """Which points the disagreement QA uses: lidarseg ground where a point has a label, else the split's ground.

    DECISION (2026-11-10 amendment to ADR 0005): the labels are driveable_surface, sidewalk and terrain; a point
    of an unlabelled sweep keeps the ground split's verdict (RANSAC or CSF).
    """
    if labels is None:
        return split_ground
    labelled, is_ground = heights.label_ground(labels, driveable_index)
    return np.where(labelled, is_ground, split_ground)


def observed_core(
    features: list[dict], origin: np.ndarray, cell_m: float, count: np.ndarray
) -> dict[str, float]:
    """Share of each facility's core cells (cell centres inside the core) that have ground points."""
    ny, nx = count.shape
    out: dict[str, float] = {}
    for f in features:
        fid = f["properties"]["id"]
        geom = shape(f["geometry"])
        if geom.area == 0:
            # DECISION: a line or point facility is judged on a cell-sized buffer around it.
            geom = geom.buffer(cell_m)
        minx, miny, maxx, maxy = geom.bounds
        i0 = max(int(np.floor((minx - origin[0]) / cell_m)), 0)
        i1 = min(int(np.floor((maxx - origin[0]) / cell_m)) + 1, nx)
        j0 = max(int(np.floor((miny - origin[1]) / cell_m)), 0)
        j1 = min(int(np.floor((maxy - origin[1]) / cell_m)) + 1, ny)
        if i1 <= i0 or j1 <= j0:
            out[fid] = 0.0
            continue
        xs = origin[0] + (np.arange(i0, i1) + 0.5) * cell_m
        ys = origin[1] + (np.arange(j0, j1) + 0.5) * cell_m
        gx, gy = np.meshgrid(xs, ys)
        inside = contains_xy(geom, gx.ravel(), gy.ravel())
        n_in = int(inside.sum())
        if n_in == 0:
            out[fid] = 0.0
            continue
        seen = count[j0:j1, i0:i1].ravel()[inside] > 0
        out[fid] = float(seen.sum() / n_in)
    return out


# ------------------------------------------------------------------ output


def _write_laz(
    path: Path, xyz: np.ndarray, intensity: np.ndarray, classification: int
) -> None:
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([LAZ_SCALE_M] * 3)
    header.offsets = xyz.min(axis=0) if len(xyz) else np.zeros(3)
    header.add_crs(pyproj.CRS.from_epsg(CRS_EPSG))
    las = laspy.LasData(header)
    las.xyz = xyz
    las.intensity = intensity.astype(np.uint16)
    las.classification = np.full(len(xyz), classification, np.uint8)
    las.write(path)


def _run(
    ctx: Any,
    params: GroundParams,
    method: str,
    classify: Callable[[np.ndarray, GroundParams], np.ndarray],
) -> StageResult:
    out: Path = ctx.stage_dir("ground")
    out.mkdir(exist_ok=True)
    min_observed = ctx.min_observed
    align_dir = ctx.input_dir("align")
    align_qa = json.loads((align_dir / "qa.json").read_text())
    refined = np.array(
        [
            p["matrix"]
            for p in json.loads((align_dir / "poses.json").read_text())["poses"]
        ],
        dtype=float,
    ).reshape(-1, 4, 4)
    ref = np.array(
        [
            p["matrix"]
            for p in json.loads((ctx.input_dir("load") / "poses.json").read_text())[
                "poses"
            ]
        ],
        dtype=float,
    ).reshape(-1, 4, 4)
    features = json.loads((ctx.input_dir("load") / "facilities.geojson").read_text())[
        "features"
    ]
    with np.load(ctx.input_dir("mask") / "points.npz") as f:
        fields = {k: f[k] for k in (*POINT_FIELDS, "lidarseg") if k in f.files}

    xyz, intensity, sweep = aligned_points(fields, ref, refined)
    keep = voxel_first(xyz, params.voxel_m)
    xyz, intensity, sweep = xyz[keep], intensity[keep], sweep[keep]
    labels = None
    if (
        "lidarseg" in fields
    ):  # same point order as aligned_points: sorted by sweep, stable
        order = np.argsort(fields["sweep"].astype(np.int64), kind="stable")
        labels = fields["lidarseg"][order][keep]
    seg_file = ctx.input_dir("load") / "lidarseg.json"
    drv = (
        json.loads(seg_file.read_text()).get("driveable_index")
        if seg_file.is_file()
        else None
    )
    ground = classify(xyz, params)
    if not ground.any():
        return StageResult(status="failed", message="no ground points after the split")

    cell = params.qa_cell_m
    origin = xyz[:, :2].min(axis=0)
    span = np.floor((xyz[:, :2].max(axis=0) - origin) / cell).astype(int)
    shape_yx = (int(span[1]) + 1, int(span[0]) + 1)
    gxy, gz = xyz[ground, :2], xyz[ground, 2]
    zmean, count = surface_grid(gxy, gz, origin, cell, shape_yx)

    gij = grid_index(gxy, origin, cell)
    gflat = gij[:, 1] * shape_yx[1] + gij[:, 0]
    rmse = float(np.sqrt(np.mean((gz - zmean.ravel()[gflat]) ** 2)))
    use = qa_ground(ground, labels, drv)
    p95 = sweep_disagreement_p95(
        xyz[use, :2], xyz[use, 2], sweep[use], origin, cell, shape_yx, zmean
    )
    observed = observed_core(features, origin, cell, count)
    not_scanned = sorted(k for k, v in observed.items() if v < min_observed)

    reasons = []
    if align_qa.get("fallback_used"):
        reasons.append(
            f"align fell back to dataset poses: {align_qa.get('fallback_reason')}"
        )
    if p95 is None:
        reasons.append("no cell seen by two sweeps, so heights cannot be checked")
    elif p95 > params.qa_max_p95_m:
        reasons.append(
            f"ground-z disagreement P95 {p95:.3f} m above {params.qa_max_p95_m} m"
        )
    height_valid = not reasons

    _write_laz(out / "ground.laz", xyz[ground], intensity[ground], GROUND_CLASS)
    _write_laz(
        out / "nonground.laz", xyz[~ground], intensity[~ground], UNASSIGNED_CLASS
    )
    np.savez_compressed(
        out / "surface.npz",
        z=zmean,
        count=count,
        origin=origin,
        cell_m=np.float64(cell),
    )
    qa = {
        "method": method,
        "rmse_m": rmse,
        "z_disagreement_p95_m": p95,
        "height_valid": height_valid,
        "height_invalid_reason": "; ".join(reasons) or None,
        "qa_cell_m": cell,
        "qa_max_p95_m": params.qa_max_p95_m,
        "n_ground": int(ground.sum()),
        "n_nonground": int((~ground).sum()),
        "observed_core": {k: round(v, 4) for k, v in observed.items()},
        "min_observed": min_observed,
        "not_scanned_enough": not_scanned,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=qa)


@register("ground", "ransac-tiles")
def run_ransac(ctx: Any, params: GroundParams) -> StageResult:
    return _run(ctx, params, "ransac-tiles", partial(ransac_ground, seed=ctx.seed))


@register("ground", "csf")
def run_csf(ctx: Any, params: GroundParams) -> StageResult:
    return _run(ctx, params, "csf", csf_ground)
