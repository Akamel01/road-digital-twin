"""Stage 11 semantics (mapillary-m2f): camera paint and curb classes projected onto the lidar ground.

Source of truth: docs/decisions/0006-camera-lidar-fusion.md (Q2a, Q4, Q5); ticket #178.
A Mapillary Vistas segmenter labels every camera image. Each lidar ground point that the z-buffer
(twin.stages.zbuffer, the colour stage's visibility test) says a camera sees takes the label at its pixel.
Labels are voted per ground cell across images. Paint and curb probability rasters and the features
extracted from them come out, plus the Q5 variants: lidar-only (features stage as is), camera-only, and fused.
Inputs: load's cameras.json, boxes.json, reference.geojson; align's poses.json; ground's ground.laz,
nonground.laz, surface.npz; features' three geojson files and qa.json.
The model is research-only (Mapillary Vistas is CC BY-NC-SA 4.0): the stage's metrics say so, so the manifest does.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import laspy
import numpy as np
import shapely
from PIL import Image
from shapely.geometry import mapping, shape

from twin.contracts import AccuracyParams, ColourParams, SemanticsParams, StageResult
from twin.registry import register
from twin.stages import accuracy, colour, features, zbuffer
from twin.stages.load import DATAROOT_DEFAULT

log = logging.getLogger(__name__)
OUTPUT_FILES = ("prob.npz", "prob.pgw", "paint_prob.png", "curb_prob.png", "qa.json")
KINDS = ("markings.geojson", "crosswalks.geojson", "curbs.geojson")

# Our classes. Everything else is 0.
MARKING, CROSSWALK, CURB, SIGN, SIGNAL = 1, 2, 3, 4, 5
# DECISION: Vistas has no stop-line class (a stop line is "Lane Marking - General"), so stop lines come out as
# markings and the features' marking typing (map stop_line layer) names them. "Crosswalk - Plain" is a crosswalk
# without stripes, so it joins the crosswalk class. "Curb Cut" is a ramp, not a curb, and stays out.
VISTAS_CLASSES = {
    "Lane Marking - General": MARKING,
    "Lane Marking - Crosswalk": CROSSWALK,
    "Crosswalk - Plain": CROSSWALK,
    "Curb": CURB,
    "Traffic Sign (Front)": SIGN,
    "Traffic Light": SIGNAL,
}
MODEL_NAME = "mask2former-swin-large-mapillary-vistas-semantic"
MODEL_REPO = "facebook/" + MODEL_NAME
LICENCES = {
    "model": MODEL_REPO,
    "code": "Mask2Former: MIT (Swin and Deformable-DETR parts: MIT and Apache-2.0); transformers: Apache-2.0",
    "weights": "Hugging Face card says 'other' (no terms stated); trained on Mapillary Vistas, CC BY-NC-SA 4.0",
    "dataset": "CC BY-NC-SA 4.0",
}

# DECISION: sign and signal pixels are counted, not projected: they are not on the ground (ticket item 3 projects
# paint and curb only).
# DECISION: fixed extraction constants, as in the features stage. Clusters of cells: lines need LINE_MIN_LEN_M
# (features), crosswalk polygons need CROSS_MIN_M2 after closing gaps of CROSS_CLOSE_M.
EPS_M = 0.3
MIN_CELLS = 5
CROSS_CLOSE_M = 0.3
CROSS_MIN_M2 = 2.0
# DECISION: a camera feature is added to the fused set when under half its length (area) lies within ADD_M of a
# lidar feature of the same family.
ADD_M = 0.5
ADD_MAX_SHARE = 0.5
SAMPLE_M = 0.25


# ------------------------------------------------------------------ segmenter


class Mask2Former:
    """Mask2Former Swin-L, Mapillary Vistas semantic, from a local folder (the weights live under /data/models).

    Called with an RGB uint8 image (H, W, 3); returns a (H, W) uint8 map of our class codes.
    """

    def __init__(self, path: Path, long_side_px: int):
        import torch
        from transformers import Mask2FormerForUniversalSegmentation

        self.torch, self.long_side = torch, long_side_px
        self.model = (
            Mask2FormerForUniversalSegmentation.from_pretrained(path)
            .half()
            .cuda()
            .eval()
        )
        lut = np.zeros(len(self.model.config.id2label), np.uint8)
        for i, name in self.model.config.id2label.items():
            lut[int(i)] = VISTAS_CLASSES.get(name, 0)
        self.lut = torch.from_numpy(lut).cuda()
        # Normalisation from the checkpoint's preprocessor_config.json.
        self.mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1).cuda()
        self.std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1).cuda()

    def __call__(self, img: np.ndarray) -> np.ndarray:
        torch = self.torch
        F = torch.nn.functional
        h, w = img.shape[:2]
        s = self.long_side / max(h, w)
        size = (max(32, round(h * s / 32) * 32), max(32, round(w * s / 32) * 32))
        with torch.inference_mode():
            x = torch.from_numpy(img).cuda().permute(2, 0, 1)[None].float() / 255
            x = F.interpolate(x, size, mode="bilinear", align_corners=False)
            out = self.model(pixel_values=((x - self.mean) / self.std).half())
            # Semantic map = sum over queries of class probability times mask probability (the HF recipe).
            cls = out.class_queries_logits.float().softmax(-1)[..., :-1]
            seg = torch.einsum(
                "bqc,bqhw->bchw", cls, out.masks_queries_logits.float().sigmoid()
            )
            seg = F.interpolate(seg, (h, w), mode="bilinear", align_corners=False)
            return self.lut[seg.argmax(1)[0].long()].cpu().numpy()


# ------------------------------------------------------------------ projection and voting


def _visible(gpu, targets, nonground, boxes, c2w, K, size, cp):
    """zbuffer.visible on the GPU when colour's rules allow it (None gpu: the CPU). Returns (mask, gpu)."""
    if gpu is not None:
        xp, g_t, g_n = gpu
        try:
            return xp.asnumpy(
                zbuffer.visible(g_t, g_n, boxes, c2w, K, size, cp, xp)
            ), gpu
        except (
            RuntimeError,
            MemoryError,
        ) as exc:  # out of memory or another CUDA error: CPU from here on
            log.warning(
                "semantics: GPU failed (%s: %s), continuing on the CPU",
                type(exc).__name__,
                exc,
            )
            xp.get_default_memory_pool().free_all_blocks()
    return zbuffer.visible(targets, nonground, boxes, c2w, K, size, cp), None


