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

from twin import heights
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
# DECISION (#190): after ICP the drives still differ by a height offset and a tilt along the drive (diagnosis in the
# PR), so each drive gets a height plane fitted to all pairs at once. The scale and iterations are for the
# per-pair robust fit (layer mix-ups and car tops are outliers).
PLANE_SCALE_M = 0.15
PLANE_ITER = 10
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


def plane_fit(xy: np.ndarray, dz: np.ndarray) -> np.ndarray:
    """Robust (IRLS, weight 1 within PLANE_SCALE_M then falling as 1/r^2) fit of dz = a + bx*x + by*y. Returns (a, bx, by). xy is centred on the polygon."""
    A = np.column_stack([np.ones(len(dz)), xy])
    w = np.ones(len(dz))
    for _ in range(PLANE_ITER):
        sw = np.sqrt(w)
        coef = np.linalg.lstsq(A * sw[:, None], dz * sw, rcond=None)[0]
        r = np.abs(dz - A @ coef)
        w = np.minimum(1.0, (PLANE_SCALE_M / np.maximum(r, 1e-9)) ** 2)
    return coef


def fit_zplanes(cells: dict[str, dict], ref: str) -> dict[str, np.ndarray]:
    """Per-drive height plane z += a + bx*x + by*y (x, y from the polygon centre) that makes all drives' ground agree.

    Every pair with enough shared cells gives a robust plane difference; one linear least squares over all pairs
    (weighted by cells shared, ref held at zero) then spreads the disagreement over the drives instead of
    pinning everything to the reference. Drives with no pair stay at zero.
    """
    ids = sorted(cells)
    col = {k: i for i, k in enumerate(k for k in ids if k != ref)}
    rows, rhs = [], []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            keys = sorted(cells[a].keys() & cells[b].keys())
            if len(keys) < MIN_CELLS:
                continue
            xy = np.array(keys, float) * CELL_M
            d = plane_fit(xy, np.array([cells[a][k] - cells[b][k] for k in keys]))
            w = np.sqrt(len(keys))
            for j in range(3):
                row = np.zeros(3 * len(col))
                for k, sign in ((a, 1.0), (b, -1.0)):
                    if k in col:
                        row[3 * col[k] + j] = sign * w
                rows.append(row)
                rhs.append(d[j] * w)
    out = {k: np.zeros(3) for k in ids}
    if rows:
        sol = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
        for k, i in col.items():
            out[k] = -sol[3 * i : 3 * i + 3]
    return out


def apply_zplane(xyz: np.ndarray, plane: np.ndarray) -> np.ndarray:
    """xyz centred on the polygon; adds the drive's height plane to z."""
    out = xyz.copy()
    out[:, 2] += plane[0] + xyz[:, :2] @ plane[1:]
    return out


def thin(xyz: np.ndarray, voxel: float) -> np.ndarray:
    return xyz[np.sort(ground.voxel_first(xyz, voxel))]


def register_drives(
    clouds: dict[str, np.ndarray],
    centre: np.ndarray,
    seed: int = 0,
    ground: dict[str, np.ndarray] | None = None,
) -> dict:
    """Register drives to a growing reference. clouds: drive id -> (N, 3) in the map frame.

    The reference is the drive with the most points. Then, repeatedly, the unregistered drive with
    the most overlap with the registered cloud is aligned to it. Returns per-drive corrections
    (4x4, in the frame centred on `centre`), a height plane per drive (zplanes: a, bx, by), a note per drive, and the
    ground disagreement per pair before, after ICP (registered) and after the planes (after). `ground` (drive id -> (N, 3), same frame) are the drives' ground-class points; the
    ground disagreement is measured on them (2026-11-10 amendment to ADR 0005), or on `clouds` when absent.
    """
    o3d.utility.random.seed(seed)
    pts = {k: thin(v - centre, ICP_VOXEL_M) for k, v in clouds.items()}
    gnd = {k: v - centre for k, v in (ground or clouds).items()}
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
    registered = {k: ground_cells(apply(corr.get(k, eye), gnd[k])) for k in ids}
    # DECISION (#190): ICP leaves each drive with a height offset and tilt; fit one plane per drive over all pairs.
    # Only registered drives take part (an unregistered drive's overlap is unknown); the reference stays at zero.
    zplane = {k: np.zeros(3) for k in ids}
    zplane.update(fit_zplanes({k: registered[k] for k in corr}, ref))
    after = {
        k: {
            c: z + zplane[k][0] + CELL_M * (c[0] * zplane[k][1] + c[1] * zplane[k][2])
            for c, z in registered[k].items()
        }
        for k in ids
    }
    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            row = {
                "a": a,
                "b": b,
                "before": ground_disagreement(before[a], before[b]),
                "registered": ground_disagreement(registered[a], registered[b]),
                "after": ground_disagreement(after[a], after[b]),
            }
            if row["before"] or row["registered"] or row["after"]:
                pairs.append(row)
    return {
        "reference": ref,
        "corrections": corr,
        "zplanes": zplane,
        "info": info,
        "pairs": pairs,
    }


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


