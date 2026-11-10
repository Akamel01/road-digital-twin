"""Per-sweep height, roll and pitch from a consensus ground surface (issue 177, ADR 0006 Q7).

Why: nuScenes ego z is 0 and KISS-ICP drifts in z, so sweeps (and, in an area, whole drives) sit at different
heights even where x, y and yaw agree. The method (fixed by the operator in ADR 0006 Q7):

  1. Build a consensus ground surface on a 0.5 m grid from the ground points of every sweep.
  2. Fit each sweep's z, roll and pitch to that surface by robust least squares.
  3. Rebuild the surface and repeat until the change is below a tolerance.

x, y and yaw are never touched. One function, `correct_heights`, serves both callers: align (the sweeps of one
drive) and the area merge (the sweeps of every registered drive at once).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from twin.parallel import pmap
from twin.stages.load import LIDARSEG_NONE

# ---- consensus surface
# DECISION: the grid is the operator's 0.5 m (issue 177).
CELL_M = 0.5
# DECISION: "robust low percentile": each sweep first reduces its ground points in a cell to their 20th
# percentile (leaked non-ground points, which are above the road, do not lift it); the surface is then the
# MEDIAN of those per-sweep values over the sweeps that see the cell (a sweep that is off by 0.3 m does not
# pull the median, so it is judged against the others, not against itself).
SWEEP_CELL_PCT = 20.0
# DECISION: a cell is part of the surface only if at least this many sweeps see it; with fewer, a sweep would be
# fitted to itself.
MIN_SWEEPS_PER_CELL = 3

# ---- ground points
# DECISION: only ground within this horizontal range of the ego origin is used. Far returns are sparse and
# noisy, and 25 m is still a lever of 25 m for pitch.
MAX_RANGE_M = 25.0
# DECISION: ground points are thinned to one per this voxel in the ego frame (keeps the fit small; the
# percentile and the median do not need every point).
THIN_VOXEL_M = 0.2
# lidarseg: flat.driveable_surface, flat.other, flat.sidewalk, flat.terrain are consecutive indices in
# nuScenes-lidarseg. DECISION: ground = driveable_surface, sidewalk and terrain (the operator's list), as offsets
# from load's driveable_index; flat.other (offset 1) is left out.
GROUND_LABEL_OFFSETS = (0, 2, 3)

# ---- fit
# DECISION: a sweep is fitted only with this many ground points in valid cells; fewer and it keeps its pose.
MIN_FIT_POINTS = 200
# DECISION: roll needs ground at least this wide (lateral spread), pitch this long, else that angle is not
# fitted (it would be a guess). z is always fitted.
MIN_SPAN_M = 4.0
# DECISION: Huber loss, scale from the median absolute residual (floor 0.01 m), eight reweighting passes.
HUBER_K = 1.345
SCALE_FLOOR_M = 0.01
IRLS_PASSES = 8
# DECISION: plausibility guard (coordinator, 2026-11-10). A sweep whose fit would exceed these is rejected: it
# keeps its input pose and is counted in the QA. A real vehicle does not tilt 2 degrees on a road, and a 0.5 m
# height step in the fit is more likely a different road layer than drift.
MAX_TILT_RAD = np.radians(2.0)
MAX_DZ_M = 0.5
# DECISION: stop when no sweep moves more than 1 mm in z or 0.01 degree in roll or pitch; 100 passes at most
# (low-frequency drift spreads along the drive by one overlap per pass).
MAX_ITER = 100
TOL_Z_M = 1e-3
TOL_ANGLE_RAD = np.radians(0.01)


# ------------------------------------------------------------------ ground points


def _ransac_job(k: int) -> np.ndarray:
    pts, seed = _JOB  # type: ignore[misc]  # dict: sweep -> thinned near points
    from twin.contracts import GroundParams
    from twin.stages import (
        ground,
    )  # lazy: ground imports align, which imports this module

    p = pts[k]
    if len(p) < ground.MIN_PLANE_POINTS:
        return np.zeros(0, bool)
    return ground.ransac_ground(p, GroundParams(), seed + k)


_JOB: tuple[dict[int, np.ndarray], int] | None = None  # read by forked workers


def ego_ground(
    egos: list[np.ndarray],
    labels: list[np.ndarray],
    driveable_index: int | None,
    seed: int = 0,
    workers: int | None = None,
) -> list[np.ndarray]:
    """Ground points per sweep, in the ego frame: (n_k, 3) arrays.

    egos[k]: sweep k's masked points in its ego frame. labels[k]: its lidarseg labels (LIDARSEG_NONE when the
    sweep has none). A labelled sweep keeps its driveable-surface, sidewalk and terrain points; any other sweep
    uses the seeded tiled-RANSAC ground of the ground stage, run in the ego frame, so it does not depend on
    the poses being fitted.
    """
    global _JOB
    out: list[np.ndarray | None] = [None] * len(egos)
    todo = []
    for k, p in enumerate(egos):
        lab = labels[k]
        if driveable_index is not None and (lab != LIDARSEG_NONE).any():
            keep = np.hypot(p[:, 0], p[:, 1]) <= MAX_RANGE_M
            ok = keep & np.isin(
                lab, [driveable_index + o for o in GROUND_LABEL_OFFSETS]
            )
            out[k] = _thin(p[ok])
        else:
            todo.append(k)
    near = {k: _thin_near(egos[k]) for k in todo}
    _JOB = (near, seed)  # type: ignore[assignment]
    try:
        masks = pmap(_ransac_job, todo, workers)
    finally:
        _JOB = None
    for k, m in zip(todo, masks, strict=True):
        out[k] = near[k][m] if len(m) else near[k][:0]
    return out  # type: ignore[return-value]


def _thin(p: np.ndarray) -> np.ndarray:
    return p[np.sort(_voxel_first(p, THIN_VOXEL_M))] if len(p) else p


def _thin_near(p: np.ndarray) -> np.ndarray:
    return _thin(p[np.hypot(p[:, 0], p[:, 1]) <= MAX_RANGE_M])


def _voxel_first(xyz: np.ndarray, voxel_m: float) -> np.ndarray:
    ijk = np.floor(xyz / voxel_m).astype(np.int64)
    ijk -= ijk.min(axis=0)
    dims = tuple(int(d) for d in ijk.max(axis=0) + 1)
    _, first = np.unique(np.ravel_multi_index(ijk.T, dims), return_index=True)
    return first


def label_ground(
    labels: np.ndarray, driveable_index: int | None
) -> tuple[np.ndarray, np.ndarray]:
    """(labelled, is_ground) per point from lidarseg labels: driveable surface, sidewalk and terrain are ground."""
    if driveable_index is None:
        return np.zeros(len(labels), bool), np.zeros(len(labels), bool)
    return labels != LIDARSEG_NONE, np.isin(
        labels, [driveable_index + o for o in GROUND_LABEL_OFFSETS]
    )


# ------------------------------------------------------------------ the correction


def _huber_fit(design: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Robust least squares of design @ beta ~ target (Huber, reweighted). Deterministic."""
    beta = np.linalg.lstsq(design, target, rcond=None)[0]
    for _ in range(IRLS_PASSES):
        r = target - design @ beta
        scale = max(1.4826 * float(np.median(np.abs(r))), SCALE_FLOOR_M)
        w = np.minimum(1.0, HUBER_K * scale / np.maximum(np.abs(r), 1e-12))
        sw = np.sqrt(w)
        beta = np.linalg.lstsq(design * sw[:, None], target * sw, rcond=None)[0]
    return beta


