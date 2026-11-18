"""256 px WebP tile pyramids for plan rasters (decision 41)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

TILE = 256


def write_mosaic_tiles(out, layer, mosaic, zmax, bbox, meta) -> None:
    """Write sparse loose XYZ WebP tiles for one area mosaic layer.

    Writes ``out/tiles/<layer>/<z>/<x>/<y>.webp``, skipping tiles whose alpha
    channel is entirely zero. Writes ``out/tiles/<layer>/meta.json`` with bbox,
    crs, zmin, zmax, cell_m_at_zmax and the written tile list/count.
    lidar/ortho use lossy WebP (q85); height/coverage use lossless WebP.
    """
    out = Path(out)
    layer_dir = out / "tiles" / layer
    lossy = layer in ("lidar", "ortho")
    arr = np.asarray(mosaic)
    base_img = Image.fromarray(arr.astype(np.uint8))
    written: list[list[int]] = []
    for z in range(zmax + 1):
        side = TILE * 2**z
        img = base_img.resize((side, side), Image.Resampling.NEAREST)
        n = 2**z
        for tx in range(n):
            for ty in range(n):
                tile = img.crop((tx * TILE, ty * TILE, (tx + 1) * TILE, (ty + 1) * TILE))
                tile_arr = np.asarray(tile)
                if tile_arr.shape[-1] >= 4 and not (tile_arr[..., 3] > 0).any():
                    continue
                path = layer_dir / str(z) / str(tx) / f"{ty}.webp"
                path.parent.mkdir(parents=True, exist_ok=True)
                if lossy:
                    tile.save(path, "WEBP", quality=85)
                else:
                    tile.save(path, "WEBP", lossless=True)
                written.append([z, tx, ty])

    if hasattr(meta, "model_dump"):
        meta_dict: dict[str, Any] = dict(meta.model_dump())
    elif isinstance(meta, dict):
        meta_dict = dict(meta)
    else:
        meta_dict = {}
    meta_dict.setdefault("crs", "EPSG:32619")
    meta_dict.setdefault("bbox", [float(v) for v in bbox])
    meta_dict.setdefault("zmin", 0)
    meta_dict.setdefault("zmax", int(zmax))
    meta_dict.setdefault(
        "cell_m_at_zmax", float((bbox[2] - bbox[0]) / (TILE * 2**zmax))
    )
    meta_dict.setdefault("tile_px", TILE)
    meta_dict["tiles"] = written
    meta_dict["tile_count"] = len(written)
    meta_dict["count"] = len(written)
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / "meta.json").write_text(json.dumps(meta_dict, indent=2))
