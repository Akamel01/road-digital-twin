"""Mapping between the audit tool's surfaces and labelled-site features.

Importing this module must not touch cv2 or FastAPI (P8); raster work lives in
``twin.labelraster`` and is imported lazily by the generator.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.errors import GeometryTypeError
from shapely.geometry import shape

from twin import labels
from twin.area import drive_correction
from twin.area import drive_tokens as area_drive_tokens
from twin.contracts import LabelFeature
from twin.labels import read_labels, read_site, valid_site, write_labels
from twin.runstore import DONE, RunStore

W_M = 80.0
H_M = 75.0
CELL = 0.05
W_PX = 1600
H_PX = 1500
FIT_TOL_M = 0.1

_FULL_STAGES = ("load", "align", "ground", "colour")
_FALLBACK_STAGES = ("load", "align", "ground")

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


def _load_draft(draft_path, site: str) -> tuple[dict, list]:
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
    return data, surfaces


def validate_draft(draft_path, site: str) -> int:
    _data, surfaces = _load_draft(draft_path, site)
    for surface in surfaces:
        surface_to_feature(surface)
    return len(surfaces)


def import_draft(store: Path, site: str, draft_path, *, replace: bool = False) -> int:
    store = Path(store)
    _data, surfaces = _load_draft(draft_path, site)

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


def _iter_geometry_points(geom: Any):
    if not isinstance(geom, dict):
        return
    typ = geom.get("type")
    coords = geom.get("coordinates")
    if typ == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
        yield coords[0], coords[1]
        return
    if typ == "LineString" and isinstance(coords, list):
        for p in coords:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                yield p[0], p[1]
        return
    if typ == "Polygon" and isinstance(coords, list):
        for ring in coords:
            if not isinstance(ring, list):
                continue
            for p in ring:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    yield p[0], p[1]
        return
    if typ == "MultiPoint" and isinstance(coords, list):
        for p in coords:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                yield p[0], p[1]
        return
    if typ == "MultiLineString" and isinstance(coords, list):
        for line in coords:
            if not isinstance(line, list):
                continue
            for p in line:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    yield p[0], p[1]
        return
    if typ == "MultiPolygon" and isinstance(coords, list):
        for poly in coords:
            if not isinstance(poly, list):
                continue
            for ring in poly:
                if not isinstance(ring, list):
                    continue
                for p in ring:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        yield p[0], p[1]
        return
    # best effort flatten
    def _walk(obj):
        if isinstance(obj, (list, tuple)):
            if len(obj) == 2 and not any(isinstance(x, (list, tuple, dict)) for x in obj):
                yield obj[0], obj[1]
            else:
                for item in obj:
                    yield from _walk(item)
    yield from _walk(coords)


def _polygon_bounds(polygon: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(polygon, dict):
        return None
    try:
        g = shape(polygon)
    except (GeometryTypeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    if g.is_empty or not g.is_valid:
        # try to make valid? avoid geometry ops changing meaning; skip invalid
        try:
            g = g.buffer(0)
        except Exception:  # noqa: BLE001
            return None
    if g.is_empty:
        return None
    try:
        minx, miny, maxx, maxy = g.bounds
        vals = (float(minx), float(miny), float(maxx), float(maxy))
    except (TypeError, ValueError, AttributeError):
        return None
    if not all(math.isfinite(v) for v in vals):
        return None
    return vals


def _stages_done(run, required: tuple[str, ...]) -> bool:
    by = {s.get("name"): s for s in run.stages if isinstance(s, dict)}
    for name in required:
        stage = by.get(name)
        if not stage or stage.get("status") not in DONE:
            return False
    return True


@dataclass(frozen=True)
class FrameDrive:
    """One merged drive's camera files and the map-frame transform that registers it."""
    name: str
    base: Path
    transform: np.ndarray | None = None


@dataclass(frozen=True)
class AreaSource:
    """One area build as a label-tool source: merged ground cloud plus the merged drives' cameras."""
    name: str
    base: Path
    frames: tuple[FrameDrive, ...] = ()


