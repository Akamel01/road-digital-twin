"""Area coverage: per-5m-cell drive counts and sampled road-surface density.

Pure/testable core for ticket #253. Semantics are pinned by the plan:
- Coverage/overlap/grid in nuScenes map frame (local tmerc, meters) rebuilt from
  stored intersections+buffer_m (B1). Never use persisted EPSG:32619 polygon for tests.
- Grid: 5m, aligned to floor(min_x/min_y / 5)*5 of rebuilt map-frame polygon bounds.
  In-area iff cell center inside rebuilt map-frame polygon.
- Drivable union from get_records_in_patch(bounds, ["drivable_area"], "intersect")
  with no pad, reused for eligibility and geometric fallback (I2).
- road_eligible iff cell_box.intersection(drivable_union).area > 0 (I1).
- Road-surface point: lidarseg flat.driveable_surface when labels provided, else
  geometric road_mask-equivalent fallback using same drivable union (I1/I2).
- Covered cell iff >=1 road-surface point of a drive falls in that in-area cell
  after filtering to rebuilt map-frame area polygon.
- Low-coverage (eligible only): drive_count < 2 OR density_pts_m2 < threshold.
  density_pts_m2 = road_surface_points_in_cell / 25.0 (sampled semantics, sweep_step 4).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely

from twin.select import CELL_M, GROUND_TOL_M

SWEEP_STEP = 4
DENSITY_THRESHOLD_PTS_M2 = 50.0
SCHEMA_VERSION = 1
FRAME = "nuScenes-local-tmerc"
DENSITY_SEMANTICS = "sampled_every_4th_keyframe"
ROAD_ELIGIBLE_RULE = "cell_box.intersection(drivable_union).area > 0"


@dataclass(frozen=True)
class Cell:
    ix: int
    iy: int
    x0: float
    y0: float
    road_eligible: bool
    center_inside: bool


def rebuild_map_frame_polygon(
    intersection_polygons: dict[str, shapely.Geometry],
    tokens: list[str],
    buffer_m: float,
):
    """Rebuild area polygon in nuScenes map frame (meters)."""
    return shapely.union_all([intersection_polygons[t] for t in tokens]).buffer(buffer_m)


def grid_origin(polygon) -> tuple[float, float]:
    minx, miny, _, _ = polygon.bounds
    return math.floor(minx / CELL_M) * CELL_M, math.floor(miny / CELL_M) * CELL_M


def build_grid(polygon, drivable_union) -> tuple[list[Cell], tuple[float, float]]:
    """Build deterministic in-area cell list and grid origin."""
    ox, oy = grid_origin(polygon)
    minx, miny, maxx, maxy = polygon.bounds
    ix0 = math.floor((minx - ox) / CELL_M)
    iy0 = math.floor((miny - oy) / CELL_M)
    ix1 = math.ceil((maxx - ox) / CELL_M)
    iy1 = math.ceil((maxy - oy) / CELL_M)
    cells: list[Cell] = []
    for iy in range(iy0, iy1):
        for ix in range(ix0, ix1):
            x0 = ox + ix * CELL_M
            y0 = oy + iy * CELL_M
            cx = x0 + CELL_M / 2.0
            cy = y0 + CELL_M / 2.0
            if not shapely.contains_xy(polygon, cx, cy):
                continue
            cell_box = shapely.box(x0, y0, x0 + CELL_M, y0 + CELL_M)
            inter = cell_box.intersection(drivable_union)
            road_eligible = (not inter.is_empty) and (inter.area > 0.0)
            cells.append(
                Cell(
                    ix=ix,
                    iy=iy,
                    x0=float(x0),
                    y0=float(y0),
                    road_eligible=road_eligible,
                    center_inside=True,
                )
            )
    cells.sort(key=lambda c: (c.ix, c.iy))
    return cells, (float(ox), float(oy))


def _ground_z_by_cell(points_xyz: np.ndarray):
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    if len(pts) == 0:
        return {}
    cells = np.floor(pts[:, :2] / CELL_M).astype(np.int64)
    z = pts[:, 2]
    ground_z: dict[tuple[int, int], list[float]] = {}
    for i in range(len(pts)):
        key = (int(cells[i, 0]), int(cells[i, 1]))
        ground_z.setdefault(key, []).append(float(z[i]))
    return {k: float(np.percentile(np.asarray(v), 5)) for k, v in ground_z.items()}


def geometric_road_mask(points_xyz: np.ndarray, drivable_union) -> np.ndarray:
    """Geometric road mask equivalent to twin.select.road_mask using same union."""
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    mask = np.zeros(len(pts), dtype=bool)
    if len(pts) == 0 or drivable_union is None or drivable_union.is_empty:
        return mask
    idx = np.flatnonzero(shapely.contains_xy(drivable_union, pts[:, 0], pts[:, 1]))
    if idx.size == 0:
        return mask
    gz = _ground_z_by_cell(pts[idx])
    cells = np.floor(pts[idx, :2] / CELL_M).astype(np.int64)
    keep = np.zeros(idx.size, dtype=bool)
    for j, i in enumerate(idx):
        key = (int(cells[j, 0]), int(cells[j, 1]))
        keep[j] = abs(float(pts[i, 2]) - gz[key]) <= GROUND_TOL_M
    mask[idx[keep]] = True
    return mask


def road_surface_mask(
    points_xyz: np.ndarray,
    drivable_union,
    labels_flat_driveable: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
    """Return (mask, ground_source) for road-surface points.

    labels_flat_driveable: optional bool/0-1 array aligned with points marking
    lidarseg flat.driveable_surface. If provided and non-None, used as primary.
    """
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    if labels_flat_driveable is not None:
        lbl = np.asarray(labels_flat_driveable).reshape(-1).astype(bool)
        if len(lbl) != len(pts):
            raise ValueError("labels_flat_driveable length must match points")
        return lbl, "lidarseg_flat.driveable_surface"
    return geometric_road_mask(pts, drivable_union), "geometric_road_mask_fallback"


def filter_points_to_polygon(points_xyz: np.ndarray, polygon):
    pts = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    if len(pts) == 0:
        return pts, np.array([], dtype=int)
    inside = np.asarray(shapely.contains_xy(polygon, pts[:, 0], pts[:, 1]), dtype=bool)
    idx = np.flatnonzero(inside)
    return pts[idx], idx


def _cell_key(x: float, y: float, ox: float, oy: float) -> tuple[int, int]:
    return math.floor((x - ox) / CELL_M), math.floor((y - oy) / CELL_M)


def accumulate_drive(
    acc: dict[tuple[int, int], dict],
    points_xyz: np.ndarray,
    polygon,
    drivable_union,
    labels_flat_driveable: np.ndarray | None = None,
    ox: float | None = None,
    oy: float | None = None,
) -> str:
    """Accumulate one drive's road-surface observations into acc.

    acc maps (ix,iy) -> {road_eligible, drive_count, road_surface_points, x0, y0}.
    labels_flat_driveable, if provided, is aligned to points_xyz and filtered to
    the rebuilt map-frame area polygon.
    Only counts points inside rebuilt map-frame area polygon and in in-area cells.
    Returns ground_source.
    """
    if ox is None or oy is None:
        ox, oy = grid_origin(polygon)
    pts_all = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    pts_in, inside_idx = filter_points_to_polygon(pts_all, polygon)
    labels_in = None
    if labels_flat_driveable is not None:
        lbl_all = np.asarray(labels_flat_driveable).reshape(-1)
        if len(lbl_all) != len(pts_all):
            raise ValueError("labels_flat_driveable length must match points")
        labels_in = lbl_all[inside_idx]
    mask, ground_source = road_surface_mask(pts_in, drivable_union, labels_in)
    road_pts = pts_in[mask] if len(pts_in) else pts_in
    if len(road_pts) == 0:
        return ground_source
    covered = set()
    for p in road_pts:
        key = _cell_key(float(p[0]), float(p[1]), ox, oy)
        covered.add(key)
        if key in acc:
            acc[key]["road_surface_points"] += 1
    for key in covered:
        if key in acc:
            acc[key]["drive_count"] += 1
    return ground_source


def init_accumulator(cells: list[Cell]):
    return {
        (c.ix, c.iy): {
            "road_eligible": c.road_eligible,
            "drive_count": 0,
            "road_surface_points": 0,
            "x0": c.x0,
            "y0": c.y0,
        }
        for c in cells
    }


def cell_records(
    acc: dict[tuple[int, int], dict], density_threshold_pts_m2: float = DENSITY_THRESHOLD_PTS_M2
):
    records = []
    for key in sorted(acc.keys()):
        r = acc[key]
        eligible = bool(r["road_eligible"])
        pts = int(r["road_surface_points"])
        density = pts / (CELL_M * CELL_M)
        drive_count = int(r["drive_count"])
        if eligible:
            low = (drive_count < 2) or (density < float(density_threshold_pts_m2))
        else:
            low = False
        records.append(
            {
                "ix": int(key[0]),
                "iy": int(key[1]),
                "x0": float(r["x0"]),
                "y0": float(r["y0"]),
                "road_eligible": eligible,
                "drive_count": drive_count,
                "density_pts_m2": float(density),
                "road_surface_points": pts,
                "low_coverage": bool(low),
            }
        )
    return records


def low_coverage_cells(records) -> set[tuple[int, int]]:
    return {
        (r["ix"], r["iy"])
        for r in records
        if r.get("road_eligible") and r.get("low_coverage")
    }


def cells_gained(baseline_records, candidate_records) -> int:
    """Marginal eligible low-coverage cells fixed by adding candidate to baseline."""
    base_low = low_coverage_cells(baseline_records)
    cand_low = low_coverage_cells(candidate_records)
    return len(base_low - cand_low)


def coverage_document(
    area_name: str,
    area_path: str | Path,
    location: str,
    grid_origin_map: tuple[float, float],
    cells: list[dict],
    density_threshold_pts_m2: float = DENSITY_THRESHOLD_PTS_M2,
    ground_sources: Iterable[str] | None = None,
    baseline_scene_tokens: list[str] | None = None,
    extra_metadata: dict | None = None,
) -> dict:
    gs = sorted(set(ground_sources or []))
    doc = {
        "schema_version": SCHEMA_VERSION,
        "area": area_name,
        "area_path": str(area_path),
        "location": location,
        "frame": FRAME,
        "grid_origin_map": [float(grid_origin_map[0]), float(grid_origin_map[1])],
        "cell_m": float(CELL_M),
        "density_threshold_pts_m2": float(density_threshold_pts_m2),
        "sweep_step": SWEEP_STEP,
        "density_semantics": DENSITY_SEMANTICS,
        "ground_source": gs[0] if len(gs) == 1 else gs,
        "ground_sources": gs,
        "baseline_scene_tokens": list(baseline_scene_tokens or []),
        "road_eligible_rule": ROAD_ELIGIBLE_RULE,
        "cells": list(cells),
    }
    if extra_metadata:
        doc.update(extra_metadata)
    return doc


def atomic_write_json(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())