# ------------------------------------------------------------------ heights across drives


def drive_ground(work: Path, polygon) -> tuple[np.ndarray, list[np.ndarray]] | None:
    """A drive's align poses (S, 4, 4) and its ground points per sweep in the ego frame (saved by align), clipped
    to the polygon (by their position at the align poses). None when the drive has no ground file."""
    f = work / "3_align" / "ground_ego.npz"
    if not f.is_file():
        return None
    poses = _poses(work / "3_align")
    with np.load(f) as z:
        xyz = np.column_stack([z["x"], z["y"], z["z"]])
        sweep = z["sweep"].astype(np.int64)
    bounds = np.concatenate([[0], np.cumsum(np.bincount(sweep, minlength=len(poses)))])
    ego = [xyz[bounds[k] : bounds[k + 1]] for k in range(len(poses))]
    for k in range(len(poses)):
        w = apply(poses[k], ego[k])
        ego[k] = ego[k][shapely.contains_xy(polygon, w[:, 0], w[:, 1])]
    return poses, ego


def world_ground(poses: np.ndarray, ego: list[np.ndarray]) -> np.ndarray:
    """(N, 4): x, y, z in the map frame and the sweep index, of a drive's ground points."""
    return np.vstack(
        [
            np.column_stack([apply(poses[k], g), np.full(len(g), k)])
            for k, g in enumerate(ego)
        ]
    )


def about(t: np.ndarray, centre: np.ndarray) -> np.ndarray:
    """The 4x4 that applies t in the frame centred on `centre`, as a map-frame transform."""
    shift = np.eye(4)
    shift[:3, 3] = centre
    back = np.eye(4)
    back[:3, 3] = -centre
    return shift @ t @ back


def fit_heights(
    drives: dict[str, tuple[np.ndarray, list[np.ndarray]]],
    corr: dict[str, np.ndarray],
    centre: np.ndarray,
) -> tuple[dict[str, np.ndarray], dict]:
    """Per-sweep z, roll and pitch of all registered drives against one consensus ground (heights.correct_heights).

    drives: drive -> (align poses, ground points per sweep in the ego frame), from drive_ground. Returns, per
    drive, the (S, 4, 4) map-frame transform that takes a sweep's points from where the registration left them to
    where the height fit puts them, and the QA.
    DECISION: only registered drives enter; an unregistered drive's height is unknown, so it is left alone.
    """
    poses, ground, owner = [], [], []
    names = [n for n in sorted(drives) if n in corr]
    for name in names:
        p, g = drives[name]
        p = about(corr[name], centre) @ p
        poses.append(p)
        ground += g
        owner += [(name, k) for k in range(len(p))]
    allp = np.concatenate(poses)
    new, rep = heights.correct_heights(allp, ground)
    delta = new @ np.linalg.inv(allp)
    out, i = {}, 0
    for name, p in zip(names, poses, strict=True):
        out[name] = delta[i : i + len(p)]
        i += len(p)
    rows = heights.sweep_rows(rep)
    for row, (name, k) in zip(rows, owner, strict=True):
        row["scene"], row["sweep"] = name, k
    return out, {"summary": heights.summary(rep), "sweeps": rows}


def move_sweeps(p: np.ndarray, delta: np.ndarray) -> np.ndarray:
    """Apply delta[k] (map frame) to the points of sweep k. p: (N, 5+) with the sweep index in column 4."""
    xyz = p[:, :3].copy()
    sweep = p[:, 4].astype(np.int64)
    for k in np.unique(sweep):
        sel = sweep == k
        xyz[sel] = apply(delta[k], xyz[sel])
    return xyz


# ------------------------------------------------------------------ command


