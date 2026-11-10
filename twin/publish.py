"""twin publish: copy one run per drive into a static showcase folder (spec section 3)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import laspy
import numpy as np
from PIL import Image

from twin.contracts import STAGES, AreaFacility, AreaIndex, Drive, Manifest
from twin.runner import default_store
from twin.tiles import TILE, write_tiles

MAX_FILE_BYTES = 25 * 1024 * 1024  # Pages limit per file
MAX_FILES = 20_000  # Pages limit per build, exclusive
FALLBACK_GSD_M = 0.1  # raster cell when the colour stage did not run
MAX_ZOOM = (
    4  # ponytail: pyramid capped at 4096 px per raster, bigger drives get coarser cells
)
THIN_ROUNDS = 6  # ponytail: LAZ thinning doubles the voxel up to this many times
PUBLIC_FILES = ("twin.geojson", "plan.pdf", "plan.dxf", "profile.pdf", "profile.dxf")
# Coverage colours match the web legend: observed green, unobserved red (web/components/MapPanel.tsx).
OBSERVED = (156, 199, 164, 160)  # #9CC7A4
UNOBSERVED = (224, 112, 79, 150)  # #E0704F


def _stage(run_dir: Path, name: str) -> Path:
    return run_dir / f"{STAGES[name].number}_{name}"


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


def _ortho(run_dir: Path, grid: tuple) -> np.ndarray | None:
    """colour/ortho.png resampled onto the plan grid, alpha kept."""
    png = _stage(run_dir, "colour") / "ortho.png"
    if not png.exists():
        return None
    x0, y0, cell, side = grid
    img = np.asarray(Image.open(png).convert("RGBA"))
    a, _, _, e, c, f = map(
        float, (_stage(run_dir, "colour") / "ortho.pgw").read_text().split()
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


def _rasters(
    run_dir: Path, manifest: Manifest
) -> tuple[dict[str, np.ndarray], int, tuple[float, float, float, float]]:
    """Lidar intensity, orthoimage and coverage on one square grid over the ground points."""
    las = laspy.read(_stage(run_dir, "ground") / "ground.laz")
    x, y = np.asarray(las.x), np.asarray(las.y)
    intensity = np.asarray(las.intensity, dtype=np.float64) / 65535
    gsd = _gsd(manifest)
    x0, y0 = float(x.min()), float(y.min())
    extent = max(float(x.max()) - x0, float(y.max()) - y0, gsd)
    need = int(np.ceil(extent / gsd))
    zoom = min(MAX_ZOOM, max(0, int(np.ceil(np.log2(need / TILE)))))
    side = TILE * 2**zoom
    cell = extent / side
    cols = np.clip(((x - x0) / cell).astype(int), 0, side - 1)
    rows = np.clip(side - 1 - ((y - y0) / cell).astype(int), 0, side - 1)
    flat = rows * side + cols
    count = np.bincount(flat, minlength=side * side)
    total = np.bincount(flat, weights=intensity, minlength=side * side)
    filled = count > 0
    lidar = np.zeros((side * side, 4), np.uint8)
    lidar[filled, :3] = (total[filled] / count[filled] * 255).astype(np.uint8)[:, None]
    lidar[filled, 3] = 255
    lidar = lidar.reshape(side, side, 4)
    rasters = {"lidar": lidar}
    ortho = _ortho(run_dir, (x0, y0, cell, side))
    observed = np.zeros((side, side), bool)
    if ortho is not None:
        rasters["ortho"] = ortho
        observed = ortho[..., 3] > 0
    coverage = np.zeros((side, side, 4), np.uint8)
    coverage[lidar[..., 3] > 0] = UNOBSERVED  # ground the lidar saw but no camera coloured
    coverage[observed] = OBSERVED
    rasters["coverage"] = coverage
    bbox = (x0, y0, x0 + side * cell, y0 + side * cell)
    return rasters, zoom, bbox


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
        load = _stage(run_dir, "load") / "facilities.geojson"
        for feat in json.loads(load.read_text())["features"]:
            meta.setdefault(feat["properties"]["id"], feat["properties"])
        observed = json.loads((_stage(run_dir, "ground") / "qa.json").read_text())
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


def publish_runs(
    run_ids: list[str],
    out: Path,
    store: Path,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_files: int = MAX_FILES,
) -> AreaIndex:
    """Copy the public files of each run into out (the showcase folder) and write area.json.

    Raises ValueError naming the file when a file exceeds max_file_bytes or the
    folder holds max_files or more files.
    """
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for rid in run_ids:
        run_dir = store / rid
        manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
        dest = out / manifest.run_id
        dest.mkdir(exist_ok=True)
        shutil.copy(run_dir / "manifest.json", dest / "manifest.json")
        outputs = _stage(run_dir, "outputs")
        for name in PUBLIC_FILES:
            shutil.copy(outputs / name, dest / name)
        for name in ("profile.csv", "centrelines.geojson"):  # the profile stage is optional
            if (_stage(run_dir, "profile") / name).exists():
                shutil.copy(_stage(run_dir, "profile") / name, dest / name)
        _thin_laz(outputs / "twin.laz", dest / "twin.laz", max_file_bytes)
        rasters, zoom, bbox = _rasters(run_dir, manifest)
        write_tiles(out, manifest.run_id, rasters, bbox, max_zoom=zoom)
        runs.append((manifest, run_dir, bbox))
    area = _area(runs)
    (out / "area.json").write_text(area.model_dump_json(indent=2))
    files = [p for p in out.rglob("*") if p.is_file()]
    for path in files:
        _check_size(path, out, max_file_bytes)
    if len(files) >= max_files:
        raise ValueError(f"{len(files)} files in {out}, limit is {max_files - 1}")
    return area


def publish_command(run_ids: list[str], out: Path, store: Path | None) -> int:
    try:
        publish_runs(run_ids, out, store or default_store())
    except ValueError as err:
        print(f"twin publish: {err}", file=sys.stderr)
        return 1
    print(out / "area.json")
    return 0
