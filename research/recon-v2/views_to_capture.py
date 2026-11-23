"""split.json views (nuScenes global) -> capture frame (EPSG:32619 minus origin_offset), world->cam 4x4."""
import json
import sys

import numpy as np
from twin.stages.load import MAP_ORIGIN_LATLON, run_crs, to_run_pose

split, capture_json, out = sys.argv[1:4]
off = np.asarray(json.load(open(capture_json))["origin_offset"], float)
tr = run_crs(MAP_ORIGIN_LATLON)
res = []
for v in json.load(open(split))["views"]:
    c2w = to_run_pose(np.asarray(v["cam_to_global"]), tr)
    c2w[:3, 3] -= off
    res.append({"token": v["token"], "scene": v["scene"], "K": v["K"], "width": v["width"], "height": v["height"],
                "viewmat": np.linalg.inv(c2w).tolist()})
json.dump({"views": res, "exclude": json.load(open(split))["train_exclude_us"]}, open(out, "w"))
print(len(res), "views ->", out)
