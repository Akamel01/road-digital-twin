"""Study area: a polygon from HD-map intersections and the nuScenes drives that pass through it.

`twin area define` writes <store>/areas/<name>.json. The run store keeps run folders
named by run id, so the `areas` folder is never read as a run.
"""

import json
import os
import sys
import tempfile
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
    return json.loads(path.read_text())


def resolve_area_arg(area_arg: str, store: Path) -> Path:
    """Z1: try arg, <store>/arg, <store>/areas/<arg>. Exit-2 semantics handled by caller."""
    tried = []
    p = Path(area_arg)
    tried.append(str(p))
    if p.exists():
        return p.resolve() if p.is_absolute() or p.exists() else p
    p2 = store / area_arg
    tried.append(str(p2))
    if p2.exists():
        return p2
    p3 = store / "areas" / area_arg
    tried.append(str(p3))
    if p3.exists():
        return p3
    raise FileNotFoundError("tried paths: " + ", ".join(tried))


def _read_area_json(path: Path) -> dict:
    return json.loads(path.read_text())


def rebuilt_map_frame_polygon_from_area(area_def: dict, dataroot: Path, location: str | None = None):
    loc = location or area_def.get("location")
    if not loc:
        raise ValueError("area definition missing location")
    polys = load_intersections(dataroot, loc)
    tokens = area_def.get("intersections") or []
    if not tokens:
        raise ValueError("area definition missing intersections")
    buffer_m = float(area_def.get("buffer_m", 0.0))
    return shapely.union_all([polys[t] for t in tokens]).buffer(buffer_m)


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
        out.append(
            {
                "scene": s["name"],
                "scene_token": s["token"],
                "date": log.get("date_captured"),
                "description": s.get("description", ""),
                "rain": "rain" in (s.get("description", "").lower()),
            }
        )
    return out


def _poses_for_scenes(root: Path, version: str, scene_tokens: set[str]):
    scene_of_sample = {
        s["token"]: s["scene_token"]
        for s in _versioned_table(root, version, "sample")
        if s.get("scene_token") in scene_tokens
    }
    pose_scene = {}
    for sd in _versioned_table(root, version, "sample_data"):
        scene = scene_of_sample.get(sd.get("sample_token"))
        if scene:
            pose_scene[sd["ego_pose_token"]] = scene
    poses = [
        p for p in _versioned_table(root, version, "ego_pose") if p["token"] in pose_scene
    ]
    return poses, pose_scene


def _drive_overlaps_polygon(
    root: Path, version: str, scene_token: str, polygon
) -> bool:
    poses, pose_scene = _poses_for_scenes(root, version, {scene_token})
    for p in poses:
        if pose_scene.get(p["token"]) != scene_token:
            continue
        t = p.get("translation", [0, 0, 0])
        if shapely.contains_xy(polygon, t[0], t[1]):
            return True
    return False


