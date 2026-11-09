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
from pathlib import Path
from typing import Any

import CSF
import laspy
import numpy as np
import open3d as o3d
import pyproj
from shapely import contains_xy
from shapely.geometry import shape

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
# DECISION: the sweep-disagreement QA uses ground-class points only. A +-0.5 m band around the cell surface
# also took in non-ground points (curb faces, wheels, low vegetation) that one sweep sees and another does not,
# so it measured scene content, not alignment (issue #130: 0.59 m with the band vs 0.112 m ground-only on scene-0757).
# DECISION: the slow ICP z drift is corrected here, not in align: only this stage knows which points are ground.
# The correction is a piecewise-linear dz(t) per sweep, applied to point z (poses.json stays as align wrote it).
# Smoothness weight on dz's second difference; small next to the thousands of cell residuals.
Z_SMOOTH_WEIGHT = 1.0


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


def ransac_ground(xyz: np.ndarray, params: GroundParams) -> np.ndarray:
    """Per tile: fit one plane with RANSAC; its inliers are ground. Tiles with no near-horizontal plane are non-ground."""
    ground = np.zeros(len(xyz), bool)
    tile = np.floor(xyz[:, :2] / params.tile_m).astype(np.int64)
    tile -= tile.min(axis=0)
    dims = tuple(int(d) for d in tile.max(axis=0) + 1)
    keys = np.ravel_multi_index(tile.T, dims)
    order = np.argsort(keys, kind="stable")
    _uniq, start, count = np.unique(keys[order], return_index=True, return_counts=True)
    for s, c in zip(start, count, strict=True):
        if c < MIN_PLANE_POINTS:
            continue
        idx = order[s : s + c]
        pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz[idx]))
        model, inliers = pcd.segment_plane(
            distance_threshold=params.ransac_dist_m,
            ransac_n=3,
            num_iterations=RANSAC_ITERATIONS,
        )
        if abs(model[2]) < MIN_PLANE_NORMAL_Z:
            continue
        ground[idx[np.asarray(inliers, dtype=np.int64)]] = True
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
) -> float | None:
    """P95 over cells of (max - min) across sweeps of each sweep's mean z in the cell.

    Pass ground points only. Only cells seen by two or more sweeps count.
    Returns None when no cell has two sweeps.
    """
    cs_cell, _cs_sweep, mean_cs = _cell_sweep_means(
        xy, z, sweep, origin, cell_m, shape_yx
    )
    cells, cinv = np.unique(cs_cell, return_inverse=True)
    cmax = np.full(len(cells), -np.inf)
    cmin = np.full(len(cells), np.inf)
    np.maximum.at(cmax, cinv, mean_cs)
    np.minimum.at(cmin, cinv, mean_cs)
    n_per_cell = np.bincount(cinv)
    spread = (cmax - cmin)[n_per_cell >= 2]
    if spread.size == 0:
        return None
    return float(np.percentile(spread, 95))


