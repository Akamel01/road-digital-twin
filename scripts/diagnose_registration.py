"""Split the cross-drive ground residual of an area merge into causes (issue #190). Usage:
python scripts/diagnose_registration.py <area.json> <merged-folder> [out.json]
Per pair, on the ground cells both drives see after registration (dz = a - b): a constant offset, a planar tilt,
a horizontal shift (dz explained by the ground slope times an xy shift), and the rest (layer mix-up, noise)."""

import json
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import shape

from twin import merge


def load(area_f, folder):
    area = json.loads(Path(area_f).read_text())
    poly = shape(area["polygon"])
    centre = np.array([*poly.centroid.coords[0], 0.0])
    drives = json.loads((Path(folder) / "drives.json").read_text())
    cells = {}
    for d in drives:
        k = d["scene"]
        found = merge.drive_ground(Path(folder) / "drives" / k, poly)
        g = merge.world_ground(*found)[:, :3]
        c = d["correction"] or {"dx_m": 0, "dy_m": 0, "dz_m": 0, "yaw_deg": 0}
        y = np.radians(c["yaw_deg"])
        t = np.eye(4)
        t[:2, :2] = [[np.cos(y), -np.sin(y)], [np.sin(y), np.cos(y)]]
        t[:3, 3] = [c["dx_m"], c["dy_m"], c["dz_m"]]
        cells[k] = merge.ground_cells(merge.apply(t, g - centre))
    return cells


def split(ca, cb):
    keys = sorted(ca.keys() & cb.keys())
    if len(keys) < merge.MIN_CELLS:
        return None
    xy = np.array(keys, float) * merge.CELL_M
    dz = np.array([ca[k] - cb[k] for k in keys])
    n = len(dz)
    total = float(np.mean(dz**2))
    # gradient of drive b's ground (central differences on its cells)
    gx = np.array(
        [cb.get((i + 1, j), np.nan) - cb.get((i - 1, j), np.nan) for i, j in keys]
    ) / (2 * merge.CELL_M)
    gy = np.array(
        [cb.get((i, j + 1), np.nan) - cb.get((i, j - 1), np.nan) for i, j in keys]
    ) / (2 * merge.CELL_M)
    ok = np.isfinite(gx) & np.isfinite(gy) & (np.hypot(gx, gy) < 0.3)
    c = np.median(dz)
    r1 = dz - c
    A = np.column_stack([xy[:, 0] - xy[:, 0].mean(), xy[:, 1] - xy[:, 1].mean()])
    coef, *_ = np.linalg.lstsq(A, r1, rcond=None)
    r2 = r1 - A @ coef
    B = np.column_stack([gx[ok], gy[ok], np.ones(ok.sum())])
    sh, *_ = np.linalg.lstsq(B, r2[ok], rcond=None)
    r3 = r2.copy()
    r3[ok] = r2[ok] - B @ sh
    layer = np.abs(r3) > 0.5
    ms = lambda v: float(np.mean(v**2))
    p95 = lambda v: float(np.percentile(np.abs(v), 95))
    return {
        "n_cells": n,
        "p95_m": p95(dz),
        "offset_m": float(c),
        "tilt_deg": float(np.degrees(np.hypot(*coef))),
        "shift_xy_m": [float(sh[0]), float(sh[1])],
        "share_offset": float(c**2 / total),
        "share_tilt": float((ms(r1) - ms(r2)) / total),
        "share_shift": float((ms(r2) - ms(r3)) / total),
        "share_rest": float(ms(r3) / total),
        "share_layer": float(np.sum(r3[layer] ** 2) / n / total),
        "p95_after_offset_m": p95(r1),
        "p95_after_tilt_m": p95(r2),
        "p95_after_shift_m": p95(r3),
        "rms_dz_m": float(np.sqrt(total)),
    }


if __name__ == "__main__":
    cells = load(sys.argv[1], sys.argv[2])
    ids = sorted(cells)
    rows = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            r = split(cells[a], cells[b])
            if r:
                rows.append({"a": a, "b": b, **r})
    rows.sort(key=lambda r: r["p95_m"])
    mid = len(rows) // 2
    pick = rows[-5:][::-1] + rows[mid - 2 : mid + 3]
    print(
        "pair  p95  | share offset tilt shift rest(layer) | offset_m tilt_deg shift_xy"
    )
    for r in pick:
        print(
            f"{r['a'][6:]}-{r['b'][6:]} {r['p95_m']:.2f} | {r['share_offset']:.2f} {r['share_tilt']:.2f} {r['share_shift']:.2f} {r['share_rest']:.2f}({r['share_layer']:.2f}) | {r['offset_m']:+.2f} {r['tilt_deg']:.2f} {r['shift_xy_m'][0]:+.2f},{r['shift_xy_m'][1]:+.2f}"
        )
    a = np.array(
        [
            [r[k] for k in ("share_offset", "share_tilt", "share_shift", "share_rest")]
            for r in rows
        ]
    )
    print("mean shares all pairs", a.mean(0).round(2), "n", len(rows))
    print(
        "median p95 all",
        np.median([r["p95_m"] for r in rows]),
        "after offset",
        np.median([r["p95_after_offset_m"] for r in rows]),
        "after tilt",
        np.median([r["p95_after_tilt_m"] for r in rows]),
        "after shift",
        np.median([r["p95_after_shift_m"] for r in rows]),
    )
    Path(sys.argv[3] if len(sys.argv) > 3 else "diag.json").write_text(
        json.dumps(rows, indent=1)
    )
