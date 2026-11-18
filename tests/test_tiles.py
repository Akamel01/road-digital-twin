import json

import numpy as np
import pytest
from PIL import Image

from twin.fake_run import write_fake_runs
from twin.publish import (
    _bincount_intensity,
    _coverage_union,
    _ortho_first_wins,
    publish_runs,
)
from twin.tiles import TILE, write_mosaic_tiles


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    base = tmp_path_factory.mktemp("tiles")
    s = base / "store"
    runs = write_fake_runs(s, drives=2)
    publish_runs([p.name for p in runs], s / "showcase", store=s)
    return s


def test_mosaic_presence(store):
    tiles = store / "showcase" / "tiles"
    for layer in ("lidar", "ortho", "height", "coverage"):
        assert (tiles / layer / "meta.json").is_file()
        assert any((tiles / layer).rglob("*.webp"))


def test_tile_decode(store):
    p = store / "showcase" / "tiles" / "lidar" / "1" / "1" / "0.webp"
    img = Image.open(p)
    assert img.size == (TILE, TILE)


def test_metadata_roundtrip(store):
    meta = json.loads((store / "showcase" / "tiles" / "lidar" / "meta.json").read_text())
    assert meta["crs"] == "EPSG:32619"
    assert meta["zmin"] == 0
    assert "bbox" in meta and "cell_m_at_zmax" in meta
    assert "tiles" in meta and "tile_count" in meta
    assert meta["tile_count"] == len(meta["tiles"])
    extent = meta["bbox"][2] - meta["bbox"][0]
    zmax = meta["zmax"]
    assert meta["cell_m_at_zmax"] == pytest.approx(extent / (TILE * 2 ** zmax))


def test_empty_tiles_skipped(store):
    # at least one missing tile in grid (sparse)
    layer_dir = store / "showcase" / "tiles" / "lidar"
    meta = json.loads((layer_dir / "meta.json").read_text())
    z = meta["zmax"]
    total = (2 ** z) ** 2
    level_tiles = [t for t in meta["tiles"] if t[0] == z]
    assert len(level_tiles) <= total


def test_aggregation_tiebreak():
    grid = (0.0, 0.0, 1.0, 4)
    xs = np.array([0.5, 0.5])
    ys = np.array([0.5, 0.5])
    intensity = np.array([100.0 / 255.0, 200.0 / 255.0])
    lidar = _bincount_intensity(xs, ys, intensity, grid)
    assert lidar[3, 0, :3].tolist() == [150, 150, 150]
    assert lidar[3, 0, 3] == 255

    side = 4
    o0 = np.zeros((side, side, 4), np.uint8)
    o0[3, 0] = (255, 0, 0, 255)
    o1 = np.zeros((side, side, 4), np.uint8)
    o1[3, 0] = (0, 0, 255, 255)
    ortho = _ortho_first_wins([o0, o1])
    assert ortho[3, 0, :3].tolist() == [255, 0, 0]
    assert ortho[3, 0, 3] == 255

    has_points = np.zeros((side, side), bool)
    has_points[3, 0] = True
    cov = _coverage_union([o0, o1], has_points)
    assert cov[3, 0, :3].tolist() == [156, 199, 164]
    assert cov[3, 0, 3] == 160


def test_write_mosaic_tiles_skips_empty(tmp_path):
    mosaic = np.zeros((4, 4, 4), np.uint8)
    mosaic[0, 0] = (10, 20, 30, 255)
    write_mosaic_tiles(tmp_path, "lidar", mosaic, 0, (0.0, 0.0, 4.0, 4.0), {})
    assert (tmp_path / "tiles" / "lidar" / "0" / "0" / "0.webp").is_file()
    meta = json.loads((tmp_path / "tiles" / "lidar" / "meta.json").read_text())
    assert meta["tile_count"] == 1
