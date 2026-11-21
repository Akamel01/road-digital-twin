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
from twin.area import drive_correction
from twin.contracts import Params, Pipeline, stage_dir
from twin.runner import StageContext
from twin.runrecord import read_record, write_document
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
NOISE_PCT = 95.0
MIN_GROUND_DZ_M = 0.15
MIN_STRUCTURE_DH_M = 0.30
# DECISION: only cells of the HD map's drivable area are compared (walls, trees and parked vehicles seen from another
# side differ by metres between same-date drives, which sets the noise far above a road change). A region of fewer
# than MIN_REGION_CELLS changed cells (2 m2) is speckle and is dropped.
MIN_REGION_CELLS = 8
# DECISION: registration leaves each drive pair with a smooth height error (metres on the seaport area at the time of
# writing, ADR 0005 G2) that is not a change. A pair's cell differences are taken relative to their median over
# RESID_TILE_CELLS x RESID_TILE_CELLS cells (10 m), so a change smaller than a tile stands out and a smooth offset does not.
RESID_TILE_CELLS = 20
MIN_TILE_CELLS = 10
# ---- support
# DECISION: a drive "supports" a feature when it has at least SUPPORT_MIN_POINTS points within SUPPORT_BUFFER_M of the
# feature in plan and within SUPPORT_BAND_M above or below the ground of that cell: it saw the place, whatever it saw.
SUPPORT_BUFFER_M = 0.3
SUPPORT_BAND_M = 0.3
SUPPORT_MIN_POINTS = 5
SUPPORT_TILE_M = 10.0

FEATURE_FILES = ("markings.geojson", "crosswalks.geojson", "curbs.geojson", "ramps.geojson")
STAGE_ORDER = ("ground", "features", "profile", "isd", "accuracy")


# ------------------------------------------------------------------ inputs


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
        load = stage_dir(work / "drives" / d["scene"], "load")
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
        with np.load(stage_dir(base, "mask") / "parked.npz") as f:
            fields = {k: f[k] for k in ground.POINT_FIELDS}
        if len(fields["x"]) == 0:
            continue
        poses = lambda p: np.array(
            [r["matrix"] for r in json.loads(p.read_text())["poses"]], dtype=float
        ).reshape(-1, 4, 4)
        xyz, _, _ = ground.aligned_points(
            fields, poses(stage_dir(base, "load") / "poses.json"), poses(stage_dir(base, "align") / "poses.json")
        )
        xyz = apply(drive_correction(d.get("correction")), xyz - centre) + centre
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


