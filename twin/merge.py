"""Merge the drives of an area into one registered cloud (issue #141).

`twin area merge <name>` builds each dry drive of an area file through load, mask and align
(the existing stage functions, one scratch folder per drive), clips it to the area polygon,
then registers every drive to a reference by point-to-plane ICP in the overlap. It writes
merged.npz (every point keeps its drive index), drives.json and qa.json.

DECISION: this is its own step, not a pipeline stage. A stage takes one scene's folder as input
(contracts.STAGES); an area has many, so the contracts stay unchanged and single-drive runs are untouched.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import open3d as o3d
import shapely
from shapely.geometry import shape

from twin.contracts import Params
from twin.stages import align, ground, load, mask

# DECISION: registration works on points thinned to one per 0.3 m voxel.
ICP_VOXEL_M = 0.3
# DECISION: coarse-to-fine ICP, three correspondence distances. Dataset poses start within a few metres.
ICP_STEPS_M = (2.0, 1.0, 0.5)
ICP_MAX_ITER = 50
NORMAL_RADIUS_M = 1.0
# DECISION: a drive is registered only if enough of it lies within OVERLAP_DIST_M of the cloud so far
# and the final ICP fitness is at least MIN_FITNESS. Otherwise it stays at its dataset pose, flagged.
OVERLAP_DIST_M = 1.0
MIN_OVERLAP_POINTS = 500
MIN_FITNESS = 0.2
# DECISION: dataset heights are relative (each drive starts at z = 0), so drives differ in height by metres.
# z_offset matches points in plan view within XY_MATCH_M.
XY_MATCH_M = 0.5
# DECISION: ground disagreement is the height difference of the ground per CELL_M plan cell, where the ground is the
# GROUND_PCT-th percentile of z in the cell (cells with MIN_CELL_POINTS or more points). The tiled RANSAC split
# picked several layers (roofs, car tops) and made the pair distances meaningless. On a near-flat road a
# vertical difference is the point-to-plane distance to within cos(slope).
CELL_M = 0.5
GROUND_PCT = 10
MIN_CELL_POINTS = 5
MIN_CELLS = 200


# ------------------------------------------------------------------ geometry


def _pcd(xyz: np.ndarray, normals: bool = False) -> o3d.geometry.PointCloud:
    p = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(xyz))
    if normals:
        p.estimate_normals(
            o3d.geometry.KDTreeSearchParamHybrid(radius=NORMAL_RADIUS_M, max_nn=30)
        )
        # DECISION: normals point up, so a point-to-plane distance does not depend on scan order.
        n = np.asarray(p.normals)
        p.normals = o3d.utility.Vector3dVector(np.where(n[:, 2:] < 0, -n, n))
    return p


def nearest(query: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Index and distance of the nearest target point for each query point."""
    nns = o3d.core.nns.NearestNeighborSearch(o3d.core.Tensor(target))
    nns.knn_index()
    idx, d2 = nns.knn_search(o3d.core.Tensor(query), 1)
    return idx.numpy().ravel(), np.sqrt(d2.numpy().ravel())


def nearest_xy(query: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest target point in plan view (z ignored): index and x/y distance."""
    flat = np.array([1.0, 1.0, 0.0])
    return nearest(query * flat, target * flat)


def z_offset(src: np.ndarray, tgt: np.ndarray) -> float:
    """Median height of src over tgt where they overlap in plan view (start for ICP: drive heights are relative)."""
    idx, d = nearest_xy(src, tgt)
    ok = d <= XY_MATCH_M
    return float(np.median(tgt[idx[ok], 2] - src[ok, 2])) if ok.any() else 0.0


def yaw_translation(t: np.ndarray) -> np.ndarray:
    """Keep only the yaw and translation of a 4x4, as seen from the origin (the polygon centre): tilt is dropped."""
    yaw = np.arctan2(t[1, 0], t[0, 0])
    c, s = np.cos(yaw), np.sin(yaw)
    out = np.eye(4)
    out[:2, :2] = [[c, -s], [s, c]]
    out[:3, 3] = t[:3, 3]
    return out


def apply(t: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    return xyz @ t[:3, :3].T + t[:3, 3]


def register(src: np.ndarray, tgt: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Point-to-plane ICP of src onto tgt ((N, 3), centred on the polygon). Returns (yaw + translation 4x4, fitness, rmse)."""
    s, t = _pcd(src), _pcd(tgt, normals=True)
    est = o3d.pipelines.registration.TransformationEstimationPointToPlane()
    crit = o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=ICP_MAX_ITER)
    cur = np.eye(4)
    cur[2, 3] = z_offset(src, tgt)
    for dist in ICP_STEPS_M:
        res = o3d.pipelines.registration.registration_icp(s, t, dist, cur, est, crit)
        cur = yaw_translation(np.asarray(res.transformation))
    final = o3d.pipelines.registration.evaluate_registration(s, t, ICP_STEPS_M[-1], cur)
    return cur, float(final.fitness), float(final.inlier_rmse)


