"""Stage 12 splats (gsplat-lidar): 3D Gaussian splats started from the lidar, for the viewing layer and a 2-3 cm orthophoto.

Source of truth: docs/decisions/0006-camera-lidar-fusion.md (Q1, Q2c, Q3); ticket #176; docs/research/gaussian-splats.md.
Splats are a rendering. Nothing measured from them goes into the twin's metrics unless the lidar confirms it, so this
stage writes no feature and no accuracy number; its geometry check (splat centres against the lidar ground) only says
how far the rendering can be trusted as a picture of the lidar surface.

Method (gsplat, Apache-2.0):
- The splats start at the aligned lidar points (ground and non-ground, a random subset).
- Training images use the dataset poses (ego pose at the image time times the camera extrinsic). Each training camera has
  a small learnable correction (clamped), reported as QA (Q3).
- The loss is photometric (L1 and SSIM) plus the relative error against the lidar depth projected into the image.
  Pixels covered by annotated boxes (cars, people) are left out: the lidar cloud had them removed (mask stage).
- Every holdout_every-th image is held out and scores PSNR and SSIM, with the dataset pose.
Inputs: load's cameras.json, boxes.json; align's poses.json; ground's ground.laz, nonground.laz, surface.npz.
Outputs: splats.npz, ortho.png (+ ortho.pgw, ground layer, transparent where unobserved), qa.json.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

import laspy
import numpy as np
from PIL import Image

from twin.contracts import SplatsParams, StageResult
from twin.registry import register
from twin.stages import colour, zbuffer
from twin.stages.load import DATAROOT_DEFAULT

log = logging.getLogger(__name__)
OUTPUT_FILES = ("splats.npz", "ortho.png", "ortho.pgw", "qa.json")
LICENCES = {
    "splat library": "gsplat 1.5.3, Apache-2.0 (nerfstudio-project/gsplat)",
    "torch": "BSD-3-Clause",
    "data": "nuScenes images and lidar, CC BY-NC-SA 4.0",
}
# DECISION: the VRAM budget on the shared box is 10 GB (the card has 12 GB and Librarian uses some).
VRAM_BUDGET_MIB = 10 * 1024
# DECISION: lidar depth is used between these ranges only; nearer returns hit the ego car, farther are sparse.
DEPTH_MIN_M, DEPTH_MAX_M = 1.0, 70.0
# DECISION: the densification thresholds scale with this length (gsplat's scene_scale). With lidar start points a few
# cm apart, 8 m puts the split threshold (1 % of it) at 8 cm.
SCENE_SCALE_M = 8.0
# Learning rates (gsplat's simple_trainer defaults, except the means: the lidar is the authority for position, so they
# move 10 times less than in an image-only start).
LR = {"means": 1.6e-5, "scales": 5e-3, "quats": 1e-3, "opacities": 5e-2, "colors": 5e-3}
POSE_LR = 1e-4
SSIM_WEIGHT = 0.2
BOX_DILATE_PX = 5
ORTHO_TILE_PX = 2048
OPACITY_MIN = 0.3  # splats below this are not counted in the geometry check or written to the orthophoto
INIT_VOXEL_M = 0.1
INIT_FLAT_M = 0.01
INIT_SCALE_MIN_M, INIT_SCALE_MAX_M = 0.03, 0.5
GEOM_CELL_M = 0.5
GEOM_MIN_SPLATS = 5
GEOM_WINDOW_M = 2.0
GEOM_PCT = 10  # the ground of a cell is the 10th percentile of z, as in merge.py


# ------------------------------------------------------------------ numpy parts (tested without a GPU)


def scaled_intrinsics(k: np.ndarray, size: tuple[int, int], long_side: int):
    """(K scaled, (w, h)) for an image of `size` (w, h) resized so that its longest side is long_side px."""
    s = long_side / max(size)
    w, h = max(1, round(size[0] * s)), max(1, round(size[1] * s))
    k = np.asarray(k, float).copy()
    k[0] *= w / size[0]
    k[1] *= h / size[1]
    return k, (w, h)


def sparse_depth(points: np.ndarray, c2w: np.ndarray, k: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(h, w) float32 depth of the nearest lidar point per pixel, 0 where none (size is (w, h), k is for that size)."""
    w, h = size
    uv, d = zbuffer.project(points, c2w, k)
    with np.errstate(invalid="ignore"):
        ok = (d >= DEPTH_MIN_M) & (d <= DEPTH_MAX_M) & (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
    out = np.full(h * w, np.inf, np.float32)
    cell = np.floor(uv[ok, 1]).astype(np.int64) * w + np.floor(uv[ok, 0]).astype(np.int64)
    np.minimum.at(out, cell, d[ok].astype(np.float32))
    out[np.isinf(out)] = 0
    return out.reshape(h, w)


def box_mask(boxes: list[dict], c2w: np.ndarray, k: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(h, w) bool: pixels near the faces of the annotated boxes (dilated by BOX_DILATE_PX)."""
    w, h = size
    m = np.zeros((h, w), bool)
    if not boxes:
        return m
    uv, d = zbuffer.project(zbuffer.box_samples(boxes, 0.15), c2w, k)
    with np.errstate(invalid="ignore"):
        ok = (d > 0.5) & (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
    m[np.floor(uv[ok, 1]).astype(int), np.floor(uv[ok, 0]).astype(int)] = True
    r = BOX_DILATE_PX
    pad = np.pad(m, r)
    out = np.zeros_like(m)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= pad[r + dy : r + dy + h, r + dx : r + dx + w]
    return out


def ground_z_at(surface: dict, xy: np.ndarray) -> np.ndarray:
    """Lidar ground height at xy (N, 2) from ground's surface grid; NaN where the lidar saw no ground."""
    c = float(surface["cell_m"])
    ij = np.floor((xy - surface["origin"]) / c).astype(np.int64)
    z = surface["z"]
    ny, nx = z.shape
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < nx) & (ij[:, 1] >= 0) & (ij[:, 1] < ny)
    out = np.full(len(xy), np.nan)
    sel = np.flatnonzero(ok)
    v = z[ij[sel, 1], ij[sel, 0]].astype(float)
    v[surface["count"][ij[sel, 1], ij[sel, 0]] <= 0] = np.nan
    out[sel] = v
    return out


def geometry_agreement(centres: np.ndarray, surface: dict) -> dict:
    """How far the splat centres sit from the lidar ground.

    Per GEOM_CELL_M cell of the lidar ground surface that holds at least GEOM_MIN_SPLATS splat centres within
    GEOM_WINDOW_M of the ground height, the splats' ground is their GEOM_PCT-th percentile of z (the convention of
    merge.py) and the cell's difference is that minus the lidar ground height. Reports |difference| P50 and P95 (m), the
    cells compared, and the share of observed lidar-ground cells that have enough splats.
    """
    gz = ground_z_at(surface, centres[:, :2])
    near = np.isfinite(gz) & (np.abs(centres[:, 2] - gz) <= GEOM_WINDOW_M)
    c = centres[near]
    ij = np.floor((c[:, :2] - surface["origin"]) / GEOM_CELL_M).astype(np.int64)
    key = ij[:, 1] * 100000 + ij[:, 0]
    order = np.argsort(key)
    key, c, gzn = key[order], c[order], gz[near][order]
    cuts = np.flatnonzero(np.diff(key)) + 1
    diffs = []
    for idx in np.split(np.arange(len(key)), cuts):
        if len(idx) >= GEOM_MIN_SPLATS:
            diffs.append(np.percentile(c[idx, 2], GEOM_PCT) - gzn[idx].mean())
    # Lidar-ground cells at the same resolution: surface cells are surface["cell_m"] wide, so count those with ground.
    n_cells = int((surface["count"] > 0).sum() * (float(surface["cell_m"]) / GEOM_CELL_M) ** 2)
    d = np.abs(np.asarray(diffs))
    return {
        "cell_m": GEOM_CELL_M,
        "n_cells_compared": len(d),
        "coverage": round(len(d) / max(n_cells, 1), 3),
        "abs_p50_m": round(float(np.percentile(d, 50)), 4) if len(d) else None,
        "abs_p95_m": round(float(np.percentile(d, 95)), 4) if len(d) else None,
        "signed_mean_m": round(float(np.mean(diffs)), 4) if len(d) else None,
    }


def ortho_tiles(lo: np.ndarray, hi: np.ndarray, pixel_m: float, tile_px: int = ORTHO_TILE_PX):
    """Tiles covering [lo, hi] (x, y) as (col0, row0, w_px, h_px) in a north-up image whose pixel (0, 0) is at
    (lo_x, hi_y). Returns (tiles, (width_px, height_px))."""
    width = math.ceil((hi[0] - lo[0]) / pixel_m)
    height = math.ceil((hi[1] - lo[1]) / pixel_m)
    tiles = [
        (c, r, min(tile_px, width - c), min(tile_px, height - r))
        for r in range(0, height, tile_px)
        for c in range(0, width, tile_px)
    ]
    return tiles, (width, height)


def pose_report(deltas: np.ndarray, names: list[str], p: SplatsParams) -> dict:
    """The per-camera corrections (deltas rows: rotation vector rad, translation m), summarised and flagged."""
    deg = np.degrees(np.linalg.norm(deltas[:, :3], axis=1))
    m = np.linalg.norm(deltas[:, 3:], axis=1)
    flag = (deg > p.pose_flag_deg) | (m > p.pose_flag_m)
    by_ch: dict[str, dict] = {}
    for ch in sorted(set(names)):
        s = np.array([n == ch for n in names])
        by_ch[ch] = {"median_deg": round(float(np.median(deg[s])), 4), "median_m": round(float(np.median(m[s])), 4)}
    return {
        "n_cameras": len(deg),
        "rotation_deg_p50": round(float(np.percentile(deg, 50)), 4),
        "rotation_deg_p95": round(float(np.percentile(deg, 95)), 4),
        "rotation_deg_max": round(float(deg.max()), 4),
        "translation_m_p50": round(float(np.percentile(m, 50)), 4),
        "translation_m_p95": round(float(np.percentile(m, 95)), 4),
        "translation_m_max": round(float(m.max()), 4),
        "n_flagged": int(flag.sum()),
        "drive_flagged": bool(flag.mean() >= 0.25),
        "by_channel": by_ch,
    }


# ------------------------------------------------------------------ torch parts


def _delta_matrix(torch, d):
    """4x4 camera-frame correction from d = (rotation vector rad, translation m)."""
    z = torch.zeros((), device=d.device)
    k = torch.stack([z, -d[2], d[1], d[2], z, -d[0], -d[1], d[0], z]).reshape(3, 3)
    rot = torch.linalg.matrix_exp(k)
    top = torch.cat([rot, d[3:, None]], dim=1)
    return torch.cat([top, torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=d.device)], dim=0)