def vote(
    targets: np.ndarray,
    nonground: np.ndarray,
    views,
    segment: Callable[[np.ndarray], np.ndarray],
    cell_m: float,
    cp: ColourParams | None = None,
    stats: dict | None = None,
) -> dict:
    """Per ground cell: how many target points were seen, in how many images, and how many got each class.

    targets (N, 3) are the points to label; nonground and the per-view boxes are the occluders (as in colour).
    views yields (cam_to_world, K, image, boxes). segment maps an image to (H, W) class codes.
    Returns arrays over a grid of cell_m cells: seen, images, marking, crosswalk, curb (all per cell, flat),
    z (mean target height per cell, NaN where empty) and the grid (origin, cell_m, nx, ny).
    """
    cp = cp or ColourParams()
    origin = targets[:, :2].min(axis=0)
    ij = np.floor((targets[:, :2] - origin) / cell_m).astype(np.int64)
    nx, ny = int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1
    flat = ij[:, 1] * nx + ij[:, 0]
    n = nx * ny
    zn = np.bincount(flat, minlength=n)
    z = np.bincount(flat, weights=targets[:, 2], minlength=n) / np.maximum(zn, 1)
    z[zn == 0] = np.nan
    r = {
        k: np.zeros(n, np.int32)
        for k in ("seen", "images", "marking", "crosswalk", "curb")
    }
    st = stats if stats is not None else {}
    st.update(
        n_images=0,
        n_images_seen=0,
        seconds_segment=0.0,
        seconds_project=0.0,
        sign_px=0,
        signal_px=0,
    )
    gpu = colour._to_gpu(targets, nonground, cp)
    for c2w, K, img, boxes in views:
        h, w = img.shape[:2]
        t0 = time.perf_counter()
        codes = segment(img)
        t1 = time.perf_counter()
        vis, gpu = _visible(gpu, targets, nonground, boxes, c2w, K, (w, h), cp)
        st["n_images"] += 1
        st["sign_px"] += int((codes == SIGN).sum())
        st["signal_px"] += int((codes == SIGNAL).sum())
        idx = np.flatnonzero(vis)
        if idx.size:
            uv, _ = zbuffer.project(targets[idx], c2w, K)
            code = codes[
                np.clip(np.floor(uv[:, 1]).astype(np.int64), 0, h - 1),
                np.clip(np.floor(uv[:, 0]).astype(np.int64), 0, w - 1),
            ]
            cell = flat[idx]
            seen = np.bincount(cell, minlength=n)
            r["seen"] += seen
            r["images"] += seen > 0
            for name, k in (
                ("marking", MARKING),
                ("crosswalk", CROSSWALK),
                ("curb", CURB),
            ):
                r[name] += np.bincount(cell[code == k], minlength=n)
            st["n_images_seen"] += 1
        st["seconds_segment"] += t1 - t0
        st["seconds_project"] += time.perf_counter() - t1
    st["device"] = "cpu" if gpu is None else "gpu"
    if gpu is not None:
        gpu[0].get_default_memory_pool().free_all_blocks()
    return {**r, "z": z, "origin": origin, "cell_m": cell_m, "nx": nx, "ny": ny}