def runs_for_area(store, area, *, areas_root=None):
    store = Path(store)
    build_dir, area_def = labels.resolve_area(store, area, areas_root=areas_root)
    tokens = area_drive_tokens(build_dir, defined=area_def)
    rs = RunStore(store)
    dataset_version = None
    if isinstance(area_def, dict):
        dataset_version = area_def.get("dataset_version")
    out = []
    seen = set()
    for token in tokens:
        candidates = rs.runs(scene=token, dataset_version=dataset_version)
        chosen = None
        for required in (_FULL_STAGES, _FALLBACK_STAGES):
            for run in candidates:
                if _stages_done(run, required):
                    chosen = run
                    break
            if chosen is not None:
                break
        if chosen is not None and chosen.path not in seen:
            out.append(chosen.path)
            seen.add(chosen.path)
    return out


def area_source(build_dir, area_def) -> AreaSource | None:
    """Returns the area build as one label-tool source, or None when it has no merged ground cloud; frames is empty when the area definition has no usable polygon or the merged drives are missing."""
    build = Path(build_dir)
    name = build.name.removesuffix("-twin").removesuffix("-merged")
    root = build.parent
    twin = build if (build / "4_ground" / "ground.laz").is_file() else root / f"{name}-twin"
    merged = build if build.name.endswith("-merged") else root / f"{name}-merged"
    if not (twin / "4_ground" / "ground.laz").is_file():
        return None
    try:
        drives = json.loads((merged / "drives.json").read_text())
    except (OSError, ValueError):
        drives = []
    frames: tuple[FrameDrive, ...] = ()
    poly = area_def.get("polygon") if isinstance(area_def, dict) else None
    if drives and isinstance(poly, dict):
        try:
            centre = np.array([*shape(poly).centroid.coords[0], 0.0])
        except (
            GeometryTypeError,
            shapely.errors.ShapelyError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            IndexError,
        ):
            centre = None
        if centre is not None:
            frames = tuple(
                FrameDrive(
                    name=d["scene"],
                    base=merged / "drives" / d["scene"],
                    transform=drive_correction(d.get("correction"), centre),
                )
                for d in drives
                if isinstance(d, dict) and d.get("scene")
            )
    return AreaSource(name=name, base=twin, frames=frames)


def window_for(store, site, *, centre: bool = False):
    meta = read_site(store, site)
    fc = read_labels(store, site)
    minx = miny = math.inf
    maxx = maxy = -math.inf

    pb = _polygon_bounds(getattr(meta, "polygon", None))
    if pb is not None:
        minx = min(minx, pb[0])
        miny = min(miny, pb[1])
        maxx = max(maxx, pb[2])
        maxy = max(maxy, pb[3])

    if centre and pb is not None:
        cx = (pb[0] + pb[2]) / 2.0
        cy = (pb[1] + pb[3]) / 2.0
    else:
        cx = cy = None

    features = (fc.get("features") if isinstance(fc, dict) else None) or []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        for x, y in _iter_geometry_points(feat.get("geometry")):
            try:
                xf = float(x)
                yf = float(y)
            except (TypeError, ValueError):
                continue
            if not (math.isfinite(xf) and math.isfinite(yf)):
                continue
            minx = min(minx, xf)
            miny = min(miny, yf)
            maxx = max(maxx, xf)
            maxy = max(maxy, yf)

    if not (math.isfinite(minx) and math.isfinite(miny) and math.isfinite(maxx) and math.isfinite(maxy)):
        raise DraftError(f"site {site!r} has no finite polygon or label geometry for window")

    bounds = [minx, miny, maxx, maxy]
    w = maxx - minx
    h = maxy - miny
    if w <= W_M + FIT_TOL_M and h <= H_M + FIT_TOL_M:
        if centre and pb is not None:
            return (float(cx - W_M / 2.0), float(cy + H_M / 2.0), {"fallback": False, "bounds": bounds})
        return (float(minx), float(maxy), {"fallback": False, "bounds": bounds})

    if centre and pb is not None:
        return (float(cx - W_M / 2.0), float(cy + H_M / 2.0), {"fallback": True, "bounds": bounds})
    ucx = (minx + maxx) / 2.0
    ucy = (miny + maxy) / 2.0
    return (float(ucx - W_M / 2.0), float(ucy + H_M / 2.0), {"fallback": True, "bounds": bounds})


