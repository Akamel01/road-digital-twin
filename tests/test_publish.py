import json
import re
from pathlib import Path

import laspy
import pytest
from PIL import Image

from twin.cli import main
from twin.contracts import AreaIndex
from twin.fake_run import FACILITIES, write_fake_runs
from twin.publish import _rasters, _thin_laz, publish_runs
from twin.tiles import TILE, TileMeta

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("pub")
    store = base / "runs"
    folders = write_fake_runs(store, drives=2)
    return store, [f.name for f in folders]


def _site(runs, tmp_path, **limits):
    store, run_ids = runs
    site = tmp_path / "site"
    publish_runs(run_ids, site, store, **limits)
    return site, run_ids


def test_layout_and_area_validate(runs, tmp_path):
    site, run_ids = _site(runs, tmp_path)
    for rid in run_ids:
        for name in ("twin.geojson", "manifest.json", "twin.laz", "plan.pdf", "profile.csv"):
            assert (site / rid / name).is_file(), name
        for raster in ("lidar", "ortho", "coverage"):
            assert (site / "tiles" / rid / raster / "0" / "0" / "0.webp").is_file()
        assert laspy.read(site / rid / "twin.laz").header.point_count > 0
    assert Image.open(site / "tiles" / run_ids[0] / "lidar" / "2" / "1" / "1.webp")
    area = AreaIndex.model_validate_json((site / "area.json").read_text())
    try:
        import jsonschema
    except ImportError:
        jsonschema = None
    if jsonschema:
        jsonschema.validate(
            json.loads((site / "area.json").read_text()),
            json.loads((SCHEMAS / "area_index.schema.json").read_text()),
        )
    assert [d.run_id for d in area.drives] == run_ids


def test_best_run_is_highest_coverage(runs, tmp_path):
    site, run_ids = _site(runs, tmp_path)
    area = AreaIndex.model_validate_json((site / "area.json").read_text())
    by_name = {f.name: f for f in area.facilities}
    spec = {f.name: f for f in FACILITIES}
    for name, fs in spec.items():
        if name not in by_name:
            continue
        got = by_name[name]
        best_index = max(fs.observed, key=fs.observed.get)
        assert got.best_run == run_ids[best_index], name
        assert got.observed_core == fs.observed[best_index]
        assert set(got.runs) == {run_ids[i] for i in fs.observed}
        assert got.not_scanned_enough == (got.observed_core < 0.5)
    assert by_name["Fake St, block 1"].best_run == run_ids[1]


def test_file_size_limit_names_file(runs, tmp_path):
    with pytest.raises(ValueError, match=r"\.\w+: \d+ bytes exceeds 1000 byte limit"):
        _site(runs, tmp_path, max_file_bytes=1000)


def test_file_count_limit(runs, tmp_path):
    with pytest.raises(ValueError, match="files in"):
        _site(runs, tmp_path, max_files=10)


def test_laz_thinned_under_limit(runs, tmp_path):
    store, run_ids = runs
    src = store / run_ids[0] / "10_outputs" / "twin.laz"
    dst = tmp_path / "thin.laz"
    limit = src.stat().st_size // 2
    _thin_laz(src, dst, limit)
    assert dst.stat().st_size <= limit
    assert 0 < laspy.read(dst).header.point_count < laspy.read(src).header.point_count


def test_cli_publish(runs, tmp_path, capsys):
    store, run_ids = runs
    site = tmp_path / "cli"
    code = main(["publish", *run_ids, "--out", str(site), "--store", str(store)])
    assert code == 0
    assert (site / "area.json").is_file()
    assert re.search("area.json", capsys.readouterr().out)


def test_tile_meta_places_tiles(runs, tmp_path):
    store, run_ids = runs
    site, _ = _site(runs, tmp_path)
    area = AreaIndex.model_validate_json((site / "area.json").read_text())
    for rid in run_ids:
        las = laspy.read(store / rid / "4_ground" / "ground.laz")
        minx, miny = float(las.x.min()), float(las.y.min())
        extent = max(float(las.x.max()) - minx, float(las.y.max()) - miny)
        for raster in ("lidar", "ortho", "coverage"):
            meta = TileMeta.model_validate_json(
                (site / "tiles" / rid / raster / "meta.json").read_text()
            )
            assert meta.crs == "EPSG:32619"
            assert meta.bbox[0] == pytest.approx(minx)
            assert meta.bbox[1] == pytest.approx(miny)
            assert meta.bbox[2] - meta.bbox[0] == pytest.approx(
                meta.bbox[3] - meta.bbox[1]
            )
            assert meta.bbox[2] - meta.bbox[0] >= extent
            assert meta.cell_m_at_zmax == pytest.approx(
                (meta.bbox[2] - meta.bbox[0]) / (TILE * 2**meta.zmax)
            )
        drive = next(d for d in area.drives if d.run_id == rid)
        assert drive.bbox == pytest.approx(list(meta.bbox))


def test_fake_showcase_writes_tile_meta(runs, tmp_path):
    store, run_ids = runs
    ref = tmp_path / "ref"
    publish_runs(run_ids, ref, store=store)
    for rid in run_ids:
        for raster in ("lidar", "ortho", "coverage"):
            meta = TileMeta.model_validate_json(
                (store / "showcase" / "tiles" / rid / raster / "meta.json").read_text()
            )
            assert meta.crs == "EPSG:32619"
            assert meta.zmax >= 0
            assert meta.bbox[2] > meta.bbox[0] and meta.bbox[3] > meta.bbox[1]
            assert meta.cell_m_at_zmax == pytest.approx(
                (meta.bbox[2] - meta.bbox[0]) / (TILE * 2**meta.zmax)
            )
            ref_meta = (ref / "tiles" / rid / raster / "meta.json").read_text()
            assert (store / "showcase" / "tiles" / rid / raster / "meta.json").read_text() == ref_meta
            assert (store / "showcase" / "tiles" / rid / raster / "0" / "0" / "0.webp").is_file()


def test_lidar_intensity_white_point(tmp_path):
    store = tmp_path / "runs"
    folders = write_fake_runs(store, drives=1)
    run_dir = folders[0]

    import laspy
    import numpy as np

    xs = np.array([0.0, 50.0, 0.0, 50.0])
    ys = np.array([0.0, 0.0, 50.0, 50.0])
    zs = np.zeros(4)
    xyz = np.column_stack([xs, ys, zs])
    header = laspy.LasHeader(point_format=6)
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = xyz.min(axis=0)
    las = laspy.LasData(header)
    las.x = xs
    las.y = ys
    las.z = zs
    las.intensity = np.array([0, 30, 60, 110], dtype=np.uint16)
    las.write(run_dir / "4_ground" / "ground.laz")

    from twin.contracts import Manifest

    manifest = Manifest.model_validate_json((run_dir / "manifest.json").read_text())
    rasters, _zoom, _bbox = _rasters(run_dir, manifest)
    lidar = rasters["lidar"]
    filled = lidar[..., 3] == 255
    assert sorted(lidar[filled, 0].tolist()) == [0, 127, 255, 255]