def _sampled_lidar_points_for_scene(nusc, scene_token: str, polygon, step: int):
    """Yield (points_xyz[N,3], labels_flat_driveable_or_None) for sampled keyframes."""
    scene = nusc.get("scene", scene_token)
    keyframes = []
    token = scene["first_sample_token"]
    while token:
        sample = nusc.get("sample", token)
        keyframes.append(sample)
        token = sample.get("next")
    for sample in keyframes[::step]:
        sd_token = sample["data"].get("LIDAR_TOP")
        if not sd_token:
            continue
        sd = nusc.get("sample_data", sd_token)
        # points in global/map frame
        from nuscenes.utils.data_classes import LidarPointCloud
        from pyquaternion import Quaternion

        pc = LidarPointCloud.from_file(nusc.get_sample_data_path(sd_token))
        cs = nusc.get("calibrated_sensor", sd["calibrated_sensor_token"])
        ego = nusc.get("ego_pose", sd["ego_pose_token"])
        pc.rotate(Quaternion(cs["rotation"]).rotation_matrix)
        pc.translate(np.array(cs["translation"]))
        pc.rotate(Quaternion(ego["rotation"]).rotation_matrix)
        pc.translate(np.array(ego["translation"]))
        pts = np.asarray(pc.points[:3, :].T, dtype=float)
        if len(pts) == 0:
            continue
        inside = np.asarray(shapely.contains_xy(polygon, pts[:, 0], pts[:, 1]), dtype=bool)
        if not inside.any():
            continue
        pts_in = pts[inside]
        labels_in = None
        # lidarseg labels if available for this sample_data
        try:
            lidarseg_token = None
            if hasattr(nusc, "get") :
                # nusc.lidarseg exists in some versions; also table presence
                pass
            # devkit: get('lidarseg', token) by sample_data token in some tables, else path
            lidarseg = nusc.get("lidarseg", sd_token)
            if lidarseg and isinstance(lidarseg, dict):
                from nuscenes.utils.data_io import load_bin_file
                import os as _os

                lab_path = _os.path.join(nusc.dataroot, lidarseg.get("filename", ""))
                if lab_path and _os.path.isfile(lab_path):
                    labels = np.fromfile(lab_path, dtype=np.uint8)
                    # determine flat.driveable_surface index from category if present
                    drive_idx = None
                    if hasattr(nusc, "lidarseg_name2idx_mapping") and isinstance(
                        nusc.lidarseg_name2idx_mapping, dict
                    ):
                        drive_idx = nusc.lidarseg_name2idx_mapping.get(
                            "flat.driveable_surface"
                        )
                    if drive_idx is None and hasattr(nusc, "category"):
                        for c in nusc.category:
                            if c.get("name") == "flat.driveable_surface":
                                drive_idx = c.get("index")
                                break
                    if drive_idx is not None and len(labels) == len(pts):
                        labels_in = (labels[inside] == int(drive_idx))
        except Exception:
            labels_in = None
        yield pts_in, labels_in


def _accumulate_drive_observations(acc, nusc, scene_token, polygon, drivable_union, step, ox, oy):
    import twin.area_coverage as ac

    sources = []
    for pts, labels in _sampled_lidar_points_for_scene(nusc, scene_token, polygon, step):
        src = ac.accumulate_drive(
            acc,
            pts,
            polygon,
            drivable_union,
            labels_flat_driveable=labels,
            ox=ox,
            oy=oy,
        )
        sources.append(src)
    if not sources:
        return "geometric_road_mask_fallback"
    if len(set(sources)) == 1:
        return sources[0]
    return sorted(set(sources))


