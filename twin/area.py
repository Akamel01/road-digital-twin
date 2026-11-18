"""Study area: a polygon from HD-map intersections and the nuScenes drives that pass through it.

`twin area define` writes <store>/areas/<name>.json. The run store keeps run folders
named by run id, so the `areas` folder is never read as a run.
"""

import json
import sys
from pathlib import Path

import numpy as np
import shapely
from pyquaternion import Quaternion
from shapely.geometry import mapping

import twin.area_coverage as ac
from twin.devkit_compat import nuscenes_map_class
from twin.stages.load import MAP_ORIGIN_LATLON, run_crs

MIN_PREFIX = 8


def _table(root: Path, version: str, name: str) -> list[dict]:
    return json.loads((root / version / f"{name}.json").read_text())


def load_intersections(dataroot, location: str) -> dict[str, shapely.Polygon]:
    """Intersection road segments of one HD map: full token -> polygon, map frame."""
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


def drive_tokens(build: Path, defined: dict | None = None) -> list[str]:
    """Scene tokens of the drives an area build used (its drives.json lists scene names), in that order.
    The tokens come from the area definition <store>/areas/<area>.json, where the build folder is
    <area>-twin or <area>-merged. When ``defined`` is passed, its ``drives`` list is used instead of
    reading the sibling ``<name>.json``. [] when required data is missing or unreadable."""
    build = Path(build)
    name = build.name.removesuffix("-twin").removesuffix("-merged")
    try:
        if defined is None:
            defined_drives = json.loads((build.parent / f"{name}.json").read_text())["drives"]
        else:
            defined_drives = defined.get("drives") or []
        used = json.loads((build / "drives.json").read_text())
    except (OSError, ValueError, KeyError):
        return []
    token = {
        d["scene"]: d["scene_token"]
        for d in defined_drives
        if isinstance(d, dict) and d.get("scene") and d.get("scene_token")
    }
    return [token[d["scene"]] for d in used if isinstance(d, dict) and d.get("scene") in token]


VERSION = "v1.0-trainval"
# DECISION: a candidate scene counts when its ego path passes within this distance (m) of the area: LIDAR_TOP
# scans the area from neighbouring streets. Every scene that drives through Seaport's area is already in it.
LIDAR_REACH_M = 30.0


def _jt(root, version, name):
    p = root / version / f"{name}.json"
    if not p.is_file():
        raise FileNotFoundError(p)
    return json.loads(p.read_text())


def _rebuild_poly(area_def, root):
    polys = load_intersections(root, area_def["location"])
    return shapely.union_all([polys[t] for t in area_def["intersections"]]).buffer(float(area_def.get("buffer_m", 0.0)))


def _drivable_union(nusc_map, bounds):
    recs = nusc_map.get_records_in_patch(tuple(bounds), ["drivable_area"], "intersect")
    polys = []
    for tok in recs.get("drivable_area", []):
        for pt in nusc_map.get("drivable_area", tok).get("polygon_tokens", []):
            polys.append(nusc_map.extract_polygon(pt))
    return shapely.union_all(polys) if polys else shapely.Polygon()


def _build_indices(root, version, location):
    logs = {l["token"]: l for l in _jt(root, version, "log")}
    scenes = [s for s in _jt(root, version, "scene") if logs[s["log_token"]]["location"] == location]
    samples = {s["token"]: s for s in _jt(root, version, "sample")}
    cal = {c["token"]: c for c in _jt(root, version, "calibrated_sensor")}
    sample_data_table = _jt(root, version, "sample_data")
    sd_by_sample = {}
    for sd in sample_data_table:
        # nuScenes sample_data has no channel field; the sensor is in the path (samples/LIDAR_TOP/...).
        if "/LIDAR_TOP/" in sd.get("filename", ""):
            sd_by_sample.setdefault(sd["sample_token"], []).append(sd)
    del sample_data_table
    referenced = {sd["ego_pose_token"] for recs in sd_by_sample.values() for sd in recs}
    ego_table = _jt(root, version, "ego_pose")
    ego = {p["token"]: p for p in ego_table if p["token"] in referenced}
    del ego_table
    for recs in sd_by_sample.values():
        recs.sort(key=lambda r: (not r.get("is_key_frame", False), r["token"]))
    return logs, scenes, samples, sd_by_sample, ego, cal


def _keyframes(scene, samples):
    out, tok = [], scene["first_sample_token"]
    while tok:
        s = samples[tok]
        out.append(s)
        tok = s.get("next")
    return out


