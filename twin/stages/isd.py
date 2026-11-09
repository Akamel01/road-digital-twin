"""Stage 8 isd (aashto-b): AASHTO Case B sight distance, left and right, from each intersection approach.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (ISD) and 8 (ISD).
Prior work: docs/research/sight-line-heights.md (heights; ISD Case B passenger car 1.08 m eye and 1.08 m object)
and docs/research/related-work.md sections 6 and 9 (gonzalez-gomez-2019, kilani-2021: no open code, nothing reused).
Inputs: load's facilities.geojson (approach lines and eye points); ground's surface.npz, nonground.laz and qa.json;
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
# DECISION: the object point moves along the crossing approach in 0.5 m steps (the surface cell size), from the
# required distance down. The available distance is the farthest step whose sight line is clear.
SEARCH_STEP_M = 0.5
# DECISION: operator, 2026-11-09: the crossing approaches for a side are those whose outward bearing differs from
# the viewer's by 45 to 135 degrees. If a side has several, the one nearest 90 degrees is used.
CROSS_MIN_DEG = 45.0
CROSS_MAX_DEG = 135.0
# DECISION: a leg's status is the worse of its sides: indeterminate, then short, then ok.
RANK = {"ok": 0, "short": 1, "indeterminate": 2}
SIDES = ("left", "right")
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


def _near(xyz: np.ndarray, pts: np.ndarray, band: float) -> np.ndarray:
    """Points in the plan box around pts, widened by band. A point that can block a sight line lies within band of
    the triangle of its eye, the crossing approach's start and its far object, so the box keeps every such point."""
    lo = pts.min(axis=0) - band
    hi = pts.max(axis=0) + band
    keep = np.all((xyz[:, :2] >= lo) & (xyz[:, :2] <= hi), axis=1)
    return xyz[keep]


def _outward(line, centre: np.ndarray) -> np.ndarray:
    """Plan vector from the core centre out along an approach, to its far end."""
    return np.asarray(line.coords[-1], dtype=float)[:2] - centre


def _crossings(
    viewer: str, lines: dict[str, Any], centre: np.ndarray
) -> dict[str, str]:
    """Side ('left' or 'right') -> crossing approach, for the driver on the viewer approach facing into the core.

    Left and right are seen from that driver: facing f = -outward, right is (f_y, -f_x).
    """
    v = _outward(lines[viewer], centre)
    f = -v
    right = np.array([f[1], -f[0]])
    best: dict[str, tuple[float, str]] = {}
    for name, line in lines.items():
        if name == viewer or np.allclose(line.coords[0], line.coords[-1]):
            continue
        c = _outward(line, centre)
        cos = float(v @ c / (np.linalg.norm(v) * np.linalg.norm(c)))
        ang = float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
        if not CROSS_MIN_DEG <= ang <= CROSS_MAX_DEG:
            continue
        side = "right" if float(c @ right) > 0 else "left"
        dev = abs(ang - 90.0)
        if side not in best or dev < best[side][0]:
            best[side] = (dev, name)
    return {side: name for side, (_, name) in best.items()}


def _side_available(
    surface: Surface,
    eye: np.ndarray,
    start: np.ndarray,
    u: np.ndarray,
    required: float,
    nonground: np.ndarray,
    parked: np.ndarray | None,
    params: IsdParams,
    height_valid: bool,
) -> tuple[float | None, str]:
    """Farthest object position on the crossing approach still visible, and the reason.

    The object sits at distance d from the crossing approach's start (its core edge) along u. Returns (None, reason)
    when the required sight line is indeterminate (coverage gap or invalid heights).
    """

    def test(d: float):
        return sight_line(
            eye,
            start + d * u,
            surface=surface,
            nonground_xyz=nonground,
            params=params,
            height_valid=height_valid,
            parked_xyz=parked,
        )

    full = test(required)
    if full.status == INDETERMINATE:
        return None, full.reason
    if full.status == CLEAR:
        return required, full.reason
    for d in np.arange(required - SEARCH_STEP_M, 0.0, -SEARCH_STEP_M):
        if test(float(d)).status == CLEAR:
            return float(d), full.reason
    return 0.0, "no object point on the crossing approach is visible"


def _viewer_leg(
    name: str,
    eye: np.ndarray,
    lines: dict[str, Any],
    centre: np.ndarray,
    surface: Surface,
    nonground: np.ndarray,
    parked_all: np.ndarray,
    params: IsdParams,
    height_valid: bool,
    required: float,
) -> dict[str, Any]:
    band = params.band_m
    crossings = _crossings(name, lines, centre)
    out: dict[str, Any] = {
        "leg": name,
        "required_m": round(required, 2),
        "left": None,
        "right": None,
    }
    statuses, reasons = [], []
    for side in SIDES:
        cname = crossings.get(side)
        if cname is None:
            reasons.append(f"{side}: no crossing approach")
            continue
        cline = lines[cname]
        start = np.asarray(cline.coords[0], dtype=float)[:2]
        end = np.asarray(cline.coords[-1], dtype=float)[:2]
        u = (end - start) / np.linalg.norm(end - start)
        pts = np.array([eye, start, start + required * u])
        ng = _near(nonground, pts, band)
        pk = _near(parked_all, pts, band)
        without, why = _side_available(
            surface, eye, start, u, required, ng, None, params, height_valid
        )
        with_, _ = (
            (None, why)
            if without is None
            else _side_available(
                surface, eye, start, u, required, ng, pk, params, height_valid
            )
        )
        if without is None or with_ is None:
            side_out = {
                "leg": cname,
                "available_m": None,
                "available_with_parked_m": None,
                "status": INDETERMINATE,
            }
            reasons.append(f"{side} {cname}: {why}")
        else:
            status = "ok" if without >= required else "short"
            side_out = {
                "leg": cname,
                "available_m": round(without, 2),
                "available_with_parked_m": round(with_, 2),
                "status": status,
            }
            reasons.append(f"{side} {cname}: with parked vehicles {with_:.1f} m")
        out[side] = side_out
        statuses.append(side_out["status"])
    out["status"] = max(statuses, key=RANK.__getitem__) if statuses else INDETERMINATE
    out["reason"] = "; ".join(reasons)
    return out


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
        centre = np.asarray(shape(feature["geometry"]).centroid.coords[0], dtype=float)
        lines = {
            leg["approach"]: shape(leg["geometry"]) for leg in props.get("legs", [])
        }
        eyes = {
            e["approach"]: shape(e["geometry"]) for e in props.get("eye_points", [])
        }
        legs = []
        for name in lines:
            eye_pt = eyes.get(name)
            if eye_pt is None:
                legs.append(
                    {
                        "leg": name,
                        "required_m": round(required, 2),
                        "left": None,
                        "right": None,
                        "status": INDETERMINATE,
                        "reason": "no eye point",
                    }
                )
                continue
            legs.append(
                _viewer_leg(
                    name,
                    np.array([eye_pt.x, eye_pt.y], dtype=float),
                    lines,
                    centre,
                    surface,
                    nonground,
                    parked_all,
                    params,
                    height_valid,
                    required,
                )
            )
        facs.append({"facility": fid, "legs": legs})

    doc = {"case": params.case, "facilities": facs, "not_scanned_enough": not_scanned}
    (out / "isd.json").write_text(json.dumps(doc, indent=2))
    metrics = {
        # The viewer reads the per-leg results from the manifest (web/lib/runmetrics.ts), so they ride along.
        "case": params.case,
        "facilities": facs,
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
