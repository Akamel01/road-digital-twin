"""#425: where do drive groups A and B disagree? Per 0.5 m cell ground height (merge.ground_cells) per drive."""
import json

import numpy as np
from PIL import Image
from twin import merge

M = "/data/twin-sites/areas/site-a1-signal-merged"
A = ["scene-0233", "scene-0248", "scene-0295", "scene-0714", "scene-0715"]
B = ["scene-0234", "scene-0259", "scene-0296", "scene-0297", "scene-0716"]
idx = {r["scene"]: r["index"] for r in json.load(open(f"{M}/drives.json"))}
z = np.load(f"{M}/merged.npz")
x, y, zz, d = z["x"], z["y"], z["z"], z["drive"]
cells = {}
for s in A + B:
    m = d == idx[s]
    cells[s] = merge.ground_cells(np.column_stack([x[m], y[m], zz[m]]))
    print(s, len(cells[s]), flush=True)

def group(names):
    keys = set().union(*[cells[n].keys() for n in names])
    out = {}
    for k in keys:
        v = [cells[n][k] for n in names if k in cells[n]]
        if len(v) >= 2:
            out[k] = (float(np.median(v)), float(np.min(v)), float(np.max(v)), len(v))
    return out

ga, gb = group(A), group(B)
shared = sorted(ga.keys() & gb.keys())
dz = np.array([ga[k][0] - gb[k][0] for k in shared])
ij = np.array(shared)
print("shared cells", len(shared), "|dz| p50 %.2f p95 %.2f" % tuple(np.percentile(np.abs(dz), [50, 95])))
bad = np.abs(dz) > 1.0
print("cells |dz|>1 m:", int(bad.sum()), "A higher:", int((dz > 1).sum()), "B higher:", int((dz < -1).sum()))
# within-group spread at bad cells: is the high group itself consistent?
spreadA = np.array([ga[k][2] - ga[k][1] for k in shared])
spreadB = np.array([gb[k][2] - gb[k][1] for k in shared])
print("bad cells: within-A spread p50 %.2f, within-B spread p50 %.2f" % (np.median(spreadA[bad]), np.median(spreadB[bad])))
print("bad cells: dz values p10/50/90", np.round(np.percentile(dz[bad], [10, 50, 90]), 2))
# image: grey = shared ok, red = A higher, blue = B higher
i0, j0 = ij.min(0)
W, H = ij[:, 0].max() - i0 + 1, ij[:, 1].max() - j0 + 1
img = np.full((H, W, 3), 255, np.uint8)
for (i, j), v in zip(ij, dz):
    c = (200, 200, 200) if abs(v) <= 0.3 else ((255, 140, 0) if abs(v) <= 1 else ((220, 0, 0) if v > 0 else (0, 60, 220)))
    img[H - 1 - (j - j0), i - i0] = c
Image.fromarray(img).resize((W * 3, H * 3), Image.NEAREST).save("/data/recon-v2/a1/ab_cells.png")
# connected clusters of bad cells, largest first, with centres in UTM
from scipy.ndimage import label

grid = np.zeros((H, W), bool)
for (i, j), b in zip(ij, bad):
    grid[j - j0, i - i0] = b
lab, n = label(grid)
sizes = np.bincount(lab.ravel())[1:]
for c in np.argsort(-sizes)[:6]:
    jj, ii = np.nonzero(lab == c + 1)
    sel = [k for k, (i, j) in enumerate(ij) if lab[j - j0, i - i0] == c + 1]
    print("cluster %d cells, centre UTM (%.1f, %.1f), dz median %.2f m" % (sizes[c], (ii.mean() + i0 + 0.5) * merge.CELL_M,
          (jj.mean() + j0 + 0.5) * merge.CELL_M, np.median(dz[sel])))

# --- road-only: cells whose centre is inside the HD map drivable_area (reference.geojson, run CRS)
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union

ref = json.load(open(f"{M}/drives/scene-0233/1_load/reference.geojson"))
drv = unary_union([shape(f["geometry"]) for f in ref["features"] if f["properties"].get("layer") == "drivable_area"])
cx, cy = (ij[:, 0] + 0.5) * merge.CELL_M, (ij[:, 1] + 0.5) * merge.CELL_M
road = contains_xy(drv, cx, cy)
print("ROAD cells", int(road.sum()), "|dz| p50 %.2f p95 %.2f" % tuple(np.percentile(np.abs(dz[road]), [50, 95])),
      "| >1 m:", int((np.abs(dz[road]) > 1).sum()))
print("OFF-ROAD cells", int((~road).sum()), "|dz| p50 %.2f p95 %.2f" % tuple(np.percentile(np.abs(dz[~road]), [50, 95])),
      "| >1 m:", int((np.abs(dz[~road]) > 1).sum()))
for name, sel in (("road", road),):
    a = np.abs(dz[sel]); print("road |dz| p90 %.2f p99 %.2f max %.2f" % (np.percentile(a, 90), np.percentile(a, 99), a.max()))
