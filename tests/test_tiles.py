import io
import json

import pytest
from PIL import Image
from pmtiles.reader import MemorySource, Reader

from twin.cli import main
from twin.fake_run import write_fake_runs
from twin.publish import PublishReport
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
        if z < 1:
            continue
        maxdiff = 0
        for y in range(2 ** z):
            left = Image.open(io.BytesIO(reader.get(z, 0, y))).convert('RGBA')
            right = Image.open(io.BytesIO(reader.get(z, 1, y))).convert('RGBA')
            for row in range(TILE):
                lp = left.getpixel((TILE - 1, row))
                rp = right.getpixel((0, row))
                if lp[3] == 0 or rp[3] == 0:
                    continue
                for c in range(3):
                    maxdiff = max(maxdiff, abs(lp[c] - rp[c]))
        # seam tolerance: adjacent non-empty cells differ by at most 1
        assert maxdiff <= 1, (layer, maxdiff)


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
