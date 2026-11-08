"""Stage 3 align: KISS-ICP on masked sweeps, anchored to the dataset x/y/yaw; or the dataset poses.

Source of truth: docs/design/twin-v1-spec.md, sections 4 and 6 (Align).
Method choice and KISS-ICP config: docs/research/kiss-icp-fit.md (KISS-ICP stays, see
docs/research/multi-sensor-sota.md section 1).
Input: mask's points.npz (run CRS, x, y, z, intensity, sweep) and load's poses.json
(dataset ego pose per sweep, run CRS). Output: poses.json (refined 4x4 per sweep), qa.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from kiss_icp.config import load_config
from kiss_icp.kiss_icp import KissICP

from twin.contracts import AlignParams, StageResult
from twin.registry import register

OUTPUT_FILES = ("poses.json", "qa.json")
POINT_FIELDS = ("x", "y", "z", "sweep")

# DECISION: KISS-ICP range and voxel settings from docs/research/kiss-icp-fit.md (starting point, tune on real data).
ICP_MAX_RANGE_M = 70.0
ICP_MIN_RANGE_M = 2.0  # research estimate, not verified
# DECISION: a sweep with fewer masked points than this is an ICP failure (falls back to dataset poses).
MIN_SWEEP_POINTS = 100
# DECISION: the operator's example threshold (task brief). The spec sets no value.
DRIFT_P95_MAX_M = 1.0
# DECISION: each pose contributes its position and a point this far ahead on its x axis, so yaw enters the 2D fit.
HEADING_LEVER_M = 1.0


class AlignFailure(RuntimeError):
    """ICP ran but its result is not usable."""


# ------------------------------------------------------------------ anchoring


def fit_rigid_2d(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray]:
    """Least-squares rigid 2D fit dst ~ R(yaw) @ src + t, no scale (Kabsch = Umeyama without scale).

    src, dst: (N, 2). Returns (yaw in radians, t of shape (2,)).
    """
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    u, _, vt = np.linalg.svd((src - mu_s).T @ (dst - mu_d))
    # DECISION: reflections are refused; the sign correction keeps R a proper rotation.
    d = 1.0 if np.linalg.det(vt.T @ u.T) >= 0 else -1.0
    rot = vt.T @ np.diag([1.0, d]) @ u.T
    t = mu_d - rot @ mu_s
    return float(np.arctan2(rot[1, 0], rot[0, 0])), t


def _planar_points(poses: np.ndarray) -> np.ndarray:
    """(2N, 2): each pose's position, then a point HEADING_LEVER_M ahead along its x axis."""
    pos = poses[:, :2, 3]
    ahead = pos + HEADING_LEVER_M * poses[:, :2, 0]
    return np.concatenate([pos, ahead])


def fit_anchor(icp: np.ndarray, ref: np.ndarray, z0: float = 0.0) -> np.ndarray:
    """4x4 rigid correction (yaw about z, x, y) that best maps the ICP poses onto the dataset x/y/yaw.

    icp, ref: (N, 4, 4). Z is set to z0 and pitch and roll stay zero: ICP keeps those relative to sweep 0.
    """
    yaw, t = fit_rigid_2d(_planar_points(icp), _planar_points(ref))
    c, s = np.cos(yaw), np.sin(yaw)
    a = np.eye(4)
    a[:2, :2] = [[c, -s], [s, c]]
    a[:2, 3] = t
    a[2, 3] = z0
    return a


def anchor(icp: np.ndarray, ref: np.ndarray, windows: np.ndarray) -> np.ndarray:
    """Fit one 2D correction per window and apply it to that window's ICP poses."""
    out = np.empty_like(icp)
    z0 = float(
        ref[0, 2, 3]
    )  # DECISION: z is the dataset height of sweep 0, plus ICP's relative z (no absolute height claim).
    for w in np.unique(windows):
        sel = windows == w
        out[sel] = fit_anchor(icp[sel], ref[sel], z0) @ icp[sel]
    return out


def window_ids(timestamps_us: list[int], window_s: float) -> np.ndarray:
    """Window index per sweep: sweeps in the same window_s-long slice share one correction."""
    t = (np.asarray(timestamps_us, dtype=float) - timestamps_us[0]) / 1e6
    return np.floor(t / window_s).astype(int)


def _yaw(poses: np.ndarray) -> np.ndarray:
    return np.arctan2(poses[:, 1, 0], poses[:, 0, 0])


def drift_stats(refined: np.ndarray, ref: np.ndarray) -> dict[str, float]:
    """x/y drift (distance) and yaw drift (degrees) of the refined poses against the dataset."""
    xy = np.linalg.norm(refined[:, :2, 3] - ref[:, :2, 3], axis=1)
    dyaw = np.abs(
        np.arctan2(np.sin(_yaw(refined) - _yaw(ref)), np.cos(_yaw(refined) - _yaw(ref)))
    )
    return {
        "xy_drift_p50_m": float(np.percentile(xy, 50)),
        "xy_drift_p95_m": float(np.percentile(xy, 95)),
        "yaw_drift_p95_deg": float(np.degrees(np.percentile(dyaw, 95))),
    }


# ------------------------------------------------------------------ KISS-ICP


