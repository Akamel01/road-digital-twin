"""Stage 7 profile (centreline): ground z along each road centreline, every `profile.sample_m`.

Source of truth: docs/design/twin-v1-spec.md, sections 3, 4, 6 (Outputs) and 8 (Profile).
Prior work: docs/research/related-work.md section 6 (vertical profile from mobile lidar: holgado-barco-2014,
which uses orthogonal regression on the road profile; we only sample the ground surface, descriptive).
Input: ground's surface.npz and qa.json; load's facilities.geojson. Output: profile.csv, centrelines.geojson.
Descriptive only (spec R1). Heights are written even when height_valid is false; metrics carry the flag.
"""

from __future__ import annotations

import json
from itertools import combinations
from typing import Any

import numpy as np
from shapely.geometry import LineString, mapping, shape

from twin.contracts import ProfileParams, StageResult
from twin.facilities import fallback_centreline
from twin.registry import register

CSV_HEADER = "facility,line,s_m,z_m,n"
OUTPUT_FILES = ("profile.csv", "centrelines.geojson")
CRS_EPSG = 32619
# DECISION: two intersection legs form a through line when their outward directions differ by at least this.
PAIR_MIN_DEG = 150.0
# DECISION: 8-way compass, clockwise from north. A line's label starts at the end with the lower index.
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _octant(v: np.ndarray) -> int:
    """8-way compass index of a vector (x east, y north)."""
    bearing = np.degrees(np.arctan2(v[0], v[1])) % 360.0
    return round(bearing / 45.0) % 8


def _angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def intersection_lines(
    core_centre: np.ndarray, legs: list[LineString]
) -> list[tuple[str, LineString]]:
    """Through lines (two legs whose far ends are nearly opposite, joined across the core) and one line
    per unpaired leg (from the core centre outward). Each leg starts at the core edge.

    # DECISION: pairing is greedy, most opposite pair first. A leg is used once.
    """
    dirs = [np.asarray(lg.coords[-1]) - core_centre for lg in legs]
    cand = sorted(
        (
            (_angle_deg(dirs[i], dirs[j]), i, j)
            for i, j in combinations(range(len(legs)), 2)
        ),
        key=lambda t: -t[0],
    )
    used: set[int] = set()
    pairs = []
    for ang, i, j in cand:
        if ang < PAIR_MIN_DEG:
            break
        if i in used or j in used:
            continue
        used |= {i, j}
        pairs.append((i, j))

    raw: list[tuple[list[tuple[float, float]], bool]] = []  # (coords, is_through)
    for i, j in pairs:
        # far end of leg i -> core edge of leg i -> (straight across the core) -> core edge of j -> far end of j
        coords = list(reversed(legs[i].coords)) + list(legs[j].coords)
        raw.append(([tuple(c[:2]) for c in coords], True))
    for k in range(len(legs)):
        if k not in used:
            coords = [tuple(core_centre)] + list(legs[k].coords)
            raw.append(([tuple(c[:2]) for c in coords], False))

    out: list[tuple[str, LineString]] = []
    taken: set[str] = set()
    for coords, through in raw:
        far_a = np.asarray(coords[0]) - core_centre
        far_b = np.asarray(coords[-1]) - core_centre
        if through:
            if _octant(far_b) < _octant(far_a):
                coords = coords[::-1]
                far_a, far_b = far_b, far_a
            label = f"{COMPASS[_octant(far_a)]}-{COMPASS[_octant(far_b)]}"
        else:
            label = COMPASS[_octant(far_b)]
        base, n = label, 2
        while label in taken:  # two lines with the same label in one facility
            label = f"{base}-{n}"
            n += 1
        taken.add(label)
        out.append((label, LineString(coords)))
    return out


def facility_lines(feature: dict) -> list[tuple[str, LineString]]:
    """(label, line) per road line of a facility. Intersections use their legs; segments their stored
    centreline; access points the core midline. All labelled 'main' unless an intersection has legs."""
    props = feature["properties"]
    core = shape(feature["geometry"])
    if props.get("type") == "intersection" and props.get("legs"):
        legs = [shape(leg["geometry"]) for leg in props["legs"]]
        return intersection_lines(np.asarray(core.centroid.coords[0]), legs)
    if "centreline" in props:
        return [("main", shape(props["centreline"]))]
    return [("main", fallback_centreline(core))]


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
        profiled.append(fid)
        for label, line in facility_lines(feature):
            line_id = f"{fid}/{label}"
            lines.append(
                {
                    "type": "Feature",
                    "geometry": mapping(line),
                    "properties": {"facility": fid, "line": line_id, "label": label},
                }
            )
            for s, x, y in sample_line(line, params.sample_m):
                hit = ground_z_at(surf, x, y)
                if hit is not None:
                    rows.append(f"{fid},{line_id},{s:.1f},{hit[0]:.3f},{hit[1]}")

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
        "lines": len(lines),
        "not_scanned_enough": not_scanned,
        "samples": len(rows) - 1,
    }
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=metrics)


@register("profile", "centreline")
def run_centreline(ctx: Any, params: ProfileParams) -> StageResult:
    return _run(ctx, params)