def _lidarseg_table(root, version):
    p = root / version / "lidarseg.json"
    if not p.is_file():
        return {}, None
    try:
        rows = json.loads(p.read_text())
        idx = {r["sample_data_token"]: r["filename"] for r in rows if r.get("sample_data_token") and r.get("filename")}
    except Exception:  # noqa: BLE001
        idx = {}
    didx = None
    cp = root / version / "category.json"
    if cp.is_file():
        try:
            for c in json.loads(cp.read_text()):
                if c.get("name") == "flat.driveable_surface":
                    didx = int(c["index"])
        except Exception:  # noqa: BLE001
            didx = None
    return idx, didx


def _world_xy(root, sd, cal, ego):
    pts = np.fromfile(root / sd["filename"], dtype=np.float32).reshape(-1, 5)[:, :3].T
    if pts.size == 0:
        return np.empty((0, 2), np.float32), 0
    pts = Quaternion(cal["rotation"]).rotation_matrix @ pts + np.array(cal["translation"])[:, None]
    pts = Quaternion(ego["rotation"]).rotation_matrix @ pts + np.array(ego["translation"])[:, None]
    xy = pts[:2].T.astype(np.float32, copy=False)
    n = xy.shape[0]
    del pts
    return xy, n


def _road_mask(xy, area_poly, drivable_union, root, lseg_idx, sd_token, didx, n_pts):
    in_area = shapely.contains_xy(area_poly, xy[:, 0], xy[:, 1])
    if not np.any(in_area):
        return np.zeros(len(xy), bool)
    road = np.zeros(len(xy), bool)
    fn = lseg_idx.get(sd_token)
    if fn and didx is not None:
        p = root / fn
        if p.is_file():
            try:
                lab = np.fromfile(p, dtype=np.uint8)
                if lab.size == n_pts:
                    road = (lab == np.uint8(didx)) & in_area
            except Exception:  # noqa: BLE001
                road = np.zeros(len(xy), bool)
    if not np.any(road):
        # geometric fallback: on drivable union (approx road surface)
        if drivable_union is not None and not drivable_union.is_empty:
            road = shapely.contains_xy(drivable_union, xy[:, 0], xy[:, 1]) & in_area
        else:
            road = in_area
    return np.asarray(road, bool)


def _overlapping_scene_tokens(scenes, samples, sd_by_sample, ego, area_poly):
    scene_of_sample = {s["token"]: s["scene_token"] for s in samples.values()}
    pose_scene = {}
    for st, recs in sd_by_sample.items():
        sc = scene_of_sample.get(st)
        if sc and recs:
            for r in recs:
                pose_scene[r["ego_pose_token"]] = sc
    if not pose_scene:
        return set()
    toks = [t for t in pose_scene if t in ego]
    if not toks:
        return set()
    xs = [ego[t]["translation"][0] for t in toks]
    ys = [ego[t]["translation"][1] for t in toks]
    inside = shapely.contains_xy(area_poly, xs, ys)
    return {pose_scene[t] for t, ok in zip(toks, inside) if ok}


def _observe(scene, samples, sd_by_sample, ego, cal, masks, area_poly, drivable_union, drive_count, point_count, root, lseg_idx, didx):
    seen = np.zeros_like(drive_count, dtype=np.uint8)
    for kf in _keyframes(scene, samples)[:: ac.SWEEP_STEP]:
        recs = sd_by_sample.get(kf["token"]) or []
        if not recs:
            continue
        sd = recs[0]
        ep, cs = ego.get(sd["ego_pose_token"]), cal.get(sd["calibrated_sensor_token"])
        if not ep or not cs or not shapely.contains_xy(area_poly, ep["translation"][0], ep["translation"][1]):
            continue
        try:
            xy, n = _world_xy(root, sd, cs, ep)
        except Exception:  # noqa: BLE001,S112
            continue
        if n == 0:
            continue
        road = _road_mask(xy, area_poly, drivable_union, root, lseg_idx, sd["token"], didx, n)
        ac.add_points(point_count, seen, masks, xy, road)
        del xy, road
    ac.close_drive(drive_count, seen)