def run_kiss_icp(sweeps: list[np.ndarray], voxel_m: float) -> np.ndarray:
    """KISS-ICP over sweeps in time order. Each sweep is (N, 3) in its own ego frame.

    Returns (n, 4, 4): pose k maps sweep k's frame into sweep 0's frame (pose 0 is identity).
    """
    cfg = load_config(None)
    cfg.data.deskew = False  # nuScenes has no per-point timestamps (spec section 6)
    cfg.data.max_range = ICP_MAX_RANGE_M
    cfg.data.min_range = ICP_MIN_RANGE_M
    cfg.mapping.voxel_size = voxel_m
    odo = KissICP(cfg)
    poses = np.empty((len(sweeps), 4, 4))
    for k, pts in enumerate(sweeps):
        odo.register_frame(pts, np.array([]))
        poses[k] = odo.last_pose
    return poses


def ego_sweeps(fields: dict[str, np.ndarray], ref: np.ndarray) -> list[np.ndarray]:
    """Split the masked points by sweep and move each sweep into its ego frame (inverse dataset pose).

    # DECISION: ego frame, not LIDAR_TOP sensor frame. The sensor extrinsic is not in run files; a fixed extrinsic does not change ICP's rigid motion.
    """
    n = len(ref)
    sweep = fields["sweep"].astype(np.int64)
    if sweep.size and sweep.max() >= n:
        raise ValueError(f"point sweep {sweep.max()} has no pose (poses.json has {n})")
    order = np.argsort(sweep, kind="stable")
    xyz = np.column_stack([fields["x"], fields["y"], fields["z"]])[order]
    bounds = np.concatenate([[0], np.cumsum(np.bincount(sweep, minlength=n))])
    out = []
    for k in range(n):
        inv = np.linalg.inv(ref[k])
        p = xyz[bounds[k] : bounds[k + 1]]
        out.append(p @ inv[:3, :3].T + inv[:3, 3])
    return out


# ------------------------------------------------------------------ stage


def _inputs(ctx: Any) -> tuple[dict, dict[str, np.ndarray]]:
    load = json.loads((ctx.input_dir("load") / "poses.json").read_text())
    with np.load(ctx.input_dir("mask") / "points.npz") as f:
        fields = {k: f[k] for k in POINT_FIELDS}
    return load, fields


def _write(
    out: Path, crs: str, entries: list[dict], poses: np.ndarray, qa: dict
) -> None:
    rows = [
        {**{k: v for k, v in e.items() if k != "matrix"}, "matrix": m.tolist()}
        for e, m in zip(entries, poses, strict=True)
    ]
    (out / "poses.json").write_text(json.dumps({"crs": crs, "poses": rows}))
    (out / "qa.json").write_text(json.dumps(qa, indent=2))


def _execute(ctx: Any, params: AlignParams, use_icp: bool) -> StageResult:
    out: Path = ctx.stage_dir("align")
    out.mkdir(exist_ok=True)
    load, fields = _inputs(ctx)
    entries = load["poses"]
    ref = np.array([e["matrix"] for e in entries], dtype=float).reshape(-1, 4, 4)
    stamps = [int(e["timestamp_us"]) for e in entries]

    if not use_icp:
        reason = "method dataset-poses: ICP not run"
        refined = ref
        drift = drift_stats(ref, ref)
    else:
        reason = None
        refined = ref
        drift: dict[str, float | None] = {
            "xy_drift_p50_m": None,
            "xy_drift_p95_m": None,
            "yaw_drift_p95_deg": None,
        }
        try:
            sweeps = ego_sweeps(fields, ref)
            short = [k for k, p in enumerate(sweeps) if len(p) < MIN_SWEEP_POINTS]
            if short:
                k = short[0]
                raise AlignFailure(
                    f"sweep {k} has {len(sweeps[k])} masked points, below {MIN_SWEEP_POINTS}"
                )
            icp = run_kiss_icp(sweeps, params.voxel_m)
            if not np.isfinite(icp).all():
                raise AlignFailure("ICP produced non-finite poses")
            anchored = anchor(icp, ref, window_ids(stamps, params.window_s))
            drift = drift_stats(anchored, ref)
            if drift["xy_drift_p95_m"] > DRIFT_P95_MAX_M:
                raise AlignFailure(
                    f"x/y drift P95 {drift['xy_drift_p95_m']:.2f} m above {DRIFT_P95_MAX_M} m"
                )
            refined = anchored
        except Exception as exc:  # noqa: BLE001 # DECISION: any ICP failure falls back to the dataset poses
            reason = f"{type(exc).__name__}: {exc}"
            refined = ref  # the poses written are the dataset poses; drift above is the failed ICP's

    fallback = reason is not None
    if fallback:
        ctx.log.warning("align falls back to dataset poses: %s", reason)
    qa = {
        "method": "dataset-poses" if not use_icp else "kiss-icp",
        "fallback_used": fallback,
        "fallback_reason": reason,
        **drift,
        "n_sweeps": len(entries),
    }
    _write(out, load["crs"], entries, refined, qa)
    return StageResult(
        status="ok",
        files=list(OUTPUT_FILES),
        metrics=qa,
        message=f"fallback to dataset poses: {reason}" if fallback else "",
    )


@register("align", "kiss-icp")
def run_icp(ctx: Any, params: AlignParams) -> StageResult:
    return _execute(ctx, params, use_icp=True)


@register("align", "dataset-poses")
def run_dataset(ctx: Any, params: AlignParams) -> StageResult:
    return _execute(ctx, params, use_icp=False)
