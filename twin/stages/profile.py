"""Stage 7 profile (centreline): ground z along each facility's centreline every `profile.sample_m`.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (Outputs) and 8 (Profile).
Prior work: docs/research/related-work.md section 6 (vertical profile from mobile lidar: holgado-barco-2014,
which uses orthogonal regression on the road profile; we only sample the ground surface, descriptive).
Input: ground's surface.npz and qa.json; load's facilities.geojson. Output: profile.csv, centrelines.geojson.
Descriptive only (spec R1). With height_valid false, profile.csv has its header and no heights.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from shapely.geometry import LineString, mapping, shape

from twin.contracts import ProfileParams, StageResult
from twin.facilities import _fallback_centreline
from twin.registry import register

CSV_HEADER = "facility,s_m,z_m,n"
OUTPUT_FILES = ("profile.csv", "centrelines.geojson")
CRS_EPSG = 32619


def centreline_of(feature: dict) -> LineString:
    """The facility's own centreline when it has one (segments), else the midline of its core.

    # DECISION: intersections and access points have no stored centreline; their centreline is the
    # rectangle midline of the core (facilities._fallback_centreline). The spec does not say how to pick one.
    """
    props = feature["properties"]
    if "centreline" in props:
        return shape(props["centreline"])
    return _fallback_centreline(shape(feature["geometry"]))


def sample_line(line: LineString, step_m: float) -> list[tuple[float, float, float]]:
    """(s, x, y) every step_m along the line, plus the end point."""
    length = line.length
    s_vals = np.append(np.arange(0.0, length, step_m), length)
    return [(float(s), p.x, p.y) for s, p in ((s, line.interpolate(s)) for s in s_vals)]


def ground_z_at(surf: dict[str, Any], x: float, y: float) -> tuple[float, int] | None:
    """(z, n) of the surface cell holding (x, y), or None outside the grid or in an empty cell.

    # DECISION: nearest cell, no interpolation. The surface cell size (ground.qa_cell_m) caps the z resolution.
    """
    ny, nx = surf["z"].shape
    cell = float(surf["cell_m"])
    ox, oy = surf["origin"]
    i = int(np.floor((x - ox) / cell))
    j = int(np.floor((y - oy) / cell))
    if not (0 <= i < nx and 0 <= j < ny):
        return None
    n = int(surf["count"][j, i])
    z = float(surf["z"][j, i])
    if n == 0 or not np.isfinite(z):
        return None
    return z, n


def _run(ctx: Any, params: ProfileParams) -> StageResult:
    out = ctx.stage_dir("profile")
    out.mkdir(exist_ok=True)
    ground = ctx.input_dir("ground")
    qa = json.loads((ground / "qa.json").read_text())
    height_valid = bool(qa["height_valid"])
    observed = qa["observed_core"]
    with np.load(ground / "surface.npz") as f:
        surf = {k: f[k] for k in ("z", "count", "origin", "cell_m")}
    features = json.loads((ctx.input_dir("load") / "facilities.geojson").read_text())[
        "features"
    ]

    rows = [CSV_HEADER]
    lines = []
    profiled, not_scanned = [], []
    for feature in features:
        fid = feature["properties"]["id"]
        if observed.get(fid, 0.0) < ctx.min_observed:
            not_scanned.append(fid)
            continue
        line = centreline_of(feature)
        profiled.append(fid)
        lines.append(
            {
                "type": "Feature",
                "geometry": mapping(line),
                "properties": {"facility": fid},
            }
        )
        if not height_valid:
            continue  # indeterminate (height): no heights are written
        for s, x, y in sample_line(line, params.sample_m):
            hit = ground_z_at(surf, x, y)
            if hit is not None:
                rows.append(f"{fid},{s:.1f},{hit[0]:.3f},{hit[1]}")

    (out / "profile.csv").write_text("\n".join(rows) + "\n")
    centrelines = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"EPSG:{CRS_EPSG}"}},
        "features": lines,
    }
    (out / "centrelines.geojson").write_text(json.dumps(centrelines))
    metrics = {
        "height_valid": height_valid,
        "facilities_profiled": profiled,
        "not_scanned_enough": not_scanned,
        "samples": len(rows) - 1,
    }
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=metrics)


@register("profile", "centreline")
def run_centreline(ctx: Any, params: ProfileParams) -> StageResult:
    return _run(ctx, params)