def merge_area(area: dict, out: Path, params: Params, log) -> dict:
    version = area["dataset_version"]
    old = out / "manifest.json"
    if old.is_file():  # DECISION: a folder built from another dataset version is refused (its cached drives would mix)
        had = json.loads(old.read_text()).get("data", {}).get("nuscenes_version")
        if had is not None and had != version:
            raise ValueError(
                f"dataset version {version!r} differs from the earlier merge's {had!r}"
            )
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
    names = sorted(clouds)
    # DECISION (2026-11-10 amendment to ADR 0005): the cross-drive ground disagreement is measured on ground-class
    # points (align's ground_ego.npz: lidarseg labels where a sweep has them, else RANSAC), not on every point.
    # A drive without that file falls back to all its points.
    found = {k: drive_ground(out / "drives" / k, polygon) for k in names}
    gworld = {k: world_ground(*found[k]) for k in names if found[k] is not None}
    ground_pts = {
        k: gworld[k][:, :3] if k in gworld else clouds[k][:, :3] for k in names
    }
    res = register_drives(
        {k: v[:, :3] for k, v in clouds.items()}, centre, params.seed, ground_pts
    )
    # DECISION: heights are fitted across drives only when merge.heights is set (off by default). They come after
    # the drive registration (it gives the drives' overall dz) and move only z, roll and pitch of each sweep; x, y
    # and yaw stay as align and the registration gave them.
    deltas, hqa = {}, None
    if params.merge.heights:
        deltas, hqa = fit_heights(
            {k: found[k] for k in names if found[k] is not None},
            res["corrections"],
            centre,
        )
    parts = []
    for i, k in enumerate(names):
        p = clouds[k]
        xyz = apply(res["corrections"].get(k, np.eye(4)), p[:, :3] - centre)
        xyz = apply_zplane(xyz, res["zplanes"][k]) + centre
        if k in deltas:
            xyz = move_sweeps(np.column_stack([xyz, p[:, 3:]]), deltas[k])
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
    if params.merge.heights:
        # the pair table: "after" is the planes plus the height fit; "registered" stays ICP alone
        cells = {}
        for k in names:
            g = apply(res["corrections"].get(k, np.eye(4)), ground_pts[k] - centre)
            g = apply_zplane(g, res["zplanes"][k]) + centre
            if k in deltas and k in gworld:
                g = move_sweeps(
                    np.column_stack([g, g[:, 0], gworld[k][:, 3]]), deltas[k]
                )
            cells[k] = ground_cells(g)
        for row in res["pairs"]:
            row["after"] = ground_disagreement(cells[row["a"]], cells[row["b"]])
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
            "z_plane": dict(
                zip(("a_m", "bx", "by"), map(float, res["zplanes"][k]), strict=True)
            ),
        }
        for i, k in enumerate(names)
    ]
    qa = {
        "area": area["name"],
        "reference": res["reference"],
        "drives": drives,
        "ground_disagreement_pairs": res["pairs"],
        "heights": hqa["summary"] if hqa else None,
        "skipped": skipped,
    }
    # DECISION: a minimal manifest.json so `twin eval <folder>` can read gate G2. The gate's metric is the
    # median over pairs of the after-registration ground P95; the worst pair is reported beside it.
    p95 = [p["after"]["p95_m"] for p in res["pairs"] if p["after"]]
    reg = [p["registered"]["p95_m"] for p in res["pairs"] if p.get("registered")]
    metrics = {
        "cross_drive_ground_p95_m": float(np.median(p95)) if p95 else None,
        "cross_drive_ground_p95_worst_m": max(p95) if p95 else None,
        "cross_drive_ground_p95_registered_m": float(np.median(reg)) if reg else None,
        "n_drives": len(names),
        "n_skipped": len(skipped),
    }
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": f"area-{area['name']}",
                "data": {"nuscenes_version": version},
                "metrics": {"align": metrics},
                "stages": [],
            },
            indent=2,
        )
    )
    (out / "drives.json").write_text(json.dumps(drives, indent=2))
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    if hqa:
        (out / "heights.json").write_text(json.dumps(hqa["sweeps"]))
    return qa


def area_merge_command(name: str, store: Path | None, heights_on: bool = False) -> int:
    from twin.runner import default_store

    base = Path(store) if store else default_store()
    area = json.loads((base / "areas" / f"{name}.json").read_text())
    os.environ["NUSCENES_VERSION"] = area[
        "dataset_version"
    ]  # read by load when it opens the dataset
    out = base / "areas" / f"{name}-merged"
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    params = Params(merge={"heights": heights_on})
    qa = merge_area(area, out, params, logging.getLogger("twin.merge"))
    print(json.dumps(qa, indent=2))
    return 0
