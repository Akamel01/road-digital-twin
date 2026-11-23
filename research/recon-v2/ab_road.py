"""#425 part 2: A vs B disagreement on nuScenes-lidarseg driveable_surface points only (keyframe sweeps).

Recovers per-point lidarseg for merged.npz rows: merge.build_drive keeps mask points inside the polygon in order,
so merged rows of drive k == mask points[keep] of drive k (after the area correction)."""
import json
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape
from twin import merge
from twin.stages import ground, mask

M = "/data/twin-sites/areas/site-a1-signal-merged"
area = json.load(open("/data/twin-sites/areas/site-a1-signal.json"))
poly = shape(area["polygon"])
A = ["scene-0233", "scene-0248", "scene-0295", "scene-0714", "scene-0715"]
B = ["scene-0234", "scene-0259", "scene-0296", "scene-0297", "scene-0716"]
idx = {r["scene"]: r["index"] for r in json.load(open(f"{M}/drives.json"))}
z = np.load(f"{M}/merged.npz")
cells, park = {}, {}
for s in A + B:
    w = Path(f"{M}/drives/{s}")
    with np.load(f"{w}/2_mask/points.npz") as f:
        fields = {k: f[k] for k in mask.POINT_FIELDS}
        seg = f["lidarseg"] if "lidarseg" in f.files else None
    xyz, _, _ = ground.aligned_points(fields, merge._poses(merge.stage_dir(w, "load")), merge._poses(merge.stage_dir(w, "align")))
    keep = shapely.contains_xy(poly, xyz[:, 0], xyz[:, 1])
    rows = np.flatnonzero(z["drive"] == idx[s])
    assert rows.size == keep.sum(), (s, rows.size, keep.sum())
    lab = seg[keep]
    r = rows[lab == 24]
    cells[s] = merge.ground_cells(np.column_stack([z["x"][r], z["y"][r], z["z"][r]]))
    print(s, "road pts", r.size, "cells", len(cells[s]), flush=True)

def med(names):
    out = {}
    for k in set().union(*[cells[n].keys() for n in names]):
        v = [cells[n][k] for n in names if k in cells[n]]
        if len(v) >= 2:
            out[k] = float(np.median(v))
    return out

ga, gb = med(A), med(B)
sh = sorted(ga.keys() & gb.keys())
dz = np.array([ga[k] - gb[k] for k in sh])
a = np.abs(dz)
print("LIDARSEG ROAD cells", len(sh), "|dz| p50 %.3f p90 %.3f p95 %.3f p99 %.3f max %.2f, >0.3 m: %d"
      % (*np.percentile(a, [50, 90, 95, 99]), a.max(), int((a > 0.3).sum())))
print("signed dz median %.3f (A minus B)" % np.median(dz))
# within-group (pairwise) for reference
def pair_p95(names):
    vals = []
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            r = merge.ground_disagreement(cells[x], cells[y])
            if r: vals.append(r["p95_m"])
    return np.round(vals, 3)
print("within A pair p95:", pair_p95(A)); print("within B pair p95:", pair_p95(B))
