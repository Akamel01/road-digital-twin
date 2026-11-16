"""Compact area coverage for suggest-drives (#253). numpy grids only."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
import shapely

CELL_M = 5.0
SWEEP_STEP = 4
DENSITY_THRESHOLD = 50.0


def build_masks(area_poly, drivable_union):
    minx, miny, maxx, maxy = area_poly.bounds
    ox = math.floor(minx / CELL_M) * CELL_M
    oy = math.floor(miny / CELL_M) * CELL_M
    nx = max(math.ceil((maxx - ox) / CELL_M), 1)
    ny = max(math.ceil((maxy - oy) / CELL_M), 1)
    xs = ox + (np.arange(nx) + 0.5) * CELL_M
    ys = oy + (np.arange(ny) + 0.5) * CELL_M
    xx, yy = np.meshgrid(xs, ys)
    in_area = shapely.contains_xy(area_poly, xx.ravel(), yy.ravel()).reshape(ny, nx)
    bx = ox + np.arange(nx) * CELL_M
    by = oy + np.arange(ny) * CELL_M
    bxx, byy = np.meshgrid(bx, by)
    boxes = shapely.box(bxx.ravel(), byy.ravel(), bxx.ravel() + CELL_M, byy.ravel() + CELL_M)
    if drivable_union is None or drivable_union.is_empty:
        eligible = np.zeros((ny, nx), dtype=bool)
    else:
        inter = shapely.intersection(boxes, drivable_union)
        eligible = (shapely.area(inter) > 0).reshape(ny, nx)
    eligible &= in_area
    return {"ox": float(ox), "oy": float(oy), "nx": nx, "ny": ny, "in_area": in_area, "eligible": eligible}


def new_grids(masks):
    shp = (masks["ny"], masks["nx"])
    return np.zeros(shp, np.int32), np.zeros(shp, np.int32)


def add_points(point_count, seen, masks, xy, road_mask):
    if xy.size == 0:
        return
    idx = np.flatnonzero(road_mask)
    if idx.size == 0:
        return
    x, y = xy[idx, 0], xy[idx, 1]
    ix = np.floor((x - masks["ox"]) / CELL_M).astype(np.int64)
    iy = np.floor((y - masks["oy"]) / CELL_M).astype(np.int64)
    ok = (ix >= 0) & (ix < masks["nx"]) & (iy >= 0) & (iy < masks["ny"])
    ix, iy = ix[ok], iy[ok]
    if ix.size == 0:
        return
    ok = masks["in_area"][iy, ix]
    ix, iy = ix[ok], iy[ok]
    if ix.size == 0:
        return
    flat = iy * masks["nx"] + ix
    np.add.at(point_count.ravel(), flat, 1)
    seen.ravel()[flat] = 1


def close_drive(drive_count, seen):
    drive_count += (seen > 0).astype(np.int32)
    seen.fill(0)


def density_low(masks, drive_count, point_count, threshold=DENSITY_THRESHOLD):
    density = point_count.astype(np.float32) / (CELL_M * CELL_M)
    low = masks["eligible"] & ((drive_count < 2) | (density < float(threshold)))
    return density, low


def coverage_doc(area_def, area_path, masks, drive_count, point_count, baseline_tokens, threshold=DENSITY_THRESHOLD):
    density, low = density_low(masks, drive_count, point_count, threshold)
    cells = []
    for iy in range(masks["ny"]):
        for ix in range(masks["nx"]):
            if not masks["in_area"][iy, ix]:
                continue
            cells.append({
                "ix": ix, "iy": iy,
                "x0": float(masks["ox"] + ix * CELL_M),
                "y0": float(masks["oy"] + iy * CELL_M),
                "road_eligible": bool(masks["eligible"][iy, ix]),
                "drive_count": int(drive_count[iy, ix]),
                "density_pts_m2": float(density[iy, ix]),
                "road_surface_points": int(point_count[iy, ix]),
                "low_coverage": bool(low[iy, ix]),
            })
    return {
        "schema_version": 1,
        "area": area_def.get("name") or Path(area_path).stem,
        "area_path": str(area_path),
        "location": area_def.get("location"),
        "frame": "nuScenes-local-tmerc",
        "grid_origin_map": [masks["ox"], masks["oy"]],
        "cell_m": CELL_M,
        "density_threshold_pts_m2": float(threshold),
        "sweep_step": SWEEP_STEP,
        "density_semantics": "sampled_every_4th_keyframe",
        "baseline_scene_tokens": list(baseline_tokens),
        "cells": cells,
    }


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def coverage_path(area_path):
    p = Path(area_path)
    return p.with_name(f"{p.stem}.coverage.json")


def flags(desc):
    d = (desc or "").lower()
    rain = "rain" in d
    night = "night" in d
    tod = "unknown"
    for kw in ("night", "dawn", "dusk", "morning", "afternoon", "evening", "day"):
        if kw in d:
            tod = kw
            break
    return rain, night, tod


def rank(cands, top_n):
    return sorted(cands, key=lambda r: (-r["cells_gained"], -r["diversity"], r.get("scene", ""), r.get("scene_token", "")))[: max(0, int(top_n))]
