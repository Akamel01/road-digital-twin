import json
import sys

import numpy as np
from PIL import Image, ImageDraw

s = json.load(open("a1/split.json"))
def n(v):
    return np.load("a1/gt/%s.npz" % v["token"])["z"].size if v["channel"] == "CAM_FRONT" else -1
best = max(s["views"], key=n)
g = np.load("a1/gt/%s.npz" % best["token"])
im = Image.open("/data/nuscenes/" + best["image"]).convert("RGB")
d = ImageDraw.Draw(im)
for u, v, z, c in zip(g["u"], g["v"], g["z"], g["cls"]):
    col = (255, int(max(0, 255 - z * 8)), 0) if c == 24 else (0, 200, 255)
    d.ellipse([u - 2, v - 2, u + 2, v + 2], fill=col)
im.resize((800, 450)).save(sys.argv[1])
print(best["scene"], best["channel"], g["z"].size)
