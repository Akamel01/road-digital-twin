"""Stage 8 isd (aashto-b): AASHTO Case B sight distance per intersection leg, without and with parked vehicles.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (ISD) and 8 (ISD).
Prior work: docs/research/sight-line-heights.md (heights; ISD Case B passenger car 1.08 m eye and 1.08 m object)
and docs/research/related-work.md sections 6 and 9 (gonzalez-gomez-2019, kilani-2021: no open code, nothing reused).
Inputs: load's facilities.geojson (leg lines and eye points); ground's surface.npz, nonground.laz and qa.json;
mask's parked.npz; align's poses.json and load's poses.json (to move parked points into the aligned frame).
Output: isd.json. Access points are listed in metrics only: load stores no exit geometry for them yet.
"""

from __future__ import annotations

import json
from typing import Any

import laspy
import numpy as np
from shapely.geometry import shape

from twin.contracts import IsdParams, StageResult
from twin.facilities import isd_required_m
from twin.registry import register
from twin.sightline import CLEAR, INDETERMINATE, Surface, sight_line
from twin.stages.ground import aligned_points

OUTPUT_FILES = ("isd.json",)
# DECISION: the object point moves along the leg in 0.5 m steps (the surface cell size) from the required distance
# back to 0.5 m. The available distance is the farthest step whose sight line is clear.
SEARCH_STEP_M = 0.5
# DECISION: a leg is judged on the without-parked result (as in the fake run). The with-parked result is reported.
PARKED_FIELDS = ("x", "y", "z", "intensity", "sweep")


def _parked_xyz(mask_dir, align_dir, load_dir) -> np.ndarray:
    """Parked-vehicle points in the aligned frame, same as ground's points."""
    with np.load(mask_dir / "parked.npz") as f:
        fields = {k: f[k] for k in PARKED_FIELDS}
    if len(fields["x"]) == 0:
        return np.empty((0, 3))
    ref = np.array(
        [
            p["matrix"]
            for p in json.loads((load_dir / "poses.json").read_text())["poses"]
        ],
        dtype=float,
    ).reshape(-1, 4, 4)
    refined = np.array(
        [
            p["matrix"]
            for p in json.loads((align_dir / "poses.json").read_text())["poses"]
        ],
        dtype=float,
    ).reshape(-1, 4, 4)
    xyz, _, _ = aligned_points(fields, ref, refined)
    return xyz


def _corridor(
    xyz: np.ndarray, a: np.ndarray, u: np.ndarray, length: float, band: float
) -> np.ndarray:
    """Points that can block any sight line from a along u up to length. Exact: a 3D point within band of a
    segment is within band of it in plan, so points outside this strip cannot block."""
    rel = xyz[:, :2] - a
    t = rel @ u
    d = np.abs(rel[:, 0] * u[1] - rel[:, 1] * u[0])
    keep = (t >= -band) & (t <= length + band) & (d <= band)
    return xyz[keep]


def _available(
    surface: Surface,
    a: np.ndarray,
    u: np.ndarray,
    required: float,
    nonground: np.ndarray,
    parked: np.ndarray | None,
    params: IsdParams,
    height_valid: bool,
) -> tuple[float | None, str]:
    """Farthest object point along the leg still visible, in steps of SEARCH_STEP_M, and the reason.

    Returns (None, reason) when the required sight line is indeterminate (coverage gap or invalid heights).
    """

    def test(d: float):
        return sight_line(
            a,
            a + d * u,
            surface=surface,
            nonground_xyz=nonground,
            params=params,
            height_valid=height_valid,
            parked_xyz=parked,
        )

    full = test(required)
    if full.status == INDETERMINATE:
        return None, full.reason
    for d in np.arange(required, 0.0, -SEARCH_STEP_M):
        if test(float(d)).status == CLEAR:
            return float(d), full.reason
    return 0.0, "no object point along the leg is visible"


