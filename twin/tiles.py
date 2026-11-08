"""256 px WebP tile pyramids for plan rasters (decision 41)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict

TILE = 256
MAX_ZOOM = 2


class TileMeta(BaseModel):
    """meta.json beside each raster's pyramid, so the UI can place tiles."""

    model_config = ConfigDict(extra="forbid")

    crs: Literal["EPSG:32619"] = "EPSG:32619"
    bbox: tuple[float, float, float, float]  # minx, miny, maxx, maxy in metres
    tile_px: int = TILE
    zmin: int = 0
    zmax: int
    cell_m_at_zmax: float
    origin: Literal["top-left"] = "top-left"


def write_tiles(
    showcase: Path,
    run_id: str,
    rasters: dict[str, np.ndarray],
    bbox: tuple[float, float, float, float],
    max_zoom: int = MAX_ZOOM,
) -> None:
    """Write showcase/tiles/<run>/<raster>/<z>/<x>/<y>.webp and meta.json per raster.

    Level z is the raster resized to TILE * 2**z px square, cut into TILE px tiles.
    bbox is the extent the level-max grid covers; the raster must be square.
    """
    meta = TileMeta(
        bbox=bbox,
        zmax=max_zoom,
        cell_m_at_zmax=(bbox[2] - bbox[0]) / (TILE * 2**max_zoom),
    )
    for name, base in rasters.items():
        img0 = Image.fromarray(base)
        for z in range(max_zoom + 1):
            side = TILE * 2**z
            img = img0.resize((side, side), Image.Resampling.NEAREST)
            for tx in range(2**z):
                for ty in range(2**z):
                    path = (
                        showcase
                        / "tiles"
                        / run_id
                        / name
                        / str(z)
                        / str(tx)
                        / f"{ty}.webp"
                    )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tile = img.crop(
                        (tx * TILE, ty * TILE, (tx + 1) * TILE, (ty + 1) * TILE)
                    )
                    tile.save(path, "WEBP", lossless=True)
        (showcase / "tiles" / run_id / name / "meta.json").write_text(
            meta.model_dump_json(indent=2)
        )