def probability(r: dict, name: str) -> np.ndarray:
    """Share of the seen points of each cell labelled `name` (marking, crosswalk, curb, or paint = both)."""
    votes = r["marking"] + r["crosswalk"] if name == "paint" else r[name]
    return votes / np.maximum(r["seen"], 1)


def _on(r: dict, name: str, p: SemanticsParams) -> np.ndarray:
    """Cells that count as `name`: seen in enough images, with probability at least min_prob."""
    return (r["images"] >= p.min_images) & (probability(r, name) >= p.min_prob)


# ------------------------------------------------------------------ features from the rasters


def _centres(r: dict, cells: np.ndarray) -> np.ndarray:
    ix, iy = cells % r["nx"], cells // r["nx"]
    xy = r["origin"] + (np.column_stack([ix, iy]) + 0.5) * r["cell_m"]
    return np.column_stack([xy, r["z"][cells]])


def _evidence(r: dict, cells: np.ndarray, name: str) -> dict:
    """Images and votes behind a feature: median images per cell, labelled points, mean probability."""
    votes = (
        r["marking"][cells] + r["crosswalk"][cells]
        if name == "paint"
        else r[name][cells]
    )
    return {
        "source": "camera",
        "evidence": ["camera"],
        "n_cells": len(cells),
        "n_images": int(np.median(r["images"][cells])),
        "votes": int(votes.sum()),
        "prob_mean": round(float((votes / np.maximum(r["seen"][cells], 1)).mean()), 3),
    }


def camera_lines(r: dict, name: str, kind: str, p: SemanticsParams) -> list[dict]:
    """LineString features from the cells of class `name`: cluster the cell centres, bin along the axis."""
    cells = np.flatnonzero(_on(r, name, p))
    if len(cells) < MIN_CELLS:
        return []
    xyz = _centres(r, cells)
    labels = features.cluster_xy(xyz[:, :2], EPS_M, MIN_CELLS)
    out: list[dict] = []
    for lab in np.unique(labels[labels >= 0]):
        sel = labels == lab
        c, u = features._axis(xyz[sel, :2])
        t = (xyz[sel, :2] - c) @ u
        if t.max() - t.min() < features.LINE_MIN_LEN_M:
            continue
        for verts, _n in features.binned_pieces(xyz[sel], c, u):
            length = float(np.hypot(*np.diff(verts[:, :2], axis=0).T).sum())
            if length > 0:
                out.append(
                    features._feature(
                        kind,
                        f"{kind}-cam-{len(out) + 1:04d}",
                        "LineString",
                        [[float(v) for v in vert] for vert in verts],
                        {
                            "length_m": round(length, 3),
                            **_evidence(r, cells[sel], name),
                        },
                    )
                )
    return out


