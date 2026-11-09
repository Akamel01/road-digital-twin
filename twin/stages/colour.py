"""Stage 6 colour (zbuffer-topk): median colour of the best top_k views per point, and the orthoimage.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (Colour) and 8.
Prior work: docs/research/camera-ground-projection.md (steps 1 to 5: camera pose, projection, z-buffer with
boxes, range filter, top-K median) and docs/research/multi-sensor-sota.md section 2 (decision 38).
Visibility, camera poses and box blockers come from twin.stages.zbuffer.
Inputs: ground's ground.laz, nonground.laz and qa.json; align's poses.json (refined sweep poses);
load's cameras.json, boxes.json. Outputs: ortho.png, ortho.pgw, rgb.npz, qa.json.
"""

from __future__ import annotations

import bisect
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import laspy
import numpy as np
from PIL import Image

from twin.contracts import ColourParams, StageResult
from twin.registry import register
from twin.stages import zbuffer
from twin.stages.load import DATAROOT_DEFAULT

OUTPUT_FILES = ("ortho.png", "ortho.pgw", "rgb.npz", "qa.json")
ORTHO_LABEL = "orthoimage"
INDETERMINATE_LABEL = "indeterminate (height)"
# DECISION: a view is an (cam_to_world, K, image, boxes) tuple; colour_points takes any iterable of them so the
# stage can stream one image at a time.


def footprint(
    points: np.ndarray, cam_to_world: np.ndarray, K: np.ndarray
) -> np.ndarray:
    """Ground footprint proxy d^3 / (f^2 h) per point (camera-ground-projection, step 5). Smaller = closer, sharper.

    d is the horizontal range, h the camera height above the point. DECISION: h is floored at 1 mm, so points at or
    above camera height rank last instead of dividing by zero or going negative.
    """
    cam = cam_to_world[:3, 3]
    d = np.hypot(*(points[:, :2] - cam[:2]).T)
    h = np.maximum(cam[2] - points[:, 2], 1e-3)
    f = (float(K[0, 0]) + float(K[1, 1])) / 2
    return d**3 / (f * f * h)


