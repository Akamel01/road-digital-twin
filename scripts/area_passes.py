"""Rank nuScenes intersections by how many trainval drives pass through them (keyframe LIDAR_TOP ego poses)."""
import json
from collections import defaultdict

import matplotlib.pyplot as plt
from shapely.geometry import Point
from shapely.strtree import STRtree

plt.style.use = lambda s: None  # the devkit asks for a style this matplotlib lacks
from nuscenes.map_expansion.map_api import NuScenesMap

root = "/data/nuscenes"
def j(n): return json.load(open(f"{root}/v1.0-trainval/{n}.json"))

scenes, logs, samples = j("scene"), {l["token"]: l for l in j("log")}, j("sample")
ego = {e["token"]: e for e in j("ego_pose")}
sd = j("sample_data")
lidar_kf = {}  # sample -> ego_pose token
for s in sd:
    if s["is_key_frame"] and "LIDAR_TOP" in s["filename"]:
        lidar_kf[s["sample_token"]] = s["ego_pose_token"]
by_scene = defaultdict(list)
for s in samples:
    by_scene[s["scene_token"]].append(s)

maps = {}
out = defaultdict(lambda: {"scenes": set(), "night": 0, "rain": 0})
for sc in scenes:
    loc = logs[sc["log_token"]]["location"]
    if loc not in maps:
        m = NuScenesMap(root, loc)
        polys = [(r["token"], m.extract_polygon(r["polygon_token"])) for r in m.road_segment if r["is_intersection"]]
        maps[loc] = (polys, STRtree([p for _, p in polys]))
    polys, tree = maps[loc]
    hit = set()
    for smp in by_scene[sc["token"]]:
        x, y, _ = ego[lidar_kf[smp["token"]]]["translation"]
        for i in tree.query(Point(x, y)):
            if polys[i][1].contains(Point(x, y)):
                hit.add(polys[i][0])
    d = sc["description"].lower()
    for t in hit:
        o = out[(loc, t)]
        o["scenes"].add(sc["name"])
        o["night"] += "night" in d
        o["rain"] += "rain" in d

rank = sorted(out.items(), key=lambda kv: -len(kv[1]["scenes"]))
for (loc, t), o in rank[:25]:
    c = maps[loc][0][[k for k, _ in maps[loc][0]].index(t)][1].centroid
    print(f"{len(o['scenes']):3d} scenes  night {o['night']:2d} rain {o['rain']:2d}  {loc:22s} {t[:8]}  ({c.x:.0f},{c.y:.0f})  {sorted(o['scenes'])[:6]}")
with open("/data/area_passes.json", "w") as f:
    json.dump({f"{l}/{t}": sorted(o["scenes"]) for (l, t), o in rank[:25]}, f, indent=1)