def camera_crosswalks(r: dict, p: SemanticsParams) -> list[dict]:
    """Polygon features from crosswalk cells: the cell squares with gaps up to CROSS_CLOSE_M closed."""
    cells = np.flatnonzero(_on(r, "crosswalk", p))
    if not len(cells):
        return []
    xyz, h = _centres(r, cells), r["cell_m"] / 2
    squares = shapely.box(xyz[:, 0] - h, xyz[:, 1] - h, xyz[:, 0] + h, xyz[:, 1] + h)
    merged = shapely.union_all(squares).buffer(CROSS_CLOSE_M).buffer(-CROSS_CLOSE_M)
    out: list[dict] = []
    for poly in getattr(merged, "geoms", [merged]):
        if poly.is_empty or poly.area < CROSS_MIN_M2:
            continue
        inside = cells[shapely.contains_xy(poly, xyz[:, 0], xyz[:, 1])]
        if not len(inside):
            continue
        out.append(
            features._feature(
                "crosswalk",
                f"crosswalk-cam-{len(out) + 1:04d}",
                "Polygon",
                features._lift(
                    mapping(poly)["coordinates"], float(np.nanmean(r["z"][inside]))
                ),
                {
                    "area_m2": round(float(poly.area), 3),
                    **_evidence(r, inside, "crosswalk"),
                },
            )
        )
    return out


# ------------------------------------------------------------------ fusion


def _dilate(mask: np.ndarray, n: int) -> np.ndarray:
    """mask with every True grown to a disc of n cells."""
    out = np.zeros_like(mask)
    ny, nx = mask.shape
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            if dx * dx + dy * dy <= n * n:
                out[max(dy, 0) : ny + min(dy, 0), max(dx, 0) : nx + min(dx, 0)] |= mask[
                    max(-dy, 0) : ny + min(-dy, 0), max(-dx, 0) : nx + min(-dx, 0)
                ]
    return out


def _samples(geom: Any) -> np.ndarray:
    g = shapely.force_2d(geom)
    g = g.boundary if g.geom_type in ("Polygon", "MultiPolygon") else g
    return shapely.get_coordinates(shapely.segmentize(g, SAMPLE_M))


def fuse(
    lidar: list[dict], r: dict, name: str, p: SemanticsParams
) -> tuple[list[dict], dict]:
    """Keep a lidar feature only where camera votes of class `name` support it.

    Samples along the feature are looked up in the grid. Fewer than half of them seen in min_images images
    means the cameras did not observe it: it is kept and says so (DECISION: dropping on no camera view would punish
    ground no camera saw). Otherwise it is kept when at least support_share of the observed samples lie within
    support_radius_m of a cell of class `name`, and dropped when not. Returns (kept, counts).
    """
    ny, nx, cell = r["ny"], r["nx"], r["cell_m"]
    seen = (r["images"] >= p.min_images).reshape(ny, nx)
    sup = _dilate(
        _on(r, name, p).reshape(ny, nx), int(np.ceil(p.support_radius_m / cell))
    )
    kept, counts = [], {"supported": 0, "not_observed": 0, "dropped": 0}
    for f in lidar:
        s = _samples(shape(f["geometry"]))
        i = np.floor((s - r["origin"]) / cell).astype(np.int64)
        ok = (i >= 0).all(axis=1) & (i[:, 0] < nx) & (i[:, 1] < ny)
        obs = np.zeros(len(s), bool)
        obs[ok] = seen[i[ok, 1], i[ok, 0]]
        props = f["properties"]
        if obs.mean() < 0.5:
            counts["not_observed"] += 1
            props["evidence"] = [*props["evidence"], "camera: not observed"]
            props["source"] = "lidar"
        else:
            share = float(sup[i[obs, 1], i[obs, 0]].mean())
            if share < p.support_share:
                counts["dropped"] += 1
                continue
            counts["supported"] += 1
            props["evidence"] = [*props["evidence"], "camera"]
            props["camera_support"] = round(share, 3)
            props["source"] = "lidar+camera"
        kept.append(f)
    return kept, counts


def _new_only(cam: list[dict], lidar: list[dict]) -> list[dict]:
    """Camera features with under ADD_MAX_SHARE of their size within ADD_M of any lidar feature."""
    if not lidar:
        return list(cam)
    near = shapely.union_all(
        [shapely.force_2d(shape(f["geometry"])) for f in lidar]
    ).buffer(ADD_M)
    out = []
    for f in cam:
        g = shapely.force_2d(shape(f["geometry"]))
        size = g.area if g.geom_type == "Polygon" else g.length
        if (
            g.intersection(near).area
            if g.geom_type == "Polygon"
            else g.intersection(near).length
        ) < ADD_MAX_SHARE * size:
            out.append(f)
    return out