def suggest_drives_command(area, top, density_threshold=50.0, apply=False, dataroot=None, store=None, version=VERSION, **_ignored):
    area_path = Path(area)
    if not area_path.is_file():
        print(f"area file not found: {area_path}", file=sys.stderr)
        return 2
    try:
        top_n = int(top)
        if top_n < 1:
            raise ValueError
    except Exception:  # noqa: BLE001
        print("--top must be an integer >= 1", file=sys.stderr)
        return 2
    thr = float(density_threshold)
    if thr < 0:
        print("--density-threshold must be >= 0", file=sys.stderr)
        return 2
    root = Path(dataroot) if dataroot else Path(".")
    for n in ("log", "scene", "sample", "sample_data", "ego_pose", "calibrated_sensor"):
        if not (root / version / f"{n}.json").is_file():
            print(f"missing dataset table: {root / version / f'{n}.json'}", file=sys.stderr)
            return 2
    try:
        area_def = json.loads(area_path.read_text())
        rebuilt = _rebuild_poly(area_def, root)
        nusc_map = nuscenes_map_class()(dataroot=str(root), map_name=area_def["location"])
        drivable = _drivable_union(nusc_map, rebuilt.bounds)
        logs, scenes, samples, sd_by_sample, ego, cal = _build_indices(root, version, area_def["location"])
    except Exception as e:  # noqa: BLE001
        print(str(e), file=sys.stderr)
        return 2

    lseg_idx, didx = _lidarseg_table(root, version)
    overlap = _overlapping_scene_tokens(scenes, samples, sd_by_sample, ego, rebuilt.buffer(LIDAR_REACH_M))
    existing = list(area_def.get("drives") or [])
    existing_tokens = {d.get("scene_token") for d in existing}
    masks = ac.build_masks(rebuilt, drivable)
    base_drive, base_pts = ac.new_grids(masks)
    by_token = {s["token"]: s for s in scenes}
    for tok in existing_tokens & overlap:
        sc = by_token.get(tok)
        if sc:
            _observe(sc, samples, sd_by_sample, ego, cal, masks, rebuilt, drivable, base_drive, base_pts, root, lseg_idx, didx)
    _, base_low = ac.density_low(masks, base_drive, base_pts, thr)
    base_low_set = set(zip(*np.where(base_low)))

    ex_rain = any(ac.flags(d.get("description"))[0] for d in existing)
    ex_night = any(ac.flags(d.get("description"))[1] for d in existing)
    ex_tod = {ac.flags(d.get("description"))[2] for d in existing} - {"unknown"}
    cands = []
    for sc in scenes:
        if sc["token"] not in overlap or sc["token"] in existing_tokens:
            continue
        cd, cp = base_drive.copy(), base_pts.copy()
        _observe(sc, samples, sd_by_sample, ego, cal, masks, rebuilt, drivable, cd, cp, root, lseg_idx, didx)
        _, low = ac.density_low(masks, cd, cp, thr)
        gained = len(base_low_set - set(zip(*np.where(low))))
        rain, night, tod = ac.flags(sc.get("description", ""))
        div = int((rain and not ex_rain) + (night and not ex_night) + (tod != "unknown" and tod not in ex_tod))
        cands.append({"scene": sc["name"], "scene_token": sc["token"], "date": logs[sc["log_token"]].get("date_captured"), "description": sc.get("description", ""), "cells_gained": int(gained), "rain": rain, "night": night, "diversity": div, "_d": cd, "_p": cp})
    ranked = ac.rank(cands, top_n)
    print(f"{'scene':<14} {'scene_token':<34} {'cells_gained':>12} {'rain':<6} {'night':<6}")
    for r in ranked:
        print(f"{r['scene']:<14} {r['scene_token']:<34} {r['cells_gained']:>12} {r['rain']!s:<6} {r['night']!s:<6}")

    fd, fp, base_tokens = base_drive, base_pts, [d.get("scene_token") for d in existing if d.get("scene_token")]
    if apply and ranked:
        drives_out = list(existing)
        seen = set(existing_tokens)
        for r in ranked:
            if r["scene_token"] in seen:
                continue
            drives_out.append({"scene": r["scene"], "scene_token": r["scene_token"], "date": r.get("date"), "description": r.get("description", ""), "rain": bool(r["rain"]), "build_input": not bool(r["rain"])})
            seen.add(r["scene_token"])
            fd, fp = r["_d"], r["_p"]
            base_tokens.append(r["scene_token"])
        nd = dict(area_def); nd["drives"] = drives_out
        ac.atomic_write_json(area_path, nd)
    ac.atomic_write_json(ac.coverage_path(area_path), ac.coverage_doc(area_def, area_path, masks, fd, fp, base_tokens, thr))
    return 0
