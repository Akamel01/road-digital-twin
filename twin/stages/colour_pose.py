"""Per-frame camera pose refinement against lidar paint, for the colour stage's zbuffer-pose-refine method. CPU only.

Anchors are points sampled along the observed lidar markings (paint stripe centre lines), with the marking index
in column 3. For one camera frame, refine_one:
  1. keeps the anchors the frame can see (zbuffer.visible, once, at the calibrated pose);
  2. measures, for each anchor, where the painted stripe centre sits in the image along the normal of the
     projected marking (colour._cross_section_offset on a cross-section sampled in pixels). That gives an
     observed image point q and a unit normal n per anchor;
  3. solves the 6-DOF correction delta (rotation vector rad, translation m, camera frame, c2w' = c2w @ T(delta))
     that minimises soft_l1(n . (project(anchor) - q)) in pixels, plus a weak prior towards the calibrated pose;
  4. repeats 2 and 3 (the measurement moves with the pose), like ICP.
The correction is applied only when it lowers the median stripe offset, keeps enough inliers and stays inside
the pose_max_deg / pose_max_m bound.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.ndimage import map_coordinates
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from twin.sightline import Surface
from twin.stages import colour, profile, zbuffer

# DECISION: image cross-sections reach this far (m, at the anchor's depth) either side of the projected lidar line.
# Wider than colour.EDGE_SEARCH_M so a 0.5 m crosswalk bar that is 0.2 m off still has both edges inside.
SEARCH_M = 0.8
# DECISION: ICP-style rounds of measure-then-solve per frame.
ROUNDS = 4
# DECISION: soft_l1 scale (px): residuals beyond about this count linearly, not quadratically.
LOSS_PX = 1.5
# DECISION: an anchor is an outlier when its residual exceeds max(OUTLIER_PX, 3 x 1.4826 x MAD) (px).
OUTLIER_PX = 2.0
# DECISION: prior weight (px) on delta / bound: a correction at the bound costs as much as one anchor this far off.
PRIOR_PX = 1.0


def lidar_paint_edges(markings: Any, ground_surface: Surface | None, points_3d: Any = None, step_m: float | None = None) -> np.ndarray:
    """(N, 4) anchors: x, y, z and marking index, every step_m along each observed marking.

    z comes from the marking's own 3D coordinates; 2D markings take it from ground_surface, then from the nearest of points_3d. Markings with fewer than colour.EDGE_MIN_SAMPLES anchors are dropped.
    """
    step_m = colour.EDGE_STEP_M if step_m is None else step_m
    pts = None if points_3d is None or len(points_3d) == 0 else np.asarray(points_3d, float)
    out = []
    for li, feat in enumerate(markings or []):
        if feat.get("properties", {}).get("reliability") != "observed":
            continue
        xyz = np.asarray(feat["geometry"]["coordinates"], float)
        if len(xyz) < 2:
            continue
        seg = np.hypot(*np.diff(xyz[:, :2], axis=0).T)
        s_vert = np.concatenate([[0.0], np.cumsum(seg)])
        s = np.append(np.arange(0.0, s_vert[-1], step_m), s_vert[-1])
        x, y = np.interp(s, s_vert, xyz[:, 0]), np.interp(s, s_vert, xyz[:, 1])
        if xyz.shape[1] >= 3:
            z = np.interp(s, s_vert, xyz[:, 2])
        else:
            z = np.array([_ground_z(ground_surface, pts, a, b) for a, b in zip(x, y, strict=True)], float)
        ok = np.isfinite(z)
        if ok.sum() >= colour.EDGE_MIN_SAMPLES:
            out.append(np.column_stack([x[ok], y[ok], z[ok], np.full(ok.sum(), float(li))]))
    return np.vstack(out) if out else np.zeros((0, 3), float)


def _ground_z(surf: Surface | None, pts: np.ndarray | None, x: float, y: float) -> float:
    hit = profile.ground_z_at(surf, x, y) if surf is not None else None
    if hit is not None:
        return float(hit[0])
    if pts is not None:
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        i = int(np.argmin(d))
        if d[i] <= 2.0:
            return float(pts[i, 2])
    return np.nan


def _tangents(anchors: Any, labels: Any = None) -> np.ndarray:
    """(N, 3) unit tangents along each marking (central differences within a marking; zero for a lone point)."""
    arr = np.asarray(anchors, float)
    xyz = arr[:, :3]
    if labels is None:
        labels = arr[:, 3] if arr.shape[1] >= 4 else np.zeros(len(arr))
    labels = np.asarray(labels)
    t = np.zeros_like(xyz)
    for lab in np.unique(labels):
        idx = np.flatnonzero(labels == lab)
        if idx.size >= 2:
            t[idx] = np.gradient(xyz[idx], axis=0)
    n = np.linalg.norm(t, axis=1, keepdims=True)
    return np.divide(t, n, out=np.zeros_like(t), where=n > 0)


def _delta_matrix(delta: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = Rotation.from_rotvec(delta[:3]).as_matrix()
    T[:3, 3] = delta[3:]
    return T


def _gray(img: np.ndarray) -> np.ndarray:
    img = np.asarray(img, float)
    return img if img.ndim == 2 else img[..., :3] @ np.array([0.299, 0.587, 0.114])


def measure(c2w: np.ndarray, K: np.ndarray, gray: np.ndarray, xyz: np.ndarray, tangents: np.ndarray):
    """Per anchor: projected pixel p, unit image normal n and the signed stripe-centre offset (px) along n.

    The offset is NaN where no single stripe with two edges is found inside the cross-section.
    """
    h, w = gray.shape
    p, depth = zbuffer.project(xyz, c2w, K)
    p2, _ = zbuffer.project(xyz + 0.1 * tangents, c2w, K)
    d = p2 - p
    n = np.column_stack([-d[:, 1], d[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    m_per_px = np.maximum(depth, 1e-3) / K[0, 0]  # cross-section scale at the anchor (_cross_section_offset works in m)
    half = np.nan_to_num(np.clip(np.ceil(SEARCH_M / m_per_px), 3, 200), nan=3).astype(int)
    off = np.full(len(xyz), np.nan)
    for i in np.flatnonzero(np.isfinite(p).all(axis=1) & (depth > 0) & np.isfinite(n).all(axis=1)):
        s = np.arange(-half[i], half[i] + 1, dtype=float)
        u, v = p[i, 0] + s * n[i, 0], p[i, 1] + s * n[i, 1]
        ok = (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
        lum = map_coordinates(gray, [v, u], order=1, mode="nearest")
        val = colour._cross_section_offset(lum, ok, s * m_per_px[i])
        if val is not None:
            off[i] = val / m_per_px[i]
    return p, n, off


def refine_one(
    base_c2w: Any,
    K: Any,
    image: Any,
    anchors_3d: Any,
    params: Any,
    nonground: Any = None,
    boxes: Any = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Refine one camera frame's pose. Returns (c2w used for colouring, final offsets px, info).

    info: applied, reason (converged, no_anchors, insufficient_inliers, no_improvement, hit_bound), hit_bound,
    delta (6), n_anchors, n_inliers, offset_px_before / offset_px_after (median |stripe offset|, px).
    """
    base = np.asarray(base_c2w, float).reshape(4, 4)
    K = np.asarray(K, float).reshape(3, 3)
    anchors = np.zeros((0, 4)) if anchors_3d is None else np.asarray(anchors_3d, float)
    if anchors.ndim == 1:
        anchors = anchors.reshape(-1, 3)
    max_deg, max_m = float(params.pose_max_deg), float(params.pose_max_m)
    min_anchors = int(params.pose_min_anchors)
    info: dict[str, Any] = {"applied": False, "reason": "no_anchors", "hit_bound": False, "delta": [0.0] * 6,
                            "n_anchors": 0, "n_inliers": 0, "offset_px_before": None, "offset_px_after": None}
    gray = _gray(image)
    h, w = gray.shape
    if len(anchors):
        ng = np.zeros((0, 3)) if nonground is None else np.asarray(nonground, float).reshape(-1, 3)
        vis = zbuffer.visible(anchors[:, :3], ng, boxes or [], base, K, (w, h), params)
        anchors = anchors[vis]
    if len(anchors) > params.pose_max_anchors:
        anchors = anchors[np.linspace(0, len(anchors) - 1, params.pose_max_anchors).astype(int)]
    tang = _tangents(anchors) if len(anchors) else np.zeros((0, 3))
    keep = np.linalg.norm(tang, axis=1) > 0
    xyz, tang = anchors[keep, :3], tang[keep]
    info["n_anchors"] = len(xyz)
    if len(xyz) < min_anchors:
        return base.copy(), np.zeros(0), info

    _, _, off0 = measure(base, K, gray, xyz, tang)
    if np.isfinite(off0).sum() < min_anchors:
        info["reason"] = "insufficient_inliers"
        return base.copy(), off0, info
    before = float(np.nanmedian(np.abs(off0)))
    info["offset_px_before"] = round(before, 3)

    scale = np.array([np.radians(max_deg)] * 3 + [max_m] * 3)
    delta = np.zeros(6)
    inl = np.zeros(len(xyz), bool)
    for _ in range(ROUNDS):
        c2w = base @ _delta_matrix(delta)
        p, n, off = measure(c2w, K, gray, xyz, tang)
        ok = np.isfinite(off)
        if ok.sum() < min_anchors:
            break
        mad = 1.4826 * np.median(np.abs(off[ok] - np.median(off[ok])))
        inl = ok & (np.abs(np.nan_to_num(off)) <= max(OUTLIER_PX, 3 * mad))
        if inl.sum() < min_anchors:
            break
        q = p[inl] + off[inl, None] * n[inl]
        X, N = xyz[inl], n[inl]

        def res(d, X=X, N=N, q=q):
            uv, _ = zbuffer.project(X, base @ _delta_matrix(d), K)
            return np.concatenate([np.einsum("ij,ij->i", uv - q, N), PRIOR_PX * d / scale])

        # ponytail: 2-point finite differences on a cheap projection; analytic Jacobian if this ever shows in a profile.
        delta = least_squares(res, delta, bounds=(-scale, scale), loss="soft_l1", f_scale=LOSS_PX,
                              x_scale=scale, max_nfev=params.pose_max_nfev).x

    info["n_inliers"] = int(inl.sum())
    info["delta"] = [round(float(x), 7) for x in delta]
    hit = bool(np.any(np.abs(delta) >= scale * (1 - 1e-3)))
    info["hit_bound"] = hit
    c2w = base @ _delta_matrix(delta)
    _, _, off1 = measure(c2w, K, gray, xyz, tang)
    after = float(np.nanmedian(np.abs(off1))) if np.isfinite(off1).any() else np.inf
    info["offset_px_after"] = round(after, 3) if np.isfinite(after) else None
    if inl.sum() < min_anchors or np.isfinite(off1).sum() < min_anchors:
        info["reason"] = "insufficient_inliers"
    elif hit:
        info["reason"] = "hit_bound"
    elif not after < before:
        info["reason"] = "no_improvement"
    else:
        info.update(applied=True, reason="converged")
        return c2w, off1, info
    info["delta"] = [0.0] * 6
    return base.copy(), off0, info
