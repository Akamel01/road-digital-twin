"""Store I/O, draft mapping, approval and versioning for labelled sites.

A labelled site lives at ``<store>/labels/<site>/`` and holds:
  site.json          - a SiteMeta
  labels.geojson     - a GeoJSON FeatureCollection of LabelFeature properties
  labels.v{N}.geojson - frozen snapshots taken on approve / new-version
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def valid_site(site: str) -> bool:
    return bool(SITE_ID.fullmatch(site)) and ".." not in site and "\\" not in site

from shapely.geometry import mapping, shape

from twin.contracts import LabelFeature, SiteMeta, stage_dir

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

def list_sites(store: Path | str, role: str | None = None) -> list[SiteMeta]:
    """Labelled sites under <store>/labels, sorted by id; a missing labels dir is []."""
    root = Path(store) / "labels"
    if not root.is_dir():
        return []
    out: list[SiteMeta] = []
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        sp = d / "site.json"
        if not sp.is_file():
            continue
        site = SiteMeta.model_validate_json(sp.read_text())
        if role is not None and site.role != role:
            continue
        out.append(site)
    out.sort(key=lambda s: s.id)
    return out


def read_labels(store: Path | str, site: str) -> dict:
    p = labels_path(store, site)
    if not p.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(p.read_text())


def write_site(store: Path | str, site: str, meta: SiteMeta) -> None:
    d = labels_dir(store, site)
    d.mkdir(parents=True, exist_ok=True)
    site_path(store, site).write_text(meta.model_dump_json(indent=2) + "\n")


def area_build_dir(store: Path | str, area: str, *, areas_root: Path | None = None) -> Path:
    # area may be a name or a path; prefer a -twin build (or one with 5_features),
    # then a -merged build.
    store = Path(store)
    p = Path(area)
    names = [area]
    for suf in ("-twin", "-merged"):
        if not area.endswith(suf):
            names.append(area + suf)
    root = Path(areas_root) if areas_root is not None else store / "areas"
    cand_set: list[Path] = []
    if p.is_dir():
        cand_set.append(p)
    # areas_root candidates first
    for nm in (f"{area}-twin", area, f"{area}-merged"):
        cand_set.append(root / nm)
    for name in names:
        cand_set.append(root / name)
    # preserve current candidates
    for name in names:
        cand_set.append(store / name)
        cand_set.append(store / "areas" / name)
    # explicit *.json -> sibling builds
    if p.suffix == ".json":
        stem = p.stem
        for suf in ("-twin", "-merged", ""):
            cand_set.append(p.parent / (stem + suf if suf else stem))
    seen: set[Path] = set()
    uniq: list[Path] = []
    for c in cand_set:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    existing = [c for c in uniq if c.is_dir()]

    def _has_features(c: Path) -> bool:
        if stage_dir(c, "features").is_dir():
            return True
        return any((c / f).is_file() for f in FEATURE_FILES)

    def _score(c: Path) -> tuple[int, int, int]:
        twin_like = c.name.endswith("-twin") or stage_dir(c, "features").is_dir()
        return (0 if twin_like else 1, 0 if _has_features(c) else 1, 0 if (c / "merged.npz").is_file() else 1)

    existing.sort(key=_score)
    for c in existing:
        if _has_features(c) or (c / "merged.npz").is_file():
            return c
    if p.is_dir():
        return p
    cand = store / "areas" / area
    if cand.is_dir():
        return cand
    if areas_root is not None:
        cand2 = root / area
        if cand2.is_dir():
            return cand2
    raise FileNotFoundError(f"no area build for {area!r}")


def _area_def(store: Path | str, area: str, build_dir: Path, areas_root: Path | None = None) -> dict:
    store = Path(store)
    name = build_dir.name.removesuffix("-twin").removesuffix("-merged")
    root = Path(areas_root) if areas_root is not None else store / "areas"
    # named candidates
    named = [
        build_dir.parent / f"{name}.json",
        root / f"{name}.json",
        store / "areas" / f"{name}.json",
    ]
    p = Path(area)
    if p.is_file():
        named.append(p)
    for cand in named:
        if cand.is_file():
            try:
                d = json.loads(cand.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(d, dict):
                return d
    # wildcard next to build dir, only if exactly one parses to dict with polygon
    wildcard = []
    for cand in build_dir.parent.glob("*.json"):
        try:
            d = json.loads(cand.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and "polygon" in d:
            wildcard.append(d)
    if len(wildcard) == 1:
        return wildcard[0]
    if len(wildcard) == 0:
        raise FileNotFoundError(f"area def for {area!r} not found")
    raise ValueError(f"ambiguous area def for {area!r}: {len(wildcard)} polygon JSON files in {build_dir.parent}")


def _map_feature(element: str, feat: dict, source_file: str, idx: int) -> dict:
    props = dict(feat.get("properties") or {})
    fid = props.get("id")
    if fid is None:
        fid = f"{source_file}:{idx}"
    if element == "marking":
        mt = props.get("marking_type")
        if mt is None and isinstance(props.get("type"), str):
            mt = props.get("type")
        typ = "stop_line" if mt == "stop_line" else "solid_line"
    else:
        typ = _TYPE_DEFAULT[element]
    label = LabelFeature(
        id=str(fid),
        element=element,  # type: ignore[arg-type]
        type=typ,  # type: ignore[arg-type]
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


def resolve_area(store: Path | str, area: str, *, areas_root: Path | None = None) -> tuple[Path, dict]:
    store = Path(store)
    build_dir = area_build_dir(store, area, areas_root=areas_root)
    area_def = _area_def(store, area, build_dir, areas_root=areas_root)
    return build_dir, area_def


def draft(
    store: Path | str,
    site: str,
    area: str,
    *,
    force: bool = False,
    role: str = "dev",
    created_at: str | None = None,
    empty: bool = False,
    areas_root: Path | None = None,
) -> SiteMeta:
    store = Path(store)
    d = labels_dir(store, site)
    if d.exists() and site_path(store, site).exists() and not force:
        raise FileExistsError(f"site {site!r} already exists at {d}")
    if force:
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)

    build_dir, area_def = resolve_area(store, area, areas_root=areas_root)

    features_dir = stage_dir(build_dir, "features") if stage_dir(build_dir, "features").is_dir() else build_dir
    site_poly = area_def["polygon"]

    def _clip_geom(geom):
        if not isinstance(geom, dict):
            return geom
        try:
            g = shape(geom)
            poly = shape(site_poly)
        except (ValueError, TypeError, AttributeError):
            return geom
        if g.is_empty:
            return None
        inter = g.intersection(poly)
        if inter.is_empty:
            return None
        return mapping(inter)

    features_out: list[dict] = []
    if not empty:
        for fname in FEATURE_FILES:
            fpath = features_dir / fname
            if not fpath.is_file():
                continue
            try:
                fc = json.loads(fpath.read_text())
            except (OSError, ValueError):
                continue
            element = _ELEMENT_BY_FILE[fname]
            for i, feat in enumerate(fc.get("features", []) if isinstance(fc, dict) else []):
                if not isinstance(feat, dict):
                    continue
                geom = _clip_geom(feat.get("geometry"))
                if geom is None:
                    continue
                feat = dict(feat)
                feat["geometry"] = geom
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


def set_meta(store: Path | str, site: str, *, control, notes) -> SiteMeta:
    store = Path(store)
    meta = read_site(store, site)
    new_meta = SiteMeta.model_validate(
        {**meta.model_dump(mode="json"), "control": control, "notes": notes}
    )
    write_site(store, site, new_meta)
    return new_meta


# aliases used by API/CLI
update_labels = write_labels
save_labels = write_labels
put_labels = write_labels
read_site_meta = read_site
load_site = read_site
load_labels = read_labels