def colour_points(
    points: np.ndarray,
    nonground: np.ndarray,
    views: Iterable[tuple[np.ndarray, np.ndarray, np.ndarray, list[dict]]],
    params: ColourParams,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per point: median colour of its best top_k visible views.

    Returns rgb (N, 3) uint8 (zero where unobserved), observed (N,) bool and n_views (N,) int, the number of views kept.
    nonground are the occluders (ground never occludes ground); boxes come per view.
    """
    n, k = len(points), params.top_k
    best_fp = np.full((n, k), np.inf)
    best_rgb = np.zeros((n, k, 3), np.uint8)
    for cam_to_world, K, img, boxes in views:
        h, w = img.shape[:2]
        vis = zbuffer.visible(points, nonground, boxes, cam_to_world, K, (w, h), params)
        idx = np.flatnonzero(vis)
        if idx.size == 0:
            continue
        uv, _ = zbuffer.project(points[idx], cam_to_world, K)
        cols = np.clip(np.floor(uv[:, 1]).astype(np.int64), 0, h - 1)
        rows = np.clip(np.floor(uv[:, 0]).astype(np.int64), 0, w - 1)
        col = img[cols, rows]
        fp = footprint(points[idx], cam_to_world, K)
        # Replace the worst kept view wherever this one is closer.
        worst = np.argmax(best_fp[idx], axis=1)
        better = fp < best_fp[idx, worst]
        keep, slot = idx[better], worst[better]
        best_fp[keep, slot] = fp[better]
        best_rgb[keep, slot] = col[better]

    kept = np.isfinite(best_fp)
    observed = kept.any(axis=1)
    n_views = kept.sum(axis=1)
    rgb = np.zeros((n, 3), np.uint8)
    if observed.any():
        vals = np.where(
            kept[observed][..., None], best_rgb[observed].astype(float), np.nan
        )
        rgb[observed] = np.round(np.nanmedian(vals, axis=1)).astype(np.uint8)
    return rgb, observed, n_views


def ortho_raster(
    xy: np.ndarray, rgb: np.ndarray, observed: np.ndarray, cell_m: float
) -> tuple[np.ndarray, np.ndarray]:
    """North-up RGBA raster of cell_m cells: per cell, the per-channel lower median of its observed points.

    Cells with no observed point have alpha 0 (unobserved, never filled). Returns (rgba, origin) where origin is the
    lower-left corner of the grid in the same CRS as xy.
    """
    origin = xy.min(axis=0)
    ij = np.floor((xy - origin) / cell_m).astype(np.int64)
    nx, ny = int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1
    rgba = np.zeros((ny, nx, 4), np.uint8)
    obs = np.flatnonzero(observed)
    if obs.size == 0:
        return rgba[::-1], origin
    flat = ij[obs, 1] * nx + ij[obs, 0]
    cells = vals = None
    for c in range(3):
        order = np.lexsort(
            (rgb[obs, c], flat)
        )  # by cell, then by value within the cell
        cells, start, count = np.unique(
            flat[order], return_index=True, return_counts=True
        )
        mid = start + (count - 1) // 2
        if vals is None:
            vals = np.zeros((len(cells), 3), np.uint8)
        vals[:, c] = rgb[obs, c][order][mid]
    rgba[cells // nx, cells % nx, :3] = vals
    rgba[cells // nx, cells % nx, 3] = 255
    return rgba[::-1], origin  # row 0 is the north edge


def boxes_at(sweep_boxes: list[dict], t: int) -> list[dict]:
    """Boxes at image time t: the nearest sweep's boxes, each centre lerped to the same track's box in the other sweep.

    sweep_boxes: load's boxes.json entries (timestamp_us, boxes with token). Tracks with a box in only one sweep keep
    that sweep's box unchanged.
    """
    times = [s["timestamp_us"] for s in sweep_boxes]
    i = min(max(bisect.bisect_right(times, t) - 1, 0), len(times) - 2)
    a, b = sweep_boxes[i], sweep_boxes[i + 1]
    s = (t - a["timestamp_us"]) / (b["timestamp_us"] - a["timestamp_us"])
    near_is_a = s < 0.5
    near, far = (a, b) if near_is_a else (b, a)
    other = {bx["token"]: bx for bx in far["boxes"]}
    out = []
    for bx in near["boxes"]:
        o = other.get(bx["token"])
        if o is not None:
            ca, cb = (
                (bx["center"], o["center"])
                if near_is_a
                else (o["center"], bx["center"])
            )
            centre = (1 - s) * np.asarray(ca, float) + s * np.asarray(cb, float)
            bx = {**bx, "center": centre.tolist()}
        out.append(bx)
    return out


@register("colour", "zbuffer-topk")
def run(ctx: Any, params: ColourParams) -> StageResult:
    out: Path = ctx.stage_dir("colour")
    out.mkdir(exist_ok=True)
    gdir = ctx.input_dir("ground")
    ground_qa = json.loads((gdir / "qa.json").read_text())
    ground_xyz = laspy.read(gdir / "ground.laz").xyz
    nonground_xyz = laspy.read(gdir / "nonground.laz").xyz
    # Same order as outputs' twin cloud: ground first, then non-ground.
    points = np.vstack([ground_xyz, nonground_xyz])

    align_rows = json.loads((ctx.input_dir("align") / "poses.json").read_text())[
        "poses"
    ]
    ego = np.array([r["matrix"] for r in align_rows], float).reshape(-1, 4, 4)
    times = np.array([r["timestamp_us"] for r in align_rows], np.int64)
    ldir = ctx.input_dir("load")
    cams = json.loads((ldir / "cameras.json").read_text())["cameras"]
    sweep_boxes = json.loads((ldir / "boxes.json").read_text())["sweeps"]
    # DECISION: a camera outside the sweep span has no refined pose, so it is skipped (counted in qa.json).
    usable = [c for c in cams if times[0] <= c["timestamp_us"] <= times[-1]]
    root = Path(os.environ.get("NUSCENES_ROOT", DATAROOT_DEFAULT))

    def views():
        for cam in usable:
            t = int(cam["timestamp_us"])
            c2w = zbuffer.camera_to_world(ego, times, t, cam["extrinsics"])
            K = np.asarray(cam["intrinsics"], float)
            img = np.asarray(Image.open(root / cam["image"]).convert("RGB"))
            yield c2w, K, img, boxes_at(sweep_boxes, t)

    rgb, observed, n_views = colour_points(points, nonground_xyz, views(), params)

    height_valid = bool(ground_qa["height_valid"])
    ortho, origin = ortho_raster(
        points[: len(ground_xyz), :2],
        rgb[: len(ground_xyz)],
        observed[: len(ground_xyz)],
        params.gsd_m,
    )
    ny = ortho.shape[0]
    cell = params.gsd_m
    Image.fromarray(ortho).save(out / "ortho.png")
    ul_x, ul_y = origin[0] + cell / 2, origin[1] + ny * cell - cell / 2
    pgw = [cell, 0.0, 0.0, -cell, ul_x, ul_y]
    (out / "ortho.pgw").write_text("\n".join(f"{v:.6f}" for v in pgw) + "\n")
    np.savez_compressed(out / "rgb.npz", rgb=rgb, observed=observed)

    label = ORTHO_LABEL if height_valid else INDETERMINATE_LABEL
    qa = {
        "method": "zbuffer-topk",
        "ortho_label": label,
        "height_valid": height_valid,
        "views_median": float(np.median(n_views[observed])) if observed.any() else None,
        "observed_share": float(observed.mean()),
        "n_points": len(points),
        "n_cameras": len(cams),
        "n_cameras_skipped_outside_sweeps": len(cams) - len(usable),
        "top_k": params.top_k,
        "gsd_m": cell,
        # Not measured yet: needs the features stage's marking edges (spec section 6, QA).
        "edge_offset_p95_m": None,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(
        status="ok",
        files=list(OUTPUT_FILES),
        metrics=qa,
        message=label,
    )
