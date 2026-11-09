"""Study area: a polygon from HD-map intersections and the nuScenes drives that pass through it.

`twin area define` writes <store>/areas/<name>.json. The run store keeps run folders
named by run id, so the `areas` folder is never read as a run.
"""

import json
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
