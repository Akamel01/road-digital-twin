"""Colour stage helper: per-camera depth buffer and point visibility (not a registered stage).

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (Colour) and 8.
Prior work: docs/research/camera-ground-projection.md (steps 1 to 4: camera pose, devkit projection,
z-buffer with boxes, range filter) and docs/research/multi-sensor-sota.md section 2 (decision 38).
Inputs: align's refined sweep poses (poses.json "poses"), load's sweep timestamps and cameras.json
(intrinsics, extrinsics). The colour stage (later ticket) calls these functions; nothing registers here.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from twin.contracts import ColourParams
from twin.stages.load import pose_matrix, quat_to_matrix, slerp

# DECISION: the devkit keeps image pixels with a 1 px margin inside the border (map_pointcloud_to_image).
IMAGE_MARGIN_PX = 1


# ------------------------------------------------------------------ camera pose


def matrix_to_quat(r: np.ndarray) -> np.ndarray:
    """[w, x, y, z] quaternion from a 3x3 rotation matrix (Shepperd's method, the branch with the largest term)."""
    tr = r[0, 0] + r[1, 1] + r[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [
            0.25 * s,
            (r[2, 1] - r[1, 2]) / s,
            (r[0, 2] - r[2, 0]) / s,
            (r[1, 0] - r[0, 1]) / s,
        ]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1 + r[0, 0] - r[1, 1] - r[2, 2]) * 2
        q = [
            (r[2, 1] - r[1, 2]) / s,
            0.25 * s,
            (r[0, 1] + r[1, 0]) / s,
            (r[0, 2] + r[2, 0]) / s,
        ]
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1 + r[1, 1] - r[0, 0] - r[2, 2]) * 2
        q = [
            (r[0, 2] - r[2, 0]) / s,
            (r[0, 1] + r[1, 0]) / s,
            0.25 * s,
            (r[1, 2] + r[2, 1]) / s,
        ]
    else:
        s = math.sqrt(1 + r[2, 2] - r[0, 0] - r[1, 1]) * 2
        q = [
            (r[1, 0] - r[0, 1]) / s,
            (r[0, 2] + r[2, 0]) / s,
            (r[1, 2] + r[2, 1]) / s,
            0.25 * s,
        ]
    return np.array(q)


def pose_at(ego_poses: np.ndarray, times_us: np.ndarray, t_us: int) -> np.ndarray:
    """Refined ego pose (4x4, run CRS) at time t_us: lerp translation, slerp rotation between sweeps."""
    times = np.asarray(times_us, dtype=np.int64)
    if len(times) < 2 or not times[0] <= t_us <= times[-1]:
        raise ValueError(f"time {t_us} outside the sweep span {times[0]}..{times[-1]}")
    k = min(max(int(np.searchsorted(times, t_us, side="right")) - 1, 0), len(times) - 2)
    s = (t_us - times[k]) / (times[k + 1] - times[k])
    a, b = ego_poses[k], ego_poses[k + 1]
    q = slerp(matrix_to_quat(a[:3, :3]), matrix_to_quat(b[:3, :3]), s)
    out = np.eye(4)
    out[:3, :3] = quat_to_matrix(q)
    out[:3, 3] = (1 - s) * a[:3, 3] + s * b[:3, 3]
    return out


def camera_to_world(
    ego_poses: np.ndarray, times_us: np.ndarray, image_t_us: int, extrinsic: dict
) -> np.ndarray:
    """T_global_cam for one image: the ego pose at the image time times the camera extrinsic.

    extrinsic: cameras.json "extrinsics" ({"translation", "rotation_wxyz"}, relative to the ego body).
    """
    t_ego_cam = pose_matrix(extrinsic["translation"], extrinsic["rotation_wxyz"])
    return pose_at(ego_poses, times_us, image_t_us) @ t_ego_cam


# ------------------------------------------------------------------ boxes


def box_blockers(
    boxes: list[dict], cam_to_world: np.ndarray, K: np.ndarray, params: ColourParams, xp: Any = np
) -> np.ndarray:
    """Box face samples for one camera, spaced one depth-buffer cell apart at each box's nearest distance.

    A fixed spacing leaves see-through gaps up close: at 5 m a 4 px cell is about 2.5 cm, so the
    samples must follow the depth. Nearest distance = centre distance minus half the box diagonal,
    floored at min_depth_m.
    Up close this is millions of samples, so with xp=cupy they are built on the GPU.
    """
    cam = cam_to_world[:3, 3]
    fx = float(np.asarray(K)[0, 0])
    out = []
    for b in boxes:
        radius = np.linalg.norm(np.asarray(b["size"], dtype=float)) / 2
        dist = np.linalg.norm(np.asarray(b["center"], dtype=float) - cam) - radius
        step = max(dist, params.min_depth_m) / (fx * params.zbuf_scale)
        out.append(box_samples([b], step, xp))
    return xp.vstack(out) if out else xp.empty((0, 3))


