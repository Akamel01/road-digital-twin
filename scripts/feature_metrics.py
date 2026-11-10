"""Before/after check for crosswalk and curb extraction (issue #158 approach).

usage: feature_metrics.py RUN_DIR [RUN_DIR ...] [--plot out.png]
Per run: feature count, false-positive rate (share of 0.25 m boundary samples farther than the radius from the
map reference) and matched P50/P95 (samples within the radius). Crosswalks use ped_crossing, curbs the
drivable_area boundary. The plot shows one panel per run over the HD map.
"""

import argparse
import json

import matplotlib
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import shape

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RADIUS_M = 1.0


def _fc(run, p):
    try:
        return json.load(open(f"{run}/{p}"))["features"]
    except FileNotFoundError:
        return []


def _g(f):
    return shapely.force_2d(shape(f["geometry"]))


def _samples(g):
    o = g.boundary if g.geom_type in ("Polygon", "MultiPolygon") else g
    return shapely.points(shapely.get_coordinates(shapely.segmentize(o, 0.25)))


def metrics(run, radius=RADIUS_M):
    ref = [(f["properties"]["layer"], _g(f)) for f in _fc(run, "1_load/reference.geojson")]
    ped = shapely.union_all([g for k, g in ref if k == "ped_crossing"])
    dab = shapely.union_all([g for k, g in ref if k == "drivable_area"]).boundary
    out = {}
    for name, ref_g, feats in (
        ("crosswalks", ped, _fc(run, "5_features/crosswalks.geojson")),
        ("curbs", dab, _fc(run, "5_features/curbs.geojson")),
    ):
        d = [shapely.distance(_samples(_g(f)), ref_g) for f in feats]
        allz = np.concatenate(d) if d else np.array([])
        m = allz[allz <= radius]
        out[name] = {
            "n": len(feats),
            "fp_rate_samples": round(float((allz > radius).mean()), 3) if len(allz) else None,
            "fp_features": int(sum(x.min() > radius for x in d)),
            "matched_p50": round(float(np.percentile(m, 50)), 3) if len(m) else None,
            "matched_p95": round(float(np.percentile(m, 95)), 3) if len(m) else None,
            "matched_n": len(m),
        }
    return out


def plot(runs, path):
    r0 = runs[0]
    ref = _fc(r0, "1_load/reference.geojson")
    allg = [_g(f) for f in ref if f["properties"]["layer"] == "drivable_area"]
    x0, y0, x1, y1 = shapely.union_all(allg).bounds
    cols = {"drivable_area": "#dddddd", "ped_crossing": "#9ecae1", "stop_line": "#fdd0a2",
            "lane_divider": "g", "road_divider": "darkgreen"}
    fig, axs = plt.subplots(1, len(runs), figsize=(10 * len(runs), 10), squeeze=False)
    for ax, run in zip(axs[0], runs, strict=True):
        for f in ref:
            g = affinity.translate(_g(f), -x0, -y0)
            c = cols.get(f["properties"]["layer"], "gray")
            for p in getattr(g, "geoms", [g]):
                if p.geom_type == "Polygon":
                    ax.fill(*p.exterior.xy, fc=c, ec="gray", alpha=0.6)
                else:
                    ax.plot(*p.xy, color=c, lw=2)
        for name, color in (("crosswalks", "red"), ("curbs", "magenta"), ("markings", "orange")):
            for f in _fc(run, f"5_features/{name}.geojson"):
                g = affinity.translate(_g(f), -x0, -y0)
                for p in getattr(g, "geoms", [g]):
                    if p.geom_type == "Polygon":
                        ax.fill(*p.exterior.xy, fc=color, ec="darkred", alpha=0.8)
                    else:
                        ax.plot(*p.xy, color=color, lw=2)
        m = metrics(run)
        ax.set_title(f"{run.rstrip('/').split('/')[-1]}  crosswalks {m['crosswalks']['n']}, curbs {m['curbs']['n']}")
        ax.set_aspect("equal")
        ax.set_xlim(0, x1 - x0)
        ax.set_ylim(0, y1 - y0)
    fig.savefig(path, dpi=70, bbox_inches="tight")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--plot")
    a = ap.parse_args()
    for r in a.runs:
        print(r, json.dumps(metrics(r)))
    if a.plot:
        plot(a.runs, a.plot)