def _ssim_map(torch, a, b):
    """Per-pixel SSIM of two (1, 3, h, w) images in [0, 1] (11x11 Gaussian window, sigma 1.5), averaged over colour."""
    x = torch.arange(11, device=a.device, dtype=a.dtype) - 5
    g = torch.exp(-(x**2) / (2 * 1.5**2))
    g = g / g.sum()
    win = (g[:, None] * g[None, :]).expand(3, 1, 11, 11).contiguous()

    def f(t):
        return torch.nn.functional.conv2d(t, win, padding=5, groups=3)

    mu_a, mu_b = f(a), f(b)
    saa, sbb, sab = f(a * a) - mu_a**2, f(b * b) - mu_b**2, f(a * b) - mu_a * mu_b
    c1, c2 = 0.01**2, 0.03**2
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a**2 + mu_b**2 + c1) * (saa + sbb + c2))
    return m.mean(1, keepdim=True)


def _thin(points: np.ndarray, voxel_m: float) -> np.ndarray:
    import open3d as o3d

    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    return np.asarray(pcd.voxel_down_sample(voxel_m).points)


def _nn_dist(points: np.ndarray) -> np.ndarray:
    import open3d as o3d

    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
    return np.clip(np.asarray(pcd.compute_nearest_neighbor_distance()), INIT_SCALE_MIN_M, INIT_SCALE_MAX_M)


