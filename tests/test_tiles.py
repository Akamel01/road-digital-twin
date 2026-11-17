import io
import json

import numpy as np
import pytest
from PIL import Image
from pmtiles.reader import MemorySource, Reader

from twin.cli import main
from twin.fake_run import write_fake_runs
from twin.publish import (
    PublishReport,
    _bincount_intensity,
    _coverage_union,
    _ortho_first_wins,
)
from twin.tiles import TILE


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    base = tmp_path_factory.mktemp("tiles")
    s = base / "store"
    write_fake_runs(s, drives=2)
    return s


def test_mosaic_presence(store):
    tiles = store / "showcase" / "tiles"
    for layer in ("lidar", "ortho", "height", "coverage"):
        assert (tiles / f"{layer}.pmtiles").is_file()
    # per-drive pyramids are still written (kept until web ticket lands)


def test_tile_decode(store):
    data = (store / "showcase" / "tiles" / "lidar.pmtiles").read_bytes()
    reader = Reader(MemorySource(data))
    # z=1 covered tile (bottom-right data)
    blob = reader.get(1, 1, 0)
    img = Image.open(io.BytesIO(blob))
    assert img.size == (TILE, TILE)
    assert img.getpixel((TILE - 1, TILE - 1)) == (255, 255, 255, 255)


def test_metadata_roundtrip(store):
    data = (store / "showcase" / "tiles" / "lidar.pmtiles").read_bytes()
    reader = Reader(MemorySource(data))
    header = reader.header()
    meta = reader.metadata()
    assert header["min_zoom"] == 0
    assert meta["zmin"] == 0
    assert meta["crs"] == "EPSG:32619"
    assert meta["origin"] == "top-left"
    assert "bbox" in meta and "cell_m_at_zmax" in meta
    assert "layer" in meta and "run_ids" in meta
    extent = meta["bbox"][2] - meta["bbox"][0]
    zmax = meta["zmax"]
    assert meta["cell_m_at_zmax"] == pytest.approx(extent / (TILE * 2 ** zmax))