def _format_suggest_table(rows):
    header = f"{'scene':<14} {'scene_token':<34} {'cells_gained':>12} {'rain':<6} {'night':<6}"
    lines = [header]
    for r in rows:
        lines.append(
            f"{str(r.get('scene','')):<14} {str(r.get('scene_token','')):<34} "
            f"{int(r.get('cells_gained',0)):>12} {str(bool(r.get('rain',False))):<6} {str(bool(r.get('night',False))):<6}"
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
    root = Path(dataroot)
    store_path = Path(store) if store else None
    if store_path is None:
        from twin.runner import default_store

        store_path = default_store()

    # Z1 resolution
    try:
        resolved = resolve_area_arg(str(area_arg), store_path)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    # validation (CLI may also check; enforce here for programmatic use)
    if top_n is None or int(top_n) < 1:
        print("--top must be an integer >= 1", file=sys.stderr)
        return 2
    if density_threshold is None or float(density_threshold) < 0:
        print("--density-threshold must be >= 0", file=sys.stderr)
        return 2
    top_n = int(top_n)
    density_threshold = float(density_threshold)

    # dataset presence check for required resources/tables (basic)
    required_tables = ["scene.json", "sample.json", "sample_data.json", "ego_pose.json", "log.json"]
    for t in required_tables:
        if not (root / version / t).is_file():
            print(f"missing dataset table: {root / version / t}", file=sys.stderr)
            return 2

    area_def = _read_area_json(resolved)
    location = area_def.get("location")
    if not location:
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
    except Exception as e:
        print(f"failed to load area/map resources: {e}", file=sys.stderr)
        return 2

    cells, origin = ac_mod.build_grid(rebuilt, drivable_union)
    baseline_acc = ac_mod.init_accumulator(cells)
    existing_drives = list(area_def.get("drives") or [])
    existing_tokens = {d.get("scene_token") for d in existing_drives if d.get("scene_token")}

    # instantiate NuScenes for version (explicit, not scan_scenes/DevkitSource)
    try:
        if _nusc_factory:
            nusc = _nusc_factory(version=version, dataroot=str(root), verbose=False)
        else:
            from nuscenes.nuscenes import NuScenes

            nusc = NuScenes(version, dataroot=str(root), verbose=False)
    except Exception as e:
        print(f"failed to load nuScenes {version} at {root}: {e}", file=sys.stderr)
        return 2

    baseline_sources = []
    for d in existing_drives:
        tok = d.get("scene_token")
        if not tok:
            continue
        try:
            src = _accumulate_drive_observations(
                baseline_acc, nusc, tok, rebuilt, drivable_union, SUGGEST_SWEEP_STEP, origin[0], origin[1]
            )
            baseline_sources.append(src)
        except Exception as e:
            print(f"failed to read baseline drive {tok}: {e}", file=sys.stderr)
            return 2

    baseline_records = ac_mod.cell_records(baseline_acc, density_threshold)

    # candidate discovery: trainval/version, same location, overlaps rebuilt polygon, exclude existing
    try:
        scene_rows = _scene_rows_for_location(root, version, location)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2

    candidate_rows = []
    try:
        for row in scene_rows:
            tok = row["scene_token"]
            if tok in existing_tokens:
                continue
            if not _drive_overlaps_polygon(root, version, tok, rebuilt):
                continue
            cand_acc = ac_mod.init_accumulator(cells)
            # start from baseline copy? marginal vs baseline means baseline+candidate
            for k, v in baseline_acc.items():
                cand_acc[k] = dict(v)
            src = _accumulate_drive_observations(
                cand_acc, nusc, tok, rebuilt, drivable_union, SUGGEST_SWEEP_STEP, origin[0], origin[1]
            )
            candidate_records = ac_mod.cell_records(cand_acc, density_threshold)
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
    except Exception as e:
        print(f"failed to evaluate candidates: {e}", file=sys.stderr)
        return 2

    ranked = ac_mod.rank_candidates(candidate_rows, baseline_records, existing_drives, top_n)
    available = ranked[: len(ranked)] if len(ranked) < top_n else ranked[:top_n]

    # write coverage.json next to resolved area (always, even empty candidates)
    cov_path = ac_mod.coverage_path_for_area(resolved)
    baseline_scene_tokens = [d.get("scene_token") for d in existing_drives if d.get("scene_token")]
    gs = sorted(set(baseline_sources + [r.get("ground_source") for r in candidate_rows if r.get("ground_source")]))
    extra = {
        "epsg_persisted_polygon": area_def.get("epsg"),
        "dataset_version_area": area_def.get("dataset_version"),
        "suggest_version": version,
        "dataroot": str(root),
        "store": str(store_path),
        "generated_with": "twin.area_coverage",
        "area_resolved_path": str(resolved),
    }
    doc = ac_mod.coverage_document(
        area_def.get("name") or resolved.stem,
        str(resolved),
        location,
        origin,
        baseline_records,
        density_threshold_pts_m2=density_threshold,
        ground_sources=gs,
        baseline_scene_tokens=baseline_scene_tokens,
        extra_metadata=extra,
    )
    ac_mod.atomic_write_json(cov_path, doc)

    # print table
    print(_format_suggest_table(available))

    if apply_changes and available:
        # append top-N ranked in ranked order, dedupe by scene_token, preserve keys/order of existing entries
        existing = list(area_def.get("drives") or [])
        seen = {d.get("scene_token") for d in existing if d.get("scene_token")}
        for r in available:
            tok = r.get("scene_token")
            if tok in seen:
                continue
            existing.append(_drive_entry_from_row(r))
            seen.add(tok)
        new_def = dict(area_def)
        new_def["drives"] = existing
        ac_mod.atomic_write_json(resolved, new_def)

    return 0