def box_samples(boxes: list[dict], step_m: float, xp: Any = np) -> np.ndarray:
    """(M, 3) points on the six faces of each box (boxes.json format, run CRS), spaced step_m apart."""
    out = []
    for b in boxes:
        # DECISION: as in mask.inside, nuScenes size is [w, l, h] with length on the local x axis.
        half = np.asarray(b["size"], dtype=float)[[1, 0, 2]] / 2
        rot = quat_to_matrix(b["rotation"])
        centre = np.asarray(b["center"], dtype=float)
        for axis in range(3):
            a1, a2 = [a for a in range(3) if a != axis]
            g1 = xp.linspace(
                -half[a1], half[a1], max(2, math.ceil(2 * half[a1] / step_m) + 1)
            )
            g2 = xp.linspace(
                -half[a2], half[a2], max(2, math.ceil(2 * half[a2] / step_m) + 1)
            )
            u, v = xp.meshgrid(g1, g2)
            for sign in (-1.0, 1.0):
                p = xp.zeros((u.size, 3))
                p[:, a1], p[:, a2] = u.ravel(), v.ravel()
                p[:, axis] = sign * half[axis]
                out.append(p @ xp.asarray(rot.T) + xp.asarray(centre))
    return xp.vstack(out) if out else xp.empty((0, 3))


# ------------------------------------------------------------------ projection and visibility


def project(
    points: np.ndarray, cam_to_world: np.ndarray, K: np.ndarray, xp: Any = np
) -> tuple[np.ndarray, np.ndarray]:
    """Pixel coordinates (N, 2) and depth (N,) of world points, camera axes x right, y down, z forward.

    Points at depth 0 or behind the camera get NaN pixels; the caller filters by depth. xp is numpy, or cupy when
    points are on the GPU (the small pose and intrinsics arrays are moved to match).
    """
    cam_to_world, K = xp.asarray(cam_to_world, dtype=float), xp.asarray(K, dtype=float)
    r, t = cam_to_world[:3, :3], cam_to_world[:3, 3]
    cam = (points - t) @ r  # R^T (p - t), row-wise
    depth = cam[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        uvw = cam @ K.T
        uv = uvw[:, :2] / uvw[:, 2:3]
    uv[depth <= 0] = np.nan
    return uv, depth


def visible(
    targets: np.ndarray,
    nonground: np.ndarray,
    boxes: list[dict],
    cam_to_world: np.ndarray,
    K: np.ndarray,
    image_size: tuple[int, int],
    params: ColourParams,
    xp: Any = np,
) -> np.ndarray:
    """(N,) bool: targets that this camera may colour. With xp=cupy, targets and nonground are GPU arrays and so is the result.

    A target passes if it lands inside the image (with IMAGE_MARGIN_PX), is at least min_depth_m away,
    lies within max_range_m horizontally of the camera, and is no deeper than the depth buffer plus
    zbuf_tol_m. The buffer holds the nearest occluder per cell at zbuf_scale resolution. Occluders are
    the non-ground points (nonground) plus the box faces at the image time (boxes). Ground never
    occludes ground: on a near-flat street that only causes false self-occlusion at shallow angles
    (decision 2026-11-08). Occluders nearer than min_depth_m are ignored, as are targets.
    """
    width, height = image_size
    s = params.zbuf_scale
    blockers = xp.vstack([nonground, box_blockers(boxes, cam_to_world, K, params, xp)])

    def in_image(uv: np.ndarray, depth: np.ndarray) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return (
                (uv[:, 0] >= IMAGE_MARGIN_PX)
                & (uv[:, 0] < width - IMAGE_MARGIN_PX)
                & (uv[:, 1] >= IMAGE_MARGIN_PX)
                & (uv[:, 1] < height - IMAGE_MARGIN_PX)
                & (depth >= params.min_depth_m)
            )

    t_uv, t_depth = project(targets, cam_to_world, K, xp)
    t_ok = in_image(t_uv, t_depth)

    b_uv, b_depth = project(blockers, cam_to_world, K, xp)
    b_ok = in_image(b_uv, b_depth)

    buf_w, buf_h = math.ceil(width * s), math.ceil(height * s)
    buf = xp.full(buf_h * buf_w, xp.inf)
    b_cell = _cell(b_uv[b_ok], s, buf_w, buf_h, xp)
    xp.minimum.at(buf, b_cell, b_depth[b_ok])

    t_cell = _cell(t_uv[t_ok], s, buf_w, buf_h, xp)
    depth_ok = xp.zeros(len(targets), bool)
    depth_ok[t_ok] = t_depth[t_ok] <= buf[t_cell] + params.zbuf_tol_m

    centre = xp.asarray(cam_to_world[:2, 3])
    in_range = xp.hypot(*(targets[:, :2] - centre).T) <= params.max_range_m
    return t_ok & depth_ok & in_range


def _cell(uv: np.ndarray, scale: float, buf_w: int, buf_h: int, xp: Any = np) -> np.ndarray:
    col = xp.clip(xp.floor(uv[:, 0] * scale).astype(xp.int64), 0, buf_w - 1)
    row = xp.clip(xp.floor(uv[:, 1] * scale).astype(xp.int64), 0, buf_h - 1)
    return row * buf_w + col