def initial_splats(ground: np.ndarray, nonground: np.ndarray, n_max: int, seed: int) -> dict:
    """The lidar start: (xyz, log scales, quats wxyz) of the first splats.

    DECISION: all ground points thinned to INIT_VOXEL_M (a flat disc each, scaled to the gap to its nearest
    neighbour, so the road is covered without holes from the start) plus a random share of the thinned non-ground
    points (round blobs) up to n_max in all. Ground discs make the orthophoto complete where the lidar saw ground.
    """
    g = _thin(ground, INIT_VOXEL_M)
    ng = _thin(nonground, INIT_VOXEL_M)
    rng = np.random.default_rng(seed)
    if len(g) > n_max:
        g = g[rng.choice(len(g), n_max, replace=False)]
    ng = ng[rng.choice(len(ng), max(0, min(len(ng), n_max - len(g))), replace=False)]
    dg, dn = _nn_dist(g), _nn_dist(ng) if len(ng) else np.zeros(0)
    scales = np.vstack(
        [
            np.log(np.column_stack([dg * 0.7, dg * 0.7, np.full_like(dg, INIT_FLAT_M)])),
            np.log(np.repeat(np.maximum(dn, INIT_SCALE_MIN_M)[:, None] * 0.7, 3, 1)),
        ]
    ).astype(np.float32)
    quats = np.zeros((len(g) + len(ng), 4), np.float32)
    quats[:, 0] = 1.0  # discs lie flat, in the world's xy plane; the non-ground blobs are round, so the same quat is fine
    return {"xyz": np.vstack([g, ng]), "scales": scales, "quats": quats}


