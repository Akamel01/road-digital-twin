"""twin publish: aggregate all drives into one square area grid per layer (spec section 3)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

import laspy
import numpy as np
from PIL import Image
from pydantic import BaseModel

from twin.contracts import AreaFacility, AreaIndex, Drive, Manifest, stage_dir
from twin.height_raster import compute_height_above_road, render_height_rgba
from twin.runner import default_store
from twin.runrecord import read_manifest, record_path
from twin.tiles import TILE, write_mosaic_tiles

MAX_FILE_BYTES = 25 * 1024 * 1024  # Pages limit per file
INTENSITY_WHITE = 60  # nuScenes ground LAZ intensity white point (P99.5 ~59, max 110, run 20261115-183951-13e4b7)
MAX_FILES = 20_000  # Pages limit per build, exclusive
HEIGHT_MOSAIC_TARGET_M = 0.125  # height mosaic target cell (half of 25 cm raster)
FALLBACK_GSD_M = 0.1  # raster cell when the colour stage did not run
MAX_ZOOM = 8  # mosaic pyramid upper cap
THIN_ROUNDS = 6  # ponytail: LAZ thinning doubles the voxel up to this many times
PUBLIC_FILES = ("twin.geojson", "plan.pdf", "plan.dxf", "profile.pdf", "profile.dxf")
# Coverage colours match the web legend: observed green, unobserved red (web/components/MapPanel.tsx).
OBSERVED = (156, 199, 164, 160)  # #9CC7A4
UNOBSERVED = (224, 112, 79, 150)  # #E0704F
LAYERS = ("lidar", "ortho", "height", "coverage")


class LayerReport(BaseModel):
    path: str
    max_zoom: int
    bytes: int
    tile_count: int
    cell_m_at_zmax: float = 0.0


class PublishReport(BaseModel):
    run_ids: list[str]
    layers: dict[str, LayerReport]
    total_bytes: int
    total_files: int
    max_file_bytes: int
    max_files: int
    tile_version: str = ""


def _check_size(path: Path, out: Path, max_bytes: int) -> None:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"{path.relative_to(out)}: {size} bytes exceeds {max_bytes} byte limit"
        )


def _thin_laz(src: Path, dst: Path, max_bytes: int) -> None:
    """Copy src to dst, thinning to one point per voxel until dst fits max_bytes."""
    if src.stat().st_size <= max_bytes:
        shutil.copy(src, dst)
        return
    las = laspy.read(src)
    xyz = np.column_stack([las.x, las.y, las.z])
    voxel = 0.1
    for _ in range(THIN_ROUNDS):
        keys = np.floor((xyz - xyz.min(axis=0)) / voxel).astype(np.int64)
        _, keep = np.unique(keys, axis=0, return_index=True)
        thin = laspy.LasData(las.header)
        thin.points = las.points[np.sort(keep)]
        thin.write(dst)
        if dst.stat().st_size <= max_bytes:
            return
        voxel *= 2
    raise ValueError(
        f"{dst.name}: {dst.stat().st_size} bytes exceeds {max_bytes} byte limit "
        f"after thinning to {voxel / 2} m voxels"
    )


def _gsd(manifest: Manifest) -> float:
    colour = [s for s in manifest.stages if s.name == "colour" and s.status == "ok"]
    return manifest.params.colour.gsd_m if colour else FALLBACK_GSD_M


def _resample_ortho(run_dir: Path, grid: tuple) -> np.ndarray | None:
    """colour/ortho.png resampled onto the plan grid, alpha kept."""
    png = stage_dir(run_dir, "colour") / "ortho.png"
    if not png.exists():
        return None
    x0, y0, cell, side = grid
    img = np.asarray(Image.open(png).convert("RGBA"))
    a, _, _, e, c, f = map(
        float, (stage_dir(run_dir, "colour") / "ortho.pgw").read_text().split()
    )
    rows, cols = np.meshgrid(np.arange(side), np.arange(side), indexing="ij")
    east = x0 + (cols + 0.5) * cell
    north = y0 + (side - rows - 0.5) * cell
    px = np.floor((east - (c - a / 2)) / a).astype(int)
    py = np.floor(((f - e / 2) - north) / -e).astype(int)
    h, w = img.shape[:2]
    ok = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    out = np.zeros((side, side, 4), np.uint8)
    out[ok] = img[py[ok], px[ok]]
    return out



def _grid_from_points(xs: np.ndarray, ys: np.ndarray, target: float) -> tuple[float, float, float, int]:
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    if xs.size == 0:
        x0, y0 = 0.0, 0.0
        extent = target
    else:
        x0 = float(xs.min())
        y0 = float(ys.min())
        extent = max(float(xs.max()) - x0, float(ys.max()) - y0, target)
    if extent <= 0:
        extent = target
    ratio = extent / (target * TILE)
    if ratio <= 1:
        z = 0
    else:
        z = math.ceil(math.log2(ratio))
    z = max(0, min(MAX_ZOOM, z))
    side = TILE * 2 ** z
    cell = extent / side
    return x0, y0, cell, side


def _bincount_intensity(
    xs: np.ndarray, ys: np.ndarray, intensity: np.ndarray, grid: tuple
) -> np.ndarray:
    x0, y0, cell, side = grid
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    intensity = np.asarray(intensity, dtype=np.float64)
    if xs.size == 0:
        return np.zeros((side, side, 4), np.uint8)
    cols = np.clip(((xs - x0) / cell).astype(int), 0, side - 1)
    rows = np.clip(side - 1 - ((ys - y0) / cell).astype(int), 0, side - 1)
    flat = rows * side + cols
    count = np.bincount(flat, minlength=side * side)
    total = np.bincount(flat, weights=intensity, minlength=side * side)
    filled = count > 0
    lidar = np.zeros((side * side, 4), np.uint8)
    lidar[filled, :3] = (total[filled] / count[filled] * 255).astype(np.uint8)[:, None]
    lidar[filled, 3] = 255
    return lidar.reshape(side, side, 4)



def _area(runs: list[tuple[Manifest, Path, tuple]]) -> AreaIndex:
    drives = [
        Drive(
            run_id=m.run_id,
            scene_token=m.data.scene_token,
            name=m.data.scene_token,
            bbox=list(bbox),
        )
        for m, _, bbox in runs
    ]
    meta: dict[str, dict] = {}
    covered: dict[str, dict[str, tuple[float, Manifest]]] = {}
    for m, run_dir, _ in runs:
        load = stage_dir(run_dir, "load") / "facilities.geojson"
        for feat in json.loads(load.read_text())["features"]:
            meta.setdefault(feat["properties"]["id"], feat["properties"])
        observed = json.loads((stage_dir(run_dir, "ground") / "qa.json").read_text())
        for fid, value in observed["observed_core"].items():
            covered.setdefault(fid, {})[m.run_id] = (value, m)
    facilities = []
    for fid, by_run in covered.items():
        best_id, (best, best_m) = max(by_run.items(), key=lambda kv: kv[1][0])
        props = meta[fid]
        facilities.append(
            AreaFacility(
                id=fid,
                type=props["type"],
                name=props["name"],
                best_run=best_id,
                runs=list(by_run),
                observed_core=best,
                not_scanned_enough=best < best_m.params.facilities.min_observed,
            )
        )
    return AreaIndex(drives=drives, facilities=facilities)




def _ortho_first_wins(drive_orthos: list[np.ndarray]) -> np.ndarray:
    """Mosaic ortho rasters: first drive (in run order) with alpha>0 wins per cell."""
    if not drive_orthos:
        return np.zeros((0, 0, 4), np.uint8)
    side = drive_orthos[0].shape[0]
    mosaic = np.zeros((side, side, 4), np.uint8)
    won = np.zeros((side, side), bool)
    for o in drive_orthos:
        o = np.asarray(o)
        a = o[..., 3] > 0
        take = a & ~won
        mosaic[take] = o[take]
        won |= a
    return mosaic


def _coverage_union(drive_orthos: list[np.ndarray], has_points: np.ndarray) -> np.ndarray:
    """Coverage layer: unobserved where lidar has points, observed where any drive has alpha."""
    has_points = np.asarray(has_points)
    side = has_points.shape[0] if has_points.ndim >= 1 else 0
    if drive_orthos:
        side = drive_orthos[0].shape[0]
    coverage = np.zeros((side, side, 4), np.uint8)
    coverage[has_points] = UNOBSERVED
    observed = np.zeros((side, side), bool)
    for o in drive_orthos:
        observed |= np.asarray(o)[..., 3] > 0
    coverage[observed] = OBSERVED
    return coverage


def _tile_version(out: Path, tiles_name: str = "tiles") -> str:
    """Content digest over mosaic WebP tiles (first 12 hex of sha256).

    Hashes paths as tiles/<layer>/... so the value is stable when computed over a
    temporary tiles directory before an atomic swap.
    """
    h = hashlib.sha256()
    entries = []
    tiles_dir = out / tiles_name
    for p in tiles_dir.glob("*/*/*/*.webp"):
        data = p.read_bytes()
        rel = (Path("tiles") / p.relative_to(tiles_dir)).as_posix()
        entries.append(f"{rel}:{len(data)}:{hashlib.sha256(data).hexdigest()}")
    for line in sorted(entries):
        h.update((line + "\n").encode())
    return h.hexdigest()[:12]


def publish_runs(
    run_ids: list[str],
    out: Path,
    store: Path,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_files: int = MAX_FILES,
) -> tuple[AreaIndex, PublishReport]:
    out.mkdir(parents=True, exist_ok=True)
    tiles_name = "tiles.new"
    tiles_tmp = out / tiles_name

    # Preload/validate runs before mutating published tiles: a bad run id or
    # manifest must not destroy a previous publish.
    all_drive_pts: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    manifests: list[Manifest] = []
    run_dirs: list[Path] = []
    for rid in run_ids:
        run_dir = store / rid
        manifest = read_manifest(run_dir)
        manifests.append(manifest)
        run_dirs.append(run_dir)
        las = laspy.read(stage_dir(run_dir, "ground") / "ground.laz")
        all_drive_pts.append((np.asarray(las.x), np.asarray(las.y), np.asarray(las.z)))
    h_map_all = compute_height_above_road(all_drive_pts)

    # combined bbox from all drives' ground points
    all_x = np.concatenate([p[0] for p in all_drive_pts])
    all_y = np.concatenate([p[1] for p in all_drive_pts])
    gsds = [_gsd(m) for m in manifests]
    target_lidar = max(0.05, max(gsds) if gsds else 0.05)
    grid = _grid_from_points(all_x, all_y, target_lidar)
    x0, y0, cell, side = grid

    shutil.rmtree(tiles_tmp, ignore_errors=True)

    # per-drive public files
    runs = []
    for i, rid in enumerate(run_ids):
        run_dir = run_dirs[i]
        manifest = manifests[i]
        dest = out / manifest.run_id
        dest.mkdir(exist_ok=True)
        shutil.copy(record_path(run_dir), dest / "run.json")
        outputs = stage_dir(run_dir, "outputs")
        for name in PUBLIC_FILES:
            shutil.copy(outputs / name, dest / name)
        for name in ("profile.csv", "centrelines.geojson"):
            if (stage_dir(run_dir, "profile") / name).exists():
                shutil.copy(stage_dir(run_dir, "profile") / name, dest / name)
        _thin_laz(outputs / "twin.laz", dest / "twin.laz", max_file_bytes)
        xd, yd, _ = all_drive_pts[i]
        gx0, gy0, gcell, gside = _grid_from_points(xd, yd, max(_gsd(manifest), 0.05))
        bbox_drive = (gx0, gy0, gx0 + gside * gcell, gy0 + gside * gcell)
        runs.append((manifest, run_dir, bbox_drive))

    area = _area(runs)
    (out / "area.json").write_text(area.model_dump_json(indent=2))

    layer_reports = {}
    # aggregate mosaics
    all_xs = np.concatenate([p[0] for p in all_drive_pts])
    all_ys = np.concatenate([p[1] for p in all_drive_pts])
    all_int = np.concatenate([
        np.clip(np.asarray(laspy.read(stage_dir(rd, "ground") / "ground.laz").intensity, dtype=np.float64) / INTENSITY_WHITE, 0.0, 1.0)
        for rd in run_dirs
    ])
    lidar_mosaic = _bincount_intensity(all_xs, all_ys, all_int, grid)

    drive_orthos = []
    for rd in run_dirs:
        o = _resample_ortho(rd, grid)
        if o is not None:
            drive_orthos.append(o)
    ortho_mosaic = _ortho_first_wins(drive_orthos)

    height_mosaic = render_height_rgba(h_map_all, x0=x0, y0=y0, cell=cell, side=side)

    coverage_mosaic = _coverage_union(drive_orthos, lidar_mosaic[..., 3] > 0)

    bbox = (x0, y0, x0 + side * cell, y0 + side * cell)

    layers_data = {
        "lidar": (lidar_mosaic, target_lidar),
        "ortho": (ortho_mosaic, target_lidar),
        "height": (height_mosaic, HEIGHT_MOSAIC_TARGET_M),
        "coverage": (coverage_mosaic, HEIGHT_MOSAIC_TARGET_M),
    }

    for layer in LAYERS:
        arr, target = layers_data[layer]
        g = _grid_from_points(all_x, all_y, target)
        _gx, _gy, gcell, gside = g
        gextent = gside * gcell
        # zmax = smallest z with cell <= target (computed below)
        zmax = 0
        ratio = gextent / (target * TILE)
        if ratio > 1:
            zmax = math.ceil(math.log2(ratio))
        zmax = max(0, min(MAX_ZOOM, zmax))
        meta = {
            "crs": "EPSG:32619",
            "bbox": [float(v) for v in bbox],
            "tile_px": TILE,
            "zmin": 0,
            "zmax": zmax,
            "cell_m_at_zmax": float(gextent / (TILE * 2**zmax)),
            "origin": "top-left",
            "layer": layer,
            "run_ids": run_ids,
        }
        write_mosaic_tiles(out, layer, arr, zmax, bbox, meta, tiles_name=tiles_name)
        # compute tile count
        layer_dir = tiles_tmp / layer
        tiles = [p for p in layer_dir.rglob("*.webp")]
        # per layer bytes = sum of webp + meta
        layer_bytes = sum(p.stat().st_size for p in layer_dir.rglob("*") if p.is_file())
        layer_reports[layer] = LayerReport(
            path=f"tiles/{layer}",
            max_zoom=zmax,
            bytes=layer_bytes,
            tile_count=len(tiles),
            cell_m_at_zmax=float(gextent / (TILE * 2**zmax)),
        )

    # Size/count checks over the would-be final output (tiles.new treated as tiles).
    files = [
        p for p in out.rglob("*")
        if p.is_file() and "tiles.new" not in p.relative_to(out).parts
    ]
    files.extend(p for p in tiles_tmp.rglob("*") if p.is_file())
    for path in [p for p in out.rglob("*") if p.is_file() and "tiles.new" not in p.relative_to(out).parts]:
        _check_size(path, out, max_file_bytes)
    for path in [p for p in tiles_tmp.rglob("*") if p.is_file()]:
        size = path.stat().st_size
        if size > max_file_bytes:
            rel = (Path("tiles") / path.relative_to(tiles_tmp)).as_posix()
            raise ValueError(f"{rel}: {size} bytes exceeds {max_file_bytes} byte limit")
    if len(files) >= max_files:
        raise ValueError(f"{len(files)} files in {out}, limit is {max_files - 1}")

    report = PublishReport(
        run_ids=run_ids,
        layers=layer_reports,
        total_bytes=0,
        total_files=len(files),
        max_file_bytes=max_file_bytes,
        max_files=max_files,
    )
    report_path = out / "publish_report.json"
    other = [p for p in files if p != report_path]
    base = sum(p.stat().st_size for p in other)
    report.tile_version = _tile_version(out, tiles_name=tiles_name)
    total = base
    for _ in range(10):
        report.total_bytes = total
        report_path.write_text(report.model_dump_json(indent=2))
        new_total = base + report_path.stat().st_size
        if new_total == total:
            break
        total = new_total
    report.total_bytes = total
    report_path.write_text(report.model_dump_json(indent=2))

    # Commit tiles atomically only after report/size checks succeeded.
    shutil.rmtree(out / "tiles", ignore_errors=True)
    os.replace(tiles_tmp, out / "tiles")
    return area, report

def publish_command(run_ids: list[str], out: Path, store: Path | None) -> int:
    try:
        _area, report = publish_runs(run_ids, out, store or default_store())
    except ValueError as err:
        print(f"twin publish: {err}", file=sys.stderr)
        return 1
    print(out / "area.json")
    per = " ".join(f"{k}:z{v.max_zoom} tiles={v.tile_count} bytes={v.bytes}" for k, v in report.layers.items())
    print(f"publish_report: files={report.total_files} {per} total_bytes={report.total_bytes}")
    return 0