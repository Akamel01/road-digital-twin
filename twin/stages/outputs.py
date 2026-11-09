"""Stage 10 outputs: twin.laz, twin.geojson, plan and profile sheets (DXF and PDF).

Source of truth: docs/design/twin-v1-spec.md, sections 4, 6 and 8.
Sheet drawing lives in twin/drawings.py.
"""

import csv
import json
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import pyproj
from shapely.geometry import shape

from twin import drawings
from twin.contracts import StageResult
from twin.registry import register

CRS_EPSG = 32619
LICENCE = "Derived from nuScenes (CC BY-NC-SA 4.0). Non-commercial research demo."
SHEET_LICENCE = (
    "Derived from nuScenes (CC BY-NC-SA 4.0). Street names \u00a9 OpenStreetMap "
    "contributors (ODbL). Non-commercial research demo."
)
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

    files = ["twin.laz", "twin.geojson"]
    _sheets(ctx, features, files)

    return StageResult(
        status="ok",
        files=files,
        metrics={"n_points": len(xyz), "n_features": len(features)},
    )


def _polylines(geom: dict) -> list[list[tuple[float, float]]]:
    """2D polylines of a Polygon, MultiPolygon, LineString or MultiLineString.

    Each polygon ring (exterior and holes) and each line becomes one polyline.
    """
    g = shape(geom)
    out = []
    for part in getattr(g, "geoms", [g]):
        rings = (
            [part.exterior, *part.interiors] if part.geom_type == "Polygon" else [part]
        )
        for ring in rings:
            out.append([(float(c[0]), float(c[1])) for c in ring.coords])
    return out


def _plan_inputs(ctx: Any, features: list[dict]) -> tuple[dict, list, list]:
    lines: dict[str, list] = {"MARKINGS": [], "CROSSWALKS": []}
    if (ctx.input_dir("features") / "curbs.geojson").is_file():
        lines["CURBS"] = []
    labels = []
    facilities = {}
    for feat in features:
        props = feat["properties"]
        layer = props["layer"]
        polys = _polylines(feat["geometry"])
        lines.setdefault(layer.upper(), []).extend(polys)
        if layer == "facilities":
            facilities[props.get("id")] = props
            pts = polys[0]  # outer ring of the facility, as before
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            labels.append((str(props.get("id", "")), (cx, cy)))
    return lines, labels, _sightlines(ctx, facilities)


def _sightlines(ctx: Any, facilities: dict) -> list:
    """Sight lines: from each leg's eye point, one line per side (left, right) to its crossing approach, ending
    at available_m along that approach from its core edge (clipped to the approach)."""
    path = ctx.stage_dir("isd") / "isd.json"
    if not path.is_file():
        return []
    out = []
    for fac in json.loads(path.read_text()).get("facilities", []):
        props = facilities.get(fac["facility"]) or {}
        lines = {
            leg["approach"]: shape(leg["geometry"]) for leg in props.get("legs", [])
        }
        eyes = {
            e["approach"]: shape(e["geometry"]) for e in props.get("eye_points", [])
        }
        for leg in fac["legs"]:
            name = leg["leg"]
            eye = eyes.get(name)
            if eye is None:
                continue
            eye_xy = (eye.x, eye.y)
            views = [
                (side, leg[side])
                for side in ("left", "right")
                if leg.get(side) is not None
            ]
            if not views and leg["status"] == "indeterminate":
                out.append((eye_xy, None, False, f"{name}: indeterminate"))
            for side, view in views:
                if view["status"] == "indeterminate" or view["available_m"] is None:
                    out.append((eye_xy, None, False, f"{name} {side}: indeterminate"))
                    continue
                cross = lines.get(view["leg"])
                if cross is None:
                    continue
                end = cross.interpolate(min(float(view["available_m"]), cross.length))
                text = f"{name} {side}: {view['available_m']:.1f} m (need {leg['required_m']:.1f} m)"
                out.append((eye_xy, (end.x, end.y), view["status"] == "short", text))
    return out


def _profile_inputs(ctx: Any) -> list:
    """(line id, s_m, z_m) per road line, from profile/profile.csv. One block per line."""
    rows: dict[str, tuple[list, list]] = {}
    with (ctx.stage_dir("profile") / "profile.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            s_list, z_list = rows.setdefault(row["line"], ([], []))
            s_list.append(float(row["s_m"]))
            z_list.append(float(row["z_m"]))
    return [(line, s_list, z_list) for line, (s_list, z_list) in rows.items()]


def _height_valid(ctx: Any) -> bool:
    qa = ctx.stage_dir("ground") / "qa.json"
    if not qa.is_file():
        return False  # no evidence of valid heights; show indeterminate
    return bool(json.loads(qa.read_text()).get("height_valid", False))


def _sheets(ctx: Any, features: list[dict], files: list[str]) -> None:
    out = ctx.stage_dir("outputs")
    source = (
        f"Source: nuScenes v1.0-mini, scene {ctx.scene_token}; run {ctx.run_dir.name}"
    )
    lines, labels, sight = _plan_inputs(ctx, features)
    drawings.write_plan(
        out / "plan.dxf",
        lines=lines,
        labels=labels,
        sight=sight,
        source=source,
        licence=SHEET_LICENCE,
    )
    drawings.render_pdf(out / "plan.dxf", out / "plan.pdf")
    files += ["plan.dxf", "plan.pdf"]

    if not (ctx.stage_dir("profile") / "profile.csv").is_file():
        return
    drawings.write_profile(
        out / "profile.dxf",
        profiles=_profile_inputs(ctx),
        height_valid=_height_valid(ctx),
        source=source,
        licence=SHEET_LICENCE,
    )
    drawings.render_pdf(out / "profile.dxf", out / "profile.pdf")
    files += ["profile.dxf", "profile.pdf"]