def ground_cells(xyz: np.ndarray) -> dict[tuple[int, int], float]:
    """Ground height per CELL_M plan cell: the GROUND_PCT percentile of z, for cells with enough points."""
    ij = np.floor(xyz[:, :2] / CELL_M).astype(np.int64)
    order = np.lexsort((ij[:, 1], ij[:, 0]))
    ij, z = ij[order], xyz[order, 2]
    cut = np.flatnonzero(np.any(np.diff(ij, axis=0) != 0, axis=1)) + 1
    out = {}
    for lo, hi in zip(np.r_[0, cut], np.r_[cut, len(z)], strict=True):
        if hi - lo >= MIN_CELL_POINTS:
            out[(int(ij[lo, 0]), int(ij[lo, 1]))] = float(
                np.percentile(z[lo:hi], GROUND_PCT)
            )
    return out


def ground_disagreement(ca: dict, cb: dict) -> dict | None:
    """P50/P95 of the ground height difference between two drives' ground_cells, over cells both see (>= MIN_CELLS)."""
    shared = ca.keys() & cb.keys()
    if len(shared) < MIN_CELLS:
        return None
    dz = np.abs([ca[k] - cb[k] for k in sorted(shared)])
    return {
        "n_cells": len(shared),
        "p50_m": float(np.percentile(dz, 50)),
        "p95_m": float(np.percentile(dz, 95)),
    }


def thin(xyz: np.ndarray, voxel: float) -> np.ndarray:
    return xyz[np.sort(ground.voxel_first(xyz, voxel))]


def register_drives(
    clouds: dict[str, np.ndarray], centre: np.ndarray, seed: int = 0
) -> dict:
    """Register drives to a growing reference. clouds: drive id -> (N, 3) in the map frame.

    The reference is the drive with the most points. Then, repeatedly, the unregistered drive with
    the most overlap with the registered cloud is aligned to it. Returns per-drive corrections
    (4x4, in the frame centred on `centre`), a note per drive, and the ground disagreement
    per pair before and after.
    """
    o3d.utility.random.seed(seed)
    pts = {k: thin(v - centre, ICP_VOXEL_M) for k, v in clouds.items()}
    gnd = {k: v - centre for k, v in clouds.items()}
    ids = sorted(clouds)
    ref = max(ids, key=lambda k: (len(clouds[k]), k))
    corr = {ref: np.eye(4)}
    info = {ref: {"role": "reference"}}
    target = pts[ref]
    todo = [k for k in ids if k != ref]
    while todo:
        overlap = {
            k: int((nearest_xy(pts[k], target)[1] <= OVERLAP_DIST_M).sum())
            for k in todo
        }
        k = max(todo, key=lambda x: (overlap[x], x))
        todo.remove(k)
        if overlap[k] < MIN_OVERLAP_POINTS:
            info[k] = {"role": "unregistered", "reason": f"overlap {overlap[k]} points"}
            continue
        t, fit, rmse = register(pts[k], target)
        if fit < MIN_FITNESS:
            info[k] = {"role": "unregistered", "reason": f"ICP fitness {fit:.2f}"}
            continue
        corr[k] = t
        info[k] = {"role": "registered", "fitness": fit, "rmse_m": rmse}
        target = np.vstack([target, apply(t, pts[k])])
    eye = np.eye(4)
    before = {k: ground_cells(gnd[k]) for k in ids}
    after = {k: ground_cells(apply(corr.get(k, eye), gnd[k])) for k in ids}
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            row = {
                "a": a,
                "b": b,
                "before": ground_disagreement(before[a], before[b]),
                "after": ground_disagreement(after[a], after[b]),
            }
            if row["before"] or row["after"]:
                pairs.append(row)
    return {"reference": ref, "corrections": corr, "info": info, "pairs": pairs}


def correction_summary(t: np.ndarray) -> dict:
    return {
        "dx_m": float(t[0, 3]),
        "dy_m": float(t[1, 3]),
        "dz_m": float(t[2, 3]),
        "translation_m": float(np.linalg.norm(t[:3, 3])),
        "yaw_deg": float(np.degrees(np.arctan2(t[1, 0], t[0, 0]))),
    }


# ------------------------------------------------------------------ one drive


def _poses(d: Path) -> np.ndarray:
    rows = json.loads((d / "poses.json").read_text())["poses"]
    return np.array([r["matrix"] for r in rows], dtype=float).reshape(-1, 4, 4)