def _load_views(ctx: Any, p: SplatsParams, origin: np.ndarray, points: np.ndarray):
    """Per usable camera image: dict with channel, c2w (world minus `origin`), K, size, image uint8, depth, box mask."""
    ldir = ctx.input_dir("load")
    rows = json.loads((ctx.input_dir("align") / "poses.json").read_text())["poses"]
    ego = np.array([r["matrix"] for r in rows], float).reshape(-1, 4, 4)
    times = np.array([r["timestamp_us"] for r in rows], np.int64)
    cams = json.loads((ldir / "cameras.json").read_text())["cameras"]
    sweep_boxes = json.loads((ldir / "boxes.json").read_text())["sweeps"]
    root = Path(os.environ.get("NUSCENES_ROOT", DATAROOT_DEFAULT))
    shifted = points - origin
    views = []
    for cam in sorted(cams, key=lambda c: (c["timestamp_us"], c["channel"])):
        t = int(cam["timestamp_us"])
        if not times[0] <= t <= times[-1]:
            continue
        c2w_world = zbuffer.camera_to_world(ego, times, t, cam["extrinsics"])
        c2w = c2w_world.copy()
        c2w[:3, 3] -= origin
        img = Image.open(root / cam["image"]).convert("RGB")
        k, size = scaled_intrinsics(cam["intrinsics"], img.size, p.long_side_px)
        img = np.asarray(img.resize(size, Image.BILINEAR))
        views.append(
            {
                "channel": cam["channel"],
                "t": t,
                "c2w": c2w,
                "K": k,
                "size": size,
                "image": img,
                "depth": sparse_depth(shifted, c2w, k, size),
                "box": box_mask(colour.boxes_at(sweep_boxes, t), c2w_world, k, size),
            }
        )
    return views


