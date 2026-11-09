"""Stage 9 accuracy (one-way): distance from each extracted element to the HD map's own geometry.

Source of truth: docs/design/twin-v1-spec.md, sections 4, 6 (Accuracy) and 8.
Prior work: docs/research/multi-sensor-sota.md section 5 (mobile-mapping accuracy is stated against an
independent reference; that section points to ASPRS RMSE against checkpoints, which v1 does not have, so v1
reports P50, P95 and coverage against the map as the spec says). Distance and length use shapely 2, which is
already a dependency; no new method or package is added.
Input: features' markings.geojson, crosswalks.geojson, curbs.geojson (optional) and qa.json; load's
reference.geojson and facilities.geojson. Output: accuracy.json.
Only features with reliability "observed" are scored (operator rule, 2026-11-08).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from twin.contracts import AccuracyParams, StageResult
from twin.registry import register

OUTPUT_FILES = ("accuracy.json",)
# Reference layers per element type (spec section 6, Accuracy).
# Lane markings: lane_divider and road_divider are map lines; road_divider is a median line (weaker reference).
REFERENCE = {
    "markings": ("lane_divider", "road_divider"),
    "crosswalks": ("ped_crossing",),
    "curbs": ("drivable_area",),
}
ELEMENT_FILES = {
    "markings": "markings.geojson",
    "crosswalks": "crosswalks.geojson",
    "curbs": "curbs.geojson",
}
# Curbs are scored against the drivable-area edge, which is the map's drawing choice, so they are labelled.
LABELS = {"curbs": "map-conditioned"}
# DECISION: a feature belongs to a facility when its centroid lies inside the facility's core polygon.
# DECISION: crosswalks are area elements. Each extracted vertex is measured to the ped_crossing POLYGON (0 when
# inside), and coverage is the share of ped_crossing area within buffer_m of the extracted crosswalks. Measuring
# to the outline would score correct inner stripes ~half a crossing width off.
AREA_TYPES = frozenset({"crosswalks"})
# Operator decision (2026-11-08): outlines are densified every DENSIFY_M metres before measuring, so P50 and P95
# are length-weighted and do not depend on how many vertices a shape has.
DENSIFY_M = 0.25


def _read_fc(path: Path) -> list[dict]:
    return json.loads(path.read_text()).get("features", [])


def _geom(feature: dict) -> BaseGeometry:
    return shapely.force_2d(shape(feature["geometry"]))


def _outline(geom: BaseGeometry) -> BaseGeometry:
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom.boundary
    return geom


def _reference(
    features: list[dict], layers: tuple[str, ...], area: bool
) -> BaseGeometry | None:
    """Union of the reference features in these layers, or None when there are none.

    Line references use the outline (boundary) of polygons; area references keep the polygon itself.
    """
    parts = [
        _geom(f) if area else _outline(_geom(f))
        for f in features
        if f["properties"].get("layer") in layers
    ]
    parts = [p for p in parts if not p.is_empty]
    return shapely.union_all(parts) if parts else None


def _observed(features: list[dict]) -> tuple[list[BaseGeometry], int]:
    """Geometries of observed features, and how many were left out as not observed."""
    kept, excluded = [], 0
    for f in features:
        if f["properties"].get("reliability") == "observed":
            kept.append(_geom(f))
        else:
            excluded += 1
    return kept, excluded


def _vertex_distances(elements: list[BaseGeometry], ref: BaseGeometry) -> np.ndarray:
    """One-way distance (m) from points every DENSIFY_M along every element outline to the reference."""
    if not elements:
        return np.empty(0)
    verts = np.vstack(
        [
            shapely.get_coordinates(shapely.segmentize(_outline(g), DENSIFY_M))
            for g in elements
        ]
    )
    return np.asarray(shapely.distance(shapely.points(verts), ref), dtype=float)


def _size(geom: BaseGeometry, area: bool) -> float:
    """Area for area references, length for line references."""
    return float(geom.area if area else geom.length)


def _matched(
    elements: list[BaseGeometry], ref: BaseGeometry, buffer_m: float, area: bool
) -> float:
    """Length (or area) of the reference within buffer_m of any element."""
    if not elements or ref.is_empty:
        return 0.0
    near = shapely.union_all(elements).buffer(buffer_m)
    return _size(ref.intersection(near), area)


def _entry(
    layers: tuple[str, ...] | str,
    dists: np.ndarray,
    matched: float,
    ref_len: float,
    label: str = "",
    reason: str = "",
) -> dict[str, Any]:
    layer_name = ", ".join(layers) if isinstance(layers, tuple) else layers
    if not reason and len(dists) == 0:
        reason = "no observed elements"
    if not reason and ref_len <= 0:
        reason = "no reference in run"
    if reason:
        return {
            "reference_layer": layer_name,
            "p50_m": None,
            "p95_m": None,
            "coverage": None,
            "n": len(dists),
            "label": label,
            "reason": reason,
        }
    return {
        "reference_layer": layer_name,
        "p50_m": round(float(np.percentile(dists, 50)), 3),
        "p95_m": round(float(np.percentile(dists, 95)), 3),
        "coverage": round(min(matched / ref_len, 1.0), 3),
        "n": len(dists),
        "label": label,
        "reason": "",
    }


@register("accuracy", "one-way")
def run_one_way(ctx: Any, params: AccuracyParams) -> StageResult:
    out = ctx.stage_dir("accuracy")
    out.mkdir(exist_ok=True)
    features_dir = ctx.input_dir("features")
    load_dir = ctx.input_dir("load")
    buffer_m = params.buffer_m

    feat_qa = json.loads((features_dir / "qa.json").read_text())
    not_scanned = set(feat_qa.get("not_scanned_enough", []))
    # DECISION: nothing writes markings_extractable yet; select's go/no-go does not reach the run. If a later
    # stage writes false here, markings are reported as "not extractable at this density" (spec section 6).
    markings_extractable = bool(feat_qa.get("markings_extractable", True))

    reference = _read_fc(load_dir / "reference.geojson")
    ref = {
        t: _reference(reference, layers, t in AREA_TYPES)
        for t, layers in REFERENCE.items()
    }

    elements: dict[str, list[BaseGeometry]] = {}
    excluded = 0
    absent: list[str] = []
    for kind, name in ELEMENT_FILES.items():
        path = features_dir / name
        if not path.is_file():
            # Curbs are off in the run (features.curbs.enabled false): skip, no failure.
            absent.append(kind)
            continue
        kept, n_excluded = _observed(_read_fc(path))
        elements[kind] = kept
        excluded += n_excluded

    active = [t for t in elements if not (t == "markings" and not markings_extractable)]

    per_element: dict[str, dict] = {}
    for kind in active:
        geoms = elements[kind]
        r = ref[kind]
        if r is None:
            per_element[kind] = _entry(
                REFERENCE[kind], np.empty(0), 0.0, 0.0, LABELS.get(kind, ""), ""
            )
            continue
        area = kind in AREA_TYPES
        dists = _vertex_distances(geoms, r)
        matched = _matched(geoms, r, buffer_m, area)
        per_element[kind] = _entry(
            REFERENCE[kind], dists, matched, _size(r, area), LABELS.get(kind, "")
        )
    for kind in elements:
        if kind not in active:
            per_element[kind] = _entry(
                REFERENCE[kind],
                np.empty(0),
                0.0,
                0.0,
                LABELS.get(kind, ""),
                "not extractable at this density",
            )

    per_facility: dict[str, dict] = {}
    facilities = _read_fc(load_dir / "facilities.geojson")
    for fac in facilities:
        fid = fac["properties"]["id"]
        core = _geom(fac)
        if fid in not_scanned:
            per_facility[fid] = _entry(
                "", np.empty(0), 0.0, 0.0, "", "not scanned enough"
            )
            continue
        dist_parts: list[np.ndarray] = []
        matched = ref_len = 0.0
        used_layers: list[str] = []
        used_labels: set[str] = set()
        for kind in active:
            r = ref[kind]
            if r is None:
                continue
            members = [g for g in elements[kind] if core.contains(g.centroid)]
            clipped = r.intersection(core)
            if clipped.is_empty:
                continue
            area = kind in AREA_TYPES
            ref_len += _size(clipped, area)
            matched += _matched(members, clipped, buffer_m, area)
            if members:
                dist_parts.append(_vertex_distances(members, r))
                used_layers.extend(REFERENCE[kind])
                if kind in LABELS:
                    used_labels.add(LABELS[kind])
        dists = np.concatenate(dist_parts) if dist_parts else np.empty(0)
        per_facility[fid] = _entry(
            tuple(dict.fromkeys(used_layers)),
            dists,
            matched,
            ref_len,
            ", ".join(sorted(used_labels)),
        )

    doc = {
        "method": "one-way",
        "buffer_m": buffer_m,
        "elements": per_element,
        "facilities": per_facility,
        "qa": {
            "n_observed_only": True,
            "n_excluded_not_observed": excluded,
            "absent_element_files": absent,
            "markings_extractable": markings_extractable,
        },
    }
    (out / "accuracy.json").write_text(json.dumps(doc, indent=2))
    return StageResult(status="ok", files=list(OUTPUT_FILES), metrics=doc)
