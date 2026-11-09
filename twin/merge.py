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

from twin.contracts import GroundParams, Params
from twin.stages import align, ground, load, mask

# DECISION: registration works on points thinned to one per 0.3 m voxel; the ground split uses 0.2 m.
ICP_VOXEL_M = 0.3
GROUND_VOXEL_M = 0.2
# DECISION: coarse-to-fine ICP, three correspondence distances. Dataset poses start within a few metres.
ICP_STEPS_M = (2.0, 1.0, 0.5)
ICP_MAX_ITER = 50
NORMAL_RADIUS_M = 1.0
# DECISION: a drive is registered only if enough of it lies within OVERLAP_DIST_M of the cloud so far
# and the final ICP fitness is at least MIN_FITNESS. Otherwise it stays at its dataset pose, flagged.
OVERLAP_DIST_M = 1.0
MIN_OVERLAP_POINTS = 500
MIN_FITNESS = 0.2
# A ground point of one drive is compared when the other drive has ground within this distance.
PAIR_DIST_M = 0.5


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
    for dist in ICP_STEPS_M:
        res = o3d.pipelines.registration.registration_icp(s, t, dist, cur, est, crit)
        cur = yaw_translation(np.asarray(res.transformation))
    final = o3d.pipelines.registration.evaluate_registration(s, t, ICP_STEPS_M[-1], cur)
    return cur, float(final.fitness), float(final.inlier_rmse)


def ground_disagreement(a: np.ndarray, b: np.ndarray) -> dict | None:
    """P50/P95 of the point-to-plane distance from a's ground points to b's ground, where b has ground within PAIR_DIST_M."""
    if len(a) == 0 or len(b) == 0:
        return None
    idx, d = nearest(a, b)
    ok = d <= PAIR_DIST_M
    if ok.sum() < MIN_OVERLAP_POINTS:
        return None
    normals = np.asarray(_pcd(b, normals=True).normals)[idx[ok]]
    dist = np.abs(np.einsum("ij,ij->i", a[ok] - b[idx[ok]], normals))
    return {
        "n_points": int(ok.sum()),
        "p50_m": float(np.percentile(dist, 50)),
        "p95_m": float(np.percentile(dist, 95)),
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
    gnd = {}
    for k, v in clouds.items():
        g = thin(v - centre, GROUND_VOXEL_M)
        gnd[k] = g[ground.ransac_ground(g, GroundParams())]
    ids = sorted(clouds)
    ref = max(ids, key=lambda k: (len(clouds[k]), k))
    corr = {ref: np.eye(4)}
    info = {ref: {"role": "reference"}}
    target = pts[ref]
    todo = [k for k in ids if k != ref]
    while todo:
        overlap = {
            k: int((nearest(pts[k], target)[1] <= OVERLAP_DIST_M).sum()) for k in todo
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
    pairs = []
    eye = np.eye(4)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            row = {
                "a": a,
                "b": b,
                "before": ground_disagreement(gnd[a], gnd[b]),
                "after": ground_disagreement(
                    apply(corr.get(a, eye), gnd[a]), apply(corr.get(b, eye), gnd[b])
                ),
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
    (out / "drives.json").write_text(json.dumps(drives, indent=2))
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return qa


def area_merge_command(name: str, store: Path | None) -> int:
    from twin.runner import default_store

    base = Path(store) if store else default_store()
    area = json.loads((base / "areas" / f"{name}.json").read_text())
    os.environ["NUSCENES_VERSION"] = area["dataset_version"]  # read by load at import
    out = base / "areas" / f"{name}-merged"
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    qa = merge_area(area, out, Params(), logging.getLogger("twin.merge"))
    print(json.dumps(qa, indent=2))
    return 0
