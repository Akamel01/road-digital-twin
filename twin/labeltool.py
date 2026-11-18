"""Mapping between the audit tool's surfaces and labelled-site features.

Importing this module must not touch cv2 or FastAPI (P8); raster work lives in
``twin.labelraster`` and is imported lazily by the generator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from twin.contracts import LabelFeature
from twin.labels import read_labels, read_site, valid_site, write_labels

SURFACE_MAP: dict[str, tuple[str, str]] = {
    "lane line, solid white": ("marking", "solid_line"),
    "lane line, dashed white": ("marking", "dashed_line"),
    "lane line, solid yellow": ("marking", "solid_line"),
    "lane line, double yellow": ("marking", "double_line"),
    "stop line": ("marking", "stop_line"),
    "crosswalk, ladder": ("crosswalk", "ladder"),
    "crosswalk, continental": ("crosswalk", "continental"),
    "crosswalk, transverse": ("crosswalk", "transverse"),
    "crosswalk, zebra": ("crosswalk", "zebra"),
    "curb": ("curb", "curb"),
    "edge of pavement": ("marking", "edge_line"),
}

SURFACE_TYPES: tuple[str, ...] = tuple(SURFACE_MAP)


class DraftError(ValueError):
    """Raised when a draft cannot be converted or imported."""


def _is_point(p: Any) -> bool:
    return isinstance(p, (list, tuple)) and len(p) == 2


def surface_to_feature(surface: dict) -> dict:
    if not isinstance(surface, dict):
        raise DraftError("surface must be a dict")
    raw = surface.get("type")
    if not raw or raw not in SURFACE_MAP:
        raise DraftError(f"unknown surface type: {raw!r}")
    sid = surface.get("id")
    if not sid:
        raise DraftError("surface missing id")
    xy = surface.get("xy")
    if not isinstance(xy, (list, tuple)) or not xy:
        raise DraftError("surface missing xy")
    if not all(_is_point(p) for p in xy):
        raise DraftError("surface xy contains invalid points")
    by = surface.get("by")
    if by is not None and by != "operator":
        raise DraftError(f"surface by must be 'operator', got {by!r}")

    element, typ = SURFACE_MAP[raw]
    is_poly = surface.get("geom") == "polygon" or element == "crosswalk"

    if is_poly:
        if len(xy) < 3:
            raise DraftError("polygon needs at least 3 points")
        coords = [list(p) for p in xy]
        if coords and coords[0] != coords[-1]:
            coords = coords + [list(coords[0])]
    else:
        if len(xy) < 2:
            raise DraftError("line needs at least 2 points")
        coords = [list(p) for p in xy]

    geometry = (
        {"type": "Polygon", "coordinates": [coords]}
        if is_poly
        else {"type": "LineString", "coordinates": coords}
    )

    props = {k: surface[k] for k in LabelFeature.model_fields if k in surface}
    props["id"] = sid
    props["element"] = element
    props["type"] = typ
    props["origin"] = "operator"
    props["source_marking_type"] = raw
    props["evidence"] = surface.get("evidence")

    LabelFeature.model_validate(props)

    return {"type": "Feature", "geometry": geometry, "properties": props}


def import_draft(store: Path, site: str, draft_path, *, replace: bool = False) -> int:
    store = Path(store)
    if not valid_site(site):
        raise DraftError(f"bad site id: {site!r}")
    path = Path(draft_path)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise DraftError(f"cannot read draft: {exc}") from exc
    if not isinstance(data, dict):
        raise DraftError("draft must be a JSON object")

    if data.get("set") != site:
        raise DraftError(
            f"draft set {data.get('set')!r} does not match site {site!r}"
        )

    if "surfaces" in data:
        surfaces = data["surfaces"]
    elif "surface_features" in data:
        surfaces = data["surface_features"]
    else:
        raise DraftError("draft has no surfaces")
    if not isinstance(surfaces, list):
        raise DraftError("surfaces must be a list")
    if not surfaces:
        raise DraftError("draft has no surfaces")

    supports = data.get("supports") or []
    devices = data.get("devices") or []
    if supports:
        raise DraftError("draft supports must be empty")
    if devices:
        raise DraftError("draft devices must be empty")

    meta = read_site(store, site)

    if replace:
        existing: list[dict] = []
    else:
        existing = list(read_labels(store, site).get("features", []))

    index_by_id = {f.get("properties", {}).get("id"): i for i, f in enumerate(existing)}

    for surface in surfaces:
        feature = surface_to_feature(surface)
        pid = feature["properties"]["id"]
        if pid in index_by_id:
            existing[index_by_id[pid]] = feature
        else:
            existing.append(feature)
            index_by_id[pid] = len(existing) - 1

    write_labels(
        store,
        site,
        {"type": "FeatureCollection", "features": existing},
        expected_version=meta.version,
    )
    return len(surfaces)
