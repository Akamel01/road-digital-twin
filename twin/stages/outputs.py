"""Stage 10 outputs: twin.laz and twin.geojson.

Source of truth: docs/design/twin-v1-spec.md, sections 4 and 6.
TODO (ticket 10b): plan.dxf, plan.pdf, profile.dxf, profile.pdf (method dxf-pdf).
"""

import json
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import pyproj

from twin.contracts import StageResult
from twin.registry import register

CRS_EPSG = 32619
LICENCE = "Derived from nuScenes (CC BY-NC-SA 4.0). Non-commercial research demo."
SCALE_M = 0.001
GROUND_CLASS = 2
UNASSIGNED_CLASS = 1
FEATURE_LAYERS = ("markings", "crosswalks", "curbs")  # curbs may be absent


def _ground_points(ctx: Any) -> tuple[np.ndarray, np.ndarray]:
    """Ground points first, then non-ground. Returns (xyz, classification)."""
    gdir = ctx.input_dir("ground")
    parts, classes = [], []
    if (gdir / "ground.laz").is_file():
        ground = laspy.read(gdir / "ground.laz")
        parts.append(ground.xyz)
        classes.append(np.full(len(ground.x), GROUND_CLASS, np.uint8))
    elif (gdir / "surface.npz").is_file():
        # Fallback when the LAZ is missing. Assumes the grid cells were saved as x, y, z arrays.
        with np.load(gdir / "surface.npz") as surf:
            if not {"x", "y", "z"} <= set(surf.files):
                raise ValueError(
                    "surface.npz has no x, y, z arrays; cannot place ground"
                )
            xyz = np.column_stack([surf["x"], surf["y"], surf["z"]])
        parts.append(xyz)
        classes.append(np.full(len(xyz), GROUND_CLASS, np.uint8))
    else:
        raise FileNotFoundError("ground stage has neither ground.laz nor surface.npz")
    if (gdir / "nonground.laz").is_file():
        non = laspy.read(gdir / "nonground.laz")
        parts.append(non.xyz)
        classes.append(np.full(len(non.x), UNASSIGNED_CLASS, np.uint8))
    xyz = np.vstack(parts) if parts else np.zeros((0, 3))
    return xyz, np.concatenate(classes) if classes else np.zeros(0, np.uint8)


def _rgb(ctx: Any, n: int) -> np.ndarray | None:
    """Per-point uint16 RGB aligned with the points, or None when colour did not run."""
    if not ctx.stage_dir("colour").is_dir():
        return None
    with np.load(ctx.input_dir("colour") / "rgb.npz") as f:
        rgb = np.asarray(f["rgb"])
        observed = np.asarray(f["observed"], dtype=bool)
    if len(rgb) != n or len(observed) != n:
        raise ValueError(f"rgb.npz has {len(rgb)} points, ground stage has {n}")
    if rgb.dtype == np.uint8:
        rgb = rgb.astype(np.uint16) * 257  # 8-bit to 16-bit, as LAS stores it
    rgb = rgb.astype(np.uint16)
    rgb[~observed] = 0  # unobserved stays uncoloured, never filled
    return rgb


def _write_laz(
    path: Path, xyz: np.ndarray, classes: np.ndarray, rgb: np.ndarray | None
) -> None:
    header = laspy.LasHeader(point_format=7 if rgb is not None else 6, version="1.4")
    header.scales = np.array([SCALE_M] * 3)
    header.offsets = xyz.min(axis=0) if len(xyz) else np.zeros(3)
    header.add_crs(pyproj.CRS.from_epsg(CRS_EPSG))
    header.vlrs.append(
        laspy.VLR(
            user_id="twin",
            record_id=1,
            description="licence",
            record_data=LICENCE.encode(),
        )
    )
    las = laspy.LasData(header)
    las.xyz = xyz
    las.classification = classes
    if rgb is not None:
        las.red, las.green, las.blue = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    las.write(path)


def _features(ctx: Any) -> list[dict]:
    """Markings, crosswalks, curbs and facilities, each tagged with its layer."""
    fdir = ctx.input_dir("features")
    sources = [(layer, fdir / f"{layer}.geojson") for layer in FEATURE_LAYERS]
    sources.append(("facilities", ctx.stage_dir("load") / "facilities.geojson"))
    features = []
    for layer, path in sources:
        if not path.is_file():
            if layer in ("curbs", "facilities"):
                continue  # curbs off, or no facilities file
            raise FileNotFoundError(path)
        for feat in json.loads(path.read_text())["features"]:
            props = dict(feat.get("properties") or {})
            props["layer"] = layer
            features.append({**feat, "properties": props})
    return features


@register("outputs", "dxf-pdf")
def run(ctx: Any, params: Any) -> StageResult:
    out = ctx.stage_dir("outputs")
    out.mkdir(exist_ok=True)

    xyz, classes = _ground_points(ctx)
    _write_laz(out / "twin.laz", xyz, classes, _rgb(ctx, len(xyz)))

    features = _features(ctx)
    doc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"EPSG:{CRS_EPSG}"}},
        "licence": LICENCE,
        "features": features,
    }
    (out / "twin.geojson").write_text(json.dumps(doc))

    return StageResult(
        status="ok",
        files=["twin.laz", "twin.geojson"],
        metrics={"n_points": len(xyz), "n_features": len(features)},
    )
