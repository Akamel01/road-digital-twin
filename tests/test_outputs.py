import json
import logging
from pathlib import Path

import laspy
import numpy as np
import pytest

from twin import registry
from twin.runner import StageContext
from twin.stages import outputs  # noqa: F401  (import registers the stage at collection time)

LICENCE = "Derived from nuScenes (CC BY-NC-SA 4.0). Non-commercial research demo."


def _line(x0, y0, z0, props):
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[x0, y0, z0], [x0 + 5, y0, z0]],
        },
        "properties": props,
    }


def _fc(features):
    return json.dumps({"type": "FeatureCollection", "features": features})


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """A run folder with synthetic ground, features, and facilities stage outputs."""
    rng = np.random.default_rng(0)
    base = np.array([331000.0, 4690000.0, 10.0])
    ground_xyz = base + rng.uniform(0, 20, size=(300, 3)) * [1, 1, 0.1]
    non_xyz = base + rng.uniform(0, 20, size=(50, 3)) * [1, 1, 1]

    ground_dir = tmp_path / "4_ground"
    ground_dir.mkdir()
    _write_points(ground_dir / "ground.laz", ground_xyz)
    _write_points(ground_dir / "nonground.laz", non_xyz)

    feat_dir = tmp_path / "5_features"
    feat_dir.mkdir()
    (feat_dir / "markings.geojson").write_text(
        _fc([_line(331001, 4690001, 10.0, {"id": "m1", "kind": "marking"})])
    )
    (feat_dir / "crosswalks.geojson").write_text(
        _fc([_line(331002, 4690002, 10.0, {"id": "c1"})])
    )
    (feat_dir / "curbs.geojson").write_text(
        _fc([_line(331003, 4690003, 10.1, {"id": "k1", "n_points": 40})])
    )

    load_dir = tmp_path / "1_load"
    load_dir.mkdir()
    (load_dir / "facilities.geojson").write_text(
        _fc([_line(331004, 4690004, 10.0, {"id": "int-1", "type": "intersection"})])
    )
    return tmp_path


def _write_points(path: Path, xyz: np.ndarray) -> None:
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001] * 3)
    header.offsets = xyz.min(axis=0)
    las = laspy.LasData(header)
    las.xyz = xyz
    las.write(path)


def _ctx(run_dir: Path) -> StageContext:
    (run_dir / "10_outputs").mkdir(exist_ok=True)
    return StageContext(
        run_dir=run_dir,
        scene_token="scene-test",
        seed=0,
        log=logging.getLogger("test"),
    )


def _run(run_dir: Path):
    return registry.lookup("outputs", "dxf-pdf")(_ctx(run_dir), None)


def test_registered_under_contract_name():
    assert registry.lookup("outputs", "dxf-pdf") is not None


def test_laz_without_colour(run_dir):
    result = _run(run_dir)

    assert result.status == "ok"
    assert result.files == ["twin.laz", "twin.geojson"]
    las = laspy.read(run_dir / "10_outputs" / "twin.laz")
    assert las.header.point_format.id == 6
    assert len(las.points) == 350
    assert set(np.unique(las.classification)) == {1, 2}
    assert int(np.sum(las.classification == 2)) == 300
    assert "32619" in las.header.parse_crs().to_wkt()
    assert result.metrics["n_points"] == 350
    assert any(
        v.description == "licence" and v.record_data.decode() == LICENCE
        for v in las.header.vlrs
    )


def test_laz_with_colour_has_rgb(run_dir):
    colour = run_dir / "6_colour"
    colour.mkdir()
    rng = np.random.default_rng(1)
    rgb = rng.integers(0, 256, size=(350, 3), dtype=np.uint8)
    observed = np.ones(350, dtype=bool)
    observed[:10] = False
    np.savez(colour / "rgb.npz", rgb=rgb, observed=observed)

    _run(run_dir)

    las = laspy.read(run_dir / "10_outputs" / "twin.laz")
    assert las.header.point_format.id == 7
    assert np.all(las.red[10:] == rgb[10:, 0].astype(np.uint16) * 257)
    assert np.all(las.red[:10] == 0)  # unobserved stays uncoloured
    assert "32619" in las.header.parse_crs().to_wkt()


def test_geojson_layers_and_licence(run_dir):
    _run(run_dir)

    doc = json.loads((run_dir / "10_outputs" / "twin.geojson").read_text())
    assert doc["type"] == "FeatureCollection"
    assert doc["crs"]["properties"]["name"] == "EPSG:32619"
    assert doc["licence"] == LICENCE
    layers = {f["properties"]["layer"] for f in doc["features"]}
    assert layers == {"markings", "crosswalks", "curbs", "facilities"}
    curb = next(f for f in doc["features"] if f["properties"]["id"] == "k1")
    assert curb["properties"]["n_points"] == 40
    assert len(curb["geometry"]["coordinates"][0]) == 3  # 3D kept


def test_curbs_absent(run_dir):
    (run_dir / "5_features" / "curbs.geojson").unlink()

    result = _run(run_dir)

    assert result.status == "ok"
    doc = json.loads((run_dir / "10_outputs" / "twin.geojson").read_text())
    layers = {f["properties"]["layer"] for f in doc["features"]}
    assert "curbs" not in layers
    assert layers == {"markings", "crosswalks", "facilities"}
    assert result.metrics["n_features"] == 3


def test_surface_fallback_when_laz_missing(run_dir):
    (run_dir / "4_ground" / "ground.laz").unlink()
    xyz = np.array([[331000.0, 4690000.0, 10.0], [331000.5, 4690000.0, 10.0]])
    np.savez(
        run_dir / "4_ground" / "surface.npz", x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2]
    )

    result = _run(run_dir)

    assert result.status == "ok"
    las = laspy.read(run_dir / "10_outputs" / "twin.laz")
    assert len(las.points) == 2 + 50  # surface cells plus non-ground


def test_missing_ground_fails_cleanly(run_dir):
    (run_dir / "4_ground" / "ground.laz").unlink()
    with pytest.raises(FileNotFoundError):
        _run(run_dir)


def test_colour_length_mismatch_raises(run_dir):
    colour = run_dir / "6_colour"
    colour.mkdir()
    np.savez(
        colour / "rgb.npz", rgb=np.zeros((5, 3), np.uint8), observed=np.ones(5, bool)
    )
    with pytest.raises(ValueError):
        _run(run_dir)