def _leg(
    surface: Surface,
    eye: np.ndarray,
    far: np.ndarray,
    required: float,
    nonground: np.ndarray,
    parked_all: np.ndarray,
    params: IsdParams,
    height_valid: bool,
) -> dict[str, Any]:
    band = params.band_m
    u = far - eye
    length = float(np.linalg.norm(u))
    if length == 0.0:
        return {
            "status": INDETERMINATE,
            "reason": "leg has no direction (eye at its far end)",
        }
    u = u / length
    ng = _corridor(nonground, eye, u, required, band)
    pk = _corridor(parked_all, eye, u, required, band)
    without, reason = _available(
        surface, eye, u, required, ng, None, params, height_valid
    )
    with_, _ = _available(surface, eye, u, required, ng, pk, params, height_valid)
    if without is None or with_ is None:
        return {
            "status": INDETERMINATE,
            "reason": reason,
            "available_m": None,
            "available_with_parked_m": None,
        }
    status = "ok" if without >= required else "short"
    return {
        "status": status,
        "reason": f"with parked vehicles {with_:.1f} m",
        "available_m": round(without, 2),
        "available_with_parked_m": round(with_, 2),
    }


def _run(ctx: Any, params: IsdParams) -> StageResult:
    out = ctx.stage_dir("isd")
    out.mkdir(exist_ok=True)
    ground = ctx.input_dir("ground")
    load = ctx.input_dir("load")
    qa = json.loads((ground / "qa.json").read_text())
    height_valid = bool(qa["height_valid"])
    observed = qa["observed_core"]
    with np.load(ground / "surface.npz") as f:
        surface = Surface(
            z=f["z"], count=f["count"], origin=f["origin"], cell_m=float(f["cell_m"])
        )
    nonground = np.asarray(laspy.read(ground / "nonground.laz").xyz, dtype=float)
    parked_all = _parked_xyz(ctx.input_dir("mask"), ctx.input_dir("align"), load)
    features = json.loads((load / "facilities.geojson").read_text())["features"]

    required = isd_required_m(params)
    facs, checked, not_scanned, access = [], [], [], []
    for feature in features:
        props = feature["properties"]
        fid = props["id"]
        if props.get("type") == "access_point":
            access.append(fid)
            continue
        if props.get("type") != "intersection":
            continue
        if observed.get(fid, 0.0) < ctx.min_observed:
            not_scanned.append(fid)
            continue
        checked.append(fid)
        eyes = {
            e["approach"]: shape(e["geometry"]) for e in props.get("eye_points", [])
        }
        legs = []
        for leg in props.get("legs", []):
            name = leg["approach"]
            eye_pt = eyes.get(name)
            if eye_pt is None:
                legs.append(
                    {
                        "leg": name,
                        "required_m": round(required, 2),
                        "status": INDETERMINATE,
                        "reason": "no eye point",
                        "available_m": None,
                        "available_with_parked_m": None,
                    }
                )
                continue
            line = shape(leg["geometry"])
            res = _leg(
                surface,
                np.array([eye_pt.x, eye_pt.y]),
                np.asarray(line.coords[-1], dtype=float)[:2],
                required,
                nonground,
                parked_all,
                params,
                height_valid,
            )
            legs.append({"leg": name, "required_m": round(required, 2), **res})
        facs.append({"facility": fid, "legs": legs})

    doc = {"case": params.case, "facilities": facs, "not_scanned_enough": not_scanned}
    (out / "isd.json").write_text(json.dumps(doc, indent=2))
    metrics = {
        "height_valid": height_valid,
        "required_m": round(required, 2),
        "facilities_checked": checked,
        "not_scanned_enough": not_scanned,
        "access_points_without_exit_geometry": access,
        "legs": sum(len(f["legs"]) for f in facs),
    }
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=metrics)


@register("isd", "aashto-b")
def run_aashto_b(ctx: Any, params: IsdParams) -> StageResult:
    return _run(ctx, params)