def _window_covered(area_def, x0, y1):
    if not isinstance(area_def, dict):
        raise DraftError("area def missing or invalid polygon for window coverage")
    polygon = area_def.get("polygon")
    if not isinstance(polygon, dict):
        raise DraftError(
            f"area {area_def.get('name', '<unknown>')!r} has no polygon; "
            f"cannot validate window ({x0}, {y1}) — check --area/--areas"
        )
    try:
        poly = shape(polygon)
    except Exception as exc:
        raise DraftError(
            f"area {area_def.get('name', '<unknown>')!r} has invalid polygon for "
            f"window ({x0}, {y1}); check --area/--areas"
        ) from exc
    if poly.is_empty:
        raise DraftError(
            f"area {area_def.get('name', '<unknown>')!r} has empty polygon for "
            f"window ({x0}, {y1}); check --area/--areas"
        )
    box = shapely.box(float(x0), float(y1) - H_M, float(x0) + W_M, float(y1))
    try:
        inter = poly.intersection(box)
    except Exception as exc:
        raise DraftError(
            f"area {area_def.get('name', '<unknown>')!r} polygon could not be checked "
            f"against window ({x0}, {y1}); check --area/--areas"
        ) from exc
    box_area = box.area
    covered = (inter.area / box_area) if box_area else 0.0
    if covered < 0.95:
        name = area_def.get("name", "<unknown>")
        raise DraftError(
            f"window ({x0}, {y1}, {W_M}x{H_M} m) is not covered by area {name!r} "
            f"({covered:.1%} < 95%); choose a window inside the area or pass --area/--areas"
        )
    return True