def train(views: list[dict], init: dict, p: SplatsParams, log_every: int = 1000) -> dict:
    """Train the splats on the non-held-out views. Returns the splats (numpy), pose deltas, losses and held-out scores."""
    import torch
    from gsplat import rasterization
    from gsplat.strategy import DefaultStrategy

    torch.manual_seed(p.seed)
    dev = "cuda"
    total = torch.cuda.get_device_properties(0).total_memory
    torch.cuda.set_per_process_memory_fraction(min(1.0, VRAM_BUDGET_MIB * 2**20 / total))
    torch.cuda.reset_peak_memory_stats()

    held = [i for i in range(len(views)) if i % p.holdout_every == 0]
    train_ids = [i for i in range(len(views)) if i % p.holdout_every != 0]

    def to_t(v):
        return {
            "img": torch.from_numpy(v["image"]).to(dev),
            "depth": torch.from_numpy(v["depth"]).to(dev),
            "ok": torch.from_numpy(~v["box"]).to(dev),
            "c2w": torch.from_numpy(v["c2w"]).float().to(dev),
            "K": torch.from_numpy(v["K"]).float().to(dev),
            "size": v["size"],
        }

    data = [to_t(v) for v in views]
    params = torch.nn.ParameterDict(
        {
            "means": torch.nn.Parameter(torch.from_numpy(init["xyz"].astype(np.float32)).to(dev)),
            "scales": torch.nn.Parameter(torch.from_numpy(init["scales"]).to(dev)),
            "quats": torch.nn.Parameter(torch.from_numpy(init["quats"]).to(dev)),
            "opacities": torch.nn.Parameter(torch.zeros(len(init["xyz"]), device=dev)),
            "colors": torch.nn.Parameter(torch.zeros(len(init["xyz"]), 3, device=dev)),
        }
    )
    opts = {k: torch.optim.Adam([{"params": params[k], "lr": LR[k], "name": k}], eps=1e-15) for k in params}
    pose = torch.zeros(len(views), 6, device=dev, requires_grad=p.pose_refine)
    pose_opt = torch.optim.Adam([pose], lr=POSE_LR) if p.pose_refine else None
    max_rad, max_m = math.radians(p.pose_max_deg), p.pose_max_m
    strategy = DefaultStrategy(refine_stop_iter=p.iterations // 2, reset_every=3000, verbose=False)
    strategy.check_sanity(params, opts)
    state = strategy.initialize_state(scene_scale=SCENE_SCALE_M)

    def render(i, with_pose=True):
        d = data[i]
        c2w = d["c2w"]
        if p.pose_refine and with_pose:
            c2w = c2w @ _delta_matrix(torch, pose[i])
        w, h = d["size"]
        out, _alpha, info = rasterization(
            params["means"],
            params["quats"],
            torch.exp(params["scales"]),
            torch.sigmoid(params["opacities"]),
            torch.sigmoid(params["colors"]),
            torch.linalg.inv(c2w)[None],
            d["K"][None],
            w,
            h,
            render_mode="RGB+ED",
            packed=False,
        )
        return out[0, ..., :3], out[0, ..., 3], info

    rng = np.random.default_rng(p.seed)
    t0 = time.perf_counter()
    losses = []
    capped_at = None
    for step in range(p.iterations):
        i = train_ids[int(rng.integers(len(train_ids)))]
        d = data[i]
        rgb, depth, info = render(i)
        strategy.step_pre_backward(params, opts, state, step, info)
        gt = d["img"].float() / 255
        ok = d["ok"]
        l1 = ((rgb - gt).abs().mean(-1) * ok).sum() / ok.sum().clamp(min=1)
        ssim = _ssim_map(torch, rgb.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None])[0, 0]
        loss = (1 - SSIM_WEIGHT) * l1 + SSIM_WEIGHT * (1 - (ssim * ok).sum() / ok.sum().clamp(min=1))
        if p.depth_weight > 0:
            m = (d["depth"] > 0) & ok
            if m.any():
                loss = loss + p.depth_weight * ((depth - d["depth"]).abs() / d["depth"].clamp(min=1))[m].mean()
        loss.backward()
        strategy.step_post_backward(params, opts, state, step, info, packed=False)
        for o in opts.values():
            o.step()
            o.zero_grad(set_to_none=True)
        if pose_opt is not None:
            pose_opt.step()
            pose_opt.zero_grad(set_to_none=True)
            with torch.no_grad():
                pose[:, :3].clamp_(-max_rad, max_rad)
                pose[:, 3:].clamp_(-max_m, max_m)
        if capped_at is None and len(params["means"]) >= p.max_gaussians:
            strategy.refine_stop_iter = step  # no more growth; the cap keeps VRAM inside the budget
            capped_at = step
        if step % log_every == 0:
            losses.append((step, round(float(loss), 4), len(params["means"])))
            log.info("splats step %d loss %.4f n %d", step, float(loss), len(params["means"]))
    torch.cuda.synchronize()
    seconds_train = time.perf_counter() - t0

    # Held-out views, dataset pose.
    psnr, ssim_l, depth_err = [], [], []
    with torch.no_grad():
        for i in held:
            rgb, depth, _ = render(i, with_pose=False)
            rgb = rgb.clamp(0, 1)
            d = data[i]
            gt = d["img"].float() / 255
            ok = d["ok"]
            if ok.sum() == 0:
                continue
            mse = (((rgb - gt) ** 2).mean(-1) * ok).sum() / ok.sum()
            psnr.append(float(-10 * torch.log10(mse.clamp(min=1e-10))))
            sm = _ssim_map(torch, rgb.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None])[0, 0]
            ssim_l.append(float((sm * ok).sum() / ok.sum()))
            m = (d["depth"] > 0) & ok
            if m.any():
                depth_err.append(float((depth - d["depth"]).abs()[m].median()))
    return {
        "splats": {k: v.detach().cpu().numpy() for k, v in params.items()},
        "pose": pose.detach().cpu().numpy(),
        "pose_train_ids": train_ids,
        "held_ids": held,
        "psnr": psnr,
        "ssim": ssim_l,
        "depth_median_err_m": depth_err,
        "seconds_train": seconds_train,
        "losses": losses,
        "capped_at_step": capped_at,
        "peak_vram_mib": round(torch.cuda.max_memory_allocated() / 2**20),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 2**20),
    }


