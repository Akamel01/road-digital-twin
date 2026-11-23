"""Harness split -> drivestudio timesteps for one scene (10 Hz interpolated: keyframe k sits at t = 5k).

Writes {"test": [...], "exclude": [...], "views": {"<t>_<cam>": token}} and checks that each test image is the keyframe image."""
import filecmp
import json
import sys

scene_name, scene_dir, out = sys.argv[1:4]
CAMS = ["CAM_FRONT", "CAM_FRONT_LEFT", "CAM_FRONT_RIGHT", "CAM_BACK_LEFT", "CAM_BACK_RIGHT", "CAM_BACK"]
with open("/data/recon-v2/a1/split.json") as f:
    split = json.load(f)
views = [v for v in split["views"] if v["scene"] == scene_name]
with open("/data/nuscenes/v1.0-trainval/scene.json") as f:
    sc = next(s for s in json.load(f) if s["name"] == scene_name)
with open("/data/nuscenes/v1.0-trainval/sample.json") as f:
    samples = {s["token"]: s for s in json.load(f)}
order, tok = [], sc["first_sample_token"]
while tok:
    order.append(tok)
    tok = samples[tok]["next"]
kf = {t: i for i, t in enumerate(order)}
test, vmap, bad = set(), {}, 0
for v in views:
    t = 5 * kf[v["sample"]]
    c = CAMS.index(v["channel"])
    test.add(t)
    vmap[f"{t}_{c}"] = v["token"]
    if not filecmp.cmp(f"{scene_dir}/images/{t:03d}_{c}.jpg", "/data/nuscenes/" + v["image"], shallow=False):
        bad += 1
excl = sorted({t + d for t in test for d in range(-3, 4) if t + d >= 0})
with open(out, "w") as f:
    json.dump({"test": sorted(test), "exclude": excl, "views": vmap}, f)
print(len(views), "views", len(test), "test timesteps", len(excl), "excluded", "image mismatches:", bad)