def build_drive(scene: dict, work: Path, polygon, params: Params, log) -> np.ndarray:
    """load, mask, align for one scene; its aligned points inside polygon, (N, 5): x, y, z, intensity, sweep."""
    from twin.runner import StageContext

    cache = work / "clip.npy"
    if cache.is_file():
        return np.load(cache)
    ctx = StageContext(work, scene["scene_token"], params.seed, log)
    for name, fn, p in (
        ("load", load.run, params.facilities),
        ("mask", mask.run, params.mask),
        ("align", align.run_icp, params.align),
    ):
        res = fn(ctx, p)
        if res.status != "ok":
            raise RuntimeError(f"{name}: {res.message}")
    with np.load(ctx.stage_dir("mask") / "points.npz") as f:
        fields = {k: f[k] for k in mask.POINT_FIELDS}
    xyz, inten, sweep = ground.aligned_points(
        fields, _poses(ctx.stage_dir("load")), _poses(ctx.stage_dir("align"))
    )
    keep = shapely.contains_xy(polygon, xyz[:, 0], xyz[:, 1])
    out = np.column_stack([xyz, inten, sweep])[keep]
    np.save(cache, out)
    return out


# ------------------------------------------------------------------ command


def merge_area(area: dict, out: Path, params: Params, log) -> dict:
    polygon = shape(area["polygon"])
    centre = np.array([*polygon.centroid.coords[0], 0.0])
    scenes = sorted(
        (d for d in area["drives"] if d.get("build_input")), key=lambda d: d["scene"]
    )
    clouds, meta, skipped = {}, {}, []
    for sc in scenes:
        work = out / "drives" / sc["scene"]
        work.mkdir(parents=True, exist_ok=True)
        try:
            pts = build_drive(sc, work, polygon, params, log)
        except Exception as exc:  # noqa: BLE001 # DECISION: a drive whose files are missing or whose stages fail is skipped and listed
            reason = f"{type(exc).__name__}: {exc}"
            skipped.append({"scene": sc["scene"], "reason": reason})
            log.warning("skip %s: %s", sc["scene"], reason)
            continue
        if len(pts) == 0:
            skipped.append({"scene": sc["scene"], "reason": "no points in the polygon"})
            continue
        clouds[sc["scene"]] = pts
        meta[sc["scene"]] = sc
    if not clouds:
        raise RuntimeError("no drive could be built")
    res = register_drives({k: v[:, :3] for k, v in clouds.items()}, centre, params.seed)
    names = sorted(clouds)
    parts = []
    for i, k in enumerate(names):
        p = clouds[k]
        xyz = apply(res["corrections"].get(k, np.eye(4)), p[:, :3] - centre) + centre
        parts.append(np.column_stack([xyz, p[:, 3], np.full(len(p), i)]))
    allp = np.vstack(parts)
    np.savez_compressed(
        out / "merged.npz",
        x=allp[:, 0],
        y=allp[:, 1],
        z=allp[:, 2],
        intensity=allp[:, 3],
        drive=allp[:, 4].astype(np.uint16),
    )
    drives = [
        {
            "index": i,
            "scene": k,
            "date": meta[k]["date"],
            "n_points": len(clouds[k]),
            **res["info"][k],
            "correction": correction_summary(res["corrections"][k])
            if k in res["corrections"]
            else None,
        }
        for i, k in enumerate(names)
    ]
    qa = {
        "area": area["name"],
        "reference": res["reference"],
        "drives": drives,
        "ground_disagreement_pairs": res["pairs"],
        "skipped": skipped,
    }
    # DECISION: a minimal manifest.json so `twin eval <folder>` can read gate G2. The gate's metric is the
    # median over pairs of the after-registration ground P95; the worst pair is reported beside it.
    p95 = [p["after"]["p95_m"] for p in res["pairs"] if p["after"]]
    metrics = {
        "cross_drive_ground_p95_m": float(np.median(p95)) if p95 else None,
        "cross_drive_ground_p95_worst_m": max(p95) if p95 else None,
        "n_drives": len(names),
        "n_skipped": len(skipped),
    }
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": f"area-{area['name']}",
                "metrics": {"align": metrics},
                "stages": [],
            },
            indent=2,
        )
    )
    (out / "drives.json").write_text(json.dumps(drives, indent=2))
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return qa


def area_merge_command(name: str, store: Path | None) -> int:
    from twin.runner import default_store

    base = Path(store) if store else default_store()
    area = json.loads((base / "areas" / f"{name}.json").read_text())
    os.environ["NUSCENES_VERSION"] = area[
        "dataset_version"
    ]  # read by load when it opens the dataset
    out = base / "areas" / f"{name}-merged"
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    qa = merge_area(area, out, Params(), logging.getLogger("twin.merge"))
    print(json.dumps(qa, indent=2))
    return 0