def build_variants(
    lidar: dict[str, list[dict]], r: dict, reference: list[dict], p: SemanticsParams
):
    """(camera, fused, counts): per file name, the camera-only and fused feature lists.

    lidar: the features stage's lists by file name. Paint features (markings, crosswalks) are checked against
    paint cells (marking or crosswalk class), curbs against curb cells. Camera features that no lidar feature
    explains are added to the fused set, flagged source "camera".
    """
    camera = {
        "markings.geojson": camera_lines(r, "marking", "marking", p),
        "crosswalks.geojson": camera_crosswalks(r, p),
        "curbs.geojson": camera_lines(r, "curb", "curb", p),
    }
    features.type_markings(camera["markings.geojson"], reference)
    channel = {
        "markings.geojson": "paint",
        "crosswalks.geojson": "paint",
        "curbs.geojson": "curb",
    }
    # A camera marking inside a lidar crosswalk is a stripe the lidar already has.
    explained = {
        "markings.geojson": lidar["markings.geojson"] + lidar["crosswalks.geojson"],
        "crosswalks.geojson": lidar["crosswalks.geojson"],
        "curbs.geojson": lidar["curbs.geojson"],
    }
    fused, counts = {}, {}
    for kind in KINDS:
        kept, c = fuse(lidar[kind], r, channel[kind], p)
        added = _new_only(camera[kind], explained[kind])
        fused[kind] = kept + added
        counts[kind] = {
            **c,
            "n_lidar": len(lidar[kind]),
            "n_camera": len(camera[kind]),
            "added_camera": len(added),
        }
    return camera, fused, counts


# ------------------------------------------------------------------ outputs


def variant_accuracy(
    features_dir: Path, load_dir: Path, out_dir: Path, params: AccuracyParams
) -> dict:
    """The accuracy stage's document for the features in features_dir (accuracy.json lands in out_dir)."""
    ctx = SimpleNamespace(
        stage_dir=lambda _n: out_dir,
        input_dir=lambda s: features_dir if s == "features" else load_dir,
    )
    return accuracy.run_one_way(ctx, params).metrics


def _raster_png(r: dict, name: str, path: Path, min_images: int) -> None:
    p = np.round(probability(r, name) * 255).astype(np.uint8)
    alpha = np.where(r["images"] >= min_images, 255, 0).astype(np.uint8)
    la = np.stack([p, alpha], axis=-1).reshape(r["ny"], r["nx"], 2)
    Image.fromarray(la[::-1], "LA").save(
        path
    )  # row 0 is the north edge, as in the orthoimage


def _write_pgw(r: dict, path: Path) -> None:
    c = r["cell_m"]
    ul = [r["origin"][0] + c / 2, r["origin"][1] + r["ny"] * c - c / 2]
    path.write_text("\n".join(f"{v:.6f}" for v in [c, 0.0, 0.0, -c, *ul]) + "\n")


