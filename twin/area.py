"""Study area: a polygon from HD-map intersections and the nuScenes drives that pass through it.

`twin area define` writes <store>/areas/<name>.json. The run store keeps run folders
named by run id, so the `areas` folder is never read as a run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import mapping

from twin.stages.load import MAP_ORIGIN_LATLON, run_crs

MIN_PREFIX = 8


def _table(root: Path, version: str, name: str) -> list[dict]:
    return json.loads((root / version / f"{name}.json").read_text())


def load_intersections(dataroot, location: str) -> dict[str, shapely.Polygon]:
    """Intersection road segments of one HD map: full token -> polygon, map frame."""
    from twin.devkit_compat import nuscenes_map_class

    nusc_map = nuscenes_map_class()(dataroot=str(dataroot), map_name=location)
    return {
        r["token"]: nusc_map.extract_polygon(r["polygon_token"])
        for r in nusc_map.road_segment
        if r["is_intersection"]
    }


def resolve_tokens(prefixes: list[str], known) -> list[str]:
    """Full tokens for unique prefixes of at least 8 characters. Raises ValueError otherwise."""
    out = []
    for p in prefixes:
        hits = [t for t in known if len(p) >= MIN_PREFIX and t.startswith(p)]
        if len(hits) != 1:
            raise ValueError(f"{p!r} matches {len(hits)} intersections, need exactly 1")
        out.append(hits[0])
    return out


def drives_through(root: Path, version: str, location: str, polygon) -> list[dict]:
    """Scenes of this map location with any ego pose (keyframe or sweep, any sensor) inside polygon."""
    logs = {log["token"]: log for log in _table(root, version, "log")}
    scenes = {
        s["token"]: s
        for s in _table(root, version, "scene")
        if logs[s["log_token"]]["location"] == location
    }
    scene_of_sample = {
        s["token"]: s["scene_token"]
        for s in _table(root, version, "sample")
        if s["scene_token"] in scenes
    }
    pose_scene = {}  # ego_pose token -> scene token
    for sd in _table(root, version, "sample_data"):
        scene = scene_of_sample.get(sd["sample_token"])
        if scene:
            pose_scene[sd["ego_pose_token"]] = scene
    poses = [p for p in _table(root, version, "ego_pose") if p["token"] in pose_scene]
    xs = [p["translation"][0] for p in poses]
    ys = [p["translation"][1] for p in poses]
    inside = shapely.contains_xy(polygon, xs, ys)
    hit = {pose_scene[p["token"]] for p, i in zip(poses, inside) if i}
    rows = []
    for token in hit:
        s = scenes[token]
        rows.append(
            {
                "scene": s["name"],
                "scene_token": token,
                "date": logs[s["log_token"]]["date_captured"],
                "description": s["description"],
                "rain": "rain" in s["description"].lower(),
            }
        )
    return sorted(rows, key=lambda r: r["scene"])


def _to_utm(tr, coords):
    x, y = tr.transform(coords[:, 0], coords[:, 1])
    return np.column_stack([x, y])


def make_area(
    name, polygons, prefixes, buffer_m, root, version, location, include_rain=False
) -> dict:
    """The area record. polygons: intersection token -> map-frame polygon.

    DECISION: the buffer is applied and poses are tested in the map frame (metres,
    local tmerc with k=1); the saved polygon is that polygon moved to EPSG:32619.
    DECISION: rain drives are listed but held out (build_input false) unless include_rain.
    """
    tokens = resolve_tokens(prefixes, polygons)
    poly = shapely.union_all([polygons[t] for t in tokens]).buffer(buffer_m)
    tr = run_crs(MAP_ORIGIN_LATLON)
    utm = shapely.transform(poly, lambda a: _to_utm(tr, a))
    drives = drives_through(Path(root), version, location, poly)
    for d in drives:
        d["build_input"] = include_rain or not d["rain"]
    return {
        "name": name,
        "location": location,
        "epsg": 32619,
        "buffer_m": buffer_m,
        "intersections": tokens,
        "polygon": mapping(utm),
        "dataset_version": version,
        "drives": drives,
    }


def area_define_command(
    name, intersections, buffer_m, location, dataroot, version, store, include_rain
) -> int:
    from twin.runner import default_store

    root = Path(dataroot)
    if not (root / version / "scene.json").is_file():
        print(f"nuScenes {version} not found at {root}", file=sys.stderr)
        return 2
    try:
        area = make_area(
            name,
            load_intersections(root, location),
            intersections,
            buffer_m,
            root,
            version,
            location,
            include_rain,
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    out = (Path(store) if store else default_store()) / "areas" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(area, indent=2) + "\n")
    rain = sum(d["rain"] for d in area["drives"])
    print(f"{out}: {len(area['drives'])} drives, {rain} rain (held out)")
    for d in area["drives"]:
        flag = "RAIN" if d["rain"] else "    "
        print(f"  {d['scene']}  {d['date']}  {flag}  {d['description']}")
    return 0


def drive_tokens(build: Path) -> list[str]:
    """Scene tokens of the drives an area build used (its drives.json lists scene names), in that order.
    The tokens come from the area definition <store>/areas/<area>.json, where the build folder is
    <area>-twin or <area>-merged. [] when either file is missing."""
    build = Path(build)
    name = build.name.removesuffix("-twin").removesuffix("-merged")
    try:
        defined = json.loads((build.parent / f"{name}.json").read_text())["drives"]
        used = json.loads((build / "drives.json").read_text())
    except (OSError, ValueError, KeyError):
        return []
    token = {d["scene"]: d["scene_token"] for d in defined}
    return [token[d["scene"]] for d in used if d.get("scene") in token]


# --- suggest-drives (ticket #253, M2) ---

SUGGEST_DRIVES_VERSION = "v1.0-trainval"
SUGGEST_SWEEP_STEP = 4
SUGGEST_DENSITY_THRESHOLD = 50.0


def _versioned_table(root: Path, version: str, name: str) -> list[dict]:
    path = root / version / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing dataset table: {path}")
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"failed to read dataset table {path}: {e}") from e


def resolve_area_arg(area_arg: str, store: Path) -> Path:
    """Z1: try arg, <store>/arg, <store>/areas/<arg>.

    Returns existing resolved path, else raises FileNotFoundError listing tried paths.
    """
    store = Path(store).resolve()
    p = Path(area_arg)
    tried: list[str] = []
    candidates: list[Path] = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append(p)
        candidates.append(store / area_arg)
        candidates.append(store / "areas" / area_arg)
    for cand in candidates:
        tried.append(str(cand))
        if cand.exists():
            return cand.resolve()
    raise FileNotFoundError("tried paths: " + ", ".join(tried))


def _read_area_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"failed to read area JSON {path}: {e}") from e
    if not isinstance(data, dict):
        raise TypeError(f"area JSON must be an object: {path}")
    return data


def rebuilt_map_frame_polygon_from_area(
    area_def: dict, dataroot: Path, location: str | None = None
):
    loc = location or area_def.get("location")
    if not loc:
        raise ValueError("area definition missing location")
    polys = load_intersections(dataroot, loc)
    tokens = area_def.get("intersections") or []
    if not tokens:
        raise ValueError("area definition missing intersections")
    missing = [t for t in tokens if t not in polys]
    if missing:
        raise ValueError(f"area intersections not found in map: {missing[:3]}")
    buffer_m = float(area_def.get("buffer_m", 0.0))
    poly = shapely.union_all([polys[t] for t in tokens]).buffer(buffer_m)
    if poly is None or poly.is_empty:
        raise ValueError("rebuilt map-frame polygon is empty")
    return poly


def _drivable_union(nusc_map, bounds):
    records = nusc_map.get_records_in_patch(
        tuple(bounds), layer_names=["drivable_area"], mode="intersect"
    )
    polys = []
    for token in records.get("drivable_area", []):
        rec = nusc_map.get("drivable_area", token)
        for poly_token in rec.get("polygon_tokens", []):
            polys.append(nusc_map.extract_polygon(poly_token))
    if not polys:
        return shapely.Polygon()
    return shapely.union_all(polys)


def _scene_rows_for_location(root: Path, version: str, location: str) -> list[dict]:
    logs = {log["token"]: log for log in _versioned_table(root, version, "log")}
    out = []
    for s in _versioned_table(root, version, "scene"):
        log = logs.get(s["log_token"])
        if not log or log.get("location") != location:
            continue
        desc = s.get("description", "") or ""
        out.append(
            {
                "scene": s["name"],
                "scene_token": s["token"],
                "date": log.get("date_captured"),
                "description": desc,
                "rain": "rain" in desc.lower(),
            }
        )
    return out


def _scene_pose_index(root: Path, version: str, polygon):
    """Build scene_token -> in-polygon flag once for this area (single table pass)."""
    scenes = _versioned_table(root, version, "scene")
    scene_tokens = {s["token"] for s in scenes}
    scene_of_sample = {
        s["token"]: s["scene_token"]
        for s in _versioned_table(root, version, "sample")
        if s.get("scene_token") in scene_tokens
    }
    pose_scene: dict[str, str] = {}
    for sd in _versioned_table(root, version, "sample_data"):
        scene = scene_of_sample.get(sd.get("sample_token"))
        if scene:
            pose_scene[sd["ego_pose_token"]] = scene
    if not pose_scene:
        return {}
    poses = [
        p for p in _versioned_table(root, version, "ego_pose") if p["token"] in pose_scene
    ]
    if not poses:
        return {}
    xs = np.array([p["translation"][0] for p in poses], dtype=float)
    ys = np.array([p["translation"][1] for p in poses], dtype=float)
    inside = np.asarray(shapely.contains_xy(polygon, xs, ys), dtype=bool)
    hit: set[str] = set()
    for p, ok in zip(poses, inside, strict=False):
        if ok:
            scene = pose_scene.get(p["token"])
            if scene:
                hit.add(scene)
    return {tok: (tok in hit) for tok in scene_tokens}


def _drive_overlaps_polygon_index(scene_token: str, overlap_index: dict[str, bool]) -> bool:
    return bool(overlap_index.get(scene_token, False))


def _driveable_surface_index(nusc) -> int | None:
    mapping = getattr(nusc, "lidarseg_name2idx_mapping", None)
    if isinstance(mapping, dict) and "flat.driveable_surface" in mapping:
        try:
            return int(mapping["flat.driveable_surface"])
        except (TypeError, ValueError):
            return None
    categories = getattr(nusc, "category", None)
    if isinstance(categories, list):
        for c in categories:
            if c.get("name") == "flat.driveable_surface" and "index" in c:
                try:
                    return int(c["index"])
                except (TypeError, ValueError):
                    return None
    return None


def _lidarseg_driveable_labels(nusc, sd_token: str, n_points: int, inside_idx, drive_idx: int | None):
    if drive_idx is None:
        return None
    try:
        rec = nusc.get("lidarseg", sd_token)
    except (KeyError, AttributeError, TypeError):
        return None
    if not isinstance(rec, dict):
        return None
    filename = rec.get("filename")
    if not filename:
        return None
    path = os.path.join(nusc.dataroot, filename)
    if not os.path.isfile(path):
        return None
    try:
        labels = np.fromfile(path, dtype=np.uint8)
    except (OSError, ValueError):
        return None
    if len(labels) != n_points:
        return None
    try:
        return labels[inside_idx] == int(drive_idx)
    except (IndexError, TypeError, ValueError):
        return None


def _sampled_lidar_points_for_scene(nusc, scene_token: str, polygon, step: int):
    """Yield (points_xyz[N,3], labels_flat_driveable_or_None) for sampled keyframes."""
    scene = nusc.get("scene", scene_token)
    keyframes = []
    token = scene["first_sample_token"]
    while token:
        sample = nusc.get("sample", token)
        keyframes.append(sample)
        token = sample.get("next")
    drive_idx = _driveable_surface_index(nusc)
    for sample in keyframes[::step]:
        sd_token = sample["data"].get("LIDAR_TOP")
        if not sd_token:
            continue
        try:
            from nuscenes.utils.data_classes import LidarPointCloud
            from pyquaternion import Quaternion

            sd = nusc.get("sample_data", sd_token)
            pc = LidarPointCloud.from_file(nusc.get_sample_data_path(sd_token))
            cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
            ego = nusc.get("ego_pose", sd["ego_pose_token"])
            pc.rotate(Quaternion(cs["rotation"]).rotation_matrix)
            pc.translate(np.array(cs["translation"]))
            pc.rotate(Quaternion(ego["rotation"]).rotation_matrix)
            pc.translate(np.array(ego["translation"]))
        except (KeyError, OSError, ValueError, TypeError, AssertionError, ImportError):
            continue
        pts = np.asarray(pc.points[:3, :].T, dtype=float)
        if len(pts) == 0:
            continue
        inside = np.asarray(shapely.contains_xy(polygon, pts[:, 0], pts[:, 1]), dtype=bool)
        if not inside.any():
            continue
        inside_idx = np.flatnonzero(inside)
        pts_in = pts[inside_idx]
        labels_in = _lidarseg_driveable_labels(nusc, sd_token, len(pts), inside_idx, drive_idx)
        yield pts_in, labels_in


def _accumulate_drive_observations(
    acc, nusc, scene_token, polygon, drivable_union, step, ox, oy
):
    import twin.area_coverage as ac

    sources: list[str] = []
    covered_all: set[tuple[int, int]] = set()
    for pts, labels in _sampled_lidar_points_for_scene(nusc, scene_token, polygon, step):
        try:
            src, covered = ac.accumulate_drive_points(
                acc,
                pts,
                polygon,
                drivable_union,
                labels_flat_driveable=labels,
                ox=ox,
                oy=oy,
                count_drive=False,
            )
        except (ValueError, TypeError):
            continue
        if src:
            sources.append(str(src))
        covered_all.update(covered)
    ac.mark_drive_coverage(acc, covered_all)
    uniq = sorted(set(sources))
    if not uniq:
        return "geometric_road_mask_fallback"
    if len(uniq) == 1:
        return uniq[0]
    return uniq


def _flatten_source_list(values) -> list[str]:
    out: set[str] = set()
    for v in values or []:
        if v is None:
            continue
        if isinstance(v, (list, tuple, set)):
            for s in v:
                if s:
                    out.add(str(s))
        else:
            out.add(str(v))
    return sorted(out)


def _format_suggest_table(rows):
    header = f"{'scene':<14} {'scene_token':<34} {'cells_gained':>12} {'rain':<6} {'night':<6}"
    lines = [header]
    for r in rows:
        scene = str(r.get("scene", ""))
        tok = str(r.get("scene_token", ""))
        gained = int(r.get("cells_gained", 0))
        rain = str(bool(r.get("rain", False)))
        night = str(bool(r.get("night", False)))
        lines.append(
            f"{scene:<14} {tok:<34} {gained:>12} {rain:<6} {night:<6}"
        )
    return "\n".join(lines)


def _drive_entry_from_row(row):
    return {
        "scene": row["scene"],
        "scene_token": row["scene_token"],
        "date": row.get("date"),
        "description": row.get("description", ""),
        "rain": bool(row.get("rain", False)),
        "build_input": not bool(row.get("rain", False)),
    }


def suggest_drives_command(
    area_arg,
    top_n,
    density_threshold,
    apply_changes,
    dataroot,
    store,
    version=SUGGEST_DRIVES_VERSION,
    *,
    _coverage_module=None,
    _nusc_factory=None,
    _nusc_map_factory=None,
) -> int:
    import twin.area_coverage as ac

    ac_mod = _coverage_module or ac
    root = Path(dataroot).resolve()
    if store is None:
        from twin.runner import default_store

        store_path = Path(default_store()).resolve()
    else:
        store_path = Path(store).resolve()

    # Z1 resolution
    try:
        resolved = resolve_area_arg(str(area_arg), store_path)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    # validation (CLI may also check; enforce here for programmatic use)
    try:
        top_n_i = int(top_n)
    except (TypeError, ValueError):
        print("--top must be an integer >= 1", file=sys.stderr)
        return 2
    if top_n_i < 1:
        print("--top must be an integer >= 1", file=sys.stderr)
        return 2
    try:
        density_threshold_f = float(density_threshold)
    except (TypeError, ValueError):
        print("--density-threshold must be >= 0", file=sys.stderr)
        return 2
    if density_threshold_f < 0:
        print("--density-threshold must be >= 0", file=sys.stderr)
        return 2

    # dataset presence check for required resources/tables (basic)
    required_tables = [
        "scene.json",
        "sample.json",
        "sample_data.json",
        "ego_pose.json",
        "log.json",
    ]
    for t in required_tables:
        if not (root / version / t).is_file():
            print(f"missing dataset table: {root / version / t}", file=sys.stderr)
            return 2

    try:
        area_def = _read_area_json(resolved)
    except (TypeError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2

    location = area_def.get("location")
    if not location or not isinstance(location, str):
        print("area definition missing location", file=sys.stderr)
        return 2

    try:
        from twin.devkit_compat import nuscenes_map_class

        NuScenesMap = nuscenes_map_class()
        nusc_map = (
            _nusc_map_factory(dataroot=str(root), map_name=location)
            if _nusc_map_factory
            else NuScenesMap(dataroot=str(root), map_name=location)
        )
        rebuilt = rebuilt_map_frame_polygon_from_area(area_def, root, location)
        drivable_union = _drivable_union(nusc_map, rebuilt.bounds)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except (KeyError, OSError, RuntimeError, TypeError, AssertionError) as e:
        print(f"failed to load area/map resources: {e}", file=sys.stderr)
        return 2

    try:
        cells, origin = ac_mod.build_grid(rebuilt, drivable_union)
        baseline_acc = ac_mod.init_accumulator(cells)
    except (ValueError, TypeError) as e:
        print(f"failed to build coverage grid: {e}", file=sys.stderr)
        return 2

    existing_drives = list(area_def.get("drives") or [])
    existing_tokens = {
        d.get("scene_token") for d in existing_drives if isinstance(d, dict) and d.get("scene_token")
    }

    # instantiate NuScenes for version (explicit, not scan_scenes/DevkitSource)
    try:
        if _nusc_factory:
            nusc = _nusc_factory(version=version, dataroot=str(root), verbose=False)
        else:
            from nuscenes.nuscenes import NuScenes

            nusc = NuScenes(version, dataroot=str(root), verbose=False)
    except (AssertionError, FileNotFoundError, KeyError, OSError, RuntimeError, ValueError) as e:
        print(f"failed to load nuScenes {version} at {root}: {e}", file=sys.stderr)
        return 2

    baseline_sources: list[object] = []
    for d in existing_drives:
        if not isinstance(d, dict):
            continue
        tok = d.get("scene_token")
        if not tok:
            continue
        try:
            src = _accumulate_drive_observations(
                baseline_acc,
                nusc,
                tok,
                rebuilt,
                drivable_union,
                SUGGEST_SWEEP_STEP,
                origin[0],
                origin[1],
            )
            baseline_sources.append(src)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError, AssertionError) as e:
            print(f"failed to read baseline drive {tok}: {e}", file=sys.stderr)
            return 2

    baseline_records = ac_mod.cell_records(baseline_acc, density_threshold_f)

    # candidate discovery: trainval/version, same location, overlaps rebuilt polygon, exclude existing
    try:
        scene_rows = _scene_rows_for_location(root, version, location)
        overlap_index = _scene_pose_index(root, version, rebuilt)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    candidate_rows = []
    try:
        for row in scene_rows:
            tok = row["scene_token"]
            if tok in existing_tokens:
                continue
            if not _drive_overlaps_polygon_index(tok, overlap_index):
                continue
            cand_acc = {k: dict(v) for k, v in baseline_acc.items()}
            src = _accumulate_drive_observations(
                cand_acc,
                nusc,
                tok,
                rebuilt,
                drivable_union,
                SUGGEST_SWEEP_STEP,
                origin[0],
                origin[1],
            )
            candidate_records = ac_mod.cell_records(cand_acc, density_threshold_f)
            candidate_rows.append(
                {
                    **row,
                    "candidate_records": candidate_records,
                    "ground_source": src,
                }
            )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except (KeyError, OSError, RuntimeError, TypeError, AssertionError) as e:
        print(f"failed to evaluate candidates: {e}", file=sys.stderr)
        return 2

    ranked = ac_mod.rank_candidates(
        candidate_rows, baseline_records, existing_drives, top_n_i
    )

    # write coverage.json next to resolved area (always, even empty candidates)
    cov_path = ac_mod.coverage_path_for_area(resolved)
    baseline_scene_tokens = [
        d.get("scene_token") for d in existing_drives if isinstance(d, dict) and d.get("scene_token")
    ]
    gs = _flatten_source_list(
        list(baseline_sources) + [r.get("ground_source") for r in candidate_rows]
    )
    extra = {
        "epsg_persisted_polygon": area_def.get("epsg"),
        "dataset_version_area": area_def.get("dataset_version"),
        "suggest_version": version,
        "dataroot": str(root),
        "store": str(store_path),
        "generated_with": "twin.area_coverage",
        "area_resolved_path": str(resolved),
    }
    try:
        doc = ac_mod.coverage_document(
            area_def.get("name") or resolved.stem,
            str(resolved),
            location,
            origin,
            baseline_records,
            density_threshold_pts_m2=density_threshold_f,
            ground_sources=gs,
            baseline_scene_tokens=baseline_scene_tokens,
            extra_metadata=extra,
        )
        ac_mod.atomic_write_json(cov_path, doc)
    except (OSError, TypeError, ValueError) as e:
        print(f"failed to write coverage output {cov_path}: {e}", file=sys.stderr)
        return 2

    # print table
    print(_format_suggest_table(ranked))

    if apply_changes and ranked:
        # append top-N ranked in ranked order, dedupe by scene_token, preserve keys/order of existing entries
        existing = list(area_def.get("drives") or [])
        seen = {d.get("scene_token") for d in existing if isinstance(d, dict) and d.get("scene_token")}
        for r in ranked:
            tok = r.get("scene_token")
            if tok in seen:
                continue
            existing.append(_drive_entry_from_row(r))
            seen.add(tok)
        new_def = dict(area_def)
        new_def["drives"] = existing
        try:
            ac_mod.atomic_write_json(resolved, new_def)
        except (OSError, TypeError, ValueError) as e:
            print(f"failed to write area file {resolved}: {e}", file=sys.stderr)
            return 2

    return 0