def render_ortho(splats: dict, surface: dict, ground_z: np.ndarray, p: SplatsParams, origin: np.ndarray):
    """(rgba uint8 (h, w, 4), (x0, y_top)): the ground layer seen from above, one pixel = ortho_cm.

    Only splats within ground_band_m of the lidar ground surface are drawn; pixels the splats do not cover are transparent.
    """
    import torch
    from gsplat import rasterization

    pix = p.ortho_cm / 100
    means = splats["means"]
    sel = np.isfinite(ground_z) & (np.abs(means[:, 2] + origin[2] - ground_z) <= p.ground_band_m)
    sel &= 1 / (1 + np.exp(-splats["opacities"])) >= OPACITY_MIN
    # The picture covers the lidar's observed ground; stray splats outside it are not drawn.
    c = float(surface["cell_m"])
    j, i = np.nonzero(surface["count"] > 0)
    lo = surface["origin"] + np.array([i.min(), j.min()]) * c
    hi = surface["origin"] + np.array([i.max() + 1, j.max() + 1]) * c
    sel &= (means[:, :2] + origin[:2] >= lo).all(1) & (means[:, :2] + origin[:2] <= hi).all(1)
    tiles, (width, height) = ortho_tiles(lo, hi, pix)
    top = hi[1]
    dev = "cuda"
    t = {k: torch.from_numpy(v[sel]).to(dev) for k, v in splats.items()}
    z_cam = float(means[sel, 2].max() + 10)
    rgba = np.zeros((height, width, 4), np.uint8)
    for c0, r0, w, h in tiles:
        # Camera looks down: x east, y south (image down), z down. Pixel (u, v) of this tile is world
        # x = lo_x + (c0 + u) * pix, y = top - (r0 + v) * pix.
        cx = lo[0] + (c0 + w / 2) * pix - origin[0]
        cy = top - (r0 + h / 2) * pix - origin[1]
        c2w = np.array([[1, 0, 0, cx], [0, -1, 0, cy], [0, 0, -1, z_cam], [0, 0, 0, 1]], np.float32)
        k = np.array([[1 / pix, 0, w / 2], [0, 1 / pix, h / 2], [0, 0, 1]], np.float32)
        with torch.no_grad():
            img, alpha, _ = rasterization(
                t["means"],
                t["quats"],
                torch.exp(t["scales"]),
                torch.sigmoid(t["opacities"]),
                torch.sigmoid(t["colors"]),
                torch.from_numpy(np.linalg.inv(c2w))[None].to(dev),
                torch.from_numpy(k)[None].to(dev),
                w,
                h,
                near_plane=0.01,
                far_plane=1000.0,
                camera_model="ortho",
                render_mode="RGB",
            )
        rgba[r0 : r0 + h, c0 : c0 + w, :3] = (img[0].clamp(0, 1) * 255).byte().cpu().numpy()
        rgba[r0 : r0 + h, c0 : c0 + w, 3] = np.where((alpha[0, ..., 0] > 0.3).cpu().numpy(), 255, 0)
    return rgba, (float(lo[0]), float(top))


