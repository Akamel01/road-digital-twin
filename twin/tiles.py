"""256 px WebP tile pyramids for plan rasters (decision 41)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image
from pmtiles.reader import MemorySource, Reader
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from pydantic import BaseModel, ConfigDict
from pyproj import Transformer

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


class PMTilesMeta(BaseModel):
    """Metadata embedded in a PMTiles archive (consumer-needed fields)."""

    crs: str = "EPSG:32619"
    bbox: tuple[float, float, float, float] | None = None
    tile_px: int = TILE
    zmin: int = 0
    zmax: int = 0
    cell_m_at_zmax: float = 0.0
    origin: str = "top-left"
    layer: str = ""
    run_ids: list[str] = []


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


def write_pmtiles(
    path,
    tiles_by_zoom: dict[int, dict[tuple[int, int], bytes]],
    meta: PMTilesMeta,
    header_bbox_wgs84,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Collect tile ids and sort ascending for clustered writes.
    entries: list[tuple[int, int, int, bytes]] = []
    for z, tiles in tiles_by_zoom.items():
        for (x, y), data in tiles.items():
            entries.append((z, x, y, data))
    entries.sort(key=lambda e: zxy_to_tileid(e[0], e[1], e[2]))

    transformer = Transformer.from_crs("EPSG:32619", "EPSG:4326", always_xy=True)
    minx, miny, maxx, maxy = header_bbox_wgs84
    if abs(minx) > 180 or abs(maxx) > 180 or abs(miny) > 90 or abs(maxy) > 90:
        lon_min, lat_min = transformer.transform(minx, miny)
        lon_max, lat_max = transformer.transform(maxx, maxy)
    else:
        lon_min, lat_min, lon_max, lat_max = minx, miny, maxx, maxy
    min_lon = min(lon_min, lon_max)
    max_lon = max(lon_min, lon_max)
    min_lat = min(lat_min, lat_max)
    max_lat = max(lat_min, lat_max)

    header = {
        "tile_type": TileType.WEBP,
        "tile_compression": Compression.NONE,
        "min_zoom": 0,
        "max_zoom": meta.zmax,
        "min_lon_e7": round(min_lon * 1e7),
        "min_lat_e7": round(min_lat * 1e7),
        "max_lon_e7": round(max_lon * 1e7),
        "max_lat_e7": round(max_lat * 1e7),
        "center_lon_e7": round(((min_lon + max_lon) / 2) * 1e7),
        "center_lat_e7": round(((min_lat + max_lat) / 2) * 1e7),
        "center_zoom": meta.zmax,
    }

    with open(path, "wb") as f:
        writer = Writer(f)
        for z, x, y, data in entries:
            tile_id = zxy_to_tileid(z, x, y)
            writer.write_tile(tile_id, data)
        writer.finalize(header, meta.model_dump())

    return path


def read_pmtiles(path):
    path = Path(path)
    data = path.read_bytes()
    source = MemorySource(data)
    reader = Reader(source)
    header = reader.header()
    metadata = reader.metadata()
    return header, metadata, reader.get