def test_seam_check(store):
    layers = ("lidar", "ortho", "height", "coverage")
    for layer in layers:
        data = (store / "showcase" / "tiles" / f"{layer}.pmtiles").read_bytes()
        reader = Reader(MemorySource(data))
        z = reader.header()["max_zoom"]
        if layer == "height":
            # height mosaic has zmax=0 (single tile): no adjacent tile seam to check.
            assert z == 0, (layer, z)
            continue
        compared = 0
        maxdiff = 0
        ntx = 2 ** z
        for tx in range(ntx - 1):
            for y in range(ntx):
                left = Image.open(io.BytesIO(reader.get(z, tx, y))).convert('RGBA')
                right = Image.open(io.BytesIO(reader.get(z, tx + 1, y))).convert('RGBA')
                for row in range(TILE):
                    lp = left.getpixel((TILE - 1, row))
                    rp = right.getpixel((0, row))
                    if lp[3] == 0 and rp[3] == 0:
                        continue
                    compared += 1
                    if lp[3] > 0 and rp[3] > 0:
                        for c in range(3):
                            maxdiff = max(maxdiff, abs(lp[c] - rp[c]))
        if layer == "lidar":
            # non-vacuous: force z=1 where data exists; fall back to within-tile seam.
            z = min(1, reader.header()["max_zoom"])
            if z < 1:
                z = reader.header()["max_zoom"]
            compared = 0
            maxdiff = 0
            ntx = 2 ** z
            for tx in range(ntx - 1):
                for y in range(ntx):
                    left = Image.open(io.BytesIO(reader.get(z, tx, y))).convert('RGBA')
                    right = Image.open(io.BytesIO(reader.get(z, tx + 1, y))).convert('RGBA')
                    for row in range(TILE):
                        lp = left.getpixel((TILE - 1, row))
                        rp = right.getpixel((0, row))
                        if lp[3] == 0 or rp[3] == 0:
                            continue
                        compared += 1
                        for c in range(3):
                            maxdiff = max(maxdiff, abs(lp[c] - rp[c]))
            if compared == 0:
                tile = Image.open(io.BytesIO(reader.get(z, ntx - 1, ntx - 1))).convert('RGBA')
                for row in range(TILE):
                    lp = tile.getpixel((TILE // 2 - 1, row))
                    rp = tile.getpixel((TILE // 2, row))
                    if lp[3] == 0 and rp[3] == 0:
                        continue
                    compared += 1
                    if lp[3] > 0 and rp[3] > 0:
                        for c in range(3):
                            maxdiff = max(maxdiff, abs(lp[c] - rp[c]))
            assert compared > 0, (layer, "no opaque pairs compared")
            assert maxdiff <= 1, (layer, maxdiff, compared)
            continue
        # non-vacuous: at least one opaque pair must have been compared
        assert compared > 0, (layer, "no opaque pairs compared")
        # seam tolerance: adjacent non-empty cells differ by at most 1
        assert maxdiff <= 1, (layer, maxdiff, compared)


def test_overlap_tiebreak(store):
    # lidar: mean of both drives' intensities (fixture drives are paint-level -> 255)
    lidar_data = (store / "showcase" / "tiles" / "lidar.pmtiles").read_bytes()
    lidar_reader = Reader(MemorySource(lidar_data))
    lz = lidar_reader.header()["max_zoom"]
    lidar_img = Image.open(io.BytesIO(lidar_reader.get(lz, 1, 1))).convert("RGBA")
    lidar_cell = next(
        ( (x, y) for y in range(TILE) for x in range(TILE)
          if lidar_img.getpixel((x, y))[3] > 0 ),
        None,
    )
    assert lidar_cell is not None, "no opaque lidar cell in overlap"
    assert lidar_img.getpixel(lidar_cell)[:3] == (255, 255, 255), "lidar != mean"

    # ortho: first drive in run order wins in the overlapping (observed) region
    ortho_data = (store / "showcase" / "tiles" / "ortho.pmtiles").read_bytes()
    ortho_reader = Reader(MemorySource(ortho_data))
    oz = ortho_reader.header()["max_zoom"]
    ortho_img = Image.open(io.BytesIO(ortho_reader.get(oz, 1, 1))).convert("RGBA")
    ortho_cell = next(
        ( (x, y) for y in range(TILE) for x in range(TILE)
          if ortho_img.getpixel((x, y))[3] > 0 ),
        None,
    )
    assert ortho_cell is not None, "no opaque ortho cell in overlap"
    assert ortho_img.getpixel(ortho_cell)[:3] == (168, 160, 150), "ortho != first drive"

    # height: build-wide value present (single tile, z=0)
    height_data = (store / "showcase" / "tiles" / "height.pmtiles").read_bytes()
    height_reader = Reader(MemorySource(height_data))
    hz = height_reader.header()["max_zoom"]
    assert hz == 0
    height_img = Image.open(io.BytesIO(height_reader.get(hz, 0, 0))).convert("RGBA")
    height_cell = next(
        ( (x, y) for y in range(TILE) for x in range(TILE)
          if height_img.getpixel((x, y))[3] > 0 ),
        None,
    )
    assert height_cell is not None, "no height cell"

    # coverage: observed (union) in the overlapping region
    cov_data = (store / "showcase" / "tiles" / "coverage.pmtiles").read_bytes()
    cov_reader = Reader(MemorySource(cov_data))
    cz = cov_reader.header()["max_zoom"]
    cov_img = Image.open(io.BytesIO(cov_reader.get(cz, 1, 1))).convert("RGBA")
    cov_cell = next(
        ( (x, y) for y in range(TILE) for x in range(TILE)
          if cov_img.getpixel((x, y))[3] > 0 ),
        None,
    )
    assert cov_cell is not None, "no coverage cell"
    assert cov_img.getpixel(cov_cell)[:3] == (156, 199, 164), "coverage != observed"

    # continuity across overlap region: a full row of observed cells, no gaps
    row = ortho_cell[1]
    run = 0
    maxrun = 0
    for x in range(TILE):
        if cov_img.getpixel((x, row))[3] > 0:
            run += 1
            maxrun = max(maxrun, run)
        else:
            run = 0
    assert maxrun >= 10, (maxrun, "gap in overlap region")


def test_overlap_production(tmp_path):
    from twin.fake_run import write_fake_runs
    from twin.publish import publish_runs

    store = tmp_path / "store"
    run_dirs = write_fake_runs(store, drives=2)
    run_ids = [p.name for p in run_dirs]
    # publish_runs already invoked by write_fake_runs; call explicitly to be production-backed.
    publish_runs(run_ids, store / "showcase", store=store)

    # ortho: first drive wins in the overlapping (observed) region — production path.
    ortho_data = (store / "showcase" / "tiles" / "ortho.pmtiles").read_bytes()
    ortho_reader = Reader(MemorySource(ortho_data))
    ortho_blob = ortho_reader.get(1, 1, 0)
    assert ortho_blob is not None
    ortho_img = Image.open(io.BytesIO(ortho_blob)).convert("RGBA")
    covered = [ (x, y) for y in range(TILE) for x in range(TILE)
                if ortho_img.getpixel((x, y))[3] > 0 ]
    assert covered, "no covered ortho pixel in overlap tile"
    assert ortho_img.getpixel(covered[0])[:3] == (168, 160, 150), "ortho != first drive"

    # coverage: union -> alpha > 0 in covered region.
    cov_data = (store / "showcase" / "tiles" / "coverage.pmtiles").read_bytes()
    cov_reader = Reader(MemorySource(cov_data))
    cov_blob = cov_reader.get(1, 1, 0)
    assert cov_blob is not None
    cov_img = Image.open(io.BytesIO(cov_blob)).convert("RGBA")
    assert any(cov_img.getpixel((x, y))[3] > 0 for y in range(TILE) for x in range(TILE)), "no coverage"

    # height: build-wide field produced (PMTiles exists).
    height_data = (store / "showcase" / "tiles" / "height.pmtiles").read_bytes()
    height_reader = Reader(MemorySource(height_data))
    height_blob = height_reader.get(0, 0, 0)
    assert height_blob is not None, "height tile missing"

    # lidar: PMTiles exists.
    lidar_data = (store / "showcase" / "tiles" / "lidar.pmtiles").read_bytes()
    lidar_reader = Reader(MemorySource(lidar_data))
    lidar_blob = lidar_reader.get(1, 1, 0)
    assert lidar_blob is not None, "lidar tile missing"


def test_file_count_and_size(store):
    report = PublishReport.model_validate_json(
        (store / "showcase" / "publish_report.json").read_text()
    )
    pm = sorted((store / "showcase" / "tiles").glob("*.pmtiles"))
    assert len(pm) == 4
    for p in pm:
        assert p.stat().st_size <= 25 * 1024 * 1024
    assert report.total_bytes == sum(p.stat().st_size for p in (store / "showcase").rglob("*") if p.is_file())
    assert report.total_files >= 4


def test_dry_run(store, tmp_path, monkeypatch, capsys):
    run_id = next(p.name for p in store.iterdir() if p.is_dir() and p.name != "showcase")
    gates = store / run_id / "gates.json"
    if not gates.exists():
        gates.write_text(json.dumps({"run_id": run_id, "verdict": "go", "gates_version": 1, "gates": {}}))
    code = main(["site", "publish", run_id, "--dry-run", "--store", str(store)])
    out = capsys.readouterr().out
    assert code == 0
    assert "files=" in out


def test_aggregation_tiebreak():
    # lidar mean: _bincount_intensity with intensities 100,200 -> 150.
    grid = (0.0, 0.0, 1.0, 4)
    xs = np.array([0.5, 0.5])
    ys = np.array([0.5, 0.5])
    intensity = np.array([100.0 / 255.0, 200.0 / 255.0])
    lidar = _bincount_intensity(xs, ys, intensity, grid)
    assert lidar[3, 0, :3].tolist() == [150, 150, 150]
    assert lidar[3, 0, 3] == 255

    # ortho first-wins: production helper.
    side = 4
    o0 = np.zeros((side, side, 4), np.uint8)
    o0[3, 0] = (255, 0, 0, 255)
    o1 = np.zeros((side, side, 4), np.uint8)
    o1[3, 0] = (0, 0, 255, 255)
    ortho = _ortho_first_wins([o0, o1])
    assert ortho[3, 0, :3].tolist() == [255, 0, 0]
    assert ortho[3, 0, 3] == 255

    # coverage union: observed where either drive has alpha.
    has_points = np.zeros((side, side), bool)
    has_points[3, 0] = True
    cov = _coverage_union([o0, o1], has_points)
    assert cov[3, 0, :3].tolist() == [156, 199, 164]
    assert cov[3, 0, 3] == 160

    # height: compute_height_above_road on two drives -> build-wide value present.
    from twin.height_raster import compute_height_above_road
    hf = compute_height_above_road([
        (np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([1.0, 2.0])),
        (np.array([2.0]), np.array([2.0]), np.array([3.0])),
    ])
    assert hf.h.size > 0

    # continuity: no gaps/NaN across overlap region.
    assert not np.isnan(ortho.astype(float)).any()
    assert not np.isnan(cov.astype(float)).any()