def _cell_sweep_means(
    xy: np.ndarray,
    z: np.ndarray,
    sweep: np.ndarray,
    origin: np.ndarray,
    cell_m: float,
    shape_yx: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mean z per (cell, sweep). Returns (cell, sweep, mean z) of the pairs."""
    ij = grid_index(xy, origin, cell_m)
    flat = ij[:, 1] * shape_yx[1] + ij[:, 0]
    sweep = sweep.astype(np.int64)
    n_sweeps = int(sweep.max()) + 1
    uniq, inv = np.unique(flat * n_sweeps + sweep, return_inverse=True)
    mean_cs = np.bincount(inv, weights=z) / np.bincount(inv)
    return uniq // n_sweeps, uniq % n_sweeps, mean_cs


def estimate_z_drift(
    xy: np.ndarray,
    z: np.ndarray,
    sweep: np.ndarray,
    t_sweep: np.ndarray,
    origin: np.ndarray,
    cell_m: float,
    shape_yx: tuple[int, int],
    knot_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Smooth per-sweep z offset dz(t) that ground cells seen by sweeps far apart in time disagree by.

    Pass ground points only. Observed cell-sweep mean = truth + dz(t_sweep); the cell's reference is the mean
    of its sweeps' means. dz is piecewise-linear on knots every knot_s seconds, least squares with a second
    difference smoothness penalty and mean(dz) = 0. Deterministic (no randomness).
    Returns (dz per sweep, knot times, knot values). Subtract dz from a sweep's z to correct it.
    """
    n = len(t_sweep)
    nk = max(2, int(np.ceil((t_sweep.max() - t_sweep.min()) / knot_s)) + 1)
    knots = np.linspace(t_sweep.min(), t_sweep.max(), nk)
    if t_sweep.max() == t_sweep.min():
        return np.zeros(n), knots, np.zeros(nk)
    # hat basis per sweep: row k of basis is the weights of sweep k on the knots
    basis = np.zeros((n, nk))
    for j in range(nk):
        e = np.zeros(nk)
        e[j] = 1.0
        basis[:, j] = np.interp(t_sweep, knots, e)
    cell, sw, mean_cs = _cell_sweep_means(xy, z, sweep, origin, cell_m, shape_yx)
    cinv = np.unique(cell, return_inverse=True)[1]
    n_per = np.bincount(cinv)
    multi = n_per[cinv] >= 2
    cell, sw, mean_cs, cinv = cell[multi], sw[multi], mean_cs[multi], cinv[multi]
    if len(cell) == 0:
        return np.zeros(n), knots, np.zeros(nk)
    cinv = np.unique(cinv, return_inverse=True)[1]
    n_per = np.bincount(cinv)
    ref = np.bincount(cinv, weights=mean_cs) / n_per
    rows = basis[sw]  # (M, nk)
    mean_rows = np.zeros((n_per.size, nk))
    np.add.at(mean_rows, cinv, rows)
    mean_rows /= n_per[:, None]
    design = rows - mean_rows[cinv]
    resid = mean_cs - ref[cinv]
    blocks = [design, np.ones((1, nk)) * (design.shape[0] ** 0.5)]
    rhs = [resid, np.zeros(1)]
    if nk >= 3:
        d2 = np.diff(np.eye(nk), n=2, axis=0) * Z_SMOOTH_WEIGHT
        blocks.append(d2)
        rhs.append(np.zeros(len(d2)))
    knot_dz = np.linalg.lstsq(np.vstack(blocks), np.concatenate(rhs), rcond=None)[0]
    return basis @ knot_dz, knots, knot_dz


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
    o3d.utility.random.seed(ctx.seed)
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
        fields = {k: f[k] for k in POINT_FIELDS}

    xyz, intensity, sweep = aligned_points(fields, ref, refined)
    keep = voxel_first(xyz, params.voxel_m)
    xyz, intensity, sweep = xyz[keep], intensity[keep], sweep[keep]
    ground = classify(xyz, params)
    if not ground.any():
        return StageResult(status="failed", message="no ground points after the split")

    cell = params.qa_cell_m
    origin = xyz[:, :2].min(axis=0)
    span = np.floor((xyz[:, :2].max(axis=0) - origin) / cell).astype(int)
    shape_yx = (int(span[1]) + 1, int(span[0]) + 1)
    gxy, gsweep = xyz[ground, :2], sweep[ground]
    p95_before = sweep_disagreement_p95(
        gxy, xyz[ground, 2], gsweep, origin, cell, shape_yx
    )
    stamps = np.array(
        [
            int(p["timestamp_us"])
            for p in json.loads((ctx.input_dir("load") / "poses.json").read_text())[
                "poses"
            ]
        ],
        dtype=float,
    )
    t_sweep = (stamps - stamps[0]) / 1e6
    dz, knots, knot_dz = estimate_z_drift(
        gxy,
        xyz[ground, 2],
        gsweep,
        t_sweep,
        origin,
        cell,
        shape_yx,
        params.z_drift_knot_s,
    )
    xyz[:, 2] -= dz[sweep]
    gz = xyz[ground, 2]
    zmean, count = surface_grid(gxy, gz, origin, cell, shape_yx)

    gij = grid_index(gxy, origin, cell)
    gflat = gij[:, 1] * shape_yx[1] + gij[:, 0]
    rmse = float(np.sqrt(np.mean((gz - zmean.ravel()[gflat]) ** 2)))
    p95 = sweep_disagreement_p95(gxy, gz, gsweep, origin, cell, shape_yx)
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
        "z_disagreement_p95_before_correction_m": p95_before,
        "z_drift_correction_p95_m": float(np.percentile(np.abs(dz), 95)),
        "z_drift_knots_s": [round(float(k), 3) for k in knots],
        "z_drift_knots_dz_m": [round(float(k), 5) for k in knot_dz],
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
    return _run(ctx, params, "ransac-tiles", ransac_ground)


@register("ground", "csf")
def run_csf(ctx: Any, params: GroundParams) -> StageResult:
    return _run(ctx, params, "csf", csf_ground)