def generate(
    store,
    site: str,
    *,
    area: str | None = None,
    areas_root: Path | None = None,
    import_path: Path | None = None,
    replace: bool = False,
    reset: bool = False,
    x0: float | None = None,
    y1: float | None = None,
) -> Path:
    import os
    import shutil
    import sys
    import tempfile

    store = Path(store)
    if areas_root is not None:
        areas_root = Path(areas_root)
    if not valid_site(site):
        raise DraftError(f"bad site id: {site!r}")

    preexisting = labels.site_path(store, site).is_file()
    if (x0 is None) != (y1 is None):
        raise DraftError("must provide both --x0 and --y1")
    if reset and not preexisting:
        raise DraftError(f"site {site!r} does not exist; cannot reset")

    meta = read_site(store, site) if preexisting else None

    if reset and area is None:
        raise DraftError("area required to reset site")
    if not preexisting and not reset and area is None:
        raise DraftError("missing site without --area")
    if reset and meta is not None and meta.frozen:
        raise DraftError("site is frozen; reset refused")

    area_name = area or (meta.source_area if meta else None)
    if not area_name:
        raise DraftError("area required")

    build_dir, area_def = labels.resolve_area(store, area_name, areas_root=areas_root)
    runs = runs_for_area(store, area_name, areas_root=areas_root)

    used_area = False
    if not runs:
        src = area_source(build_dir, area_def)
        if src is not None:
            runs = [src]
            used_area = True

    if preexisting and not runs:
        raise DraftError(
            f"existing site {site!r} has no resolvable runs for area {area_name!r}; "
            "check --store/--areas/--area"
        )

    explicit_window = x0 is not None and y1 is not None
    info = {"fallback": False}
    if explicit_window:
        _window_covered(area_def, float(x0), float(y1))
        wx0, wy1 = float(x0), float(y1)
    else:
        wx0 = wy1 = None  # set after import/auto

    if import_path is not None:
        validate_draft(import_path, site)

    site_dir = labels.labels_dir(store, site)
    existed_before = preexisting
    needs_snapshot = bool(reset or import_path is not None)
    backup_root: Path | None = None
    backup_ok = False
    keep_backup = False
    if needs_snapshot and existed_before:
        backup_root = Path(tempfile.mkdtemp(prefix="labeltool-site-"))
        try:
            shutil.copytree(site_dir, backup_root / "site")
            backup_ok = True
        except BaseException:
            shutil.rmtree(backup_root, ignore_errors=True)
            raise

    try:
        if reset:
            assert meta is not None
            role = meta.role or "audit"
            labels.draft(
                store,
                site,
                area_name,
                force=True,
                empty=True,
                areas_root=areas_root,
                role=role,
            )
            meta = read_site(store, site)
        elif not preexisting:
            labels.draft(
                store,
                site,
                area_name,
                empty=True,
                areas_root=areas_root,
                role="audit",
            )
            meta = read_site(store, site)

        if import_path is not None:
            import_draft(store, site, Path(import_path), replace=replace)

        if not explicit_window:
            wx0, wy1, info = window_for(store, site, centre=used_area)
            if preexisting and not reset:
                print(
                    f"warning: auto window for existing site {site!r}; "
                    f"use --x0/--y1 to pin the recorded window",
                    file=sys.stderr,
                )

        from twin import labelraster
        from twin.dataset import DatasetConfig

        nuscenes_root = DatasetConfig.from_env().root
        data = labelraster.export_window(
            store, runs, site=site, x0=wx0, y1=wy1, nuscenes_root=nuscenes_root
        )
        data["site"] = site
        data["window_fallback"] = bool(info.get("fallback", False))
        data.setdefault("missing", [])
        data.setdefault("no_imagery", False)

        if used_area:
            data["unavailable"] = ["ortho", "fused"]
            if data.get("no_imagery") is False and not data["frames"]:
                source_name = runs[0].name
                data["missing"].append(
                    f"no usable camera frames (check {source_name}-merged/drives and the nuScenes root)"
                )

        html = render(data)
        out_dir = labels.labels_dir(store, site)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "tool.html"
        tmp = out_dir / "tool.html.tmp"
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, target)
        return target
    except BaseException:
        if backup_ok and backup_root is not None:
            try:
                if site_dir.exists():
                    shutil.rmtree(site_dir)
                shutil.copytree(backup_root / "site", site_dir)
            except BaseException:
                keep_backup = True
                print(
                    f"labeltool: restore failed; backup preserved at {backup_root}",
                    file=sys.stderr,
                )
                raise
        elif not existed_before and site_dir.exists():
            shutil.rmtree(site_dir)
        raise
    finally:
        if backup_root is not None and not keep_backup:
            shutil.rmtree(backup_root, ignore_errors=True)


def render(data: dict) -> str:
    data = dict(data or {})
    if "site" not in data:
        data["site"] = data.get("site", "")
    data["surface_types"] = list(SURFACE_TYPES)
    data["surface_map"] = {k: list(v) for k, v in SURFACE_MAP.items()}
    data["area_types"] = [raw for raw, (el, t) in SURFACE_MAP.items() if el == "crosswalk"]
    from twin.contracts import LabelFeature

    data["schema_fields"] = list(LabelFeature.model_fields)
    base = resources.files("twin").joinpath("templates")
    template_path = base.joinpath("label_tool.html")
    pure_path = base.joinpath("labeltool_pure.js")
    template = template_path.read_text("utf-8")
    pure = pure_path.read_text("utf-8")
    if template.count("__DATA__") != 1:
        raise ValueError("expected __DATA__ placeholder exactly once")
    if template.count("__PURE__") != 1:
        raise ValueError("expected __PURE__ placeholder exactly once")
    payload = json.dumps(data, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = template.replace("__DATA__", payload, 1)
    html = html.replace("__PURE__", pure, 1)
    return html