def _fc(feats: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": feats})


def write_variants(out: Path, camera: dict, fused: dict, features_dir: Path) -> None:
    for name, sets in (("camera", camera), ("fused", fused)):
        d = out / "variants" / name
        d.mkdir(parents=True, exist_ok=True)
        for kind in KINDS:
            (d / kind).write_text(_fc(sets[kind]))
        shutil.copy(
            features_dir / "qa.json", d / "qa.json"
        )  # accuracy reads not_scanned_enough from it


def _gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return int(out.split()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def model_dir() -> Path:
    return Path(os.environ.get("TWIN_MODELS", "/data/models")) / MODEL_NAME


@register("semantics", "mapillary-m2f")
def run(ctx: Any, params: SemanticsParams) -> StageResult:
    return run_with(ctx, params, Mask2Former(model_dir(), params.long_side_px))


def run_with(
    ctx: Any, params: SemanticsParams, segment: Callable[[np.ndarray], np.ndarray]
) -> StageResult:
    """The stage with any segmenter (tests pass a stub)."""
    out: Path = ctx.stage_dir("semantics")
    out.mkdir(exist_ok=True)
    gdir, fdir, ldir = (
        ctx.input_dir("ground"),
        ctx.input_dir("features"),
        ctx.input_dir("load"),
    )
    ground = laspy.read(gdir / "ground.laz").xyz
    nonground = laspy.read(gdir / "nonground.laz").xyz
    # Targets: the ground plus the non-ground points at curb height (features' curbs use the same set).
    near = features._near_ground_nonground(gdir, 0.25 + features.CURB_ABOVE_SLACK_M)
    targets = np.vstack([ground, near])

    align_rows = json.loads((ctx.input_dir("align") / "poses.json").read_text())[
        "poses"
    ]
    ego = np.array([row["matrix"] for row in align_rows], float).reshape(-1, 4, 4)
    times = np.array([row["timestamp_us"] for row in align_rows], np.int64)
    cams = json.loads((ldir / "cameras.json").read_text())["cameras"]
    sweep_boxes = json.loads((ldir / "boxes.json").read_text())["sweeps"]
    usable = [
        c for c in cams if times[0] <= c["timestamp_us"] <= times[-1]
    ]  # as in colour
    root = Path(os.environ.get("NUSCENES_ROOT", DATAROOT_DEFAULT))

    def views():
        for cam in usable:
            t = int(cam["timestamp_us"])
            c2w = zbuffer.camera_to_world(ego, times, t, cam["extrinsics"])
            img = np.asarray(Image.open(root / cam["image"]).convert("RGB"))
            yield (
                c2w,
                np.asarray(cam["intrinsics"], float),
                img,
                colour.boxes_at(sweep_boxes, t),
            )

    stats: dict = {}
    t0 = time.perf_counter()
    r = vote(targets, nonground, views(), segment, params.cell_m, ColourParams(), stats)
    peak = {"gpu_used_mib_after": _gpu_used_mib()}
    try:
        import torch

        peak["torch_peak_allocated_mib"] = round(
            torch.cuda.max_memory_allocated() / 2**20
        )
        peak["torch_peak_reserved_mib"] = round(
            torch.cuda.max_memory_reserved() / 2**20
        )
    except (ImportError, RuntimeError):  # no torch (a stub run) or no CUDA
        pass

    lidar = {
        k: json.loads((fdir / k).read_text())["features"]
        if (fdir / k).is_file()
        else []
        for k in KINDS
    }
    reference_path = ldir / "reference.geojson"
    reference = (
        json.loads(reference_path.read_text())["features"]
        if reference_path.is_file()
        else []
    )
    camera, fused, counts = build_variants(lidar, r, reference, params)
    write_variants(out, camera, fused, fdir)

    np.savez_compressed(
        out / "prob.npz",
        **{
            k: r[k]
            for k in ("seen", "images", "marking", "crosswalk", "curb", "z", "origin")
        },
        cell_m=r["cell_m"],
        nx=r["nx"],
        ny=r["ny"],
    )
    _write_pgw(r, out / "prob.pgw")
    _raster_png(r, "paint", out / "paint_prob.png", params.min_images)
    _raster_png(r, "curb", out / "curb_prob.png", params.min_images)

    acc = AccuracyParams()
    variants = {
        "lidar": variant_accuracy(fdir, ldir, out / "variants" / "lidar", acc),
        "camera": variant_accuracy(
            out / "variants" / "camera", ldir, out / "variants" / "camera", acc
        ),
        "fused": variant_accuracy(
            out / "variants" / "fused", ldir, out / "variants" / "fused", acc
        ),
    }
    qa = {
        "method": "mapillary-m2f",
        "research_only": True,
        "licences": LICENCES,
        "classes": VISTAS_CLASSES,
        "cell_m": params.cell_m,
        "n_cameras": len(cams),
        "n_cameras_skipped_outside_sweeps": len(cams) - len(usable),
        "observed_cells": int((r["images"] >= params.min_images).sum()),
        "fusion": counts,
        "seconds_total": round(time.perf_counter() - t0, 2),
        **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in stats.items()},
        **peak,
        "variants": variants,
    }
    (out / "qa.json").write_text(json.dumps(qa, indent=2))
    return StageResult(
        status="ok", files=list(OUTPUT_FILES), metrics=qa, message="research-only"
    )