def residual(diff: np.ndarray, shape_yx: tuple[int, int]) -> np.ndarray:
    """A pair's per-cell difference minus its median over its 10 m tile (NaN where the tile has too few cells)."""
    ny, nx = shape_yx
    t = RESID_TILE_CELLS
    ny2, nx2 = -(-ny // t) * t, -(-nx // t) * t
    a = np.full((ny2, nx2), np.nan, np.float32)
    a[:ny, :nx] = diff.reshape(ny, nx)
    blocks = a.reshape(ny2 // t, t, nx2 // t, t)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(blocks, axis=(1, 3))
    med[np.sum(np.isfinite(blocks), axis=(1, 3)) < MIN_TILE_CELLS] = np.nan
    full = np.repeat(np.repeat(med, t, axis=0), t, axis=1)[:ny, :nx]
    return (a[:ny, :nx] - full).ravel()


def noise_levels(lo: np.ndarray, hi: np.ndarray, dates: list[str], shape_yx: tuple[int, int]) -> dict:
    """Thresholds (ground, structure) from drives of the same date, and what they came from."""
    dg, dh = [], []
    for date in sorted(set(dates)):
        idx = [i for i, d in enumerate(dates) if d == date]
        for k, a in enumerate(idx):
            for b in idx[k + 1 :]:
                dg.append(np.abs(residual(lo[a] - lo[b], shape_yx)))
                dh.append(np.abs(residual((hi[a] - lo[a]) - (hi[b] - lo[b]), shape_yx)))
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


def detect_change(lo: np.ndarray, hi: np.ndarray, dates: list[str], noise: dict, shape_yx: tuple[int, int]) -> dict:
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
                dz = np.abs(residual(g[a] - g[b], shape_yx))
                dh = np.abs(residual(s[a] - s[b], shape_yx))
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


CHANGED_SHARE = 0.5  # a feature (or map feature) mostly on changed cells is left out of accuracy


def _changed_share(geom, cut) -> float:
    """Share of a geometry on changed cells: by area, length, or point count."""
    geom = shapely.make_valid(shapely.force_2d(geom))
    if geom.is_empty:
        return 0.0
    inside = geom.intersection(cut)
    if geom.area > 0:
        return inside.area / geom.area
    if geom.length > 0:
        return inside.length / geom.length
    return 0.0 if inside.is_empty else 1.0


def flag_changed(feats: list[dict], regions: list[dict]) -> int:
    """Mark features mostly on a change region (CHANGED_SHARE): properties.changed and change_dates. The map
    reference uses the same rule (mask_reference), so a feature and its map counterpart leave accuracy together;
    before #283 a feature touching a region was dropped while the map one was only clipped, which scored correct
    crosswalks as missed. Returns how many."""
    if not regions:
        return 0
    polys = [shape(r["geometry"]) for r in regions]
    cut = shapely.union_all(polys)
    tree = shapely.STRtree(polys)
    n = 0
    for f in feats:
        g = shape(f["geometry"])
        hit = tree.query(shapely.force_2d(g), predicate="intersects")
        if len(hit) and _changed_share(g, cut) > CHANGED_SHARE:
            f["properties"]["changed"] = True
            f["properties"]["change_dates"] = sorted({d for i in hit for d in regions[i]["properties"]["dates"]})
            n += 1
    return n


def mask_reference(reference: list[dict], regions: list[dict]) -> list[dict]:
    """The map reference without the features mostly on changed regions (same rule as flag_changed):
    accuracy compares only what did not change."""
    if not regions:
        return reference
    cut = shapely.union_all([shape(r["geometry"]) for r in regions])
    return [f for f in reference if _changed_share(shape(f["geometry"]), cut) <= CHANGED_SHARE]


def construction_check(regions: list[dict], drives: list[dict], work: Path, centre: np.ndarray, date: str) -> dict:
    """Does the change layer cover the construction seen on one date?

    Looks at the annotated construction vehicles and workers of that date's drives (boxes.json, moved by the drive's
    registration) and reports how many of their positions lie in or within 2 m of a changed region.
    """
    from twin.merge import apply

    sel = [d for d in drives if d["date"] == date]
    cats = ("vehicle.construction", "human.pedestrian.construction_worker")
    pts, track = [], []
    for d in sel:
        base = work / "drives" / d["scene"]
        ego = np.array([r["matrix"] for r in json.loads((stage_dir(base, "align") / "poses.json").read_text())["poses"]])
        track.append(apply(drive_correction(d.get("correction")), ego.reshape(-1, 4, 4)[:, :3, 3] - centre) + centre)
        boxes = json.loads((stage_dir(work / "drives" / d["scene"], "load") / "boxes.json").read_text())["sweeps"]
        c = np.array([b["center"] for sw in boxes for b in sw["boxes"] if b["category"] in cats])
        if len(c):
            pts.append(apply(drive_correction(d.get("correction")), c - centre) + centre)
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
        # for scale: the same share for the drives' own driving path, which is not construction
        tr = shapely.points(np.vstack(track)[:, :2])
        out["path_within_2m_of_change"] = float(np.mean(shapely.distance(tr, cut) <= 2.0))
    return out


# ------------------------------------------------------------------ command


def _stage(ctx: StageContext, name: str, params: Params, pipeline: Pipeline) -> dict:
    fn = registry.lookup(name, getattr(pipeline, name).method)
    t0 = time.time()
    res = fn(ctx, getattr(params, params.groups_for(name)[0]))
    if res.status != "ok":
        raise RuntimeError(f"{name}: {res.message}")
    return {"seconds": round(time.time() - t0, 1), "metrics": res.metrics}


def twin_area(base: Path, name: str, log: logging.Logger, check_date: str | None = None) -> dict:
    """Run the area twin. base: the run store; reads areas/<name>.json and areas/<name>-merged, writes areas/<name>-twin."""
    from twin import areasteps

    t_start = time.time()
    area = json.loads((base / "areas" / f"{name}.json").read_text())
    work = base / "areas" / f"{name}-merged"
    out = base / "areas" / f"{name}-twin"
    out.mkdir(parents=True, exist_ok=True)
    polygon = shape(area["polygon"])
    centre = np.array([*polygon.centroid.coords[0], 0.0])
    drives = json.loads((work / "drives.json").read_text())
    dates = [d["date"] for d in drives]
    params, pipeline = Params(), Pipeline()
    pipeline.features.method = "raster"

    log.info("merged cloud: %s", name)

    # D8 order: load/mask/align stand-ins -> ground -> features -> change -> profile -> isd -> accuracy
    load_res = areasteps.load_step(work, area, out)
    if load_res.status != "ok":
        raise RuntimeError(f"load: {load_res.status}")
    mask_res = areasteps.mask_step(work, area, out)
    if mask_res.status != "ok":
        raise RuntimeError(f"mask: {mask_res.status}")
    align_res = areasteps.align_step(out)
    if align_res.status != "ok":
        raise RuntimeError(f"align: {align_res.status}")

    ground_res = areasteps.ground_step(
        work, area, drives, stage_dir(out, "load"), stage_dir(out, "align"), out, params, log
    )
    if ground_res.status != "ok":
        raise RuntimeError(f"ground: {ground_res.status}")
    seconds = {"ground": float(ground_res.metrics.get("seconds", 0.0))}
    stage_metrics = {"ground": {k: v for k, v in ground_res.metrics.items() if k != "seconds"}}

    ctx = StageContext(out, f"area-{name}", params.seed, log, params.facilities.min_observed)
    for st in ("features",):
        r = _stage(ctx, st, params, pipeline)
        seconds[st], stage_metrics[st] = r["seconds"], r["metrics"]

    change_res = areasteps.change_step(
        work, area, drives, stage_dir(out, "features"), stage_dir(out, "load"), out
    )
    if change_res.status != "ok":
        raise RuntimeError(f"change: {change_res.status}")

    for st in ("profile", "isd", "accuracy"):
        r = _stage(ctx, st, params, pipeline)
        seconds[st], stage_metrics[st] = r["seconds"], r["metrics"]

    mman = read_record(work)
    total = round(time.time() - t_start, 1)
    regions = json.loads((out / "change.geojson").read_text())["features"]
    summary = {
        "area": name,
        "n_drives": len(drives),
        "n_features": int(change_res.metrics.get("n_features", 0)),
        "n_features_changed": int(change_res.metrics.get("n_features_changed", 0)),
        "n_change_regions": int(change_res.metrics.get("n_change_regions", len(regions))),
        "change_area_m2": float(change_res.metrics.get("change_area_m2", 0.0)),
        "noise": change_res.metrics.get("noise", {}),
        "seconds": seconds,
        "twin_seconds": total,
        "construction_check": construction_check(regions, drives, work, centre, check_date) if check_date else None,
        "by_date": change_res.metrics.get("by_date", {
            d: {"regions": sum(d in r["properties"]["dates"] for r in regions),
                "area_m2": round(sum(r["properties"]["area_m2"] for r in regions if d in r["properties"]["dates"]), 1)}
            for d in sorted(set(dates))
        }),
    }
    (out / "change.json").write_text(json.dumps(summary, indent=2))
    for f in ("merged.npz", "drives.json", "qa.json"):  # the site's latest view reads the cloud and drives from the area folder
        (out / f).unlink(missing_ok=True)
        (out / f).symlink_to((work / f).resolve())
    # a minimal Run Record so `twin eval <folder>` reads G2 (from merge), G3 and G5
    acc = stage_metrics["accuracy"]
    write_document(out, {
        "run_id": f"area-{name}-twin",
        "data": mman.get("data", {}),
        "metrics": {"align": mman["metrics"]["align"], "ground": stage_metrics["ground"], "accuracy": acc},
        "stages": [{"seconds": v} for v in seconds.values()],
    })
    return summary


def area_twin_command(name: str, store: Path | None, check_date: str | None = None) -> int:
    from twin.runner import default_store

    logging.basicConfig(level=logging.INFO)
    base = Path(store) if store else default_store()
    print(json.dumps(twin_area(base, name, logging.getLogger("twin.areatwin"), check_date), indent=2))
    return 0
