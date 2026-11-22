import json
import re
from pathlib import Path

import laspy
import pytest

from twin.cli import main
from twin.contracts import AreaIndex
from twin.fake_run import FACILITIES, write_fake_runs
from twin.publish import (
    _bincount_intensity,
    _grid_from_points,
    _thin_laz,
    _tile_version,
    publish_runs,
)

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
        for name in ("twin.geojson", "run.json", "twin.laz", "plan.pdf", "profile.csv"):
            assert (site / rid / name).is_file(), name
        assert not (site / rid / "manifest.json").exists()
        assert laspy.read(site / rid / "twin.laz").header.point_count > 0
    for layer in ("lidar", "ortho", "height", "coverage"):
        assert (site / "tiles" / layer / "meta.json").is_file()
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
    for rid in run_ids:
        assert not (site / "tiles" / rid).exists()
    report = json.loads((site / "publish_report.json").read_text())
    assert re.fullmatch(r"[0-9a-f]{12}", report["tile_version"])


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
    assert (site / "tiles" / "lidar" / "meta.json").is_file()
    assert re.search("area.json", capsys.readouterr().out)




def test_lidar_intensity_white_point(tmp_path):
    import numpy as np

    xs = np.array([0.0, 50.0, 0.0, 50.0])
    ys = np.array([0.0, 0.0, 50.0, 50.0])
    intensity = np.array([0.0, 30.0 / 60.0, 60.0 / 60.0, 110.0 / 60.0])
    intensity = np.clip(intensity, 0.0, 1.0)
    grid = _grid_from_points(xs, ys, 0.05)
    lidar = _bincount_intensity(xs, ys, intensity, grid)
    filled = lidar[..., 3] == 255
    assert sorted(lidar[filled, 0].tolist()) == [0, 127, 255, 255]


def test_stale_tiles_removed(runs, tmp_path):
    store, run_ids = runs
    site = tmp_path / "stale"
    # pre-create stale per-drive and high-z tiles
    stale1 = site / "tiles" / run_ids[0] / "lidar" / "meta.json"
    stale2 = site / "tiles" / "lidar" / "9" / "0" / "0.webp"
    stale1.parent.mkdir(parents=True, exist_ok=True)
    stale2.parent.mkdir(parents=True, exist_ok=True)
    stale1.write_text("{}")
    stale2.write_bytes(b"x")
    publish_runs(run_ids, site, store)
    assert not stale1.exists()
    assert not stale2.exists()


def test_tile_version_changes_on_same_size_content(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    p = out / "tiles" / "lidar" / "0" / "0" / "0.webp"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"aaaa")
    v1 = _tile_version(out)
    p.write_bytes(b"bbbb")
    v2 = _tile_version(out)
    assert v1 != v2
    assert len(v1) == 12 and all(c in "0123456789abcdef" for c in v1)


def test_bad_run_id_preserves_previous_tiles(runs, tmp_path):
    site, run_ids = _site(runs, tmp_path)
    sentinel = site / "tiles" / "lidar" / "sentinel.txt"
    sentinel.write_text("keep")
    before_files = sorted(
        p.relative_to(site / "tiles").as_posix()
        for p in (site / "tiles").rglob("*")
        if p.is_file()
    )
    with pytest.raises(FileNotFoundError):
        publish_runs([*run_ids, "no-such-run"], site, runs[0])
    assert sentinel.read_text() == "keep"
    after_files = sorted(
        p.relative_to(site / "tiles").as_posix()
        for p in (site / "tiles").rglob("*")
        if p.is_file()
    )
    assert before_files == after_files
    assert not (site / "tiles.new").exists()


def test_successful_publish_replaces_tiles(runs, tmp_path):
    site, run_ids = _site(runs, tmp_path)
    stale = site / "tiles" / "stale" / "old.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old")
    publish_runs(run_ids, site, runs[0])
    assert not stale.exists()
    assert not (site / "tiles.new").exists()
    assert (site / "tiles" / "lidar" / "meta.json").is_file()
