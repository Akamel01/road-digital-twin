"""Twin from the merged cloud, with change detection (issue #142).

`twin area twin <name>` reads what `twin area merge` wrote (merged.npz, drives.json, and the per-drive folders it
cached) and runs ground, features, profile, isd and accuracy on the one registered cloud. On top of the single-drive
stages it adds:

- change detection: a 0.5 m cell where drives from different dates disagree beyond the registration noise is
  "changed", with its dates. Changed cells are written as change.geojson. Features on changed cells are marked
  properties.changed and left out of accuracy, together with the map reference there (operator decision
  2026-11-09: detect and flag, not latest-wins).
- support: every feature records which drives saw it (properties.support).

DECISION: like merge, this is its own step, not a pipeline stage. A stage takes one scene's folder as input.
It never edits merge's files: a different registration only changes merged.npz and drives.json.
"""

from __future__ import annotations

import json
import logging
import time
import warnings
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import mapping, shape

from twin import registry
from twin.contracts import Params, Pipeline
from twin.runner import StageContext
from twin.stages import ground

# ---- change detection
# DECISION: cells are 0.5 m, the cell merge measures ground disagreement on (merge.CELL_M).
CELL_M = 0.5
# DECISION: a drive describes a cell with its ground height (10th percentile of z) and its top (90th percentile).
# The structure height is top minus ground: it is not affected by a drive's own height offset.
GROUND_PCT, TOP_PCT = 10, 90
MIN_CELL_POINTS = 10
# DECISION: the registration noise is read off the data. Two drives of the same date saw the same road, so every cell
# difference between them is noise (registration, sampling, passing objects). A date pair is "changed" in a cell when it
# differs by more than the NOISE_PCT-th percentile of the same-date differences, but never by less than the floor.
NOISE_PCT = 99.0
MIN_GROUND_DZ_M = 0.15
MIN_STRUCTURE_DH_M = 0.30
# DECISION: a region of fewer than MIN_REGION_CELLS changed cells (1 m2) is speckle and is dropped.
MIN_REGION_CELLS = 4
# ---- support
# DECISION: a drive "supports" a feature when it has at least SUPPORT_MIN_POINTS points within SUPPORT_BUFFER_M of the
# feature in plan and within SUPPORT_BAND_M above or below the ground of that cell: it saw the place, whatever it saw.
SUPPORT_BUFFER_M = 0.3
SUPPORT_BAND_M = 0.3
SUPPORT_MIN_POINTS = 5
SUPPORT_TILE_M = 10.0

FEATURE_FILES = ("markings.geojson", "crosswalks.geojson", "curbs.geojson")
STAGE_ORDER = ("ground", "features", "profile", "isd", "accuracy")


# ------------------------------------------------------------------ inputs


def _correction(c: dict | None) -> np.ndarray:
    """The 4x4 merge applied to a drive (yaw and translation, in the frame centred on the polygon), from drives.json."""
    t = np.eye(4)
    if c:
        yaw = np.radians(c["yaw_deg"])
        t[:2, :2] = [[np.cos(yaw), -np.sin(yaw)], [np.sin(yaw), np.cos(yaw)]]
        t[:3, 3] = [c["dx_m"], c["dy_m"], c["dz_m"]]
    return t


