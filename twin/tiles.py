"""256 px WebP tile pyramids for plan rasters (decision 41)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

TILE = 256
MAX_ZOOM = 2


def write_tiles(
    showcase: Path,
    run_id: str,
    rasters: dict[str, np.ndarray],
    max_zoom: int = MAX_ZOOM,
) -> None:
    """Write showcase/tiles/<run>/<raster>/<z>/<x>/<y>.webp for square RGBA rasters.

    Level z is the raster resized to TILE * 2**z px square, cut into TILE px tiles.
    """
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