def _group_pick(
    sorted_vals: np.ndarray, start: np.ndarray, count: np.ndarray, q: float
) -> np.ndarray:
    """Value at fraction q of each group of an already group-wise sorted array (lower index, no interpolation)."""
    return sorted_vals[start + np.floor(q * (count - 1)).astype(np.int64)]


def correct_heights(
    poses: np.ndarray, ground: list[np.ndarray]
) -> tuple[np.ndarray, dict]:
    """Fit every sweep's z, roll and pitch to a consensus ground surface. Returns (poses, report).

    poses: (S, 4, 4) sweep poses, ego frame -> map. ground[k]: sweep k's ground points in its ego frame (n_k, 3).
    Only z, roll and pitch change: the returned pose keeps x, y and yaw (to the 1e-6 rounding of the angles).
    A sweep with too little ground, or one whose fit breaks the plausibility guard, keeps its pose: `report["fitted"][k]` is False and `report["rejected"][k]` says which.
    The mean of the corrections over fitted sweeps is zero, so the group's overall height and tilt stay as given.

    report: arrays dz_m, roll_rad, pitch_rad, fitted, n_points, residual_before_m, residual_after_m (median
    absolute residual to the surface, per sweep), plus iterations and converged.
    """
    s_n = len(poses)
    counts = np.array([len(g) for g in ground], dtype=np.int64)
    p = np.vstack(ground) if counts.sum() else np.zeros((0, 3))
    sweep = np.repeat(np.arange(s_n), counts)
    bounds = np.concatenate([[0], np.cumsum(counts)])
    rot, trans = poses[:, :3, :3], poses[:, :3, 3]
    # map-frame x, y and z of every ground point at the given poses. x and y are used once, to assign cells.
    wx = np.einsum("nj,nj->n", rot[sweep, 0, :], p) + trans[sweep, 0]
    wy = np.einsum("nj,nj->n", rot[sweep, 1, :], p) + trans[sweep, 1]
    z0 = np.einsum("nj,nj->n", rot[sweep, 2, :], p) + trans[sweep, 2]
    u, v = p[:, 0], p[:, 1]

    ij = np.floor(np.column_stack([wx, wy]) / CELL_M).astype(np.int64)
    ij -= ij.min(axis=0) if len(ij) else 0
    dims = tuple(int(d) for d in ij.max(axis=0) + 1) if len(ij) else (1, 1)
    cell_key = np.ravel_multi_index(ij.T, dims) if len(ij) else np.zeros(0, np.int64)
    _, cell = np.unique(cell_key, return_inverse=True)
    n_cell = int(cell.max()) + 1 if len(cell) else 0
    # group = (cell, sweep), numbered cell-major so the groups of one cell are contiguous
    _, group = np.unique(cell.astype(np.int64) * s_n + sweep, return_inverse=True)
    g_count = np.bincount(group)
    g_start = np.cumsum(g_count) - g_count
    g_cell = np.zeros(len(g_count), np.int64)
    g_cell[group] = cell
    c_count = np.bincount(g_cell, minlength=n_cell)
    c_start = np.cumsum(c_count) - c_count
    cell_ok = c_count >= MIN_SWEEPS_PER_CELL

    dz = np.zeros(s_n)
    a = np.zeros(
        s_n
    )  # z' = z + dz + a * u + b * v (small angles); pitch = -a, roll = b
    b = np.zeros(s_n)
    fitted = np.zeros(s_n, bool)
    rejected = np.zeros(s_n, bool)
    res_before = np.full(s_n, np.nan)

    def surface(z: np.ndarray) -> np.ndarray:
        order = np.lexsort((z, group))
        g_val = _group_pick(z[order], g_start, g_count, SWEEP_CELL_PCT / 100.0)
        o2 = np.lexsort((g_val, g_cell))
        sv = g_val[o2]
        lo = sv[c_start + (c_count - 1) // 2]
        hi = sv[c_start + c_count // 2]
        return 0.5 * (lo + hi)

    iterations, converged, last_z, last_angle = 0, False, 0.0, 0.0
    for it in range(MAX_ITER):
        iterations = it + 1
        z = z0 + dz[sweep] + a[sweep] * u + b[sweep] * v
        surf = surface(z)
        resid = surf[cell] - z
        usable = cell_ok[cell]
        step_dz, step_a, step_b = np.zeros(s_n), np.zeros(s_n), np.zeros(s_n)
        for k in range(s_n):
            sl = slice(bounds[k], bounds[k + 1])
            sel = usable[sl]
            if it == 0 and sel.any():
                res_before[k] = float(np.median(np.abs(resid[sl][sel])))
            if rejected[k] or sel.sum() < MIN_FIT_POINTS:
                continue
            uk, vk, rk = u[sl][sel], v[sl][sel], resid[sl][sel]
            cols = [np.ones_like(uk)]
            use_pitch = np.ptp(uk) >= MIN_SPAN_M
            use_roll = np.ptp(vk) >= MIN_SPAN_M
            if use_pitch:
                cols.append(uk)
            if use_roll:
                cols.append(vk)
            beta = _huber_fit(np.column_stack(cols), rk)
            fitted[k] = True
            step_dz[k] = beta[0]
            i = 1
            if use_pitch:
                step_a[k] = beta[i]
                i += 1
            if use_roll:
                step_b[k] = beta[i]
        dz, a, b = dz + step_dz, a + step_a, b + step_b
        # the guard: a sweep over a bound goes back to its input pose for good, and stops being fitted
        bad = (
            fitted
            & ~rejected
            & (
                (np.abs(dz) > MAX_DZ_M)
                | (np.abs(a) > MAX_TILT_RAD)
                | (np.abs(b) > MAX_TILT_RAD)
            )
        )
        rejected |= bad
        fitted &= ~bad
        dz[bad], a[bad], b[bad] = 0.0, 0.0, 0.0
        # DECISION: gauge. The surface fixes heights only relative to the sweeps themselves, so the mean correction
        # over fitted sweeps is removed: the group keeps the overall height and tilt it came with.
        if fitted.any():
            dz[fitted] -= dz[fitted].mean()
            a[fitted] -= a[fitted].mean()
            b[fitted] -= b[fitted].mean()
        if (
            np.abs(step_dz).max() < TOL_Z_M
            and max(np.abs(step_a).max(), np.abs(step_b).max()) < TOL_ANGLE_RAD
        ):
            converged = True
            break

    # DECISION: rounded to a micrometre and a micro-radian so reruns are bit-identical (as align does for ICP).
    dz, pitch, roll = np.round(dz, 6), np.round(-a, 6), np.round(b, 6)
    new = poses.copy()
    for k in np.flatnonzero(fitted):
        cp, sp, cr, sr = (
            np.cos(pitch[k]),
            np.sin(pitch[k]),
            np.cos(roll[k]),
            np.sin(roll[k]),
        )
        ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
        rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
        new[k, :3, :3] = poses[k, :3, :3] @ ry @ rx
        new[k, 2, 3] = poses[k, 2, 3] + dz[k]
    # residual of the final poses against the surface rebuilt from them
    z = np.einsum("nj,nj->n", new[sweep, 2, :3], p) + new[sweep, 2, 3]
    resid = surface(z)[cell] - z
    res_after = np.full(s_n, np.nan)
    for k in range(s_n):
        sel = cell_ok[cell[bounds[k] : bounds[k + 1]]]
        if sel.any():
            res_after[k] = float(
                np.median(np.abs(resid[bounds[k] : bounds[k + 1]][sel]))
            )
    return new, {
        "dz_m": dz,
        "roll_rad": roll,
        "pitch_rad": pitch,
        "fitted": fitted,
        "rejected": rejected,
        "n_points": counts,
        "residual_before_m": res_before,
        "residual_after_m": res_after,
        "iterations": iterations,
        "converged": converged,
        "last_step_z_m": last_z,
        "last_step_angle_deg": float(np.degrees(last_angle)),
    }


def summary(report: dict) -> dict:
    """Short QA numbers for qa.json: how big the corrections were and how well the sweeps agree afterwards."""
    f = report["fitted"]

    def p95(x: np.ndarray) -> float | None:
        x = x[np.isfinite(x)]
        return float(np.percentile(x, 95)) if x.size else None

    return {
        "n_sweeps": len(f),
        "n_fitted": int(f.sum()),
        "n_rejected": int(report["rejected"].sum()),
        "iterations": int(report["iterations"]),
        "converged": bool(report["converged"]),
        "last_step_z_m": report["last_step_z_m"],
        "last_step_angle_deg": report["last_step_angle_deg"],
        "dz_p95_abs_m": p95(np.abs(report["dz_m"][f])),
        "roll_p95_abs_deg": p95(np.degrees(np.abs(report["roll_rad"][f]))),
        "pitch_p95_abs_deg": p95(np.degrees(np.abs(report["pitch_rad"][f]))),
        "residual_before_p95_m": p95(report["residual_before_m"][f]),
        "residual_after_p95_m": p95(report["residual_after_m"][f]),
    }


def sweep_rows(report: dict, stamps_us: list[int] | None = None) -> list[dict]:
    """One QA row per sweep: the correction applied and the residual to the surface before and after."""
    rows = []
    for k in range(len(report["fitted"])):
        row = {
            "sweep": k,
            "fitted": bool(report["fitted"][k]),
            "rejected": bool(report["rejected"][k]),
            "dz_m": float(report["dz_m"][k]),
            "roll_deg": float(np.degrees(report["roll_rad"][k])),
            "pitch_deg": float(np.degrees(report["pitch_rad"][k])),
            "n_points": int(report["n_points"][k]),
            "residual_before_m": _num(report["residual_before_m"][k]),
            "residual_after_m": _num(report["residual_after_m"][k]),
        }
        if stamps_us is not None:
            row["timestamp_us"] = int(stamps_us[k])
        rows.append(row)
    return rows


def _num(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


# ------------------------------------------------------------------ CAN-bus IMU check


def _roll_pitch(q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Roll and pitch (radians) of unit quaternions (w, x, y, z), z-y-x convention."""
    w, x, y, z = q.T
    roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2 * (w * y - z * x), -1, 1))
    return roll, pitch


def imu_check(
    scene_token: str,
    stamps_us: list[int],
    roll_rad: np.ndarray,
    pitch_rad: np.ndarray,
    fitted: np.ndarray,
) -> dict:
    """Compare the fitted roll and pitch with the CAN-bus IMU's. Reported only, never applied.

    The IMU gives absolute tilt, the fit gives tilt relative to the group mean, so both are centred on their own
    mean over the fitted sweeps. Reports the P95 of the difference (degrees) and the correlation. Best effort:
    when the files are missing the result says why.
    """
    try:
        root = Path(os.environ.get("NUSCENES_ROOT", "/data/nuscenes"))
        version = os.environ.get("NUSCENES_VERSION", "v1.0-mini")
        scenes = json.loads((root / version / "scene.json").read_text())
        name = next(s["name"] for s in scenes if s["token"] == scene_token)
        imu = json.loads((root / "can_bus" / f"{name}_ms_imu.json").read_text())
    except Exception as exc:  # noqa: BLE001 # DECISION: the check is optional; a missing file is a reason, not an error
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    t = np.array([r["utime"] for r in imu], dtype=float)
    q = np.array([r["q"] for r in imu], dtype=float)
    order = np.argsort(t)
    t, q = t[order], q[order]
    r_imu, p_imu = _roll_pitch(q)
    st = np.asarray(stamps_us, dtype=float)
    inside = fitted & (st >= t[0]) & (st <= t[-1])
    if inside.sum() < 10:
        return {
            "available": False,
            "reason": "fewer than 10 fitted sweeps inside the IMU time span",
        }
    out: dict = {"available": True, "scene": name, "n_sweeps": int(inside.sum())}
    for label, ours, theirs in (("roll", roll_rad, r_imu), ("pitch", pitch_rad, p_imu)):
        o = ours[inside] - ours[inside].mean()
        i = np.interp(st[inside], t, np.unwrap(theirs))
        i = i - i.mean()
        out[f"{label}_diff_p95_deg"] = float(
            np.degrees(np.percentile(np.abs(o - i), 95))
        )
        out[f"{label}_imu_std_deg"] = float(np.degrees(i.std()))
        out[f"{label}_fit_std_deg"] = float(np.degrees(o.std()))
        out[f"{label}_corr"] = (
            float(np.corrcoef(o, i)[0, 1]) if o.std() > 0 and i.std() > 0 else None
        )
    return out