def _fc(feats: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": feats})


def area_inputs(drives: list[dict], work: Path, polygon) -> tuple[list[dict], list[dict]]:
    """Facilities and map reference of the whole area, from the per-drive load folders.

    A facility comes from the drive whose copy of it is largest (a scene patch can cut it); a reference feature is the
    union of the drives' pieces, clipped to the area polygon.
    """
    facs: dict[str, dict] = {}
    ref: dict[tuple, list] = {}
    props: dict[tuple, dict] = {}
    for d in drives:
        load = work / "drives" / d["scene"] / "1_load"
        for f in json.loads((load / "facilities.geojson").read_text())["features"]:
            fid = f["properties"]["id"]
            if fid not in facs or shape(f["geometry"]).area > shape(facs[fid]["geometry"]).area:
                facs[fid] = f
        for f in json.loads((load / "reference.geojson").read_text())["features"]:
            key = (f["properties"]["layer"], f["properties"]["token"])
            ref.setdefault(key, []).append(shape(f["geometry"]))
            props[key] = f["properties"]
    facilities = [f for f in facs.values() if shape(f["geometry"]).intersects(polygon)]
    reference = []
    for key, parts in sorted(ref.items()):
        geom = shapely.make_valid(shapely.union_all(parts)).intersection(polygon)
        if not geom.is_empty:
            reference.append({"type": "Feature", "geometry": mapping(geom), "properties": props[key]})
    return facilities, reference


def parked_vehicles(drives: list[dict], work: Path, centre: np.ndarray, polygon) -> np.ndarray:
    """Parked-vehicle points of all drives in the merged frame, (N, 3), inside the area polygon."""
    from twin.merge import apply

    out = []
    for d in drives:
        base = work / "drives" / d["scene"]
        with np.load(base / "2_mask" / "parked.npz") as f:
            fields = {k: f[k] for k in ground.POINT_FIELDS}
        if len(fields["x"]) == 0:
            continue
        poses = lambda p: np.array(
            [r["matrix"] for r in json.loads(p.read_text())["poses"]], dtype=float
        ).reshape(-1, 4, 4)
        xyz, _, _ = ground.aligned_points(
            fields, poses(base / "1_load" / "poses.json"), poses(base / "3_align" / "poses.json")
        )
        xyz = apply(_correction(d.get("correction")), xyz - centre) + centre
        out.append(xyz[shapely.contains_xy(polygon, xyz[:, 0], xyz[:, 1])])
    return np.vstack(out) if out else np.empty((0, 3))


# ------------------------------------------------------------------ change detection


def cell_stats(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, drive: np.ndarray, origin: np.ndarray, shape_yx: tuple[int, int], n_drives: int
) -> tuple[np.ndarray, np.ndarray]:
    """Ground height and top per drive and cell: two (n_drives, ny * nx) arrays, NaN where the drive has too few points."""
    ny, nx = shape_yx
    ix = np.floor((x - origin[0]) / CELL_M).astype(np.int64)
    iy = np.floor((y - origin[1]) / CELL_M).astype(np.int64)
    key = (iy * nx + ix) * n_drives + drive
    order = np.lexsort((z, key))
    ks, zs = key[order], z[order]
    del order
    starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
    n = np.diff(np.r_[starts, len(ks)])
    ok = n >= MIN_CELL_POINTS
    starts, n, ks = starts[ok], n[ok], ks[starts[ok]]
    lo = np.full((n_drives, ny * nx), np.nan, np.float32)
    hi = lo.copy()
    lo[ks % n_drives, ks // n_drives] = zs[starts + (n - 1) * GROUND_PCT // 100]
    hi[ks % n_drives, ks // n_drives] = zs[starts + (n - 1) * TOP_PCT // 100]
    return lo, hi


def by_date(a: np.ndarray, dates: list[str]) -> dict[str, np.ndarray]:
    """Median over the drives of each date, per cell."""
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # a cell no drive of the date saw stays NaN
        for date in sorted(set(dates)):
            out[date] = np.nanmedian(a[[i for i, d in enumerate(dates) if d == date]], axis=0)
    return out


def noise_levels(lo: np.ndarray, hi: np.ndarray, dates: list[str]) -> dict:
    """Thresholds (ground, structure) from drives of the same date, and what they came from."""
    dg, dh = [], []
    for date in sorted(set(dates)):
        idx = [i for i, d in enumerate(dates) if d == date]
        for k, a in enumerate(idx):
            for b in idx[k + 1 :]:
                dg.append(np.abs(lo[a] - lo[b]))
                dh.append(np.abs((hi[a] - lo[a]) - (hi[b] - lo[b])))
    dg = np.concatenate(dg) if dg else np.empty(0)
    dh = np.concatenate(dh) if dh else np.empty(0)
    dg, dh = dg[np.isfinite(dg)], dh[np.isfinite(dh)]
    ng = float(np.percentile(dg, NOISE_PCT)) if len(dg) else None
    nh = float(np.percentile(dh, NOISE_PCT)) if len(dh) else None
    return {
        "same_date_cells": len(dg),
        "ground_noise_m": ng,
        "structure_noise_m": nh,
        "ground_threshold_m": max(MIN_GROUND_DZ_M, ng or 0.0),
        "structure_threshold_m": max(MIN_STRUCTURE_DH_M, nh or 0.0),
    }


def detect_change(lo: np.ndarray, hi: np.ndarray, dates: list[str], noise: dict) -> dict:
    """Per cell: does any pair of dates disagree beyond the noise?

    Returns changed (bool per cell), kind (1 ground, 2 structure, 3 both), odd (per date, bool per cell: the date that
    differs from the others, the one in most flagged pairs of the cell) and the largest differences.
    """
    g = by_date(lo, dates)
    s = {d: by_date(hi, dates)[d] - g[d] for d in g}
    names = sorted(g)
    ncell = lo.shape[1]
    kind = np.zeros(ncell, np.uint8)
    votes = {d: np.zeros(ncell, np.int16) for d in names}
    max_dz = np.zeros(ncell, np.float32)
    max_dh = np.zeros(ncell, np.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                dz, dh = np.abs(g[a] - g[b]), np.abs(s[a] - s[b])
                zc = dz > noise["ground_threshold_m"]
                sc = dh > noise["structure_threshold_m"]
                kind |= zc.astype(np.uint8) | (sc.astype(np.uint8) << 1)
                votes[a] += zc | sc
                votes[b] += zc | sc
                max_dz = np.fmax(max_dz, dz)
                max_dh = np.fmax(max_dh, dh)
    changed = kind > 0
    top = np.max(list(votes.values()), axis=0)
    odd = {d: changed & (votes[d] == top) for d in names}
    return {"changed": changed, "kind": kind, "odd": odd, "max_dz": max_dz, "max_dh": max_dh}


def change_regions(
    det: dict, origin: np.ndarray, shape_yx: tuple[int, int], dates: list[str], scenes: list[str]
) -> list[dict]:
    """GeoJSON features: connected changed cells, each with its dates, kind and largest differences."""
    nx = shape_yx[1]
    cells = np.flatnonzero(det["changed"])
    if len(cells) == 0:
        return []
    iy, ix = cells // nx, cells % nx
    boxes = shapely.box(
        origin[0] + ix * CELL_M, origin[1] + iy * CELL_M, origin[0] + (ix + 1) * CELL_M, origin[1] + (iy + 1) * CELL_M
    )
    merged = shapely.union_all(boxes)
    parts = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
    tree = shapely.STRtree(boxes)
    feats = []
    for poly in parts:
        members = cells[tree.query(poly, predicate="contains")]
        if len(members) < MIN_REGION_CELLS:
            continue
        odd = sorted(d for d, m in det["odd"].items() if m[members].any())
        kinds = int(np.bitwise_or.reduce(det["kind"][members]))
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(poly),
                "properties": {
                    "n_cells": len(members),
                    "area_m2": round(len(members) * CELL_M**2, 2),
                    "kind": {1: "ground", 2: "structure", 3: "ground+structure"}[kinds],
                    "dates": odd,
                    "drives": sorted(s for s, d in zip(scenes, dates, strict=True) if d in odd),
                    "max_dz_m": round(float(det["max_dz"][members].max()), 3),
                    "max_dh_m": round(float(det["max_dh"][members].max()), 3),
                },
            }
        )
    feats.sort(key=lambda f: -f["properties"]["area_m2"])
    for i, f in enumerate(feats):
        f["properties"]["id"] = f"change-{i + 1:04d}"
    return feats


# ------------------------------------------------------------------ support and changed flags


def support(
    feats: list[dict],
    xyz: np.ndarray,
    drive: np.ndarray,
    ground_z: np.ndarray,
    origin: np.ndarray,
    shape_yx: tuple[int, int],
    scenes: list[str],
) -> None:
    """Set properties.support on each feature: the points of each drive near it, and the drives that have enough.

    xyz, drive, ground_z: all merged points, their drive index and the ground height of their cell.
    """
    near = np.abs(xyz[:, 2] - ground_z) <= SUPPORT_BAND_M
    xyz, drive = xyz[near], drive[near]
    tile = np.floor((xyz[:, :2] - origin) / SUPPORT_TILE_M).astype(np.int64)
    ntx = int(tile[:, 0].max()) + 1
    key = tile[:, 1] * ntx + tile[:, 0]
    order = np.argsort(key, kind="stable")
    key, xyz, drive = key[order], xyz[order], drive[order]
    for f in feats:
        geom = shapely.force_2d(shape(f["geometry"])).buffer(SUPPORT_BUFFER_M)
        x0, y0, x1, y1 = geom.bounds
        tx = np.arange(int((x0 - origin[0]) // SUPPORT_TILE_M), int((x1 - origin[0]) // SUPPORT_TILE_M) + 1)
        ty = np.arange(int((y0 - origin[1]) // SUPPORT_TILE_M), int((y1 - origin[1]) // SUPPORT_TILE_M) + 1)
        want = (ty[:, None] * ntx + tx[None, :]).ravel()
        want = want[(want >= 0)]
        lo, hi = np.searchsorted(key, want, "left"), np.searchsorted(key, want, "right")
        sel = np.concatenate([np.arange(a, b) for a, b in zip(lo, hi, strict=True)]) if len(want) else np.empty(0, int)
        inside = shapely.contains_xy(geom, xyz[sel, 0], xyz[sel, 1])
        n = np.bincount(drive[sel[inside]], minlength=len(scenes))
        have = {scenes[i]: int(c) for i, c in enumerate(n) if c >= SUPPORT_MIN_POINTS}
        f["properties"]["support"] = {"n_drives": len(have), "drives": have}


def flag_changed(feats: list[dict], regions: list[dict]) -> int:
    """Mark features that touch a change region: properties.changed and change_dates. Returns how many."""
    if not regions:
        return 0
    polys = [shape(r["geometry"]) for r in regions]
    tree = shapely.STRtree(polys)
    n = 0
    for f in feats:
        hit = tree.query(shapely.force_2d(shape(f["geometry"])), predicate="intersects")
        if len(hit):
            f["properties"]["changed"] = True
            f["properties"]["change_dates"] = sorted({d for i in hit for d in regions[i]["properties"]["dates"]})
            n += 1
    return n


def mask_reference(reference: list[dict], regions: list[dict]) -> list[dict]:
    """The map reference without the changed regions: accuracy compares only what did not change."""
    if not regions:
        return reference
    cut = shapely.union_all([shape(r["geometry"]) for r in regions])
    out = []
    for f in reference:
        geom = shapely.make_valid(shape(f["geometry"])).difference(cut)
        if not geom.is_empty:
            out.append({**f, "geometry": mapping(geom)})
    return out


def construction_check(regions: list[dict], drives: list[dict], work: Path, centre: np.ndarray, date: str) -> dict:
    """Does the change layer cover the construction seen on one date?

    Looks at the annotated construction vehicles and workers of that date's drives (boxes.json, moved by the drive's
    registration) and reports how many of their positions lie in or within 2 m of a changed region.
    """
    from twin.merge import apply

    sel = [d for d in drives if d["date"] == date]
    cats = ("vehicle.construction", "human.pedestrian.construction_worker")
    pts = []
    for d in sel:
        boxes = json.loads((work / "drives" / d["scene"] / "1_load" / "boxes.json").read_text())["sweeps"]
        c = np.array([b["center"] for sw in boxes for b in sw["boxes"] if b["category"] in cats])
        if len(c):
            pts.append(apply(_correction(d.get("correction")), c - centre) + centre)
    mine = [r for r in regions if date in r["properties"]["dates"]]
    out = {
        "date": date,
        "drives": [d["scene"] for d in sel],
        "regions_with_date": len(mine),
        "area_m2_with_date": round(sum(r["properties"]["area_m2"] for r in mine), 1),
    }
    if pts and regions:
        p = np.vstack(pts)
        # one position per 0.5 m cell, so a parked machine seen in 400 sweeps counts once
        p = np.unique(np.floor(p[:, :2] / CELL_M).astype(np.int64), axis=0) * CELL_M + CELL_M / 2
        cut = shapely.union_all([shape(r["geometry"]) for r in regions])
        cut_date = shapely.union_all([shape(r["geometry"]) for r in mine]) if mine else shapely.Polygon()
        pts2 = shapely.points(p)
        out["construction_cells"] = len(p)
        out["within_2m_of_change"] = float(np.mean(shapely.distance(pts2, cut) <= 2.0))
        out["within_2m_of_change_with_date"] = float(np.mean(shapely.distance(pts2, cut_date) <= 2.0))
    return out


# ------------------------------------------------------------------ command


def _stage(ctx: StageContext, name: str, params: Params, pipeline: Pipeline) -> dict:
    fn = registry.lookup(name, getattr(pipeline, name).method)
    t0 = time.time()
    res = fn(ctx, getattr(params, name))
    if res.status != "ok":
        raise RuntimeError(f"{name}: {res.message}")
    return {"seconds": round(time.time() - t0, 1), "metrics": res.metrics}


def twin_area(base: Path, name: str, log: logging.Logger, check_date: str | None = None) -> dict:
    """Run the area twin. base: the run store; reads areas/<name>.json and areas/<name>-merged, writes areas/<name>-twin."""
    t_start = time.time()
    area = json.loads((base / "areas" / f"{name}.json").read_text())
    work = base / "areas" / f"{name}-merged"
    out = base / "areas" / f"{name}-twin"
    out.mkdir(parents=True, exist_ok=True)
    polygon = shape(area["polygon"])
    centre = np.array([*polygon.centroid.coords[0], 0.0])
    drives = json.loads((work / "drives.json").read_text())
    scenes = [d["scene"] for d in drives]
    dates = [d["date"] for d in drives]
    params, pipeline = Params(), Pipeline()
    with np.load(work / "merged.npz") as f:
        x, y, z = f["x"], f["y"], f["z"]
        intensity, drive = f["intensity"].astype(np.float32), f["drive"].astype(np.int64)
    log.info("merged cloud: %d points, %d drives", len(x), len(drives))

    # load/mask/align stand-ins: the area's facilities and map, and the drives' parked vehicles, in the merged frame
    facilities, reference = area_inputs(drives, work, polygon)
    parked = parked_vehicles(drives, work, centre, polygon)
    ident = json.dumps({"poses": [{"matrix": np.eye(4).tolist()}]})
    for d, files in {
        "1_load": {"facilities.geojson": _fc(facilities), "reference.geojson": _fc(reference), "poses.json": ident},
        "3_align": {"poses.json": ident, "qa.json": json.dumps({"method": "merged-icp", "fallback_used": False, "xy_drift_p95_m": None})},
    }.items():
        (out / d).mkdir(exist_ok=True)
        for fn, text in files.items():
            (out / d / fn).write_text(text)
    (out / "2_mask").mkdir(exist_ok=True)
    np.savez_compressed(
        out / "2_mask" / "parked.npz",
        x=parked[:, 0], y=parked[:, 1], z=parked[:, 2],
        intensity=np.zeros(len(parked), np.float32), sweep=np.zeros(len(parked), np.uint16),
    )

    # change detection
    b = polygon.bounds
    origin = np.array([b[0], b[1]])
    shape_yx = (int((b[3] - b[1]) // CELL_M) + 2, int((b[2] - b[0]) // CELL_M) + 2)
    inside = shapely.contains_xy(polygon, x, y)
    lo, hi = cell_stats(x[inside], y[inside], z[inside], drive[inside], origin, shape_yx, len(drives))
    del inside
    noise = noise_levels(lo, hi, dates)
    det = detect_change(lo, hi, dates, noise)
    regions = change_regions(det, origin, shape_yx, dates, scenes)
    (out / "change.geojson").write_text(_fc(regions))
    log.info("change: %d regions, noise %s", len(regions), noise)

    # ground on the merged cloud; sweep = drive, so G3 is the cross-drive ground disagreement
    t0 = time.time()
    perm = np.random.default_rng(params.seed).permutation(len(x))  # thinning keeps the first point of a voxel: no drive wins every voxel
    xyz = np.column_stack([x, y, z])[perm]
    inten, drv = intensity[perm], drive[perm]
    keep = ground.voxel_first(xyz, params.ground.voxel_m)
    ctx = StageContext(out, f"area-{name}", params.seed, log, params.facilities.min_observed)
    res = ground.split_and_write(
        ctx, params.ground, "ransac-tiles", lambda p, q: ground.ransac_ground(p, q, params.seed),
        xyz[keep], inten[keep], drv[keep].astype(np.int32), None, None,
        json.loads((out / "3_align" / "qa.json").read_text()), facilities,
    )
    if res.status != "ok":
        raise RuntimeError(f"ground: {res.message}")
    seconds = {"ground": round(time.time() - t0, 1)}
    stage_metrics = {"ground": res.metrics}
    del xyz, inten, drv, keep, perm

    # features, then support and the changed flag, then accuracy against the unchanged map
    for st in ("features",):
        r = _stage(ctx, st, params, pipeline)
        seconds[st], stage_metrics[st] = r["seconds"], r["metrics"]
    gz = np.nanmedian(np.where(np.isfinite(lo), lo, np.nan), axis=0)
    cell = (np.floor((y - origin[1]) / CELL_M).astype(np.int64) * shape_yx[1] + np.floor((x - origin[0]) / CELL_M).astype(np.int64))
    cell = np.clip(cell, 0, gz.size - 1)
    fdir = ctx.stage_dir("features")
    n_changed = 0
    all_feats = {}
    for fn in FEATURE_FILES:
        if (fdir / fn).is_file():
            all_feats[fn] = json.loads((fdir / fn).read_text())["features"]
    flat = [f for v in all_feats.values() for f in v]
    support(flat, np.column_stack([x, y, z]), drive, gz[cell], origin, shape_yx, scenes)
    n_changed = flag_changed(flat, regions)
    for fn, v in all_feats.items():
        (fdir / fn).write_text(_fc(v))
    (out / "1_load" / "reference.full.geojson").write_text(_fc(reference))
    (out / "1_load" / "reference.geojson").write_text(_fc(mask_reference(reference, regions)))
    for st in ("profile", "isd", "accuracy"):
        r = _stage(ctx, st, params, pipeline)
        seconds[st], stage_metrics[st] = r["seconds"], r["metrics"]

    mman = json.loads((work / "manifest.json").read_text())
    total = round(time.time() - t_start, 1)
    summary = {
        "area": name,
        "n_drives": len(drives),
        "n_features": len(flat),
        "n_features_changed": n_changed,
        "n_change_regions": len(regions),
        "change_area_m2": round(sum(r["properties"]["area_m2"] for r in regions), 1),
        "noise": noise,
        "seconds": seconds,
        "twin_seconds": total,
        "construction_check": construction_check(regions, drives, work, centre, check_date) if check_date else None,
        "by_date": {
            d: {"regions": sum(d in r["properties"]["dates"] for r in regions),
                "area_m2": round(sum(r["properties"]["area_m2"] for r in regions if d in r["properties"]["dates"]), 1)}
            for d in sorted(set(dates))
        },
    }
    (out / "change.json").write_text(json.dumps(summary, indent=2))
    # a minimal manifest so `twin eval <folder>` reads G2 (from merge), G3 and G5
    acc = stage_metrics["accuracy"]
    (out / "manifest.json").write_text(json.dumps({
        "run_id": f"area-{name}-twin",
        "data": mman.get("data", {}),
        "metrics": {"align": mman["metrics"]["align"], "ground": stage_metrics["ground"], "accuracy": acc},
        "stages": [{"seconds": v} for v in seconds.values()],
    }, indent=2))
    return summary


def area_twin_command(name: str, store: Path | None, check_date: str | None = None) -> int:
    from twin.runner import default_store

    logging.basicConfig(level=logging.INFO)
    base = Path(store) if store else default_store()
    print(json.dumps(twin_area(base, name, logging.getLogger("twin.areatwin"), check_date), indent=2))
    return 0
