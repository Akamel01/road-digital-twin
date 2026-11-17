"""Store I/O, draft mapping, approval and versioning for labelled sites.

A labelled site lives at ``<store>/labels/<site>/`` and holds:
  site.json          - a SiteMeta
  labels.geojson     - a GeoJSON FeatureCollection of LabelFeature properties
  labels.v{N}.geojson - frozen snapshots taken on approve / new-version
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from twin.contracts import LabelFeature, SiteMeta
from twin.site import resolve_area

FEATURE_FILES = ("markings.geojson", "crosswalks.geojson", "curbs.geojson", "ramps.geojson")

_ELEMENT_BY_FILE = {
    "markings.geojson": "marking",
    "crosswalks.geojson": "crosswalk",
    "curbs.geojson": "curb",
    "ramps.geojson": "curb_ramp",
}
_TYPE_DEFAULT = {
    "marking": "solid_line",
    "crosswalk": "zebra",
    "curb": "curb",
    "curb_ramp": "curb_ramp",
}
_RAMP_FIELDS = (
    "kind",
    "width_m",
    "run_length_m",
    "running_slope_pct",
    "cross_slope_pct",
    "flare_slope_pct",
    "gutter_step_m",
    "running_slope_status",
    "cross_slope_status",
    "flare_slope_status",
    "gutter_step_status",
    "status",
    "nearest_crosswalk_m",
    "crosswalk_id",
    "n_points",
)


class FrozenSiteError(RuntimeError):
    """Raised when an edit is attempted on a frozen site."""


def labels_dir(store: Path | str, site: str) -> Path:
    return Path(store) / "labels" / site


def site_path(store: Path | str, site: str) -> Path:
    return labels_dir(store, site) / "site.json"


def labels_path(store: Path | str, site: str) -> Path:
    return labels_dir(store, site) / "labels.geojson"


def snapshot_path(store: Path | str, site: str, version: int) -> Path:
    return labels_dir(store, site) / f"labels.v{version}.geojson"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_site(store: Path | str, site: str) -> SiteMeta:
    return SiteMeta.model_validate_json(site_path(store, site).read_text())


def read_labels(store: Path | str, site: str) -> dict:
    p = labels_path(store, site)
    if not p.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(p.read_text())


def write_site(store: Path | str, site: str, meta: SiteMeta) -> None:
    d = labels_dir(store, site)
    d.mkdir(parents=True, exist_ok=True)
    site_path(store, site).write_text(meta.model_dump_json(indent=2) + "\n")


def _area_build_dir(store: Path, area: str) -> Path:
    # area may be a name or a path; reuse resolve_area when possible.
    try:
        return resolve_area(Path(store), area)
    except Exception:
        p = Path(area)
        if p.is_dir():
            return p
        cand = Path(store) / "areas" / area
        if cand.is_dir():
            return cand
        raise


def _area_def(store: Path, area: str, build_dir: Path) -> dict:
    name = build_dir.name.removesuffix("-twin").removesuffix("-merged")
    for cand in (Path(store) / "areas" / f"{name}.json", Path(area)):
        if cand.is_file():
            try:
                return json.loads(cand.read_text())
            except (OSError, ValueError):
                pass
    # fall back: search next to build dir
    for cand in build_dir.parent.glob("*.json"):
        try:
            d = json.loads(cand.read_text())
            if isinstance(d, dict) and "polygon" in d:
                return d
        except (OSError, ValueError):
            continue
    raise FileNotFoundError(f"area def for {area!r} not found")


def _map_feature(element: str, feat: dict, source_file: str, idx: int) -> dict:
    props = dict(feat.get("properties") or {})
    fid = props.get("id")
    if fid is None:
        fid = f"{source_file}:{idx}"
    label = LabelFeature(
        id=str(fid),
        element=element,  # type: ignore[arg-type]
        type=_TYPE_DEFAULT[element],  # type: ignore[arg-type]
        origin="drafted",
        source_feature_id=str(props.get("id")) if props.get("id") is not None else None,
        source_file=source_file,
        source_marking_type=props.get("marking_type") if props.get("marking_type") is not None else (props.get("type") if isinstance(props.get("type"), str) else None),
        height_m=props.get("height_m") if isinstance(props.get("height_m"), (int, float)) else None,
        **{f: props.get(f) for f in _RAMP_FIELDS if f in props},
    )
    out = {"type": "Feature", "geometry": feat.get("geometry"), "properties": label.model_dump(mode="json", exclude_none=False)}
    # keep ramp fields that were present
    return out


def draft(
    store: Path | str,
    site: str,
    area: str,
    *,
    force: bool = False,
    role: str = "dev",
    created_at: str | None = None,
) -> SiteMeta:
    store = Path(store)
    d = labels_dir(store, site)
    if d.exists() and site_path(store, site).exists() and not force:
        raise FileExistsError(f"site {site!r} already exists at {d}")
    if force:
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    build_dir = _area_build_dir(store, area)
    area_def = _area_def(store, area, build_dir)

    features_out: list[dict] = []
    for fname in FEATURE_FILES:
        fpath = build_dir / fname
        if not fpath.is_file():
            continue
        try:
            fc = json.loads(fpath.read_text())
        except (OSError, ValueError):
            continue
        element = _ELEMENT_BY_FILE[fname]
        for i, feat in enumerate(fc.get("features", []) if isinstance(fc, dict) else []):
            features_out.append(_map_feature(element, feat, fname, i))

    meta = SiteMeta(
        id=site,
        role=role,  # type: ignore[arg-type]
        polygon=area_def["polygon"],
        version=1,
        approved_by=None,
        approved_at=None,
        crs="EPSG:32619",
        created_at=created_at or _now(),
        source_area=build_dir.name.removesuffix("-twin").removesuffix("-merged"),
        frozen=False,
    )
    write_site(store, site, meta)
    labels_path(store, site).write_text(json.dumps({"type": "FeatureCollection", "features": features_out}, indent=2) + "\n")
    return meta


# aliases
draft_labels = draft
draft_site = draft


def approve(store: Path | str, site: str, approved_by: str, *, approved_at: str | None = None) -> SiteMeta:
    store = Path(store)
    meta = read_site(store, site)
    old_version = meta.version
    # snapshot current labels as labels.v{old}.geojson
    if labels_path(store, site).exists():
        shutil.copyfile(labels_path(store, site), snapshot_path(store, site, old_version))
    meta.frozen = True
    meta.approved_by = approved_by
    meta.approved_at = approved_at or _now()
    meta.version = old_version + 1
    write_site(store, site, meta)
    return meta


def new_version(store: Path | str, site: str) -> SiteMeta:
    store = Path(store)
    meta = read_site(store, site)
    old_version = meta.version
    if labels_path(store, site).exists():
        shutil.copyfile(labels_path(store, site), snapshot_path(store, site, old_version))
    meta.version = old_version + 1
    meta.frozen = False
    meta.approved_by = None
    meta.approved_at = None
    write_site(store, site, meta)
    return meta


def write_labels(
    store: Path | str,
    site: str,
    feature_collection: Any,
    *,
    version: int | None = None,
    expected_version: int | None = None,
) -> SiteMeta:
    store = Path(store)
    meta = read_site(store, site)
    if meta.frozen:
        raise FrozenSiteError(f"site {site!r} is frozen")
    want = version if version is not None else expected_version
    if want is not None and want != meta.version:
        raise ValueError(f"stale version: expected {meta.version}, got {want}")
    # validate features
    fc = feature_collection
    if isinstance(fc, dict):
        feats = fc.get("features", [])
        for f in feats:
            props = f.get("properties", {}) if isinstance(f, dict) else {}
            LabelFeature.model_validate(props)
    labels_path(store, site).write_text(json.dumps(fc, indent=2) + "\n")
    return meta


# aliases used by API/CLI
update_labels = write_labels
save_labels = write_labels
put_labels = write_labels
read_site_meta = read_site
load_site = read_site
load_labels = read_labels