# ------------------------------------------------------------------ the stage


@register("splats", "gsplat-lidar")
def run(ctx: Any, params: SplatsParams) -> StageResult:
    out: Path = ctx.stage_dir("splats")
    out.mkdir(exist_ok=True)
    gdir = ctx.input_dir("ground")
    ground, nonground = laspy.read(gdir / "ground.laz").xyz, laspy.read(gdir / "nonground.laz").xyz
    pts = np.vstack([ground, nonground])
    sf = np.load(gdir / "surface.npz")
    surface = {k: sf[k] for k in sf.files}
    origin = np.round(pts.mean(0), 0)
    t0 = time.perf_counter()
    views = _load_views(ctx, params, origin, pts)
    seconds_prepare = time.perf_counter() - t0
    init = initial_splats(ground - origin, nonground - origin, params.init_points, params.seed)
    res = train(views, init, params)
    sp = res["splats"]

    centres = sp["means"] + origin
    opaque = 1 / (1 + np.exp(-sp["opacities"])) >= OPACITY_MIN
    geom = geometry_agreement(centres[opaque], surface)
    rgba, (x0, ytop) = render_ortho(sp, surface, ground_z_at(surface, centres[:, :2]), params, origin)
    Image.fromarray(rgba, "RGBA").save(out / "ortho.png")
    pix = params.ortho_cm / 100
    (out / "ortho.pgw").write_text("\n".join(f"{v:.6f}" for v in [pix, 0.0, 0.0, -pix, x0 + pix / 2, ytop - pix / 2]) + "\n")

    np.savez_compressed(
        out / "splats.npz",
        means=sp["means"].astype(np.float32),
        scales_log=sp["scales"].astype(np.float16),
        quats=sp["quats"].astype(np.float16),
        opacity_logit=sp["opacities"].astype(np.float16),
        colour_logit=sp["colors"].astype(np.float16),
        origin=origin,
    )
    names = [views[i]["channel"] for i in res["pose_train_ids"]]
    corr = res["pose"][res["pose_train_ids"]]
    qa = {
        "method": "gsplat-lidar",
        "rendering_only": True,
        "licences": LICENCES,
        "n_images": len(views),
        "n_train": len(res["pose_train_ids"]),
        "n_held_out": len(res["held_ids"]),
        "image_px": list(views[0]["size"]),
        "n_init_points": len(init["xyz"]),
        "n_splats": len(sp["means"]),
        "n_splats_opaque": int(opaque.sum()),
        "capped_at_step": res["capped_at_step"],
        "heldout_psnr_db": round(float(np.mean(res["psnr"])), 3),
        "heldout_ssim": round(float(np.mean(res["ssim"])), 4),
        "heldout_psnr_by_image": [round(v, 2) for v in res["psnr"]],
        "heldout_depth_median_abs_err_m": round(float(np.mean(res["depth_median_err_m"])), 3) if res["depth_median_err_m"] else None,
        "scoring_note": "pixels under annotated boxes are excluded; held-out images use the dataset pose",
        "geometry_vs_lidar_ground": geom,
        "pose_corrections": pose_report(corr, names, params),
        "ortho": {"cm_per_px": params.ortho_cm, "size_px": [rgba.shape[1], rgba.shape[0]], "layer": f"splats within {params.ground_band_m} m of the lidar ground"},
        "seconds_prepare": round(seconds_prepare, 1),
        "seconds_train": round(res["seconds_train"], 1),
        "gpu_minutes_train": round(res["seconds_train"] / 60, 2),
        "peak_vram_allocated_mib": res["peak_vram_mib"],
        "peak_vram_reserved_mib": res["peak_reserved_mib"],
        "vram_budget_mib": VRAM_BUDGET_MIB,
        "loss_log": res["losses"],
        "output_bytes": sum((out / f).stat().st_size for f in ("splats.npz", "ortho.png", "ortho.pgw")),
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=qa, message="rendering only")
